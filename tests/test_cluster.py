"""The cluster (docker-compose.yml, Dockerfile, docs/DEPLOY.md): pins, secrets, logins, the base-file fetch."""

from __future__ import annotations

import hashlib
import json
import re
import stat
from pathlib import Path

import pytest

from src.db import logins
from src.ingest import fetch

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")


def test_fetch_pins_the_revision_of_the_ingest_registry():
    registry = json.loads((ROOT / "src/ingest/registry/ingest.json").read_text(encoding="utf-8"))
    revisions = {v["config"]["hf_revision"] for v in registry["versions"]}
    assert revisions == {fetch.REVISION}
    assert fetch.REVISION in fetch.URL and re.fullmatch(r"[0-9a-f]{64}", fetch.SHA256)


def test_fetch_keeps_a_good_copy_and_refuses_a_different_one(tmp_path):
    body = b"parquet bytes"
    (tmp_path / "bger.parquet").write_bytes(body)
    good = hashlib.sha256(body).hexdigest()
    assert fetch.fetch(tmp_path, url="http://unused.invalid/", expected=good) == tmp_path / "bger.parquet"
    with pytest.raises(SystemExit, match="exists with SHA-256"):
        fetch.fetch(tmp_path, url="http://unused.invalid/", expected="0" * 64)


def test_fetch_downloads_checks_and_never_keeps_a_wrong_file(tmp_path):
    """Declared mock: a local HTTP server stands in for Hugging Face (G9)."""
    import functools
    import http.server
    import threading

    served = tmp_path / "served"
    served.mkdir()
    body = b"pinned parquet bytes" * 1000
    (served / "bger.parquet").write_bytes(body)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(served))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/bger.parquet"
    try:
        with pytest.raises(SystemExit, match="does not match"):
            fetch.fetch(tmp_path / "bad", url=url, expected="0" * 64)
        assert not any((tmp_path / "bad").iterdir())  # neither the file nor its .part
        got = fetch.fetch(tmp_path / "good", url=url, expected=hashlib.sha256(body).hexdigest())
        assert got.read_bytes() == body
    finally:
        server.shutdown()


def test_login_passwords_come_from_the_environment_only():
    long = "x" * logins.MIN_LENGTH
    assert logins.plan({"SUVA_PIPELINE_PASSWORD": long}) == {
        "suva_pipeline": long,
        "suva_api": None,
        "suva_report": None,
    }
    with pytest.raises(SystemExit, match="shorter than"):
        logins.plan({"SUVA_API_PASSWORD": "short"})


def test_init_env_fills_only_missing_secrets_and_restricts_the_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text("LLM_NAME=apertus-v1-5-8b\nPOSTGRES_PASSWORD=kept-value-of-the-operator\nSUVA_API_PASSWORD=\n")
    written = logins.init_env(env)
    assert written == ["SUVA_PIPELINE_PASSWORD", "SUVA_API_PASSWORD", "SUVA_REPORT_PASSWORD"]
    text = env.read_text()
    assert "POSTGRES_PASSWORD=kept-value-of-the-operator" in text and "LLM_NAME=apertus-v1-5-8b" in text
    assert text.count("SUVA_API_PASSWORD=") == 1 and "SUVA_API_PASSWORD=\n" not in text
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert logins.init_env(env) == []  # idempotent
    assert env.read_text() == text


def test_every_image_is_pinned_by_digest():
    images = re.findall(r"^\s*image:\s*(\S+)", COMPOSE, re.M)
    assert images, "no image in docker-compose.yml"
    for image in images:
        assert image.startswith("${SUVA_IMAGE") or "@sha256:" in image, image
    base = re.search(r"^ARG PYTHON_IMAGE=(\S+)", (ROOT / "Dockerfile").read_text(), re.M)
    assert base and "@sha256:" in base.group(1)


def test_no_secret_and_no_endpoint_in_the_compose_file():
    for line in COMPOSE.splitlines():
        m = re.match(r"\s*(\w*PASSWORD|\w*API_KEY|LLM_BASE_URL):\s*(.+)", line)
        if m:
            assert m.group(2).startswith("${"), f"literal value for {m.group(1)}"
    assert "POSTGRES_HOST_AUTH_METHOD: trust" not in COMPOSE
    assert "https://" not in COMPOSE  # endpoints come from .env (G3)


def test_the_database_and_the_local_model_have_no_route_out():
    backend = re.search(r"^networks:\n  backend:\n    internal: true", COMPOSE, re.M)
    assert backend, "the backend network must be internal"
    for service in ("db", "llm"):
        block = re.search(rf"^  {service}:\n(.*?)(?=^  \w|\Z)", COMPOSE, re.M | re.S).group(1)
        assert "      - egress" not in block, f"{service} must not reach the egress network"
        assert "ports:" not in block, f"{service} must not publish a port"


def test_secrets_and_derived_data_never_enter_the_image():
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    for entry in (".env", ".env.*", "data", "tmp", ".git"):
        assert entry in ignored, entry


MAKEFILE = (ROOT / "Makefile").read_text(encoding="utf-8")


def _recipe(target: str) -> list[str]:
    block = re.search(rf"^{target}:.*\n((?:\t.*\n)+)", MAKEFILE, re.M)
    assert block, f"no target {target}"
    return [line.strip() for line in block.group(1).splitlines()]


def _service(name: str) -> str:
    found = re.search(rf"^  {name}:\n(.*?)(?=^  \w[\w-]*:\n|^\S|\Z)", COMPOSE, re.M | re.S)
    assert found, f"no service {name}"
    return found.group(1)


def test_bootstrap_guards_the_schema_around_the_deploy():
    steps = _recipe("bootstrap")
    assert [s.split()[-1] for s in steps] == ["CMD=check", "db-deploy", "CMD=record", "db-logins"]


def test_load_ends_with_the_closure_check():
    assert _recipe("load")[-1].endswith("ingest-closure")
    assert _recipe("ingest-closure") == ["$(PY) -m src.ingest closure"]


def test_validate_is_an_ops_job_run_by_the_pipeline_login():
    block = _service("validate")
    assert 'profiles: ["ops"]' in block and 'command: ["make", "validate"]' in block
    assert "<<: *pipeline-db" in block and "      - egress" not in block


def test_the_api_login_never_takes_the_pipeline_role():
    block = _service("app")
    assert "PGUSER: suva_api" in block and 'DB_PIPELINE_ROLE: ""' in block


def test_every_job_that_reads_replay_caches_mounts_data_derived():
    for name in ("load", "pipeline", "app", "validate"):
        assert "${SUVA_DERIVED_SOURCE:-suva_derived}:/app/data/derived" in _service(name), name
