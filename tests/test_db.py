"""Migrations runner, schema constraints and ingest_runs (WP-A)."""

from __future__ import annotations

import psycopg
import pytest
from psycopg import errors

from suva_data import config, db

pytestmark = pytest.mark.db

EXPECTED_TABLES = {
    "ingest_runs",
    "raw_files",
    "rulings",
    "source_records",
    "ruling_texts",
    "conflicts",
    "statute_refs",
    "labels",
    "gold_summaries",
    "schema_migrations",
}
HASH = "a" * 64


def _tables(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}


def _ruling(conn, docket="8C_72/2025", decision_date="2025-11-03", **extra) -> int:
    cols = {
        "docket": docket,
        "decision_date": decision_date,
        "division": docket.split("_")[0],
        "in_window": True,
        **extra,
    }
    query = f"INSERT INTO rulings ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) RETURNING id"
    return conn.execute(query, list(cols.values())).fetchone()[0]


def _source_record(conn, key="k1", docket="8C_72/2025") -> int:
    return conn.execute(
        "INSERT INTO source_records (source, source_key, docket) VALUES ('swiss_caselaw', %s, %s) RETURNING id",
        (key, docket),
    ).fetchone()[0]


# --- migrations ---------------------------------------------------------------------------------


def test_migrate_from_scratch_then_idempotent(db_conn):
    db_conn.execute("DROP SCHEMA public CASCADE")
    db_conn.execute("CREATE SCHEMA public")
    expected_files = sorted(p.name for p in config.MIGRATIONS_DIR.glob("*.sql"))

    assert db.migrate(db_conn) == expected_files
    assert EXPECTED_TABLES <= _tables(db_conn)
    assert db_conn.execute("SELECT to_regclass('public.v_relevance')").fetchone()[0] is not None
    applied = db_conn.execute("SELECT filename, sha256, applied_at FROM schema_migrations ORDER BY 1").fetchall()
    assert [r[0] for r in applied] == expected_files

    assert db.migrate(db_conn) == []  # second run: nothing to do, nothing re-applied
    assert (
        db_conn.execute("SELECT filename, sha256, applied_at FROM schema_migrations ORDER BY 1").fetchall() == applied
    )


def test_migrate_runs_in_filename_order_each_once(db_conn, tmp_path):
    (tmp_path / "902_b.sql").write_text("INSERT INTO _mig_order (step) VALUES ('902');")
    (tmp_path / "901_a.sql").write_text(
        "CREATE TABLE _mig_order (n serial, step text); INSERT INTO _mig_order (step) VALUES ('100%');"
    )
    try:
        assert db.migrate(db_conn, tmp_path) == ["901_a.sql", "902_b.sql"]
        assert db.migrate(db_conn, tmp_path) == []
        (tmp_path / "903_c.sql").write_text("INSERT INTO _mig_order (step) VALUES ('903');")
        assert db.migrate(db_conn, tmp_path) == ["903_c.sql"]
        assert [r[0] for r in db_conn.execute("SELECT step FROM _mig_order ORDER BY n")] == ["100%", "902", "903"]
    finally:
        db_conn.execute("DROP TABLE IF EXISTS _mig_order")
        db_conn.execute("DELETE FROM schema_migrations WHERE filename LIKE '90%'")


def test_failed_migration_leaves_nothing_behind(db_conn, tmp_path):
    (tmp_path / "901_bad.sql").write_text("CREATE TABLE _mig_half (id int); SELECT no_such_function();")
    with pytest.raises(psycopg.Error):
        db.migrate(db_conn, tmp_path)
    assert "_mig_half" not in _tables(db_conn)  # its own transaction was rolled back
    assert not db_conn.execute("SELECT 1 FROM schema_migrations WHERE filename = '901_bad.sql'").fetchone()
    assert db_conn.execute("SELECT 1").fetchone() == (1,)  # connection still usable


def test_changed_applied_migration_is_refused(db_conn, tmp_path):
    f = tmp_path / "901_a.sql"
    f.write_text("SELECT 1;")
    try:
        db.migrate(db_conn, tmp_path)
        f.write_text("SELECT 2;")
        with pytest.raises(RuntimeError, match="901_a.sql"):
            db.migrate(db_conn, tmp_path)
    finally:
        db_conn.execute("DELETE FROM schema_migrations WHERE filename LIKE '90%'")


def test_fixture_gives_empty_tables(db_conn):
    for table in sorted(EXPECTED_TABLES - {"schema_migrations"}):
        assert db_conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0, table


# --- schema constraints ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "docket", ["8C-72-2025", "8C_72_2025", "8c_72/2025", "C_72/2025", "8C_72/25", " 8C_72/2025", ""]
)
def test_rulings_reject_bad_docket(db_conn, docket):
    with pytest.raises(errors.CheckViolation):
        db_conn.execute(
            "INSERT INTO rulings (docket, decision_date, division, in_window) VALUES (%s, '2025-11-03', '8C', true)",
            (docket,),
        )


