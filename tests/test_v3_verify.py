# ruff: noqa: E501  (test data: whole sentences, kept on one line to stay readable)
"""Tests of the v3 verifier (src/summarize/v3/verify.py): content and speaker of every sentence, decided by code.

The model is the declared fake transport of tests/test_refine.py: no gateway call, no database (G9). Records and
sentences are built by hand; the ruling is the invented one of tests/test_refine.py with one consideration added.
"""

from __future__ import annotations

from src.summarize.extract.write import required_terms
from src.summarize.refine import checks
from src.summarize.refine.model import Model
from src.summarize.refine.steps.terms import pairs
from src.summarize.v3 import verify as v
from src.summarize.v3.types import Proposition, Record, Sentence
from tests.test_refine import RULING, Fake

LOWER = "Die Vorinstanz erwog, der Status quo sine sei am 30. Juni 2023 erreicht gewesen."
CLAIM = "Der Beschwerdeführer macht geltend, seine Beschwerden seien weiterhin unfallbedingt."
TEXT = RULING.replace("\n3. Gemäss den Berichten", f"\n2.2 {LOWER} {CLAIM}\n\n3. Gemäss den Berichten")
FACT = "Der Versicherte stürzte am 7. Mai 2023 von einer Leiter."
RULE = (
    "Die Leistungspflicht des Unfallversicherers setzt einen natürlichen Kausalzusammenhang voraus (Art. 6 Abs. 1 UVG)."
)
ANSWER = "Die Vorinstanz hat die Leistungseinstellung daher zu Recht bestätigt."
PARTIES = {"insured_female": False, "appellant": "insured", "insurer": "Suva"}
REPAIR, MISSING, ENTAIL = "v3-verify@1__repair", "v3-verify@1__missing", "entail@1__v3"

S_FACT = "Der Versicherte stürzte von einer Leiter."
S_LOWER = "Die Vorinstanz erwog, der Status quo sine sei am 30. Juni 2023 erreicht gewesen."
S_RULE = (
    "Die Leistungspflicht des Unfallversicherers setzt einen natürlichen Kausalzusammenhang voraus (Art. 6 Abs. 1 UVG)."
)
S_ANSWER = "Das Bundesgericht hält fest, dass die Vorinstanz die Leistungseinstellung zu Recht bestätigt hat."
S_AS_COURT = "Das Bundesgericht hält fest, dass der Status quo sine am 30. Juni 2023 erreicht war."


def record(*extra: Proposition, status: str = "ok") -> Record:
    propositions = (
        Proposition("P1", "fact", "court", "facts", "S1", FACT),
        Proposition("P2", "fact", "lower_court", "E.2.2", "S2", LOWER),
        Proposition("P3", "rule", "court", "E.2.1", "S3", RULE),
        Proposition("P4", "answer", "court", "E.3", "S4", ANSWER),
        *extra,
    )
    return Record(propositions, "rejected", False, dict(PARTIES), None, status=status)


def ruling(text: str = TEXT) -> dict:
    return {"text": text, "language": "de", "category": "uv", "docket": "8C_1/2025", "starred": None}


def clean() -> list[Sentence]:
    return [
        Sentence(S_FACT, ("P1",)),
        Sentence(S_LOWER, ("P2",)),
        Sentence(S_RULE, ("P3",)),
        Sentence(S_ANSWER, ("P4",)),
    ]


def run(draft: list[Sentence], fake: Fake, rec: Record | None = None, language: str = "de", budget: int = 40):
    return v.verify(draft, rec or record(), language, ruling(), Model(fake, budget=budget, labeler=fake.label))


def prompt(fake: Fake, n: int) -> str:
    return fake.sent[n][1][-1]["content"]


# --- the fiche as a whole -----------------------------------------------------------------------------------------


def test_a_clean_draft_passes_and_ends_with_the_outcome_sentence_code_adds():
    fake = Fake()
    fiche = run(clean(), fake)
    assert fiche.status == "ok" and fiche.missing == []
    assert [s.status for s in fiche.sentences] == ["written"] * 4
    assert all(s.entailment == 0.97 and not s.problems for s in fiche.sentences)
    assert fiche.text.startswith(S_FACT) and fiche.text.endswith("Die Beschwerde wird abgewiesen.")
    assert fiche.text.count("Beschwerde wird abgewiesen") == 1
    assert fiche.calls == 4 and [name for name, _ in fake.sent] == ["entail@1/v3"] * 4  # one reading per sentence


