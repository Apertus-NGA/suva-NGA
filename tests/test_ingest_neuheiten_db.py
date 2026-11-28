"""The Neuheiten loader (src/ingest/neuheiten.py) on PostgreSQL: one snapshot, every entry a source ref or an
exclusion (closure, F-04), exact publication and subject observations, idempotent. Runs only with DATABASE_URL: it
creates a throwaway database, deploys src/db/sql into it and drops it at the end.

Data: the committed real list page tests/fixtures/bger_lists/20251212.html (6 real rulings, DE, FR and IT) and its
empty weekend page. Three rulings are checked field by field: 8C_458/2025 (DE, starred), 8C_648/2025 (FR) and
1C_594/2025 (IT). Declared change (G9): in the copy, 8C_313/2024's decision date is moved to 13.08.2025 so that one
entry falls outside every window. No Suva label is written (D-031); no ruling text (D-038).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import uuid
from datetime import date
from pathlib import Path

import pytest

pytestmark = [pytest.mark.db, pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="needs DATABASE_URL")]

FIXTURES = Path(__file__).parent / "fixtures" / "bger_lists"
ROOT = Path(__file__).resolve().parents[1]
# (docket, decision date, language) inserted as rulings; 8C_313/2024 is left out (out of window in the copy)
RULINGS = [
    ("8C_458/2025", date(2025, 11, 18), "de"),
    ("8C_648/2025", date(2025, 12, 1), "fr"),
    ("1C_594/2025", date(2025, 11, 11), "it"),
    ("4A_508/2025", date(2025, 11, 12), "de"),
    ("7B_65/2023", date(2025, 12, 5), "fr"),
]


def _pages(tmp: Path) -> Path:
    d = tmp / "bger_list"
    d.mkdir()
    shutil.copy(FIXTURES / "20251213.html", d / "20251213.html")
    page = (FIXTURES / "20251212.html").read_text(encoding="utf-8")
    assert page.count("13.11.2025") == 1
    (d / "20251212.html").write_text(page.replace("13.11.2025", "13.08.2025"), encoding="utf-8")
    return d


def _cfg():
    from src.ingest.models import IngestConfig

    reg = json.loads((ROOT / "src/ingest/registry/ingest.json").read_text(encoding="utf-8"))
    return IngestConfig.model_validate(reg["versions"][0]["config"])


def test_an_in_window_entry_missing_from_the_corpus_is_counted_not_excluded(tmp_path):
    from src.ingest import neuheiten

    pages = neuheiten.read_pages(_pages(tmp_path))
    keys = {(d, dd) for d, dd, _ in RULINGS if d != "7B_65/2023"}
    c = neuheiten.classify(pages.rows, keys, _cfg())
    assert [r.docket for r in c.not_in_base] == ["7B_65/2023"]
    assert c.by_reason() == {"OUT_OF_WINDOW": 1} and len(c.loaded) == 4


@pytest.fixture(scope="module")
def loaded(tmp_path_factory):
    import psycopg
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    from src.db import deploy
    from src.db.pg import connect
    from src.db.registry import profile_version
    from src.db.runs import begin_run, finish_run
    from src.ingest import neuheiten
    from src.ingest.__main__ import load_registries

    base = os.environ["DATABASE_URL"]
    name = f"suva_test_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    url = make_conninfo(**(conninfo_to_dict(base) | {"dbname": name}))
    try:
        res = deploy.run_psql(argparse.Namespace(compose=False, url=url), deploy.script_for(deploy.sql_files()), True)
        assert res.returncode == 0, res.stderr
        directory = _pages(tmp_path_factory.mktemp("neuheiten"))
        with connect(url, actor="test") as conn:
            load_registries(conn)
            with conn.cursor() as cur:
                pvid, _ = profile_version(cur, "default")
            run = begin_run(
                conn,
                profile_version_id=pvid,
                kind="ingest",
                step="ingest",
                operation="test.rulings",
                component_version_id=None,
                params={},
                code_paths=("tests/test_ingest_neuheiten_db.py",),
                actor="test",
            )
            with conn.transaction(), conn.cursor() as cur:
                cur.executemany(
                    """INSERT INTO corpus.ruling (docket, decision_date, language, bger_url, origin, created_by_run_id)
                       VALUES (%s, %s, %s, 'https://www.bger.ch/', 'base_dataset', %s)""",
                    [(d, dd, lang, run.run_id) for d, dd, lang in RULINGS],
                )
                finish_run(cur, run)
            dry = neuheiten.dry_run(conn, directory)
            first = neuheiten.load_neuheiten(conn, directory, actor="test")
            again = neuheiten.load_neuheiten(conn, directory, actor="test")
        yield url, dry, first, again
    finally:
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _all(url: str, sql: str, args: tuple = ()):
    import psycopg

    with psycopg.connect(url) as conn:
        return conn.execute(sql, args).fetchall()


def test_counts_of_the_first_and_second_load(loaded):
    _, dry, first, again = loaded
    assert dry["rows_in"] == first["rows_in"] == 6 and dry["matched"] == 5 and dry["not_in_base"] == 0
    assert first["files"] == 2 and first["pages_with_list"] == 1
    assert first["written"] == 5 and first["already_loaded"] == 0 and first["excluded"] == {"OUT_OF_WINDOW": 1}
    assert first["publication_observations_written"] == 5 and first["subject_observations_written"] == 5
    assert first["closure_ok"] is True and first["row_count"] == 6
    # idempotent: the same snapshot, nothing new
    assert again["snapshot_id"] == first["snapshot_id"]
    assert again["written"] == 0 and again["already_loaded"] == 5 and again["exclusions_written"] == 0
    assert again["publication_observations_written"] == 0 and again["subject_observations_written"] == 0


def test_one_snapshot_and_its_closure(loaded):
    url, _, first, _ = loaded
    snaps = _all(
        url, "SELECT source::text, revision, row_count FROM ops.source_snapshot WHERE source = 'bger_neuheiten'"
    )
    assert snaps == [("bger_neuheiten", "7eb6025dcac351e426a0fcae1cba3a02c332e7ed", 6)]
    closure = _all(
        url,
        """SELECT loaded_refs, exclusions, unaccounted_rows, closure_ok, exclusions_by_reason
           FROM corpus.v_ingest_closure WHERE snapshot_id = %s""",
        (first["snapshot_id"],),
    )
    assert closure == [(5, 1, 0, True, {"OUT_OF_WINDOW": 1})]
    exc = _all(url, "SELECT source, external_id, docket_raw, decision_date, reason_code FROM corpus.ingest_exclusion")
    assert exc == [("aza_id", "aza://13-11-2025-8C_313-2024", "8C_313/2024", date(2025, 8, 13), "OUT_OF_WINDOW")]


def test_three_real_rulings_stored_field_by_field(loaded):
    url, *_ = loaded
    rows = _all(
        url,
        """SELECT r.docket, r.language::text, s.external_id, p.source::text, p.quality::text, p.observed_date, p.star,
                  p.sachgebiet, o.rubric, o.star
           FROM corpus.ruling r
           JOIN corpus.ruling_source_ref s ON s.ruling_id = r.ruling_id AND s.source = 'aza_id'
           JOIN corpus.publication_observation p ON p.ruling_id = r.ruling_id AND p.source = 'neuheiten'
           JOIN corpus.subject_observation o ON o.ruling_id = r.ruling_id AND o.source = 'neuheiten'
           WHERE r.docket IN ('8C_458/2025', '8C_648/2025', '1C_594/2025') ORDER BY r.docket""",
    )
    day = date(2025, 12, 12)
    assert rows[1] == (
        "8C_458/2025", "de", "aza://18-11-2025-8C_458-2025", "neuheiten", "exact", day, True,
        "Unfallversicherung", "Unfallversicherung", True,
    )  # fmt: skip
    assert rows[2][:7] == ("8C_648/2025", "fr", "aza://01-12-2025-8C_648-2025", "neuheiten", "exact", day, False)
    assert rows[2][7] == rows[2][8] == "Santé & sécurité sociale" and rows[2][9] is False
    assert rows[0][:7] == ("1C_594/2025", "it", "aza://11-11-2025-1C_594-2025", "neuheiten", "exact", day, False)
    assert rows[0][7].startswith("Pianificazione territoriale") and rows[0][9] is False
