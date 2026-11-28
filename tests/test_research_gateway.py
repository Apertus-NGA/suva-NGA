"""G2 for research/: the experiments reach the gateway only through src/llm/ (AGENTS.md G2, G3).

Same check as tests/test_doctrines.py (its helpers are imported, not copied), applied to `research/`, which
that test does not scan. No network call.

MOCK DECLARED (G9): `monkeypatch` points research/apertus.py's read-only legacy cache at an empty temporary
path, so the refusal test cannot be answered by a teammate's local cache. Nothing else is faked.
"""

from __future__ import annotations

import ast
import importlib.util

import pytest

from tests.test_doctrines import ROOT, env_defaults, gateway_access_outside_llm

RESEARCH = ROOT / "research"


def research_files():
    return sorted(p for p in RESEARCH.rglob("*.py") if "cache" not in p.parts and "out" not in p.parts)


def test_g2_research_reaches_the_gateway_only_through_src_llm():
    assert research_files(), "research/ has no Python file: the scan would prove nothing"
    assert gateway_access_outside_llm(research_files()) == []


def test_g3_research_sets_no_default_for_the_imposed_variables():
    assert env_defaults(research_files()) == []


def test_research_client_imports_the_shared_client_and_no_http_library():
    tree = ast.parse((RESEARCH / "apertus.py").read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(a.name for a in node.names)
    assert "src.llm.client" in modules
    assert not {m for m in modules if m.split(".")[0] in ("urllib", "httpx", "requests", "http", "aiohttp")}


def _research_client():
    spec = importlib.util.spec_from_file_location("research_apertus", RESEARCH / "apertus.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "params",
    [
        {"model": "apertus-v1-5-70b-thinking", "max_tokens": 10},
        {"model": "apertus-v1-5-70b", "max_tokens": 10, "temperature": 0.6, "top_p": 0.95},
        {"model": "apertus-v1-5-70b", "max_tokens": 10, "continue_final_message": True},
    ],
)
def test_research_refuses_what_the_shared_client_refuses(monkeypatch, tmp_path, params):
    research = _research_client()
    monkeypatch.setattr(research, "LEGACY_DB", tmp_path / "absent.sqlite")
    with pytest.raises(research.ResearchRefused):
        research.chat(messages=[{"role": "user", "content": "Ist dieses Urteil relevant?"}], **params)
