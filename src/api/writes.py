"""Write side of the API: only through the data layer's SECURITY DEFINER functions (gold.submit_review,
summ.create_expert_version, ops.submit_request), each with app.actor set by the session (src/api/db.py)."""

from __future__ import annotations

import re
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from . import queries


class NotFound(LookupError):
    """The ruling, summary or request does not exist."""


class Conflict(RuntimeError):
    """The request is valid but the current state refuses it (HTTP 409)."""


RELEVANCE_ACTIONS = {"mark_relevant": "relevant", "mark_not_relevant": "not_relevant", "reopen": "withdrawn"}
DOCKET = re.compile(r"^[0-9]{1,2}[A-Z]_[0-9]+/[0-9]{4}$")  # the DDL's own docket format (corpus.ruling)
PRESET = "suva_house"


def _db_message(exc: psycopg.Error) -> str:
    diag = getattr(exc, "diag", None)
    text = (diag.message_primary if diag and diag.message_primary else str(exc)).strip()
    return text.splitlines()[0] if text else type(exc).__name__


def _call(conn: psycopg.Connection, sql: str, args: list[Any]) -> Any:
    """Run one write function and commit; a refusal by the database (trigger, CHECK, RAISE) becomes a Conflict."""
    try:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            value = cur.fetchone()
        conn.commit()
    except (
        psycopg.errors.RaiseException,
        psycopg.errors.CheckViolation,
        psycopg.errors.ForeignKeyViolation,
        psycopg.errors.UniqueViolation,
        psycopg.errors.InvalidTextRepresentation,
    ) as exc:
        conn.rollback()
        raise Conflict(f"the database refused the change: {_db_message(exc)}") from exc
    return value


