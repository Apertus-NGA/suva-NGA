# ruff: noqa: E501  (test data: whole sentences of invented rulings, kept on one line to stay readable)
"""Tests of the v3 record (src/summarize/v3/record.py). The model is the declared fake transport of
tests/test_refine.py: no gateway call, no database (G9). Every ruling and sentence here is invented."""

from __future__ import annotations

import pytest

from src.summarize.extract import candidates as cand
from src.summarize.extract import parties
from src.summarize.refine.model import Model, ModelFailed
from src.summarize.v3 import record
from src.summarize.v3.types import MAX_PROPOSITIONS
from tests.test_extract import INCOME, LOWER
from tests.test_refine import RULING, Fake

# A party's proposed conclusion in the conditional (S6), then the court's own conclusion (S7).
CONDITIONAL = """Arrêt du 3 juin 2025

Faits :
A. L'assurée s'est blessée à l'épaule le 7 mai 2023. La CNA lui a alloué une indemnité pour atteinte à l'intégrité de 10 %.

Considérant en droit :
1. Le recours est recevable (art. 82 LTF).

2. Le litige porte sur le taux de l'indemnité pour atteinte à l'intégrité.

3. Selon l'art. 24 al. 1 LAA, l'assuré qui souffre d'une atteinte importante et durable à son intégrité a droit à une indemnité équitable.

4. L'appréciation du médecin d'arrondissement repose sur un examen complet de l'épaule blessée. En conclusion, l'indemnité devrait être portée à 15 % au moins. Il s'ensuit que le taux de 10 % retenu par la CNA doit être confirmé.

Par ces motifs, le Tribunal fédéral prononce :
1. Le recours est rejeté.
2. Les frais judiciaires, arrêtés à 800 fr., sont mis à la charge de la recourante.
"""

READ, AGAIN = record.READ_VERSION, record.AGAIN_VERSION


def model_for(fake: Fake, budget: int = 12) -> Model:
    return Model(fake, budget=budget, labeler=fake.label)


def answer(*items: tuple[str, str, str], point: str = "der Punkt") -> dict:
    return {
        "a_point": point,
        "b_propositions": [{"a_id": i, "b_speaker": who, "c_slot": slot} for i, who, slot in items],
    }


def ids(text: str) -> dict[str, str]:
    """The candidate id by the opening words of its sentence."""
    return {c.text[:24]: c.id for c in cand.candidates(text).kept}


def prompt_of(fake: Fake, version: str) -> str:
    return next(messages for v, messages in fake.sent if v == version)[-1]["content"]


def rows(rec) -> list[tuple[str, str, str, str]]:
    return [(p.id, p.slot, p.speaker, p.source_id) for p in rec.propositions]


# --- the record ---------------------------------------------------------------------------------------------------


def test_a_clean_record_has_the_question_from_code_then_facts_rule_condition_and_answer_copied_from_the_ruling():
    s = ids(RULING)
    fact, rule, limit, concl = (
        s["Der Versicherte stürzte "],
        s["Die Leistungspflicht des"],
        s["Fällt dieser dahin, ende"],
        s["Die Vorinstanz hat die L"],
    )
    fake = Fake(**{READ: [answer((concl, "court", "answer"), (limit, "court", "condition"), (rule, "court", "rule"), (fact, "court", "fact"))]})  # fmt: skip
    model = model_for(fake)
    rec = record.read(RULING, model)
    assert rows(rec) == [  # the fiche's order, not the answer's; ids by code
        ("P1", "question", "court", "Q"),
        ("P2", "fact", "court", fact),
        ("P3", "rule", "court", rule),
        ("P4", "condition", "court", limit),
        ("P5", "answer", "court", concl),
    ]
    assert (
        rec.get("P1").source == "Streitig ist, ob die Suva ihre Leistungen zu Recht per 30. Juni 2023 eingestellt hat."
    )
    assert (
        rec.get("P3").source
        == "Die Leistungspflicht des Unfallversicherers setzt einen natürlichen Kausalzusammenhang voraus (Art. 6 Abs. 1 UVG)."
    )
    assert all(" ".join(p.source.split()) in " ".join(RULING.split()) for p in rec.propositions)
    assert [p.label for p in rec.propositions] == ["E.2", "facts", "E.2.1", "E.2.1", "E.3"]
    assert (rec.status, rec.issues, rec.calls, rec.outcome, rec.remand) == ("ok", [], 1, "rejected", False)
    assert rec.calls == model.calls
    assert [p.id for p in rec.required()] == ["P3", "P5"]
    assert rec.parties["insured_female"] is None and set(rec.parties) == {"insured_female", "appellant", "insurer"}
    sent = prompt_of(fake, READ)
    assert f"{rule} [article]:" in sent and "[E.2.1]" in sent and "[facts]" in sent  # candidates with code's tags
    assert "Die Beschwerde ist zulässig" not in sent  # admissibility never reaches the model
    assert record.QUESTION_BY_CODE in sent and '"question"' not in sent  # the question is not the model's to fill
    assert '"lower_court"' in sent and '"expert"' in sent and "reports what a party argues" in sent


