-- ============================================================================
-- File: 80_triggers.sql (integrity: deterministic ids, append-only guards, validation, audit, gates)
-- Date: 2026-11-28
-- Description: Triggers that enforce what a CHECK or a foreign key cannot: deterministic uuid5 ids,
--              append-only facts (with the columns allowed to change), cross-table validation (a step
--              version pinned by the run's profile, citations from the same segmentation, scorer
--              comparability, review/target consistency, each ledger row against its rule version, a layer-2
--              judgement against its own call (DDL-1), a
--              source row either loaded or excluded, serialised per snapshot across sessions, an exclusion's
--              reason and file kind), version numbering,
--              the rule set of a used or pinned step version sealed, the German + French pair of every summary
--              version and the complete rule ledger of every assessment (both deferred to commit; a ledger is
--              sealed once committed), the release gate, and the audit log.
--              Trigger names start with a number: PostgreSQL fires same-event triggers in name order.
-- SGBD: PostgreSQL 17
-- Doc: docs/DB_DDL_PLANNING.md §7.8, §8.3, §9.2, §10.2, §12.2, §13.5, §13.7, §15.7
-- ============================================================================
-- PREREQUISITE: 70_functions.sql
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1. Deterministic ids (key strings documented in each table's comment)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TRIGGER t00_uuid5 BEFORE INSERT ON ops.json_schema
  FOR EACH ROW EXECUTE FUNCTION ops.assign_uuid5('json_schema_id', 'json_schema', 'schema_code', 'v_major', 'v_minor', 'v_patch');
CREATE OR REPLACE TRIGGER t00_uuid5 BEFORE INSERT ON ops.model
  FOR EACH ROW EXECUTE FUNCTION ops.assign_uuid5('model_id', 'model', 'gateway_id');
CREATE OR REPLACE TRIGGER t00_uuid5 BEFORE INSERT ON ops.prompt_version
  FOR EACH ROW EXECUTE FUNCTION ops.assign_uuid5('prompt_version_id', 'prompt', 'role', 'v_major', 'v_minor', 'v_patch');
CREATE OR REPLACE TRIGGER t00_uuid5 BEFORE INSERT ON ops.component_version
  FOR EACH ROW EXECUTE FUNCTION ops.assign_uuid5('component_version_id', 'cv', 'step', 'v_major', 'v_minor', 'v_patch');
CREATE OR REPLACE TRIGGER t00_uuid5 BEFORE INSERT ON ops.rule
  FOR EACH ROW EXECUTE FUNCTION ops.assign_uuid5('rule_id', 'rule', 'rule_code', 'v_major', 'v_minor', 'v_patch');
CREATE OR REPLACE TRIGGER t00_uuid5 BEFORE INSERT ON ops.pipeline_profile_version
  FOR EACH ROW EXECUTE FUNCTION ops.assign_uuid5('profile_version_id', 'profile', 'profile_code', 'v_major', 'v_minor', 'v_patch');
CREATE OR REPLACE TRIGGER t00_uuid5 BEFORE INSERT ON corpus.ruling
  FOR EACH ROW EXECUTE FUNCTION ops.assign_uuid5('ruling_id', 'bger', 'docket', 'decision_date');
CREATE OR REPLACE TRIGGER t00_uuid5 BEFORE INSERT ON corpus.ruling_text
  FOR EACH ROW EXECUTE FUNCTION ops.assign_uuid5('text_id', 'text', 'ruling_id', 'source', 'content_sha256');
CREATE OR REPLACE TRIGGER t00_uuid5 BEFORE INSERT ON corpus.segmentation
  FOR EACH ROW EXECUTE FUNCTION ops.assign_uuid5('segmentation_id', 'segmentation', 'text_id', 'component_version_id');
CREATE OR REPLACE TRIGGER t00_uuid5 BEFORE INSERT ON corpus.consideration
  FOR EACH ROW EXECUTE FUNCTION ops.assign_uuid5('consideration_id', 'consideration', 'segmentation_id', 'ordinal');
CREATE OR REPLACE TRIGGER t00_uuid5 BEFORE INSERT ON corpus.population
  FOR EACH ROW EXECUTE FUNCTION ops.assign_uuid5('population_id', 'population', 'code');
CREATE OR REPLACE TRIGGER t00_uuid5 BEFORE INSERT ON gold.suva_summary
  FOR EACH ROW EXECUTE FUNCTION ops.assign_uuid5('suva_summary_id', 'suva_summary', 'source_file');
CREATE OR REPLACE TRIGGER t00_uuid5 BEFORE INSERT ON summ.preset_version
  FOR EACH ROW EXECUTE FUNCTION ops.assign_uuid5('preset_version_id', 'preset_version', 'preset_code', 'v_major', 'v_minor', 'v_patch');
CREATE OR REPLACE TRIGGER t00_uuid5 BEFORE INSERT ON summ.summary
  FOR EACH ROW EXECUTE FUNCTION ops.assign_uuid5('summary_id', 'summary', 'ruling_id', 'preset_code');

-- ---------------------------------------------------------------------------
-- 2. Append-only guards (no argument = nothing may change; arguments = the columns allowed to change)
-- ---------------------------------------------------------------------------
DO $$
DECLARE
  t record;
BEGIN
  FOR t IN SELECT * FROM (VALUES
    -- fully append-only facts
    ('ops.source_snapshot', ''), ('ops.blob', ''), ('ops.run_metric', ''), ('ops.llm_call', ''),
    ('ops.llm_call_example', ''), ('ops.artifact', ''), ('ops.component_version_model', ''),
    ('ops.component_version_prompt', ''), ('ops.component_version_rule', ''), ('ops.pipeline_profile_step', ''),
    ('ops.log_event', ''), ('audit.change_log', ''),
    ('corpus.ruling', ''), ('corpus.ruling_source_ref', ''), ('corpus.publication_observation', ''), ('corpus.subject_observation', ''),
    ('corpus.consideration', ''), ('corpus.ruling_parse', ''), ('corpus.ingest_issue', ''), ('corpus.ingest_exclusion', ''),
    ('corpus.population_member', ''),
    ('triage.assessment', ''), ('triage.assessment_reason', ''), ('triage.llm_judgement', ''),
    ('triage.justification', ''), ('triage.assessment_evidence', ''), ('triage.threshold', ''),
    ('triage.ranking', ''), ('triage.ranking_entry', ''),
    ('gold.label', ''), ('gold.expert_review', ''), ('gold.suva_summary', ''),
    ('summ.summary', ''), ('summ.preset_version_prompt', ''), ('summ.summary_text', ''),
    ('summ.summary_claim', ''), ('summ.claim_citation', ''), ('summ.verification_check', ''),
    -- registry and configuration: insert-only except the listed columns
    ('ops.reason_code', 'label_de,label_fr,description'),
    ('ops.model', 'allowed'),
    ('ops.json_schema', 'status'), ('ops.prompt_version', 'status'), ('ops.component_version', 'status'),
    ('ops.rule', 'status'), ('ops.pipeline_profile_version', 'status'), ('summ.preset_version', 'status'),
    ('ops.pipeline_profile', 'name,description,is_default,retired_at'),
    ('summ.perspective_anchor', 'label_de,label_fr,rubric_de,rubric_fr,status'),
    ('summ.preset', 'name_de,name_fr,description,selectable,is_mandatory,retired_at'),
    -- execution rows with a lifecycle
    ('ops.pipeline_run', 'status,finished_at,error_summary'),
    ('ops.work_item', 'status,attempts,last_reason_code,last_error,last_span_id'),
    ('ops.user_request', 'status,run_id,ruling_id,status_detail'),
    ('ops.release', 'is_current,superseded_at'),
    ('corpus.ruling_text', 'is_primary'),
    ('corpus.segmentation', 'is_primary'),
    ('corpus.population', 'description,manifest_sha256,frozen_at,is_delivery_default'),
    ('summ.summary_version', 'quality_status,is_current')
  ) AS v(tbl, allowed)
  LOOP
    EXECUTE format(
      'CREATE OR REPLACE TRIGGER t10_guard BEFORE UPDATE OR DELETE ON %s FOR EACH ROW EXECUTE FUNCTION ops.guard_mutation(%s)',
      t.tbl,
      (SELECT coalesce(string_agg(quote_literal(c), ', '), '') FROM unnest(string_to_array(nullif(t.allowed, ''), ',')) AS c));
  END LOOP;
END $$;

-- ---------------------------------------------------------------------------
-- 3. updated_at
-- ---------------------------------------------------------------------------
DO $$
DECLARE
  tbl text;
BEGIN
  FOREACH tbl IN ARRAY ARRAY[
    'ops.reason_code', 'ops.json_schema', 'ops.prompt_version', 'ops.component_version', 'ops.rule',
    'ops.pipeline_profile', 'ops.pipeline_profile_version', 'ops.work_item', 'ops.user_request', 'ops.release',
    'corpus.ruling_text', 'corpus.segmentation', 'corpus.population',
    'summ.perspective_anchor', 'summ.preset', 'summ.preset_version', 'summ.summary_version']
  LOOP
    EXECUTE format('CREATE OR REPLACE TRIGGER t20_updated_at BEFORE UPDATE ON %s FOR EACH ROW EXECUTE FUNCTION ops.set_updated_at()', tbl);
  END LOOP;
END $$;

-- ---------------------------------------------------------------------------
-- 4. Validation
-- ---------------------------------------------------------------------------

-- A configuration, definition or payload must point to a schema of the right subject.
-- TG_ARGV[0] = schema id column, TG_ARGV[1] = expected subject.
CREATE OR REPLACE FUNCTION ops.check_schema_subject() RETURNS trigger
  LANGUAGE plpgsql AS $$
DECLARE
  sid uuid := (to_jsonb(NEW) ->> TG_ARGV[0])::uuid;
  got ops.schema_subject;
BEGIN
  SELECT subject INTO got FROM ops.json_schema WHERE json_schema_id = sid;
  IF got IS DISTINCT FROM TG_ARGV[1]::ops.schema_subject THEN
    RAISE EXCEPTION '%.%: % must point to a % schema, got %', TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_ARGV[0], TG_ARGV[1], got;
  END IF;
  RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER t30_schema_subject BEFORE INSERT ON ops.component_version
  FOR EACH ROW EXECUTE FUNCTION ops.check_schema_subject('config_schema_id', 'step_config');
CREATE OR REPLACE TRIGGER t30_schema_subject BEFORE INSERT ON ops.rule
  FOR EACH ROW EXECUTE FUNCTION ops.check_schema_subject('definition_schema_id', 'rule_definition');
CREATE OR REPLACE TRIGGER t30_schema_subject BEFORE INSERT ON summ.preset_version
  FOR EACH ROW EXECUTE FUNCTION ops.check_schema_subject('config_schema_id', 'preset_config');
CREATE OR REPLACE TRIGGER t30_schema_subject BEFORE INSERT ON gold.expert_review
  FOR EACH ROW EXECUTE FUNCTION ops.check_schema_subject('review_schema_id', 'review_payload');

-- A rule belongs to the step of its version. The rule set of a version is sealed once an assessment uses it or a
-- profile pins it (F-10): a rule added later would leave every certified ledger of that version incomplete, or let
-- a row for it be added afterwards. Reloading an identical binding (the registry loader's ON CONFLICT DO NOTHING)
-- passes; anything else is a new version.
CREATE OR REPLACE FUNCTION ops.check_component_version_rule() RETURNS trigger
  LANGUAGE plpgsql AS $$
DECLARE
  cv ops.component_version%ROWTYPE;
BEGIN
  SELECT * INTO cv FROM ops.component_version WHERE component_version_id = NEW.component_version_id;
  IF (SELECT step FROM ops.rule WHERE rule_id = NEW.rule_id) IS DISTINCT FROM cv.step THEN
    RAISE EXCEPTION 'rule % does not belong to the step of component version %', NEW.rule_id, NEW.component_version_id;
  END IF;
  IF (EXISTS (SELECT 1 FROM triage.assessment a WHERE a.component_version_id = NEW.component_version_id)
      OR EXISTS (SELECT 1 FROM ops.pipeline_profile_step ps WHERE ps.component_version_id = NEW.component_version_id))
     AND NOT EXISTS (SELECT 1 FROM ops.component_version_rule r
                     WHERE r.component_version_id = NEW.component_version_id AND r.rule_id = NEW.rule_id
                       AND r.ordinal = NEW.ordinal AND r.enabled = NEW.enabled AND r.params = NEW.params) THEN
    RAISE EXCEPTION 'component version % (%): its rule set is sealed (used by an assessment or pinned by a profile); a new or changed rule binding needs a new version',
      cv.version_label, cv.step;
  END IF;
  RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER t30_check BEFORE INSERT ON ops.component_version_rule
  FOR EACH ROW EXECUTE FUNCTION ops.check_component_version_rule();

CREATE OR REPLACE FUNCTION ops.check_profile_step() RETURNS trigger
  LANGUAGE plpgsql AS $$
DECLARE
  cv ops.component_version%ROWTYPE;
  profile_major smallint;
BEGIN
  SELECT * INTO cv FROM ops.component_version WHERE component_version_id = NEW.component_version_id;
  IF cv.step <> NEW.step THEN
    RAISE EXCEPTION 'profile step %: component version % is a % version', NEW.step, cv.version_label, cv.step;
  END IF;
  SELECT v_major INTO profile_major FROM ops.pipeline_profile_version WHERE profile_version_id = NEW.profile_version_id;
  IF profile_major >= 1 AND cv.v_major = 0 THEN
    RAISE EXCEPTION 'a profile version V%.x cannot pin the draft step version % (%)', profile_major, cv.version_label, NEW.step;
  END IF;
  RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER t30_check BEFORE INSERT ON ops.pipeline_profile_step
  FOR EACH ROW EXECUTE FUNCTION ops.check_profile_step();

CREATE OR REPLACE FUNCTION ops.check_span() RETURNS trigger
  LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'ops.span is append-only: DELETE refused';
  END IF;
  IF TG_OP = 'UPDATE' THEN
    IF OLD.status <> 'running' THEN
      RAISE EXCEPTION 'span % is already closed (%)', OLD.span_id, OLD.status;
    END IF;
    IF NEW.status = 'running' THEN
      RAISE EXCEPTION 'span %: an update must close it', OLD.span_id;
    END IF;
    IF (to_jsonb(NEW) - ARRAY['status', 'ended_at', 'duration_ms', 'error_reason_code', 'error_message', 'attributes'])
       IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['status', 'ended_at', 'duration_ms', 'error_reason_code', 'error_message', 'attributes']) THEN
      RAISE EXCEPTION 'span %: closing may change only status, ended_at, error fields and attributes', OLD.span_id;
    END IF;
  END IF;
  IF NEW.parent_span_id IS NOT NULL
     AND (SELECT run_id FROM ops.span WHERE span_id = NEW.parent_span_id) IS DISTINCT FROM NEW.run_id THEN
    RAISE EXCEPTION 'span %: parent span belongs to another run', NEW.span_id;
  END IF;
  RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER t10_guard BEFORE INSERT OR UPDATE OR DELETE ON ops.span
  FOR EACH ROW EXECUTE FUNCTION ops.check_span();

CREATE OR REPLACE FUNCTION ops.check_llm_call_example() RETURNS trigger
  LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.example_ruling_id IS NOT NULL
     AND NEW.example_ruling_id = (SELECT ruling_id FROM ops.llm_call WHERE llm_call_id = NEW.llm_call_id) THEN
    RAISE EXCEPTION 'few-shot hygiene: a call cannot use the judged ruling as its own example (D-021 point 8)';
  END IF;
  RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER t30_check BEFORE INSERT ON ops.llm_call_example
  FOR EACH ROW EXECUTE FUNCTION ops.check_llm_call_example();

CREATE OR REPLACE FUNCTION ops.check_release() RETURNS trigger
  LANGUAGE plpgsql AS $$
BEGIN
  IF (SELECT profile_code FROM ops.pipeline_profile_version WHERE profile_version_id = NEW.profile_version_id) <> NEW.profile_code THEN
    RAISE EXCEPTION 'release: profile version % does not belong to profile %', NEW.profile_version_id, NEW.profile_code;
  END IF;
  IF (SELECT pr.profile_version_id FROM triage.ranking rk JOIN ops.pipeline_run pr ON pr.run_id = rk.run_id
      WHERE rk.ranking_id = NEW.ranking_id) IS DISTINCT FROM NEW.profile_version_id THEN
    RAISE EXCEPTION 'release: ranking % was not produced by profile version %', NEW.ranking_id, NEW.profile_version_id;
  END IF;
  RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER t30_check BEFORE INSERT ON ops.release
  FOR EACH ROW EXECUTE FUNCTION ops.check_release();

-- Release gate (AFTER, so the release row is visible to the gate functions).
CREATE OR REPLACE FUNCTION ops.release_gate() RETURNS trigger
  LANGUAGE plpgsql AS $$
DECLARE
  problems jsonb;
BEGIN
  IF NEW.is_current AND (TG_OP = 'INSERT' OR NOT OLD.is_current) THEN
    SELECT jsonb_agg(jsonb_build_object('problem', g.problem, 'ruling_id', g.ruling_id))
      INTO problems
      FROM (SELECT * FROM triage.release_gate_problems(NEW.release_id) LIMIT 20) g;
    IF problems IS NOT NULL THEN
      RAISE EXCEPTION 'release % cannot become current: % (first 20 shown)', NEW.release_id, problems;
    END IF;
  END IF;
  RETURN NULL;
END $$;
CREATE OR REPLACE TRIGGER t40_gate AFTER INSERT OR UPDATE OF is_current ON ops.release
  FOR EACH ROW EXECUTE FUNCTION ops.release_gate();

-- corpus ---------------------------------------------------------------------

CREATE OR REPLACE FUNCTION corpus.check_text_hash() RETURNS trigger
  LANGUAGE plpgsql AS $$
BEGIN
  IF encode(sha256(convert_to(NEW.content, 'UTF8')), 'hex') <> NEW.content_sha256 THEN
    RAISE EXCEPTION '%.%: content_sha256 is not the SHA-256 of content', TG_TABLE_SCHEMA, TG_TABLE_NAME;
  END IF;
  RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER t30_hash BEFORE INSERT ON corpus.ruling_text
  FOR EACH ROW EXECUTE FUNCTION corpus.check_text_hash();
CREATE OR REPLACE TRIGGER t30_hash BEFORE INSERT ON corpus.consideration
  FOR EACH ROW EXECUTE FUNCTION corpus.check_text_hash();

CREATE OR REPLACE FUNCTION corpus.check_consideration_parent() RETURNS trigger
  LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.parent_consideration_id IS NOT NULL
     AND (SELECT segmentation_id FROM corpus.consideration WHERE consideration_id = NEW.parent_consideration_id) IS DISTINCT FROM NEW.segmentation_id THEN
    RAISE EXCEPTION 'consideration %: parent belongs to another segmentation', NEW.e_number;
  END IF;
  RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER t31_parent BEFORE INSERT ON corpus.consideration
  FOR EACH ROW EXECUTE FUNCTION corpus.check_consideration_parent();

CREATE OR REPLACE FUNCTION corpus.check_parse() RETURNS trigger
  LANGUAGE plpgsql AS $$
BEGIN
  IF (SELECT ruling_id FROM corpus.ruling_text WHERE text_id = NEW.text_id) IS DISTINCT FROM NEW.ruling_id THEN
    RAISE EXCEPTION 'ruling_parse: text % does not belong to ruling %', NEW.text_id, NEW.ruling_id;
  END IF;
  RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER t30_check BEFORE INSERT ON corpus.ruling_parse
  FOR EACH ROW EXECUTE FUNCTION corpus.check_parse();

-- Ingest exclusion ledger (F-04): decided by an ingest step version, for an ingest reason (or OUT_OF_WINDOW), on a
-- snapshot of the kind of file the source row comes from (otherwise the closure of that snapshot is wrong).
CREATE OR REPLACE FUNCTION corpus.check_ingest_exclusion() RETURNS trigger
  LANGUAGE plpgsql AS $$
DECLARE
  r_domain   ops.reason_domain;
  snap_kind  ops.source_kind;
  kinds      ops.source_kind[] := CASE NEW.source
                                    WHEN 'hf_decision_id' THEN ARRAY['hf_bger']::ops.source_kind[]
                                    WHEN 'aza_id'         THEN ARRAY['bger_neuheiten', 'bger_ruling_page']::ops.source_kind[]
                                    WHEN 'team_list_2096' THEN ARRAY['team_list_2096']::ops.source_kind[]
                                  END;
BEGIN
  IF (SELECT step FROM ops.component_version WHERE component_version_id = NEW.component_version_id) IS DISTINCT FROM 'ingest' THEN
    RAISE EXCEPTION 'ingest_exclusion %/%: component version % is not an ingest version', NEW.source, NEW.external_id, NEW.component_version_id;
  END IF;
  SELECT rc.domain INTO r_domain FROM ops.reason_code rc WHERE rc.code = NEW.reason_code;
  IF FOUND AND r_domain <> 'ingest' AND NEW.reason_code <> 'OUT_OF_WINDOW' THEN  -- an unknown code: the foreign key says so
    RAISE EXCEPTION 'ingest_exclusion %/%: reason % is not an ingest reason (domain %); only ingest reasons and OUT_OF_WINDOW exclude a source row',
      NEW.source, NEW.external_id, NEW.reason_code, r_domain;
  END IF;
  SELECT s.source INTO snap_kind FROM ops.source_snapshot s WHERE s.snapshot_id = NEW.snapshot_id;
  IF FOUND AND kinds IS NOT NULL AND snap_kind <> ALL (kinds) THEN  -- an unknown source: ingest_exclusion_source_chk says so
    RAISE EXCEPTION 'ingest_exclusion %/%: a % row cannot come from a % snapshot (expected %)', NEW.source, NEW.external_id, NEW.source, snap_kind, kinds;
  END IF;
  RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER t30_check BEFORE INSERT ON corpus.ingest_exclusion
  FOR EACH ROW EXECUTE FUNCTION corpus.check_ingest_exclusion();

-- A source row of a snapshot is either loaded (corpus.ruling_source_ref) or excluded (corpus.ingest_exclusion),
-- never both: checked on insert into either table, so the closure row_count = refs + exclusions counts each row once.
-- Across sessions the check is serialised per snapshot: corpus.lock_source_rows() takes a transaction-level advisory
-- lock, so a second transaction writing rows of the same snapshot waits for the first to end, and its EXISTS (a new
-- statement under READ COMMITTED, the pipeline's isolation) then sees the first one's committed rows. One lock per
-- snapshot, not per row: a load writes ~195,000 rows in one transaction, more distinct locks than the shared lock
-- table holds (max_locks_per_transaction). The loader takes the same lock before it writes (src/ingest/hf_base.py),
-- so its closure check never runs beside another load of the snapshot.
CREATE OR REPLACE FUNCTION corpus.lock_source_rows(p_snapshot_id uuid) RETURNS void
  LANGUAGE sql VOLATILE AS $$
  SELECT pg_advisory_xact_lock(hashtextextended('corpus.source_row|' || p_snapshot_id::text, 0));
$$;
COMMENT ON FUNCTION corpus.lock_source_rows(uuid) IS 'Serialises the writes of source refs and ingest exclusions of one snapshot across transactions (advisory lock held until commit or rollback): the exclusivity trigger t31_exclusive and the HF loader take it.';

CREATE OR REPLACE FUNCTION corpus.check_source_row_exclusive() RETURNS trigger
  LANGUAGE plpgsql AS $$
BEGIN
  PERFORM corpus.lock_source_rows(NEW.snapshot_id);
  IF TG_TABLE_NAME = 'ingest_exclusion' THEN
    IF EXISTS (SELECT 1 FROM corpus.ruling_source_ref r
               WHERE r.source = NEW.source AND r.external_id = NEW.external_id AND r.snapshot_id = NEW.snapshot_id) THEN
      RAISE EXCEPTION 'ingest_exclusion %/%: this source row of snapshot % is loaded (corpus.ruling_source_ref), it cannot also be excluded',
        NEW.source, NEW.external_id, NEW.snapshot_id;
    END IF;
  ELSIF EXISTS (SELECT 1 FROM corpus.ingest_exclusion x
                WHERE x.snapshot_id = NEW.snapshot_id AND x.source = NEW.source AND x.external_id = NEW.external_id) THEN
    RAISE EXCEPTION 'ruling_source_ref %/%: this source row of snapshot % is excluded (corpus.ingest_exclusion), it cannot also be loaded',
      NEW.source, NEW.external_id, NEW.snapshot_id;
  END IF;
  RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER t31_exclusive BEFORE INSERT ON corpus.ingest_exclusion
  FOR EACH ROW EXECUTE FUNCTION corpus.check_source_row_exclusive();
CREATE OR REPLACE TRIGGER t31_exclusive BEFORE INSERT ON corpus.ruling_source_ref
  FOR EACH ROW EXECUTE FUNCTION corpus.check_source_row_exclusive();

CREATE OR REPLACE FUNCTION corpus.check_population_frozen() RETURNS trigger
  LANGUAGE plpgsql AS $$
BEGIN
  IF TG_TABLE_NAME = 'population' THEN
    IF OLD.frozen_at IS NOT NULL THEN
      RAISE EXCEPTION 'population % is frozen since %', OLD.code, OLD.frozen_at;
    END IF;
  ELSIF (SELECT frozen_at FROM corpus.population WHERE population_id = NEW.population_id) IS NOT NULL THEN
    RAISE EXCEPTION 'population % is frozen: no new member', NEW.population_id;
  END IF;
  RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER t30_frozen BEFORE UPDATE ON corpus.population
  FOR EACH ROW EXECUTE FUNCTION corpus.check_population_frozen();
CREATE OR REPLACE TRIGGER t30_frozen BEFORE INSERT ON corpus.population_member
  FOR EACH ROW EXECUTE FUNCTION corpus.check_population_frozen();

-- triage ---------------------------------------------------------------------

CREATE OR REPLACE FUNCTION triage.check_assessment() RETURNS trigger
  LANGUAGE plpgsql AS $$
DECLARE
  run ops.pipeline_run%ROWTYPE;
  up  triage.assessment%ROWTYPE;
BEGIN
  SELECT * INTO run FROM ops.pipeline_run WHERE run_id = NEW.run_id;
  IF NOT EXISTS (
    SELECT 1 FROM ops.pipeline_profile_step ps
    WHERE ps.profile_version_id = run.profile_version_id AND ps.step = NEW.step
      AND ps.component_version_id = NEW.component_version_id) THEN
    RAISE EXCEPTION 'assessment: component version % is not the % version pinned by the run''s profile version (D-064)',
      NEW.component_version_id, NEW.step;
  END IF;
  IF NEW.mode <> run.mode THEN
    RAISE EXCEPTION 'assessment: mode % differs from the run''s mode %', NEW.mode, run.mode;
  END IF;
  IF (SELECT s.run_id FROM ops.span s WHERE s.span_id = NEW.span_id) IS DISTINCT FROM NEW.run_id THEN
    RAISE EXCEPTION 'assessment: span % belongs to another run', NEW.span_id;
  END IF;
  IF NEW.upstream_assessment_id IS NOT NULL THEN
    SELECT * INTO up FROM triage.assessment WHERE assessment_id = NEW.upstream_assessment_id;
    IF up.ruling_id <> NEW.ruling_id OR up.step >= NEW.step THEN
      RAISE EXCEPTION 'assessment: upstream must be an earlier step of the same ruling';
    END IF;
  END IF;
  IF NEW.input_text_id IS NOT NULL
     AND (SELECT ruling_id FROM corpus.ruling_text WHERE text_id = NEW.input_text_id) <> NEW.ruling_id THEN
    RAISE EXCEPTION 'assessment: input text belongs to another ruling';
  END IF;
  IF NEW.input_segmentation_id IS NOT NULL
     AND (SELECT text_id FROM corpus.segmentation WHERE segmentation_id = NEW.input_segmentation_id) IS DISTINCT FROM NEW.input_text_id THEN
    RAISE EXCEPTION 'assessment: input segmentation is not a segmentation of the input text';
  END IF;
  RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER t30_check BEFORE INSERT ON triage.assessment
  FOR EACH ROW EXECUTE FUNCTION triage.check_assessment();

-- One ledger row (F-10). The assessment was inserted in this transaction: a ledger is written with its assessment
-- and sealed at that commit, so no row is added to a committed assessment. The rule is an enabled rule of the
-- assessment's step version, at its ordinal, with its reason code and its kind as effect. A not_applicable row says
-- why (layer 1: one of five preconditions; text_absent only without a text). Only a keep is blocked, by another
-- enabled flag of the version (t50_ledger checks that it fired; layer 1 also names the closed rubric). full_text
-- evidence: on a text, a fired or blocked row carries the offsets of its match, which is the exact slice of the
-- stored text; without a text, nothing was searched, so only not_applicable, or a rule whose check fires on the missing
-- text itself (definition.check text_unavailable, V1.2.0's L1_KEEP_TEXT_UNAVAILABLE: fired, no offsets, no match).
CREATE OR REPLACE FUNCTION triage.check_assessment_reason() RETURNS trigger
  LANGUAGE plpgsql AS $$
DECLARE
  a        record;
  vr       record;
  br       record;
  t_len    integer;
  t_slice  text;
  why      text := NEW.detail ->> 'why';
  blocker  text := NEW.detail ->> 'blocked_by';
BEGIN
  SELECT t.*, t.xmin AS row_xmin INTO a FROM triage.assessment t WHERE t.assessment_id = NEW.assessment_id;
  IF FOUND AND NOT ops.inserted_in_current_xact(a.row_xmin) THEN
    RAISE EXCEPTION 'assessment_reason: assessment % is already committed: its ledger was certified at that commit and is sealed (a ledger is written in the transaction of its assessment)',
      NEW.assessment_id;
  END IF;
  SELECT cvr.ordinal, cvr.enabled, rl.rule_code, rl.kind, rl.reason_code, rl.definition ->> 'check' AS check_name INTO vr
  FROM ops.component_version_rule cvr JOIN ops.rule rl ON rl.rule_id = cvr.rule_id
  WHERE cvr.component_version_id = a.component_version_id AND cvr.rule_id = NEW.rule_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'assessment_reason: rule % is not a rule of the assessment''s step version', NEW.rule_id;
  END IF;
  IF vr.reason_code <> NEW.reason_code THEN
    RAISE EXCEPTION 'assessment_reason: reason_code must be the rule''s reason code';
  END IF;
  IF NEW.effect <> vr.kind THEN
    RAISE EXCEPTION 'assessment_reason: rule %: effect % must be the rule''s kind %', vr.rule_code, NEW.effect, vr.kind;
  END IF;
  IF NOT vr.enabled THEN
    RAISE EXCEPTION 'assessment_reason: rule % is disabled in the assessment''s step version', vr.rule_code;
  END IF;
  IF NEW.ordinal <> vr.ordinal THEN
    RAISE EXCEPTION 'assessment_reason: rule %: ordinal % must be the rule''s ordinal % in the step version', vr.rule_code, NEW.ordinal, vr.ordinal;
  END IF;
  IF NEW.evidence_consideration_id IS NOT NULL
     AND (SELECT segmentation_id FROM corpus.consideration WHERE consideration_id = NEW.evidence_consideration_id) IS DISTINCT FROM a.input_segmentation_id THEN
    RAISE EXCEPTION 'assessment_reason: evidence must come from the assessment''s input segmentation (G1)';
  END IF;
  IF NEW.outcome = 'not_applicable' THEN
    IF coalesce(btrim(why), '') = '' THEN
      RAISE EXCEPTION 'assessment_reason: rule %: not_applicable needs detail.why', vr.rule_code;
    END IF;
    IF a.step = 'layer1_filter'
       AND why NOT IN ('court_not_listed', 'letter_not_listed', 'rubric_missing', 'text_absent', 'gegenstand_absent') THEN
      RAISE EXCEPTION 'assessment_reason: rule %: detail.why % is not one of court_not_listed, letter_not_listed, rubric_missing, text_absent, gegenstand_absent',
        vr.rule_code, why;
    END IF;
    IF why = 'text_absent' AND a.input_text_id IS NOT NULL THEN
      RAISE EXCEPTION 'assessment_reason: rule %: why text_absent, but the assessment has an input text (%): its text rules run on it',
        vr.rule_code, a.input_text_id;
    END IF;
  END IF;
  IF NEW.outcome = 'blocked' THEN
    IF vr.kind <> 'keep' THEN
      RAISE EXCEPTION 'assessment_reason: rule %: only a keep rule can be blocked, not a % rule', vr.rule_code, vr.kind;
    END IF;
    SELECT cvr.enabled, rl.kind, rl.rule_id INTO br
    FROM ops.component_version_rule cvr JOIN ops.rule rl ON rl.rule_id = cvr.rule_id
    WHERE cvr.component_version_id = a.component_version_id AND rl.rule_code = blocker;
    IF NOT FOUND OR NOT br.enabled OR br.kind <> 'flag' OR br.rule_id = NEW.rule_id THEN
      RAISE EXCEPTION 'assessment_reason: rule %: blocked needs detail.blocked_by naming another enabled flag rule of the same step version, got %',
        vr.rule_code, coalesce(blocker, 'nothing');
    END IF;
    IF a.step = 'layer1_filter' AND coalesce(btrim(NEW.detail ->> 'closed_rubric_match'), '') = '' THEN
      RAISE EXCEPTION 'assessment_reason: rule %: a blocked layer-1 row needs detail.closed_rubric_match (the closed rubric that blocks it)', vr.rule_code;
    END IF;
  END IF;
  IF NEW.evidence_field = 'full_text' THEN
    IF a.input_text_id IS NULL THEN
      IF NEW.outcome IN ('not_fired', 'blocked') OR NEW.char_start IS NOT NULL OR NEW.matched_text IS NOT NULL THEN
        RAISE EXCEPTION 'assessment_reason: rule %: the assessment has no input text, so no text was searched: a text rule is not_applicable (why text_absent), and only a rule that fires on the missing text names full_text, without offsets or match',
          vr.rule_code;
      END IF;
      -- a fired row without offsets is evidence of the missing text only: no other rule can claim a keep on it
      IF NEW.outcome = 'fired' AND vr.check_name IS DISTINCT FROM 'text_unavailable' THEN
        RAISE EXCEPTION 'assessment_reason: rule %: the assessment has no input text, so only a rule whose check is text_unavailable can fire on full_text (check %)',
          vr.rule_code, coalesce(vr.check_name, 'none');
      END IF;
    ELSE
      IF NEW.outcome IN ('fired', 'blocked') AND NEW.char_start IS NULL THEN
        RAISE EXCEPTION 'assessment_reason: rule %: a full-text match needs its offsets in the input text', vr.rule_code;
      END IF;
      IF NEW.char_start IS NOT NULL THEN
        -- content || '' reads the whole text first: substr() on a compressed text decompresses only a byte prefix,
        -- which can end inside a multibyte character ("invalid byte sequence", PostgreSQL 17).
        SELECT char_length, left(substr(content || '', NEW.char_start + 1, NEW.char_end - NEW.char_start), 300)
          INTO t_len, t_slice
          FROM corpus.ruling_text WHERE text_id = a.input_text_id;
        IF NEW.char_end > t_len THEN
          RAISE EXCEPTION 'assessment_reason: rule %: offsets [%, %) beyond the input text (% characters)', vr.rule_code, NEW.char_start, NEW.char_end, t_len;
        END IF;
        IF NEW.matched_text IS DISTINCT FROM t_slice THEN
          RAISE EXCEPTION 'assessment_reason: rule %: matched_text must equal the input text slice [%, %)', vr.rule_code, NEW.char_start, NEW.char_end;
        END IF;
      END IF;
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER t30_check BEFORE INSERT ON triage.assessment_reason
  FOR EACH ROW EXECUTE FUNCTION triage.check_assessment_reason();

-- The ledger of one assessment is complete and agrees with its decision (F-10). Deferred to commit, because the
-- assessment row is written before its ledger rows. Every drop (out_of_scope) is certified, whatever its outcome
-- (G5); a failed or skipped assessment that keeps the ruling (potentially) needs no ledger. Completeness applies to
-- a version with rules; check rules are excepted: assessment_reason refuses effect 'check' (they are recorded by
-- summ.verification_check and triage.justification instead). A blocked row's blocker fired in the same ledger.
-- Layer 1: potentially <=> a keep fired, and the reason is the decisive rule's (the fired keep, else the fired
-- drop, with the lowest ordinal; F-13).
CREATE OR REPLACE FUNCTION triage.check_assessment_ledger() RETURNS trigger
  LANGUAGE plpgsql AS $$
DECLARE
  missing    text;
  extra      text;
  unfired    text;
  keeps      integer;
  keep_code  text;
  drops      integer;
  drop_code  text;
BEGIN
  IF NEW.outcome <> 'ok' AND NEW.in_suva_scope <> 'out_of_scope' THEN
    RETURN NULL;
  END IF;
  IF EXISTS (SELECT 1 FROM ops.component_version_rule cvr JOIN ops.rule rl ON rl.rule_id = cvr.rule_id
             WHERE cvr.component_version_id = NEW.component_version_id AND cvr.enabled AND rl.kind <> 'check') THEN
    SELECT string_agg(v.rule_code, ', ' ORDER BY v.ordinal) FILTER (WHERE ar.rule_id IS NULL),
           string_agg(coalesce(rl.rule_code, ar.rule_id::text), ', ' ORDER BY ar.ordinal) FILTER (WHERE v.rule_id IS NULL)
      INTO missing, extra
      FROM (SELECT cvr.rule_id, cvr.ordinal, rl2.rule_code
              FROM ops.component_version_rule cvr JOIN ops.rule rl2 ON rl2.rule_id = cvr.rule_id
             WHERE cvr.component_version_id = NEW.component_version_id AND cvr.enabled AND rl2.kind <> 'check') v
      FULL JOIN (SELECT * FROM triage.assessment_reason WHERE assessment_id = NEW.assessment_id) ar ON ar.rule_id = v.rule_id
      LEFT JOIN ops.rule rl ON rl.rule_id = ar.rule_id;
    IF missing IS NOT NULL THEN
      RAISE EXCEPTION 'assessment % (%): ledger incomplete, no row for the enabled rule(s) %', NEW.assessment_id, NEW.step, missing;
    END IF;
    IF extra IS NOT NULL THEN
      RAISE EXCEPTION 'assessment % (%): ledger rows for rule(s) % that are not enabled rules of its step version', NEW.assessment_id, NEW.step, extra;
    END IF;
    SELECT string_agg(rl.rule_code || ' (by ' || coalesce(ar.detail ->> 'blocked_by', '?') || ')', ', ' ORDER BY ar.ordinal)
      INTO unfired
      FROM triage.assessment_reason ar JOIN ops.rule rl ON rl.rule_id = ar.rule_id
     WHERE ar.assessment_id = NEW.assessment_id AND ar.outcome = 'blocked'
       AND NOT EXISTS (SELECT 1 FROM triage.assessment_reason b JOIN ops.rule brl ON brl.rule_id = b.rule_id
                       WHERE b.assessment_id = NEW.assessment_id AND b.outcome = 'fired' AND brl.rule_code = ar.detail ->> 'blocked_by');
    IF unfired IS NOT NULL THEN
      RAISE EXCEPTION 'assessment % (%): blocked rule(s) % name a blocker that did not fire', NEW.assessment_id, NEW.step, unfired;
    END IF;
  END IF;
  IF NEW.step <> 'layer1_filter' THEN
    RETURN NULL;
  END IF;
  SELECT count(*) FILTER (WHERE effect = 'keep' AND outcome = 'fired'),
         (array_agg(reason_code ORDER BY ordinal) FILTER (WHERE effect = 'keep' AND outcome = 'fired'))[1],
         count(*) FILTER (WHERE effect = 'drop' AND outcome = 'fired'),
         (array_agg(reason_code ORDER BY ordinal) FILTER (WHERE effect = 'drop' AND outcome = 'fired'))[1]
    INTO keeps, keep_code, drops, drop_code
    FROM triage.assessment_reason WHERE assessment_id = NEW.assessment_id;
  IF NEW.in_suva_scope = 'potentially' THEN
    IF keeps = 0 THEN
      RAISE EXCEPTION 'assessment % (layer1_filter): kept (potentially) but no keep rule fired', NEW.assessment_id;
    END IF;
    IF NEW.reason_code IS DISTINCT FROM keep_code THEN
      RAISE EXCEPTION 'assessment % (layer1_filter): reason_code % must be % (the fired keep rule with the lowest ordinal)',
        NEW.assessment_id, coalesce(NEW.reason_code, 'NULL'), keep_code;
    END IF;
  ELSIF NEW.in_suva_scope = 'out_of_scope' THEN
    IF keeps > 0 THEN
      RAISE EXCEPTION 'assessment % (layer1_filter): dropped (out_of_scope) although keep rule % fired', NEW.assessment_id, keep_code;
    END IF;
    IF drops = 0 THEN
      RAISE EXCEPTION 'assessment % (layer1_filter): dropped (out_of_scope) but no drop rule fired', NEW.assessment_id;
    END IF;
    IF NEW.reason_code IS DISTINCT FROM drop_code THEN
      RAISE EXCEPTION 'assessment % (layer1_filter): reason_code % must be % (the fired drop rule with the lowest ordinal)',
        NEW.assessment_id, coalesce(NEW.reason_code, 'NULL'), drop_code;
    END IF;
  END IF;
  RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS t50_ledger ON triage.assessment;
CREATE CONSTRAINT TRIGGER t50_ledger AFTER INSERT ON triage.assessment
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION triage.check_assessment_ledger();

-- TG_ARGV[0] = the step the detail row belongs to.
CREATE OR REPLACE FUNCTION triage.check_detail_step() RETURNS trigger
  LANGUAGE plpgsql AS $$
BEGIN
  IF (SELECT step FROM triage.assessment WHERE assessment_id = NEW.assessment_id) IS DISTINCT FROM TG_ARGV[0]::ops.pipeline_step THEN
    RAISE EXCEPTION '%.% rows belong to % assessments only', TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_ARGV[0];
  END IF;
  RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER t30_check BEFORE INSERT ON triage.llm_judgement
  FOR EACH ROW EXECUTE FUNCTION triage.check_detail_step('layer2_judge');
CREATE OR REPLACE TRIGGER t30_check BEFORE INSERT ON triage.justification
  FOR EACH ROW EXECUTE FUNCTION triage.check_detail_step('justification');

-- Layer 2 (DDL-1, D-079; docs/LAYER2.md): a judgement points to its own call. The call has the assessment's run and
-- ruling and the step layer2_judge; the judgement's prompt is the one the call sent and one its step version declares;
-- the requested model is the call's, the served model the call's model field or, without it, its header. Fires after
-- t30_check, which has already checked that the assessment is a layer2_judge one.
CREATE OR REPLACE FUNCTION triage.check_llm_judgement() RETURNS trigger
  LANGUAGE plpgsql AS $$
DECLARE
  a triage.assessment%ROWTYPE;
  c ops.llm_call%ROWTYPE;
BEGIN
  SELECT * INTO a FROM triage.assessment WHERE assessment_id = NEW.assessment_id;
  SELECT * INTO c FROM ops.llm_call WHERE llm_call_id = NEW.llm_call_id;
  IF c.run_id IS DISTINCT FROM a.run_id OR c.ruling_id IS DISTINCT FROM a.ruling_id OR c.step <> 'layer2_judge' THEN
    RAISE EXCEPTION 'llm_judgement %: call % is not a layer2_judge call of the same run and ruling', NEW.assessment_id, NEW.llm_call_id;
  END IF;
  IF c.prompt_version_id IS DISTINCT FROM NEW.prompt_version_id THEN
    RAISE EXCEPTION 'llm_judgement %: prompt version % is not the one call % sent (%)',
      NEW.assessment_id, NEW.prompt_version_id, NEW.llm_call_id, coalesce(c.prompt_version_id::text, 'none');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM ops.component_version_prompt cvp
                 WHERE cvp.component_version_id = a.component_version_id AND cvp.prompt_version_id = NEW.prompt_version_id) THEN
    RAISE EXCEPTION 'llm_judgement %: prompt version % is not a prompt of the assessment''s step version', NEW.assessment_id, NEW.prompt_version_id;
  END IF;
  IF NEW.requested_model IS DISTINCT FROM c.requested_model THEN
    RAISE EXCEPTION 'llm_judgement %: requested model % is not the call''s (%)', NEW.assessment_id, NEW.requested_model, c.requested_model;
  END IF;
  IF NEW.served_model IS DISTINCT FROM coalesce(c.served_model, c.served_model_header) THEN
    RAISE EXCEPTION 'llm_judgement %: served model % is not the call''s (%)',
      NEW.assessment_id, coalesce(NEW.served_model, 'none'), coalesce(c.served_model, c.served_model_header, 'none');
  END IF;
  RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER t31_call BEFORE INSERT ON triage.llm_judgement
  FOR EACH ROW EXECUTE FUNCTION triage.check_llm_judgement();

CREATE OR REPLACE FUNCTION triage.check_evidence() RETURNS trigger
  LANGUAGE plpgsql AS $$
BEGIN
  IF (SELECT segmentation_id FROM corpus.consideration WHERE consideration_id = NEW.consideration_id)
     IS DISTINCT FROM (SELECT input_segmentation_id FROM triage.assessment WHERE assessment_id = NEW.assessment_id) THEN
    RAISE EXCEPTION 'assessment_evidence: the consideration is not from the assessment''s input segmentation (G1)';
  END IF;
  RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER t30_check BEFORE INSERT ON triage.assessment_evidence
  FOR EACH ROW EXECUTE FUNCTION triage.check_evidence();

CREATE OR REPLACE FUNCTION triage.check_threshold() RETURNS trigger
  LANGUAGE plpgsql AS $$
BEGIN
  IF (SELECT step FROM ops.component_version WHERE component_version_id = NEW.scorer_component_version_id) <> 'layer2_judge'
     OR (SELECT step FROM ops.component_version WHERE component_version_id = NEW.ranking_component_version_id) <> 'ranking'
     OR (NEW.layer1_component_version_id IS NOT NULL
         AND (SELECT step FROM ops.component_version WHERE component_version_id = NEW.layer1_component_version_id) <> 'layer1_filter') THEN
    RAISE EXCEPTION 'threshold: scorer must be a layer2_judge version, ranking a ranking version, layer1 a layer1_filter version';
  END IF;
  RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER t30_check BEFORE INSERT ON triage.threshold
  FOR EACH ROW EXECUTE FUNCTION triage.check_threshold();

CREATE OR REPLACE FUNCTION triage.check_ranking_entry() RETURNS trigger
  LANGUAGE plpgsql AS $$
DECLARE
  rk     triage.ranking%ROWTYPE;
  th     triage.threshold%ROWTYPE;
  a      triage.assessment%ROWTYPE;
  sa     triage.assessment%ROWTYPE;
  scv    ops.component_version%ROWTYPE;
  tcv    ops.component_version%ROWTYPE;
BEGIN
  SELECT * INTO rk FROM triage.ranking WHERE ranking_id = NEW.ranking_id;
  SELECT * INTO th FROM triage.threshold WHERE threshold_id = rk.threshold_id;
  SELECT * INTO a  FROM triage.assessment WHERE assessment_id = NEW.assessment_id;
  SELECT * INTO sa FROM triage.assessment WHERE assessment_id = NEW.score_assessment_id;
  IF NOT EXISTS (SELECT 1 FROM corpus.population_member WHERE population_id = rk.population_id AND ruling_id = NEW.ruling_id) THEN
    RAISE EXCEPTION 'ranking_entry: ruling % is not a member of the ranked population', NEW.ruling_id;
  END IF;
  IF a.step <> 'ranking' OR a.ruling_id <> NEW.ruling_id OR a.run_id <> rk.run_id THEN
    RAISE EXCEPTION 'ranking_entry: assessment_id must be the ranking assessment of this ruling in the ranking''s run';
  END IF;
  IF sa.ruling_id <> NEW.ruling_id OR sa.step NOT IN ('layer1_filter', 'layer2_judge') THEN
    RAISE EXCEPTION 'ranking_entry: score_assessment_id must be a layer1_filter or layer2_judge assessment of this ruling';
  END IF;
  IF sa.step = 'layer2_judge' THEN
    SELECT * INTO scv FROM ops.component_version WHERE component_version_id = sa.component_version_id;
    SELECT * INTO tcv FROM ops.component_version WHERE component_version_id = th.scorer_component_version_id;
    IF scv.v_major <> tcv.v_major OR scv.v_minor <> tcv.v_minor THEN
      RAISE EXCEPTION 'ranking_entry: score from layer2_judge % is not comparable with the threshold''s scorer % (same major.minor required, D-064)',
        scv.version_label, tcv.version_label;
    END IF;
  END IF;
  IF (NEW.final_score_0_100 IS NULL) <> (a.in_suva_scope = 'potentially') THEN
    RAISE EXCEPTION 'ranking_entry: final score is NULL exactly for a failed judgement (potentially)';
  END IF;
  IF NEW.final_score_0_100 IS NOT NULL AND NEW.above_threshold <> (NEW.final_score_0_100 >= th.value_0_100) THEN
    RAISE EXCEPTION 'ranking_entry: above_threshold must equal final_score >= threshold (%)', th.value_0_100;
  END IF;
  IF NEW.final_score_0_100 IS NOT NULL AND (a.in_suva_scope = 'in_scope') <> NEW.above_threshold THEN
    RAISE EXCEPTION 'ranking_entry: the ranking label must agree with above_threshold';
  END IF;
  RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER t30_check BEFORE INSERT ON triage.ranking_entry
  FOR EACH ROW EXECUTE FUNCTION triage.check_ranking_entry();

-- gold -----------------------------------------------------------------------

CREATE OR REPLACE FUNCTION gold.check_expert_review() RETURNS trigger
  LANGUAGE plpgsql AS $$
DECLARE
  sup gold.expert_review%ROWTYPE;
BEGIN
  IF NEW.target_kind = 'scope'
     AND (SELECT in_suva_scope FROM triage.assessment WHERE assessment_id = NEW.assessment_id) IS DISTINCT FROM NEW.reviewed_label THEN
    RAISE EXCEPTION 'expert_review: reviewed_label must be the label of the reviewed assessment';
  END IF;
  IF NEW.supersedes_review_id IS NOT NULL THEN
    SELECT * INTO sup FROM gold.expert_review WHERE review_id = NEW.supersedes_review_id;
    IF sup.target_kind <> NEW.target_kind
       OR sup.assessment_id IS DISTINCT FROM NEW.assessment_id
       OR sup.summary_version_id IS DISTINCT FROM NEW.summary_version_id THEN
      RAISE EXCEPTION 'expert_review: a review supersedes only a review of the same target';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER t31_check BEFORE INSERT ON gold.expert_review
  FOR EACH ROW EXECUTE FUNCTION gold.check_expert_review();

-- summ -----------------------------------------------------------------------

CREATE OR REPLACE FUNCTION summ.before_insert_version() RETURNS trigger
  LANGUAGE plpgsql AS $$
DECLARE
  s summ.summary%ROWTYPE;
BEGIN
  SELECT * INTO s FROM summ.summary WHERE summary_id = NEW.summary_id FOR UPDATE;   -- serialises version numbering
  NEW.version_no := coalesce((SELECT max(version_no) FROM summ.summary_version WHERE summary_id = NEW.summary_id), 0) + 1;
  IF NEW.parent_version_id IS NOT NULL
     AND (SELECT summary_id FROM summ.summary_version WHERE summary_version_id = NEW.parent_version_id) <> NEW.summary_id THEN
    RAISE EXCEPTION 'summary_version: parent belongs to another summary';
  END IF;
  IF (SELECT preset_code FROM summ.preset_version WHERE preset_version_id = NEW.preset_version_id) <> s.preset_code THEN
    RAISE EXCEPTION 'summary_version: preset version is not a version of preset %', s.preset_code;
  END IF;
  IF (SELECT step FROM ops.component_version WHERE component_version_id = NEW.component_version_id) <> 'summarise' THEN
    RAISE EXCEPTION 'summary_version: component version must be a summarise version';
  END IF;
  IF (SELECT t.ruling_id FROM corpus.segmentation g JOIN corpus.ruling_text t ON t.text_id = g.text_id
      WHERE g.segmentation_id = NEW.source_segmentation_id) <> s.ruling_id THEN
    RAISE EXCEPTION 'summary_version: source segmentation belongs to another ruling';
  END IF;
  RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER t30_check BEFORE INSERT ON summ.summary_version
  FOR EACH ROW EXECUTE FUNCTION summ.before_insert_version();

-- A version is complete only with exactly one German and one French text (checked at commit).
CREATE OR REPLACE FUNCTION summ.check_version_pair() RETURNS trigger
  LANGUAGE plpgsql AS $$
BEGIN
  IF (SELECT count(*) FILTER (WHERE language = 'de') = 1 AND count(*) FILTER (WHERE language = 'fr') = 1 AND count(*) = 2
      FROM summ.summary_text WHERE summary_version_id = NEW.summary_version_id) IS NOT TRUE THEN
    RAISE EXCEPTION 'summary version % must hold exactly one German and one French text (D-067)', NEW.summary_version_id;
  END IF;
  RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS t50_pair ON summ.summary_version;
CREATE CONSTRAINT TRIGGER t50_pair AFTER INSERT ON summ.summary_version
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION summ.check_version_pair();

CREATE OR REPLACE FUNCTION summ.check_summary_text() RETURNS trigger
  LANGUAGE plpgsql AS $$
BEGIN
  IF (SELECT creator_kind FROM summ.summary_version WHERE summary_version_id = NEW.summary_version_id) = 'pipeline'
     AND NEW.llm_call_id IS NULL THEN
    RAISE EXCEPTION 'summary_text: a pipeline text needs its own LLM call, written from the source (D-014)';
  END IF;
  RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER t30_check BEFORE INSERT ON summ.summary_text
  FOR EACH ROW EXECUTE FUNCTION summ.check_summary_text();

CREATE OR REPLACE FUNCTION summ.check_citation() RETURNS trigger
  LANGUAGE plpgsql AS $$
DECLARE
  cons corpus.consideration%ROWTYPE;
  seg  uuid;
BEGIN
  SELECT * INTO cons FROM corpus.consideration WHERE consideration_id = NEW.consideration_id;
  SELECT v.source_segmentation_id INTO seg
  FROM summ.summary_claim c
  JOIN summ.summary_text t ON t.summary_text_id = c.summary_text_id
  JOIN summ.summary_version v ON v.summary_version_id = t.summary_version_id
  WHERE c.claim_id = NEW.claim_id;
  IF cons.segmentation_id IS DISTINCT FROM seg THEN
    RAISE EXCEPTION 'claim_citation: consideration % is not from the version''s source segmentation (G1)', cons.cid;
  END IF;
  IF NOT cons.is_citable THEN
    RAISE EXCEPTION 'claim_citation: consideration % is unnumbered and cannot be cited', cons.cid;
  END IF;
  RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER t30_check BEFORE INSERT ON summ.claim_citation
  FOR EACH ROW EXECUTE FUNCTION summ.check_citation();

CREATE OR REPLACE FUNCTION summ.check_verification() RETURNS trigger
  LANGUAGE plpgsql AS $$
BEGIN
  IF (SELECT step = 'verify' AND kind = 'check' FROM ops.rule WHERE rule_id = NEW.rule_id) IS NOT TRUE THEN
    RAISE EXCEPTION 'verification_check: rule must be a verify check rule';
  END IF;
  RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER t30_check BEFORE INSERT ON summ.verification_check
  FOR EACH ROW EXECUTE FUNCTION summ.check_verification();

-- ---------------------------------------------------------------------------
-- 5. Audit (AFTER; arguments = primary-key columns)
-- ---------------------------------------------------------------------------
DO $$
DECLARE
  t record;
BEGIN
  FOR t IN SELECT * FROM (VALUES
    ('ops.reason_code',              'INSERT OR UPDATE', 'code'),
    ('ops.json_schema',              'INSERT OR UPDATE', 'json_schema_id'),
    ('ops.prompt_version',           'INSERT OR UPDATE', 'prompt_version_id'),
    ('ops.component_version',        'INSERT OR UPDATE', 'component_version_id'),
    ('ops.rule',                     'INSERT OR UPDATE', 'rule_id'),
    ('ops.model',                    'INSERT OR UPDATE', 'model_id'),
    ('ops.pipeline_profile',         'INSERT OR UPDATE', 'profile_code'),
    ('ops.pipeline_profile_version', 'INSERT OR UPDATE', 'profile_version_id'),
    ('ops.release',                  'INSERT OR UPDATE', 'release_id'),
    ('ops.user_request',             'INSERT OR UPDATE', 'request_id'),
    ('ops.pipeline_run',             'UPDATE',           'run_id'),
    ('ops.work_item',                'UPDATE',           'run_id,ruling_id,step,target_ref'),
    ('corpus.ruling_text',           'UPDATE',           'text_id'),
    ('corpus.segmentation',          'UPDATE',           'segmentation_id'),
    ('corpus.population',            'INSERT OR UPDATE', 'population_id'),
    ('summ.perspective_anchor',      'INSERT OR UPDATE', 'perspective'),
    ('summ.preset',                  'INSERT OR UPDATE', 'preset_code'),
    ('summ.preset_version',          'INSERT OR UPDATE', 'preset_version_id'),
    ('summ.summary_version',         'UPDATE',           'summary_version_id'),
    ('gold.expert_review',           'INSERT',           'review_id')
  ) AS v(tbl, events, pk)
  LOOP
    EXECUTE format('CREATE OR REPLACE TRIGGER t90_audit AFTER %s ON %s FOR EACH ROW EXECUTE FUNCTION audit.log_change(%s)',
                   t.events, t.tbl,
                   (SELECT string_agg(quote_literal(c), ', ') FROM unnest(string_to_array(t.pk, ',')) AS c));
  END LOOP;
END $$;
