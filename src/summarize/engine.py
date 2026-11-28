"""The summary engine: one ruling in, the German and the French fiche out, with every Apertus call it made.

    result = summarise(source, client)                 # -> engine_types.EngineResult (no database, no file)
    result = summarise(source, client, writer="v2")    # the prompt-written fiche only

The engine is the summary owner's v3 writer, ported unchanged from branch `summarize/v3` @ a4a1504
(ENGINE_VERSION). This module replicates, step for step, that branch's per-ruling logic (pipeline.py `write`
and `_v3`), without its database:
1. the ruling text is cleaned (summarize.clean) and routed to its matter (prompts.category_of);
2. v3 reads the record once, shared by both languages (v3/record.py), then writes and verifies the German and
   the French fiche in parallel, each from the ruling (v3/write.py, v3/verify.py; finish adds the outcome
   sentence and Suva's closing note);
3. a failed record sends both languages to the prompt-written fiche (v2); a failed v3 fiche sends that language
   to v2 (summarize.write_fiche, up to two repairs, then finish.finish);
4. every fiche is reviewed by the checker (summarize.review); a v3 fiche gets its confidence by code
   (v3/confidence.py);
5. a replay miss is never a fallback: it propagates (ReplayMiss), as on the branch, also when v3 caught it as a
   sentence problem ("entailment not read: ... ReplayMiss"): a replayed version is the recorded one or none.

What differs from the branch, outside v3's logic: a v2 call that fails gives a `failed` fiche instead of stopping
the run (the branch raised SystemExit and stored nothing; the writer now decides); the ruling's publication mark
(`starred`) is unknown (RulingSource has none), so the closing note says "Fünfer-Entscheid" when the bench says so
and never "zur Publikation vorgesehen"; a kept sentence's `text` is the sentence as it reads in the body (finish's
per-sentence transforms, `_as_in_body`); any exception leaving `summarise` carries the calls already made
(`engine_calls`), so the writer stores them; a call whose answer the Model rejected is marked
(client_log.invalid_answer).

Local fixes on top of a4a1504, to report upstream: refine/evidence.py `passages` no longer raises on a reasoning
heading without a numbered consideration; `as_data` neutralises every closing tag, not only </ruling>; refine/
entail.py refuses a premise over 8,000 characters (ModelFailed, "not read") instead of cutting it silently (G4).
The code identity of a run covers the whole import closure (src/layer3/models.py ENGINE_CODE_GLOBS).

Every call reaches the gateway through the caller's src/llm/client.py client (G2), with the branch's parameters
(large model, temperature 0, JSON mode for v3, one-token readings with top_logprobs 20 for entailment, max_tokens
1,200 for v2), so the client's cache keys are the branch's. The client's observer hands every attempt and cache
hit back to this module, which turns each into one CallRecord (as layer 2 does, src/layer2/run.py).

Identifiers come from code (G1): proposition ids are an enum of the record, consideration labels are found by
code in the ruling (refine/evidence.py), the outcome sentence is code's. Ruling text is data, delimited by v3's
prompts (G4). The engine imports nothing from the database.
"""

from __future__ import annotations

import copy
import dataclasses
import re
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from src.llm.client import InputRejected, LLMError, ReplayMiss, ServedModelError
from src.summarize import finish, summarize, v3
from src.summarize.engine_types import (
    CallRecord,
    EngineResult,
    Fiche,
    FicheStatus,
    Proposition,
    RulingSource,
    Sentence,
)
from src.summarize.extract import candidates as cand
from src.summarize.extract.write import ruling_language, with_admissibility
from src.summarize.prompts import VERSION as V2_PROMPT_VERSION
from src.summarize.prompts import category_of
from src.summarize.refine.model import Model, ModelFailed, p_yes_from
from src.summarize.v3 import types as v3types
from src.summarize.v3 import verify as v3verify

