# ruff: noqa: E501  (test data: whole sentences of rulings and summaries, kept on one line to stay readable)
"""Tests of the refine loop (src/summarize/refine). The model is a declared fake transport: no gateway call (G9)."""

from __future__ import annotations

import json

import pytest

from src.summarize.refine import checks, evidence
from src.summarize.refine.draft import Draft, Patch, PatchRefused
from src.summarize.refine.model import Model, ModelFailed, enum, obj
from src.summarize.refine.record import validate
from src.summarize.refine.runner import refine, run_step
from src.summarize.refine.step import Candidate, Context, Step
from src.summarize.refine.steps.facts import Facts
from src.summarize.refine.steps.form import Form
from src.summarize.refine.steps.holding import Holding
from src.summarize.refine.steps.length import Length
from src.summarize.refine.steps.terms import Terms

RULING = """Urteil vom 3. Juni 2025
Besetzung
Bundesrichterin Heine, Präsidentin,
Bundesrichter Métral, Bundesrichterin Viscione,
Gerichtsschreiber Grünenfelder.

Sachverhalt:
A. Der Versicherte stürzte am 7. Mai 2023 von einer Leiter. Die Suva verneinte mit Einspracheentscheid vom
12. Oktober 2023 einen Anspruch auf Leistungen über den 30. Juni 2023 hinaus.

Erwägungen:
1. Die Beschwerde ist zulässig (Art. 82 BGG).

2. Streitig ist, ob die Suva ihre Leistungen zu Recht per 30. Juni 2023 eingestellt hat.

2.1 Die Leistungspflicht des Unfallversicherers setzt einen natürlichen Kausalzusammenhang voraus (Art. 6 Abs. 1 UVG).
Fällt dieser dahin, endet die Leistungspflicht.

3. Gemäss den Berichten war der Status quo sine am 30. Juni 2023 erreicht. Die Vorinstanz hat die
Leistungseinstellung daher zu Recht bestätigt.

Demnach erkennt das Bundesgericht:
1. Die Beschwerde wird abgewiesen.
2. Die Gerichtskosten von Fr. 800.- werden dem Beschwerdeführer auferlegt.
"""

DRAFT = (
    "Der Versicherte stürzte von einer Leiter. Die Suva stellte ihre Leistungen per 30. Juni 2023 ein.\n\n"
    "Das Bundesgericht hielt fest, dass die Leistungspflicht immer auch ohne Kausalzusammenhang besteht.\n\n"
    "Die Beschwerde wird abgewiesen."
)


class Fake:
    """A declared fake of the gateway: answers by prompt-version prefix, in order, and records what was sent."""

    def __init__(self, **answers: list[dict]) -> None:
        self.answers = {k: list(v) for k, v in answers.items()}
        self.sent: list[tuple[str, list[dict]]] = []

    def __call__(self, messages, response_format, prompt_version, max_tokens):
        self.sent.append((prompt_version, messages))
        for prefix, queue in self.answers.items():
            if prompt_version.startswith(prefix.replace("__", "/")) and queue:
                return json.dumps(queue.pop(0))
        raise AssertionError(f"unexpected call {prompt_version}")


def ctx_for(fake: Fake, record: dict | None = None, language: str = "de", lexicon: str = "") -> Context:
    return Context(language, RULING, evidence.passages(RULING), "uv", Model(fake, budget=10), record, lexicon, "de")


# --- evidence -----------------------------------------------------------------------------------------------------


def test_passages_follow_the_numbering_and_keep_dates_as_text():
    parts = evidence.passages(RULING)
    assert list(parts) == ["facts", "E.1", "E.2", "E.2.1", "E.3", "operative"]
    assert "7. Mai 2023" in parts["facts"]
    assert parts["operative"].startswith("Demnach erkennt")


