"""Platform on PostgreSQL: the ingest exclusion ledger and its closure (F-04), the pipeline role (F-11), the code
of every run (F-09) and the registry's approvals (F-12). Runs only with DATABASE_URL: it creates a throwaway database,
deploys src/db/sql into it, loads the synthetic parquet of tests/test_ingest_ledger.py (one row per exclusion reason),
and drops the database at the end. No Suva label is written (D-031); no real ruling text (D-038).
"""

from __future__ import annotations

import argparse
import json
import os
import uuid
from pathlib import Path

import pytest

from tests.test_ingest_ledger import EXPECTED, LOADED, ROWS, ingest_config, write_parquet

pytestmark = [pytest.mark.db, pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="needs DATABASE_URL")]


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


@pytest.fixture(scope="module")
def ingested(db, tmp_path_factory):
    """A load whose ledger loses one row (refused, nothing written), then the real load, then the same load again."""
    from dataclasses import replace

    from src.db.pg import connect
    from src.ingest import hf_base
    from src.ingest.__main__ import load_registries

    parquet = write_parquet(tmp_path_factory.mktemp("closure") / "bger.parquet")
    cfg = ingest_config()
    real = hf_base.exclusion_ledger
    with connect(db, actor="test") as conn:
        load_registries(conn)
        with pytest.MonkeyPatch.context() as mp:  # declared mock (G9): the ledger forgets one excluded row
            mp.setattr(hf_base, "exclusion_ledger", lambda *a: replace(real(*a), exclusions=real(*a).exclusions[1:]))
            with pytest.raises(RuntimeError, match="ingest closure failed") as lost:
                hf_base.load_base(conn, parquet, cfg, [], actor="test")
        first = hf_base.load_base(conn, parquet, cfg, [], actor="test")
        again = hf_base.load_base(conn, parquet, cfg, [], actor="test")
    return db, str(lost.value), first, again


def _one(url: str, sql: str, args: tuple = ()):
    import psycopg

    with psycopg.connect(url) as conn:
        return conn.execute(sql, args).fetchone()


def test_a_load_that_loses_a_row_fails_and_writes_nothing(ingested):
    url, lost, _, _ = ingested
    assert "1 unaccounted" in lost and f"{len(ROWS)} file rows" in lost
    status, error = _one(
        url,
        """SELECT status::text, error_summary FROM ops.pipeline_run WHERE kind = 'ingest' ORDER BY started_at
           LIMIT 1""",
    )
    assert status == "failed" and "ingest closure failed" in error
    # the transaction rolled back: no snapshot, ruling, source ref or exclusion from that run
    assert _one(
        url,
        """SELECT (SELECT count(*) FROM corpus.ruling r JOIN ops.pipeline_run p ON p.run_id = r.created_by_run_id
                   WHERE p.status = 'failed'),
                  (SELECT count(*) FROM corpus.ingest_exclusion x JOIN ops.pipeline_run p USING (run_id)
                   WHERE p.status = 'failed')""",
    ) == (0, 0)


def test_every_row_of_the_file_is_a_source_ref_or_an_exclusion(ingested):
    url, _, first, _ = ingested
    closure = _one(
        url,
        """SELECT row_count, loaded_refs, base_refs, twin_refs, exclusions, exclusions_by_row_index, unaccounted_rows,
                  closure_ok, exclusions_by_reason
           FROM corpus.v_ingest_closure WHERE source = 'hf_bger'""",
    )
    reasons: dict[str, int] = {}
    for reason in EXPECTED.values():
        reasons[reason] = reasons.get(reason, 0) + 1
    assert closure == (len(ROWS), len(LOADED), 4, 1, len(EXPECTED), 3, 0, True, reasons)
    assert sum(reasons.values()) == len(EXPECTED) == 15 and len(ROWS) == 20

    import psycopg

    with psycopg.connect(url) as conn:
        stored = conn.execute(
            """SELECT x.external_id, x.reason_code, x.docket_raw, x.decision_date::text, x.detail, cv.step::text,
                      x.run_id::text
               FROM corpus.ingest_exclusion x JOIN ops.component_version cv USING (component_version_id)"""
        ).fetchall()
        refs = {r[0] for r in conn.execute("SELECT external_id FROM corpus.ruling_source_ref").fetchall()}
    assert {e: r for e, r, *_ in stored} == EXPECTED and refs == LOADED
    assert {s[5] for s in stored} == {"ingest"} and {s[6] for s in stored} == {first["run_id"]}
    by_id = {s[0]: s for s in stored}
    assert by_id["bger_X_1"][2:4] == ("Ohne Nummer", "2026-04-03")
    assert by_id["bger_X_1-D20260403"][4]["base_reason"] == "ING_DOCKET_MALFORMED"
    assert by_id["bger_8C_4_2019-D20190501"][4] == {
        "base_id": "bger_8C_4_2019",
        "base_reason": "OUT_OF_WINDOW",
        "decision_date": "2019-05-01",
        "publication_date": None,
        "first_seen": "2019-05-10",
    }


