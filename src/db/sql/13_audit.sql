-- ============================================================================
-- File: 13_audit.sql (change log)
-- Date: 2026-11-28
-- Description: Every change to a mutable row (registry status, presets, anchors, current-version switches,
--              releases, work status, runs closing, expert reviews) is written here with the actor and the
--              run of the session (SET app.actor / app.run_id). Append-only.
-- SGBD: PostgreSQL 17
-- Doc: docs/DB_DDL_PLANNING.md §14
-- ============================================================================
-- PREREQUISITE: 00_extensions.sql
-- ============================================================================

CREATE TABLE IF NOT EXISTS audit.change_log (
  change_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  occurred_at   timestamptz NOT NULL DEFAULT now(),
  table_name    text NOT NULL,
  action        text NOT NULL CHECK (action IN ('INSERT', 'UPDATE', 'DELETE')),
  row_pk        jsonb NOT NULL,
  actor         text,
  run_id        uuid,
  db_role       text NOT NULL DEFAULT current_user,
  old_row       jsonb,
  new_row       jsonb
);
CREATE INDEX IF NOT EXISTS change_log_table_ix ON audit.change_log (table_name, occurred_at DESC);
COMMENT ON TABLE audit.change_log IS 'Change log of mutable rows. actor and run_id come from the session settings app.actor and app.run_id. Append-only.';

-- AFTER trigger. TG_ARGV = the primary-key columns of the audited table.
CREATE OR REPLACE FUNCTION audit.log_change() RETURNS trigger
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
  src jsonb := CASE WHEN TG_OP = 'DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
  pk  jsonb := '{}'::jsonb;
  i   int;
BEGIN
  FOR i IN 0 .. TG_NARGS - 1 LOOP
    pk := pk || jsonb_build_object(TG_ARGV[i], src -> TG_ARGV[i]);
  END LOOP;
  INSERT INTO audit.change_log (table_name, action, row_pk, actor, run_id, old_row, new_row)
  VALUES (TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME, TG_OP, pk, ops.current_actor(), ops.current_run_id(),
          CASE WHEN TG_OP <> 'INSERT' THEN to_jsonb(OLD) END,
          CASE WHEN TG_OP <> 'DELETE' THEN to_jsonb(NEW) END);
  RETURN NULL;
END $$;
