-- ============================================================================
-- File: 85_cross_fks.sql (foreign keys that point to a later file)
-- Date: 2026-11-28
-- Description: ops tables are created before corpus/triage/gold/summ; their foreign keys to those schemas
--              are added here, once (ops.ensure_constraint is idempotent).
-- SGBD: PostgreSQL 17
-- Doc: docs/DB_DDL_PLANNING.md §15.1
-- ============================================================================
-- PREREQUISITE: 50_summ.sql
-- ============================================================================

DO $$ BEGIN
  PERFORM ops.ensure_constraint('ops.model', 'model_source_snapshot_fk',
  'FOREIGN KEY (source_snapshot_id) REFERENCES ops.source_snapshot(snapshot_id) ON DELETE RESTRICT');
  PERFORM ops.ensure_constraint('ops.span', 'span_ruling_fk',
  'FOREIGN KEY (ruling_id) REFERENCES corpus.ruling(ruling_id) ON DELETE RESTRICT');
  PERFORM ops.ensure_constraint('ops.work_item', 'work_item_ruling_fk',
  'FOREIGN KEY (ruling_id) REFERENCES corpus.ruling(ruling_id) ON DELETE RESTRICT');
  PERFORM ops.ensure_constraint('ops.user_request', 'user_request_ruling_fk',
  'FOREIGN KEY (ruling_id) REFERENCES corpus.ruling(ruling_id) ON DELETE RESTRICT');
  PERFORM ops.ensure_constraint('ops.user_request', 'user_request_preset_fk',
  'FOREIGN KEY (preset_code) REFERENCES summ.preset(preset_code) ON DELETE RESTRICT');
  PERFORM ops.ensure_constraint('ops.llm_call', 'llm_call_ruling_fk',
  'FOREIGN KEY (ruling_id) REFERENCES corpus.ruling(ruling_id) ON DELETE RESTRICT');
  PERFORM ops.ensure_constraint('ops.llm_call_example', 'llm_call_example_ruling_fk',
  'FOREIGN KEY (example_ruling_id) REFERENCES corpus.ruling(ruling_id) ON DELETE RESTRICT');
  PERFORM ops.ensure_constraint('ops.llm_call_example', 'llm_call_example_suva_summary_fk',
  'FOREIGN KEY (suva_summary_id) REFERENCES gold.suva_summary(suva_summary_id) ON DELETE RESTRICT');
  PERFORM ops.ensure_constraint('ops.release', 'release_ranking_fk',
  'FOREIGN KEY (ranking_id) REFERENCES triage.ranking(ranking_id) ON DELETE RESTRICT');
  PERFORM ops.ensure_constraint('gold.expert_review', 'expert_review_summary_version_fk',
  'FOREIGN KEY (summary_version_id) REFERENCES summ.summary_version(summary_version_id) ON DELETE RESTRICT');
END $$;
