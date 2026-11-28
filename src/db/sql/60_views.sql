-- ============================================================================
-- File: 60_views.sql (projections: current label, traces, timelines, exports, gates)
-- Date: 2026-11-28
-- Description: Everything "current" is computed here, never stored (counters and labels are projections).
--              The label shown and used is the default pipeline's (D-063); expert reviews sit beside it
--              (D-066). The layer-1 rule ledger and the ingest closure are read here (F-01, F-04).
--              Gate functions are used by the release trigger (80_triggers.sql) and by tests.
-- SGBD: PostgreSQL 17
-- Doc: docs/DB_DDL_PLANNING.md §8.4, §9.3, §10.3, §11.6, §12, §13.5, §13.7
-- ============================================================================
-- PREREQUISITE: 50_summ.sql, 12_ops_logs.sql
-- ============================================================================

-- --- corpus ------------------------------------------------------------------

CREATE OR REPLACE VIEW corpus.v_ruling AS
SELECT
  r.ruling_id, r.docket, r.decision_date, r.court, r.register_letter, r.filing_year, r.language,
  r.gegenstand, r.previous_instance, r.bger_url, r.origin, r.quarter_by_decision,
  pub.observed_date                       AS publication_date,
  pub.source                              AS publication_source,
  apx.observed_date                       AS publication_date_approx,
  CASE WHEN pub.observed_date IS NOT NULL THEN 'exact'
       WHEN apx.observed_date IS NOT NULL THEN 'approx_first_seen'
       ELSE 'unknown' END                 AS publication_quality,
  CASE WHEN pub.observed_date IS NOT NULL
       THEN extract(year FROM pub.observed_date)::integer::text || 'Q' || extract(quarter FROM pub.observed_date)::integer::text
  END                                     AS quarter_by_publication,
  pub.star,
  pub.sachgebiet,
  t.text_id                               AS primary_text_id,
  t.char_length,
  t.clean_length,
  s.segmentation_id                       AS primary_segmentation_id,
  s.consideration_count
FROM corpus.ruling r
LEFT JOIN LATERAL (
  SELECT o.observed_date, o.source, o.star, o.sachgebiet
  FROM corpus.publication_observation o
  WHERE o.ruling_id = r.ruling_id AND o.quality = 'exact'
  ORDER BY (o.source = 'neuheiten') DESC
  LIMIT 1) pub ON true
LEFT JOIN LATERAL (
  SELECT o.observed_date
  FROM corpus.publication_observation o
  WHERE o.ruling_id = r.ruling_id AND o.quality = 'approx_first_seen'
  LIMIT 1) apx ON true
LEFT JOIN corpus.ruling_text t ON t.ruling_id = r.ruling_id AND t.is_primary
LEFT JOIN corpus.segmentation s ON s.text_id = t.text_id AND s.is_primary;
COMMENT ON VIEW corpus.v_ruling IS 'Ruling with its best publication date (Neuheiten > HF poller), the approximation kept apart, quarter_by_publication from exact dates only (D-050), primary text and segmentation.';

CREATE OR REPLACE VIEW corpus.v_ingest_closure AS
WITH refs AS (
  SELECT snapshot_id, count(*) AS loaded_refs, count(*) FILTER (WHERE NOT is_twin) AS base_refs,
         count(*) FILTER (WHERE is_twin) AS twin_refs
  FROM corpus.ruling_source_ref GROUP BY snapshot_id
), exc AS (
  SELECT snapshot_id, sum(n) AS exclusions, sum(n_by_row) AS exclusions_by_row_index,
         jsonb_object_agg(reason_code, n ORDER BY reason_code) AS exclusions_by_reason
  FROM (SELECT snapshot_id, reason_code, count(*) AS n,
               count(*) FILTER (WHERE external_id ~ '^row:[0-9]+$') AS n_by_row
        FROM corpus.ingest_exclusion GROUP BY snapshot_id, reason_code) x
  GROUP BY snapshot_id
)
SELECT
  s.snapshot_id, s.source, s.revision, s.file_sha256, s.row_count,
  coalesce(r.loaded_refs, 0)                       AS loaded_refs,
  coalesce(r.base_refs, 0)                         AS base_refs,
  coalesce(r.twin_refs, 0)                         AS twin_refs,
  coalesce(e.exclusions, 0)::bigint                AS exclusions,
  coalesce(e.exclusions_by_reason, '{}'::jsonb)    AS exclusions_by_reason,
  coalesce(e.exclusions_by_row_index, 0)::bigint   AS exclusions_by_row_index,
  s.row_count - coalesce(r.loaded_refs, 0) - coalesce(e.exclusions, 0)::bigint AS unaccounted_rows,
  coalesce(s.row_count = coalesce(r.loaded_refs, 0) + coalesce(e.exclusions, 0)::bigint, false) AS closure_ok
