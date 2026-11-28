"""Postgres plumbing shared by the reference adapters of the classifier, the summarizer and the app.

The three components keep their logic free of SQL. Their Postgres adapters (``src/triage/pg.py``,
``src/summarize/pg.py``, ``src/suva_app/pg.py``) target the schema in ``db/migrations/`` and use these helpers.

Transaction convention: ``connect()`` returns an AUTOCOMMIT connection and every multi-statement write is
wrapped in ``with conn.transaction():``, so a function either fully applies or leaves nothing behind.
Adapted from ``src/suva_data/db.py`` (the ingestion package, not on this branch); keep the two in step.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import psycopg

REPO = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO / "db" / "migrations"
DEFAULT_DATABASE_URL = "postgresql://suva@localhost:54329/suva"
# Arbitrary constant: serialises concurrent `migrate` calls on one database (same key as suva_data.db).
_MIGRATE_LOCK_KEY = 5_420_001


def database_url() -> str:
    """``DATABASE_URL`` from the environment, else the local compose database."""
    return os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL


def connect(url: str | None = None, **kwargs) -> psycopg.Connection:
    """Open a psycopg (v3) connection to ``url`` (default: ``database_url()``). Autocommit unless overridden."""
    kwargs.setdefault("autocommit", True)
    return psycopg.connect(url or database_url(), **kwargs)


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
    """Apply every `*.sql` in `migrations_dir` (default: MIGRATIONS_DIR) in filename order, once each.

    Applied files are tracked in `schema_migrations`; each migration runs in its own transaction together
    with its tracking row. Returns the filenames applied by this call ([] when up to date).
    Raises RuntimeError if an already applied file was edited afterwards (checksum differs).
    """
    directory = Path(migrations_dir or MIGRATIONS_DIR)
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
                conn.execute("INSERT INTO schema_migrations (filename, sha256) VALUES (%s, %s)", (path.name, digest))
            applied_now.append(path.name)
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (_MIGRATE_LOCK_KEY,))
    return applied_now


def git_commit() -> str | None:
    """Current commit of the repository, or None if git is unavailable / this is not a checkout."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, timeout=10, check=True
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return out or None
