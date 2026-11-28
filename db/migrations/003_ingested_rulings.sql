-- Rulings added by a live ingest (python -m suva_data ingest), on top of the pinned dataset.
-- The pinned dataset is selected by a fixed decision-date window; an ingest selects by PUBLICATION date,
-- so it can add rulings decided outside that window. This table is how a later rebuild knows to keep them.
-- A row is written once and never changed: (docket, decision_date) identifies the ruling.
CREATE TABLE ingested_rulings (
    docket         text NOT NULL CHECK (docket ~ '^\d{1,2}[A-Z]_\d+/\d{4}$'),
    decision_date  date NOT NULL,
    published_from date NOT NULL,                  -- the publication-date range of the run that added it
    published_to   date NOT NULL CHECK (published_to >= published_from),
    ingested_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (docket, decision_date)
);
