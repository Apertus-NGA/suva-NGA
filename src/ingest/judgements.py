"""Read Suva's material in judgements/ without its personal fields (D-051, D-040).

The workbook is read cell by cell from its XML, columns A (quarter label) and B (docket or title) only: never
column C (creation date), never column D (intranet link), never the file properties. Each export is read for
its bger.ch link only (`aza://DD-MM-YYYY-<docket>`), which carries the docket and the decision date: never
the author section. judgements/ itself is never modified.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[2]
JUDGEMENTS = ROOT / "judgements"
WORKBOOK = JUDGEMENTS / "BG_Urteile_2025_Q4_2026_Q1.xlsx"
DOCKET = re.compile(r"^[0-9]{1,2}[A-Z]_[0-9]+/[0-9]{4}$")
_DOCKET_IN_TEXT = re.compile(r"\b[0-9]{1,2}[A-Z]_[0-9]+/[0-9]{4}\b")
_NUMBER_IN_TEXT = re.compile(r"\b([0-9]+)/([0-9]{4})\b")
_FEDERAL_COURT = re.compile(r"\b(?:BGer|Bundesgericht|TF|Tribunal f[ée]d[ée]ral)\b")
_AZA = re.compile(r"aza://(\d{2})-(\d{2})-(\d{4})-([0-9]{1,2}[A-Z]_[0-9]+)-([0-9]{4})")
_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_ALLOWED_COLUMNS = ("A", "B")


@dataclass(frozen=True)
class ListRow:
    row: int
    quarter_label: str
    entry: str  # a docket, a docket without its court prefix, or a cantonal title


@dataclass(frozen=True)
class ExportRef:
    file: str  # path under judgements/
    docket: str
    decision_date: date


def _shared_strings(z: zipfile.ZipFile) -> list[str]:
    root = ElementTree.fromstring(z.read("xl/sharedStrings.xml"))
    return ["".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t")) for si in root.findall("m:si", _NS)]


def list_rows(workbook: Path = WORKBOOK) -> list[ListRow]:
    """The rows of Suva's relevance list: (quarter label, entry). Header row skipped. Columns A and B only."""
    with zipfile.ZipFile(workbook) as z:
        strings = _shared_strings(z)
        sheet = ElementTree.fromstring(z.read("xl/worksheets/sheet1.xml"))
    rows: list[ListRow] = []
    for row in sheet.iter(f"{{{_NS['m']}}}row"):
        number = int(row.get("r"))
        if number == 1:
            continue
        cells: dict[str, str] = {}
        for cell in row.findall("m:c", _NS):
            column = re.sub(r"\d+", "", cell.get("r", ""))
            if column not in _ALLOWED_COLUMNS:
                continue  # D-051: never read the creation date or the intranet link
            value = cell.find("m:v", _NS)
            if value is None or value.text is None:
                continue
            cells[column] = strings[int(value.text)] if cell.get("t") == "s" else value.text
        if cells.get("A") and cells.get("B"):
            rows.append(ListRow(number, cells["A"].strip(), cells["B"].strip()))
    return rows


def export_refs(directory: Path = JUDGEMENTS) -> list[ExportRef]:
    """Docket and decision date of each summary export, from its bger.ch link only."""
    refs: list[ExportRef] = []
    for path in sorted(directory.glob("Export_*.html")):
        found = _AZA.search(path.read_text(encoding="utf-8", errors="replace"))
        if not found:
            raise ValueError(f"{path.name}: no aza:// link")
        day, month, year, head, filing_year = found.groups()
        refs.append(
            ExportRef(f"judgements/{path.name}", f"{head}/{filing_year}", date(int(year), int(month), int(day)))
        )
    return refs


def resolve_entry(entry: str, export_dockets: set[str]) -> tuple[str | None, str | None]:
    """(docket, None) for a Federal Court entry, (None, title) for the cantonal row.

    An entry is a docket (`8C_464/2025`) or a title (`BGer-Urteil 458/2025 vom 18. November 2025`). One title
    lacks its court prefix: it is resolved through the export with the same number and filing year
    (docs/SUVA_DATA.md §2), and only if exactly one export matches. A title that names no Federal Court
    ruling (the cantonal decision, Q-28) stays a title.
    """
    found = _DOCKET_IN_TEXT.search(entry)
    if found:
        return found.group(0), None
    if _FEDERAL_COURT.search(entry):
        bare = _NUMBER_IN_TEXT.search(entry)
        if bare:
            number, year = bare.groups()
            candidates = sorted(d for d in export_dockets if d.endswith(f"_{number}/{year}"))
            if len(candidates) == 1:
                return candidates[0], None
            raise ValueError(f"list entry {entry!r}: {len(candidates)} exports match, cannot resolve the court")
    return None, entry
