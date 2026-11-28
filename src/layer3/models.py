"""Configuration models of the layer-3 steps (segment, summarise, verify) and of the suva_house preset (D-064).

Each registry file (src/layer3/registry/*.json) is validated by one of these models when the registry loader writes
it (src/ingest/__main__.py); a stored version is immutable, any change is a new version. The shared check codes are
the same list for the engine (Sentence.checks) and the writer (one verify rule per code, rule_code V3_<CODE>).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_ROOT = Path(__file__).resolve().parents[2]
# The engine's import closure (src/summarize/engine.py and every module it loads, with the data file v2 reads): where
# every summary prompt lives. Its prompts are not in ops.prompt_version, so this hash is their identity (F-09): the
# summarise version's code_sha256 (src/ingest/__main__.py) and each run's (src/layer3/run.py). A test checks that
# every module the engine loads is covered (tests/test_layer3_unit.py).
ENGINE_CODE_GLOBS: tuple[str, ...] = (
    "src/areas.py",
    "src/summarize/__init__.py",
    "src/summarize/engine.py",
    "src/summarize/examples.py",
    "src/summarize/finish.py",
    "src/summarize/prompts.py",
    "src/summarize/summarize.py",
    "src/summarize/v2/*.py",
    "src/summarize/v2/glossary.json",
    "src/summarize/v3/*.py",
    "src/summarize/refine/**/*.py",
    "src/summarize/extract/*.py",
)


def engine_code_paths(root: Path = _ROOT) -> tuple[str, ...]:
    """The repo-relative files of the engine's import closure that exist, sorted (see ENGINE_CODE_GLOBS)."""
    found = {p.relative_to(root).as_posix() for pattern in ENGINE_CODE_GLOBS for p in root.glob(pattern) if p.is_file()}
    return tuple(sorted(found))


# The verification codes the engine fills in Sentence.checks (src/summarize/engine_types.py), in rule order.
CHECK_CODES: tuple[str, ...] = (
    "language",
    "placeholder",
    "new_identifier",
    "modal_strength",
    "glossary_term",
    "suva_named",
    "outcome_restated",
    "speaker",
    "entailment",
    "duplicate",
)
RULE_PREFIX = "V3_"


def rule_code(check: str) -> str:
    """The verify rule of one check code: `entailment` -> `V3_ENTAILMENT`."""
    return RULE_PREFIX + check.upper()


ModelRole = Literal["generator", "repair", "judge"]  # = ops.model_role
CallPurpose = Literal["record", "write", "verify", "entail", "repair", "missing", "v2_write", "v2_repair"]


class SegmentConfig(BaseModel):
    """segment V0.x: the own splitter (consideration headings found by code in the ruling text)."""

    model_config = ConfigDict(extra="forbid")

    method: Literal["own_splitter"]
    heading_rules: str = Field(min_length=1, description="where the heading rules come from (ported, not imported)")
    min_citable_depth: int = Field(ge=1, description="a consideration is citable at this depth or deeper")
    locate_offsets: bool
    becomes_primary: bool = Field(description="False: a V0 splitter is never primary (D-070 criteria not measured)")


class SummariseConfig(BaseModel):
    """summarise V1.x: which engine writes the pair, its fallback, and the model role of each call purpose."""

    model_config = ConfigDict(extra="forbid")

    engine: str = Field(pattern=r"^v3@[0-9a-f]{7,40}$")
    fallback: Literal["v2"]
    languages: list[Literal["de", "fr"]]
    call_roles: dict[CallPurpose, ModelRole]
    verify_purposes: list[CallPurpose] = Field(description="call purposes recorded under the verify step")
    quality: Literal["verified_if_both_v3_ok_and_no_failed_check"]
    keep_expert_current: bool = Field(description="a generated version never displaces a current expert edit")
    skip_unchanged: bool = Field(description="no new version when the texts and the lineage equal the current one")

    @field_validator("languages")
    @classmethod
    def _pair(cls, value: list[str]) -> list[str]:
        if sorted(value) != ["de", "fr"]:
            raise ValueError("a summary version is always a German + French pair (D-067)")
        return value


class VerifyConfig(BaseModel):
    """verify V1.x: the engine's per-sentence checks, stored one row per claim and code."""

    model_config = ConfigDict(extra="forbid")

    checks: list[str]
    rule_prefix: Literal["V3_"]
    entailment_min: float = Field(gt=0, le=1)
    repair_attempts: int = Field(ge=0)
    removed_sentence: Literal["text_check_per_failed_code"]
    fallback_rule_for_removed: str

    @field_validator("checks")
    @classmethod
    def _known(cls, value: list[str]) -> list[str]:
        if tuple(value) != CHECK_CODES:
            raise ValueError(f"checks must be exactly {CHECK_CODES}, in that order")
        return value


class VerifyRuleDefinition(BaseModel):
    """One verify rule: which engine check code it stores, on which target."""

    model_config = ConfigDict(extra="forbid")

    check: str
    target: Literal["claim"]
    source: Literal["engine_sentence_checks"]

    @field_validator("check")
    @classmethod
    def _known(cls, value: str) -> str:
        if value not in CHECK_CODES:
            raise ValueError(f"unknown check code {value!r}")
        return value


class PresetConfig(BaseModel):
    """summ.preset_version.config (subject preset_config): the editorial choices of one preset version."""

    model_config = ConfigDict(extra="forbid")

    perspective: int = Field(ge=0, le=10)
    style: Literal["rule_statement", "narrative", "by_ruling_language"]
    writer: Literal["v3"]
    languages: list[Literal["de", "fr"]]
    title: dict[Literal["de", "fr"], str] = Field(description="title line templates; {docket} and {date} by code")
    title_matter: Literal["ruling_language_only", "never"] = Field(
        description="the matter is appended only to the title in the ruling's language: code never translates it"
    )


class PresetVersionEntry(BaseModel):
    """One entry of `versions` in a preset registry file (src/layer3/registry/presets/*.json)."""

    model_config = ConfigDict(extra="forbid")

    version: tuple[int, int, int]
    bump_kind: Literal["initial", "major", "minor", "patch"]
    previous: tuple[int, int, int] | None
    config: dict
    changelog: str = Field(min_length=1)
    decision: str = Field(pattern=r"^D-[0-9]{3}$")
