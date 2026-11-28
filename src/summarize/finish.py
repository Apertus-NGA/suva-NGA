"""Deterministic finishing of a fiche: everything code can decide is decided by code, not by the model.

Applied after generation, in this order. Each step is a pure function of the fiche and the ruling text:
1. strip Markdown the model adds (bold, headings, bullets);
2. law abbreviations in the fiche's language (a German fiche says UVG, a French one LAA): a one-to-one swap;
3. an article citation is kept only if that article number and that statute are in the ruling;
4. "offensichtlich unbegründet" / "manifestement non fondé" is kept only if either wording is in the ruling;
5. consideration references are kept only if that consideration exists in the ruling;
6. the outcome is stated exactly once: sentences that are nothing but the outcome are removed and the
   outcome read from the operative part is appended, unless the fiche already states it inside a longer sentence;
7. the note Suva puts under a fiche ("Fünfer-Entscheid, zur Publikation vorgesehen.") is added from facts:
   five judges in the heading of the ruling, and the publication mark of the court's list.

What is NOT done here, because code cannot do it safely: choosing the legal point, rewriting a sentence,
replacing the court's party placeholders (A.________). Those are reported as notes for the checker.
"""

from __future__ import annotations

import re

# German <-> French abbreviations of the same act. Only acts with one official abbreviation per language.
_DE_FR = {
    "UVG": "LAA", "UVV": "OLAA", "ATSG": "LPGA", "ATSV": "OPGA", "IVG": "LAI", "IVV": "RAI",
    "KVG": "LAMal", "BVG": "LPP", "VVG": "LCA", "BGG": "LTF", "AHVG": "LAVS", "AVIG": "LACI", "MVG": "LAM",
}  # fmt: skip
_IT_DE = {"LAINF": "UVG", "OAINF": "UVV"}  # Italian forms seen in rulings; LPGA / LAI / LTF equal the French ones
_TO = {
    "de": {**{fr: de for de, fr in _DE_FR.items()}, **_IT_DE},
    "fr": {**_DE_FR, **{it: _DE_FR[de] for it, de in _IT_DE.items()}},
}
_ARTICLE_WORDS = {
    "de": ((r"\bal\.\s*(?=\d)", "Abs. "), (r"\blet\.\s*(?=[a-z]\b)", "lit. "), (r"\bart\.\s*(?=\d)", "Art. ")),
    "fr": ((r"\bAbs\.\s*(?=\d)", "al. "), (r"\blit\.\s*(?=[a-z]\b)", "let. "), (r"\bArt\.\s*(?=\d)", "art. ")),
}
# One statute, both languages. A citation stays only when the ruling names that statute and that article.
_STATUTE = {
    "uvg": ("uvg", "laa"),
    "atsg": ("atsg", "lpga"),
    "uvv": ("uvv", "olaa"),
    "atsv": ("atsv", "opga"),
    "bgg": ("bgg", "ltf"),
}
_CANON = {alias: canon for canon, aliases in _STATUTE.items() for alias in aliases}
_CITE = re.compile(
    r"\bart\.\s*(\d+[a-z]?)(?:\s*(?:abs|al)\.\s*\d+)?(?:\s*(?:lit|let)\.\s*[a-z])?\s*"
    r"(uvg|laa|atsg|lpga|uvv|olaa|atsv|opga|bgg|ltf)\b",
    re.IGNORECASE,
)
# The same claim in either language. Present in the ruling in one language, allowed in the fiche in both.
_EITHER_LANGUAGE = ("offensichtlich", "manifestement")
_UNGROUNDED_PHRASE = re.compile(
    r"(?:\s+comme)?\s*(?:offensichtlich unbegründet|manifestement (?:non|mal) fondé)",
    re.IGNORECASE,
)