ENGINE_VERSION = "v3@a4a1504"  # the summary owner's v3, ported from branch summarize/v3 at this commit
WRITERS = ("v3", "v2")
LANGUAGES = ("de", "fr")
STEP = "summarise"  # the trace step of every call (ops.pipeline_step)
V2_MAX_TOKENS = 1200  # summarize.chat on the branch
CHECK_CODES = (
    "language",
    "placeholder",
    "new_identifier",
    "modal_strength",
    "glossary_term",
    "suva_named",
    "outcome_restated",
    "speaker",
    "entailment",
    "duplicate",
)

_WRITE_TAG = re.compile(r"^v3-write@\d+/(de|fr)\b")
_REFUSED = re.compile(r"^(S\d+) refused as (?:the court's |the )(question|fact|rule|condition|answer)\b")
_ENTAILMENT_VALUE = re.compile(r"^entailment (\d+(?:\.\d+)?) below")
_ATTEMPT = re.compile(r"^attempt (\d): (.*)$", re.S)


class NotSummarisable(ValueError):
    """The ruling cannot be summarised: no usable text (the branch's pipeline.NotSummarisable)."""


# --- the gateway shim: every call through the caller's client, one CallRecord per attempt or cache hit ----------


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def purpose_of(prompt_version: str) -> str:
    """The CallRecord purpose from v3's prompt tag ("/retry" of an invalid answer keeps its purpose)."""
    if prompt_version.startswith("record@"):
        return "record"
    if prompt_version.startswith("v3-write@"):
        return "write"
    if prompt_version.startswith("entail@"):
        return "entail"
    if prompt_version.startswith("v3-verify@"):
        kind = (prompt_version.split("/") + [""])[1]
        return kind if kind in ("repair", "missing") else "verify"
    raise ValueError(f"no purpose for prompt version {prompt_version!r}")


class _Router:
    """The client's observer while the engine uses it: hands each log record to the engine call that made it
    (trace["engine_call"]) and passes every record on to the observer the client had before (never replaced)."""

    def __init__(self, previous: Callable[[dict], None] | None) -> None:
        self.previous = previous
        self._lock = threading.Lock()
        self._open: dict[str, list[dict]] = {}

    def start(self, token: str) -> None:
        with self._lock:
            self._open[token] = []

    def stop(self, token: str) -> list[dict]:
        with self._lock:
            return self._open.pop(token, [])

    def __call__(self, record: dict) -> None:
        token = (record.get("trace") or {}).get("engine_call")
        if token:
            with self._lock:
                bucket = self._open.get(token)
                if bucket is not None:
                    bucket.append(record)
        if self.previous is not None:
            self.previous(record)


_INSTALL = threading.Lock()


def _router(client: Any) -> _Router:
    with _INSTALL:
        current = getattr(client, "observer", None)
        if isinstance(current, _Router):
            return current
        router = _Router(current)
        client.observer = router
        return router


def _window(record: dict) -> tuple[str, str]:
    """(started_at, finished_at) of one attempt: the log time is its end, the latency gives its start."""
    end = datetime.fromisoformat(record["at"])
    start = end - timedelta(seconds=record.get("latency_s") or 0)
    return start.isoformat(timespec="milliseconds"), end.isoformat(timespec="milliseconds")


