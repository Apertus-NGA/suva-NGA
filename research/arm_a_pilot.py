"""Arm A pilot: Apertus alone, several prompt variants.

DEVELOPMENT EXPERIMENT (MODELS.md §4): the `*_think` variants use a thinking model, which the shared client
src/llm/ refuses (AGENTS.md G3, thinking off). research/apertus.py raises ResearchRefused for them unless
research/cache/apertus.sqlite already holds the answer; the other variants run through the client.
"""
import sys, time
import numpy as np, pandas as pd
from sklearn.metrics import roc_auc_score
from arm_a_lib import *
from common import prf

df = load(); C = df[df.labelled & df.cand]
rs = np.random.RandomState(1)
parts = [C[(C.cls == c) & (C.pos == p)].sample(n, random_state=rs) for c, p, n in [("UV", 1, 10), ("IV", 1, 10), ("UV", 0, 15), ("IV", 0, 15)]]
S = pd.concat(parts)
V = {
 "a_plain":        dict(prompt="plain"),
 "b_rubric":       dict(prompt="rubric"),
 "c_fewshot":      dict(prompt="fewshot"),
 "b_rubric_full":  dict(prompt="rubric", inp="full"),
 "f_plain_label":  dict(prompt="plain", out="label"),
 "f_rubric_label": dict(prompt="rubric", out="label"),
 "f_fewshot_label":dict(prompt="fewshot", out="label"),
 "d_rubric_think": dict(prompt="rubric", model=M70T),
 "h_strict": dict(prompt="strict"),
 "h_check": dict(prompt="check"),
 "h_strict_label": dict(prompt="strict", out="label"),
 "h_strict_think": dict(prompt="strict", model=M70T),
 "g_rubric_8b":    dict(prompt="rubric", model=M8),
 "g_rubric_label_8b": dict(prompt="rubric", out="label", model=M8),
}
todo = sys.argv[1:] or list(V)
rows = []
for k in todo:
    t = time.time(); d = run(S, "pilot_" + k, **V[k]); d.to_parquet(OUT / f"arm_a_pilot_{k}.parquet")
    y = S.pos.values; ok = d.decision.notna().values
    pred = d.decision.fillna(0).values.astype(bool)
    sc = d.score.fillna(d.decision.fillna(0) * 100).values
    r = prf(pred, y)
    acc = lambda m: float((pred[m] == y[m]).mean())
    rows.append(dict(v=k, err=int(d.error.notna().sum()), unparsed=int((~ok).sum()), yes=int(pred.sum()), acc=round(acc(np.ones(len(y), bool)), 2),
                     acc_uv=round(acc((S.cls == "UV").values), 2), acc_iv=round(acc((S.cls == "IV").values), 2),
                     R=round(r["recall"], 2), P=round(r["precision"], 2), f2=round(r["f2"], 3), auc=round(roc_auc_score(y, sc), 3),
                     nuniq=int(pd.Series(sc).nunique()), ptok=int(d.ptok.fillna(0).mean()), sec=int(time.time() - t)))
    print(rows[-1], flush=True)
    if d.error.notna().any(): print("  ERR", d.error.dropna().iloc[0][:200])
print(pd.DataFrame(rows).to_string())
