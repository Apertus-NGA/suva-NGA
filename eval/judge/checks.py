"""Deterministic checks, run before the judge: what code can decide is not asked of a model (docs/EVAL.md §1.3).

Each check returns the passages it found; an empty list means the check passes. They cover form only:
citation style and statute abbreviations of the right language, plain prose, no anonymisation placeholder,
no repeated sentence, Swiss spelling, length.
"""

from __future__ import annotations

import re

WRONG_SIGIL = {
    "de": r"\b(LAA|OLAA|LPGA|OPGA|LAI|RAI|LPP|LAMal|LCA|LTF|LAVS|Cst\.|CEDH|LAINF)\b",
    "fr": r"\b(UVG|UVV|ATSG|ATSV|IVG|IVV|BVG|KVG|VVG|BGG|AHVG|EMRK)\b",
}
WRONG_CITATION_FORM = {
    "de": r"\bal\.\s*\d|\blet\.\s*[a-z]\b|\bconsid\.|\bch\.\s*\d",
    "fr": r"\bAbs\.\s*\d|\blit\.\s*[a-z]\b|\bBst\.|\bErw\.|\bE\.\s*\d|\bZiff\.",
}
MARKUP = (
    r"(?m)^\s*(#{1,6}\s|[-*•]\s|\d+[.)]\s)|\*\*"
    r"|^\s*(Sachverhalt|Erwägungen|Faits|Considérants|Zusammenfassung|Résumé)\s*:"
)
PLACEHOLDER = r"\b[A-Z]\.?_{3,}"


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-ZÄÖÜÀÉÈ«\"])", text.strip()) if s.strip()]


def run_checks(summary: str, language: str, length_band: tuple[int, int] | None = None) -> dict[str, list[str]]:
    """Check name -> passages found. `length_band` is (low, high) in words; none means the length is not checked."""
    found: dict[str, list[str]] = {
        "wrong_language_abbreviation": sorted(set(re.findall(WRONG_SIGIL[language], summary))),
        "wrong_language_citation_form": sorted(
            {m.group(0) for m in re.finditer(WRONG_CITATION_FORM[language], summary)}
        ),
        "markup_or_heading": sorted({m.group(0).strip() for m in re.finditer(MARKUP, summary)}),
        "anonymisation_placeholder": sorted(set(re.findall(PLACEHOLDER, summary))),
        "eszett": ["ß"] if language == "de" and "ß" in summary else [],
    }
    seen: set[str] = set()
    repeated = []
    for sentence in sentences(summary):
        key = re.sub(r"\W+", " ", sentence.lower()).strip()
        if len(key) > 15 and key in seen:
            repeated.append(sentence)
        seen.add(key)
    found["repeated_sentence"] = repeated
    words = len(summary.split())
    found["length_out_of_band"] = (
        [f"{words} words, band {length_band[0]} to {length_band[1]}"]
        if length_band and not length_band[0] <= words <= length_band[1]
        else []
    )
    return found
