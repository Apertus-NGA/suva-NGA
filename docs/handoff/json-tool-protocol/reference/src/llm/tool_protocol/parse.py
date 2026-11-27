# SPDX-License-Identifier: Apache-2.0
# Portions adapted from ArchAI (kirtanp/hackpertus-archives, src/archai/llm.py, extract_json),
# Copyright (c) 2026 The ArchAI contributors, MIT License. See NOTICE.
r"""Tolerant extraction of one JSON object from an Apertus reply.

The model is asked for exactly one JSON object. In practice the reply can carry code fences,
inline reasoning (``<|inner_prefix|> ... <|inner_suffix|>`` on the 70B-thinking variant, ``<think>``
blocks elsewhere), leaked template tokens (``<|tools_prefix|>``), prose around the object, or small
syntax slips (raw newlines in strings, ``\'`` in French text, a trailing comma, a German opening
quote closed by a straight quote).

Rules this module guarantees (each one is a test in ``tests/tool_protocol/``):

1. Only **top-level** candidates are considered. A candidate is a balanced ``{...}`` (or ``[...]``)
   span that starts outside any other candidate. When a candidate fails to parse, the scan continues
   *after* its end, never inside it, so an inner object of a broken reply is never returned as if it
   were the answer. (ArchAI's ``extract_json`` retried from the next ``{`` and could return a nested
   object; this is the fix.)
2. An unterminated ``{`` stops the scan with status ``truncated``: no guessing on cut output. An
   unterminated ``[`` is taken as prose (``[sic``); the scan resumes at the next ``{``, and from then
   on only ``{`` opens a candidate (this keeps the scan linear).
3. Repairs are few, targeted, applied to the candidate span only, and reported in ``repairs``.
4. The function never raises on model text and runs in linear time in the input length (the tests
   count scanner steps on adversarial inputs instead of timing them).
5. It never echoes input text in ``error``: the diagnostic can be sent back to the model in a
   repair turn without leaking data into logs twice.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

__all__ = ["ParseResult", "parse_object", "MAX_REPLY_CHARS"]

#: Replies longer than this are refused before scanning (a JSON proposal is a few KB at most).
MAX_REPLY_CHARS = 200_000

ParseStatus = Literal["ok", "no_object", "truncated", "invalid_json", "top_level_array", "too_long"]

# Inline reasoning of Apertus thinking variants (measured on Keera, LESSONS K11), closed or not.
_INNER = re.compile(r"<\|inner_prefix\|>.*?(?:<\|inner_suffix\|>|\Z)", re.S)
_THINK = re.compile(r"<think>.*?(?:</think>|\Z)", re.S | re.I)
# Any remaining chat-template token such as <|tools_prefix|>, <|assistant_end|>.
_CONTROL = re.compile(r"<\|[A-Za-z0-9_]{1,40}\|>")
_FENCE = re.compile(r"```[A-Za-z]*[ \t]*")


@dataclass(frozen=True)
class ParseResult:
    """Outcome of :func:`parse_object`.

    Attributes:
        obj: The parsed top-level JSON object, or ``None`` on failure.
        status: ``ok`` or a failure code (see ``ParseStatus``).
        repairs: Names of the syntax repairs applied, in order (empty when the reply was clean).
        stripped: What was removed before scanning: ``fence``, ``inner_reasoning``, ``think``,
            ``control_token``, ``bom``.
        error: A short diagnostic for a repair turn. Never contains reply text.
    """

    obj: dict[str, Any] | None
    status: ParseStatus
    repairs: tuple[str, ...] = field(default_factory=tuple)
    stripped: tuple[str, ...] = field(default_factory=tuple)
    error: str | None = None

    @property
    def ok(self) -> bool:
        """``True`` when an object was decoded (``status == "ok"``)."""
        return self.obj is not None


def _clean(text: str) -> tuple[str, list[str]]:
    stripped: list[str] = []
    if text.startswith("﻿"):
        text = text[1:]
        stripped.append("bom")
    for name, rx in (("inner_reasoning", _INNER), ("think", _THINK), ("control_token", _CONTROL),
                     ("fence", _FENCE)):
        new = rx.sub("", text)
        if new != text:
            stripped.append(name)
            text = new
    return text, stripped


def _candidates(text: str, ops: list[int] | None = None) -> tuple[list[tuple[int, int]], bool]:
    """Top-level balanced spans ``[start, end)``; second value is True if the scan hit an unterminated ``{``.

    ``ops`` (tests only) receives the number of characters visited: at most about twice the length.
    """
    spans: list[tuple[int, int]] = []
    i, n, steps = 0, len(text), 0
    lists_allowed = True
    try:
        while i < n:
            ch = text[i]
            steps += 1
            if ch != "{" and not (ch == "[" and lists_allowed):
                i += 1
                continue
            start, depth, in_str, esc = i, 0, False, False
            j = i
            while j < n:
                c = text[j]
                steps += 1
                if in_str:
                    if esc:
                        esc = False
                    elif c == "\\":
                        esc = True
                    elif c == '"':
                        in_str = False
                elif c == '"':
                    in_str = True
                elif c in "{[":
                    depth += 1
                elif c in "}]":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            if j >= n:  # never closed
                if text[start] == "[":
                    # an unbalanced "[" in prose: resume at the next "{" and stop opening list candidates,
                    # otherwise every later "[" would rescan to the end (quadratic).
                    lists_allowed = False
                    nxt = text.find("{", start + 1)
                    i = n if nxt < 0 else nxt
                    continue
                return spans, True
            spans.append((start, j + 1))
            i = j + 1
        return spans, False
    finally:
        if ops is not None:
            ops.append(steps)


def _fix_backslash_quote(s: str) -> str:
    # French text: the model escapes an apostrophe as \' which JSON forbids.
    return s.replace("\\'", "'")


_STOP = re.compile(r'["“»\n]')
_NON_SPACE = re.compile(r"\S")


def _fix_german_quotes(s: str, ops: list[int] | None = None) -> str:
    """A German opening quote „ (or «) closed by a straight " inside a JSON string: turn that " into “ (or »).

    Single pass: the next stop character and the verdict for each straight quote are computed once,
    so the repair stays linear even with thousands of opening quotes (``ops`` counts steps, tests only).
    """
    out, i, n, steps = [], 0, len(s), 0
    stop_at: int | None = None     # position of the next '"', '“', '»' or newline at or after i + 1
    verdict: dict[int, bool] = {}  # straight quote position -> is it prose (not a JSON string end)?
    while i < n:
        c = s[i]
        steps += 1
        out.append(c)
        if c in "„«":
            if stop_at is None or stop_at <= i:
                m = _STOP.search(s, i + 1)
                stop_at = m.start() if m else n
                steps += 1
            k = stop_at
            if k < n and s[k] == '"':
                if k not in verdict:
                    m2 = _NON_SPACE.search(s, k + 1)
                    # a real JSON string end is followed by , } ] or : ; anything else is prose
                    verdict[k] = bool(m2) and m2.group(0) not in ",}]:"
                    steps += 1
                if verdict[k]:
                    closer = "“" if c == "„" else "»"
                    out.append(s[i + 1:k])
                    out.append(closer)
                    steps += k - i
                    i = k + 1
                    continue
        i += 1
    if ops is not None:
        ops.append(steps)
    return "".join(out)


_TRAILING_COMMA = re.compile(r",\s*[}\]]")


def _fix_trailing_commas(s: str) -> str:
    # String-aware: only commas outside strings are touched. Matching at a position (no slicing).
    res, in_str, esc, last = [], False, False, 0
    for idx, c in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == ",":
            m = _TRAILING_COMMA.match(s, idx)
            if m:
                res.append(s[last:idx])
                last = idx + 1
    res.append(s[last:])
    return "".join(res)


_REPAIRS = (
    ("lenient_control_chars", None),
    ("backslash_quote", _fix_backslash_quote),
    ("german_quotes", _fix_german_quotes),
    ("trailing_comma", _fix_trailing_commas),
)


def _try_load(span: str) -> tuple[Any, tuple[str, ...], str | None]:
    try:
        return json.loads(span), (), None
    except json.JSONDecodeError as e:
        first_error = f"{e.msg} at line {e.lineno} column {e.colno}"
    applied: list[str] = []
    current = span
    for name, fn in _REPAIRS:
        if fn is None:
            try:
                return json.JSONDecoder(strict=False).decode(current), (*applied, name), None
            except json.JSONDecodeError:
                continue
        fixed = fn(current)
        if fixed == current:
            continue
        current = fixed
        applied.append(name)
        for strict in (True, False):
            try:
                val = json.JSONDecoder(strict=strict).decode(current)
                return val, tuple(applied) + (() if strict else ("lenient_control_chars",)), None
            except json.JSONDecodeError:
                continue
    return None, (), first_error


def parse_object(text: str | None) -> ParseResult:
    r"""Return the first top-level JSON object of a model reply.

    Args:
        text: The raw ``content`` of the assistant message (``None`` or empty is a failure).

    Returns:
        A :class:`ParseResult`. ``obj`` is set only when a top-level object (or a list holding
        exactly one object, unwrapped and reported as ``unwrapped_singleton_list``) was decoded.

    Example:
        >>> parse_object('Sure! ```json\n{"a_evidence": ["c3"]}\n```').obj
        {'a_evidence': ['c3']}
    """
    if not text:
        return ParseResult(None, "no_object", error="empty reply")
    if len(text) > MAX_REPLY_CHARS:
        return ParseResult(None, "too_long", error=f"reply longer than {MAX_REPLY_CHARS} characters")
    cleaned, stripped = _clean(text)
    spans, truncated = _candidates(cleaned)
    pre_repairs: tuple[str, ...] = ()
    if truncated and ("„" in cleaned or "«" in cleaned):
        # A German opening quote closed by a straight quote unbalances the string scan itself:
        # repair the whole text once and rescan (the repair only touches quotes inside strings).
        fixed = _fix_german_quotes(cleaned)
        spans2, truncated2 = _candidates(fixed)
        if not truncated2:
            cleaned, spans, truncated, pre_repairs = fixed, spans2, False, ("german_quotes",)
    first_error: str | None = None
    saw_array = False
    for start, end in spans:
        val, repairs, err = _try_load(cleaned[start:end])
        repairs = pre_repairs + repairs
        if isinstance(val, dict):
            return ParseResult(val, "ok", repairs, tuple(stripped))
        if isinstance(val, list):
            if len(val) == 1 and isinstance(val[0], dict):
                return ParseResult(val[0], "ok", (*repairs, "unwrapped_singleton_list"), tuple(stripped))
            if any(isinstance(x, dict) for x in val):
                saw_array = True
            continue
        if err and first_error is None and cleaned[start] == "{":
            first_error = err
    if truncated:
        return ParseResult(None, "truncated", stripped=tuple(stripped),
                           error="the JSON object is not closed (reply cut off?)")
    if first_error:
        return ParseResult(None, "invalid_json", stripped=tuple(stripped), error=f"invalid JSON: {first_error}")
    if saw_array:
        return ParseResult(None, "top_level_array", stripped=tuple(stripped),
                           error="expected one JSON object, got a list of several objects")
    return ParseResult(None, "no_object", stripped=tuple(stripped), error="no JSON object found in the reply")
