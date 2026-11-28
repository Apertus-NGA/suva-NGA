"""The ruling page and summary workspace: generate, revise, edit, confirm as gold; every step recorded.

Mock declared (AGENTS.md G9): `FakeModel` (from test_summary_pipeline) stands in for Apertus and records the
prompts it is sent. No network; the database is the real test database.
"""

import pytest
from psycopg import errors
from psycopg.types.json import Jsonb

from suva_app import queries, workspace
from suva_data import config
from suva_data import reconcile as rec
from tests.test_summary_pipeline import FICHE, FakeModel, _ruling

pytestmark = pytest.mark.db


def _events(conn):
    return conn.execute(
        "SELECT language, action, reason, note, unchanged, before_id IS NOT NULL, after_id IS NOT NULL FROM summary_events ORDER BY id"  # noqa: E501
    ).fetchall()


def _versions(conn, rid, language="de"):
    return conn.execute(
        """SELECT version, origin, is_current, confirmed_at IS NOT NULL, body FROM summaries
           WHERE ruling_id = %s AND language = %s ORDER BY version""",
        (rid, language),
    ).fetchall()


@pytest.fixture
def drafted(db_conn):
    """A ruling with a generated German and French summary."""
    rid = _ruling(db_conn)
    workspace.generate(db_conn, rid, ask=FakeModel(), model="m")
    return rid


# --- the page ---------------------------------------------------------------------------------------------------


def test_page_holds_the_ruling_its_text_and_no_summary_yet(db_conn):
    rid = _ruling(db_conn, subject="Unfallversicherung (Kausalzusammenhang)")
    page = workspace.ruling_page(db_conn, rid)
    assert (page["ruling"]["docket"], page["ruling"]["title"], page["ruling"]["status"]) == (
        "8C_900/2025",
        "Kausalzusammenhang",
        "not_relevant",  # decided in a quarter Suva listed completely, and not on that list
    )
    assert page["text"].startswith("Bundesgericht") and page["text_source"] == "swiss_caselaw"
    assert page["summaries"] == {"de": None, "fr": None} and page["reference"] == {"de": None, "fr": None}
    assert page["prompt_category"] == "uv" and "key_point" in page["revisions"]


def test_page_gives_the_reason_of_the_current_prediction_only(db_conn):
    rid = _ruling(db_conn)
    assert workspace.ruling_page(db_conn, rid)["explanation"] is None  # no prediction: no reason, not an empty string
    for text, current in (("Alte Begründung.", False), ("Vermutlich relevant. Dafür: Leitentscheid.", True)):
        run = db_conn.execute(  # one prediction per ruling and run: the older run's is no longer current
            "INSERT INTO model_runs (kind, models) VALUES ('triage', %s) RETURNING id",
            (Jsonb([{"name": "m", "role": "r"}]),),
        ).fetchone()[0]
        db_conn.execute(
            "INSERT INTO predictions (ruling_id, run_id, score, relevant, explanation, is_current) "
            "VALUES (%s, %s, 0.9, true, %s, %s)",
            (rid, run, text, current),
        )
    assert workspace.ruling_page(db_conn, rid)["explanation"] == "Vermutlich relevant. Dafür: Leitentscheid."


def test_page_shows_suvas_text_but_never_its_author(db_conn):
    rid = _ruling(db_conn)
    db_conn.execute(
        "INSERT INTO gold_summaries (ruling_id, language, title, body, author, source_file) VALUES (%s, 'de', 'T', 'Suva-Text.', 'Name Vorname (XYZ)', 'Export.html')",  # noqa: E501
        (rid,),
    )
    page = workspace.ruling_page(db_conn, rid)
    assert page["reference"] == {"de": "Suva-Text.", "fr": None}
    assert "Name Vorname" not in str(page) and "Export.html" not in str(page)


def test_unknown_ruling(db_conn):
    with pytest.raises(workspace.NotFound):
        workspace.ruling_page(db_conn, 10_000_000)


# --- generate ---------------------------------------------------------------------------------------------------


def test_generate_stores_both_languages_and_records_it(db_conn):
    rid = _ruling(db_conn)
    page = workspace.generate(db_conn, rid, ask=FakeModel(), model="m")
    de = page["summaries"]["de"]
    assert (de["version"], de["origin"], de["confirmed"], de["category"]) == (1, "model", False, "uv")
    assert de["body"].endswith("Die Beschwerde wird abgewiesen.") and page["summaries"]["fr"]["body"].endswith(
        "Le recours est rejeté."
    )  # noqa: E501
    assert _events(db_conn) == [
        ("de", "generate", None, None, None, False, True),
        ("fr", "generate", None, None, None, False, True),
    ]  # noqa: E501


