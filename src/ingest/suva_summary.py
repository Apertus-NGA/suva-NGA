"""Suva's reference summaries (judgements/Export_*.html) into gold.suva_summary (DS5, D-051).

One row per export: docket, decision date, Text DE, Text FR, the ruling it belongs to, and a bger.ch link built
by code from the docket and the decision date (G1). The export's own link is only checked, never stored: it must
be a bger.ch link (http or https: one export has an http link) naming the same aza:// id. The author section is
never stored, logged or printed (D-051): the parser returns it, this module never reads that attribute.

Provenance: the 'judgements_export' snapshot of src/ingest/gold.py (the same manifest of file hashes) is reused;
it is created the same way when absent. Every export is written, already loaded, or excluded with a reason code
of ops.reason_code. No table can hold an excluded export yet (corpus.ingest_exclusion takes HF, aza and team-list
ids only), so an exclusion refuses the whole load and nothing is written (T30: a missing ruling is a crawl gap,
never a silent skip). One transaction; a second run adds nothing.

    python -m src.ingest.suva_summary --database-url postgresql://... [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import psycopg

from src.db.pg import connect
from src.db.registry import profile_version
from src.db.runs import begin_run, events, fail_run, finish_run, metrics
from src.ingest import judgements as jd
from src.ingest.gold import _exports_sha
from src.ingest.hf_base import bger_url
from src.suva_data.loaders.gold_summaries import GoldSummaryError, parse_export

CODE_PATHS = (
    "src/ingest/suva_summary.py",
    "src/ingest/judgements.py",
    "src/ingest/gold.py",
    "src/suva_data/loaders/gold_summaries.py",
)
SOURCE = "judgements_export"
_BGER_LINK = re.compile(r"^https?://([a-z0-9-]+\.)*bger\.ch/", re.IGNORECASE)

# Why an export is not written. Each must exist in ops.reason_code (checked before any write).
NO_DOCKET = "ING_DOCKET_MALFORMED"  # no Federal Court docket in the file name, or it disagrees with the aza:// id
NO_DATE = "ING_DECISION_DATE_MISSING"  # no aza:// id, so no decision date
NO_RULING = "GOLD_RULING_MISSING"  # seed request: no corpus.ruling on (docket, decision date)
UNPARSEABLE = "GOLD_EXPORT_UNPARSEABLE"  # seed request: parse_export refused the file
MISMATCH = "GOLD_EXPORT_MISMATCH"  # seed request: title date or export link disagrees with the aza:// id


@dataclass(frozen=True)
class Row:
    source_file: str  # judgements/Export_....html
    docket: str
    decision_date: date
    ruling_language: str
    text_de: str
    text_fr: str
    bger_url: str


@dataclass
class Ledger:
    rows: list[Row] = field(default_factory=list)
    exclusions: list[tuple[str, str, str]] = field(default_factory=list)  # (source_file, reason_code, detail)

    def by_reason(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for _, code, _ in self.exclusions:
            out[code] = out.get(code, 0) + 1
        return out


def read_exports(directory: Path = jd.JUDGEMENTS) -> tuple[list[jd.ExportRef], Ledger]:
    """Parse every export of the directory. Pure: no database. The author attribute is discarded unread."""
    paths = sorted(directory.glob("Export_*.html"))
    ledger = Ledger()
    refs: list[jd.ExportRef] = []
    for path in paths:
        source_file = f"judgements/{path.name}"
        try:
            ref = _ref(path)
        except ValueError as exc:
            ledger.exclusions.append((source_file, NO_DATE, str(exc)))
            continue
        refs.append(ref)
        try:
            parsed = parse_export(path.read_text(encoding="utf-8"), path.name)
        except GoldSummaryError as exc:
            reason = NO_DOCKET if "case number" in str(exc) else UNPARSEABLE
            ledger.exclusions.append((source_file, reason, str(exc)))
            continue
        if parsed.docket != ref.docket:
            ledger.exclusions.append((source_file, NO_DOCKET, f"file name {parsed.docket}, aza:// id {ref.docket}"))
            continue
        if parsed.decision_date_from_title and parsed.decision_date_from_title != ref.decision_date.isoformat():
            ledger.exclusions.append(
                (source_file, MISMATCH, f"title date {parsed.decision_date_from_title}, aza:// {ref.decision_date}")
            )
            continue
        aza = f"aza://{ref.decision_date:%d-%m-%Y}-{ref.docket.replace('/', '-')}"
        link = parsed.source_url or ""
        if not _BGER_LINK.match(link) or aza not in link:
            ledger.exclusions.append((source_file, MISMATCH, f"export link is not a bger.ch link to {aza}"))
            continue
        ledger.rows.append(
            Row(
                source_file=source_file,
                docket=ref.docket,
                decision_date=ref.decision_date,
                ruling_language=parsed.title_language,
                text_de=parsed.body_de,
                text_fr=parsed.body_fr,
                bger_url=bger_url(ref.docket, ref.decision_date),  # built by code (G1)
            )
        )
    return refs, ledger


def _ref(path: Path) -> jd.ExportRef:
    """The docket and decision date of one export, from its aza:// id (src/ingest/judgements.py)."""
    found = jd._AZA.search(path.read_text(encoding="utf-8", errors="replace"))
    if not found:
        raise ValueError(f"{path.name}: no aza:// link")
    day, month, year, head, filing_year = found.groups()
    return jd.ExportRef(f"judgements/{path.name}", f"{head}/{filing_year}", date(int(year), int(month), int(day)))


