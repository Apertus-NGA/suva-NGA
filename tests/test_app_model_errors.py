"""The summary routes answer 503 with a JSON message when the model is not configured or a replay misses.

MOCK DECLARED (G9): FastAPI's TestClient drives the app in-process (no server, no lifespan, so the real
`suva` database is never opened); `get_conn` is overridden with the test database connection. For the
missing key, nothing is faked: the LLM_* variables are removed and `.env` is pointed at an empty directory,
so the real `client_from_env` raises ConfigError before any call. For the replay miss, `_raise_replay_miss`
stands in for the model and raises the client's ReplayMiss. `httpx.Client` is replaced by `_NoNetwork`.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.llm import client as llm
from src.llm.client import ReplayMiss
from src.summarize import summarize
from suva_app import main, workspace
from tests.test_summary_pipeline import FakeModel, _ruling

pytestmark = pytest.mark.db


class _NoNetwork:
    def __init__(self, *args, **kwargs):
        raise AssertionError("the app opened an HTTP client")


def _raise_replay_miss(messages):
    raise ReplayMiss("no cached answer for abc123 (prompt v2); run in live mode")


@pytest.fixture
def api(db_conn, tmp_path, monkeypatch):
    for key in ("LLM_NAME", "LLM_NAME_SMALL", "LLM_BASE_URL", "LLM_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(summarize, "ROOT", tmp_path)  # no .env to load the key from
    monkeypatch.setattr(llm, "DEFAULT_STORE", tmp_path)
    monkeypatch.setattr(llm.httpx, "Client", _NoNetwork)
    main.app.dependency_overrides[main.get_conn] = lambda: db_conn
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.clear()


def _stored(conn):
    return conn.execute("SELECT count(*) FROM summaries").fetchone()[0]


def test_generate_without_a_key_is_503_with_a_clear_message(api, db_conn):
    rid = _ruling(db_conn)
    r = api.post(f"/api/rulings/{rid}/summaries")
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert "LLM_API_KEY" in detail and "not configured" in detail
    assert _stored(db_conn) == 0


def test_revise_without_a_key_is_503(api, db_conn):
    rid = _ruling(db_conn)
    workspace.generate(db_conn, rid, ask=FakeModel(), model="m")
    before = _stored(db_conn)
    r = api.post(f"/api/rulings/{rid}/summaries/de/revise", json={"reason": "shorter"})
    assert r.status_code == 503
    assert "LLM_API_KEY" in r.json()["detail"]
    assert _stored(db_conn) == before


def test_replay_miss_is_503_with_a_clear_message(api, db_conn, monkeypatch):
    monkeypatch.setattr(workspace, "_default_ask", _raise_replay_miss)
    rid = _ruling(db_conn)
    r = api.post(f"/api/rulings/{rid}/summaries")
    assert r.status_code == 503
    assert "no cached answer" in r.json()["detail"]
    assert _stored(db_conn) == 0


def test_the_export_and_list_routes_answer(api, db_conn):
    rid = _ruling(db_conn)
    workspace.generate(db_conn, rid, ask=FakeModel(), model="m")
    assert api.post(f"/api/rulings/{rid}/relevance", json={"action": "mark_not_relevant"}).status_code == 200
    events = api.get("/api/relevance-events", params={"ruling_id": rid}).json()
    # (a ruling decided in a quarter Suva listed starts as a derived "not relevant": the decision is still recorded)
    assert [(e["action"], e["status_after"]) for e in events["items"]] == [("mark_not_relevant", "not_relevant")]
    assert api.put(f"/api/rulings/{rid}/summaries/de", json={"body": "Neu."}).json()["summaries"]["de"]["version"] == 2
    edits = api.get("/api/summary-events", params={"kind": "edit"}).json()
    assert edits["total"] == 1 and edits["items"][0]["after_text"] == "Neu."
    listed = api.get("/api/rulings", params={"sort": "status", "has_summary": "true", "status": "not_relevant"}).json()
    assert [r["id"] for r in listed["items"]] == [rid]
