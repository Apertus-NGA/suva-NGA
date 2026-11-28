"""What code decides about a summary text before it is stored: title line, claims, sections, citations, checks and
the version's quality (docs/LAYER3.md). Pure functions over the engine's result (src/summarize/engine_types.py),
no database, so they are tested without one (tests/test_layer3_unit.py).

- Title line: rendered by code from the docket and the decision date in the text's language (DB plan §13.1); the
  matter is appended only to the title in the ruling's language, because code never translates it.
- Claims: one per kept sentence (written, repaired, or added by code), in order. Section from the slot of the
  first proposition the sentence states (question and fact -> facts, rule -> law, condition -> application,
  answer -> outcome);
  a code sentence (outcome, note) is `outcome`. Status `verified` when none of its checks failed, `flagged`
  otherwise, or when a model sentence carries no check at all, names no known proposition, or cannot be found in
  the stored body (entailment detail `not_in_body`). `rendered_text` is the sentence as the engine gives it (as it
  reads in the body); `model_text` the same for a model sentence, cut at 300 characters with "…" (entailment
  detail `model_text_truncated`, `model_text_full`), NULL for code's sentences.
- Citations: the sentence's evidence label, then the labels of its propositions, resolved by code to citable
  considerations of the version's segmentation (G1); a label that resolves to nothing is not cited.
- Removed sentences: one text-level `fail` per failed code; `not_applicable` under the fallback rule when the
  engine read the sentence's checks and none failed (left out for length), with why; a `fail` under the fallback
  rule only when the engine named no check at all.
- Quality: `verified` when both fiches are v3 and ok and no claim is flagged, else `flagged`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from src.layer3.models import CHECK_CODES, PresetConfig
from src.layer3.segment import label_number
from src.summarize.engine_types import Fiche, Proposition, Sentence

SLOT_SECTION = {"question": "facts", "fact": "facts", "rule": "law", "condition": "application", "answer": "outcome"}
MAX_MODEL_TEXT = 300  # summ.summary_claim.model_text CHECK
MAX_PARAGRAPHS = 20  # summ.summary_text.paragraph_count CHECK
MONTHS = {
    "de": ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November",
           "Dezember"),
    "fr": ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre",
           "décembre"),
}  # fmt: skip
_PARAGRAPHS = re.compile(r"\n[ \t]*\n")


class FicheRejected(ValueError):
    """A fiche cannot be stored as one language of a version; the ruling fails with `reason_code`."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class CheckPlan:
    check: str  # engine check code, e.g. "entailment" (rule V3_ENTAILMENT)
    status: str  # pass | fail | not_applicable
    detail: dict


@dataclass(frozen=True)
class ClaimPlan:
    ordinal: int
    paragraph_no: int
    section: str
    model_text: str | None
    rendered_text: str
    status: str  # verified | flagged
    citations: tuple[str, ...]  # consideration ids, in order
    checks: tuple[CheckPlan, ...]


@dataclass(frozen=True)
class TextPlan:
    language: str
    writer: str
    fiche_status: str
    title_line: str
    body: str
    word_count: int
    paragraph_count: int
    write_call_id: str | None
    repair_call_id: str | None
    claims: tuple[ClaimPlan, ...]
    removed: tuple[CheckPlan, ...]  # text-level checks of removed sentences
    unknown_checks: tuple[str, ...] = field(default=())  # codes the engine sent that verify does not register


def format_date(day: date, language: str) -> str:
    """2 April 2026 -> "2. April 2026" (de), "2 avril 2026" (fr), "1er avril 2026" on the first."""
    month = MONTHS[language][day.month - 1]
    if language == "de":
        return f"{day.day}. {month} {day.year}"
    return f"{'1er' if day.day == 1 else day.day} {month} {day.year}"


def clean_matter(matter: str | None) -> str | None:
    """A source matter as a title fragment: one line, no trailing comma or semicolon, at most 120 characters."""
    if not matter:
        return None
    text = " ".join(matter.split()).strip(" ,;:")
    return text[:120].rstrip() or None


def title_line(
    language: str, *, docket: str, decision_date: date, matter: str | None, ruling_language: str, preset: PresetConfig
) -> str:
    title = preset.title[language].format(docket=docket, date=format_date(decision_date, language))  # type: ignore[index]
    fragment = clean_matter(matter)
    if fragment and preset.title_matter == "ruling_language_only" and language == ruling_language:
        title = f"{title} – {fragment}"
    return title


def count_words(body: str) -> int:
    return len(body.split())


def count_paragraphs(body: str) -> int:
    return sum(1 for p in _PARAGRAPHS.split(body.strip()) if p.strip())


def section_for(sentence: Sentence, propositions: dict[str, Proposition]) -> str | None:
    """The claim section of one sentence; None when a model sentence names no known proposition."""
    if sentence.status == "code":
        return "outcome"
    for pid in sentence.propositions:
        if pid in propositions:
            return SLOT_SECTION[propositions[pid].slot]
    return None


def claim_status(sentence: Sentence) -> str:
    if any(status == "fail" for status in sentence.checks.values()):
        return "flagged"
    if sentence.status != "code" and not sentence.checks:
        return "flagged"
    return "verified"


