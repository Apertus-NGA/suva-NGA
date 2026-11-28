-- Rule-evaluation ledger (F-01, F-02, F-10, F-13): every enabled rule of the step version has exactly one row,
-- at its ordinal, with its kind as effect; full-text evidence is the exact slice of the stored text, with offsets
-- on full text only; a blocked keep names another enabled flag that fired; not_applicable says why, text_absent only
-- without a text; the deferred check t50_ledger ties the layer-1 decision to the fired rules (every drop, whatever
-- its outcome); the rule set of a used or pinned version is sealed. A ledger is also sealed once its assessment is
-- committed: that needs two transactions, so tests/test_db_ledger_sealed.py covers it. Deferred checks are forced
-- with SET CONSTRAINTS ALL IMMEDIATE inside each case. Views: triage.v_layer1_ledger, triage.v_scope_trace counts.
-- Seed labels (F-03).
BEGIN;
\ir _fixtures.sql

-- the fixture's ledgers are complete (layer 1 and ranking); layer-2 and justification versions have no rule
SET CONSTRAINTS ALL IMMEDIATE;
SET CONSTRAINTS ALL DEFERRED;

-- a layer-1 version shaped like the registry's: nine rules in the registry order, a tenth one disabled ------------
INSERT INTO ops.rule (step, rule_code, v_major, v_minor, v_patch, kind, definition, definition_schema_id, reason_code, status, bump_kind, changelog)
SELECT 'layer1_filter', r.code, 1, 0, 0, r.kind::ops.rule_kind, jsonb_build_object('check', r.chk),
       (SELECT json_schema_id FROM ops.json_schema WHERE schema_code = 'test.rule_definition'), r.code, 'active', 'initial', 'fixture'
FROM (VALUES ('L1_KEEP_RUBRIC_MISSING', 'keep', 'court_rubric_missing'), ('L1_KEEP_ACCIDENT_TERM', 'keep', 'text_accident_term'),
             ('L1_KEEP_CONTRACT_TERM', 'keep', 'text_contract_term'), ('L1_FLAG_CLOSED_RUBRIC', 'flag', 'text_contract_term_blocked'),
             ('L1_DROP_WRONG_COURT', 'drop', 'court_not_listed'), ('L1_DROP_WRONG_LETTER', 'drop', 'letter_not_listed'),
             ('L1_SIGNAL_RUBRIC_FROM_TITLE', 'signal', 'rubric_from_gegenstand'), ('L1_KEEP_TEXT_UNAVAILABLE', 'keep', 'text_unavailable')
     ) AS r(code, kind, chk);

INSERT INTO ops.component_version (step, name, v_major, v_minor, v_patch, config_schema_id, config, config_sha256, code_path, code_sha256,
                                  status, bump_kind, previous_version_id, changelog, decision_ref, validation_ref)
VALUES ('layer1_filter', 'fixture layer-1 ledger', 1, 1, 0, (SELECT json_schema_id FROM ops.json_schema WHERE schema_code = 'test.step_config'),
        '{}', repeat('4', 64), 'src/fixture.py', repeat('5', 64), 'active', 'minor', pg_temp.cv('layer1_filter'), 'nine rules and a disabled one',
        'D-073', 'expected/layer1/V1.1.0.json');
INSERT INTO ops.component_version_rule (component_version_id, rule_id, ordinal, enabled)
SELECT pg_temp.cv('layer1_filter', 1, 1), pg_temp.rule(r.code), r.ord, r.code <> 'L1_KEEP_TEXT_UNAVAILABLE'
FROM (VALUES ('L1_KEEP_RUBRIC', 1), ('L1_KEEP_RUBRIC_MISSING', 2), ('L1_KEEP_ACCIDENT_TERM', 3), ('L1_KEEP_CONTRACT_TERM', 4),
             ('L1_FLAG_CLOSED_RUBRIC', 5), ('L1_DROP_WRONG_COURT', 6), ('L1_DROP_WRONG_LETTER', 7), ('L1_DROP_RUBRIC_OUT', 8),
             ('L1_SIGNAL_RUBRIC_FROM_TITLE', 9), ('L1_KEEP_TEXT_UNAVAILABLE', 10)) AS r(code, ord);

INSERT INTO ops.pipeline_profile (profile_code, name) VALUES ('ledger_test', 'Ledger test');
INSERT INTO ops.pipeline_profile_version (profile_code, v_major, v_minor, v_patch, status, bump_kind, changelog)
VALUES ('ledger_test', 1, 0, 0, 'active', 'initial', 'fixture');
INSERT INTO ops.pipeline_profile_step (profile_version_id, step, component_version_id)
SELECT profile_version_id, 'layer1_filter', pg_temp.cv('layer1_filter', 1, 1) FROM ops.pipeline_profile_version WHERE profile_code = 'ledger_test';
INSERT INTO ops.pipeline_run (run_id, profile_version_id, kind, mode, git_dirty, params_sha256, triggered_by)
VALUES ('00000000-0000-4000-8000-000000000003', (SELECT profile_version_id FROM ops.pipeline_profile_version WHERE profile_code = 'ledger_test'),
        'layer1', 'REPLAY', false, repeat('6', 64), 'ci');

-- second (non-primary) texts with the terms the text rules match; synthetic, no personal data
INSERT INTO corpus.ruling_text (ruling_id, source, content, content_sha256, snapshot_id)
SELECT pg_temp.rid(t.docket), 'bger', t.c, encode(sha256(convert_to(t.c, 'UTF8')), 'hex'), '00000000-0000-4000-8000-0000000000a1'
FROM (VALUES ('8C_493/2025', 'Die Suva ist Beschwerdegegnerin. Erwägungen: 1. Der Rückfall.'),
             ('8C_307/2025', 'Arbeitslosenversicherung: Taggeld nach VVG.')) AS t(docket, c);
CREATE FUNCTION pg_temp.bger_text(p_docket text) RETURNS uuid LANGUAGE sql AS
  $f$ SELECT text_id FROM corpus.ruling_text WHERE ruling_id = pg_temp.rid(p_docket) AND source = 'bger' $f$;

