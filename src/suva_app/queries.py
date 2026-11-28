"""Read queries behind the ruling list. Plain SQL on a psycopg connection, no web framework in here.

Two things the raw tables do not give directly:

- area: rulings not yet seen on a bger.ch list have `area` NULL, but their subject line starts with it
  ("Unfallversicherung (Prozessvoraussetzung)"), so the area shown is coalesce(area, that prefix).
- topic: the area is written in the ruling's language. The three areas at the core of Suva's work are
  mapped to one code each (UV accident, MV military, IV invalidity insurance), as in research/common.py.

- title: the court's subject line is "<area> (<keywords>)". The area is shown on its own, so the title a
  lawyer scans is the keywords ("Kausalzusammenhang; Invalidenrente"). See display_title.

Scores are stored 0..1 and shown 0..100.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from psycopg.rows import dict_row

TOPICS = ("UV", "MV", "IV")
# The status of a ruling, from what an expert decided or, failing that, what the system assessed.
STATUSES = ("not_assessed", "potentially_relevant", "ai_relevant", "expert_confirmed", "not_relevant")
STATUS_SQL = """CASE WHEN label = 'relevant' THEN 'expert_confirmed'
                     WHEN label = 'not_relevant' THEN 'not_relevant'
                     WHEN predicted_relevant THEN 'ai_relevant'
                     WHEN predicted_relevant IS NOT NULL THEN 'potentially_relevant'
                     ELSE 'not_assessed' END"""
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
           r.field_sources ->> 'publication_date' AS publication_source,
           i.ingested_at,
           coalesce(i.ingested_at >= (SELECT max(started_at) FROM ingest_runs WHERE command = 'ingest'), false)
               AS is_new,  -- added by the latest update
           v.relevance AS label, v.basis AS label_basis,
           round(p.score * 100)::int AS score, p.relevant AS predicted_relevant,
           EXISTS (SELECT 1 FROM gold_summaries g WHERE g.ruling_id = r.id AND g.is_current) AS has_gold_summary,
           EXISTS (SELECT 1 FROM summaries s WHERE s.ruling_id = r.id AND s.is_current) AS has_summary
    FROM rulings r
    JOIN v_relevance v ON v.ruling_id = r.id
    LEFT JOIN predictions p ON p.ruling_id = r.id AND p.is_current
    LEFT JOIN ingested_rulings i ON i.docket = r.docket AND i.decision_date = r.decision_date
), list AS (
    SELECT base.*,
           CASE WHEN lower(area) ~ 'unfallversicherung|assurance-accident|infortuni' THEN 'UV'
                WHEN lower(area) ~ 'milit' THEN 'MV'
                WHEN lower(area) ~ 'invalid' THEN 'IV'
           END AS topic,
           {status} AS status
    FROM base
)
""".replace("{status}", STATUS_SQL)


