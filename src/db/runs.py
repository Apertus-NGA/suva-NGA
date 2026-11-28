"""Runs and their root span (docs/DB_DDL_PLANNING.md §11, §14).

`begin_run` commits the run row and its root span first, so a failure later in the run still leaves a
trace: `fail_run` closes both with the error; `finish_run` closes them on success. A step's own rows
are written in one transaction between the two: all or nothing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import psycopg

from src.db.pg import git_state, sha256_text


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
    actor: str,
    mode: str = "LIVE",
    resolved_models: dict | None = None,
    model_override: bool = False,
) -> Run:
    """`resolved_models`: the models actually used per role; `model_override`: they differ from the declared ones
    (the judges' LLM_NAME, D-064). Both are fixed at insert: the run row only lets its status change."""
    commit, dirty = git_state()
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
    """Close the root span and the run, inside the step's transaction. `partial`: the run is usable, some items
    failed and wait for the next run (they stay `potentially`, never a negative: D-063)."""
    if status not in ("succeeded", "partial"):
        raise ValueError(f"finish_run closes a usable run only (succeeded or partial), not {status!r}")
    cur.execute("UPDATE ops.span SET status = 'ok', ended_at = now() WHERE span_id = %s", (run.span_id,))
    cur.execute("UPDATE ops.pipeline_run SET status = %s, finished_at = now() WHERE run_id = %s", (status, run.run_id))


def fail_run(conn: psycopg.Connection, run: Run, error: BaseException, status: str = "failed") -> None:
    """After a rollback: close the root span and the run as failed (or aborted, on Ctrl-C), with the error."""
    conn.rollback()
    message = f"{type(error).__name__}: {error}"[:500]
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE ops.span SET status = 'error', ended_at = now(), error_message = %s WHERE span_id = %s",
            (message, run.span_id),
        )
        cur.execute(
            "UPDATE ops.pipeline_run SET status = %s, finished_at = now(), error_summary = %s WHERE run_id = %s",
            (status if status in ("failed", "aborted") else "failed", message, run.run_id),
        )
    conn.commit()


def events(cur: psycopg.Cursor, run: Run, step: str, rows: list[tuple]) -> None:
    """Insert log events: rows of (seq, level, event_code, message, attributes, ruling_id, span_id)."""
    cur.execute("SELECT ops.ensure_log_partitions(current_date - 1, current_date + 1)")
    cur.executemany(
        """INSERT INTO ops.log_event (run_id, seq, ts, span_id, ruling_id, step, level, event_code, message, attributes)
           VALUES (%s, %s, clock_timestamp(), %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
        [
            (run.run_id, seq, span or run.span_id, ruling, step, level, code, message, json.dumps(attrs or {}))
            for seq, level, code, message, attrs, ruling, span in rows
        ],
    )


def metrics(cur: psycopg.Cursor, run: Run, step: str, values: dict[str, float], unit: str = "count") -> None:
    cur.executemany(
        "INSERT INTO ops.run_metric (run_id, step, metric_code, value, unit) VALUES (%s, %s, %s, %s, %s) ON CONFLICT "
        "DO NOTHING",
        [(run.run_id, step, code.lower(), value, unit) for code, value in values.items()],
    )
