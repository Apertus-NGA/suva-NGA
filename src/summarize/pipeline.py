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
4b. when refine is on (`--refine`, or SUMMARY_REFINE=1), improve each finished fiche step by step
   (src/summarize/refine): Apertus proposes one narrow fix at a time, code verifies it; the draft and the trace
   of every step are stored with the run;
5. store both fiches as a new version in `summaries`, with a `model_runs` row naming the model, the prompt
   version, the route and what the checker found.

Rules it keeps: a fiche written or confirmed by an expert is never replaced as the current version; nothing is
stored if either language fails; the model is only reached through `summarize.chat` (the shared client).
"""

from __future__ import annotations

import argparse
import functools
import os
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from psycopg.types.json import Jsonb

if str(Path(__file__).resolve().parents[2]) not in sys.path:  # run as a script or as a module
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.llm.client import ReplayMiss  # noqa: E402
from src.summarize import finish, summarize  # noqa: E402
from src.summarize.prompts import VERSION as PROMPT_VERSION  # noqa: E402
from src.summarize.prompts import category_of  # noqa: E402

PIPELINE_VERSION = "1"
REFINE_BUDGET = 80  # Apertus calls of refine per ruling: the shared record and both languages
WRITERS = ("extract", "v2")  # extract: the fiche from the ruling's own sentences (src/summarize/extract); v2: prompt
EXTRACT_MIN_SENTENCES = 3  # fewer of the chosen sentences kept: the v2 fiche instead (review, 28 Nov)


def _choice_budget(text: str) -> int:
    """One reading per consideration, the point and two readings of the choice with a retry each."""
    from src.summarize.extract import candidates

    return len({c.label for c in candidates.candidates(text).kept}) + 10


def _fiche_budget(choice) -> int:
    """Up to six calls per sentence (two writes, two readings, the antecedent), the question, flow and polish."""
    return 6 * (len(choice.chosen) + 2) + 20


LANGUAGES = ("de", "fr")
MODES = ("live", "replay")
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
        f"""SELECT r.id, r.docket, r.decision_date::text, r.division, {_AREA}, r.starred, t.text, r.language
            FROM rulings r LEFT JOIN ruling_texts t ON t.ruling_id = r.id AND t.is_canonical AND t.bad_reason IS NULL
            WHERE r.id = %s""",
        (ruling_id,),
    ).fetchone()
    if row is None:
        raise NotSummarisable(f"no ruling with id {ruling_id}")
    if not row[6]:
        raise NotSummarisable(f"{row[1]} has no usable text")
    keys = ("id", "docket", "decision_date", "division", "area", "starred", "text", "language")
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


def lexicon(conn, language: str, target_docket: str) -> str:
    """Suva's summaries in one language, the target's own excluded: where refine's terms step finds a term
    attested (src/summarize/refine/steps/terms.py). Read at run time, never copied (D-031)."""
    rows = conn.execute(
        """SELECT g.body FROM gold_summaries g JOIN rulings r ON r.id = g.ruling_id
           WHERE g.is_current AND g.language = %s AND r.docket <> %s""",
        (language, target_docket),
    ).fetchall()
    return "\n".join(body for (body,) in rows)


def _replay_miss(exc: BaseException) -> None:
    """A replay miss stays one: the caller stores nothing (the model wraps every transport error, review)."""
    cause = exc
    while cause is not None:
        if isinstance(cause, ReplayMiss):
            raise cause
        cause = cause.__cause__


def _extract(ruling: dict, category: str, make_model, lexicons: dict[str, str] | None) -> dict:
    """The extractive fiches {language: fiche}; a language whose fiche failed is missing (the caller falls back to
    the prompt-written fiche for it, so every ruling gets one)."""
    from src.summarize import extract
    from src.summarize.refine.model import ModelFailed

    out: dict = {}
    try:
        choice = extract.choose.choose(ruling["text"], make_model(_choice_budget(ruling["text"])))
    except ModelFailed as exc:
        _replay_miss(exc)
        return {"_error": f"choice failed: {exc}"}
    source = {"text": ruling["text"], "language": ruling.get("language"), "category": category,
              "starred": ruling.get("starred")}  # fmt: skip

    def one(language: str):
        model = make_model(_fiche_budget(choice))
        known = {**source, "lexicon": (lexicons or {}).get(language, "")}
        try:
            return extract.write.write_fiche(choice, language, known, model, frame="question")
        except ModelFailed as exc:
            return exc

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(len(LANGUAGES)) as pool:  # DE and FR at once; the client caps concurrent calls (G2)
        fiches = dict(zip(LANGUAGES, pool.map(one, LANGUAGES), strict=True))
    for language, fiche in fiches.items():
        if isinstance(fiche, ModelFailed):
            _replay_miss(fiche)
            out[f"_error_{language}"] = str(fiche)
            continue
        kept = [w for w in fiche.sentences if w.status in extract.KEPT and not w.source_id.startswith("Q")]
        if len(kept) < min(EXTRACT_MIN_SENTENCES, len(choice.chosen)):
            out[f"_error_{language}"] = f"only {len(kept)} of the chosen sentences kept"
            continue
        out[language] = {"text": fiche.text, "raw": "", "finish_notes": fiche.notes, "writer": "extract",
                         "extract": {"version": extract.VERSION, "draft": "", "calls": fiche.calls,
                                     "checks_before": {}, "checks_after": {},
                                     "trace": extract.as_steps(choice, fiche)}}  # fmt: skip
    return out


def write(
    ruling: dict,
    shots: dict[str, list[dict]],
    ask: Ask | None = None,
    refine_model=None,
    lexicons: dict[str, str] | None = None,
    extract_model=None,
) -> dict:
    """Both fiches of one ruling, finished. With `extract_model` (a function budget -> Model) the extractive writer
    writes them, and the prompt-written fiche (v2) stands in for a language it could not write; else v2, refined
    when `refine_model` is given. Nothing is stored here."""
    category = route(ruling["area"])
    result = {"docket": ruling["docket"], "category": category, "languages": {}}
    extracted = _extract(ruling, category, extract_model, lexicons) if extract_model is not None else {}
    if extract_model is not None:
        result["extract_errors"] = {k: v for k, v in extracted.items() if k.startswith("_")}
    record = None
    for language in LANGUAGES:
        if language in extracted:
            fiche = extracted[language]
            fiche["problems"] = summarize.review(
                language, finish.without_note(fiche["text"]), ruling["text"], ruling["docket"]
            )
            result["languages"][language] = fiche
            continue
        raw, _ = summarize.write_fiche(language, ruling, shots[language], category, ask)
        text, notes = finish.finish(language, raw, ruling["text"], ruling["starred"])
        fiche = {"text": text, "raw": raw, "finish_notes": notes, "writer": "v2"}
        if refine_model is not None:
            from src.summarize import refine

            if record is None:  # one shared reading of the ruling for both languages
                record = refine.read_record(ruling["text"], refine.evidence.passages(ruling["text"]), refine_model)
            refined = refine.refine_fiche(
                text, language, ruling["text"], category, refine_model, record,
                (lexicons or {}).get(language, ""), ruling.get("language"),
            )  # fmt: skip
            fiche["text"], fiche["refine"] = refined.text, refined.as_dict()
        # The checker looks for the outcome at the end of the fiche, so it reads the text without the closing note.
        fiche["problems"] = summarize.review(
            language, finish.without_note(fiche["text"]), ruling["text"], ruling["docket"]
        )
        result["languages"][language] = fiche
    if record is not None:
        result["record"] = record
    return result


def _refine_params(result: dict) -> dict | None:
    """What the run stores about refine: per language the draft, the step statuses and the checks."""
    out = {}
    for language, fiche in result["languages"].items():
        trace = fiche.get("refine") or fiche.get("extract")  # the interface reads both the same way
        if trace:
            out[language] = {
                "version": trace["version"], "draft": trace["draft"], "calls": trace["calls"],
                "checks_before": trace["checks_before"], "checks_after": trace["checks_after"],
                "steps": trace["trace"],
            }  # fmt: skip
    if not out:
        return None
    record = result.get("record") or {}
    out["record"] = {k: record.get(k) for k in ("version", "status", "question", "rules", "answer", "issues")}
    return out


def store(conn, ruling_id: int, result: dict, model: str) -> dict:
    """Save both fiches as a new version. Returns {"run_id", "versions": {lang: n}, "current": {lang: bool}}."""
    out: dict = {"versions": {}, "current": {}}
    with conn.transaction():
        conn.execute("SELECT 1 FROM rulings WHERE id = %s FOR UPDATE", (ruling_id,))
        params = {
            "pipeline": PIPELINE_VERSION,
            "prompt": PROMPT_VERSION,
            "category": result["category"],
            "mode": result.get("mode"),
            "problems": {lang: p["problems"] for lang, p in result["languages"].items()},
            "finish_notes": {lang: p["finish_notes"] for lang, p in result["languages"].items()},
            "writer": {lang: p.get("writer", "v2") for lang, p in result["languages"].items()},
        }
        if result.get("extract_errors"):
            params["extract_errors"] = result["extract_errors"]
        if refined := _refine_params(result):
            params["refine"] = refined
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


def refine_on() -> bool:
    return os.environ.get("SUMMARY_REFINE", "0").strip() in ("1", "true", "yes", "on")


def writer_from_env() -> str:
    """SUMMARY_WRITER: "v2" (the library's default, which the pipeline's tests rely on) or "extract" (the v1
    summaries: set in .env.example, so a deployment writes them)."""
    value = os.environ.get("SUMMARY_WRITER", "v2").strip().lower() or "v2"
    if value not in WRITERS:
        raise ValueError(f"SUMMARY_WRITER must be one of {WRITERS}, got {value!r}")
    return value


def summarise_ruling(
    conn,
    ruling_id: int,
    ask: Ask | None = None,
    model: str | None = None,
    mode: str = "live",
    refine: bool | None = None,
    refine_transport=None,
    writer: str | None = None,
) -> dict:
    """Route, write, finish and store the fiches of one ruling. Returns the result with what was stored.

    Without `ask`, the model is reached through `summarize.chat` in `mode`: "live" calls the gateway,
    "replay" answers from the client's replay cache and raises `ReplayMiss` (nothing stored) on a miss.
    With `ask`, the caller's function answers and `mode` is recorded as "injected".
    `refine` (default: SUMMARY_REFINE) refines each fiche; its calls go through `refine_transport`, or through the
    shared client in `mode` when none is given and no `ask` was injected.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    writer = writer or writer_from_env()
    if writer not in WRITERS:
        raise ValueError(f"writer must be one of {WRITERS}, got {writer!r}")
    refining = (refine if refine is not None else refine_on()) and writer == "v2"  # extract polishes on its own
    extracting = writer == "extract"
    if (refining or extracting) and refine_transport is None and ask is not None:
        raise ValueError("an injected ask needs an injected refine_transport")
    ruling = load_ruling(conn, ruling_id)
    shots = {language: examples(conn, language, ruling["docket"]) for language in LANGUAGES}
    refine_model = make_model = None
    if refining or extracting:
        from src.llm.client import client_from_env
        from src.summarize.refine import Model, gateway
        from src.summarize.refine.model import gateway_labeler

        if refine_transport is None:
            client = client_from_env(mode)
            refine_transport, labeler = gateway(client=client), gateway_labeler(client=client)
        else:
            labeler = getattr(refine_transport, "label", None)
        if refining:
            refine_model = Model(refine_transport, budget=REFINE_BUDGET, labeler=labeler)
        if extracting:
            transport = refine_transport

            def make_model(budget: int):
                return Model(transport, budget=budget, labeler=labeler)

    lexicons = (
        {language: lexicon(conn, language, ruling["docket"]) for language in LANGUAGES}
        if (refine_model or make_model) else None
    )  # fmt: skip
    result = write(ruling, shots, ask or functools.partial(_chat, mode=mode), refine_model, lexicons, make_model)
    result["mode"] = "injected" if ask is not None else mode
    result["stored"] = store(conn, ruling_id, result, model or os.environ.get("LLM_NAME") or "unknown")
    return result


def _chat(messages: list[dict], mode: str) -> str:
    return summarize.chat(messages, mode=mode)  # looked up at call time, so tests can replace summarize.chat


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
    parser.add_argument(
        "--mode", choices=MODES, default="live", help="live: call Apertus; replay: answer from the replay cache only"
    )
    parser.add_argument("--refine", action="store_true", help="refine each fiche step by step (or SUMMARY_REFINE=1)")
    parser.add_argument("--writer", choices=WRITERS, help="extract (the v1 summaries) or v2 (default: SUMMARY_WRITER)")
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
            result = summarise_ruling(conn, ruling_id, mode=args.mode, refine=args.refine or refine_on(),
                                      writer=args.writer)  # fmt: skip
        except (NotSummarisable, ReplayMiss, SystemExit) as e:
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
