"""The ruling's sentences a Suva fiche can be built from, and the reason code for every one left out (G5).

Suva writes a fiche mostly from a handful of the ruling's own sentences, lightly adapted, taken from the court's
considerations and, less often, from the facts (docs/EXTRACT.md §1). Code first removes what such a fiche never
restates, by legal category, never by a word list learnt from Suva's texts:

| reason           | what                                                                                   |
|------------------|----------------------------------------------------------------------------------------|
| operative        | the operative part: code writes the outcome sentence (finish.py)                       |
| admissibility    | consideration 1 when the ruling decides the merits                                     |
| costs            | the last consideration when it settles costs                                           |
| procedural_law   | a sentence whose only articles are of the Federal Supreme Court Act (BGG, LTF)         |
| citation         | a sentence that is nothing but references to other rulings or literature               |
| party_argument   | a sentence that reports what a party argues, not what the court holds                  |
| proceedings      | a sentence of the facts about the filings before the Federal Supreme Court             |
| reported         | reported speech (sei, habe, serait, aurait): a party's or the lower court's position   |
| fragment         | under MIN_WORDS words                                                                  |

Every candidate gets an id `S1…Sn` (in reading order) and keeps the label of its passage, so a model can only
choose ids and code copies the sentence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.summarize import finish
from src.summarize.refine import evidence
from src.summarize.refine.draft import split_sentences

VERSION = "candidates@3"
MIN_WORDS = 6

# A court sentence quoting a party: "Der Beschwerdeführer rügt …", "La recourante soutient que …". The verbs are
# the ones the court uses to report an argument; the court's own holding uses other ones.
_PARTY = (
    r"(?:Der|Die)\s+(?:Beschwerdef(?:ü|ue)hrer(?:in)?|Beschwerdegegner(?:in)?|Versicherte|Suva|Vorinstanz)"
    r"|(?:Le|La|L')\s*(?:recourant|recourante|intimé|intimée|assuré|assurée|CNA|Suva|autorité précédente)"
    r"|(?:Il|La)\s+ricorrente"
)
_ARGUES = (
    r"(?:macht|machen)\s+geltend|rügt|rügen|bringt\s+vor|wendet\s+ein|beanstandet|argumentiert|vertritt\s+die\s+"
    r"Auffassung|hält\s+dafür|bestreitet|soutient|fait\s+valoir|reproche|invoque|conteste|allègue|se\s+plaint"
    r"|objecte|estime\s+que|fa\s+valere|sostiene|censura|lamenta"
)
_PARTY_ARGUMENT = re.compile(rf"^\s*(?:{_PARTY})\b[^.;:]{{0,80}}?\b(?:{_ARGUES})\b", re.IGNORECASE)

# The facts' last part: who appealed, what they ask, who answered. Suva's fiche states none of it.
_PROCEEDINGS = re.compile(
    r"\b(?:erhebt|erhob|führt|führte)\s+(?:[^.]{0,60}\s)?Beschwerde|\bbeantragt|\bbeantragte|\bschliesst\s+auf"
    r"|verzichtet(?:e)?\s+auf\s+(?:eine\s+)?(?:Vernehmlassung|Stellungnahme)|lässt\s+sich\s+nicht\s+vernehmen"
    r"|\binterjet\w*\s+(?:un\s+)?recours|\bconclu\w*\s+(?:principalement|à\s+titre\s+subsidiaire|au\s+rejet|implicitement"
    r"|à\s+l'annulation|à\s+la\s+réforme)|\bà\s+titre\s+subsidiaire,?\s+(?:il|elle)\s+conclut|renoncé\s+à\s+se\s+déterminer"
    r"|se\s+réfère\s+(?:purement\s+et\s+simplement\s+)?à\s+son\s+(?:jugement|arrêt)|n'a\s+pas\s+été\s+ordonné"
    r"|propone\s+ricorso|chiede\s+(?:in\s+via\s+principale|l'annullamento)|rinunciat\w*\s+a\s+(?:esprimersi|determinarsi)",
    re.IGNORECASE,
)

# Reported speech: the court restating a position it then answers. Measured on the iterate set (28 Nov): in 16 %
# of the other candidates, in 3 % of the sentences Suva's fiches restate.
_REPORTED = re.compile(
    r"\b(?:sei|seien|habe|hätte|hätten|wäre|wären|serait|seraient|aurait|auraient|sarebbe|avrebbe)\b"
)

# What a sentence holds, read by code and shown to Apertus as a hint (choose.py), never as a decision.
_CASE_LAW = re.compile(r"\b(?:BGE|ATF|DTF)\s+\d+|\b\d[A-Z]_\d+/\d{4}")
_FORMULA = re.compile(
    r"Nach (?:der|ständiger) Rechtsprechung|Gemäss (?:der )?Rechtsprechung|Praxisgemäss|Selon (?:la|une) jurisprudence"
    r"|D'après la jurisprudence|Il est de jurisprudence|Aux termes de l'art|Selon l'art|Gemäss Art|Nach Art"
    r"|En vertu de l'art|Conformément à l'art|Secondo la giurisprudenza|Giusta l'art",
    re.IGNORECASE,
)
_PARTY_NAMED = re.compile(
    r"recourante?|intimée?|Beschwerdef(?:ü|ue)hrer|Beschwerdegegner|_{3,}|Vorinstanz|cour cantonale|juridiction "
    r"cantonale|tribunal cantonal|kantonale Gericht|premier juge|ricorrente|Corte cantonale",
    re.IGNORECASE,
)


def tags(sentence: str) -> list[str]:
    """Hints for the chooser: whether the sentence cites law, states it in the court's formula, names a party."""
    out = []
    if evidence.articles(sentence):
        out.append("article")
    if _CASE_LAW.search(sentence):
        out.append("case law")
    if _FORMULA.search(sentence):
        out.append("rule formula")
    if _PARTY_NAMED.search(sentence):
        out.append("names a party")
    return out


