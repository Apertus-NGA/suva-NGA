# SPDX-License-Identifier: Apache-2.0
"""Tool specifications and the JSON schemas sent to the gateway.

A :class:`Tool` is a named, typed action that Apertus may *propose* and that code executes (or
simply reads, for a "form" tool such as a triage justification). Its ``parameters`` are a JSON
schema object, written by hand or generated from a pydantic model (``Model.model_json_schema()``).

Keera facts this module encodes (``docs/LESSONS.md``, measured 27 Nov 2026 unless noted):

* ``response_format: json_schema`` with ``strict: true`` works when every object has
  ``additionalProperties: false`` (K2: 12/12 probes, 33/33 whole-ruling calls per model).
* Under strict mode, keys come out in **alphabetical order** (K3). Field names are therefore
  prefixed (``a_``, ``b_``, ``c_``) so that alphabetical order is the generation order we want
  (evidence first, label last). :func:`lint_strict` fails a schema whose declared order differs
  from its alphabetical order.
* ``maxItems``/``minItems`` and lists of integers were fragile on shared gateways (other teams,
  reported): they are removed from the wire schema and enforced by code instead, together with
  ``minLength``, ``maxLength``, ``pattern``, ``uniqueItems``, ``minimum`` and ``maximum``.
* :class:`Tool` refuses any schema keyword that :func:`~.validate.validate` does not enforce, so
  that a constraint can never be dropped from the wire *and* ignored by code (fail closed).
* Lists of objects and ``anyOf`` were **not covered by the gateway probe** (K12). Keera accepted both
  in the 27 Nov smoke (42 strict loop requests with ``anyOf`` branches, 6 live contract calls with a
  list of claim objects), which is an observation, not a measurement: :func:`lint_strict` still
  reports them as warnings, and the probe must cover them before a contract relies on them.
"""
from __future__ import annotations

import copy
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = [
    "Tier", "Tool", "strict_profile", "inline_refs", "bind_enums", "lint_strict", "response_format",
    "placeholder_example", "loop_schema", "unsupported_keywords", "FINISH", "SUPPORTED_KEYWORDS",
]

#: Name of the pseudo-tool that ends a bounded loop.
FINISH = "finish"

_CODE_ONLY_KEYWORDS = ("maxItems", "minItems", "maxLength", "minLength", "uniqueItems", "pattern",
                       "minimum", "maximum")
_DROP_KEYWORDS = ("title", "default", "examples")
#: Every keyword a tool schema may use. :func:`~.validate.validate` enforces each of them (or, for
#: ``description``/``title``/``default``/``examples``, they carry no constraint). Anything else
#: (``format``, ``allOf``, ``not``, ``prefixItems``, ``additionalProperties`` as a schema ...) is refused
#: by :class:`Tool`, because the wire would drop or ignore it and code would not check it.
SUPPORTED_KEYWORDS = frozenset({
    "type", "properties", "required", "additionalProperties", "items", "enum", "const",
    "anyOf", "oneOf", "$ref", "$defs", "description", "title", "default", "examples",
    *_CODE_ONLY_KEYWORDS,
})


class Tier(str, Enum):
    """How the JSON shape is requested from the gateway, strongest first (the JSON cascade)."""

    STRICT = "json_schema"   # server-side constrained decoding against the wire schema
    OBJECT = "json_object"   # server guarantees JSON syntax only; schema in the prompt
    PROMPT = "prompt"        # no response_format; schema and placeholder example in the prompt

    def weaker(self) -> Tier | None:
        """The next tier of the cascade, or ``None`` after ``PROMPT``."""
        order = [Tier.STRICT, Tier.OBJECT, Tier.PROMPT]
        i = order.index(self)
        return order[i + 1] if i + 1 < len(order) else None


