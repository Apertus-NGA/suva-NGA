"""Layer 3's database load: one transaction for a whole run (docs/LAYER3.md; DB plan §13.5, §14).

Per ruling attempted: its span; the blobs of the messages and one ops.llm_call per CallRecord, each under its own
span (the summarise step for record and write calls, the verify step for verify and entailment calls). Per ruling
summarised: its segmentation (segment V0.1.0, reused when stored), summ.summary (uuid5 of ruling and preset), one
summ.summary_version with its German and French summ.summary_text, one summ.summary_claim per kept sentence, its
summ.claim_citation rows and its summ.verification_check rows (rule V3_<CODE>), one text-level check per removed
sentence; then the new version is made current (the previous current one unset first: the one-current index is not
deferrable), unless the current version is an expert edit. A rerun whose texts, versions and segmentation equal the
latest pipeline version adds nothing (`unchanged`), whether or not an expert edit is current. The pair check (one
German and one French text) is a deferred trigger: a version is all or nothing at commit.

A ruling that failed after the engine made calls (a missing language, an untraced fiche, a replay miss, an engine
bug: the engine hands its calls back) still gets its span, blobs and one ops.llm_call per call. `parsed_ok` is false
for an answer the engine rejected (client_log.invalid_answer, or followed by its "/retry"); `parse_error` holds that
reason or a parse failure of the client (`length`, `json_format_unsupported`), never an HTTP error kind (those are
`error_reason_code`). A call refused before any attempt (a replay miss) carries the run's mode, not LIVE.

Ids are deterministic (uuid5 of the run, the ruling and the position), so a reload of the same run is refused by
primary keys rather than duplicated.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psycopg

from src.db.pg import uuid5
from src.db.runs import Run
from src.layer3 import segment as seg
from src.layer3.models import CHECK_CODES, SummariseConfig, VerifyConfig, rule_code
from src.layer3.render import TextPlan
from src.llm.client import ENDPOINT
from src.llm.served_model import canonical
from src.summarize.engine_types import CallRecord, EngineResult

PRESET = "suva_house"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


@dataclass
class Work:
    """One ruling of the run, from selection to storage."""

    ruling_id: str
    docket: str
    requests: list[str] = field(default_factory=list)  # ops.user_request ids this ruling answers
    rank_score: float | None = None  # layer-2 score_raw that selected it (None: a request or a docket)
    decision_date: Any = None
    language: str | None = None
    text_id: str | None = None
    text: str | None = None
    title: str | None = None
    matter: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    outcome: str = "pending"  # stored | unchanged | failed | skipped
    reason_code: str | None = None
    error: str | None = None
    result: EngineResult | None = None
    segmentation: seg.Segmentation | None = None
    texts: list[TextPlan] = field(default_factory=list)
    citable: dict[str, str] = field(default_factory=dict)  # e_number -> consideration id the plan cited
    quality: str | None = None
    summary_version_id: str | None = None
    current_kept: bool = False  # the current version is an expert edit and stays current


@dataclass(frozen=True)
class Context:
    run: Run
    mode: str  # LIVE | REPLAY
    summarise_cv: str
    verify_cv: str
    segment_cv: str
    preset_version_id: str
    summarise: SummariseConfig
    verify: VerifyConfig
    rules: dict[str, str]  # check code -> ops.rule id
    min_citable_depth: int


def canonical_messages(messages: Any) -> str:
    return json.dumps(list(messages), sort_keys=True, ensure_ascii=False)


def messages_sha256(messages: Any) -> str:
    return hashlib.sha256(canonical_messages(messages).encode("utf-8")).hexdigest()


def _client_log(call: CallRecord) -> dict:
    """What the engine copied from the client's log record (src/summarize/engine.py `Calls`): cache_key, attempt,
    mode, endpoint, http_status, finish_reason, served_model_header, messages_sha256, attempted."""
    log = (call.params or {}).get("client_log")
    return log if isinstance(log, dict) else {}


def request_params(call: CallRecord) -> dict:
    """The request parameters of a call, without the engine's copy of the client log."""
    return {k: v for k, v in (call.params or {}).items() if k != "client_log"}


