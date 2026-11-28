-- ============================================================================
-- File: 30_triage.sql (predictions: assessments, thresholds, rankings)
-- Date: 2026-11-28
-- Description: One append-only assessment per (run, ruling, step, repetition), with the scope label
--              in_suva_scope (D-063): layer1_filter -> potentially | out_of_scope; layer2_judge and
--              justification -> potentially (layer 2 scores 0-100); ranking -> in_scope | out_of_scope at
--              the frozen threshold. A failure stays potentially. Every out_of_scope carries a reason (G5).
--              The current label is a view (60_views.sql), never a column.
-- SGBD: PostgreSQL 17
-- Doc: docs/DB_DDL_PLANNING.md §9, §10
-- ============================================================================
-- PREREQUISITE: 20_corpus.sql
-- ============================================================================

CREATE TABLE IF NOT EXISTS triage.assessment (
  assessment_id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id                  uuid NOT NULL REFERENCES ops.pipeline_run(run_id) ON DELETE RESTRICT,
  ruling_id               uuid NOT NULL REFERENCES corpus.ruling(ruling_id) ON DELETE RESTRICT,
  step                    ops.pipeline_step NOT NULL
                            CHECK (step IN ('layer1_filter', 'layer2_judge', 'justification', 'ranking')),
  repetition_idx          smallint NOT NULL DEFAULT 0 CHECK (repetition_idx >= 0),
  component_version_id    uuid NOT NULL REFERENCES ops.component_version(component_version_id) ON DELETE RESTRICT,
  span_id                 uuid NOT NULL REFERENCES ops.span(span_id) ON DELETE RESTRICT,
  upstream_assessment_id  uuid REFERENCES triage.assessment(assessment_id) ON DELETE RESTRICT,
  input_text_id           uuid REFERENCES corpus.ruling_text(text_id) ON DELETE RESTRICT,
  input_segmentation_id   uuid REFERENCES corpus.segmentation(segmentation_id) ON DELETE RESTRICT,
  input_fingerprint       char(64) NOT NULL CHECK (input_fingerprint ~ '^[0-9a-f]{64}$'),
  in_suva_scope           ops.in_suva_scope NOT NULL,
  outcome                 ops.assessment_outcome NOT NULL,
  score_raw               double precision,
  score_0_100             numeric(5,2) CHECK (score_0_100 BETWEEN 0 AND 100),
  score_source            ops.score_source,
  reason_code             text REFERENCES ops.reason_code(code) ON DELETE RESTRICT,
  explanation_de          text,
  mode                    ops.run_mode NOT NULL,
  started_at              timestamptz NOT NULL,
  finished_at             timestamptz,
  created_at              timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT assessment_uq UNIQUE (run_id, ruling_id, step, repetition_idx),
  CONSTRAINT assessment_reason_chk CHECK (in_suva_scope <> 'out_of_scope' OR reason_code IS NOT NULL),
  CONSTRAINT assessment_failure_chk CHECK (outcome <> 'failed' OR in_suva_scope = 'potentially'),
  CONSTRAINT assessment_layer1_chk CHECK (step <> 'layer1_filter' OR in_suva_scope IN ('potentially', 'out_of_scope')),
  CONSTRAINT assessment_middle_chk CHECK (step NOT IN ('layer2_judge', 'justification') OR in_suva_scope = 'potentially'),
  CONSTRAINT assessment_ranking_chk CHECK (step <> 'ranking' OR in_suva_scope <> 'potentially' OR score_source = 'failed'),
  CONSTRAINT assessment_score_chk CHECK (step NOT IN ('layer2_judge', 'ranking') OR outcome <> 'ok' OR score_0_100 IS NOT NULL),
  CONSTRAINT assessment_order_chk CHECK (finished_at IS NULL OR finished_at >= started_at)
);
COMMENT ON TABLE triage.assessment IS
  'One step''s verdict on one ruling in one run. Append-only (trigger + grants). The step version must be the one the run''s profile pins (trigger). input_fingerprint = SHA-256 over every input: a rerun skips identical inputs. docs/DB_DDL_PLANNING.md §10.1.';
