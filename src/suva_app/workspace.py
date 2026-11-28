"""The ruling page and the summary workspace: read a ruling, generate, revise, edit and confirm its summaries.

Every action is recorded in `summary_events` (append-only) in the same transaction as the change, so the
path of a summary (model draft -> revision asked "shorter" -> expert edit -> confirmed) can be read back.
A confirmed summary is gold: it is the expert's word, whether they edited the text or accepted it as written.
"""

from __future__ import annotations

import sys
from collections.abc import Callable

from psycopg.types.json import Jsonb

from suva_data import config

if str(config.REPO) not in sys.path:  # src/summarize lives at the repository root
    sys.path.insert(0, str(config.REPO))

from src.llm.client import ReplayMiss  # noqa: E402, F401  (main.py maps it to 503)
from src.llm.config import ConfigError  # noqa: E402, F401  (main.py maps it to 503)
from src.summarize import finish, pipeline, summarize  # noqa: E402
from src.summarize.prompts import VERSION as PROMPT_VERSION  # noqa: E402
from src.summarize.prompts import system_prompt  # noqa: E402

from . import feedback  # noqa: E402

ACTOR = "expert"
LANGUAGES = ("de", "fr")
Ask = Callable[[list[dict]], str]

# What each revision button asks Apertus to do. Chosen from faults measured on generated fiches (27-28 Nov 2026).
REVISIONS = {
    "shorter": "Make it shorter. Keep every legal rule and every reference; cut repetition and facts the rule does not need.",  # noqa: E501
    "more_detail": "It is too thin. Add the rule the court applies and how it applied it in this case, from the ruling only.",  # noqa: E501
    "rule_first": "It retells the case. Rewrite it so that it leads with the legal rule the court states, "
    "then only the facts needed to understand that rule.",
    "key_point": "It is built around the wrong point or misses the main one. Rebuild it around the legal question "
    "the expert names below, as the ruling decides it.",
    "cite_considerations": "After each rule, add the consideration it comes from in brackets, "
    "using only consideration numbers that appear in the ruling.",
    "terminology": "Correct the legal terms and abbreviations so that they are the ones the law and the ruling use "
    "in this language. Change nothing else.",
    "align_languages": "Make it say the same as the fiche in the other language given below, paragraph by paragraph, "
    "in correct legal wording of this language. It is not a word-for-word translation.",
    "wrong_statement": "It contains a statement the ruling does not support. Remove or correct the statement "
    "the expert names below, checking it against the ruling. Change nothing else.",
    "other": "Follow the expert's instruction below. Change nothing else.",
}
NEEDS_NOTE = ("key_point", "wrong_statement", "other")


class NotFound(LookupError):
    pass


def _default_ask(messages: list[dict]) -> str:
    summarize.load_env()
    return summarize.chat(messages)


def _current(conn, ruling_id: int, language: str):
    return conn.execute(
        """SELECT id, version, origin, body, confirmed_at FROM summaries
           WHERE ruling_id = %s AND language = %s AND is_current""",
        (ruling_id, language),
    ).fetchone()


def _add_version(
    conn, ruling_id: int, language: str, body: str, origin: str, *, run_id=None, parent_id=None, confirm=False
) -> int:
    """Insert a new current version (the previous one stays in the table). Returns its id."""
    if not body or not body.strip():
        raise ValueError("a summary cannot be empty")
    version = conn.execute(
        "SELECT coalesce(max(version), 0) + 1 FROM summaries WHERE ruling_id = %s AND language = %s",
        (ruling_id, language),
    ).fetchone()[0]
    conn.execute(
        "UPDATE summaries SET is_current = false WHERE ruling_id = %s AND language = %s AND is_current",
        (ruling_id, language),
    )
    return conn.execute(
        """INSERT INTO summaries (ruling_id, language, body, origin, run_id, parent_id, version, created_by,
                                  confirmed_at, confirmed_by)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CASE WHEN %s THEN now() END, CASE WHEN %s THEN %s END)
           RETURNING id""",
        (ruling_id, language, body.strip(), origin, run_id, parent_id, version,
         ACTOR if origin == "expert" else "pipeline", confirm, confirm, ACTOR),
    ).fetchone()[0]  # fmt: skip


