"""Arm N: 70B with REAL thinking. The reasoning block is forced by prefilling the assistant turn with <|inner_prefix|>
(thinking model, no system message, continue_final_message). Step 2 asks the base 70B for a one-word verdict given that
reasoning and reads P(Ja) from token probabilities, so the result can be ranked.

DEVELOPMENT EXPERIMENT (MODELS.md §4): this arm needs a thinking model, which the shared client src/llm/
refuses (AGENTS.md G3, thinking off). research/apertus.py therefore raises ResearchRefused for any
request not already answered in research/cache/apertus.sqlite: the arm replays offline only."""
import re, sys
import numpy as np, pandas as pd
import arm_a_lib as A
from common import load, OUT, prf, evaluate, logreg
from apertus import chat_many, p_yes, M70T, M70
from sklearn.metrics import roc_auc_score

df = load(); L = df[df.labelled & df.cand]
if len(sys.argv) > 1: L = L.sample(int(sys.argv[1]), random_state=3)
END = "Antworte am Schluss mit einer Zeile: Antwort: Ja oder Antwort: Nein."
def base(r):
    m = A.messages(r, "strict", "trim", "label")
    return "\n".join(x["content"] for x in m if x["role"] == "system") + "\n\n" + "\n".join(x["content"] for x in m if x["role"] == "user").replace(A.FMT_LABEL, END)
B = {r.id: base(r) for _, r in L.iterrows()}
j1 = [dict(model=M70T, messages=[{"role": "user", "content": B[i]}, {"role": "assistant", "content": "<|inner_prefix|>"}], continue_final_message=True, add_generation_prompt=False,
           skip_special_tokens=False, temperature=0.6, top_p=0.95, max_tokens=2500, tag="think2_reason") for i in L.id]
r1 = chat_many(j1, workers=8, progress=40)
rows, j2 = [], []
for i, x in zip(L.id, r1):
    t = x["text"] or ""; closed = "<|inner_suffix|>" in t; think, ans = (t.split("<|inner_suffix|>", 1) + [""])[:2] if closed else (t, "")
    m = re.findall(r"Antwort\s*:?\**\s*(Ja|Nein)", ans or t, re.I)
    rows.append({"id": i, "closed": closed, "think_chars": len(think), "ctok": x["usage"].get("completion_tokens"), "decision": (int(m[-1].lower() == "ja") if m else np.nan), "reasoning": think[:6000]})
    j2.append(dict(model=M70, messages=[{"role": "user", "content": B[i].replace(END, "Überlege zuerst.")}, {"role": "assistant", "content": think.strip()[:6000] or "(keine Überlegung)"},
                                        {"role": "user", "content": "Gestützt auf deine Überlegung: Soll das Urteil in die Rechtsprechungsübersicht der Suva aufgenommen werden? Antworte mit genau einem Wort: Ja oder Nein."}],
                   max_tokens=3, logprobs=True, top_logprobs=10, tag="think2_verdict"))
r2 = chat_many(j2, workers=8, progress=80)
T = pd.DataFrame(rows); T["p_yes"] = [p_yes(x) if p_yes(x) is not None else float((x["text"] or "").strip().lower().startswith("ja")) for x in r2]
T.to_parquet(OUT / "arm_n_thinking2.parquet")
print("n", len(T), "| reasoning block closed", int(T.closed.sum()), "| median reasoning chars", int(T.think_chars.median()), "| median completion tokens", int(T.ctok.median()), "| unparsed own decision", int(T.decision.isna().sum()))
D = L.merge(T, on="id"); D["decision"] = D.decision.fillna((D.p_yes > .5).astype(int))
miss = 59 - int(D.pos.sum()) if len(D) == 221 else 0
print("own decision after thinking:", {k: round(v, 3) if isinstance(v, float) else v for k, v in prf(D.decision.values.astype(bool), D.pos.values, miss).items()}, "| yes rate", round(D.decision.mean(), 2))
print("verdict P(Ja) > 0.5:", {k: round(v, 3) if isinstance(v, float) else v for k, v in prf((D.p_yes > .5).values, D.pos.values, miss).items()})
for a, S in (("accident ins.", D[D.area_uvmv == 1]), ("disability ins.", D[D.area_iv == 1])): print("ranking inside", a, round(roc_auc_score(S.pos, S.p_yes), 3))
if len(D) == 221:
    d2 = df.merge(T[["id", "p_yes"]].rename(columns={"p_yes": "think_p"}), on="id", how="left"); d2["think_p"] = d2.think_p.fillna(0)
    evaluate(d2, ["think_p"], logreg(), "cand", "70B real thinking, P(Ja) alone")
    evaluate(d2, ["area_uvmv", "app_inst", "five", "star", "obv", "suva_party", "think_p"], logreg(), "cand", "structural 6 + 70B real thinking")
