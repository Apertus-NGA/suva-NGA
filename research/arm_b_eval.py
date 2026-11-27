"""Evaluate rubric answers. usage: arm_b_eval.py [answers parquet name] [quick]"""
import sys, numpy as np
from sklearn.metrics import roc_auc_score
from arm_b_lib import *
from common import evaluate, logreg, DET_FEATURES
name = sys.argv[1] if len(sys.argv) > 1 else "arm_b_rubric_lab.parquet"
quick = len(sys.argv) > 2
df = load(); a = pd.read_parquet(OUT / name)
Q = [q for q in QUESTIONS if q in a.columns]
d = df.merge(a[["id"] + Q], on="id", how="left")
C = d[d.labelled & d.cand & d[Q[0]].notna()]
print("answers for", len(C), "of 221 labelled candidates; missing values per q:", d[d.labelled & d.cand][Q].isna().sum().to_dict())
def auc(s, q):
    return roc_auc_score(s.pos, s[q]) if s.pos.nunique() == 2 else float("nan")
print("| question | Ja%% UV rel (n=%d) | UV non (n=%d) | Ja%% IV rel (n=%d) | IV non (n=%d) | AUC all | AUC UV | AUC IV |" % tuple(
    len(C[(C.cls == c) & (C.pos == p)]) for c in ["UV", "IV"] for p in [1, 0]))
print("|---|---|---|---|---|---|---|---|")
for q in Q:
    r = [100 * (C[(C.cls == c) & (C.pos == p)][q] > 0.5).mean() for c in ["UV", "IV"] for p in [1, 0]]
    print(f"| {q} | {r[0]:.0f} | {r[1]:.0f} | {r[2]:.0f} | {r[3]:.0f} | {auc(C,q):.3f} | {auc(C[C.cls=='UV'],q):.3f} | {auc(C[C.cls=='IV'],q):.3f} |")
for q in Q: d[q] = d[q].fillna(0.5)
d["cand2"] = d.cand
res = []
res.append(evaluate(d, DET_FEATURES, logreg(), "cand", "(a) DET"))
res.append(evaluate(d, DET_FEATURES + Q, logreg(), "cand", "(b) DET + all questions"))
res.append(evaluate(d, Q, logreg(), "cand", "(d) questions only"))
if not quick:
    for q in Q:
        res.append(evaluate(d, DET_FEATURES + [q], logreg(), "cand", f"(c) DET + {q}"))
    # interaction: IV x question (questions matter most for IV)
    for q in ["q_transfer", "q_newsletter", "q_rule"]:
        if q in Q: d["iv_" + q] = d[q] * d.area_iv
    best = [q for q in ["q_newsletter", "q_rule", "q_new", "q_uvcore"] if q in Q]
    res.append(evaluate(d, DET_FEATURES + best, logreg(), "cand", "(e) DET + " + "+".join(best)))
    res.append(evaluate(d, DET_FEATURES + Q + [c for c in d.columns if c.startswith("iv_q_")], logreg(), "cand", "(f) DET + all + IVxq"))
    res.append(evaluate(d, DET_FEATURES + Q, logreg(0.1), "cand", "(g) DET + all, C=0.1"))
pd.DataFrame(res).to_csv(OUT / ("arm_b_eval_" + name.replace(".parquet", ".csv")), index=False)
# ---- two-track (lead's helper): all UV/MV submitted, model decides IV only
from two_track import two_track
IVF = ["app_inst", "five", "star", "obv"]
tt = [two_track(d, IVF, logreg(), "TT structural 4")]
tt.append(two_track(d, IVF + Q, logreg(), "TT structural + all questions"))
tt.append(two_track(d, Q, logreg(), "TT questions only"))
if not quick:
    for q in Q:
        tt.append(two_track(d, IVF + [q], logreg(), f"TT structural + {q}"))
    ivC = C[C.cls == "IV"]
    top = sorted(Q, key=lambda q: -abs(auc(ivC, q) - 0.5))[:3]
    print("top-3 by IV AUC (chosen on all labelled IV: optimistic):", top)
    tt.append(two_track(d, IVF + top, logreg(), "TT structural + top3-by-IV-AUC (optimistic)"))
    for sub in (["q_rule", "q_new"], ["q_rule", "q_new", "q_insurer_lost"], ["q_newsletter", "q_rule", "q_new", "q_practice"]):
        tt.append(two_track(d, IVF + sub, logreg(), "TT structural + " + "+".join(s[2:] for s in sub)))
pd.DataFrame(tt).to_csv(OUT / ("arm_b_tt_" + name.replace(".parquet", ".csv")), index=False)