CREATE TEMP SEQUENCE rep START 10;
CREATE FUNCTION pg_temp.l1(p_id uuid, p_docket text, p_scope text, p_reason text, p_text uuid, p_outcome text DEFAULT 'ok') RETURNS void LANGUAGE sql AS $f$
  INSERT INTO triage.assessment (assessment_id, run_id, ruling_id, step, repetition_idx, component_version_id, span_id, input_text_id,
                                 input_fingerprint, in_suva_scope, outcome, score_0_100, score_source, reason_code, explanation_de, mode, started_at)
  VALUES (p_id, '00000000-0000-4000-8000-000000000003', pg_temp.rid(p_docket), 'layer1_filter', nextval('pg_temp.rep')::smallint,
          pg_temp.cv('layer1_filter', 1, 1), pg_temp.span('layer1_filter', p_docket, '00000000-0000-4000-8000-000000000003'), p_text,
          repeat('0', 64), p_scope::ops.in_suva_scope, p_outcome::ops.assessment_outcome,
          CASE WHEN p_scope = 'out_of_scope' THEN 0 END, CASE WHEN p_scope = 'out_of_scope' THEN 'net'::ops.score_source END,
          p_reason, 'Test.', 'REPLAY', now()) $f$;

-- three complete ledgers: kept on rubric and text, kept on rubric without text, dropped with a blocked contract term
CREATE TEMP TABLE ledger_tpl (tpl text, rule_code text, outcome ops.rule_outcome, evidence_field text, examined_value text,
                              char_start int, char_end int, matched_text text, detail jsonb NOT NULL DEFAULT '{}');
INSERT INTO ledger_tpl VALUES
  ('kept', 'L1_KEEP_RUBRIC',              'fired',     'rubric:gegenstand', 'Unfallversicherung', NULL, NULL, 'Unfallversicherung', '{}'),
  ('kept', 'L1_KEEP_RUBRIC_MISSING',      'not_fired', 'rubric:gegenstand', 'Unfallversicherung', NULL, NULL, NULL, '{}'),
  ('kept', 'L1_KEEP_ACCIDENT_TERM',       'fired',     'full_text', NULL, 4, 8, 'Suva', '{"pattern": "accident_terms"}'),
  ('kept', 'L1_KEEP_CONTRACT_TERM',       'not_fired', 'full_text', NULL, NULL, NULL, NULL, '{"pattern": "contract_terms", "text_chars": 61}'),
  ('kept', 'L1_FLAG_CLOSED_RUBRIC',       'not_fired', 'full_text', NULL, NULL, NULL, NULL, '{"pattern": "contract_terms"}'),
  ('kept', 'L1_DROP_WRONG_COURT',         'not_fired', 'docket', '8C', NULL, NULL, NULL, '{}'),
  ('kept', 'L1_DROP_WRONG_LETTER',        'not_fired', 'docket', '8C', NULL, NULL, NULL, '{}'),
  ('kept', 'L1_DROP_RUBRIC_OUT',          'not_fired', 'rubric:gegenstand', 'Unfallversicherung', NULL, NULL, NULL, '{}'),
  ('kept', 'L1_SIGNAL_RUBRIC_FROM_TITLE', 'fired',     'gegenstand', 'Unfallversicherung', NULL, NULL, 'Unfallversicherung', '{}'),
  ('no_text', 'L1_KEEP_RUBRIC',              'fired',          'rubric:gegenstand', 'Assicurazione contro gli infortuni', NULL, NULL, 'Assicurazione contro gli infortuni', '{}'),
  ('no_text', 'L1_KEEP_RUBRIC_MISSING',      'not_fired',      'rubric:gegenstand', 'Assicurazione contro gli infortuni', NULL, NULL, NULL, '{}'),
  ('no_text', 'L1_KEEP_ACCIDENT_TERM',       'not_applicable', NULL, NULL, NULL, NULL, NULL, '{"why": "text_absent"}'),
  ('no_text', 'L1_KEEP_CONTRACT_TERM',       'not_applicable', NULL, NULL, NULL, NULL, NULL, '{"why": "text_absent"}'),
  ('no_text', 'L1_FLAG_CLOSED_RUBRIC',       'not_applicable', NULL, NULL, NULL, NULL, NULL, '{"why": "text_absent"}'),
  ('no_text', 'L1_DROP_WRONG_COURT',         'not_fired',      'docket', '8C', NULL, NULL, NULL, '{}'),
  ('no_text', 'L1_DROP_WRONG_LETTER',        'not_fired',      'docket', '8C', NULL, NULL, NULL, '{}'),
  ('no_text', 'L1_DROP_RUBRIC_OUT',          'not_fired',      'rubric:gegenstand', 'Assicurazione contro gli infortuni', NULL, NULL, NULL, '{}'),
  ('no_text', 'L1_SIGNAL_RUBRIC_FROM_TITLE', 'fired',          'gegenstand', 'Assicurazione contro gli infortuni', NULL, NULL, 'Assicurazione contro gli infortuni', '{}'),
  ('dropped', 'L1_KEEP_RUBRIC',              'not_fired', 'rubric:neuheiten', 'Arbeitslosenversicherung', NULL, NULL, NULL, '{}'),
  ('dropped', 'L1_KEEP_RUBRIC_MISSING',      'not_fired', 'rubric:neuheiten', 'Arbeitslosenversicherung', NULL, NULL, NULL, '{}'),
  ('dropped', 'L1_KEEP_ACCIDENT_TERM',       'not_fired', 'full_text', NULL, NULL, NULL, NULL, '{"pattern": "accident_terms", "text_chars": 43}'),
  ('dropped', 'L1_KEEP_CONTRACT_TERM',       'blocked',   'full_text', NULL, 39, 42, 'VVG',
             '{"blocked_by": "L1_FLAG_CLOSED_RUBRIC", "closed_rubric_match": "Arbeitslosenversicherung"}'),
  ('dropped', 'L1_FLAG_CLOSED_RUBRIC',       'fired',     'rubric:neuheiten', 'Arbeitslosenversicherung', NULL, NULL, 'Arbeitslosenversicherung', '{}'),
  ('dropped', 'L1_DROP_WRONG_COURT',         'not_fired', 'docket', '8C', NULL, NULL, NULL, '{}'),
  ('dropped', 'L1_DROP_WRONG_LETTER',        'not_fired', 'docket', '8C', NULL, NULL, NULL, '{}'),
  ('dropped', 'L1_DROP_RUBRIC_OUT',          'fired',     'rubric:neuheiten', 'Arbeitslosenversicherung', NULL, NULL, 'Arbeitslosenversicherung', '{}'),
  ('dropped', 'L1_SIGNAL_RUBRIC_FROM_TITLE', 'not_fired', 'rubric:neuheiten', 'Arbeitslosenversicherung', NULL, NULL, NULL, '{"rubric_source": "neuheiten"}');

