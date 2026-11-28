"""layer1_filter V1.2.0 (D-083) end to end on PostgreSQL, and the ingest closure command (F-04).

A throwaway database (from DATABASE_URL, dropped at the end) is loaded through the real registries and the HF loader
from a synthetic parquet: one ruling without text (empty full_text, so no corpus.ruling_text row and no input text
for its assessment) and one ruling per audited miss V1.2.0 fixes. Dockets and texts are synthetic: none is in
judgements/, no person is named (D-038), and the one Suva label lives only in the throwaway database (D-031).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import uuid

import pytest

pytestmark = [pytest.mark.db, pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="needs DATABASE_URL")]

ROWS = [  # decision_id, docket, decision_date, publication_date, scraped_at, language, title, legal_area, full_text
    ("bger_5A_906_2026", "5A_906/2026", "2026-05-04", "", "2026-05-10T08:00:00", "de", "Erbrecht,", "Erbrecht", ""),
    (
        "bger_4A_901_2025",
        "4A_901/2025",
        "2026-04-14",
        "",
        "2026-04-20T08:00:00",
        "de",
        "Haftpflichtrecht; Revision",
        "",
        "Der Kläger verlangt Schadenersatz.",
    ),
    (
        "bger_8C_902_2025",
        "8C_902/2025",
        "2026-04-15",
        "",
        "2026-04-21T08:00:00",
        "de",
        "Invalidenversicherung",
        "Gesundheitswesen & soziale Sicherheit",
        "Die IV-Stelle verfügte.",
    ),
    (
        "bger_9C_903_2025",
        "9C_903/2025",
        "2026-05-05",
        "",
        "2026-05-12T08:00:00",
        "it",
        "Assicurazione contro le malattie (premi),",
        "Assicurazione contro le malattie",
        "Diritto: 1. Il ricorso è respinto.",
    ),
    (
        "bger_2C_904_2025",
        "2C_904/2025",
        "2026-05-06",
        "",
        "2026-05-12T08:00:00",
        "de",
        "Steuerrecht,",
        "Steuerrecht",
        "Die Schweizerische Unfallversicherungsanstalt hat Beschwerde geführt.",
    ),
    (
        "bger_6B_905_2025",
        "6B_905/2025",
        "2026-05-07",
        "",
        "2026-05-13T08:00:00",
        "fr",
        "Droit pénal,",
        "Droit pénal",
        "Les prestations de l'assurance accident sont réservées.",
    ),
    (  # kept by both versions
        "bger_8C_911_2026",
        "8C_911/2026",
        "2026-04-08",
        "2026-05-26",
        "2026-05-26T08:00:00",
        "fr",
        "Assurance-accidents (rechute),",
        "Assurance-accidents",
        "La Suva est intimée.",
    ),
    (  # dropped by both versions
        "bger_4A_907_2025",
        "4A_907/2025",
        "2026-06-02",
        "",
        "2026-06-08T08:00:00",
        "de",
        "Mietrecht; Kündigung",
        "",
        "Die Kündigung ist gültig.",
    ),
]
NEWLY_KEPT = {  # V1.1.0 drops, V1.2.0 keeps, by this decisive rule
    "5A_906/2026": "L1_KEEP_TEXT_UNAVAILABLE",
    "4A_901/2025": "L1_KEEP_TITLE_RUBRIC",
    "8C_902/2025": "L1_KEEP_TITLE_RUBRIC",
    "9C_903/2025": "L1_KEEP_RUBRIC",
    "2C_904/2025": "L1_KEEP_ACCIDENT_TERM",
    "6B_905/2025": "L1_KEEP_ACCIDENT_TERM",
}
DOCKET = re.compile(r"\b\d{1,2}[A-Z]_\d+")


@pytest.fixture(scope="module")
def loaded(tmp_path_factory):
    import psycopg
    import pyarrow as pa
    import pyarrow.parquet as pq
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    from src.db import deploy
    from src.db.pg import connect
    from src.ingest.__main__ import load_registries
    from src.ingest.hf_base import load_base
    from src.ingest.models import IngestConfig

    base = os.environ["DATABASE_URL"]
    name = f"suva_test_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    url = make_conninfo(**(conninfo_to_dict(base) | {"dbname": name}))
    tmp = tmp_path_factory.mktemp("layer1_v120")
    try:
        res = deploy.run_psql(argparse.Namespace(compose=False, url=url), deploy.script_for(deploy.sql_files()), True)
        assert res.returncode == 0, res.stderr
        cols = ["decision_id", "docket_number", "decision_date", "publication_date", "scraped_at", "language"]
        cols += ["title", "legal_area", "full_text"]
        rows = [dict(zip(cols, r, strict=True)) | {"appealed_court_raw": None} for r in ROWS]
        parquet = tmp / "bger.parquet"
        pq.write_table(pa.Table.from_pylist(rows), parquet)
        with connect(url, actor="test") as conn:
            load_registries(conn)
            with conn.cursor() as cur:
                cur.execute("SELECT config FROM ops.component_version WHERE step = 'ingest'")
                cfg = IngestConfig.model_validate(cur.fetchone()[0])
            summary = load_base(conn, parquet, cfg, [], actor="test")
        yield url, tmp, summary
    finally:
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture(scope="module")
def runs(loaded):
    """One run of the default profile (layer1_filter V1.1.0) and one of layer1_candidate (V1.2.0)."""
    from src.db.pg import connect
    from src.layer1.run import run_layer1

    url, tmp, _ = loaded
    with connect(url, actor="test") as conn:
        old = run_layer1(conn, profile="default", runs_dir=tmp / "runs", actor="test")
        new = run_layer1(conn, profile="layer1_candidate", runs_dir=tmp / "runs", actor="test")
    return old, new


def _decisions(url: str, run_id: str) -> dict[str, tuple]:
    import psycopg

    with psycopg.connect(url) as conn:
        return {
            docket: (scope, reason, text_id, explanation)
            for docket, scope, reason, text_id, explanation in conn.execute(
                """SELECT r.docket, a.in_suva_scope::text, a.reason_code, a.input_text_id::text, a.explanation_de
                   FROM triage.assessment a JOIN corpus.ruling r USING (ruling_id) WHERE a.run_id = %s""",
                (run_id,),
            ).fetchall()
        }


def test_the_ruling_without_text_is_loaded_without_a_text(loaded):
    _, _, summary = loaded
    assert (summary["rulings"], summary["texts"], summary["closure_ok"]) == (len(ROWS), len(ROWS) - 1, 1)


def test_v110_drops_the_ruling_without_text_on_its_prefix_alone_and_v120_keeps_it(loaded, runs):
    """G5: V1.1.0 drops 5A_906/2026, which has no text, on its docket prefix alone (L1_DROP_WRONG_COURT: the term
    checks could not run). V1.2.0 keeps it with L1_KEEP_TEXT_UNAVAILABLE, and the database certified that ledger
    row (full_text, no offsets, no match) on an assessment without an input text."""
    import psycopg

    from src.layer1.run import NO_TEXT

    url, _, _ = loaded
    old, new = runs
    assert (old["version"], new["version"]) == ("V1.1.0", "V1.2.0")
    before, after = _decisions(url, old["run_id"]), _decisions(url, new["run_id"])
    assert before["5A_906/2026"][:3] == ("out_of_scope", "L1_DROP_WRONG_COURT", None)
    assert NO_TEXT in before["5A_906/2026"][3]
    assert after["5A_906/2026"] == (
        "potentially",
        "L1_KEEP_TEXT_UNAVAILABLE",
        None,
        "Vorauswahl bestanden: Kein Urteilstext verfügbar: vorsorglich behalten.",
    )
    with psycopg.connect(url) as conn:
        ledger = conn.execute(
            """SELECT rule_code, outcome::text, evidence_field, char_start, matched_text, detail ->> 'why', is_decisive
               FROM triage.v_layer1_ledger WHERE run_id = %s AND docket = '5A_906/2026' ORDER BY ordinal""",
            (new["run_id"],),
        ).fetchall()
        per_run = dict(
            conn.execute(
                """SELECT run_id::text, count(*)::float / count(DISTINCT assessment_id) FROM triage.v_layer1_ledger
                   WHERE run_id IN (%s, %s) GROUP BY 1""",
                (old["run_id"], new["run_id"]),
            ).fetchall()
        )
    assert per_run == {old["run_id"]: 9.0, new["run_id"]: 11.0}  # every rule of the version, once per ruling
    rows = {code: rest for code, *rest in ledger}
    assert len(ledger) == 11
    assert rows["L1_KEEP_TEXT_UNAVAILABLE"] == ["fired", "full_text", None, None, None, True]
    assert rows["L1_DROP_WRONG_COURT"] == ["fired", "docket", None, "5A", None, False]
    for code in ("L1_KEEP_ACCIDENT_TERM", "L1_KEEP_CONTRACT_TERM", "L1_FLAG_CLOSED_RUBRIC"):
        assert rows[code][:2] == ["not_applicable", None] and rows[code][4] == "text_absent"
    assert rows["L1_KEEP_TITLE_RUBRIC"][4] == "court_not_listed"


def test_v120_keeps_each_audited_miss_and_changes_nothing_v110_keeps(loaded, runs):
    import psycopg

    url, _, _ = loaded
    old, new = runs
    before, after = _decisions(url, old["run_id"]), _decisions(url, new["run_id"])
    for docket, reason in NEWLY_KEPT.items():
        assert before[docket][0] == "out_of_scope", docket
        assert after[docket][:2] == ("potentially", reason), docket
    assert before["8C_911/2026"][:2] == after["8C_911/2026"][:2] == ("potentially", "L1_KEEP_RUBRIC")
    assert before["4A_907/2025"][:2] == after["4A_907/2025"][:2] == ("out_of_scope", "L1_DROP_RUBRIC_OUT")
    assert (old["kept"], new["kept"]) == (1, 1 + len(NEWLY_KEPT))
    with psycopg.connect(url) as conn:
        matches = conn.execute(
            """SELECT l.docket, t.content, l.char_start, l.char_end, l.matched_text FROM triage.v_layer1_ledger l
               JOIN corpus.ruling_text t ON t.text_id = l.input_text_id
               WHERE l.run_id = %s AND l.rule_code = 'L1_KEEP_ACCIDENT_TERM' AND l.outcome = 'fired'""",
            (new["run_id"],),
        ).fetchall()
        title = conn.execute(
            """SELECT docket, evidence_field, examined_value, matched_text, is_decisive FROM triage.v_layer1_ledger
               WHERE run_id = %s AND rule_code = 'L1_KEEP_TITLE_RUBRIC' AND outcome = 'fired' ORDER BY docket""",
            (new["run_id"],),
        ).fetchall()
    found = {docket: (content[start:end], matched) for docket, content, start, end, matched in matches}
    assert found["2C_904/2025"] == ("Unfallversicherungsanstalt", "Unfallversicherungsanstalt")
    assert found["6B_905/2025"] == ("assurance accident", "assurance accident")
    assert title == [  # decisive where no lower-ordinal keep fired; otherwise listed under "Ebenso"
        ("4A_901/2025", "gegenstand", "Haftpflichtrecht", "Haftpflichtrecht", True),
        ("8C_902/2025", "gegenstand", "Invalidenversicherung", "Invalidenversicherung", True),
        ("8C_911/2026", "gegenstand", "Assurance-accidents", "Assurance-accidents", False),
        ("9C_903/2025", "gegenstand", "Assicurazione contro le malattie", "Assicurazione contro le malattie", False),
    ]
    assert after["8C_911/2026"][3] == (
        "Vorauswahl bestanden: Rechtsgebiet in der Liste der Abteilung. Ebenso: Text nennt die Suva oder die Unfall- "
        "oder Militärversicherung; Rechtsgebiet laut Gegenstand in der Liste der Abteilung."
    )


def test_the_v120_run_files_equal_the_database_and_its_log_closes(loaded, runs):
    from src.db.pg import connect
    from src.layer1.run import verify_run

    url, tmp, _ = loaded
    _, new = runs
    log = json.loads((tmp / "runs" / new["run_id"] / "layer1_log.json").read_text())
    assert log["quality"]["all_checks_passed"]
    assert log["actions"][0]["passed_by_reason"].get("kept_title_rubric") == 2
    assert log["actions"][1]["passed_by_reason"].get("kept_text_unavailable") == 1
    assert new["golden"] == "not_comparable"  # a synthetic corpus is not the pinned snapshot
    with connect(url, actor="test") as conn:
        read, problems = verify_run(conn, new["run_id"], tmp / "runs")
    assert (read, problems) == (len(ROWS), [])


def test_validate_default_against_the_candidate_passes_and_fixes_a_labelled_drop(loaded, tmp_path, monkeypatch):
    """A synthetic Suva label on the ruling without text (throwaway database only, D-031): the baseline (default,
    V1.1.0) drops it, the candidate keeps it. No ruling goes potentially -> out_of_scope, so validate passes; the
    baseline's recall is reported, not required. The report holds aggregates only."""
    import psycopg

    from src.layer1.__main__ import main

    url, _, summary = loaded
    monkeypatch.setenv("DATABASE_URL", url)
    with psycopg.connect(url) as conn:
        conn.execute("SET app.actor = 'test'")
        conn.execute("""INSERT INTO ops.source_snapshot (snapshot_id, source, uri, file_sha256, retrieved_at)
                        VALUES ('00000000-0000-4000-8000-0000000000a3', 'judgements_workbook', 'judgements/x.xlsx',
                                repeat('e', 64), now())""")
        conn.execute(
            """INSERT INTO gold.label (ruling_id, source, in_suva_scope, quarter_label, source_ref, snapshot_id,
                                       created_by_run_id)
               SELECT ruling_id, 'suva_relevance_list', true, '2026 Q2', 'judgements/x.xlsx#row-2',
                      '00000000-0000-4000-8000-0000000000a3', %s FROM corpus.ruling WHERE docket = '5A_906/2026'""",
            (summary["run_id"],),
        )
    out = tmp_path / "validation.json"
    argv = ["validate", "--baseline-profile", "default", "--profile", "layer1_candidate", "--out", str(out)]
    assert main([*argv, "--runs-dir", str(tmp_path / "runs")]) == 0
    v = json.loads(out.read_text())["validation"]
    assert v["passed"] and v["failures"] == []
    assert (v["potentially_to_out_of_scope"], v["out_of_scope_to_potentially"]) == (0, len(NEWLY_KEPT))
    assert (v["baseline"]["layer1_filter"], v["candidate"]["layer1_filter"]) == ("V1.1.0", "V1.2.0")
    assert v["recall"]["baseline"]["suva_list"] == {"total": 1, "kept": 0, "not_assessed": 0}
    assert v["recall"]["candidate"]["suva_list"] == {"total": 1, "kept": 1, "not_assessed": 0}
    assert v["checks"]["candidate_recall_complete"] is True
    assert not DOCKET.search(out.read_text())  # aggregates only (D-031)


