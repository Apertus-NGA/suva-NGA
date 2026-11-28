"""The ruling as evidence: labelled passages, and the check that a quotation really is in one of them.

Code splits the ruling into passages a model can only name, never invent: `facts`, one passage per consideration
(`E.2.1`), and `operative`. A quotation the model gives is accepted only if `quote_in` finds it in the passage it
names, after the documented normalisation below (`normalise`). A quotation found under another passage is moved
there by code (`locate`); one found nowhere is rejected.
"""

from __future__ import annotations

import re
import unicodedata

MIN_QUOTE = 20  # letters and digits; a shorter quotation proves nothing

_FACTS = re.compile(r"(?mi)^[ \t]*(?:Sachverhalt|Faits|Fatti)[ \t]*:")
_REASONS = re.compile(
    r"(?mi)^[ \t]*(?:in Erwägung,?|Erwägungen[ \t]*:|Considérant en (?:fait et en )?droit[ \t]*:|Considérant[ \t]*:"
    r"|Considerando in diritto[ \t]*:|Considerando[ \t]*:|Diritto[ \t]*:)"
)
_OPERATIVE = re.compile(r"(?mi)^[ \t]*(?:Demnach (?:erkennt|verfügt|beschliesst)|Par ces motifs|Per questi motivi)")
_NUMBER = re.compile(r"(?m)^[ \t]*(\d{1,2}(?:\.\d{1,2})*)\.?(?=\s)")


def _follows(previous: list[int] | None, number: list[int]) -> bool:
    """True when `number` can be the next consideration heading after `previous` (2.1 -> 2.2, 2.1.1 or 3)."""
    if previous is None:
        return len(number) == 1
    if number == [*previous, 1]:
        return True
    return any(
        len(number) == level + 1 and number[:level] == previous[:level] and number[level] == previous[level] + 1
        for level in range(len(previous))
    )


def passages(text: str) -> dict[str, str]:
    """The ruling split into labelled passages, in reading order.

    A number that does not continue the numbering ("7. Mai 2024" inside consideration 3) stays text. A ruling
    without a reasoning heading is one passage, `text`; one with a heading but no numbered consideration has
    `reasons`."""
    operative = _OPERATIVE.search(text)
    end = operative.start() if operative else len(text)
    reasons = _REASONS.search(text, 0, end)
    parts: dict[str, str] = {}
    if reasons is None:
        parts["text"] = text[:end].strip()
    else:
        facts = _FACTS.search(text, 0, reasons.start())
        parts["facts"] = text[facts.end() if facts else 0 : reasons.start()].strip()
        previous: list[int] | None = None
        starts: list[tuple[int, str]] = []
        for match in _NUMBER.finditer(text, reasons.end(), end):
            number = [int(n) for n in match.group(1).split(".")]
            if _follows(previous, number):
                starts.append((match.start(), "E." + match.group(1)))
                previous = number
        if not starts:
            parts["reasons"] = text[reasons.end() : end].strip()
        stops = [start for start, _ in starts[1:]] + [end]
        for (start, label), stop in zip(starts, stops, strict=True):
            parts[label] = text[start:stop].strip()
    if operative:
        parts["operative"] = text[operative.start() :].strip()
    return {label: body for label, body in parts.items() if body}


def considerations(parts: dict[str, str]) -> list[str]:
    """The labels of the court's reasoning."""
    labels = [label for label in parts if label.startswith("E.")]
    return labels or [label for label in parts if label in ("reasons", "text")]


# --- quotations ---------------------------------------------------------------------------------------------------

_MARKS = str.maketrans({"„": '"', "“": '"', "”": '"', "«": '"', "»": '"', "‹": "'", "›": "'", "’": "'", "‘": "'",
                        "–": "-", "—": "-"})  # fmt: skip
_ELLIPSIS = re.compile(r"\[\.\.\.\]|\[…\]|\.\.\.|…")


def normalise(text: str) -> str:
    """The form both sides are compared in: Unicode NFC, no soft hyphen, a word split at a line break joined
    ("Versicherungs-\\nleistungen"), one kind of quotation mark and dash, single spaces, case folded."""
    text = unicodedata.normalize("NFC", text).replace("­", "").replace(" ", " ")
    text = re.sub(r"(?<=\w)-[ \t]*\n[ \t]*(?=[a-zäöüéèêàâçîôû])", "", text)
    return re.sub(r"\s+", " ", text.translate(_MARKS)).strip().casefold()


def _pieces(quote: str) -> list[str]:
    return [p for p in (normalise(part).strip(" ,;:.") for part in _ELLIPSIS.split(quote)) if p]


def long_enough(quote: str) -> bool:
    return len(re.sub(r"\W", "", "".join(_pieces(quote)))) >= MIN_QUOTE


def quote_in(quote: str, passage: str) -> bool:
    """True when every piece of the quotation (pieces are separated by an ellipsis) is in the passage, in order."""
    pieces, haystack, position = _pieces(quote), normalise(passage), 0
    for piece in pieces:
        found = haystack.find(piece, position)
        if found < 0:
            return False
        position = found + len(piece)
    return bool(pieces)


def locate(quote: str, parts: dict[str, str], named: str | None = None) -> str | None:
    """The label of the passage that holds the quotation: the one named if it does, else the first that does."""
    if not isinstance(quote, str) or not long_enough(quote):
        return None
    if named in parts and quote_in(quote, parts[named]):
        return named
    return next((label for label, body in parts.items() if quote_in(quote, body)), None)


