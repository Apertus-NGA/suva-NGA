-- ============================================================================
-- File: 11_ops_execution.sql (execution: what ran)
-- Date: 2026-11-28
-- Description: Source snapshots, runs (each pinned to a profile version), spans (units of work), metrics,
--              work items (resume, progress), user requests (add a judgement, request a summary), LLM calls
--              (every raw output), few-shot examples used, blobs, releases and hashed artifacts.
--              Foreign keys to corpus/triage/gold/summ are added in 85_cross_fks.sql.
-- SGBD: PostgreSQL 17
-- Doc: docs/DB_DDL_PLANNING.md §11, §14
-- ============================================================================
-- PREREQUISITE: 10_ops_registry.sql
-- ============================================================================

CREATE TABLE IF NOT EXISTS ops.source_snapshot (
  snapshot_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source         ops.source_kind NOT NULL,
  revision       text,
  uri            text NOT NULL,
  file_sha256    char(64) NOT NULL CHECK (file_sha256 ~ '^[0-9a-f]{64}$'),
  byte_size      bigint CHECK (byte_size >= 0),
  row_count      bigint CHECK (row_count >= 0),
  retrieved_at   timestamptz NOT NULL,
  notes          text,
  created_at     timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT source_snapshot_uq UNIQUE NULLS NOT DISTINCT (source, revision, file_sha256)
);
COMMENT ON TABLE ops.source_snapshot IS 'Every input file a load read: source, revision (HF commit), hash, size. The root of every lineage. Append-only.';

CREATE TABLE IF NOT EXISTS ops.pipeline_run (
  run_id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  parent_run_id        uuid REFERENCES ops.pipeline_run(run_id) ON DELETE RESTRICT,
  profile_version_id   uuid NOT NULL REFERENCES ops.pipeline_profile_version(profile_version_id) ON DELETE RESTRICT,
  kind                 ops.run_kind NOT NULL,
  mode                 ops.run_mode NOT NULL,
  status               ops.run_status NOT NULL DEFAULT 'running',
  git_commit           char(40) CHECK (git_commit ~ '^[0-9a-f]{40}$'),
  git_dirty            boolean NOT NULL,
  params               jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(params) = 'object'),
  params_sha256        char(64) NOT NULL CHECK (params_sha256 ~ '^[0-9a-f]{64}$'),
  resolved_models      jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(resolved_models) = 'object'),
  model_override       boolean NOT NULL DEFAULT false,
  triggered_by         ops.triggered_by NOT NULL,
  actor                text,
  host_label           text,
  started_at           timestamptz NOT NULL DEFAULT now(),
  finished_at          timestamptz,
  error_summary        text,
  CONSTRAINT pipeline_run_finished_chk CHECK ((status = 'running') = (finished_at IS NULL)),
  CONSTRAINT pipeline_run_order_chk CHECK (finished_at IS NULL OR finished_at >= started_at)
);
COMMENT ON TABLE ops.pipeline_run IS
  'One execution (= one trace). Pinned to a profile version. resolved_models = the models actually used per role; model_override = the judges'' LLM_NAME differs from the declared models (a release warns, never blocks, D-064). Only status, finished_at, error_summary change after insert. docs/DB_DDL_PLANNING.md §14.';
COMMENT ON COLUMN ops.pipeline_run.host_label IS 'A machine label. Never a person''s name (G13).';
CREATE INDEX IF NOT EXISTS pipeline_run_profile_ix ON ops.pipeline_run (profile_version_id, started_at DESC);

