"""Arm I: final candidates, honest operating points (best-F2 vs recall-first), 0-100 points score, Q2 predictions."""
import json, sys
import numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from common import load, evaluate, logreg, DET_FEATURES, OUT, _oof, best_threshold, prf, f2_counts
from evalx import held_out, curve, policy_eval

df = load().reset_index(drop=True)
ra = pd.read_parquet(OUT / "rubric_answers.parquet"); Q = [c for c in ra.columns if c.startswith("q_")]
df = df.merge(ra[["id"] + Q], on="id", how="left")
df["principle"] = (df.q_rule + df.q_new + (1 - df.q_factual) + (1 - df.q_routine)) / 4
MORE = []
if (OUT / "more_answers_lab.parquet").exists():
    parts = [pd.read_parquet(OUT / "more_answers_lab.parquet")]
    if (OUT / "more_answers_q2.parquet").exists(): parts.append(pd.read_parquet(OUT / "more_answers_q2.parquet"))
    m = pd.concat(parts); MORE = [c for c in m.columns if c.startswith("q_")]; df = df.merge(m, on="id", how="left")
    L = df[df.labelled & df.cand]
    print("new questions, AUC inside UV / inside IV / mean P(Ja):")
    for c in MORE + ["q_rule", "q_new", "q_factual", "q_routine"]:
        print(f"  {c:12s} {roc_auc_score(L[L.area_uvmv==1].pos, L[L.area_uvmv==1][c]):.3f} / {roc_auc_score(L[L.area_iv==1].pos, L[L.area_iv==1][c]):.3f} / {L[c].mean():.2f}")
    # signs fixed by meaning: + rule,new,legalq,headnote,depth,unusual,corrects,learn ; - factual,routine,stdonly
    P = ["q_rule", "q_new", "q_legalq", "q_headnote", "q_depth", "q_unusual", "q_corrects", "q_learn"]; N = ["q_factual", "q_routine", "q_stdonly"]
    df["principle11"] = (df[P].sum(axis=1) + (1 - df[N]).sum(axis=1)) / (len(P) + len(N))
CORE = ["area_uvmv", "app_inst", "five", "star", "obv", "suva_party"]
CANDS = {"A. structural 6": CORE, "B. structural 11": DET_FEATURES, "C. structural 6 + principle (4 Apertus answers)": CORE + ["principle"]}
if MORE: CANDS["D. structural 6 + principle (11 Apertus answers)"] = CORE + ["principle11"]
if MORE and (OUT / "category.parquet").exists():
    cat = pd.read_parquet(OUT / "category.parquet"); cat["cat_subst"] = cat.cat_A + cat.cat_B + cat.cat_C
    df = df.merge(cat[["id", "cat_subst", "cat_D", "cat"]], on="id", how="left")
    df["principle12"] = (df[P].sum(axis=1) + (1 - df[N]).sum(axis=1) + df.cat_subst) / 12
    CANDS["E. structural 6 + principle (11 answers + category)"] = CORE + ["principle12"]
    CANDS["F. structural 6 + principle11 + category"] = CORE + ["principle11", "cat_subst"]
L = df[df.labelled & df.cand]
for c in ["principle"] + (["principle11"] if MORE else []) + (["principle12", "cat_subst"] if "principle12" in df else []):
    print(c, "AUC UV", round(roc_auc_score(L[L.area_uvmv==1].pos, L[L.area_uvmv==1][c]), 3), "IV", round(roc_auc_score(L[L.area_iv==1].pos, L[L.area_iv==1][c]), 3))
rows = []
for name, feats in CANDS.items():
    r = evaluate(df, feats, logreg(), "cand", name)
    h = held_out(df, feats, logreg()); c1, c2 = curve(h, "s_xq"), curve(h, "s_rcv")
    pol = policy_eval(df, feats, logreg(), policies=("f2", "r90", "r95", "r100"))
    for p, v in pol.items():
        rows.append({"model": name, "policy": p, **v, "xq_sum": round(v["xq_recall"] + v["xq_f2"], 3), "rcv_sum": round(v["rcv_recall"] + v["rcv_f2"], 3)})
    print("   ideal-cut curve, submissions needed for recall .85/.90/.95/1.0: xq", [int(c1[k]["kept"]) for k in (.85, .9, .95, 1.0)], "F2", [c1[k]["f2"] for k in (.85, .9, .95, 1.0)], "| rcv", [int(c2[k]["kept"]) for k in (.85, .9, .95, 1.0)], "F2", [c2[k]["f2"] for k in (.85, .9, .95, 1.0)])
