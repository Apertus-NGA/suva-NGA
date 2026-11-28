"""Triage v1: readings, consensus, score, cut and the rows written for the UI.

No network and no database. Declared fakes: `FakeClient` stands in for `src.llm.client.LLMClient` and returns
fixed log-probabilities; `FakeConn` stands in for a psycopg connection and records the SQL it is given.
"""
# ruff: noqa: E501  (header fixtures and expected rows read better on one line)

from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pytest

from src.triage import pipeline as pl
from src.triage import readings as rd
from src.triage import scorer as sc

NB = " "
RULING = (
    f"Bundesgericht{NB}\n\nUrteil vom 1. Dezember 2025{NB}\n\nBesetzung{NB}\n\nBundesrichterin Viscione, Präsidentin,{NB}\n\n"
    f"Bundesrichterinnen Heine, Scherrer Reber,{NB}\n\nGerichtsschreiber Hochuli.{NB}\n\nVerfahrensbeteiligte{NB}\n\n"
    f"A.________,{NB}\n\nBeschwerdeführer,{NB}\n\ngegen{NB}\n\nSchweizerische Unfallversicherungsanstalt (Suva),{NB}\n\n"
    f"Beschwerdegegnerin.{NB}\n\nGegenstand{NB}\n\nUnfallversicherung (Kausalzusammenhang),{NB}\n\n"
    "Sachverhalt:\n\nA. Der Versicherte verdrehte sich den Fuss.\n\nErwägungen:\n\n1. Streitig ist der Kausalzusammenhang. "
    + "Das Gericht prüft die Akten. " * 30
    + "\n\nDemnach erkennt das Bundesgericht:\n\n1. Die Beschwerde wird abgewiesen.\n"
)


def logprobs(**tokens: float) -> dict:
    return {"content": [{"top_logprobs": [{"token": t, "logprob": math.log(p)} for t, p in tokens.items()]}]}


class FakeClient:
    """Answers every call with the same first-token alternatives and records what it was sent."""

    def __init__(self, answer: dict | None = None, fail: bool = False) -> None:
        self.answer, self.fail, self.calls = answer, fail, []

    def chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if self.fail:
            raise RuntimeError("gateway down")
        return SimpleNamespace(logprobs=self.answer)


# --- readings ---------------------------------------------------------------------------------------------


def test_yes_reading_is_the_share_of_ja_among_yes_and_no():
    assert rd.value_from_logprobs(logprobs(Ja=0.6, Nein=0.2, Vielleicht=0.2), "yes") == pytest.approx(0.75)
    assert rd.value_from_logprobs(logprobs(**{" ja": 0.1, "Nein.": 0.9}), "yes") == pytest.approx(0.1)


def test_scale_reading_is_the_probability_weighted_level():
    value = rd.value_from_logprobs(logprobs(**{"1": 0.5, "2": 0.25, "4": 0.25}), "scale")
    assert value == pytest.approx(1 * 0.5 + 2 * 0.25 + 4 * 0.25)


@pytest.mark.parametrize("kind", ["yes", "scale"])
def test_a_reading_without_an_answer_token_is_empty_not_zero(kind):
    assert rd.value_from_logprobs(logprobs(Das=0.9, Urteil=0.1), kind) is None
    assert rd.value_from_logprobs(None, kind) is None


def test_every_reading_sends_the_ruling_first_and_the_question_last_as_one_token_call():
    doc = {**pl.sections(RULING), "uvmv": 1}
    client = FakeClient(logprobs(Ja=0.9, Nein=0.1, **{"2": 0.5}))
    values = rd.read_all(client, doc)
    assert set(values) == set(rd.READINGS) and len(client.calls) == 6
    for (messages, kwargs), (name, (version, _)) in zip(client.calls, rd.READINGS.items(), strict=True):
        assert [m["role"] for m in messages] == ["system", "user"], name
        user = messages[1]["content"]
        assert user.startswith("<urteil>") and "Streitig ist der Kausalzusammenhang" in user
        assert (
            user.rstrip().endswith((".", "Nein.")) and user.index("</urteil>") < len(user) - 100
        )  # question after the ruling
        assert kwargs == {
            "max_tokens": 1,
            "prompt_version": version,
            "logprobs": True,
            "top_logprobs": 20,
            "first_token_only": True,
        }


