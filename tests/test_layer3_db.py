"""Layer 3 end to end on PostgreSQL: registry, layer 1, layer 2, then summaries with their segmentation, texts,
claims, citations, checks, LLM calls, spans, events, metrics, requests, the pair trigger, unchanged reruns, a missing
language, replay misses and a current expert edit. Runs only with DATABASE_URL: it creates a throwaway database,
deploys src/db/sql, and drops it at the end. Every write runs under `SET ROLE suva_g_pipeline`.

MOCKS DECLARED (G9):
- the layer-2 gateway is `httpx.MockTransport` (`Gateway`), an OpenAI-compatible fake answering one first-token
  label per docket, so layer 2 gives the rulings a score to rank;
- the summary engine is `FakeEngine`, a plain function standing in for src.summarize.engine.summarise: it returns a
  fixed EngineResult (propositions, a German and a French fiche, one CallRecord per call) built from the source;
  `BrokenEngine` wraps it to raise after two calls (an engine bug, its calls handed back as `engine_calls`) or to
  leave out the French fiche.
Rulings: real dockets with short synthetic texts (no personal data, D-038; no Suva text, D-031).
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import uuid
from pathlib import Path

import httpx
import pytest

pytestmark = [pytest.mark.db, pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="needs DATABASE_URL")]

TEXT = {
    "de": "Sachverhalt:\nA. Unfall.\n\nErwägungen:\n\n1. Die Suva ist Beschwerdegegnerin.\n\n2. Streitig ist der "
    "Rückfall.\n2.1 Der Rückfall setzt einen Zusammenhang voraus.\n2.2 Er fehlt.\n\nDemnach erkennt das "
    "Bundesgericht:\n1. Die Beschwerde wird abgewiesen.",
    "fr": "Faits:\nA. Accident.\n\nConsidérant en droit:\n\n1. Le recours est recevable.\n\n2. La rechute.\n2.1 Elle "
    "suppose un lien.\n\nPar ces motifs, le Tribunal fédéral prononce:\n1. Le recours est rejeté.",
    "it": "Fatti:\nA. Infortunio.\n\nDiritto:\n\n1. Presupposto processuale.\n\n2. La ricaduta.\n\nPer questi "
    "motivi, il Tribunale federale pronuncia:\n1. Il ricorso è respinto.",
}
COLS = ["decision_id", "docket_number", "decision_date", "publication_date", "scraped_at", "language", "title",
        "legal_area", "full_text"]  # fmt: skip
ROWS = [
    ("bger_8C_493_2025", "8C_493/2025", "2026-04-02", "", "2026-04-20T08:00:00", "de",
     "Unfallversicherung (Rückfall),", "", TEXT["de"]),
    ("bger_8C_307_2025", "8C_307/2025", "2026-04-08", "2026-05-26", "2026-05-26T08:00:00", "fr",
     "Assurance-accidents (rechute),", "Assurance-accidents", TEXT["fr"]),
    ("bger_8C_199_2026", "8C_199/2026", "2026-04-27", "", "2026-05-02T08:00:00", "it",
     "Assicurazione contro gli infortuni,", "", TEXT["it"]),
    ("bger_5A_1_2026", "5A_1/2026", "2026-05-04", "", "2026-05-10T08:00:00", "de", "Erbrecht,", "Erbrecht",
     "Erbteilung."),
]  # fmt: skip
KEY = "test-key-not-a-secret-4242"
JUDGE = "apertus-v1-5-8b"
LARGE = "apertus-v1-5-70b"
ANSWERS = {"8C_493/2025": (-0.02, -4.0), "8C_307/2025": (-3.0, -0.05), "8C_199/2026": (-0.7, -0.7)}
CODES = ("language", "placeholder", "new_identifier", "modal_strength", "glossary_term", "suva_named",
         "outcome_restated", "speaker", "entailment", "duplicate")  # fmt: skip
PASS = dict.fromkeys(CODES, "pass")


class Gateway:
    """Fake layer-2 endpoint: Ja/Nein log-probabilities per docket."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        docket = body["messages"][1]["content"].split(":", 1)[0].removeprefix("Urteil ")
        ja, nein = ANSWERS[docket]
        alts = [{"token": "Ja", "logprob": ja}, {"token": "Nein", "logprob": nein}]
        choice = {
            "message": {"content": "Ja"},
            "finish_reason": "length",
            "logprobs": {"content": [{"token": "Ja", "logprob": ja, "top_logprobs": alts}]},
        }
        return httpx.Response(200, json={"model": JUDGE, "choices": [choice], "usage": {"prompt_tokens": 9}})