@dataclass
class RulingFilters:
    """Every field is optional; empty means "do not filter on this"."""

    decided_from: date | None = None
    decided_to: date | None = None
    published_from: date | None = None
    published_to: date | None = None
    divisions: list[str] = field(default_factory=list)
    areas: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)  # UV / MV / IV
    languages: list[str] = field(default_factory=list)
    outcomes: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)  # relevant / not_relevant / unknown (human labels)
    statuses: list[str] = field(default_factory=list)  # see STATUSES
    starred: bool | None = None  # marked for publication in the official collection
    predicted_relevant: bool | None = None  # the system's decision
    ingested: bool | None = None  # added by a live update (True) / part of the base dataset
    # The inbox: assessed relevant and not reviewed, or added by the latest update and not decided by an expert.
    inbox: bool | None = None
    summarised: bool | None = None  # has a summary: Suva's reference one or a generated one
    score_min: int | None = None  # 0..100
    score_max: int | None = None
    q: str | None = None  # case number or subject contains


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
    for column, values in (
        ("division", f.divisions),
        ("area", f.areas),
        ("topic", f.topics),
        ("language", f.languages),
        ("outcome", f.outcomes),
        ("label", f.labels),
        ("status", f.statuses),
    ):
        if values:
            add(f"{column} = ANY(%s)", list(values))
    if f.starred is not None:
        add("starred = %s", f.starred)
    if f.predicted_relevant is not None:
        add("predicted_relevant = %s", f.predicted_relevant)
    if f.summarised is not None:
        add("(has_gold_summary OR has_summary)" if f.summarised else "NOT (has_gold_summary OR has_summary)")
    if f.ingested is not None:
        add("ingested_at IS NOT NULL" if f.ingested else "ingested_at IS NULL")
    if f.inbox:
        add("(status = 'ai_relevant' OR (is_new AND label_basis IS DISTINCT FROM 'expert_override'))")
    if f.score_min is not None:
        add("score >= %s", f.score_min)
    if f.score_max is not None:
        add("score <= %s", f.score_max)
    if f.q and f.q.strip():
        # Escape LIKE wildcards so "8C_72" matches that text and not "8C" + any character + "72".
        needle = "%" + f.q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        add("(docket ILIKE %s OR subject ILIKE %s)", needle, needle)
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def list_rulings(
    conn,
    filters: RulingFilters | None = None,
    *,
    sort: str = "decision_date",
    order: str = "desc",
    limit: int = 50,
    offset: int = 0,
) -> dict:
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
    for item in items:
        item["title"] = display_title(item["subject"], item["area"])
    return {"total": total, "items": items}


def get_ruling(conn, ruling_id: int) -> dict | None:
    """One ruling as its page shows it, or None: the list's fields plus the text, the reason and the summaries.

    text            the canonical full text, tidied for reading (display_text); None when none is held
    explanation     why the current prediction says relevant or not; None without one
    suva_summaries  Suva's own summary per language: {"de": {"title", "body"} | None, "fr": ...}
    summaries       ours per language (model output or an expert's edit): {"headline", "body", "origin"} | None
    Suva's author field and link are never read here (D-051).
    """
    with conn.cursor(row_factory=dict_row) as cur:
        ruling = cur.execute(_BASE + "SELECT * FROM list WHERE id = %s", (ruling_id,)).fetchone()
        if ruling is None:
            return None
        text = cur.execute(
            "SELECT text FROM ruling_texts WHERE ruling_id = %s AND is_canonical", (ruling_id,)
        ).fetchone()
        prediction = cur.execute(
            "SELECT explanation FROM predictions WHERE ruling_id = %s AND is_current", (ruling_id,)
        ).fetchone()
        suva = cur.execute(
            "SELECT language, title, body FROM gold_summaries WHERE ruling_id = %s AND is_current", (ruling_id,)
        ).fetchall()
        ours = cur.execute(
            "SELECT language, headline, body, origin FROM summaries WHERE ruling_id = %s AND is_current", (ruling_id,)
        ).fetchall()
    ruling["title"] = display_title(ruling["subject"], ruling["area"])
    ruling["text"] = display_text(text["text"]) if text else None
    ruling["explanation"] = prediction["explanation"] if prediction else None
    for key, rows in (("suva_summaries", suva), ("summaries", ours)):
        by_language = {row.pop("language"): row for row in rows}
        ruling[key] = {language: by_language.get(language) for language in ("de", "fr")}
    return ruling


def display_text(text: str) -> str:
    """A stored ruling text made readable: the words and line breaks are kept, the layout noise is not.

    Sources give the text with no-break spaces, indented lines and runs of empty lines. Here every line is
    trimmed and several empty lines become one, so paragraphs are separated by exactly one empty line.
    The stored text itself is never changed.
    """
    lines = [line.strip() for line in text.replace("\xa0", " ").split("\n")]
    kept: list[str] = []
    for line in lines:
        if line or (kept and kept[-1]):
            kept.append(line)
    return "\n".join(kept).strip()


