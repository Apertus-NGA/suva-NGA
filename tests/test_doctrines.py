"""Doctrine tests: the golden rules that code can check (AGENTS.md G2, G3, G13; docs/agents/platform.md step 10)."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ("LLM_NAME", "LLM_BASE_URL", "LLM_API_KEY")
CODE_DIRS = ("src", "eval")


def code_files() -> list[Path]:
    return sorted(p for d in CODE_DIRS if (ROOT / d).is_dir() for p in (ROOT / d).rglob("*.py"))


def gateway_access_outside_llm(files: list[Path], root: Path = ROOT) -> list[str]:
    """G2: only src/llm/ may read the endpoint or the key, call /chat/completions or import an LLM SDK."""
    hits = []
    for path in files:
        if root / "src" / "llm" in path.parents:
            continue
        text = path.read_text(encoding="utf-8")
        for needle in ("LLM_BASE_URL", "LLM_API_KEY", "/chat/completions", "/v1/completions"):
            if needle in text:
                hits.append(f"{path.relative_to(root)}: {needle}")
        tree = ast.parse(text)
        for node in ast.walk(tree):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else []
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            hits += [
                f"{path.relative_to(root)}: imports {n}" for n in names if n.split(".")[0] in ("openai", "litellm")
            ]
    return hits


def env_defaults(files: list[Path], root: Path = ROOT) -> list[str]:
    """G3: no default value for the three imposed names (os.getenv / os.environ.get with a second argument)."""
    hits = []
    for path in files:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and len(node.args) >= 2 and isinstance(node.args[0], ast.Constant)):
                continue
            func = ast.unparse(node.func)
            if func in ("os.getenv", "os.environ.get", "getenv", "environ.get") and node.args[0].value in REQUIRED:
                hits.append(f"{path.relative_to(root)}:{node.lineno}: default for {node.args[0].value}")
    return hits


def test_g2_only_src_llm_reaches_the_gateway():
    assert gateway_access_outside_llm(code_files()) == []


def test_g2_check_goes_red_on_a_violation(tmp_path):
    (tmp_path / "src" / "llm").mkdir(parents=True)
    bad = tmp_path / "src" / "rogue.py"
    bad.write_text('import os, openai\nurl = os.environ["LLM_BASE_URL"] + "/chat/completions"\n')
    allowed = tmp_path / "src" / "llm" / "client.py"
    allowed.write_text('import os\nurl = os.environ["LLM_BASE_URL"]\n')
    assert gateway_access_outside_llm([bad, allowed], root=tmp_path) == [
        "src/rogue.py: LLM_BASE_URL",
        "src/rogue.py: /chat/completions",
        "src/rogue.py: imports openai",
    ]


def test_g3_no_default_for_imposed_llm_variables():
    assert env_defaults(code_files()) == []


def test_g3_env_default_check_goes_red(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text('import os\nname = os.getenv("LLM_NAME", "x")\nok = os.getenv("OTHER", "y")\n')
    assert env_defaults([bad], root=tmp_path) == ["bad.py:2: default for LLM_NAME"]


def test_g3_env_example_has_no_values():
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    for key in REQUIRED:
        assert f"{key}=" in lines, f".env.example must list {key} with no value"
    assert all(line.endswith("=") for line in lines if line and not line.startswith("#")), "no value in .env.example"


def test_no_network_at_import():
    """No module of src/ opens a connection when imported (platform rule: no network at import or start-up)."""
    modules = sorted(
        ".".join(p.relative_to(ROOT).with_suffix("").parts).removesuffix(".__init__")
        for p in (ROOT / "src").rglob("*.py")
    )
    code = (
        "import socket\n"
        "def _deny(*a, **k): raise RuntimeError('network call at import')\n"
        "socket.socket.connect = _deny\nsocket.create_connection = _deny\nsocket.getaddrinfo = _deny\n"
        "import importlib\n"
        f"for m in {modules!r}: importlib.import_module(m)\n"
        "print('ok')\n"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0 and out.stdout.strip() == "ok", out.stderr[-2000:]
