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
    fake = Echo()  # answers by content: sentences are written in parallel, so an answer queue would mix them up
    fiche = write.write_fiche(
        choice, "de", {"text": RULING, "language": "de", "category": "uv", "starred": False},
        Model(fake, budget=60, labeler=fake.label),
    )
    assert fiche.text.startswith(
        "Die Leistungspflicht des Unfallversicherers setzt einen natürlichen Kausalzusammenhang voraus"
    )
    assert fiche.text.endswith("Die Beschwerde wird abgewiesen.")
    statuses = [w.status for w in fiche.sentences]
    assert set(statuses) <= {"written", "copied"} and len(statuses) == len(chosen)
    for w in fiche.sentences:  # a copied sentence had nothing to adapt, and no call was made for it
        assert (w.status == "copied") == write.nothing_to_adapt(w.source)
    writes = sum(v.startswith(f"{write.VERSION}/") for v in fake.sent)
    assert writes == statuses.count("written")


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
                            "proceedings", "reported", "recital", "review", "fragment"}  # fmt: skip


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
    ).replace(
        "2. Die Gerichtskosten werden der Suva auferlegt.",
        "2. Die Sache wird zur Neuverlegung der Kosten zurückgewiesen.",
    )
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
    source = RULING.replace(
        "1. Die Beschwerde wird abgewiesen.", "1. Die Beschwerde wird abgewiesen, soweit darauf einzutreten ist."
    )
    assert write.with_admissibility("Text. Die Beschwerde wird abgewiesen.", "de", source).endswith(
        "Die Beschwerde wird abgewiesen, soweit darauf einzutreten ist."
    )
    assert write.with_admissibility("Text. Die Beschwerde wird abgewiesen.", "de", RULING).endswith("abgewiesen.")


def test_trim_leaves_out_facts_then_application_and_keeps_the_answer_and_what_code_added():
    long = " ".join(["Wort"] * 100) + "."
    sentences = [write.Written(f"S{n}", label, role, "x", long, "written") for n, (label, role) in enumerate(
        [("facts", "fact"), ("E.3", "rule"), ("E.4", "application"), ("E.5", "application"), ("E.5", "holding"),
         ("E.6", "condition")], 1)]  # fmt: skip
    choice = choose.Choice(
        "p", (), 0, {}, {"E.3": 0.9, "E.4": 0.2, "E.5": 0.8, "E.6": 0.5}, ["S6 added for income_comparison:deduction"]
    )
    kept, notes = write.trim(sentences, choice, "de")  # limit 303 words: three sentences of 101 words fit
    assert [w.source_id for w in kept] == ["S2", "S5", "S6"]
    assert [n.split()[0] for n in notes] == ["S1", "S3", "S4"]  # fact, then the lower-read application first


# --- parties ------------------------------------------------------------------------------------------------------

HEAD_DE = """Urteil vom 3. Juni 2025
Verfahrensbeteiligte
HDI Global SE, Hannover, Niederlassung Zürich/Schweiz, Hardstrasse 201, 8005 Zürich,
vertreten durch Rechtsanwalt X.,
Beschwerdeführerin,

gegen

A.________,
vertreten durch Rechtsanwältin Y.,
Beschwerdegegnerin.

Gegenstand
Unfallversicherung
"""
HEAD_FR = """Arrêt du 3 juin 2025
Participants à la procédure
A.________, représenté par Me Z., avocat,
recourant,

contre

Caisse nationale suisse d'assurance en cas d'accidents (CNA), Fluhmattstrasse 1, 6002 Lucerne,
intimée.

Objet
Assurance-accidents
"""


def test_the_parties_are_read_from_the_heading_not_guessed():
    from src.summarize.extract import parties

    de = parties.read(HEAD_DE + RULING)
    assert (de.insurer, de.appellant, de.insured_female) == ("HDI Global SE", "insurer", True)  # not "Suva"
    fr = parties.read(HEAD_FR + RULING)
    assert (fr.insurer, fr.appellant, fr.insured_female) == ("Suva", "insured", False)  # the CNA is the Suva
    line = de.describe("de")
    assert (
        "die Versicherte (eine Frau)" in line and "HDI Global SE" in line and "Beschwerde führt HDI Global SE" in line
    )


