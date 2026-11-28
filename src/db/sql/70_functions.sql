-- ============================================================================
-- File: 70_functions.sql (the only write paths for experts and the UI)
-- Date: 2026-11-28
-- Description: SECURITY DEFINER functions owned by suva_owner, with a pinned search_path. The API role
--              (suva_g_review) may EXECUTE them and write nothing else. Each refuses to run without
--              app.actor (a pseudonymous handle, G13).
-- SGBD: PostgreSQL 17
-- Doc: docs/DB_DDL_PLANNING.md §5, §12.2, §13.5, §15.6
-- ============================================================================
-- PREREQUISITE: 60_views.sql
-- ============================================================================

CREATE OR REPLACE FUNCTION ops.require_actor() RETURNS text
  LANGUAGE plpgsql STABLE SET search_path = pg_catalog, pg_temp AS $$
DECLARE
  a text := ops.current_actor();
BEGIN
  IF a IS NULL THEN
    RAISE EXCEPTION 'app.actor is not set: expert and UI writes need a pseudonymous handle (SET app.actor = ''...'')';
  END IF;
  RETURN a;
END $$;

-- "Add another judgement" (D-015) or "summarise this ruling under this preset".
CREATE OR REPLACE FUNCTION ops.submit_request(
  p_kind        ops.request_kind,
  p_docket      text DEFAULT NULL,
  p_bger_url    text DEFAULT NULL,
  p_ruling_id   uuid DEFAULT NULL,
  p_preset_code text DEFAULT NULL
) RETURNS uuid
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
  rid uuid;
BEGIN
  INSERT INTO ops.user_request (kind, docket, bger_url, ruling_id, preset_code, requested_by_actor)
  VALUES (p_kind, p_docket, p_bger_url, p_ruling_id, p_preset_code, ops.require_actor())
  RETURNING request_id INTO rid;
  RETURN rid;
END $$;
COMMENT ON FUNCTION ops.submit_request(ops.request_kind, text, text, uuid, text) IS 'UI request: add a judgement by docket or bger.ch link, or a summary of any ruling under any preset. The pipeline accepts it into a run.';

-- Expert review of a scope label (relevant | not_relevant on any label; correct | incorrect on in_scope or out_of_scope)
-- or of a summary version (validated | rejected); withdrawn takes back the review given in p_supersedes (D-093).
CREATE OR REPLACE FUNCTION gold.submit_review(
  p_target_kind  ops.review_target,
  p_target_id    uuid,
  p_verdict      ops.review_verdict,
  p_payload      jsonb DEFAULT '{}'::jsonb,
  p_comment      text DEFAULT NULL,
  p_supersedes   uuid DEFAULT NULL
) RETURNS uuid
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
  actor_handle text := ops.require_actor();
  schema_id    uuid;
  label        ops.in_suva_scope;
  rid          uuid;
BEGIN
  SELECT s.json_schema_id INTO schema_id
  FROM ops.json_schema s
  WHERE s.subject = 'review_payload'
    AND s.schema_code = CASE p_target_kind WHEN 'scope' THEN 'scope_review.payload' ELSE 'summary_review.payload' END
    AND s.status = 'active'
  ORDER BY s.v_major DESC, s.v_minor DESC, s.v_patch DESC
  LIMIT 1;
  IF schema_id IS NULL THEN
    RAISE EXCEPTION 'no active review schema for %', p_target_kind;
  END IF;
  IF p_verdict = 'withdrawn' AND p_supersedes IS NULL THEN
    RAISE EXCEPTION 'a withdrawn review takes back an earlier review of the same target: pass its review_id as p_supersedes';
  END IF;

  IF p_target_kind = 'scope' THEN
    SELECT a.in_suva_scope INTO label FROM triage.assessment a WHERE a.assessment_id = p_target_id;
    IF label IS NULL THEN
      RAISE EXCEPTION 'assessment % not found', p_target_id;
    END IF;
    INSERT INTO gold.expert_review (target_kind, assessment_id, verdict, reviewed_label, review_schema_id,
                                    payload, actor, comment, supersedes_review_id)
    VALUES ('scope', p_target_id, p_verdict, label, schema_id, coalesce(p_payload, '{}'::jsonb),
            actor_handle, p_comment, p_supersedes)
    RETURNING review_id INTO rid;
  ELSE
    INSERT INTO gold.expert_review (target_kind, summary_version_id, verdict, review_schema_id,
                                    payload, actor, comment, supersedes_review_id)
    VALUES ('summary_version', p_target_id, p_verdict, schema_id, coalesce(p_payload, '{}'::jsonb),
            actor_handle, p_comment, p_supersedes)
    RETURNING review_id INTO rid;
  END IF;
  RETURN rid;
END $$;
COMMENT ON FUNCTION gold.submit_review(ops.review_target, uuid, ops.review_verdict, jsonb, text, uuid) IS 'The only way to write gold.expert_review (D-066, D-093). Takes the latest active review schema (scope_review.payload V1.1.0: shown_status, shown_score_0_100, shown_score_raw = what the expert saw; the DB checks only that the payload is an object); copies the label of the assessment. Scope: relevant | not_relevant on any label, correct | incorrect on in_scope or out_of_scope. Summary: validated | rejected. withdrawn requires p_supersedes, the review it takes back (same target, never a withdrawal).';