# --- confirm as gold ----------------------------------------------------------------------------------------------


def test_confirming_an_unedited_draft_makes_it_gold_and_says_it_was_accepted_unchanged(db_conn, drafted):
    page = workspace.confirm(db_conn, drafted, "de")
    assert page["summaries"]["de"]["confirmed"] is True and page["summaries"]["de"]["origin"] == "model"
    assert page["summaries"]["fr"]["confirmed"] is False
    assert _events(db_conn)[-1] == ("de", "confirm", None, None, True, True, True)
    assert queries.learning(db_conn)["expert_summaries"] == 1 and queries.learning(db_conn)["accepted_unchanged"] == 1
    workspace.confirm(db_conn, drafted, "de")  # confirming twice records nothing new
    assert len(_events(db_conn)) == 3


def test_editing_keeps_the_models_draft_and_the_experts_text_side_by_side(db_conn, drafted):
    page = workspace.save_edit(db_conn, drafted, "de", "  Die Regel, von der Expertin präzisiert.  ")
    assert (
        page["summaries"]["de"]["version"],
        page["summaries"]["de"]["origin"],
        page["summaries"]["de"]["confirmed"],
    ) == (2, "expert", False)  # noqa: E501
    rows = _versions(db_conn, drafted)
    assert [(v, o, cur, conf) for v, o, cur, conf, _ in rows] == [
        (1, "model", False, False),
        (2, "expert", True, False),
    ]  # noqa: E501
    assert rows[1][4] == "Die Regel, von der Expertin präzisiert." and rows[0][4].startswith("Die Leistungspflicht")
    assert db_conn.execute(
        "SELECT parent_id IS NOT NULL FROM summaries WHERE version = 2 AND language = 'de'"
    ).fetchone()[0]  # noqa: E501
    assert _events(db_conn)[-1] == ("de", "edit", None, None, None, True, True)


def test_save_and_confirm_in_one_step_is_gold_and_not_unchanged(db_conn, drafted):
    workspace.save_edit(db_conn, drafted, "de", "Endgültiger Text der Expertin.", confirm=True)
    assert _versions(db_conn, drafted)[-1][:4] == (2, "expert", True, True)
    assert [e[1:5] for e in _events(db_conn)[-2:]] == [("edit", None, None, None), ("confirm", None, None, False)]


def test_saving_the_same_text_records_nothing_and_with_confirm_only_confirms(db_conn, drafted):
    body = workspace.ruling_page(db_conn, drafted)["summaries"]["de"]["body"]
    workspace.save_edit(db_conn, drafted, "de", body)
    assert len(_events(db_conn)) == 2 and len(_versions(db_conn, drafted)) == 1
    workspace.save_edit(db_conn, drafted, "de", body, confirm=True)
    assert (
        _versions(db_conn, drafted)
        and _versions(db_conn, drafted)[0][3] is True
        and _events(db_conn)[-1][1:5] == ("confirm", None, None, True)
    )  # noqa: E501


def test_a_confirmation_can_be_taken_back_and_the_text_stays(db_conn, drafted):
    workspace.confirm(db_conn, drafted, "de")
    page = workspace.unconfirm(db_conn, drafted, "de")
    assert page["summaries"]["de"]["confirmed"] is False and len(_versions(db_conn, drafted)) == 1
    assert _events(db_conn)[-1][1] == "unconfirm"
    with pytest.raises(workspace.NotFound):
        workspace.unconfirm(db_conn, drafted, "de")


def test_a_confirmed_summary_is_not_replaced_when_the_pipeline_runs_again(db_conn, drafted):
    workspace.confirm(db_conn, drafted, "de")
    page = workspace.generate(
        db_conn, drafted, ask=FakeModel({"de": "Ganz anderer Entwurf mit Regel.", "fr": "Un autre projet."}), model="m"
    )  # noqa: E501
    assert (
        page["summaries"]["de"]["confirmed"] is True and page["summaries"]["de"]["version"] == 1
    )  # still the gold one  # noqa: E501
    assert page["summaries"]["fr"]["version"] == 2  # the unconfirmed French draft was replaced


@pytest.mark.parametrize("body", ["", "   \n "])
def test_an_empty_text_is_refused(db_conn, drafted, body):
    with pytest.raises(ValueError):
        workspace.save_edit(db_conn, drafted, "de", body)
    assert len(_versions(db_conn, drafted)) == 1


def test_only_german_and_french(db_conn, drafted):
    with pytest.raises(ValueError):
        workspace.confirm(db_conn, drafted, "it")


# --- revision buttons -----------------------------------------------------------------------------------------------


