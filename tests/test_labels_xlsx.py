"""Labels loader: the three xlsx rules (DATA_LAYER 3.1), the real-file numbers, and the database contract."""

from __future__ import annotations

import datetime as dt
from collections import Counter

import openpyxl
import pytest

from src.suva_data import config
from src.suva_data.loaders.labels_xlsx import (
    HEADER,
    LabelRow,
    LabelsError,
    LabelsResult,
    quarter_of,
    read_labels,
    write_labels,
)
from src.suva_data.models import DOCKET_RE

CANTONAL_TITLE = "Entscheid des Kantonsgerichts Basel-Landschaft vom 5. Februar 2026"
MALFORMED_TITLE = "BGer-Urteil 458/2025 vom 18. November 2025"


@pytest.fixture(scope="module")
def real() -> LabelsResult:
    return read_labels()


def make_xlsx(tmp_path, rows, header=HEADER, sheet_name="Urteile"):
    """rows: (quarter, title, erstellt, hyperlink target or None)."""
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = sheet_name
    sheet.append(list(header))
    for quarter, title, erstellt, url in rows:
        sheet.append([quarter, title, erstellt, "SharePoint öffnen"])
        if url:
            sheet.cell(row=sheet.max_row, column=4).hyperlink = url
    path = tmp_path / "labels.xlsx"
    workbook.save(path)
    return path


# --- pure parsing, real file ------------------------------------------------------------------------


def test_real_file_numbers(real):
    assert len(real.rows) == 59
    assert len(real.dropped) == 1
    assert Counter(row.docket.split("_")[0] for row in real.rows) == {"8C": 53, "9C": 6}
    assert Counter(row.quarter for row in real.rows) == {"2025 Q4": 28, "2026 Q1": 31}
    assert len({row.docket for row in real.rows}) == 59
    assert all(DOCKET_RE.match(row.docket) for row in real.rows)
    # every sheet row is accounted for: header + 59 kept + 1 dropped
    assert sorted([row.xlsx_row for row in real.rows] + [d[0] for d in real.dropped]) == list(range(2, 62))


def test_rule_1_cantonal_row_is_dropped_with_a_reason(real):
    assert real.dropped == [(7, CANTONAL_TITLE, "cantonal_ruling_out_of_scope")]
    assert all(row.xlsx_title != CANTONAL_TITLE for row in real.rows)
    assert all(row.xlsx_row != 7 for row in real.rows)


def test_rule_1_unknown_title_is_dropped_with_a_distinct_reason_never_guessed(tmp_path):
    path = make_xlsx(
        tmp_path,
        [
            ("2026 Q1", "8C_1/2026", dt.datetime(2026, 3, 1), None),
            (
                "2026 Q1",
                "BGer-Urteil 999/2025 vom 3. Februar 2026",
                dt.datetime(2026, 3, 1),
                None,
            ),  # not in the override table
            (
                "2026 Q1",
                "Urteil 8C_2/2026 vom 3. Februar 2026",
                dt.datetime(2026, 3, 1),
                None,
            ),  # a docket inside free text
            ("2026 Q1", CANTONAL_TITLE, dt.datetime(2026, 3, 1), None),
        ],
    )
    result = read_labels(path)
    assert [row.docket for row in result.rows] == ["8C_1/2026"]
    assert result.dropped == [
        (3, "BGer-Urteil 999/2025 vom 3. Februar 2026", "unparseable_title"),
        (4, "Urteil 8C_2/2026 vom 3. Februar 2026", "unparseable_title"),
        (5, CANTONAL_TITLE, "cantonal_ruling_out_of_scope"),
    ]


def test_rule_2_malformed_row_uses_the_explicit_override(real):
    (row,) = [row for row in real.rows if row.xlsx_title == MALFORMED_TITLE]
    assert row.docket == "8C_458/2025"
    assert row.quarter == "2025 Q4"
    assert row.xlsx_row == 49
    # the override is confirmed by the gold summary of the same ruling
    assert (config.JUDGEMENTS_DIR / "Export_8C_458_2025.html").exists()
    # all other rows carry the case number exactly as typed
    assert all(row.docket == row.xlsx_title for row in real.rows if row.xlsx_title != MALFORMED_TITLE)


def test_rule_3_erstellt_is_stored_but_never_decides_the_quarter(real, tmp_path):
    assert all(row.erstellt and dt.datetime.fromisoformat(row.erstellt) for row in real.rows)
    # In the real file the workflow date is often in a later quarter than the ruling: it cannot be used.
    later = [row for row in real.rows if quarter_of(dt.datetime.fromisoformat(row.erstellt)) != row.quarter]
    assert later, "expected real rows whose Erstellt quarter differs from the Jahr / Quartal column"

    path = make_xlsx(tmp_path, [("2025 Q4", "8C_1/2025", dt.datetime(2026, 6, 23, 9, 30), None)])
    (row,) = read_labels(path).rows
    assert row.quarter == "2025 Q4"
    assert row.erstellt == "2026-06-23T09:30:00"


