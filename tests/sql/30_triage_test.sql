-- Triage (D-063, D-064, D-046): the scope-label invariants, the pinned step version, lineage, G1 evidence,
-- scorer comparability, the release gate, and the label, export and trace views.
BEGIN;
\ir _fixtures.sql

-- the label before any release: the latest run of the default profile
DO $$ BEGIN
  ASSERT (SELECT pipeline_label || '|' || step || '|' || label_origin FROM triage.v_scope_pipeline WHERE ruling_id = pg_temp.rid('8C_493/2025'))
         = 'in_scope|ranking|latest_run', 'label of 8C_493/2025';
  ASSERT (SELECT reason_label_de FROM triage.v_scope_pipeline WHERE ruling_id = pg_temp.rid('8C_199/2026')) = 'Relevanzwert unter der Schwelle',
         'an exclusion shows its German reason (G5)';
END $$;

-- scope-label invariants (CHECK constraints)
CREATE FUNCTION pg_temp.l1(p_scope text, p_outcome text, p_reason text, p_rep int) RETURNS text LANGUAGE sql AS $f$
  SELECT format($s$INSERT INTO triage.assessment (run_id, ruling_id, step, repetition_idx, component_version_id, span_id, input_fingerprint,
                    in_suva_scope, outcome, reason_code, mode, started_at)
                  VALUES ('00000000-0000-4000-8000-000000000001', pg_temp.rid('8C_307/2025'), 'layer1_filter', %s, pg_temp.cv('layer1_filter'),
                          pg_temp.span('layer1_filter', '8C_307/2025'), repeat('0', 64), %L, %L, %L, 'REPLAY', now())$s$,
                p_rep, p_scope, p_outcome, p_reason) $f$;
SELECT pg_temp.expect_error(pg_temp.l1('out_of_scope', 'ok', NULL, 5), 'assessment_reason_chk');
SELECT pg_temp.expect_error(pg_temp.l1('out_of_scope', 'failed', 'L1_DROP_NO_RULE', 5), 'assessment_failure_chk');
SELECT pg_temp.expect_error(pg_temp.l1('in_scope', 'ok', NULL, 5), 'assessment_layer1_chk');
SELECT pg_temp.expect_error($q$
  INSERT INTO triage.assessment (run_id, ruling_id, step, repetition_idx, component_version_id, span_id, input_fingerprint, in_suva_scope, outcome, score_0_100, mode, started_at)
  VALUES ('00000000-0000-4000-8000-000000000001', pg_temp.rid('8C_307/2025'), 'layer2_judge', 5, pg_temp.cv('layer2_judge'),
          pg_temp.span('layer2_judge', '8C_307/2025'), repeat('0', 64), 'in_scope', 'ok', 80, 'REPLAY', now())$q$, 'assessment_middle_chk');
SELECT pg_temp.expect_error($q$
  INSERT INTO triage.assessment (run_id, ruling_id, step, repetition_idx, component_version_id, span_id, input_fingerprint, in_suva_scope, outcome, mode, started_at)
  VALUES ('00000000-0000-4000-8000-000000000001', pg_temp.rid('8C_307/2025'), 'layer2_judge', 5, pg_temp.cv('layer2_judge'),
          pg_temp.span('layer2_judge', '8C_307/2025'), repeat('0', 64), 'potentially', 'ok', 'REPLAY', now())$q$, 'assessment_score_chk');
SELECT pg_temp.expect_error($q$
  INSERT INTO triage.assessment (run_id, ruling_id, step, repetition_idx, component_version_id, span_id, input_fingerprint, in_suva_scope, outcome, score_0_100, score_source, mode, started_at)
  VALUES ('00000000-0000-4000-8000-000000000001', pg_temp.rid('8C_307/2025'), 'ranking', 5, pg_temp.cv('ranking'),
          pg_temp.span('ranking', '8C_307/2025'), repeat('0', 64), 'potentially', 'ok', 30, 'judged', 'REPLAY', now())$q$, 'assessment_ranking_chk');
-- a failed judgement stays potentially: allowed
INSERT INTO triage.assessment (run_id, ruling_id, step, repetition_idx, component_version_id, span_id, input_fingerprint, in_suva_scope, outcome, score_source, reason_code, mode, started_at)
VALUES ('00000000-0000-4000-8000-000000000001', pg_temp.rid('8C_307/2025'), 'layer2_judge', 6, pg_temp.cv('layer2_judge'),
        pg_temp.span('layer2_judge', '8C_307/2025'), repeat('0', 64), 'potentially', 'failed', 'failed', 'L2_FAILED_CALL', 'REPLAY', now());

