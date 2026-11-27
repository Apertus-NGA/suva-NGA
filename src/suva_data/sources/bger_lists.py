"""Source adapter for the bger.ch "Neue Entscheide" daily publication lists (tier 1).

One list per weekday. Each list gives, per ruling: decision date, case number, link to the full
text, a publication star (BGE candidate), subject area (Sachgebiet) and a subject line. The list's
own date is the ruling's publication date. See docs/ARCHITECTURE.md 3.3, 4 and 6.1.

Snapshot layout: ``SNAPSHOT_DIR/bger_list/YYYYMMDD.html``, one file per requested calendar day,
stored as UTF-8. A file with an empty body is evidence that the day had no list (weekends).

Quirks handled here:
- the pages declare UTF-8 but are cp1252 (decoded on fetch, stored as UTF-8);
- the publication star is a ``*`` appended to the subject area inside ``<CITE>``;
- the server omits its TLS intermediate certificate: we add the published DigiCert intermediate
  to the default trust store (verification stays on);
- the firewall (Imperva) answers HTTP 403/429 or a page containing "Incapsula". Such a page is
  never written to disk, and `fetch` stops at the first one.

`parse` is offline. `fetch` is the only code that uses the network.
"""

from __future__ import annotations

import html
import re
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Iterator

from .. import config
from ..config import Window
from ..models import DOCKET_RE, SourceRecord, division_of, normalise_docket

URL = "https://www.bger.ch/ext/eurospider/live/de/php/aza/http/index_aza.php?date={d:%Y%m%d}&lang=de&mode=news"
BLOCK_MARKER = "Incapsula"
BLOCK_HTTP_CODES = (403, 429)
DEFAULT_LOOKAHEAD_DAYS = 92  # rulings are published up to ~2 months after the decision (max seen: 56 days)
DEFAULT_DELAY_S = 2.0
MAX_CONSECUTIVE_ERRORS = 3  # non-block failures in a row before `fetch` gives up

_FILE_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})\.html$")


class BlockedError(RuntimeError):
    """bger.ch's firewall refused the request. Stop and retry later; do not hammer."""


@dataclass
class Entry:
    """One row of a list page, as `parse_day` reads it ('' = not present on the page)."""

    list_date: str  # publication day (the list the ruling appeared on), ISO
    decision_date: str  # ISO
    case: str  # raw case string as printed, e.g. 8C_72/2025
    division: str  # e.g. 8C
    starred: bool  # marked for publication (BGE candidate)
    area: str  # Sachgebiet without the star, e.g. "Unfallversicherung" / "Assurance-accidents"
    subject: str  # detail line under the area
    url: str


@dataclass(frozen=True)
class FetchResult:
    """Outcome of the last `BgerListAdapter.fetch` call (also returned by `fetch_lists`)."""

    status: str  # 'complete' | 'blocked' | 'incomplete' (non-block errors left gaps)
    written: tuple[str, ...] = ()  # paths relative to SNAPSHOT_DIR, in fetch order
    requested: int = 0  # network requests made
    already_present: int = 0  # needed days that were already in the snapshot
    blocked_on: str | None = None  # ISO day of the request that was blocked
    remaining: tuple[str, ...] = ()  # needed ISO days still missing afterwards
    errors: tuple[tuple[str, str], ...] = ()  # (ISO day, message) for non-block failures
    detail: str = ""


@dataclass(frozen=True)
class Coverage:
    """What the snapshot holds. 'Missing' means: no snapshot file for that weekday (never fetched)."""

    first_list_date: str | None  # first / last day that has a real list
    last_list_date: str | None
    lists: int  # days with a real list
    missing_weekdays_in_range: int  # weekdays between first and last list date without a snapshot file
    weekdays_without_list_in_range: tuple[str, ...]  # fetched weekdays with no usable list (empty or wrong page)
    window_from: str  # the publication-date range a window needs: decision_from … decision_to + look-ahead
    window_to: str
    window_missing_weekdays: tuple[str, ...]  # weekdays of that range without a snapshot file

    def as_dict(self) -> dict:
        return asdict(self)


# --- parsing ----------------------------------------------------------------------------------


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def _iso(dmy: str) -> str:
    d, m, y = dmy.split(".")
    return f"{y}-{m}-{d}"