def test_rulings_accept_valid_row_and_null_unknowns(db_conn):
    rid = _ruling(db_conn, language="fr", publication_date="2025-11-03")
    row = db_conn.execute("SELECT starred, area, field_sources FROM rulings WHERE id = %s", (rid,)).fetchone()
    assert row == (None, None, {})  # unknown is NULL, never a default


def test_rulings_reject_bad_language(db_conn):
    with pytest.raises(errors.CheckViolation):
        _ruling(db_conn, language="en")


def test_rulings_reject_publication_before_decision(db_conn):
    with pytest.raises(errors.CheckViolation):
        _ruling(db_conn, decision_date="2025-11-03", publication_date="2025-11-02")


def test_rulings_unique_docket_and_date(db_conn):
    _ruling(db_conn)
    _ruling(db_conn, decision_date="2025-11-04")  # same docket, other date: a real double ruling
    with pytest.raises(errors.UniqueViolation):
        _ruling(db_conn)


def test_canonical_text_cannot_have_bad_reason(db_conn):
    sr = _source_record(db_conn)
    insert = (
        "INSERT INTO ruling_texts (source_record_id, source, text, sha256_normalized, char_count, bad_reason, is_canonical) "
        "VALUES (%s, 'swiss_caselaw', 'x', %s, 1, %s, %s)"
    )
    with pytest.raises(errors.CheckViolation):
        db_conn.execute(insert, (sr, HASH, "error_page", True))
    db_conn.execute(insert, (sr, HASH, "error_page", False))  # a bad text may be stored, just not as canonical
    with pytest.raises(errors.CheckViolation):
        db_conn.execute("UPDATE ruling_texts SET is_canonical = true WHERE source_record_id = %s", (sr,))


def test_only_one_canonical_text_per_ruling(db_conn):
    rid = _ruling(db_conn)
    insert = (
        "INSERT INTO ruling_texts (source_record_id, ruling_id, source, text, sha256_normalized, char_count, is_canonical) "
        "VALUES (%s, %s, 'swiss_caselaw', 'x', %s, 1, true)"
    )
    db_conn.execute(insert, (_source_record(db_conn, "k1"), rid, HASH))
    with pytest.raises(errors.UniqueViolation):
        db_conn.execute(insert, (_source_record(db_conn, "k2"), rid, HASH))


def test_source_records_reject_unknown_source_and_status(db_conn):
    with pytest.raises(errors.CheckViolation):
        db_conn.execute(
            "INSERT INTO source_records (source, source_key, docket) VALUES ('wikipedia', 'k', '8C_72/2025')"
        )
    with pytest.raises(errors.CheckViolation):
        db_conn.execute(
            "INSERT INTO source_records (source, source_key, docket, status) VALUES ('swiss_caselaw', 'k', '8C_72/2025', 'done')"
        )


def test_raw_files_reject_bad_sha256(db_conn):
    with pytest.raises(errors.CheckViolation):
        db_conn.execute(
            "INSERT INTO raw_files (source, path, sha256, bytes) VALUES ('suva', 'a.xlsx', 'not-a-hash', 1)"
        )


def test_labels_reject_bad_value_and_quarter(db_conn):
    rid = _ruling(db_conn)
    with pytest.raises(errors.CheckViolation):
        db_conn.execute("INSERT INTO labels (ruling_id, label_set, value) VALUES (%s, 's', 'maybe')", (rid,))
    with pytest.raises(errors.CheckViolation):
        db_conn.execute(
            "INSERT INTO labels (ruling_id, label_set, value, quarter) VALUES (%s, 's', 'relevant', '2025Q4')", (rid,)
        )


# --- ingest_runs ------------------------------------------------------------------------------------


def test_start_and_finish_run(db_conn):
    run_id = db.start_run(db_conn, "load", {"source": "swiss_caselaw", "note": "a\x00b"})
    row = db_conn.execute(
        "SELECT command, params, git_commit, status, finished_at FROM ingest_runs WHERE id = %s", (run_id,)
    ).fetchone()
    assert row[0] == "load" and row[1] == {"source": "swiss_caselaw", "note": "ab"}
    assert row[2] == db.git_commit()
    assert row[3] == "running" and row[4] is None

    db.finish_run(db_conn, run_id, "ok", {"read": 3})
    status, report, finished = db_conn.execute(
        "SELECT status, report, finished_at FROM ingest_runs WHERE id = %s", (run_id,)
    ).fetchone()
    assert status == "ok" and report == {"read": 3} and finished is not None

    with pytest.raises(ValueError):
        db.finish_run(db_conn, run_id, "done")
    with pytest.raises(LookupError):
        db.finish_run(db_conn, run_id + 1000, "ok")


def test_start_run_tolerates_missing_git(db_conn, monkeypatch):
    def boom(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(db.subprocess, "run", boom)
    run_id = db.start_run(db_conn, "build")
    assert db_conn.execute("SELECT git_commit, params FROM ingest_runs WHERE id = %s", (run_id,)).fetchone() == (
        None,
        {},
    )
