# SPDX-License-Identifier: Apache-2.0
"""Behaviour of propose() and run_tools() with scripted chat functions (no network)."""
import json

import pytest

from llm.tool_protocol import (
    ChatReply,
    RequestRejected,
    Tier,
    Tool,
    TransportFailure,
    consideration_table,
    delimit,
    propose,
    run_tools,
)

from .checks_example import quote_in_cited
from .contracts import JUSTIFY, SUMMARY, TAG_SIGNAL
from .fakes import ScriptedChat

RULING = {
    "docket": "8C_000/2025",
    "considerations": [
        {"id": "c1", "e_number": "1", "text": "Die Beschwerde ist zulässig."},
        {"id": "c2", "e_number": "4.2", "text": "Der Integritätsschaden beträgt 10 Prozent (Art. 36 Abs. 4 UVV)."},
        {"id": "c3", "e_number": "5", "text": "Die Beschwerde wird abgewiesen."},
    ],
}
TABLE = {"a_evidence[]": consideration_table(RULING["considerations"])}
GOOD = json.dumps({"a_evidence": ["c2"], "b_key_statement": "Rate 10 %.", "c_label": "relevant"})


def call(chat, tool=JUSTIFY, **kw):
    kw.setdefault("id_tables", TABLE)
    return propose(chat, tool, system="You read Swiss Federal Supreme Court rulings.",
                   user=delimit("ruling", "...", "n0nce"), purpose="triage_justify", prompt_version="t1", **kw)


def test_first_attempt_ok_sends_one_system_message_and_strict_enum():
    chat = ScriptedChat([GOOD])
    out = call(chat)
    assert out.status == "ok" and out.value["a_evidence"] == ["c2"] and out.attempts == 1
    req = chat.requests[0]
    assert [m["role"] for m in req.messages] == ["system", "user"]
    schema = req.response_format["json_schema"]["schema"]
    assert schema["properties"]["a_evidence"]["items"]["enum"] == ["c1", "c2", "c3"]
    assert "maxItems" not in json.dumps(schema) and req.temperature == 0.0


def test_invalid_json_then_repair_turn_with_diagnostics_only():
    chat = ScriptedChat(["{'a_evidence': ['c2']}", GOOD])
    out = call(chat)
    assert out.status == "ok_repaired" and out.attempts == 2
    roles = [m["role"] for m in chat.requests[1].messages]
    assert roles == ["system", "user", "assistant", "user"]
    assert "could not be used" in chat.requests[1].messages[-1]["content"]


def test_unoffered_id_twice_fails_closed_with_reference_reason():
    bad = json.dumps({"a_evidence": ["c7"], "b_key_statement": "x", "c_label": "relevant"})
    out = call(ScriptedChat([bad, bad]))
    assert out.status == "failed" and out.reason == "reference" and out.value is None
    assert {p.code for p in out.problems} == {"not_offered"}


def test_length_is_never_parsed_and_budget_doubles_once():
    chat = ScriptedChat([ChatReply(GOOD[:20], "length"), GOOD])
    out = call(chat, max_tokens=100)
    assert out.ok and [r.max_tokens for r in chat.requests] == [100, 200]
    out2 = call(ScriptedChat([ChatReply(GOOD, "length"), ChatReply(GOOD, "length")]))
    assert out2.status == "failed" and out2.reason == "truncated"


def test_cascade_steps_down_on_response_format_rejection_without_counting_an_attempt():
    chat = ScriptedChat([RequestRejected("response_format", "json_schema unsupported"), GOOD])
    out = call(chat)
    assert out.ok and out.tier is Tier.OBJECT and out.attempts == 1
    assert chat.requests[1].response_format == {"type": "json_object"}
    assert "Shape (placeholders" in chat.requests[1].messages[0]["content"]


def test_cascade_reaches_prompt_tier():
    chat = ScriptedChat([RequestRejected("response_format"), RequestRejected("response_format"), GOOD])
    out = call(chat)
    assert out.ok and out.tier is Tier.PROMPT and chat.requests[-1].response_format is None


def test_repair_folded_into_one_user_message_when_roles_are_refused():
    chat = ScriptedChat(["not json", RequestRejected("message_roles"), GOOD])
    out = call(chat)
    assert out.ok
    assert [m["role"] for m in chat.requests[-1].messages] == ["system", "user"]
    assert "Your previous reply was" in chat.requests[-1].messages[-1]["content"]


def test_transport_failure_is_failed_never_a_label():
    out = call(ScriptedChat([TransportFailure("timeout")]))
    assert out.status == "failed" and out.reason == "transport" and out.value is None


def test_trace_has_hashes_not_text():
    out = call(ScriptedChat([GOOD]))
    t = out.trace[0]
    assert t["content_sha256"] and "content" not in t and t["finish_reason"] == "stop"


def test_grounding_check_rejects_a_paraphrased_quote_then_accepts_the_repair():
    tool_tables = {"a_consideration": consideration_table(RULING["considerations"], none_option=True)}
    para = json.dumps({"a_consideration": "c2", "b_quote": "Integritätsschaden von zehn Prozent", "c_value": "10"})
    exact = json.dumps({"a_consideration": "E. 4.2", "b_quote": "beträgt 10 Prozent", "c_value": "10 Prozent"})
    out = call(ScriptedChat([para, exact]), tool=TAG_SIGNAL, id_tables=tool_tables, checks=[quote_in_cited],
               context=RULING)
    assert out.status == "ok_repaired" and out.value["a_consideration"] == "c2"


