"""Launch the pipeline's existing steps from the API: layer 1, then layer 2, as the CLIs `make layer1` and
`make layer2` run them (python -m src.layer1 run, python -m src.layer2 run), one job at a time, in the background.

The truth about a run stays in the database (ops.pipeline_run, written by each step); the API only keeps the job
that links the steps it started, in memory, plus its log in data/runs/api/<job_id>.log. Opt-in: API_RUNS_ENABLED=1.
The steps connect with PIPELINE_DATABASE_URL (default: DATABASE_URL), the pipeline login, not the API's (F-11).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = REPO_ROOT / "data" / "runs" / "api"

StepRunner = Callable[[list[str], dict[str, str], Path], tuple[int, str]]


class RunsDisabled(RuntimeError):
    """Launching runs is not enabled on this server (API_RUNS_ENABLED)."""


class RunAlreadyRunning(RuntimeError):
    """A job is running: one at a time."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def summary_of(stdout: str) -> dict[str, Any]:
    """The JSON object a step CLI prints last (indent=2, starting with '{' at the start of a line), or {}."""
    lines = stdout.splitlines()
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].startswith("{"):
            try:
                value = json.loads("\n".join(lines[i:]))
            except json.JSONDecodeError:
                continue
            return value if isinstance(value, dict) else {}
    return {}


def subprocess_runner(argv: list[str], env: dict[str, str], log: Path) -> tuple[int, str]:
    """Run one step; its output goes to the job's log and is returned for the summary."""
    done = subprocess.run(argv, cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=False)
    with log.open("a", encoding="utf-8") as out:
        out.write(f"$ {' '.join(argv[1:])}\n{done.stdout}{done.stderr}\n[exit {done.returncode}]\n")
    return done.returncode, done.stdout


@dataclass
class Step:
    name: str
    argv: list[str]
    status: str = "pending"  # pending | running | succeeded | partial | failed | skipped
    run_id: str | None = None
    exit_code: int | None = None
    started_at: str | None = None
    finished_at: str | None = None
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class Job:
    job_id: str
    mode: str
    steps: list[Step]
    requested: dict[str, Any]
    status: str = "running"  # running | succeeded | partial | failed
    started_at: str = field(default_factory=_now)
    finished_at: str | None = None
    log: str = ""

    def public(self) -> dict[str, Any]:
        out = asdict(self)
        for step in out["steps"]:
            step.pop("argv", None)
            keep = ("status", "judged", "failed", "skipped", "replay_misses", "kept", "dropped", "rulings_in", "golden")
            step["summary"] = {k: v for k, v in step["summary"].items() if k in keep}
        return out


class Launcher:
    def __init__(self, settings: Settings, runner: StepRunner = subprocess_runner, log_dir: Path = LOG_DIR):
        self.settings = settings
        self.runner = runner
        self.log_dir = log_dir
        self._lock = threading.Lock()
        self._current: Job | None = None
        self._last: Job | None = None

    def plan(self, mode: str, limit: int | None, all_: bool, populations: list[str]) -> list[Step]:
        if mode not in {"replay", "live"}:
            raise ValueError("mode must be replay or live")
        if mode == "live" and not (limit or all_):
            raise ValueError("a live run needs `limit` or `all` (no expensive action by default)")
        python = sys.executable
        layer2 = [python, "-m", "src.layer2", "run", "--mode", mode]
        if limit:
            layer2 += ["--limit", str(limit)]
        elif all_:
            layer2.append("--all")
        for population in populations or list(self.settings.layer2_populations):
            layer2 += ["--population", population]
        if self.settings.layer2_store:
            layer2 += ["--store", self.settings.layer2_store]
        return [Step("layer1", [python, "-m", "src.layer1", "run", "--profile", "default"]), Step("layer2", layer2)]

    def start(self, mode: str | None, limit: int | None, all_: bool, populations: list[str]) -> Job:
        if not self.settings.runs_enabled:
            raise RunsDisabled("launching runs is not enabled on this server (set API_RUNS_ENABLED=1)")
        mode = mode or self.settings.mode
        steps = self.plan(mode, limit, all_, populations)
        with self._lock:
            if self._current is not None:
                raise RunAlreadyRunning(f"job {self._current.job_id} is running")
            job = Job(
                job_id=str(uuid.uuid4()),
                mode=mode,
                steps=steps,
                requested={"mode": mode, "limit": limit, "all": all_, "populations": populations},
            )
            self.log_dir.mkdir(parents=True, exist_ok=True)
            job.log = str(self.log_dir / f"{job.job_id}.log")
            self._current = job
        threading.Thread(target=self._run, args=(job,), name=f"api-job-{job.job_id[:8]}", daemon=True).start()
        return job

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        url = self.settings.pipeline_database_url or os.environ.get("DATABASE_URL")
        if url:
            env["DATABASE_URL"] = url
        return env

    def _run(self, job: Job) -> None:
        try:
            for step in job.steps:
                step.status, step.started_at = "running", _now()
                try:
                    code, stdout = self.runner(step.argv, self._env(), Path(job.log))
                except Exception as exc:  # the step could not even start: the job fails, the API keeps serving
                    code, stdout = -1, ""
                    with Path(job.log).open("a", encoding="utf-8") as out:
                        out.write(f"[could not start {step.name}: {exc}]\n")
                step.exit_code, step.finished_at = code, _now()
                step.summary = summary_of(stdout)
                step.run_id = step.summary.get("run_id")
                if code != 0:
                    step.status = "failed"
                    break
                step.status = step.summary.get("status", "succeeded")
            for step in job.steps:
                if step.status == "pending":
                    step.status = "skipped"
            statuses = {s.status for s in job.steps}
            job.status = "failed" if "failed" in statuses else "partial" if "partial" in statuses else "succeeded"
        finally:
            job.finished_at = _now()
            with self._lock:
                self._last, self._current = job, None

    def status(self) -> dict[str, Any]:
        with self._lock:
            current, last = self._current, self._last
        return {
            "enabled": self.settings.runs_enabled,
            "running": current is not None,
            "current": current.public() if current else None,
            "last": last.public() if last else None,
        }
