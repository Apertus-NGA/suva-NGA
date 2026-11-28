# ruff: noqa: E501  (prompt texts are kept on one line each, as in reading_prompts.py)
"""Apertus readings inside a deterministic harness, each with its unharnessed twin (experiment).

One legal question (a ``Claim``) is asked in three ways, so the effect of the harness can be measured:

- ``zero``:    the question, one word Ja/Nein. No evidence asked. This is the "before".
- ``cited``:   Ja/Nein, and for a Ja the number of the consideration where it stands, chosen from the list of
               numbers code read in the ruling. Apertus must commit to a place.
- ``located``: Ja/Nein, and always the number of the consideration that matters most for the question.
               Code then looks for the claim's marker wording in that consideration, for every ruling.

Apertus never writes the evidence (it paraphrases and translates, measured 28 Nov): it points to a consideration
and code fetches the text. Two further readings follow the same split, Apertus locates and code measures:

- ``read_locate``:  the consideration that decides the dispute; code measures it (``measure``).
- ``read_article``: the provision that decides the dispute, alone (``zero``) or with its consideration
                    (``cited``); code checks that the provision is named in that consideration.

A failed call or an unusable answer gives ``None`` values, never a "no".
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from src.triage import evidence as ev
from src.triage import reading_prompts as p

ARMS = ("zero", "cited", "located")


@dataclass(frozen=True)
class Claim:
    name: str
    question: str
    markers: re.Pattern[str]  # searched in the normalised (casefolded) text of the cited consideration


PRACTICE = Claim(
    "practice",
    "Frage: Ändert, präzisiert oder klärt das Bundesgericht in diesem Urteil seine Rechtsprechung, oder entscheidet es eine Rechtsfrage, die es als offen oder neu bezeichnet?\n"
    "Zähle NICHT: die Wiedergabe oder blosse Anwendung gefestigter Rechtsprechung auf den Einzelfall.\n"
    "In den meisten Urteilen lautet die Antwort Nein.",
    re.compile(
        r"praxisänderung|änderung der (?:rechtsprechung|praxis)|präzisier|klarstell|klarzustellen|erstmals|offen ?gelassen|offen bleiben|"
        r"(?:bisher|bislang|noch) nicht (?:entschieden|geklärt|beantwortet)|grundsätzliche[rn]? bedeutung|festzuhalten ist|"
        r"changement de (?:jurisprudence|pratique)|précis(?:er|é|ion)|pour la première fois|laissée? (?:ouverte|indécise)|question de principe|"
        r"cambiamento d(?:i|ella) (?:giurisprudenza|prassi)|per la prima volta|lasciat[ao] apert"
    ),
)
LEGAL_ERROR = Claim(
    "legal_error",
    "Frage: Stellt das Bundesgericht fest, dass die Vorinstanz oder der Versicherer das Recht falsch angewendet hat (ein Rechtsfehler)?\n"
    "Zähle NICHT: eine andere Würdigung des Sachverhalts, der Arztberichte oder Gutachten dieses Falls, und die Abweisung der Beschwerde.\n"
    "In den meisten Urteilen lautet die Antwort Nein.",
    re.compile(
        r"verletzte? (?:damit |somit |demnach )?bundesrecht|bundesrecht verletzt|bundesrechtswidrig|rechtsfehlerhaft|zu unrecht|"
        r"viol(?:e|é|ation)[^.]{0,30}droit fédéral|contraire au droit fédéral|à tort|"
        r"viola[^.]{0,30}diritto federale|a torto"
    ),
)
TRANSFER = Claim(
    "transfer",
    "Frage: Betrifft die vom Bundesgericht entschiedene Streitfrage eine Regel, die auch in der Unfallversicherung gilt (z.B. Allgemeiner Teil ATSG, Invaliditätsgrad und Einkommensvergleich, Beweiswert von Gutachten, Kausalität, Revision und Wiedererwägung, Rückerstattung, Verfahren vor dem Versicherer)?\n"
    "Zähle NICHT: Fragen, die nur eine andere Versicherung betreffen (z.B. Eingliederungsmassnahmen der IV, Ergänzungsleistungen, Beiträge), und reine Prozessfragen vor Bundesgericht.",
    re.compile(
        r"\batsg\b|\blpga\b|\buvg\b|\blaa\b|\blainf\b|unfall|accident|infortun|invaliditätsgrad|einkommensvergleich|taux d'invalidité|"
        r"comparaison des revenus|grado d'invalidità|gutachten|expertise|perizia|kausal|causal|wiedererwägung|reconsidération|"
        r"riconsiderazione|rückerstattung|restitution|restituzione"
    ),
)
CLAIMS = {c.name: c for c in (PRACTICE, LEGAL_ERROR, TRANSFER)}

_ZERO = "Antworte mit genau einem Wort: Ja oder Nein."


def _two_lines(second: str, numbers: list[str]) -> str:
    return (
        f"Antworte in genau zwei Zeilen:\nZeile 1: Ja oder Nein\nZeile 2: {second}, gewählt aus dieser Liste: "
        + ", ".join(numbers)
    )


def answer_format(arm: str, numbers: list[str]) -> str:
    if arm == "zero":
        return _ZERO
    if arm == "cited":
        return _two_lines("bei Ja die Nummer der Erwägung, in der das steht", numbers) + "; bei Nein einen Bindestrich."
    if arm == "located":
        return _two_lines("die Nummer der Erwägung, die für diese Frage am wichtigsten ist", numbers) + "."
    raise ValueError(arm)


def _messages(ruling_text: str, question: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": p.SYS_L},
        {"role": "user", "content": f"{p.doc(p.sections(ruling_text))}\n\n{question}"},
    ]


def block(cons: list[tuple[str, str]], number: str) -> str:
    """Text of a consideration with its sub-considerations ("4" covers 4, 4.1, 4.2.1 ...)."""
    return "\n".join(t for n, t in cons if n == number or n.startswith(number + ".")).strip()


def _number(line: str, numbers: list[str]) -> str | None:
    m = re.search(r"\d{1,2}(?:\.\d{1,2}){0,3}", line)
    return m.group(0) if m and m.group(0) in numbers else None


def read_claim(client: Any, ruling_text: str, claim: Claim, arm: str, size: str = "small") -> dict[str, Any]:
    """P(Ja) of the claim; for ``cited`` / ``located`` also the consideration and code's marker check on it."""
    empty = {"p": None, "label": None, "consideration": None, "check": None, "evidence": ""}
    reasoning = p.sections(ruling_text)["reasoning"]
    cons = ev.considerations(reasoning)
    numbers = [n for n, _ in cons]
    if arm != "zero" and not numbers:
        return empty  # no numbered reasoning: nothing to point at, the reading is not asked
    first_only = arm == "zero"
    try:
        result = client.chat(
            _messages(ruling_text, f"{claim.question}\n\n{answer_format(arm, numbers)}"),
            max_tokens=1
            if first_only
            else 80,  # the 70B adds a sentence after the number; 24 cut 123 of 298 answers (G3)
            size=size,
            prompt_version=f"claim_{claim.name}_{arm}@1",
            logprobs=True,
            top_logprobs=20,
            first_token_only=first_only,
        )
    except Exception:  # noqa: BLE001  a failed reading stays empty, never a "no"
        return empty
    prob = ev.p_yes(result.logprobs)
    if prob is None:
        return empty
    if first_only:
        return {**empty, "p": prob, "label": "ja" if prob > 0.5 else "nein"}
    lines = [ln.strip() for ln in (result.content or "").strip().splitlines() if ln.strip()]
    label, _ = ev.parse(result.content)
    number = _number(" ".join(lines[1:]), numbers) if len(lines) > 1 else None
    if arm == "cited" and label != "ja":
        number = None
    text = block(cons, number) if number else ""
    check = bool(claim.markers.search(ev._norm(text))) if text else (False if arm == "cited" else None)
    return {"p": prob, "label": label, "consideration": number, "check": check, "evidence": text[:600]}


