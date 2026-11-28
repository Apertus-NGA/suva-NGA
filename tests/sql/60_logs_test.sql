-- Logs (D-065): spans close once, events land in day partitions (or the default), payload size limit,
-- idempotent reload, append-only, timeline and health views, partition creation.
BEGIN;
\ir _fixtures.sql

-- a span closes once, with a computed duration
INSERT INTO ops.span (span_id, run_id, step, operation, ruling_id, status, started_at)
VALUES ('00000000-0000-4000-8000-000000000b01', '00000000-0000-4000-8000-000000000001', 'layer2_judge', 'llm.call',
        pg_temp.rid('8C_493/2025'), 'running', now() - interval '2 seconds');
UPDATE ops.span SET status = 'ok', ended_at = now() WHERE span_id = '00000000-0000-4000-8000-000000000b01';
DO $$ BEGIN
  ASSERT (SELECT duration_ms BETWEEN 1500 AND 10000 FROM ops.span WHERE span_id = '00000000-0000-4000-8000-000000000b01'), 'duration_ms computed';
END $$;
SELECT pg_temp.expect_error($q$UPDATE ops.span SET status = 'error', ended_at = now() WHERE span_id = '00000000-0000-4000-8000-000000000b01'$q$, 'already closed');
SELECT pg_temp.expect_error($q$
  INSERT INTO ops.span (run_id, operation, status, started_at, ended_at)
  VALUES ('00000000-0000-4000-8000-000000000001', 'x', 'ok', now(), now() - interval '1 hour')$q$, 'order_chk');
SELECT pg_temp.expect_error($q$
  INSERT INTO ops.span (run_id, operation, status, started_at) VALUES ('00000000-0000-4000-8000-000000000001', 'x', 'ok', now())$q$, 'closed_chk');
SELECT pg_temp.expect_error($q$DELETE FROM ops.span WHERE span_id = '00000000-0000-4000-8000-000000000b01'$q$, 'append-only');

-- events: today's partition, the default partition for a day without one
INSERT INTO ops.log_event (run_id, seq, ts, span_id, ruling_id, step, level, event_code, message, attributes) VALUES
  ('00000000-0000-4000-8000-000000000001', 1, now(), '00000000-0000-4000-8000-000000000b01', pg_temp.rid('8C_493/2025'), 'layer2_judge',
   'info', 'llm.response.received', 'served model checked', '{"finish_reason": "stop"}'),
  ('00000000-0000-4000-8000-000000000001', 2, '2030-06-01 12:00+00', NULL, NULL, NULL, 'debug', 'layer1.rule.evaluated', 'far future', '{}');
DO $$ BEGIN
  ASSERT (SELECT tableoid::regclass::text FROM ops.log_event WHERE seq = 1) LIKE 'ops.log_event_p%', 'today has its own partition';
  ASSERT (SELECT tableoid::regclass::text FROM ops.log_event WHERE seq = 2) = 'ops.log_event_default', 'other days go to the default partition';
END $$;
INSERT INTO ops.log_event (run_id, seq, ts, level, event_code, message)
SELECT run_id, seq, ts, level, event_code, message FROM ops.log_event WHERE seq = 1
ON CONFLICT DO NOTHING;
DO $$ BEGIN
  ASSERT (SELECT count(*) FROM ops.log_event WHERE run_id = '00000000-0000-4000-8000-000000000001') = 2, 'reloading a log file is idempotent';
END $$;
SELECT pg_temp.expect_error($q$
  INSERT INTO ops.log_event (run_id, seq, ts, level, event_code, message) VALUES ('00000000-0000-4000-8000-000000000001', 3, now(), 'info', 'Bad Code', 'x')$q$,
  'check constraint');
SELECT pg_temp.expect_error($q$
  INSERT INTO ops.log_event (run_id, seq, ts, level, event_code, message, attributes)
  SELECT '00000000-0000-4000-8000-000000000001', 4, now(), 'info', 'layer2.prompt.built', 'too big',
         jsonb_build_object('payload', (SELECT string_agg(md5(i::text), '') FROM generate_series(1, 2000) AS i))$q$, 'check constraint');
SELECT pg_temp.expect_error($q$UPDATE ops.log_event SET message = 'x' WHERE seq = 1$q$, 'only .* may change');

-- timeline and health
DO $$ BEGIN
  ASSERT (SELECT count(*) FILTER (WHERE kind = 'span') > 0 AND count(*) FILTER (WHERE kind = 'event') = 1
          FROM ops.v_ruling_timeline WHERE ruling_id = pg_temp.rid('8C_493/2025')), 'timeline holds spans and events';
  ASSERT (SELECT count(*) FROM ops.v_run_health WHERE run_id = '00000000-0000-4000-8000-000000000001') >= 5, 'health per step';
END $$;

-- metrics are append-only; partitions are created on demand
INSERT INTO ops.run_metric (run_id, step, metric_code, value, unit) VALUES ('00000000-0000-4000-8000-000000000001', 'layer1_filter', 'kept', 2, 'rulings');
SELECT pg_temp.expect_error($q$UPDATE ops.run_metric SET value = 3$q$, 'only .* may change');
DO $$ BEGIN
  ASSERT ops.ensure_log_partitions('2031-01-01', '2031-01-03') = 3, 'three partitions created';
  ASSERT ops.ensure_log_partitions('2031-01-01', '2031-01-03') = 0, 'idempotent';
END $$;

ROLLBACK;
