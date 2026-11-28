-- Expert scope verdicts on any label, and withdrawal (D-093). relevant | not_relevant give the expert's own label on
-- any pipeline label, potentially included; correct | incorrect stay on in_scope | out_of_scope; withdrawn takes back
-- the review it supersedes (same target, never a withdrawal) and leaves no expert label. The payload records what the
-- expert saw (scope_review.payload V1.1.0), so each (seen, given) pair is a training example.
-- Synthetic ruling 8C_901/2026 (judged by layer 2 only), no personal data.
BEGIN;
\ir _fixtures.sql
SET LOCAL app.actor = 'expert-1';

-- a review by its comment (each review below has its own)
CREATE FUNCTION pg_temp.rv(p_comment text) RETURNS uuid LANGUAGE sql AS
  $f$ SELECT review_id FROM gold.expert_review WHERE comment = p_comment $f$;
CREATE FUNCTION pg_temp.seen(p_docket text) RETURNS text LANGUAGE sql AS $f$
  SELECT concat_ws('|', pipeline_label, expert_verdict, coalesce(expert_implied_label::text, '-'), reviewed_label, review_is_stale::text)
  FROM triage.v_scope_current WHERE ruling_id = pg_temp.rid(p_docket) $f$;

-- a ruling whose label is layer 2's: potentially (no ranking step yet, D-075)
INSERT INTO corpus.ruling (docket, decision_date, language, gegenstand, bger_url, origin, created_by_run_id) VALUES
  ('8C_901/2026', '2026-05-21', 'de', 'Unfallversicherung (Rückfall)',
   'https://search.bger.ch/ext/eurospider/live/de/php/aza/http/index.php?lang=de&type=show_document&highlight_docid=aza://21-05-2026-8C_901-2026',
   'base_dataset', '00000000-0000-4000-8000-000000000001');
INSERT INTO triage.assessment (assessment_id, run_id, ruling_id, step, component_version_id, span_id, upstream_assessment_id,
                               input_fingerprint, in_suva_scope, outcome, score_raw, score_0_100, score_source, reason_code, mode, started_at)
VALUES ('00000000-0000-4000-8000-000000000d01', '00000000-0000-4000-8000-000000000001', pg_temp.rid('8C_901/2026'), 'layer1_filter',
        pg_temp.cv('layer1_filter'), pg_temp.span('layer1_filter', '8C_901/2026'), NULL, repeat('0', 64), 'potentially', 'ok',
        NULL, NULL, NULL, 'L1_KEEP_RUBRIC', 'REPLAY', now()),
       ('00000000-0000-4000-8000-000000000d02', '00000000-0000-4000-8000-000000000001', pg_temp.rid('8C_901/2026'), 'layer2_judge',
        pg_temp.cv('layer2_judge'), pg_temp.span('layer2_judge', '8C_901/2026'), '00000000-0000-4000-8000-000000000d01',
        repeat('0', 64), 'potentially', 'ok', 0.58, 64, 'judged', NULL, 'REPLAY', now());
DO $$ BEGIN
  ASSERT (SELECT pipeline_label || '|' || step || '|' || assessment_id FROM triage.v_scope_pipeline WHERE ruling_id = pg_temp.rid('8C_901/2026'))
         = 'potentially|layer2_judge|00000000-0000-4000-8000-000000000d02', 'layer 2 forms the label';
END $$;

-- the payload schema: V1.1.0 is the latest active scope payload, a minor bump of V1.0.0, which stays in place
DO $$ BEGIN
  ASSERT (SELECT s.status || '|' || s.bump_kind || '|' || p.version_label || '|' || p.status
          FROM ops.json_schema s JOIN ops.json_schema p ON p.json_schema_id = s.previous_version_id
          WHERE s.schema_code = 'scope_review.payload' AND s.version_label = 'V1.1.0') = 'active|minor|V1.0.0|active',
         'scope_review.payload V1.1.0 follows V1.0.0';
  ASSERT (SELECT json_schema -> 'properties' ? 'shown_score_0_100' AND (json_schema ->> 'additionalProperties')::boolean IS FALSE
          FROM ops.json_schema WHERE schema_code = 'scope_review.payload' AND version_label = 'V1.1.0'), 'V1.1.0 declares what the expert saw';
  ASSERT (SELECT max(version_label) FROM ops.json_schema WHERE schema_code = 'summary_review.payload') = 'V1.0.0', 'summary payload unchanged';
