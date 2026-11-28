"""Swiss Case Law daily files (Hugging Face): new rulings by PUBLICATION date. Tier 3, like the pinned file.

The dataset publishes one Parquet file per day under `artifacts/parquet/deltas/YYYY-MM-DD.parquet`, holding
what its scrapers collected that day from every Swiss court. For the Federal Supreme Court its poller copies
the publication date from bger.ch's daily list. Measured on 27 Nov 2026 against our own bger.ch lists for
8 to 19 June 2026: all 370 rulings present, 369 with the same publication date, one without a date.

What this adapter relies on, and what it does not:
- A row is selected by its publication-date COLUMN, never by the date in the file name: a daily file can
  also hold a bulk re-scrape of thousands of old rulings (9 June 2026: 14,888 rows, 37 with a date).
- Federal Supreme Court rows have no publication date before about 19 May 2026, so earlier days give nothing.
- The archive has days without a file, and the files are not pinned: `fetch` records each file's sha256.
- Two column layouts exist (one until at least June 2026, one seen in November 2026). An unknown layout
  is refused, not guessed.
- The publication star is in the newer layout only and has not been checked against bger.ch. It is passed
  on as this source's value; config.NEVER_CANONICAL keeps it from becoming the canonical star.

`fetch` is the only method that uses the network. It stores, per day, only the Federal Supreme Court rows
that have a publication date. `parse` reads those stored files.
"""

from __future__ import annotations

import hashlib
import io
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .. import config
from ..models import SourceRecord, normalise_docket
from .swiss_caselaw import SwissCaselawAdapter, _blank, _iso_date, _jsonable, _write_deterministic

DAILY_DIR = "daily"
COURT = "bger"
TIMEOUT_S = 120
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Older layout -> the column names of the pinned file, which the rest of the pipeline already understands.
OLD_TO_NEW = {
    "id": "decision_id",
    "docket": "docket_number",
    "published_date": "publication_date",
    "content_text": "full_text",
    "url": "source_url",
}
REQUIRED = ("decision_id", "court", "docket_number", "decision_date", "publication_date", "full_text")


def daily_url(day: str) -> str:
    if not _DAY_RE.match(day):
        raise ValueError(f"not a day (YYYY-MM-DD): {day!r}")
    return f"https://huggingface.co/datasets/{config.SWISS_CASELAW_REPO}/resolve/main/artifacts/parquet/deltas/{day}.parquet"