# -- Apertus locates the deciding consideration; code measures it -----------------------------------------------

_CASE_LAW = re.compile(r"\b(?:bge|atf|dtf) \d+ [ivx]+ \d+|\b\d[a-z]_\d+/\d{4}|\b[a-z]{1,2} \d+/\d{2}\b")
_ARTICLE = re.compile(
    r"\bart\.?\s*(\d+[a-z]*(?:bis|ter|quater)?)(?:\s*(?:abs|al|cpv|lit|let|lett|ziff|ch|satz|phr)\.?\s*\w+)*\s+([a-zäöü]{2,6})\b"
)
LAW_FAMILY = {
    **dict.fromkeys(("atsg", "lpga", "atsv", "opga"), "atsg"),
    **dict.fromkeys(("uvg", "laa", "lainf", "uvv", "olaa", "oainf", "mvg", "lam"), "uvg"),
    **dict.fromkeys(("ivg", "lai", "ivv", "rai", "oai"), "ivg"),
    **dict.fromkeys(("bgg", "ltf"), "bgg"),
}
SHARED = frozenset({"atsg", "uvg"})  # general part and accident / military law: holds for an accident insurer


def articles(text: str) -> list[tuple[str, str]]:
    """(article number, law family) of every provision named in the text; unknown laws are "other"."""
    return [(m.group(1), LAW_FAMILY.get(m.group(2), "other")) for m in _ARTICLE.finditer(ev._norm(text))]


