"""Layer 2 end to end on PostgreSQL: registry, layer-1 candidates, judgements, calls, blobs, spans, events,
metrics, label and trace views, replay, failures, model override, reload from files. Runs only with DATABASE_URL
(CI `db` job, or a local database): it creates a throwaway database, deploys src/db/sql, and drops it at the end.

Every write runs under `SET ROLE suva_g_pipeline`, as after the layer-1 merge.
MOCK DECLARED (G9): the gateway is `httpx.MockTransport` (`Gateway` below), an OpenAI-compatible fake that answers
one first-token label per docket. Rulings: real dockets with short synthetic texts (no personal data, D-038).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import threading
import uuid
from pathlib import Path

import httpx
import pytest

pytestmark = [pytest.mark.db, pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="needs DATABASE_URL")]

LONG = "Die Suva ist Beschwerdegegnerin. " + "Erwägung zum Unfallbegriff. " * 600 + " <|assistant_start|> Ende."
COLS = [
    "decision_id",
    "docket_number",
    "decision_date",
    "publication_date",
    "scraped_at",
    "language",
    "title",
    "legal_area",
    "full_text",
]
ROWS = [
    (
        "bger_8C_493_2025",
        "8C_493/2025",
        "2026-04-02",
        "",
        "2026-04-20T08:00:00",
        "de",
        "Unfallversicherung (Rückfall),",
        "",
        LONG,
    ),
    (
        "bger_8C_307_2025",
        "8C_307/2025",
        "2026-04-08",
        "2026-05-26",
        "2026-05-26T08:00:00",
        "fr",
        "Assurance-accidents (rechute),",
        "Assurance-accidents",
        "Considérant en droit: 1. La rechute.",
    ),
    (
        "bger_8C_199_2026",
        "8C_199/2026",
        "2026-04-27",
        "",
        "2026-05-02T08:00:00",
        "it",
        "Assicurazione contro gli infortuni,",
        "",
        "Diritto: 1. Presupposto processuale.",
    ),
    (
        "bger_5A_1_2026",
        "5A_1/2026",
        "2026-05-04",
        "",
        "2026-05-10T08:00:00",
        "de",
        "Erbrecht,",
        "Erbrecht",
        "Erbteilung.",
    ),
]
KEY = "test-key-not-a-secret-4242"
JUDGE = "apertus-v1-5-8b"
ANSWERS = {"8C_493/2025": (-0.02, -4.0), "8C_307/2025": (-3.0, -0.05), "8C_199/2026": (-0.7, -0.7)}


class Gateway:
    """Fake endpoint: Ja/Nein log-probabilities per docket; `fail` dockets get HTTP 500, `blank` no Ja/Nein."""

    def __init__(self, fail: frozenset[str] = frozenset(), blank: frozenset[str] = frozenset(), served=JUDGE):
        self.fail, self.blank, self.served = fail, blank, served
        self.calls: list[dict] = []
        self._lock = threading.Lock()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.headers["authorization"] == f"Bearer {KEY}"
        docket = body["messages"][1]["content"].split(":", 1)[0].removeprefix("Urteil ")
        with self._lock:
            self.calls.append(body)
        if docket in self.fail:
            return httpx.Response(500, json={"error": "down"})
        ja, nein = ANSWERS[docket]
        alts = (
            [{"token": "Die", "logprob": -9.0}]
            if docket in self.blank
            else [{"token": "Ja", "logprob": ja}, {"token": "Nein", "logprob": nein}, {"token": "J", "logprob": -12.0}]
        )
        choice = {
            "message": {"content": alts[0]["token"]},
            "finish_reason": "length",
            "logprobs": {"content": [{"token": alts[0]["token"], "logprob": alts[0]["logprob"], "top_logprobs": alts}]},
        }
        return httpx.Response(
            200,
            json={"model": self.served, "choices": [choice], "usage": {"prompt_tokens": 120, "completion_tokens": 1}},
            headers={"x-keera-model": self.served},
        )


def client(store: Path, gateway: Gateway | None, *, mode="live", name="apertus-v1-5-70b", small=JUDGE):
    from src.llm.client import LLMClient
    from src.llm.config import LLMConfig

    if mode == "replay":
        cfg = LLMConfig.from_env("replay", {})
    else:
        cfg = LLMConfig(
            mode="live", name=name, name_small=small, base_url="https://endpoint.invalid/v1", api_key=KEY, concurrency=2
        )
    return LLMClient(cfg, store_dir=store, transport=httpx.MockTransport(gateway or Gateway()), sleep=lambda s: None)


def pipeline(url):
    """A session under `SET ROLE suva_g_pipeline` (INSERT, lifecycle UPDATEs only, no DELETE: 90_roles.sql)."""
    from src.db.pg import connect

    conn = connect(url, actor="test")
    conn.execute("SET ROLE suva_g_pipeline")
    conn.commit()
    return conn


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    import psycopg
    import pyarrow as pa
    import pyarrow.parquet as pq
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    from src.db import deploy
    from src.ingest.__main__ import load_registries
    from src.ingest.hf_base import load_base
    from src.ingest.models import IngestConfig
    from src.layer1.run import run_layer1

    base = os.environ["DATABASE_URL"]
    name = f"suva_test_{uuid.uuid4().hex[:10]}"
    tmp = tmp_path_factory.mktemp("layer2")
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    url = make_conninfo(**(conninfo_to_dict(base) | {"dbname": name}))
    try:
        res = deploy.run_psql(
            argparse.Namespace(compose=False, url=url), deploy.script_for(deploy.sql_files()), capture=True
        )
        assert res.returncode == 0, res.stderr
        table = pa.Table.from_pylist([dict(zip(COLS, r, strict=True)) | {"appealed_court_raw": None} for r in ROWS])
        pq.write_table(table, tmp / "bger.parquet")
        with pipeline(url) as conn:
            load_registries(conn)
            with conn.cursor() as cur:
                cur.execute("SELECT config FROM ops.component_version WHERE step = 'ingest'")
                cfg = IngestConfig.model_validate(cur.fetchone()[0])
            load_base(conn, tmp / "bger.parquet", cfg, [], actor="test")
            out = run_layer1(conn, runs_dir=tmp / "runs", actor="test")
            assert (out["kept"], out["dropped"]) == (3, 1)
        yield url, tmp
    finally:
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def run(url, tmp, c, **kw):
    from src.layer2.run import run_layer2

    with pipeline(url) as conn:
        return run_layer2(conn, runs_dir=tmp / "runs", actor="test", client=c, **kw)


def rows(url, sql, *args):

    with pipeline(url) as conn, conn.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()


def test_live_run_stores_every_judgement_with_its_lineage(db):
    url, tmp = db
    gw = Gateway()
    out = run(url, tmp, client(tmp / "store_a", gw), mode="live")
    assert (out["status"], out["judged"], out["failed"], out["skipped"]) == ("succeeded", 3, 0, 0)
    assert out["judge"] == JUDGE and out["model_override"] == 0 and out["live_calls"] == 3
    assert out["truncated"] == 1 and out["neutralised"] == 1
    assert {b["model"] for b in gw.calls} == {JUDGE} and all(b["top_logprobs"] == 20 for b in gw.calls)
    assert all(b["max_tokens"] == 1 and b["temperature"] == 0 for b in gw.calls)
    long_user = next(b for b in gw.calls if "8C_493" in b["messages"][1]["content"])["messages"][1]["content"]
    assert "<|" not in long_user and "\n[…]\n" in long_user  # neutralised (G4), cut and marked
    rid = out["run_id"]
    got = {
        d: (s, o, src, raw, s100, up)
        for d, s, o, src, raw, s100, up in rows(
            url,
            """
        SELECT r.docket, a.in_suva_scope::text, a.outcome::text, a.score_source::text, a.score_raw, a.score_0_100,
               u.step::text
        FROM triage.assessment a JOIN corpus.ruling r USING (ruling_id)
        JOIN triage.assessment u ON u.assessment_id = a.upstream_assessment_id
        WHERE a.run_id = %s""",
            rid,
        )
    }
    assert set(got) == set(ANSWERS)  # the layer-1 drop (5A) is never judged
    for docket, (ja, nein) in ANSWERS.items():
        scope, outcome, src, raw, s100, up = got[docket]
        assert (scope, outcome, src, up) == ("potentially", "ok", "judged", "layer1_filter")
        p_ja, p_nein = math.exp(ja) + math.exp(-12.0), math.exp(nein)  # 'J' counts as Ja (D-074 token set)
        assert math.isclose(raw, math.log(p_ja) - nein) and float(s100) == round(100 * p_ja / (p_ja + p_nein), 2)
    detail = rows(
        url,
        """SELECT j.truncation, j.text_chars_sent, j.text_chars_total, j.yes_no_in_top,
                                 jsonb_array_length(j.top_logprobs), j.served_model, c.llm_call_id = j.llm_call_id
                          FROM triage.llm_judgement j JOIN triage.assessment a USING (assessment_id)
                          JOIN ops.llm_call c ON c.span_id IN (SELECT span_id FROM ops.span WHERE parent_span_id =
                                                               a.span_id)
                          JOIN corpus.ruling r ON r.ruling_id = a.ruling_id
                          WHERE a.run_id = %s AND r.docket = '8C_493/2025'""",
        rid,
    )
    assert detail == [("head12000_tail2000", 14000, len(LONG), True, 3, JUDGE, True)]
    calls = rows(
        url,
        """SELECT c.cache_hit, c.mode::text, c.http_status, c.attempt, b.content IS NOT NULL,
                                encode(sha256(convert_to(b.content, 'UTF8')), 'hex') = c.messages_sha256
                         FROM ops.llm_call c JOIN ops.blob b ON b.sha256 = c.messages_sha256 WHERE c.run_id = %s""",
        rid,
    )
    assert calls == [(False, "LIVE", 200, 1, True, True)] * 3
    spans = dict(rows(url, "SELECT operation, count(*) FROM ops.span WHERE run_id = %s GROUP BY 1", rid))
    assert spans == {"layer2.run": 1, "layer2.judge": 3, "llm.call": 3}
    code = "SELECT params -> 'code_paths', length(params ->> 'code_sha256') FROM ops.pipeline_run WHERE run_id = %s"
    assert rows(url, code, rid) == [(["src/layer2/engine.py", "src/layer2/models.py", "src/layer2/run.py"], 64)]
    trace = rows(
        url,
        """SELECT r.docket, t.served_model, t.p_yes IS NOT NULL FROM triage.v_scope_trace t
                         JOIN corpus.ruling r USING (ruling_id) WHERE t.step = 'layer2_judge' ORDER BY 1""",
    )
    assert [d for d, *_ in trace] == sorted(ANSWERS) and all(s == JUDGE and p for _, s, p in trace)
    label = dict(
        rows(
            url,
            """SELECT r.docket, p.step::text FROM triage.v_scope_pipeline p
                              JOIN corpus.ruling r USING (ruling_id)""",
        )
    )
    assert label["5A_1/2026"] == "layer1_filter" and label["8C_307/2025"] == "layer2_judge"
    dumped = json.dumps(rows(url, "SELECT attributes FROM ops.log_event WHERE run_id = %s", rid))
    dumped += json.dumps(rows(url, "SELECT params, raw_output FROM ops.llm_call WHERE run_id = %s", rid))
    assert KEY not in dumped and "Beschwerdegegnerin" not in dumped  # no key, no prompt text in logs (§11.5)
    manifest = json.loads((Path(out["files"]) / "manifest.json").read_text())
    assert set(manifest["files"]) == {
        "layer2_judgements.jsonl",
        "llm_attempts.jsonl",
        "messages.jsonl",
        "replay_misses.jsonl",
    }
    assert (Path(out["files"]) / "replay_misses.jsonl").read_text() == ""  # a live run misses nothing


def test_replay_gives_the_same_scores_from_the_cache(db):
    url, tmp = db
    live = run(url, tmp, client(tmp / "store_b", Gateway()), mode="live")
    gw = Gateway()
    replay = run(url, tmp, client(tmp / "store_b", gw, mode="replay"), mode="replay")
    assert gw.calls == [] and replay["cache_hits"] == 3 and replay["mode"] == "REPLAY"
    q = (
        "SELECT r.docket, a.score_raw, a.mode::text FROM triage.assessment a JOIN corpus.ruling r USING (ruling_id) "
        "WHERE a.run_id = %s ORDER BY 1"
    )
    a, b = rows(url, q, live["run_id"]), rows(url, q, replay["run_id"])
    assert [(d, s) for d, s, _ in a] == [(d, s) for d, s, _ in b] and {m for *_, m in b} == {"REPLAY"}
    assert rows(url, "SELECT DISTINCT cache_hit, mode::text FROM ops.llm_call WHERE run_id = %s", replay["run_id"]) == [
        (True, "REPLAY")
    ]


def test_failures_stay_potentially_with_a_reason_and_every_attempt(db):
    url, tmp = db
    gw = Gateway(fail=frozenset({"8C_493/2025"}), blank=frozenset({"8C_307/2025"}))  # not the first: preflight passes
    out = run(url, tmp, client(tmp / "store_c", gw), mode="live", max_failed_share=0.7)
    assert (out["status"], out["judged"], out["failed"]) == ("partial", 1, 2)
    got = dict(
        (
            (d, (o, s, r, src))
            for d, o, s, r, src in rows(
                url,
                """
        SELECT r.docket, a.outcome::text, a.in_suva_scope::text, a.reason_code, a.score_source::text
        FROM triage.assessment a JOIN corpus.ruling r USING (ruling_id) WHERE a.run_id = %s""",
                out["run_id"],
            )
        )
    )
    assert got["8C_493/2025"] == ("failed", "potentially", "L2_FAILED_CALL", "failed")
    assert got["8C_307/2025"] == ("failed", "potentially", "L2_FAIL_NO_YESNO_TOKEN", "failed")
    attempts = rows(
        url,
        """SELECT c.http_status, c.error_reason_code, c.parsed_ok FROM ops.llm_call c
                            JOIN corpus.ruling r USING (ruling_id) WHERE c.run_id = %s AND r.docket = '8C_493/2025'""",
        out["run_id"],
    )
    assert attempts == [(500, "WORK_HTTP_ERROR", None)] * 4  # MAX_ATTEMPTS of the client, each one recorded
    blank = rows(
        url,
        """SELECT j.yes_no_in_top, j.p_yes, c.parsed_ok, c.parse_error IS NOT NULL
                         FROM triage.llm_judgement j JOIN triage.assessment a USING (assessment_id)
                         JOIN ops.llm_call c ON c.llm_call_id = j.llm_call_id JOIN corpus.ruling r ON r.ruling_id =
                         a.ruling_id WHERE a.run_id = %s AND r.docket = '8C_307/2025'""",
        out["run_id"],
    )
    assert blank == [(False, None, False, True)]  # the answer is kept as evidence, never read as "no"
    assert rows(
        url, "SELECT count(*) FROM ops.log_event WHERE run_id = %s AND event_code = 'llm.retry'", out["run_id"]
    ) == [(4,)]


def test_a_dead_gateway_stops_the_run_after_one_ruling_and_loads_nothing(db):
    from src.layer2.run import Layer2RunFailed

    url, tmp = db
    gw = Gateway(fail=frozenset(ANSWERS))
    with pytest.raises(Layer2RunFailed, match="preflight"):
        run(url, tmp, client(tmp / "store_d", gw), mode="live")
    assert len(gw.calls) == 4  # the first ruling's attempts only, not 4 x every candidate
    run_id, status = rows(
        url,
        """SELECT run_id::text, status::text FROM ops.pipeline_run WHERE kind = 'layer2'
                                  ORDER BY started_at DESC LIMIT 1""",
    )[0]
    assert status == "failed"
    assert rows(url, "SELECT count(*) FROM triage.assessment WHERE run_id = %s", run_id) == [(0,)]
    assert (tmp / "runs" / run_id / "layer2_judgements.jsonl").is_file()


def test_another_model_set_by_the_judges_is_recorded_as_an_override(db):
    url, tmp = db
    gw = Gateway(served="apertus-v1-5-70b")
    out = run(url, tmp, client(tmp / "store_e", gw, small="apertus-v1-5-70b"), mode="live")
    assert out["model_override"] == 1 and out["judge"] == "apertus-v1-5-70b"
    assert rows(
        url, "SELECT model_override, resolved_models ->> 'judge' FROM ops.pipeline_run WHERE run_id = %s", out["run_id"]
    ) == [(True, "apertus-v1-5-70b")]


def test_reloading_the_files_of_a_run_adds_nothing(db):
    from src.db.runs import Run
    from src.layer2.models import Layer2JudgementRecord
    from src.layer2.run import _load, load_version

    url, tmp = db
    out = run(url, tmp, client(tmp / "store_f", Gateway()), mode="live")
    run_dir = Path(out["files"])
    records = [Layer2JudgementRecord.model_validate_json(x) for x in (run_dir / "layer2_judgements.jsonl").open()]
    attempts = [json.loads(x) for x in (run_dir / "llm_attempts.jsonl").open()]
    blobs = {b["sha256"]: b["content"] for b in map(json.loads, (run_dir / "messages.jsonl").open())}
    count = """SELECT (SELECT count(*) FROM triage.assessment WHERE run_id = %(r)s),
                      (SELECT count(*) FROM ops.llm_call WHERE run_id = %(r)s),
                      (SELECT count(*) FROM ops.span WHERE run_id = %(r)s)"""
    with pipeline(url) as conn, conn.cursor() as cur:
        cur.execute(count, {"r": out["run_id"]})
        before = cur.fetchone()
        cur.execute(
            """SELECT span_id::text, profile_version_id::text, component_version_id::text FROM ops.span
                       JOIN ops.pipeline_run USING (run_id) WHERE run_id = %s AND parent_span_id IS NULL""",
            (out["run_id"],),
        )
        span_id, pvid, cvid = cur.fetchone()
        v = load_version(cur, cvid)
        _load(cur, Run(out["run_id"], span_id, pvid, cvid), v, "LIVE", records, attempts, blobs, {})
        cur.execute(count, {"r": out["run_id"]})
        assert cur.fetchone() == before
        conn.rollback()


def test_the_breaker_stops_a_run_whose_calls_keep_failing(db):
    from src.layer2.run import Layer2RunFailed

    url, tmp = db
    gw = Gateway(fail=frozenset({"8C_307/2025", "8C_493/2025"}))  # the first (8C_199) answers, the others fail
    with pytest.raises(Layer2RunFailed, match="breaker"):
        run(url, tmp, client(tmp / "store_g", gw), mode="live", breaker=2)
    status = rows(
        url, "SELECT status::text FROM ops.pipeline_run WHERE kind = 'layer2' ORDER BY started_at DESC LIMIT 1"
    )
    assert status == [("failed",)]


def test_certification_compares_the_run_that_covers_the_set_not_the_latest_slice(db):
    from src.layer2.validate import certification_run

    url, tmp = db
    full = run(url, tmp, client(tmp / "store_h", Gateway()), mode="live")
    slice_ = run(url, tmp, client(tmp / "store_h", Gateway()), mode="live", kind="eval", limit=1)
    keys = {(d, str(dd)) for d, dd in rows(url, "SELECT docket, decision_date FROM corpus.ruling")}
    with pipeline(url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT component_version_id::text FROM ops.span WHERE run_id = %s AND parent_span_id IS NULL",
            (slice_["run_id"],),
        )
        chosen = certification_run(cur, cur.fetchone()[0], keys)
    assert chosen == full["run_id"] != slice_["run_id"]  # the slice is newer but covers 1 ruling, the run 3


def test_replay_with_a_partial_cache_judges_what_it_has_and_counts_the_rest(db):
    from src.layer2.run import Layer2RunFailed

    url, tmp = db
    run(url, tmp, client(tmp / "store_j", Gateway()), mode="live", limit=2)  # 8C_199 and 8C_307 only
    out = run(url, tmp, client(tmp / "store_j", Gateway(), mode="replay"), mode="replay")
    assert (out["status"], out["judged"], out["failed"], out["replay_misses"]) == ("partial", 2, 0, 1)
    assert rows(url, "SELECT count(*) FROM triage.assessment WHERE run_id = %s", out["run_id"]) == [(2,)]
    missed = [json.loads(x) for x in (Path(out["files"]) / "replay_misses.jsonl").open()]
    assert [m["docket"] for m in missed] == ["8C_493/2025"]
    assert rows(
        url,
        "SELECT count(*) FROM ops.log_event WHERE run_id = %s AND event_code = 'layer2.replay.missing'",
        out["run_id"],
    ) == [(1,)]
    label = rows(
        url,
        """SELECT p.step::text, p.score_0_100 IS NOT NULL FROM triage.v_scope_pipeline p
                         JOIN corpus.ruling r USING (ruling_id) WHERE r.docket = '8C_493/2025'""",
    )
    assert label == [("layer2_judge", True)]  # the earlier judgement keeps its place: a miss writes no row
    with pytest.raises(Layer2RunFailed, match="none of the 3 candidates"):
        run(url, tmp, client(tmp / "store_empty", Gateway(), mode="replay"), mode="replay")
