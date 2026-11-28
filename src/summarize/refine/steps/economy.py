"""Step `economy` (T4): each point stated once. The outcome sentence is written by code (finish.py); a sentence
that restates the outcome as well ("Das Bundesgericht hat die Beschwerde teilweise gutgeheissen und …") says it
twice.

Detect by code: an editable sentence that states the appeal's outcome while the code-written outcome sentence is
there. Repair (one call per sentence): the sentence without the outcome, or delete it when nothing else is in it.
Code keeps the new wording only if it no longer states the outcome, is in the fiche's language, and adds no
identifier.
"""

from __future__ import annotations

import re

from src.summarize.refine import checks
from src.summarize.refine.draft import Draft, Patch
from src.summarize.refine.model import STRING, enum, obj
from src.summarize.refine.step import Candidate, Context, Step
from src.summarize.refine.steps.common import NAME

VERSION = "economy@1"
MAX_FIX = 2

# Wider than finish._STATES_OUTCOME: any sentence telling how the appeal ended, in either word order.
_OUTCOME = re.compile(
    r"(?:Beschwerde|Rechtsmittel)\b[^.]{0,120}?\b(?:abgewiesen|gutgeheissen|abzuweisen|gutzuheissen|nicht eingetreten)"
    r"|(?:weist|wies|heisst|hiess)\b[^.]{0,60}?\bBeschwerde\b"
    r"|\brecours\b[^.]{0,120}?\b(?:rejet[ée]|admis|rejette|irrecevable)"
    r"|\b(?:rejette|rejeta|admet|admit)\b[^.]{0,60}?\brecours\b",
    re.IGNORECASE,
)
PROMPT = (
    "In this {lang} case-law summary the outcome of the appeal is already stated by the last sentence:\n"
    '"{outcome}"\nThis other sentence states the outcome too:\n<sentence>\n{sentence}\n</sentence>\n'
    "Rewrite it in {lang} without the outcome, keeping everything else it says (the reason, the rule, the facts), or "
    "answer 'delete' if nothing else is in it.\n- a_action: 'rewrite' or 'delete';\n- b_sentence: the new sentence "
    "(empty for delete)."
)


def restates(text: str) -> bool:
    return bool(_OUTCOME.search(text))


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
        prompt = PROMPT.format(lang=lang, outcome=outcome, sentence=sentence)
        answer = ctx.model.ask([{"role": "user", "content": prompt}], "economy", shape, VERSION, max_tokens=300)
        if answer["a_action"] == "delete":
            return Candidate("outcome stated twice: sentence deleted", sentence, patch=Patch("delete", "s0"))
        new = " ".join(answer["b_sentence"].split())

        def check(before: Draft, after: Draft) -> list[str]:
            problems = ["still states the outcome"] if restates(new) else []
            found = checks.language_of(new)
            if found is not None and found != ctx.language:
                problems.append(f"written in {found}")
            problems += checks.new_identifiers(new, sentence, ctx.source)
            if len(new) > len(sentence):
                problems.append("longer than before")
            return problems

        return Candidate("outcome stated twice: restatement removed", sentence, patch=Patch("replace", "s0", new),
                         verify=check)  # fmt: skip
