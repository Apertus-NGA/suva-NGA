"""Profiles: what a digest of one kind of ruling must state, detected and checked by code.

A profile is chosen by code from the articles the court cites in its considerations (never by Apertus, never by
the docket). Its checklist comes from the law of that question, not from Suva's texts, so it cannot fit the few
rulings we measure on (docs/EXTRACT.md §4). A ruling that matches no profile follows the general path.

Each checklist item has a pattern in DE, FR and IT. An item counts only when the ruling's considerations discuss
it; when the choice then has no sentence that does, code adds the best candidate that states it (one of the
best-ranked considerations, citing law if it can), at most MAX_ADDED per ruling. The profile's description is also
given to Apertus when it chooses (choose.py), as a hint.

The outcome rule holds for every ruling: when the court sends the case back, the digest says what goes back and
why, from the court's own sentence.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from src.summarize.extract import candidates as cand
from src.summarize.refine import evidence

VERSION = "profiles@3"
MAX_ADDED = 3  # two for the profile, and the court's answer


@dataclass(frozen=True)
class Item:
    id: str
    says: str  # what the digest states, for the prompt
    pattern: re.Pattern


@dataclass(frozen=True)
class Profile:
    id: str
    about: str  # for the prompt
    articles: re.Pattern  # on the normalised article citations of the considerations
    items: tuple[Item, ...]


def _p(text: str) -> re.Pattern:
    return re.compile(text, re.IGNORECASE)


PROFILES = (
    Profile(
        "income_comparison",
        "the degree of invalidity by comparing incomes (Art. 16 ATSG / LPGA)",
        _p(r"Art\. 16 (?:ATSG|LPGA)\b"),
        (
            Item(
                "wage_table",
                "which statistical wage table and line the income rests on",
                _p(r"\bLSE\b|\bESS\b|\bTA1\b|\bRSS\b|Tabellenl(?:o|ö)hn|salaires? statistiques?|tabella"),
            ),
            Item(
                "skill_level",
                "the skill level applied and why",
                _p(r"Kompetenzniveau|niveau de comp(?:é|e)tences?|livello di competenz"),
            ),
            Item(
                "deduction",
                "whether a deduction from the table wage is made and why",
                _p(r"Abzug vom Tabellenlohn|leidensbedingte[nr]? Abzug|\bAbzug\b|abattement|deduzione"),
            ),
            Item(
                "incomes",
                "the income without and with the impairment compared",
                _p(
                    r"Valideneinkommen|Invalideneinkommen|revenu (?:sans invalidit|d'invalide)"
                    r"|reddito d[ai] (?:valido|invalido)"
                ),
            ),
        ),
    ),  # fmt: skip
    Profile(
        "causation",
        "whether the accident caused the health problem (Art. 6 UVG / LAA)",
        _p(r"Art\. 6 (?:Abs\. 1 )?(?:UVG|LAA)\b"),
        (
            Item(
                "natural",
                "the natural causal link and its standard of proof",
                _p(r"nat(?:ü|u)rliche[nr]? Kausal|causalit(?:é|e) naturelle|nesso (?:di )?causal\w* natural"),
            ),
            Item(
                "adequate",
                "the adequate causal link and the test applied",
                _p(r"ad(?:ä|a)quate[nr]? Kausal|causalit(?:é|e) ad(?:é|e)quate|nesso (?:di )?causal\w* adeguat"),
            ),
            Item(
                "status_quo",
                "when the status quo ante or sine is reached",
                _p(r"status quo (?:sine|ante)|statu quo (?:sine|ante)"),
            ),
        ),
    ),  # fmt: skip
)
REMAND = Item(
    "remand",
    "what the court sends back, to whom, and what must be clarified",
    # the case sent back, not "renvoyer à" (to refer to: run x16 took "il suffit d'y renvoyer" for the remand)
    _p(r"zur(?:ü|u)ckgewiesen|R(?:ü|u)ckweisung|(?:cause|affaire|dossier)\s+(?:(?:est|soit|doit être|sera)\s+)?renvoy"
       r"|renvo(?:ie|yer|yant)\s+la\s+cause|renvoi\s+de\s+la\s+cause|(?:causa|incarto)\s+(?:è|viene|va)\s+rinviat"
       r"|rinvi\w*\s+la\s+causa"),
)  # fmt: skip


# For every ruling: the court's own answer on the point. Run x2: C2 (main question resolved) failed on 7 of 24,
# the choice had the rules but not the sentence that applies them and concludes.
ANSWER = Item(
    "answer",
    "the court's own conclusion on the point in dispute",
    _p(r"^(?:Zusammenfassend|Insgesamt|Nach dem Gesagten|Im Ergebnis|Demnach|Somit|Folglich|Es ergibt sich"
       r"|Il s'ensuit|En définitive|En conclusion|En résumé|Partant|Vu ce qui précède|Au vu de ce qui précède|Dès lors"
       r"|Ne consegue|In conclusione|Pertanto|Ne discende)\b"),
)  # fmt: skip


def _considerations(found: cand.Candidates) -> list[cand.Candidate]:
    return [c for c in found.kept if c.label.startswith("E.")]


def detect(text: str) -> Profile | None:
    """The profile the considerations are about, or None. A profile counts its articles cited (twice or more) or
    its own items discussed (two items, each named twice or more): courts deciding causation cite the case law,
    rarely Art. 6 UVG itself (8C_311/2025, 8C_720/2024), and an Italian ruling may never cite Art. 16 ATSG."""
    parts = evidence.passages(text)
    body = " ".join(v for k, v in parts.items() if k.startswith("E."))
    cited = Counter(
        " ".join(a.replace("art.", "Art.").replace(" al. ", " Abs. ").replace(" cpv. ", " Abs. ").split())
        for a in evidence.ARTICLE.findall(body)
    )
    best, best_score = None, 0
    for profile in PROFILES:
        by_article = sum(k for a, k in cited.items() if profile.articles.search(a)) >= 2
        by_items = sum(len(item.pattern.findall(body)) >= 2 for item in profile.items) >= 2
        score = 2 * by_article + by_items + sum(len(item.pattern.findall(body)) for item in profile.items) / 1000
        if (by_article or by_items) and score > best_score:
            best, best_score = profile, score
    return best


def remanded(text: str) -> bool:
    """True when point 1 of the operative part sends the case back (a referral of the costs alone, in a later
    point, is not the merits: 8C_399/2025)."""
    operative = " ".join(evidence.passages(text).get("operative", "").split())
    first = re.search(r"\b1\.\s+(.*?)(?=\s2\.\s|$)", operative)
    return bool(REMAND.pattern.search(first.group(1) if first else operative))


def hint(profile: Profile | None, remand: bool) -> str:
    """The profile's checklist as the chooser reads it."""
    lines = []
    if profile:
        lines.append(f"This ruling decides {profile.about}. A digest of such a ruling states, where the court "
                     "discusses it: " + "; ".join(i.says for i in profile.items) + ".")  # fmt: skip
    if remand:
        lines.append(f"The court sends the case back: the digest states {REMAND.says}.")
    return ("\n" + "\n".join(lines)) if lines else ""


