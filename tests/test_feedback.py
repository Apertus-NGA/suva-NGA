"""Expert relevance decisions: status, the append-only record, and its protection (src/suva_app/feedback.py)."""

import pytest
from psycopg import errors
from psycopg.types.json import Jsonb

from suva_app import feedback, queries
from suva_app.queries import RulingFilters
from suva_data import config
from suva_data import reconcile as rec
from tests.test_reconcile import GOOD, R, build, ruling

pytestmark = pytest.mark.db


def _ruling(conn, docket, decided="2026-05-12"):
    return conn.execute(
        "INSERT INTO rulings (docket, decision_date, division, in_window) VALUES (%s, %s, '8C', true) RETURNING id",
        (docket, decided),
    ).fetchone()[0]


def _predict(conn, ruling_id, score):
    run = conn.execute(
        "INSERT INTO model_runs (kind, models) VALUES ('triage', %s) RETURNING id",
        (Jsonb([{"name": "m", "role": "r"}]),),
    ).fetchone()[0]
    return conn.execute(
        "INSERT INTO predictions (ruling_id, run_id, score, relevant) VALUES (%s, %s, %s, %s) RETURNING id",
        (ruling_id, run, score, score >= 0.5),
    ).fetchone()[0]


def _status(conn, ruling_id):
    return feedback.status_of(conn, ruling_id)["status"]


def _events(conn):
    return conn.execute(
        """SELECT action, status_before, status_after, score_shown, reason, comment, actor
           FROM relevance_events ORDER BY id"""
    ).fetchall()


def test_status_comes_from_the_expert_first_and_the_system_otherwise(db_conn):
    plain, potential, ai, listed, negative = (
        _ruling(db_conn, "8C_1/2026"),
        _ruling(db_conn, "8C_2/2026"),
        _ruling(db_conn, "8C_3/2026"),
        _ruling(db_conn, "8C_4/2026"),
        _ruling(db_conn, "8C_5/2025", decided="2025-11-03"),  # a labelled quarter, not on Suva's list
    )
    _predict(db_conn, potential, 0.3)
    _predict(db_conn, ai, 0.8)
    _predict(db_conn, listed, 0.1)
    db_conn.execute(
        "INSERT INTO labels (ruling_id, label_set, value) VALUES (%s, %s, 'relevant')", (listed, config.LABEL_SET_XLSX)
    )
    assert [_status(db_conn, r) for r in (plain, potential, ai, listed, negative)] == [
        "not_assessed", "potentially_relevant", "ai_relevant", "expert_confirmed", "not_relevant",
    ]  # fmt: skip
    assert feedback.status_of(db_conn, 10_000_000) is None


def test_confirming_an_ai_assessed_ruling_records_the_path_and_what_was_shown(db_conn):
    rid = _ruling(db_conn, "8C_3/2026")
    prediction = _predict(db_conn, rid, 0.8)
    result = feedback.decide_relevance(db_conn, rid, "confirm_relevant", comment="  Leitentscheid  ")
    assert (result["status_before"], result["status_after"]) == ("ai_relevant", "expert_confirmed")
    assert _status(db_conn, rid) == "expert_confirmed"
    assert _events(db_conn) == [
        ("confirm_relevant", "ai_relevant", "expert_confirmed", 0.8, None, "Leitentscheid", "expert")
    ]
    assert db_conn.execute("SELECT prediction_id FROM relevance_events").fetchone()[0] == prediction
    assert db_conn.execute("SELECT value, created_by FROM labels WHERE label_set = 'expert_override'").fetchall() == [
        ("relevant", "expert")
    ]


