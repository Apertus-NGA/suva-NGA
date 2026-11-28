"""Command line behind the Make targets (AGENTS.md §6). `make run` is our convention (D-042).

`run` executes, in order, each stage printing one line labelled LIVE or REPLAY:
    S0 db         start the local compose database when DATABASE_URL points at it, connect, apply migrations
    S1 ingest     only when `rulings` is empty: `suva_data pull` (if data/snapshot is missing) then `build`
    S2 triage     layer 1 + layer 2 (src/triage/pipeline.py); a full run writes the predictions
    S3 summarise  the German and French fiches of the top N suspected-relevant rulings without a summary
    S4 serve      the API and the UI on 127.0.0.1:8000 (skipped with --no-serve, `make run SERVE=0`)
A stage that cannot run stops the run with its name and the reason, and the exit code is non-zero.

The CLI never does an expensive action by default: live runs need `--limit N` (a smoke run: triage of the
first N rulings, nothing written, at most N summaries) or `--all`, and `--dry-run` shows the plan.
Replay mode calls no gateway: it reads only cached answers (data/derived/llm) and fails on a missing one.
Other targets (crawl, refit, eval, eval-private, claims) are still stubs that print STUB.

`.env` and `.env.local` at the repo root are read if present (the environment wins; never committed).
"""

from __future__ import annotations

import argparse
import inspect
import os
import shutil
import subprocess
import sys
import time
import uuid
from urllib.parse import urlsplit

from src.llm.config import ConfigError, LLMConfig
from src.llm.served_model import REPO_ROOT

COMPOSE_DB_PORT = 54329  # docker-compose.yml publishes the db service on 127.0.0.1:54329
WEB_DIR = REPO_ROOT / "src" / "web"
DEFAULT_SUMMARY_LIMIT = 5