class Calls:
    """Every call of one ruling, through the caller's client (src/llm/client.py), recorded as CallRecords.

    `params` of a CallRecord holds the request parameters exactly as the client logged them, plus `client_log`:
    what ops.llm_call needs and the CallRecord contract has no field for (cache_key, attempt, mode, endpoint,
    http_status, finish_reason, served_model_header, messages_sha256, and `attempted`: False when the client
    refused the call before any attempt, so there is no cache key)."""

    def __init__(self, client: Any, ruling_id: str) -> None:
        self.client = client
        self.ruling_id = ruling_id
        self.router = _router(client)
        self.records: list[CallRecord] = []
        self._lock = threading.Lock()

    def chat(
        self,
        messages: list[dict],
        *,
        purpose: str,
        language: str | None,
        prompt_version: str,
        sink: list[CallRecord] | None = None,
        **kwargs,
    ):
        """One call through the client; its CallRecords are kept, and also appended to `sink` when given."""
        token = uuid.uuid4().hex
        trace = {"step": STEP, "ruling_id": self.ruling_id, "engine_call": token, "purpose": purpose}
        self.router.start(token)
        started = _now()
        result, error = None, None
        try:
            result = self.client.chat(messages, prompt_version=prompt_version, trace=trace, **kwargs)
            return result
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:500]
            raise
        finally:
            attempts = self.router.stop(token)
            rows = self._record(messages, purpose, language, prompt_version, kwargs, attempts, result, error, started)
            if sink is not None:
                sink.extend(rows)

    def mark_invalid(self, call_id: str, reason: str) -> None:
        """The answer of this call was rejected after it arrived (invalid JSON or schema, no Ja/Nein reading):
        noted in its client_log (`invalid_answer`), so ops.llm_call stores it as parsed_ok false."""
        with self._lock:
            for n, rec in enumerate(self.records):
                if rec.call_id == call_id:
                    log = {**(rec.params.get("client_log") or {}), "invalid_answer": reason[:300]}
                    self.records[n] = dataclasses.replace(rec, params={**rec.params, "client_log": log})
                    return

    def _requested(self, size: str) -> str:
        cfg = getattr(self.client, "cfg", None)
        name = (getattr(cfg, "name", None) if size == "large" else getattr(cfg, "name_small", None)) if cfg else None
        return name or ""

    def _record(
        self, messages, purpose, language, prompt_version, kwargs, attempts, result, error, started
    ) -> list[CallRecord]:
        sent = tuple(copy.deepcopy(messages))
        size = kwargs.get("size", "large")
        asked = {"temperature": 0, "max_tokens": kwargs.get("max_tokens")}
        for key in ("response_format", "logprobs", "top_logprobs"):
            if kwargs.get(key) not in (None, False):
                asked[key] = kwargs[key]
        rows: list[CallRecord] = []
        for a in attempts:
            served = a.get("served") or {}
            latency = a.get("latency_s")
            start, end = _window(a)
            log = {
                "attempted": True,
                "cache_key": a.get("cache_key"),
                "attempt": a.get("attempt"),
                "mode": a.get("mode"),
                "endpoint": a.get("endpoint"),
                "http_status": a.get("status"),
                "finish_reason": a.get("finish_reason"),
                "served_model_header": served.get("header"),
                "messages_sha256": a.get("messages_sha256"),
            }
            rows.append(
                CallRecord(
                    call_id=str(uuid.uuid4()),
                    purpose=purpose,
                    prompt_version=a.get("prompt_version") or prompt_version,
                    language=language,
                    messages=sent,
                    response_text=a.get("content"),
                    requested_model=a.get("requested") or self._requested(size),
                    served_model=served.get("served") or served.get("header"),
                    size=size,
                    params={**(a.get("params") or asked), "client_log": log},
                    usage=dict(a.get("usage") or {}),
                    latency_ms=round(latency * 1000) if latency is not None else None,
                    cache_hit=bool(a.get("cache_hit")),
                    error=a.get("error"),
                    started_at=start,
                    finished_at=end,
                )
            )
        if not rows:  # refused before any attempt, or the client's observer was replaced by its owner
            log: dict[str, Any] = {"attempted": result is not None}
            if result is not None:
                log.update(cache_key=result.cache_key, attempt=result.attempts or 1, mode=result.mode,
                           finish_reason=result.finish_reason)  # fmt: skip
            rows.append(
                CallRecord(
                    call_id=str(uuid.uuid4()),
                    purpose=purpose,
                    prompt_version=prompt_version,
                    language=language,
                    messages=sent,
                    response_text=result.content if result is not None else None,
                    requested_model=self._requested(size),
                    served_model=result.served_model if result is not None else None,
                    size=size,
                    params={**asked, "client_log": log},
                    usage=dict(result.usage) if result is not None else {},
                    latency_ms=round(result.latency_s * 1000) if result is not None and result.latency_s else None,
                    cache_hit=bool(result is not None and result.mode == "REPLAY"),
                    error=error,
                    started_at=started,
                    finished_at=_now(),
                )
            )
        with self._lock:
            self.records.extend(rows)
        return rows


