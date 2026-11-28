"""Arm O, step 2: read one Apertus feature for every ruling layer 1 keeps, through the shared client.

The rulings come from the replayed pipeline (no relevance reading is re-asked). Answers are cached by the client
(data/derived/llm), so a rerun costs nothing. Output, one row per docket, git-ignored (D-031):
data/derived/triage_features/<feature>_<size>.parquet

Run: uv run --frozen python research/arm_o_features_run.py --feature topic --size small [--quarters "2025 Q4"]
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
from src.triage import (  # noqa: E402
    evidence,
    features,
    pipeline,  # noqa: E402
)
from suva_data import db  # noqa: E402

OUT = ROOT / "data" / "derived" / "triage_features"
READERS = {
    "topic": lambda client, text, size: features.read_topic(client, text, size),
    "statement": lambda client, text, size: evidence.read_statement(client, text, size),
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--feature", choices=sorted(READERS), required=True)
    ap.add_argument("--size", choices=("small", "large"), required=True)
    ap.add_argument("--quarters", nargs="*", default=None, help="decision quarters; default: every kept ruling")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)

    with db.connect() as conn:
        result = pipeline.run(conn, client_from_env("replay"), workers=5)
    kept = result["kept"]
    if args.quarters:
        kept = [r for r in kept if r["quarter"] in args.quarters]
    if args.limit:
        kept = kept[: args.limit]
    client = client_from_env("live")
    reader = READERS[args.feature]
    t0 = time.time()
    with ThreadPoolExecutor(args.workers) as pool:
        answers = list(pool.map(lambda r: reader(client, r["text"], args.size), kept))
    rows = [{"docket": r["docket"], "quarter": r["quarter"], **a} for r, a in zip(kept, answers, strict=True)]
    df = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    suffix = "" if not (args.quarters or args.limit) else "_partial"
    path = OUT / f"{args.feature}_{args.size}{suffix}.parquet"
    df.to_parquet(path, index=False)
    empty = int(df.filter(like="f_").isna().all(axis=1).sum())
    took = f"{time.time() - t0:.0f}s"
    print(f"{args.feature} {args.size}: {len(df)} rulings in {took}, {empty} without an answer -> {path}")
    if "answer" in df:
        print(df["answer"].value_counts(dropna=False).to_dict())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
