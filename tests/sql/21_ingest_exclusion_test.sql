-- Ingest exclusion ledger (F-04, G5): every row of a source file not loaded has a reason; a source row of a
-- snapshot is either loaded (ruling_source_ref) or excluded, never both; exclusions are append-only, decided by
-- an ingest version, with an ingest reason, against a snapshot of the row's kind of file; corpus.v_ingest_closure
-- proves row_count = refs + exclusions for every snapshot, a second revision of the file included.
BEGIN;
\ir _fixtures.sql

INSERT INTO ops.component_version (step, name, v_major, v_minor, v_patch, config_schema_id, config, config_sha256, code_path, code_sha256,
                                  status, bump_kind, changelog, decision_ref, validation_ref)
VALUES ('ingest', 'fixture ingest', 1, 0, 0, (SELECT json_schema_id FROM ops.json_schema WHERE schema_code = 'test.step_config'), '{}',
        repeat('4', 64), 'src/fixture.py', repeat('5', 64), 'active', 'initial', 'fixture', 'D-072', 'expected/ingest/V1.0.0.json');

-- a file of 6 rows: 3 loaded (2 base rows and 1 twin), 3 excluded (one without a usable id, kept by its row index)
INSERT INTO ops.source_snapshot (snapshot_id, source, revision, uri, file_sha256, row_count, retrieved_at)
VALUES ('00000000-0000-4000-8000-0000000000a3', 'hf_bger', 'fixture-closure', 'hf://datasets/x/bger.parquet', repeat('e', 64), 6, now());
INSERT INTO corpus.ruling_source_ref (source, external_id, ruling_id, snapshot_id, is_twin) VALUES
  ('hf_decision_id', 'bger_8C_493_2025', pg_temp.rid('8C_493/2025'), '00000000-0000-4000-8000-0000000000a3', false),
  ('hf_decision_id', 'bger_8C_493_2025-D20260402', pg_temp.rid('8C_493/2025'), '00000000-0000-4000-8000-0000000000a3', true),
  ('hf_decision_id', 'bger_8C_307_2025', pg_temp.rid('8C_307/2025'), '00000000-0000-4000-8000-0000000000a3', false);
INSERT INTO corpus.ingest_exclusion (snapshot_id, source, external_id, docket_raw, decision_date, reason_code, detail, component_version_id, run_id)
VALUES
  ('00000000-0000-4000-8000-0000000000a3', 'hf_decision_id', 'bger_5A_1_2020', '5A_1/2020', '2020-03-02', 'OUT_OF_WINDOW',
   '{"decision_date": "2020-03-02", "publication_date": null}', pg_temp.cv('ingest'), '00000000-0000-4000-8000-000000000001'),
  ('00000000-0000-4000-8000-0000000000a3', 'hf_decision_id', 'bger_8C_9_2025-D20260105', '8C_9/2025', '2026-01-05', 'ING_TWIN_SAME_DATE',
   '{"base_id": "bger_8C_9_2025"}', pg_temp.cv('ingest'), '00000000-0000-4000-8000-000000000001'),
  ('00000000-0000-4000-8000-0000000000a3', 'hf_decision_id', 'row:5', 'Ohne Nummer', NULL, 'ING_DECISION_DATE_MISSING',
   '{}', pg_temp.cv('ingest'), '00000000-0000-4000-8000-000000000001');

DO $$
DECLARE
  c corpus.v_ingest_closure%ROWTYPE;
