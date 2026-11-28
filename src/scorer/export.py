"""Export the latest stored scorer run from the database it ran on (the legacy `model_runs` / `predictions` tables).

    python -m src.scorer export --from-url postgresql://... --out data/derived/scorer/run.json

Read-only on the source. The file holds one row per ruling the run kept, keyed by docket and decision date. It is
derived from a model fitted on Suva's list, so it stays in data/derived/ (git-ignored, D-031).
"""

from __future__ import annotations

import json
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from src.scorer.models import StoredRun

_RUN = (
    "SELECT id, created_at, git_commit, models, params FROM model_runs WHERE kind = 'triage' ORDER BY id DESC LIMIT 1"
)
_ROWS = """SELECT r.docket, r.decision_date::text AS decision_date, p.score, p.relevant AS promoted,
                  p.explanation AS explanation_de, p.details
           FROM predictions p JOIN rulings r ON r.id = p.ruling_id
           WHERE p.run_id = %s ORDER BY r.docket, r.decision_date"""


def export(source_url: str, out: Path, mode: str) -> StoredRun:
    with psycopg.connect(source_url, row_factory=dict_row) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        run = conn.execute(_RUN).fetchone()
        if run is None:
            raise SystemExit("export: the source database has no triage run")
        rows = conn.execute(_ROWS, (run["id"],)).fetchall()
    stored = StoredRun(
        source_run_id=run["id"],
        created_at=run["created_at"].isoformat(),
        git_commit=run["git_commit"],
        mode=mode,
        scorer=run["params"]["scorer"],
        models=run["models"],
        rulings=[
            {
                "docket": row["docket"],
                "decision_date": row["decision_date"],
                "score": row["score"],
                "promoted": row["promoted"],
                "explanation_de": row["explanation_de"],
                "contributions": row["details"]["contributions"],
                "signals": row["details"]["signals"],
                "apertus_readings": row["details"].get("apertus_readings"),
                "apertus_consensus": row["details"].get("apertus_consensus"),
                "layer1": row["details"]["layer1"],
            }
            for row in rows
        ],
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(stored.model_dump(), ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return stored
