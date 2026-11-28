-- Roles (§15.6): the API reads and writes only through the functions; the pipeline inserts facts and updates
-- lifecycle columns only (the pipeline group also writes the rule and exclusion ledgers, F-11); the report role only reads.
BEGIN;
\ir _fixtures.sql

-- API
SET LOCAL ROLE suva_api;
DO $$
BEGIN
  PERFORM count(*) FROM triage.v_scope_current;
  BEGIN
    INSERT INTO gold.expert_review (target_kind, assessment_id, verdict, reviewed_label, review_schema_id, actor)
    SELECT 'scope', '00000000-0000-4000-8000-000000000602', 'correct', 'out_of_scope', json_schema_id, 'x' FROM ops.json_schema LIMIT 1;
    RAISE EXCEPTION 'suva_api inserted directly into gold.expert_review';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  BEGIN
    UPDATE triage.assessment SET explanation_de = 'x' WHERE assessment_id = '00000000-0000-4000-8000-000000000601';
    RAISE EXCEPTION 'suva_api updated an assessment';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  BEGIN
    INSERT INTO ops.work_item (run_id, ruling_id, step) SELECT '00000000-0000-4000-8000-000000000001', ruling_id, 'summarise' FROM corpus.ruling LIMIT 1;
    RAISE EXCEPTION 'suva_api inserted a work item';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
END $$;
SET LOCAL app.actor = 'expert-1';
SELECT gold.submit_review('scope', '00000000-0000-4000-8000-000000000602', 'incorrect');
SELECT ops.submit_request('add_judgement', '8C_2/2026');
RESET ROLE;

-- pipeline
SET LOCAL ROLE suva_pipeline;
DO $$
BEGIN
  INSERT INTO ops.work_item (run_id, ruling_id, step) SELECT '00000000-0000-4000-8000-000000000001', ruling_id, 'summarise' FROM corpus.ruling WHERE docket = '8C_493/2025';
  UPDATE ops.work_item SET status = 'done', attempts = 1 WHERE step = 'summarise';
  BEGIN
    UPDATE triage.assessment SET score_0_100 = 1 WHERE assessment_id = '00000000-0000-4000-8000-000000000601';
    RAISE EXCEPTION 'suva_pipeline updated a score';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  BEGIN
    PERFORM gold.submit_review('scope', '00000000-0000-4000-8000-000000000602', 'correct');
    RAISE EXCEPTION 'suva_pipeline wrote an expert review';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  BEGIN
    DELETE FROM corpus.ruling WHERE docket = '8C_199/2026';
    RAISE EXCEPTION 'suva_pipeline deleted a ruling';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
END $$;
RESET ROLE;

-- the audit log records the role each session acted as (its SET ROLE), not the owner its trigger function runs as
DO $$ BEGIN
  ASSERT (SELECT db_role FROM audit.change_log WHERE table_name = 'ops.work_item' AND action = 'UPDATE'
          ORDER BY change_id DESC LIMIT 1) = 'suva_pipeline', 'a pipeline update is audited as suva_pipeline';
  ASSERT (SELECT db_role FROM audit.change_log WHERE table_name = 'gold.expert_review'
          ORDER BY change_id DESC LIMIT 1) = 'suva_api', 'an expert review is audited as suva_api';
END $$;

-- pipeline group, which layer 1 runs under (F-11): writes a complete rule ledger (checked under this role) and the
-- ingest exclusion ledger, reads the new views, never changes an exclusion
INSERT INTO ops.component_version (step, name, v_major, v_minor, v_patch, config_schema_id, config, config_sha256, code_path, code_sha256, bump_kind, changelog)
VALUES ('ingest', 'fixture ingest', 1, 0, 0, (SELECT json_schema_id FROM ops.json_schema WHERE schema_code = 'test.step_config'), '{}',
        repeat('4', 64), 'x', repeat('5', 64), 'initial', 'fixture');
