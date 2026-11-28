"""Layer-2 benchmark report on suva-ft-v3: rule vs Apertus 8B vs Apertus 70B (docs/FINETUNE.md §5-§6).

Writes an aggregate-only Markdown report (no docket, no per-ruling score: D-031) and its JSON twin.
Metrics: experiments/finetune/metrics.py (frozen, tested against the audit's numbers).

Sources:
  --source runs_v3  the audit's single zero-shot passes (data/derived/finetune/runs_v3/, scored 27 Nov 2026
                    with 03_keera_baseline.py); used before the benchmark has run.
  --source bench    the benchmark of 06_benchmark_repeat.py (data/derived/finetune/bench_v3/): 8b_all (3 passes),
                    70b_all (1 pass), 70b_poshard (100 repetitions on positives + hard negatives).
Usage:
  python3 -I experiments/finetune/scripts/07_report_v3.py --source runs_v3 \
      --out-md results/finetune_benchmark_v3_prelim.md
  python3 -I experiments/finetune/scripts/07_report_v3.py --source bench --out-md results/finetune_benchmark_v3.md
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[3]
FT = REPO / "experiments" / "finetune"
D = REPO / "data" / "derived" / "finetune"
BENCH = D / "bench_v3"  # --bench-dir
_spec = importlib.util.spec_from_file_location("ft_metrics", FT / "metrics.py")
M = importlib.util.module_from_spec(_spec)
sys.modules["ft_metrics"] = M
_spec.loader.exec_module(M)

Q1, Q4 = M.QUARTERS
MODEL_ID = {"8b": "apertus-v1-5-8b", "70b": "apertus-v1-5-70b"}
LABEL = {"rule": "Rule, 3 signals (no LLM)", "8b": "Apertus 8B zero-shot", "70b": "Apertus 70B zero-shot",
         "rule+8b": "Rule + 8B (rank average)", "rule+70b": "Rule + 70B (rank average)"}
SHORTNAME = {"rule": "Rule", "8b": "8B", "70b": "70B", "rule+8b": "Rule+8B", "rule+70b": "Rule+70B"}
PAIRS = [("8b", "rule"), ("70b", "rule"), ("70b", "8b")]
DECISION = ("auc_hard_pooled", "f2_tr_full_pooled")  # §7 decision rule, applied here to zero-shot vs rule
PRIMARY = [
    ("auc_hard_pooled", "AUC vs hard negatives (59 pos vs 235 hard)"),
    ("f2_tr_full_pooled", "F2 at transferred threshold, full quarter"),
    ("f2_tr_l1_pooled", "F2 at transferred threshold, after layer 1"),
    ("f2_top45_pooled", "F2 of the top-45 list per quarter"),
    ("recall_top45_pooled", "Recall of the top-45 list per quarter"),
    ("f2_top60_pooled", "F2 of the top-60 list per quarter"),
    ("recall_top60_pooled", "Recall of the top-60 list per quarter"),
]
PER_FOLD = [("auc_hard", "AUC vs hard"), ("f2_tr_full", "F2 transferred, full"), ("f2_tr_l1", "F2 transferred, L1"),
            ("f2_top45", "F2 top-45"), ("f2_top60", "F2 top-60"), ("auc_full", "AUC full quarter (sanity)")]
SUBGROUPS = [("matiere_UV", "UV"), ("matiere_IV", "IV"), ("lang_de", "DE"), ("lang_fr", "FR"), ("lang_it", "IT")]


def sha(p: Path) -> str:
    return M.file_sha256(p)


def scores_from(paths: list[Path]) -> dict[str, float]:
    out: dict[str, float] = {}
    for p in paths:
        out.update(M.load_scores_jsonl(p))
    return out


def load_systems(source: str, pop) -> tuple[dict[str, dict[str, float]], dict]:
    rule = M.load_rule_scores(D / "audit_v3/resultats/a02_features.json.gz")
    prov = {"rule": {"what": "audit/a07_rule_minimal.py on the a02 features", "date": "deterministic",
                     "features_sha256": sha(D / "audit_v3/resultats/a02_features.json.gz")}}
    if source == "runs_v3":
        s = {m: scores_from([D / f"runs_v3/fold{f}_keera_{m}/test_scores.jsonl" for f in "AB"]) for m in ("8b", "70b")}
        for m in ("8b", "70b"):
            mt = [json.loads((D / f"runs_v3/fold{f}_keera_{m}/test_metrics.json").read_text()) for f in "AB"]
            prov[m] = {"what": "audit single pass, 03_keera_baseline.py (logprobs not stored)", "model": MODEL_ID[m],
                       "gateway": "Keera", "date": "2026-11-27 (docs/FINETUNE.md §4)",
                       "calls": sum(x["n"] for x in mt), "failed": sum(x["n_failed"] for x in mt),
                       "prompt_tokens": sum(x["prompt_tokens"] for x in mt),
                       "wall_s": sum(x["elapsed_s"] for x in mt)}
    else:
        s = {}
        for m, d in (("8b", "8b_all"), ("70b", "70b_all")):
            s[m] = scores_from([BENCH / d / f / "rep000.jsonl" for f in ("fold_A", "fold_B")])
            ra = json.loads((BENCH / d / "run_args.json").read_text())
            rs = json.loads((BENCH / d / "run_summary.json").read_text())
            prov[m] = {"what": f"06_benchmark_repeat.py, {d}, repetition file rep000", "model": ra["model"],
                       "gateway": ra["gateway"], "date": ra["started"], "git_head": ra["git_head"],
                       "script_sha256": ra["script_sha256"], "ids_digest": ra["ids_digest"],
                       "calls": sum(v["calls"] for v in rs.values()),
                       "live_calls": sum(v["live_calls"] for v in rs.values()),
                       "prompt_tokens": sum(v["prompt_tokens"] for v in rs.values()),
                       "wall_s": sum(v["wall_s"] for v in rs.values()),
                       "served_models": sorted({x for v in rs.values() for x in v["served_models"]})}
            if ra["ids_digest"] != M.IDS_DIGEST:
                sys.exit(f"{d}: scored on ids digest {ra['ids_digest'][:12]}…, not suva-ft-v3: stop")
    return {"rule": rule, **s}, prov


def fmt(v, nd=3) -> str:
    if v is None:
        return "n/a"
    return f"{v:.{nd}f}"


def fmt_ci(cell, nd=3) -> str:
    if cell["point"] is None:
        return "n/a"
    ci = cell["ci95"]
    return f"{fmt(cell['point'], nd)} [{fmt(ci[0], nd)}, {fmt(ci[1], nd)}]" if ci else fmt(cell["point"], nd)


def fmt_diff(cell) -> str:
    if cell["point"] is None:
        return "n/a"
    lo, hi = cell["ci95"]
    tag = "includes 0"
    if cell["ci_strictly_above_0"]:
        tag = "**above 0**"
    elif cell["ci_strictly_below_0"]:
        tag = "**below 0**"
    return f"{cell['point']:+.3f} [{lo:+.3f}, {hi:+.3f}] {tag}"


LAB = dict(PRIMARY)
SHORT = {"auc_hard_pooled": "AUC vs hard", "f2_tr_full_pooled": "F2 at the transferred threshold",
         "f2_tr_l1_pooled": "F2 after layer 1", "f2_top45_pooled": "top-45 F2",
         "recall_top45_pooled": "top-45 recall", "f2_top60_pooled": "top-60 F2",
         "recall_top60_pooled": "top-60 recall"}


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def verdict_line(res: dict, a: str, ref: str = "rule") -> tuple[str, str]:
    """Deterministic, from the decision metrics fixed in advance (docs/FINETUNE.md §7), then the other primaries."""
    pair = res["pairs"][f"{a} - {ref}"]
    cells = [pair[k] for k in DECISION]
    if all(c["ci_strictly_above_0"] for c in cells):
        head, text = "beats", "beats the rule on both decision metrics (paired 95 % CIs strictly above 0)"
    elif any(c["ci_strictly_below_0"] for c in cells):
        worse = [SHORT[k] for k, c in zip(DECISION, cells, strict=True) if c["ci_strictly_below_0"]]
        head, text = "worse", f"is worse than the rule on {_join(worse)} (paired 95 % CI strictly below 0)"
    elif any(c["ci_strictly_above_0"] for c in cells):
        better = [SHORT[k] for k, c in zip(DECISION, cells, strict=True) if c["ci_strictly_above_0"]]
        head, text = "partial", (f"does not beat the rule: better on {_join(better)} only (the pass rule needs both "
                                 "decision metrics)")
    else:
        head, text = "tie", "does not beat the rule (both paired 95 % CIs include 0)"
    below = [SHORT[k] for k, _ in PRIMARY if k not in DECISION and pair[k]["ci_strictly_below_0"]]
    above = [SHORT[k] for k, _ in PRIMARY if k not in DECISION and pair[k]["ci_strictly_above_0"]]
    if below:
        text += f"; on the other primary metrics it is worse than the rule on {_join(below)}"
    if above:
        text += f"; on the other primary metrics it is better than the rule on {_join(above)}"
    return head, text


def fmt_thr(t) -> str:
    if t is None:
        return "n/a"
    return f"1 − {1 - t:.1e}" if 0.9999 < t < 1 else f"{t:.4f}"


def run_verify() -> str:
    r = subprocess.run([sys.executable, "-I", str(FT / "scripts/verify_dataset.py"), "--manifest",
                        str(FT / "manifests/suva-ft-v3/MANIFEST_suva_ft_v3.json"), "--data", str(D / "suva-ft-v3")],
                       capture_output=True, text=True)
    last = (r.stdout.strip().splitlines() or ["?"])[-1]
    if r.returncode != 0:
        sys.exit(f"verify_dataset.py failed ({last}): do not compare results")
    return last


def git_head() -> str:
    r = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    return r.stdout.strip() or "?"


def _rep_meta(reps_dir: Path, i: int) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(reps_dir.glob(f"fold_*/rep{i:03d}.meta.json"))]


def repetition_section(pop, scores70: dict[str, float], m70: dict, mrule: dict) -> tuple[list[str], dict]:
    reps_dir = BENCH / "70b_poshard"
    files = {f: sorted((reps_dir / f).glob("rep*.jsonl")) for f in ("fold_A", "fold_B")}
    n = min(len(v) for v in files.values())
    if n == 0:
        return ["_70B repetitions: not run yet._", ""], {}
    reps = [scores_from([files["fold_A"][i], files["fold_B"][i]]) for i in range(n)]
    thr = {q: m70[f"thr_tr_full_{q}"] for q in M.QUARTERS}
    rep = M.repetition_report(pop, reps, scores70, "70b", thr)
    rs = json.loads((reps_dir / "run_summary.json").read_text())
    dist = rep["metric_distribution"]
    per = [M.measure(M.System("70b", {**scores70, **r}, pop)) for r in reps]
    reach = {k: sum(m[k] >= mrule[k] for m in per) for k, _ in PRIMARY}
    lines = [f"{rep['n_reps']} repetitions of the 70B on the {rep['n_rulings']} positives + hard negatives. "
             "F2 and top-k per repetition use the full pass's scores for the easy negatives (they are not repeated).",
             "", "| Metric | mean | std | min | max | repetitions ≥ rule |", "|---|---|---|---|---|---|"]
    for k, lab in PRIMARY:
        if k in dist:
            d = dist[k]
            lines.append(f"| {lab} | {fmt(d['mean'])} | {fmt(d['std'])} | {fmt(d['min'])} | {fmt(d['max'])} | "
                         f"{reach[k]}/{len(per)} (rule {fmt(mrule[k])}) |")
    groups = {}
    for i in range(n):
        for m in _rep_meta(reps_dir, i):
            g = groups.setdefault(m.get("workers"), {"reps": set(), "n": 0, "wall": 0.0, "p50": []})
            g["reps"].add(i + 1)
            g["n"] += m["n"]
            g["wall"] += m["wall_s"]
            if m.get("latency_p50_s") is not None:
                g["p50"].append(m["latency_p50_s"])
    lines += ["", "Throughput by concurrency: " + "; ".join(
        f"{w} concurrent calls, {len(g['reps'])} repetitions: {g['n'] / g['wall']:.1f} calls/s, median latency "
        f"{sorted(g['p50'])[len(g['p50']) // 2]:.2f} s" for w, g in sorted(groups.items(), key=lambda x: x[0] or 0))
        + ". Repetitions 1–4 ran during the concurrency ramp, before the full pass; the later ones, sent back to "
        "back on the same 294 prompts, were about 10× faster (very likely prefix caching at the gateway), yet no "
        "ruling got the same score in every repetition."]
    sp, fl = rep["ruling_spread"], rep["flips"]
    lines += ["", f"Per-ruling score spread (max − min over repetitions): max {fmt(sp['max'])}, median "
              f"{fmt(sp['median'], 4)}, 95th percentile {fmt(sp['p95'])}; {sp['n_gt_0.05']} rulings above 0.05, "
              f"{sp['n_gt_0.1']} above 0.1, {sp['n_identical']} identical in every repetition.",
              f"Rulings that cross a threshold in at least one repetition: {fl['at_0.5']} at 0.5; "
              f"{fl['at_transferred_threshold']} at the full pass's transferred threshold "
              f"({fmt_thr(thr[Q1])} for {Q1}, {fmt_thr(thr[Q4])} for {Q4}).",
              f"Cost: {sum(v['calls'] for v in rs.values())} calls "
              f"({sum(v['live_calls'] for v in rs.values())} live), "
              f"{sum(v['prompt_tokens'] for v in rs.values()):,} prompt tokens, "
              f"{sum(v['wall_s'] for v in rs.values()) / 3600:.2f} h wall time.", ""]
    return lines, {**rep, "cost": rs}


def determinism_8b(pop) -> tuple[list[str], dict]:
    """The 8B's full passes: identical rulings, and each primary metric per pass (the report uses pass 1)."""
    p = BENCH / "8b_all" / "run_summary.json"
    if not p.is_file():
        return [], {}
    rs = json.loads(p.read_text())
    n = sum(v["n_rulings"] for v in rs.values())
    same = sum(v["identical_across_reps"] for v in rs.values())
    mx = max((v["max_spread"] or 0) for v in rs.values())
    files = {f: sorted((BENCH / "8b_all" / f).glob("rep*.jsonl")) for f in ("fold_A", "fold_B")}
    k = min(len(v) for v in files.values())
    reps = [scores_from([files["fold_A"][i], files["fold_B"][i]]) for i in range(k)]
    m1 = M.measure(M.System("8b", reps[0], pop))
    thr = {q: m1[f"thr_tr_full_{q}"] for q in M.QUARTERS}
    rep = M.repetition_report(pop, reps, {}, "8b", thr)
    lines = [f"**8B, {k} full passes.** {same}/{n} rulings have the same score in every pass; max spread "
             f"{mx:.3g}; {rep['ruling_spread']['n_gt_0.05']} rulings differ by more than 0.05. Rulings that cross the "
             f"first pass's transferred threshold in at least one pass: {rep['flips']['at_transferred_threshold']}; "
             f"at 0.5: {rep['flips']['at_0.5']}. Primary metrics per pass (the tables above use pass 1):", "",
             "| Metric | " + " | ".join(f"pass {i + 1}" for i in range(k)) + " |", "|---|" + "---|" * k]
    per = [M.measure(M.System("8b", r, pop)) for r in reps]
    for key, lab in PRIMARY:
        lines.append(f"| {lab} | " + " | ".join(fmt(m[key]) for m in per) + " |")
    lines.append("")
    return lines, {**rep, "summary": rs}


