"""register_raw_files and load_source_records (WP-A)."""

from __future__ import annotations

import hashlib

import pytest

from suva_data import load, textnorm
from suva_data.models import SourceRecord

pytestmark = pytest.mark.db

# Odd whitespace, a non-breaking space, CRLF and a decomposed character: must come back byte for byte.
GOOD_TEXT = (
    "Bundesgericht \r\n\r\n  Urteil vom 3. November 2025 \n\n\tSachverhalt:\n"
    + "Die Beschwerdeführerin verlangt eine Invalidenrente.  " * 20
    + "\n\nLuzern, 3. November 2025\n\nDer Präsident:   Die Gerichtsschreiberin:\n\n"
)
ERROR_PAGE = "Dokument nicht gefunden"


def rec(key="k1", docket="8C_72/2025", decision_date="2025-11-03", source="swiss_caselaw", **kw) -> SourceRecord:
    return SourceRecord(source=source, source_key=key, docket=docket, decision_date=decision_date, **kw)


def snapshot(conn) -> dict:
    """Everything the load writes, including the row ids."""
    return {
        "source_records": conn.execute("SELECT * FROM source_records ORDER BY id").fetchall(),
        "ruling_texts": conn.execute("SELECT * FROM ruling_texts ORDER BY id").fetchall(),
        "raw_files": conn.execute("SELECT * FROM raw_files ORDER BY id").fetchall(),
    }


def assert_counts_add_up(c: dict) -> None:
    assert c["read"] == c["inserted"] + c["updated"] + c["unchanged"] + c["rejected"], c


@pytest.fixture
def snap(tmp_path, monkeypatch):
    monkeypatch.setattr(load.config, "SNAPSHOT_DIR", tmp_path)
    (tmp_path / "swiss_caselaw").mkdir()
    (tmp_path / "swiss_caselaw" / "bger_window.parquet").write_bytes(b"parquet bytes")
    (tmp_path / "swiss_caselaw" / "other.json").write_bytes(b"{}")
    return tmp_path


# --- raw files --------------------------------------------------------------------------------------

def test_register_raw_files_is_idempotent(db_conn, snap):
    paths = ["swiss_caselaw/bger_window.parquet", snap / "swiss_caselaw" / "other.json"]  # relative and absolute
    assert load.register_raw_files(db_conn, "swiss_caselaw", paths) == {"read": 2, "inserted": 2, "updated": 0, "unchanged": 0}
    before = snapshot(db_conn)
    assert [r[1:] for r in before["raw_files"]] == [
        ("swiss_caselaw", "swiss_caselaw/bger_window.parquet", hashlib.sha256(b"parquet bytes").hexdigest(), 13),
        ("swiss_caselaw", "swiss_caselaw/other.json", hashlib.sha256(b"{}").hexdigest(), 2),
    ]
    assert load.register_raw_files(db_conn, "swiss_caselaw", paths) == {"read": 2, "inserted": 0, "updated": 0, "unchanged": 2}
    assert snapshot(db_conn) == before

    (snap / "swiss_caselaw" / "other.json").write_bytes(b"{} ")
    assert load.register_raw_files(db_conn, "swiss_caselaw", paths) == {"read": 2, "inserted": 0, "updated": 1, "unchanged": 1}
    after = snapshot(db_conn)["raw_files"]
    assert after[1][0] == before["raw_files"][1][0] and after[1][3:] == (hashlib.sha256(b"{} ").hexdigest(), 3)


def test_register_raw_files_refuses_bad_input(db_conn, snap, tmp_path_factory):
    with pytest.raises(ValueError):
        load.register_raw_files(db_conn, "wikipedia", ["swiss_caselaw/other.json"])
    outside = tmp_path_factory.mktemp("outside") / "x.json"
    outside.write_bytes(b"{}")
    with pytest.raises(ValueError):
        load.register_raw_files(db_conn, "swiss_caselaw", [outside])
    with pytest.raises(FileNotFoundError):
        load.register_raw_files(db_conn, "swiss_caselaw", ["swiss_caselaw/missing.json"])
    assert snapshot(db_conn)["raw_files"] == []


# --- source records ---------------------------------------------------------------------------------

