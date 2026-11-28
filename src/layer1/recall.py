"""Recall of a layer-1 run on Suva's labels, and the validation report (D-073; docs/LAYER1.md §6).

The recall check is blocking: a labelled ruling layer 1 drops fails it (TIPS handoff §6.1). Cohorts: Suva's
relevance list (Q4/2025, Q1/2026), its summary exports, and the Q3/2025 summaries outside the list. The
report holds aggregate counts only (D-031): no Suva label per docket leaves the database.
"""

from __future__ import annotations

import json
from pathlib import Path

import psycopg

_RECALL_SQL = """
WITH listed AS (
       SELECT DISTINCT ruling_id FROM gold.label
       WHERE source = 'suva_relevance_list' AND in_suva_scope AND ruling_id IS NOT NULL),
     exported AS (
       SELECT DISTINCT ruling_id FROM gold.label WHERE source = 'suva_summary_export' AND in_suva_scope),
     cohorts AS (
       SELECT 'suva_list' AS cohort, ruling_id FROM listed
       UNION ALL SELECT 'summary_exports', ruling_id FROM exported
       UNION ALL SELECT 'q3_2025_summaries', e.ruling_id
                 FROM exported e JOIN corpus.ruling r ON r.ruling_id = e.ruling_id
                 WHERE r.quarter_by_decision = '2025Q3' AND e.ruling_id NOT IN (SELECT ruling_id FROM listed)
       UNION ALL SELECT 'all_labelled', ruling_id
                 FROM (SELECT ruling_id FROM listed UNION SELECT ruling_id FROM exported) u)
SELECT c.cohort, count(*) AS total,
       count(*) FILTER (WHERE a.in_suva_scope = 'potentially') AS kept,
       count(*) FILTER (WHERE a.assessment_id IS NULL) AS not_assessed,
       coalesce(array_agg(r.docket ORDER BY r.docket)
                  FILTER (WHERE a.in_suva_scope IS DISTINCT FROM 'potentially'), '{}') AS missed
FROM cohorts c
JOIN corpus.ruling r ON r.ruling_id = c.ruling_id
LEFT JOIN triage.assessment a
       ON a.ruling_id = c.ruling_id AND a.run_id = %s AND a.step = 'layer1_filter' AND a.repetition_idx = 0
GROUP BY c.cohort ORDER BY c.cohort
"""


def latest_run(cur: psycopg.Cursor, profile: str = "default") -> str:
    cur.execute(
        """SELECT pr.run_id::text FROM ops.pipeline_run pr
           JOIN ops.pipeline_profile_version pv ON pv.profile_version_id = pr.profile_version_id
           WHERE pr.kind = 'layer1' AND pr.status = 'succeeded' AND pv.profile_code = %s
           ORDER BY pr.started_at DESC LIMIT 1""",
        (profile,),
    )
    row = cur.fetchone()
    if row is None:
        raise LookupError(f"no succeeded layer-1 run for profile {profile}")
    return row[0]


def recall(cur: psycopg.Cursor, run_id: str) -> dict[str, dict]:
    cur.execute(_RECALL_SQL, (run_id,))
    out = {}
    for cohort, total, kept, not_assessed, missed in cur.fetchall():
        out[cohort] = {"total": total, "kept": kept, "not_assessed": not_assessed, "missed": list(missed)}
    if not out:
        raise LookupError("no labels in gold.label: run `python -m src.ingest gold` first")
    return out


def record_recall(conn: psycopg.Connection, run_id: str) -> dict[str, dict]:
    """Compute recall, store it as metrics of the run, return it. Missed dockets stay in the database (D-031)."""
    with conn.transaction(), conn.cursor() as cur:
        result = recall(cur, run_id)
        cur.executemany(
            """INSERT INTO ops.run_metric (run_id, step, metric_code, value, unit) VALUES (%s, 'layer1_filter', %s,
               %s, 'rulings')
               ON CONFLICT DO NOTHING""",
            [
                (run_id, f"recall_{cohort}_{key}", values[key])
                for cohort, values in result.items()
                for key in ("total", "kept")
            ],
        )
    return result


def run_summary(cur: psycopg.Cursor, run_id: str) -> dict:
    """Aggregate counts of a run: version, totals, by reason, by population. No per-docket label."""
    cur.execute(
        """SELECT cv.version_label, pv.profile_code, pv.version_label, pr.started_at::text, pr.git_commit, pr.git_dirty
           FROM ops.pipeline_run pr
           JOIN ops.span root ON root.run_id = pr.run_id AND root.parent_span_id IS NULL AND root.operation =
               'layer1.run'
           JOIN ops.component_version cv ON cv.component_version_id = root.component_version_id
           JOIN ops.pipeline_profile_version pv ON pv.profile_version_id = pr.profile_version_id WHERE pr.run_id =
               %s""",
        (run_id,),
    )
    version, profile, profile_version, started, commit, dirty = cur.fetchone()
    cur.execute("SELECT metric_code, value FROM ops.run_metric WHERE run_id = %s AND step = 'layer1_filter'", (run_id,))
    values = {code: float(v) for code, v in cur.fetchall()}
    cur.execute(
        """SELECT p.code, count(*), count(*) FILTER (WHERE a.in_suva_scope = 'potentially')
           FROM triage.assessment a JOIN corpus.population_member m ON m.ruling_id = a.ruling_id
           JOIN corpus.population p ON p.population_id = m.population_id
           WHERE a.run_id = %s AND a.step = 'layer1_filter' GROUP BY p.code ORDER BY p.code""",
        (run_id,),
    )
    populations = {code: {"rulings": n, "kept": k} for code, n, k in cur.fetchall()}
    return {
        "run_id": run_id,
        "layer1_filter": version,
        "profile": f"{profile} {profile_version}",
        "started_at": started,
        "git_commit": commit,
        "git_dirty": dirty,
        "totals": {k: int(v) for k, v in values.items() if not k.startswith(("reason_", "recall_"))},
        "by_reason": {k.removeprefix("reason_").upper(): int(v) for k, v in values.items() if k.startswith("reason_")},
        "recall": {k.removeprefix("recall_"): int(v) for k, v in values.items() if k.startswith("recall_")},
        "by_population": populations,
    }


def compare(cur: psycopg.Cursor, run_a: str, run_b: str) -> dict:
    """How many rulings change scope between two runs, in each direction (counts only)."""
    cur.execute(
        """SELECT a.in_suva_scope::text, b.in_suva_scope::text, count(*)
           FROM triage.assessment a JOIN triage.assessment b ON b.ruling_id = a.ruling_id AND b.run_id = %s AND
               b.step = 'layer1_filter'
           WHERE a.run_id = %s AND a.step = 'layer1_filter' AND a.in_suva_scope <> b.in_suva_scope GROUP BY 1, 2""",
        (run_b, run_a),
    )
    return {f"{x}->{y}": n for x, y, n in cur.fetchall()}


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
