"""Candidate gate for the Suva score.

The court digits, the proceedings letters and the kept subjects are in
``docs/DATA.md`` §5. ``passes`` keeps a ruling when its digit, its letter
and its Neuheiten subject are in that set. A trailing asterisk on the
subject (proposed for the official reporter) is ignored.
"""

from __future__ import annotations

LETTERS = {
    "8": frozenset("CDFG"),
    "9": frozenset("CDFG"),
    "4": frozenset("ADFG"),
}

# News-page subject, lower case, without the reporter asterisk.
SOCIAL = frozenset(
    {
        "unfallversicherung",
        "assurance-accidents",
        "assicurazione contro gli infortuni",
        "invalidenversicherung",
        "assurance-invalidité",
        "assicurazione per l'invalidità",
        "krankenversicherung",
        "assurance-maladie",
        "assicurazione malattie",
        "berufliche vorsorge",
        "prévoyance professionnelle",
        "previdenza professionale",
        "previdenza professionnale",
    }
)
CONTRACT = frozenset(
    {
        "vertragsrecht",
        "droit des contrats",
        "diritto contrattuale",
    }
)
AREAS = {
    "8": SOCIAL,
    "9": SOCIAL,
    "4": CONTRACT,
}


def court_of(docket: str) -> str:
    """Prefix before the underscore, for example ``8C``."""
    return docket.split("_", 1)[0]


def _subject(area: str) -> str:
    return area.strip().casefold().rstrip("*").strip()


def passes(docket: str, area: str | None) -> bool:
    """True when the court, the letter and the subject are in the keep set."""
    head = court_of(docket)
    if len(head) != 2:
        return False
    division, letter = head[0], head[1]
    allowed = AREAS.get(division)
    if allowed is None or letter not in LETTERS[division]:
        return False
    if not area:
        return False
    return _subject(area) in allowed


if __name__ == "__main__":
    assert passes("8C_78/2025", "Unfallversicherung")
    assert passes("9C_65/2025", "Assicurazione per l'invalidità")
    assert passes("4A_106/2025", "Vertragsrecht")
    assert passes("4A_106/2025", "Vertragsrecht*")
    assert passes("8F_1/2025", "Assurance-accidents")
    assert passes("9C_1/2025", "Assurance-maladie")
    assert passes("9D_1/2025", "Prévoyance professionnelle")
    assert not passes("8C_748/2024", "Arbeitslosenversicherung")
    assert not passes("7B_1/2025", "Unfallversicherung")
    assert not passes("9C_1/2025", "Finances publiques & droit fiscal")
    assert not passes("4A_1/2025", "Haftpflichtrecht")
    assert not passes("8C_1/2025", None)
    assert not passes("5A_1/2025", "Droit des contrats")
    print("filter ok")