COMMENT ON COLUMN triage.assessment.score_0_100 IS 'Layer 2: 100 x P(Ja)/(P(Ja)+P(Nein)) (D-063). Layer 1: the filter''s score for a drop (score_source = net). Ranking: the final score.';
CREATE INDEX IF NOT EXISTS assessment_ruling_ix ON triage.assessment (ruling_id, step, created_at DESC);
CREATE INDEX IF NOT EXISTS assessment_run_ix ON triage.assessment (run_id, step);

CREATE TABLE IF NOT EXISTS triage.assessment_reason (
  assessment_id              uuid NOT NULL REFERENCES triage.assessment(assessment_id) ON DELETE RESTRICT,
  ordinal                    smallint NOT NULL CHECK (ordinal >= 1),
  rule_id                    uuid NOT NULL REFERENCES ops.rule(rule_id) ON DELETE RESTRICT,
  reason_code                text NOT NULL REFERENCES ops.reason_code(code) ON DELETE RESTRICT,
  effect                     ops.rule_kind NOT NULL CHECK (effect <> 'check'),
  evidence_field             text,
  evidence_consideration_id  uuid REFERENCES corpus.consideration(consideration_id) ON DELETE RESTRICT,
  char_start                 integer CHECK (char_start >= 0),
  char_end                   integer,
  matched_text               text CHECK (matched_text IS NULL OR char_length(matched_text) <= 300),
  PRIMARY KEY (assessment_id, ordinal),
  CONSTRAINT assessment_reason_evidence_chk CHECK (effect NOT IN ('keep', 'drop') OR evidence_field IS NOT NULL OR evidence_consideration_id IS NOT NULL),
  CONSTRAINT assessment_reason_offsets_chk CHECK ((char_start IS NULL) = (char_end IS NULL) AND (char_end IS NULL OR char_end >= char_start))
);
COMMENT ON TABLE triage.assessment_reason IS 'Every rule that fired (layer1.reasons[]), with the exact rule version and its evidence. Rules evaluated without firing are debug events (§11.3). Append-only.';

CREATE TABLE IF NOT EXISTS triage.llm_judgement (
  assessment_id       uuid PRIMARY KEY REFERENCES triage.assessment(assessment_id) ON DELETE RESTRICT,
  llm_call_id         uuid NOT NULL REFERENCES ops.llm_call(llm_call_id) ON DELETE RESTRICT,
  prompt_version_id   uuid NOT NULL REFERENCES ops.prompt_version(prompt_version_id) ON DELETE RESTRICT,
  requested_model     text NOT NULL,
  served_model        text,
  question_language   ops.lang_code NOT NULL,
  logprob_yes         double precision,
  logprob_no          double precision,
  p_yes               double precision CHECK (p_yes BETWEEN 0 AND 1),
  top_logprobs        jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(top_logprobs) = 'array'),
  yes_no_in_top       boolean NOT NULL,
  text_chars_total    integer NOT NULL CHECK (text_chars_total >= 0),
  text_chars_sent     integer NOT NULL CHECK (text_chars_sent >= 0),
  truncation          text NOT NULL,
  input_tokens        integer CHECK (input_tokens >= 0),
  created_at          timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT llm_judgement_sent_chk CHECK (text_chars_sent <= text_chars_total)
);
COMMENT ON TABLE triage.llm_judgement IS 'Layer-2 detail: the Ja/Nein log-probabilities, p_yes, the raw top_logprobs, the truncation applied. Append-only.';

CREATE TABLE IF NOT EXISTS triage.justification (
  assessment_id               uuid PRIMARY KEY REFERENCES triage.assessment(assessment_id) ON DELETE RESTRICT,
  llm_call_id                 uuid NOT NULL REFERENCES ops.llm_call(llm_call_id) ON DELETE RESTRICT,
  repair_llm_call_id          uuid REFERENCES ops.llm_call(llm_call_id) ON DELETE RESTRICT,
  json_valid                  boolean NOT NULL,
  key_statement               text CHECK (key_statement IS NULL OR char_length(key_statement) <= 300),
  offered_consideration_count integer NOT NULL CHECK (offered_consideration_count >= 0),
  party_check_status          ops.party_check_status NOT NULL,
  party_check_rule_id         uuid REFERENCES ops.rule(rule_id) ON DELETE RESTRICT,
  party_check_detail          jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(party_check_detail) = 'object'),
  created_at                  timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE triage.justification IS 'Step 4 detail: the JSON protocol output (key statement, cited considerations) and the party check (no act attributed to Suva unless Suva is a party). Append-only.';

