"""Arm D: classical models on deterministic features. Model type, feature set, training scope, ablation, text baseline."""
import json, sys
import numpy as np, pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier, HistGradientBoostingClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler
from common import load, evaluate, logreg, DET_FEATURES, DET_EXTRA, RUBRIC_ORIG, OUT

df = load(); df["_all"] = True
rows = []
def run(name, feats, mk, scope="cand", **kw):
    r = evaluate(df, feats, mk, scope, name, **kw); rows.append(r); return r

print("== 1. model type (11 deterministic features, candidates)")
run("logreg C=1 balanced", DET_FEATURES, logreg(1.0))
run("logreg C=0.1 balanced", DET_FEATURES, logreg(0.1))
run("logreg C=10 balanced", DET_FEATURES, logreg(10))
run("logreg L1 C=0.5", DET_FEATURES, lambda: make_pipeline(StandardScaler(), LogisticRegression(C=0.5, penalty="l1", solver="liblinear", class_weight="balanced")))
run("gradient boosting depth2 n100", DET_FEATURES, lambda: GradientBoostingClassifier(max_depth=2, n_estimators=100, learning_rate=0.05, subsample=0.8, random_state=0))
run("gradient boosting depth3 n200", DET_FEATURES, lambda: GradientBoostingClassifier(max_depth=3, n_estimators=200, learning_rate=0.05, subsample=0.8, random_state=0))
run("hist gradient boosting", DET_FEATURES, lambda: HistGradientBoostingClassifier(max_depth=3, max_iter=100, learning_rate=0.05, class_weight="balanced", random_state=0))
run("random forest 500 leaf5", DET_FEATURES, lambda: RandomForestClassifier(500, min_samples_leaf=5, class_weight="balanced", random_state=0, n_jobs=-1))

print("\n== 2. feature set (logreg, candidates)")
run("original Suva rubric (9)", RUBRIC_ORIG, logreg())
run("deterministic 11", DET_FEATURES, logreg())
run("deterministic 11 + 9 extras", DET_FEATURES + DET_EXTRA, logreg())
df["uv_x_app"] = df.area_uvmv * df.app_inst; df["iv_x_app"] = df.area_iv * df.app_inst
df["iv_x_obv"] = df.area_iv * df.obv; df["iv_x_five"] = df.area_iv * df.five; df["uv_x_topics"] = df.area_uvmv * df.uv_topics
INTER = ["uv_x_app", "iv_x_app", "iv_x_obv", "iv_x_five", "uv_x_topics"]
run("deterministic 11 + area interactions", DET_FEATURES + INTER, logreg())
run("gb depth2 on 11 + extras", DET_FEATURES + DET_EXTRA, lambda: GradientBoostingClassifier(max_depth=2, n_estimators=100, learning_rate=0.05, subsample=0.8, random_state=0))

print("\n== 3. training scope (logreg 11; single+area flags do the gating when trained wider)")
for sc in ["cand", "g_area", "g_div", "_all"]:
    run(f"logreg 11, scope={sc}", DET_FEATURES, logreg(), sc)
for sc in ["cand", "g_div", "_all"]:
    run(f"gb depth2, scope={sc}", DET_FEATURES, lambda: GradientBoostingClassifier(max_depth=2, n_estimators=100, learning_rate=0.05, subsample=0.8, random_state=0), sc, repeats=2)

print("\n== 4. ablation on candidates (logreg): drop one / add one")
base = evaluate(df, DET_FEATURES, logreg(), "cand", "base", verbose=False)
abl = []
for f in DET_FEATURES:
    r = evaluate(df, [x for x in DET_FEATURES if x != f], logreg(), "cand", f"drop {f}", verbose=False)
    abl.append(("drop", f, r["xq_f2"] - base["xq_f2"], r["rcv_f2"] - base["rcv_f2"], r["ap"] - base["ap"]))
for f in DET_EXTRA + INTER:
    r = evaluate(df, DET_FEATURES + [f], logreg(), "cand", f"add {f}", verbose=False)
    abl.append(("add", f, r["xq_f2"] - base["xq_f2"], r["rcv_f2"] - base["rcv_f2"], r["ap"] - base["ap"]))
A = pd.DataFrame(abl, columns=["op", "feature", "d_xq_f2", "d_rcv_f2", "d_ap"]).round(3); print(A.to_string(index=False))
A.to_csv(OUT / "arm_d_ablation.csv", index=False)

print("\n== 5. text baseline: TF-IDF on reasoning (fit inside each fold)")
df = df.reset_index(drop=True); df["_row"] = np.arange(len(df)); TXT = df.reasoning.values
def tfidf_model(C=1.0):
    return lambda: make_pipeline(FunctionTransformer(lambda X: TXT[X[:, 0].astype(int)]),
                                 TfidfVectorizer(max_features=20000, ngram_range=(1, 2), min_df=3, sublinear_tf=True),
                                 LogisticRegression(C=C, class_weight="balanced", max_iter=2000))
run("tfidf(reasoning) logreg", ["_row"], tfidf_model(1.0), repeats=2)
run("tfidf(reasoning) logreg C=10", ["_row"], tfidf_model(10.0), repeats=2)

print("\n== 6. fitted weights (logreg 11, all labelled candidates) as points")
S = df[df.labelled & df.cand]; m = logreg()().fit(S[DET_FEATURES].values.astype(float), S.pos.values)
lr = m.named_steps["logisticregression"]; sc = m.named_steps["standardscaler"]
raw = lr.coef_[0] / sc.scale_
W = pd.DataFrame({"feature": DET_FEATURES, "log_odds_per_unit": raw.round(2), "fires": [int((S[f] > 0).sum()) for f in DET_FEATURES],
                  "rate_if_fires": [round(S[S[f] > 0].pos.mean(), 2) if (S[f] > 0).any() else None for f in DET_FEATURES]})
print(W.to_string(index=False)); W.to_csv(OUT / "arm_d_weights.csv", index=False)
R = pd.DataFrame(rows); R.to_csv(OUT / "arm_d_results.csv", index=False)
print("\nTOP by repeated-CV F2:"); print(R.sort_values("rcv_f2", ascending=False)[["name", "scope", "n_feat", "xq_f2", "xq_recall", "xq_precision", "xq_kept", "rcv_f2", "rcv_f2_sd", "ap"]].head(12).round(3).to_string(index=False))
