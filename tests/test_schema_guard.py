"""The schema guard (src/db/schema_guard.py) and the structure it compares (src/db/structure.py, expected/db/)."""

from __future__ import annotations

import argparse
import os
import uuid

import pytest

from src.db import schema_guard as guard
from src.db import structure

WANT = ["column\tops.t.a\tinteger", "table\tops.t\tr"]


def test_decide_covers_every_state():
    assert guard.decide(present=False, live=[], want=WANT) == "fresh"
    assert guard.decide(present=True, live=list(WANT), want=WANT) == "same"
    with pytest.raises(SystemExit, match=r"\+column\tops\.t\.b\tinteger"):
        guard.decide(present=True, live=[*WANT, "column\tops.t.b\tinteger"], want=WANT)
    with pytest.raises(SystemExit, match=r"-column\tops\.t\.a\tinteger"):
        guard.decide(present=True, live=["table\tops.t\tr"], want=WANT)


def test_the_expected_structure_is_consistent():
    lines = structure.expected()  # refuses a file whose digest does not match its objects
    assert lines == sorted(lines, key=lambda line: tuple(line.split("\t", 2)[:2]))
    kinds = {line.split("\t", 1)[0] for line in lines}
    assert kinds == {"table", "column", "constraint", "index", "enum"}


@pytest.fixture
def database():
    """A throwaway database on the DATABASE_URL server, dropped at the end."""
    import psycopg
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    base = os.environ["DATABASE_URL"]
    name = f"suva_guard_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    try:
        yield make_conninfo(**(conninfo_to_dict(base) | {"dbname": name}))
    finally:
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


needs_db = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="needs DATABASE_URL")


@pytest.mark.db
@needs_db
def test_guard_on_a_real_database(database, monkeypatch):
    import psycopg

    from src.db import deploy

    monkeypatch.setenv("DATABASE_URL", database)
    args = argparse.Namespace(compose=False, url=database)
    assert guard.check() == "fresh"
    assert deploy.cmd_deploy(args) == 0
    with psycopg.connect(database) as conn:
        # The committed reference is what a fresh deploy of these files builds (CI catches a stale file here).
        assert structure.read(conn) == structure.expected()
        assert conn.execute("SELECT current_setting('default_transaction_isolation')").fetchone()[0] == "read committed"
    assert guard.check() == "same"
    assert deploy.cmd_deploy(args) == 0  # a second deploy on the same structure: idempotent
    with psycopg.connect(database, autocommit=True) as conn:
        # Replaceable objects and runtime partitions are not structure: a new function, more log partitions.
        conn.execute("CREATE FUNCTION ops.guard_probe() RETURNS int LANGUAGE sql RETURN 1")
        conn.execute("SELECT ops.ensure_log_partitions(current_date + 10, current_date + 12)")
    assert guard.check() == "same"
    with psycopg.connect(database, autocommit=True) as conn:  # a structural change made outside the files
        conn.execute("ALTER TABLE ops.pipeline_run ADD COLUMN guard_probe int")
    with pytest.raises(SystemExit, match=r"\+column\tops\.pipeline_run\.guard_probe\tinteger"):
        guard.check()


@pytest.mark.db
@needs_db
def test_a_failed_deploy_leaves_nothing_behind(database, tmp_path, monkeypatch):
    import psycopg

    from src.db import deploy

    broken = tmp_path / "99_broken.sql"
    broken.write_text("SELECT 1/0;\n")
    files = deploy.sql_files()
    monkeypatch.setattr(deploy, "sql_files", lambda *a, **k: [*files, broken])
    assert deploy.cmd_deploy(argparse.Namespace(compose=False, url=database)) != 0
    with psycopg.connect(database) as conn:
        assert conn.execute("SELECT count(*) FROM pg_namespace WHERE nspname = 'ops'").fetchone()[0] == 0
