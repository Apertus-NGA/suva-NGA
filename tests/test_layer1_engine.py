"""Layer-1 engine (src/layer1/engine.py): parity with the frozen reference (src/courts.py at 4c246a8, vendored as
src/layer1/reference_courts_4c246a8.py, never the live src/courts.py: L2-F21), evidence offsets, normalisation,
reasons, and the rule ledger: every rule of the version evaluated once per ruling, with its outcome (F-01, F-02, F-03,
F-13)."""

from __future__ import annotations

import functools
import json
from pathlib import Path

import pytest

from src.layer1 import reference_courts_4c246a8 as courts  # the frozen reference V1.0.0 reproduces (D-073)
from src.layer1.engine import Layer1Engine, RuleSpec, fingerprint
from src.layer1.models import Layer1Config
from src.layer1.run import NO_TEXT, explain

REGISTRY = json.loads((Path(__file__).resolve().parents[1] / "src/layer1/registry/layer1_filter.json").read_text())


def specs(version: list[int]) -> list[RuleSpec]:
    ver = next(v for v in REGISTRY["versions"] if v["version"] == version)
    rules = {r["rule_code"]: r for r in REGISTRY["rules"]}
    return [
        RuleSpec(code, rules[code]["definition"]["check"], rules[code]["kind"], i)
        for i, code in enumerate(ver["rules"], 1)
    ]


def engine(version: list[int]) -> Layer1Engine:
    ver = next(v for v in REGISTRY["versions"] if v["version"] == version)
    return Layer1Engine(Layer1Config.model_validate(ver["config"]), specs(version))


V100, V110 = engine([1, 0, 0]), engine([1, 1, 0])

# (docket, legal_area, gegenstand, text): the cases of tests/test_courts.py and the reference's _self_check (4c246a8)
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
    """Drift guard: V1.0.0 is src/courts.py at 4c246a8 (the vendored reference, whose bytes
    tests/test_layer1_reference.py pins). The live src/courts.py may change: that never edits V1.0.0."""
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


LABELS = {
    "L1_KEEP_RUBRIC": "Rechtsgebiet in der Liste",
    "L1_KEEP_RUBRIC_MISSING": "Rechtsgebiet fehlt",
    "L1_KEEP_ACCIDENT_TERM": "Text nennt die Suva",
    "L1_KEEP_CONTRACT_TERM": "Text nennt das VVG",
    "L1_DROP_WRONG_COURT": "Abteilung nicht in der Liste",
    "L1_DROP_WRONG_LETTER": "Verfahrensart nicht berücksichtigt",
    "L1_DROP_RUBRIC_OUT": "Rechtsgebiet nicht in der Liste",
    "L1_FLAG_CLOSED_RUBRIC": "VVG-Begriff, Gebiet ausgeschlossen",
    "L1_SIGNAL_RUBRIC_FROM_TITLE": "Rechtsgebiet aus dem Gegenstand gelesen",
}


def test_explanation_is_german_and_names_the_reason():
    kept = V100.decide("8C_1/2025", {"hf_legal_area": "Unfallversicherung"}, None, "Die Suva.")
    assert explain(kept, LABELS) == "Vorauswahl bestanden: Rechtsgebiet in der Liste. Ebenso: Text nennt die Suva."
    titled = V100.decide("9C_1/2025", {"hf_legal_area": None}, "Berufliche Vorsorge,", None)
    assert explain(titled, LABELS) == (
        "Vorauswahl bestanden: Rechtsgebiet in der Liste."
        " (Rechtsgebiet aus dem Gegenstand gelesen: Berufliche Vorsorge)"
    )


def test_a_drop_explanation_states_what_the_text_check_found():
    """F-03: a drop label states only its own condition; the explanation adds the text outcome from the ledger."""
    no_text = V110.decide("5A_1/2026", {"hf_legal_area": "Erbrecht"}, None, None)
    assert explain(no_text, LABELS) == f"Von der Vorauswahl ausgeschlossen: Abteilung nicht in der Liste. {NO_TEXT}"
    clear = V110.decide("5A_1/2026", {"hf_legal_area": "Erbrecht"}, None, "Erbteilung.")
    assert explain(clear, LABELS) == (
        "Von der Vorauswahl ausgeschlossen: Abteilung nicht in der Liste. "
        "Im Urteilstext geprüft, ohne Treffer: Suchbegriffe zu Suva, Unfall- und Militärversicherung; "
        "Suchbegriffe zu VVG und Taggeldversicherung "
        "(nur die Begriffe der Filterversion; andere Formulierungen erkennt die Prüfung nicht)."
    )
    blocked = V100.decide("9C_1/2025", {"hf_legal_area": "Finances publiques & droit fiscal"}, None, "impôt et LCA")
    assert explain(blocked, LABELS) == (
        "Von der Vorauswahl ausgeschlossen: Rechtsgebiet nicht in der Liste. "
        "Im Urteilstext geprüft, ohne Treffer: Suchbegriffe zu Suva, Unfall- und Militärversicherung "
        "(nur die Begriffe der Filterversion; andere Formulierungen erkennt die Prüfung nicht). "
        "Hinweis: VVG-Begriff, Gebiet ausgeschlossen: «LCA» im Urteilstext gefunden, "
        "Rechtsgebiet «Finances publiques & droit fiscal»."
    )