_OUTCOME = {
    "rejected": {"de": "Die Beschwerde wird abgewiesen.", "fr": "Le recours est rejeté."},
    "admitted": {"de": "Die Beschwerde wird gutgeheissen.", "fr": "Le recours est admis."},
    "partial": {"de": "Die Beschwerde wird teilweise gutgeheissen.", "fr": "Le recours est partiellement admis."},
}
# Any wording by which a fiche states how the appeal ended.
_STATES_OUTCOME = re.compile(
    r"beschwerde (?:der \w+ )?(?:wird|ist|wurde)\b[^.]{0,60}?(?:abgewiesen|gutgeheissen|unbegründet)"
    r"|(?:weist|wies) die beschwerde\b[^.]{0,40}?\bab\b|heisst die beschwerde\b[^.]{0,40}?\bgut\b"
    r"|recours (?:de [^.]{0,30}? )?(?:est|doit être|a été)\b[^.]{0,60}?(?:rejeté|admis|mal fondé|infondé)"
    r"|(?:rejette|admet) (?:partiellement )?le recours",
    re.IGNORECASE,
)
_CONSIDERATION = re.compile(
    r"\s*\((?:E\.|Erw\.|Erwägung(?:en)?|consid\.)\s*([\d.]+(?:\s*(?:[-–]|und|et|bis|à)\s*[\d.]+)*)\)"
)
# A closing note already under the fiche (written by the model or by an earlier pass): taken off, then added from facts.
_NOTE = re.compile(
    r"\s*(?:Fünfer-Entscheid(?:, zur Publikation vorgesehen)?|Zur Publikation vorgesehen"
    r"|Décision à cinq(?:, prévue pour publication)?|Prévue pour publication)\.?\s*$",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÜÉÈÀ])")
_PANEL = re.compile(r"(Besetzung|Composition|Composizione)(.*?)(Gerichtsschreiber|Greffi|Cancellier)", re.S)
_TITLES = re.compile(
    r"\b(?:Bundesrichter(?:in)?(?:nen)?|Mmes?|MM?\.|les|la|le|Juges?|fédéra(?:l|le|ux)|Giudic[ei]|federal[ei]|"
    r"Präsident(?:in)?|Président[e]?|Presidente|suppléant[e]?|nebenamtliche[rn]?|supplente|"
    r"als Einzelrichter(?:in)?|en qualité de juge unique)\b"
)


def strip_markdown(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text, flags=re.S)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text)
    text = re.sub(r"(?m)^\s{0,3}[-*•]\s+", "", text)
    return text.strip()


def own_language_abbreviations(text: str, language: str) -> str:
    """UVG in German, LAA in French: swap the other language's abbreviation and its article words."""
    for foreign, own in _TO[language].items():
        text = re.sub(rf"\b{re.escape(foreign)}\b", own, text)
    for pattern, own in _ARTICLE_WORDS[language]:
        text = re.sub(pattern, own, text)
    return text


def _has_consideration(number: str, source: str) -> bool:
    number = number.rstrip(".")
    return re.search(rf"(?m)^\s*{re.escape(number)}\.?\s", source) is not None or (
        re.search(rf"(?:E\.|consid\.|Erw\.)\s*{re.escape(number)}\b", source) is not None
    )


def _flat(source: str) -> str:
    return re.sub(r"\s+", " ", source).lower()


def _article_in_ruling(number: str, sigil: str, source: str) -> bool:
    aliases = _STATUTE[_CANON[sigil.lower()]]
    if not any(alias in source for alias in aliases):
        return False
    return re.search(rf"art\.\s*{re.escape(number)}\b", source) is not None


def cited_articles_in_the_ruling(text: str, source: str) -> tuple[str, list[str]]:
    """Drop a statute citation whose article is not in the ruling. Any statute, any fiche."""
    source_low = _flat(source)
    dropped: list[str] = []

    def keep(match: re.Match) -> str:
        if _article_in_ruling(match.group(1), match.group(2), source_low):
            return match.group(0)
        dropped.append(match.group(0).strip())
        return ""

    return re.sub(r"[ \t]{2,}", " ", _CITE.sub(keep, text)), dropped


def grounded_wording_only(text: str, source: str) -> tuple[str, bool]:
    """Drop 'manifestly ill-founded' unless the ruling says it in German or in French."""
    source_low = _flat(source)
    if any(word in source_low for word in _EITHER_LANGUAGE) or not _UNGROUNDED_PHRASE.search(text):
        return text, False
    kept = []
    for sentence in _SENTENCE_END.split(text.strip()):
        if not _UNGROUNDED_PHRASE.search(sentence):
            kept.append(sentence)
            continue
        residue = _UNGROUNDED_PHRASE.sub("", sentence).strip(" .;,:")
        if len(residue) >= 25:
            kept.append(_UNGROUNDED_PHRASE.sub("", sentence).strip())
    return " ".join(kept), True


def real_considerations_only(text: str, source: str) -> tuple[str, list[str]]:
    """Drop a bracketed reference when one of its consideration numbers is not in the ruling."""
    dropped: list[str] = []

    def keep(match: re.Match) -> str:
        numbers = re.findall(r"\d+(?:\.\d+)*", match.group(1))
        if numbers and all(_has_consideration(n, source) for n in numbers):
            return match.group(0)
        dropped.append(match.group(0).strip())
        return ""

    return _CONSIDERATION.sub(keep, text), dropped