# --- what a rule can be ------------------------------------------------------------------------------------------

_LAWS = (
    "UVG|UVV|ATSG|ATSV|IVG|IVV|KVG|KVV|BVG|BVV2|VVG|BGG|AHVG|AVIG|MVG|ELG|FZG|ZGB|OR|BV|EMRK|"
    "LAA|OLAA|LPGA|OPGA|LAI|RAI|LAMal|OAMal|LPP|OPP2|LCA|LTF|LAVS|LACI|LAM|LPC|LFLP|CC|CO|Cst|CEDH|LAINF|OAINF"
)
ARTICLE = re.compile(
    r"\b[Aa]rt\.\s*\d+[a-z]?(?:\s*(?:Abs|al|cpv)\.\s*\d+)?(?:\s*(?:lit|let|Bst)\.\s*[a-z]\)?)?"
    r"(?:\s*(?:Satz|phrase|frase)\s*\d+)?\s+(?:" + _LAWS + r")\b"
)


def articles(text: str) -> list[str]:
    """The article citations of a text, read by code, in order of first appearance."""
    return list(dict.fromkeys(" ".join(m.group(0).split()) for m in ARTICLE.finditer(text)))


# The court's formula for "the lower court set out the law correctly; we refer to it" (DE, FR, IT). A rule
# quoted there is a recital, not the rule the court applies to decide.
_RECITAL = re.compile(
    r"Darauf (?:kann|wird) verwiesen|darauf verwiesen werden kann|(?:Il|On) (?:suffit|peut) (?:d'|y )?(?:y )?renvoyer"
    r"|il peut y être renvoyé|(?:si può|può essere) (?:fatto )?rinvi|a cui si rinvia|ai quali si rinvia|vi si rinvia",
    re.IGNORECASE,
)
_COSTS = re.compile(r"Gerichtskosten|Parteientschädigung|frais judiciaires|dépens|spese giudiziarie|ripetibili")
_PROCEDURAL = (" BGG", " LTF")


def rule_candidates(parts: dict[str, str], merits: bool) -> tuple[list[str], dict[str, str]]:
    """The considerations where the rule the court applies to decide can stand, and why each other one cannot.

    Left out: a mere reference to the lower court's statement of the law; the costs at the end; and, when the
    ruling decides the merits, admissibility (E.1) and considerations citing only procedural law (BGG, LTF).
    If every consideration would be left out, all stay candidates."""
    labels = considerations(parts)
    numbered = [label for label in labels if label.startswith("E.")]
    last = max((int(label.split(".")[1]) for label in numbered), default=None)
    excluded: dict[str, str] = {}
    for label in numbered:
        body, first = parts[label], int(label.split(".")[1])
        cited = articles(body)
        if _RECITAL.search(body):
            excluded[label] = "refers to the lower court's statement of the law"
        elif first == last and _COSTS.search(body):
            excluded[label] = "costs"
        elif merits and first == 1:
            excluded[label] = "admissibility"
        elif merits and cited and all(a.endswith(_PROCEDURAL) for a in cited):
            excluded[label] = "procedural law only"
    kept = [label for label in labels if label not in excluded]
    return (kept, excluded) if kept else (labels, {})


def as_data(text: str) -> str:
    """Ruling text cannot close its delimiter or pass for a control tag (AGENTS.md G4)."""
    return text.replace("</ruling>", "</ ruling>").replace("<|", "< |")


def labelled(parts: dict[str, str], labels: list[str] | None = None) -> str:
    """The passages as the model sees them: `[label]` then the text, inside one <ruling> delimiter."""
    chosen = labels if labels is not None else list(parts)
    body = "\n\n".join(f"[{label}]\n{as_data(parts[label])}" for label in chosen if label in parts)
    return f"<ruling>\n{body}\n</ruling>"


# --- pointers: the model names where a sentence starts, code copies the sentence ---------------------------------

MIN_OPENING_WORDS = 4
_HEADING = re.compile(r"^\s*(?:\d{1,2}(?:\.\d{1,2})*\.?|[A-Z]\.)\s+")  # "2.1 " or "A. " before the sentence


def sentences(passage: str) -> list[str]:
    """The sentences of a passage, split by the same rules as a summary (abbreviations, ordinals, initials)."""
    from src.summarize.refine.draft import split_sentences

    return split_sentences(" ".join(passage.split()))


def expand(opening: str, passage: str, count: int = 1) -> str | None:
    """The `count` sentences of the passage that begin at (or contain) `opening`, copied from the ruling."""
    words = opening.split()
    if len(words) < MIN_OPENING_WORDS:
        return None
    needle = normalise(" ".join(words))
    found = sentences(passage)
    for index, sentence in enumerate(found):
        if needle in normalise(sentence):
            return _HEADING.sub("", " ".join(found[index : index + max(1, count)]))
    # an opening that runs across a sentence boundary: look in the flattened passage
    flat = " ".join(passage.split())
    if needle in normalise(flat):
        for index in range(len(found)):
            if needle in normalise(" ".join(found[index : index + 2])):
                return _HEADING.sub("", " ".join(found[index : index + max(2, count)]))
    return None


def find(opening: str, parts: dict[str, str], named: str | None = None, count: int = 1) -> tuple[str, str] | None:
    """(label, sentences) of the passage that holds the opening: the named passage first, then any other."""
    if not isinstance(opening, str):
        return None
    order = ([named] if named in parts else []) + [label for label in parts if label != named]
    for label in order:
        text = expand(opening, parts[label], count)
        if text:
            return label, text
    return None
