"""The API without a database: settings, filters, sentence split, the run launcher (with a declared fake runner),
request validation and the error contract. The database side is tests/test_api_db.py."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api import queries
from src.api.app import create_app
from src.api.runs import Launcher, RunAlreadyRunning, RunsDisabled, summary_of
from src.api.settings import Settings, SettingsError
from src.api.writes import split_sentences


def test_settings_defaults_keep_runs_off_and_no_threshold():
    s = Settings.from_env({})
    assert (s.actor, s.db_role, s.mode, s.runs_enabled, s.ai_relevant_min_score) == (
        "expert",
        "suva_api",
        "replay",
        False,
        None,
    )


@pytest.mark.parametrize(
    "env",
    [
        {"API_AI_RELEVANT_MIN_SCORE": "101"},
        {"API_AI_RELEVANT_MIN_SCORE": "high"},
        {"MODE": "fast"},
        {"API_ACTOR": " "},
        {"API_MAX_DB_SESSIONS": "21"},
        {"API_MAX_DB_SESSIONS": "0"},
    ],
)
def test_settings_refuse_unusable_values(env):
    with pytest.raises(SettingsError):
        Settings.from_env(env)


def test_settings_read_the_threshold_and_populations():
    s = Settings.from_env(
        {"API_AI_RELEVANT_MIN_SCORE": "80", "API_LAYER2_POPULATIONS": "2026Q2_union, 2025Q4_decision"}
    )
    assert s.ai_relevant_min_score == 80.0 and s.layer2_populations == ("2026Q2_union", "2025Q4_decision")


def test_a_facet_drops_only_its_own_filter():
    f = queries.Filters(courts=["8C"], languages=["fr"], q="50%_")
    clause, args = queries.where(f, frozenset({"court"}))
    assert "court" not in clause and "language" in clause
    assert args[0] == "%50\\%\\_%"  # LIKE wildcards in the search text are escaped
    full, full_args = queries.where(f)
    assert "court = ANY(%s)" in full and ["8C"] in full_args


def test_the_threshold_is_inlined_as_a_number_and_absent_by_default():
    assert "NULL::numeric IS NOT NULL" in queries.rows_cte(None)
    assert "80.0::numeric IS NOT NULL" in queries.rows_cte(80)


def test_sentences_split_on_full_stops_but_not_after_legal_abbreviations():
    body = (
        "Nach Art. 6 Abs. 1 UVG werden Leistungen erbracht. Das Gericht verweist auf E. 4.2 und BGE 147 V 1.\n\n"
        "Die Beschwerde wird abgewiesen."
    )
    assert split_sentences(body) == [
        (1, "Nach Art. 6 Abs. 1 UVG werden Leistungen erbracht."),
        (1, "Das Gericht verweist auf E. 4.2 und BGE 147 V 1."),
        (2, "Die Beschwerde wird abgewiesen."),
    ]


def test_summary_of_reads_the_last_json_object_a_step_prints():
    out = 'run S2: starting\n{\n  "run_id": "abc",\n  "status": "partial"\n}\n'
    assert summary_of(out) == {"run_id": "abc", "status": "partial"}
    assert summary_of("no json here") == {}


class FakeRunner:
    """Declared mock of `subprocess_runner`: records argv, answers per step, can hold a step until released."""

    def __init__(self, answers: dict[str, tuple[int, str]], hold: threading.Event | None = None):
        self.answers, self.hold, self.calls = answers, hold, []

    def __call__(self, argv: list[str], env: dict[str, str], log: Path) -> tuple[int, str]:
        self.calls.append((argv, env.get("DATABASE_URL")))
        if self.hold is not None:
            self.hold.wait(5)
        return self.answers[argv[2]]


def wait_done(launcher: Launcher) -> dict:
    for _ in range(200):
        status = launcher.status()
        if not status["running"]:
            return status
        time.sleep(0.01)
    raise AssertionError("the job did not finish")


def settings(**kw) -> Settings:
    return Settings(**({"runs_enabled": True} | kw))


def test_a_job_runs_layer1_then_layer2_with_the_pipeline_login(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://api@db/suva")
    runner = FakeRunner(
        {
            "src.layer1": (0, '{\n "run_id": "l1", "kept": 3\n}'),
            "src.layer2": (0, '{\n "run_id": "l2", "status": "partial", "replay_misses": 2\n}'),
        }
    )
    launcher = Launcher(
        settings(pipeline_database_url="postgresql://pipeline@db/suva", layer2_store="/tmp/store"), runner, tmp_path
    )
    launcher.start(None, None, False, ["2026Q2_union"])
    status = wait_done(launcher)
    job = status["last"]
    assert job["status"] == "partial" and [s["status"] for s in job["steps"]] == ["succeeded", "partial"]
    assert [s["run_id"] for s in job["steps"]] == ["l1", "l2"] and job["steps"][1]["summary"]["replay_misses"] == 2
    (l1, url1), (l2, url2) = runner.calls
    assert l1[2:] == ["src.layer1", "run", "--profile", "default"]
    assert l2[2:] == [
        "src.layer2",
        "run",
        "--mode",
        "replay",
        "--population",
        "2026Q2_union",
        "--store",
        "/tmp/store",
    ]
    assert url1 == url2 == "postgresql://pipeline@db/suva"


def test_a_failed_layer1_skips_layer2_and_fails_the_job(tmp_path):
    runner = FakeRunner({"src.layer1": (1, "boom"), "src.layer2": (0, "{}")})
    launcher = Launcher(settings(), runner, tmp_path)
    launcher.start("replay", None, False, [])
    job = wait_done(launcher)["last"]
    assert job["status"] == "failed" and [s["status"] for s in job["steps"]] == ["failed", "skipped"]
    assert len(runner.calls) == 1


def test_one_job_at_a_time(tmp_path):
    hold = threading.Event()
    launcher = Launcher(settings(), FakeRunner({"src.layer1": (0, "{}"), "src.layer2": (0, "{}")}, hold), tmp_path)
    launcher.start("replay", None, False, [])
    with pytest.raises(RunAlreadyRunning):
        launcher.start("replay", None, False, [])
    hold.set()
    assert wait_done(launcher)["last"]["status"] == "succeeded"


def test_runs_are_opt_in_and_a_live_run_needs_a_scope(tmp_path):
    with pytest.raises(RunsDisabled):
        Launcher(Settings(), FakeRunner({}), tmp_path).start("replay", None, False, [])
    launcher = Launcher(settings(), FakeRunner({}), tmp_path)
    with pytest.raises(ValueError, match="limit"):
        launcher.start("live", None, False, [])
    steps = launcher.plan("live", 5, False, [])
    assert steps[1].argv[-4:] == ["--mode", "live", "--limit", "5"]
    assert launcher.plan("live", None, True, [])[1].argv[-1] == "--all"


def client(**kw) -> TestClient:
    s = settings(**kw)
    launcher = Launcher(s, FakeRunner({"src.layer1": (0, "{}"), "src.layer2": (0, "{}")}), Path("/tmp/api-test-logs"))
    return TestClient(create_app(s, launcher))


def test_bad_parameters_answer_422_before_any_database_access(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    c = client()
    assert c.get("/api/rulings", params={"sort": "bogus"}).status_code == 422
    assert c.get("/api/rulings", params={"limit": 201}).status_code == 422
    assert c.get("/api/rulings", params={"status": "maybe"}).status_code == 422
    assert c.get("/api/rulings", params={"area": "XX"}).status_code == 422
    assert c.get("/api/rulings/not-a-uuid").status_code == 422


def test_without_a_database_the_api_says_so_with_503(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    c = client()
    r = c.get("/api/rulings")
    assert r.status_code == 503 and "DATABASE_URL" in r.json()["detail"]
    h = c.get("/api/health")
    assert h.status_code == 503 and h.json()["ok"] is False


def test_the_run_endpoint_maps_the_launcher_errors(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert client(runs_enabled=False).post("/api/runs", json={}).status_code == 403
    c = client()
    assert c.post("/api/runs", json={"mode": "live"}).status_code == 422
    r = c.post("/api/runs", json={"mode": "replay"})
    assert r.status_code == 202 and r.json()["enabled"] is True


def test_a_request_waits_for_a_free_session_then_answers_503(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    s = settings(max_db_sessions=1, db_wait_s=0.05)
    app = create_app(s, Launcher(s, FakeRunner({}), Path("/tmp/api-test-logs")))
    assert app.state.db_slots.acquire(timeout=1)  # another request holds the only session
    try:
        r = TestClient(app).get("/api/learning")
        assert r.status_code == 503 and r.headers["retry-after"] == "1" and "busy" in r.json()["detail"]
    finally:
        app.state.db_slots.release()
    r = TestClient(app).get("/api/learning")  # the session is free again: now the missing DATABASE_URL answers
    assert r.status_code == 503 and "DATABASE_URL" in r.json()["detail"]


class _FakeConnection:
    """Declared mock: stands for the database session the route opens; the write itself is mocked too."""

    def close(self) -> None:
        pass


def test_confirm_relevant_is_an_alias_of_mark_relevant(monkeypatch):
    # Mocks (declared): src.api.app.connect returns _FakeConnection; writes.decide_relevance records the action.
    seen: list[str] = []
    monkeypatch.setattr("src.api.app.connect", lambda settings, read_only: _FakeConnection())

    def fake_decide(conn, ruling_id, action, comment, token, *, threshold):
        seen.append(action)
        return {"id": ruling_id, "action_stored": action}

    monkeypatch.setattr("src.api.app.writes.decide_relevance", fake_decide)
    c = client()
    rid = "00000000-0000-0000-0000-000000000001"
    r = c.post(f"/api/rulings/{rid}/relevance", json={"action": "confirm_relevant"})
    assert r.status_code == 200 and r.json()["action_stored"] == "mark_relevant"
    assert c.post(f"/api/rulings/{rid}/relevance", json={"action": "mark_not_relevant"}).status_code == 200
    assert seen == ["mark_relevant", "mark_not_relevant"]
    assert c.post(f"/api/rulings/{rid}/relevance", json={"action": "confirm"}).status_code == 422
    assert seen == ["mark_relevant", "mark_not_relevant"]  # a refused action never reaches the write


def test_the_built_ui_is_served_at_the_root_and_the_api_keeps_priority(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    (tmp_path / "index.html").write_text("<!doctype html><title>UI build</title>", encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log(1)", encoding="utf-8")
    c = client(ui_dist=str(tmp_path))
    root = c.get("/")
    assert root.status_code == 200 and "UI build" in root.text
    assert c.get("/app.js").text == "console.log(1)"
    assert c.get("/api/rulings", params={"sort": "bogus"}).status_code == 422  # the API route, not the UI
    health = c.get("/api/health")
    assert health.status_code == 503 and health.json()["ok"] is False


def test_no_ui_is_mounted_without_an_index_html(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert client(ui_dist=str(tmp_path)).get("/").status_code == 404
    assert client(ui_dist=str(tmp_path / "missing")).get("/").status_code == 404
    assert Settings.from_env({"API_UI_DIST": str(tmp_path)}).ui_dist == str(tmp_path)
    assert Settings.from_env({}).ui_dist is None


class _FakeCursor:
    """Declared mock: a cursor that answers the stored rows of triage.assessment_reason joined to ops.rule."""

    def __init__(self, rows):
        self.rows, self.sql = rows, []

    def execute(self, sql, args=None):
        self.sql.append(sql)

    def fetchall(self):
        return self.rows


def test_scorer_signals_become_rules_and_readings():
    cur = _FakeCursor(
        [
            {
                "rule_code": "SC_AREA_UVMV",
                "definition": {"feature": "area_uvmv", "source": "code", "direction": 1},
                "outcome": "fired",
                "detail": {"value": 1.0, "contribution": 3.04, "effect": 3.57},
            },
            {
                "rule_code": "SC_SINGLE_JUDGE",
                "definition": {"feature": "single_judge"},  # no registered direction: the contribution's sign
                "outcome": "not_fired",
                "detail": {"value": 0.0, "contribution": 1.69, "effect": 0.0},
            },
            {
                "rule_code": "SC_CONSENSUS",
                "definition": {"feature": "consensus", "direction": 1},
                "outcome": "fired",
                "detail": {"value": 0.4, "contribution": 0.4, "effect": 0.4, "readings": {"r1": 0.5, "r2": None}},
            },
        ]
    )
    rules, readings = queries._scorer_signals(cur, "a-1")
    assert "effect = 'signal'" in cur.sql[0]
    assert [(r["rule"], r["source"], r["direction"], r["applies"]) for r in rules] == [
        ("SC_AREA_UVMV", "code", 1, True),
        ("SC_SINGLE_JUDGE", "code", 1, False),
        ("SC_CONSENSUS", "apertus", 1, True),
    ]
    assert rules[0]["value"] == 1.0 and rules[0]["effect"] == 3.57
    assert readings == [{"reading": "r1", "level": 0.5}, {"reading": "r2", "level": None}]
