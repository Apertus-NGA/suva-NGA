"""FastAPI over the six-schema database. The compose app service supplies the suva_api login."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from threading import BoundedSemaphore
from typing import Annotated, Literal
from uuid import UUID

import psycopg
from fastapi import FastAPI, HTTPException, Query
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from src.db import pg

app = FastAPI(title="Suva case-law API")
# The compose service runs a single Uvicorn process. Leave headroom under the login's 20-connection limit.
_sessions = BoundedSemaphore(12)


@contextmanager
def session(*, read_only: bool = True) -> Iterator[psycopg.Connection]:
    if not _sessions.acquire(blocking=False):
        raise HTTPException(503, "API database connections are busy")
    try:
        with pg.connect(actor="expert", pipeline=False) as conn:
            if conn.info.user != "suva_api":
                raise HTTPException(503, "The API database login must be suva_api")
            conn.row_factory = dict_row
            if read_only:
                conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            yield conn
    except (psycopg.OperationalError, pg.DatabaseNotConfigured) as exc:
        raise HTTPException(503, "Database unavailable") from exc
    finally:
        _sessions.release()


_RULINGS = """
    SELECT r.ruling_id AS id, r.docket, r.decision_date, r.publication_date, r.publication_date_approx,
           r.publication_quality, r.court, r.language, r.gegenstand AS subject, r.bger_url,
           s.assessment_id, s.pipeline_label, s.step, s.mode, s.score_0_100 AS score, a.score_raw,
           s.reason_code, s.reason_label_de, s.reason_label_fr, s.explanation_de,
           jsonb_build_object('verdict', s.expert_verdict, 'label', s.expert_implied_label,
                              'at', s.reviewed_at, 'stale', s.review_is_stale) AS expert,
           ss.summary_id IS NOT NULL AS has_summary,
           COALESCE(ss.expert_verdict = 'validated', false) AS summary_validated,
           CASE WHEN NOT s.review_is_stale AND s.expert_implied_label = 'in_scope' THEN 'expert_relevant'
                WHEN NOT s.review_is_stale AND s.expert_implied_label = 'out_of_scope' THEN 'expert_not_relevant'
                WHEN s.pipeline_label = 'in_scope' THEN 'ai_relevant'
                WHEN s.pipeline_label = 'potentially' THEN 'potentially_relevant'
                WHEN s.pipeline_label = 'out_of_scope' AND (s.step = 'layer1_filter' OR s.score_source = 'net')
                    THEN 'filtered_out'
                WHEN s.pipeline_label = 'out_of_scope' THEN 'ai_not_relevant'
                ELSE 'not_assessed' END AS status
    FROM corpus.v_ruling r
    LEFT JOIN triage.v_scope_current s ON s.ruling_id = r.ruling_id
    LEFT JOIN triage.assessment a ON a.assessment_id = s.assessment_id
    LEFT JOIN summ.v_summary_current ss ON ss.ruling_id = r.ruling_id AND ss.preset_code = 'suva_house'
