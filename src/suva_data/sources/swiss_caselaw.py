"""Swiss Case Law (Hugging Face) source adapter: tier 3 (docs/DATA_LAYER.md 3.4, 4, 6, 7).

`fetch` verifies the two pinned originals in RAW_DIR and writes the window subset to SNAPSHOT_DIR.
`parse` reads only that subset. Nothing is cleaned, collapsed or rejected here: the reconciler does that.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download

from .. import config
from ..config import Window
from ..models import SourceRecord, division_of, normalise_docket

BGER_REPO_FILE = "data/bger.parquet"
STATUTES_REPO_FILE = "graph/statute_references.parquet"
# Where each repo file lives under RAW_DIR/swiss_caselaw/<revision>/.
RAW_LAYOUT = {BGER_REPO_FILE: "bger.parquet", STATUTES_REPO_FILE: "graph/statute_references.parquet"}

BGER_SNAPSHOT = "bger_window.parquet"
STATUTES_SNAPSHOT = "statute_references_window.parquet"

TEXT_COLUMN = "full_text"
KEY_COLUMNS = ["decision_id", "docket_number", "decision_date"]
STATUTE_SORT = ["decision_id", "law_code", "article", "paragraph", "mention_count"]
ROW_GROUP_SIZE = 500
_MARKER = ".sha256_verified.json"
_HASH_CHUNK = 8 * 1024 * 1024


class ChecksumMismatch(RuntimeError):
    """A pinned original does not have the sha256 recorded in config.SWISS_CASELAW_FILES."""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_HASH_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def _iso_date(value) -> str | None:
    """'2025-12-11' or '2025-12-11T00:00:00' -> '2025-12-11'. None if it is not a date."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    if not isinstance(value, str):
        return None
    head = value.strip()[:10]
    try:
        date.fromisoformat(head)
    except ValueError:
        return None
    return head


