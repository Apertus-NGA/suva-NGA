"""Layer-2 contracts: the step configuration, the prompt file and the judgement record (docs/LAYER2.md).

One pydantic model per contract: it validates, and it generates the JSON Schema stored in `ops.json_schema`
(docs/DB_DDL_PLANNING.md §7.4). The database never parses these shapes (D-064). The frozen contracts of
`src/schemas.py` are not touched (layer-1 precedent: `src/layer1/models.py`).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Outcome = Literal["ok", "failed", "skipped"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AnswerTokens(Contract):
    """First-token alternatives counted as Ja and as Nein (lower case, spaces stripped)."""

    yes: list[str] = Field(min_length=1)
    no: list[str] = Field(min_length=1)


class TextCap(Contract):
    """The D-074 cut: a text longer than `max_chars` is sent as its first `head` characters, the marker, and its
    last `max_chars - head` characters. Recorded per ruling (`llm_judgement.truncation`), never silent (G4)."""

    max_chars: int = Field(gt=0)
    head: int = Field(gt=0)
    marker: str = Field(min_length=1)


class Layer2Config(Contract):
    """Configuration of one `layer2_judge` version. V1.0.0 is the D-074 scoring chain, byte for byte."""

    client_prompt_version: str = Field(
        min_length=1, description="The prompt_version string the client puts in its cache key (D-074 parity)"
    )
    question_language: Literal["de", "fr", "it"] = "de"
    answer_tokens: AnswerTokens
    top_logprobs: int = Field(ge=1, le=20)
    max_tokens: Literal[1] = 1
    temperature: Literal[0] = 0  # the client always sends 0 (src/llm/client.py)
    text_cap: TextCap
    neutralise_control_tags: bool = True
    score_raw: Literal["logit"] = "logit"
    score_mapping: Literal["p_yes_x100"] = "p_yes_x100"
    max_failed_share: float = Field(ge=0, le=1, description="Above it the run fails and nothing is loaded")


class PromptFile(Contract):
    """A versioned prompt file under prompts/ (loaded into ops.prompt_version)."""

    role: str = Field(pattern=r"^[a-z0-9_]+(\.[a-z0-9_]+)*$")
    version: list[int] = Field(min_length=3, max_length=3)
    bump_kind: Literal["initial", "major", "minor", "patch"]
    previous: list[int] | None = None
    contains_suva_material: bool
    system_template: str = Field(min_length=1)
    user_template: str = Field(min_length=1)
    response_schema: dict | None = None
    origin: str | None = None
    changelog: str = Field(min_length=1)


class Prompt(Contract):
    """A prompt version as the runner uses it (read from the database)."""

    prompt_version_id: str
    role: str
    version_label: str
    template_sha256: str
    system_template: str
    user_template: str


class Prepared(Contract):
    """What the code did to the text before the call."""

    chars_total: int = Field(ge=0)
    chars_sent: int = Field(ge=0, description="Source characters sent (the marker of a cut is not counted)")
    truncation: str
    neutralised: int = Field(ge=0, description="Control-like tags replaced (G4)")


class Reading(Contract):
    """The first-token reading of one answer (docs/FINETUNE.md §1)."""

    p_ja: float = Field(ge=0)
    p_nein: float = Field(ge=0)
    p_yes: float = Field(ge=0, le=1)
    mass: float = Field(ge=0)
    logprob_yes: float | None
    logprob_no: float | None
    logit: float
    yes_no_in_top: bool
    top20_floor: float
    top_logprobs: list[tuple[str | None, float | None]]


class Layer2JudgementRecord(Contract):
    """One line of layer2_judgements.jsonl: the file the database loads (D-061: files are the truth)."""

    run_id: str
    ruling_id: str
    docket: str
    decision_date: str
    language: str | None
    repetition: int = Field(ge=0)
    upstream_assessment_id: str
    text_id: str | None
    text_sha256: str | None
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome: Outcome
    reason_code: str | None
    score_source: Literal["judged", "failed"] | None
    score_raw: float | None
    score_0_100: float | None = Field(default=None, ge=0, le=100)
    reading: Reading | None
    prepared: Prepared | None
    messages_sha256: str | None
    cache_key: str | None
    requested_model: str | None
    served_model: str | None
    attempts: int = Field(ge=0)
    cache_hit: bool | None
    input_tokens: int | None
    latency_ms: int | None
    error: str | None
    explanation_de: str = Field(min_length=1)
    started_at: str
    finished_at: str
