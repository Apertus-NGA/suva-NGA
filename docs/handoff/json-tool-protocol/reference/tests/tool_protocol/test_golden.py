# SPDX-License-Identifier: Apache-2.0
"""Golden tests: stored raw replies -> expected parse status, repairs and validation verdict.

``golden/replies.jsonl`` holds **hand-written** replies that reproduce failure shapes reported by
other teams or listed in LESSONS (no ruling text, no Suva text: the file is safe for a public
repo). The expected verdicts were recorded from this code and reviewed by hand; they pin behaviour,
they are not independent ground truth. Add real
recorded replies from the benchmark with ``eval/tool_bench/run.py --export-golden`` after review
(public rulings only; D-031 for anything derived from Suva's data). A behaviour change shows up as a
golden diff and needs ``UPDATE_GOLDEN=1`` plus a reviewed PR.
"""
import json
import os
from pathlib import Path

import pytest

from llm.tool_protocol import consideration_table, parse_object, validate

from .contracts import JUSTIFY

GOLDEN = Path(__file__).parent / "golden" / "replies.jsonl"
TABLE = consideration_table([{"id": f"c{i}", "e_number": n} for i, n in enumerate(["1", "2", "3.1", "3.2", "4"], 1)])


def verdict(raw: str) -> dict:
    r = parse_object(raw)
    out = {"parse": r.status, "parse_repairs": list(r.repairs), "stripped": list(r.stripped)}
    if r.obj is not None:
        v = validate(r.obj, JUSTIFY.parameters, id_tables={"a_evidence[]": TABLE})
        out.update(valid=not v.fatal, codes=sorted({p.code for p in v.problems}), repairs=sorted(v.repairs),
                   evidence=v.obj.get("a_evidence") if v.obj else None)
    return out


CASES = [json.loads(line) for line in GOLDEN.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_golden(case):
    got = verdict(case["raw"])
    if os.environ.get("UPDATE_GOLDEN") == "1":
        case["expected"] = got
        return
    assert got == case["expected"], f"{case['id']}: {case['why']}"


def test_update_golden_writes_file():
    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in CASES), encoding="utf-8")