BEGIN
  SELECT * INTO c FROM corpus.v_ingest_closure WHERE snapshot_id = '00000000-0000-4000-8000-0000000000a3';
  ASSERT (c.row_count, c.loaded_refs, c.base_refs, c.twin_refs, c.exclusions, c.exclusions_by_row_index, c.unaccounted_rows, c.closure_ok)
         = (6::bigint, 3::bigint, 2::bigint, 1::bigint, 3::bigint, 1::bigint, 0::bigint, true), format('closure: %s', to_jsonb(c));
  ASSERT c.exclusions_by_reason = '{"ING_DECISION_DATE_MISSING": 1, "ING_TWIN_SAME_DATE": 1, "OUT_OF_WINDOW": 1}', format('by reason: %s', c.exclusions_by_reason);
  ASSERT NOT EXISTS (SELECT 1 FROM corpus.v_ingest_closure WHERE snapshot_id = '00000000-0000-4000-8000-0000000000a1'),
         'a snapshot without refs or exclusions is not listed';
END $$;

-- a row lost without a reason breaks the closure; a row counted twice too
SAVEPOINT closure;
INSERT INTO ops.source_snapshot (snapshot_id, source, revision, uri, file_sha256, row_count, retrieved_at)
VALUES ('00000000-0000-4000-8000-0000000000a4', 'hf_bger', 'fixture-lossy', 'hf://datasets/x/bger.parquet', repeat('c', 64), 4, now());
INSERT INTO corpus.ingest_exclusion (snapshot_id, source, external_id, reason_code, component_version_id, run_id)
VALUES ('00000000-0000-4000-8000-0000000000a4', 'hf_decision_id', 'bger_5A_2_2020', 'OUT_OF_WINDOW', pg_temp.cv('ingest'), '00000000-0000-4000-8000-000000000001');
INSERT INTO corpus.ingest_exclusion (snapshot_id, source, external_id, reason_code, component_version_id, run_id)
VALUES ('00000000-0000-4000-8000-0000000000a3', 'hf_decision_id', 'bger_5A_3_2020', 'OUT_OF_WINDOW', pg_temp.cv('ingest'), '00000000-0000-4000-8000-000000000001');
DO $$ BEGIN
  ASSERT (SELECT unaccounted_rows || '|' || closure_ok FROM corpus.v_ingest_closure WHERE snapshot_id = '00000000-0000-4000-8000-0000000000a4') = '3|false',
         'three rows of the lossy file have no reason';
  ASSERT (SELECT unaccounted_rows || '|' || closure_ok FROM corpus.v_ingest_closure WHERE snapshot_id = '00000000-0000-4000-8000-0000000000a3') = '-1|false',
         'one more row accounted for than the file holds';
END $$;
ROLLBACK TO SAVEPOINT closure;

-- exclusivity, both ways (per snapshot)
SELECT pg_temp.expect_error($q$
  INSERT INTO corpus.ingest_exclusion (snapshot_id, source, external_id, reason_code, component_version_id, run_id)
  VALUES ('00000000-0000-4000-8000-0000000000a3', 'hf_decision_id', 'bger_8C_307_2025', 'OUT_OF_WINDOW', pg_temp.cv('ingest'),
          '00000000-0000-4000-8000-000000000001')$q$, 'is loaded \(corpus.ruling_source_ref\), it cannot also be excluded');
SELECT pg_temp.expect_error($q$
  INSERT INTO corpus.ruling_source_ref (source, external_id, ruling_id, snapshot_id, is_twin)
  VALUES ('hf_decision_id', 'bger_5A_1_2020', pg_temp.rid('8C_199/2026'), '00000000-0000-4000-8000-0000000000a3', false)$q$,
  'is excluded \(corpus.ingest_exclusion\), it cannot also be loaded');
-- another snapshot (another file revision) may exclude a row this one loaded
INSERT INTO corpus.ingest_exclusion (snapshot_id, source, external_id, reason_code, component_version_id, run_id)
VALUES ('00000000-0000-4000-8000-0000000000a1', 'hf_decision_id', 'bger_8C_307_2025', 'OUT_OF_WINDOW', pg_temp.cv('ingest'), '00000000-0000-4000-8000-000000000001');