-- the step version must be the one the run's profile pins; same run for the span; same mode; lineage goes backwards
INSERT INTO ops.component_version (step, name, v_major, v_minor, v_patch, config_schema_id, config, config_sha256, code_path, code_sha256, bump_kind, previous_version_id, changelog)
VALUES ('layer1_filter', 'filter E+', 1, 1, 0, (SELECT json_schema_id FROM ops.json_schema WHERE schema_code = 'test.step_config'), '{}', repeat('4', 64), 'x', repeat('5', 64),
        'minor', pg_temp.cv('layer1_filter'), 'wider whitelist');
SELECT pg_temp.expect_error($q$
  INSERT INTO triage.assessment (run_id, ruling_id, step, repetition_idx, component_version_id, span_id, input_fingerprint, in_suva_scope, outcome, mode, started_at)
  VALUES ('00000000-0000-4000-8000-000000000001', pg_temp.rid('8C_307/2025'), 'layer1_filter', 7, pg_temp.cv('layer1_filter', 1, 1),
          pg_temp.span('layer1_filter', '8C_307/2025'), repeat('0', 64), 'potentially', 'ok', 'REPLAY', now())$q$, 'pinned by the run');
INSERT INTO ops.pipeline_run (run_id, profile_version_id, kind, mode, git_dirty, params_sha256, triggered_by)
VALUES ('00000000-0000-4000-8000-000000000002', (SELECT profile_version_id FROM ops.pipeline_profile_version WHERE profile_code = 'default'),
        'layer1', 'REPLAY', false, repeat('6', 64), 'cli');
SELECT pg_temp.expect_error($q$
  INSERT INTO triage.assessment (run_id, ruling_id, step, repetition_idx, component_version_id, span_id, input_fingerprint, in_suva_scope, outcome, mode, started_at)
  VALUES ('00000000-0000-4000-8000-000000000001', pg_temp.rid('8C_307/2025'), 'layer1_filter', 7, pg_temp.cv('layer1_filter'),
          pg_temp.span('layer1_filter', '8C_307/2025', '00000000-0000-4000-8000-000000000002'), repeat('0', 64), 'potentially', 'ok', 'REPLAY', now())$q$,
  'another run');
SELECT pg_temp.expect_error($q$
  INSERT INTO triage.assessment (run_id, ruling_id, step, repetition_idx, component_version_id, span_id, input_fingerprint, in_suva_scope, outcome, mode, started_at)
  VALUES ('00000000-0000-4000-8000-000000000001', pg_temp.rid('8C_307/2025'), 'layer1_filter', 7, pg_temp.cv('layer1_filter'),
          pg_temp.span('layer1_filter', '8C_307/2025'), repeat('0', 64), 'potentially', 'ok', 'LIVE', now())$q$, 'mode');
SELECT pg_temp.expect_error($q$
  INSERT INTO triage.assessment (run_id, ruling_id, step, repetition_idx, component_version_id, span_id, upstream_assessment_id, input_fingerprint, in_suva_scope, outcome, mode, started_at)
  VALUES ('00000000-0000-4000-8000-000000000001', pg_temp.rid('8C_307/2025'), 'layer1_filter', 7, pg_temp.cv('layer1_filter'),
          pg_temp.span('layer1_filter', '8C_307/2025'), '00000000-0000-4000-8000-000000000602', repeat('0', 64), 'potentially', 'ok', 'REPLAY', now())$q$,
  'earlier step');

-- append-only, evidence from the input segmentation only (G1), reasons from the step's own rules, detail tables per step
SELECT pg_temp.expect_error($q$UPDATE triage.assessment SET score_0_100 = 1 WHERE assessment_id = '00000000-0000-4000-8000-000000000201'$q$, 'only .* may change');
SELECT pg_temp.expect_error($q$
  INSERT INTO triage.assessment_evidence (assessment_id, consideration_id, role)
  VALUES ('00000000-0000-4000-8000-000000000301', pg_temp.cons('8C_307/2025', 1), 'cited')$q$, 'input segmentation');
SELECT pg_temp.expect_error($q$
  INSERT INTO triage.assessment_reason (assessment_id, ordinal, rule_id, reason_code, effect, evidence_field)
  VALUES ('00000000-0000-4000-8000-000000000101', 2, pg_temp.rule('V1_IDS_IN_SET'), 'V1_IDS_IN_SET', 'flag', 'docket')$q$, 'not a rule');
SELECT pg_temp.expect_error($q$
  INSERT INTO triage.assessment_reason (assessment_id, ordinal, rule_id, reason_code, effect, evidence_field)
  VALUES ('00000000-0000-4000-8000-000000000101', 2, pg_temp.rule('L1_DROP_NO_RULE'), 'L1_KEEP_COURT_8C_9C', 'drop', 'docket')$q$, 'rule''s reason code');
