"""Arm O: feature sets x {logistic regression, XGBoost} on the current pipeline's kept rulings.

Reads the triage pipeline from the replay cache (no gateway call, nothing written to the database or
results/), joins the research sprint's cached Apertus rubric answers by docket (rulings outside the sprint's
narrower gate get the neutral value), and scores every variant with ``src.triage.variants``. Optional
``--features <parquet>`` joins new per-docket Apertus features (columns ``f_*``).

Run: uv run --frozen python research/arm_o_variants.py [--features data/derived/triage_features/<file>.parquet]
Output: research/out/arm_o_variants.json (git-ignored, aggregate counts only).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.llm.client import client_from_env  # noqa: E402
from src.triage import pipeline  # noqa: E402
from src.triage import scorer as sc  # noqa: E402
from src.triage import variants as vr  # noqa: E402
from suva_data import db  # noqa: E402

OUT = ROOT / "research" / "out"
FEATURES_DIR = ROOT / "data" / "derived" / "triage_features"
READINGS = ("verdict", "yes_strict", "scale_generic", "scale_area", "scale_headnote", "scale_tail")
FACTS = sc.FEATURES[:8]
RUBRIC = [
    "q_rule", "q_new", "q_factual", "q_routine", "q_insurer_lost",
    "q_transfer", "q_practice", "q_newsletter", "q_uvcore",
]
MORE = ["q_legalq", "q_headnote", "q_depth", "q_unusual", "q_corrects", "q_learn", "q_stdonly"]


def logit(p: pd.Series) -> pd.Series:
    p = p.clip(1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def kept_rows() -> list[dict]:
    with db.connect() as conn:
        result = pipeline.run(conn, client_from_env("replay"), workers=5)
    failed, gate = pipeline.failures(result)
    if failed or gate:
        raise SystemExit(f"replay cache incomplete ({failed} readings, {gate} gate readings)")
    return result["kept"]


# Code-read topic of the subject line's bracket. Lists fixed from Suva's rubric (src/triage/reading_prompts.RUBRIC:
# a disability ruling is picked when its point also holds in accident insurance) and a look at 2025 Q4 only.
_BRACKET = re.compile(r"\(([^)]*)\)")
_PROC = re.compile(
    r"prozessvoraus|prozessvorausse|recevabilit|presupposto processuale|nichteintret|irrecevab|unentgeltlich|"
    r"assistance judiciaire|gratuito patrocinio|parteientsch|kosten|frais|spese"
)
_SHARED = re.compile(
    r"invaliditätsbemessung|einkommensvergleich|valideneinkommen|invalideneinkommen|leidensabzug|tabellenlohn|"
    r"évaluation de l'invalidité|revenu|abattement|valutazione dell'invalidit|reddito|"
    r"hilflos|impotence|grande invalidit|revision|révision|revisione|neuanmeldung|nouvelle demande|"
    r"rückerstattung|restitution|restituzione|drittauszahlung|verrechnung|compensation|"
    r"gutachten|expertise|perizia|rechtliches gehör|droit d'être entendu|frist|délai|termine"
)


def bracket(subject: object) -> str:
    m = _BRACKET.search(subject) if isinstance(subject, str) else None
    return m.group(1).casefold() if m else ""


def build_table(kept: list[dict], extra: pd.DataFrame | None) -> tuple[dict[str, np.ndarray], list[str]]:
    rows = [r for r in kept if r.get("y") is not None]
    df = pd.DataFrame({"docket": [r["docket"] for r in rows]})
    topics = [bracket(r.get("subject")) for r in rows]
    df["c_proc_subject"] = [float(bool(_PROC.search(t))) for t in topics]
    df["c_shared_topic"] = [float(bool(_SHARED.search(t))) for t in topics]
    is_iv = [r["signals"]["area"] == "IV" for r in rows]
    df["c_shared_topic_iv"] = df["c_shared_topic"] * np.array(is_iv, dtype=float)
    for i, name in enumerate(sc.FEATURES):
        df[name] = [r["x"][i] for r in rows]
    for name in READINGS:  # the six relevance readings, None outside the core rulings
        df[f"r_{name}"] = [(r.get("readings") or {}).get(name) for r in rows]
    df["area_iv_flag"] = np.array(is_iv, dtype=float)
    df["y"] = [r["y"] for r in rows]
    df["quarter"] = [r["quarter"] for r in rows]
    df["core"] = [r["signals"]["area"] in pipeline.CORE_AREAS for r in rows]
    lab = pd.read_parquet(OUT / "arm_b_rubric_lab.parquet").drop(columns="id")
    more = pd.read_parquet(OUT / "more_answers_lab.parquet")
    more = more.merge(pd.read_parquet(OUT / "arm_b_rubric_lab.parquet")[["id", "docket"]], on="id").drop(columns="id")
    df = df.merge(lab, on="docket", how="left").merge(more, on="docket", how="left")
    df["in_research"] = df["q_rule"].notna()
    # the sprint's composite, signs fixed by meaning (research/arm_g_composite.py), then a logit-scale version
    df["principle"] = (df.q_rule + df.q_new + (1 - df.q_factual) + (1 - df.q_routine)) / 4
    df["principle_logit"] = (logit(df.q_rule) + logit(df.q_new) - logit(df.q_factual) - logit(df.q_routine)) / 4
    added = ["principle", "principle_logit", *RUBRIC, *MORE, *(f"r_{n}" for n in READINGS)]
    if extra is not None:
        df = df.merge(extra, on="docket", how="left")
        added += [c for c in extra.columns if c.startswith("f_")]
    for path in sorted(FEATURES_DIR.glob("*_*.parquet")):
        if path.stem.endswith("_partial"):
            continue
        size = path.stem.rsplit("_", 1)[1]
        new = pd.read_parquet(path)
        cols = [c for c in new.columns if c.startswith("f_")]
        new = new[["docket", *cols]].rename(columns={c: f"{c}_{size}" for c in cols})
        df = df.merge(new, on="docket", how="left")
        added += [f"{c}_{size}" for c in cols]
    for c in added:  # neutral value for rulings no reading covers: the mean of the rulings read
        df[c] = df[c].fillna(df[c].mean())
    for c in [c for c in added if c.startswith(("f_stmt_p_", "f_topic_shared_"))]:  # extreme probabilities
        df[f"{c}_logit"] = logit(df[c])
        added.append(f"{c}_logit")
    # Consensus+ : the six readings and the new ones, each standardised over the core rulings and averaged with
    # equal weights, as pipeline.Consensus does (no label involved). Topic counts only inside disability insurance.
    core_mask = df["core"].astype(bool)
    for size in ("small", "large"):
        extra_cols = [c for c in (f"f_stmt_p_{size}_logit", f"f_topic_shared_{size}_logit") if c in df]
        if not extra_cols:
            continue
        parts = [df["consensus"] / df.loc[core_mask, "consensus"].std()]
        for c in extra_cols:
            z = (df[c] - df.loc[core_mask, c].mean()) / df.loc[core_mask, c].std()
            if "topic" in c:
                z = z * df["area_iv_flag"]
            parts.append(z.where(core_mask, 0.0))
        df[f"consensus_plus_{size}"] = sum(parts) / len(parts)
        added.append(f"consensus_plus_{size}")
    for c in [c for c in added if c.startswith("f_topic_")]:  # the topic matters inside disability insurance
        df[f"{c}_iv"] = df[c] * df["area_iv_flag"]
        added.append(f"{c}_iv")
    return {c: df[c].to_numpy() for c in df.columns}, added


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=OUT / "arm_o_variants.json")
    args = ap.parse_args(argv)
    extra = pd.read_parquet(args.features) if args.features else None
    table, added = build_table(kept_rows(), extra)
    base_cols = [*FACTS, "consensus"]
    sets = {
        # raw Apertus, no engineering (principle 9): one reading, or the averaged readings, plus nothing else
        "Apertus verdict alone": ["r_verdict"],
        "Apertus consensus alone": ["consensus"],
        "facts8": FACTS,
        "facts8+consensus (baseline)": base_cols,
        "facts8+consensus+principle (research)": [*base_cols, "principle"],
        "facts8+consensus+proc (code)": [*base_cols, "c_proc_subject"],
    }
    new = [c for c in added if c.startswith("f_")]
    for size in ("small", "large"):
        mine = [c for c in new if c.endswith(f"_{size}") or c.endswith(f"_{size}_iv")]
        if not mine:
            continue
        topic_iv = [f"f_topic_{g}_{size}_iv" for g in ("shared", "medical", "iv_only")]
        stmt = [f"f_stmt_p_{size}", f"f_stmt_verified_{size}", f"f_stmt_own_{size}"]
        sets[f"facts8+consensus+topic_iv[{size}]"] = [*base_cols, *[c for c in topic_iv if c in new]]
        sets[f"facts8+consensus+topic_shared_iv[{size}]"] = [*base_cols, f"f_topic_shared_{size}_iv"]
        for c in stmt:
            if c in new:
                sets[f"facts8+consensus+{c}"] = [*base_cols, c]
        if f"f_stmt_own_{size}" in new:
            sets[f"facts8+consensus+stmt_own+topic_shared_iv[{size}]"] = [
                *base_cols, f"f_stmt_own_{size}", f"f_topic_shared_{size}_iv"]
            sets[f"facts8+stmt_own+topic_shared_iv[{size}] (no consensus)"] = [
                *FACTS, f"f_stmt_own_{size}", f"f_topic_shared_{size}_iv"]
    for size in ("small", "large"):
        if f"consensus_plus_{size}" in added:
            sets[f"facts8+consensus_plus[{size}] (no fitted weight)"] = [*FACTS, f"consensus_plus_{size}"]
            sets[f"facts8+consensus+stmt_p_logit[{size}]"] = [*base_cols, f"f_stmt_p_{size}_logit"]
            sets[f"facts8+consensus+stmt_p_logit+shared_logit_iv[{size}]"] = [
                *base_cols, f"f_stmt_p_{size}_logit", f"f_topic_shared_{size}_logit_iv"]
    variants = []
    for name, cols in sets.items():
        variants.append(vr.Variant(f"LR {name}", cols, vr.logistic))
        variants.append(vr.Variant(f"XGB {name}", cols, vr.xgboost, weighted=True))
    results = [vr.evaluate(v, table) for v in variants]
    base = next(r for r in results if r["variant"] == "LR facts8+consensus (baseline)")
    for r in results:
        r["beats_baseline"] = vr.beats(r, base)
        r["bootstrap_vs_baseline"] = vr.paired_bootstrap(r, base, n_boot=1000)
    summary = {
        "labelled_kept": int(len(table["y"])),
        "relevant": int(table["y"].sum()),
        "covered_by_research_answers": int(table["in_research"].sum()),
        "relevant_covered": int(table["y"][table["in_research"]].sum()),
        "results": [vr.public(r) for r in results],
    }
    args.out.write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(f"labelled kept {summary['labelled_kept']}, relevant {summary['relevant']}")
    head = "variant".ljust(56) + " ".join(f"@{s:.2f}" for s in vr.SHARES)
    print(head + "  meanF  F2@.4 meanF2 n95 n100 Q1@.4  d@.4 [95% CI] P(>) beats")
    for r in results:
        p = r["pooled"]
        found = " ".join(f"{p[f'{s:.2f}']['found']:>5}" for s in vr.SHARES)
        q1 = r["primary"]["at_share"]["0.40"]["found"]
        b = r["bootstrap_vs_baseline"]
        need = f"{r['pooled_needed_95']:>3} {r['pooled_needed_100']:>4}"
        boot = f"{b['mean']:+5.1f} [{b['low']:+.0f},{b['high']:+.0f}] {b['p_better']:.2f}"
        print(f"{r['variant'][:55].ljust(56)}{found}  {r['mean_found']:5.1f} {p['0.40']['f2']:.3f}  {r['mean_f2']:.3f} "
              f"{need} {q1:>4}  {boot} {'YES' if r['beats_baseline'] else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
