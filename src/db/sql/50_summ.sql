-- ============================================================================
-- File: 50_summ.sql (summaries)
-- Date: 2026-11-28
-- Description: Presets (stored in the DB, selected at run time; perspective 0 = insured person to 10 =
--              insurer, active anchors with written rubrics; suva_house = anchor 5, mandatory), summaries
--              (ruling x preset), immutable versions that are always a German + French pair, texts, claims,
--              citations by FK (G1) and verifier checks (D-067, D-068, D-069).
-- SGBD: PostgreSQL 17
-- Doc: docs/DB_DDL_PLANNING.md §13
-- ============================================================================
-- PREREQUISITE: 40_gold.sql
-- ============================================================================

CREATE TABLE IF NOT EXISTS summ.perspective_anchor (
  perspective  smallint PRIMARY KEY CHECK (perspective BETWEEN 0 AND 10),
  label_de     text NOT NULL,
  label_fr     text NOT NULL,
  rubric_de    text,
  rubric_fr    text,
  status       ops.registry_status NOT NULL DEFAULT 'draft',
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT perspective_anchor_rubric_chk CHECK (status <> 'active' OR (rubric_de IS NOT NULL AND rubric_fr IS NOT NULL))
);
COMMENT ON TABLE summ.perspective_anchor IS
  'Perspective anchors (D-068): 0 insured advocate, 3 insured-leaning, 5 neutral (suva_house), 7 insurer-leaning, 10 insurer advocate. An anchor is active only once its rubric is written (owner: summarise). A perspective changes emphasis and the practice paragraph, never facts, holding, outcome or citations.';

