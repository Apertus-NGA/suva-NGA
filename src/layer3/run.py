"""Run layer 3: summarise the selected rulings, files first, then the database (D-061; docs/LAYER3.md).

1. The run reads the versions its profile pins: segment, summarise, verify (D-064), and the active suva_house preset
   version. Candidates while Q-17 is open: the top `limit` rulings of `population` by layer-2 score (score_raw,
   highest first) in the latest succeeded or partial layer2_judge run of the profile's pinned version, minus the
   engine's few-shot dockets (they are in every write prompt); or the given `dockets`. Plus the pending
   ops.user_request rows of kind summary: accepted into the run, then done or failed with the run id and a reason.
2. Per ruling: the primary text from corpus.ruling_text, the gegenstand and the matter rubric
   (corpus.subject_observation, neuheiten first), the own-splitter segmentation (segment V0.1.0), then the engine
   (src/summarize/engine.py, imported at run time only) through src/llm/ (G2), live or from the replay cache.
3. Files: data/runs/<run_id>/summaries.jsonl, calls.jsonl, messages.jsonl and manifest.json (SHA-256 of each).
4. One transaction (src/layer3/store.py): spans, blobs, LLM calls, segmentations, summaries, versions, texts,
   claims, citations, checks, the current-version switch, the requests, events and metrics. A version with a missing
   language is never stored: that ruling fails with its reason (D-067).
5. The run ends succeeded (every ruling stored or unchanged), partial (some failed or had no recorded answer), or
   failed (none stored). A failed run still commits, in one transaction before it is closed failed, every
   attempted ruling's span, the blobs and one ops.llm_call per call the engine made (also the calls an engine
   exception handed back, `engine_calls`), the requests' failure with their reasons, events and metrics. On any
   error the manifest is rewritten with status failed (aborted on Ctrl-C) and the error.
"""

from __future__ import annotations

import inspect
import json
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

from src.db.pg import ROOT, sha256_file, uuid5
from src.db.registry import pinned_version, profile_version
from src.db.runs import begin_run, events, fail_run, finish_run, metrics
from src.layer3 import segment as seg
from src.layer3.models import SegmentConfig, SummariseConfig, VerifyConfig, engine_code_paths
from src.layer3.presets import active_preset
from src.layer3.render import FicheRejected, plan_text, quality_status
from src.layer3.store import PRESET, Context, Work, cache_key, canonical_messages, load, messages_sha256, rule_ids
from src.llm.client import DEFAULT_STORE, ReplayMiss
from src.llm.served_model import canonical
from src.summarize.engine_types import EngineResult, RulingSource

STEP = "summarise"
RUNS_DIR = ROOT / "data" / "runs"
DEFAULT_POPULATION = "2026Q2_union"
DEFAULT_LIMIT = 10
_OWN_CODE = (
    "src/layer3/models.py",
    "src/layer3/presets.py",
    "src/layer3/render.py",
    "src/layer3/run.py",
    "src/layer3/segment.py",
    "src/layer3/store.py",
    "src/summarize/engine_types.py",
)
EMPTY_METRICS = ("rulings_in", "stored", "unchanged", "failed", "replay_misses", "verified_versions",
                 "flagged_versions", "llm_calls", "requests_done", "requests_failed")  # fmt: skip

Engine = Callable[..., EngineResult]


class Layer3RunFailed(RuntimeError):
    """No ruling could be summarised. The attempted rulings' spans and calls, the requests' failure, events and
    metrics are committed before the run is closed failed; no version is stored.
    `replay_only`: every ruling lacked a recorded answer (replay mode), so nothing was wrong but the cache."""

    def __init__(self, message: str, *, replay_only: bool = False) -> None:
        super().__init__(message)
        self.replay_only = replay_only