CREATE TABLE IF NOT EXISTS triage.assessment_evidence (
  assessment_id     uuid NOT NULL REFERENCES triage.assessment(assessment_id) ON DELETE RESTRICT,
  consideration_id  uuid NOT NULL REFERENCES corpus.consideration(consideration_id) ON DELETE RESTRICT,
  role              text NOT NULL CHECK (role IN ('supports', 'cited')),
  PRIMARY KEY (assessment_id, consideration_id)
);
COMMENT ON TABLE triage.assessment_evidence IS 'Considerations an assessment cites, by FK. Trigger: from the assessment''s input segmentation only (G1). Append-only.';

CREATE TABLE IF NOT EXISTS triage.threshold (
  threshold_id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ranking_component_version_id  uuid NOT NULL REFERENCES ops.component_version(component_version_id) ON DELETE RESTRICT,
  scorer_component_version_id   uuid NOT NULL REFERENCES ops.component_version(component_version_id) ON DELETE RESTRICT,
  layer1_component_version_id   uuid REFERENCES ops.component_version(component_version_id) ON DELETE RESTRICT,
  metric                        text NOT NULL DEFAULT 'F2',
  value_0_100                   numeric(5,2) NOT NULL CHECK (value_0_100 BETWEEN 0 AND 100),
  chosen_on_population_id       uuid NOT NULL REFERENCES corpus.population(population_id) ON DELETE RESTRICT,
  reported_on_population_id     uuid REFERENCES corpus.population(population_id) ON DELETE RESTRICT,
  metrics                       jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metrics) = 'object'),
  policy                        text NOT NULL,
  frozen_at                     timestamptz NOT NULL,
  created_by_run_id             uuid NOT NULL REFERENCES ops.pipeline_run(run_id) ON DELETE RESTRICT,
  created_at                    timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE triage.threshold IS
  'A frozen F2 threshold and where it comes from (population chosen on and reported on, metrics with CI, policy D-021 point 8). Valid only for scores of the same scorer step, major and minor (D-064; trigger on ranking entries). Append-only.';

CREATE TABLE IF NOT EXISTS triage.ranking (
  ranking_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id          uuid NOT NULL REFERENCES ops.pipeline_run(run_id) ON DELETE RESTRICT,
  population_id   uuid NOT NULL REFERENCES corpus.population(population_id) ON DELETE RESTRICT,
  threshold_id    uuid NOT NULL REFERENCES triage.threshold(threshold_id) ON DELETE RESTRICT,
  tie_break       text NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ranking_uq UNIQUE (run_id, population_id)
);
COMMENT ON TABLE triage.ranking IS 'A ranking of one population in one run, at one threshold. A rank belongs to (run, population), never to a ruling (D-046, D-050). Append-only.';

CREATE TABLE IF NOT EXISTS triage.ranking_entry (
  ranking_id            uuid NOT NULL REFERENCES triage.ranking(ranking_id) ON DELETE RESTRICT,
  ruling_id             uuid NOT NULL REFERENCES corpus.ruling(ruling_id) ON DELETE RESTRICT,
  assessment_id         uuid NOT NULL REFERENCES triage.assessment(assessment_id) ON DELETE RESTRICT,
  score_assessment_id   uuid NOT NULL REFERENCES triage.assessment(assessment_id) ON DELETE RESTRICT,
  final_score_0_100     numeric(5,2) CHECK (final_score_0_100 BETWEEN 0 AND 100),
  rank                  integer NOT NULL CHECK (rank >= 1),
  above_threshold       boolean NOT NULL,
  in_top10              boolean GENERATED ALWAYS AS (rank <= 10) STORED,
  in_top30              boolean GENERATED ALWAYS AS (rank <= 30) STORED,
  PRIMARY KEY (ranking_id, ruling_id),
  CONSTRAINT ranking_entry_rank_uq UNIQUE (ranking_id, rank)
);
COMMENT ON TABLE triage.ranking_entry IS
  'Rank of one ruling in one ranking. assessment_id = the ranking-step assessment (the label); score_assessment_id = the assessment that gave the score (layer 2 if judged, layer 1 if dropped by the filter). final_score is NULL only for a failed judgement (potentially). Append-only.';
