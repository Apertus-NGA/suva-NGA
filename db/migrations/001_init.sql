-- Suva data layer: initial schema. See docs/ARCHITECTURE.md section 5.
-- Rules: constraints live here (6.1 #7); unknown is NULL, never a default (6.1 #6).

CREATE TABLE ingest_runs (
    id          bigserial PRIMARY KEY,
    command     text        NOT NULL,
    params      jsonb       NOT NULL DEFAULT '{}',
    git_commit  text,
    status      text        NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'ok', 'failed', 'partial')),
    report      jsonb,
    started_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);

-- Every file in the published snapshot, with its checksum.
CREATE TABLE raw_files (
    id        bigserial PRIMARY KEY,
    source    text   NOT NULL CHECK (source IN ('bger_list', 'bger_ruling', 'entscheidsuche', 'swiss_caselaw', 'suva')),
    path      text   NOT NULL UNIQUE,          -- relative to the snapshot directory
    sha256    text   NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    bytes     bigint NOT NULL CHECK (bytes >= 0)
);

-- One row per ruling: the canonical view, built by the reconciler from source_records.
CREATE TABLE rulings (
    id               bigserial PRIMARY KEY,
    docket           text NOT NULL CHECK (docket ~ '^\d{1,2}[A-Z]_\d+/\d{4}$'),
    decision_date    date NOT NULL,
    division         text NOT NULL,
    language         text CHECK (language IN ('de', 'fr', 'it')),
    publication_date date,                      -- NULL = not known
    starred          boolean,                   -- NULL = not known; false = seen on a bger.ch list without a star
    area             text,
    subject          text,
    outcome          text,                      -- derived (third party)
    cited_decisions  jsonb,                     -- derived (third party)
    official_url     text,
    field_sources    jsonb   NOT NULL DEFAULT '{}',   -- {"area": "bger_list", ...}
    flags            jsonb   NOT NULL DEFAULT '{}',
    in_window        boolean NOT NULL,
    UNIQUE (docket, decision_date),
    CHECK (publication_date IS NULL OR publication_date >= decision_date)
);
CREATE INDEX rulings_docket_idx ON rulings (docket);
CREATE INDEX rulings_decision_date_idx ON rulings (decision_date);

-- Every record from every source, kept as-is. Nothing is dropped here: duplicates and bad rows stay,
-- with `status` saying what the reconciler did with them.
CREATE TABLE source_records (
    id            bigserial PRIMARY KEY,
    source        text NOT NULL CHECK (source IN ('bger_list', 'bger_ruling', 'entscheidsuche', 'swiss_caselaw')),
    source_key    text NOT NULL,
    docket        text NOT NULL,
    decision_date date,
    fields        jsonb NOT NULL DEFAULT '{}',
    record        jsonb NOT NULL DEFAULT '{}',
    raw_file_id   bigint REFERENCES raw_files (id),
    ruling_id     bigint REFERENCES rulings (id) ON DELETE SET NULL,
    status        text NOT NULL DEFAULT 'loaded' CHECK (status IN ('loaded', 'used', 'duplicate', 'rejected')),
    status_reason text,
    UNIQUE (source, source_key)
);
CREATE INDEX source_records_docket_idx ON source_records (docket, decision_date);

-- Full text per source. Stored exactly as the source gave it.
CREATE TABLE ruling_texts (
    id                bigserial PRIMARY KEY,
    source_record_id  bigint NOT NULL UNIQUE REFERENCES source_records (id) ON DELETE CASCADE,
    ruling_id         bigint REFERENCES rulings (id) ON DELETE SET NULL,
    source            text    NOT NULL,
    text              text    NOT NULL,
    sha256_normalized text    NOT NULL CHECK (sha256_normalized ~ '^[0-9a-f]{64}$'),
    char_count        integer NOT NULL CHECK (char_count >= 0),
    bad_reason        text,                     -- NULL = passed the bad-text check
    is_canonical      boolean NOT NULL DEFAULT false,
    CHECK (NOT (is_canonical AND bad_reason IS NOT NULL))
);
CREATE UNIQUE INDEX ruling_texts_one_canonical ON ruling_texts (ruling_id) WHERE is_canonical;
CREATE INDEX ruling_texts_ruling_idx ON ruling_texts (ruling_id);