def test_the_closure_command_reports_every_snapshot_and_fails_on_an_open_one(loaded, tmp_path, monkeypatch, capsys):
    """F-04: `python -m src.ingest closure` reads corpus.v_ingest_closure (counts only, no docket) and exits 1 when a
    snapshot does not close. Last test of the module: it adds a second HF snapshot whose file has 2 rows of which
    only 1 is accounted for (one exclusion, no ref)."""
    import psycopg

    from src.ingest.__main__ import main

    url, _, summary = loaded
    monkeypatch.setenv("DATABASE_URL", url)
    out = tmp_path / "closure.json"
    assert main(["closure", "--out", str(out)]) == 0
    report = json.loads(out.read_text())
    [snap] = report["snapshots"]
    assert report["closure_ok"] is True and report["view"] == "corpus.v_ingest_closure"
    assert (snap["source"], snap["file_rows"], snap["loaded_refs"], snap["exclusions"]) == ("hf_bger", 8, 8, 0)
    assert (snap["unaccounted_rows"], snap["closure_ok"], snap["exclusions_by_reason"]) == (0, True, {})
    assert not DOCKET.search(out.read_text())
    assert "closure: OK" in capsys.readouterr().out

    with psycopg.connect(url) as conn:
        conn.execute("SET app.actor = 'test'")
        conn.execute("""INSERT INTO ops.source_snapshot (snapshot_id, source, revision, uri, file_sha256, retrieved_at,
                                                         row_count)
                        VALUES ('00000000-0000-4000-8000-0000000000b9', 'hf_bger', 'test-revision', 'test.parquet',
                                repeat('d', 64), now(), 2)""")
        conn.execute(
            """INSERT INTO corpus.ingest_exclusion (snapshot_id, source, external_id, docket_raw, decision_date,
                                                    reason_code, component_version_id, run_id)
               SELECT '00000000-0000-4000-8000-0000000000b9', 'hf_decision_id', 'test_row_1', NULL, NULL,
                      'OUT_OF_WINDOW', component_version_id, %s FROM ops.component_version WHERE step = 'ingest'""",
            (summary["run_id"],),
        )
    assert main(["closure", "--out", str(out)]) == 1
    report = json.loads(out.read_text())
    open_snap = next(s for s in report["snapshots"] if s["revision"] == "test-revision")
    assert report["closure_ok"] is False
    assert (open_snap["file_rows"], open_snap["exclusions"], open_snap["unaccounted_rows"]) == (2, 1, 1)
    assert open_snap["exclusions_by_reason"] == {"OUT_OF_WINDOW": 1} and open_snap["closure_ok"] is False
    assert "closure: FAILED" in capsys.readouterr().out
