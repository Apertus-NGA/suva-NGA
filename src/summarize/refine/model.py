"""The one seam to Apertus for refine: a strict-JSON call through the project's client (AGENTS.md G2, G3).

A step builds its messages and a JSON schema whose ids are enums of this draft and this ruling, and calls
`Model.ask`. The answer is parsed and checked against the schema's enums here, so a step only ever sees ids that
exist. Strict mode returns keys in alphabetical order (docs/LESSONS.md K3), so fields are prefixed `a_`, `b_`, …
in the order the model should think: evidence first, verdict last.

Tests pass `FakeModel`-style objects with the same `ask` signature; nothing here calls the gateway in a test.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

Transport = Callable[[list[dict], dict, str, int], str]  # (messages, response_format, prompt_version, max_tokens)


class ModelFailed(RuntimeError):
    """The call failed or its answer is not valid against the schema. The step marks its item needs_review."""


def obj(properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required if required is not None else list(properties),
        "properties": properties,
    }


def enum(values: list[str]) -> dict:
    return {"type": "string", "enum": list(dict.fromkeys(values))}


def array(items: dict, max_items: int | None = None) -> dict:
    out = {"type": "array", "items": items}
    if max_items is not None:
        out["maxItems"] = max_items
    return out


STRING = {"type": "string"}


def _valid(value, schema: dict, path: str = "$") -> None:
    """Enforce what the step relies on, whatever the endpoint did with `strict`: types, required keys, enums."""
    kind = schema.get("type")
    if kind == "object":
        if not isinstance(value, dict):
            raise ModelFailed(f"{path}: not an object")
        for key in schema.get("required", []):
            if key not in value:
                raise ModelFailed(f"{path}.{key}: missing")
        for key, sub in schema.get("properties", {}).items():
            if key in value:
                _valid(value[key], sub, f"{path}.{key}")
    elif kind == "array":
        if not isinstance(value, list):
            raise ModelFailed(f"{path}: not a list")
        for n, item in enumerate(value):
            _valid(item, schema["items"], f"{path}[{n}]")
    elif kind == "string":
        if not isinstance(value, str):
            raise ModelFailed(f"{path}: not a string")
        if "enum" in schema and value not in schema["enum"]:
            raise ModelFailed(f"{path}: {value!r} is not one of the allowed ids")


@dataclass
class Model:
    """Counts calls against a budget and validates every answer. `transport` reaches the gateway."""

    transport: Transport
    budget: int = 24
    calls: int = 0
    log: list[dict] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def remaining(self) -> int:
        return self.budget - self.calls

    def ask(self, messages: list[dict], name: str, schema: dict, prompt_version: str, max_tokens: int = 800) -> dict:
        with self._lock:
            if self.calls >= self.budget:
                raise ModelFailed("call budget exhausted")
            self.calls += 1
        response_format = {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}
        try:
            raw = self.transport(messages, response_format, prompt_version, max_tokens)
        except ModelFailed:
            raise
        except Exception as exc:  # noqa: BLE001  a failed call is never a "no": the item goes to needs_review
            self.log.append({"prompt": prompt_version, "error": f"{type(exc).__name__}: {exc}"[:300]})
            raise ModelFailed(f"call failed: {type(exc).__name__}: {exc}") from exc
        try:
            answer = json.loads(raw)
        except ValueError as exc:
            self.log.append({"prompt": prompt_version, "error": "invalid JSON"})
            raise ModelFailed("the answer is not valid JSON") from exc
        _valid(answer, schema)
        self.log.append({"prompt": prompt_version, "ok": True})
        return answer


def gateway(mode: str = "live", client=None) -> Transport:
    """A transport over the shared client (src/llm/client.py): cache, replay, served-model check, call log."""
    from src.llm.client import client_from_env

    shared = client or client_from_env(mode)

    def send(messages: list[dict], response_format: dict, prompt_version: str, max_tokens: int) -> str:
        return shared.chat(
            messages,
            max_tokens=max_tokens,
            prompt_version=prompt_version,
            schema_version=prompt_version,
            response_format=response_format,
        ).content

    return send
