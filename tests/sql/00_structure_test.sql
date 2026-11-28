-- Structure: table and ENUM counts, comments everywhere, a guard on every table, no personal-data column,
-- generated columns, deterministic ids equal to Python's uuid.uuid5. docs/DB_DDL_PLANNING.md §6, §15.
BEGIN;
\ir _fixtures.sql

DO $$
DECLARE
  n int;
  missing text;
BEGIN
  SELECT count(*) INTO n
  FROM pg_class c JOIN pg_namespace s ON s.oid = c.relnamespace
  WHERE s.nspname IN ('ops', 'corpus', 'triage', 'gold', 'summ', 'audit') AND c.relkind IN ('r', 'p') AND NOT c.relispartition;
  ASSERT n = 58, format('expected 58 tables, found %s', n);

  SELECT count(*) INTO n FROM pg_type t JOIN pg_namespace s ON s.oid = t.typnamespace WHERE s.nspname = 'ops' AND t.typtype = 'e';
  ASSERT n = 45, format('expected 45 ENUMs, found %s', n);

  SELECT string_agg(s.nspname || '.' || c.relname, ', ') INTO missing
  FROM pg_class c JOIN pg_namespace s ON s.oid = c.relnamespace
  WHERE s.nspname IN ('ops', 'corpus', 'triage', 'gold', 'summ', 'audit') AND c.relkind IN ('r', 'p', 'v')
    AND NOT c.relispartition AND obj_description(c.oid, 'pg_class') IS NULL;
  ASSERT missing IS NULL, format('tables or views without a comment: %s', missing);

  SELECT string_agg(s.nspname || '.' || c.relname, ', ') INTO missing
  FROM pg_class c JOIN pg_namespace s ON s.oid = c.relnamespace
  WHERE s.nspname IN ('ops', 'corpus', 'triage', 'gold', 'summ', 'audit') AND c.relkind IN ('r', 'p') AND NOT c.relispartition
    AND NOT EXISTS (SELECT 1 FROM pg_trigger tg WHERE tg.tgrelid = c.oid AND tg.tgname = 't10_guard');
  ASSERT missing IS NULL, format('tables without an append-only guard: %s', missing);

  SELECT string_agg(table_schema || '.' || table_name || '.' || column_name, ', ') INTO missing
  FROM information_schema.columns
  WHERE table_schema IN ('ops', 'corpus', 'triage', 'gold', 'summ', 'audit')
    AND column_name ~* '(^judges?$|clerk|author|staff|intranet|sharepoint|first_name|last_name|surname)';
  ASSERT missing IS NULL, format('personal-data columns are forbidden (D-038, D-051): %s', missing);

  ASSERT (SELECT array_agg(e ORDER BY e) FROM unnest(enum_range(NULL::ops.in_suva_scope)) e)
         = ARRAY['in_scope', 'out_of_scope', 'potentially']::ops.in_suva_scope[], 'in_suva_scope values (D-063)';
  ASSERT 'layer1_filter'::ops.pipeline_step < 'ranking'::ops.pipeline_step, 'pipeline_step must follow the pipeline order';

  -- uuid5 = Python uuid.uuid5(UUID('1dd0895a-ba8b-499e-985e-5f92eed68ad3'), 'bger|8C_802/2023|2026-03-27')
  ASSERT ops.uuid5('bger|8C_802/2023|2026-03-27') = '9192a7de-7fa2-5920-b935-aa171fce030e', 'uuid5 differs from Python';
  ASSERT pg_temp.rid('8C_493/2025') = ops.uuid5('bger|8C_493/2025|2026-04-02'), 'ruling id must be uuid5 of its key';

  ASSERT (SELECT court || '|' || register_letter || '|' || filing_year || '|' || quarter_by_decision
          FROM corpus.ruling WHERE docket = '8C_493/2025') = '8C|C|2025|2026Q2', 'generated ruling columns';
  ASSERT (SELECT version_label FROM ops.component_version WHERE component_version_id = pg_temp.cv('layer2_judge')) = 'V1.0.0',
         'version label V<major>.<minor>.<patch>';
  ASSERT (SELECT count(*) FROM ops.reason_code) >= 40, 'reason-code vocabulary seeded';
  ASSERT (SELECT count(*) FROM summ.perspective_anchor) = 5, 'five perspective anchors (0, 3, 5, 7, 10)';
  ASSERT (SELECT perspective FROM summ.preset WHERE is_mandatory) = 5, 'suva_house is the mandatory anchor-5 preset (D-068)';
END $$;

ROLLBACK;
