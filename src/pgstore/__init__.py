"""Postgres access shared by the reference adapters of the classifier, the summarizer and the app.

The three components keep their logic free of SQL. Their Postgres adapters target the schema in
``db/migrations/`` and reach the database only through these names. They are the ingestion package's
plumbing (``src/suva_data/db.py``, ``src/suva_data/config.py``) under one stable import, so an adapter for
another schema can replace this module without touching the components.
"""

from __future__ import annotations

import psycopg

from src.suva_data import config
from src.suva_data.db import git_commit, migrate, strip_nul

REPO = config.REPO
MIGRATIONS_DIR = config.MIGRATIONS_DIR

__all__ = ["REPO", "MIGRATIONS_DIR", "database_url", "connect", "migrate", "strip_nul", "git_commit"]


def database_url() -> str:
    """``DATABASE_URL`` (environment or ``.env``, read by ``src/suva_data/config.py``)."""
    return config.DATABASE_URL


def connect(url: str | None = None, **kwargs) -> psycopg.Connection:
    """Open a psycopg (v3) connection to ``url`` (default: ``database_url()``). Autocommit unless overridden."""
    kwargs.setdefault("autocommit", True)
    return psycopg.connect(url or database_url(), **kwargs)