def test_the_run_reports_the_closure_beside_the_existing_counters(ingested):
    url, _, first, _ = ingested
    assert (first["file_rows"], first["source_refs"], first["exclusions"], first["closure_ok"]) == (20, 5, 15, 1)
    assert (first["rows_read"], first["out_of_window"], first["rejected_malformed"], first["twins"]) == (13, 3, 1, 1)
    import psycopg

    with psycopg.connect(url) as conn:
        values = dict(
            conn.execute(
                "SELECT metric_code, value::int FROM ops.run_metric WHERE run_id = %s", (first["run_id"],)
            ).fetchall()
        )
        event = conn.execute(
            "SELECT attributes FROM ops.log_event WHERE run_id = %s AND event_code = 'ingest.exclusions.recorded'",
            (first["run_id"],),
        ).fetchone()[0]
    assert values["file_rows"] == 20 and values["closure_ok"] == 1 and values["out_of_window"] == 3
    assert {k: v for k, v in values.items() if k.startswith("excluded_")} == {
        "excluded_out_of_window": 5,
        "excluded_ing_twin_same_date": 5,
        "excluded_ing_decision_date_missing": 1,
        "excluded_ing_docket_malformed": 1,
        "excluded_ing_source_id_missing": 1,
        "excluded_ing_source_id_duplicate": 2,
    }
    assert event["closure_ok"] is True and event["file_rows"] == 20 and sum(event["by_reason"].values()) == 15


def test_loading_the_same_file_again_changes_nothing(ingested):
    url, _, first, again = ingested
    assert again["exclusions"] == first["exclusions"] and again["source_refs"] == first["source_refs"]
    assert _one(url, "SELECT count(*), count(DISTINCT run_id) FROM corpus.ingest_exclusion") == (15, 1)
    assert _one(url, "SELECT status::text FROM ops.pipeline_run WHERE run_id = %s", (again["run_id"],)) == (
        "succeeded",
    )


def test_every_run_records_its_code_and_acts_as_the_pipeline_group(ingested):
    from src.db.pg import PIPELINE_ROLE, connect
    from src.db.registry import code_sha256
    from src.ingest.hf_base import CODE_PATHS

    url, _, first, _ = ingested
    with connect(url, actor="test") as conn:
        assert conn.execute("SELECT current_user, session_user <> current_user").fetchone() == (PIPELINE_ROLE, True)
    params = _one(url, "SELECT params FROM ops.pipeline_run WHERE run_id = %s", (first["run_id"],))[0]
    assert params["code_paths"] == sorted(CODE_PATHS) and params["code_sha256"] == code_sha256(CODE_PATHS)
    roles = _one(
        url,
        "SELECT array_agg(DISTINCT db_role), count(*) FROM audit.change_log WHERE run_id = %s",
        (first["run_id"],),
    )
    assert roles[0] == [PIPELINE_ROLE] and roles[1] >= 2  # the run closing, the populations it froze


def test_the_pipeline_role_can_be_changed_or_disabled_but_never_silently_missing(db, monkeypatch, capsys):
    import psycopg

    from src.db.pg import DatabaseRoleError, connect

    monkeypatch.setenv("DB_PIPELINE_ROLE", "suva_no_such_role")
    with pytest.raises(DatabaseRoleError, match="cannot SET ROLE suva_no_such_role .*make db-deploy"):
        connect(db, actor="test")
    monkeypatch.setenv("DB_PIPELINE_ROLE", "suva_g_read")
    with connect(db, actor="test") as conn:  # a read-only group: the role is really taken
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                "INSERT INTO ops.reason_code (code, domain, label_de, label_fr) VALUES ('X_1', 'ingest', 'x', 'y')"
            )
    monkeypatch.setenv("DB_PIPELINE_ROLE", "")
    with connect(db, actor="test") as conn:
        assert conn.execute("SELECT current_user = session_user").fetchone() == (True,)
    assert "DB_PIPELINE_ROLE is empty" in capsys.readouterr().err


def test_the_registry_keeps_a_version_whose_code_changed_but_never_a_changed_approval(ingested, tmp_path, capsys):
    from src.db.pg import ROOT, connect
    from src.db.registry import RegistryConflict, load_profiles, load_step_registry
    from src.ingest.models import IngestConfig

    url = ingested[0]
    path = ROOT / "src" / "ingest" / "registry" / "ingest.json"
    stored = _one(url, "SELECT code_sha256 FROM ops.component_version WHERE step = 'ingest'")[0]
    with connect(url, actor="test") as conn:
        load_step_registry(conn, path, IngestConfig, None, ("src/ingest/hf_base.py", "src/ingest/gold.py"))
    assert "notice: ingest V1.0.0 was created by other code" in capsys.readouterr().err
    assert _one(url, "SELECT code_sha256 FROM ops.component_version WHERE step = 'ingest'")[0] == stored

    reg = json.loads(path.read_text(encoding="utf-8"))
    reg["versions"][0]["decision"] = "D-061"
    edited = tmp_path / "ingest.json"
    edited.write_text(json.dumps(reg), encoding="utf-8")
    with connect(url, actor="test") as conn, pytest.raises(RegistryConflict, match="an approval is immutable"):
        load_step_registry(conn, edited, IngestConfig, None, ("src/ingest/hf_base.py", "src/ingest/models.py"))

    profiles = json.loads((ROOT / "src" / "db" / "seed" / "profiles.json").read_text(encoding="utf-8"))
    profiles["profiles"][0]["versions"][0]["decision"] = "D-064"
    seed = tmp_path / "profiles.json"
    seed.write_text(json.dumps(profiles), encoding="utf-8")
    with connect(url, actor="test") as conn, pytest.raises(RegistryConflict, match="an approval is immutable"):
        load_profiles(conn, seed)
    assert _one(url, "SELECT count(DISTINCT decision_ref) FROM ops.pipeline_profile_version") == (1,)


