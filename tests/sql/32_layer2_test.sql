-- Layer 2 (docs/LAYER2.md): a judgement points to its own call (DDL-1), and the label reads only usable runs, along
-- the lineage of each ruling's current layer-1 decision (DDL-2). Synthetic ruling 8C_900/2026, no personal data.
BEGIN;
\ir _fixtures.sql

-- ---------------------------------------------------------------------------
-- DDL-1: triage.llm_judgement against its call (t31_call)
-- ---------------------------------------------------------------------------
-- a second layer-2 assessment of 8C_493/2025 in the fixture run (repetition 1), on layer-1 assessment 101
INSERT INTO triage.assessment (assessment_id, run_id, ruling_id, step, repetition_idx, component_version_id, span_id,
                               upstream_assessment_id, input_fingerprint, in_suva_scope, outcome, score_raw, score_0_100,
                               score_source, mode, started_at)
VALUES ('00000000-0000-4000-8000-000000000a01', '00000000-0000-4000-8000-000000000001', pg_temp.rid('8C_493/2025'),
        'layer2_judge', 1, pg_temp.cv('layer2_judge'), pg_temp.span('layer2_judge', '8C_493/2025'),
        '00000000-0000-4000-8000-000000000101', repeat('0', 64), 'potentially', 'ok', 2.4, 92, 'judged', 'REPLAY', now());

CREATE FUNCTION pg_temp.j(p_call text, p_prompt uuid, p_requested text, p_served text) RETURNS text LANGUAGE sql AS $f$
  SELECT format($s$INSERT INTO triage.llm_judgement (assessment_id, llm_call_id, prompt_version_id, requested_model, served_model,
                    question_language, p_yes, yes_no_in_top, text_chars_total, text_chars_sent, truncation)
                  VALUES ('00000000-0000-4000-8000-000000000a01', %L, %L, %L, %L, 'de', 0.92, true, 63, 63, 'none')$s$,
                p_call, p_prompt, p_requested, p_served) $f$;
CREATE FUNCTION pg_temp.p1() RETURNS uuid LANGUAGE sql AS
  $f$ SELECT prompt_version_id FROM ops.prompt_version WHERE role = 'layer2_judge.question' AND v_major = 1 $f$;

-- a prompt version no step version declares, and a layer-2 call that sent it
INSERT INTO ops.prompt_version (role, v_major, v_minor, v_patch, template_sha256, system_template, user_template, contains_suva_material,
                                status, bump_kind, previous_version_id, changelog)
VALUES ('layer2_judge.question', 2, 0, 0, repeat('9', 64), 'other system', 'other user', false, 'active', 'major', pg_temp.p1(), 'fixture');
INSERT INTO ops.llm_call (llm_call_id, run_id, span_id, ruling_id, step, purpose, language, prompt_version_id, cache_key, cache_hit, mode,
                          endpoint, model_role, requested_model, served_model, finish_reason, parsed_ok, attempt, started_at)
VALUES ('00000000-0000-4000-8000-000000000a90', '00000000-0000-4000-8000-000000000001', pg_temp.span('layer2_judge', '8C_493/2025'),
        pg_temp.rid('8C_493/2025'), 'layer2_judge', 'layer2_judge', 'de',
        (SELECT prompt_version_id FROM ops.prompt_version WHERE role = 'layer2_judge.question' AND v_major = 2),
        repeat('a', 64), false, 'REPLAY', '/chat/completions', 'judge', 'fixture-model-large', 'fixture-model-large', 'length', true, 1, now());
-- the same layer-2 call shape in another run (a finished one)
INSERT INTO ops.pipeline_run (run_id, profile_version_id, kind, mode, status, git_dirty, params_sha256, triggered_by, finished_at)
VALUES ('00000000-0000-4000-8000-000000000a04', (SELECT profile_version_id FROM ops.pipeline_profile_version WHERE profile_code = 'default'),
        'layer2', 'REPLAY', 'succeeded', false, repeat('6', 64), 'ci', now());
INSERT INTO ops.llm_call (llm_call_id, run_id, span_id, ruling_id, step, purpose, language, prompt_version_id, cache_key, cache_hit, mode,
                          endpoint, model_role, requested_model, served_model, finish_reason, parsed_ok, attempt, started_at)
VALUES ('00000000-0000-4000-8000-000000000a91', '00000000-0000-4000-8000-000000000a04',
        pg_temp.span('layer2_judge', '8C_493/2025', '00000000-0000-4000-8000-000000000a04'), pg_temp.rid('8C_493/2025'),
        'layer2_judge', 'layer2_judge', 'de', pg_temp.p1(), repeat('b', 64), false, 'REPLAY', '/chat/completions', 'judge',
        'fixture-model-large', 'fixture-model-large', 'length', true, 1, now());

SELECT pg_temp.expect_error(pg_temp.j('00000000-0000-4000-8000-000000000902', pg_temp.p1(), 'fixture-model-large', 'fixture-model-large'),
                            'not a layer2_judge call of the same run and ruling');   -- 902 judged 8C_307/2025
