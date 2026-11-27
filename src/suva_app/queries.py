"""Read queries behind the ruling list. Plain SQL on a psycopg connection, no web framework in here.

Two things the raw tables do not give directly:

- area: rulings not yet seen on a bger.ch list have `area` NULL, but their subject line starts with it
  ("Unfallversicherung (Prozessvoraussetzung)"), so the area shown is coalesce(area, that prefix).
- topic: the area is written in the ruling's language. The three areas at the core of Suva's work are
  mapped to one code each (UV accident, MV military, IV invalidity insurance), as in research/common.py.

Scores are stored 0..1 and shown 0..100.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from psycopg.rows import dict_row

TOPICS = ("UV", "MV", "IV")
LABELS = ("relevant", "not_relevant", "unknown")
SORTS = {
    "decision_date": "decision_date",
    "publication_date": "publication_date",
    "docket": "docket",
    "area": "area",
    "score": "score",
}
MAX_PAGE_SIZE = 200

_BASE = """
WITH base AS (
    SELECT r.id, r.docket, r.decision_date, r.publication_date, r.division, r.language, r.starred,
           coalesce(r.area, nullif(split_part(r.subject, ' (', 1), '')) AS area,
           r.subject, r.outcome, r.official_url,
           v.relevance AS label, v.basis AS label_basis,
           round(p.score * 100)::int AS score, p.relevant AS predicted_relevant,
           EXISTS (SELECT 1 FROM gold_summaries g WHERE g.ruling_id = r.id AND g.is_current) AS has_gold_summary,
           EXISTS (SELECT 1 FROM summaries s WHERE s.ruling_id = r.id AND s.is_current) AS has_summary
    FROM rulings r
    JOIN v_relevance v ON v.ruling_id = r.id
    LEFT JOIN predictions p ON p.ruling_id = r.id AND p.is_current
), list AS (
    SELECT base.*,
           CASE WHEN lower(area) ~ 'unfallversicherung|assurance-accident|infortuni' THEN 'UV'
                WHEN lower(area) ~ 'milit' THEN 'MV'
                WHEN lower(area) ~ 'invalid' THEN 'IV'
           END AS topic
    FROM base
)
"""


@dataclass
class RulingFilters:
    """Every field is optional; empty means "do not filter on this"."""

    decided_from: date | None = None
    decided_to: date | None = None
    published_from: date | None = None
    published_to: date | None = None
    divisions: list[str] = field(default_factory=list)
    areas: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)       # UV / MV / IV
    languages: list[str] = field(default_factory=list)
    outcomes: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)       # relevant / not_relevant / unknown (human labels)
    starred: bool | None = None                            # marked for publication in the official collection
    predicted_relevant: bool | None = None                 # the system's decision
    score_min: int | None = None                           # 0..100
    score_max: int | None = None
    q: str | None = None                                   # case number or subject contains


def _where(f: RulingFilters) -> tuple[str, list]:
    clauses: list[str] = []
    params: list = []

    def add(sql: str, *values) -> None:
        clauses.append(sql)
        params.extend(values)

    if f.decided_from:
        add("decision_date >= %s", f.decided_from)
    if f.decided_to:
        add("decision_date <= %s", f.decided_to)
    if f.published_from:
        add("publication_date >= %s", f.published_from)
    if f.published_to:
        add("publication_date <= %s", f.published_to)
    for column, values in (("division", f.divisions), ("area", f.areas), ("topic", f.topics),
                           ("language", f.languages), ("outcome", f.outcomes), ("label", f.labels)):
        if values:
            add(f"{column} = ANY(%s)", list(values))
    if f.starred is not None:
        add("starred = %s", f.starred)
    if f.predicted_relevant is not None:
        add("predicted_relevant = %s", f.predicted_relevant)
    if f.score_min is not None:
        add("score >= %s", f.score_min)
    if f.score_max is not None:
        add("score <= %s", f.score_max)
    if f.q and f.q.strip():
        # Escape LIKE wildcards so "8C_72" matches that text and not "8C" + any character + "72".
        needle = "%" + f.q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        add("(docket ILIKE %s OR subject ILIKE %s)", needle, needle)
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def list_rulings(conn, filters: RulingFilters | None = None, *, sort: str = "decision_date", order: str = "desc",
                 limit: int = 50, offset: int = 0) -> dict:
    """One page of rulings plus the total number matching the filters: {"total": n, "items": [...]}."""
    if sort not in SORTS:
        raise ValueError(f"sort must be one of {sorted(SORTS)}, got {sort!r}")
    if order not in ("asc", "desc"):
        raise ValueError(f"order must be 'asc' or 'desc', got {order!r}")
    limit = max(1, min(int(limit), MAX_PAGE_SIZE))
    offset = max(0, int(offset))
    where, params = _where(filters or RulingFilters())
    # Missing values go last in both directions; the tie-break keeps pages stable.
    order_by = f"{SORTS[sort]} {order.upper()} NULLS LAST, decision_date DESC, docket ASC, id ASC"
    with conn.cursor(row_factory=dict_row) as cur:
        total = cur.execute(_BASE + "SELECT count(*) AS n FROM list" + where, params).fetchone()["n"]
        items = cur.execute(
            _BASE + "SELECT * FROM list" + where + f" ORDER BY {order_by} LIMIT %s OFFSET %s", [*params, limit, offset]
        ).fetchall()
    return {"total": total, "items": items}


def facets(conn) -> dict:
    """The values each filter can take, with counts over all rulings, and whether scores are placeholders."""
    with conn.cursor(row_factory=dict_row) as cur:
        def counted(column: str, order: str = "n DESC, value") -> list[dict]:
            return cur.execute(
                _BASE + f"SELECT {column} AS value, count(*) AS n FROM list WHERE {column} IS NOT NULL GROUP BY 1 ORDER BY {order}"
            ).fetchall()

        ranges = cur.execute(
            """SELECT count(*) AS total, min(decision_date) AS decided_min, max(decision_date) AS decided_max,
                      min(publication_date) AS published_min, max(publication_date) AS published_max FROM rulings"""
        ).fetchone()
        scoring = cur.execute(
            """SELECT count(*) AS scored, coalesce(bool_or(coalesce((m.params ->> 'stub')::boolean, false)), false) AS stub
               FROM predictions p JOIN model_runs m ON m.id = p.run_id WHERE p.is_current"""
        ).fetchone()
        return {
            **ranges,
            "scored": scoring["scored"],
            "stub_scores": scoring["stub"],
            "divisions": counted("division", "value"),
            "areas": counted("area"),
            "topics": counted("topic"),
            "languages": counted("language"),
            "outcomes": counted("outcome"),
            "labels": counted("label"),
        }