SELECT pg_temp.expect_error($q$
  INSERT INTO triage.llm_judgement (assessment_id, llm_call_id, prompt_version_id, requested_model, question_language, yes_no_in_top, text_chars_total, text_chars_sent, truncation)
  VALUES ('00000000-0000-4000-8000-000000000101', '00000000-0000-4000-8000-000000000901',
          (SELECT prompt_version_id FROM ops.prompt_version WHERE role = 'layer2_judge.question'), 'm', 'de', true, 1, 1, 'none')$q$, 'layer2_judge assessments only');

-- scorer comparability: a threshold fitted on layer2_judge V2.0.0 cannot rank V1.0.0 scores (D-064)
INSERT INTO ops.component_version (step, name, v_major, v_minor, v_patch, config_schema_id, config, config_sha256, code_path, code_sha256, bump_kind, previous_version_id, changelog)
VALUES ('layer2_judge', '8B judge', 2, 0, 0, (SELECT json_schema_id FROM ops.json_schema WHERE schema_code = 'test.step_config'), '{}', repeat('4', 64), 'x', repeat('5', 64),
        'major', pg_temp.cv('layer2_judge'), 'other model: scores not comparable');
INSERT INTO corpus.population (code, quarter, definition, role, built_by_run_id) VALUES
  ('fixture_pop2', '2026Q2', 'union', 'target', '00000000-0000-4000-8000-000000000001'),
  ('fixture_pop3', '2026Q2', 'union', 'target', '00000000-0000-4000-8000-000000000001');
INSERT INTO corpus.population_member (population_id, ruling_id, basis)
SELECT population_id, pg_temp.rid('8C_493/2025'), 'decision_date' FROM corpus.population WHERE code IN ('fixture_pop2', 'fixture_pop3');
INSERT INTO triage.threshold (threshold_id, ranking_component_version_id, scorer_component_version_id, value_0_100, chosen_on_population_id, policy, frozen_at, created_by_run_id) VALUES
  ('00000000-0000-4000-8000-000000000402', pg_temp.cv('ranking'), pg_temp.cv('layer2_judge', 2, 0), 50,
   (SELECT population_id FROM corpus.population WHERE code = 'fixture_pop2'), 'fixture', now(), '00000000-0000-4000-8000-000000000001'),
  ('00000000-0000-4000-8000-000000000403', pg_temp.cv('ranking'), pg_temp.cv('layer2_judge'), 95,
   (SELECT population_id FROM corpus.population WHERE code = 'fixture_pop3'), 'fixture', now(), '00000000-0000-4000-8000-000000000001');
INSERT INTO triage.ranking (ranking_id, run_id, population_id, threshold_id, tie_break) VALUES
  ('00000000-0000-4000-8000-000000000502', '00000000-0000-4000-8000-000000000001', (SELECT population_id FROM corpus.population WHERE code = 'fixture_pop2'),
   '00000000-0000-4000-8000-000000000402', 'score desc'),
  ('00000000-0000-4000-8000-000000000503', '00000000-0000-4000-8000-000000000001', (SELECT population_id FROM corpus.population WHERE code = 'fixture_pop3'),
   '00000000-0000-4000-8000-000000000403', 'score desc');
INSERT INTO triage.assessment (assessment_id, run_id, ruling_id, step, repetition_idx, component_version_id, span_id, upstream_assessment_id, input_fingerprint,
                               in_suva_scope, outcome, score_0_100, score_source, mode, started_at)
VALUES ('00000000-0000-4000-8000-000000000611', '00000000-0000-4000-8000-000000000001', pg_temp.rid('8C_493/2025'), 'ranking', 1, pg_temp.cv('ranking'),
        pg_temp.span('ranking', '8C_493/2025'), '00000000-0000-4000-8000-000000000301', repeat('0', 64), 'in_scope', 'ok', 92, 'judged', 'REPLAY', now());
SELECT pg_temp.expect_error($q$
  INSERT INTO triage.ranking_entry (ranking_id, ruling_id, assessment_id, score_assessment_id, final_score_0_100, rank, above_threshold)
  VALUES ('00000000-0000-4000-8000-000000000502', pg_temp.rid('8C_493/2025'), '00000000-0000-4000-8000-000000000611',
          '00000000-0000-4000-8000-000000000201', 92, 1, true)$q$, 'not comparable');
SELECT pg_temp.expect_error($q$
  INSERT INTO triage.ranking_entry (ranking_id, ruling_id, assessment_id, score_assessment_id, final_score_0_100, rank, above_threshold)
  VALUES ('00000000-0000-4000-8000-000000000503', pg_temp.rid('8C_493/2025'), '00000000-0000-4000-8000-000000000611',
          '00000000-0000-4000-8000-000000000201', 92, 1, true)$q$, 'above_threshold must equal');
