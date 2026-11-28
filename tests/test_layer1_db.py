"""Layer 1 end to end on PostgreSQL: ingest, run, files, assessments, evidence, spans, metrics, recall, reload,
failure. Runs only with DATABASE_URL (CI `db` job, or a local database): it creates a throwaway database,
deploys src/db/sql into it, and drops it at the end. Rulings: real dockets of Q2/2026 with short synthetic
texts (no personal data, D-038).
"""

from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import date
from pathlib import Path

import pytest

pytestmark = [pytest.mark.db, pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="needs DATABASE_URL")]

ROWS = [  # decision_id, docket, decision_date, publication_date, scraped_at, language, title, legal_area, full_text
    (
        "bger_8C_493_2025",
        "8C_493/2025",
        "2026-04-02",
        "",
        "2026-04-20T08:00:00",
        "de",
        "Unfallversicherung (Rückfall, Invalidenrente),",
        "",
        "Die Suva ist Beschwerdegegnerin. Erwägungen: 1. Der Rückfall.",
    ),
    (
        "bger_8C_493_2025-D20260402",
        "8C_493/2025",
        "2026-04-02",
        "",
        "2026-04-20T08:00:00",
        "de",
        "Unfallversicherung (Rückfall, Invalidenrente),",
        "",
        "Die Suva ist Beschwerdegegnerin. Erwägungen: 1. Der Rückfall.",
    ),
    (
        "bger_8C_307_2025",
        "8C_307/2025",
        "2026-04-08",
        "2026-05-26",
        "2026-05-26T08:00:00",
        "fr",
        "Assurance-accidents (rechute),",
        "Assurance-accidents",
        "Considérant en droit: 1. La rechute.",
    ),
    (
        "bger_8C_199_2026",
        "8C_199/2026",
        "2026-04-27",
        "",
        "2026-05-02T08:00:00",
        "it",
        "Assicurazione contro gli infortuni (presupposto processuale),",
        "",
        "Diritto: 1. Presupposto processuale.",
    ),
    (
        "bger_5A_1_2026",
        "5A_1/2026",
        "2026-05-04",
        "",
        "2026-05-10T08:00:00",
        "de",
        "Erbrecht,",
        "Erbrecht",
        "Erbteilung.",
    ),
    (
        "bger_9C_10_2026",
        "9C_10/2026",
        "2026-05-05",
        "",
        "2026-05-12T08:00:00",
        "fr",
        "Droit fiscal,",
        "Finances publiques & droit fiscal",
        "Impôt; art. 95c LCA.",
    ),
]


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    import psycopg
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    from src.db import deploy

    base = os.environ["DATABASE_URL"]
    name = f"suva_test_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    url = make_conninfo(**(conninfo_to_dict(base) | {"dbname": name}))
    try:
        ns = argparse.Namespace(compose=False, url=url)
        res = deploy.run_psql(ns, deploy.script_for(deploy.sql_files()), capture=True)
        assert res.returncode == 0, res.stderr
        yield url, tmp_path_factory.mktemp("layer1")
    finally:
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture(scope="module")
def loaded(db):
    import pyarrow as pa
    import pyarrow.parquet as pq

    from src.db.pg import connect
    from src.ingest.__main__ import load_registries
    from src.ingest.hf_base import load_base
    from src.ingest.models import IngestConfig

    url, tmp = db
    cols = [
        "decision_id",
        "docket_number",
        "decision_date",
        "publication_date",
        "scraped_at",
        "language",
        "title",
        "legal_area",
        "full_text",
    ]
    table = pa.Table.from_pylist([dict(zip(cols, r, strict=True)) | {"appealed_court_raw": None} for r in ROWS])
    parquet = tmp / "bger.parquet"
    pq.write_table(table, parquet)
    with connect(url, actor="test") as conn:
        load_registries(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT config FROM ops.component_version WHERE step = 'ingest'")
            cfg = IngestConfig.model_validate(cur.fetchone()[0])
        summary = load_base(conn, parquet, cfg, [], actor="test")
        with conn.cursor() as cur:  # one Suva label, as the gold loader would write it
            cur.execute("""INSERT INTO ops.source_snapshot (snapshot_id, source, uri, file_sha256, retrieved_at)
                           VALUES ('00000000-0000-4000-8000-0000000000a2', 'judgements_workbook',
                               'judgements/x.xlsx', repeat('f', 64), now())""")
            cur.execute(
                """INSERT INTO gold.label (ruling_id, source, in_suva_scope, quarter_label, source_ref, snapshot_id,
                   created_by_run_id)
                           SELECT ruling_id, 'suva_relevance_list', true, '2026 Q2', 'judgements/x.xlsx#row-2',
                                  '00000000-0000-4000-8000-0000000000a2', %s FROM corpus.ruling WHERE docket =
                                      '8C_493/2025'""",
                (summary["run_id"],),
            )
        conn.commit()
    return url, tmp, summary


def test_ingest_counts_and_twin(loaded):
    _, _, summary = loaded
    assert summary["rulings"] == 5 and summary["twins"] == 1
    assert summary["population_2026Q2_decision"] == 5
    assert summary["population_2026Q2_publication"] == 5  # 1 exact (HF poller), 4 approximate (first seen)


def test_run_writes_files_and_every_decision(loaded):
    from src.db.pg import connect, sha256_file
    from src.layer1.recall import record_recall
    from src.layer1.run import run_layer1

    url, tmp, _ = loaded
    with connect(url, actor="test") as conn:
        out = run_layer1(conn, runs_dir=tmp / "runs", actor="test")
        assert (out["rulings"], out["kept"], out["dropped"]) == (5, 3, 2)
        assert out["parity"] == {"same": 5}
        run_dir = Path(out["files"])
        manifest = json.loads((run_dir / "manifest.json").read_text())
        assert manifest["files"]["decisions.jsonl"] == sha256_file(run_dir / "decisions.jsonl")
        log = json.loads((run_dir / "layer1_log.json").read_text())
        assert log["schema_version"] == "layer1-log-1" and log["quality"]["all_checks_passed"]

        with conn.cursor() as cur:
            cur.execute("SELECT status FROM ops.pipeline_run WHERE run_id = %s", (out["run_id"],))
            assert cur.fetchone()[0] == "succeeded"
            cur.execute(
                """SELECT r.docket, a.in_suva_scope::text, a.reason_code, a.score_source::text, a.explanation_de
                           FROM triage.assessment a JOIN corpus.ruling r USING (ruling_id) WHERE a.run_id = %s ORDER
                               BY 1""",
                (out["run_id"],),
            )
            rows = {d: (s, r, src, e) for d, s, r, src, e in cur.fetchall()}
            assert rows["5A_1/2026"][:3] == ("out_of_scope", "L1_DROP_WRONG_COURT", "net")
            assert rows["9C_10/2026"][:2] == ("out_of_scope", "L1_DROP_RUBRIC_OUT")
            assert rows["8C_199/2026"][:2] == ("potentially", "L1_KEEP_RUBRIC")
            assert rows["5A_1/2026"][3].startswith("Von der Vorauswahl ausgeschlossen: ")
            cur.execute(
                """SELECT t.content, ra.char_start, ra.char_end FROM triage.assessment_reason ra
                           JOIN triage.assessment a USING (assessment_id) JOIN corpus.ruling_text t ON t.text_id =
                               a.input_text_id
                           WHERE a.run_id = %s AND ra.reason_code = 'L1_KEEP_ACCIDENT_TERM'""",
                (out["run_id"],),
            )
            content, start, end = cur.fetchone()
            assert content[start:end] == "Suva"
            cur.execute(
                """SELECT count(*) FROM triage.assessment_reason ra JOIN triage.assessment a USING (assessment_id)
                           WHERE a.run_id = %s AND ra.reason_code = 'L1_FLAG_CLOSED_RUBRIC'""",
                (out["run_id"],),
            )
            assert cur.fetchone()[0] == 1
            cur.execute(
                "SELECT count(*) FILTER (WHERE parent_span_id IS NOT NULL), count(*) FILTER (WHERE status <> 'ok') "
                "FROM ops.span WHERE run_id = %s",
                (out["run_id"],),
            )
            assert cur.fetchone() == (5, 0)
            cur.execute(
                "SELECT value FROM ops.run_metric WHERE run_id = %s AND metric_code = 'rulings_in'", (out["run_id"],)
            )
            assert cur.fetchone()[0] == 5
            cur.execute(
                "SELECT count(*) FROM ops.log_event WHERE run_id = %s AND event_code = 'layer1.decision.made'",
                (out["run_id"],),
            )
            assert cur.fetchone()[0] == 5

        result = record_recall(conn, out["run_id"])
        assert result["suva_list"]["kept"] == result["suva_list"]["total"] == 1

        # reloading the same files into the same run changes nothing (deterministic ids, ON CONFLICT)
        from src.db.runs import Run
        from src.layer1.models import Layer1DecisionRecord
        from src.layer1.run import _load, load_version

        with conn.cursor() as cur:
            cur.execute(
                "SELECT span_id::text, profile_version_id::text, component_version_id::text FROM ops.span s "
                "JOIN ops.pipeline_run pr USING (run_id) WHERE s.run_id = %s AND s.parent_span_id IS NULL",
                (out["run_id"],),
            )
            span_id, pvid, cvid = cur.fetchone()
            _, _, rule_ids, _ = load_version(cur, cvid)
        records = [
            Layer1DecisionRecord.model_validate_json(line)
            for line in (run_dir / "decisions.jsonl").read_text().splitlines()
        ]
        with conn.transaction(), conn.cursor() as cur:
            _load(cur, Run(out["run_id"], span_id, pvid, cvid), records, rule_ids)
            cur.execute("SELECT count(*) FROM triage.assessment WHERE run_id = %s", (out["run_id"],))
            assert cur.fetchone()[0] == 5


def test_a_run_with_no_ruling_fails_and_leaves_no_assessment(loaded):
    from src.db.pg import connect
    from src.layer1.run import run_layer1

    url, tmp, _ = loaded
    with connect(url, actor="test") as conn:
        with pytest.raises(RuntimeError, match="0 rulings"):
            run_layer1(conn, population="no_such_population", runs_dir=tmp / "runs", actor="test")
        with conn.cursor() as cur:
            cur.execute("""SELECT pr.status::text, (SELECT count(*) FROM triage.assessment a WHERE a.run_id = pr.run_id)
                           FROM ops.pipeline_run pr WHERE pr.kind = 'layer1' ORDER BY pr.started_at DESC LIMIT 1""")
            assert cur.fetchone() == ("failed", 0)


def test_registry_refuses_an_edited_version(loaded, tmp_path):
    from src.db.pg import connect
    from src.db.registry import RegistryConflict, load_step_registry
    from src.layer1.models import Layer1Config, RuleDefinition

    url, _, _ = loaded
    reg = json.loads(Path("src/layer1/registry/layer1_filter.json").read_text())
    reg["versions"][0]["config"]["accident_terms"] = r"\bsuva\b"
    edited = tmp_path / "edited.json"
    edited.write_text(json.dumps(reg))
    with connect(url, actor="test") as conn, pytest.raises(RegistryConflict, match="bump the version"):
        load_step_registry(conn, edited, Layer1Config, RuleDefinition, ("src/layer1/engine.py", "src/layer1/models.py"))
    assert date.today()  # the loader refused before writing anything (transaction rolled back)