END $$;

-- relevant on a potentially label: accepted, the expert's label is in_scope; submit_review picks payload V1.1.0
SELECT gold.submit_review('scope', '00000000-0000-4000-8000-000000000d02', 'relevant',
                          '{"shown_status": "potentially", "shown_score_0_100": 64, "shown_score_raw": 0.58}', 'r1');
DO $$ BEGIN
  ASSERT pg_temp.seen('8C_901/2026') = 'potentially|relevant|in_scope|potentially|false', format('relevant: %s', pg_temp.seen('8C_901/2026'));
  ASSERT (SELECT s.schema_code || '|' || s.version_label || '|' || (r.payload ->> 'shown_score_0_100')
          FROM gold.expert_review r JOIN ops.json_schema s ON s.json_schema_id = r.review_schema_id WHERE r.review_id = pg_temp.rv('r1'))
         = 'scope_review.payload|V1.1.0|64', 'the latest active scope payload, with what the expert saw';
END $$;

-- the relative verdicts still never review a potentially label
SELECT pg_temp.expect_error($q$SELECT gold.submit_review('scope', '00000000-0000-4000-8000-000000000d02', 'correct')$q$, 'target_chk');
SELECT pg_temp.expect_error($q$SELECT gold.submit_review('scope', '00000000-0000-4000-8000-000000000d02', 'incorrect')$q$, 'target_chk');
-- a summary verdict on a scope target, and a scope verdict on a summary, stay refused
SELECT pg_temp.expect_error($q$SELECT gold.submit_review('scope', '00000000-0000-4000-8000-000000000d02', 'validated')$q$, 'target_chk');
SELECT pg_temp.expect_error($q$SELECT gold.submit_review('summary_version', '00000000-0000-4000-8000-000000000701', 'relevant')$q$, 'target_chk');

-- the expert changes their mind: not_relevant supersedes relevant, the expert's label is out_of_scope
SELECT gold.submit_review('scope', '00000000-0000-4000-8000-000000000d02', 'not_relevant', '{"shown_status": "potentially"}', 'r2',
                          pg_temp.rv('r1'));
DO $$ BEGIN
  ASSERT pg_temp.seen('8C_901/2026') = 'potentially|not_relevant|out_of_scope|potentially|false', format('not_relevant: %s', pg_temp.seen('8C_901/2026'));
END $$;

-- not_relevant on the potentially layer-2 assessment of a ruling the pipeline later ranked in_scope: a stale review
SELECT gold.submit_review('scope', '00000000-0000-4000-8000-000000000201', 'not_relevant', '{}', 'r3');
DO $$ BEGIN
  ASSERT pg_temp.seen('8C_493/2025') = 'in_scope|not_relevant|out_of_scope|potentially|true', format('stale review: %s', pg_temp.seen('8C_493/2025'));
END $$;
-- relevant on an out_of_scope label (the expert overrides the pipeline), on the current assessment
SELECT gold.submit_review('scope', '00000000-0000-4000-8000-000000000603', 'relevant', '{}', 'r4');
DO $$ BEGIN
  ASSERT pg_temp.seen('8C_199/2026') = 'out_of_scope|relevant|in_scope|out_of_scope|false', format('override: %s', pg_temp.seen('8C_199/2026'));
END $$;

-- withdrawn: needs the review it takes back, of the same target, and never a withdrawal
SELECT pg_temp.expect_error($q$SELECT gold.submit_review('scope', '00000000-0000-4000-8000-000000000d02', 'withdrawn')$q$, 'p_supersedes');
SELECT pg_temp.expect_error($q$
  INSERT INTO gold.expert_review (target_kind, assessment_id, verdict, reviewed_label, review_schema_id, actor)
  SELECT 'scope', '00000000-0000-4000-8000-000000000d02', 'withdrawn', 'potentially', json_schema_id, 'expert-1'
  FROM ops.json_schema WHERE schema_code = 'scope_review.payload' AND version_label = 'V1.1.0'$q$, 'target_chk');
SELECT pg_temp.expect_error($q$
  SELECT gold.submit_review('scope', '00000000-0000-4000-8000-000000000d02', 'withdrawn', '{}', 'x', pg_temp.rv('r3'))$q$, 'same target');

