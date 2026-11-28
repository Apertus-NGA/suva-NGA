-- ============================================================================
-- File: 00_extensions.sql (foundation: extensions, owner role, schemas, ENUMs, shared functions)
-- Date: 2026-11-28
-- Description: Everything the other files need. Runs as a superuser (or a role with CREATEROLE and
--              CREATE on the database); ends with SET ROLE suva_owner so that every object created by
--              the next files belongs to the owner role, never to a login role.
-- SGBD: PostgreSQL 17 (pgvector/pgvector:0.8.1-pg17, pinned in docker-compose.yml)
-- Doc: docs/DB_DDL_PLANNING.md §1.4, §7.1, §15
-- ============================================================================
-- PREREQUISITE: none. Idempotent: safe to run twice. A fresh deploy drops the six schemas first.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;  -- uuid_generate_v5, same result as Python uuid.uuid5

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'suva_owner') THEN
    CREATE ROLE suva_owner NOLOGIN;
  END IF;
END $$;
COMMENT ON ROLE suva_owner IS 'Owns every object of the data layer. Never logs in. See docs/DB_DDL_PLANNING.md §15.6.';

DO $$ BEGIN
  EXECUTE format('GRANT CREATE, CONNECT, TEMPORARY ON DATABASE %I TO suva_owner', current_database());
END $$;

SET ROLE suva_owner;

CREATE SCHEMA IF NOT EXISTS ops;
CREATE SCHEMA IF NOT EXISTS corpus;
CREATE SCHEMA IF NOT EXISTS triage;
CREATE SCHEMA IF NOT EXISTS gold;
CREATE SCHEMA IF NOT EXISTS summ;
CREATE SCHEMA IF NOT EXISTS audit;

COMMENT ON SCHEMA ops    IS 'Registry (step versions, models, configuration schemas, rules, profiles) and execution (runs, spans, events, metrics, LLM calls, work, artifacts, releases). Shared ENUMs and helpers. docs/DB_DDL_PLANNING.md §7, §11, §14.';
COMMENT ON SCHEMA corpus IS 'Rulings and what their sources say: identity, publication observations, texts, segmentations, considerations, parses, populations. docs/DB_DDL_PLANNING.md §8.';
COMMENT ON SCHEMA triage IS 'Predictions: one append-only assessment per step, ruling and run; thresholds and rankings. docs/DB_DDL_PLANNING.md §9-§10.';
COMMENT ON SCHEMA gold   IS 'Truth (Suva labels and summaries) and expert opinions (reviews), never mixed with predictions. docs/DB_DDL_PLANNING.md §12.';
COMMENT ON SCHEMA summ   IS 'Summaries: presets, versions (German + French pairs), texts, claims, citations, checks. docs/DB_DDL_PLANNING.md §13.';
COMMENT ON SCHEMA audit  IS 'Change log of every mutable row. docs/DB_DDL_PLANNING.md §14.';

-- ---------------------------------------------------------------------------
-- ENUMs (closed sets). Open vocabularies are lookup tables (ops.reason_code, summ.perspective_anchor).
-- The order of pipeline_step is the pipeline order: views sort on it.
-- ---------------------------------------------------------------------------
DO $$
DECLARE
  e record;
