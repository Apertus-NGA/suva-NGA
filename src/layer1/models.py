"""Layer-1 contracts: the step configuration, the rule definitions and the decision record.

One pydantic model per contract (docs/DOCTRINE.md): it validates, and it generates the JSON Schema stored in
`ops.json_schema` (docs/DB_DDL_PLANNING.md §7.4). The database never parses these shapes (D-064).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Scope = Literal["potentially", "out_of_scope"]
Effect = Literal["keep", "drop", "flag", "signal"]
RubricSource = Literal["neuheiten", "hf_legal_area", "gegenstand_head"]
Check = Literal[
    "court_rubric_kept",
    "court_rubric_missing",
    "text_accident_term",
    "text_contract_term",
    "text_contract_term_blocked",
    "court_not_listed",
    "letter_not_listed",
    "court_rubric_out",
    "rubric_from_gegenstand",
]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CourtKeepSet(Contract):
    letters: str = Field(min_length=1, description="Proceedings letters kept on this court, e.g. CDFG")
    rubrics: list[str] = Field(min_length=1, description="Matter rubrics kept, lower case, in DE/FR/IT")


class Normalisation(Contract):
    casefold: bool = True
    nfkc: bool = False
    apostrophes: bool = False  # typographic ’ ‘ to '
    nbsp: bool = False  # no-break space to space


class TitleHead(Contract):
    cut_at: str = Field(
        default="(", min_length=1, description="Characters that end the matter at the start of the title"
    )
    strip_trailing: str = ",;"


class Layer1Config(Contract):
    """Configuration of one `layer1_filter` version. V1.0.0 reproduces src/courts.py at 4c246a8 exactly."""

    courts: dict[str, CourtKeepSet] = Field(min_length=1, description="Court digit -> letters and rubrics kept")
    rubric_sources: list[RubricSource] = Field(min_length=1, description="Where the rubric is read, first filled wins")
    title_head: TitleHead = TitleHead()
    normalise: Normalisation = Normalisation()
    accident_terms: str = Field(
        min_length=1, description="Regex on the folded text: Suva, its names, accident/military insurance"
    )
    contract_terms: str = Field(
        min_length=1, description="Regex on the folded text: VVG, LCA, private daily-allowance insurance"
    )
    closed_rubrics: str = Field(
        min_length=1, description="Regex on the folded rubric: matters a contract term must not pull back in"
    )


class RuleDefinition(Contract):
    """What a rule checks. The executor of each check is code (src/layer1/engine.py); its parameters are config."""

    check: Check
    note: str | None = None


class Evidence(Contract):
    field: Literal["docket", "rubric", "gegenstand", "full_text"]
    source: str | None = None  # rubric source when field == rubric
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)
    matched: str = Field(min_length=1, max_length=300)


class RuleHit(Contract):
    rule_code: str
    effect: Effect
    evidence: Evidence


class Layer1DecisionRecord(Contract):
    """One line of decisions.jsonl: the file the database loads (D-061: files are the truth)."""

    run_id: str
    ruling_id: str
    docket: str
    decision_date: str
    text_id: str | None
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    in_suva_scope: Scope
    reason_code: str
    score_0_100: float | None = Field(default=None, ge=0, le=100)
    rubric: str | None
    rubric_source: RubricSource | None
    subject: str  # the reason src/courts.py gives (kept_subject, subject_missing, wrong_court, ...)
    text: str  # kept_text, kept_contract, text_clear, text_absent
    hits: list[RuleHit]
    explanation_de: str = Field(min_length=1)