class FakeEngine:
    """Declared fake of src.summarize.engine.summarise(source): a fixed EngineResult per ruling.

    `missing`: dockets answered without a French fiche; `miss`: dockets that raise a replay miss; `variant`: a word
    appended to every body (a changed text, so a new version)."""

    def __init__(self, missing=frozenset(), miss=frozenset(), variant=""):
        self.missing, self.miss, self.variant = missing, miss, variant
        self.seen: list[str] = []

    def __call__(self, source):
        from src.llm.client import ReplayMiss
        from src.summarize.engine_types import CallRecord, EngineResult, Fiche, Proposition, Sentence

        self.seen.append(source.docket)
        if source.docket in self.miss:
            raise ReplayMiss("no cached answer for this test")
        assert source.text.startswith(("Sachverhalt", "Faits", "Fatti")) and source.text_id
        props = (
            Proposition("P1", "fact", "court", "Unfall.", "E.1", True),
            Proposition("P2", "rule", "court", "Zusammenhang.", "E.2.1", True),
            Proposition("P3", "answer", "court", "Abgewiesen.", None, True),
        )
        calls, fiches = [], {}

        def call(purpose, language, tag, answer):
            rec = CallRecord(
                call_id=str(uuid.uuid4()), purpose=purpose, prompt_version=tag, language=language,
                messages=({"role": "system", "content": "fake"}, {"role": "user", "content": f"{tag} {source.docket}"}),
                response_text=answer, requested_model=LARGE, served_model=LARGE, size="large",
                params={"temperature": 0, "max_tokens": 50,
                        "client_log": {"cache_key": uuid.uuid4().hex * 2, "attempt": 1, "endpoint": "/chat/completions",
                                       "http_status": 200, "finish_reason": "stop"}},
                usage={"prompt_tokens": 100, "completion_tokens": 20}, latency_ms=12, cache_hit=False, error=None,
                started_at="2026-11-28T10:00:00+00:00", finished_at="2026-11-28T10:00:01+00:00",
            )  # fmt: skip
            calls.append(rec)
            return rec.call_id

        call("record", None, "record@1/read", "{}")
        for lang in ("de", "fr"):
            if lang == "fr" and source.docket in self.missing:
                continue
            write = call("write", lang, f"v3-write@2/{lang}", "fiche")
            call("entail", lang, "entail@1/v3", "Ja")
            sentences = (
                Sentence(1, 1, f"Fakt {lang}.", ("P1",), "written", 0.97, "E.1", "Unfall.", None, PASS),
                Sentence(2, 1, f"Regel {lang}.", ("P2",), "written", 0.95, "E.2.1", "Zusammenhang.", None,
                         PASS | {"glossary_term": "not_applicable"}),
                Sentence(3, 2, f"Weg {lang}.", ("P2",), "removed", 0.4, "E.2", None, "not entailed",
                         {"entailment": "fail"}),
                Sentence(4, 2, f"Ausgang {lang}.", (), "code"),
            )  # fmt: skip
            body = f"Fakt {lang}. Regel {lang}.\n\nAusgang {lang}.{self.variant}"
            fiches[lang] = Fiche(lang, "v3", "ok", body, sentences, 88.0, "high", (), write, None)
        return EngineResult(source.ruling_id, "v3@a4a1504", "ok", props, fiches, tuple(calls))


