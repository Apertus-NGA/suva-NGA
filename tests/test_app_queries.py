"""Ruling list queries and placeholder scores (src/suva_app)."""

from __future__ import annotations

from datetime import date

import pytest
from psycopg.types.json import Jsonb

from suva_app import queries, stub
from suva_app.queries import RulingFilters

pytestmark = pytest.mark.db


def _ruling(
    conn, docket, decided, *, published=None, area=None, subject=None, language="de", outcome=None, starred=None
) -> int:
    return conn.execute(
        """INSERT INTO rulings (docket, decision_date, publication_date, division, language, area, subject, outcome, starred, in_window)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, true) RETURNING id""",
        (docket, decided, published, docket.split("_")[0], language, area, subject, outcome, starred),
    ).fetchone()[0]


def _predict(conn, ruling_id, score, *, params=None) -> None:
    run = conn.execute(
        "INSERT INTO model_runs (kind, models, params) VALUES ('triage', %s, %s) RETURNING id",
        (Jsonb([{"name": "m", "role": "r"}]), Jsonb(params or {})),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO predictions (ruling_id, run_id, score, relevant) VALUES (%s, %s, %s, %s)",
        (ruling_id, run, score, score >= 0.5),
    )


@pytest.fixture
def data(db_conn):
    """Five rulings covering every filter: ids by short name."""
    ids = {
        # accident insurance, German, decided Q1/2026, labelled relevant by Suva, starred
        "uv_de": _ruling(
            db_conn,
            "8C_72/2025",
            "2026-01-15",
            published="2026-02-10",
            area="Unfallversicherung",
            subject="Unfallversicherung (Kausalzusammenhang)",
            outcome="dismissed",
            starred=True,
        ),
        # accident insurance, French, decided Q2/2026, not yet on a bger.ch list: area and star unknown
        "uv_fr": _ruling(
            db_conn,
            "8C_607/2025",
            "2026-06-30",
            published="2026-07-24",
            language="fr",
            subject="Assurance-accidents (rente d'invalidité)",
            outcome="approved",
        ),
        # invalidity insurance, decided Q4/2025: a derived negative
        "iv": _ruling(
            db_conn,
            "9C_10/2025",
            "2025-11-03",
            published="2025-11-28",
            area="Invalidenversicherung",
            subject="Invalidenversicherung (Rente)",
            outcome="dismissed",
            starred=False,
        ),
        # military insurance, Italian
        "mv": _ruling(
            db_conn,
            "8C_300/2025",
            "2026-03-02",
            published="2026-03-20",
            language="it",
            area="Assicurazione militare",
            subject="Assicurazione militare",
            starred=False,
        ),
        # criminal procedure, no publication date, no prediction
        "other": _ruling(
            db_conn, "7B_5/2026", "2026-05-12", area="Strafprozess", subject="Haft", outcome="inadmissible"
        ),
    }
    db_conn.execute(
        "INSERT INTO labels (ruling_id, label_set, value) VALUES (%s, 'suva_xlsx_2025Q4_2026Q1', 'relevant')",
        (ids["uv_de"],),
    )
    for name, score in (("uv_de", 0.91), ("uv_fr", 0.666), ("iv", 0.12), ("mv", 0.5)):
        _predict(db_conn, ids[name], score)
    return ids


def _dockets(conn, filters=None, **kwargs) -> list[str]:
    return [r["docket"] for r in queries.list_rulings(conn, filters, **kwargs)["items"]]


def test_no_filter_returns_everything_newest_decision_first(db_conn, data):
    result = queries.list_rulings(db_conn)
    assert result["total"] == 5
    assert [r["docket"] for r in result["items"]] == [
        "8C_607/2025",
        "7B_5/2026",
        "8C_300/2025",
        "8C_72/2025",
        "9C_10/2025",
    ]