-- Expert edit of one language of a summary version: creates version n+1 (expert_edit), copies the other
-- language unchanged (texts, claims, citations), writes the edited language, and makes the new version current.
-- p_claims: [{"paragraph_no": 1, "section": "law", "text": "...", "cites": ["<consideration_id>", ...],
--             "edited_from_claim_id": "<claim_id or null>"}, ...]
CREATE OR REPLACE FUNCTION summ.create_expert_version(
  p_parent_version_id uuid,
  p_language          ops.lang_code,
  p_title_line        text,
  p_body              text,
  p_claims            jsonb
) RETURNS uuid
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
  actor_handle text := ops.require_actor();
  parent       summ.summary_version%ROWTYPE;
  new_id       uuid;
  other_lang   ops.lang_code := CASE p_language WHEN 'de' THEN 'fr'::ops.lang_code ELSE 'de'::ops.lang_code END;
  src_text     summ.summary_text%ROWTYPE;
  new_text_id  uuid;
  src_claim    summ.summary_claim%ROWTYPE;
  new_claim_id uuid;
  c            jsonb;
  cite         text;
  n            int := 0;
BEGIN
  IF p_language NOT IN ('de', 'fr') THEN
    RAISE EXCEPTION 'a summary version holds German and French texts only';
  END IF;
  IF jsonb_typeof(p_claims) <> 'array' OR jsonb_array_length(p_claims) = 0 THEN
    RAISE EXCEPTION 'p_claims must be a non-empty JSON array';
  END IF;
  SELECT * INTO parent FROM summ.summary_version WHERE summary_version_id = p_parent_version_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'summary version % not found', p_parent_version_id;
  END IF;

  INSERT INTO summ.summary_version (summary_id, version_no, origin, parent_version_id, preset_version_id,
                                    component_version_id, source_segmentation_id, creator_kind, creator_actor)
  VALUES (parent.summary_id, NULL, 'expert_edit', parent.summary_version_id, parent.preset_version_id,
          parent.component_version_id, parent.source_segmentation_id, 'expert', actor_handle)
  RETURNING summary_version_id INTO new_id;

  -- the other language, unchanged
  SELECT * INTO src_text FROM summ.summary_text WHERE summary_version_id = parent.summary_version_id AND language = other_lang;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'parent version % has no % text', p_parent_version_id, other_lang;
  END IF;
  INSERT INTO summ.summary_text (summary_version_id, language, title_line, body, word_count, paragraph_count, llm_call_id, repair_llm_call_id)
  VALUES (new_id, other_lang, src_text.title_line, src_text.body, src_text.word_count, src_text.paragraph_count,
          src_text.llm_call_id, src_text.repair_llm_call_id)
  RETURNING summary_text_id INTO new_text_id;
  FOR src_claim IN SELECT * FROM summ.summary_claim WHERE summary_text_id = src_text.summary_text_id ORDER BY ordinal LOOP
    INSERT INTO summ.summary_claim (summary_text_id, ordinal, paragraph_no, section, model_text, rendered_text, status, edited_from_claim_id)
    VALUES (new_text_id, src_claim.ordinal, src_claim.paragraph_no, src_claim.section, src_claim.model_text,
            src_claim.rendered_text, src_claim.status, src_claim.claim_id)
    RETURNING claim_id INTO new_claim_id;
    INSERT INTO summ.claim_citation (claim_id, consideration_id, ordinal)
    SELECT new_claim_id, cc.consideration_id, cc.ordinal FROM summ.claim_citation cc WHERE cc.claim_id = src_claim.claim_id;
  END LOOP;

  -- the edited language
  INSERT INTO summ.summary_text (summary_version_id, language, title_line, body, word_count, paragraph_count)
  VALUES (new_id, p_language, p_title_line, p_body,
          coalesce(array_length(regexp_split_to_array(btrim(p_body), '\s+'), 1), 0),
          greatest(1, (SELECT count(*) FROM regexp_split_to_table(btrim(p_body), '\n\s*\n') AS para WHERE btrim(para) <> '')::int))
  RETURNING summary_text_id INTO new_text_id;
  FOR c IN SELECT * FROM jsonb_array_elements(p_claims) LOOP
    n := n + 1;
    INSERT INTO summ.summary_claim (summary_text_id, ordinal, paragraph_no, section, model_text, rendered_text, status, edited_from_claim_id)
    VALUES (new_text_id, n, (c ->> 'paragraph_no')::smallint, (c ->> 'section')::ops.claim_section, NULL,
            c ->> 'text', 'flagged', nullif(c ->> 'edited_from_claim_id', '')::uuid)
    RETURNING claim_id INTO new_claim_id;
    FOR cite IN SELECT jsonb_array_elements_text(coalesce(c -> 'cites', '[]'::jsonb)) LOOP
      INSERT INTO summ.claim_citation (claim_id, consideration_id) VALUES (new_claim_id, cite::uuid);
    END LOOP;
  END LOOP;

  UPDATE summ.summary_version SET is_current = false WHERE summary_id = parent.summary_id AND is_current;
  UPDATE summ.summary_version SET is_current = true WHERE summary_version_id = new_id;
  RETURN new_id;
END $$;
COMMENT ON FUNCTION summ.create_expert_version(uuid, ops.lang_code, text, text, jsonb) IS
  'Expert edit: version n+1 (expert_edit), the other language copied unchanged, the edited language with its claims (status flagged until the verifier reruns), made current. A version stays a German + French pair (D-067).';
