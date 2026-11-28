"""A committed rule ledger cannot be changed afterwards (F-10). Runs only with DATABASE_URL: it creates a throwaway
database, deploys src/db/sql, commits the SQL fixture (tests/sql/_fixtures.sql), then tries, in later transactions
and under the pipeline role layer 1 writes with (F-11), to change what was certified at that commit:

- a ledger row added to an assessment that is already committed (a failed one, which had no ledger, and a dropped
  one, whose ledger was complete) is refused: a ledger is written in the transaction of its assessment;
- a rule added to a step version that assessments already use is refused: the version's rule set is sealed, so a
  certified ledger never becomes incomplete.

The SQL tests (tests/sql/*_test.sql) run inside one rolled-back transaction each, so they cannot commit; this is
why these two cases live here.
"""

from __future__ import annotations

import argparse
import os
import uuid
from pathlib import Path

import pytest

pytestmark = [pytest.mark.db, pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="needs DATABASE_URL")]

FIXTURE = Path(__file__).parent / "sql" / "_fixtures.sql"
FAILED = "00000000-0000-4000-8000-000000000105"  # layer 1, failed, potentially, no ledger
DROPPED = "00000000-0000-4000-8000-000000000103"  # layer 1, out_of_scope, complete ledger (fixture)

SETUP = f"""
INSERT INTO triage.assessment (assessment_id, run_id, ruling_id, step, repetition_idx, component_version_id, span_id,
                               input_fingerprint, in_suva_scope, outcome, mode, started_at)
VALUES ('{FAILED}', '00000000-0000-4000-8000-000000000001', pg_temp.rid('8C_307/2025'), 'layer1_filter', 5,
        pg_temp.cv('layer1_filter'), pg_temp.span('layer1_filter', '8C_307/2025'), repeat('0', 64), 'potentially',
        'failed', 'REPLAY', now());
"""

RULE = "(SELECT rule_id FROM ops.rule WHERE rule_code = '{}' AND v_major = 1)"
L1 = (
    "(SELECT component_version_id FROM ops.component_version"
    " WHERE step = 'layer1_filter' AND v_major = 1 AND v_minor = 0)"
)

ATTACKS = [
    (
        "a fired keep added to a committed failed assessment",
        f"""INSERT INTO triage.assessment_reason (assessment_id, ordinal, rule_id, reason_code, effect, outcome,
                                                  evidence_field, examined_value, matched_text)
            VALUES ('{FAILED}', 1, {RULE.format("L1_KEEP_RUBRIC")}, 'L1_KEEP_RUBRIC', 'keep', 'fired',
                    'rubric:gegenstand', 'Assurance-accidents', 'Assurance-accidents')""",
        rf"assessment {FAILED} is already committed",
    ),
    (
        "a row added to the complete ledger of a committed drop",
        f"""INSERT INTO triage.assessment_reason (assessment_id, ordinal, rule_id, reason_code, effect, outcome,
                                                  evidence_field, examined_value, matched_text)
            VALUES ('{DROPPED}', 1, {RULE.format("L1_KEEP_RUBRIC")}, 'L1_KEEP_RUBRIC', 'keep', 'fired',
                    'rubric:gegenstand', 'Assicurazione contro gli infortuni', 'Assicurazione contro gli infortuni')""",
        rf"assessment {DROPPED} is already committed",
    ),
    (
        "a rule appended to the version the committed ledgers certify",
        f"""INSERT INTO ops.rule (step, rule_code, v_major, v_minor, v_patch, kind, definition, definition_schema_id,
                                  reason_code, status, bump_kind, changelog)
            VALUES ('layer1_filter', 'L1_KEEP_TITLE_RUBRIC', 1, 0, 0, 'keep', '{{}}',
                    (SELECT json_schema_id FROM ops.json_schema WHERE schema_code = 'test.rule_definition'),
                    'L1_KEEP_TITLE_RUBRIC', 'active', 'initial', 'attack');
            INSERT INTO ops.component_version_rule (component_version_id, rule_id, ordinal)
            VALUES ({L1}, {RULE.format("L1_KEEP_TITLE_RUBRIC")}, 3)""",
        r"its rule set is sealed",
    ),
]


