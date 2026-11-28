# ruff: noqa: E501  (test data: whole sentences of rulings, kept on one line to stay readable)
"""Tests of the extractive writer (src/summarize/extract). The model is the declared fake transport of
tests/test_refine.py: no gateway call (G9)."""

from __future__ import annotations

import pytest

from src.summarize.extract import candidates as cand
from src.summarize.extract import choose, write
from src.summarize.refine.model import Model, ModelFailed
from tests.test_refine import RULING, Fake

FR_RULING = """Arrêt du 3 juin 2025
Composition
Mmes et MM. les Juges fédéraux Viscione, Présidente, Maillard et Métral.
Greffière : Barman Ionta.

Faits :
A. L'assurée a chuté le 7 mai 2023. La CNA a refusé ses prestations par décision sur opposition du 12 octobre 2023.
B. L'assurée interjette un recours en matière de droit public contre cet arrêt, en concluant principalement à sa réforme.
L'Office fédéral de la santé publique a renoncé à se déterminer.

Considérant en droit :
1. Le recours est recevable (art. 82 LTF).

2. La recourante soutient que la cour cantonale aurait violé le droit fédéral en niant son droit aux prestations.

3. Selon la jurisprudence, le droit à des prestations de l'assurance-accidents suppose un lien de causalité naturelle entre l'accident et l'atteinte à la santé (art. 6 al. 1 LAA). Ce lien serait rompu, selon la recourante, par la durée du traitement.
Le statu quo sine a été atteint le 30 juin 2023, de sorte que la CNA pouvait mettre fin à ses prestations.

Par ces motifs, le Tribunal fédéral prononce :
1. Le recours est rejeté.
2. Les frais judiciaires, arrêtés à 800 fr., sont mis à la charge de la recourante.
"""


def model_for(fake: Fake, budget: int = 40) -> Model:
    return Model(fake, budget=budget, labeler=fake.label)


# --- candidates ---------------------------------------------------------------------------------------------------


def test_the_filter_leaves_out_what_a_fiche_never_restates_and_says_why():
    found = cand.candidates(FR_RULING)
    reasons = {sentence[:40]: why for _, why, sentence in found.dropped}
    assert reasons["Le recours est recevable (art. 82 LTF)."[:40]] == "admissibility"
    assert any(why == "operative" for why in reasons.values())
    assert reasons["L'assurée interjette un recours en matière"[:40]] == "proceedings"
    assert reasons["L'Office fédéral de la santé publique a ren"[:40]] == "proceedings"
    assert reasons["La recourante soutient que la cour cantona"[:40]] == "party_argument"
    assert reasons["Ce lien serait rompu, selon la recourante, "[:40]] == "reported"
    kept = [c.text for c in found.kept]
    assert kept[0].startswith("L'assurée a chuté le 7 mai 2023")  # the heading "A." is taken off
    assert any(t.startswith("Selon la jurisprudence, le droit à des prestations") for t in kept)
    assert [c.id for c in found.kept] == [f"S{n}" for n in range(1, len(kept) + 1)]


def test_tags_say_what_a_sentence_holds():
    rule = "Selon la jurisprudence, le droit à des prestations suppose un lien de causalité naturelle (art. 6 al. 1 LAA; ATF 129 V 177)."
    assert cand.tags(rule) == ["article", "case law", "rule formula"]
    assert cand.tags("La cour cantonale a retenu que la recourante travaillait à plein temps.") == ["names a party"]


# --- choose -------------------------------------------------------------------------------------------------------


def test_choose_ranks_considerations_offers_only_their_sentences_and_restores_the_courts_order():
    found = cand.candidates(RULING)
    by_label = {c.label: c.id for c in found.kept}
    v = choose.VERSION
    fake = Fake(**{
        f"{v}/passages": [{"a_point": "Ende der Leistungspflicht", "b_passages": ["E.3"]}],
        f"{v}/rank/E.2.1": [0.9], f"{v}/rank/E.3": [0.8], f"{v}/rank/E.2": [0.1],
        f"{v}/sentences": [{"a_chosen": [
            {"a_id": by_label["E.3"], "b_role": "holding"},
            {"a_id": by_label["E.2.1"], "b_role": "rule"},
            {"a_id": by_label["E.2.1"], "b_role": "condition"},  # a repeat is dropped
            {"a_id": by_label["facts"], "b_role": "fact"},
        ]}, {"a_chosen": [  # the second reading (passages best-ranked first) agrees
            {"a_id": by_label["E.2.1"], "b_role": "rule"}, {"a_id": by_label["E.3"], "b_role": "holding"},
            {"a_id": by_label["facts"], "b_role": "fact"},
        ]}],
    })  # fmt: skip
    choice = choose.choose(RULING, model_for(fake))
    assert [c.label for c, _ in choice.chosen] == ["facts", "E.2.1", "E.3"]  # the court's order, not the answer's
    assert choice.scores == {"E.2": 0.1, "E.2.1": 0.9, "E.3": 0.8}
    sentences_prompt = next(m for v_, m in fake.sent if v_.startswith(f"{v}/sentences"))[-1]["content"]
    assert "[E.2.1]" in sentences_prompt and "[facts]" in sentences_prompt
    assert "Die Beschwerde ist zulässig" not in sentences_prompt  # admissibility never reaches the model
    assert "[article]" in sentences_prompt  # code's hints are shown


