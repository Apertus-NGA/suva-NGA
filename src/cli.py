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
    ("S2 net", "drop only the clearly out-of-domain, each with a reason code (optional, D-021)"),
    ("S3 judgement", "ask Apertus for a judgement per candidate (live slice or replay, D-032)"),
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
        else:
            stub(f"run {name}", what)
    print("run: skeleton only, no stage implemented yet (docs/STATE.md lists the stubs)")
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