def test_a_failed_call_leaves_the_reading_empty():
    doc = {**pl.sections(RULING), "uvmv": 1}
    assert set(rd.read_all(FakeClient(fail=True), doc).values()) == {None}


# --- consensus --------------------------------------------------------------------------------------------


def reading(level: float) -> dict[str, float]:
    return {"verdict": 0.2 + 0.15 * level, "yes_strict": 0.1 + 0.2 * level, "scale_generic": level, "constant": 2.0}


def test_consensus_drops_a_reading_that_says_the_same_for_every_ruling_and_orders_rulings():
    consensus = sc.Consensus.fit([reading(v) for v in (1.0, 2.0, 3.0, 4.0)])
    assert set(consensus.stats) == {"verdict", "yes_strict", "scale_generic"}
    low, high = consensus.value(reading(1.0)), consensus.value(reading(4.0))
    assert low < 0 < high


def test_consensus_is_neutral_without_readings_and_uses_what_is_there():
    consensus = sc.Consensus.fit([reading(v) for v in (1.0, 2.0, 3.0, 4.0)])
    assert consensus.value(None) == 0.0 and consensus.value({}) == 0.0
    partial = {"verdict": None, "yes_strict": None, "scale_generic": 4.0}
    assert consensus.value(partial) > 0


# --- score and cut ----------------------------------------------------------------------------------------


def test_features_follow_the_declared_order_and_unknown_publication_is_not_yes():
    signals = {
        "area": "IV",
        "appeal_by_institution": True,
        "five_judges": False,
        "proposed_for_publication": "unknown",
        "core_topics": 3,
        "long_ruling": True,
        "other_accident_insurer": False,
    }
    row = dict(zip(sc.FEATURES, sc.features(signals, 0.7), strict=True))
    assert row == {
        "area_uvmv": 0.0,
        "area_iv": 1.0,
        "appeal_by_institution": 1.0,
        "five_judges": 0.0,
        "publication": 0.0,
        "manifestly_unfounded": 0.0,
        "suva_party": 0.0,
        "single_judge": 0.0,
        "consensus": 0.7,
        "core_topics": 3.0,
        "long_accident": 0.0,  # a long ruling counts under its own area only
        "long_disability": 1.0,
        "other_accident_insurer": 0.0,
    }
    accident = dict(zip(sc.FEATURES, sc.features({"area": "UV", "long_ruling": True}, 0.0), strict=True))
    assert accident["long_accident"] == 1.0 and accident["long_disability"] == 0.0 and accident["core_topics"] == 0.0


def toy_data(n: int = 120, seed: int = 0):
    rng = np.random.default_rng(seed)
    x = np.zeros((n, len(sc.FEATURES)))
    x[:, 0] = rng.integers(0, 2, n)  # accident insurance
    x[:, 2] = rng.integers(0, 2, n)  # appeal by an institution
    x[:, 8] = rng.normal(size=n)  # consensus
    y = ((x[:, 0] + x[:, 2] + 0.8 * x[:, 8] + rng.normal(scale=0.5, size=n)) > 1.2).astype(int)
    return x, y


def test_scorer_ranks_rulings_with_the_signals_higher_and_explains_each_rule():
    x, y = toy_data()
    model = sc.Scorer.fit(x, y, n_core=len(y))
    strong = [1, 0, 1, 0, 0, 0, 0, 0, 1.5, 0, 0, 0, 0]
    weak = [0, 0, 0, 0, 0, 0, 0, 0, -1.5, 0, 0, 0, 0]
    scores = model.score(np.array([strong, weak], float))
    assert scores[0] > scores[1] and 0 <= scores[1] <= scores[0] <= 1
    contributions = model.contributions(strong)
    assert set(contributions) == set(sc.FEATURES)
    assert contributions["area_uvmv"] > 0 and contributions["consensus"] > 0


