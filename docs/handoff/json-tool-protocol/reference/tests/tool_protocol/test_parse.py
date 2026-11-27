# SPDX-License-Identifier: Apache-2.0
"""Unit tests of parse_object: one test per rule of the module docstring and per known failure mode."""
import pytest

from llm.tool_protocol import parse_object


@pytest.mark.parametrize("text, expected", [
    ('{"a": 1}', {"a": 1}),
    ('  \n{"a": 1}\n', {"a": 1}),
    ('```json\n{"a": 1}\n```', {"a": 1}),
    ('```\n{"a": 1}\n```', {"a": 1}),
    ('Here is the JSON:\n{"a": 1}\nHope this helps.', {"a": 1}),
    ('﻿{"a": 1}', {"a": 1}),
    ('{"a": "x {not a brace} y"}', {"a": "x {not a brace} y"}),
    ('{"a": "quote \\" inside"}', {"a": 'quote " inside'}),
    ('{"a": "Zürich – «Unfall» – ß"}', {"a": "Zürich – «Unfall» – ß"}),
])
def test_clean_and_wrapped_replies(text, expected):
    r = parse_object(text)
    assert r.status == "ok" and r.obj == expected


def test_inline_reasoning_of_70b_thinking_is_removed():
    r = parse_object('<|inner_prefix|>Let me think {"a": 0}<|inner_suffix|>{"a": 1}')
    assert r.obj == {"a": 1} and "inner_reasoning" in r.stripped


def test_unclosed_inline_reasoning_means_no_answer():
    r = parse_object('<|inner_prefix|>still thinking {"a": 0}')
    assert not r.ok


def test_think_tags_and_leaked_template_tokens():
    r = parse_object('<think>hmm</think><|tools_prefix|>{"a": 1}<|tools_suffix|>')
    assert r.obj == {"a": 1}
    assert {"think", "control_token"} <= set(r.stripped)


def test_first_top_level_object_wins():
    assert parse_object('{"a": 1} {"a": 2}').obj == {"a": 1}


def test_prose_braces_before_the_object_are_skipped():
    r = parse_object('Use {placeholders} like this: {"a": 1}')
    assert r.obj == {"a": 1}


def test_nested_object_of_a_broken_reply_is_never_returned():
    # ArchAI's extract_json would return {"b": 1} here: the outer object fails, it retried at the next "{".
    r = parse_object('{"a": {"b": 1}, oops}')
    assert r.obj is None and r.status == "invalid_json"


def test_truncated_reply_is_a_failure_not_a_guess():
    r = parse_object('{"a_calls": [{"a_tool": "x", "b_args": {"q": 1}}, {"a_tool": "y"')
    assert r.obj is None and r.status == "truncated"


def test_singleton_list_is_unwrapped_and_reported():
    r = parse_object('[{"a": 1}]')
    assert r.obj == {"a": 1} and "unwrapped_singleton_list" in r.repairs


def test_list_of_several_objects_is_refused():
    r = parse_object('[{"a": 1}, {"a": 2}]')
    assert r.obj is None and r.status == "top_level_array"


def test_bracket_citations_in_prose_do_not_hide_the_object():
    assert parse_object('See [1] and E. [4.2: {"a": 1}').obj == {"a": 1}


@pytest.mark.parametrize("text, repair", [
    ('{"a": "line1\nline2"}', "lenient_control_chars"),
    ('{"a": "l\\\'assurance"}', "backslash_quote"),
    ('{"a": "Die „Suva" hat"}', "german_quotes"),
    ('{"a": [1, 2,], }', "trailing_comma"),
])
def test_targeted_syntax_repairs(text, repair):
    r = parse_object(text)
    assert r.ok, r
    assert repair in r.repairs


def test_german_quote_repair_keeps_the_text():
    assert parse_object('{"a": "Die „Suva" hat"}').obj == {"a": "Die „Suva“ hat"}


def test_trailing_comma_inside_a_string_is_kept():
    assert parse_object('{"a": "x,}", "b": [1,],}').obj == {"a": "x,}", "b": [1]}


@pytest.mark.parametrize("text, status", [
    (None, "no_object"), ("", "no_object"), ("No JSON here.", "no_object"),
    ("{'a': 1}", "invalid_json"), ("x" * 200_001, "too_long"),
])
def test_failures_are_statuses_not_exceptions(text, status):
    r = parse_object(text)
    assert r.obj is None and r.status == status and r.error


def test_error_never_echoes_reply_text():
    secret = "8C_123/2025 confidential sentence"
    r = parse_object('{"a": ' + secret)
    assert secret not in (r.error or "")
