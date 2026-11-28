"""Outer gate ("possibly relevant"): one rule, code only, no model.

A ruling is **possibly relevant** when its subject area is accident insurance (UV),
military insurance (MV) or disability insurance (IV). Nothing else is checked here:
not the court, not the docket prefix (G5), not the bench, not the length.

The subject area is read from two places, and either one is enough:

1. the court's list of new rulings (``sachgebiet`` of a ``RulingRecord``), for example
   ``Unfallversicherung``, ``Assurance-invalidité*`` or ``Assicurazione contro gli infortuni``;
2. the subject line of the ruling's own header (under ``Gegenstand`` / ``Objet`` / ``Oggetto``),
   for example ``Unfallversicherung (Kausalzusammenhang)``.

If neither can be read, the ruling is kept and flagged (the gate fails open).
A dropped ruling always carries a reason code. Description, measurements and limits:
``docs/TRIAGE_OUTER_GATE.md``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from src.schemas import NetDecision

VERSION = "outer_gate_area@1"

Area = Literal["UV", "MV", "IV"]

# Full names of the three areas as the court writes them, in German, French and Italian.
# Whole names, not fragments: "invalidit" alone would also match an occupational-pension
# subject such as "Prévoyance professionnelle (rente d'invalidité)", and "milit" alone
# would match the military service exemption tax ("Militärpflichtersatz").
_AREAS: tuple[tuple[Area, re.Pattern[str]], ...] = (
    (
        "UV",
        re.compile(
            r"unfallversicherung|assurance[- ]accidents?\b|assicurazione (?:contro gli |contro l'|contro )?infortuni"
        ),
    ),
    ("MV", re.compile(r"militärversicherung|assurance[- ]militaire|assicurazione militare")),
    ("IV", re.compile(r"invalidenversicherung|assurance[- ]invalidité|assicurazione (?:per l'|per la |d')?invalidità")),
)
# "[^\\S\\n]" is any blank except a line break: the court's pages use non-breaking spaces here.
_HEADER_SUBJECT = re.compile(r"^[^\S\n]*(?:Gegenstand|Objet|Oggetto)[^\S\n]*:?[^\S\n]*\n\s*(\S.*)$", re.MULTILINE)
_HEADER_WINDOW = 8000  # the header sits at the top of the ruling

REASON_NOT_IN_AREA = "area_not_uv_mv_iv"
FLAG_UNDETERMINED = "area_undetermined"


def _normalise(text: str) -> str:
    return text.replace("’", "'").replace(" ", " ").strip().rstrip("*").strip().casefold()


def classify_area(text: str | None) -> Area | None:
    """UV, MV or IV when the text names one of the three areas, otherwise None.

    Only the part before the first parenthesis is read: the parenthesis holds the topic
    of the dispute ("Invalidenrente", "rente d'invalidité"), not the area.
    When several areas are named, the first of UV, MV, IV wins.
    """
    if not text:
        return None
    head = _normalise(text).split("(", 1)[0]
    for area, pattern in _AREAS:
        if pattern.search(head):
            return area
    return None


def header_subject(full_text: str | None) -> str | None:
    """The subject line of the ruling's header, or None when the header has none."""
    if not full_text:
        return None
    match = _HEADER_SUBJECT.search(full_text[:_HEADER_WINDOW])
    if not match:
        return None
    return match.group(1).strip().rstrip(",").strip() or None


@dataclass(frozen=True)
class OuterGateDecision:
    """Outcome of the outer gate for one ruling.

    ``reasons`` lists every rule that kept the ruling (``list_area:UV``, ``header_area:IV``,
    ``area_undetermined``). ``reason_code`` is set only when the ruling is dropped.
    """

    kept: bool
    area: Area | None
    reasons: tuple[str, ...]
    reason_code: str | None = None
    version: str = VERSION

    @property
    def flagged(self) -> bool:
        """True when the ruling was kept only because its area could not be read."""
        return FLAG_UNDETERMINED in self.reasons

    def net_decision(self) -> NetDecision:
        """The same decision in the shared contract (``src/schemas.py``)."""
        return NetDecision(kept=self.kept, reason_code=self.reason_code)


def outer_gate(list_area: str | None, full_text: str | None = None) -> OuterGateDecision:
    """Decide whether a ruling is possibly relevant.

    ``list_area``: the subject area from the court's list of new rulings, or None.
    ``full_text``: the ruling's text, used only for its header subject line, or None.
    """
    from_list = classify_area(list_area)
    subject = header_subject(full_text)
    from_header = classify_area(subject)
    reasons: list[str] = []
    if from_list:
        reasons.append(f"list_area:{from_list}")
    if from_header:
        reasons.append(f"header_area:{from_header}")
    if reasons:
        return OuterGateDecision(kept=True, area=from_list or from_header, reasons=tuple(reasons))
    if not (list_area and list_area.strip()) and subject is None:
        return OuterGateDecision(kept=True, area=None, reasons=(FLAG_UNDETERMINED,))
    return OuterGateDecision(kept=False, area=None, reasons=(), reason_code=REASON_NOT_IN_AREA)


def measure(rows: Iterable[Mapping[str, object]]) -> dict[str, int]:
    """Counts for a set of rulings: how many are kept, flagged, and how many relevant ones are kept.

    Each row needs ``list_area`` and ``full_text``; ``relevant`` (bool) is optional.
    """
    out = {
        "rulings": 0,
        "kept": 0,
        "flagged": 0,
        "relevant": 0,
        "relevant_kept": 0,
        "by_area_UV": 0,
        "by_area_MV": 0,
        "by_area_IV": 0,
    }
    for row in rows:
        decision = outer_gate(row.get("list_area"), row.get("full_text"))  # type: ignore[arg-type]
        out["rulings"] += 1
        out["kept"] += decision.kept
        out["flagged"] += decision.flagged
        if decision.area:
            out[f"by_area_{decision.area}"] += 1
        if row.get("relevant"):
            out["relevant"] += 1
            out["relevant_kept"] += decision.kept
    return out
