"""Repeated zero-shot benchmark of base Apertus on suva-ft-v3 (docs/FINETUNE.md §6). No training, so no epochs.

Every call goes through src/llm/ (AGENTS.md G2): concurrency cap, timeout, one error classifier with retries,
served-model check, the `llm_calls` log and the cache, in a store dedicated to this benchmark
(`<out>/../llm_store/` by default, under data/derived/, git-ignored).

Prompt, parameters and score are those of 03_keera_baseline.py, unchanged: the dataset's messages, T=0,
max_tokens=1, logprobs with top_logprobs=20; score = P(Ja) / (P(Ja) + P(Nein)) on the first output token, where
P(Ja) sums the top-20 tokens 'ja'/'j' and P(Nein) the tokens 'nein'/'nei'/'ne' (case and spaces ignored).
New: logprob(Ja), logprob(Nein), the logit, the raw top-20, the served model and the token usage per ruling.

A failed call fails the run (no silent drop): the repetition file is not written. Rerunning resumes: finished
repetitions are skipped and calls already answered come back from the store's cache (marked REPLAY).
Repetition i is sent with `repetition = rep_offset + i` (part of the cache key), so each one is a fresh call.

Usage (needs LLM_NAME, LLM_NAME_SMALL, LLM_BASE_URL, LLM_API_KEY in the environment; LLM_CONCURRENCY <= 5):
  uv run --frozen python -I experiments/finetune/scripts/06_benchmark_repeat.py \
      --data-root data/derived/finetune/suva-ft-v3 \
      --manifest experiments/finetune/manifests/suva-ft-v3/MANIFEST_suva_ft_v3.json \
      --model apertus-v1-5-8b --subset all --reps 3 --all --out data/derived/finetune/bench_v3/8b_all
  ... --dry-run          prints the plan, no call, no key needed
  ... --summary-only     recomputes run_summary.json from the stored repetitions
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import subprocess
import sys
import time
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))  # python -I drops the working directory: import src.llm from the repo root

PROMPT_VERSION = "suva-ft-v3/zero-shot-ja-nein"  # the dataset's own prompt; part of the cache key
SLOT_MAX = 16  # AGENTS.md G2: concurrent calls across all team machines stay <= 16
JA, NEIN = ("ja", "j"), ("nein", "nei", "ne")
PARAMS = {"max_tokens": 1, "logprobs": True, "top_logprobs": 20, "first_token_only": True}


class ScoreError(RuntimeError):
    """The answer cannot give a score (no Ja/Nein in the top-20, no logprobs): fails the run."""


def read_first_token(logprobs: dict | None) -> dict:
    """Score and log-probabilities from the first token's top_logprobs, as 03_keera_baseline.py computes them."""
    try:
        top = logprobs["content"][0]["top_logprobs"]
    except (TypeError, KeyError, IndexError) as exc:
        raise ScoreError(f"no top_logprobs in the answer: {exc!r}") from exc
    if not top:
        raise ScoreError("empty top_logprobs")
    p_ja = p_nein = 0.0
    for t in top:
        tok = (t.get("token") or "").strip().lower()
        p = math.exp(t.get("logprob", -99))
        if tok in JA:
            p_ja += p
        elif tok in NEIN:
            p_nein += p
    if p_ja + p_nein <= 0:
        raise ScoreError("neither Ja nor Nein in the top-20")
    lp_ja = math.log(p_ja) if p_ja > 0 else None
    lp_nein = math.log(p_nein) if p_nein > 0 else None
    return {
        "p_ja": p_ja, "p_nein": p_nein, "score": p_ja / (p_ja + p_nein), "mass": p_ja + p_nein,
        "logprob_ja": lp_ja, "logprob_nein": lp_nein,
        "logit": (lp_ja - lp_nein) if lp_ja is not None and lp_nein is not None else None,
        "top20_floor": min(t.get("logprob", -99) for t in top),  # bound for a token absent from the top-20
        "top20": [[t.get("token"), t.get("logprob")] for t in top],
    }


def score_one(client, size: str, ex: dict, repetition: int) -> dict:
    """One ruling, one call through src/llm/. Raises on any failure."""
    res = client.chat(ex["prompt"], size=size, prompt_version=PROMPT_VERSION, repetition=repetition, **PARAMS)
    row = {**ex["meta"], "label": ex["completion"][0]["content"], "repetition": repetition}
    row.update(read_first_token(res.logprobs))
    row.update({"served_model": res.served_model, "mode": res.mode, "latency_s": res.latency_s,
                "attempts": res.attempts, "prompt_tokens": res.usage.get("prompt_tokens"),
                "completion_tokens": res.usage.get("completion_tokens")})
    return row