@dataclass(frozen=True)
class Tool:
    """A typed action the model may propose.

    Attributes:
        name: Stable identifier, ``snake_case``; part of the cache key through the prompt.
        description: One or two sentences the model reads. Say what the tool is for and what it
            must not be used for.
        parameters: JSON schema of the arguments (type ``object``). Field names carry the ``a_``,
            ``b_`` ... prefixes when their generation order matters.
        handler: Optional code that executes the call in a loop: ``handler(args, context) -> result``.
            Must be deterministic and read-only (see ``read_only``).
        read_only: Must stay ``True`` for every tool offered to Apertus in this project. A tool with
            side effects (writing, sending, deleting) is never registered (doctrine: the lawyer decides).
        caps: Extra caps by path (``{"a_evidence": 3}``), merged under the ``caps`` argument of
            :func:`~.protocol.propose`; for generated schemas that carry no ``maxItems``/``maxLength``.

    Raises:
        ValueError: a name that is not snake_case or is reserved, parameters that are not an object
            schema, a tool that is not read-only, or a schema keyword code does not enforce
            (see :data:`SUPPORTED_KEYWORDS`).
    """

    name: str
    description: str
    parameters: Mapping[str, Any]
    handler: Callable[[dict[str, Any], Any], Any] | None = None
    read_only: bool = True
    caps: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.isidentifier() or self.name != self.name.lower():
            raise ValueError(f"tool name must be snake_case: {self.name!r}")
        if self.name == FINISH:
            raise ValueError("'finish' is reserved")
        if self.parameters.get("type") != "object":
            raise ValueError(f"{self.name}: parameters must be a JSON schema of type object")
        if not self.read_only:
            raise ValueError(f"{self.name}: only read-only tools may be offered to the model")
        bad = unsupported_keywords(self.parameters)
        if bad:
            raise ValueError(f"{self.name}: schema keywords not enforced by code (fail closed): {bad}")


def unsupported_keywords(schema: Mapping[str, Any]) -> list[str]:
    """Paths of schema keywords outside :data:`SUPPORTED_KEYWORDS` (``"/a_date: format"``). Empty = fine."""
    found: list[str] = []

    def walk(node: Any, path: str) -> None:
        if not isinstance(node, Mapping):
            found.append(f"{path or '/'}: schema must be an object")
            return
        for k, v in node.items():
            if k not in SUPPORTED_KEYWORDS:
                found.append(f"{path or '/'}: {k}")
            elif k == "additionalProperties" and not isinstance(v, bool):
                found.append(f"{path or '/'}: additionalProperties must be true or false, not a schema")
        for name, sub in (node.get("properties") or {}).items():
            walk(sub, f"{path}/{name}")
        for name, sub in (node.get("$defs") or {}).items():
            walk(sub, f"{path}/$defs/{name}")
        if isinstance(node.get("items"), Mapping):
            walk(node["items"], f"{path}[]")
        elif "items" in node:
            found.append(f"{path or '/'}: items must be one schema (tuple items are not supported)")
        for key in ("anyOf", "oneOf"):
            for i, sub in enumerate(node.get(key) or ()):
                walk(sub, f"{path}/{key}[{i}]")

    walk(schema, "")
    return found


def _inline_refs(node: Any, defs: Mapping[str, Any], depth: int = 0) -> Any:
    if depth > 20:
        raise ValueError("schema $ref nesting too deep (recursive model?)")
    if isinstance(node, dict):
        if "$ref" in node:
            ref = node["$ref"]
            if not ref.startswith("#/$defs/") or ref.split("/")[-1] not in defs:
                raise ValueError(f"unsupported or unknown $ref {ref!r}")
            target = copy.deepcopy(defs[ref.split("/")[-1]])
            extra = {k: v for k, v in node.items() if k != "$ref"}
            target.update(extra)
            return _inline_refs(target, defs, depth + 1)
        return {k: _inline_refs(v, defs, depth) for k, v in node.items() if k != "$defs"}
    if isinstance(node, list):
        return [_inline_refs(v, defs, depth) for v in node]
    return node