def test_load_stores_record_and_text_unchanged(db_conn, snap):
    load.register_raw_files(db_conn, "swiss_caselaw", ["swiss_caselaw/bger_window.parquet"])
    r = rec(
        fields={"language": "de", "starred": False, "cited_decisions": ["8C_1/2020"]},
        record={"decision_id": "bger_8C_72_2025", "nested": {"n": 1.5, "none": None}},
        text=GOOD_TEXT,
        raw_file="swiss_caselaw/bger_window.parquet",
    )
    counts = load.load_source_records(db_conn, [r])
    assert counts == {"read": 1, "inserted": 1, "updated": 0, "unchanged": 0, "rejected": 0, "not_stored": 0, "texts": 1, "bad_texts": 0}

    row = db_conn.execute(
        "SELECT sr.source, sr.source_key, sr.docket, sr.decision_date::text, sr.fields, sr.record, f.path, sr.ruling_id, sr.status, sr.status_reason "
        "FROM source_records sr JOIN raw_files f ON f.id = sr.raw_file_id"
    ).fetchone()
    assert row == (
        "swiss_caselaw", "k1", "8C_72/2025", "2025-11-03", r.fields, r.record,
        "swiss_caselaw/bger_window.parquet", None, "loaded", None,
    )
    text, source, sha, chars, bad, canonical, ruling_id = db_conn.execute(
        "SELECT text, source, sha256_normalized, char_count, bad_reason, is_canonical, ruling_id FROM ruling_texts"
    ).fetchone()
    assert text == GOOD_TEXT  # exactly as given: no trimming, no NFC, no newline conversion
    assert (source, sha, chars, bad, canonical, ruling_id) == (
        "swiss_caselaw", textnorm.text_hash(GOOD_TEXT), len(GOOD_TEXT), None, False, None,
    )


def test_load_is_idempotent_and_keeps_reconciler_state(db_conn):
    records = [rec("k1", text=GOOD_TEXT, fields={"language": "de"}), rec("k2", docket="9C_5/2026", decision_date=None), rec("k3", text=ERROR_PAGE)]
    first = load.load_source_records(db_conn, records)
    assert first == {"read": 3, "inserted": 3, "updated": 0, "unchanged": 0, "rejected": 0, "not_stored": 0, "texts": 2, "bad_texts": 1}
    before = snapshot(db_conn)

    second = load.load_source_records(db_conn, iter(records))
    assert second == {"read": 3, "inserted": 0, "updated": 0, "unchanged": 3, "rejected": 0, "not_stored": 0, "texts": 2, "bad_texts": 1}
    assert snapshot(db_conn) == before

    # What the reconciler sets later must survive a reload of unchanged records.
    ruling_id = db_conn.execute(
        "INSERT INTO rulings (docket, decision_date, division, in_window) VALUES ('8C_72/2025', '2025-11-03', '8C', true) RETURNING id"
    ).fetchone()[0]
    db_conn.execute("UPDATE source_records SET ruling_id = %s, status = 'used' WHERE source_key = 'k1'", (ruling_id,))
    db_conn.execute("UPDATE source_records SET status = 'duplicate', status_reason = 'same text as k1' WHERE source_key = 'k3'")
    db_conn.execute(
        "UPDATE ruling_texts SET ruling_id = %s, is_canonical = true WHERE source_record_id = (SELECT id FROM source_records WHERE source_key = 'k1')",
        (ruling_id,),
    )
    reconciled = snapshot(db_conn)
    third = load.load_source_records(db_conn, records)
    assert third == second
    assert snapshot(db_conn) == reconciled


