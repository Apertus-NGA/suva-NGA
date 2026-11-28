"""Loader for Suva's relevance labels (docs/DATA_LAYER.md, section 3.1).

`read_labels` is pure (xlsx -> rows); `write_labels` attaches them to `rulings` in one transaction.

Three rules, each a regression test in tests/test_labels_xlsx.py:

1. The cantonal row is a mistake (organiser, A2): it is dropped, with a reason, and never becomes a label.
2. The row without a division prefix is mapped through `TITLE_OVERRIDES`, an explicit table. No fuzzy matching.
3. `Erstellt` is Suva's internal workflow date. It is stored as metadata and never used for quarter logic:
   the quarter comes only from the `Jahr / Quartal` column, and is checked against the ruling's decision date.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl

from .. import config
from ..models import DOCKET_RE, normalise_docket

SHEET_NAME = "Urteile"
HEADER = ("Jahr / Quartal", "Urteilsnummer / Titel", "Erstellt", "SharePoint-Link")
QUARTER_RE = re.compile(r"^\d{4} Q[1-4]$")

# Exact title -> case number, for rows where the case number was typed wrongly. Add an entry only with evidence.
TITLE_OVERRIDES: dict[str, str] = {
    # Division prefix missing. Confirmed by judgements/Export_8C_458_2025.html (same title, link to 8C_458/2025).
    "BGer-Urteil 458/2025 vom 18. November 2025": "8C_458/2025",
}

# Exact title -> drop reason, for rows known not to be Federal Supreme Court rulings.
KNOWN_OUT_OF_SCOPE: dict[str, str] = {
    # Organiser, 2026-11-27 (A2): a mistake in the list; only Federal Supreme Court rulings count.
    "Entscheid des Kantonsgerichts Basel-Landschaft vom 5. Februar 2026": "cantonal_ruling_out_of_scope",
}
UNPARSEABLE = "unparseable_title"  # neither a case number, nor an override, nor a known entry: a new surprise


class LabelsError(ValueError):
    """The labels cannot be read or attached safely. Nothing was written."""


@dataclass(frozen=True)
class LabelRow:
    docket: str
    quarter: str  # from the `Jahr / Quartal` column, e.g. '2025 Q4'
    xlsx_title: str  # the `Urteilsnummer / Titel` cell as typed
    xlsx_row: int  # 1-based sheet row (the header is row 1)
    erstellt: str | None  # ISO datetime; Suva's workflow date, metadata only
    sharepoint_url: str | None  # hyperlink target (intranet, not reachable)


@dataclass(frozen=True)
class LabelsResult:
    rows: list[LabelRow] = field(default_factory=list)
    dropped: list[tuple[int, str, str]] = field(default_factory=list)  # (xlsx_row, title, reason)


def quarter_of(date: dt.date) -> str:
    """Quarter of a decision date in the xlsx notation: 2025-12-11 -> '2025 Q4'."""
    return f"{date.year} Q{(date.month - 1) // 3 + 1}"


def _iso(value) -> str | None:
    if value is None:
        return None
    return value.isoformat() if isinstance(value, (dt.datetime, dt.date)) else str(value)


def read_labels(path: Path | str = config.LABELS_XLSX) -> LabelsResult:
    # Not read-only mode: hyperlink targets are only available on a fully loaded sheet.
    workbook = openpyxl.load_workbook(path)
    if SHEET_NAME not in workbook.sheetnames:
        raise LabelsError(f"{path}: sheet {SHEET_NAME!r} not found (sheets: {workbook.sheetnames})")
    sheet = workbook[SHEET_NAME]

    header = tuple(cell.value for cell in sheet[1][: len(HEADER)])
    if header != HEADER:
        raise LabelsError(f"{path}: unexpected header {header!r}, expected {HEADER!r}")

    result = LabelsResult()
    for cells in sheet.iter_rows(min_row=2, max_col=len(HEADER)):
        quarter_cell, title_cell, erstellt_cell, link_cell = cells
        if all(cell.value is None for cell in cells):
            continue
        row_number = title_cell.row
        title = str(title_cell.value or "").strip()
        quarter = str(quarter_cell.value or "").strip()
        if not QUARTER_RE.match(quarter):
            raise LabelsError(f"{path}: row {row_number} ({title!r}): invalid quarter {quarter_cell.value!r}")

        if title in TITLE_OVERRIDES:
            docket = TITLE_OVERRIDES[title]
        elif DOCKET_RE.match(title):
            docket = normalise_docket(title)
        else:
            result.dropped.append((row_number, title, KNOWN_OUT_OF_SCOPE.get(title, UNPARSEABLE)))
            continue

        result.rows.append(
            LabelRow(
                docket=docket,
                quarter=quarter,
                xlsx_title=title,
                xlsx_row=row_number,
                erstellt=_iso(erstellt_cell.value),
                sharepoint_url=link_cell.hyperlink.target if link_cell.hyperlink else None,
            )
        )

    by_docket: dict[str, list[int]] = {}
    for row in result.rows:
        by_docket.setdefault(row.docket, []).append(row.xlsx_row)
    duplicates = {docket: rows for docket, rows in by_docket.items() if len(rows) > 1}
    if duplicates:
        raise LabelsError(f"{path}: duplicate case numbers (docket: sheet rows): {duplicates}")
    return result


def resolve_dockets(conn, dockets) -> tuple[dict[str, tuple[int, dt.date]], list[str], dict[str, list[str]]]:
    """Map each docket to its single `rulings` row.

    Returns (resolved {docket: (ruling_id, decision_date)}, missing [docket], ambiguous {docket: [decision dates]}).
    Labels and gold summaries only carry a case number, and a case number can have two rulings
    (7B_1356/2025), so the caller must fail on anything in `missing` or `ambiguous`.
    """
    dockets = sorted(set(dockets))
    found: dict[str, list[tuple[int, dt.date]]] = {}
    rows = conn.execute(
        "SELECT docket, id, decision_date FROM rulings WHERE docket = ANY(%s) ORDER BY docket, decision_date",
        (dockets,),
    ).fetchall()
    for docket, ruling_id, decision_date in rows:
        found.setdefault(docket, []).append((ruling_id, decision_date))
    resolved = {docket: hits[0] for docket, hits in found.items() if len(hits) == 1}
    missing = [docket for docket in dockets if docket not in found]
    ambiguous = {docket: [d.isoformat() for _, d in hits] for docket, hits in found.items() if len(hits) > 1}
    return resolved, missing, ambiguous


def _metadata(row: LabelRow) -> dict:
    return {
        "erstellt": row.erstellt,
        "sharepoint_url": row.sharepoint_url,
        "xlsx_title": row.xlsx_title,
        "xlsx_row": row.xlsx_row,
    }


def write_labels(conn, result: LabelsResult, label_set: str = config.LABEL_SET_XLSX) -> dict[str, int]:
    """Insert one 'relevant' label per row. All or nothing; running it again changes nothing.

    Raises LabelsError, listing every offending docket, if a docket matches no ruling or several,
    if a label's quarter is not the quarter of the ruling's decision date (A1), or if a label already
    stored for this label set differs from the file.
    """
    with conn.transaction():
        resolved, missing, ambiguous = resolve_dockets(conn, [row.docket for row in result.rows])
        quarter_mismatch = [
            f"{row.docket}: xlsx {row.quarter!r}, decided {resolved[row.docket][1].isoformat()}"
            f" = {quarter_of(resolved[row.docket][1])!r}"
            for row in result.rows
            if row.docket in resolved and quarter_of(resolved[row.docket][1]) != row.quarter
        ]

        existing = {
            ruling_id: (value, quarter, metadata)
            for ruling_id, value, quarter, metadata in conn.execute(
                "SELECT ruling_id, value, quarter, metadata FROM labels WHERE label_set = %s", (label_set,)
            )
        }
        to_insert, changed, unchanged = [], [], 0
        for row in result.rows:
            if row.docket not in resolved:
                continue
            ruling_id = resolved[row.docket][0]
            wanted = ("relevant", row.quarter, _metadata(row))
            if ruling_id not in existing:
                to_insert.append((ruling_id, label_set, *wanted[:2], json.dumps(wanted[2])))
            elif existing[ruling_id] == wanted:
                unchanged += 1
            else:
                changed.append(row.docket)

        problems = []
        if missing:
            problems.append(f"no ruling for {len(missing)} docket(s): {missing}")
        if ambiguous:
            problems.append(
                f"more than one ruling for {len(ambiguous)} docket(s) (docket: decision dates): {ambiguous}"
            )
        if quarter_mismatch:
            problems.append(
                f"quarter differs from the decision-date quarter for {len(quarter_mismatch)} label(s): {quarter_mismatch}"
            )
        if changed:
            problems.append(
                f"{len(changed)} label(s) already stored in {label_set!r} differ from the file"
                f" (labels are never overwritten): {changed}"
            )
        if problems:
            raise LabelsError("labels not written. " + "; ".join(problems))

        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO labels (ruling_id, label_set, value, quarter, metadata) VALUES (%s, %s, %s, %s, %s::jsonb)",
                to_insert,
            )
    return {
        "read": len(result.rows),
        "dropped": len(result.dropped),
        "inserted": len(to_insert),
        "unchanged": unchanged,
    }