def test_a_quote_matches_despite_spacing_quotes_and_line_breaks_but_an_invented_one_does_not():
    parts = evidence.passages(RULING)
    assert evidence.quote_in("Die Vorinstanz hat die  Leistungseinstellung daher zu Recht bestätigt", parts["E.3"])
    assert evidence.quote_in(
        "Leistungspflicht des Unfallversicherers ... natürlichen Kausalzusammenhang", parts["E.2.1"]
    )
    assert not evidence.quote_in("Die Vorinstanz hat die Leistungseinstellung zu Unrecht bestätigt", parts["E.3"])
    assert evidence.locate("Die Vorinstanz hat die Leistungseinstellung daher zu Recht", parts, "E.2") == "E.3"
    assert evidence.locate("zu kurz", parts) is None


def test_rule_candidates_leave_out_admissibility_when_the_merits_are_decided():
    candidates, excluded = evidence.rule_candidates(evidence.passages(RULING), merits=True)
    assert "E.1" not in candidates and excluded["E.1"] == "admissibility"
    assert "E.2.1" in candidates


# --- draft --------------------------------------------------------------------------------------------------------


def test_sentences_do_not_split_after_abbreviations_or_ordinals():
    draft = Draft.from_text("Nach Art. 6 Abs. 1 UVG gilt dies (E. 4.2). Am 1. Januar 2024 trat es in Kraft. Gut.")
    assert [s.text for s in draft.sentences] == [
        "Nach Art. 6 Abs. 1 UVG gilt dies (E. 4.2).",
        "Am 1. Januar 2024 trat es in Kraft.",
        "Gut.",
    ]


def test_the_outcome_sentence_is_locked_and_a_patch_on_it_is_refused():
    draft = Draft.from_text(DRAFT)
    assert draft.sentences[-1].locked
    with pytest.raises(PatchRefused):
        draft.apply(Patch("replace", draft.sentences[-1].id, "Die Beschwerde wird gutgeheissen."))
    edited = draft.apply(Patch("delete", "s2"))
    assert [s.id for s in edited.sentences] == ["s1", "s2", "s3"]
    assert "Leistungen per" not in edited.render()
    assert edited.render().count("\n\n") == 2


def test_a_span_patch_changes_only_the_span():
    draft = Draft.from_text("Die Rente wird verneint. Ende.")
    after = draft.apply(Patch("replace", "s1", "Invalidenrente", span="Rente"))
    assert after.sentences[0].text == "Die Invalidenrente wird verneint."
    with pytest.raises(PatchRefused):
        draft.apply(Patch("replace", "s1", "x", span="nicht da"))


# --- model seam ---------------------------------------------------------------------------------------------------


def test_an_id_outside_the_enum_is_rejected_and_the_budget_is_enforced():
    shape = obj({"a_sentence": enum(["s1", "s2"])})
    model = Model(lambda *a: json.dumps({"a_sentence": "s9"}), budget=2)
    with pytest.raises(ModelFailed, match="allowed ids"):
        model.ask([{"role": "user", "content": "x"}], "t", shape, "v")
    model = Model(lambda *a: "not json", budget=3)
    with pytest.raises(ModelFailed, match="not valid JSON"):  # one targeted retry, then the item fails
        model.ask([{"role": "user", "content": "x"}], "t", shape, "v")
    assert model.calls == 2
    with pytest.raises(ModelFailed, match="budget"):
        model.ask([{"role": "user", "content": "x"}], "t", shape, "v")


def test_an_invalid_answer_gets_one_retry_that_names_the_error():
    answers = iter([json.dumps({"a_sentence": "s9"}), json.dumps({"a_sentence": "s2"})])
    sent = []
    model = Model(lambda messages, *a: sent.append(messages) or next(answers), budget=5)
    assert model.ask([{"role": "user", "content": "x"}], "t", obj({"a_sentence": enum(["s1", "s2"])}), "v") == {
        "a_sentence": "s2"
    }
    assert "'s9' is not one of the allowed ids" in sent[1][-1]["content"]
    assert 'one of ["s1", "s2"]' in sent[0][-1]["content"]  # the format is stated in the prompt


# --- the acceptance rule ----------------------------------------------------------------------------------------


