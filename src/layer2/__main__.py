"""Layer 2 commands (docs/LAYER2.md). Needs DATABASE_URL; live mode needs LLM_* (G3).

python -m src.layer2 run [--mode replay|live] [--population CODE] [--limit N | --all] [--store PATH]
                         [--kind layer2|eval] [--repetition N] [--layer1-run RUN_ID] [--workers N]
python -m src.layer2 validate --data-root DIR --manifest FILE [--bench DIR] [--run RUN_ID] [--write-expected]
                              [--out PATH]   (default results/layer2_validation.json, the committed report)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.db.pg import connect
from src.layer2.run import Layer2RunFailed, run_layer2
from src.layer2.validate import ValidationFailed, run_report, validate
from src.llm.client import DEFAULT_STORE
from src.llm.config import ConfigError


def main(argv: list[str] | None = None) -> int:
    from src.cli import load_dotenv

    load_dotenv()  # .env and .env.local, as make run does; the environment wins
    ap = argparse.ArgumentParser(prog="python -m src.layer2", description="Layer 2, the Apertus relevance judge.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--profile", default="default")
    run.add_argument("--population", action="append", help="population code; repeat for several")
    run.add_argument("--mode", choices=["replay", "live"], default="replay")
    lim = run.add_mutually_exclusive_group()
    lim.add_argument("--limit", type=int)
    lim.add_argument("--all", action="store_true")
    run.add_argument("--store", type=Path, default=DEFAULT_STORE, help="client cache and call log")
    run.add_argument("--kind", choices=["layer2", "eval"], default="layer2")
    run.add_argument("--repetition", type=int, default=0)
    run.add_argument("--layer1-run")
    run.add_argument("--workers", type=int)
    run.add_argument("--max-failed-share", type=float)
    val = sub.add_parser("validate")
    val.add_argument("--profile", default="default")
    val.add_argument("--data-root", type=Path, required=True)
    val.add_argument("--manifest", type=Path, required=True)
    val.add_argument("--bench", type=Path, help="benchmark folder with fold_*/rep000.jsonl (score parity)")
    val.add_argument("--run")
    val.add_argument("--write-expected", action="store_true")
    val.add_argument("--out", type=Path, help="aggregate report (default results/layer2_validation.json)")
    rep = sub.add_parser("report", help="aggregates of one run (no Suva label) for results/")
    rep.add_argument("--run", required=True)
    rep.add_argument("--out", type=Path)
    args = ap.parse_args(argv)

    if args.cmd == "run" and args.mode == "live" and not (args.limit or args.all):
        print("run --mode live: pass --limit N or --all (no expensive action by default)", file=sys.stderr)
        return 2
    with connect(actor="layer2-cli") as conn:
        try:
            if args.cmd == "run":
                out = run_layer2(
                    conn,
                    profile=args.profile,
                    population=args.population,
                    mode=args.mode,
                    limit=args.limit,
                    store=args.store,
                    repetition=args.repetition,
                    kind=args.kind,
                    layer1_run=args.layer1_run,
                    workers=args.workers,
                    actor="layer2-cli",
                    max_failed_share=args.max_failed_share,
                )
            elif args.cmd == "report":
                out = run_report(conn, args.run)
                if args.out:
                    args.out.write_text(
                        json.dumps(out, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
                    )
            else:
                out = validate(
                    conn,
                    data_root=args.data_root,
                    manifest_path=args.manifest,
                    bench_dir=args.bench,
                    run_id=args.run,
                    profile=args.profile,
                    write_expected=args.write_expected,
                    **({"results_path": args.out} if args.out else {}),
                )
        except (Layer2RunFailed, ValidationFailed, ConfigError, LookupError) as exc:
            print(f"layer2 {args.cmd}: {exc}", file=sys.stderr)
            return 1
    print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