def test_hyperlink_target_is_extracted(real):
    assert all(row.sharepoint_url and row.sharepoint_url.startswith("https://") for row in real.rows)
    first = next(row for row in real.rows if row.docket == "8C_464/2025")
    assert first.xlsx_row == 2
    assert first.erstellt == "2026-03-23T10:30:07"
    # Only the page name is checked: the intranet host and path stay in judgements/ (D-051).
    assert first.sharepoint_url.endswith("/BGer-Urteil-8C_464-2025-vom-25.-Februar-2026.aspx")


def test_missing_hyperlink_is_none(tmp_path):
    path = make_xlsx(tmp_path, [("2025 Q4", "8C_1/2025", dt.datetime(2025, 12, 1), None)])
    assert read_labels(path).rows[0].sharepoint_url is None


def test_duplicate_docket_fails_loudly(tmp_path):
    path = make_xlsx(
        tmp_path,
        [
            ("2025 Q4", "8C_1/2025", dt.datetime(2025, 12, 1), None),
            ("2026 Q1", "9C_5/2025", dt.datetime(2026, 2, 1), None),
            ("2026 Q1", "8C_1/2025", dt.datetime(2026, 2, 1), None),
        ],
    )
    with pytest.raises(LabelsError, match=r"duplicate.*8C_1/2025.*\[2, 4\]"):
        read_labels(path)


def test_invalid_quarter_and_unexpected_header_fail_loudly(tmp_path):
    with pytest.raises(LabelsError, match="invalid quarter"):
        read_labels(make_xlsx(tmp_path, [("Q4 2025", "8C_1/2025", dt.datetime(2025, 12, 1), None)]))
    with pytest.raises(LabelsError, match="unexpected header"):
        read_labels(make_xlsx(tmp_path, [], header=("Quartal", "Titel", "Erstellt", "Link")))


def test_quarter_of():
    assert quarter_of(dt.date(2025, 10, 1)) == "2025 Q4"
    assert quarter_of(dt.date(2025, 12, 31)) == "2025 Q4"
    assert quarter_of(dt.date(2026, 1, 1)) == "2026 Q1"
    assert quarter_of(dt.date(2026, 3, 31)) == "2026 Q1"
    assert quarter_of(dt.date(2026, 4, 1)) == "2026 Q2"


# --- database ---------------------------------------------------------------------------------------


def add_ruling(conn, docket, decision_date, in_window=True) -> int:
    return conn.execute(
        "INSERT INTO rulings (docket, decision_date, division, in_window) VALUES (%s, %s, %s, %s) RETURNING id",
        (docket, decision_date, docket.split("_")[0], in_window),
    ).fetchone()[0]


def label(
    docket, quarter, xlsx_row=2, erstellt="2026-03-23T10:30:07", url="https://intranet.example/x.aspx"
) -> LabelRow:
    return LabelRow(docket, quarter, docket, xlsx_row, erstellt, url)


def count(conn, table) -> int:
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


@pytest.mark.db
def test_write_real_labels_happy_path_and_idempotent(db_conn, real):
    decided = {"2025 Q4": "2025-11-15", "2026 Q1": "2026-02-15"}
    for row in real.rows:
        add_ruling(db_conn, row.docket, decided[row.quarter])

    assert write_labels(db_conn, real) == {"read": 59, "dropped": 1, "inserted": 59, "unchanged": 0}
    rows = db_conn.execute(
        "SELECT r.docket, l.label_set, l.value, l.quarter, l.metadata FROM labels l JOIN rulings r ON r.id = "
        "l.ruling_id"
    ).fetchall()
    assert len(rows) == 59
    assert {r[1] for r in rows} == {config.LABEL_SET_XLSX} and {r[2] for r in rows} == {"relevant"}
    by_docket = {r[0]: r for r in rows}
    assert by_docket["8C_458/2025"][3] == "2025 Q4"
    metadata = dict(by_docket["8C_458/2025"][4])
    # Only the page name is checked: the intranet host and path stay in judgements/ (D-051).
    assert metadata.pop("sharepoint_url").endswith("/BGer-Urteil-458-2025-vom-18.-November-2025.aspx")
    assert metadata == {
        "erstellt": "2025-12-15T10:43:02",
        "xlsx_title": MALFORMED_TITLE,
        "xlsx_row": 49,
    }

    before = db_conn.execute("SELECT id, ruling_id, quarter, metadata, created_at FROM labels ORDER BY id").fetchall()
    assert write_labels(db_conn, real) == {"read": 59, "dropped": 1, "inserted": 0, "unchanged": 59}
    assert (
        db_conn.execute("SELECT id, ruling_id, quarter, metadata, created_at FROM labels ORDER BY id").fetchall()
        == before
    )