def _event(
    conn, ruling_id, language, action, *, before=None, after=None, reason=None, note=None, unchanged=None
) -> None:
    conn.execute(
        """INSERT INTO summary_events (ruling_id, language, action, reason, note, before_id, after_id, unchanged, actor)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (ruling_id, language, action, reason, (note or "").strip() or None, before, after, unchanged, ACTOR),
    )


def _language(language: str) -> str:
    if language not in LANGUAGES:
        raise ValueError(f"language must be one of {LANGUAGES}, got {language!r}")
    return language


# --- reading -----------------------------------------------------------------------------------------------


def refine_checks(steps: list[dict] | None) -> list[dict]:
    """What the refine loop checked on this summary, for the expert: per step its status and, per finding, what was
    found, whether the edit was kept, the passage it rests on and why an edit was refused (src/summarize/refine)."""
    out = []
    for step in steps or []:
        findings = [
            {k: f.get(k) for k in ("reason", "accepted", "evidence", "quote", "why_not") if f.get(k) is not None}
            for f in step.get("findings", [])
        ]
        out.append({"step": step["step"], "status": step["status"], "findings": findings, "note": step.get("note")})
    return out


def ruling_page(conn, ruling_id: int) -> dict:
    """Everything the ruling page shows: facts, status, full text, both summaries, Suva's own summary if any."""
    from . import queries

    with conn.cursor() as cur:
        cur.execute(queries._BASE + "SELECT * FROM list WHERE id = %s", (ruling_id,))
        row = cur.fetchone()
        if row is None:
            raise NotFound(f"no ruling with id {ruling_id}")
        ruling = dict(zip([c.name for c in cur.description], row, strict=True))
    ruling["title"] = queries.display_title(ruling["subject"], ruling["area"])
    text = conn.execute(
        "SELECT text, source FROM ruling_texts WHERE ruling_id = %s AND is_canonical", (ruling_id,)
    ).fetchone()
    summaries = {}
    for language in LANGUAGES:
        current = conn.execute(
            """SELECT s.id, s.version, s.origin, s.body, s.confirmed_at, s.created_at,
                      m.params ->> 'category', m.params -> 'problems' -> %s, m.params -> 'refine' -> %s -> 'steps'
               FROM summaries s LEFT JOIN model_runs m ON m.id = s.run_id
               WHERE s.ruling_id = %s AND s.language = %s AND s.is_current""",
            (language, language, ruling_id, language),
        ).fetchone()
        summaries[language] = current and {
            "id": current[0], "version": current[1], "origin": current[2], "body": current[3],
            "confirmed": current[4] is not None, "confirmed_at": current[4], "created_at": current[5],
            "category": current[6], "problems": current[7] or [], "checks": refine_checks(current[8]),
        }  # fmt: skip
    # Suva's own summary: the texts only. Its author and file name are never sent to the interface.
    reference = dict(
        conn.execute(
            "SELECT language, body FROM gold_summaries WHERE ruling_id = %s AND is_current", (ruling_id,)
        ).fetchall()
    )
    return {
        "ruling": ruling,
        "text": queries.display_text(text[0]) if text else None,  # tidied for reading; the stored text is untouched
        "text_source": text[1] if text else None,
        "prompt_category": pipeline.route(ruling["area"]),
        "summaries": summaries,
        "reference": {language: reference.get(language) for language in LANGUAGES},
        "revisions": list(REVISIONS),
    }


# --- writing -----------------------------------------------------------------------------------------------


def generate(conn, ruling_id: int, ask: Ask | None = None, model: str | None = None) -> dict:
    """Write both summaries with the pipeline (version 1) and record it."""
    try:
        result = pipeline.summarise_ruling(conn, ruling_id, ask or _default_ask, model)
    except pipeline.NotSummarisable as e:
        raise NotFound(str(e)) from e
    with conn.transaction():
        for language in LANGUAGES:
            after = conn.execute(
                "SELECT id FROM summaries WHERE ruling_id = %s AND language = %s AND run_id = %s",
                (ruling_id, language, result["stored"]["run_id"]),
            ).fetchone()[0]
            _event(conn, ruling_id, language, "generate", after=after)
    return ruling_page(conn, ruling_id)


def save_edit(conn, ruling_id: int, language: str, body: str, confirm: bool = False) -> dict:
    """The expert's own text becomes a new version; with confirm=True it is confirmed as final in the same step."""
    _language(language)
    with conn.transaction():
        if conn.execute("SELECT 1 FROM rulings WHERE id = %s FOR UPDATE", (ruling_id,)).fetchone() is None:
            raise NotFound(f"no ruling with id {ruling_id}")
        current = _current(conn, ruling_id, language)
        if current is not None and current[3].strip() == (body or "").strip():
            if confirm:
                return _confirm_current(conn, ruling_id, language, current)
            return ruling_page(conn, ruling_id)  # nothing changed, nothing to record
        new = _add_version(
            conn, ruling_id, language, body, "expert", parent_id=current[0] if current else None, confirm=confirm
        )
        _event(conn, ruling_id, language, "edit", before=current[0] if current else None, after=new)
        if confirm:
            _event(conn, ruling_id, language, "confirm", before=new, after=new, unchanged=False)
    return ruling_page(conn, ruling_id)


def _confirm_current(conn, ruling_id: int, language: str, current) -> dict:
    summary_id, _, origin, _, confirmed_at = current
    if confirmed_at is None:
        conn.execute("UPDATE summaries SET confirmed_at = now(), confirmed_by = %s WHERE id = %s", (ACTOR, summary_id))
        # "unchanged" = the expert accepted the model's text as it was written: agreement is data too.
        _event(conn, ruling_id, language, "confirm", before=summary_id, after=summary_id, unchanged=origin == "model")
    return ruling_page(conn, ruling_id)


def confirm(conn, ruling_id: int, language: str) -> dict:
    """Confirm the current summary as final: a gold summary."""
    _language(language)
    with conn.transaction():
        current = _current(conn, ruling_id, language)
        if current is None:
            raise NotFound("there is no summary to confirm")
        return _confirm_current(conn, ruling_id, language, current)


def unconfirm(conn, ruling_id: int, language: str) -> dict:
    """Take a confirmation back. The text stays; it is a draft again."""
    _language(language)
    with conn.transaction():
        current = _current(conn, ruling_id, language)
        if current is None or current[4] is None:
            raise NotFound("there is no confirmed summary")
        conn.execute("UPDATE summaries SET confirmed_at = NULL, confirmed_by = NULL WHERE id = %s", (current[0],))
        _event(conn, ruling_id, language, "unconfirm", before=current[0], after=current[0])
    return ruling_page(conn, ruling_id)


def revise(conn, ruling_id: int, language: str, reason: str, note: str | None = None,
           ask: Ask | None = None, model: str | None = None) -> dict:  # fmt: skip
    """Ask Apertus for one defined change to the current summary. The request and both texts are kept."""
    _language(language)
    if reason not in REVISIONS:
        raise ValueError(f"reason must be one of {list(REVISIONS)}, got {reason!r}")
    note = (note or "").strip()
    if reason in NEEDS_NOTE and not note:
        raise ValueError(f"'{reason}' needs a note saying what is meant")
    try:
        ruling = pipeline.load_ruling(conn, ruling_id)
    except pipeline.NotSummarisable as e:
        raise NotFound(str(e)) from e
    current = _current(conn, ruling_id, language)
    if current is None:
        raise NotFound("there is no summary to revise")
    category = pipeline.route(ruling["area"])
    other_language = "fr" if language == "de" else "de"
    parts = [
        "Ruling:", ruling["text"], "",
        "Current fiche:", current[3], "",
        "Revise the current fiche. " + REVISIONS[reason],
    ]  # fmt: skip
    if note:
        parts.append(f"The expert says: {note}")
    if reason == "align_languages":
        other = _current(conn, ruling_id, other_language)
        if other is None:
            raise NotFound("there is no fiche in the other language to align with")
        parts += ["", "Fiche in the other language:", other[3]]
    parts += [
        "",
        "Schreibe ausschliesslich Deutsch." if language == "de" else "Write in French only.",
        "Invent nothing. Answer with the revised fiche only.",
    ]
    raw = (ask or _default_ask)(
        [
            {"role": "system", "content": system_prompt(language, category)},
            {"role": "user", "content": "\n".join(parts)},
        ]
    )
    body, notes = finish.finish(language, raw, ruling["text"], ruling["starred"])
    problems = summarize.review(language, finish.without_note(body), ruling["text"], ruling["docket"])
    import os

    with conn.transaction():
        params = {"pipeline": pipeline.PIPELINE_VERSION, "prompt": PROMPT_VERSION, "category": category, "revision": reason,  # noqa: E501
                  "problems": {language: problems}, "finish_notes": {language: notes}}  # fmt: skip
        run_id = conn.execute(
            "INSERT INTO model_runs (kind, models, params) VALUES ('summary', %s, %s) RETURNING id",
            (Jsonb([{"name": model or os.environ.get("LLM_NAME") or "unknown", "role": "revises a fiche on an expert's request"}]),  # noqa: E501
             Jsonb(params)),
        ).fetchone()[0]  # fmt: skip
        new = _add_version(conn, ruling_id, language, body, "model", run_id=run_id, parent_id=current[0])
        _event(conn, ruling_id, language, "revise", before=current[0], after=new, reason=reason, note=note)
    return ruling_page(conn, ruling_id)


def decide_relevance(conn, ruling_id: int, action: str) -> dict:
    feedback.decide_relevance(conn, ruling_id, action)
    return ruling_page(conn, ruling_id)
