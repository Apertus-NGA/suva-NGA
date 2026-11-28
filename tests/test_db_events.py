"""`src.db.runs.events` is idempotent per (run_id, seq) (L2-F20). Runs only with DATABASE_URL: it creates a throwaway
database, deploys src/db/sql and the SQL fixture (tests/sql/_fixtures.sql, for a profile version), and drops it.

`ops.log_event` is partitioned by `ts`, so its key is (run_id, seq, ts) and a unique (run_id, seq) is impossible;
`ts` is the real clock time of the insert. Before the fix, emitting a run's events again (a reload of its files)
added a second row per seq, since `ON CONFLICT` never saw a conflict on a new timestamp. Now an event is inserted only
when its run has no row with that seq, and a per-run transaction lock makes a concurrent emission wait for the first
one instead of inserting a duplicate. `finish_run` and `fail_run` close a run and its root span after its events, at
the real clock time, so every event lies within its run's time range. No mock: every assertion reads the stored rows.
"""

from __future__ import annotations

import argparse
import os
import uuid
from pathlib import Path

import pytest

pytestmark = [pytest.mark.db, pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="needs DATABASE_URL")]

FIXTURE = Path(__file__).parent / "sql" / "_fixtures.sql"
STEP = "layer1_filter"


@pytest.fixture(scope="module")
def database():
    import psycopg
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    from src.db import deploy

    base = os.environ["DATABASE_URL"]
    name = f"suva_test_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    url = make_conninfo(**(conninfo_to_dict(base) | {"dbname": name}))
    try:
        ns = argparse.Namespace(compose=False, url=url)
        res = deploy.run_psql(ns, deploy.script_for(deploy.sql_files()), capture=True)
        assert res.returncode == 0, res.stderr
        script = f"\\set ON_ERROR_STOP on\nBEGIN;\n{deploy.expand_includes(FIXTURE)}\nCOMMIT;\n"
        res = deploy.run_psql(ns, script, capture=True)
        assert res.returncode == 0, res.stderr
        yield url
    finally:
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _run(conn):
    from src.db.runs import begin_run

    with conn.cursor() as cur:
        cur.execute("SELECT profile_version_id::text FROM ops.pipeline_profile_version WHERE profile_code = 'default'")
        pvid = cur.fetchone()[0]
    return begin_run(
        conn,
        profile_version_id=pvid,
        kind="layer1",
        step=STEP,
        operation="test.events",
        component_version_id=None,
        params={"test": "events"},
        code_paths=("src/db/runs.py",),
        actor="test",
    )


def _rows(conn, run_id: str) -> list[tuple]:
    return conn.execute(
        "SELECT seq, ts, message FROM ops.log_event WHERE run_id = %s ORDER BY seq, ts", (run_id,)
    ).fetchall()


def _event(seq: int, message: str) -> tuple:
    return (seq, "info", "layer1.test.emitted", message, {"seq": seq}, None, None)


def test_emitting_the_same_events_twice_leaves_one_row_per_seq(database):
    from src.db.pg import connect
    from src.db.runs import events

    with connect(database, actor="test") as conn:
        run = _run(conn)
        before = conn.execute("SELECT clock_timestamp()").fetchone()[0]
        conn.commit()
        with conn.transaction(), conn.cursor() as cur:
            events(cur, run, STEP, [_event(1, "first"), _event(2, "first"), _event(3, "first")])
        first = _rows(conn, run.run_id)
        conn.commit()
        with conn.transaction(), conn.cursor() as cur:  # a reload of the run's events, plus a new one
            events(cur, run, STEP, [_event(1, "again"), _event(2, "again"), _event(3, "again"), _event(4, "new")])
        with conn.transaction(), conn.cursor() as cur:  # a seq repeated inside one call
            events(cur, run, STEP, [_event(5, "once"), _event(5, "twice")])
        after = conn.execute("SELECT clock_timestamp()").fetchone()[0]
        stored = _rows(conn, run.run_id)
        conn.commit()

    assert [seq for seq, _, _ in stored] == [1, 2, 3, 4, 5]  # one row per seq
    assert stored[:3] == first  # the first emission is kept, timestamp and content
    assert [m for _, _, m in stored] == ["first", "first", "first", "new", "once"]
    assert all(before <= ts <= after for _, ts, _ in stored)  # the real clock time of the insert
    assert len({ts for _, ts, _ in stored}) == 5


def test_a_concurrent_emission_of_the_same_run_waits_and_adds_nothing(database):
    import psycopg

    from src.db.pg import connect
    from src.db.runs import events

    with connect(database, actor="test") as first, connect(database, actor="test") as second:
        run = _run(first)
        second.execute("SET lock_timeout = '300ms'")
        second.commit()
        with first.transaction(), first.cursor() as cur:
            events(cur, run, STEP, [_event(1, "first")])  # not committed yet: invisible to the second session
            with pytest.raises(psycopg.errors.LockNotAvailable):
                with second.transaction(), second.cursor() as cur2:
                    events(cur2, run, STEP, [_event(1, "second")])
        with second.transaction(), second.cursor() as cur2:  # after the first commit: sees its row, adds nothing
            events(cur2, run, STEP, [_event(1, "second")])
        stored = _rows(second, run.run_id)
        second.commit()
    assert [(seq, m) for seq, _, m in stored] == [(1, "first")]


def test_every_event_of_a_closed_run_lies_within_its_run_and_root_span(database):
    """The run and its root span close with the real clock time (`clock_timestamp()`), after the events the closing
    transaction wrote: `now()` is the transaction start, so before the fix every event of a run was stamped after its
    run's `finished_at` (review fix). A failed run (`fail_run`) also closes after its last committed event."""
    from src.db.pg import connect
    from src.db.runs import events, fail_run, finish_run

    with connect(database, actor="test") as conn:
        ok, failed = _run(conn), _run(conn)
        with conn.transaction(), conn.cursor() as cur:  # a step's closing transaction: events, then the close
            events(cur, ok, STEP, [_event(1, "decided"), _event(2, "files")])
            finish_run(cur, ok)
        with conn.transaction(), conn.cursor() as cur:  # a committed event, then a failure
            events(cur, failed, STEP, [_event(1, "before the failure")])
        fail_run(conn, failed, RuntimeError("synthetic failure"))
        bounds = {
            run_id: (started, finished, span_started, span_ended, status)
            for run_id, started, finished, span_started, span_ended, status in conn.execute(
                """SELECT pr.run_id::text, pr.started_at, pr.finished_at, s.started_at, s.ended_at, pr.status::text
                   FROM ops.pipeline_run pr JOIN ops.span s ON s.run_id = pr.run_id AND s.parent_span_id IS NULL
                   WHERE pr.run_id IN (%s, %s)""",
                (ok.run_id, failed.run_id),
            ).fetchall()
        }
        stored = {run.run_id: [ts for _, ts, _ in _rows(conn, run.run_id)] for run in (ok, failed)}
        conn.commit()

    assert {run_id: b[4] for run_id, b in bounds.items()} == {ok.run_id: "succeeded", failed.run_id: "failed"}
    for run_id, stamps in stored.items():
        started, finished, span_started, span_ended, _ = bounds[run_id]
        assert stamps and all(started <= ts <= finished for ts in stamps), (run_id, started, finished, stamps)
        assert all(span_started <= ts <= span_ended for ts in stamps), (run_id, span_started, span_ended, stamps)