-- writes a template's rows for an assessment: ordinal, reason code and effect from the version (p_skip leaves a rule out)
CREATE FUNCTION pg_temp.ledger(p_id uuid, p_tpl text, p_skip text DEFAULT '') RETURNS void LANGUAGE sql AS $f$
  INSERT INTO triage.assessment_reason (assessment_id, ordinal, rule_id, reason_code, effect, outcome, evidence_field, examined_value,
                                        char_start, char_end, matched_text, detail)
  SELECT p_id, cvr.ordinal, rl.rule_id, rl.reason_code, rl.kind, t.outcome, t.evidence_field, t.examined_value,
         t.char_start, t.char_end, t.matched_text, t.detail
  FROM pg_temp.ledger_tpl t
  JOIN ops.rule rl ON rl.rule_code = t.rule_code AND rl.v_major = 1
  JOIN ops.component_version_rule cvr ON cvr.rule_id = rl.rule_id AND cvr.component_version_id = pg_temp.cv('layer1_filter', 1, 1)
  WHERE t.tpl = p_tpl AND t.rule_code <> p_skip $f$;

-- one row of a template, with one column overridden (jsonb merge), as a single INSERT
CREATE FUNCTION pg_temp.row_sql(p_id text, p_tpl text, p_rule text, p_override jsonb DEFAULT '{}') RETURNS text LANGUAGE sql AS $f$
  SELECT format($s$INSERT INTO triage.assessment_reason (assessment_id, ordinal, rule_id, reason_code, effect, outcome, evidence_field,
                                                        examined_value, char_start, char_end, matched_text, detail)
                   SELECT %L, (r ->> 'ordinal')::smallint, (r ->> 'rule_id')::uuid, r ->> 'reason_code', (r ->> 'effect')::ops.rule_kind,
                          (r ->> 'outcome')::ops.rule_outcome, r ->> 'evidence_field', r ->> 'examined_value', (r ->> 'char_start')::int,
                          (r ->> 'char_end')::int, r ->> 'matched_text', r -> 'detail'
                   FROM (SELECT to_jsonb(x) || %L::jsonb AS r FROM (
                           SELECT cvr.ordinal, rl.rule_id, rl.reason_code, rl.kind AS effect, t.outcome, t.evidence_field, t.examined_value,
                                  t.char_start, t.char_end, t.matched_text, t.detail
                           FROM pg_temp.ledger_tpl t
                           JOIN ops.rule rl ON rl.rule_code = t.rule_code AND rl.v_major = 1
                           JOIN ops.component_version_rule cvr ON cvr.rule_id = rl.rule_id AND cvr.component_version_id = pg_temp.cv('layer1_filter', 1, 1)
                           WHERE t.tpl = %L AND t.rule_code = %L) x) y$s$, p_id, p_override, p_tpl, p_rule) $f$;

-- like expect_error, but forces the deferred checks before deciding
CREATE FUNCTION pg_temp.expect_ledger_error(p_sql text, p_pattern text) RETURNS void LANGUAGE plpgsql AS $f$
BEGIN
  BEGIN
    EXECUTE p_sql;
    SET CONSTRAINTS ALL IMMEDIATE;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM !~* p_pattern THEN
      RAISE EXCEPTION 'expected an error matching "%", got: %', p_pattern, SQLERRM;
    END IF;
    RETURN;
  END;
  RAISE EXCEPTION 'expected an error matching "%", but this passed the ledger checks: %', p_pattern, p_sql;
END $f$;

-- valid ledgers pass the deferred check --------------------------------------------------------------------------
SELECT pg_temp.l1('00000000-0000-4000-8000-000000000a01', '8C_493/2025', 'potentially', 'L1_KEEP_RUBRIC', pg_temp.bger_text('8C_493/2025'));
SELECT pg_temp.ledger('00000000-0000-4000-8000-000000000a01', 'kept');
SELECT pg_temp.l1('00000000-0000-4000-8000-000000000a02', '8C_199/2026', 'potentially', 'L1_KEEP_RUBRIC', NULL);
SELECT pg_temp.ledger('00000000-0000-4000-8000-000000000a02', 'no_text');
SELECT pg_temp.l1('00000000-0000-4000-8000-000000000a03', '8C_307/2025', 'out_of_scope', 'L1_DROP_RUBRIC_OUT', pg_temp.bger_text('8C_307/2025'));
SELECT pg_temp.ledger('00000000-0000-4000-8000-000000000a03', 'dropped');
-- a failed or skipped assessment that keeps the ruling (potentially) needs no ledger
SELECT pg_temp.l1('00000000-0000-4000-8000-000000000a04', '8C_307/2025', 'potentially', NULL, NULL, 'failed');
SELECT pg_temp.l1('00000000-0000-4000-8000-000000000a05', '8C_199/2026', 'potentially', NULL, NULL, 'skipped');
SET CONSTRAINTS ALL IMMEDIATE;
SET CONSTRAINTS ALL DEFERRED;