def test_rejecting_then_reopening_keeps_every_step(db_conn):
    rid = _ruling(db_conn, "8C_3/2026")
    _predict(db_conn, rid, 0.8)
    feedback.decide_relevance(db_conn, rid, "mark_not_relevant", reason="routine")
    assert _status(db_conn, rid) == "not_relevant"
    feedback.decide_relevance(db_conn, rid, "confirm_relevant")
    feedback.decide_relevance(db_conn, rid, "reopen")
    assert _status(db_conn, rid) == "ai_relevant"  # back to what the system says
    assert [(a, b, c) for a, b, c, *_ in _events(db_conn)] == [
        ("mark_not_relevant", "ai_relevant", "not_relevant"),
        ("confirm_relevant", "not_relevant", "expert_confirmed"),
        ("reopen", "expert_confirmed", "ai_relevant"),
    ]
    assert db_conn.execute("SELECT count(*) FROM labels").fetchone()[0] == 0


def test_agreeing_with_what_is_already_confirmed_is_still_recorded(db_conn):
    rid = _ruling(db_conn, "8C_4/2026")
    db_conn.execute(
        "INSERT INTO labels (ruling_id, label_set, value) VALUES (%s, %s, 'relevant')", (rid, config.LABEL_SET_XLSX)
    )
    feedback.decide_relevance(db_conn, rid, "confirm_relevant")
    assert [(a, b, c, score) for a, b, c, score, *_ in _events(db_conn)] == [
        ("confirm_relevant", "expert_confirmed", "expert_confirmed", None)
    ]


def test_a_ruling_never_assessed_can_be_confirmed(db_conn):
    rid = _ruling(db_conn, "8C_1/2026")
    result = feedback.decide_relevance(db_conn, rid, "confirm_relevant")
    assert (result["status_before"], result["status_after"]) == ("not_assessed", "expert_confirmed")


def test_bad_action_and_unknown_ruling_write_nothing(db_conn):
    rid = _ruling(db_conn, "8C_1/2026")
    with pytest.raises(ValueError):
        feedback.decide_relevance(db_conn, rid, "delete_everything")
    with pytest.raises(feedback.UnknownRuling):
        feedback.decide_relevance(db_conn, 10_000_000, "confirm_relevant")
    assert _events(db_conn) == [] and db_conn.execute("SELECT count(*) FROM labels").fetchone()[0] == 0


def test_the_event_table_refuses_values_outside_its_lists(db_conn):
    rid = _ruling(db_conn, "8C_1/2026")
    with pytest.raises(errors.CheckViolation):
        db_conn.execute(
            """INSERT INTO relevance_events (ruling_id, action, status_before, status_after)
               VALUES (%s, 'confirm_relevant', 'maybe', 'expert_confirmed')""",
            (rid,),
        )


def test_status_filter_facet_and_learning_transitions(db_conn):
    a, b, c = _ruling(db_conn, "8C_1/2026"), _ruling(db_conn, "8C_2/2026"), _ruling(db_conn, "8C_3/2026")
    _predict(db_conn, a, 0.8)
    _predict(db_conn, b, 0.9)
    _predict(db_conn, c, 0.2)
    feedback.decide_relevance(db_conn, a, "confirm_relevant")
    feedback.decide_relevance(db_conn, b, "confirm_relevant")
    feedback.decide_relevance(db_conn, c, "confirm_relevant")
    feedback.decide_relevance(db_conn, c, "mark_not_relevant")

    def listed(*statuses):
        rows = queries.list_rulings(db_conn, RulingFilters(statuses=list(statuses)))["items"]
        return {r["docket"] for r in rows}

    assert listed("expert_confirmed") == {"8C_1/2026", "8C_2/2026"} and listed("not_relevant") == {"8C_3/2026"}
    assert listed("ai_relevant", "potentially_relevant") == set()
    assert {(f["value"], f["n"]) for f in queries.facets(db_conn)["statuses"]} == {
        ("expert_confirmed", 2),
        ("not_relevant", 1),
    }
    learning = queries.learning(db_conn)
    assert learning["decisions"] == 4 and learning["confirmed_by_experts"] == 2 and learning["rejected_by_experts"] == 1
    assert learning["transitions"] == [
        {"before": "ai_relevant", "after": "expert_confirmed", "n": 2},
        {"before": "expert_confirmed", "after": "not_relevant", "n": 1},
        {"before": "potentially_relevant", "after": "expert_confirmed", "n": 1},
    ]


