"""Step `length` (T4): inside the word band of Suva's summaries for the fiche's language.

Only a summary over the band is changed. Apertus ranks the sentences a reader would miss least (ids from a closed
list; the outcome and the closing note are never offered, nor the sentence the holding step relies on when the
record names it). Code deletes them in that order and stops as soon as the summary is inside the band. A summary
under the band is left as it is: adding content to reach a length would invent it.
"""

from __future__ import annotations

from src.summarize.refine import checks
from src.summarize.refine.draft import Draft, Patch
from src.summarize.refine.model import array, enum, obj
from src.summarize.refine.step import Candidate, Context, Step
from src.summarize.refine.steps.common import NAME, editable

VERSION = "length@1"

PROMPT = (
    "This {lang} case-law summary has {words} words; Suva's summaries have at most {high}. List the sentence ids a "
    "lawyer would miss least, least important first: repeated points, procedural history, details of the facts "
    "that the rule does not need. Never list the sentence that states the court's rule or its answer.\n"
    "<summary>\n{summary}\n</summary>"
)


class Length(Step):
    id, version, kind = "length", VERSION, "model"

    def propose(self, draft: Draft, ctx: Context) -> list[Candidate]:
        low, high = checks.LENGTH_BAND[ctx.language]
        words = draft.words()
        ids = editable(draft)
        if words <= high or len(ids) < 2:
            return []
        shape = obj({"a_least_important": array(enum(ids))})
        prompt = PROMPT.format(lang=NAME[ctx.language], words=words, high=high, summary=draft.numbered())
        answer = ctx.model.ask([{"role": "user", "content": prompt}], "length", shape, VERSION, max_tokens=120)
        out, remaining = [], words
        for sid in dict.fromkeys(answer["a_least_important"]):
            if remaining <= high:
                break
            sentence = draft.get(sid).text
            if remaining - len(sentence.split()) < low:
                continue
            remaining -= len(sentence.split())
            out.append(Candidate(f"over {high} words: least important sentence dropped", sentence,
                                 patch=Patch("delete", sid)))  # fmt: skip
        return out
