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
) -> Run:
    commit, dirty = git_state()
    params_json = json.dumps(params, sort_keys=True)
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO ops.pipeline_run (profile_version_id, kind, mode, git_commit, git_dirty, params,
               params_sha256,
                                             triggered_by, actor)
               VALUES (%s, %s, %s, %s, %s, %s, %s, 'cli', %s) RETURNING run_id::text""",
            (profile_version_id, kind, mode, commit, dirty, params_json, sha256_text(params_json), actor),
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


def finish_run(cur: psycopg.Cursor, run: Run) -> None:
    """Close the root span and the run as succeeded, inside the step's transaction."""
    cur.execute("UPDATE ops.span SET status = 'ok', ended_at = now() WHERE span_id = %s", (run.span_id,))
    cur.execute(
        "UPDATE ops.pipeline_run SET status = 'succeeded', finished_at = now() WHERE run_id = %s", (run.run_id,)
    )


def fail_run(conn: psycopg.Connection, run: Run, error: BaseException) -> None:
    """After a rollback: close the root span and the run as failed, with the error."""
    conn.rollback()
    message = f"{type(error).__name__}: {error}"[:500]
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE ops.span SET status = 'error', ended_at = now(), error_message = %s WHERE span_id = %s",
            (message, run.span_id),
        )
        cur.execute(
            "UPDATE ops.pipeline_run SET status = 'failed', finished_at = now(), error_summary = %s WHERE run_id = %s",
            (message, run.run_id),
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
