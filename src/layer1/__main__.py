"""Layer 1 commands (docs/LAYER1.md §6). Needs DATABASE_URL.

python -m src.layer1 run [--profile default] [--population CODE]   decide every ruling, files then DB
python -m src.layer1 recall [--run RUN_ID] [--profile default]     blocking recall on Suva's labels
python -m src.layer1 report --run A [--run B] [--out PATH]         aggregate validation report
python -m src.layer1 golden --parquet PATH [--write]                certified decisions, in memory (no DB)
python -m src.layer1 verify --run RUN_ID [--runs-dir PATH]          the run's files equal its DB rows (read-only)
python -m src.layer1 validate --baseline-profile P0 --profile P1 [--out PATH]   run both, recall, compare
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.db.pg import ROOT, connect
from src.layer1.recall import compare, latest_run, record_recall, run_summary, validate, write_report
from src.layer1.run import RUNS_DIR, run_layer1, verify_run


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
    gold = sub.add_parser("golden")
    gold.add_argument("--parquet", required=True, type=Path)
    gold.add_argument("--write", action="store_true", help="write the expected file of a version that has none")
    ver = sub.add_parser("verify")
    ver.add_argument("--run", required=True)
    ver.add_argument("--runs-dir", type=Path, default=RUNS_DIR)
    val = sub.add_parser("validate")
    val.add_argument("--baseline-profile", required=True)
    val.add_argument("--profile", required=True)
    val.add_argument("--out", default=str(ROOT / "results" / "layer1_validation.json"))
    val.add_argument("--runs-dir", type=Path, default=RUNS_DIR)
    args = ap.parse_args(argv)

    if args.cmd == "golden":
        from src.layer1.golden import check

        problems = check(args.parquet, write=args.write)
        for problem in problems:
            print(f"golden: {problem}", file=sys.stderr)
        print("golden: OK (certified decisions unchanged)" if not problems else "golden: FAILED")
        return 1 if problems else 0

    with connect(actor="layer1-cli") as conn:
        if args.cmd == "verify":
            conn.read_only = True
            read, problems = verify_run(conn, args.run, args.runs_dir)
            for problem in problems[:20]:
                print(f"verify: {problem}", file=sys.stderr)
            if len(problems) > 20:
                print(f"verify: ... and {len(problems) - 20} more", file=sys.stderr)
            if problems:
                print(f"verify: FAILED ({len(problems)} differences between the files and the database)")
                return 1
            print(f"verify: OK ({read} records equal their assessments and ledgers; files match the manifest)")
            return 0
        if args.cmd == "validate":
            report = validate(conn, args.baseline_profile, args.profile, runs_dir=args.runs_dir)
            write_report(Path(args.out), report)
            v = report["validation"]
            for role in ("baseline", "candidate"):
                r = v[role]
                print(f"{role:9} {r['profile']}: run {r['run_id']}, {r['layer1_filter']}, golden {r['golden']}")
            print(
                f"scope changes: potentially->out_of_scope {v['potentially_to_out_of_scope']}, "
                f"out_of_scope->potentially {v['out_of_scope_to_potentially']}"
            )
            for role, cohorts in v["recall"].items():
                print(
                    f"recall {role}: " + ", ".join(f"{c} {x['kept']}/{x['total']}" for c, x in sorted(cohorts.items()))
                )
            if v["note"]:
                print(f"note: {v['note']}")
            for failure in v["failures"]:
                print(f"validate: {failure}", file=sys.stderr)
            print(f"wrote {args.out}")
            print("validate: OK" if v["passed"] else "validate: FAILED")
            return 0 if v["passed"] else 1
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