def test_no_exclusion_names_a_ruling_text(ingested):
    url = ingested[0]
    assert _one(
        url, "SELECT count(*) FROM corpus.ingest_exclusion WHERE strpos(detail::text, 'Synthetischer') > 0"
    ) == (0,)
    assert Path(url).name  # the throwaway database is dropped by the fixture


@pytest.mark.parametrize("first", ["ingest_exclusion", "ruling_source_ref"])
def test_two_concurrent_transactions_cannot_both_load_and_exclude_a_source_row(ingested, first):
    """Exclusivity across sessions (F-04): A inserts the row into one table and keeps its transaction open, B inserts
    the same (snapshot, source, external_id) into the other. Without a lock neither sees the other's uncommitted row
    and both commit (red before the fix: (1, 1)); with it B waits for A's commit, then its check sees A's row and
    refuses. A separate snapshot (another file kind), so the module's hf_bger closure stays intact."""
    import threading
    import time

    import psycopg

    from src.db.pg import connect

    url, _, loaded, _ = ingested
    probe = f"race_probe_{first}"
    cv = _one(url, "SELECT component_version_id::text FROM ops.component_version WHERE step = 'ingest'")[0]
    ruling = _one(url, "SELECT ruling_id::text FROM corpus.ruling ORDER BY docket LIMIT 1")[0]
    with connect(url, actor="test") as conn:
        snap = conn.execute(
            """INSERT INTO ops.source_snapshot (source, revision, uri, file_sha256, retrieved_at)
               VALUES ('bger_neuheiten', %s, 'https://www.bger.ch/neuheiten', repeat('e', 64), now())
               RETURNING snapshot_id::text""",
            (probe,),
        ).fetchone()[0]
    insert = {
        "ingest_exclusion": (
            """INSERT INTO corpus.ingest_exclusion (snapshot_id, source, external_id, reason_code, component_version_id,
               run_id) VALUES (%s, 'aza_id', %s, 'OUT_OF_WINDOW', %s, %s)""",
            (snap, probe, cv, loaded["run_id"]),
        ),
        "ruling_source_ref": (
            """INSERT INTO corpus.ruling_source_ref (source, external_id, ruling_id, snapshot_id)
               VALUES ('aza_id', %s, %s, %s)""",
            (probe, ruling, snap),
        ),
    }
    second = next(t for t in insert if t != first)
    a, b = connect(url, actor="test-a"), connect(url, actor="test-b")
    outcome: dict[str, object] = {}

    def b_inserts() -> None:
        try:
            b.execute(*insert[second])
            b.commit()
            outcome["b"] = "committed"
        except psycopg.Error as exc:
            b.rollback()
            outcome["b"] = exc

    try:
        a.execute(*insert[first])  # A's transaction stays open
        worker = threading.Thread(target=b_inserts)
        worker.start()
        waits, deadline = None, time.monotonic() + 10
        while waits is None and worker.is_alive() and time.monotonic() < deadline:
            waits = _one(
                url,
                "SELECT wait_event FROM pg_stat_activity WHERE pid = %s AND wait_event_type = 'Lock'",
                (b.info.backend_pid,),
            )
            time.sleep(0.05)
        a.commit()
        worker.join(timeout=30)
        assert not worker.is_alive()
    finally:
        a.close()
        b.close()
    assert waits == ("advisory",), f"B did not wait for A's lock ({waits}); B: {outcome.get('b')}"
    assert isinstance(outcome["b"], psycopg.errors.RaiseException), outcome["b"]
    assert "it cannot also be" in str(outcome["b"])
    counts = _one(
        url,
        """SELECT (SELECT count(*) FROM corpus.ingest_exclusion WHERE external_id = %s),
                  (SELECT count(*) FROM corpus.ruling_source_ref WHERE external_id = %s)""",
        (probe, probe),
    )
    assert counts == ((1, 0) if first == "ingest_exclusion" else (0, 1))
    closure = "SELECT loaded_refs + exclusions FROM corpus.v_ingest_closure WHERE snapshot_id = %s"
    assert _one(url, closure, (snap,)) == (1,)  # the closure counts the source row once (2 before the fix)