-- Every cross-source disagreement and every rejected value.
CREATE TABLE conflicts (
    id            bigserial PRIMARY KEY,
    ruling_id     bigint REFERENCES rulings (id) ON DELETE CASCADE,
    docket        text NOT NULL,
    decision_date date,
    field         text NOT NULL,
    kind          text NOT NULL CHECK (kind IN ('value_mismatch', 'text_mismatch', 'bad_text', 'duplicate_collapsed', 'missing_in_source', 'invalid_value')),
    winner_source text,
    loser_source  text,
    winner_value  text,
    loser_value   text
);
CREATE INDEX conflicts_ruling_idx ON conflicts (ruling_id);

CREATE TABLE statute_refs (
    ruling_id     bigint NOT NULL REFERENCES rulings (id) ON DELETE CASCADE,
    law_code      text   NOT NULL,
    article       text   NOT NULL,
    paragraph     text   NOT NULL DEFAULT '',
    mention_count integer,
    PRIMARY KEY (ruling_id, law_code, article, paragraph)
);

-- Relevance labels. Several label sets can coexist (Suva's xlsx now, expert overrides later).
CREATE TABLE labels (
    id         bigserial PRIMARY KEY,
    ruling_id  bigint NOT NULL REFERENCES rulings (id) ON DELETE CASCADE,
    label_set  text   NOT NULL,
    value      text   NOT NULL CHECK (value IN ('relevant', 'not_relevant')),
    quarter    text   CHECK (quarter ~ '^\d{4} Q[1-4]$'),
    metadata   jsonb  NOT NULL DEFAULT '{}',    -- xlsx: erstellt, sharepoint_url, xlsx_title, xlsx_row
    created_by text   NOT NULL DEFAULT 'pipeline',
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (ruling_id, label_set)
);

-- Human-written reference summaries. Versioned so expert edits fit later.
CREATE TABLE gold_summaries (
    id          bigserial PRIMARY KEY,
    ruling_id   bigint  NOT NULL REFERENCES rulings (id) ON DELETE CASCADE,
    language    text    NOT NULL CHECK (language IN ('de', 'fr')),
    title       text    NOT NULL,
    body        text    NOT NULL CHECK (length(btrim(body)) > 0),   -- paragraphs separated by a blank line
    author      text,
    source_url  text,                           -- the "Link zum Urteil" in the export
    source_file text,
    version     integer NOT NULL DEFAULT 1,
    is_current  boolean NOT NULL DEFAULT true,
    created_by  text    NOT NULL DEFAULT 'pipeline',
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (ruling_id, language, version)
);
CREATE UNIQUE INDEX gold_summaries_one_current ON gold_summaries (ruling_id, language) WHERE is_current;

-- Relevance as used for training / evaluation. 'not_relevant' is derived, never stored (A4).
CREATE VIEW v_relevance AS
SELECT r.id AS ruling_id,
       r.docket,
       r.decision_date,
       to_char(r.decision_date, 'YYYY "Q"Q') AS decision_quarter,
       CASE
           WHEN ov.value IS NOT NULL THEN ov.value
           WHEN xl.ruling_id IS NOT NULL THEN 'relevant'
           WHEN gs.ruling_id IS NOT NULL THEN 'relevant'
           WHEN r.decision_date BETWEEN DATE '2025-10-01' AND DATE '2026-03-31' THEN 'not_relevant'
           ELSE 'unknown'
       END AS relevance,
       CASE
           WHEN ov.value IS NOT NULL THEN 'expert_override'
           WHEN xl.ruling_id IS NOT NULL THEN 'suva_xlsx'
           WHEN gs.ruling_id IS NOT NULL THEN 'gold_summary_only'
           WHEN r.decision_date BETWEEN DATE '2025-10-01' AND DATE '2026-03-31' THEN 'complete_list_negative'
           ELSE 'no_label'
       END AS basis
FROM rulings r
LEFT JOIN labels ov ON ov.ruling_id = r.id AND ov.label_set = 'expert_override'
LEFT JOIN labels xl ON xl.ruling_id = r.id AND xl.label_set = 'suva_xlsx_2025Q4_2026Q1' AND xl.value = 'relevant'
LEFT JOIN (SELECT DISTINCT ruling_id FROM gold_summaries WHERE is_current) gs ON gs.ruling_id = r.id;