def code_paths() -> tuple[str, ...]:
    """The run's code identity (F-09): the writer, the contract and the engine's whole import closure, where its
    prompts live (src/layer3/models.py ENGINE_CODE_GLOBS)."""
    return tuple(sorted(set(_OWN_CODE) | set(engine_code_paths())))


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _config(cur: psycopg.Cursor, cvid: str, model: type) -> Any:
    cur.execute("SELECT config FROM ops.component_version WHERE component_version_id = %s", (cvid,))
    return model.model_validate(cur.fetchone()[0])


def layer2_source(cur: psycopg.Cursor, profile_code: str, layer2_cv: str) -> str | None:
    """The latest succeeded or partial layer-2 run of this profile that used the pinned layer2_judge version."""
    cur.execute(
        """SELECT pr.run_id::text FROM ops.pipeline_run pr
           JOIN ops.pipeline_profile_version pv ON pv.profile_version_id = pr.profile_version_id
           WHERE pr.kind = 'layer2' AND pr.status IN ('succeeded', 'partial') AND pv.profile_code = %s
             AND EXISTS (SELECT 1 FROM triage.assessment a WHERE a.run_id = pr.run_id AND a.step = 'layer2_judge'
                                                            AND a.component_version_id = %s)
           ORDER BY pr.finished_at DESC LIMIT 1""",
        (profile_code, layer2_cv),
    )
    row = cur.fetchone()
    return row[0] if row else None


def top_rulings(
    cur: psycopg.Cursor, layer2_run: str, population: str | None, limit: int, exclude: set[str]
) -> list[Work]:
    """The `limit` highest layer-2 scores of the run (within the population), the excluded dockets left out."""
    where, args = "", [layer2_run]
    if population:
        where = (
            "AND EXISTS (SELECT 1 FROM corpus.population_member m JOIN corpus.population p "
            "ON p.population_id = m.population_id WHERE m.ruling_id = r.ruling_id AND p.code = %s)"
        )
        args.append(population)
    cur.execute(
        f"""SELECT r.ruling_id::text, r.docket, a.score_raw FROM triage.assessment a
            JOIN corpus.ruling r ON r.ruling_id = a.ruling_id
            WHERE a.run_id = %s AND a.step = 'layer2_judge' AND a.outcome = 'ok' AND a.score_raw IS NOT NULL
              AND a.repetition_idx = 0 {where}
            ORDER BY a.score_raw DESC, r.docket, r.decision_date""",
        args,
    )
    out = [Work(rid, docket, rank_score=score) for rid, docket, score in cur.fetchall() if docket not in exclude]
    return out[:limit]


def docket_rulings(cur: psycopg.Cursor, dockets: list[str]) -> list[Work]:
    cur.execute(
        "SELECT ruling_id::text, docket FROM corpus.ruling WHERE docket = ANY(%s) ORDER BY docket, decision_date",
        (list(dockets),),
    )
    found = [Work(rid, docket) for rid, docket in cur.fetchall()]
    missing = sorted(set(dockets) - {w.docket for w in found})
    if missing:
        raise LookupError(f"not in corpus.ruling: {', '.join(missing)}")
    return found


def pending_requests(cur: psycopg.Cursor, *, lock: bool = False) -> list[tuple[str, str, str, str]]:
    """(request_id, ruling_id, docket, preset_code) of the pending summary requests, oldest first."""
    cur.execute(
        """SELECT q.request_id::text, q.ruling_id::text, r.docket, q.preset_code FROM ops.user_request q
           JOIN corpus.ruling r ON r.ruling_id = q.ruling_id
           WHERE q.kind = 'summary' AND q.status = 'pending' ORDER BY q.created_at"""
        + (" FOR UPDATE OF q SKIP LOCKED" if lock else ""),
    )
    return cur.fetchall()


