# ruff: noqa: E501  (prompt texts are kept on one line each, as in reading_prompts.py)
"""Apertus as a feature extractor (experiment): which legal question a ruling decides, as a forced choice.

Why a forced choice: on yes/no questions such as "does this point also apply in accident insurance?" Apertus
answers yes to almost everything (research sprint, 27 Nov: median P(Ja) 0.998). Here it picks one topic letter;
the probabilities over the letters are read from the first token (``max_tokens`` 1, ``top_logprobs`` 20) and code
maps each topic to a group with a table fixed before measuring (``GROUPS``), from Suva's rubric: a disability
ruling is picked when the point it decides also holds in accident insurance.

Apertus only chooses a letter from the list (G1); a failed call or an answer outside the list gives ``None``,
never a negative (D-021 point 7). Calls go through the shared client ``src/llm/`` (G2).
"""

from __future__ import annotations

import math
from typing import Any

from src.triage import reading_prompts as p

VERSION = "topic@1"

TOPICS: dict[str, str] = {
    "A": "Beweiswürdigung im Einzelfall: Gesundheitszustand, Arbeitsfähigkeit oder Kausalität anhand der Arztberichte dieses Falls",
    "B": "Invaliditätsbemessung als Rechtsfrage: Einkommensvergleich, Validen- oder Invalideneinkommen, Tabellenlohn, Leidensabzug",
    "C": "Anforderungen an medizinische Gutachten: Form, Verfahren, Mitwirkung oder Beweiswert als Rechtsfrage",
    "D": "Revision, Neuanmeldung, Wiedererwägung oder Rückkommen auf eine laufende Leistung",
    "E": "Rückerstattung, Verrechnung, Nachzahlung oder Auszahlung an Dritte",
    "F": "Hilflosenentschädigung, Pflege- oder Betreuungsleistungen",
    "G": "Leistung, die es nur in der Invalidenversicherung gibt: berufliche Eingliederung, Hilfsmittel, medizinische Massnahmen der IV, IV-Taggeld",
    "H": "Verfahrensfrage: Eintreten, Fristen, Kosten, unentgeltliche Rechtspflege, rechtliches Gehör",
    "I": "Unfallbegriff, Unfallkausalität oder eine Leistung der Unfall- oder Militärversicherung",
    "J": "Etwas anderes",
}
# Fixed before measuring (28 Nov 2026), from src/triage/reading_prompts.RUBRIC.
GROUPS: dict[str, tuple[str, ...]] = {
    "shared": ("B", "C", "D", "E", "F"),  # points that hold in accident insurance too
    "medical": ("A",),
    "iv_only": ("G",),
    "procedure": ("H",),
    "accident": ("I",),
}

SYSTEM = p.SYS_L
QUESTION = (
    "Welche Rechtsfrage entscheidet das Bundesgericht in diesem Urteil hauptsächlich? Massgebend ist die Frage, "
    "die das Ergebnis trägt, nicht die Leistung, um die es insgesamt geht.\n"
    + "\n".join(f"{k} = {v}" for k, v in TOPICS.items())
    + "\n\nAntworte nur mit einem Buchstaben von A bis J."
)


def build_messages(ruling_text: str) -> list[dict[str, str]]:
    """The ruling first (header, facts, reasoning, operative part, delimited as data), the question last."""
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"{p.doc(p.sections(ruling_text))}\n\n{QUESTION}"},
    ]


def letter_probabilities(logprobs: dict[str, Any] | None) -> dict[str, float] | None:
    """Probabilities over the topic letters, normalised over the letters seen; None when no letter is among them."""
    if not logprobs or not logprobs.get("content"):
        return None
    mass = dict.fromkeys(TOPICS, 0.0)
    for alt in logprobs["content"][0].get("top_logprobs", []):
        token = alt["token"].strip().strip(".:)(\"'*").upper()
        if token in mass:
            mass[token] += math.exp(alt["logprob"])
    total = sum(mass.values())
    return {k: v / total for k, v in mass.items()} if total > 0 else None


def group_features(probs: dict[str, float] | None) -> dict[str, float | None]:
    """``f_topic_<group>`` = probability of the group's letters; all None when there is no answer."""
    return {f"f_topic_{g}": (sum(probs[k] for k in ks) if probs else None) for g, ks in GROUPS.items()}


def read_topic(client: Any, ruling_text: str, size: str = "large") -> dict[str, Any]:
    """One forced-choice reading. ``answer`` is the most likely letter, or None."""
    try:
        result = client.chat(
            build_messages(ruling_text),
            max_tokens=1,
            size=size,
            prompt_version=VERSION,
            logprobs=True,
            top_logprobs=20,
            first_token_only=True,
        )
    except Exception:  # noqa: BLE001  a failed reading stays empty, never a "no"
        probs = None
    else:
        probs = letter_probabilities(result.logprobs)
    answer = max(probs, key=probs.get) if probs else None  # type: ignore[arg-type]
    return {"answer": answer, **group_features(probs)}