-- a second revision of the file closes on its own: the rows the first revision loaded are loaded again, as source
-- references of the new snapshot (one reference per snapshot and source row)
INSERT INTO ops.source_snapshot (snapshot_id, source, revision, uri, file_sha256, row_count, retrieved_at)
VALUES ('00000000-0000-4000-8000-0000000000b2', 'hf_bger', 'fixture-closure-rev-b', 'hf://datasets/x/bger.parquet', repeat('f', 64), 4, now());
INSERT INTO corpus.ruling_source_ref (source, external_id, ruling_id, snapshot_id, is_twin) VALUES
  ('hf_decision_id', 'bger_8C_493_2025', pg_temp.rid('8C_493/2025'), '00000000-0000-4000-8000-0000000000b2', false),
  ('hf_decision_id', 'bger_8C_493_2025-D20260402', pg_temp.rid('8C_493/2025'), '00000000-0000-4000-8000-0000000000b2', true),
  ('hf_decision_id', 'bger_8C_199_2026', pg_temp.rid('8C_199/2026'), '00000000-0000-4000-8000-0000000000b2', false);
INSERT INTO corpus.ingest_exclusion (snapshot_id, source, external_id, docket_raw, decision_date, reason_code, component_version_id, run_id)
VALUES ('00000000-0000-4000-8000-0000000000b2', 'hf_decision_id', 'bger_5A_1_2020', '5A_1/2020', '2020-03-02', 'OUT_OF_WINDOW', pg_temp.cv('ingest'),
        '00000000-0000-4000-8000-000000000001');