def test_a_ruling_with_an_expert_decision_cannot_be_removed_by_a_rebuild(db_conn):
    build(
        db_conn,
        [
            R(config.SWISS_CASELAW, "dec", text=GOOD),
            R(config.SWISS_CASELAW, "jan", text=GOOD, docket="8C_500/2025", date="2026-01-20"),
        ],
    )
    jan = ruling(db_conn, "8C_500/2025", "2026-01-20")["id"]
    feedback.decide_relevance(db_conn, jan, "mark_not_relevant")
    feedback.decide_relevance(db_conn, jan, "reopen")  # no label left, only the record of the decisions
    with pytest.raises(RuntimeError, match="8C_500/2025"):
        rec.reconcile(db_conn, config.Window("2025-10-01", "2025-12-31"))
    assert ruling(db_conn, "8C_500/2025", "2026-01-20")["id"] == jan and len(_events(db_conn)) == 2


def test_relevance_events_export_lists_every_transition_with_the_prediction_it_overrode(db_conn):
    scored, bare = _ruling(db_conn, "8C_1/2026"), _ruling(db_conn, "8C_2/2026")
    prediction = _predict(db_conn, scored, 0.8)
    feedback.decide_relevance(db_conn, scored, "mark_not_relevant", comment="kein Bezug")
    feedback.decide_relevance(db_conn, scored, "confirm_relevant")  # the expert changes their mind
    feedback.decide_relevance(db_conn, bare, "mark_not_relevant")  # never assessed: still decidable
    out = queries.relevance_events(db_conn)
    assert out["total"] == 3
    rows = [(e["docket"], e["action"], e["status_before"], e["status_after"], e["prediction_id"],
             e["predicted_relevant"], e["score_shown"]) for e in out["items"]]  # fmt: skip
    assert rows == [  # newest first
        ("8C_2/2026", "mark_not_relevant", "not_assessed", "not_relevant", None, None, None),
        ("8C_1/2026", "confirm_relevant", "not_relevant", "expert_confirmed", prediction, True, 0.8),
        ("8C_1/2026", "mark_not_relevant", "ai_relevant", "not_relevant", prediction, True, 0.8),
    ]
    assert all(e["created_at"] and e["actor"] == "expert" for e in out["items"])
    assert out["items"][2]["comment"] == "kein Bezug"
    assert queries.relevance_events(db_conn, ruling_id=bare)["total"] == 1


def test_sort_by_status_puts_expert_confirmed_first_then_ai_then_potential_then_the_rest(db_conn):
    ids = {
        name: _ruling(db_conn, f"8C_{n}/2026")
        for n, name in enumerate(("gold", "ai", "ai_low", "maybe", "none", "out"), 1)
    }  # noqa: E501
    for name, score in (("gold", 0.2), ("ai", 0.9), ("ai_low", 0.6), ("maybe", 0.3), ("out", 0.95)):
        _predict(db_conn, ids[name], score)
    feedback.decide_relevance(db_conn, ids["gold"], "confirm_relevant")
    feedback.decide_relevance(db_conn, ids["out"], "mark_not_relevant")
    by_id = {v: k for k, v in ids.items()}
    best_first = [by_id[r["id"]] for r in queries.list_rulings(db_conn, sort="status", order="desc")["items"]]
    assert best_first == ["gold", "ai", "ai_low", "maybe", "none", "out"]
    worst_first = [by_id[r["id"]] for r in queries.list_rulings(db_conn, sort="status", order="asc")["items"]]
    assert worst_first == ["out", "none", "maybe", "ai", "ai_low", "gold"]