@dataclass
class _Language:
    """The language of one v3 Model: learnt from its first call, the write call ("v3-write@2/de"). The record's
    model never writes, so its calls stay without a language (they serve both). `last_call`: the CallRecord that
    answered the Model's latest call (one Model is used by one thread at a time)."""

    language: str | None = None
    last_call: str | None = None

    def see(self, prompt_version: str) -> str | None:
        found = _WRITE_TAG.match(prompt_version)
        if found:
            self.language = found.group(1)
        return self.language


def _transport(calls: Calls, slot: _Language):
    """refine.model.gateway, through `calls`: the same client parameters, so the same cache keys."""

    def send(messages: list[dict], response_format: dict, prompt_version: str, max_tokens: int) -> str:
        language = slot.see(prompt_version)
        rows: list[CallRecord] = []
        try:
            return calls.chat(
                messages,
                purpose=purpose_of(prompt_version),
                language=language,
                prompt_version=prompt_version,
                max_tokens=max_tokens,
                schema_version=prompt_version,
                response_format=response_format,
                sink=rows,
            ).content
        finally:
            slot.last_call = rows[-1].call_id if rows else None

    return send


class _Answers(list):
    """Model.log of one v3 Model. Model.ask logs a rejected answer as {"prompt", "error", "attempt"} right after
    the call that gave it; that call (the slot's last) is then marked invalid, before the Model's "/retry"."""

    def __init__(self, calls: Calls, slot: _Language) -> None:
        super().__init__()
        self.calls, self.slot = calls, slot

    def append(self, entry) -> None:
        super().append(entry)
        if isinstance(entry, dict) and "attempt" in entry and entry.get("error") and self.slot.last_call:
            self.calls.mark_invalid(self.slot.last_call, f"invalid answer: {entry['error']}")


def _labeler(calls: Calls, slot: _Language):
    """refine.model.gateway_labeler, through `calls`: one-token Ja/Nein readings (max_tokens 1, top_logprobs 20)."""

    def label(messages: list[dict], prompt_version: str) -> float | None:
        rows: list[CallRecord] = []
        result = calls.chat(
            messages,
            purpose=purpose_of(prompt_version),
            language=slot.language,
            prompt_version=prompt_version,
            max_tokens=1,
            logprobs=True,
            top_logprobs=20,
            first_token_only=True,
            sink=rows,
        )
        value = p_yes_from(result.logprobs)
        if value is None and rows:
            calls.mark_invalid(rows[-1].call_id, "no Ja or Nein among the first token's alternatives")
        return value

    return label


def _v2_ask(calls: Calls, language: str):
    """summarize.chat, through `calls`: the first call writes the fiche, the next ones are the checker's repairs."""
    made = [0]

    def ask(messages: list[dict]) -> str:
        purpose = "v2_write" if made[0] == 0 else "v2_repair"
        made[0] += 1
        return calls.chat(
            messages, purpose=purpose, language=language, prompt_version=V2_PROMPT_VERSION, max_tokens=V2_MAX_TOKENS
        ).content

    return ask


# --- the branch's per-ruling logic (pipeline.py write and _v3) -----------------------------------------------------


def _replay_miss(exc: BaseException) -> None:
    """A replay miss stays one: the caller stores nothing (the model wraps every transport error)."""
    cause: BaseException | None = exc
    while cause is not None:
        if isinstance(cause, ReplayMiss):
            raise cause
        cause = cause.__cause__


def _ruling(source: RulingSource) -> dict:
    """The branch's ruling dict (pipeline.load_ruling) from a RulingSource. `area`: the rubric layer 1 read, else
    the head of the subject line, as the branch's coalesce(area, split_part(subject, ' (', 1))."""
    text = summarize.clean(source.text or "")
    if not text.strip():
        raise NotSummarisable(f"{source.docket} has no usable text")
    head = (source.title or "").split(" (", 1)[0].strip() or None
    return {
        "id": source.ruling_id,
        "docket": source.docket,
        "decision_date": source.decision_date.isoformat(),
        "division": source.docket.split("_", 1)[0],
        "area": source.matter or head,
        "starred": None,  # the publication mark is not in RulingSource
        "text": text,
        "language": source.language,
    }