def _snapshot(cur: psycopg.Cursor, sha: str, count: int, write: bool) -> str | None:
    """gold.py's 'judgements_export' snapshot of this manifest; created the same way when absent (write=True)."""
    if write:
        cur.execute(
            """INSERT INTO ops.source_snapshot (source, uri, file_sha256, row_count, retrieved_at)
               VALUES (%s, 'judgements/Export_*.html', %s, %s, now())
               ON CONFLICT ON CONSTRAINT source_snapshot_uq DO NOTHING""",
            (SOURCE, sha, count),
        )
    cur.execute(
        "SELECT snapshot_id::text, row_count FROM ops.source_snapshot WHERE source = %s AND revision IS NULL "
        "AND file_sha256 = %s",
        (SOURCE, sha),
    )
    found = cur.fetchone()
    if found is None:
        return None
    if found[1] != count:
        raise RuntimeError(f"snapshot {found[0]} records {found[1]} exports, the directory has {count}")
    return found[0]


def _plan(cur: psycopg.Cursor, ledger: Ledger) -> tuple[list[tuple], int]:
    """Match each row to its ruling; split into rows to insert and rows already stored (identical, else fail)."""
    to_insert: list[tuple] = []
    already = 0
    for row in ledger.rows:
        cur.execute(
            "SELECT ruling_id::text FROM corpus.ruling WHERE docket = %s AND decision_date = %s",
            (row.docket, row.decision_date),
        )
        found = cur.fetchone()
        if found is None:
            ledger.exclusions.append((row.source_file, NO_RULING, f"{row.docket} decided {row.decision_date}"))
            continue
        cur.execute(
            """SELECT docket, decision_date, ruling_id::text, ruling_language::text, text_de, text_fr, bger_url
               FROM gold.suva_summary WHERE source_file = %s""",
            (row.source_file,),
        )
        stored = cur.fetchone()
        wanted = (
            row.docket,
            row.decision_date,
            found[0],
            row.ruling_language,
            row.text_de,
            row.text_fr,
            row.bger_url,
        )
        if stored is not None:
            if tuple(stored) != wanted:
                raise RuntimeError(f"{row.source_file}: stored summary differs from the file; never overwritten")
            already += 1
            continue
        to_insert.append((*wanted, row.source_file, len(row.text_de.split()), len(row.text_fr.split())))
    return to_insert, already


def _check_reason_codes(cur: psycopg.Cursor, ledger: Ledger) -> list[str]:
    codes = sorted(ledger.by_reason())
    if not codes:
        return []
    cur.execute("SELECT code FROM ops.reason_code WHERE code = ANY(%s)", (codes,))
    known = {r[0] for r in cur.fetchall()}
    return [c for c in codes if c not in known]