SELECT pg_temp.expect_error(pg_temp.j('00000000-0000-4000-8000-000000000903', pg_temp.p1(), 'fixture-model-large', 'fixture-model-large'),
                            'not a layer2_judge call of the same run and ruling');   -- 903 is the justification's call
SELECT pg_temp.expect_error(pg_temp.j('00000000-0000-4000-8000-000000000a91', pg_temp.p1(), 'fixture-model-large', 'fixture-model-large'),
                            'not a layer2_judge call of the same run and ruling');   -- a call of another run
SELECT pg_temp.expect_error(pg_temp.j('00000000-0000-4000-8000-000000000901',
                                      (SELECT prompt_version_id FROM ops.prompt_version WHERE role = 'layer2_judge.question' AND v_major = 2),
                                      'fixture-model-large', 'fixture-model-large'),
                            'is not the one call');                                   -- 901 sent prompt V1
SELECT pg_temp.expect_error(pg_temp.j('00000000-0000-4000-8000-000000000a90',
                                      (SELECT prompt_version_id FROM ops.prompt_version WHERE role = 'layer2_judge.question' AND v_major = 2),
                                      'fixture-model-large', 'fixture-model-large'),
                            'not a prompt of the assessment''s step version');        -- V2 is the call's, not the version's
SELECT pg_temp.expect_error(pg_temp.j('00000000-0000-4000-8000-000000000901', pg_temp.p1(), 'another-model', 'fixture-model-large'),
                            'requested model');
SELECT pg_temp.expect_error(pg_temp.j('00000000-0000-4000-8000-000000000901', pg_temp.p1(), 'fixture-model-large', 'another-model'),
                            'served model');
SELECT pg_temp.expect_error(pg_temp.j('00000000-0000-4000-8000-000000000901', pg_temp.p1(), 'fixture-model-large', NULL),
                            'served model');
-- the coherent row passes (its own call, the prompt it sent and its version declares, the same models)
DO $$ BEGIN EXECUTE pg_temp.j('00000000-0000-4000-8000-000000000901', pg_temp.p1(), 'fixture-model-large', 'fixture-model-large'); END $$;
DO $$ BEGIN
  ASSERT (SELECT count(*) FROM triage.llm_judgement WHERE assessment_id = '00000000-0000-4000-8000-000000000a01') = 1, 'coherent judgement stored';
END $$;

-- ---------------------------------------------------------------------------
-- DDL-2: the label reads usable runs only, along the current layer-1 decision
-- ---------------------------------------------------------------------------
INSERT INTO corpus.ruling (docket, decision_date, language, gegenstand, bger_url, origin, created_by_run_id) VALUES
  ('8C_900/2026', '2026-05-20', 'de', 'Unfallversicherung (Kausalzusammenhang)',
   'https://search.bger.ch/ext/eurospider/live/de/php/aza/http/index.php?lang=de&type=show_document&highlight_docid=aza://20-05-2026-8C_900-2026',
   'base_dataset', '00000000-0000-4000-8000-000000000001');

-- runs of the default profile: finished ones, one failed, one aborted, one partial, one eval (one assessment per run,
-- step and ruling: assessment_uq)
INSERT INTO ops.pipeline_run (run_id, profile_version_id, kind, mode, status, git_dirty, params_sha256, triggered_by, finished_at)
SELECT r.id::uuid, (SELECT profile_version_id FROM ops.pipeline_profile_version WHERE profile_code = 'default'),
       r.kind::ops.run_kind, 'REPLAY', r.status::ops.run_status, false, repeat('6', 64), 'ci', now()
FROM (VALUES ('00000000-0000-4000-8000-000000000b0a', 'layer1', 'succeeded'),
             ('00000000-0000-4000-8000-000000000b0b', 'layer1', 'succeeded'),
             ('00000000-0000-4000-8000-000000000b09', 'layer1', 'succeeded'),
             ('00000000-0000-4000-8000-000000000b10', 'layer2', 'succeeded'),
             ('00000000-0000-4000-8000-000000000b0f', 'layer2', 'failed'),
             ('00000000-0000-4000-8000-000000000b0c', 'layer2', 'aborted'),
             ('00000000-0000-4000-8000-000000000b0d', 'layer2', 'partial'),
             ('00000000-0000-4000-8000-000000000b0e', 'eval', 'succeeded')) AS r(id, kind, status);

