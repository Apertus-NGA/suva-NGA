# ruff: noqa: E501  (feature-set names and the printed table are kept on one line each)
"""Arm P, step 3: choose the classifier. Feature sets x model families, hyperparameters tuned by nested CV.

For every feature set and model family:
- inner loop (4-fold, on the training part only) picks the hyperparameters by average precision;
- outer loop reports what that tuned model finds on rulings it never saw: (a) out of quarter, fit on one
  listed quarter and rank the other, both directions pooled; (b) 5 repeats of stratified 5-fold over both.
The list is the top ``share`` x (the test part's accident / military / disability rulings), as the pipeline cuts.

Feature sets separate what the harness adds: the same Apertus questions asked with no evidence ("before")
and with a consideration to name ("after"). No gateway call. Output: aggregates only (D-031).

Run: uv run --frozen python research/arm_p_sweep.py [--out results/triage_model_sweep.json]
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GridSearchCV, StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research"))

import arm_o_variants as ao  # noqa: E402
import arm_p_compare as cmp  # noqa: E402

from src.triage import variants as vr  # noqa: E402

SHARES = (0.30, 0.40, 0.50)
BASE = ao.FACTS + ["consensus"]
CLAIMS = ("practice", "legal_error", "transfer")


def feature_sets(size: str) -> dict[str, list[str]]:
    before = [f"l_{c}_zero_{size}" for c in CLAIMS]
    after = [f"l_{c}_cited_{size}" for c in CLAIMS]
    return {
        "8 facts (no Apertus)": ao.FACTS,
        "current: 8 facts + consensus": BASE,
        f"+ before: 3 zero-shot readings ({size})": BASE + before,
        f"+ after: 3 cited readings ({size})": BASE + after,
        f"+ after: practice, legal error cited ({size})": BASE + after[:2],
        f"+ after: legal error cited ({size})": BASE + after[1:2],
        f"+ after: legal error located + check ({size})": BASE + [f"l_legal_error_located_{size}", f"chk_legal_error_located_{size}"],
        f"+ after: cited readings + statement ({size})": BASE + after[:2] + [f"f_stmt_p_{size}_logit"],
        f"+ statement with evidence ({size})": BASE + [f"f_stmt_p_{size}_logit"],
        f"8 facts + after: cited readings + statement, no consensus ({size})": ao.FACTS + after[:2] + [f"f_stmt_p_{size}_logit"],
    }


def families() -> dict[str, tuple[object, dict]]:
    lr = make_pipeline(StandardScaler(), LogisticRegression(class_weight="balanced", max_iter=2000, solver="liblinear"))
    grid = {"logisticregression__C": [0.003, 0.01, 0.03, 0.1, 0.3, 1.0, 3.0], "logisticregression__penalty": ["l1", "l2"]}
    xgb = XGBClassifier(subsample=0.8, colsample_bytree=0.8, random_state=0, n_jobs=1, eval_metric="logloss")
    xgrid = {"n_estimators": [100, 300], "max_depth": [1, 2, 3], "learning_rate": [0.03, 0.1], "min_child_weight": [1, 3]}
    return {"logistic regression": (lr, grid), "xgboost": (xgb, xgrid)}


def tuned(estimator: object, grid: dict, x: np.ndarray, y: np.ndarray, seed: int) -> GridSearchCV:
    inner = StratifiedKFold(4, shuffle=True, random_state=seed)
    return GridSearchCV(estimator, grid, scoring="average_precision", cv=inner, n_jobs=-1).fit(x, y)


def found_at(scores: np.ndarray, y: np.ndarray, core: np.ndarray) -> dict[str, int]:
    order = np.argsort(-scores, kind="stable")
    out = {f"{s:.2f}": int(y[order[: max(1, int(round(s * int(core.sum()))))]].sum()) for s in SHARES}
    out["n40"] = max(1, int(round(0.40 * int(core.sum()))))
    out["need95"], out["need100"] = vr.needed(scores, y, 0.95), vr.needed(scores, y, 1.0)
    return out


def run(x: np.ndarray, y: np.ndarray, quarter: np.ndarray, core: np.ndarray, est: object, grid: dict, repeats: int) -> dict:
    total = int(y.sum())
    parts, chosen = [], Counter()
    for train_q, test_q in vr.FOLDS:  # out of quarter
        tr, te = quarter == train_q, quarter == test_q
        search = tuned(est, grid, x[tr], y[tr], 0)
        chosen[json.dumps(search.best_params_, sort_keys=True)] += 1
        parts.append((test_q, found_at(search.predict_proba(x[te])[:, 1], y[te], core[te])))
    ooq = {k: sum(p[k] for _, p in parts) for k in parts[0][1]}
    submitted = ooq.pop("n40")
    ooq["f2_40"] = round(5 * ooq["0.40"] / (4 * total + submitted), 3)
    ooq["q1_40"] = dict(parts)[vr.FOLDS[0][1]]["0.40"]
    cv = []
    for rep in range(repeats):
        sums: Counter = Counter()
        for tr, te in StratifiedKFold(5, shuffle=True, random_state=rep).split(x, y):
            search = tuned(est, grid, x[tr], y[tr], rep)
            chosen[json.dumps(search.best_params_, sort_keys=True)] += 1
            sums.update(found_at(search.predict_proba(x[te])[:, 1], y[te], core[te]))
        cv.append(dict(sums))
    return {
        "out_of_quarter": ooq,
        "cv_found_40": [c["0.40"] for c in cv],
        "cv_mean": {k: round(float(np.mean([c[k] for c in cv])), 2) for k in ("0.30", "0.40", "0.50", "need95", "need100")},
        "chosen": chosen.most_common(3),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "research" / "out" / "arm_p_sweep.json"))
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--sizes", nargs="*", default=["small", "large"])
    args = ap.parse_args(argv)
    warnings.filterwarnings("ignore")
    df, added = cmp.build()
    core = df.core.astype(bool).to_numpy()
    num = df.select_dtypes("number").columns
    df[num] = df[num].fillna(df.loc[core, num].mean()).fillna(0.0)  # not asked: the average of those asked
    y, quarter = df.y.to_numpy().astype(int), df.quarter.to_numpy()
    sets: dict[str, list[str]] = {}
    for size in args.sizes:
        sets.update(feature_sets(size))
    results = []
    print(f"{'features':66s} {'model':20s} OOQ found@30/40/50  F2@40 need95/100 Q1 | CV found@30/40/50 need95/100")
    for fam, (est, grid) in families().items():
        for name, cols in sets.items():
            if any(c not in df for c in cols):
                continue
            r = run(df[cols].to_numpy(float), y, quarter, core, est, grid, args.repeats)
            results.append({"features": name, "columns": cols, "model": fam, **r})
            o, c = r["out_of_quarter"], r["cv_mean"]
            print(
                f"{name:66s} {fam:20s} {o['0.30']:3d}/{o['0.40']}/{o['0.50']}        {o['f2_40']:.3f} "
                f"{o['need95']:4d}/{o['need100']:<4d} {o['q1_40']:2d} | {c['0.30']:.1f}/{c['0.40']:.1f}/{c['0.50']:.1f} "
                f"{c['need95']:.0f}/{c['need100']:.0f}",
                flush=True,
            )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({"relevant": int(y.sum()), "kept": int(len(y)), "results": results}, indent=1))
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
