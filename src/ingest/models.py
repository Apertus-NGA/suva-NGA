"""Configuration of the `ingest` step: the HF base dataset (D-062, D-072). Checked against ops.json_schema."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Window(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    start: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class IngestConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    hf_repo: str
    hf_file: str
    hf_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    decision_quarters: dict[str, Window] = Field(min_length=1, description="Quarter code -> decision-date window")
    target_quarter: str = Field(pattern=r"^\d{4}Q[1-4]$")
    publication_exact: Window = Field(description="HF poller dates (exact) inside the target window")
    publication_approx: Window = Field(description="First-collection dates (approximate) where no exact date exists")
    poller_start: str = Field(
        pattern=r"^\d{4}-\d{2}-\d{2}$", description="HF publication dates before this are not trusted"
    )
    twin_rule: Literal["same_date"] = "same_date"
    columns: list[str] = Field(min_length=1, description="HF columns read; judges, clerks, outcome are never read")
