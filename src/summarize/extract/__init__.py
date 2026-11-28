"""The extractive writer: the fiche built from the ruling's own sentences (docs/REFINE.md for refine).

    choice = choose.choose(text, model)                       # one reading of the ruling, shared by DE and FR
    fiche = write.write_fiche(choice, "de", ruling, model, frame="question")
    steps = as_steps(choice, fiche)                           # the trace the interface shows (workspace.refine_checks)

Code filters the ruling (candidates.py), Apertus ranks the considerations and chooses sentences by id (choose.py),
code adds what the profile of the case and the court's answer require (profiles.py), Apertus adapts or translates
each sentence, which code and an entailment reading check (write.py), and refine's form, terms and language steps
polish the result. Every sentence keeps the consideration and the ruling sentence it comes from.
"""

from __future__ import annotations

from src.summarize.extract import choose, write

VERSION = "extract@1"


def as_steps(choice: choose.Choice, fiche: write.Fiche) -> list[dict]:
    """The fiche's trace in the step format the interface reads: per sentence the consideration and the ruling
    sentence it comes from (evidence, quote), whether it was kept, and why not."""
    sentences = [
        {"reason": f"{w.label} ({w.role})", "accepted": w.status in ("written", "cleaned"), "evidence": w.label,
         "quote": w.source, "text": w.text, "status": w.status,
         **({"why_not": "; ".join(w.problems)} if w.status not in ("written", "cleaned") and w.problems else {})}
        for w in fiche.sentences
    ]  # fmt: skip
    return [
        {"step": "choose", "status": "passed", "calls": 0, "findings": [],
         "note": f"{len(choice.chosen)} sentences of {choice.offered} candidates; " + "; ".join(choice.notes or [])},
        {"step": "write", "status": "needs_review" if any(w.status == "dropped" for w in fiche.sentences)
         else "corrected", "calls": fiche.calls, "findings": sentences},
        {"step": "flow", "status": "passed", "calls": 0,
         "findings": [{"reason": f["id"], "accepted": f.get("accepted"), **({"why_not": f["why_not"]} if
                       f.get("why_not") else {})} for f in fiche.flow]},
        *[{**o, "step": "polish:" + o["step"]} for o in fiche.polish],
    ]  # fmt: skip


__all__ = ["VERSION", "as_steps", "choose", "write"]
