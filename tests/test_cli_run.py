"""`make run` (src/cli.py `run`) and the triage stage it calls (src/triage/pipeline.py).

MOCK DECLARED (G9):
- `FakeStages` stands in for `src.cli.Stages`, the real stages (database, ingest, triage, summaries, serve).
  It records the order of the calls and returns or raises what each test sets; no database, no network.
- `FakeConn` stands in for a psycopg connection in the triage tests; `fake_run` replaces
  `src.triage.pipeline.run` (the whole classifier) with a fixed result; `FakeClient` stands in for the
  shared Apertus client (only its `cfg` is read). No gateway call is made anywhere in this file.
"""

from __future__ import annotations

import argparse
import json
from types import SimpleNamespace

import pytest

from src import cli
from src.triage import pipeline as tp


class FakeStages:
    def __init__(self, rulings: int = 6055, fail: dict[str, str] | None = None) -> None:
        self.rulings = rulings
        self.fail = fail or {}
        self.calls: list[tuple] = []

    def _maybe_fail(self, name: str) -> None:
        if name in self.fail:
            raise cli.StageError(self.fail[name])

    def db_up(self) -> str:
        self.calls.append(("db_up",))
        self._maybe_fail("db_up")
        return "local compose database is up"

    def connect(self):
        self.calls.append(("connect",))
        self._maybe_fail("connect")
        return "conn", "connected; migrations up to date"

    def count_rulings(self, conn) -> int:
        self.calls.append(("count_rulings",))
        return self.rulings

    def ingest(self, conn) -> str:
        self.calls.append(("ingest",))
        self._maybe_fail("ingest")
        self.rulings = 10
        return "built from data/snapshot: 10 rulings"

    def triage(self, conn, mode, limit) -> str:
        self.calls.append(("triage", mode, limit))
        self._maybe_fail("triage")
        return "10 rulings assessed"

    def summarise(self, conn, mode, n) -> str:
        self.calls.append(("summarise", mode, n))
        self._maybe_fail("summarise")
        return f"{n} rulings summarised"

    def serve(self) -> int:
        self.calls.append(("serve",))
        return 0


def plan(**kw) -> argparse.Namespace:
    base = {"mode": "replay", "limit": None, "all": False, "dry_run": False, "no_serve": True, "summary_limit": 5}
    return argparse.Namespace(**{**base, **kw})


def names(stages: FakeStages) -> list[str]:
    return [c[0] for c in stages.calls]


def test_stages_run_in_order_and_a_loaded_database_is_not_ingested(capsys):
    stages = FakeStages(rulings=6055)
    assert cli.cmd_run(plan(no_serve=False), stages) == 0
    assert names(stages) == ["db_up", "connect", "count_rulings", "triage", "summarise", "serve"]
    out = capsys.readouterr().out
    assert "S1 ingest: skipped" in out and "6055 rulings" in out
    # every line of the run is labelled with its mode (AGENTS.md §6)
    run_lines = [line for line in out.splitlines() if line.startswith("run")]
    assert run_lines and all("[REPLAY]" in line for line in run_lines)


def test_an_empty_database_is_ingested_before_triage():
    stages = FakeStages(rulings=0)
    assert cli.cmd_run(plan(), stages) == 0
    assert names(stages) == ["db_up", "connect", "count_rulings", "ingest", "triage", "summarise"]


def test_a_stage_that_cannot_run_fails_loudly_and_stops_the_run(capsys):
    stages = FakeStages(fail={"triage": "no cached answer for 12 Apertus calls"})
    assert cli.cmd_run(plan(), stages) == 1
    assert "summarise" not in names(stages)
    captured = capsys.readouterr()
    assert "S2 triage: FAILED: no cached answer for 12 Apertus calls" in captured.err
    assert "done" not in captured.out


def test_an_unexpected_error_in_a_stage_is_reported_with_the_stage_name(capsys):
    class Broken(FakeStages):
        def summarise(self, conn, mode, n):
            raise KeyError("boom")

    assert cli.cmd_run(plan(), Broken()) == 1
    assert "S3 summarise: FAILED: KeyError" in capsys.readouterr().err


def test_live_needs_an_explicit_scope(capsys):
    stages = FakeStages()
    assert cli.cmd_run(plan(mode="live"), stages) == 2
    assert stages.calls == []
    assert "--limit N or --all" in capsys.readouterr().err


