"""Schema for model output and expert edits (db/migrations/002_model_output.sql)."""

from __future__ import annotations

import pytest
from psycopg import errors
from psycopg.types.json import Jsonb

pytestmark = pytest.mark.db

MODELS = Jsonb([{"name": "apertus-v1-5-70b", "role": "relevance classification"}])


def _ruling(conn, docket="8C_72/2025", decision_date="2025-11-03") -> int:
    return conn.execute(
        "INSERT INTO rulings (docket, decision_date, division, in_window) VALUES (%s, %s, %s, true) RETURNING id",
        (docket, decision_date, docket.split("_")[0]),
    ).fetchone()[0]


def _run(conn, kind="triage") -> int:
    return conn.execute("INSERT INTO model_runs (kind, models) VALUES (%s, %s) RETURNING id", (kind, MODELS)).fetchone()[0]


def _count(conn, table) -> int:
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_tables_exist_and_start_empty(db_conn):
    for table in ("model_runs", "predictions", "summaries"):
        assert _count(db_conn, table) == 0, table


# --- model_runs -------------------------------------------------------------------------------------

def test_run_rejects_unknown_kind(db_conn):
    with pytest.raises(errors.CheckViolation):
        _run(db_conn, kind="translate")


@pytest.mark.parametrize("models", [[], {"name": "apertus-v1-5-70b"}])
def test_run_must_list_at_least_one_model(db_conn, models):
    with pytest.raises(errors.CheckViolation):
        db_conn.execute("INSERT INTO model_runs (kind, models) VALUES ('triage', %s)", (Jsonb(models),))


# --- predictions ------------------------------------------------------------------------------------

def test_prediction_roundtrip_with_null_explanation(db_conn):
    rid, run = _ruling(db_conn), _run(db_conn)
    db_conn.execute("INSERT INTO predictions (ruling_id, run_id, score, relevant) VALUES (%s, %s, 0.83, true)", (rid, run))
    row = db_conn.execute("SELECT score, relevant, explanation, details, is_current FROM predictions").fetchone()
    assert row == (0.83, True, None, {}, True)


@pytest.mark.parametrize("score", [-0.01, 1.01])
def test_prediction_rejects_score_outside_0_1(db_conn, score):
    rid, run = _ruling(db_conn), _run(db_conn)
    with pytest.raises(errors.CheckViolation):
        db_conn.execute("INSERT INTO predictions (ruling_id, run_id, score, relevant) VALUES (%s, %s, %s, true)", (rid, run, score))


def test_only_one_current_prediction_per_ruling(db_conn):
    rid, first, second = _ruling(db_conn), _run(db_conn), _run(db_conn)
    db_conn.execute("INSERT INTO predictions (ruling_id, run_id, score, relevant) VALUES (%s, %s, 0.2, false)", (rid, first))
    with pytest.raises(errors.UniqueViolation):
        db_conn.execute("INSERT INTO predictions (ruling_id, run_id, score, relevant) VALUES (%s, %s, 0.9, true)", (rid, second))
    # Retiring the old one first keeps the history and lets the new one in.
    db_conn.execute("UPDATE predictions SET is_current = false WHERE ruling_id = %s", (rid,))
    db_conn.execute("INSERT INTO predictions (ruling_id, run_id, score, relevant) VALUES (%s, %s, 0.9, true)", (rid, second))
    assert db_conn.execute("SELECT score FROM predictions WHERE is_current").fetchall() == [(0.9,)]
    assert _count(db_conn, "predictions") == 2


def test_one_prediction_per_ruling_and_run(db_conn):
    rid, run = _ruling(db_conn), _run(db_conn)
    db_conn.execute("INSERT INTO predictions (ruling_id, run_id, score, relevant, is_current) VALUES (%s, %s, 0.2, false, false)", (rid, run))
    with pytest.raises(errors.UniqueViolation):
        db_conn.execute("INSERT INTO predictions (ruling_id, run_id, score, relevant, is_current) VALUES (%s, %s, 0.3, false, false)", (rid, run))


