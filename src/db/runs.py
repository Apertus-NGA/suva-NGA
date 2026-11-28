"""Runs and their root span (docs/DB_DDL_PLANNING.md §11, §14).

`begin_run` commits the run row and its root span first, so a failure later in the run still leaves a
trace: `fail_run` closes both with the error; `finish_run` closes them on success. A step's own rows
are written in one transaction between the two: all or nothing. Both close with `clock_timestamp()`, the real time of
the close, not `now()` (the transaction start): a step writes its events and metrics in the closing transaction, before
`finish_run`, so each event the run writes lies within [started_at, finished_at] of its run and root span. What is
appended to a closed run later (layer 1's `layer1.validation.*` event, its recall metrics) comes after `finished_at`.

Every run records the code that ran it (F-09): `params.code_paths` (the step's run paths, repo-relative) and
`params.code_sha256` (`src.db.registry.code_sha256` over exactly those paths). It is the same hash function a
registry version applies to its own `code_path` when created, but the two path sets can differ: a layer-1 run hashes
src/layer1/{engine,models,run,golden,recall,reference_courts_4c246a8}.py (`src.layer1.run.CODE_PATHS`), its version
src/layer1/{engine,models}.py (src/ingest/__main__.py REGISTRIES). Compare a run's hash only with another run's over
the same `code_paths`, never with its version's `code_sha256`. Two runs with the same hash ran the same code; the
golden check of a run proves its decisions whatever the code.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

import psycopg

from src.db.pg import git_state, sha256_text
from src.db.registry import code_sha256


@dataclass(frozen=True)
class Run:
    run_id: str
    span_id: str
    profile_version_id: str
    component_version_id: str | None


def begin_run(
    conn: psycopg.Connection,
    *,
    profile_version_id: str,
    kind: str,
    step: str,
    operation: str,
    component_version_id: str | None,
    params: dict,
    code_paths: Sequence[str],
    actor: str,
    mode: str = "LIVE",
    resolved_models: dict | None = None,
    model_override: bool = False,
) -> Run:
    """Open a run and its root span. `code_paths`: the source files of the step, recorded with their hash (F-09).
    `resolved_models`: the models actually used per role; `model_override`: they differ from the declared ones
    (the judges' LLM_NAME, D-064). Both are fixed at insert: the run row only lets its status change."""
    if not code_paths:
        raise ValueError(f"begin_run({operation}): name the step's code paths (params.code_sha256, F-09)")
    commit, dirty = git_state()
    params = {**params, "code_paths": sorted(code_paths), "code_sha256": code_sha256(code_paths)}
    params_json = json.dumps(params, sort_keys=True)
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO ops.pipeline_run (profile_version_id, kind, mode, git_commit, git_dirty, params,
               params_sha256, resolved_models, model_override, triggered_by, actor)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'cli', %s) RETURNING run_id::text""",
            (
                profile_version_id,
                kind,
                mode,
                commit,
                dirty,
                params_json,
                sha256_text(params_json),
                json.dumps(resolved_models or {}, sort_keys=True),
                model_override,
                actor,
            ),
        )
        run_id = cur.fetchone()[0]
        cur.execute("SELECT set_config('app.run_id', %s, false)", (run_id,))
        cur.execute(
            """INSERT INTO ops.span (run_id, step, operation, component_version_id, status, started_at)
               VALUES (%s, %s, %s, %s, 'running', now()) RETURNING span_id::text""",
            (run_id, step, operation, component_version_id),
        )
        span_id = cur.fetchone()[0]
    conn.commit()
    return Run(run_id, span_id, profile_version_id, component_version_id)


def finish_run(cur: psycopg.Cursor, run: Run, status: str = "succeeded") -> None:
    """Close the root span and the run, inside the step's transaction, as its last write (after the events and metrics,
    so they lie within the run's time range). `partial`: the run is usable, some items failed and wait for the next run
    (they stay `potentially`, never a negative: D-063)."""
    if status not in ("succeeded", "partial"):
        raise ValueError(f"finish_run closes a usable run only (succeeded or partial), not {status!r}")
    cur.execute("UPDATE ops.span SET status = 'ok', ended_at = clock_timestamp() WHERE span_id = %s", (run.span_id,))
    cur.execute(
        "UPDATE ops.pipeline_run SET status = %s, finished_at = clock_timestamp() WHERE run_id = %s",
        (status, run.run_id),
    )


def fail_run(conn: psycopg.Connection, run: Run, error: BaseException, status: str = "failed") -> None:
    """After a rollback: close the root span and the run as failed (or aborted, on Ctrl-C), with the error."""
    conn.rollback()
    message = f"{type(error).__name__}: {error}"[:500]
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE ops.span SET status = 'error', ended_at = clock_timestamp(), error_message = %s WHERE span_id = %s",
            (message, run.span_id),
        )
        cur.execute(
            "UPDATE ops.pipeline_run SET status = %s, finished_at = clock_timestamp(), error_summary = %s "
            "WHERE run_id = %s",
            (status if status in ("failed", "aborted") else "failed", message, run.run_id),
        )
    conn.commit()


_EVENT_SQL = """
INSERT INTO ops.log_event (run_id, seq, ts, span_id, ruling_id, step, level, event_code, message, attributes)
SELECT %(run_id)s::uuid, %(seq)s::bigint, clock_timestamp(), %(span_id)s::uuid, %(ruling_id)s::uuid,
       %(step)s::ops.pipeline_step, %(level)s::ops.log_level, %(code)s, %(message)s, %(attributes)s::jsonb
WHERE NOT EXISTS (SELECT 1 FROM ops.log_event e WHERE e.run_id = %(run_id)s::uuid AND e.seq = %(seq)s::bigint)
"""


def events(cur: psycopg.Cursor, run: Run, step: str, rows: list[tuple]) -> None:
    """Insert log events: rows of (seq, level, event_code, message, attributes, ruling_id, span_id).

    Idempotent per (run_id, seq) (L2-F20): `seq` is the event's identity within its run, so an event is inserted only
    when its run has no row with that seq yet; emitting a run's events again (a reload of its files) adds nothing and
    the first row, with its real clock timestamp, stays. `ops.log_event` is partitioned by `ts`, which its key must
    contain, so no unique (run_id, seq) index can say it: a transaction lock per run (held to commit) makes a
    concurrent emission for the same run wait, then see the committed rows, instead of inserting duplicates.
    """
    cur.execute("SELECT ops.ensure_log_partitions(current_date - 1, current_date + 1)")
    cur.execute("SELECT pg_advisory_xact_lock(hashtextextended('ops.log_event|' || %s, 0))", (run.run_id,))
    cur.executemany(
        _EVENT_SQL,
        [
            {
                "run_id": run.run_id,
                "seq": seq,
                "span_id": span or run.span_id,
                "ruling_id": ruling,
                "step": step,
                "level": level,
                "code": code,
                "message": message,
                "attributes": json.dumps(attrs or {}),
            }
            for seq, level, code, message, attrs, ruling, span in rows
        ],
    )


def metrics(cur: psycopg.Cursor, run: Run, step: str, values: dict[str, float], unit: str = "count") -> None:
    cur.executemany(
        "INSERT INTO ops.run_metric (run_id, step, metric_code, value, unit) VALUES (%s, %s, %s, %s, %s) ON CONFLICT "
        "DO NOTHING",
        [(run.run_id, step, code.lower(), value, unit) for code, value in values.items()],
    )
