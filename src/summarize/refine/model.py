"""The one seam to Apertus for refine: a strict-JSON call through the project's client (AGENTS.md G2, G3).

A step builds its messages and a JSON schema whose ids are enums of this draft and this ruling, and calls
`Model.ask`. The schema is written into the prompt and the call uses JSON mode (`json_object`): measured on
28 Nov, strict `json_schema` decoding of a long ruling looped on whitespace until max_tokens (1,800 tokens of
blanks, 161 s), while JSON mode answered the same request. The answer is parsed and checked against the schema
here (types, required keys, enums), so a step only ever sees ids that exist; an invalid answer gets one targeted
retry that names the error. Fields are prefixed `a_`, `b_`, … in the order the model should think: evidence
first, verdict last.

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


def _template(schema: dict) -> str:
    kind = schema.get("type")
    if kind == "object":
        inner = ", ".join(f'"{k}": {_template(v)}' for k, v in schema["properties"].items())
        return "{" + inner + "}"
    if kind == "array":
        cap = f", at most {schema['maxItems']}" if "maxItems" in schema else ""
        return f"[{_template(schema['items'])}, ...{cap}]"
    if "enum" in schema:
        return "one of " + json.dumps(schema["enum"], ensure_ascii=False)
    return '"..."'


def describe(schema: dict) -> str:
    """The answer format as the prompt states it."""
    return "Answer with one JSON object, on as few lines as possible, in exactly this format:\n" + _template(schema)


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
        if "maxItems" in schema:
            del value[schema["maxItems"] :]  # extra items are ignored, never an error
        kept = []
        for n, item in enumerate(value):
            try:
                _valid(item, schema["items"], f"{path}[{n}]")
                kept.append(item)
            except ModelFailed:
                if schema["items"].get("type") != "object":
                    raise
                # one bad item of a list (an id that is not offered) is dropped; the rest of the answer stands
        value[:] = kept
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

    def _call(self, messages: list[dict], prompt_version: str, max_tokens: int) -> str:
        with self._lock:
            if self.calls >= self.budget:
                raise ModelFailed("call budget exhausted")
            self.calls += 1
        try:
            return self.transport(messages, {"type": "json_object"}, prompt_version, max_tokens)
        except ModelFailed:
            raise
        except Exception as exc:  # noqa: BLE001  a failed call is never a "no": the item goes to needs_review
            self.log.append({"prompt": prompt_version, "error": f"{type(exc).__name__}: {exc}"[:300]})
            raise ModelFailed(f"call failed: {type(exc).__name__}: {exc}") from exc

    def ask(self, messages: list[dict], name: str, schema: dict, prompt_version: str, max_tokens: int = 800) -> dict:
        """The validated answer. One retry when the answer is not valid JSON or breaks the schema."""
        sent = [*messages[:-1], {**messages[-1], "content": messages[-1]["content"] + "\n\n" + describe(schema)}]
        for attempt in range(2):
            raw = self._call(sent, prompt_version if attempt == 0 else f"{prompt_version}/retry", max_tokens)
            try:
                answer = json.loads(raw)
                _valid(answer, schema)
            except (ValueError, ModelFailed) as exc:
                reason = "not valid JSON" if not isinstance(exc, ModelFailed) else str(exc)
                self.log.append({"prompt": prompt_version, "error": reason, "attempt": attempt})
                if attempt == 1:
                    raise ModelFailed(f"invalid answer: {reason}") from exc
                sent = [*sent, {"role": "assistant", "content": raw[:4000]},
                        {"role": "user", "content": f"That answer is invalid ({reason}). Answer again with one "
                         "JSON object that follows the format exactly, and nothing else."}]  # fmt: skip
                continue
            self.log.append({"prompt": prompt_version, "ok": True, "attempt": attempt})
            return answer
        raise AssertionError("unreachable")


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
