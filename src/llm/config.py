"""Configuration of the Apertus client, from the environment only (AGENTS.md G3, docs/ARCHITECTURE.md §4).

No default for `LLM_NAME`, `LLM_BASE_URL` or `LLM_API_KEY`: in live mode a missing one stops the run with a
clear message; replay mode needs none of them (D-032). `LLM_NAME` must name an Apertus model (event rule
E1), in either id form: the judges may set the 8B or the 70B, as a gateway id or a Hugging Face id (Q-23).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from src.llm.served_model import names_apertus

Mode = Literal["live", "replay"]
REQUIRED = ("LLM_NAME", "LLM_BASE_URL", "LLM_API_KEY")

# Defaults of the optional settings (PROPOSED by the platform owner; change them here only).
DEFAULT_CONCURRENCY = 4  # ARCHITECTURE §4.5: the limiter starts at 4
MEMBER_SHARE = 5  # D-030 while open: 5 concurrent calls per member, team total <= 16
DEFAULT_TIMEOUT_S = 180.0  # the 70B took 81 s for 250k input tokens on 27 Nov (docs/LESSONS.md K6)
DEFAULT_MAX_INPUT_TOKENS = 120_000  # G4: well below the 250,624 tokens Keera answered on 27 Nov (K6)


class ConfigError(RuntimeError):
    """Configuration that cannot run: stops at startup, before any call."""


def _get(env: Mapping[str, str], key: str) -> str | None:
    value = env.get(key, "").strip()
    return value or None


def _int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = _get(env, key)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise ConfigError(f"{key} must be positive, got {value}")
    return value


def _float(env: Mapping[str, str], key: str, default: float) -> float:
    raw = _get(env, key)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be a number, got {raw!r}") from exc
    if value <= 0:
        raise ConfigError(f"{key} must be positive, got {value}")
    return value


@dataclass(frozen=True)
class LLMConfig:
    mode: Mode
    name: str | None
    name_small: str | None
    base_url: str | None
    api_key: str | None = field(repr=False)
    concurrency: int = DEFAULT_CONCURRENCY
    timeout_s: float = DEFAULT_TIMEOUT_S
    max_input_tokens: int = DEFAULT_MAX_INPUT_TOKENS

    @classmethod
    def from_env(cls, mode: Mode, env: Mapping[str, str] | None = None) -> LLMConfig:
        env = os.environ if env is None else env
        if mode not in ("live", "replay"):
            raise ConfigError(f"mode must be 'live' or 'replay', got {mode!r}")
        name, base_url, api_key = (_get(env, k) for k in REQUIRED)
        if mode == "live":
            missing = [k for k, v in zip(REQUIRED, (name, base_url, api_key), strict=True) if not v]
            if missing:
                raise ConfigError(
                    f"live mode needs {', '.join(missing)} (AGENTS.md G3). Set them in .env "
                    "(see .env.example) or in the environment, or run in replay mode."
                )
        name_small = _get(env, "LLM_NAME_SMALL") or name
        for key, value in (("LLM_NAME", name), ("LLM_NAME_SMALL", name_small)):
            if value is not None and not names_apertus(value):
                raise ConfigError(
                    f"{key}={value!r} names no Apertus model. Event rule E1: Apertus v1.5 performs the "
                    "core task (ids in MODELS.md §1, gateway or Hugging Face form)."
                )
        concurrency = _int(env, "LLM_CONCURRENCY", DEFAULT_CONCURRENCY)
        if concurrency > MEMBER_SHARE:
            raise ConfigError(
                f"LLM_CONCURRENCY={concurrency} is above a member's share ({MEMBER_SHARE}, D-030 while open)"
            )
        return cls(
            mode=mode,
            name=name,
            name_small=name_small,
            base_url=base_url.rstrip("/") if base_url else None,
            api_key=api_key,
            concurrency=concurrency,
            timeout_s=_float(env, "LLM_TIMEOUT_S", DEFAULT_TIMEOUT_S),
            max_input_tokens=_int(env, "LLM_MAX_INPUT_TOKENS", DEFAULT_MAX_INPUT_TOKENS),
        )