def test_the_sentence_before_is_given_and_is_part_of_the_entailment_premise():
    before = "Das Valideneinkommen beträgt Fr. 60'000."
    sentence = cand.Candidate(
        "S5", "E.3", "Dieser Betrag ist der versicherten Person als Valideneinkommen anzurechnen."
    )
    new = "Das Valideneinkommen von Fr. 60'000 ist der Versicherten anzurechnen."
    fake = Fake(**{f"{write.VERSION}/0": [{"a_sentence": new}]})
    written = write.write_sentence(sentence, "rule", "de", {"text": INCOME, "language": "de", "category": "uv"},
                                   model_for(fake), before, "The parties: …")  # fmt: skip
    assert written.status == "written"
    prompt = fake.sent[0][1][-1]["content"]
    assert before in prompt and "The parties: …" in prompt
    premise = next(m for v, m in fake.sent if v.startswith("entail@1/write"))[-1]["content"]
    assert before in premise and sentence.text in premise


def test_a_rule_made_stronger_or_weaker_is_refused_by_code():
    assert write.strength(
        "l'appréciation des juges cantonaux doit être confirmée",
        "l'appréciation des juges cantonaux peut être confirmée",
    )
    assert write.strength("Die Rente kann gekürzt werden.", "La rente doit être réduite.")
    assert not write.strength("Die Rente muss gekürzt werden.", "Die Rente ist zu kürzen.")
    assert not write.strength("Das Gericht bestätigt die Kürzung.", "Le Tribunal confirme la réduction.")


def test_the_admissibility_qualifier_has_its_variants():
    source = RULING.replace(
        "1. Die Beschwerde wird abgewiesen.",
        "1. Die Beschwerde wird abgewiesen, soweit darauf eingetreten werden kann.",
    )
    assert write.with_admissibility("Text. Die Beschwerde wird abgewiesen.", "de", source).endswith(
        "soweit darauf einzutreten ist."
    )


# --- editorial rules ----------------------------------------------------------------------------------------------

LOWER = """Urteil vom 3. Juni 2025

Sachverhalt:
A. Die Versicherte verletzte sich am Knie.

Erwägungen:
1. Die Beschwerde ist zulässig.

2. Die Vorinstanz erwog, die Versicherte habe die Leistungen zu Recht verloren, da kein Kausalzusammenhang mehr bestehe. Sie stellte auf das Gutachten von Dr. B. ab, das sie für überzeugend hielt.
Dem ist zuzustimmen, denn das Gutachten ist schlüssig und beruht auf allseitigen Untersuchungen der Versicherten.

3. Somit hat die Vorinstanz die Leistungseinstellung zu Recht bestätigt, weil der Status quo sine erreicht war.

Demnach erkennt das Bundesgericht:
1. Die Beschwerde wird abgewiesen.
"""


def test_the_lower_courts_reasoning_is_kept_with_its_voice_until_the_court_speaks_again():
    found = cand.candidates(LOWER)
    voices = {c.text[:25]: c.voice for c in found.kept}
    assert voices["Sie stellte auf das Gutac"] == "lower_court"
    assert voices["Dem ist zuzustimmen, denn"] == "court"  # the court's own assessment ends the report
    assert voices["Somit hat die Vorinstanz "] == "court"  # a new consideration in the court's voice
    assert cand.tags("Sie stellte auf das Gutachten ab.", "lower_court") == ["lower court"]


def test_the_writer_is_told_who_speaks_and_the_answer_is_never_the_lower_courts():
    from src.summarize.extract import profiles

    found = cand.candidates(LOWER)
    reported = next(c for c in found.kept if c.voice == "lower_court")
    fake = Fake(
        **{
            f"{write.VERSION}/0": [
                {"a_sentence": "Die Vorinstanz stellte auf das Gutachten ab, das sie für überzeugend hielt."}
            ]
        }
    )
    write.write_sentence(
        reported, "application", "de", {"text": LOWER, "language": "de", "category": "uv"}, model_for(fake)
    )
    assert "reports the lower court's reasoning" in fake.sent[0][1][-1]["content"]
    _, notes = profiles.check(found, [], LOWER, {"E.2": 0.9, "E.3": 0.5})
    assert notes and notes[0].split()[0] == next(c.id for c in found.kept if c.text.startswith("Somit hat"))


