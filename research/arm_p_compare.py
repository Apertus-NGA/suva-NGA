"""Arm P, step 2: what the deterministic harness changes, feature by feature and in the classifier.

For each Apertus reading of ``src.triage.claims``, on the accident / military / disability rulings of the two
listed quarters:

- code only:  the claim's marker wording anywhere in the reasoning (no Apertus);
- before:     Apertus, one word Ja/Nein, no evidence asked (``zero``);
- cited:      Apertus must name the consideration for a Ja;
- located:    Apertus always names the consideration; code looks for the wording in it.

Then each feature is added to the current classifier (8 facts + consensus, logistic regression) under the
out-of-quarter protocol of ``src.triage.variants``. No gateway call: reads the replay cache and
data/derived/triage_claims/. Output: aggregates only (D-031).

Run: uv run --frozen python research/arm_p_compare.py [--out results/triage_claims.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research"))

import arm_o_variants as ao  # noqa: E402

from src.triage import claims as cl  # noqa: E402
from src.triage import evidence as ev  # noqa: E402
from src.triage import reading_prompts as p  # noqa: E402
from src.triage import variants as vr  # noqa: E402

CLAIMS_DIR = ROOT / "data" / "derived" / "triage_claims"
SIZES = {"small": "8B", "large": "70B"}
QUARTERS = [fold[1] for fold in vr.FOLDS][::-1]  # 2025 Q4, 2026 Q1
BASE = ao.FACTS + ["consensus"]


def load(name: str, size: str) -> pd.DataFrame | None:
    path = CLAIMS_DIR / f"{name}_{size}.parquet"
    return pd.read_parquet(path).set_index("docket") if path.exists() else None


def build() -> tuple[pd.DataFrame, list[str]]:
    kept = ao.kept_rows()
    table, _ = ao.build_table(kept, None)
    df = pd.DataFrame({k: v for k, v in table.items() if np.ndim(v) == 1}).set_index("docket", drop=False)
    text = {r["docket"]: r["text"] for r in kept}
    reasoning = {d: (p.sections(text[d])["reasoning"] or text[d]) for d in df.index}
    norm = {d: ev._norm(reasoning[d]) for d in df.index}
    added: list[str] = []

    def add(col: str, values: pd.Series | dict) -> None:
        df[col] = pd.Series(values, dtype=float).reindex(df.index)
        added.append(col)

    for name, claim in cl.CLAIMS.items():
        add(f"code_{name}", {d: float(bool(claim.markers.search(norm[d]))) for d in df.index})
        for size in SIZES:
            for arm in cl.ARMS:
                got = load(f"{name}_{arm}", size)
                if got is None:
                    continue
                key = f"{name}_{arm}_{size}"
                add(f"p_{key}", got["p"])
                add(f"l_{key}", ao.logit(got["p"].astype(float)))
                if arm != "zero":
                    check = got["check"].map({True: 1.0, False: 0.0})
                    add(f"chk_{key}", check)
                    add(f"pchk_{key}", got["p"].astype(float) * check)  # counts only where code finds the wording
    whole = pd.DataFrame({d: cl.measure(reasoning[d]) for d in df.index}).T
    for m in cl.MEASURES:
        add(f"code_m_{m}", whole[m])
    add("code_article_shared", {d: cl.most_cited_article(text[d])["shared"] for d in df.index})
    for size in SIZES:
        got = load("locate", size)
        if got is not None:
            for m in cl.MEASURES:
                add(f"loc_{m}_{size}", got[m])
        for arm in ("zero", "cited"):
            got = load(f"article_{arm}", size)
            if got is not None:
                add(f"art_shared_{arm}_{size}", got["shared"])
                add(f"art_inruling_{arm}_{size}", got["in_ruling"].map({True: 1.0, False: 0.0}))
                if arm == "cited":
                    add(f"art_check_{size}", got["check"].map({True: 1.0, False: 0.0}))
    return df, added


def auc(y: pd.Series, v: pd.Series) -> float | None:
    ok = v.notna()
    if ok.sum() < 10 or y[ok].nunique() < 2 or v[ok].nunique() < 2:
        return None
    return round(float(roc_auc_score(y[ok], v[ok])), 3)


def feature_row(df: pd.DataFrame, col: str, binary_at: float = 0.5) -> dict:
    core = df[df.core.astype(bool)]
    v = core[col]
    yes = v > binary_at
    n, tp = int(yes.sum()), int(core.y[yes].sum())
    return {
        "feature": col,
        "answered": int(v.notna().sum()),
        "yes": n,
        "yes_relevant": tp,
        "precision": round(tp / n, 3) if n else None,
        "recall_of_yes": round(tp / int(core.y.sum()), 3),
        **{f"auc_{q}": auc(core.y[core.quarter == q], v[core.quarter == q]) for q in QUARTERS},
        "auc_iv_only": auc(core.y[core.area_iv_flag == 1], v[core.area_iv_flag == 1]),
    }


def model_rows(df: pd.DataFrame, added: list[str], sets: dict[str, list[str]]) -> list[dict]:
    filled = df.copy()
    core = filled.core.astype(bool)
    for c in added:  # a ruling that was not asked takes the average of those that were, as the consensus does
        filled[c] = filled[c].fillna(filled.loc[core, c].mean()).fillna(0.0)
    table = {c: filled[c].to_numpy() for c in filled.columns}
    base = vr.evaluate(vr.Variant("baseline", BASE, vr.logistic), table)
    out = [{**vr.public(base), "vs_baseline": None, "passes": None}]
    for name, cols in sets.items():
        if any(c not in filled for c in cols):
            continue
        res = vr.evaluate(vr.Variant(name, BASE + cols, vr.logistic), table)
        boot = vr.paired_bootstrap(res, base)
        out.append({**vr.public(res), "vs_baseline": boot, "passes": bool(vr.beats(res, base))})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "research" / "out" / "arm_p_compare.json"))
    args = ap.parse_args(argv)
    df, added = build()
    core = df[df.core.astype(bool)]
    print(f"core rulings {len(core)}, relevant {int(core.y.sum())}")
    cols = ["consensus", "r_yes_strict"] + [c for c in added if not c.startswith("l_")]
    features = [feature_row(df, c) for c in cols]
    names = ("n", "yes", "rel", "prec", "AUC Q4", "AUC Q1", "AUC IV")
    print(f"{'feature':34s} " + " ".join(f"{n:>7s}" if i > 2 else f"{n:>4s}" for i, n in enumerate(names)))
    for r in features:
        vals = [r["precision"], r[f"auc_{QUARTERS[0]}"], r[f"auc_{QUARTERS[1]}"], r["auc_iv_only"]]
        txt = " ".join(f"{v:7.2f}" if v is not None else "      -" for v in vals)
        print(f"{r['feature']:34s} {r['answered']:4d} {r['yes']:4d} {r['yes_relevant']:4d} {txt}")

    sets: dict[str, list[str]] = {}
    for name in cl.CLAIMS:
        sets[f"{name} | code only"] = [f"code_{name}"]
        for size in SIZES:
            sets[f"{name} | before (zero-shot) {SIZES[size]}"] = [f"l_{name}_zero_{size}"]
            sets[f"{name} | cited {SIZES[size]}"] = [f"l_{name}_cited_{size}"]
            sets[f"{name} | located {SIZES[size]}"] = [f"l_{name}_located_{size}"]
            checked = [f"l_{name}_located_{size}", f"chk_{name}_located_{size}"]
            sets[f"{name} | located + code check {SIZES[size]}"] = checked
    for m in ("practice", "error", "case_law", "shared_law"):
        sets[f"deciding consideration: {m} | code only (whole ruling)"] = [f"code_m_{m}"]
        for size in SIZES:
            sets[f"deciding consideration: {m} | located {SIZES[size]}"] = [f"loc_{m}_{size}"]
    sets["article shared | code only (most cited)"] = ["code_article_shared"]
    for size in SIZES:
        sets[f"article shared | before (zero-shot) {SIZES[size]}"] = [f"art_shared_zero_{size}"]
        sets[f"article shared | cited + checked {SIZES[size]}"] = [f"art_shared_cited_{size}"]
    models = model_rows(df, added, sets)
    print(f"\n{'variant':62s} found@30/40/50/60/70   F2@40  need95/100  Q1@40  vs base")
    for r in models:
        found = "/".join(str(r["pooled"][f"{s:.2f}"]["found"]) for s in vr.SHARES)
        q1 = r["primary"]["at_share"]["0.40"]["found"]
        vs = r["vs_baseline"]
        delta = f"{vs['mean']:+.1f} [{vs['low']:+.0f},{vs['high']:+.0f}]" if vs else ""
        flag = " PASS" if r["passes"] else ""
        need = f"{r['pooled_needed_95']}/{r['pooled_needed_100']}"
        print(f"{r['variant']:62s} {found:20s} {r['pooled']['0.40']['f2']:.3f}  {need:10s}  {q1:3d}   {delta}{flag}")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    summary = {"core_rulings": int(len(core)), "relevant": int(core.y.sum()), "features": features, "models": models}
    Path(args.out).write_text(json.dumps(summary, indent=1, default=float))
    print(f"\n-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
