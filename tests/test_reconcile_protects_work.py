"""Reconcile never deletes a ruling that carries work, and adding rulings leaves existing ones alone.

"Work" is anything attached to a ruling: a Suva label, an expert override, a reference summary,
a generated or expert-edited summary, a relevance prediction.
"""

import pytest
from psycopg.types.json import Jsonb

from src.suva_data import config
from src.suva_data import reconcile as rec
from tests.test_reconcile import GOOD, R, build, ruling

pytestmark = pytest.mark.db

Q4_ONLY = config.Window("2025-10-01", "2025-12-31")
JAN = dict(docket="8C_500/2025", date="2026-01-20")  # inside the default window, outside Q4_ONLY


def _run(conn, kind):
    return conn.execute(
        "INSERT INTO model_runs (kind, models) VALUES (%s, %s) RETURNING id",
        (kind, Jsonb([{"name": "test-model", "role": "test"}])),
    ).fetchone()[0]


def _summary(conn, ruling_id, body, *, origin="model", version=1, parent_id=None):
    conn.execute("UPDATE summaries SET is_current = false WHERE ruling_id = %s AND language = 'de'", (ruling_id,))
    return conn.execute(
        """INSERT INTO summaries (ruling_id, language, body, origin, run_id, parent_id, version)
           VALUES (%s, 'de', %s, %s, %s, %s, %s) RETURNING id""",
        (ruling_id, body, origin, _run(conn, "summary") if origin == "model" else None, parent_id, version),
    ).fetchone()[0]


def _prediction(conn, ruling_id, score=0.8):
    conn.execute(
        "INSERT INTO predictions (ruling_id, run_id, score, relevant) VALUES (%s, %s, %s, true)",
        (ruling_id, _run(conn, "triage"), score),
    )


def _count(conn, table):
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def _two_rulings(conn):
    """One ruling decided in December, one in January; returns the January ruling's id."""
    build(conn, [R(config.SWISS_CASELAW, "dec", text=GOOD), R(config.SWISS_CASELAW, "jan", text=GOOD, **JAN)])
    return ruling(conn, **JAN)["id"]


# --- nothing that carries work is deleted ---------------------------------------------------------


def test_ruling_with_a_summary_is_not_deleted_when_the_window_narrows(db_conn):
    jan = _two_rulings(db_conn)
    _summary(db_conn, jan, "Zusammenfassung.")
    with pytest.raises(RuntimeError, match="8C_500/2025"):
        rec.reconcile(db_conn, Q4_ONLY)
    # The refusal undoes the whole reconcile: ruling, summary and the link to its source text are as before.
    assert ruling(db_conn, **JAN)["id"] == jan
    assert db_conn.execute("SELECT body FROM summaries WHERE ruling_id = %s", (jan,)).fetchall() == [
        ("Zusammenfassung.",)
    ]
    assert db_conn.execute("SELECT ruling_id FROM source_records WHERE source_key = 'jan'").fetchone()[0] == jan


def test_ruling_with_a_prediction_is_not_deleted_when_the_window_narrows(db_conn):
    jan = _two_rulings(db_conn)
    _prediction(db_conn, jan)
    with pytest.raises(RuntimeError, match="8C_500/2025"):
        rec.reconcile(db_conn, Q4_ONLY)
    assert ruling(db_conn, **JAN)["id"] == jan
    assert _count(db_conn, "predictions") == 1


def test_ruling_without_any_work_is_still_removed_when_the_window_narrows(db_conn):
    _two_rulings(db_conn)
    report = rec.reconcile(db_conn, Q4_ONLY)
    assert report.rulings_removed == 1
    assert ruling(db_conn, **JAN) is None and ruling(db_conn) is not None


# --- adding rulings leaves existing ones alone ------------------------------------------------------


def test_adding_a_new_ruling_keeps_every_edit_on_the_existing_one(db_conn):
    build(db_conn, [R(config.SWISS_CASELAW, "dec", text=GOOD)])
    old = ruling(db_conn)["id"]
    generated = _summary(db_conn, old, "Entwurf des Modells.")
    _summary(db_conn, old, "Von der Expertin korrigiert.", origin="expert", version=2, parent_id=generated)
    _prediction(db_conn, old, 0.91)
    db_conn.execute(
        "INSERT INTO labels (ruling_id, label_set, value) VALUES (%s, 'expert_override', 'not_relevant')",
        (old,),
    )
    before = db_conn.execute(
        "SELECT id, version, origin, body, is_current, parent_id FROM summaries ORDER BY id"
    ).fetchall()

    # A later ingest: the same ruling arrives again (now also from the mirror) together with a new one.
    report = build(
        db_conn,
        [
            R(config.SWISS_CASELAW, "dec", text=GOOD),
            R(config.ENTSCHEIDSUCHE, "dec-mirror", text=GOOD),
            R(config.SWISS_CASELAW, "jan", text=GOOD, **JAN),
        ],
    )

    assert report.rulings == 2 and report.rulings_removed == 0
    assert _count(db_conn, "rulings") == 2  # the existing ruling was not added a second time
    assert ruling(db_conn)["id"] == old
    assert (
        db_conn.execute("SELECT id, version, origin, body, is_current, parent_id FROM summaries ORDER BY id").fetchall()
        == before
    )
    assert db_conn.execute("SELECT score FROM predictions WHERE ruling_id = %s AND is_current", (old,)).fetchall() == [
        (0.91,)
    ]
    assert db_conn.execute("SELECT relevance, basis FROM v_relevance WHERE ruling_id = %s", (old,)).fetchone() == (
        "not_relevant",
        "expert_override",
    )
    new = ruling(db_conn, **JAN)
    assert new is not None and _count(db_conn, "summaries") == 2  # the new ruling starts with no summary of its own


def test_known_ruling_gains_a_publication_date_without_losing_its_summary(db_conn):
    build(db_conn, [R(config.SWISS_CASELAW, "dec", text=GOOD)])
    old = ruling(db_conn)
    assert old["publication_date"] is None
    _summary(db_conn, old["id"], "Zusammenfassung.")
    build(db_conn, [R(config.BGER_LIST, "2026-01-14:8C_72/2025", publication_date="2026-01-14", starred=False)])
    now = ruling(db_conn)
    assert (now["id"], now["publication_date"], now["starred"]) == (old["id"], "2026-01-14", False)
    assert _count(db_conn, "summaries") == 1
