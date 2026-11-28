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
| recital          | the court's formula referring to the lower court's statement of the law                |
| review           | the standard of review: it cites BGG/LTF Art. 95, 97, 105 or 106                       |
| fragment         | under MIN_WORDS words                                                                  |

Every candidate gets an id `S1…Sn` (in reading order) and keeps the label of its passage, so a model can only
choose ids and code copies the sentence. A candidate also carries its voice: `lower_court` when the court reports
the lower court's reasoning (a consideration that opens with it, up to the court's own assessment), else `court`.
Such a sentence is kept, since Suva sometimes restates reasoning the court confirms (8C_311/2025 on the iterate
set), but who says it is made explicit when it is written, and it is never taken as the court's answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.summarize import finish
from src.summarize.refine import evidence
from src.summarize.refine.draft import split_sentences

VERSION = "candidates@5"
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
    r"|objecte|estime\s+que|considère\s+(?:pour\s+sa\s+part|que)|est\s+d'avis|ist\s+der\s+(?:Auffassung|Ansicht)"
    r"|vertritt\s+(?:demgegenüber\s+)?die\s+Auffassung|fa\s+valere|sostiene|censura|lamenta|ritiene"
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


def tags(sentence: str, voice: str = "court") -> list[str]:
    """Hints for the chooser: who speaks, whether the sentence cites law, states it in the court's formula, names a
    party."""
    out = ["lower court"] if voice == "lower_court" else []
    if evidence.articles(sentence):
        out.append("article")
    if _CASE_LAW.search(sentence):
        out.append("case law")
    if _FORMULA.search(sentence):
        out.append("rule formula")
    if _PARTY_NAMED.search(sentence):
        out.append("names a party")
    return out


# A party's complaint opened by a participle: "Se plaignant d'une violation …, la recourante observe".
_COMPLAINT_OPENS = re.compile(
    r"^(?:Se plaignant|Invoquant|Reprochant|Contestant|Faisant valoir|Lamentando|Facendo valere)\b"
)

# The court reporting the lower court's reasoning: a consideration that opens with it is the lower court's until
# the court gives its own assessment. Run x9 (28 Nov): "En conclusion, aucun acte illicite … n'était imputable"
# was the cantonal judge's conclusion, which the fiche presented as the court's.
_LOWER_COURT = (
    r"(?:Die Vorinstanz|Das kantonale Gericht|Das Versicherungsgericht|Das Sozialversicherungsgericht"
    r"|Die kantonalen Richter|La cour cantonale|La juridiction cantonale|Le tribunal cantonal|Le premier juge"
    r"|Les premiers juges|Les juges cantonaux|L'autorité précédente|L'instance précédente|La Corte cantonale"
    r"|Il Tribunale cantonale|I giudici cantonali|La Corte delle assicurazioni)"
)
_REASONED = (
    r"(?:erwog|hat erwogen|hielt fest|hat festgehalten|stellte fest|hat festgestellt|kam zum Schluss|gelangte|"
    r"begründete|verneinte|bejahte|a retenu|a considéré|a jugé|a estimé|a constaté|a admis|a nié|a exposé|a relevé|"
    r"ha ritenuto|ha considerato|ha accertato|ha stabilito|ha negato)"
)
_LOWER_OPENS = re.compile(rf"^(?:[^,.]{{0,40}},\s*)?{_LOWER_COURT}\b[^.]{{0,60}}?\b{_REASONED}\b", re.IGNORECASE)
# The court's own voice again: it assesses what it reported.
_COURT_OWN = re.compile(
    r"^(?:Dem ist|Dies ist|Diese (?:Beurteilung|Auffassung|Würdigung|Argumentation)|Das ist|Dies trifft|Es trifft"
    r"|Inwiefern|Entgegen|Was die|Das Bundesgericht|Cette (?:appréciation|argumentation|motivation|opinion|conclusion)"
    r"|Ce raisonnement|On ne (?:saurait|voit)|Il n'y a pas|Tel n'est|Contrairement|Le Tribunal fédéral|Or,|Quoi qu'"
    r"|Il Tribunale federale|Questa (?:valutazione|conclusione)|Non si|Orbene)",
    re.IGNORECASE,
)


# The articles of the Federal Supreme Court Act on the standard of review (what the court may examine).
_REVIEW = re.compile(r"(?:Art|art)\.\s*(?:95|96|97|105|106)\b.*\b(?:BGG|LTF)$")
# … and its wording, when the article stands in another sentence (run x16: 8C_311/2025)
_REVIEW_WORDS = re.compile(
    r"n'est pas lié par (?:les faits|l'état de fait|la constatation)|nicht an die [^.]{0,60}(?:Feststellung|Tatsachen)"
    r"[^.]{0,40}gebunden|non è vincolat\w* (?:dai fatti|dall'accertamento)"
    r"|prüft (?:frei|nur)[^.]{0,40}(?:Rechtsverletzung|Sachverhalt)|examine (?:librement|d'office)",
    re.IGNORECASE,
)


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
    voice: str = "court"  # "court" | "lower_court"


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
    if _PARTY_ARGUMENT.search(sentence) or _COMPLAINT_OPENS.search(sentence):
        return "party_argument"
    if label == "facts" and _PROCEEDINGS.search(sentence):
        return "proceedings"
    if _REPORTED.search(sentence):
        return "reported"
    if evidence._RECITAL.search(sentence):  # "darauf kann verwiesen werden", "il suffit d'y renvoyer"
        return "recital"
    if any(_REVIEW.search(a) for a in cited) or _REVIEW_WORDS.search(
        sentence
    ):  # run x16: "nicht an die … Tatsachen gebunden (Art. 97 Abs. 2 BGG)"
        return "review"
    return None


def candidates(text: str) -> Candidates:
    """The sentences of a ruling a fiche may restate, numbered S1…Sn, and every other one with its reason."""
    parts = evidence.passages(text)
    merits = finish.outcome_kind(text) in ("rejected", "admitted", "partial")  # as record.py
    _, excluded = evidence.rule_candidates(parts, merits)
    kept: list[Candidate] = []
    dropped: list[tuple[str, str, str]] = []
    current, opened, reporting = None, False, False
    for label, sentence in sentences(parts):
        if label != current:
            current, opened, reporting = label, False, False
        if not opened and len(sentence.split()) >= MIN_WORDS:  # the first real sentence, not the number "4."
            opened = True
            reporting = label.startswith("E.") and bool(_LOWER_OPENS.search(sentence))
        elif reporting and _COURT_OWN.search(sentence):
            reporting = False
        why = reason(label, sentence, excluded)
        if why:
            dropped.append((label, why, sentence))
        else:
            kept.append(Candidate(f"S{len(kept) + 1}", label, sentence, "lower_court" if reporting else "court"))
    return Candidates(tuple(kept), tuple(dropped))