def _v3(ruling: dict, category: str, shots: dict[str, list[dict]], calls: Calls) -> tuple:
    """(record or None, {language: v3 Fiche}, {"_error…": reason}): pipeline._v3 without its storage format."""
    source = {"text": ruling["text"], "language": ruling.get("language"), "category": category,
              "docket": ruling.get("docket"), "starred": ruling.get("starred")}  # fmt: skip

    def make_model(budget: int) -> Model:
        slot = _Language()
        return Model(_transport(calls, slot), budget=budget, labeler=_labeler(calls, slot), log=_Answers(calls, slot))

    try:
        result = v3.fiches(source, shots, make_model)
    except ModelFailed as exc:
        _replay_miss(exc)
        return None, {}, {"_error": f"record failed: {exc}"}
    record, out, errors = result["record"], {}, {}
    for language, fiche in result["languages"].items():
        if isinstance(fiche, ModelFailed):
            _replay_miss(fiche)
            errors[f"_error_{language}"] = str(fiche)
            continue
        if fiche.status == "failed" or not fiche.text.strip():
            errors[f"_error_{language}"] = "no usable fiche: " + "; ".join(fiche.notes)[:300]
            continue
        out[language] = fiche
    return record, out, errors


# --- from v3's trace to the contract ----------------------------------------------------------------------------


def _classify(problem: str) -> str:
    """The shared check code of one problem v3 wrote (verify.code_problems, entail.gate, without_repeats).
    A sentence with no proposition of the record behind it, an unknown id or no text has no premise in the ruling:
    it counts as an entailment failure."""
    text = problem.strip()
    if text.startswith("written in "):
        return "language"
    if text.startswith(("anonymisation placeholder", "a placeholder in brackets")):
        return "placeholder"
    if re.match(r"^(?:article|consideration|number) .+ not in the ruling$", text):
        return "new_identifier"
    if text.startswith(("stronger than the ruling", "weaker than the ruling")):
        return "modal_strength"
    if text.startswith("glossary term missing"):
        return "glossary_term"
    if text.startswith("names Suva"):
        return "suva_named"
    if text.startswith("states the outcome of the appeal"):
        return "outcome_restated"
    if text.startswith("speaker:"):
        return "speaker"
    if text.startswith("repeats an earlier sentence"):
        return "duplicate"
    if text.startswith(("entailment", "no ruling text to check")) or text in ("empty",):
        return "entailment"
    if text.startswith("no proposition of the record") or re.match(r"^proposition \S+ is not in the record$", text):
        return "entailment"
    raise ValueError(f"unclassified v3 problem: {text[:80]!r}")


def _split(problems: list[str]) -> tuple[list[str], list[str], list[str]]:
    """(attempt 1 problems, attempt 2 problems, problems added after the sentence passed: repeat, length)."""
    first, second, later = [], [], []
    for p in problems:
        found = _ATTEMPT.match(p)
        if not found:
            later.append(p)
        elif found.group(1) == "1":
            first.append(found.group(2))
        else:
            second.append(found.group(2))
    return first, second, later


def sentence_checks(s: v3types.Sentence, record: v3types.Record, language: str, ruling: dict) -> dict[str, str]:
    """Check code -> pass | fail | not_applicable for the text v3 kept for this sentence.

    v3 stores problems as text; this reads them back. A sentence written or repaired passed every check it was
    given (its final text); a sentence removed at its check keeps its first text (verify.settle), so its first
    attempt's problems describe it; one removed later (a repeat, the length) had passed. Which checks apply is
    decided as verify.code_problems decides it: the modal check only for one proposition, the glossary only when
    terms are required, the outcome check only without an answer proposition, the entailment reading only when
    every code check passed, the duplicate check only for a sentence kept at its check."""
    first, _second, later = _split(list(s.problems))
    removed_at_check = s.status == "removed" and not later
    final = first if removed_at_check else []
    failed = {_classify(p) for p in final} | {_classify(p) for p in later if p.startswith("repeats")}
    known = v3verify._known(tuple(s.propositions), record)
    if not known or any(p in ("empty",) or p.startswith("no proposition of the record") for p in final):
        return {code: ("fail" if code == "entailment" else "not_applicable") for code in CHECK_CODES}
    source_language = ruling.get("language") or ruling_language(ruling["text"]) or language
    case = v3verify._Case(record, language, ruling, None, source_language)  # no model: only code reads it
    applies = {
        "modal_strength": len(known) == 1,
        "glossary_term": bool(v3verify._terms(known, case)),
        "outcome_restated": not any(p.slot == "answer" for p in known),
        "entailment": not (failed - {"entailment", "duplicate"}),
        "duplicate": not removed_at_check,
    }
    return {
        code: "fail" if code in failed else ("pass" if applies.get(code, True) else "not_applicable")
        for code in CHECK_CODES
    }


