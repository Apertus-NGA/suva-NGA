"""Step `language` (T2, T3): idiomatic Swiss legal German or French, in a digest's impersonal register.

Code finds what it can (an anonymisation placeholder, a sentence in another language). Apertus lists up to
MAX_FIX more sentences a native Swiss legal writer would rewrite, naming the kind of problem and the span. Repair:
one call per sentence. Code keeps the new wording only if it is in the fiche's language, keeps every article,
consideration reference and number exactly, keeps the meaning's length (0.6 to 1.5 times), and leaves no
placeholder.
"""

from __future__ import annotations

import re

from src.summarize.refine import checks, entail
from src.summarize.refine.draft import Draft, Patch
from src.summarize.refine.model import STRING, array, enum, obj
from src.summarize.refine.step import Candidate, Context, Step
from src.summarize.refine.steps.common import NAME, editable, guarded, polish, terms_hint

VERSION = "language@4"
MAX_FIX = 3
PROBLEMS = ["grammar", "calque_or_foreign_word", "wrong_word", "not_impersonal_register", "placeholder", "clumsy"]

SYSTEM = (
    "You are a Swiss legal editor who writes {lang} natively. You edit case-law digests of the Federal Supreme "
    "Court for an accident insurer: impersonal, neutral, declarative. You never add or remove content."
)
DETECT = (
    "Summary, one sentence per line:\n<summary>\n{summary}\n</summary>\n\n"
    "List the sentences a native Swiss legal writer of {lang} would rewrite, at most {max}: a grammar error, a "
    "calque or a word from another language, a wrong word, a personal or non-neutral register, an anonymisation "
    "placeholder (like A.________), or clearly clumsy wording. Most sentences are fine; list only clear problems. "
    "An empty list is a correct answer.\n- a_sentence: the id;\n- b_problem: the kind;\n- c_span: the words at "
    "fault, exactly as written."
)
REPAIR = (
    "Rewrite this sentence of a {lang} case-law digest. Problem: {problem} ('{span}').\n<sentence>\n{sentence}\n"
    "</sentence>\nKeep the same content, the same articles, consideration references and numbers, character for "
    "character. Write natural Swiss legal {lang}{spelling}. Replace an anonymisation placeholder (A.________) by "
    "the role this person has in this sentence ({roles}); never give a person someone else's role.\n"
    "- a_sentence: the rewritten sentence."
)
_ROLES = {
    "de": "der Versicherte, die Beschwerdeführerin, der Gutachter, die Ärztin, der Arbeitgeber",
    "fr": "l'assuré, la recourante, l'expert, le médecin, l'employeur",
}
_SPELLING = {"de": " (Swiss spelling: ss, never ß)", "fr": ""}
_PLACEHOLDER = re.compile(checks.PLACEHOLDER)


class Language(Step):
    id, version, kind = "language", VERSION, "model"

    def propose(self, draft: Draft, ctx: Context) -> list[Candidate]:
        ids = editable(draft)
        if not ids:
            return []
        lang = NAME[ctx.language]
        flagged: dict[str, tuple[str, str]] = {}
        for sentence in draft.sentences:
            if sentence.locked:
                continue
            if match := _PLACEHOLDER.search(sentence.text):
                flagged[sentence.id] = ("placeholder", match.group(0))
            elif (found := checks.language_of(sentence.text)) and found != ctx.language:
                flagged[sentence.id] = ("calque_or_foreign_word", f"written in {NAME.get(found, found)}")
        item = obj({"a_sentence": enum(ids), "b_problem": enum(PROBLEMS), "c_span": STRING})
        messages = [
            {"role": "system", "content": SYSTEM.format(lang=lang)},
            {"role": "user", "content": DETECT.format(summary=draft.numbered(), lang=lang, max=MAX_FIX)},
        ]
        answer = ctx.model.ask(messages, "language", obj({"items": array(item, MAX_FIX)}), f"{VERSION}/detect", 400)
        for entry in answer["items"]:
            span = entry["c_span"].strip()
            if entry["a_sentence"] not in flagged and span and span in draft.get(entry["a_sentence"]).text:
                flagged[entry["a_sentence"]] = (entry["b_problem"], span)
        return [self._repair(draft.get(sid).text, problem, span, ctx) for sid, (problem, span) in
                list(flagged.items())[:MAX_FIX]]  # fmt: skip

    def _repair(self, sentence: str, problem: str, span: str, ctx: Context) -> Candidate:
        lang = NAME[ctx.language]
        prompt = REPAIR.format(lang=lang, problem=problem.replace("_", " "), span=span, sentence=sentence,
                               spelling=_SPELLING[ctx.language], roles=_ROLES[ctx.language])  # fmt: skip
        prompt += terms_hint(ctx)
        messages = [{"role": "system", "content": SYSTEM.format(lang=lang)}, {"role": "user", "content": prompt}]
        new = ctx.model.ask(messages, "rewrite", obj({"a_sentence": STRING}), f"{VERSION}/repair", 400)["a_sentence"]
        new = polish(new, ctx)
        detail: dict = {}

        def check(before: Draft, after: Draft) -> list[str]:
            problems = checks.same_identifiers(new, sentence)
            found = checks.language_of(new)
            if found is not None and found != ctx.language:
                problems.append(f"written in {found}")
            ratio = len(new) / max(1, len(sentence))
            if not 0.6 <= ratio <= 1.5:
                problems.append(f"length changed by a factor {ratio:.2f}")
            if _PLACEHOLDER.search(new):
                problems.append("placeholder left")
            if ctx.language == "de" and "ß" in new:
                problems.append("ß")
            if checks.restates_outcome(new) and not checks.restates_outcome(sentence):
                problems.append("states the outcome")
            if problems:
                return problems
            # A rewording must not change what the sentence says (run r1: one 'clumsy' fix added a condition the
            # court never set): the old sentence must say everything the new one says. For a placeholder the role
            # comes from the ruling, so the facts of the ruling are given as well.
            premise = sentence if problem != "placeholder" else f"{ctx.parts.get('facts', '')}\n\n{sentence}"
            gated, value = entail.gate(premise, new, ctx.model, "language")
            detail["entailment"] = value
            return gated

        return Candidate(
            f"{problem}: {span}", sentence, patch=Patch("replace", "s0", new), verify=guarded(check), detail=detail
        )