FROM ops.source_snapshot s
LEFT JOIN refs r ON r.snapshot_id = s.snapshot_id
LEFT JOIN exc e ON e.snapshot_id = s.snapshot_id
WHERE r.snapshot_id IS NOT NULL OR e.snapshot_id IS NOT NULL;
COMMENT ON VIEW corpus.v_ingest_closure IS
  'Every row of a source file accounted for (F-04, G5), per snapshot that has source refs or exclusions: closure_ok = row_count = loaded refs (base + twins) + exclusions. Source refs are kept per snapshot, so a new revision of a file closes on its own, the rows an earlier revision loaded included. A row with a missing or duplicate source id is recorded as row:<index> (exclusions_by_row_index) and counted inside exclusions. unaccounted_rows > 0 = rows lost without a reason; NULL row_count = closure unknown (false).';

-- --- triage ------------------------------------------------------------------

CREATE OR REPLACE VIEW triage.v_current_release AS
SELECT rel.release_id, rel.profile_code, rel.profile_version_id, rel.ranking_id, rel.warnings,
       rk.run_id AS ranking_run_id, rk.population_id, rk.threshold_id
FROM ops.release rel
JOIN triage.ranking rk ON rk.ranking_id = rel.ranking_id
JOIN ops.pipeline_profile p ON p.profile_code = rel.profile_code
WHERE rel.is_current AND p.is_default AND p.retired_at IS NULL;
COMMENT ON VIEW triage.v_current_release IS 'The current release of the default pipeline (at most one row).';

CREATE OR REPLACE VIEW triage.v_scope_pipeline AS
WITH candidates AS (
  SELECT a.*, 1 AS prio, 'release'::text AS label_origin
  FROM triage.assessment a
  JOIN triage.v_current_release cur ON a.run_id = cur.ranking_run_id
  WHERE a.step = 'ranking' AND a.repetition_idx = 0
  UNION ALL
  SELECT a.*, 2 AS prio, 'latest_run'::text AS label_origin
  FROM triage.assessment a
  JOIN ops.pipeline_run pr ON pr.run_id = a.run_id
  JOIN ops.pipeline_profile_version pv ON pv.profile_version_id = pr.profile_version_id
  JOIN ops.pipeline_profile p ON p.profile_code = pv.profile_code AND p.is_default AND p.retired_at IS NULL
  WHERE a.repetition_idx = 0 AND pr.kind <> 'eval'
)
SELECT DISTINCT ON (c.ruling_id)
  c.ruling_id,
  c.in_suva_scope   AS pipeline_label,
  c.step,
  c.assessment_id,
  c.run_id,
  c.score_0_100,
  c.score_source,
  c.reason_code,
  rc.label_de       AS reason_label_de,
  rc.label_fr       AS reason_label_fr,
  c.explanation_de,
  c.outcome,
  c.mode,
  c.label_origin,
  c.created_at
FROM candidates c
LEFT JOIN ops.reason_code rc ON rc.code = c.reason_code
ORDER BY c.ruling_id, c.prio, c.step DESC, c.created_at DESC;
COMMENT ON VIEW triage.v_scope_pipeline IS
  'THE label (D-063): the default pipeline''s furthest-step assessment per ruling, from its current release, else from its latest non-eval run. not_assessed = no row.';

CREATE OR REPLACE VIEW triage.v_scope_current AS
SELECT
  p.*,
  rv.verdict                                       AS expert_verdict,
  rv.reviewed_label,
  rv.assessment_id                                 AS reviewed_assessment_id,
  (rv.assessment_id IS NOT NULL AND rv.assessment_id <> p.assessment_id) AS review_is_stale,
  CASE WHEN rv.verdict = 'correct' THEN rv.reviewed_label
       WHEN rv.verdict = 'incorrect' AND rv.reviewed_label = 'in_scope' THEN 'out_of_scope'::ops.in_suva_scope
       WHEN rv.verdict = 'incorrect' AND rv.reviewed_label = 'out_of_scope' THEN 'in_scope'::ops.in_suva_scope
  END                                              AS expert_implied_label,
  rv.actor                                         AS reviewed_by,
  rv.created_at                                    AS reviewed_at
