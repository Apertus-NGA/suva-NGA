"""Arm L: a cut-off that needs no tuning: submit the top p% of candidates by score. Honest by construction (p fixed in advance)."""
import numpy as np, pandas as pd
from sklearn.model_selection import StratifiedKFold
from common import load, logreg, OUT, f2_counts
df = load().reset_index(drop=True)
ra = pd.read_parquet(OUT / "rubric_answers.parquet"); df = df.merge(ra[["id"] + [c for c in ra if c.startswith("q_")]], on="id", how="left")
m = pd.concat([pd.read_parquet(OUT / "more_answers_lab.parquet"), pd.read_parquet(OUT / "more_answers_q2.parquet")]); df = df.merge(m, on="id", how="left")
df["principle"] = (df.q_rule + df.q_new + (1 - df.q_factual) + (1 - df.q_routine)) / 4
P = ["q_rule", "q_new", "q_legalq", "q_headnote", "q_depth", "q_unusual", "q_corrects", "q_learn"]; N = ["q_factual", "q_routine", "q_stdonly"]
df["principle11"] = (df[P].sum(axis=1) + (1 - df[N]).sum(axis=1)) / 11
a = pd.read_parquet(OUT / "arm_a_strict_label.parquet"); df = df.merge(a[["id", "p_yes"]].rename(columns={"p_yes": "a70"}), on="id", how="left")
CORE = ["area_uvmv", "app_inst", "five", "star", "obv", "suva_party"]
M = {"A. structural 6": CORE, "C. + principle (4)": CORE + ["principle"], "D. + principle (11)": CORE + ["principle11"], "G. + principle (4) + 70B score": CORE + ["principle", "a70"], "70B score alone": ["a70"]}
S = df[df.labelled & df.cand].reset_index(drop=True); y = S.pos.values; rows = []
def top(s, yy, p):
    k = int(round(p * len(s))); idx = np.argsort(-s, kind="stable")[:k]; tp = int(yy[idx].sum()); return tp, k - tp
for name, f in M.items():
    X = S[f].values.astype(float)
    for p in (0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
        tp = fp = 0
        for a_, b_ in [("2025 Q4", "2026 Q1"), ("2026 Q1", "2025 Q4")]:
            tr, te = (S.q == a_).values, (S.q == b_).values
            t, f_ = top(logreg()().fit(X[tr], y[tr]).predict_proba(X[te])[:, 1], y[te], p); tp += t; fp += f_
        xq = (tp / 59, f2_counts(tp, fp, 59 - tp), tp + fp)
        R, F = [], []
        for rep in range(10):
            tp = fp = 0
            for tr, te in StratifiedKFold(5, shuffle=True, random_state=200 + rep).split(X, y):
                t, f_ = top(logreg()().fit(X[tr], y[tr]).predict_proba(X[te])[:, 1], y[te], p); tp += t; fp += f_
            R.append(tp / 59); F.append(f2_counts(tp, fp, 59 - tp))
        rows.append({"model": name, "top share": p, "submitted": xq[2], "recall xq": round(xq[0], 3), "F2 xq": round(xq[1], 3), "recall rcv": round(np.mean(R), 3), "F2 rcv": round(np.mean(F), 3),
                     "recall+F2 xq": round(xq[0] + xq[1], 3), "recall+F2 rcv": round(np.mean(R) + np.mean(F), 3)})
T = pd.DataFrame(rows); T.to_csv(OUT / "arm_l_topshare.csv", index=False)
print(T.pivot(index="top share", columns="model", values="recall rcv").round(2).to_string()); print()
print(T.pivot(index="top share", columns="model", values="recall xq").round(2).to_string()); print()
print(T.pivot(index="top share", columns="model", values="F2 rcv").round(3).to_string()); print()
print(T.pivot(index="top share", columns="model", values="F2 xq").round(3).to_string())
