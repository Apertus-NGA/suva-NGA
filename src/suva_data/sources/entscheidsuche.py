"""entscheidsuche.ch source adapter (tier 2): bulk search API -> deterministic page files -> SourceRecords.

docs/DATA_LAYER.md 3.5, 4, 6, 7. `fetch` is the only method that uses the network; it talks to
config.ENTSCHEIDSUCHE_SEARCH_URL only, sequentially, with a pause between requests.

Snapshot layout (relative to SNAPSHOT_DIR):
    entscheidsuche/<YYYY-MM>/page_<NNN>.json   all CH_BGer rulings decided in that month (clipped to the window)
    entscheidsuche/extras/page_<NNN>.json      rulings outside the window, found by case number
    entscheidsuche/documents/<_id>.html        raw per-ruling HTML, only for hits whose API text is truncated

Every page file is {"hits": [{"_id", "_source"}, ...], "query": <filter>, "total": n}. Within one
directory the hits are sorted by _id and then cut into pages, so the bytes do not depend on the order in
which the server returned them.

The search API cuts `attachment.content` at 100,000 characters. For those hits `fetch` also saves the
per-ruling .html file (raw bytes), and `parse` takes the text from it (record["text_origin"] says which).
"""

from __future__ import annotations

import calendar
import copy
import json
import os
import re
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterator

from .. import config, textnorm
from ..config import Window
from ..models import SourceRecord, division_of, normalise_docket

PAGE_SIZE = 100  # hits per request and per saved file
DOCKET_BATCH = 50  # case numbers per `terms` query
MAX_RETRIES = 2  # after the first attempt, on 5xx / timeout
TIMEOUT_S = 90
SORT = [{"date": "asc"}, {"id": "asc"}]  # verified 2026-11-27: both sortable, accepted by search_after
EXTRAS_DIR = "extras"
DOCUMENTS_DIR = "documents"
DOCS_URL = "https://entscheidsuche.ch/docs/"
API_CONTENT_LIMIT = 100000  # attachment.content_length of a hit whose content was cut by the search API

_ID_RE = re.compile(r"^CH_BGer_\d+_(?P<docket>.+)_(?P<date>\d{4}-\d{2}-\d{2})$")
_MONTH_DIR_RE = re.compile(r"^\d{4}-\d{2}$")
_LANGUAGES = ("de", "fr", "it")

# (url, body or None for GET, headers, timeout seconds) -> (HTTP status, response body)
HttpFn = Callable[[str, bytes | None, dict, float], tuple[int, bytes]]


class EntscheidsucheError(RuntimeError):
    """The server answered, but not with something we can use."""


class EntscheidsucheRefused(EntscheidsucheError):
    """HTTP 403 / 429: the site is refusing us. Stop; do not retry."""


class EntscheidsucheNotFound(EntscheidsucheError):
    """HTTP 404 for a per-ruling file."""


class _SearchRejected(EntscheidsucheError):
    """Elasticsearch returned an error document (it does so with HTTP 200)."""


def urllib_http(url: str, body: bytes | None, headers: dict, timeout: float) -> tuple[int, bytes]:
    """Default HTTP function. Returns the status instead of raising on 4xx/5xx; raises OSError on timeouts."""
    request = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def month_ranges(window: Window) -> list[tuple[str, str, str]]:
    """[('2025-10', '2025-10-01', '2025-10-31'), ...] for every month overlapping the window, clipped to it."""
    out = []
    year, month = int(window.decision_from[:4]), int(window.decision_from[5:7])
    while f"{year:04d}-{month:02d}" <= window.decision_to[:7]:
        label = f"{year:04d}-{month:02d}"
        next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
        gte = max(f"{label}-01", window.decision_from)
        lte = min(f"{label}-{calendar.monthrange(year, month)[1]:02d}", window.decision_to)
        out.append((label, gte, lte))
        year, month = next_year, next_month
    return out


def month_query(gte: str, lte: str) -> dict:
    return {"bool": {"filter": [{"term": {"hierarchy": "CH_BGer"}}, {"range": {"date": {"gte": gte, "lte": lte}}}]}}