def test_predictions_go_when_the_ruling_goes(db_conn):
    rid, run = _ruling(db_conn), _run(db_conn)
    db_conn.execute("INSERT INTO predictions (ruling_id, run_id, score, relevant) VALUES (%s, %s, 0.5, true)", (rid, run))
    db_conn.execute("DELETE FROM rulings WHERE id = %s", (rid,))
    assert _count(db_conn, "predictions") == 0


# --- summaries --------------------------------------------------------------------------------------

def _summary(conn, rid, *, language="de", body="Text.", origin="model", run_id=None, parent_id=None, version=1, is_current=True) -> int:
    return conn.execute(
        """INSERT INTO summaries (ruling_id, language, body, origin, run_id, parent_id, version, is_current)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (rid, language, body, origin, run_id, parent_id, version, is_current),
    ).fetchone()[0]


def test_summary_de_and_fr_are_both_current(db_conn):
    rid, run = _ruling(db_conn), _run(db_conn, "summary")
    _summary(db_conn, rid, language="de", run_id=run)
    _summary(db_conn, rid, language="fr", run_id=run)
    assert db_conn.execute("SELECT language, headline FROM summaries WHERE is_current ORDER BY 1").fetchall() == [("de", None), ("fr", None)]


@pytest.mark.parametrize("field, value", [("language", "it"), ("body", "  \n "), ("origin", "robot"), ("version", 0)])
def test_summary_rejects_bad_values(db_conn, field, value):
    rid = _ruling(db_conn)
    with pytest.raises(errors.CheckViolation):
        _summary(db_conn, rid, **{field: value})


def test_expert_edit_is_a_new_version_and_keeps_the_old_one(db_conn):
    rid, run = _ruling(db_conn), _run(db_conn, "summary")
    generated = _summary(db_conn, rid, run_id=run)
    with pytest.raises(errors.UniqueViolation):  # two current versions
        _summary(db_conn, rid, origin="expert", parent_id=generated, version=2)
    db_conn.execute("UPDATE summaries SET is_current = false WHERE id = %s", (generated,))
    _summary(db_conn, rid, body="Korrigiert.", origin="expert", parent_id=generated, version=2)
    rows = db_conn.execute("SELECT version, origin, body, is_current, parent_id FROM summaries ORDER BY version").fetchall()
    assert rows == [(1, "model", "Text.", False, None), (2, "expert", "Korrigiert.", True, generated)]


def test_summary_version_is_unique_per_ruling_and_language(db_conn):
    rid = _ruling(db_conn)
    _summary(db_conn, rid, is_current=False)
    with pytest.raises(errors.UniqueViolation):
        _summary(db_conn, rid, is_current=False)


def test_expert_summary_cannot_claim_a_run(db_conn):
    rid, run = _ruling(db_conn), _run(db_conn, "summary")
    with pytest.raises(errors.CheckViolation):
        _summary(db_conn, rid, origin="expert", run_id=run)


def test_summary_survives_when_its_run_is_deleted(db_conn):
    rid, run = _ruling(db_conn), _run(db_conn, "summary")
    _summary(db_conn, rid, run_id=run)
    db_conn.execute("DELETE FROM model_runs WHERE id = %s", (run,))
    assert db_conn.execute("SELECT run_id FROM summaries").fetchall() == [(None,)]


# --- expert override uses the existing labels table ---------------------------------------------------

def test_expert_override_wins_over_prediction_in_v_relevance(db_conn):
    rid, run = _ruling(db_conn, decision_date="2026-05-12"), _run(db_conn)  # Q2/2026: no label, so 'unknown'
    db_conn.execute("INSERT INTO predictions (ruling_id, run_id, score, relevant) VALUES (%s, %s, 0.1, false)", (rid, run))
    assert db_conn.execute("SELECT relevance, basis FROM v_relevance").fetchone() == ("unknown", "no_label")
    db_conn.execute("INSERT INTO labels (ruling_id, label_set, value, created_by) VALUES (%s, 'expert_override', 'relevant', 'expert')", (rid,))
    assert db_conn.execute("SELECT relevance, basis FROM v_relevance").fetchone() == ("relevant", "expert_override")