-- the rule set of a step version is sealed once an assessment uses it or a profile pins it: a certified ledger
-- cannot go stale under a rule added later (a new rule is a new version) ---------------------------------------------
INSERT INTO ops.rule (step, rule_code, v_major, v_minor, v_patch, kind, definition, definition_schema_id, reason_code, status, bump_kind, changelog)
VALUES ('layer1_filter', 'L1_KEEP_TITLE_RUBRIC', 1, 0, 0, 'keep', '{"check": "title_rubric_kept"}',
        (SELECT json_schema_id FROM ops.json_schema WHERE schema_code = 'test.rule_definition'), 'L1_KEEP_TITLE_RUBRIC', 'active', 'initial', 'fixture'),
       ('parse', 'P1_FIXTURE', 1, 0, 0, 'flag', '{}',
        (SELECT json_schema_id FROM ops.json_schema WHERE schema_code = 'test.rule_definition'), 'ING_TEXT_MISSING', 'active', 'initial', 'fixture');
-- used by the assessments above
SELECT pg_temp.expect_error($q$
  INSERT INTO ops.component_version_rule (component_version_id, rule_id, ordinal)
  VALUES (pg_temp.cv('layer1_filter', 1, 1), pg_temp.rule('L1_KEEP_TITLE_RUBRIC'), 11)$q$,
  'component version V1.1.0 \(layer1_filter\): its rule set is sealed \(used by an assessment or pinned by a profile\)');
-- pinned by the default profile, never used
SELECT pg_temp.expect_error($q$
  INSERT INTO ops.component_version_rule (component_version_id, rule_id, ordinal) VALUES (pg_temp.cv('parse'), pg_temp.rule('P1_FIXTURE'), 1)$q$,
  'component version V1.0.0 \(parse\): its rule set is sealed');
-- a changed binding of a rule already bound (another ordinal) is refused too, even with ON CONFLICT DO NOTHING
SELECT pg_temp.expect_error($q$
  INSERT INTO ops.component_version_rule (component_version_id, rule_id, ordinal)
  VALUES (pg_temp.cv('layer1_filter', 1, 1), pg_temp.rule('L1_KEEP_RUBRIC'), 12) ON CONFLICT DO NOTHING$q$, 'its rule set is sealed');
-- the registry loader's reload of the same bindings (ON CONFLICT DO NOTHING) still passes
INSERT INTO ops.component_version_rule (component_version_id, rule_id, ordinal, enabled)
SELECT component_version_id, rule_id, ordinal, enabled FROM ops.component_version_rule WHERE component_version_id = pg_temp.cv('layer1_filter', 1, 1)
ON CONFLICT DO NOTHING;
DO $$ BEGIN
  ASSERT (SELECT count(*) FROM ops.component_version_rule WHERE component_version_id = pg_temp.cv('layer1_filter', 1, 1)) = 10, 'ten bindings, unchanged';
END $$;

-- completeness (t50_ledger) ------------------------------------------------------------------------------------------
-- a missing rule
SELECT pg_temp.expect_ledger_error($q$
  SELECT pg_temp.l1('00000000-0000-4000-8000-000000000b01', '8C_493/2025', 'potentially', 'L1_KEEP_RUBRIC', pg_temp.bger_text('8C_493/2025'));
  SELECT pg_temp.ledger('00000000-0000-4000-8000-000000000b01', 'kept', 'L1_KEEP_CONTRACT_TERM')$q$,
  'ledger incomplete, no row for the enabled rule\(s\) L1_KEEP_CONTRACT_TERM');
-- no ledger at all, also for another step: the ranking version has one rule
SELECT pg_temp.expect_ledger_error($q$
  INSERT INTO triage.assessment (run_id, ruling_id, step, repetition_idx, component_version_id, span_id, input_fingerprint, in_suva_scope,
                                 outcome, score_0_100, score_source, reason_code, mode, started_at)
  VALUES ('00000000-0000-4000-8000-000000000001', pg_temp.rid('8C_307/2025'), 'ranking', 9, pg_temp.cv('ranking'),
          pg_temp.span('ranking', '8C_307/2025'), repeat('0', 64), 'out_of_scope', 'ok', 30, 'judged', 'RANK_BELOW_THRESHOLD', 'REPLAY', now())$q$,
  '\(ranking\): ledger incomplete, no row for the enabled rule\(s\) RANK_BELOW_THRESHOLD');
-- a duplicate rule: same ordinal (primary key), or another ordinal past the row check (unique rule per assessment)
SELECT pg_temp.expect_ledger_error($q$
  SELECT pg_temp.l1('00000000-0000-4000-8000-000000000b02', '8C_493/2025', 'potentially', 'L1_KEEP_RUBRIC', pg_temp.bger_text('8C_493/2025'));
  SELECT pg_temp.ledger('00000000-0000-4000-8000-000000000b02', 'kept');
  SELECT pg_temp.ledger('00000000-0000-4000-8000-000000000b02', 'kept')$q$, 'duplicate key .*assessment_reason_pkey');
SELECT pg_temp.expect_ledger_error(format($q$
  ALTER TABLE triage.assessment_reason DISABLE TRIGGER t30_check;
  SELECT pg_temp.l1('00000000-0000-4000-8000-000000000b03', '8C_493/2025', 'potentially', 'L1_KEEP_RUBRIC', pg_temp.bger_text('8C_493/2025'));
  SELECT pg_temp.ledger('00000000-0000-4000-8000-000000000b03', 'kept');
  %s$q$, pg_temp.row_sql('00000000-0000-4000-8000-000000000b03', 'kept', 'L1_KEEP_RUBRIC', '{"ordinal": 11}')),
  'assessment_reason_rule_uq');
-- an extra row (a disabled rule) that slipped past the row check is still caught at commit
SELECT pg_temp.expect_ledger_error($q$
  ALTER TABLE triage.assessment_reason DISABLE TRIGGER t30_check;
  SELECT pg_temp.l1('00000000-0000-4000-8000-000000000b04', '8C_493/2025', 'potentially', 'L1_KEEP_RUBRIC', pg_temp.bger_text('8C_493/2025'));
  SELECT pg_temp.ledger('00000000-0000-4000-8000-000000000b04', 'kept');
  INSERT INTO triage.assessment_reason (assessment_id, ordinal, rule_id, reason_code, effect, outcome, detail)
  VALUES ('00000000-0000-4000-8000-000000000b04', 10, pg_temp.rule('L1_KEEP_TEXT_UNAVAILABLE'), 'L1_KEEP_TEXT_UNAVAILABLE', 'keep', 'not_applicable',
          '{"why": "rule disabled"}')$q$,
  'ledger rows for rule\(s\) L1_KEEP_TEXT_UNAVAILABLE that are not enabled rules');

