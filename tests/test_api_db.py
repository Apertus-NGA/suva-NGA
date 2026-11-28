"""The API end to end on a throwaway PostgreSQL: deploy src/db/sql, ingest four rulings (DE, FR, IT accident rulings and
one inheritance ruling), layer 1, layer 2 with a declared fake gateway (tests/test_layer2_db.py), then every endpoint
through the API login (SET ROLE suva_api), and one real launch of layer 1 -> layer 2 as subprocesses.
Runs only with DATABASE_URL (CI `db` job, or a local database)."""

from __future__ import annotations

import os
import time

import pytest

from tests.test_layer2_db import db  # noqa: F401  (the layer-2 fixture: deploy, ingest, layer 1)

pytestmark = [pytest.mark.db, pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="needs DATABASE_URL")]


@pytest.fixture(scope="module")
def api(db_layer2):
    from fastapi.testclient import TestClient

    from src.api.app import create_app
    from src.api.runs import Launcher
    from src.api.settings import Settings

    url, tmp, store = db_layer2
    settings = Settings(runs_enabled=True, layer2_store=str(store))
    old = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        yield TestClient(create_app(settings, Launcher(settings, log_dir=tmp / "api-logs"))), url
    finally:
        os.environ["DATABASE_URL"] = old or ""


@pytest.fixture(scope="module")
def db_layer2(db):  # noqa: F811  (the imported fixture, requested by name)
    """The layer-2 test database with one live layer-2 run answered by the fake gateway (its cache = the store)."""
    from tests.test_layer2_db import Gateway, client, run

    url, tmp = db
    out = run(url, tmp, client(tmp / "api_store", Gateway()), mode="live")
    assert (out["status"], out["judged"]) == ("succeeded", 3)
    return url, tmp, tmp / "api_store"


def by_docket(c, docket):
    items = c.get("/api/rulings", params={"q": docket}).json()["items"]
    assert len(items) == 1, items
    return items[0]


def stored(url, sql, *args):
    from tests.test_layer2_db import rows

    return rows(url, sql, *args)


def test_every_ruling_is_listed_with_its_status_area_and_score(api):
    c, _ = api
    page = c.get("/api/rulings", params={"sort": "score", "order": "desc"}).json()
    assert page["total"] == 4
    by = {r["docket"]: r for r in page["items"]}
    assert {d: r["status"] for d, r in by.items()} == {
        "8C_493/2025": "potentially_relevant",
        "8C_307/2025": "potentially_relevant",
        "8C_199/2026": "potentially_relevant",
        "5A_1/2026": "filtered_out",
    }
    assert not any(r["is_new"] for r in page["items"])  # one ingest only: the base, not an incremental one
    assert c.get("/api/rulings", params={"inbox": "true"}).json()["total"] == 0
    assert {d: r["area"] for d, r in by.items()} == {
        "8C_493/2025": "UV",  # Unfallversicherung (DE)
        "8C_307/2025": "UV",  # Assurance-accidents (FR)
        "8C_199/2026": "UV",  # Assicurazione contro gli infortuni (IT)
        "5A_1/2026": "other",
    }
    assert page["items"][0]["docket"] == "8C_493/2025"  # P(Ja) highest of the fake gateway's answers
    judged = [r for r in page["items"] if r["step"] == "layer2_judge"]
    assert len(judged) == 3 and all(r["score_raw"] is not None and r["mode"] == "LIVE" for r in judged)
    assert all(r["explanation_de"] for r in page["items"])
    assert by["5A_1/2026"]["reason_code"].startswith("L1_DROP")


def test_filters_and_facets_agree(api):
    c, _ = api
    fr = c.get("/api/rulings", params={"language": "fr"}).json()
    assert [r["docket"] for r in fr["items"]] == ["8C_307/2025"]
    assert c.get("/api/rulings", params={"core": "true"}).json()["total"] == 3
    assert c.get("/api/rulings", params={"court": "5A"}).json()["total"] == 1
    facets = c.get("/api/facets", params={"court": "8C"}).json()
    assert facets["total"] == 3
    assert {f["value"]: f["n"] for f in facets["courts"]} == {"8C": 3, "5A": 1}  # its own filter dropped
    assert {f["value"]: f["n"] for f in facets["statuses"]} == {"potentially_relevant": 3}


def test_the_ruling_page_shows_the_text_and_why(api):
    c, url = api
    row = by_docket(c, "8C_493/2025")
    detail = c.get(f"/api/rulings/{row['id']}").json()
    rel = detail["relevance"]
    assert detail["text"].startswith("Die Suva ist Beschwerdegegnerin.")
    assert rel["state"] == "scored" and rel["label"] == "potentially" and rel["step"] == "layer2_judge"
    assert [h["step"] for h in rel["trace"]] == ["layer2_judge", "layer1_filter"]
    fired = [x for x in rel["layer1"] if x["char_start"] is not None]
    assert fired and all(detail["text"][x["char_start"] : x["char_end"]] == x["matched_text"] for x in fired)
    (p_yes,) = stored(
        url,
        "SELECT j.p_yes FROM triage.llm_judgement j JOIN triage.assessment a USING (assessment_id)"
        " WHERE a.ruling_id = %s::uuid",
        row["id"],
    )[0]
    assert rel["layer2"]["p_yes"] == pytest.approx(p_yes) and rel["layer2"]["model"] == "apertus-v1-5-8b"
    assert detail["summaries"] == {"de": None, "fr": None} and detail["reference"] is None
    assert c.get("/api/rulings/00000000-0000-0000-0000-000000000000").status_code == 404