def outcome_kind(source: str) -> str:
    """'rejected' | 'admitted' | 'partial' from point 1 of the operative part, or '' when it is something else."""
    tail = source[-6000:]
    start = max(tail.rfind(m) for m in ("Demnach erkennt", "erkennt die Präsidentin", "erkennt der Präsident",
                                        "Par ces motifs", "Per questi motivi"))  # fmt: skip
    if start < 0:
        return ""
    block = re.sub(r"\s+", " ", tail[start : start + 700])
    first = re.search(r"\b1\.\s+(.*?)(?=\s2\.\s|$)", block)
    point = (first.group(1) if first else block).lower()
    if "nicht eingetreten" in point or "irrecevable" in point or "inammissibile" in point:
        return ""
    rejected = "abgewiesen" in point or "rejeté" in point or "respinto" in point
    admitted = "gutgeheissen" in point or "admis" in point or "accolto" in point
    if "teilweise" in point or "partiellement" in point or "parzialmente" in point or (rejected and admitted):
        return "partial"  # also "admis ... rejeté pour le surplus"
    if rejected:
        return "rejected"
    if admitted:
        return "admitted"
    return ""


def outcome_once(text: str, language: str, kind: str) -> str:
    """The outcome exactly once. Unknown kind (inadmissible, struck off, ...): the text is left as it is."""
    if not kind:
        return text
    sentence = _OUTCOME[kind][language]
    paragraphs = []
    for paragraph in text.split("\n\n"):
        kept = []
        for part in _SENTENCE_END.split(paragraph.strip()):
            residue = _STATES_OUTCOME.sub("", part).strip(" .;,:")
            if _STATES_OUTCOME.search(part) and len(residue) < 25:
                continue  # a sentence that is nothing but the outcome
            kept.append(part)
        if kept:
            paragraphs.append(" ".join(kept))
    body = "\n\n".join(paragraphs)
    if _STATES_OUTCOME.search(body):
        return body  # stated inside a sentence that also gives reasons: not repeated
    return f"{body} {sentence}".strip() if body else sentence


def judges(source: str) -> int | None:
    """Number of judges in the heading of the ruling, or None when the heading is not recognised."""
    match = _PANEL.search(source[:4000])
    if not match:
        return None
    names = _TITLES.sub(" ", match.group(2))
    return sum(1 for part in re.split(r",|\bund\b|\bet\b|\be\b", names) if re.search(r"[A-ZÉ][a-zéèüöä]{2,}", part))


def bench_note(language: str, source: str, starred: bool | None) -> str:
    """Suva's closing note, from facts only. Empty when neither fact holds or the publication mark is unknown."""
    five = judges(source) == 5
    if language == "de":
        parts = (["Fünfer-Entscheid"] if five else []) + (["zur Publikation vorgesehen"] if starred else [])
    else:
        parts = (["Décision à cinq"] if five else []) + (["prévue pour publication"] if starred else [])
    if not parts:
        return ""
    note = ", ".join(parts) + "."
    return note[0].upper() + note[1:]


def without_note(text: str) -> str:
    """The fiche without Suva's closing note (for checks that look at the last sentence)."""
    return _NOTE.sub("", text).strip()


def finish(language: str, text: str, source: str, starred: bool | None = None) -> tuple[str, list[str]]:
    """The finished fiche and notes on what was changed or still needs a person."""
    notes: list[str] = []
    text = strip_markdown(text)
    swapped = own_language_abbreviations(text, language)
    if swapped != text:
        notes.append("abbreviations put in the fiche's language")
    text, absent = cited_articles_in_the_ruling(swapped, source)
    notes += [f"article not in the ruling removed: {cite}" for cite in absent]
    text, ungrounded = grounded_wording_only(text, source)
    if ungrounded:
        notes.append("ungrounded 'manifestly ill-founded' removed")
    text, dropped = real_considerations_only(text, source)
    notes += [f"reference not in the ruling removed: {d}" for d in dropped]
    text = outcome_once(_NOTE.sub("", text), language, outcome_kind(source))
    note = bench_note(language, source, starred)
    if note:
        text = f"{text}\n\n{note}"
    if "____" in text:
        notes.append("party placeholder left in the text")
    return re.sub(r"[ \t]+", " ", text).strip(), notes
