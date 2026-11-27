# SPDX-License-Identifier: Apache-2.0
"""Closed sets of ids the model may choose from, and exact (never fuzzy) resolution of what it wrote.

Golden rule G1: identifiers never come from Apertus; it may only *choose* ids from a list we give it.
An :class:`IdTable` is that list for one call. It accepts a few deterministic spellings of an offered
id (case, zero padding, the court's own consideration number with its ``E.``/``consid.`` prefix) and
nothing else: no edit distance, no "closest id". A spelling that matches two ids is rejected as
ambiguous. Seen on Keera (27 Nov pilot): the 8B used the ``E. x`` format in only 15 of 33 replies
(often writing bare numbers), and 11 of its 100 cited numbers did not exist in the ruling.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

__all__ = ["IdTable", "Resolution", "consideration_table", "NONE_ID"]

# Prefixes that announce a court consideration number, DE/FR/IT, with or without a dot.
_E_PREFIX = re.compile(
    r"^(?:erwägung|erw|considérant|considerant|considerando|consid|cons|e)(?![a-zà-ÿ])\.?\s*",
    re.I,
)
_LOCAL = re.compile(r"^([a-z]{1,3})0*(\d+)$", re.I)  # c3, C03, a12


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).strip().strip("[](){}<>«»„“\"'`").strip()
    return re.sub(r"\s+", " ", s)


@dataclass(frozen=True)
class Resolution:
    """Result of :meth:`IdTable.resolve`: the canonical id, or ``None`` with a reason code."""

    canonical: str | None
    reason: str | None = None  # "not_offered" | "ambiguous" | "empty" | "not_a_string"


@dataclass
class IdTable:
    """The ids offered to the model in one call, with their accepted aliases.

    Args:
        ids: Canonical ids in the order shown to the model (for example ``["c1", "c2"]``).
        aliases: Optional extra spellings per canonical id (for example the court number ``"4.2"``).

    The table is built by code from the source record; the model never adds to it.
    """

    ids: list[str]
    aliases: Mapping[str, Iterable[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if len(set(self.ids)) != len(self.ids):
            raise ValueError("duplicate canonical ids")
        self._index: dict[str, set[str]] = {}
        for cid in self.ids:
            self._add(cid, cid)
            m = _LOCAL.match(cid)
            if m:
                self._add(f"{m.group(1)}{int(m.group(2))}", cid)
        for cid, names in self.aliases.items():
            if cid not in self.ids:
                raise ValueError(f"alias for unknown id {cid!r}")
            for name in names:
                self._add(name, cid)

    def _add(self, spelling: str, cid: str) -> None:
        self._index.setdefault(_fold(spelling).casefold(), set()).add(cid)

    def resolve(self, raw: object) -> Resolution:
        """Map what the model wrote onto an offered id, exactly, or explain why not."""
        if not isinstance(raw, str):
            return Resolution(None, "not_a_string")
        s = _fold(raw)
        if not s:
            return Resolution(None, "empty")
        keys = [s.casefold()]
        m = _LOCAL.match(s)
        if m:
            keys.append(f"{m.group(1)}{int(m.group(2))}".casefold())
        if _E_PREFIX.match(s) and not _LOCAL.match(s):
            bare = _E_PREFIX.sub("", s, count=1).rstrip(".")
            if bare:
                keys += [f"e. {bare}".casefold(), bare.casefold()]
        elif s.endswith(".") and "." in s[:-1]:
            keys.append(s.rstrip(".").casefold())  # "4.2." -> "4.2"
        for key in keys:
            hits = self._index.get(key)
            if hits:
                if len(hits) > 1:
                    return Resolution(None, "ambiguous")
                return Resolution(next(iter(hits)))
        return Resolution(None, "not_offered")

    def __contains__(self, cid: object) -> bool:
        return cid in self.ids


#: Sentinel id offered when "nothing in the text supports it" must be a valid answer (abstention).
NONE_ID = "none"


def consideration_table(considerations: Iterable[Mapping[str, str]], *, none_option: bool = False) -> IdTable:
    """Build the table for a ruling's considerations.

    Each item needs ``id`` (``c1``, ``c2``, ... in document order) and ``e_number`` (the court's own
    numbering, for example ``"4.2"``). The court number is accepted as an alias only when it is
    dotted (``"4.2"``) or written with a consideration prefix (``"E. 4"``, ``"consid. 4"``): a bare
    ``"4"`` would be ambiguous with the position ``c4`` and is therefore not an alias.

    With ``none_option=True`` the sentinel :data:`NONE_ID` is offered too, so that abstaining is a
    valid choice under strict decoding (a schema without an abstention value makes the model fill
    the field anyway: 15/15 and 14/15 fills in another team's test).
    """
    ids, aliases = [], {}
    for item in considerations:
        cid, num = item["id"], str(item.get("e_number") or "").strip().rstrip(".")
        ids.append(cid)
        names = set()
        if num:
            names |= {f"E. {num}", f"E.{num}", f"consid. {num}", f"Erw. {num}", f"cons. {num}"}
            if "." in num:
                names.add(num)
        aliases[cid] = names
    if none_option:
        ids.append(NONE_ID)
        aliases[NONE_ID] = {"null", "keine", "aucun", "aucune", "nessuno", "nessuna"}
    return IdTable(ids, aliases)