class _OneShot(Step):
    id = "probe"

    def __init__(self, candidate: Candidate) -> None:
        self.candidate = candidate

    def propose(self, draft, ctx):
        return [self.candidate]


def test_a_patch_that_breaks_a_code_check_is_reverted():
    ctx = ctx_for(Fake())
    draft = Draft.from_text(DRAFT)
    sentence = draft.sentences[0].text
    bad = Candidate("probe", sentence, patch=Patch("replace", "s0", "Le recours de l'assuré selon la LAA."))
    after, outcome = run_step(_OneShot(bad), draft, ctx)
    assert after.render() == draft.render()
    assert outcome.status == "needs_review"
    assert "would break" in outcome.findings[0]["why_not"]


def test_a_failed_model_call_is_needs_review_and_the_loop_goes_on():
    ctx = ctx_for(Fake())  # no answers: every call raises
    result = refine(DRAFT, ctx, [Facts(), Form("form_final")])
    assert [o.status for o in result.trace] == ["needs_review", "passed"]
    assert result.text == Draft.from_text(DRAFT).render()


# --- steps ----------------------------------------------------------------------------------------------------------


def test_form_puts_references_in_the_fiche_language_and_drops_invented_ones():
    ctx = ctx_for(Fake(), language="fr")
    text = "Le Tribunal fédéral rappelle la règle (E. 2.1). Il cite aussi un considérant absent (consid. 9.4).\n\nLe recours est rejeté."
    result = refine(text, ctx, [Form()])
    assert "(consid. 2.1)" in result.text
    assert "9.4" not in result.text


def test_facts_rewrites_an_unsupported_sentence_from_a_verified_quote():
    detect = {"items": [
        {"a_sentence": "s1", "b_label": "facts", "c_opening": "A. Der Versicherte stürzte am 7. Mai", "d_verdict": "same"},
        {"a_sentence": "s2", "b_label": "facts", "c_opening": "Die Suva verneinte mit Einspracheentscheid vom", "d_verdict": "same"},
        {"a_sentence": "s3", "b_label": "E.2.1", "c_opening": "Die Leistungspflicht des Unfallversicherers setzt einen", "d_verdict": "different"},
    ]}  # fmt: skip
    repair = {"a_label": "E.2.1", "b_opening": "Die Leistungspflicht des Unfallversicherers setzt einen natürlichen",
              "c_action": "rewrite",
              "d_sentence": "Das Bundesgericht hielt fest, dass die Leistungspflicht einen natürlichen Kausalzusammenhang voraussetzt."}  # fmt: skip
    recheck = {"items": [{"a_sentence": "s3", "b_label": "E.2.1", "c_opening": "Die Leistungspflicht des Unfallversicherers setzt einen", "d_verdict": "same"}]}  # fmt: skip
    fake = Fake(**{"facts@5__detect": [detect], "facts@5__repair": [repair], "facts@5__recheck": [recheck]})
    result = refine(DRAFT, ctx_for(fake), [Facts()])
    assert "ohne Kausalzusammenhang" not in result.text
    assert "natürlichen Kausalzusammenhang voraussetzt" in result.text
    assert result.trace[0].status == "corrected"
    # the ruling went to the model as labelled data
    assert "[E.2.1]" in fake.sent[0][1][1]["content"] and "<ruling>" in fake.sent[0][1][1]["content"]
    # the evidence stored is the ruling's own sentence, copied by code from the pointer
    finding = result.trace[0].findings[0]
    assert finding["quote"].startswith("Die Leistungspflicht des Unfallversicherers") and finding["evidence"] == "E.2.1"


def test_facts_refuses_a_repair_whose_quote_is_invented():
    detect = {"items": [{"a_sentence": "s3", "b_label": "E.2.1", "c_opening": "x " * 10, "d_verdict": "not_in_ruling"}]}
    repair = {"a_label": "E.3", "b_opening": "Das Bundesgericht hat dies nie gesagt, aber",
              "c_action": "rewrite", "d_sentence": "Die Leistungspflicht besteht nach Art. 99 UVG immer."}  # fmt: skip
    fake = Fake(**{"facts@5__detect": [detect], "facts@5__repair": [repair]})
    result = refine(DRAFT, ctx_for(fake), [Facts()])
    assert result.text == Draft.from_text(DRAFT).render()
    why = result.trace[0].findings[0]["why_not"]
    assert "was not found" in why and "99" in why


