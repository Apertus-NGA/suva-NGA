"""The HF loader's classification and its exclusion ledger, without a database (F-04, G5).

A synthetic parquet holds one row per way a row can leave the load: out of every window (read by the window filter
or not), a malformed docket inside a window, no decision date, a twin whose base is excluded (read or not), a row
without an id, an id repeated inside the read rows and across the filter. `exclusion_ledger` must account for every
row, agree with `read_base` on what is loaded, and keep read_base's counters exactly (the golden check compares them
on the real file). Rulings: synthetic dockets, no text of a real ruling, no personal data (D-038).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.db.pg import ROOT

COLUMNS = ["decision_id", "docket_number", "decision_date", "publication_date", "scraped_at", "language", "title"]
ROWS = [  # index: decision_id, docket_number, decision_date, publication_date, scraped_at, language, title
    ("bger_8C_1_2026", "8C_1/2026", "2026-04-02", None, "2026-04-20T08:00:00", "de", "Unfallversicherung"),  # 0
    ("bger_8C_1_2026-D20260402", "8C_1/2026", "2026-04-02", None, "2026-04-20T08:00:00", "de", "Unfall"),  # 1 twin
    ("bger_8C_2_2019", "8C_2/2019", "2019-03-01", "2019-03-05", "2019-03-05T08:00:00", "de", "Alt"),  # 2 not read
    ("bger_8C_3_2019", "8C_3/2019", "2019-03-01", None, "2026-06-20T08:00:00", "de", "Alt"),  # 3 read, no window
    ("bger_X_1", "Ohne Nummer", "2026-04-03", None, "2026-04-20T08:00:00", "de", "Ohne"),  # 4 malformed
    ("bger_X_1-D20260403", "Ohne Nummer", "2026-04-03", None, "2026-04-20T08:00:00", "de", "Ohne"),  # 5 its twin
    ("bger_8C_5_2026", "8C_5/2026", None, None, "2026-04-10T08:00:00", "fr", "Sans date"),  # 6 no decision date
    ("bger_8C_4_2019", "8C_4/2019", "2019-05-01", None, "2019-05-10T08:00:00", "it", "Vecchio"),  # 7 not read
    ("bger_8C_4_2019-D20190501", "8C_4/2019", "2019-05-01", None, "2019-05-10T08:00:00", "it", "Vecchio"),  # 8 twin
    (None, "8C_7/2026", "2026-04-05", None, "2026-04-20T08:00:00", "de", "Ohne Kennung"),  # 9 no id
    ("bger_8C_1_2026", "8C_1/2026", "2026-04-02", None, "2026-04-21T08:00:00", "de", "Doppelt"),  # 10 repeats 0
    ("bger_8C_6_2026", "8C_6/2026", "2026-04-06", "2026-05-26", "2026-05-26T08:00:00", "fr", "Rechute"),  # 11
    ("bger_8C_6_2026", "8C_6/2018", "2018-01-01", None, "2018-01-02T08:00:00", "fr", "Ancien"),  # 12 repeats 11
    ("bger_9C_8_2026", "9C_8/2026", "2026-05-04", None, "2026-05-10T08:00:00", "it", "Infortuni"),  # 13
    # a base the filter reads by its publication date, and its same-date twin the filter does not read (two cases)
    ("bger_8C_9_2015", "8C_9/2015", "2015-03-01", "2026-05-26", "2026-05-26T08:00:00", "de", "Revision"),  # 14
    ("bger_8C_9_2015-D20150301", "8C_9/2015", "2015-03-01", None, "2015-03-10T08:00:00", "de", "Revision"),  # 15
    ("bger_8C_10_2015", "8C_10/2015", "2015-03-02", None, "2026-06-20T08:00:00", "de", "Alt"),  # 16 read, no window
    ("bger_8C_10_2015-D20150302", "8C_10/2015", "2015-03-02", None, "2015-03-10T08:00:00", "de", "Alt"),  # 17
    # the reverse, as in the pinned file: the filter reads the twin (collected again), not its same-date base
    ("bger_8C_11_2015", "8C_11/2015", "2015-03-03", None, "2015-03-10T08:00:00", "de", "Alt"),  # 18 not read
    ("bger_8C_11_2015-D20150303", "8C_11/2015", "2015-03-03", None, "2026-06-20T08:00:00", "de", "Alt"),  # 19 read
]
EXPECTED = {  # external_id -> reason
    "bger_8C_2_2019": "OUT_OF_WINDOW",
    "bger_8C_3_2019": "OUT_OF_WINDOW",
    "bger_X_1": "ING_DOCKET_MALFORMED",
    "bger_X_1-D20260403": "ING_TWIN_SAME_DATE",
    "bger_8C_5_2026": "ING_DECISION_DATE_MISSING",
    "bger_8C_4_2019": "OUT_OF_WINDOW",
    "bger_8C_4_2019-D20190501": "ING_TWIN_SAME_DATE",
    "row:9": "ING_SOURCE_ID_MISSING",
    "row:10": "ING_SOURCE_ID_DUPLICATE",
    "row:12": "ING_SOURCE_ID_DUPLICATE",
    "bger_8C_9_2015-D20150301": "ING_TWIN_SAME_DATE",
    "bger_8C_10_2015": "OUT_OF_WINDOW",
    "bger_8C_10_2015-D20150302": "ING_TWIN_SAME_DATE",
    "bger_8C_11_2015": "OUT_OF_WINDOW",
    "bger_8C_11_2015-D20150303": "ING_TWIN_SAME_DATE",
}
LOADED = {"bger_8C_1_2026", "bger_8C_1_2026-D20260402", "bger_8C_6_2026", "bger_9C_8_2026", "bger_8C_9_2015"}


def write_parquet(path: Path, rows: list[tuple] = ROWS) -> Path:
    import pyarrow as pa
    import pyarrow.parquet as pq

    extra = {"legal_area": None, "full_text": "Erwägungen: 1. Synthetischer Text.", "appealed_court_raw": None}
    pq.write_table(pa.Table.from_pylist([dict(zip(COLUMNS, r, strict=True)) | extra for r in rows]), path)
    return path


def ingest_config():
    from src.ingest.models import IngestConfig

    reg = json.loads((ROOT / "src" / "ingest" / "registry" / "ingest.json").read_text(encoding="utf-8"))
    return IngestConfig.model_validate(reg["versions"][0]["config"])


def test_every_row_is_loaded_or_excluded_with_its_reason(tmp_path):
    from src.ingest.hf_base import EXCLUSION_REASONS, exclusion_ledger, read_base

    parquet = write_parquet(tmp_path / "bger.parquet")
    cfg = ingest_config()
    rows, stats = read_base(parquet, cfg, [])
    ledger = exclusion_ledger(parquet, cfg, [])

    assert ledger.file_rows == len(ROWS) == len(ledger.loaded_ids) + len(ledger.exclusions)
    assert set(ledger.loaded_ids) == LOADED == {i for r in rows for i in (r.decision_id, *r.twins)}
    assert {e.external_id: e.reason_code for e in ledger.exclusions} == EXPECTED
    assert set(ledger.by_reason()) == set(EXCLUSION_REASONS) and sum(ledger.by_reason().values()) == len(EXPECTED)
    # read_base keeps its counters and their meaning: rows the window filter reads, and what happened to them
    assert dict(stats) == {
        "rows_read": 13,
        "twins": 1,
        "out_of_window": 3,  # 8C_11/2015's twin among them: read alone, its base is not read
        "rejected_malformed": 1,
        "no_decision_date": 1,
    }
    assert ledger.rows_read == stats["rows_read"]

    by_id = {e.external_id: e for e in ledger.exclusions}
    assert by_id["bger_X_1-D20260403"].detail["base_reason"] == "ING_DOCKET_MALFORMED"  # lost silently before F-04
    assert by_id["bger_8C_4_2019-D20190501"].detail["base_reason"] == "OUT_OF_WINDOW"
    assert by_id["bger_X_1"].detail["populations"] == ["2026Q2_decision", "2026Q2_publication", "2026Q2_union"]
    assert by_id["bger_X_1"].docket_raw == "Ohne Nummer" and str(by_id["bger_X_1"].decision_date) == "2026-04-03"
    assert by_id["bger_8C_5_2026"].decision_date is None and by_id["bger_8C_5_2026"].detail["decision_date_raw"] is None
    assert by_id["bger_8C_2_2019"].detail == {
        "decision_date": "2019-03-01",
        "publication_date": "2019-03-05",
        "first_seen": "2019-03-05",
    }
    assert by_id["row:9"].detail["decision_id"] is None and by_id["row:9"].row == 9
    assert by_id["row:10"].detail["first_row"] == 0
    assert by_id["row:12"].detail["decision_id"] == "bger_8C_6_2026"  # same id as a row the window filter reads
    assert by_id["row:12"].detail["first_row"] == 11
    # a twin the filter does not read is matched with its base among the rows it reads, never attached to it
    assert by_id["bger_8C_9_2015-D20150301"].detail["base_loaded"] is True
    assert by_id["bger_8C_9_2015-D20150301"].detail["why"] == "twin_not_read"
    assert "why" not in by_id["bger_8C_10_2015-D20150302"].detail  # the first case names its base's reason instead
    assert by_id["bger_8C_10_2015-D20150302"].detail["base_reason"] == "OUT_OF_WINDOW"
    # a twin the filter reads without its base: the whole file gives it its twin reason, the load is unchanged
    assert by_id["bger_8C_11_2015-D20150303"].detail["base_reason"] == "OUT_OF_WINDOW"
    for e in ledger.exclusions:  # identity values only: never ruling text
        assert "Synthetischer" not in json.dumps(e.detail)


def test_classify_is_the_one_rule_for_both_paths(tmp_path):
    """read_base and the ledger decide the rows the filter reads with the same function: same loaded rows."""
    import pyarrow.parquet as pq

    from src.ingest.hf_base import IDENTITY_COLUMNS, classify, read_base, window_filters

    parquet = write_parquet(tmp_path / "bger.parquet")
    cfg = ingest_config()
    rows, _ = read_base(parquet, cfg, [])
    identity = pq.read_table(parquet, columns=list(IDENTITY_COLUMNS), filters=window_filters(cfg, [])).to_pylist()
    from_identity = classify(identity, cfg, [])
    assert sorted(from_identity.rows) == sorted(r.decision_id for r in rows)
    assert {k: v.populations for k, v in from_identity.rows.items()} == {r.decision_id: r.populations for r in rows}


def test_a_window_filter_that_would_lose_a_ruling_is_refused(tmp_path, monkeypatch):
    """The ledger proves the window filter of read_base loses nothing: a narrower filter is caught."""
    from src.ingest import hf_base

    parquet = write_parquet(tmp_path / "bger.parquet")
    cfg = ingest_config()
    narrow = [[("decision_date", ">=", "2026-05-01")]]  # misses April rulings that are in 2026Q2
    monkeypatch.setattr(hf_base, "window_filters", lambda cfg, refs: narrow)
    with pytest.raises(RuntimeError, match="not read by the window filter: it would lose them"):
        hf_base.exclusion_ledger(parquet, cfg, [])


def test_a_twin_of_a_loaded_base_the_filter_does_not_read_says_so(tmp_path):
    """The second ING_TWIN_SAME_DATE case: the base is loaded (here through the publication window), its same-date twin
    is not read by the window filter (no publication date, first seen before the approximate window). read_base is
    certified and frozen, so the ruling keeps no ref for that twin; the exclusion must say why (base_loaded, why), not
    claim the base is not loaded."""
    from src.ingest.hf_base import exclusion_ledger, read_base

    rows = [
        ("bger_8C_1_2024", "8C_1/2024", "2024-06-01", "2026-06-01", "2026-06-01T08:00:00", "de", "Unfallversicherung"),
        (
            "bger_8C_1_2024-D20240601",
            "8C_1/2024",
            "2024-06-01",
            None,
            "2026-01-01T08:00:00",
            "de",
            "Unfallversicherung",
        ),
    ]
    parquet = write_parquet(tmp_path / "twin.parquet", rows)
    cfg = ingest_config()
    base, stats = read_base(parquet, cfg, [])
    ledger = exclusion_ledger(parquet, cfg, [])

    assert [(r.decision_id, r.twins) for r in base] == [("bger_8C_1_2024", [])] and stats["rows_read"] == 1
    assert ledger.file_rows == 2 and ledger.loaded_ids == {"bger_8C_1_2024"}
    (e,) = ledger.exclusions
    assert (e.external_id, e.reason_code, e.row) == ("bger_8C_1_2024-D20240601", "ING_TWIN_SAME_DATE", 1)
    assert e.detail == {
        "base_id": "bger_8C_1_2024",
        "base_loaded": True,
        "why": "twin_not_read",
        "decision_date": "2024-06-01",
        "publication_date": None,
        "first_seen": "2026-01-01",
    }
    assert "base_reason" not in e.detail
