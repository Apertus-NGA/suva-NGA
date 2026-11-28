-- Gold (D-066): expert reviews only through gold.submit_review (actor required), verdicts paired with their
-- target, correct | incorrect never on potentially, the implied label beside the pipeline label, supersession, Suva
-- labels with closed-world negatives. The absolute verdicts and withdrawal (D-092): 41_expert_review_test.sql.
BEGIN;
\ir _fixtures.sql

-- no actor, no review
SET LOCAL app.actor = '';
SELECT pg_temp.expect_error($q$SELECT gold.submit_review('scope', '00000000-0000-4000-8000-000000000602', 'incorrect')$q$, 'app.actor');
SET LOCAL app.actor = 'expert-1';

-- an expert says the out_of_scope label of 8C_307/2025 is incorrect
SELECT gold.submit_review('scope', '00000000-0000-4000-8000-000000000602', 'incorrect', '{}', 'Rückfall: relevant.');
DO $$ BEGIN
  ASSERT (SELECT reviewed_label FROM gold.expert_review WHERE assessment_id = '00000000-0000-4000-8000-000000000602') = 'out_of_scope',
         'the label the expert saw is copied';
  ASSERT (SELECT pipeline_label || '|' || expert_verdict || '|' || expert_implied_label || '|' || review_is_stale
          FROM triage.v_scope_current WHERE ruling_id = pg_temp.rid('8C_307/2025')) = 'out_of_scope|incorrect|in_scope|false',
         'pipeline label kept, expert opinion beside it (D-066)';
  ASSERT EXISTS (SELECT 1 FROM audit.change_log WHERE table_name = 'gold.expert_review' AND actor = 'expert-1'), 'review audited';
END $$;

-- verdicts must match their target; the relative verdicts (correct | incorrect) never review a potentially label
SELECT pg_temp.expect_error($q$SELECT gold.submit_review('scope', '00000000-0000-4000-8000-000000000602', 'validated')$q$, 'target_chk');
SELECT pg_temp.expect_error($q$SELECT gold.submit_review('scope', '00000000-0000-4000-8000-000000000201', 'correct')$q$, 'target_chk');

-- a review supersedes only a review of the same target; reviews are never edited
SELECT pg_temp.expect_error($q$
  SELECT gold.submit_review('scope', '00000000-0000-4000-8000-000000000601', 'correct', '{}', NULL,
                            (SELECT review_id FROM gold.expert_review WHERE assessment_id = '00000000-0000-4000-8000-000000000602'))$q$, 'same target');
SELECT gold.submit_review('scope', '00000000-0000-4000-8000-000000000602', 'correct', '{}', 'second look',
                          (SELECT review_id FROM gold.expert_review WHERE assessment_id = '00000000-0000-4000-8000-000000000602'));
DO $$ BEGIN
  ASSERT (SELECT expert_verdict FROM triage.v_scope_current WHERE ruling_id = pg_temp.rid('8C_307/2025')) = 'correct', 'the superseding review wins';
END $$;
SELECT pg_temp.expect_error($q$UPDATE gold.expert_review SET comment = 'x'$q$, 'only .* may change');

-- summary review
SELECT gold.submit_review('summary_version', '00000000-0000-4000-8000-000000000701', 'validated');
DO $$ BEGIN
  ASSERT (SELECT expert_verdict FROM summ.v_summary_current WHERE ruling_id = pg_temp.rid('8C_493/2025')) = 'validated', 'summary validated by an expert';
END $$;

-- Suva labels and closed-world negatives on a labelled population
INSERT INTO ops.source_snapshot (snapshot_id, source, uri, file_sha256, retrieved_at)
VALUES ('00000000-0000-4000-8000-0000000000a2', 'judgements_workbook', 'judgements/BG_Urteile_2025_Q4_2026_Q1.xlsx', repeat('f', 64), now());
INSERT INTO gold.label (ruling_id, source, in_suva_scope, quarter_label, source_ref, snapshot_id, created_by_run_id)
VALUES (pg_temp.rid('8C_493/2025'), 'suva_relevance_list', true, '2026 Q2', 'judgements/BG_Urteile_2025_Q4_2026_Q1.xlsx#row-1',
        '00000000-0000-4000-8000-0000000000a2', '00000000-0000-4000-8000-000000000001');
SELECT pg_temp.expect_error($q$
  INSERT INTO gold.label (external_title, source, in_suva_scope, quarter_label, source_ref, snapshot_id, created_by_run_id)
  VALUES ('cantonal decision', 'suva_relevance_list', true, '2026 Q1', 'elsewhere/file.xlsx', '00000000-0000-4000-8000-0000000000a2',
          '00000000-0000-4000-8000-000000000001')$q$, 'check constraint');
INSERT INTO corpus.population (code, quarter, definition, role, built_by_run_id)
VALUES ('fixture_labelled', '2026Q2', 'decision_date', 'labelled', '00000000-0000-4000-8000-000000000001');
INSERT INTO corpus.population_member (population_id, ruling_id, basis)
SELECT population_id, r.ruling_id, 'decision_date' FROM corpus.population, corpus.ruling r
WHERE code = 'fixture_labelled' AND r.docket IN ('8C_493/2025', '8C_307/2025');
DO $$ BEGIN
  ASSERT (SELECT in_suva_scope::text || '|' || basis FROM gold.v_label_effective WHERE ruling_id = pg_temp.rid('8C_493/2025')) = 'true|suva_list', 'listed';
  ASSERT (SELECT in_suva_scope::text || '|' || basis FROM gold.v_label_effective WHERE ruling_id = pg_temp.rid('8C_307/2025')) = 'false|closed_world',
         'unlisted = false, flagged closed_world (Q-04)';
END $$;

ROLLBACK;
