"""The checks a stored scorer run must pass before it is loaded (src/scorer/load.py, D-094). No database, no model."""

import json
from pathlib import Path

import pytest

from src.scorer.load import StoredRunMismatch, inputs, ledger
from src.scorer.models import RankingConfig, ScorerConfig, SignalRule, StoredRuling

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = json.loads((ROOT / "src/scorer/registry/layer2_scorer.json").read_text(encoding="utf-8"))
CONFIG = ScorerConfig.model_validate(REGISTRY["versions"][0]["config"])

SIGNALS = {
    "area": "UV",
    "suva_party": True,
    "core_topics": 5,
    "long_ruling": False,
    "proposed_for_publication": "unknown",
}
READINGS = {
    "verdict": 0.99,
    "yes_strict": 0.01,
    "scale_generic": 1.0,
    "scale_area": 3.8,
    "scale_headnote": 1.7,
    "scale_tail": 1.0,
}


def stored(signals=SIGNALS, consensus=0.25, readings=READINGS, **changes) -> StoredRuling:
    """A stored ruling whose contributions and score follow from the registered weights."""
    values = inputs(signals, consensus)
    contributions = {
        name: CONFIG.rule_weights[name].weight
        * (values[name] - CONFIG.rule_weights[name].mean)
        / CONFIG.rule_weights[name].scale
        for name in CONFIG.features
    }
    logit = CONFIG.intercept + sum(contributions.values())
    row = {
        "docket": "8C_1/2026",
        "decision_date": "2026-05-01",
        "score": 1 / (1 + 2.718281828459045**-logit),
        "promoted": True,
        "explanation_de": "Vermutlich relevant.",
        "contributions": contributions,
        "signals": signals,
        "apertus_readings": readings,
        "apertus_consensus": consensus,
        "layer1": {"kept": True},
    }
    row.update(changes)
    return StoredRuling.model_validate(row)


def test_registry_file_matches_its_contracts():
    for rule in REGISTRY["rules"]:
        SignalRule.model_validate(rule["definition"])
    assert [r["definition"]["feature"] for r in REGISTRY["rules"]] == CONFIG.features
    assert set(CONFIG.rule_weights) == set(CONFIG.features)
    for name, rule in CONFIG.rule_weights.items():  # a rule never moves the score against its fixed direction
        assert rule.weight * rule.sign >= 0, name
    ranking = json.loads((ROOT / "src/scorer/registry/ranking.json").read_text(encoding="utf-8"))
    RankingConfig.model_validate(ranking["versions"][0]["config"])


def test_a_consistent_ruling_gives_its_logit_and_one_entry_per_rule():
    ruling = stored()
    logit, entries = ledger(ruling, CONFIG)
    assert [e["rule"] for e in entries] == CONFIG.features
    assert logit == pytest.approx(CONFIG.intercept + sum(ruling.contributions.values()))
    by_rule = {e["rule"]: e for e in entries}
    assert by_rule["suva_party"]["applies"] and by_rule["suva_party"]["detail"]["value"] == 1.0
    assert not by_rule["area_iv"]["applies"] and by_rule["area_iv"]["detail"]["effect"] == 0.0
    assert by_rule["consensus"]["detail"]["readings"] == READINGS


def test_a_ruling_apertus_did_not_read_has_no_apertus_effect():
    ruling = stored(consensus=0.0, readings=None)
    _, entries = ledger(ruling, CONFIG)
    consensus = next(e for e in entries if e["rule"] == "consensus")
    assert not consensus["applies"] and consensus["detail"]["effect"] == 0.0 and "readings" not in consensus["detail"]


def test_a_contribution_that_the_weights_do_not_give_stops_the_load():
    good = stored()
    with pytest.raises(StoredRunMismatch, match="rule suva_party"):
        ledger(
            stored(contributions={**good.contributions, "suva_party": good.contributions["suva_party"] + 0.01}), CONFIG
        )


def test_a_score_that_the_contributions_do_not_give_stops_the_load():
    with pytest.raises(StoredRunMismatch, match="stored score"):
        ledger(stored(score=0.5), CONFIG)


def test_a_missing_or_unknown_rule_stops_the_load():
    good = stored()
    fewer = {k: v for k, v in good.contributions.items() if k != "consensus"}
    with pytest.raises(StoredRunMismatch, match="not the registered ones"):
        ledger(stored(contributions=fewer), CONFIG)
