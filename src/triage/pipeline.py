"""The relevance pipeline, end to end (triage v1).

    layer 1 (src/courts.py)  ->  structural signals  ->  six Apertus readings  ->  score  ->  tier
    -> one current row per kept ruling in the `predictions` table, which the UI reads.

Run (`make run` calls `run_and_store`; `make triage` calls `main`):
    python -m src.triage.pipeline --mode replay            # from cached Apertus answers only; nothing written
    python -m src.triage.pipeline --mode live --write      # real calls where no answer is cached, then write
    python -m src.triage.pipeline --mode live --limit 3    # a smoke run: neither the database nor results/

A full run (no --limit) writes results/triage_pipeline.json, labelled LIVE or REPLAY. In replay mode a missing
cached answer stops the run before anything is written (a missing answer would otherwise read as "no reading").

Tiers as the UI shows them: in each decision quarter the highest-scored kept rulings, as many as 40% of the
quarter's accident, military and disability rulings, are "suspected relevant" (`predictions.relevant = true`);
the other kept rulings are "possibly relevant" (`false`); a ruling layer 1 does
not keep has no current prediction ("not assessed"). Description and measurements: docs/TRIAGE_PIPELINE.md.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from src import courts
from src.signals.structural import as_dict, structural_signals
from src.triage import readings as rd
from src.triage import scorer as sc
from src.triage.reading_prompts import sections

VERSION = "triage_pipeline@1"
CORE_AREAS = ("UV", "MV", "IV")
LISTED = ("2025 Q4", "2026 Q1")  # the quarters for which Suva's list is complete
RESULTS = Path(__file__).resolve().parents[2] / "results" / "triage_pipeline.json"

_SQL = """
SELECT r.id, r.docket, r.decision_date, r.area, r.subject, r.starred, r.language, t.text,
       v.decision_quarter, v.basis
FROM rulings r
JOIN v_relevance v ON v.ruling_id = r.id
JOIN ruling_texts t ON t.ruling_id = r.id AND t.is_canonical
ORDER BY r.id
"""


def load_rulings(conn: Any) -> list[dict[str, Any]]:
    columns = ("id", "docket", "decision_date", "area", "subject", "starred", "language", "text", "quarter", "basis")
    return [dict(zip(columns, row, strict=True)) for row in conn.execute(_SQL).fetchall()]


def label(ruling: dict[str, Any]) -> int | None:
    """1 / 0 from Suva's list in a listed quarter (closed world, Q-04); None anywhere else."""
    if ruling["quarter"] not in LISTED:
        return None
    if ruling["basis"] == "suva_xlsx":
        return 1
    if ruling["basis"] == "complete_list_negative":
        return 0
    return None  # an expert override made in the UI is not Suva's list


def prepare(ruling: dict[str, Any], judge: Any) -> dict[str, Any]:
    """Layer 1 and the structural signals of one ruling."""
    area = ruling["area"] if isinstance(ruling["area"], str) and ruling["area"].strip() else None
    title = ruling["subject"] if isinstance(ruling["subject"], str) and ruling["subject"].strip() else None
    text = ruling["text"] or ""
    layer1 = courts.layer1_record(ruling["docket"], area, title, text, judge)
    out = {**ruling, "layer1": {k: v for k, v in layer1.items() if k != "docket"}, "kept": bool(layer1["kept"])}
    if out["kept"]:
        signals = as_dict(structural_signals(area, ruling["starred"], text))
        out["signals"] = signals
        out["core"] = signals["area"] in CORE_AREAS and not signals.get("single_judge", False)
    return out


def read(client: Any, ruling: dict[str, Any]) -> dict[str, float | None]:
    """The six Apertus readings of a core ruling (accident, military or disability insurance, full decision)."""
    doc = {**sections(ruling["text"]), "uvmv": int(ruling["signals"]["area"] in ("UV", "MV"))}
    return rd.read_all(client, doc)


def _f2(tp: int, fp: int, fn: int) -> float:
    return 5 * tp / (5 * tp + 4 * fn + fp) if tp else 0.0


def promote(scores: np.ndarray, core: np.ndarray) -> np.ndarray:
    """The cut: the highest-scored rulings of a period, as many as ``CORE_SHARE`` of its core rulings."""
    n = max(1, int(round(sc.CORE_SHARE * int(core.sum()))))
    chosen = np.zeros(len(scores), bool)
    chosen[np.argsort(-scores, kind="stable")[:n]] = True
    return chosen


