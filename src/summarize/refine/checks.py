"""Code checks: what code can decide about a summary is decided here, never asked of a model.

`run(text, ctx)` returns check name -> findings (an empty list passes). The refine loop keeps a patch only if no
check has more findings after it than before (`regressions`). `new_identifiers` is the G1 guard on any sentence a
model wrote: every article, consideration reference and number in it must already be in the ruling.
"""

from __future__ import annotations

import re
from collections import Counter

from src.summarize import finish, summarize
from src.summarize.refine.evidence import normalise

# The same form checks the evaluation judge runs before calling its model (eval/judge/checks.py), restated here
# so src/ does not import eval/. Kept identical on purpose: a summary refine leaves clean is clean for the judge.
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
# Words per language: the 10th to 90th percentile of Suva's 55 summaries (the judge's band, eval/judge/run.py
# length_bands, measured 28 Nov 2026; aggregates only, D-031).
LENGTH_BAND = {"de": (64, 337), "fr": (84, 402)}

_FUNCTION_WORDS = {
    "de": {"der", "die", "das", "und", "nicht", "ist", "zu", "den", "mit", "von", "dass", "sich", "des", "auf", "für",
           "eine", "ein", "wird", "im", "dem", "nach", "bei", "auch", "oder", "werden", "hat"},
    "fr": {"le", "la", "les", "et", "de", "des", "du", "un", "une", "est", "que", "qui", "dans", "pour", "pas", "au",
           "aux", "sur", "par", "ne", "il", "elle", "sont", "ce", "cette", "son", "sa"},
    "it": {"il", "lo", "gli", "di", "che", "è", "per", "non", "della", "del", "nel", "alla", "sono", "una", "con"},
}  # fmt: skip


def language_of(text: str) -> str | None:
    """The language a sentence is written in, from its function words; None when too short to tell."""
    words = re.findall(r"[a-zàâäçéèêëîïôöùûüè]+", text.lower())
    if len(words) < 5:
        return None
    counts = {lang: sum(w in vocab for w in words) for lang, vocab in _FUNCTION_WORDS.items()}
    best = max(counts, key=counts.get)
    return best if counts[best] >= 2 else None


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-ZÄÖÜÀÉÈ«\"])", text.strip()) if s.strip()]


def run(text: str, language: str, source: str) -> dict[str, list[str]]:
    """Check name -> findings for a whole summary."""
    body = finish.without_note(text)
    found: dict[str, list[str]] = {
        "wrong_language_abbreviation": sorted(set(re.findall(WRONG_SIGIL[language], text))),
        "wrong_language_citation_form": sorted({m.group(0) for m in re.finditer(WRONG_CITATION_FORM[language], text)}),
        "markup_or_heading": sorted({m.group(0).strip() for m in re.finditer(MARKUP, text)}),
        "anonymisation_placeholder": sorted(set(re.findall(PLACEHOLDER, text))),
        "eszett": ["ß"] if language == "de" and "ß" in text else [],
        "invented_consideration": [
            m.group(0).strip()
            for m in finish._CONSIDERATION.finditer(text)
            if not all(finish._has_consideration(n, source) for n in re.findall(r"\d+(?:\.\d+)*", m.group(1)))
        ],
        # The project's blocking checks (wrong sigil, outcome missing or inverted, article not in the ruling, a
        # pasted operative block, the fiche in another language), read on the text without the closing note.
        "blocking": [p for p in summarize.blocking(language, body, source) if p.startswith("critique")],
        "foreign_sentence": [s for s in sentences(body) if (lang := language_of(s)) and lang != language],
    }
    seen: set[str] = set()
    repeated = []
    for sentence in sentences(text):
        key = re.sub(r"\W+", " ", sentence.lower()).strip()
        if len(key) > 15 and key in seen:
            repeated.append(sentence)
        seen.add(key)
    found["repeated_sentence"] = repeated
    low, high = LENGTH_BAND[language]
    words = len(text.split())
    found["length_out_of_band"] = [] if low <= words <= high else [f"{words} words, band {low} to {high}"]
    return found