def test_a_sentence_that_repeats_an_earlier_one_is_left_out():
    a = write.Written(
        "S1",
        "E.3",
        "rule",
        "x",
        "Damit der Unfallversicherer Leistungen erbringt, muss eine psychische Erkrankung nachgewiesen werden.",
        "written",
    )
    b = write.Written(
        "S2",
        "E.3",
        "rule",
        "x",
        "Damit die Suva Leistungen erbringt, muss eine psychische Erkrankung nachgewiesen werden.",
        "written",
    )
    c = write.Written(
        "S3",
        "E.4",
        "holding",
        "x",
        "Die Sache geht zur psychiatrischen Begutachtung an die Vorinstanz zurück.",
        "written",
    )
    kept, notes = write.without_repeats([a, b, c])
    assert [w.source_id for w in kept] == ["S1", "S3"] and b.status == "repeat"
    assert notes == ["S2 left out: it repeats S1"]


def test_the_question_is_the_courts_own_sentence_and_the_v2_frame_must_be_entailed_by_the_facts():
    asked = write.question(RULING)
    assert len(asked) == 1 and asked[0].text.startswith("Streitig ist, ob die Suva ihre Leistungen")
    draft = ("Der Versicherte stürzte am 7. Mai 2023 von einer Leiter. Er verlor dabei drei Finger. "
             "Das Bundesgericht bestätigt die Einstellung der Leistungen.\n\nDie Beschwerde wird abgewiesen.")  # fmt: skip
    fake = Fake(**{"entail@1/frame": [0.95, 0.1]})
    frame = write.frame_from_draft(draft, "de", {"text": RULING}, model_for(fake))
    assert [w.status for w in frame] == ["written", "dropped"]  # the invented fact is refused
    assert frame[0].text.startswith("Der Versicherte stürzte")  # and the frame stops before the court's holding
    premise = next(m for v, m in fake.sent if v.startswith("entail@1/frame"))[-1]["content"]
    assert "Streitig ist, ob die Suva" in premise


def test_a_procedural_question_brings_the_sentence_that_names_the_substance():
    text = RULING.replace("2. Streitig ist, ob die Suva ihre Leistungen zu Recht per 30. Juni 2023 eingestellt hat.",
                          "2. Streitig ist, ob die Vorinstanz Bundesrecht verletzte, indem sie den Einspracheentscheid bestätigte. "
                          "Dabei geht es um die Frage, ob der Status quo sine am 30. Juni 2023 erreicht war.")  # fmt: skip
    asked = write.question(text)
    assert [q.id for q in asked] == ["Q", "Q2"] and asked[1].text.startswith("Dabei geht es um die Frage")


def test_code_shortens_a_repeated_lead_in_and_a_long_name_after_its_first_mention():
    texts = ["La cour cantonale a retenu que l'Office de l'assurance-invalidité pour le canton de Vaud n'avait commis aucune faute.",
             "La cour cantonale a retenu qu'aucun acte illicite n'était imputable à l'Office de l'assurance-invalidité pour le canton de Vaud.",
             "Le Tribunal fédéral confirme ce point."]  # fmt: skip
    out, notes = write.edit(texts, "fr")
    assert out[0] == texts[0]  # the first mention keeps the full name
    assert out[1] == "Elle a en outre retenu qu'aucun acte illicite n'était imputable à l'office AI."
    assert len(notes) == 2


# --- the pipeline -------------------------------------------------------------------------------------------------


FRENCH = [
    "Le droit aux prestations suppose une relation de cause à effet entre l'événement et l'atteinte",
    "Lorsque cette relation disparaît, l'obligation de l'assureur prend fin",
    "Les rapports médicaux établissent que l'état antérieur était retrouvé",
    "Partant, la juridiction cantonale pouvait confirmer la suppression des prestations",
    "La chute depuis une échelle constitue l'événement assuré",
    "La question litigieuse concerne la fin du versement des prestations",
]


