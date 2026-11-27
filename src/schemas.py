"""The frozen contracts (docs/ARCHITECTURE.md §3). Owner: platform. Changes by PR only (AGENTS.md G7).

One pydantic model per contract: it validates, and it generates the JSON schema (`json_schemas()`) used for
`response_format` and prompt examples. Every model forbids unknown fields (`additionalProperties: false`).
LLM output fields carry `a_`/`b_`/`c_` prefixes because the gateway emits JSON keys in alphabetical order
(docs/LESSONS.md K3): the prefix fixes the generation order.

What these contracts keep open on purpose: both dates and both quarters on every ruling (D-050); where a
score comes from (`score_source`, D-021); the threshold and the top-30 cut both marked (D-046).
"""

from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

SCHEMA_VERSION = "1"

DOCKET_PATTERN = r"^[0-9]{1,2}[A-Z]_[0-9]+/[0-9]{4}$"  # 8C_802/2023: court + register letter, number, filing year
QUARTER_PATTERN = r"^[0-9]{4}Q[1-4]$"  # 2026Q2
CONSIDERATION_ID_PATTERN = r"^c[0-9]+$"  # c1, c2, ... in document order (what Apertus sees)

Docket = Annotated[str, StringConstraints(pattern=DOCKET_PATTERN)]
Quarter = Annotated[str, StringConstraints(pattern=QUARTER_PATTERN)]
ConsiderationId = Annotated[str, StringConstraints(pattern=CONSIDERATION_ID_PATTERN)]
Language = Literal["de", "fr", "it"]
Outcome = Literal["upheld", "partly_upheld", "dismissed", "inadmissible", "remanded", "other"]
Mode = Literal["LIVE", "REPLAY"]


def quarter_of(d: date) -> str:
    """The calendar quarter of a date, as `2026Q2`. Computed by code, never typed (D-050)."""
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Rulings (stage S0) ---------------------------------------------------------------------------------


class Consideration(Contract):
    id: ConsiderationId
    e_number: str | None = None  # the court's numbering ("5.1"), rendered as "E. 5.1" / "consid. 5.1" by code
    text: str = Field(min_length=1)


class RulingRecord(Contract):
    """One Federal Court decision. Key: (docket, decision_date): one docket can hold several decisions (T14)."""

    docket: Docket
    decision_date: date
    # The publication date comes only from a Neuheiten page (ours, or HF's poller from 19 May 2026); it is
    # never derived from the decision date. A first-collection date is only an approximation (crawl brief).
    publication_date: date | None = None
    publication_date_source: Literal["neuheiten", "hf_poller"] | None = None
    publication_date_approx: date | None = None
    publication_date_quality: Literal["exact", "approx_first_seen", "unknown"]
    quarter_by_decision: Quarter
    quarter_by_publication: Quarter | None = None
    court: Annotated[str, StringConstraints(pattern=r"^[0-9]{1,2}[A-Z]$")]  # "8C"
    register_letter: Annotated[str, StringConstraints(pattern=r"^[A-Z]$")]  # "C"
    language: Language
    sachgebiet: str | None = None  # subject area, in the ruling's language (Neuheiten list)
    gegenstand: str | None = None
    star: bool = False  # destined for publication: exists only in the Neuheiten list
    url: str = Field(min_length=1)
    text_source: Literal["hf", "bger", "entscheidsuche", "opencaselaw"] | None = None
    text_hash: str | None = None  # SHA-256 of full_text
    full_text: str | None = None
    text_missing_reason: str | None = None  # a counted reason code when there is no text (G5)
    clean_length: int | None = Field(default=None, ge=0)  # characters of the cleaned text (rule SR8)
    considerations: list[Consideration] = Field(default_factory=list)
    parties_block: str | None = None
    bench_size: int | None = Field(default=None, ge=1)
    operative_part: str | None = None
    outcome: Outcome | None = None

    @model_validator(mode="after")
    def _consistent(self) -> RulingRecord:
        if not self.docket.startswith(f"{self.court}_") or self.court[-1] != self.register_letter:
            raise ValueError("court and register_letter must match the docket")
        if self.quarter_by_decision != quarter_of(self.decision_date):
            raise ValueError("quarter_by_decision must be computed from decision_date")
        expected_pub_quarter = quarter_of(self.publication_date) if self.publication_date else None
        if self.quarter_by_publication != expected_pub_quarter:
            raise ValueError("quarter_by_publication must be computed from publication_date")
        has_pub = self.publication_date is not None
        if has_pub != (self.publication_date_source is not None) or has_pub != (
            self.publication_date_quality == "exact"
        ):
            raise ValueError("publication_date, its source and quality 'exact' go together")
        if self.publication_date_quality == "approx_first_seen" and self.publication_date_approx is None:
            raise ValueError("quality 'approx_first_seen' needs publication_date_approx")
        if self.publication_date_quality == "unknown" and self.publication_date_approx is not None:
            raise ValueError("quality 'unknown' cannot carry publication_date_approx")
        if self.full_text is None:
            if not self.text_missing_reason:
                raise ValueError("a ruling without text needs text_missing_reason (G5)")
        else:
            if not self.full_text.strip():
                raise ValueError("full_text is empty: use text_missing_reason instead (G4)")
            if self.text_source is None or self.text_hash != sha256_text(self.full_text):
                raise ValueError("full_text needs text_source and text_hash = SHA-256 of full_text")
        ids = [c.id for c in self.considerations]
        if ids != [f"c{i}" for i in range(1, len(ids) + 1)]:
            raise ValueError("consideration ids must be c1, c2, ... in document order")
        return self


