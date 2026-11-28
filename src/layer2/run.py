"""Run layer 2 over layer 1's candidates: files first, then the database (D-061; docs/LAYER2.md).

1. The run reads the `layer2_judge` version its profile pins: configuration, prompt, declared judge model (D-064).
2. Candidates: the `potentially` assessments of the latest succeeded layer-1 run that used the `layer1_filter`
   version the same profile pins (or a given layer-1 run). A layer-1 drop is never judged here (L2-D06).
3. One call per candidate through `src/llm/` (G2), live or from the replay cache (D-032). Every attempt and every
   cache hit is recorded (client observer). Failures and skips stay `potentially`, never a negative (D-063).
4. It writes `data/runs/<run_id>/`: `layer2_judgements.jsonl`, `llm_attempts.jsonl`, `messages.jsonl` (the exact
   messages, by SHA-256) and `manifest.json` (counts and SHA-256 of the three files).
5. It loads them in one transaction: spans (one per ruling, one per attempt), blobs, LLM calls, assessments,
   judgement details, events and metrics. All or nothing. Above `max_failed_share` failed calls, nothing but
   the failed run row reaches the database.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg

from src.db.pg import ROOT, sha256_file, sha256_text, uuid5
from src.db.registry import pinned_version, profile_version
from src.db.runs import Run, begin_run, events, fail_run, finish_run, metrics
from src.layer2.engine import (
    NoYesNoAnswer,
    build_messages,
    canonical_messages,
    explanation_de,
    fingerprint,
    messages_sha256,
    read_first_token,
    score_0_100,
)
from src.layer2.models import Layer2Config, Layer2JudgementRecord, Prompt, Reading
from src.llm.client import DEFAULT_STORE, InputRejected, LLMClient, LLMError, ReplayMiss
from src.llm.config import LLMConfig
from src.llm.served_model import ServedModelError, canonical

STEP = "layer2_judge"
# The step's code, for the run's code identity (F-09): begin_run records params.code_paths and params.code_sha256.
CODE_PATHS = ("src/layer2/engine.py", "src/layer2/models.py", "src/layer2/run.py")
PURPOSE = "relevance_judgement"
RUNS_DIR = ROOT / "data" / "runs"
# Replay mode, no recorded answer: the candidate is not judged in this run (no row, so an earlier judgement keeps its
# place in the label while the ruling's current layer-1 decision is the one it was judged on: an identical layer-1
# rerun keeps it, a changed decision does not; DDL-2), listed in replay_misses.jsonl and counted; never a failure
# (D-085, docs/LAYER2.md §4).
REPLAY_MISS = "L2_REPLAY_MISS"
BREAKER_CONSECUTIVE = 5  # live call failures in a row that stop a run: the gateway is down, not one ruling
PROGRESS_EVERY_S = 10.0
# error kind of the client (src/llm/client.py) -> work reason code (src/db/sql/95_seed_reference.sql)
ERROR_CODES = {
    "rate": "WORK_RATE_LIMITED",
    "timeout": "WORK_TIMEOUT",
    "server": "WORK_HTTP_ERROR",
    "network": "WORK_HTTP_ERROR",
    "auth": "WORK_HTTP_ERROR",
    "not_found": "WORK_HTTP_ERROR",
    "bad_request": "WORK_HTTP_ERROR",
    "json_format_unsupported": "WORK_HTTP_ERROR",
    "length": "WORK_PARSE_ERROR",
    "served_model_rejected": "WORK_MODEL_MISMATCH",
}
_CANDIDATES_SQL = """
SELECT a.assessment_id::text, r.ruling_id::text, r.docket, r.decision_date::text, r.language::text,
       t.text_id::text, t.content, t.content_sha256
