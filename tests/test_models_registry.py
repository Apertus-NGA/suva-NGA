"""Every model id the code references is listed in MODELS.md (event rule E6; MODELS.md §1 runtime checks).

Scanned: src/, eval/, prompts/, Makefile, Dockerfile, docker-compose.yml, .env.example. Not scanned: tests/
(they use invented non-Apertus ids on purpose, to prove the served-model check rejects them, T25) and docs/.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = re.compile(
    r"(?<![\w/.-])("
    r"swiss-ai/[A-Za-z0-9._-]+"
    r"|apertus-v[0-9][A-Za-z0-9._-]*"
    r"|pplx-embed[A-Za-z0-9._-]*"
    r"|bge-m3[A-Za-z0-9._-]*"
    r"|(?:gpt|claude|gemini|llama|mistral|qwen)-[A-Za-z0-9._-]+"
    r"|[A-Za-z0-9-]+/[A-Za-z0-9._-]*(?:embed|bge(?![a-z])|e5-|gte-|llama|mistral|qwen|Apertus)[A-Za-z0-9._-]*"
    r")",
    re.I,
)


# Installed or built third-party files, not our code (src/web/node_modules, src/web/dist).
SKIPPED_DIRS = {"__pycache__", "node_modules", "dist"}


def scanned_files(root: Path = ROOT) -> list[Path]:
    files = [root / n for n in ("Makefile", "Dockerfile", "docker-compose.yml", ".env.example")]
    for d in ("src", "eval", "prompts"):
        if (root / d).is_dir():
            files += [p for p in (root / d).rglob("*") if p.is_file() and not SKIPPED_DIRS & set(p.parts)]
    return [f for f in files if f.is_file()]


def registered_ids(root: Path = ROOT) -> set[str]:
    text = (root / "MODELS.md").read_text(encoding="utf-8")
    return {t.lower() for t in re.findall(r"`([^`\s]+)`", text)}


def unregistered(files: list[Path], registered: set[str]) -> list[str]:
    hits = []
    for path in files:
        for m in MODEL_ID.finditer(path.read_text(encoding="utf-8", errors="ignore")):
            model = m.group(1).rstrip(".")
            if model.lower() not in registered:
                hits.append(f"{path.name}: {model}")
    return hits


def test_every_model_id_in_code_is_in_models_md():
    assert unregistered(scanned_files(), registered_ids()) == []


def test_check_goes_red_on_an_unlisted_model(tmp_path):
    f = tmp_path / "x.py"
    f.write_text('JUDGE = "apertus-v1-5-70b"\nEMB = "intfloat/multilingual-e5-large"\nX = "gpt-4o"\n')
    assert unregistered([f], registered_ids()) == ["x.py: intfloat/multilingual-e5-large", "x.py: gpt-4o"]


def test_bger_paths_are_not_model_ids_but_bge_models_are(tmp_path):
    """`bger` (Bundesgericht) in a data path or dataset name is not the `bge` embedding family."""
    f = tmp_path / "x.py"
    f.write_text(
        'A = "data/bger.parquet"\nB = "suva-nga/bger-rulings"\nC = "docs/CH_BGer"\n'
        'D = "BAAI/bge-reranker-v2"\nE = "BAAI/bge_small"\n'
    )
    assert unregistered([f], registered_ids()) == ["x.py: BAAI/bge-reranker-v2", "x.py: BAAI/bge_small"]