SELECT gold.submit_review('scope', '00000000-0000-4000-8000-000000000d02', 'withdrawn', '{"shown_status": "potentially"}', 'w1',
                          pg_temp.rv('r2'));
DO $$ BEGIN
  ASSERT pg_temp.seen('8C_901/2026') = 'potentially|withdrawn|-|potentially|false', format('withdrawn: %s', pg_temp.seen('8C_901/2026'));
  ASSERT (SELECT expert_implied_label IS NULL AND reviewed_assessment_id = '00000000-0000-4000-8000-000000000d02'
          FROM triage.v_scope_current WHERE ruling_id = pg_temp.rid('8C_901/2026')), 'no expert label after a withdrawal';
  ASSERT (SELECT verdict FROM gold.v_expert_review_current WHERE assessment_id = '00000000-0000-4000-8000-000000000d02') = 'withdrawn',
         'the withdrawal is the current review of its target';
END $$;
SELECT pg_temp.expect_error($q$
  SELECT gold.submit_review('scope', '00000000-0000-4000-8000-000000000d02', 'withdrawn', '{}', 'x', pg_temp.rv('w1'))$q$, 'never a withdrawal');

-- after a withdrawal the expert may decide again
SELECT gold.submit_review('scope', '00000000-0000-4000-8000-000000000d02', 'relevant', '{}', 'r5', pg_temp.rv('w1'));
DO $$ BEGIN
  ASSERT pg_temp.seen('8C_901/2026') = 'potentially|relevant|in_scope|potentially|false', format('decided again: %s', pg_temp.seen('8C_901/2026'));
END $$;

-- the legacy verdicts keep working on in_scope | out_of_scope (a ruling with no other review: now() does not move inside
-- this transaction, so two unsuperseded reviews of one ruling would tie on created_at)
SELECT gold.submit_review('scope', '00000000-0000-4000-8000-000000000602', 'correct', '{}', 'r6');
DO $$ BEGIN
  ASSERT pg_temp.seen('8C_307/2025') = 'out_of_scope|correct|out_of_scope|out_of_scope|false', format('legacy correct: %s', pg_temp.seen('8C_307/2025'));
END $$;
SELECT gold.submit_review('scope', '00000000-0000-4000-8000-000000000602', 'incorrect', '{}', 'r7', pg_temp.rv('r6'));
DO $$ BEGIN
  ASSERT pg_temp.seen('8C_307/2025') = 'out_of_scope|incorrect|in_scope|out_of_scope|false', format('legacy incorrect: %s', pg_temp.seen('8C_307/2025'));
END $$;

-- summary review: withdrawn with the review it supersedes, never without
SELECT gold.submit_review('summary_version', '00000000-0000-4000-8000-000000000701', 'validated', '{}', 's1');
SELECT pg_temp.expect_error($q$SELECT gold.submit_review('summary_version', '00000000-0000-4000-8000-000000000701', 'withdrawn')$q$, 'p_supersedes');
SELECT gold.submit_review('summary_version', '00000000-0000-4000-8000-000000000701', 'withdrawn', '{}', 'w2', pg_temp.rv('s1'));
DO $$ BEGIN
  ASSERT (SELECT expert_verdict FROM summ.v_summary_current WHERE ruling_id = pg_temp.rid('8C_493/2025')) = 'withdrawn', 'summary review withdrawn';
  ASSERT (SELECT reviewed_label IS NULL AND s.schema_code = 'summary_review.payload'
          FROM gold.expert_review r JOIN ops.json_schema s ON s.json_schema_id = r.review_schema_id WHERE r.review_id = pg_temp.rv('w2')),
         'a summary withdrawal has no label and the summary payload';
END $$;
SELECT pg_temp.expect_error($q$
  SELECT gold.submit_review('summary_version', '00000000-0000-4000-8000-000000000701', 'withdrawn', '{}', 'x', pg_temp.rv('w2'))$q$,
  'never a withdrawal');

-- reviews stay append-only
SELECT pg_temp.expect_error($q$UPDATE gold.expert_review SET verdict = 'withdrawn' WHERE comment = 'r5'$q$, 'only .* may change');

ROLLBACK;
