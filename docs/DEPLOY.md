# DEPLOY: the cluster (docker compose)

> **Status: PROPOSED (D-090), Sat 28 Nov 2026.** Owner: platform (the lead, while D-024 is open). Files: `docker-compose.yml`, `Dockerfile`, `.dockerignore`, the `cluster-*` targets of the `Makefile`, `src/db/logins.py`, `src/ingest/fetch.py`, `tests/test_cluster.py`, the CI job `cluster`.
> What the cluster runs today: the data layer, the loaders, layer 1 and its recall check (`make run` stage S2). Layer 2 (S3) and the next stages run inside it as soon as `make run` calls them: the cluster calls make targets, so a new stage needs no change here. The API and UI service is ready but off (profile `ui`): `make serve` is a stub until the FastAPI app lands, after layer 3 (summaries).

## 1. What runs where

```
                      ┌───────────────── network backend (internal: no route out) ─────────────────┐
  .env ──secrets──▶   │  db (PostgreSQL 17 + pgvector)  ◀── migrate (owner: schema, logins)          │
                      │        ▲    ▲    ▲                                                           │
                      │        │    │    └── backup (profile ops, owner: pg_dump)                    │
                      │        │    └─────── load (suva_pipeline: registry, base dataset, labels)    │
                      │        └──────────── pipeline (suva_pipeline: make run SERVE=0)  ──┐         │
                      │  llm (profile sovereign: Apertus on vLLM, GPU, offline) ◀──────────┤         │
                      │  app (profile ui, suva_api: make serve, after layer 3)             │         │
                      └────────────────────────────────────────────────────────────────────┼─────────┘
                        network egress: fetch (Hugging Face, once), pipeline and app ──────┘──▶ LLM_BASE_URL
```

| Service | Kind | Login | Network | Does |
|---|---|---|---|---|
| `db` | long-running | `suva` (owner) | backend | PostgreSQL 17 with pgvector, image pinned by digest; scram-sha-256; no published port |
| `migrate` | one-shot | `suva` | backend | `make bootstrap`: `src/db/sql` (idempotent), then the passwords of the three logins |
| `fetch` | one-shot | none | egress | `make fetch-base`: the pinned HF file, checked by SHA-256; does nothing when the file is already there |
| `load` | one-shot | `suva_pipeline` | backend | `make load`: versions and rules, base dataset (6,055 rulings), Suva's labels (D-051 fields never read) |
| `pipeline` | one-shot | `suva_pipeline` | backend, egress | `make run SERVE=0`, `MODE=replay` by default, `MODE=live` with the three `LLM_*` variables |
| `llm` | profile `sovereign` | n/a | backend | Apertus served by vLLM inside the cluster (§6) |
| `app` | profile `ui` | `suva_api` | backend, egress | `make serve` on port 8000, bound to localhost; health check `/api/health` |
| `backup` | profile `ops` | `suva` | backend | custom-format `pg_dump` into the `backups` volume |

Order: `db` healthy → `migrate` → (`fetch`) → `load` → `pipeline`; each waits for the previous one to succeed. Every job runs twice with the same result (the loaders and the schema are idempotent; each pipeline run is a new run row).

Volumes: `pgdata` (database), `suva_data` (`/app/data`: `data/runs/<run_id>/` files, caches, `data/derived/`), `suva_results` (`/app/results`), `hf_base` (the base dataset), `apertus_weights`, `backups`. A volume can be replaced by a host directory through its `*_SOURCE` or `BACKUP_TARGET` variable.

## 2. How the cluster answers the judging criteria

| Criterion (source) | What it asks | How the cluster meets it |
|---|---|---|
| Template `README.md` (D-039) | "run end-to-end when judges try to run it" | `make cluster-env && make cluster-up` on a fresh clone: secrets generated, schema, base dataset, labels, `make run` (§3). Docker on `linux/amd64`, no GPU, minutes (Q-23 default) |
| `challenge_description.md` §3, rule E5 | deployable on-premise, air-gapped or on a sovereign Swiss cloud | one set of containers for the three targets; air-gapped: images and files carried in, local Apertus (§5, §6) |
| Rules E1, E3 | Apertus does the core task; at runtime only Apertus and open-weights models | the only model endpoint is `LLM_BASE_URL`: the Keera or CSCS gateway, or the in-cluster vLLM; no other AI service |
| Event jury: sovereign deployability | "no external service at runtime scores highest" | with the `sovereign` profile, nothing leaves the host: the database and the model sit on an internal network |
| `challenge_description.md` §4, ranking 2 (top 30, "you didn't miss anything relevant") | recall first | layer 1 runs with its blocking recall check: the job fails if one of Suva's labelled rulings is dropped (82/82 kept) |
| `challenge_description.md` §4, ranking 1 (top 10 summaries) | summaries graded by Suva's experts | not in the cluster yet: layer 3 lands as a `make run` stage, then the `app` service shows it |
| `challenge_description.md` §4, bonus | "Project/Code is easy to transfer to Azure" | §8: configuration by environment only, one OCI image, standard PostgreSQL; a mapping to Azure services |
| `challenge_description.md` §1 | "a central, searchable and query-enabled knowledge base" | PostgreSQL holds every ruling, decision, reason and run (D-061); `suva_report` gives read-only access |

