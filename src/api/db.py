"""Database sessions of the API: app.actor set, the API login's rights (SET ROLE), its statement timeout.

One connection per request (no pool: a prototype on one machine); at most API_MAX_DB_SESSIONS at once (src/api/app.py).
A read runs in one READ ONLY, REPEATABLE READ transaction: every statement of the request (a list page and its total,
the parts of a ruling page) sees the same snapshot, even while a pipeline run writes. Writes keep the database's
default READ COMMITTED (PR #51).
"""

from __future__ import annotations

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from src.db.pg import database_url, set_session

from .settings import Settings


class ApiDatabaseError(RuntimeError):
    """The API cannot open a usable session (role missing, database unreachable)."""


class ApiBusy(RuntimeError):
    """Every database session the API may hold is in use (API_MAX_DB_SESSIONS)."""


def connect(settings: Settings, *, read_only: bool) -> psycopg.Connection:
    try:
        conn = psycopg.connect(database_url(), row_factory=dict_row, connect_timeout=5)
    except psycopg.OperationalError as exc:
        raise ApiDatabaseError(f"the database is unreachable: {str(exc).strip().splitlines()[0]}") from exc
    try:
        set_session(conn, actor=settings.actor)
        with conn.cursor() as cur:
            if settings.db_role:
                cur.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(settings.db_role)))
            cur.execute("SELECT set_config('statement_timeout', %s, false)", (f"{settings.statement_timeout_ms}ms",))
        conn.commit()
        conn.read_only = read_only
        if read_only:
            conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
    except psycopg.Error as exc:
        conn.close()
        reason = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        raise ApiDatabaseError(
            f"cannot open an API session ({reason}): deploy the roles (make db-deploy) and grant {settings.db_role} "
            "to the login of DATABASE_URL, or set API_DB_ROLE (empty: the login's own rights)"
        ) from exc
    except BaseException:
        conn.close()
        raise
    return conn