def load_source(cur: psycopg.Cursor, w: Work) -> None:
    """Fill the ruling's identity, primary text, gegenstand and matter rubric from corpus.* (never from Apertus)."""
    cur.execute(
        """SELECT r.decision_date, r.language::text, r.gegenstand, t.text_id::text, t.content,
                  (SELECT so.rubric FROM corpus.subject_observation so WHERE so.ruling_id = r.ruling_id
                   ORDER BY (so.source = 'neuheiten') DESC LIMIT 1)
           FROM corpus.ruling r
           LEFT JOIN LATERAL (SELECT text_id, content FROM corpus.ruling_text x WHERE x.ruling_id = r.ruling_id
                              ORDER BY x.is_primary DESC, x.created_at LIMIT 1) t ON true
           WHERE r.ruling_id = %s""",
        (w.ruling_id,),
    )
    w.decision_date, w.language, w.title, w.text_id, w.text, w.matter = cur.fetchone()


def _call_engine(engine: Engine, source: RulingSource, available: dict[str, Any]) -> EngineResult:
    """Call the engine with the keyword arguments its signature names among `available` (mode, store, store_dir,
    client: built on first use). The engine's signature is the other owner's; the writer adapts to it."""
    params = inspect.signature(engine).parameters
    kwargs = {}
    for name, value in available.items():
        if name in params:
            kwargs[name] = value() if name == "client" else value
    return engine(source, **kwargs)


def _is_replay_miss(exc: BaseException) -> bool:
    seen: BaseException | None = exc
    while seen is not None:
        if isinstance(seen, ReplayMiss) or type(seen).__name__ == "ReplayMiss":
            return True
        seen = seen.__cause__ or seen.__context__
    return False


def summarise_one(
    w: Work, engine: Engine, available: dict[str, Any], preset, seg_cfg: SegmentConfig, segment_cv: str
) -> Work:
    """The engine on one ruling, then the plan of both texts. Never raises for an engine or a fiche problem."""
    w.started_at = _now()
    try:
        if not w.text or not w.text_id:
            w.outcome, w.reason_code, w.error = "failed", "ING_TEXT_MISSING", "no text: no call (G4)"
            return w
        w.segmentation = seg.split(w.text)
        source = RulingSource(
            ruling_id=w.ruling_id,
            docket=w.docket,
            decision_date=w.decision_date,
            language=w.language,
            text_id=w.text_id,
            text=w.text,
            title=w.title,
            matter=w.matter,
        )
        try:
            result = _call_engine(engine, source, available)
        except Exception as exc:  # the engine's failure is this ruling's, never the run's
            miss = _is_replay_miss(exc)
            w.outcome = "skipped" if miss else "failed"
            w.reason_code = "L3_REPLAY_MISS" if miss else "L3_ENGINE_FAILED"
            w.error = f"{type(exc).__name__}: {exc}"[:500]
            made = tuple(getattr(exc, "engine_calls", ()) or ())
            if made:  # the calls it made before it raised are stored all the same (one ops.llm_call each)
                version = str(getattr(exc, "engine_version", None) or "unknown")
                w.result = EngineResult(w.ruling_id, version, "failed", (), {}, made)
            return w
        w.result = result
        if result.ruling_id != w.ruling_id:
            w.outcome, w.reason_code = "failed", "L3_ENGINE_FAILED"
            w.error = f"the engine answered for ruling {result.ruling_id}"
            return w
        missing = [lang for lang in ("de", "fr") if lang not in result.fiches]
        if missing:
            w.outcome, w.reason_code = "failed", "L3_LANGUAGE_MISSING"
            w.error = f"no {' or '.join(missing)} fiche: a version is always a pair (D-067)"
            return w
        citable = {
            c.e_number: seg.consideration_id(seg.segmentation_id(w.text_id, segment_cv), c.ordinal)
            for c in w.segmentation.considerations
            if c.depth >= seg_cfg.min_citable_depth
        }
        propositions = {p.pid: p for p in result.propositions}
        call_ids = {c.call_id for c in result.calls}
        texts = []
        for lang in ("de", "fr"):
            plan = plan_text(
                result.fiches[lang],
                docket=w.docket,
                decision_date=w.decision_date,
                matter=w.matter or w.title,
                ruling_language=w.language or "",
                propositions=propositions,
                citable=citable,
                preset=preset,
            )
            for cid in (plan.write_call_id, plan.repair_call_id):
                if cid and cid not in call_ids:
                    raise FicheRejected("L3_FICHE_UNTRACED", f"the {lang} fiche names call {cid}, not in the result")
            texts.append(plan)
        w.texts, w.citable, w.quality = texts, citable, quality_status(texts)
        w.outcome = "ready"
    except FicheRejected as exc:
        w.outcome, w.reason_code, w.error = "failed", exc.reason_code, str(exc)[:500]
    except Exception as exc:  # a bug in this ruling's plan fails this ruling only; its calls are still stored
        w.outcome, w.reason_code, w.error = "failed", "L3_ENGINE_FAILED", f"{type(exc).__name__}: {exc}"[:500]
    finally:
        w.finished_at = _now()
    return w


