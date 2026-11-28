"""Recall of a layer-1 run on Suva's labels, and the validation report (D-073; docs/LAYER1.md §6).

The recall check is blocking: a labelled ruling layer 1 drops fails it (TIPS handoff §6.1). Cohorts: Suva's
relevance list (Q4/2025, Q1/2026), its summary exports, and the Q3/2025 summaries outside the list. The
report holds aggregate counts only (D-031): no Suva label per docket leaves the database.

`validate` runs a baseline and a candidate profile, records recall, compares them ruling by ruling and fails on a
ruling that goes potentially -> out_of_scope or that the candidate does not decide, rulings that differ between the
runs, a labelled ruling the candidate drops, or a failed run (a golden mismatch fails one). Its runs are of kind
`eval` (measurements): `latest_run`, the label and layer 2 read `layer1` runs only.
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
    """How many rulings change scope between two runs, in each direction (counts only).

    Rulings are matched by identity, not counted: a ruling one run assessed and the other did not is a change to or
    from `not_assessed` (`potentially->not_assessed` is a ruling run A keeps that run B never decided).
    """
    cur.execute(
        """WITH a AS (SELECT ruling_id, in_suva_scope::text AS scope FROM triage.assessment
                      WHERE run_id = %(a)s AND step = 'layer1_filter' AND repetition_idx = 0),
                b AS (SELECT ruling_id, in_suva_scope::text AS scope FROM triage.assessment
                      WHERE run_id = %(b)s AND step = 'layer1_filter' AND repetition_idx = 0)
           SELECT coalesce(a.scope, 'not_assessed'), coalesce(b.scope, 'not_assessed'), count(*)
           FROM a FULL JOIN b ON b.ruling_id = a.ruling_id
           WHERE a.scope IS DISTINCT FROM b.scope GROUP BY 1, 2""",
        {"a": run_a, "b": run_b},
    )
    return {f"{x}->{y}": n for x, y, n in cur.fetchall()}


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _next_seq(cur: psycopg.Cursor, run_id: str) -> int:
    cur.execute("SELECT coalesce(max(seq), 0) + 1 FROM ops.log_event WHERE run_id = %s", (run_id,))
    return cur.fetchone()[0]


def validate(
    conn: psycopg.Connection,
    baseline_profile: str,
    profile: str,
    *,
    runs_dir: Path | None = None,
    actor: str = "layer1-cli",
) -> dict:
    """Run a baseline and a candidate profile on the same corpus, record recall, compare (docs/LAYER1.md §6).

    The candidate passes when both runs succeed (a golden mismatch fails a run), they decide the same rulings (by
    identity, not by count), no ruling the baseline keeps is dropped or left undecided by the candidate, and, when
    Suva's labels are loaded, the candidate keeps every labelled ruling. The baseline's recall is reported, not
    required: a candidate may fix it. Aggregates only (D-031). Event `layer1.validation.passed|failed` on the
    candidate run. Both runs are of kind `eval`: a measurement never forms the label (triage.v_scope_pipeline) and is
    never layer 2's candidate source, so the release gate leaves the delivered label as it found it.
    """
    from src.layer1.run import RUNS_DIR, STEP, run_layer1

    outs: dict[str, dict | None] = {}
    failures: list[str] = []
    for role, prof in (("baseline", baseline_profile), ("candidate", profile)):
        try:
            outs[role] = run_layer1(conn, profile=prof, runs_dir=runs_dir or RUNS_DIR, actor=actor, kind="eval")
        except Exception as exc:  # recorded as a failed run by run_layer1; the validation reports it
            outs[role] = None
            failures.append(f"{role} run ({prof}) failed: {type(exc).__name__}: {exc}"[:500])
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM gold.label")
        has_labels = cur.fetchone()[0] > 0
    conn.commit()
    recalls: dict[str, dict] = {}
    if has_labels:
        for role, out in outs.items():
            if out is not None:
                full = record_recall(conn, out["run_id"])
                recalls[role] = {c: {k: v[k] for k in ("total", "kept", "not_assessed")} for c, v in full.items()}
    base, cand = outs["baseline"], outs["candidate"]
    with conn.cursor() as cur:
        report: dict = {"runs": [run_summary(cur, o["run_id"]) for o in (base, cand) if o is not None]}
        changes = compare(cur, base["run_id"], cand["run_id"]) if base and cand else {}
    conn.commit()
    if base and cand:
        report["scope_changes"] = changes
    removals = changes.get("potentially->out_of_scope", 0)
    # kept by the baseline, never decided by the candidate: a removal too
    unassessed_kept = changes.get("potentially->not_assessed", 0)
    only_base = sum(n for k, n in changes.items() if k.endswith("->not_assessed"))
    only_cand = sum(n for k, n in changes.items() if k.startswith("not_assessed->"))
    candidate_recall = recalls.get("candidate")
    checks = {
        "runs_succeeded": base is not None and cand is not None,
        "same_rulings": bool(base and cand) and only_base == 0 and only_cand == 0,
        "no_removal": bool(base and cand) and removals == 0 and unassessed_kept == 0,
        "candidate_recall_complete": (
            None if candidate_recall is None else all(v["kept"] == v["total"] for v in candidate_recall.values())
        ),
        "golden_not_failed": not any("golden check failed" in f for f in failures),
    }
    if base and cand and (only_base or only_cand):
        failures.append(
            f"the runs decided different rulings: {only_base} only in the baseline, {only_cand} only in the candidate"
        )
    if removals:
        failures.append(f"{removals} ruling(s) go potentially -> out_of_scope")
    if unassessed_kept:
        failures.append(f"{unassessed_kept} ruling(s) the baseline keeps are not decided by the candidate")
    if candidate_recall is not None and not checks["candidate_recall_complete"]:
        failures.append("the candidate drops a labelled ruling")
    passed = not failures and all(v is not False for v in checks.values())
    validation = {
        "passed": passed,
        "baseline": {"profile": baseline_profile, **_role(base)},
        "candidate": {"profile": profile, **_role(cand)},
        "potentially_to_out_of_scope": removals,
        "out_of_scope_to_potentially": changes.get("out_of_scope->potentially", 0),
        "potentially_not_decided_by_candidate": unassessed_kept,
        "recall": recalls,
        "checks": checks,
        "failures": failures,
        "note": None if has_labels else "gold.label is empty: recall not measured (python -m src.ingest gold)",
    }
    report["validation"] = validation
    if cand is not None:
        from src.db.runs import Run, events

        with conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """SELECT span_id::text, pr.profile_version_id::text, component_version_id::text FROM ops.span s
                   JOIN ops.pipeline_run pr USING (run_id) WHERE s.run_id = %s AND s.parent_span_id IS NULL""",
                (cand["run_id"],),
            )
            span_id, pvid, cvid = cur.fetchone()
            run = Run(cand["run_id"], span_id, pvid, cvid)
            events(
                cur,
                run,
                STEP,
                [
                    (
                        _next_seq(cur, run.run_id),
                        "info" if passed else "error",
                        "layer1.validation.passed" if passed else "layer1.validation.failed",
                        (f"validated against {baseline_profile}" + ("" if passed else ": " + "; ".join(failures)))[
                            :400
                        ],
                        validation,
                        None,
                        None,
                    )
                ],
            )
    return report


def _role(out: dict | None) -> dict:
    if out is None:
        return {"run_id": None, "layer1_filter": None, "golden": None}
    return {
        "run_id": out["run_id"],
        "layer1_filter": out["version"],
        "golden": out["golden"],
        "rulings": out["rulings"],
        "kept": out["kept"],
    }
