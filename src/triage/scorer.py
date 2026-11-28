"""Triage steps 3b to 5: the Apertus consensus, the score, the cut and the explanation.

- consensus: the six readings, each standardised, averaged with equal weights. Nothing is fitted to labels.
- score: logistic regression on eight code-read facts and the consensus, trained on the kept rulings of the
  listed quarters (Suva's list as labels, closed world, Q-04).
- cut: a score threshold frozen from out-of-fold scores of the listed quarters.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

VERSION = "scorer@1"
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
]
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
    ]


def _model() -> Any:
    return make_pipeline(StandardScaler(), LogisticRegression(C=1.0, class_weight="balanced", max_iter=3000))


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
        scaler, lr = self.model[0], self.model[-1]
        z = (np.array(row) - scaler.mean_) / scaler.scale_
        return {name: float(c) for name, c in zip(FEATURES, z * lr.coef_[0], strict=True)}


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