RECORD = {
    "rules": [{"label": "E.2.1", "quote": "Die Leistungspflicht des Unfallversicherers setzt einen natürlichen Kausalzusammenhang voraus"}],
    "answer": {"label": "E.3", "quote": "Die Vorinstanz hat die Leistungseinstellung daher zu Recht bestätigt"},
    "status": "ok",
}  # fmt: skip


def test_holding_inserts_each_missing_rule_with_the_reference_added_by_code():
    record = {
        **RECORD,
        "rules": [
            *RECORD["rules"],
            {"label": "E.3", "quote": "Gemäss den Berichten war der Status quo sine am 30. Juni 2023 erreicht."},
        ],
    }
    detect = {
        "a_rules": [{"a_rule": "R1", "b_sentence": "none"}, {"a_rule": "R2", "b_sentence": "s1"}],
        "b_answer_sentence": "none",
    }
    repair = {"a_after": "s2", "b_sentences": [
        {"a_item": "R1", "b_text": "Die Leistungspflicht des Unfallversicherers setzt einen natürlichen Kausalzusammenhang voraus."},
        {"a_item": "A", "b_text": "Da der Status quo sine erreicht war, durfte die Suva die Leistungen einstellen."},
    ]}  # fmt: skip
    confirm = {"a_states": "yes"}  # the targeted question about the sentence written for R1
    fake = Fake(**{"holding@3__detect": [detect], "holding@3__repair": [repair], "holding@3__confirm": [confirm]})
    result = refine(DRAFT, ctx_for(fake, record), [Holding()])
    assert (
        "voraus (E. 2.1). Da der Status quo sine erreicht war, durfte die Suva die Leistungen einstellen (E. 3)."
        in result.text
    )
    assert result.trace[0].status == "corrected"
    assert "R2 (E.3)" in fake.sent[0][1][1]["content"]


def test_holding_refuses_an_insert_when_the_re_check_still_misses_a_rule():
    detect = {"a_rules": [{"a_rule": "R1", "b_sentence": "none"}], "b_answer_sentence": "s3"}
    repair = {"a_after": "s1", "b_sentences": [{"a_item": "R1", "b_text": "Die Suva muss immer zahlen."}]}
    fake = Fake(
        **{"holding@3__detect": [detect], "holding@3__repair": [repair], "holding@3__confirm": [{"a_states": "no"}]}
    )
    result = refine(DRAFT, ctx_for(fake, RECORD), [Holding()])
    assert result.text == Draft.from_text(DRAFT).render()
    assert "R1 not stated faithfully" in result.trace[0].findings[0]["why_not"]


def test_holding_is_skipped_without_a_checked_record():
    result = refine(DRAFT, ctx_for(Fake(), {"rules": [], "status": "needs_review"}), [Holding()])
    assert result.trace[0].status == "skipped" and result.calls == 0


def test_terms_swaps_a_glossary_term_and_refuses_an_unattested_replacement():
    text = "Die Suva erliess eine décision sur opposition. Der Versicherte erhielt ein Taggeldchen.\n\nDie Beschwerde wird abgewiesen."
    answer = {
        "items": [
            {"a_sentence": "s2", "b_span": "Taggeldchen", "c_replacement": "Zauberwort", "d_reason": "not_swiss_usage"}
        ]
    }
    result = refine(text, ctx_for(Fake(**{"terms@1": [answer]}), lexicon="Taggeld"), [Terms()])
    assert "Einspracheentscheid" in result.text
    assert "Zauberwort" not in result.text
    assert any("not attested" in f.get("why_not", "") for f in result.trace[0].findings)


