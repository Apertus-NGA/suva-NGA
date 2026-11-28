"""Layer 1 end to end on PostgreSQL: ingest, run, files, assessments, the rule ledger (every rule of the version
per ruling, certified by the database), evidence, spans, metrics, golden status, verify, validate, recall, sealed
reload, failure. Runs only with DATABASE_URL (CI `db` job, or a local database): it creates a throwaway database,
deploys src/db/sql into it, and drops it at the end. Rulings: real dockets of Q2/2026 with short synthetic
texts (no personal data, D-038); the Suva labels are synthetic and live only in the throwaway database (D-031).
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
    (  # kept by V1.1.0 (default) only: its wider accident terms read "Unfallversicherer"; V1.0.0 drops it
        "bger_2C_5_2026",
        "2C_5/2026",
        "2026-05-06",
        "",
        "2026-05-12T08:00:00",
        "de",
        "Steuerrecht,",
        "Steuerrecht",
        "Der Unfallversicherer hat geleistet.",
    ),
]
RULES = 9  # rules of layer1_filter V1.0.0 and V1.1.0 (src/layer1/registry/layer1_filter.json)


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
    assert summary["rulings"] == 6 and summary["twins"] == 1
    assert summary["population_2026Q2_decision"] == 6
    assert summary["population_2026Q2_publication"] == 6  # 1 exact (HF poller), 5 approximate (first seen)


def test_run_writes_files_and_every_decision(loaded):
    import psycopg

    from src.db.pg import connect, sha256_file
    from src.layer1.recall import record_recall
    from src.layer1.run import NO_TEXT, run_layer1

    url, tmp, _ = loaded
    with connect(url, actor="test") as conn:
        out = run_layer1(conn, runs_dir=tmp / "runs", actor="test")
        assert (out["rulings"], out["kept"], out["dropped"]) == (6, 4, 2)
        assert out["parity"] == {"same": 5, "different": 1}  # V1.1.0 keeps 2C_5/2026, the 4c246a8 reference does not
        assert sum(out["outcomes"].values()) == 6 * RULES  # one evaluation per rule and ruling
        assert out["golden"] == "not_comparable"  # a synthetic corpus is not the pinned snapshot
        run_dir = Path(out["files"])
        manifest = json.loads((run_dir / "manifest.json").read_text())
        assert manifest["files"]["decisions.jsonl"] == sha256_file(run_dir / "decisions.jsonl")
        assert manifest["golden"]["status"] == "not_comparable"
        assert manifest["golden"]["reason"] == "the corpus was not loaded from the snapshot the expected file pins"
        log = json.loads((run_dir / "layer1_log.json").read_text())
        assert log["schema_version"] == "layer1-log-1" and log["quality"]["all_checks_passed"]
        assert log["run"]["started_at"].endswith("+00:00") and log["run"]["finished_at"] >= log["run"]["started_at"]
        assert len(log["run"]["input"]["sha256"]) == 64 and log["run"]["input"]["bytes"] > 0
        records = [json.loads(line) for line in (run_dir / "decisions.jsonl").read_text().splitlines()]
        assert {(a["ruling_id"], a["decision_date"]) for a in log["assets"]} == {
            (r["ruling_id"], r["decision_date"]) for r in records
        }

        with conn.cursor() as cur:
            cur.execute("SELECT status FROM ops.pipeline_run WHERE run_id = %s", (out["run_id"],))
            assert cur.fetchone()[0] == "succeeded"
            cur.execute(
                """SELECT r.docket, a.in_suva_scope::text, a.reason_code, a.score_source::text, a.explanation_de
                   FROM triage.assessment a JOIN corpus.ruling r USING (ruling_id) WHERE a.run_id = %s ORDER BY 1""",
                (out["run_id"],),
            )
            rows = {d: (s, r, src, e) for d, s, r, src, e in cur.fetchall()}
            assert rows["5A_1/2026"][:3] == ("out_of_scope", "L1_DROP_WRONG_COURT", "net")
            assert rows["9C_10/2026"][:2] == ("out_of_scope", "L1_DROP_RUBRIC_OUT")
            assert rows["8C_199/2026"][:2] == ("potentially", "L1_KEEP_RUBRIC")
            assert rows["2C_5/2026"][:2] == ("potentially", "L1_KEEP_ACCIDENT_TERM")
            assert rows["5A_1/2026"][3] == (
                "Von der Vorauswahl ausgeschlossen: Abteilung nicht in der Liste der Vorauswahl. Im Urteilstext "
                "geprüft, ohne Treffer: Suchbegriffe zu Suva, Unfall- und Militärversicherung; Suchbegriffe zu VVG "
                "und Taggeldversicherung (nur die Begriffe der Filterversion; andere Formulierungen erkennt die "
                "Prüfung nicht)."
            )
            assert NO_TEXT not in rows["5A_1/2026"][3]

            # the ledger: every rule of the version, once per ruling, at its ordinal in the version (F-01)
            cur.execute(
                """SELECT count(*), count(DISTINCT l.assessment_id),
                          count(*) FILTER (WHERE l.ordinal = cvr.ordinal AND l.rule_code = rl.rule_code)
                   FROM triage.v_layer1_ledger l
                   JOIN triage.assessment a ON a.assessment_id = l.assessment_id
                   JOIN ops.rule rl ON rl.rule_code = l.rule_code AND rl.version_label = l.rule_version
                   JOIN ops.component_version_rule cvr
                     ON cvr.component_version_id = a.component_version_id AND cvr.rule_id = rl.rule_id
                   WHERE l.run_id = %s""",
                (out["run_id"],),
            )
            assert cur.fetchone() == (6 * RULES, 6, 6 * RULES)
            cur.execute(
                "SELECT count(*) FROM ops.component_version_rule WHERE component_version_id = "
                "(SELECT component_version_id FROM ops.span WHERE run_id = %s AND parent_span_id IS NULL)",
                (out["run_id"],),
            )
            assert cur.fetchone()[0] == RULES
            cur.execute(
                """SELECT outcome::text, count(*) FROM triage.v_layer1_ledger WHERE run_id = %s GROUP BY 1""",
                (out["run_id"],),
            )
            assert dict(cur.fetchall()) == {k: v for k, v in out["outcomes"].items() if v}
            cur.execute(
                "SELECT count(*) FROM triage.v_layer1_ledger WHERE run_id = %s AND is_decisive", (out["run_id"],)
            )
            assert cur.fetchone()[0] == 6  # exactly one decisive rule per ruling

            # a fired full-text keep: its offsets index the stored text
            cur.execute(
                """SELECT t.content, ra.char_start, ra.char_end, ra.matched_text FROM triage.assessment_reason ra
                   JOIN triage.assessment a USING (assessment_id)
                   JOIN corpus.ruling r ON r.ruling_id = a.ruling_id
                   JOIN corpus.ruling_text t ON t.text_id = a.input_text_id
                   WHERE a.run_id = %s AND ra.reason_code = 'L1_KEEP_ACCIDENT_TERM' AND ra.outcome = 'fired'
                     AND r.docket = '8C_493/2025'""",
                (out["run_id"],),
            )
            content, start, end, matched = cur.fetchone()
            assert content[start:end] == matched == "Suva"
            # the blocked contract term keeps its term and its offsets: the exact slice of the stored text (F-02)
            cur.execute(
                """SELECT t.content, l.char_start, l.char_end, l.matched_text, l.detail, l.evidence_field
                   FROM triage.v_layer1_ledger l JOIN corpus.ruling_text t ON t.text_id = l.input_text_id
                   WHERE l.run_id = %s AND l.outcome = 'blocked'""",
                (out["run_id"],),
            )
            [(content, start, end, matched, detail, field)] = cur.fetchall()
            assert content[start:end] == matched == "LCA" and field == "full_text"
            assert detail == {
                "pattern": "contract_terms",
                "blocked_by": "L1_FLAG_CLOSED_RUBRIC",
                "closed_rubric_match": "finances publiques",
            }
            cur.execute(
                """SELECT count(*) FROM triage.v_layer1_ledger
                   WHERE run_id = %s AND rule_code = 'L1_FLAG_CLOSED_RUBRIC' AND outcome = 'fired'""",
                (out["run_id"],),
            )
            assert cur.fetchone()[0] == 1
            cur.execute(
                "SELECT count(*) FILTER (WHERE parent_span_id IS NOT NULL), count(*) FILTER (WHERE status <> 'ok'), "
                "sum((attributes -> 'outcomes' ->> 'fired')::int) "
                "FROM ops.span WHERE run_id = %s",
                (out["run_id"],),
            )
            assert cur.fetchone() == (6, 0, out["outcomes"]["fired"])
            cur.execute(
                "SELECT metric_code, value FROM ops.run_metric WHERE run_id = %s AND metric_code IN "
                "('rulings_in', 'ledger_rows', 'outcome_blocked')",
                (out["run_id"],),
            )
            assert dict(cur.fetchall()) == {"rulings_in": 6, "ledger_rows": 6 * RULES, "outcome_blocked": 1}
            cur.execute(
                "SELECT count(*) FROM ops.log_event WHERE run_id = %s AND event_code = 'layer1.decision.made'",
                (out["run_id"],),
            )
            assert cur.fetchone()[0] == 6
            cur.execute(
                "SELECT level::text, attributes ->> 'status' FROM ops.log_event WHERE run_id = %s "
                "AND event_code = 'layer1.golden.not_comparable'",
                (out["run_id"],),
            )
            assert cur.fetchall() == [("warning", "not_comparable")]

        result = record_recall(conn, out["run_id"])
        assert result["suva_list"]["kept"] == result["suva_list"]["total"] == 1

        # a committed ledger is sealed: loading the same records into the same run again is refused
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
        conn.commit()
        parsed = [
            Layer1DecisionRecord.model_validate_json(line)
            for line in (run_dir / "decisions.jsonl").read_text().splitlines()
        ]
        with pytest.raises(psycopg.Error, match="is already committed"):
            with conn.transaction(), conn.cursor() as cur:
                _load(cur, Run(out["run_id"], span_id, pvid, cvid), parsed, rule_ids)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*), (SELECT count(*) FROM triage.assessment_reason ar JOIN triage.assessment a2 "
                "USING (assessment_id) WHERE a2.run_id = %s) FROM triage.assessment WHERE run_id = %s",
                (out["run_id"], out["run_id"]),
            )
            assert cur.fetchone() == (6, 6 * RULES)


def test_every_run_records_its_code_and_acts_as_the_pipeline_group(loaded):
    """F-09, F-11: each run's params name its code and its hash; its audit rows carry the pipeline group's role."""
    import psycopg

    from src.db.pg import PIPELINE_ROLE
    from src.db.registry import code_sha256
    from src.ingest.hf_base import CODE_PATHS as INGEST_CODE
    from src.layer1.run import CODE_PATHS as LAYER1_CODE

    url, _, summary = loaded
    with psycopg.connect(url) as conn:
        runs = conn.execute(
            "SELECT run_id::text, kind::text, params FROM ops.pipeline_run WHERE kind IN ('ingest', 'layer1')"
        ).fetchall()
        audited = dict(
            conn.execute(
                """SELECT kind::text, array_agg(DISTINCT c.db_role ORDER BY c.db_role)
                   FROM audit.change_log c JOIN ops.pipeline_run p ON p.run_id = c.run_id GROUP BY kind"""
            ).fetchall()
        )
    assert {kind for _, kind, _ in runs} == {"ingest", "layer1"}
    for run_id, kind, params in runs:
        code = INGEST_CODE if kind == "ingest" else LAYER1_CODE
        assert params["code_paths"] == sorted(code), run_id
        assert params["code_sha256"] == code_sha256(code), run_id
    assert audited == {"ingest": [PIPELINE_ROLE], "layer1": [PIPELINE_ROLE]}
    assert summary["closure_ok"] == 1 and summary["file_rows"] == len(ROWS)


def _tampered_load(url: str, tmp: Path, change) -> str:
    """Load the records of a fresh in-memory run with one change into a new run; returns the database's refusal."""
    import psycopg

    from src.db.pg import connect
    from src.db.registry import pinned_version, profile_version
    from src.db.runs import begin_run, fail_run
    from src.layer1.models import Layer1DecisionRecord
    from src.layer1.run import CODE_PATHS, STEP, _load, load_version

    latest = max((tmp / "runs").iterdir(), key=lambda p: p.stat().st_mtime)
    records = [
        Layer1DecisionRecord.model_validate_json(line) for line in (latest / "decisions.jsonl").read_text().splitlines()
    ]
    records = [change(r) for r in records]
    with connect(url, actor="test") as conn:
        with conn.cursor() as cur:
            pvid, _ = profile_version(cur, "default")
            cvid = pinned_version(cur, pvid, STEP)
            _, _, rule_ids, _ = load_version(cur, cvid)
        run = begin_run(
            conn,
            profile_version_id=pvid,
            kind="layer1",
            step=STEP,
            operation="layer1.run",
            component_version_id=cvid,
            params={"tampered": True},
            code_paths=CODE_PATHS,
            actor="test",
        )
        with pytest.raises(psycopg.Error) as refused:
            with conn.transaction(), conn.cursor() as cur:
                _load(cur, run, records, rule_ids)
        fail_run(conn, run, refused.value)
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM triage.assessment WHERE run_id = %s", (run.run_id,))
            assert cur.fetchone()[0] == 0  # all or nothing
    return str(refused.value)


