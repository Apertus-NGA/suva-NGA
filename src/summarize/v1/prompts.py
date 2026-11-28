"""v1. One glossary for every ruling, one prompt.

This is the prompt of the 27 November measurement. v2, per matter, is in
src/summarize/v2/. This module is no longer called.
"""

from __future__ import annotations

import json
from pathlib import Path

VERSION = "v1"
GLOSSARY = json.loads((Path(__file__).parent / "glossary.json").read_text(encoding="utf-8"))


def glossary_block(language: str) -> str:
    lines = ["Statutes (do not translate the sigil; use the one of the fiche language):"]
    for law in GLOSSARY["laws"]:
        if language == "de":
            lines.append(f"- {law['de']} (French: {law['fr']})")
        else:
            lines.append(f"- {law['fr']} (German: {law['de']})")
    lines.append("Articles: cite the form of the fiche language.")
    for art in GLOSSARY["articles"]:
        lines.append(f"- {art['de']} = {art['fr']}")
    lines.append("Phrases:")
    for phrase in GLOSSARY["phrases"]:
        lines.append(f"- {phrase['de']} = {phrase['fr']}")
    return "\n".join(lines)


def system_prompt(language: str) -> str:
    if language == "de":
        return (
            "Write a Suva fiche in German, in two to four paragraphs, "
            "with no title, no bullet list and no headings. "
            "Paragraph 1: what happened, in one pass, with no medical detail. "
            "Paragraph 2: the rule the Federal Supreme Court states for this case. "
            "Last sentence: the outcome in one sentence. "
            "Do not copy the 'Demnach erkennt' block, the court costs, "
            "the signatures, the place or the date of the copy. "
            "The examples show length and tone only. Their facts and outcomes "
            "belong to other cases. "
            "Cite only articles this ruling applies, in German form "
            "(UVG, ATSG, UVV). Art. 17 ATSG is the revision, not the status quo. "
            "Invent nothing. Answer with the fiche only."
        )
    return (
        "Write a Suva fiche in French, in two to four paragraphs, "
        "with no title, no bullet list and no headings. "
        "Paragraph 1: what happened, in one pass, with no medical detail. "
        "Paragraph 2: the rule the Federal Supreme Court states for this ruling. "
        "Last sentence: the outcome in one sentence, in French. "
        "Do not copy the operative block, the court costs, the signatures or the place. "
        "If there are two events, both belong in the first paragraph. "
        "If the ruling applies Art. 4 ATSG, write art. 4 LPGA. "
        "The examples show length and tone only. "
        "Their facts and outcomes belong to other cases. "
        "Cite only an article this ruling applies, in French form "
        "(LAA, LPGA, OLAA). art. 17 LPGA is the revision, not the status quo. "
        "Invent nothing. Answer with the fiche only."
    )


def user_prompt(language: str, examples: list[dict], target: dict) -> str:
    from src.summarize.summarize import anchors, directions, order_of, outcome_sentence, required_forms

    label = "Merkblatt" if language == "de" else "Fiche"
    chunks = [
        glossary_block(language),
        "",
        "Tone examples only. Do not reuse their facts or their outcome.",
        "",
    ]
    for example in examples:
        chunks.append(f"{label} of another ruling ({example['docket']}):")
        chunks.append(example["body"])
        chunks.append("")
    chunks.append("Ruling to summarise, and only this one:")
    chunks.append(
        f"{target['docket']} of {target['decision_date']}, court {target['division']}, matter {target['area']}."
    )
    chunks.append(target["text"])
    chunks.append("")
    held = anchors(target["text"])
    if held:
        if language == "de":
            chunks.append(
                "Diese Sätze dieses Entscheids gehören in den Text, "
                "in Prosa und mit deutschen Siglen. Nicht weglassen, nicht als Zitatblock anhängen:"
            )
        else:
            chunks.append(
                "These sentences of this ruling belong in the fiche, in French prose, "
                "with the French sigils of the glossary (UVG becomes LAA, ATSG becomes LPGA). "
                "Do not drop them, and do not paste them in German:"
            )
        chunks.append(held)
        chunks.append("")
    forms = required_forms(language, target["text"])
    if forms:
        joined = " ; ".join(forms)
        if language == "de":
            chunks.append(f"Der Text enthält diese Formulierungen, im Satz und nur einmal: {joined}.")
        else:
            chunks.append(f"The text contains these wordings, inside a sentence and only once: {joined}.")
        chunks.append("")
    held_sense = directions(language, target["text"])
    if held_sense:
        if language == "de":
            chunks.append("Richtung, die dieser Entscheid vorgibt. Nicht umkehren:")
        else:
            chunks.append("Direction this ruling imposes. Do not reverse it:")
        chunks.extend(held_sense)
        chunks.append("")
    order = order_of(target["text"])
    if order:
        sentence = outcome_sentence(language, order)
        if language == "de":
            chunks.append(f"Ausgang dieses Entscheids, auf Deutsch, in einem Satz und nur einmal: {sentence}")
        else:
            chunks.append(f"Outcome of this ruling, in French, in one sentence and only once: {sentence}")
        chunks.append("")
    if language == "de":
        chunks.append("Schreibe ausschliesslich Deutsch, auch wenn der Entscheid französisch oder italienisch ist.")
    else:
        chunks.append("Write in French only, even if the ruling is in German or Italian.")
    chunks.append(f"{label} :")
    return "\n".join(chunks)


def repair_prompt(
    language: str,
    draft: str,
    forms: list[str],
    issue: list[str],
    sense: list[str],
) -> str:
    must = " ; ".join(forms)
    wrong = ", ".join(issue)
    way = " ".join(sense)
    if language == "de":
        return (
            "Überarbeite das Merkblatt. Keine Aufzählung, kein kopierter Urteilsblock, "
            "das Dispositiv nur im letzten Satz. "
            f"Zu beheben: {wrong}. "
            f"Richtung: {way} "
            f"Diese Formulierungen müssen im Text stehen: {must}.\n\n"
            f"{draft}"
        )
    return (
        "Rewrite the fiche. No list, no pasted operative block, "
        "the outcome only in the last sentence. "
        f"Fix: {wrong}. "
        f"Direction: {way} "
        f"These wordings must appear in the text: {must}.\n\n"
        f"{draft}"
    )