def test_revision_sends_the_instruction_the_ruling_and_the_current_text_and_stores_the_reason(db_conn, drafted):
    before = workspace.ruling_page(db_conn, drafted)["summaries"]["de"]["body"]
    model = FakeModel(
        {"de": "Kürzere Fassung: Ohne natürlichen Kausalzusammenhang keine Leistung (E. 4.1).", "fr": "x"}
    )  # noqa: E501
    page = workspace.revise(db_conn, drafted, "de", "shorter", ask=model, model="m")
    system, user = model.calls[0][0]["content"], model.calls[0][1]["content"]
    assert "Matter: Unfallversicherung" in system  # still the prompt of the ruling's matter
    assert workspace.REVISIONS["shorter"] in user and before in user and "natürliche Kausalzusammenhang" in user
    de = page["summaries"]["de"]
    assert (de["version"], de["origin"], de["confirmed"]) == (2, "model", False)
    assert (
        de["body"]
        == "Kürzere Fassung: Ohne natürlichen Kausalzusammenhang keine Leistung (E. 4.1). Die Beschwerde wird abgewiesen."  # noqa: E501
    )  # noqa: E501
    assert _events(db_conn)[-1] == ("de", "revise", "shorter", None, None, True, True)
    assert (
        db_conn.execute("SELECT params ->> 'revision' FROM model_runs ORDER BY id DESC LIMIT 1").fetchone()[0]
        == "shorter"
    )  # noqa: E501
    learning = queries.learning(db_conn)
    assert learning["revision_requests"] == 1 and learning["revision_reasons"] == [{"reason": "shorter", "n": 1}]


def test_key_point_revision_carries_the_experts_note(db_conn, drafted):
    model = FakeModel()
    workspace.revise(
        db_conn, drafted, "de", "key_point", note="E. 4.2, natürlicher Kausalzusammenhang", ask=model, model="m"
    )  # noqa: E501
    assert "The expert says: E. 4.2, natürlicher Kausalzusammenhang" in model.calls[0][1]["content"]
    assert _events(db_conn)[-1][2:4] == ("key_point", "E. 4.2, natürlicher Kausalzusammenhang")


@pytest.mark.parametrize("reason", ["key_point", "wrong_statement", "other"])
def test_reasons_that_need_a_note_are_refused_without_one(db_conn, drafted, reason):
    model = FakeModel()
    with pytest.raises(ValueError, match="needs a note"):
        workspace.revise(db_conn, drafted, "de", reason, note="  ", ask=model, model="m")
    assert model.calls == [] and len(_versions(db_conn, drafted)) == 1


def test_align_languages_shows_the_other_languages_summary(db_conn, drafted):
    french = workspace.ruling_page(db_conn, drafted)["summaries"]["fr"]["body"]
    model = FakeModel()
    workspace.revise(db_conn, drafted, "de", "align_languages", ask=model, model="m")
    assert "Fiche in the other language:" in model.calls[0][1]["content"] and french in model.calls[0][1]["content"]


def test_unknown_reason_and_missing_summary(db_conn, drafted):
    with pytest.raises(ValueError):
        workspace.revise(db_conn, drafted, "de", "make_it_nice", ask=FakeModel(), model="m")
    empty = _ruling(db_conn, docket="8C_901/2025")
    with pytest.raises(workspace.NotFound):
        workspace.revise(db_conn, empty, "de", "shorter", ask=FakeModel(), model="m")


def test_a_revision_of_a_confirmed_summary_is_a_new_unconfirmed_draft_and_the_gold_text_is_kept(db_conn, drafted):
    workspace.confirm(db_conn, drafted, "de")
    page = workspace.revise(
        db_conn, drafted, "de", "shorter", ask=FakeModel({"de": "Kurz und mit Regel gefasst.", "fr": "x"}), model="m"
    )  # noqa: E501
    assert page["summaries"]["de"]["confirmed"] is False
    assert [(v, cur, conf) for v, _, cur, conf, _ in _versions(db_conn, drafted)] == [
        (1, False, True),
        (2, True, False),
    ]  # noqa: E501


# --- the record is protected ----------------------------------------------------------------------------------------


def test_event_table_refuses_a_revision_without_a_reason(db_conn, drafted):
    with pytest.raises(errors.CheckViolation):
        db_conn.execute(
            "INSERT INTO summary_events (ruling_id, language, action) VALUES (%s, 'de', 'revise')", (drafted,)
        )  # noqa: E501


def test_a_ruling_with_summary_work_cannot_be_removed_by_a_rebuild(db_conn, drafted):
    with pytest.raises((RuntimeError, errors.ForeignKeyViolation)):
        rec.reconcile(db_conn, config.Window("2020-01-01", "2020-12-31"))
    assert len(_versions(db_conn, drafted)) == 1 and FICHE["de"][:20] in _versions(db_conn, drafted)[0][4]