BEGIN
  FOR e IN SELECT * FROM (VALUES
    ('lang_code',              ARRAY['de','fr','it']),
    ('in_suva_scope',          ARRAY['in_scope','out_of_scope','potentially']),
    ('pipeline_step',          ARRAY['ingest','segment','parse','layer1_filter','layer2_judge','justification','ranking','summarise','verify','export']),
    ('run_mode',               ARRAY['LIVE','REPLAY']),
    ('run_kind',               ARRAY['load','ingest','segment','parse','layer1','layer2','justify','rank','summarise','verify','export','refit','eval','full']),
    ('run_status',             ARRAY['running','succeeded','failed','partial','aborted']),
    ('triggered_by',           ARRAY['cli','api','ci']),
    ('registry_status',        ARRAY['draft','active','deprecated','retired']),
    ('bump_kind',              ARRAY['initial','major','minor','patch']),
    ('schema_subject',         ARRAY['step_config','rule_definition','preset_config','review_payload']),
    ('model_role',             ARRAY['judge','generator','repair']),
    ('rule_kind',              ARRAY['keep','drop','flag','signal','check']),
    ('rule_outcome',           ARRAY['fired','not_fired','not_applicable','blocked']),
    ('reason_domain',          ARRAY['triage','verify','ingest','work','summary']),
    ('source_kind',            ARRAY['hf_bger','hf_erwaegungen','hf_structure','bger_neuheiten','bger_ruling_page','judgements_workbook','judgements_export','models_md','team_list_2096','registry_seed']),
    ('span_status',            ARRAY['running','ok','error','skipped','cancelled']),
    ('log_level',              ARRAY['debug','info','warning','error','critical']),
    ('work_status',            ARRAY['todo','running','done','failed','skipped']),
    ('request_kind',           ARRAY['add_judgement','summary']),
    ('request_status',         ARRAY['pending','accepted','done','failed','rejected']),
    ('artifact_kind',          ARRAY['ranked_csv','plain_list','summaries_md','ingestion_report','authored_export','log_bundle','other']),
    ('assessment_outcome',     ARRAY['ok','failed','skipped']),
    ('score_source',           ARRAY['judged','signals_only','net','failed']),
    ('party_check_status',     ARRAY['pass','fail_suva_not_party','fail_party_not_in_block','not_applicable']),
    ('publication_source',     ARRAY['neuheiten','hf_poller','hf_first_seen']),
    ('publication_quality',    ARRAY['exact','approx_first_seen']),
    ('text_source',            ARRAY['hf','bger','entscheidsuche','opencaselaw']),
    ('segmentation_method',    ARRAY['hf_erwaegungen','own_splitter']),
    ('segmentation_status',    ARRAY['ok','partial','failed']),
    ('outcome_kind',           ARRAY['upheld','partly_upheld','dismissed','inadmissible','remanded','other']),
    ('ruling_origin',          ARRAY['base_dataset','user_added']),
    ('subject_source',         ARRAY['neuheiten','hf_legal_area']),
    ('population_definition',  ARRAY['decision_date','publication_date','union','reference']),
    ('population_role',        ARRAY['target','labelled','reference']),
    ('member_basis',           ARRAY['decision_date','publication_exact','publication_approx','reference']),
    ('label_source',           ARRAY['suva_relevance_list','suva_summary_export']),
    ('review_target',          ARRAY['scope','summary_version']),
    ('review_verdict',         ARRAY['correct','incorrect','validated','rejected']),
    ('creator_kind',           ARRAY['pipeline','expert']),
    ('summary_style',          ARRAY['rule_statement','narrative','by_ruling_language']),
    ('summary_version_origin', ARRAY['generated','repaired','regenerated','expert_edit']),
    ('summary_quality',        ARRAY['draft','verified','flagged','rejected']),
    ('claim_section',          ARRAY['facts','law','application','outcome','practice']),
    ('claim_status',           ARRAY['verified','flagged','rejected']),
    ('check_status',           ARRAY['pass','fail','not_applicable'])
  ) AS v(name, labels)
  LOOP
    IF NOT EXISTS (
      SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
      WHERE n.nspname = 'ops' AND t.typname = e.name
    ) THEN
      EXECUTE format('CREATE TYPE ops.%I AS ENUM (%s)', e.name,
                     (SELECT string_agg(quote_literal(l), ', ') FROM unnest(e.labels) AS l));
    END IF;
  END LOOP;
END $$;

COMMENT ON TYPE ops.in_suva_scope IS 'The scope label (D-063): in_scope = True, out_of_scope = False (always with a reason code), potentially = passed layer 1 and not decided yet, or failed and waiting for a retry.';
COMMENT ON TYPE ops.pipeline_step IS 'Pipeline steps in pipeline order (docs/DB_DDL_PLANNING.md §7.3). Views sort on this order.';
COMMENT ON TYPE ops.rule_outcome IS 'What one rule of a step version did for one assessment (triage.assessment_reason): fired = condition true, its effect applies; not_fired = evaluated, condition false; not_applicable = a precondition failed (detail.why); blocked = condition true but neutralised by another rule (detail.blocked_by). F-01, F-02.';

-- ---------------------------------------------------------------------------
-- Shared functions
-- ---------------------------------------------------------------------------

-- Deterministic ids (docs/DB_DDL_PLANNING.md §15.5). Python side: uuid.uuid5(NAMESPACE, name) with the same
-- namespace and the same key string give the same id, on every machine and after every rebuild.
CREATE OR REPLACE FUNCTION ops.uuid5(p_name text) RETURNS uuid
  LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
  RETURN public.uuid_generate_v5('1dd0895a-ba8b-499e-985e-5f92eed68ad3'::uuid, p_name);
COMMENT ON FUNCTION ops.uuid5(text) IS
  'uuid5 over the project namespace 1dd0895a-ba8b-499e-985e-5f92eed68ad3. Key strings: see ops.assign_uuid5().';

