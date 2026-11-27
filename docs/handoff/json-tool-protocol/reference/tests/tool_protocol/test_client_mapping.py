# SPDX-License-Identifier: Apache-2.0
"""Contract of the client mapping (examples/chatfn_mapping.py): body shape and error classification.

In the repo these assertions move to the client's own tests (owner: platform), against
``src/llm/client.py``; they pin what the protocol expects from it. Skipped when ``examples/`` is not
on the path. No network.
"""
import io
import json
import urllib.error

import pytest

from llm.tool_protocol import ChatRequest, RequestRejected, Tier, TransportFailure, response_format, strict_profile

from .contracts import JUSTIFY

mapping = pytest.importorskip("examples.chatfn_mapping")
classify_400, from_body, to_body = mapping.classify_400, mapping.from_body, mapping.to_body


def req(**kw):
    base = dict(messages=({"role": "system", "content": "s"}, {"role": "user", "content": "u"}),
                response_format=response_format(Tier.STRICT, strict_profile(JUSTIFY.parameters), "justify"),
                max_tokens=400, purpose="triage_justify", prompt_version="v1")
    base.update(kw)
    return ChatRequest(**base)


def test_body_for_json_calls_has_no_tools_and_one_system_message():
    body = to_body(req(), "apertus-v1-5-70b")
    assert body["response_format"]["json_schema"]["strict"] is True and "tools" not in body
    assert [m["role"] for m in body["messages"]].count("system") == 1 and body["temperature"] == 0.0
    assert "chat_template_kwargs" not in body
    json.dumps(body)  # serialisable


def test_thinking_variant_gets_thinking_off():
    assert to_body(req(), "any-model-thinking")["chat_template_kwargs"] == {"enable_thinking": False}


def test_native_tools_are_passed_only_when_asked():
    tools = ({"type": "function", "function": {"name": "x", "parameters": {"type": "object", "properties": {}}}},)
    body = to_body(req(response_format=None, tools=tools, tool_choice={"type": "function", "function": {"name": "x"}}),
                   "m")
    assert body["tools"] == list(tools) and body["tool_choice"]["function"]["name"] == "x"
    assert "response_format" not in body


@pytest.mark.parametrize("detail, kind", [
    ('{"error": "response_format json_schema not supported"}', "response_format"),
    ("guided decoding backend failed to compile grammar", "response_format"),
    ("Conversation roles must alternate user/assistant", "message_roles"),
    ("Only one system message is allowed", "message_roles"),
    ("max_tokens must be positive", "other"),
])
def test_400_classification(detail, kind):
    assert classify_400(detail) == kind


def test_reply_mapping_keeps_served_model_and_tool_calls():
    call = {"id": "1", "type": "function", "function": {"name": "x", "arguments": "{}"}}
    body = {"model": "apertus-v1-5-70b",
            "choices": [{"finish_reason": "tool_calls", "message": {"content": None, "tool_calls": [call]}}]}
    r = from_body(body)
    assert r.served_model == "apertus-v1-5-70b" and r.finish_reason == "tool_calls" and len(r.tool_calls) == 1
    assert from_body({}).content is None


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _ok_body():
    return _Resp(json.dumps({"model": "m", "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]})
                 .encode())


def _http_error(code, headers=None, body=b"{}"):
    return urllib.error.HTTPError("https://gw.invalid/chat/completions", code, "x", headers or {}, io.BytesIO(body))


def _client(monkeypatch, script):
    calls, sleeps = [], []

    def fake_urlopen(request, timeout=None, context=None):
        calls.append(request)
        item = script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    monkeypatch.setenv("LLM_BASE_URL", "https://gw.invalid/api/v1")
    monkeypatch.setattr(mapping.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(mapping.time, "sleep", sleeps.append)
    return mapping.make_chat_fn("m", retries=2), calls, sleeps


def test_429_is_retried_honouring_retry_after(monkeypatch):
    chat, calls, sleeps = _client(monkeypatch, [_http_error(429, {"Retry-After": "7"}), _ok_body()])
    assert chat(req()).content == "{}" and len(calls) == 2 and sleeps == [7.0]


def test_http_error_is_classified_before_the_url_error_branch(monkeypatch):
    # HTTPError subclasses URLError: a 400 must become RequestRejected at once, never a retried network error.
    body = b'{"detail": "response_format json_schema not supported"}'
    chat, calls, sleeps = _client(monkeypatch, [_http_error(400, body=body), _ok_body()])
    with pytest.raises(RequestRejected) as e:
        chat(req())
    assert e.value.kind == "response_format" and len(calls) == 1 and sleeps == []


@pytest.mark.parametrize("code", [401, 403, 404])
def test_auth_and_missing_routes_are_never_retried(monkeypatch, code):
    chat, calls, _ = _client(monkeypatch, [_http_error(code), _ok_body()])
    with pytest.raises(TransportFailure):
        chat(req())
    assert len(calls) == 1


def test_network_errors_are_retried_then_raised(monkeypatch):
    chat, calls, sleeps = _client(monkeypatch, [urllib.error.URLError("down")] * 3)
    with pytest.raises(TransportFailure):
        chat(req())
    assert len(calls) == 3 and len(sleeps) == 2


def test_base_url_has_no_default_in_code(monkeypatch):
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="LLM_BASE_URL"):
        mapping.make_chat_fn("m")


def test_parallel_tool_calls_and_cache_salt():
    tools = ({"type": "function", "function": {"name": "t", "parameters": {"type": "object", "properties": {}}}},)
    body = to_body(req(response_format=None, tools=tools, parallel_tool_calls=True, cache_salt="rep1"), "m")
    assert body["parallel_tool_calls"] is True and "cache_salt" not in json.dumps(body)
