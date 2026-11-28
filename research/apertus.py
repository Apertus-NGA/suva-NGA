"""Research front-end to the shared Apertus client `src/llm/` (AGENTS.md G2, G3). Development use only.

Every live call goes through `src.llm.client`: its configuration from the environment (G3, no defaults), its
timeout, its single error classifier and retry policy, its served-model check against MODELS.md §1, its
`finish_reason == "length"` rule, its per-member concurrency cap and its cache and call log
(`data/derived/llm/research/`, git-ignored). This module only keeps the call signatures the research scripts
(and a teammate's notebook) import:

    from apertus import chat, chat_many, p_yes, M70
    r = chat(M70, [{"role": "user", "content": "..."}], max_tokens=200)
    r["text"], r["reasoning"], r["usage"], r["logprobs"], r["error"]

Settings come from the environment, or from `.env` / `.env.local` read by `src.cli.load_dotenv` (never
overriding the environment). The research script chooses the model: `model` is passed to the shared
client as its `LLM_NAME` for that call, and must name an Apertus model (E1).

Old answers: `research/cache/apertus.sqlite` (written by the earlier direct client, git-ignored) is still
read, read-only, under its old request key, so earlier experiments replay offline. Nothing new is written
there.

What the shared client refuses, and this module therefore refuses with `ResearchRefused` instead of
bypassing it (a cached old answer is still returned):
- thinking models (`*-thinking`) and assistant-prefill controls (`continue_final_message`,
  `add_generation_prompt`): thinking mode stays off (G3). Scripts that need them (arm_k_thinking.py,
  arm_n_thinking2.py, the `*_think` arms of arm_a_pilot.py / arm_a_full.py) replay from the old cache only.
- sampling other than temperature 0 (`temperature`, `top_p`), and any other request field the client
  does not expose.
- `retries` and `timeout` are accepted for compatibility: retries are decided by the client's error
  classifier (the argument is ignored); `timeout` sets the client's timeout (`LLM_TIMEOUT_S`).

Label calls (`logprobs=True` with `max_tokens <= 4`) are sent as the client's first-token calls
(`first_token_only`, `max_tokens` capped at 2), the only short call the client accepts without treating
`finish_reason == "length"` as a failure. `p_yes` reads the first token, so the scores keep their meaning;
the returned text is at most two tokens.

`chat_many` runs at most `LLM_CONCURRENCY` calls at once (the client's cap, at most the member share of
D-030), whatever `workers` asks for.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from src.cli import load_dotenv  # noqa: E402
from src.llm.client import DEFAULT_STORE, InputRejected, LLMClient, LLMError, ReplayMiss  # noqa: E402
from src.llm.config import DEFAULT_CONCURRENCY, ConfigError, LLMConfig  # noqa: E402

LEGACY_DB = ROOT / "cache" / "apertus.sqlite"
STORE = DEFAULT_STORE / "research"
M70, M70T, M8, M8T = "apertus-v1-5-70b", "apertus-v1-5-70b-thinking", "apertus-v1-5-8b", "apertus-v1-5-8b-thinking"
PASSED_THROUGH = {"max_tokens", "logprobs", "top_logprobs", "seed", "response_format"}
REFUSED_CONTROLS = {"continue_final_message", "add_generation_prompt", "chat_template_kwargs"}
_lock = threading.Lock()
_clients: dict[tuple[str, int], LLMClient] = {}


class ResearchRefused(RuntimeError):
    """A request the shared client deliberately does not make (thinking, sampling, raw controls)."""


def _legacy_lookup(body: dict) -> dict | None:
    """Answer of the earlier direct client for exactly this request body, if cached (read-only)."""
    if not LEGACY_DB.is_file():
        return None
    key = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    with _lock:
        con = sqlite3.connect(f"file:{LEGACY_DB}?mode=ro", uri=True, timeout=60)
        try:
            row = con.execute("select response from calls where key=?", (key,)).fetchone()
        except sqlite3.OperationalError:
            row = None
        finally:
            con.close()
    return _parse_legacy(json.loads(row[0])) if row else None


def _parse_legacy(data: dict) -> dict:
    ch = data["choices"][0]
    msg = ch["message"]
    lp = (ch.get("logprobs") or {}).get("content")
    return {"text": msg.get("content"), "reasoning": msg.get("reasoning") or msg.get("reasoning_content"),
            "usage": data.get("usage", {}), "logprobs": lp, "finish": ch.get("finish_reason"), "cached": True,
            "error": None}


def _config(model: str, timeout: int) -> LLMConfig:
    load_dotenv()
    env = {**os.environ, "LLM_NAME": model, "LLM_NAME_SMALL": model, "LLM_TIMEOUT_S": str(timeout)}
    return LLMConfig.from_env("live", env)


def _client(model: str, timeout: int) -> LLMClient:
    with _lock:
        key = (model, timeout)
        if key not in _clients:
            _clients[key] = LLMClient(_config(model, timeout), store_dir=STORE)
        return _clients[key]


def _refusal(model: str, params: dict) -> str | None:
    if "thinking" in model.lower():
        return f"{model!r} is a thinking model: the shared client keeps thinking off (AGENTS.md G3)"
    controls = REFUSED_CONTROLS & params.keys()
    if controls:
        return f"{sorted(controls)} prefill the assistant turn for thinking: refused by the shared client (G3)"
    if params.get("temperature", 0) != 0 or "top_p" in params:
        return "sampling (temperature != 0, top_p) is not offered by the shared client: it calls at temperature 0"
    unknown = params.keys() - PASSED_THROUGH - {"temperature"}
    if unknown:
        return f"request fields {sorted(unknown)} are not offered by the shared client (src/llm/client.py)"
    if "max_tokens" not in params:
        return "max_tokens is required by the shared client"
    return None


def chat(model: str, messages: list[dict], tag: str = "", retries: int = 6, timeout: int = 300, **params) -> dict:
    """One chat completion through `src.llm.client`. Same result dict as before; `retries` is ignored."""
    del retries  # the client's classify_error decides retries (G3)
    body = {"model": model, "messages": messages, "temperature": 0, **params}
    old = _legacy_lookup(body)
    if old is not None:
        return old
    reason = _refusal(model, params)
    if reason:
        raise ResearchRefused(f"{reason}. Only a cached answer in {LEGACY_DB.name} could serve this request.")
    logprobs = bool(params.get("logprobs"))
    max_tokens = int(params["max_tokens"])
    first_token_only = logprobs and max_tokens <= 4
    try:
        r = _client(model, timeout).chat(
            messages,
            max_tokens=min(max_tokens, 2) if first_token_only else max_tokens,
            prompt_version="research:" + (tag or "untagged"),
            response_format=params.get("response_format"),
            logprobs=logprobs,
            top_logprobs=params.get("top_logprobs"),
            seed=params.get("seed"),
            first_token_only=first_token_only,
        )
    except (LLMError, InputRejected, ReplayMiss) as exc:
        return {"text": None, "error": str(exc)[:300], "reasoning": None, "usage": {}, "logprobs": None,
                "finish": None, "cached": False}
    return {"text": r.content, "reasoning": None, "usage": r.usage, "logprobs": (r.logprobs or {}).get("content"),
            "finish": r.finish_reason, "cached": r.mode == "REPLAY", "error": None}


def chat_many(jobs: list[dict], workers: int = 8, progress: int = 50) -> list[dict]:
    """jobs: list of kwargs for chat(). Returns results in order. Workers are capped at the client's cap."""
    if not jobs:
        return []
    load_dotenv()
    try:
        cap = LLMConfig.from_env("live", {**os.environ, "LLM_NAME": M70}).concurrency
    except ConfigError:  # offline replay of old answers; a live call still fails in chat() with the clear message
        cap = DEFAULT_CONCURRENCY
    workers = max(1, min(workers, cap))
    out: list = [None] * len(jobs)
    done = [0]

    def run(i: int) -> None:
        out[i] = chat(**jobs[i])
        with _lock:
            done[0] += 1
            if progress and done[0] % progress == 0:
                print(f"  {done[0]}/{len(jobs)}", flush=True)

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(run, range(len(jobs))))
    return out


