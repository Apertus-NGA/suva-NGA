"""The batch summariser (src/summarize/batch.py) and how `make run` uses it (src/cli.py).

MOCK DECLARED (G9): `FakeConn` stands in for a psycopg connection (nothing is read from it); `batch.pending` is
replaced by a fixed list and `pipeline.summarise_ruling` by a function that records its arguments and returns or
raises what the test sets. No database and no gateway call anywhere in this file.
"""

from __future__ import annotations

import pytest

from src import scout_cli as cli
from src.llm.client import ReplayMiss
from src.summarize import batch
from src.summarize import pipeline as sp

TODO = [
    (1, "8C_1/2026", True, 0.9),
    (2, "8C_2/2026", True, 0.8),
    (3, "8C_3/2026", False, 0.4),
    (4, "8C_4/2026", False, 0.1),
]


class FakeConn:
    closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def close(self):
        self.closed = True


@pytest.fixture
def fakes(monkeypatch):
    seen, written, opened = [], set(), []

    def pending(conn, writer="v3", limit=None, ruling_id=None, **scope):
        rows = [t for t in TODO if t[0] not in written and (ruling_id is None or t[0] == ruling_id)]
        return rows[:limit] if limit else rows

    def summarise_ruling(conn, ruling_id, mode="live", writer=None):
        seen.append((ruling_id, mode, writer))
        if ruling_id == 2:
            raise KeyError("boom")
        if ruling_id == 3 and mode == "replay":
            raise ReplayMiss("no cached answer")
        written.add(ruling_id)
        return {"languages": {"de": {"writer": "v3"}, "fr": {"writer": "v2" if ruling_id == 4 else "v3"}}}

    def connect():
        opened.append(FakeConn())
        return opened[-1]

    monkeypatch.setattr(batch, "pending", pending)
    monkeypatch.setattr(sp, "summarise_ruling", summarise_ruling)
    return {"seen": seen, "written": written, "connect": connect, "opened": opened}


def test_one_failure_does_not_stop_the_batch_and_every_outcome_is_counted(fakes):
    lines = []
    out = batch.run("replay", workers=2, connect=fakes["connect"], say=lines.append)
    assert sorted(fakes["seen"]) == [(1, "replay", "v3"), (2, "replay", "v3"), (3, "replay", "v3"), (4, "replay", "v3")]
    assert (out["done"], out["failed"], out["uncached"], out["fallback"]) == (
        ["8C_1/2026"], ["8C_2/2026"], ["8C_3/2026"], ["8C_4/2026"])  # fmt: skip
    assert "4 rulings pending (2 relevant by layer 2 first)" in lines[0]
    assert sum("/4 8C_" in line for line in lines) == 4 and "KeyError" in "".join(lines)
    assert "1 failed" in lines[-1] and "1 not in the replay cache" in lines[-1]


def test_a_second_run_skips_what_the_first_one_finished(fakes):
    batch.run("live", workers=1, connect=fakes["connect"], say=lambda line: None)
    first = len(fakes["seen"])
    out = batch.run("live", workers=1, connect=fakes["connect"], say=lambda line: None)
    assert out["pending"] == 1 and [s[0] for s in fakes["seen"][first:]] == [2]  # only the one that failed


def test_a_replay_miss_in_live_mode_is_a_failure(fakes):
    fakes["written"].update({1, 2, 4})
    monkey = sp.summarise_ruling

    def missing(conn, ruling_id, mode="live", writer=None):
        raise ReplayMiss("unexpected in live")

    sp.summarise_ruling = missing
    try:
        out = batch.run("live", workers=1, connect=fakes["connect"], say=lambda line: None)
    finally:
        sp.summarise_ruling = monkey
    assert out["failed"] == ["8C_3/2026"] and out["uncached"] == []


def test_the_selection_never_takes_an_expert_fiche_and_puts_relevant_rulings_first():
    query = batch._PENDING
    assert "s.origin = 'expert' OR s.confirmed_at IS NOT NULL" in query
    assert "ORDER BY coalesce(p.relevant, false) DESC, p.score DESC" in query and "p.is_current" in query


def test_make_run_asks_for_v3(monkeypatch):
    seen = []

    def summarise_ruling(conn, ruling_id, ask=None, model=None, mode="live", writer=None):
        seen.append((ruling_id, mode, writer))
        return {"languages": {"de": {}, "fr": {}}}

    monkeypatch.setattr(sp, "summarise_ruling", summarise_ruling)
    monkeypatch.setattr(cli.Stages, "summary_candidates", lambda self, conn, n: (True, [(7, "8C_1/2026")]))
    cli.Stages().summarise(None, "replay", None)
    assert seen == [(7, "replay", "v3")]


def test_some_failures_do_not_keep_the_run_from_the_ui(monkeypatch):
    def summarise_ruling(conn, ruling_id, ask=None, model=None, mode="live", writer=None):
        if ruling_id == 8:
            raise KeyError("boom")
        return {"languages": {"de": {}, "fr": {}}}

    monkeypatch.setattr(sp, "summarise_ruling", summarise_ruling)
    todo = [(7, "8C_1/2026"), (8, "8C_2/2026")]
    monkeypatch.setattr(cli.Stages, "summary_candidates", lambda self, conn, n: (True, todo))
    line = cli.Stages().summarise(None, "replay", None)
    assert "1 rulings summarised" in line and "1 failed" in line and "8C_2/2026" in line
