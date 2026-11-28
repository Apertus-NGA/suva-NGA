"""The Qwen router probe stays off the Apertus gateway and does not call the network at import."""

import pytest

from src.qwen_comparison.__main__ import DEFAULT_TASKS, MODEL, URL, main


def test_router_target_is_not_the_gateway():
    assert URL == "https://router.huggingface.co/v1/chat/completions"
    assert MODEL == "Qwen/Qwen3.8-27B"
    assert DEFAULT_TASKS.name == "tasks.json"
    assert "qwen_probe" in DEFAULT_TASKS.parts


def test_main_stops_without_a_token(monkeypatch):
    monkeypatch.delenv("HF_INFERENCE_TOKEN", raising=False)
    with pytest.raises(SystemExit, match="HF_INFERENCE_TOKEN"):
        main()
