"""Batch summaries: every potentially relevant ruling gets a German and a French fiche, written by v3.

    uv run --frozen python -m src.summarize.batch --mode live              # everything pending, 8 workers
    uv run --frozen python -m src.summarize.batch --mode live --limit 3    # the first 3 pending
    uv run --frozen python -m src.summarize.batch --mode replay            # from the replay cache, no gateway call
    uv run --frozen python -m src.summarize.batch --dry-run                # what is pending; no call, nothing stored

Pending: a ruling with a current prediction (it passed layer 1) and a usable text that lacks, in German or in
French, a model-written fiche from a run that asked for this writer. A language whose current fiche an expert
wrote or confirmed is never pending (and `pipeline.store` never replaces such a fiche). Order: rulings layer 2
calls relevant first, then by score, highest first.

Resumable: a finished ruling is no longer pending, so a second run skips it; each worker checks again just before
it starts a ruling, so two runs at once do not write a ruling twice. A ruling that fails is logged and the run
goes on. Each worker has its own database connection; every Apertus call goes through src/llm/client.py, whose
cache answers a request already answered (a ruling interrupted half-way costs only its missing calls).
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:  # run as a script or as a module
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.llm.client import ReplayMiss  # noqa: E402
from src.summarize import pipeline as sp  # noqa: E402

DEFAULT_WRITER = "v3"
DEFAULT_WORKERS = 8  # the gateway answered about 11,000 calls an hour with 8 workers (28 Nov)

# {done}: which run counts as having written the language. {scope}: optional extra conditions on the ruling.
_PENDING = """
SELECT r.id, r.docket, coalesce(p.relevant, false), p.score
FROM predictions p JOIN rulings r ON r.id = p.ruling_id
WHERE p.is_current
  AND EXISTS (SELECT 1 FROM ruling_texts t
              WHERE t.ruling_id = r.id AND t.is_canonical AND t.bad_reason IS NULL AND t.text <> '')
  AND EXISTS (
      SELECT 1 FROM unnest(%(languages)s::text[]) AS lang
      WHERE NOT EXISTS (SELECT 1 FROM summaries s JOIN model_runs m ON m.id = s.run_id
                        WHERE s.ruling_id = r.id AND s.language = lang AND s.origin = 'model' AND {done})
        AND NOT EXISTS (SELECT 1 FROM summaries s
                        WHERE s.ruling_id = r.id AND s.language = lang AND s.is_current
                          AND (s.origin = 'expert' OR s.confirmed_at IS NOT NULL)))
  {scope}
