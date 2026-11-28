"""Step `terms` (T1): every legal term in the established Swiss form of the fiche's language.

Code first: a term of the other language from the project glossary (src/summarize/v2/glossary.json) is replaced by
its counterpart, with no model. Then Apertus lists up to MAX_TERMS terms it would change, each with the exact span
and a replacement. Code keeps a replacement only if the span is in the sentence and the replacement is attested:
it appears in the glossary, in the ruling when the ruling is written in the fiche's language, or in Suva's own
summaries in that language (`Context.lexicon`). Apertus proposes; an attested Swiss term decides.
"""

from __future__ import annotations

import re

from src.summarize.refine.checks import mentions
from src.summarize.refine.draft import Draft, Patch
from src.summarize.refine.model import STRING, array, enum, obj
from src.summarize.refine.step import Candidate, Context, Step
from src.summarize.refine.steps.common import NAME, editable
from src.summarize.v2.prompts import GLOSSARY

VERSION = "terms@1"
MAX_TERMS = 4
REASONS = ["other_language", "not_swiss_usage", "wrong_legal_concept", "imprecise"]

SYSTEM = (
    "You are a Swiss legal editor. You check that a {lang} case-law summary uses the established Swiss legal term "
    "of {lang} for every legal notion (as the Federal Supreme Court and Swiss insurers write it). You answer only "
    "about the summary given."
)
DETECT = (
    "Summary, one sentence per line:\n<summary>\n{summary}\n</summary>\n\n"
    "List the terms of art that a Swiss legal editor would change, at most {max}. Most summaries need none or one "
    "change; an empty list is a correct answer. For each:\n"
    "- a_sentence: the sentence id;\n- b_span: the term exactly as written in that sentence (one to four words);\n"
    "- c_replacement: the established Swiss {lang} term;\n- d_reason: why."
)


def pairs(category: str) -> list[dict]:
    rows = []
    for key in ("common", category):
        for kind in ("phrases", "laws"):
            rows += GLOSSARY.get(key, {}).get(kind, [])
    return [r for r in rows if r.get("de") and r.get("fr")]


def glossary_text(language: str, category: str) -> str:
    return "\n".join(row[language] for row in pairs(category))


class Terms(Step):
    id, version, kind = "terms", VERSION, "model"

    def propose(self, draft: Draft, ctx: Context) -> list[Candidate]:
        fixes = self._glossary(draft, ctx)
        local = draft  # the model reads the summary with the glossary fixes in, so its spans match after them
        for fix in fixes:
            local = local.apply(fix.patch)
        return fixes + self._model(local, ctx)

    def _glossary(self, draft: Draft, ctx: Context) -> list[Candidate]:
        other = "fr" if ctx.language == "de" else "de"
        out = []
        for sentence in draft.sentences:
            if sentence.locked:
                continue
            for row in pairs(ctx.category):
                foreign, own = row[other], row[ctx.language]
                if foreign.lower() == own.lower() or len(foreign) < 5:
                    continue
                match = re.search(rf"(?<!\w){re.escape(foreign)}(?!\w)", sentence.text, re.IGNORECASE)
                if match:
                    out.append(Candidate(f"glossary: {foreign} -> {own}", sentence.text,
                                         patch=Patch("replace", sentence.id, own, span=match.group(0))))  # fmt: skip
                    break
        return out

    def _model(self, draft: Draft, ctx: Context) -> list[Candidate]:
        ids = editable(draft)
        if not ids:
            return []
        lang = NAME[ctx.language]
        item = obj({"a_sentence": enum(ids), "b_span": STRING, "c_replacement": STRING, "d_reason": enum(REASONS)})
        shape = obj({"items": array(item, MAX_TERMS)})
        messages = [
            {"role": "system", "content": SYSTEM.format(lang=lang)},
            {"role": "user", "content": DETECT.format(summary=draft.numbered(), max=MAX_TERMS, lang=lang)},
        ]
        answer = ctx.model.ask(messages, "terms", shape, f"{VERSION}/{ctx.language}", max_tokens=500)
        attested = "\n".join([ctx.lexicon, glossary_text(ctx.language, ctx.category)])
        if ctx.ruling_language == ctx.language:
            attested += "\n" + ctx.source
        out = []
        for entry in answer["items"][:MAX_TERMS]:
            sentence = draft.get(entry["a_sentence"]).text
            span, new = entry["b_span"].strip(), entry["c_replacement"].strip()
            reason = f"{entry['d_reason']}: {span} -> {new}"
            if not span or span not in sentence or span.lower() == new.lower():
                continue  # an answer that names no real span is not a finding
            problems = [] if mentions(attested, new) else ["replacement not attested in the glossary, the ruling "
                                                           "or Suva's summaries"]  # fmt: skip
            out.append(Candidate(reason, sentence, patch=Patch("replace", "s0", new, span=span),
                                 verify=lambda b, a, p=problems: p))  # fmt: skip
        return out
