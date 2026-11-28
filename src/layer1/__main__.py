"""Layer 1 commands (docs/LAYER1.md §6). Needs DATABASE_URL.

python -m src.layer1 run [--profile default] [--population CODE]   decide every ruling, files then DB
python -m src.layer1 recall [--run RUN_ID] [--profile default]     blocking recall on Suva's labels
python -m src.layer1 report --run A [--run B] [--out PATH]         aggregate validation report
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.db.pg import ROOT, connect
from src.layer1.recall import compare, latest_run, record_recall, run_summary, write_report
from src.layer1.run import run_layer1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.layer1", description="Layer 1, the first filter before Apertus.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--profile", default="default")
    run.add_argument("--population")
    rec = sub.add_parser("recall")
    rec.add_argument("--run")
    rec.add_argument("--profile", default="default")
    rep = sub.add_parser("report")
    rep.add_argument("--run", action="append", required=True)
    rep.add_argument("--out", default=str(ROOT / "results" / "layer1_validation.json"))
    args = ap.parse_args(argv)

    with connect(actor="layer1-cli") as conn:
        if args.cmd == "run":
            print(
                json.dumps(
                    run_layer1(conn, profile=args.profile, population=args.population, actor="layer1-cli"), indent=2
                )
            )
            return 0
        if args.cmd == "recall":
            with conn.cursor() as cur:
                run_id = args.run or latest_run(cur, args.profile)
            result = record_recall(conn, run_id)
            failed = False
            for cohort, values in result.items():
                print(f"{cohort:20} {values['kept']}/{values['total']} kept")
                if values["kept"] != values["total"]:
                    failed = True
                    print(f"  dropped or not assessed: {', '.join(values['missed'])}", file=sys.stderr)
            print("recall: OK" if not failed else "recall: FAILED (a labelled ruling is dropped)")
            return 1 if failed else 0
        with conn.cursor() as cur:
            runs = [run_summary(cur, r) for r in args.run]
            report = {"runs": runs}
            if len(args.run) == 2:
                report["scope_changes"] = compare(cur, args.run[0], args.run[1])
        write_report(Path(args.out), report)
        print(f"wrote {args.out}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
