"""Regression tests for the API login and transaction settings using a recording DB connection."""

from contextlib import contextmanager
from types import SimpleNamespace

from fastapi.testclient import TestClient

from src import api


def record_connection(monkeypatch, user="suva_api"):
    calls = []
    rows = [{"request_id": "00000000-0000-4000-8000-000000000001"}]

    def execute(sql, params=()):
        calls.append((sql, params))
        return SimpleNamespace(fetchone=lambda: rows[0], fetchall=lambda: [])

    @contextmanager
    def connect(*, actor, pipeline):
        calls.append((actor, pipeline))
        yield SimpleNamespace(info=SimpleNamespace(user=user), execute=execute)

    monkeypatch.setattr(api.pg, "connect", connect)
    return calls


def test_reads_preserve_api_role_and_snapshot(monkeypatch):
    calls = record_connection(monkeypatch)
    response = TestClient(api.app).get("/api/health")
    assert response.json()["current_runs"] == []
    assert calls[:2] == [("expert", False), ("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY", ())]


def test_owner_login_refused_before_query(monkeypatch):
    calls = record_connection(monkeypatch, "suva_owner")
    assert TestClient(api.app).get("/api/health").status_code == 503
    assert calls == [("expert", False)]


def test_request_uses_write_procedure_as_expert(monkeypatch):
    calls = record_connection(monkeypatch)
    response = TestClient(api.app).post("/api/requests", json={"kind": "add_judgement", "docket": "8C_493/2025"})
    assert response.status_code == 202
    assert response.json()["status"] == "pending"
    assert calls == [
        ("expert", False),
        (
            "SELECT ops.submit_request(%s, %s, %s, %s, %s) AS request_id",
            ("add_judgement", "8C_493/2025", None, None, None),
        ),
    ]


def test_invalid_filters_do_not_connect(monkeypatch):
    calls = record_connection(monkeypatch)
    client = TestClient(api.app)
    for query in ["limit=201", "sort=garbage", "published_from=2026-03-01&published_to=2026-02-28"]:
        assert client.get("/api/rulings?" + query).status_code == 422
    assert calls == []