def test_length_drops_the_least_important_sentences_only_until_inside_the_band():
    filler = " ".join(["Die Vorinstanz prüfte die Akten sorgfältig und ausführlich."] * 1)
    long = " ".join(f"Satz {n} {filler * 6}" for n in range(8)) + "\n\nDie Beschwerde wird abgewiesen."
    draft = Draft.from_text(long)
    assert draft.words() > checks.LENGTH_BAND["de"][1]
    order = {"a_least_important": [s.id for s in draft.sentences if not s.locked]}
    result = refine(long, ctx_for(Fake(**{"length@1": [order]})), [Length()])
    words = len(result.text.split())
    assert checks.LENGTH_BAND["de"][0] <= words <= checks.LENGTH_BAND["de"][1]
    assert result.text.endswith("Die Beschwerde wird abgewiesen.")


def test_new_identifiers_catch_an_invented_article_or_number():
    assert checks.new_identifiers("Nach Art. 6 UVG endet die Pflicht am 30. Juni 2023.", "", RULING) == []
    found = checks.new_identifiers("Nach Art. 19 UVG gilt eine Frist von 245 Tagen.", "", RULING)
    assert any("19" in p for p in found) and any("245" in p for p in found)


def test_record_moves_a_quote_to_its_real_passage_and_drops_an_invented_one():
    parts = evidence.passages(RULING)
    candidates, _ = evidence.rule_candidates(parts, merits=True)
    answer = {
        "a_question": {"a_label": "E.2", "b_opening": "Streitig ist, ob die Suva ihre Leistungen", "c_sentences": "1"},
        "b_rules": [{"a_label": "E.3", "b_opening": "Die Leistungspflicht des Unfallversicherers setzt einen natürlichen", "c_sentences": "2"},
                    {"a_label": "E.2.1", "b_opening": "Ein erfundener Grundsatz, den es nicht gibt", "c_sentences": "1"}],
        "c_answer": {"a_label": "E.3", "b_opening": "Die Vorinstanz hat die Leistungseinstellung daher", "c_sentences": "1"},
    }  # fmt: skip
    record = validate(answer, parts, candidates)
    assert record["rules"] == [{
        "label": "E.2.1",
        "quote": "Die Leistungspflicht des Unfallversicherers setzt einen natürlichen Kausalzusammenhang voraus "
                 "(Art. 6 Abs. 1 UVG). Fällt dieser dahin, endet die Leistungspflicht.",
        "moved_from": "E.3",
    }]  # fmt: skip
    assert record["status"] == "ok"
    assert any("rule 1" in issue for issue in record["issues"])


# --- three real rulings (German, French, Italian), from the project database ---------------------------------------


@pytest.fixture(scope="module")
def corpus():
    """The project database, read only (DATABASE_URL); skipped when it is not reachable or not built."""
    from suva_data import db

    try:
        conn = db.connect()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"project database not reachable: {exc}")
    yield conn
    conn.close()


@pytest.mark.parametrize("docket", ["8C_676/2024", "8C_178/2025", "8C_135/2025"])
def test_real_rulings_split_into_considerations_and_an_operative_part(corpus, docket):
    row = corpus.execute(
        "SELECT t.text FROM rulings r JOIN ruling_texts t ON t.ruling_id = r.id AND t.is_canonical WHERE r.docket = %s",
        (docket,),
    ).fetchone()
    if row is None:
        pytest.skip(f"{docket} is not in the test database")
    parts = evidence.passages(row[0])
    assert "operative" in parts and "facts" in parts
    assert sum(label.startswith("E.") for label in parts) >= 3
    # a real sentence of a consideration, with its spacing changed, is found and attributed to that consideration
    label = [lab for lab in parts if lab.startswith("E.")][2]
    sentence = next(s for s in parts[label].split(". ") if len(s) > 60)
    assert evidence.locate("  ".join(sentence.split()), parts) == label


# --- the pipeline stores the draft, the refined text and the trace ---------------------------------------------------


