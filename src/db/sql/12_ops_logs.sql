-- ============================================================================
-- File: 12_ops_logs.sql (log events, partitioned by day)
-- Date: 2026-11-28
-- Description: Log lines of every step, linked to their run and span. Append-heavy, so partitioned by
--              RANGE on ts (one partition per day) with a DEFAULT partition. (run_id, seq) is the emitter's
--              per-run counter: reloading data/runs/<run_id>/events.jsonl is idempotent. No FK on span_id on
--              purpose (write speed, partition independence): integrity is checked by a test query.
-- SGBD: PostgreSQL 17
-- Doc: docs/DB_DDL_PLANNING.md §11
-- ============================================================================
-- PREREQUISITE: 11_ops_execution.sql
-- ============================================================================

CREATE TABLE IF NOT EXISTS ops.log_event (
  run_id      uuid NOT NULL,
  seq         bigint NOT NULL CHECK (seq >= 0),
  ts          timestamptz NOT NULL,
  span_id     uuid,
  ruling_id   uuid,
  step        ops.pipeline_step,
  level       ops.log_level NOT NULL,
  event_code  text NOT NULL CHECK (event_code ~ '^[a-z0-9_]+(\.[a-z0-9_]+){1,3}$'),
  message     text NOT NULL,
  attributes  jsonb NOT NULL DEFAULT '{}'::jsonb
                CHECK (jsonb_typeof(attributes) = 'object' AND pg_column_size(attributes) <= 16384),
  PRIMARY KEY (run_id, seq, ts)
) PARTITION BY RANGE (ts);
COMMENT ON TABLE ops.log_event IS
  'Log lines: event_code <step>.<object>.<verb> (catalogue in docs/DB_DDL_PLANNING.md §11.3). Never a key, a full prompt, a D-051 value or a person''s name (§11.5); payloads over 16 KB go to ops.blob, referenced by hash. Every level is kept during the event (D-065). Append-only.';

CREATE TABLE IF NOT EXISTS ops.log_event_default PARTITION OF ops.log_event DEFAULT;

CREATE INDEX IF NOT EXISTS log_event_ts_brin ON ops.log_event USING brin (ts);
CREATE INDEX IF NOT EXISTS log_event_run_ix ON ops.log_event (run_id, ts);
CREATE INDEX IF NOT EXISTS log_event_ruling_ix ON ops.log_event (ruling_id, ts);
CREATE INDEX IF NOT EXISTS log_event_span_ix ON ops.log_event (span_id);
CREATE INDEX IF NOT EXISTS log_event_code_ix ON ops.log_event (event_code);

-- Creates one partition per day in [p_from, p_to]. Call it at deploy and at run start, before the run
-- writes: a day already holding rows in the DEFAULT partition cannot get its own partition.
CREATE OR REPLACE FUNCTION ops.ensure_log_partitions(p_from date, p_to date) RETURNS integer
  LANGUAGE plpgsql AS $$
DECLARE
  d       date := p_from;
  created integer := 0;
  pname   text;
BEGIN
  IF p_to < p_from THEN
    RAISE EXCEPTION 'ensure_log_partitions: % is before %', p_to, p_from;
  END IF;
  WHILE d <= p_to LOOP
    pname := 'log_event_p' || to_char(d, 'YYYYMMDD');
    IF to_regclass('ops.' || pname) IS NULL THEN
      EXECUTE format('CREATE TABLE ops.%I PARTITION OF ops.log_event FOR VALUES FROM (%L) TO (%L)',
                     pname, d::timestamp AT TIME ZONE 'UTC', (d + 1)::timestamp AT TIME ZONE 'UTC');  -- UTC days
      created := created + 1;
    END IF;
    d := d + 1;
  END LOOP;
  RETURN created;
END $$;
COMMENT ON FUNCTION ops.ensure_log_partitions(date, date) IS 'One ops.log_event partition per day in the range; returns the number created.';

DO $$ BEGIN
  PERFORM ops.ensure_log_partitions((now() AT TIME ZONE 'UTC')::date - 1, (now() AT TIME ZONE 'UTC')::date + 2);
END $$;
