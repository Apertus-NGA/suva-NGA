# SPDX-License-Identifier: Apache-2.0
"""Fail-closed hardening: generated schemas, code-only constraints, containment of checks, linear parsing,
the whitespace runaway, and the error branches of both entry points. Each test names the rule it pins."""
import json

import pytest

from llm.tool_protocol import (
    ChatReply,
    Problem,
    Tier,
    Tool,
    consideration_table,
    parse_object,
    propose,
    run_tools,
    validate,
)
from llm.tool_protocol.parse import _candidates, _fix_german_quotes

from .contracts import JUSTIFY, SUMMARY, TAG_SIGNAL
from .fakes import RequestRejected, ScriptedChat, TransportFailure

CONS = [{"id": f"c{i}", "e_number": str(i), "text": f"Erwägung {i}."} for i in range(1, 5)]
TABLE = consideration_table(CONS)
COMMON = dict(system="s", user="u", purpose="t", prompt_version="v1")

# A hand-written schema with the shapes pydantic generates: $defs/$ref, Optional (anyOf with null).
REF_SCHEMA = {
    "type": "object",
    "$defs": {"Claim": {"type": "object", "additionalProperties": False, "required": ["a_cites", "b_text"],
                        "properties": {"a_cites": {"type": "array", "items": {"type": "string"}, "maxItems": 2},
                                       "b_text": {"type": "string", "maxLength": 20}}}},
    "properties": {"a_claims": {"type": "array", "items": {"$ref": "#/$defs/Claim"}},
                   "b_note": {"anyOf": [{"type": "string", "maxLength": 10}, {"type": "null"}], "default": None}},
    "additionalProperties": False, "required": ["a_claims", "b_note"],
}
REF_TOOL = Tool("claims_form", "Claims.", REF_SCHEMA)
GARBAGE = {"a_claims": [{"a_cites": ["c99", 5], "b_text": 42, "x_extra": 1}], "b_note": {"any": "thing"}}


# ---------------------------------------------------------------- F1: $ref, anyOf, oneOf, pydantic

def test_ref_and_optional_are_validated_not_waved_through():
    v = validate(GARBAGE, REF_SCHEMA, id_tables={"a_claims[].a_cites[]": TABLE})
    codes = {(p.path, p.code) for p in v.problems}
    assert ("a_claims[0].a_cites[0]", "not_offered") in codes and ("a_claims[0].b_text", "type") in codes
    assert ("a_claims[0].x_extra", "unexpected_key") in codes and ("b_note", "type") in codes
    ok = validate({"a_claims": [{"a_cites": ["E. 2"], "b_text": "x"}], "b_note": None}, REF_SCHEMA,
                  id_tables={"a_claims[].a_cites[]": TABLE})
    assert not ok.problems and ok.obj["a_claims"][0]["a_cites"] == ["c2"]
    too_long = validate({"a_claims": [], "b_note": "x" * 11}, REF_SCHEMA)
    assert [p.code for p in too_long.problems] == ["type"]  # matches neither branch: too long and not null


def test_ref_tool_through_propose_object_tier_fails_closed_and_binds_nested_ids():
    chat = ScriptedChat([json.dumps(GARBAGE), json.dumps(GARBAGE)])
    out = propose(chat, REF_TOOL, tier=Tier.OBJECT, id_tables={"a_claims[].a_cites[]": TABLE}, **COMMON)
    assert out.status == "failed" and out.value is None and out.reason == "reference"
    assert "c1 | c2" in chat.requests[0].messages[0]["content"]  # the nested enum reached the prompt
    good = {"a_claims": [{"a_cites": ["c1"], "b_text": "ok"}], "b_note": "n"}
    out2 = propose(ScriptedChat([json.dumps(good)]), REF_TOOL, tier=Tier.STRICT,
                   id_tables={"a_claims[].a_cites[]": TABLE}, **COMMON)
    assert out2.status == "ok" and out2.value == good