def _write_files(run_dir: Path, works: list[Work], manifest: dict) -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    summaries, calls, blobs = [], [], {}
    for w in works:
        result = None
        if w.result is not None:
            result = {k: v for k, v in w.result.as_json().items() if k != "calls"}
            for c in w.result.calls:
                sha = messages_sha256(c.messages)
                blobs[sha] = canonical_messages(c.messages)
                record = {k: v for k, v in asdict(c).items() if k != "messages"}
                calls.append({"ruling_id": w.ruling_id, "messages_sha256": sha, "cache_key": cache_key(c)[0], **record})
        summaries.append(
            {
                "ruling_id": w.ruling_id,
                "docket": w.docket,
                "decision_date": str(w.decision_date) if w.decision_date else None,
                "rank_score": w.rank_score,
                "requests": w.requests,
                "outcome": w.outcome,
                "reason_code": w.reason_code,
                "error": w.error,
                "quality": w.quality,
                "segmentation": (
                    {
                        "status": w.segmentation.status,
                        "considerations": [c.e_number for c in w.segmentation.considerations],
                        "coverage_ratio": w.segmentation.coverage_ratio,
                    }
                    if w.segmentation
                    else None
                ),
                "texts": [asdict(t) for t in w.texts],
                "result": result,
                "started_at": w.started_at,
                "finished_at": w.finished_at,
            }
        )
    files = {
        "summaries.jsonl": [json.dumps(s, ensure_ascii=False, default=str) for s in summaries],
        "calls.jsonl": [json.dumps(c, ensure_ascii=False, sort_keys=True, default=str) for c in calls],
        "messages.jsonl": [json.dumps({"sha256": k, "content": blobs[k]}, ensure_ascii=False) for k in sorted(blobs)],
    }
    for name, lines in files.items():
        (run_dir / name).write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    manifest["files"] = {name: sha256_file(run_dir / name) for name in files}
    (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def _close_requests(cur: psycopg.Cursor, works: list[Work], labels: dict[str, str]) -> Counter:
    counts: Counter = Counter()
    for w in works:
        for rid in w.requests:
            if w.outcome in ("stored", "unchanged"):
                state = "done"
                detail = f"summary version {w.summary_version_id} ({w.outcome}, {w.quality})"
            else:
                state = "failed"
                detail = f"{w.reason_code}: {labels.get(w.reason_code or '', '')} {w.error or ''}".strip()[:500]
            cur.execute(
                "UPDATE ops.user_request SET status = %s, status_detail = %s WHERE request_id = %s",
                (state, detail, rid),
            )
            counts[state] += 1
    return counts


def _resolved_models(mode: str, declared: str) -> tuple[dict, bool]:
    """The large model the client will use (LLM_NAME), against the declared one (D-064)."""
    from src.llm.config import ConfigError, LLMConfig

    try:
        name = LLMConfig.from_env(mode).name  # type: ignore[arg-type]
    except ConfigError:
        if mode == "live":
            raise
        name = None
    used = name or declared
    return {role: used for role in ("generator", "repair", "judge")}, bool(name) and canonical(name) != canonical(
        declared
    )


def run_layer3(
    conn: psycopg.Connection,
    *,
    mode: str = "replay",
    profile: str = "default",
    population: str | None = DEFAULT_POPULATION,
    limit: int = DEFAULT_LIMIT,
    dockets: list[str] | None = None,
    requests: bool = True,
    actor: str = "pipeline",
    engine: Engine | None = None,
    few_shot: tuple[str, ...] | None = None,
    store: Path = DEFAULT_STORE,
    runs_dir: Path = RUNS_DIR,
    workers: int = 1,
) -> dict:
    """Summarise the selected rulings and the pending summary requests. `engine` and `few_shot` are for tests (a
    declared fake engine, G9); otherwise src.summarize.engine.summarise and src.summarize.examples are imported now."""
    if mode not in ("replay", "live"):
        raise ValueError("mode must be replay or live")
    if few_shot is None:
        from src.summarize.examples import FEW_SHOT_DOCKETS

        few_shot = tuple(FEW_SHOT_DOCKETS)
    exclude = set(few_shot)
    with conn.cursor() as cur:
        pvid, profile_label = profile_version(cur, profile)
        summarise_cv = pinned_version(cur, pvid, "summarise")
        verify_cv = pinned_version(cur, pvid, "verify")
        segment_cv = pinned_version(cur, pvid, "segment")
        layer2_cv = pinned_version(cur, pvid, "layer2_judge")
        s_cfg: SummariseConfig = _config(cur, summarise_cv, SummariseConfig)
        v_cfg: VerifyConfig = _config(cur, verify_cv, VerifyConfig)
        g_cfg: SegmentConfig = _config(cur, segment_cv, SegmentConfig)
        cur.execute(
            "SELECT version_label, (SELECT version_label FROM ops.component_version WHERE component_version_id = %s),"
            " (SELECT version_label FROM ops.component_version WHERE component_version_id = %s)"
            " FROM ops.component_version WHERE component_version_id = %s",
            (verify_cv, segment_cv, summarise_cv),
        )
        labels_v = dict(zip(("summarise", "verify", "segment"), cur.fetchone(), strict=True))
        cur.execute(
            """SELECT m.gateway_id FROM ops.component_version_model cvm JOIN ops.model m USING (model_id)
               WHERE cvm.component_version_id = %s AND cvm.model_role = 'generator'""",
            (summarise_cv,),
        )
        row = cur.fetchone()
        if row is None:
            raise LookupError(f"summarise {labels_v['summarise']}: no generator model bound (make db-registry)")
        declared = row[0]
        preset = active_preset(cur, PRESET)
        if preset is None:
            raise LookupError(f"preset {PRESET} has no active version (make db-registry)")
        rules = rule_ids(cur, verify_cv)
        layer2_run = None
        if dockets:
            todo = docket_rulings(cur, dockets)
            refused = [w.docket for w in todo if w.docket in exclude]
            if refused:
                raise LookupError(f"few-shot example dockets are never summarised (in every prompt): {refused}")
        else:
            layer2_run = layer2_source(cur, profile, layer2_cv)
            todo = top_rulings(cur, layer2_run, population, limit, exclude) if layer2_run else []
        waiting = pending_requests(cur) if requests else []
        cur.execute("SELECT code, label_de FROM ops.reason_code")
        labels = dict(cur.fetchall())
    conn.commit()
    if not todo and not waiting:
        if not dockets and layer2_run is None:
            raise LookupError("no succeeded layer-2 run of the pinned layer2_judge version: run layer 2 first")
        raise LookupError(f"nothing to summarise (population {population}, no pending summary request)")
    run_mode = "LIVE" if mode == "live" else "REPLAY"
    resolved, override = _resolved_models(mode, declared)
    run = begin_run(
        conn,
        profile_version_id=pvid,
        kind="summarise",
        step=STEP,
        operation="layer3.run",
        component_version_id=summarise_cv,
        params={
            "profile": profile,
            "profile_version": profile_label,
            "versions": labels_v,
            "preset": f"{PRESET} {preset[1]}",
            "population": population,
            "limit": limit,
            "dockets": dockets,
            "layer2_run": layer2_run,
            "few_shot_excluded": sorted(exclude),
            "requests": requests,
        },
        code_paths=code_paths(),
        actor=actor,
        mode=run_mode,
        resolved_models=resolved,
        model_override=override,
    )
    client_box: list = []
    client_lock = threading.Lock()
    works: list[Work] = []
    manifest: dict | None = None
    run_dir: Path | None = None
    try:
        by_ruling = {w.ruling_id: w for w in todo}
        rejected = 0
        if requests:
            with conn.transaction(), conn.cursor() as cur:
                for rid, ruling_id, docket, preset_code in pending_requests(cur, lock=True):
                    if preset_code != PRESET:
                        reason, state = "L3_PRESET_UNAVAILABLE", "rejected"
                    elif docket in exclude:
                        reason, state = "L3_FEW_SHOT_EXAMPLE", "rejected"
                    else:
                        reason, state = None, "accepted"
                    detail = f"{reason}: {labels.get(reason, '')}" if reason else f"accepted into run {run.run_id}"
                    cur.execute(
                        "UPDATE ops.user_request SET status = %s, run_id = %s, status_detail = %s "
                        "WHERE request_id = %s",
                        (state, run.run_id, detail, rid),
                    )
                    if state == "rejected":
                        rejected += 1
                        continue
                    by_ruling.setdefault(ruling_id, Work(ruling_id, docket)).requests.append(rid)
        works = list(by_ruling.values())
        with conn.cursor() as cur:
            for w in works:
                load_source(cur, w)
        conn.commit()
        if engine is None:
            from src.summarize.engine import summarise as engine  # imported at run time only (another owner)

        def make_client():
            from src.llm.client import LLMClient
            from src.llm.config import LLMConfig

            with client_lock:  # one client for the run (its limiter caps the concurrency, G2)
                if not client_box:
                    client_box.append(LLMClient(LLMConfig.from_env(mode), store_dir=store))  # type: ignore[arg-type]
                return client_box[0]

        available = {"mode": mode, "store": store, "store_dir": store, "client": make_client}
        t0 = time.monotonic()

        def one(w: Work) -> Work:
            done = summarise_one(w, engine, available, preset[2], g_cfg, segment_cv)
            print(
                f"layer3: {w.docket} {done.outcome}{' ' + done.reason_code if done.reason_code else ''} "
                f"({time.monotonic() - t0:.0f} s)",
                file=sys.stderr,
                flush=True,
            )
            return done

        if workers > 1 and len(works) > 1:
            with ThreadPoolExecutor(min(workers, len(works))) as pool:
                works = list(pool.map(one, works))
        else:
            works = [one(w) for w in works]
        ctx = Context(
            run=run,
            mode=run_mode,
            summarise_cv=summarise_cv,
            verify_cv=verify_cv,
            segment_cv=segment_cv,
            preset_version_id=preset[0],
            summarise=s_cfg,
            verify=v_cfg,
            rules=rules,
            min_citable_depth=g_cfg.min_citable_depth,
        )
        ready = [w for w in works if w.outcome == "ready"]
        manifest_base = {
            "run_id": run.run_id,
            "step": STEP,
            "versions": labels_v,
            "preset": f"{PRESET} {preset[1]}",
            "profile": f"{profile} {profile_label}",
            "mode": run_mode,
            "population": population,
            "layer2_run": layer2_run,
            "engine_declared": s_cfg.engine,
            "model_declared": declared,
            "model_resolved": resolved["generator"],
            "model_override": override,
        }
        run_dir = runs_dir / run.run_id
        manifest = _write_files(run_dir, works, manifest_base | {"status": "loading" if ready else "failed"})
        if not works:  # every pending request was rejected: nothing to write but their answer
            values = dict.fromkeys(EMPTY_METRICS, 0) | {"requests_rejected": rejected, "model_override": int(override)}
            with conn.transaction(), conn.cursor() as cur:
                metrics(cur, run, STEP, values)
                finish_run(cur, run, "succeeded")
            status = "succeeded"
        else:  # none ready: the attempted rulings' spans and calls are committed, then the run fails
            selection = {"todo": len(todo), "population": population, "limit": limit, "layer2_run": layer2_run}
            status, values = _load_run(conn, ctx, works, labels, manifest, rejected, override, selection)
            outcomes = {w.docket: [w.outcome, w.summary_version_id] for w in works}
            manifest = manifest | {"status": status, "metrics": values, "outcomes": outcomes}
            _write_manifest(run_dir, manifest)
            if not ready:
                reasons = Counter(w.reason_code for w in works)
                raise Layer3RunFailed(
                    f"no ruling summarised of {len(works)} ({dict(reasons)}); files in {run_dir}"
                    + ("; replay: run live or use the store that holds the answers" if reasons["L3_REPLAY_MISS"]
                       else ""),
                    replay_only=set(reasons) == {"L3_REPLAY_MISS"},
                )  # fmt: skip
    except BaseException as exc:
        aborted = isinstance(exc, KeyboardInterrupt)
        fail_run(conn, run, exc, status="aborted" if aborted else "failed")
        _fail_requests(conn, run.run_id, labels, exc, works)
        if manifest is not None and run_dir is not None:  # the run directory never says "loading" after a failure
            error = f"{type(exc).__name__}: {exc}"[:500]
            _write_manifest(run_dir, manifest | {"status": "aborted" if aborted else "failed", "error": error})
        raise
    finally:
        for client in client_box:
            client.close()
    return {
        "run_id": run.run_id,
        "status": status,
        "profile": f"{profile} {profile_label}",
        "versions": labels_v,
        "preset": f"{PRESET} {preset[1]}",
        "mode": run_mode,
        "model": resolved["generator"],
        "model_override": override,
        "layer2_run": layer2_run,
        **values,
        "dockets": {w.docket: w.outcome for w in works},
        "files": str(run_dir),
    }


def _load_run(
    conn: psycopg.Connection,
    ctx: Context,
    works: list[Work],
    labels: dict[str, str],
    manifest: dict,
    rejected: int,
    override: bool,
    selection: dict,
) -> tuple[str, dict]:
    """The run's one transaction: rows, requests, metrics, events, then the run closed succeeded or partial. With
    no ruling ready, status `failed`: everything but the run's closing is committed, and the caller fails the run
    (fail_run closes it after this commit, so the calls and spans stay)."""
    run = ctx.run
    ready = [w for w in works if w.outcome == "ready"]
    with conn.transaction(), conn.cursor() as cur:
        load(cur, ctx, works)
        outcomes = Counter(w.outcome for w in works)
        if not ready:
            status = "failed"
        else:
            status = "succeeded" if outcomes["failed"] == 0 and outcomes["skipped"] == 0 else "partial"
        req = _close_requests(cur, works, labels)
        calls = [c for w in works if w.result for c in w.result.calls]
        claims = [c for w in works if w.outcome == "stored" for t in w.texts for c in t.claims]
        values = {
            "rulings_in": len(works),
            "stored": outcomes["stored"],
            "unchanged": outcomes["unchanged"],
            "failed": outcomes["failed"],
            "replay_misses": outcomes["skipped"],
            "verified_versions": sum(1 for w in works if w.outcome == "stored" and w.quality == "verified"),
            "flagged_versions": sum(1 for w in works if w.outcome == "stored" and w.quality == "flagged"),
            "v2_fallback_fiches": sum(1 for w in works for t in w.texts if t.writer == "v2"),
            "llm_calls": len(calls),
            "cache_hits": sum(1 for c in calls if c.cache_hit),
            "live_calls": sum(1 for c in calls if not c.cache_hit and not c.error),
            "llm_errors": sum(1 for c in calls if c.error),
            "claims": len(claims),
            "claims_flagged": sum(1 for c in claims if c.status == "flagged"),
            "claims_cited": sum(1 for c in claims if c.citations),
            "checks_failed": sum(1 for c in claims for k in c.checks if k.status == "fail"),
            "removed_sentences": sum(  # sentences, not checks: one sentence may fail several codes
                len({c.detail.get("ordinal") for c in t.removed})
                for w in works
                if w.outcome == "stored"
                for t in w.texts
            ),
            "segmentations_ok": sum(1 for w in ready if w.segmentation and w.segmentation.status == "ok"),
            "segmentations_failed": sum(1 for w in ready if w.segmentation and w.segmentation.status != "ok"),
            "expert_current_kept": sum(1 for w in works if w.current_kept),
            "requests_done": req["done"],
            "requests_failed": req["failed"],
            "requests_rejected": rejected,
            "model_override": int(override),
        }
        rows = []
        for i, w in enumerate(works, start=10):
            span = uuid5(f"span|{run.run_id}|{w.ruling_id}|summarise")
            if w.outcome in ("stored", "unchanged"):
                rows.append(
                    (i, "info", f"layer3.summary.{w.outcome}", f"{w.quality} version {w.summary_version_id}",
                     {"quality": w.quality, "segmentation": w.segmentation.status if w.segmentation else None,
                      "writers": [t.writer for t in w.texts], "current_kept": w.current_kept}, w.ruling_id, span)
                )  # fmt: skip
            else:
                rows.append(
                    (i, "warning", "layer3.summary.not_made", labels.get(w.reason_code or "", ""),
                     {"outcome": w.outcome, "reason_code": w.reason_code}, w.ruling_id, span)
                )  # fmt: skip
        unknown = sorted({c for w in works for t in w.texts for c in t.unknown_checks})
        rows += [
            (1, "info", "layer3.run.selected",
             f"{len(works)} rulings ({selection['todo']} by score or docket, the rest requested)", selection, None,
             None),
            (2, "warning" if override or status != "succeeded" else "info", "layer3.run.summary",
             f"{outcomes['stored']} stored, {outcomes['unchanged']} unchanged, {outcomes['failed']} failed, "
             f"{outcomes['skipped']} without a recorded answer", values, None, None),
            (3, "info", "layer3.files.written", "summaries.jsonl, calls.jsonl, messages.jsonl", manifest["files"],
             None, None),
        ]  # fmt: skip
        if unknown:
            rows.append(
                (4, "warning", "layer3.checks.unknown", "check codes without a verify rule", {"codes": unknown},
                 None, None)
            )  # fmt: skip
        metrics(cur, run, STEP, values)
        events(cur, run, STEP, rows)
        if status != "failed":
            finish_run(cur, run, status)
    return status, values


def _write_manifest(run_dir: Path, manifest: dict) -> None:
    """The final manifest, after the commit: status, metrics and each ruling's outcome (the data files are as hashed
    before the load)."""
    (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _fail_requests(
    conn: psycopg.Connection, run_id: str, labels: dict[str, str], exc: BaseException, works: list[Work]
) -> None:
    """After a failed run: its accepted requests end failed with their ruling's reason, never left accepted."""
    generic = f"L3_ENGINE_FAILED: {labels.get('L3_ENGINE_FAILED', '')} run {run_id} failed: {exc}"[:500]
    own = {
        rid: f"{w.reason_code}: {labels.get(w.reason_code, '')} {w.error or ''}".strip()[:500]
        for w in works
        if w.reason_code
        for rid in w.requests
    }
    with conn.cursor() as cur:
        cur.execute(
            "SELECT request_id::text FROM ops.user_request WHERE run_id = %s AND status = 'accepted'", (run_id,)
        )
        for (rid,) in cur.fetchall():
            cur.execute(
                "UPDATE ops.user_request SET status = 'failed', status_detail = %s WHERE request_id = %s",
                (own.get(rid, generic), rid),
            )
    conn.commit()
