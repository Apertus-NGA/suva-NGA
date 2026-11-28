"""Suva's reference summaries into gold.suva_summary (src/ingest/suva_summary.py) on PostgreSQL.

Runs only with DATABASE_URL: it creates a throwaway database, deploys src/db/sql into it, adds the rulings of three
real exports (one German, one French, one Italian title), loads their summaries twice, and drops the database at
the end. A fourth export without its ruling is refused first: nothing is written. No author is read (D-051): the
test checks that gold.suva_summary has no author column and that the run's event carries no author key.
"""

from __future__ import annotations

import argparse
import os
import shutil
import uuid
from pathlib import Path

import pytest

pytestmark = [pytest.mark.db, pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="needs DATABASE_URL")]

ROOT = Path(__file__).resolve().parents[1]
EXPORTS = {  # file -> language of its title
    "Export_4A_106_2025.html": "de",
    "Export_8C_129_2025.html": "fr",
    "Export_8C_135_2025.html": "it",
}
NO_RULING = "Export_8C_145_2025.html"  # its ruling is never added


@pytest.fixture(scope="module")
def db():
    import psycopg
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    from src.db import deploy

    base = os.environ["DATABASE_URL"]
    name = f"suva_test_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    url = make_conninfo(**(conninfo_to_dict(base) | {"dbname": name}))
    try:
        res = deploy.run_psql(argparse.Namespace(compose=False, url=url), deploy.script_for(deploy.sql_files()), True)
        assert res.returncode == 0, res.stderr
        yield url
    finally:
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _copy(directory: Path, names) -> Path:
    directory.mkdir()
    for n in names:
        shutil.copy(ROOT / "judgements" / n, directory / n)
    return directory


@pytest.fixture(scope="module")
def loaded(db, tmp_path_factory):
    from src.db.pg import connect
    from src.db.registry import profile_version
    from src.db.runs import begin_run, finish_run
    from src.ingest import suva_summary as ss
    from src.ingest.__main__ import load_registries
    from src.ingest.hf_base import bger_url

    tmp = tmp_path_factory.mktemp("suva_summary")
    three = _copy(tmp / "three", EXPORTS)
    four = _copy(tmp / "four", [*EXPORTS, NO_RULING])
    refs, ledger = ss.read_exports(three)
    assert not ledger.exclusions and len(ledger.rows) == 3
    with connect(db, actor="test") as conn:
        load_registries(conn)
        with conn.cursor() as cur:
            pvid, _ = profile_version(cur, "default")
        run = begin_run(
            conn,
            profile_version_id=pvid,
            kind="load",
            step="ingest",
            operation="ingest.test_rulings",
            component_version_id=None,
            params={},
            code_paths=("tests/test_ingest_suva_summary_db.py",),
            actor="test",
        )
        with conn.transaction(), conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO corpus.ruling (docket, decision_date, language, bger_url, origin, created_by_run_id)
                   VALUES (%s, %s, %s, %s, 'base_dataset', %s)""",
                [
                    (r.docket, r.decision_date, r.ruling_language, bger_url(r.docket, r.decision_date), run.run_id)
                    for r in ledger.rows
                ],
            )
            finish_run(cur, run)

        with pytest.raises(LookupError, match="GOLD_RULING_MISSING") as refused:
            ss.load_summaries(conn, four, actor="test")
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM gold.suva_summary")
            after_refusal = cur.fetchone()[0]

        dry = ss.load_summaries(conn, three, actor="test", dry_run=True)
        first = ss.load_summaries(conn, three, actor="test")
        second = ss.load_summaries(conn, three, actor="test")
    return {
        "refused": str(refused.value),
        "after_refusal": after_refusal,
        "dry": dry,
        "first": first,
        "second": second,
        "refs": refs,
    }


def test_refused_load_writes_nothing(loaded):
    assert loaded["after_refusal"] == 0
    assert "Export_8C_145_2025.html" in loaded["refused"]


def test_counts_and_idempotence(loaded):
    assert loaded["dry"]["would_write"] == 3 and loaded["dry"]["written"] == 0
    first, second = loaded["first"], loaded["second"]
    assert (first["rows_in"], first["written"], first["already_loaded"], first["excluded"]) == (3, 3, 0, {})
    assert (second["rows_in"], second["written"], second["already_loaded"], second["excluded"]) == (3, 0, 3, {})
    assert first["closure_ok"] and second["closure_ok"]
    assert first["snapshot_id"] == second["snapshot_id"]


def test_stored_rows(db, loaded):
    import psycopg

    from src.ingest.hf_base import bger_url

    with psycopg.connect(db) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT s.source_file, s.docket, s.decision_date, s.ruling_language::text, s.text_de, s.text_fr,
                      s.bger_url, s.ruling_id = r.ruling_id, s.word_count_de, s.word_count_fr, s.snapshot_id::text
               FROM gold.suva_summary s JOIN corpus.ruling r USING (docket, decision_date) ORDER BY s.source_file"""
        )
        rows = cur.fetchall()
        assert [r[0] for r in rows] == [f"judgements/{n}" for n in sorted(EXPORTS)]
        for file, docket, decided, lang, de, fr, url, linked, wde, wfr, snap in rows:
            assert lang == EXPORTS[file.removeprefix("judgements/")]
            assert de.strip() and fr.strip() and wde > 0 and wfr > 0
            assert url == bger_url(docket, decided) and url.startswith("https://")
            assert linked
            assert snap == loaded["first"]["snapshot_id"]
        # closure: the snapshot records 3 exports, and 3 rows point to it
        cur.execute(
            "SELECT source::text, row_count, (SELECT count(*) FROM gold.suva_summary g "
            "WHERE g.snapshot_id = s.snapshot_id) FROM ops.source_snapshot s WHERE snapshot_id = %s",
            (loaded["first"]["snapshot_id"],),
        )
        assert cur.fetchone() == ("judgements_export", 3, 3)
        cur.execute("SELECT count(*) FROM ops.source_snapshot WHERE source = 'judgements_export'")
        assert cur.fetchone()[0] == 1  # the second run reused it


def test_no_author_anywhere(db, loaded):
    import psycopg

    with psycopg.connect(db) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'gold' "
            "AND table_name = 'suva_summary' AND column_name ILIKE '%%author%%'"
        )
        assert cur.fetchall() == []
        cur.execute("SELECT attributes::text FROM ops.log_event WHERE event_code = 'ingest.suva_summary.loaded'")
        events = [r[0] for r in cur.fetchall()]
        assert len(events) == 2 and not any("author" in e.lower() for e in events)  # two succeeded runs
    for counts in (loaded["first"], loaded["second"]):
        assert not any("author" in key for key in counts)