class SuvaExampleRecord(Contract):
    """A row of Suva's list and/or one of its exports (judgements/), built by S0.

    Nothing else is parsed or stored: no author, staff code, job title, intranet link or file property (D-051).
    """

    docket: str = Field(min_length=1)  # the cantonal row keeps its title here
    is_federal_court: bool
    decision_date: date | None = None
    quarter_label: Annotated[str, StringConstraints(pattern=r"^[0-9]{4} Q[1-4]$")] | None = None  # list rows only
    in_list: bool
    text_de: str | None = None  # exports only
    text_fr: str | None = None
    bger_url: str | None = None
    source_files: list[str] = Field(min_length=1)  # paths under judgements/

    @model_validator(mode="after")
    def _consistent(self) -> SuvaExampleRecord:
        if self.is_federal_court and not re.match(DOCKET_PATTERN, self.docket):
            raise ValueError("a Federal Court example needs a canonical docket")
        if self.in_list != (self.quarter_label is not None):
            raise ValueError("quarter_label is set exactly for list rows")
        if (self.text_de is None) != (self.text_fr is None):
            raise ValueError("an export carries both text_de and text_fr")
        if any(not f.startswith("judgements/") for f in self.source_files):
            raise ValueError("source_files are paths under judgements/")
        return self


# --- Signals and net (stages S1, S2) --------------------------------------------------------------------


class Evidence(Contract):
    consideration_id: ConsiderationId | None = None
    field: str | None = None  # for metadata evidence: "sachgebiet", "star", "parties_block", ...
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _span(self) -> Evidence:
        if self.consideration_id is None and self.field is None:
            raise ValueError("evidence points to a consideration or a field")
        if (self.start is None) != (self.end is None) or (self.start is not None and self.start > self.end):
            raise ValueError("start and end come together, start <= end")
        return self


class Signal(Contract):
    name: str = Field(min_length=1)
    value: bool | int | float | str
    evidence: Evidence | None = None


class NetDecision(Contract):
    kept: bool
    reason_code: str | None = None

    @model_validator(mode="after")
    def _reason(self) -> NetDecision:
        if not self.kept and not self.reason_code:
            raise ValueError("nothing is excluded without a reason code (G5)")
        return self


class SignalsRecord(Contract):
    docket: Docket
    decision_date: date
    signals: list[Signal]
    net_decision: NetDecision


# --- LLM outputs (stages S3, S6) -------------------------------------------------------------------------


class TriageCall(Contract):
    """One ruling per call. With log-probabilities only `c_label` is read, from the first token (S3)."""

    a_evidence: list[ConsiderationId]  # chosen among the ids sent: enum set by triage_call_schema()
    b_key_statement: str = Field(max_length=300)
    c_label: Literal["A", "B"]  # A = relevant, B = not relevant


class SummaryClaim(Contract):
    a_cites: list[ConsiderationId]
    b_text: str = Field(max_length=300)
    c_section: Literal["facts", "law", "outcome"]


class SummaryCall(Contract):
    a_claims: list[SummaryClaim]
    b_outcome: Outcome
    c_unknown: list[str]


# --- Decisions (stages S4, S5) ---------------------------------------------------------------------------


class RoleVersion(Contract):
    """Which model or prompt version served a role ("judge", "summary_de", ...): a closed object, not a map."""

    role: str = Field(min_length=1)
    version: str = Field(min_length=1)


class DecisionRecord(Contract):
    """Every ruling of a candidate population ends with one: a score and an explanation (G5)."""

    docket: Docket
    decision_date: date
    score: float = Field(ge=0, le=100)
    score_source: Literal["judged", "signals_only", "net", "failed"]  # D-021 point 7
    selected: bool  # above the F2 threshold
    rank: int = Field(ge=1)
    in_top30: bool  # D-046
    threshold_version: str = Field(min_length=1)
    explanation_de: str = Field(min_length=1)
    signals_fired: list[str]
    model_versions: list[RoleVersion]
    prompt_versions: list[RoleVersion]
    mode: Mode

    @model_validator(mode="after")
    def _top30(self) -> DecisionRecord:
        if self.in_top30 != (self.rank <= 30):
            raise ValueError("in_top30 is exactly rank <= 30")
        return self


# --- JSON schemas ----------------------------------------------------------------------------------------

CONTRACTS: dict[str, type[Contract]] = {
    "ruling_record": RulingRecord,
    "suva_example_record": SuvaExampleRecord,
    "signals_record": SignalsRecord,
    "triage_call": TriageCall,
    "summary_call": SummaryCall,
    "decision_record": DecisionRecord,
}
LLM_OUTPUTS = ("triage_call", "summary_call")


def json_schemas() -> dict[str, dict[str, Any]]:
    return {name: model.model_json_schema() for name, model in CONTRACTS.items()}


def triage_call_schema(consideration_ids: list[str]) -> dict[str, Any]:
    """The triage schema for one ruling: `a_evidence` may only name the consideration ids we sent (G1)."""
    if not consideration_ids:
        raise ValueError("a triage call needs at least one consideration id")
    schema = TriageCall.model_json_schema()
    schema["properties"]["a_evidence"]["items"] = {"type": "string", "enum": list(consideration_ids)}
    return schema


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    for name, schema in json_schemas().items():
        if out:
            out.mkdir(parents=True, exist_ok=True)
            (out / f"{name}.schema.json").write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
        else:
            print(name, json.dumps(schema)[:120], "...")
