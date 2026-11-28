"""Step `facts` (F1, F2): every sentence must be backed by a sentence of the ruling, with the same content and
strength.

Detect (one call): for each summary sentence, Apertus names the passage and the opening words of the ruling's
sentence that states it, and says whether the summary says the same, more, or something the ruling does not say.
Code finds that sentence and copies it as the evidence. A sentence is flagged only when the model says it is not
the same; a "same" whose sentence code cannot find is recorded, not flagged.
Repair (one call per flagged sentence, at most MAX_FIX): rewrite that sentence from a ruling sentence Apertus
points at, or delete it. Code checks the pointer, the language and the identifiers; then one re-check call must
find the new sentence "same".
"""

from __future__ import annotations

import re

from src.summarize.refine import evidence
from src.summarize.refine.draft import Draft, Patch
from src.summarize.refine.model import STRING, array, enum, obj
from src.summarize.refine.step import Candidate, Context, Step
from src.summarize.refine.steps.common import NAME, editable, guarded, polish, written_sentence_problems

VERSION = "facts@5"
MAX_FIX = 3
VERDICTS = ["same", "stronger_or_broader", "different", "not_in_ruling"]

DETECT = (
    "Task: check the summary below against the ruling above, sentence by sentence. Be strict: a summary sentence "
    "is 'same' only if a sentence of the ruling states it with the same content and the same strength.\n"
    "For every sentence of the summary below, in order:\n"
    "- a_sentence: its id;\n"
    "- b_label: the label of the passage of the ruling that states it best ('none' if no passage does);\n"
    "- c_opening: the first eight to twelve words of the ruling sentence that states it, exactly;\n"
    "- d_verdict: 'same' if that ruling sentence says what the summary sentence says; 'stronger_or_broader' if the "
    "summary states it more firmly, more generally, or adds a detail; 'different' if the ruling says something "
    "else (other facts, other numbers, the reverse); 'not_in_ruling' if no passage states it.\n"
    "Do not assume the summary is correct: summaries of this kind often contain one sentence that overstates or "
    "invents something. Facts are checked against the facts; statements of law against the considerations."
)
REPAIR = (
    "Task: this sentence of a {lang} summary is not backed by the ruling ({verdict}):\n"
    "<sentence>\n{sentence}\n</sentence>\n"
    "{hint}"
    "Rewrite it in {lang} so that it states only what the ruling says, keeping its place and its point in the "
    "summary{delete}.\n"
    "- a_label, b_opening: the passage and the first eight to twelve words of the ruling sentence the new sentence "
    "rests on, exactly;\n- c_action: 'rewrite' or 'delete';\n"
    "- d_sentence: the new sentence in {lang} (empty for delete). One sentence, plain prose, the established Swiss "
    "legal terms of {lang}, no article or number that is not in that ruling sentence."
)


# Suva is the accident insurer of these summaries' readers, so the generator tends to name it for any insurer. When
# the ruling names none of Suva's names, a sentence that does is wrong on its face: code flags it, no model needed.
_SUVA = {"de": re.compile(r"\bSuva\b"), "fr": re.compile(r"\b(?:CNA|Suva)\b")}
_SUVA_IN_RULING = re.compile(
    r"\b(?:Suva|CNA|INSAI|Schweizerische Unfallversicherungsanstalt|Caisse nationale suisse)", re.IGNORECASE
)


def code_flags(draft: Draft, ctx: Context) -> dict[str, dict]:
    if _SUVA_IN_RULING.search(ctx.source):
        return {}
    return {
        s.id: {"verdict": "different", "label": None, "quote": None, "verified": False, "by": "code",
               "hint": "The ruling's insurer is not Suva: name the insurer by its role (the accident insurer, "
                       "l'assureur-accidents) or as the ruling names it.\n"}
        for s in draft.sentences
        if not s.locked and _SUVA[ctx.language].search(s.text)
    }  # fmt: skip


def _summary_block(draft: Draft, ids: list[str]) -> str:
    return "\n".join(f"[{s.id}] {s.text}" for s in draft.sentences if s.id in ids)


