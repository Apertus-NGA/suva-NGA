"""Layer-1 engine (src/layer1/engine.py): parity with src/courts.py, evidence offsets, normalisation, reasons."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src import courts
from src.layer1.engine import Layer1Engine, RuleSpec, fingerprint
from src.layer1.models import Layer1Config
from src.layer1.run import explain

REGISTRY = json.loads((Path(__file__).resolve().parents[1] / "src/layer1/registry/layer1_filter.json").read_text())


def engine(version: list[int]) -> Layer1Engine:
    ver = next(v for v in REGISTRY["versions"] if v["version"] == version)
    rules = {r["rule_code"]: r for r in REGISTRY["rules"]}
    specs = [
        RuleSpec(code, rules[code]["definition"]["check"], rules[code]["kind"], i)
        for i, code in enumerate(ver["rules"], 1)
    ]
    return Layer1Engine(Layer1Config.model_validate(ver["config"]), specs)


V100, V110 = engine([1, 0, 0]), engine([1, 1, 0])

# (docket, legal_area, gegenstand, text): the cases of tests/test_courts.py and src/courts.py _self_check
CASES = [
    ("8C_78/2025", "Unfallversicherung", None, None),
    ("4A_106/2025", "Vertragsrecht*", None, None),
    ("9C_65/2025", "Assicurazione per l'invalidità", None, None),
    ("8C_748/2024", "Arbeitslosenversicherung", None, "La CNA est intimée."),
    ("8C_748/2024", "Arbeitslosenversicherung", None, "Le recours est rejeté."),
    ("6B_1/2025", "Droit pénal", None, "application de l'art. 6 UVG"),
    ("4A_1/2025", "Obligationenrecht (allgemein)", None, "Art. 14 Abs. 2 VVG."),
    ("4A_2/2025", "Gesellschaftsrecht", None, "Die Taggeldversicherung deckt den Ausfall."),
    ("7B_1/2025", "Procédure pénale", None, "art. 95c LCA (RS 221.229.1)"),
    ("8C_748/2024", "Arbeitslosenversicherung", None, "Das Taggeld wird gekürzt."),
    ("8C_748/2024", "Arbeitslosenversicherung", None, "Art. 14 Abs. 2 VVG."),
    ("8C_1/2025", "Assurance-chômage", None, "les indemnités journalières sont réduites"),
    ("8C_748/2024", "Arbeitslosenversicherung", None, "La CNA est intimée. Art. 14 VVG."),
    ("8C_1/2025", None, None, None),
    ("8C_1/2025", "   ", None, None),
    ("7B_1/2025", None, None, None),
    ("4B_1/2025", "Vertragsrecht", None, None),
    ("9C_1/2025", None, "Berufliche Vorsorge,", None),
    ("4A_1/2025", None, "contrat de travail,", None),
    ("9F_1/2025", None, None, None),
    ("8C_1/2025", "Militärversicherung", None, None),
    ("4A_1/2025", "Haftpflichtrecht", None, None),
    ("4A_1/2025", "Schuldbetreibungs- und Konkursrecht", None, None),
    ("5A_1/2025", "Droit des contrats", None, None),
    ("9C_1/2025", "Finances publiques & droit fiscal", None, "impôt et LCA"),
    ("12T_1/2025", None, "Aufsicht,", "Die Suva."),
]


@pytest.mark.parametrize("docket,area,title,text", CASES)
def test_v100_reproduces_courts(docket, area, title, text):
    ref = courts.gate_record(docket, area, title, text)
    got = V100.decide(docket, {"hf_legal_area": area}, title, text)
    assert (got.kept, got.subject, got.text) == (ref["kept"], ref["subject"], ref["text"])


def test_v100_configuration_is_courts_constants():
    """Drift guard: V1.0.0 is src/courts.py at 4c246a8. If courts.py changes, add a version, do not edit V1.0.0."""
    cfg = V100.config
    assert cfg.accident_terms == courts._TEXT_TERMS.pattern
    assert cfg.contract_terms == courts._CONTRACT_TERMS.pattern
    assert cfg.closed_rubrics == courts._CLOSED_RUBRIC.pattern
    assert {d: set(c.rubrics) for d, c in cfg.courts.items()} == {d: set(r) for d, r in courts.AREAS.items()}
    assert {d: set(c.letters) for d, c in cfg.courts.items()} == {d: set(r) for d, r in courts.LETTERS.items()}


def test_every_decision_has_one_subject_rule_and_a_reason():
    for docket, area, title, text in CASES:
        d = V110.decide(docket, {"hf_legal_area": area}, title, text)
        subject_hits = [h for h in d.hits if h.rule_code.startswith(("L1_KEEP_RUBRIC", "L1_DROP_"))]
        assert len(subject_hits) == 1
        assert d.reason_code
        assert (d.score_0_100 == 0.0) == (d.in_suva_scope == "out_of_scope")


def test_evidence_points_into_the_original_text_even_when_folding_changes_its_length():
    text = "Strasse und Straße: die SUVA ist Partei."  # ß folds to ss: the folded text is one character longer
    d = V100.decide("6B_1/2025", {"hf_legal_area": "Droit pénal"}, None, text)
    hit = next(h for h in d.hits if h.rule_code == "L1_KEEP_ACCIDENT_TERM")
    assert text[hit.evidence.start : hit.evidence.end] == "SUVA"
    assert hit.evidence.matched == "SUVA"


def test_contract_term_on_a_closed_rubric_is_flagged_not_kept():
    d = V100.decide("9C_1/2025", {"hf_legal_area": "Finances publiques & droit fiscal"}, None, "impôt et LCA")
    assert not d.kept and d.reason_code == "L1_DROP_RUBRIC_OUT"
    assert any(h.rule_code == "L1_FLAG_CLOSED_RUBRIC" and h.evidence.matched == "finances publiques" for h in d.hits)


def test_v110_normalises_typographic_apostrophes_and_widens_accident_terms():
    rubric = {"hf_legal_area": "Assicurazione per l’invalidità"}
    assert V100.decide("9C_2/2025", rubric, None, None).subject == "subject_out"
    assert V110.decide("9C_2/2025", rubric, None, None).subject == "kept_subject"
    text = "Der Unfallversicherer hat geleistet."
    assert not V100.decide("2C_1/2025", {"hf_legal_area": "Steuerrecht"}, None, text).kept
    assert V110.decide("2C_1/2025", {"hf_legal_area": "Steuerrecht"}, None, text).kept


def test_rubric_read_from_the_title_is_signalled():
    d = V100.decide("9C_1/2025", {"hf_legal_area": None}, "Berufliche Vorsorge,", None)
    assert d.rubric == "Berufliche Vorsorge" and d.rubric_source == "gegenstand_head"
    assert any(h.rule_code == "L1_SIGNAL_RUBRIC_FROM_TITLE" for h in d.hits)


def test_neuheiten_rubric_wins_over_hf_legal_area():
    d = V100.decide(
        "8C_1/2025", {"neuheiten": "Unfallversicherung", "hf_legal_area": "Arbeitslosenversicherung"}, None, None
    )
    assert d.rubric_source == "neuheiten" and d.kept


def test_explanation_is_german_and_names_the_reason():
    labels = {
        "L1_KEEP_RUBRIC": "Rechtsgebiet in der Liste",
        "L1_KEEP_ACCIDENT_TERM": "Text nennt die Suva",
        "L1_DROP_RUBRIC_OUT": "Rechtsgebiet ausserhalb der Liste",
        "L1_FLAG_CLOSED_RUBRIC": "VVG-Begriff, Gebiet ausgeschlossen",
        "L1_SIGNAL_RUBRIC_FROM_TITLE": "Rechtsgebiet aus dem Gegenstand gelesen",
    }
    kept = V100.decide("8C_1/2025", {"hf_legal_area": "Unfallversicherung"}, None, "Die Suva.")
    assert explain(kept, labels) == "Vorauswahl bestanden: Rechtsgebiet in der Liste. Ebenso: Text nennt die Suva."
    dropped = V100.decide("9C_1/2025", {"hf_legal_area": "Finances publiques & droit fiscal"}, None, "LCA")
    assert explain(dropped, labels).startswith("Von der Vorauswahl ausgeschlossen: Rechtsgebiet ausserhalb der Liste.")


def test_a_version_without_a_required_rule_is_refused():
    with pytest.raises(ValueError, match="lacks rules"):
        Layer1Engine(V100.config, [RuleSpec("L1_KEEP_RUBRIC", "court_rubric_kept", "keep", 1)])


def test_fingerprint_changes_with_any_input():
    base = fingerprint("cv", "8C_1/2025", "2026-04-02", {"hf_legal_area": "x"}, "t", "a" * 64)
    assert base == fingerprint("cv", "8C_1/2025", "2026-04-02", {"hf_legal_area": "x"}, "t", "a" * 64)
    assert base != fingerprint("cv2", "8C_1/2025", "2026-04-02", {"hf_legal_area": "x"}, "t", "a" * 64)
    assert base != fingerprint("cv", "8C_1/2025", "2026-04-02", {"hf_legal_area": "y"}, "t", "a" * 64)
