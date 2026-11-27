"""T28: the template's layout and Suva's files are intact (D-039, D-040, D-044, D-045; docs/EVAL.md T28).

Hashes recorded from the template at commit c6e50ba (docs/STATE.md §1-2, docs/SUVA_DATA.md §1). If the
organisers change a template file, copy their change exactly and update these hashes in the same PR (Q-26).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PITCH_PDF = "28112026 HackApertus – Challenge Pitch.pdf"
TEMPLATE_FILES = [
    "README.md",
    "challenge_description.md",
    "technical_report.md",
    "LICENSE",
    ".gitignore",
    "src/.gitkeep",
    "judgements/BG_Urteile_2025_Q4_2026_Q1.xlsx",
    "judgements/read.me",
    "judgements/test.txt",
    PITCH_PDF,
]
JUDGEMENTS_MANIFEST = "aee087543de78a7f81b29f1489497fec054acb053f19091c5365901327a548e0"
FILE_HASHES = {
    PITCH_PDF: "1ed75386da205c33dc54fc3c09020fe955e77656623a541e3bad1ea16f047cef",
    "challenge_description.md": "efdd0232848ed109da403b5deb3025064a3d4950f0f86f7792751990b39ea96b",
    "judgements/BG_Urteile_2025_Q4_2026_Q1.xlsx": "f7146cfd9e8419cd0801d30972d1220d8502b0b1a134364265eababe6bd1e86d",
}
GITIGNORE_TEMPLATE = (273, "a22b6846ce7aa70835e813846ee73bd887b8fec159f42299097aa33645685ef1")  # bytes, SHA-256
LICENSE_TEMPLATE = "3266fb7d3671008bdd9a543710e8cc7317e595513976f28ec9fbfd2e16d98944"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def manifest(folder: Path) -> str:
    """`cd judgements && sha256sum * | LC_ALL=C sort -k2 | sha256sum`, in Python.

    Like the shell glob `*`, hidden files (.DS_Store) are skipped; Office lock files (~$*), created while
    someone has the workbook open, are skipped too: they are local and git-ignored.
    """
    names = sorted(
        (p.name for p in folder.iterdir() if p.is_file() and not p.name.startswith((".", "~$"))),
        key=lambda n: n.encode("utf-8"),
    )
    lines = "".join(f"{sha256((folder / n).read_bytes())}  {n}\n" for n in names)
    return sha256(lines.encode("utf-8"))


@pytest.mark.parametrize("path", TEMPLATE_FILES)
def test_template_file_at_its_path(path):
    assert (ROOT / path).is_file(), f"template file missing or moved: {path} (D-039)"


def test_judgements_manifest_unchanged():
    folder = ROOT / "judgements"
    assert len(list(folder.glob("Export_*.html"))) == 55
    assert manifest(folder) == JUDGEMENTS_MANIFEST, "judgements/ changed: never edit it (D-040)"


@pytest.mark.parametrize("path", sorted(FILE_HASHES))
def test_suva_and_organiser_files_unchanged(path):
    assert sha256((ROOT / path).read_bytes()) == FILE_HASHES[path], f"{path} changed: never edit it (D-040, D-044)"


def test_gitignore_only_appended():
    size, digest = GITIGNORE_TEMPLATE
    data = (ROOT / ".gitignore").read_bytes()
    assert sha256(data[:size]) == digest, ".gitignore: the template's lines must stay first and unchanged (D-044)"


def test_license_only_copyright_line_changes():
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    normalised = re.sub(r"(?m)^(\s*)Copyright 2026 .*$", r"\1Copyright 2026 Your Team", text)
    assert sha256(normalised.encode("utf-8")) == LICENSE_TEMPLATE, "LICENSE: only the copyright line may change"
    assert "Copyright 2026" in text


def test_manifest_function_ignores_lock_and_hidden_files(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    before = manifest(tmp_path)
    (tmp_path / "~$a.xlsx").write_text("lock")
    (tmp_path / ".DS_Store").write_text("x")
    assert manifest(tmp_path) == before
    (tmp_path / "a.txt").write_text("b")  # a real change turns the test red
    assert manifest(tmp_path) != before
