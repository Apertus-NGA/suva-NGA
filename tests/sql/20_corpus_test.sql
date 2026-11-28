-- Corpus (D-062, D-070): docket format, text hash, one primary text and segmentation, publication quality,
-- considerations (cid, citable, tree), twins as source references, frozen populations, append-only rows.
BEGIN;
\ir _fixtures.sql

SELECT pg_temp.expect_error($q$
  INSERT INTO corpus.ruling (docket, decision_date, language, bger_url, origin, created_by_run_id)
  VALUES ('8C-493/2025', '2026-04-02', 'de', 'https://x', 'base_dataset', '00000000-0000-4000-8000-000000000001')$q$, 'check constraint');
SELECT pg_temp.expect_error($q$UPDATE corpus.ruling SET gegenstand = 'x' WHERE docket = '8C_493/2025'$q$, 'only .* may change');

-- text: hash checked, one primary per ruling, a second text is a new row
SELECT pg_temp.expect_error($q$
  INSERT INTO corpus.ruling_text (ruling_id, source, content, content_sha256, snapshot_id)
  VALUES (pg_temp.rid('8C_493/2025'), 'bger', 'other text', repeat('0', 64), '00000000-0000-4000-8000-0000000000a1')$q$, 'not the SHA-256');
INSERT INTO corpus.ruling_text (ruling_id, source, content, content_sha256, snapshot_id)
VALUES (pg_temp.rid('8C_493/2025'), 'bger', 'Fidelity sample.', encode(sha256(convert_to('Fidelity sample.', 'UTF8')), 'hex'), '00000000-0000-4000-8000-0000000000a1');
SELECT pg_temp.expect_error($q$UPDATE corpus.ruling_text SET is_primary = true WHERE source = 'bger'$q$, 'duplicate key');
-- a blank text is no text, whatever whitespace it holds (the engine's text.strip() == '' is text_absent)
SELECT pg_temp.expect_error($q$
  INSERT INTO corpus.ruling_text (ruling_id, source, content, content_sha256, snapshot_id)
  VALUES (pg_temp.rid('8C_307/2025'), 'bger', E'\n\t ', encode(sha256(convert_to(E'\n\t ', 'UTF8')), 'hex'), '00000000-0000-4000-8000-0000000000a1')$q$, 'ruling_text_content_visible_chk');
SELECT pg_temp.expect_error($q$
  INSERT INTO corpus.ruling_text (ruling_id, source, content, content_sha256, snapshot_id)
  VALUES (pg_temp.rid('8C_307/2025'), 'bger', E'\u00a0\u3000\u0085', encode(sha256(convert_to(E'\u00a0\u3000\u0085', 'UTF8')), 'hex'), '00000000-0000-4000-8000-0000000000a1')$q$, 'ruling_text_content_visible_chk');

-- publication: a first-seen date is approximate, never exact; quarter_by_publication only from exact dates
SELECT pg_temp.expect_error($q$
  INSERT INTO corpus.publication_observation (ruling_id, source, quality, observed_date, snapshot_id)
  VALUES (pg_temp.rid('8C_307/2025'), 'hf_first_seen', 'exact', '2026-05-02', '00000000-0000-4000-8000-0000000000a1')$q$, 'quality_chk');
INSERT INTO corpus.publication_observation (ruling_id, source, quality, observed_date, snapshot_id) VALUES
  (pg_temp.rid('8C_493/2025'), 'hf_poller', 'exact', '2026-05-20', '00000000-0000-4000-8000-0000000000a1'),
  (pg_temp.rid('8C_307/2025'), 'hf_first_seen', 'approx_first_seen', '2026-05-02', '00000000-0000-4000-8000-0000000000a1');
DO $$ BEGIN
  ASSERT (SELECT publication_quality || '|' || quarter_by_publication FROM corpus.v_ruling WHERE docket = '8C_493/2025') = 'exact|2026Q2', 'exact publication';
  ASSERT (SELECT publication_quality FROM corpus.v_ruling WHERE docket = '8C_307/2025') = 'approx_first_seen', 'approximate publication';
  ASSERT (SELECT quarter_by_publication FROM corpus.v_ruling WHERE docket = '8C_307/2025') IS NULL, 'no quarter from an approximation (D-050)';
  ASSERT (SELECT publication_quality FROM corpus.v_ruling WHERE docket = '8C_199/2026') = 'unknown', 'unknown publication';
END $$;

-- twins are kept as source references of one ruling
INSERT INTO corpus.ruling_source_ref (source, external_id, ruling_id, snapshot_id, is_twin) VALUES
  ('hf_decision_id', 'bger_8C_493_2025', pg_temp.rid('8C_493/2025'), '00000000-0000-4000-8000-0000000000a1', false),
  ('hf_decision_id', 'bger_8C_493_2025-D20260402', pg_temp.rid('8C_493/2025'), '00000000-0000-4000-8000-0000000000a1', true);

-- segmentation: one primary per text, primary only when ok; a new splitter version is a new segmentation
INSERT INTO ops.component_version (step, name, v_major, v_minor, v_patch, config_schema_id, config, config_sha256, code_path, code_sha256, bump_kind, previous_version_id, changelog)
VALUES ('segment', 'own splitter', 1, 1, 0, (SELECT json_schema_id FROM ops.json_schema WHERE schema_code = 'test.step_config'), '{}', repeat('4', 64), 'x', repeat('5', 64),
        'minor', pg_temp.cv('segment'), 'own splitter on samples');
SELECT pg_temp.expect_error($q$
  INSERT INTO corpus.segmentation (text_id, component_version_id, method, status, consideration_count, is_primary, created_by_run_id)
  VALUES (pg_temp.text_of('8C_493/2025'), pg_temp.cv('segment', 1, 1), 'own_splitter', 'partial', 2, true, '00000000-0000-4000-8000-000000000001')$q$, 'primary_ok_chk');
INSERT INTO corpus.segmentation (text_id, component_version_id, method, status, consideration_count, created_by_run_id)
VALUES (pg_temp.text_of('8C_493/2025'), pg_temp.cv('segment', 1, 1), 'own_splitter', 'ok', 1, '00000000-0000-4000-8000-000000000001');
SELECT pg_temp.expect_error($q$
  UPDATE corpus.segmentation SET is_primary = true WHERE component_version_id = pg_temp.cv('segment', 1, 1)$q$, 'duplicate key');

-- considerations: cid, citable, unnumbered rule, parent in the same segmentation
DO $$ BEGIN
  ASSERT (SELECT cid FROM corpus.consideration WHERE consideration_id = pg_temp.cons('8C_493/2025', 2)) = 'c2', 'cid = c<ordinal>';
  ASSERT (SELECT is_citable FROM corpus.consideration WHERE consideration_id = pg_temp.cons('8C_493/2025', 4)) = false, 'e_number 0 is not citable';
END $$;
SELECT pg_temp.expect_error($q$
  INSERT INTO corpus.consideration (segmentation_id, ordinal, e_number, depth, content, content_sha256)
  VALUES (pg_temp.seg('8C_307/2025'), 9, '0', 1, 'x', encode(sha256(convert_to('x', 'UTF8')), 'hex'))$q$, 'unnumbered_chk');
SELECT pg_temp.expect_error($q$
  INSERT INTO corpus.consideration (segmentation_id, ordinal, e_number, depth, parent_consideration_id, content, content_sha256)
  VALUES ((SELECT segmentation_id FROM corpus.segmentation WHERE component_version_id = pg_temp.cv('segment', 1, 1)), 1, '1.1', 2,
          pg_temp.cons('8C_493/2025', 1), 'x', encode(sha256(convert_to('x', 'UTF8')), 'hex'))$q$, 'another segmentation');

-- frozen population: no new member, no change
UPDATE corpus.population SET manifest_sha256 = repeat('a', 64), frozen_at = now() WHERE code = 'fixture_2026Q2_union';
INSERT INTO corpus.ruling (docket, decision_date, language, bger_url, origin, created_by_run_id)
VALUES ('8C_1/2026', '2026-05-04', 'de', 'https://x', 'user_added', '00000000-0000-4000-8000-000000000001');
SELECT pg_temp.expect_error($q$
  INSERT INTO corpus.population_member (population_id, ruling_id, basis)
  VALUES ((SELECT population_id FROM corpus.population WHERE code = 'fixture_2026Q2_union'), pg_temp.rid('8C_1/2026'), 'decision_date')$q$, 'frozen');
SELECT pg_temp.expect_error($q$UPDATE corpus.population SET description = 'x' WHERE code = 'fixture_2026Q2_union'$q$, 'frozen');

ROLLBACK;