# How the appeal to the Federal Supreme Court ended. A lower court's or an insurer's decision is a fact of the case,
# not the outcome (run r4 refused six fact sentences for "die Vorinstanz hiess die Beschwerde gut").
_FEDERAL = re.compile(r"\b(?:Bundesgericht|BGer|Tribunal fédéral|TF)\b")
_OUTCOME_WORDS = re.compile(
    r"\b(?:abgewiesen|gutgeheissen|abzuweisen|gutzuheissen|nicht eingetreten|weist|wies|heisst|hiess"
    r"|rejet[ée]e?|rejette|rejeta|admis|admet|admit|irrecevable)\b",
    re.IGNORECASE,
)
_CANONICAL = re.compile(
    r"^(?:Die Beschwerde (?:wird|ist|wurde)\b[^.]{0,40}(?:abgewiesen|gutgeheissen)"
    r"|Le recours (?:est|a été)\b[^.]{0,40}(?:rejeté|admis))",
    re.IGNORECASE,
)


def restates_outcome(text: str) -> bool:
    text = text.strip()
    if _CANONICAL.search(text):
        return True
    return bool(_FEDERAL.search(text) and _OUTCOME_WORDS.search(text) and re.search(r"Beschwerde|recours", text))


def failing(found: dict[str, list[str]]) -> dict[str, int]:
    return {name: len(items) for name, items in found.items() if items}


def regressions(before: dict[str, list[str]], after: dict[str, list[str]], allow: tuple[str, ...] = ()) -> list[str]:
    """Checks with more findings after a patch than before. `allow` names checks a step may trade off."""
    return [name for name in after if name not in allow and len(after[name]) > len(before.get(name, []))]


# --- the guard on model-written text (G1) --------------------------------------------------------------------------

_NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,']\d+)*(?:\s?%)?")
_YEAR_OR_SMALL = re.compile(r"^(?:[1-9]|1[0-2])$")  # 1 to 12 may be written as a word in the ruling


def _numbers(text: str) -> Counter:
    return Counter(n.replace("'", "").replace(" ", "") for n in _NUMBER.findall(text))


def new_identifiers(new: str, old: str, source: str) -> list[str]:
    """Identifiers in `new` that are neither in `old` nor in the ruling: articles, considerations, numbers."""
    problems: list[str] = []
    flat_source = summarize.flat(source).lower()
    cite = summarize.CITE_DE if re.search(r"\bArt\.", new) else summarize.CITE_FR
    for number, sigil in cite.findall(new):
        law = summarize.TO_CANON.get(sigil.lower())
        if law and not summarize._article_in_source(number, law, flat_source):
            problems.append(f"article {number} {sigil} not in the ruling")
    for match in finish._CONSIDERATION.finditer(new):
        for n in re.findall(r"\d+(?:\.\d+)*", match.group(1)):
            if not finish._has_consideration(n, source):
                problems.append(f"consideration {n} not in the ruling")
    source_numbers = _numbers(source)
    old_numbers = _numbers(old)
    for value in _numbers(new):
        if value not in source_numbers and value not in old_numbers and not _YEAR_OR_SMALL.match(value):
            problems.append(f"number {value} not in the ruling")
    return problems


def same_identifiers(new: str, old: str) -> list[str]:
    """For a rewording: articles, consideration references and numbers must be exactly the old ones."""
    problems = []
    for label, read in (
        ("articles", lambda t: Counter(" ".join(m.group(0).split()) for m in finish._CONSIDERATION.finditer(t))),
        ("numbers", _numbers),
    ):
        if read(new) != read(old):
            problems.append(f"{label} changed")
    cite = summarize.CITE_DE if re.search(r"\bArt\.", old) else summarize.CITE_FR
    if Counter(cite.findall(new)) != Counter(cite.findall(old)):
        problems.append("article citations changed")
    return problems


def mentions(text: str, term: str) -> bool:
    return normalise(term) in normalise(text)