-- the same row loaded twice in one snapshot is still one reference (the loader's ON CONFLICT DO NOTHING)
INSERT INTO corpus.ruling_source_ref (source, external_id, ruling_id, snapshot_id, is_twin)
VALUES ('hf_decision_id', 'bger_8C_493_2025', pg_temp.rid('8C_493/2025'), '00000000-0000-4000-8000-0000000000b2', false) ON CONFLICT DO NOTHING;
DO $$ BEGIN
  ASSERT (SELECT loaded_refs || '|' || exclusions || '|' || unaccounted_rows || '|' || closure_ok FROM corpus.v_ingest_closure
          WHERE snapshot_id = '00000000-0000-4000-8000-0000000000b2') = '3|1|0|true', 'the second revision closes';
  ASSERT (SELECT closure_ok FROM corpus.v_ingest_closure WHERE snapshot_id = '00000000-0000-4000-8000-0000000000a3'), 'the first still closes';
  ASSERT (SELECT count(*) FROM corpus.ruling_source_ref WHERE source = 'hf_decision_id' AND external_id = 'bger_8C_493_2025') = 2,
         'one reference per snapshot';
END $$;
-- within the new snapshot a loaded row still cannot also be excluded (here: an in-window row given a false reason)
SELECT pg_temp.expect_error($q$
  INSERT INTO corpus.ingest_exclusion (snapshot_id, source, external_id, docket_raw, decision_date, reason_code, component_version_id, run_id)
  VALUES ('00000000-0000-4000-8000-0000000000b2', 'hf_decision_id', 'bger_8C_493_2025', '8C_493/2025', '2026-04-02', 'OUT_OF_WINDOW',
          pg_temp.cv('ingest'), '00000000-0000-4000-8000-000000000001')$q$, 'is loaded \(corpus.ruling_source_ref\), it cannot also be excluded');

-- an exclusion gives an ingest reason (or OUT_OF_WINDOW), and its source row belongs to the snapshot's kind of file
SELECT pg_temp.expect_error($q$
  INSERT INTO corpus.ingest_exclusion (snapshot_id, source, external_id, reason_code, component_version_id, run_id)
  VALUES ('00000000-0000-4000-8000-0000000000a3', 'hf_decision_id', 'bger_5A_9_2020', 'RANK_BELOW_THRESHOLD', pg_temp.cv('ingest'),
          '00000000-0000-4000-8000-000000000001')$q$, 'reason RANK_BELOW_THRESHOLD is not an ingest reason');
INSERT INTO ops.source_snapshot (snapshot_id, source, revision, uri, file_sha256, row_count, retrieved_at)
VALUES ('00000000-0000-4000-8000-0000000000b3', 'judgements_workbook', NULL, 'judgements/x.xlsx', repeat('9', 64), 6, now());
SELECT pg_temp.expect_error($q$
  INSERT INTO corpus.ingest_exclusion (snapshot_id, source, external_id, reason_code, component_version_id, run_id)
  VALUES ('00000000-0000-4000-8000-0000000000b3', 'hf_decision_id', 'bger_5A_9_2020', 'OUT_OF_WINDOW', pg_temp.cv('ingest'),
          '00000000-0000-4000-8000-000000000001')$q$, 'a hf_decision_id row cannot come from a judgements_workbook snapshot');
SELECT pg_temp.expect_error($q$
  INSERT INTO corpus.ingest_exclusion (snapshot_id, source, external_id, reason_code, component_version_id, run_id)
  VALUES ('00000000-0000-4000-8000-0000000000a3', 'some_new_source', 'x1', 'OUT_OF_WINDOW', pg_temp.cv('ingest'),
          '00000000-0000-4000-8000-000000000001')$q$, 'ingest_exclusion_source_chk');

-- one row per source row; decided by an ingest version; a known reason; identity values only
SELECT pg_temp.expect_error($q$
  INSERT INTO corpus.ingest_exclusion (snapshot_id, source, external_id, reason_code, component_version_id, run_id)
  VALUES ('00000000-0000-4000-8000-0000000000a3', 'hf_decision_id', 'bger_5A_1_2020', 'ING_DOCKET_MALFORMED', pg_temp.cv('ingest'),
          '00000000-0000-4000-8000-000000000001')$q$, 'duplicate key');
SELECT pg_temp.expect_error($q$
  INSERT INTO corpus.ingest_exclusion (snapshot_id, source, external_id, reason_code, component_version_id, run_id)
  VALUES ('00000000-0000-4000-8000-0000000000a3', 'hf_decision_id', 'bger_5A_4_2020', 'OUT_OF_WINDOW', pg_temp.cv('layer1_filter'),
          '00000000-0000-4000-8000-000000000001')$q$, 'not an ingest version');
SELECT pg_temp.expect_error($q$
  INSERT INTO corpus.ingest_exclusion (snapshot_id, source, external_id, reason_code, component_version_id, run_id)
  VALUES ('00000000-0000-4000-8000-0000000000a3', 'hf_decision_id', 'bger_5A_4_2020', 'NO_SUCH_REASON', pg_temp.cv('ingest'),
          '00000000-0000-4000-8000-000000000001')$q$, 'foreign key');
SELECT pg_temp.expect_error($q$
  INSERT INTO corpus.ingest_exclusion (snapshot_id, source, external_id, reason_code, component_version_id, run_id)
  VALUES ('00000000-0000-4000-8000-0000000000a3', 'HF Decision', 'bger_5A_4_2020', 'OUT_OF_WINDOW', pg_temp.cv('ingest'),
          '00000000-0000-4000-8000-000000000001')$q$, 'check constraint');
SELECT pg_temp.expect_error($q$
  INSERT INTO corpus.ingest_exclusion (snapshot_id, source, external_id, reason_code, detail, component_version_id, run_id)
  VALUES ('00000000-0000-4000-8000-0000000000a3', 'hf_decision_id', 'bger_5A_4_2020', 'OUT_OF_WINDOW', '[]', pg_temp.cv('ingest'),
          '00000000-0000-4000-8000-000000000001')$q$, 'check constraint');

-- append-only
SELECT pg_temp.expect_error($q$UPDATE corpus.ingest_exclusion SET reason_code = 'ING_DOCKET_MALFORMED' WHERE external_id = 'bger_5A_1_2020'$q$,
  'only .* may change');
SELECT pg_temp.expect_error($q$DELETE FROM corpus.ingest_exclusion WHERE external_id = 'row:5'$q$, 'append-only');

ROLLBACK;
