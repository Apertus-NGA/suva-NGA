"""The FastAPI app: routes, request bodies, error mapping. SQL lives in queries.py (reads) and writes.py (writes).

    make serve            (python -m src.cli serve: uvicorn on API_HOST:API_PORT, default 127.0.0.1:8000)

Every error answers JSON {"detail": "..."}: 404 unknown id, 409 refused by the current state, 422 bad input,
403 runs not enabled, 503 database not configured or unreachable, 504 a query hit the statement timeout.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from typing import Annotated, Literal

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.db.pg import DatabaseNotConfigured

from . import queries, writes
from .db import ApiBusy, ApiDatabaseError, connect
from .runs import Launcher, RunAlreadyRunning, RunsDisabled
from .settings import Settings

UUID_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
RulingId = Annotated[str, Path(pattern=UUID_PATTERN, description="corpus.ruling.ruling_id (UUID)")]
RequestId = Annotated[str, Path(pattern=UUID_PATTERN, description="ops.user_request.request_id (UUID)")]
Language = Literal["de", "fr"]


def create_app(settings: Settings | None = None, launcher: Launcher | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(
        title="Suva case-law monitoring API",
        version="0.1.0",
        description="Rulings, relevance (layer 1, layer 2), expert decisions, summaries and pipeline runs. "
        "Reads the data layer of src/db/sql; writes only through its functions (docs/API.md).",
    )
    app.state.settings = settings
    app.state.db_slots = threading.BoundedSemaphore(settings.max_db_sessions)
    app.state.launcher = launcher or Launcher(settings)

    @app.exception_handler(DatabaseNotConfigured)
    async def _not_configured(_: Request, exc: DatabaseNotConfigured) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": f"the database is not configured: {exc}"})

    @app.exception_handler(ApiBusy)
    async def _busy(_: Request, exc: ApiBusy) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)}, headers={"Retry-After": "1"})

    @app.exception_handler(ApiDatabaseError)
    async def _unusable(_: Request, exc: ApiDatabaseError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(psycopg.errors.QueryCanceled)
    async def _timeout(_: Request, exc: psycopg.errors.QueryCanceled) -> JSONResponse:
        return JSONResponse(status_code=504, content={"detail": "the query took longer than the statement timeout"})

    @app.exception_handler(psycopg.OperationalError)
    async def _unreachable(_: Request, exc: psycopg.OperationalError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "the database connection failed"})

    _routes(app)
    return app


@contextmanager
def _session(request: Request, *, read_only: bool) -> Iterator[psycopg.Connection]:
    """A database session for one request, opened in the endpoint body so that FastAPI has validated the input first
    (a bad parameter answers 422 without touching the database)."""
    settings: Settings = request.app.state.settings
    slots: threading.BoundedSemaphore = request.app.state.db_slots
    if not slots.acquire(timeout=settings.db_wait_s):
        raise ApiBusy(f"all {settings.max_db_sessions} database sessions are busy: retry in a moment")
    try:
        conn = connect(settings, read_only=read_only)
        try:
            yield conn
        finally:
            conn.close()
    finally:
        slots.release()


class RelevanceDecision(BaseModel):
    action: Literal["mark_relevant", "mark_not_relevant", "reopen"]
    comment: str | None = Field(default=None, max_length=2000)
    token: str | None = Field(
        default=None, description="decision_token of the row the expert saw: 409 if the ruling changed since"
    )


class AddJudgement(BaseModel):
    docket: str | None = Field(default=None, examples=["8C_691/2024"])
    bger_url: str | None = None


class SummaryEdit(BaseModel):
    title_line: str | None = Field(default=None, max_length=500)
    body: str = Field(min_length=1, max_length=20_000)
    parent_version_id: str | None = Field(
        default=None, description="summary_version_id the expert edited: 409 if another version became current"
    )


class Validation(BaseModel):
    comment: str | None = Field(default=None, max_length=2000)


class RunRequest(BaseModel):
    mode: Literal["replay", "live"] | None = None
    limit: int | None = Field(default=None, ge=1)
    all: bool = False
    population: list[str] = Field(default_factory=list)


def _filters(
    q: str | None = None,
    decided_from: date | None = None,
    decided_to: date | None = None,
    published_from: date | None = None,
    published_to: date | None = None,
    court: Annotated[list[str] | None, Query()] = None,
    area: Annotated[list[Literal[queries.AREAS]] | None, Query()] = None,  # type: ignore[valid-type]
    core: bool = False,
    language: Annotated[list[Literal["de", "fr", "it"]] | None, Query()] = None,
    status: Annotated[list[Literal[queries.STATUSES]] | None, Query()] = None,  # type: ignore[valid-type]
    score_min: Annotated[float | None, Query(ge=0, le=100)] = None,
    score_max: Annotated[float | None, Query(ge=0, le=100)] = None,
    has_summary: bool | None = None,
    inbox: bool = False,
) -> queries.Filters:
    return queries.Filters(
        q=q or None,
        decided_from=decided_from,
        decided_to=decided_to,
        published_from=published_from,
        published_to=published_to,
        courts=court or [],
        areas=list(area or []),
        core=core,
        languages=list(language or []),
        statuses=list(status or []),
        score_min=score_min,
        score_max=score_max,
        has_summary=has_summary,
        inbox=inbox,
    )


Filters = Annotated[queries.Filters, Depends(_filters)]


def _threshold(request: Request) -> float | None:
    return request.app.state.settings.ai_relevant_min_score


def _routes(app: FastAPI) -> None:
    @app.get("/api/health", tags=["system"])
    def health(request: Request) -> dict:
        """The database is reachable, the mode of launched runs, the runs in progress."""
        settings: Settings = request.app.state.settings
        launcher: Launcher = request.app.state.launcher
        out = {"ok": True, "mode": settings.mode.upper(), "runs_enabled": settings.runs_enabled, "database": "ok"}
        try:
            with _session(request, read_only=True) as conn, conn.cursor() as cur:
                cur.execute("SELECT run_id::text, kind, started_at FROM ops.pipeline_run WHERE status = 'running'")
                out["running_runs"] = cur.fetchall()
        except (DatabaseNotConfigured, ApiDatabaseError, ApiBusy) as exc:
            return JSONResponse(status_code=503, content={**out, "ok": False, "database": str(exc)})
        out["job"] = launcher.status()["current"]
        return out

    @app.get("/api/rulings", tags=["rulings"])
    def list_rulings(
        request: Request,
        filters: Filters,
        sort: Literal["score", "decision_date", "publication_date", "docket", "status"] = "score",
        order: Literal["asc", "desc"] = "desc",
        limit: Annotated[int, Query(ge=1, le=queries.MAX_PAGE_SIZE)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict:
        """One page of rulings: {total, items: [RulingRow]}. Every ruling, assessed or not (status not_assessed)."""
        with _session(request, read_only=True) as conn:
            return queries.list_rulings(
                conn, filters, threshold=_threshold(request), sort=sort, order=order, limit=limit, offset=offset
            )

    @app.get("/api/facets", tags=["rulings"])
    def get_facets(request: Request, filters: Filters) -> dict:
        """Counts per court, area, language and status, each under every filter except its own."""
        with _session(request, read_only=True) as conn:
            return queries.facets(conn, filters, threshold=_threshold(request))

    @app.get("/api/rulings/{ruling_id}", tags=["rulings"])
    def get_ruling(request: Request, ruling_id: RulingId) -> dict:
        """One ruling: its row, its full text, why it has its label (layer 1 rules, layer 2), its summaries."""
        with _session(request, read_only=True) as conn:
            detail = queries.ruling_detail(conn, ruling_id, threshold=_threshold(request))
        if detail is None:
            raise HTTPException(404, f"no ruling with id {ruling_id}")
        return detail

    @app.post("/api/rulings/{ruling_id}/relevance", tags=["expert"])
    def decide_relevance(request: Request, ruling_id: RulingId, decision: RelevanceDecision) -> dict:
        """An expert marks the ruling relevant or not relevant, or takes the decision back (reopen). Append-only:
        stores what the expert saw (label, status, score) and what the expert gave. Returns the new RulingRow.
        With `token` (the row's decision_token), a ruling that changed since the page was loaded answers 409."""
        with _session(request, read_only=False) as conn:
            return _guard(
                lambda: writes.decide_relevance(
                    conn, ruling_id, decision.action, decision.comment, decision.token, threshold=_threshold(request)
                )
            )

    @app.post("/api/requests", status_code=202, tags=["requests"])
    def add_judgement(request: Request, body: AddJudgement) -> dict:
        """ "Add another judgement" by docket or bger.ch link (D-015). Recorded as pending; no runner processes
        requests yet."""
        with _session(request, read_only=False) as conn:
            return _guard(lambda: writes.submit_add_judgement(conn, body.docket, body.bger_url))

    @app.get("/api/requests/{request_id}", tags=["requests"])
    def get_request(request: Request, request_id: RequestId) -> dict:
        """A request's state: pending | accepted | done | failed | rejected."""
        with _session(request, read_only=True) as conn:
            return _guard(lambda: writes.get_request(conn, request_id))

    @app.post("/api/rulings/{ruling_id}/summaries", status_code=202, tags=["summaries"])
    def request_summary(request: Request, ruling_id: RulingId) -> dict:
        """Ask for the summaries of this ruling (preset suva_house). Recorded as pending; no runner yet."""
        with _session(request, read_only=False) as conn:
            return _guard(lambda: writes.submit_summary_request(conn, ruling_id))

    @app.put("/api/rulings/{ruling_id}/summaries/{language}", tags=["summaries"])
    def edit_summary(request: Request, ruling_id: RulingId, language: Language, body: SummaryEdit) -> dict:
        """An expert edit: a new version, the other language copied unchanged. 409 while no summary exists, or when
        `parent_version_id` is not the current version any more."""
        with _session(request, read_only=False) as conn:
            return _guard(
                lambda: writes.edit_summary(
                    conn, ruling_id, language, body.title_line, body.body, body.parent_version_id
                )
            )

    @app.post("/api/rulings/{ruling_id}/summaries/{language}/validate", tags=["summaries"])
    def validate_summary(
        request: Request, ruling_id: RulingId, language: Language, body: Validation | None = None
    ) -> dict:
        """Accept the current version as it is (today one review covers the DE + FR pair of a version)."""
        with _session(request, read_only=False) as conn:
            return _guard(lambda: writes.validate_summary(conn, ruling_id, body.comment if body else None))

    @app.post("/api/rulings/{ruling_id}/summaries/{language}/unvalidate", tags=["summaries"])
    def unvalidate_summary(request: Request, ruling_id: RulingId, language: Language) -> dict:
        with _session(request, read_only=False) as conn:
            return _guard(lambda: writes.unvalidate_summary(conn, ruling_id))

    @app.get("/api/rulings/{ruling_id}/summaries/{language}/versions", tags=["summaries"])
    def summary_versions(request: Request, ruling_id: RulingId, language: Language) -> list[dict]:
        with _session(request, read_only=True) as conn:
            return writes.summary_versions(conn, ruling_id)

    @app.get("/api/learning", tags=["expert"])
    def learning(request: Request) -> dict:
        """What the experts did: decisions and their transitions, summary edits and validations."""
        with _session(request, read_only=True) as conn:
            return queries.learning(conn)

    @app.get("/api/scoring", tags=["system"])
    def scoring(request: Request) -> dict:
        """How the default profile scores today: its steps, layer 1's rules, layer 2's judge."""
        with _session(request, read_only=True) as conn:
            return queries.scoring(conn)

    @app.get("/api/runs", tags=["pipeline"])
    def runs(request: Request) -> dict:
        """The job the API started (layer 1 then layer 2) and the latest runs of every step (ops.pipeline_run)."""
        with _session(request, read_only=True) as conn:
            recent = queries.recent_runs(conn)
        return {**request.app.state.launcher.status(), "recent": recent}

    @app.post("/api/runs", status_code=202, tags=["pipeline"])
    def start_run(request: Request, body: RunRequest) -> dict:
        """Start layer 1 then layer 2 in the background (the CLIs of make layer1 / make layer2). 409 while a job
        runs; 403 unless API_RUNS_ENABLED=1; a live run needs `limit` or `all`."""
        launcher: Launcher = request.app.state.launcher
        try:
            launcher.start(body.mode, body.limit, body.all, body.population)
        except RunsDisabled as exc:
            raise HTTPException(403, str(exc)) from exc
        except RunAlreadyRunning as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return launcher.status()


def _guard(call):
    try:
        return call()
    except writes.NotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except writes.Conflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def __getattr__(name: str):
    """`src.api.app:app` for uvicorn, built on first access so that importing this module needs no environment."""
    if name == "app":
        value = create_app()
        globals()["app"] = value
        return value
    raise AttributeError(name)