class Echo:
    """A declared fake of the gateway for the whole extractive writer: it ranks every consideration yes, chooses
    the first candidates offered, gives every sentence back as written (a translation: one fixed French sentence),
    and finds nothing to polish."""

    def __init__(self, fail_choice: bool = False) -> None:
        self.sent: list[str] = []
        self.fail_choice = fail_choice
        self.n = 0

    def label(self, messages, prompt_version):
        self.sent.append(prompt_version)
        return 0.97

    def __call__(self, messages, response_format, prompt_version, max_tokens):
        import json
        import re

        self.sent.append(prompt_version)
        content = messages[-1]["content"]
        if prompt_version.startswith(f"{choose.VERSION}/passages"):
            if self.fail_choice:
                raise RuntimeError("gateway down")
            return json.dumps({"a_point": "the point", "b_passages": []})
        if prompt_version.startswith(f"{choose.VERSION}/sentences"):
            ids = re.findall(r"(?m)^(S\d+)\b", content)[:4]
            return json.dumps({"a_chosen": [{"a_id": i, "b_role": "rule"} for i in ids]})
        if prompt_version.startswith("write@"):
            if content.startswith("Translate"):  # a French fiche of a German ruling: distinct French sentences
                terms = re.findall(r"Translate '[^']+' as '([^']+)'", content)
                self.n += 1
                lead = FRENCH[self.n % len(FRENCH)]
                return json.dumps({"a_sentence": f"{lead} ({', '.join(terms)})." if terms else f"{lead}."})
            return json.dumps({"a_sentence": re.findall(r"<sentence>\n(.*?)\n</sentence>", content, re.S)[-1]})
        if prompt_version.startswith("flow@"):
            pairs = re.findall(r"(?m)^(s\d+): (.*)$", content)
            return json.dumps({"a_sentences": [{"a_id": i, "b_text": t} for i, t in pairs]})
        return json.dumps({"items": []})  # refine's terms and language steps: nothing to change


@pytest.mark.db
def test_the_pipeline_writes_extractive_fiches_and_stores_where_each_sentence_comes_from(db_conn):
    from src.summarize import pipeline
    from tests.test_summary_pipeline import FakeModel, _ruling

    rid = _ruling(db_conn, text=RULING)  # long enough for a choice (the shared fixture has 3 sentences)
    echo = Echo()
    result = pipeline.summarise_ruling(db_conn, rid, ask=FakeModel(), model="test", refine_transport=echo,
                                       writer="extract")  # fmt: skip
    params = db_conn.execute("SELECT params FROM model_runs WHERE kind = 'summary'").fetchone()[0]
    stored = dict(db_conn.execute("SELECT language, body FROM summaries WHERE ruling_id = %s", (rid,)).fetchall())
    assert params["writer"] == {"de": "extract", "fr": "extract"}
    for language in ("de", "fr"):
        assert stored[language] == result["languages"][language]["text"] and stored[language].strip()
        steps = params["refine"][language]["steps"]
        assert [s["step"] for s in steps][:3] == ["choose", "write", "flow"]
        written = [f for f in steps[1]["findings"] if f["accepted"]]
        assert written and all(f["evidence"] and f["quote"] for f in written)  # the source of every sentence
    from suva_app import workspace

    checks = workspace.ruling_page(db_conn, rid)["summaries"]["de"]["checks"]
    assert checks[1]["step"] == "write" and checks[1]["findings"][0]["quote"]  # the expert sees the source
    assert sum(v.startswith(f"{choose.VERSION}/passages") for v in echo.sent) == 1  # one reading for DE and FR