def test_the_question_sentence_chosen_again_by_the_model_is_left_out():
    s = ids(RULING)
    asked, rule, concl = s["Streitig ist, ob die Suv"], s["Die Leistungspflicht des"], s["Die Vorinstanz hat die L"]
    fake = Fake(**{READ: [answer((asked, "court", "fact"), (rule, "court", "rule"), (concl, "court", "answer"))]})
    rec = record.read(RULING, model_for(fake))
    assert [p.source_id for p in rec.propositions] == ["Q", rule, concl]
    assert rec.issues == [f"{asked} left out: it is the question, which code states"]


def test_an_id_named_twice_is_used_once_with_its_first_reading():
    s = ids(RULING)
    rule, concl = s["Die Leistungspflicht des"], s["Die Vorinstanz hat die L"]
    fake = Fake(**{READ: [answer((rule, "court", "rule"), (rule, "appellant", "condition"), (concl, "court", "answer"))]})  # fmt: skip
    rec = record.read(RULING, model_for(fake))
    assert rows(rec) == [("P1", "question", "court", "Q"), ("P2", "rule", "court", rule), ("P3", "answer", "court", concl)]  # fmt: skip
    assert rec.issues == [f"{rule} named twice: used once"] and rec.status == "ok"


def test_a_lower_court_sentence_given_as_the_courts_is_corrected_and_noted():
    s = ids(LOWER)
    lower, agreed, concl = s["Sie stellte auf das Guta"], s["Dem ist zuzustimmen, den"], s["Somit hat die Vorinstanz"]
    assert cand.candidates(LOWER).get(lower).voice == "lower_court"
    fake = Fake(**{
        READ: [answer((lower, "court", "rule"), (agreed, "court", "condition"), (concl, "court", "answer"))],
        AGAIN: [answer()],  # no court rule after the correction: asked again, nothing better comes
    })  # fmt: skip
    rec = record.read(LOWER, model_for(fake))
    assert rows(rec) == [
        ("P1", "rule", "lower_court", lower),  # the slot stays, the speaker is the lower court
        ("P2", "condition", "court", agreed),
        ("P3", "answer", "court", concl),
    ]
    assert f"{lower}: speaker court -> lower_court (the court reports the lower court's reasoning)" in rec.issues
    assert [p.source_id for p in rec.required()] == [concl]  # the lower court's rule is not what the court holds
    assert rec.status == "needs_review" and rec.issues[-1] == "no court rule could be checked"
    assert f"{lower} [lower court]:" in prompt_of(fake, READ)
    assert '"question"' in prompt_of(fake, READ) and record.QUESTION_BY_MODEL in prompt_of(
        fake, READ
    )  # no "Streitig ist"


def test_a_conditional_sentence_given_as_the_courts_answer_is_refused_and_code_finds_the_real_conclusion():
    s = ids(CONDITIONAL)
    rule, proposed, real = s["Selon l'art. 24 al. 1 LA"], s["En conclusion, l'indemni"], s["Il s'ensuit que le taux "]
    fake = Fake(**{
        READ: [answer((rule, "court", "rule"), (proposed, "court", "answer"))],
        AGAIN: [answer((proposed, "court", "answer"))],  # the model insists
    })  # fmt: skip
    rec = record.read(CONDITIONAL, model_for(fake))
    assert rows(rec) == [("P1", "question", "court", "Q"), ("P2", "rule", "court", rule), ("P3", "answer", "court", real)]  # fmt: skip
    assert rec.get("P3").source == "Il s'ensuit que le taux de 10 % retenu par la CNA doit être confirmé."
    assert proposed not in [p.source_id for p in rec.propositions]
    assert rec.issues == [
        f"{proposed} refused as the court's answer: reported speech or conditional",
        f"{real} added by code as the court's answer",
    ]
    assert (rec.status, rec.calls) == ("ok", 2)


