"""Extra: logit-transformed P(Ja) (saturated questions), small sets; within-IV / within-UV AUC of logit features."""
import numpy as np
from sklearn.metrics import roc_auc_score
from arm_b_lib import *
from common import evaluate, logreg, DET_FEATURES
from two_track import two_track
df = load(); a = pd.read_parquet(OUT / "arm_b_rubric_lab.parquet"); Q = list(QUESTIONS)
d = df.merge(a[["id"] + Q], on="id", how="left")
for q in Q:
    p = d[q].fillna(0.5).clip(1e-4, 1 - 1e-4); d["l_" + q] = np.log(p / (1 - p))
LQ = ["l_" + q for q in Q]
C = d[d.labelled & d.cand]
for q in ["q_transfer", "q_newsletter", "q_practice"]:
    print(q, "P(Ja) quantiles 5/25/50/75/95:", np.round(C[q].quantile([.05, .25, .5, .75, .95]).values, 3))
evaluate(d, DET_FEATURES + LQ, logreg(), "cand", "DET + all (logit)")
evaluate(d, DET_FEATURES + LQ, logreg(0.05), "cand", "DET + all (logit), C=0.05")
evaluate(d, LQ, logreg(), "cand", "questions only (logit)")
evaluate(d, DET_FEATURES + ["l_q_rule", "l_q_new", "l_q_routine"], logreg(), "cand", "DET + rule,new,routine (logit)")
evaluate(d, DET_FEATURES + ["l_q_newsletter"], logreg(), "cand", "DET + newsletter (logit)")
IVF = ["app_inst", "five", "star", "obv"]
two_track(d, IVF + LQ, logreg(), "TT structural + all (logit)")
two_track(d, IVF + ["l_q_rule", "l_q_new", "l_q_routine"], logreg(), "TT structural + rule,new,routine (logit)")
two_track(d, IVF + ["l_q_transfer"], logreg(), "TT structural + transfer (logit)")
two_track(d, IVF + ["l_q_transfer", "l_q_rule", "l_q_new"], logreg(), "TT structural + transfer,rule,new (logit)")
