-- ============================================================================
-- File: 20_corpus.sql (rulings and what their sources say)
-- Date: 2026-11-28
-- Description: A ruling is split by source, never one flat row (D-062): identity, source references (HF
--              ids, twins), publication observations (exact or approximate), text versions, versioned
--              segmentations and their considerations (the court's numbered Erwägungen), parses, ingest
--              issues (G5's counted reasons), populations. Never ingested: judges, clerks (D-038),
--              legal_area, outcome, marked_for_publication (D-011). The scope label is NOT here (D-063).
-- SGBD: PostgreSQL 17
-- Doc: docs/DB_DDL_PLANNING.md §8
-- ============================================================================
-- PREREQUISITE: 11_ops_execution.sql
-- ============================================================================

CREATE TABLE IF NOT EXISTS corpus.ruling (
  ruling_id            uuid PRIMARY KEY,
  docket               text NOT NULL CHECK (docket ~ '^[0-9]{1,2}[A-Z]_[0-9]+/[0-9]{4}$'),
  decision_date        date NOT NULL,
  court                text GENERATED ALWAYS AS (split_part(docket, '_', 1)) STORED,
  register_letter      text GENERATED ALWAYS AS (right(split_part(docket, '_', 1), 1)) STORED,
  filing_year          smallint GENERATED ALWAYS AS (split_part(docket, '/', 2)::smallint) STORED,
  quarter_by_decision  text GENERATED ALWAYS AS (
                         extract(year FROM decision_date)::integer::text || 'Q'
                         || extract(quarter FROM decision_date)::integer::text) STORED,
  language             ops.lang_code NOT NULL,
  gegenstand           text CHECK (gegenstand IS NULL OR length(btrim(gegenstand)) > 0),
  previous_instance    text,
  bger_url             text NOT NULL CHECK (bger_url ~ '^https://'),
  origin               ops.ruling_origin NOT NULL,
  created_by_run_id    uuid NOT NULL REFERENCES ops.pipeline_run(run_id) ON DELETE RESTRICT,
  created_at           timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ruling_key_uq UNIQUE (docket, decision_date)
);
COMMENT ON TABLE corpus.ruling IS
  'Identity of one Federal Court decision. Key (docket, decision_date): one docket can hold several decisions. Id = uuid5(''bger|<docket>|<YYYY-MM-DD>''), set or checked by trigger. docs/DB_DDL_PLANNING.md §8.4.';
COMMENT ON COLUMN corpus.ruling.gegenstand IS 'HF title (the Gegenstand). NULL when empty (47 of the 2,096 Q2 rulings).';
COMMENT ON COLUMN corpus.ruling.bger_url IS 'Built by code from the aza:// id, never typed by a model (G1).';

CREATE TABLE IF NOT EXISTS corpus.ruling_source_ref (
  source        text NOT NULL CHECK (source ~ '^[a-z0-9_]+$'),
  external_id   text NOT NULL,
  ruling_id     uuid NOT NULL REFERENCES corpus.ruling(ruling_id) ON DELETE RESTRICT,
  snapshot_id   uuid NOT NULL REFERENCES ops.source_snapshot(snapshot_id) ON DELETE RESTRICT,
  is_twin       boolean NOT NULL DEFAULT false,
  created_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (source, external_id)
);
COMMENT ON TABLE corpus.ruling_source_ref IS 'Every source row behind a ruling (hf_decision_id, aza_id, team_list_2096), twins included: an HF -DYYYYMMDD row is a twin only when its base row has the same date. Append-only.';
CREATE INDEX IF NOT EXISTS ruling_source_ref_ruling_ix ON corpus.ruling_source_ref (ruling_id);

CREATE TABLE IF NOT EXISTS corpus.publication_observation (
  observation_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ruling_id        uuid NOT NULL REFERENCES corpus.ruling(ruling_id) ON DELETE RESTRICT,
  source           ops.publication_source NOT NULL,
  quality          ops.publication_quality NOT NULL,
  observed_date    date NOT NULL,
  star             boolean,
  sachgebiet       text,
  snapshot_id      uuid NOT NULL REFERENCES ops.source_snapshot(snapshot_id) ON DELETE RESTRICT,
  created_at       timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT publication_observation_uq UNIQUE (ruling_id, source),
  CONSTRAINT publication_observation_quality_chk CHECK ((source = 'hf_first_seen') = (quality = 'approx_first_seen'))
);
COMMENT ON TABLE corpus.publication_observation IS
  'What a source says about the publication date. Exact only from a Neuheiten page (ours, or HF''s poller from 19 May 2026); a first-seen date is an approximation, never a publication date (D-050). Append-only.';

CREATE TABLE IF NOT EXISTS corpus.subject_observation (
  observation_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ruling_id        uuid NOT NULL REFERENCES corpus.ruling(ruling_id) ON DELETE RESTRICT,
  source           ops.subject_source NOT NULL,
  rubric           text NOT NULL CHECK (length(btrim(rubric)) > 0),
  star             boolean,
  snapshot_id      uuid NOT NULL REFERENCES ops.source_snapshot(snapshot_id) ON DELETE RESTRICT,
  created_at       timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT subject_observation_uq UNIQUE (ruling_id, source)
);
COMMENT ON TABLE corpus.subject_observation IS
  'The matter rubric (Sachgebiet) a source states: the Neuheiten page (authoritative, with the publication star) or HF legal_area (empty for most Q2/2026 rulings). Layer 1 reads neuheiten > hf_legal_area > the head of gegenstand, and records which one it used (D-072). Append-only.';

CREATE TABLE IF NOT EXISTS corpus.ruling_text (
  text_id          uuid PRIMARY KEY,
  ruling_id        uuid NOT NULL REFERENCES corpus.ruling(ruling_id) ON DELETE RESTRICT,
  source           ops.text_source NOT NULL,
  content          text NOT NULL CHECK (length(btrim(content)) > 0),
  content_sha256   char(64) NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
  char_length      integer GENERATED ALWAYS AS (char_length(content)) STORED,
  clean_length     integer CHECK (clean_length >= 0),
  is_primary       boolean NOT NULL DEFAULT false,
  snapshot_id      uuid NOT NULL REFERENCES ops.source_snapshot(snapshot_id) ON DELETE RESTRICT,
  fetched_at       timestamptz,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ruling_text_uq UNIQUE (ruling_id, source, content_sha256)
);
CREATE UNIQUE INDEX IF NOT EXISTS ruling_text_one_primary_uix ON corpus.ruling_text (ruling_id) WHERE is_primary;
COMMENT ON TABLE corpus.ruling_text IS
  'Text versions of a ruling. A second text (e.g. a bger.ch fidelity sample) is a new row, never an overwrite. content_sha256 is checked by trigger. Id = uuid5(''text|<ruling_id>|<source>|<content_sha256>''). Only is_primary may change.';

CREATE TABLE IF NOT EXISTS corpus.segmentation (
  segmentation_id       uuid PRIMARY KEY,
  text_id               uuid NOT NULL REFERENCES corpus.ruling_text(text_id) ON DELETE RESTRICT,
  component_version_id  uuid NOT NULL REFERENCES ops.component_version(component_version_id) ON DELETE RESTRICT,
  method                ops.segmentation_method NOT NULL,
  status                ops.segmentation_status NOT NULL,
  consideration_count   integer NOT NULL CHECK (consideration_count >= 0),
  expected_count        integer CHECK (expected_count >= 0),
  coverage_ratio        numeric(6,5) CHECK (coverage_ratio BETWEEN 0 AND 1),
  offsets_found_ratio   numeric(6,5) CHECK (offsets_found_ratio BETWEEN 0 AND 1),
  is_primary            boolean NOT NULL DEFAULT false,
  created_by_run_id     uuid NOT NULL REFERENCES ops.pipeline_run(run_id) ON DELETE RESTRICT,
  span_id               uuid REFERENCES ops.span(span_id) ON DELETE RESTRICT,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT segmentation_uq UNIQUE (text_id, component_version_id),
  CONSTRAINT segmentation_primary_ok_chk CHECK (NOT is_primary OR status = 'ok')
);
CREATE UNIQUE INDEX IF NOT EXISTS segmentation_one_primary_uix ON corpus.segmentation (text_id) WHERE is_primary;
COMMENT ON TABLE corpus.segmentation IS
  'One splitting of a text into considerations, by one splitter version, with its quality. The splitter matures on samples; a version becomes primary at count match >= 99 % and coverage >= 98 %, written before measuring (D-070). Id = uuid5(''segmentation|<text_id>|<component_version_id>''). Only is_primary may change.';

CREATE TABLE IF NOT EXISTS corpus.consideration (
  consideration_id         uuid PRIMARY KEY,
  segmentation_id          uuid NOT NULL REFERENCES corpus.segmentation(segmentation_id) ON DELETE RESTRICT,
  ordinal                  integer NOT NULL CHECK (ordinal >= 1),
  cid                      text GENERATED ALWAYS AS ('c' || ordinal::text) STORED,
  e_number                 text NOT NULL CHECK (length(btrim(e_number)) > 0),
  depth                    smallint NOT NULL CHECK (depth >= 0),
  parent_consideration_id  uuid REFERENCES corpus.consideration(consideration_id) ON DELETE RESTRICT,
  is_citable               boolean GENERATED ALWAYS AS (depth >= 1) STORED,
  char_start               integer CHECK (char_start >= 0),
  char_end                 integer,
  content                  text NOT NULL CHECK (length(btrim(content)) > 0),
  content_sha256           char(64) NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
  created_at               timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT consideration_ordinal_uq UNIQUE (segmentation_id, ordinal),
  CONSTRAINT consideration_offsets_chk CHECK ((char_start IS NULL) = (char_end IS NULL) AND (char_end IS NULL OR char_end >= char_start)),
  CONSTRAINT consideration_unnumbered_chk CHECK (e_number <> '0' OR depth = 0)
);
COMMENT ON TABLE corpus.consideration IS
  'One consideration (Erwägung). cid c1..cn is what Apertus sees and may cite (G1); e_number is the court''s numbering, rendered E. x / consid. x by code (D-037). e_number "0" = unnumbered reasoning, not citable. Id = uuid5(''consideration|<segmentation_id>|<ordinal>''). Append-only.';

CREATE TABLE IF NOT EXISTS corpus.ruling_parse (
  parse_id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ruling_id             uuid NOT NULL REFERENCES corpus.ruling(ruling_id) ON DELETE RESTRICT,
  text_id               uuid NOT NULL REFERENCES corpus.ruling_text(text_id) ON DELETE RESTRICT,
  component_version_id  uuid NOT NULL REFERENCES ops.component_version(component_version_id) ON DELETE RESTRICT,
  parties_block         text,
  bench_size            smallint CHECK (bench_size BETWEEN 1 AND 9),
  operative_part        text,
  outcome               ops.outcome_kind,
  outcome_rule_id       uuid REFERENCES ops.rule(rule_id) ON DELETE RESTRICT,
  facts_start           integer CHECK (facts_start >= 0),
  considerations_start  integer CHECK (considerations_start >= 0),
  dispositive_start     integer CHECK (dispositive_start >= 0),
  clean_length          integer CHECK (clean_length >= 0),
  created_by_run_id     uuid NOT NULL REFERENCES ops.pipeline_run(run_id) ON DELETE RESTRICT,
  span_id               uuid REFERENCES ops.span(span_id) ON DELETE RESTRICT,
  created_at            timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ruling_parse_uq UNIQUE (text_id, component_version_id)
);
COMMENT ON TABLE corpus.ruling_parse IS 'Parse of one text by one parser version: parties block, bench size, operative part, outcome (taken by code from the operative part). Names of natural persons are never extracted (D-038). Append-only.';

CREATE TABLE IF NOT EXISTS corpus.ingest_issue (
  issue_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ruling_id     uuid NOT NULL REFERENCES corpus.ruling(ruling_id) ON DELETE RESTRICT,
  reason_code   text NOT NULL REFERENCES ops.reason_code(code) ON DELETE RESTRICT,
  detail        jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(detail) = 'object'),
  run_id        uuid NOT NULL REFERENCES ops.pipeline_run(run_id) ON DELETE RESTRICT,
  span_id       uuid REFERENCES ops.span(span_id) ON DELETE RESTRICT,
  created_at    timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE corpus.ingest_issue IS 'A counted, auditable reason for a gap (no text, considerations missing, count mismatch, publication unknown...): G5. Append-only.';
CREATE INDEX IF NOT EXISTS ingest_issue_ruling_ix ON corpus.ingest_issue (ruling_id);

CREATE TABLE IF NOT EXISTS corpus.population (
  population_id        uuid PRIMARY KEY,
  code                 text NOT NULL UNIQUE CHECK (code ~ '^[A-Za-z0-9_]+$'),
  quarter              text CHECK (quarter ~ '^[0-9]{4}Q[1-4]$'),
  definition           ops.population_definition NOT NULL,
  role                 ops.population_role NOT NULL,
  is_delivery_default  boolean NOT NULL DEFAULT false,
  description          text,
  manifest_sha256      char(64) CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
  frozen_at            timestamptz,
  built_by_run_id      uuid NOT NULL REFERENCES ops.pipeline_run(run_id) ON DELETE RESTRICT,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT population_frozen_manifest_chk CHECK (frozen_at IS NULL OR manifest_sha256 IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS population_one_delivery_default_uix ON corpus.population (is_delivery_default) WHERE is_delivery_default;
COMMENT ON TABLE corpus.population IS
  'A set of rulings: 2026Q2_union (target), 2026Q2_decision, 2026Q2_publication (delivery default, D-052), 2025Q4_decision, 2026Q1_decision (labelled), suva_reference. Both date readings coexist (D-050). Id = uuid5(''population|<code>''). Frozen = no new member.';

CREATE TABLE IF NOT EXISTS corpus.population_member (
  population_id  uuid NOT NULL REFERENCES corpus.population(population_id) ON DELETE RESTRICT,
  ruling_id      uuid NOT NULL REFERENCES corpus.ruling(ruling_id) ON DELETE RESTRICT,
  basis          ops.member_basis NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (population_id, ruling_id)
);
CREATE INDEX IF NOT EXISTS population_member_ruling_ix ON corpus.population_member (ruling_id);
COMMENT ON TABLE corpus.population_member IS 'Membership and why (decision date, exact or approximate publication date). Append-only; refused once the population is frozen.';
