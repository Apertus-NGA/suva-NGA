"""Triage steps 3b to 5: the Apertus consensus, the score, the cut and the explanation.

- consensus: the six readings, each standardised, averaged with equal weights. Nothing is fitted to labels.
- score: a sign-constrained logistic regression on twelve code-read facts and the consensus, trained on the
  kept rulings of the listed quarters (Suva's list as labels, closed world, Q-04). Each rule may move the score
  only in the direction a lawyer expects (``SIGNS``); a rule the labels do not support gets weight 0, it never
  turns against its meaning.
- cut: a score threshold frozen from out-of-fold scores of the listed quarters.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.optimize import minimize
from sklearn.model_selection import StratifiedKFold

VERSION = "scorer@2"
PROB_READINGS = frozenset({"verdict", "yes_strict"})  # probabilities, standardised on the log-odds scale
FEATURES = [
    "area_uvmv",
    "area_iv",
    "appeal_by_institution",
    "five_judges",
    "publication",
    "manifestly_unfounded",
    "suva_party",
    "single_judge",
    "consensus",
    "core_topics",
    "long_accident",
    "long_disability",
    "other_accident_insurer",
]
# The only direction each rule may move the score: +1 towards relevant, -1 away from it. Fixed before fitting.
SIGNS = {
    "area_uvmv": 1,
    "area_iv": 1,
    "appeal_by_institution": 1,
    "five_judges": 1,
    "publication": 1,
    "manifestly_unfounded": -1,
    "suva_party": 1,
    "single_judge": -1,
    "consensus": 1,
    "core_topics": 1,
    "long_accident": 1,
    "long_disability": -1,
    "other_accident_insurer": 1,
}
RULE_DE = {
    "area_uvmv": "Unfall- oder Militärversicherung",
    "area_iv": "Invalidenversicherung",
    "appeal_by_institution": "Beschwerde eines Versicherers oder einer Behörde",
    "five_judges": "Fünferbesetzung",
    "publication": "zur Publikation vorgesehen",
    "manifestly_unfounded": "als offensichtlich unbegründet erledigt",
    "suva_party": "Suva ist Partei",
    "single_judge": "Einzelrichterentscheid",
    "consensus": "Apertus-Lesungen: rechtliche Aussage über den Einzelfall hinaus",
    "core_topics": "Kernthemen der Unfallversicherung im Text",
    "long_accident": "ausführliches Urteil in der Unfall- oder Militärversicherung",
    "long_disability": "ausführliches Urteil in der Invalidenversicherung",
    "other_accident_insurer": "anderer Unfallversicherer ist Partei",
}
CORE_SHARE = 0.40  # share of the kept accident / military / disability rulings promoted to "suspected relevant"


def _transform(name: str, value: float) -> float:
    if name in PROB_READINGS:
        value = min(max(value, 1e-4), 1 - 1e-4)
        return math.log(value / (1 - value))
    return float(value)


@dataclass
class Consensus:
    """Standardisation of each reading, frozen from a reference population (no labels involved)."""

    stats: dict[str, tuple[float, float]] = field(default_factory=dict)

    @classmethod
    def fit(cls, readings: list[dict[str, float | None]]) -> Consensus:
        """Reference rulings are those with every reading. A reading with no spread is left out."""
        complete = [r for r in readings if r and all(v is not None for v in r.values())]
        stats: dict[str, tuple[float, float]] = {}
        for name in complete[0] if complete else []:
            values = np.array([_transform(name, r[name]) for r in complete])  # type: ignore[arg-type]
            if float(np.percentile(values, 90) - np.percentile(values, 10)) < 1e-3:
                continue  # says the same for every ruling: carries nothing
            stats[name] = (float(values.mean()), float(values.std()) + 1e-9)
        return cls(stats)

    def value(self, reading: dict[str, float | None] | None) -> float:
        """Average of the standardised readings; 0.0 (the reference average) when there is none."""
        if not reading:
            return 0.0
        scores = [
            (_transform(name, reading[name]) - mean) / spread  # type: ignore[arg-type]
            for name, (mean, spread) in self.stats.items()
            if reading.get(name) is not None
        ]
        return float(np.mean(scores)) if scores else 0.0


def features(signals: dict[str, Any], consensus: float) -> list[float]:
    """The model's inputs, in the order of ``FEATURES``."""
    area = signals.get("area")
    return [
        float(area in ("UV", "MV")),
        float(area == "IV"),
        float(bool(signals.get("appeal_by_institution"))),
        float(bool(signals.get("five_judges"))),
        float(signals.get("proposed_for_publication") is True),
        float(bool(signals.get("manifestly_unfounded"))),
        float(bool(signals.get("suva_party"))),
        float(bool(signals.get("single_judge"))),
        float(consensus),
        float(signals.get("core_topics") or 0),
        float(bool(signals.get("long_ruling")) and area in ("UV", "MV")),
        float(bool(signals.get("long_ruling")) and area == "IV"),
        float(bool(signals.get("other_accident_insurer"))),
    ]