def measure(text: str, total: int | None = None) -> dict[str, float]:
    """Code-read properties of a passage. Deterministic: the same text always gives the same numbers."""
    norm = ev._norm(text)
    laws = [fam for _, fam in articles(text)]
    return {
        "practice": float(bool(PRACTICE.markers.search(norm))),
        "error": float(bool(LEGAL_ERROR.markers.search(norm))),
        "case_law": math.log1p(len(_CASE_LAW.findall(norm))),
        "shared_law": float(any(f in SHARED for f in laws)),
        "length": math.log1p(len(norm)),
        "share": (len(text) / total) if total else 1.0,
    }


MEASURES = tuple(measure(""))
LOCATE_QUESTION = "Frage: In welcher Erwägung entscheidet das Bundesgericht die eigentliche Streitfrage dieses Falls (die tragende Erwägung, nicht Eintreten, Kognition oder Kosten)?\n\nAntworte nur mit der Nummer der Erwägung, gewählt aus dieser Liste: "


def read_locate(client: Any, ruling_text: str, size: str = "small") -> dict[str, Any]:
    empty: dict[str, Any] = {"consideration": None, "evidence": "", **dict.fromkeys(MEASURES)}
    reasoning = p.sections(ruling_text)["reasoning"]
    cons = ev.considerations(reasoning)
    numbers = [n for n, _ in cons]
    if not numbers:
        return empty
    try:
        result = client.chat(
            _messages(ruling_text, LOCATE_QUESTION + ", ".join(numbers) + "."),
            max_tokens=12,
            size=size,
            prompt_version="locate_deciding@1",
        )
    except Exception:  # noqa: BLE001
        return empty
    number = _number(result.content or "", numbers)
    if not number:
        return empty  # a number that is not in the ruling is no answer
    text = block(cons, number)
    return {"consideration": number, "evidence": text[:600], **measure(text, len(reasoning))}


def whole_ruling(ruling_text: str) -> dict[str, float]:
    """The code-only twin of ``read_locate``: the same measures on the whole reasoning, no Apertus."""
    return measure(p.sections(ruling_text)["reasoning"] or ruling_text)


ARTICLE_QUESTION = (
    "Frage: Welche Gesetzesbestimmung ist für den Entscheid der eigentlichen Streitfrage ausschlaggebend?\n\n"
)
_ARTICLE_FORM = (
    "in der Form: Art. <Nummer> <Abkürzung des Gesetzes>"  # no example article: the 8B repeated the example (28 Nov)
)
_ARTICLE_ZERO = "Antworte nur mit der Bestimmung, " + _ARTICLE_FORM


def read_article(client: Any, ruling_text: str, arm: str, size: str = "small") -> dict[str, Any]:
    """The deciding provision. ``cited``: with its consideration; code checks the provision is named there."""
    empty = {"article": None, "family": None, "shared": None, "consideration": None, "check": None, "in_ruling": None}
    reasoning = p.sections(ruling_text)["reasoning"]
    cons = ev.considerations(reasoning)
    numbers = [n for n, _ in cons]
    if arm == "cited" and not numbers:
        return empty
    fmt = (
        _ARTICLE_ZERO
        if arm == "zero"
        else "Antworte in genau zwei Zeilen:\nZeile 1: die Bestimmung, "
        + _ARTICLE_FORM
        + "\nZeile 2: die Nummer der Erwägung, in der das Gericht sie anwendet, gewählt aus dieser Liste: "
        + ", ".join(numbers)
        + "."
    )
    try:
        result = client.chat(
            _messages(ruling_text, ARTICLE_QUESTION + fmt), max_tokens=32, size=size, prompt_version=f"article_{arm}@2"
        )
    except Exception:  # noqa: BLE001
        return empty
    lines = [ln.strip() for ln in (result.content or "").strip().splitlines() if ln.strip()]
    named = articles(lines[0]) if lines else []
    if not named:
        return empty
    art, family = named[0]
    in_ruling = (art, family) in articles(reasoning or ruling_text)  # code's check on both arms: is it named at all
    out = {**empty, "article": art, "family": family, "shared": float(family in SHARED), "in_ruling": in_ruling}
    if arm == "zero":
        return out
    number = _number(" ".join(lines[1:]), numbers) if len(lines) > 1 else None
    text = block(cons, number) if number else ""
    check = (art, family) in articles(text)
    return {**out, "consideration": number, "check": check, "shared": float(family in SHARED and check)}


def most_cited_article(ruling_text: str) -> dict[str, Any]:
    """The code-only twin of ``read_article``: the provision named most often in the reasoning."""
    named = articles(p.sections(ruling_text)["reasoning"] or ruling_text)
    if not named:
        return {"article": None, "family": None, "shared": None}
    art, family = max(set(named), key=lambda a: (named.count(a), a))
    return {"article": art, "family": family, "shared": float(family in SHARED)}
