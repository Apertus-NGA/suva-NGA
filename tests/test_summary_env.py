"""`summarize.load_env` reads `.env` through the data layer's reader and tolerates a missing file.

In Docker `.env` is excluded (.dockerignore), and generate and revise call `load_env` on every request.
MOCK DECLARED (G9): `summarize.chat` is replaced by a lambda in the workspace test; no network, no database.
"""

from __future__ import annotations

import os

from src.summarize import summarize
from suva_app import workspace


def test_load_env_without_a_dotenv_file_does_not_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(summarize, "ROOT", tmp_path)
    summarize.load_env()  # no .env, no .env.local


def test_load_env_sets_missing_variables_and_never_overrides(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text('# comment\nSUMMARY_ENV_A="from file"\nexport SUMMARY_ENV_B=b\nSUMMARY_ENV_C=file\n')
    monkeypatch.setattr(summarize, "ROOT", tmp_path)
    monkeypatch.delenv("SUMMARY_ENV_A", raising=False)
    monkeypatch.delenv("SUMMARY_ENV_B", raising=False)
    monkeypatch.setenv("SUMMARY_ENV_C", "environment")
    try:
        summarize.load_env()
        assert os.environ["SUMMARY_ENV_A"] == "from file"
        assert os.environ["SUMMARY_ENV_B"] == "b"
        assert os.environ["SUMMARY_ENV_C"] == "environment"
    finally:
        os.environ.pop("SUMMARY_ENV_A", None)
        os.environ.pop("SUMMARY_ENV_B", None)


def test_workspace_default_ask_works_without_a_dotenv_file(tmp_path, monkeypatch):
    monkeypatch.setattr(summarize, "ROOT", tmp_path)
    sent = []
    monkeypatch.setattr(summarize, "chat", lambda messages: sent.append(messages) or "fiche")
    assert workspace._default_ask([{"role": "user", "content": "x"}]) == "fiche"
    assert len(sent) == 1