class SignedLogistic:
    """Logistic regression (L2, C = 1, balanced classes, standardised inputs) whose weights are bounded to the
    sign given for each input. The problem stays convex: one optimum, found by L-BFGS-B."""

    def __init__(self, signs: list[int], c: float = 1.0):
        self.signs, self.c = list(signs), c

    def fit(self, x: np.ndarray, y: np.ndarray) -> SignedLogistic:
        x, y = np.asarray(x, float), np.asarray(y, float)
        self.mean_ = x.mean(axis=0)
        spread = x.std(axis=0)
        self.scale_ = np.where(spread > 0, spread, 1.0)
        z = (x - self.mean_) / self.scale_
        n, positive = len(y), float(y.sum())
        weight = np.where(y == 1, n / (2 * max(positive, 1.0)), n / (2 * max(n - positive, 1.0)))

        def loss(params: np.ndarray) -> tuple[float, np.ndarray]:
            w, b = params[:-1], params[-1]
            margin = z @ w + b
            residual = weight * (1 / (1 + np.exp(-margin)) - y)
            value = float((weight * (np.logaddexp(0, margin) - y * margin)).sum() + 0.5 / self.c * w @ w)
            return value, np.append(z.T @ residual + w / self.c, residual.sum())

        bounds = [(0, None) if s > 0 else (None, 0) if s < 0 else (None, None) for s in self.signs]
        result = minimize(loss, np.zeros(z.shape[1] + 1), jac=True, bounds=[*bounds, (None, None)], method="L-BFGS-B")
        self.coef_, self.intercept_ = result.x[:-1], float(result.x[-1])
        return self

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        margin = ((np.asarray(x, float) - self.mean_) / self.scale_) @ self.coef_ + self.intercept_
        p = 1 / (1 + np.exp(-margin))
        return np.column_stack([1 - p, p])


def _model() -> SignedLogistic:
    return SignedLogistic([SIGNS[name] for name in FEATURES])


def out_of_fold(x: np.ndarray, y: np.ndarray, repeats: int = 5) -> np.ndarray:
    """Average out-of-fold probability over repeated stratified 5-fold."""
    scores = np.zeros(len(y))
    for rep in range(repeats):
        for train, test in StratifiedKFold(5, shuffle=True, random_state=100 + rep).split(x, y):
            scores[test] += _model().fit(x[train], y[train]).predict_proba(x[test])[:, 1] / repeats
    return scores


@dataclass
class Scorer:
    model: Any
    threshold: float
    n_train: int
    n_positive: int

    @classmethod
    def fit(cls, x: np.ndarray, y: np.ndarray, n_core: int) -> Scorer:
        """Fit on every labelled row; freeze the threshold so that ``CORE_SHARE`` of the ``n_core`` core rulings
        (accident, military, disability) are promoted, measured on out-of-fold scores."""
        oof = out_of_fold(x, y)
        promoted = max(1, int(round(CORE_SHARE * n_core)))
        threshold = float(np.sort(oof)[::-1][min(promoted, len(oof)) - 1])
        return cls(_model().fit(x, y), threshold, len(y), int(y.sum()))

    def score(self, x: np.ndarray) -> np.ndarray:
        return self.model.predict_proba(x)[:, 1]

    def contributions(self, row: list[float]) -> dict[str, float]:
        """Each rule's push on the log-odds for one ruling, relative to an average ruling."""
        z = (np.array(row) - self.model.mean_) / self.model.scale_
        return {name: float(c) for name, c in zip(FEATURES, z * self.model.coef_, strict=True)}

    def weights(self) -> dict[str, dict[str, float]]:
        """The fitted rule table: for each input its allowed direction, its weight per standard deviation, and
        the average and spread it is standardised with. With the intercept this is the whole algorithm."""
        m = self.model
        return {
            name: {"sign": SIGNS[name], "weight": float(w), "mean": float(mu), "scale": float(sd)}
            for name, w, mu, sd in zip(FEATURES, m.coef_, m.mean_, m.scale_, strict=True)
        }


def explanation_de(tier: str, contributions: dict[str, float], row: list[float], n_readings: int) -> str:
    """One German sentence per ruling, built by code from the rules that apply (G1: no model-written facts)."""
    present = {name: value for name, value in zip(FEATURES, row, strict=True)}
    pro = [
        RULE_DE[n]
        for n, c in sorted(contributions.items(), key=lambda kv: -kv[1])
        if c > 0.15 and (present[n] or n == "consensus")
    ]
    contra = [
        RULE_DE[n]
        for n, c in sorted(contributions.items(), key=lambda kv: kv[1])
        if c < -0.15 and (present[n] or n == "consensus")
    ]
    head = "Vermutlich relevant" if tier == "suspected_relevant" else "Möglicherweise relevant"
    parts = [head + "."]
    if pro:
        parts.append("Dafür: " + "; ".join(pro[:4]) + ".")
    if contra:
        parts.append("Dagegen: " + "; ".join(contra[:3]) + ".")
    if not n_readings:
        parts.append("Keine Apertus-Lesung (ausserhalb der Kerngebiete oder Einzelrichterentscheid).")
    return " ".join(parts)
