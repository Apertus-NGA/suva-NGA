"""Suva's labels into gold.label (D-062; docs/DB_DDL_PLANNING.md §12.1).

The relevance list (columns A and B of the workbook) and the 55 summary exports (their bger.ch link) become
labels. Nothing else of judgements/ is read (D-051). A listed Federal Court docket missing from the corpus
fails the load: that is a crawl gap or a window error (T30), never a silent skip.
"""

from __future__ import annotations

import hashlib

import psycopg

from src.db.pg import sha256_file
from src.db.registry import profile_version
from src.db.runs import begin_run, events, fail_run, finish_run, metrics
from src.ingest import judgements as jd


def _exports_sha(refs: list[jd.ExportRef]) -> str:
    lines = [f"{sha256_file(jd.ROOT / r.file)}  {r.file}" for r in refs]
    return hashlib.sha256("\n".join(sorted(lines)).encode("utf-8")).hexdigest()


def load_gold(conn: psycopg.Connection, actor: str) -> dict:
    rows = jd.list_rows()
    refs = jd.export_refs()
    export_dockets = {r.docket for r in refs}
    with conn.cursor() as cur:
        pvid, _ = profile_version(cur, "default")
    run = begin_run(
        conn,
        profile_version_id=pvid,
        kind="load",
        step="ingest",
        operation="ingest.gold",
        component_version_id=None,
        params={"source": "judgements/"},
        actor=actor,
    )
    try:
        with conn.transaction(), conn.cursor() as cur:
            snaps = {}
            for source, uri, sha, count in (
                ("judgements_workbook", f"judgements/{jd.WORKBOOK.name}", sha256_file(jd.WORKBOOK), len(rows)),
                ("judgements_export", "judgements/Export_*.html", _exports_sha(refs), len(refs)),
            ):
                cur.execute(
                    """INSERT INTO ops.source_snapshot (source, uri, file_sha256, row_count, retrieved_at)
                       VALUES (%s, %s, %s, %s, now()) ON CONFLICT ON CONSTRAINT source_snapshot_uq DO NOTHING""",
                    (source, uri, sha, count),
                )
                cur.execute(
                    "SELECT snapshot_id::text FROM ops.source_snapshot WHERE source = %s AND revision IS NULL AND "
                    "file_sha256 = %s",
                    (source, sha),
                )
                snaps[source] = cur.fetchone()[0]

            missing: list[str] = []
            labels = []
            for row in rows:
                docket, title = jd.resolve_entry(row.entry, export_dockets)
                quarter = row.quarter_label.replace(" ", "")
                source_ref = f"judgements/{jd.WORKBOOK.name}#row-{row.row}"
                if title is not None:
                    labels.append(
                        (
                            None,
                            title,
                            "suva_relevance_list",
                            row.quarter_label,
                            source_ref,
                            snaps["judgements_workbook"],
                        )
                    )
                    continue
                cur.execute(
                    "SELECT ruling_id::text FROM corpus.ruling WHERE docket = %s AND quarter_by_decision = %s",
                    (docket, quarter),
                )
                found = cur.fetchall()
                if len(found) != 1:
                    missing.append(f"{docket} ({row.quarter_label}): {len(found)} rulings")
                    continue
                labels.append(
                    (
                        found[0][0],
                        None,
                        "suva_relevance_list",
                        row.quarter_label,
                        source_ref,
                        snaps["judgements_workbook"],
                    )
                )
            for ref in refs:
                cur.execute(
                    "SELECT ruling_id::text FROM corpus.ruling WHERE docket = %s AND decision_date = %s",
                    (ref.docket, ref.decision_date),
                )
                found = cur.fetchone()
                if found is None:
                    missing.append(f"{ref.docket} decided {ref.decision_date} ({ref.file})")
                    continue
                labels.append((found[0], None, "suva_summary_export", None, ref.file, snaps["judgements_export"]))
            if missing:
                raise LookupError("labelled rulings missing from the corpus (T30): " + "; ".join(missing))
            cur.executemany(
                """INSERT INTO gold.label (ruling_id, external_title, source, in_suva_scope, quarter_label,
                   source_ref, snapshot_id, created_by_run_id)
                   VALUES (%s, %s, %s, true, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                [(*label[:3], label[3], label[4], label[5], run.run_id) for label in labels],
            )
            summary = {
                "list_rows": len(rows),
                "list_federal_court": sum(1 for lab in labels if lab[2] == "suva_relevance_list" and lab[0]),
                "list_cantonal": sum(1 for lab in labels if lab[1]),
                "exports": sum(1 for lab in labels if lab[2] == "suva_summary_export"),
            }
            metrics(cur, run, "ingest", summary, unit="labels")
            events(
                cur,
                run,
                "ingest",
                [
                    (
                        1,
                        "info",
                        "ingest.gold.loaded",
                        "Suva labels loaded (columns A-B and export links only, D-051)",
                        summary,
                        None,
                        None,
                    )
                ],
            )
            finish_run(cur, run)
    except Exception as exc:
        fail_run(conn, run, exc)
        raise
    return {"run_id": run.run_id, **summary}