def test_the_two_readings_keep_what_both_chose_and_the_best_considerations_sentences():
    a, b, c, d = (cand.Candidate(f"S{n}", label, f"Satz {n} mit genug Wörtern für einen Kandidaten.") for n, label in
                  ((1, "E.2"), (2, "E.3"), (3, "E.3"), (4, "E.4")))  # fmt: skip
    first, second = [(a, "rule"), (b, "rule"), (d, "holding")], [(a, "rule"), (c, "rule"), (d, "holding")]
    kept = choose.consensus(first, second, {"E.2": 0.2, "E.3": 0.9, "E.4": 0.5})
    assert [x.id for x, _ in kept] == ["S4", "S1", "S2"]  # both picked S4, S1 (by score), then the best consideration's


def test_a_sentence_that_points_back_brings_its_antecedent_or_is_left_out():
    rule = cand.Candidate("S1", "E.4", "Das Invalideneinkommen bemisst sich nach den Tabellenlöhnen der LSE.")
    back = cand.Candidate("S2", "E.4", "Dieser Betrag ist als Invalideneinkommen anzurechnen.")
    alone = cand.Candidate("S3", "E.5", "Diese Voraussetzung ist hier erfüllt, wie die Vorinstanz zutreffend festhält.")
    found = cand.Candidates((rule, back, alone), ())
    chosen, notes = choose.complete(found, [(back, "rule"), (alone, "application")])
    assert [c.id for c, _ in chosen] == ["S1", "S2"]
    assert notes == ["S1 added: S2 points back to it",
                     "S3 left out: it points back and its antecedent is not a candidate"]  # fmt: skip


def test_top_takes_the_best_considerations_by_reading():
    assert choose.top({"E.2": 0.2, "E.3": 0.9, "E.4": 0.95, "E.5": 0.1, "E.6": 0.5, "E.7": 0.3}) == [
        "E.4",
        "E.3",
        "E.6",
        "E.7",
        "E.2",
    ]


def test_a_ruling_with_too_few_candidates_goes_to_a_person():
    with pytest.raises(ModelFailed):
        choose.choose("Urteil.\n\nErwägungen:\n1. Kurz.\n", model_for(Fake()))


# --- write --------------------------------------------------------------------------------------------------------

RULE = cand.Candidate(
    "S9",
    "E.3",
    "Selon la jurisprudence, le droit à des prestations de l'assurance-accidents suppose un lien de causalité naturelle entre l'accident et l'atteinte à la santé (art. 6 al. 1 LAA; ATF 129 V 177 consid. 3.1).",
)
FR = {"text": FR_RULING, "language": "fr", "category": "uv", "starred": False}


def test_a_written_sentence_is_kept_when_code_and_the_entailment_reading_agree():
    adapted = "Selon la jurisprudence, le droit à des prestations de l'assurance-accidents suppose un lien de causalité naturelle entre l'accident et l'atteinte à la santé (art. 6 al. 1 LAA)."
    fake = Fake(**{f"{write.VERSION}/0": [{"a_sentence": adapted}]})
    written = write.write_sentence(RULE, "rule", "fr", FR, model_for(fake))
    assert written.status == "written" and written.text == adapted and written.entailment == 0.97
    prompt = fake.sent[0][1][-1]["content"]
    assert "ATF 129 V 177" in prompt and "Adapt this sentence" in prompt


def test_a_sentence_the_source_does_not_entail_gets_one_retry_then_codes_own_clean_copy():
    stronger = "Le droit à des prestations suppose toujours un lien de causalité naturelle et adéquate entre l'accident et l'atteinte à la santé (art. 6 al. 1 LAA)."
    fake = Fake(**{f"{write.VERSION}/0": [{"a_sentence": stronger}], f"{write.VERSION}/1": [{"a_sentence": stronger}],
                   "entail@1/write": [0.2, 0.3]})  # fmt: skip
    written = write.write_sentence(RULE, "rule", "fr", FR, model_for(fake))
    assert written.status == "cleaned"
    assert written.text.endswith(
        "l'atteinte à la santé (art. 6 al. 1 LAA)."
    )  # the reference parenthesis is out, the article stays
    assert "ATF" not in written.text
    retry = next(m for v, m in fake.sent if v == f"{write.VERSION}/1")
    assert "entailment 0.20 below 0.9" in retry[-1]["content"]


