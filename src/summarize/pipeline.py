"""Summary pipeline, version 1: database in, database out.

    uv run python -m src.summarize.pipeline --routes
        which prompt each ruling would get (no model call)
    uv run python -m src.summarize.pipeline --dockets 8C_78/2025
        summarise these rulings
    uv run python -m src.summarize.pipeline --status ai_relevant --limit 10
        summarise the highest-scored rulings of a status
    add --dry-run to see what would be done without calling the model

For one ruling the pipeline does, in order:
1. read the ruling from Postgres (canonical text, area, publication mark);
2. route it to the prompt of its matter: accident (uv), disability (iv), health (kv), occupational pension (bv),
   contract (vvg), or the neutral prompt (other) when the area is none of these. The route is recorded;
3. write the German and the French fiche, each from the ruling, with the model (Apertus through src/llm);
   the checker may ask the model for up to two repairs (src/summarize/summarize.py);
4. finish each fiche by code (src/summarize/finish.py): outcome once, abbreviations in the fiche's language,
   only considerations that exist, Suva's closing note;
5. store both fiches as a new version in `summaries`, with a `model_runs` row naming the model, the prompt
   version, the route and what the checker found.

Rules it keeps: a fiche written or confirmed by an expert is never replaced as the current version; nothing is
stored if either language fails; the model is only reached through `summarize.chat` (the shared client).
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from psycopg.types.json import Jsonb

if str(Path(__file__).resolve().parents[2]) not in sys.path:  # run as a script or as a module
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.summarize import finish, summarize  # noqa: E402
from src.summarize.prompts import VERSION as PROMPT_VERSION  # noqa: E402
from src.summarize.prompts import category_of  # noqa: E402

PIPELINE_VERSION = "1"
LANGUAGES = ("de", "fr")
CATEGORIES = ("uv", "iv", "kv", "bv", "vvg", "other")
_AREA = (
    "coalesce(r.area, nullif(split_part(r.subject, ' (', 1), ''))"  # the area, also for rulings not yet on a court list
)

Ask = Callable[[list[dict]], str]


class NotSummarisable(ValueError):
    """The ruling cannot be summarised (unknown, or no usable text)."""


def route(area: str | None) -> str:
    """The matter whose prompt a ruling gets, from its area of law (German, French or Italian). 'other' if none."""
    return category_of(area)


def load_ruling(conn, ruling_id: int) -> dict:
    row = conn.execute(
        f"""SELECT r.id, r.docket, r.decision_date::text, r.division, {_AREA}, r.starred, t.text
            FROM rulings r LEFT JOIN ruling_texts t ON t.ruling_id = r.id AND t.is_canonical AND t.bad_reason IS NULL
            WHERE r.id = %s""",
        (ruling_id,),
    ).fetchone()
    if row is None:
        raise NotSummarisable(f"no ruling with id {ruling_id}")
    if not row[6]:
        raise NotSummarisable(f"{row[1]} has no usable text")
    keys = ("id", "docket", "decision_date", "division", "area", "starred", "text")
    ruling = dict(zip(keys, row, strict=True))
    ruling["text"] = summarize.clean(ruling["text"])
    return ruling


def examples(conn, language: str, target_docket: str) -> list[dict]:
    """The Suva fiches shown to the model as tone examples: the pipeline's fixed pair, never the target's own."""
    wanted = [d for d in summarize.FEW_SHOT if d != target_docket]
    rows = dict(
        conn.execute(
            """SELECT r.docket, g.body FROM gold_summaries g JOIN rulings r ON r.id = g.ruling_id
               WHERE g.is_current AND g.language = %s AND r.docket = ANY(%s)""",
            (language, wanted),
        ).fetchall()
    )
    return [{"docket": d, "body": summarize.clean(rows[d])} for d in wanted if d in rows]


def write(ruling: dict, shots: dict[str, list[dict]], ask: Ask | None = None) -> dict:
    """Both fiches of one ruling, finished. Nothing is stored here."""
    category = route(ruling["area"])
    result = {"docket": ruling["docket"], "category": category, "languages": {}}
    for language in LANGUAGES:
        raw, _ = summarize.write_fiche(language, ruling, shots[language], category, ask)
        text, notes = finish.finish(language, raw, ruling["text"], ruling["starred"])
        # The checker looks for the outcome at the end of the fiche, so it reads the text without the closing note.
        problems = summarize.review(language, finish.without_note(text), ruling["text"], ruling["docket"])
        result["languages"][language] = {"text": text, "raw": raw, "problems": problems, "finish_notes": notes}
    return result


def store(conn, ruling_id: int, result: dict, model: str) -> dict:
    """Save both fiches as a new version. Returns {"run_id", "versions": {lang: n}, "current": {lang: bool}}."""
    out: dict = {"versions": {}, "current": {}}
    with conn.transaction():
        conn.execute("SELECT 1 FROM rulings WHERE id = %s FOR UPDATE", (ruling_id,))
        params = {
            "pipeline": PIPELINE_VERSION,
            "prompt": PROMPT_VERSION,
            "category": result["category"],
            "problems": {lang: p["problems"] for lang, p in result["languages"].items()},
            "finish_notes": {lang: p["finish_notes"] for lang, p in result["languages"].items()},
        }
        out["run_id"] = conn.execute(
            "INSERT INTO model_runs (kind, models, params) VALUES ('summary', %s, %s) RETURNING id",
            (Jsonb([{"name": model, "role": "writes the German and French fiche"}]), Jsonb(params)),
        ).fetchone()[0]
        for language, fiche in result["languages"].items():
            current = conn.execute(
                "SELECT id, origin, confirmed_at FROM summaries WHERE ruling_id = %s AND language = %s AND is_current",
                (ruling_id, language),
            ).fetchone()
            version = conn.execute(
                "SELECT coalesce(max(version), 0) + 1 FROM summaries WHERE ruling_id = %s AND language = %s",
                (ruling_id, language),
            ).fetchone()[0]
            # A fiche an expert wrote or confirmed stays the current one; the new draft is kept beside it.
            becomes_current = current is None or (current[1] != "expert" and current[2] is None)
            if current is not None and becomes_current:
                conn.execute("UPDATE summaries SET is_current = false WHERE id = %s", (current[0],))
            conn.execute(
                """INSERT INTO summaries (ruling_id, language, body, origin, run_id, version, is_current, created_by)
                   VALUES (%s, %s, %s, 'model', %s, %s, %s, 'pipeline')""",
                (ruling_id, language, fiche["text"], out["run_id"], version, becomes_current),
            )
            out["versions"][language], out["current"][language] = version, becomes_current
    return out


def summarise_ruling(conn, ruling_id: int, ask: Ask | None = None, model: str | None = None) -> dict:
    """Route, write, finish and store the fiches of one ruling. Returns the result with what was stored."""
    ruling = load_ruling(conn, ruling_id)
    shots = {language: examples(conn, language, ruling["docket"]) for language in LANGUAGES}
    result = write(ruling, shots, ask)
    result["stored"] = store(conn, ruling_id, result, model or os.environ.get("LLM_NAME") or "unknown")
    return result


def routes(conn, where: str = "", params: tuple = ()) -> list[tuple[int, str, str | None, str]]:
    """[(ruling id, docket, area, category)] for the rulings selected by `where` (a condition on rulings r)."""
    rows = conn.execute(
        f"SELECT r.id, r.docket, {_AREA} FROM rulings r {where} ORDER BY r.decision_date DESC, r.docket", params
    )
    return [(rid, docket, area, route(area)) for rid, docket, area in rows]


def _selected(conn, args) -> list[tuple[int, str, str | None, str]]:
    if args.dockets:
        return routes(conn, "WHERE r.docket = ANY(%s)", (args.dockets,))
    from suva_app.queries import _BASE  # the status the interface shows

    ids = [
        r[0]
        for r in conn.execute(
            _BASE + "SELECT id FROM list WHERE status = %s ORDER BY score DESC NULLS LAST, decision_date DESC LIMIT %s",
            (args.status, args.limit),
        )
    ]
    return routes(conn, "WHERE r.id = ANY(%s)", (ids,))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summary pipeline, version " + PIPELINE_VERSION)
    parser.add_argument(
        "--routes", action="store_true", help="count which prompt every ruling would get; no model call"
    )
    parser.add_argument("--dockets", nargs="+", help="case numbers to summarise")
    parser.add_argument("--status", help="summarise rulings of this status, highest score first (needs --limit)")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true", help="show the routing, call no model, store nothing")
    args = parser.parse_args(argv)

    from suva_data import db

    conn = db.connect()
    if args.routes:
        counts = Counter(category for *_, category in routes(conn))
        scope = Counter(category for *_, category in routes(conn, "WHERE r.division IN ('8C', '9C')"))
        print("prompt   all rulings   divisions 8C and 9C")
        for category in CATEGORIES:
            print(f"{category:<8} {counts[category]:>11}   {scope[category]:>19}")
        return 0
    if not args.dockets and not (args.status and args.limit):
        parser.error("give --routes, --dockets, or --status with --limit")
    todo = _selected(conn, args)
    if not todo:
        print("no ruling selected")
        return 1
    summarize.load_env()
    failed = 0
    for index, (ruling_id, docket, area, category) in enumerate(todo, start=1):
        print(f"{index}/{len(todo)} {docket}: area {area!r} -> prompt '{category}'", flush=True)
        if args.dry_run:
            continue
        try:
            result = summarise_ruling(conn, ruling_id)
        except (NotSummarisable, SystemExit) as e:
            failed += 1
            print(f"  failed: {e}", flush=True)
            continue
        for language, fiche in result["languages"].items():
            state = "current" if result["stored"]["current"][language] else "kept beside the expert's version"
            print(f"  {language} v{result['stored']['versions'][language]} ({state}), {len(fiche['text'])} characters, "
                  f"checker: {fiche['problems'] or 'ok'}", flush=True)  # fmt: skip
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
