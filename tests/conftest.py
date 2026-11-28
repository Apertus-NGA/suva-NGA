"""Shared pytest fixture: `db_conn`, a connection to a freshly migrated, empty test database.

The test database lives on the same server as config.DATABASE_URL under the name `suva_test`
(override the whole URL with SUVA_TEST_DATABASE_URL; its database name must contain 'test').
If the server is not reachable the tests using `db_conn` are skipped: start it with `docker compose up -d db`.
"""

from __future__ import annotations

import os
import time

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from suva_data import config, db

TEST_DB_NAME = "suva_test"
# Several pytest sessions may share the test database (parallel work packages): one at a time.
_SESSION_LOCK_KEY = 5_420_002
_LOCK_WAIT_SECONDS = 300


def _test_url() -> str:
    url = os.environ.get("SUVA_TEST_DATABASE_URL") or make_conninfo(config.DATABASE_URL, dbname=TEST_DB_NAME)
    name = conninfo_to_dict(url).get("dbname") or ""
    if "test" not in name:
        raise RuntimeError(f"refusing to run tests against database {name!r}: its name must contain 'test'")
    return url


def _where(url: str) -> str:
    info = conninfo_to_dict(url)
    return f"{info.get('host')}:{info.get('port')}/{info.get('dbname')}"


@pytest.fixture(scope="session")
def _db_session():
    """Create the test database if missing, rebuild its schema from the migrations, and hold a session lock."""
    test_url = _test_url()
    name = conninfo_to_dict(test_url)["dbname"]
    try:
        try:
            lock_conn = psycopg.connect(test_url, autocommit=True, connect_timeout=3)
        except psycopg.OperationalError:
            # Probably the database does not exist yet: create it via the server's default database.
            with psycopg.connect(
                make_conninfo(test_url, dbname="postgres"), autocommit=True, connect_timeout=3
            ) as admin:
                if not admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone():
                    try:
                        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
                    except psycopg.errors.DuplicateDatabase:  # another session created it just now
                        pass
            lock_conn = psycopg.connect(test_url, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(
            f"Postgres test database not reachable at {_where(test_url)} "
            f"(start it with `docker compose up -d db`): {str(exc).strip().splitlines()[0]}"
        )

    deadline = time.monotonic() + _LOCK_WAIT_SECONDS
    while not lock_conn.execute("SELECT pg_try_advisory_lock(%s)", (_SESSION_LOCK_KEY,)).fetchone()[0]:
        if time.monotonic() > deadline:
            lock_conn.close()
            raise RuntimeError(
                f"another test session has been using {_where(test_url)} for more than {_LOCK_WAIT_SECONDS}s"
            )
        time.sleep(0.2)
    try:
        lock_conn.execute("DROP SCHEMA public CASCADE")
        lock_conn.execute("CREATE SCHEMA public")
        db.migrate(lock_conn)
        yield test_url
    finally:
        lock_conn.close()  # releases the advisory lock


@pytest.fixture
def db_conn(_db_session):
    """psycopg connection (autocommit, like db.connect) to the migrated test database with every table empty."""
    conn = db.connect(_db_session)
    try:
        if not conn.execute("SELECT to_regclass('public.schema_migrations')").fetchone()[0]:
            db.migrate(conn)  # a previous test dropped the schema
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'schema_migrations' "
                "ORDER BY 1"
            )
        ]
        if tables:
            conn.execute(
                sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(sql.SQL(", ").join(map(sql.Identifier, tables)))
            )
        yield conn
    finally:
        conn.close()