@pytest.mark.db
def test_the_pipeline_stores_the_refined_fiche_its_draft_and_every_step(db_conn):
    from src.summarize import pipeline
    from tests.test_summary_pipeline import FakeModel, _ruling

    rid = _ruling(db_conn)
    rule = {"a_label": "E.4.1", "b_opening": "Nach Art. 6 Abs. 1 UVG werden", "c_sentences": "1"}
    answer = {"a_label": "E.4.2", "b_opening": "Hier fehlt der natürliche Kausalzusammenhang", "c_sentences": "1"}
    fake = Fake(**{
        "record@5__0": [{"a_question": rule, "b_rules": [rule], "c_answer": answer}],
        "facts@5__detect": [{"items": []}, {"items": []}],
        "holding@3__detect": [{"a_rules": [{"a_rule": "R1", "b_sentence": "s1"}], "b_answer_sentence": "s1"}] * 2,
        "terms@1": [{"items": []}, {"items": []}],
        "language@1__detect": [{"items": []}, {"items": []}],
    })  # fmt: skip
    result = pipeline.summarise_ruling(db_conn, rid, ask=FakeModel(), model="test", refine=True, refine_transport=fake)
    params = db_conn.execute("SELECT params FROM model_runs WHERE kind = 'summary'").fetchone()[0]
    stored = dict(db_conn.execute("SELECT language, body FROM summaries WHERE ruling_id = %s", (rid,)).fetchall())
    for language in ("de", "fr"):
        refine = params["refine"][language]
        assert [s["step"] for s in refine["steps"]] == [
            "form", "facts", "context", "holding", "economy", "terms", "language", "length", "form_final",
        ]  # fmt: skip
        assert refine["draft"] and stored[language] == result["languages"][language]["text"]
    assert params["refine"]["record"]["status"] == "ok"
    assert sum(v.startswith("record@5") for v, _ in fake.sent) == 1  # one shared reading for both languages


def test_an_injected_ask_without_a_refine_transport_is_refused():
    from src.summarize import pipeline

    with pytest.raises(ValueError, match="refine_transport"):
        pipeline.summarise_ruling(None, 1, ask=lambda m: "", refine=True)


def test_facts_flags_by_code_a_sentence_naming_suva_when_the_ruling_has_another_insurer():
    ruling = RULING.replace("Die Suva verneinte", "Die Generali verneinte").replace("ob die Suva", "ob die Generali")
    draft = "Die Suva verneinte weitere Leistungen. Der Versicherte stürzte von einer Leiter.\n\nDie Beschwerde wird abgewiesen."
    detect = {"items": []}  # the model sees nothing wrong; code does
    repair = {
        "a_label": "facts",
        "b_opening": "Die Generali verneinte mit Einspracheentscheid vom",
        "c_action": "rewrite",
        "d_sentence": "Der Unfallversicherer verneinte weitere Leistungen.",
    }
    recheck = {
        "items": [
            {
                "a_sentence": "s1",
                "b_label": "facts",
                "c_opening": "Die Generali verneinte mit Einspracheentscheid vom",
                "d_verdict": "same",
            }
        ]
    }
    fake = Fake(**{"facts@5__detect": [detect], "facts@5__repair": [repair], "facts@5__recheck": [recheck]})
    ctx = Context("de", ruling, evidence.passages(ruling), "uv", Model(fake, budget=10), None, "", "de")
    result = refine(draft, ctx, [Facts()])
    assert result.text.startswith("Der Unfallversicherer verneinte")
    assert result.trace[0].findings[0]["detected_by"] == "code"
    assert "not Suva" in fake.sent[1][1][1]["content"]
    # both calls share the system message and the ruling, so the gateway's prefix cache reads the ruling once
    first, second = fake.sent[0][1], fake.sent[1][1]
    cut = first[1]["content"].index("</ruling>")
    assert first[0] == second[0] and first[1]["content"][:cut] == second[1]["content"][:cut]