def test_a_translation_must_use_the_glossary_term_and_a_failed_one_is_left_out():
    terms = write.required_terms(RULE.text, "fr", "de", "uv")
    assert terms, "the glossary has a term of this sentence"
    src, dst = terms[0]
    bad = "Nach der Rechtsprechung setzt der Anspruch auf Leistungen der Unfallversicherung einen Zusammenhang voraus (Art. 6 Abs. 1 UVG)."
    fake = Fake(**{f"{write.VERSION}/0": [{"a_sentence": bad}], f"{write.VERSION}/1": [{"a_sentence": bad}]})
    written = write.write_sentence(RULE, "rule", "de", {**FR, "language": "fr"}, model_for(fake))
    if write.uses_term(bad, dst):
        pytest.skip(f"the glossary's first term ({dst}) happens to be in the test sentence")
    assert written.status == "dropped" and any("glossary term missing" in p for p in written.problems)
    assert f"Translate '{src}' as '{dst}'" in fake.sent[0][1][-1]["content"]


def test_uses_term_allows_inflection_but_not_a_missing_word():
    assert write.uses_term("mit überwiegender Wahrscheinlichkeit erstellt", "überwiegende Wahrscheinlichkeit")
    assert not write.uses_term("mit Wahrscheinlichkeit erstellt", "überwiegende Wahrscheinlichkeit")


def test_flow_keeps_a_connective_and_refuses_a_change_that_brings_a_number():
    texts = [
        "Der Anspruch setzt einen natürlichen Kausalzusammenhang voraus.",
        "Der Status quo sine war am 30. Juni 2023 erreicht.",
    ]
    fake = Fake(**{write.FLOW_VERSION: [{"a_sentences": [
        {"a_id": "s1", "b_text": "Der Anspruch setzt einen natürlichen Kausalzusammenhang voraus, mindestens zu 50 %."},
        {"a_id": "s2", "b_text": "Hier war der Status quo sine am 30. Juni 2023 erreicht."},
    ]}]})  # fmt: skip
    out, log = write.flow(texts, "de", {"text": RULING, "category": "uv"}, model_for(fake))
    assert out == [texts[0], "Hier war der Status quo sine am 30. Juni 2023 erreicht."]
    assert [entry["accepted"] for entry in log] == [False, True]


def test_the_fiche_ends_with_codes_outcome_sentence():
    found = cand.candidates(RULING)
    chosen = tuple((c, "rule") for c in found.kept if c.label in ("E.2.1", "E.3"))
    choice = choose.Choice("Ende der Leistungspflicht", chosen, len(found.kept), found.reasons())
    fake = Fake(**{f"{write.VERSION}/0": [{"a_sentence": c.text} for c, _ in chosen],
                   write.FLOW_VERSION: [{"a_sentences": [{"a_id": f"s{n}", "b_text": c.text} for n, (c, _) in enumerate(chosen, 1)]}]})  # fmt: skip
    fiche = write.write_fiche(
        choice, "de", {"text": RULING, "language": "de", "category": "uv", "starred": False}, model_for(fake)
    )
    assert fiche.text.startswith(
        "Die Leistungspflicht des Unfallversicherers setzt einen natürlichen Kausalzusammenhang voraus"
    )
    assert fiche.text.endswith("Die Beschwerde wird abgewiesen.")
    assert [w.status for w in fiche.sentences] == ["written"] * len(chosen)


# --- real rulings -------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def corpus():
    from suva_data import db

    try:
        conn = db.connect()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"project database not reachable: {exc}")
    yield conn
    conn.close()


@pytest.mark.parametrize("docket", ["8C_676/2024", "8C_178/2025", "8C_135/2025"])  # DE, FR, IT
def test_real_rulings_keep_considerations_and_facts_and_drop_the_operative_part(corpus, docket):
    from src.summarize import pipeline

    row = corpus.execute("SELECT id FROM rulings WHERE docket = %s", (docket,)).fetchone()
    if row is None:
        pytest.skip(f"{docket} is not in the database")
    found = cand.candidates(pipeline.load_ruling(corpus, row[0])["text"])
    labels = {c.label for c in found.kept}
    assert "operative" not in labels and "facts" in labels
    assert sum(label.startswith("E.") for label in labels) >= 3
    assert len(found.kept) >= 30
    reasons = found.reasons()
    assert reasons.get("operative", 0) > 0 and reasons.get("admissibility", 0) > 0
    assert set(reasons) <= {"operative", "admissibility", "costs", "procedural_law", "citation", "party_argument",
                            "proceedings", "reported", "fragment"}  # fmt: skip


