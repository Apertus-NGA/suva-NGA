"""Load snapshot files and SourceRecords into Postgres (docs/ARCHITECTURE.md 5, 6, 6.1).

Nothing is dropped here: every record with a usable (source, source_key) gets a `source_records` row.
Records that fail validation are stored with status='rejected' and a status_reason starting with 'load: '.
Both functions are idempotent and atomic (one transaction per call, see db.py for the convention).
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

import psycopg

from . import config, textnorm
from .models import DOCKET_RE, SourceRecord

log = logging.getLogger(__name__)

RAW_FILE_SOURCES = (*config.SOURCE_TIER, "suva")  # 'suva' = the xlsx / html exports in judgements/
REJECT_PREFIX = "load: "  # status_reason prefix for rejections made by this module (not by the reconciler)
BATCH_ROWS = 500
BATCH_TEXT_CHARS = 16_000_000
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --- cleaning ---------------------------------------------------------------------------------------

def _clean_str(s: str) -> str:
    """Postgres cannot store NUL; lone surrogates cannot be encoded as UTF-8 at all."""
    if "\x00" in s:
        s = s.replace("\x00", "")
    try:
        s.encode("utf-8")
    except UnicodeEncodeError:
        s = s.encode("utf-8", "replace").decode("utf-8")
    return s


def _clean_json(value):
    """A JSON-safe copy: NUL stripped, NaN / infinity -> null (jsonb has neither), tuples / sets -> lists."""
    if isinstance(value, str):
        return _clean_str(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {_clean_str(str(k)): _clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean_json(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_clean_json(v) for v in value), key=repr)
    return value


def _to_json(value) -> str:
    return json.dumps(_clean_json(value), ensure_ascii=False, allow_nan=False, default=str, sort_keys=True)


# --- raw files --------------------------------------------------------------------------------------

def _sha256_file(path: Path) -> tuple[str, int]:
    h, n = hashlib.sha256(), 0
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
            n += len(chunk)
    return h.hexdigest(), n


def register_raw_files(
    conn: psycopg.Connection, source: str, paths: Iterable[str | Path], snapshot_dir: Path | None = None
) -> dict[str, int]:
    """Upsert one `raw_files` row per snapshot file (path relative to the snapshot dir, sha256, bytes).

    `paths` may be relative to `snapshot_dir` (default: config.SNAPSHOT_DIR) or absolute inside it.
    Returns {'read', 'inserted', 'updated', 'unchanged'}. Raises on a missing file or a path outside the snapshot.
    """
    if source not in RAW_FILE_SOURCES:
        raise ValueError(f"unknown raw file source {source!r} (expected one of {RAW_FILE_SOURCES})")
    root = Path(snapshot_dir or config.SNAPSHOT_DIR).resolve()
    rows: dict[str, tuple[str, int]] = {}
    for p in paths:
        full = Path(p)
        full = (full if full.is_absolute() else root / full).resolve()
        try:
            rel = full.relative_to(root).as_posix()
        except ValueError:
            raise ValueError(f"{p} is not inside the snapshot directory {root}") from None
        rows[rel] = _sha256_file(full)

    counts = {"read": len(rows), "inserted": 0, "updated": 0, "unchanged": 0}
    rels = sorted(rows)
    with conn.transaction():
        existing = {
            path: (src, sha, size)
            for path, src, sha, size in conn.execute(
                "SELECT path, source, sha256, bytes FROM raw_files WHERE path = ANY(%s)", (rels,)
            )
        }
        for rel in rels:
            new = (source, *rows[rel])
            if rel not in existing:
                counts["inserted"] += 1
            elif existing[rel] != new:
                counts["updated"] += 1
            else:
                counts["unchanged"] += 1
                continue
            conn.execute(
                """
                INSERT INTO raw_files (source, path, sha256, bytes) VALUES (%s, %s, %s, %s)
                ON CONFLICT (path) DO UPDATE SET source = EXCLUDED.source, sha256 = EXCLUDED.sha256, bytes = EXCLUDED.bytes
                """,
                (source, rel, *rows[rel]),
            )
    return counts


# --- source records ---------------------------------------------------------------------------------

@dataclass
class _Row:
    source: str
    source_key: str
    docket: str
    decision_date: date | None
    fields_json: str
    record_json: str
    raw_file: str | None
    text: str | None
    bad_reason: str | None  # of the text; None when there is no text
    status: str  # 'loaded' | 'rejected'
    reason: str | None


def _prepare(rec: SourceRecord) -> _Row | str:
    """Validate and clean one record. Returns a storable row, or a reason string if it cannot be stored at all."""
    source, key = getattr(rec, "source", None), getattr(rec, "source_key", None)
    if source not in config.SOURCE_TIER:
        return f"unknown source {source!r}"
    key = _clean_str(key) if isinstance(key, str) else ""
    if not key.strip():
        return f"missing source_key (source {source})"

    problems: list[str] = []

    docket = rec.docket
    if not isinstance(docket, str) or not DOCKET_RE.match(docket):
        problems.append(f"bad docket {docket!r}")
    docket = _clean_str(docket) if isinstance(docket, str) else ""

    decision_date = None
    if rec.decision_date is not None:
        raw = rec.decision_date
        try:
            if not isinstance(raw, str) or not _ISO_DATE_RE.match(raw):
                raise ValueError
            decision_date = date.fromisoformat(raw)
        except ValueError:
            problems.append(f"bad decision_date {raw!r}")

    fields = rec.fields
    if not isinstance(fields, dict):
        problems.append(f"fields is {type(fields).__name__}, not a dict")
        fields = {}
    elif unknown := sorted(str(k) for k in fields if k not in config.CANONICAL_FIELDS):
        problems.append(f"unknown fields {unknown}")

    record = rec.record
    if not isinstance(record, dict):
        problems.append(f"record is {type(record).__name__}, not a dict")
        record = {}

    text = rec.text
    if text is not None:
        if not isinstance(text, str):
            problems.append(f"text is {type(text).__name__}, not a string (not stored)")
            text = None
        else:
            if "\x00" in text:
                text = text.replace("\x00", "")
            try:
                text.encode("utf-8")
            except UnicodeEncodeError:
                problems.append("text is not valid Unicode (not stored)")
                text = None

    raw_file = rec.raw_file
    if raw_file is not None and not isinstance(raw_file, str):
        raw_file = Path(raw_file).as_posix()

    return _Row(
        source=source,
        source_key=key,
        docket=docket,
        decision_date=decision_date,
        fields_json=_to_json(fields),
        record_json=_to_json(record),
        raw_file=raw_file,
        text=text,
        bad_reason=textnorm.bad_text_reason(text) if text is not None else None,
        status="rejected" if problems else "loaded",
        reason=REJECT_PREFIX + "; ".join(problems) if problems else None,
    )


def _text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _flush(conn: psycopg.Connection, batch: list[_Row], raw_ids: dict[str, int], counts: dict[str, int]) -> None:
    existing = {
        (r[0], r[1]): r[2:]
        for r in conn.execute(
            """
            SELECT sr.source, sr.source_key, sr.id, sr.docket, sr.decision_date, sr.fields, sr.record,
                   sr.raw_file_id, sr.status, sr.status_reason,
                   t.id IS NOT NULL, encode(sha256(convert_to(t.text, 'UTF8')), 'hex')
            FROM unnest(%s::text[], %s::text[]) AS k (source, source_key)
            JOIN source_records sr USING (source, source_key)
            LEFT JOIN ruling_texts t ON t.source_record_id = sr.id
            """,
            ([r.source for r in batch], [r.source_key for r in batch]),
        )
    }

    inserts: list[_Row] = []
    updates: list[tuple[int, _Row]] = []
    text_upserts: list[tuple[int | None, _Row]] = []  # id None = look it up after the insert
    text_deletes: list[int] = []
    for row in batch:
        raw_file_id = raw_ids[row.raw_file] if row.raw_file is not None else None
        old = existing.get((row.source, row.source_key))
        if old is None:
            inserts.append(row)
            if row.text is not None:
                text_upserts.append((None, row))
            if row.status == "loaded":
                counts["inserted"] += 1
            continue
        rec_id, docket, ddate, fields, record, old_raw, status, reason, has_text, text_sha = old
        new_text_sha = _text_sha(row.text) if row.text is not None else None
        content_same = (
            docket == row.docket
            and ddate == row.decision_date
            and fields == json.loads(row.fields_json)
            and record == json.loads(row.record_json)
            and old_raw == raw_file_id
            and (text_sha if has_text else None) == new_text_sha
        )
        load_rejected = status == "rejected" and (reason or "").startswith(REJECT_PREFIX)
        if row.status == "rejected":
            status_same = load_rejected and reason == row.reason
        else:
            status_same = not load_rejected  # whatever the reconciler set stays
        if content_same and status_same:
            if row.status == "loaded":
                counts["unchanged"] += 1
            continue
        # The record's own content changed: it goes back to 'loaded' and the reconciler must look at it again.
        updates.append((rec_id, row))
        if row.text is not None:
            text_upserts.append((rec_id, row))
        elif has_text:
            text_deletes.append(rec_id)
        if row.status == "loaded":
            counts["updated"] += 1

    if inserts:
        ids = {
            (s, k): i
            for s, k, i in conn.execute(
                """
                INSERT INTO source_records (source, source_key, docket, decision_date, fields, record, raw_file_id, status, status_reason)
                SELECT * FROM unnest(%s::text[], %s::text[], %s::text[], %s::date[], %s::jsonb[], %s::jsonb[],
                                     %s::bigint[], %s::text[], %s::text[])
                RETURNING source, source_key, id
                """,
                (
                    [r.source for r in inserts],
                    [r.source_key for r in inserts],
                    [r.docket for r in inserts],
                    [r.decision_date for r in inserts],
                    [r.fields_json for r in inserts],
                    [r.record_json for r in inserts],
                    [raw_ids[r.raw_file] if r.raw_file is not None else None for r in inserts],
                    [r.status for r in inserts],
                    [r.reason for r in inserts],
                ),
            )
        }
        text_upserts = [(i if i is not None else ids[(r.source, r.source_key)], r) for i, r in text_upserts]
    if updates:
        conn.execute(
            """
            UPDATE source_records sr
            SET docket = v.docket, decision_date = v.decision_date, fields = v.fields, record = v.record,
                raw_file_id = v.raw_file_id, status = v.status, status_reason = v.status_reason, ruling_id = NULL
            FROM unnest(%s::bigint[], %s::text[], %s::date[], %s::jsonb[], %s::jsonb[], %s::bigint[], %s::text[], %s::text[])
                 AS v (id, docket, decision_date, fields, record, raw_file_id, status, status_reason)
            WHERE sr.id = v.id
            """,
            (
                [i for i, _ in updates],
                [r.docket for _, r in updates],
                [r.decision_date for _, r in updates],
                [r.fields_json for _, r in updates],
                [r.record_json for _, r in updates],
                [raw_ids[r.raw_file] if r.raw_file is not None else None for _, r in updates],
                [r.status for _, r in updates],
                [r.reason for _, r in updates],
            ),
        )
    if text_deletes:
        conn.execute("DELETE FROM ruling_texts WHERE source_record_id = ANY(%s)", (text_deletes,))
    if text_upserts:
        conn.execute(
            """
            INSERT INTO ruling_texts (source_record_id, source, text, sha256_normalized, char_count, bad_reason)
            SELECT * FROM unnest(%s::bigint[], %s::text[], %s::text[], %s::text[], %s::int[], %s::text[])
            ON CONFLICT (source_record_id) DO UPDATE
            SET source = EXCLUDED.source, text = EXCLUDED.text, sha256_normalized = EXCLUDED.sha256_normalized,
                char_count = EXCLUDED.char_count, bad_reason = EXCLUDED.bad_reason,
                is_canonical = false, ruling_id = NULL
            """,
            (
                [i for i, _ in text_upserts],
                [r.source for _, r in text_upserts],
                [r.text for _, r in text_upserts],
                [textnorm.text_hash(r.text) for _, r in text_upserts],
                [len(r.text) for _, r in text_upserts],
                [r.bad_reason for _, r in text_upserts],
            ),
        )


def load_source_records(conn: psycopg.Connection, records: Iterable[SourceRecord]) -> dict[str, int]:
    """Upsert SourceRecords into `source_records` (key: source, source_key) and their texts into `ruling_texts`.

    Returns counts with  read == inserted + updated + unchanged + rejected :
      inserted / updated / unchanged  valid records, by what happened to their row
      rejected    records that failed validation (stored with status='rejected' when possible)
      not_stored  the part of `rejected` that could not be stored at all: unknown source, missing
                  source_key, or a (source, source_key) seen earlier in the same call (first one wins)
      texts       stored records that carry a text;  bad_texts: those whose text fails textnorm.bad_text_reason

    Idempotent: a record whose content is unchanged is not touched, so `ruling_id`, `status` and
    `is_canonical` set by the reconciler survive a reload. When a record's content (docket, date, fields,
    record, raw_file or text) DID change, its row is rewritten and reset to status='loaded', ruling_id NULL,
    and its text to is_canonical=false, ruling_id NULL. A text is removed when the record no longer has one.

    Raises KeyError (and writes nothing) if a record names a raw_file that is not in `raw_files`:
    call register_raw_files first.
    """
    counts = {k: 0 for k in ("read", "inserted", "updated", "unchanged", "rejected", "not_stored", "texts", "bad_texts")}
    with conn.transaction():
        raw_ids: dict[str, int] = dict(conn.execute("SELECT path, id FROM raw_files").fetchall())
        seen: set[tuple[str, str]] = set()
        batch: list[_Row] = []
        chars = 0
        for rec in records:
            counts["read"] += 1
            row = _prepare(rec)
            if not isinstance(row, str) and (row.source, row.source_key) in seen:
                row = f"duplicate source_key {row.source_key!r} in source {row.source}"
            if isinstance(row, str):
                counts["rejected"] += 1
                counts["not_stored"] += 1
                log.warning("record not stored: %s", row)
                continue
            if row.raw_file is not None and row.raw_file not in raw_ids:
                raise KeyError(
                    f"raw_file {row.raw_file!r} of {row.source}/{row.source_key} is not registered "
                    "(call register_raw_files first)"
                )
            seen.add((row.source, row.source_key))
            if row.status == "rejected":
                counts["rejected"] += 1
                log.warning("record %s/%s rejected: %s", row.source, row.source_key, row.reason)
            if row.text is not None:
                counts["texts"] += 1
                if row.bad_reason is not None:
                    counts["bad_texts"] += 1
                chars += len(row.text)
            batch.append(row)
            if len(batch) >= BATCH_ROWS or chars >= BATCH_TEXT_CHARS:
                _flush(conn, batch, raw_ids, counts)
                batch, chars = [], 0
        if batch:
            _flush(conn, batch, raw_ids, counts)
    return counts
