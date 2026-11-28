"""Command line behind the Make targets (AGENTS.md §6). `make run` is our convention (D-042).

Skeleton: most targets are stubs that print what they will do and exit 0, so that `make run` and CI work
from the first hour. A stub says STUB; replace it when its stage exists. The CLI never does an expensive
action by default: live runs need `--limit N` or `--all`, and offer `--dry-run`.

`.env` and `.env.local` at the repo root are read if present (the environment wins; never committed).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid

from src.llm.config import ConfigError, LLMConfig
from src.llm.served_model import REPO_ROOT

STAGES = [
    ("S0 ingest", "read the committed snapshot (data/public/) and judgements/ (D-051 fields dropped)"),
    ("S1 signals", "compute the example rules and their neighbours, each with its evidence span"),
    ("S2 layer 1", "keep or drop every ruling with its rules, reasons and evidence; recall on Suva's labels (D-073)"),
    ("S3 judgement", "layer 2: Apertus scores every layer-1 candidate, every call traced (D-075, D-076; D-032)"),
    ("S4 score", "compute the 0-100 score, the F2 threshold, the rank and the top-30 cut (D-021, D-046)"),
    ("S5 explain", "write a German explanation for every ruling, selected or not (G5)"),
    ("S6 summarise", "write the German and French summaries of the rulings named by D-047"),
    ("S7 verify", "check every reference, number and acting party against the source"),
    ("S10 export", "export the ranked list with both quarter flags, the plain docket list and the summaries"),
    ("compare", "fail on any divergence with expected/"),
]


def load_dotenv() -> None:
    """Minimal KEY=VALUE reader for .env and .env.local; never overrides the environment."""
    for name in (".env.local", ".env"):
        path = REPO_ROOT / name
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip().removeprefix("export ").strip(), value.strip().strip("'\"")
            if key and value and key not in os.environ:
                os.environ[key] = value


def stub(target: str, would: str) -> int:
    print(f"STUB {target}: would {would}")
    return 0


def run_layer1_stage() -> int:
    """S2: layer 1 on the default profile, then the blocking recall check when Suva's labels are loaded.

    Needs DATABASE_URL and a loaded base dataset (python -m src.ingest registry|base|gold); without them the
    stage is skipped with its reason, never faked.
    """
    if not os.environ.get("DATABASE_URL"):
        print("SKIPPED run S2 layer 1: no DATABASE_URL (make db-up, then python -m src.ingest registry|base|gold)")
        return 0
    from src.db.pg import connect
    from src.layer1.recall import record_recall
    from src.layer1.run import run_layer1, verify_run

    with connect(actor="make-run") as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM corpus.ruling")
            if cur.fetchone()[0] == 0:
                print("SKIPPED run S2 layer 1: corpus.ruling is empty (python -m src.ingest base --parquet PATH)")
                return 0
            cur.execute("SELECT count(*) FROM gold.label")
            has_labels = cur.fetchone()[0] > 0
        out = run_layer1(conn, actor="make-run")
        print(
            f"run S2 layer 1: {out['kept']} of {out['rulings']} kept ({out['profile']}, layer1_filter "
            f"{out['version']}, golden {out['golden']}), "
            f"files in {out['files']}"
        )
        if not has_labels:
            print(
                "SKIPPED run S2 recall: gold.label is empty, so the blocking recall check did not run "
                "(python -m src.ingest gold, then python -m src.layer1 recall)"
            )
        else:
            result = record_recall(conn, out["run_id"])
            missed = {c: v for c, v in result.items() if v["kept"] != v["total"]}
            print("run S2 recall: " + ", ".join(f"{c} {v['kept']}/{v['total']}" for c, v in sorted(result.items())))
            if missed:
                print("run S2 recall FAILED: a labelled ruling is dropped", file=sys.stderr)
                return 1
        # The run proves itself: its files (decisions, ledger, manifest) equal its database rows (F-16, read-only).
        records, problems = verify_run(conn, out["run_id"])
        if problems:
            print(f"run S2 verify FAILED: {len(problems)} differences, first: {problems[0]}", file=sys.stderr)
            return 1
        print(f"run S2 verify: files equal the database ({records} records)")
    return 0


def run_layer2_stage(mode: str, limit: int | None) -> int:
    """S3: layer 2 on layer 1's candidates (docs/LAYER2.md). Skipped with its reason, never faked: without
    DATABASE_URL, without a succeeded layer-1 run, or in replay mode without a replay cache."""
    if not os.environ.get("DATABASE_URL"):
        print("SKIPPED run S3 judgement: no DATABASE_URL")
        return 0
    from src.db.pg import connect
    from src.layer2.run import Layer2RunFailed, run_layer2
    from src.llm.client import DEFAULT_STORE

    if mode == "replay" and not (DEFAULT_STORE / "cache").is_dir():
        print(f"SKIPPED run S3 judgement: replay mode and no cache in {DEFAULT_STORE.relative_to(REPO_ROOT)}")
        return 0
    with connect(actor="make-run") as conn:
        try:
            out = run_layer2(conn, mode=mode, limit=limit, actor="make-run")
        except LookupError as exc:
            print(f"SKIPPED run S3 judgement: {exc}")
            return 0
        except (Layer2RunFailed, ConfigError) as exc:
            print(f"run S3 judgement FAILED: {exc}", file=sys.stderr)
            return 1
    print(
        f"run S3 judgement: {out['judged']} of {out['rulings_in']} judged, {out.get('replay_misses', 0)} without a "
        f"recorded answer ({out['status']}, layer2_judge "
        f"{out['version']}, judge {out['judge']}, {out['mode']}), files in {out['files']}"
    )
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    mode = args.mode
    if mode == "live":
        if not (args.all or args.limit):
            print("run --mode live: pass --limit N or --all (no expensive action by default)", file=sys.stderr)
            return 2
        try:
            cfg = LLMConfig.from_env("live")
        except ConfigError as exc:
            print(f"run: {exc}", file=sys.stderr)
            return 2
        print(f"run: mode LIVE, model {cfg.name} (small: {cfg.name_small}), scope {args.limit or 'all'}")
    else:
        print("run: mode REPLAY (no LLM_* needed, D-032); every output will be labelled LIVE or REPLAY")
    for name, what in STAGES:
        if args.dry_run:
            print(f"  [dry-run] {name}: {what}")
        elif name == "S2 layer 1":
            status = run_layer1_stage()
            if status:
                return status
        elif name == "S3 judgement":
            status = run_layer2_stage(mode, None if args.all else args.limit)
            if status:
                return status
        else:
            stub(f"run {name}", what)
    print("run: S2 and S3 implemented; the other stages are stubs (docs/STATE.md lists them)")
    return 0


def cmd_warmup(args: argparse.Namespace) -> int:
    """Warm the large model before a demo or a measurement: 3 short calls, never cached (random nonce)."""
    from src.llm.client import LLMError, client_from_env

    try:
        client = client_from_env("live")
    except ConfigError as exc:
        print(f"warmup: {exc}", file=sys.stderr)
        return 2
    if args.dry_run:
        print(f"warmup: would send 3 short calls to {client.cfg.name}")
        return 0
    for i in range(3):
        msgs = [{"role": "user", "content": f"[{uuid.uuid4().hex}] Reply with the single word: ok"}]
        t0 = time.perf_counter()
        try:
            client.chat(msgs, max_tokens=3, prompt_version="warmup")
        except LLMError as exc:
            print(f"warmup: call {i + 1} failed: {exc}", file=sys.stderr)
            return 1
        print(f"warmup: call {i + 1} {time.perf_counter() - t0:.2f} s")
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["smoke-llm"]:  # pass every flag through to the probe (argparse cannot, after a subcommand)
        from src.llm import probe

        return probe.main(argv[1:])
    ap = argparse.ArgumentParser(prog="python -m src.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="end-to-end pipeline (make run)")
    run.add_argument("--mode", choices=["replay", "live"], default="replay")
    run.add_argument("--limit", type=int)
    run.add_argument("--all", action="store_true")
    run.add_argument("--dry-run", action="store_true")
    sub.add_parser("smoke-llm", help="gateway probe (src/llm/probe.py); flags go to the probe")
    warm = sub.add_parser("warmup", help="warm the large model")
    warm.add_argument("--dry-run", action="store_true")
    stubs = {
        "serve": "serve the API and the UI (FastAPI, docs/agents/ui.md)",
        "crawl": "fetch Neuheiten lists 1 Oct 2025 to 15 Sep 2026 and ruling pages, >= 2 s apart (crawl brief)",
        "refit": "rerun the scoring with the current labels, expert corrections included (D-021)",
        "eval": "run the evaluation suites on public data and write results/*.json (docs/EVAL.md)",
        "eval-private": "measure on Suva's data, commit aggregate numbers only (D-031)",
        "claims": "regenerate every number quoted in README.md, technical_report.md and the deck from results/",
    }
    for name, what in stubs.items():
        p = sub.add_parser(name)
        p.add_argument("--limit", type=int)
        p.add_argument("--all", action="store_true")
        p.add_argument("--dry-run", action="store_true")
        p.set_defaults(would=what)
    args = ap.parse_args(argv)
    if args.cmd == "run":
        return cmd_run(args)
    if args.cmd == "warmup":
        return cmd_warmup(args)
    return stub(args.cmd, args.would)


if __name__ == "__main__":
    sys.exit(main())
