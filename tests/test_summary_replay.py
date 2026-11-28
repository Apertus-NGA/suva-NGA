"""Summaries in replay mode (D-032): answers come from the client's replay cache, a miss is an error.

MOCK DECLARED (G9): `FakeGateway` is an `httpx.MockTransport` endpoint used only to fill a temporary replay
cache through the real client (src/llm/client.py) in live mode. Every replay step then runs with
`httpx.Client` replaced by `_NoNetwork`, which fails the test if anything tries to open a connection.
The database is the real test database (tests/conftest.py).
"""

from __future__ import annotations

import json

import httpx
import pytest

from src.llm import client as llm
from src.llm.client import LLMClient, ReplayMiss
from src.llm.config import LLMConfig
from src.summarize import pipeline, summarize
from src.summarize.prompts import VERSION
from tests.test_summary_pipeline import FICHE, _ruling

LIVE_ENV = {"LLM_NAME": "apertus-v1-5-70b", "LLM_BASE_URL": "https://endpoint.invalid/v1", "LLM_API_KEY": "k"}
MSGS = [{"role": "system", "content": "s"}, {"role": "user", "content": "Fasse das Urteil zusammen."}]


class FakeGateway:
    def __init__(self, content: str):
        self.content, self.requests = content, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(request.content))
        body = {
            "model": "apertus-v1-5-70b",
            "choices": [{"message": {"content": self.content}, "finish_reason": "stop"}],
            "usage": {},
        }
        return httpx.Response(200, json=body, headers={"x-keera-model": "apertus-v1-5-70b"})


class _NoNetwork:
    def __init__(self, *args, **kwargs):
        raise AssertionError("replay mode opened an HTTP client")


@pytest.fixture
def replay_store(tmp_path, monkeypatch):
    """An empty replay store, no LLM_* variables, and no network."""
    for key in ("LLM_NAME", "LLM_NAME_SMALL", "LLM_BASE_URL", "LLM_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(llm, "DEFAULT_STORE", tmp_path)
    monkeypatch.setattr(llm.httpx, "Client", _NoNetwork)
    return tmp_path


def _fill(store, messages, content):
    """Answer `messages` once in live mode, with the parameters summarize.chat uses, so replay can find it."""
    gateway = FakeGateway(content)
    live = LLMClient(LLMConfig.from_env("live", LIVE_ENV), store_dir=store, transport=httpx.MockTransport(gateway))
    live.chat(messages, max_tokens=1200, prompt_version=VERSION)
    live.close()
    assert len(gateway.requests) == 1


def test_chat_in_replay_mode_returns_the_cached_answer_without_a_call(tmp_path, monkeypatch):
    _fill(tmp_path, MSGS, "Die Beschwerde wird abgewiesen.")
    for key in ("LLM_NAME", "LLM_NAME_SMALL", "LLM_BASE_URL", "LLM_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(llm.httpx, "Client", _NoNetwork)
    assert summarize.chat(MSGS, mode="replay", store_dir=tmp_path) == "Die Beschwerde wird abgewiesen."


def test_chat_replay_miss_raises_a_clear_error_and_calls_nothing(replay_store):
    with pytest.raises(ReplayMiss, match="no cached answer"):
        summarize.chat(MSGS, mode="replay")


@pytest.mark.db
def test_summarise_ruling_in_replay_mode_stores_nothing_on_a_miss(db_conn, replay_store):
    rid = _ruling(db_conn)
    with pytest.raises(ReplayMiss):
        pipeline.summarise_ruling(db_conn, rid, mode="replay")
    assert db_conn.execute("SELECT count(*) FROM summaries").fetchone()[0] == 0
    assert db_conn.execute("SELECT count(*) FROM model_runs").fetchone()[0] == 0


@pytest.mark.db
def test_summarise_ruling_default_mode_is_live(db_conn, monkeypatch):
    """The API keeps its default: no mode given means the live client."""
    seen = []
    monkeypatch.setattr(summarize, "chat", lambda messages, mode="live", store_dir=None: seen.append(mode) or "x")
    rid = _ruling(db_conn)
    pipeline.summarise_ruling(db_conn, rid)
    assert seen and set(seen) == {"live"}


@pytest.mark.db
def test_summarise_ruling_records_the_mode_it_ran_in(db_conn, monkeypatch):
    monkeypatch.setattr(summarize, "chat", lambda messages, mode="live", store_dir=None: FICHE[
        "de" if "ausschliesslich Deutsch" in messages[1]["content"] or messages[1]["content"].lstrip().startswith(
            "Überarbeite") else "fr"])  # fmt: skip
    rid = _ruling(db_conn)
    pipeline.summarise_ruling(db_conn, rid, mode="replay")
    params = db_conn.execute("SELECT params FROM model_runs").fetchone()[0]
    assert params["mode"] == "replay"


@pytest.mark.db
def test_pipeline_cli_takes_mode_replay_and_reports_the_miss(db_conn, replay_store, monkeypatch, capsys):
    from suva_data import db

    _ruling(db_conn)
    monkeypatch.setattr(db, "connect", lambda *a, **k: db_conn)
    assert pipeline.main(["--dockets", "8C_900/2025", "--mode", "replay"]) == 1
    out = capsys.readouterr().out
    assert "failed" in out and "no cached answer" in out
    assert db_conn.execute("SELECT count(*) FROM summaries").fetchone()[0] == 0
