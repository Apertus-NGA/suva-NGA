"""Starting an update from the web app and reporting on it (src/suva_app/updates.py).

Mock declared (AGENTS.md G9): the function that performs the ingest is replaced by `fake_run`, which records
a run in `ingest_runs` the way suva_data.ingest does. No network, no source adapter.
"""

import threading
from datetime import date

import pytest

from suva_app.updates import UpdateRunning, Updates
from suva_data import db

pytestmark = pytest.mark.db
TODAY = date(2026, 11, 27)


def _ruling(conn, docket="8C_72/2025", decided="2026-01-15", published="2026-11-10"):
    conn.execute(
        """INSERT INTO rulings (docket, decision_date, publication_date, division, in_window)
           VALUES (%s, %s, %s, '8C', true)""",
        (docket, decided, published),
    )


def recording_run(url, report=None, status="partial", gate: threading.Event | None = None, fail=None):
    """A stand-in for the ingest: waits for `gate` if given, then records a finished run."""

    def fake_run(published_from, published_to):
        if gate is not None:
            assert gate.wait(5)
        if fail:
            raise fail
        with db.connect(url) as conn:
            run_id = db.start_run(conn, "ingest", {"published_from": published_from, "published_to": published_to})
            db.finish_run(conn, run_id, status, report or {})

    return fake_run


@pytest.fixture
def url(db_conn):
    return db_conn.info.dsn + " password=" + (db_conn.info.password or "")


def test_status_before_any_update(db_conn):
    _ruling(db_conn)
    status = Updates(run=lambda a, b: None).status(db_conn, today=TODAY)
    assert status == {
        "running": False,
        "current": None,
        "last": None,
        "last_error": None,
        "last_assessment": None,
        "next_range": {"published_from": "2026-10-27", "published_to": "2026-11-26"},  # newest date held, minus 14 days
        "ingested_rulings": 0,
    }


def test_status_on_an_empty_database_offers_no_range(db_conn):
    assert Updates(run=lambda a, b: None).status(db_conn, today=TODAY)["next_range"] is None


def test_update_since_last_runs_in_the_background_and_its_result_is_reported(db_conn, url):
    _ruling(db_conn)
    report = {
        "new_rulings": 157, "known_rulings": 3, "not_confirmed_by_bger": 157, "new_with_two_texts": 41,
        "text_mismatches": ["12T_3/2025"],
        "bger": {"status": "blocked"}, "daily": {"status": "complete"}, "mirror": {"status": "complete"},
    }  # fmt: skip
    updates = Updates(run=recording_run(url, report))
    started = updates.start(db_conn, today=TODAY)
    assert started == {"published_from": "2026-10-27", "published_to": "2026-11-26"}
    updates.wait(5)
    status = updates.status(db_conn, today=TODAY)
    assert (status["running"], status["current"], status["last_error"]) == (False, None, None)
    last = status["last"]
    assert {k: last[k] for k in ("status", "published_from", "published_to", "new_rulings", "known_rulings")} == {
        "status": "partial", "published_from": "2026-10-27", "published_to": "2026-11-26",
        "new_rulings": 157, "known_rulings": 3,
    }  # fmt: skip
    assert (last["not_confirmed_by_bger"], last["new_with_two_texts"], last["text_mismatches"]) == (157, 41, 1)
    assert last["sources"] == {"bger": "blocked", "daily": "complete", "mirror": "complete"}
    assert last["finished_at"] is not None
    # The next "update now" starts 14 days before the end of this one.
    assert status["next_range"] == {"published_from": "2026-11-12", "published_to": "2026-11-26"}


def test_a_chosen_range_is_used_as_given(db_conn, url):
    updates = Updates(run=recording_run(url, status="ok"))
    assert updates.start(db_conn, "2026-07-01", "2026-07-31") == {
        "published_from": "2026-07-01",
        "published_to": "2026-07-31",
    }
    updates.wait(5)
    last = updates.status(db_conn, today=TODAY)["last"]
    assert (last["status"], last["published_from"], last["published_to"]) == ("ok", "2026-07-01", "2026-07-31")