def _latest_scope_review(conn: psycopg.Connection, ruling_id: Any) -> dict[str, Any] | None:
    """The ruling's latest scope review that no other review supersedes (the one v_scope_current shows)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT r.review_id, r.verdict, r.assessment_id FROM gold.expert_review r"
            " JOIN triage.assessment a ON a.assessment_id = r.assessment_id"
            " WHERE r.target_kind = 'scope' AND a.ruling_id = %s"
            " AND NOT EXISTS (SELECT 1 FROM gold.expert_review s WHERE s.supersedes_review_id = r.review_id)"
            " ORDER BY r.created_at DESC LIMIT 1",
            [ruling_id],
        )
        return cur.fetchone()


def decide_relevance(
    conn: psycopg.Connection,
    ruling_id: str,
    action: str,
    comment: str | None,
    token: str | None = None,
    *,
    threshold: float | None,
) -> dict[str, Any]:
    """One append-only scope review: what the expert saw (label, status, score) and what the expert gave.
    `reopen` withdraws the latest decision (a review that supersedes it)."""
    verdict = RELEVANCE_ACTIONS[action]
    row = queries.one_ruling(conn, ruling_id, threshold=threshold)
    if row is None:
        raise NotFound(f"no ruling with id {ruling_id}")
    if row["assessment_id"] is None:
        raise Conflict("this ruling has not been assessed yet: there is no pipeline label to review")
    if token is not None and token != queries.decision_token(row):
        raise Conflict("the ruling changed since the page was loaded (new label or decision): reload it")
    latest = _latest_scope_review(conn, row["ruling_id"])
    if verdict == "withdrawn":
        if latest is None or latest["verdict"] == "withdrawn":
            raise Conflict("there is no expert decision on this ruling to take back")
        target, supersedes = latest["assessment_id"], latest["review_id"]
    else:
        target = row["assessment_id"]
        supersedes = latest["review_id"] if latest and latest["assessment_id"] == target else None
    payload = {
        "shown_status": row["status"],
        "shown_score_0_100": None if row["score_0_100"] is None else float(row["score_0_100"]),
        "shown_score_raw": row["score_raw"],
    }
    _call(
        conn,
        "SELECT gold.submit_review('scope', %s, %s::ops.review_verdict, %s::jsonb, %s, %s) AS review_id",
        [target, verdict, Jsonb(payload), comment, supersedes],
    )
    fresh = queries.one_ruling(conn, ruling_id, threshold=threshold)
    return queries.ruling_row(fresh)


def submit_add_judgement(conn: psycopg.Connection, docket: str | None, bger_url: str | None) -> dict[str, Any]:
    """ "Add another judgement" (D-015): recorded for the pipeline; nothing runs it yet (no request runner)."""
    docket = (docket or "").strip() or None
    bger_url = (bger_url or "").strip() or None
    if not docket and not bger_url:
        raise ValueError("give a docket (e.g. 8C_691/2024) or a bger.ch link")
    if docket and not DOCKET.match(docket):
        raise ValueError(f"{docket!r} is not a Federal Supreme Court docket (e.g. 8C_691/2024)")
    if bger_url and not (bger_url.startswith("https://") and ".bger.ch/" in bger_url):
        raise ValueError("the link must be an https link on bger.ch")
    value = _call(conn, "SELECT ops.submit_request('add_judgement', %s, %s, NULL, NULL) AS id", [docket, bger_url])
    return get_request(conn, value["id"])


def submit_summary_request(conn: psycopg.Connection, ruling_id: str) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM corpus.ruling WHERE ruling_id = %s::uuid", [ruling_id])
        if cur.fetchone() is None:
            raise NotFound(f"no ruling with id {ruling_id}")
    value = _call(conn, "SELECT ops.submit_request('summary', NULL, NULL, %s::uuid, %s) AS id", [ruling_id, PRESET])
    return get_request(conn, value["id"])


def get_request(conn: psycopg.Connection, request_id: Any) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT request_id, kind, docket, bger_url, ruling_id, preset_code, status, status_detail, run_id,"
            " created_at, updated_at FROM ops.user_request WHERE request_id = %s::uuid",
            [str(request_id)],
        )
        r = cur.fetchone()
    if r is None:
        raise NotFound(f"no request with id {request_id}")
    return {k: (str(v) if k in {"request_id", "ruling_id", "run_id"} and v is not None else v) for k, v in r.items()}


# --- summaries (layer 3 writes them; experts edit and validate them) ---------------------------------------------

_ABBREVIATIONS = re.compile(
    r"(?:\b(?:Art|Abs|lit|Ziff|Bst|E|Erw|consid|al|ch|let|cpv|cons|vgl|bzw|ff|S|p|Nr|no|BGE|ATF|DTF|i\.V\.m|z\.B|"
    r"u\.a|resp|cf|n|N)\.)$"
)


def split_sentences(body: str) -> list[tuple[int, str]]:
    """(paragraph number, sentence) of an edited text: paragraphs on blank lines, sentences after . ! ? followed by a
    capital letter, never after a legal abbreviation (Art., Abs., E., consid., al., BGE …)."""
    out: list[tuple[int, str]] = []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body.strip()) if p.strip()]
    for number, paragraph in enumerate(paragraphs, start=1):
        text = " ".join(paragraph.split())
        start = 0
        for m in re.finditer(r"[.!?](?=\s+[«\"(]?[A-ZÄÖÜÀ-Ý])", text):
            head = text[start : m.end()]
            if _ABBREVIATIONS.search(head):
                continue
            out.append((number, head.strip()))
            start = m.end()
        tail = text[start:].strip()
        if tail:
            out.append((number, tail))
    return out


def _current_summary(conn: psycopg.Connection, ruling_id: str) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM summ.v_summary_current WHERE ruling_id = %s::uuid ORDER BY is_mandatory DESC, preset_code"
            " LIMIT 1",
            [ruling_id],
        )
        r = cur.fetchone()
    if r is None:
        raise Conflict("this ruling has no summary yet (layer 3 writes them; request one first)")
    return r


def edit_summary(
    conn: psycopg.Connection,
    ruling_id: str,
    language: str,
    title_line: str | None,
    body: str,
    parent_version_id: str | None = None,
) -> dict[str, Any]:
    """An expert edit (summ.create_expert_version): a new version, the other language copied unchanged.
    A sentence identical to one of the current text keeps its section and citations; a changed sentence keeps the
    section of the sentence before it and no citation; the database marks every edited claim flagged until the
    verifier reruns."""
    if not body.strip():
        raise ValueError("the summary text is empty")
    current = _current_summary(conn, ruling_id)
    if parent_version_id is not None and parent_version_id != str(current["summary_version_id"]):
        raise Conflict("another version of this summary became current since the page was loaded: reload it")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT c.claim_id, c.section, c.rendered_text,"
            " coalesce(array_agg(cc.consideration_id::text ORDER BY cc.ordinal) FILTER (WHERE cc.claim_id IS NOT NULL),"
            " '{}') AS cites"
            " FROM summ.summary_text t JOIN summ.summary_claim c ON c.summary_text_id = t.summary_text_id"
            " LEFT JOIN summ.claim_citation cc ON cc.claim_id = c.claim_id"
            " WHERE t.summary_version_id = %s AND t.language = %s GROUP BY c.claim_id ORDER BY min(c.ordinal)",
            [current["summary_version_id"], language],
        )
        old = cur.fetchall()
    by_text = {" ".join((c["rendered_text"] or "").split()): c for c in old}
    section = old[0]["section"] if old else "facts"
    claims = []
    for paragraph_no, sentence in split_sentences(body):
        same = by_text.get(sentence)
        if same:
            section = same["section"]
            claims.append(
                {
                    "paragraph_no": paragraph_no,
                    "section": section,
                    "text": sentence,
                    "edited_from_claim_id": str(same["claim_id"]),
                    "cites": list(same["cites"]),
                }
            )
        else:
            claims.append({"paragraph_no": paragraph_no, "section": section, "text": sentence, "cites": []})
    title = (title_line or "").strip() or current[f"title_{language}"]
    _call(
        conn,
        "SELECT summ.create_expert_version(%s, %s::ops.lang_code, %s, %s, %s::jsonb) AS id",
        [current["summary_version_id"], language, title, body.strip(), Jsonb(claims)],
    )
    return queries.summaries(conn, current["ruling_id"])


def _latest_summary_review(conn: psycopg.Connection, version_id: Any) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT review_id, verdict FROM gold.v_expert_review_current"
            " WHERE target_kind = 'summary_version' AND summary_version_id = %s",
            [version_id],
        )
        return cur.fetchone()


def validate_summary(conn: psycopg.Connection, ruling_id: str, comment: str | None) -> dict[str, Any]:
    """The expert accepts the current version (both languages) as it is: a `validated` review, recorded even when
    the text is unchanged."""
    current = _current_summary(conn, ruling_id)
    latest = _latest_summary_review(conn, current["summary_version_id"])
    _call(
        conn,
        "SELECT gold.submit_review('summary_version', %s, 'validated', '{}'::jsonb, %s, %s) AS id",
        [current["summary_version_id"], comment, latest["review_id"] if latest else None],
    )
    return queries.summaries(conn, current["ruling_id"])


def unvalidate_summary(conn: psycopg.Connection, ruling_id: str) -> dict[str, Any]:
    current = _current_summary(conn, ruling_id)
    latest = _latest_summary_review(conn, current["summary_version_id"])
    if latest is None or latest["verdict"] != "validated":
        raise Conflict("the current summary is not validated")
    _call(
        conn,
        "SELECT gold.submit_review('summary_version', %s, 'withdrawn', '{}'::jsonb, NULL, %s) AS id",
        [current["summary_version_id"], latest["review_id"]],
    )
    return queries.summaries(conn, current["ruling_id"])


def summary_versions(conn: psycopg.Connection, ruling_id: str) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT v.summary_version_id, v.version_no, v.origin, v.created_at, v.creator_kind, v.creator_actor,"
            " v.quality_status, v.is_current, v.mode, rv.verdict AS review"
            " FROM summ.summary s JOIN summ.summary_version v ON v.summary_id = s.summary_id"
            " LEFT JOIN gold.v_expert_review_current rv"
            "   ON rv.target_kind = 'summary_version' AND rv.summary_version_id = v.summary_version_id"
            " WHERE s.ruling_id = %s::uuid AND s.preset_code = %s ORDER BY v.version_no DESC",
            [ruling_id, PRESET],
        )
        rows = cur.fetchall()
    return [
        {
            "summary_version_id": str(r["summary_version_id"]),
            "version": r["version_no"],
            "origin": r["origin"],
            "created_at": r["created_at"],
            "creator": r["creator_actor"] or r["creator_kind"],
            "quality_status": r["quality_status"],
            "is_current": r["is_current"],
            "mode": r["mode"],
            "validated": r["review"] == "validated",
        }
        for r in rows
    ]