def inline_refs(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of ``schema`` with every local ``$ref`` replaced by its ``$defs`` target.

    Everything else is kept, caps included (``maxItems``, ``minLength`` ...), so the result is what
    :func:`~.validate.validate` checks and what :func:`bind_enums` binds. Keywords written next to a
    ``$ref`` (pydantic puts ``description`` there) override the target's. The input is not modified.

    Raises:
        ValueError: a non-local ``$ref``, an unknown target, or nesting deeper than 20 (recursive model).
    """
    defs = schema.get("$defs", {})
    return _inline_refs(copy.deepcopy(dict(schema)), defs)


def strict_profile(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Return the **wire** schema: refs inlined, every object closed and fully required.

    Keywords the gateway handled badly (``maxItems``, ``minLength`` ...) are removed here and
    enforced by :mod:`validate` from the original schema. ``title``/``default``/``examples``
    (pydantic noise) are dropped; ``const`` becomes a one-value ``enum``. The input is not modified.
    """
    s = inline_refs(schema)

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            node = {k: walk(v) for k, v in node.items() if k not in _DROP_KEYWORDS + _CODE_ONLY_KEYWORDS}
            if "const" in node:
                node["enum"] = [node.pop("const")]
            if "properties" in node:  # a closed record; a bare {"type": "object"} is left open and linted
                node["type"] = "object"
                node["additionalProperties"] = False
                node["required"] = list(node["properties"].keys())
            return node
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(s)


def _path_tokens(path: str) -> list[str]:
    """``"a_claims[].a_cites[]"`` -> ``["a_claims", "[]", "a_cites", "[]"]``."""
    toks: list[str] = []
    for part in path.split("."):
        name = part.rstrip("[]")
        if name:
            toks.append(name)
        toks.extend(["[]"] * (part[len(name):].count("[]")))
    return toks


def bind_enums(schema: Mapping[str, Any], bindings: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    """Return a copy of ``schema`` where each bound field accepts only the given values.

    Args:
        schema: A JSON schema object (wire or original); local ``$ref`` are inlined first.
        bindings: ``{"a_evidence[]": ["c1", "c2"], "a_claims[].a_cites[]": [...]}``. ``[]`` steps into
            array items. The target must be a string schema.

    Raises:
        ValueError: unknown path, non-string target, or an empty list of values (an empty enum
            is unsatisfiable in strict mode; send no call instead, or offer an explicit ``none`` value).
    """
    out = inline_refs(schema)
    for path, values in bindings.items():
        values = list(dict.fromkeys(values))
        if not values:
            raise ValueError(f"{path}: empty enum (nothing to choose from: do not make the call)")
        node: Any = out
        for tok in _path_tokens(path):
            if tok == "[]":
                if node.get("type") != "array" or "items" not in node:
                    raise ValueError(f"{path}: not an array at '[]'")
                node = node["items"]
            else:
                props = node.get("properties", {})
                if tok not in props:
                    raise ValueError(f"{path}: unknown field {tok!r}")
                node = props[tok]
        if node.get("type") not in ("string", None) or "anyOf" in node or "oneOf" in node:
            raise ValueError(f"{path}: enum binding needs a plain string field (no anyOf/oneOf)")
        node["type"] = "string"
        node["enum"] = values
    return out


def lint_strict(schema: Mapping[str, Any]) -> list[str]:
    """List problems of a wire schema against the Keera strict profile. Empty list = clean.

    Errors start with ``E:``, warnings with ``W:``. Unit tests assert that every contract of the
    project lints clean (``E:``-free), and the gateway probe covers each ``W:`` before use.
    """
    problems: list[str] = []

    def walk(node: Any, path: str) -> None:
        if not isinstance(node, dict):
            return
        t = node.get("type")
        if t == "object" and "properties" not in node:
            problems.append(f"E: {path or '/'}: open object (no properties) cannot be strict")
        if "properties" in node:
            props = node["properties"]
            if node.get("additionalProperties") is not False:
                problems.append(f"E: {path or '/'}: additionalProperties must be false")
            if sorted(node.get("required", [])) != sorted(props):
                problems.append(f"E: {path or '/'}: every property must be required")
            keys = list(props)
            if keys != sorted(keys):
                problems.append(f"E: {path or '/'}: declared order {keys} differs from alphabetical "
                                f"order (generation order under strict mode): prefix the names a_, b_, ...")
            for k, v in props.items():
                walk(v, f"{path}/{k}")
        if t == "array":
            items = node.get("items", {})
            if items.get("type") in ("integer", "number"):
                problems.append(f"E: {path}: arrays of numbers looped on shared gateways; use strings")
            if items.get("type") == "array":
                problems.append(f"E: {path}: arrays of arrays are not allowed")
            if items.get("type") == "object" or "properties" in items:
                problems.append(f"W: {path}: list of objects (not in the gateway probe, K12): probe first")
            walk(items, f"{path}[]")
        if "enum" in node and not node["enum"]:
            problems.append(f"E: {path}: empty enum")
        for kw in _CODE_ONLY_KEYWORDS:
            if kw in node:
                problems.append(f"E: {path}: '{kw}' must not reach the gateway (enforced in code)")
        for key in ("anyOf", "oneOf"):
            if key in node:
                problems.append(f"W: {path}: {key} (not in the gateway probe): probe first")
                for i, sub in enumerate(node[key]):
                    walk(sub, f"{path}/{key}[{i}]")

    walk(schema, "")
    return problems


def response_format(tier: Tier, wire_schema: Mapping[str, Any], name: str) -> dict[str, Any] | None:
    """The ``response_format`` body field for a tier (``None`` for :attr:`Tier.PROMPT`)."""
    if tier is Tier.STRICT:
        return {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": dict(wire_schema)}}
    if tier is Tier.OBJECT:
        return {"type": "json_object"}
    return None


def placeholder_example(schema: Mapping[str, Any], caps: Mapping[str, int] | None = None) -> Any:
    """An instance made of **placeholders**, never of plausible values.

    A filled example in the prompt is copied by the model (another team measured 53 % copies with
    the 8B); a placeholder example kept 49/49 first attempts schema-valid on both sizes (reported).
    """
    caps = caps or {}

    def ph(node: Mapping[str, Any], path: str) -> Any:
        t = node.get("type")
        if "enum" in node:
            vals = node["enum"]
            shown = " | ".join(map(str, vals[:12])) + (" | ..." if len(vals) > 12 else "")
            return f"<one of: {shown}>"
        if t == "object" or "properties" in node:
            return {k: ph(v, f"{path}.{k}" if path else k) for k, v in node.get("properties", {}).items()}
        if t == "array":
            cap = caps.get(path) or node.get("maxItems")
            return [ph(node.get("items", {}), f"{path}[]")] if cap != 0 else []
        if t == "string":
            ml = caps.get(path) or node.get("maxLength")
            return f"<text{', max ' + str(ml) + ' characters' if ml else ''}>"
        if t == "boolean":
            return "<true or false>"
        if t in ("integer", "number"):
            return f"<{t}>"
        if isinstance(t, list):
            return f"<{' or '.join(t)}>"
        return "<value>"

    return ph(schema, "")


def loop_schema(tools: Iterable[Tool], *, strict_args: bool = False) -> dict[str, Any]:
    """Wire schema of one step of the bounded loop: ``{"a_calls": [{"a_tool": ..., "b_args": {...}}]}``.

    With ``strict_args=False`` (default) ``b_args`` is a free object and each call's arguments are
    validated by code against its tool. With ``strict_args=True`` each call is an ``anyOf`` branch
    per tool; this is **experimental** (``anyOf`` in a list of objects: accepted by Keera in the 27 Nov
    smoke, not yet covered by the gateway probe).
    """
    tools = list(tools)
    names = [t.name for t in tools] + [FINISH]
    if strict_args:
        branches = [
            {"type": "object", "properties": {"a_tool": {"type": "string", "enum": [t.name]},
                                              "b_args": strict_profile(t.parameters)}}
            for t in tools
        ] + [{"type": "object", "properties": {"a_tool": {"type": "string", "enum": [FINISH]},
                                               "b_args": {"type": "object", "properties": {}}}}]
        item: dict[str, Any] = {"anyOf": [strict_profile(b) for b in branches]}
    else:
        item = {"type": "object", "properties": {"a_tool": {"type": "string", "enum": names},
                                                 "b_args": {"type": "object"}}}
    return {"type": "object", "properties": {"a_calls": {"type": "array", "items": item}}}
