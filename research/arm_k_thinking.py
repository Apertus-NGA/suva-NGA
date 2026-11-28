"""Arm K: best 70B prompt (strict rubric) with thinking mode ON.
Thinking only activates on the gateway when NO system message is sent, so the system text is moved into the user turn.
Output: reasoning between <|inner_prefix|> and <|inner_suffix|>, then the answer. usage: arm_k_thinking.py [n]

DEVELOPMENT EXPERIMENT (MODELS.md §4): this arm needs a thinking model, which the shared client src/llm/
refuses (AGENTS.md G3, thinking off). research/apertus.py therefore raises ResearchRefused for any
request not already answered in research/cache/apertus.sqlite: the arm replays offline only."""
import re, sys
import numpy as np, pandas as pd
import arm_a_lib as A
from common import load, OUT, prf, evaluate, logreg
from apertus import chat_many, M70T
from sklearn.metrics import roc_auc_score

df = load(); L = df[df.labelled & df.cand]
if len(sys.argv) > 1: L = L.sample(int(sys.argv[1]), random_state=3)
FMT = ("Überlege zuerst kurz. Schliesse danach mit genau zwei Zeilen ab:\nWahrscheinlichkeit: <ganze Zahl 0-100, dass die Suva dieses Urteil aufnimmt>\nAntwort: <Ja oder Nein>")
jobs = []
for _, r in L.iterrows():
    m = A.messages(r, "strict", "trim", "label")
    sys_txt = "\n".join(x["content"] for x in m if x["role"] == "system"); usr = "\n".join(x["content"] for x in m if x["role"] == "user")
    usr = usr.replace(A.FMT_LABEL, FMT)
    jobs.append(dict(model=M70T, messages=[{"role": "user", "content": sys_txt + "\n\n" + usr}], temperature=0.6, top_p=0.95, max_tokens=1500, tag="think_strict"))
res = chat_many(jobs, workers=8, progress=40)
rows = []
for (_, r), x in zip(L.iterrows(), res):
    t = x["text"] or ""; ans = t.split("<|inner_suffix|>")[-1] if "<|inner_suffix|>" in t else t
    md = re.findall(r"Antwort\s*:?\s*\**\s*(Ja|Nein)", ans, re.I); mp = re.findall(r"Wahrscheinlichkeit\s*:?\s*\**\s*(\d{1,3})", ans)
    rows.append({"id": r.id, "decision": (int(md[-1].lower() == "ja") if md else np.nan), "score": (float(mp[-1]) if mp else np.nan),
                 "think_chars": len(t) - len(ans), "closed": "<|inner_suffix|>" in t, "ctok": x["usage"].get("completion_tokens")})
T = pd.DataFrame(rows); T.to_parquet(OUT / "arm_k_thinking.parquet")
print("n", len(T), "| thinking closed", int(T.closed.sum()), "| unparsed decision", int(T.decision.isna().sum()), "score", int(T.score.isna().sum()), "| median thinking chars", int(T.think_chars.median()), "| median completion tokens", int(T.ctok.median()))
D = L.merge(T, on="id"); D["decision"] = D.decision.fillna(1); D["score"] = D.score.fillna(D.decision * 100)
r = prf(D.decision.values.astype(bool), D.pos.values, 59 - int(D.pos.sum()) if len(D) == 221 else 0)
print("own decision:", {k: round(v, 3) if isinstance(v, float) else v for k, v in r.items()}, "| yes rate", round(D.decision.mean(), 2))
for a, S in (("UV", D[D.area_uvmv == 1]), ("IV", D[D.area_iv == 1])): print(a, "AUC of score", round(roc_auc_score(S.pos, S.score), 3), "| distinct scores", sorted(S.score.unique())[:12])
if len(D) == 221:
    d2 = df.merge(D[["id", "score"]].rename(columns={"score": "think_score"}), on="id", how="left"); d2["think_score"] = d2.think_score.fillna(0)
    evaluate(d2, ["think_score"], logreg(), "cand", "70B thinking score alone")
    from common import DET_FEATURES
    evaluate(d2, ["area_uvmv", "app_inst", "five", "star", "obv", "suva_party", "think_score"], logreg(), "cand", "structural 6 + 70B thinking score")
