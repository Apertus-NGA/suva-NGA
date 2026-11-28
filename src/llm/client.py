"""The Apertus client (docs/ARCHITECTURE.md §4, AGENTS.md G2 to G4). Minimal first version.

Done here: configuration from the environment (G3), a timeout on every call, one `system` message, thinking
off, input hygiene before the call (empty or placeholder text, input budget, G4), the served-model check on
every response (G3), `finish_reason == "length"` as a failure, one function that classifies errors and
decides retries, the `llm_calls` log of every raw output, and the replay cache (D-032). A per-process cap
on concurrent calls (`LLM_CONCURRENCY`).

Next (not yet here): the AIMD limiter shared across processes and the circuit breaker (§4.5), streaming
for long generations (§4.6), the JSON cascade and tolerant parser with one repair call (§4.7).

Storage: `data/derived/llm/` (git-ignored while D-031 is open: prompts may contain Suva material).
No network call at import or construction.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx

from src.llm.config import LLMConfig
from src.llm.served_model import REPO_ROOT, ServedModelError, canonical, check_served, load_allow_list

DEFAULT_STORE = REPO_ROOT / "data" / "derived" / "llm"
# Answers committed with the repo, so a fresh clone replays without the gateway. Read-only: live answers are
# written to the store above. Filled by `make replay-cache` with the answers one full run reads, no others.
SHIPPED_STORE = REPO_ROOT / "replay" / "llm"
_USED: set[str] = set()  # cache keys read or written by any client of this process (the summariser opens its own)
MAX_ATTEMPTS = 4
BACKOFF_CAP_S = 30.0
ErrorKind = Literal[
    "rate", "server", "network", "timeout", "auth", "not_found", "json_format_unsupported", "bad_request", "length"
]
RETRYABLE: frozenset[str] = frozenset({"rate", "server", "network", "timeout"})

_PLACEHOLDER = re.compile(
    r"^\s*(<[^<>]{0,40}>|\{[^{}]{0,40}\}|\[[^\[\]]{0,40}\]|none|null|n/?a|todo|tbd|\.\.\.)\s*$", re.I
)
_THINKING_BLOCK = re.compile(r"<\|inner_prefix\|>.*?<\|inner_suffix\|>", re.S)


class LLMError(RuntimeError):
    """A call that failed. Its item is `failed`, never a negative label (D-021 point 7)."""

    def __init__(self, kind: ErrorKind, message: str, status: int | None = None) -> None:
        super().__init__(f"{kind}: {message}")
        self.kind = kind
        self.status = status


class InputRejected(ValueError):
    """Refused before any call (G3, G4)."""


class ReplayMiss(LookupError):
    """Replay mode, and this exact request was never answered and cached."""


@dataclass(frozen=True)
class LLMResult:
    content: str
    served_model: str | None
    finish_reason: str | None
    usage: dict[str, Any]
    logprobs: dict[str, Any] | None
    mode: Literal["LIVE", "REPLAY"]
    cache_key: str
    latency_s: float | None = None
    attempts: int = 0


def estimate_tokens(text: str) -> int:
    """A conservative estimate (3 characters per token; German and French run nearer 4). Not a tokenizer."""
    return math.ceil(len(text) / 3)


def classify_error(status: int | None, body: str = "", exc: Exception | None = None) -> ErrorKind:
    """The single place that turns a failure into a kind; RETRYABLE says which kinds are retried."""
    if exc is not None:
        return "timeout" if isinstance(exc, httpx.TimeoutException) else "network"
    if status in (408, 409, 429):
        return "rate" if status == 429 else "timeout"
    if status is not None and status >= 500:
        return "server"
    if status in (401, 403):
        return "auth"
    if status == 404:
        return "not_found"
    if status == 400 and "response_format" in body:
        return "json_format_unsupported"
    return "bad_request"


def _backoff(attempt: int, retry_after: str | None) -> float:
    if retry_after:
        try:
            return min(float(retry_after), BACKOFF_CAP_S)
        except ValueError:
            pass
    return min(BACKOFF_CAP_S, 2 ** (attempt - 1)) * (0.5 + random.random() / 2)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


@dataclass
class LLMClient:
    cfg: LLMConfig
    store_dir: Path = DEFAULT_STORE
    shipped_dir: Path | None = None  # a second, read-only store looked up after `store_dir`
    transport: httpx.BaseTransport | None = None  # tests inject a declared mock here (G9)
    sleep: Any = time.sleep
    _http: httpx.Client | None = field(default=None, init=False, repr=False)
    _slots: threading.BoundedSemaphore = field(init=False, repr=False)
    _log_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    used: set[str] = field(default_factory=set, init=False, repr=False)  # cache keys this client read or wrote

    def __post_init__(self) -> None:
        self._slots = threading.BoundedSemaphore(self.cfg.concurrency)
        self._allow = load_allow_list() if self.cfg.mode == "live" else None

    # -- public -------------------------------------------------------------------------------------------
    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        size: Literal["large", "small"] = "large",
        prompt_version: str,
        schema_version: str = "",
        response_format: dict[str, Any] | None = None,
        logprobs: bool = False,
        top_logprobs: int | None = None,
        seed: int | None = None,
        repetition: int = 0,
        first_token_only: bool = False,
    ) -> LLMResult:
        """One chat call. `first_token_only`: a label call read from the first token's log-probabilities
        (S3: max_tokens 1, top_logprobs 20). It ends with finish_reason "length" by design; its content is
        never parsed, so that cut is accepted. Every other "length" is a failure (G3)."""
        if first_token_only and (not logprobs or max_tokens > 2):
            raise InputRejected("first_token_only needs logprobs and max_tokens <= 2")
        model = (self.cfg.name if size == "large" else self.cfg.name_small) or self._replay_model(size)
        self._check_input(messages)
        params: dict[str, Any] = {"temperature": 0, "max_tokens": max_tokens}
        if response_format is not None:
            params["response_format"] = response_format
        if logprobs:
            params["logprobs"] = True
            if top_logprobs is not None:
                params["top_logprobs"] = top_logprobs
        if seed is not None:
            params["seed"] = seed
        # key over the REQUESTED model (ARCHITECTURE §4.8); in replay mode LLM_NAME may be unset
        key = _sha(
            {
                "model": canonical(model) if model else "",  # both id forms of one model share answers
                "size": size,
                "messages": messages,
                "params": params,
                "prompt_version": prompt_version,
                "schema_version": schema_version,
                "repetition": repetition,
                "first_token_only": first_token_only,
            }
        )
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        if self.cfg.mode == "replay":
            raise ReplayMiss(f"no cached answer for {key[:12]} (prompt {prompt_version}); run in live mode")
        assert model is not None  # live mode: LLMConfig.from_env guarantees it
        payload = {"model": model, "messages": messages, **params}
        if "thinking" in model.lower():
            payload["chat_template_kwargs"] = {"enable_thinking": False}  # thinking off (K11)
        return self._call(payload, key, prompt_version, size, first_token_only)

    def close(self) -> None:
        if self._http is not None:
            self._http.close()

    # -- input hygiene (G3, G4) ---------------------------------------------------------------------------
    def _check_input(self, messages: list[dict[str, str]]) -> None:
        roles = [m.get("role") for m in messages]
        if roles.count("system") > 1:
            raise InputRejected("one system message only (G3; two return 400, docs/LESSONS.md K11)")
        users = [m.get("content") or "" for m in messages if m.get("role") == "user"]
        if not users or any(not u.strip() or _PLACEHOLDER.match(u) for u in users):
            raise InputRejected("empty or placeholder user text (G4)")
        tokens = estimate_tokens("".join(m.get("content") or "" for m in messages))
        if tokens > self.cfg.max_input_tokens:
            raise InputRejected(
                f"about {tokens} input tokens, over LLM_MAX_INPUT_TOKENS={self.cfg.max_input_tokens}: "
                "split by consideration, never truncate (G4)"
            )

    # -- the call -----------------------------------------------------------------------------------------
    def _client(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(
                base_url=self.cfg.base_url or "",
                timeout=httpx.Timeout(self.cfg.timeout_s, connect=15.0),
                headers={"Authorization": f"Bearer {self.cfg.api_key}"},
                transport=self.transport,
            )
        return self._http

    def _call(
        self, payload: dict[str, Any], key: str, prompt_version: str, size: str, first_token_only: bool
    ) -> LLMResult:
        last: LLMError | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            t0 = time.perf_counter()
            with self._slots:
                try:
                    r = self._client().post("/chat/completions", json=payload)
                except httpx.HTTPError as exc:
                    r, kind = None, classify_error(None, exc=exc)
                    last = LLMError(kind, f"{type(exc).__name__}: {exc}")
            latency = round(time.perf_counter() - t0, 3)
            if r is not None and r.status_code == 200:
                return self._accept(r, payload, key, prompt_version, latency, attempt, size, first_token_only)
            if r is not None:
                kind = classify_error(r.status_code, r.text)
                last = LLMError(kind, r.text[:300], r.status_code)
            self._log(
                key,
                prompt_version,
                payload,
                attempt,
                latency,
                status=getattr(r, "status_code", None),
                error=last.kind if last else None,
            )
            if last is None or last.kind not in RETRYABLE or attempt == MAX_ATTEMPTS:
                break
            self.sleep(_backoff(attempt, r.headers.get("retry-after") if r is not None else None))
        assert last is not None
        raise last

    def _accept(
        self,
        r: httpx.Response,
        payload: dict,
        key: str,
        prompt_version: str,
        latency: float,
        attempt: int,
        size: str,
        first_token_only: bool,
    ) -> LLMResult:
        body = r.json()
        choice = (body.get("choices") or [{}])[0]
        content = _THINKING_BLOCK.sub("", (choice.get("message") or {}).get("content") or "").strip()
        check = check_served(
            payload["model"], body.get("model"), r.headers.get("x-keera-model"), self.cfg.name, self._allow
        )
        finish = choice.get("finish_reason")
        error = None if check.accepted else "served_model_rejected"
        cut = finish == "length" and not first_token_only
        if check.accepted and cut:
            error = "length"
        self._log(
            key,
            prompt_version,
            payload,
            attempt,
            latency,
            status=200,
            served=check.as_log(),
            finish_reason=finish,
            usage=body.get("usage"),
            content=content,
            error=error,
        )
        if not check.accepted:
            raise ServedModelError(f"{check.reason}: requested {payload['model']!r}, served {check.served!r} (G3)")
        if cut:
            raise LLMError("length", "finish_reason=length: output cut, never parsed (G3)", 200)
        result = LLMResult(
            content=content,
            served_model=check.served or check.header,
            finish_reason=finish,
            usage=body.get("usage") or {},
            logprobs=choice.get("logprobs"),
            mode="LIVE",
            cache_key=key,
            latency_s=latency,
            attempts=attempt,
        )
        self._cache_put(result)
        self._record_replay_model(size, payload["model"])
        return result

    # -- stores -------------------------------------------------------------------------------------------
    def _cache_path(self, key: str, store: Path | None = None) -> Path:
        return (store or self.store_dir) / "cache" / key[:2] / f"{key}.json"

    def _stores(self) -> list[Path]:
        return [self.store_dir, *([self.shipped_dir] if self.shipped_dir else [])]

    def _cache_get(self, key: str) -> LLMResult | None:
        path = next((p for p in (self._cache_path(key, s) for s in self._stores()) if p.is_file()), None)
        if path is None:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        with self._log_lock:
            self.used.add(key)
            _USED.add(key)
        return LLMResult(**{**data, "mode": "REPLAY", "latency_s": None, "attempts": 0})

    def _replay_model(self, size: str) -> str | None:
        """Replay mode may run without LLM_NAME (D-032): use the model the last live run requested."""
        if self.cfg.mode != "replay":
            return None
        for store in self._stores():
            path = store / "replay_models.json"
            model = json.loads(path.read_text(encoding="utf-8")).get(size) if path.is_file() else None
            if model:
                return model
        return None

    def _record_replay_model(self, size: str, model: str) -> None:
        path = self.store_dir / "replay_models.json"
        with self._log_lock:
            known = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
            if known.get(size) != canonical(model):
                known[size] = canonical(model)
                path.write_text(json.dumps(known, sort_keys=True) + "\n", encoding="utf-8")

    def _cache_put(self, result: LLMResult) -> None:
        """Only valid outputs from an allowed model reach here (ARCHITECTURE §4.8)."""
        path = self._cache_path(result.cache_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._log_lock:
            self.used.add(result.cache_key)
            _USED.add(result.cache_key)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(result.__dict__, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    def _log(self, key: str, prompt_version: str, payload: dict, attempt: int, latency: float, **fields: Any) -> None:
        """`llm_calls`: every raw output, invalid ones included. Never the key; the prompt only as a hash."""
        record = {
            "at": _now(),
            "cache_key": key,
            "prompt_version": prompt_version,
            "requested": payload["model"],
            "messages_sha256": _sha(payload["messages"]),
            "params": {k: v for k, v in payload.items() if k not in ("model", "messages")},
            "attempt": attempt,
            "latency_s": latency,
            "mode": "LIVE",
            **fields,
        }
        path = self.store_dir / "llm_calls.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._log_lock, path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def client_from_env(mode: Literal["live", "replay"], store_dir: Path = DEFAULT_STORE) -> LLMClient:
    """Build a client from the environment; raises ConfigError with a clear message (G3)."""
    shipped = SHIPPED_STORE if store_dir == DEFAULT_STORE else None
    return LLMClient(LLMConfig.from_env(mode), store_dir=store_dir, shipped_dir=shipped)


def export_answers(dest: Path, client: LLMClient | None = None) -> int:
    """Copy the answers a run used, and the replay model names, into `dest` (the shipped store's layout).
    With `client`: the answers that client used; without: those every client of this process used, looked up
    in the default and the shipped store. Add-only: an answer already in `dest` is left as it is.
    Returns how many answers `dest` gained."""
    keys = client.used if client else _USED
    stores = client._stores() if client else [DEFAULT_STORE, SHIPPED_STORE]
    added = 0
    for key in sorted(keys):
        paths = (s / "cache" / key[:2] / f"{key}.json" for s in stores)
        source = next((p for p in paths if p.is_file()), None)
        target = dest / "cache" / key[:2] / f"{key}.json"
        if source is None or target.is_file():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        added += 1
    models: dict[str, str] = {}
    for store in (dest, *reversed(stores)):  # the local store's names win
        path = store / "replay_models.json"
        if path.is_file():
            models.update(json.loads(path.read_text(encoding="utf-8")))
    if models:
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "replay_models.json").write_text(json.dumps(models, sort_keys=True) + "\n", encoding="utf-8")
    return added


__all__ = [
    "InputRejected",
    "LLMClient",
    "LLMError",
    "LLMResult",
    "ReplayMiss",
    "ServedModelError",
    "classify_error",
    "client_from_env",
    "export_answers",
    "estimate_tokens",
]