YES = {"ja", "yes", "oui", "si", "sì", "true", "1", "relevant"}
NO = {"nein", "no", "non", "false", "0", "irrelevant", "nicht"}


def p_yes(result: dict, position: int | None = None) -> float | None:
    """P(yes) from token logprobs (request with logprobs=True, top_logprobs=10).

    Looks at the first token whose top alternatives contain a yes/no word (or at `position`).
    Returns None if no such token is found.
    """
    lp = result.get("logprobs")
    if not lp:
        return None
    idx = [position] if position is not None else range(len(lp))
    for i in idx:
        py = pn = 0.0
        for alt in lp[i].get("top_logprobs", []):
            w = alt["token"].strip().lower().strip('."\':,*')
            if w in YES:
                py += math.exp(alt["logprob"])
            elif w in NO:
                pn += math.exp(alt["logprob"])
        if py + pn > 0.5:
            return py / (py + pn)
    return None


if __name__ == "__main__":
    r = chat(M70, [{"role": "user", "content": "Antworte nur mit Ja oder Nein: Ist die Suva ein Unfallversicherer?"}],
             max_tokens=3, logprobs=True, top_logprobs=10, tag="smoke")
    print(r["text"], p_yes(r), r["usage"], "cached" if r["cached"] else "fresh", r["error"])