def test_abstention_is_a_valid_answer():
    tool_tables = {"a_consideration": consideration_table(RULING["considerations"], none_option=True)}
    none = json.dumps({"a_consideration": "none", "b_quote": "", "c_value": ""})
    out = call(ScriptedChat([none]), tool=TAG_SIGNAL, id_tables=tool_tables, checks=[quote_in_cited], context=RULING)
    assert out.status == "ok" and out.value["a_consideration"] == "none"


def test_unsupported_claims_are_dropped_and_counted_after_the_repair_turn():
    tables = {"a_claims[].a_cites[]": consideration_table(RULING["considerations"])}
    reply = json.dumps({"a_claims": [{"a_cites": ["c2"], "b_text": "Rate 10 %.", "c_section": "law"},
                                     {"a_cites": ["c9"], "b_text": "Invented.", "c_section": "law"}],
                        "b_outcome": "dismissed", "c_unknown": []})
    out = call(ScriptedChat([reply, reply]), tool=SUMMARY, id_tables=tables, item_level=["a_claims"])
    assert out.status == "ok_repaired" and out.dropped == ("a_claims[1]",) and len(out.value["a_claims"]) == 1


def test_all_claims_dropped_is_a_failure():
    tables = {"a_claims[].a_cites[]": consideration_table(RULING["considerations"])}
    reply = json.dumps({"a_claims": [{"a_cites": ["c9"], "b_text": "x", "c_section": "law"}],
                        "b_outcome": "dismissed", "c_unknown": []})
    out = call(ScriptedChat([reply, reply]), tool=SUMMARY, id_tables=tables, item_level=["a_claims"])
    assert out.status == "failed" and out.reason == "grounding"


def test_empty_id_table_is_a_programming_error():
    with pytest.raises(ValueError, match="empty id table"):
        call(ScriptedChat([]), id_tables={"a_evidence[]": consideration_table([])})


# ---------------------------------------------------------------- bounded loop

def _tools():
    def get_consideration(args, ctx):
        return next(c["text"] for c in ctx["considerations"] if c["id"] == args["a_id"])

    def find_article(args, ctx):
        return f"{args['a_act']} {args['b_number']}"

    return [
        Tool("get_consideration", "Return the text of one consideration.",
             {"type": "object", "properties": {"a_id": {"type": "string"}}, "additionalProperties": False},
             handler=get_consideration),
        Tool("find_article", "Return the article of an act.",
             {"type": "object", "properties": {"a_act": {"type": "string", "enum": ["UVG", "ATSG"]},
                                               "b_number": {"type": "string"}}, "additionalProperties": False},
             handler=find_article),
    ]


def loop(chat, **kw):
    return run_tools(chat, _tools(), system="s", user="u", purpose="bench", prompt_version="t1", context=RULING,
                     id_tables={"get_consideration": {"a_id": consideration_table(RULING["considerations"])}}, **kw)


def step(*calls):
    return json.dumps({"a_calls": [{"a_tool": n, "b_args": a} for n, a in calls]})


def test_loop_batches_calls_dedupes_and_finishes():
    chat = ScriptedChat([step(("get_consideration", {"a_id": "E. 4.2"}),
                              ("find_article", {"a_act": "UVG", "b_number": "6"})),
                         step(("finish", {}))])
    out = loop(chat)
    assert out.status == "finished" and [c.tool for c in out.calls] == ["get_consideration", "find_article"]
    assert out.calls[0].args == {"a_id": "c2"} and "Integritätsschaden" in out.calls[0].result
    assert "<data id=" in chat.requests[1].messages[1]["content"]  # results are fed back as data


def test_loop_refuses_unknown_tools_and_bad_args_without_running_them():
    chat = ScriptedChat([step(("delete_all", {}), ("find_article", {"a_act": "LAA", "b_number": "6"})),
                         step(("finish", {}))])
    out = loop(chat)
    assert out.calls[0].error.startswith("unknown tool") and out.calls[1].error and out.calls[1].result is None


def test_loop_stops_on_repeated_calls_and_caps():
    same = step(("get_consideration", {"a_id": "c1"}))
    assert loop(ScriptedChat([same, same])).stop_reason == "only_repeated_calls"
    many = step(*[("find_article", {"a_act": "UVG", "b_number": str(i)}) for i in range(20)])
    out = loop(ScriptedChat([many]), max_calls=5)
    assert out.stop_reason == "max_calls" and len(out.calls) == 5


def test_loop_feedback_once_then_required_tools_run_by_code():
    chat = ScriptedChat([step(("finish", {})), step(("finish", {}))])
    out = loop(chat, required=[("get_consideration", {"a_id": "c3"})])
    assert out.feedback_rounds == 1 and "Not done yet" in chat.requests[1].messages[1]["content"]
    assert out.calls[-1].origin == "required" and out.calls[-1].result.startswith("Die Beschwerde wird")


def test_loop_invalid_step_fails():
    assert loop(ScriptedChat(["no json"])).status == "failed"
