# Frontend V1 consolidation: one API, one data layer

> **Status: 28 Nov 2026, consolidation phase, increment 0 (audit, profile fix, decisions, plan).** Branch `consolidate/frontend-v1`, based on `origin/main` `42a7b043` (which contains `34f8cc3f`, the frontend developer's merge of Suva Scout "side by side" with the six-schema data layer). Decisions: D-099, D-100, D-101 (`docs/DECISIONS.md`). Audience: the lead, the API owner, the DDL owner, the frontend developer, the summary owner.
> Every claim carries its evidence (`path:line` at `42a7b043`, or the command that measured it). Numbers measured by this audit say so; numbers from another member's build are labelled with their source (G11).

## 1. What this phase is for

The frontend V1 (`src/web`, React, "Suva Scout") shipped on 28 Nov with its own API (`src/suva_app`) over its own `public` schema (`db/migrations/001-005`) in its own database (`scout-db`, 127.0.0.1:54329). The repository's data layer is the six-schema PostgreSQL model (D-061 to D-071, D-091) behind `src/api` (D-092, D-093). The consolidation makes the product run on one data layer and one API, without breaking the path the judges run for the 14:30 submission (`make run`).

| Decision | What it settles |
|---|---|
| **D-099** | The default profile pins the 8B judge again (V0.5.0); the Suva Scout scorer and its ranking move unchanged to the profile `scout`. Restores the cluster's `pipeline` job and 18 database tests. Renumbers the three Scout rows that reused D-072 to D-074 as D-102 to D-104. |
| **D-100** | D-031 is settled on option (d): the replay cache, per-docket evaluation outputs and fixtures are committed; no sentence of Suva's own is; D-051 unchanged. |
| **D-101** | `src/web` is wired to `src/api` on the six schemas; `src/suva_app` and `public` stay only while a screen needs a missing route; the frontend developer's data enters the six schemas through loaders with provenance. |

## 2. The system as it runs at `42a7b043`

| Entry point | Runs | Writes | Serves | Evidence |
|---|---|---|---|---|
| `make run` (the judges' command, D-042) | `src.scout_cli run --mode replay`: scout-db up, `db/migrations` applied, ingest if `rulings` is empty (Hugging Face pull, then build), Scout triage from replayed answers, v3 summaries, UI build | `public.*` of scout-db only; files `results/triage_pipeline.json`, `data/quality_report.md`, `src/web/dist` | `src_app.main:app` (Suva Scout) with the UI at `/`, 127.0.0.1:8000 | `Makefile:20-21`; `src/scout_cli.py:95-279` |
| `make pipeline` | `src.cli run`: S2 layer 1 (`src/layer1`), S3 layer 2 (`src/layer2`) | the six schemas | `src/api` unless `SERVE=0` | `Makefile:39-41`; `src/cli.py:104-161` |
| cluster `pipeline` job | `make pipeline SERVE=0` as login `suva_pipeline` | the six schemas | none | `docker-compose.yml:140-142` |
| cluster `app` (profile `ui`) | `make api` (`src/api`), login `suva_api` | writes only through `gold.submit_review`, `summ.create_expert_version`, `ops.submit_request` | API only, **no UI** (no static mount in `src/api`) | `docker-compose.yml:242-263`; `src/api/app.py:162-300` |
| `make bridge FROM=<Scout DB URL>` | layer 1 on `scout`, export of the latest stored scorer run, load as `layer2_judge` V2.0.0 and `ranking` V1.0.0 | `triage.assessment`, `triage.assessment_reason`, `ops.pipeline_run` | none | `Makefile:49-52` (after D-099); `src/scorer/load.py:141-329` |

The two databases share no table: keys differ (bigserial in `public`, uuid5 in the six schemas) and so does granularity (`db/migrations/001_init.sql`; `src/db/sql/20_corpus.sql`). One server can hold both; the six-schema reset drops only its own schemas (`src/db/deploy.py:115`).

### 2.1 The break D-099 repairs

D-094 (PROPOSED by the scorer owner) registered the scorer as `layer2_judge` V2.0.0 and made the default profile V0.4.0 pin it (`src/db/seed/profiles.json`, `src/ingest/__main__.py:44-50`). The only executor of that step validates every pinned version as the 8B judge's config: `src/layer2/run.py:147` (`Layer2Config.model_validate`). `src/cli.py:118-125` catches `LookupError`, `Layer2RunFailed` and `ConfigError` only, so the pydantic `ValidationError` (13 fields) was uncaught: S3 of `make pipeline` stopped, and so did the cluster's `pipeline` job whenever `SUVA_DERIVED_SOURCE` supplied a replay cache. Without that cache, S3 printed SKIPPED before reaching the crash and the cluster ended green with no layer-2 score.

D-099: default V0.5.0 pins `layer2_judge` V1.0.0 again; profile `scout` V0.1.0 pins V2.0.0 and `ranking` V1.0.0. The registry is insert-only (`src/db/registry.py:296-298`) and the latest active version wins (`src/db/registry.py:334-344`), so a database that already loaded V0.4.0 moves to V0.5.0 at its next `make db-registry`. The scorer loader reads layer 1 of its own profile (`src/scorer/load.py:104-115`), so `make bridge` now runs `src.layer1 run --profile scout` first.

Trade-off, recorded in D-099: the label the API shows is the default profile's (D-063), now the 8B judge's, with no ranking step, so `ai_relevant` appears only when `API_AI_RELEVANT_MIN_SCORE` is set (D-092). Showing the scorer instead is one seed change (`is_default` on `scout`) once a scorer run is loaded, or a port of the scorer into the six schemas (§7, step 6).

## 3. Wiring `src/web` to `src/api` (D-101)

### 3.1 What the UI calls today

Every call is a relative `/api/...` to `src/suva_app` (`src/web/src/lib/api.ts:1,78-82,115-157,240,253-274`); Vite proxies `/api` to `$SUVA_API`, else `http://localhost:8000` (`src/web/vite.config.ts:5,8`). No UI test exists (`src/web/package.json:6-10`).

| UI screen / action | Call today (`suva_app`) | `src/api` equivalent | Six-schema source | Gap kind |
|---|---|---|---|---|
| Rulings list (inbox, rulings views) | `GET /api/rulings` with 20 filter params, `limit=50`, `offset` (`useRulings.ts:15`, `filters.ts:61-102`) | `GET /api/rulings` exists; `area`, `status`, `sort=area` values differ (422, `src/api/app.py:128,131,182`); `topic, division, outcome, label, starred, ingested, summarised, predicted_relevant` ignored | `corpus.v_ruling`, `triage.v_scope_current` (`src/api/queries.py:74-138`) | API + UI code |
| Facets | `GET /api/facets` (`useRulings.ts:31`) | exists; `courts` vs `divisions`; no `topics, outcomes, labels, scored, stub_scores` | same | API code |
| Expert relevance decision | `POST /api/rulings/{id}/relevance` `confirm_relevant \| mark_not_relevant \| reopen` (`App.tsx:154`, `RulingPage.tsx:72`) | exists with `mark_relevant` (422 on `confirm_relevant`, `src/api/app.py:90`); 409 on a ruling with no assessment (`src/api/writes.py:82-83`) | `gold.submit_review('scope', …)` (`src/api/writes.py:99-103`) | UI code; DDL for not-assessed rulings |
| Ruling page | `GET /api/rulings/{id}/workspace` (`RulingPage.tsx:48`) | `GET /api/rulings/{id}` and its relevance and summary reads; no `workspace` aggregate | `corpus.ruling_text`, `triage.assessment(_reason)`, `summ.v_summary_current` | API code |
| "Why" card | `relevance{state, reason, criterion, score, suspected, rules[], read_by_apertus, readings[], facts}` | `rules: []` (`src/api/queries.py:391-433`); no `suspected, readings, facts, read_by_apertus`; `not_assessed.reason` is a sentence, the UI expects a code (`queries.py:321`) | `triage.assessment_reason` (kind `signal`: `detail.value/contribution/effect/readings`, written by `src/scorer/load.py:264-277`) | API code; **UI crash risk** (`RelevanceCard.tsx:49-50`, `i18n.tsx:945-946`, no error boundary) |
| Scoring page | `GET /api/scoring` → `rules[], intercept, share_promoted` (`ScoringPage.tsx:29`) | `GET /api/scoring` returns `rules: []` (`src/api/queries.py:605-616`) | `ops.component_version.config` (`rule_weights`, `intercept`) | API code |
| Generate summaries | `POST /api/rulings/{id}/summaries` (`RulingPage.tsx:190`) | `POST /api/requests` kind `summary` → pending; no runner, no v3 → `summ.*` writer | `ops.user_request`; `summ.*` needs `corpus.segmentation` (`50_summ.sql:96`, NOT NULL) | pipeline code (layer 3, OWNER) |
| Edit, confirm, unconfirm a summary | `PUT .../summaries/{lang}`, `POST .../{lang}/confirm \| unconfirm` (`RulingPage.tsx:217-220`) | `summ.create_expert_version`, `gold.submit_review('summary_version', validated \| withdrawn)` (`src/api/writes.py:231-271`); review targets the DE+FR pair; response is not a `RulingDetail` | `summ.summary_version`, `gold.expert_review` | DDL for per-language validation; UI code |
| Revise with reason and note | `POST .../{lang}/revise` (`RulingPage.tsx:220`) | none | `ops.request_kind` has `add_judgement \| summary` only (`00_extensions.sql:73`) | DDL + runner |
| Inbox update | `GET/POST /api/updates` (`useUpdates.ts:26-39`) | none (`POST /api/runs` = layer 1 + layer 2, opt-in, `src/api/app.py:287-300`) | incremental ingest into `corpus` | pipeline + API code |
| Sentence provenance | `summaries[lang].sentences[]` with source offsets (`provenance.ts:11-28`) | none | no `summ.claim_source` (`50_summ.sql:132-153`) | DDL |
| Add a judgement by docket (AGENTS.md §1.4) | not in the UI | `POST /api/requests` kind `add_judgement` (`src/api/writes.py:118`), no runner | `ops.user_request` | UI + runner |
| Ids | numbers parsed with `Number(...)` (`App.tsx:27-31`) | string UUIDs (`src/api/app.py:29-30`) | `corpus.ruling.ruling_id` | UI code |

### 3.2 Increments (estimates, not measured)

| # | Increment | Owner | Needs DDL | Estimate |
|---|---|---|---|---|
| W1 | Adapter in `src/web/src/lib/api.ts`, selected by a build variable, mapping `src/api` reads to the UI types; UUID ids; error boundary; reason codes for `not_assessed` | frontend | no | 0.5 day |
| W2 | `src/api` additions: scorer rules and readings in relevance and scoring (from `triage.assessment_reason`, `ops.component_version.config`), `star`, rubric name, Suva label (`gold.v_label_effective`), facets shape, `confirm_relevant` alias | API owner | no | 1 day |
| W3 | Serve the built UI from `src/api` (static mount) so the cluster `ui` profile shows it; the image needs Node or a committed build (`Dockerfile:37-41`) | API owner + DDL/cluster owner | no | 2 h |
| W4 | Summary workspace on `summ.*`: segmentation step, v3 → `summ.*` writer, request runner (layer 3, OWNER's branch `layer3/summ-writer`) | OWNER | no | on OWNER's plan |
| W5 | DDL requests R1 to R5 (§6.2) | DDL owner | yes | 0.5 day + review |
| W6 | Retire `src/suva_app` and `public` once W1 to W5 serve every screen | lead | no | 1 h |

`make run` keeps serving Suva Scout until W6; the switch is a lead decision after the submission.

## 4. Where the frontend developer's database is

Not in git. Her push ships the means to rebuild and to fetch it:

| Asset | Where | Evidence |
|---|---|---|
| Published snapshot and dump: dataset **`suva-nga/bger-rulings`** pinned at revision `7eb6025dcac351e426a0fcae1cba3a02c332e7ed` | Hugging Face, **private** (checked 28 Nov with the lead's token: `private: True`, `gated: False`; without a token the API answers 401) | `src/suva_data/config.py:98-101`; `HfApi().dataset_info(...)` run by this audit |
| Its files: `dump/suva.sql.gz` (65,219,868 bytes), `tables/*.parquet` (`rulings`, `ruling_texts`, `source_records`, `conflicts`, `statute_refs`, `labels`, `gold_summaries`), `tables/schema.sql`, `snapshot/bger_list/*.html` (Neuheiten pages 1 Jul 2025 to 30 Jun 2026), `snapshot/entscheidsuche/*`, `snapshot/swiss_caselaw/*.parquet`, `manifest.json`, `quality_report.md` | same | same listing |
| `python -m src.suva_data pull` copies the dump to `db/init/10_suva.sql.gz` (git-ignored), loaded by scout-db on first start | `src/suva_data/cli.py:303-317` | read |
| Counts of her build: 6,055 rulings, 17,557 source records, 12,125 texts, 1,103 conflicts, 74,799 statute references, 59 labels, 110 gold texts | `data/manifest.json` `tables`; `data/quality_report.md:8-29` (the frontend developer's build, not re-measured here) | read |

D-051: her export writes the author column to `tables/gold_summaries.parquet` and the workbook link to `tables/labels.parquet` (`src/suva_data/export.py:74-103`). The dataset is private, so nothing is published today; making it public would publish both. Recorded as a known gap (§9, K-07).

## 5. D-031 and D-051 checks on what landed (D-100)

Scope: every file added or modified between `215e037` and `42a7b043` (24,418 files, 24,059 of them under `replay/llm/cache`).

| Check | Method | Result |
|---|---|---|
| D-051 values (author lines, name pairs, staff codes, intranet hosts and prefixes) | `uv run --frozen pytest -q tests/test_no_suva_personal_fields.py` | 4 passed |
| Verbatim Suva prose | 12-word shingles of the Text DE and Text FR of the 55 exports (parsed with `src/suva_data/loaders/gold_summaries.parse_export`, author never read), matched against every changed file (JSON parsed, strings scanned); counts and paths printed, never text | 57 files share at least one run: 50 replay answers, 4 deliverables, 3 test fixtures |
| Origin of the shared runs | the same shingles matched against the full text, regeste and abstracts of the 55 rulings in the pinned HF file | 39 files: every shared run is in the ruling itself (Suva quotes the court). 18 files: runs not in the ruling, 14 distinct phrases of 13 to 19 words, all standard legal formulas (for example "nicht wieder gutzumachenden Nachteil im Sinne von Art. 93 Abs. 1 lit. a BGG") |
| What the replay cache stores | read of a cache entry | the answer (`content`, `served_model`, `finish_reason`, `usage`, `mode`, `cache_key`, `latency_s`, `attempts`); no prompt |
| Per-docket Suva-derived files | regex scan of dockets vs the workbook and the exports | `results/extract_eval_iterate_c1..c13.json`, `results/extract_eval_holdout_c14.json` (per-ruling recall against Suva's summaries), `results/deliverables/*` (our predictions; dockets overlap the workbook because Q1/2026 decisions are published in Q2) |

The scan scripts live in the session scratchpad, not in the repository; rerunning them is the next step of K-12.

## 6. Requests to other owners

### 6.1 To the API owner (code only)

| # | Request | Evidence |
|---|---|---|
| A1 | Relevance and scoring: return the scorer's rules, readings and intercept from `triage.assessment_reason` and `ops.component_version.config` | `src/api/queries.py:391-433,605-616` |
| A2 | `not_assessed.reason` as a code, not a sentence | `src/api/queries.py:321` |
| A3 | Expose `star`, the raw rubric, the Suva label and the outcome when parsed | `corpus.v_ruling.star`; `gold.v_label_effective` |
| A4 | Summary writes return the ruling detail (or document a refetch) | `src/api/writes.py:236,259,272` |
| A5 | Static mount of the built UI | `docs/API.md:101` |
| A6 | Docs: `docs/API.md:9-10`, `src/api/app.py:3` and `docs/DATA_CATALOG.md:13` say `make serve` and `make run` serve `src/api`; since the Scout merge they serve Suva Scout and `make api` / `make pipeline` serve `src/api` | `Makefile:20-47` |

### 6.2 To the DDL owner (written requests, no edit made)

| # | Request | Why | Evidence |
|---|---|---|---|
| R1 | `summ.claim_source` (claim → ruling span: segment, start, end) | sentence provenance on the ruling page | `50_summ.sql:132-153` |
| R2 | A language on summary validation reviews, or a per-language target | the UI confirms DE and FR separately | `70_functions.sql:85-91` |
| R3 | `ops.request_kind` value for revision, and a payload column (reason, note) on `ops.user_request` | labelled revision requests | `00_extensions.sql:73`; `11_ops_execution.sql:121-134` |
| R4 | A ruling-level review target (decide on a ruling with no assessment) | Scout allows it, `src/api` answers 409; D-093 lists it open | `src/api/writes.py:82-83` |
| R5 | `source_kind` values for `entscheidsuche`, `hf_daily`, `statute_graph`, and the matching exclusion `source` CHECK and trigger kinds | provenance and closure for the frontend developer's sources | `00_extensions.sql:69`; `20_corpus.sql:56`; `80_triggers.sql:364-368` |
| R6 | A table for statute references (ruling, law, article, paragraph) | 74,799 rows exist only in `public` | `data/manifest.json` |
| R7 | GRANTs if `public` and the six schemas share one database (read roles get no SELECT on `public`) | same-database loader | `90_roles.sql:45-49` |

## 7. Data merge plan: `public` → the six schemas (D-101)

Source: the private HF dataset of §4 at its pinned revision, read from `tables/*.parquet` (never from the dump's `gold_summaries.author`). One `ops.source_snapshot` per parquet file (source, revision `7eb6025…`, SHA-256, row count); every row loaded or written to `corpus.ingest_exclusion` with a reason code; the closure view proves it (`60_views.sql:52-81`), as `src/ingest/hf_base.py:375-416` does for the HF base.

| Step | `public` source | Target | Natural key | Write path today | Blocked by |
|---|---|---|---|---|---|
| 1 | `rulings` (Neuheiten tier) | `corpus.publication_observation`, `corpus.subject_observation` (`neuheiten`) | (ruling_id, source) | none | nothing (observation kinds exist) |
| 2 | `ruling_texts` (entscheidsuche) | `corpus.ruling_text` source `entscheidsuche` | (ruling_id, source, content_sha256) | none | R5 |
| 3 | `conflicts` | `corpus.ingest_issue` | detail | none | seed reason codes |
| 4 | `statute_refs` | new table | (ruling, law, article, paragraph) | none | R6 |
| 5 | `gold_summaries` (Text DE / FR only) | `gold.suva_summary` | `source_file` | none; reuse `parse_export` from `judgements/` directly, author dropped | nothing |
| 6 | `model_runs` + `predictions` | `triage.assessment(_reason)` on profile `scout` | (run, ruling, step, repetition) | `make bridge` (D-099) | a Scout database or the dump restored |
| 7 | `labels` (expert), `relevance_events` | `gold.expert_review` | append-only | `gold.submit_review` | a target assessment (R4) |
| 8 | `summaries`, `summary_events` | `summ.*`, `gold.expert_review` | (summary_id, version_no) | `summ.create_expert_version` needs a parent | W4 (segmentation, layer 3) |

Rulings are matched on (docket, decision_date) after the same normalisation as `src/suva_data/models.normalise_docket`; a `public` ruling with no six-schema twin is excluded with a reason (`ING_NOT_IN_BASE`, to seed), never inserted silently. Estimate for steps 1, 3 and 5 with tests on three real rulings (DE, FR, IT): about 4 hours; the whole plan: about 2 days plus R5, R6 (estimates).

## 8. Tests run

| Command (worktree, throwaway DB on 127.0.0.1:55470) | Before D-099 (`42a7b043`) | After D-099 |
|---|---|---|
| `make db-deploy` | 15 files applied | unchanged (no DDL) |
| `make db-structure` | matches, 1,291 objects | unchanged |
| `make db-test` | 12 passed, 0 failed | unchanged |
| `pytest tests/test_layer2_db.py tests/test_api_db.py tests/test_registry_refs.py tests/test_scorer_load.py tests/test_ingest_closure_db.py` | 10 failed + 8 errors (one cause: `Layer2Config` refuses V2.0.0) | **43 passed** |
| `make check` (ruff check, ruff format, pytest) | 1,212 passed, 17 failed, 1 skipped, 8 errors | **1,230 passed, 7 failed, 1 skipped, 0 errors** |

The 7 failures left are not caused by D-094: `tests/test_extract.py` and `tests/test_refine.py` (3 each) query `public.rulings` on `DATABASE_URL` and fail on a database without the Scout schema (`tests/test_extract.py:236`); `tests/test_triage_features.py::test_xgboost_variant_runs_weighted` fails at `from xgboost import XGBClassifier` on this Mac (`src/triage/variants.py:46`).

## 9. Known gaps

| ID | Gap | Evidence | Impact | Next step |
|---|---|---|---|---|
| K-01 | `src/web` is bound to `suva_app` routes and shapes on all its calls | `src/web/src/lib/api.ts:115-274` vs `src/api/app.py:162-300` | D-101 not met yet | W1, W2 |
| K-02 | The "why" card dereferences fields `src/api` does not return; no error boundary | `RelevanceCard.tsx:49-50`; `i18n.tsx:945-946`; no `ErrorBoundary` in `src/web` | a white screen on the first ruling page served by `src/api` | W1 (boundary), A1, A2 |
| K-03 | No summary in the six schemas: segmentation empty, no v3 → `summ.*` writer, no runner | `50_summ.sql:96`; `docs/API.md:97,100` | the summary workspace is empty on `src/api` | W4 (OWNER) |
| K-04 | The scorer is computed only in Suva Scout; the six schemas get it through a manual `make bridge` | `Makefile:49-52`; `src/scorer/load.py:141` | under D-099 the shown label is the 8B judge's; G6 not met for V2.0.0 | port the scorer (features over `corpus.*`, readings through `src/llm`) or set `scout` as default after a bridge |
| K-05 | The bridge keeps no `ops.llm_call` for the six readings; the component hash covers `src/scorer/load.py` and `models.py` only | `src/scorer/load.py:34,217-229`; `src/ingest/__main__.py:44-50` | a change in `src/triage/scorer.py` or its prompts is invisible to the registry | hash the triage code and prompts into V2.x; backfill calls from `replay/llm` |
| K-06 | The 8B judge replays only what `data/derived/llm` holds: 383 of 935 candidates on 28 Nov (D-085) | `docs/DECISIONS.md` D-085 basis line | the default label is partial in replay | a live layer-2 run with `LLM_*`, or ship its answers (D-100 allows it) |
| K-07 | The private HF dataset stores the author column and the workbook link | `src/suva_data/export.py:74-103`; dataset listing §4 | publishing the dataset would breach D-051 | drop both columns from the export before any visibility change |
| K-08 | No loader from `public` to the six schemas except the predictions bridge | §7 | Neuheiten dates and stars (5,432 rulings per `data/quality_report.md`), entscheidsuche texts, conflicts, statute references, expert actions and summaries exist only in `public` | §7 steps 1, 3, 5 first |
| K-09 | Three Scout decision rows reused D-072 to D-074 | `docs/DECISIONS.md` (before D-099) | ambiguous references | renumbered D-102 to D-104 by D-099; `REVIEW_FINDINGS.md` keeps the old numbers as history |
| K-10 | Docs say `make serve` / `make run` serve `src/api` | `docs/API.md:9-10`; `docs/DATA_CATALOG.md:13`; `src/api/app.py:3` | a reader starts the wrong app | A6 |
| K-11 | Concurrency cap per client, not per process: summaries open one client per ruling (8 workers × 2 languages) | `src/llm/client.py:140`; `src/summarize/pipeline.py:377`; `src/summarize/batch.py:35,152` | up to about 16 concurrent calls from one machine against a team-wide cap of 16 (G2) | one shared client or a process-wide semaphore (lead, `src/llm` owner) |
| K-12 | The D-031 scan is a one-off script | §5 | a later commit is not checked | a test next to `tests/test_no_suva_personal_fields.py` |
| K-13 | Template placeholders and no report PDF at the root | `README.md:7`; `technical_report.md` header; no `*_Report.pdf` | T5, T7, T10 at submission | pitch role |
| K-14 | `make run` rewrites tracked files (`results/triage_pipeline.json`, `data/quality_report.md`) | `src/triage/pipeline.py:307-308`; `src/suva_data/cli.py:141` | a replay overwrites a LIVE result; dirty tree | write to `data/runs/` unless asked |
| K-15 | `results/deliverables/*` has no generator in the repository | `grep -rn deliverables src eval research Makefile` → none | not reproducible (G6, G11) | add a target |
| K-16 | Seven `make check` failures not caused by D-094 | §8 | `make check` red on a machine without scout-db or xgboost's runtime | skip when `public.rulings` is absent; mark the xgboost test |

## 10. Assets

| Asset | Built, tested or measured | Source |
|---|---|---|
| Suva Scout UI: list with filters, URL state, inbox, ruling page with sentence-to-source highlight, DE/FR edit, confirm, revise, scoring explainer, three UI languages | built; no UI test | `src/web/src/lib/filters.ts:56-102`; `RulingPage.tsx`; `provenance.ts`; `i18n.tsx` |
| Expert traces in `public`: `relevance_events` (status before and after, score shown), `summary_events` (before/after text, reason, note) | built; 35 tests across `test_feedback.py`, `test_workspace.py` | `src/suva_app/feedback.py:62-77`; `workspace.py:95-102` |
| `src/api` on the six schemas: least-privilege sessions, statement timeout, append-only reviews, 503/504 mapping | built; 15 unit + 8 DB tests, 8 DB tests green after D-099 (this audit) | `src/api/db.py:28-53`; `tests/test_api_db.py` |
| Scorer loader that refuses a run the registered weights do not give | built; 6 tests | `src/scorer/load.py:67-101,183-193`; `tests/test_scorer_load.py` |
| Shipped replay store (24,059 answers), checked for D-031 and D-051 | measured by this audit | `replay/llm`; §5 |
| Her dataset with Neuheiten tier-1 dates for 5,432 rulings and two independent texts for 6,050 | the frontend developer's measurement | `data/quality_report.md`; `docs/DATA_LAYER.md:9` |
| Six-schema provenance and closure machinery | built; `make ingest-closure` | `src/ingest/hf_base.py:375-416`; `60_views.sql:52-81` |
| Default profile restored, scorer profile kept | measured: 43 tests green | `src/db/seed/profiles.json`; §8 |
| Layer-1 parity reference unaffected by the `src/courts.py` change | the frozen copy's SHA-256 equals `git show 4c246a8:src/courts.py` | `src/layer1/reference_courts_4c246a8.py`; `tests/test_layer1_reference.py` |