def _jsonable(value):
    """Plain JSON types only; NaN becomes None."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) else value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "item"):  # numpy scalar
        return _jsonable(value.item())
    return str(value)


def _blank(value) -> bool:
    return (
        value is None
        or (isinstance(value, float) and math.isnan(value))
        or (isinstance(value, str) and not value.strip())
    )


def _write_deterministic(table: pa.Table, path: Path) -> None:
    """Same table -> same bytes: no schema metadata, fixed codec, fixed row groups, atomic replace."""
    table = table.replace_schema_metadata(None).combine_chunks()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    pq.write_table(
        table,
        tmp,
        compression="zstd",
        compression_level=3,
        row_group_size=ROW_GROUP_SIZE,
        use_dictionary=True,
        write_statistics=True,
        version="2.6",
        data_page_version="1.0",
        store_schema=False,
    )
    os.replace(tmp, path)


class SwissCaselawAdapter:
    """models.SourceAdapter for the pinned Hugging Face dataset."""

    name = config.SWISS_CASELAW

    def __init__(self, raw_dir: Path | str | None = None, snapshot_dir: Path | str | None = None) -> None:
        self.raw_dir = Path(raw_dir) if raw_dir is not None else config.RAW_DIR
        self.snapshot_dir = Path(snapshot_dir) if snapshot_dir is not None else config.SNAPSHOT_DIR
        # Filled by parse(): rows whose docket_number is not a BGer case number. Never silently dropped.
        self.unparsable_dockets: list[dict] = []
        # Filled by fetch() and parse(): counts, so every row stays accounted for.
        self.fetch_stats: dict = {}
        self.parse_stats: dict = {}

    # --- paths ------------------------------------------------------------------------------------
    @property
    def revision_dir(self) -> Path:
        return self.raw_dir / self.name / config.SWISS_CASELAW_REVISION

    def raw_path(self, repo_file: str) -> Path:
        return self.revision_dir / RAW_LAYOUT[repo_file]

    @property
    def bger_snapshot(self) -> Path:
        return self.snapshot_dir / self.name / BGER_SNAPSHOT

    @property
    def statutes_snapshot(self) -> Path:
        return self.snapshot_dir / self.name / STATUTES_SNAPSHOT

    # --- originals --------------------------------------------------------------------------------
    def _download(self, repo_file: str) -> None:
        target = self.raw_path(repo_file)
        staging = self.revision_dir / ".download"
        got = hf_hub_download(
            repo_id=config.SWISS_CASELAW_REPO,
            filename=repo_file,
            repo_type="dataset",
            revision=config.SWISS_CASELAW_REVISION,
            local_dir=staging,
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(got), str(target))
        shutil.rmtree(staging, ignore_errors=True)

    def _verify(self, repo_file: str) -> None:
        """Compare sha256 with the pinned value. The result is cached per (size, mtime) in a marker file."""
        path, expected = self.raw_path(repo_file), config.SWISS_CASELAW_FILES[repo_file]
        marker_path = self.revision_dir / _MARKER
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            marker = {}
        stat = path.stat()
        seen = marker.get(repo_file) or {}
        if (
            seen.get("size") == stat.st_size
            and seen.get("mtime_ns") == stat.st_mtime_ns
            and seen.get("sha256") == expected
        ):
            return
        actual = _sha256(path)
        if actual != expected:
            raise ChecksumMismatch(
                f"{path}: sha256 is {actual}, expected {expected} "
                f"({config.SWISS_CASELAW_REPO}@{config.SWISS_CASELAW_REVISION}:{repo_file}). "
                "The file is corrupt or not the pinned revision; delete it to download it again."
            )
        marker[repo_file] = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": actual}
        marker_path.write_text(json.dumps(marker, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def ensure_originals(self) -> None:
        for repo_file in config.SWISS_CASELAW_FILES:
            if not self.raw_path(repo_file).exists():
                self._download(repo_file)
            self._verify(repo_file)

    # --- fetch ------------------------------------------------------------------------------------
    def _select_rows(self, window: Window, extra_dockets: frozenset[str]) -> pa.Table:
        """Window rows + extra dockets, all columns. Reads the text only of row groups that hold a wanted row."""
        source = pq.ParquetFile(self.raw_path(BGER_REPO_FILE))
        parts, scanned, by_window, by_extra_only = [], 0, 0, 0
        for i in range(source.metadata.num_row_groups):
            keys = source.read_row_group(i, columns=KEY_COLUMNS)
            scanned += keys.num_rows
            wanted = []
            for docket, decided in zip(
                keys["docket_number"].to_pylist(), keys["decision_date"].to_pylist(), strict=True
            ):
                in_window = window.contains(_iso_date(decided))
                is_extra = not in_window and bool(extra_dockets) and normalise_docket(docket) in extra_dockets
                by_window += in_window
                by_extra_only += is_extra
                wanted.append(in_window or is_extra)
            if any(wanted):
                parts.append(source.read_row_group(i).filter(pa.array(wanted, type=pa.bool_())))
        table = pa.concat_tables(parts) if parts else source.schema_arrow.empty_table()
        self.fetch_stats = {"rows_scanned": scanned, "rows_in_window": by_window, "rows_extra_only": by_extra_only}
        return table.sort_by([("decision_id", "ascending")])

    def fetch(self, window: Window, extra_dockets: frozenset[str] = frozenset()) -> list[str]:
        self.ensure_originals()

        rulings = self._select_rows(window, extra_dockets)
        _write_deterministic(rulings, self.bger_snapshot)

        ids = pc.unique(rulings["decision_id"])
        statutes = pq.read_table(self.raw_path(STATUTES_REPO_FILE), filters=pc.field("decision_id").isin(ids))
        statutes = statutes.sort_by([(c, "ascending") for c in STATUTE_SORT if c in statutes.column_names])
        _write_deterministic(statutes, self.statutes_snapshot)

        self.fetch_stats |= {
            "rows_written": rulings.num_rows,
            "statute_rows_written": statutes.num_rows,
            "decisions_with_statutes": pc.count_distinct(statutes["decision_id"]).as_py(),
        }
        return [f"{self.name}/{BGER_SNAPSHOT}", f"{self.name}/{STATUTES_SNAPSHOT}"]

    # --- parse ------------------------------------------------------------------------------------
    def parse(self, window: Window, extra_dockets: frozenset[str] = frozenset()) -> Iterator[SourceRecord]:
        self.unparsable_dockets = []
        stats = {"rows_read": 0, "records": 0, "not_selected": 0, "unparsable_docket": 0}
        self.parse_stats = stats
        raw_file = f"{self.name}/{BGER_SNAPSHOT}"
        previous_key = None
        for batch in pq.ParquetFile(self.bger_snapshot).iter_batches(batch_size=ROW_GROUP_SIZE):
            for row in batch.to_pylist():
                stats["rows_read"] += 1
                key = row["decision_id"]
                if previous_key is not None and key <= previous_key:
                    raise ValueError(f"{raw_file} is not strictly sorted by decision_id at {key!r}; run fetch again")
                previous_key = key

                decided = _iso_date(row.get("decision_date"))
                docket = normalise_docket(row.get("docket_number"))
                if docket is None:
                    self.unparsable_dockets.append(
                        {"source_key": key, "docket_number": row.get("docket_number"), "decision_date": decided}
                    )
                    stats["unparsable_docket"] += 1
                    continue
                if not (window.contains(decided) or docket in extra_dockets):
                    stats["not_selected"] += 1
                    continue
                stats["records"] += 1
                text = row.pop(TEXT_COLUMN, None)
                yield SourceRecord(
                    source=self.name,
                    source_key=key,
                    docket=docket,
                    decision_date=decided,
                    fields=self._fields(row, docket),
                    record={k: _jsonable(v) for k, v in row.items()},
                    text=text,
                    raw_file=raw_file,
                )

    @staticmethod
    def _fields(row: dict, docket: str) -> dict:
        """Candidates for the canonical row. A key is present only when the source has a value."""
        fields: dict = {"division": division_of(docket)}
        for target, column in (
            ("language", "language"),
            ("area", "legal_area"),
            ("outcome", "outcome"),
            ("official_url", "source_url"),
        ):
            if not _blank(row.get(column)):
                fields[target] = row[column].strip()
        if (published := _iso_date(row.get("publication_date"))) is not None:
            fields["publication_date"] = published
        if isinstance(row.get("marked_for_publication"), bool):
            fields["starred"] = row["marked_for_publication"]
        if not _blank(row.get("title")) and (subject := row["title"].strip().rstrip(",").rstrip()):
            fields["subject"] = subject
        if cited := _cited(row.get("cited_decisions")):
            fields["cited_decisions"] = cited
        return fields

    def parse_statute_refs(self) -> Iterator[dict]:
        """Statute references (derived by the dataset's author) of the decisions in the subset, in file order."""
        for batch in pq.ParquetFile(self.statutes_snapshot).iter_batches(batch_size=10_000):
            for row in batch.to_pylist():
                yield {k: _jsonable(v) for k, v in row.items()}


def _cited(raw) -> list[str] | None:
    """The column is a JSON string holding a list of case numbers. None when absent, empty or not such a list."""
    if _blank(raw):
        return None
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return None
    if not isinstance(value, list):
        return None
    cited = [v for v in value if isinstance(v, str) and v.strip()]
    return cited or None