def judge_sentences(draft: Draft, ids: list[str], ctx: Context, version: str) -> dict[str, dict]:
    """Sentence id -> {"label", "quote", "verdict", "verified"} from one call."""
    labels = list(ctx.parts)
    item = obj(
        {"a_sentence": enum(ids), "b_label": enum([*labels, "none"]), "c_opening": STRING, "d_verdict": enum(VERDICTS)}
    )
    messages = evidence.messages(ctx.parts, f"{DETECT}\n\n<summary>\n{_summary_block(draft, ids)}\n</summary>")
    answer = ctx.model.ask(messages, "sentence_support", obj({"items": array(item)}), version, max_tokens=1200)
    out: dict[str, dict] = {}
    for entry in answer["items"]:
        found = evidence.find(entry["c_opening"], ctx.parts, entry["b_label"])
        out.setdefault(
            entry["a_sentence"],
            {"label": found[0] if found else entry["b_label"], "quote": found[1] if found else None,
             "verdict": entry["d_verdict"], "verified": found is not None},
        )  # fmt: skip
    return out


class Facts(Step):
    id, version, kind = "facts", VERSION, "model"
    allow = ("length_out_of_band",)  # deleting an invented sentence may make a fiche short; faithfulness comes first

    def propose(self, draft: Draft, ctx: Context) -> list[Candidate]:
        ids = editable(draft)
        if not ids:
            return []
        verdicts = {**judge_sentences(draft, ids, ctx, f"{VERSION}/detect"), **code_flags(draft, ctx)}
        flagged = [(sid, v) for sid, v in verdicts.items() if v["verdict"] != "same" and sid in ids][:MAX_FIX]
        return [self._repair(draft.get(sid).text, verdict, ctx) for sid, verdict in flagged]

    def _repair(self, sentence: str, verdict: dict, ctx: Context) -> Candidate:
        lang = NAME[ctx.language]
        shape = obj(
            {"a_label": enum(list(ctx.parts)), "b_opening": STRING, "c_action": enum(["rewrite", "delete"]),
             "d_sentence": STRING}
        )  # fmt: skip
        # A sentence that says too much or the wrong thing is corrected, never dropped: dropping loses its point.
        # Only a sentence the ruling does not state at all may be deleted, and only after a second call agrees.
        may_delete = verdict["verdict"] == "not_in_ruling"
        actions = ["rewrite", "delete"] if may_delete else ["rewrite"]
        shape["properties"]["c_action"] = enum(actions)
        delete = ", or delete it if the ruling does not state it at all" if may_delete else ""
        task = REPAIR.format(lang=lang, verdict=verdict["verdict"].replace("_", " "), sentence=sentence,
                             hint=verdict.get("hint", ""), delete=delete)  # fmt: skip
        messages = evidence.messages(ctx.parts, task)
        answer = ctx.model.ask(messages, "sentence_repair", shape, f"{VERSION}/repair", max_tokens=400)
        detail = {"verdict": verdict["verdict"], "detected_evidence_found": verdict["verified"],
                  "detected_by": verdict.get("by", "model")}  # fmt: skip
        if answer["c_action"] == "delete":

            def confirm(before: Draft, after: Draft) -> list[str]:
                sid = next((s.id for s in before.sentences if s.text == sentence), None)
                second = judge_sentences(before, [sid], ctx, f"{VERSION}/confirm").get(sid, {}).get("verdict")
                return [] if second == "not_in_ruling" else [f"second reading: {second or 'unchecked'}, not deleted"]

            return Candidate(
                "not in the ruling: deleted", sentence, verdict["label"], verdict["quote"], Patch("delete", "s0"),
                guarded(confirm), detail,
            )  # fmt: skip
        found = evidence.find(answer["b_opening"], ctx.parts, answer["a_label"])
        new = polish(answer["d_sentence"], ctx)

        def check(before: Draft, after: Draft) -> list[str]:
            problems = [] if found else ["the ruling sentence the repair rests on was not found"]
            problems += written_sentence_problems(new, sentence, ctx)
            if problems:
                return problems
            target = next((s.id for s in after.sentences if s.text == new), None)
            if target is None:
                return ["the new sentence is not in the result"]
            again = judge_sentences(after, [target], ctx, f"{VERSION}/recheck")
            if again.get(target, {}).get("verdict") != "same":
                return [f"re-check: still {again.get(target, {}).get('verdict', 'unchecked')}"]
            if code_flags(after, ctx).get(target):
                return ["still names Suva, which the ruling does not"]
            return []

        return Candidate(
            f"not backed by the ruling ({verdict['verdict']}): rewritten", sentence,
            found[0] if found else None, found[1] if found else None, Patch("replace", "s0", new), guarded(check),
            detail,
        )  # fmt: skip
