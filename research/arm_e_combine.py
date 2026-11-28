"""Arm E: combine deterministic features with Apertus rubric answers, the 70B holistic score and embedding features.

Tolerant of missing inputs: uses whatever the other arms have written to research/out/.
Writes research/out/arm_e_results.csv and research/out/arm_e_curves.json.
"""
import glob, json, sys
import numpy as np, pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from common import load, evaluate, logreg, DET_FEATURES, OUT
from evalx import held_out, curve, policy_eval

df = load().reset_index(drop=True)
rows, curves = [], {}


def run(name, feats, mk=None, scope="cand", pol=True):
    mk = mk or logreg()
    r = evaluate(df, feats, mk, scope, name)
    h = held_out(df, feats, mk, scope)
    c = curve(h, "s_xq"); curves[name] = {"xq": c, "rcv": curve(h, "s_rcv")}
    for lv in (0.9, 0.95, 1.0):
        r[f"kept@{lv}"] = c[lv]["kept"] if c[lv] else None
        r[f"f2@{lv}"] = c[lv]["f2"] if c[lv] else None
    if pol:
        p = policy_eval(df, feats, mk, scope, policies=("r95",))["r95"]
        r.update({"r95_xq_f2": p["xq_f2"], "r95_xq_recall": p["xq_recall"], "r95_xq_kept": p["xq_kept"]})
    rows.append(r)
    print(f"     to reach recall .90/.95/1.0 submit {r['kept@0.9']}/{r['kept@0.95']}/{r['kept@1.0']} "
          f"(F2 {r['f2@0.9']}/{r['f2@0.95']}/{r['f2@1.0']})" + (f" | recall-95 policy: F2 {r['r95_xq_f2']} R {r['r95_xq_recall']} kept {r['r95_xq_kept']}" if pol else ""))
    return r, h


# ------------------------------------------------------------------ inputs from other arms
Q = []
p = OUT / "rubric_answers.parquet"
if p.exists():
    ra = pd.read_parquet(p)
    Q = [c for c in ra.columns if c not in ("id", "docket") and pd.api.types.is_numeric_dtype(ra[c])]
    df = df.merge(ra[["id"] + Q], on="id", how="left")
    cover = df[df.labelled & df.cand][Q].notna().mean().round(2).to_dict()
    print("rubric questions:", Q, "| coverage on labelled candidates:", cover)
    for c in Q:
        df[c] = df[c].fillna(df[c].median())
A = []
for f in sorted(glob.glob(str(OUT / "arm_a_*.parquet"))):
    v = f.split("arm_a_")[-1].replace(".parquet", "")
    if v.startswith("pilot"):
        continue
    a = pd.read_parquet(f)
    if a.id.nunique() < 200:
        continue
    for col in ("score", "p_yes", "decision"):
        if col in a and a[col].notna().mean() > 0.9:
            n = f"a_{v}_{col}"; df = df.merge(a[["id", col]].rename(columns={col: n}), on="id", how="left")
            df[n] = df[n].astype(float).fillna(df[n].astype(float).median()); A.append(n)
print("holistic columns:", A)

print("\n== baselines")
run("deterministic 11", DET_FEATURES)
if Q:
    print("\n== Apertus rubric answers")
    run("rubric questions only", Q)
    run("deterministic + all questions", DET_FEATURES + Q)
    best = []
    for c in Q:
        r, _ = run(f"deterministic + {c}", DET_FEATURES + [c], pol=False); best.append((r["rcv_f2"], r["ap"], c))
    top = [c for _, _, c in sorted(best, reverse=True)[:3]]
    run("deterministic + top3 questions (" + ",".join(top) + ")", DET_FEATURES + top)
    # questions matter mostly inside one area: interactions
    for c in Q:
        df[c + "_iv"] = df[c] * df.area_iv; df[c + "_uv"] = df[c] * df.area_uvmv
    run("deterministic + top3 x area", DET_FEATURES + [c + s for c in top for s in ("_iv", "_uv")])
for n in A:
    print(f"\n== 70B holistic: {n}")
    run(f"{n} alone", [n])
    run(f"deterministic + {n}", DET_FEATURES + [n])
    if Q:
        run(f"deterministic + all questions + {n}", DET_FEATURES + Q + [n])

pd.DataFrame(rows).to_csv(OUT / "arm_e_results.csv", index=False)
json.dump(curves, open(OUT / "arm_e_curves.json", "w"), default=lambda o: int(o) if isinstance(o, np.integer) else float(o))
R = pd.DataFrame(rows)
print("\nTOP by repeated-CV F2:")
print(R.sort_values("rcv_f2", ascending=False)[["name", "n_feat", "xq_f2", "xq_recall", "xq_kept", "rcv_f2", "rcv_recall", "ap", "kept@0.95", "f2@0.95", "kept@1.0"]].head(15).round(3).to_string(index=False))
