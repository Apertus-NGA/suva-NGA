# DB_DDL_PLANNING: the data layer (PostgreSQL) for rulings, scope labels, versions, logs and summaries

> **Status: v0.4 — Phase 1 (doctrine freeze) and Phase 2 (SQL/schema) delivered on branch `platform/db-ddl`, 28 Nov 2026, 02:45 CET.** Decisions recorded as D-061 to D-071 in `docs/DECISIONS.md`. The DDL is in `src/db/sql/` (15 files, 57 tables), its tests in `tests/sql/` (8 files, green on PostgreSQL 17) and `tests/test_db_deploy.py`; `make db-reset`, `make db-deploy`, `make db-test`; a CI `db` job. Next: Phase 3 (docs sync) and Phase 5 (loaders, step writers). Owner: platform (the lead, while D-024 is open).
> Evidence: the read-only audit of 27 Nov (`tmp/audits/audit-data-layer-2026-11-27.md`, git-ignored) and DuckDB queries on the pinned HF file (`bger.parquet`, commit `35b17aa9c3fad71011b72f78f6ab79650ec0cf96`, SHA-256 `d2b2df1d…`). Numbers marked *estimate* are not measured.
> Reading order: §0, §7 (versions and registry), §9 (scope label), §11 (logs), §12 (expert reviews), §13 (summaries), §17 (open questions).