SET LOCAL ROLE suva_g_pipeline;
DO $$
DECLARE
  sp  uuid;
  a   uuid := '00000000-0000-4000-8000-000000000104';
  l1  uuid := (SELECT component_version_id FROM ops.component_version WHERE step = 'layer1_filter');
BEGIN
  ASSERT current_user = 'suva_g_pipeline', 'running as the pipeline group';
  INSERT INTO ops.span (run_id, step, operation, ruling_id, status, started_at, ended_at)
  VALUES ('00000000-0000-4000-8000-000000000001', 'layer1_filter', 'layer1.roles', (SELECT ruling_id FROM corpus.ruling WHERE docket = '8C_307/2025'),
          'ok', now(), now())
  RETURNING span_id INTO sp;
  INSERT INTO triage.assessment (assessment_id, run_id, ruling_id, step, repetition_idx, component_version_id, span_id, input_fingerprint,
                                 in_suva_scope, outcome, reason_code, mode, started_at)
  VALUES (a, '00000000-0000-4000-8000-000000000001', (SELECT ruling_id FROM corpus.ruling WHERE docket = '8C_307/2025'), 'layer1_filter', 1,
          l1, sp, repeat('0', 64), 'potentially', 'ok', 'L1_KEEP_RUBRIC', 'REPLAY', now());
  INSERT INTO triage.assessment_reason (assessment_id, ordinal, rule_id, reason_code, effect, outcome, evidence_field, examined_value, matched_text)
  SELECT a, cvr.ordinal, r.rule_id, r.reason_code, r.kind, CASE WHEN r.kind = 'keep' THEN 'fired' ELSE 'not_fired' END::ops.rule_outcome,
         'rubric:gegenstand', 'Assurance-accidents', CASE WHEN r.kind = 'keep' THEN 'Assurance-accidents' END
  FROM ops.component_version_rule cvr JOIN ops.rule r ON r.rule_id = cvr.rule_id WHERE cvr.component_version_id = l1;
  SET CONSTRAINTS ALL IMMEDIATE;
  SET CONSTRAINTS ALL DEFERRED;
  ASSERT (SELECT count(*) FROM triage.v_layer1_ledger WHERE assessment_id = a) = 2, 'the pipeline reads its ledger';
  INSERT INTO corpus.ingest_exclusion (snapshot_id, source, external_id, reason_code, component_version_id, run_id)
  VALUES ('00000000-0000-4000-8000-0000000000a1', 'hf_decision_id', 'bger_5A_9_2020', 'OUT_OF_WINDOW',
          (SELECT component_version_id FROM ops.component_version WHERE step = 'ingest'), '00000000-0000-4000-8000-000000000001');
  ASSERT (SELECT exclusions FROM corpus.v_ingest_closure WHERE snapshot_id = '00000000-0000-4000-8000-0000000000a1') = 1, 'the pipeline reads the closure';
  BEGIN
    UPDATE corpus.ingest_exclusion SET reason_code = 'ING_DOCKET_MALFORMED' WHERE external_id = 'bger_5A_9_2020';
    RAISE EXCEPTION 'suva_g_pipeline updated an exclusion';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  BEGIN
    DELETE FROM corpus.ingest_exclusion WHERE external_id = 'bger_5A_9_2020';
    RAISE EXCEPTION 'suva_g_pipeline deleted an exclusion';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
END $$;
RESET ROLE;

-- report
SET LOCAL ROLE suva_report;
DO $$
BEGIN
  PERFORM count(*) FROM triage.v_export_ranked;
  PERFORM count(*) FROM triage.v_layer1_ledger;
  PERFORM count(*) FROM corpus.v_ingest_closure;
  BEGIN
    INSERT INTO ops.reason_code (code, domain, label_de) VALUES ('X', 'work', 'x');
    RAISE EXCEPTION 'suva_report wrote a row';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
END $$;
RESET ROLE;

ROLLBACK;
