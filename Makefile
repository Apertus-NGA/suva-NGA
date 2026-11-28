# Our single entry point (`make run` is our convention, D-042). Targets: AGENTS.md §6.
# A fresh clone with .env filled needs only `make run`: database up, migrated, ingested if empty, triage,
# summaries, then the API and UI on 127.0.0.1:8000. Every line is labelled LIVE or REPLAY (src/cli.py).
# crawl, refit, eval, eval-private and claims are still stubs that print STUB.

PY ?= $(if $(shell command -v uv 2>/dev/null),uv run --frozen python,python3)
MODE ?= replay
SERVE ?= 1
SUMMARY_LIMIT ?=
ARGS ?=
RUN_FLAGS = $(if $(SUMMARY_LIMIT),--summary-limit $(SUMMARY_LIMIT),) $(if $(filter 0,$(SERVE)),--no-serve,)

WRITE ?= 0

.PHONY: help run run-live replay-cache serve smoke-llm warmup crawl triage refit eval eval-private claims check db-up

help: ## list the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/'

run: ## end to end, REPLAY (no gateway call): db up + migrate, ingest if empty, triage, top SUMMARY_LIMIT (default 5) summaries, serve; SERVE=0 stops before serving
	$(PY) -m src.cli run --mode $(MODE) $(RUN_FLAGS) $(ARGS)

run-live: ## the same, LIVE (needs LLM_*); ARGS="--limit N": smoke, triage of the first N rulings not written, N summaries; ARGS="--all": full triage written
	$(PY) -m src.cli run --mode live $(RUN_FLAGS) $(ARGS)

replay-cache: ## fill replay/llm (committed) with the cached Apertus answers one full run reads; no gateway call
	$(PY) -m src.cli replay-cache

serve: ## serve the API and the UI on 127.0.0.1:8000 (builds src/web/dist with npm first when missing)
	$(PY) -m src.cli serve

smoke-llm: ## gateway probe -> results/gateway_probe.json (ARGS="--long --sizes 8000,16000 --ramp 1,2,4")
	$(PY) -m src.cli smoke-llm $(ARGS)

warmup: ## warm the 70B before a demo or a measurement
	$(PY) -m src.cli warmup $(ARGS)

crawl: ## Neuheiten lists and ruling pages, politely (>= 2 s between requests, cache)
	$(PY) -m src.cli crawl $(ARGS)

triage: ## relevance pipeline v1 -> results/triage_pipeline.json (MODE=replay|live; WRITE=1 stores predictions; ARGS="--limit N" is a smoke run that writes nothing)
	$(PY) -m src.triage.pipeline --mode $(MODE) $(if $(filter 1,$(WRITE)),--write,) $(ARGS)

refit: ## rerun the scoring with the current labels, expert corrections included
	$(PY) -m src.cli refit $(ARGS)

eval: ## evaluation suites on public data -> results/*.json
	$(PY) -m src.cli eval $(ARGS)

eval-private: ## measurements on Suva's data; aggregate numbers only (D-031)
	$(PY) -m src.cli eval-private $(ARGS)

claims: ## regenerate every number quoted in README.md, technical_report.md and the deck
	$(PY) -m src.cli claims $(ARGS)

check: ## lint, unit tests, doctrine, models-registry, template-layout and D-051 tests
	uv run --frozen ruff check src tests
	uv run --frozen ruff format --check src tests
	uv run --frozen pytest

db-up: ## start the local Postgres (compose service db) and wait until it is healthy
	docker compose up -d --wait db