@pytest.fixture(scope="module")
def committed():
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
        fixture = deploy.expand_includes(FIXTURE)
        script = f"\\set ON_ERROR_STOP on\nBEGIN;\n{fixture}\n{SETUP}\nCOMMIT;\n"
        res = deploy.run_psql(ns, script, capture=True)
        assert res.returncode == 0, res.stderr
        yield url
    finally:
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _ledger(conn, assessment_id: str) -> list[tuple]:
    return conn.execute(
        """SELECT ordinal, rule_code, outcome::text FROM triage.v_layer1_ledger WHERE assessment_id = %s
           ORDER BY ordinal""",
        (assessment_id,),
    ).fetchall()


@pytest.mark.parametrize(("label", "sql", "pattern"), ATTACKS, ids=[a[0] for a in ATTACKS])
def test_a_committed_ledger_cannot_change(committed, label, sql, pattern):
    import psycopg

    with psycopg.connect(committed, autocommit=True) as conn:
        conn.execute("SET app.actor = 'test'")
        conn.execute("SET ROLE suva_g_pipeline")
        before = {a: _ledger(conn, a) for a in (FAILED, DROPPED)}
        with pytest.raises(psycopg.Error, match=pattern):
            with conn.transaction():
                conn.execute(sql)
        assert {a: _ledger(conn, a) for a in (FAILED, DROPPED)} == before, label
        assert before[FAILED] == [] and [r[2] for r in before[DROPPED]] == ["not_fired", "fired"]


def test_a_new_assessment_still_writes_its_ledger_in_its_own_transaction(committed):
    import psycopg

    new = "00000000-0000-4000-8000-000000000106"
    with psycopg.connect(committed, autocommit=True) as conn:
        conn.execute("SET app.actor = 'test'")
        conn.execute("SET ROLE suva_g_pipeline")
        with conn.transaction():
            span = conn.execute(
                """INSERT INTO ops.span (run_id, step, operation, ruling_id, status, started_at, ended_at)
                   SELECT '00000000-0000-4000-8000-000000000001', 'layer1_filter', 'layer1.sealed', ruling_id, 'ok',
                          now(), now() FROM corpus.ruling WHERE docket = '8C_493/2025' RETURNING span_id"""
            ).fetchone()[0]
            conn.execute(
                f"""INSERT INTO triage.assessment (assessment_id, run_id, ruling_id, step, repetition_idx,
                                                   component_version_id, span_id, input_fingerprint, in_suva_scope,
                                                   outcome, reason_code, mode, started_at)
                    SELECT '{new}', '00000000-0000-4000-8000-000000000001', ruling_id, 'layer1_filter', 6, {L1}, %s,
                           repeat('0', 64), 'potentially', 'ok', 'L1_KEEP_RUBRIC', 'REPLAY', now()
                    FROM corpus.ruling WHERE docket = '8C_493/2025'""",
                (span,),
            )
            conn.execute(
                f"""INSERT INTO triage.assessment_reason (assessment_id, ordinal, rule_id, reason_code, effect,
                                                          outcome, evidence_field, examined_value, matched_text)
                    VALUES ('{new}', 1, {RULE.format("L1_KEEP_RUBRIC")}, 'L1_KEEP_RUBRIC', 'keep', 'fired',
                            'rubric:gegenstand', 'Unfallversicherung', 'Unfallversicherung'),
                           ('{new}', 2, {RULE.format("L1_DROP_RUBRIC_OUT")}, 'L1_DROP_RUBRIC_OUT', 'drop', 'not_fired',
                            'rubric:gegenstand', 'Unfallversicherung', NULL)"""
            )
        assert _ledger(conn, new) == [(1, "L1_KEEP_RUBRIC", "fired"), (2, "L1_DROP_RUBRIC_OUT", "not_fired")]
