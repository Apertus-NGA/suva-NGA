"""Read side of the API: every SQL the API runs to read, in one place.

One row per ruling (`ROWS`) carries what the list, the facets and the ruling page share: the ruling's metadata
(`corpus.v_ruling`), the pipeline label and the expert's verdict (`triage.v_scope_current`), the layer-2 logit
(`triage.assessment.score_raw`), and three values derived here only: `status`, `area` and `is_new`.
The label itself is never recomputed: `triage.v_scope_pipeline` (behind `v_scope_current`) stays the one definition.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import psycopg

MAX_PAGE_SIZE = 200
PRESET = "suva_house"  # the summary every in-scope ruling must have (D-067); the API reads only this preset

# The ruling's status: the first matching row wins. An expert verdict survives a later model run (its staleness stays
# visible in `expert.stale`). `ai_relevant` / `ai_not_relevant` only from a ranking step (in_scope / out_of_scope of a
# ruling layer 1 kept), or ai_relevant from an explicit threshold (API_AI_RELEVANT_MIN_SCORE) while D-021 is open;
# `filtered_out` = layer 1 dropped it, whatever a later step republishes.
STATUSES = (
    "expert_relevant",
    "expert_not_relevant",
    "ai_relevant",
    "potentially_relevant",
    "ai_not_relevant",
    "filtered_out",
    "not_assessed",
)

# The matter of a ruling, as code (the court's matter names, any language): the rubric layer 1 reads (Neuheiten,
# then HF legal_area, then the start of the subject line), cut at the first bracket, comma or semicolon. PostgreSQL
# regular expressions, case-insensitive; the first code that matches wins.
AREA_PATTERNS: tuple[tuple[str, str], ...] = (
    ("UV", r"unfallversicherung|assurance[- ]accidents?\y|assicurazione (?:contro gli |contro l'|contro )?infortuni"),
    ("MV", r"militärversicherung|assurance[- ]militaire|assicurazione militare"),
    ("IV", r"invalidenversicherung|assurance[- ]invalidité|assicurazione (?:per l'|per la |d')?invalidità"),
    ("KV", r"krankenversicherung|assurance[- ]maladie|assicurazione (?:contro le )?malattie"),
    ("BV", r"berufliche vorsorge|prévoyance professionnelle|previdenza profession+ale"),
    ("CONTRACT", r"vertragsrecht|droit des contrats|diritto contrattuale"),
    ("LIABILITY", r"haftpflichtrecht|assurance responsabilité civile"),
)
AREAS = tuple(code for code, _ in AREA_PATTERNS) + ("other",)
CORE_AREAS = ("UV", "MV", "IV")

# Every order ends on the ruling's UUID: a stable order, so pages never overlap or skip a ruling.
SORTS = {
    "score": "score_0_100 {dir} NULLS LAST, score_raw {dir} NULLS LAST, docket, ruling_id",
    "decision_date": "decision_date {dir}, docket, ruling_id",
    "publication_date": "published_any {dir} NULLS LAST, docket, ruling_id",
    "docket": "docket {dir}, ruling_id",
    "status": "status_rank {dir}, score_0_100 DESC NULLS LAST, score_raw DESC NULLS LAST, docket, ruling_id",
}


_NBSP = " "  # the court's pages write a no-break space inside some matter names


def _literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


_AREA_CASE = (
    "CASE "
    + " ".join(f"WHEN h.head ~* {_literal(rx)} THEN {_literal(code)}" for code, rx in AREA_PATTERNS)
    + " ELSE 'other' END"
)
_STATUS_RANK = "array_position(ARRAY[" + ", ".join(_literal(s) for s in STATUSES) + "]::text[], status)"


def rows_cte(ai_relevant_min_score: float | None) -> str:
    """The shared CTE `rows`: one row per ruling. The threshold is a validated float, inlined as a literal."""
    threshold = "NULL::numeric" if ai_relevant_min_score is None else f"{float(ai_relevant_min_score)!r}::numeric"
    return f"""