FROM triage.assessment a
JOIN corpus.ruling r ON r.ruling_id = a.ruling_id
LEFT JOIN corpus.ruling_text t ON t.text_id = a.input_text_id
WHERE a.run_id = %s AND a.step = 'layer1_filter' AND a.in_suva_scope = 'potentially' AND a.repetition_idx = 0
{population}
ORDER BY r.docket, r.decision_date
"""


class Layer2RunFailed(RuntimeError):
    """The run could not judge enough candidates; nothing but the failed run row is in the database."""


@dataclass(frozen=True)
class Version:
    component_version_id: str
    label: str
    config: Layer2Config
    judge_model: str
    prompt: Prompt


@dataclass(frozen=True)
class Candidate:
    upstream_assessment_id: str
    ruling_id: str
    docket: str
    decision_date: str
    language: str
    text_id: str | None
    text: str | None
    text_sha256: str | None


@dataclass(frozen=True)
class Resolution:
    size: str
    requested: str | None
    override: bool


class _Attempts:
    """The client observer: collects every attempt and cache hit of this step, per (ruling, repetition)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_key: dict[tuple[str, int], list[dict]] = defaultdict(list)

    def __call__(self, record: dict) -> None:
        trace = record.get("trace") or {}
        if trace.get("step") == STEP:
            with self._lock:
                self._by_key[(trace["ruling_id"], trace["repetition"])].append(record)

    def pop(self, ruling_id: str, repetition: int) -> list[dict]:
        with self._lock:
            return self._by_key.pop((ruling_id, repetition), [])


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def load_version(cur: psycopg.Cursor, component_version_id: str) -> Version:
    cur.execute(
        "SELECT config, version_label FROM ops.component_version WHERE component_version_id = %s AND step = %s",
        (component_version_id, STEP),
    )
    row = cur.fetchone()
    if row is None:
        raise LookupError(f"{component_version_id} is not a {STEP} version")
    config, label = Layer2Config.model_validate(row[0]), row[1]
    cur.execute(
        """SELECT m.gateway_id FROM ops.component_version_model cvm JOIN ops.model m ON m.model_id = cvm.model_id
           WHERE cvm.component_version_id = %s AND cvm.model_role = 'judge'""",
        (component_version_id,),
    )
    judge = cur.fetchone()
    cur.execute(
        """SELECT p.prompt_version_id::text, p.role, p.version_label, p.template_sha256, p.system_template,
                  p.user_template
           FROM ops.component_version_prompt cvp
           JOIN ops.prompt_version p ON p.prompt_version_id = cvp.prompt_version_id
           WHERE cvp.component_version_id = %s AND cvp.prompt_role = 'question'""",
        (component_version_id,),
    )
    prompt = cur.fetchone()
    if judge is None or prompt is None:
        raise LookupError(f"{STEP} {label}: no judge model or question prompt bound (run make db-registry)")
    keys = ("prompt_version_id", "role", "version_label", "template_sha256", "system_template", "user_template")
    return Version(component_version_id, label, config, judge[0], Prompt(**dict(zip(keys, prompt, strict=True))))


def layer1_source(cur: psycopg.Cursor, profile_version_id: str, layer1_run: str | None = None) -> str:
    """The layer-1 run whose candidates are judged: given, or the latest succeeded one that used the
    `layer1_filter` version this profile version pins (same filter, same candidates)."""
    l1 = pinned_version(cur, profile_version_id, "layer1_filter")
    cur.execute(
        """SELECT pr.run_id::text FROM ops.pipeline_run pr
           WHERE pr.kind = 'layer1' AND pr.status = 'succeeded' AND (%s::uuid IS NULL OR pr.run_id = %s::uuid)
             AND EXISTS (SELECT 1 FROM triage.assessment a WHERE a.run_id = pr.run_id AND a.step = 'layer1_filter'
                                                            AND a.component_version_id = %s)
           ORDER BY pr.finished_at DESC LIMIT 1""",
        (layer1_run, layer1_run, l1),
    )
    row = cur.fetchone()
    if row is None:
        what = f"layer-1 run {layer1_run}" if layer1_run else "succeeded layer-1 run"
        raise LookupError(f"no {what} of the pinned layer1_filter version: run layer 1 first (make layer1)")
    return row[0]


def candidates(cur: psycopg.Cursor, layer1_run: str, populations: list[str] | None) -> list[Candidate]:
    """Layer 1's `potentially` rulings of that run, optionally only those in one of the populations."""
    where, args = "", [layer1_run]
    if populations:
        where = (
            "AND EXISTS (SELECT 1 FROM corpus.population_member m JOIN corpus.population p"
            " ON p.population_id = m.population_id WHERE m.ruling_id = r.ruling_id AND p.code = ANY(%s))"
        )
        args.append(list(populations))
    cur.execute(_CANDIDATES_SQL.format(population=where), args)
    return [Candidate(*row) for row in cur.fetchall()]


