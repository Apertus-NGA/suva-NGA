"""Certify a `layer2_judge` version against the D-074 benchmark (docs/LAYER2.md; plan L2-07, gate G-C).

Two parities, both without a gateway call:
1. messages: for every ruling of the frozen set `suva-ft-v3`, the messages built from the database text with the
   registered prompt and configuration must equal, byte for byte, the messages the benchmark sent;
2. scores: the P(Ja) of a layer-2 run (replayed from the benchmark's cache) must equal the benchmark's pass.
If both hold, the D-074 metrics (`results/finetune_benchmark_v3.json`) describe the version by identity.

Outputs: `expected/layer2/<version>.json` (counts and digests, written once, then compared: a certified behaviour
is immutable) and `results/layer2_validation.json` (aggregates). Per-ruling differences go to
`data/derived/layer2/validation/` only (D-031: the set's composition is public, its labels are not read here).
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import psycopg

from src.db.pg import ROOT, git_state, sha256_file
from src.db.registry import pinned_version, profile_version
from src.layer2.engine import build_messages, messages_sha256
from src.layer2.run import STEP, load_version

CANONICAL = "layer2-golden-1"
EXPECTED = ROOT / "expected" / "layer2"
RESULTS = ROOT / "results" / "layer2_validation.json"
DERIVED = ROOT / "data" / "derived" / "layer2" / "validation"
FOLDS = ("fold_A", "fold_B")


class ValidationFailed(RuntimeError):
    """A certified parity does not hold."""


def _digest(lines: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(lines)).encode("utf-8")).hexdigest()


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def check_frozen(manifest_path: Path, data_root: Path) -> str:
    """The test files are the frozen ones; returns the ids digest of the set."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for fold in FOLDS:
        info = manifest["splits"][f"{fold}/test"]
        if sha256_file(data_root / info["file"]) != info["sha256"]:
            raise ValidationFailed(f"{fold}/test is not the frozen file of {manifest_path.name}")
    return manifest["ids_digest_sha256"]


def certification_run(cur: psycopg.Cursor, component_version_id: str, keys: set[tuple[str, str]]) -> str:
    """The run whose scores are compared with the benchmark: among the usable runs of this version, the one that
    judged the most rulings of the certified set (`keys` = (docket, decision date)), the latest on a tie. Not
    simply the latest run: a small live or eval slice would otherwise replace the full replay of the set."""
    cur.execute(
        """SELECT pr.run_id::text, r.docket, r.decision_date::text
           FROM ops.pipeline_run pr
           JOIN triage.assessment a ON a.run_id = pr.run_id AND a.step = 'layer2_judge' AND a.outcome = 'ok'
                                   AND a.component_version_id = %s
           JOIN corpus.ruling r ON r.ruling_id = a.ruling_id
           WHERE pr.kind IN ('layer2', 'eval') AND pr.status IN ('succeeded', 'partial')
           ORDER BY pr.finished_at""",
        (component_version_id,),
    )
    coverage: dict[str, int] = {}
    for run, docket, decided in cur.fetchall():
        coverage[run] = coverage.get(run, 0) + ((docket, decided) in keys)
    if not coverage:
        raise LookupError("no layer-2 run of this version: run python -m src.layer2 run first")
    best = max(coverage.values())
    return [run for run, n in coverage.items() if n == best][-1]  # runs come in finishing order: the latest tie