FROM triage.v_scope_pipeline p
LEFT JOIN LATERAL (
  SELECT r.verdict, r.reviewed_label, r.assessment_id, r.actor, r.created_at
  FROM gold.expert_review r
  JOIN triage.assessment a ON a.assessment_id = r.assessment_id
  WHERE r.target_kind = 'scope' AND a.ruling_id = p.ruling_id
    AND NOT EXISTS (SELECT 1 FROM gold.expert_review s WHERE s.supersedes_review_id = r.review_id)
  ORDER BY r.created_at DESC
  LIMIT 1) rv ON true;
COMMENT ON VIEW triage.v_scope_current IS
  'The pipeline label plus the latest expert scope review beside it (D-066): expert_implied_label = the pipeline label, flipped when the verdict is incorrect. The delivered list and the metrics never read expert_implied_label.';

CREATE OR REPLACE VIEW triage.v_scope_trace AS
WITH RECURSIVE chain AS (
  SELECT p.ruling_id, a.assessment_id, a.upstream_assessment_id, 0 AS hop
  FROM triage.v_scope_pipeline p
  JOIN triage.assessment a ON a.assessment_id = p.assessment_id
  UNION ALL
  SELECT c.ruling_id, a.assessment_id, a.upstream_assessment_id, c.hop + 1
  FROM chain c
  JOIN triage.assessment a ON a.assessment_id = c.upstream_assessment_id
)
SELECT
  c.ruling_id, c.hop, a.step, a.assessment_id, a.in_suva_scope, a.outcome, a.score_0_100, a.score_source,
  a.reason_code, rc.label_de AS reason_label_de, a.explanation_de, a.mode,
  a.run_id, pr.kind AS run_kind, pr.git_commit, pr.model_override, ppv.profile_code, ppv.version_label AS profile_version,
  cv.name AS component_name, cv.version_label AS component_version, cv.code_sha256, cv.config_sha256,
  (SELECT jsonb_object_agg(cvm.model_role, m.gateway_id)
     FROM ops.component_version_model cvm JOIN ops.model m ON m.model_id = cvm.model_id
    WHERE cvm.component_version_id = cv.component_version_id)                          AS declared_models,
  (SELECT count(*) FROM triage.assessment_reason ar WHERE ar.assessment_id = a.assessment_id AND ar.outcome = 'fired') AS reason_count,
  (SELECT count(*) FROM triage.assessment_reason ar WHERE ar.assessment_id = a.assessment_id) AS evaluated_rule_count,
  lc.llm_call_id, lc.served_model, lc.latency_ms, lc.input_tokens, lc.output_tokens, lc.cache_hit, lc.finish_reason,
  lj.p_yes,
  t.source AS text_source, t.content_sha256 AS text_sha256,
  snap.source AS source_kind, snap.revision AS source_revision, snap.file_sha256 AS source_file_sha256,
  sp.status AS span_status, sp.duration_ms,
  (SELECT count(*) FROM ops.log_event e WHERE e.span_id = a.span_id)                    AS event_count,
  (SELECT count(*) FROM ops.log_event e WHERE e.span_id = a.span_id
                                         AND e.level IN ('warning', 'error', 'critical')) AS warning_or_worse_count
FROM chain c
JOIN triage.assessment a ON a.assessment_id = c.assessment_id
JOIN ops.pipeline_run pr ON pr.run_id = a.run_id
JOIN ops.pipeline_profile_version ppv ON ppv.profile_version_id = pr.profile_version_id
JOIN ops.component_version cv ON cv.component_version_id = a.component_version_id
JOIN ops.span sp ON sp.span_id = a.span_id
LEFT JOIN ops.reason_code rc ON rc.code = a.reason_code
LEFT JOIN triage.llm_judgement lj ON lj.assessment_id = a.assessment_id
LEFT JOIN triage.justification js ON js.assessment_id = a.assessment_id
LEFT JOIN ops.llm_call lc ON lc.llm_call_id = coalesce(lj.llm_call_id, js.llm_call_id)
LEFT JOIN corpus.ruling_text t ON t.text_id = a.input_text_id
LEFT JOIN ops.source_snapshot snap ON snap.snapshot_id = t.snapshot_id;
COMMENT ON VIEW triage.v_scope_trace IS 'The "show me why" panel: one row per step of the label''s lineage, with run, profile and component versions, models, reasons (reason_count = rules that fired; evaluated_rule_count = ledger rows, every rule of the version), LLM call, input text, source snapshot, span and event counts (D-064, D-065). Rule by rule: triage.v_layer1_ledger.';

