"""What a refine step is, and the rule that decides whether one of its edits is kept.

A step owns one concern (facts, holding, terminology, …). `propose` reads the draft and returns `Candidate`s: a
finding (what is wrong, with its evidence) and, when the step can fix it, one `Patch`. The step never applies
anything. The runner applies each patch to a copy and keeps it only when (P7 of the refine plan):

1. the patch applies (an existing sentence, not a locked one, its span present);
2. the step's own `verify` finds nothing wrong with the result (a quote not in the ruling, a new identifier, …);
3. no code check has more findings than before (`checks.regressions`), except the ones the step may trade off.

Otherwise the patch is reverted and the finding is `needs_review`. The run never stops on a failure.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from src.summarize.refine.draft import Draft, Patch
from src.summarize.refine.model import Model

Status = Literal["passed", "corrected", "needs_review", "skipped"]


@dataclass
class Context:
    """Everything a step may read. `record` is the shared, quote-checked reading of the ruling (record.py)."""

    language: str  # the fiche's language, "de" or "fr"
    source: str  # the ruling text, as the pipeline cleaned it
    parts: dict[str, str]  # the ruling's labelled passages (evidence.passages)
    category: str  # the matter of the ruling (uv, iv, kv, bv, vvg, other)
    model: Model
    record: dict | None = None
    lexicon: str = ""  # text in which a term of the fiche's language counts as attested (terms.py)
    ruling_language: str | None = None


@dataclass
class Candidate:
    """One finding and, optionally, the patch a step proposes for it."""

    reason: str
    sentence: str | None = None  # the text of the sentence concerned (resolved to an id when the patch is applied)
    evidence: str | None = None  # passage label
    quote: str | None = None  # verbatim from the ruling, checked by code
    patch: Patch | None = None
    verify: Callable[[Draft, Draft], list[str]] | None = None  # (before, after) -> problems; [] means fine
    detail: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        out = {
            "reason": self.reason,
            "sentence": self.sentence,
            "evidence": self.evidence,
            "quote": self.quote,
            "patch": self.patch.as_dict() if self.patch else None,
            **self.detail,
        }
        return {k: v for k, v in out.items() if v not in (None, "", {}, [])}


class Step:
    """Subclasses set `id`, `version`, `kind` and implement `propose`."""

    id: str = "step"
    version: str = "0"
    kind: Literal["code", "model"] = "code"
    allow: tuple[str, ...] = ()  # code checks this step may make worse (a length step may not, a facts step may)

    def propose(self, draft: Draft, ctx: Context) -> list[Candidate]:
        raise NotImplementedError


@dataclass
class Outcome:
    """One step's trace, stored with the run."""

    step: str
    version: str
    status: Status
    findings: list[dict]
    calls: int
    ms: int
    note: str | None = None

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}