def _says(item: Item, text: str) -> bool:
    """The item's pattern on the sentence without its references ("et les renvois" is a citation, not a remand)."""
    return bool(item.pattern.search(cand._CITATION.sub(" ", text)))


def _best(found: cand.Candidates, item: Item, scores: dict[str, float], taken: set[str]) -> cand.Candidate | None:
    pool = [c for c in _considerations(found) if c.id not in taken and _says(item, c.text)
            and not (item is ANSWER and c.voice == "lower_court")]  # the court's answer is its own  # fmt: skip
    if not pool:
        return None
    if item is REMAND:  # the court's own last word on what goes back, in its own voice
        own = [c for c in pool if c.voice == "court"]
        return (own or pool)[-1]
    if item is ANSWER:  # the court's last conclusion in its best-read consideration
        best = max(scores.get(c.label, 0.0) for c in pool)
        return [c for c in pool if scores.get(c.label, 0.0) == best][-1]
    return max(pool, key=lambda c: (scores.get(c.label, 0.0), bool(cand.tags(c.text)) and "names a party" not in
                                    cand.tags(c.text), -len(c.text)))  # fmt: skip


def check(found: cand.Candidates, chosen: list, text: str, scores: dict[str, float]) -> tuple[list, list[str]]:
    """The choice with what the profile and the outcome rule demand added; notes on what code did."""
    profile = detect(text)
    items = list(profile.items) if profile else []
    if remanded(text):
        items.append(REMAND)
    items.append(ANSWER)
    taken = {c.id for c, _ in chosen}
    out, notes, added = list(chosen), [], 0
    for item in items:
        if any(_says(item, c.text) for c, _ in out):
            continue
        if not any(_says(item, c.text) for c in _considerations(found)):
            continue  # the court does not discuss it: nothing to state
        if added >= MAX_ADDED:
            notes.append(f"{item.id}: not stated, and the limit of {MAX_ADDED} additions is reached")
            continue
        found_one = _best(found, item, scores, taken)
        if found_one is None:
            continue
        out.append((found_one, "holding" if item in (REMAND, ANSWER) else "condition"))
        taken.add(found_one.id)
        added += 1
        prefix = f"{profile.id}:" if profile and item in profile.items else ""
        notes.append(f"{found_one.id} added for {prefix}{item.id}")
    return out, notes
