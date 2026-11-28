"""HTTP API for the UI. Thin on purpose: parsing and status codes here, SQL in queries.py.

    uv run uvicorn suva_app.main:app --reload --port 8000

On startup the database migrations are applied (the published dump only contains the data-layer tables).
If the UI has been built (src/web/dist), it is served from the same process at "/".
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles

from suva_data import db

from . import feedback, queries, workspace
from .updates import UpdateRunning, Updates

WEB_DIST = Path(__file__).resolve().parents[1] / "web" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    with db.connect() as conn:
        db.migrate(conn)
    yield


app = FastAPI(title="Suva Rechtsprechung", lifespan=lifespan)
updates = Updates()


def get_conn():
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def _one_of(name: str, values: list[str], allowed) -> list[str]:
    bad = [v for v in values if v not in allowed]
    if bad:
        raise HTTPException(422, f"{name}: unknown value {bad[0]!r}; allowed: {', '.join(allowed)}")
    return values


@app.get("/api/health")
def health(conn=Depends(get_conn)) -> dict:
    return {"ok": True, "rulings": conn.execute("SELECT count(*) FROM rulings").fetchone()[0]}


@app.get("/api/facets")
def get_facets(conn=Depends(get_conn)) -> dict:
    return queries.facets(conn)


@app.get("/api/rulings")
def get_rulings(
    conn=Depends(get_conn),
    decided_from: date | None = None,
    decided_to: date | None = None,
    published_from: date | None = None,
    published_to: date | None = None,
    division: Annotated[list[str], Query()] = [],
    area: Annotated[list[str], Query()] = [],
    topic: Annotated[list[str], Query()] = [],
    language: Annotated[list[str], Query()] = [],
    outcome: Annotated[list[str], Query()] = [],
    label: Annotated[list[str], Query()] = [],
    status: Annotated[list[str], Query()] = [],
    starred: bool | None = None,
    predicted_relevant: bool | None = None,
    ingested: bool | None = None,
    summarised: bool | None = None,
    score_min: Annotated[int | None, Query(ge=0, le=100)] = None,
    score_max: Annotated[int | None, Query(ge=0, le=100)] = None,
    q: str | None = None,
    sort: str = "decision_date",
    order: str = "desc",
    limit: Annotated[int, Query(ge=1, le=queries.MAX_PAGE_SIZE)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    _one_of("sort", [sort], sorted(queries.SORTS))
    _one_of("order", [order], ("asc", "desc"))
    filters = queries.RulingFilters(
        decided_from=decided_from, decided_to=decided_to, published_from=published_from, published_to=published_to,
        divisions=division, areas=area, topics=_one_of("topic", topic, queries.TOPICS), languages=language,
        outcomes=outcome, labels=_one_of("label", label, queries.LABELS),
        statuses=_one_of("status", status, queries.STATUSES), starred=starred,
        predicted_relevant=predicted_relevant, ingested=ingested, summarised=summarised, score_min=score_min, score_max=score_max, q=q,
    )
    return queries.list_rulings(conn, filters, sort=sort, order=order, limit=limit, offset=offset)


@app.get("/api/rulings/{ruling_id}")
def get_ruling(ruling_id: int, conn=Depends(get_conn)) -> dict:
    """One ruling with its full text, the reason for its score and its summaries in German and French."""
    ruling = queries.get_ruling(conn, ruling_id)
    if ruling is None:
        raise HTTPException(404, f"no ruling with id {ruling_id}")
    return ruling


class RelevanceDecision(BaseModel):
    action: str  # confirm_relevant | mark_not_relevant | reopen
    reason: str | None = None
    comment: str | None = None


@app.post("/api/rulings/{ruling_id}/relevance")
def decide_relevance(ruling_id: int, decision: RelevanceDecision, conn=Depends(get_conn)) -> dict:
    """An expert confirms a ruling as relevant (a gold label), marks it not relevant, or takes a decision back."""
    try:
        return feedback.decide_relevance(conn, ruling_id, decision.action, decision.reason, decision.comment)
    except feedback.UnknownRuling as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


class SummaryText(BaseModel):
    body: str
    confirm: bool = False  # true = save and confirm as final (gold) in one step


class Revision(BaseModel):
    reason: str  # one of workspace.REVISIONS
    note: str | None = None


def _workspace(call):
    """Run a workspace action; turn its errors into HTTP answers."""
    try:
        return call()
    except workspace.NotFound as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except SystemExit as e:  # the summariser reports a gateway failure this way
        raise HTTPException(502, f"the model could not be reached: {e}") from e


@app.get("/api/rulings/{ruling_id}/workspace")
def get_workspace(ruling_id: int, conn=Depends(get_conn)) -> dict:
    """The ruling page with the summary workspace: facts, text, both summaries with version and state, revisions."""
    return _workspace(lambda: workspace.ruling_page(conn, ruling_id))


@app.post("/api/rulings/{ruling_id}/summaries")
def generate_summaries(ruling_id: int, conn=Depends(get_conn)) -> dict:
    """Write the German and French summary with Apertus (pipeline version 1). Takes up to a minute."""
    return _workspace(lambda: workspace.generate(conn, ruling_id))


@app.put("/api/rulings/{ruling_id}/summaries/{language}")
def save_summary(ruling_id: int, language: str, text: SummaryText, conn=Depends(get_conn)) -> dict:
    """Save the expert's text as a new version, optionally confirming it as final."""
    return _workspace(lambda: workspace.save_edit(conn, ruling_id, language, text.body, text.confirm))


@app.post("/api/rulings/{ruling_id}/summaries/{language}/confirm")
def confirm_summary(ruling_id: int, language: str, conn=Depends(get_conn)) -> dict:
    """Confirm the current summary as final: it becomes a gold summary."""
    return _workspace(lambda: workspace.confirm(conn, ruling_id, language))


@app.post("/api/rulings/{ruling_id}/summaries/{language}/unconfirm")
def unconfirm_summary(ruling_id: int, language: str, conn=Depends(get_conn)) -> dict:
    return _workspace(lambda: workspace.unconfirm(conn, ruling_id, language))


@app.post("/api/rulings/{ruling_id}/summaries/{language}/revise")
def revise_summary(ruling_id: int, language: str, revision: Revision, conn=Depends(get_conn)) -> dict:
    """Ask Apertus for one defined change; the reason is stored as labelled data."""
    return _workspace(lambda: workspace.revise(conn, ruling_id, language, revision.reason, revision.note))


@app.get("/api/learning")
def get_learning(conn=Depends(get_conn)) -> dict:
    return queries.learning(conn)


class UpdateRequest(BaseModel):
    """Both dates (publication dates, inclusive) for a chosen range; neither for "since the last update"."""

    published_from: date | None = None
    published_to: date | None = None


@app.get("/api/updates")
def get_updates(conn=Depends(get_conn)) -> dict:
    return updates.status(conn)


@app.post("/api/updates", status_code=202)
def start_update(request: UpdateRequest, conn=Depends(get_conn)) -> dict:
    """Start adding newly published rulings in the background. Add-only: nothing already stored is changed."""
    try:
        updates.start(
            conn,
            request.published_from.isoformat() if request.published_from else None,
            request.published_to.isoformat() if request.published_to else None,
        )
    except UpdateRunning as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return updates.status(conn)


if WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