def test_a_drop_explanation_names_the_term_lists_searched_not_what_the_ruling_says():
    """Review finding: the label of a text keep states a meaning ("Text nennt die Suva ..."). Listed as "ohne Treffer"
    it told a lawyer that a dropped ruling does not name Suva or accident insurance, when the ruling may name them in
    a wording the term list lacks (V1.1.0 does not list "Unfallversicherungsanstalt", Suva's legal name). The
    explanation names the term lists searched and says that other wordings are not recognised."""
    text = "Die Schweizerische Unfallversicherungsanstalt hat Beschwerde geführt."  # synthetic, no party (D-038)
    d = V110.decide("2C_1/2025", {"hf_legal_area": "Steuerrecht"}, None, text)
    assert not d.kept and d.reason_code == "L1_DROP_WRONG_COURT"
    accident = next(e for e in d.evaluations if e.rule_code == "L1_KEEP_ACCIDENT_TERM")
    assert accident.outcome == "not_fired" and accident.detail["pattern"] == "accident_terms"
    explanation = explain(d, LABELS)
    assert LABELS["L1_KEEP_ACCIDENT_TERM"] not in explanation and LABELS["L1_KEEP_CONTRACT_TERM"] not in explanation
    assert "Suchbegriffe zu Suva, Unfall- und Militärversicherung" in explanation
    assert "andere Formulierungen erkennt die Prüfung nicht" in explanation


def test_a_version_without_a_required_rule_is_refused():
    with pytest.raises(ValueError, match="lacks rules"):
        Layer1Engine(V100.config, [RuleSpec("L1_KEEP_RUBRIC", "court_rubric_kept", "keep", 1)])
    without_block = [r for r in specs([1, 1, 0]) if r.check != "text_contract_term_blocked"]
    with pytest.raises(ValueError, match="text_contract_term_blocked"):
        Layer1Engine(V110.config, without_block)


@pytest.mark.parametrize(
    "check,effect,message",
    [
        ("court_rubric_kept", "drop", "check court_rubric_kept is a keep rule, not a drop rule"),
        ("court_not_listed", "flag", "check court_not_listed is a drop rule, not a flag rule"),
        ("text_contract_term_blocked", "keep", "check text_contract_term_blocked is a flag rule, not a keep rule"),
        ("rubric_from_gegenstand", "keep", "check rubric_from_gegenstand is a signal rule, not a keep rule"),
    ],
)
def test_a_rule_whose_kind_is_not_its_checks_effect_is_refused(check, effect, message):
    """F-13: a subject rule bound as a flag used to end in StopIteration at decide time; now the build refuses it."""
    bad = [RuleSpec(r.rule_code, r.check, effect, r.ordinal) if r.check == check else r for r in specs([1, 1, 0])]
    with pytest.raises(ValueError, match=message):
        Layer1Engine(V110.config, bad)


def test_an_unknown_check_or_a_shared_ordinal_is_refused():
    with pytest.raises(ValueError, match="unknown check 'text_language'"):
        Layer1Engine(V110.config, [*specs([1, 1, 0]), RuleSpec("L1_KEEP_LANGUAGE", "text_language", "keep", 10)])
    twice = [RuleSpec(r.rule_code, r.check, r.effect, 1) for r in specs([1, 1, 0])]
    with pytest.raises(ValueError, match="share an ordinal"):
        Layer1Engine(V110.config, twice)


CHECK_ORDER = [
    "court_rubric_kept",
    "court_rubric_missing",
    "text_accident_term",
    "text_contract_term",
    "text_contract_term_blocked",
    "court_not_listed",
    "letter_not_listed",
    "court_rubric_out",
    "rubric_from_gegenstand",
]
RULE_ORDER = [
    "L1_KEEP_RUBRIC",
    "L1_KEEP_RUBRIC_MISSING",
    "L1_KEEP_ACCIDENT_TERM",
    "L1_KEEP_CONTRACT_TERM",
    "L1_FLAG_CLOSED_RUBRIC",
    "L1_DROP_WRONG_COURT",
    "L1_DROP_WRONG_LETTER",
    "L1_DROP_RUBRIC_OUT",
    "L1_SIGNAL_RUBRIC_FROM_TITLE",
]


