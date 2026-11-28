"""Step `form` (code only): citation forms, abbreviations and spelling of the fiche's language; references to
considerations the ruling does not have; Markdown; a repeated sentence. Nothing here needs a model."""

from __future__ import annotations

import re

from src.summarize import finish
from src.summarize.refine.checks import restates_outcome
from src.summarize.refine.draft import Draft, Patch
from src.summarize.refine.step import Candidate, Context, Step

_FORMS = {
    "fr": (
        (r"\bErw\.\s*(?=\d)", "consid. "),
        (r"\bE\.\s*(?=\d)", "consid. "),
        (r"\bAbs\.\s*(?=\d)", "al. "),
        (r"\blit\.\s*(?=[a-z]\b)", "let. "),
        (r"\bBst\.\s*(?=[a-z]\b)", "let. "),
        (r"\bZiff\.\s*(?=\d)", "ch. "),
    ),
    "de": (
        (r"\bconsid\.\s*(?=\d)", "E. "),
        (r"\bal\.\s*(?=\d)", "Abs. "),
        (r"\blet\.\s*(?=[a-z]\b)", "lit. "),
        (r"\bch\.\s*(?=\d)", "Ziff. "),
    ),
}


def fixed(text: str, language: str, source: str) -> str:
    out = finish.own_language_abbreviations(finish.strip_markdown(text), language)
    for pattern, own in _FORMS[language]:
        out = re.sub(pattern, own, out)
    out, _ = finish.real_considerations_only(out, source)
    if language == "de":
        out = out.replace("ß", "ss")
    return " ".join(out.split())


class Form(Step):
    id, version, kind = "form", "2", "code"

    def __init__(self, label: str = "form") -> None:
        self.id = label

    def propose(self, draft: Draft, ctx: Context) -> list[Candidate]:
        out: list[Candidate] = []
        seen: set[str] = set()
        for sentence in draft.sentences:
            key = re.sub(r"\W+", " ", sentence.text.lower()).strip()
            if len(key) > 15 and key in seen and not sentence.locked:
                out.append(Candidate("repeated sentence", sentence.text, patch=Patch("delete", sentence.id)))
                continue
            seen.add(key)
            if sentence.locked:
                continue
            new = fixed(sentence.text, ctx.language, ctx.source)
            if new != sentence.text:
                out.append(
                    Candidate("form of the fiche's language", sentence.text, patch=Patch("replace", sentence.id, new))
                )
        out += self._outcome(draft, ctx)
        return out

    def _outcome(self, draft: Draft, ctx: Context) -> list[Candidate]:
        """The outcome as the code-written last sentence (finish.py) when the draft buries it in another sentence.
        The economy step then takes the restatement out of that sentence."""
        kind = finish.outcome_kind(ctx.source)
        if not kind or any(s.locked and restates_outcome(s.text) for s in draft.sentences):
            return []
        body = [s for s in draft.sentences if not (s.locked and not restates_outcome(s.text))]  # not the note
        if not body:
            return []
        last = body[-1]
        sentence = finish._OUTCOME[kind][ctx.language]
        return [
            Candidate("the outcome as its own last sentence", last.text, patch=Patch("insert_after", last.id, sentence))
        ]