def extras_queries(window: Window, extra_dockets: frozenset[str]) -> list[dict]:
    """One query per batch of case numbers; rulings decided inside the window are left to the month queries."""
    dockets = sorted(extra_dockets)
    return [
        {
            "bool": {
                "filter": [{"term": {"hierarchy": "CH_BGer"}}, {"terms": {"reference": dockets[i : i + DOCKET_BATCH]}}],
                "must_not": [{"range": {"date": {"gte": window.decision_from, "lte": window.decision_to}}}],
            }
        }
        for i in range(0, len(dockets), DOCKET_BATCH)
    ]


def _canonical(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def is_truncated(source: dict) -> bool:
    """True if the search API cut this hit's text (so the per-ruling .html file is needed)."""
    attachment = source.get("attachment") if isinstance(source.get("attachment"), dict) else {}
    return (
        attachment.get("content_length") == API_CONTENT_LIMIT
        or textnorm.bad_text_reason(attachment.get("content")) == "truncated"
    )


def document_url(hit_id: str, source: dict) -> str:
    attachment = source.get("attachment") if isinstance(source.get("attachment"), dict) else {}
    url = attachment.get("content_url")
    if isinstance(url, str) and url.startswith(DOCS_URL) and url.endswith(".html"):
        return url
    return f"{DOCS_URL}CH_BGer/{hit_id}.html"


_BLOCK_TAGS = frozenset(
    "address article aside blockquote body br center dd div dl dt footer form h1 h2 h3 h4 h5 h6 head header hr html "
    "li main nav ol p pre section table tbody td tfoot th thead title tr ul".split()
)


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)  # entities arrive unescaped in handle_data
        self.parts: list[str] = []
        self.hidden = 0  # depth inside <script> / <style>

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def html_to_text(raw: bytes) -> str:
    """Text of a per-ruling .html file: tags removed, a newline at block tags, entities unescaped. Deterministic."""
    try:
        html = raw.decode("utf-8")
    except UnicodeDecodeError:
        html = raw.decode("cp1252", errors="replace")
    extractor = _TextExtractor()
    extractor.feed(html)
    extractor.close()
    return "".join(extractor.parts)