@pytest.mark.parametrize("docket,area,title,text", CASES)
def test_every_rule_is_evaluated_once_and_the_hits_are_the_fired_ones(docket, area, title, text):
    for eng in (V100, V110):
        d = eng.decide(docket, {"hf_legal_area": area}, title, text)
        assert [e.ordinal for e in d.evaluations] == list(range(1, 10))
        assert [e.rule_code for e in d.evaluations] == RULE_ORDER
        assert all(e.effect == eng.rules[r].effect for e, r in zip(d.evaluations, CHECK_ORDER, strict=True))
        fired = [e for e in d.evaluations if e.outcome == "fired"]
        assert sorted(e.rule_code for e in fired) == sorted(h.rule_code for h in d.hits)
        for h in d.hits:  # the fired evaluation carries the hit's evidence
            e = next(e for e in fired if e.rule_code == h.rule_code)
            assert (e.char_start, e.char_end, e.matched_text) == (h.evidence.start, h.evidence.end, h.evidence.matched)
        subject = [e for e in fired if e.rule_code.startswith(("L1_KEEP_RUBRIC", "L1_DROP_"))]
        assert len(subject) == 1
        decisive = [e for e in fired if e.effect == ("keep" if d.kept else "drop")]
        assert d.reason_code == decisive[0].rule_code  # lowest ordinal (evaluations are in ordinal order)
        for e in d.evaluations:
            assert (e.outcome == "not_applicable") == (e.evidence_field is None)
            if e.outcome == "not_applicable":
                assert e.detail["why"]


def _ledger(d) -> dict[str, tuple]:
    return {e.rule_code: (e.outcome, e.evidence_field, e.examined_value, e.detail.get("why")) for e in d.evaluations}


def test_outcomes_on_a_wrong_court_without_text():
    """F-03: no text and a court outside the list. The court rule fires on the docket head; the rules that need an
    allowed court are not applicable, and so are the text rules: the explanation can say the text was not checked."""
    d = V110.decide("5A_1/2026", {"hf_legal_area": "Erbrecht"}, None, None)
    led = _ledger(d)
    assert led["L1_DROP_WRONG_COURT"] == ("fired", "docket", "5A", None)
    for code in ("L1_DROP_WRONG_LETTER", "L1_KEEP_RUBRIC_MISSING", "L1_KEEP_RUBRIC", "L1_DROP_RUBRIC_OUT"):
        assert led[code] == ("not_applicable", None, None, "court_not_listed")
    for code in ("L1_KEEP_ACCIDENT_TERM", "L1_KEEP_CONTRACT_TERM", "L1_FLAG_CLOSED_RUBRIC"):
        assert led[code] == ("not_applicable", None, None, "text_absent")
    assert led["L1_SIGNAL_RUBRIC_FROM_TITLE"] == ("not_fired", "rubric:hf_legal_area", "Erbrecht", None)
    assert (d.in_suva_scope, d.reason_code) == ("out_of_scope", "L1_DROP_WRONG_COURT")


def test_outcomes_on_a_wrong_letter_a_missing_rubric_and_a_kept_rubric():
    letter = _ledger(V110.decide("4B_1/2025", {"hf_legal_area": "Vertragsrecht"}, None, None))
    assert letter["L1_DROP_WRONG_COURT"] == ("not_fired", "docket", "4B", None)
    assert letter["L1_DROP_WRONG_LETTER"] == ("fired", "docket", "4B", None)
    for code in ("L1_KEEP_RUBRIC_MISSING", "L1_KEEP_RUBRIC", "L1_DROP_RUBRIC_OUT"):
        assert letter[code] == ("not_applicable", None, None, "letter_not_listed")
    missing = _ledger(V110.decide("8C_1/2025", {"hf_legal_area": None}, None, None))
    assert missing["L1_KEEP_RUBRIC_MISSING"] == ("fired", "docket", "8C", None)
    for code in ("L1_KEEP_RUBRIC", "L1_DROP_RUBRIC_OUT"):
        assert missing[code] == ("not_applicable", None, None, "rubric_missing")
    kept = V110.decide("8C_1/2025", {"hf_legal_area": "Unfallversicherung"}, None, "Das Taggeld wird gekürzt.")
    led = _ledger(kept)
    assert led["L1_KEEP_RUBRIC"] == ("fired", "rubric:hf_legal_area", "Unfallversicherung", None)
    assert led["L1_DROP_RUBRIC_OUT"] == ("not_fired", "rubric:hf_legal_area", "Unfallversicherung", None)
    assert led["L1_KEEP_RUBRIC_MISSING"] == ("not_fired", "rubric:hf_legal_area", "Unfallversicherung", None)
    accident = next(e for e in kept.evaluations if e.rule_code == "L1_KEEP_ACCIDENT_TERM")
    assert (accident.outcome, accident.evidence_field, accident.examined_value) == ("not_fired", "full_text", None)
    assert accident.detail == {"pattern": "accident_terms", "text_chars": 25}


