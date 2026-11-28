"""Tests of the v3 verification confidence (src/summarize/v3/confidence.py): code only, no model."""

from __future__ import annotations

from src.summarize.v3.confidence import HIGH, RECORD_REVIEW_CAP, confidence
from src.summarize.v3.types import Fiche, Proposition, Record, Sentence


def record(status: str = "ok") -> Record:
    props = (
        Proposition("P1", "fact", "court", "facts", "S1", "Der Versicherte stürzte."),
        Proposition("P2", "rule", "court", "E.2", "S4", "Die Leistungspflicht setzt einen Kausalzusammenhang voraus."),
        Proposition("P3", "answer", "court", "E.3", "S6", "Die Vorinstanz hat die Einstellung zu Recht bestätigt."),
    )
    return Record(props, "rejected", False, {}, None, [], status)


def fiche(sentences: list[Sentence], missing: list[str] | None = None) -> Fiche:
    return Fiche("text", sentences, missing or [], [], 3, "ok")


def test_a_fully_verified_fiche_is_high_and_says_why():
    out = confidence(record(), fiche([Sentence("a", ("P1",), "written", [], 0.99),
                                      Sentence("b", ("P2",), "written", [], 0.97),
                                      Sentence("c", ("P3",), "written", [], 0.98)]))  # fmt: skip
    assert out["score"] >= HIGH and out["level"] == "high"
    assert out["reasons"] == ["every required point is stated and every sentence passed its checks"]
    assert out["parts"]["coverage"] == 1.0


def test_a_missing_required_point_and_a_removed_sentence_lower_the_score_and_are_named():
    full = confidence(record(), fiche([Sentence("b", ("P2",), "written", [], 0.97),
                                       Sentence("c", ("P3",), "written", [], 0.98)]))  # fmt: skip
    out = confidence(record(), fiche([Sentence("b", ("P2",), "written", [], 0.97),
                                      Sentence("c", ("P3",), "removed", ["entailment 0.2"], 0.2)], ["P3"]))  # fmt: skip
    assert out["score"] < full["score"] and out["level"] != "high"
    assert any("1 of 2 required points not stated (P3)" in r for r in out["reasons"])
    assert any("failed their checks" in r for r in out["reasons"])
    assert out["parts"]["coverage"] == 0.5 and out["parts"]["kept"] == 0.5
    one_missing = confidence(record(), fiche([Sentence("b", ("P2",), "written", [], 1.0)] * 9, ["P3"]))
    assert one_missing["level"] == "medium" and one_missing["score"] == HIGH - 1  # never "high" with a point missing


def test_a_record_that_needs_review_caps_the_score():
    out = confidence(record("needs_review"), fiche([Sentence("b", ("P2",), "written", [], 0.99),
                                                    Sentence("c", ("P3",), "written", [], 0.99)]))  # fmt: skip
    assert out["score"] <= RECORD_REVIEW_CAP and "could not be checked" in out["reasons"][0]


def test_a_repaired_sentence_counts_as_kept_but_not_as_first_pass():
    out = confidence(record(), fiche([Sentence("b", ("P2",), "repaired", ["attempt 1: x"], 0.95),
                                      Sentence("c", ("P3",), "written", [], 0.98)]))  # fmt: skip
    assert out["parts"]["kept"] == 1.0 and out["parts"]["first_pass"] == 0.5
    assert any("rewritten once" in r for r in out["reasons"])