def test_pydantic_nested_and_optional_through_propose():
    pydantic = pytest.importorskip("pydantic")

    class Claim(pydantic.BaseModel):
        model_config = pydantic.ConfigDict(extra="forbid")
        a_cites: list[str] = pydantic.Field(max_length=3)
        b_text: str = pydantic.Field(min_length=1, max_length=300)

    class Form(pydantic.BaseModel):
        model_config = pydantic.ConfigDict(extra="forbid")
        a_claims: list[Claim]
        b_note: str | None = None

    tool = Tool("form", "A form.", Form.model_json_schema())
    bad = propose(ScriptedChat([json.dumps(GARBAGE)] * 2), tool, tier=Tier.OBJECT,
                  id_tables={"a_claims[].a_cites[]": TABLE}, **COMMON)
    assert bad.status == "failed" and bad.value is None
    good = {"a_claims": [{"a_cites": ["c3"], "b_text": "t"}], "b_note": None}
    out = propose(ScriptedChat([json.dumps(good)]), tool, tier=Tier.OBJECT,
                  id_tables={"a_claims[].a_cites[]": TABLE}, **COMMON)
    assert out.status == "ok" and Form.model_validate(out.value)  # what code accepts, pydantic accepts
    empty = {"a_claims": [{"a_cites": ["c3"], "b_text": ""}], "b_note": None}
    assert propose(ScriptedChat([json.dumps(empty)] * 2), tool, tier=Tier.OBJECT, **COMMON).status == "failed"


def test_one_of_needs_exactly_one_matching_form():
    schema = {"type": "object", "additionalProperties": False, "required": ["a"],
              "properties": {"a": {"oneOf": [{"type": "string"}, {"type": "string", "maxLength": 5}]}}}
    assert [p.code for p in validate({"a": "abc"}, schema).problems] == ["ambiguous_form"]
    assert not validate({"a": "abcdefgh"}, schema).problems


def test_const_and_strict_enum_membership():
    schema = {"type": "object", "additionalProperties": False, "required": ["a", "b"],
              "properties": {"a": {"const": "x"}, "b": {"enum": [True, "no"]}}}
    assert not validate({"a": "x", "b": True}, schema).problems
    assert {p.code for p in validate({"a": "y", "b": 1}, schema).problems} == {"enum"}  # 1 is not True


@pytest.mark.parametrize("schema, fragment", [
    ({"type": "object", "properties": {"a": {"type": "string", "format": "date"}}}, "format"),
    ({"type": "object", "properties": {"a": {"allOf": [{"type": "string"}]}}}, "allOf"),
    ({"type": "object", "additionalProperties": {"type": "string"}, "properties": {}}, "not a schema"),
    ({"type": "object", "properties": {"a": {"type": "array", "items": [{"type": "string"}]}}}, "tuple items"),
    ({"type": "object", "properties": {"a": {"type": "string", "not": {"const": "x"}}}}, "not"),
])
def test_tool_refuses_keywords_code_does_not_enforce(schema, fragment):
    with pytest.raises(ValueError, match=fragment):
        Tool("t", "d", schema)


def test_enum_binding_on_an_optional_field_is_refused():
    schema = {"type": "object", "properties": {"a": {"anyOf": [{"type": "string"}, {"type": "null"}]}}}
    with pytest.raises(ValueError, match="plain string field"):
        propose(ScriptedChat([]), Tool("t", "d", schema), id_tables={"a": TABLE}, **COMMON)


# ---------------------------------------------------------------- F4: code-only constraints

@pytest.mark.parametrize("node, good, bad, code", [
    ({"type": "string", "minLength": 3}, "abc", "ab", "too_short"),
    ({"type": "string", "pattern": "^[A-Z]"}, "Abc", "abc", "pattern"),
    ({"type": "array", "items": {"type": "string"}, "uniqueItems": True}, ["a", "b"], ["a", "a"], "not_unique"),
    ({"type": "integer", "minimum": 1}, 1, 0, "too_small"),
    ({"type": "number", "maximum": 1.5}, 1.5, 2, "too_large"),
    ({"type": "array", "items": {"type": "string"}, "minItems": 1}, ["a"], [], "too_few"),
])
def test_constraints_dropped_from_the_wire_are_enforced_by_code(node, good, bad, code):
    schema = {"type": "object", "additionalProperties": False, "required": ["a"], "properties": {"a": node}}
    assert not validate({"a": good}, schema).problems
    assert [p.code for p in validate({"a": bad}, schema).problems] == [code]


def test_tool_caps_are_read_by_propose():
    tool = Tool("t", "d", {"type": "object", "properties": {"a_ids": {"type": "array", "items": {"type": "string"}}}},
                caps={"a_ids": 1})
    out = propose(ScriptedChat(['{"a_ids": ["c1", "c2", "c3"]}'] * 2), tool, id_tables={"a_ids[]": TABLE}, **COMMON)
    assert out.status == "failed" and out.reason == "schema" and out.problems[0].code == "too_many"


