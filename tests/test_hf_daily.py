"""Hugging Face daily files adapter: rulings by PUBLICATION date. Offline: the downloader is a declared fake.

Mock declared (AGENTS.md G9): `FakeDownloads` stands in for the HTTP download of one daily file. The files
it serves are small Parquet tables built here, in the two layouts the real archive uses (the columns were
read from the real files of 16 June 2026 and 26 November 2026).
"""

import io

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from src.suva_data import config
from src.suva_data.sources import hf_daily
from src.suva_data.sources.hf_daily import DailyFilesAdapter

TEXT = "Bundesgericht\n\n8C_1/2026\n\nUrteil vom 3. März 2026 ...  \n"  # trailing spaces must survive untouched


def old_row(docket="8C_1/2026", published="2026-06-16", decided="2026-03-03", court="bger", text=TEXT, **extra):
    """Layout used until at least June 2026."""
    key = "bger_" + docket.replace("/", "_")
    row = {
        "id": key,
        "court": court,
        "chamber": "IV. öffentlich-rechtliche Abteilung",
        "language": "de",
        "docket": docket,
        "decision_date": decided,
        "published_date": published,
        "title": "Unfallversicherung (Kausalzusammenhang),",
        "url": "http://relevancy.bger.ch/php/aza/http/index.php?highlight_docid=aza://x",
        "content_text": text,
        "content_sha256": "0" * 64,
        "fetched_at": "2026-06-16T11:00:36+00:00",
    }
    return {**row, **extra}


def new_row(docket="8C_2/2026", published="2026-11-26", decided="2026-11-09", court="bger", text=TEXT, **extra):
    """Layout seen in November 2026."""
    row = {
        "decision_id": "bger_" + docket.replace("/", "_"),
        "court": court,
        "chamber": "IV. öffentlich-rechtliche Abteilung",
        "docket_number": docket,
        "decision_date": decided,
        "publication_date": published,
        "marked_for_publication": True,
        "language": "fr",
        "title": "Assurance-accidents (rente),",
        "legal_area": None,
        "outcome": "dismissed",
        "source_url": "http://relevancy.bger.ch/php/aza/http/index.php?highlight_docid=aza://y",
        "cited_decisions": '["8C_72/2025"]',
        "full_text": text,
        "scraped_at": "2026-11-26T14:01:08+00:00",
    }
    return {**row, **extra}


def parquet_bytes(rows):
    buffer = io.BytesIO()
    pq.write_table(pa.Table.from_pylist(rows), buffer)
    return buffer.getvalue()


class FakeDownloads:
    """day -> bytes of that day's file. A day not in `files` has no file (the archive has such gaps)."""

    def __init__(self, files, failing=()):
        self.files, self.failing, self.calls = files, set(failing), []

    def __call__(self, day):
        self.calls.append(day)
        if day in self.failing:
            raise OSError("connection reset")
        return self.files.get(day)


@pytest.fixture
def adapter(tmp_path):
    def make(files, failing=()):
        downloads = FakeDownloads({d: parquet_bytes(rows) for d, rows in files.items()}, failing)
        return DailyFilesAdapter(snapshot_dir=tmp_path, download=downloads), downloads

    return make


# --- fetch ------------------------------------------------------------------------------------------


def test_fetch_keeps_only_federal_supreme_court_rows_with_a_publication_date(adapter):
    a, _ = adapter(
        {
            "2026-06-16": [
                old_row("8C_1/2026"),
                old_row("8C_9/2020", published=None),  # bulk re-scrape of an old ruling: no publication date
                old_row("8C_8/2020", published=""),
                old_row("VB.2026.1", court="zh_gerichte"),
            ]
        }
    )
    report = a.fetch("2026-06-16", "2026-06-16")
    assert report.status == "complete"
    day = report.days[0]
    counts = {k: day[k] for k in ("day", "status", "rows", "kept", "without_publication_date", "other_courts")}
    assert counts == {
        "day": "2026-06-16",
        "status": "written",
        "rows": 4,
        "kept": 1,
        "without_publication_date": 2,
        "other_courts": 1,
    }
    assert len(report.days) == 1
    assert len(report.days[0]["sha256"]) == 64 and report.days[0]["bytes"] > 0
    assert [r.docket for r in a.parse("2026-06-16", "2026-06-16")] == ["8C_1/2026"]


def test_fetch_is_resumable_and_reports_days_without_a_file(adapter):
    a, downloads = adapter({"2026-06-16": [old_row()], "2026-06-18": [old_row("8C_3/2026", published="2026-06-18")]})
    first = a.fetch("2026-06-16", "2026-06-18")
    assert [(d["day"], d["status"]) for d in first.days] == [
        ("2026-06-16", "written"),
        ("2026-06-17", "no_file"),
        ("2026-06-18", "written"),
    ]
    assert first.status == "complete" and downloads.calls == ["2026-06-16", "2026-06-17", "2026-06-18"]
    second = a.fetch("2026-06-16", "2026-06-18")
    # Stored days are not downloaded again; a day that had no file is asked for again (it may appear later).
    assert downloads.calls[3:] == ["2026-06-17"]
    assert [(d["day"], d["status"]) for d in second.days] == [
        ("2026-06-16", "present"),
        ("2026-06-17", "no_file"),
        ("2026-06-18", "present"),
    ]


def test_fetch_reports_a_failed_day_and_goes_on(adapter):
    a, _ = adapter(
        {"2026-06-16": [old_row()], "2026-06-17": [old_row("8C_3/2026", published="2026-06-17")]},
        failing=["2026-06-16"],
    )
    report = a.fetch("2026-06-16", "2026-06-17")
    assert report.status == "incomplete"
    assert report.days[0] == {"day": "2026-06-16", "status": "failed", "error": "OSError: connection reset"}
    assert report.days[1]["status"] == "written"
    assert [r.docket for r in a.parse("2026-06-16", "2026-06-17")] == ["8C_3/2026"]