def validate(
    conn: psycopg.Connection,
    *,
    data_root: Path,
    manifest_path: Path,
    bench_dir: Path | None = None,
    run_id: str | None = None,
    profile: str = "default",
    write_expected: bool = False,
    expected_dir: Path = EXPECTED,
    results_path: Path = RESULTS,
    derived_dir: Path = DERIVED,
) -> dict:
    ids_digest = check_frozen(manifest_path, data_root)
    with conn.cursor() as cur:
        pvid, _ = profile_version(cur, profile)
        cvid = pinned_version(cur, pvid, STEP)
        v = load_version(cur, cvid)
        cur.execute(
            "SELECT version_label FROM ops.component_version WHERE component_version_id = %s",
            (pinned_version(cur, pvid, "layer1_filter"),),
        )
        layer1 = cur.fetchone()[0]  # the compared subset is layer 1's candidates: certified per layer-1 version
        cur.execute("SELECT config_sha256 FROM ops.component_version WHERE component_version_id = %s", (cvid,))
        config_sha = cur.fetchone()[0]
        dataset = [r for fold in FOLDS for r in _rows(data_root / fold / "test.jsonl")]
        cur.execute(
            """SELECT r.docket, r.decision_date::text, t.content FROM corpus.ruling r
               JOIN corpus.ruling_text t ON t.ruling_id = r.ruling_id AND t.is_primary"""
        )
        texts = {(d, dd): c for d, dd, c in cur.fetchall()}
        # 1. messages parity
        equal, different, missing = [], [], []
        truncation, neutralised = Counter(), 0
        for row in dataset:
            meta = row["meta"]
            text = texts.get((meta["docket"], meta["decision_date"]))
            if text is None:
                missing.append(meta["decision_id"])
                continue
            messages, prepared = build_messages(
                meta["docket"], text, v.prompt, v.config.text_cap, v.config.neutralise_control_tags
            )
            truncation[prepared.truncation] += 1
            neutralised += prepared.neutralised > 0
            ours, theirs = messages_sha256(messages), messages_sha256(row["prompt"])
            (equal if ours == theirs else different).append(f"{meta['decision_id']}:{ours}")
        # 2. scores parity
        scores: dict = {"compared": 0}
        if bench_dir is not None:
            bench = {r["decision_id"]: r for fold in FOLDS for r in _rows(bench_dir / fold / "rep000.jsonl")}
            by_key = {(r["meta"]["docket"], r["meta"]["decision_date"]): r["meta"]["decision_id"] for r in dataset}
            run = run_id or certification_run(cur, cvid, set(by_key))
            cur.execute(
                """SELECT r.docket, r.decision_date::text, j.p_yes, a.score_0_100, a.score_raw
                   FROM triage.assessment a JOIN triage.llm_judgement j USING (assessment_id)
                   JOIN corpus.ruling r ON r.ruling_id = a.ruling_id
                   WHERE a.run_id = %s AND a.step = 'layer2_judge' AND a.outcome = 'ok'""",
                (run,),
            )
            judged = cur.fetchall()
            diffs, lines = [], []
            for docket, decided, p_yes, _s100, _raw in judged:
                did = by_key.get((docket, decided))
                if did is None or did not in bench:
                    continue
                diffs.append(abs(p_yes - bench[did]["score"]))
                lines.append(f"{did}:{p_yes!r}")
            s100_values = [float(s) for *_, s, _ in judged]
            scores = {
                "run_id": run,
                "judged_in_run": len(judged),
                "compared": len(diffs),
                "equal": sum(1 for d in diffs if d == 0.0),
                "max_abs_diff": max(diffs) if diffs else None,
                "scores_digest": _digest(lines),
                "distinct_p_yes": len({p for _, _, p, _, _ in judged}),
                "distinct_score_0_100": len(set(s100_values)),
                "tied_at_100": sum(1 for s in s100_values if s == 100.0),
                "tied_at_0": sum(1 for s in s100_values if s == 0.0),
                "distinct_score_raw": len({r for *_, r in judged}),
            }
    expected = {
        "canonical": CANONICAL,
        "step": STEP,
        "version": v.label,
        "prompt": f"{v.prompt.role} {v.prompt.version_label}",
        "prompt_template_sha256": v.prompt.template_sha256,
        "config_sha256": config_sha,
        "dataset": {"name": "suva-ft-v3", "ids_digest": ids_digest, "rulings": len(dataset)},
        "messages": {
            "in_db": len(equal) + len(different),
            "missing_in_db": len(missing),
            "equal": len(equal),
            "different": len(different),
            "digest": _digest(equal + different),
        },
        "scores": {"layer1_filter": layer1}
        | {k: scores[k] for k in ("compared", "equal", "max_abs_diff", "scores_digest") if k in scores},
    }
    derived_dir.mkdir(parents=True, exist_ok=True)
    (derived_dir / f"{v.label}.json").write_text(
        json.dumps({"different": sorted(different), "missing": sorted(missing)}, indent=1) + "\n", encoding="utf-8"
    )
    commit, dirty = git_state()
    results = {
        "what": "layer2_judge certification against the D-074 benchmark (docs/LAYER2.md)",
        "version": v.label,
        "git_commit": commit,
        "git_dirty": dirty,
        "expected": expected,
        "truncation": dict(truncation),
        "texts_with_control_tags": neutralised,
        "scores": scores,
        "metrics_source": "results/finetune_benchmark_v3.json (by identity when both parities hold)",
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    path = expected_dir / f"{v.label}.json"
    if write_expected and not path.exists():
        expected_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")
    problems = []
    if different or missing:
        problems.append(f"messages: {len(different)} different, {len(missing)} missing in the database")
    if scores.get("compared") and scores["equal"] != scores["compared"]:
        problems.append(f"scores: {scores['compared'] - scores['equal']} of {scores['compared']} differ")
    if path.exists():
        certified = json.loads(path.read_text(encoding="utf-8"))
        if certified.get("scores", {}).get("layer1_filter") != layer1 or not scores.get("compared"):
            certified, expected = (  # another layer-1 version or no run: only the messages part is certified here
                {k: x for k, x in certified.items() if k != "scores"},
                {k: x for k, x in expected.items() if k != "scores"},
            )
        if certified != expected:
            problems.append(f"differs from the certified {path.relative_to(ROOT)}")
    if problems:
        raise ValidationFailed("; ".join(problems))
    return results


def run_report(conn: psycopg.Connection, run_id: str) -> dict:
    """Aggregates of one layer-2 run (public rulings: no Suva label is read). For results/ (G11)."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT pr.status::text, pr.mode::text, pr.kind::text, pr.git_commit, pr.started_at::text,
                      pr.finished_at::text, pr.resolved_models, pr.model_override, pr.params
               FROM ops.pipeline_run pr WHERE pr.run_id = %s""",
            (run_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise LookupError(f"no run {run_id}")
        keys = (
            "status",
            "mode",
            "kind",
            "git_commit",
            "started_at",
            "finished_at",
            "resolved_models",
            "model_override",
        )
        report: dict = dict(zip(keys, row[:8], strict=True)) | {"run_id": run_id, "params": row[8]}
        cur.execute("SELECT metric_code, value FROM ops.run_metric WHERE run_id = %s ORDER BY 1", (run_id,))
        report["metrics"] = {k: float(v) for k, v in cur.fetchall()}
        base = """FROM triage.assessment a JOIN corpus.ruling r ON r.ruling_id = a.ruling_id
                  LEFT JOIN triage.llm_judgement j ON j.assessment_id = a.assessment_id
                  WHERE a.run_id = %s AND a.step = 'layer2_judge'"""
        cur.execute(f"SELECT r.language::text, count(*) {base} GROUP BY 1 ORDER BY 1", (run_id,))
        report["by_language"] = dict(cur.fetchall())
        cur.execute(
            f"""SELECT r.court, count(*), round(avg(j.p_yes)::numeric, 3)::float {base} GROUP BY 1 ORDER BY 2 DESC""",
            (run_id,),
        )
        report["by_court"] = {c: {"n": n, "mean_p_yes": m} for c, n, m in cur.fetchall()}
        cur.execute(
            f"""SELECT CASE WHEN j.p_yes >= 0.9 THEN 'p>=0.9' WHEN j.p_yes >= 0.5 THEN '0.5<=p<0.9'
                            WHEN j.p_yes >= 0.1 THEN '0.1<=p<0.5' WHEN j.p_yes >= 0.001 THEN '0.001<=p<0.1'
                            WHEN j.p_yes IS NOT NULL THEN 'p<0.001' ELSE 'not judged' END, count(*) {base}
                GROUP BY 1 ORDER BY 1""",
            (run_id,),
        )
        report["p_yes_bands"] = dict(cur.fetchall())
        cur.execute(
            f"""SELECT count(DISTINCT a.score_raw), count(DISTINCT a.score_0_100),
                       count(*) FILTER (WHERE a.score_0_100 = 100), count(*) FILTER (WHERE a.score_0_100 = 0) {base}""",
            (run_id,),
        )
        raw, s100, at100, at0 = cur.fetchone()
        report["ties"] = {"distinct_score_raw": raw, "distinct_score_0_100": s100, "at_100": at100, "at_0": at0}
    return report