def cache_key(call: CallRecord) -> tuple[str, str]:
    """(key, source) of one call: the client's key the engine copied (client_log), else the client's formula
    (src/llm/client.py `chat`) recomputed from the record, for a call refused before any attempt."""
    given = _client_log(call).get("cache_key") or (call.params or {}).get("cache_key")
    if isinstance(given, str) and _HEX64.match(given):
        return given, "client"
    params = request_params(call)
    params.pop("cache_key", None)
    schema_version = params.pop("schema_version", "")
    repetition = params.pop("repetition", 0)
    first_token_only = params.pop("first_token_only", False)
    key = {
        "model": canonical(call.requested_model) if call.requested_model else "",
        "size": call.size,
        "messages": list(call.messages),
        "params": params,
        "prompt_version": call.prompt_version,
        "schema_version": schema_version,
        "repetition": repetition,
        "first_token_only": first_token_only,
    }
    digest = hashlib.sha256(json.dumps(key, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return digest, "writer_formula"


# error kind of the client (src/llm/client.py; the engine copies it into CallRecord.error) -> work reason code
ERROR_KINDS = {
    "rate": "WORK_RATE_LIMITED",
    "timeout": "WORK_TIMEOUT",
    "length": "WORK_PARSE_ERROR",
    "served_model_rejected": "WORK_MODEL_MISMATCH",
}


PARSE_KINDS = ("length", "json_format_unsupported")  # client error kinds that are parse failures, not HTTP ones


def error_code(error: str | None) -> str | None:
    """Work reason code of a failed call (src/db/sql/95_seed_reference.sql)."""
    if not error:
        return None
    if error in ERROR_KINDS:
        return ERROR_KINDS[error]
    if error.startswith("ReplayMiss"):
        return "L3_REPLAY_MISS"
    text = error.lower()
    if "timeout" in text:
        return "WORK_TIMEOUT"
    if "ratelimit" in text or "rate limit" in text or "429" in text:
        return "WORK_RATE_LIMITED"
    if "servedmodel" in text or "served_model" in text:
        return "WORK_MODEL_MISMATCH"
    if any(word in text for word in ("length", "json", "parse")):
        return "WORK_PARSE_ERROR"
    return "WORK_HTTP_ERROR"


def _window(started: str | None, finished: str | None) -> tuple[str, str]:
    start = datetime.fromisoformat(started) if started else datetime.fromisoformat(finished or "")
    end = datetime.fromisoformat(finished) if finished else start
    return start.isoformat(), max(start, end).isoformat()


def rejected_answers(calls: tuple[CallRecord, ...] | list[CallRecord]) -> dict[str, str]:
    """{call_id: why} of the answers the engine rejected: marked by the engine (client_log.invalid_answer), or
    followed in the same language by a call of the same prompt version plus "/retry" (refine/model.py `ask`)."""
    out = {c.call_id: str(_client_log(c)["invalid_answer"]) for c in calls if _client_log(c).get("invalid_answer")}
    for j, later in enumerate(calls):
        if not later.prompt_version.endswith("/retry"):
            continue
        base = later.prompt_version.removesuffix("/retry")
        for earlier in reversed(calls[:j]):
            if earlier.prompt_version == base and earlier.language == later.language and earlier.error is None:
                out.setdefault(earlier.call_id, "invalid answer, retried")
                break
    return out


def call_id(run_id: str, ruling_id: str, call: CallRecord) -> str:
    return uuid5(f"llm_call|{run_id}|{ruling_id}|{call.call_id}")


_SPAN_SQL = """INSERT INTO ops.span (span_id, run_id, parent_span_id, step, operation, ruling_id, component_version_id,
                                     status, started_at, ended_at, attributes, error_reason_code, error_message)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""


def _calls(cur: psycopg.Cursor, ctx: Context, w: Work, ruling_span: str) -> dict[str, str]:
    """Blobs, call spans and ops.llm_call rows of one ruling. Returns {CallRecord.call_id: llm_call_id}."""
    assert w.result is not None
    blobs = {messages_sha256(c.messages): canonical_messages(c.messages) for c in w.result.calls}
    cur.executemany(
        "INSERT INTO ops.blob (sha256, media_type, byte_size, content) VALUES (%s, 'application/json', %s, %s) "
        "ON CONFLICT DO NOTHING",
        [(k, len(v.encode("utf-8")), v) for k, v in sorted(blobs.items())],
    )
    ids, spans, rows = {}, [], []
    verify_purposes = set(ctx.summarise.verify_purposes)
    rejected = rejected_answers(w.result.calls)
    for i, call in enumerate(w.result.calls, start=1):
        lid = call_id(ctx.run.run_id, w.ruling_id, call)
        ids[call.call_id] = lid
        step = "verify" if call.purpose in verify_purposes else "summarise"
        cv = ctx.verify_cv if step == "verify" else ctx.summarise_cv
        span = uuid5(f"span|llm|{ctx.run.run_id}|{w.ruling_id}|{i}")
        start, end = _window(call.started_at, call.finished_at)
        code = error_code(call.error)
        spans.append(
            (
                span,
                ctx.run.run_id,
                ruling_span,
                step,
                "llm.call",
                w.ruling_id,
                cv,
                "error" if call.error else "ok",
                start,
                end,
                json.dumps({"purpose": call.purpose, "prompt": call.prompt_version, "cache_hit": call.cache_hit}),
                code,
                (call.error or "")[:500] or None,
            )
        )
        key, key_source = cache_key(call)
        log = _client_log(call)
        usage = call.usage or {}
        language = call.language if call.language in ("de", "fr", "it") else None
        params = {**request_params(call), "prompt_tag": call.prompt_version, "size": call.size}
        params["cache_key_source"] = key_source
        attempt = log.get("attempt")
        if call.cache_hit:
            mode = "REPLAY"
        elif log.get("attempted") is False:  # refused before any attempt (a replay miss): no gateway call
            mode = ctx.mode
        else:
            mode = "LIVE"
        invalid = rejected.get(call.call_id)
        parse_error = invalid or (call.error if call.error in PARSE_KINDS else None)
        parsed_ok = False if invalid else (None if call.error else call.response_text is not None)
        rows.append(
            (
                lid,
                ctx.run.run_id,
                span,
                w.ruling_id,
                step,
                call.purpose,
                language,
                key,
                call.cache_hit,
                mode,
                log.get("endpoint") or ENDPOINT,
                ctx.summarise.call_roles.get(call.purpose),  # type: ignore[call-overload]
                call.requested_model or "unknown",
                call.served_model,
                log.get("served_model_header"),
                json.dumps(params, sort_keys=True, default=str),
                messages_sha256(call.messages),
                call.response_text,
                log.get("finish_reason"),
                parsed_ok,
                (parse_error or "")[:500] or None,
                log.get("http_status"),
                code,
                max(1, int(attempt)) if isinstance(attempt, int) else 1,
                usage.get("prompt_tokens"),
                usage.get("completion_tokens"),
                (usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
                call.latency_ms,
                start,
            )
        )
    cur.executemany(_SPAN_SQL, spans)
    cur.executemany(
        """INSERT INTO ops.llm_call (llm_call_id, run_id, span_id, ruling_id, step, purpose, language, cache_key,
               cache_hit, mode, endpoint, model_role, requested_model, served_model, served_model_header, params,
               messages_sha256, raw_output, finish_reason, parsed_ok, parse_error, http_status, error_reason_code,
               attempt, input_tokens, output_tokens, cached_tokens, latency_ms, started_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                   %s, %s, %s, %s, %s)""",
        rows,
    )
    return ids


_VERSION_SQL = """SELECT v.summary_version_id::text, v.origin::text, v.component_version_id::text,
                  v.preset_version_id::text, v.source_segmentation_id::text,
                  max(t.title_line) FILTER (WHERE t.language = 'de'), max(t.body) FILTER (WHERE t.language = 'de'),
                  max(t.title_line) FILTER (WHERE t.language = 'fr'), max(t.body) FILTER (WHERE t.language = 'fr')
           FROM summ.summary_version v JOIN summ.summary_text t USING (summary_version_id)
           WHERE v.summary_id = %s AND {where} GROUP BY 1, 2, 3, 4, 5 ORDER BY max(v.version_no) DESC LIMIT 1"""


def _current(cur: psycopg.Cursor, summary_id: str, *, latest_pipeline: bool = False) -> dict | None:
    """The current version of the summary, or (`latest_pipeline`) its latest version the pipeline wrote."""
    where = "v.creator_kind = 'pipeline'" if latest_pipeline else "v.is_current"
    cur.execute(_VERSION_SQL.format(where=where), (summary_id,))
    row = cur.fetchone()
    if row is None:
        return None
    keys = ("id", "origin", "cv", "preset", "segmentation", "title_de", "body_de", "title_fr", "body_fr")
    return dict(zip(keys, row, strict=True))


def _remap(planned: dict[str, str], stored: dict[str, str]) -> dict[str, str]:
    """Planned consideration id -> stored one, by the court's numbering. Equal when the segmentation was written
    now; a reused segmentation keeps its own ids, and a number it does not hold is not cited."""
    return {cid: stored[e] for e, cid in planned.items() if e in stored}


def _store_version(cur: psycopg.Cursor, ctx: Context, w: Work, ruling_span: str, calls: dict[str, str]) -> None:
    """Segmentation, summary, version, texts, claims, citations, checks; then the current-version switch."""
    assert w.segmentation is not None and w.text_id is not None
    run_id = ctx.run.run_id
    seg_span = uuid5(f"span|{run_id}|{w.ruling_id}|segment")
    verify_span = uuid5(f"span|{run_id}|{w.ruling_id}|verify")
    sid = seg.segmentation_id(w.text_id, ctx.segment_cv)
    cur.execute("SELECT status::text, consideration_count FROM corpus.segmentation WHERE segmentation_id = %s", (sid,))
    existing = cur.fetchone()
    seg_status, seg_count = existing or (w.segmentation.status, len(w.segmentation.considerations))
    start, end = _window(w.started_at, w.finished_at)
    cur.executemany(  # spans first: the segmentation and the checks point to them
        _SPAN_SQL,
        [
            (
                seg_span,
                run_id,
                ruling_span,
                "segment",
                "segment.split",
                w.ruling_id,
                ctx.segment_cv,
                "ok" if seg_status == "ok" else "error",
                start,
                start,
                json.dumps({"status": seg_status, "considerations": seg_count, "reused": existing is not None}),
                "ING_CONSIDERATIONS_MISSING" if seg_status != "ok" else None,
                None,
            ),
            (
                verify_span,
                run_id,
                ruling_span,
                "verify",
                "verify.checks",
                w.ruling_id,
                ctx.verify_cv,
                "ok",
                end,
                end,
                json.dumps({"claims": sum(len(t.claims) for t in w.texts)}),
                None,
                None,
            ),
        ],
    )
    stored = seg.store(
        cur,
        text_id=w.text_id,
        component_version_id=ctx.segment_cv,
        run_id=run_id,
        span_id=seg_span,
        seg=w.segmentation,
        min_citable_depth=ctx.min_citable_depth,
    )
    remap = _remap(w.citable, stored.citable)
    summary_id = uuid5(f"summary|{w.ruling_id}|{PRESET}")
    cur.execute(
        "INSERT INTO summ.summary (summary_id, ruling_id, preset_code) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
        (summary_id, w.ruling_id, PRESET),
    )
    current = _current(cur, summary_id)  # decides whether an expert edit stays current
    latest = _current(cur, summary_id, latest_pipeline=True)  # what a rerun compares with (never an expert's text)
    by_lang = {t.language: t for t in w.texts}
    if (
        ctx.summarise.skip_unchanged
        and latest is not None
        and (latest["cv"], latest["preset"], latest["segmentation"])
        == (ctx.summarise_cv, ctx.preset_version_id, stored.segmentation_id)
        and all(
            (latest[f"title_{lang}"], latest[f"body_{lang}"]) == (by_lang[lang].title_line, by_lang[lang].body)
            for lang in ("de", "fr")
        )
    ):
        w.outcome, w.summary_version_id = "unchanged", latest["id"]
        return
    vid = uuid5(f"summary_version|{run_id}|{w.ruling_id}|{PRESET}")
    cur.execute(
        """INSERT INTO summ.summary_version (summary_version_id, summary_id, version_no, origin, parent_version_id,
               preset_version_id, component_version_id, source_segmentation_id, creator_kind, creator_run_id,
               quality_status, is_current, mode, span_id)
           VALUES (%s, %s, NULL, 'generated', NULL, %s, %s, %s, 'pipeline', %s, %s, false, %s, %s)""",
        (vid, summary_id, ctx.preset_version_id, ctx.summarise_cv, stored.segmentation_id, run_id, w.quality, ctx.mode,
         ruling_span),
    )  # fmt: skip
    texts, claims, citations, checks = [], [], [], []
    for plan in w.texts:
        tid = uuid5(f"summary_text|{vid}|{plan.language}")
        texts.append(
            (
                tid,
                vid,
                plan.language,
                plan.title_line,
                plan.body,
                plan.word_count,
                plan.paragraph_count,
                calls[plan.write_call_id] if plan.write_call_id else None,
                calls[plan.repair_call_id] if plan.repair_call_id else None,
            )
        )
        for claim in plan.claims:
            cid = uuid5(f"summary_claim|{tid}|{claim.ordinal}")
            claims.append(
                (cid, tid, claim.ordinal, claim.paragraph_no, claim.section, claim.model_text, claim.rendered_text,
                 claim.status)
            )  # fmt: skip
            cited = list(dict.fromkeys(remap[c] for c in claim.citations if c in remap))
            citations += [(cid, cons, n) for n, cons in enumerate(cited, start=1)]
            for check in claim.checks:
                if check.check in ctx.rules:
                    checks.append(
                        (uuid5(f"verification_check|{cid}|{check.check}"), "claim", cid, None, ctx.rules[check.check],
                         check.status, json.dumps(check.detail, ensure_ascii=False), run_id, verify_span)
                    )  # fmt: skip
        for i, check in enumerate(plan.removed, start=1):
            if check.check in ctx.rules:
                checks.append(
                    (uuid5(f"verification_check|{tid}|removed|{i}"), "text", None, tid, ctx.rules[check.check],
                     check.status, json.dumps(check.detail, ensure_ascii=False), run_id, verify_span)
                )  # fmt: skip
    cur.executemany(
        """INSERT INTO summ.summary_text (summary_text_id, summary_version_id, language, title_line, body, word_count,
               paragraph_count, llm_call_id, repair_llm_call_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        texts,
    )
    cur.executemany(
        """INSERT INTO summ.summary_claim (claim_id, summary_text_id, ordinal, paragraph_no, section, model_text,
               rendered_text, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        claims,
    )
    cur.executemany(
        "INSERT INTO summ.claim_citation (claim_id, consideration_id, ordinal) VALUES (%s, %s, %s)", citations
    )
    cur.executemany(
        """INSERT INTO summ.verification_check (check_id, target_kind, claim_id, summary_text_id, rule_id, status,
               detail, run_id, span_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        checks,
    )
    w.outcome, w.summary_version_id = "stored", vid
    if current is not None and current["origin"] == "expert_edit" and ctx.summarise.keep_expert_current:
        w.current_kept = True
        return
    cur.execute(
        "UPDATE summ.summary_version SET is_current = false WHERE summary_id = %s AND is_current AND "
        "summary_version_id <> %s",
        (summary_id, vid),
    )
    cur.execute("UPDATE summ.summary_version SET is_current = true WHERE summary_version_id = %s", (vid,))


def load(cur: psycopg.Cursor, ctx: Context, works: list[Work]) -> None:
    """Everything of one run's attempted rulings, in the caller's transaction."""
    for w in works:
        if w.outcome == "pending":
            raise RuntimeError(f"{w.docket}: not attempted, cannot be loaded")
        ruling_span = uuid5(f"span|{ctx.run.run_id}|{w.ruling_id}|summarise")
        start, end = _window(w.started_at, w.finished_at)
        status = {"failed": "error", "skipped": "skipped"}.get(w.outcome, "ok")
        cur.execute(
            _SPAN_SQL,
            (
                ruling_span,
                ctx.run.run_id,
                ctx.run.span_id,
                "summarise",
                "layer3.summarise",
                w.ruling_id,
                ctx.summarise_cv,
                status,
                start,
                end,
                json.dumps(
                    {
                        "calls": len(w.result.calls) if w.result else 0,
                        "engine": w.result.engine_version if w.result else None,
                        "record_status": w.result.record_status if w.result else None,
                        "quality": w.quality,
                        "requests": len(w.requests),
                    }
                ),
                w.reason_code if w.outcome in ("failed", "skipped") else None,
                (w.error or "")[:500] or None,
            ),
        )
        calls = _calls(cur, ctx, w, ruling_span) if w.result is not None else {}
        if w.outcome == "ready":
            _store_version(cur, ctx, w, ruling_span, calls)


def rule_ids(cur: psycopg.Cursor, verify_cv: str) -> dict[str, str]:
    """{check code: rule id} of the verify version: the rules bound to it, V3_<CODE>."""
    cur.execute(
        """SELECT r.rule_code, r.rule_id::text FROM ops.component_version_rule b JOIN ops.rule r USING (rule_id)
           WHERE b.component_version_id = %s AND b.enabled ORDER BY b.ordinal""",
        (verify_cv,),
    )
    by_code = dict(cur.fetchall())
    return {c: by_code[rule_code(c)] for c in CHECK_CODES if rule_code(c) in by_code}