def test_row_shape(db_conn, data):
    row = next(r for r in queries.list_rulings(db_conn)["items"] if r["docket"] == "8C_72/2025")
    assert row == {
        "id": data["uv_de"],
        "docket": "8C_72/2025",
        "decision_date": date(2026, 1, 15),
        "publication_date": date(2026, 2, 10),
        "division": "8C",
        "language": "de",
        "starred": True,
        "area": "Unfallversicherung",
        "subject": "Unfallversicherung (Kausalzusammenhang)",
        "outcome": "dismissed",
        "official_url": None,
        "label": "relevant",
        "label_basis": "suva_xlsx",
        "score": 91,
        "predicted_relevant": True,
        "has_gold_summary": False,
        "has_summary": False,
        "topic": "UV",
        "publication_source": None,
        "ingested_at": None,
        "title": "Kausalzusammenhang",
        "status": "expert_confirmed",
    }


def test_area_falls_back_to_subject_prefix_and_invalidity_pension_stays_accident(db_conn, data):
    row = next(r for r in queries.list_rulings(db_conn)["items"] if r["docket"] == "8C_607/2025")
    assert (row["area"], row["topic"], row["score"]) == ("Assurance-accidents", "UV", 67)


def test_unscored_ruling_has_null_score_not_zero(db_conn, data):
    row = next(r for r in queries.list_rulings(db_conn)["items"] if r["docket"] == "7B_5/2026")
    assert (row["score"], row["predicted_relevant"], row["topic"], row["label"]) == (None, None, None, "unknown")


def test_decision_date_and_publication_date_are_separate_filters(db_conn, data):
    june_decided = RulingFilters(decided_from=date(2026, 6, 1), decided_to=date(2026, 6, 30))
    june_published = RulingFilters(published_from=date(2026, 6, 1), published_to=date(2026, 6, 30))
    july_published = RulingFilters(published_from=date(2026, 7, 1), published_to=date(2026, 7, 31))
    assert _dockets(db_conn, june_decided) == ["8C_607/2025"]
    assert _dockets(db_conn, june_published) == []
    assert _dockets(db_conn, july_published) == ["8C_607/2025"]


def test_date_bounds_are_inclusive(db_conn, data):
    assert _dockets(db_conn, RulingFilters(decided_from=date(2026, 3, 2), decided_to=date(2026, 3, 2))) == [
        "8C_300/2025"
    ]


@pytest.mark.parametrize(
    "filters, expected",
    [
        (RulingFilters(topics=["UV"]), {"8C_72/2025", "8C_607/2025"}),
        (RulingFilters(topics=["UV", "MV", "IV"]), {"8C_72/2025", "8C_607/2025", "8C_300/2025", "9C_10/2025"}),
        (RulingFilters(areas=["Assurance-accidents"]), {"8C_607/2025"}),
        (RulingFilters(divisions=["9C", "7B"]), {"9C_10/2025", "7B_5/2026"}),
        (RulingFilters(languages=["fr", "it"]), {"8C_607/2025", "8C_300/2025"}),
        (RulingFilters(outcomes=["dismissed"]), {"8C_72/2025", "9C_10/2025"}),
        (RulingFilters(labels=["relevant"]), {"8C_72/2025"}),
        (RulingFilters(labels=["not_relevant"]), {"9C_10/2025", "8C_300/2025"}),
        (RulingFilters(labels=["unknown"]), {"8C_607/2025", "7B_5/2026"}),
        (RulingFilters(starred=True), {"8C_72/2025"}),
        (RulingFilters(starred=False), {"9C_10/2025", "8C_300/2025"}),
        (RulingFilters(predicted_relevant=True), {"8C_72/2025", "8C_607/2025", "8C_300/2025"}),
        (RulingFilters(predicted_relevant=False), {"9C_10/2025"}),
        (RulingFilters(score_min=67), {"8C_72/2025", "8C_607/2025"}),
        (RulingFilters(score_min=50, score_max=67), {"8C_607/2025", "8C_300/2025"}),
        (RulingFilters(score_max=12), {"9C_10/2025"}),
        (RulingFilters(q="8c_72"), {"8C_72/2025"}),
        (RulingFilters(q="rente"), {"8C_607/2025", "9C_10/2025"}),
        (RulingFilters(q="  "), {"8C_72/2025", "8C_607/2025", "9C_10/2025", "8C_300/2025", "7B_5/2026"}),
        (RulingFilters(topics=["UV"], languages=["de"], score_min=80), {"8C_72/2025"}),
    ],
)
def test_filters(db_conn, data, filters, expected):
    result = queries.list_rulings(db_conn, filters)
    assert {r["docket"] for r in result["items"]} == expected
    assert result["total"] == len(expected)


