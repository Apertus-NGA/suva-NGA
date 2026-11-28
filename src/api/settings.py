"""API settings, read once from the environment (`.env` / `.env.local` are loaded by `src/cli.py`).

No default for a secret or a URL (G3, G13): DATABASE_URL is read by `src/db/pg.py`, PIPELINE_DATABASE_URL here.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass


class SettingsError(ValueError):
    """An API setting has a value the API cannot use."""


def _flag(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    actor: str = "expert"  # app.actor of every session: one shared expert during the event (no person's name, G13)
    db_role: str | None = "suva_api"  # SET ROLE: the API login's own rights, even on an owner URL (F-11)
    statement_timeout_ms: int = 15_000  # the suva_api login's own timeout (90_roles.sql)
    mode: str = "replay"  # what a run started from the API uses by default (D-032)
    runs_enabled: bool = False  # launching pipeline runs is opt-in (API_RUNS_ENABLED=1)
    pipeline_database_url: str | None = None  # the pipeline login for launched runs; default: DATABASE_URL
    layer2_store: str | None = None  # --store of a launched layer-2 run (replay cache); default: the client's own
    layer2_populations: tuple[str, ...] = ()  # --population of a launched layer-2 run; default: every kept ruling
    ai_relevant_min_score: float | None = None  # D-021 stays open: unset = only the ranking step makes ai_relevant
    max_db_sessions: int = 12  # under the suva_api login's 20 connections (90_roles.sql)
    db_wait_s: float = 5.0  # how long a request waits for a free session before 503
    host: str = "127.0.0.1"
    port: int = 8000

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        actor = env.get("API_ACTOR", "expert").strip()
        if not actor:
            raise SettingsError("API_ACTOR is empty: every write needs an actor (ops.require_actor)")
        mode = env.get("MODE", "replay").strip().lower() or "replay"
        if mode not in {"replay", "live"}:
            raise SettingsError(f"MODE must be replay or live, not {mode!r}")
        threshold = None
        raw = env.get("API_AI_RELEVANT_MIN_SCORE", "").strip()
        if raw:
            try:
                threshold = float(raw)
            except ValueError as exc:
                raise SettingsError(f"API_AI_RELEVANT_MIN_SCORE must be a number from 0 to 100, not {raw!r}") from exc
            if not 0 <= threshold <= 100:
                raise SettingsError(f"API_AI_RELEVANT_MIN_SCORE must be from 0 to 100, not {threshold}")
        try:
            timeout = int(env.get("API_STATEMENT_TIMEOUT_MS", "15000"))
            port = int(env.get("API_PORT", "8000"))
            sessions = int(env.get("API_MAX_DB_SESSIONS", "12"))
        except ValueError as exc:
            raise SettingsError(
                f"API_STATEMENT_TIMEOUT_MS, API_PORT, API_MAX_DB_SESSIONS must be integers: {exc}"
            ) from exc
        if not 1 <= sessions <= 20:
            raise SettingsError(
                f"API_MAX_DB_SESSIONS must be from 1 to 20 (the suva_api login allows 20), not {sessions}"
            )
        populations = tuple(p.strip() for p in env.get("API_LAYER2_POPULATIONS", "").split(",") if p.strip())
        return cls(
            actor=actor,
            db_role=env.get("API_DB_ROLE", "suva_api").strip() or None,
            statement_timeout_ms=timeout,
            mode=mode,
            runs_enabled=_flag(env.get("API_RUNS_ENABLED")),
            pipeline_database_url=env.get("PIPELINE_DATABASE_URL", "").strip() or None,
            layer2_store=env.get("API_LAYER2_STORE", "").strip() or None,
            layer2_populations=populations,
            ai_relevant_min_score=threshold,
            max_db_sessions=sessions,
            host=env.get("API_HOST", "127.0.0.1").strip() or "127.0.0.1",
            port=port,
        )