def test_a_rule_never_turns_against_its_meaning():
    """Every weight keeps the sign fixed in SIGNS; a rule the labels contradict gets weight 0, not the other sign."""
    rng = np.random.default_rng(3)
    n = 200
    x = np.zeros((n, len(sc.FEATURES)))
    upheld, five, single = (sc.FEATURES.index(k) for k in ("area_uvmv", "five_judges", "single_judge"))
    x[:, upheld] = rng.integers(0, 2, n)
    x[:, five] = rng.integers(0, 2, n)
    x[:, single] = rng.integers(0, 2, n)
    # five judges and single judge both point the WRONG way in these labels; accident insurance the right way
    y = ((x[:, upheld] - x[:, five] + x[:, single] + rng.normal(scale=0.4, size=n)) > 0.5).astype(int)
    model = sc.Scorer.fit(x, y, n_core=n)
    weights = model.weights()
    assert set(weights) == set(sc.FEATURES)
    for name, rule in weights.items():
        assert rule["weight"] * sc.SIGNS[name] >= 0, name
    assert weights["five_judges"]["weight"] == 0 and weights["single_judge"]["weight"] == 0
    assert weights["area_uvmv"]["weight"] > 0.5
    row = [0.0] * len(sc.FEATURES)
    row[five] = 1.0
    assert model.contributions(row)["five_judges"] == 0  # so the explanation never cites it against the ruling


