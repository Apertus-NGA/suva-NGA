"""Cached, threaded client for the Apertus gateway (OpenAI-compatible chat completions).

Reads LLM_BASE_URL / LLM_API_KEY from the repo's .env (never print the key).
Every response is cached in research/cache/apertus.sqlite keyed by the full request,
so reruns cost nothing and results are reproducible.

    from apertus import chat, chat_many, p_yes
    r = chat("apertus-v1-5-70b", [{"role": "user", "content": "..."}], max_tokens=200)
    r["text"], r["reasoning"], r["usage"], r["logprobs"]
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / "cache" / "apertus.sqlite"
M70, M70T, M8, M8T = "apertus-v1-5-70b", "apertus-v1-5-70b-thinking", "apertus-v1-5-8b", "apertus-v1-5-8b-thinking"
_lock = threading.Lock()
_env: dict | None = None


def _cfg() -> dict:
    global _env
    if _env is None:
        _env = {}
        for line in (ROOT.parent / ".env").read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                _env[k.strip()] = v.strip()
        _env.update({k: v for k, v in os.environ.items() if k.startswith("LLM_")})
    return _env


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(DB, timeout=60)
    con.execute("pragma journal_mode=WAL")
    con.execute("create table if not exists calls (key text primary key, model text, tag text, request text, response text, ts real)")
    return con


def chat(model: str, messages: list[dict], tag: str = "", retries: int = 6, timeout: int = 300, **params) -> dict:
    """One chat completion. params go straight into the request body (temperature defaults to 0)."""
    body = {"model": model, "messages": messages, "temperature": 0, **params}
    key = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    with _lock:
        con = _con()
        row = con.execute("select response from calls where key=?", (key,)).fetchone()
        con.close()
    if row:
        return _parse(json.loads(row[0]), cached=True)
    cfg = _cfg()
    req = urllib.request.Request(cfg["LLM_BASE_URL"].rstrip("/") + "/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + cfg["LLM_API_KEY"], "Content-Type": "application/json"})
    err = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
            with _lock:
                con = _con()
                con.execute("insert or replace into calls values (?,?,?,?,?,?)",
                            (key, model, tag, json.dumps(body, ensure_ascii=False), json.dumps(data, ensure_ascii=False), time.time()))
                con.commit(); con.close()
            return _parse(data, cached=False)
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code}: {e.read()[:300]!r}"
            if e.code in (400, 401, 403, 404, 422):
                break
        except Exception as e:  # timeouts, connection resets
            err = repr(e)[:300]
        time.sleep(min(60, 2 ** i))
    return {"text": None, "error": err, "reasoning": None, "usage": {}, "logprobs": None, "cached": False}


def _parse(data: dict, cached: bool) -> dict:
    ch = data["choices"][0]
    msg = ch["message"]
    lp = (ch.get("logprobs") or {}).get("content")
    return {"text": msg.get("content"), "reasoning": msg.get("reasoning") or msg.get("reasoning_content"),
            "usage": data.get("usage", {}), "logprobs": lp, "finish": ch.get("finish_reason"), "cached": cached, "error": None}


def chat_many(jobs: list[dict], workers: int = 8, progress: int = 50) -> list[dict]:
    """jobs: list of kwargs for chat(). Returns results in order."""
    out: list = [None] * len(jobs)
    done = [0]

    def run(i: int) -> None:
        out[i] = chat(**jobs[i])
        with _lock:
            done[0] += 1
            if progress and done[0] % progress == 0:
                print(f"  {done[0]}/{len(jobs)}", flush=True)

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(run, range(len(jobs))))
    return out


YES = {"ja", "yes", "oui", "si", "sì", "true", "1", "relevant"}
NO = {"nein", "no", "non", "false", "0", "irrelevant", "nicht"}


def p_yes(result: dict, position: int | None = None) -> float | None:
    """P(yes) from token logprobs (request with logprobs=True, top_logprobs=10).

    Looks at the first token whose top alternatives contain a yes/no word (or at `position`).
    Returns None if no such token is found.
    """
    lp = result.get("logprobs")
    if not lp:
        return None
    idx = [position] if position is not None else range(len(lp))
    for i in idx:
        py = pn = 0.0
        for alt in lp[i].get("top_logprobs", []):
            w = alt["token"].strip().lower().strip('."\':,*')
            if w in YES:
                py += math.exp(alt["logprob"])
            elif w in NO:
                pn += math.exp(alt["logprob"])
        if py + pn > 0.5:
            return py / (py + pn)
    return None


if __name__ == "__main__":
    r = chat(M70, [{"role": "user", "content": "Antworte nur mit Ja oder Nein: Ist die Suva ein Unfallversicherer?"}],
             max_tokens=3, logprobs=True, top_logprobs=10, tag="smoke")
    print(r["text"], p_yes(r), r["usage"], "cached" if r["cached"] else "fresh", r["error"])