def _citations(sentence: Sentence, propositions: dict[str, Proposition], citable: dict[str, str]) -> tuple[str, ...]:
    labels = [sentence.label] + [propositions[p].label for p in sentence.propositions if p in propositions]
    out: list[str] = []
    for label in labels:
        cid = citable.get(label_number(label) or "")
        if cid and cid not in out:
            out.append(cid)
    return tuple(out)


def _flat(text: str) -> str:
    return " ".join(text.split())


def _model_text(text: str) -> tuple[str, dict]:
    """(model_text within the column's 300 characters, entailment detail): a longer sentence is cut with "…" and
    kept in full in the detail, never dropped (NULL model_text means an expert's claim)."""
    if len(text) <= MAX_MODEL_TEXT:
        return text, {}
    return text[: MAX_MODEL_TEXT - 1].rstrip() + "…", {"model_text_truncated": True, "model_text_full": text}


def _evidence(sentence: Sentence) -> dict:
    return {
        "sentence_status": sentence.status,
        "entailment": sentence.entailment,
        "label": sentence.label,
        "quote": sentence.quote,
        "why_not": sentence.why_not,
    }


def plan_text(
    fiche: Fiche,
    *,
    docket: str,
    decision_date: date,
    matter: str | None,
    ruling_language: str,
    propositions: dict[str, Proposition],
    citable: dict[str, str],
    preset: PresetConfig,
    fallback_rule_check: str = "entailment",
) -> TextPlan:
    """One language of a version, as it will be stored. Raises FicheRejected when it cannot be stored."""
    body = (fiche.body or "").strip()
    if not body:
        raise FicheRejected("L3_LANGUAGE_MISSING", f"the {fiche.language} fiche has no text ({fiche.status})")
    if not fiche.write_call_id:
        raise FicheRejected("L3_FICHE_UNTRACED", f"the {fiche.language} fiche names no write call (D-014)")
    paragraphs = count_paragraphs(body)
    if paragraphs > MAX_PARAGRAPHS:
        raise FicheRejected("L3_ENGINE_FAILED", f"the {fiche.language} fiche has {paragraphs} paragraphs (max 20)")
    claims: list[ClaimPlan] = []
    removed: list[CheckPlan] = []
    unknown: list[str] = []
    flat_body = _flat(body)
    for sentence in fiche.sentences:
        unknown += [c for c in sentence.checks if c not in CHECK_CODES and c not in unknown]
        if sentence.status == "removed":
            failed = [c for c in CHECK_CODES if sentence.checks.get(c) == "fail"]
            detail = {**_evidence(sentence), "text": sentence.text, "ordinal": sentence.ordinal}
            if failed:  # what the engine found
                removed += [CheckPlan(code, "fail", detail | {"attributed": "engine"}) for code in failed]
            elif sentence.checks:  # read and passed, then left out (length): no failure to claim
                removed.append(
                    CheckPlan(fallback_rule_check, "not_applicable",
                              detail | {"attributed": "none", "removed_for": sentence.why_not})
                )  # fmt: skip
            else:  # the engine named no check at all: the writer's fallback rule records the removal
                removed.append(CheckPlan(fallback_rule_check, "fail", detail | {"attributed": "fallback"}))
            continue
        text = sentence.text.strip()
        if not text:
            continue
        section = section_for(sentence, propositions)
        status = claim_status(sentence) if section is not None else "flagged"
        is_model = sentence.status in ("written", "repaired")
        model, extra = _model_text(text) if is_model else (None, {})
        if _flat(text) not in flat_body:  # the claim must read as the stored body says it
            status = "flagged"
            extra = extra | {"not_in_body": True, "engine_text": text}
        checks = tuple(
            CheckPlan(code, sentence.checks[code], _evidence(sentence) | extra if code == "entailment" else {})
            for code in CHECK_CODES
            if code in sentence.checks
        )
        claims.append(
            ClaimPlan(
                ordinal=len(claims) + 1,
                paragraph_no=max(1, sentence.paragraph_no),
                section=section or "facts",
                model_text=model,
                rendered_text=text,
                status=status,
                citations=_citations(sentence, propositions, citable),
                checks=checks,
            )
        )
    return TextPlan(
        language=fiche.language,
        writer=fiche.writer,
        fiche_status=fiche.status,
        title_line=title_line(
            fiche.language,
            docket=docket,
            decision_date=decision_date,
            matter=matter,
            ruling_language=ruling_language,
            preset=preset,
        ),
        body=body,
        word_count=count_words(body),
        paragraph_count=max(1, paragraphs),
        write_call_id=fiche.write_call_id,
        repair_call_id=fiche.repair_call_id,
        claims=tuple(claims),
        removed=tuple(removed),
        unknown_checks=tuple(unknown),
    )


def quality_status(texts: list[TextPlan]) -> str:
    """`verified` when both fiches are v3 and ok and no claim is flagged; `flagged` otherwise (fallback to v2,
    a fiche that needs review, or a claim with a failed check)."""
    ok = all(t.writer == "v3" and t.fiche_status == "ok" for t in texts)
    clean = all(c.status == "verified" for t in texts for c in t.claims)
    return "verified" if ok and clean else "flagged"