def test_the_title_signal_fires_only_when_the_rubric_came_from_the_title():
    titled = V110.decide("9C_1/2025", {"hf_legal_area": None}, "Berufliche Vorsorge,", None)
    signal = next(e for e in titled.evaluations if e.rule_code == "L1_SIGNAL_RUBRIC_FROM_TITLE")
    assert (signal.outcome, signal.evidence_field, signal.matched_text) == (
        "fired",
        "gegenstand",
        "Berufliche Vorsorge",
    )
    listed = V110.decide("9C_1/2025", {"hf_legal_area": "Berufliche Vorsorge"}, "Berufliche Vorsorge,", None)
    signal = next(e for e in listed.evaluations if e.rule_code == "L1_SIGNAL_RUBRIC_FROM_TITLE")
    assert (signal.outcome, signal.detail) == ("not_fired", {"rubric_source": "hf_legal_area"})


def test_a_blocked_contract_term_keeps_its_term_and_offsets():
    """F-02: the contract term matched on a closed rubric is recorded as blocked, with the exact slice of the text."""
    text = "Steuerfrage nach Art. 14 VVG, impôt."
    d = V110.decide("9C_1/2025", {"hf_legal_area": "Finances publiques & droit fiscal"}, None, text)
    blocked = next(e for e in d.evaluations if e.rule_code == "L1_KEEP_CONTRACT_TERM")
    assert blocked.outcome == "blocked" and blocked.evidence_field == "full_text"
    assert text[blocked.char_start : blocked.char_end] == blocked.matched_text == "VVG"
    assert blocked.detail == {
        "pattern": "contract_terms",
        "blocked_by": "L1_FLAG_CLOSED_RUBRIC",
        "closed_rubric_match": "finances publiques",
    }
    flag = next(e for e in d.evaluations if e.rule_code == "L1_FLAG_CLOSED_RUBRIC")
    assert (flag.outcome, flag.evidence_field, flag.matched_text) == (
        "fired",
        "rubric:hf_legal_area",
        "finances publiques",
    )
    assert (d.in_suva_scope, d.reason_code) == ("out_of_scope", "L1_DROP_RUBRIC_OUT")
    assert {h.rule_code for h in d.hits} == {"L1_DROP_RUBRIC_OUT", "L1_FLAG_CLOSED_RUBRIC"}  # the hits as before


def test_absent_text_makes_the_text_rules_not_applicable_with_why():
    for text in (None, "", "   \n"):
        d = V110.decide("8C_1/2025", {"hf_legal_area": "Unfallversicherung"}, None, text)
        for e in d.evaluations:
            if e.rule_code in ("L1_KEEP_ACCIDENT_TERM", "L1_KEEP_CONTRACT_TERM", "L1_FLAG_CLOSED_RUBRIC"):
                assert (e.outcome, e.evidence_field, e.char_start, e.detail) == (
                    "not_applicable",
                    None,
                    None,
                    {"why": "text_absent"},
                )


def test_the_decisive_rule_is_the_fired_keep_with_the_lowest_ordinal():
    """F-13: precedence follows the version's ordinals, not the order the engine happens to evaluate in."""
    case = ("8C_1/2025", {"hf_legal_area": "Unfallversicherung"}, None, "Die Suva ist Partei.")
    assert V110.decide(*case).reason_code == "L1_KEEP_RUBRIC"
    order = {"L1_KEEP_ACCIDENT_TERM": 1, "L1_KEEP_RUBRIC": 3}
    swapped = [RuleSpec(r.rule_code, r.check, r.effect, order.get(r.rule_code, r.ordinal)) for r in specs([1, 1, 0])]
    d = Layer1Engine(V110.config, swapped).decide(*case)
    assert d.reason_code == "L1_KEEP_ACCIDENT_TERM"
    assert [e.rule_code for e in d.evaluations][:3] == [
        "L1_KEEP_ACCIDENT_TERM",
        "L1_KEEP_RUBRIC_MISSING",
        "L1_KEEP_RUBRIC",
    ]