CREATE OR REPLACE VIEW triage.v_layer1_ledger AS
SELECT
  a.assessment_id, a.run_id, a.ruling_id, r.docket, r.decision_date,
  ppv.profile_code, ppv.version_label AS profile_version,
  cv.version_label                    AS component_version,
  a.in_suva_scope,
  a.reason_code                       AS decision_reason_code,
  ar.ordinal, rl.rule_code, rl.version_label AS rule_version, ar.effect, ar.outcome,
  (ar.outcome = 'fired' AND ar.reason_code IS NOT DISTINCT FROM a.reason_code) AS is_decisive,
  ar.evidence_field, ar.examined_value, ar.char_start, ar.char_end, ar.matched_text, ar.detail,
  rc.label_de, rc.label_fr,
  a.input_text_id, t.content_sha256   AS text_sha256
FROM triage.assessment a
JOIN triage.assessment_reason ar ON ar.assessment_id = a.assessment_id
JOIN ops.rule rl ON rl.rule_id = ar.rule_id
JOIN corpus.ruling r ON r.ruling_id = a.ruling_id
JOIN ops.pipeline_run pr ON pr.run_id = a.run_id
JOIN ops.pipeline_profile_version ppv ON ppv.profile_version_id = pr.profile_version_id
JOIN ops.component_version cv ON cv.component_version_id = a.component_version_id
LEFT JOIN ops.reason_code rc ON rc.code = ar.reason_code
LEFT JOIN corpus.ruling_text t ON t.text_id = a.input_text_id
WHERE a.step = 'layer1_filter';
COMMENT ON VIEW triage.v_layer1_ledger IS
  'Layer 1 rule by rule (F-01, F-02): one row per assessment and rule of its version, with the outcome (fired, not_fired, not_applicable, blocked), the evidence, the German and French labels, and is_decisive (the fired rule whose reason code is the decision''s). Order by assessment_id, ordinal.';

CREATE OR REPLACE VIEW triage.v_export_ranked AS
SELECT
  cur.release_id,
  pop.code                     AS population_code,
  r.docket, r.decision_date,
  vr.publication_date, vr.publication_date_approx, vr.publication_quality,
  r.quarter_by_decision, vr.quarter_by_publication,
  ARRAY(SELECT p2.code FROM corpus.population_member pm JOIN corpus.population p2 ON p2.population_id = pm.population_id
        WHERE pm.ruling_id = r.ruling_id ORDER BY p2.code) AS populations,
  e.final_score_0_100, e.rank, e.above_threshold, e.in_top10, e.in_top30,
  a.in_suva_scope, a.score_source, a.reason_code, a.explanation_de
FROM triage.v_current_release cur
JOIN corpus.population pop ON pop.population_id = cur.population_id
JOIN triage.ranking_entry e ON e.ranking_id = cur.ranking_id
JOIN triage.assessment a ON a.assessment_id = e.assessment_id
JOIN corpus.ruling r ON r.ruling_id = e.ruling_id
JOIN corpus.v_ruling vr ON vr.ruling_id = r.ruling_id;
COMMENT ON VIEW triage.v_export_ranked IS 'The delivered ranked list of the current release (D-046): score, rank, threshold and top-30 marks, both dates and every population of each ruling (D-050). Must equal the hashed results/ file.';

-- --- gold --------------------------------------------------------------------

CREATE OR REPLACE VIEW gold.v_label_effective AS
SELECT
  p.population_id, p.code AS population_code, pm.ruling_id,
  coalesce(bool_or(l.in_suva_scope), false)                       AS in_suva_scope,
  CASE WHEN count(l.label_id) > 0 THEN 'suva_list' ELSE 'closed_world' END AS basis,
  EXISTS (SELECT 1 FROM gold.suva_summary ss WHERE ss.ruling_id = pm.ruling_id) AS has_suva_summary
