"""Layer 3 commands (docs/LAYER3.md). Needs DATABASE_URL; live mode needs LLM_* (G3).

python -m src.layer3 run [--mode replay|live] [--population CODE] [--limit N] [--dockets D ...] [--no-requests]
                         [--store PATH] [--workers N]
python -m src.layer3 requests [--mode replay|live] [--store PATH]     the pending summary requests only
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.db.pg import DatabaseNotConfigured, connect
from src.layer3.run import DEFAULT_LIMIT, DEFAULT_POPULATION, Layer3RunFailed, run_layer3
from src.llm.client import DEFAULT_STORE
from src.llm.config import ConfigError


def main(argv: list[str] | None = None) -> int:
    from src.cli import load_dotenv

    load_dotenv()  # .env and .env.local, as make run does; the environment wins
    ap = argparse.ArgumentParser(prog="python -m src.layer3", description="Layer 3, the German and French summaries.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="the top rulings by layer-2 score, plus the pending summary requests")
    req = sub.add_parser("requests", help="the pending summary requests only (ops.user_request)")
    for p in (run, req):
        p.add_argument("--profile", default="default")
        p.add_argument("--mode", choices=["replay", "live"], default="replay")
        p.add_argument("--store", type=Path, default=DEFAULT_STORE, help="client cache and call log")
        p.add_argument("--workers", type=int, default=1)
    run.add_argument("--population", default=DEFAULT_POPULATION, help="population code ('' for the whole run)")
    run.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="rulings by score (default 10, Q-17)")
    run.add_argument("--dockets", nargs="+", help="summarise these dockets instead of the top by score")
    run.add_argument("--no-requests", action="store_true", help="leave the pending summary requests")
    args = ap.parse_args(argv)
    kwargs = dict(mode=args.mode, profile=args.profile, store=args.store, workers=args.workers, actor="layer3-cli")
    if args.cmd == "run":
        kwargs |= dict(
            population=args.population or None,
            limit=args.limit,
            dockets=args.dockets,
            requests=not args.no_requests,
        )
    else:
        kwargs |= dict(limit=0, requests=True)
    try:
        conn = connect(actor="layer3-cli")
    except DatabaseNotConfigured as exc:
        print(f"layer3: {exc}", file=sys.stderr)
        return 2
    with conn:
        try:
            out = run_layer3(conn, **kwargs)
        except LookupError as exc:
            print(f"layer3: nothing done: {exc}", file=sys.stderr)
            return 0 if args.cmd == "requests" else 1
        except (Layer3RunFailed, ConfigError) as exc:
            print(f"layer3 FAILED: {exc}", file=sys.stderr)
            return 1
    print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