## 3. Run it

```
make cluster-env
make cluster-up
make cluster-ps
make cluster-down
```

1. `make cluster-env` writes the four cluster secrets into `.env` when they are missing (random, 32 bytes each; never overwrites, never prints; file mode 600). Add the three `LLM_*` variables to `.env` for `MODE=live`.
2. `make cluster-up` builds the app image (labelled with the current commit) and runs the `pipeline` job; `db`, `migrate`, `fetch` and `load` run first. The first run downloads the base dataset (925 MB) once.
3. `make cluster-ps` shows every service, one-shot jobs included; `make cluster-logs` follows the logs.
4. `make cluster-down` stops the cluster and keeps every volume. Removing the volumes deletes the database: a human does it, never an agent (G12).

Measured Sat 28 Nov on a laptop (arm64, the `linux/amd64` image emulated, other work running), base dataset already in place: the first run of the whole chain took 60 s (load 10 s, layer 1 38 s: 935 of 6,055 kept, recall 82/82, as `suva_pipeline`). A second run on the same volumes gave the same result in 460 s (fetch 2 s, migrate 1 s, load 10 s, layer 1 135 s); the rest of that time is not explained yet. Measure on the target host before quoting a duration.

Other commands: `make cluster-config` (checks the compose file with the current `.env`, every profile), `make cluster-build`, `make cluster-backup`, `docker compose --profile ui up -d app` once `make serve` exists.

## 4. Security

- **Secrets** come from `.env` (git-ignored, never in the image: `.dockerignore`) or from the platform's secret store. `docker-compose.yml` holds no value: a missing secret stops compose with a message naming it. `tests/test_cluster.py` fails on a literal password, key or endpoint, on `trust` authentication, and on an image without a digest.
- **Logins** (src/db/sql/90_roles.sql): the owner `suva` deploys and backs up; the jobs use `suva_pipeline` (group `suva_g_pipeline`: reads, inserts facts, no DDL); the app will use `suva_api`; `suva_report` is read-only. Passwords are set by `migrate` (`src/db/logins.py`, at least 16 characters, never logged). `python -m src.db.logins --verify suva_pipeline` proves that the login connects and cannot create a table in any schema; CI runs it.
- **Network:** `backend` is internal, so the database and the local model have no route out and publish no port. Only `fetch`, `pipeline` and `app` reach `egress`. The app binds to `127.0.0.1` by default (`APP_BIND`, `APP_PORT`): expose it through a TLS reverse proxy, never directly.
- **Containers:** non-root user (uid 10001), read-only root file system, `/tmp` in memory, every capability dropped, `no-new-privileges`, an init process, memory and process limits, logs rotated (5 × 10 MB per container). The image holds no `.git`, no `data/`, no `tmp/`, no docs.
- **Traceability:** every run records the commit the image was built from (`SUVA_GIT_COMMIT`, a build argument set by `make cluster-build`) and whether the tree was clean. A run in the cluster on 28 Nov recorded `e1bc7c2`.

## 5. Data and the air-gapped path

- **Base dataset:** `voilaj/swiss-caselaw`, `data/bger.parquet` at commit `35b17aa9…`, SHA-256 `d2b2df1d…` (`src/ingest/fetch.py`, the same commit as `src/ingest/registry/ingest.json`; a test keeps them equal). `fetch` downloads it once into `hf_base`; a file that is present with the right SHA-256 is kept and nothing is downloaded; a file with another SHA-256 stops the job.
- **Air-gapped install:** on a connected machine, `docker compose build` then `docker save` the app image and pull and save the PostgreSQL image (and vLLM for §6); download `bger.parquet` and the Apertus weights. Carry them in. On the target: `docker load`, put the parquet file in a directory and set `HF_BASE_SOURCE` to it, set `APERTUS_WEIGHTS_SOURCE`, then `make cluster-env && make cluster-up`. `fetch` finds the file, checks it and makes no network call.
- **Suva's labels** come from `judgements/` inside the image (public, unchanged, D-040); only columns A and B and the export links are read (D-051).
- **Updates of the rulings:** a new pinned HF commit is a new `ingest` version (D-064), then a new `fetch` pin; a scheduled crawl of bger.ch (`make crawl`) is not built yet.