def _page_bytes(query: dict, total: int, hits: list[dict]) -> bytes:
    page = {"query": query, "total": total, "hits": hits}
    return (json.dumps(page, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")


class EntscheidsucheAdapter:
    name = config.ENTSCHEIDSUCHE

    def __init__(
        self,
        snapshot_dir: Path | str | None = None,
        delay: float = 1.0,
        http: HttpFn = urllib_http,
        sleep: Callable[[float], None] = time.sleep,
        page_size: int = PAGE_SIZE,
        search_url: str = config.ENTSCHEIDSUCHE_SEARCH_URL,
    ):
        if not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        self.snapshot_dir = Path(snapshot_dir) if snapshot_dir is not None else config.SNAPSHOT_DIR
        self.delay = delay
        self.http = http
        self.sleep = sleep
        self.page_size = page_size
        self.search_url = search_url
        self.request_count = 0
        self._last_request: float | None = None
        # Filled by fetch(): {'2025-10': 715, ..., 'extras': 23} (hits on disk per directory).
        self.fetch_totals: dict[str, int] = {}
        # Filled by parse(), for the quality report. Nothing lands here silently: see parse().
        self.undetermined: list[dict] = []  # hits without a usable case number (not yielded)
        self.docket_notes: list[dict] = []  # hits where `reference` and the id needed a decision
        self.repeated_ids: list[dict] = []  # the same _id found in a second page file (yielded once)
        self.bad_documents: list[dict] = []  # document texts that still fail textnorm.bad_text_reason (yielded)
        # Filled by fetch(): truncated hits whose .html file answered 404 (fetch carries on).
        self.documents_missing: list[dict] = []
        self.documents_needed = 0  # truncated hits seen by the last fetch()

    # ------------------------------------------------------------------ fetch

    @property
    def root(self) -> Path:
        return self.snapshot_dir / self.name

    def fetch(self, window: Window, extra_dockets: frozenset[str] = frozenset()) -> list[str]:
        written: list[str] = []
        for label, gte, lte in month_ranges(window):
            written += self._sync_dir(label, [month_query(gte, lte)])
        outside = frozenset(extra_dockets)
        if outside:
            written += self._sync_dir(EXTRAS_DIR, extras_queries(window, outside))
        written += self._sync_documents()
        return written

    def _sync_documents(self) -> list[str]:
        """Save the raw .html of every saved hit whose API text is truncated. Existing files are kept."""
        self.documents_missing, self.documents_needed = [], 0
        wanted: dict[str, str] = {}
        for path in self._page_files():
            for hit in json.loads(path.read_text(encoding="utf-8"))["hits"]:
                if is_truncated(hit["_source"]):
                    wanted[hit["_id"]] = document_url(hit["_id"], hit["_source"])
        self.documents_needed = len(wanted)
        written = []
        for hit_id in sorted(wanted):
            path = self.root / DOCUMENTS_DIR / f"{hit_id}.html"
            if path.is_file() and path.stat().st_size:
                continue
            try:
                raw = self.fetch_document(wanted[hit_id])
            except EntscheidsucheNotFound:
                self.documents_missing.append({"source_key": hit_id, "url": wanted[hit_id], "status": 404})
                continue
            if not raw.strip():
                raise EntscheidsucheError(f"empty document from {wanted[hit_id]}")
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_bytes(raw)
            os.replace(tmp, path)
            written.append(path.relative_to(self.snapshot_dir).as_posix())
        return written

    def _sync_dir(self, dirname: str, queries: list[dict]) -> list[str]:
        """Make <root>/<dirname>/ hold exactly the results of `queries`. Skips the network if it already does."""
        directory = self.root / dirname
        saved = self._saved_hit_count(directory, queries)
        if saved is not None:
            self.fetch_totals[dirname] = saved
            return []

        # Download everything for this directory first, so a failure half-way leaves no partial files.
        pages: list[tuple[dict, int, list[dict]]] = []
        for query in queries:
            total, hits = self._search_all(query)
            hits.sort(key=lambda h: h["_id"])
            for i in range(0, len(hits), self.page_size):
                pages.append((query, total, hits[i : i + self.page_size]))
            if not hits:
                pages.append((query, 0, []))  # keep the proof that the query returned nothing

        directory.mkdir(parents=True, exist_ok=True)
        for stale in directory.glob("page_*.json*"):
            stale.unlink()
        written = []
        for number, (query, total, hits) in enumerate(pages, start=1):
            path = directory / f"page_{number:03d}.json"
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_bytes(_page_bytes(query, total, hits))
            os.replace(tmp, path)
            written.append(path.relative_to(self.snapshot_dir).as_posix())
        self.fetch_totals[dirname] = sum(len(hits) for _, _, hits in pages)
        return written

    def _saved_hit_count(self, directory: Path, queries: list[dict]) -> int | None:
        """Number of saved hits if the directory completely answers `queries`, else None."""
        files = sorted(directory.glob("page_*.json"))
        if not files:
            return None
        per_query: dict[str, list[int]] = {}  # canonical query -> [total, hits saved]
        try:
            for path in files:
                page = json.loads(path.read_text(encoding="utf-8"))
                entry = per_query.setdefault(_canonical(page["query"]), [page["total"], 0])
                if entry[0] != page["total"]:
                    return None
                entry[1] += len(page["hits"])
        except (ValueError, KeyError, TypeError):
            return None
        if set(per_query) != {_canonical(q) for q in queries}:
            return None
        if any(total != count for total, count in per_query.values()):
            return None
        return sum(count for _, count in per_query.values())

    def _search_all(self, query: dict) -> tuple[int, list[dict]]:
        try:
            return self._page_through(query, use_search_after=True)
        except _SearchRejected as first:
            if not getattr(first, "after_first_page", False):
                raise
            return self._page_through(query, use_search_after=False)  # totals per query are far below 10,000

    def _page_through(self, query: dict, use_search_after: bool) -> tuple[int, list[dict]]:
        """All hits for `query` as [{'_id', '_source'}], and the server's total. Raises if they disagree."""
        hits: dict[str, dict] = {}
        total: int | None = None
        cursor = None
        received = 0
        while True:
            body: dict = {"size": self.page_size, "track_total_hits": True, "query": query, "sort": SORT}
            if received and use_search_after:
                body["search_after"] = cursor
            elif received:
                body["from"] = received
            try:
                answer = self._search(body)
            except _SearchRejected as e:
                e.after_first_page = bool(received) and use_search_after
                raise
            reported = answer["hits"]["total"]
            reported = reported["value"] if isinstance(reported, dict) else reported
            if total is not None and reported != total:
                raise EntscheidsucheError(f"total changed while paging ({total} -> {reported}) for {_canonical(query)}")
            total = reported
            page = answer["hits"]["hits"]
            for hit in page:
                hits[hit["_id"]] = {"_id": hit["_id"], "_source": hit["_source"]}
            received += len(page)
            if not page or received >= total:
                break
            cursor = page[-1].get("sort")
            if use_search_after and cursor is None:
                raise EntscheidsucheError("hits carry no sort values; cannot continue with search_after")
        if len(hits) != total:
            raise EntscheidsucheError(
                f"server reports {total} hits but {len(hits)} distinct hits were received for {_canonical(query)}"
            )
        return total, list(hits.values())

    def _search(self, body: dict) -> dict:
        status, raw = self._request(self.search_url, json.dumps(body, ensure_ascii=False).encode("utf-8"))
        try:
            answer = json.loads(raw.decode("utf-8"))
        except ValueError as e:
            raise EntscheidsucheError(f"search returned HTTP {status} with a body that is not JSON") from e
        if not isinstance(answer, dict) or "error" in answer or "hits" not in answer:
            raise _SearchRejected(f"search rejected (HTTP {status}): {raw[:300].decode('utf-8', 'replace')}")
        if answer.get("timed_out") or answer.get("_shards", {}).get("failed"):
            raise EntscheidsucheError("search answer is incomplete (timed out or failed shards)")
        return answer

    def _request(self, url: str, body: bytes | None) -> tuple[int, bytes]:
        """One polite request: pause, honest user agent, <= MAX_RETRIES retries on 5xx/timeout, stop on 403/429."""
        headers = {"User-Agent": config.USER_AGENT, "Accept": "application/json, text/html"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        problem = ""
        for attempt in range(MAX_RETRIES + 1):
            pause = self.delay * (2**attempt if attempt else 1)  # 1x, then 2x, 4x back-off
            if self._last_request is not None or attempt:
                self.sleep(pause)
            self.request_count += 1
            self._last_request = time.monotonic()
            try:
                status, raw = self.http(url, body, headers, TIMEOUT_S)
            except OSError as e:  # URLError, socket timeout, connection reset
                problem = f"{type(e).__name__}: {e}"
                continue
            if status in (403, 429):
                raise EntscheidsucheRefused(
                    f"entscheidsuche.ch refused the request (HTTP {status}) for {url}; stopping, nothing was written "
                    "for the current directory. Wait before running fetch again."
                )
            if status >= 500:
                problem = f"HTTP {status}"
                continue
            if status == 404 and body is None:
                raise EntscheidsucheNotFound(f"HTTP 404 for {url}")
            if status >= 400 and body is None:
                raise EntscheidsucheError(f"HTTP {status} for {url}")
            return status, raw
        raise EntscheidsucheError(f"giving up on {url} after {MAX_RETRIES + 1} attempts: {problem}")

    def fetch_document(self, url: str) -> bytes:
        """GET one per-ruling file (docs/CH_BGer/<id>.html|.json) with the same politeness rules. Network."""
        if not url.startswith(DOCS_URL):
            raise ValueError(f"refusing to contact another host: {url}")
        return self._request(url, None)[1]

    # ------------------------------------------------------------------ parse

    def parse(self, window: Window, extra_dockets: frozenset[str] = frozenset()) -> Iterator[SourceRecord]:
        self.undetermined, self.docket_notes, self.repeated_ids, self.bad_documents = [], [], [], []
        records: dict[str, SourceRecord] = {}
        for path in self._page_files():
            raw_file = path.relative_to(self.snapshot_dir).as_posix()
            for hit in json.loads(path.read_text(encoding="utf-8"))["hits"]:
                source_key, source = hit["_id"], hit["_source"]
                decision_date = source.get("date") or None
                docket, candidates, note = _docket_of(source_key, source)
                if not (window.contains(decision_date) or candidates & extra_dockets):
                    continue
                if source_key in records:
                    self.repeated_ids.append({"source_key": source_key, "raw_file": raw_file})
                    continue
                if note:
                    self.docket_notes.append({"source_key": source_key, "note": note, "docket": docket,
                                              "reference": source.get("reference"), "raw_file": raw_file})
                if docket is None:
                    self.undetermined.append({"source_key": source_key, "decision_date": decision_date,
                                              "reference": source.get("reference"), "raw_file": raw_file})
                    continue
                record = copy.deepcopy(source)
                attachment = record.get("attachment")
                text = attachment.pop("content", None) if isinstance(attachment, dict) else None
                document = self.root / DOCUMENTS_DIR / f"{source_key}.html"
                if document.is_file():
                    record["text_origin"] = "document_html"
                    record["api_content_length"] = len(text) if text is not None else None
                    record["document_file"] = document.relative_to(self.snapshot_dir).as_posix()
                    text = html_to_text(document.read_bytes())
                    reason = textnorm.bad_text_reason(text)
                    if reason:
                        self.bad_documents.append({"source_key": source_key, "docket": docket, "reason": reason,
                                                   "document_file": record["document_file"]})
                else:
                    record["text_origin"] = "search_api"
                fields: dict = {"division": division_of(docket)}
                if source.get("language") in _LANGUAGES:
                    fields["language"] = source["language"]
                official_url = _bger_url(record)
                if official_url:
                    fields["official_url"] = official_url
                records[source_key] = SourceRecord(
                    source=self.name,
                    source_key=source_key,
                    docket=docket,
                    decision_date=decision_date,
                    fields=fields,
                    record=record,
                    text=text,
                    raw_file=raw_file,
                )
        for source_key in sorted(records):
            yield records[source_key]

    def _page_files(self) -> list[Path]:
        """Month directories first (sorted), then extras: a ruling saved twice is taken from its month page."""
        if not self.root.is_dir():
            return []
        months = sorted(d for d in self.root.iterdir() if d.is_dir() and _MONTH_DIR_RE.match(d.name))
        directories = months + ([self.root / EXTRAS_DIR] if (self.root / EXTRAS_DIR).is_dir() else [])
        return [path for d in directories for path in sorted(d.glob("page_*.json"))]


def _docket_of(source_key: str, source: dict) -> tuple[str | None, frozenset[str], str | None]:
    """(docket, every case number this hit is known by, note for the report or None).

    Exactly one usable `reference` -> that one. Several or none -> the case number in the id decides.
    """
    reference = source.get("reference")
    reference = [reference] if isinstance(reference, str) else list(reference or [])
    from_reference = [d for d in (normalise_docket(r) for r in reference if isinstance(r, str)) if d]
    m = _ID_RE.match(source_key)
    from_id = normalise_docket(m["docket"]) if m else None
    candidates = frozenset(from_reference) | ({from_id} if from_id else frozenset())

    if len(reference) == 1 and from_reference:
        note = None if from_id == from_reference[0] else f"reference {from_reference[0]} != id {from_id}"
        return from_reference[0], candidates, note
    kind = "no reference" if not reference else f"{len(reference)} references"
    if from_id:
        suffix = "" if not from_reference or from_id in from_reference else ", id not among them"
        return from_id, candidates, f"{kind}: docket taken from id{suffix}"
    if from_reference:
        return from_reference[0], candidates, f"{kind}, id unusable: first usable reference taken"
    return None, candidates, f"{kind}: no case number found"


def _bger_url(record: dict) -> str | None:
    """The original bger.ch URL if the record carries one (entscheidsuche usually stores only an internal key)."""
    attachment = record.get("attachment") if isinstance(record.get("attachment"), dict) else {}
    for value in (record.get("url"), record.get("source"), attachment.get("source"), attachment.get("url")):
        if isinstance(value, str) and re.match(r"https?://([a-z0-9.-]+\.)?bger\.ch/", value):
            return value
    return None
