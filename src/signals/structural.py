"""Structural signals: facts about a ruling that code reads from its header and text. No model.

These are the inputs of the relevance score that do not need reading comprehension:

- ``area``                      accident (UV), military (MV) or disability (IV) insurance, else "other"
- ``bench_size``                number of judges named in the bench block
- ``single_judge``              one judge (short procedural decisions)
- ``five_judges``               five or more judges (questions of principle)
- ``appeal_by_institution``     the appeal was brought by an insurer, an authority or a company,
                                not by the insured person
- ``suva_party``                Suva (CNA, INSAI) is named in the parties block
- ``suva_appellant``            Suva brought the appeal
- ``manifestly_unfounded``      the court dismissed the appeal as manifestly unfounded (Art. 109 BGG)
- ``proposed_for_publication``  the star of the court's list; "unknown" when the list was not seen

Each signal carries the place it was read from. Measurements: ``docs/TRIAGE_SIGNALS.md``.
"""

from __future__ import annotations

import re

from src.schemas import Evidence, Signal
from src.triage.outer_gate import classify_area, header_subject

VERSION = "structural_signals@1"

_SUVA = re.compile(
    r"\b(?:Suva|SUVA|CNA|INSAI)\b|Schweizerische[nr]? Unfallversicherungsanstalt|Caisse nationale suisse d'assurance"
    r"|Istituto nazionale svizzero di assicurazione"
)
# The header ends where the facts or the reasoning begin.
_BODY_START = re.compile(
    r"\n\s*(?:Sachverhalt|Faits|Fatti|En fait|Ritenuto in fatto|Erwägungen|Erwägung|Considérant en droit|Considérants?"
    r"|En droit|Diritto|Considerando in diritto|Considerando|Nach Einsicht|Vu|Visto)\s*:?\s*\n"
)
_HEADER_FALLBACK = 2500
_BENCH = re.compile(r"(?:Besetzung|Composition|Composizione)(.*?)(?:Gerichtsschreiber|Greffi|Cancellier)", re.S)
_TITLES = re.compile(
    r"\b(?:Bundesrichter(?:in)?(?:nen)?|Mmes?|MM?\.|les|la|le|Juges?|fédéra(?:l|le|ux)|Giudic[ei]|federal[ei]"
    r"|Präsident(?:in)?|Président[e]?|Presidente|suppléant[e]?|nebenamtliche[rn]?|supplente"
    r"|als Einzelrichter(?:in)?|en qualité de juge unique)\b"
)
_NAME = re.compile(r"[A-ZÉ][a-zéèüöä]{2,}")
_PARTIES = re.compile(
    r"(?:Verfahrensbeteiligte|Participants à la procédure|Partecipanti al procedimento)(.*?)"
    r"\b(Beschwerdeführer(?:in)?(?:nen)?|Gesuchsteller(?:in)?|recourante?s?|requérante?s?|ricorrent[ei]|istante)\b",
    re.S,
)
_PERSON = re.compile(r"^\s*[A-Z]\.(?:[A-Z]\.)?_{4,}")  # an anonymised natural person: "A.________"
_INSTITUTION = re.compile(
    r"AG\b|SA\b|Versicher|[Aa]ssurance|[Aa]ssicurazion|Istituto|INSAI|CNA\b|IV-Stelle|Office|Ufficio|Bundesamt|Caisse|Suva|Stiftung|Anstalt"
    r"|Kasse|Fondation|Gemeinde|Sozial"
)
_UNFOUNDED = re.compile(
    r"offensichtlich unbegründet|manifestement (?:mal fondé|infondé)|manifestamente infondat"
    r"|Art\. 109 (?:Abs\. 2|al\. 2|cpv\. 2)"
)


def header(full_text: str) -> str:
    """The part of the ruling before the facts or the reasoning: court, bench, parties, subject."""
    match = _BODY_START.search(full_text)
    return full_text[: match.start()] if match else full_text[:_HEADER_FALLBACK]


def bench_size(head: str) -> tuple[int, tuple[int, int]] | None:
    """Number of judges named in the bench block, with the block's position; None when there is no block."""
    match = _BENCH.search(head)
    if not match:
        return None
    names = re.split(r",|\bund\b|\bet\b|\be\b", _TITLES.sub(" ", match.group(1)))
    return sum(1 for name in names if _NAME.search(name)), match.span(1)


def appellant(head: str) -> tuple[str, tuple[int, int]] | None:
    """The text naming who brought the appeal, with its position; None when the parties block is not found."""
    match = _PARTIES.search(head)
    return (match.group(1), match.span(1)) if match else None


def structural_signals(list_area: str | None, starred: bool | None, full_text: str | None) -> list[Signal]:
    """Every structural signal of one ruling, in a fixed order.

    ``list_area``: subject area from the court's list (may carry the publication star), or None.
    ``starred``: True/False when the court's list was seen, None when it was not.
    ``full_text``: the ruling's text, or None when there is none.
    """
    text = full_text or ""
    head = header(text) if text else ""
    signals: list[Signal] = []

    def add(name: str, value: bool | int | str, field: str, span: tuple[int, int] | None = None) -> None:
        evidence = Evidence(field=field, start=span[0], end=span[1]) if span else Evidence(field=field)
        signals.append(Signal(name=name, value=value, evidence=evidence))

    from_list = classify_area(list_area)
    area = from_list or classify_area(header_subject(text))
    add("area", area or "other", "sachgebiet" if from_list or not area else "header_subject")

    bench = bench_size(head)
    if bench:
        size, span = bench
        add("bench_size", size, "bench", span)
        add("single_judge", size == 1, "bench", span)
        add("five_judges", size >= 5, "bench", span)

    who = appellant(head)
    if who:
        segment, span = who
        is_person = bool(_PERSON.search(segment))
        add(
            "appeal_by_institution", (not is_person) and bool(_INSTITUTION.search(segment[:200])), "parties_block", span
        )
        add("suva_appellant", (not is_person) and bool(_SUVA.search(segment)), "parties_block", span)

    party = _SUVA.search(head)
    add("suva_party", bool(party), "parties_block", party.span() if party else None)

    unfounded = _UNFOUNDED.search(text)
    add("manifestly_unfounded", bool(unfounded), "full_text", unfounded.span() if unfounded else None)

    if starred is None and list_area and list_area.strip().endswith("*"):
        starred = True
    add("proposed_for_publication", "unknown" if starred is None else bool(starred), "star")
    return signals


def as_dict(signals: list[Signal]) -> dict[str, bool | int | float | str]:
    """Signal values by name."""
    return {signal.name: signal.value for signal in signals}
