-- ============================================================================
-- File: 40_gold.sql (truth and expert opinion)
-- Date: 2026-11-28
-- Description: Suva's labels and reference summaries (truth for Q4/2025 and Q1/2026), and expert reviews
--              (opinions about our outputs). Never mixed with predictions. No author, staff code, job title
--              or intranet link column exists anywhere (D-051). Rows derived from judgements/ leave the DB
--              only towards data/derived/ while D-031 is open.
-- SGBD: PostgreSQL 17
-- Doc: docs/DB_DDL_PLANNING.md §12
-- ============================================================================
-- PREREQUISITE: 30_triage.sql
-- ============================================================================

CREATE TABLE IF NOT EXISTS gold.label (
  label_id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ruling_id           uuid REFERENCES corpus.ruling(ruling_id) ON DELETE RESTRICT,
  external_title      text,
  source              ops.label_source NOT NULL,
  in_suva_scope       boolean NOT NULL,
  quarter_label       text CHECK (quarter_label ~ '^[0-9]{4} Q[1-4]$'),
  source_ref          text NOT NULL CHECK (source_ref LIKE 'judgements/%'),
  snapshot_id         uuid NOT NULL REFERENCES ops.source_snapshot(snapshot_id) ON DELETE RESTRICT,
  created_by_run_id   uuid NOT NULL REFERENCES ops.pipeline_run(run_id) ON DELETE RESTRICT,
  created_at          timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT label_target_chk CHECK ((ruling_id IS NULL) <> (external_title IS NULL)),
  CONSTRAINT label_list_quarter_chk CHECK (source <> 'suva_relevance_list' OR quarter_label IS NOT NULL),
  CONSTRAINT label_uq UNIQUE NULLS NOT DISTINCT (source, ruling_id, external_title)
);
COMMENT ON TABLE gold.label IS
  'Suva''s truth: a row of its relevance list or one of its 55 exports. external_title = the cantonal row (Q-28), which has no Federal Court ruling. Append-only. Negatives are a view (closed world, Q-04), never stored.';

CREATE TABLE IF NOT EXISTS gold.expert_review (
  review_id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  target_kind           ops.review_target NOT NULL,
  assessment_id         uuid REFERENCES triage.assessment(assessment_id) ON DELETE RESTRICT,
  summary_version_id    uuid,                                -- FK to summ.summary_version, 85_cross_fks.sql
  verdict               ops.review_verdict NOT NULL,
  reviewed_label        ops.in_suva_scope,
  review_schema_id      uuid NOT NULL REFERENCES ops.json_schema(json_schema_id) ON DELETE RESTRICT,
  payload               jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(payload) = 'object'),
  actor                 text NOT NULL CHECK (length(btrim(actor)) > 0),
  comment               text,
  supersedes_review_id  uuid REFERENCES gold.expert_review(review_id) ON DELETE RESTRICT,
  span_id               uuid REFERENCES ops.span(span_id) ON DELETE RESTRICT,
  created_at            timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT expert_review_target_chk CHECK (
    (target_kind = 'scope' AND assessment_id IS NOT NULL AND summary_version_id IS NULL
       AND verdict IN ('correct', 'incorrect') AND reviewed_label IN ('in_scope', 'out_of_scope'))
    OR (target_kind = 'summary_version' AND summary_version_id IS NOT NULL AND assessment_id IS NULL
       AND verdict IN ('validated', 'rejected') AND reviewed_label IS NULL))
);
COMMENT ON TABLE gold.expert_review IS
  'Expert opinions, append-only and apart from the pipeline''s label (D-066). Scope review V1: correct | incorrect, only on in_scope or out_of_scope. Summary review: validated | rejected. payload follows review_schema_id (empty in V1, ready for V2 without DDL change). Inserted only through gold.submit_review(). actor is a pseudonymous handle (G13).';
CREATE INDEX IF NOT EXISTS expert_review_assessment_ix ON gold.expert_review (assessment_id, created_at DESC);
CREATE INDEX IF NOT EXISTS expert_review_summary_ix ON gold.expert_review (summary_version_id, created_at DESC);

CREATE TABLE IF NOT EXISTS gold.suva_summary (
  suva_summary_id   uuid PRIMARY KEY,
  docket            text NOT NULL CHECK (docket ~ '^[0-9]{1,2}[A-Z]_[0-9]+/[0-9]{4}$'),
  decision_date     date NOT NULL,
  ruling_id         uuid REFERENCES corpus.ruling(ruling_id) ON DELETE RESTRICT,
  ruling_language   ops.lang_code,
  text_de           text NOT NULL CHECK (length(btrim(text_de)) > 0),
  text_fr           text NOT NULL CHECK (length(btrim(text_fr)) > 0),
  bger_url          text NOT NULL CHECK (bger_url ~ '^https://'),
  source_file       text NOT NULL UNIQUE CHECK (source_file LIKE 'judgements/Export\_%' ESCAPE '\'),
  style_observed    text CHECK (style_observed IN ('rule_statement', 'narrative')),
  word_count_de     integer CHECK (word_count_de >= 0),
  word_count_fr     integer CHECK (word_count_fr >= 0),
  snapshot_id       uuid NOT NULL REFERENCES ops.source_snapshot(snapshot_id) ON DELETE RESTRICT,
  created_at        timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE gold.suva_summary IS
  'Suva''s 55 human summaries, parsed (DS5): only docket, dates, Text DE, Text FR and the bger.ch link (D-051). Id = uuid5(''suva_summary|<source_file>''). Append-only.';
