-- Summary workspace: confirming a summary as final (gold), and an append-only record of every action.
-- Rows of summary_events are inserted, never changed or deleted. The texts are not copied into an event:
-- "before" and "after" point at two versions in `summaries`, which keeps every version.
-- All experts share one identity for now: actor = 'expert'.

-- A summary an expert confirmed as final. The model can never set these.
ALTER TABLE summaries
    ADD COLUMN confirmed_at timestamptz,
    ADD COLUMN confirmed_by text,
    ADD CONSTRAINT summaries_confirmed_together CHECK ((confirmed_at IS NULL) = (confirmed_by IS NULL));

CREATE TABLE summary_events (
    id          bigserial PRIMARY KEY,
    ruling_id   bigint NOT NULL REFERENCES rulings (id) ON DELETE RESTRICT,
    language    text   NOT NULL CHECK (language IN ('de', 'fr')),
    action      text   NOT NULL CHECK (action IN ('generate', 'revise', 'edit', 'confirm', 'unconfirm')),
    -- Why a revision was asked for: one click, countable. NULL for the other actions.
    reason      text   CHECK (reason IN ('shorter', 'more_detail', 'rule_first', 'key_point', 'cite_considerations',
                                         'terminology', 'align_languages', 'wrong_statement', 'other')),
    note        text,                                   -- the expert's words: which consideration, which sentence, ...
    before_id   bigint REFERENCES summaries (id) ON DELETE RESTRICT,   -- the version on screen
    after_id    bigint REFERENCES summaries (id) ON DELETE RESTRICT,   -- the version this action produced or confirmed
    unchanged   boolean,                                -- confirm only: true = accepted exactly as the model wrote it
    actor       text   NOT NULL DEFAULT 'expert',
    created_at  timestamptz NOT NULL DEFAULT now(),
    CHECK ((action = 'revise') = (reason IS NOT NULL))
);
CREATE INDEX summary_events_ruling_idx ON summary_events (ruling_id, language, id);
