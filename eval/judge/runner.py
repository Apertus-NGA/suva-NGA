"""Shared plumbing of the two commands: the answer cache, the worker pool and the token count."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

from eval.judge.core import Item, Transport, Verdict, judge_one

DEFAULT_WORKERS = 6


class Cache:
    """Answers already paid for, one JSON line each. A rerun with the same prompts costs nothing."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {}
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    self._data[row["key"]] = row["answer"]

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, answer: Any) -> None:
        with self._lock:
            self._data[key] = answer
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"key": key, "answer": answer}, ensure_ascii=False) + "\n")


@dataclass(frozen=True)
class Task:
    task_id: str
    criterion: str
    item: Item
    repetition: int = 0


def live_transport() -> tuple[Transport, str, str]:
    """The real judge: settings from the environment or `.env` (src/llm/judge.py)."""
    from src.llm.judge import chat, config_from_env

    cfg = config_from_env()
    return partial(chat, cfg), cfg.model, cfg.effort


def run_tasks(
    tasks: Iterable[Task],
    transport: Transport,
    *,
    model: str,
    effort: str,
    cache: Cache | None = None,
    workers: int = DEFAULT_WORKERS,
) -> dict[str, Verdict]:
    """Every task gets a verdict. A call that raises is recorded as ERROR with its reason, never dropped."""

    def one(task: Task) -> tuple[str, Verdict]:
        verdict = judge_one(
            task.criterion, task.item, transport, repetition=task.repetition, cache=cache, model=model, effort=effort
        )
        return task.task_id, verdict

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(pool.map(one, list(tasks)))


def token_totals(verdicts: Iterable[Verdict]) -> dict[str, float]:
    """Tokens of the last attempt of each call, and the cost when the endpoint reports one (`usage.cost`)."""
    totals: dict[str, float] = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0, "cost_usd": 0.0}
    for verdict in verdicts:
        totals["calls"] += verdict.attempts if verdict.usage else 0
        for key in ("prompt_tokens", "completion_tokens"):
            totals[key] += int(verdict.usage.get(key) or 0)
        totals["cost_usd"] += float(verdict.usage.get("cost") or 0)
    totals["cost_usd"] = round(totals["cost_usd"], 4)
    return totals
