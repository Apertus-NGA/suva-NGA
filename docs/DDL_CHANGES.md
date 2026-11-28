# DDL_CHANGES: what changed in the database, for whoever builds the API and the UI

> Owner: the DDL owner (platform; the lead while D-024 is open). Readers: the API and UI builders, human or agent. Each entry says what changed in `src/db/sql/` and **what it changes for an API contract**. The baseline is the data catalog (`docs/DATA_CATALOG.md`, snapshot on `main` @ `14caaba`, amended for DDL-2). Newest entry first.

## How the entries are checked

Each entry is measured, not read from the SQL: the baseline DDL and the new DDL are deployed into two empty databases, then compared object by object (tables, columns, constraints, indexes, ENUMs from `src/db/structure.py`, plus every view column, view definition, function and trigger). `expected/db/structure.json` is the machine-readable list of every table, column, constraint, index and ENUM of the current DDL (1,291 objects); CI fails when it does not match a fresh deploy.

## 2026-11-28, branch `api/fastapi-backend` (D-093): expert decisions on any assessed ruling

Measured: `main` @ `95d744a` against this branch, fresh deploys. **2 differences out of 1,291 structure objects** (`expected/db/structure.json` regenerated), plus view, function, trigger and seed changes listed below. **Every existing database needs a reset** (`docs/RUNBOOK_DB.md` §2): the guard refuses the changed ENUM and constraint.

| Object | Change | Effect on the API contract |
|---|---|---|
| ENUM `ops.review_verdict` | + `relevant`, `not_relevant`, `withdrawn` | a reader of `gold.expert_review.verdict`, `v_scope_current.expert_verdict` or `v_summary_current.expert_verdict` meets three new values |
| Constraint `gold.expert_review.expert_review_target_chk` | a scope review may be `relevant` \| `not_relevant` on any label (`potentially` included); `withdrawn` (scope or summary) needs `supersedes_review_id`; a scope review always has a `reviewed_label` | an expert can decide on a `potentially` ruling and take a decision back; `reviewed_label` still means the label the expert saw |
| `triage.v_scope_current` (definition) | `expert_implied_label`: `relevant` → `in_scope`, `not_relevant` → `out_of_scope`, `withdrawn` → NULL | same columns; after a withdrawal `expert_verdict` = `withdrawn` and no implied label |
| `gold.submit_review()` | refuses `withdrawn` without `p_supersedes` | the API passes the review it takes back |
| `gold.check_expert_review()` | a withdrawal never supersedes another withdrawal | 409 from the API |
| Seed `ops.json_schema` | `scope_review.payload` V1.1.0: optional `shown_status`, `shown_score_0_100` (0-100), `shown_score_raw` | the payload records what the expert saw; the database checks only that it is an object |

## 2026-11-28, PR #51 (D-091) and what landed since the catalog snapshot (PR #48, PR #49)

Measured: catalog baseline `47f3e47` against `main` + PR #51. **6 differences out of about 1,740 objects, none in a table, a column or a view's columns.**

| Object | Change | Effect on the API contract |
|---|---|---|
| Tables, columns, constraints, indexes, ENUMs | **none** (1,291 objects identical) | none |
| View columns (every view of the six schemas) | **none** | none: the same columns, the same types |
| `triage.v_scope_pipeline` (view definition) | DDL-2, PR #49: the label comes only from runs that finished usable (`succeeded` or `partial`, never `eval`), and only along the lineage of the ruling's current layer-1 decision | same columns, **fewer rows can qualify**: a judgement from a failed or aborted run, or made on an older layer-1 decision, no longer forms the label. The catalog already describes it (§ `triage.v_scope_pipeline`). Read the label from this view (or `triage.v_scope_current`), never from `triage.assessment` directly |
| `triage.llm_judgement`: trigger `t31_call` and function `triage.check_llm_judgement()` | DDL-1, PR #49: a judgement must link to its LLM call | write side only (the pipeline writes it); nothing for a reader |
| `triage.check_assessment_reason()` | D32, PR #48: on a ruling without text, only a `text_unavailable` rule may fire on `full_text` | write side only; nothing for a reader |
| Database setting `default_transaction_isolation` | PR #51: pinned to `read committed` on the database | an API session runs READ COMMITTED unless it asks for more; a multi-statement read that needs one snapshot opens its own `BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY` |
| Deploy (`src/db/deploy.py`, `src/db/schema_guard.py`) | PR #51: one transaction; the guard compares the structure | none at run time; an upgrade that changes a table stops before it touches the database (`docs/RUNBOOK_DB.md`) |

## Rules an API keeps (current state)

- **Login and rights.** The API connects as `suva_api` (groups `suva_g_read` and `suva_g_review`), never as the owner or the pipeline login. It keeps that login's own rights: `src.db.pg.connect()` runs `SET ROLE suva_g_pipeline` by default, which `suva_api` is not granted, so the API calls `connect(..., pipeline=False)` or runs with `DB_PIPELINE_ROLE` set empty (the cluster's `app` service does, `docker-compose.yml`).
- **Writes.** The API writes only through `gold.submit_review`, `summ.create_expert_version` and `ops.submit_request` (SECURITY DEFINER functions, `src/db/sql/90_roles.sql`); it cannot insert into a table directly.
- **Statement timeout.** `suva_api` has `statement_timeout = 15s` and at most 20 connections (`90_roles.sql`): size a pool accordingly.
- **The label.** `triage.v_scope_pipeline` (pipeline) and `triage.v_scope_current` (pipeline + latest expert review). A ruling with no row is not assessed. `score_raw` (the logit, for ranking, D-077) is on `triage.assessment`, joined by `assessment_id`.
- **Stability.** A table or column change always comes with a new entry here, a regenerated `expected/db/structure.json` and a reset of every database (`docs/RUNBOOK_DB.md`); a view, function or trigger change comes with an entry here when it changes what a reader sees.
