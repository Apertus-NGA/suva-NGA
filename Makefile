# Our single entry point (`make run` is our convention, D-042). Targets: AGENTS.md §6.
# Skeleton: stages not built yet print STUB and what they will do (docs/STATE.md lists them).

PY ?= $(if $(shell command -v uv 2>/dev/null),uv run --frozen python,python3)
MODE ?= replay
SERVE ?= 1
ARGS ?=

WRITE ?= 0

.PHONY: help run run-live serve smoke-llm warmup crawl triage refit eval eval-private claims check db-up

help: ## list the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/'

run: ## end-to-end run from the committed snapshot (MODE=replay|live, SERVE=0 to skip serving)
	$(PY) -m src.cli run --mode $(MODE) $(ARGS)
	@if [ "$(SERVE)" != "0" ]; then $(MAKE) --no-print-directory serve; fi

run-live: ## the same pipeline with real calls; needs LLM_* and ARGS="--limit N" or ARGS="--all"
	$(PY) -m src.cli run --mode live $(ARGS)

serve: ## serve the API and the UI only
	$(PY) -m src.cli serve $(ARGS)

smoke-llm: ## gateway probe -> results/gateway_probe.json (ARGS="--long --sizes 8000,16000 --ramp 1,2,4")
	$(PY) -m src.cli smoke-llm $(ARGS)

warmup: ## warm the 70B before a demo or a measurement
	$(PY) -m src.cli warmup $(ARGS)

crawl: ## Neuheiten lists and ruling pages, politely (>= 2 s between requests, cache)
	$(PY) -m src.cli crawl $(ARGS)

triage: ## relevance pipeline v1 -> results/triage_pipeline.json (MODE=replay|live; WRITE=1 stores predictions for the UI)
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
