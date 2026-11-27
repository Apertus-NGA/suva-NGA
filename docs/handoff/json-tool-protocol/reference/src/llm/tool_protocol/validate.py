# SPDX-License-Identifier: Apache-2.0
# Key-name repair adapted from ArchAI (kirtanp/hackpertus-archives, src/archai/agent.py, repair_args),
# Copyright (c) 2026 The ArchAI contributors, MIT License, made stricter (see below). See NOTICE.
"""Shape and reference validation of a parsed proposal, with a few logged, deterministic repairs.

Layers (the first three are here; grounding checks live in ``src/verify/`` and are injected):

1. **Shape**: the JSON-schema subset of :data:`~.schema.SUPPORTED_KEYWORDS`: ``type`` (object,
   array, string, integer, number, boolean, null), ``properties`` (every declared key is required,
   as on the wire), ``additionalProperties``, ``items``, ``enum``, ``const``, ``anyOf``, ``oneOf``
   and local ``$ref`` (inlined first, so nested pydantic models and ``Optional`` fields are checked).
   ``true`` is never an integer, and ``1`` never matches an enum value ``true``.
2. **References**: fields bound to an :class:`~.ids.IdTable` are resolved *exactly*; an id that was
   not offered is an error, never a fuzzy match.
3. **Code-only constraints**: ``maxItems``, ``minItems``, ``uniqueItems``, ``maxLength``,
   ``minLength``, ``pattern`` (searched, as in JSON Schema), ``minimum`` and ``maximum`` are
   removed from the wire schema and enforced here. :class:`~.schema.Tool` refuses any other keyword,
   so no constraint is silently dropped.

Repairs (each one is reported, counted and tested):

* ``key_prefix_restored:x->a_x``: the model dropped the ordering prefix of exactly one missing key.
* ``key_renamed:x->y``: an unknown key whose spelling is very close (ratio >= 0.85) to exactly one
  missing expected key. ArchAI also mapped *any* unknown key onto a lone missing argument and
  used cutoff 0.5; both are removed here because they can route a value into the wrong field.
* ``wrapped_scalar:path``: a string where a list of strings is expected becomes a one-item list.
  Splitting a string on commas (ArchAI) is not done: legal references contain commas.
* ``deduplicated:path``: repeated ids in a list are kept once, first occurrence wins.
* ``id_normalised:path``: ``"E. 4.2"`` resolved to ``"c7"`` through the call's id table.
"""
from __future__ import annotations

import difflib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .ids import IdTable
from .schema import inline_refs

__all__ = ["Problem", "Validation", "validate", "Check"]


@dataclass(frozen=True)
class Problem:
    """One reason a proposal (or one item of it) is not acceptable.

    Attributes:
        path: Where, as ``a_claims[2].a_cites[0]`` (``""`` = the whole object).
        code: Machine code: ``missing``, ``unexpected_key``, ``type``, ``enum``, ``not_offered``,
            ``ambiguous_id``, ``ambiguous_form``, ``too_many``, ``too_few``, ``too_long``,
            ``too_short``, ``pattern``, ``not_unique``, ``too_small``, ``too_large``, or a grounding
            code from ``src/verify/`` (``quote_not_in_source``, ``number_not_in_cited`` ...).
        message: Short English text for logs and for the repair turn. Never contains source text.
        fatal: ``True``: the proposal is rejected. ``False``: only the array item at ``drop_path``
            is removed (for example one unsupported claim of a summary), and counted.
            :func:`~.protocol.propose` treats a non-fatal problem as fatal unless its ``drop_path``
            names one item of an array declared in ``item_level`` (fail closed).
        drop_path: The array item to remove when ``fatal`` is ``False`` (``"a_claims[3]"``).
    """

    path: str
    code: str
    message: str
    fatal: bool = True
    drop_path: str | None = None


#: A grounding check: ``check(obj, context) -> problems``. Implemented in ``src/verify/``.
Check = Callable[[dict[str, Any], Any], Sequence[Problem]]


@dataclass
class Validation:
    """Result of :func:`validate`: the normalised object, its problems and the repairs applied."""

    obj: dict[str, Any] | None
    problems: list[Problem] = field(default_factory=list)
    repairs: list[str] = field(default_factory=list)

    @property
    def fatal(self) -> list[Problem]:
        """Problems that reject the whole proposal."""
        return [p for p in self.problems if p.fatal]

    @property
    def droppable(self) -> list[Problem]:
        """Problems that only remove one array item (``drop_path``)."""
        return [p for p in self.problems if not p.fatal]


def _type_ok(value: Any, t: str) -> bool:
    if t == "string":
        return isinstance(value, str)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "null":
        return value is None
    if t == "array":
        return isinstance(value, list)
    if t == "object":
        return isinstance(value, dict)
    return False


