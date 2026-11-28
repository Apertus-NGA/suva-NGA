"""The Suva Scout scorer on the six-schema database (D-094).

python -m src.scorer export --from-url URL [--out data/derived/scorer/run.json] [--mode LIVE|REPLAY]
python -m src.scorer load [--file data/derived/scorer/run.json] [--profile default]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from src.db import pg
from src.scorer.export import export
from src.scorer.load import StoredRunMismatch, load

DEFAULT_FILE = Path("data/derived/scorer/run.json")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.scorer", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    exp = sub.add_parser("export", help="write a stored scorer run to a file (read-only on the source)")
    exp.add_argument("--from-url", default=os.environ.get("SCORER_SOURCE_URL"), help="database the scorer ran on")
    exp.add_argument("--out", type=Path, default=DEFAULT_FILE)
    exp.add_argument("--mode", choices=["LIVE", "REPLAY"], default="LIVE", help="how the stored run called Apertus")
    ld = sub.add_parser("load", help="load a stored scorer run as layer 2 and ranking")
    ld.add_argument("--file", type=Path, default=DEFAULT_FILE)
    ld.add_argument("--profile", default="default")
    args = ap.parse_args(argv)

    if args.cmd == "export":
        if not args.from_url:
            print("export: name the source database (--from-url or SCORER_SOURCE_URL)", file=sys.stderr)
            return 2
        stored = export(args.from_url, args.out, args.mode)
        promoted = sum(1 for r in stored.rulings if r.promoted)
        print(
            json.dumps(
                {
                    "file": str(args.out),
                    "source_run_id": stored.source_run_id,
                    "scorer": stored.scorer,
                    "rulings": len(stored.rulings),
                    "promoted": promoted,
                },
                indent=2,
            )
        )
        return 0
    if not args.file.is_file():
        print(f"load: no file {args.file} (python -m src.scorer export)", file=sys.stderr)
        return 2
    try:
        with pg.connect() as conn:
            print(json.dumps(load(conn, args.file, args.profile), indent=2))
    except StoredRunMismatch as exc:
        print(f"load: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