@pytest.mark.db
def test_erstellt_in_another_quarter_does_not_matter(db_conn):
    add_ruling(db_conn, "8C_1/2025", "2025-12-11")
    result = LabelsResult(rows=[label("8C_1/2025", "2025 Q4", erstellt="2026-06-23T09:30:00")])
    assert write_labels(db_conn, result)["inserted"] == 1
    quarter, metadata = db_conn.execute("SELECT quarter, metadata FROM labels").fetchone()
    assert quarter == "2025 Q4" and metadata["erstellt"] == "2026-06-23T09:30:00"


@pytest.mark.db
def test_missing_ruling_fails_and_writes_nothing(db_conn):
    add_ruling(db_conn, "8C_1/2025", "2025-12-11")
    result = LabelsResult(
        rows=[label("8C_1/2025", "2025 Q4", 2), label("8C_2/2025", "2025 Q4", 3), label("9C_3/2025", "2026 Q1", 4)]
    )
    with pytest.raises(LabelsError) as error:
        write_labels(db_conn, result)
    assert "no ruling for 2 docket(s)" in str(error.value)
    assert "8C_2/2025" in str(error.value) and "9C_3/2025" in str(error.value)
    assert count(db_conn, "labels") == 0


@pytest.mark.db
def test_ambiguous_docket_fails_and_writes_nothing(db_conn):
    add_ruling(db_conn, "8C_1/2025", "2025-12-11")
    add_ruling(db_conn, "7B_1356/2025", "2026-01-26")
    add_ruling(db_conn, "7B_1356/2025", "2026-03-18")
    result = LabelsResult(rows=[label("8C_1/2025", "2025 Q4", 2), label("7B_1356/2025", "2026 Q1", 3)])
    with pytest.raises(LabelsError) as error:
        write_labels(db_conn, result)
    assert "more than one ruling" in str(error.value)
    assert "7B_1356/2025" in str(error.value) and "2026-01-26" in str(error.value) and "2026-03-18" in str(error.value)
    assert count(db_conn, "labels") == 0


@pytest.mark.db
def test_quarter_mismatch_fails_and_writes_nothing(db_conn):
    add_ruling(db_conn, "8C_1/2025", "2025-12-11")
    add_ruling(db_conn, "8C_2/2025", "2026-01-05")  # decided in Q1, listed under Q4
    result = LabelsResult(rows=[label("8C_1/2025", "2025 Q4", 2), label("8C_2/2025", "2025 Q4", 3)])
    with pytest.raises(LabelsError) as error:
        write_labels(db_conn, result)
    assert "quarter differs" in str(error.value)
    assert "8C_2/2025" in str(error.value) and "8C_1/2025" not in str(error.value)
    assert count(db_conn, "labels") == 0


@pytest.mark.db
def test_stored_label_that_differs_from_the_file_is_not_overwritten(db_conn):
    add_ruling(db_conn, "8C_1/2025", "2025-12-11")
    write_labels(db_conn, LabelsResult(rows=[label("8C_1/2025", "2025 Q4", xlsx_row=2)]))
    with pytest.raises(LabelsError, match="differ from the file.*8C_1/2025"):
        write_labels(db_conn, LabelsResult(rows=[label("8C_1/2025", "2025 Q4", xlsx_row=9)]))
    assert db_conn.execute("SELECT metadata->>'xlsx_row' FROM labels").fetchall() == [("2",)]


@pytest.mark.db
def test_v_relevance(db_conn):
    from src.suva_data.loaders.gold_summaries import GoldSummary, write_gold_summaries

    add_ruling(db_conn, "8C_1/2025", "2025-12-11")  # labelled
    add_ruling(db_conn, "8C_2/2025", "2025-08-28", in_window=False)  # only a gold summary (Q3/2025)
    add_ruling(db_conn, "8C_3/2025", "2025-11-15")  # in the labelled quarters, no label
    add_ruling(db_conn, "8C_4/2026", "2026-05-01")  # Q2/2026: prediction target
    add_ruling(db_conn, "8C_5/2025", "2025-09-30", in_window=False)  # Q3/2025 without summary
    write_labels(db_conn, LabelsResult(rows=[label("8C_1/2025", "2025 Q4")]))
    write_gold_summaries(
        db_conn,
        [
            GoldSummary(
                "8C_2/2025",
                "Export_8C_2_2025.html",
                "BGer-Urteil 8C_2/2025 vom 28. August 2025",
                "de",
                "2025-08-28",
                "DE",
                "FR",
                "A",
                None,
            )
        ],
    )
    view = {
        docket: (relevance, basis, quarter)
        for docket, relevance, basis, quarter in db_conn.execute(
            "SELECT docket, relevance, basis, decision_quarter FROM v_relevance"
        )
    }
    assert view == {
        "8C_1/2025": ("relevant", "suva_xlsx", "2025 Q4"),
        "8C_2/2025": ("relevant", "gold_summary_only", "2025 Q3"),
        "8C_3/2025": ("not_relevant", "complete_list_negative", "2025 Q4"),
        "8C_4/2026": ("unknown", "no_label", "2026 Q2"),
        "8C_5/2025": ("unknown", "no_label", "2025 Q3"),
    }