def evaluate(x: np.ndarray, y: np.ndarray, quarter: np.ndarray, core: np.ndarray, n_missed: int) -> dict[str, Any]:
    """Out of quarter: fit on one listed quarter, cut and report on the other, both pooled."""
    tp = fp = 0
    per: dict[str, Any] = {}
    for a, b in ((LISTED[0], LISTED[1]), (LISTED[1], LISTED[0])):
        train, test = quarter == a, quarter == b
        model = sc.Scorer.fit(x[train], y[train], int(core[train].sum()))
        chosen = promote(model.score(x[test]), core[test])
        hit, wrong = int((chosen & (y[test] == 1)).sum()), int((chosen & (y[test] == 0)).sum())
        per[b] = {"submitted": int(chosen.sum()), "relevant_found": hit, "relevant": int(y[test].sum())}
        tp, fp = tp + hit, fp + wrong
    total = int(y.sum()) + n_missed
    return {
        "protocol": "fit on one listed quarter; on the other, promote 40% of its core rulings; folds pooled",
        "submitted": tp + fp,
        "relevant_found": tp,
        "relevant_total": total,
        "recall": round(tp / total, 3),
        "precision": round(tp / max(tp + fp, 1), 3),
        "f2": round(_f2(tp, fp, total - tp), 3),
        "per_quarter": per,
    }


def run(conn: Any, client: Any, workers: int = 5, limit: int | None = None) -> dict[str, Any]:
    from src.area_judge import gate_judge

    rulings = load_rulings(conn)
    if limit:
        rulings = rulings[:limit]
    judge = gate_judge(client)
    with ThreadPoolExecutor(workers) as pool:
        prepared = list(pool.map(lambda r: prepare(r, judge), rulings))
    kept = [r for r in prepared if r["kept"]]
    core = [r for r in kept if r["core"]]
    with ThreadPoolExecutor(workers) as pool:
        for ruling, reading in zip(core, pool.map(lambda r: read(client, r), core), strict=True):
            ruling["readings"] = reading
    if limit:  # a smoke run: the first N rulings cannot train the scorer (it needs both labelled quarters)
        summary = {
            "version": VERSION,
            "rulings": len(prepared),
            "kept_by_layer1": len(kept),
            "core_rulings_read_by_apertus": len(core),
            "apertus_readings_failed": sum(1 for r in core for v in r["readings"].values() if v is None),
            "scorer": f"not fitted: a smoke run of the first {limit} rulings",
        }
        return {"summary": summary, "kept": kept, "model": None, "consensus": None}
    consensus = sc.Consensus.fit([r["readings"] for r in core])
    for ruling in kept:
        ruling["consensus"] = consensus.value(ruling.get("readings"))
        ruling["x"] = sc.features(ruling["signals"], ruling["consensus"])
        ruling["y"] = label(ruling)
    train = [r for r in kept if r["y"] is not None]
    x = np.array([r["x"] for r in train])
    y = np.array([r["y"] for r in train])
    quarter = np.array([r["quarter"] for r in train])
    is_core = np.array([r["signals"]["area"] in CORE_AREAS for r in train])
    relevant_all = sum(1 for r in prepared if label(r) == 1)
    measured = evaluate(x, y, quarter, is_core, relevant_all - int(y.sum()))
    model = sc.Scorer.fit(x, y, int(is_core.sum()))
    scores = model.score(np.array([r["x"] for r in kept]))
    for ruling, score in zip(kept, scores, strict=True):
        ruling["score"] = float(score)
        ruling["tier"] = "possibly_relevant"
        ruling["contributions"] = model.contributions(ruling["x"])
    for q in {r["quarter"] for r in kept}:  # the cut is taken per decision quarter, as it was measured
        group = [r for r in kept if r["quarter"] == q]
        core_flags = np.array([r["signals"]["area"] in CORE_AREAS for r in group])
        if not core_flags.any():
            continue
        for ruling, chosen in zip(group, promote(np.array([r["score"] for r in group]), core_flags), strict=True):
            if chosen:
                ruling["tier"] = "suspected_relevant"
    failed = sum(1 for r in core for v in r["readings"].values() if v is None)
    summary = {
        "version": VERSION,
        "rulings": len(prepared),
        "kept_by_layer1": len(kept),
        "core_rulings_read_by_apertus": len(core),
        "apertus_readings_failed": failed,
        "consensus_readings": sorted(consensus.stats),
        "training_rulings": len(train),
        "training_relevant": int(y.sum()),
        "relevant_not_kept_by_layer1": relevant_all - int(y.sum()),
        "threshold": round(model.threshold, 4),
        "out_of_quarter": measured,
        "by_quarter": {
            q: {
                "kept": sum(1 for r in kept if r["quarter"] == q),
                "suspected_relevant": sum(1 for r in kept if r["quarter"] == q and r["tier"] == "suspected_relevant"),
            }
            for q in sorted({r["quarter"] for r in kept})
        },
    }
    return {"summary": summary, "kept": kept, "model": model, "consensus": consensus}