def test_search_treats_underscore_and_percent_literally(db_conn, data):
    assert _dockets(db_conn, RulingFilters(q="8C_607/2025")) == ["8C_607/2025"]
    assert (
        _dockets(db_conn, RulingFilters(q="8C_607_2025")) == []
    )  # "_" is not "any character", so it does not stand in for "/"
    assert _dockets(db_conn, RulingFilters(q="%")) == []


def test_sort_by_score_puts_unscored_last_in_both_directions(db_conn, data):
    assert _dockets(db_conn, sort="score", order="desc") == [
        "8C_72/2025",
        "8C_607/2025",
        "8C_300/2025",
        "9C_10/2025",
        "7B_5/2026",
    ]
    assert _dockets(db_conn, sort="score", order="asc") == [
        "9C_10/2025",
        "8C_300/2025",
        "8C_607/2025",
        "8C_72/2025",
        "7B_5/2026",
    ]


def test_sort_by_publication_date_puts_unpublished_last(db_conn, data):
    assert _dockets(db_conn, sort="publication_date", order="asc")[-1] == "7B_5/2026"
    assert _dockets(db_conn, sort="publication_date", order="desc")[-1] == "7B_5/2026"


def test_paging_covers_every_row_once(db_conn, data):
    pages = [queries.list_rulings(db_conn, sort="area", limit=2, offset=o) for o in (0, 2, 4)]
    assert [p["total"] for p in pages] == [5, 5, 5]
    seen = [r["docket"] for p in pages for r in p["items"]]
    assert len(seen) == 5 and len(set(seen)) == 5


@pytest.mark.parametrize("kwargs", [{"sort": "id; DROP TABLE rulings"}, {"sort": "nope"}, {"order": "sideways"}])
def test_unknown_sort_or_order_is_refused(db_conn, kwargs):
    with pytest.raises(ValueError):
        queries.list_rulings(db_conn, **kwargs)


def test_only_the_current_prediction_counts(db_conn, data):
    db_conn.execute("UPDATE predictions SET is_current = false WHERE ruling_id = %s", (data["iv"],))
    _predict(db_conn, data["iv"], 0.8)
    result = queries.list_rulings(db_conn)
    assert result["total"] == 5  # no duplicate row for the ruling with two predictions
    assert next(r for r in result["items"] if r["docket"] == "9C_10/2025")["score"] == 80


def test_expert_override_changes_the_label(db_conn, data):
    db_conn.execute(
        "INSERT INTO labels (ruling_id, label_set, value) VALUES (%s, 'expert_override', 'not_relevant')",
        (data["uv_de"],),
    )
    row = next(r for r in queries.list_rulings(db_conn)["items"] if r["docket"] == "8C_72/2025")
    assert (row["label"], row["label_basis"]) == ("not_relevant", "expert_override")