def test_changed_record_is_updated_and_reset(db_conn):
    load.load_source_records(db_conn, [rec("k1", text=GOOD_TEXT, fields={"language": "de"}), rec("k2", text=GOOD_TEXT)])
    ruling_id = db_conn.execute(
        "INSERT INTO rulings (docket, decision_date, division, in_window) VALUES ('8C_72/2025', '2025-11-03', '8C', true) RETURNING id"
    ).fetchone()[0]
    db_conn.execute("UPDATE source_records SET ruling_id = %s, status = 'used'", (ruling_id,))
    db_conn.execute("UPDATE ruling_texts SET ruling_id = %s", (ruling_id,))
    db_conn.execute("UPDATE ruling_texts SET is_canonical = true WHERE source_record_id = (SELECT id FROM source_records WHERE source_key = 'k1')")
    ids = dict(db_conn.execute("SELECT source_key, id FROM source_records").fetchall())

    # k1: its text is now an error page; k2: only a metadata field changed.
    counts = load.load_source_records(db_conn, [rec("k1", text=ERROR_PAGE, fields={"language": "de"}), rec("k2", text=GOOD_TEXT, fields={"area": "UV"})])
    assert counts == {"read": 2, "inserted": 0, "updated": 2, "unchanged": 0, "rejected": 0, "not_stored": 0, "texts": 2, "bad_texts": 1}
    rows = db_conn.execute(
        "SELECT sr.source_key, sr.id, sr.fields, sr.ruling_id, sr.status, t.text, t.bad_reason, t.is_canonical, t.ruling_id, t.char_count "
        "FROM source_records sr JOIN ruling_texts t ON t.source_record_id = sr.id ORDER BY 1"
    ).fetchall()
    assert rows == [
        ("k1", ids["k1"], {"language": "de"}, None, "loaded", ERROR_PAGE, "error_page", False, None, len(ERROR_PAGE)),
        ("k2", ids["k2"], {"area": "UV"}, None, "loaded", GOOD_TEXT, None, False, None, len(GOOD_TEXT)),
    ]

    # A record that no longer has a text loses its text row.
    counts = load.load_source_records(db_conn, [rec("k1", fields={"language": "de"})])
    assert (counts["updated"], counts["texts"]) == (1, 0)
    assert [r[0] for r in db_conn.execute("SELECT source_record_id FROM ruling_texts")] == [ids["k2"]]


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("", "empty"),
        ("  \n ", "empty"),
        ("Dokument nicht gefunden", "error_page"),
        ("Bundesgericht. Urteil. Gerichtsschreiber", "too_short"),
        ("Erwägung ohne Ende. " * 100, "no_signature_block"),
    ],
)
def test_bad_text_is_stored_with_its_reason(db_conn, text, reason):
    assert textnorm.bad_text_reason(text) == reason  # the test data means what it says
    counts = load.load_source_records(db_conn, [rec(text=text)])
    assert (counts["inserted"], counts["texts"], counts["bad_texts"]) == (1, 1, 1)
    assert db_conn.execute("SELECT text, bad_reason, char_count, is_canonical FROM ruling_texts").fetchone() == (text, reason, len(text), False)
    assert db_conn.execute("SELECT status FROM source_records").fetchone() == ("loaded",)  # judging the text is the reconciler's job


def test_record_without_text_gets_no_text_row(db_conn):
    counts = load.load_source_records(db_conn, [rec(source="bger_list", key="20251103:8C_72/2025", fields={"starred": True})])
    assert (counts["inserted"], counts["texts"]) == (1, 0)
    assert db_conn.execute("SELECT count(*) FROM ruling_texts").fetchone()[0] == 0


INVALID = [
    (dict(docket="8C-72-2025"), "bad docket"),
    (dict(docket="CH_BGer_008_8C-72-2025"), "bad docket"),
    (dict(decision_date="03.11.2025"), "bad decision_date"),
    (dict(decision_date="2025-02-30"), "bad decision_date"),
    (dict(fields={"language": "de", "court": "BGer"}), "unknown fields ['court']"),
]


@pytest.mark.parametrize(("override", "reason"), INVALID)
def test_invalid_record_is_rejected_not_fatal(db_conn, override, reason):
    records = [rec("good1", text=GOOD_TEXT), rec("bad", text=GOOD_TEXT, **override), rec("good2")]
    counts = load.load_source_records(db_conn, records)
    assert counts == {"read": 3, "inserted": 2, "updated": 0, "unchanged": 0, "rejected": 1, "not_stored": 0, "texts": 2, "bad_texts": 0}
    assert_counts_add_up(counts)

    rows = dict((r[0], r[1:]) for r in db_conn.execute("SELECT source_key, status, status_reason, docket FROM source_records"))
    assert rows["good1"][:2] == ("loaded", None) and rows["good2"][:2] == ("loaded", None)
    status, status_reason, docket = rows["bad"]
    assert status == "rejected" and status_reason.startswith("load: ") and reason in status_reason
    assert docket == override.get("docket", "8C_72/2025")  # kept as the source gave it
    assert db_conn.execute("SELECT count(*) FROM ruling_texts").fetchone()[0] == 2  # the rejected record's text is kept too

    before = snapshot(db_conn)
    again = load.load_source_records(db_conn, records)
    assert again == {"read": 3, "inserted": 0, "updated": 0, "unchanged": 2, "rejected": 1, "not_stored": 0, "texts": 2, "bad_texts": 0}
    assert snapshot(db_conn) == before