def test_the_premise_of_the_reading_names_the_speaker_so_a_right_attribution_is_supported():
    fake = Fake()
    run(clean(), fake)
    lower, answer = prompt(fake, 1), prompt(fake, 3)
    assert f"{v.SPEAKER_LINE['lower_court']}\n{LOWER}" in lower and "Auffassung der Vorinstanz" in lower
    assert f"{v.SPEAKER_LINE['court']}\n{ANSWER}" in answer and "Auffassung der Vorinstanz" not in answer
    party = v.premise_of([Proposition("P9", "fact", "appellant", "E.2.2", "S9", CLAIM)], PARTIES)
    assert "beschwerdeführenden Partei (der versicherten Person)" in party and party.endswith(CLAIM)


def test_a_record_that_needs_review_makes_the_fiche_need_review():
    assert run(clean(), Fake(), record(status="needs_review")).status == "needs_review"


# --- the speaker check --------------------------------------------------------------------------------------------


def test_a_lower_court_proposition_given_as_the_courts_holding_is_refused_by_code_and_repaired_once():
    fake = Fake(**{REPAIR: [{"a_sentence": S_LOWER}]})
    draft = [
        Sentence(S_FACT, ("P1",)),
        Sentence(S_AS_COURT, ("P2",)),
        Sentence(S_RULE, ("P3",)),
        Sentence(S_ANSWER, ("P4",)),
    ]
    fiche = run(draft, fake)
    names = [name for name, _ in fake.sent]
    # code refused it: no reading was spent on the wrong sentence, the repair comes right after the first sentence
    assert names == ["entail@1/v3", "v3-verify@1/repair", "entail@1/v3", "entail@1/v3", "entail@1/v3"]
    asked = prompt(fake, 1)
    assert "presents as the Federal Supreme Court's own statement what the lower court says" in asked
    assert "P2 (fact), said in the ruling by the lower court" in asked and LOWER in asked and S_AS_COURT in asked
    assert "this is NOT the Federal Supreme Court's statement; the lower court says it" in asked
    assert '"a_sentence"' in asked
    repaired = fiche.sentences[1]
    assert repaired.status == "repaired" and repaired.text == S_LOWER and repaired.entailment == 0.97
    assert repaired.problems and all(p.startswith("attempt 1: speaker:") for p in repaired.problems)
    assert fiche.status == "needs_review" and S_AS_COURT not in fiche.text and S_LOWER in fiche.text
    assert fiche.calls == 5


def test_when_the_repair_fails_too_the_sentence_is_removed_with_the_problems_of_both_attempts():
    still_wrong = "Der Status quo sine war am 30. Juni 2023 erreicht."  # no court, but no attribution either
    fake = Fake(**{REPAIR: [{"a_sentence": still_wrong}]})
    draft = [
        Sentence(S_FACT, ("P1",)),
        Sentence(S_AS_COURT, ("P2",)),
        Sentence(S_RULE, ("P3",)),
        Sentence(S_ANSWER, ("P4",)),
    ]
    fiche = run(draft, fake)
    removed = fiche.sentences[1]
    assert removed.status == "removed"
    assert any(p.startswith("attempt 1: speaker:") for p in removed.problems)
    assert any(p.startswith("attempt 2: speaker: P2 is said by the lower court") for p in removed.problems)
    assert fiche.status == "needs_review" and "Status quo sine" not in fiche.text
    assert [name for name, _ in fake.sent].count("entail@1/v3") == 3  # the two refused texts were never read
    assert any(note.startswith("P2 removed") for note in fiche.notes)