-- one row against its rule version (t30_check); the assessments here stay incomplete, so they are rolled back -------
SAVEPOINT rows;
SELECT pg_temp.l1('00000000-0000-4000-8000-000000000c01', '8C_493/2025', 'potentially', 'L1_KEEP_RUBRIC', pg_temp.bger_text('8C_493/2025'));
SELECT pg_temp.expect_error($q$
  INSERT INTO triage.assessment_reason (assessment_id, ordinal, rule_id, reason_code, effect, outcome, evidence_field)
  VALUES ('00000000-0000-4000-8000-000000000c01', 1, pg_temp.rule('V1_IDS_IN_SET'), 'V1_IDS_IN_SET', 'flag', 'fired', 'docket')$q$,
  'not a rule of the assessment''s step version');
SELECT pg_temp.expect_error(pg_temp.row_sql('00000000-0000-4000-8000-000000000c01', 'kept', 'L1_FLAG_CLOSED_RUBRIC', '{"effect": "keep"}'),
  'rule L1_FLAG_CLOSED_RUBRIC: effect keep must be the rule''s kind flag');
SELECT pg_temp.expect_error(pg_temp.row_sql('00000000-0000-4000-8000-000000000c01', 'kept', 'L1_KEEP_ACCIDENT_TERM', '{"ordinal": 1}'),
  'rule L1_KEEP_ACCIDENT_TERM: ordinal 1 must be the rule''s ordinal 3');
SELECT pg_temp.expect_error($q$
  INSERT INTO triage.assessment_reason (assessment_id, ordinal, rule_id, reason_code, effect, outcome, detail)
  VALUES ('00000000-0000-4000-8000-000000000c01', 10, pg_temp.rule('L1_KEEP_TEXT_UNAVAILABLE'), 'L1_KEEP_TEXT_UNAVAILABLE', 'keep', 'not_applicable',
          '{"why": "text_present"}')$q$,
  'rule L1_KEEP_TEXT_UNAVAILABLE is disabled');
SELECT pg_temp.expect_error(pg_temp.row_sql('00000000-0000-4000-8000-000000000c01', 'kept', 'L1_KEEP_ACCIDENT_TERM', '{"char_end": 9999}'),
  'offsets \[4, 9999\) beyond the input text \(61 characters\)');
SELECT pg_temp.expect_error(pg_temp.row_sql('00000000-0000-4000-8000-000000000c01', 'kept', 'L1_KEEP_ACCIDENT_TERM', '{"matched_text": "Unfa"}'),
  'matched_text must equal the input text slice \[4, 8\)');
SELECT pg_temp.expect_error(pg_temp.row_sql('00000000-0000-4000-8000-000000000c01', 'kept', 'L1_KEEP_ACCIDENT_TERM', '{"char_start": 3, "char_end": 7}'),
  'matched_text must equal the input text slice \[3, 7\)');
SELECT pg_temp.expect_error(pg_temp.row_sql('00000000-0000-4000-8000-000000000c01', 'kept', 'L1_KEEP_ACCIDENT_TERM',
                                            '{"outcome": "not_applicable", "evidence_field": null, "char_start": null, "char_end": null, "matched_text": null, "detail": {}}'),
  'not_applicable needs detail.why');
SELECT pg_temp.expect_error(pg_temp.row_sql('00000000-0000-4000-8000-000000000c01', 'dropped', 'L1_KEEP_CONTRACT_TERM', '{"char_start": null, "char_end": null, "matched_text": null, "detail": {"closed_rubric_match": "x"}}'),
  'blocked needs detail.blocked_by naming another enabled flag rule of the same step version, got nothing');
SELECT pg_temp.expect_error(pg_temp.row_sql('00000000-0000-4000-8000-000000000c01', 'dropped', 'L1_KEEP_CONTRACT_TERM', '{"char_start": null, "char_end": null, "matched_text": null, "detail": {"blocked_by": "V1_IDS_IN_SET"}}'),
  'blocked needs detail.blocked_by naming another enabled flag rule of the same step version, got V1_IDS_IN_SET');
-- blocked: the blocker is another enabled flag of the version (not the rule itself, not a disabled rule, not a drop);
-- only a keep is blocked; a layer-1 block names the closed rubric it matched
SELECT pg_temp.expect_error(pg_temp.row_sql('00000000-0000-4000-8000-000000000c01', 'dropped', 'L1_KEEP_CONTRACT_TERM',
                                            format('{"char_start": 4, "char_end": 8, "matched_text": "Suva", "detail": {"blocked_by": "%s", "closed_rubric_match": "arbeitslos"}}', b.code)::jsonb),
  format('blocked needs detail.blocked_by naming another enabled flag rule of the same step version, got %s', b.code))
FROM (VALUES ('L1_KEEP_CONTRACT_TERM'), ('L1_KEEP_TEXT_UNAVAILABLE'), ('L1_DROP_RUBRIC_OUT')) AS b(code);
SELECT pg_temp.expect_error(pg_temp.row_sql('00000000-0000-4000-8000-000000000c01', 'dropped', 'L1_DROP_RUBRIC_OUT',
                                            '{"outcome": "blocked", "detail": {"blocked_by": "L1_FLAG_CLOSED_RUBRIC", "closed_rubric_match": "arbeitslos"}}'),
  'rule L1_DROP_RUBRIC_OUT: only a keep rule can be blocked, not a drop rule');
SELECT pg_temp.expect_error(pg_temp.row_sql('00000000-0000-4000-8000-000000000c01', 'dropped', 'L1_KEEP_CONTRACT_TERM',
                                            '{"char_start": 4, "char_end": 8, "matched_text": "Suva", "detail": {"blocked_by": "L1_FLAG_CLOSED_RUBRIC"}}'),
  'rule L1_KEEP_CONTRACT_TERM: a blocked layer-1 row needs detail.closed_rubric_match');
