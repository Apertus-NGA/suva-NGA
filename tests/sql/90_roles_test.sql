-- Roles (§15.6): the API reads and writes only through the functions; the pipeline inserts facts and updates
-- lifecycle columns only; the report role only reads.
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

-- report
SET LOCAL ROLE suva_report;
DO $$
BEGIN
  PERFORM count(*) FROM triage.v_export_ranked;
  BEGIN
    INSERT INTO ops.reason_code (code, domain, label_de) VALUES ('X', 'work', 'x');
    RAISE EXCEPTION 'suva_report wrote a row';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
END $$;
RESET ROLE;

ROLLBACK;
