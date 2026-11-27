"""Database plumbing: connection, migrations runner, ingest_runs bookkeeping (docs/ARCHITECTURE.md 5, 7).

Transaction convention used by this package: `connect()` returns an AUTOCOMMIT connection and every
multi-statement write is wrapped in `with conn.transaction():`. So a function either fully applies or
leaves nothing behind, and callers never need `conn.commit()` (calling it anyway is harmless).
If a caller passes a non-autocommit connection that is already inside a transaction, the same blocks
become savepoints and the caller's commit decides.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from . import config

RUN_STATUSES = ("running", "ok", "failed", "partial")
# Arbitrary constant: serialises concurrent `migrate` calls on one database.
_MIGRATE_LOCK_KEY = 5_420_001


def connect(url: str | None = None, **kwargs) -> psycopg.Connection:
    """Open a psycopg (v3) connection to `url` (default: config.DATABASE_URL). Autocommit unless overridden."""
    kwargs.setdefault("autocommit", True)
    return psycopg.connect(url or config.DATABASE_URL, **kwargs)


def strip_nul(value):
    """Remove NUL characters, which Postgres text and jsonb cannot store. Recurses into dicts / lists."""
    if isinstance(value, str):
        return value.replace("\x00", "") if "\x00" in value else value
    if isinstance(value, dict):
        return {strip_nul(k): strip_nul(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [strip_nul(v) for v in value]
    return value


def migrate(conn: psycopg.Connection, migrations_dir: Path | None = None) -> list[str]:
    """Apply every `*.sql` in `migrations_dir` (default: config.MIGRATIONS_DIR) in filename order, once each.

    Applied files are tracked in `schema_migrations`; each migration runs in its own transaction together
    with its tracking row. Returns the filenames applied by this call ([] when up to date).
    Raises RuntimeError if an already applied file was edited afterwards (checksum differs).
    """
    directory = Path(migrations_dir or config.MIGRATIONS_DIR)
    files = sorted(directory.glob("*.sql"), key=lambda p: p.name)
    applied_now: list[str] = []
    conn.execute("SELECT pg_advisory_lock(%s)", (_MIGRATE_LOCK_KEY,))
    try:
        with conn.transaction():
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    filename   text PRIMARY KEY,
                    sha256     text NOT NULL,
                    applied_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
        done = dict(conn.execute("SELECT filename, sha256 FROM schema_migrations").fetchall())
        for path in files:
            sql = path.read_text(encoding="utf-8")
            digest = hashlib.sha256(sql.encode("utf-8")).hexdigest()
            if path.name in done:
                if done[path.name] != digest:
                    raise RuntimeError(
                        f"migration {path.name} was changed after it was applied "
                        "(add a new migration instead, or recreate the database)"
                    )
                continue
            with conn.transaction():
                conn.execute(sql.encode("utf-8"))  # bytes: no parameters, so '%' in SQL needs no escaping
                conn.execute(
                    "INSERT INTO schema_migrations (filename, sha256) VALUES (%s, %s)", (path.name, digest)
                )
            applied_now.append(path.name)
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (_MIGRATE_LOCK_KEY,))
    return applied_now


def git_commit() -> str | None:
    """Current commit of the repository, or None if git is unavailable / this is not a checkout."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=config.REPO, capture_output=True, text=True, timeout=10, check=True
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return out or None


def start_run(conn: psycopg.Connection, command: str, params: dict | None = None) -> int:
    """Insert an ingest_runs row with status 'running'; returns its id."""
    row = conn.execute(
        "INSERT INTO ingest_runs (command, params, git_commit) VALUES (%s, %s, %s) RETURNING id",
        (command, Jsonb(strip_nul(params or {})), git_commit()),
    ).fetchone()
    return row[0]


def finish_run(conn: psycopg.Connection, run_id: int, status: str, report: dict | None = None) -> None:
    """Close an ingest_runs row: status in ('ok', 'failed', 'partial'), optional JSON report."""
    if status not in RUN_STATUSES:
        raise ValueError(f"status must be one of {RUN_STATUSES}, got {status!r}")
    cur = conn.execute(
        "UPDATE ingest_runs SET status = %s, report = %s, finished_at = now() WHERE id = %s",
        (status, None if report is None else Jsonb(strip_nul(report)), run_id),
    )
    if cur.rowcount != 1:
        raise LookupError(f"no ingest_runs row with id {run_id}")
