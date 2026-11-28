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


# Calques the judge failed in run r2 (T1 fell from 0.83 to 0.67): the French word in a German fiche and the reverse.
CALQUES = {
    "de": ["Gutachten (nicht: Expertise)", "Vorinstanz oder kantonales Gericht (nicht: untere Instanz)",
           "Invalidenrente (nicht: Rente allein, wenn die IV-Rente gemeint ist)"],
    "fr": ["autorité précédente ou juridiction cantonale (pas: instance inférieure)",
           "rente d'invalidité (pas: rente seule, s'il s'agit de la rente AI)", "expertise (pas: Gutachten)"],
}  # fmt: skip


# Procedural terms of art: a rewording that brings one in changes the law the sentence states (run r7: a 'clumsy'
# fix turned the insured's objections into an "Einsprache", the formal objection procedure; T1 failed).
PROCEDURAL = {
    "de": ("Einsprache", "Beschwerde", "Rekurs", "Revision", "Wiedererwägung", "Rückweisung", "Klage", "Verfügung",
           "Einspracheentscheid", "Nichteintreten"),
    "fr": ("opposition", "recours", "révision", "reconsidération", "renvoi", "action", "décision sur opposition",
           "irrecevab", "non-entrée en matière"),
}  # fmt: skip


def new_terms(new: str, old: str, ctx) -> list[str]:
    """Terms of art (the matter's glossary and the procedural ones) in `new` that `old` did not use."""
    from src.summarize.refine.steps.terms import pairs

    vocabulary = [row[ctx.language] for row in pairs(ctx.category)] + list(PROCEDURAL[ctx.language])
    low_new, low_old = new.lower(), old.lower()
    return [
        f"brings in the term '{t}'"
        for t in dict.fromkeys(vocabulary)
        if t.lower() in low_new and t.lower() not in low_old
    ]


def terms_hint(ctx) -> str:
    """The matter's glossary in the fiche's language, for any prompt that writes text (src/summarize/v2)."""
    from src.summarize.refine.steps.terms import pairs

    own = [row[ctx.language] for row in pairs(ctx.category)]
    listed = "; ".join(dict.fromkeys(own + CALQUES[ctx.language]))
    return f"\nSwiss {NAME[ctx.language]} terms to use: {listed}."


def polish(text: str, ctx) -> str:
    """Code's normalisation of any model-written text before it is checked: the fiche language's abbreviations,
    citation forms and spelling, no invented consideration reference (the same as the form step)."""
    from src.summarize.refine.steps.form import fixed

    return fixed(" ".join(text.split()), ctx.language, ctx.source)


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
    if checks.restates_outcome(new) and not checks.restates_outcome(old):
        problems.append("states the outcome, which the code-written last sentence already states")
    if re.search(r"_{3,}", new):
        problems.append("anonymisation placeholder")
    problems += checks.new_identifiers(new, old, ctx.source)
    return problems


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"\w{4,}", text.lower())}


def repeats(new: str, draft: Draft, threshold: float = 0.6) -> list[str]:
    """Sentences of `new` that say what a sentence of the draft already says: most of their words are shared (a
    near-duplicate; run r5 re-inserted a draft's first sentence with its placeholder filled in)."""
    from src.summarize.refine.draft import split_sentences

    found = []
    for sentence in split_sentences(new):
        mine = _words(sentence)
        for old in draft.sentences:
            theirs = _words(old.text)
            if mine and theirs and len(mine & theirs) / min(len(mine), len(theirs)) >= threshold:
                found.append(f"repeats {old.id}: {old.text[:60]!r}")
                break
    return found


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
