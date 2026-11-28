"""Export the database as Parquet tables (a second, convenient way to read the same data).

The PostgreSQL dump stays the primary deliverable. These files exist so the data can be read with
pandas / `datasets.load_dataset` without running a database. They are derived from the database only,
written in a fixed order with fixed settings, so the same database gives byte-identical files.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from . import config

S, D, B, I = pa.string(), pa.date32(), pa.bool_(), pa.int32()


def _j(value):
    return None if value is None else json.dumps(value, ensure_ascii=False, sort_keys=True)


# name -> (schema, SQL in a deterministic order, per-row converter or None)
TABLES: dict[str, tuple[pa.Schema, str, object]] = {
    # One row per ruling, with the text to use and its relevance. The file most people want.
    "rulings": (
        pa.schema(
            [
                ("docket", S),
                ("decision_date", D),
                ("decision_quarter", S),
                ("division", S),
                ("language", S),
                ("publication_date", D),
                ("starred", B),
                ("area", S),
                ("subject", S),
                ("outcome", S),
                ("cited_decisions", pa.list_(S)),
                ("official_url", S),
                ("in_window", B),
                ("relevance", S),
                ("relevance_basis", S),
                ("has_gold_summary", B),
                ("text_source", S),
                ("text_char_count", I),
                ("n_text_sources", I),
                ("text", S),
                ("field_sources", S),
                ("flags", S),
            ]
        ),
        """SELECT r.docket, r.decision_date, v.decision_quarter, r.division, r.language, r.publication_date, r.starred,
                  r.area, r.subject, r.outcome, r.cited_decisions, r.official_url, r.in_window, v.relevance, v.basis,
                  EXISTS (SELECT 1 FROM gold_summaries g WHERE g.ruling_id = r.id AND g.is_current),
                  t.source, t.char_count, (r.flags->>'text_sources')::int, t.text, r.field_sources, r.flags
           FROM rulings r JOIN v_relevance v ON v.ruling_id = r.id
           LEFT JOIN ruling_texts t ON t.ruling_id = r.id AND t.is_canonical
           ORDER BY r.decision_date, r.docket""",
        lambda r: r[:20] + (_j(r[20]), _j(r[21])),
    ),
    "gold_summaries": (
        pa.schema(
            [
                ("docket", S),
                ("decision_date", D),
                ("language", S),
                ("title", S),
                ("body", S),
                ("author", S),
                ("source_url", S),
                ("source_file", S),
                ("version", I),
                ("is_current", B),
            ]
        ),
        """SELECT r.docket, r.decision_date, g.language, g.title, g.body, g.author, g.source_url, g.source_file, g.version, g.is_current
           FROM gold_summaries g JOIN rulings r ON r.id = g.ruling_id ORDER BY r.decision_date, r.docket, g.language, g.version""",
        None,
    ),
    "labels": (
        pa.schema(
            [
                ("docket", S),
                ("decision_date", D),
                ("label_set", S),
                ("value", S),
                ("quarter", S),
                ("created_by", S),
                ("xlsx_title", S),
                ("xlsx_row", I),
                ("erstellt", S),
                ("sharepoint_url", S),
            ]
        ),
        """SELECT r.docket, r.decision_date, l.label_set, l.value, l.quarter, l.created_by, l.metadata->>'xlsx_title',
                  (l.metadata->>'xlsx_row')::int, l.metadata->>'erstellt', l.metadata->>'sharepoint_url'
           FROM labels l JOIN rulings r ON r.id = l.ruling_id ORDER BY r.decision_date, r.docket, l.label_set""",
        None,
    ),
    # Every source's text for every ruling (the canonical one is flagged). Large.
    "ruling_texts": (
        pa.schema(
            [
                ("docket", S),
                ("decision_date", D),
                ("source", S),
                ("source_key", S),
                ("is_canonical", B),
                ("bad_reason", S),
                ("char_count", I),
                ("sha256_normalized", S),
                ("text", S),
            ]
        ),
        """SELECT sr.docket, sr.decision_date, sr.source, sr.source_key, t.is_canonical, t.bad_reason, t.char_count, t.sha256_normalized, t.text
           FROM ruling_texts t JOIN source_records sr ON sr.id = t.source_record_id ORDER BY sr.source, sr.source_key""",
        None,
    ),
    "source_records": (
        pa.schema(
            [
                ("source", S),
                ("source_key", S),
                ("docket", S),
                ("decision_date", D),
                ("status", S),
                ("status_reason", S),
                ("fields", S),
                ("record", S),
            ]
        ),
        """SELECT source, source_key, docket, decision_date, status, status_reason, fields, record
           FROM source_records ORDER BY source, source_key""",
        lambda r: r[:6] + (_j(r[6]), _j(r[7])),
    ),
    "conflicts": (
        pa.schema(
            [
                ("docket", S),
                ("decision_date", D),
                ("field", S),
                ("kind", S),
                ("winner_source", S),
                ("loser_source", S),
                ("winner_value", S),
                ("loser_value", S),
            ]
        ),
        """SELECT docket, decision_date, field, kind, winner_source, loser_source, winner_value, loser_value FROM conflicts ORDER BY id""",
        None,
    ),
    "statute_refs": (
        pa.schema(
            [
                ("docket", S),
                ("decision_date", D),
                ("law_code", S),
                ("article", S),
                ("paragraph", S),
                ("mention_count", I),
            ]
        ),
        """SELECT r.docket, r.decision_date, s.law_code, s.article, s.paragraph, s.mention_count
           FROM statute_refs s JOIN rulings r ON r.id = s.ruling_id ORDER BY r.decision_date, r.docket, s.law_code, s.article, s.paragraph""",
        None,
    ),
}

BATCH_ROWS = 500


def export_tables(conn, out_dir: Path | None = None) -> dict[str, dict]:
    """Write one Parquet file per table plus schema.sql. Returns {file: {rows, bytes, sha256}}."""
    out_dir = Path(out_dir or config.DATA_DIR / "tables")
    out_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, dict] = {}
    for name, (schema, sql, convert) in TABLES.items():
        path, tmp = out_dir / f"{name}.parquet", out_dir / f"{name}.parquet.part"
        rows = 0
        # A named (server-side) cursor streams the rows, so the large text tables never sit in memory at once.
        with conn.transaction(), conn.cursor(name=f"export_{name}") as cur:
            cur.execute(sql)
            with pq.ParquetWriter(
                tmp,
                schema,
                compression="zstd",
                compression_level=9,
                write_statistics=True,
                version="2.6",
                data_page_size=1 << 20,
            ) as writer:
                while True:
                    batch = cur.fetchmany(BATCH_ROWS)
                    if not batch:
                        break
                    if convert:
                        batch = [convert(r) for r in batch]
                    cols = list(zip(*batch))
                    writer.write_table(
                        pa.table([pa.array(c, type=f.type) for c, f in zip(cols, schema)], schema=schema)
                    )
                    rows += len(batch)
                if rows == 0:
                    writer.write_table(schema.empty_table())
        tmp.replace(path)
        result[f"{name}.parquet"] = {"rows": rows, **_stat(path)}
    schema_path = out_dir / "schema.sql"
    with schema_path.open("wb") as out:
        for m in sorted(config.MIGRATIONS_DIR.glob("*.sql")):
            out.write(f"-- {m.name}\n".encode())
            with m.open("rb") as f:
                shutil.copyfileobj(f, out)
            out.write(b"\n")
    result["schema.sql"] = _stat(schema_path)
    return result


def _stat(path: Path) -> dict:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return {"bytes": path.stat().st_size, "sha256": h.hexdigest()}
