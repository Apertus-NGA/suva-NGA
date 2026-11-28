-- ============================================================================
-- File: 90_roles.sql (least-privilege roles and grants)
-- Date: 2026-11-28
-- Description: suva_owner owns everything and never logs in. Three groups: suva_g_pipeline (reads all,
--              inserts facts, updates only lifecycle columns), suva_g_review (expert and UI writes, only
--              through SECURITY DEFINER functions), suva_g_read (reads). Logins carry no password here:
--              passwords come from the environment or a secret store (G13). No UPDATE or DELETE grant on
--              append-only tables (defence in depth with the triggers).
-- SGBD: PostgreSQL 17
-- Doc: docs/DB_DDL_PLANNING.md §15.6
-- ============================================================================
-- PREREQUISITE: 85_cross_fks.sql. Runs as a superuser (or CREATEROLE): RESET ROLE first.
-- ============================================================================

RESET ROLE;

DO $$
DECLARE
  r record;
BEGIN
  FOR r IN SELECT * FROM (VALUES
    ('suva_g_pipeline', 'NOLOGIN', ''),
    ('suva_g_review',   'NOLOGIN', ''),
    ('suva_g_read',     'NOLOGIN', ''),
    ('suva_pipeline',   'LOGIN',   'suva_g_pipeline'),
    ('suva_api',        'LOGIN',   'suva_g_read,suva_g_review'),
    ('suva_report',     'LOGIN',   'suva_g_read')
  ) AS v(name, login, member_of)
  LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r.name) THEN
      EXECUTE format('CREATE ROLE %I %s', r.name, r.login);
    END IF;
    IF r.member_of <> '' THEN
      EXECUTE format('GRANT %s TO %I', r.member_of, r.name);
    END IF;
  END LOOP;
END $$;
ALTER ROLE suva_api SET statement_timeout = '15s';
ALTER ROLE suva_api CONNECTION LIMIT 20;
COMMENT ON ROLE suva_pipeline IS 'Login of the pipeline steps and loaders. Password from the environment, never in the repo (G13).';
COMMENT ON ROLE suva_api IS 'Login of the API and UI: reads, and writes only through gold.submit_review, summ.create_expert_version, ops.submit_request.';
COMMENT ON ROLE suva_report IS 'Read-only login for the report and the judges.';

DO $$ BEGIN
  EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database());
  EXECUTE format('GRANT CONNECT, TEMPORARY ON DATABASE %I TO suva_g_pipeline, suva_g_review, suva_g_read', current_database());
END $$;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO suva_g_pipeline, suva_g_review, suva_g_read;
GRANT USAGE ON SCHEMA ops, corpus, triage, gold, summ TO suva_g_pipeline, suva_g_review, suva_g_read;
GRANT USAGE ON SCHEMA audit TO suva_g_pipeline;

-- reading
GRANT SELECT ON ALL TABLES IN SCHEMA ops, corpus, triage, gold, summ TO suva_g_read, suva_g_pipeline;
GRANT SELECT ON ALL TABLES IN SCHEMA audit TO suva_g_pipeline;
ALTER DEFAULT PRIVILEGES FOR ROLE suva_owner IN SCHEMA ops, corpus, triage, gold, summ
  GRANT SELECT ON TABLES TO suva_g_read, suva_g_pipeline;

-- pipeline: insert facts (never expert reviews)
GRANT INSERT ON ALL TABLES IN SCHEMA ops, corpus, triage, summ TO suva_g_pipeline;
GRANT INSERT ON gold.label, gold.suva_summary TO suva_g_pipeline;

-- pipeline: lifecycle columns only
GRANT UPDATE (status, finished_at, error_summary)                           ON ops.pipeline_run TO suva_g_pipeline;
GRANT UPDATE (status, attempts, last_reason_code, last_error, last_span_id) ON ops.work_item TO suva_g_pipeline;
GRANT UPDATE (status, run_id, ruling_id, status_detail)                     ON ops.user_request TO suva_g_pipeline;
GRANT UPDATE (is_current, superseded_at)                                    ON ops.release TO suva_g_pipeline;
GRANT UPDATE (status, ended_at, error_reason_code, error_message, attributes) ON ops.span TO suva_g_pipeline;
GRANT UPDATE (status) ON ops.json_schema, ops.prompt_version, ops.component_version, ops.rule,
                         ops.pipeline_profile_version, summ.preset_version TO suva_g_pipeline;
GRANT UPDATE (allowed)                                                      ON ops.model TO suva_g_pipeline;
GRANT UPDATE (name, description, is_default, retired_at)                    ON ops.pipeline_profile TO suva_g_pipeline;
GRANT UPDATE (label_de, label_fr, description)                              ON ops.reason_code TO suva_g_pipeline;
GRANT UPDATE (is_primary)                                                   ON corpus.ruling_text, corpus.segmentation TO suva_g_pipeline;
GRANT UPDATE (description, manifest_sha256, frozen_at, is_delivery_default) ON corpus.population TO suva_g_pipeline;
GRANT UPDATE (quality_status, is_current)                                   ON summ.summary_version TO suva_g_pipeline;
GRANT UPDATE (name_de, name_fr, description, selectable, is_mandatory, retired_at) ON summ.preset TO suva_g_pipeline;
GRANT UPDATE (label_de, label_fr, rubric_de, rubric_fr, status)             ON summ.perspective_anchor TO suva_g_pipeline;

-- write functions: nobody by default, then the groups that need them
REVOKE EXECUTE ON FUNCTION gold.submit_review(ops.review_target, uuid, ops.review_verdict, jsonb, text, uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION summ.create_expert_version(uuid, ops.lang_code, text, text, jsonb) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION ops.submit_request(ops.request_kind, text, text, uuid, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gold.submit_review(ops.review_target, uuid, ops.review_verdict, jsonb, text, uuid) TO suva_g_review;
GRANT EXECUTE ON FUNCTION summ.create_expert_version(uuid, ops.lang_code, text, text, jsonb) TO suva_g_review;
GRANT EXECUTE ON FUNCTION ops.submit_request(ops.request_kind, text, text, uuid, text) TO suva_g_review;

-- partitions are created by the owner on behalf of the pipeline
ALTER FUNCTION ops.ensure_log_partitions(date, date) SECURITY DEFINER SET search_path = pg_catalog, pg_temp;
REVOKE EXECUTE ON FUNCTION ops.ensure_log_partitions(date, date) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops.ensure_log_partitions(date, date) TO suva_g_pipeline;