def test_justify_needs_evidence_and_a_statement():
    empty = '{"a_evidence": [], "b_key_statement": "", "c_label": "relevant"}'
    out = propose(ScriptedChat([empty, empty]), JUSTIFY, id_tables={"a_evidence[]": TABLE}, **COMMON)
    assert out.status == "failed" and {p.code for p in out.problems} == {"too_few", "too_short"}


# ---------------------------------------------------------------- F8: checks cannot open a hole

def _soft(drop_path):
    def check(obj, ctx):
        return [Problem("b_quote", "quote_not_in_source", "not verbatim", fatal=False, drop_path=drop_path)]
    return check


@pytest.mark.parametrize("drop_path, item_level", [(None, ()), ("a_claims[0]", ()), ("b_quote", ["a_claims"])])
def test_non_fatal_check_problem_outside_item_level_is_fatal(drop_path, item_level):
    reply = '{"a_consideration": "c1", "b_quote": "invented", "c_value": "x"}'
    out = propose(ScriptedChat([reply, reply]), TAG_SIGNAL, id_tables={"a_consideration": TABLE},
                  checks=[_soft(drop_path)], item_level=item_level, **COMMON)
    assert out.status == "failed" and out.value is None and out.reason == "grounding"


def test_fatal_grounding_reason_and_problems_are_reported():
    def hard(obj, ctx):
        return [Problem("b_quote", "quote_not_in_source", "not verbatim")]
    reply = '{"a_consideration": "c1", "b_quote": "q", "c_value": "q"}'
    out = propose(ScriptedChat([reply, reply]), TAG_SIGNAL, id_tables={"a_consideration": TABLE}, checks=[hard],
                  **COMMON)
    assert out.reason == "grounding" and [p.code for p in out.problems] == ["quote_not_in_source"]


# ---------------------------------------------------------------- F7: the parser stays linear

ADVERSARIAL = {
    "open_brackets": "[" * 50_000,
    "open_bracket_words": "[x " * 16_000,
    "brace_then_german_quotes": "{" + "„" * 50_000,
    "many_german_quotes_in_a_string": '{"a": "' + '„x" y ' * 8_000 + '"}',
    "lists_and_objects": "[ {} " * 10_000,
}


@pytest.mark.parametrize("name", sorted(ADVERSARIAL))
def test_parser_work_is_linear_on_adversarial_input(name):
    text = ADVERSARIAL[name]
    ops: list[int] = []
    _candidates(text, ops)
    _fix_german_quotes(text, ops)
    assert all(o <= 3 * len(text) + 10 for o in ops), (name, ops, len(text))
    parse_object(text)  # and it returns (status irrelevant here)


def test_unclosed_bracket_in_prose_does_not_hide_the_object():
    r = parse_object('[sic the answer is {"a_evidence": ["c1"]} and [another {"b": 1}')
    assert r.ok and r.obj == {"a_evidence": ["c1"]}


# ---------------------------------------------------------------- F12: whitespace runaway under STRICT

def test_whitespace_runaway_steps_down_once_without_using_the_repair():
    runaway = ChatReply('{"a_evidence": ["c1"]' + " " * 400, "length", "m")
    ok = '{"a_evidence": ["c1"], "b_key_statement": "k", "c_label": "relevant"}'
    chat = ScriptedChat([runaway, ok])
    out = propose(chat, JUSTIFY, tier=Tier.STRICT, id_tables={"a_evidence[]": TABLE}, **COMMON)
    assert out.status == "ok" and out.tier is Tier.OBJECT and out.attempts == 1
    assert out.trace[0]["cascade"] == "whitespace_runaway"
    assert chat.requests[1].response_format == {"type": "json_object"} and chat.requests[1].max_tokens == 400


def test_whitespace_runaway_is_stepped_down_only_once_and_only_from_strict():
    runaway = ChatReply("{" + " " * 400, "length", "m")
    out = propose(ScriptedChat([runaway, runaway, runaway]), JUSTIFY, tier=Tier.STRICT,
                  id_tables={"a_evidence[]": TABLE}, **COMMON)
    assert out.status == "failed" and out.reason == "truncated" and out.tier is Tier.OBJECT


# ---------------------------------------------------------------- F5 / F18 / F17: pass-through and branches