def _entailment(s: v3types.Sentence) -> float | None:
    """The reading of the text v3 kept: for a sentence removed at its check, its first attempt's (verify.settle
    keeps the first text and the second attempt's reading); otherwise v3's own value."""
    first, second, later = _split(list(s.problems))
    if s.status == "removed" and not later and second:
        values = [float(m.group(1)) for p in first if (m := _ENTAILMENT_VALUE.match(p))]
        return values[0] if values else None
    return s.entailment


def _code_sentences(body: str, language: str, ruling: dict) -> list[tuple[str, int]]:
    """(text, paragraph) of what code added at the end of a v3 fiche: the outcome sentence (finish.outcome_once,
    with the court's "so far as admissible" when it applies) and Suva's closing note (finish.bench_note)."""
    out: list[tuple[str, int]] = []
    note = finish.bench_note(language, ruling["text"], ruling.get("starred"))
    main = finish.without_note(body)
    kind = finish.outcome_kind(ruling["text"])
    if kind:
        plain = finish._OUTCOME[kind][language]
        sentence = with_admissibility(plain, language, ruling["text"])
        if main.endswith(sentence):
            out.append((sentence, main.count("\n\n") + 1))
    if note and body.endswith(note):
        out.append((note, body.count("\n\n") + 1))
    return out


def _as_in_body(text: str, language: str, source: str) -> str:
    """A kept v3 sentence as it reads in the body: verify.verify joins the kept sentences (a full stop added where
    one is missing), then finish.finish strips markdown, puts abbreviations in the fiche's language, drops a
    reference to a consideration the ruling does not have and collapses spaces. The same transforms, per sentence.
    (finish.outcome_once may still drop a sentence that is nothing but the outcome: the writer flags a claim it
    cannot find in the body.)"""
    text = text if text.endswith((".", "!", "?")) else text + "."
    text = finish.own_language_abbreviations(finish.strip_markdown(text), language)
    text, _ = finish.real_considerations_only(text, source)
    return re.sub(r"[ \t]+", " ", text).strip()


def _sentences(fiche: v3types.Fiche, record: v3types.Record, language: str, ruling: dict) -> tuple[Sentence, ...]:
    """v3's sentences (kept and removed, in written order), then the sentences code added. Ordinals: the kept
    sentences 1..k in text order, code's after them, the removed ones last. A kept sentence's text is as it reads
    in the body (`_as_in_body`); a removed one keeps v3's text (it is in no body); v3's raw answer is the write or
    repair call's response_text."""
    by_id = {p.id: p for p in record.propositions}
    kept = [s for s in fiche.sentences if s.status != "removed"]
    code = _code_sentences(fiche.text, language, ruling)
    ordinal: dict[int, int] = {id(s): n for n, s in enumerate(kept, 1)}
    after = len(kept) + len(code)
    for s in fiche.sentences:
        if s.status == "removed":
            after += 1
            ordinal[id(s)] = after
    out = []
    for s in fiche.sentences:
        sources = [by_id[i] for i in s.propositions if i in by_id]
        out.append(
            Sentence(
                ordinal=ordinal[id(s)],
                paragraph_no=1,  # verify joins the kept sentences into one paragraph
                text=s.text if s.status == "removed" else _as_in_body(s.text, language, ruling["text"]),
                propositions=tuple(s.propositions),
                status=s.status,  # written | repaired | removed
                entailment=_entailment(s),
                label=", ".join(dict.fromkeys(p.label for p in sources)) or None,
                quote=" … ".join(p.source for p in sources) or None,
                why_not=("; ".join(s.problems) or None) if s.status == "removed" else None,
                checks=sentence_checks(s, record, language, ruling),
            )
        )
    for n, (text, paragraph) in enumerate(code, len(kept) + 1):
        out.append(Sentence(ordinal=n, paragraph_no=paragraph, text=text, propositions=(), status="code"))
    return tuple(out)


