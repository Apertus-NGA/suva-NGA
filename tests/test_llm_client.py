"""The Apertus client (src/llm/client.py) and its configuration (G3, G4; docs/EVAL.md T25, T26).

MOCK DECLARED (G9): every test here replaces the gateway with `httpx.MockTransport`, a fake OpenAI-compatible
endpoint defined below. Assertions are on the request actually sent, on the stored `llm_calls` log and on the
replay cache, not on an HTTP status. The live behaviour is measured by `make smoke-llm` (results/gateway_probe.json).
"""

from __future__ import annotations

import json

import httpx
import pytest

from src.llm.client import InputRejected, LLMClient, LLMError, ReplayMiss, ServedModelError, classify_error
from src.llm.config import ConfigError, LLMConfig

GOOD_ENV = {"LLM_NAME": "apertus-v1-5-70b", "LLM_BASE_URL": "https://endpoint.invalid/v1", "LLM_API_KEY": "k"}
MSGS = [{"role": "system", "content": "s"}, {"role": "user", "content": "Ist die Beschwerde begründet?"}]


class FakeGateway:
    """A fake endpoint: answers from a queue of (status, body, headers); records every request."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(request.content))
        status, body, headers = self.answers.pop(0)
        return httpx.Response(status, json=body, headers=headers)


def ok(model="apertus-v1-5-70b", content="A", finish="stop", header=True):
    headers = {"x-keera-model": model} if header else {}
    body = {"model": model, "choices": [{"message": {"content": content}, "finish_reason": finish}], "usage": {}}
    return (200, body, headers)


def make(tmp_path, gateway, env=GOOD_ENV, mode="live"):
    cfg = LLMConfig.from_env(mode, env)
    return LLMClient(cfg, store_dir=tmp_path, transport=httpx.MockTransport(gateway), sleep=lambda s: None)


def logged(tmp_path):
    return [json.loads(line) for line in (tmp_path / "llm_calls.jsonl").read_text().splitlines()]


# --- configuration (G3, E1) -------------------------------------------------------------------------------


def test_live_mode_requires_the_three_names_without_default():
    with pytest.raises(ConfigError, match="LLM_API_KEY"):
        LLMConfig.from_env("live", {**GOOD_ENV, "LLM_API_KEY": ""})


def test_replay_mode_needs_no_llm_variables():
    cfg = LLMConfig.from_env("replay", {})
    assert cfg.name is None and cfg.api_key is None


def test_llm_name_must_name_apertus():
    with pytest.raises(ConfigError, match="E1"):
        LLMConfig.from_env("live", {**GOOD_ENV, "LLM_NAME": "gpt-4o"})


def test_concurrency_above_member_share_is_refused():
    with pytest.raises(ConfigError, match="D-030"):
        LLMConfig.from_env("live", {**GOOD_ENV, "LLM_CONCURRENCY": "8"})


def test_key_is_not_in_repr():
    assert "k'" not in repr(LLMConfig.from_env("live", GOOD_ENV))


# --- served model (G3; T25, T26) --------------------------------------------------------------------------


def test_t26_hugging_face_8b_id_without_header_is_accepted_and_logged(tmp_path):
    env = {**GOOD_ENV, "LLM_NAME": "swiss-ai/Apertus-v1.5-8B"}
    gw = FakeGateway(ok(model="swiss-ai/Apertus-v1.5-8B", header=False))
    result = make(tmp_path, gw, env).chat(MSGS, max_tokens=1, prompt_version="p0")
    assert result.content == "A" and result.mode == "LIVE"
    assert gw.requests[0]["model"] == "swiss-ai/Apertus-v1.5-8B"
    log = logged(tmp_path)[0]
    assert log["served"]["accepted"] and not log["served"]["header_present"]


def test_t25_another_allowed_apertus_id_is_accepted_and_counted(tmp_path):
    gw = FakeGateway(ok(model="swiss-ai/Apertus-v1.5-8B"))
    make(tmp_path, gw).chat(MSGS, max_tokens=1, prompt_version="p0")
    assert logged(tmp_path)[0]["served"]["mismatch"] is True


def test_t25_non_apertus_served_model_is_rejected_and_not_cached(tmp_path):
    gw = FakeGateway(ok(model="some-other-model"))
    with pytest.raises(ServedModelError):
        make(tmp_path, gw).chat(MSGS, max_tokens=1, prompt_version="p0")
    assert logged(tmp_path)[0]["error"] == "served_model_rejected"
    assert not (tmp_path / "cache").exists()


# --- the request actually sent (G3) ----------------------------------------------------------------------


def test_request_is_t0_one_system_message_and_thinking_off_for_thinking_models(tmp_path):
    env = {**GOOD_ENV, "LLM_NAME": "apertus-v1-5-70b-thinking"}
    gw = FakeGateway(ok(model="apertus-v1-5-70b-thinking", content="<|inner_prefix|>hmm<|inner_suffix|>B"))
    result = make(tmp_path, gw, env).chat(MSGS, max_tokens=5, prompt_version="p0")
    sent = gw.requests[0]
    assert sent["temperature"] == 0 and sent["max_tokens"] == 5
    assert [m["role"] for m in sent["messages"]].count("system") == 1
    assert sent["chat_template_kwargs"] == {"enable_thinking": False}
    assert result.content == "B"  # the thinking block is stripped


def test_no_thinking_kwargs_for_plain_models(tmp_path):
    gw = FakeGateway(ok())
    make(tmp_path, gw).chat(MSGS, max_tokens=1, prompt_version="p0")
    assert "chat_template_kwargs" not in gw.requests[0]


# --- input hygiene (G4): refused before any call ---------------------------------------------------------


@pytest.mark.parametrize(
    "messages",
    [
        [{"role": "system", "content": "a"}, {"role": "system", "content": "b"}, {"role": "user", "content": "x"}],
        [{"role": "system", "content": "s"}, {"role": "user", "content": "   "}],
        [{"role": "system", "content": "s"}, {"role": "user", "content": "<text>"}],
        [{"role": "system", "content": "s"}],
    ],
)
def test_bad_input_is_refused_before_the_call(tmp_path, messages):
    gw = FakeGateway()
    with pytest.raises(InputRejected):
        make(tmp_path, gw).chat(messages, max_tokens=1, prompt_version="p0")
    assert gw.requests == []


def test_input_over_budget_is_refused(tmp_path):
    gw = FakeGateway()
    client = make(tmp_path, gw, {**GOOD_ENV, "LLM_MAX_INPUT_TOKENS": "100"})
    with pytest.raises(InputRejected, match="never truncate"):
        client.chat([{"role": "user", "content": "x" * 400}], max_tokens=1, prompt_version="p0")
    assert gw.requests == []


# --- failures and retries --------------------------------------------------------------------------------


def test_length_cut_is_a_failure_never_parsed_nor_cached(tmp_path):
    gw = FakeGateway(ok(finish="length"))
    with pytest.raises(LLMError) as err:
        make(tmp_path, gw).chat(MSGS, max_tokens=1, prompt_version="p0")
    assert err.value.kind == "length"
    assert not (tmp_path / "cache").exists()


def test_429_is_retried_then_succeeds(tmp_path):
    gw = FakeGateway((429, {"error": "slow down"}, {"retry-after": "1"}), ok())
    result = make(tmp_path, gw).chat(MSGS, max_tokens=1, prompt_version="p0")
    assert result.attempts == 2 and len(gw.requests) == 2
    assert [r.get("error") for r in logged(tmp_path)] == ["rate", None]


def test_401_is_never_retried(tmp_path):
    gw = FakeGateway((401, {"error": "bad key"}, {}), ok())
    with pytest.raises(LLMError) as err:
        make(tmp_path, gw).chat(MSGS, max_tokens=1, prompt_version="p0")
    assert err.value.kind == "auth" and len(gw.requests) == 1


def test_classify_error():
    assert classify_error(400, "response_format json_schema not supported") == "json_format_unsupported"
    assert classify_error(504) == "server" and classify_error(404) == "not_found"
    assert classify_error(None, exc=httpx.ReadTimeout("t")) == "timeout"


# --- replay (D-032) --------------------------------------------------------------------------------------


def test_replay_returns_the_cached_answer_labelled_replay_without_any_call(tmp_path):
    make(tmp_path, FakeGateway(ok(content="A"))).chat(MSGS, max_tokens=1, prompt_version="p0")
    gw = FakeGateway()
    replayed = make(tmp_path, gw, env={}, mode="replay").chat(MSGS, max_tokens=1, prompt_version="p0")
    assert replayed.content == "A" and replayed.mode == "REPLAY" and gw.requests == []


def test_replay_miss_is_an_error_not_a_negative(tmp_path):
    with pytest.raises(ReplayMiss):
        make(tmp_path, FakeGateway(), env={}, mode="replay").chat(MSGS, max_tokens=1, prompt_version="p1")


def test_cache_key_changes_with_prompt_version_and_repetition(tmp_path):
    gw = FakeGateway(ok(), ok(), ok())
    client = make(tmp_path, gw)
    keys = {
        client.chat(MSGS, max_tokens=1, prompt_version="p0").cache_key,
        client.chat(MSGS, max_tokens=1, prompt_version="p1").cache_key,
        client.chat(MSGS, max_tokens=1, prompt_version="p0", repetition=1).cache_key,
    }
    assert len(keys) == 3 and len(gw.requests) == 3


def test_replay_with_the_other_id_form_hits_the_same_answers(tmp_path):
    make(tmp_path, FakeGateway(ok(content="A"))).chat(MSGS, max_tokens=1, prompt_version="p0")
    env = {"LLM_NAME": "swiss-ai/Apertus-v1.5-70B"}
    replayed = make(tmp_path, FakeGateway(), env=env, mode="replay").chat(MSGS, max_tokens=1, prompt_version="p0")
    assert replayed.content == "A"


def test_live_never_reuses_answers_of_another_model(tmp_path):
    make(tmp_path, FakeGateway(ok(content="A"))).chat(MSGS, max_tokens=1, prompt_version="p0")
    gw = FakeGateway(ok(model="apertus-v1-5-8b", content="B"))
    env = {**GOOD_ENV, "LLM_NAME": "apertus-v1-5-8b"}
    assert make(tmp_path, gw, env).chat(MSGS, max_tokens=1, prompt_version="p0").content == "B"


def test_first_token_label_call_accepts_the_designed_length_cut(tmp_path):
    lp = {"content": [{"token": "Ja", "logprob": -0.01, "top_logprobs": [{"token": "Ja", "logprob": -0.01}]}]}
    status, body, headers = ok(content="Ja", finish="length")
    body["choices"][0]["logprobs"] = lp
    gw = FakeGateway((status, body, headers))
    r = make(tmp_path, gw).chat(
        MSGS, max_tokens=1, prompt_version="p0", logprobs=True, top_logprobs=20, first_token_only=True
    )
    assert r.logprobs == lp and gw.requests[0]["top_logprobs"] == 20
    with pytest.raises(InputRejected):  # only for real label calls
        make(tmp_path, FakeGateway()).chat(MSGS, max_tokens=50, prompt_version="p0", first_token_only=True)


# --- trace and observer (docs/LAYER2_IMPLEMENTATION_PLANNING.md L2-D09) --------------------------------------


def test_observer_sees_every_attempt_with_its_trace_and_the_key_ignores_the_trace(tmp_path):
    seen = []
    gw = FakeGateway((429, {"error": "slow down"}, {"retry-after": "1"}), ok())
    client = make(tmp_path, gw)
    client.observer = seen.append
    trace = {"run_id": "r1", "ruling_id": "x1", "step": "layer2_judge", "repetition": 0}
    result = client.chat(MSGS, max_tokens=1, prompt_version="p0", trace=trace)
    assert [r["error"] for r in seen] == ["rate", None] and all(r["trace"] == trace for r in seen)
    assert all(r["endpoint"] == "/chat/completions" and r["cache_hit"] is False for r in seen)
    assert (
        seen[-1]["cache_key"]
        == result.cache_key
        == make(tmp_path, FakeGateway()).chat(MSGS, max_tokens=1, prompt_version="p0").cache_key
    )  # same key without a trace: answered from the cache


def test_a_cache_hit_is_logged_and_observed_as_replay(tmp_path):
    make(tmp_path, FakeGateway(ok(content="A"))).chat(MSGS, max_tokens=1, prompt_version="p0")
    seen = []
    client = make(tmp_path, FakeGateway(), env={}, mode="replay")
    client.observer = seen.append
    client.chat(MSGS, max_tokens=1, prompt_version="p0", trace={"ruling_id": "x2"})
    assert len(seen) == 1 and seen[0]["cache_hit"] is True and seen[0]["mode"] == "REPLAY"
    assert seen[0]["content"] == "A" and seen[0]["attempt"] == 1 and seen[0]["trace"] == {"ruling_id": "x2"}
    assert logged(tmp_path)[-1]["cache_hit"] is True
    assert "Authorization" not in json.dumps(seen[0]) and "api_key" not in json.dumps(seen[0])


def test_a_base_url_without_scheme_fails_at_startup():
    with pytest.raises(ConfigError, match="https://"):
        LLMConfig.from_env("live", {**GOOD_ENV, "LLM_BASE_URL": "REMPLACE_PAR_TON_ENDPOINT"})


# --- the shipped answers: a committed, read-only store a fresh clone replays from ---------------------------


def _answer_once(store, content="A"):
    """One live call against the fake gateway, cached in `store`. Returns the result."""
    client = make(store, FakeGateway(ok(content=content)))
    return client.chat(MSGS, max_tokens=5, prompt_version="p1")


def test_replay_falls_back_to_the_shipped_answers_when_the_local_store_has_none(tmp_path):
    shipped, local = tmp_path / "shipped", tmp_path / "local"
    _answer_once(shipped, "aus dem Lieferumfang")
    client = LLMClient(LLMConfig.from_env("replay", GOOD_ENV), store_dir=local, shipped_dir=shipped)
    result = client.chat(MSGS, max_tokens=5, prompt_version="p1")
    assert (result.content, result.mode) == ("aus dem Lieferumfang", "REPLAY")
    assert not (local / "cache").exists()  # reading the shipped store writes nothing


def test_the_local_answer_wins_over_the_shipped_one_and_live_never_writes_the_shipped_store(tmp_path):
    shipped, local = tmp_path / "shipped", tmp_path / "local"
    _answer_once(shipped, "alt")
    before = sorted(p.name for p in shipped.rglob("*") if p.is_file())
    _answer_once(local, "neu")
    gateway = FakeGateway(ok(content="frisch"))
    live = LLMClient(
        LLMConfig.from_env("live", GOOD_ENV), store_dir=local, shipped_dir=shipped,
        transport=httpx.MockTransport(gateway), sleep=lambda s: None,
    )  # fmt: skip
    assert live.chat(MSGS, max_tokens=5, prompt_version="p1").content == "neu"
    assert live.chat(MSGS, max_tokens=5, prompt_version="p2").content == "frisch"  # not cached anywhere: one call
    assert len(gateway.requests) == 1
    assert sorted(p.name for p in shipped.rglob("*") if p.is_file()) == before


def test_replay_without_llm_name_takes_the_model_from_the_shipped_store(tmp_path):
    shipped = tmp_path / "shipped"
    _answer_once(shipped)
    client = LLMClient(LLMConfig.from_env("replay", {}), store_dir=tmp_path / "local", shipped_dir=shipped)
    assert client.chat(MSGS, max_tokens=5, prompt_version="p1").content == "A"


def test_export_ships_only_the_answers_a_run_used(tmp_path):
    from src.llm.client import export_answers

    local, dest = tmp_path / "local", tmp_path / "dest"
    writer = make(local, FakeGateway(ok(content="gebraucht"), ok(content="nicht gebraucht")))
    used = writer.chat(MSGS, max_tokens=5, prompt_version="p1")
    writer.chat(MSGS, max_tokens=5, prompt_version="other")
    run = LLMClient(LLMConfig.from_env("replay", GOOD_ENV), store_dir=local)
    run.chat(MSGS, max_tokens=5, prompt_version="p1")
    assert export_answers(dest, client=run) == 1
    assert [p.stem for p in (dest / "cache").rglob("*.json")] == [used.cache_key]
    assert json.loads((dest / "replay_models.json").read_text()) == {"large": "apertus-v1-5-70b"}
    fresh = LLMClient(LLMConfig.from_env("replay", {}), store_dir=tmp_path / "empty", shipped_dir=dest)
    assert fresh.chat(MSGS, max_tokens=5, prompt_version="p1").content == "gebraucht"
    with pytest.raises(ReplayMiss):
        fresh.chat(MSGS, max_tokens=5, prompt_version="other")