def test_the_same_conditional_sentence_stays_when_the_model_gives_it_to_a_party():
    s = ids(CONDITIONAL)
    rule, proposed, real = s["Selon l'art. 24 al. 1 LA"], s["En conclusion, l'indemni"], s["Il s'ensuit que le taux "]
    fake = Fake(**{READ: [answer((rule, "court", "rule"), (proposed, "appellant", "answer"), (real, "court", "answer"))]})  # fmt: skip
    rec = record.read(CONDITIONAL, model_for(fake))
    assert rows(rec)[2:] == [("P3", "answer", "appellant", proposed), ("P4", "answer", "court", real)]
    assert (rec.status, rec.issues, rec.calls) == ("ok", [], 1)
    assert [p.source_id for p in rec.required()] == [rule, real]


def test_one_retry_names_what_is_missing_and_what_was_refused():
    s = ids(RULING)
    rule, limit, concl = s["Die Leistungspflicht des"], s["Fällt dieser dahin, ende"], s["Die Vorinstanz hat die L"]
    fake = Fake(**{
        READ: [answer((limit, "court", "rule"), (rule, "court", "rule"))],  # no answer
        AGAIN: [answer((concl, "court", "answer"))],
    })  # fmt: skip
    model = model_for(fake)
    rec = record.read(RULING, model)
    assert rows(rec) == [
        ("P1", "question", "court", "Q"),
        ("P2", "rule", "court", rule),
        ("P3", "condition", "court", limit),  # a rule without article, case law or formula is a condition
        ("P4", "answer", "court", concl),
    ]
    assert rec.issues == [f"{limit}: slot rule -> condition (no article, case law or rule formula)"]
    assert (rec.status, rec.calls, model.calls) == ("ok", 2, 2)
    assert [v for v, _ in fake.sent] == [READ, AGAIN]
    again = prompt_of(fake, AGAIN)
    assert record.MISSING["answer"] in again and record.MISSING["rule"] not in again
    assert f"- {limit}: slot rule -> condition" in again  # code's notes go back to the model
    assert 'one of ["answer"]' in again  # only the missing slot can be answered


def test_the_retry_can_move_a_sentence_already_kept_as_the_courts_into_the_missing_slot():
    s = ids(RULING)
    rule, concl = s["Die Leistungspflicht des"], s["Die Vorinstanz hat die L"]
    fake = Fake(**{
        READ: [answer((rule, "court", "rule"), (concl, "court", "condition"))],
        AGAIN: [answer((concl, "court", "answer"))],
    })  # fmt: skip
    rec = record.read(RULING, model_for(fake))
    assert rows(rec)[1:] == [("P2", "rule", "court", rule), ("P3", "answer", "court", concl)]
    assert rec.issues == [f"{concl}: slot condition -> answer (second reading)"] and rec.status == "ok"


def test_no_second_call_when_the_first_reading_checks_and_never_a_third():
    s = ids(RULING)
    fake = Fake(**{READ: [answer()], AGAIN: [answer(), answer()]})
    rec = record.read(RULING, model_for(fake))
    assert [v for v, _ in fake.sent] == [READ, AGAIN]  # one retry at most
    assert rows(rec) == [("P1", "question", "court", "Q")]  # no sentence of the ruling opens as a conclusion
    assert rec.status == "needs_review" and rec.issues == ["no court rule and no court answer could be checked"]
    assert rec.calls == 2 and rec.required() == [] and s


def test_a_failed_call_propagates_and_a_ruling_without_sentences_needs_no_call():
    with pytest.raises(ModelFailed):
        record.read(RULING, model_for(Fake(), budget=0))
    fake = Fake()
    rec = record.read("Urteil.\n\nErwägungen:\n1. Kurz.\n", model_for(fake))
    assert (rec.status, rec.propositions, rec.calls, fake.sent) == ("needs_review", (), 0, [])
    assert rec.issues == ["no candidate sentences: nothing to build a record from"]


