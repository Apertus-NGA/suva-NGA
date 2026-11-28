"""v2. One prompt and one glossary per matter (src/courts.py).

v1, one glossary for every ruling, is in src/summarize/v1/.
Each fiche receives only the sigils and phrases of its matter, plus the shared
procedural core. The article list is not injected: an article enters the prompt
only when the ruling itself applies it.
"""

from __future__ import annotations

import json
from pathlib import Path

VERSION = "v2"
GLOSSARY = json.loads((Path(__file__).parent / "glossary.json").read_text(encoding="utf-8"))
SOCIAL = frozenset({"uv", "iv", "kv"})
_SUBJECTS = {key: frozenset(block["subjects"]) for key, block in GLOSSARY.items() if key != "common"}

_STYLE = {
    "de": (
        "Write a Suva fiche in German, in two to four paragraphs, "
        "with no title, no bullet list and no headings. "
        "Paragraph 1: what happened, in one pass, with no medical detail. "
        "Paragraph 2: the rule the Federal Supreme Court states for this case. "
        "Last sentence: the outcome in one sentence. "
        "Do not copy the 'Demnach erkennt' block, the court costs, "
        "the signatures, the place or the date of the copy. "
        "The examples show length and tone only. Their facts and outcomes "
        "belong to other cases. "
        "Cite only an article this ruling applies, in the German form of this matter."
    ),
    "fr": (
        "Write a Suva fiche in French, in two to four paragraphs, "
        "with no title, no bullet list and no headings. "
        "Paragraph 1: what happened, in one pass, with no medical detail. "
        "Paragraph 2: the rule the Federal Supreme Court states for this case. "
        "Last sentence: the outcome in one sentence, in French. "
        "Do not copy the operative block, the court costs, the signatures or the place. "
        "The examples show length and tone only. "
        "Their facts and outcomes belong to other cases. "
        "Cite only an article this ruling applies, in the French form of this matter."
    ),
}
_FOCUS = {
    "uv": {
        "de": (
            "Matter: Unfallversicherung. Keep what the ruling says about the UVG benefit: "
            "the notion of accident, natural causation and, only if the ruling examines it, "
            "adequate causation. Art. 6 Abs. 2 UVG is the presumption of cover, "
            "Art. 4 ATSG is natural causation: do not mix them. "
            "Name an IV or KVG rule only when this ruling applies it."
        ),
        "fr": (
            "Matter: assurance-accidents. Keep what the ruling says about the LAA benefit: "
            "the notion of accident, natural causation and, only if the ruling examines it, "
            "adequate causation. art. 6 al. 2 LAA is the presumption of cover, "
            "art. 4 LPGA is natural causation: do not mix them. "
            "Name an AI or LAMal rule only when this ruling applies it."
        ),
    },
    "iv": {
        "de": (
            "Matter: Invalidenversicherung. The question is the pension, the disability rate "
            "or the income under the IVG, not a UVG benefit. "
            "Name the UVG only when the ruling sets the two statutes against each other."
        ),
        "fr": (
            "Matter: assurance-invalidité. The question is the pension, the disability rate "
            "or the income under the LAI, not an LAA benefit. "
            "Name the LAA only when the ruling sets the two statutes against each other."
        ),
    },
    "kv": {
        "de": (
            "Matter: Krankenversicherung. The question is the benefit under the KVG. "
            "Name the UVG only when the ruling really examines a coordination."
        ),
        "fr": (
            "Matter: assurance-maladie. The question is the benefit under the LAMal. "
            "Name the LAA only when the ruling really examines a coordination."
        ),
    },
    "bv": {
        "de": (
            "Matter: berufliche Vorsorge. The question is the benefit under the BVG. "
            "Name the UVG or the ATSG only when the ruling applies them."
        ),
        "fr": (
            "Matter: prévoyance professionnelle. The question is the LPP benefit. "
            "Name the LAA or the LPGA only when the ruling applies them."
        ),
    },
    "vvg": {
        "de": (
            "Matter: Vertragsrecht, private insurance. The question is the VVG contract, "
            "not a social-insurance benefit. "
            "Name the UVG only when the ruling really examines the coordination."
        ),
        "fr": (
            "Matter: droit des contrats, private insurance. The question is the LCA contract, "
            "not a social-insurance benefit. "
            "Name the LAA only when the ruling really examines the coordination."
        ),
    },
    "other": {
        "de": "Matter not classified. Only the rule of this ruling, no vocabulary from another branch.",
        "fr": "Matter not classified. Only the rule of this ruling, no vocabulary from another branch.",
    },
}
_REVISION = {
    "de": "Art. 17 ATSG is the revision, not the status quo.",
    "fr": "art. 17 LPGA is the revision, not the status quo.",
}
_CLOSE = {
    "de": "Invent nothing. Answer with the fiche only.",
    "fr": "Invent nothing. Answer with the fiche only.",
}


def category_of(area: str | None) -> str:
    """Matter key from the Neuheiten subject. A trailing asterisk is ignored."""
    subject = (area or "").strip().casefold().rstrip("*").strip()
    for key, names in _SUBJECTS.items():
        if subject in names:
            return key
    return "other"


def _laws(category: str) -> list[dict]:
    own = list(GLOSSARY.get(category, {}).get("laws", []))
    if category in SOCIAL or category == "other":
        return list(GLOSSARY["common"]["laws"]) + own
    return own


def _phrases(category: str) -> list[dict]:
    common = GLOSSARY["common"]["phrases"]
    own = GLOSSARY.get(category, {}).get("phrases", [])
    return list(common) + list(own)


def sigils(language: str, category: str) -> str:
    """Sigils of this matter, in the language of the fiche."""
    key = "de" if language == "de" else "fr"
    names = [law[key] for law in _laws(category)]
    return ", ".join(names)


def sigil_hint(category: str) -> str:
    """DE to FR sigils of this matter."""
    return ", ".join(f"{law['de']} becomes {law['fr']}" for law in _laws(category))


def glossary_block(language: str, category: str) -> str:
    """Statutes and phrases of this matter only."""
    key = "de" if language == "de" else "fr"
    other = "fr" if key == "de" else "de"
    lines = [
        "Statutes of this matter (do not translate the sigil; use the one of the fiche language): "
        + sigils(language, category)
        + "."
    ]
    lines.append("Phrases:")
    for phrase in _phrases(category):
        lines.append(f"- {phrase[key]} ({phrase[other]})")
    return "\n".join(lines)


def system_prompt(language: str, category: str) -> str:
    parts = [_STYLE[language], _FOCUS[category][language]]
    if category in SOCIAL:
        parts.append(_REVISION[language])
    parts.append(_CLOSE[language])
    return " ".join(parts)
