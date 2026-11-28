"""Candidate gate for the Suva score.

The court digits, the proceedings letters and the kept subjects are in
``docs/DATA.md`` §5. ``decide`` stores two decisions. The subject decision
keeps a ruling when its digit, its letter and its Neuheiten subject are in
that set. The subject is matched by name (``src/areas.py``), in German, French
or Italian. It is read from the Neuheiten rubric, and when that is empty from
the start of the ruling's subject line. The text decision keeps a ruling when
the text names Suva, CNA, INSAI or an accident or military insurance term.
Either decision is enough. A trailing asterisk on the subject (proposed for
the official reporter) is ignored.

Code drops a ruling on its subject only when the Neuheiten rubric names a
matter outside the set. When the rubric is empty and the subject line names no
kept matter (``subject_unknown``), or there is no subject line
(``subject_missing``), code does not decide: ``layer1_record`` asks Apertus to
read the matter (``src/area_judge.py``). Without an answer the ruling is kept.
The measured counts are in ``docs/LAYER1.md``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

try:  # imported as ``src.courts`` by the tests, as ``courts`` by the scripts launched from src/
    from .areas import area_code, first_segment
except ImportError:
    from areas import area_code, first_segment

LETTERS = {
    "8": frozenset("CDFG"),
    "9": frozenset("CDFG"),
    "4": frozenset("ADFG"),
}

# Matters kept per court, as codes of ``src/areas.py`` (the names in three languages are there).
SOCIAL = frozenset({"UV", "MV", "IV", "KV", "BV"})
CONTRACT = frozenset({"CONTRACT", "LIABILITY"})
AREAS = {
    "8": SOCIAL,
    "9": SOCIAL,
    "4": CONTRACT,
}
# Accident or military insurance, and the insurer's names. Short forms need a word boundary.
_TEXT_TERMS = re.compile(
    r"\b(?:"
    r"suva|cna|insai|uvg|laa|lainf|mvg|"
    r"unfallversicherung(?:sgesetz|en)?|unfallversicherers?|unfallversicherern|militärversicherung|"
    r"assurance-accidents?|assureurs?-accidents?|assurance militaire|"
    r"assicurazione (?:contro gli )?infortuni|assicuratore infortuni|assicurazione militare"
    r")\b"
)
_SUBJECT_UNREAD = frozenset({"subject_missing", "subject_unknown"})  # code could not read the matter
_SUBJECT_KEEPS = frozenset({"kept_subject"}) | _SUBJECT_UNREAD


@dataclass(frozen=True)
class Gate:
    """The subject decision and the text decision, kept apart."""

    kept: bool
    subject: str
    text: str

    @property
    def needs_apertus(self) -> bool:
        """Code could not read the matter and the text decision did not keep the ruling."""
        return self.subject in _SUBJECT_UNREAD and self.text != "kept_text"


def court_of(docket: str) -> str:
    """Prefix before the underscore, for example ``8C``."""
    return docket.split("_", 1)[0]


def _missing(area: object) -> bool:
    return not isinstance(area, str) or not area.strip()


def rubric_from_title(title: object) -> str | None:
    """Matter at the start of ``title``, the column just before ``legal_area``.

    When Hugging Face leaves ``legal_area`` empty it still writes
    ``Invalidenversicherung,``, ``Assurance-accidents (lien de causalité),`` or
    ``Invalidenversicherung, Invalidenrente`` in ``title``. The matter ends at the first
    bracket, comma or semicolon. The following column, ``regeste``, is empty on those rows.
    """
    return first_segment(title)


def area_for_gate(area: object, title: object = None) -> object:
    """Use ``area`` when it is filled, otherwise the matter parsed from ``title``."""
    if not _missing(area):
        return area
    return rubric_from_title(title)


def _subject_reason(docket: str, area: object, title: object = None) -> str:
    head = court_of(docket)
    if len(head) != 2:
        return "wrong_court"
    division, letter = head[0], head[1]
    allowed = AREAS.get(division)
    if allowed is None:
        return "wrong_court"
    if letter not in LETTERS[division]:
        return "wrong_letter"
    if not _missing(area):
        return "kept_subject" if area_code(area) in allowed else "subject_out"
    matter = rubric_from_title(title)
    if matter is None:
        return "subject_missing"
    # A title often names the dispute ("contrat de travail", "Rechtsverweigerung"), not the matter:
    # when it names no kept matter, nothing was read.
    return "kept_subject" if area_code(matter) in allowed else "subject_unknown"


def _text_reason(text: object) -> str:
    if not isinstance(text, str) or not text.strip():
        return "text_absent"
    if _TEXT_TERMS.search(text.casefold()):
        return "kept_text"
    return "text_clear"


def decide(docket: str, area: object = None, text: object = None, title: object = None) -> Gate:
    """Keep when the subject decision or the text decision says so.

    ``area`` is the Neuheiten rubric. ``title`` is the ruling's subject line, read only when ``area`` is empty.
    """
    subject = _subject_reason(docket, area, title)
    text_reason = _text_reason(text)
    kept = subject in _SUBJECT_KEEPS or text_reason == "kept_text"
    return Gate(kept, subject, text_reason)


def passes(docket: str, area: object = None, text: object = None, title: object = None) -> bool:
    """True when ``decide`` keeps the ruling."""
    return decide(docket, area, text, title).kept


def gate_record(docket: str, area: object = None, title: object = None, text: object = None) -> dict[str, object]:
    """One layer-1 row. ``text`` is the text decision, not the ruling."""
    gate = decide(docket, area, text, title)
    return {"docket": docket, "subject": gate.subject, "text": gate.text, "kept": gate.kept}


LAYER1_COLUMNS = ["docket", "subject", "text", "apertus", "matter", "in_scope_probability", "kept"]


def layer1_record(
    docket: str, area: object = None, title: object = None, text: object = None, judge: object = None
) -> dict[str, object]:
    """One layer-1 row with the Apertus reading where code could not read the matter.

    ``judge(ruling_text, kept_matters)`` returns ``apertus``, ``matter``, ``in_scope_probability`` and
    ``kept`` (``src/area_judge.gate_judge``). It is called only when ``decide`` says ``needs_apertus``.
    No judge (``pending``) or a failed call (``failed``) keeps the ruling: a missing answer is not a no.
    """
    gate = decide(docket, area, text, title)
    row: dict[str, object] = {
        "docket": docket,
        "subject": gate.subject,
        "text": gate.text,
        "apertus": "not_asked",
        "matter": None,
        "in_scope_probability": None,
        "kept": gate.kept,
    }
    if not gate.needs_apertus:
        return row
    if judge is None:
        row["apertus"] = "pending"
        return row
    try:
        answer = judge(text, AREAS[court_of(docket)[0]])  # type: ignore[operator]
    except Exception:  # noqa: BLE001  any failure of the reading keeps the ruling
        row["apertus"] = "failed"
        return row
    row.update({key: answer[key] for key in ("apertus", "matter", "in_scope_probability", "kept")})
    return row


def write_layer1(cache, dest, limit: int | None = None, judge: object = None, workers: int = 1):
    """Write one row per ruling in ``cache``. The ruling text is not stored."""
    from concurrent.futures import ThreadPoolExecutor

    import pandas as pd

    frame = pd.read_parquet(cache, columns=["docket", "area", "subject", "text"])
    if limit is not None:
        frame = frame.head(limit)

    def one(row) -> dict[str, object]:
        area = row.area if isinstance(row.area, str) and row.area.strip() else None
        title = row.subject if isinstance(row.subject, str) and row.subject.strip() else None
        text = row.text if isinstance(row.text, str) else None
        return layer1_record(row.docket, area, title, text, judge)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(one, frame.itertuples(index=False)))
    out = pd.DataFrame(rows, columns=LAYER1_COLUMNS)
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
    parser.add_argument(
        "--apertus",
        choices=("off", "replay", "live"),
        default="off",
        help="read the matter with Apertus where code could not (off: those rulings stay kept as pending)",
    )
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
    judge, workers = None, 1
    if args.apertus != "off":
        sys.path.insert(0, str(root))  # the shared client is the package ``src.llm`` (G2)
        from src.area_judge import gate_judge
        from src.llm.client import client_from_env

        client = client_from_env(args.apertus)
        judge, workers = gate_judge(client), client.cfg.concurrency
    out = write_layer1(cache, dest, None if args.all else args.limit, judge, workers)
    kept = int(out["kept"].sum())
    asked = int((~out["apertus"].isin(["not_asked", "pending"])).sum())
    print(f"wrote {dest} ({len(out)} rows, {kept} kept, {asked} read by Apertus)")
    return 0


if __name__ == "__main__":
    import sys

    if len(sys.argv) == 1:
        _self_check()
    else:
        raise SystemExit(main())