FROM corpus.population p
JOIN corpus.population_member pm ON pm.population_id = p.population_id
LEFT JOIN gold.label l ON l.ruling_id = pm.ruling_id AND l.source = 'suva_relevance_list'
WHERE p.role = 'labelled'
GROUP BY p.population_id, p.code, pm.ruling_id;
COMMENT ON VIEW gold.v_label_effective IS 'Suva''s labels on the labelled populations; every unlisted member is false with basis closed_world (Q-04: an assumption, shown as such). has_suva_summary marks the must-hit subset.';

CREATE OR REPLACE VIEW gold.v_expert_review_current AS
SELECT DISTINCT ON (r.target_kind, coalesce(r.assessment_id, r.summary_version_id))
  r.*
FROM gold.expert_review r
WHERE NOT EXISTS (SELECT 1 FROM gold.expert_review s WHERE s.supersedes_review_id = r.review_id)
ORDER BY r.target_kind, coalesce(r.assessment_id, r.summary_version_id), r.created_at DESC;
COMMENT ON VIEW gold.v_expert_review_current IS 'The latest non-superseded review per target.';

-- --- summ --------------------------------------------------------------------

CREATE OR REPLACE VIEW summ.v_summary_current AS
SELECT
  s.summary_id, s.ruling_id, s.preset_code, pr.perspective, pr.is_mandatory,
  v.summary_version_id, v.version_no, v.origin, v.quality_status, v.creator_kind, v.mode, v.created_at,
  de.title_line AS title_de, de.body AS body_de, de.word_count AS words_de,
  fr.title_line AS title_fr, fr.body AS body_fr, fr.word_count AS words_fr,
  rv.verdict AS expert_verdict, rv.actor AS reviewed_by, rv.created_at AS reviewed_at
FROM summ.summary s
JOIN summ.preset pr ON pr.preset_code = s.preset_code
JOIN summ.summary_version v ON v.summary_id = s.summary_id AND v.is_current
LEFT JOIN summ.summary_text de ON de.summary_version_id = v.summary_version_id AND de.language = 'de'
LEFT JOIN summ.summary_text fr ON fr.summary_version_id = v.summary_version_id AND fr.language = 'fr'
LEFT JOIN gold.v_expert_review_current rv
  ON rv.target_kind = 'summary_version' AND rv.summary_version_id = v.summary_version_id;
COMMENT ON VIEW summ.v_summary_current IS 'Current version per (ruling, preset): both texts, verifier status, the latest expert review.';

CREATE OR REPLACE FUNCTION summ.mandatory_summary_gaps(p_release_id uuid)
  RETURNS TABLE (ruling_id uuid, docket text, decision_date date)
  LANGUAGE sql STABLE AS $$
  SELECT r.ruling_id, r.docket, r.decision_date
  FROM ops.release rel
  JOIN triage.ranking_entry e ON e.ranking_id = rel.ranking_id
  JOIN triage.assessment a ON a.assessment_id = e.assessment_id
  JOIN corpus.ruling r ON r.ruling_id = e.ruling_id
  WHERE rel.release_id = p_release_id
    AND a.in_suva_scope = 'in_scope'
    AND NOT EXISTS (
      SELECT 1
      FROM summ.summary s
      JOIN summ.preset p ON p.preset_code = s.preset_code AND p.is_mandatory AND p.retired_at IS NULL
      JOIN summ.summary_version v ON v.summary_id = s.summary_id AND v.is_current AND v.quality_status <> 'rejected'
      WHERE s.ruling_id = e.ruling_id
        AND (SELECT count(*) FROM summ.summary_text t WHERE t.summary_version_id = v.summary_version_id) = 2)
$$;
COMMENT ON FUNCTION summ.mandatory_summary_gaps(uuid) IS 'In-scope rulings of a release (default pipeline label) without a current, non-rejected suva_house version with both languages (D-067).';

CREATE OR REPLACE VIEW summ.v_mandatory_summary_gaps AS
SELECT g.* FROM triage.v_current_release cur, LATERAL summ.mandatory_summary_gaps(cur.release_id) g;
COMMENT ON VIEW summ.v_mandatory_summary_gaps IS 'Mandatory-summary gaps of the current release of the default pipeline: must be empty (D-067).';