def test_live_without_a_key_fails_before_any_stage(monkeypatch, capsys):
    for key in ("LLM_NAME", "LLM_BASE_URL", "LLM_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    stages = FakeStages()
    assert cli.cmd_run(plan(mode="live", limit=3), stages) == 2
    assert stages.calls == []
    err = capsys.readouterr().err
    assert "[LIVE]" in err and "S2 triage" in err and "LLM_" in err


def test_live_limit_caps_triage_and_summaries(monkeypatch):
    monkeypatch.setattr(cli, "_check_live_config", lambda: "apertus-v1-5-70b")
    stages = FakeStages()
    assert cli.cmd_run(plan(mode="live", limit=2, summary_limit=5), stages) == 0
    assert ("triage", "live", 2) in stages.calls
    assert ("summarise", "live", 2) in stages.calls


def test_summary_limit_zero_skips_summaries(capsys):
    stages = FakeStages()
    assert cli.cmd_run(plan(summary_limit=0), stages) == 0
    assert "summarise" not in names(stages)
    assert "S3 summarise: skipped" in capsys.readouterr().out


def test_dry_run_touches_nothing(capsys):
    stages = FakeStages()
    assert cli.cmd_run(plan(dry_run=True), stages) == 0
    assert stages.calls == []
    assert "[dry-run]" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("url", "local"),
    [
        ("postgresql://suva@localhost:54329/suva", True),
        ("postgresql://suva@127.0.0.1:54329/suva_e2e", True),
        ("postgresql://suva@db:5432/suva", False),
        ("postgresql://me:pw@localhost:5432/other", False),
    ],
)
def test_the_compose_database_is_started_only_when_the_url_points_at_it(url, local):
    assert cli.is_local_compose_db(url) is local


def test_replay_summaries_fail_loudly_when_the_summariser_has_no_replay_mode(monkeypatch):
    from src.summarize import pipeline as sp

    def summarise_ruling(conn, ruling_id, ask=None, model=None):  # the signature before a `mode` exists
        raise AssertionError("must not be called: it would reach the gateway live")

    monkeypatch.setattr(sp, "summarise_ruling", summarise_ruling)
    with pytest.raises(cli.StageError, match="no replay mode"):
        cli.Stages().summarise(None, "replay", 3)


def test_summaries_pass_the_mode_when_the_summariser_accepts_it(monkeypatch):
    from src.summarize import pipeline as sp

    seen = []

    def summarise_ruling(conn, ruling_id, ask=None, model=None, mode="live"):
        seen.append((ruling_id, mode))
        return {"languages": {"de": {}, "fr": {}}}

    monkeypatch.setattr(sp, "summarise_ruling", summarise_ruling)
    monkeypatch.setattr(cli.Stages, "summary_candidates", lambda self, conn, n: (True, [(7, "8C_1/2026")]))
    message = cli.Stages().summarise(None, "replay", 1)
    assert seen == [(7, "replay")]
    assert "8C_1/2026" in message


# --- the triage stage (src/triage/pipeline.py) ---------------------------------------------------------


class FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeClient:
    def __init__(self, mode: str = "replay") -> None:
        self.cfg = SimpleNamespace(mode=mode, name=None)


def fake_result(failed_readings: int = 0, failed_gate: int = 0) -> dict:
    kept = [{"layer1": {"apertus": "failed"}} for _ in range(failed_gate)]
    summary = {"version": tp.VERSION, "rulings": 4, "kept_by_layer1": 2, "apertus_readings_failed": failed_readings}
    return {"summary": summary, "kept": kept, "model": None, "consensus": None}


@pytest.fixture
def triage_fakes(monkeypatch, tmp_path):
    import psycopg

    from src.llm import client as llm_client
    from suva_data import db

    connected = []

    def suva_connect(*a, **kw):
        connected.append("suva_data.db.connect")
        return FakeConn()

    def raw_connect(*a, **kw):
        connected.append("psycopg.connect")
        return FakeConn()

    written = []
    monkeypatch.setattr(db, "connect", suva_connect)
    monkeypatch.setattr(psycopg, "connect", raw_connect)
    monkeypatch.setattr(llm_client, "client_from_env", lambda mode, **kw: FakeClient(mode))
    monkeypatch.setattr(tp, "run", lambda conn, client, workers=5, limit=None: fake_result())
    monkeypatch.setattr(tp, "write", lambda conn, result, names: written.append(names) or 41)
    monkeypatch.setattr(tp, "RESULTS", tmp_path / "results" / "triage_pipeline.json")
    return SimpleNamespace(connected=connected, written=written, results=tp.RESULTS)


def test_a_limit_smoke_run_writes_neither_results_nor_predictions(triage_fakes):
    assert tp.main(["--limit", "2", "--write"]) == 0
    assert not triage_fakes.results.exists()
    assert triage_fakes.written == []


def test_a_full_run_writes_the_results_file_labelled_with_its_mode(triage_fakes):
    assert tp.main([]) == 0
    stored = json.loads(triage_fakes.results.read_text())
    assert stored["mode"] == "REPLAY"


def test_triage_connects_through_suva_data(triage_fakes):
    tp.main(["--limit", "1"])
    assert triage_fakes.connected == ["suva_data.db.connect"]
    assert not hasattr(tp, "DEFAULT_DSN")


def test_replay_misses_stop_triage_before_anything_is_written(monkeypatch, triage_fakes):
    monkeypatch.setattr(tp, "run", lambda conn, client, workers=5, limit=None: fake_result(3, 2))
    with pytest.raises(tp.TriageIncomplete, match="3 of the readings and 2 layer-1 matter readings"):
        tp.run_and_store(FakeConn(), FakeClient("replay"), mode="replay", write_db=True)
    assert triage_fakes.written == []
    assert not triage_fakes.results.exists()