WITH scope AS MATERIALIZED (
  -- materialized: the planner estimates two rows for this view and would loop over it once per ruling
  SELECT sc.*, a.score_raw,
         -- the label of layer 1 on this lineage (an upstream is always an earlier step: at most three hops)
         CASE WHEN a.step = 'layer1_filter' THEN a.in_suva_scope WHEN u1.step = 'layer1_filter' THEN u1.in_suva_scope
              WHEN u2.step = 'layer1_filter' THEN u2.in_suva_scope WHEN u3.step = 'layer1_filter' THEN u3.in_suva_scope
         END AS layer1_label
  FROM triage.v_scope_current sc
  JOIN triage.assessment a ON a.assessment_id = sc.assessment_id
  LEFT JOIN triage.assessment u1 ON u1.assessment_id = a.upstream_assessment_id
  LEFT JOIN triage.assessment u2 ON u2.assessment_id = u1.upstream_assessment_id
  LEFT JOIN triage.assessment u3 ON u3.assessment_id = u2.upstream_assessment_id
), summaries AS MATERIALIZED (
  SELECT c.ruling_id, coalesce(bool_or(c.expert_verdict = 'validated'), false) AS summary_validated
  FROM summ.v_summary_current c WHERE c.preset_code = 'suva_house' GROUP BY c.ruling_id
), refs AS MATERIALIZED (
  -- Suva's own summary of the ruling (gold.suva_summary), when one is linked to it
  SELECT DISTINCT g.ruling_id FROM gold.suva_summary g WHERE g.ruling_id IS NOT NULL
), latest_ingest AS (
  -- the latest usable INCREMENTAL ingest: the first ingest loads the base, so is_new needs a later one
  SELECT run_id FROM ops.pipeline_run
  WHERE kind = 'ingest' AND status IN ('succeeded', 'partial')
    AND (SELECT count(*) FROM ops.pipeline_run p WHERE p.kind = 'ingest' AND p.status IN ('succeeded', 'partial')) > 1
  ORDER BY started_at DESC LIMIT 1
), base AS (
  SELECT
    v.ruling_id, v.docket, v.decision_date, v.publication_date, v.publication_date_approx, v.publication_quality,
    coalesce(v.publication_date, v.publication_date_approx) AS published_any,
    v.quarter_by_decision, v.quarter_by_publication, v.court, v.register_letter, v.language,
    v.gegenstand AS subject, v.bger_url, v.primary_text_id, v.star,
    {_AREA_CASE} AS area, nullif(h.head, '') AS rubric,
    sc.pipeline_label, sc.step, sc.score_0_100, sc.score_raw, sc.score_source, sc.reason_code,
    sc.reason_label_de, sc.reason_label_fr, sc.explanation_de, sc.outcome, sc.mode, sc.label_origin,
    sc.assessment_id, sc.run_id, sc.expert_verdict, sc.reviewed_label, sc.review_is_stale,
    sc.expert_implied_label, sc.reviewed_at,
    CASE
      WHEN sc.expert_implied_label = 'in_scope' THEN 'expert_relevant'
      WHEN sc.expert_implied_label = 'out_of_scope' THEN 'expert_not_relevant'
      WHEN sc.pipeline_label = 'in_scope' THEN 'ai_relevant'
      WHEN {threshold} IS NOT NULL AND sc.pipeline_label = 'potentially' AND sc.step <> 'layer1_filter'
           AND sc.score_0_100 >= {threshold} THEN 'ai_relevant'
      WHEN sc.pipeline_label = 'potentially' THEN 'potentially_relevant'
      WHEN sc.layer1_label = 'out_of_scope' THEN 'filtered_out'
      WHEN sc.pipeline_label = 'out_of_scope' THEN 'ai_not_relevant'
      ELSE 'not_assessed'
    END AS status,
    coalesce(r.created_by_run_id = li.run_id, false) AS is_new,
    sm.ruling_id IS NOT NULL AS has_summary, coalesce(sm.summary_validated, false) AS summary_validated,
    rf.ruling_id IS NOT NULL AS has_reference
  FROM corpus.v_ruling v
  JOIN corpus.ruling r ON r.ruling_id = v.ruling_id
  LEFT JOIN latest_ingest li ON true
  LEFT JOIN LATERAL (
    SELECT so.rubric FROM corpus.subject_observation so
    WHERE so.ruling_id = v.ruling_id
    ORDER BY (so.source = 'neuheiten') DESC, so.created_at DESC LIMIT 1) so ON true
  LEFT JOIN LATERAL (
    SELECT btrim(rtrim(btrim(regexp_replace(translate(coalesce(so.rubric, v.gegenstand, ''), '’{_NBSP}', ''' '),
                                            '[(,;].*$', '')), '*')) AS head) h ON true
  LEFT JOIN scope sc ON sc.ruling_id = v.ruling_id
  LEFT JOIN summaries sm ON sm.ruling_id = v.ruling_id
  LEFT JOIN refs rf ON rf.ruling_id = v.ruling_id
), rows AS (
  SELECT base.*, {_STATUS_RANK} AS status_rank FROM base
)
"""


@dataclass
class Filters:
    q: str | None = None
    decided_from: date | None = None
    decided_to: date | None = None
    published_from: date | None = None
    published_to: date | None = None
    courts: list[str] = field(default_factory=list)
    areas: list[str] = field(default_factory=list)
    core: bool = False
    languages: list[str] = field(default_factory=list)
    statuses: list[str] = field(default_factory=list)
    score_min: float | None = None
    score_max: float | None = None
    has_summary: bool | None = None
    inbox: bool = False
    ruling_id: str | None = None


def where(f: Filters, skip: frozenset[str] = frozenset()) -> tuple[str, list[Any]]:
    """The WHERE clause of the filters, without those in `skip` (facets drop their own filter)."""
    parts: list[str] = []
    args: list[Any] = []

    def add(name: str, clause: str, *values: Any) -> None:
        if name not in skip:
            parts.append(clause)
            args.extend(values)

    if f.ruling_id:
        add("id", "ruling_id = %s::uuid", f.ruling_id)
    if f.q:
        pattern = "%" + f.q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        add("q", "(docket ILIKE %s OR subject ILIKE %s)", pattern, pattern)
    if f.decided_from:
        add("decided", "decision_date >= %s", f.decided_from)
    if f.decided_to:
        add("decided", "decision_date <= %s", f.decided_to)
    if f.published_from:
        add("published", "published_any >= %s", f.published_from)
    if f.published_to:
        add("published", "published_any <= %s", f.published_to)
    if f.courts:
        add("court", "court = ANY(%s)", list(f.courts))
    if f.areas:
        add("area", "area = ANY(%s)", list(f.areas))
    if f.core:
        add("area", "area = ANY(%s)", list(CORE_AREAS))
    if f.languages:
        add("language", "language::text = ANY(%s)", list(f.languages))
    if f.statuses:
        add("status", "status = ANY(%s)", list(f.statuses))
    if f.score_min is not None:
        add("score", "score_0_100 >= %s", f.score_min)
    if f.score_max is not None:
        add("score", "score_0_100 <= %s", f.score_max)
    if f.has_summary is not None:
        add("has_summary", "has_summary = %s", f.has_summary)
    if f.inbox:  # new, and no active expert decision (a withdrawn one sends it back to the inbox)
        add("inbox", "is_new AND (expert_verdict IS NULL OR expert_verdict = 'withdrawn')")
    return (" AND ".join(parts) or "true"), args


def decision_token(r: dict[str, Any]) -> str:
    """What the expert saw: the assessment behind the label and the time of the latest expert decision. A decision
    sent with an older token answers 409 (the ruling changed since the page was loaded)."""
    at = r["reviewed_at"].isoformat() if r["reviewed_at"] else ""
    return f"{r['assessment_id'] or ''}|{at}"


def ruling_row(r: dict[str, Any]) -> dict[str, Any]:
    """The RulingRow of the API from one row of `rows`."""
    return {
        "id": str(r["ruling_id"]),
        "docket": r["docket"],
        "decision_date": r["decision_date"],
        "publication_date": r["publication_date"],
        "publication_date_approx": r["publication_date_approx"],
        "publication_quality": r["publication_quality"],
        "quarter_by_decision": r["quarter_by_decision"],
        "quarter_by_publication": r["quarter_by_publication"],
        "court": r["court"],
        "language": r["language"],
        "area": r["area"],
        "rubric": r["rubric"],
        "star": r["star"],
        "subject": r["subject"],
        "bger_url": r["bger_url"],
        "status": r["status"],
        "pipeline_label": r["pipeline_label"],
        "step": r["step"],
        "score": None if r["score_0_100"] is None else float(r["score_0_100"]),
        "score_raw": r["score_raw"],
        "score_source": r["score_source"],
        "reason_code": r["reason_code"],
        "reason_label_de": r["reason_label_de"],
        "reason_label_fr": r["reason_label_fr"],
        "explanation_de": r["explanation_de"],
        "outcome": r["outcome"],
        "mode": r["mode"],
        "is_new": r["is_new"],
        "has_summary": r["has_summary"],
        "summary_validated": r["summary_validated"],
        "has_reference": r["has_reference"],
        "decision_token": decision_token(r),
        "expert": {
            "verdict": r["expert_verdict"],
            "label": r["expert_implied_label"],
            "at": r["reviewed_at"],
            "stale": bool(r["review_is_stale"]) if r["expert_verdict"] is not None else False,
        },
    }


def list_rulings(
    conn: psycopg.Connection, f: Filters, *, threshold: float | None, sort: str, order: str, limit: int, offset: int
) -> dict[str, Any]:
    w, args = where(f)
    direction = "ASC" if order == "asc" else "DESC"
    order_by = SORTS[sort].format(dir=direction)
    cte = rows_cte(threshold)
    with conn.cursor() as cur:
        cur.execute(
            f"{cte} SELECT *, count(*) OVER () AS total_count FROM rows WHERE {w}"
            f" ORDER BY {order_by} LIMIT %s OFFSET %s",
            [*args, limit, offset],
        )
        found = cur.fetchall()
        if found:
            total = found[0]["total_count"]
        else:  # past the last page: the window gave no row to read the total from
            cur.execute(f"{cte} SELECT count(*) AS n FROM rows WHERE {w}", args)
            total = cur.fetchone()["n"]
        items = [ruling_row(r) for r in found]
    return {"total": total, "items": items}


def one_ruling(conn: psycopg.Connection, ruling_id: str, *, threshold: float | None) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(f"{rows_cte(threshold)} SELECT * FROM rows WHERE ruling_id = %s::uuid", [ruling_id])
        r = cur.fetchone()
    return r


def facets(conn: psycopg.Connection, f: Filters, *, threshold: float | None) -> dict[str, Any]:
    """Counts per value of each facet, under every filter except the facet's own."""
    parts: list[str] = []
    args: list[Any] = []

    def scalar(alias: str, expr: str, skip: frozenset[str]) -> None:
        w, a = where(f, skip)
        parts.append(f"(SELECT {expr} FROM rows WHERE {w}) AS {alias}")
        args.extend(a)

    def counted(alias: str, column: str, skip: str) -> None:
        w, a = where(f, frozenset({skip}))
        parts.append(
            f"(SELECT coalesce(json_agg(json_build_object('value', value, 'n', n) ORDER BY n DESC, value), '[]'::json)"
            f" FROM (SELECT {column}::text AS value, count(*) AS n FROM rows WHERE {w} GROUP BY 1) x) AS {alias}"
        )
        args.extend(a)

    scalar("total", "count(*)", frozenset())
    scalar("decided_min", "min(decision_date)", frozenset({"decided"}))
    scalar("decided_max", "max(decision_date)", frozenset({"decided"}))
    scalar("published_min", "min(published_any)", frozenset({"published"}))
    scalar("published_max", "max(published_any)", frozenset({"published"}))
    counted("courts", "court", "court")
    counted("areas", "area", "area")
    counted("languages", "language", "language")
    counted("statuses", "status", "status")
    with conn.cursor() as cur:
        cur.execute(f"{rows_cte(threshold)} SELECT {', '.join(parts)}", args)
        return dict(cur.fetchone())


# --- the ruling page ---------------------------------------------------------------------------------------------


def relevance(conn: psycopg.Connection, row: dict[str, Any]) -> dict[str, Any]:
    """The "why" card: the current label's lineage (v_scope_trace), layer 1's fired rules with their offsets in the
    ruling text, and layer 2's reading of Apertus. `rules` lists the scorer's signals (src/scorer/load.py) when the
    current layer-2 assessment was written by the scorer; otherwise it stays empty (the 8B judge has no rule)."""
    if row["assessment_id"] is None:
        return {
            "state": "not_assessed",
            "reason": "no assessment of the default pipeline forms a label yet",
            "reason_code": "NOT_ASSESSED",
        }
    with conn.cursor() as cur:
        cur.execute(
            "SELECT t.*, pr.status AS run_status, pr.started_at AS run_started_at, pr.finished_at AS run_finished_at"
            " FROM triage.v_scope_trace t JOIN ops.pipeline_run pr ON pr.run_id = t.run_id"
            " WHERE t.ruling_id = %s ORDER BY t.hop",
            [row["ruling_id"]],
        )
        hops = cur.fetchall()
        current = hops[0] if hops else None
        layer1_hop = next((h for h in hops if h["step"] == "layer1_filter"), None)
        layer1: list[dict[str, Any]] = []
        text_id = None
        if layer1_hop:
            cur.execute(
                "SELECT rule_code, label_de, label_fr, effect, outcome, is_decisive, evidence_field, examined_value,"
                " matched_text, char_start, char_end, detail, input_text_id"
                " FROM triage.v_layer1_ledger WHERE assessment_id = %s AND outcome = 'fired' ORDER BY ordinal",
                [layer1_hop["assessment_id"]],
            )
            for x in cur.fetchall():
                text_id = x["input_text_id"]
                layer1.append(
                    {
                        "rule": x["rule_code"],
                        "label_de": x["label_de"],
                        "label_fr": x["label_fr"],
                        "effect": x["effect"],
                        "outcome": x["outcome"],
                        "decisive": x["is_decisive"],
                        "field": x["evidence_field"],
                        "examined_value": x["examined_value"],
                        "text_id": str(x["input_text_id"]) if x["input_text_id"] else None,
                        "matched_text": x["matched_text"],
                        "char_start": x["char_start"],
                        "char_end": x["char_end"],
                        "detail": x["detail"],
                    }
                )
        layer2 = None
        signal_rules: list[dict[str, Any]] = []
        readings: list[dict[str, Any]] = []
        layer2_hop = next((h for h in hops if h["step"] == "layer2_judge"), None)
        if layer2_hop:
            signal_rules, readings = _scorer_signals(cur, layer2_hop["assessment_id"])
            cur.execute(
                "SELECT j.requested_model, j.served_model, j.question_language, j.logprob_yes, j.logprob_no, j.p_yes,"
                " j.yes_no_in_top, j.top_logprobs, j.text_chars_total, j.text_chars_sent, j.truncation,"
                " j.input_tokens, j.llm_call_id, pv.version_label AS prompt_version, pv.role AS prompt_role"
                " FROM triage.llm_judgement j JOIN ops.prompt_version pv ON pv.prompt_version_id = j.prompt_version_id"
                " WHERE j.assessment_id = %s",
                [layer2_hop["assessment_id"]],
            )
            j = cur.fetchone()
            if j:
                layer2 = {
                    "model": j["served_model"],
                    "requested_model": j["requested_model"],
                    "prompt_version": j["prompt_version"],
                    "prompt_role": j["prompt_role"],
                    "question_language": j["question_language"],
                    "p_yes": j["p_yes"],
                    "logprob_yes": j["logprob_yes"],
                    "logprob_no": j["logprob_no"],
                    "yes_no_in_top": j["yes_no_in_top"],
                    "top_logprobs": j["top_logprobs"],
                    "text_chars_total": j["text_chars_total"],
                    "text_chars_sent": j["text_chars_sent"],
                    "truncation": j["truncation"],
                    "input_tokens": j["input_tokens"],
                    "llm_call_id": str(j["llm_call_id"]) if j["llm_call_id"] else None,
                    "outcome": layer2_hop["outcome"],
                }
    return {
        "state": "scored" if row["score_0_100"] is not None else "assessed",
        "label": row["pipeline_label"],
        "step": row["step"],
        "score": None if row["score_0_100"] is None else float(row["score_0_100"]),
        "score_raw": row["score_raw"],
        "score_source": row["score_source"],
        "reason_code": row["reason_code"],
        "reason_label_de": row["reason_label_de"],
        "reason_label_fr": row["reason_label_fr"],
        "explanation_de": row["explanation_de"],
        "mode": row["mode"],
        "run": None
        if current is None
        else {
            "run_id": str(current["run_id"]),
            "kind": current["run_kind"],
            "status": current["run_status"],
            "mode": current["mode"],
            "started_at": current["run_started_at"],
            "finished_at": current["run_finished_at"],
            "profile": f"{current['profile_code']} {current['profile_version']}",
            "component": f"{current['component_name']} {current['component_version']}",
        },
        "trace": [
            {
                "hop": h["hop"],
                "step": h["step"],
                "label": h["in_suva_scope"],
                "outcome": h["outcome"],
                "score": None if h["score_0_100"] is None else float(h["score_0_100"]),
                "reason_code": h["reason_code"],
                "explanation_de": h["explanation_de"],
                "run_id": str(h["run_id"]),
                "component_version": h["component_version"],
            }
            for h in hops
        ],
        "text_id": str(text_id) if text_id else None,
        "layer1": layer1,
        "layer2": layer2,
        "rules": signal_rules,
        "readings": readings,
        "read_by_apertus": (
            any(r["source"] == "apertus" and r["applies"] for r in signal_rules) if signal_rules else layer2 is not None
        ),
    }


def _number(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _direction(definition: dict[str, Any], detail: dict[str, Any]) -> int | None:
    """The rule's fixed direction (ops.rule.definition), else the sign of its stored contribution."""
    registered = definition.get("direction")
    if registered in (1, -1):
        return int(registered)
    contribution = _number(detail.get("contribution"))
    if contribution is None or contribution == 0:
        return None
    return 1 if contribution > 0 else -1


def _scorer_signals(cur: psycopg.Cursor, assessment_id: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(rules, readings) of a layer-2 assessment written by the scorer: its `signal` reasons, in the scorer's order.
    Detail keys from src/scorer/load.py: value, contribution, effect, and readings on the Apertus rule when read."""
    cur.execute(
        "SELECT r.rule_code, r.definition, ar.outcome, ar.detail FROM triage.assessment_reason ar"
        " JOIN ops.rule r ON r.rule_id = ar.rule_id WHERE ar.assessment_id = %s AND ar.effect = 'signal'"
        " ORDER BY ar.ordinal",
        [assessment_id],
    )
    rules: list[dict[str, Any]] = []
    readings: list[dict[str, Any]] = []
    for x in cur.fetchall():
        definition = x["definition"] if isinstance(x["definition"], dict) else {}
        detail = x["detail"] if isinstance(x["detail"], dict) else {}
        feature = definition.get("feature")
        source = definition.get("source") or ("apertus" if feature == "consensus" else "code")
        rules.append(
            {
                "rule": x["rule_code"],
                "feature": feature,
                "source": source,
                "direction": _direction(definition, detail),
                "applies": x["outcome"] == "fired",
                "value": _number(detail.get("value")),
                "effect": _number(detail.get("effect")),
            }
        )
        if isinstance(detail.get("readings"), dict) and not readings:
            readings = [{"reading": k, "level": _number(v)} for k, v in detail["readings"].items()]
    return rules, readings


def ruling_text(conn: psycopg.Connection, text_id: Any) -> dict[str, Any] | None:
    if text_id is None:
        return None
    with conn.cursor() as cur:
        cur.execute("SELECT text_id, source, content FROM corpus.ruling_text WHERE text_id = %s", [text_id])
        return cur.fetchone()


def summaries(conn: psycopg.Connection, ruling_id: Any) -> dict[str, Any]:
    """The current summary per language (preset suva_house, the mandatory one), its sentences and their status.
    Empty until layer 3."""
    out: dict[str, Any] = {"de": None, "fr": None}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM summ.v_summary_current WHERE ruling_id = %s AND preset_code = %s",
            [ruling_id, PRESET],
        )
        cur_row = cur.fetchone()
        if cur_row is None:
            return out
        cur.execute(
            "SELECT t.language, t.summary_text_id, c.claim_id, c.ordinal, c.paragraph_no, c.section, c.rendered_text,"
            " c.status FROM summ.summary_text t LEFT JOIN summ.summary_claim c ON c.summary_text_id = t.summary_text_id"
            " WHERE t.summary_version_id = %s ORDER BY t.language, c.ordinal",
            [cur_row["summary_version_id"]],
        )
        claims = cur.fetchall()
    for lang in ("de", "fr"):
        out[lang] = {
            "summary_version_id": str(cur_row["summary_version_id"]),
            "summary_id": str(cur_row["summary_id"]),
            "preset": cur_row["preset_code"],
            "version": cur_row["version_no"],
            "origin": cur_row["origin"],
            "quality_status": cur_row["quality_status"],
            "mode": cur_row["mode"],
            "validated": cur_row["expert_verdict"] == "validated",
            "validated_at": cur_row["reviewed_at"] if cur_row["expert_verdict"] == "validated" else None,
            "title_line": cur_row[f"title_{lang}"],
            "body": cur_row[f"body_{lang}"],
            "sentences": [
                {
                    "claim_id": str(c["claim_id"]),
                    "ordinal": c["ordinal"],
                    "paragraph": c["paragraph_no"],
                    "section": c["section"],
                    "text": c["rendered_text"],
                    "status": c["status"],
                    "sources": [],
                }
                for c in claims
                if c["language"] == lang and c["claim_id"] is not None
            ],
        }
    return out


def latest_summary_request(conn: psycopg.Connection, ruling_id: Any) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT request_id, status, status_detail, created_at, updated_at FROM ops.user_request"
            " WHERE ruling_id = %s AND kind = 'summary' ORDER BY created_at DESC LIMIT 1",
            [ruling_id],
        )
        r = cur.fetchone()
    return None if r is None else {**r, "request_id": str(r["request_id"])}


def reference_summary(conn: psycopg.Connection, ruling_id: Any) -> dict[str, Any] | None:
    """Suva's own summary of the ruling (gold.suva_summary: texts only, D-051). Empty until its loader exists."""
    with conn.cursor() as cur:
        cur.execute("SELECT text_de, text_fr FROM gold.suva_summary WHERE ruling_id = %s LIMIT 1", [ruling_id])
        r = cur.fetchone()
    return None if r is None else {"de": r["text_de"], "fr": r["text_fr"]}


def ruling_detail(conn: psycopg.Connection, ruling_id: str, *, threshold: float | None) -> dict[str, Any] | None:
    row = one_ruling(conn, ruling_id, threshold=threshold)
    if row is None:
        return None
    text = ruling_text(conn, row["primary_text_id"])
    return {
        "ruling": ruling_row(row),
        "text": text["content"] if text else None,
        "text_id": str(text["text_id"]) if text else None,
        "text_source": text["source"] if text else None,
        "relevance": relevance(conn, row),
        "summaries": summaries(conn, row["ruling_id"]),
        "summary_request": latest_summary_request(conn, row["ruling_id"]),
        "reference": reference_summary(conn, row["ruling_id"]),
    }


# --- counters and descriptions -----------------------------------------------------------------------------------


_IMPLIED = (
    "CASE r.verdict WHEN 'relevant' THEN 'in_scope' WHEN 'not_relevant' THEN 'out_of_scope'"
    " WHEN 'correct' THEN r.reviewed_label::text"
    " WHEN 'incorrect' THEN CASE r.reviewed_label WHEN 'in_scope' THEN 'out_of_scope' ELSE 'in_scope' END END"
)


def learning(conn: psycopg.Connection) -> dict[str, Any]:
    """What the experts did, as counts: scope decisions and their transitions, summary edits and validations."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM gold.expert_review r WHERE r.target_kind = 'scope' AND r.verdict <> 'withdrawn'"
        )
        decisions = cur.fetchone()["n"]
        cur.execute(
            f"SELECT coalesce(r.payload ->> 'shown_status', r.reviewed_label::text) AS before, {_IMPLIED} AS after,"
            " count(*) AS n FROM gold.expert_review r WHERE r.target_kind = 'scope' AND r.verdict <> 'withdrawn'"
            " GROUP BY 1, 2 ORDER BY 3 DESC, 1, 2"
        )
        transitions = cur.fetchall()
        cur.execute(
            "SELECT count(*) FILTER (WHERE origin IN ('generated', 'repaired', 'regenerated')) AS generated,"
            " count(*) FILTER (WHERE origin = 'expert_edit') AS edited FROM summ.summary_version"
        )
        versions = cur.fetchone()
        cur.execute(
            "SELECT count(*) AS n FROM gold.v_expert_review_current WHERE target_kind = 'summary_version'"
            " AND verdict = 'validated'"
        )
        validated = cur.fetchone()["n"]
        cur.execute(
            "SELECT t.language, count(*) AS n FROM summ.summary_version v"
            " JOIN summ.summary_text t ON t.summary_version_id = v.summary_version_id"
            " JOIN summ.summary_text p ON p.summary_version_id = v.parent_version_id AND p.language = t.language"
            " WHERE v.origin = 'expert_edit' AND (t.body <> p.body OR t.title_line <> p.title_line)"
            " GROUP BY 1 ORDER BY 1"
        )
        per_language = {r["language"]: r["n"] for r in cur.fetchall()}
    return {
        "decisions": decisions,
        "transitions": transitions,
        "summaries_generated": versions["generated"],
        "summaries_edited": versions["edited"],
        "summaries_validated": validated,
        "edits_per_language": per_language,
    }


def scoring(conn: psycopg.Connection) -> dict[str, Any]:
    """How the current default profile scores: its steps and versions, layer 1's rules, layer 2's judge."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT profile_code, profile_version, step, component_name, component_version, models, enabled_rules"
            " FROM ops.v_profile WHERE is_default AND profile_status = 'active'"
            " ORDER BY string_to_array(ltrim(profile_version, 'V'), '.')::int[] DESC, step"
        )
        steps = cur.fetchall()
        version = steps[0]["profile_version"] if steps else None
        steps = [s for s in steps if s["profile_version"] == version]
        cur.execute(
            "SELECT r.rule_code, cvr.ordinal, cvr.enabled, rc.label_de, rc.label_fr, r.description"
            " FROM ops.v_profile p"
            " JOIN ops.component_version_rule cvr ON cvr.component_version_id = p.component_version_id"
            " JOIN ops.rule r ON r.rule_id = cvr.rule_id LEFT JOIN ops.reason_code rc ON rc.code = r.rule_code"
            " WHERE p.is_default AND p.profile_version = %s AND p.step = 'layer1_filter' ORDER BY cvr.ordinal",
            [version],
        )
        rules = cur.fetchall()
        cur.execute(
            "SELECT role, version_label, status FROM ops.prompt_version WHERE role LIKE 'layer2_judge.%%'"
            " ORDER BY version_label DESC LIMIT 1"
        )
        prompt = cur.fetchone()
        cur.execute(
            "SELECT cv.config FROM ops.v_profile p"
            " JOIN ops.component_version cv ON cv.component_version_id = p.component_version_id"
            " WHERE p.is_default AND p.profile_version = %s AND p.step = 'layer2_judge' LIMIT 1",
            [version],
        )
        judge = cur.fetchone()
        scorer_rules: list[dict[str, Any]] = []
        intercept = None
        config = judge["config"] if judge and isinstance(judge["config"], dict) else {}
        weights = config.get("rule_weights")
        if isinstance(weights, dict) and weights:
            cur.execute(
                "SELECT r.rule_code, r.definition ->> 'feature' AS feature, r.definition ->> 'source' AS source"
                " FROM ops.v_profile p"
                " JOIN ops.component_version_rule cvr ON cvr.component_version_id = p.component_version_id"
                " JOIN ops.rule r ON r.rule_id = cvr.rule_id"
                " WHERE p.is_default AND p.profile_version = %s AND p.step = 'layer2_judge'",
                [version],
            )
            codes = {x["feature"]: x for x in cur.fetchall()}
            apertus = set(config.get("apertus_rules") or [])
            intercept = _number(config.get("intercept"))
            for feature in config.get("features") or list(weights):
                w = weights.get(feature) or {}
                registered = codes.get(feature) or {}
                weight = _number(w.get("weight"))
                scorer_rules.append(
                    {
                        "rule": registered.get("rule_code") or feature,
                        "feature": feature,
                        "source": registered.get("source") or ("apertus" if feature in apertus else "code"),
                        "direction": _direction({"direction": w.get("sign")}, {"contribution": weight}),
                        "weight": weight,
                        "effect": 0,
                        "share": None,
                    }
                )
    return {
        "profile": None if version is None else {"code": steps[0]["profile_code"], "version": version},
        "steps": steps,
        "layer1_rules": rules,
        "layer2": {
            "prompt": prompt,
            "score": "100 x P(Ja) / (P(Ja) + P(Nein)), read from the first token's log-probabilities",
            "score_raw": "ln P(Ja) - ln P(Nein) (the logit), used to order ties",
            "label": "always potentially: only a ranking step decides in_scope (D-063, D-021)",
        },
        "rules": scorer_rules,
        "intercept": intercept,
    }


def recent_runs(conn: psycopg.Connection, limit: int = 20) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT r.run_id, r.kind, r.status, r.mode, r.started_at, r.finished_at, r.triggered_by, r.actor,"
            " (SELECT m.value FROM ops.run_metric m WHERE m.run_id = r.run_id AND m.metric_code = 'replay_misses'"
            "  LIMIT 1) AS replay_misses"
            " FROM ops.pipeline_run r ORDER BY r.started_at DESC LIMIT %s",
            [limit],
        )
        return [{**r, "run_id": str(r["run_id"])} for r in cur.fetchall()]