def test_signed_model_matches_plain_logistic_regression_when_no_bound_binds():
    """Same optimum as scikit-learn's L2 logistic regression (C = 1, balanced) when the signs agree with the data."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    x, y = toy_data()
    cols = [0, 2, 8]  # the three informative inputs, all expected positive
    signed = sc.SignedLogistic([1, 1, 1]).fit(x[:, cols], y)
    plain = LogisticRegression(C=1.0, class_weight="balanced", max_iter=3000).fit(
        StandardScaler().fit_transform(x[:, cols]), y
    )
    assert signed.coef_ == pytest.approx(plain.coef_[0], abs=2e-3)
    assert signed.intercept_ == pytest.approx(plain.intercept_[0], abs=2e-3)


def test_the_cut_promotes_forty_percent_of_the_core_rulings_by_score():
    scores = np.array([0.9, 0.1, 0.8, 0.2, 0.7, 0.3, 0.6, 0.4, 0.5, 0.05])
    core = np.array([True] * 5 + [False] * 5)  # five core rulings -> two promoted
    chosen = pl.promote(scores, core)
    assert chosen.sum() == 2 and list(np.where(chosen)[0]) == [0, 2]


def test_explanation_is_built_from_the_rules_that_apply():
    row = [1, 0, 1, 0, 0, 1, 0, 0, 0.9, 2, 0, 0, 0]
    contributions = dict(zip(sc.FEATURES, [0.8, 0, 0.9, 0, 0, -0.7, 0, 0, 0.4, 0.3, 0, 0, 0], strict=True))
    text = sc.explanation_de("suspected_relevant", contributions, row, n_readings=6)
    assert text.startswith("Vermutlich relevant.")
    assert "Beschwerde eines Versicherers oder einer Behörde" in text and "Unfall- oder Militärversicherung" in text
    assert "Dagegen: als offensichtlich unbegründet erledigt." in text
    assert "Kernthemen der Unfallversicherung im Text" in text
    assert "Fünferbesetzung" not in text  # a rule that does not apply is not cited
    assert "Keine Apertus-Lesung" in sc.explanation_de("possibly_relevant", contributions, row, n_readings=0)


# --- labels, layer 1 and the rows written -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("quarter", "basis", "expected"),
    [
        ("2025 Q4", "suva_xlsx", 1),
        ("2026 Q1", "complete_list_negative", 0),
        ("2026 Q2", "no_label", None),  # the quarter to predict
        ("2025 Q3", "gold_summary_only", None),  # no complete list for that quarter
        ("2026 Q1", "expert_override", None),  # a correction made in the UI is not Suva's list
    ],
)
def test_training_labels_come_only_from_suvas_list_in_the_listed_quarters(quarter, basis, expected):
    assert pl.label({"quarter": quarter, "basis": basis}) == expected


def test_prepare_runs_layer_one_and_reads_signals_only_for_kept_rulings():
    base = {"starred": False, "language": "de", "quarter": "2025 Q4", "basis": "complete_list_negative"}
    kept = pl.prepare(
        {**base, "docket": "8C_1/2025", "area": "Unfallversicherung", "subject": None, "text": RULING}, None
    )
    assert kept["kept"] is True and kept["core"] is True
    assert kept["signals"]["area"] == "UV" and kept["signals"]["suva_party"] is True
    assert kept["layer1"]["subject"] == "kept_subject" and "docket" not in kept["layer1"]
    dropped = pl.prepare(
        {**base, "docket": "2C_1/2025", "area": "Steuerrecht", "subject": None, "text": "Steuern."}, None
    )
    assert dropped["kept"] is False and "signals" not in dropped


class FakeConn:
    """Records statements; answers the INSERT ... RETURNING id of the run with id 7."""

    def __init__(self) -> None:
        self.statements: list[tuple[str, tuple]] = []

    def transaction(self):
        from contextlib import nullcontext

        return nullcontext()

    def execute(self, sql, params=()):
        self.statements.append((" ".join(sql.split()), params))
        return SimpleNamespace(fetchone=lambda: (7,))


def test_write_retires_earlier_predictions_and_stores_one_explained_row_per_kept_ruling():
    pytest.importorskip("psycopg")
    x, y = toy_data()
    model = sc.Scorer.fit(x, y, n_core=len(y))
    row = [1, 0, 1, 0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0]
    kept = [
        {
            "id": 11,
            "tier": "suspected_relevant",
            "score": 0.91,
            "x": row,
            "consensus": 1.0,
            "contributions": model.contributions(row),
            "layer1": {"subject": "kept_subject", "kept": True},
            "signals": {"area": "UV"},
            "readings": {"verdict": 0.9, "yes_strict": None},
        },
        {
            "id": 12,
            "tier": "possibly_relevant",
            "score": 0.08,
            "x": [0.0] * 13,
            "consensus": 0.0,
            "contributions": model.contributions([0.0] * 13),
            "layer1": {"subject": "kept_subject", "kept": True},
            "signals": {"area": "KV"},
        },
    ]
    result = {
        "summary": {"out_of_quarter": {"f2": 0.7}},
        "model": model,
        "consensus": sc.Consensus({"verdict": (0.0, 1.0)}),
        "kept": kept,
    }
    conn = FakeConn()
    run_id = pl.write(conn, result, [{"name": "apertus-v1-5-70b", "role": "readings"}])
    assert run_id == 7
    sql = [s for s, _ in conn.statements]
    assert (
        sql[0].startswith("INSERT INTO model_runs")
        and sql[1] == "UPDATE predictions SET is_current = false WHERE is_current"
    )
    inserts = [params for s, params in conn.statements if s.startswith("INSERT INTO predictions")]
    assert [(p[0], p[1], p[3]) for p in inserts] == [(11, 7, True), (12, 7, False)]
    assert inserts[0][2] == 0.91 and inserts[0][4].startswith("Vermutlich relevant.")
    assert "Keine Apertus-Lesung" in inserts[1][4]
    assert inserts[0][5].obj["tier"] == "suspected_relevant" and inserts[0][5].obj["apertus_readings"]["verdict"] == 0.9
    stored = conn.statements[0][1][1].obj  # the run's params: the whole rule table, so the score can be recomputed
    assert set(stored["rule_weights"]) == set(sc.FEATURES) and "intercept" in stored
    assert stored["rule_weights"]["single_judge"]["sign"] == -1