def _propositions(record: v3types.Record, text: str) -> tuple[tuple[Proposition, ...], list[str]]:
    """The record's propositions (accepted), then the sentences code refused as the court's (not accepted, with
    code's note), and the record's issues tied to neither (for the fiche's problems)."""
    issues = list(record.issues)
    used: set[int] = set()
    out = []
    for p in record.propositions:
        mine = [n for n, issue in enumerate(issues) if re.match(rf"^{re.escape(p.source_id)}\b", issue)]
        used.update(mine)
        out.append(
            Proposition(
                pid=p.id,
                slot=p.slot,  # type: ignore[arg-type]  v3 also has "question" (see the report)
                speaker=p.speaker,  # type: ignore[arg-type]
                sentence=p.source,
                label=p.label or None,
                accepted=True,
                note="; ".join(issues[n] for n in mine) or None,
            )
        )
    found = cand.candidates(text) if any(_REFUSED.match(i) for i in issues) else None
    refused = 0
    for n, issue in enumerate(issues):
        match = _REFUSED.match(issue)
        if n in used or match is None or found is None:
            continue
        candidate = next((c for c in found.kept if c.id == match.group(1)), None)
        if candidate is None:
            continue
        used.add(n)
        refused += 1
        out.append(
            Proposition(
                pid=f"R{refused}",
                slot=match.group(2),  # type: ignore[arg-type]
                speaker="court",  # code refuses only what the model gave as the court's
                sentence=candidate.text,
                label=candidate.label or None,
                accepted=False,
                note=issue,
            )
        )
    return tuple(out), [issue for n, issue in enumerate(issues) if n not in used]


def _call_id(calls: list[CallRecord], language: str, purposes: tuple[str, ...]) -> str | None:
    """The last call of this language and purpose that answered (a JSON retry or a client retry comes after)."""
    for call in reversed(calls):
        if call.language == language and call.purpose in purposes and call.error is None:
            return call.call_id
    return None


def _v3_fiche(language: str, fiche, record, ruling: dict, calls: list[CallRecord], loose: list[str]) -> Fiche:
    problems = summarize.review(language, finish.without_note(fiche.text), ruling["text"], ruling["docket"])
    conf = v3.confidence(record, fiche)
    return Fiche(
        language=language,  # type: ignore[arg-type]
        writer="v3",
        status=fiche.status,
        body=fiche.text,
        sentences=_sentences(fiche, record, language, ruling),
        confidence=float(conf["score"]),
        band=conf["level"],
        problems=tuple([*problems, *fiche.notes, *(f"record: {i}" for i in loose)]),
        write_call_id=_call_id(calls, language, ("write",)),
        repair_call_id=_call_id(calls, language, ("repair",)),
    )


def _v2_fiche(language: str, ruling: dict, shots: list[dict], category: str, calls: Calls, why: str | None) -> Fiche:
    """summarize.write_fiche then finish.finish, as the branch's `write` does for a language v3 did not write."""
    before = [f"v3: {why}"] if why else []
    try:
        raw, _ = summarize.write_fiche(language, ruling, shots, category, _v2_ask(calls, language))
    except ReplayMiss:
        raise
    except (LLMError, ServedModelError, InputRejected) as exc:
        return Fiche(
            language=language,  # type: ignore[arg-type]
            writer="v2",
            status="failed",
            body="",
            sentences=(),
            problems=tuple([*before, f"v2 call failed: {type(exc).__name__}: {exc}"[:500]]),
            write_call_id=_call_id(calls.records, language, ("v2_write",)),
            repair_call_id=_call_id(calls.records, language, ("v2_repair",)),
        )
    text, notes = finish.finish(language, raw, ruling["text"], ruling.get("starred"))
    problems = summarize.review(language, finish.without_note(text), ruling["text"], ruling["docket"])
    status: FicheStatus = "needs_review" if text.strip() else "failed"  # nothing verified it sentence by sentence
    return Fiche(
        language=language,  # type: ignore[arg-type]
        writer="v2",
        status=status,
        body=text,
        sentences=(),
        problems=tuple([*before, *problems, *notes]),
        write_call_id=_call_id(calls.records, language, ("v2_write",)),
        repair_call_id=_call_id(calls.records, language, ("v2_repair",)),
    )