def load_summaries(
    conn: psycopg.Connection, directory: Path = jd.JUDGEMENTS, *, actor: str = "pipeline", dry_run: bool = False
) -> dict:
    """Load every export of the directory. All or nothing; idempotent. Returns the counts."""
    refs, ledger = read_exports(directory)
    rows_in = len(refs) + sum(1 for _, code, _ in ledger.exclusions if code == NO_DATE)
    sha = _exports_sha(refs)

    if dry_run:
        with conn.cursor() as cur:
            snap = _snapshot(cur, sha, len(refs), write=False)
            to_insert, already = _plan(cur, ledger)
        conn.rollback()
        return _counts(rows_in, 0, already, ledger, snap, dry_run=True, would_write=len(to_insert))

    with conn.cursor() as cur:
        pvid, _ = profile_version(cur, "default")
    run = begin_run(
        conn,
        profile_version_id=pvid,
        kind="load",
        step="ingest",
        operation="ingest.suva_summary",
        component_version_id=None,
        params={"source": "judgements/Export_*.html", "manifest_sha256": sha},
        code_paths=CODE_PATHS,
        actor=actor,
    )
    try:
        with conn.transaction(), conn.cursor() as cur:
            snap = _snapshot(cur, sha, len(refs), write=True)
            to_insert, already = _plan(cur, ledger)
            if ledger.exclusions:
                missing = _check_reason_codes(cur, ledger)
                detail = "; ".join(f"{f}: {code} ({why})" for f, code, why in ledger.exclusions)
                seed = f" reason codes absent from ops.reason_code (seed needed): {missing}." if missing else ""
                raise LookupError(
                    f"{len(ledger.exclusions)} export(s) cannot be written and no table holds an export exclusion: "
                    f"nothing written.{seed} {detail}"
                )
            cur.executemany(
                """INSERT INTO gold.suva_summary (docket, decision_date, ruling_id, ruling_language, text_de, text_fr,
                   bger_url, source_file, word_count_de, word_count_fr, snapshot_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (source_file) DO NOTHING""",
                [(*r, snap) for r in to_insert],
            )
            # closure: every export of the manifest is a stored row, identical to the file
            cur.execute(
                "SELECT count(*) FROM gold.suva_summary WHERE source_file = ANY(%s)",
                ([r.file for r in refs],),
            )
            stored = cur.fetchone()[0]
            if stored != len(refs) or len(to_insert) + already != len(refs):
                raise RuntimeError(
                    f"closure failed: {len(refs)} exports, {stored} stored, {len(to_insert)} written + {already} "
                    "already loaded"
                )
            counts = _counts(rows_in, len(to_insert), already, ledger, snap)
            metrics(
                cur,
                run,
                "ingest",
                {
                    "suva_summary_rows_in": rows_in,
                    "suva_summary_written": len(to_insert),
                    "suva_summary_already": already,
                },
                unit="summaries",
            )
            events(
                cur,
                run,
                "ingest",
                [
                    (
                        1,
                        "info",
                        "ingest.suva_summary.loaded",
                        "Suva reference summaries loaded (Text DE, Text FR, docket, date; no author, D-051)",
                        counts,
                        None,
                        None,
                    )
                ],
            )
            finish_run(cur, run)
    except Exception as exc:
        fail_run(conn, run, exc)
        raise
    return {"run_id": run.run_id, **counts}


def _counts(rows_in, written, already, ledger: Ledger, snap, *, dry_run=False, would_write=None) -> dict:
    out = {
        "rows_in": rows_in,
        "written": written,
        "already_loaded": already,
        "excluded": ledger.by_reason(),
        "snapshot_id": snap,
        "closure_ok": rows_in == written + already + len(ledger.exclusions) and not ledger.exclusions,
    }
    if dry_run:
        out |= {"dry_run": True, "would_write": would_write, "closure_ok": None}
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.ingest.suva_summary", description=__doc__.splitlines()[0])
    parser.add_argument("--database-url", default=None, help="default: DATABASE_URL")
    parser.add_argument("--dry-run", action="store_true", help="parse and match, write nothing")
    parser.add_argument("--actor", default="pipeline")
    args = parser.parse_args(argv)
    with connect(args.database_url, actor=args.actor) as conn:
        counts = load_summaries(conn, actor=args.actor, dry_run=args.dry_run)
    print(json.dumps(counts, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