def run_rep(client, size: str, rows: list[dict], repetition: int, workers: int, path: Path) -> dict:
    """Score every row; write the file only if every call succeeded. Returns the repetition's meta."""
    t0, started = time.time(), datetime.now(UTC).isoformat(timespec="seconds")
    ex = ThreadPoolExecutor(workers)
    futs = [ex.submit(score_one, client, size, r, repetition) for r in rows]
    done, _ = wait(futs, return_when=FIRST_EXCEPTION)
    failed = [f for f in done if f.exception() is not None]
    if failed:
        ex.shutdown(wait=True, cancel_futures=True)
        raise failed[0].exception()
    ex.shutdown(wait=True)
    res = [f.result() for f in futs]  # same order as the dataset
    tmp = path.with_suffix(".part")
    with tmp.open("w", encoding="utf-8") as fh:
        for r in res:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(path)
    meta = {
        "repetition": repetition, "n": len(res), "started": started,
        "finished": datetime.now(UTC).isoformat(timespec="seconds"), "wall_s": round(time.time() - t0, 1),
        "n_live": sum(r["mode"] == "LIVE" for r in res), "n_replay": sum(r["mode"] == "REPLAY" for r in res),
        "prompt_tokens": sum(r["prompt_tokens"] or 0 for r in res),
        "completion_tokens": sum(r["completion_tokens"] or 0 for r in res),
        "served_models": sorted({r["served_model"] or "?" for r in res}),
        "attempts_gt_1": sum((r["attempts"] or 0) > 1 for r in res),
        "workers": workers,
        "latency_p50_s": _pct([r["latency_s"] for r in res if r["latency_s"] is not None], 0.5),
        "latency_p95_s": _pct([r["latency_s"] for r in res if r["latency_s"] is not None], 0.95),
    }
    path.with_suffix(".meta.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
    return meta


def _pct(v: list[float], q: float) -> float | None:
    v = sorted(v)
    return v[min(len(v) - 1, int(q * len(v)))] if v else None


def load_rows(path: Path, subset: str) -> list[dict]:
    rows = [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]
    if subset == "all":
        return rows
    if subset == "couche1":
        return [r for r in rows if r["meta"].get("couche1")]
    return [r for r in rows if r["meta"]["kind"] in ("positive", "hard_negative")]  # pos_hard


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_test_files(manifest: Path, data_root: Path, folds: list[str]) -> str:
    """The test files must be the frozen ones (run verify_dataset.py for the full check). Returns the ids digest."""
    m = json.loads(manifest.read_text(encoding="utf-8"))
    for fold in folds:
        info = m["splits"][f"{fold}/test"]
        got = sha256(data_root / info["file"])
        if got != info["sha256"]:
            sys.exit(f"{fold}/test.jsonl is not the frozen file ({got[:12]}… != {info['sha256'][:12]}…): stop")
    return m["ids_digest_sha256"]


def git_head() -> str:
    try:
        return subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "?"


def summarise_run(out: Path) -> dict:
    """Determinism, spread and cost of the stored repetitions (metrics are in 07_report_v3.py)."""
    summary = {}
    for fdir in sorted(p for p in out.iterdir() if p.is_dir() and p.name.startswith("fold_")):
        reps = sorted(fdir.glob("rep*.jsonl"))
        metas = [json.loads(p.with_suffix(".meta.json").read_text()) for p in reps
                 if p.with_suffix(".meta.json").is_file()]
        scores: dict[str, list[float]] = {}
        for p in reps:
            for line in p.open(encoding="utf-8"):
                r = json.loads(line)
                scores.setdefault(r["decision_id"], []).append(r["score"])
        spread = sorted(max(v) - min(v) for v in scores.values()) if scores else []
        summary[fdir.name] = {
            "n_reps": len(reps), "n_rulings": len(scores),
            "identical_across_reps": sum(s == 0 for s in spread), "max_spread": spread[-1] if spread else None,
            "calls": sum(m["n"] for m in metas), "live_calls": sum(m["n_live"] for m in metas),
            "prompt_tokens": sum(m["prompt_tokens"] for m in metas),
            "completion_tokens": sum(m["completion_tokens"] for m in metas),
            "wall_s": round(sum(m["wall_s"] for m in metas), 1),
            "served_models": sorted({s for m in metas for s in m["served_models"]}),
        }
    (out / "run_summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", type=Path)
    ap.add_argument("--manifest", type=Path)
    ap.add_argument("--model", help="must equal LLM_NAME (sent as the large model) or LLM_NAME_SMALL")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--store", type=Path, help="src/llm store (cache + llm_calls); default <out>/../llm_store")
    ap.add_argument("--folds", default="fold_A,fold_B")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--rep-offset", type=int, default=0, help="repetition id of the first repetition")
    ap.add_argument("--subset", choices=["all", "couche1", "pos_hard"], default="all")
    ap.add_argument("--workers", type=int, help="default LLM_CONCURRENCY (4); capped by the client")
    ap.add_argument("--gateway-label", default="Keera", help="written in the run metadata (never the URL)")
    ap.add_argument("--slot-concurrency", type=int,
                    help=f"lead-approved slot: concurrent calls above a member's share, at most {SLOT_MAX} (G2 team "
                         "ceiling); recorded in the run metadata")
    lim = ap.add_mutually_exclusive_group()
    lim.add_argument("--limit", type=int, help="first N rulings per fold (smoke test)")
    lim.add_argument("--all", action="store_true", help="every ruling of the subset")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--summary-only", action="store_true")
    a = ap.parse_args()

    if a.summary_only:
        print(json.dumps(summarise_run(a.out), indent=1))
        return
    if not (a.limit or a.all):
        sys.exit("an expensive run needs --limit N or --all (AGENTS.md §6); --dry-run shows the plan")
    if not (a.data_root and a.manifest and a.model):
        sys.exit("--data-root, --manifest and --model are required")
    folds = a.folds.split(",")
    digest = check_test_files(a.manifest, a.data_root, folds)
    plan = {f: len(load_rows(a.data_root / f / "test.jsonl", a.subset)[: a.limit or None]) for f in folds}
    calls = sum(plan.values()) * a.reps
    if a.dry_run:
        print(json.dumps({"model": a.model, "subset": a.subset, "reps": a.reps, "rulings_per_fold": plan,
                          "calls": calls, "repetition_ids": [a.rep_offset, a.rep_offset + a.reps - 1]}, indent=1))
        return

    from src.llm.client import LLMClient
    from src.llm.config import LLMConfig

    cfg = LLMConfig.from_env("live")  # fails fast with a clear message if a variable is missing (G3)
    if a.model == cfg.name:
        size = "large"
    elif a.model == cfg.name_small:
        size = "small"
    else:
        sys.exit(f"--model {a.model!r} is neither LLM_NAME ({cfg.name!r}) nor LLM_NAME_SMALL ({cfg.name_small!r})")
    if a.slot_concurrency:
        if not 1 <= a.slot_concurrency <= SLOT_MAX:
            sys.exit(f"--slot-concurrency must be 1..{SLOT_MAX}: G2 caps the whole team at {SLOT_MAX} concurrent calls")
        # D-030 caps a member at 5 (src/llm/config.py); a slot the lead announces may use up to the team ceiling
        cfg = dataclasses.replace(cfg, concurrency=a.slot_concurrency)
    workers = min(a.workers or cfg.concurrency, cfg.concurrency)
    store = a.store or (a.out.parent / "llm_store")
    client = LLMClient(cfg, store_dir=store)
    a.out.mkdir(parents=True, exist_ok=True)
    run_meta = {
        "dataset": "suva-ft-v3", "ids_digest": digest, "model": a.model, "gateway": a.gateway_label,
        "subset": a.subset, "reps": a.reps, "rep_offset": a.rep_offset, "limit": a.limit, "workers": workers,
        "slot_concurrency": a.slot_concurrency,
        "prompt_version": PROMPT_VERSION, "params": PARAMS, "git_head": git_head(),
        "script_sha256": sha256(Path(__file__)), "started": datetime.now(UTC).isoformat(timespec="seconds"),
        "note": "experiments/ scripts are untracked until the lead's go: script_sha256 identifies the code",
    }
    (a.out / "run_args.json").write_text(json.dumps(run_meta, indent=1) + "\n", encoding="utf-8")
    with (a.out / "invocations.jsonl").open("a", encoding="utf-8") as fh:  # every resume, with its settings
        fh.write(json.dumps(run_meta) + "\n")
    try:
        for fold in folds:
            rows = load_rows(a.data_root / fold / "test.jsonl", a.subset)[: a.limit or None]
            fdir = a.out / fold
            fdir.mkdir(exist_ok=True)
            for i in range(a.reps):
                path = fdir / f"rep{i:03d}.jsonl"
                if path.is_file() and sum(1 for _ in path.open()) == len(rows):
                    continue
                meta = run_rep(client, size, rows, a.rep_offset + i, workers, path)
                print(json.dumps({"fold": fold, "rep": i, **{k: meta[k] for k in
                                  ("n", "n_live", "n_replay", "wall_s", "served_models")}}), flush=True)
    finally:
        client.close()
    print(json.dumps(summarise_run(a.out), indent=1))


if __name__ == "__main__":
    main()