**Changes in v0.5 (28 Nov, layer 1 on the DB, branch `triage/layer1-enterprise`):**
- One table added: `corpus.subject_observation` (a ruling's rubric per source, D-072), so 57 tables; enum `subject_source`.
- Layer-1 reason codes are the `L1_*` codes of `docs/LAYER1.md` §6.2 (D-073), replacing the filter-E codes of v0.4.
- §19.2: DB-11 (HF bger part), DB-13 and the layer-1 part of DB-14 done; DB-10 in part (registry loader and the files-then-DB writer, without the protocols and the tee).

**Changes in v0.4:**
- Phase 2 delivered (§19.2: DB-01 to DB-09 done). One table added while writing the SQL: `ops.user_request` (the "add another judgement" and "summarise this ruling" requests of the UI, §5), so 56 tables. Audit moved to its own file, `13_audit.sql`.
- §21: the D-lines are recorded in `docs/DECISIONS.md` as D-061 to D-071.

**Changes in v0.3:**
- OQ-3, OQ-5, OQ-12 and OQ-15 to OQ-20 settled with the recommendation (§17.1); §12.3, §13.4 and §13.6 now state decisions.
- §21 added: the D-lines to record in `docs/DECISIONS.md` (Phase 1).

**Changes in v0.2:**
- Answers to OQ-1, 2, 4, 6, 7, 8, 9, 10, 11, 13 and 14 recorded (§17.1).
- New §7: one version per step, numbered `V<major>.<minor>.<patch>`, each bound to its own models, a configuration checked against a JSON Schema template, and rules.
- New §11: logs as spans, events and metrics.
- New: expert reviews (§12.2), versioned segmentations for the splitter (§8.3), presets stored in the DB (§13.2).
- OQ-3, OQ-5 and OQ-12 explained (§12.3, §13.4, §13.6).

---

## 0. TL;DR

- **One PostgreSQL 17 database** (D-004, the pinned `pgvector/pgvector:0.8.1-pg17` image) with **6 schemas**: `corpus`, `triage`, `gold`, `summ`, `ops`, `audit`.
- **Every step of the pipeline has its own versions,** numbered `V<major>.<minor>.<patch>` (e.g. `V2.1.2`). A version holds its models, its configuration and its rules. A **pipeline profile** (e.g. `default` V1.0.0) pins one version per step, and every run, assessment, summary and log line points to the exact version that produced it.
- **The DB does not know any configuration's shape.** Each configuration is a `jsonb` value that the application checks against a JSON Schema **template**, stored and versioned in `ops.json_schema`. A new configuration field needs no DDL change.
- **The logs are first-class data:** spans (one unit of work, e.g. one step on one ruling), events (log lines, partitioned by day), and metrics (counters per step). Every assessment, LLM call and summary links to its span. A timeline view shows the full story of a ruling.
- **Committed files are the source of truth, and the DB can be rebuilt from them** (the "fresh deploy" rule). State written by people (expert reviews, expert edits, presets) is exported to files so it survives a rebuild. The Q2 deliverable never waits for the DB.
- **The base dataset comes from HF:** the Q2/2026 union (2,677 rulings), Q4/2025 (1,931), Q1/2026 (2,005) and the 23 Q3/2025 rulings Suva summarised, about 6,055 in total. Considerations (the court's numbered reasoning) come from the downloaded `erwaegungen_paragraphs` file, stored as **versioned segmentations** so the splitter can mature before it is applied everywhere.
- **`in_suva_scope` ∈ {`in_scope`, `out_of_scope`, `potentially`},** produced per layer (assessments that are never edited) and read through a **view**.
  - Layer 1 gives `potentially` or `out_of_scope`.
  - Layer 2 gives a **score from 0 to 100** and keeps `potentially`.
  - Ranking (the frozen threshold) gives `in_scope` or `out_of_scope`.
  - A failure stays `potentially`.
- **The label shown and used is the default pipeline's.** Experts add **reviews**: relevance V1 = `correct` or `incorrect`; summaries = `validated` or `rejected`. Reviews are stored apart, never merged into the pipeline's label.
- **Summaries:** one (ruling, preset) pair has immutable versions; **each version is always a German + French pair**; each text is split into claims; claims cite considerations through a database link (G1) and carry the verifier's checks.
- **Presets live in the DB** and can be selected at run time. Perspective goes from 0 (insured person) to 10 (insurer), using written anchors at 0, 3, 5, 7 and 10. The perspective changes emphasis, never facts. `suva_house` is the mandatory preset for every in-scope ruling.
- **Roles follow least privilege:** an owner role that never logs in, three groups, and experts writing only through narrow functions. A **Postgres service in CI from now on** runs the SQL tests.
- **Scope:** 57 tables in P0 (built: `src/db/sql/`), many of them small lookup or join tables. P1 adds parties, references, splits and search.

---

## 1. Vision and architectural frame

### 1.1 What the DB is for

| Purpose | Served by |
|---|---|
| Store every ruling of the base dataset with its sources | `corpus.*` |
| Give every ruling its scope label, layer by layer, with the full why | `triage.*`, views |
| Version every step: models, configuration, rules; compose them into pipeline profiles | `ops` registry (§7) |
| Show transparency: any number on screen traces back to version, configuration, model, prompt, input, source and logs | `ops` execution and logs (§11, §14), trace views |
| Keep the truth (Suva) and expert opinions apart from predictions | `gold.*` |
| Store summaries of several kinds and versions, verified claim by claim, reviewed by experts | `summ.*`, `gold.expert_review` |
| Resume an interrupted run; show progress | `ops.work_item`, spans |

Not its job: holding anything that cannot be rebuilt, except what people write (that is exported); computing the evaluation metrics (eval scripts read views or files); search (D-033, §18).

### 1.2 The needs as understood

| # | Need | Where |
|---|---|---|
| N1 | We are scored on **Q2/2026** predictions; Q4/2025 and Q1/2026 are training and/or evaluation data; all three are ingested | §8.1, §12.5 |
| N2 | Ruling data spread over several tables, not one row per ruling with every field | §8.4 |
| N3 | Every ruling has `in_suva_scope`: true, false or potentially; potentially is the result of layer 1 | §9 |
| N4 | Exhaustive, enterprise-grade scoring metadata for every layer | §10 |
| N5 | Every in-scope ruling (by the default pipeline) **must** have a summary; any ruling **may** have one | §13.7 |
| N6 | Several **kinds** of summary, one kind per **preset** | §13.2 |
| N7 | Several **versions** per summary; a version is always a German + French pair | §13.5 |
| N8 | Presets on a perspective scale, insured ↔ insurer | §13.3 |
| N9 | A separate model version for each layer and step | §7.2, §7.3 |
| N10 | Versions numbered `V<major>.<minor>.<patch>` | §7.1 |
| N11 | For each layer, a template set of configuration and rules; the DDL is agnostic to the configuration's shape but ready for it | §7.4, §7.5, §7.7 |
| N12 | Every step logs a lot; the DDL handles it for deep transparency | §11 |
| N13 | Experts validate summaries and review relevance (V1: correct or incorrect) from the frontend | §12.2 |
| N14 | Presets stored in the DB and selected at run time | §13.2 |

### 1.3 Constraints inherited from the project

| Constraint | Meaning here |
|---|---|
| G1 | identifiers come from code, never from Apertus |
| G5 | no exclusion without a counted reason; a failure is not a negative |
| G9 | tests assert on stored output |
| G13, D-038 | no personal data; no team member names in files |
| D-051 | no Suva author, staff code or intranet link |
| D-031 | anything derived from `judgements/` stays out of git; the DB is not in git, and exports of gold data or of prompts containing Suva text go to `data/derived/` |
| D-050 | both dates kept |
| D-052 | the delivered window is the publication date by default |
| D-046 | the threshold and the top-30 cut are both marked |
| D-047 | summary order |
| D-059 | `src/` holds code and its run-time data only |
| `tests/test_models_registry.py` | no model id in `src/` unless it is listed in `MODELS.md`, so the DB's model table is loaded from `MODELS.md` |

### 1.4 Method

The plan follows a seven-phase feature method (0 design draft, 1 doctrine freeze, 2 SQL/schema, 3 docs sync, 4 deploy gate, 5 implementation, 6 validation), applied with this repo's rules:

| Method rule | Here | Why |
|---|---|---|
| Decisions recorded with a work-item id | `DB-NN` work items (§19); decisions become D-lines in `docs/DECISIONS.md` (§21) | `docs/DECISIONS.md` is this repo's register (AGENTS.md §2) |
| Nothing is lost | **append-only** facts (assessments, LLM calls, labels, reviews, summary versions, logs), protected by a trigger and by grants; `retired_at` / `status` on registry and configuration rows | traceability: a fact is superseded, never edited |
| Who created a row | `creator_kind` (`pipeline` \| `expert`) + `creator_run_id` \| `creator_actor` (a pseudonymous handle), with a strict CHECK | no user accounts; G13 |
| One table per relation, not per target | `gold.expert_review` (target = a scope assessment or a summary version); `summ.verification_check` (target = claim or text) | fewer tables, one rule set |
| Counters are projections | no `*_count` column on business rows; views and `ops.run_metric` | a counter column drifts |
| Fresh deploy, no ALTER | `make db-reset` drops, recreates and reloads from files, plus the export of what people wrote | matches "files are the truth" |
| Closed vocabularies are ENUMs | ENUMs in `00_extensions.sql`; **lookup tables** for open vocabularies with UI labels (`ops.reason_code`, `summ.perspective_anchor`) | they grow with each version |
| Numbered, idempotent SQL files with tests | `src/db/sql/NN_*.sql`, `src/db/deploy.py` behind `make db-reset` / `make db-test`, `tests/sql/*.sql` | D-059; one entry point (Makefile: lead's approval, G7) |
| Roles in their own file | `src/db/sql/90_roles.sql` (§15.6) | |
| Engine version | PostgreSQL 17 (pinned image); no PG18-only feature | compose; Azure is D-049 |
| Memory note per project | written at Phase 1, outside the repo | |

---

## 2. Business model: five entities that are never merged

| Entity | What it is | Key | Schema |
|---|---|---|---|
| **Ruling** | a Federal Court decision and what its sources state about it | (docket, decision_date) | `corpus` |
| **Assessment** | what one step of one pipeline version concluded about one ruling in one run | (run, ruling, step, repetition) | `triage` |
| **Truth and opinion** | Suva's labels (truth for Q4/2025, Q1/2026) and expert reviews (opinions about our outputs) | label id, review id | `gold` |
| **Summary** | a text about one ruling under one preset, in versions | (ruling, preset) → versions | `summ` |
| **Provenance** | the **registry** (what may run: step versions, models, configurations, rules, profiles) and the **execution** (what ran: runs, spans, events, LLM calls, files) | version label; run id | `ops`, `audit` |

| Forbidden fusion | Why it breaks |
|---|---|
| Ruling + truth (`ruling.is_relevant`) | training and evaluation leak |
| Assessment + truth (one label column filled by the pipeline, Suva and experts) | the pipeline can no longer be measured |
| Ruling + assessment (`ruling.score`, `ruling.rank`) | a rerun erases history; a rank depends on population and run |
| Ruling + summary (`ruling.summary_de`) | one kind, one version, no claims, no checks |
| Registry + execution (configuration copied into result rows) | nobody can say which version produced a row; nobody can reuse a version |
| Logs + business rows (debug text in `explanation_de`) | the UI shows noise; logs cannot be filtered or partitioned |

---

## 3. Capability separation

| Capability | Source of truth | DB role | Forbidden coupling |
|---|---|---|---|
| Ruling corpus | `data/public/*.parquet` built from pinned HF files (`ops.source_snapshot`: commit and hash) | projection, rebuilt by the loader | editing a text or a consideration in the DB |
| Segmentations (considerations) | the segmentation step's output files, per splitter version | projection; one primary segmentation per text | citing a consideration from another segmentation |
| Registry: step versions, configuration templates, rules, profiles | seed files `src/db/seed/registry/*.json` (reviewed in PRs), plus seeds containing Suva material in `data/derived/registry/` while D-031 is open | projection; insert-only | editing a version in place |
| Models | `MODELS.md` (single home of ids, E6, G3) | projection (`ops.model`) | a model id typed in SQL or code |
| Presets | **the DB** (selected at run time; created by seed or UI) | truth, exported to `data/derived/authored/` at each change | a preset changed without a new version |
| Gold labels | `judgements/` (read-only, D-040) | projection | the pipeline writing `gold.*` |
| Expert reviews, expert summary edits | **the DB** | truth, exported to `data/derived/authored/` at each change and release | losing them on `make db-reset` |
| Assessments | stage result files + LLM cache | projection, append-only | a UI writing an assessment |
| Logs (spans, events, metrics) | `data/runs/<run_id>/{spans,events,metrics}.jsonl` (git-ignored) | projection, loaded idempotently | logs only in the DB, or only on stdout |
| Ranking, delivered list | `results/ranked_q2_2026.csv`, `results/relevant_q2_2026.txt`, hashed in `ops.artifact` | projection | ranking from inside the UI |
| Current scope label | none: computed | view | a stored "current label" column |

---

## 4. Internal contracts

Stages never write SQL. They use three protocols in `src/db/`:

```python
class Registry(Protocol):                       # §7: what may run
    def profile(self, code: str = "default", version: str | None = None) -> ProfileVersion: ...
    def component_version(self, step: Step, version: str) -> ComponentVersion: ...
    def register_component_version(self, step: Step, version: str, config: dict, rules: list[RuleRef],
                                   models: dict[ModelRole, ModelRef], prompts: dict[str, PromptRef],
                                   changelog: str) -> ComponentVersionId: ...   # validates config against its JSON Schema
    def preset(self, code: str, version: str | None = None) -> PresetVersion: ...

class Store(Protocol):                          # business records
    def begin_run(self, profile: ProfileVersion, kind: RunKind, mode: Mode, params: dict) -> RunId: ...
    def finish_run(self, run_id: RunId, status: RunStatus) -> None: ...
    def upsert_rulings(self, rulings: Iterable[RulingRecord], snapshot: SnapshotRef) -> Counts: ...
    def record_assessments(self, rows: Iterable[AssessmentRecord]) -> Counts: ...
    def record_llm_call(self, call: LLMCallRecord) -> LLMCallId: ...
    def save_summary_version(self, v: SummaryVersionRecord) -> SummaryVersionId: ...
    def work_items(self, run_id: RunId, step: Step, status: WorkStatus) -> Iterator[WorkItem]: ...

class Telemetry(Protocol):                      # §11: what happened
    def span(self, step: Step, operation: str, ruling_id: RulingId | None = None) -> ContextManager[Span]: ...
    def event(self, level: Level, code: str, message: str, **attributes) -> None: ...
    def metric(self, step: Step, code: str, value: float, unit: str) -> None: ...
```

Each protocol has a file implementation (always on: JSONL and Parquet, the source of truth) and a Postgres implementation. A `Tee` writes the file first. Records are pydantic contracts in `src/schemas.py` (frozen contracts: change by PR, G7).

**Future-proof check:**
- Postgres → Azure Database for PostgreSQL (D-049): only the connection string changes.
- A stage is rewritten: it keeps its `step` and gets a new version.
- A new configuration field: new JSON Schema version, no DDL change.
- A new log field: it goes into `attributes`, no DDL change.

---

## 5. API boundary

| Verb and route | Reads or writes | Through |
|---|---|---|
| `GET /api/rulings?population=&scope=&sort=score` | table rows | `corpus.v_ruling` ⨝ `triage.v_scope_current` ⨝ `triage.ranking_entry` |
| `GET /api/rulings/{docket}` | ruling page | `corpus.*`, `triage.v_scope_current` |
| `GET /api/rulings/{docket}/trace` | every step's assessment with versions, models, reasons, evidence, LLM calls | `triage.v_scope_trace` |
| `GET /api/rulings/{docket}/timeline` | spans and events of the ruling, all runs | `ops.v_ruling_timeline` |
| `GET /api/rulings/{docket}/summaries?preset=` | current versions, claims, citations, checks, expert reviews | `summ.v_summary_current` |
| `GET /api/presets` | active presets with their perspective and current version | `summ.preset`, `summ.preset_version` |
| `GET /api/registry/profiles/{code}` | the step versions of a profile (transparency panel) | `ops.v_profile` |
| `GET /api/export/relevant?population=2026Q2_publication` | delivered list | `triage.v_export_ranked` (equal to the hashed file) |
| `GET /api/status` | runs, metrics, work items, degraded steps | `ops.*` |
| `POST /api/rulings` `{docket \| url}` | "add another judgement" (D-015) | `ops.request_work()` |
| `POST /api/rulings/{docket}/summaries` `{preset_code}` | requests a summary of any ruling under any preset | `ops.request_work()` |
| `POST /api/reviews/scope` `{assessment_id, verdict}` | expert relevance review, V1: `correct` \| `incorrect` | `gold.submit_review()` |
| `POST /api/reviews/summary` `{summary_version_id, verdict}` | expert summary review: `validated` \| `rejected` | `gold.submit_review()` |
| `POST /api/summaries/{summary_id}/versions` | expert edit → a new version (German + French pair) | `summ.create_expert_version()` |

**Not in the API:** writing an assessment, a ranking, a span or an event; editing a ruling, a text, a consideration or a registry version; deleting anything; editing Suva's gold.

---

## 6. Schema map and inventory

```text
REGISTRY (what may run)                                    EXECUTION (what ran)
ops.json_schema ◀── ops.component_version ──▶ ops.model    ops.pipeline_run ──┬── ops.span ── ops.log_event (partitioned by day)
ops.reason_code ◀── ops.rule ◀── ops.component_version_rule│   (profile_version)├── ops.run_metric
ops.prompt_version ◀── ops.component_version_prompt        │                    ├── ops.llm_call ── ops.llm_call_example
ops.pipeline_profile ── _version ── _step ─────────────────┘                    ├── ops.work_item
                                                                                ├── ops.artifact ── ops.release
                                                                                └── ops.source_snapshot      ops.blob
CORPUS
corpus.ruling ── ruling_source_ref │ publication_observation │ ruling_text ── segmentation ── consideration (tree)
              ── ruling_parse │ ingest_issue │ population_member ── population
TRIAGE
triage.assessment (per step, span, component version) ── assessment_reason (rule, evidence)
                  ├── llm_judgement (layer 2)   ├── justification ── assessment_evidence ── corpus.consideration
                  └── ranking_entry ── ranking ── threshold                          (ops.release points to a ranking)
GOLD
gold.label (Suva list, Suva exports)   gold.expert_review (scope | summary_version)   gold.suva_summary   gold.split_*
SUMM
summ.perspective_anchor ◀── summ.preset ── preset_version ── preset_version_prompt
summ.summary (ruling × preset) ── summary_version (pair) ── summary_text (de, fr) ── summary_claim ── claim_citation
                                                                                  └── verification_check (rule)
AUDIT
audit.change_log ← triggers on every mutable row
```

| Schema | P0 tables | P1 tables |
|---|---|---|
| `ops` registry (12) | reason_code, json_schema, model, prompt_version, component_version, component_version_model, component_version_prompt, rule, component_version_rule, pipeline_profile, pipeline_profile_version, pipeline_profile_step | |
| `ops` execution (12) | source_snapshot, pipeline_run, work_item, user_request, span, log_event, run_metric, llm_call, llm_call_example, blob, artifact, release | |
| `corpus` (10) | ruling, ruling_source_ref, publication_observation, ruling_text, segmentation, consideration, ruling_parse, ingest_issue, population, population_member | ruling_party, ruling_reference |
| `triage` (8) | assessment, assessment_reason, llm_judgement, justification, assessment_evidence, threshold, ranking, ranking_entry | |
| `gold` (3) | label, expert_review, suva_summary | split_set, split_member |
| `summ` (10) | perspective_anchor, preset, preset_version, preset_version_prompt, summary, summary_version, summary_text, summary_claim, claim_citation, verification_check | |
| `audit` (1) | change_log | |

P0 = 57 tables. Expected volumes:
- about 6,055 rulings
- considerations: 150,000 to 250,000 rows per segmentation version (*estimate*)
- assessments: one per ruling per step per run
- LLM calls: a few thousand per night
- events: 100,000 to 1,000,000 per full run (*estimate*, §11.4)

Postgres handles all of this; only `ops.log_event` needs partitioning.

---

## 7. Versioning and registry

### 7.1 Version format and bump rules

Format: **`V<major>.<minor>.<patch>`**, e.g. `V2.1.2`. "V2" names the major line. Each versioned table stores `v_major`, `v_minor`, `v_patch` (smallint, ≥ 0) and a generated `version_label`. Major 0 (`V0.x.y`) means draft: it can run in experiments, never in a release of the `default` profile.

| Bump | When | Consequence (enforced or checked) |
|---|---|---|
| **MAJOR** | the meaning of the output changes: another model (8B ↔ 70B), another question or score definition, another label set, a new major of the configuration schema | scores are not comparable: thresholds and rankings must be refitted; the trigger of §10.2 refuses a ranking that mixes majors |
| **MINOR** | same meaning, outputs may change: a rule added or removed, another few-shot pool, another truncation, prompt wording, a new minor of the configuration schema | re-measure on the labelled quarters before a release; a threshold stays valid within the same `major.minor` only |
| **PATCH** | no intended output change: logging, refactoring, speed | replaying the cache must give identical outputs: a test compares output hashes on a sample |

Every version row has `bump_kind` (`initial` \| `major` \| `minor` \| `patch`), `previous_version_id` and a non-empty `changelog`. The same scheme versions component versions, configuration schemas, rules, prompts, presets, review schemas and pipeline profiles.

### 7.2 Models

**`ops.model`** is loaded by the registry loader from `MODELS.md`, the single home of model ids (E6, G3). The SQL files contain no model id, so `tests/test_models_registry.py` stays green.

Columns:
- `model_id` (`uuid5` of the gateway id)
- `family`, `size`
- `gateway_id`, `hf_id`, `revision`
- `allowed` (the allow-list of G3)
- `source_snapshot_id`

**`ops.component_version_model`**: (`component_version_id`, `model_role`) PK, then `model_id`. Roles: `judge`, `generator`, `repair`. This gives each step its own model per role (N9).

**At run time** the judges may set `LLM_NAME` to another Apertus id (G3, D-032):
- `ops.pipeline_run.resolved_models` records the models actually resolved, per role.
- `model_override` is true when they differ from the declared ones.
- Every LLM call stores the requested and served model.
- A release built on an overridden run carries a warning in `ops.release.warnings`; it is never blocked, because the judges' run must complete (OQ-19, settled).

### 7.3 Steps and component versions

`pipeline_step` (ENUM), with the pipeline steps of the team's diagram:

| Diagram step | `pipeline_step` values |
|---|---|
| 1 Crawl + ingestion | `ingest`, `segment`, `parse` |
| 2 Layer 1 | `layer1_filter` |
| 3 Layer 2 | `layer2_judge` |
| 4 Party check + German reason | `justification` |
| 5 Ranking | `ranking` |
| 6 Summaries + verifier | `summarise`, `verify` |
| 7 `results/` with hash | `export` |

**`ops.component_version`** columns:

| Column | Notes |
|---|---|
| `component_version_id` | `uuid5('cv|' || step || '|' || version_label)` |
| `step` | |
| `name` | |
| `v_major`, `v_minor`, `v_patch`, `version_label` | UNIQUE (`step`, `v_major`, `v_minor`, `v_patch`) |
| `config_schema_id` | FK `ops.json_schema` |
| `config` | jsonb, CHECK it is an object |
| `config_sha256` | |
| `code_path`, `code_sha256` | e.g. `src/layer1/engine.py` and `src/layer1/models.py` |
| `git_commit` | |
| `status` | `draft` \| `active` \| `deprecated` \| `retired` |
| `bump_kind`, `previous_version_id`, `changelog` | |
| `created_by_actor`, `created_at` | |

Insert-only: only `status` may change, and it is audited. **`ops.component_version_prompt`**: (`component_version_id`, `prompt_role`) → `prompt_version_id`.

### 7.4 Configuration templates: the DB is agnostic, but ready

**`ops.json_schema`** columns:
- `json_schema_id` (`uuid5`)
- `subject`: `step_config` \| `rule_definition` \| `preset_config` \| `review_payload`
- `schema_code`: e.g. `layer2_judge.config`, `scope_review.payload`
- the version (V…)
- `json_schema` (jsonb, a JSON Schema draft 2020-12 document)
- `template` (jsonb: a complete example configuration, the starting point for a new version)
- `schema_sha256`, `status`, `changelog`
- UNIQUE (`schema_code`, version)

How it is enforced:
- **In the application** (mandatory): `Registry.register_component_version` validates `config` against the schema before inserting it (the Python `jsonschema` package, or the pydantic model the schema is generated from).
- **In the DB:** the FK to the schema, `jsonb_typeof(config) = 'object'`, and `config_sha256`. Validation inside Postgres needs the `pg_jsonschema` extension, which the pinned image lacks (§18).
- Result: adding or changing a configuration field is a new schema version, never a DDL change.

### 7.5 Rules

**`ops.rule`**: one rule, versioned. Columns:
- `rule_id` (`uuid5`)
- `step`, `rule_code` (e.g. `L1_KEEP_TITLE_TERM`), the version (V…)
- `kind`: `keep` \| `drop` \| `flag` \| `signal` \| `check`
- `definition` (jsonb) + `definition_schema_id` (FK `ops.json_schema`)
- `reason_code` (FK `ops.reason_code`: what the UI says when it fires)
- `description`, `status`, `changelog`
- UNIQUE (`rule_code`, version)

**`ops.component_version_rule`**: (`component_version_id`, `rule_id`) PK, `ordinal` (UNIQUE per component version), `enabled`, `params` (jsonb).

The tables that store results point to the **exact rule version** that fired: `triage.assessment_reason.rule_id`, `summ.verification_check.rule_id`.

**`ops.reason_code`** (one vocabulary for the whole DB): `code` PK, `domain` (`triage` \| `verify` \| `ingest` \| `work`), `label_de` NOT NULL, `label_fr`, `description`. It replaces the separate lookups of v0.1.

### 7.6 Pipeline profiles: "the default pipeline"

| Table | Columns |
|---|---|
| `ops.pipeline_profile` | `profile_code` PK (`default`, `experiment_8b`…), `name`, `description`, `is_default` (partial UNIQUE: exactly one), `retired_at` |
| `ops.pipeline_profile_version` | the version (V…), `status`, `changelog`, `bump_kind`; UNIQUE (`profile_code`, version) |
| `ops.pipeline_profile_step` | (`profile_version_id`, `step`) PK → `component_version_id`; trigger: the component version's `step` = `step`; a profile version with major ≥ 1 refuses a `V0.x` step |

`ops.pipeline_run.profile_version_id` is NOT NULL. A trigger checks that every assessment's `component_version_id` is the version its run's profile pins for that step. "By the default pipeline" means: the current release (`ops.release.is_current`) of the `default` profile.

### 7.7 The template set per step (illustrative; written as seed files in Phase 2)

| Step | Configuration template (keys) | Rules (initial set) |
|---|---|---|
| `ingest` | `sources.hf_bger.revision`, `windows[]` (populations to build), `twin_rule: same_date`, `columns[]` (read list; `judges`, `clerks`, `outcome`, `marked_for_publication` never in it; `legal_area` read as a rubric observation, D-072) | `ING_TWIN_SAME_DATE` |
| `segment` | `method: hf_erwaegungen \| own_splitter`, `hf_file.revision`, `min_citable_depth: 1`, `locate_offsets: true`, `expected_count_source: hf_structure`, `acceptance: {count_match_min, coverage_min}` | `SEG_COUNT_MATCH`, `SEG_COVERAGE`, `SEG_OFFSET_FOUND` |
| `parse` | `dispositive_markers{de,fr,it}`, `bench_pattern`, `outcome_patterns{…}`, `parties_markers{…}` | `PAR_OUTCOME_*` |
| `layer1_filter` | `courts{digit: {letters, rubrics}}`, `rubric_sources: [neuheiten, hf_legal_area, gegenstand_head]`, `normalise{casefold, nfkc, apostrophes, nbsp}`, `accident_terms`, `contract_terms`, `closed_rubrics` (model: `src/layer1/models.py`) | `L1_KEEP_RUBRIC`, `L1_KEEP_RUBRIC_MISSING`, `L1_KEEP_ACCIDENT_TERM`, `L1_KEEP_CONTRACT_TERM`, `L1_FLAG_CLOSED_RUBRIC`, `L1_DROP_WRONG_COURT`, `L1_DROP_WRONG_LETTER`, `L1_DROP_RUBRIC_OUT`, `L1_SIGNAL_RUBRIC_FROM_TITLE` (D-073; `docs/LAYER1.md` §6.2) |
| `layer2_judge` | `model_role: judge`, `question_prompt` (ref), `answer_tokens: [Ja, Nein]`, `top_logprobs: 20`, `text_cap: {head: 12000, tail: 2000}`, `score_mapping: p_yes_x100`, `temperature: 0`, `max_tokens: 1` | `L2_FAIL_NO_YESNO_TOKEN` |
| `justification` | `model_role`, `json_mode_cascade`, `max_tokens: 400`, `key_statement_max: 300`, `repair_attempts: 1` | `JUS_PARTY_SUVA_ACTING_ONLY_IF_PARTY`, `JUS_ACTING_PARTY_IN_BLOCK`, `JUS_EVIDENCE_IN_SET` |
| `ranking` | `threshold_policy: f2_cross_quarter_frozen`, `threshold_ref`, `tie_break`, `populations: [2026Q2_union, 2026Q2_publication]`, `top_k: [10, 30]` | `RANK_BELOW_THRESHOLD` |
| `summarise` | `model_roles{generator, repair}`, `streaming: true`, `max_tokens`, `repair_attempts: 1`; editorial choices come from the preset | `SUM_PAIR_REQUIRED` |
| `verify` | `normalisation: NFKC`, `repair_attempts: 1`, `fail_closed: true` | `V1_IDS_IN_SET`, `V2_QUOTE_VERBATIM`, `V3_NUMBERS_PRESENT`, `V4_CANONICAL_REFS`, `V5_HAS_CITATION`, `V6_ACTING_PARTY` |
| `export` | `files[]`, `hash: sha256`, `formats` | — |

### 7.8 Lifecycle and immutability

Registry rows are **insert-only**. Only `status` changes (`draft → active → deprecated → retired`), and each change is audited. Correcting a version means creating the next version. A version referenced by a run can never be deleted (FKs are `ON DELETE RESTRICT`).

---

## 8. Corpus

### 8.1 The base dataset

Built from the pinned HF files only (bger.ch Neuheiten pages add observations later, §18).

| Set | Rulings | Date quality | Population code |
|---|---|---|---|
| Decided 1 Apr to 30 Jun 2026 | 2,096 | exact | `2026Q2_decision` |
| Published 19 May to 30 Jun 2026 (HF poller) | 992 | exact | part of `2026Q2_publication` |
| First seen 1 Apr to 18 May 2026, no exact publication date | 1,068 | approximate (`scraped_at`: same day as the publication date in at least 80 % of the 3,684 rulings that have both) | part of `2026Q2_publication` |
| **Q2 union** (target) | **2,677** | flagged per row | `2026Q2_union` |
| Decided Q4/2025, Q1/2026 (labelled) | 1,931 + 2,005 | exact | `2025Q4_decision`, `2026Q1_decision` |
| Rulings of `judgements/` outside those windows | 23 | exact | `suva_reference` |

Loader rules:
- **Twins:** a `-DYYYYMMDD` row is dropped only when its base row has the same date (18 rows); 6B_920/2025 and 7B_1356/2025 are real second decisions. Every source row is kept in `corpus.ruling_source_ref`, with `is_twin`.
- **Taken from HF:** `decision_id`, `docket_number`, `decision_date`, `publication_date`, `scraped_at`, `language`, `title` (empty for 47 of the 2,096), `full_text` (present for 2,096 of 2,096), `appealed_court_raw`, `cited_decisions`, `content_hash`, `source_url`.
- **Never taken:** `judges`, `clerks` (D-038), `outcome`, `marked_for_publication` (D-011).
- **Taken as a rubric observation:** `legal_area` (empty for 1,683 of 2,096), into `corpus.subject_observation` only when filled (D-072).
- Counts go to `results/ingestion.json` and `ops.run_metric`; a mismatch fails the run (`docs/DATA.md` §10).

### 8.2 What `erwaegungen_paragraphs` is

A ruling has four parts:
1. the header: court, date, bench, parties, subject, previous instance
2. the facts
3. the **considerations** (`Erwägungen` / `Considérants`): the court's numbered reasoning, `1.`, `1.1`, `5.3.2`…
4. the operative part

HF ships `structure/erwaegungen_paragraphs.parquet` at the pinned commit (4.99 GB, refreshed weekly):
- one row per consideration: `decision_id`, `e_number` (`1`, `1.1`, `2a`, `3c/aa`), `depth`, `parent`, verbatim `text`
- reasoning without numbers is one row with `e_number = "0"`, which cannot be cited
- `structure/structure.parquet` (6 MB) holds `erwaegungen_paragraph_count` per decision, used to check completeness

Source: the dataset README, read 28 Nov; the columns are checked once the file is downloaded (DB-08).

Why it matters:
- Apertus cites only the ids we send (`c1…cn`, G1).
- The code renders `E. 5.1` / `consid. 5.1` from `e_number` (D-037).
- The verifier checks claims against the considerations.
- Long rulings are split, never cut (G4).

### 8.3 Segmentations: letting the splitter mature first

Decision (OQ-8): the HF file is downloaded locally and parsed, and the splitter is hardened on samples before it runs on the whole dataset. So the DB keeps **several segmentations per text**, each produced by a version of the `segment` step, with its quality measured.

**`corpus.segmentation`** columns:
- `segmentation_id`, `text_id`, `component_version_id` (splitter V…), `method` (`hf_erwaegungen` \| `own_splitter`)
- `status` (`ok` \| `partial` \| `failed`)
- `consideration_count`, `expected_count` (from `structure.parquet`), `coverage_ratio` (characters covered ÷ length of the considerations part), `offsets_found_ratio`
- `is_primary` (partial UNIQUE: one per text), `created_by_run_id`, `span_id`

A splitter version becomes **primary** for the corpus only when its acceptance criteria pass. The criteria are **count match ≥ 99 %** (against `structure.parquet`) and **coverage ≥ 98 %** (OQ-20, settled), written in its configuration before measuring (G10). Assessments and summaries pin the segmentation they used (`input_segmentation_id`, `source_segmentation_id`); a trigger refuses evidence or citations taken from another segmentation.

### 8.4 Tables

`uuid5(x)` = a deterministic UUID computed by the loader from the natural key (OQ-9): same ids after a rebuild and on every team machine.

| Table | Columns and rules |
|---|---|
| `corpus.ruling` | `ruling_id` (`uuid5('bger|'||docket||'|'||decision_date)`), `docket` (CHECK `^[0-9]{1,2}[A-Z]_[0-9]+/[0-9]{4}$`), `decision_date`, UNIQUE (`docket`, `decision_date`); generated `court`, `register_letter`, `filing_year`, `quarter_by_decision`; `language`; `gegenstand` (NULL when empty); `previous_instance`; `bger_url` (built by code); `origin` (`base_dataset` \| `user_added`); `created_by_run_id` |
| `corpus.ruling_source_ref` | (`source`, `external_id`) PK, `ruling_id`, `snapshot_id`, `is_twin` |
| `corpus.publication_observation` | `ruling_id`, `source` (`neuheiten` \| `hf_poller` \| `hf_first_seen`), `quality` (`exact` \| `approx_first_seen`), `observed_date`, `star`, `sachgebiet`, `snapshot_id`; UNIQUE (`ruling_id`, `source`); CHECK `hf_first_seen` ⇔ `approx_first_seen` |
| `corpus.ruling_text` | `text_id` (`uuid5(ruling, source, sha)`), `ruling_id`, `source` (`hf` \| `bger` \| `entscheidsuche`), `content` (CHECK non-blank), `content_sha256`, `char_length`, `clean_length`, `is_primary` (partial UNIQUE), `snapshot_id` |
| `corpus.subject_observation` | `observation_id`, `ruling_id`, `source` (`neuheiten` \| `hf_legal_area`), `rubric` (CHECK non-blank), `star`, `snapshot_id`; UNIQUE (`ruling_id`, `source`); written only when the source has a value (D-072) |
| `corpus.segmentation` | §8.3 |
| `corpus.consideration` | `consideration_id` (`uuid5(segmentation, ordinal)`), `segmentation_id`, `ordinal` (UNIQUE per segmentation; generated `cid = 'c' || ordinal`), `e_number`, `depth`, `parent_consideration_id`, generated `is_citable` (`depth >= 1`), `char_start` / `char_end`, `content`, `content_sha256` |
| `corpus.ruling_parse` | one row per (text, parser version): `parties_block`, `bench_size`, `operative_part`, `outcome`, `outcome_rule_id` (FK `ops.rule`), section offsets, `component_version_id`, `span_id` |
| `corpus.ingest_issue` | `ruling_id`, `reason_code` (FK `ops.reason_code`, domain `ingest`), `detail`, `run_id`, `span_id` |
| `corpus.population` | `code` UNIQUE, `quarter`, `definition` (`decision_date` \| `publication_date` \| `union` \| `reference`), `role` (`target` \| `labelled` \| `reference`), `is_delivery_default` (partial UNIQUE; D-052: `2026Q2_publication`), `manifest_sha256`, `frozen_at`, `built_by_run_id` |
| `corpus.population_member` | (`population_id`, `ruling_id`) PK, `basis` (`decision_date` \| `publication_exact` \| `publication_approx`); a trigger refuses new members once the population is frozen |
| `corpus.v_ruling` (view) | ruling + best publication date (`neuheiten` > `hf_poller`), approximation apart, `quarter_by_publication` from exact dates only, primary text stats |

---

## 9. The scope label: `in_suva_scope`

### 9.1 Values

| Value | Your word | Meaning | Written by |
|---|---|---|---|
| `potentially` | Potentially | passed layer 1, not decided yet; or the decision failed and waits for a retry | `layer1_filter`, `layer2_judge`, `justification` |
| `out_of_scope` | False | excluded, **always with a reason code** | `layer1_filter`, `ranking` |
| `in_scope` | True | score at or above the frozen F2 threshold | `ranking` |

No assessment means not assessed yet: shown as `not_assessed` in views, never stored.

### 9.2 State machine (one ruling, one run, one profile version)

```text
 not_assessed ── layer1_filter ──┬──▶ out_of_scope   (reason e.g. L1_DROP_RUBRIC_OUT; score_source 'net')
                                 └──▶ potentially ── layer2_judge ──▶ potentially, score_0_100 = 100 × P(Ja)/(P(Ja)+P(Nein))
                                                        │ failed ──▶ potentially, score_source 'failed', work item failed
                                                        ▼
                                          justification ──▶ potentially (+ key statement, evidence, party check)
                                                        ▼
                                          ranking ──┬──▶ in_scope      (score ≥ threshold)
                                                    └──▶ out_of_scope  (RANK_BELOW_THRESHOLD)
```

Invariants:
1. **CHECK:** `layer1_filter` writes only `potentially` or `out_of_scope`; `layer2_judge` and `justification` write only `potentially`; `ranking` writes `in_scope` or `out_of_scope`, or `potentially` with `score_source = 'failed'`.
2. **CHECK:** `out_of_scope` ⇒ `reason_code` NOT NULL (G5).
3. **CHECK:** `outcome = 'failed'` ⇒ `potentially` (a failure is never a negative).
4. **Release gate:** every member of the target population has a label, and no `potentially` remains unless it is listed as failed.

### 9.3 Views (never a column)

- **`triage.v_scope_pipeline`**: for each ruling, the assessment of the furthest step in the current release of the `default` profile. This is **the label** (OQ-7).
- **`triage.v_scope_current`**: the above, plus the latest expert scope review (§12.2): `pipeline_label`, `expert_verdict` (`correct` \| `incorrect` \| NULL), `expert_implied_label` (the pipeline label, flipped when the verdict is `incorrect`), `reviewed_at`. What each consumer reads is settled in §12.3.

---

## 10. Traceability per layer

### 10.1 Common envelope: `triage.assessment` (append-only)

| Column | Purpose |
|---|---|
| `assessment_id` uuid PK | |
| `run_id` FK NOT NULL | the execution (and through it, the profile version) |
| `ruling_id` FK NOT NULL | |
| `step` (`pipeline_step`) | CHECK in (`layer1_filter`, `layer2_judge`, `justification`, `ranking`) |
| `repetition_idx` smallint DEFAULT 0 | G10: 2 repetitions in measurement runs |
| `component_version_id` FK NOT NULL | exact step version (trigger: the one its profile pins) |
| `span_id` FK NOT NULL | the unit of work in the logs (§11) |
| `upstream_assessment_id` FK | the previous step's assessment (lineage) |
| `input_text_id`, `input_segmentation_id` FK | what was read |
| `input_fingerprint` char(64) NOT NULL | SHA-256 over every input: a rerun skips identical inputs (pipeline step 7) |
| `in_suva_scope` NOT NULL | §9 |
| `outcome` | `ok` \| `failed` \| `skipped` |
| `score_raw` double | native value (P(Ja), rule score) |
| `score_0_100` numeric(5,2) | CHECK 0 to 100 |
| `score_source` | `judged` \| `signals_only` \| `net` \| `failed` (D-021 point 7) |
| `reason_code` FK `ops.reason_code` | required when `out_of_scope` |
| `explanation_de` | German reason shown in the UI |
| `mode` | `LIVE` \| `REPLAY` |
| `started_at`, `finished_at` | |

UNIQUE (`run_id`, `ruling_id`, `step`, `repetition_idx`).

### 10.2 Per-step detail

| Step | Detail table | Stored, exhaustively |
|---|---|---|
| `layer1_filter` | `triage.assessment_reason` | **every** rule that fired, kept or dropped: `rule_id` (exact version), `reason_code`, `effect`, `evidence_field`, `evidence_consideration_id`, `char_start` / `char_end`, `matched_text` (≤ 300 characters); rules evaluated without firing are logged as `debug` events (§11.3) |
| `layer2_judge` | `triage.llm_judgement` (1:1) | `llm_call_id`, `prompt_version_id`, requested and served model, question language, `logprob_yes`, `logprob_no`, `p_yes`, `top_logprobs` (raw, up to 20), `yes_no_in_top`, `text_chars_total`, `text_chars_sent`, `truncation` (`head12000_tail2000`), `input_tokens` |
| `justification` | `triage.justification` (1:1) + `triage.assessment_evidence` | `llm_call_id`, `repair_llm_call_id`, `json_valid`, `key_statement` (≤ 300), number of consideration ids offered, `party_check_status` (`pass` \| `fail_suva_not_party` \| `fail_party_not_in_block` \| `not_applicable`) + `party_check_rule_id`; evidence = considerations by FK, trigger: same segmentation (G1) |
| `ranking` | `triage.threshold`, `triage.ranking`, `triage.ranking_entry` | threshold: value, metric (F2), chosen-on and reported-on populations, metrics (recall, precision, F2, hits at 30, CI), policy (D-021 point 8), `scorer_component_version_id`, `frozen_at`; ranking: (run, population, threshold, tie-break); entry: `final_score_0_100`, `rank` (UNIQUE per ranking), `above_threshold`, generated `in_top10` and `in_top30` |

**Comparability trigger:** a ranking entry is refused when its layer-2 assessment's component version does not have the same step, `v_major` and `v_minor` as the threshold's scorer version (§7.1).

### 10.3 Trace view

`triage.v_scope_trace` returns one row per (ruling, step) in the current release, with:
- the assessment and its run (git commit, mode, profile version)
- the component version (label, code hash, configuration hash, models per role)
- the reasons and their evidence
- the LLM call (served model, latency, tokens, cache hit, finish reason)
- the input text and segmentation
- the source snapshot (HF commit, file hash)
- the span (status, duration) and its number of events by level

It feeds the "show me why" panel (`GET /api/rulings/{docket}/trace`).

---

## 11. Observability: spans, events, metrics

### 11.1 Model

The model follows OpenTelemetry's vocabulary:
- **trace** = a run (`run_id`)
- **span** = a unit of work: one step on one ruling, or an operation inside it (an LLM call, a check, a repair)
- **event** = a log line inside a span
- **metric** = a counter or measure per run and step

Business rows (assessments, LLM calls, summary versions, checks) point to their span. A span points to its parent, its run, its step and its component version.

### 11.2 Tables

| Table | Columns | Notes |
|---|---|---|
| `ops.span` | `span_id` uuid PK, `run_id` FK, `parent_span_id` FK, `step`, `operation` (`layer2.judge`, `llm.call`, `verify.V3`…), `ruling_id`, `component_version_id`, `status` (`running` \| `ok` \| `error` \| `skipped` \| `cancelled`), `started_at`, `ended_at`, generated `duration_ms`, `attributes` jsonb, `error_reason_code`, `error_message` | inserted at start; **one** UPDATE allowed (closing: `status`, `ended_at`, error fields), enforced by trigger |
| `ops.log_event` | (`run_id`, `seq`, `ts`) PK, `span_id`, `ruling_id`, `step`, `level` (`debug` \| `info` \| `warning` \| `error` \| `critical`), `event_code` (dotted, §11.3), `message`, `attributes` jsonb NOT NULL DEFAULT `'{}'` | **partitioned by RANGE (`ts`), one partition per day** plus a DEFAULT partition; `seq` is the emitter's per-run counter, so reloading a JSONL file is idempotent (`ON CONFLICT DO NOTHING`); **no FK** on `span_id` (write speed, partition independence), integrity checked by a test query |
| `ops.run_metric` | (`run_id`, `step`, `metric_code`) PK, `value` numeric, `unit`, `measured_at` | `rulings_in`, `rulings_out`, `kept`, `dropped`, `llm_calls`, `llm_errors`, `tokens_in`, `latency_p95_ms`…; a step with 0 output fails the run (G6) |

Indexes:
- `log_event`: BRIN on `ts`; btree on (`run_id`, `ts`), (`ruling_id`, `ts`), (`span_id`), (`event_code`)
- `span`: (`run_id`, `step`), (`ruling_id`, `started_at`), (`parent_span_id`)

### 11.3 Event catalogue (initial; open vocabulary, convention `<step>.<object>.<verb>`)

| Step | Events |
|---|---|
| ingest | `ingest.snapshot.loaded`, `ingest.ruling.twin_dropped`, `ingest.field.excluded`, `ingest.count.mismatch` |
| segment | `segment.count.mismatch`, `segment.offset.not_found`, `segment.fallback.own_splitter`, `segment.version.promoted` |
| parse | `parse.outcome.decided`, `parse.parties.not_found` |
| layer1_filter | `layer1.rule.evaluated` (debug, every rule), `layer1.rule.fired`, `layer1.decision` |
| layer2_judge | `layer2.prompt.built` (characters, tokens, truncation), `layer2.score`, `layer2.yesno.missing` |
| LLM (any step) | `llm.request`, `llm.retry` (error class, back-off), `llm.response` (served model, finish reason), `llm.cache.hit`, `llm.model.mismatch` |
| justification | `justification.json.invalid`, `justification.repair`, `justification.party_check.failed` |
| ranking | `ranking.threshold.applied`, `ranking.population.ranked` |
| summarise and verify | `summarise.generated`, `verify.check.failed`, `verify.repair`, `verify.fail_closed` |
| export, work | `export.artifact.written` (path, hash), `work.item.failed`, `work.item.retried` |

### 11.4 Volume, partitions, retention

*Estimate:* a full run over about 6,055 rulings writes 30,000 to 50,000 spans and 100,000 to 1,000,000 events (debug included). That is small for Postgres, but it is append-heavy and grows with every run, hence the daily partitions.

`ops.ensure_log_partitions(from_date, to_date)` is called by the deploy and at run start. Retention (OQ-17, settled): every level, `debug` included, is stored and kept during the event. Afterwards, dropping `debug` partitions older than N days is a trigger-gated step (§18).

### 11.5 Redaction

Events and span attributes **never** contain:
- an API key or connection string (G13)
- a D-051 value (Suva author, staff code, intranet link)
- the name of a natural person (D-038)
- a full prompt

Prompts and raw outputs live in `ops.llm_call` / `ops.blob`; an event refers to them by id or hash. `attributes` is limited to 16 KB per row (CHECK on `pg_column_size`); larger payloads go to `ops.blob`, referenced by hash. The D-051 test (T31) also scans the exported JSONL logs.

### 11.6 Views

- `ops.v_ruling_timeline`: spans and events of one ruling across runs, in time order (the transparency timeline of the UI).
- `ops.v_run_health`: per run and step, the metrics, error rate, p95 latency and failed work items (the admin panel; a step at 0 is red).

---

## 12. Truth and expert opinion (`gold`)

### 12.1 `gold.label` (Suva's truth, append-only)

Columns:
- `label_id`
- `ruling_id` (NULL for the cantonal row: `external_title` instead, Q-28)
- `source`: `suva_relevance_list` \| `suva_summary_export`
- `in_suva_scope` boolean
- `quarter_label`
- `source_ref`: the path under `judgements/` and the row
- `snapshot_id`

**No author, staff code, job title or intranet link column exists** (D-051).

**`gold.v_label_effective`** gives Suva's list, plus `false` for every other member of a labelled population, flagged `basis = 'closed_world'` (Q-04: an assumption, shown as such).

### 12.2 `gold.expert_review` (opinions, append-only, polymorphic)

| Column | Rule |
|---|---|
| `review_id` uuid PK | |
| `target_kind` | `scope` \| `summary_version` |
| `assessment_id` FK | set exactly when `target_kind = 'scope'` (the assessment whose label the expert saw) |
| `summary_version_id` FK | set exactly when `target_kind = 'summary_version'` |
| `verdict` | `correct` \| `incorrect` (scope, V1); `validated` \| `rejected` (summary); CHECK pairs verdict and target |
| `reviewed_label` | copy of the label shown; V1: CHECK in (`in_scope`, `out_of_scope`) |
| `review_schema_id` FK `ops.json_schema` | `scope_review.payload` V1.0.0, `summary_review.payload` V1.0.0 |
| `payload` jsonb DEFAULT `'{}'` | empty in V1; ready for V2 (e.g. an expert score from 0 to 100, reasons) without DDL change |
| `actor` NOT NULL | pseudonymous handle |
| `comment` | |
| `supersedes_review_id` FK | an expert changing their mind |
| `span_id`, `created_at` | |

Inserted only through `gold.submit_review(...)` (SECURITY DEFINER), which needs `app.actor` set.

### 12.3 What an expert's "incorrect" changes (OQ-3, settled 28 Nov)

After a run, one ruling can carry three things:
1. **the default pipeline's label** (e.g. `out_of_scope`)
2. **Suva's label** (only Q4/2025 and Q1/2026; hidden for Q2)
3. **an expert's verdict** on the label shown (`correct` or `incorrect`)

The label is the pipeline's (OQ-7). What the expert's verdict changes depends on who reads it; the right-hand column is the decision:

| Consumer | Option A: the verdict is shown only | Option B: the verdict also acts | Decided |
|---|---|---|---|
| Table and ruling page | pipeline label + an "Expert: incorrect" badge | idem, plus a filter "expert says in scope" | **B** (badge always, filter available) |
| Delivered list (`results/`, export) | pipeline only | expert flips included | **A**: the scored file must be reproducible from the pipeline alone |
| Mandatory summary (§13.7) | pipeline label only | an `incorrect` on an `out_of_scope` ruling also queues a `suva_house` summary | **B, queued but not gating**: the expert said it matters, so a summary is offered; the release gate still follows the pipeline |
| Training the next version (refit, S9) | not used | verdicts become labels with `source = expert` | **B**, always tagged, never mixed into metrics measured against Suva's labels |
| Evaluation metrics | Suva's labels only | | **A**: experts are not the hidden list |

### 12.4 `gold.suva_summary` (DS5)

`docket`, `decision_date`, `ruling_id`, `ruling_language`, `text_de`, `text_fr`, `bger_url`, `source_file`, `style_observed` (computed by code), word counts. These are the only fields D-051 allows. D-031: rows derived from `judgements/` leave the DB only towards `data/derived/`.

### 12.5 Splits (P1)

`gold.split_set` (code, version, manifest SHA-256) + `gold.split_member` (`split_set_id`, `ruling_id`, `fold`, `role`: `train` \| `valid` \| `test` \| `fewshot_pool` \| `holdout`). "Q4/2025 and Q1/2026 are training and/or evaluation data" is a property of a split, not of a ruling; the frozen set `suva-ft-v3` (`docs/FINETUNE.md`) is the first entry.

---

## 13. Summaries

### 13.1 What a summary is in this project

A **Suva case-law digest** of one Federal Court ruling:
- **German and French**, each written from the ruling's source (considerations plus a fact sheet), never translated from the other (D-014). Both keep the same paragraphs and consideration references, as Suva's 55 exports do (Q-27).
- **Title line** rendered by code: `BGer-Urteil <docket> vom <date>` / `Arrêt du TF <docket> du <date>`, where the date is the decision date.
- **Body:** 1 to 8 plain paragraphs (median 3), then the bger.ch link, **never** an author line (D-051).
- **Style (Q-30):** rule statement for German-language rulings, narrative for French and Italian ones.
- **Length (D-053):** median 177 words in German and 226 in French.
- **References:** `E. x` / `consid. x`, rendered by code from consideration ids (D-037).
- **Verification:** every statement is verified (6 checks, one repair, then fail closed).
- **Graded:** our top 10 summaries (template) and the "Top 5" compared with Suva's June 2026 summaries (deck); D-047 sets the order.

### 13.2 Presets, stored in the DB

| Table | Columns |
|---|---|
| `summ.perspective_anchor` | `perspective` smallint PK (0 to 10), `label_de`, `label_fr`, `rubric_de`, `rubric_fr`, `status`. An anchor exists only once its rubric is written. |
| `summ.preset` | `preset_code` PK, `name_de`, `name_fr`, `description`, `perspective` FK `perspective_anchor`, `style` (`rule_statement` \| `narrative` \| `by_ruling_language`), `is_mandatory` (partial UNIQUE: exactly one active), `selectable` (shown in the UI), `retired_at`, `created_by_actor`, `created_at`, `updated_at` |
| `summ.preset_version` | the version (V…), `config` jsonb + `config_schema_id` (`preset_config`), `config_sha256`, `status` (one active per preset), `bump_kind`, `changelog`; UNIQUE (`preset_code`, version); insert-only |
| `summ.preset_version_prompt` | (`preset_version_id`, `language`, `prompt_role`) PK → `prompt_version_id` |

Presets are the DB's own state (OQ-11): the UI lists the selectable ones (`GET /api/presets`), and a run or a request picks one by code. Seeds start the table; every change is exported to `data/derived/authored/` (prompts may contain Suva excerpts, D-031).

### 13.3 Perspective (settled: 0 to 10, anchors 0 / 3 / 5 / 7 / 10)

| Anchor | Reader | What comes first |
|---|---|---|
| 0 | the insured person (advocate) | their rights, which arguments won or lost, what to watch for in a claim |
| 3 | insured-leaning | the same, with the court's rule stated fully |
| 5 | neutral | the court's rule and its application (= `suva_house`, §13.4) |
| 7 | insurer-leaning | consequences for claims handling, with the rule stated fully |
| 10 | the insurer (advocate) | which defence held, which practice to change |

**What a perspective may change:** which consequences come first, the paragraph order, the `practice` paragraph, vocabulary and tone.

**What it may never change:** facts, holding, outcome, numbers, cited considerations. Every claim outside `practice` is checked by the 6 checks, and the `SUM_NON_PRACTICE_INVARIANT` rule compares those claims with the `suva_house` version of the same ruling. The UI shows the perspective as a badge.

Cost: 2 calls of about 34 s per summary (measured on 27 Nov). Only `suva_house` runs in the pipeline; the other presets run on request.

### 13.4 Where `suva_house` sits on the scale (OQ-5, settled 28 Nov: option a)

`suva_house` is the graded output: it must read like Suva's 55 exports. Three options:

| Option | Meaning | Problem |
|---|---|---|
| **(a) `suva_house` is anchor 5** | the neutral anchor's rubric is "write like the 55 exports"; there is no separate neutral preset | none serious: the exports are neutral rule statements; 1 preset fewer |
| (b) `suva_house` is off the scale (NULL), with a separate neutral 5 | style and perspective are two separate things | two presets that produce almost the same text; the UI must explain the difference |
| (c) `suva_house` at 7, because Suva is an insurer | follows "who writes" | pushes the graded output away from the neutral style of the examples: a risk for the grade |

**Decided: (a).** `suva_house` is the anchor-5 preset; anchor 5's rubric is "write like the 55 exports". The other active anchors are 0, 3, 7 and 10.

### 13.5 Summaries, versions (always a pair), texts, claims

| Table | Columns and rules |
|---|---|
| `summ.summary` | `summary_id`, `ruling_id`, `preset_code`; UNIQUE (`ruling_id`, `preset_code`). Identity only. |
| `summ.summary_version` | `summary_version_id`, `summary_id`, `version_no` (UNIQUE per summary; trigger: max + 1), `origin` (`generated` \| `repaired` \| `regenerated` \| `expert_edit`), `parent_version_id`, `preset_version_id`, `component_version_id` (the `summarise` step version: code and models), `source_segmentation_id`, `creator_kind` + `creator_run_id` \| `creator_actor` (strict CHECK), `quality_status` (verifier: `draft` \| `verified` \| `flagged` \| `rejected`), `is_current` (partial UNIQUE; switch audited), `mode`, `span_id`, `created_at`. **Trigger: a version is complete only with exactly one German and one French text** (deferred constraint trigger, checked at commit). |
| `summ.summary_text` | `summary_text_id`, `summary_version_id`, `language` (UNIQUE per version), `title_line`, `body` (rendered by code from the claims), `word_count`, `paragraph_count`, `llm_call_id` (NULL only for an expert edit), `repair_llm_call_id`. Append-only. |
| `summ.summary_claim` | `claim_id`, `summary_text_id`, `ordinal`, `paragraph_no`, `section` (§13.6), `model_text` (≤ 300), `rendered_text`, `status`, `edited_from_claim_id`. Append-only. |
| `summ.claim_citation` | (`claim_id`, `consideration_id`) PK; trigger: the consideration belongs to the version's `source_segmentation_id` (G1). |
| `summ.verification_check` | `check_id`, `target_kind` (`claim` \| `text`) + `claim_id` \| `summary_text_id` (strict CHECK), `rule_id` (FK `ops.rule`, step `verify`: V1 to V6 and the perspective invariant), `status` (`pass` \| `fail` \| `not_applicable`), `detail`, `run_id`, `span_id`. Append-only. |
| `summ.v_summary_current` (view) | the current version per (ruling, preset), with both texts, claims, citations, checks, and the latest expert review (`validated` \| `rejected` \| none) |

An expert edit creates version n + 1 (`origin = 'expert_edit'`) through `summ.create_expert_version(...)`, which copies the text of the other language unchanged. Expert **validation** is a review (§12.2), not a column: the history of who validated what stays complete.

### 13.6 Claim sections and the frozen contract (OQ-12, settled 28 Nov)

When Apertus writes a summary, it returns JSON shaped by the frozen contract `SummaryCall` in `src/schemas.py`. Each claim carries a `c_section` tag, today one of `facts` \| `law` \| `outcome`. Two needs don't fit that set:
1. **The narrative style has four moves:** facts, the rule, the application of the rule to this case, the outcome. Without an `application` tag, application sentences are tagged `law`. Then the verifier and the UI can't tell "what the court says in general" from "what it decided here".
2. **Perspective presets differ only in the `practice` paragraph.** Without a `practice` tag, the invariant "everything except practice is the same as in `suva_house`" (§13.3) cannot be checked, because nothing marks which claims may differ.

**Decided:** add `application` and `practice` to the set. It is additive: every output valid today stays valid. Since `src/schemas.py` is a frozen contract, it goes through a PR the lead approves (G7). The DB's `claim_section` ENUM has the five values from the start.

### 13.7 "Every in-scope ruling must have a summary" (settled: by the default pipeline)

The view `summ.v_mandatory_summary_gaps` lists every member of the release's target population where:
- `triage.v_scope_pipeline` says `in_scope` (the default pipeline's label), and
- there is no current `suva_house` version whose `quality_status` is not `rejected`.

`ops.release` refuses `is_current = true` while that view is not empty (trigger), and `make db-test` asserts it. Expert validation is shown, but it does not gate (the gate must work overnight, without an expert). Any other ruling may have any summary.

---

## 14. Execution and operations (`ops`, `audit`)

| Table | Key columns |
|---|---|
| `ops.source_snapshot` | `snapshot_id`, `source` (`hf_bger`, `hf_erwaegungen`, `hf_structure`, `bger_neuheiten`, `judgements_workbook`, `judgements_export`, `models_md`, `team_list_2096`), `revision`, `uri`, `file_sha256`, `byte_size`, `row_count`, `retrieved_at`; UNIQUE (`source`, `revision`, `file_sha256`) |
| `ops.pipeline_run` | `run_id`, `parent_run_id`, `profile_version_id` NOT NULL, `kind` (`ingest` \| `segment` \| `layer1` \| `layer2` \| `justify` \| `rank` \| `summarise` \| `verify` \| `export` \| `refit` \| `eval` \| `full`), `mode`, `status` (`running` \| `succeeded` \| `failed` \| `partial` \| `aborted`), `git_commit`, `git_dirty`, `params` + `params_sha256`, `resolved_models` jsonb, `model_override`, `triggered_by` (`cli` \| `api` \| `ci`), `actor`, `host_label` (no personal name), `started_at`, `finished_at` |
| `ops.work_item` | (`run_id`, `ruling_id`, `step`, `target_ref`) PK, `status` (`todo` \| `running` \| `done` \| `failed` \| `skipped`), `attempts`, `last_reason_code`, `last_error`, `last_span_id`, `updated_at`. This handles resume, the overnight queue and progress. `target_ref` is the preset code for summary requests, empty otherwise. |
| `ops.llm_call` (append-only; mirrors `llm_calls.jsonl`) | `llm_call_id`, `run_id`, `span_id`, `ruling_id`, `step`, `purpose`, `language`, `prompt_version_id`, `cache_key`, `cache_hit`, `mode`, `endpoint`, `model_role`, `requested_model`, `served_model`, `served_model_header`, `params` jsonb, `repetition_idx`, `messages_sha256` (→ `ops.blob`), `raw_output`, `finish_reason`, `parsed_ok`, `parse_error`, `http_status`, `error_reason_code`, `attempt`, `input_tokens`, `output_tokens`, `cached_tokens`, `latency_ms`, `started_at`. Never the API key. |
| `ops.llm_call_example` | (`llm_call_id`, `position`), `example_kind`, `example_ruling_id` / `suva_summary_id`: proves few-shot hygiene (never the judged ruling, never a test ruling; D-021 point 8, `docs/EVAL.md` §4) |
| `ops.prompt_version` | `prompt_version_id`, `role`, the version (V…), `template_sha256`, `system_template`, `user_template`, `response_schema`, `contains_suva_material` (D-031), `changelog` |
| `ops.blob` | `sha256` PK, `media_type`, `byte_size`, `content`: prompt messages, oversized log attributes, raw pages |
| `ops.artifact` | `artifact_id`, `run_id`, `release_id`, `kind` (`ranked_csv`, `plain_list`, `summaries_md`, `ingestion_report`, `authored_export`, `log_bundle`), `path`, `sha256`, `row_count` (step 7: "results/ with hash") |
| `ops.release` | `release_id`, `profile_version_id`, `ranking_id`, `created_at`, `created_by_actor`, `notes`, `is_current` (partial UNIQUE per profile), `warnings` jsonb (e.g. `model_override`); gate trigger: §9.2 invariant 4, §13.7 |
| `audit.change_log` | `change_id` bigint identity, `occurred_at`, `table_name`, `row_pk`, `action`, `actor` (`current_setting('app.actor', true)`), `run_id` (`current_setting('app.run_id', true)`), `old_row`, `new_row`. Triggers on every mutable row: registry `status`, presets, `summary_version` (`is_current`, `quality_status`), `release`, `work_item` (status only), span closing. |

**What people write survives a rebuild:** `make db-export-authored` writes `gold.expert_review`, the expert summary versions (with their texts and claims) and the presets to `data/derived/authored/<UTC timestamp>/*.jsonl`, plus a manifest with SHA-256. It runs automatically after each expert write batch and at each release. `make db-reset` reloads the latest export.

---

## 15. SQL conventions

1. **Files:** `src/db/sql/00_extensions.sql` (extensions, schemas, ENUMs, shared functions), `10_ops_registry.sql`, `11_ops_execution.sql`, `12_ops_logs.sql` (partitioned table and partition function), `13_audit.sql`, `20_corpus.sql`, `30_triage.sql`, `40_gold.sql`, `50_summ.sql`, `60_views.sql`, `70_functions.sql` (SECURITY DEFINER write functions), `80_triggers.sql`, `85_cross_fks.sql` (foreign keys to later files), `90_roles.sql`, `95_seed_reference.sql` (reason codes, anchors, `suva_house`, V1 review payload schemas). Seeds: `src/db/seed/` (registry, reason codes, anchors), never a model id. Each file has the template's header: description, prerequisites, `Doc: docs/DB_DDL_PLANNING.md §X`.
2. **Idempotent:** `CREATE … IF NOT EXISTS`; ENUMs in `DO $$ … EXCEPTION WHEN duplicate_object …$$` blocks; loaders use `INSERT … ON CONFLICT DO NOTHING` on natural keys.
3. **Generated columns use immutable expressions only:** cast numbers to text explicitly (`'V' || v_major::text || '.' || …`), because `text || smallint` is not immutable.
4. **ENUMs** (closed sets): `lang_code`, `in_suva_scope`, `pipeline_step`, `run_mode`, `run_kind`, `run_status`, `registry_status`, `bump_kind`, `assessment_outcome`, `score_source`, `publication_source`, `publication_quality`, `text_source`, `segmentation_method`, `segmentation_status`, `outcome_kind`, `population_definition`, `population_role`, `member_basis`, `label_source`, `review_target`, `review_verdict`, `creator_kind`, `summary_version_origin`, `summary_quality`, `claim_section`, `check_status`, `work_status`, `span_status`, `log_level`, `model_role`, `rule_kind`, `schema_subject`, `summary_style`, `ruling_origin`. **Lookup tables** (open, labelled for the UI): `ops.reason_code`, `summ.perspective_anchor`.
5. **IDs:** `uuid5` for corpus and registry rows (stable across rebuilds and machines); `gen_random_uuid()` for events (runs, spans, assessments, calls, versions, reviews); `(run_id, seq)` for log events. Exports always carry natural keys (docket, decision date, version label).
6. **Roles (OQ-13, best practice):**
   - **`suva_owner`** (NOLOGIN): owns every schema and object; the deploy runs `SET ROLE suva_owner`; no application connects as owner or superuser.
   - **Groups** (NOLOGIN):
     - `suva_g_pipeline`: SELECT everywhere; INSERT on `corpus`, `triage`, `summ`, `ops` execution; UPDATE only on span closing, `work_item.status`, `summary_version` status columns, `release.is_current`
     - `suva_g_review`: EXECUTE on `gold.submit_review`, `summ.create_expert_version`, `ops.request_work`
     - `suva_g_read`: SELECT on the views
   - **Logins:** `suva_pipeline` ∈ `suva_g_pipeline`; `suva_api` ∈ `suva_g_read` + `suva_g_review`; `suva_report` ∈ `suva_g_read`.
   - **Hygiene:**
     - `REVOKE ALL ON SCHEMA public FROM PUBLIC`
     - `ALTER DEFAULT PRIVILEGES FOR ROLE suva_owner …` for future objects
     - no UPDATE or DELETE grant on append-only tables (defence in depth with the triggers)
     - `statement_timeout` and a connection limit on `suva_api`
     - SCRAM-SHA-256 passwords from the environment (never in the repo, G13); the local compose stays `trust` on an internal network with no published port
   - Expert writes go **only** through SECURITY DEFINER functions with `SET search_path` pinned, and they refuse to run without `app.actor`.
7. **Append-only:** trigger `forbid_update_delete()` plus grants on assessments and their details, thresholds, rankings, LLM calls, labels, reviews, summary texts, claims, citations, checks, log events, metrics, and registry rows (except `status`).
8. **Comments:** `COMMENT ON` every table and every non-obvious column, citing the doctrine (G1, G5, D-051…).
9. **CI (OQ-14, now):** a `db` job in `.github/workflows/ci.yml` with a `services: postgres` entry using the pinned image digest of `docker-compose.yml`. It runs `make db-reset` then `make db-test` (SQL tests in `tests/sql/` + `pytest -m db`). `make check` stays DB-free. Changes to `ci.yml` and the `Makefile`: lead's approval (G7).
10. **Excerpt** (the full SQL comes in Phase 2):

```sql
DO $$ BEGIN
  CREATE TYPE in_suva_scope AS ENUM ('in_scope', 'out_of_scope', 'potentially');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS ops.component_version (
  component_version_id uuid PRIMARY KEY,                       -- uuid5('cv|' || step || '|' || version_label), set by the registry loader
  step                 pipeline_step NOT NULL,
  name                 text NOT NULL,
  v_major              smallint NOT NULL CHECK (v_major >= 0),
  v_minor              smallint NOT NULL CHECK (v_minor >= 0),
  v_patch              smallint NOT NULL CHECK (v_patch >= 0),
  version_label        text GENERATED ALWAYS AS ('V' || v_major::text || '.' || v_minor::text || '.' || v_patch::text) STORED,
  config_schema_id     uuid NOT NULL REFERENCES ops.json_schema(json_schema_id) ON DELETE RESTRICT,
  config               jsonb NOT NULL CHECK (jsonb_typeof(config) = 'object'),   -- shape checked by the application against config_schema_id
  config_sha256        char(64) NOT NULL,
  code_path            text NOT NULL,
  code_sha256          char(64) NOT NULL,
  git_commit           char(40),
  status               registry_status NOT NULL DEFAULT 'draft',
  bump_kind            bump_kind NOT NULL,
  previous_version_id  uuid REFERENCES ops.component_version(component_version_id) ON DELETE RESTRICT,
  changelog            text NOT NULL CHECK (length(btrim(changelog)) > 0),
  created_by_actor     text,
  created_at           timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT component_version_uq UNIQUE (step, v_major, v_minor, v_patch)
);
COMMENT ON TABLE ops.component_version IS
  'One version (V<major>.<minor>.<patch>) of one pipeline step: code, configuration, models, prompts, rules. Insert-only except status. See docs/DB_DDL_PLANNING.md §7.';

CREATE TABLE IF NOT EXISTS ops.log_event (
  run_id      uuid NOT NULL,
  seq         bigint NOT NULL,
  ts          timestamptz NOT NULL,
  span_id     uuid,                                            -- no FK on purpose: write speed; checked by a test query
  ruling_id   uuid,
  step        pipeline_step,
  level       log_level NOT NULL,
  event_code  text NOT NULL CHECK (event_code ~ '^[a-z0-9_]+(\.[a-z0-9_]+){1,3}$'),
  message     text NOT NULL,
  attributes  jsonb NOT NULL DEFAULT '{}' CHECK (pg_column_size(attributes) <= 16384),
  PRIMARY KEY (run_id, seq, ts)
) PARTITION BY RANGE (ts);
```

---

## 16. Anti-patterns (forbidden)

| # | ❌ Wrong | ✅ Right |
|---|---|---|
| 1 | one `rulings` table with every fact in columns | per-source tables (§8.4) |
| 2 | `corpus.ruling.in_suva_scope` | assessments + views (§9.3) |
| 3 | one label column for pipeline, Suva and experts | `triage.assessment`, `gold.label`, `gold.expert_review` |
| 4 | `rank` or `in_top30` on the ruling or the assessment | `triage.ranking_entry` per (run, population) |
| 5 | `UPDATE triage.assessment` after a rerun | a new run writes new rows; trigger and grants refuse UPDATE |
| 6 | a timeout written as `out_of_scope` | `potentially`, `score_source = 'failed'`, work item `failed` |
| 7 | `out_of_scope` without a reason | CHECK + `reason_code` FK with a German label |
| 8 | a claim citing `"E. 5.1"` typed by the model | `summ.claim_citation` FK, same segmentation (G1) |
| 9 | `ruling.summary_de`, one column per preset | summary → version (pair) → text → claim |
| 10 | `UPDATE summ.summary_text` for an expert edit | a new version through `summ.create_expert_version` |
| 11 | a version edited in place ("V2.1.2, but fixed") | insert `V2.1.3`; only `status` changes |
| 12 | a version without a changelog or bump kind | NOT NULL `changelog`, `bump_kind` |
| 13 | configuration fields as DB columns (`layer2.top_logprobs int`) | `config` jsonb + JSON Schema template (§7.4) |
| 14 | a model id typed in SQL or in a seed | `ops.model` loaded from `MODELS.md` |
| 15 | a threshold reused across scorer majors or minors | comparability trigger (§10.2) |
| 16 | an assessment produced by a version its profile does not pin | trigger on `pipeline_profile_step` |
| 17 | debug text stored in business columns | `ops.log_event` with an `event_code` |
| 18 | a prompt or a key inside a log line | references to `ops.llm_call` / `ops.blob`; redaction rule §11.5 |
| 19 | one unpartitioned log table | daily partitions, BRIN on `ts` |
| 20 | personal-data columns (judges, clerks, Suva authors, staff codes, names of people) | excluded by design; T31 scans DB exports and logs |
| 21 | presets, reviews or edits only in a Docker volume | `make db-export-authored` |
| 22 | counters on rows | views, `ops.run_metric` |
| 23 | a first-seen date stored as the publication date | `publication_observation.quality` |
| 24 | dropping every HF `-D` row by regex | same-date twin rule |
| 25 | hard-coded windows in queries | `corpus.population_member` |
| 26 | citations taken from another splitter version | trigger: same `segmentation_id` |
| 27 | `ALTER TABLE` during the event | fresh deploy + reload |
| 28 | SQL inside stage code | `Registry`, `Store`, `Telemetry` protocols |
| 29 | the API writing tables directly | SECURITY DEFINER functions, `suva_g_review` |

---

## 17. Open questions

### 17.1 Settled (27-28 Nov)

| # | Decision |
|---|---|
| S1 | Scored on Q2/2026; Q4/2025 and Q1/2026 are training and/or evaluation data; all ingested |
| S2 | The base dataset comes from HF (pinned files); bger.ch only enriches |
| S3 | PostgreSQL (D-004) |
| OQ-1 | `in_scope` / `out_of_scope` / `potentially` |
| OQ-2 | Layer 2 gives a score from 0 to 100 (`100 × P(Ja)/(P(Ja)+P(Nein))`); the label stays `potentially` until ranking |
| OQ-4 | Perspective 0 to 10, anchors 0 / 3 / 5 / 7 / 10 with written rubrics |
| OQ-6 | A summary version is always a German + French pair |
| OQ-7 | The label is the default pipeline's; experts validate summaries and review relevance (V1: correct or incorrect) |
| OQ-8 | The HF considerations file is downloaded and parsed locally; the splitter matures on samples first; the DDL comes first and keeps versioned segmentations |
| OQ-9 | Deterministic `uuid5` for corpus and registry rows |
| OQ-10 | Full prompts and raw outputs stored in the DB |
| OQ-11 | Presets stored in the DB, selected at run time |
| OQ-13 | Roles by best practice (§15.6) |
| OQ-14 | DB tests in CI now (§15.9) |
| N9-N12 | Versions `V<major>.<minor>.<patch>` per step with their own models; configuration templates and rules, schema-agnostic DDL; first-class logs |
| OQ-3 | Expert `incorrect` (§12.3): table = badge + filter; export = pipeline only; summary = queued, not gating; refit = used, tagged `expert`; metrics = Suva's labels only |
| OQ-5 | `suva_house` is the anchor-5 preset (§13.4) |
| OQ-12 | `application` and `practice` added to the claim sections of `SummaryCall`, additive PR (G7) |
| OQ-15 | A threshold is valid for scores of the same scorer `major.minor`; patch versions are free (§7.1, §10.2) |
| OQ-16 | Step versions, rules and configuration schemas come from seed files reviewed in PRs; presets are created in the DB or the UI (§3) |
| OQ-17 | Every log level, `debug` included, is stored and kept during the event; `debug` partitions may be dropped 30 days later (§11.4) |
| OQ-18 | V1: an expert reviews only `in_scope` or `out_of_scope` labels, never `potentially` (CHECK, §12.2); V2 may allow it |
| OQ-19 | A judges' `LLM_NAME` override warns (`ops.release.warnings`), never blocks (§7.2) |
| OQ-20 | Splitter promotion: count match ≥ 99 %, coverage ≥ 98 %, written before measuring (§8.3) |

### 17.2 Still open

None in this file. Every new question goes to `docs/DECISIONS.md` §2 as `OPEN` (AGENTS.md §2.5).

### 17.3 Project questions this design keeps open (AGENTS.md §2.3)

| Question | How the design keeps it open |
|---|---|
| D-050 | populations are data |
| D-052 | `is_delivery_default` marks one population |
| D-046 | threshold and top-30 cut, both in `ranking_entry` |
| D-021 points 2 and 7 | layer 1 stores its reasons; `score_source` keeps the failure path |
| D-047 | the order of work items |
| Q-30, Q-27 | preset configuration |
| D-031 | Suva-derived rows and prompts leave the DB only towards `data/derived/` |
| D-033 | no search column in P0 |
| Q-23 | the file stores work without a DB |

---

## 18. Further considerations (activation triggers)

| Topic | Trigger |
|---|---|
| Neuheiten observations (exact publication dates before 19 May 2026, star, Sachgebiet) | bger.ch answers an ordinary browser at human pace |
| `corpus.ruling_party`, `corpus.ruling_reference` (institutions as parties; canonical article, BGE and docket ids, or HF `graph/statute_references.parquet`) | work on the step-4 party check or on verifier check V4 starts |
| Publication-date populations of Q4/2025 and Q1/2026 | Suva answers Q-02 with "publication date" |
| JSON Schema validation inside Postgres (`pg_jsonschema`) | the image is rebuilt with the extension, or a second writer bypasses the application |
| Full-text search (`tsvector` per language) and `pgvector` | D-033 settled on (b), (c) or (d), after the 5 UI must-haves pass end to end |
| Materialised views for `v_scope_current` and `v_ruling_timeline` | UI p95 above 300 ms |
| Log retention job (detach and drop `debug` partitions) | the event is over, or `ops.log_event` exceeds 10 GB |
| Partitioning `ops.llm_call` | above 1 million rows |
| Export of logs to an external collector (OpenTelemetry) | deployment at Suva (target architecture a or c) |
| Row-level security per expert | more than one expert account |
| Expert scope review V2 (a score from 0 to 100 in `payload`) | V1 verdicts collected and the UI ready |
| Azure Database for PostgreSQL | the report's section 2 is drafted (D-049) |
| Cantonal rulings | Suva says the hold-out includes them (Q-28) |

---

## 19. Delivery plan

### 19.1 Template phases

| Phase | Here | Exit gate |
|---|---|---|
| 0 Design draft | this file | §17.2 answered: **done 28 Nov 01:20 CET** |
| 1 Doctrine freeze | D-lines in `docs/DECISIONS.md` (PR), `DB-NN` below, memory note | lead approves: **D-061 to D-071 recorded 28 Nov, branch `platform/db-ddl`** |
| 2 SQL/schema | `src/db/sql/*.sql`, `src/db/seed/`, `tests/sql/*.sql`, `src/db/deploy.py`, `make db-reset` / `db-test` / `db-export-authored`, CI `db` job | fresh deploy green locally and in CI; counts match: **local green 28 Nov 02:40 CET (deploy twice, reset, 8 SQL test files, 2 mutations caught); CI job added, not run yet** |
| 3 Docs sync | `docs/ARCHITECTURE.md` §3 and §5, `docs/DATA.md` §10, `src/schemas.py`, `docs/agents/crawl.md`, `triage.md`, `summarise.md`, `ui.md` point here | one place per fact |
| 4 Deploy gate | user validates the final SQL | explicit OK |
| 5 Implementation | protocols, loaders, step writers, API reads and writes | the 3-real-ruling test (G6) |
| 6 Validation | `docs/RUNBOOK_DB.md`: resume, diagnostic queries, rebuild, partition maintenance | overnight run resumes after a kill |

### 19.2 Work items

| Id | Title | Depends on | Done when |
|---|---|---|---|
| DB-01 ✅ | `00_extensions.sql`: schemas, ENUMs, shared functions | §17.2 | fresh deploy passes |
| DB-02 ✅ | Registry tables + reference seeds (`95_seed_reference.sql`: reason codes with German and French labels, perspective anchors as drafts, `suva_house`, V1 review payload schemas) | DB-01 | done; the step seeds (filter E and verifier rules, `default` profile) are written by the registry loader, DB-10 |
| DB-03 ✅ | Execution and log tables (spans, partitioned events, metrics, LLM calls, work items, artifacts, releases, blobs) + partition function | DB-01 | 1 million synthetic events load and query by ruling in < 1 s: **measured 28 Nov: load 7.4 s, query by ruling 1 ms (index scan across day partitions), PG 17 under amd64 emulation on the lead's Mac** |
| DB-04 ✅ | `corpus` tables + `v_ruling` | DB-02 | twin rule and population freeze tested |
| DB-05 ✅ | `triage` tables, scope views, trace view, comparability trigger | DB-04 | §9.2 invariants tested |
| DB-06 ✅ | `gold` tables, `submit_review`, `v_label_effective` | DB-04 | closed-world flag and review pairing tested |
| DB-07 ✅ | `summ` tables, pair trigger, `create_expert_version`, gap view, release gate | DB-05 | gate refuses a release with a gap; a version without its pair fails at commit |
| DB-08 ✅ | Roles and grants (`90_roles.sql`) | DB-01..07 | API login cannot UPDATE an assessment (test) |
| DB-09 | CI `db` job | DB-01..08 | green on a PR (job written 28 Nov; first run on the PR) |
| DB-10 (in part) | `Registry`, `Store`, `Telemetry` protocols; file, Postgres and tee implementations; registry loader for the seed files of §7.7 (models from `MODELS.md`) | DB-09 | unit tests with a declared fake |
| DB-11 ✅ (HF bger; structure with DB-12) | Base dataset loader (HF bger, structure) | DB-10 | counts of §8.1 reproduced |
| DB-12 | Splitter track: download the 4.99 GB file, segmentation V0.x on samples, acceptance criteria, promotion to V1.0.0 | DB-11 | criteria of OQ-20 met, written before measuring |
| DB-13 ✅ | Gold loader (`judgements/`, D-051 fields dropped) | DB-10 | 59 + 1 rows, 55 summaries, T31 green |
| DB-14 (layer 1 ✅) | Step writers: layer 1, layer 2, justification, ranking, export | DB-11, DB-12 | every assessment has a span and its pinned version |
| DB-15 | Summary writer + verifier writer | DB-14 | gap view empty for the release |
| DB-16 | API reads and writes on views and functions | DB-07, DB-08 | 5 must-haves + reviews + timeline read the DB |
| DB-17 | Authored export and reload | DB-16 | a rebuild keeps reviews, edits and presets |

### 19.3 Critical path and time (*estimates*)

```text
T-0  §17.2 answered (done); Phase 1 PR with the D-lines of §21 (20 min)
T-1  DB-01..08 DDL + SQL tests (3 to 4 h)          ║ in parallel: download of the HF considerations file (7 to 35 min, depending on the line)
T-2  DB-09 CI job (30 min) → DB-10 protocols (1.5 h)  ║ in parallel: DB-12 splitter on samples (2 to 4 h, depends on the mismatch rate)
T-3  DB-11 + DB-13 loaders (1.5 to 2 h)
T-4  DB-14 writers (2 h) → DB-15 summaries (1.5 h) → DB-16 API (2 h)
```

**Hackathon cut:** the scored output (Q2 ranked list + summaries) is produced by the steps into files, whatever the DB's state. If time runs short before feature freeze (Sat 12:00), the DB is filled from those files in one pass, and the UI reads it. Nothing scored waits for the DB.

---

## 20. References

- The seven-phase feature method (§1.4); its source document is kept outside the repo (D-018).
- `docs/ARCHITECTURE.md` §1 to §4; `docs/DATA.md` §1, §3, §6, §10; `docs/SUVA_DATA.md` §3, §4.
- `docs/TIPS_LAYER1_FILTER_HANDOFF.md` and `experiments/finetune/filtre_couche1/filtre_e.py` (filter E rules); `docs/FINETUNE.md` (layer-2 scorer, `suva-ft-v3`).
- `docs/agents/ui.md` (must-haves, corrections); `MODELS.md` (model ids, allow-list); `tests/test_models_registry.py`.
- HF `voilaj/swiss-caselaw` README, section "`structure/` files" (read 28 Nov 2026, commit `35b17aa9…`).
- `tmp/audits/audit-data-layer-2026-11-27.md` (git-ignored): evidence for contradictions K1 to K11.

---

## 21. Phase 1: D-lines to record in `docs/DECISIONS.md`

**Recorded in `docs/DECISIONS.md` §1 on 28 Nov (branch `platform/db-ddl`).** D-058 is reserved (tool-calling). The layer-2 baseline, numbered D-060 on its branch, landed as D-074 (PR #38); D-060 is left to the layer-1 gate proposal (PR #36). Each row points here; the plan stays the single home of the detail.

| ID | Date | Decision | Status | Basis | Revisit if |
|---|---|---|---|---|---|
| D-061 | 2026-11-28 | **Data layer.** PostgreSQL 17 (D-004) in 6 schemas (`corpus`, `triage`, `gold`, `summ`, `ops`, `audit`). Committed files are the truth and the DB is rebuilt from them (fresh deploy, no ALTER); state written by people (expert reviews, expert edits, presets) is exported to `data/derived/authored/`. The scored Q2 output never waits for the DB. Detail: `docs/DB_DDL_PLANNING.md` §1-§6. | DECIDED | lead, 28 Nov; audit of 27 Nov | the judges cannot run Docker (Q-23) |
| D-062 | 2026-11-28 | **Base dataset from pinned HF files:** Q2/2026 union (2,677), Q4/2025 (1,931) and Q1/2026 (2,005) by decision date, and the 23 Q3/2025 rulings of `judgements/`; same-date twin rule; `judges`, `clerks`, `legal_area`, `outcome`, `marked_for_publication` never ingested. Both date readings kept (D-050 stays open). §8.1. | DECIDED | measured on HF commit `35b17aa9…`, 28 Nov | a newer HF commit is pinned |
| D-063 | 2026-11-28 | **Scope label** `in_suva_scope` ∈ {`in_scope`, `out_of_scope`, `potentially`}, written per step as append-only assessments: layer 1 → `potentially` \| `out_of_scope`; layer 2 → a score 0-100 = 100 × P(Ja)/(P(Ja)+P(Nein)), label stays `potentially`; ranking → `in_scope` \| `out_of_scope` at the frozen threshold; a failure stays `potentially`; every `out_of_scope` has a reason code (G5). The label shown and used is the default pipeline's, read through a view, never a column. §9-§10. | DECIDED | lead, 28 Nov | D-021 settles another score form |
| D-064 | 2026-11-28 | **Versions per step:** `V<major>.<minor>.<patch>` for each step, rule, configuration schema, prompt, preset and pipeline profile; models bound per step and role (ids loaded from `MODELS.md`); configurations are `jsonb` checked by the application against versioned JSON Schema templates (DDL agnostic to their shape); versioned rules; the `default` profile pins one version per step. MAJOR = outputs not comparable; MINOR = re-measure; PATCH = identical outputs. A threshold is valid for the same scorer `major.minor`. A judges' `LLM_NAME` override warns, never blocks. §7. | DECIDED | lead, 28 Nov | n/a |
| D-065 | 2026-11-28 | **Logs as data:** spans, daily-partitioned events and metrics per run; every assessment, LLM call and summary links to its span; no key, prompt, D-051 value or person's name in a log line; every level kept during the event. §11. | DECIDED | lead, 28 Nov | `ops.log_event` above 10 GB |
| D-066 | 2026-11-28 | **Expert reviews**, append-only and kept apart from the pipeline's label: scope review V1 `correct` \| `incorrect` (only on `in_scope` or `out_of_scope`), summary review `validated` \| `rejected`; payload versioned for V2. An `incorrect` shows a badge and a filter, queues a `suva_house` summary without gating, feeds the next version's training tagged `expert`; it never changes the delivered list or the metrics against Suva's labels. §12. | DECIDED | lead, 28 Nov | Suva asks for expert overrides in the delivered list |
| D-067 | 2026-11-28 | **Summaries:** (ruling, preset) → versions, each always a German + French pair → texts → claims → citations (FK to considerations of the same segmentation, G1) → verifier checks. Every in-scope ruling of the default pipeline must have a current `suva_house` version (release gate); any ruling may have any preset. §13.5, §13.7. | DECIDED | lead, 28 Nov | Q-17 changes the graded set |
| D-068 | 2026-11-28 | **Presets in the DB**, selected at run time. Perspective 0 (insured person) to 10 (insurer), active anchors 0 / 3 / 5 / 7 / 10 with written rubrics; `suva_house` is anchor 5 and the mandatory preset; a perspective changes emphasis and the `practice` paragraph, never facts, holding, outcome or citations. §13.2-§13.4. | DECIDED | lead, 28 Nov | Q-30 or Suva feedback on style |
| D-069 | 2026-11-28 | **`SummaryCall` claim sections** gain `application` and `practice` (additive change to the frozen contract in `src/schemas.py`, its own PR). §13.6. | DECIDED | lead, 28 Nov | n/a |
| D-070 | 2026-11-28 | **Considerations:** HF `erwaegungen_paragraphs` (4.99 GB) downloaded and parsed locally; segmentations are versioned per splitter version; a version becomes primary at count match ≥ 99 % and coverage ≥ 98 %, criteria written before measuring (G10). §8.2-§8.3. | DECIDED | lead, 28 Nov | the HF file disappears or changes schema |
| D-071 | 2026-11-28 | **SQL conventions:** `uuid5` ids for corpus and registry rows; prompts and raw outputs stored in the DB; least-privilege roles (owner that never logs in, three groups, expert writes only through SECURITY DEFINER functions); append-only by trigger and grants; DB tests in CI (`db` job, pinned image). §15. | DECIDED | lead, 28 Nov | n/a |
