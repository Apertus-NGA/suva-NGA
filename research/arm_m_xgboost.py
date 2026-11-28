"""Arm M: real XGBoost, same protocol as every other model."""
import numpy as np, pandas as pd
from xgboost import XGBClassifier
from sklearn.model_selection import StratifiedKFold
from common import load, evaluate, logreg, DET_FEATURES, DET_EXTRA, OUT, f2_counts
df = load().reset_index(drop=True); df["_all"] = True
ra = pd.read_parquet(OUT / "rubric_answers.parquet"); Q = [c for c in ra if c.startswith("q_")]; df = df.merge(ra[["id"] + Q], on="id", how="left")
df["principle"] = (df.q_rule + df.q_new + (1 - df.q_factual) + (1 - df.q_routine)) / 4
CORE = ["area_uvmv", "app_inst", "five", "star", "obv", "suva_party"]
def xgb(depth=2, n=100, lr=0.05, spw=None, **kw):
    return lambda: XGBClassifier(max_depth=depth, n_estimators=n, learning_rate=lr, subsample=0.8, colsample_bytree=0.8, min_child_weight=kw.pop("mcw", 2),
                                 reg_lambda=kw.pop("lam", 1.0), scale_pos_weight=spw or 1.0, random_state=0, n_jobs=4, verbosity=0, eval_metric="logloss", **kw)
rows = []
def run(name, feats, mk, scope="cand", repeats=5):
    r = evaluate(df, feats, mk, scope, name, repeats=repeats); rows.append(r)
print("== reference"); run("logistic regression, structural 6", CORE, logreg())
print("== XGBoost on gated candidates")
run("xgb depth1 n100 (stumps), structural 6", CORE, xgb(1, 100))
run("xgb depth2 n100, structural 6", CORE, xgb(2, 100))
run("xgb depth2 n100 weighted, structural 6", CORE, xgb(2, 100, spw=2.7))
run("xgb depth2 n100, structural 11", DET_FEATURES, xgb(2, 100))
run("xgb depth3 n300, structural 11", DET_FEATURES, xgb(3, 300))
run("xgb depth2 n100, 11 + 9 extras", DET_FEATURES + DET_EXTRA, xgb(2, 100))
run("xgb depth2 n100 strong reg, 11 + 9 extras", DET_FEATURES + DET_EXTRA, xgb(2, 100, lam=10, mcw=5))
run("xgb depth2 n100, structural 6 + principle", CORE + ["principle"], xgb(2, 100))
run("xgb depth2 n100, structural 6 + 9 Apertus answers", CORE + Q, xgb(2, 100))
run("xgb depth2 n100, 11 + extras + 9 Apertus answers", DET_FEATURES + DET_EXTRA + Q, xgb(2, 100, lam=5, mcw=3))
print("== XGBoost, wider training sets (structural 11; Apertus answers exist only for candidates)")
run("xgb depth2 n100 weighted, all 8C/9C", DET_FEATURES, xgb(2, 100, spw=10), "g_div", 2)
run("xgb depth2 n150 weighted, all 3,936 rulings", DET_FEATURES, xgb(2, 150, spw=60), "_all", 2)
run("xgb depth2 n150 unweighted, all 3,936 rulings", DET_FEATURES, xgb(2, 150), "_all", 2)
R = pd.DataFrame(rows); R.to_csv(OUT / "arm_m_xgboost.csv", index=False)
# tuning-free top-share comparison on candidates
S = df[df.labelled & df.cand].reset_index(drop=True); y = S.pos.values
def top(s, yy, p):
    k = int(round(p * len(s))); idx = np.argsort(-s, kind="stable")[:k]; tp = int(yy[idx].sum()); return tp, k - tp
out = []
for name, feats, mk in [("logistic, structural 6", CORE, logreg()), ("logistic, 6 + principle", CORE + ["principle"], logreg()), ("xgb d2, structural 6", CORE, xgb(2, 100)),
                        ("xgb d2, 6 + principle", CORE + ["principle"], xgb(2, 100)), ("xgb d2, 6 + 9 answers", CORE + Q, xgb(2, 100))]:
    X = S[feats].values.astype(float)
    for p in (0.4, 0.6, 0.9):
        Rr, F = [], []
        for rep in range(5):
            tp = fp = 0
            for tr, te in StratifiedKFold(5, shuffle=True, random_state=200 + rep).split(X, y):
                t, f = top(mk().fit(X[tr], y[tr]).predict_proba(X[te])[:, 1], y[te], p); tp += t; fp += f
            Rr.append(tp / 59); F.append(f2_counts(tp, fp, 59 - tp))
        tp = fp = 0
        for a, b in [("2025 Q4", "2026 Q1"), ("2026 Q1", "2025 Q4")]:
            tr, te = (S.q == a).values, (S.q == b).values; t, f = top(mk().fit(X[tr], y[tr]).predict_proba(X[te])[:, 1], y[te], p); tp += t; fp += f
        out.append({"model": name, "top share": p, "recall xq": round(tp / 59, 3), "F2 xq": round(f2_counts(tp, fp, 59 - tp), 3), "recall rcv": round(np.mean(Rr), 3), "F2 rcv": round(np.mean(F), 3)})
T = pd.DataFrame(out); T.to_csv(OUT / "arm_m_xgboost_topshare.csv", index=False); print("\ntop-share cut-offs:"); print(T.to_string(index=False))
m = xgb(2, 100)().fit(S[CORE + Q].values.astype(float), y); print("\nxgb gain importance (6 + 9 answers):", dict(sorted(zip(CORE + Q, m.feature_importances_.round(3)), key=lambda kv: -kv[1])))