def test_a_remand_and_the_profile_are_read_by_code_and_told_to_the_model():
    s = ids(INCOME)
    rule, level = s["Das Invalideneinkommen i"], s["Massgebend ist das Kompe"]
    fake = Fake(**{READ: [answer((rule, "court", "condition"), (level, "court", "answer"))], AGAIN: [answer()]})
    rec = record.read(INCOME, model_for(fake))
    assert (rec.remand, rec.profile, rec.outcome) == (True, "income_comparison", "partial")
    sent = prompt_of(fake, READ)
    assert "The court sends the case back" in sent and "skill level" in sent
    assert "the court sends the case back, and no sentence of its own says what goes back" in rec.issues
    assert rec.status == "needs_review"  # no rule with a legal anchor in this ruling's candidates


def test_code_adds_the_courts_own_sentence_on_what_goes_back():
    remand = INCOME.replace(
        "berücksichtigt sind.",
        "berücksichtigt sind. Die Sache ist daher an die Suva zurückzuweisen, damit sie den Abzug neu prüfe. "
        "Die Sache wird zur Abklärung des Valideneinkommens an die Suva zurückgewiesen.",
    ).replace("Das Invalideneinkommen ist gestützt", "Gemäss Art. 16 ATSG ist das Invalideneinkommen gestützt")
    s = ids(remand)
    rule, level, back = s["Gemäss Art. 16 ATSG ist "], s["Massgebend ist das Kompe"], s["Die Sache wird zur Abklä"]
    fake = Fake(**{READ: [answer((rule, "court", "rule"), (level, "court", "answer"))]})
    rec = record.read(remand, model_for(fake))
    # the last sentence that says it and is not in reported speech ("prüfe" follows "zurückzuweisen": not matched;
    # the earlier one does not say "zurückgewiesen")
    assert rows(rec)[-2:] == [("P2", "answer", "court", level), ("P3", "answer", "court", back)]
    assert rec.issues == [f"{back} added by code: the court sends the case back"] and rec.status == "ok"


def test_the_cap_drops_facts_then_other_speakers_then_conditions_and_never_the_courts_answer():
    c = cand.Candidate("S1", "E.2", "Ein Satz mit genug Wörtern für einen Kandidaten.")
    given = [("Q", "question", "court", c), ("Q2", "question", "court", c), ("S1", "fact", "court", c),
             ("S2", "fact", "court", c), ("S3", "rule", "court", c), ("S4", "rule", "lower_court", c),
             ("S5", "condition", "court", c), ("S6", "condition", "court", c), ("S7", "answer", "appellant", c),
             ("S8", "answer", "court", c), ("S9", "answer", "court", c)]  # fmt: skip
    issues: list[str] = []
    kept = record._capped(given, issues)
    assert len(kept) == MAX_PROPOSITIONS
    assert [r[0] for r in kept] == ["Q", "Q2", "S3", "S4", "S5", "S6", "S8", "S9"]  # facts first, then a party's
    assert [i.split()[0] for i in issues] == ["S2", "S1", "S7"]
    many = [(f"S{n}", "rule", "court", c) for n in range(1, 9)] + [("S9", "answer", "court", c), ("S10", "answer", "court", c)]  # fmt: skip
    kept = record._capped(many, [])
    assert [r[0] for r in kept] == ["S1", "S2", "S3", "S4", "S5", "S6", "S9", "S10"]  # the last rules, not the answers


# --- who speaks: the detectors, on invented sentences -------------------------------------------------------------


@pytest.mark.parametrize(
    "sentence",
    [
        "Die Rente sei zu Unrecht herabgesetzt worden.",
        "Der Gutachter habe die Schulter nicht untersucht.",
        "Die Rente wäre demnach auf 20 % zu erhöhen.",
        "Die Suva hätte weitere Abklärungen treffen müssen.",
        "Die Vorinstanz solle ein neues Gutachten einholen.",
        "Ein Kausalzusammenhang müsse bejaht werden.",
        "Es bestehe kein Anspruch auf eine Rente.",
        "Le taux devrait être porté à 15 %.",
        "Le rapport serait incomplet sur ce point.",
        "L'expert aurait ignoré les douleurs de l'épaule.",
        "Il faudrait ordonner une nouvelle expertise.",
        "Une rente pourrait dès lors être allouée.",
        "La rendita dovrebbe essere aumentata al 20 %.",
        "Il rapporto sarebbe incompleto su questo punto.",
    ],
)
def test_reported_speech_and_the_conditional_are_detected(sentence):
    assert record.reported(sentence)