class BrokenEngine:
    """Declared fake: 8C_307/2025 raises after two calls (as src.summarize.engine does on a bug: the calls already
    made ride on the exception, `engine_calls`); any other ruling comes back without its French fiche."""

    def __call__(self, source):
        result = FakeEngine(missing=frozenset({source.docket}))(source)
        if source.docket == "8C_307/2025":
            exc = ValueError("unclassified v3 problem: invented for this test")
            exc.engine_calls, exc.engine_version = result.calls[:2], "v3@a4a1504"
            raise exc
        return result


DEPLOYED: dict[str, bool] = {}
# The default profile pins the scorer as layer2_judge V2.0.0, which src/layer2 cannot run yet (docs/LAYER3.md G-14):
# layer 2 and layer 3 run on summaries_8b (src/db/seed/profiles.json).
PROFILE = "summaries_8b"


def _version_trigger_runs_as_owner(url) -> bool:
    """summ.before_insert_version locks the summary row (FOR UPDATE), which needs an UPDATE privilege the pipeline
    group does not have: the function must run as its owner (SECURITY DEFINER, 80_triggers.sql)."""
    import psycopg

    with psycopg.connect(url) as conn:
        return conn.execute(
            "SELECT prosecdef FROM pg_proc WHERE oid = 'summ.before_insert_version'::regproc"
        ).fetchone()[0]


def pipeline(url):
    from src.db.pg import connect

    conn = connect(url, actor="test")
    conn.execute("SET ROLE suva_g_pipeline")
    conn.commit()
    return conn


def rows(url, sql, *args):
    with pipeline(url) as conn, conn.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()


def request_summary(url, docket):
    """A UI request (ops.submit_request) as the API login (read + review groups), its only write path for it."""
    import psycopg

    with psycopg.connect(url) as conn:
        conn.execute("SET ROLE suva_api")
        conn.execute("SELECT set_config('app.actor', 'test-reviewer', false)")
        rid = conn.execute(
            "SELECT ops.submit_request('summary', NULL, NULL, (SELECT ruling_id FROM corpus.ruling WHERE docket = %s),"
            " 'suva_house')",
            (docket,),
        ).fetchone()[0]
        conn.commit()
    return str(rid)


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
    from src.layer2.run import run_layer2
    from src.llm.client import LLMClient
    from src.llm.config import LLMConfig

    base = os.environ["DATABASE_URL"]
    name = f"suva_test_{uuid.uuid4().hex[:10]}"
    tmp = tmp_path_factory.mktemp("layer3")
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    url = make_conninfo(**(conninfo_to_dict(base) | {"dbname": name}))
    try:
        res = deploy.run_psql(
            argparse.Namespace(compose=False, url=url), deploy.script_for(deploy.sql_files()), capture=True
        )
        assert res.returncode == 0, res.stderr
        DEPLOYED["version_trigger_runs_as_owner"] = _version_trigger_runs_as_owner(url)
        table = pa.Table.from_pylist([dict(zip(COLS, r, strict=True)) | {"appealed_court_raw": None} for r in ROWS])
        pq.write_table(table, tmp / "bger.parquet")
        with pipeline(url) as conn:
            loaded = load_registries(conn)
            assert any("summarise.json: V1.0.0" in line for line in loaded) and "suva_house V1.0.0" in loaded
            assert "default V0.5.0" in loaded and "summaries_8b V0.1.0" in loaded
            with conn.cursor() as cur:
                cur.execute("SELECT config FROM ops.component_version WHERE step = 'ingest'")
                cfg = IngestConfig.model_validate(cur.fetchone()[0])
            load_base(conn, tmp / "bger.parquet", cfg, [], actor="test")
            assert run_layer1(conn, runs_dir=tmp / "runs", actor="test")["kept"] == 3
            llm = LLMConfig(mode="live", name=LARGE, name_small=JUDGE, base_url="https://endpoint.invalid/v1",
                            api_key=KEY, concurrency=2)  # fmt: skip
            client = LLMClient(
                llm, store_dir=tmp / "store", transport=httpx.MockTransport(Gateway()), sleep=lambda s: 0
            )
            assert (
                run_layer2(conn, mode="live", profile=PROFILE, runs_dir=tmp / "runs", actor="test", client=client)[
                    "judged"
                ]
                == 3
            )
        yield url, tmp
    finally:
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def run3(url, tmp, engine, **kw):
    from src.layer3.run import run_layer3

    with pipeline(url) as conn:
        return run_layer3(conn, actor="test", engine=engine, few_shot=(), store=tmp / "store", runs_dir=tmp / "runs",
                          profile=PROFILE, **kw)  # fmt: skip


