"""Summaries v3: a checked record of what the fiche must say, one written fiche per language, every sentence verified.

    result = fiches(ruling, examples, make_model)     # {"record": Record, "languages": {lang: Fiche | ModelFailed}}
    steps = as_steps(result["record"], fiche)         # the trace the interface shows (workspace.refine_checks)

See types.py for the design and the contract of the three parts.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from src.summarize.refine.model import ModelFailed
from src.summarize.v3 import record as record_part
from src.summarize.v3 import verify as verify_part
from src.summarize.v3 import write as write_part
from src.summarize.v3.confidence import confidence
from src.summarize.v3.types import VERSION, Fiche, Record

LANGUAGES = ("de", "fr")
RECORD_BUDGET = 12  # the record: a few calls and their retries
FICHE_BUDGET_PER_SENTENCE = 3  # per written sentence: its reading, one repair, the repair's reading


def fiche_budget(record: Record) -> int:
    """One call to write, then per sentence a reading and at most one repair with its reading, and the missing ones."""
    return 6 + FICHE_BUDGET_PER_SENTENCE * (2 * len(record.propositions) + 2)


def fiches(ruling: dict, examples: dict[str, list[dict]], make_model) -> dict:
    """The record (read once) and the verified fiche of each language. A language whose fiche could not be written
    holds the ModelFailed instead; a ModelFailed from the record propagates (the caller falls back)."""
    record = record_part.read(ruling["text"], make_model(RECORD_BUDGET))

    def one(language: str):
        model = make_model(fiche_budget(record))
        try:
            draft = write_part.write(record, language, ruling, examples.get(language, []), model)
            return verify_part.verify(draft, record, language, ruling, model)
        except ModelFailed as exc:
            return exc

    with ThreadPoolExecutor(len(LANGUAGES)) as pool:  # DE and FR at once; the client caps concurrent calls (G2)
        written = dict(zip(LANGUAGES, pool.map(one, LANGUAGES), strict=True))
    return {"record": record, "languages": written}


def as_steps(record: Record, fiche: Fiche) -> list[dict]:
    """The trace in the step format the interface reads: the record's propositions with who says them and the
    ruling sentence behind each, then every written sentence with the proposition(s) it states and why it was
    refused when it was."""
    by_id = {p.id: p for p in record.propositions}
    propositions = [
        {"reason": f"{p.id} {p.slot}, said by: {p.speaker}", "accepted": True, "evidence": p.label, "quote": p.source}
        for p in record.propositions
    ]
    sentences = []
    for s in fiche.sentences:
        sources = [by_id[i] for i in s.propositions if i in by_id]
        entry = {
            "reason": ", ".join(f"{p.id} {p.slot} ({p.speaker})" for p in sources) or "no proposition",
            "accepted": s.status != "removed",
            "evidence": ", ".join(dict.fromkeys(p.label for p in sources)),
            "quote": " … ".join(p.source for p in sources),
            "text": s.text,
            "status": s.status,
            "entailment": s.entailment,
        }
        if s.problems:
            entry["why_not"] = "; ".join(s.problems)
        sentences.append(entry)
    missing = [{"reason": f"{i} not stated", "accepted": False, "evidence": by_id[i].label, "quote": by_id[i].source}
               for i in fiche.missing if i in by_id]  # fmt: skip
    return [
        {"step": "record", "status": "passed" if record.status == "ok" else "needs_review", "calls": record.calls,
         "findings": propositions, "note": "; ".join(record.issues) or None},
        {"step": "verify", "status": {"ok": "passed", "needs_review": "needs_review"}.get(fiche.status, "needs_review"),
         "calls": fiche.calls, "findings": sentences + missing, "note": "; ".join(fiche.notes) or None},
    ]  # fmt: skip


__all__ = ["VERSION", "Fiche", "Record", "as_steps", "confidence", "fiches"]