def test_fetch_does_not_ask_for_today_or_later(adapter):
    a, downloads = adapter({})
    a.today = "2026-06-17"
    report = a.fetch("2026-06-16", "2026-06-20")
    assert downloads.calls == ["2026-06-16"]  # 17 June is not over yet: its file may still be incomplete
    assert [d["day"] for d in report.days] == ["2026-06-16"]


def test_a_file_in_an_unknown_layout_is_refused_not_guessed(adapter):
    a, _ = adapter({"2026-06-16": [{"court": "bger", "some_new_column": "x"}]})
    report = a.fetch("2026-06-16", "2026-06-16")
    assert report.status == "incomplete" and report.days[0]["status"] == "failed"
    assert "layout" in report.days[0]["error"]


# --- parse ------------------------------------------------------------------------------------------


def test_both_layouts_give_the_same_kind_of_record(adapter):
    a, _ = adapter({"2026-06-16": [old_row()], "2026-11-26": [new_row()]})
    a.fetch("2026-06-16", "2026-11-26")
    old, new = sorted(a.parse("2026-06-01", "2026-11-30"), key=lambda r: r.docket)

    assert (old.source, old.source_key, old.docket, old.decision_date) == (
        config.SWISS_CASELAW,
        "bger_8C_1_2026",
        "8C_1/2026",
        "2026-03-03",
    )
    assert old.fields == {
        "division": "8C",
        "language": "de",
        "publication_date": "2026-06-16",
        "subject": "Unfallversicherung (Kausalzusammenhang)",
        "official_url": "http://relevancy.bger.ch/php/aza/http/index.php?highlight_docid=aza://x",
    }
    assert old.text == TEXT  # exactly as given
    assert old.raw_file == "swiss_caselaw/daily/2026-06-16.parquet"
    assert (
        old.record["daily_file"] == "2026-06-16" and "content_text" not in old.record and "full_text" not in old.record
    )

    assert (new.source_key, new.docket, new.decision_date) == ("bger_8C_2_2026", "8C_2/2026", "2026-11-09")
    assert new.fields == {
        "division": "8C",
        "language": "fr",
        "publication_date": "2026-11-26",
        "starred": True,
        "outcome": "dismissed",
        "subject": "Assurance-accidents (rente)",
        "official_url": "http://relevancy.bger.ch/php/aza/http/index.php?highlight_docid=aza://y",
        "cited_decisions": ["8C_72/2025"],
    }  # fmt: skip


def test_parse_selects_by_publication_date_inclusive_not_by_decision_date(adapter):
    a, _ = adapter(
        {
            "2026-06-16": [
                old_row("8C_1/2026", published="2026-06-16", decided="2026-03-03"),
                old_row("8C_3/2026", published="2026-06-15", decided="2026-06-01"),  # a late row for the day before
            ],
            "2026-06-17": [old_row("8C_4/2026", published="2026-06-17", decided="2026-06-16")],
        }
    )
    a.fetch("2026-06-15", "2026-06-17")
    dockets = lambda start, end: [r.docket for r in a.parse(start, end)]  # noqa: E731
    assert dockets("2026-06-16", "2026-06-16") == ["8C_1/2026"]
    assert dockets("2026-06-15", "2026-06-15") == ["8C_3/2026"]
    assert dockets("2026-06-15", "2026-06-17") == ["8C_1/2026", "8C_3/2026", "8C_4/2026"]  # sorted by key
    assert dockets("2026-03-01", "2026-03-31") == []  # the decision date does not select


def test_a_ruling_in_two_daily_files_is_taken_from_the_earliest_and_the_repeat_is_counted(adapter):
    a, _ = adapter(
        {
            "2026-06-16": [old_row("8C_1/2026", text="first version")],
            "2026-06-17": [old_row("8C_1/2026", text="second version")],
        }
    )
    a.fetch("2026-06-16", "2026-06-17")
    records = list(a.parse("2026-06-16", "2026-06-17"))
    assert [r.text for r in records] == ["first version"]
    assert a.parse_stats["repeats"] == 1 and a.repeated == [
        {"source_key": "bger_8C_1_2026", "daily_file": "2026-06-17"}
    ]


def test_a_case_number_that_cannot_be_read_is_counted_not_dropped_silently(adapter):
    a, _ = adapter({"2026-06-16": [old_row(), old_row("Sammelentscheid", id="bger_x")]})
    a.fetch("2026-06-16", "2026-06-16")
    assert [r.docket for r in a.parse("2026-06-16", "2026-06-16")] == ["8C_1/2026"]
    assert a.parse_stats == {"rows_read": 2, "records": 1, "outside_range": 0, "repeats": 0, "unparsable_docket": 1}
    assert a.unparsable_dockets == [{"source_key": "bger_x", "docket": "Sammelentscheid", "daily_file": "2026-06-16"}]


def test_parse_reads_nothing_from_the_network(adapter):
    a, downloads = adapter({"2026-06-16": [old_row()]})
    a.fetch("2026-06-16", "2026-06-16")
    downloads.calls.clear()
    list(a.parse("2026-06-16", "2026-06-16"))
    assert downloads.calls == []


def test_daily_url_points_at_the_archive_folder_of_the_dataset():
    assert hf_daily.daily_url("2026-06-16") == (
        "https://huggingface.co/datasets/voilaj/swiss-caselaw/resolve/main/artifacts/parquet/deltas/2026-06-16.parquet"
    )
    with pytest.raises(ValueError):
        hf_daily.daily_url("../../etc/passwd")
