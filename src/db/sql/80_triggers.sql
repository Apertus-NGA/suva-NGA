-- ============================================================================
-- File: 80_triggers.sql (integrity: deterministic ids, append-only guards, validation, audit, gates)
-- Date: 2026-11-28
-- Description: Triggers that enforce what a CHECK or a foreign key cannot: deterministic uuid5 ids,
--              append-only facts (with the columns allowed to change), cross-table validation (a step
--              version pinned by the run's profile, citations from the same segmentation, scorer
--              comparability, review/target consistency), version numbering, the German + French pair
--              of every summary version (deferred to commit), the release gate, and the audit log.
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
    ('corpus.ruling', ''), ('corpus.ruling_source_ref', ''), ('corpus.publication_observation', ''),
    ('corpus.consideration', ''), ('corpus.ruling_parse', ''), ('corpus.ingest_issue', ''),
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

CREATE OR REPLACE FUNCTION ops.check_component_version_rule() RETURNS trigger
  LANGUAGE plpgsql AS $$
BEGIN
  IF (SELECT step FROM ops.rule WHERE rule_id = NEW.rule_id)
     IS DISTINCT FROM (SELECT step FROM ops.component_version WHERE component_version_id = NEW.component_version_id) THEN
    RAISE EXCEPTION 'rule % does not belong to the step of component version %', NEW.rule_id, NEW.component_version_id;
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

CREATE OR REPLACE FUNCTION triage.check_assessment_reason() RETURNS trigger
  LANGUAGE plpgsql AS $$
DECLARE
  a triage.assessment%ROWTYPE;
BEGIN
  SELECT * INTO a FROM triage.assessment WHERE assessment_id = NEW.assessment_id;
  IF NOT EXISTS (SELECT 1 FROM ops.component_version_rule r
                 WHERE r.component_version_id = a.component_version_id AND r.rule_id = NEW.rule_id) THEN
    RAISE EXCEPTION 'assessment_reason: rule % is not a rule of the assessment''s step version', NEW.rule_id;
  END IF;
  IF (SELECT reason_code FROM ops.rule WHERE rule_id = NEW.rule_id) <> NEW.reason_code THEN
    RAISE EXCEPTION 'assessment_reason: reason_code must be the rule''s reason code';
  END IF;
  IF NEW.evidence_consideration_id IS NOT NULL
     AND (SELECT segmentation_id FROM corpus.consideration WHERE consideration_id = NEW.evidence_consideration_id) IS DISTINCT FROM a.input_segmentation_id THEN
    RAISE EXCEPTION 'assessment_reason: evidence must come from the assessment''s input segmentation (G1)';
  END IF;
  RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER t30_check BEFORE INSERT ON triage.assessment_reason
  FOR EACH ROW EXECUTE FUNCTION triage.check_assessment_reason();

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
