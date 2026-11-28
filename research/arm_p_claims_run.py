"""Arm P, step 1: the harnessed Apertus readings and their unharnessed twins, through the shared client.

Reads the accident / military / disability rulings layer 1 keeps (the rulings the pipeline asks Apertus about),
by default those of the two listed quarters. Every reading of ``src.triage.claims`` is asked in each of its arms.
Answers are cached by the client (data/derived/llm). Output, one row per docket, git-ignored (D-031):
data/derived/triage_claims/<reading>_<size>.parquet

Run: uv run --frozen python research/arm_p_claims_run.py --size small [--readings practice:zero locate ...]
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.llm.client import client_from_env  # noqa: E402
from src.triage import claims as cl  # noqa: E402
from src.triage import pipeline  # noqa: E402
from src.triage import variants as vr  # noqa: E402
from suva_data import db  # noqa: E402

OUT = ROOT / "data" / "derived" / "triage_claims"
LISTED = sorted({q for fold in vr.FOLDS for q in fold})


def readers() -> dict:
    out = {
        f"{name}:{arm}": (lambda client, text, size, c=claim, a=arm: cl.read_claim(client, text, c, a, size))
        for name, claim in cl.CLAIMS.items()
        for arm in cl.ARMS
    }
    out["locate"] = lambda client, text, size: cl.read_locate(client, text, size)
    out["article:zero"] = lambda client, text, size: cl.read_article(client, text, "zero", size)
    out["article:cited"] = lambda client, text, size: cl.read_article(client, text, "cited", size)
    return out


def main(argv: list[str] | None = None) -> int:
    all_readers = readers()
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", choices=("small", "large"), required=True)
    ap.add_argument("--readings", nargs="*", default=sorted(all_readers), choices=sorted(all_readers))
    ap.add_argument("--all-quarters", action="store_true", help="every kept core ruling, not only the listed quarters")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)

    with db.connect() as conn:
        result = pipeline.run(conn, client_from_env("replay"), workers=5)
    core = [r for r in result["kept"] if r["signals"]["area"] in pipeline.CORE_AREAS]
    if not args.all_quarters:
        core = [r for r in core if r["quarter"] in LISTED]
    if args.limit:
        core = core[: args.limit]
    client = client_from_env("live")
    OUT.mkdir(parents=True, exist_ok=True)
    suffix = ("_all" if args.all_quarters else "") + ("_partial" if args.limit else "")
    for name in args.readings:
        reader, t0 = all_readers[name], time.time()
        with ThreadPoolExecutor(args.workers) as pool:
            answers = list(pool.map(lambda r, f=reader: f(client, r["text"], args.size), core))
        rows = [{"docket": r["docket"], "quarter": r["quarter"], **a} for r, a in zip(core, answers, strict=True)]
        df = pd.DataFrame(rows)
        path = OUT / f"{name.replace(':', '_')}_{args.size}{suffix}.parquet"
        df.to_parquet(path, index=False)
        key = "p" if "p" in df else "consideration" if name == "locate" else "article"
        missing, took = int(df[key].isna().sum()), f"{time.time() - t0:.0f}s"
        print(f"{name} {args.size}: {len(df)} rulings in {took}, {missing} without an answer", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
