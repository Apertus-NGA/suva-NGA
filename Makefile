# Our single entry point (`make run` is our convention, D-042). Targets: AGENTS.md §6.
# Skeleton: stages not built yet print STUB and what they will do (docs/STATE.md lists them).

PY ?= $(if $(shell command -v uv 2>/dev/null),uv run --frozen python,python3)
MODE ?= replay
SERVE ?= 1
ARGS ?=
# DB target: DATABASE_URL when set (CI), else psql inside the compose service db (docs/DB_DDL_PLANNING.md §15)
DB_TARGET ?= $(if $(DATABASE_URL),,--compose)

.PHONY: help run run-live serve smoke-llm warmup crawl refit eval eval-private claims check db-up db-deploy db-reset db-test db-registry ingest-base ingest-gold layer1 layer1-recall

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

db-deploy: ## apply src/db/sql/NN_*.sql in order (idempotent)
	$(PY) -m src.db.deploy deploy $(DB_TARGET)

db-reset: ## fresh deploy: drop the six schemas, re-apply src/db/sql (refuses if expert rows would be lost)
	$(PY) -m src.db.deploy reset --yes $(DB_TARGET)

db-test: ## SQL tests in tests/sql, each in a transaction rolled back
	$(PY) -m src.db.deploy test $(DB_TARGET)

db-registry: ## load step versions, rules and pipeline profiles into the DB (needs DATABASE_URL)
	$(PY) -m src.ingest registry

ingest-base: ## load the HF base dataset: make ingest-base PARQUET=path/to/bger.parquet (pinned commit, docs/LAYER1.md §6)
	$(PY) -m src.ingest base --parquet $(PARQUET)

ingest-gold: ## load Suva's labels from judgements/ (columns A-B and export links only, D-051)
	$(PY) -m src.ingest gold

layer1: ## run layer 1 on the default profile (PROFILE=..., POPULATION=...): files in data/runs/, then the DB
	$(PY) -m src.layer1 run --profile $(or $(PROFILE),default) $(if $(POPULATION),--population $(POPULATION))

layer1-recall: ## blocking recall of the latest layer-1 run on Suva's labels
	$(PY) -m src.layer1 recall --profile $(or $(PROFILE),default)

.PHONY: layer2 layer2-validate
layer2: ## layer 2 on layer 1's candidates (MODE=replay|live; ARGS="--limit N|--all --population CODE --store DIR")
	$(PY) -m src.layer2 run --mode $(MODE) --profile $(or $(PROFILE),default) $(ARGS)

layer2-validate: ## certify the pinned layer2_judge version against the D-074 benchmark (needs data/derived/finetune)
	$(PY) -m src.layer2 validate --data-root data/derived/finetune/suva-ft-v3 --manifest experiments/finetune/manifests/suva-ft-v3/MANIFEST_suva_ft_v3.json --bench data/derived/finetune/bench_v3/8b_all $(ARGS)
