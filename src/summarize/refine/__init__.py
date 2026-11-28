"""Refine: after the pipeline writes a fiche, a fixed list of narrow steps improves it one concern at a time.

Apertus interprets, code verifies: every step names sentences and passages by id from closed lists, every quote is
looked up in the ruling, every identifier in a model-written sentence must already be in the ruling, and a patch is
kept only if it fixes its finding and no code check gets worse. Everything is traced.

    from src.summarize.refine import refine_fiche, read_record
"""

from __future__ import annotations

from src.summarize.refine import evidence
from src.summarize.refine.model import Model, gateway
from src.summarize.refine.record import read as read_record
from src.summarize.refine.runner import VERSION, Result, refine
from src.summarize.refine.step import Context


def refine_fiche(
    text: str,
    language: str,
    source: str,
    category: str,
    model: Model,
    record: dict | None = None,
    lexicon: str = "",
    ruling_language: str | None = None,
    steps=None,
) -> Result:
    """Refine one finished fiche. `record` is the shared reading of the ruling (read it once per ruling)."""
    ctx = Context(language, source, evidence.passages(source), category, model, record, lexicon, ruling_language)
    return refine(text, ctx, steps)


__all__ = ["VERSION", "Model", "Result", "gateway", "read_record", "refine_fiche"]
