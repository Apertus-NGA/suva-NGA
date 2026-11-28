-- ============================================================================
-- File: 10_ops_registry.sql (registry: what may run)
-- Date: 2026-11-28
-- Description: Versioned step components (V<major>.<minor>.<patch>), their models, prompts and rules,
--              the JSON Schema templates their configurations follow, the reason-code vocabulary, and
--              pipeline profiles (the "default pipeline" pins one version per step). Registry rows are
--              insert-only: only status (and updated_at) may change; a fix is a new version.
--              The DB is agnostic to configuration shapes: configurations are jsonb, checked by the
--              application against ops.json_schema (docs/DB_DDL_PLANNING.md §7.4).
-- SGBD: PostgreSQL 17
-- Doc: docs/DB_DDL_PLANNING.md §7
-- ============================================================================
-- PREREQUISITE: 00_extensions.sql. Model ids are never written in SQL: ops.model is loaded from MODELS.md.
-- ============================================================================

CREATE TABLE IF NOT EXISTS ops.reason_code (
  code          text PRIMARY KEY CHECK (code ~ '^[A-Z][A-Z0-9_]*$'),
  domain        ops.reason_domain NOT NULL,
  label_de      text NOT NULL CHECK (length(btrim(label_de)) > 0),
  label_fr      text,
  description   text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE ops.reason_code IS
  'One vocabulary of reasons for the whole DB (triage drops, verifier checks, ingest issues, work errors). The UI shows label_de, so a lawyer reads a sentence, not a code (G5). docs/DB_DDL_PLANNING.md §7.5.';

CREATE TABLE IF NOT EXISTS ops.json_schema (
  json_schema_id       uuid PRIMARY KEY,
  subject              ops.schema_subject NOT NULL,
  schema_code          text NOT NULL CHECK (schema_code ~ '^[a-z0-9_]+(\.[a-z0-9_]+)+$'),
  v_major              smallint NOT NULL CHECK (v_major >= 0),
  v_minor              smallint NOT NULL CHECK (v_minor >= 0),
  v_patch              smallint NOT NULL CHECK (v_patch >= 0),
  version_label        text GENERATED ALWAYS AS ('V' || v_major::text || '.' || v_minor::text || '.' || v_patch::text) STORED,
  json_schema          jsonb NOT NULL CHECK (jsonb_typeof(json_schema) = 'object'),
  template             jsonb NOT NULL CHECK (jsonb_typeof(template) = 'object'),
  schema_sha256        char(64) NOT NULL CHECK (schema_sha256 ~ '^[0-9a-f]{64}$'),
  status               ops.registry_status NOT NULL DEFAULT 'draft',
  bump_kind            ops.bump_kind NOT NULL,
  previous_version_id  uuid REFERENCES ops.json_schema(json_schema_id) ON DELETE RESTRICT,
  changelog            text NOT NULL CHECK (length(btrim(changelog)) > 0),
  created_by_actor     text,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT json_schema_uq UNIQUE (schema_code, v_major, v_minor, v_patch),
  CONSTRAINT json_schema_bump_chk CHECK ((bump_kind = 'initial') = (previous_version_id IS NULL))
);
COMMENT ON TABLE ops.json_schema IS
  'Versioned JSON Schema templates for step configurations, rule definitions, preset configurations and review payloads. template is a complete example: the starting point of a new version. Id = uuid5(''json_schema|<code>|<major>|<minor>|<patch>''). docs/DB_DDL_PLANNING.md §7.4.';

CREATE TABLE IF NOT EXISTS ops.model (
  model_id             uuid PRIMARY KEY,
  family               text NOT NULL,
  size_label           text NOT NULL,
  gateway_id           text NOT NULL UNIQUE,
  hf_id                text UNIQUE,
  revision             text,
  allowed              boolean NOT NULL,
  source_snapshot_id   uuid NOT NULL,                       -- FK to ops.source_snapshot (MODELS.md), 85_cross_fks.sql
  created_at           timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE ops.model IS
  'Models, loaded from MODELS.md (the single home of model ids, E6, G3); never typed in SQL. allowed = on the G3 allow-list. Id = uuid5(''model|<gateway_id>''). docs/DB_DDL_PLANNING.md §7.2.';

CREATE TABLE IF NOT EXISTS ops.prompt_version (
  prompt_version_id       uuid PRIMARY KEY,
  role                    text NOT NULL CHECK (role ~ '^[a-z0-9_]+(\.[a-z0-9_]+)*$'),
  v_major                 smallint NOT NULL CHECK (v_major >= 0),
  v_minor                 smallint NOT NULL CHECK (v_minor >= 0),
  v_patch                 smallint NOT NULL CHECK (v_patch >= 0),
  version_label           text GENERATED ALWAYS AS ('V' || v_major::text || '.' || v_minor::text || '.' || v_patch::text) STORED,
  template_sha256         char(64) NOT NULL CHECK (template_sha256 ~ '^[0-9a-f]{64}$'),
  system_template         text NOT NULL,
  user_template           text NOT NULL,
  response_schema         jsonb,
  contains_suva_material  boolean NOT NULL,
  status                  ops.registry_status NOT NULL DEFAULT 'draft',
  bump_kind               ops.bump_kind NOT NULL,
  previous_version_id     uuid REFERENCES ops.prompt_version(prompt_version_id) ON DELETE RESTRICT,
  changelog               text NOT NULL CHECK (length(btrim(changelog)) > 0),
  created_by_actor        text,
  created_at              timestamptz NOT NULL DEFAULT now(),
  updated_at              timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT prompt_version_uq UNIQUE (role, v_major, v_minor, v_patch),
  CONSTRAINT prompt_version_bump_chk CHECK ((bump_kind = 'initial') = (previous_version_id IS NULL))
);
COMMENT ON TABLE ops.prompt_version IS
  'Versioned prompts. contains_suva_material = built from judgements/: its exports stay in data/derived/ while D-031 is open. Id = uuid5(''prompt|<role>|<major>|<minor>|<patch>''). docs/DB_DDL_PLANNING.md §14.';

CREATE TABLE IF NOT EXISTS ops.component_version (
  component_version_id  uuid PRIMARY KEY,
  step                  ops.pipeline_step NOT NULL,
  name                  text NOT NULL CHECK (length(btrim(name)) > 0),
  v_major               smallint NOT NULL CHECK (v_major >= 0),
  v_minor               smallint NOT NULL CHECK (v_minor >= 0),
  v_patch               smallint NOT NULL CHECK (v_patch >= 0),
  version_label         text GENERATED ALWAYS AS ('V' || v_major::text || '.' || v_minor::text || '.' || v_patch::text) STORED,
  config_schema_id      uuid NOT NULL REFERENCES ops.json_schema(json_schema_id) ON DELETE RESTRICT,
  config                jsonb NOT NULL CHECK (jsonb_typeof(config) = 'object'),
  config_sha256         char(64) NOT NULL CHECK (config_sha256 ~ '^[0-9a-f]{64}$'),
  code_path             text NOT NULL,
  code_sha256           char(64) NOT NULL CHECK (code_sha256 ~ '^[0-9a-f]{64}$'),
  git_commit            char(40) CHECK (git_commit ~ '^[0-9a-f]{40}$'),
  status                ops.registry_status NOT NULL DEFAULT 'draft',
  bump_kind             ops.bump_kind NOT NULL,
  previous_version_id   uuid REFERENCES ops.component_version(component_version_id) ON DELETE RESTRICT,
  changelog             text NOT NULL CHECK (length(btrim(changelog)) > 0),
  created_by_actor      text,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT component_version_uq UNIQUE (step, v_major, v_minor, v_patch),
  CONSTRAINT component_version_bump_chk CHECK ((bump_kind = 'initial') = (previous_version_id IS NULL))
);
COMMENT ON TABLE ops.component_version IS
  'One version (V<major>.<minor>.<patch>) of one pipeline step: code hash, configuration (jsonb, shape checked by the application against config_schema_id), models, prompts, rules. MAJOR = outputs not comparable, MINOR = re-measure, PATCH = identical outputs. Insert-only except status. Id = uuid5(''cv|<step>|<major>|<minor>|<patch>''). docs/DB_DDL_PLANNING.md §7.1, §7.3.';
COMMENT ON COLUMN ops.component_version.config IS 'Step configuration. The DB checks only that it is an object; its shape is versioned in ops.json_schema (§7.4).';

CREATE TABLE IF NOT EXISTS ops.component_version_model (
  component_version_id  uuid NOT NULL REFERENCES ops.component_version(component_version_id) ON DELETE RESTRICT,
  model_role            ops.model_role NOT NULL,
  model_id              uuid NOT NULL REFERENCES ops.model(model_id) ON DELETE RESTRICT,
  created_at            timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (component_version_id, model_role)
);
COMMENT ON TABLE ops.component_version_model IS 'The model each step version declares per role (N9). The run records the models actually resolved (judges may set LLM_NAME). docs/DB_DDL_PLANNING.md §7.2.';

CREATE TABLE IF NOT EXISTS ops.component_version_prompt (
  component_version_id  uuid NOT NULL REFERENCES ops.component_version(component_version_id) ON DELETE RESTRICT,
  prompt_role           text NOT NULL CHECK (prompt_role ~ '^[a-z0-9_]+$'),
  prompt_version_id     uuid NOT NULL REFERENCES ops.prompt_version(prompt_version_id) ON DELETE RESTRICT,
  created_at            timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (component_version_id, prompt_role)
);
COMMENT ON TABLE ops.component_version_prompt IS 'The prompt versions a step version uses, per prompt role. Append-only.';

CREATE TABLE IF NOT EXISTS ops.rule (
  rule_id               uuid PRIMARY KEY,
  step                  ops.pipeline_step NOT NULL,
  rule_code             text NOT NULL CHECK (rule_code ~ '^[A-Z][A-Z0-9_]*$'),
  v_major               smallint NOT NULL CHECK (v_major >= 0),
  v_minor               smallint NOT NULL CHECK (v_minor >= 0),
  v_patch               smallint NOT NULL CHECK (v_patch >= 0),
  version_label         text GENERATED ALWAYS AS ('V' || v_major::text || '.' || v_minor::text || '.' || v_patch::text) STORED,
  kind                  ops.rule_kind NOT NULL,
  definition            jsonb NOT NULL CHECK (jsonb_typeof(definition) = 'object'),
  definition_schema_id  uuid NOT NULL REFERENCES ops.json_schema(json_schema_id) ON DELETE RESTRICT,
  reason_code           text NOT NULL REFERENCES ops.reason_code(code) ON DELETE RESTRICT,
  description           text,
  status                ops.registry_status NOT NULL DEFAULT 'draft',
  bump_kind             ops.bump_kind NOT NULL,
  previous_version_id   uuid REFERENCES ops.rule(rule_id) ON DELETE RESTRICT,
  changelog             text NOT NULL CHECK (length(btrim(changelog)) > 0),
  created_by_actor      text,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT rule_uq UNIQUE (rule_code, v_major, v_minor, v_patch),
  CONSTRAINT rule_bump_chk CHECK ((bump_kind = 'initial') = (previous_version_id IS NULL))
);
COMMENT ON TABLE ops.rule IS
  'Versioned rules (layer-1 keep/drop rules, party checks, verifier checks...). definition is jsonb, its shape versioned in ops.json_schema. Results point to the exact rule version that fired. Id = uuid5(''rule|<rule_code>|<major>|<minor>|<patch>''). docs/DB_DDL_PLANNING.md §7.5.';

CREATE TABLE IF NOT EXISTS ops.component_version_rule (
  component_version_id  uuid NOT NULL REFERENCES ops.component_version(component_version_id) ON DELETE RESTRICT,
  rule_id               uuid NOT NULL REFERENCES ops.rule(rule_id) ON DELETE RESTRICT,
  ordinal               integer NOT NULL CHECK (ordinal >= 1),
  enabled               boolean NOT NULL DEFAULT true,
  params                jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(params) = 'object'),
  created_at            timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (component_version_id, rule_id),
  CONSTRAINT component_version_rule_ordinal_uq UNIQUE (component_version_id, ordinal)
);
COMMENT ON TABLE ops.component_version_rule IS 'The rules a step version applies, in order, with their parameters. The rule must belong to the same step (trigger). Append-only.';

CREATE TABLE IF NOT EXISTS ops.pipeline_profile (
  profile_code   text PRIMARY KEY CHECK (profile_code ~ '^[a-z0-9_]+$'),
  name           text NOT NULL,
  description    text,
  is_default     boolean NOT NULL DEFAULT false,
  retired_at     timestamptz,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS pipeline_profile_one_default_uix
  ON ops.pipeline_profile (is_default) WHERE is_default AND retired_at IS NULL;
COMMENT ON TABLE ops.pipeline_profile IS 'Named pipelines. Exactly one active default: "the default pipeline" whose label is shown and used (D-063). docs/DB_DDL_PLANNING.md §7.6.';

CREATE TABLE IF NOT EXISTS ops.pipeline_profile_version (
  profile_version_id   uuid PRIMARY KEY,
  profile_code         text NOT NULL REFERENCES ops.pipeline_profile(profile_code) ON DELETE RESTRICT,
  v_major              smallint NOT NULL CHECK (v_major >= 0),
  v_minor              smallint NOT NULL CHECK (v_minor >= 0),
  v_patch              smallint NOT NULL CHECK (v_patch >= 0),
  version_label        text GENERATED ALWAYS AS ('V' || v_major::text || '.' || v_minor::text || '.' || v_patch::text) STORED,
  status               ops.registry_status NOT NULL DEFAULT 'draft',
  bump_kind            ops.bump_kind NOT NULL,
  previous_version_id  uuid REFERENCES ops.pipeline_profile_version(profile_version_id) ON DELETE RESTRICT,
  changelog            text NOT NULL CHECK (length(btrim(changelog)) > 0),
  created_by_actor     text,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pipeline_profile_version_uq UNIQUE (profile_code, v_major, v_minor, v_patch),
  CONSTRAINT pipeline_profile_version_bump_chk CHECK ((bump_kind = 'initial') = (previous_version_id IS NULL))
);
COMMENT ON TABLE ops.pipeline_profile_version IS 'A version of a profile. Id = uuid5(''profile|<profile_code>|<major>|<minor>|<patch>''). A version with major >= 1 refuses any V0.x step (trigger).';

CREATE TABLE IF NOT EXISTS ops.pipeline_profile_step (
  profile_version_id    uuid NOT NULL REFERENCES ops.pipeline_profile_version(profile_version_id) ON DELETE RESTRICT,
  step                  ops.pipeline_step NOT NULL,
  component_version_id  uuid NOT NULL REFERENCES ops.component_version(component_version_id) ON DELETE RESTRICT,
  created_at            timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (profile_version_id, step)
);
COMMENT ON TABLE ops.pipeline_profile_step IS 'The step versions a profile version pins. Every assessment must come from the version its run''s profile pins (trigger in 80_triggers.sql).';
