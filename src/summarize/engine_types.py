"""The contract between the summary engine (src/summarize/engine.py) and the layer-3 writer (src/layer3/).

The engine reads one ruling and returns an EngineResult: the record of propositions shared by both languages, one
Fiche per language (German and French, each written from the ruling, never translated), and every Apertus call it
made (CallRecord). The writer stores all of it in summ.* and ops.llm_call (docs/LAYER3.md). Nothing here touches the
database or the gateway: plain data, so the writer can be tested with a fake engine and the engine without a DB.

Identifiers (dockets, consideration labels, article references) come from code, never from Apertus (G1): `label` is
a consideration label found by code in the ruling text (for example "E. 3.1"), resolved to a corpus.consideration
row by the writer when a segmentation has it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Literal

Slot = Literal["question", "fact", "rule", "condition", "answer"]  # "question": the court's question, stated by code
Speaker = Literal["court", "lower_court", "appellant", "respondent", "expert"]
SentenceStatus = Literal["written", "repaired", "removed", "code"]  # "code": outcome sentence or note added by code
FicheStatus = Literal["ok", "needs_review", "failed"]
CheckStatus = Literal["pass", "fail", "not_applicable"]
Purpose = Literal["record", "write", "verify", "entail", "repair", "missing", "v2_write", "v2_repair"]


@dataclass(frozen=True)
class RulingSource:
    """What the engine reads: one ruling, from corpus.* (never from Apertus)."""

    ruling_id: str
    docket: str
    decision_date: date
    language: str  # the ruling's language: de | fr | it
    text_id: str  # corpus.ruling_text.text_id of `text`
    text: str
    title: str | None = None  # corpus.ruling.gegenstand
    matter: str | None = None  # the rubric layer 1 read (subject observation), if any
    starred: bool | None = None  # marked for the official reporter (Neuheiten star), when a source says so


@dataclass(frozen=True)
class Proposition:
    """A point of the ruling the fiche must state, chosen by Apertus by sentence id, copied and checked by code."""

    pid: str  # "P1", "P2", ...
    slot: Slot
    speaker: Speaker
    sentence: str  # the ruling sentence, copied by code
    label: str | None  # consideration label found by code, e.g. "E. 3.1"
    accepted: bool
    note: str | None = None  # what code refused or changed


@dataclass(frozen=True)
class Sentence:
    """One sentence of a fiche, in order, with its verification."""

    ordinal: int  # 1..n over the kept sentences of the fiche
    paragraph_no: int  # 1..n
    text: str
    propositions: tuple[str, ...]  # pids the sentence states
    status: SentenceStatus
    entailment: float | None = None  # P(Ja) of the entailment reading, when read
    label: str | None = None  # consideration label of its evidence
    quote: str | None = None  # the ruling sentence it rests on
    why_not: str | None = None  # why a removed sentence was removed
    # check code -> outcome; the codes are the rules of src/layer3/registry/verify.json
    checks: dict[str, CheckStatus] = field(default_factory=dict)


@dataclass(frozen=True)
class Fiche:
    """One language's summary."""

    language: Literal["de", "fr"]
    writer: Literal["v3", "v2"]  # v2 when v3 failed for this language (fallback)
    status: FicheStatus
    body: str  # the final text (code's outcome sentence and note included), plain paragraphs separated by blank lines
    sentences: tuple[Sentence, ...]  # kept and removed sentences; empty for a v2 fiche
    confidence: float | None = None  # 0-100, computed by code from the trace (v3 only)
    band: str | None = None  # high | medium | low (v3 only)
    problems: tuple[str, ...] = ()  # problems the checks left (v2 review, v3 flags)
    write_call_id: str | None = None  # CallRecord.call_id of the call that wrote this fiche
    repair_call_id: str | None = None  # CallRecord.call_id of its last repair, if any


@dataclass(frozen=True)
class CallRecord:
    """One Apertus call (or cache hit) the engine made, for ops.llm_call (one row each, G2 through src/llm/)."""

    call_id: str  # uuid4 string, set by the engine's gateway shim
    purpose: Purpose
    prompt_version: str  # e.g. "v3-write@2/de", "record@1/read", "entail@1/v3"
    language: str | None
    messages: tuple[dict, ...]  # exactly what was sent
    response_text: str | None
    requested_model: str
    served_model: str | None
    size: str  # the client's size: large | small
    params: dict  # max_tokens, temperature, response_format, top_logprobs...
    usage: dict  # prompt_tokens, completion_tokens when known
    latency_ms: int | None
    cache_hit: bool
    error: str | None  # None when the call succeeded
    started_at: str  # ISO 8601
    finished_at: str  # ISO 8601


@dataclass(frozen=True)
class EngineResult:
    ruling_id: str
    engine_version: str  # e.g. "v3@a4a1504"
    record_status: FicheStatus
    propositions: tuple[Proposition, ...]
    fiches: dict[str, Fiche]  # exactly "de" and "fr"
    calls: tuple[CallRecord, ...]

    def as_json(self) -> dict:
        return asdict(self)