def test_facets(db_conn, data):
    f = queries.facets(db_conn)
    assert (f["total"], f["scored"], f["stub_scores"]) == (5, 4, False)
    assert (f["decided_min"], f["decided_max"]) == (date(2025, 11, 3), date(2026, 6, 30))
    assert (f["published_min"], f["published_max"]) == (date(2025, 11, 28), date(2026, 7, 24))
    assert f["topics"] == [{"value": "UV", "n": 2}, {"value": "IV", "n": 1}, {"value": "MV", "n": 1}]
    assert f["divisions"] == [{"value": "7B", "n": 1}, {"value": "8C", "n": 3}, {"value": "9C", "n": 1}]
    assert {"value": "Assurance-accidents", "n": 1} in f["areas"]
    assert {(x["value"], x["n"]) for x in f["labels"]} == {("relevant", 1), ("not_relevant", 2), ("unknown", 2)}


def test_facets_on_empty_database(db_conn):
    f = queries.facets(db_conn)
    assert (f["total"], f["scored"], f["stub_scores"], f["areas"], f["decided_min"]) == (0, 0, False, [], None)


# --- placeholder scores -------------------------------------------------------------------------------


def test_stub_score_is_deterministic_and_in_range():
    assert stub.stub_score("8C_72/2025", "UV", "unknown") == stub.stub_score("8C_72/2025", "UV", "unknown")
    for i in range(200):
        for topic, label in ((None, "unknown"), ("UV", "unknown"), ("IV", "not_relevant"), ("UV", "relevant")):
            assert 0.01 <= stub.stub_score(f"8C_{i}/2025", topic, label) <= 0.99


def test_stub_seed_fills_only_unscored_rulings_and_is_flagged(db_conn, data):
    assert stub.seed(db_conn) == 1  # only 7B_5/2026 had no prediction
    assert stub.seed(db_conn) == 0  # nothing left to fill, and no empty run is created
    f = queries.facets(db_conn)
    assert (f["scored"], f["stub_scores"]) == (5, True)
    assert db_conn.execute("SELECT count(*) FROM model_runs WHERE (params ->> 'stub')::boolean").fetchone()[0] == 1


def test_stub_remove_deletes_placeholders_and_keeps_real_predictions(db_conn, data):
    stub.seed(db_conn)
    assert stub.remove(db_conn) == 1
    f = queries.facets(db_conn)
    assert (f["scored"], f["stub_scores"]) == (4, False)
    assert stub.remove(db_conn) == 0


# --- titles ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "subject, area, expected",
    [
        (
            "Unfallversicherung (Fallabschluss; Kausalzusammenhang)",
            "Unfallversicherung",
            "Fallabschluss; Kausalzusammenhang",
        ),
        ("Assurance-accidents (rente d'invalidité)", "Assurance-accidents", "Rente d'invalidité"),
        ("Invalidenversicherung, Invalidenrente", "Invalidenversicherung", "Invalidenrente"),
        ("Unfallversicherung", "Unfallversicherung", None),  # says no more than the area
        ("Garantievertrag,", "Vertragsrecht", "Garantievertrag"),  # stray comma from the source
        (
            "Rechtsverweigerung (Prozessvoraussetzung)",
            "Invalidenversicherung",
            "Rechtsverweigerung (Prozessvoraussetzung)",
        ),
        (
            "Unfallversicherungsgesetz, Revision",
            "Unfallversicherung",
            "Unfallversicherungsgesetz, Revision",
        ),  # not the area + keywords
        ("Unfallversicherung (Rente) und weiteres", "Unfallversicherung", "Unfallversicherung (Rente) und weiteres"),
        ("Haft", None, "Haft"),
        (None, "Strafprozess", None),
        ("  ", None, None),
    ],
)
def test_display_title(subject, area, expected):
    assert queries.display_title(subject, area) == expected


def test_list_gives_title_next_to_the_unchanged_subject(db_conn, data):
    rows = {r["docket"]: r for r in queries.list_rulings(db_conn)["items"]}
    assert (rows["8C_607/2025"]["title"], rows["8C_607/2025"]["subject"]) == (
        "Rente d'invalidité",
        "Assurance-accidents (rente d'invalidité)",
    )
    assert rows["8C_300/2025"]["title"] is None  # "Assicurazione militare": the area only
    assert rows["7B_5/2026"]["title"] == "Haft"