def resolve_model(cfg: LLMConfig, judge: str, store: Path) -> Resolution:
    """Which client size carries the declared judge. `small` first: the D-074 benchmark sent the 8B as the small
    model, and the size is part of the cache key. No match: LLM_NAME is used and the override recorded (D-064)."""
    names: dict[str, str | None] = {"small": cfg.name_small, "large": cfg.name}
    replay_models = store / "replay_models.json"
    if cfg.mode == "replay" and replay_models.is_file():
        known = json.loads(replay_models.read_text(encoding="utf-8"))
        names = {size: names[size] or known.get(size) for size in names}
    for size in ("small", "large"):
        if names[size] and canonical(names[size]) == canonical(judge):
            return Resolution(size, names[size], False)
    return Resolution("large", names["large"], True)


def _served(record: dict) -> tuple[str | None, str | None]:
    served = record.get("served") or {}
    return served.get("served"), served.get("header")


def judge_one(
    client: LLMClient,
    collector: _Attempts,
    c: Candidate,
    v: Version,
    res: Resolution,
    *,
    run_id: str,
    repetition: int,
    labels: dict[str, str],
) -> tuple[Layer2JudgementRecord, list[dict], str | None]:
    """One candidate: (record, attempt records, canonical messages). Never raises for a gateway or answer problem."""
    started = _now()
    cfg = v.config
    fp = fingerprint(v.component_version_id, v.prompt.template_sha256, res.requested, c.text_sha256, repetition)
    base = dict(
        run_id=run_id,
        ruling_id=c.ruling_id,
        docket=c.docket,
        decision_date=c.decision_date,
        language=c.language,
        repetition=repetition,
        upstream_assessment_id=c.upstream_assessment_id,
        text_id=c.text_id,
        text_sha256=c.text_sha256,
        input_fingerprint=fp,
        requested_model=res.requested,
    )
    if not c.text:
        rec = Layer2JudgementRecord(
            **base,
            outcome="skipped",
            reason_code="ING_TEXT_MISSING",
            score_source=None,
            score_raw=None,
            reading=None,
            prepared=None,
            messages_sha256=None,
            cache_key=None,
            served_model=None,
            attempts=0,
            cache_hit=None,
            input_tokens=None,
            latency_ms=None,
            error="no text: no call (G4)",
            explanation_de=explanation_de(
                outcome="skipped",
                version=v.label,
                model=None,
                reading=None,
                prepared=None,
                reason_label=labels.get("ING_TEXT_MISSING"),
            ),
            started_at=started,
            finished_at=_now(),
        )
        return rec, [], None
    messages, prepared = build_messages(c.docket, c.text, v.prompt, cfg.text_cap, cfg.neutralise_control_tags)
    msha = messages_sha256(messages)
    reading: Reading | None = None
    reason, error, result = None, None, None
    try:
        result = client.chat(
            messages,
            max_tokens=cfg.max_tokens,
            size=res.size,  # type: ignore[arg-type]
            prompt_version=cfg.client_prompt_version,
            logprobs=True,
            top_logprobs=cfg.top_logprobs,
            first_token_only=True,
            repetition=repetition,
            trace={"run_id": run_id, "ruling_id": c.ruling_id, "step": STEP, "repetition": repetition},
        )
        reading = read_first_token(result.logprobs, cfg.answer_tokens)
    except NoYesNoAnswer as exc:
        reason, error = "L2_FAIL_NO_YESNO_TOKEN", str(exc)
    except ReplayMiss as exc:
        reason, error = REPLAY_MISS, f"ReplayMiss: {exc}"[:500]
    except (LLMError, ServedModelError, InputRejected) as exc:
        reason, error = "L2_FAILED_CALL", f"{type(exc).__name__}: {exc}"[:500]
    attempts = collector.pop(c.ruling_id, repetition)
    final = next((a for a in reversed(attempts) if not a.get("error")), None)
    served = (result.served_model if result is not None else None) or (_served(final)[0] if final else None)
    usage = (final or {}).get("usage") or {}
    latency = (final or {}).get("latency_s")
    ok = reading is not None
    rec = Layer2JudgementRecord(
        **base,
        outcome="ok" if ok else ("skipped" if reason == REPLAY_MISS else "failed"),
        reason_code=None if ok else reason,
        score_source="judged" if ok else (None if reason == REPLAY_MISS else "failed"),
        score_raw=reading.logit if ok else None,
        score_0_100=score_0_100(reading) if ok else None,
        reading=reading,
        prepared=prepared,
        messages_sha256=msha,
        cache_key=result.cache_key if result is not None else None,
        served_model=served,
        attempts=len(attempts),
        cache_hit=bool(final and final.get("cache_hit")) if final else None,
        input_tokens=usage.get("prompt_tokens"),
        latency_ms=round(latency * 1000) if latency is not None else None,
        error=error,
        explanation_de=explanation_de(
            outcome="ok" if ok else ("skipped" if reason == REPLAY_MISS else "failed"),
            version=v.label,
            model=served,
            reading=reading,
            prepared=prepared,
            reason_label=labels.get(reason or ""),
        ),
        started_at=started,
        finished_at=_now(),
    )
    for a in attempts:  # the attempts file keeps the raw top 20 of a "no Ja/Nein" answer for the judgement row
        a.setdefault("messages_sha256", msha)
    if reason == "L2_FAIL_NO_YESNO_TOKEN" and result is not None and final is not None:
        final["raw_top_logprobs"] = _raw_top(result.logprobs)
    return rec, attempts, canonical_messages(messages)