def test_an_expert_decides_on_a_potentially_ruling_and_takes_it_back(api):
    c, url = api
    row = by_docket(c, "8C_307/2025")
    rel = c.post(
        f"/api/rulings/{row['id']}/relevance",
        json={"action": "mark_relevant", "comment": "rule", "token": row["decision_token"]},
    )
    assert rel.status_code == 200 and rel.json()["status"] == "expert_relevant"
    stale = c.post(f"/api/rulings/{row['id']}/relevance", json={"action": "reopen", "token": row["decision_token"]})
    assert stale.status_code == 409  # the page that sent it still shows the state before the decision
    flip = c.post(f"/api/rulings/{row['id']}/relevance", json={"action": "mark_not_relevant"}).json()
    assert flip["status"] == "expert_not_relevant" and flip["expert"]["label"] == "out_of_scope"
    back = c.post(f"/api/rulings/{row['id']}/relevance", json={"action": "reopen"}).json()
    assert back["status"] == "potentially_relevant" and back["expert"]["verdict"] == "withdrawn"
    assert c.post(f"/api/rulings/{row['id']}/relevance", json={"action": "reopen"}).status_code == 409
    reviews = stored(
        url,
        "SELECT r.verdict::text, r.reviewed_label::text, r.payload ->> 'shown_status', r.actor,"
        " r.supersedes_review_id IS NOT NULL FROM gold.expert_review r"
        " JOIN triage.assessment a USING (assessment_id) WHERE a.ruling_id = %s::uuid ORDER BY r.created_at",
        row["id"],
    )
    assert reviews == [
        ("relevant", "potentially", "potentially_relevant", "expert", False),
        ("not_relevant", "potentially", "expert_relevant", "expert", True),
        ("withdrawn", "potentially", "expert_not_relevant", "expert", True),
    ]
    learning = c.get("/api/learning").json()
    assert learning["decisions"] == 2
    assert {(t["before"], t["after"]) for t in learning["transitions"]} == {
        ("potentially_relevant", "in_scope"),
        ("expert_relevant", "out_of_scope"),
    }


def test_requests_are_recorded_and_summary_writes_wait_for_a_summary(api):
    c, url = api
    added = c.post("/api/requests", json={"docket": "8C_691/2024"})
    assert added.status_code == 202 and added.json()["status"] == "pending"
    assert c.get(f"/api/requests/{added.json()['request_id']}").json()["docket"] == "8C_691/2024"
    assert c.post("/api/requests", json={"docket": "8C 691/2024"}).status_code == 422
    assert c.post("/api/requests", json={}).status_code == 422
    row = by_docket(c, "8C_199/2026")
    asked = c.post(f"/api/rulings/{row['id']}/summaries").json()
    assert asked["kind"] == "summary" and asked["preset_code"] == "suva_house"
    assert c.get(f"/api/rulings/{row['id']}").json()["summary_request"]["status"] == "pending"
    assert c.put(f"/api/rulings/{row['id']}/summaries/de", json={"body": "Ein Satz."}).status_code == 409
    assert c.post(f"/api/rulings/{row['id']}/summaries/fr/validate").status_code == 409
    assert stored(url, "SELECT count(*) FROM ops.user_request")[0][0] == 2


def test_scoring_describes_the_default_profile(api):
    c, _ = api
    s = c.get("/api/scoring").json()
    assert s["profile"]["code"] == "default"
    assert {x["step"] for x in s["steps"]} >= {"layer1_filter", "layer2_judge"}
    assert len(s["layer1_rules"]) >= 9 and s["rules"] == []


def test_the_api_launches_layer1_then_layer2_as_subprocesses(api):
    c, url = api
    before = stored(url, "SELECT count(*) FROM ops.pipeline_run WHERE kind IN ('layer1', 'layer2')")[0][0]
    started = c.post("/api/runs", json={"mode": "replay"})
    assert started.status_code == 202
    assert c.post("/api/runs", json={"mode": "replay"}).status_code in (202, 409)  # 409 while the job runs
    for _ in range(600):
        status = c.get("/api/runs").json()
        if not status["running"]:
            break
        time.sleep(0.1)
    job = status["last"]
    assert job["status"] == "succeeded", job
    assert [s["name"] for s in job["steps"]] == ["layer1", "layer2"]
    assert job["steps"][1]["summary"]["judged"] == 3  # every answer replayed from the fake gateway's cache
    after = stored(url, "SELECT count(*) FROM ops.pipeline_run WHERE kind IN ('layer1', 'layer2')")[0][0]
    assert after == before + 2
    assert {r["run_id"] for r in status["recent"]} >= {s["run_id"] for s in job["steps"]}