# --- profiles -----------------------------------------------------------------------------------------------------

INCOME = """Urteil vom 3. Juni 2025

Sachverhalt:
A. Die Versicherte verletzte sich am Knie.

Erwägungen:
1. Die Beschwerde ist zulässig.

2. Streitig ist das Invalideneinkommen. Das Invalideneinkommen ist gestützt auf die Tabellenlöhne der LSE zu bestimmen, wenn die versicherte Person keine Erwerbstätigkeit mehr ausübt.

3. Massgebend ist das Kompetenzniveau 1 der Tabelle TA1, weil die Versicherte keine Ausbildung hat. Das Valideneinkommen beträgt Fr. 60'000. Ein Abzug vom Tabellenlohn ist hier nicht gerechtfertigt, weil die Einschränkungen bereits im Zumutbarkeitsprofil berücksichtigt sind.

Demnach erkennt das Bundesgericht:
1. Die Beschwerde wird teilweise gutgeheissen und die Sache wird zu neuer Verfügung an die Suva zurückgewiesen.
2. Die Gerichtskosten werden der Suva auferlegt.
"""


def test_a_profile_is_detected_by_its_own_terms_when_its_article_is_not_cited():
    from src.summarize.extract import profiles

    assert profiles.detect(INCOME).id == "income_comparison"
    assert profiles.detect(RULING) is None  # one mention of causation is not a profile
    assert profiles.remanded(INCOME)


def test_a_referral_of_the_costs_alone_is_not_a_remand():
    from src.summarize.extract import profiles

    costs_only = INCOME.replace(
        "1. Die Beschwerde wird teilweise gutgeheissen und die Sache wird zu neuer Verfügung an die Suva zurückgewiesen.",
        "1. Die Beschwerde wird abgewiesen.",
    ).replace("2. Die Gerichtskosten werden der Suva auferlegt.", "2. Die Sache wird zur Neuverlegung der Kosten zurückgewiesen.")
    assert not profiles.remanded(costs_only)


def test_the_profile_adds_the_sentence_for_an_item_the_court_discusses_and_the_choice_missed():
    from src.summarize.extract import profiles

    found = cand.candidates(INCOME)
    first = next(c for c in found.kept if c.text.startswith("Das Invalideneinkommen ist gestützt"))
    chosen, notes = profiles.check(found, [(first, "rule")], INCOME, {"E.2": 0.9, "E.3": 0.8})
    added = [c.text for c, _ in chosen[1:]]
    assert len(added) == 2  # skill level and deduction are missing; no sentence of this ruling concludes
    assert any("Kompetenzniveau" in t for t in added)
    assert any("Abzug vom Tabellenlohn" in t for t in added)
    assert len(notes) == 2  # the remand is in the operative part only: the considerations give nothing to add


def test_the_courts_conclusion_is_added_when_the_choice_has_none():
    from src.summarize.extract import profiles

    text = RULING.replace("Die Vorinstanz hat die\nLeistungseinstellung daher zu Recht bestätigt.",
                          "Die Vorinstanz hat das richtig gesehen.\nSomit hat die Vorinstanz die Leistungseinstellung zu Recht bestätigt.")  # fmt: skip
    found = cand.candidates(text)
    rule = next(c for c in found.kept if c.label == "E.2.1")
    chosen, notes = profiles.check(found, [(rule, "rule")], text, {"E.2.1": 0.9, "E.3": 0.8})
    assert chosen[-1][0].text.startswith("Somit hat die Vorinstanz") and chosen[-1][1] == "holding"
    assert notes == [f"{chosen[-1][0].id} added for answer"]


def test_a_bracketed_placeholder_is_refused_and_the_outcome_keeps_so_far_as_admissible():
    assert any("brackets" in p for p in write._problems("Der Betrag von [Betrag] Fr. wurde festgelegt und bestätigt.",
                                                        "Le montant de 196 fr. 80 a été fixé et confirmé.", "de", RULING, []))  # fmt: skip
    source = RULING.replace("1. Die Beschwerde wird abgewiesen.", "1. Die Beschwerde wird abgewiesen, soweit darauf einzutreten ist.")
    assert write.with_admissibility("Text. Die Beschwerde wird abgewiesen.", "de", source).endswith(
        "Die Beschwerde wird abgewiesen, soweit darauf einzutreten ist.")
    assert write.with_admissibility("Text. Die Beschwerde wird abgewiesen.", "de", RULING).endswith("abgewiesen.")
