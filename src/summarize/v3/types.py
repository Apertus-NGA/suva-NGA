"""Summaries v3: the shared contract of its three parts (record.py, write.py, verify.py).

    record = record.read(text, model)                                  # once per ruling, shared by DE and FR
    draft = write.write(record, "de", ruling, examples, model)         # one call: the whole fiche, as sentences
    fiche = verify.verify(draft, record, "de", ruling, model)          # every sentence checked, then finished

The design (28 Nov, after runs x1 to x16 and the blind comparison of the extractive writer with v2):
- What the fiche must say is decided before it is written, as a short record of propositions. Each proposition
  points to a sentence of the ruling (code copies it) and names WHO says it. Code checks the speaker against its
  own signals; only the Federal Supreme Court's own propositions can be stated as what the court holds.
- Apertus then writes the whole fiche in one call per language, seeing the ruling, the record, Suva's examples
  and the glossary: coherent text, as the prompt-written fiche (v2) is.
- Every written sentence names the proposition(s) it states; code and one-token readings check each sentence
  against the ruling sentence(s) behind them, and the speaker. What fails is repaired once or removed and flagged.

`ruling` everywhere is a dict: {"text", "language" (of the ruling, may be None), "category" (uv, iv, kv, bv, vvg,
other), "docket", "starred"}. `model` is src.summarize.refine.model.Model (JSON answers validated by `ask`,
one-token Ja/Nein readings by `p_yes`).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

VERSION = "v3@1"
SPEAKERS = ("court", "lower_court", "appellant", "respondent", "expert")  # court = the Federal Supreme Court
SLOTS = ("question", "fact", "rule", "condition", "answer")  # the order a fiche states them in
MAX_PROPOSITIONS = 8


@dataclass(frozen=True)
class Proposition:
    """One thing the fiche must say, resting on the ruling's own text."""

    id: str  # "P1", "P2", … in the order the fiche states them
    slot: str  # one of SLOTS
    speaker: str  # one of SPEAKERS: who says this in the ruling
    label: str  # the passage it comes from: "facts", "E.4.2"
    source_id: str  # the candidate sentence id (src/summarize/extract/candidates.py), "S12"; "Q" for the question
    source: str  # the ruling's sentence, copied by code, never written by the model


@dataclass
class Record:
    """What code and Apertus read from the ruling, once, for both languages."""

    propositions: tuple[Proposition, ...]
    outcome: str  # finish.outcome_kind: "rejected" | "admitted" | "partial" | ""
    remand: bool  # point 1 of the operative part sends the case back
    parties: dict  # {"insured_female": bool | None, "appellant": "insured" | "insurer" | None, "insurer": str | None}
    profile: str | None  # "income_comparison" | "causation" | None (src/summarize/extract/profiles.py)
    issues: list[str] = field(default_factory=list)  # what code refused or changed, and why
    status: str = "ok"  # "ok" | "needs_review" (no court rule or no court answer could be checked)
    calls: int = 0
    version: str = VERSION

    def get(self, pid: str) -> Proposition:
        return next(p for p in self.propositions if p.id == pid)

    def required(self) -> list[Proposition]:
        """What every fiche must state: the court's own rules and its answer."""
        return [p for p in self.propositions if p.speaker == "court" and p.slot in ("rule", "answer")]

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Sentence:
    """One sentence of a fiche and the proposition(s) it states (1 or 2 ids)."""

    text: str
    propositions: tuple[str, ...]
    status: str = "written"  # "written" | "repaired" | "removed"
    problems: list[str] = field(default_factory=list)
    entailment: float | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Fiche:
    """The verified fiche of one language."""

    text: str  # finished: outcome sentence and Suva's closing note added by code
    sentences: list[Sentence]  # every sentence written, kept or not
    missing: list[str]  # ids of required propositions no kept sentence states
    notes: list[str]
    calls: int
    status: str  # "ok" | "needs_review" | "failed" (no usable text: the caller falls back to v2)

    def as_dict(self) -> dict:
        return asdict(self)