def test_a_run_stores_the_pair_with_claims_citations_checks_calls_and_closes_the_request(db):
    url, tmp = db
    rid = request_summary(url, "8C_307/2025")  # the lowest score: summarised because it is requested
    engine = FakeEngine()
    out = run3(url, tmp, engine, limit=2)
    assert (out["status"], out["stored"], out["failed"], out["rulings_in"]) == ("succeeded", 3, 0, 3)
    assert engine.seen[:2] == ["8C_493/2025", "8C_199/2026"]  # top 2 by layer-2 score, then the request
    assert out["verified_versions"] == 3 and out["requests_done"] == 1 and out["llm_calls"] == 15
    run_id = out["run_id"]

    current = {
        d: rest
        for d, *rest in rows(
            url,
            """SELECT r.docket, v.title_de, v.title_fr, v.body_de, v.body_fr, v.quality_status::text, v.origin::text,
                      v.creator_kind::text, v.mode::text, v.version_no, v.preset_code
               FROM summ.v_summary_current v JOIN corpus.ruling r USING (ruling_id)""",
        )
    }
    assert set(current) == set(ANSWERS)
    de = current["8C_493/2025"]
    assert de[0] == "BGer-Urteil 8C_493/2025 vom 2. April 2026 – Unfallversicherung (Rückfall)"
    assert de[1] == "Arrêt du TF 8C_493/2025 du 2 avril 2026"  # the German matter is never put in the French title
    assert de[2].startswith("Fakt de.") and de[3].startswith("Fakt fr.")
    assert de[4:] == ["verified", "generated", "pipeline", "REPLAY", 1, "suva_house"]
    assert current["8C_199/2026"][:2] == [
        "BGer-Urteil 8C_199/2026 vom 27. April 2026",
        "Arrêt du TF 8C_199/2026 du 27 avril 2026",
    ]

    claims = rows(
        url,
        """SELECT r.docket, t.language::text, c.ordinal, c.section::text, c.status::text, c.model_text IS NULL,
                  (SELECT string_agg(k.e_number, ',' ORDER BY cc.ordinal) FROM summ.claim_citation cc
                   JOIN corpus.consideration k USING (consideration_id) WHERE cc.claim_id = c.claim_id)
           FROM summ.summary_claim c JOIN summ.summary_text t USING (summary_text_id)
           JOIN summ.summary_version v USING (summary_version_id) JOIN summ.summary s USING (summary_id)
           JOIN corpus.ruling r USING (ruling_id) WHERE v.creator_run_id = %s AND r.docket = '8C_493/2025'
           ORDER BY 2, 3""",
        run_id,
    )
    assert claims == [
        ("8C_493/2025", "de", 1, "facts", "verified", False, "1"),
        ("8C_493/2025", "de", 2, "law", "verified", False, "2.1"),
        ("8C_493/2025", "de", 3, "outcome", "verified", True, None),
        ("8C_493/2025", "fr", 1, "facts", "verified", False, "1"),
        ("8C_493/2025", "fr", 2, "law", "verified", False, "2.1"),
        ("8C_493/2025", "fr", 3, "outcome", "verified", True, None),
    ]
    # the Italian ruling has no consideration 2.1: its law claim cites nothing rather than a wrong consideration (G1)
    it_cites = rows(
        url,
        """SELECT count(*) FROM summ.claim_citation cc JOIN summ.summary_claim c USING (claim_id)
           JOIN summ.summary_text t USING (summary_text_id) JOIN summ.summary_version v USING (summary_version_id)
           JOIN summ.summary s USING (summary_id) JOIN corpus.ruling r USING (ruling_id)
           WHERE v.creator_run_id = %s AND r.docket = '8C_199/2026'""",
        run_id,
    )
    assert it_cites == [(2,)]  # E.1 in each language

    checks = dict(
        rows(
            url,
            """SELECT ru.rule_code || ':' || k.target_kind || ':' || k.status::text, count(*)
               FROM summ.verification_check k JOIN ops.rule ru USING (rule_id) WHERE k.run_id = %s GROUP BY 1""",
            run_id,
        )
    )
    assert checks["V3_ENTAILMENT:claim:pass"] == 12  # 2 model claims x 2 languages x 3 rulings
    assert checks["V3_ENTAILMENT:text:fail"] == 6  # one removed sentence per fiche
    assert checks["V3_GLOSSARY_TERM:claim:not_applicable"] == 6
    assert sum(checks.values()) == 3 * 2 * (2 * len(CODES) + 1)
    detail = rows(
        url,
        """SELECT k.detail FROM summ.verification_check k JOIN ops.rule ru USING (rule_id)
           WHERE k.run_id = %s AND ru.rule_code = 'V3_ENTAILMENT' AND k.target_kind = 'text' LIMIT 1""",
        run_id,
    )[0][0]
    assert detail["why_not"] == "not entailed" and detail["entailment"] == 0.4 and detail["attributed"] == "engine"

    links = rows(
        url,
        """SELECT t.language::text, c.purpose, c.language::text, c.step::text, c.model_role::text, c.requested_model,
                  c.http_status, c.finish_reason, b.sha256 IS NOT NULL
           FROM summ.summary_text t JOIN summ.summary_version v USING (summary_version_id)
           JOIN ops.llm_call c ON c.llm_call_id = t.llm_call_id JOIN ops.blob b ON b.sha256 = c.messages_sha256
           WHERE v.creator_run_id = %s ORDER BY 1""",
        run_id,
    )
    assert (
        links
        == [("de", "write", "de", "summarise", "generator", LARGE, 200, "stop", True)] * 3
        + [("fr", "write", "fr", "summarise", "generator", LARGE, 200, "stop", True)] * 3
    )
    steps = dict(
        rows(
            url, "SELECT purpose || ':' || step::text, count(*) FROM ops.llm_call WHERE run_id = %s GROUP BY 1", run_id
        )
    )
    assert steps == {"record:summarise": 3, "write:summarise": 6, "entail:verify": 6}

    segs = rows(
        url,
        """SELECT r.docket, g.status::text, g.consideration_count, g.method::text, g.is_primary
           FROM corpus.segmentation g JOIN corpus.ruling_text t USING (text_id) JOIN corpus.ruling r USING (ruling_id)
           ORDER BY 1""",
    )
    assert segs == [("8C_199/2026", "ok", 2, "own_splitter", False), ("8C_307/2025", "ok", 3, "own_splitter", False),
                    ("8C_493/2025", "ok", 4, "own_splitter", False)]  # fmt: skip
    spans = dict(rows(url, "SELECT operation, count(*) FROM ops.span WHERE run_id = %s GROUP BY 1", run_id))
    assert spans == {"layer3.run": 1, "layer3.summarise": 3, "segment.split": 3, "verify.checks": 3, "llm.call": 15}
    req = rows(url, "SELECT status::text, run_id::text, status_detail FROM ops.user_request WHERE request_id = %s", rid)
    assert req[0][:2] == ("done", run_id) and "verified" in req[0][2]
    run_row = rows(
        url,
        "SELECT kind::text, status::text, mode::text, resolved_models FROM ops.pipeline_run WHERE run_id = %s",
        run_id,
    )
    assert run_row[0][:3] == ("summarise", "succeeded", "REPLAY")
    metrics = dict(rows(url, "SELECT metric_code, value FROM ops.run_metric WHERE run_id = %s", run_id))
    assert (metrics["stored"], metrics["claims"], metrics["removed_sentences"]) == (3, 18, 6)
    events = {c for (c,) in rows(url, "SELECT event_code FROM ops.log_event WHERE run_id = %s", run_id)}
    assert {"layer3.run.selected", "layer3.run.summary", "layer3.files.written", "layer3.summary.stored"} <= events

    files = Path(out["files"])
    manifest = json.loads((files / "manifest.json").read_text())
    from src.db.pg import sha256_file

    assert {n: sha256_file(files / n) for n in manifest["files"]} == manifest["files"]
    assert len((files / "calls.jsonl").read_text().splitlines()) == 15
    assert KEY not in (files / "calls.jsonl").read_text()