CREATE OR REPLACE FUNCTION triage.release_gate_problems(p_release_id uuid)
  RETURNS TABLE (problem text, ruling_id uuid)
  LANGUAGE sql STABLE AS $$
  SELECT 'unranked_member', pm.ruling_id
  FROM ops.release rel
  JOIN triage.ranking rk ON rk.ranking_id = rel.ranking_id
  JOIN corpus.population_member pm ON pm.population_id = rk.population_id
  WHERE rel.release_id = p_release_id
    AND NOT EXISTS (SELECT 1 FROM triage.ranking_entry e WHERE e.ranking_id = rk.ranking_id AND e.ruling_id = pm.ruling_id)
  UNION ALL
  SELECT 'missing_mandatory_summary', g.ruling_id
  FROM summ.mandatory_summary_gaps(p_release_id) g
$$;
COMMENT ON FUNCTION triage.release_gate_problems(uuid) IS 'Why a release may not become current: a target member without a label, or an in-scope ruling without its mandatory summary (§9.2 invariant 4, §13.7). A failed judgement stays potentially and is allowed (it is listed in ranking_entry).';

-- --- ops ---------------------------------------------------------------------

CREATE OR REPLACE VIEW ops.v_ruling_timeline AS
SELECT s.ruling_id, s.started_at AS ts, 'span'::text AS kind, s.run_id, s.step, s.operation AS code,
       s.status::text AS level_or_status, s.error_message AS message, s.attributes, s.span_id, s.duration_ms
FROM ops.span s
WHERE s.ruling_id IS NOT NULL
UNION ALL
SELECT e.ruling_id, e.ts, 'event'::text, e.run_id, e.step, e.event_code,
       e.level::text, e.message, e.attributes, e.span_id, NULL::bigint
FROM ops.log_event e
WHERE e.ruling_id IS NOT NULL;
COMMENT ON VIEW ops.v_ruling_timeline IS 'Spans and events of a ruling across runs; order by ts. The transparency timeline of the UI (D-065).';

CREATE OR REPLACE VIEW ops.v_run_health AS
SELECT
  pr.run_id, pr.kind, pr.status, pr.mode, s.step,
  count(*)                                                     AS spans,
  count(*) FILTER (WHERE s.status = 'error')                   AS error_spans,
  percentile_cont(0.95) WITHIN GROUP (ORDER BY s.duration_ms)  AS p95_duration_ms,
  (SELECT count(*) FROM ops.work_item w WHERE w.run_id = pr.run_id AND w.step = s.step AND w.status = 'failed') AS failed_items,
  (SELECT jsonb_object_agg(m.metric_code, m.value) FROM ops.run_metric m WHERE m.run_id = pr.run_id AND m.step = s.step) AS metrics
FROM ops.pipeline_run pr
JOIN ops.span s ON s.run_id = pr.run_id
WHERE s.step IS NOT NULL
GROUP BY pr.run_id, pr.kind, pr.status, pr.mode, s.step;
COMMENT ON VIEW ops.v_run_health IS 'Admin panel: per run and step, spans, errors, p95 duration, failed work items, metrics. A step at 0 is red (G6).';

CREATE OR REPLACE VIEW ops.v_profile AS
SELECT
  p.profile_code, p.is_default, pv.profile_version_id, pv.version_label AS profile_version, pv.status AS profile_status,
  ps.step, cv.component_version_id, cv.name AS component_name, cv.version_label AS component_version,
  cv.status AS component_status, cv.code_sha256, cv.config_sha256,
  (SELECT jsonb_object_agg(cvm.model_role, m.gateway_id)
     FROM ops.component_version_model cvm JOIN ops.model m ON m.model_id = cvm.model_id
    WHERE cvm.component_version_id = cv.component_version_id)                                  AS models,
  (SELECT count(*) FROM ops.component_version_rule r WHERE r.component_version_id = cv.component_version_id AND r.enabled) AS enabled_rules
FROM ops.pipeline_profile p
JOIN ops.pipeline_profile_version pv ON pv.profile_code = p.profile_code
JOIN ops.pipeline_profile_step ps ON ps.profile_version_id = pv.profile_version_id
JOIN ops.component_version cv ON cv.component_version_id = ps.component_version_id;
COMMENT ON VIEW ops.v_profile IS 'Which step versions, models and rules each profile version pins (transparency panel).';