def test_unstorable_records_are_counted_not_stored(db_conn):
    records = [
        rec("good"),
        rec("x", source="wikipedia"),  # source_records.source could not hold it
        rec(""),  # no key to store it under
        rec("good", docket="9C_1/2026"),  # same key again: the first one wins
    ]
    counts = load.load_source_records(db_conn, records)
    assert counts == {"read": 4, "inserted": 1, "updated": 0, "unchanged": 0, "rejected": 3, "not_stored": 3, "texts": 0, "bad_texts": 0}
    assert_counts_add_up(counts)
    assert db_conn.execute("SELECT source_key, docket, status FROM source_records").fetchall() == [("good", "8C_72/2025", "loaded")]


def test_rejected_record_becomes_loaded_once_fixed(db_conn):
    load.load_source_records(db_conn, [rec("k1", decision_date="2025-13-01")])
    assert db_conn.execute("SELECT status, decision_date FROM source_records").fetchone() == ("rejected", None)
    counts = load.load_source_records(db_conn, [rec("k1", decision_date=None)])  # stored columns identical, only validity differs
    assert (counts["updated"], counts["rejected"]) == (1, 0)
    assert db_conn.execute("SELECT status, status_reason FROM source_records").fetchone() == ("loaded", None)


def test_same_key_in_two_sources_are_two_records(db_conn):
    counts = load.load_source_records(db_conn, [rec("same", text=GOOD_TEXT), rec("same", source="entscheidsuche", text=ERROR_PAGE)])
    assert (counts["inserted"], counts["texts"], counts["bad_texts"]) == (2, 2, 1)
    assert db_conn.execute(
        "SELECT sr.source, t.source, t.bad_reason FROM source_records sr JOIN ruling_texts t ON t.source_record_id = sr.id ORDER BY 1"
    ).fetchall() == [("entscheidsuche", "entscheidsuche", "error_page"), ("swiss_caselaw", "swiss_caselaw", None)]


def test_nul_bytes_are_stripped(db_conn):
    text = GOOD_TEXT[:50] + "\x00" + GOOD_TEXT[50:]
    r = rec(fields={"subject": "Unfall\x00versicherung"}, record={"ti\x00tle": "a\x00b", "list": ["x\x00", {"k": "\x00"}], "nan": float("nan")}, text=text)
    counts = load.load_source_records(db_conn, [r])
    assert (counts["inserted"], counts["rejected"]) == (1, 0)
    fields, record = db_conn.execute("SELECT fields, record FROM source_records").fetchone()
    assert fields == {"subject": "Unfallversicherung"}
    assert record == {"title": "ab", "list": ["x", {"k": ""}], "nan": None}
    assert db_conn.execute("SELECT text, char_count, sha256_normalized FROM ruling_texts").fetchone() == (GOOD_TEXT, len(GOOD_TEXT), textnorm.text_hash(GOOD_TEXT))
    assert load.load_source_records(db_conn, [r])["unchanged"] == 1


def test_unregistered_raw_file_fails_loudly_and_writes_nothing(db_conn):
    with pytest.raises(KeyError, match="register_raw_files"):
        load.load_source_records(db_conn, [rec("k1"), rec("k2", raw_file="swiss_caselaw/nope.parquet")])
    assert db_conn.execute("SELECT count(*) FROM source_records").fetchone()[0] == 0


def test_load_in_batches(db_conn, monkeypatch):
    monkeypatch.setattr(load, "BATCH_ROWS", 7)
    records = [rec(f"k{i:03d}", docket=f"8C_{i + 1}/2025", text=GOOD_TEXT + str(i) if i % 3 else None) for i in range(50)]
    records.insert(20, rec("bad", docket="nope"))
    first = load.load_source_records(db_conn, records)
    assert first == {"read": 51, "inserted": 50, "updated": 0, "unchanged": 0, "rejected": 1, "not_stored": 0, "texts": 33, "bad_texts": 0}
    assert_counts_add_up(first)
    assert db_conn.execute("SELECT count(*), count(DISTINCT docket) FROM source_records").fetchone() == (51, 51)
    # every text sits on its own record
    assert db_conn.execute(
        "SELECT count(*) FROM ruling_texts t JOIN source_records sr ON sr.id = t.source_record_id "
        "WHERE t.text = %s || ltrim(substr(sr.source_key, 2), '0')",
        (GOOD_TEXT,),
    ).fetchone()[0] == 33
    second = load.load_source_records(db_conn, records)
    assert (second["unchanged"], second["rejected"], second["inserted"], second["updated"]) == (50, 1, 0, 0)
    assert_counts_add_up(second)