def test_the_pair_trigger_refuses_a_version_with_one_language(db):
    import psycopg

    url, _ = db
    with pipeline(url) as conn:
        v = conn.execute(
            """SELECT v.summary_id, v.preset_version_id, v.component_version_id, v.source_segmentation_id,
                      v.creator_run_id, t.llm_call_id
               FROM summ.summary_version v JOIN summ.summary_text t USING (summary_version_id) LIMIT 1"""
        ).fetchone()
        vid = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO summ.summary_version (summary_version_id, summary_id, version_no, origin, preset_version_id,
                   component_version_id, source_segmentation_id, creator_kind, creator_run_id, mode)
               VALUES (%s, %s, NULL, 'generated', %s, %s, %s, 'pipeline', %s, 'REPLAY')""",
            (vid, *v[:5]),
        )
        conn.execute(
            """INSERT INTO summ.summary_text (summary_version_id, language, title_line, body, word_count,
                   paragraph_count, llm_call_id) VALUES (%s, 'de', 'T', 'B', 1, 1, %s)""",
            (vid, v[5]),
        )
        with pytest.raises(psycopg.errors.RaiseException, match="exactly one German and one French text"):
            conn.commit()


def test_a_rerun_with_the_same_texts_adds_no_version_and_a_changed_text_a_new_current_one(db):
    url, tmp = db
    again = run3(url, tmp, FakeEngine(), limit=2, requests=False)
    assert (again["status"], again["stored"], again["unchanged"]) == ("succeeded", 0, 2)
    changed = run3(url, tmp, FakeEngine(variant=" Neu."), limit=1, requests=False)
    assert changed["stored"] == 1
    versions = rows(
        url,
        """SELECT v.version_no, v.is_current FROM summ.summary_version v JOIN summ.summary s USING (summary_id)
           JOIN corpus.ruling r USING (ruling_id) WHERE r.docket = '8C_493/2025' AND v.creator_kind = 'pipeline'
           ORDER BY 1""",
    )
    assert versions[-2:] == [(1, False), (2, True)]


def test_a_missing_language_fails_that_ruling_only_and_stores_no_version_for_it(db):
    url, tmp = db
    out = run3(url, tmp, FakeEngine(missing=frozenset({"8C_199/2026"}), variant=" Drei."), limit=2, requests=False)
    assert (out["status"], out["stored"], out["failed"]) == ("partial", 1, 1)
    assert out["dockets"] == {"8C_493/2025": "stored", "8C_199/2026": "failed"}
    span = rows(
        url,
        """SELECT s.status::text, s.error_reason_code FROM ops.span s JOIN corpus.ruling r USING (ruling_id)
           WHERE s.run_id = %s AND s.operation = 'layer3.summarise' AND r.docket = '8C_199/2026'""",
        out["run_id"],
    )
    assert span == [("error", "L3_LANGUAGE_MISSING")]
    stored = rows(url, "SELECT count(*) FROM summ.summary_version WHERE creator_run_id = %s", out["run_id"])
    assert stored == [(1,)]
    calls = rows(
        url,
        """SELECT count(*) FROM ops.llm_call c JOIN corpus.ruling r USING (ruling_id)
           WHERE c.run_id = %s AND r.docket = '8C_199/2026'""",
        out["run_id"],
    )
    assert calls == [(3,)]  # the failed ruling's calls are traced all the same


def test_replay_misses_everywhere_fail_the_run_and_its_request(db):
    from src.layer3.run import Layer3RunFailed

    url, tmp = db
    rid = request_summary(url, "8C_307/2025")
    engine = FakeEngine(miss=frozenset(ANSWERS))
    with pytest.raises(Layer3RunFailed) as failed:
        run3(url, tmp, engine, limit=1)
    assert failed.value.replay_only
    assert rows(url, "SELECT status::text, error_summary IS NOT NULL FROM ops.pipeline_run WHERE kind = 'summarise' "
                     "ORDER BY started_at DESC LIMIT 1") == [("failed", True)]  # fmt: skip
    req = rows(url, "SELECT status::text, status_detail FROM ops.user_request WHERE request_id = %s", rid)
    assert req[0][0] == "failed" and req[0][1].startswith("L3_REPLAY_MISS")


def test_a_current_expert_edit_stays_current_and_few_shot_dockets_are_never_summarised(db):
    import psycopg

    from src.layer3.run import run_layer3

    url, tmp = db
    with psycopg.connect(url) as conn:
        conn.execute("SET ROLE suva_api")
        conn.execute("SELECT set_config('app.actor', 'test-reviewer', false)")
        parent = conn.execute(
            """SELECT v.summary_version_id FROM summ.v_summary_current v JOIN corpus.ruling r USING (ruling_id)
               WHERE r.docket = '8C_493/2025'"""
        ).fetchone()[0]
        expert = conn.execute(
            "SELECT summ.create_expert_version(%s, 'de', 'BGer-Urteil 8C_493/2025', 'Korrigiert.', %s)",
            (parent, json.dumps([{"paragraph_no": 1, "section": "facts", "text": "Korrigiert.", "cites": []}])),
        ).fetchone()[0]
        conn.commit()
    out = run3(url, tmp, FakeEngine(variant=" Vier."), limit=1, requests=False)
    assert out["stored"] == 1 and out["expert_current_kept"] == 1
    newest = "SELECT max(v.version_no) FROM summ.summary_version v JOIN summ.summary s USING (summary_id) " \
             "JOIN corpus.ruling r USING (ruling_id) WHERE r.docket = '8C_493/2025'"  # fmt: skip
    before = rows(url, newest)
    again = run3(url, tmp, FakeEngine(variant=" Vier."), limit=1, requests=False)  # red before: compared with the
    assert (again["stored"], again["unchanged"]) == (0, 1)  # expert's current text, so a version on every rerun
    assert rows(url, newest) == before
    current = rows(
        url,
        """SELECT v.summary_version_id::text, v.origin::text FROM summ.v_summary_current v
           JOIN corpus.ruling r USING (ruling_id) WHERE r.docket = '8C_493/2025'""",
    )
    assert current == [(str(expert), "expert_edit")]
    engine = FakeEngine()
    with pipeline(url) as conn:
        res = run_layer3(conn, actor="test", engine=engine, few_shot=("8C_493/2025",), store=tmp / "store",
                         profile=PROFILE, runs_dir=tmp / "runs", limit=1, requests=False)  # fmt: skip
    assert engine.seen == ["8C_199/2026"] and res["rulings_in"] == 1
    with pipeline(url) as conn, pytest.raises(LookupError, match="few-shot"):
        run_layer3(conn, actor="test", engine=engine, few_shot=("8C_493/2025",), dockets=["8C_493/2025"],
                   profile=PROFILE, store=tmp / "store", runs_dir=tmp / "runs")  # fmt: skip


def test_the_deployed_ddl_lets_the_pipeline_group_insert_a_summary_version(db):
    """The deployed DDL (80_triggers.sql: summ.before_insert_version is SECURITY DEFINER) lets the pipeline group lock
    the summary row it versions; red on the DDL before the fix."""
    assert DEPLOYED["version_trigger_runs_as_owner"]  # and the writer tests above insert versions as the group


def test_the_real_engine_is_wired_through_the_writer_and_a_replay_miss_is_counted_not_faked(db):
    """No fake engine here: src.summarize.engine.summarise and src.summarize.examples, imported by the writer at run
    time, with a replay client on an empty store (no call reaches any endpoint). The first call misses, the engine
    lets ReplayMiss through, and the writer records L3_REPLAY_MISS for every ruling."""
    from src.layer3.run import Layer3RunFailed, run_layer3

    url, tmp = db
    with pipeline(url) as conn, pytest.raises(Layer3RunFailed) as failed:
        run_layer3(conn, mode="replay", actor="test", store=tmp / "empty_store", runs_dir=tmp / "runs", limit=2,
                   profile=PROFILE, requests=False)  # fmt: skip
    assert failed.value.replay_only
    summaries = Path(str(failed.value).split("files in ")[1].split(";")[0]) / "summaries.jsonl"
    lines = [json.loads(line) for line in summaries.read_text().splitlines()]
    assert {(r["docket"], r["outcome"], r["reason_code"]) for r in lines} == {
        ("8C_493/2025", "skipped", "L3_REPLAY_MISS"),
        ("8C_199/2026", "skipped", "L3_REPLAY_MISS"),
    }


def test_a_run_with_no_ruling_stored_still_commits_every_call_its_rulings_made(db):
    """Red before: the run raised before any load, so the calls of rulings that failed (an engine bug after two calls,
    a missing French fiche after three) reached no ops.llm_call; and the manifest is rewritten failed."""
    from src.layer3.run import Layer3RunFailed

    url, tmp = db
    with pytest.raises(Layer3RunFailed) as failed:
        run3(url, tmp, BrokenEngine(), dockets=["8C_307/2025", "8C_199/2026"], requests=False)
    assert not failed.value.replay_only
    latest = "SELECT run_id::text, status::text FROM ops.pipeline_run WHERE kind = 'summarise' ORDER BY started_at DESC"
    run_id, status = rows(url, latest + " LIMIT 1")[0]
    assert status == "failed"
    calls = dict(
        rows(
            url,
            """SELECT r.docket, count(*) FROM ops.llm_call c JOIN corpus.ruling r USING (ruling_id)
               WHERE c.run_id = %s GROUP BY 1""",
            run_id,
        )
    )
    assert calls == {"8C_307/2025": 2, "8C_199/2026": 3}
    spans = rows(
        url,
        """SELECT r.docket, s.status::text, s.error_reason_code FROM ops.span s JOIN corpus.ruling r USING (ruling_id)
           WHERE s.run_id = %s AND s.operation = 'layer3.summarise' ORDER BY 1""",
        run_id,
    )
    assert spans == [("8C_199/2026", "error", "L3_LANGUAGE_MISSING"), ("8C_307/2025", "error", "L3_ENGINE_FAILED")]
    assert rows(url, "SELECT count(*) FROM ops.span WHERE run_id = %s AND operation = 'llm.call'", run_id) == [(5,)]
    assert rows(url, "SELECT count(*) FROM summ.summary_version WHERE creator_run_id = %s", run_id) == [(0,)]
    parsed = rows(url, "SELECT DISTINCT parsed_ok, parse_error FROM ops.llm_call WHERE run_id = %s", run_id)
    assert parsed == [(True, None)]
    metrics = dict(rows(url, "SELECT metric_code, value FROM ops.run_metric WHERE run_id = %s", run_id))
    assert (metrics["llm_calls"], metrics["failed"], metrics["stored"]) == (5, 2, 0)
    manifest = json.loads((tmp / "runs" / run_id / "manifest.json").read_text())
    assert manifest["status"] == "failed" and manifest["error"].startswith("Layer3RunFailed")
    assert manifest["metrics"]["llm_calls"] == 5
