"""T31, the D-051 output test: no file we write holds an author field, staff code or intranet link of judgements/.

The forbidden values are read from judgements/ at test time (tests/suva_forbidden.py), kept in memory and
written nowhere; a failure names the file, the line and the kind of match, never the value.
Scanned: every file of the repo except judgements/ itself, the pitch PDF (Suva's), git internals, virtual
environments, tool caches and tmp/ (scratch). That covers data/derived/, data/public/, results/, expected/,
logs, llm_calls, caches, prompts, exports, UI pages, docs and the report. Limit: text inside compressed PDF
streams (the report PDF) is not read; check the report's Markdown source instead.
"""

from __future__ import annotations

from pathlib import Path

from tests.suva_forbidden import Forbidden, load, scan

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "judgements", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache",
             ".mypy_cache", ".cache", "tmp"}  # fmt: skip
SKIP_FILES = {"28112026 HackApertus – Challenge Pitch.pdf"}
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2"}


def generated_files() -> list[Path]:
    out = []
    for path in ROOT.rglob("*"):
        rel = path.relative_to(ROOT)
        if not path.is_file() or set(rel.parts) & SKIP_DIRS or path.name in SKIP_FILES:
            continue
        if path.suffix.lower() in SKIP_SUFFIXES or path.name.startswith("~$"):
            continue
        out.append(path)
    return out


def test_forbidden_values_were_found():
    """Guards against a vacuous pass: if parsing breaks, the forbidden set would be empty."""
    f = load(ROOT / "judgements")
    assert f.exports_with_author == 55
    assert f.author_lines and f.name_pairs and f.staff_codes
    assert f.intranet_hosts and f.intranet_prefixes


def test_no_generated_file_contains_a_d051_value():
    hits = scan(generated_files(), load(ROOT / "judgements"), ROOT)
    assert not hits, "D-051 values found (file:line: kind):\n" + "\n".join(hits)


def test_scanner_goes_red_on_a_planted_synthetic_value(tmp_path):
    """Self-test with invented values only (no real value is ever written)."""
    fake = Forbidden(
        author_lines={"Muster Hans (MUH), Jurist"},
        name_pairs={"Muster Hans", "Hans Muster"},
        staff_codes={"MUH"},
        intranet_hosts={"intra.example.invalid"},
        intranet_prefixes={"/sites/team/pages"},
    )
    planted = tmp_path / "out.jsonl"
    planted.write_text(
        "clean line\n"
        "von Hans  Muster verfasst\n"  # name pair, other order, extra space
        "Kürzel MUH.\n"  # standalone staff code
        "see https://INTRA.example.invalid/sites/team/pages/x\n"  # host (any case) and prefix
        "MUHAMMAD and hans muster are not matches\n",  # longer token, wrong case
        encoding="utf-8",
    )
    hits = scan([planted], fake, tmp_path)
    assert hits == [
        "out.jsonl:2: author name pair",
        "out.jsonl:3: staff code",
        "out.jsonl:4: intranet host",
        "out.jsonl:4: intranet path prefix",
    ]
    assert all("Muster" not in h and "MUH" not in h for h in hits)