def test_a_non_court_proposition_needs_an_attribution_to_the_right_kind_of_speaker():
    lower = [Proposition("P2", "fact", "lower_court", "E.2.2", "S2", LOWER)]
    claim = [Proposition("P5", "fact", "appellant", "E.2.2", "S5", CLAIM)]
    expert = [Proposition("P6", "fact", "expert", "E.3", "S6", "x")]
    bare = v.speaker_problems("Der Status quo sine war am 30. Juni 2023 erreicht.", lower, PARTIES)
    assert len(bare) == 1 and "must attribute" in bare[0] and "the lower court" in bare[0]
    for ok in (
        S_LOWER,
        "Nach Auffassung der Vorinstanz war der Status quo sine erreicht.",
        "Dazu erwog das kantonale Gericht, der Status quo sine sei erreicht.",
        "La cour cantonale a retenu que le statu quo sine était atteint.",
        "Selon les premiers juges, le statu quo sine était atteint.",
        "Die Vorinstanz bestätigte den Einspracheentscheid.",  # whose act is reported is clear
    ):
        assert v.speaker_problems(ok, lower, PARTIES) == [], ok
    for wrong in (S_AS_COURT, "Le Tribunal fédéral retient que le statu quo sine était atteint."):
        assert any(
            "as the Federal Supreme Court's own statement" in p for p in v.speaker_problems(wrong, lower, PARTIES)
        )
    # a party: by its role in the proceedings or, as the record knows who appeals, by its side
    for ok in (
        "Der Beschwerdeführer macht geltend, die Beschwerden seien unfallbedingt.",
        "Der Versicherte rügt, die Beschwerden seien unfallbedingt.",
        "Vor Bundesgericht macht der Beschwerdeführer geltend, die Beschwerden seien unfallbedingt.",
        "L'assuré soutient que les troubles sont d'origine accidentelle.",
        "Le recourant fait valoir que les troubles sont d'origine accidentelle.",
    ):
        assert v.speaker_problems(ok, claim, PARTIES) == [], ok
    # the insured's argument given to the insurer or to an expert, and the expert's finding given to the insured
    assert (
        "attributes it to the insurer"
        in v.speaker_problems("Die Suva macht geltend, die Beschwerden seien unfallbedingt.", claim, PARTIES)[0]
    )
    assert v.speaker_problems("Der Gutachter hält fest, die Beschwerden seien unfallbedingt.", claim, PARTIES)
    assert v.speaker_problems("Der Versicherte macht geltend, die Beschwerden seien degenerativ.", expert, PARTIES)
    assert v.speaker_problems("Laut dem Kreisarzt sind die Beschwerden degenerativ.", expert, PARTIES) == []
    # who appeals is unknown: any attribution to somebody other than the court is accepted, none is still refused
    unknown = {"appellant": None, "insurer": None}
    assert v.speaker_problems("Die Suva macht geltend, die Beschwerden seien unfallbedingt.", claim, unknown) == []
    assert v.speaker_problems("Die Beschwerden sind unfallbedingt.", claim, unknown)
    # the insurer's name of the record counts as the insurer
    named = {"appellant": "insurer", "insurer": "Helvetia"}
    assert v.speaker_problems("Die Helvetia macht geltend, die Beschwerden seien degenerativ.", claim, named) == []


def test_the_courts_own_holding_is_not_given_to_the_lower_court_but_may_mention_it():
    answer = [Proposition("P4", "answer", "court", "E.3", "S4", ANSWER)]
    for wrong in (
        "Die Vorinstanz erwog, dass die Leistungseinstellung rechtens sei.",
        "La cour cantonale a considéré que la suppression des prestations était justifiée.",
        "Der Beschwerdeführer macht geltend, die Leistungseinstellung sei rechtens.",
    ):
        problems = v.speaker_problems(wrong, answer, PARTIES)
        assert len(problems) == 1 and "as its author" in problems[0], wrong
    for ok in (
        "Die Leistungseinstellung hat die Vorinstanz zu Recht bestätigt.",  # the lower court as the one appraised
        S_ANSWER,
        "Die Vorinstanz hat zu Recht erwogen, dass die Leistungseinstellung rechtens ist.",
        "Die Suva hat ihre Leistungen eingestellt, da der Status quo sine erreicht war.",  # an act, not an author
        "C'est à juste titre que la cour cantonale a confirmé la suppression des prestations.",
        S_RULE,
    ):
        assert v.speaker_problems(ok, answer, PARTIES) == [], ok
    # in the fiche: refused by code, and with no repair on offer the sentence is removed
    fake = Fake()
    draft = [*clean()[:3], Sentence("Die Vorinstanz erwog, dass die Leistungseinstellung rechtens sei.", ("P4",))]
    fiche = run(draft, fake)
    assert fiche.sentences[3].status == "removed" and "as its author" in fiche.sentences[3].problems[0]
    kept = run(
        [*clean()[:3], Sentence("Die Leistungseinstellung hat die Vorinstanz zu Recht bestätigt.", ("P4",))], Fake()
    )
    assert kept.status == "ok" and kept.sentences[3].status == "written"