def validate(
    obj: Any,
    schema: Mapping[str, Any],
    *,
    id_tables: Mapping[str, IdTable] | None = None,
    caps: Mapping[str, int] | None = None,
    item_level: Sequence[str] = (),
) -> Validation:
    """Validate ``obj`` against ``schema`` (the original schema, with its caps), resolving ids.

    Args:
        obj: Output of :func:`~.parse.parse_object`.
        schema: The tool's parameter schema **before** :func:`~.schema.strict_profile`, so that
            ``maxItems``/``maxLength`` ... are still present (they are enforced here). Local
            ``$ref`` are inlined (:func:`~.schema.inline_refs`) before validation.
        id_tables: ``{"a_evidence[]": table}``: values at that path must resolve in the table.
        caps: Extra caps by path (``{"a_evidence": 3, "b_key_statement": 300}``), for schemas
            generated without ``maxItems``/``maxLength``.
        item_level: Array paths (``"a_claims"``) whose items may be dropped one by one: a problem
            inside such an item is non-fatal and drops that item only.

    Returns:
        A :class:`Validation`. ``obj`` is a normalised deep copy; the input is not modified.
    """
    id_tables = dict(id_tables or {})
    caps = dict(caps or {})
    repairs: list[str] = []
    problems: list[Problem] = []

    def item_scope(path: str) -> str | None:
        for root in item_level:
            if path.startswith(root + "["):
                end = path.index("]", len(root)) + 1
                return path[:end]
        return None

    def add(path: str, code: str, message: str) -> None:
        scope = item_scope(path)
        problems.append(Problem(path, code, message, fatal=scope is None, drop_path=scope))

    def bound_path(path: str) -> str:
        # "a_claims[3].a_cites[1]" -> "a_claims[].a_cites[]"
        out, i = [], 0
        while i < len(path):
            if path[i] == "[":
                j = path.index("]", i)
                out.append("[]")
                i = j + 1
            else:
                out.append(path[i])
                i += 1
        return "".join(out)

    def walk(value: Any, node: Mapping[str, Any], path: str) -> Any:
        branches_key = "anyOf" if "anyOf" in node else "oneOf" if "oneOf" in node else None
        if branches_key:
            return walk_branches(value, node, branches_key, path)
        types = node.get("type")
        types = [types] if isinstance(types, str) else list(types or [])
        bp = bound_path(path)
        table = id_tables.get(bp)
        if table is not None:
            if not isinstance(value, str):
                add(path, "type", "expected an id string")
                return value
            res = table.resolve(value)
            if res.canonical is None:
                code = "ambiguous_id" if res.reason == "ambiguous" else "not_offered"
                add(path, code, f"id not in the offered list ({res.reason})")
                return value
            if res.canonical != value:
                repairs.append(f"id_normalised:{path}")
            return res.canonical
        if types and not any(_type_ok(value, t) for t in types):
            if "array" in types and isinstance(value, str) and node.get("items", {}).get("type") == "string":
                repairs.append(f"wrapped_scalar:{path}")
                value = [value]
            else:
                add(path, "type", f"expected {' or '.join(types)}")
                return value
        if "enum" in node and not _in(value, node["enum"]):
            add(path, "enum", f"value not allowed (allowed: {', '.join(map(str, node['enum'][:15]))})")
            return value
        if "const" in node and not _in(value, [node["const"]]):
            add(path, "enum", f"value not allowed (allowed: {node['const']})")
            return value
        if isinstance(value, dict) and "properties" in node:
            props: Mapping[str, Any] = node["properties"]
            value = dict(value)
            unknown = [k for k in value if k not in props]
            missing = [k for k in props if k not in value]
            for k in unknown:
                # 1) the model dropped our ordering prefix ("evidence" for "a_evidence");
                # 2) a near-identical spelling (ratio >= 0.85). Exactly one candidate, or no repair.
                restored = [m for m in missing if re.sub(r"^[a-z]_", "", m) == k]
                close = restored or [m for m in missing
                                     if difflib.SequenceMatcher(None, k.lower(), m.lower()).ratio() >= 0.85]
                if len(close) == 1:
                    value[close[0]] = value.pop(k)
                    missing.remove(close[0])
                    kind = "key_prefix_restored" if restored else "key_renamed"
                    repairs.append(f"{kind}:{path + '.' if path else ''}{k}->{close[0]}")
                elif node.get("additionalProperties") is not True:
                    add(f"{path + '.' if path else ''}{k}", "unexpected_key", "key not in the format")
            for k in missing:
                add(f"{path + '.' if path else ''}{k}", "missing", "required key missing")
            for k, sub in props.items():
                if k in value:
                    value[k] = walk(value[k], sub, f"{path + '.' if path else ''}{k}")
            return value
        if isinstance(value, dict) and node.get("additionalProperties") is not True:
            if value:  # {"type": "object"} with no properties: only {} is accepted (closed by default)
                add(path, "unexpected_key", "no keys are allowed here")
            return value
        if isinstance(value, list):
            items = node.get("items", {})
            new = [walk(v, items, f"{path}[{i}]") for i, v in enumerate(value)]
            if bound_path(path + "[]") in id_tables:
                seen, dedup = set(), []
                for v in new:
                    key = v if isinstance(v, str) else repr(v)
                    if key not in seen:
                        seen.add(key)
                        dedup.append(v)
                if len(dedup) != len(new):
                    repairs.append(f"deduplicated:{path}")
                new = dedup
            elif node.get("uniqueItems") and len({_key(v) for v in new}) != len(new):
                add(path, "not_unique", "items must be distinct")
            cap = caps.get(bp, node.get("maxItems"))
            if cap is not None and len(new) > cap:
                add(path, "too_many", f"at most {cap} items")
            low = node.get("minItems")
            if low is not None and len(new) < low:
                add(path, "too_few", f"at least {low} items")
            return new
        if isinstance(value, str):
            cap = caps.get(bp, node.get("maxLength"))
            if cap is not None and len(value) > cap:
                add(path, "too_long", f"at most {cap} characters")
            low = node.get("minLength")
            if low is not None and len(value) < low:
                add(path, "too_short", f"at least {low} characters")
            if "pattern" in node and re.search(node["pattern"], value) is None:
                add(path, "pattern", "text does not have the required form")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in node and value < node["minimum"]:
                add(path, "too_small", f"at least {node['minimum']}")
            if "maximum" in node and value > node["maximum"]:
                add(path, "too_large", f"at most {node['maximum']}")
        return value

    def walk_branches(value: Any, node: Mapping[str, Any], key: str, path: str) -> Any:
        # Each branch is tried on its own; its problems and repairs are kept only if it is chosen.
        # Preference: a branch that matches without repairs, then one that matches with repairs.
        # oneOf additionally requires that exactly one branch matches.
        siblings = {k: v for k, v in node.items() if k not in ("anyOf", "oneOf")}
        tried = []
        for branch in node[key]:
            p0, r0 = len(problems), len(repairs)
            out = walk(value, {**siblings, **branch}, path)
            tried.append((out, problems[p0:], repairs[r0:]))
            del problems[p0:]
            del repairs[r0:]
        matches = [t for t in tried if not t[1]]
        if key == "oneOf" and len(matches) > 1:
            add(path, "ambiguous_form", "the value matches more than one allowed form")
            return value
        if matches:
            out, _, reps = min(matches, key=lambda t: len(t[2]))
            repairs.extend(reps)
            return out
        best = min(tried, key=lambda t: len(t[1]))
        if any(p.path != path for p in best[1]) and not any(p.path == path for p in best[1]):
            problems.extend(best[1])  # the form matched at this level; report its inner problems
        else:
            forms = [str(b.get("type", "object" if "properties" in b else "value")) for b in node[key]]
            add(path, "type", f"expected one of: {', '.join(forms)}")
        return value

    if not isinstance(obj, dict):
        return Validation(None, [Problem("", "type", "expected one JSON object")], repairs)
    normalised = walk(obj, inline_refs(schema), "")
    return Validation(normalised, problems, repairs)


