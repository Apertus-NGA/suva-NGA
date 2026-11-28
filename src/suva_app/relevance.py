"""Why a ruling has its score, as the ruling page shows it, and the rule table behind every score.

Everything here is read or computed by code from what the triage run stored (``predictions.details``,
``model_runs.params``): no model is called, and the same ruling always gets the same explanation.

- ``explain``: for one ruling, the rules with what each does to this ruling's score, the six Apertus
  readings, the facts that carry no weight, or the reason layer 1 did not keep the ruling.
- ``scoring``: the rule table of the current run (direction and weight of each rule) and what it measured.
"""

from __future__ import annotations

from typing import Any

from src import courts
from src.triage import scorer as sc

APERTUS_RULES = frozenset({"consensus"})  # every other rule is a fact read by code
COUNTED = frozenset({"core_topics"})  # a count, not yes/no
SCALE_READINGS = frozenset({"scale_generic", "scale_area", "scale_headnote", "scale_tail"})  # levels 1 to 5


def rule_rows(values: list[float], weights: dict[str, dict[str, float]], read_by_apertus: bool) -> list[dict[str, Any]]:
    """One row per rule, in the order of ``scorer.FEATURES``.

    ``effect`` is the rule's push on the score's log-odds for this ruling: for a fact, against a ruling where
    the fact does not apply (so a rule that does not apply has effect 0); for the Apertus consensus, against an
    average ruling. ``applies`` says whether the rule is shown as a reason.
    """
    rows = []
    for name, value in zip(sc.FEATURES, values, strict=True):
        rule = weights[name]
        if name in APERTUS_RULES:
            effect = rule["weight"] * (value - rule["mean"]) / rule["scale"] if read_by_apertus else 0.0
            applies = read_by_apertus
        else:
            effect = rule["weight"] * value / rule["scale"]
            applies = value != 0
        rows.append(
            {
                "rule": name,
                "source": "apertus" if name in APERTUS_RULES else "code",
                "direction": sc.SIGNS[name],
                "applies": applies,
                "value": value,
                "effect": round(effect, 3) + 0.0,  # never "-0.0"
            }
        )
    return rows


def reading_levels(readings: dict[str, float | None] | None) -> list[dict[str, Any]]:
    """Each Apertus reading as a level between 0 and 1 (a five-step scale is mapped from 1..5); None if it failed."""
    out = []
    for name, value in sorted((readings or {}).items()):
        level = None if value is None else (value - 1) / 4 if name in SCALE_READINGS else value
        out.append({"reading": name, "level": None if level is None else round(min(max(level, 0.0), 1.0), 3)})
    return out


def not_assessed(docket: str, area: str | None, subject: str | None, text: str | None) -> dict[str, Any]:
    """Why a ruling has no score: the reason code of layer 1 (``src/courts.py``), read again by code.

    ``wrong_court`` / ``wrong_letter`` / ``subject_out``: layer 1's subject decision, with the value it read.
    ``apertus_out_of_scope``: code could not read the matter and Apertus read it as outside Suva's fields.
    ``not_scored_yet``: layer 1 keeps the ruling; it was added after the last triage run.
    """
    gate = courts.decide(docket, area, text, subject)
    if gate.kept and not gate.needs_apertus:
        return {"reason": "not_scored_yet", "criterion": None}
    if gate.needs_apertus:
        return {"reason": "apertus_out_of_scope", "criterion": None}
    return {"reason": gate.subject, "criterion": gate.subject_criterion, "text": gate.text}


def explain(conn: Any, ruling_id: int) -> dict[str, Any] | None:
    """The relevance panel of one ruling; None when the ruling does not exist."""
    ruling = conn.execute(
        """SELECT r.docket, r.area, r.subject, t.text
           FROM rulings r LEFT JOIN ruling_texts t ON t.ruling_id = r.id AND t.is_canonical
           WHERE r.id = %s""",
        (ruling_id,),
    ).fetchone()
    if ruling is None:
        return None
    prediction = conn.execute(
        """SELECT round(p.score * 100)::int, p.relevant, p.explanation, p.details, m.params
           FROM predictions p JOIN model_runs m ON m.id = p.run_id
           WHERE p.ruling_id = %s AND p.is_current""",
        (ruling_id,),
    ).fetchone()
    if prediction is None:
        return {"state": "not_assessed", **not_assessed(*ruling)}
    score, relevant, sentence, details, params = prediction
    details, weights = details or {}, (params or {}).get("rule_weights")
    out: dict[str, Any] = {"state": "scored", "score": score, "suspected": bool(relevant), "sentence_de": sentence}
    signals = details.get("signals") or {}
    readings = details.get("apertus_readings")
    read_by_apertus = bool(readings) and any(v is not None for v in readings.values())
    if weights and set(weights) == set(sc.FEATURES):
        values = sc.features(signals, float(details.get("apertus_consensus") or 0.0))
        out["rules"] = rule_rows(values, weights, read_by_apertus)
    else:  # a run stored before the rule table was kept: nothing to compute from
        out["rules"] = []
    out["read_by_apertus"] = read_by_apertus
    out["readings"] = reading_levels(readings) if read_by_apertus else []
    topics = signals.get("core_topic_names") or ""
    out["facts"] = {
        "appeal_upheld": signals.get("appeal_upheld"),
        "core_topics": [name for name in topics.split(", ") if name],
        "bench_size": signals.get("bench_size"),
        "suva_appellant": signals.get("suva_appellant"),
    }
    out["layer1"] = details.get("layer1")
    return out


def scoring(conn: Any) -> dict[str, Any] | None:
    """The rule table and the measurements of the latest triage run; None before any run."""
    run = conn.execute(
        "SELECT id, created_at, models, params FROM model_runs WHERE kind = 'triage' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if run is None:
        return None
    run_id, created_at, models, params = run
    weights = params.get("rule_weights") or {}
    rules = [
        {
            "rule": name,
            "source": "apertus" if name in APERTUS_RULES else "code",
            "direction": sc.SIGNS[name],
            "weight": round(weights[name]["weight"], 3),
            # what the rule does to the log-odds when it applies (a fact), or per standard deviation (Apertus)
            "effect": round(weights[name]["weight"] / (1.0 if name in APERTUS_RULES else weights[name]["scale"]), 3),
            "share": round(weights[name]["mean"], 3) if name not in APERTUS_RULES | COUNTED else None,
        }
        for name in sc.FEATURES
        if name in weights
    ]
    counts = conn.execute(
        "SELECT count(*), count(*) FILTER (WHERE relevant) FROM predictions WHERE is_current AND run_id = %s", (run_id,)
    ).fetchone()
    return {
        "run_id": run_id,
        "created_at": created_at,
        "pipeline": params.get("pipeline"),
        "scorer": params.get("scorer"),
        "models": models,
        "rules": rules,
        "intercept": params.get("intercept"),
        "readings": sorted(params.get("reading_prompts") or {}),
        "measured": params.get("measured"),
        "share_promoted": sc.CORE_SHARE,
        "scored": counts[0],
        "suspected": counts[1],
    }
