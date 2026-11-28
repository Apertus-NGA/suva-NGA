"""Compare scoring variants of the triage classifier on the same kept rulings (experiment, not the pipeline).

A variant is a feature set and a model (logistic regression or XGBoost). Every variant is scored the same way,
on the kept rulings of the two listed quarters, with labels from Suva's list (closed world, Q-04):

- out of quarter: fit on one listed quarter, rank the other; ``primary`` is fit on 2025 Q4, test on 2026 Q1
  (new Apertus prompts are written on 2025 Q4 only); ``pooled`` adds the swapped direction, which is optimistic
  for any feature whose prompt was written on 2025 Q4;
- the list submitted in the test quarter is the top ``share`` x (its accident, military and disability rulings),
  as in ``pipeline.promote``; ``SHARES`` sweeps it;
- recall first: ``needed_95`` and ``needed_100`` are the shortest top-of-ranking lists that reach 95% and 100% of
  the test quarter's relevant rulings.

Pass rule, written before any variant was measured (28 Nov 2026): a variant beats the baseline only if, pooled,
it finds at least 2 more relevant rulings at share 0.40, finds no fewer at any share of ``SHARES``, and needs no
longer a list for 95% recall. Anything else is reported as "no gain".
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

SHARES = (0.30, 0.40, 0.50, 0.60, 0.70)
FOLDS = (("2025 Q4", "2026 Q1"), ("2026 Q1", "2025 Q4"))  # (train, test); the first is the primary direction


def f2(tp: int, fp: int, fn: int) -> float:
    return 5 * tp / (5 * tp + 4 * fn + fp) if tp else 0.0


def logistic() -> Any:
    """The unconstrained logistic regression of triage_pipeline@1 (the experiments' baseline). The pipeline's
    current scorer is sign-constrained and takes its own fixed inputs (``src.triage.scorer``)."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    return make_pipeline(StandardScaler(), LogisticRegression(C=1.0, class_weight="balanced", max_iter=3000))


def xgboost() -> Any:
    from xgboost import XGBClassifier

    # small and strongly regularised: about 60 positives per fit
    return XGBClassifier(
        n_estimators=200,
        max_depth=2,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=2,
        reg_lambda=1.0,
        random_state=0,
        n_jobs=1,
        eval_metric="logloss",
    )


@dataclass
class Variant:
    name: str
    columns: Sequence[str]
    model: Callable[[], Any]
    weighted: bool = False  # XGBoost: scale_pos_weight = negatives / positives


def needed(scores: np.ndarray, y: np.ndarray, target: float) -> int:
    """Length of the shortest top-of-ranking list that holds ``target`` of the relevant rulings."""
    want = int(np.ceil(target * int(y.sum())))
    if want == 0:
        return 0
    hits = np.cumsum(y[np.argsort(-scores, kind="stable")])
    return int(np.searchsorted(hits, want) + 1)


def fit_score(variant: Variant, x_train: np.ndarray, y_train: np.ndarray, x_test: np.ndarray) -> np.ndarray:
    model = variant.model()
    if variant.weighted:
        model.set_params(scale_pos_weight=float((y_train == 0).sum()) / max(int(y_train.sum()), 1))
    model.fit(x_train, y_train)
    return model.predict_proba(x_test)[:, 1]


def evaluate(variant: Variant, table: dict[str, np.ndarray]) -> dict[str, Any]:
    """``table``: column arrays plus ``y`` (0/1), ``quarter`` and ``core`` (accident, military or disability)."""
    x = np.column_stack([table[c] for c in variant.columns]).astype(float)
    y, quarter, core = table["y"].astype(int), table["quarter"], table["core"].astype(bool)
    per: dict[str, Any] = {}
    for train_q, test_q in FOLDS:
        train, test = quarter == train_q, quarter == test_q
        scores = fit_score(variant, x[train], y[train], x[test])
        yt, ct = y[test], core[test]
        order = np.argsort(-scores, kind="stable")
        at = {}
        for share in SHARES:
            n = max(1, int(round(share * int(ct.sum()))))
            found = int(yt[order[:n]].sum())
            at[f"{share:.2f}"] = {"submitted": n, "found": found}
        per[test_q] = {
            "_scores": scores,
            "_y": yt,
            "_core": ct,
            "relevant": int(yt.sum()),
            "at_share": at,
            "needed_95": needed(scores, yt, 0.95),
            "needed_100": needed(scores, yt, 1.0),
        }
    pooled = {}
    total = sum(p["relevant"] for p in per.values())
    for share in SHARES:
        key = f"{share:.2f}"
        tp = sum(p["at_share"][key]["found"] for p in per.values())
        sub = sum(p["at_share"][key]["submitted"] for p in per.values())
        pooled[key] = {
            "submitted": sub,
            "found": tp,
            "recall": round(tp / total, 3),
            "f2": round(f2(tp, sub - tp, total - tp), 3),
        }
    primary = {k: v for k, v in per[FOLDS[0][1]].items() if not k.startswith("_")}
    return {
        "_folds": {q: {k: per[q][k] for k in ("_scores", "_y", "_core")} for q in per},
        "mean_found": round(float(np.mean([pooled[k]["found"] for k in pooled])), 2),
        "mean_f2": round(float(np.mean([pooled[k]["f2"] for k in pooled])), 3),
        "variant": variant.name,
        "columns": list(variant.columns),
        "primary_test": FOLDS[0][1],
        "primary": primary,
        "pooled": pooled,
        "pooled_needed_95": sum(p["needed_95"] for p in per.values()),
        "pooled_needed_100": sum(p["needed_100"] for p in per.values()),
        "relevant_total": total,
    }


def beats(candidate: dict[str, Any], baseline: dict[str, Any]) -> bool:
    """The pass rule of the module docstring."""
    c, b = candidate["pooled"], baseline["pooled"]
    return (
        c["0.40"]["found"] >= b["0.40"]["found"] + 2
        and all(c[k]["found"] >= b[k]["found"] for k in b)
        and candidate["pooled_needed_95"] <= baseline["pooled_needed_95"]
    )


def _found(scores: np.ndarray, y: np.ndarray, core: np.ndarray, share: float) -> int:
    n = max(1, int(round(share * int(core.sum()))))
    return int(y[np.argsort(-scores, kind="stable")[:n]].sum())


def paired_bootstrap(
    candidate: dict[str, Any], baseline: dict[str, Any], share: float = 0.40, n_boot: int = 2000, seed: int = 0
) -> dict[str, float]:
    """Resample the test rulings of each quarter (the same draw for both variants) and count, pooled, how many
    more relevant rulings the candidate finds at ``share``. Returns the mean difference, its 95% interval and the
    share of draws in which the candidate finds more."""
    rng = np.random.default_rng(seed)
    diffs = np.zeros(n_boot)
    for q, fold in baseline["_folds"].items():
        other = candidate["_folds"][q]
        y, core, n = fold["_y"], fold["_core"], len(fold["_y"])
        for b in range(n_boot):
            idx = rng.integers(0, n, n)
            diffs[b] += _found(other["_scores"][idx], y[idx], core[idx], share) - _found(
                fold["_scores"][idx], y[idx], core[idx], share
            )
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return {
        "mean": round(float(diffs.mean()), 2),
        "low": float(lo),
        "high": float(hi),
        "p_better": round(float((diffs > 0).mean()), 3),
    }


def public(result: dict[str, Any]) -> dict[str, Any]:
    """The result without its per-ruling arrays (aggregates only, D-031)."""
    return {k: v for k, v in result.items() if not k.startswith("_")}


def repeated_cv(
    variants: Sequence[Variant], table: dict[str, np.ndarray], share: float = 0.40, repeats: int = 10
) -> dict[str, list[int]]:
    """A second protocol, as the research sprint used: stratified 5-fold over both listed quarters, repeated with
    new splits. For each repeat, the out-of-fold scores of each quarter are cut at ``share`` of its core rulings
    and the relevant rulings found are summed over the quarters. The folds are the same for every variant, so the
    lists are paired by repeat."""
    from sklearn.model_selection import StratifiedKFold

    y, quarter, core = table["y"].astype(int), table["quarter"], table["core"].astype(bool)
    out: dict[str, list[int]] = {v.name: [] for v in variants}
    for rep in range(repeats):
        folds = list(StratifiedKFold(5, shuffle=True, random_state=1000 + rep).split(np.zeros(len(y)), y))
        for v in variants:
            x = np.column_stack([table[c] for c in v.columns]).astype(float)
            oof = np.zeros(len(y))
            for train, test in folds:
                oof[test] = fit_score(v, x[train], y[train], x[test])
            out[v.name].append(
                sum(_found(oof[quarter == q], y[quarter == q], core[quarter == q], share) for q in np.unique(quarter))
            )
    return out