# --- content: code first, the reading last ------------------------------------------------------------------------


def test_a_low_entailment_reading_refuses_the_sentence():
    fake = Fake(**{ENTAIL: [0.97, 0.2], REPAIR: [{"a_sentence": S_LOWER}]})
    fiche = run(clean(), fake)
    second = fiche.sentences[1]
    assert second.status == "repaired" and second.problems == [
        "attempt 1: entailment 0.20 below 0.9: the source does not say this"
    ]
    assert "entailment 0.20 below 0.9" in prompt(fake, 2) and fake.sent[2][0] == "v3-verify@1/repair"
    again = run(clean(), Fake(**{ENTAIL: [0.97, 0.2, 0.3], REPAIR: [{"a_sentence": S_LOWER}]}))
    assert again.sentences[1].status == "removed" and again.sentences[1].entailment == 0.3
    assert any(p.startswith("attempt 2: entailment 0.30") for p in again.sentences[1].problems)
    assert again.status == "needs_review"


def test_an_article_the_ruling_lacks_is_refused_by_code_without_an_entailment_reading():
    invented = "Die Leistungspflicht des Unfallversicherers setzt einen natürlichen Kausalzusammenhang voraus (Art. 18 Abs. 1 UVG)."
    fake = Fake(**{REPAIR: [{"a_sentence": invented}]})
    fiche = run([Sentence(invented, ("P3",)), Sentence(S_ANSWER, ("P4",))], fake)
    # the one reading is P4's; the last call is for the now missing P3 (no answer on offer: it stays missing)
    assert [name for name, _ in fake.sent] == ["v3-verify@1/repair", "entail@1/v3", "v3-verify@1/missing"]
    assert "article 18 UVG not in the ruling" in prompt(fake, 0)
    first = fiche.sentences[0]
    assert first.status == "removed" and first.entailment is None
    assert "attempt 1: article 18 UVG not in the ruling" in first.problems
    assert "attempt 2: article 18 UVG not in the ruling" in first.problems
    assert fiche.calls == 3  # repair, P4's reading, and the call for the now missing P3 (refused: no answer on offer)
    assert fiche.missing == ["P3"]


def test_code_refuses_placeholders_the_outcome_a_changed_strength_another_language_and_unknown_ids():
    case = v._Case(record(), "de", ruling(), Model(Fake(), budget=5), "de")
    assert "anonymisation placeholder left" in v.code_problems("A.________ stürzte von einer Leiter.", ("P1",), case)
    assert any(
        "placeholder in brackets" in p
        for p in v.code_problems("Der Versicherte stürzte am [Datum] von einer Leiter.", ("P1",), case)
    )
    assert any(
        "outcome of the appeal" in p
        for p in v.code_problems("Das Bundesgericht weist die Beschwerde ab.", ("P2",), case)
    )
    # the court's answer may say what is confirmed or sent back (finish adds the outcome only once)
    assert not any(
        "outcome of the appeal" in p
        for p in v.code_problems("Das Bundesgericht weist die Beschwerde ab.", ("P4",), case)
    )
    assert v.normalised("P1 und P2: Der Versicherte stürzte. (P3)", "de", "") == "Der Versicherte stürzte."
    assert any(
        "written in French" in p
        for p in v.code_problems("La personne assurée est tombée d'une échelle et elle est blessée.", ("P1",), case)
    )
    assert "number 2019 not in the ruling" in v.code_problems(
        "Der Versicherte stürzte 2019 von einer Leiter.", ("P1",), case
    )
    may = Proposition("P7", "rule", "court", "E.2.1", "S7", "Der Versicherer kann die Leistungen einstellen.")
    strict = v._Case(record(may), "de", ruling(), Model(Fake(), budget=5), "de")
    assert any(
        "stronger than the ruling" in p
        for p in v.code_problems("Der Versicherer muss die Leistungen einstellen.", ("P7",), strict)
    )
    assert v.code_problems("Der Versicherer kann die Leistungen einstellen.", ("P7",), strict) == []
    # an id the record lacks: nothing to check against and nothing to repair from, so no call at all
    fake = Fake()
    fiche = run([*clean(), Sentence("Der Unfall ereignete sich bei der Arbeit.", ("P9",))], fake)
    assert (
        fiche.sentences[4].status == "removed"
        and "proposition P9 is not in the record" in fiche.sentences[4].problems[0]
    )
    assert fiche.calls == 4 and fiche.status == "needs_review"