CREATE TABLE IF NOT EXISTS summ.preset (
  preset_code       text PRIMARY KEY CHECK (preset_code ~ '^[a-z0-9_]+$'),
  name_de           text NOT NULL,
  name_fr           text NOT NULL,
  description       text,
  perspective       smallint NOT NULL REFERENCES summ.perspective_anchor(perspective) ON DELETE RESTRICT,
  style             ops.summary_style NOT NULL,
  is_mandatory      boolean NOT NULL DEFAULT false,
  selectable        boolean NOT NULL DEFAULT true,
  retired_at        timestamptz,
  created_by_actor  text,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS preset_one_mandatory_uix ON summ.preset (is_mandatory) WHERE is_mandatory AND retired_at IS NULL;
COMMENT ON TABLE summ.preset IS
  'A kind of summary. Stored in the DB (the DB is its source of truth, exported to data/derived/authored/), listed by the UI, picked by code at run time. Exactly one active mandatory preset: suva_house.';

CREATE TABLE IF NOT EXISTS summ.preset_version (
  preset_version_id    uuid PRIMARY KEY,
  preset_code          text NOT NULL REFERENCES summ.preset(preset_code) ON DELETE RESTRICT,
  v_major              smallint NOT NULL CHECK (v_major >= 0),
  v_minor              smallint NOT NULL CHECK (v_minor >= 0),
  v_patch              smallint NOT NULL CHECK (v_patch >= 0),
  version_label        text GENERATED ALWAYS AS ('V' || v_major::text || '.' || v_minor::text || '.' || v_patch::text) STORED,
  config_schema_id     uuid NOT NULL REFERENCES ops.json_schema(json_schema_id) ON DELETE RESTRICT,
  config               jsonb NOT NULL CHECK (jsonb_typeof(config) = 'object'),
  config_sha256        char(64) NOT NULL CHECK (config_sha256 ~ '^[0-9a-f]{64}$'),
  status               ops.registry_status NOT NULL DEFAULT 'draft',
  bump_kind            ops.bump_kind NOT NULL,
  previous_version_id  uuid REFERENCES summ.preset_version(preset_version_id) ON DELETE RESTRICT,
  changelog            text NOT NULL CHECK (length(btrim(changelog)) > 0),
  created_by_actor     text,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT preset_version_uq UNIQUE (preset_code, v_major, v_minor, v_patch),
  CONSTRAINT preset_version_bump_chk CHECK ((bump_kind = 'initial') = (previous_version_id IS NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS preset_version_one_active_uix ON summ.preset_version (preset_code) WHERE status = 'active';
COMMENT ON TABLE summ.preset_version IS 'Editorial configuration of a preset (length, sections, few-shot policy, perspective rubric...), jsonb checked against config_schema_id. Insert-only except status. Id = uuid5(''preset_version|<preset_code>|<major>|<minor>|<patch>'').';

CREATE TABLE IF NOT EXISTS summ.preset_version_prompt (
  preset_version_id  uuid NOT NULL REFERENCES summ.preset_version(preset_version_id) ON DELETE RESTRICT,
  language           ops.lang_code NOT NULL,
  prompt_role        text NOT NULL CHECK (prompt_role ~ '^[a-z0-9_]+$'),
  prompt_version_id  uuid NOT NULL REFERENCES ops.prompt_version(prompt_version_id) ON DELETE RESTRICT,
  created_at         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (preset_version_id, language, prompt_role)
);
COMMENT ON TABLE summ.preset_version_prompt IS 'The prompt versions a preset version uses, per language and role. Append-only.';

CREATE TABLE IF NOT EXISTS summ.summary (
  summary_id    uuid PRIMARY KEY,
  ruling_id     uuid NOT NULL REFERENCES corpus.ruling(ruling_id) ON DELETE RESTRICT,
  preset_code   text NOT NULL REFERENCES summ.preset(preset_code) ON DELETE RESTRICT,
  created_at    timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT summary_uq UNIQUE (ruling_id, preset_code)
);
COMMENT ON TABLE summ.summary IS 'Identity of one (ruling, preset) summary; its content lives in versions. Id = uuid5(''summary|<ruling_id>|<preset_code>''). Append-only.';

CREATE TABLE IF NOT EXISTS summ.summary_version (
  summary_version_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  summary_id              uuid NOT NULL REFERENCES summ.summary(summary_id) ON DELETE RESTRICT,
  version_no              integer NOT NULL CHECK (version_no >= 1),
  origin                  ops.summary_version_origin NOT NULL,
  parent_version_id       uuid REFERENCES summ.summary_version(summary_version_id) ON DELETE RESTRICT,
  preset_version_id       uuid NOT NULL REFERENCES summ.preset_version(preset_version_id) ON DELETE RESTRICT,
  component_version_id    uuid NOT NULL REFERENCES ops.component_version(component_version_id) ON DELETE RESTRICT,
  source_segmentation_id  uuid NOT NULL REFERENCES corpus.segmentation(segmentation_id) ON DELETE RESTRICT,
  creator_kind            ops.creator_kind NOT NULL,
  creator_run_id          uuid REFERENCES ops.pipeline_run(run_id) ON DELETE RESTRICT,
  creator_actor           text,
  quality_status          ops.summary_quality NOT NULL DEFAULT 'draft',
  is_current              boolean NOT NULL DEFAULT false,
  mode                    ops.run_mode,
  span_id                 uuid REFERENCES ops.span(span_id) ON DELETE RESTRICT,
  created_at              timestamptz NOT NULL DEFAULT now(),
  updated_at              timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT summary_version_no_uq UNIQUE (summary_id, version_no),
  CONSTRAINT summary_version_creator_chk CHECK (
    (creator_kind = 'pipeline' AND creator_run_id IS NOT NULL AND creator_actor IS NULL AND origin <> 'expert_edit' AND mode IS NOT NULL)
    OR (creator_kind = 'expert' AND creator_actor IS NOT NULL AND origin = 'expert_edit')),
  CONSTRAINT summary_version_parent_chk CHECK (origin = 'generated' OR parent_version_id IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS summary_version_one_current_uix ON summ.summary_version (summary_id) WHERE is_current;
COMMENT ON TABLE summ.summary_version IS
  'An immutable version of a summary: always one German and one French text (deferred check at commit, D-067). version_no is assigned by trigger. Only quality_status (verifier) and is_current change, audited. Expert validation is a review (gold.expert_review), not a column.';

CREATE TABLE IF NOT EXISTS summ.summary_text (
  summary_text_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  summary_version_id   uuid NOT NULL REFERENCES summ.summary_version(summary_version_id) ON DELETE RESTRICT,
  language             ops.lang_code NOT NULL CHECK (language IN ('de', 'fr')),
  title_line           text NOT NULL CHECK (length(btrim(title_line)) > 0),
  body                 text NOT NULL CHECK (length(btrim(body)) > 0),
  word_count           integer NOT NULL CHECK (word_count >= 0),
  paragraph_count      smallint NOT NULL CHECK (paragraph_count BETWEEN 1 AND 20),
  llm_call_id          uuid REFERENCES ops.llm_call(llm_call_id) ON DELETE RESTRICT,
  repair_llm_call_id   uuid REFERENCES ops.llm_call(llm_call_id) ON DELETE RESTRICT,
  created_at           timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT summary_text_language_uq UNIQUE (summary_version_id, language)
);
COMMENT ON TABLE summ.summary_text IS
  'One language of a version. title_line and body are rendered by code (references from consideration ids, D-037; never an author line, D-051). A pipeline text has its own LLM call written from the source, never a translation of the other language (D-014). Append-only.';

CREATE TABLE IF NOT EXISTS summ.summary_claim (
  claim_id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  summary_text_id       uuid NOT NULL REFERENCES summ.summary_text(summary_text_id) ON DELETE RESTRICT,
  ordinal               smallint NOT NULL CHECK (ordinal >= 1),
  paragraph_no          smallint NOT NULL CHECK (paragraph_no >= 1),
  section               ops.claim_section NOT NULL,
  model_text            text CHECK (model_text IS NULL OR char_length(model_text) <= 300),
  rendered_text         text NOT NULL CHECK (length(btrim(rendered_text)) > 0),
  status                ops.claim_status NOT NULL,
  edited_from_claim_id  uuid REFERENCES summ.summary_claim(claim_id) ON DELETE RESTRICT,
  created_at            timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT summary_claim_ordinal_uq UNIQUE (summary_text_id, ordinal)
);
COMMENT ON TABLE summ.summary_claim IS 'One statement of a text. section includes application and practice (D-069): only practice may differ between perspectives. model_text = the model''s text (NULL for an expert-written claim). Append-only.';

CREATE TABLE IF NOT EXISTS summ.claim_citation (
  claim_id          uuid NOT NULL REFERENCES summ.summary_claim(claim_id) ON DELETE RESTRICT,
  consideration_id  uuid NOT NULL REFERENCES corpus.consideration(consideration_id) ON DELETE RESTRICT,
  ordinal           smallint NOT NULL DEFAULT 1 CHECK (ordinal >= 1),
  PRIMARY KEY (claim_id, consideration_id)
);
COMMENT ON TABLE summ.claim_citation IS 'Considerations a claim cites, by FK. Trigger: a citable consideration of the version''s source segmentation (G1). Append-only.';

CREATE TABLE IF NOT EXISTS summ.verification_check (
  check_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  target_kind       text NOT NULL CHECK (target_kind IN ('claim', 'text')),
  claim_id          uuid REFERENCES summ.summary_claim(claim_id) ON DELETE RESTRICT,
  summary_text_id   uuid REFERENCES summ.summary_text(summary_text_id) ON DELETE RESTRICT,
  rule_id           uuid NOT NULL REFERENCES ops.rule(rule_id) ON DELETE RESTRICT,
  status            ops.check_status NOT NULL,
  detail            jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(detail) = 'object'),
  run_id            uuid NOT NULL REFERENCES ops.pipeline_run(run_id) ON DELETE RESTRICT,
  span_id           uuid REFERENCES ops.span(span_id) ON DELETE RESTRICT,
  created_at        timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT verification_check_target_chk CHECK (
    (target_kind = 'claim' AND claim_id IS NOT NULL AND summary_text_id IS NULL)
    OR (target_kind = 'text' AND summary_text_id IS NOT NULL AND claim_id IS NULL))
);
CREATE INDEX IF NOT EXISTS verification_check_claim_ix ON summ.verification_check (claim_id);
CREATE INDEX IF NOT EXISTS verification_check_text_ix ON summ.verification_check (summary_text_id);
COMMENT ON TABLE summ.verification_check IS 'One verifier check (V1 to V6, the perspective invariant) on a claim or a text, with the exact rule version. Append-only.';