@pytest.mark.db
def test_a_ruling_the_extractive_writer_cannot_read_still_gets_the_prompt_written_fiches(db_conn):
    from src.summarize import pipeline
    from tests.test_summary_pipeline import FakeModel, _ruling

    rid = _ruling(db_conn, text=RULING)  # long enough to reach the choice call, which the gateway fails
    echo = Echo(fail_choice=True)
    pipeline.summarise_ruling(db_conn, rid, ask=FakeModel(), model="test", refine_transport=echo,
                              writer="extract")  # fmt: skip
    params = db_conn.execute("SELECT params FROM model_runs WHERE kind = 'summary'").fetchone()[0]
    assert params["writer"] == {"de": "v2", "fr": "v2"}
    assert "choice failed" in params["extract_errors"]["_error"]
    assert db_conn.execute("SELECT count(*) FROM summaries WHERE ruling_id = %s", (rid,)).fetchone()[0] == 2
    assert any(v.startswith(f"{choose.VERSION}/passages") for v in echo.sent)  # the failure came from the gateway


# --- review fixes (28 Nov) -----------------------------------------------------------------------------------------


def test_must_is_matched_as_whole_words_only():
    assert not write.strength("Die Rente ist zulässig und kann gekürzt werden.", "Die Rente kann gekürzt werden.")
    assert write.strength("Die Rente ist zu kürzen.", "Die Rente kann gekürzt werden.")
    assert not write.strength("Das ist zutreffend, die Rente kann gekürzt werden.", "Die Rente kann gekürzt werden.")


def test_a_citation_is_not_a_remand():
    from src.summarize.extract import profiles

    assert not profiles._says(
        profiles.REMAND, "Le droit à la rente suppose un lien de causalité (ATF 129 V 177 et les renvois)."
    )
    assert profiles._says(
        profiles.REMAND,
        "Le recours doit être admis en ce sens que l'arrêt est annulé et la cause renvoyée à l'intimée.",
    )
    assert not profiles._says(
        profiles.REMAND, "L'arrêt entrepris expose correctement les règles; il suffit d'y renvoyer."
    )


def test_a_ruling_without_a_language_in_the_database_is_read_for_it():
    assert write.ruling_language(RULING) == "de"
    assert write.ruling_language(FR_RULING) == "fr"


def test_codes_copy_in_another_language_is_never_kept():
    sentence = cand.Candidate(
        "S1",
        "E.3",
        "Le statu quo sine a été atteint le 30 juin 2023, de sorte que la CNA pouvait mettre fin à ses prestations.",
    )
    fake = Fake(
        **{f"{write.VERSION}/0": [{"a_sentence": sentence.text}], f"{write.VERSION}/1": [{"a_sentence": sentence.text}]}
    )
    written = write.write_sentence(
        sentence, "holding", "de", {"text": FR_RULING, "language": None, "category": "uv"}, model_for(fake)
    )
    assert written.status == "dropped"  # read as a French ruling: a translation, and the French copy is no German fiche


def test_the_lead_in_is_shortened_only_where_gender_and_verb_allow():
    de = ["Das kantonale Gericht hielt fest, dass die Rente zu kürzen sei und die Kürzung dem Gesetz entspreche.",
          "Das kantonale Gericht hielt fest, dass die Versicherte keine Einwände erhoben habe."]  # fmt: skip
    assert write.edit(de, "de")[0] == de  # "Sie hielt fest zudem" would be wrong German
    de2 = ["Die Vorinstanz erwog, dass die Rente zu kürzen sei und die Kürzung dem Gesetz entspreche.",
           "Die Vorinstanz erwog, dass die Versicherte keine Einwände erhoben habe."]  # fmt: skip
    assert write.edit(de2, "de")[0][1].startswith("Sie erwog zudem, dass")


def test_a_quoted_word_copied_from_the_source_language_is_refused_in_a_translation():
    problems = write._problems("Le droit à la rente est examiné de manière globale («allseitig») selon la jurisprudence.",
                               "Der Rentenanspruch ist umfassend („allseitig“) zu prüfen, wie die Rechtsprechung festhält.",
                               "fr", RULING, [], translation=True)  # fmt: skip
    assert any("allseitig" in p for p in problems)


def test_every_failed_ranking_is_a_failure_not_an_order_by_label():
    fake = Fake(**{f"{choose.VERSION}/passages": [{"a_point": "p", "b_passages": []}]})
    fake.label = lambda messages, version: None  # no Ja or Nein among the alternatives: every reading fails
    with pytest.raises(ModelFailed, match="no consideration could be read"):
        choose.choose(RULING, model_for(fake))
