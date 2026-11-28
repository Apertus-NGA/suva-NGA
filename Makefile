# Our single entry point (`make run` is our convention, D-042). Targets: AGENTS.md §6.
# Skeleton: stages not built yet print STUB and what they will do (docs/STATE.md lists them).

PY ?= $(if $(shell command -v uv 2>/dev/null),uv run --frozen python,python3)
MODE ?= replay
SERVE ?= 1
ARGS ?=
# DB target: DATABASE_URL when set (CI), else psql inside the compose service db (docs/DB_DDL_PLANNING.md §15)
DB_TARGET ?= $(if $(DATABASE_URL),,--compose)

.PHONY: help run run-live serve summaries replay-cache triage pipeline pipeline-live api web-api sources-neuheiten bridge smoke-llm warmup crawl refit eval eval-private claims check db-up db-deploy db-reset db-test db-registry ingest-base ingest-gold layer1 layer1-recall layer1-golden layer1-verify layer1-validate

help: ## list the targets
	@grep -E '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/'

SUMMARY_LIMIT ?=
RUN_FLAGS = $(if $(SUMMARY_LIMIT),--summary-limit $(SUMMARY_LIMIT),) $(if $(filter 0,$(SERVE)),--no-serve,)

# --- Suva Scout (the product the judges run): its own tables (db/migrations) on the local database scout-db.
run: ## end to end, REPLAY (no gateway call, answers in replay/llm): db up + migrate, ingest if empty, triage, v3 summaries, serve the UI on 127.0.0.1:8000; SERVE=0 stops before serving; SUMMARY_LIMIT=N caps the summaries
	$(PY) -m src.scout_cli run --mode $(MODE) $(RUN_FLAGS) $(ARGS)

run-live: ## the same with real Apertus calls (needs LLM_*); ARGS="--limit N": smoke; ARGS="--all": full triage written
	$(PY) -m src.scout_cli run --mode live $(RUN_FLAGS) $(ARGS)

serve: ## serve Suva Scout (API and UI) on 127.0.0.1:8000
	$(PY) -m src.scout_cli serve

summaries: ## batch v3 summaries (DE + FR), resumable (MODE=replay|live; ARGS="--workers 8 --limit N --dry-run")
	$(PY) -m src.summarize.batch --mode $(MODE) $(ARGS)

replay-cache: ## fill replay/llm (committed) with the cached Apertus answers one full run reads; no gateway call
	$(PY) -m src.scout_cli replay-cache

triage: ## relevance pipeline -> results/triage_pipeline.json (MODE=replay|live; WRITE=1 stores predictions)
	$(PY) -m src.triage.pipeline --mode $(MODE) $(if $(filter 1,$(WRITE)),--write,) $(ARGS)

# --- The six-schema data layer (src/db/sql), its pipeline (layer 1, layer 2) and its HTTP API (docs/API.md).
pipeline: ## the six-schema pipeline from the loaded base (MODE=replay|live, SERVE=0 to skip serving its API)
	$(PY) -m src.cli run --mode $(MODE) $(ARGS)
	@if [ "$(SERVE)" != "0" ]; then $(MAKE) --no-print-directory api; fi

pipeline-live: ## the same with real calls; needs LLM_* and ARGS="--limit N" or ARGS="--all"
	$(PY) -m src.cli run --mode live $(ARGS)

api: ## serve the six-schema HTTP API (src/api, docs/API.md) and, when built (make web-api), the UI at / (D-101)
	API_UI_DIST=$(or $(API_UI_DIST),src/web/dist-api) $(PY) -m src.cli serve $(ARGS)

sources-neuheiten: ## load the committed bger.ch Neuheiten pages (replay/bger_neuheiten) as publication and subject observations (D-106); changes layer 1's rubric input: not in make pipeline until a layer-1 version is certified on it
	$(PY) -m src.ingest.neuheiten --database-url $(DATABASE_URL)