def test_economy_takes_a_restated_outcome_out_of_another_sentence():
    from src.summarize.refine.steps.economy import Economy

    facts = "Der Versicherte stürzte am 7. Mai 2023 von einer Leiter, die Suva stellte ihre Leistungen per 30. Juni 2023 ein. "
    draft = (
        facts + "Das Bundesgericht hat die Beschwerde abgewiesen, weil der Kausalzusammenhang fehlte.\n\n"
        "Die Beschwerde wird abgewiesen."
    )
    answer = {"a_action": "rewrite", "b_sentence": "Der natürliche Kausalzusammenhang fehlte."}
    result = refine(draft, ctx_for(Fake(**{"economy@1": [answer]})), [Economy()])
    assert result.text == facts + "Der natürliche Kausalzusammenhang fehlte.\n\nDie Beschwerde wird abgewiesen."
    refused = refine(
        draft,
        ctx_for(Fake(**{"economy@1": [{"a_action": "rewrite", "b_sentence": "Die Beschwerde wurde abgewiesen."}]})),
        [Economy()],
    )
    assert "still states the outcome" in refused.trace[0].findings[0]["why_not"]


def test_context_adds_the_facts_to_a_summary_under_the_band_from_a_ruling_sentence():
    from src.summarize.refine.steps.context import ContextStep

    short = "Das Bundesgericht bestätigte die Leistungseinstellung.\n\nDie Beschwerde wird abgewiesen."
    answer = {
        "a_label": "facts",
        "b_opening": "Der Versicherte stürzte am 7. Mai 2023",
        "c_text": "Der Versicherte stürzte am 7. Mai 2023 von einer Leiter; die Suva stellte ihre Leistungen per 30. Juni 2023 ein.",
    }
    recheck = {
        "items": [
            {
                "a_sentence": "s1",
                "b_label": "facts",
                "c_opening": "Der Versicherte stürzte am 7. Mai 2023",
                "d_verdict": "same",
            }
        ]
    }
    fake = Fake(**{"context@3": [answer], "facts@5__recheck": [recheck]})
    result = refine(short, ctx_for(fake), [ContextStep()])
    assert result.text.startswith("Der Versicherte stürzte am 7. Mai 2023 von einer Leiter")
    assert result.trace[0].status == "corrected" and result.trace[0].findings[0]["evidence"] == "facts"
    invented = {
        "a_label": "facts",
        "b_opening": "Der Versicherte stürzte am 7. Mai 2023",
        "c_text": "Der Versicherte stürzte am 9. Mai 2021 aus 12 Metern Höhe.",
    }
    refused = refine(short, ctx_for(Fake(**{"context@3": [invented]})), [ContextStep()])
    assert "number 2021 not in the ruling" in refused.trace[0].findings[0]["why_not"]


def test_facts_deletes_only_an_invented_sentence_and_only_when_a_second_reading_agrees():
    detect = {"items": [{"a_sentence": "s3", "b_label": "none", "c_opening": "", "d_verdict": "not_in_ruling"}]}
    repair = {"a_label": "E.2.1", "b_opening": "", "c_action": "delete", "d_sentence": ""}
    agree = {"items": [{"a_sentence": "s3", "b_label": "none", "c_opening": "", "d_verdict": "not_in_ruling"}]}
    disagree = {
        "items": [
            {
                "a_sentence": "s3",
                "b_label": "E.2.1",
                "c_opening": "Die Leistungspflicht des Unfallversicherers setzt",
                "d_verdict": "same",
            }
        ]
    }
    kept = refine(
        DRAFT,
        ctx_for(Fake(**{"facts@5__detect": [detect], "facts@5__repair": [repair], "facts@5__confirm": [disagree]})),
        [Facts()],
    )
    assert "ohne Kausalzusammenhang" in kept.text and "second reading" in kept.trace[0].findings[0]["why_not"]
    gone = refine(
        DRAFT,
        ctx_for(Fake(**{"facts@5__detect": [detect], "facts@5__repair": [repair], "facts@5__confirm": [agree]})),
        [Facts()],
    )
    assert "ohne Kausalzusammenhang" not in gone.text


