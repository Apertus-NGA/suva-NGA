-- Expert decisions on relevance, as an append-only record: rows are inserted, never changed or deleted.
-- Each row keeps what the expert saw (the status and score at that moment) and what they decided, so
-- "how many AI-assessed rulings were confirmed" is a count over this table. That is the training data.
-- The current human decision is still the 'expert_override' row in `labels` (read by v_relevance); it is
-- written in the same transaction as the event (src/suva_app/feedback.py).
-- All experts share one identity for now: actor = 'expert'.
CREATE TABLE relevance_events (
    id            bigserial PRIMARY KEY,
    ruling_id     bigint NOT NULL REFERENCES rulings (id) ON DELETE RESTRICT,   -- a ruling with a decision cannot be deleted
    action        text   NOT NULL CHECK (action IN ('confirm_relevant', 'mark_not_relevant', 'reopen')),
    status_before text   NOT NULL CHECK (status_before IN ('not_assessed', 'potentially_relevant', 'ai_relevant', 'expert_confirmed', 'not_relevant')),
    status_after  text   NOT NULL CHECK (status_after  IN ('not_assessed', 'potentially_relevant', 'ai_relevant', 'expert_confirmed', 'not_relevant')),
    prediction_id bigint REFERENCES predictions (id) ON DELETE SET NULL,        -- the prediction on screen, if any
    score_shown   double precision CHECK (score_shown BETWEEN 0 AND 1),         -- copied, so it survives the prediction
    reason        text,                                                         -- optional short code
    comment       text,
    actor         text   NOT NULL DEFAULT 'expert',
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX relevance_events_ruling_idx ON relevance_events (ruling_id, id);