def _raw_top(logprobs: Any) -> list:
    try:
        return [[t.get("token"), t.get("logprob")] for t in logprobs["content"][0]["top_logprobs"]]
    except (TypeError, KeyError, IndexError):
        return []


def _write(
    run_dir: Path,
    records: list[Layer2JudgementRecord],
    attempts: list[dict],
    blobs: dict[str, str],
    manifest: dict,
    misses: list[Layer2JudgementRecord] | None = None,
) -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    keep = ("ruling_id", "docket", "decision_date", "upstream_assessment_id", "messages_sha256", "error")
    files = {
        "layer2_judgements.jsonl": [rec.model_dump_json() for rec in records],
        "replay_misses.jsonl": [json.dumps({k: getattr(m, k) for k in keep}, ensure_ascii=False) for m in misses or []],
        "llm_attempts.jsonl": [json.dumps(a, ensure_ascii=False, sort_keys=True) for a in attempts],
        "messages.jsonl": [json.dumps({"sha256": k, "content": blobs[k]}, ensure_ascii=False) for k in sorted(blobs)],
    }
    for name, lines in files.items():
        (run_dir / name).write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    manifest["files"] = {name: sha256_file(run_dir / name) for name in files}
    (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def _attempt_window(a: dict) -> tuple[str, str]:
    """(started_at, ended_at) of one attempt: the log time is its end; the latency gives its start."""
    end = datetime.fromisoformat(a["at"])
    start = end - timedelta(seconds=a.get("latency_s") or 0)
    return start.isoformat(), end.isoformat()


def _load(
    cur: psycopg.Cursor,
    run: Run,
    v: Version,
    mode: str,
    records: list[Layer2JudgementRecord],
    attempts: list[dict],
    blobs: dict[str, str],
    labels: dict[str, str],
) -> None:
    """Spans, blobs, LLM calls, assessments and judgement details. Deterministic ids: a reload is a no-op."""
    by_ruling: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for a in attempts:
        by_ruling[(a["trace"]["ruling_id"], a["trace"]["repetition"])].append(a)
    cur.executemany(
        """INSERT INTO ops.blob (sha256, media_type, byte_size, content) VALUES (%s, 'application/json', %s, %s)
           ON CONFLICT DO NOTHING""",
        [(k, len(c.encode("utf-8")), c) for k, c in sorted(blobs.items())],
    )
    spans, calls, assessments, details, evts = [], [], [], [], []
    seq = 10
    for rec in records:
        span_id = uuid5(f"span|{run.run_id}|{rec.ruling_id}|{STEP}|{rec.repetition}")
        assessment_id = uuid5(f"assessment|{run.run_id}|{rec.ruling_id}|{STEP}|{rec.repetition}")
        status = {"ok": "ok", "failed": "error", "skipped": "skipped"}[rec.outcome]
        spans.append(
            (
                span_id,
                run.run_id,
                run.span_id,
                "layer2.judge",
                rec.ruling_id,
                v.component_version_id,
                status,
                rec.started_at,
                rec.finished_at,
                json.dumps(
                    {
                        "outcome": rec.outcome,
                        "cache_hit": rec.cache_hit,
                        "attempts": rec.attempts,
                        "truncation": rec.prepared.truncation if rec.prepared else None,
                    }
                ),
                rec.reason_code if rec.outcome != "ok" else None,
                (rec.error or "")[:500] or None,
            )
        )
        final_call = None
        for i, a in enumerate(by_ruling[(rec.ruling_id, rec.repetition)], start=1):
            call_id = uuid5(f"llm_call|{run.run_id}|{rec.ruling_id}|{rec.repetition}|{i}")
            call_span = uuid5(f"span|llm|{run.run_id}|{rec.ruling_id}|{rec.repetition}|{i}")
            start, end = _attempt_window(a)
            err = a.get("error")
            served, header = _served(a)
            usage = a.get("usage") or {}
            is_final = not err and a.get("cache_key") == rec.cache_key
            spans.append(
                (
                    call_span,
                    run.run_id,
                    span_id,
                    "llm.call",
                    rec.ruling_id,
                    v.component_version_id,
                    "error" if err else "ok",
                    start,
                    end,
                    json.dumps(
                        {
                            "attempt": a.get("attempt"),
                            "cache_hit": a.get("cache_hit"),
                            "http_status": a.get("status"),
                            "error": err,
                        }
                    ),
                    ERROR_CODES.get(err or "", "WORK_HTTP_ERROR") if err else None,
                    err,
                )
            )
            calls.append(
                (
                    call_id,
                    run.run_id,
                    call_span,
                    rec.ruling_id,
                    STEP,
                    PURPOSE,
                    v.config.question_language,
                    v.prompt.prompt_version_id,
                    a["cache_key"],
                    bool(a.get("cache_hit")),
                    "REPLAY" if a.get("cache_hit") else "LIVE",
                    a.get("endpoint") or "unknown",
                    a.get("requested") or rec.requested_model or "unknown",
                    served,
                    header,
                    json.dumps(a.get("params") or {}, sort_keys=True),
                    rec.repetition,
                    a.get("messages_sha256"),
                    a.get("content"),
                    a.get("finish_reason"),
                    (rec.outcome == "ok") if is_final else None,
                    rec.error if is_final and rec.reason_code == "L2_FAIL_NO_YESNO_TOKEN" else None,
                    a.get("status"),
                    ERROR_CODES.get(err or "", "WORK_HTTP_ERROR") if err else None,
                    max(1, int(a.get("attempt") or 1)),
                    usage.get("prompt_tokens"),
                    usage.get("completion_tokens"),
                    (usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
                    round(a["latency_s"] * 1000) if a.get("latency_s") is not None else None,
                    start,
                )
            )
            if is_final:
                final_call = (call_id, a)
            if err:
                evts.append(
                    (
                        seq,
                        "warning",
                        "llm.retry",
                        f"attempt {a.get('attempt')} failed: {err}",
                        {"attempt": a.get("attempt"), "http_status": a.get("status")},
                        rec.ruling_id,
                        call_span,
                    )
                )
                seq += 1
            elif a.get("cache_hit"):
                evts.append(
                    (seq, "debug", "llm.cache.hit", "answer from the replay cache", {}, rec.ruling_id, call_span)
                )
                seq += 1
        assessments.append(
            (
                assessment_id,
                run.run_id,
                rec.ruling_id,
                rec.repetition,
                v.component_version_id,
                span_id,
                rec.upstream_assessment_id,
                rec.text_id,
                rec.input_fingerprint,
                rec.outcome,
                rec.score_raw,
                rec.score_0_100,
                rec.score_source,
                rec.reason_code,
                rec.explanation_de,
                mode,
                rec.started_at,
                rec.finished_at,
            )
        )
        if final_call is not None and rec.prepared is not None:
            reading, a = rec.reading, final_call[1]
            top = reading.top_logprobs if reading else a.get("raw_top_logprobs") or []
            details.append(
                (
                    assessment_id,
                    final_call[0],
                    v.prompt.prompt_version_id,
                    rec.requested_model or "unknown",
                    rec.served_model,
                    v.config.question_language,
                    reading.logprob_yes if reading else None,
                    reading.logprob_no if reading else None,
                    reading.p_yes if reading else None,
                    json.dumps([list(t) for t in top]),
                    bool(reading and reading.yes_no_in_top),
                    rec.prepared.chars_total,
                    rec.prepared.chars_sent,
                    rec.prepared.truncation,
                    rec.input_tokens,
                )
            )
        if rec.prepared is not None:
            evts.append(
                (
                    seq,
                    "info",
                    "layer2.prompt.built",
                    "messages built from the primary text",
                    {**rec.prepared.model_dump(), "messages_sha256": rec.messages_sha256},
                    rec.ruling_id,
                    span_id,
                )
            )
            seq += 1
        if rec.outcome == "ok":
            evts.append(
                (
                    seq,
                    "debug",
                    "layer2.score",
                    f"p_yes {rec.reading.p_yes:.6g}",
                    {"p_yes": rec.reading.p_yes, "score_raw": rec.score_raw, "mass": rec.reading.mass},
                    rec.ruling_id,
                    span_id,
                )
            )
        elif rec.reason_code == "L2_FAIL_NO_YESNO_TOKEN":
            evts.append((seq, "warning", "layer2.yesno.missing", rec.error or "", {}, rec.ruling_id, span_id))
        else:
            evts.append(
                (
                    seq,
                    "warning",
                    "layer2.judgement.not_made",
                    labels.get(rec.reason_code or "", ""),
                    {"outcome": rec.outcome, "reason_code": rec.reason_code},
                    rec.ruling_id,
                    span_id,
                )
            )
        seq += 1
    cur.executemany(
        """INSERT INTO ops.span (span_id, run_id, parent_span_id, step, operation, ruling_id, component_version_id,
                                 status, started_at, ended_at, attributes, error_reason_code, error_message)
           VALUES (%s, %s, %s, 'layer2_judge', %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
        spans,
    )
    cur.executemany(
        """INSERT INTO ops.llm_call (llm_call_id, run_id, span_id, ruling_id, step, purpose, language,
               prompt_version_id, cache_key, cache_hit, mode, endpoint, model_role, requested_model,
               served_model, served_model_header, params, repetition_idx, messages_sha256, raw_output,
               finish_reason, parsed_ok, parse_error, http_status, error_reason_code, attempt, input_tokens,
               output_tokens, cached_tokens, latency_ms, started_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'judge', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                   %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT DO NOTHING""",
        calls,
    )
    cur.executemany(
        """INSERT INTO triage.assessment (assessment_id, run_id, ruling_id, step, repetition_idx,
               component_version_id, span_id, upstream_assessment_id, input_text_id, input_fingerprint,
               in_suva_scope, outcome, score_raw, score_0_100, score_source, reason_code, explanation_de, mode,
               started_at, finished_at)
           VALUES (%s, %s, %s, 'layer2_judge', %s, %s, %s, %s, %s, %s, 'potentially',
                   %s, %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT DO NOTHING""",
        assessments,
    )
    cur.executemany(
        """INSERT INTO triage.llm_judgement (assessment_id, llm_call_id, prompt_version_id, requested_model,
               served_model, question_language, logprob_yes, logprob_no, p_yes, top_logprobs, yes_no_in_top,
               text_chars_total, text_chars_sent, truncation, input_tokens)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
        details,
    )
    events(cur, run, STEP, evts)


def _call_failed(rec: Layer2JudgementRecord) -> bool:
    """A failed call to the gateway (not an answer without Ja/Nein, not a replay miss): counts for the breaker."""
    return rec.reason_code == "L2_FAILED_CALL" and not (rec.error or "").startswith("ReplayMiss")


def _judge_all(
    client: LLMClient,
    collector: _Attempts,
    todo: list[Candidate],
    v: Version,
    res: Resolution,
    *,
    run_id: str,
    repetition: int,
    labels: dict[str, str],
    workers: int,
    breaker: int,
) -> tuple[list[tuple], str | None]:
    """Judge every candidate. In live mode the first candidate with a text goes alone (preflight): a gateway that
    cannot answer stops the run after one ruling, not after hundreds of retried calls. Then the rest in parallel,
    stopped after `breaker` failed calls in a row, with a progress line on stderr every 10 s. Returns the results
    of the candidates attempted, in candidate order, and why the run stopped early (None if it did not)."""
    results: list[tuple | None] = [None] * len(todo)

    def one(c: Candidate) -> tuple:
        return judge_one(client, collector, c, v, res, run_id=run_id, repetition=repetition, labels=labels)

    first = next((i for i, c in enumerate(todo) if c.text), None)
    if client.cfg.mode == "live" and first is not None:
        results[first] = one(todo[first])
        if _call_failed(results[first][0]):
            return [results[first]], f"preflight: the first call failed ({results[first][0].error})"
    stop, lock = threading.Event(), threading.Lock()
    state = {"in_a_row": 0, "done": sum(r is not None for r in results), "failed": 0, "cache": 0}

    def task(i: int) -> tuple[int, tuple | None]:
        if stop.is_set():
            return i, None
        out = one(todo[i])
        with lock:
            state["in_a_row"] = state["in_a_row"] + 1 if _call_failed(out[0]) else 0
            state["done"] += 1
            state["failed"] += out[0].outcome == "failed"
            state["cache"] += bool(out[0].cache_hit)
            if state["in_a_row"] >= breaker:
                stop.set()
        return i, out

    pool = ThreadPoolExecutor(max(1, workers))
    t0 = last = time.monotonic()
    try:
        futures = [pool.submit(task, i) for i in range(len(todo)) if results[i] is None]
        for fut in as_completed(futures):
            i, out = fut.result()
            results[i] = out
            if time.monotonic() - last >= PROGRESS_EVERY_S:
                last = time.monotonic()
                print(
                    f"layer2: {state['done']}/{len(todo)} done, {state['failed']} failed, {state['cache']} from cache, "
                    f"{last - t0:.0f} s",
                    file=sys.stderr,
                    flush=True,
                )
    except BaseException:
        stop.set()
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    pool.shutdown(wait=True)
    done = [r for r in results if r is not None]
    reason = f"breaker: {breaker} calls failed in a row ({done[-1][0].error})" if stop.is_set() else None
    return done, reason


def _pct(values: list[float], q: float) -> float | None:
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))] if values else None


def run_layer2(
    conn: psycopg.Connection,
    *,
    profile: str = "default",
    population: list[str] | None = None,
    mode: str = "replay",
    limit: int | None = None,
    store: Path = DEFAULT_STORE,
    repetition: int = 0,
    kind: str = "layer2",
    layer1_run: str | None = None,
    workers: int | None = None,
    runs_dir: Path = RUNS_DIR,
    actor: str = "pipeline",
    client: LLMClient | None = None,
    max_failed_share: float | None = None,
    breaker: int = BREAKER_CONSECUTIVE,
) -> dict:
    """Judge layer 1's candidates. `client` is for tests (a declared mock transport, G9); otherwise the client is
    built from the environment (G3). `max_failed_share` overrides the version's value (recorded in the run)."""
    if kind not in ("layer2", "eval"):
        raise ValueError("kind must be layer2 (feeds the label) or eval (never does, L2-D06)")
    with conn.cursor() as cur:
        pvid, profile_label = profile_version(cur, profile)
        v = load_version(cur, pinned_version(cur, pvid, STEP))
        l1_run = layer1_source(cur, pvid, layer1_run)
        todo = candidates(cur, l1_run, population)[: limit or None]
        cur.execute("SELECT code, label_de FROM ops.reason_code")
        labels = dict(cur.fetchall())
    conn.commit()
    if not todo:
        where = f" in {', '.join(population)}" if population else ""
        raise LookupError(f"layer-1 run {l1_run} has no candidate{where}")
    collector = _Attempts()
    if client is None:
        client = LLMClient(LLMConfig.from_env(mode), store_dir=store, observer=collector)  # type: ignore[arg-type]
    else:
        client.observer = collector
    res = resolve_model(client.cfg, v.judge_model, client.store_dir)
    share = v.config.max_failed_share if max_failed_share is None else max_failed_share
    run_mode = "LIVE" if mode == "live" else "REPLAY"
    store_label = str(client.store_dir.relative_to(ROOT)) if client.store_dir.is_relative_to(ROOT) else "outside repo"
    params = {
        "profile": profile,
        "profile_version": profile_label,
        "version": v.label,
        "population": population,
        "limit": limit,
        "repetition": repetition,
        "layer1_run": l1_run,
        "store": store_label,
        "max_failed_share": share,
        "client_size": res.size,
    }
    run = begin_run(
        conn,
        profile_version_id=pvid,
        kind=kind,
        step=STEP,
        operation="layer2.run",
        component_version_id=v.component_version_id,
        params=params,
        code_paths=CODE_PATHS,
        actor=actor,
        mode=run_mode,
        resolved_models={"judge": res.requested},
        model_override=res.override,
    )
    try:
        n = min(workers or client.cfg.concurrency, client.cfg.concurrency)
        out, stopped = _judge_all(
            client,
            collector,
            todo,
            v,
            res,
            run_id=run.run_id,
            repetition=repetition,
            labels=labels,
            workers=n,
            breaker=breaker,
        )
        misses = [o[0] for o in out if o[0].reason_code == REPLAY_MISS]
        out = [o for o in out if o[0].reason_code != REPLAY_MISS]  # not judged in this run: no row (REPLAY_MISS)
        records = [o[0] for o in out]
        attempts = [a | {"index": i} for o in out for i, a in enumerate(o[1], start=1)]
        blobs = {o[0].messages_sha256: o[2] for o in out if o[2] is not None and o[0].messages_sha256}
        for sha, content in blobs.items():  # the blob key must be the hash the client logged
            if sha256_text(content) != sha:
                raise RuntimeError(f"messages hash mismatch for blob {sha[:12]}")
        outcomes = Counter(r.outcome for r in records)
        judged, failed = outcomes["ok"], outcomes["failed"]
        status = "succeeded" if failed == 0 and not misses else "partial"
        latencies = [r.latency_ms for r in records if r.latency_ms is not None and not r.cache_hit]
        values = {
            "rulings_in": len(records) + len(misses),
            "judged": judged,
            "failed": failed,
            "skipped": outcomes["skipped"],
            "replay_misses": len(misses),
            "llm_attempts": len(attempts),
            "llm_errors": sum(1 for a in attempts if a.get("error")),
            "cache_hits": sum(1 for a in attempts if a.get("cache_hit")),
            "live_calls": sum(1 for a in attempts if not a.get("cache_hit") and not a.get("error")),
            "tokens_in": sum(r.input_tokens or 0 for r in records if not r.cache_hit),
            "truncated": sum(1 for r in records if r.prepared and r.prepared.truncation != "none"),
            "neutralised": sum(1 for r in records if r.prepared and r.prepared.neutralised),
            "model_override": int(res.override),
        }
        for key, q in (("latency_p50_ms", 0.5), ("latency_p95_ms", 0.95)):
            if (p := _pct(latencies, q)) is not None:
                values[key] = p
        manifest = _write(
            runs_dir / run.run_id,
            records,
            attempts,
            blobs,
            {
                "run_id": run.run_id,
                "step": STEP,
                "version": v.label,
                "profile": profile,
                "profile_version": profile_label,
                "kind": kind,
                "mode": run_mode,
                "population": population,
                "layer1_run": l1_run,
                "judge_declared": v.judge_model,
                "judge_requested": res.requested,
                "model_override": res.override,
                "client_size": res.size,
                "prompt": f"{v.prompt.role} {v.prompt.version_label}",
                "prompt_template_sha256": v.prompt.template_sha256,
                "status": status,
                "metrics": values,
            },
            misses,
        )
        if stopped:
            raise Layer2RunFailed(
                f"stopped after {len(records)} of {len(todo)} candidates, {stopped}; files in {runs_dir / run.run_id}"
            )
        if misses and not records:
            raise Layer2RunFailed(
                f"replay: none of the {len(misses)} candidates has a recorded answer in this store; run live or use "
                f"the store that holds them (--store); files in {runs_dir / run.run_id}"
            )
        if judged == 0 or failed > share * len(records):
            raise Layer2RunFailed(
                f"{failed} of {len(records)} judgements failed (allowed share {share}); "
                f"files in {runs_dir / run.run_id}; rerun the same command to retry (answered calls replay)"
            )
        with conn.transaction(), conn.cursor() as cur:
            _load(cur, run, v, run_mode, records, attempts, blobs, labels)
            metrics(cur, run, STEP, values)
            events(
                cur,
                run,
                STEP,
                [
                    (
                        1,
                        "info",
                        "layer2.model.resolved",
                        f"judge {res.requested} as {res.size}",
                        {"declared": v.judge_model, "requested": res.requested, "override": res.override},
                        None,
                        None,
                    ),
                    (
                        2,
                        "warning" if res.override else "info",
                        "layer2.run.summary",
                        f"{judged} judged, {failed} failed, {outcomes['skipped']} skipped",
                        values,
                        None,
                        None,
                    ),
                    (
                        3,
                        "info",
                        "layer2.files.written",
                        "layer2_judgements.jsonl, llm_attempts.jsonl, messages.jsonl, replay_misses.jsonl",
                        manifest["files"],
                        None,
                        None,
                    ),
                ]
                + (
                    [
                        (
                            4,
                            "warning",
                            "layer2.replay.missing",
                            f"{len(misses)} candidates have no recorded answer in this store: not judged in this run",
                            {"count": len(misses), "store": store_label, "first": [m.docket for m in misses[:10]]},
                            None,
                            None,
                        )
                    ]
                    if misses
                    else []
                ),
            )
            finish_run(cur, run, status)
    except BaseException as exc:  # Ctrl-C included: the run row never stays `running`
        fail_run(conn, run, exc, status="aborted" if isinstance(exc, KeyboardInterrupt) else "failed")
        raise
    finally:
        if client is not None:
            client.close()
    return {
        "run_id": run.run_id,
        "status": status,
        "version": v.label,
        "profile": f"{profile} {profile_label}",
        "layer1_run": l1_run,
        "judge": res.requested,
        "model_override": res.override,
        "mode": run_mode,
        **values,
        "files": str(runs_dir / run.run_id),
    }
