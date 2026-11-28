-- Model output and expert edits: the contract between the pipeline (triage, summariser) and the UI.
-- Same rules as 001: constraints live here; unknown is NULL, never a default.
-- Expert relevance overrides are NOT here: they are rows in `labels` with label_set = 'expert_override'
-- (already read by v_relevance).

-- One row per triage or summarisation run: which models did what, with which settings.
CREATE TABLE model_runs (
    id         bigserial PRIMARY KEY,
    kind       text  NOT NULL CHECK (kind IN ('triage', 'summary')),
    -- Every model used, with its role: [{"name": "apertus-v1-5-70b", "role": "relevance classification"}, ...]
    models     jsonb NOT NULL CHECK (jsonb_typeof(models) = 'array' AND jsonb_array_length(models) > 0),
    params     jsonb NOT NULL DEFAULT '{}',     -- prompt version, threshold, feature list, ...
    git_commit text,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Relevance prediction for a ruling. Old predictions are kept; exactly one per ruling is current.
CREATE TABLE predictions (
    id          bigserial PRIMARY KEY,
    ruling_id   bigint  NOT NULL REFERENCES rulings (id) ON DELETE CASCADE,
    run_id      bigint  NOT NULL REFERENCES model_runs (id) ON DELETE CASCADE,
    score       double precision NOT NULL CHECK (score BETWEEN 0 AND 1),
    relevant    boolean NOT NULL,               -- the decision at the run's threshold
    explanation text,                           -- why relevant / not relevant, shown to the expert
    details     jsonb   NOT NULL DEFAULT '{}',  -- features, rubric answers, ...
    is_current  boolean NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (ruling_id, run_id)
);
CREATE UNIQUE INDEX predictions_one_current ON predictions (ruling_id) WHERE is_current;
CREATE INDEX predictions_current_score ON predictions (score DESC) WHERE is_current;

-- Generated summaries and expert edits of them. Versioned per (ruling, language); one version is current.
CREATE TABLE summaries (
    id         bigserial PRIMARY KEY,
    ruling_id  bigint  NOT NULL REFERENCES rulings (id) ON DELETE CASCADE,
    language   text    NOT NULL CHECK (language IN ('de', 'fr')),
    headline   text,                            -- the bold one-line statement; NULL if the summary has none
    body       text    NOT NULL CHECK (body ~ '\S'),   -- not only whitespace; paragraphs separated by a blank line
    origin     text    NOT NULL CHECK (origin IN ('model', 'expert')),
    run_id     bigint  REFERENCES model_runs (id) ON DELETE SET NULL,
    parent_id  bigint  REFERENCES summaries (id) ON DELETE SET NULL,   -- the version an expert edit started from
    version    integer NOT NULL DEFAULT 1 CHECK (version >= 1),
    is_current boolean NOT NULL DEFAULT true,
    created_by text    NOT NULL DEFAULT 'pipeline',
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (ruling_id, language, version),
    CHECK (origin <> 'expert' OR run_id IS NULL)   -- an expert edit is not the output of a run
);
CREATE UNIQUE INDEX summaries_one_current ON summaries (ruling_id, language) WHERE is_current;