web-api: ## build the UI for src/api into src/web/dist-api (VITE_BACKEND=api, D-101); make run keeps the Scout build
	cd src/web && npm ci && VITE_BACKEND=api npx vite build --outDir dist-api

bridge: ## copy Suva Scout's stored scores into the six-schema database as layer 2 and ranking on the profile scout (D-094, D-099): make bridge FROM=<Scout database URL>
	$(PY) -m src.layer1 run --profile scout
	$(PY) -m src.scorer export --from-url $(or $(FROM),postgresql://suva@localhost:54329/suva)
	$(PY) -m src.scorer load --profile scout

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

.PHONY: scorer-export scorer-load
scorer-export: ## write a stored Suva Scout scorer run to data/derived/scorer/run.json: make scorer-export FROM=postgresql://...
	$(PY) -m src.scorer export --from-url $(FROM)

scorer-load: ## load that run as layer 2 (the scorer) and ranking (its promotion) on the profile scout (D-094, D-099; needs make layer1 PROFILE=scout first)
	$(PY) -m src.scorer load --profile $(or $(PROFILE),scout) $(if $(FILE),--file $(FILE))

.PHONY: layer2 layer2-validate
layer2: ## layer 2 on layer 1's candidates (MODE=replay|live; ARGS="--limit N|--all --population CODE --store DIR")
	$(PY) -m src.layer2 run --mode $(MODE) --profile $(or $(PROFILE),default) $(ARGS)

# Like layer1-validate, the report goes to data/runs/validation/ (git-ignored; writable in the cluster) unless OUT
# names a file: OUT=results/layer2_validation.json regenerates the committed report, from a clean checkout.
layer2-validate: ## certify the pinned layer2_judge version against the D-074 benchmark (needs data/derived/finetune) [OUT=path]
	$(PY) -m src.layer2 validate --data-root data/derived/finetune/suva-ft-v3 --manifest experiments/finetune/manifests/suva-ft-v3/MANIFEST_suva_ft_v3.json --bench data/derived/finetune/bench_v3/8b_all --out $(or $(OUT),data/runs/validation/layer2_validation.json) $(ARGS)

layer1-golden: ## certified layer-1 and ingest decisions, in memory, no DB: make layer1-golden PARQUET=path [WRITE=1]
	$(PY) -m src.layer1 golden --parquet $(PARQUET) $(if $(WRITE),--write)

layer1-verify: ## a layer-1 run's files equal its DB rows, read-only: make layer1-verify RUN=<run_id>
	$(PY) -m src.layer1 verify --run $(RUN)

# The report goes to data/runs/validation/ (git-ignored on a workstation, writable in the cluster) unless OUT names a
# file: a default run never overwrites a committed results file.
L1V_BASE = $(or $(BASE),layer1_reference)
L1V_PROFILE = $(or $(PROFILE),default)
layer1-validate: ## run two profiles, recall, compare; fails on a removal: make layer1-validate BASE=... PROFILE=... [OUT=path]
	$(PY) -m src.layer1 validate --baseline-profile $(L1V_BASE) --profile $(L1V_PROFILE) --out $(or $(OUT),data/runs/validation/layer1_validation_$(L1V_BASE)_$(L1V_PROFILE).json)

# --- Cluster (docs/DEPLOY.md). The compose jobs call the first four targets inside the app image; the cluster-*
# targets wrap docker compose on the host. Never `docker compose down -v` (G12): volumes hold the database.
.PHONY: db-logins db-schema-guard db-structure ingest-closure fetch-base bootstrap load validate cluster-env cluster-config cluster-build cluster-up cluster-down cluster-ps cluster-logs cluster-backup cluster-validate
CLUSTER_PROFILES = --profile sovereign --profile ui --profile ops
CLUSTER_BUILD_ENV = GIT_COMMIT=$$(git rev-parse HEAD 2>/dev/null) GIT_DIRTY=$$(test -z "$$(git status --porcelain 2>/dev/null)" && echo 0 || echo 1)

db-logins: ## set the passwords of the login roles from SUVA_*_PASSWORD (owner, after db-deploy)
	$(PY) -m src.db.logins

db-schema-guard: ## the database's structure against expected/db/structure.json (CMD=check|show, owner)
	$(PY) -m src.db.schema_guard $(or $(CMD),show)

db-structure: ## compare the database's structure with expected/db/structure.json; WRITE=1 rewrites it (after a fresh deploy)
	$(PY) -m src.db.structure $(if $(WRITE),--write)

ingest-closure: ## every source row loaded or excluded with its reason; exit 1 if a snapshot does not close (F-04)
	$(PY) -m src.ingest closure

fetch-base: ## download the pinned HF base file into HF_BASE_DIR (default data/hf), checked by SHA-256
	$(PY) -m src.ingest.fetch --dest $(or $(HF_BASE_DIR),data/hf)

bootstrap: ## the cluster's migrate job: schema guard, schema in one transaction, login passwords (owner)
	@$(MAKE) --no-print-directory db-schema-guard CMD=check
	@$(MAKE) --no-print-directory db-deploy
	@$(MAKE) --no-print-directory db-logins

load: ## the cluster's load job: registry, base dataset (PARQUET=...), Suva's labels, closure (pipeline login)
	@$(MAKE) --no-print-directory db-registry
	@$(MAKE) --no-print-directory ingest-base PARQUET=$(PARQUET)
	@$(MAKE) --no-print-directory ingest-gold
	@$(MAKE) --no-print-directory ingest-closure

# The layer-2 branch replays the certified set (the labelled quarters) from the benchmark's answers in a run of kind
# eval, then certifies it: the gate never depends on an earlier layer-2 run, and like layer1-validate's runs (kind
# eval too) it never changes the delivered label. It needs a succeeded layer-1 run (make run S2, or make layer1).
L2_CERT_STORE ?= data/derived/layer2/replay_store
validate: ## the cluster's release gate: layer 1 on two profiles, recall, compare; layer-2 certification when its data is there
	@$(MAKE) --no-print-directory layer1-validate OUT=
	@if [ -d data/derived/finetune/suva-ft-v3 ]; then \
		if [ ! -d $(L2_CERT_STORE)/cache ]; then \
			echo "validate: no benchmark replay store in $(L2_CERT_STORE) (docs/LAYER2.md §3: hard links to data/derived/finetune/bench_v3/llm_store/cache)" >&2; exit 1; \
		fi; \
		$(MAKE) --no-print-directory layer2 MODE=replay PROFILE= ARGS="--kind eval --store $(L2_CERT_STORE) --population 2025Q4_decision --population 2026Q1_decision" \
		&& $(MAKE) --no-print-directory layer2-validate OUT= ARGS=; \
	else \
		echo "SKIPPED layer2-validate: no data/derived/finetune/suva-ft-v3 (Suva-derived, D-031; mount it with SUVA_DERIVED_SOURCE)"; \
	fi

cluster-env: ## generate the cluster's missing secrets into .env (never overwrites, never prints; mode 600)
	python3 -m src.db.logins --init-env .env

cluster-config: ## validate docker-compose.yml with the current .env, every profile
	docker compose $(CLUSTER_PROFILES) config --quiet

cluster-build: ## build the app image, labelled with the current commit
	$(CLUSTER_BUILD_ENV) docker compose build

cluster-up: ## build, then run the pipeline job; db, migrate, fetch and load run first (docs/DEPLOY.md §3)
	$(CLUSTER_BUILD_ENV) docker compose build
	docker compose run --rm pipeline

cluster-down: ## stop the cluster; volumes (database, runs, results) are kept
	docker compose $(CLUSTER_PROFILES) down

cluster-ps: ## state of every service, one-shot jobs included
	docker compose ps --all

cluster-logs: ## follow the logs of every service
	docker compose logs --follow --tail 100

cluster-backup: ## pg_dump of the database into the backups volume (profile ops)
	docker compose --profile ops run --rm backup

cluster-validate: ## release gate in the cluster: make validate as the pipeline login (profile ops)
	docker compose --profile ops run --rm validate
