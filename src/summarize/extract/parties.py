"""Who the parties are, read by code from the ruling: the insured person's gender, who appealed, the insurer.

Every sentence is written by its own call (write.py), so nothing keeps the parties consistent across them: run x4
(28 Nov) named one insured "der Versicherten", "dem Versicherten" and "die Beschwerdegegnerin" in one fiche. Code
reads the facts once and every call gets the same description: name the parties by their role in the insurance,
the insurer by the name the ruling uses (docs/LESSONS.md: the model said "Suva" for another insurer).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.summarize.refine import evidence

_FEMALE = re.compile(
    r"\b(?:die Versicherte|der Versicherten\b(?! Person)|die Beschwerdeführerin|l'assurée|la recourante|l'intéressée"
    r"|l'assicurata|la ricorrente)\b",
    re.IGNORECASE,
)
_MALE = re.compile(
    r"\b(?:der Versicherte|dem Versicherten|den Versicherten|der Beschwerdeführer\b(?!in)|l'assuré\b(?!e)"
    r"|le recourant|l'intéressé\b(?!e)|l'assicurato|il ricorrente)\b",
    re.IGNORECASE,
)
# An insurer's name: the brand, then only words that belong to a name (capitalised, or a legal form), and an IV
# office with its canton. Never the words that follow it in the sentence (run x4 read "IV-Stelle die Kosten").
_NAME_TAIL = r"(?:\s+(?:[A-ZÄÖÜÉ][\w-]+|SA|AG|SpA|Assurances?|Versicherungen?|Accidents|Unfall))*"
_INSURER = re.compile(
    r"\b(?:Suva|SUVA|CNA|Allianz|AXA|Helsana|Zurich|Generali|Bâloise|Baloise|Mobiliar|Visana|CSS|Sanitas|SWICA|Vaudoise"
    r"|Groupe Mutuel|Concordia|Assura)\b"
    + _NAME_TAIL
    + r"|\b(?:IV-Stelle|office AI|Office de l'assurance-invalidité|Ufficio AI)"
    r"(?:\s+(?:des Kantons|du canton|pour le canton|de la République et canton|del Cantone)"
    r"\s+(?:de\s+|du\s+|d')?[A-ZÄÖÜÉ][\w-]+)?"
)
_APPEAL = re.compile(
    r"([^.]{0,120}?)\b(?:erhebt|erhob|führt|führte|reicht|reichte)\b[^.]{0,60}?Beschwerde"
    r"|([^.]{0,120}?)\binterjet\w*\s+(?:un\s+)?recours|([^.]{0,120}?)\b(?:propone|ha proposto)\s+ricorso",
)


@dataclass(frozen=True)
class Parties:
    insured_female: bool | None
    appellant: str | None  # "insured" | "insurer" | None
    insurer: str | None

    def describe(self, language: str) -> str:
        """The line every writing call gets."""
        if language == "de":
            person = {True: "die Versicherte (eine Frau)", False: "der Versicherte (ein Mann)"}.get(
                self.insured_female, "die versicherte Person"
            )
            insurer = self.insurer or "der Versicherer"
            roles = {
                "insured": f"Beschwerde führt {person}, die Gegenpartei ist {insurer}",
                "insurer": f"Beschwerde führt {insurer}; {person} ist die Gegenpartei",
            }.get(self.appellant or "", "")
        else:
            person = {True: "l'assurée (une femme)", False: "l'assuré (un homme)"}.get(
                self.insured_female, "la personne assurée"
            )
            insurer = self.insurer or "l'assureur"
            roles = {
                "insured": f"le recours est de {person}, l'intimé est {insurer}",
                "insurer": f"le recours est de {insurer}; {person} est l'intimé(e)",
            }.get(self.appellant or "", "")
        line = f"The parties: the insured person is {person}; the insurer is {insurer}"
        line += f" ({roles})" if roles else ""
        return (
            line + ". Name them by their role in the insurance (the insured person, the insurer by its name), not by "
            "their role in the proceedings, and keep the insured person's gender."
        )


_HEADING = re.compile(r"(?:Verfahrensbeteiligte|Participants à la procédure|Partecipanti al procedimento)(.*?)"
                      r"(?:Gegenstand|Objet|Oggetto)\b", re.DOTALL)  # fmt: skip
_SIDES = re.compile(r"\s(?:gegen|contre|contro)\s")
_ROLE = re.compile(
    r"\b(Beschwerdef(?:ü|ue)hrer(?:in)?|Beschwerdegegner(?:in)?|recourante?|intimée?|ricorrente|opponente|resistente)\b"
)
_FEMININE_ROLE = re.compile(r"(?:in|ante|ée)$")
_SUVA_NAMES = re.compile(
    r"Suva|SUVA|\bCNA\b|INSAI|Unfallversicherungsanstalt|Caisse nationale suisse|Istituto nazionale svizzero di assic"
)
_ANONYMISED = re.compile(r"^[A-Z]\.?_{3,}|^[A-Z]\.\s?[A-Z]\.?_{2,}")


def _heading(text: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]]] | None:
    """(appellant side, other side), each a list of (name, role word), from the ruling's list of parties. Every
    party there ends with its role word ("…, Beschwerdeführerin,"): the piece before it is the party, its first
    comma-separated part the name."""
    found = _HEADING.search(text[:8000])
    if not found:
        return None
    block = " ".join(found.group(1).split())
    sides = _SIDES.split(block, maxsplit=1)
    if len(sides) != 2:
        return None
    out = []
    for side in sides:
        parties, start = [], 0
        for role in _ROLE.finditer(side):
            piece = side[start : role.start()].strip(" ,.")
            if piece:
                parties.append((piece.split(",")[0].strip(), role.group(1)))
            start = role.end()
        out.append(parties)
    return (out[0], out[1]) if out[0] and out[1] else None


def read(text: str) -> Parties:
    """The parties from the list at the head of the ruling (who appeals stands before "gegen"); the facts and
    considerations only when that list cannot be read. Run x4: the heading named HDI Global SE as the appellant of
    8C_676/2024, which neither the facts nor the considerations name."""
    parts = evidence.passages(text)
    facts = parts.get("facts", "") or text[:6000]
    body = facts + " " + " ".join(v for k, v in parts.items() if k.startswith("E."))
    heading = _heading(text)
    gender, appellant, insurer = None, None, None
    if heading:
        for side_name, side in (("appellant", heading[0]), ("other", heading[1])):
            for name, role in side:
                company = re.search(r"\b(?:AG|SA|GmbH|Sàrl|SpA|Sagl)\b", name)
                if _ANONYMISED.match(name) and company and insurer is None:
                    insurer = "the insurer (anonymised)"
                    appellant = "insurer" if side_name == "appellant" else appellant
                elif _ANONYMISED.match(name) and gender is None:
                    gender = (
                        bool(_FEMININE_ROLE.search(role))
                        if role not in ("ricorrente", "opponente", "resistente", "")
                        else None
                    )
                    if side_name == "appellant":
                        appellant = "insured"
                elif insurer is None:
                    insurer = "Suva" if _SUVA_NAMES.search(name) else name
                    if side_name == "appellant":
                        appellant = "insurer"
    if gender is None:
        female, male = len(_FEMALE.findall(body)), len(_MALE.findall(body))
        gender = None if female == male or max(female, male) < 2 else female > male
    if insurer is None:
        named = [" ".join(m.group(0).split()) for m in _INSURER.finditer(body)]
        named = ["Suva" if n.upper().startswith(("CNA", "SUVA")) else n for n in named]  # one institution, two names
        insurer = max(dict.fromkeys(named), key=named.count) if named else None
    if appellant is None:
        for match in _APPEAL.finditer(" ".join(facts.split())):
            subject = next(g for g in match.groups() if g is not None)
            appellant = "insurer" if _INSURER.search(subject[-120:]) else "insured"
    return Parties(gender, appellant, insurer)