-- BEFORE INSERT trigger: sets (or checks) a deterministic id from a prefix and column values.
-- TG_ARGV[0] = id column, TG_ARGV[1] = key prefix, TG_ARGV[2..] = key columns.
-- Key = prefix || '|' || col1 || '|' || col2 ..., each value as its JSON text (dates as YYYY-MM-DD).
CREATE OR REPLACE FUNCTION ops.assign_uuid5() RETURNS trigger
  LANGUAGE plpgsql AS $$
DECLARE
  row_json jsonb := to_jsonb(NEW);
  id_col   text  := TG_ARGV[0];
  key      text  := TG_ARGV[1];
  i        int;
  v        text;
  computed uuid;
BEGIN
  FOR i IN 2 .. TG_NARGS - 1 LOOP
    v := row_json ->> TG_ARGV[i];
    IF v IS NULL THEN
      RAISE EXCEPTION '%.%: key column % is NULL, cannot compute the deterministic id', TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_ARGV[i];
    END IF;
    key := key || '|' || v;
  END LOOP;
  computed := ops.uuid5(key);
  IF row_json ->> id_col IS NULL THEN
    NEW := jsonb_populate_record(NEW, jsonb_build_object(id_col, computed));
  ELSIF (row_json ->> id_col)::uuid <> computed THEN
    RAISE EXCEPTION '%.%: % must be uuid5(%) = %, got %', TG_TABLE_SCHEMA, TG_TABLE_NAME, id_col, key, computed, row_json ->> id_col;
  END IF;
  RETURN NEW;
END $$;

-- BEFORE UPDATE OR DELETE trigger: append-only by default; TG_ARGV lists the columns that may change.
-- Defence in depth with the grants of 90_roles.sql.
CREATE OR REPLACE FUNCTION ops.guard_mutation() RETURNS trigger
  LANGUAGE plpgsql AS $$
DECLARE
  -- Generated columns are excluded: in a BEFORE trigger they are not computed yet.
  allowed text[] := coalesce(TG_ARGV::text[], ARRAY[]::text[]) || ARRAY['updated_at']
                    || ARRAY(SELECT a.attname::text FROM pg_attribute a
                             WHERE a.attrelid = TG_RELID AND a.attgenerated <> '' AND NOT a.attisdropped);
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION '%.% is append-only: DELETE refused (supersede the row instead)', TG_TABLE_SCHEMA, TG_TABLE_NAME;
  END IF;
  IF (to_jsonb(NEW) - allowed) IS DISTINCT FROM (to_jsonb(OLD) - allowed) THEN
    RAISE EXCEPTION '%.%: only % may change (insert a new version instead)', TG_TABLE_SCHEMA, TG_TABLE_NAME, allowed;
  END IF;
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION ops.set_updated_at() RETURNS trigger
  LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END $$;

-- Adds a constraint once (cross-file foreign keys, 85_cross_fks.sql).
CREATE OR REPLACE FUNCTION ops.ensure_constraint(p_table regclass, p_name text, p_definition text) RETURNS void
  LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = p_table AND conname = p_name) THEN
    EXECUTE format('ALTER TABLE %s ADD CONSTRAINT %I %s', p_table, p_name, p_definition);
  END IF;
END $$;

-- The actor and the run of the current session, for audit and expert writes.
CREATE OR REPLACE FUNCTION ops.current_actor() RETURNS text
  LANGUAGE sql STABLE
  RETURN nullif(btrim(current_setting('app.actor', true)), '');

CREATE OR REPLACE FUNCTION ops.current_run_id() RETURNS uuid
  LANGUAGE sql STABLE
  RETURN nullif(btrim(current_setting('app.run_id', true)), '')::uuid;

-- True when a row the caller can see (its xmin) was inserted by the current transaction or one of its
-- subtransactions (savepoints included): a visible row whose inserting transaction is still in progress can only be
-- ours. The 32-bit xmin is widened to the 64-bit id nearest to the current transaction's (within 2^31, the window
-- PostgreSQL keeps unfrozen ids in). Used to seal what a transaction certified at its commit (rule ledgers, F-10).
CREATE OR REPLACE FUNCTION ops.inserted_in_current_xact(p_xmin xid) RETURNS boolean
  LANGUAGE sql VOLATILE
  RETURN (SELECT pg_xact_status((c.cur + ((((p_xmin::text::bigint - (c.cur & 4294967295)) + 2147483648) & 4294967295)
                                          - 2147483648))::text::xid8) = 'in progress'
          FROM (SELECT pg_current_xact_id()::text::bigint AS cur) c);
COMMENT ON FUNCTION ops.inserted_in_current_xact(xid) IS
  'True when the row whose xmin is given was inserted by the current transaction (or a savepoint of it). Only meaningful for a row the caller can see. Seals a committed rule ledger (triage.check_assessment_reason, F-10).';