def test_facts_never_offers_delete_for_a_sentence_that_only_overstates():
    detect = {
        "items": [
            {
                "a_sentence": "s3",
                "b_label": "E.2.1",
                "c_opening": "Die Leistungspflicht des Unfallversicherers setzt",
                "d_verdict": "stronger_or_broader",
            }
        ]
    }
    fake = Fake(
        **{
            "facts@5__detect": [detect],
            "facts@5__repair": [{"a_label": "E.2.1", "b_opening": "x", "c_action": "delete", "d_sentence": ""}],
        }
    )
    result = refine(DRAFT, ctx_for(fake), [Facts()])
    assert result.trace[0].status == "needs_review"  # 'delete' is not an allowed answer here: the answer is invalid
    assert '["rewrite"]' in fake.sent[1][1][-1]["content"]


def test_a_bad_item_of_a_list_is_dropped_and_the_rest_of_the_answer_stands():
    shape = obj({"items": {"type": "array", "items": obj({"a_sentence": enum(["s1", "s2"])})}})
    answer = json.dumps({"items": [{"a_sentence": "s9"}, {"a_sentence": "s2"}]})
    assert Model(lambda *a: answer).ask([{"role": "user", "content": "x"}], "t", shape, "v") == {
        "items": [{"a_sentence": "s2"}]
    }


def test_form_writes_the_outcome_as_its_own_last_sentence_when_the_draft_buries_it():
    buried = (
        "Der Versicherte stürzte am 7. Mai 2023 von einer Leiter, und das Bundesgericht hat die Beschwerde "
        "abgewiesen, weil der natürliche Kausalzusammenhang am 30. Juni 2023 dahingefallen war."
    )
    result = refine(buried, ctx_for(Fake()), [Form()])
    assert result.text.endswith("dahingefallen war. Die Beschwerde wird abgewiesen.")
    assert Draft.from_text(result.text).sentences[-1].locked
    already = refine(DRAFT, ctx_for(Fake()), [Form()])
    assert already.text.count("Die Beschwerde wird abgewiesen.") == 1


def test_a_pointer_with_the_consideration_number_still_finds_the_sentence():
    parts = evidence.passages(RULING)
    assert evidence.find("2. Streitig ist, ob die Suva ihre Leistungen", parts)[0] == "E.2"


def test_a_pointer_that_paraphrases_its_end_or_drops_a_parenthetical_still_finds_the_sentence():
    parts = evidence.passages(RULING)
    # the model wrote the whole sentence and changed its end: the opening words still hold
    assert (
        evidence.find(
            "Die Leistungspflicht des Unfallversicherers setzt einen natürlichen Zusammenhang immer voraus", parts
        )[0]
        == "E.2.1"
    )
    # the model dropped a parenthetical of the ruling
    assert evidence.find("setzt einen natürlichen Kausalzusammenhang voraus. Fällt dieser dahin", parts)[0] == "E.2.1"
    assert evidence.find("Ein völlig erfundener Satz, der nirgends im Urteil steht", parts) is None


def test_a_rule_without_a_legal_anchor_is_not_a_rule():
    from src.summarize.refine.record import anchored

    assert anchored("Die Leistungspflicht setzt einen natürlichen Kausalzusammenhang voraus (Art. 6 Abs. 1 UVG).")
    assert anchored("Nach der Rechtsprechung ist der Status quo sine massgebend (BGE 146 V 51 E. 5.1).")
    assert not anchored("Il ricorrente contesta in questa sede unicamente il reddito da valido.")


def test_a_lower_courts_decision_is_a_fact_not_the_outcome():
    assert checks.restates_outcome("Das Bundesgericht wies die Beschwerde ab, weil der Kausalzusammenhang fehlte.")
    assert checks.restates_outcome("Le recours est rejeté.")
    assert not checks.restates_outcome("Das kantonale Gericht hiess die Beschwerde des Versicherten gut.")
    assert not checks.restates_outcome("La cour cantonale a admis le recours de l'assuré.")
