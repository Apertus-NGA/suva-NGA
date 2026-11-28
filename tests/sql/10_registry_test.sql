-- Registry (D-064): deterministic ids, insert-only versions (only status changes), changelog and bump rules,
-- schema subjects, rules bound to their step, profiles refusing draft steps, audit of status changes.
BEGIN;
\ir _fixtures.sql

-- a wrong explicit id is refused
SELECT pg_temp.expect_error($q$
  INSERT INTO corpus.ruling (ruling_id, docket, decision_date, language, bger_url, origin, created_by_run_id)
  VALUES (gen_random_uuid(), '8C_1/2025', '2026-05-01', 'de', 'https://x', 'base_dataset', '00000000-0000-4000-8000-000000000001')$q$,
  'must be uuid5');

-- status may change (and is audited); the configuration may not; nothing is deleted
UPDATE ops.component_version SET status = 'deprecated' WHERE component_version_id = pg_temp.cv('verify');
DO $$ BEGIN
  ASSERT EXISTS (SELECT 1 FROM audit.change_log WHERE table_name = 'ops.component_version' AND action = 'UPDATE' AND actor = 'test'),
         'status change must be audited with the actor';
END $$;
SELECT pg_temp.expect_error($q$UPDATE ops.component_version SET config = '{"x": 1}' WHERE step = 'verify'$q$, 'only .* may change');
SELECT pg_temp.expect_error($q$DELETE FROM ops.rule WHERE rule_code = 'L1_DROP_NO_RULE'$q$, 'append-only');
SELECT pg_temp.expect_error($q$UPDATE ops.rule SET definition = '{"x": 1}' WHERE rule_code = 'L1_DROP_NO_RULE'$q$, 'only .* may change');

-- a new version needs a changelog, and "initial" exactly when there is no previous version
SELECT pg_temp.expect_error($q$
  INSERT INTO ops.component_version (step, name, v_major, v_minor, v_patch, config_schema_id, config, config_sha256, code_path, code_sha256, bump_kind, previous_version_id, changelog)
  VALUES ('verify', 'x', 1, 1, 0, (SELECT json_schema_id FROM ops.json_schema WHERE schema_code = 'test.step_config'), '{}', repeat('4', 64), 'x', repeat('5', 64),
          'minor', pg_temp.cv('verify'), '   ')$q$, 'changelog');
SELECT pg_temp.expect_error($q$
  INSERT INTO ops.component_version (step, name, v_major, v_minor, v_patch, config_schema_id, config, config_sha256, code_path, code_sha256, bump_kind, changelog)
  VALUES ('verify', 'x', 1, 1, 0, (SELECT json_schema_id FROM ops.json_schema WHERE schema_code = 'test.step_config'), '{}', repeat('4', 64), 'x', repeat('5', 64),
          'minor', 'no previous version')$q$, 'bump_chk');

-- a step configuration must point to a step_config schema
SELECT pg_temp.expect_error($q$
  INSERT INTO ops.component_version (step, name, v_major, v_minor, v_patch, config_schema_id, config, config_sha256, code_path, code_sha256, bump_kind, previous_version_id, changelog)
  VALUES ('verify', 'x', 1, 1, 0, (SELECT json_schema_id FROM ops.json_schema WHERE schema_code = 'test.rule_definition'), '{}', repeat('4', 64), 'x', repeat('5', 64),
          'minor', pg_temp.cv('verify'), 'wrong schema subject')$q$, 'step_config schema');

-- a configuration is an object; its shape is the application's job (D-064)
SELECT pg_temp.expect_error($q$
  INSERT INTO ops.component_version (step, name, v_major, v_minor, v_patch, config_schema_id, config, config_sha256, code_path, code_sha256, bump_kind, previous_version_id, changelog)
  VALUES ('verify', 'x', 1, 1, 0, (SELECT json_schema_id FROM ops.json_schema WHERE schema_code = 'test.step_config'), '[1]', repeat('4', 64), 'x', repeat('5', 64),
          'minor', pg_temp.cv('verify'), 'array config')$q$, 'check constraint');

-- a rule of another step cannot be bound
SELECT pg_temp.expect_error($q$
  INSERT INTO ops.component_version_rule (component_version_id, rule_id, ordinal)
  VALUES (pg_temp.cv('verify'), pg_temp.rule('L1_KEEP_COURT_8C_9C'), 9)$q$, 'does not belong');

-- a profile version V1+ refuses a draft (V0.x) step version
INSERT INTO ops.component_version (step, name, v_major, v_minor, v_patch, config_schema_id, config, config_sha256, code_path, code_sha256, bump_kind, changelog)
VALUES ('parse', 'draft parser', 0, 1, 0, (SELECT json_schema_id FROM ops.json_schema WHERE schema_code = 'test.step_config'), '{}', repeat('4', 64), 'x', repeat('5', 64),
        'initial', 'draft');
INSERT INTO ops.pipeline_profile_version (profile_code, v_major, v_minor, v_patch, bump_kind, previous_version_id, changelog)
VALUES ('default', 1, 1, 0, 'minor', (SELECT profile_version_id FROM ops.pipeline_profile_version WHERE profile_code = 'default' AND v_minor = 0), 'next');
SELECT pg_temp.expect_error($q$
  INSERT INTO ops.pipeline_profile_step (profile_version_id, step, component_version_id)
  VALUES ((SELECT profile_version_id FROM ops.pipeline_profile_version WHERE profile_code = 'default' AND v_minor = 1), 'parse', pg_temp.cv('parse', 0, 1))$q$,
  'draft step version');
SELECT pg_temp.expect_error($q$
  INSERT INTO ops.pipeline_profile_step (profile_version_id, step, component_version_id)
  VALUES ((SELECT profile_version_id FROM ops.pipeline_profile_version WHERE profile_code = 'default' AND v_minor = 1), 'verify', pg_temp.cv('parse'))$q$,
  'is a parse version');

-- one default profile only
SELECT pg_temp.expect_error($q$INSERT INTO ops.pipeline_profile (profile_code, name, is_default) VALUES ('other', 'Other', true)$q$, 'duplicate key');

ROLLBACK;