def _git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return None


def write(conn: Any, result: dict[str, Any], model_names: list[dict[str, str]]) -> int:
    """One triage run, one current prediction per kept ruling. Earlier predictions stay, no longer current."""
    from psycopg.types.json import Jsonb

    summary, model = result["summary"], result["model"]
    params = {
        "pipeline": VERSION,
        "layer1": "src/courts.py (D-060)",
        "readings": rd.VERSION,
        "reading_prompts": {name: version for name, (version, _) in rd.READINGS.items()},
        "scorer": sc.VERSION,
        "features": sc.FEATURES,
        "threshold": model.threshold,
        "consensus_stats": result["consensus"].stats,
        "measured": summary["out_of_quarter"],
    }
    with conn.transaction():
        run_id = conn.execute(
            "INSERT INTO model_runs (kind, models, params, git_commit) VALUES ('triage', %s, %s, %s) RETURNING id",
            (Jsonb(model_names), Jsonb(params), _git_commit()),
        ).fetchone()[0]
        conn.execute("UPDATE predictions SET is_current = false WHERE is_current")
        for ruling in result["kept"]:
            n_readings = sum(1 for v in (ruling.get("readings") or {}).values() if v is not None)
            details = {
                "tier": ruling["tier"],
                "layer1": ruling["layer1"],
                "signals": ruling["signals"],
                "apertus_readings": ruling.get("readings"),
                "apertus_consensus": ruling["consensus"],
                "contributions": ruling["contributions"],
            }
            conn.execute(
                """INSERT INTO predictions (ruling_id, run_id, score, relevant, explanation, details, is_current)
                   VALUES (%s, %s, %s, %s, %s, %s, true)""",
                (
                    ruling["id"],
                    run_id,
                    ruling["score"],
                    ruling["tier"] == "suspected_relevant",
                    sc.explanation_de(ruling["tier"], ruling["contributions"], ruling["x"], n_readings),
                    Jsonb(details),
                ),
            )
    return run_id


class TriageIncomplete(RuntimeError):
    """Some Apertus answers are missing (in replay mode: not in the cache); nothing was written."""


def failures(result: dict[str, Any]) -> tuple[int, int]:
    """(failed relevance readings, failed layer-1 matter readings) of one run."""
    gate = sum(1 for r in result["kept"] if (r.get("layer1") or {}).get("apertus") == "failed")
    return int(result["summary"].get("apertus_readings_failed", 0)), gate


def model_names(client: Any) -> list[dict[str, str]]:
    return [
        {
            "name": client.cfg.name or "apertus (replayed)",
            "role": "six relevance readings and the layer-1 matter reading",
        },
        {
            "name": "logistic regression (scikit-learn)",
            "role": "combines code-read facts and the Apertus consensus into the score",
        },
    ]


def run_and_store(
    conn: Any, client: Any, *, mode: str, write_db: bool, limit: int | None = None, workers: int = 5
) -> dict[str, Any]:
    """Run the pipeline, then store it. A --limit run is a smoke run: it writes neither the database nor
    results/. In replay mode any missing answer raises TriageIncomplete before anything is written."""
    result = run(conn, client, workers=workers, limit=limit)
    summary = result["summary"]
    summary["mode"] = mode.upper()
    readings_failed, gate_failed = failures(result)
    summary["layer1_apertus_failed"] = gate_failed
    if mode == "replay" and (readings_failed or gate_failed):
        raise TriageIncomplete(
            f"replay cache incomplete: {readings_failed} of the readings and {gate_failed} layer-1 matter readings "
            f"have no cached answer (cache: data/derived/llm); nothing written. Run live, or restore the cache"
        )
    if limit:
        return summary
    if write_db:
        summary["run_id"] = write(conn, result, model_names(client))
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--mode", choices=("live", "replay"), default="replay", help="Apertus calls: real or cached only"
    )
    parser.add_argument("--write", action="store_true", help="write the predictions to the database")
    parser.add_argument("--limit", type=int, default=None, help="only the first N rulings (a smoke run)")
    parser.add_argument("--workers", type=int, default=5)
    args = parser.parse_args(argv)

    from src.llm.client import client_from_env
    from suva_data import db

    client = client_from_env(args.mode)
    with db.connect() as conn:
        try:
            summary = run_and_store(
                conn, client, mode=args.mode, write_db=args.write, limit=args.limit, workers=args.workers
            )
        except TriageIncomplete as exc:
            print(f"triage [{args.mode.upper()}]: FAILED: {exc}")
            return 1
    print(json.dumps(summary, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
