"""Arm F: in-context learning on lesson statements.

Apertus sees short lesson statements of rulings Suva picked / did not pick (same insurance area as the target,
taken from a reference set of labelled rulings) and judges whether the new ruling would be picked.
Each ruling gets two scores:
  icl_other : examples from the OTHER labelled quarter (used when the ruling is a test row)
  icl_same  : examples from its OWN quarter, itself excluded (used when the ruling is a training row)
so cross-quarter evaluation never lets a test label reach a test prediction.
"""
import sys, random
import numpy as np, pandas as pd
from common import load, OUT, prf, best_threshold, f2_counts
from apertus import chat_many, p_yes, M70

MODEL = sys.argv[1] if len(sys.argv) > 1 else M70
N_NEG = int(sys.argv[2]) if len(sys.argv) > 2 else 20
df = load(); les = pd.read_parquet(OUT / "lessons.parquet")[["id", "lesson"]].drop_duplicates("id")
D = df[df.labelled & df.cand].merge(les, on="id", how="inner").reset_index(drop=True)
D["area"] = np.where(D.area_uvmv == 1, "UV", "IV")
print("rulings with a lesson:", len(D), "of 221; picks", int(D.pos.sum()))
SYS = ("Du bist Juristin in der Rechtsabteilung der Suva (Schweizerische Unfallversicherungsanstalt). "
       "Die Rechtsabteilung wählt jedes Quartal jene Bundesgerichtsurteile aus, die für die Praxis der Unfallversicherung lehrreich sind, und fasst sie zusammen. "
       "Du beurteilst anhand früherer Auswahlentscheide, ob ein neues Urteil ausgewählt würde.")
AREA = {"UV": "Unfallversicherung", "IV": "Invalidenversicherung"}

def prompt(target, ref):
    rnd = random.Random(int(target.id))
    pos = ref[ref.pos == 1]; neg = ref[ref.pos == 0]
    neg = neg.sample(min(len(neg), N_NEG), random_state=int(target.id) % 1000)
    ex = [(1, r.lesson) for r in pos.itertuples()] + [(0, r.lesson) for r in neg.itertuples()]
    rnd.shuffle(ex)
    lines = [f"{i+1}. [{'AUSGEWÄHLT' if y else 'NICHT AUSGEWÄHLT'}] {t.strip()}" for i, (y, t) in enumerate(ex)]
    u = (f"Frühere Urteile aus dem Bereich {AREA[target.area]} mit dem Entscheid der Rechtsabteilung:\n\n" + "\n\n".join(lines) +
         f"\n\nNeues Urteil ({AREA[target.area]}):\n{target.lesson.strip()}\n\n"
         "Würde die Rechtsabteilung der Suva dieses neue Urteil auswählen? Orientiere dich an den früheren Entscheiden. Antworte nur mit Ja oder Nein.")
    return [{"role": "system", "content": SYS}, {"role": "user", "content": u}]

jobs, keys = [], []
for t in D.itertuples():
    same = D[(D.q == t.q) & (D.area == t.area) & (D.id != t.id)]; other = D[(D.q != t.q) & (D.area == t.area)]
    for kind, ref in (("same", same), ("other", other)):
        jobs.append(dict(model=MODEL, messages=prompt(t, ref), max_tokens=3, logprobs=True, top_logprobs=10, tag=f"icl_{kind}")); keys.append((t.id, kind))
res = chat_many(jobs, workers=6, progress=100)
rows = {}
for (i, kind), r in zip(keys, res):
    p = p_yes(r); rows.setdefault(i, {})["icl_" + kind] = p if p is not None else (1.0 if (r["text"] or "").strip().lower().startswith("ja") else 0.0)
R = pd.DataFrame.from_dict(rows, orient="index").rename_axis("id").reset_index()
tag = ("" if MODEL == M70 else "_8b") + (f"_n{N_NEG}" if N_NEG != 20 else "")
R.to_parquet(OUT / f"icl{tag}.parquet"); D = D.merge(R, on="id")
from sklearn.metrics import roc_auc_score
for a in ("UV", "IV"):
    s = D[D.area == a]; print(a, "AUC icl_other", round(roc_auc_score(s.pos, s.icl_other), 3), "icl_same", round(roc_auc_score(s.pos, s.icl_same), 3), "mean p", s.icl_other.mean().round(2))
print("all AUC icl_other", round(roc_auc_score(D.pos, D.icl_other), 3))
# honest cross-quarter: threshold from training rows' icl_same, applied to test rows' icl_other
tot = dict(tp=0, fp=0, fn=0)
for a, b in [("2025 Q4", "2026 Q1"), ("2026 Q1", "2025 Q4")]:
    tr, te = D[D.q == a], D[D.q == b]; thr = best_threshold(tr.icl_same.values, tr.pos.values)
    r = prf(te.icl_other.values >= thr, te.pos.values, int(df[df.labelled & (df.q == b)].pos.sum() - te.pos.sum()))
    for k in tot: tot[k] += r[k]
print("ICL alone, cross-quarter: F2", round(f2_counts(**tot), 3), "recall", round(tot["tp"] / 59, 3), "kept", tot["tp"] + tot["fp"])
