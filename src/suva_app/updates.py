"""Running the live ingest from the web app: start one in the background, report how it went.

One update at a time in this process. The run itself is suva_data.ingest (add-only, ground truth first);
its record in `ingest_runs` is what the status is read from, so the status survives a restart of the app.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import date

from suva_data import db, ingest


class UpdateRunning(RuntimeError):
    """An update is already running in this process."""


def _default_run(published_from: str, published_to: str) -> None:
    from suva_data.cli import gold_dockets  # reads judgements/: the rulings the base dataset keeps outside its window

    with db.connect() as conn:
        ingest.ingest(conn, published_from, published_to, extra_dockets=gold_dockets())


class Updates:
    def __init__(self, run: Callable[[str, str], None] = _default_run) -> None:
        self._run = run
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.current: dict | None = None  # {"published_from", "published_to"} while a run is going
        self.last_error: str | None = None  # an error that kept the last run from even being recorded

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(
        self, conn, published_from: str | None = None, published_to: str | None = None, today: date | None = None
    ) -> dict:
        """Start an update for a range of publication dates, or "since the last update" when no range is given."""
        if (published_from is None) != (published_to is None):
            raise ValueError("give both dates of the range, or neither")
        if published_from is None:
            published_from, published_to = ingest.since_last_range(conn, today=today)
        if date.fromisoformat(published_to) < date.fromisoformat(published_from):
            raise ValueError(f"the range ends before it starts: {published_from} .. {published_to}")
        with self._lock:
            if self.running:
                raise UpdateRunning("an update is already running")
            self.current, self.last_error = {"published_from": published_from, "published_to": published_to}, None
            self._thread = threading.Thread(target=self._work, args=(published_from, published_to), daemon=True)
            self._thread.start()
        return self.current

    def _work(self, published_from: str, published_to: str) -> None:
        try:
            self._run(published_from, published_to)
        except Exception as e:  # recorded as a failed run by ingest when it got that far; kept here in any case
            self.last_error = f"{type(e).__name__}: {e}"
        finally:
            self.current = None

    def wait(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def status(self, conn, today: date | None = None) -> dict:
        """What the interface shows: is one running, how the last one went, what "update now" would cover."""
        last = conn.execute(
            """SELECT id, status, params ->> 'published_from', params ->> 'published_to',
                      started_at, finished_at, report
               FROM ingest_runs WHERE command = 'ingest' AND status <> 'running' ORDER BY id DESC LIMIT 1"""
        ).fetchone()
        try:
            next_range = dict(
                zip(("published_from", "published_to"), ingest.since_last_range(conn, today=today), strict=True)
            )
        except ValueError:
            next_range = None
        return {
            "running": self.running,
            "current": self.current if self.running else None,
            "last": _run_summary(last) if last else None,
            "last_error": self.last_error,
            "next_range": next_range,
            "ingested_rulings": conn.execute("SELECT count(*) FROM ingested_rulings").fetchone()[0],
        }


def _run_summary(row) -> dict:
    run_id, status, published_from, published_to, started_at, finished_at, report = row
    report = report or {}
    sources = {name: (report.get(name) or {}).get("status") for name in ("bger", "daily", "mirror")}
    return {
        "run_id": run_id,
        "status": status,  # 'ok' | 'partial' | 'failed'
        "published_from": published_from,
        "published_to": published_to,
        "started_at": started_at,
        "finished_at": finished_at,
        "new_rulings": report.get("new_rulings"),
        "known_rulings": report.get("known_rulings"),
        "not_confirmed_by_bger": report.get("not_confirmed_by_bger"),
        "new_with_two_texts": report.get("new_with_two_texts"),
        "text_mismatches": len(report.get("text_mismatches") or []),
        "sources": sources,  # each: 'complete' | 'blocked' | 'incomplete' | 'failed' | None
        "error": report.get("error"),
    }
