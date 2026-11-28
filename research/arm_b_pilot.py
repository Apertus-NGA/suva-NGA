"""Format pilot: 40 balanced labelled candidates; label-first (all questions) vs rationale-then-label (4 questions)."""
import sys, time, numpy as np
from sklearn.metrics import roc_auc_score
from arm_b_lib import *
W = int(sys.argv[1]) if len(sys.argv) > 1 else 4
df = load(); C = df[df.labelled & df.cand]
P = pd.concat([C[(C.pos==1)&(C.cls=="UV")].sample(12, random_state=1), C[(C.pos==1)&(C.cls=="IV")].sample(8, random_state=1),
               C[(C.pos==0)&(C.cls=="UV")].sample(10, random_state=1), C[(C.pos==0)&(C.cls=="IV")].sample(10, random_state=1)])
docs = {r.id: doc(r) for _, r in P.iterrows()}
RQ = ["q_transfer", "q_rule", "q_newsletter", "q_factual"]
out = []
for fmt, qs in [("label", list(QUESTIONS)), ("rat", RQ)]:
    jobs = [(i, q) for q in qs for i in P.id]
    t = time.time()
    res = chat_many([q_job(M70, docs[i], q, fmt, f"pilot_{fmt}") for i, q in jobs], workers=W, progress=100)
    print(fmt, "secs/call", (time.time() - t) / len(jobs), flush=True)
    for (i, q), x in zip(jobs, res):
        p, h, t_ = parse_q(x, fmt); out.append(dict(id=i, q=q, fmt=fmt, p=p, h=h, text=t_))
o = pd.DataFrame(out).merge(P[["id", "docket", "pos", "cls"]], on="id")
o.to_parquet(OUT / "arm_b_pilot.parquet")
for (q, fmt), s in o.groupby(["q", "fmt"]):
    s2 = s.dropna(subset=["p"])
    print(f"{q:14s} {fmt:5s} n={len(s2)} miss={len(s)-len(s2)} AUC_p={roc_auc_score(s2.pos, s2.p):.3f} AUC_hard={roc_auc_score(s2.pos, s2.h.fillna(0.5)):.3f} ja_rel={s2[s2.pos==1].h.mean():.2f} ja_non={s2[s2.pos==0].h.mean():.2f}")
