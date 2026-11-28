"""Step `economy` (T4): each point stated once. The outcome sentence is written by code (finish.py); a sentence
that restates the outcome as well ("Das Bundesgericht hat die Beschwerde teilweise gutgeheissen und …") says it
twice.

Detect by code: an editable sentence that states the appeal's outcome while the code-written outcome sentence is
there. Repair (one call per sentence): the sentence without the outcome, or delete it when nothing else is in it.
Code keeps the new wording only if it no longer states the outcome, is in the fiche's language, and adds no
identifier.
"""

from __future__ import annotations

from src.summarize.refine import checks, entail
from src.summarize.refine.draft import Draft, Patch
from src.summarize.refine.model import STRING, enum, obj
from src.summarize.refine.step import Candidate, Context, Step
from src.summarize.refine.steps.common import NAME, guarded, new_terms, polish, terms_hint

VERSION = "economy@3"
MAX_FIX = 2

PROMPT = (
    "In this {lang} case-law summary the outcome of the appeal is already stated by the last sentence:\n"
    '"{outcome}"\nThis other sentence states the outcome too:\n<sentence>\n{sentence}\n</sentence>\n'
    "Rewrite it in {lang} without the outcome, keeping everything else it says (the reason, the rule, the facts), or "
    "answer 'delete' if nothing else is in it.\n- a_action: 'rewrite' or 'delete';\n- b_sentence: the new sentence "
    "(empty for delete)."
)


restates = checks.restates_outcome


class Economy(Step):
    id, version, kind = "economy", VERSION, "model"

    def propose(self, draft: Draft, ctx: Context) -> list[Candidate]:
        outcome = next((s.text for s in draft.sentences if s.locked and restates(s.text)), None)
        if outcome is None:
            return []
        flagged = [s for s in draft.sentences if not s.locked and restates(s.text)][:MAX_FIX]
        return [self._repair(s.text, outcome, ctx) for s in flagged]

    def _repair(self, sentence: str, outcome: str, ctx: Context) -> Candidate:
        lang = NAME[ctx.language]
        shape = obj({"a_action": enum(["rewrite", "delete"]), "b_sentence": STRING})
        prompt = PROMPT.format(lang=lang, outcome=outcome, sentence=sentence) + terms_hint(ctx)
        answer = ctx.model.ask([{"role": "user", "content": prompt}], "economy", shape, VERSION, max_tokens=300)
        if answer["a_action"] == "delete":
            return Candidate("outcome stated twice: sentence deleted", sentence, patch=Patch("delete", "s0"))
        new = polish(answer["b_sentence"], ctx)

        def check(before: Draft, after: Draft) -> list[str]:
            problems = ["still states the outcome"] if restates(new) else []
            found = checks.language_of(new)
            if found is not None and found != ctx.language:
                problems.append(f"written in {found}")
            problems += checks.new_identifiers(new, sentence, ctx.source) + new_terms(new, sentence, ctx)
            if len(new) > len(sentence):
                problems.append("longer than before")
            if problems:
                return problems
            gated, value = entail.gate(sentence, new, ctx.model, "economy")
            detail["entailment"] = value
            return gated

        detail: dict = {}
        return Candidate("outcome stated twice: restatement removed", sentence, patch=Patch("replace", "s0", new),
                         verify=guarded(check), detail=detail)  # fmt: skip
