"""Tests of experiments/finetune/scripts/06_benchmark_repeat.py on 3 real rulings (one DE, one FR, one IT).

MOCK DECLARED (G9): the Keera gateway is replaced by `httpx.MockTransport`, a fake OpenAI-compatible endpoint
that records every request and answers with canned first-token log-probabilities. The real src/llm/ client runs
on top of it (served-model check, retries, cache, llm_calls log). The assertions bear on the request actually sent
and on the stored file. Skipped without the git-ignored data in data/derived/finetune/.
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
_spec = importlib.util.spec_from_file_location("bench06", ROOT / "experiments/finetune/scripts/06_benchmark_repeat.py")
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)

from src.llm.client import LLMClient, LLMError  # noqa: E402
from src.llm.config import LLMConfig  # noqa: E402

TEST_A = ROOT / "data/derived/finetune/suva-ft-v3/fold_A/test.jsonl"
pytestmark = pytest.mark.skipif(not TEST_A.is_file(), reason="data/derived/finetune/ absent (git-ignored, D-031)")

TOP = [{"token": "Ja", "logprob": -0.1}, {"token": " Nein", "logprob": -2.4}, {"token": "ja", "logprob": -5.0},
       {"token": "Das", "logprob": -7.0}]


@pytest.fixture
def three_rulings():
    rows = [json.loads(line) for line in TEST_A.open(encoding="utf-8")]
    picked = []
    for lang in ("de", "fr", "it"):
        picked.append(next(r for r in rows if r["meta"]["lang"] == lang))
    return picked


def _gateway(log: list, top=TOP, status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        log.append({"url": str(request.url), "body": body})
        if status != 200:
            return httpx.Response(status, text="mock failure")
        return httpx.Response(200, headers={"x-keera-model": body["model"]}, json={
            "model": body["model"],
            "choices": [{"message": {"role": "assistant", "content": "Ja"}, "finish_reason": "length",
                         "logprobs": {"content": [{"token": "Ja", "logprob": -0.1, "top_logprobs": top}]}}],
            "usage": {"prompt_tokens": 4321, "completion_tokens": 1},
        })
    return handler


def _client(tmp_path, handler) -> LLMClient:
    cfg = LLMConfig(mode="live", name="apertus-v1-5-70b", name_small="apertus-v1-5-8b",
                    base_url="https://gateway.invalid/api/v1", api_key="test-key")
    return LLMClient(cfg, store_dir=tmp_path / "store", transport=httpx.MockTransport(handler), sleep=lambda s: None)


def test_run_rep_sends_the_dataset_prompt_and_stores_logprobs(tmp_path, three_rulings):
    log: list = []
    client = _client(tmp_path, _gateway(log))
    out = tmp_path / "rep000.jsonl"
    meta = B.run_rep(client, "small", three_rulings, repetition=7, workers=2, path=out)
    rows = [json.loads(line) for line in out.open(encoding="utf-8")]
    assert [r["decision_id"] for r in rows] == [r["meta"]["decision_id"] for r in three_rulings]
    assert {r["lang"] for r in rows} == {"de", "fr", "it"}
    p_ja, p_nein = math.exp(-0.1) + math.exp(-5.0), math.exp(-2.4)
    for r in rows:
        assert r["score"] == pytest.approx(p_ja / (p_ja + p_nein))
        assert r["logprob_ja"] == pytest.approx(math.log(p_ja))
        assert r["logprob_nein"] == pytest.approx(-2.4)
        assert r["logit"] == pytest.approx(math.log(p_ja) + 2.4)
        assert r["top20"][0] == ["Ja", -0.1] and r["top20_floor"] == -7.0
        assert r["served_model"] == "apertus-v1-5-8b" and r["mode"] == "LIVE" and r["repetition"] == 7
        assert r["prompt_tokens"] == 4321
    sent = sorted((c["body"] for c in log), key=lambda b: b["messages"][1]["content"])
    want = sorted((r["prompt"] for r in three_rulings), key=lambda m: m[1]["content"])
    assert [b["messages"] for b in sent] == want  # the dataset's messages, unchanged
    for b in sent:
        assert (b["model"], b["max_tokens"], b["temperature"], b["logprobs"], b["top_logprobs"]) == (
            "apertus-v1-5-8b", 1, 0, True, 20)
    assert all(c["url"].endswith("/chat/completions") for c in log)
    assert meta["n"] == 3 and meta["n_live"] == 3 and meta["prompt_tokens"] == 3 * 4321
    assert json.loads(out.with_suffix(".meta.json").read_text())["served_models"] == ["apertus-v1-5-8b"]
    calls_log = (tmp_path / "store" / "llm_calls.jsonl").read_text().splitlines()
    assert len(calls_log) == 3 and "test-key" not in "".join(calls_log)

    # same repetition again: answered from the cache, no new request; another repetition: a fresh call
    B.run_rep(client, "small", three_rulings, repetition=7, workers=2, path=tmp_path / "again.jsonl")
    assert len(log) == 3
    again = [json.loads(line) for line in (tmp_path / "again.jsonl").open()]
    assert {r["mode"] for r in again} == {"REPLAY"} and [r["score"] for r in again] == [r["score"] for r in rows]
    B.run_rep(client, "small", three_rulings[:1], repetition=8, workers=1, path=tmp_path / "rep8.jsonl")
    assert len(log) == 4


def test_no_ja_nein_in_top20_fails_the_run(tmp_path, three_rulings):
    client = _client(tmp_path, _gateway([], top=[{"token": "Das", "logprob": -0.2}]))
    out = tmp_path / "rep000.jsonl"
    with pytest.raises(B.ScoreError):
        B.run_rep(client, "large", three_rulings, repetition=0, workers=2, path=out)
    assert not out.exists() and not out.with_suffix(".part").exists()


def test_gateway_failure_fails_the_run_after_retries(tmp_path, three_rulings):
    log: list = []
    client = _client(tmp_path, _gateway(log, status=503))
    out = tmp_path / "rep000.jsonl"
    with pytest.raises(LLMError):
        B.run_rep(client, "large", three_rulings[:1], repetition=0, workers=1, path=out)
    assert len(log) == 4  # MAX_ATTEMPTS in src/llm/client.py, then the run stops
    assert not out.exists()
