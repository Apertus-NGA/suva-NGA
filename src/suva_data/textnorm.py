"""Text normalisation, hashing and the bad-text check shared by all sources (docs/DATA_LAYER.md 6, 6.1)."""

from __future__ import annotations

import hashlib
import re
import unicodedata

MIN_TEXT_CHARS = 600
# entscheidsuche's search API cuts `attachment.content` at this many characters (seen on 22 long rulings).
TRUNCATION_LENGTHS = frozenset({99992, 100000})
_ERROR_MARKERS = ("Dokument nicht gefunden", "in elektronischer Form nicht verfügbar", "Incapsula incident")
# A real ruling ends with the court / president / clerk signature block.
_SIGNATURE_RE = re.compile(
    r"Bundesgericht|Tribunal f[ée]d[ée]ral|Tribunale federale|Gerichtsschreiber|Greffi[eè]r|Cancellier|Pr[äée]sident|Presidente",
    re.I,
)


def normalise(text: str) -> str:
    """Form used ONLY for comparing texts across sources; stored texts are never altered."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def compare_key(text: str) -> str:
    """Form used to decide whether two sources hold the SAME ruling text.

    Sources extract the same HTML differently (no-break spaces, line breaks inside words, spacing around
    anonymised names), so whitespace is removed entirely and compatibility characters are folded (NFKC).
    Every letter, digit and punctuation mark still has to match.
    """
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def text_hash(text: str) -> str:
    return hashlib.sha256(compare_key(text).encode("utf-8")).hexdigest()


def bad_text_reason(text: str | None) -> str | None:
    """None if the text looks like a complete ruling, otherwise a short reason."""
    if not text or not text.strip():
        return "empty"
    if any(m in text for m in _ERROR_MARKERS):
        return "error_page"
    if len(normalise(text)) < MIN_TEXT_CHARS:
        return "too_short"
    if len(text) in TRUNCATION_LENGTHS and not _SIGNATURE_RE.search(text[-400:]):
        return "truncated"
    if not _SIGNATURE_RE.search(text[-400:]):
        return "no_signature_block"
    return None