def test_fingerprint_changes_with_any_input():
    base = fingerprint("cv", "8C_1/2025", "2026-04-02", {"hf_legal_area": "x"}, "t", "a" * 64)
    assert base == fingerprint("cv", "8C_1/2025", "2026-04-02", {"hf_legal_area": "x"}, "t", "a" * 64)
    assert base != fingerprint("cv2", "8C_1/2025", "2026-04-02", {"hf_legal_area": "x"}, "t", "a" * 64)
    assert base != fingerprint("cv", "8C_1/2025", "2026-04-02", {"hf_legal_area": "y"}, "t", "a" * 64)


def test_make_run_s2_says_when_the_recall_check_is_skipped(monkeypatch, capsys):
    """F-14: with no Suva label loaded, S2 of `make run` says the blocking recall check did not run.

    Mocks (declared, G9): `src.db.pg.connect` returns a fake connection whose counts are 5 rulings and 0 labels, and
    `src.layer1.run.run_layer1` returns a fixed summary. No database is touched; the DB path is tested in
    tests/test_layer1_db.py (recall exits 1 when a labelled ruling is dropped).
    """
    import src.db.pg as pg
    import src.layer1.run as layer1_run
    from src import cli

    class FakeCursor:
        counts = iter([(5,), (0,)])  # SELECT count(*) FROM corpus.ruling, then FROM gold.label

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql):
            assert sql.startswith("SELECT count(*) FROM ")

        def fetchone(self):
            return next(self.counts)

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def cursor(self):
            return FakeCursor()

    summary = {"kept": 3, "rulings": 5, "profile": "default V0.2.0", "version": "V1.1.0", "golden": "not_comparable"}
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused.invalid/none")
    monkeypatch.setattr(pg, "connect", lambda **kw: FakeConnection())
    monkeypatch.setattr(layer1_run, "run_layer1", lambda conn, **kw: summary | {"files": "data/runs/x"})
    assert cli.run_layer1_stage() == 0
    out = capsys.readouterr().out
    assert "run S2 layer 1: 3 of 5 kept (default V0.2.0, layer1_filter V1.1.0, golden not_comparable)" in out
    assert "SKIPPED run S2 recall: gold.label is empty, so the blocking recall check did not run" in out


def test_golden_status_of_a_database_run():
    """§2.4 Golden in every run: matched, mismatch (the run then fails) or not comparable, with the reason."""
    from src.layer1.golden import compare_run, digest

    lines = ['{"docket": "a"}', '{"docket": "b"}']
    stored = {
        "version": "V1.1.0",
        "ingest_version": "V1.0.0",
        "rulings": 2,
        "kept": 1,
        "dropped": 1,
        "by_reason": {"L1_DROP_WRONG_COURT": 1, "L1_KEEP_RUBRIC": 1},
        "decisions_sha256": digest(lines),
    }
    run = {
        "population": None,
        "snapshot_pinned": True,
        "ingest_versions": {"V1.0.0"},
        "lines": lines,
        "kept": 1,
        "by_reason": {"L1_KEEP_RUBRIC": 1, "L1_DROP_WRONG_COURT": 1},
    }
    assert compare_run(stored, **run)["status"] == "matched"
    changed = compare_run(stored, **run | {"lines": ['{"docket": "a"}', '{"docket": "c"}']})
    assert (changed["status"], changed["differs"]) == ("mismatch", ["decisions_sha256"])
    reasons = {
        "no expected file": compare_run(None, **run),
        "population": compare_run(stored, **run | {"population": "2026Q2_decision"}),
        "not loaded from the snapshot": compare_run(stored, **run | {"snapshot_pinned": False}),
        "loaded by ingest V0.9.0": compare_run(stored, **run | {"ingest_versions": {"V0.9.0"}}),
        "1 rulings decided": compare_run(stored, **run | {"lines": lines[:1]}),
    }
    for expected, result in reasons.items():
        assert result["status"] == "not_comparable" and expected in result["reason"]


# --- layer1_filter V1.2.0 (D-083): two keeps appended after the V1.1.0 ordinals, wider vocabulary ------------------


@functools.cache
def v120() -> Layer1Engine:
    return engine([1, 2, 0])