@pytest.mark.parametrize(
    "sentence",
    [
        "Die Rente ist seit dem 1. Mai 2023 geschuldet.",  # "seit" is not "sei"
        "Auf Seite 4 des Berichts steht die Diagnose.",
        "Die Leistungspflicht entfällt, es sei denn, der Versicherer hat den Schaden anerkannt.",  # "unless"
        "Der Anspruch besteht, sei es als Rente, sei es als Abfindung.",
        "Die Würde des Menschen ist zu achten.",  # the noun, not the conditional
        "Seine Habe wurde beim Unfall zerstört.",
        "Die Beschwerdeführerin haben die Ärzte am 3. Mai 2023 untersucht.",
        "Die Rente sollte am 1. Mai 2023 beginnen.",  # past tense or the court's own caution: not taken
        "Das Gutachten dürfte den Anforderungen genügen.",
        "On ne saurait suivre cette argumentation.",  # the court's own, not "aurait"
        "Le droit à la rente prend naissance le 1er mai 2023.",
        "L'assuré a droit à une indemnité équitable.",
        "Le médecin a constaté une lésion de l'épaule.",
        "La rendita è dovuta dal 1° maggio 2023.",
    ],
)
def test_the_detector_leaves_the_indicative_alone(sentence):
    assert not record.reported(sentence)


def test_a_sentence_that_reads_as_an_argument_is_given_to_the_one_who_argues():
    insured_appeals = parties.Parties(True, "insured", "Suva")
    unknown = parties.Parties(None, None, None)
    cases = {
        "Die Beschwerdeführerin rügt eine Verletzung des Untersuchungsgrundsatzes.": "appellant",
        "Nach Ansicht der Beschwerdegegnerin ist der Fall abgeschlossen.": "respondent",
        "Selon la recourante, le rapport du médecin est incomplet.": "appellant",
        "De l'avis de l'intimée, le traitement est terminé.": "respondent",
        "Selon les premiers juges, le lien de causalité est rompu.": "lower_court",
        "Se plaignant d'une instruction lacunaire, l'assurée demande une expertise.": "appellant",
        "Die Suva macht geltend, der Status quo sine ist erreicht.": "respondent",
    }
    for sentence, speaker in cases.items():
        assert record.party_argument(sentence), sentence
        assert record.arguer(sentence, insured_appeals) == speaker, sentence
    assert record.arguer("Die Suva macht geltend, der Status quo sine ist erreicht.", unknown) is None  # who appealed?
    for own in (
        "Selon l'art. 6 al. 1 LAA, les prestations sont allouées en cas d'accident.",
        "Nach der Rechtsprechung genügt ein blosser Verdacht nicht.",
        "Gemäss den Berichten war der Status quo sine erreicht.",
        "La recourante a repris le travail le 3 mai 2023.",
    ):
        assert not record.party_argument(own), own


def test_check_corrects_or_refuses_what_the_model_calls_the_courts():
    who = parties.Parties(True, "insured", "Suva")
    argued = cand.Candidate("S1", "E.3", "Selon la recourante, le rapport du médecin est incomplet et contradictoire.")
    assert record.check(argued, "answer", "court", who)[:2] == ("answer", "appellant")
    assert record.check(argued, "answer", "expert", who) == ("answer", "expert", [])  # only "court" is checked
    wished = cand.Candidate("S2", "E.3", "Die Rente wäre demnach auf 20 % zu erhöhen.")
    for slot in ("rule", "condition", "answer", "question"):
        assert record.check(wished, slot, "court", who)[0] == ""
    assert record.check(wished, "fact", "court", who)[0] == "fact"
    in_facts = cand.Candidate("S3", "facts", "Somit hat die Suva ihre Leistungen am 30. Juni 2023 eingestellt.")
    assert record.check(in_facts, "answer", "court", who)[0] == ""  # the court concludes in its considerations
    bare = cand.Candidate("S4", "E.3", "Ein blosser Verdacht genügt dafür nicht.")
    anchored = cand.Candidate("S5", "E.3", "Nach der Rechtsprechung genügt ein blosser Verdacht nicht (BGE 129 V 177).")
    assert record.check(bare, "rule", "court", who)[0] == "condition"
    assert record.check(anchored, "rule", "court", who) == ("rule", "court", [])
