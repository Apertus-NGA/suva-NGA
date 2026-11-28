"""Tests of the forced-choice topic feature and of the variant evaluation. No gateway call: the client is a
declared fake (G9) that records the messages it was sent and returns fixed log-probabilities."""

from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pytest

from src.triage import features as ft
from src.triage import variants as vr

RULING = (
    "Urteil vom 3. März 2026\nII. sozialrechtliche Abteilung\nBesetzung\nBundesrichter A, B, C\nGerichtsschreiber X\n"
    "Sachverhalt:\nA. Die Versicherte bezog eine Hilflosenentschädigung.\n"
    "Erwägungen:\n1. Streitig ist die Revision der Hilflosenentschädigung.\n"
    "Demnach erkennt das Bundesgericht:\n1. Die Beschwerde wird abgewiesen."
)


def logprobs(**tokens: float) -> dict:
    return {"content": [{"top_logprobs": [{"token": t, "logprob": math.log(p)} for t, p in tokens.items()]}]}


class FakeClient:
    """Declared mock of src.llm.client.LLMClient.chat."""

    def __init__(self, answer=None, fail=False):
        self.answer, self.fail, self.sent = answer, fail, []

    def chat(self, messages, **kwargs):
        self.sent.append((messages, kwargs))
        if self.fail:
            raise RuntimeError("gateway down")
        return SimpleNamespace(logprobs=self.answer)


def test_letter_probabilities_normalise_over_letters_only():
    probs = ft.letter_probabilities(logprobs(**{"F": 0.5, " D": 0.25, "Ja": 0.2, "x": 0.05}))
    assert probs["F"] == pytest.approx(2 / 3)
    assert probs["D"] == pytest.approx(1 / 3)
    assert sum(probs.values()) == pytest.approx(1.0)


def test_no_letter_is_no_answer_not_a_negative():
    assert ft.letter_probabilities(logprobs(Ja=0.9, Nein=0.1)) is None
    assert ft.group_features(None) == {f"f_topic_{g}": None for g in ft.GROUPS}


def test_groups_cover_each_letter_at_most_once():
    used = [k for ks in ft.GROUPS.values() for k in ks]
    assert len(used) == len(set(used))
    assert set(used) <= set(ft.TOPICS)


def test_read_topic_sends_ruling_first_question_last_and_one_token():
    client = FakeClient(logprobs(F=0.6, D=0.3, A=0.1))
    out = ft.read_topic(client, RULING, size="small")
    messages, kwargs = client.sent[0]
    assert messages[0]["role"] == "system" and len(messages) == 2
    user = messages[1]["content"]
    assert user.index("<urteil>") < user.index("Welche Rechtsfrage") and user.rstrip().endswith("A bis J.")
    assert "Hilflosenentschädigung" in user
    assert kwargs["max_tokens"] == 1 and kwargs["top_logprobs"] == 20 and kwargs["first_token_only"]
    assert kwargs["size"] == "small" and kwargs["prompt_version"] == ft.VERSION
    assert out["answer"] == "F"
    assert out["f_topic_shared"] == pytest.approx(0.9)
    assert out["f_topic_medical"] == pytest.approx(0.1)


def test_failed_call_gives_empty_features():
    out = ft.read_topic(FakeClient(fail=True), RULING)
    assert out["answer"] is None and all(v is None for k, v in out.items() if k.startswith("f_"))


def test_needed_is_shortest_list_reaching_target():
    scores = np.array([0.9, 0.8, 0.7, 0.6, 0.5])
    y = np.array([1, 0, 1, 0, 1])
    assert vr.needed(scores, y, 1.0) == 5
    assert vr.needed(scores, y, 0.6) == 3


def _table(seed=0):
    rng = np.random.default_rng(seed)
    n = 200
    signal = rng.normal(size=n)
    y = (signal + rng.normal(scale=0.8, size=n) > 1.0).astype(int)
    return {
        "good": signal,
        "noise": rng.normal(size=n),
        "y": y,
        "quarter": np.array(["2025 Q4"] * 100 + ["2026 Q1"] * 100),
        "core": np.ones(n, bool),
    }


def test_evaluate_counts_and_pass_rule_on_synthetic_data():
    table = _table()
    good = vr.evaluate(vr.Variant("good", ["good"], vr.logistic), table)
    noise = vr.evaluate(vr.Variant("noise", ["noise"], vr.logistic), table)
    assert good["relevant_total"] == int(table["y"].sum())
    assert good["pooled"]["0.40"]["submitted"] == 80  # 40% of 100 core rulings per test quarter, two quarters
    assert good["pooled"]["0.40"]["found"] > noise["pooled"]["0.40"]["found"]
    assert vr.beats(good, noise) and not vr.beats(noise, good)
    assert not vr.beats(good, good)  # a variant never beats itself: the rule needs +2 found


def test_xgboost_variant_runs_weighted():
    out = vr.evaluate(vr.Variant("xgb", ["good", "noise"], vr.xgboost, weighted=True), _table(1))
    assert out["pooled"]["0.40"]["found"] > 0