"""


@app.get("/api/health")
def health():
    with session() as conn:
        current = conn.execute("""SELECT run_id, kind, started_at, mode FROM ops.pipeline_run
                                  WHERE status = 'running' ORDER BY started_at DESC""").fetchall()
    return {"ok": True, "mode": os.environ.get("MODE", "replay").upper(), "current_runs": current}


@app.get("/api/rulings")
def rulings(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort: Literal["score", "decision_date", "publication_date", "docket", "status"] = "decision_date",
    order: Literal["asc", "desc"] = "desc",
    court: Annotated[list[str] | None, Query()] = None,
    language: Annotated[list[Literal["de", "fr", "it"]] | None, Query()] = None,
    status: Annotated[
        list[
            Literal[
                "expert_relevant",
                "expert_not_relevant",
                "ai_relevant",
                "potentially_relevant",
                "filtered_out",
                "ai_not_relevant",
                "not_assessed",
            ]
        ]
        | None,
        Query(),
    ] = None,
    q: str | None = None,
    decided_from: date | None = None,
    decided_to: date | None = None,
    published_from: date | None = None,
    published_to: date | None = None,
    score_min: Annotated[float | None, Query(ge=0, le=100)] = None,
    score_max: Annotated[float | None, Query(ge=0, le=100)] = None,
    has_summary: bool | None = None,
):
    conditions, params = [], []
    for column, values in (("court", court), ("language::text", language), ("status", status)):
        if values:
            conditions.append(f"{column} = ANY(%s)")
            params.append(values)
    pubdate = "coalesce(publication_date, publication_date_approx)"
    for column, lower, upper in (
        ("decision_date", decided_from, decided_to),
        (pubdate, published_from, published_to),
        ("score", score_min, score_max),
    ):
        if lower is not None and upper is not None and lower > upper:
            raise HTTPException(422, "Range start exceeds range end")
        for operator, value in ((">=", lower), ("<=", upper)):
            if value is not None:
                conditions.append(f"{column} {operator} %s")
                params.append(value)
    if q:
        conditions.append("(strpos(lower(docket), lower(%s)) > 0 OR strpos(lower(subject), lower(%s)) > 0)")
        params.extend([q, q])
    if has_summary is not None:
        conditions.append("has_summary = %s")
        params.append(has_summary)
    source = f" FROM ({_RULINGS}) rows"
    if conditions:
        source += " WHERE " + " AND ".join(conditions)
    ordering = {"publication_date": pubdate, "score": f"score {order} NULLS LAST, score_raw"}.get(sort, sort)
    with session() as conn:
        total = conn.execute("SELECT count(*) AS total" + source, params).fetchone()["total"]
        items = conn.execute(
            "SELECT *" + source + f" ORDER BY {ordering} {order} NULLS LAST, id LIMIT %s OFFSET %s",
            [*params, limit, offset],
        ).fetchall()
    return {"total": total, "items": items}


@app.get("/api/rulings/{ruling_id}")
def ruling(ruling_id: UUID):
    with session() as conn:
        row = conn.execute(_RULINGS + " WHERE r.ruling_id = %s", (ruling_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Ruling not found")
        primary = conn.execute(
            """SELECT t.text_id, t.source AS text_source, t.content AS text
                                  FROM corpus.v_ruling r LEFT JOIN corpus.ruling_text t ON t.text_id = r.primary_text_id
                                  WHERE r.ruling_id = %s""",
            (ruling_id,),
        ).fetchone()
        trace = conn.execute(
            """SELECT t.*, pr.status AS run_status, pr.started_at, a.created_at,
                      coalesce(m.value, 0)::bigint AS replay_misses, j.truncation, pv.version_label AS prompt_version
               FROM triage.v_scope_trace t JOIN ops.pipeline_run pr USING (run_id)
               JOIN triage.assessment a ON a.assessment_id = t.assessment_id
               LEFT JOIN triage.llm_judgement j ON j.assessment_id = t.assessment_id
               LEFT JOIN ops.prompt_version pv ON pv.prompt_version_id = j.prompt_version_id
               LEFT JOIN ops.run_metric m ON m.run_id = t.run_id AND m.step = t.step AND m.metric_code = 'replay_misses'
               WHERE t.ruling_id = %s ORDER BY t.hop""",
            (ruling_id,),
        ).fetchall()
        ledger = []
        for step in trace:
            if step["step"] == "layer1_filter":
                ledger = conn.execute(
                    """SELECT rule_code AS rule, label_de, label_fr, effect, outcome,
                                         is_decisive AS decisive, evidence_field AS field, matched_text,
                                         char_start, char_end, input_text_id AS text_id FROM triage.v_layer1_ledger
                                         WHERE assessment_id = %s AND outcome = 'fired' ORDER BY ordinal""",
                    (step["assessment_id"],),
                ).fetchall()
        texts = conn.execute(
            """SELECT t.language, t.title_line, t.body, s.summary_version_id, s.version_no AS version, s.origin,
                      s.quality_status, s.mode, COALESCE(s.expert_verdict = 'validated', false) AS validated,
                      CASE WHEN s.expert_verdict = 'validated' THEN s.reviewed_at END AS validated_at
               FROM summ.v_summary_current s JOIN summ.summary_text t USING (summary_version_id)
               WHERE s.ruling_id = %s AND s.preset_code = 'suva_house'""",
            (ruling_id,),
        ).fetchall()
        summaries = {"de": None, "fr": None}
        for entry in texts:
            summaries[entry["language"]] = entry
        request = conn.execute(
            """SELECT request_id, status FROM ops.user_request WHERE kind = 'summary'
               AND ruling_id = %s AND preset_code = 'suva_house' ORDER BY created_at DESC, request_id DESC LIMIT 1""",
            (ruling_id,),
        ).fetchone()
        reference = conn.execute(
            "SELECT text_de AS de, text_fr AS fr FROM gold.suva_summary WHERE ruling_id = %s "
            "ORDER BY created_at DESC, suva_summary_id DESC LIMIT 1",
            (ruling_id,),
        ).fetchone()
    current = trace[0] if trace else None
    judge = next((entry for entry in trace if entry["step"] == "layer2_judge"), None)
    return {
        "ruling": row,
        "summaries": summaries,
        "summary_request": request,
        "reference": reference,
        **primary,
        "relevance": {
            "state": "scored" if row["score"] is not None else ("assessed" if current else "not_assessed"),
            "step": row["step"],
            "run": (
                {
                    "run_id": current["run_id"],
                    "status": current["run_status"],
                    "mode": current["mode"],
                    "created_at": current["created_at"],
                    "replay_misses": current["replay_misses"],
                }
                if current
                else None
            ),
            "layer2": (
                {
                    "model": judge["served_model"],
                    "prompt_version": judge["prompt_version"],
                    "p_yes": judge["p_yes"],
                    "truncation": judge["truncation"],
                    "llm_call_id": judge["llm_call_id"],
                }
                if judge
                else None
            ),
            "rules": [],
            "label": row["pipeline_label"],
            "score": row["score"],
            "score_raw": row["score_raw"],
            "explanation_de": row["explanation_de"],
            "layer1": ledger,
            "trace": trace,
        },
    }


class AddJudgement(BaseModel):
    kind: Literal["add_judgement"]
    docket: str | None = Field(default=None, pattern=r"^[0-9]{1,2}[A-Z]_[0-9]+/[0-9]{4}$")
    bger_url: str | None = None


def submit(kind, *, docket=None, bger_url=None, ruling_id=None, preset=None):
    with session(read_only=False) as conn:
        if ruling_id and not conn.execute("SELECT 1 FROM corpus.ruling WHERE ruling_id = %s", (ruling_id,)).fetchone():
            raise HTTPException(404, "Ruling not found")
        row = conn.execute(
            "SELECT ops.submit_request(%s, %s, %s, %s, %s) AS request_id", (kind, docket, bger_url, ruling_id, preset)
        ).fetchone()
    return {**row, "status": "pending"}


@app.post("/api/requests", status_code=202)
def add_judgement(request: AddJudgement):
    if not (request.docket or request.bger_url):
        raise HTTPException(422, "Supply a docket or a bger.ch URL")
    if request.bger_url:
        from urllib.parse import urlsplit

        try:
            url = urlsplit(request.bger_url)
            valid = (
                url.scheme == "https"
                and url.hostname
                and (url.hostname == "bger.ch" or url.hostname.endswith(".bger.ch"))
            )
        except ValueError:
            valid = False
        if not valid:
            raise HTTPException(422, "Expected an HTTPS bger.ch URL")
    return submit(request.kind, docket=request.docket, bger_url=request.bger_url)


@app.post("/api/rulings/{ruling_id}/summaries", status_code=202)
def request_summary(ruling_id: UUID):
    return submit("summary", ruling_id=ruling_id, preset="suva_house")


@app.get("/api/requests/{request_id}")
def request_status(request_id: UUID):
    with session() as conn:
        row = conn.execute(
            """SELECT request_id, status, run_id, ruling_id, status_detail FROM ops.user_request
                              WHERE request_id = %s""",
            (request_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Request not found")
    return row
