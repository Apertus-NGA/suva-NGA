"""The court's matter names, read one way everywhere.

The Federal Supreme Court names the matter of a ruling in the ruling's language, on its
Neuheiten list (``Unfallversicherung``, ``Assurance-accidents*``) and, for the social-law
courts, at the start of the subject line (``Unfallversicherung (Kausalzusammenhang)``).
``area_code`` turns any of these into one code, whatever the language or the spelling.
Which codes a gate, a filter or a signal keeps is their choice, not this module's.

Whole names, not fragments: ``invalidit`` alone would also match
``Prévoyance professionnelle (rente d'invalidité)``, and ``milit`` alone would match the
exemption tax ``Militärpflichtersatz``. Only the part before the first bracket, comma or
semicolon is read: what follows is the dispute, not the matter.
"""

from __future__ import annotations

import re

# Order matters when a line names two matters: the first code listed here wins.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "UV",
        re.compile(
            r"unfallversicherung|assurance[- ]accidents?\b|assicurazione (?:contro gli |contro l'|contro )?infortuni"
        ),
    ),
    ("MV", re.compile(r"militärversicherung|assurance[- ]militaire|assicurazione militare")),
    ("IV", re.compile(r"invalidenversicherung|assurance[- ]invalidité|assicurazione (?:per l'|per la |d')?invalidità")),
    ("KV", re.compile(r"krankenversicherung|assurance[- ]maladie|assicurazione (?:contro le )?malattie")),
    # The court's page also spells the Italian "professionnale".
    ("BV", re.compile(r"berufliche vorsorge|prévoyance professionnelle|previdenza profession+ale")),
    ("CONTRACT", re.compile(r"vertragsrecht|droit des contrats|diritto contrattuale")),
    # No Italian civil-liability rubric was read on the Neuheiten pages (docs/DATA.md §5).
    ("LIABILITY", re.compile(r"haftpflichtrecht|assurance responsabilité civile")),
)

CODES: tuple[str, ...] = tuple(code for code, _ in _PATTERNS)
_CUT = re.compile(r"[(,;]")


def first_segment(text: object) -> str | None:
    """The matter at the start of a line: the part before the first bracket, comma or semicolon."""
    if not isinstance(text, str):
        return None
    head = _CUT.split(text, maxsplit=1)[0].strip().rstrip("*").strip()
    return head or None


def _normalise(text: str) -> str:
    return text.replace("’", "'").replace(" ", " ").casefold()


def area_code(text: object) -> str | None:
    """UV, MV, IV, KV, BV, CONTRACT or LIABILITY when the line names that matter, otherwise None."""
    head = first_segment(text)
    if head is None:
        return None
    head = _normalise(head)
    for code, pattern in _PATTERNS:
        if pattern.search(head):
            return code
    return None
