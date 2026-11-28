"""Per-person settings: suva_data reads `.env.local` and `.env` at the repo root; the environment wins."""

import os

from suva_data import config


def _write(path, text):
    path.write_text(text, encoding="utf-8")


def test_reads_key_value_lines_and_ignores_comments_blanks_and_empty_values(tmp_path):
    _write(
        tmp_path / ".env",
        "# a comment\n\nDATABASE_URL=postgresql://someone@localhost:5432/suva\nLLM_NAME=\n"
        "  SUVA_DATA_DIR = /tmp/x  \nnot a setting\n",
    )
    assert config.read_env_files(tmp_path) == {
        "DATABASE_URL": "postgresql://someone@localhost:5432/suva",
        "SUVA_DATA_DIR": "/tmp/x",
    }


def test_quotes_and_export_prefix_are_accepted(tmp_path):
    _write(tmp_path / ".env", "export DATABASE_URL=\"postgresql://a@h/db\"\nSUVA_DATA_DIR='/data dir'\n")
    assert config.read_env_files(tmp_path) == {"DATABASE_URL": "postgresql://a@h/db", "SUVA_DATA_DIR": "/data dir"}


def test_value_may_contain_equal_signs(tmp_path):
    _write(tmp_path / ".env", "DATABASE_URL=postgresql://a@h/db?sslmode=require&application_name=x\n")
    assert config.read_env_files(tmp_path)["DATABASE_URL"] == "postgresql://a@h/db?sslmode=require&application_name=x"


def test_env_local_wins_over_env(tmp_path):
    _write(tmp_path / ".env", "DATABASE_URL=from-env\nSUVA_DATA_DIR=shared\n")
    _write(tmp_path / ".env.local", "DATABASE_URL=from-local\n")
    assert config.read_env_files(tmp_path) == {"DATABASE_URL": "from-local", "SUVA_DATA_DIR": "shared"}


def test_no_files_is_fine(tmp_path):
    assert config.read_env_files(tmp_path) == {}


def test_setting_order_is_environment_then_files_then_default():
    files = {"DATABASE_URL": "from-file"}
    assert config.setting("DATABASE_URL", "default", env={"DATABASE_URL": "from-env"}, files=files) == "from-env"
    assert config.setting("DATABASE_URL", "default", env={}, files=files) == "from-file"
    assert config.setting("DATABASE_URL", "default", env={}, files={}) == "default"
    # An empty variable means "not set", like an empty line in .env.example.
    assert config.setting("DATABASE_URL", "default", env={"DATABASE_URL": ""}, files=files) == "from-file"


def test_reading_the_files_does_not_touch_the_process_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    _write(tmp_path / ".env", "LLM_API_KEY=would-be-a-secret\n")
    config.read_env_files(tmp_path)
    assert "LLM_API_KEY" not in os.environ
