"""The gate on everything a model writes into a summary: does the ruling (or the old sentence) say it?

A narrow natural-language-inference question, asked of Apertus as a one-token Ja/Nein reading: text A is the ruling
sentence an edit rests on (or the sentence it rewrites), text B the new sentence. The answer is P(Ja) from the first
token's log-probabilities, and an edit passes only above THRESHOLD. Measured on run r2 (28 Nov): re-asking Apertus
to search the whole ruling for a new sentence let through rewrites that added a condition the court never set;
the judge failed F2 on five of them. Apertus is yes-biased (docs/LESSONS.md), hence the high bar; the value of
every reading is stored in the trace, so the bar can be measured and moved.
"""

from __future__ import annotations

from src.summarize.refine import evidence
from src.summarize.refine.model import Model, ModelFailed

VERSION = "entail@1"
THRESHOLD = 0.9

SYSTEM = (
    "Du vergleichst zwei Texte zu einem Urteil des Schweizerischen Bundesgerichts. Text B kann deutsch oder "
    "französisch sein. Du antwortest mit einem Wort: Ja oder Nein."
)
QUESTION = (
    "Text A:\n<a>\n{premise}\n</a>\n\nText B:\n<b>\n{hypothesis}\n</b>\n\n"
    "Sagt Text A alles, was Text B sagt, mit derselben Bedeutung und derselben Stärke, ohne dass Text B eine "
    "Bedingung, Einschränkung, Tatsache, Zahl oder Wertung hinzufügt, die nicht in Text A steht? "
    "Antworte nur mit Ja oder Nein."
)


MAX_PREMISE = 8000  # characters; a longer premise is not read (G4: never cut silently; a4a1504 cut it to 8000)


def p_entails(premise: str, hypothesis: str, model: Model, tag: str) -> float:
    if len(premise) > MAX_PREMISE:
        raise ModelFailed(f"premise over {MAX_PREMISE} characters ({len(premise)}): not read, never cut")
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": QUESTION.format(premise=evidence.as_data(premise),
                                                    hypothesis=evidence.as_data(hypothesis))},
    ]  # fmt: skip
    return model.p_yes(messages, f"{VERSION}/{tag}")


def gate(premise: str | None, hypothesis: str, model: Model, tag: str) -> tuple[list[str], float | None]:
    """([] if the premise says the hypothesis, else the reason), and the reading."""
    if not premise:
        return ["no ruling text to check the new sentence against"], None
    value = p_entails(premise, hypothesis, model, tag)
    if value < THRESHOLD:
        return [f"entailment {value:.2f} below {THRESHOLD}: the source does not say this"], value
    return [], value