def _raise_on_replay_miss(calls: Calls, docket: str) -> None:
    """A replay miss v3 caught and kept as a sentence problem (verify.examine, settle, cover wrap it in
    ModelFailed) still ends the ruling: a replayed version is the recorded one, never a different text."""
    miss = next((c for c in calls.records if (c.error or "").startswith("ReplayMiss")), None)
    if miss is not None:
        raise ReplayMiss(f"{docket}: {miss.purpose} call {miss.prompt_version}: {miss.error}")


def summarise(
    source: RulingSource,
    client: Any,
    *,
    examples: dict[str, list[dict]] | None = None,
    writer: str = "v3",
) -> EngineResult:
    """The German and the French fiche of one ruling, and every call made (see the module docstring).

    `client`: a src.llm.client.LLMClient (live or replay); its observer is wrapped, never replaced. `examples`:
    Suva's example fiches per language ({"de": [{"docket", "body"}], "fr": [...]}); default: read from
    judgements/ (src/summarize/examples.py), the target's own excluded. `writer`: "v3" (v2 where v3 fails) or
    "v2". Raises NotSummarisable for a ruling without text (no call made) and ReplayMiss for a replay miss,
    wherever v3 met it; any other failure of a call ends as a fallback or a `failed` fiche. Whatever exception
    leaves after the first call (a replay miss, a bug) carries `engine_calls`: the CallRecords already made."""
    if writer not in WRITERS:
        raise ValueError(f"writer must be one of {WRITERS}, got {writer!r}")
    ruling = _ruling(source)
    category = category_of(ruling["area"])
    if examples is None:
        from src.summarize.examples import examples_for

        examples = examples_for(source.docket)
    shots = {language: list(examples.get(language, [])) for language in LANGUAGES}
    calls = Calls(client, source.ruling_id)
    try:
        record, written, errors = (None, {}, {"_error": "writer v2: no record"})
        if writer == "v3":
            record, written, errors = _v3(ruling, category, shots, calls)
            _raise_on_replay_miss(calls, source.docket)
        propositions, loose = _propositions(record, ruling["text"]) if record is not None else ((), [])
        fiches: dict[str, Fiche] = {}
        for language in LANGUAGES:
            if language in written:
                fiches[language] = _v3_fiche(language, written[language], record, ruling, calls.records, loose)
            else:
                why = (errors.get(f"_error_{language}") or errors.get("_error")) if writer == "v3" else None
                fiches[language] = _v2_fiche(language, ruling, shots[language], category, calls, why)
        _raise_on_replay_miss(calls, source.docket)
        record_status: FicheStatus = "failed" if record is None else ("ok" if record.status == "ok" else "needs_review")
        return EngineResult(
            ruling_id=source.ruling_id,
            engine_version=ENGINE_VERSION,
            record_status=record_status,
            propositions=propositions,
            fiches=fiches,
            calls=tuple(calls.records),
        )
    except BaseException as exc:  # the calls already made are the writer's to store (ops.llm_call), then re-raised
        exc.engine_calls = tuple(calls.records)  # type: ignore[attr-defined]
        exc.engine_version = ENGINE_VERSION  # type: ignore[attr-defined]
        raise


__all__ = ["CHECK_CODES", "ENGINE_VERSION", "WRITERS", "NotSummarisable", "purpose_of", "sentence_checks", "summarise"]