SELECT pg_temp.expect_error($q$
  INSERT INTO triage.ranking_entry (ranking_id, ruling_id, assessment_id, score_assessment_id, final_score_0_100, rank, above_threshold)
  VALUES ('00000000-0000-4000-8000-000000000503', pg_temp.rid('8C_493/2025'), '00000000-0000-4000-8000-000000000611',
          '00000000-0000-4000-8000-000000000201', 92, 1, false)$q$, 'must agree');
SELECT pg_temp.expect_error($q$
  INSERT INTO triage.ranking_entry (ranking_id, ruling_id, assessment_id, score_assessment_id, final_score_0_100, rank, above_threshold)
  VALUES ('00000000-0000-4000-8000-000000000501', pg_temp.rid('8C_307/2025'), '00000000-0000-4000-8000-000000000602',
          '00000000-0000-4000-8000-000000000202', 30, 9, false)$q$, 'duplicate key');

-- release gate: an unranked member, then a missing mandatory summary, block the release
SAVEPOINT unranked;
INSERT INTO corpus.ruling (docket, decision_date, language, bger_url, origin, created_by_run_id)
VALUES ('8C_1/2026', '2026-05-04', 'de', 'https://x', 'user_added', '00000000-0000-4000-8000-000000000001');
INSERT INTO corpus.population_member (population_id, ruling_id, basis)
VALUES ((SELECT population_id FROM corpus.population WHERE code = 'fixture_2026Q2_union'), pg_temp.rid('8C_1/2026'), 'decision_date');
SELECT pg_temp.expect_error($q$UPDATE ops.release SET is_current = true WHERE release_id = '00000000-0000-4000-8000-000000000801'$q$, 'unranked_member');
ROLLBACK TO SAVEPOINT unranked;

SAVEPOINT rejected;
UPDATE summ.summary_version SET quality_status = 'rejected' WHERE summary_version_id = '00000000-0000-4000-8000-000000000701';
SELECT pg_temp.expect_error($q$UPDATE ops.release SET is_current = true WHERE release_id = '00000000-0000-4000-8000-000000000801'$q$, 'missing_mandatory_summary');
ROLLBACK TO SAVEPOINT rejected;

UPDATE ops.release SET is_current = true WHERE release_id = '00000000-0000-4000-8000-000000000801';

DO $$
DECLARE
  steps text;
BEGIN
  ASSERT (SELECT count(*) FROM triage.v_current_release) = 1, 'one current release';
  ASSERT (SELECT label_origin FROM triage.v_scope_pipeline WHERE ruling_id = pg_temp.rid('8C_493/2025')) = 'release', 'label from the release';
  ASSERT (SELECT count(*) FROM triage.v_export_ranked) = 3, 'export holds every ranked ruling';
  ASSERT (SELECT string_agg(docket, ',' ORDER BY rank) FROM triage.v_export_ranked) = '8C_493/2025,8C_307/2025,8C_199/2026', 'export order';
  ASSERT (SELECT in_top10 AND in_top30 AND above_threshold FROM triage.v_export_ranked WHERE rank = 1), 'top marks of rank 1 (D-046)';
  SELECT string_agg(step::text || ':' || component_version, ',' ORDER BY hop) INTO steps
  FROM triage.v_scope_trace WHERE ruling_id = pg_temp.rid('8C_493/2025');
  ASSERT steps = 'ranking:V1.0.0,justification:V1.0.0,layer2_judge:V1.0.0,layer1_filter:V1.0.0', format('trace: %s', steps);
  ASSERT (SELECT p_yes FROM triage.v_scope_trace WHERE ruling_id = pg_temp.rid('8C_493/2025') AND step = 'layer2_judge') = 0.92, 'trace shows p_yes';
  ASSERT (SELECT declared_models ->> 'judge' FROM triage.v_scope_trace WHERE ruling_id = pg_temp.rid('8C_493/2025') AND step = 'layer2_judge')
         = 'fixture-model-large', 'trace shows the declared model';
  ASSERT (SELECT source_revision FROM triage.v_scope_trace WHERE ruling_id = pg_temp.rid('8C_493/2025') AND step = 'layer1_filter')
         = '35b17aa9c3fad71011b72f78f6ab79650ec0cf96', 'trace reaches the source snapshot';
END $$;
SELECT pg_temp.expect_error($q$
  INSERT INTO ops.release (profile_code, profile_version_id, ranking_id, is_current)
  VALUES ('default', (SELECT profile_version_id FROM ops.pipeline_profile_version WHERE profile_code = 'default'), '00000000-0000-4000-8000-000000000501', true)$q$,
  'duplicate key');

ROLLBACK;