def parse_day(page: str) -> tuple[str | None, list[Entry]]:
    """Parse one list page. Returns (list date as ISO or None, entries in page order)."""
    m = re.search(r"Liste der am(?:&nbsp;|\s|<b>)*(\d{2}\.\d{2}\.\d{4})", page)
    list_date = _iso(m.group(1)) if m else None
    entries: list[Entry] = []
    current: dict | None = None
    for row in re.findall(r"<TR\b[^>]*>(.*?)</TR>", page, flags=re.S | re.I):
        cells = re.findall(r"<TD\b[^>]*>(.*?)</TD>", row, flags=re.S | re.I)
        link = re.search(r'<A HREF="([^"]*highlight_docid=aza://[^"]*)"[^>]*>(.*?)</A>', row, flags=re.S | re.I)
        if link:
            if current:
                entries.append(Entry(**current))
            texts = [_clean(c) for c in cells]
            dec = next((t for t in texts if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", t)), "")
            case = _clean(link.group(2))
            area = re.search(r"<CITE>(.*?)</CITE>", row, flags=re.S | re.I)
            current = dict(
                list_date=list_date or "",
                decision_date=_iso(dec) if dec else "",
                case=case,
                division=case.split("_")[0],
                starred="*" in "".join(t for t in texts if t not in (dec, case)),
                # the publication star is appended to the area name, e.g. "Invalidenversicherung*"
                area=_clean(area.group(1)).rstrip("*").strip() if area else "",
                subject="",
                url=html.unescape(link.group(1)),
            )
        elif current is not None:
            detail = " ".join(t for t in (_clean(c) for c in cells) if t)
            if detail:
                current["subject"] = (current["subject"] + " " + detail).strip()
    if current:
        entries.append(Entry(**current))
    return list_date, entries


def _valid_iso(s: str) -> bool:
    try:
        date.fromisoformat(s)
    except ValueError:
        return False
    return len(s) == 10


# --- network ----------------------------------------------------------------------------------


def ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(str(config.CERT_INTERMEDIATE))
    return ctx


def fetch_day(
    d: date,
    snapshot_dir: Path | None = None,
    *,
    ctx: ssl.SSLContext | None = None,
    refresh: bool = False,
    timeout: float = 30,
) -> tuple[str, bool]:
    """Return (page html, fetched_from_network) for one day; reads the snapshot first.

    Raises BlockedError on HTTP 403/429 or a firewall page; nothing is written in that case.
    """
    directory = Path(snapshot_dir) if snapshot_dir else config.SNAPSHOT_DIR / config.BGER_LIST
    path = directory / f"{d:%Y%m%d}.html"
    if path.exists() and not refresh:
        return path.read_text(encoding="utf-8"), False
    req = urllib.request.Request(URL.format(d=d), headers={"User-Agent": config.USER_AGENT})
    try:
        with urllib.request.urlopen(req, context=ctx or ssl_context(), timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        if e.code in BLOCK_HTTP_CODES:
            raise BlockedError(f"HTTP {e.code} for {d}") from e
        raise
    # The page declares UTF-8 but the list body is cp1252; decode strictly, then fall back.
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    # Never store a firewall block page: it would later look like a day without a list.
    # (Days without a list, e.g. weekends, legitimately return an empty body; those are stored.)
    if BLOCK_MARKER in text:
        raise BlockedError(f"firewall block page for {d}")
    directory.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return text, True


def _weekdays(start: date, end: date) -> Iterator[date]:
    d = start
    while d <= end:
        if d.weekday() < 5:  # no lists are published on weekends (verified Jul 2025 – Jun 2026)
            yield d
        d += timedelta(days=1)


# --- adapter ----------------------------------------------------------------------------------


@dataclass
class BgerListAdapter:
    """models.SourceAdapter for the daily lists.

    After `parse`, `problems` lists everything that was read but not emitted or not clean
    (dicts with 'kind', 'raw_file' and details), so every page and entry stays accounted for:
      list_date_mismatch   page whose own list date is missing or differs from its filename: skipped
      block_page           a firewall page found in the snapshot: skipped
      unexpected_file      a file in the snapshot dir that is not YYYYMMDD.html: skipped
      invalid_docket       entry whose case string is not a BGer case number: skipped
      docket_normalised    entry emitted, but its case string was not in canonical form
      invalid_decision_date / missing_decision_date   entry without a usable decision date
                           (emitted with decision_date=None only if its docket is in extra_dockets)
      duplicate_source_key the same docket twice on one list: both emitted, the later ones
                           with '#2', '#3' appended to the source_key
    After `fetch`, `last_fetch` holds a FetchResult (status 'complete' | 'blocked' | 'incomplete').
    """

    snapshot_dir: Path | None = None  # default: config.SNAPSHOT_DIR / config.BGER_LIST
    lookahead_days: int = DEFAULT_LOOKAHEAD_DAYS
    delay_s: float = DEFAULT_DELAY_S
    today: date | None = None  # default: date.today(); `fetch` never requests today or later
    name: str = config.BGER_LIST
    problems: list[dict] = field(default_factory=list)
    last_fetch: FetchResult | None = None

    def __post_init__(self) -> None:
        self.snapshot_dir = Path(self.snapshot_dir) if self.snapshot_dir else config.SNAPSHOT_DIR / config.BGER_LIST

    # -- snapshot access --

    def _rel(self, file_day: str) -> str:
        return f"{self.name}/{file_day.replace('-', '')}.html"

    def _files(self, report: list[dict] | None = None) -> dict[str, Path]:
        """ISO day -> snapshot file, sorted by day."""
        out: dict[str, Path] = {}
        if not self.snapshot_dir.is_dir():
            return out
        for p in sorted(self.snapshot_dir.iterdir()):
            m = _FILE_RE.match(p.name)
            if m and _valid_iso("-".join(m.groups())):
                out["-".join(m.groups())] = p
            elif report is not None and p.is_file() and not p.name.startswith(".") and p.suffix != ".part":
                report.append({"kind": "unexpected_file", "raw_file": f"{self.name}/{p.name}"})
        return out

    def _lists(self, report: list[dict] | None = None) -> Iterator[tuple[str, list[Entry]]]:
        """(ISO day, entries) for every snapshot page that is a real list for its own day."""
        for day, path in self._files(report).items():
            page = path.read_text(encoding="utf-8")
            if not page.strip():
                continue  # a day without a list
            problem = None
            if BLOCK_MARKER in page:
                problem = {"kind": "block_page"}
            else:
                list_date, entries = parse_day(page)
                # The site may serve a different day for dates without a list; only keep exact matches.
                if list_date != day:
                    problem = {"kind": "list_date_mismatch", "file_date": day, "list_date": list_date, "entries": len(entries)}
            if problem:
                if report is not None:
                    report.append({**problem, "raw_file": self._rel(day)})
                continue
            yield day, entries

    # -- SourceAdapter --

    def parse(self, window: Window, extra_dockets: frozenset[str] = frozenset()) -> Iterator[SourceRecord]:
        """Offline. One record per list entry decided in the window or whose docket is in extra_dockets.

        A ruling that appears on several lists yields several records. Sorted by source_key.
        Runs eagerly, so `problems` is complete as soon as this returns.
        """
        self.problems = problems = []
        records: list[SourceRecord] = []
        seen: dict[str, int] = {}
        for day, entries in self._lists(problems):
            raw_file = self._rel(day)
            for e in entries:
                where = {"raw_file": raw_file, "list_date": day, "case": e.case}
                docket = normalise_docket(e.case)
                if docket is None or not DOCKET_RE.match(docket):
                    problems.append({"kind": "invalid_docket", **where, "decision_date": e.decision_date or None})
                    continue
                if docket != e.case:
                    problems.append({"kind": "docket_normalised", **where, "docket": docket})
                decision_date: str | None = e.decision_date or None
                if decision_date is None:
                    problems.append({"kind": "missing_decision_date", **where})
                elif not _valid_iso(decision_date):
                    problems.append({"kind": "invalid_decision_date", **where, "decision_date": decision_date})
                    decision_date = None
                if not (window.contains(decision_date) or docket in extra_dockets):
                    continue
                key = f"{day}:{docket}"
                seen[key] = seen.get(key, 0) + 1
                if seen[key] > 1:
                    problems.append({"kind": "duplicate_source_key", **where, "source_key": key})
                    key = f"{key}#{seen[key]}"
                fields: dict = {"publication_date": day, "starred": e.starred, "division": division_of(docket)}
                for k, v in (("area", e.area), ("subject", e.subject), ("official_url", e.url)):
                    if v:
                        fields[k] = v
                record = {k: v for k, v in asdict(e).items() if v != ""}
                record["list_date"] = day
                records.append(
                    SourceRecord(
                        source=self.name,
                        source_key=key,
                        docket=docket,
                        decision_date=decision_date,
                        fields=fields,
                        record=record,
                        text=None,
                        raw_file=raw_file,
                    )
                )
        records.sort(key=lambda r: r.source_key)
        return iter(records)

    def needed_days(self, window: Window, lookahead_days: int | None = None) -> list[date]:
        """Weekdays whose list can hold a ruling decided in the window: from … to + look-ahead."""
        la = self.lookahead_days if lookahead_days is None else lookahead_days
        start = date.fromisoformat(window.decision_from)
        return list(_weekdays(start, date.fromisoformat(window.decision_to) + timedelta(days=la)))

    def fetch(self, window: Window, extra_dockets: frozenset[str] = frozenset()) -> list[str]:
        """Download the missing lists. Returns the relative paths written; details in `last_fetch`.

        Sequential, `delay_s` between requests, days already in the snapshot are skipped. Stops at
        the first firewall block (status 'blocked') instead of raising; a block page is never
        written. Days that are not over yet (today and later) are not requested, because an empty
        answer would be stored as "no list". `extra_dockets` cannot be looked up by case number on
        this source and is ignored: their lists are found only if they fall in the date range.
        """
        today = self.today or date.today()
        present = self._files()
        needed = [d for d in self.needed_days(window) if d < today]
        todo = [d for d in needed if d.isoformat() not in present]
        written: list[str] = []
        errors: list[tuple[str, str]] = []
        status, blocked_on, detail, requested, consecutive = "complete", None, "", 0, 0
        ctx = ssl_context() if todo else None
        for d in todo:
            if requested:
                time.sleep(self.delay_s)
            requested += 1
            try:
                fetch_day(d, self.snapshot_dir, ctx=ctx)
            except BlockedError as e:
                status, blocked_on, detail = "blocked", d.isoformat(), str(e)
                break
            except Exception as e:  # report the gap and go on; give up if the site keeps failing
                errors.append((d.isoformat(), f"{type(e).__name__}: {e}"))
                status, consecutive = "incomplete", consecutive + 1
                if consecutive >= MAX_CONSECUTIVE_ERRORS:
                    detail = f"stopped after {consecutive} consecutive errors"
                    break
                continue
            consecutive = 0
            written.append(self._rel(d.isoformat()))
        done = set(written)
        self.last_fetch = FetchResult(
            status=status,
            written=tuple(written),
            requested=requested,
            already_present=len(needed) - len(todo),
            blocked_on=blocked_on,
            remaining=tuple(d.isoformat() for d in todo if self._rel(d.isoformat()) not in done),
            errors=tuple(errors),
            detail=detail,
        )
        return written

    # -- reporting --

    def coverage(self, window: Window = config.DEFAULT_WINDOW, lookahead_days: int | None = None) -> Coverage:
        """Offline summary of which lists the snapshot holds, for the data-quality report."""
        present = self._files()
        listed = [day for day, _ in self._lists()]
        first, last = (listed[0], listed[-1]) if listed else (None, None)
        missing, without_list = 0, []
        if listed:
            have = set(listed)
            for d in _weekdays(date.fromisoformat(first), date.fromisoformat(last)):
                if d.isoformat() not in present:
                    missing += 1
                elif d.isoformat() not in have:
                    without_list.append(d.isoformat())
        needed = self.needed_days(window, lookahead_days)
        la = self.lookahead_days if lookahead_days is None else lookahead_days
        return Coverage(
            first_list_date=first,
            last_list_date=last,
            lists=len(listed),
            missing_weekdays_in_range=missing,
            weekdays_without_list_in_range=tuple(without_list),
            window_from=window.decision_from,
            window_to=(date.fromisoformat(window.decision_to) + timedelta(days=la)).isoformat(),
            window_missing_weekdays=tuple(d.isoformat() for d in needed if d.isoformat() not in present),
        )


def fetch_lists(window: Window = config.DEFAULT_WINDOW, **adapter_kwargs) -> FetchResult:
    """Convenience: run `BgerListAdapter(**adapter_kwargs).fetch(window)` and return its FetchResult."""
    adapter = BgerListAdapter(**adapter_kwargs)
    adapter.fetch(window)
    return adapter.last_fetch
