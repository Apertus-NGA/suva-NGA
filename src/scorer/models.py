"""Contracts of the scorer's registry entries and of the stored run file it loads (D-094)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RuleWeight(Contract):
    """One rule of the fitted scorer. `sign` is fixed before fitting; `mean` and `scale` standardise the input."""

    sign: Literal[1, -1]
    weight: float
    mean: float
    scale: float


class ScorerConfig(Contract):
    """Configuration of layer2_judge V2.x: the fitted scorer, frozen."""

    scorer: str = Field(min_length=1)
    pipeline: str = Field(min_length=1)
    readings: str = Field(min_length=1)
    features: list[str] = Field(min_length=1, description="the rules, in the scorer's input order")
    intercept: float
    rule_weights: dict[str, RuleWeight]
    apertus_rules: list[str] = Field(description="rules fed by Apertus readings; the others are read by code")
    score_raw: Literal["logit"]
    score_mapping: Literal["probability_x100"]


class SignalRule(Contract):
    """Definition of one scorer rule (ops.rule.definition)."""

    feature: str = Field(min_length=1)
    source: Literal["code", "apertus"]
    direction: Literal[1, -1]


class RankingConfig(Contract):
    """Configuration of ranking V1.x: the scorer run's own promotion, taken as stored."""

    cut: Literal["stored_promotion"]
    scorer: str = Field(min_length=1)
    reference_threshold: float = Field(description="the score threshold the scorer froze, for information only")


class StoredRuling(Contract):
    """One kept ruling of the stored scorer run."""

    docket: str
    decision_date: str
    score: float = Field(ge=0, le=1)
    promoted: bool
    explanation_de: str | None
    contributions: dict[str, float]
    signals: dict
    apertus_readings: dict[str, float | None] | None
    apertus_consensus: float | None
    layer1: dict


class StoredRun(Contract):
    """A run of the scorer, exported from the database it ran on (`python -m src.scorer export`)."""

    source_run_id: int
    created_at: str
    git_commit: str | None
    mode: Literal["LIVE", "REPLAY"]
    scorer: str
    models: list[dict]
    rulings: list[StoredRuling]