def test_references_in_parentheses_are_taken_out_by_code_and_articles_stay():
    draft = clean()
    draft[2] = Sentence(S_RULE.replace("(Art. 6 Abs. 1 UVG)", "(Art. 6 Abs. 1 UVG; BGE 129 V 177 E. 3.1)"), ("P3",))
    fiche = run(draft, Fake())
    assert fiche.status == "ok" and fiche.sentences[2].text == S_RULE and "BGE" not in fiche.text


def test_a_failed_call_fails_its_sentence_only_never_the_fiche():
    fake = Fake()
    fiche = run(clean(), fake, budget=2)  # two readings, then the budget is spent
    assert [s.status for s in fiche.sentences][:2] == ["written", "written"]
    rest = [s for s in fiche.sentences if s.status == "removed"]
    assert len(rest) >= 2 and all("call budget exhausted" in " ".join(s.problems) for s in rest)
    assert fiche.calls == 2 and fiche.missing == ["P3", "P4"]
    assert fiche.status == "failed"  # two sentences kept, but no holding of the court among them


# --- the fiche: repeats, coverage, length, status -----------------------------------------------------------------


def test_a_missing_required_proposition_is_written_by_one_call_checked_and_put_in_at_its_place():
    fake = Fake(**{MISSING: [{"a_sentence": S_RULE}]})
    draft = [Sentence(S_FACT, ("P1",)), Sentence(S_LOWER, ("P2",)), Sentence(S_ANSWER, ("P4",))]
    fiche = run(draft, fake)
    assert [s.propositions for s in fiche.sentences] == [("P1",), ("P2",), ("P3",), ("P4",)]
    assert fiche.sentences[2].text == S_RULE and fiche.sentences[2].status == "written"
    assert fiche.missing == [] and fiche.text.index(S_LOWER) < fiche.text.index(S_RULE) < fiche.text.index(S_ANSWER)
    name, messages = fake.sent[3]
    assert name == "v3-verify@1/missing" and fake.sent[4][0] == "entail@1/v3"  # the new sentence is read like any
    asked = messages[-1]["content"]
    assert "Write the sentence that states this" in asked and RULE in asked
    assert "P3 (rule), said in the ruling by the Federal Supreme Court" in asked
    assert "P3 (required) was not stated: sentence added" in fiche.notes
    # a refused answer leaves the proposition missing, and the fiche goes to a person
    refused = run(
        draft,
        Fake(
            **{
                MISSING: [
                    {"a_sentence": "Die Vorinstanz erwog, die Leistungspflicht setze einen Kausalzusammenhang voraus."}
                ]
            }
        ),
    )
    assert refused.missing == ["P3"] and refused.status == "needs_review"
    assert [s.status for s in refused.sentences] == ["written", "written", "removed", "written"]


def test_a_sentence_that_repeats_an_earlier_one_is_removed():
    draft = clean()
    draft.insert(2, Sentence("Der Versicherte stürzte am 7. Mai 2023 von einer Leiter.", ("P1",)))
    fiche = run(draft, Fake())
    assert [s.status for s in fiche.sentences] == ["written", "written", "removed", "written", "written"]
    assert "repeats an earlier sentence" in fiche.sentences[2].problems[0]
    assert fiche.text.count("stürzte") == 1 and fiche.status == "needs_review"
    assert any("repeats" in note for note in fiche.notes)
    # a different sentence about the same proposition is not a repeat
    other = clean()
    other.insert(1, Sentence("Der Sturz ereignete sich am 7. Mai 2023.", ("P1",)))
    assert run(other, Fake()).status == "ok"


def _filler(k: int, words: int) -> str:
    letters = "abcdefghijklmnopqrstuvwxyz"
    return (
        "Der Versicherte hatte "
        + " ".join(f"faktum{letters[k]}{letters[i % 26]}{letters[i // 26]}" for i in range(words))
        + "."
    )


