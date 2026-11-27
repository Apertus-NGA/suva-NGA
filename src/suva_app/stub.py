"""Placeholder relevance scores, so the UI can be built before triage writes real predictions.

    uv run python -m suva_app.stub            # write placeholder scores for every ruling
    uv run python -m suva_app.stub --remove   # delete them again

The scores are NOT model output. They are a fixed pseudo-random number per case number, shifted up for
accident / military insurance and for rulings Suva labelled relevant, so the list looks plausible.
They live in one model_runs row marked params = {"stub": true}; the API reports that and the UI shows it.
Real triage output replaces them: `--remove` first, or retire them by writing new current predictions.
"""

from __future__ import annotations

import argparse
import hashlib

from psycopg.types.json import Jsonb

from suva_data import db

STUB_MODELS = [{"name": "placeholder", "role": "no model: fixed pseudo-random scores for UI development"}]
THRESHOLD = 0.5


def stub_score(docket: str, topic: str | None, label: str) -> float:
    """Deterministic value in [0.01, 0.99]: the same ruling always gets the same placeholder."""
    noise = int(hashlib.sha256(docket.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    if label == "relevant":
        low, high = 0.62, 0.99
    elif topic in ("UV", "MV"):
        low, high = 0.25, 0.90
    elif topic == "IV":
        low, high = 0.08, 0.60
    else:
        low, high = 0.01, 0.20
    return round(low + noise * (high - low), 4)


def remove(conn) -> int:
    """Delete every placeholder run (its predictions go with it). Returns the number of predictions removed."""
    with conn.transaction():
        n = conn.execute(
            "SELECT count(*) FROM predictions p JOIN model_runs m ON m.id = p.run_id WHERE (m.params ->> 'stub')::boolean"
        ).fetchone()[0]
        conn.execute("DELETE FROM model_runs WHERE (params ->> 'stub')::boolean")
    return n


def seed(conn) -> int:
    """Write a placeholder prediction for every ruling that has no current prediction. Returns how many."""
    from .queries import _BASE  # the same area / topic logic the list uses

    with conn.transaction():
        rows = conn.execute(
            _BASE + "SELECT id, docket, topic, label FROM list l "
                    "WHERE NOT EXISTS (SELECT 1 FROM predictions p WHERE p.ruling_id = l.id AND p.is_current) ORDER BY id"
        ).fetchall()
        if not rows:
            return 0
        run_id = conn.execute(
            "INSERT INTO model_runs (kind, models, params, git_commit) VALUES ('triage', %s, %s, %s) RETURNING id",
            (Jsonb(STUB_MODELS), Jsonb({"stub": True, "threshold": THRESHOLD}), db.git_commit()),
        ).fetchone()[0]
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO predictions (ruling_id, run_id, score, relevant, explanation) VALUES (%s, %s, %s, %s, NULL)",
                [(rid, run_id, s, s >= THRESHOLD) for rid, docket, topic, label in rows
                 for s in [stub_score(docket, topic, label)]],
            )
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--remove", action="store_true", help="delete the placeholder scores")
    args = parser.parse_args()
    with db.connect() as conn:
        db.migrate(conn)
        if args.remove:
            print(f"removed {remove(conn)} placeholder predictions")
        else:
            print(f"wrote {seed(conn)} placeholder predictions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