# References to other rulings and literature: removed before counting what the sentence says itself.
_CITATION = re.compile(
    r"\b(?:BGE|ATF|DTF)\s+\d+\s+[IV]+\s+\d+(?:\s+(?:E\.|consid\.)\s*[\d.]+)?"
    r"|\b(?:Urteile?|arrêts?|sentenz[ae])\s+(?:des\s+Bundesgerichts\s+|du\s+Tribunal\s+fédéral\s+)?"
    r"\d[A-Z]_\d+/\d{4}(?:\s+vom\s+[\d.]+\s*\w*\s*\d{0,4}|\s+du\s+\d+\w*\s+\w+\s+\d{4})?(?:\s+(?:E\.|consid\.)\s*[\d.]+)?"
    r"|\b\d[A-Z]_\d+/\d{4}"
    r"|\b(?:E\.|consid\.|Erw\.)\s*[\d.]+"
    r"|\b(?:mit\s+Hinweisen?|avec\s+(?:les\s+)?(?:références|renvois)(?:\s+citée?s)?|und\s+dort\s+zitierte\s+\w+"
    r"|vgl\.|voir|cf\.|siehe|n\.\s*\d+|N\.\s*\d+|Rz\.\s*\d+|p\.\s*\d+|S\.\s*\d+|ss\.|ff\.)"
)


@dataclass(frozen=True)
class Candidate:
    id: str
    label: str
    text: str


@dataclass(frozen=True)
class Candidates:
    kept: tuple[Candidate, ...]
    dropped: tuple[tuple[str, str, str], ...]  # (label, reason, sentence)

    def get(self, cid: str) -> Candidate:
        return next(c for c in self.kept if c.id == cid)

    def reasons(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for _, reason, _ in self.dropped:
            counts[reason] = counts.get(reason, 0) + 1
        return counts


def sentences(parts: dict[str, str]) -> list[tuple[str, str]]:
    """Every sentence of the ruling with its passage label, the consideration number ("2.1") taken off."""
    out = []
    for label, body in parts.items():
        for paragraph in re.split(r"\n\s*\n", body):
            flat = " ".join(paragraph.split())
            if not flat:
                continue
            for sentence in split_sentences(flat):
                sentence = evidence._HEADING.sub("", sentence).strip()
                if sentence:
                    out.append((label, sentence))
    return out


def _own_words(sentence: str) -> int:
    """Words of the sentence once references to rulings and literature are taken out."""
    bare = re.sub(r"[()\[\];,]", " ", _CITATION.sub(" ", sentence))
    return len(re.findall(r"[^\W\d_]{2,}", bare))


def reason(label: str, sentence: str, excluded: dict[str, str]) -> str | None:
    """Why a sentence cannot be in a Suva fiche, or None when it can."""
    if label == "operative":
        return "operative"
    top = label.split(".")[0] + "." + label.split(".")[1] if label.startswith("E.") else label
    if excluded.get(top) in ("admissibility", "costs") or excluded.get(label) in ("admissibility", "costs"):
        return excluded.get(top) or excluded.get(label)
    cited = evidence.articles(sentence)
    if cited and all(a.endswith(evidence._PROCEDURAL) for a in cited):
        return "procedural_law"
    if len(sentence.split()) < MIN_WORDS:
        return "fragment"
    if _CITATION.search(sentence) and _own_words(sentence) < MIN_WORDS:  # a short fact without a reference stays
        return "citation"
    if _PARTY_ARGUMENT.search(sentence):
        return "party_argument"
    if label == "facts" and _PROCEEDINGS.search(sentence):
        return "proceedings"
    if _REPORTED.search(sentence):
        return "reported"
    return None


def candidates(text: str) -> Candidates:
    """The sentences of a ruling a fiche may restate, numbered S1…Sn, and every other one with its reason."""
    parts = evidence.passages(text)
    merits = finish.outcome_kind(text) in ("rejected", "admitted", "partial")  # as record.py
    _, excluded = evidence.rule_candidates(parts, merits)
    kept: list[Candidate] = []
    dropped: list[tuple[str, str, str]] = []
    for label, sentence in sentences(parts):
        why = reason(label, sentence, excluded)
        if why:
            dropped.append((label, why, sentence))
        else:
            kept.append(Candidate(f"S{len(kept) + 1}", label, sentence))
    return Candidates(tuple(kept), tuple(dropped))
