"""Helpers shared by the steps: language names, guards on model-written sentences, consideration references."""

from __future__ import annotations

import re

from src.summarize.refine import checks
from src.summarize.refine.draft import Draft
from src.summarize.refine.model import ModelFailed

NAME = {"de": "German", "fr": "French", "it": "Italian"}
MAX_SENTENCE_WORDS = 60


def reference(label: str | None, language: str) -> str:
    """The bracketed consideration reference code adds for a passage label ("E.4.2" -> "(E. 4.2)")."""
    if not label or not label.startswith("E."):
        return ""
    number = label[2:]
    return f" (E. {number})" if language == "de" else f" (consid. {number})"


def with_reference(sentence: str, label: str | None, language: str) -> str:
    """Put the reference before the final full stop, unless the sentence already cites a consideration."""
    ref = reference(label, language)
    sentence = sentence.strip()
    if not ref or re.search(r"\((?:E\.|consid\.|Erw\.)", sentence):
        return sentence
    return sentence[:-1] + ref + "." if sentence.endswith(".") else sentence + ref + "."


def written_sentence_problems(new: str, old: str, ctx, max_words: int = MAX_SENTENCE_WORDS) -> list[str]:
    """What code demands of any sentence a model wrote: the fiche's language, a sane length, no new identifier,
    no Markdown, no placeholder left."""
    problems = []
    if not new.strip():
        return ["empty sentence"]
    language = checks.language_of(new)
    if language is not None and language != ctx.language:
        problems.append(f"written in {language}, not {ctx.language}")
    if len(new.split()) > max_words:
        problems.append(f"{len(new.split())} words, over {max_words}")
    if re.search(r"\*\*|^\s*[-•#]", new):
        problems.append("markup")
    problems += checks.new_identifiers(new, old, ctx.source)
    return problems


def guarded(check):
    """Wrap a verify function that may call the model: a failed call refuses the patch, it never crashes the run."""

    def verify(before: Draft, after: Draft) -> list[str]:
        try:
            return check(before, after)
        except ModelFailed as exc:
            return [f"re-check failed: {exc}"]

    return verify


def editable(draft: Draft) -> list[str]:
    return draft.ids(editable_only=True)