# --- rulings added by an update ---------------------------------------------------------------------------


def test_ingested_filter_and_fields(db_conn, data):
    db_conn.execute(
        "INSERT INTO ingested_rulings (docket, decision_date, published_from, published_to) VALUES ('8C_607/2025', '2026-06-30', '2026-07-24', '2026-07-24')"
    )
    db_conn.execute(
        """UPDATE rulings SET field_sources = '{"publication_date": "bger_list"}' WHERE docket = '8C_72/2025'"""
    )
    assert _dockets(db_conn, RulingFilters(ingested=True)) == ["8C_607/2025"]
    assert len(_dockets(db_conn, RulingFilters(ingested=False))) == 4
    rows = {r["docket"]: r for r in queries.list_rulings(db_conn)["items"]}
    assert rows["8C_607/2025"]["ingested_at"] is not None and rows["8C_72/2025"]["ingested_at"] is None
    assert rows["8C_72/2025"]["publication_source"] == "bger_list" and rows["8C_607/2025"]["publication_source"] is None


# --- summaries and the learning numbers ---------------------------------------------------------------------


def _gold(conn, ruling_id, language="de"):
    conn.execute(
        "INSERT INTO gold_summaries (ruling_id, language, title, body) VALUES (%s, %s, 'Titel', 'Text.')",
        (ruling_id, language),
    )


def _summary(conn, ruling_id, origin):
    run = None
    if origin == "model":
        run = conn.execute(
            "INSERT INTO model_runs (kind, models) VALUES ('summary', %s) RETURNING id",
            (Jsonb([{"name": "m", "role": "r"}]),),
        ).fetchone()[0]
    conn.execute(
        "INSERT INTO summaries (ruling_id, language, body, origin, run_id) VALUES (%s, 'de', 'Text.', %s, %s)",
        (ruling_id, origin, run),
    )


def test_summarised_filter_covers_reference_and_generated_summaries(db_conn, data):
    _gold(db_conn, data["uv_de"])
    _summary(db_conn, data["iv"], "model")
    assert set(_dockets(db_conn, RulingFilters(summarised=True))) == {"8C_72/2025", "9C_10/2025"}
    assert len(_dockets(db_conn, RulingFilters(summarised=False))) == 3


def test_learning_numbers(db_conn, data):
    empty = queries.learning(db_conn)
    assert {k: v for k, v in empty.items() if v} == {"relevant_rulings": 1}
    assert set(empty) == {
        "relevant_rulings", "confirmed_by_experts", "rejected_by_experts", "reference_summaries", "generated_summaries",
        "expert_summaries", "revision_requests", "accepted_unchanged", "decisions", "transitions", "revision_reasons",
    }  # fmt: skip
    _gold(db_conn, data["uv_de"], "de")
    _gold(db_conn, data["uv_de"], "fr")
    _summary(db_conn, data["iv"], "model")
    _summary(db_conn, data["mv"], "expert")
    db_conn.execute("UPDATE summaries SET confirmed_at = now(), confirmed_by = 'expert' WHERE origin = 'expert'")
    db_conn.execute(
        "INSERT INTO labels (ruling_id, label_set, value) VALUES (%s, 'expert_override', 'relevant')", (data["uv_fr"],)
    )
    db_conn.execute(
        "INSERT INTO labels (ruling_id, label_set, value) VALUES (%s, 'expert_override', 'not_relevant')", (data["iv"],)
    )
    numbers = queries.learning(db_conn)
    assert {k: numbers[k] for k in ("relevant_rulings", "confirmed_by_experts", "rejected_by_experts", "reference_summaries",
                                    "generated_summaries", "expert_summaries")} == {
        "relevant_rulings": 2, "confirmed_by_experts": 1, "rejected_by_experts": 1,
        "reference_summaries": 1, "generated_summaries": 1, "expert_summaries": 1,
    }  # fmt: skip