# (docket, legal_area, gegenstand, text): synthetic cases of the audit findings (dockets not in judgements/, D-031)
V12_CASES = [
    ("4A_901/2025", None, "Haftpflichtrecht; Revision", "Der Kläger verlangt Schadenersatz."),  # F-06: title cut
    (
        "8C_902/2025",
        "Gesundheitswesen & soziale Sicherheit",
        "Invalidenversicherung",
        "Die IV-Stelle verfügte.",
    ),  # F-08
    ("9C_903/2025", "Assicurazione contro le malattie", None, "Diritto: 1. Il ricorso è respinto."),  # F-07: Italian
    ("2C_904/2025", "Steuerrecht", None, "Die Schweizerische Unfallversicherungsanstalt hat Beschwerde geführt."),
    ("6B_905/2025", "Droit pénal", None, "Les prestations de l'assurance accident sont réservées."),  # no hyphen
    ("7B_906/2025", "Procédure pénale", None, "L'assurance accidents a versé des indemnités."),
    ("5A_906/2026", "Erbrecht", None, None),  # G5: no text, a court outside the list
    ("5A_909/2026", "Erbrecht", None, ""),
    ("4A_907/2025", None, "Mietrecht; Kündigung", "Die Kündigung ist gültig."),  # dropped by every version
    ("4B_910/2026", "Vertragsrecht", "Vertragsrecht", "Die Klage wird abgewiesen."),  # wrong letter
    ("8C_908/2025", None, None, "Erwägungen."),  # no rubric, no title: kept as a missing rubric
]
NEWLY_KEPT = {  # V1.1.0 drops these, V1.2.0 keeps them, by this decisive rule
    "4A_901/2025": "L1_KEEP_TITLE_RUBRIC",
    "8C_902/2025": "L1_KEEP_TITLE_RUBRIC",
    "9C_903/2025": "L1_KEEP_RUBRIC",
    "2C_904/2025": "L1_KEEP_ACCIDENT_TERM",
    "6B_905/2025": "L1_KEEP_ACCIDENT_TERM",
    "7B_906/2025": "L1_KEEP_ACCIDENT_TERM",
    "5A_906/2026": "L1_KEEP_TEXT_UNAVAILABLE",
    "5A_909/2026": "L1_KEEP_TEXT_UNAVAILABLE",
}
RULE_ORDER_V120 = [*RULE_ORDER, "L1_KEEP_TEXT_UNAVAILABLE", "L1_KEEP_TITLE_RUBRIC"]


def _decide(eng: Layer1Engine, case: tuple) -> object:
    docket, area, title, text = case
    return eng.decide(docket, {"hf_legal_area": area}, title, text)


@pytest.mark.parametrize("case", V12_CASES, ids=lambda c: c[0])
def test_v120_fixes_each_audited_miss_and_v110_still_drops_it(case):
    """F-06, F-07, F-08, the accident vocabulary (review of stage 2) and G5: each case V1.1.0 drops is kept by V1.2.0
    with the expected decisive rule; the other cases keep the decision V1.1.0 gives them."""
    old, new = _decide(V110, case), _decide(v120(), case)
    if case[0] in NEWLY_KEPT:
        assert (old.in_suva_scope, new.in_suva_scope) == ("out_of_scope", "potentially")
        assert new.reason_code == NEWLY_KEPT[case[0]]
    else:
        assert (new.in_suva_scope, new.reason_code) == (old.in_suva_scope, old.reason_code)


def test_v120_reads_the_title_head_cut_at_a_semicolon():
    d = _decide(v120(), V12_CASES[0])
    title = next(e for e in d.evaluations if e.rule_code == "L1_KEEP_TITLE_RUBRIC")
    assert (title.outcome, title.evidence_field, title.examined_value, title.matched_text) == (
        "fired",
        "gegenstand",
        "Haftpflichtrecht",
        "Haftpflichtrecht",
    )
    assert title.detail == {"pattern": "courts.4.rubrics", "rubric_key": "haftpflichtrecht", "cut_at": "(;,:"}
    assert (d.rubric, d.subject) == ("Haftpflichtrecht; Revision", "subject_out")  # the rubric rule still reads it
    assert any(h.rule_code == "L1_KEEP_TITLE_RUBRIC" and h.evidence.field == "gegenstand" for h in d.hits)


def test_v120_reads_the_title_behind_an_umbrella_rubric():
    d = _decide(v120(), V12_CASES[1])
    led = _ledger(d)
    assert led["L1_DROP_RUBRIC_OUT"] == (
        "fired",
        "rubric:hf_legal_area",
        "Gesundheitswesen & soziale Sicherheit",
        None,
    )
    assert led["L1_KEEP_TITLE_RUBRIC"] == ("fired", "gegenstand", "Invalidenversicherung", None)
    assert (d.in_suva_scope, d.reason_code) == ("potentially", "L1_KEEP_TITLE_RUBRIC")


def test_v120_keeps_the_italian_health_insurance_rubric():
    d = _decide(v120(), V12_CASES[2])
    assert _ledger(d)["L1_KEEP_RUBRIC"] == ("fired", "rubric:hf_legal_area", "Assicurazione contro le malattie", None)
    assert _ledger(d)["L1_KEEP_TITLE_RUBRIC"] == ("not_applicable", None, None, "gegenstand_absent")


