-- Shared fixture for tests/sql/*_test.sql (included with \ir inside each test's transaction, then rolled back).
-- Three real rulings of Q2/2026 (HF voilaj/swiss-caselaw, commit 35b17aa9): 8C_493/2025 (de), 8C_307/2025 (fr),
-- 8C_199/2026 (it). Their texts here are short synthetic stand-ins: no personal data (D-038), no Suva text (D-031).
-- Happy path: layer 1 -> layer 2 -> justification -> ranking at a threshold of 50 -> a suva_house summary of the
-- in-scope ruling -> a release (not current yet).

SET LOCAL app.actor = 'test';
SET LOCAL client_min_messages = warning;

CREATE FUNCTION pg_temp.expect_error(p_sql text, p_pattern text) RETURNS void LANGUAGE plpgsql AS $f$
BEGIN
  BEGIN
    EXECUTE p_sql;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM !~* p_pattern THEN
      RAISE EXCEPTION 'expected an error matching "%", got: %', p_pattern, SQLERRM;
    END IF;
    RETURN;
  END;
  RAISE EXCEPTION 'expected an error matching "%", but this succeeded: %', p_pattern, p_sql;
END $f$;

CREATE FUNCTION pg_temp.rid(p_docket text) RETURNS uuid LANGUAGE sql AS
  $f$ SELECT ruling_id FROM corpus.ruling WHERE docket = p_docket $f$;
CREATE FUNCTION pg_temp.cv(p_step text, p_major int DEFAULT 1, p_minor int DEFAULT 0) RETURNS uuid LANGUAGE sql AS
  $f$ SELECT component_version_id FROM ops.component_version WHERE step = p_step::ops.pipeline_step AND v_major = p_major AND v_minor = p_minor AND v_patch = 0 $f$;
CREATE FUNCTION pg_temp.rule(p_code text) RETURNS uuid LANGUAGE sql AS
  $f$ SELECT rule_id FROM ops.rule WHERE rule_code = p_code AND v_major = 1 $f$;
CREATE FUNCTION pg_temp.text_of(p_docket text) RETURNS uuid LANGUAGE sql AS
  $f$ SELECT text_id FROM corpus.ruling_text WHERE ruling_id = pg_temp.rid(p_docket) AND is_primary $f$;
CREATE FUNCTION pg_temp.seg(p_docket text) RETURNS uuid LANGUAGE sql AS
  $f$ SELECT segmentation_id FROM corpus.segmentation WHERE text_id = pg_temp.text_of(p_docket) AND is_primary $f$;
CREATE FUNCTION pg_temp.cons(p_docket text, p_ordinal int) RETURNS uuid LANGUAGE sql AS
  $f$ SELECT consideration_id FROM corpus.consideration WHERE segmentation_id = pg_temp.seg(p_docket) AND ordinal = p_ordinal $f$;
CREATE FUNCTION pg_temp.span(p_step text, p_docket text, p_run uuid DEFAULT '00000000-0000-4000-8000-000000000001') RETURNS uuid LANGUAGE sql AS $f$
  INSERT INTO ops.span (run_id, step, operation, ruling_id, component_version_id, status, started_at, ended_at)
  VALUES (p_run, p_step::ops.pipeline_step, p_step || '.fixture', pg_temp.rid(p_docket), pg_temp.cv(p_step), 'ok', now(), now())
  RETURNING span_id $f$;

-- registry -------------------------------------------------------------------
INSERT INTO ops.source_snapshot (snapshot_id, source, revision, uri, file_sha256, retrieved_at)
VALUES ('00000000-0000-4000-8000-0000000000a1', 'hf_bger', '35b17aa9c3fad71011b72f78f6ab79650ec0cf96',
        'hf://datasets/voilaj/swiss-caselaw/data/bger.parquet', repeat('d', 64), now());

INSERT INTO ops.json_schema (subject, schema_code, v_major, v_minor, v_patch, json_schema, template, schema_sha256, status, bump_kind, changelog)
VALUES ('step_config',     'test.step_config',     1, 0, 0, '{"type": "object"}', '{}', repeat('1', 64), 'active', 'initial', 'fixture'),
       ('rule_definition', 'test.rule_definition', 1, 0, 0, '{"type": "object"}', '{}', repeat('2', 64), 'active', 'initial', 'fixture'),
       ('preset_config',   'test.preset_config',   1, 0, 0, '{"type": "object"}', '{}', repeat('3', 64), 'active', 'initial', 'fixture');

INSERT INTO ops.model (gateway_id, family, size_label, allowed, source_snapshot_id)
VALUES ('fixture-model-large', 'fixture', 'L', true, '00000000-0000-4000-8000-0000000000a1');

INSERT INTO ops.component_version (step, name, v_major, v_minor, v_patch, config_schema_id, config, config_sha256, code_path, code_sha256, status, bump_kind, changelog)
SELECT s::ops.pipeline_step, 'fixture ' || s, 1, 0, 0,
       (SELECT json_schema_id FROM ops.json_schema WHERE schema_code = 'test.step_config'),
       '{}', repeat('4', 64), 'src/fixture.py', repeat('5', 64), 'active', 'initial', 'fixture'
FROM unnest(ARRAY['segment', 'parse', 'layer1_filter', 'layer2_judge', 'justification', 'ranking', 'summarise', 'verify']) AS s;

INSERT INTO ops.component_version_model (component_version_id, model_role, model_id)
SELECT pg_temp.cv('layer2_judge'), 'judge', model_id FROM ops.model WHERE gateway_id = 'fixture-model-large';
-- the question prompt, declared by the layer-2 version: a judgement's prompt is the one its call sent (DDL-1). Bound
-- before a profile pins the version: a pinned version's models and prompts are sealed
INSERT INTO ops.prompt_version (role, v_major, v_minor, v_patch, template_sha256, system_template, user_template, contains_suva_material, status, bump_kind, changelog)
VALUES ('layer2_judge.question', 1, 0, 0, repeat('8', 64), 'fixture system', 'fixture user', false, 'active', 'initial', 'fixture');
INSERT INTO ops.component_version_prompt (component_version_id, prompt_role, prompt_version_id)
SELECT pg_temp.cv('layer2_judge'), 'question', prompt_version_id FROM ops.prompt_version WHERE role = 'layer2_judge.question';

INSERT INTO ops.rule (step, rule_code, v_major, v_minor, v_patch, kind, definition, definition_schema_id, reason_code, status, bump_kind, changelog)
SELECT r.step::ops.pipeline_step, r.code, 1, 0, 0, r.kind::ops.rule_kind, '{}',
       (SELECT json_schema_id FROM ops.json_schema WHERE schema_code = 'test.rule_definition'), r.code, 'active', 'initial', 'fixture'
FROM (VALUES ('layer1_filter', 'L1_KEEP_RUBRIC', 'keep'), ('layer1_filter', 'L1_DROP_RUBRIC_OUT', 'drop'),
             ('verify', 'V1_IDS_IN_SET', 'check'), ('ranking', 'RANK_BELOW_THRESHOLD', 'drop')) AS r(step, code, kind);

INSERT INTO ops.component_version_rule (component_version_id, rule_id, ordinal) VALUES
  (pg_temp.cv('layer1_filter'), pg_temp.rule('L1_KEEP_RUBRIC'), 1),
  (pg_temp.cv('layer1_filter'), pg_temp.rule('L1_DROP_RUBRIC_OUT'), 2),
  (pg_temp.cv('verify'), pg_temp.rule('V1_IDS_IN_SET'), 1),
  (pg_temp.cv('ranking'), pg_temp.rule('RANK_BELOW_THRESHOLD'), 1);

INSERT INTO ops.pipeline_profile (profile_code, name, is_default) VALUES ('default', 'Default pipeline', true);
INSERT INTO ops.pipeline_profile_version (profile_code, v_major, v_minor, v_patch, status, bump_kind, changelog)
VALUES ('default', 1, 0, 0, 'active', 'initial', 'fixture');
INSERT INTO ops.pipeline_profile_step (profile_version_id, step, component_version_id)
SELECT pv.profile_version_id, cv.step, cv.component_version_id
FROM ops.pipeline_profile_version pv CROSS JOIN ops.component_version cv
WHERE pv.profile_code = 'default';

-- a finished run: only succeeded or partial runs form the label (DDL-2)
INSERT INTO ops.pipeline_run (run_id, profile_version_id, kind, mode, status, git_dirty, params_sha256, triggered_by, finished_at)
VALUES ('00000000-0000-4000-8000-000000000001',
        (SELECT profile_version_id FROM ops.pipeline_profile_version WHERE profile_code = 'default'),
        'full', 'REPLAY', 'succeeded', false, repeat('6', 64), 'ci', now());

-- corpus ---------------------------------------------------------------------
INSERT INTO corpus.ruling (docket, decision_date, language, gegenstand, bger_url, origin, created_by_run_id) VALUES
  ('8C_493/2025', '2026-04-02', 'de', 'Unfallversicherung (Rückfall, Invalidenrente)',
   'https://search.bger.ch/ext/eurospider/live/de/php/aza/http/index.php?lang=de&type=show_document&highlight_docid=aza://02-04-2026-8C_493-2025',
   'base_dataset', '00000000-0000-4000-8000-000000000001'),
  ('8C_307/2025', '2026-04-08', 'fr', 'Assurance-accidents (notification de la décision; rechute)',
   'https://search.bger.ch/ext/eurospider/live/de/php/aza/http/index.php?lang=fr&type=show_document&highlight_docid=aza://08-04-2026-8C_307-2025',
   'base_dataset', '00000000-0000-4000-8000-000000000001'),
  ('8C_199/2026', '2026-04-27', 'it', 'Assicurazione contro gli infortuni (presupposto processuale)',
   'https://search.bger.ch/ext/eurospider/live/de/php/aza/http/index.php?lang=it&type=show_document&highlight_docid=aza://27-04-2026-8C_199-2026',
   'base_dataset', '00000000-0000-4000-8000-000000000001');

INSERT INTO corpus.ruling_text (ruling_id, source, content, content_sha256, is_primary, snapshot_id)
SELECT pg_temp.rid(t.docket), 'hf', t.c, encode(sha256(convert_to(t.c, 'UTF8')), 'hex'), true, '00000000-0000-4000-8000-0000000000a1'
FROM (VALUES
  ('8C_493/2025', 'Erwägungen: 1. Erste Erwägung. 1.1 Unterpunkt. 2. Zweite Erwägung.'),
  ('8C_307/2025', 'Considérant en droit: 1. Premier considérant. 1.1 Sous-point. 2. Second considérant.'),
  ('8C_199/2026', 'Diritto: 1. Primo considerando. 1.1 Sottopunto. 2. Secondo considerando.')) AS t(docket, c);

INSERT INTO corpus.segmentation (text_id, component_version_id, method, status, consideration_count, expected_count, coverage_ratio, offsets_found_ratio, is_primary, created_by_run_id)
SELECT t.text_id, pg_temp.cv('segment'), 'hf_erwaegungen', 'ok', 3, 3, 1, 1, true, '00000000-0000-4000-8000-000000000001'
FROM corpus.ruling_text t;

INSERT INTO corpus.consideration (segmentation_id, ordinal, e_number, depth, content, content_sha256)
SELECT g.segmentation_id, c.ordinal, c.e_number, c.depth, c.content, encode(sha256(convert_to(c.content, 'UTF8')), 'hex')
FROM corpus.segmentation g
CROSS JOIN (VALUES (1, '1', 1, 'First consideration.'), (3, '2', 1, 'Second consideration.')) AS c(ordinal, e_number, depth, content);
INSERT INTO corpus.consideration (segmentation_id, ordinal, e_number, depth, parent_consideration_id, content, content_sha256)
SELECT c1.segmentation_id, 2, '1.1', 2, c1.consideration_id, 'Sub-point.', encode(sha256(convert_to('Sub-point.', 'UTF8')), 'hex')
FROM corpus.consideration c1 WHERE c1.ordinal = 1;
INSERT INTO corpus.consideration (segmentation_id, ordinal, e_number, depth, content, content_sha256)
VALUES (pg_temp.seg('8C_493/2025'), 4, '0', 0, 'Unnumbered reasoning.', encode(sha256(convert_to('Unnumbered reasoning.', 'UTF8')), 'hex'));

INSERT INTO corpus.population (code, quarter, definition, role, built_by_run_id)
VALUES ('fixture_2026Q2_union', '2026Q2', 'union', 'target', '00000000-0000-4000-8000-000000000001');
INSERT INTO corpus.population_member (population_id, ruling_id, basis)
SELECT p.population_id, r.ruling_id, 'decision_date' FROM corpus.population p CROSS JOIN corpus.ruling r WHERE p.code = 'fixture_2026Q2_union';

-- layer 1 ---------------------------------------------------------------------
INSERT INTO triage.assessment (assessment_id, run_id, ruling_id, step, component_version_id, span_id, input_text_id, input_fingerprint,
                               in_suva_scope, outcome, score_raw, score_0_100, score_source, reason_code, explanation_de, mode, started_at) VALUES
  ('00000000-0000-4000-8000-000000000101', '00000000-0000-4000-8000-000000000001', pg_temp.rid('8C_493/2025'), 'layer1_filter',
   pg_temp.cv('layer1_filter'), pg_temp.span('layer1_filter', '8C_493/2025'), pg_temp.text_of('8C_493/2025'), repeat('a', 64),
   'potentially', 'ok', NULL, NULL, NULL, 'L1_KEEP_RUBRIC', 'Vorauswahl bestanden: Rechtsgebiet in der Liste der Abteilung.', 'REPLAY', now()),
  ('00000000-0000-4000-8000-000000000102', '00000000-0000-4000-8000-000000000001', pg_temp.rid('8C_307/2025'), 'layer1_filter',
   pg_temp.cv('layer1_filter'), pg_temp.span('layer1_filter', '8C_307/2025'), pg_temp.text_of('8C_307/2025'), repeat('b', 64),
   'potentially', 'ok', NULL, NULL, NULL, 'L1_KEEP_RUBRIC', 'Vorauswahl bestanden: Rechtsgebiet in der Liste der Abteilung.', 'REPLAY', now()),
  ('00000000-0000-4000-8000-000000000103', '00000000-0000-4000-8000-000000000001', pg_temp.rid('8C_199/2026'), 'layer1_filter',
   pg_temp.cv('layer1_filter'), pg_temp.span('layer1_filter', '8C_199/2026'), pg_temp.text_of('8C_199/2026'), repeat('c', 64),
   'out_of_scope', 'ok', 0, 0, 'net', 'L1_DROP_RUBRIC_OUT', 'Keine Regel der Vorauswahl trifft zu.', 'REPLAY', now());

-- the rule ledger (F-01): every enabled rule of the version, at its ordinal, whatever it did (complete at commit, t50_ledger)
INSERT INTO triage.assessment_reason (assessment_id, ordinal, rule_id, reason_code, effect, outcome, evidence_field, examined_value, matched_text) VALUES
  ('00000000-0000-4000-8000-000000000101', 1, pg_temp.rule('L1_KEEP_RUBRIC'), 'L1_KEEP_RUBRIC', 'keep', 'fired', 'rubric:gegenstand', 'Unfallversicherung', 'Unfallversicherung'),
  ('00000000-0000-4000-8000-000000000101', 2, pg_temp.rule('L1_DROP_RUBRIC_OUT'), 'L1_DROP_RUBRIC_OUT', 'drop', 'not_fired', 'rubric:gegenstand', 'Unfallversicherung', NULL),
  ('00000000-0000-4000-8000-000000000102', 1, pg_temp.rule('L1_KEEP_RUBRIC'), 'L1_KEEP_RUBRIC', 'keep', 'fired', 'rubric:gegenstand', 'Assurance-accidents', 'Assurance-accidents'),
  ('00000000-0000-4000-8000-000000000102', 2, pg_temp.rule('L1_DROP_RUBRIC_OUT'), 'L1_DROP_RUBRIC_OUT', 'drop', 'not_fired', 'rubric:gegenstand', 'Assurance-accidents', NULL),
  ('00000000-0000-4000-8000-000000000103', 1, pg_temp.rule('L1_KEEP_RUBRIC'), 'L1_KEEP_RUBRIC', 'keep', 'not_fired', 'rubric:gegenstand', 'Assicurazione contro gli infortuni', NULL),
  ('00000000-0000-4000-8000-000000000103', 2, pg_temp.rule('L1_DROP_RUBRIC_OUT'), 'L1_DROP_RUBRIC_OUT', 'drop', 'fired', 'rubric:gegenstand', 'Assicurazione contro gli infortuni', 'Assicurazione contro gli infortuni');

-- layer 2 ---------------------------------------------------------------------

INSERT INTO ops.llm_call (llm_call_id, run_id, span_id, ruling_id, step, purpose, language, prompt_version_id, cache_key, cache_hit, mode, endpoint,
                          model_role, requested_model, served_model, finish_reason, parsed_ok, attempt, input_tokens, output_tokens, latency_ms, started_at)
SELECT c.id::uuid, '00000000-0000-4000-8000-000000000001', pg_temp.span(c.step, c.docket), pg_temp.rid(c.docket), c.step::ops.pipeline_step,
       c.purpose, c.lang::ops.lang_code,
       CASE WHEN c.step = 'layer2_judge' THEN (SELECT prompt_version_id FROM ops.prompt_version WHERE role = 'layer2_judge.question') END,
       repeat(c.k, 64), false, 'REPLAY', '/chat/completions', c.role::ops.model_role,
       'fixture-model-large', 'fixture-model-large', 'stop', true, 1, 5000, 1, 600, now()
FROM (VALUES
  ('00000000-0000-4000-8000-000000000901', 'layer2_judge',  '8C_493/2025', 'layer2_judge',  'de', '7', 'judge'),
  ('00000000-0000-4000-8000-000000000902', 'layer2_judge',  '8C_307/2025', 'layer2_judge',  'de', '8', 'judge'),
  ('00000000-0000-4000-8000-000000000903', 'justification', '8C_493/2025', 'justification', 'de', '9', 'judge'),
  ('00000000-0000-4000-8000-000000000904', 'summarise',     '8C_493/2025', 'summary',       'de', 'e', 'generator'),
  ('00000000-0000-4000-8000-000000000905', 'summarise',     '8C_493/2025', 'summary',       'fr', 'f', 'generator')
) AS c(id, step, docket, purpose, lang, k, role);

INSERT INTO triage.assessment (assessment_id, run_id, ruling_id, step, component_version_id, span_id, upstream_assessment_id, input_text_id,
                               input_segmentation_id, input_fingerprint, in_suva_scope, outcome, score_raw, score_0_100, score_source, mode, started_at) VALUES
  ('00000000-0000-4000-8000-000000000201', '00000000-0000-4000-8000-000000000001', pg_temp.rid('8C_493/2025'), 'layer2_judge',
   pg_temp.cv('layer2_judge'), pg_temp.span('layer2_judge', '8C_493/2025'), '00000000-0000-4000-8000-000000000101',
   pg_temp.text_of('8C_493/2025'), pg_temp.seg('8C_493/2025'), repeat('d', 64), 'potentially', 'ok', 0.92, 92, 'judged', 'REPLAY', now()),
  ('00000000-0000-4000-8000-000000000202', '00000000-0000-4000-8000-000000000001', pg_temp.rid('8C_307/2025'), 'layer2_judge',
   pg_temp.cv('layer2_judge'), pg_temp.span('layer2_judge', '8C_307/2025'), '00000000-0000-4000-8000-000000000102',
   pg_temp.text_of('8C_307/2025'), pg_temp.seg('8C_307/2025'), repeat('e', 64), 'potentially', 'ok', 0.30, 30, 'judged', 'REPLAY', now());


INSERT INTO triage.llm_judgement (assessment_id, llm_call_id, prompt_version_id, requested_model, served_model, question_language,
                                  logprob_yes, logprob_no, p_yes, yes_no_in_top, text_chars_total, text_chars_sent, truncation)
SELECT j.a::uuid, j.c::uuid, (SELECT prompt_version_id FROM ops.prompt_version WHERE role = 'layer2_judge.question'),
       'fixture-model-large', 'fixture-model-large', 'de', j.ly, j.ln, j.p, true, 63, 63, 'none'
FROM (VALUES ('00000000-0000-4000-8000-000000000201', '00000000-0000-4000-8000-000000000901', -0.08, -2.5, 0.92),
             ('00000000-0000-4000-8000-000000000202', '00000000-0000-4000-8000-000000000902', -1.2, -0.36, 0.30)) AS j(a, c, ly, ln, p);

-- justification ------------------------------------------------------------------
INSERT INTO triage.assessment (assessment_id, run_id, ruling_id, step, component_version_id, span_id, upstream_assessment_id, input_text_id,
                               input_segmentation_id, input_fingerprint, in_suva_scope, outcome, explanation_de, mode, started_at)
VALUES ('00000000-0000-4000-8000-000000000301', '00000000-0000-4000-8000-000000000001', pg_temp.rid('8C_493/2025'), 'justification',
        pg_temp.cv('justification'), pg_temp.span('justification', '8C_493/2025'), '00000000-0000-4000-8000-000000000201',
        pg_temp.text_of('8C_493/2025'), pg_temp.seg('8C_493/2025'), repeat('f', 64), 'potentially', 'ok',
        'Rückfall in der Unfallversicherung: Kausalzusammenhang.', 'REPLAY', now());
INSERT INTO triage.justification (assessment_id, llm_call_id, json_valid, key_statement, offered_consideration_count, party_check_status)
VALUES ('00000000-0000-4000-8000-000000000301', '00000000-0000-4000-8000-000000000903', true, 'Key statement.', 3, 'pass');
INSERT INTO triage.assessment_evidence (assessment_id, consideration_id, role)
VALUES ('00000000-0000-4000-8000-000000000301', pg_temp.cons('8C_493/2025', 1), 'supports');

-- ranking ---------------------------------------------------------------------------
INSERT INTO triage.threshold (threshold_id, ranking_component_version_id, scorer_component_version_id, layer1_component_version_id,
                              value_0_100, chosen_on_population_id, policy, frozen_at, created_by_run_id)
VALUES ('00000000-0000-4000-8000-000000000401', pg_temp.cv('ranking'), pg_temp.cv('layer2_judge'), pg_temp.cv('layer1_filter'), 50,
        (SELECT population_id FROM corpus.population WHERE code = 'fixture_2026Q2_union'), 'fixture', now(), '00000000-0000-4000-8000-000000000001');
INSERT INTO triage.ranking (ranking_id, run_id, population_id, threshold_id, tie_break)
VALUES ('00000000-0000-4000-8000-000000000501', '00000000-0000-4000-8000-000000000001',
        (SELECT population_id FROM corpus.population WHERE code = 'fixture_2026Q2_union'), '00000000-0000-4000-8000-000000000401', 'score desc, docket');

INSERT INTO triage.assessment (assessment_id, run_id, ruling_id, step, component_version_id, span_id, upstream_assessment_id, input_fingerprint,
                               in_suva_scope, outcome, score_0_100, score_source, reason_code, explanation_de, mode, started_at) VALUES
  ('00000000-0000-4000-8000-000000000601', '00000000-0000-4000-8000-000000000001', pg_temp.rid('8C_493/2025'), 'ranking', pg_temp.cv('ranking'),
   pg_temp.span('ranking', '8C_493/2025'), '00000000-0000-4000-8000-000000000301', repeat('1', 64), 'in_scope', 'ok', 92, 'judged',
   'RANK_AT_OR_ABOVE_THRESHOLD', 'Relevant: Rückfall in der Unfallversicherung.', 'REPLAY', now()),
  ('00000000-0000-4000-8000-000000000602', '00000000-0000-4000-8000-000000000001', pg_temp.rid('8C_307/2025'), 'ranking', pg_temp.cv('ranking'),
   pg_temp.span('ranking', '8C_307/2025'), '00000000-0000-4000-8000-000000000202', repeat('2', 64), 'out_of_scope', 'ok', 30, 'judged',
   'RANK_BELOW_THRESHOLD', 'Relevanzwert unter der Schwelle.', 'REPLAY', now()),
  ('00000000-0000-4000-8000-000000000603', '00000000-0000-4000-8000-000000000001', pg_temp.rid('8C_199/2026'), 'ranking', pg_temp.cv('ranking'),
   pg_temp.span('ranking', '8C_199/2026'), '00000000-0000-4000-8000-000000000103', repeat('3', 64), 'out_of_scope', 'ok', 0, 'net',
   'RANK_BELOW_THRESHOLD', 'Durch die Vorauswahl ausgeschlossen.', 'REPLAY', now());

INSERT INTO triage.assessment_reason (assessment_id, ordinal, rule_id, reason_code, effect, outcome, evidence_field, examined_value) VALUES
  ('00000000-0000-4000-8000-000000000601', 1, pg_temp.rule('RANK_BELOW_THRESHOLD'), 'RANK_BELOW_THRESHOLD', 'drop', 'not_fired', 'score_0_100', '92'),
  ('00000000-0000-4000-8000-000000000602', 1, pg_temp.rule('RANK_BELOW_THRESHOLD'), 'RANK_BELOW_THRESHOLD', 'drop', 'fired', 'score_0_100', '30'),
  ('00000000-0000-4000-8000-000000000603', 1, pg_temp.rule('RANK_BELOW_THRESHOLD'), 'RANK_BELOW_THRESHOLD', 'drop', 'fired', 'score_0_100', '0');

INSERT INTO triage.ranking_entry (ranking_id, ruling_id, assessment_id, score_assessment_id, final_score_0_100, rank, above_threshold) VALUES
  ('00000000-0000-4000-8000-000000000501', pg_temp.rid('8C_493/2025'), '00000000-0000-4000-8000-000000000601', '00000000-0000-4000-8000-000000000201', 92, 1, true),
  ('00000000-0000-4000-8000-000000000501', pg_temp.rid('8C_307/2025'), '00000000-0000-4000-8000-000000000602', '00000000-0000-4000-8000-000000000202', 30, 2, false),
  ('00000000-0000-4000-8000-000000000501', pg_temp.rid('8C_199/2026'), '00000000-0000-4000-8000-000000000603', '00000000-0000-4000-8000-000000000103', 0, 3, false);

-- summary of the in-scope ruling (suva_house) ---------------------------------------
INSERT INTO summ.preset_version (preset_code, v_major, v_minor, v_patch, config_schema_id, config, config_sha256, status, bump_kind, changelog)
VALUES ('suva_house', 1, 0, 0, (SELECT json_schema_id FROM ops.json_schema WHERE schema_code = 'test.preset_config'), '{}', repeat('9', 64),
        'active', 'initial', 'fixture');
INSERT INTO summ.summary (ruling_id, preset_code) VALUES (pg_temp.rid('8C_493/2025'), 'suva_house');
INSERT INTO summ.summary_version (summary_version_id, summary_id, version_no, origin, preset_version_id, component_version_id,
                                  source_segmentation_id, creator_kind, creator_run_id, quality_status, is_current, mode)
VALUES ('00000000-0000-4000-8000-000000000701',
        (SELECT summary_id FROM summ.summary WHERE ruling_id = pg_temp.rid('8C_493/2025') AND preset_code = 'suva_house'), NULL, 'generated',
        (SELECT preset_version_id FROM summ.preset_version WHERE preset_code = 'suva_house'), pg_temp.cv('summarise'),
        pg_temp.seg('8C_493/2025'), 'pipeline', '00000000-0000-4000-8000-000000000001', 'verified', true, 'REPLAY');
INSERT INTO summ.summary_text (summary_text_id, summary_version_id, language, title_line, body, word_count, paragraph_count, llm_call_id) VALUES
  ('00000000-0000-4000-8000-000000000711', '00000000-0000-4000-8000-000000000701', 'de', 'BGer-Urteil 8C_493/2025 vom 2. April 2026',
   'Synthetischer Satz (E. 1).', 4, 1, '00000000-0000-4000-8000-000000000904'),
  ('00000000-0000-4000-8000-000000000712', '00000000-0000-4000-8000-000000000701', 'fr', 'Arrêt du TF 8C_493/2025 du 2 avril 2026',
   'Phrase synthétique (consid. 1).', 4, 1, '00000000-0000-4000-8000-000000000905');
INSERT INTO summ.summary_claim (claim_id, summary_text_id, ordinal, paragraph_no, section, model_text, rendered_text, status) VALUES
  ('00000000-0000-4000-8000-000000000721', '00000000-0000-4000-8000-000000000711', 1, 1, 'law', 'Synthetischer Satz (c1).', 'Synthetischer Satz (E. 1).', 'verified'),
  ('00000000-0000-4000-8000-000000000722', '00000000-0000-4000-8000-000000000712', 1, 1, 'law', 'Phrase synthétique (c1).', 'Phrase synthétique (consid. 1).', 'verified');
INSERT INTO summ.claim_citation (claim_id, consideration_id) VALUES
  ('00000000-0000-4000-8000-000000000721', pg_temp.cons('8C_493/2025', 1)),
  ('00000000-0000-4000-8000-000000000722', pg_temp.cons('8C_493/2025', 1));

-- release (not current yet) ----------------------------------------------------------
INSERT INTO ops.release (release_id, profile_code, profile_version_id, ranking_id, created_by_actor)
VALUES ('00000000-0000-4000-8000-000000000801', 'default',
        (SELECT profile_version_id FROM ops.pipeline_profile_version WHERE profile_code = 'default'),
        '00000000-0000-4000-8000-000000000501', 'test');