-- not_applicable: why is one of the five preconditions, and text_absent only when the assessment has no text
SELECT pg_temp.expect_error(pg_temp.row_sql('00000000-0000-4000-8000-000000000c01', 'no_text', 'L1_KEEP_ACCIDENT_TERM', '{"detail": {"why": null}}'),
  'not_applicable needs detail.why');
SELECT pg_temp.expect_error(pg_temp.row_sql('00000000-0000-4000-8000-000000000c01', 'no_text', 'L1_KEEP_ACCIDENT_TERM', '{"detail": {"why": "banana"}}'),
  'rule L1_KEEP_ACCIDENT_TERM: detail.why banana is not one of court_not_listed, letter_not_listed, rubric_missing, text_absent, gegenstand_absent');
SELECT pg_temp.expect_error(pg_temp.row_sql('00000000-0000-4000-8000-000000000c01', 'no_text', 'L1_KEEP_ACCIDENT_TERM'),
  'rule L1_KEEP_ACCIDENT_TERM: why text_absent, but the assessment has an input text');
-- a full-text match on a text has offsets, and offsets belong to full-text evidence only
SELECT pg_temp.expect_error(pg_temp.row_sql('00000000-0000-4000-8000-000000000c01', 'kept', 'L1_KEEP_ACCIDENT_TERM',
                                            '{"char_start": null, "char_end": null, "matched_text": "invented, not in the text"}'),
  'rule L1_KEEP_ACCIDENT_TERM: a full-text match needs its offsets in the input text');
SELECT pg_temp.expect_error(pg_temp.row_sql('00000000-0000-4000-8000-000000000c01', 'kept', 'L1_KEEP_ACCIDENT_TERM',
                                            '{"evidence_field": "fulltext", "char_start": 0, "char_end": 4, "matched_text": "Militaerversicherung (invented)"}'),
  'assessment_reason_offsets_field_chk');
SELECT pg_temp.expect_error(pg_temp.row_sql('00000000-0000-4000-8000-000000000c01', 'dropped', 'L1_KEEP_CONTRACT_TERM',
                                            '{"evidence_field": "rubric:neuheiten", "char_start": 5000, "char_end": 5003, "matched_text": "XYZ"}'),
  'assessment_reason_offsets_field_chk');
-- a match has at least one character
SELECT pg_temp.expect_error(pg_temp.row_sql('00000000-0000-4000-8000-000000000c01', 'kept', 'L1_KEEP_ACCIDENT_TERM', '{"char_start": 3, "char_end": 3, "matched_text": ""}'),
  'assessment_reason_offsets_chk');
-- without an input text no text was searched: offsets, a match or an evaluated (not_fired) text rule are refused
SELECT pg_temp.l1('00000000-0000-4000-8000-000000000c02', '8C_199/2026', 'potentially', 'L1_KEEP_RUBRIC', NULL);
SELECT pg_temp.expect_error(pg_temp.row_sql('00000000-0000-4000-8000-000000000c02', 'kept', 'L1_KEEP_ACCIDENT_TERM'),
  'rule L1_KEEP_ACCIDENT_TERM: the assessment has no input text');
SELECT pg_temp.expect_error(pg_temp.row_sql('00000000-0000-4000-8000-000000000c02', 'kept', 'L1_KEEP_ACCIDENT_TERM',
                                            '{"char_start": null, "char_end": null, "matched_text": "Suva"}'),
  'rule L1_KEEP_ACCIDENT_TERM: the assessment has no input text');
SELECT pg_temp.expect_error(pg_temp.row_sql('00000000-0000-4000-8000-000000000c02', 'kept', 'L1_KEEP_CONTRACT_TERM'),
  'rule L1_KEEP_CONTRACT_TERM: the assessment has no input text');
