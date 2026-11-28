"""Expert decisions. Every decision goes through here: the event and the current state are written together.

Nothing is overwritten without a trace: `relevance_events` keeps each decision with the status and score the
expert saw. The current decision lives in `labels` (label_set 'expert_override'), which v_relevance reads.
"""

from __future__ import annotations

from . import queries

ACTIONS = ("confirm_relevant", "mark_not_relevant", "reopen")
OVERRIDE = "expert_override"
ACTOR = "expert"  # one shared identity for now


class UnknownRuling(LookupError):
    pass


def status_of(conn, ruling_id: int) -> dict | None:
    """{"status", "label_basis", "prediction_id", "score"} of one ruling as the list shows it, or None."""
    row = conn.execute(queries._BASE + "SELECT status, label_basis FROM list WHERE id = %s", (ruling_id,)).fetchone()
    if row is None:
        return None
    prediction = conn.execute(
        "SELECT id, score FROM predictions WHERE ruling_id = %s AND is_current", (ruling_id,)
    ).fetchone()
    return {
        "status": row[0],
        "label_basis": row[1],
        "prediction_id": prediction[0] if prediction else None,
        "score": prediction[1] if prediction else None,
    }


def decide_relevance(conn, ruling_id: int, action: str, reason: str | None = None, comment: str | None = None) -> dict:
    """Record an expert decision and apply it. Returns {"status_before", "status_after", "event_id"}.

    confirm_relevant   the ruling is relevant to Suva: a gold label
    mark_not_relevant  the ruling is not relevant: a gold label too
    reopen             take the expert decision back; the status falls back to the system's assessment
    A decision that changes nothing (confirming what is already confirmed) is still recorded: an expert
    agreeing is information.
    """
    if action not in ACTIONS:
        raise ValueError(f"action must be one of {ACTIONS}, got {action!r}")
    with conn.transaction():
        conn.execute("SELECT 1 FROM rulings WHERE id = %s FOR UPDATE", (ruling_id,))
        before = status_of(conn, ruling_id)
        if before is None:
            raise UnknownRuling(f"no ruling with id {ruling_id}")
        if action == "reopen":
            conn.execute("DELETE FROM labels WHERE ruling_id = %s AND label_set = %s", (ruling_id, OVERRIDE))
        else:
            value = "relevant" if action == "confirm_relevant" else "not_relevant"
            conn.execute(
                """INSERT INTO labels (ruling_id, label_set, value, created_by) VALUES (%s, %s, %s, %s)
                   ON CONFLICT (ruling_id, label_set) DO UPDATE SET value = EXCLUDED.value, created_at = now()""",
                (ruling_id, OVERRIDE, value, ACTOR),
            )
        after = status_of(conn, ruling_id)
        event_id = conn.execute(
            """INSERT INTO relevance_events (ruling_id, action, status_before, status_after, prediction_id, score_shown,
                                             reason, comment, actor)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (
                ruling_id,
                action,
                before["status"],
                after["status"],
                before["prediction_id"],
                before["score"],
                (reason or "").strip() or None,
                (comment or "").strip() or None,
                ACTOR,
            ),
        ).fetchone()[0]
    return {"status_before": before["status"], "status_after": after["status"], "event_id": event_id}