def test_only_one_update_at_a_time(db_conn, url):
    gate = threading.Event()
    updates = Updates(run=recording_run(url, gate=gate))
    updates.start(db_conn, "2026-07-01", "2026-07-02")
    try:
        status = updates.status(db_conn, today=TODAY)
        assert status["running"] is True and status["current"] == {
            "published_from": "2026-07-01",
            "published_to": "2026-07-02",
        }
        with pytest.raises(UpdateRunning):
            updates.start(db_conn, "2026-07-03", "2026-07-04")
    finally:
        gate.set()
        updates.wait(5)
    assert updates.status(db_conn, today=TODAY)["running"] is False
    updates.start(db_conn, "2026-07-03", "2026-07-04")  # allowed again once the first has finished
    updates.wait(5)


@pytest.mark.parametrize("args", [("2026-07-02", "2026-07-01"), ("2026-07-01", None), (None, "2026-07-01")])
def test_bad_ranges_are_refused_before_anything_starts(db_conn, args):
    calls = []
    updates = Updates(run=lambda a, b: calls.append((a, b)))
    with pytest.raises(ValueError):
        updates.start(db_conn, *args)
    assert calls == [] and updates.running is False


def test_since_last_on_an_empty_database_is_refused(db_conn):
    with pytest.raises(ValueError, match="date range"):
        Updates(run=lambda a, b: None).start(db_conn, today=TODAY)


def test_a_run_that_crashes_is_reported_and_does_not_block_the_next_one(db_conn, url):
    updates = Updates(run=recording_run(url, fail=OSError("disk full")))
    updates.start(db_conn, "2026-07-01", "2026-07-02")
    updates.wait(5)
    status = updates.status(db_conn, today=TODAY)
    assert (status["running"], status["last_error"], status["last"]) == (False, "OSError: disk full", None)
    updates.start(db_conn, "2026-07-01", "2026-07-02")
    updates.wait(5)


def test_a_failed_run_is_shown_with_its_error(db_conn, url):
    updates = Updates(run=recording_run(url, {"error": "RuntimeError: refused"}, status="failed"))
    updates.start(db_conn, "2026-07-01", "2026-07-02")
    updates.wait(5)
    last = updates.status(db_conn, today=TODAY)["last"]
    assert (last["status"], last["error"], last["new_rulings"]) == ("failed", "RuntimeError: refused", None)


# --- after the ingest: the new rulings are assessed, so they get their tier ----------------------------------
# Mock declared (G9): `assess` stands in for the triage pipeline (src/triage/pipeline.run_and_store).


def test_the_new_rulings_are_assessed_once_the_ingest_has_finished(db_conn, url):
    _ruling(db_conn)
    order = []

    def assess():
        with db.connect(url) as conn:  # the ingest's run is recorded before the assessment starts
            order.append(conn.execute("SELECT count(*) FROM ingest_runs WHERE status <> 'running'").fetchone()[0])
        return {"mode": "LIVE", "assessed": 12, "suspected_relevant": 3}

    updates = Updates(run=recording_run(url, {"new_rulings": 12}, status="ok"), assess=assess)
    assert updates.status(db_conn, today=TODAY)["last_assessment"] is None
    updates.start(db_conn, today=TODAY)
    updates.wait(5)
    status = updates.status(db_conn, today=TODAY)
    assert order == [1]
    assert status["last_assessment"] == {"status": "ok", "mode": "LIVE", "assessed": 12, "suspected_relevant": 3}
    assert (status["running"], status["last_error"]) == (False, None)


def test_an_assessment_that_fails_is_reported_and_the_ingest_still_counts(db_conn, url):
    def assess():
        raise RuntimeError("replay cache incomplete: 6 readings have no cached answer")

    updates = Updates(run=recording_run(url, {"new_rulings": 2}, status="ok"), assess=assess)
    updates.start(db_conn, "2026-07-01", "2026-07-02")
    updates.wait(5)
    status = updates.status(db_conn, today=TODAY)
    assert status["last"]["new_rulings"] == 2 and status["last_error"] is None
    assert status["last_assessment"] == {
        "status": "failed",
        "error": "RuntimeError: replay cache incomplete: 6 readings have no cached answer",
    }


def test_no_assessment_after_an_ingest_that_crashed(db_conn, url):
    called = []
    updates = Updates(run=recording_run(url, fail=OSError("disk full")), assess=lambda: called.append(1) or {})
    updates.start(db_conn, "2026-07-01", "2026-07-02")
    updates.wait(5)
    assert called == [] and updates.status(db_conn, today=TODAY)["last_assessment"] is None
