"""Load a stored run of the Suva Scout scorer into the six-schema database (D-094).

    python -m src.scorer load --file data/derived/scorer/run.json [--profile default]

Two runs are written, each in one transaction:

1. layer 2 (`layer2_judge`, the scorer version the profile pins): one assessment per stored ruling that the
   profile's current layer 1 kept, with its score, its German explanation and a ledger row per rule.
2. ranking (`ranking`): one `in_scope` assessment per ruling the scorer's run promoted. A kept ruling it did not
   promote gets no ranking assessment: it stays `potentially`, with its score.

Nothing is recomputed, and nothing is taken on trust either: for every ruling the code rebuilds each rule's input
from the stored facts, checks that the stored contribution is that input times the registered weight, and that the
stored score is the logistic of the intercept plus the contributions. A ruling that fails a check stops the load.

A stored ruling that layer 1 of this database dropped is not loaded (a layer-1 drop is never judged, L2-D06); it is
counted in the run's metrics. A ruling loaded before from the same file is not loaded twice.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import psycopg

from src.db import pg, runs
from src.db.registry import pinned_version, profile_version
from src.scorer.models import ScorerConfig, StoredRuling, StoredRun

CODE_PATHS = ("src/scorer/load.py", "src/scorer/models.py")
READER_MODEL = "apertus-v1-5-70b"
PROMOTED_REASON = "RANK_PROMOTED_BY_SCORER"
TOLERANCE = 1e-6


class StoredRunMismatch(RuntimeError):
    """The stored run does not agree with the registered scorer version, or with itself."""


def inputs(signals: dict[str, Any], consensus: float) -> dict[str, float]:
    """Each rule's input, rebuilt from the stored facts (the scorer's own mapping, scorer@2)."""
    area = signals.get("area")
    return {
        "area_uvmv": float(area in ("UV", "MV")),
        "area_iv": float(area == "IV"),
        "appeal_by_institution": float(bool(signals.get("appeal_by_institution"))),
        "five_judges": float(bool(signals.get("five_judges"))),
        "publication": float(signals.get("proposed_for_publication") is True),
        "manifestly_unfounded": float(bool(signals.get("manifestly_unfounded"))),
        "suva_party": float(bool(signals.get("suva_party"))),
        "single_judge": float(bool(signals.get("single_judge"))),
        "consensus": float(consensus),
        "core_topics": float(signals.get("core_topics") or 0),
        "long_accident": float(bool(signals.get("long_ruling")) and area in ("UV", "MV")),
        "other_accident_insurer": float(bool(signals.get("other_accident_insurer"))),
    }


def read_by_apertus(ruling: StoredRuling) -> bool:
    return any(value is not None for value in (ruling.apertus_readings or {}).values())


def ledger(ruling: StoredRuling, config: ScorerConfig) -> tuple[float, list[dict[str, Any]]]:
    """(logit, one entry per rule in the scorer's order) for one stored ruling, checked against the stored values."""
    key = f"{ruling.docket} ({ruling.decision_date})"
    if set(ruling.contributions) != set(config.features):
        raise StoredRunMismatch(f"{key}: stored rules {sorted(ruling.contributions)} are not the registered ones")
    read = read_by_apertus(ruling)
    values = inputs(ruling.signals, ruling.apertus_consensus or 0.0)
    entries = []
    for name in config.features:
        rule = config.rule_weights[name]
        value = values[name]
        expected = rule.weight * (value - rule.mean) / rule.scale
        stored = ruling.contributions[name]
        if abs(expected - stored) > TOLERANCE:
            raise StoredRunMismatch(
                f"{key}: rule {name}: stored contribution {stored!r}, but the registered weight gives {expected!r} "
                f"for the stored facts (input {value!r})"
            )
        if name in config.apertus_rules:
            applies = read
            effect = expected if read else 0.0  # against an average ruling
        else:
            applies = value != 0
            effect = rule.weight * value / rule.scale  # against a ruling where the fact does not apply
        detail: dict[str, Any] = {"value": value, "contribution": stored, "effect": round(effect, 6) + 0.0}
        if name in config.apertus_rules and read:
            detail["readings"] = ruling.apertus_readings
        entries.append({"rule": name, "applies": applies, "detail": detail})
    logit = config.intercept + sum(ruling.contributions[name] for name in config.features)
    probability = 1.0 / (1.0 + math.exp(-logit))
    if abs(probability - ruling.score) > TOLERANCE:
        raise StoredRunMismatch(
            f"{key}: stored score {ruling.score!r}, but the stored contributions give {probability!r}"
        )
    return logit, entries


_LAYER1 = """
SELECT r.ruling_id::text, r.docket, r.decision_date::text, l1.assessment_id::text, l1.in_suva_scope::text
FROM corpus.ruling r
LEFT JOIN LATERAL (
  SELECT a.assessment_id, a.in_suva_scope
  FROM triage.assessment a
  JOIN ops.pipeline_run pr ON pr.run_id = a.run_id
  JOIN ops.pipeline_profile_version pv ON pv.profile_version_id = pr.profile_version_id
  WHERE a.ruling_id = r.ruling_id AND a.step = 'layer1_filter' AND a.repetition_idx = 0
    AND pv.profile_code = %s AND pr.kind <> 'eval' AND pr.status IN ('succeeded', 'partial')
  ORDER BY a.created_at DESC, a.assessment_id DESC LIMIT 1) l1 ON true
"""


def _fingerprint(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _span(cur: psycopg.Cursor, run: runs.Run, step: str, operation: str, ruling_id: str, version_id: str) -> str:
    span_id = pg.uuid5(f"span|{run.run_id}|{step}|{ruling_id}")
    cur.execute(
        """INSERT INTO ops.span (span_id, run_id, parent_span_id, step, operation, ruling_id, component_version_id,
                                 status, started_at, ended_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, 'ok', clock_timestamp(), clock_timestamp())""",
        (span_id, run.run_id, run.span_id, step, operation, ruling_id, version_id),
    )
    return span_id


_ASSESSMENT = """
INSERT INTO triage.assessment (assessment_id, run_id, ruling_id, step, component_version_id, span_id,
    upstream_assessment_id, input_fingerprint, in_suva_scope, outcome, score_raw, score_0_100, score_source,
    reason_code, explanation_de, mode, started_at, finished_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'ok', %s, %s, %s, %s, %s, %s, clock_timestamp(), clock_timestamp())
"""


def load(conn: psycopg.Connection, path: Path, profile: str = "default") -> dict[str, Any]:
    """Load the stored run at `path`. Returns the counts; `already_loaded` is set when the file was loaded before."""
    raw = path.read_bytes()
    file_sha = hashlib.sha256(raw).hexdigest()
    stored = StoredRun.model_validate_json(raw)

    with conn.cursor() as cur:
        pvid, profile_label = profile_version(cur, profile)
        scorer_id = pinned_version(cur, pvid, "layer2_judge")
        ranking_id = pinned_version(cur, pvid, "ranking")
        cur.execute("SELECT config FROM ops.component_version WHERE component_version_id = %s", (scorer_id,))
        raw_config = cur.fetchone()[0]
        if "rule_weights" not in raw_config:
            raise StoredRunMismatch(
                f"profile {profile} {profile_label} pins a layer2_judge version that is not the scorer"
            )
        config = ScorerConfig.model_validate(raw_config)
        if config.scorer != stored.scorer:
            raise StoredRunMismatch(f"the file is a run of {stored.scorer}, the profile pins {config.scorer}")
        cur.execute(
            """SELECT rl.definition ->> 'feature', rl.rule_id::text, rl.reason_code, cvr.ordinal
               FROM ops.component_version_rule cvr JOIN ops.rule rl ON rl.rule_id = cvr.rule_id
               WHERE cvr.component_version_id = %s AND cvr.enabled""",
            (scorer_id,),
        )
        rules = {feature: (rule_id, reason, ordinal) for feature, rule_id, reason, ordinal in cur.fetchall()}
        if set(rules) != set(config.features):
            raise StoredRunMismatch("the scorer version's rules are not its configured features")
        cur.execute(
            "SELECT run_id::text FROM ops.pipeline_run WHERE kind = 'layer2' AND status = 'succeeded' "
            "AND params ->> 'file_sha256' = %s AND profile_version_id = %s",
            (file_sha, pvid),
        )
        before = cur.fetchone()
        cur.execute(_LAYER1, (profile,))
        layer1 = {(docket, day): (ruling_id, l1_id, scope) for ruling_id, docket, day, l1_id, scope in cur.fetchall()}
    conn.commit()
    if before is not None:
        return {"already_loaded": before[0], "file_sha256": file_sha}

    # Check everything before the first write: a stored run that disagrees with the registry loads nothing.
    checked, not_in_corpus, dropped_by_layer1, no_layer1 = [], 0, 0, 0
    for ruling in stored.rulings:
        logit, entries = ledger(ruling, config)
        found = layer1.get((ruling.docket, ruling.decision_date))
        if found is None:
            not_in_corpus += 1
        elif found[1] is None:
            no_layer1 += 1
        elif found[2] != "potentially":
            dropped_by_layer1 += 1
        else:
            checked.append((ruling, found[0], found[1], logit, entries))
    kept_here = sum(1 for _, l1_id, scope in layer1.values() if l1_id is not None and scope == "potentially")
    counts = {
        "stored_rulings": len(stored.rulings),
        "scored": len(checked),
        "promoted": sum(1 for ruling, *_ in checked if ruling.promoted),
        "read_by_apertus": sum(1 for ruling, *_ in checked if read_by_apertus(ruling)),
        "stored_not_in_corpus": not_in_corpus,
        "stored_dropped_by_layer1": dropped_by_layer1,
        "stored_without_layer1": no_layer1,
        "kept_by_layer1_without_score": kept_here - len(checked),
    }
    params = {
        "source": "stored scorer run",
        "source_run_id": stored.source_run_id,
        "source_created_at": stored.created_at,
        "source_git_commit": stored.git_commit,
        "scorer": stored.scorer,
        "file_sha256": file_sha,
        "profile": profile,
        "profile_version": profile_label,
    }

    scored: dict[str, tuple[str, float, float, str, str | None]] = {}
    run = runs.begin_run(
        conn,
        profile_version_id=pvid,
        kind="layer2",
        step="layer2_judge",
        operation="scorer.load",
        component_version_id=scorer_id,
        params=params,
        code_paths=CODE_PATHS,
        actor="pipeline",
        mode=stored.mode,
        resolved_models={"judge": READER_MODEL},
    )
    try:
        with conn.transaction(), conn.cursor() as cur:
            for ruling, ruling_id, l1_id, logit, entries in checked:
                span_id = _span(cur, run, "layer2_judge", "scorer.load.ruling", ruling_id, scorer_id)
                assessment_id = pg.uuid5(f"assessment|{run.run_id}|layer2_judge|{ruling_id}")
                score = round(ruling.score * 100, 2)
                source = "judged" if read_by_apertus(ruling) else "signals_only"
                cur.execute(
                    _ASSESSMENT,
                    (
                        assessment_id,
                        run.run_id,
                        ruling_id,
                        "layer2_judge",
                        scorer_id,
                        span_id,
                        l1_id,
                        _fingerprint(
                            stored.scorer,
                            stored.source_run_id,
                            ruling.docket,
                            ruling.decision_date,
                            ruling.score,
                            ruling.contributions,
                        ),
                        "potentially",
                        logit,
                        score,
                        source,
                        None,
                        ruling.explanation_de,
                        stored.mode,
                    ),
                )
                for entry in entries:
                    rule_id, reason, ordinal = rules[entry["rule"]]
                    cur.execute(
                        """INSERT INTO triage.assessment_reason (assessment_id, ordinal, rule_id, reason_code, effect,
                                                                 outcome, detail)
                           VALUES (%s, %s, %s, %s, 'signal', %s, %s)""",
                        (
                            assessment_id,
                            ordinal,
                            rule_id,
                            reason,
                            "fired" if entry["applies"] else "not_fired",
                            json.dumps(entry["detail"]),
                        ),
                    )
                scored[ruling_id] = (assessment_id, logit, score, source, ruling.explanation_de)
            runs.metrics(cur, run, "layer2_judge", {k: float(v) for k, v in counts.items()})
            runs.finish_run(cur, run)
    except BaseException as exc:
        runs.fail_run(conn, run, exc)
        raise

    rank = runs.begin_run(
        conn,
        profile_version_id=pvid,
        kind="rank",
        step="ranking",
        operation="scorer.load.promotion",
        component_version_id=ranking_id,
        params={**params, "layer2_run_id": run.run_id},
        code_paths=CODE_PATHS,
        actor="pipeline",
        mode=stored.mode,
    )
    try:
        with conn.transaction(), conn.cursor() as cur:
            for ruling, ruling_id, _l1, _logit, _entries in checked:
                if not ruling.promoted:
                    continue
                l2_id, logit, score, source, explanation = scored[ruling_id]
                span_id = _span(cur, rank, "ranking", "scorer.load.promotion.ruling", ruling_id, ranking_id)
                cur.execute(
                    _ASSESSMENT,
                    (
                        pg.uuid5(f"assessment|{rank.run_id}|ranking|{ruling_id}"),
                        rank.run_id,
                        ruling_id,
                        "ranking",
                        ranking_id,
                        span_id,
                        l2_id,
                        _fingerprint(stored.scorer, stored.source_run_id, ruling.docket, ruling.decision_date, True),
                        "in_scope",
                        logit,
                        score,
                        source,
                        PROMOTED_REASON,
                        explanation,
                        stored.mode,
                    ),
                )
            runs.metrics(cur, rank, "ranking", {"promoted": float(counts["promoted"])})
            runs.finish_run(cur, rank)
    except BaseException as exc:
        runs.fail_run(conn, rank, exc)
        raise
    return {**counts, "layer2_run_id": run.run_id, "ranking_run_id": rank.run_id, "file_sha256": file_sha}