T = pd.DataFrame(rows); T.to_csv(OUT / "arm_i_operating_points.csv", index=False)
print("\nHonest operating points (threshold chosen on training folds only):"); print(T.to_string(index=False))
print("\nreference: submit all 221 candidates -> recall 1.00, F2 0.646, sum 1.646 | all UV/MV -> recall 0.73, F2 0.703, sum 1.432")

# ---------------- points score and Q2 predictions for each candidate
best = [k for k in CANDS if k.startswith(sys.argv[1])][0] if len(sys.argv) > 1 else list(CANDS)[0]
TAG = best[0]
feats = CANDS[best]; S = df[df.labelled & df.cand]; X, y = S[feats].values.astype(float), S.pos.values
lr = LogisticRegression(C=1.0, class_weight="balanced", max_iter=2000).fit(X, y)   # unscaled so weights read per rule
w, b = lr.coef_[0], lr.intercept_[0]
lo = b + sum(min(0, wi) * 1 for wi in w); hi = b + sum(max(0, wi) * 1 for wi in w)
pts = 100 * w / (hi - lo); base = 100 * (b - lo) / (hi - lo)
print(f"\nPOINTS SCORE for '{best}' (0-100; base {base:.0f} points)"); P = pd.DataFrame({"rule": feats, "points": pts.round(1), "log_odds": w.round(2)}); print(P.to_string(index=False))
P.to_csv(OUT / f"arm_i_points_{TAG}.csv", index=False)
def score(D): return np.clip(100 * (D[feats].values.astype(float) @ w + b - lo) / (hi - lo), 0, 100)
oof = np.zeros(len(y))
from sklearn.model_selection import StratifiedKFold
for rep in range(5):
    for tr, te in StratifiedKFold(5, shuffle=True, random_state=rep).split(X, y):
        m = LogisticRegression(C=1.0, class_weight="balanced", max_iter=2000).fit(X[tr], y[tr]); oof[te] += (100 * (X[te] @ m.coef_[0] + m.intercept_[0] - lo) / (hi - lo)) / 5
cuts = {"best F2": best_threshold(oof, y)}
for nm, lv in (("recall 90%", .90), ("recall 95%", .95), ("recall 100%", 1.0)):
    cuts[nm] = np.sort(oof[y == 1])[::-1][int(np.ceil(lv * y.sum())) - 1]
Q2 = df[(df.q == "2026 Q2") & df.cand].copy()
miss = Q2[feats].isna().any(axis=1).sum(); Q2[feats] = Q2[feats].fillna(S[feats].median())
Q2["score"] = score(Q2).round(1); S = S.assign(score=score(S).round(1), oof_score=oof.round(1))
print(f"\nQ2 candidates: {len(Q2)} (rows with a missing feature filled by the median: {miss}); June: {(Q2.decision_date.astype(str) >= '2026-06-01').sum()}")
for nm, c in cuts.items():
    r = prf(oof >= c, y); print(f"  cut '{nm}': score >= {c:5.1f} | labelled out-of-fold: recall {r['recall']:.2f} F2 {r['f2']:.3f} kept {r['kept']:3d} of 221 | Q2 submitted: {(Q2.score >= c).sum()} of {len(Q2)}")
    Q2["submit_" + nm.replace(" ", "_").replace("%", "")] = (Q2.score >= c).astype(int)
Q2.sort_values("score", ascending=False)[["docket", "decision_date", "cls", "language", "score", "subject"] + feats + [c for c in Q2 if c.startswith("submit_")]].to_csv(OUT / f"q2_predictions_{TAG}.csv", index=False)
S.sort_values("oof_score", ascending=False)[["docket", "decision_date", "cls", "pos", "score", "oof_score", "subject"] + feats].to_csv(OUT / f"labelled_scores_{TAG}.csv", index=False)
json.dump({"model": best, "features": feats, "cuts": {k: float(v) for k, v in cuts.items()}, "base_points": float(base)}, open(OUT / f"arm_i_final_{TAG}.json", "w"), indent=1)
print("\nTop 8 June 2026 rulings by score:"); print(Q2[Q2.decision_date.astype(str) >= "2026-06-01"].sort_values("score", ascending=False)[["docket", "cls", "score", "subject"]].head(8).to_string(index=False))