-- only a rule whose check fires on the absence of text (V1.2.0's text_unavailable) fires on full_text without a text,
-- without offsets or match: a term keep fired there would certify a keep with no evidence (review fix). The accepted
-- shape, a fired L1_KEEP_TEXT_UNAVAILABLE on the real registry, is covered by tests/test_layer1_v120_db.py.
SELECT pg_temp.expect_error(pg_temp.row_sql('00000000-0000-4000-8000-000000000c02', 'kept', 'L1_KEEP_ACCIDENT_TERM',
                                            '{"char_start": null, "char_end": null, "matched_text": null}'),
  'rule L1_KEEP_ACCIDENT_TERM: the assessment has no input text, so only a rule whose check is text_unavailable can fire on full_text \(check text_accident_term\)');
-- CHECKs: evidence of a fired keep or drop; offsets and match only when fired or blocked; no copied text
SELECT pg_temp.expect_error(pg_temp.row_sql('00000000-0000-4000-8000-000000000c01', 'kept', 'L1_KEEP_RUBRIC', '{"evidence_field": null}'),
  'assessment_reason_evidence_chk');
SELECT pg_temp.expect_error(pg_temp.row_sql('00000000-0000-4000-8000-000000000c01', 'kept', 'L1_KEEP_RUBRIC_MISSING', '{"matched_text": "Unfallversicherung"}'),
  'assessment_reason_match_chk');
SELECT pg_temp.expect_error(pg_temp.row_sql('00000000-0000-4000-8000-000000000c01', 'kept', 'L1_KEEP_CONTRACT_TERM', '{"char_start": 4, "char_end": 8, "matched_text": "Suva"}'),
  'assessment_reason_match_chk');
SELECT pg_temp.expect_error(pg_temp.row_sql('00000000-0000-4000-8000-000000000c01', 'kept', 'L1_KEEP_CONTRACT_TERM', '{"examined_value": "Die Suva"}'),
  'assessment_reason_full_text_chk');
SELECT pg_temp.expect_error(pg_temp.row_sql('00000000-0000-4000-8000-000000000c01', 'kept', 'L1_DROP_WRONG_COURT', format('{"examined_value": "%s"}', repeat('x', 301))::jsonb),
  'check constraint');
SELECT pg_temp.expect_error(pg_temp.row_sql('00000000-0000-4000-8000-000000000c01', 'kept', 'L1_DROP_WRONG_COURT', '{"detail": [1]}'), 'check constraint');
SELECT pg_temp.expect_error(pg_temp.row_sql('00000000-0000-4000-8000-000000000c01', 'kept', 'L1_DROP_WRONG_COURT', format('{"detail": {"text": "%s"}}', repeat('x', 2100))::jsonb),
  'check constraint');
-- a match early in a long multibyte text stored compressed (pglz): substr() on a compressed value decompresses only a
-- byte prefix, which can end inside a character ("invalid byte sequence", PostgreSQL 17); the check reads the whole
-- text first. Here the prefix substr(content, 6, 4) needs ends inside an 'é'.
INSERT INTO corpus.ruling_text (ruling_id, source, content, content_sha256, snapshot_id)
SELECT pg_temp.rid('8C_199/2026'), 'bger', c, encode(sha256(convert_to(c, 'UTF8')), 'hex'), '00000000-0000-4000-8000-0000000000a1'
FROM (SELECT 'xDie Suva. ' || repeat('é', 4000) AS c) x;
SELECT pg_temp.l1('00000000-0000-4000-8000-000000000c03', '8C_199/2026', 'potentially', 'L1_KEEP_RUBRIC', pg_temp.bger_text('8C_199/2026'));
DO $$ BEGIN
  ASSERT (SELECT pg_column_compression(content) FROM corpus.ruling_text WHERE text_id = pg_temp.bger_text('8C_199/2026')) = 'pglz',
         'the text is stored compressed, so the slice path is exercised';
  EXECUTE pg_temp.row_sql('00000000-0000-4000-8000-000000000c03', 'kept', 'L1_KEEP_ACCIDENT_TERM', '{"char_start": 5, "char_end": 9}');
  ASSERT (SELECT matched_text FROM triage.assessment_reason WHERE assessment_id = '00000000-0000-4000-8000-000000000c03') = 'Suva',
         'the match on a compressed multibyte text is certified';
END $$;
ROLLBACK TO SAVEPOINT rows;

-- the layer-1 decision agrees with the fired rules (t50_ledger, F-13) --------------------------------------------------
SELECT pg_temp.expect_ledger_error($q$
  SELECT pg_temp.l1('00000000-0000-4000-8000-000000000d01', '8C_307/2025', 'potentially', 'L1_DROP_RUBRIC_OUT', pg_temp.bger_text('8C_307/2025'));
  SELECT pg_temp.ledger('00000000-0000-4000-8000-000000000d01', 'dropped')$q$, 'kept \(potentially\) but no keep rule fired');
SELECT pg_temp.expect_ledger_error($q$
  SELECT pg_temp.l1('00000000-0000-4000-8000-000000000d02', '8C_493/2025', 'out_of_scope', 'L1_DROP_RUBRIC_OUT', pg_temp.bger_text('8C_493/2025'));
  SELECT pg_temp.ledger('00000000-0000-4000-8000-000000000d02', 'kept')$q$, 'dropped \(out_of_scope\) although keep rule L1_KEEP_RUBRIC fired');
SELECT pg_temp.expect_ledger_error($q$
  SELECT pg_temp.l1('00000000-0000-4000-8000-000000000d03', '8C_493/2025', 'potentially', 'L1_KEEP_ACCIDENT_TERM', pg_temp.bger_text('8C_493/2025'));
  SELECT pg_temp.ledger('00000000-0000-4000-8000-000000000d03', 'kept')$q$,
  'reason_code L1_KEEP_ACCIDENT_TERM must be L1_KEEP_RUBRIC \(the fired keep rule with the lowest ordinal\)');
SELECT pg_temp.expect_ledger_error($q$
  SELECT pg_temp.l1('00000000-0000-4000-8000-000000000d04', '8C_307/2025', 'out_of_scope', 'L1_DROP_WRONG_COURT', pg_temp.bger_text('8C_307/2025'));
  SELECT pg_temp.ledger('00000000-0000-4000-8000-000000000d04', 'dropped')$q$,
  'reason_code L1_DROP_WRONG_COURT must be L1_DROP_RUBRIC_OUT \(the fired drop rule with the lowest ordinal\)');
SELECT pg_temp.expect_ledger_error(format($q$
  SELECT pg_temp.l1('00000000-0000-4000-8000-000000000d05', '8C_307/2025', 'out_of_scope', 'L1_DROP_RUBRIC_OUT', pg_temp.bger_text('8C_307/2025'));
  SELECT pg_temp.ledger('00000000-0000-4000-8000-000000000d05', 'dropped', 'L1_DROP_RUBRIC_OUT');
  %s$q$, pg_temp.row_sql('00000000-0000-4000-8000-000000000d05', 'dropped', 'L1_DROP_RUBRIC_OUT', '{"outcome": "not_fired", "matched_text": null}')),
  'dropped \(out_of_scope\) but no drop rule fired');
-- a block needs its blocker to have fired: here the rubric keep and the accident term ("Suva" at verified offsets)
-- are "blocked" by a flag that did not fire, and the ruling is dropped
INSERT INTO ledger_tpl
SELECT 'blocked_unfired', rule_code, outcome, evidence_field, examined_value, char_start, char_end, matched_text, detail FROM ledger_tpl WHERE tpl = 'kept';
UPDATE ledger_tpl SET outcome = 'blocked', detail = '{"blocked_by": "L1_FLAG_CLOSED_RUBRIC", "closed_rubric_match": "arbeitslos"}'
WHERE tpl = 'blocked_unfired' AND rule_code IN ('L1_KEEP_RUBRIC', 'L1_KEEP_ACCIDENT_TERM');
UPDATE ledger_tpl SET outcome = 'fired', matched_text = examined_value WHERE tpl = 'blocked_unfired' AND rule_code = 'L1_DROP_RUBRIC_OUT';
SELECT pg_temp.expect_ledger_error($q$
  SELECT pg_temp.l1('00000000-0000-4000-8000-000000000d06', '8C_493/2025', 'out_of_scope', 'L1_DROP_RUBRIC_OUT', pg_temp.bger_text('8C_493/2025'));
  SELECT pg_temp.ledger('00000000-0000-4000-8000-000000000d06', 'blocked_unfired')$q$,
  'blocked rule\(s\) L1_KEEP_RUBRIC \(by L1_FLAG_CLOSED_RUBRIC\), L1_KEEP_ACCIDENT_TERM \(by L1_FLAG_CLOSED_RUBRIC\) name a blocker that did not fire');
-- a drop is certified whatever the assessment outcome: a skipped layer-1 drop without a ledger is refused
SELECT pg_temp.expect_ledger_error($q$
  SELECT pg_temp.l1('00000000-0000-4000-8000-000000000d07', '8C_493/2025', 'out_of_scope', 'L1_DROP_WRONG_COURT', pg_temp.bger_text('8C_493/2025'), 'skipped')$q$,
  'ledger incomplete');

-- the views ------------------------------------------------------------------------------------------------------------
DO $$
DECLARE
  got text;
BEGIN
  SELECT string_agg(ordinal || ':' || rule_code || ':' || outcome, ',' ORDER BY ordinal) INTO got
  FROM triage.v_layer1_ledger WHERE assessment_id = '00000000-0000-4000-8000-000000000a03';
  ASSERT got = '1:L1_KEEP_RUBRIC:not_fired,2:L1_KEEP_RUBRIC_MISSING:not_fired,3:L1_KEEP_ACCIDENT_TERM:not_fired,'
               '4:L1_KEEP_CONTRACT_TERM:blocked,5:L1_FLAG_CLOSED_RUBRIC:fired,6:L1_DROP_WRONG_COURT:not_fired,'
               '7:L1_DROP_WRONG_LETTER:not_fired,8:L1_DROP_RUBRIC_OUT:fired,9:L1_SIGNAL_RUBRIC_FROM_TITLE:not_fired',
         format('ledger of the dropped ruling: %s', got);
  ASSERT (SELECT count(*) FROM triage.v_layer1_ledger WHERE run_id = '00000000-0000-4000-8000-000000000003') = 27,
         'nine rows for each of the three complete assessments, none for the failed one';
  ASSERT (SELECT string_agg(assessment_id::text || '=' || rule_code, ',' ORDER BY assessment_id) FROM triage.v_layer1_ledger
          WHERE run_id = '00000000-0000-4000-8000-000000000003' AND is_decisive)
         = '00000000-0000-4000-8000-000000000a01=L1_KEEP_RUBRIC,00000000-0000-4000-8000-000000000a02=L1_KEEP_RUBRIC,'
           '00000000-0000-4000-8000-000000000a03=L1_DROP_RUBRIC_OUT', 'exactly one decisive rule per assessment';
  ASSERT (SELECT label_de FROM triage.v_layer1_ledger WHERE assessment_id = '00000000-0000-4000-8000-000000000a03' AND is_decisive)
         = 'Rechtsgebiet nicht in der Liste der Abteilung', 'the decisive rule shows its German label';
  ASSERT (SELECT detail ->> 'blocked_by' FROM triage.v_layer1_ledger
          WHERE assessment_id = '00000000-0000-4000-8000-000000000a03' AND outcome = 'blocked') = 'L1_FLAG_CLOSED_RUBRIC', 'blocked_by';
  ASSERT (SELECT profile_code || '|' || component_version || '|' || rule_version || '|' || docket || '|' || (text_sha256 IS NOT NULL)
          FROM triage.v_layer1_ledger WHERE assessment_id = '00000000-0000-4000-8000-000000000a01' AND ordinal = 3)
         = 'ledger_test|V1.1.0|V1.0.0|8C_493/2025|true', 'ledger lineage columns';
  ASSERT (SELECT count(*) FROM triage.v_layer1_ledger WHERE assessment_id = '00000000-0000-4000-8000-000000000a02' AND outcome = 'not_applicable'
          AND detail ->> 'why' = 'text_absent' AND text_sha256 IS NULL) = 3, 'text rules not applicable without a text';
  -- the trace counts fired rules apart from evaluated ones
  ASSERT (SELECT reason_count || '/' || evaluated_rule_count FROM triage.v_scope_trace
          WHERE ruling_id = pg_temp.rid('8C_493/2025') AND step = 'layer1_filter') = '1/2', 'trace: 1 fired of 2 evaluated (layer 1)';
  ASSERT (SELECT reason_count || '/' || evaluated_rule_count FROM triage.v_scope_trace
          WHERE ruling_id = pg_temp.rid('8C_493/2025') AND step = 'ranking') = '0/1', 'trace: 0 fired of 1 evaluated (ranking)';
END $$;

-- seed (F-03): new reason codes, and drop labels that state only their own condition
DO $$ BEGIN
  ASSERT (SELECT count(*) FROM ops.reason_code
          WHERE code IN ('ING_DOCKET_MALFORMED', 'ING_DECISION_DATE_MISSING', 'L1_KEEP_TEXT_UNAVAILABLE', 'L1_KEEP_TITLE_RUBRIC')
            AND label_fr IS NOT NULL) = 4, 'four new reason codes with German and French labels';
  ASSERT (SELECT domain FROM ops.reason_code WHERE code = 'ING_DOCKET_MALFORMED') = 'ingest', 'ingest domain';
  ASSERT NOT EXISTS (SELECT 1 FROM ops.reason_code WHERE code LIKE 'L1_DROP_%'
                     AND (label_de ~* 'text|versicherungsbegriff' OR label_fr ~* 'texte|terme')), 'a drop label claims nothing about the text';
  -- labels are shared by every version: one that names the configured courts would turn false when a version changes them
  ASSERT NOT EXISTS (SELECT 1 FROM ops.reason_code WHERE code LIKE 'L1_%' AND (label_de ~ '[0-9]' OR label_fr ~ '[0-9]')),
         'no layer-1 label names a court or any other configured value';
END $$;

ROLLBACK;