CREATE TABLE IF NOT EXISTS ops.blob (
  sha256       char(64) PRIMARY KEY CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  media_type   text NOT NULL,
  byte_size    bigint NOT NULL CHECK (byte_size >= 0),
  content      text NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE ops.blob IS 'Content-addressed payloads: prompt messages, oversized log attributes, raw pages. Insert with ON CONFLICT DO NOTHING. Append-only.';

CREATE TABLE IF NOT EXISTS ops.span (
  span_id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id                uuid NOT NULL REFERENCES ops.pipeline_run(run_id) ON DELETE RESTRICT,
  parent_span_id        uuid REFERENCES ops.span(span_id) ON DELETE RESTRICT,
  step                  ops.pipeline_step,
  operation             text NOT NULL CHECK (operation ~ '^[a-z0-9_]+(\.[a-z0-9_]+)*$'),
  ruling_id             uuid,                                -- FK to corpus.ruling, 85_cross_fks.sql
  component_version_id  uuid REFERENCES ops.component_version(component_version_id) ON DELETE RESTRICT,
  status                ops.span_status NOT NULL DEFAULT 'running',
  started_at            timestamptz NOT NULL DEFAULT now(),
  ended_at              timestamptz,
  duration_ms           bigint GENERATED ALWAYS AS (
                          CASE WHEN ended_at IS NULL THEN NULL
                               ELSE (extract(epoch FROM (ended_at - started_at)) * 1000)::bigint END) STORED,
  attributes            jsonb NOT NULL DEFAULT '{}'::jsonb
                          CHECK (jsonb_typeof(attributes) = 'object' AND pg_column_size(attributes) <= 16384),
  error_reason_code     text REFERENCES ops.reason_code(code) ON DELETE RESTRICT,
  error_message         text,
  CONSTRAINT span_closed_chk CHECK ((status = 'running') = (ended_at IS NULL)),
  CONSTRAINT span_order_chk CHECK (ended_at IS NULL OR ended_at >= started_at)
);
COMMENT ON TABLE ops.span IS
  'A unit of work (one step on one ruling, or an operation inside it: an LLM call, a check). Inserted at start, closed once (trigger). Business rows point to their span. No key, prompt, D-051 value or person''s name in attributes (§11.5). docs/DB_DDL_PLANNING.md §11.';
CREATE INDEX IF NOT EXISTS span_run_step_ix ON ops.span (run_id, step);
CREATE INDEX IF NOT EXISTS span_ruling_ix ON ops.span (ruling_id, started_at);
CREATE INDEX IF NOT EXISTS span_parent_ix ON ops.span (parent_span_id);

CREATE TABLE IF NOT EXISTS ops.run_metric (
  run_id        uuid NOT NULL REFERENCES ops.pipeline_run(run_id) ON DELETE RESTRICT,
  step          ops.pipeline_step NOT NULL,
  metric_code   text NOT NULL CHECK (metric_code ~ '^[a-z0-9_]+$'),
  value         numeric NOT NULL,
  unit          text NOT NULL,
  measured_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (run_id, step, metric_code)
);
COMMENT ON TABLE ops.run_metric IS 'Counters and measures per run and step (rulings_in, kept, dropped, llm_calls, latency_p95_ms...). A step with 0 output fails the run (G6). Append-only.';

CREATE TABLE IF NOT EXISTS ops.work_item (
  run_id            uuid NOT NULL REFERENCES ops.pipeline_run(run_id) ON DELETE RESTRICT,
  ruling_id         uuid NOT NULL,                           -- FK to corpus.ruling, 85_cross_fks.sql
  step              ops.pipeline_step NOT NULL,
  target_ref        text NOT NULL DEFAULT '',                -- preset code for a summary, '' otherwise
  status            ops.work_status NOT NULL DEFAULT 'todo',
  attempts          smallint NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  last_reason_code  text REFERENCES ops.reason_code(code) ON DELETE RESTRICT,
  last_error        text,
  last_span_id      uuid REFERENCES ops.span(span_id) ON DELETE RESTRICT,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (run_id, ruling_id, step, target_ref)
);
COMMENT ON TABLE ops.work_item IS 'The queue of a run: resume ("rerun the same command"), the overnight run, progress bars. A circuit breaker leaves items todo, never failed.';
CREATE INDEX IF NOT EXISTS work_item_status_ix ON ops.work_item (run_id, step, status);

CREATE TABLE IF NOT EXISTS ops.user_request (
  request_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  kind               ops.request_kind NOT NULL,
  docket             text CHECK (docket ~ '^[0-9]{1,2}[A-Z]_[0-9]+/[0-9]{4}$'),
  bger_url           text CHECK (bger_url ~ '^https://'),
  ruling_id          uuid,                                   -- FK to corpus.ruling, 85_cross_fks.sql
  preset_code        text,                                   -- FK to summ.preset, 85_cross_fks.sql
  status             ops.request_status NOT NULL DEFAULT 'pending',
  run_id             uuid REFERENCES ops.pipeline_run(run_id) ON DELETE RESTRICT,
  requested_by_actor text NOT NULL,
  status_detail      text,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT user_request_target_chk CHECK (
    (kind = 'add_judgement' AND (docket IS NOT NULL OR bger_url IS NOT NULL) AND preset_code IS NULL)
    OR (kind = 'summary' AND ruling_id IS NOT NULL AND preset_code IS NOT NULL))
);
COMMENT ON TABLE ops.user_request IS 'Requests from the UI: "add another judgement" (D-015) by docket or bger.ch link, or a summary of any ruling under any preset. Created only through ops.submit_request(); the pipeline accepts them into a run.';

CREATE TABLE IF NOT EXISTS ops.llm_call (
  llm_call_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id               uuid NOT NULL REFERENCES ops.pipeline_run(run_id) ON DELETE RESTRICT,
  span_id              uuid NOT NULL REFERENCES ops.span(span_id) ON DELETE RESTRICT,
  ruling_id            uuid,                                 -- FK to corpus.ruling, 85_cross_fks.sql
  step                 ops.pipeline_step NOT NULL,
  purpose              text NOT NULL CHECK (purpose ~ '^[a-z0-9_]+$'),
  language             ops.lang_code,
  prompt_version_id    uuid REFERENCES ops.prompt_version(prompt_version_id) ON DELETE RESTRICT,
  cache_key            char(64) NOT NULL CHECK (cache_key ~ '^[0-9a-f]{64}$'),
  cache_hit            boolean NOT NULL,
  mode                 ops.run_mode NOT NULL,
  endpoint             text NOT NULL,
  model_role           ops.model_role,
  requested_model      text NOT NULL,
  served_model         text,
  served_model_header  text,
  params               jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(params) = 'object'),
  repetition_idx       smallint NOT NULL DEFAULT 0 CHECK (repetition_idx >= 0),
  messages_sha256      char(64) REFERENCES ops.blob(sha256) ON DELETE RESTRICT,
  raw_output           text,
  finish_reason        text,
  parsed_ok            boolean,
  parse_error          text,
  http_status          smallint,
  error_reason_code    text REFERENCES ops.reason_code(code) ON DELETE RESTRICT,
  attempt              smallint NOT NULL DEFAULT 1 CHECK (attempt >= 1),
  input_tokens         integer CHECK (input_tokens >= 0),
  output_tokens        integer CHECK (output_tokens >= 0),
  cached_tokens        integer CHECK (cached_tokens >= 0),
  latency_ms           integer CHECK (latency_ms >= 0),
  started_at           timestamptz NOT NULL,
  created_at           timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE ops.llm_call IS
  'Every LLM call, invalid outputs included; mirrors data/derived/llm/llm_calls.jsonl. Never the API key (G13). Requested and served model on every row (G3). Append-only. docs/DB_DDL_PLANNING.md §14.';
CREATE INDEX IF NOT EXISTS llm_call_run_ix ON ops.llm_call (run_id);
CREATE INDEX IF NOT EXISTS llm_call_ruling_ix ON ops.llm_call (ruling_id);
CREATE INDEX IF NOT EXISTS llm_call_cache_ix ON ops.llm_call (cache_key);
CREATE INDEX IF NOT EXISTS llm_call_span_ix ON ops.llm_call (span_id);

CREATE TABLE IF NOT EXISTS ops.llm_call_example (
  llm_call_id        uuid NOT NULL REFERENCES ops.llm_call(llm_call_id) ON DELETE RESTRICT,
  position           smallint NOT NULL CHECK (position >= 1),
  example_kind       text NOT NULL CHECK (example_kind IN ('suva_summary', 'labelled_ruling')),
  example_ruling_id  uuid,                                   -- FK to corpus.ruling, 85_cross_fks.sql
  suva_summary_id    uuid,                                   -- FK to gold.suva_summary, 85_cross_fks.sql
  PRIMARY KEY (llm_call_id, position),
  CONSTRAINT llm_call_example_ref_chk CHECK (
    (example_kind = 'labelled_ruling' AND example_ruling_id IS NOT NULL AND suva_summary_id IS NULL)
    OR (example_kind = 'suva_summary' AND suva_summary_id IS NOT NULL))
);
COMMENT ON TABLE ops.llm_call_example IS 'The few-shot examples a call carried: proves the judged ruling and the test rulings were never examples (D-021 point 8). Append-only.';

CREATE TABLE IF NOT EXISTS ops.release (
  release_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_code        text NOT NULL REFERENCES ops.pipeline_profile(profile_code) ON DELETE RESTRICT,
  profile_version_id  uuid NOT NULL REFERENCES ops.pipeline_profile_version(profile_version_id) ON DELETE RESTRICT,
  ranking_id          uuid NOT NULL,                         -- FK to triage.ranking, 85_cross_fks.sql
  created_by_actor    text,
  notes               text,
  is_current          boolean NOT NULL DEFAULT false,
  warnings            jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(warnings) = 'array'),
  superseded_at       timestamptz,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS release_one_current_uix ON ops.release (profile_code) WHERE is_current;
COMMENT ON TABLE ops.release IS
  'What is published: a ranking of a profile version. The current release of the default profile carries "the label" (D-063). Becoming current is gated: every target member labelled, no unexplained potentially, no missing mandatory summary (trigger). warnings records e.g. model_override.';

CREATE TABLE IF NOT EXISTS ops.artifact (
  artifact_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id        uuid NOT NULL REFERENCES ops.pipeline_run(run_id) ON DELETE RESTRICT,
  release_id    uuid REFERENCES ops.release(release_id) ON DELETE RESTRICT,
  kind          ops.artifact_kind NOT NULL,
  path          text NOT NULL,
  sha256        char(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  row_count     bigint CHECK (row_count >= 0),
  created_at    timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT artifact_uq UNIQUE (run_id, path)
);
COMMENT ON TABLE ops.artifact IS 'Files a run wrote, with their SHA-256 (pipeline step 7: results/ with hash). The export endpoint must equal the hashed file. Append-only.';
