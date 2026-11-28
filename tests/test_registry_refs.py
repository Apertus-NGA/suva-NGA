"""Every registry version names the decision that approved it and the file that certifies it (F-12, D-064).

Step versions (src/*/registry/*.json) and profile versions (src/db/seed/profiles.json) are checked by the same
pydantic models the registry loader uses; each `decision` must be a D-NNN row of docs/DECISIONS.md; each
`validation` must be an existing expected file that certifies that very step and version.
"""

from __future__ import annotations

import json
import re

import pytest

from src.db.pg import ROOT
from src.db.registry import ProfileVersionEntry, StepVersionEntry, label

STEP_REGISTRIES = sorted(ROOT.glob("src/*/registry/*.json"))
PROFILES = ROOT / "src" / "db" / "seed" / "profiles.json"


def _decisions() -> set[str]:
    text = (ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
    return set(re.findall(r"^(?:\| |#{2,4} )(D-[0-9]{3})\b", text, flags=re.MULTILINE))


def test_the_registries_are_found():
    names = {p.name for p in STEP_REGISTRIES}
    assert {"ingest.json", "layer1_filter.json"} <= names


@pytest.mark.parametrize("path", STEP_REGISTRIES, ids=lambda p: p.name)
def test_every_step_version_names_its_decision_and_certified_file(path):
    reg = json.loads(path.read_text(encoding="utf-8"))
    decisions = _decisions()
    for raw in reg["versions"]:
        ver = StepVersionEntry.model_validate(raw)
        where = f"{path.name} {label(ver.version)}"
        assert ver.decision in decisions, f"{where}: {ver.decision} is not a row of docs/DECISIONS.md"
        if ver.validation is None:
            continue
        expected = ROOT / ver.validation
        assert expected.is_file(), f"{where}: {ver.validation} does not exist"
        certified = json.loads(expected.read_text(encoding="utf-8"))
        assert (certified["step"], certified["version"]) == (reg["step"], label(ver.version)), (
            f"{where}: {ver.validation} certifies {certified['step']} {certified['version']}"
        )


def test_every_profile_version_names_its_decision():
    decisions = _decisions()
    for prof in json.loads(PROFILES.read_text(encoding="utf-8"))["profiles"]:
        for raw in prof["versions"]:
            ver = ProfileVersionEntry.model_validate(raw)
            assert ver.decision in decisions, f"profile {prof['code']} {label(ver.version)}: {ver.decision} unknown"


def test_a_version_without_its_decision_or_with_a_stray_key_is_refused():
    raw = json.loads((ROOT / "src" / "ingest" / "registry" / "ingest.json").read_text(encoding="utf-8"))["versions"][0]
    for broken in (
        {k: v for k, v in raw.items() if k != "decision"},
        {k: v for k, v in raw.items() if k != "validation"},
        raw | {"decision": "D-73"},
        raw | {"validation": "results/x.json"},
        raw | {"decison": "D-073"},
    ):
        with pytest.raises(ValueError):
            StepVersionEntry.model_validate(broken)