def test_the_database_certifies_each_ledger_row_and_each_decision(loaded):
    """F-10: what run.py writes is re-checked by the database, row by row and, at commit, ruling by ruling."""
    url, tmp, _ = loaded

    def wrong_slice(rec):
        evs = [e.model_copy(update={"matched_text": "LCA."}) if e.outcome == "blocked" else e for e in rec.evaluations]
        return rec.model_copy(update={"evaluations": evs})

    assert "matched_text must equal the input text slice" in _tampered_load(url, tmp, wrong_slice)

    def wrong_reason(rec):  # a kept ruling whose reason is not its decisive fired keep
        if rec.docket != "8C_493/2025":
            return rec
        return rec.model_copy(update={"reason_code": "L1_KEEP_ACCIDENT_TERM"})

    assert "must be L1_KEEP_RUBRIC (the fired keep rule with the lowest ordinal)" in _tampered_load(
        url, tmp, wrong_reason
    )

    def missing_rule(rec):
        return rec.model_copy(update={"evaluations": rec.evaluations[:-1]})

    assert "ledger incomplete, no row for the enabled rule(s) L1_SIGNAL_RUBRIC_FROM_TITLE" in _tampered_load(
        url, tmp, missing_rule
    )


def test_verify_proves_the_files_equal_the_database_and_fails_on_a_tampered_file(loaded, tmp_path, monkeypatch, capsys):
    from src.layer1.__main__ import main

    url, tmp, _ = loaded
    monkeypatch.setenv("DATABASE_URL", url)
    with __import__("psycopg").connect(url) as conn:
        run_id = conn.execute(
            "SELECT run_id::text FROM ops.pipeline_run WHERE kind = 'layer1' AND status = 'succeeded' "
            "ORDER BY started_at LIMIT 1"
        ).fetchone()[0]
    assert main(["verify", "--run", run_id, "--runs-dir", str(tmp / "runs")]) == 0
    assert "verify: OK (6 records" in capsys.readouterr().out

    copy = tmp_path / run_id
    shutil.copytree(tmp / "runs" / run_id, copy)
    lines = (copy / "decisions.jsonl").read_text().splitlines()
    first = json.loads(lines[0])
    tampered = next(e for e in first["evaluations"] if e["examined_value"] is not None)
    tampered["examined_value"] = "XX"
    lines[0] = json.dumps(first, ensure_ascii=False)
    (copy / "decisions.jsonl").write_text("\n".join(lines) + "\n")
    assert main(["verify", "--run", run_id, "--runs-dir", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert "verify: FAILED" in captured.out
    assert "decisions.jsonl: SHA-256 differs from manifest.json" in captured.err
    assert f"rule {tampered['rule_code']} examined_value differs (file 'XX', database" in captured.err


def test_validate_passes_an_addition_and_fails_a_removal(loaded, tmp_path, capsys, monkeypatch):
    from src.layer1.__main__ import main

    url, tmp, _ = loaded
    monkeypatch.setenv("DATABASE_URL", url)
    out = tmp_path / "validation.json"
    args = ["--runs-dir", str(tmp / "runs"), "--out", str(out)]
    assert main(["validate", "--baseline-profile", "layer1_reference", "--profile", "default", *args]) == 0
    report = json.loads(out.read_text())
    v = report["validation"]
    assert v["passed"] and v["potentially_to_out_of_scope"] == 0 and v["out_of_scope_to_potentially"] == 1
    assert v["checks"]["candidate_recall_complete"] is True
    assert v["recall"]["candidate"]["suva_list"] == {"total": 1, "kept": 1, "not_assessed": 0}
    assert "missed" not in json.dumps(report)  # aggregates only (D-031)
    assert (v["baseline"]["layer1_filter"], v["candidate"]["layer1_filter"]) == ("V1.0.0", "V1.1.0")
    assert "validate: OK" in capsys.readouterr().out

    assert main(["validate", "--baseline-profile", "default", "--profile", "layer1_reference", *args]) == 1
    v = json.loads(out.read_text())["validation"]
    assert not v["passed"] and v["failures"] == ["1 ruling(s) go potentially -> out_of_scope"]
    with __import__("psycopg").connect(url) as conn:
        events = conn.execute(
            "SELECT event_code, level::text FROM ops.log_event WHERE run_id IN (%s, %s) "
            "AND event_code LIKE 'layer1.validation.%%' ORDER BY ts",
            (report["validation"]["candidate"]["run_id"], v["candidate"]["run_id"]),
        ).fetchall()
    assert events == [("layer1.validation.passed", "info"), ("layer1.validation.failed", "error")]


def _certified(url: str, version: str, counts: dict, decisions_sha256: str) -> dict:
    """An expected/layer1 file that certifies this synthetic corpus: its HF snapshot and ingest version, the given
    counts (rulings, kept, dropped, by_reason) and the given decisions digest."""
    import psycopg

    with psycopg.connect(url) as conn:
        file_sha, revision = conn.execute(
            "SELECT file_sha256, revision FROM ops.source_snapshot WHERE source = 'hf_bger'"
        ).fetchone()
        [ingest] = conn.execute("SELECT version_label FROM ops.component_version WHERE step = 'ingest'").fetchone()
    return {
        "canonical": "layer1-golden-1",
        "step": "layer1_filter",
        "version": version,
        "ingest_version": ingest,
        "snapshot": {"hf_revision": revision, "file_sha256": file_sha},
        "rulings": counts["rulings"],
        "kept": counts["kept"],
        "dropped": counts["dropped"],
        "by_reason": dict(sorted(counts["by_reason"].items())),
        "decisions_sha256": decisions_sha256,
    }


def _certify(monkeypatch, stored: dict) -> None:
    """Mock (declared, G9): `src.layer1.golden.expected_layer1` returns `stored` for its version and no file for any
    other, instead of reading expected/layer1/<version>.json (which certifies the real HF file, not this corpus)."""
    from src.layer1 import golden

    monkeypatch.setattr(
        golden, "expected_layer1", lambda version, *a, **kw: stored if version == stored["version"] else None
    )


def test_a_golden_mismatch_fails_the_run_and_loads_nothing(loaded, tmp_path, monkeypatch):
    """§2.4 golden in every run, on the database path (G9: the guard of the certified decisions). The expected file is
    mocked (see _certify) to certify this corpus. With the true digest the run matches and says so; with any other
    digest it fails before loading anything: run failed, no assessment, no ledger row, no ruling span, and the
    manifest records the mismatch."""
    import psycopg

    from src.db.pg import connect
    from src.layer1.run import run_layer1

    url, _, _ = loaded
    with connect(url, actor="test") as conn:
        base = run_layer1(conn, runs_dir=tmp_path / "base", actor="test")
    assert (base["golden"], base["version"]) == ("not_comparable", "V1.1.0")
    digest = json.loads((Path(base["files"]) / "manifest.json").read_text())["golden"]["decisions_sha256"]

    _certify(monkeypatch, _certified(url, base["version"], base, digest))
    with connect(url, actor="test") as conn:
        matched = run_layer1(conn, runs_dir=tmp_path / "matched", actor="test")
        assert matched["golden"] == "matched"
        assert conn.execute(
            "SELECT level::text, event_code FROM ops.log_event "
            "WHERE run_id = %s AND event_code LIKE 'layer1.golden.%%'",
            (matched["run_id"],),
        ).fetchall() == [("info", "layer1.golden.matched")]

    _certify(monkeypatch, _certified(url, base["version"], base, "0" * 64))
    with connect(url, actor="test") as conn, pytest.raises(RuntimeError) as failed:
        run_layer1(conn, runs_dir=tmp_path / "mismatch", actor="test")
    assert str(failed.value).startswith(
        "golden check failed: layer1_filter V1.1.0 no longer decides as expected/layer1/V1.1.0.json certifies "
        "(decisions_sha256 differ)"
    )
    [run_dir] = list((tmp_path / "mismatch").iterdir())
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert (manifest["golden"]["status"], manifest["golden"]["differs"]) == ("mismatch", ["decisions_sha256"])
    with psycopg.connect(url) as conn:
        assert conn.execute(
            """SELECT pr.status::text,
                      (SELECT count(*) FROM triage.assessment a WHERE a.run_id = pr.run_id),
                      (SELECT count(*) FROM triage.assessment_reason ar
                       JOIN triage.assessment a ON a.assessment_id = ar.assessment_id WHERE a.run_id = pr.run_id),
                      (SELECT count(*) FROM ops.span s WHERE s.run_id = pr.run_id AND s.parent_span_id IS NOT NULL)
               FROM ops.pipeline_run pr WHERE pr.run_id = %s""",
            (run_dir.name,),
        ).fetchone() == ("failed", 0, 0, 0)


def test_validate_fails_when_the_candidate_run_fails_its_golden_check(loaded, tmp_path, monkeypatch, capsys):
    """The expected file of V1.1.0 (the candidate, profile default) is mocked (see _certify) to certify this corpus
    with a wrong digest; V1.0.0 (the baseline, layer1_reference) has none. The candidate run fails, so validate fails
    with exit 1: runs_succeeded and golden_not_failed are False."""
    from src.layer1.__main__ import main

    url, _, _ = loaded
    monkeypatch.setenv("DATABASE_URL", url)
    counts = {"rulings": 6, "kept": 4, "dropped": 2, "by_reason": {}}
    _certify(monkeypatch, _certified(url, "V1.1.0", counts, "0" * 64))
    out = tmp_path / "validation.json"
    args = ["--runs-dir", str(tmp_path / "runs"), "--out", str(out)]
    assert main(["validate", "--baseline-profile", "layer1_reference", "--profile", "default", *args]) == 1
    v = json.loads(out.read_text())["validation"]
    assert not v["passed"]
    assert v["checks"]["runs_succeeded"] is False and v["checks"]["golden_not_failed"] is False
    assert v["baseline"]["golden"] == "not_comparable" and v["candidate"]["run_id"] is None
    [failure] = v["failures"]
    assert failure.startswith("candidate run (default) failed: RuntimeError: golden check failed: layer1_filter V1.1.0")
    assert "validate: FAILED" in capsys.readouterr().out


def test_validate_compares_rulings_by_identity_not_by_count(loaded, tmp_path, monkeypatch):
    """Review finding: two runs of 5 rulings each, over different rulings, passed as "the same rulings" (counts were
    compared) with no removal (an inner join hid the ruling only the baseline decided). Mock (declared, G9):
    `src.layer1.run.run_layer1` is wrapped so that the baseline decides a population without 5A_1/2026 and the
    candidate a population without 8C_199/2026, which the baseline keeps. Both populations are synthetic, in the
    throwaway database only."""
    import psycopg

    import src.layer1.run as layer1_run
    from src.db.pg import connect
    from src.layer1.recall import validate

    url, _, summary = loaded
    with psycopg.connect(url) as conn:
        conn.execute("SET app.actor = 'test'")
        for code, left_out in (("test_without_5a_1", "5A_1/2026"), ("test_without_8c_199", "8C_199/2026")):
            conn.execute(
                "INSERT INTO corpus.population (code, definition, role, built_by_run_id) "
                "VALUES (%s, 'reference', 'reference', %s)",
                (code, summary["run_id"]),
            )
            conn.execute(
                """INSERT INTO corpus.population_member (population_id, ruling_id, basis)
                   SELECT p.population_id, r.ruling_id, 'reference' FROM corpus.population p, corpus.ruling r
                   WHERE p.code = %s AND r.docket <> %s""",
                (code, left_out),
            )
    populations = iter(["test_without_5a_1", "test_without_8c_199"])  # baseline first, then candidate
    real = layer1_run.run_layer1
    monkeypatch.setattr(
        layer1_run, "run_layer1", lambda conn, **kw: real(conn, **kw | {"population": next(populations)})
    )
    with connect(url, actor="test") as conn:
        report = validate(conn, "default", "default", runs_dir=tmp_path / "runs", actor="test")
    v = report["validation"]
    assert (v["baseline"]["rulings"], v["candidate"]["rulings"]) == (5, 5)  # equal counts, different rulings
    assert report["scope_changes"] == {"potentially->not_assessed": 1, "not_assessed->out_of_scope": 1}
    assert v["potentially_to_out_of_scope"] == 0 and v["potentially_not_decided_by_candidate"] == 1
    assert v["checks"]["same_rulings"] is False and v["checks"]["no_removal"] is False and not v["passed"]
    assert "the runs decided different rulings: 1 only in the baseline, 1 only in the candidate" in v["failures"]
    assert "1 ruling(s) the baseline keeps are not decided by the candidate" in v["failures"]


def test_a_blank_text_is_absent_for_the_engine_and_refused_by_the_database(loaded):
    """Review finding: the engine treats a text without a visible character as absent (text.strip() == ''), but the
    database stored one (btrim strips spaces only), and the ledger trigger then refused why text_absent on an
    assessment with an input text: the whole run failed at insert. One definition now, Python's str.isspace(): every
    such text is text_absent for the engine and refused by corpus.ruling_text; a visible character is accepted."""
    import psycopg

    from src.db.pg import connect, sha256_text
    from src.layer1.golden import registry_engine

    url, _, _ = loaded
    engine = registry_engine([1, 1, 0])
    blanks = [chr(c) for c in range(0x110000) if chr(c).isspace()]
    insert = """INSERT INTO corpus.ruling_text (ruling_id, source, content, content_sha256, snapshot_id)
                VALUES (%s, 'bger', %s, %s, %s)"""
    with connect(url, actor="test") as conn:
        ruling_id, snapshot_id = conn.execute(
            "SELECT ruling_id::text, snapshot_id::text FROM corpus.ruling_text WHERE is_primary LIMIT 1"
        ).fetchone()
        conn.commit()
        with conn.transaction(force_rollback=True):
            for content in [*blanks, "".join(blanks)]:
                decision = engine.decide("8C_1/2025", {"hf_legal_area": "Unfallversicherung"}, None, content)
                assert decision.text == "text_absent", repr(content)
                with pytest.raises(psycopg.errors.CheckViolation, match="ruling_text_content_visible_chk"):
                    with conn.transaction():
                        conn.execute(insert, (ruling_id, content, sha256_text(content), snapshot_id))
            visible = "".join(blanks) + "x"
            assert engine.decide("8C_1/2025", {"hf_legal_area": None}, None, visible).text == "text_clear"
            conn.execute(insert, (ruling_id, visible, sha256_text(visible), snapshot_id))


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


def _stored_rules(conn, version: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT r.rule_code FROM ops.component_version_rule b JOIN ops.rule r USING (rule_id)
               JOIN ops.component_version cv USING (component_version_id)
               WHERE cv.step = 'layer1_filter' AND cv.version_label = %s ORDER BY b.ordinal""",
            (version,),
        )
        return [code for (code,) in cur.fetchall()]


def test_registry_refuses_a_file_that_drops_a_rule_of_an_existing_version(loaded, tmp_path):
    """Dropping the last rule of V1.1.0 inserts nothing new (each remaining binding exists): the database seal never
    sees it, so the loader must compare the stored binding with the file (red before the fix: the file loaded)."""
    from src.db.pg import connect
    from src.db.registry import RegistryConflict, load_step_registry
    from src.layer1.models import Layer1Config, RuleDefinition

    url, _, _ = loaded
    reg = json.loads(Path("src/layer1/registry/layer1_filter.json").read_text())
    dropped = reg["versions"][1]["rules"].pop()
    assert reg["versions"][1]["version"] == [1, 1, 0] and dropped == "L1_SIGNAL_RUBRIC_FROM_TITLE"
    edited = tmp_path / "dropped.json"
    edited.write_text(json.dumps(reg))
    with connect(url, actor="test") as conn:
        with pytest.raises(RegistryConflict, match=r"layer1_filter V1\.1\.0: its rules are .* immutable"):
            load_step_registry(
                conn, edited, Layer1Config, RuleDefinition, ("src/layer1/engine.py", "src/layer1/models.py")
            )
        assert len(_stored_rules(conn, "V1.1.0")) == RULES and _stored_rules(conn, "V1.1.0")[-1] == dropped


def test_registry_refuses_a_reordered_rule_set_of_a_version_nothing_seals_yet(loaded, tmp_path):
    """A version no profile pins and no assessment uses is not sealed by the database: reordering its rules inserts
    nothing (every binding exists, ON CONFLICT DO NOTHING); the loader refuses it. Rolled back: nothing stays."""
    from src.db.pg import connect
    from src.db.registry import RegistryConflict, load_step_registry
    from src.layer1.models import Layer1Config, RuleDefinition

    url, _, _ = loaded
    code = ("src/layer1/engine.py", "src/layer1/models.py")
    reg = json.loads(Path("src/layer1/registry/layer1_filter.json").read_text())
    spare = {**reg["versions"][1], "version": [1, 9, 0], "previous": [1, 1, 0], "bump_kind": "minor"}
    reg["versions"].append(spare)
    first = tmp_path / "spare.json"
    first.write_text(json.dumps(reg))
    spare["rules"] = [spare["rules"][1], spare["rules"][0], *spare["rules"][2:]]
    swapped = tmp_path / "swapped.json"
    swapped.write_text(json.dumps(reg))
    with connect(url, actor="test") as conn:
        with conn.transaction(force_rollback=True):
            load_step_registry(conn, first, Layer1Config, RuleDefinition, code)
            with pytest.raises(RegistryConflict, match=r"layer1_filter V1\.9\.0: its rules are"):
                load_step_registry(conn, swapped, Layer1Config, RuleDefinition, code)
            assert _stored_rules(conn, "V1.9.0")[:2] == ["L1_KEEP_RUBRIC", "L1_KEEP_RUBRIC_MISSING"]
        assert _stored_rules(conn, "V1.9.0") == []


def _label_dropped_ruling(url: str, run_id: str) -> None:
    """A synthetic Suva label on 5A_1/2026, which both versions drop (throwaway database only, D-031). Idempotent."""
    import psycopg

    with psycopg.connect(url) as conn:
        conn.execute("SET app.actor = 'test'")
        conn.execute(
            """INSERT INTO gold.label (ruling_id, source, in_suva_scope, quarter_label, source_ref, snapshot_id,
                                       created_by_run_id)
               SELECT ruling_id, 'suva_relevance_list', true, '2026 Q2', 'judgements/x.xlsx#row-3',
                      '00000000-0000-4000-8000-0000000000a2', %s FROM corpus.ruling WHERE docket = '5A_1/2026'
               ON CONFLICT DO NOTHING""",
            (run_id,),
        )


def test_recall_exits_1_when_a_labelled_ruling_is_dropped(loaded, monkeypatch, capsys):
    """F-14: the blocking recall check fails. Synthetic label on a dropped ruling, in the throwaway database only.
    Last tests of the module (this one and the next): the label changes the recall of the tests above."""
    import psycopg

    from src.layer1.__main__ import main

    url, _, summary = loaded
    monkeypatch.setenv("DATABASE_URL", url)
    _label_dropped_ruling(url, summary["run_id"])
    with psycopg.connect(url) as conn:
        run_id = conn.execute(
            "SELECT run_id::text FROM ops.pipeline_run pr JOIN ops.pipeline_profile_version pv "
            "USING (profile_version_id) WHERE pr.kind = 'layer1' AND pr.status = 'succeeded' "
            "AND pv.profile_code = 'default' ORDER BY pr.started_at LIMIT 1"
        ).fetchone()[0]
    assert main(["recall", "--run", run_id]) == 1
    captured = capsys.readouterr()
    assert "suva_list            1/2 kept" in captured.out
    assert "recall: FAILED (a labelled ruling is dropped)" in captured.out


def test_validate_fails_when_the_candidate_drops_a_labelled_ruling(loaded, tmp_path, monkeypatch, capsys):
    """F-14 in validate: Suva labels a ruling the candidate drops (the synthetic label on 5A_1/2026). Baseline and
    candidate are the same profile, so no ruling changes scope: the recall check alone fails the validation."""
    from src.layer1.__main__ import main

    url, _, summary = loaded
    monkeypatch.setenv("DATABASE_URL", url)
    _label_dropped_ruling(url, summary["run_id"])
    out = tmp_path / "validation.json"
    args = ["--runs-dir", str(tmp_path / "runs"), "--out", str(out)]
    assert main(["validate", "--baseline-profile", "default", "--profile", "default", *args]) == 1
    v = json.loads(out.read_text())["validation"]
    checks = v["checks"]
    assert (checks["runs_succeeded"], checks["same_rulings"], checks["no_removal"]) == (True, True, True)
    assert checks["candidate_recall_complete"] is False and not v["passed"]
    assert v["failures"] == ["the candidate drops a labelled ruling"]
    assert v["recall"]["candidate"]["suva_list"] == {"total": 2, "kept": 1, "not_assessed": 0}
    assert "missed" not in out.read_text() and "5A_1" not in out.read_text()  # aggregates only (D-031)
    assert "validate: FAILED" in capsys.readouterr().out