ORDER BY coalesce(p.relevant, false) DESC, p.score DESC NULLS LAST, r.decision_date DESC, r.docket
"""
_ASKED = "m.params ->> 'requested_writer' = %(writer)s"  # the run asked for the writer (v2 may have stood in)
_WROTE = "m.params -> 'writer' ->> lang = %(writer)s"  # the writer itself wrote this language
_NEW = """AND EXISTS (SELECT 1 FROM ingested_rulings i
              WHERE i.docket = r.docket AND i.decision_date = r.decision_date
                AND i.ingested_at >= (SELECT max(started_at) FROM ingest_runs WHERE command = 'ingest'))"""


def pending(
    conn,
    writer: str = DEFAULT_WRITER,
    limit: int | None = None,
    new_only: bool = False,
    retry_fallbacks: bool = False,
    dockets: list[str] | None = None,
    ruling_id: int | None = None,
    reverse: bool = False,
) -> list[tuple[int, str, bool, float | None]]:
    """[(ruling id, docket, relevant by layer 2, score)] still to summarise, most important first.

    `reverse`: least important first (a second run that works towards the first one from the other end).
    `new_only`: only the rulings the latest update added. `retry_fallbacks`: a language v2 wrote in place of the
    writer is pending again. `dockets` / `ruling_id` narrow the selection."""
    scope, params = [], {"languages": list(sp.LANGUAGES), "writer": writer}
    if new_only:
        scope.append(_NEW)
    if dockets:
        scope.append("AND r.docket = ANY(%(dockets)s)")
        params["dockets"] = dockets
    if ruling_id is not None:
        scope.append("AND r.id = %(ruling_id)s")
        params["ruling_id"] = ruling_id
    query = _PENDING.format(done=_WROTE if retry_fallbacks else _ASKED, scope="\n  ".join(scope))
    if reverse:
        query = query.replace(" DESC", " ASC").replace("NULLS LAST", "NULLS FIRST")
    if limit is not None:
        query += " LIMIT %(limit)s"
        params["limit"] = limit
    return [(int(r[0]), r[1], bool(r[2]), r[3]) for r in conn.execute(query, params).fetchall()]


def run(
    mode: str = "live",
    writer: str = DEFAULT_WRITER,
    workers: int = DEFAULT_WORKERS,
    limit: int | None = None,
    new_only: bool = False,
    retry_fallbacks: bool = False,
    dockets: list[str] | None = None,
    reverse: bool = False,
    connect=None,
    say=None,
) -> dict:
    """Summarise everything pending with `workers` threads, one database connection each. Never raises for one
    ruling: it is counted and the run goes on. Returns the counts and the dockets per outcome."""
    if connect is None:
        from suva_data import db

        connect = db.connect
    say = say or (lambda line: print(line, flush=True))
    tag = f"summaries [{mode.upper()}]"
    select = {"writer": writer, "new_only": new_only, "retry_fallbacks": retry_fallbacks}
    with connect() as conn:
        todo = pending(conn, limit=limit, dockets=dockets, reverse=reverse, **select)
    out = {"mode": mode, "writer": writer, "pending": len(todo), "done": [], "fallback": [], "failed": [],
           "uncached": [], "skipped": []}  # fmt: skip
    relevant = sum(1 for t in todo if t[2])
    say(f"{tag}: {len(todo)} rulings pending ({relevant} relevant by layer 2 first), writer {writer}, "
        f"{workers} workers")  # fmt: skip
    if not todo:
        return out
    local, lock, started = threading.local(), threading.Lock(), time.monotonic()

    def one(item) -> tuple[str, str]:
        ruling_id, docket, _, _ = item
        try:
            conn = getattr(local, "conn", None)
            if conn is None or conn.closed:
                conn = local.conn = connect()
            if not pending(conn, ruling_id=ruling_id, **select):
                return "skipped", "written meanwhile by another run"
            result = sp.summarise_ruling(conn, ruling_id, mode=mode, writer=writer)
        except ReplayMiss as exc:
            return ("uncached" if mode == "replay" else "failed"), f"ReplayMiss: {exc}"
        except sp.NotSummarisable as exc:
            return "skipped", str(exc)
        except (Exception, SystemExit) as exc:  # noqa: BLE001  one ruling never stops the batch
            conn = getattr(local, "conn", None)
            if conn is not None:  # the connection may be the thing that broke: the next ruling opens a new one
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass
                local.conn = None
            return "failed", f"{type(exc).__name__}: {exc}"[:300]
        wrote = {language: fiche.get("writer", "v2") for language, fiche in result["languages"].items()}
        detail = " ".join(f"{language}={w}" for language, w in wrote.items())
        return ("done" if all(w == writer for w in wrote.values()) else "fallback"), detail

    with ThreadPoolExecutor(max(1, workers)) as pool:
        futures = {pool.submit(one, item): item for item in todo}
        for n, future in enumerate(as_completed(futures), start=1):
            docket = futures[future][1]
            outcome, detail = future.result()
            with lock:
                out[outcome].append(docket)
            elapsed = time.monotonic() - started
            rate = n / elapsed * 60 if elapsed else 0.0
            eta = (len(todo) - n) / rate if rate else 0.0
            say(
                f"{tag} {n}/{len(todo)} {docket}: {outcome} ({detail}) | {writer} both {len(out['done'])}, "
                f"v2 stood in {len(out['fallback'])}, failed {len(out['failed'])}, uncached {len(out['uncached'])}, "
                f"skipped {len(out['skipped'])} | {rate:.1f}/min, about {eta:.0f} min left"
            )
    say(
        f"{tag}: finished in {(time.monotonic() - started) / 60:.1f} min: {len(out['done'])} written by {writer} in "
        f"both languages, {len(out['fallback'])} with v2 standing in for a language, {len(out['failed'])} failed, "
        f"{len(out['uncached'])} not in the replay cache, {len(out['skipped'])} skipped"
    )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Batch summaries of every potentially relevant ruling")
    parser.add_argument("--mode", choices=sp.MODES, default="replay", help="live calls Apertus; replay never does")
    parser.add_argument("--writer", choices=sp.WRITERS, default=DEFAULT_WRITER)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--limit", type=int, help="at most N rulings, the most important first")
    parser.add_argument("--dockets", nargs="+", help="only these case numbers (still only when pending)")
    parser.add_argument("--new-only", action="store_true", help="only the rulings the latest update added")
    parser.add_argument("--retry-fallbacks", action="store_true", help="also redo a language v2 wrote instead")
    parser.add_argument("--reverse", action="store_true", help="least important first (a second run from the end)")
    parser.add_argument("--dry-run", action="store_true", help="list what is pending; no call, nothing stored")
    args = parser.parse_args(argv)

    from src.cli import load_dotenv

    load_dotenv()
    if args.dry_run:
        from suva_data import db

        with db.connect() as conn:
            todo = pending(
                conn, args.writer, args.limit, args.new_only, args.retry_fallbacks, args.dockets, reverse=args.reverse
            )
        print(f"summaries [dry-run]: {len(todo)} pending, {sum(1 for t in todo if t[2])} relevant by layer 2")
        for _, docket, relevant, score in todo[:20]:
            print(f"  {docket} relevant={relevant} score={score}")
        return 0
    if args.mode == "live":
        from src.llm.config import ConfigError, LLMConfig

        try:
            LLMConfig.from_env("live")
        except ConfigError as exc:
            print(f"summaries [LIVE]: FAILED before any call: {exc}", file=sys.stderr)
            return 2
    out = run(
        args.mode, args.writer, args.workers, args.limit, args.new_only, args.retry_fallbacks, args.dockets,
        reverse=args.reverse,
    )  # fmt: skip
    return 1 if out["pending"] and not (out["done"] or out["fallback"] or out["skipped"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
