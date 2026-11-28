"""The frozen reference of layer 1 (L2-F21, D-073): `src/layer1/reference_courts_4c246a8.py` is a byte-identical copy
of `git show 4c246a8:src/courts.py`, the code `layer1_filter` V1.0.0 reproduces decision for decision.

Layer 1 measures parity, and builds its `layer1-log-1` JSON, against this copy, never against the live
`src/courts.py`: that file belongs to its owner and keeps evolving (PR #42 rewrites it), while the certified versions
must not move with it. The copy is never edited (ruff accepts it as is); a new reference is a new file.
"""

from __future__ import annotations

import ast
import hashlib
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "src" / "layer1" / "reference_courts_4c246a8.py"
COMMIT, SOURCE = "4c246a8", "src/courts.py"
# SHA-256 of the blob `git show 4c246a8:src/courts.py` (git object d31ebd9e373337f670065ffd01977a7ffe4a4e92).
REFERENCE_SHA256 = "41cc56b7458ae59800766618dde01367336400fa816e84fcba30a9d3513a2000"


def test_the_vendored_reference_is_the_certified_blob():
    """Any edit of the copy, even a reformat, changes its SHA-256: a different reference is a new file and version."""
    assert hashlib.sha256(REFERENCE.read_bytes()).hexdigest() == REFERENCE_SHA256


def _git_blob() -> bytes | None:
    """`git show 4c246a8:src/courts.py`, or None when the history is not available (shallow clone, no git)."""
    try:
        found = subprocess.run(
            ["git", "-C", str(ROOT), "cat-file", "-e", f"{COMMIT}^{{commit}}"], capture_output=True, timeout=30
        )
        if found.returncode != 0:
            return None
        shown = subprocess.run(["git", "-C", str(ROOT), "show", f"{COMMIT}:{SOURCE}"], capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return shown.stdout if shown.returncode == 0 else None


def test_the_vendored_reference_equals_the_commit_when_history_is_available():
    blob = _git_blob()
    if blob is None:
        pytest.skip(f"git history without {COMMIT} (shallow clone or no git): the SHA-256 constant still pins the copy")
    assert hashlib.sha256(blob).hexdigest() == REFERENCE_SHA256
    assert REFERENCE.read_bytes() == blob


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names |= {f"{node.module}.{alias.name}" for alias in node.names}
    return names


def test_no_layer1_module_imports_the_live_courts_module():
    """Layer 1 is independent of the evolution of src/courts.py: no module of src/layer1/ imports it."""
    offenders = sorted(
        str(path.relative_to(ROOT))
        for path in (ROOT / "src" / "layer1").rglob("*.py")
        if {"src.courts", "courts"} & _imports(path)
    )
    assert offenders == []


def test_the_run_measures_parity_against_the_vendored_reference():
    from src.layer1 import reference_courts_4c246a8, run

    assert run.reference is reference_courts_4c246a8
    assert Path(reference_courts_4c246a8.__file__).resolve() == REFERENCE
    assert run.REFERENCE_PATH == "src/layer1/reference_courts_4c246a8.py"
    assert run.REFERENCE_PATH in run.CODE_PATHS  # the run records the reference among the code it executed (F-09)
