-- Summaries (D-067, D-068, D-069): German + French pair checked at commit, version numbering, a pipeline text
-- has its own LLM call, citations from the source segmentation and citable only, expert edits as new current
-- versions, verifier checks bound to verify rules, one mandatory preset, anchors with rubrics, mandatory gaps.
BEGIN;
\ir _fixtures.sql

-- the fixture's version is a complete pair
SET CONSTRAINTS ALL IMMEDIATE;
SET CONSTRAINTS ALL DEFERRED;

-- a version with only a German text fails at commit
SAVEPOINT pair;
INSERT INTO summ.summary_version (summary_version_id, summary_id, version_no, origin, parent_version_id, preset_version_id, component_version_id,
                                  source_segmentation_id, creator_kind, creator_run_id, mode)
SELECT '00000000-0000-4000-8000-000000000702', summary_id, NULL, 'regenerated', '00000000-0000-4000-8000-000000000701', preset_version_id,
       component_version_id, source_segmentation_id, 'pipeline', '00000000-0000-4000-8000-000000000001', 'REPLAY'
FROM summ.summary_version WHERE summary_version_id = '00000000-0000-4000-8000-000000000701';
DO $$ BEGIN
  ASSERT (SELECT version_no FROM summ.summary_version WHERE summary_version_id = '00000000-0000-4000-8000-000000000702') = 2, 'version_no = max + 1';
END $$;
INSERT INTO summ.summary_text (summary_version_id, language, title_line, body, word_count, paragraph_count, llm_call_id)
VALUES ('00000000-0000-4000-8000-000000000702', 'de', 'BGer-Urteil 8C_493/2025 vom 2. April 2026', 'Nur Deutsch.', 2, 1, '00000000-0000-4000-8000-000000000904');
SELECT pg_temp.expect_error('SET CONSTRAINTS ALL IMMEDIATE', 'exactly one German and one French');
ROLLBACK TO SAVEPOINT pair;

-- a pipeline text needs its own LLM call (written from the source, D-014)
SELECT pg_temp.expect_error($q$
  INSERT INTO summ.summary_text (summary_version_id, language, title_line, body, word_count, paragraph_count)
  VALUES ('00000000-0000-4000-8000-000000000701', 'it', 'x', 'x', 1, 1)$q$, 'check constraint|own LLM call');

-- citations: only considerations of the source segmentation, only numbered ones (G1)
SELECT pg_temp.expect_error($q$
  INSERT INTO summ.claim_citation (claim_id, consideration_id) VALUES ('00000000-0000-4000-8000-000000000721', pg_temp.cons('8C_307/2025', 1))$q$,
  'source segmentation');
SELECT pg_temp.expect_error($q$
  INSERT INTO summ.claim_citation (claim_id, consideration_id) VALUES ('00000000-0000-4000-8000-000000000721', pg_temp.cons('8C_493/2025', 4))$q$,
  'unnumbered');
SELECT pg_temp.expect_error($q$UPDATE summ.summary_text SET body = 'edited in place' WHERE summary_text_id = '00000000-0000-4000-8000-000000000711'$q$,
  'only .* may change');

-- verifier checks are verify rules of kind check
SELECT pg_temp.expect_error($q$
  INSERT INTO summ.verification_check (target_kind, claim_id, rule_id, status, run_id)
  VALUES ('claim', '00000000-0000-4000-8000-000000000721', pg_temp.rule('L1_DROP_NO_RULE'), 'pass', '00000000-0000-4000-8000-000000000001')$q$, 'verify check rule');
INSERT INTO summ.verification_check (target_kind, claim_id, rule_id, status, run_id)
VALUES ('claim', '00000000-0000-4000-8000-000000000721', pg_temp.rule('V1_IDS_IN_SET'), 'pass', '00000000-0000-4000-8000-000000000001');

-- expert edit of the French text: version 2, current, German copied unchanged, still a pair
SET LOCAL app.actor = 'expert-1';
SELECT summ.create_expert_version(
  '00000000-0000-4000-8000-000000000701', 'fr', 'Arrêt du TF 8C_493/2025 du 2 avril 2026', 'Texte corrigé par l''experte.',
  jsonb_build_array(jsonb_build_object('paragraph_no', 1, 'section', 'law', 'text', 'Texte corrigé par l''experte.',
                                       'cites', jsonb_build_array(pg_temp.cons('8C_493/2025', 1)),
                                       'edited_from_claim_id', '00000000-0000-4000-8000-000000000722')));
SET CONSTRAINTS ALL IMMEDIATE;
DO $$ BEGIN
  ASSERT (SELECT v.version_no || '|' || v.origin || '|' || v.creator_actor FROM summ.v_summary_current sc
          JOIN summ.summary_version v USING (summary_version_id) WHERE sc.ruling_id = pg_temp.rid('8C_493/2025')) = '2|expert_edit|expert-1',
         'the expert version is current';
  ASSERT (SELECT is_current FROM summ.summary_version WHERE summary_version_id = '00000000-0000-4000-8000-000000000701') = false, 'v1 no longer current';
  ASSERT (SELECT body_de FROM summ.v_summary_current WHERE ruling_id = pg_temp.rid('8C_493/2025')) = 'Synthetischer Satz (E. 1).', 'German copied unchanged';
  ASSERT (SELECT body_fr FROM summ.v_summary_current WHERE ruling_id = pg_temp.rid('8C_493/2025')) = 'Texte corrigé par l''experte.', 'French edited';
  ASSERT (SELECT count(*) FROM audit.change_log WHERE table_name = 'summ.summary_version' AND action = 'UPDATE' AND actor = 'expert-1') = 2,
         'the current switch is audited';
END $$;

-- presets: one mandatory; an anchor exists only with its rubric to become active; perspective must be an anchor
SELECT pg_temp.expect_error($q$
  INSERT INTO summ.preset (preset_code, name_de, name_fr, perspective, style, is_mandatory) VALUES ('other', 'x', 'x', 5, 'narrative', true)$q$, 'duplicate key');
SELECT pg_temp.expect_error($q$
  INSERT INTO summ.preset (preset_code, name_de, name_fr, perspective, style) VALUES ('p4', 'x', 'x', 4, 'narrative')$q$, 'foreign key');
SELECT pg_temp.expect_error($q$UPDATE summ.perspective_anchor SET status = 'active' WHERE perspective = 0$q$, 'rubric_chk');
INSERT INTO summ.preset (preset_code, name_de, name_fr, perspective, style) VALUES ('insured_view', 'Sicht der versicherten Person', 'Point de vue de l''assuré', 0, 'narrative');
SELECT pg_temp.expect_error($q$UPDATE summ.preset SET perspective = 10 WHERE preset_code = 'insured_view'$q$, 'only .* may change');

-- mandatory gaps follow the default pipeline's in_scope rulings of a release
DO $$ BEGIN
  ASSERT (SELECT count(*) FROM summ.mandatory_summary_gaps('00000000-0000-4000-8000-000000000801')) = 0, 'no gap';
END $$;
UPDATE summ.summary_version SET quality_status = 'rejected' WHERE is_current AND summary_id = (SELECT summary_id FROM summ.summary LIMIT 1);
DO $$ BEGIN
  ASSERT (SELECT string_agg(docket, ',') FROM summ.mandatory_summary_gaps('00000000-0000-4000-8000-000000000801')) = '8C_493/2025',
         'a rejected current version leaves a gap';
END $$;

ROLLBACK;