def http_download(day: str) -> bytes | None:
    """One daily file, or None when the archive has no file for that day. Network."""
    request = urllib.request.Request(daily_url(day), headers={"User-Agent": config.USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return response.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def _days(start: str, end: str) -> list[str]:
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if last < first:
        raise ValueError(f"the range ends before it starts: {start} .. {end}")
    return [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]


def _to_common_layout(table: pa.Table) -> pa.Table:
    """Rename the older layout's columns; refuse a table that has neither layout's columns."""
    names = [OLD_TO_NEW.get(name, name) for name in table.column_names]
    missing = [column for column in REQUIRED if column not in names]
    if missing:
        raise ValueError(
            f"unknown daily-file layout: no column for {', '.join(missing)} (has: {', '.join(table.column_names)})"
        )
    return table.rename_columns(names)


@dataclass
class FetchReport:
    """What `fetch` did, day by day. status: 'complete', or 'incomplete' when a day failed."""

    published_from: str
    published_to: str
    status: str = "complete"
    days: list[dict] = field(default_factory=list)

    @property
    def written(self) -> list[str]:
        return [d["day"] for d in self.days if d["status"] == "written"]


class DailyFilesAdapter:
    """Rulings the Federal Supreme Court published in a date range, from the dataset's daily files."""

    name = config.SWISS_CASELAW

    def __init__(
        self, snapshot_dir: Path | str | None = None, download: Callable[[str], bytes | None] = http_download
    ) -> None:
        self.snapshot_dir = Path(snapshot_dir or config.SNAPSHOT_DIR)
        self.root = self.snapshot_dir / self.name / DAILY_DIR
        self.download = download
        self.today: str | None = None  # tests set this; None means the real date
        self.parse_stats: dict = {}
        self.repeated: list[dict] = []
        self.unparsable_dockets: list[dict] = []

    def _path(self, day: str) -> Path:
        return self.root / f"{day}.parquet"

    def _rel(self, day: str) -> str:
        return f"{self.name}/{DAILY_DIR}/{day}.parquet"

    # --- fetch ------------------------------------------------------------------------------------
    def fetch(self, published_from: str, published_to: str) -> FetchReport:
        """Store the days of the range that are not stored yet. Never raises for one bad day: it is reported.

        A day that is not over yet is not asked for (its file may be incomplete). A day without a file is
        asked for again on the next run, in case the file appears later.
        """
        report = FetchReport(published_from, published_to)
        today = self.today or date.today().isoformat()
        for day in _days(published_from, published_to):
            if day >= today:
                continue
            if self._path(day).is_file():
                report.days.append({"day": day, "status": "present"})
                continue
            try:
                raw = self.download(day)
                if raw is None:
                    report.days.append({"day": day, "status": "no_file"})
                    continue
                report.days.append({"day": day, "status": "written", **self._store(day, raw)})
            except Exception as e:  # one bad day must not lose the others
                report.status = "incomplete"
                report.days.append({"day": day, "status": "failed", "error": f"{type(e).__name__}: {e}"})
        return report

    def _store(self, day: str, raw: bytes) -> dict:
        table = _to_common_layout(pq.read_table(io.BytesIO(raw)))
        courts = table.column("court").to_pylist()
        published = table.column("publication_date").to_pylist()
        ours = [court == COURT for court in courts]
        keep = [is_ours and not _blank(p) for is_ours, p in zip(ours, published, strict=True)]
        kept = table.filter(pa.array(keep)).sort_by("decision_id")
        _write_deterministic(kept, self._path(day))
        return {
            "rows": table.num_rows,
            "kept": kept.num_rows,
            "without_publication_date": sum(ours) - kept.num_rows,
            "other_courts": table.num_rows - sum(ours),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
        }

    # --- parse ------------------------------------------------------------------------------------
    def parse(self, published_from: str, published_to: str) -> Iterator[SourceRecord]:
        """Offline. One record per ruling published in the range (both ends included), sorted by source key.

        A ruling that appears in more than one stored daily file is taken from the earliest file; later
        copies are counted in `parse_stats["repeats"]` and listed in `repeated`, never merged in.
        """
        _days(published_from, published_to)  # validates the range
        stats = {"rows_read": 0, "records": 0, "outside_range": 0, "repeats": 0, "unparsable_docket": 0}
        self.parse_stats, self.repeated, self.unparsable_dockets = stats, [], []
        records: dict[str, SourceRecord] = {}
        for path in sorted(self.root.glob("*.parquet")):
            day = path.stem
            for row in pq.read_table(path).to_pylist():
                stats["rows_read"] += 1
                key = row["decision_id"]
                published = _iso_date(row.get("publication_date"))
                docket = normalise_docket(row.get("docket_number"))
                if docket is None:
                    stats["unparsable_docket"] += 1
                    self.unparsable_dockets.append(
                        {"source_key": key, "docket": row.get("docket_number"), "daily_file": day}
                    )
                    continue
                if published is None or not (published_from <= published <= published_to):
                    stats["outside_range"] += 1
                    continue
                if key in records:
                    stats["repeats"] += 1
                    self.repeated.append({"source_key": key, "daily_file": day})
                    continue
                text = row.pop("full_text", None)
                records[key] = SourceRecord(
                    source=self.name,
                    source_key=key,
                    docket=docket,
                    decision_date=_iso_date(row.get("decision_date")),
                    fields=SwissCaselawAdapter._fields(row, docket),
                    record={"daily_file": day, **{k: _jsonable(v) for k, v in row.items()}},
                    text=text,
                    raw_file=self._rel(day),
                )
        stats["records"] = len(records)
        for key in sorted(records):
            yield records[key]