def _in(value: Any, allowed: Sequence[Any]) -> bool:
    """Membership that does not confuse ``True`` with ``1`` or ``1`` with ``1.0``."""
    return any(type(a) is type(value) and a == value for a in allowed)


def _key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def drop_items(obj: dict[str, Any], problems: Sequence[Problem]) -> tuple[dict[str, Any], list[str]]:
    """Remove the array items named by non-fatal problems. Returns the new object and dropped paths."""
    targets = sorted({p.drop_path for p in problems if not p.fatal and p.drop_path}, reverse=True,
                     key=lambda s: (s.rsplit("[", 1)[0], int(s.rsplit("[", 1)[1].rstrip("]"))))
    out = _deepcopy_json(obj)
    dropped: list[str] = []
    for tp in targets:
        container_path, idx = tp.rsplit("[", 1)
        idx = int(idx.rstrip("]"))
        container = _get(out, container_path)
        if isinstance(container, list) and 0 <= idx < len(container):
            container.pop(idx)
            dropped.append(tp)
    return out, dropped


def _deepcopy_json(x: Any) -> Any:
    if isinstance(x, dict):
        return {k: _deepcopy_json(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_deepcopy_json(v) for v in x]
    return x


def _get(obj: Any, path: str) -> Any:
    node = obj
    for part in path.replace("]", "").split("."):
        if not part:
            continue
        name, *idx = part.split("[")
        if name:
            node = node.get(name) if isinstance(node, dict) else None
        for i in idx:
            node = node[int(i)] if isinstance(node, list) and int(i) < len(node) else None
    return node