def display_title(subject: str | None, area: str | None) -> str | None:
    """What to show as a ruling's title, from the court's subject line. None when it says no more than the area.

    "Unfallversicherung (Fallabschluss; Kausalzusammenhang)" -> "Fallabschluss; Kausalzusammenhang"
    "Invalidenversicherung, Invalidenrente"                  -> "Invalidenrente"
    "Unfallversicherung"                                     -> None (the area is shown anyway)
    "Garantievertrag,"                                       -> "Garantievertrag"
    The words are the court's own: only the repeated area, stray end punctuation and a lower-case first
    letter are tidied. `subject` itself is returned unchanged next to it.
    """
    text = (subject or "").strip().rstrip(",;").strip()
    if area and text.startswith(area):
        rest = text[len(area) :].strip()
        if rest.startswith("(") and rest.endswith(")"):
            text = rest[1:-1].strip()
        elif rest[:1] in (",", ";", ":"):
            text = rest[1:].strip()
        elif not rest:
            text = ""
    return (text[:1].upper() + text[1:]) if text else None


def facets(conn) -> dict:
    """The values each filter can take, with counts over all rulings, and whether scores are placeholders."""
    with conn.cursor(row_factory=dict_row) as cur:

        def counted(column: str, order: str = "n DESC, value") -> list[dict]:
            return cur.execute(
                _BASE + f"SELECT {column} AS value, count(*) AS n FROM list WHERE {column} IS NOT NULL "
                f"GROUP BY 1 ORDER BY {order}"
            ).fetchall()

        ranges = cur.execute(
            """SELECT count(*) AS total, min(decision_date) AS decided_min, max(decision_date) AS decided_max,
                      min(publication_date) AS published_min, max(publication_date) AS published_max FROM rulings"""
        ).fetchone()
        scoring = cur.execute(
            """SELECT count(*) AS scored, coalesce(bool_or(coalesce((m.params ->> 'stub')::boolean, false)), false) AS
               stub
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
            "statuses": counted("status"),
        }


def learning(conn) -> dict:
    """What expert work has produced so far: the numbers behind the Learning page."""
    row = conn.execute(
        """SELECT
             (SELECT count(*) FROM v_relevance WHERE relevance = 'relevant'),
             (SELECT count(*) FROM labels WHERE label_set = 'expert_override' AND value = 'relevant'),
             (SELECT count(*) FROM labels WHERE label_set = 'expert_override' AND value = 'not_relevant'),
             (SELECT count(DISTINCT ruling_id) FROM gold_summaries WHERE is_current),
             (SELECT count(DISTINCT ruling_id) FROM summaries WHERE is_current AND origin = 'model'),
             (SELECT count(DISTINCT ruling_id) FROM summaries WHERE is_current AND confirmed_at IS NOT NULL),
             (SELECT count(*) FROM summary_events WHERE action = 'revise'),
             (SELECT count(*) FROM summary_events WHERE action = 'confirm' AND unchanged)"""
    ).fetchone()
    keys = ("relevant_rulings", "confirmed_by_experts", "rejected_by_experts", "reference_summaries",
            "generated_summaries", "expert_summaries", "revision_requests", "accepted_unchanged")  # fmt: skip
    reasons = conn.execute(
        "SELECT reason, count(*) FROM summary_events WHERE action = 'revise' GROUP BY 1 ORDER BY 2 DESC, 1"
    ).fetchall()
    # Which status each decision started from and ended in: the path, not only the result.
    transitions = conn.execute(
        """SELECT status_before, status_after, count(*) FROM relevance_events
           GROUP BY 1, 2 ORDER BY 3 DESC, 1, 2"""
    ).fetchall()
    return {
        **dict(zip(keys, row, strict=True)),
        "decisions": sum(n for *_, n in transitions),
        "transitions": [{"before": b, "after": a, "n": n} for b, a, n in transitions],
        "revision_reasons": [{"reason": r, "n": n} for r, n in reasons],
    }
