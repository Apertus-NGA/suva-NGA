"""Arm J: forced-choice category instead of yes/no (avoids Apertus's yes-bias). One call per ruling, probabilities over six letters."""
import math, sys
import numpy as np, pandas as pd
import arm_b_lib as B
from common import load, OUT
from apertus import chat_many, M70
from sklearn.metrics import roc_auc_score

CATS = {"A": "Das Gericht legt eine Norm aus oder stellt ein allgemeines Kriterium oder eine Methode des materiellen Rechts auf bzw. präzisiert sie.",
        "B": "Das Gericht entscheidet eine Verfahrensfrage von allgemeiner Bedeutung (Fristen, Zuständigkeit, Parteirechte, Verfahrenspflichten des Versicherers, Kosten).",
        "C": "Das Gericht wendet gefestigte Rechtsprechung auf eine besondere, nicht alltägliche Konstellation an.",
        "D": "Das Gericht prüft im Wesentlichen die Würdigung der medizinischen Beweise und bestätigt den angefochtenen Entscheid.",
        "E": "Das Gericht beanstandet die Sachverhaltsabklärung oder Beweiswürdigung und weist die Sache zur weiteren Abklärung zurück.",
        "F": "Das Urteil betrifft im Kern eine Leistung oder Regel, die es nur in der Invalidenversicherung gibt."}
Q = ("Welche Beschreibung trifft auf den Kern dieses Urteils am besten zu?\n" + "\n".join(f"{k}) {v}" for k, v in CATS.items()) +
     "\n\nHinweis: Die meisten Urteile gehören zu D. Wähle A, B oder C nur, wenn das Urteil tatsächlich eine über den Einzelfall hinaus verwendbare rechtliche Aussage enthält.\n"
     "Antworte nur mit einem Buchstaben (A, B, C, D, E oder F).")
df = load(); part = df[df.cand & (df.labelled | (df.q == "2026 Q2"))]
jobs = [dict(model=M70, messages=[{"role": "system", "content": B.SYS_Q}, {"role": "user", "content": f"{B.doc(r)}\n\n{Q}"}], max_tokens=2, logprobs=True, top_logprobs=12, tag="category") for _, r in part.iterrows()]
res = chat_many(jobs, workers=6, progress=100)
rows = []
for (_, r), x in zip(part.iterrows(), res):
    p = dict.fromkeys(CATS, 0.0)
    if x.get("logprobs"):
        for alt in x["logprobs"][0]["top_logprobs"]:
            w = alt["token"].strip().strip(").").upper()
            if w in p: p[w] += math.exp(alt["logprob"])
    s = sum(p.values()) or 1.0
    rows.append({"id": r.id, **{"cat_" + k: v / s for k, v in p.items()}, "cat": (x.get("text") or "?").strip()[:1].upper()})
C = pd.DataFrame(rows); C.to_parquet(OUT / "category.parquet")
D = df[df.labelled & df.cand].merge(C, on="id")
print("category counts and pick rate (labelled candidates):")
for a, S in (("UV", D[D.area_uvmv == 1]), ("IV", D[D.area_iv == 1])):
    g = S.groupby("cat").pos.agg(["sum", "count"]); g["rate"] = (g["sum"] / g["count"]).round(2); print(a, g.T.to_dict())
D["cat_subst"] = D.cat_A + D.cat_B + D.cat_C
for c in ["cat_A", "cat_B", "cat_C", "cat_D", "cat_E", "cat_F", "cat_subst"]:
    print(f"  {c:10s} AUC UV {roc_auc_score(D[D.area_uvmv==1].pos, D[D.area_uvmv==1][c]):.3f} | IV {roc_auc_score(D[D.area_iv==1].pos, D[D.area_iv==1][c]):.3f} | mean {D[c].mean():.2f}")