def test_cache_salt_reaches_every_request_of_both_entry_points():
    ok = '{"a_evidence": ["c1"], "b_key_statement": "k", "c_label": "relevant"}'
    chat = ScriptedChat(["{", ok])
    propose(chat, JUSTIFY, id_tables={"a_evidence[]": TABLE}, cache_salt="rep1", **COMMON)
    loop_chat = ScriptedChat(['{"a_calls": []}'])
    tool = Tool("get", "d", {"type": "object", "properties": {"a_id": {"type": "string"}}},
                handler=lambda a, c: "x")
    run_tools(loop_chat, [tool], cache_salt="rep1", **COMMON)
    assert {r.cache_salt for r in chat.requests + loop_chat.requests} == {"rep1"}


def test_repair_turn_replays_a_long_reply_whole_and_the_fallback_delimits_it():
    long_reply = '{"a_claims": [' + ",".join(['{"a_cites": ["c9"], "b_text": "t", "c_section": "law"}'] * 150) + "]"
    assert 4_000 < len(long_reply) < 16_000
    chat = ScriptedChat([long_reply, RequestRejected("message_roles"), "{}"])
    propose(chat, SUMMARY, id_tables={"a_claims[].a_cites[]": TABLE}, max_tokens=3000, **COMMON)
    assert chat.requests[1].messages[2]["content"] == long_reply  # assistant turn, not cut at 4,000
    folded = chat.requests[2].messages[1]["content"]
    assert "<data id=" in folded and "kind=previous_reply" in folded


def test_rejected_other_fails_without_retry():
    chat = ScriptedChat([RequestRejected("other", "bad")])
    out = propose(chat, JUSTIFY, id_tables={"a_evidence[]": TABLE}, **COMMON)
    assert out.status == "failed" and out.reason == "rejected" and len(chat.requests) == 1


def test_top_level_array_of_objects_is_not_an_answer():
    two = '[{"a_evidence": ["c1"]}, {"a_evidence": ["c2"]}]'
    out = propose(ScriptedChat([two, two]), JUSTIFY, id_tables={"a_evidence[]": TABLE}, **COMMON)
    assert out.status == "failed" and out.reason == "invalid_json" and out.trace[0]["parse"] == "top_level_array"


GET = Tool("get_text", "Get a consideration's text.",
           {"type": "object", "properties": {"a_id": {"type": "string"}}},
           handler=lambda a, c: {"c1": "one", "c2": "two"}[a["a_id"]])
BOOM = Tool("boom", "Fails.", {"type": "object", "properties": {}}, handler=lambda a, c: 1 / 0)


@pytest.mark.parametrize("error", [TransportFailure("x"), RequestRejected("other")])
def test_loop_transport_or_rejection_fails(error):
    out = run_tools(ScriptedChat([error]), [GET], **COMMON)
    assert out.status == "failed" and out.stop_reason == "transport_or_rejected" and out.calls == ()


def test_loop_handler_exception_is_fed_back_not_raised():
    chat = ScriptedChat(['{"a_calls": [{"a_tool": "boom", "b_args": {}}]}', '{"a_calls": []}'])
    out = run_tools(chat, [BOOM], **COMMON)
    assert out.status == "finished" and out.calls[0].error.startswith("ZeroDivisionError")
    assert "ZeroDivisionError" in chat.requests[1].messages[1]["content"]


def test_loop_finish_together_with_calls_runs_them_then_stops():
    chat = ScriptedChat(['{"a_calls": [{"a_tool": "get_text", "b_args": {"a_id": "c1"}}, {"a_tool": "finish"}]}'])
    out = run_tools(chat, [GET], id_tables={"get_text": {"a_id": TABLE}}, **COMMON)
    assert out.status == "finished" and [c.result for c in out.calls] == ["one"] and len(chat.requests) == 1


def test_loop_reminder_counts_a_required_call_by_its_arguments():
    # get_text(c1) ran, but get_text(c2) was required: the reminder must still come, then code runs it.
    chat = ScriptedChat(['{"a_calls": [{"a_tool": "get_text", "b_args": {"a_id": "c1"}}]}', '{"a_calls": []}',
                         '{"a_calls": []}'])
    out = run_tools(chat, [GET], id_tables={"get_text": {"a_id": TABLE}}, required=[("get_text", {"a_id": "c2"})],
                    **COMMON)
    assert out.feedback_rounds == 1 and "Not done yet" in chat.requests[2].messages[1]["content"]
    assert [(c.args["a_id"], c.origin) for c in out.calls] == [("c1", "model"), ("c2", "required")]
