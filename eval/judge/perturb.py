"""Controlled defects: each function damages a good summary in the way ONE criterion must catch.

They build the judge's validation set (docs/JUDGE.md §5). A summary written by Suva's experts in the ruling's
language is the positive case; the same text after one of these edits is a negative case whose true label is
known by construction. The edits are generic word lists and sentences of our own: no Suva text is stored
here. A function returns None when the edit does not apply to that text.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from eval.judge.checks import sentences


@dataclass(frozen=True)
class Context:
    language: str  # language of the text being damaged
    parallel: str = ""  # the same summary in the other language
    outcome: str = ""  # outcome recorded for the ruling: dismissed, approved, partial_approval, inadmissible


Edit = Callable[[str, Context], str | None]

OUTCOME_SENTENCE = {
    "de": {
        "dismissed": "Die Beschwerde wird abgewiesen.",
        "approved": "Die Beschwerde wird gutgeheissen.",
        "partial_approval": "Die Beschwerde wird teilweise gutgeheissen.",
        "inadmissible": "Auf die Beschwerde wird nicht eingetreten.",
    },
    "fr": {
        "dismissed": "Le recours est rejeté.",
        "approved": "Le recours est admis.",
        "partial_approval": "Le recours est partiellement admis.",
        "inadmissible": "Le recours est irrecevable.",
    },
}
OPPOSITE = {
    "dismissed": "approved",
    "approved": "dismissed",
    "partial_approval": "dismissed",
    "inadmissible": "approved",
}

FOREIGN_TERMS = {
    "de": [
        (r"\bEinspracheentscheid", "Widerspruchsbescheid"),
        (r"\bEinsprache\b", "Widerspruch"),
        (r"\bBeschwerde\b", "Berufung"),
        (r"\bInvalidenrente\b", "Erwerbsminderungsrente"),
        (r"\bIntegritätsentschädigung\b", "Schmerzensgeld"),
        (r"\bTaggeld", "Krankengeld"),
        (r"\bkantonale Gericht\b", "Landessozialgericht"),
        (r"\bVorinstanz\b", "Unterinstanz"),
        (r"\bGutachten", "Expertise"),
        (r"\bValideneinkommen", "Einkommen ohne Unfall"),
        (r"\bInvalideneinkommen", "Einkommen mit Behinderung"),
    ],
    "fr": [
        (r"\bdécision sur opposition\b", "décision de réclamation"),
        (r"\bopposition\b", "réclamation"),
        (r"\brecours\b", "appel"),
        (r"\brente d[’']invalidité\b", "pension d'invalidité"),
        (r"\bindemnité pour atteinte à l[’']intégrité\b", "dommages-intérêts pour préjudice corporel"),
        (r"\bindemnités? journalières?\b", "allocation quotidienne"),
        (r"\brevenu sans invalidité\b", "salaire d'avant l'accident"),
        (r"\brevenu d[’']invalide\b", "salaire de personne handicapée"),
        (
            r"\b(juridiction cantonale|[Tt]ribunal cantonal|[Cc]our cantonale|premiers juges)\b",
            "tribunal de grande instance",
        ),
        (r"\bvraisemblance prépondérante\b", "forte probabilité"),
    ],
}
FLIPS = {
    "de": [
        (r"\bselten\b", "regelmässig"),
        (r"\bnicht ausnahmslos\b", "ausnahmslos"),
        (r"\bgrundsätzlich\b", "ausnahmslos"),
        (r"\blässt das Bundesgericht offen\b", "bejaht das Bundesgericht"),
        (r"\boffen gelassen\b", "bejaht"),
        (r"\bkein Bundesrecht verletzt\b", "Bundesrecht verletzt"),
        (r"\bverbietet sich\b", "ist zulässig"),
        (r"\bgenügen nicht\b", "genügen"),
        (r"\bkumulativ\b", "alternativ"),
        (r"\bist zu verneinen\b", "ist zu bejahen"),
        (r"\bnicht erfüllt\b", "erfüllt"),
        (r"\bin der Regel\b", "ausnahmslos"),
    ],
    "fr": [
        (r"\brarement\b", "régulièrement"),
        (r"\bne suffisent pas\b", "suffisent"),
        (r"\bne suffit pas\b", "suffit"),
        (r"\bn[’']a (donc )?pas violé\b", "a violé"),
        (r"\ben principe\b", "dans tous les cas"),
        (r"\bcumulativement\b", "alternativement"),
        (r"\bà raison\b", "à tort"),
        (r"\bn[’']est pas remplie\b", "est remplie"),
        (r"\bne lient pas\b", "lient"),
        (r"\bexceptionnellement\b", "régulièrement"),
        (r"\b[Ii]l est interdit\b", "Il est permis"),
        (r"\bne tranche pas\b", "tranche par l'affirmative"),
    ],
}
SENTENCE = {
    "opinion": {
        "de": " Meiner Meinung nach ist das ein ziemlich harter Entscheid, merken Sie sich das gut!",
        "fr": " À mon avis, c'est une décision franchement sévère, retenez bien cela !",
    },
    "assistant": {
        "de": "Gerne fasse ich das Urteil für Sie zusammen. ",
        "fr": "Voici volontiers le résumé de l'arrêt pour vous. ",
    },
    "boilerplate": {
        "de": " Die Gerichtskosten von Fr. 800.- werden der unterliegenden Partei auferlegt. Dieses Urteil wird den"
        " Parteien, dem kantonalen Gericht und dem Bundesamt für Gesundheit schriftlich mitgeteilt.",
        "fr": " Les frais judiciaires, arrêtés à 800 fr., sont mis à la charge de la partie qui succombe. Le présent"
        " arrêt est communiqué aux parties, à la juridiction cantonale et à l'Office fédéral de la santé publique.",
    },
    "invented_fact": {
        "de": " Die versicherte Person war zum Zeitpunkt des Ereignisses 58 Jahre alt"
        " und arbeitete als Dachdecker in Chur.",
        "fr": " La personne assurée était âgée de 58 ans au moment de l'événement"
        " et travaillait comme couvreur à Coire.",
    },
    "invented_holding": {
        "de": " Das Bundesgericht hält zudem fest, dass diese Rechtsprechung ohne Weiteres auch für die"
        " Militärversicherung und die berufliche Vorsorge gilt.",
        "fr": " Le Tribunal fédéral précise en outre que cette jurisprudence vaut sans autre également pour"
        " l'assurance militaire et la prévoyance professionnelle.",
    },
    "invented_reference": {
        "de": " (Art. 113 Abs. 4 UVV; E. 12.6)",
        "fr": " (art. 113 al. 4 OLAA ; consid. 12.6)",
    },
    "stub": {
        "de": "Der Versicherer verneinte seine Leistungspflicht. Das kantonale Gericht beurteilte die dagegen"
        " erhobene Beschwerde. Das Bundesgericht prüfte die Vorbringen der beschwerdeführenden Partei.",
        "fr": "L'assureur a nié son obligation de prester. La juridiction cantonale a statué sur le recours formé"
        " contre cette décision. Le Tribunal fédéral a examiné les griefs de la partie recourante.",
    },
}


def _replace_all(text: str, pairs: list[tuple[str, str]], limit: int | None = None) -> str | None:
    """Applies the word pairs; a word that opens a sentence keeps its capital. None when nothing matched."""
    done = 0
    for pattern, replacement in pairs:
        lower_start = pattern.startswith(r"\b") and pattern[2].islower()

        def swap(match: re.Match[str], replacement: str = replacement, lower_start: bool = lower_start) -> str:
            capital = lower_start and match.group(0)[0].isupper()
            return replacement[0].upper() + replacement[1:] if capital else replacement

        text, n = re.subn(_any_initial(pattern), swap, text, count=limit or 0)
        done += n
        if limit and done >= limit:
            break
    return text if done else None


def _any_initial(pattern: str) -> str:
    """`\\bselten` also matches `Selten`: a pattern that starts with a lower-case letter accepts its capital."""
    if pattern.startswith(r"\b") and pattern[2].islower():
        return rf"\b[{pattern[2]}{pattern[2].upper()}]{pattern[3:]}"
    return pattern


def foreign_legal_terms(text: str, ctx: Context) -> str | None:
    return _replace_all(text, FOREIGN_TERMS[ctx.language])


def opinion_and_address(text: str, ctx: Context) -> str | None:
    return text + SENTENCE["opinion"][ctx.language]


def assistant_voice(text: str, ctx: Context) -> str | None:
    return SENTENCE["assistant"][ctx.language] + text


def other_language_sentence(text: str, ctx: Context) -> str | None:
    """One sentence of the text replaced by a sentence in the other language (the same one when the two
    texts run in parallel, else the middle sentence of the other text)."""
    own, other = sentences(text), [s for s in sentences(ctx.parallel) if len(s) > 40]
    if len(own) < 2 or not other:
        return None
    index = len(own) // 2
    foreign = sentences(ctx.parallel)[index] if len(sentences(ctx.parallel)) == len(own) else other[len(other) // 2]
    return text.replace(own[index], foreign, 1)


def boilerplate_and_repeat(text: str, ctx: Context) -> str | None:
    last = sentences(text)[-1]
    return text + SENTENCE["boilerplate"][ctx.language] + " " + last


def altered_number(text: str, ctx: Context) -> str | None:
    match = re.search(r"\b(\d{1,2})\s?%", text)
    if match:
        return text[: match.start(1)] + str(int(match.group(1)) + 17) + text[match.end(1) :]
    match = re.search(r"\b(20[012]\d)\b", text)
    if match:
        return text[: match.start(1)] + str(int(match.group(1)) - 4) + text[match.end(1) :]
    return None


def invented_fact(text: str, ctx: Context) -> str | None:
    first = sentences(text)[0]
    return text.replace(first, first + SENTENCE["invented_fact"][ctx.language], 1)


def flipped_strength(text: str, ctx: Context) -> str | None:
    return _replace_all(text, FLIPS[ctx.language], limit=1)


def invented_holding(text: str, ctx: Context) -> str | None:
    return text + SENTENCE["invented_holding"][ctx.language]


def wrong_outcome(text: str, ctx: Context) -> str | None:
    swaps = {
        "de": [
            (r"\bteilweise gutgeheissen\b", "abgewiesen"),
            (r"\bgutgeheissen\b", "ABGEW"),
            (r"\babgewiesen\b", "gutgeheissen"),
        ],
        "fr": [(r"\bpartiellement admis\b", "rejeté"), (r"\badmis\b", "REJ"), (r"\brejeté\b", "admis")],
    }[ctx.language]
    changed = _replace_all(text, swaps)
    if changed:
        return changed.replace("ABGEW", "abgewiesen").replace("REJ", "rejeté")
    if ctx.outcome in OPPOSITE:
        return text + " " + OUTCOME_SENTENCE[ctx.language][OPPOSITE[ctx.outcome]]
    return None


def wrong_reference(text: str, ctx: Context) -> str | None:
    match = re.search(r"\b[Aa]rt\.\s*(\d+)", text)
    if match:
        return text[: match.start(1)] + str(int(match.group(1)) + 31) + text[match.end(1) :]
    return text + SENTENCE["invented_reference"][ctx.language]


def facts_and_outcome_only(text: str, ctx: Context) -> str | None:
    """A summary with no legal point at all: procedure and, when known, the outcome."""
    outcome = OUTCOME_SENTENCE[ctx.language].get(ctx.outcome, "")
    return (SENTENCE["stub"][ctx.language] + " " + outcome).strip()


def first_paragraph_only(text: str, ctx: Context) -> str | None:
    """Drops every paragraph after the first, so legal points of the full text go missing."""
    paragraphs = [p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    return paragraphs[0] if len(paragraphs) >= 2 else None


# Criterion id -> the edits that must make it FAIL.
EDITS: dict[str, list[Edit]] = {
    "T1": [foreign_legal_terms],
    "T2": [opinion_and_address, assistant_voice],
    "T3": [other_language_sentence],
    "T4": [boilerplate_and_repeat],
    "F1": [altered_number, invented_fact],
    "F2": [flipped_strength, invented_holding],
    "F3": [wrong_outcome],
    "F4": [wrong_reference],
    "C1": [facts_and_outcome_only],
    "C2": [facts_and_outcome_only],
    "R1": [first_paragraph_only, facts_and_outcome_only],
}
