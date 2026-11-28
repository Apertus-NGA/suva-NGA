"""HTTP transport of the evaluation judge (docs/JUDGE.md). Evaluation only: `make run` never imports this.

The judge is an open-weights model of another family than Apertus (event rule E4, AGENTS.md G10), served by
any OpenAI-compatible endpoint. It has its own three settings, read from the environment or `.env`, with no
default: `JUDGE_MODEL`, `JUDGE_BASE_URL`, `JUDGE_API_KEY`. `JUDGE_REASONING_EFFORT` is optional (default: the
highest level, "high"). This module lives in `src/llm/` because only this package may call a chat endpoint
(G2). It never reads the Apertus settings and refuses an Apertus model: Apertus does not grade itself.
"""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from src.llm.served_model import names_apertus

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = ("JUDGE_MODEL", "JUDGE_BASE_URL", "JUDGE_API_KEY")
DEFAULT_EFFORT = "high"
DEFAULT_TIMEOUT_S = 240.0  # a reasoning model at its highest effort on a long ruling; slower calls are retried
RETRY_STATUS = (408, 429, 500, 502, 503, 504)


class JudgeError(RuntimeError):
    """A judge call that gave no usable answer. Counted as failed, never as a verdict."""


@dataclass(frozen=True)
class JudgeConfig:
    model: str
    base_url: str
    api_key: str = field(repr=False)
    effort: str = DEFAULT_EFFORT
    timeout_s: float = DEFAULT_TIMEOUT_S


def _env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    pairs = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            pairs[key.strip()] = value.strip().strip("'\"")
    return pairs


def config_from_env(env: Mapping[str, str] | None = None, env_file: Path | None = None) -> JudgeConfig:
    """The environment wins over `.env`. A missing setting stops the run before any call."""
    merged = {**_env_file(ROOT / ".env" if env_file is None else env_file), **(os.environ if env is None else env)}
    values = {key: merged.get(key, "").strip() for key in REQUIRED}
    missing = [key for key, value in values.items() if not value]
    if missing:
        raise JudgeError(f"the judge needs {', '.join(missing)} in the environment or in .env (docs/JUDGE.md)")
    if names_apertus(values["JUDGE_MODEL"]):
        raise JudgeError("JUDGE_MODEL names an Apertus model: the judge must be of another family (AGENTS.md G10)")
    return JudgeConfig(
        model=values["JUDGE_MODEL"],
        base_url=values["JUDGE_BASE_URL"].rstrip("/"),
        api_key=values["JUDGE_API_KEY"],
        effort=merged.get("JUDGE_REASONING_EFFORT", "").strip() or DEFAULT_EFFORT,
    )


def chat(
    cfg: JudgeConfig,
    *,
    messages: list[dict[str, str]],
    schema: dict[str, Any],
    max_tokens: int,
    seed: int = 0,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """One call. Returns the text, the served model, the token usage and the reasoning length."""
    body = {
        "model": cfg.model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0,
        "seed": seed,
        "reasoning_effort": cfg.effort,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "verdict", "strict": True, "schema": schema},
        },
    }
    headers = {"Authorization": f"Bearer {cfg.api_key}"}
    own = client is None
    http = httpx.Client(timeout=cfg.timeout_s) if own else client
    try:
        for attempt in (1, 2, 3):
            try:
                response = http.post(f"{cfg.base_url}/chat/completions", headers=headers, json=body)
            except httpx.HTTPError as exc:
                if attempt == 3:
                    raise JudgeError(f"network: {type(exc).__name__}") from exc
                time.sleep(2**attempt)
                continue
            if response.status_code in RETRY_STATUS and attempt < 3:
                time.sleep(2**attempt)
                continue
            if response.status_code != 200:
                raise JudgeError(f"HTTP {response.status_code}: {response.text[:300]}")
            data = response.json()
            choice = data["choices"][0]
            if choice.get("finish_reason") == "length":
                raise JudgeError("answer cut at max_tokens")
            served = str(data.get("model") or "")
            if names_apertus(served):
                raise JudgeError(f"the endpoint served an Apertus model ({served})")
            message = choice["message"]
            reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
            return {
                "content": message.get("content") or "",
                "model": served,
                "usage": data.get("usage") or {},
                "reasoning_chars": len(reasoning),
            }
        raise JudgeError("no answer after three attempts")
    finally:
        if own:
            http.close()
