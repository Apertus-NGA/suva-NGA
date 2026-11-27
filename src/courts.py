"""Candidate gate for the Suva score.

The court digits, the proceedings letters and the kept subjects are in
``docs/DATA.md`` §5. ``decide`` stores two decisions. The subject decision
keeps a ruling when its digit, its letter and its Neuheiten subject are in
that set, and also when the subject is missing on an allowed court. The text
decision keeps it when the text names Suva, CNA, INSAI or an accident or
military insurance term. Either decision is enough. A trailing asterisk on
the subject (proposed for the official reporter) is ignored.
The measured counts are in ``docs/LAYER1.md``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

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
        "militärversicherung",
        "assurance militaire",
        "assicurazione militare",
    }
)
CONTRACT = frozenset(
    {
        "vertragsrecht",
        "droit des contrats",
        "diritto contrattuale",
        "haftpflichtrecht",
        "assurance responsabilité civile",
    }
)
AREAS = {
    "8": SOCIAL,
    "9": SOCIAL,
    "4": CONTRACT,
}

# Accident or military insurance, and the insurer's names. Short forms need a word boundary.
_TEXT_TERMS = re.compile(
    r"\b(?:"
    r"suva|cna|insai|uvg|laa|lainf|mvg|"
    r"unfallversicherung|militärversicherung|"
    r"assurance-accidents|assurance militaire|"
    r"assicurazione contro gli infortuni|assicurazione militare"
    r")\b"
)
_SUBJECT_KEEPS = frozenset({"kept_subject", "subject_missing"})


@dataclass(frozen=True)
class Gate:
    """The subject decision and the text decision, kept apart."""

    kept: bool
    subject: str
    text: str


def court_of(docket: str) -> str:
    """Prefix before the underscore, for example ``8C``."""
    return docket.split("_", 1)[0]


def _subject(area: str) -> str:
    return area.strip().casefold().rstrip("*").strip()


def _missing(area: object) -> bool:
    return not isinstance(area, str) or not area.strip()


def rubric_from_title(title: object) -> str | None:
    """Matter at the start of ``title``, the column just before ``legal_area``.

    When Hugging Face leaves ``legal_area`` empty it still writes
    ``Invalidenversicherung,`` or ``Assurance-accidents (lien de causalité),``
    in ``title``. The following column, ``regeste``, is empty on those rows.
    """
    if not isinstance(title, str):
        return None
    head = title.strip().split("(", 1)[0]
    head = head.strip().rstrip(",;").strip()
    return head or None


def area_for_gate(area: object, title: object = None) -> object:
    """Use ``area`` when it is filled, otherwise the matter parsed from ``title``."""
    if not _missing(area):
        return area
    return rubric_from_title(title)


def _subject_reason(docket: str, area: object) -> str:
    head = court_of(docket)
    if len(head) != 2:
        return "wrong_court"
    division, letter = head[0], head[1]
    allowed = AREAS.get(division)
    if allowed is None:
        return "wrong_court"
    if letter not in LETTERS[division]:
        return "wrong_letter"
    if _missing(area):
        return "subject_missing"
    if _subject(area) in allowed:
        return "kept_subject"
    return "subject_out"


def _text_reason(text: object) -> str:
    if not isinstance(text, str) or not text.strip():
        return "text_absent"
    if _TEXT_TERMS.search(text.casefold()):
        return "kept_text"
    return "text_clear"


def decide(docket: str, area: object = None, text: object = None) -> Gate:
    """Keep when the subject decision or the text decision says so."""
    subject = _subject_reason(docket, area)
    text_reason = _text_reason(text)
    kept = subject in _SUBJECT_KEEPS or text_reason == "kept_text"
    return Gate(kept, subject, text_reason)


def passes(docket: str, area: object = None, text: object = None) -> bool:
    """True when ``decide`` keeps the ruling."""
    return decide(docket, area, text).kept


def gate_record(docket: str, area: object = None, title: object = None, text: object = None) -> dict[str, object]:
    """One layer-1 row. ``text`` is the text decision, not the ruling."""
    gate = decide(docket, area_for_gate(area, title), text)
    return {"docket": docket, "subject": gate.subject, "text": gate.text, "kept": gate.kept}


def write_layer1(cache, dest, limit: int | None = None):
    """Write one row per ruling in ``cache``. The ruling text is not stored."""
    import pandas as pd

    frame = pd.read_parquet(cache, columns=["docket", "area", "subject", "text"])
    if limit is not None:
        frame = frame.head(limit)
    rows = []
    for row in frame.itertuples(index=False):
        area = row.area if isinstance(row.area, str) and row.area.strip() else None
        title = row.subject if isinstance(row.subject, str) and row.subject.strip() else None
        text = row.text if isinstance(row.text, str) else None
        rows.append(gate_record(row.docket, area, title, text))
    out = pd.DataFrame(rows, columns=["docket", "subject", "text", "kept"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(dest, index=False)
    return out


def _self_check() -> None:
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
    assert passes("8C_1/2025", "Militärversicherung")
    assert passes("4A_1/2025", "Haftpflichtrecht")
    assert passes("4A_1/2025", "Assurance responsabilité civile")
    assert not passes("4A_1/2025", "Schuldbetreibungs- und Konkursrecht")
    assert passes("8C_1/2025", None)
    assert not passes("5A_1/2025", "Droit des contrats")
    blank = decide("8C_1/2025", None)
    assert blank.kept and blank.subject == "subject_missing" and blank.text == "text_absent"
    assert decide("8C_1/2025", "   ").subject == "subject_missing"
    assert decide("7B_1/2025", None).subject == "wrong_court"
    assert decide("4B_1/2025", "Vertragsrecht").subject == "wrong_letter"
    dropped = decide("8C_748/2024", "Arbeitslosenversicherung", "Le recours est rejeté.")
    assert not dropped.kept and dropped.subject == "subject_out" and dropped.text == "text_clear"
    kept_by_text = decide("8C_748/2024", "Arbeitslosenversicherung", "La CNA est intimée.")
    assert kept_by_text.kept and kept_by_text.subject == "subject_out" and kept_by_text.text == "kept_text"
    assert decide("6B_1/2025", "Droit pénal", "Art. 6 UVG.").text == "kept_text"
    row = gate_record("9C_1/2025", None, "Berufliche Vorsorge,", None)
    assert row == {"docket": "9C_1/2025", "subject": "kept_subject", "text": "text_absent", "kept": True}
    print("filter ok")


def main(argv: list[str] | None = None) -> int:
    """Write data/cache/layer1.parquet. Pass ``--limit N`` or ``--all``."""
    import argparse
    import sys
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Write the layer-1 table for the local cache.")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not args.all and args.limit is None:
        print("pass --limit N or --all", file=sys.stderr)
        return 2
    root = Path(__file__).resolve().parents[1]
    cache = root / "data" / "cache" / "rulings.parquet"
    dest = root / "data" / "cache" / "layer1.parquet"
    if args.dry_run:
        print(f"dry-run: would write {dest} from {cache} ({args.limit or 'all'} rows)")
        return 0
    out = write_layer1(cache, dest, None if args.all else args.limit)
    kept = int(out["kept"].sum())
    print(f"wrote {dest} ({len(out)} rows, {kept} kept)")
    return 0


if __name__ == "__main__":
    import sys

    if len(sys.argv) == 1:
        _self_check()
    else:
        raise SystemExit(main())
