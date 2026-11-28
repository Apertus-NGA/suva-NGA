"""The schema guard (src/db/schema_guard.py): deploy on an existing database only when it holds the same schema."""

from __future__ import annotations

import argparse
import os
import uuid

import pytest

from src.db import schema_guard as guard

CURRENT = "a" * 64


def test_decide_covers_every_state():
    assert guard.decide(present=False, recorded=None, current=CURRENT, adopt=False) == "fresh"
    # schemas dropped by hand, nothing deployed yet (a reset deploys and records: test_guard_on_a_real_database)
    assert guard.decide(present=False, recorded="b" * 64, current=CURRENT, adopt=False) == "fresh"
    assert guard.decide(present=True, recorded=CURRENT, current=CURRENT, adopt=False) == "same"
    assert guard.decide(present=True, recorded=None, current=CURRENT, adopt=True) == "adopt"
    with pytest.raises(SystemExit, match="no recorded fingerprint"):
        guard.decide(present=True, recorded=None, current=CURRENT, adopt=False)
    with pytest.raises(SystemExit, match="deployed from schema bbbbbbbbbbbb"):
        guard.decide(present=True, recorded="b" * 64, current=CURRENT, adopt=True)  # adopt never overrides a change


def test_the_fingerprint_is_the_deployed_script():
    from src.db.deploy import script_for, sql_files
    from src.db.pg import sha256_text

    assert guard.shipped() == sha256_text(script_for(sql_files())) == guard.shipped()


@pytest.mark.db
@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="needs DATABASE_URL")
def test_guard_on_a_real_database(monkeypatch):
    import psycopg
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    from src.db import deploy

    base = os.environ["DATABASE_URL"]
    name = f"suva_guard_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    url = make_conninfo(**(conninfo_to_dict(base) | {"dbname": name}))
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.delenv("SUVA_SCHEMA_ADOPT", raising=False)
    try:
        assert guard.check() == "fresh"
        res = deploy.run_psql(argparse.Namespace(compose=False, url=url), deploy.script_for(deploy.sql_files()), True)
        assert res.returncode == 0, res.stderr
        with pytest.raises(SystemExit, match="no recorded fingerprint"):
            guard.check()  # a schema deployed without the guard is never trusted silently
        monkeypatch.setenv("SUVA_SCHEMA_ADOPT", "1")
        assert guard.check() == "adopt"
        monkeypatch.delenv("SUVA_SCHEMA_ADOPT")
        guard.record()
        assert guard.check() == "same"
        with psycopg.connect(url, autocommit=True) as conn:  # the files change: another image, another schema
            conn.execute(f"ALTER DATABASE \"{name}\" SET {guard.SETTING} = '{'c' * 64}'")
        with pytest.raises(SystemExit, match="deployed from schema cccccccccccc"):
            guard.check()
        # the documented recovery: reset (drop, deploy, record), then the next bootstrap passes. Red before: the reset
        # kept the old fingerprint and the guard refused again, with the same steps
        reset = argparse.Namespace(yes=True, discard_authored=False, compose=False, url=url)
        assert deploy.cmd_reset(reset) == 0
        assert guard.check() == "same"
        with guard._connect(url) as conn:
            assert guard.stored(conn) == guard.shipped()
    finally:
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
