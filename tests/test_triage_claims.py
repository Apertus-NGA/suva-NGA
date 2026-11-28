"""Tests of the harnessed Apertus readings (src/triage/claims.py). No gateway call: the client is a declared
fake (G9) that records what it was sent and returns a fixed answer."""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from src.triage import claims as cl

RULING = (
    "Urteil vom 3. März 2026\nBesetzung\nBundesrichter A, B, C\nGerichtsschreiber X\n"
    "Sachverhalt:\nA. Die Versicherte verlangte eine Rente.\n"
    "Erwägungen:\n1. Das Bundesgericht prüft frei (Art. 95 BGG).\n"
    "2. Nach der Rechtsprechung ist der Tabellenlohn massgebend (BGE 148 V 174; Urteil 8C_123/2020).\n"
    "3. Streitig ist der Invaliditätsgrad nach Art. 16 ATSG.\n"
    "3.1. Die Rechtsprechung ist dahin zu präzisieren, dass der Abzug auch bei Teilzeitarbeit zu prüfen ist.\n"
    "3.2. Die Vorinstanz hat damit Bundesrecht verletzt.\n"
    "Demnach erkennt das Bundesgericht:\n1. Die Beschwerde wird gutgeheissen."
)


def logprobs(**tokens: float) -> dict:
    return {"content": [{"top_logprobs": [{"token": t, "logprob": math.log(p)} for t, p in tokens.items()]}]}


class FakeClient:
    """Declared mock of src.llm.client.LLMClient.chat."""

    def __init__(self, content="", answer=None, fail=False):
        self.content, self.answer, self.fail, self.sent = content, answer, fail, []

    def chat(self, messages, **kwargs):
        self.sent.append((messages, kwargs))
        if self.fail:
            raise RuntimeError("gateway down")
        return SimpleNamespace(logprobs=self.answer, content=self.content)


YES = logprobs(Ja=0.8, Nein=0.2)


def test_zero_arm_is_one_token_and_asks_for_no_evidence():
    client = FakeClient(answer=YES)
    out = cl.read_claim(client, RULING, cl.PRACTICE, "zero")
    user, kwargs = client.sent[0][0][1]["content"], client.sent[0][1]
    assert user.rstrip().endswith("Ja oder Nein.") and "Erwägung, in der" not in user
    assert kwargs["max_tokens"] == 1 and kwargs["first_token_only"]
    assert kwargs["prompt_version"] == "claim_practice_zero@1"
    assert out["p"] == pytest.approx(0.8) and out["check"] is None and out["consideration"] is None


def test_cited_arm_lists_the_numbers_and_checks_the_markers_in_the_cited_consideration():
    client = FakeClient("Ja\n3.1", YES)
    out = cl.read_claim(client, RULING, cl.PRACTICE, "cited")
    assert "gewählt aus dieser Liste: 1, 2, 3, 3.1, 3.2;" in client.sent[0][0][1]["content"]
    assert out["consideration"] == "3.1" and out["check"] is True and out["evidence"].startswith("Die Rechtsprechung")
    wrong_place = cl.read_claim(FakeClient("Ja\n1", YES), RULING, cl.PRACTICE, "cited")
    assert wrong_place["consideration"] == "1" and wrong_place["check"] is False  # no such wording there
    invented = cl.read_claim(FakeClient("Ja\n7.4", YES), RULING, cl.PRACTICE, "cited")
    assert invented["consideration"] is None and invented["check"] is False and invented["p"] == pytest.approx(0.8)
    no = cl.read_claim(FakeClient("Nein\n-", logprobs(Ja=0.1, Nein=0.9)), RULING, cl.PRACTICE, "cited")
    assert no["consideration"] is None and no["check"] is False


def test_located_arm_checks_the_consideration_even_for_a_no():
    out = cl.read_claim(FakeClient("Nein\n3.2", logprobs(Ja=0.3, Nein=0.7)), RULING, cl.LEGAL_ERROR, "located")
    assert out["label"] == "nein" and out["consideration"] == "3.2" and out["check"] is True
    assert out["p"] == pytest.approx(0.3)


def test_a_top_level_number_covers_its_sub_considerations():
    cons = cl.ev.considerations(cl.p.sections(RULING)["reasoning"])
    text = cl.block(cons, "3")
    assert "Invaliditätsgrad" in text and "präzisieren" in text and "Bundesrecht verletzt" in text
    assert "Tabellenlohn" not in text


def test_failures_and_unnumbered_rulings_give_no_reading():
    assert cl.read_claim(FakeClient(fail=True), RULING, cl.PRACTICE, "zero")["p"] is None
    client = FakeClient("Ja\n1", YES)
    assert cl.read_claim(client, "Kein nummerierter Text.", cl.PRACTICE, "cited")["p"] is None
    assert client.sent == []  # not asked at all
    assert cl.read_locate(FakeClient(fail=True), RULING)["consideration"] is None


def test_measure_is_deterministic_and_reads_markers_citations_and_laws():
    m = cl.measure("Die Rechtsprechung ist zu präzisieren (BGE 148 V 174; Urteil 8C_123/2020), Art. 16 ATSG.", 200)
    assert m["practice"] == 1.0 and m["error"] == 0.0 and m["shared_law"] == 1.0
    assert m["case_law"] == pytest.approx(math.log1p(2))
    assert cl.measure("Art. 95 BGG")["shared_law"] == 0.0
    assert set(m) == set(cl.MEASURES)


def test_articles_map_french_and_italian_law_names_to_one_family():
    assert cl.articles("Art. 16 ATSG, art. 16 LPGA et art. 28 al. 1 LAI; art. 6 cpv. 1 LAINF") == [
        ("16", "atsg"),
        ("16", "atsg"),
        ("28", "ivg"),
        ("6", "uvg"),
    ]


def test_locate_measures_only_the_consideration_apertus_points_to():
    client = FakeClient("3")
    out = cl.read_locate(client, RULING)
    assert client.sent[0][0][1]["content"].rstrip().endswith("1, 2, 3, 3.1, 3.2.")
    assert out["consideration"] == "3" and out["practice"] == 1.0 and out["error"] == 1.0 and out["shared_law"] == 1.0
    assert out["case_law"] == 0.0 and 0 < out["share"] < 1  # the cited case law stands in consideration 2
    assert cl.whole_ruling(RULING)["case_law"] > 0
    assert cl.read_locate(FakeClient("9"), RULING)["consideration"] is None  # not a number of this ruling


def test_article_is_shared_only_when_the_cited_consideration_names_it():
    ok = cl.read_article(FakeClient("Art. 16 ATSG\n3"), RULING, "cited")
    assert ok["family"] == "atsg" and ok["check"] is True and ok["shared"] == 1.0
    elsewhere = cl.read_article(FakeClient("Art. 16 ATSG\n2"), RULING, "cited")
    assert elsewhere["check"] is False and elsewhere["shared"] == 0.0
    zero = cl.read_article(FakeClient("Art. 95 BGG"), RULING, "zero")
    assert zero["family"] == "bgg" and zero["shared"] == 0.0 and zero["check"] is None
    assert cl.read_article(FakeClient("Ich weiss es nicht."), RULING, "zero")["article"] is None
    assert cl.most_cited_article(RULING)["article"] in {"16", "95"}