@pytest.mark.parametrize(
    "case,matched",
    [
        (V12_CASES[3], "Unfallversicherungsanstalt"),
        (V12_CASES[4], "assurance accident"),
        (V12_CASES[5], "assurance accidents"),
    ],
)
def test_v120_accident_terms_read_suvas_legal_name_and_the_unhyphenated_french_term(case, matched):
    d = _decide(v120(), case)
    accident = next(e for e in d.evaluations if e.rule_code == "L1_KEEP_ACCIDENT_TERM")
    assert accident.outcome == "fired" and accident.matched_text == matched
    assert case[3][accident.char_start : accident.char_end] == matched  # offsets index the original text


@pytest.mark.parametrize("text", [None, "", "   \n"])
def test_v120_keeps_a_ruling_without_text_on_any_court(text):
    """G5: no ruling is dropped on its docket prefix alone. Without a text the term checks cannot run, so the ruling is
    kept, and the ledger says why: the text rules are not applicable, L1_KEEP_TEXT_UNAVAILABLE fired on the missing
    text itself (full_text, no offsets, no match, as the database accepts for an assessment without a text)."""
    d = v120().decide("5A_906/2026", {"hf_legal_area": "Erbrecht"}, None, text)
    led = _ledger(d)
    assert led["L1_DROP_WRONG_COURT"] == ("fired", "docket", "5A", None)
    assert led["L1_KEEP_TEXT_UNAVAILABLE"] == ("fired", "full_text", None, None)
    assert led["L1_KEEP_TITLE_RUBRIC"] == ("not_applicable", None, None, "court_not_listed")
    for code in ("L1_KEEP_ACCIDENT_TERM", "L1_KEEP_CONTRACT_TERM", "L1_FLAG_CLOSED_RUBRIC"):
        assert led[code] == ("not_applicable", None, None, "text_absent")
    unavailable = next(e for e in d.evaluations if e.rule_code == "L1_KEEP_TEXT_UNAVAILABLE")
    assert (unavailable.char_start, unavailable.matched_text) == (None, None)
    assert unavailable.detail == {"text_chars": len(text or "")}
    assert (d.in_suva_scope, d.reason_code, d.subject, d.text) == (
        "potentially",
        "L1_KEEP_TEXT_UNAVAILABLE",
        "wrong_court",
        "text_absent",
    )
    assert explain(d, LABELS_V120) == "Vorauswahl bestanden: Kein Urteilstext verfügbar."
    assert V110.decide("5A_906/2026", {"hf_legal_area": "Erbrecht"}, None, text).reason_code == "L1_DROP_WRONG_COURT"


def test_v120_title_rule_says_why_it_did_not_apply_or_did_not_fire():
    led = _ledger(_decide(v120(), V12_CASES[8]))
    assert led["L1_KEEP_TITLE_RUBRIC"] == ("not_fired", "gegenstand", "Mietrecht", None)
    assert led["L1_KEEP_TEXT_UNAVAILABLE"] == ("not_fired", "full_text", None, None)
    assert _ledger(_decide(v120(), V12_CASES[9]))["L1_KEEP_TITLE_RUBRIC"][3] == "letter_not_listed"
    assert _ledger(_decide(v120(), V12_CASES[10]))["L1_KEEP_TITLE_RUBRIC"][3] == "gegenstand_absent"
    blank_title = v120().decide("4A_901/2025", {"hf_legal_area": "Vertragsrecht"}, " ;(x)", "Text.")
    assert _ledger(blank_title)["L1_KEEP_TITLE_RUBRIC"][3] == "gegenstand_absent"


@pytest.mark.parametrize("case", CASES + V12_CASES, ids=lambda c: c[0])
def test_v120_keeps_everything_v110_keeps_with_the_same_reason(case):
    """Monotone by construction: the new keeps come after every V1.1.0 ordinal, so the decisive rule of a ruling
    V1.1.0 keeps does not change."""
    old, new = _decide(V110, case), _decide(v120(), case)
    if old.kept:
        assert (new.in_suva_scope, new.reason_code) == ("potentially", old.reason_code)


@pytest.mark.parametrize("case", CASES + V12_CASES, ids=lambda c: c[0])
def test_v120_evaluates_its_eleven_rules_once_and_the_hits_are_the_fired_ones(case):
    d = _decide(v120(), case)
    assert [e.ordinal for e in d.evaluations] == list(range(1, 12))
    assert [e.rule_code for e in d.evaluations] == RULE_ORDER_V120
    fired = [e for e in d.evaluations if e.outcome == "fired"]
    assert sorted(e.rule_code for e in fired) == sorted(h.rule_code for h in d.hits)
    for h in d.hits:
        e = next(e for e in fired if e.rule_code == h.rule_code)
        assert (e.char_start, e.char_end, e.matched_text) == (h.evidence.start, h.evidence.end, h.evidence.matched)
    decisive = [e for e in fired if e.effect == ("keep" if d.kept else "drop")]
    assert d.reason_code == decisive[0].rule_code


