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
from fastapi.staticfiles import StaticFiles

from suva_data import db

from . import queries

WEB_DIST = Path(__file__).resolve().parents[1] / "web" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    with db.connect() as conn:
        db.migrate(conn)
    yield


app = FastAPI(title="Suva Rechtsprechung", lifespan=lifespan)


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
    starred: bool | None = None,
    predicted_relevant: bool | None = None,
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
        outcomes=outcome, labels=_one_of("label", label, queries.LABELS), starred=starred,
        predicted_relevant=predicted_relevant, score_min=score_min, score_max=score_max, q=q,
    )
    return queries.list_rulings(conn, filters, sort=sort, order=order, limit=limit, offset=offset)


if WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
