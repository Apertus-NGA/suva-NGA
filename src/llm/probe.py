"""Gateway probe: `make smoke-llm` (docs/EVAL.md §7, docs/agents/platform.md step 5, D-028).

Measures what the gateway really does, with our own code, and writes `results/gateway_probe.json`.
It is part of `src/llm/`, so it may call the gateway (G2). It never runs at import or at boot.

Cheap by default (about 30 short calls). Expensive items are opt-in:
  --long            one ~700-token generation per model (30 s each on the 70B)
  --sizes 8000,...  input-size ladder (synthetic filler; the 504 limit of docs/LESSONS.md K6)
  --ramp 1,2,4,8    concurrency ramp; above a member's share (5, D-030) only with --announced-slot
Prompts are synthetic: no ruling text and no Suva material (D-031, D-051). The key, the endpoint URL and
the prompts are never written to the results.

Usage: python -m src.llm.probe [--dry-run] [--models A,B] [--long] [--sizes ...] [--ramp ...]
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from src.llm.config import MEMBER_SHARE, ConfigError, LLMConfig
from src.llm.served_model import REPO_ROOT, check_served, load_allow_list

PROBE_VERSION = "1"
RESULTS = REPO_ROOT / "results" / "gateway_probe.json"
TEAM_LIMIT = 16  # AGENTS.md G2: sum of concurrent calls across the team

SYSTEM = "You are a careful assistant. Answer exactly as asked."
YES_NO = "Is Bern the capital of Switzerland? Answer with one word: Ja or Nein."
SHORT = "Name three Swiss cantons, separated by commas. No other text."
STRICT_SCHEMA = {
    "type": "object",
    "properties": {
        "zeta": {"type": "string"},
        "alpha": {"type": "string"},
        "mid": {"type": "integer"},
    },
    "required": ["zeta", "alpha", "mid"],
    "additionalProperties": False,
}
IDENTITY_PROMPTS = [
    "Complete the sentence in German: Die Unfallversicherung deckt",
    "Translate into French: Die Beschwerde wird abgewiesen.",
    "Give one synonym of 'Erwägung' in legal German.",
    "Write the number 1234 in words, in Italian.",
    "Name the Swiss federal court located in Lucerne.",
    "Complete in French: Le Tribunal fédéral rappelle que",
    "What does 'BGE' stand for? Answer in German, one line.",
    "Translate into German: le recours est partiellement admis.",
    "Name two Swiss social insurances, in German.",
    "Complete in Italian: Il ricorso è",
]
FILLER_WORDS = (
    "Versicherung Leistung Gericht Kanton Rente Taggeld Arbeit Gesundheit Verfahren Frist Antrag "
    "Entscheid Beweis Gutachten Kausalität Unfall Folge Schaden Kosten Recht"
).split()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Probe:
    def __init__(self, cfg: LLMConfig, http: httpx.Client) -> None:
        self.cfg = cfg
        self.http = http
        self.allow = load_allow_list()
        self.calls: list[dict[str, Any]] = []

    # -- one call -----------------------------------------------------------------------------------
    def chat(self, model: str, messages: list[dict], item: str, **params: Any) -> dict[str, Any]:
        """One /chat/completions call; returns a record (never the prompt, never the key)."""
        payload: dict[str, Any] = {"model": model, "messages": messages, "temperature": 0, **params}
        if "thinking" in model.lower():
            payload["chat_template_kwargs"] = {"enable_thinking": False}  # thinking off (G3, K11)
        rec: dict[str, Any] = {"item": item, "requested": model, "at": _now()}
        t0 = time.perf_counter()
        try:
            if payload.get("stream"):
                rec.update(self._stream(payload, t0))
            else:
                r = self.http.post(f"{self.cfg.base_url}/chat/completions", json=payload)
                rec["latency_s"] = round(time.perf_counter() - t0, 3)
                rec["status"] = r.status_code
                rec["header"] = r.headers.get("x-keera-model")
                if r.status_code == 200:
                    body = r.json()
                    choice = (body.get("choices") or [{}])[0]
                    rec["served"] = body.get("model")
                    rec["finish_reason"] = choice.get("finish_reason")
                    rec["content"] = (choice.get("message") or {}).get("content")
                    rec["logprobs"] = choice.get("logprobs")
                    rec["usage"] = body.get("usage")
                else:
                    rec["error"] = r.text[:300]
        except httpx.HTTPError as exc:
            rec["latency_s"] = round(time.perf_counter() - t0, 3)
            rec["status"] = None
            rec["error"] = f"{type(exc).__name__}: {exc}"[:300]
        if rec.get("served") or rec.get("header"):
            check = check_served(model, rec.get("served"), rec.get("header"), self.cfg.name, self.allow)
            rec["served_check"] = check.as_log()
        self.calls.append({k: v for k, v in rec.items() if k not in ("content", "logprobs")})
        return rec

    def _stream(self, payload: dict, t0: float) -> dict[str, Any]:
        out: dict[str, Any] = {"chunks": 0, "content": ""}
        with self.http.stream("POST", f"{self.cfg.base_url}/chat/completions", json=payload) as r:
            out["status"] = r.status_code
            out["header"] = r.headers.get("x-keera-model")
            if r.status_code != 200:
                out["error"] = r.read().decode("utf-8", "replace")[:300]
                return out
            for line in r.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                out["served"] = chunk.get("model") or out.get("served")
                if chunk.get("usage"):
                    out["usage"] = chunk["usage"]
                for choice in chunk.get("choices") or []:
                    delta = (choice.get("delta") or {}).get("content") or ""
                    if delta and "ttft_s" not in out:
                        out["ttft_s"] = round(time.perf_counter() - t0, 3)
                    out["content"] += delta
                    out["chunks"] += 1
                    if choice.get("finish_reason"):
                        out["finish_reason"] = choice["finish_reason"]
        out["latency_s"] = round(time.perf_counter() - t0, 3)
        return out

    @staticmethod
    def msgs(user: str, system: str = SYSTEM) -> list[dict]:
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    # -- items ----------------------------------------------------------------------------------------
    def models_list(self) -> dict[str, Any]:
        t0 = time.perf_counter()
        try:
            r = self.http.get(f"{self.cfg.base_url}/models")
        except httpx.HTTPError as exc:
            return {"status": None, "error": f"{type(exc).__name__}: {exc}"[:300]}
        out: dict[str, Any] = {"status": r.status_code, "latency_s": round(time.perf_counter() - t0, 3)}
        if r.status_code == 200:
            data = r.json().get("data") or []
            out["ids"] = sorted(m.get("id") for m in data if m.get("id"))
            out["fields"] = sorted({k for m in data for k in m})
        return out

    def latency(self, model: str, warm_calls: int) -> dict[str, Any]:
        first = self.chat(model, self.msgs(SHORT), "latency_first", max_tokens=30)
        warm = [self.chat(model, self.msgs(SHORT), "latency_warm", max_tokens=30) for _ in range(warm_calls)]
        lat = [c["latency_s"] for c in warm if c.get("status") == 200]
        return {
            "first_call_s": first.get("latency_s"),
            "first_status": first.get("status"),
            "warm_median_s": statistics.median(lat) if lat else None,
            "warm_max_s": max(lat) if lat else None,
            "warm_ok": len(lat),
            "warm_calls": warm_calls,
        }

    def noise(self, model: str) -> dict[str, Any]:
        runs = [self.chat(model, self.msgs(SHORT), "noise", max_tokens=40, seed=7).get("content") for _ in range(2)]
        return {"identical": runs[0] is not None and runs[0] == runs[1], "runs": 2}

    def json_modes(self, model: str) -> dict[str, Any]:
        ask = "Return a JSON object with zeta='z', alpha='a' and mid=3."
        strict = self.chat(
            model,
            self.msgs(ask),
            "json_schema_strict",
            max_tokens=60,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "probe", "schema": STRICT_SCHEMA, "strict": True},
            },
        )
        obj = self.chat(model, self.msgs(ask), "json_object", max_tokens=60, response_format={"type": "json_object"})
        return {"json_schema_strict": _json_result(strict), "json_object": _json_result(obj)}

    def logprobs(self, model: str) -> dict[str, Any]:
        rec = self.chat(model, self.msgs(YES_NO), "top_logprobs", max_tokens=1, logprobs=True, top_logprobs=20)
        out: dict[str, Any] = {"status": rec.get("status"), "error": rec.get("error")}
        content = ((rec.get("logprobs") or {}).get("content")) or []
        if content:
            top = content[0].get("top_logprobs") or []
            out["first_token"] = content[0].get("token")
            out["n_top"] = len(top)
            out["top5"] = [[t.get("token"), round(t.get("logprob", 0.0), 3)] for t in top[:5]]
        out["works"] = bool(content) and out.get("n_top", 0) > 0
        return out

    def streaming(self, model: str) -> dict[str, Any]:
        rec = self.chat(model, self.msgs(SHORT), "streaming", max_tokens=40, stream=True)
        return {k: rec.get(k) for k in ("status", "ttft_s", "latency_s", "chunks", "finish_reason", "error")}

    def two_system_messages(self, model: str) -> dict[str, Any]:
        msgs = [{"role": "system", "content": SYSTEM}, *self.msgs(SHORT, system="Be brief.")]
        rec = self.chat(model, msgs, "two_system_messages", max_tokens=10)
        return {"status": rec.get("status")}

    def identity(self, big: str, small: str, n: int) -> dict[str, Any]:
        same = 0
        for prompt in IDENTITY_PROMPTS[:n]:
            a = self.chat(big, self.msgs(prompt), "identity", max_tokens=40).get("content")
            b = self.chat(small, self.msgs(prompt), "identity", max_tokens=40).get("content")
            same += int(a is not None and a == b)
        share = same / n if n else None
        return {"pairs": n, "identical": same, "alert": share is not None and share > 0.9}

    def long_generation(self, model: str) -> dict[str, Any]:
        prompt = "Write about 600 words, in German, on the history of Swiss social insurance."
        rec = self.chat(model, self.msgs(prompt), "long_generation", max_tokens=900, stream=True)
        tokens = ((rec.get("usage") or {}).get("completion_tokens")) or None
        lat = rec.get("latency_s")
        return {
            "status": rec.get("status"),
            "latency_s": lat,
            "ttft_s": rec.get("ttft_s"),
            "completion_tokens": tokens,
            "tokens_per_s": round(tokens / lat, 1) if tokens and lat else None,
            "finish_reason": rec.get("finish_reason"),
        }

    def sizes(self, model: str, ladder: list[int]) -> list[dict[str, Any]]:
        out = []
        rng = random.Random(11)
        for target in ladder:
            # ~1.6 tokens per filler word (German compounds); a random id first defeats the prefix cache (K14)
            words = [str(rng.random())] + [rng.choice(FILLER_WORDS) for _ in range(int(target / 1.6))]
            user = " ".join(words) + "\n\nHow many times does the word 'Unfall' appear above? Answer: a number."
            rec = self.chat(model, self.msgs(user), f"size_{target}", max_tokens=8)
            usage = rec.get("usage") or {}
            out.append(
                {
                    "target_tokens": target,
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "status": rec.get("status"),
                    "latency_s": rec.get("latency_s"),
                    "error": rec.get("error"),
                }
            )
            if rec.get("status") != 200:
                break
        return out

    def ramp(self, model: str, levels: list[int]) -> list[dict[str, Any]]:
        out = []
        for level in levels:
            with ThreadPoolExecutor(max_workers=level) as pool:
                t0 = time.perf_counter()
                recs = list(
                    pool.map(
                        lambda _i, lvl=level: self.chat(model, self.msgs(YES_NO), f"ramp_{lvl}", max_tokens=1),
                        range(level * 2),
                    )
                )
                wall = round(time.perf_counter() - t0, 3)
            statuses: dict[str, int] = {}
            for r in recs:
                statuses[str(r.get("status"))] = statuses.get(str(r.get("status")), 0) + 1
            out.append({"concurrency": level, "calls": len(recs), "wall_s": wall, "statuses": statuses})
            if any(r.get("status") != 200 for r in recs):
                break
        return out


def _json_result(rec: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"status": rec.get("status"), "error": rec.get("error")}
    if rec.get("status") == 200:
        try:
            obj = json.loads(rec.get("content") or "")
            out["valid_json"] = True
            out["key_order"] = list(obj) if isinstance(obj, dict) else None
            out["matches_schema_keys"] = isinstance(obj, dict) and set(obj) == {"zeta", "alpha", "mid"}
        except json.JSONDecodeError:
            out["valid_json"] = False
    return out


def plan(args: argparse.Namespace, models: list[str]) -> list[str]:
    big = models[0]
    steps = ["GET /models"]
    for m in models:
        steps.append(f"{m}: latency, 1 cold-ish + {args.warm} warm short calls; noise, 2 identical calls")
    steps += [
        f"{big}: json_schema strict and json_object (2 calls)",
        f"{big}: top_logprobs=20, max_tokens=1 (1 call)",
        f"{big}: streaming (1 call); two system messages (1 call, expected 400)",
    ]
    if len(models) > 1:
        steps.append(f"identity {models[0]} vs {models[1]}: {args.identity} greedy prompt pairs")
    if args.long:
        steps += [f"{m}: one ~700-token streamed generation" for m in models]
    if args.sizes:
        steps.append(f"{big}: input-size ladder {args.sizes} (stops at the first error)")
    if args.ramp:
        steps.append(f"{big}: concurrency ramp {args.ramp}, 2 calls per slot (stops at the first error)")
    return steps


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.llm.probe", description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="print the plan, make no call")
    ap.add_argument("--models", help="comma-separated ids (default: LLM_NAME, then LLM_NAME_SMALL if different)")
    ap.add_argument("--warm", type=int, default=3, help="warm latency calls per model (default 3)")
    ap.add_argument("--identity", type=int, default=5, help="8B/70B identity pairs (default 5, max 10)")
    ap.add_argument("--long", action="store_true", help="one ~700-token generation per model")
    ap.add_argument("--sizes", help="input-size ladder in tokens, e.g. 8000,16000,24000")
    ap.add_argument("--ramp", help="concurrency levels, e.g. 1,2,4,8")
    ap.add_argument("--announced-slot", action="store_true", help="allow ramp levels above a member's share")
    ap.add_argument("--out", type=Path, default=RESULTS)
    args = ap.parse_args(argv)

    try:
        cfg = LLMConfig.from_env("live")
    except ConfigError as exc:
        if not args.dry_run:
            print(f"probe: {exc}", file=sys.stderr)
            return 2
        cfg = None
    models = (
        [m.strip() for m in args.models.split(",") if m.strip()]
        if args.models
        else [m for m in dict.fromkeys([cfg.name, cfg.name_small] if cfg else []) if m]
    )
    ramp = [int(x) for x in args.ramp.split(",")] if args.ramp else []
    sizes = [int(x) for x in args.sizes.split(",")] if args.sizes else []
    too_high = [lvl for lvl in ramp if lvl > (TEAM_LIMIT if args.announced_slot else MEMBER_SHARE)]
    if too_high:
        print(
            f"probe: ramp levels {too_high} exceed "
            + ("the team limit (16, G2)" if args.announced_slot else f"a member's share ({MEMBER_SHARE}, D-030)")
            + "; levels above the share need an announced slot (--announced-slot)",
            file=sys.stderr,
        )
        return 2
    args.identity = max(0, min(args.identity, len(IDENTITY_PROMPTS)))

    steps = plan(args, models or ["<LLM_NAME>"])
    if args.dry_run or cfg is None:
        print("probe plan (dry run, no call):")
        print("\n".join(f"  - {s}" for s in steps))
        return 0

    started = _now()
    with httpx.Client(
        timeout=httpx.Timeout(cfg.timeout_s, connect=15.0),
        headers={"Authorization": f"Bearer {cfg.api_key}"},
    ) as http:
        probe = Probe(cfg, http)
        items: dict[str, Any] = {"models": probe.models_list()}
        for m in models:
            items[f"latency[{m}]"] = probe.latency(m, args.warm)
            items[f"noise[{m}]"] = probe.noise(m)
        big = models[0]
        items["json_modes"] = probe.json_modes(big)
        items["top_logprobs"] = probe.logprobs(big)
        items["streaming"] = probe.streaming(big)
        items["two_system_messages"] = probe.two_system_messages(big)
        if len(models) > 1 and args.identity:
            items["identity"] = probe.identity(models[0], models[1], args.identity)
        if args.long:
            for m in models:
                items[f"long_generation[{m}]"] = probe.long_generation(m)
        if sizes:
            items["input_sizes"] = probe.sizes(big, sizes)
        if ramp:
            items["concurrency_ramp"] = probe.ramp(big, ramp)

    checks = [c["served_check"] for c in probe.calls if "served_check" in c]
    result = {
        "probe_version": PROBE_VERSION,
        "started_at": started,
        "finished_at": _now(),
        "mode": "LIVE",
        "llm_name": cfg.name,
        "llm_name_small": cfg.name_small,
        "models_probed": models,
        "allow_list": sorted(probe.allow),
        "calls": len(probe.calls),
        # the two-system-messages call is expected to fail (K11): not counted as an error
        "errors": sum(1 for c in probe.calls if c.get("status") != 200 and c["item"] != "two_system_messages"),
        "served_models_seen": sorted({c["served"] for c in checks if c.get("served")}),
        "served_rejected": sum(1 for c in checks if not c["accepted"]),
        "served_mismatch": sum(1 for c in checks if c["mismatch"]),
        "header_present": sum(1 for c in checks if c["header_present"]),
        "header_missing": sum(1 for c in checks if not c["header_present"]),
        "items": items,
        "call_log": probe.calls,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"probe: {result['calls']} calls, {result['errors']} errors, written to {args.out}")
    if result["served_rejected"]:
        print("probe: a served model is outside the allow-list (G3)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