-- one assessment, with an explicit creation time (a test runs in one transaction, where now() never moves)
CREATE FUNCTION pg_temp.a(p_id text, p_run text, p_step text, p_up text, p_scope text, p_score numeric, p_at int) RETURNS void
LANGUAGE sql AS $f$
  INSERT INTO triage.assessment (assessment_id, run_id, ruling_id, step, component_version_id, span_id, upstream_assessment_id,
                                 input_fingerprint, in_suva_scope, outcome, score_0_100, score_source, reason_code, mode, started_at, created_at)
  VALUES (p_id::uuid, p_run::uuid, pg_temp.rid('8C_900/2026'), p_step::ops.pipeline_step, pg_temp.cv(p_step),
          pg_temp.span(p_step, '8C_900/2026', p_run::uuid), p_up::uuid, repeat('0', 64), p_scope::ops.in_suva_scope, 'ok', p_score,
          CASE WHEN p_step = 'layer2_judge' THEN 'judged'::ops.score_source END,
          CASE WHEN p_scope = 'out_of_scope' THEN 'L1_DROP_RUBRIC_OUT' WHEN p_step = 'layer1_filter' THEN 'L1_KEEP_RUBRIC' END,
          'REPLAY', now(), now() + make_interval(secs => p_at)) $f$;
CREATE FUNCTION pg_temp.label() RETURNS text LANGUAGE sql AS
  $f$ SELECT step || ':' || right(assessment_id::text, 3) FROM triage.v_scope_pipeline WHERE ruling_id = pg_temp.rid('8C_900/2026') $f$;

SELECT pg_temp.a('00000000-0000-4000-8000-000000000c01', '00000000-0000-4000-8000-000000000b0a', 'layer1_filter', NULL, 'potentially', NULL, 1);
SELECT pg_temp.a('00000000-0000-4000-8000-000000000c11', '00000000-0000-4000-8000-000000000001', 'layer2_judge',
                 '00000000-0000-4000-8000-000000000c01', 'potentially', 80, 2);
DO $$ BEGIN ASSERT pg_temp.label() = 'layer2_judge:c11', format('judged on the current layer-1 decision: %s', pg_temp.label()); END $$;

-- later judgements from runs that did not finish usable, or from an eval run: never the label
SELECT pg_temp.a('00000000-0000-4000-8000-000000000c12', '00000000-0000-4000-8000-000000000b0f', 'layer2_judge',
                 '00000000-0000-4000-8000-000000000c01', 'potentially', 10, 3);
SELECT pg_temp.a('00000000-0000-4000-8000-000000000c13', '00000000-0000-4000-8000-000000000b0c', 'layer2_judge',
                 '00000000-0000-4000-8000-000000000c01', 'potentially', 11, 4);
SELECT pg_temp.a('00000000-0000-4000-8000-000000000c14', '00000000-0000-4000-8000-000000000b0e', 'layer2_judge',
                 '00000000-0000-4000-8000-000000000c01', 'potentially', 12, 5);
DO $$ BEGIN ASSERT pg_temp.label() = 'layer2_judge:c11', format('failed, aborted and eval runs ignored: %s', pg_temp.label()); END $$;

-- a partial run is usable: its later judgement is the label
SELECT pg_temp.a('00000000-0000-4000-8000-000000000c15', '00000000-0000-4000-8000-000000000b0d', 'layer2_judge',
                 '00000000-0000-4000-8000-000000000c01', 'potentially', 70, 6);
DO $$ BEGIN ASSERT pg_temp.label() = 'layer2_judge:c15', format('a partial run counts: %s', pg_temp.label()); END $$;

-- a newer layer-1 decision makes every judgement of the older one stale: the label falls back to layer 1
SELECT pg_temp.a('00000000-0000-4000-8000-000000000c02', '00000000-0000-4000-8000-000000000b0b', 'layer1_filter', NULL, 'out_of_scope', 0, 7);
DO $$ BEGIN ASSERT pg_temp.label() = 'layer1_filter:c02', format('stale judgements ignored: %s', pg_temp.label()); END $$;

-- a judgement with no layer-1 root never forms the label, even the latest one
SELECT pg_temp.a('00000000-0000-4000-8000-000000000c16', '00000000-0000-4000-8000-000000000a04', 'layer2_judge', NULL, 'potentially', 99, 8);
DO $$ BEGIN ASSERT pg_temp.label() = 'layer1_filter:c02', format('no layer-1 root, no label: %s', pg_temp.label()); END $$;

-- and a judgement on the current decision is the label again
SELECT pg_temp.a('00000000-0000-4000-8000-000000000c03', '00000000-0000-4000-8000-000000000b09', 'layer1_filter', NULL, 'potentially', NULL, 9);
SELECT pg_temp.a('00000000-0000-4000-8000-000000000c17', '00000000-0000-4000-8000-000000000b10', 'layer2_judge',
                 '00000000-0000-4000-8000-000000000c03', 'potentially', 55, 10);
DO $$ BEGIN ASSERT pg_temp.label() = 'layer2_judge:c17', format('judged on the new current decision: %s', pg_temp.label()); END $$;

-- the fixture's rulings keep their labels (furthest step of the finished fixture run)
DO $$ BEGIN
  ASSERT (SELECT pipeline_label || '|' || step FROM triage.v_scope_pipeline WHERE ruling_id = pg_temp.rid('8C_493/2025')) = 'in_scope|ranking',
         'fixture label unchanged';
END $$;

ROLLBACK;
