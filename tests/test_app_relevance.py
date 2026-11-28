"""The relevance panel is built by code from the stored run (src/suva_app/relevance.py). No model, no database:
the functions that turn stored values into what the page shows are tested directly."""

from __future__ import annotations

import pytest

from src.suva_app import relevance as rel
from src.triage import scorer as sc

WEIGHTS = {
    name: {"sign": sc.SIGNS[name], "weight": 0.5 * sc.SIGNS[name], "mean": 0.2, "scale": 0.4} for name in sc.FEATURES
}


def row_of(rows: list[dict], name: str) -> dict:
    return next(r for r in rows if r["rule"] == name)


def test_a_rule_that_does_not_apply_has_no_effect_and_one_that_applies_pushes_in_its_direction():
    signals = {"area": "UV", "suva_party": True, "manifestly_unfounded": True, "core_topics": 2}
    rows = rel.rule_rows(sc.features(signals, 0.6), WEIGHTS, read_by_apertus=True)
    assert [r["rule"] for r in rows] == sc.FEATURES
    assert row_of(rows, "suva_party") == {
        "rule": "suva_party", "source": "code", "direction": 1, "applies": True, "value": 1.0, "effect": 1.25,
    }  # fmt: skip
    assert row_of(rows, "manifestly_unfounded")["effect"] == -1.25
    assert row_of(rows, "core_topics")["effect"] == 2.5  # counts twice: two topics
    five = row_of(rows, "five_judges")
    assert five["applies"] is False and five["effect"] == 0 and str(five["effect"]) == "0.0"  # never "-0.0"
    single = row_of(rows, "single_judge")
    assert single["applies"] is False and str(single["effect"]) == "0.0"


def test_the_apertus_rule_is_measured_against_an_average_ruling_and_is_silent_without_a_reading():
    rows = rel.rule_rows(sc.features({"area": "IV"}, 0.6), WEIGHTS, read_by_apertus=True)
    apertus = row_of(rows, "consensus")
    assert apertus["source"] == "apertus" and apertus["applies"] is True
    assert apertus["effect"] == pytest.approx(0.5 * (0.6 - 0.2) / 0.4)
    below = row_of(rel.rule_rows(sc.features({"area": "IV"}, -0.6), WEIGHTS, True), "consensus")
    assert below["effect"] < 0  # shown under "speaks against"
    unread = row_of(rel.rule_rows(sc.features({"area": "KV"}, 0.0), WEIGHTS, read_by_apertus=False), "consensus")
    assert unread["applies"] is False and unread["effect"] == 0


def test_readings_become_levels_between_zero_and_one_and_a_failed_reading_stays_empty():
    levels = {r["reading"]: r["level"] for r in rel.reading_levels(
        {"verdict": 0.9, "yes_strict": None, "scale_generic": 1.0, "scale_area": 5.0, "scale_headnote": 3.0}
    )}  # fmt: skip
    assert levels == {
        "verdict": 0.9,
        "yes_strict": None,
        "scale_generic": 0.0,
        "scale_area": 1.0,
        "scale_headnote": 0.5,
    }
    assert rel.reading_levels(None) == []


@pytest.mark.parametrize(
    ("docket", "area", "reason", "criterion"),
    [
        ("1C_12/2025", "Raumplanung", "wrong_court", "1"),
        ("9C_233/2025", "Finances publiques & droit fiscal", "subject_out", "finances publiques & droit fiscal"),
        ("8C_10/2026", "Unfallversicherung", "not_scored_yet", None),
        ("8C_11/2026", None, "apertus_out_of_scope", None),
    ],
)
def test_a_ruling_without_a_score_gets_layer_ones_reason(docket, area, reason, criterion):
    out = rel.not_assessed(docket, area, None, "Ein Text ohne einschlägige Begriffe.")
    assert out["reason"] == reason and out["criterion"] == criterion
