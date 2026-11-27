# SPDX-License-Identifier: Apache-2.0
# Native tool-call extraction (_native_calls, with its "_invalid_json" marker) and the thread-pool runner
# are adapted from ArchAI's tool_bench (kirtanp/hackpertus-archives, src/archai/tool_bench.py,
# _calls_native and main), Copyright (c) 2026 The ArchAI contributors, MIT License. See NOTICE.
"""Run the tool benchmark: native tool calling vs the JSON protocol, per model and language.

Configurations (one request per case and repetition; the JSON form calls get the pipeline's single
repair turn, the loop and native calls get none, so comparisons use ``exact_first``):

* ``json_strict``: the JSON protocol with ``response_format: json_schema`` strict (Tier.STRICT).
* ``json_object``: the JSON protocol with ``json_object`` and a placeholder example (Tier.OBJECT).
* ``native_auto``: the gateway's OpenAI ``tools`` with ``tool_choice: "auto"`` (and
  ``parallel_tool_calls: true`` for the call categories). A plain-text answer to an evidence case is
  scored ``exact = False`` but recorded in ``text_exact`` (was the id in the text right?).
* ``native_forced``: ``tool_choice`` naming the tool; evidence category only (one form tool).

Every gateway call goes through the chat function returned by ``--chat module:factory``
(``factory(model) -> ChatFn``), by default ``llm.client:chat_fn``, the project client (G2). Nothing
here reads a key. Every live run gets its own ``run_id`` (the ``--out`` folder name and the start
time), and repetition ``r`` of that run sends ``cache_salt="<run_id>/rep<r>"``: the client's replay
cache can serve neither one repetition from another nor one run from an earlier one (G10). A reply
the client nevertheless marks ``REPLAY`` during a live run is counted (``cache_hits``) and the run
exits 3: its numbers are not a measurement.

The CLI never spends calls by default (``AGENTS.md`` §6): a live run needs ``--limit N`` (at most N
cases) or ``--all``, and ``--dry-run`` prints the cases and jobs without calling anything.

Examples::

    python -m eval.tool_bench.run --rulings data/public/bench_rulings.jsonl --profile quick \
        --models apertus-v1-5-70b apertus-v1-5-8b --dry-run --out results/tool_bench/quick_2026-11-28
    python -m eval.tool_bench.run --rulings data/public/bench_rulings.jsonl --profile full --reps 2 --all \
        --models apertus-v1-5-70b apertus-v1-5-8b --out results/tool_bench/full_2026-11-28
    python -m eval.tool_bench.run --rulings data/public/bench_rulings.jsonl --profile full \
        --models apertus-v1-5-70b apertus-v1-5-8b --replay results/tool_bench/full_2026-11-28/replies.jsonl \
        --out results/tool_bench/full_2026-11-28_rescored   # re-score stored replies with today's code
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import llm.tool_protocol as tp
from llm.tool_protocol import (
    ChatFn,
    ChatReply,
    ChatRequest,
    RequestRejected,
    Tier,
    TransportFailure,
    consideration_table,
    delimit,
    new_nonce,
    parse_object,
    propose,
    run_tools,
    validate,
)

from . import score as sc
from .cases import build_cases, load_rulings
from .tools import ACTS, CALL_TOOLS, LOCATE_PASSAGE, id_tables_for, native_tool_specs

#: tool_bench-1 was the 27 Nov smoke; tool_bench-2 names the tool in SYSTEM_LOCATE (review F2).
PROMPT_VERSION = "tool_bench-2"
CONFIGS = ("json_strict", "json_object", "native_auto", "native_forced")
SYSTEM_CALLS = ("You help a lawyer work with Swiss Federal Supreme Court rulings. Use the tools when they help. "
                "Call several tools at once when the request needs several. If no tool fits the request, make no call.")
SYSTEM_LOCATE = ("You locate passages in Swiss Federal Supreme Court rulings. Answer with the locate_passage tool: "
                 "the id of the consideration that contains the passage, or none if no consideration contains it.")
MAX_TOKENS = 300


def request_sha256(req: ChatRequest) -> str:
    """Fingerprint of everything the request sends (and its cache salt): replay checks it."""
    body = {"messages": list(req.messages), "response_format": req.response_format, "max_tokens": req.max_tokens,
            "temperature": req.temperature, "tools": list(req.tools or ()), "tool_choice": req.tool_choice,
            "parallel_tool_calls": req.parallel_tool_calls, "cache_salt": req.cache_salt}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


class Recorder:
    """Wraps a chat function and keeps every reply with its request fingerprint."""

    def __init__(self, chat: ChatFn):
        self.chat = chat
        self.replies: list[ChatReply] = []
        self.requests: list[str] = []

    def __call__(self, req: ChatRequest) -> ChatReply:
        """Forward the request and keep the reply."""
        reply = self.chat(req)
        self.requests.append(request_sha256(req))
        self.replies.append(reply)
        return reply


class ReplayChat:
    """Returns stored replies in order. Used by ``--replay`` to re-score a run with new code, offline.

    Each stored reply carries the fingerprint of the request that produced it. When today's code
    sends a different request (a prompt or schema change), the reply is still returned, so the
    parser and validator can be re-scored, but ``changed`` counts it and the row says so: such a
    replay re-scores parsing, it does not measure the new prompt.
    """

    def __init__(self, replies: Sequence[Mapping[str, Any]]):
        self.replies = [(ChatReply(r.get("content"), r.get("finish_reason"), r.get("served_model"),
                                   tuple(r.get("tool_calls") or ()), "REPLAY"), r.get("request_sha256"))
                        for r in replies]
        self.changed = 0

    def __call__(self, req: ChatRequest) -> ChatReply:
        """Return the next stored reply; count it when the request differs from the recorded one."""
        if not self.replies:
            raise TransportFailure("replay store exhausted (the code now makes more calls than the recorded run)")
        reply, sha = self.replies.pop(0)
        if sha != request_sha256(req):
            self.changed += 1
        return reply


def applies(config: str, case: Mapping[str, Any]) -> bool:
    """``native_forced`` names one tool, so it only fits the single-tool evidence category."""
    return config != "native_forced" or case["category"] == "evidence"


def _user(case: Mapping[str, Any]) -> str:
    if not case.get("data"):
        return case["q"]
    kind = "ruling" if case["category"] == "evidence" else "ruling_index"
    return delimit(kind, case["data"], new_nonce(case["data"])) + "\n\n" + case["q"]


def _native_calls(reply: ChatReply) -> list[list[Any]]:
    """``[[name, args], ...]`` from a native reply; unparsable arguments become ``{"_invalid_json": True}``."""
    out = []
    for c in reply.tool_calls or ():
        fn = (c or {}).get("function") or {}
        raw = fn.get("arguments")
        try:
            args = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except json.JSONDecodeError:
            args = {"_invalid_json": True}
        out.append([fn.get("name"), args if isinstance(args, dict) else {"_not_an_object": True}])
    return out


def _offered(case: Mapping[str, Any]) -> dict[str, dict[str, set[str]]]:
    """The canonical ids each tool field may take, from the case data alone (not from an IdTable)."""
    cons = {c["id"] for c in case.get("considerations") or [{"id": "c1"}]}
    return {LOCATE_PASSAGE.name: {"a_consideration": cons | {"none"}}, "get_consideration": {"a_id": cons},
            "find_article": {"a_act": set(ACTS)}}


def _id_stats(raw_calls: Sequence[Sequence[Any]], valid_calls: Sequence[Sequence[Any]],
              tables: Mapping[str, Mapping[str, Any]], offered: Mapping[str, Mapping[str, set[str]]]
              ) -> dict[str, int]:
    emitted = invented = noncanonical = accepted_invalid = 0
    for name, args in raw_calls:
        for field, table in tables.get(name, {}).items():
            if isinstance(args, Mapping) and field in args:
                emitted += 1
                res = table.resolve(args[field])
                if res.canonical is None:
                    invented += 1
                elif res.canonical != args[field]:
                    noncanonical += 1
    for name, args in valid_calls:  # an independent check of the validator: T3
        for field, allowed in offered.get(name, {}).items():
            if isinstance(args, Mapping) and field in args and args[field] not in allowed:
                accepted_invalid += 1
    return {"ids_emitted": emitted, "invented_ids": invented, "noncanonical_ids": noncanonical,
            "accepted_invalid_ids": accepted_invalid}


def _text_answer(reply: ChatReply | None, table: Any) -> str | None:
    """The id a plain-text answer names, if the whole answer is one offered id (``c4``, ``E. 4.2``, ``none``)."""
    text = re.sub(r"[\s.:;!*`\"']+$", "", ((reply.content if reply else None) or "").strip())
    text = re.sub(r"^[\s*`\"']+", "", text)
    if not text or len(text) > 40:
        return None
    return table.resolve(text).canonical


def _leak(reply: ChatReply | None) -> bool:
    text = (reply.content or "") if reply else ""
    return "<|tools_prefix|>" in text or ('"name"' in text and '"arguments"' in text)


def cache_salt(run_id: str, rep: int) -> str:
    """The salt of the client's replay key for one repetition of one run (never sent to the gateway).

    Every live run has a ``run_id``, so no run and no repetition can be served from another (G10).
    An empty ``run_id`` is the form of runs made before version 0.2.1 (repetition 0 unsalted); it is
    kept only so that their stored replies still replay with matching fingerprints.
    """
    if not run_id:
        return f"rep{rep}" if rep else ""
    return f"{run_id}/rep{rep}"


def run_case(chat: ChatFn, case: Mapping[str, Any], config: str, rep: int = 0, run_id: str = ""
             ) -> tuple[dict[str, Any], list[ChatReply], list[str]]:
    """Run one case under one configuration and repetition.

    Returns the scored row (no prompt text), the replies and their request fingerprints.
    """
    rec = Recorder(chat)
    salt = cache_salt(run_id, rep)
    t0 = time.perf_counter()
    row: dict[str, Any] = {"request_error": None, "repaired": False, "attempts": 0, "tier": None,
                           "text_exact": None}
    if case["category"] == "evidence":
        table = consideration_table(case["considerations"], none_option=True)
        tables = {LOCATE_PASSAGE.name: {"a_consideration": table}}
        gold = [[LOCATE_PASSAGE.name, case["gold"]]]
        if config.startswith("json"):
            tier = Tier.STRICT if config == "json_strict" else Tier.OBJECT
            out = propose(rec, LOCATE_PASSAGE, system=SYSTEM_LOCATE, user=_user(case), purpose="tool_bench",
                          prompt_version=PROMPT_VERSION, tier=tier, id_tables={"a_consideration": table},
                          max_tokens=MAX_TOKENS, cache_salt=salt)
            usable = [r for r in rec.replies if r.finish_reason != "length"]
            first = parse_object(rec.replies[0].content).obj if rec.replies and rec.replies[0] in usable else None
            raw_calls = [[LOCATE_PASSAGE.name, first]] if isinstance(first, dict) else []
            valid_calls = [[LOCATE_PASSAGE.name, out.value]] if out.ok else []
            v1 = validate(first, LOCATE_PASSAGE.parameters, id_tables={"a_consideration": table}) if first else None
            row.update(valid=out.ok, repaired=out.status == "ok_repaired", attempts=out.attempts, tier=out.tier.value,
                       failure=out.reason,
                       exact_first=bool(v1 and not v1.fatal and [[LOCATE_PASSAGE.name, v1.obj]] == gold))
            if out.reason in ("transport", "rejected"):
                row["request_error"] = out.reason
        else:
            choice: Any = "auto" if config == "native_auto" else {"type": "function",
                                                                  "function": {"name": LOCATE_PASSAGE.name}}
            raw_calls, valid_calls, row = _native(rec, case, [LOCATE_PASSAGE], tables, choice, SYSTEM_LOCATE, row,
                                                  salt)
            row["valid"] = row["valid"] and len(valid_calls) == 1
            row["exact_first"] = None
            if not raw_calls and rec.replies:
                said = _text_answer(rec.replies[0], table)
                row["text_exact"] = said == case["gold"]["a_consideration"]
    else:
        tables = id_tables_for(case["considerations"] or [{"id": "c1", "e_number": "1"}])
        gold = case["gold"]
        if config.startswith("json"):
            tier = Tier.STRICT if config == "json_strict" else Tier.OBJECT
            out = run_tools(rec, CALL_TOOLS, system=SYSTEM_CALLS, user=_user(case), purpose="tool_bench",
                            prompt_version=PROMPT_VERSION, tier=tier, id_tables=tables, max_steps=1,
                            feedback_rounds=0, max_calls=6, max_tokens=MAX_TOKENS, cache_salt=salt)
            first_reply = rec.replies[0] if rec.replies else None
            usable = first_reply is not None and first_reply.finish_reason != "length"
            parsed = parse_object(first_reply.content) if usable else None
            raw = (parsed.obj or {}).get("a_calls") if parsed and parsed.ok else None
            raw_calls = [[c.get("a_tool"), c.get("b_args")] for c in raw or [] if isinstance(c, dict)
                         and c.get("a_tool") != "finish"]
            valid_calls = [[r.tool, dict(r.args)] for r in out.calls if r.error is None and r.origin == "model"]
            row.update(valid=out.status != "failed" and all(r.error is None for r in out.calls),
                       attempts=len(rec.replies), tier=tier.value,
                       failure=out.stop_reason if out.status == "failed" else None,
                       unknown_tools=sum(1 for r in out.calls if (r.error or "").startswith("unknown tool")),
                       exact_first=None)
            if out.stop_reason == "transport_or_rejected":
                row["request_error"] = out.stop_reason
        else:
            raw_calls, valid_calls, row = _native(rec, case, list(CALL_TOOLS), tables, "auto", SYSTEM_CALLS, row,
                                                  salt, parallel=True)
            row["exact_first"] = None
    s_raw = sc.score_calls(gold, raw_calls)
    s_val = sc.score_calls(gold, valid_calls)
    if case["category"] == "irrelevance":
        # Restraint is judged on what the model emitted: a refused call is still a call.
        s_raw["exact"] = s_val["exact"] = bool(row.get("valid")) and not raw_calls
    last = rec.replies[-1] if rec.replies else None
    row.update(exact_raw=s_raw["exact"], exact=s_val["exact"], precision=round(s_val["precision"], 3),
               recall=round(s_val["recall"], 3), raw_calls=raw_calls, calls=valid_calls, gold=gold,
               latency_s=round(time.perf_counter() - t0, 3), leaked_tool_text=_leak(last),
               served_model=last.served_model if last else None, finish_reason=last.finish_reason if last else None,
               content_sha256=[hashlib.sha256((r.content or "").encode()).hexdigest()[:16] for r in rec.replies],
               **_id_stats(raw_calls, valid_calls, tables, _offered(case)))
    if row.get("exact_first") is None:
        row["exact_first"] = row["exact"]
    return row, rec.replies, rec.requests


def _native(rec: Recorder, case: Mapping[str, Any], tools: Sequence[tp.Tool], tables: Mapping[str, Mapping[str, Any]],
            choice: Any, system: str, row: dict[str, Any], salt: str = "", *, parallel: bool | None = None
            ) -> tuple[list, list, dict]:
    req = ChatRequest(({"role": "system", "content": system}, {"role": "user", "content": _user(case)}), None,
                      MAX_TOKENS, "tool_bench", PROMPT_VERSION, tools=tuple(native_tool_specs(tools, tables)),
                      tool_choice=choice, parallel_tool_calls=parallel, cache_salt=salt)
    try:
        reply = rec(req)
    except (RequestRejected, TransportFailure) as e:
        row.update(valid=False, request_error=type(e).__name__, attempts=1, tier="native", failure="request",
                   unknown_tools=0)
        return [], [], row
    raw_calls = _native_calls(reply)
    by_name = {t.name: t for t in tools}
    valid_calls, unknown, refused = [], 0, 0
    for name, args in raw_calls:
        tool = by_name.get(name)
        if tool is None:
            unknown += 1
            continue
        v = validate(args, tool.parameters, id_tables=tables.get(name, {}))
        if v.fatal or v.obj is None:
            refused += 1
            continue
        valid_calls.append([name, v.obj])
    row.update(valid=reply.finish_reason != "length" and unknown == 0 and refused == 0, attempts=1, tier="native",
               unknown_tools=unknown, failure=None if not (unknown or refused) else "refused_calls")
    return raw_calls, valid_calls, row


def run_bench(cases: Sequence[Mapping[str, Any]], chat_factory: Callable[[str], ChatFn], *, models: Sequence[str],
              configs: Sequence[str] = CONFIGS, reps: int = 1, concurrency: int = 4,
              replay: Mapping[tuple, Sequence[Mapping[str, Any]]] | None = None,
              partial: Path | None = None, run_id: str = "") -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run every applicable (model, config, rep, case). Returns ``(rows, replies)`` in a stable order.

    A job that raises becomes a row with ``request_error = "exception:<type>"``; the run goes on.
    With ``partial``, each finished job is appended to that file at once, so an interrupted run
    keeps what it measured. ``run_id`` salts the replay key (:func:`cache_salt`); a replay must pass
    the ``run_id`` of the run it replays.
    """
    jobs = [(m, cfg, rep, c) for m in models for cfg in configs for rep in range(reps) for c in cases
            if applies(cfg, c)]
    chats = {m: chat_factory(m) for m in models} if replay is None else {}
    lock = threading.Lock()

    def one(job: tuple) -> tuple[dict[str, Any], dict[str, Any]]:
        model, cfg, rep, case = job
        key = (model, cfg, case["id"], rep)
        chat = ReplayChat(replay.get(key, [])) if replay is not None else chats[model]
        try:
            row, replies, requests = run_case(chat, case, cfg, rep, run_id)
        except Exception as e:  # noqa: BLE001 - one broken job must not lose the run
            row = {"request_error": f"exception:{type(e).__name__}", "valid": False, "exact": False,
                   "exact_raw": False, "exact_first": False, "calls": [], "raw_calls": [], "text_exact": None}
            replies, requests = [], []
        if isinstance(chat, ReplayChat):
            row["replay_request_changed"] = chat.changed
        row = {"model": model, "config": cfg, "rep": rep, "case_id": case["id"], "category": case["category"],
               "lang": case["lang"], **row}
        stored = {"key": list(key), "run_id": run_id,
                  "replies": [{"content": r.content, "finish_reason": r.finish_reason,
                               "served_model": r.served_model, "tool_calls": list(r.tool_calls),
                               "mode": r.mode, "request_sha256": q}
                              for r, q in zip(replies, requests, strict=True)]}
        if partial is not None:
            with lock, partial.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"row": row, "replies": stored}, ensure_ascii=False, default=str) + "\n")
        return row, stored

    results: dict[int, tuple[dict[str, Any], dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as ex:
        futures = {ex.submit(one, job): i for i, job in enumerate(jobs)}
        for fut in as_completed(futures):
            results[futures[fut]] = fut.result()
    out = [results[i] for i in range(len(jobs))]
    return [r for r, _ in out], [s for _, s in out]


def export_golden(rows: Sequence[Mapping[str, Any]], replies: Sequence[Mapping[str, Any]],
                  cases: Sequence[Mapping[str, Any]], path: Path) -> int:
    """Write recorded first replies of the JSON evidence configs as golden candidates (review before commit)."""
    by_case = {c["id"]: c for c in cases}
    n = 0
    with path.open("w", encoding="utf-8") as f:
        for row, rep in zip(rows, replies, strict=True):
            if row["category"] != "evidence" or not row["config"].startswith("json") or not rep["replies"]:
                continue
            raw = rep["replies"][0]["content"]
            case = by_case[row["case_id"]]
            table = consideration_table(case["considerations"], none_option=True)
            p = parse_object(raw)
            v = validate(p.obj, LOCATE_PASSAGE.parameters, id_tables={"a_consideration": table}) if p.ok else None
            expected = {"parse": p.status, "valid": bool(v and not v.fatal),
                        "value": (v.obj or {}).get("a_consideration") if v else None}
            f.write(json.dumps({"id": f"{row['model']}-{row['config']}-{row['case_id']}-r{row['rep']}",
                                "why": "recorded on the gateway; reviewed before commit", "tool": LOCATE_PASSAGE.name,
                                "considerations": case["considerations"], "raw": raw, "expected": expected},
                               ensure_ascii=False) + "\n")
            n += 1
    return n


def _factory(spec: str) -> Callable[[str], ChatFn]:
    mod, _, attr = spec.partition(":")
    return getattr(importlib.import_module(mod), attr)


def _md(rep: Mapping[str, Any], checks: Sequence[Mapping[str, Any]], comparisons: Mapping[str, Any],
        decision: Mapping[str, Any] | None = None) -> str:
    lines = ["# Tool benchmark", "",
             "| model / config | n | exact | 95 % CI | exact first | exact raw | valid | text answers (right) | "
             "invented ids | median s |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for k, v in rep.items():
        o = v["overall"]
        lines.append(f"| {k} | {o['n']} | {o['exact']} | {o['exact_ci95']} | {o['exact_first']} | {o['exact_raw']} | "
                     f"{o['valid']} | {o['answered_in_text']} ({o['text_answer_correct']}) | "
                     f"{o['invented_id_rate']} | {o['latency_median_s']} |")
    lines += ["", "## Thresholds (PROPOSED)", "", "| id | group | n | metric | value | target | pass | blocking |",
              "|---|---|---|---|---|---|---|---|"]
    for c in checks:
        lines.append(f"| {c['id']} | {c.get('group')} | {c.get('n')} | {c.get('metric')} | {c.get('value')} | "
                     f"{c.get('op')} {c.get('target')} | {c['pass']} | {c.get('blocking', True)} |")
    lines += ["", "## Native vs JSON on evidence (paired on exact_first, other minus json_strict)", "", "```",
              json.dumps(comparisons, indent=1), "```", ""]
    if decision:
        lines += ["## Decision rule (computed; portability is checked by hand)", "",
                  f"Verdict: **{decision['verdict']}**", "", "```", json.dumps(decision["per_language"], indent=1),
                  "```", ""]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Exit 1 when a blocking threshold fails, 2 on a usage error, 3 when a live run hit the cache."""
    ap = argparse.ArgumentParser(description="Tool benchmark: native vs JSON protocol")
    ap.add_argument("--rulings", required=True, help="JSONL of public ruling records")
    ap.add_argument("--models", nargs="+", required=True, help="model ids listed in MODELS.md (either id form)")
    ap.add_argument("--configs", nargs="+", default=list(CONFIGS), choices=CONFIGS)
    ap.add_argument("--profile", default="quick", choices=["quick", "full"])
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--concurrency", type=int, default=4, help="stay within the member's share (D-030)")
    ap.add_argument("--chat", default="llm.client:chat_fn", help="module:factory, factory(model) -> ChatFn")
    ap.add_argument("--replay", help="replies.jsonl of an earlier run: re-score offline, no gateway call")
    ap.add_argument("--export-golden", help="write golden candidates (JSON evidence replies) to this file")
    ap.add_argument("--out", required=True)
    size = ap.add_mutually_exclusive_group()
    size.add_argument("--limit", type=int, help="live: run at most this many cases (stable order)")
    size.add_argument("--all", action="store_true", help="live: run every case of the profile")
    ap.add_argument("--dry-run", action="store_true", help="print cases and jobs; no call, no file written")
    a = ap.parse_args(argv)
    if not (a.replay or a.dry_run or a.all or a.limit):
        ap.error("a live run needs --limit N or --all (AGENTS.md section 6); --dry-run shows its size first")

    out = Path(a.out)
    rulings_sha = hashlib.sha256(Path(a.rulings).read_bytes()).hexdigest()
    cases, warnings = build_cases(load_rulings(a.rulings), a.profile, a.seed)
    if a.limit and not a.replay:
        cases = cases[: a.limit]
    cases_sha = hashlib.sha256("".join(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n"
                                       for c in cases).encode("utf-8")).hexdigest()
    jobs = sum(1 for _m in a.models for cfg in a.configs for _r in range(a.reps) for c in cases if applies(cfg, c))
    if a.dry_run:
        print(json.dumps({"dry_run": True, "cases": len(cases), "jobs": jobs, "models": a.models,
                          "configs": a.configs, "reps": a.reps, "cases_sha256": cases_sha,
                          "note": "each job makes 1 call, 2 if the JSON forms repair or the cascade steps down"},
                         indent=1))
        return 0
    out.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    replay = None
    if a.replay:
        stored = [json.loads(x) for x in Path(a.replay).read_text(encoding="utf-8").splitlines() if x.strip()]
        replay = {tuple(r["key"]): r["replies"] for r in stored}
        run_id = stored[0].get("run_id", "") if stored else ""
    else:
        run_id = f"{out.name}@{started}"
    partial = out / "partial.jsonl"
    partial.unlink(missing_ok=True)
    rows, replies = run_bench(cases, _factory(a.chat) if not replay else (lambda m: None), models=a.models,
                              configs=a.configs, reps=a.reps, concurrency=a.concurrency, replay=replay,
                              partial=partial, run_id=run_id)
    for name, items in (("cases.jsonl", cases), ("rows.jsonl", rows), ("replies.jsonl", replies)):
        (out / name).write_text("".join(json.dumps(x, ensure_ascii=False, default=str) + "\n" for x in items),
                                encoding="utf-8")
    rep = sc.report(rows)
    checks = sc.check_thresholds(rows)
    comparisons = {other: sc.compare_configs(rows, "json_strict", other, category="evidence")
                   for other in ("json_object", "native_auto", "native_forced") if other in a.configs}
    decision = sc.decide(rows) if {"json_strict", "native_forced"} <= set(a.configs) else None
    meta = {"started_utc": started, "finished_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "protocol_version": tp.__version__, "prompt_version": PROMPT_VERSION, "profile": a.profile,
            "seed": a.seed, "reps": a.reps, "models": a.models, "configs": a.configs, "cases": len(cases),
            "calls": sum(len(r["replies"]) for r in replies), "mode": "REPLAY" if replay else "LIVE",
            "run_id": run_id, "limit": a.limit if not replay else None,
            "cache_hits": None if replay else sum(x.get("mode") == "REPLAY" for r in replies for x in r["replies"]),
            "rulings_sha256": rulings_sha, "cases_sha256": cases_sha,
            "replay_requests_changed": sum(r.get("replay_request_changed", 0) for r in rows) if replay else None,
            "job_exceptions": sum(str(r.get("request_error") or "").startswith("exception:") for r in rows),
            "warnings": warnings}
    (out / "report.json").write_text(json.dumps({"meta": meta, "report": rep, "thresholds": checks,
                                                 "native_vs_json": comparisons, "decision": decision},
                                                indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "report.md").write_text(_md(rep, checks, comparisons, decision), encoding="utf-8")
    partial.unlink(missing_ok=True)
    if a.export_golden:
        print(f"golden candidates: {export_golden(rows, replies, cases, Path(a.export_golden))}")
    print(json.dumps(meta, indent=1))
    if meta["cache_hits"]:
        print(f"{meta['cache_hits']} replies came from the client's replay cache: this live run is not a measurement",
              file=sys.stderr)
        return 3
    return 1 if any(not c["pass"] and c.get("blocking", True) for c in checks) else 0


if __name__ == "__main__":
    sys.exit(main())