## 6. Sovereign inference (profile `sovereign`)

```
docker compose --profile sovereign up -d llm
```

- vLLM `v0.33.0` (pinned by digest) serves the weights in `APERTUS_WEIGHTS_SOURCE` (folder `APERTUS_MODEL_DIR`, default `Apertus-v1.5-8B`) under the name `APERTUS_SERVED_NAME` (default `apertus-v1-5-8b`, on the allow-list of `MODELS.md` §1). Offline: `HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`, no usage statistics. It refuses any key but `LLM_API_KEY`.
- Point the jobs at it in `.env`: `LLM_BASE_URL=http://llm:8000/v1`, `LLM_NAME=apertus-v1-5-8b`, `LLM_API_KEY=<the same key>`, `MODE=live`. The pipeline waits for `llm` to be healthy when the profile is on. The 70B needs several GPUs: `VLLM_TENSOR_PARALLEL`.
- `--max-logprobs 20`: layer 2 reads the top 20 log-probabilities of the first token (D-074).
- **Not tested here:** it needs an NVIDIA GPU host. The compose file is validated with this profile in CI; whether vLLM `v0.33.0` loads Apertus v1.5 is to check on the GPU host before relying on it.

## 7. Operations

- **Upgrade:** pull or rebuild the image, `make cluster-up`. `migrate` re-applies `src/db/sql` (idempotent, no `ALTER`, D-061); a schema change that needs a fresh deploy goes through `make db-reset`, which refuses to drop rows written by experts.
- **Backup:** `make cluster-backup` writes `suva-<UTC time>.dump` into `backups` (or `BACKUP_TARGET`). Restore into an empty database with `pg_restore --clean --if-exists -d suva <file>` run in the `db` container.
- **Resources:** `db` 2 CPUs and 2 GB, `load` 6 GB, `pipeline` 4 GB, `migrate` and `fetch` 1 GB, `app` 2 GB; change them in `docker-compose.yml` for a larger host.
- **Logs:** stdout of every container, rotated; PostgreSQL logs connections and statements slower than 5 s. The pipeline's own spans, events and metrics are in the database (`ops.*`, D-065).

## 8. Transfer to Azure (the template's bonus; D-049, Q-19 open)

Nothing in the code is Azure-specific; the move is configuration. Service names and pgvector support are to verify on the day of the move (`docs/ARCHITECTURE.md` §7). Azure is not presented as option c): a US provider's Swiss region is not obviously "under Swiss jurisdiction" (Q-19).

| Cluster piece | Azure |
|---|---|
| app image (`Dockerfile`) | Azure Container Registry |
| `migrate`, `fetch`, `load`, `pipeline` (one-shot) | Azure Container Apps jobs, run in order, manual or scheduled trigger |
| `app` | Azure Container Apps with HTTPS ingress |
| `db` | Azure Database for PostgreSQL flexible server (PostgreSQL 17, extensions `vector`, `pg_trgm` allow-listed) |
| volumes `suva_data`, `suva_results`, `hf_base` | Azure Files shares |
| `.env` secrets | Key Vault secrets, passed as environment variables |
| `llm` / `LLM_BASE_URL` | any OpenAI-compatible Apertus endpoint: the CSCS or Keera gateway, or vLLM on a GPU VM |
| `backend` internal network | a virtual network with a private endpoint for PostgreSQL |
| logs | Log Analytics (container stdout) |

Region: Switzerland North, for data residency.

## 9. Limits

- The `app` service waits for `make serve` (FastAPI, after layer 3).
- Layer 2 and the next stages run in the cluster once `make run` calls them; nothing to change here.
- CI proves the compose file, the image, the schema and the least-privileged login; the full chain with the 925 MB file and the GPU profile are tested by hand.
- `make db-up` (the developer database) now needs `POSTGRES_PASSWORD` in `.env`: `make cluster-env` sets it. A database volume created before this change keeps its old authentication until it is recreated.