def test_an_over_long_draft_is_trimmed_facts_first_and_never_a_required_proposition():
    facts = [Proposition(f"F{k}", "fact", "court", "facts", f"S1{k}", _filler(k, 60 + k)) for k in range(5)]
    rec = record(*facts)
    draft = [*clean(), *(Sentence(p.source, (p.id,)) for p in facts)]
    limit = int(checks.LENGTH_BAND["de"][1] * v.TRIM_SHARE)
    assert sum(len(s.text.split()) for s in draft) > limit
    fiche = run(draft, Fake(), rec)
    kept = [s for s in fiche.sentences if s.status != "removed"]
    removed = [s for s in fiche.sentences if s.status == "removed"]
    assert sum(len(s.text.split()) for s in kept) <= limit
    assert removed and all(s.problems == ["left out for length"] for s in removed)
    assert {s.propositions[0] for s in removed} <= {"P1", "F0", "F1", "F2", "F3", "F4"}  # facts only
    assert removed[-1].propositions == ("F4",)  # the longest fact went first
    stated = {pid for s in kept for pid in s.propositions}
    assert {"P3", "P4"} <= stated and "P2" in stated  # the holding stays; the lower court's view outlasts the facts
    assert fiche.missing == [] and fiche.status == "needs_review"
    assert any(note.endswith("left out for length") for note in fiche.notes)
    # required propositions alone are never trimmed, however long
    long_rule = Proposition("P3", "rule", "court", "E.2.1", "S3", _filler(6, 320))
    only = Record(
        (long_rule, Proposition("P4", "answer", "court", "E.3", "S4", ANSWER)), "rejected", False, dict(PARTIES), None
    )
    same = run([Sentence(long_rule.source, ("P3",)), Sentence(S_ANSWER, ("P4",))], Fake(), only)
    assert [s.status for s in same.sentences] == ["written", "written"]
    assert any("still over" in note for note in same.notes)


def test_too_little_left_or_no_holding_of_the_court_is_a_failed_fiche():
    one = run([Sentence(S_ANSWER, ("P4",))], Fake())  # the call for the missing P3 has no answer: one sentence kept
    assert one.status == "failed" and one.missing == ["P3"]
    no_holding = run([Sentence(S_FACT, ("P1",)), Sentence(S_LOWER, ("P2",))], Fake())
    assert no_holding.status == "failed" and no_holding.missing == ["P3", "P4"]
    two = run([Sentence(S_RULE, ("P3",)), Sentence(S_ANSWER, ("P4",))], Fake())
    assert two.status == "ok"


# --- the other language -------------------------------------------------------------------------------------------


def test_a_french_fiche_of_a_german_ruling_must_use_the_glossary_term():
    row = next(
        r
        for r in pairs("uv")
        if r["de"].isalpha() and not r["de"].isupper() and len(r["de"]) > 8 and r["de"].lower() != r["fr"].lower()
    )
    source = f"Im vorliegenden Fall bildet {row['de']} den Gegenstand der Prüfung durch das Gericht."
    terms = required_terms(source, "de", "fr", "uv")
    assert (row["de"], row["fr"]) in terms
    rec = Record(
        (Proposition("P1", "rule", "court", "E.2", "S1", source), Proposition("P2", "answer", "court", "E.3", "S2", ANSWER)),
        "rejected", False, dict(PARTIES), None,
    )  # fmt: skip
    without = "Dans le cas présent, cet acte est l'objet de l'examen par le tribunal et il est examiné."
    with_terms = (
        "Dans le cas présent, " + " et ".join(dst for _, dst in terms) + " est l'objet de l'examen par le tribunal."
    )
    answer = "C'est à juste titre que la cour cantonale a confirmé la suppression des prestations."
    fake = Fake(**{REPAIR: [{"a_sentence": with_terms}]})
    fiche = run([Sentence(without, ("P1",)), Sentence(answer, ("P2",))], fake, rec, language="fr")
    first = fiche.sentences[0]
    assert first.status == "repaired" and first.text == with_terms
    assert first.problems[0].startswith("attempt 1: glossary term missing:") and row["fr"] in first.problems[0]
    assert fake.sent[0][0] == "v3-verify@1/repair" and f"Use '{row['fr']}' for '{row['de']}'" in prompt(fake, 0)
    assert "in Swiss legal French" in fake.sent[0][1][0]["content"]
    assert fiche.sentences[1].status == "written" and fiche.text.endswith("Le recours est rejeté.")
    # the same sentences for a French ruling need no glossary term
    french = {**ruling(), "language": "fr"}
    case = v._Case(rec, "fr", french, Model(Fake(), budget=5), "fr")
    assert v.code_problems(without, ("P1",), case) == []
