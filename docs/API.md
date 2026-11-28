# API: the HTTP interface for the legal-expert UI and the judges

> **Status: PROPOSED (D-092, D-093), Sat 28 Nov 2026.** Code: `src/api/`. Tests: `tests/test_api_unit.py`, `tests/test_api_db.py` (`-m db`). Data behind every field: `docs/DATA_CATALOG.md`. The routes follow the frontend's brief of 28 Nov.

## 1. Run it

| Command | What it does |
|---|---|
| `make serve` | uvicorn on `API_HOST:API_PORT` (default `127.0.0.1:8000`); OpenAPI page at `/docs` |
| `make run` | the pipeline, then `make serve` (`SERVE=0` skips serving) |
| `docker compose --profile ui up -d app` | the cluster's `app` service (login `suva_api`, `SUVA_API_PASSWORD` set in `.env`) |

Needs `DATABASE_URL` (a database built by `make db-deploy` and loaded). Settings, all optional (`.env.example`):

| Variable | Default | Effect |
|---|---|---|
| `API_HOST`, `API_PORT` | `127.0.0.1`, `8000` | where uvicorn listens (`0.0.0.0` inside the container) |
| `API_ACTOR` | `expert` | `app.actor` of every session: one shared expert during the event, never a person's name (G13) |
| `API_DB_ROLE` | `suva_api` | `SET ROLE` of every session: the API login's rights (read, and the three write functions), even on an owner URL |
| `API_STATEMENT_TIMEOUT_MS` | `15000` | the `suva_api` login's own timeout |
| `MODE` | `replay` | default mode of a run launched from the API |
| `API_RUNS_ENABLED` | off | `1` lets `POST /api/runs` launch layer 1 then layer 2 |
| `PIPELINE_DATABASE_URL` | `DATABASE_URL` | the pipeline login those runs use (never the API's own) |
| `API_LAYER2_STORE`, `API_LAYER2_POPULATIONS` | none | `--store`, `--population` of the launched layer 2 |
| `API_AI_RELEVANT_MIN_SCORE` | unset | a threshold on `score_0_100` that makes `ai_relevant`; unset while D-021 is open |

## 2. Conventions

- **Ids** are UUID strings (`ruling_id`, `request_id`, `summary_version_id`). A docket is not an id.
- **Errors** answer JSON `{"detail": "..."}`: 404 unknown id, 409 refused by the current state (the database's own message), 422 bad input (checked before any database access), 403 runs not enabled, 503 database not configured or unreachable, 504 statement timeout.
- **Pages**: `limit` 1 to 200 (default 50), `offset`. Every order ends on the ruling's UUID, so pages are stable.
- **Labels**: the API returns codes (statuses, reason codes, enums) and the database's German and French labels where they exist; `explanation_de` exists only in German.
- **Mode**: `mode` (`LIVE` | `REPLAY`) on every row and every layer-2 reading.
- **Dates**: `publication_date` (exact), `publication_date_approx` (first seen in HF), `publication_quality` (`exact` | `approx_first_seen` | `unknown`); date filters use the exact date, else the approximate one.
- **Text offsets** (`char_start`, `char_end` in the "why" card) are zero-based, end-exclusive positions in Unicode code points of the text named by `text_id`. JavaScript strings count UTF-16 units: convert before slicing.
- **Writes** go only through `gold.submit_review`, `summ.create_expert_version` and `ops.submit_request`, each with `app.actor` set.

## 3. Status of a ruling (derived in one place, `src/api/queries.py`)

The first matching line wins. The label itself is `triage.v_scope_pipeline`'s (behind `v_scope_current`), never recomputed.

| `status` | When |
|---|---|
| `expert_relevant` | the latest expert decision says relevant (`v_scope_current.expert_implied_label = 'in_scope'`), even after a later model run (`expert.stale` = true then) |
| `expert_not_relevant` | the latest expert decision says not relevant |
| `ai_relevant` | a ranking step wrote `in_scope`; or `API_AI_RELEVANT_MIN_SCORE` is set and a layer-2 score reaches it. **No ruling today**: the ranking step is not built (D-021) |
| `potentially_relevant` | the label is `potentially` (layer 1 kept it; layer 2 scores it, or its judgement is missing in a partial run) |
| `ai_not_relevant` | a ranking step wrote `out_of_scope` for a ruling layer 1 kept. No ruling today |
| `filtered_out` | layer 1 dropped it (whatever a later step republishes) |
| `not_assessed` | no row in `v_scope_pipeline` |

`area` = the court's matter name (Neuheiten rubric, else HF legal area, else the start of the subject line, cut at the first bracket, comma or semicolon) as `UV`, `MV`, `IV`, `KV`, `BV`, `CONTRACT`, `LIABILITY` or `other`; `core=true` = UV, MV, IV. `is_new` = created by the latest usable ingest when it is an incremental one (the first ingest loads the base: no ruling is new until a later ingest exists).

## 4. Endpoints

| Method and path | Body or query | Returns |
|---|---|---|
| `GET /api/health` | | `{ok, mode, runs_enabled, database, running_runs, job}`; 503 when the database is unusable |
| `GET /api/rulings` | `q`, `decided_from`, `decided_to`, `published_from`, `published_to`, `court`*, `area`*, `core`, `language`*, `status`*, `score_min`, `score_max`, `has_summary`, `inbox`, `sort` (`score` \| `decision_date` \| `publication_date` \| `docket` \| `status`), `order`, `limit`, `offset` (* repeatable) | `{total, items: [RulingRow]}` |
| `GET /api/facets` | the same filters | `{total, decided_min, decided_max, published_min, published_max, courts, areas, languages, statuses}`, each list `[{value, n}]` counted under every filter but its own |
| `GET /api/rulings/{id}` | | `{ruling: RulingRow, text, text_id, text_source, relevance, summaries: {de, fr}, summary_request, reference}` |
| `POST /api/rulings/{id}/relevance` | `{action: mark_relevant \| mark_not_relevant \| reopen, comment?, token?}` | the new `RulingRow`; 409 when not assessed, nothing to reopen, or `token` is stale |
| `POST /api/rulings/{id}/summaries` | | 202, the request `{request_id, kind, status, ...}` (stays `pending`: no request runner yet) |
| `PUT /api/rulings/{id}/summaries/{de\|fr}` | `{body, title_line?, parent_version_id?}` | the summaries; 409 while the ruling has no summary or `parent_version_id` is stale |
| `POST /api/rulings/{id}/summaries/{lang}/validate` | `{comment?}` | the summaries (one review covers the DE + FR version) |
| `POST /api/rulings/{id}/summaries/{lang}/unvalidate` | | the summaries; 409 when not validated |
| `GET /api/rulings/{id}/summaries/{lang}/versions` | | `[{summary_version_id, version, origin, created_at, creator, quality_status, is_current, mode, validated}]` |
| `POST /api/requests` | `{docket?, bger_url?}` | 202, the "add another judgement" request (D-015), `pending` |
| `GET /api/requests/{id}` | | `{request_id, kind, status (pending \| accepted \| done \| failed \| rejected), status_detail, ...}` |
| `GET /api/learning` | | `{decisions, transitions: [{before, after, n}], summaries_generated, summaries_edited, summaries_validated, edits_per_language}` |
| `GET /api/scoring` | | the default profile's steps, layer 1's rules (DE/FR labels), layer 2's judge; `rules: []` |
| `GET /api/runs` | | `{enabled, running, current, last, recent}`: the job the API started and the latest `ops.pipeline_run` rows (with `replay_misses`) |
| `POST /api/runs` | `{mode?, limit?, all?, population?}` | 202 and the job; 403 unless `API_RUNS_ENABLED=1`, 409 while a job runs, 422 for a live run without `limit` or `all` |

**RulingRow**: `id, docket, decision_date, publication_date, publication_date_approx, publication_quality, quarter_by_decision, quarter_by_publication, court, language, area, subject, bger_url, status, pipeline_label, step, score (0-100), score_raw (the logit: orders ties), score_source, reason_code, reason_label_de, reason_label_fr, explanation_de, outcome, mode, is_new, has_summary, summary_validated, decision_token, expert {verdict, label, at, stale}`.

**relevance** (the "why" card): `state` (`scored` \| `assessed` \| `not_assessed`), `label`, `step`, `score`, `score_raw`, `reason_code` and its labels, `explanation_de`, `mode`, `run {run_id, kind, status, mode, started_at, finished_at, profile, component}`, `trace` (one hop per step of the label's lineage), `text_id`, `layer1` (the fired rules: `rule, label_de, label_fr, effect, outcome, decisive, field, examined_value, matched_text, char_start, char_end, detail`), `layer2` (`model, requested_model, prompt_version, p_yes, logprob_yes, logprob_no, yes_no_in_top, top_logprobs, text_chars_total, text_chars_sent, truncation, input_tokens, llm_call_id, outcome`), `rules: []`.

**Summary** (per language, `null` until layer 3 writes `summ.*`): `summary_version_id, summary_id, preset, version, origin, quality_status, mode, validated, validated_at, title_line, body, sentences [{claim_id, ordinal, paragraph, section, text, status, sources: []}]`.

## 5. Smoke test with curl

```bash
curl -s localhost:8000/api/health
curl -s 'localhost:8000/api/rulings?status=potentially_relevant&core=true&limit=5'
curl -s 'localhost:8000/api/facets?language=fr'
curl -s -X POST localhost:8000/api/requests -H 'Content-Type: application/json' -d '{"docket": "8C_691/2024"}'
```

## 6. Not in this increment

| Missing | Needs |
|---|---|
| `ai_relevant` / `ai_not_relevant` rulings | a ranking step with a measured cut (D-021) |
| summaries, their sources, per-language validation | the v3 → `summ.*` writer, `summ.claim_source` (provenance option B), a language on summary reviews |
| expert decision on a not-assessed ruling | a ruling-level review target (D-093, open part) |
| refresh (`/api/updates`), inbox content | incremental ingest with `created_by_run_id`, a refresh run that links its child runs |
| processing of requests | a request runner (`ops.user_request`: pending → accepted → done or failed) |
| UI served by the API, CORS for a separate dev server | the UI owner's choice (open) |
| folders and exports, revision by reason, Suva's reference summaries | their tables and a `gold.suva_summary` loader |