STAGES = [
    ("S0 db", "start the local compose database if DATABASE_URL points at it, connect, apply db/migrations"),
    ("S1 ingest", "only if `rulings` is empty: suva_data pull (if data/snapshot is missing), then build"),
    ("S2 triage", "layer 1 + layer 2 (src/triage/pipeline.py); a full run writes the predictions"),
    ("S3 summarise", "German and French fiches of the top N suspected-relevant rulings without a summary"),
    ("S4 serve", "the API and the UI (uvicorn suva_app.main:app on 127.0.0.1:8000)"),
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


class StageError(RuntimeError):
    """A stage cannot run; the message says why."""


def is_local_compose_db(url: str) -> bool:
    """True when the URL points at the db service of docker-compose.yml, as published on this machine."""
    parts = urlsplit(url)
    return parts.hostname in ("localhost", "127.0.0.1", "::1") and parts.port == COMPOSE_DB_PORT


def where(url: str) -> str:
    """host:port/database of a URL, without user or password (safe to print)."""
    parts = urlsplit(url)
    return f"{parts.hostname}:{parts.port or 5432}{parts.path}"


def _check_live_config() -> str:
    """The model name if the live settings are complete; raises ConfigError otherwise (G3)."""
    return LLMConfig.from_env("live").name


class Stages:
    """The real stages of `run`. Each returns the line it prints, or raises StageError."""

    def db_up(self) -> str:
        from suva_data import config

        url = config.DATABASE_URL
        if not is_local_compose_db(url):
            return f"DATABASE_URL points at {where(url)}, not the compose database: not started here"
        if shutil.which("docker") is None:
            return f"docker not found: assuming the database at {where(url)} is already up"
        proc = subprocess.run(["docker", "compose", "up", "-d", "--wait", "db"], cwd=REPO_ROOT, check=False)
        if proc.returncode != 0:
            raise StageError(f"`docker compose up -d --wait db` exited {proc.returncode}")
        return f"local compose database up (docker compose up -d --wait db), {where(url)}"

    def connect(self):
        import psycopg

        from suva_data import config, db

        try:
            conn = db.connect()
        except psycopg.OperationalError as exc:
            first = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
            raise StageError(f"cannot connect to {where(config.DATABASE_URL)}: {first} (start it: make db-up)") from exc
        applied = db.migrate(conn)
        done = f"applied {', '.join(applied)}" if applied else "schema up to date"
        return conn, f"connected to {where(config.DATABASE_URL)}; migrations: {done}"

    def count_rulings(self, conn) -> int:
        return int(conn.execute("SELECT count(*) FROM rulings").fetchone()[0])

    def ingest(self, conn) -> str:
        from suva_data import cli as data_cli
        from suva_data import config

        pulled = ""
        if not any(p.is_file() for p in config.SNAPSHOT_DIR.rglob("*")):
            print(f"  no snapshot in {config.SNAPSHOT_DIR}: suva_data pull ({config.OWN_DATASET_REPO})", flush=True)
            try:
                data_cli.cmd_pull(argparse.Namespace(revision=None))
            except Exception as exc:  # noqa: BLE001  network or Hugging Face: reported as the stage's reason
                raise StageError(f"suva_data pull failed: {type(exc).__name__}: {exc}") from exc
            pulled = f"pulled {config.OWN_DATASET_REPO}@{config.OWN_DATASET_REVISION[:12]}, then "
        try:
            status = data_cli.cmd_build(argparse.Namespace(update_manifest=False))
        except SystemExit as exc:
            raise StageError(f"suva_data build stopped: {exc}") from exc
        n = self.count_rulings(conn)
        if status != 0:
            raise StageError(f"suva_data build finished with failed checks (listed above); {n} rulings loaded")
        if n == 0:
            raise StageError("suva_data build loaded no ruling")
        return f"{pulled}built from {config.SNAPSHOT_DIR}: {n} rulings"

    def triage(self, conn, mode: str, limit: int | None) -> str:
        from src.llm.client import client_from_env
        from src.triage import pipeline as tp

        try:
            client = client_from_env(mode)
        except ConfigError as exc:
            raise StageError(str(exc)) from exc
        try:
            s = tp.run_and_store(conn, client, mode=mode, write_db=limit is None, limit=limit)
        except tp.TriageIncomplete as exc:
            raise StageError(str(exc)) from exc
        finally:
            client.close()
        suspected = sum(q["suspected_relevant"] for q in s.get("by_quarter", {}).values())
        line = (
            f"{s['rulings']} rulings, {s['kept_by_layer1']} kept by layer 1, "
            f"{s['core_rulings_read_by_apertus']} read by Apertus ({s['apertus_readings_failed']} readings failed), "
            f"{suspected} suspected relevant"
        )
        if limit:
            return line + f"; smoke run of the first {limit}: nothing written"
        return line + f"; predictions written as model run {s['run_id']}; {tp.RESULTS.relative_to(REPO_ROOT)}"

    def summary_candidates(self, conn, n: int) -> tuple[bool, list[tuple[int, str]]]:
        """(any current prediction?, the top n suspected-relevant rulings without a current summary)."""
        from suva_app.queries import _BASE  # the status the interface shows

        any_prediction = conn.execute("SELECT EXISTS (SELECT 1 FROM predictions WHERE is_current)").fetchone()[0]
        rows = conn.execute(
            _BASE + "SELECT id, docket FROM list WHERE status = 'ai_relevant' AND NOT has_summary "
            "ORDER BY score DESC NULLS LAST, decision_date DESC LIMIT %s",
            (n,),
        ).fetchall()
        return bool(any_prediction), [(int(r[0]), r[1]) for r in rows]

    def summarise(self, conn, mode: str, n: int) -> str:
        from src.summarize import pipeline as sp

        # The summariser gains a `mode` argument in a parallel change; until then it can only call live.
        accepts_mode = "mode" in inspect.signature(sp.summarise_ruling).parameters
        if mode == "replay" and not accepts_mode:
            raise StageError(
                "the summariser has no replay mode yet (src/summarize/pipeline.summarise_ruling takes no `mode`), "
                "so it would call the gateway live; skip it with SUMMARY_LIMIT=0, or run live with --limit N"
            )
        any_prediction, todo = self.summary_candidates(conn, n)
        if not any_prediction:
            raise StageError("no current prediction to rank by: S2 triage has written none (a --limit run writes none)")
        if not todo:
            return f"nothing to do: every suspected-relevant ruling already has a current summary (asked for {n})"
        extra = {"mode": mode} if accepts_mode else {}
        from src.llm.client import ReplayMiss

        done: list[str] = []
        uncached: list[str] = []  # replay only: no cached answer is not an error, the run still reaches the UI
        failed: list[str] = []
        for index, (ruling_id, docket) in enumerate(todo, start=1):
            print(f"  {index}/{len(todo)} {docket}", flush=True)
            try:
                sp.summarise_ruling(conn, ruling_id, **extra)
                done.append(docket)
            except ReplayMiss as exc:
                if mode != "replay":
                    failed.append(f"{docket}: {type(exc).__name__}: {exc}")
                else:
                    uncached.append(docket)
            except (Exception, SystemExit) as exc:  # noqa: BLE001  the gateway client exits with SystemExit
                failed.append(f"{docket}: {type(exc).__name__}: {exc}")
        if failed:
            raise StageError(f"{len(failed)} of {len(todo)} failed: " + "; ".join(failed))
        line = f"{len(done)} rulings summarised in German and French: {', '.join(done) or 'none'}"
        if uncached:
            line += (
                f"; {len(uncached)} not in the replay cache, left without a summary ({', '.join(uncached)}): "
                '`make run-live ARGS="--limit N"` writes them'
            )
        return line

    def serve(self) -> int:
        return serve()


def build_ui() -> str:
    """Build src/web/dist when it is missing (FastAPI serves it at "/"). Never fails the API: says why not."""
    if (WEB_DIR / "dist" / "index.html").is_file():
        return "UI: src/web/dist present"
    if shutil.which("npm") is None:
        return "UI: npm not found, so src/web/dist is not built: serving the API only (install Node to get the UI)"
    for step in (["npm", "--prefix", str(WEB_DIR), "ci"], ["npm", "--prefix", str(WEB_DIR), "run", "build"]):
        print(f"serve: {' '.join(step)}", flush=True)
        if subprocess.run(step, cwd=REPO_ROOT, check=False).returncode != 0:
            raise StageError(f"UI build failed at `{' '.join(step)}`")
    return "UI: built src/web/dist"


def serve() -> int:
    import uvicorn

    host = os.environ.get("SUVA_HOST") or "127.0.0.1"
    port = int(os.environ.get("SUVA_PORT") or 8000)
    import socket

    with socket.socket() as probe:  # fail with the reason before the app starts, not after its startup
        try:
            probe.bind((host, port))
        except OSError as exc:
            raise StageError(f"{host}:{port} is already in use ({exc.strerror}); stop it or set SUVA_PORT") from exc
    print(f"serve: {build_ui()}", flush=True)
    print(f"serve: API and UI on http://{host}:{port} (Ctrl-C to stop)", flush=True)
    uvicorn.run("suva_app.main:app", host=host, port=port)
    return 0


def cmd_run(args: argparse.Namespace, stages=None) -> int:
    stages = Stages() if stages is None else stages
    mode = args.mode
    tag = f"[{mode.upper()}]"
    limit = args.limit
    n_summaries = min(limit, args.summary_limit) if limit else args.summary_limit
    if mode == "live":
        if not (args.all or limit):
            print(f"run {tag}: pass --limit N or --all (no expensive action by default)", file=sys.stderr)
            return 2
        if not args.dry_run:
            try:
                model = _check_live_config()
            except ConfigError as exc:
                print(f"run {tag} S2 triage, S3 summarise: FAILED before any stage: {exc}", file=sys.stderr)
                return 2
            print(f"run {tag}: model {model}, scope {f'first {limit} rulings (smoke)' if limit else 'all'}")
    else:
        print(f"run {tag}: no gateway call; cached Apertus answers only (data/derived/llm, D-032)")
    if args.dry_run:
        for name, what in STAGES:
            print(f"run {tag} [dry-run] {name}: {what}")
        return 0

    def say(name: str, line: str) -> None:
        print(f"run {tag} {name}: {line}", flush=True)

    current = "S0 db"
    try:
        say(current, stages.db_up())
        conn, line = stages.connect()
        say(current, line)
        current = "S1 ingest"
        held = stages.count_rulings(conn)
        if held:
            say(current, f"skipped: the database already holds {held} rulings (a loaded database is never re-ingested)")
        else:
            say(current, stages.ingest(conn))
        current = "S2 triage"
        say(current, stages.triage(conn, mode, limit))
        current = "S3 summarise"
        if n_summaries <= 0:
            say(current, "skipped (SUMMARY_LIMIT=0)")
        else:
            say(current, stages.summarise(conn, mode, n_summaries))
    except StageError as exc:
        print(f"run {tag} {current}: FAILED: {exc}", file=sys.stderr)
        return 1
    except (Exception, SystemExit) as exc:  # noqa: BLE001  any other error still names its stage
        print(f"run {tag} {current}: FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if args.no_serve:
        say("S4 serve", "skipped (SERVE=0); done")
        return 0
    say("S4 serve", "starting; every stage above done")
    try:
        return stages.serve()
    except StageError as exc:
        print(f"run {tag} S4 serve: FAILED: {exc}", file=sys.stderr)
        return 1


def cmd_replay_cache(args: argparse.Namespace) -> int:
    """Fill replay/llm (committed) with the answers one full replay run reads, so a fresh clone needs no gateway:
    the triage of every ruling, and the summaries of every ruling that holds a model-written summary now.
    No gateway call and nothing written to the database (each summary is replayed, then rolled back)."""
    from src.llm.client import SHIPPED_STORE, ReplayMiss, client_from_env, export_answers
    from src.summarize import pipeline as sp
    from src.triage import pipeline as tp
    from suva_data import db

    client = client_from_env("replay")
    with db.connect() as conn:
        failed = tp.failures(tp.run(conn, client))
        if any(failed):
            print(f"replay-cache: FAILED: triage is missing answers {failed}; run `make triage MODE=live` first")
            return 1
        ids = conn.execute(
            "SELECT DISTINCT s.ruling_id, r.docket FROM summaries s JOIN rulings r ON r.id = s.ruling_id "
            "WHERE s.origin = 'model' ORDER BY r.docket"
        ).fetchall()
        replayed, missing = 0, []
        for ruling_id, docket in ids:
            try:
                with conn.transaction(force_rollback=True):
                    sp.summarise_ruling(conn, ruling_id, mode="replay")
                replayed += 1
            except ReplayMiss:
                missing.append(docket)
    added = export_answers(SHIPPED_STORE)
    total = sum(1 for _ in (SHIPPED_STORE / "cache").rglob("*.json"))
    print(
        f"replay-cache: {added} answers added, {total} in {SHIPPED_STORE.relative_to(REPO_ROOT)}; "
        f"summaries replayable: {replayed} of {len(ids)}" + (f"; not cached: {', '.join(missing)}" if missing else "")
    )
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    try:
        return serve()
    except StageError as exc:
        print(f"serve: FAILED: {exc}", file=sys.stderr)
        return 1


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
    run.add_argument("--no-serve", action="store_true", help="stop after the summaries (make run SERVE=0)")
    run.add_argument(
        "--summary-limit",
        type=int,
        default=int(os.environ.get("SUMMARY_LIMIT") or DEFAULT_SUMMARY_LIMIT),
        help="summarise at most N rulings (SUMMARY_LIMIT, default %(default)s; 0 skips)",
    )
    sub.add_parser("serve", help="serve the API and the UI (builds src/web/dist first when missing)")
    sub.add_parser("replay-cache", help="fill replay/llm with the cached answers one full run reads (no gateway)")
    sub.add_parser("smoke-llm", help="gateway probe (src/llm/probe.py); flags go to the probe")
    warm = sub.add_parser("warmup", help="warm the large model")
    warm.add_argument("--dry-run", action="store_true")
    stubs = {
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
    if args.cmd == "serve":
        return cmd_serve(args)
    if args.cmd == "replay-cache":
        return cmd_replay_cache(args)
    if args.cmd == "warmup":
        return cmd_warmup(args)
    return stub(args.cmd, args.would)


if __name__ == "__main__":
    sys.exit(main())
