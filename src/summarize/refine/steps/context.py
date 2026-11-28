"""Step `context` (R1, T4, C2): a summary under Suva's word band gets the facts a reader needs, from the ruling.

Measured on the 24 baseline drafts of the iterate set (28 Nov): none was over the band and 11 were under it; some
had no facts at all ("Am 21. August 2025 hat das Bundesgericht …"). Detect by code: under the band. Repair (one
call): one or two sentences of the facts (the insured event, what the insurer and the lower court decided, what
the appellant claims), pointing at the ruling sentence they rest on; inserted before the first sentence. Code checks
the pointer, the language and the identifiers; the facts step's check (one call) must find the new text "same".
"""

from __future__ import annotations

from src.summarize.refine import checks, evidence
from src.summarize.refine.draft import Draft, Patch
from src.summarize.refine.model import STRING, enum, obj
from src.summarize.refine.step import Candidate, Context, Step
from src.summarize.refine.steps.common import NAME, guarded, polish, repeats, written_sentence_problems
from src.summarize.refine.steps.facts import VERSION as FACTS_VERSION
from src.summarize.refine.steps.facts import judge_sentences

VERSION = "context@4"

TASK = (
    "Task: the {lang} summary below of the ruling above is too short and lacks the facts a lawyer needs to "
    "understand the point. Write one or two sentences in {lang}, in the impersonal register of a case-law digest, "
    "stating only facts the ruling states: the insured event, what the insurer decided, what the lower court "
    "decided, what the appellant claims. Never say how the Federal Supreme Court decided (the summary's last "
    "sentence does). No medical detail, no names (say 'der Versicherte', 'l'assuré', the insurer as the ruling "
    "names it), no point already in the summary.\n"
    "- a_label, b_opening: the passage and the first eight to twelve words of the ruling sentence the new text "
    "rests on most, exactly;\n- c_text: the new sentences, in {lang}.\n\n<summary>\n{summary}\n</summary>"
)


class ContextStep(Step):
    id, version, kind = "context", VERSION, "model"

    def propose(self, draft: Draft, ctx: Context) -> list[Candidate]:
        low, _ = checks.LENGTH_BAND[ctx.language]
        if draft.words() >= low or not draft.sentences:
            return []
        task = TASK.format(lang=NAME[ctx.language], summary=draft.numbered())
        facts_labels = [label for label in ctx.parts if label in ("facts", "text")] or list(ctx.parts)
        shape = obj({"a_label": enum(facts_labels), "b_opening": STRING, "c_text": STRING})
        answer = ctx.model.ask(evidence.messages(ctx.parts, task), "context", shape, VERSION, max_tokens=400)
        found = evidence.find(answer["b_opening"], ctx.parts, answer["a_label"], 2)
        text = polish(answer["c_text"], ctx)
        first = draft.sentences[0].text

        def check(before: Draft, after: Draft) -> list[str]:
            # The pointer is evidence when code finds it; the gate is the facts check below (a sentence that sums up
            # two facts rarely has one ruling sentence it opens with: run r4 lost 8 of 13 additions to that).
            problems = written_sentence_problems(text, "", ctx, max_words=90) + repeats(text, before)
            if "____" in text:
                problems.append("placeholder")
            if problems:
                return problems
            target = next((s.id for s in after.sentences if s.text == text), None)
            verdict = judge_sentences(after, [target], ctx, f"{FACTS_VERSION}/recheck").get(target, {}).get("verdict")
            return [] if verdict == "same" else [f"re-check: {verdict or 'unchecked'}"]

        return [
            Candidate(
                f"under {low} words: facts added from the ruling", first, found[0] if found else None,
                found[1] if found else None, Patch("insert_before", "s0", text), guarded(check),
            )
        ]  # fmt: skip