def main() -> None:
    global BENCH
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["runs_v3", "bench"], required=True)
    ap.add_argument("--out-md", type=Path, required=True)
    ap.add_argument("--n-boot", type=int, default=M.N_BOOT)
    ap.add_argument("--seed", type=int, default=M.SEED)
    ap.add_argument("--bench-dir", type=Path, default=BENCH)
    ap.add_argument("--combos", action="store_true", help="FT-Q3 (docs/FINETUNE.md §6b): add rule + 8B, rule + 70B")
    a = ap.parse_args()
    BENCH = a.bench_dir

    verified = run_verify()
    pop = M.load_population(D / "suva-ft-v3")
    raw, prov = load_systems(a.source, pop)
    amb = M.load_ambiguous(D / "audit_v3/negatifs_ambigus_v3.csv")
    names = ["rule", "8b", "70b"]
    pairs = list(PAIRS)
    if a.combos:
        for m in ("8b", "70b"):
            c = f"rule+{m}"
            raw[c] = M.rank_average(pop, [raw["rule"], raw[m]])
            prov[c] = {"what": f"mean of within-quarter percentile ranks of the rule and {LABEL[m]} (no weight fitted)",
                       "inputs": f"rule; {prov[m]['what']}"}
            names.append(c)
            pairs += [(c, "rule"), (c, m)]
    keys = sorted({k for k in M.measure(M.System("rule", raw["rule"], pop))})

    def block(p):
        systems = [M.System(n, raw[n], p) for n in names]
        boots = M.paired_bootstrap(systems, a.n_boot, a.seed)
        return M.summarise(systems, boots, keys, pairs)

    res, sens = block(pop), block(pop.without(amb))
    m70 = M.measure(M.System("70b", raw["70b"], pop))
    counts = pop.counts()
    now = datetime.now(ZoneInfo("Europe/Zurich")).strftime("%Y-%m-%d %H:%M %Z")
    scripts = {p: sha(FT / p) for p in ("metrics.py", "scripts/07_report_v3.py", "scripts/06_benchmark_repeat.py",
                                         "audit/a07_rule_minimal.py")}

    L = []
    title = "Layer-2 benchmark on suva-ft-v3: rule vs Apertus zero-shot"
    if a.combos:
        title = "FT-Q3 on suva-ft-v3: rule + Apertus combination (rank average)"
    if a.source == "runs_v3":
        title += " (PRELIMINARY)"
    L += [f"# {title}", ""]
    if a.source == "runs_v3":
        L += ["> **PRELIMINARY.** Source: the audit's single zero-shot passes of 27 Nov 2026 (`runs_v3`), not the "
              "benchmark of `docs/FINETUNE.md` §6, which has not run yet (no gateway key in the session that wrote "
              "this file). Same gateway, prompt and score definition as the benchmark; no repetitions, no stored "
              "logprobs. `results/finetune_benchmark_v3.md` replaces this file once the benchmark has run.", ""]
    L += ["Machine-written by `experiments/finetune/scripts/07_report_v3.py`. Aggregates only (D-031): no docket, "
          "no per-ruling score.", "",
          "| Item | Value |", "|---|---|",
          f"| Dataset | `{M.DATASET}`, ids digest `{M.IDS_DIGEST}`; `verify_dataset.py`: {verified} |",
          f"| Population | 2026Q1 (fold_A test): {counts[Q1]['positive']} pos, {counts[Q1]['hard_negative']} hard, "
          f"{counts[Q1]['easy_negative']} easy · 2025Q4 (fold_B test): {counts[Q4]['positive']} pos, "
          f"{counts[Q4]['hard_negative']} hard, {counts[Q4]['easy_negative']} easy |",
          f"| Generated | {now}; repo HEAD `{git_head()}` (experiments/ untracked: scripts identified by SHA-256 "
          "below) |",
          f"| Bootstrap | paired, {a.n_boot} resamples, seed {a.seed}, stratified by quarter × (pos, hard, easy); "
          "thresholds re-learnt on every resample |"]
    for n in names:
        p = prov[n]
        desc = "; ".join(f"{k} {v}" for k, v in p.items() if k != "what")
        L.append(f"| {LABEL[n]} | {p['what']}; {desc} |")
    L += ["| Scripts SHA-256 | " + "; ".join(f"`{k}` {v[:12]}…" for k, v in scripts.items()) + " |",
          f"| Ambiguous negatives | 25 dockets, list SHA-256 `{M.AMBIGUOUS_SHA256[:12]}…` |", ""]

    others = [n for n in names if n != "rule"]
    verdicts = {n: verdict_line(res, n) for n in others}
    L += ["## Verdict", ""]
    beats = [n for n in others if verdicts[n][0] == "beats"]
    f2 = {n: res["systems"][n]["f2_tr_full_pooled"]["point"] for n in names}
    auc = {n: res["systems"][n]["auc_hard_pooled"]["point"] for n in names}
    points = ("Point estimates: AUC vs hard " + ", ".join(f"{SHORTNAME[n]} {auc[n]:.3f}" for n in names)
              + "; F2 transferred " + ", ".join(f"{SHORTNAME[n]} {f2[n]:.3f}" for n in names) + ". ")
    caveat = ("With 59 positives the intervals are wide: differences of a few points cannot be resolved, so "
              "\"does not beat\" is not \"is equal\".")
    if a.combos:
        combo_vs_llm = {c: verdict_line(res, c, ref=c.split("+")[1]) for c in names if "+" in c}
        main = "rule+8b"
        head = (f"**Rule + 8B, the FT-Q3 system, {'beats' if verdicts[main][0] == 'beats' else 'does not beat'} "
                f"the three-signal rule.**")
        para = (f"{head} Pass rule written before measuring (`docs/FINETUNE.md` §6b): paired 95 % CI strictly above 0 "
                "on pooled AUC vs hard negatives and pooled F2 at the transferred threshold. "
                + " ".join(f"{LABEL[c]} {verdicts[c][1]}. Compared with {SHORTNAME[c.split('+')[1]]} alone, it "
                           f"{combo_vs_llm[c][1].replace('the rule', SHORTNAME[c.split('+')[1]] + ' alone')}."
                           for c in names if "+" in c)
                + " " + points + caveat)
    else:
        head = ("**No zero-shot Apertus model beats the three-signal rule (no LLM).**" if not beats else
                f"**{' and '.join(LABEL[n] for n in beats)} beat{'s' if len(beats) == 1 else ''} the three-signal "
                "rule.**")
        para = (f"{head} The decision metrics were fixed before the run: pooled AUC vs hard negatives and pooled F2 "
                f"at the transferred threshold. " + " ".join(f"{SHORTNAME[n]} {verdicts[n][1]}." for n in others)
                + " " + points + caveat)
    L += [para, ""]

    L += ["## Primary metrics (pooled over both test quarters, 95 % paired bootstrap CI)", "",
          "| Metric | " + " | ".join(LABEL[n] for n in names) + " |", "|---|" + "---|" * len(names)]
    for k, lab in PRIMARY:
        L.append(f"| {lab} | " + " | ".join(fmt_ci(res["systems"][n][k]) for n in names) + " |")
    L += ["", "Counts at the transferred threshold (TP / FP, pooled, full quarter): " + "; ".join(
        f"{LABEL[n]} {res['systems'][n]['tp_tr_full_pooled']['point']:.0f} / "
        f"{res['systems'][n]['fp_tr_full_pooled']['point']:.0f}" for n in names) + ".", ""]

    L += ["### Paired differences (a − b; the decision rule needs the CI strictly above 0)", "",
          "| Metric | " + " | ".join(f"{SHORTNAME[x]} − {SHORTNAME[y]}" for x, y in pairs) + " |",
          "|---|" + "---|" * len(pairs)]
    for k, lab in PRIMARY:
        L.append(f"| {lab} | " + " | ".join(fmt_diff(res["pairs"][f"{x} - {y}"][k]) for x, y in pairs) + " |")
    L.append("")

    L += ["## Per fold (fold_A = deployment view: trained on 2025Q4, tested on 2026Q1)", "",
          "| Metric | " + " | ".join(f"{LABEL[n]} {q}" for n in names for q in (Q1, Q4)) + " |",
          "|---|" + "---|" * (2 * len(names))]
    for k, lab in PER_FOLD:
        L.append(f"| {lab} | " + " | ".join(fmt_ci(res["systems"][n][f"{k}_{q}"]) for n in names for q in (Q1, Q4))
                 + " |")
    L += ["", "Transferred thresholds (learnt on the other quarter, full / after L1): " + "; ".join(
        f"{LABEL[n]} {q}: {fmt_thr(res['systems'][n][f'thr_tr_full_{q}']['point'])} / "
        f"{fmt_thr(res['systems'][n][f'thr_tr_l1_{q}']['point'])}" for n in names for q in (Q1, Q4)) + ".",
        "fold_B trains on rulings later than its test quarter (soft temporal leak; it does not touch labels).", ""]

    L += ["## Recall by subject and language (pooled)", "",
          "At the transferred threshold (full quarter), then in the top-60 list per quarter. "
          "IT has 1 positive: not measurable.", "",
          "| Group | " + " | ".join(f"{LABEL[n]} @thr" for n in names) + " | "
          + " | ".join(f"{LABEL[n]} top-60" for n in names) + " |", "|---|" + "---|" * (2 * len(names))]
    for g, lab in SUBGROUPS:
        cells = [fmt_ci(res["systems"][n].get(f"recall_tr_full_{g}", {"point": None})) for n in names]
        cells += [fmt_ci(res["systems"][n].get(f"recall_top60_{g}", {"point": None})) for n in names]
        npos = sum(1 for rows in pop.rows.values() for r in rows if r.y and (
            (g.startswith("matiere_") and r.matiere == g[8:]) or (g.startswith("lang_") and r.lang == g[5:])))
        L.append(f"| {lab} ({npos} pos) | " + " | ".join(cells) + " |")
    L.append("")

    L += ["## Sensitivity: without the 25 ambiguous negatives (audit finding M1)", "",
          "| Metric | " + " | ".join(LABEL[n] for n in names) + " | "
          + " | ".join(f"{SHORTNAME[x]} − Rule" for x in others) + " |",
          "|---|" + "---|" * (len(names) + len(others))]
    for k, lab in PRIMARY[:4]:
        L.append(f"| {lab} | " + " | ".join(fmt_ci(sens["systems"][n][k]) for n in names) + " | "
                 + " | ".join(fmt_diff(sens["pairs"][f"{x} - rule"][k]) for x in others) + " |")
    L.append("")

    rep_json, det_json = {}, {}
    if a.source == "bench" and not a.combos:
        L += ["## Repeatability", ""]
        det_lines, det_json = determinism_8b(pop)
        L += det_lines
        rep_lines, rep_json = repetition_section(pop, raw["70b"], m70, M.measure(M.System("rule", raw["rule"], pop)))
        L += rep_lines

    L += ["## How to read this", "",
          "- Thresholds are never chosen on the quarter they are measured on; the valid split selects nothing.",
          "- A tie at a top-k cut counts its expected share of positives. Ties at the F2 optimum take the lowest "
          "threshold (recall first).",
          "- Full-quarter AUC saturates (easy negatives) and is a sanity check only.",
          "- Labels come from Suva's workbook; Q1/2026 negatives are probably noisy (M1): read the sensitivity "
          "table with the main one.", ""]

    a.out_md.parent.mkdir(parents=True, exist_ok=True)
    a.out_md.write_text("\n".join(L), encoding="utf-8")
    out_json = a.out_md.with_suffix(".json")
    out_json.write_text(json.dumps({
        "dataset": M.DATASET, "ids_digest": M.IDS_DIGEST, "verify": verified, "generated": now,
        "git_head": git_head(), "scripts_sha256": scripts, "source": a.source, "provenance": prov,
        "n_boot": a.n_boot, "seed": a.seed, "population": counts, "main": res, "without_ambiguous": sens,
        "verdicts": {n: v[0] for n, v in verdicts.items()}, "repetitions_70b": rep_json,
        "determinism_8b": det_json,
    }, indent=1, default=list) + "\n", encoding="utf-8")
    print(f"wrote {a.out_md} and {out_json}")


if __name__ == "__main__":
    main()
