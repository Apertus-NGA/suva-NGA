"""Layer-1 contracts: the step configuration, the rule definitions and the decision record.

One pydantic model per contract (docs/DOCTRINE.md): it validates, and it generates the JSON Schema stored in
`ops.json_schema` (docs/DB_DDL_PLANNING.md §7.4). The database never parses these shapes (D-064).
"""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

Scope = Literal["potentially", "out_of_scope"]
Effect = Literal["keep", "drop", "flag", "signal"]
Outcome = Literal["fired", "not_fired", "not_applicable", "blocked"]
# Why a rule did not apply (the vocabulary of the traceability plan §2.1, also checked by triage.assessment_reason's
# trigger). Only the title check of V1.2.0 (`title_rubric_kept`, plan §2.5, D-083) emits `gegenstand_absent`: it needs
# a title to apply. The title signal of every version is `not_fired` with detail.rubric_source when the rubric did not
# come from the title, as the plan's outcome table says.
NotApplicableWhy = Literal[
    "court_not_listed", "letter_not_listed", "rubric_missing", "text_absent", "gegenstand_absent"
]
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
    "text_unavailable",  # V1.2.0 (D-083): no text, kept so that no ruling is dropped on its docket alone (G5)
    "title_rubric_kept",  # V1.2.0 (D-083): the title head, cut wider than title_head, is in the court's keep set
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


class TitleRubric(Contract):
    """The title head the `title_rubric_kept` check reads (V1.2.0, D-083): the Gegenstand cut at the first of these
    characters, stripped. Wider than `title_head` (the rubric source), which cuts at `(` only (audit F-06, F-08)."""

    cut_at: str = Field(min_length=1, description="Characters that end the matter at the start of the title")


class Layer1Config(Contract):
    """Configuration of one `layer1_filter` version. V1.0.0 reproduces src/courts.py at 4c246a8 exactly."""

    courts: dict[str, CourtKeepSet] = Field(min_length=1, description="Court digit -> letters and rubrics kept")
    rubric_sources: list[RubricSource] = Field(min_length=1, description="Where the rubric is read, first filled wins")
    title_head: TitleHead = TitleHead()
    title_rubric: TitleRubric | None = Field(
        default=None, description="Cut of the title-rubric check; set when the version has a title_rubric_kept rule"
    )
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
    """What a fired rule read. `matched` is None only for a rule that fires on a missing text (full_text, no offsets:
    `text_unavailable`, V1.2.0), as its ledger row is (`triage.assessment_reason`)."""

    field: Literal["docket", "rubric", "gegenstand", "full_text"]
    source: str | None = None  # rubric source when field == rubric
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)
    matched: str | None = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def _missing_text_only(self) -> Evidence:
        if self.matched is None and (self.field != "full_text" or self.start is not None or self.end is not None):
            raise ValueError("only a rule that fires on a missing text has no match (full_text, no offsets)")
        return self


class RuleHit(Contract):
    rule_code: str
    effect: Effect
    evidence: Evidence


class RuleEvaluation(Contract):
    """What one rule of the version did for one ruling: one row of `triage.assessment_reason` (F-01, F-02).

    Every enabled rule of a `layer1_filter` version gets exactly one evaluation per ruling, at its ordinal in the
    version. `fired`: the condition is true and the effect applies. `not_fired`: evaluated, false. `not_applicable`:
    a precondition failed (`detail.why`). `blocked`: the condition is true but another rule neutralises it
    (`detail.blocked_by`). Offsets index the stored ruling text; the database re-checks every field (F-10).
    """

    rule_code: str
    effect: Effect
    ordinal: int = Field(ge=1)
    outcome: Outcome
    evidence_field: str | None = Field(
        default=None, description="docket, rubric:<source>, gegenstand or full_text; None only when not_applicable"
    )
    examined_value: str | None = Field(
        default=None, max_length=300, description="The short value the condition read; None for full-text rules"
    )
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    matched_text: str | None = Field(default=None, min_length=1, max_length=300)
    detail: dict[str, str | int | list[str] | None] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _consistent(self) -> RuleEvaluation:
        problems = []
        if self.outcome != "not_applicable" and self.evidence_field is None:
            problems.append("an evaluated rule names the field it examined")
        if self.outcome == "not_applicable" and self.detail.get("why") not in get_args(NotApplicableWhy):
            problems.append(f"not_applicable needs detail.why in {get_args(NotApplicableWhy)}")
        if self.outcome == "blocked" and not self.detail.get("blocked_by"):
            problems.append("blocked needs detail.blocked_by")
        if self.outcome not in ("fired", "blocked") and (self.char_start is not None or self.matched_text is not None):
            problems.append("offsets and a match belong to a fired or blocked rule only")
        if (self.char_start is None) != (self.char_end is None):
            problems.append("char_start and char_end go together")
        if self.char_start is not None and (self.evidence_field != "full_text" or self.char_end <= self.char_start):
            problems.append("offsets are a non-empty span of the full text")
        if self.evidence_field == "full_text" and self.examined_value is not None:
            problems.append("a full-text rule copies no text into examined_value")
        if problems:
            raise ValueError(f"rule {self.rule_code} ({self.outcome}): " + "; ".join(problems))
        return self


class Layer1DecisionRecord(Contract):
    """One line of decisions.jsonl: one ruling's decision and the ledger of every rule of the version.

    The run writes this file and loads the database from the same in-memory records (D-061); the database is not
    loaded from the file. `python -m src.layer1 verify --run RUN_ID` proves that the file and the database rows
    are equal (F-16). The fired evaluations are the rule hits: they are not stored twice.
    """

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
    # The outcomes of the subject and text checks src/courts.py also has (kept_subject, subject_missing, wrong_court,
    # wrong_letter, subject_out; kept_text, kept_contract, text_clear, text_absent), in every version. A keep those
    # checks do not know (V1.2.0: L1_KEEP_TITLE_RUBRIC, L1_KEEP_TEXT_UNAVAILABLE) is in reason_code and the ledger.
    subject: str
    text: str
    evaluations: list[RuleEvaluation] = Field(min_length=1, description="Every enabled rule, in ordinal order")
    explanation_de: str = Field(min_length=1)