def test_v120_is_v110_plus_the_approved_changes():
    """Drift guard of D-083: V1.2.0 = V1.1.0 + the Italian health rubric on courts 8 and 9 + the title-rubric cut +
    two accident terms + two rules appended; nothing else. V1.0.0 and V1.1.0 have no title-rubric setting."""
    raw = {tuple(v["version"]): v for v in REGISTRY["versions"]}
    old, new = raw[(1, 1, 0)], raw[(1, 2, 0)]
    assert (new["previous"], new["bump_kind"], new["decision"]) == ([1, 1, 0], "minor", "D-083")
    assert new["rules"] == [*old["rules"], "L1_KEEP_TEXT_UNAVAILABLE", "L1_KEEP_TITLE_RUBRIC"]
    a, b = old["config"], new["config"]
    assert set(b) - set(a) == {"title_rubric"} and b["title_rubric"] == {"cut_at": "(;,:"}
    assert "title_rubric" not in raw[(1, 0, 0)]["config"]
    assert V100.config.title_rubric is None and V110.config.title_rubric is None
    for key in ("rubric_sources", "title_head", "normalise", "contract_terms", "closed_rubrics"):
        assert b[key] == a[key], key
    assert b["courts"]["4"] == a["courts"]["4"]
    for digit in ("8", "9"):
        assert b["courts"][digit]["letters"] == a["courts"][digit]["letters"]
        assert set(b["courts"][digit]["rubrics"]) - set(a["courts"][digit]["rubrics"]) == {
            "assicurazione contro le malattie"
        }
        assert set(a["courts"][digit]["rubrics"]) <= set(b["courts"][digit]["rubrics"])
    widened = a["accident_terms"].replace("unfallversicherern|", "unfallversicherern|unfallversicherungsanstalt|")
    assert b["accident_terms"] == widened.replace("assurance-accidents?", "assurance[- ]accidents?")


def test_a_title_rule_without_its_cut_setting_is_refused():
    title_rule = RuleSpec("L1_KEEP_TITLE_RUBRIC", "title_rubric_kept", "keep", 10)
    with pytest.raises(ValueError, match="title_rubric_kept needs config.title_rubric"):
        Layer1Engine(V110.config, [*specs([1, 1, 0]), title_rule])
    with pytest.raises(ValueError, match="check text_unavailable is a keep rule, not a drop rule"):
        Layer1Engine(
            V110.config, [*specs([1, 1, 0]), RuleSpec("L1_KEEP_TEXT_UNAVAILABLE", "text_unavailable", "drop", 10)]
        )


LABELS_V120 = LABELS | {
    "L1_KEEP_TEXT_UNAVAILABLE": "Kein Urteilstext verfügbar",
    "L1_KEEP_TITLE_RUBRIC": "Rechtsgebiet laut Gegenstand in der Liste",
}


def test_the_layer1_log_closes_on_every_v120_keep():
    """The `layer1-log-1` audit log (the frozen reference, not edited) keeps a ruling when its subject or its text
    action passes; its closure checks fail a run otherwise. A V1.2.0 keep that the reference does not know is logged as
    a subject pass (title rubric, criterion = the cut head) or a text pass (no text, criterion empty_text)."""
    from src.layer1.run import _log_row, _reference_row

    rows = {}
    for docket, area, title, text in CASES + V12_CASES:
        fields = {"neuheiten": None, "hf_legal_area": area}
        d = v120().decide(docket, fields, title, text)
        ref = _reference_row(docket, fields, title, text)
        same = (ref["kept"], ref["subject"], ref["text"]) == (d.kept, d.subject, d.text)
        rows[(docket, title)] = ref if same else _log_row(ref, d)
    log = courts.build_layer1_log(list(rows.values()), {"phase": "layer1"})
    assert log["quality"]["all_checks_passed"], log["quality"]
    title_row = rows[("4A_901/2025", "Haftpflichtrecht; Revision")]
    assert (title_row["subject"], title_row["subject_pass"], title_row["subject_criterion"]) == (
        "kept_title_rubric",
        True,
        "haftpflichtrecht",
    )
    assert (title_row["path"], title_row["kept"]) == ("subject_only", True)
    no_text = rows[("5A_906/2026", None)]
    assert (no_text["text"], no_text["text_pass"], no_text["text_criterion"], no_text["path"]) == (
        "kept_text_unavailable",
        True,
        "empty_text",
        "text_only",
    )
