"""PostgreSQL sessions for the pipeline steps and loaders (docs/DB_DDL_PLANNING.md §4, §15.6).

Every session sets `app.actor` (and `app.run_id` when known), which the audit log and the expert write
functions read. The URL comes from DATABASE_URL; no default, no password in code (G13).

Least privilege (F-11): every session then runs `SET ROLE` to the pipeline group (`DB_PIPELINE_ROLE`, default
`suva_g_pipeline`), whatever login the URL names (a deployment user, a superuser in a local container): the
pipeline reads everything, inserts facts and updates only lifecycle columns (src/db/sql/90_roles.sql), and the audit
log records that role. An empty DB_PIPELINE_ROLE keeps the login's own rights, with a warning. Deploy (psql, as the
owner) is unaffected.

SET ROLE is not a security boundary: any code on the connection can RESET ROLE (or SET ROLE to any other role the
login may take) and get the login's rights back. It keeps honest pipeline code inside the group's rights and makes the
audit log name that group; no src/ code resets it. Real least privilege needs DATABASE_URL to name a login whose only
membership is the pipeline group (suva_pipeline, src/db/sql/90_roles.sql), never the owner or a superuser such as the
local container's.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[2]
NAMESPACE = uuid.UUID("1dd0895a-ba8b-499e-985e-5f92eed68ad3")  # same as ops.uuid5() in 00_extensions.sql
PIPELINE_ROLE = "suva_g_pipeline"  # src/db/sql/90_roles.sql


class DatabaseNotConfigured(RuntimeError):
    """DATABASE_URL is not set and no URL was given."""


class DatabaseRoleError(RuntimeError):
    """The session cannot take the pipeline role (missing, or not granted to the login)."""


def database_url(url: str | None = None) -> str:
    found = url or os.environ.get("DATABASE_URL")
    if not found:
        raise DatabaseNotConfigured("set DATABASE_URL (or pass --url)")
    return found


def connect(
    url: str | None = None, *, actor: str = "pipeline", run_id: str | None = None, pipeline: bool = True
) -> psycopg.Connection:
    """A session with app.actor set. `pipeline=True` (every step and loader) takes the pipeline role (F-11);
    `pipeline=False` keeps the login's own rights, for owner operations only (src/db/logins.py sets the login
    passwords and proves what a login itself may do)."""
    conn = psycopg.connect(database_url(url))
    try:
        set_session(conn, actor=actor, run_id=run_id)
        if pipeline:
            set_role(conn)
    except BaseException:
        conn.close()
        raise
    return conn


def pipeline_role() -> str | None:
    """The role every pipeline session runs as: DB_PIPELINE_ROLE, default suva_g_pipeline; None when set empty."""
    return os.environ.get("DB_PIPELINE_ROLE", PIPELINE_ROLE).strip() or None


def set_role(conn: psycopg.Connection) -> None:
    """SET ROLE to the pipeline role for the whole session (F-11); a clear error when it cannot be taken."""
    role = pipeline_role()
    if role is None:
        print(
            "warning: DB_PIPELINE_ROLE is empty: the session keeps the login's own rights, not the pipeline group's "
            "least privilege (F-11)",
            file=sys.stderr,
        )
        return
    try:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))
        conn.commit()
    except psycopg.Error as exc:
        conn.rollback()
        reason = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        raise DatabaseRoleError(
            f"cannot SET ROLE {role} ({reason}): deploy the roles (make db-deploy), grant {role} to the login of "
            "DATABASE_URL, or set DB_PIPELINE_ROLE to another group (empty: run with the login's own rights)"
        ) from exc


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
    """(commit, dirty) of the working tree. Outside git (the container image holds no .git), the commit the image
    was built from (SUVA_GIT_COMMIT, SUVA_GIT_DIRTY: Dockerfile build args); (None, True) when unknown."""
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True)
        status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        built = os.environ.get("SUVA_GIT_COMMIT", "").strip()
        if not built:
            return None, True
        return built, os.environ.get("SUVA_GIT_DIRTY", "1").strip() != "0"
    return commit.stdout.strip(), bool(status.stdout.strip())
