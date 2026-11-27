"""Arm G: fewer, sturdier Apertus features. A single 'principle' composite from four rubric answers, and recall-first curves."""
import sys, json
import numpy as np, pandas as pd
from sklearn.metrics import roc_auc_score
from common import load, evaluate, logreg, DET_FEATURES, OUT
from evalx import held_out, curve, policy_eval
from two_track import two_track

df = load().reset_index(drop=True)
ra = pd.read_parquet(OUT / "rubric_answers.parquet"); Q = [c for c in ra.columns if c.startswith("q_")]
df = df.merge(ra[["id"] + Q], on="id", how="left")
df["principle"] = (df.q_rule + df.q_new + (1 - df.q_factual) + (1 - df.q_routine)) / 4   # signs fixed a priori by meaning
df["principle2"] = (df.q_rule + df.q_new) / 2
for f in sorted((OUT).glob("arm_a_strict_label.parquet")):
    a = pd.read_parquet(f); df = df.merge(a[["id", "p_yes"]].rename(columns={"p_yes": "a70"}), on="id", how="left")
L = df[df.labelled & df.cand]
for c in ["principle", "principle2", "a70"]:
    if c in L: print(c, "AUC all", round(roc_auc_score(L.pos, L[c]), 3), "UV", round(roc_auc_score(L[L.area_uvmv == 1].pos, L[L.area_uvmv == 1][c]), 3), "IV", round(roc_auc_score(L[L.area_iv == 1].pos, L[L.area_iv == 1][c]), 3))
rows = []
def run(name, feats, mk=None):
    mk = mk or logreg(); r = evaluate(df, feats, mk, "cand", name); h = held_out(df, feats, mk); c = curve(h, "s_xq"); c2 = curve(h, "s_rcv")
    r.update({f"xq_kept@{k}": v["kept"] for k, v in c.items()}); r.update({f"xq_f2@{k}": v["f2"] for k, v in c.items()}); r.update({f"rcv_kept@{k}": v["kept"] for k, v in c2.items()})
    print("      submit to reach recall .85/.90/.95/1.0  xq:", [c[k]["kept"] for k in (0.85, 0.9, 0.95, 1.0)], " rcv:", [c2[k]["kept"] for k in (0.85, 0.9, 0.95, 1.0)])
    rows.append(r); return h
CORE = ["area_uvmv", "app_inst", "five", "star", "obv", "suva_party"]            # 6 sturdy structural features
h0 = run("deterministic 11", DET_FEATURES)
run("core 6 structural", CORE)
h1 = run("deterministic 11 + principle", DET_FEATURES + ["principle"])
run("core 6 + principle", CORE + ["principle"])
run("core 6 + principle2 (rule,new)", CORE + ["principle2"])
df["principle_iv"] = df.principle * df.area_iv; df["principle_uv"] = df.principle * df.area_uvmv
run("core 6 + principle by area", CORE + ["principle_iv", "principle_uv"])
if "a70" in df:
    run("core 6 + principle + 70B score", CORE + ["principle", "a70"])
    run("deterministic 11 + principle + 70B score", DET_FEATURES + ["principle", "a70"])
print("\ntwo-track (all UV/MV in; model decides IV)")
IVF = ["app_inst", "five", "star", "obv"]
two_track(df, IVF, logreg(), "TT structural 4")
two_track(df, IVF + ["principle"], logreg(), "TT structural 4 + principle")
two_track(df, ["app_inst", "five", "principle"], logreg(), "TT app_inst, five, principle")
for p in ("0.75", "0.9"):
    two_track(df, IVF + ["principle"], logreg(), f"TT structural 4 + principle, keep {p} of training IV picks", pol=p)
    two_track(df, IVF, logreg(), f"TT structural 4, keep {p} of training IV picks", pol=p)
print("\nthreshold policies, deterministic 11 + principle:")
for k, v in policy_eval(df, DET_FEATURES + ["principle"], logreg(), policies=("f2", "r90", "r95")).items(): print(" ", k, v)
pd.DataFrame(rows).to_csv(OUT / "arm_g_results.csv", index=False)
h1.merge(h0[["id", "s_xq", "s_rcv"]].rename(columns={"s_xq": "det_xq", "s_rcv": "det_rcv"}), on="id").to_csv(OUT / "arm_g_heldout_scores.csv", index=False)
