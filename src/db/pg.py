"""PostgreSQL sessions for the pipeline steps and loaders (docs/DB_DDL_PLANNING.md §4, §15.6).

Every session sets `app.actor` (and `app.run_id` when known), which the audit log and the expert write
functions read. The URL comes from DATABASE_URL; no default, no password in code (G13).
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import uuid
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[2]
NAMESPACE = uuid.UUID("1dd0895a-ba8b-499e-985e-5f92eed68ad3")  # same as ops.uuid5() in 00_extensions.sql


class DatabaseNotConfigured(RuntimeError):
    """DATABASE_URL is not set and no URL was given."""


def database_url(url: str | None = None) -> str:
    found = url or os.environ.get("DATABASE_URL")
    if not found:
        raise DatabaseNotConfigured("set DATABASE_URL (or pass --url)")
    return found


def connect(url: str | None = None, *, actor: str = "pipeline", run_id: str | None = None) -> psycopg.Connection:
    conn = psycopg.connect(database_url(url))
    set_session(conn, actor=actor, run_id=run_id)
    return conn


def set_session(conn: psycopg.Connection, *, actor: str, run_id: str | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('app.actor', %s, false)", (actor,))
        cur.execute("SELECT set_config('app.run_id', %s, false)", (run_id or "",))
    conn.commit()


def uuid5(key: str) -> str:
    """Deterministic id, equal to ops.uuid5(key) in the database."""
    return str(uuid.uuid5(NAMESPACE, key))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def git_state() -> tuple[str | None, bool]:
    """(commit, dirty) of the working tree, or (None, True) outside git."""
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True)
        status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None, True
    return commit.stdout.strip(), bool(status.stdout.strip())
