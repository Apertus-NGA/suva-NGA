# suva-NGA data catalog: layers 1 and 2, layer 3 preview

> **Status: measured snapshot, 28 Nov 2026, 10:40 CET, on `main` @ `14caaba`.** **Amended 28 Nov 10:53 CET** for layer 2's DDL-1, DDL-2 and replay policy (branch `triage/layer2-ddl`); counts unchanged. Owner: `lead`. Readers: whoever builds the UI or the API, human or agent. Out of date after any change to `src/db/sql/`, to the ingest, to layer 1 or layer 2, or when layer 3 or the ranking lands: regenerate it then.
> **DDL changes after this snapshot, with their effect on an API contract:** `docs/DDL_CHANGES.md` (none in a table, a column or a view's columns as of 28 Nov, PR #51).

An exhaustive, raw list of the data that exists. It makes no recommendation and no design decision.

| Part | State at this commit |
|---|---|
| Ingest (rulings, texts, dates, populations) | implemented, filled |
| Layer 1 (deterministic pre-filter) | implemented, filled |
| Layer 2 (Apertus relevance judge) | implemented, filled |
| Ranking (threshold, top 30, release, export) | schema only, **empty** |
| Layer 3 (summaries) | schema only, **empty**. **Section 13 is a preview: subject to change.** |
| HTTP API | `src/api/`, `make serve` (`docs/API.md`, D-092), added after this snapshot |

## 0. How this was produced

- **Code and schema:** `origin/main` @ `14caaba` (PR #45, layer 2 merged into main), DDL `src/db/sql/` (15 files).
- **Database:** a fresh PostgreSQL 17, built with that commit's own commands:
  - `db-deploy`, then `db-registry`;
  - `ingest base` on the pinned Hugging Face file `voilaj/swiss-caselaw`, revision `35b17aa9`;
  - `ingest gold` on `judgements/`;
  - `layer1 run --profile default` (profile `default` V0.3.0, which pins `layer1_filter` V1.1.0);
  - `layer2 run` in **REPLAY** mode on the populations `2025Q4_decision`, `2026Q1_decision` and `2026Q2_union`: 912 rulings judged, 0 failures.
- **Counts:** every count here comes from that database. A database built another way (a live run, another profile, other populations) has other counts but the same shapes.
- **Generated sections:** the catalog of every column (Appendix B) and the enums (Appendix A) come from PostgreSQL's own catalog, with each column's comment.
- **Repo rules:** this file holds no Suva label per docket (D-031) and no author field from `judgements/` (D-051).

## 1. Facts to know before reading the rest

1. **Schemas.** All data is in PostgreSQL, in 6 schemas:
   - `corpus`: rulings, texts, dates, populations;
   - `triage`: layer 1 and layer 2 assessments, ranking;
   - `gold`: Suva's labels, expert reviews;
   - `summ`: layer 3;
   - `ops`: runs, spans, events, metrics, LLM calls, registry of versions;
   - `audit`: change log.

   There are 58 tables and 15 views.
2. **Ids.** Every id is a UUID. A ruling's natural key is `(docket, decision_date)`, unique (`corpus.ruling.ruling_key_uq`). A docket looks like `8C_691/2024`.
3. **The frontend on PR #42 uses another data layer.** That frontend (`src/web/` on branch `handoff/components`) calls a FastAPI (`src/suva_app/`). That API reads `db/migrations/*.sql`: `public.rulings`, `predictions`, `summaries`, `summary_events`, with integer ids. None of those tables exist in this data layer.
4. **Labels.** The pipeline's label per ruling is `ops.in_suva_scope` = `in_scope | out_of_scope | potentially`.
   - Layer 1 writes `out_of_scope` or `potentially`.
   - Layer 2 always writes `potentially` and adds a score.
   - Only the ranking step writes `in_scope`. It is not built, so **no ruling is `in_scope` in this snapshot**.
5. **Two scores on a layer-2 row.** `score_raw` is the logit, ln P(Ja) − ln P(Nein): 912 distinct values for 912 rulings. `score_0_100` is `numeric(5,2)` = 100 × P(Ja)/(P(Ja)+P(Nein)): 114 distinct values, and 189 rulings sit exactly at 100.00.
6. **Explanations.** Every assessment row carries a German explanation, `explanation_de`. Layer 1 and layer 2 each write one per ruling they assess.
7. **Dates.**
   - `decision_date` is always present.
   - An exact `publication_date` exists for 1,435 rulings. For 4,620 rulings, `publication_date_approx` holds the date the ruling was first seen in the HF dataset instead.
   - `quarter_by_publication` is filled only when the publication date is exact.
8. **Always-empty columns.** The columns `star` (BGE candidate) and `sachgebiet` exist, but they are empty for every ruling, because the bger.ch Neuheiten lists are not fed. `corpus.ruling.gegenstand` (the subject line) is filled for 6,007 of 6,055 rulings.
9. **No considerations yet.** `corpus.segmentation` and `corpus.consideration` are empty, so no consideration ids, `consideration_count` or `clean_length` exist.
10. **Expert writes.** Expert reviews and UI requests are empty tables. Their write functions exist (section 11).
11. **Suva's summary texts.** `gold.suva_summary` (Suva's own DE and FR summary texts) is empty: no loader writes it at this commit. `gold.label` holds the 55 summary exports as labels only.
12. **LIVE / REPLAY.** Every assessment and every LLM call carries `mode` = `LIVE | REPLAY`. Layer 1 is code only and records `LIVE`.

## 2. Where each step writes

```text
HF parquet (pinned) ──ingest──► corpus.ruling · ruling_text · ruling_source_ref · publication_observation
                               · subject_observation · population · population_member · ingest_exclusion
judgements/ ──ingest gold──►    gold.label                                  (gold.suva_summary: no loader)
db-registry ──►                 ops.component_version · rule · model · prompt_version · pipeline_profile* · json_schema
layer 1 (code) ──►              triage.assessment (step layer1_filter, 1 row per ruling)
                               · triage.assessment_reason (1 row per rule per ruling = the rule ledger)
layer 2 (Apertus 8B) ──►        triage.assessment (step layer2_judge, upstream_assessment_id → the layer-1 row)
                               · triage.llm_judgement · ops.llm_call · ops.blob (exact messages)
every step ──►                  ops.pipeline_run · ops.span · ops.log_event · ops.run_metric · audit.change_log
ranking (NOT BUILT) ──►         triage.threshold · ranking · ranking_entry · ops.release   → triage.v_export_ranked
layer 3 (NOT BUILT) ──►         summ.summary · summary_version · summary_text · summary_claim · claim_citation
                               · verification_check                                     → summ.v_summary_current
UI writes (functions) ──►       gold.expert_review · summ.summary_version (expert edit) · ops.user_request
```

## 3. Every relation, its writer and its state

`rows` = rows in this snapshot. A view's writer is `view`.

| Relation | Kind | Written by | Rows | Comment |
|---|---|---|---:|---|
| `audit.change_log` | table | triggers, on every audited write | 103 | Change log of mutable rows. actor and run_id come from the session settings app.actor and app.run_id. Append-only. |
| `corpus.consideration` | table | no writer yet (segment step not built) | 0 | One consideration (Erwägung). cid c1..cn is what Apertus sees and may cite (G1); e_number is the court's numbering, rendered E. x / consid. x by code (D-037). e_number "0" = unnumbered reasoning, not citable. Id = uuid5('consideration\|<segmentation_id>\|<ordi |
| `corpus.ingest_exclusion` | table | ingest | 188,811 | Every row of a source file that was NOT loaded, with its reason (G5, F-04): OUT_OF_WINDOW (in no population window), ING_TWIN_SAME_DATE (a same-date duplicate row that is not a source ref: its base row is not loaded, detail.base_reason naming why; or its base  |
| `corpus.ingest_issue` | table | ingest (none recorded here) | 0 | A counted, auditable reason for a gap (no text, considerations missing, count mismatch, publication unknown...): G5. Append-only. |
| `corpus.population` | table | ingest | 6 | A set of rulings: 2026Q2_union (target), 2026Q2_decision, 2026Q2_publication (delivery default, D-052), 2025Q4_decision, 2026Q1_decision (labelled), suva_reference. Both date readings coexist (D-050). Id = uuid5('population\|<code>'). Frozen = no new member. |
| `corpus.population_member` | table | ingest | 10,792 | Membership and why (decision date, exact or approximate publication date). Append-only; refused once the population is frozen. |
| `corpus.publication_observation` | table | ingest (HF dates; the Neuheiten source is not fed) | 6,055 | What a source says about the publication date. Exact only from a Neuheiten page (ours, or HF's poller from 19 May 2026); a first-seen date is an approximation, never a publication date (D-050). Append-only. |
| `corpus.ruling` | table | ingest | 6,055 | Identity of one Federal Court decision. Key (docket, decision_date): one docket can hold several decisions. Id = uuid5('bger\|<docket>\|<YYYY-MM-DD>'), set or checked by trigger. docs/DB_DDL_PLANNING.md §8.4. |
| `corpus.ruling_parse` | table | no writer yet (parse step not built) | 0 | Parse of one text by one parser version: parties block, bench size, operative part, outcome (taken by code from the operative part). Names of natural persons are never extracted (D-038). Append-only. |
| `corpus.ruling_source_ref` | table | ingest | 6,072 | Every source row behind a ruling (hf_decision_id, aza_id, team_list_2096), twins included, per snapshot: an HF -DYYYYMMDD row is a twin only when its base row has the same date. One row per (snapshot, source, external_id): a new revision of the file records th |
| `corpus.ruling_text` | table | ingest | 6,055 | Text versions of a ruling. A second text (e.g. a bger.ch fidelity sample) is a new row, never an overwrite. content_sha256 is checked by trigger. Id = uuid5('text\|<ruling_id>\|<source>\|<content_sha256>'). Only is_primary may change. |
| `corpus.segmentation` | table | no writer yet (segment step not built) | 0 | One splitting of a text into considerations, by one splitter version, with its quality. The splitter matures on samples; a version becomes primary at count match >= 99 % and coverage >= 98 %, written before measuring (D-070). Id = uuid5('segmentation\|<text_id |
| `corpus.subject_observation` | table | ingest (HF legal_area) | 4,327 | The matter rubric (Sachgebiet) a source states: the Neuheiten page (authoritative, with the publication star) or HF legal_area (empty for most Q2/2026 rulings). Layer 1 reads neuheiten > hf_legal_area > the head of gegenstand, and records which one it used (D- |
| `corpus.v_ingest_closure` | view | view | 1 | Every row of a source file accounted for (F-04, G5), per snapshot that has source refs or exclusions: closure_ok = row_count = loaded refs (base + twins) + exclusions. Source refs are kept per snapshot, so a new revision of a file closes on its own, the rows a |
| `corpus.v_ruling` | view | view | 6,055 | Ruling with its best publication date (Neuheiten > HF poller), the approximation kept apart, quarter_by_publication from exact dates only (D-050), primary text and segmentation. |
| `gold.expert_review` | table | function gold.submit_review (none yet) | 0 | Expert opinions, append-only and apart from the pipeline's label (D-066, D-093). Scope review: relevant \| not_relevant = the expert's own label on any pipeline label (potentially included); correct \| incorrect = the V1 relative verdict, only on in_scope or out_of_scope. Summary review: validated \| rejected. withdrawn (both kinds) supersedes the review it takes back, of the same target and never a withdrawal; the target then has no expert opinion until a new review. reviewed_label = the label the expert saw (copied from the assessment); payload follows review_schema_id (scope_review.payload V1.1.0: what the expert saw, shown_status and shown scores). Inserted only through gold.submit_review(). actor is a pseudonymous handle (G13).|
| `gold.label` | table | ingest gold | 115 | Suva's truth: a row of its relevance list or one of its 55 exports. external_title = the cantonal row (Q-28), which has no Federal Court ruling. Append-only. Negatives are a view (closed world, Q-04), never stored. |
| `gold.suva_summary` | table | no loader at this commit | 0 | Suva's 55 human summaries, parsed (DS5): only docket, dates, Text DE, Text FR and the bger.ch link (D-051). Id = uuid5('suva_summary\|<source_file>'). Append-only. |
| `gold.v_expert_review_current` | view | view | 0 | The latest non-superseded review per target. |
| `gold.v_label_effective` | view | view | 3,936 | Suva's labels on the labelled populations; every unlisted member is false with basis closed_world (Q-04: an assumption, shown as such). has_suva_summary marks the must-hit subset. |
| `ops.artifact` | table | no writer yet | 0 | Files a run wrote, with their SHA-256 (pipeline step 7: results/ with hash). The export endpoint must equal the hashed file. Append-only. |
| `ops.blob` | table | layer 2 (exact messages sent to Apertus) | 912 | Content-addressed payloads: prompt messages, oversized log attributes, raw pages. Insert with ON CONFLICT DO NOTHING. Append-only. |
| `ops.component_version` | table | db-registry | 5 | One version (V<major>.<minor>.<patch>) of one pipeline step: code hash, configuration (jsonb, shape checked by the application against config_schema_id), models, prompts, rules, and the decision and validation file that approved it. MAJOR = outputs not compara |
| `ops.component_version_model` | table | db-registry | 1 | The model each step version declares per role (N9). The run records the models actually resolved (judges may set LLM_NAME). docs/DB_DDL_PLANNING.md §7.2. |
| `ops.component_version_prompt` | table | db-registry | 1 | The prompt versions a step version uses, per prompt role. Append-only. |
| `ops.component_version_rule` | table | db-registry | 29 | The rules a step version applies, in order, with their parameters. The rule must belong to the same step (trigger). Append-only, and sealed once an assessment uses the version or a profile pins it: a new rule is a new version, so a certified rule ledger never  |
| `ops.json_schema` | table | db-registry | 6 | Versioned JSON Schema templates for step configurations, rule definitions, preset configurations and review payloads. template is a complete example: the starting point of a new version. Id = uuid5('json_schema\|<code>\|<major>\|<minor>\|<patch>'). docs/DB_DDL |
| `ops.llm_call` | table | layer 2 | 912 | Every LLM call, invalid outputs included; mirrors data/derived/llm/llm_calls.jsonl. Never the API key (G13). Requested and served model on every row (G3). Append-only. docs/DB_DDL_PLANNING.md §14. |
| `ops.llm_call_example` | table | no writer yet | 0 | The few-shot examples a call carried: proves the judged ruling and the test rulings were never examples (D-021 point 8). Append-only. |
| `ops.log_event` | partitioned | every step | 8,802 | Log lines: event_code <step>.<object>.<verb> (catalogue in docs/DB_DDL_PLANNING.md §11.3). Never a key, a full prompt, a D-051 value or a person's name (§11.5); payloads over 16 KB go to ops.blob, referenced by hash. Every level is kept during the event (D-065 |
| `ops.model` | table | db-registry | 2 | Models, loaded from MODELS.md (the single home of model ids, E6, G3); never typed in SQL. allowed = on the G3 allow-list. Id = uuid5('model\|<gateway_id>'). docs/DB_DDL_PLANNING.md §7.2. |
| `ops.pipeline_profile` | table | db-registry | 3 | Named pipelines. Exactly one active default: "the default pipeline" whose label is shown and used (D-063). docs/DB_DDL_PLANNING.md §7.6. |
| `ops.pipeline_profile_step` | table | db-registry | 11 | The step versions a profile version pins. Every assessment must come from the version its run's profile pins (trigger in 80_triggers.sql). |
| `ops.pipeline_profile_version` | table | db-registry | 5 | A version of a profile, and the decision that approved it. Id = uuid5('profile\|<profile_code>\|<major>\|<minor>\|<patch>'). A version with major >= 1 refuses any V0.x step (trigger). |
| `ops.pipeline_run` | table | every step | 4 | One execution (= one trace). Pinned to a profile version. resolved_models = the models actually used per role; model_override = the judges' LLM_NAME differs from the declared models (a release warns, never blocks, D-064). Only status, finished_at, error_summar |
| `ops.prompt_version` | table | db-registry | 1 | Versioned prompts. contains_suva_material = built from judgements/: its exports stay in data/derived/ while D-031 is open. Id = uuid5('prompt\|<role>\|<major>\|<minor>\|<patch>'). docs/DB_DDL_PLANNING.md §14. |
| `ops.reason_code` | table | seed (95_seed_reference.sql) | 48 | One vocabulary of reasons for the whole DB (triage drops, verifier checks, ingest issues, work errors). The UI shows label_de, so a lawyer reads a sentence, not a code (G5). docs/DB_DDL_PLANNING.md §7.5. |
| `ops.release` | table | no writer yet (ranking not built) | 0 | What is published: a ranking of a profile version. The current release of the default profile carries "the label" (D-063). Becoming current is gated: every target member labelled, no unexplained potentially, no missing mandatory summary (trigger). warnings rec |
| `ops.rule` | table | db-registry | 11 | Versioned rules (layer-1 keep/drop rules, party checks, verifier checks...). definition is jsonb, its shape versioned in ops.json_schema. Results point to the exact rule version that fired. Id = uuid5('rule\|<rule_code>\|<major>\|<minor>\|<patch>'). docs/DB_DD |
| `ops.run_metric` | table | every step | 56 | Counters and measures per run and step (rulings_in, kept, dropped, llm_calls, latency_p95_ms...). A step with 0 output fails the run (G6). Append-only. |
| `ops.source_snapshot` | table | ingest, db-registry | 4 | Every input file a load read: source, revision (HF commit), hash, size. The root of every lineage. Append-only. |
| `ops.span` | table | every step | 7,883 | A unit of work (one step on one ruling, or an operation inside it: an LLM call, a check). Inserted at start, closed once (trigger). Business rows point to their span. No key, prompt, D-051 value or person's name in attributes (§11.5). docs/DB_DDL_PLANNING.md § |
| `ops.user_request` | table | function ops.submit_request (none yet) | 0 | Requests from the UI: "add another judgement" (D-015) by docket or bger.ch link, or a summary of any ruling under any preset. Created only through ops.submit_request(); the pipeline accepts them into a run. |
| `ops.v_profile` | view | view | 11 | Which step versions, models and rules each profile version pins (transparency panel). |
| `ops.v_ruling_timeline` | view | view | 16,670 | Spans and events of a ruling across runs; order by ts. The transparency timeline of the UI (D-065). |
| `ops.v_run_health` | view | view | 4 | Admin panel: per run and step, spans, errors, p95 duration, failed work items, metrics. A step at 0 is red (G6). |
| `ops.work_item` | table | no writer yet | 0 | The queue of a run: resume ("rerun the same command"), the overnight run, progress bars. A circuit breaker leaves items todo, never failed. |
| `summ.claim_citation` | table | no writer yet (layer 3) | 0 | Considerations a claim cites, by FK. Trigger: a citable consideration of the version's source segmentation (G1). Append-only. |
| `summ.perspective_anchor` | table | seed | 5 | Perspective anchors (D-068): 0 insured advocate, 3 insured-leaning, 5 neutral (suva_house), 7 insurer-leaning, 10 insurer advocate. An anchor is active only once its rubric is written (owner: summarise). A perspective changes emphasis and the practice paragrap |
| `summ.preset` | table | seed | 1 | A kind of summary. Stored in the DB (the DB is its source of truth, exported to data/derived/authored/), listed by the UI, picked by code at run time. Exactly one active mandatory preset: suva_house. |
| `summ.preset_version` | table | no writer yet (layer 3) | 0 | Editorial configuration of a preset (length, sections, few-shot policy, perspective rubric...), jsonb checked against config_schema_id. Insert-only except status. Id = uuid5('preset_version\|<preset_code>\|<major>\|<minor>\|<patch>'). |
| `summ.preset_version_prompt` | table | no writer yet (layer 3) | 0 | The prompt versions a preset version uses, per language and role. Append-only. |
| `summ.summary` | table | no writer yet (layer 3) | 0 | Identity of one (ruling, preset) summary; its content lives in versions. Id = uuid5('summary\|<ruling_id>\|<preset_code>'). Append-only. |
| `summ.summary_claim` | table | no writer yet (layer 3) | 0 | One statement of a text. section includes application and practice (D-069): only practice may differ between perspectives. model_text = the model's text (NULL for an expert-written claim). Append-only. |
| `summ.summary_text` | table | no writer yet (layer 3) | 0 | One language of a version. title_line and body are rendered by code (references from consideration ids, D-037; never an author line, D-051). A pipeline text has its own LLM call written from the source, never a translation of the other language (D-014). Append |
| `summ.summary_version` | table | no writer yet (layer 3); function summ.create_expert_version | 0 | An immutable version of a summary: always one German and one French text (deferred check at commit, D-067). version_no is assigned by trigger. Only quality_status (verifier) and is_current change, audited. Expert validation is a review (gold.expert_review), no |
| `summ.v_mandatory_summary_gaps` | view | view | 0 | Mandatory-summary gaps of the current release of the default pipeline: must be empty (D-067). |
| `summ.v_summary_current` | view | view | 0 | Current version per (ruling, preset): both texts, verifier status, the latest expert review. |
| `summ.verification_check` | table | no writer yet (layer 3) | 0 | One verifier check (V1 to V6, the perspective invariant) on a claim or a text, with the exact rule version. Append-only. |
| `triage.assessment` | table | layer 1, layer 2 | 6,967 | One step's verdict on one ruling in one run. Append-only (trigger + grants). The step version must be the one the run's profile pins (trigger). input_fingerprint = SHA-256 over every input: a rerun skips identical inputs. docs/DB_DDL_PLANNING.md §10.1. |
| `triage.assessment_evidence` | table | no writer yet | 0 | Considerations an assessment cites, by FK. Trigger: from the assessment's input segmentation only (G1). Append-only. |
| `triage.assessment_reason` | table | layer 1 (one row per rule per ruling) | 54,495 | The rule-evaluation ledger (F-01, F-02): one row per enabled rule of the assessment's step version (check rules excepted), whatever it did: fired, not_fired, not_applicable (detail.why) or blocked (detail.blocked_by). ordinal = the rule's ordinal in the versio |
| `triage.justification` | table | no writer yet | 0 | Step 4 detail: the JSON protocol output (key statement, cited considerations) and the party check (no act attributed to Suva unless Suva is a party). Append-only. |
| `triage.llm_judgement` | table | layer 2 | 912 | Layer-2 detail: the Ja/Nein log-probabilities, p_yes, the raw top_logprobs, the truncation applied. Append-only. |
| `triage.ranking` | table | no writer yet (ranking not built) | 0 | A ranking of one population in one run, at one threshold. A rank belongs to (run, population), never to a ruling (D-046, D-050). Append-only. |
| `triage.ranking_entry` | table | no writer yet (ranking not built) | 0 | Rank of one ruling in one ranking. assessment_id = the ranking-step assessment (the label); score_assessment_id = the assessment that gave the score (layer 2 if judged, layer 1 if dropped by the filter). final_score is NULL only for a failed judgement (potenti |
| `triage.threshold` | table | no writer yet (ranking not built) | 0 | A frozen F2 threshold and where it comes from (population chosen on and reported on, metrics with CI, policy D-021 point 8). Valid only for scores of the same scorer step, major and minor (D-064; trigger on ranking entries). Append-only. |
| `triage.v_current_release` | view | view | 0 | The current release of the default pipeline (at most one row). |
| `triage.v_export_ranked` | view | view | 0 | The delivered ranked list of the current release (D-046): score, rank, threshold and top-30 marks, both dates and every population of each ruling (D-050). Must equal the hashed results/ file. |
| `triage.v_layer1_ledger` | view | view | 54,495 | Layer 1 rule by rule (F-01, F-02): one row per assessment and rule of its version, with the outcome (fired, not_fired, not_applicable, blocked), the evidence, the German and French labels, and is_decisive (the fired rule whose reason code is the decision's). O |
| `triage.v_scope_current` | view | view | 6,055 | The pipeline label plus the latest expert scope review beside it (D-066): expert_implied_label = the pipeline label, flipped when the verdict is incorrect. The delivered list and the metrics never read expert_implied_label. |
| `triage.v_scope_pipeline` | view | view | 6,055 | THE label (D-063): the default pipeline's furthest-step assessment per ruling, from its current release, else from its usable runs (succeeded or partial, not eval) and only along the lineage of its current layer-1 decision, matched on the decision (DDL-2): an identical layer-1 rerun keeps the later steps. not_assessed = no row. |
| `triage.v_scope_trace` | view | view | 6,967 | The "show me why" panel: one row per step of the label's lineage, with run, profile and component versions, models, reasons (reason_count = rules that fired; evaluated_rule_count = ledger rows, every rule of the version), LLM call, input text, source snapshot, |

## 4. Ruling data (`corpus`)

The main read view is **`corpus.v_ruling`**, with one row per ruling. It holds the ruling's metadata, its best publication date, its quarters and its primary text id. The text itself is `corpus.ruling_text.content` (`primary_text_id`).

| Measure | Value |
|---|---|
| Rulings | 6,055 (all `origin = base_dataset`, all texts `source = hf`) |
| Languages | de 3,792, fr 1,966, it 297 |
| Courts (docket prefix) | 11Z 1, 12T 3, 1C 542, 1D 10, 1F 14, 1G 1, 2C 545, 2D 27, 2E 3, 2F 25, 2G 2, 4A 542, 4D 198, 4F 46, 4G 1, 5A 896, 5D 47, 5F 51, 5G 1, 6B 749, 6F 22, 6G 3, 7B 1107, 7F 43, 7G 4, 8C 624, 8F 18, 8G 1, 9C 483, 9D 17, 9F 27, 9G 2 |
| Publication date | approx_first_seen 4,620, exact 1,435 |
| Text length (`char_length`) | min 483, max 392,688 characters |
| Rows read from the HF file / excluded at ingest | 27,286 read in the date windows; exclusions recorded in `corpus.ingest_exclusion`: OUT_OF_WINDOW 188,788, ING_TWIN_SAME_DATE 23 |

Quarter by decision date × quarter by exact publication date (`null` = no exact publication date):

| quarter_by_decision | quarter_by_publication | rulings |
|---|---|---:|
| 2025Q3 | null | 23 |
| 2025Q4 | 2026Q3 | 1 |
| 2025Q4 | null | 1,930 |
| 2026Q1 | 2026Q2 | 11 |
| 2026Q1 | 2026Q3 | 1 |
| 2026Q1 | null | 1,993 |
| 2026Q2 | 2026Q2 | 981 |
| 2026Q2 | 2026Q3 | 438 |
| 2026Q2 | 2026Q4 | 3 |
| 2026Q2 | null | 674 |

Populations (`corpus.population`, members in `corpus.population_member`; a ruling can belong to several):

| Code | Quarter | Definition | Role | Delivery default | Members | Layer 1 dropped | Layer 1 kept | Layer 2 scored |
|---|---|---|---|---|---:|---:|---:|---:|
| `2025Q4_decision` | 2025Q4 | decision_date | labelled | False | 1,931 | 1,636 | 295 | 295 |
| `2026Q1_decision` | 2026Q1 | decision_date | labelled | False | 2,005 | 1,666 | 339 | 339 |
| `2026Q2_decision` | 2026Q2 | decision_date | target | False | 2,096 | 1,818 | 278 | 278 |
| `2026Q2_publication` | 2026Q2 | publication_date | target | True | 2,060 | 1,748 | 312 | 312 |
| `2026Q2_union` | 2026Q2 | union | target | False | 2,677 | 2,294 | 383 | 383 |
| `suva_reference` | None | reference | reference | False | 23 | 0 | 23 | 0 |

Other corpus relations:
- `corpus.publication_observation`: one row per date observation (source `hf_poller` = exact, `hf_first_seen` = approximate); `star` and `sachgebiet` empty.
- `corpus.subject_observation`: the HF `legal_area` of 4,327 rulings (source `hf_legal_area`).
- `corpus.ruling_source_ref`: the source row(s) behind each ruling (6,072 refs for 6,055 rulings: twins).
- `corpus.v_ingest_closure`: one row that accounts for every source row (read, kept, excluded per reason).

## 5. Layer 1 data (deterministic pre-filter, no LLM)

**One `triage.assessment` row per ruling per run** (`step = 'layer1_filter'`), plus **one `triage.assessment_reason` row per rule per ruling** (the rule ledger: every rule of the version, whether it fired or not). The view **`triage.v_layer1_ledger`** joins the ledger with docket, profile, version, rule labels DE and FR, and `is_decisive`.

- Version in this snapshot: `layer1_filter` V1.1.0 (9 rules per ruling, 54,495 ledger rows for 6,055 rulings).
- Assessment values: `out_of_scope` 5,120 (`score_source = net`, `score_0_100 = 0.00`), `potentially` 935 (`score_source` null, `score_0_100` null).
- `reason_code` on the assessment row = the decisive rule (keep code when kept, drop code when dropped).
- Rule outcome values (`ops.rule_outcome`): `fired | not_fired | not_applicable | blocked`. Rule effects (`ops.rule_kind`): `keep | drop | flag | signal | check`.
- Evidence per ledger row: `evidence_field` (`docket`, `full_text`, `gegenstand`, `rubric:<source>`), `examined_value`, `char_start` / `char_end` / `matched_text` (offsets into `corpus.ruling_text.content` for text matches), `detail` (jsonb: pattern, rubric key, why not applicable…). `evidence_consideration_id` is empty (no segmentation).
- The rubric that layer 1 read is visible in the ledger: `evidence_field = 'rubric:hf_legal_area'` or `'rubric:gegenstand_head'`, with the rubric in `examined_value`.

Decisive rule per ruling (from `v_layer1_ledger.decision_reason_code`):

| Decisive rule | Rulings | Example `explanation_de` (first of its code, alphabetical) |
|---|---:|---|
| `L1_DROP_WRONG_COURT` | 4,058 | Von der Vorauswahl ausgeschlossen: Abteilung nicht in der Liste der Vorauswahl. Im Urteilstext geprüft, ohne Treffer: Suchbegriffe zu Suva, Unfall- und Militärversicherung; Suchbegriffe zu VVG und Taggeldversicherung (nur die Begriffe der Filterversion; andere Formulierungen erkennt die Prüfung nich |
| `L1_DROP_RUBRIC_OUT` | 1,062 | Von der Vorauswahl ausgeschlossen: Rechtsgebiet nicht in der Liste der Abteilung. Im Urteilstext geprüft, ohne Treffer: Suchbegriffe zu Suva, Unfall- und Militärversicherung; Suchbegriffe zu VVG und Taggeldversicherung (nur die Begriffe der Filterversion; andere Formulierungen erkennt die Prüfung ni |
| `L1_KEEP_RUBRIC` | 859 | Vorauswahl bestanden: Rechtsgebiet in der Liste der Abteilung. |
| `L1_KEEP_ACCIDENT_TERM` | 47 | Vorauswahl bestanden: Text nennt die Suva oder die Unfall- oder Militärversicherung. |
| `L1_KEEP_RUBRIC_MISSING` | 19 | Vorauswahl bestanden: Rechtsgebiet fehlt: vorsorglich behalten. |
| `L1_KEEP_CONTRACT_TERM` | 10 | Vorauswahl bestanden: Text nennt das VVG oder eine Taggeldversicherung. |

Ledger rows per rule and outcome (all rulings):

| Rule | Effect | Outcome | Rows |
|---|---|---|---:|
| `L1_DROP_RUBRIC_OUT` | drop | fired | 1,081 |
| `L1_DROP_RUBRIC_OUT` | drop | not_fired | 859 |
| `L1_DROP_RUBRIC_OUT` | drop | not_applicable | 4,115 |
| `L1_DROP_WRONG_COURT` | drop | fired | 4,096 |
| `L1_DROP_WRONG_COURT` | drop | not_fired | 1,959 |
| `L1_DROP_WRONG_LETTER` | drop | not_fired | 1,959 |
| `L1_DROP_WRONG_LETTER` | drop | not_applicable | 4,096 |
| `L1_FLAG_CLOSED_RUBRIC` | flag | not_fired | 6,055 |
| `L1_KEEP_ACCIDENT_TERM` | keep | fired | 280 |
| `L1_KEEP_ACCIDENT_TERM` | keep | not_fired | 5,775 |
| `L1_KEEP_CONTRACT_TERM` | keep | fired | 43 |
| `L1_KEEP_CONTRACT_TERM` | keep | not_fired | 6,012 |
| `L1_KEEP_RUBRIC` | keep | fired | 859 |
| `L1_KEEP_RUBRIC` | keep | not_fired | 1,081 |
| `L1_KEEP_RUBRIC` | keep | not_applicable | 4,115 |
| `L1_KEEP_RUBRIC_MISSING` | keep | fired | 19 |
| `L1_KEEP_RUBRIC_MISSING` | keep | not_fired | 1,940 |
| `L1_KEEP_RUBRIC_MISSING` | keep | not_applicable | 4,096 |
| `L1_SIGNAL_RUBRIC_FROM_TITLE` | signal | fired | 1,680 |
| `L1_SIGNAL_RUBRIC_FROM_TITLE` | signal | not_fired | 4,375 |

Rules of each `layer1_filter` version (`ops.component_version_rule`, in evaluation order):

| Version | Rules | Codes |
|---|---:|---|
| V1.0.0 | 9 | L1_KEEP_RUBRIC, L1_KEEP_RUBRIC_MISSING, L1_KEEP_ACCIDENT_TERM, L1_KEEP_CONTRACT_TERM, L1_FLAG_CLOSED_RUBRIC, L1_DROP_WRONG_COURT, L1_DROP_WRONG_LETTER, L1_DROP_RUBRIC_OUT, L1_SIGNAL_RUBRIC_FROM_TITLE |
| V1.1.0 | 9 | L1_KEEP_RUBRIC, L1_KEEP_RUBRIC_MISSING, L1_KEEP_ACCIDENT_TERM, L1_KEEP_CONTRACT_TERM, L1_FLAG_CLOSED_RUBRIC, L1_DROP_WRONG_COURT, L1_DROP_WRONG_LETTER, L1_DROP_RUBRIC_OUT, L1_SIGNAL_RUBRIC_FROM_TITLE |
| V1.2.0 | 11 | L1_KEEP_RUBRIC, L1_KEEP_RUBRIC_MISSING, L1_KEEP_ACCIDENT_TERM, L1_KEEP_CONTRACT_TERM, L1_FLAG_CLOSED_RUBRIC, L1_DROP_WRONG_COURT, L1_DROP_WRONG_LETTER, L1_DROP_RUBRIC_OUT, L1_SIGNAL_RUBRIC_FROM_TITLE, L1_KEEP_TEXT_UNAVAILABLE, L1_KEEP_TITLE_RUBRIC |

Rule descriptions (`ops.rule.description`):

| Rule | Description |
|---|---|
| `L1_KEEP_RUBRIC` | Court 4, 8 or 9, an allowed proceedings letter, and a matter rubric in the court's keep set. |
| `L1_KEEP_RUBRIC_MISSING` | Allowed court and letter, but no rubric to read: kept so that a blank field is never a miss (G5). |
| `L1_KEEP_ACCIDENT_TERM` | The text names Suva, CNA, INSAI, the UVG/LAA/LAINF/MVG or accident or military insurance. |
| `L1_KEEP_CONTRACT_TERM` | The text names the insurance-contract act (VVG, LCA) or private daily-allowance insurance. |
| `L1_FLAG_CLOSED_RUBRIC` | A contract term matched but the rubric is closed (unemployment, old-age, tax...): it does not keep. |
| `L1_DROP_WRONG_COURT` | The court is not 4, 8 or 9 and the text names no keep term. |
| `L1_DROP_WRONG_LETTER` | The proceedings letter is not kept on this court and the text names no keep term. |
| `L1_DROP_RUBRIC_OUT` | The rubric is outside the court's keep set and the text names no keep term. |
| `L1_SIGNAL_RUBRIC_FROM_TITLE` | No rubric field was filled: the matter was read from the start of the Gegenstand line. |

## 6. Layer 2 data (Apertus relevance judge)

**One `triage.assessment` row per judged ruling per run** (`step = 'layer2_judge'`), linked to its layer-1 row by `upstream_assessment_id`, plus **one `triage.llm_judgement` row** (what Apertus answered) and **one `ops.llm_call` row per attempt or cache hit**. The exact messages are in `ops.blob` (key `ops.llm_call.messages_sha256`).

- Version: `layer2_judge` V1.0.0, judge `apertus-v1-5-8b` (zero-shot, German question, answer read from the first token's log-probabilities: `max_tokens 1`, `top_logprobs 20`, `temperature 0`).
- Who is judged: the rulings layer 1 kept (`potentially`) in the populations of the run. Here 912 of the 935 kept; the other 23 belong only to `suva_reference`, which was not in the run.
- Label: always `potentially`. `outcome` = `ok | failed | skipped` (a failed or skipped call keeps `potentially`, with reason `L2_FAILED_CALL` or `L2_FAIL_NO_YESNO_TOKEN`). `score_source = judged`.
- Since 28 Nov (after this snapshot): a replay run writes **no row** for a candidate without a recorded answer (`replay_misses.jsonl`, metric `replay_misses`, run `partial`), so an earlier judgement keeps its place in the label while the ruling's current layer-1 decision is unchanged; and the trigger `t31_call` refuses a `triage.llm_judgement` row whose call is not its own (other run, ruling or step; another prompt than the one the call sent or the version declares; other models). `docs/LAYER2.md` §4, §7.
- Languages of the judged rulings: de 573, fr 311, it 28.
- `score_raw` (double, logit): 912 distinct values, min -22.250, max 29.000.
- `score_0_100` (`numeric(5,2)`): 114 distinct values, min 0.00, max 100.00, **189 rulings at exactly 100.00**.
- Text sent: the ruling's text, cut to the first 12,000 + last 2,000 characters when longer than 14,000 (`llm_judgement.truncation`: `none` 505, `head12000_tail2000` 407); `text_chars_total`, `text_chars_sent` per ruling.
- `explanation_de`: generated by code from the score (447 distinct texts). Most frequent:

  - (332×) Apertus-Einschätzung (Modell apertus-v1-5-8b, Version V1.0.0): Wahrscheinlichkeit «Ja» < 0,1 %. Über die Relevanz entscheidet erst die Rangierung.
  - (84×) Apertus-Einschätzung (Modell apertus-v1-5-8b, Version V1.0.0): Wahrscheinlichkeit «Ja» > 99,9 %. Über die Relevanz entscheidet erst die Rangierung.
  - (10×) Apertus-Einschätzung (Modell apertus-v1-5-8b, Version V1.0.0): Wahrscheinlichkeit «Ja» 0,2 %. Über die Relevanz entscheidet erst die Rangierung.
  - (10×) Apertus-Einschätzung (Modell apertus-v1-5-8b, Version V1.0.0): Wahrscheinlichkeit «Ja» 0,1 %. Über die Relevanz entscheidet erst die Rangierung.

Distribution of `score_0_100` in 10-point buckets (bucket 1 = [0, 10), …, bucket 10 = [90, 100]):

| Bucket | Rulings |
|---:|---:|
| 1 | 595 |
| 2 | 9 |
| 3 | 12 |
| 4 | 9 |
| 5 | 6 |
| 6 | 5 |
| 7 | 2 |
| 8 | 8 |
| 9 | 6 |
| 10 | 260 |

`triage.llm_judgement` fields: `requested_model`, `served_model`, `question_language` (`de`), `logprob_yes`, `logprob_no`, `p_yes`, `top_logprobs` (jsonb: the 20 first-token candidates with their log-probabilities), `yes_no_in_top`, `text_chars_total`, `text_chars_sent`, `truncation`, `input_tokens`, `prompt_version_id`, `llm_call_id`.

`ops.llm_call` fields (one per attempt or cache hit): `purpose` (`relevance_judgement`), `language`, `endpoint` (`/chat/completions`), `model_role` (`judge`), `requested_model`, `served_model`, `served_model_header`, `params` (jsonb), `cache_key`, `cache_hit`, `mode`, `raw_output` (`Ja` / `Nein` …), `finish_reason`, `parsed_ok`, `parse_error`, `http_status`, `error_reason_code`, `attempt`, `input_tokens`, `output_tokens`, `cached_tokens`, `latency_ms` (empty on cache hits), `started_at`. No API key and no prompt text in it; the messages are in `ops.blob`.

The prompt (`ops.prompt_version`, role `layer2_judge.question`, V1.0.0): a German system prompt (712 characters) and the user template `Urteil {docket}:\n\n{text}\n\nIst dieses Urteil für die Suva relevant? Antworte nur mit Ja oder Nein.`

Measured live elsewhere (not in this snapshot): on 28 Nov ~06:50 CET, 383 of 383 Q2 rulings (`2026Q2_union`) judged live in 37 s, latency p50 378 ms / p95 528 ms (`docs/LAYER2.md`, `results/layer2_q2_2026.json`).

## 7. The label views: what the pipeline says per ruling

- **`triage.v_scope_pipeline`**: THE pipeline label per ruling = the furthest-step assessment of the default profile (from the current release when one exists, else from its usable runs, succeeded or partial and not eval, along the lineage of its current layer-1 decision: a judgement made on another layer-1 decision, from a failed or aborted run, or with no layer-1 root never forms the label; DDL-2, 28 Nov. The decision is matched by content (`layer1_filter` version, input fingerprint, scope, reason code, outcome), not by assessment id, so an identical rerun of layer 1 keeps the judgements; a layer-1 run of kind `eval`, such as the two runs of `make layer1-validate`, never counts). A ruling with no row = not assessed. Columns: `pipeline_label`, `step`, `score_0_100`, `score_source`, `reason_code`, `reason_label_de/fr`, `explanation_de`, `outcome`, `mode`, `label_origin` (`release | latest_run`), `assessment_id`, `run_id`, `created_at`. It does **not** carry `score_raw` (that is on `triage.assessment`, via `assessment_id`).
- **`triage.v_scope_current`**: `v_scope_pipeline` + the latest expert scope review: `expert_verdict`, `reviewed_label`, `reviewed_assessment_id`, `review_is_stale`, `expert_implied_label`, `reviewed_by`, `reviewed_at` (all empty here).
- **`triage.v_scope_trace`**: the "why" lineage, one row per step per ruling (`hop` 0 = furthest step, 1 = the step before). Per hop: label, score, reason and its German label, `explanation_de`, run, profile and component versions, code and config hashes, declared models, `reason_count`, `evaluated_rule_count`, the LLM call (served model, tokens, cache hit, finish reason, `p_yes`), text source and hash, source revision and file hash, span status, duration, event counts.
- **`ops.v_ruling_timeline`**: every span and event of a ruling across runs (`kind` span|event, `step`, `code`, `level_or_status`, `message`, `attributes`, `duration_ms`, `ts`).

| `v_scope_current` | pipeline_label | step | label_origin | mode | rulings |
|---|---|---|---|---|---:|
| | out_of_scope | layer1_filter | latest_run | LIVE | 5,120 |
| | potentially | layer1_filter | latest_run | LIVE | 23 |
| | potentially | layer2_judge | latest_run | REPLAY | 912 |

## 8. Suva's data (`gold`)

- **`gold.label`**: Suva's positives from `judgements/` (source `suva_relevance_list` or `suva_summary_export`); `in_suva_scope` is always `true`; a cantonal row has `external_title` instead of `ruling_id`.
- **`gold.v_label_effective`**: per labelled population, every member with `in_suva_scope` and its `basis`: `suva_list` (listed) or `closed_world` (not listed, assumed negative: an assumption, Q-04), plus `has_suva_summary`.
- **`gold.suva_summary`**: Suva's DE and FR summary texts (columns in Appendix B). Empty at this commit.
- **`gold.expert_review`**, **`gold.v_expert_review_current`**: expert reviews (empty).

| `gold.label` source | quarter_label | rows |
|---|---|---:|
| suva_relevance_list | 2025 Q4 | 28 |
| suva_relevance_list | 2026 Q1 | 32 |
| suva_summary_export | None | 55 |

| `gold.v_label_effective` population | basis | in_suva_scope | has_suva_summary | rulings |
|---|---|---|---|---:|
| 2025Q4_decision | closed_world | False | False | 1,903 |
| 2025Q4_decision | suva_list | True | False | 28 |
| 2026Q1_decision | closed_world | False | False | 1,974 |
| 2026Q1_decision | suva_list | True | False | 31 |

Repo rules on this data (facts of `AGENTS.md`, `docs/DECISIONS.md`): never show or copy a Suva author, staff code or intranet link (D-051; the database never stores them); Suva labels per docket stay in the database and `data/derived/`, never in a committed file (D-031); never add personal data about people in rulings (D-038).

## 9. Runs, logs and metrics (`ops`)

- **`ops.pipeline_run`**: one row per run: `kind` (`load | ingest | layer1 | layer2 | …`), `mode`, `status` (`running | succeeded | failed | partial | aborted`), `git_commit`, `git_dirty`, `params` (jsonb: profile, version, populations, code paths and hash…), `resolved_models` (jsonb, e.g. `{"judge": "apertus-v1-5-8b"}`), `model_override`, `triggered_by`, `actor`, `started_at`, `finished_at`, `error_summary`.
- **`ops.v_run_health`**: per run and step: `spans`, `error_spans`, `p95_duration_ms`, `failed_items`, `metrics` (jsonb).
- **`ops.span`**: one span per unit of work (`step`, `operation`, `ruling_id`, `status`, `duration_ms`, `attributes`, `error_reason_code`, `error_message`).
- **`ops.log_event`** (daily partitions): `step`, `level`, `event_code`, `message`, `attributes`, `ruling_id`, `span_id`, `ts`.
- **`ops.run_metric`**: `step`, `metric_code`, `value`, `unit` per run.
- **`ops.v_profile`**: which step versions, models and rules each profile version pins.

| Span step | operation | status | count |
|---|---|---|---:|
| layer1_filter | layer1.decide | ok | 6,055 |
| layer2_judge | llm.call | ok | 912 |
| layer2_judge | layer2.judge | ok | 912 |
| layer2_judge | layer2.run | ok | 1 |
| ingest | ingest.gold | ok | 1 |
| layer1_filter | layer1.run | ok | 1 |
| ingest | ingest.hf_base | ok | 1 |

| Event step | level | event_code | count |
|---|---|---|---:|
| layer1_filter | info | `layer1.decision.made` | 6,055 |
| layer2_judge | debug | `llm.cache.hit` | 912 |
| layer2_judge | debug | `layer2.score` | 912 |
| layer2_judge | info | `layer2.prompt.built` | 912 |
| ingest | info | `ingest.exclusions.recorded` | 1 |
| layer1_filter | info | `layer1.files.written` | 1 |
| layer2_judge | info | `layer2.files.written` | 1 |
| ingest | info | `ingest.gold.loaded` | 1 |
| ingest | info | `ingest.population.frozen` | 1 |
| layer1_filter | info | `layer1.run.decided` | 1 |
| layer2_judge | info | `layer2.model.resolved` | 1 |
| ingest | info | `ingest.snapshot.loaded` | 1 |
| layer1_filter | info | `layer1.golden.matched` | 1 |
| layer1_filter | warning | `layer1.parity.checked` | 1 |
| layer2_judge | info | `layer2.run.summary` | 1 |

| Run kind | step | metric_code | value | unit |
|---|---|---|---:|---|
| load | ingest | `exports` | 55 | labels |
| load | ingest | `list_cantonal` | 1 | labels |
| load | ingest | `list_federal_court` | 59 | labels |
| load | ingest | `list_rows` | 60 | labels |
| ingest | ingest | `closure_ok` | 1 | rows |
| ingest | ingest | `excluded_ing_decision_date_missing` | 0 | rows |
| ingest | ingest | `excluded_ing_docket_malformed` | 0 | rows |
| ingest | ingest | `excluded_ing_source_id_duplicate` | 0 | rows |
| ingest | ingest | `excluded_ing_source_id_missing` | 0 | rows |
| ingest | ingest | `excluded_ing_twin_same_date` | 23 | rows |
| ingest | ingest | `excluded_out_of_window` | 188788 | rows |
| ingest | ingest | `exclusions` | 188811 | rows |
| ingest | ingest | `file_rows` | 194883 | rows |
| ingest | ingest | `out_of_window` | 21214 | rows |
| ingest | ingest | `population_2025q4_decision` | 1931 | rows |
| ingest | ingest | `population_2026q1_decision` | 2005 | rows |
| ingest | ingest | `population_2026q2_decision` | 2096 | rows |
| ingest | ingest | `population_2026q2_publication` | 2060 | rows |
| ingest | ingest | `population_2026q2_union` | 2677 | rows |
| ingest | ingest | `population_suva_reference` | 23 | rows |
| ingest | ingest | `rejected_malformed` | 0 | rows |
| ingest | ingest | `rows_read` | 27286 | rows |
| ingest | ingest | `rulings` | 6055 | rows |
| ingest | ingest | `source_refs` | 6072 | rows |
| ingest | ingest | `texts` | 6055 | rows |
| ingest | ingest | `twins` | 17 | rows |
| ingest | ingest | `with_hf_legal_area` | 4327 | rows |
| layer1 | layer1_filter | `dropped` | 5120 | count |
| layer1 | layer1_filter | `kept` | 935 | count |
| layer1 | layer1_filter | `ledger_rows` | 54495 | count |
| layer1 | layer1_filter | `outcome_blocked` | 0 | count |
| layer1 | layer1_filter | `outcome_fired` | 8058 | count |
| layer1 | layer1_filter | `outcome_not_applicable` | 16422 | count |
| layer1 | layer1_filter | `outcome_not_fired` | 30015 | count |
| layer1 | layer1_filter | `parity_different` | 17 | count |
| layer1 | layer1_filter | `parity_same` | 6038 | count |
| layer1 | layer1_filter | `reason_l1_drop_rubric_out` | 1062 | count |
| layer1 | layer1_filter | `reason_l1_drop_wrong_court` | 4058 | count |
| layer1 | layer1_filter | `reason_l1_keep_accident_term` | 47 | count |
| layer1 | layer1_filter | `reason_l1_keep_contract_term` | 10 | count |
| layer1 | layer1_filter | `reason_l1_keep_rubric` | 859 | count |
| layer1 | layer1_filter | `reason_l1_keep_rubric_missing` | 19 | count |
| layer1 | layer1_filter | `rubric_from_title` | 1680 | count |
| layer1 | layer1_filter | `rulings_in` | 6055 | count |
| layer2 | layer2_judge | `cache_hits` | 912 | count |
| layer2 | layer2_judge | `failed` | 0 | count |
| layer2 | layer2_judge | `judged` | 912 | count |
| layer2 | layer2_judge | `live_calls` | 0 | count |
| layer2 | layer2_judge | `llm_attempts` | 912 | count |
| layer2 | layer2_judge | `llm_errors` | 0 | count |
| layer2 | layer2_judge | `model_override` | 0 | count |
| layer2 | layer2_judge | `neutralised` | 0 | count |
| layer2 | layer2_judge | `rulings_in` | 912 | count |
| layer2 | layer2_judge | `skipped` | 0 | count |
| layer2 | layer2_judge | `tokens_in` | 0 | count |
| layer2 | layer2_judge | `truncated` | 407 | count |

## 10. Reference data

**Reason codes** (`ops.reason_code`, seeded; every label exists in German and French):

| Code | Domain | label_de | label_fr |
|---|---|---|---|
| `JUS_ACTING_PARTY_IN_BLOCK` | triage | Handelnde Partei steht im Rubrum | La partie agissante figure dans le rubrum |
| `JUS_EVIDENCE_IN_SET` | triage | Zitierte Erwägungen stammen aus dem Urteil | Les considérants cités proviennent de l'arrêt |
| `JUS_JSON_INVALID` | triage | Begründung nicht im erwarteten Format | Justification hors du format attendu |
| `JUS_PARTY_SUVA_ACTING_ONLY_IF_PARTY` | triage | Der Suva wird nur eine Handlung zugeschrieben, wenn sie Partei ist | Un acte n'est attribué à la Suva que si elle est partie |
| `L1_DROP_RUBRIC_OUT` | triage | Rechtsgebiet nicht in der Liste der Abteilung | Domaine juridique hors de la liste de cette cour |
| `L1_DROP_WRONG_COURT` | triage | Abteilung nicht in der Liste der Vorauswahl | Cour hors de la liste du filtre |
| `L1_DROP_WRONG_LETTER` | triage | Verfahrensart in dieser Abteilung nicht berücksichtigt | Type de procédure non retenu pour cette cour |
| `L1_FLAG_CLOSED_RUBRIC` | triage | VVG-Begriff im Text, aber Rechtsgebiet ausgeschlossen (z. B. Arbeitslosenversicherung) | Terme LCA dans le texte, mais domaine exclu (p. ex. assurance-chômage) |
| `L1_KEEP_ACCIDENT_TERM` | triage | Text nennt die Suva oder die Unfall- oder Militärversicherung | Le texte mentionne la Suva ou l'assurance-accidents ou militaire |
| `L1_KEEP_CONTRACT_TERM` | triage | Text nennt das VVG oder eine Taggeldversicherung | Le texte mentionne la LCA ou une assurance d'indemnités journalières |
| `L1_KEEP_RUBRIC` | triage | Rechtsgebiet in der Liste der Abteilung | Domaine juridique retenu pour cette cour |
| `L1_KEEP_RUBRIC_MISSING` | triage | Rechtsgebiet fehlt: vorsorglich behalten | Domaine juridique absent : conservé par prudence |
| `L1_KEEP_TEXT_UNAVAILABLE` | triage | Kein Urteilstext verfügbar: vorsorglich behalten | Texte de l'arrêt indisponible : conservé par prudence |
| `L1_KEEP_TITLE_RUBRIC` | triage | Rechtsgebiet laut Gegenstand in der Liste der Abteilung | Domaine juridique selon l'objet retenu pour cette cour |
| `L1_SIGNAL_RUBRIC_FROM_TITLE` | triage | Rechtsgebiet aus dem Gegenstand gelesen | Domaine lu dans l'objet |
| `L2_FAILED_CALL` | triage | Beurteilung durch Apertus fehlgeschlagen, wird wiederholt | Évaluation par Apertus échouée, nouvel essai prévu |
| `L2_FAIL_NO_YESNO_TOKEN` | triage | Antwort ohne Ja/Nein: nicht verwertbar | Réponse sans Ja/Nein : inexploitable |
| `OUT_OF_WINDOW` | triage | Ausserhalb aller Zeitfenster | Hors de toutes les périodes |
| `RANK_AT_OR_ABOVE_THRESHOLD` | triage | Relevanzwert auf oder über der Schwelle | Score de pertinence au seuil ou au-dessus |
| `RANK_BELOW_THRESHOLD` | triage | Relevanzwert unter der Schwelle | Score de pertinence sous le seuil |
| `V1_IDS_IN_SET` | verify | Zitierte Erwägungen gehören zum Urteil | Les considérants cités appartiennent à l'arrêt |
| `V2_QUOTE_VERBATIM` | verify | Zitat wörtlich im Urteil | Citation littérale de l'arrêt |
| `V3_NUMBERS_PRESENT` | verify | Zahlen, Daten und Beträge stehen in der zitierten Erwägung | Chiffres, dates et montants présents dans le considérant cité |
| `V4_CANONICAL_REFS` | verify | Artikel, BGE und Dossiernummern stehen im Urteil | Articles, ATF et numéros de dossier présents dans l'arrêt |
| `V5_HAS_CITATION` | verify | Jede Aussage hat einen Beleg | Chaque affirmation est étayée |
| `V6_ACTING_PARTY` | verify | Handelnde Partei ist Verfahrensbeteiligte | La partie agissante est partie à la procédure |
| `ING_CONSIDERATION_NOT_LOCATED` | ingest | Erwägung im Text nicht gefunden | Considérant introuvable dans le texte |
| `ING_CONSIDERATIONS_COUNT_MISMATCH` | ingest | Anzahl Erwägungen weicht ab | Nombre de considérants divergent |
| `ING_CONSIDERATIONS_MISSING` | ingest | Erwägungen fehlen in der Quelle | Considérants absents de la source |
| `ING_DECISION_DATE_MISSING` | ingest | Entscheiddatum fehlt in der Quelle | Date de l'arrêt absente de la source |
| `ING_DOCKET_MALFORMED` | ingest | Geschäftsnummer nicht im Format des Bundesgerichts | Numéro de dossier hors du format du Tribunal fédéral |
| `ING_PUBLICATION_UNKNOWN` | ingest | Publikationsdatum unbekannt | Date de publication inconnue |
| `ING_SOURCE_ID_DUPLICATE` | ingest | Kennung der Quelle doppelt vergeben | Identifiant de la source en double |
| `ING_SOURCE_ID_MISSING` | ingest | Zeile der Quelle ohne Kennung | Ligne de la source sans identifiant |
| `ING_TEXT_MISSING` | ingest | Kein Urteilstext verfügbar | Texte de l'arrêt indisponible |
| `ING_TWIN_SAME_DATE` | ingest | Doppelte Zeile der Quelle (gleiches Datum) | Ligne en double dans la source (même date) |
| `PAR_OUTCOME_PATTERN` | ingest | Ausgang aus dem Dispositiv | Issue tirée du dispositif |
| `SEG_COUNT_MATCH` | ingest | Anzahl Erwägungen stimmt | Nombre de considérants conforme |
| `SEG_COVERAGE` | ingest | Erwägungsteil vollständig abgedeckt | Partie des considérants entièrement couverte |
| `SEG_OFFSET_FOUND` | ingest | Position der Erwägung gefunden | Position du considérant trouvée |
| `WORK_CIRCUIT_OPEN` | work | Lauf pausiert (Schutzschalter) | Exécution en pause (disjoncteur) |
| `WORK_HTTP_ERROR` | work | Fehler des Dienstes | Erreur du service |
| `WORK_MODEL_MISMATCH` | work | Geliefertes Modell nicht zugelassen | Modèle servi non autorisé |
| `WORK_PARSE_ERROR` | work | Antwort nicht lesbar | Réponse illisible |
| `WORK_RATE_LIMITED` | work | Anfragelimit erreicht | Limite de requêtes atteinte |
| `WORK_TIMEOUT` | work | Zeitüberschreitung | Délai dépassé |
| `SUM_NON_PRACTICE_INVARIANT` | summary | Ausser «Praxis» identisch mit der Suva-Fassung | Identique à la version Suva, hormis la « pratique » |
| `SUM_PAIR_REQUIRED` | summary | Deutsche und französische Fassung vorhanden | Versions allemande et française présentes |

**Step versions** (`ops.component_version`):

| Step | Version | Name | Status | Decision | Expected file |
|---|---|---|---|---|---|
| ingest | V1.0.0 | HF base dataset | active | D-072 | `expected/ingest/V1.0.0.json` |
| layer1_filter | V1.0.0 | layer-1 gate, parity with src/courts.py@4c246a8 | active | D-073 | `expected/layer1/V1.0.0.json` |
| layer1_filter | V1.1.0 | layer-1 gate, normalised text, wider accident terms | active | D-073 | `expected/layer1/V1.1.0.json` |
| layer1_filter | V1.2.0 | layer-1 gate, no-text keep, title rubric, wider vocabulary | active | D-083 | `expected/layer1/V1.2.0.json` |
| layer2_judge | V1.0.0 | Apertus 8B zero-shot Ja/Nein, the D-074 chain | active | D-076 | `expected/layer2/V1.0.0.json` |

**Profiles** (`ops.v_profile`, one row per profile version and step):

| profile_code | is_default | profile_version | profile_status | step | component_name | component_version | models | enabled_rules |
|---|---|---|---|---|---|---|---|---|
| default | True | V0.1.0 | active | ingest | HF base dataset | V1.0.0 | None | 0 |
| default | True | V0.1.0 | active | layer1_filter | layer-1 gate, parity with src/courts.py@4c246a8 | V1.0.0 | None | 9 |
| default | True | V0.2.0 | active | ingest | HF base dataset | V1.0.0 | None | 0 |
| default | True | V0.2.0 | active | layer1_filter | layer-1 gate, normalised text, wider accident terms | V1.1.0 | None | 9 |
| default | True | V0.3.0 | active | ingest | HF base dataset | V1.0.0 | None | 0 |
| default | True | V0.3.0 | active | layer1_filter | layer-1 gate, normalised text, wider accident terms | V1.1.0 | None | 9 |
| default | True | V0.3.0 | active | layer2_judge | Apertus 8B zero-shot Ja/Nein, the D-074 chain | V1.0.0 | {'judge': 'apertus-v1-5-8b'} | 0 |
| layer1_reference | False | V0.1.0 | active | ingest | HF base dataset | V1.0.0 | None | 0 |
| layer1_reference | False | V0.1.0 | active | layer1_filter | layer-1 gate, parity with src/courts.py@4c246a8 | V1.0.0 | None | 9 |
| layer1_candidate | False | V0.1.0 | active | ingest | HF base dataset | V1.0.0 | None | 0 |
| layer1_candidate | False | V0.1.0 | active | layer1_filter | layer-1 gate, no-text keep, title rubric, wider vocabulary | V1.2.0 | None | 11 |

**Models** (`ops.model`): `apertus-v1-5-70b` (`swiss-ai/Apertus-v1.5-70B`, size 70B) and `apertus-v1-5-8b` (`swiss-ai/Apertus-v1.5-8B`, size 8B), both `allowed`.

## 11. Writes the database already offers (SECURITY DEFINER functions)

The API login `suva_api` reads every schema and writes only through these functions; each needs `app.actor` set on the session (`ops.require_actor()`).

| Function | Returns | Who may execute | Comment |
|---|---|---|---|
| `gold.submit_review(ops.review_target,uuid,ops.review_verdict,jsonb,text,uuid)` | uuid | suva_api, suva_g_review, suva_owner | The only way to write gold.expert_review (D-066). Takes the latest active review schema; copies the label the expert saw. |
| `ops.submit_request(ops.request_kind,text,text,uuid,text)` | uuid | suva_api, suva_g_review, suva_owner | UI request: add a judgement by docket or bger.ch link, or a summary of any ruling under any preset. The pipeline accepts it into a run. |
| `summ.create_expert_version(uuid,ops.lang_code,text,text,jsonb)` | uuid | suva_api, suva_g_review, suva_owner | Expert edit: version n+1 (expert_edit), the other language copied unchanged, the edited language with its claims (status flagged until the verifier reruns), made current. A version stays a German + French pair (D-067). |
| `summ.mandatory_summary_gaps(uuid)` | TABLE(ruling_id uuid, docket text, decision_date date) | suva_api, suva_g_pipeline, suva_g_read, suva_g_review, suva_owner, suva_pipeline, suva_report | In-scope rulings of a release (default pipeline label) without a current, non-rejected suva_house version with both languages (D-067). |
| `triage.release_gate_problems(uuid)` | TABLE(problem text, ruling_id uuid) | suva_api, suva_g_pipeline, suva_g_read, suva_g_review, suva_owner, suva_pipeline, suva_report | Why a release may not become current: a target member without a label, or an in-scope ruling without its mandatory summary (§9.2 invariant 4, §13.7). A failed judgement stays potentially and is allowed (it is listed in ranking_entry). |

Constraints that shape these writes (from the DDL):
- `gold.expert_review` CHECK `expert_review_target_chk` (D-093, after this snapshot): a scope review has verdict `relevant | not_relevant` on any label (`potentially` included), `correct | incorrect` on `in_scope` or `out_of_scope`, or `withdrawn` with `supersedes_review_id`; a summary review has verdict `validated | rejected`, or `withdrawn` with `supersedes_review_id`, and no label. Before D-093 a scope review on a `potentially` assessment was refused.
- `ops.user_request`: `kind` = `add_judgement | summary`; `status` = `pending | accepted | done | failed | rejected`; a request names a docket, a bger.ch link or a ruling id (`user_request_target_chk`).
- `summ.create_expert_version` creates a new version of an existing summary (it needs one to exist).

## 12. Defined but empty at this commit

| Relation(s) | Waits for |
|---|---|
| `triage.threshold`, `triage.ranking`, `triage.ranking_entry`, `ops.release`, views `triage.v_current_release`, `triage.v_export_ranked` | the ranking step (D-021 open): F2 threshold, rank, top-10 and top-30 marks, `final_score_0_100`, delivered list |
| `triage.justification`, `triage.assessment_evidence` | a justification step (key statement, cited considerations) |
| `corpus.segmentation`, `corpus.consideration`, `corpus.ruling_parse`, `corpus.ingest_issue` | segment and parse steps (considerations, parties, outcome, bench) |
| `gold.suva_summary` | a loader of Suva's summary texts |
| `gold.expert_review`, `ops.user_request` | UI writes |
| `ops.work_item`, `ops.artifact`, `ops.llm_call_example` | work queue, exported artefacts, few-shot links |
| all of `summ.*` except `perspective_anchor`, `preset` | layer 3 |

## 13. Layer 3 (summaries): PREVIEW, SUBJECT TO CHANGE

> **For any reader, human or agent:** layer 3 is **not implemented**. The `summ` schema below exists in the DDL and has SQL tests (`tests/sql/50_summ_test.sql`), but **no code writes it** and **no data exists**. The summariser that will fill it is not chosen. Field names, statuses and shapes may change before layer 3 lands; do not treat this section as a stable contract.

What the DDL defines today:
- **`summ.summary`**: one per (ruling, preset); unique `(ruling_id, preset_code)`.
- **`summ.summary_version`**: versions of a summary: `version_no` (max + 1), `origin` (`generated | repaired | regenerated | expert_edit`), `parent_version_id` (required unless `generated`), `preset_version_id`, `component_version_id`, `source_segmentation_id`, `creator_kind` (`pipeline | expert`), creator run or actor, `quality_status` (`draft | verified | flagged | rejected`), `is_current` (one current version per summary), `mode`, span.
- **`summ.summary_text`**: exactly one German and one French text per version (checked at commit): `language` (`de | fr`), `title_line`, `body`, `word_count`, `paragraph_count` (1..20), `llm_call_id`, `repair_llm_call_id`.
- **`summ.summary_claim`**: statements of a text: `section` (`facts | law | application | outcome | practice`), `model_text` (≤ 300 characters), `rendered_text`, `status` (`verified | flagged | rejected`), `edited_from_claim_id`.
- **`summ.claim_citation`**: claim → consideration (must belong to the version's source segmentation).
- **`summ.verification_check`**: one check per claim or text: `rule_id` (verify rules `V1_IDS_IN_SET` … `V6_ACTING_PARTY`), `status` (`pass | fail | not_applicable`).
- **`summ.preset`**, **`summ.preset_version`**, **`summ.preset_version_prompt`**, **`summ.perspective_anchor`**: presets of a summary; seeded: preset `suva_house` (name DE `Suva-Stil`, FR `Style Suva`, perspective 5, style `by_ruling_language`, mandatory, selectable) and anchors 0, 3, 5, 7, 10 (labels DE/FR, status `draft`, no rubric yet).
- **`summ.v_summary_current`**: the current version per (ruling, preset) with both texts, the verifier status and the latest expert review.
- **`summ.v_mandatory_summary_gaps`**: the in-scope rulings of the current release that lack a non-rejected `suva_house` summary (a release gate).
- Write paths: `summ.create_expert_version(...)` (expert edit), `gold.submit_review('summary_version', …, 'validated'|'rejected', …)`, `ops.submit_request('summary', …)`.

Elsewhere in the repo, outside this data layer:
- `src/summarize/summarize.py` on `main`: a probe generator (reads a parquet, writes `data/trial/<docket>.json`, no database).
- Branches `handoff/components`, `summarize/extract`, `summarize/refine`, `triage/apertus-features`: summary pipelines and a summary workspace (generate, edit, confirm, revise with 9 revision reasons) that write the **other** data layer (`db/migrations`: `summaries`, `summary_events`, `model_runs`), not `summ.*`.
- Targets described in the docs (not built): German and French each written from the source, never translated; Suva's structure (title line `BGer-Urteil <docket> vom <date>` / `Arrêt du TF <docket> du <date>`, plain paragraphs, bger.ch link, no author line); references rendered by code from consideration ids; six verifier checks per statement (`docs/ARCHITECTURE.md` S6-S7, `docs/CHALLENGE.md` §8, `docs/DB_DDL_PLANNING.md` §13).

## 14. Run files on disk (`data/runs/<run_id>/`, git-ignored)

Each run writes its files first, then loads the database in one transaction. The files hold the same facts as the database rows, plus a few fields that exist only there.

| Run | File | One record = | Keys |
|---|---|---|---|
| layer 1 | `decisions.jsonl` | one ruling | `run_id, ruling_id, docket, decision_date, text_id, input_fingerprint, in_suva_scope, reason_code, score_0_100, rubric, rubric_source, subject, text, evaluations[] {rule_code, effect, ordinal, outcome, evidence_field, examined_value, char_start, char_end, matched_text, detail}, explanation_de` |
| layer 1 | `layer1_log.json` | the run | `schema_version, phase, phase_kind, run, population, actions, quality, assets` |
| layer 1 | `manifest.json` | the run | `run_id, step, version, profile, profile_version, population, rulings, kept, dropped, ledger_rows, outcomes, parity_with_courts, parity_reference, log_checks_passed, golden, files` |
| layer 2 | `layer2_judgements.jsonl` | one ruling | `run_id, ruling_id, docket, decision_date, language, repetition, upstream_assessment_id, text_id, text_sha256, input_fingerprint, outcome, reason_code, score_source, score_raw, score_0_100, reading {p_ja, p_nein, p_yes, mass, logprob_yes, logprob_no, logit, yes_no_in_top, top20_floor, top_logprobs}, prepared {chars_total, chars_sent, truncation, neutralised}, messages_sha256, cache_key, requested_model, served_model, attempts, cache_hit, input_tokens, latency_ms, error, explanation_de, started_at, finished_at` |
| layer 2 | `llm_attempts.jsonl` | one attempt or cache hit | `at, attempt, cache_hit, cache_key, content, endpoint, error, finish_reason, index, latency_s, messages_sha256, mode, params, prompt_version, requested, served, status, trace, usage` |
| layer 2 | `messages.jsonl` | one message set | `sha256, content` |
| layer 2 | `manifest.json` | the run | `run_id, step, version, profile, profile_version, kind, mode, population, layer1_run, judge_declared, judge_requested, model_override, client_size, prompt, prompt_template_sha256, status, metrics, files` |

Committed aggregates (no Suva label per docket): `results/layer1_validation.json`, `results/layer1_validation_reference.json`, `results/ingest_closure.json`, `results/layer2_validation.json`, `results/layer2_q2_2026.json`; expected outputs per version in `expected/ingest/`, `expected/layer1/`, `expected/layer2/`.

## Appendix A. Every enum (`ops.*`)

| Enum | Values |
|---|---|
| `ops.artifact_kind` | ranked_csv \| plain_list \| summaries_md \| ingestion_report \| authored_export \| log_bundle \| other |
| `ops.assessment_outcome` | ok \| failed \| skipped |
| `ops.bump_kind` | initial \| major \| minor \| patch |
| `ops.check_status` | pass \| fail \| not_applicable |
| `ops.claim_section` | facts \| law \| application \| outcome \| practice |
| `ops.claim_status` | verified \| flagged \| rejected |
| `ops.creator_kind` | pipeline \| expert |
| `ops.in_suva_scope` | in_scope \| out_of_scope \| potentially |
| `ops.label_source` | suva_relevance_list \| suva_summary_export |
| `ops.lang_code` | de \| fr \| it |
| `ops.log_level` | debug \| info \| warning \| error \| critical |
| `ops.member_basis` | decision_date \| publication_exact \| publication_approx \| reference |
| `ops.model_role` | judge \| generator \| repair |
| `ops.outcome_kind` | upheld \| partly_upheld \| dismissed \| inadmissible \| remanded \| other |
| `ops.party_check_status` | pass \| fail_suva_not_party \| fail_party_not_in_block \| not_applicable |
| `ops.pipeline_step` | ingest \| segment \| parse \| layer1_filter \| layer2_judge \| justification \| ranking \| summarise \| verify \| export |
| `ops.population_definition` | decision_date \| publication_date \| union \| reference |
| `ops.population_role` | target \| labelled \| reference |
| `ops.publication_quality` | exact \| approx_first_seen |
| `ops.publication_source` | neuheiten \| hf_poller \| hf_first_seen |
| `ops.reason_domain` | triage \| verify \| ingest \| work \| summary |
| `ops.registry_status` | draft \| active \| deprecated \| retired |
| `ops.request_kind` | add_judgement \| summary |
| `ops.request_status` | pending \| accepted \| done \| failed \| rejected |
| `ops.review_target` | scope \| summary_version |
| `ops.review_verdict` | correct \| incorrect \| validated \| rejected \| relevant \| not_relevant \| withdrawn (the last three: D-093, after this snapshot) |
| `ops.rule_kind` | keep \| drop \| flag \| signal \| check |
| `ops.rule_outcome` | fired \| not_fired \| not_applicable \| blocked |
| `ops.ruling_origin` | base_dataset \| user_added |
| `ops.run_kind` | load \| ingest \| segment \| parse \| layer1 \| layer2 \| justify \| rank \| summarise \| verify \| export \| refit \| eval \| full |
| `ops.run_mode` | LIVE \| REPLAY |
| `ops.run_status` | running \| succeeded \| failed \| partial \| aborted |
| `ops.schema_subject` | step_config \| rule_definition \| preset_config \| review_payload |
| `ops.score_source` | judged \| signals_only \| net \| failed |
| `ops.segmentation_method` | hf_erwaegungen \| own_splitter |
| `ops.segmentation_status` | ok \| partial \| failed |
| `ops.source_kind` | hf_bger \| hf_erwaegungen \| hf_structure \| bger_neuheiten \| bger_ruling_page \| judgements_workbook \| judgements_export \| models_md \| team_list_2096 \| registry_seed |
| `ops.span_status` | running \| ok \| error \| skipped \| cancelled |
| `ops.subject_source` | neuheiten \| hf_legal_area |
| `ops.summary_quality` | draft \| verified \| flagged \| rejected |
| `ops.summary_style` | rule_statement \| narrative \| by_ruling_language |
| `ops.summary_version_origin` | generated \| repaired \| regenerated \| expert_edit |
| `ops.text_source` | hf \| bger \| entscheidsuche \| opencaselaw |
| `ops.triggered_by` | cli \| api \| ci |
| `ops.work_status` | todo \| running \| done \| failed \| skipped |

## Appendix B. Every column of every relation

`filled` = rows where the column is not null, over the relation's rows, in this snapshot.


### `audit.change_log` (table, 103 rows)

Change log of mutable rows. actor and run_id come from the session settings app.actor and app.run_id. Append-only.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `change_id` | bigint | no | 103 / 103 |  |
| `occurred_at` | timestamp with time zone | no | 103 / 103 |  |
| `table_name` | text | no | 103 / 103 |  |
| `action` | text | no | 103 / 103 |  |
| `row_pk` | jsonb | no | 103 / 103 |  |
| `actor` | text | yes | 103 / 103 |  |
| `run_id` | uuid | yes | 16 / 103 |  |
| `db_role` | text | no | 103 / 103 | The role the session acted as: its SET ROLE role (the pipeline group suva_g_pipeline for every pipeline session, F-11), else its login. Written by audit.log_change(), which runs as the owner (SECURITY DEFINER), so it reads the session's role setting, not current_user (which is the owner there). |
| `old_row` | jsonb | yes | 10 / 103 |  |
| `new_row` | jsonb | yes | 103 / 103 |  |

### `corpus.consideration` (table, 0 rows)

One consideration (Erwägung). cid c1..cn is what Apertus sees and may cite (G1); e_number is the court's numbering, rendered E. x / consid. x by code (D-037). e_number "0" = unnumbered reasoning, not citable. Id = uuid5('consideration\|<segmentation_id>\|<ordinal>'). Append-only.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `consideration_id` | uuid | no | 0 / 0 |  |
| `segmentation_id` | uuid | no | 0 / 0 |  |
| `ordinal` | integer | no | 0 / 0 |  |
| `cid` | text | yes | 0 / 0 |  |
| `e_number` | text | no | 0 / 0 |  |
| `depth` | smallint | no | 0 / 0 |  |
| `parent_consideration_id` | uuid | yes | 0 / 0 |  |
| `is_citable` | boolean | yes | 0 / 0 |  |
| `char_start` | integer | yes | 0 / 0 |  |
| `char_end` | integer | yes | 0 / 0 |  |
| `content` | text | no | 0 / 0 |  |
| `content_sha256` | character(64) | no | 0 / 0 |  |
| `created_at` | timestamp with time zone | no | 0 / 0 |  |

### `corpus.ingest_exclusion` (table, 188,811 rows)

Every row of a source file that was NOT loaded, with its reason (G5, F-04): OUT_OF_WINDOW (in no population window), ING_TWIN_SAME_DATE (a same-date duplicate row that is not a source ref: its base row is not loaded, detail.base_reason naming why; or its base is loaded but the certified window filter does not read the twin, detail.base_loaded = true and detail.why = twin_not_read, so the ruling is loaded without this twin id among its refs), ING_DECISION_DATE_MISSING, ING_DOCKET_MALFORMED (in a window, not a docket), ING_SOURCE_ID_MISSING and ING_SOURCE_ID_DUPLICATE (a row without a usable id of its own, recorded as row:<index>). With corpus.ruling_source_ref it accounts for every row: ops.source_snapshot.row_count = refs + exclusions (corpus.v_ingest_closure). A (snapshot, source, external_id) is either here or a source ref, never both (trigger). Append-only.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `snapshot_id` | uuid | no | 188,811 / 188,811 |  |
| `source` | text | no | 188,811 / 188,811 | The kind of source row id, as in corpus.ruling_source_ref; it fixes the kind of file the snapshot must be (trigger): hf_decision_id -> hf_bger, aza_id -> bger_neuheiten or bger_ruling_page, team_list_2096 -> team_list_2096. |
| `external_id` | text | no | 188,811 / 188,811 | The row's id in the source (hf_decision_id: the HF decision_id). A row without a usable id (missing or duplicate) is recorded as row:<index> in the file. |
| `docket_raw` | text | yes | 188,811 / 188,811 | The docket exactly as the source wrote it, unchecked: a malformed docket is a reason to exclude, not to refuse the row. |
| `decision_date` | date | yes | 188,811 / 188,811 |  |
| `reason_code` | text | no | 188,811 / 188,811 | An ingest reason (domain ingest), or OUT_OF_WINDOW (trigger). |
| `detail` | jsonb | no | 188,811 / 188,811 | The values the decision compared: decision, publication and first-seen dates, the base id of a twin (with base_reason, or base_loaded and why), the windows. Identity fields only, never ruling text. |
| `component_version_id` | uuid | no | 188,811 / 188,811 | The ingest step version whose windows and rules decided the exclusion (trigger: an ingest version). |
| `run_id` | uuid | no | 188,811 / 188,811 |  |
| `created_at` | timestamp with time zone | no | 188,811 / 188,811 |  |

### `corpus.ingest_issue` (table, 0 rows)

A counted, auditable reason for a gap (no text, considerations missing, count mismatch, publication unknown...): G5. Append-only.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `issue_id` | uuid | no | 0 / 0 |  |
| `ruling_id` | uuid | no | 0 / 0 |  |
| `reason_code` | text | no | 0 / 0 |  |
| `detail` | jsonb | no | 0 / 0 |  |
| `run_id` | uuid | no | 0 / 0 |  |
| `span_id` | uuid | yes | 0 / 0 |  |
| `created_at` | timestamp with time zone | no | 0 / 0 |  |

### `corpus.population` (table, 6 rows)

A set of rulings: 2026Q2_union (target), 2026Q2_decision, 2026Q2_publication (delivery default, D-052), 2025Q4_decision, 2026Q1_decision (labelled), suva_reference. Both date readings coexist (D-050). Id = uuid5('population\|<code>'). Frozen = no new member.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `population_id` | uuid | no | 6 / 6 |  |
| `code` | text | no | 6 / 6 |  |
| `quarter` | text | yes | 5 / 6 |  |
| `definition` | ops.population_definition | no | 6 / 6 |  |
| `role` | ops.population_role | no | 6 / 6 |  |
| `is_delivery_default` | boolean | no | 6 / 6 |  |
| `description` | text | yes | 6 / 6 |  |
| `manifest_sha256` | character(64) | yes | 6 / 6 |  |
| `frozen_at` | timestamp with time zone | yes | 6 / 6 |  |
| `built_by_run_id` | uuid | no | 6 / 6 |  |
| `created_at` | timestamp with time zone | no | 6 / 6 |  |
| `updated_at` | timestamp with time zone | no | 6 / 6 |  |

### `corpus.population_member` (table, 10,792 rows)

Membership and why (decision date, exact or approximate publication date). Append-only; refused once the population is frozen.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `population_id` | uuid | no | 10,792 / 10,792 |  |
| `ruling_id` | uuid | no | 10,792 / 10,792 |  |
| `basis` | ops.member_basis | no | 10,792 / 10,792 |  |
| `created_at` | timestamp with time zone | no | 10,792 / 10,792 |  |

### `corpus.publication_observation` (table, 6,055 rows)

What a source says about the publication date. Exact only from a Neuheiten page (ours, or HF's poller from 19 May 2026); a first-seen date is an approximation, never a publication date (D-050). Append-only.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `observation_id` | uuid | no | 6,055 / 6,055 |  |
| `ruling_id` | uuid | no | 6,055 / 6,055 |  |
| `source` | ops.publication_source | no | 6,055 / 6,055 |  |
| `quality` | ops.publication_quality | no | 6,055 / 6,055 |  |
| `observed_date` | date | no | 6,055 / 6,055 |  |
| `star` | boolean | yes | 0 / 6,055 |  |
| `sachgebiet` | text | yes | 0 / 6,055 |  |
| `snapshot_id` | uuid | no | 6,055 / 6,055 |  |
| `created_at` | timestamp with time zone | no | 6,055 / 6,055 |  |

### `corpus.ruling` (table, 6,055 rows)

Identity of one Federal Court decision. Key (docket, decision_date): one docket can hold several decisions. Id = uuid5('bger\|<docket>\|<YYYY-MM-DD>'), set or checked by trigger. docs/DB_DDL_PLANNING.md §8.4.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `ruling_id` | uuid | no | 6,055 / 6,055 |  |
| `docket` | text | no | 6,055 / 6,055 |  |
| `decision_date` | date | no | 6,055 / 6,055 |  |
| `court` | text | yes | 6,055 / 6,055 |  |
| `register_letter` | text | yes | 6,055 / 6,055 |  |
| `filing_year` | smallint | yes | 6,055 / 6,055 |  |
| `quarter_by_decision` | text | yes | 6,055 / 6,055 |  |
| `language` | ops.lang_code | no | 6,055 / 6,055 |  |
| `gegenstand` | text | yes | 6,007 / 6,055 | HF title (the Gegenstand). NULL when empty (47 of the 2,096 Q2 rulings). |
| `previous_instance` | text | yes | 5,413 / 6,055 |  |
| `bger_url` | text | no | 6,055 / 6,055 | Built by code from the aza:// id, never typed by a model (G1). |
| `origin` | ops.ruling_origin | no | 6,055 / 6,055 |  |
| `created_by_run_id` | uuid | no | 6,055 / 6,055 |  |
| `created_at` | timestamp with time zone | no | 6,055 / 6,055 |  |

### `corpus.ruling_parse` (table, 0 rows)

Parse of one text by one parser version: parties block, bench size, operative part, outcome (taken by code from the operative part). Names of natural persons are never extracted (D-038). Append-only.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `parse_id` | uuid | no | 0 / 0 |  |
| `ruling_id` | uuid | no | 0 / 0 |  |
| `text_id` | uuid | no | 0 / 0 |  |
| `component_version_id` | uuid | no | 0 / 0 |  |
| `parties_block` | text | yes | 0 / 0 |  |
| `bench_size` | smallint | yes | 0 / 0 |  |
| `operative_part` | text | yes | 0 / 0 |  |
| `outcome` | ops.outcome_kind | yes | 0 / 0 |  |
| `outcome_rule_id` | uuid | yes | 0 / 0 |  |
| `facts_start` | integer | yes | 0 / 0 |  |
| `considerations_start` | integer | yes | 0 / 0 |  |
| `dispositive_start` | integer | yes | 0 / 0 |  |
| `clean_length` | integer | yes | 0 / 0 |  |
| `created_by_run_id` | uuid | no | 0 / 0 |  |
| `span_id` | uuid | yes | 0 / 0 |  |
| `created_at` | timestamp with time zone | no | 0 / 0 |  |

### `corpus.ruling_source_ref` (table, 6,072 rows)

Every source row behind a ruling (hf_decision_id, aza_id, team_list_2096), twins included, per snapshot: an HF -DYYYYMMDD row is a twin only when its base row has the same date. One row per (snapshot, source, external_id): a new revision of the file records the rows it loads again, so every snapshot closes on its own (corpus.v_ingest_closure, F-04), and a row whose docket or date changed points to its new ruling. A (snapshot, source, external_id) is either here or in corpus.ingest_exclusion, never both (trigger). Append-only.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `source` | text | no | 6,072 / 6,072 |  |
| `external_id` | text | no | 6,072 / 6,072 |  |
| `ruling_id` | uuid | no | 6,072 / 6,072 |  |
| `snapshot_id` | uuid | no | 6,072 / 6,072 |  |
| `is_twin` | boolean | no | 6,072 / 6,072 |  |
| `created_at` | timestamp with time zone | no | 6,072 / 6,072 |  |

### `corpus.ruling_text` (table, 6,055 rows)

Text versions of a ruling. A second text (e.g. a bger.ch fidelity sample) is a new row, never an overwrite. content_sha256 is checked by trigger. Id = uuid5('text\|<ruling_id>\|<source>\|<content_sha256>'). Only is_primary may change.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `text_id` | uuid | no | 6,055 / 6,055 |  |
| `ruling_id` | uuid | no | 6,055 / 6,055 |  |
| `source` | ops.text_source | no | 6,055 / 6,055 |  |
| `content` | text | no | 6,055 / 6,055 | The text, with at least one character that is not whitespace. Whitespace is the set of Python's str.isspace() (tab, newline, no-break and other Unicode spaces), the definition the layer-1 engine and the HF loader use for an absent text (text.strip() == ''): a blank text is no text (ING_TEXT_MISSING), never a row, so layer 1 never meets a stored text it treats as absent (its trigger refuses why text_absent on an assessment with an input text). tests/test_layer1_db.py proves the two definitions agree. |
| `content_sha256` | character(64) | no | 6,055 / 6,055 |  |
| `char_length` | integer | yes | 6,055 / 6,055 |  |
| `clean_length` | integer | yes | 0 / 6,055 |  |
| `is_primary` | boolean | no | 6,055 / 6,055 |  |
| `snapshot_id` | uuid | no | 6,055 / 6,055 |  |
| `fetched_at` | timestamp with time zone | yes | 0 / 6,055 |  |
| `created_at` | timestamp with time zone | no | 6,055 / 6,055 |  |
| `updated_at` | timestamp with time zone | no | 6,055 / 6,055 |  |

### `corpus.segmentation` (table, 0 rows)

One splitting of a text into considerations, by one splitter version, with its quality. The splitter matures on samples; a version becomes primary at count match >= 99 % and coverage >= 98 %, written before measuring (D-070). Id = uuid5('segmentation\|<text_id>\|<component_version_id>'). Only is_primary may change.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `segmentation_id` | uuid | no | 0 / 0 |  |
| `text_id` | uuid | no | 0 / 0 |  |
| `component_version_id` | uuid | no | 0 / 0 |  |
| `method` | ops.segmentation_method | no | 0 / 0 |  |
| `status` | ops.segmentation_status | no | 0 / 0 |  |
| `consideration_count` | integer | no | 0 / 0 |  |
| `expected_count` | integer | yes | 0 / 0 |  |
| `coverage_ratio` | numeric(6,5) | yes | 0 / 0 |  |
| `offsets_found_ratio` | numeric(6,5) | yes | 0 / 0 |  |
| `is_primary` | boolean | no | 0 / 0 |  |
| `created_by_run_id` | uuid | no | 0 / 0 |  |
| `span_id` | uuid | yes | 0 / 0 |  |
| `created_at` | timestamp with time zone | no | 0 / 0 |  |
| `updated_at` | timestamp with time zone | no | 0 / 0 |  |

### `corpus.subject_observation` (table, 4,327 rows)

The matter rubric (Sachgebiet) a source states: the Neuheiten page (authoritative, with the publication star) or HF legal_area (empty for most Q2/2026 rulings). Layer 1 reads neuheiten > hf_legal_area > the head of gegenstand, and records which one it used (D-072). Append-only.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `observation_id` | uuid | no | 4,327 / 4,327 |  |
| `ruling_id` | uuid | no | 4,327 / 4,327 |  |
| `source` | ops.subject_source | no | 4,327 / 4,327 |  |
| `rubric` | text | no | 4,327 / 4,327 |  |
| `star` | boolean | yes | 0 / 4,327 |  |
| `snapshot_id` | uuid | no | 4,327 / 4,327 |  |
| `created_at` | timestamp with time zone | no | 4,327 / 4,327 |  |

### `corpus.v_ingest_closure` (view, 1 rows)

Every row of a source file accounted for (F-04, G5), per snapshot that has source refs or exclusions: closure_ok = row_count = loaded refs (base + twins) + exclusions. Source refs are kept per snapshot, so a new revision of a file closes on its own, the rows an earlier revision loaded included. A row with a missing or duplicate source id is recorded as row:<index> (exclusions_by_row_index) and counted inside exclusions. unaccounted_rows > 0 = rows lost without a reason; NULL row_count = closure unknown (false).

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `snapshot_id` | uuid | yes | 1 / 1 |  |
| `source` | ops.source_kind | yes | 1 / 1 |  |
| `revision` | text | yes | 1 / 1 |  |
| `file_sha256` | character(64) | yes | 1 / 1 |  |
| `row_count` | bigint | yes | 1 / 1 |  |
| `loaded_refs` | bigint | yes | 1 / 1 |  |
| `base_refs` | bigint | yes | 1 / 1 |  |
| `twin_refs` | bigint | yes | 1 / 1 |  |
| `exclusions` | bigint | yes | 1 / 1 |  |
| `exclusions_by_reason` | jsonb | yes | 1 / 1 |  |
| `exclusions_by_row_index` | bigint | yes | 1 / 1 |  |
| `unaccounted_rows` | bigint | yes | 1 / 1 |  |
| `closure_ok` | boolean | yes | 1 / 1 |  |

### `corpus.v_ruling` (view, 6,055 rows)

Ruling with its best publication date (Neuheiten > HF poller), the approximation kept apart, quarter_by_publication from exact dates only (D-050), primary text and segmentation.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `ruling_id` | uuid | yes | 6,055 / 6,055 |  |
| `docket` | text | yes | 6,055 / 6,055 |  |
| `decision_date` | date | yes | 6,055 / 6,055 |  |
| `court` | text | yes | 6,055 / 6,055 |  |
| `register_letter` | text | yes | 6,055 / 6,055 |  |
| `filing_year` | smallint | yes | 6,055 / 6,055 |  |
| `language` | ops.lang_code | yes | 6,055 / 6,055 |  |
| `gegenstand` | text | yes | 6,007 / 6,055 |  |
| `previous_instance` | text | yes | 5,413 / 6,055 |  |
| `bger_url` | text | yes | 6,055 / 6,055 |  |
| `origin` | ops.ruling_origin | yes | 6,055 / 6,055 |  |
| `quarter_by_decision` | text | yes | 6,055 / 6,055 |  |
| `publication_date` | date | yes | 1,435 / 6,055 |  |
| `publication_source` | ops.publication_source | yes | 1,435 / 6,055 |  |
| `publication_date_approx` | date | yes | 4,620 / 6,055 |  |
| `publication_quality` | text | yes | 6,055 / 6,055 |  |
| `quarter_by_publication` | text | yes | 1,435 / 6,055 |  |
| `star` | boolean | yes | 0 / 6,055 |  |
| `sachgebiet` | text | yes | 0 / 6,055 |  |
| `primary_text_id` | uuid | yes | 6,055 / 6,055 |  |
| `char_length` | integer | yes | 6,055 / 6,055 |  |
| `clean_length` | integer | yes | 0 / 6,055 |  |
| `primary_segmentation_id` | uuid | yes | 0 / 6,055 |  |
| `consideration_count` | integer | yes | 0 / 6,055 |  |

### `gold.expert_review` (table, 0 rows)

Expert opinions, append-only and apart from the pipeline's label (D-066, D-093). Scope review: relevant \| not_relevant = the expert's own label on any pipeline label (potentially included); correct \| incorrect = the V1 relative verdict, only on in_scope or out_of_scope. Summary review: validated \| rejected. withdrawn (both kinds) supersedes the review it takes back, of the same target and never a withdrawal; the target then has no expert opinion until a new review. reviewed_label = the label the expert saw (copied from the assessment); payload follows review_schema_id (scope_review.payload V1.1.0: what the expert saw, shown_status and shown scores). Inserted only through gold.submit_review(). actor is a pseudonymous handle (G13).

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `review_id` | uuid | no | 0 / 0 |  |
| `target_kind` | ops.review_target | no | 0 / 0 |  |
| `assessment_id` | uuid | yes | 0 / 0 |  |
| `summary_version_id` | uuid | yes | 0 / 0 |  |
| `verdict` | ops.review_verdict | no | 0 / 0 |  |
| `reviewed_label` | ops.in_suva_scope | yes | 0 / 0 |  |
| `review_schema_id` | uuid | no | 0 / 0 |  |
| `payload` | jsonb | no | 0 / 0 |  |
| `actor` | text | no | 0 / 0 |  |
| `comment` | text | yes | 0 / 0 |  |
| `supersedes_review_id` | uuid | yes | 0 / 0 |  |
| `span_id` | uuid | yes | 0 / 0 |  |
| `created_at` | timestamp with time zone | no | 0 / 0 |  |

### `gold.label` (table, 115 rows)

Suva's truth: a row of its relevance list or one of its 55 exports. external_title = the cantonal row (Q-28), which has no Federal Court ruling. Append-only. Negatives are a view (closed world, Q-04), never stored.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `label_id` | uuid | no | 115 / 115 |  |
| `ruling_id` | uuid | yes | 114 / 115 |  |
| `external_title` | text | yes | 1 / 115 |  |
| `source` | ops.label_source | no | 115 / 115 |  |
| `in_suva_scope` | boolean | no | 115 / 115 |  |
| `quarter_label` | text | yes | 60 / 115 |  |
| `source_ref` | text | no | 115 / 115 |  |
| `snapshot_id` | uuid | no | 115 / 115 |  |
| `created_by_run_id` | uuid | no | 115 / 115 |  |
| `created_at` | timestamp with time zone | no | 115 / 115 |  |

### `gold.suva_summary` (table, 0 rows)

Suva's 55 human summaries, parsed (DS5): only docket, dates, Text DE, Text FR and the bger.ch link (D-051). Id = uuid5('suva_summary\|<source_file>'). Append-only.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `suva_summary_id` | uuid | no | 0 / 0 |  |
| `docket` | text | no | 0 / 0 |  |
| `decision_date` | date | no | 0 / 0 |  |
| `ruling_id` | uuid | yes | 0 / 0 |  |
| `ruling_language` | ops.lang_code | yes | 0 / 0 |  |
| `text_de` | text | no | 0 / 0 |  |
| `text_fr` | text | no | 0 / 0 |  |
| `bger_url` | text | no | 0 / 0 |  |
| `source_file` | text | no | 0 / 0 |  |
| `style_observed` | text | yes | 0 / 0 |  |
| `word_count_de` | integer | yes | 0 / 0 |  |
| `word_count_fr` | integer | yes | 0 / 0 |  |
| `snapshot_id` | uuid | no | 0 / 0 |  |
| `created_at` | timestamp with time zone | no | 0 / 0 |  |

### `gold.v_expert_review_current` (view, 0 rows)

The latest non-superseded review per target.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `review_id` | uuid | yes | 0 / 0 |  |
| `target_kind` | ops.review_target | yes | 0 / 0 |  |
| `assessment_id` | uuid | yes | 0 / 0 |  |
| `summary_version_id` | uuid | yes | 0 / 0 |  |
| `verdict` | ops.review_verdict | yes | 0 / 0 |  |
| `reviewed_label` | ops.in_suva_scope | yes | 0 / 0 |  |
| `review_schema_id` | uuid | yes | 0 / 0 |  |
| `payload` | jsonb | yes | 0 / 0 |  |
| `actor` | text | yes | 0 / 0 |  |
| `comment` | text | yes | 0 / 0 |  |
| `supersedes_review_id` | uuid | yes | 0 / 0 |  |
| `span_id` | uuid | yes | 0 / 0 |  |
| `created_at` | timestamp with time zone | yes | 0 / 0 |  |

### `gold.v_label_effective` (view, 3,936 rows)

Suva's labels on the labelled populations; every unlisted member is false with basis closed_world (Q-04: an assumption, shown as such). has_suva_summary marks the must-hit subset.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `population_id` | uuid | yes | 3,936 / 3,936 |  |
| `population_code` | text | yes | 3,936 / 3,936 |  |
| `ruling_id` | uuid | yes | 3,936 / 3,936 |  |
| `in_suva_scope` | boolean | yes | 3,936 / 3,936 |  |
| `basis` | text | yes | 3,936 / 3,936 |  |
| `has_suva_summary` | boolean | yes | 3,936 / 3,936 |  |

### `ops.artifact` (table, 0 rows)

Files a run wrote, with their SHA-256 (pipeline step 7: results/ with hash). The export endpoint must equal the hashed file. Append-only.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `artifact_id` | uuid | no | 0 / 0 |  |
| `run_id` | uuid | no | 0 / 0 |  |
| `release_id` | uuid | yes | 0 / 0 |  |
| `kind` | ops.artifact_kind | no | 0 / 0 |  |
| `path` | text | no | 0 / 0 |  |
| `sha256` | character(64) | no | 0 / 0 |  |
| `row_count` | bigint | yes | 0 / 0 |  |
| `created_at` | timestamp with time zone | no | 0 / 0 |  |

### `ops.blob` (table, 912 rows)

Content-addressed payloads: prompt messages, oversized log attributes, raw pages. Insert with ON CONFLICT DO NOTHING. Append-only.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `sha256` | character(64) | no | 912 / 912 |  |
| `media_type` | text | no | 912 / 912 |  |
| `byte_size` | bigint | no | 912 / 912 |  |
| `content` | text | no | 912 / 912 |  |
| `created_at` | timestamp with time zone | no | 912 / 912 |  |

### `ops.component_version` (table, 5 rows)

One version (V<major>.<minor>.<patch>) of one pipeline step: code hash, configuration (jsonb, shape checked by the application against config_schema_id), models, prompts, rules, and the decision and validation file that approved it. MAJOR = outputs not comparable, MINOR = re-measure, PATCH = identical outputs. Insert-only except status. Id = uuid5('cv\|<step>\|<major>\|<minor>\|<patch>'). docs/DB_DDL_PLANNING.md §7.1, §7.3.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `component_version_id` | uuid | no | 5 / 5 |  |
| `step` | ops.pipeline_step | no | 5 / 5 |  |
| `name` | text | no | 5 / 5 |  |
| `v_major` | smallint | no | 5 / 5 |  |
| `v_minor` | smallint | no | 5 / 5 |  |
| `v_patch` | smallint | no | 5 / 5 |  |
| `version_label` | text | yes | 5 / 5 |  |
| `config_schema_id` | uuid | no | 5 / 5 |  |
| `config` | jsonb | no | 5 / 5 | Step configuration. The DB checks only that it is an object; its shape is versioned in ops.json_schema (§7.4). |
| `config_sha256` | character(64) | no | 5 / 5 |  |
| `code_path` | text | no | 5 / 5 |  |
| `code_sha256` | character(64) | no | 5 / 5 |  |
| `git_commit` | character(40) | yes | 0 / 5 |  |
| `status` | ops.registry_status | no | 5 / 5 |  |
| `bump_kind` | ops.bump_kind | no | 5 / 5 |  |
| `previous_version_id` | uuid | yes | 2 / 5 |  |
| `changelog` | text | no | 5 / 5 |  |
| `decision_ref` | text | yes | 5 / 5 | The docs/DECISIONS.md line that approved this version (D-NNN), from the registry file (F-12). NULL only for rows written before the registry carried it; insert-only like the rest of the row, so the loader compares it strictly. |
| `validation_ref` | text | yes | 5 / 5 | The certified expected file that validates this version (e.g. expected/layer1/V1.1.0.json), from the registry file (F-12). Repo-relative path under expected/; NULL when the version has no certified output yet. |
| `created_by_actor` | text | yes | 5 / 5 |  |
| `created_at` | timestamp with time zone | no | 5 / 5 |  |
| `updated_at` | timestamp with time zone | no | 5 / 5 |  |

### `ops.component_version_model` (table, 1 rows)

The model each step version declares per role (N9). The run records the models actually resolved (judges may set LLM_NAME). docs/DB_DDL_PLANNING.md §7.2.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `component_version_id` | uuid | no | 1 / 1 |  |
| `model_role` | ops.model_role | no | 1 / 1 |  |
| `model_id` | uuid | no | 1 / 1 |  |
| `created_at` | timestamp with time zone | no | 1 / 1 |  |

### `ops.component_version_prompt` (table, 1 rows)

The prompt versions a step version uses, per prompt role. Append-only.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `component_version_id` | uuid | no | 1 / 1 |  |
| `prompt_role` | text | no | 1 / 1 |  |
| `prompt_version_id` | uuid | no | 1 / 1 |  |
| `created_at` | timestamp with time zone | no | 1 / 1 |  |

### `ops.component_version_rule` (table, 29 rows)

The rules a step version applies, in order, with their parameters. The rule must belong to the same step (trigger). Append-only, and sealed once an assessment uses the version or a profile pins it: a new rule is a new version, so a certified rule ledger never goes stale (trigger, F-10). Reloading the same binding is a no-op.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `component_version_id` | uuid | no | 29 / 29 |  |
| `rule_id` | uuid | no | 29 / 29 |  |
| `ordinal` | integer | no | 29 / 29 |  |
| `enabled` | boolean | no | 29 / 29 |  |
| `params` | jsonb | no | 29 / 29 |  |
| `created_at` | timestamp with time zone | no | 29 / 29 |  |

### `ops.json_schema` (table, 6 rows)

Versioned JSON Schema templates for step configurations, rule definitions, preset configurations and review payloads. template is a complete example: the starting point of a new version. Id = uuid5('json_schema\|<code>\|<major>\|<minor>\|<patch>'). docs/DB_DDL_PLANNING.md §7.4.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `json_schema_id` | uuid | no | 6 / 6 |  |
| `subject` | ops.schema_subject | no | 6 / 6 |  |
| `schema_code` | text | no | 6 / 6 |  |
| `v_major` | smallint | no | 6 / 6 |  |
| `v_minor` | smallint | no | 6 / 6 |  |
| `v_patch` | smallint | no | 6 / 6 |  |
| `version_label` | text | yes | 6 / 6 |  |
| `json_schema` | jsonb | no | 6 / 6 |  |
| `template` | jsonb | no | 6 / 6 |  |
| `schema_sha256` | character(64) | no | 6 / 6 |  |
| `status` | ops.registry_status | no | 6 / 6 |  |
| `bump_kind` | ops.bump_kind | no | 6 / 6 |  |
| `previous_version_id` | uuid | yes | 0 / 6 |  |
| `changelog` | text | no | 6 / 6 |  |
| `created_by_actor` | text | yes | 6 / 6 |  |
| `created_at` | timestamp with time zone | no | 6 / 6 |  |
| `updated_at` | timestamp with time zone | no | 6 / 6 |  |

### `ops.llm_call` (table, 912 rows)

Every LLM call, invalid outputs included; mirrors data/derived/llm/llm_calls.jsonl. Never the API key (G13). Requested and served model on every row (G3). Append-only. docs/DB_DDL_PLANNING.md §14.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `llm_call_id` | uuid | no | 912 / 912 |  |
| `run_id` | uuid | no | 912 / 912 |  |
| `span_id` | uuid | no | 912 / 912 |  |
| `ruling_id` | uuid | yes | 912 / 912 |  |
| `step` | ops.pipeline_step | no | 912 / 912 |  |
| `purpose` | text | no | 912 / 912 |  |
| `language` | ops.lang_code | yes | 912 / 912 |  |
| `prompt_version_id` | uuid | yes | 912 / 912 |  |
| `cache_key` | character(64) | no | 912 / 912 |  |
| `cache_hit` | boolean | no | 912 / 912 |  |
| `mode` | ops.run_mode | no | 912 / 912 |  |
| `endpoint` | text | no | 912 / 912 |  |
| `model_role` | ops.model_role | yes | 912 / 912 |  |
| `requested_model` | text | no | 912 / 912 |  |
| `served_model` | text | yes | 912 / 912 |  |
| `served_model_header` | text | yes | 0 / 912 |  |
| `params` | jsonb | no | 912 / 912 |  |
| `repetition_idx` | smallint | no | 912 / 912 |  |
| `messages_sha256` | character(64) | yes | 912 / 912 |  |
| `raw_output` | text | yes | 912 / 912 |  |
| `finish_reason` | text | yes | 912 / 912 |  |
| `parsed_ok` | boolean | yes | 912 / 912 |  |
| `parse_error` | text | yes | 0 / 912 |  |
| `http_status` | smallint | yes | 0 / 912 |  |
| `error_reason_code` | text | yes | 0 / 912 |  |
| `attempt` | smallint | no | 912 / 912 |  |
| `input_tokens` | integer | yes | 912 / 912 |  |
| `output_tokens` | integer | yes | 912 / 912 |  |
| `cached_tokens` | integer | yes | 912 / 912 |  |
| `latency_ms` | integer | yes | 0 / 912 |  |
| `started_at` | timestamp with time zone | no | 912 / 912 |  |
| `created_at` | timestamp with time zone | no | 912 / 912 |  |

### `ops.llm_call_example` (table, 0 rows)

The few-shot examples a call carried: proves the judged ruling and the test rulings were never examples (D-021 point 8). Append-only.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `llm_call_id` | uuid | no | 0 / 0 |  |
| `position` | smallint | no | 0 / 0 |  |
| `example_kind` | text | no | 0 / 0 |  |
| `example_ruling_id` | uuid | yes | 0 / 0 |  |
| `suva_summary_id` | uuid | yes | 0 / 0 |  |

### `ops.log_event` (partitioned, 8,802 rows)

Log lines: event_code <step>.<object>.<verb> (catalogue in docs/DB_DDL_PLANNING.md §11.3). Never a key, a full prompt, a D-051 value or a person's name (§11.5); payloads over 16 KB go to ops.blob, referenced by hash. Every level is kept during the event (D-065). Append-only.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `run_id` | uuid | no | 8,802 / 8,802 |  |
| `seq` | bigint | no | 8,802 / 8,802 |  |
| `ts` | timestamp with time zone | no | 8,802 / 8,802 |  |
| `span_id` | uuid | yes | 8,802 / 8,802 |  |
| `ruling_id` | uuid | yes | 8,791 / 8,802 |  |
| `step` | ops.pipeline_step | yes | 8,802 / 8,802 |  |
| `level` | ops.log_level | no | 8,802 / 8,802 |  |
| `event_code` | text | no | 8,802 / 8,802 |  |
| `message` | text | no | 8,802 / 8,802 |  |
| `attributes` | jsonb | no | 8,802 / 8,802 |  |

### `ops.model` (table, 2 rows)

Models, loaded from MODELS.md (the single home of model ids, E6, G3); never typed in SQL. allowed = on the G3 allow-list. Id = uuid5('model\|<gateway_id>'). docs/DB_DDL_PLANNING.md §7.2.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `model_id` | uuid | no | 2 / 2 |  |
| `family` | text | no | 2 / 2 |  |
| `size_label` | text | no | 2 / 2 |  |
| `gateway_id` | text | no | 2 / 2 |  |
| `hf_id` | text | yes | 2 / 2 |  |
| `revision` | text | yes | 0 / 2 |  |
| `allowed` | boolean | no | 2 / 2 |  |
| `source_snapshot_id` | uuid | no | 2 / 2 |  |
| `created_at` | timestamp with time zone | no | 2 / 2 |  |

### `ops.pipeline_profile` (table, 3 rows)

Named pipelines. Exactly one active default: "the default pipeline" whose label is shown and used (D-063). docs/DB_DDL_PLANNING.md §7.6.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `profile_code` | text | no | 3 / 3 |  |
| `name` | text | no | 3 / 3 |  |
| `description` | text | yes | 3 / 3 |  |
| `is_default` | boolean | no | 3 / 3 |  |
| `retired_at` | timestamp with time zone | yes | 0 / 3 |  |
| `created_at` | timestamp with time zone | no | 3 / 3 |  |
| `updated_at` | timestamp with time zone | no | 3 / 3 |  |

### `ops.pipeline_profile_step` (table, 11 rows)

The step versions a profile version pins. Every assessment must come from the version its run's profile pins (trigger in 80_triggers.sql).

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `profile_version_id` | uuid | no | 11 / 11 |  |
| `step` | ops.pipeline_step | no | 11 / 11 |  |
| `component_version_id` | uuid | no | 11 / 11 |  |
| `created_at` | timestamp with time zone | no | 11 / 11 |  |

### `ops.pipeline_profile_version` (table, 5 rows)

A version of a profile, and the decision that approved it. Id = uuid5('profile\|<profile_code>\|<major>\|<minor>\|<patch>'). A version with major >= 1 refuses any V0.x step (trigger).

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `profile_version_id` | uuid | no | 5 / 5 |  |
| `profile_code` | text | no | 5 / 5 |  |
| `v_major` | smallint | no | 5 / 5 |  |
| `v_minor` | smallint | no | 5 / 5 |  |
| `v_patch` | smallint | no | 5 / 5 |  |
| `version_label` | text | yes | 5 / 5 |  |
| `status` | ops.registry_status | no | 5 / 5 |  |
| `bump_kind` | ops.bump_kind | no | 5 / 5 |  |
| `previous_version_id` | uuid | yes | 2 / 5 |  |
| `changelog` | text | no | 5 / 5 |  |
| `decision_ref` | text | yes | 5 / 5 | The docs/DECISIONS.md line that approved this profile version (D-NNN), from src/db/seed/profiles.json (F-12). NULL only for rows written before the seed carried it; insert-only like the rest of the row, so the loader compares it strictly. |
| `created_by_actor` | text | yes | 5 / 5 |  |
| `created_at` | timestamp with time zone | no | 5 / 5 |  |
| `updated_at` | timestamp with time zone | no | 5 / 5 |  |

### `ops.pipeline_run` (table, 4 rows)

One execution (= one trace). Pinned to a profile version. resolved_models = the models actually used per role; model_override = the judges' LLM_NAME differs from the declared models (a release warns, never blocks, D-064). Only status, finished_at, error_summary change after insert. docs/DB_DDL_PLANNING.md §14.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `run_id` | uuid | no | 4 / 4 |  |
| `parent_run_id` | uuid | yes | 0 / 4 |  |
| `profile_version_id` | uuid | no | 4 / 4 |  |
| `kind` | ops.run_kind | no | 4 / 4 |  |
| `mode` | ops.run_mode | no | 4 / 4 |  |
| `status` | ops.run_status | no | 4 / 4 |  |
| `git_commit` | character(40) | yes | 4 / 4 |  |
| `git_dirty` | boolean | no | 4 / 4 |  |
| `params` | jsonb | no | 4 / 4 |  |
| `params_sha256` | character(64) | no | 4 / 4 |  |
| `resolved_models` | jsonb | no | 4 / 4 |  |
| `model_override` | boolean | no | 4 / 4 |  |
| `triggered_by` | ops.triggered_by | no | 4 / 4 |  |
| `actor` | text | yes | 4 / 4 |  |
| `host_label` | text | yes | 0 / 4 | A machine label. Never a person's name (G13). |
| `started_at` | timestamp with time zone | no | 4 / 4 |  |
| `finished_at` | timestamp with time zone | yes | 4 / 4 |  |
| `error_summary` | text | yes | 0 / 4 |  |

### `ops.prompt_version` (table, 1 rows)

Versioned prompts. contains_suva_material = built from judgements/: its exports stay in data/derived/ while D-031 is open. Id = uuid5('prompt\|<role>\|<major>\|<minor>\|<patch>'). docs/DB_DDL_PLANNING.md §14.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `prompt_version_id` | uuid | no | 1 / 1 |  |
| `role` | text | no | 1 / 1 |  |
| `v_major` | smallint | no | 1 / 1 |  |
| `v_minor` | smallint | no | 1 / 1 |  |
| `v_patch` | smallint | no | 1 / 1 |  |
| `version_label` | text | yes | 1 / 1 |  |
| `template_sha256` | character(64) | no | 1 / 1 |  |
| `system_template` | text | no | 1 / 1 |  |
| `user_template` | text | no | 1 / 1 |  |
| `response_schema` | jsonb | yes | 1 / 1 |  |
| `contains_suva_material` | boolean | no | 1 / 1 |  |
| `status` | ops.registry_status | no | 1 / 1 |  |
| `bump_kind` | ops.bump_kind | no | 1 / 1 |  |
| `previous_version_id` | uuid | yes | 0 / 1 |  |
| `changelog` | text | no | 1 / 1 |  |
| `created_by_actor` | text | yes | 1 / 1 |  |
| `created_at` | timestamp with time zone | no | 1 / 1 |  |
| `updated_at` | timestamp with time zone | no | 1 / 1 |  |

### `ops.reason_code` (table, 48 rows)

One vocabulary of reasons for the whole DB (triage drops, verifier checks, ingest issues, work errors). The UI shows label_de, so a lawyer reads a sentence, not a code (G5). docs/DB_DDL_PLANNING.md §7.5.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `code` | text | no | 48 / 48 |  |
| `domain` | ops.reason_domain | no | 48 / 48 |  |
| `label_de` | text | no | 48 / 48 |  |
| `label_fr` | text | yes | 48 / 48 |  |
| `description` | text | yes | 0 / 48 |  |
| `created_at` | timestamp with time zone | no | 48 / 48 |  |
| `updated_at` | timestamp with time zone | no | 48 / 48 |  |

### `ops.release` (table, 0 rows)

What is published: a ranking of a profile version. The current release of the default profile carries "the label" (D-063). Becoming current is gated: every target member labelled, no unexplained potentially, no missing mandatory summary (trigger). warnings records e.g. model_override.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `release_id` | uuid | no | 0 / 0 |  |
| `profile_code` | text | no | 0 / 0 |  |
| `profile_version_id` | uuid | no | 0 / 0 |  |
| `ranking_id` | uuid | no | 0 / 0 |  |
| `created_by_actor` | text | yes | 0 / 0 |  |
| `notes` | text | yes | 0 / 0 |  |
| `is_current` | boolean | no | 0 / 0 |  |
| `warnings` | jsonb | no | 0 / 0 |  |
| `superseded_at` | timestamp with time zone | yes | 0 / 0 |  |
| `created_at` | timestamp with time zone | no | 0 / 0 |  |
| `updated_at` | timestamp with time zone | no | 0 / 0 |  |

### `ops.rule` (table, 11 rows)

Versioned rules (layer-1 keep/drop rules, party checks, verifier checks...). definition is jsonb, its shape versioned in ops.json_schema. Results point to the exact rule version that fired. Id = uuid5('rule\|<rule_code>\|<major>\|<minor>\|<patch>'). docs/DB_DDL_PLANNING.md §7.5.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `rule_id` | uuid | no | 11 / 11 |  |
| `step` | ops.pipeline_step | no | 11 / 11 |  |
| `rule_code` | text | no | 11 / 11 |  |
| `v_major` | smallint | no | 11 / 11 |  |
| `v_minor` | smallint | no | 11 / 11 |  |
| `v_patch` | smallint | no | 11 / 11 |  |
| `version_label` | text | yes | 11 / 11 |  |
| `kind` | ops.rule_kind | no | 11 / 11 |  |
| `definition` | jsonb | no | 11 / 11 |  |
| `definition_schema_id` | uuid | no | 11 / 11 |  |
| `reason_code` | text | no | 11 / 11 |  |
| `description` | text | yes | 11 / 11 |  |
| `status` | ops.registry_status | no | 11 / 11 |  |
| `bump_kind` | ops.bump_kind | no | 11 / 11 |  |
| `previous_version_id` | uuid | yes | 0 / 11 |  |
| `changelog` | text | no | 11 / 11 |  |
| `created_by_actor` | text | yes | 11 / 11 |  |
| `created_at` | timestamp with time zone | no | 11 / 11 |  |
| `updated_at` | timestamp with time zone | no | 11 / 11 |  |

### `ops.run_metric` (table, 56 rows)

Counters and measures per run and step (rulings_in, kept, dropped, llm_calls, latency_p95_ms...). A step with 0 output fails the run (G6). Append-only.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `run_id` | uuid | no | 56 / 56 |  |
| `step` | ops.pipeline_step | no | 56 / 56 |  |
| `metric_code` | text | no | 56 / 56 |  |
| `value` | numeric | no | 56 / 56 |  |
| `unit` | text | no | 56 / 56 |  |
| `measured_at` | timestamp with time zone | no | 56 / 56 |  |

### `ops.source_snapshot` (table, 4 rows)

Every input file a load read: source, revision (HF commit), hash, size. The root of every lineage. Append-only.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `snapshot_id` | uuid | no | 4 / 4 |  |
| `source` | ops.source_kind | no | 4 / 4 |  |
| `revision` | text | yes | 1 / 4 |  |
| `uri` | text | no | 4 / 4 |  |
| `file_sha256` | character(64) | no | 4 / 4 |  |
| `byte_size` | bigint | yes | 2 / 4 |  |
| `row_count` | bigint | yes | 3 / 4 | Every row of the source file, read or not (for hf_bger: all rows of the parquet, not only those a filter let through). Closure (F-04): row_count = loaded source refs + recorded exclusions (corpus.v_ingest_closure). |
| `retrieved_at` | timestamp with time zone | no | 4 / 4 |  |
| `notes` | text | yes | 1 / 4 |  |
| `created_at` | timestamp with time zone | no | 4 / 4 |  |

### `ops.span` (table, 7,883 rows)

A unit of work (one step on one ruling, or an operation inside it: an LLM call, a check). Inserted at start, closed once (trigger). Business rows point to their span. No key, prompt, D-051 value or person's name in attributes (§11.5). docs/DB_DDL_PLANNING.md §11.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `span_id` | uuid | no | 7,883 / 7,883 |  |
| `run_id` | uuid | no | 7,883 / 7,883 |  |
| `parent_span_id` | uuid | yes | 7,879 / 7,883 |  |
| `step` | ops.pipeline_step | yes | 7,883 / 7,883 |  |
| `operation` | text | no | 7,883 / 7,883 |  |
| `ruling_id` | uuid | yes | 7,879 / 7,883 |  |
| `component_version_id` | uuid | yes | 7,882 / 7,883 |  |
| `status` | ops.span_status | no | 7,883 / 7,883 |  |
| `started_at` | timestamp with time zone | no | 7,883 / 7,883 |  |
| `ended_at` | timestamp with time zone | yes | 7,883 / 7,883 |  |
| `duration_ms` | bigint | yes | 7,883 / 7,883 |  |
| `attributes` | jsonb | no | 7,883 / 7,883 |  |
| `error_reason_code` | text | yes | 0 / 7,883 |  |
| `error_message` | text | yes | 0 / 7,883 |  |

### `ops.user_request` (table, 0 rows)

Requests from the UI: "add another judgement" (D-015) by docket or bger.ch link, or a summary of any ruling under any preset. Created only through ops.submit_request(); the pipeline accepts them into a run.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `request_id` | uuid | no | 0 / 0 |  |
| `kind` | ops.request_kind | no | 0 / 0 |  |
| `docket` | text | yes | 0 / 0 |  |
| `bger_url` | text | yes | 0 / 0 |  |
| `ruling_id` | uuid | yes | 0 / 0 |  |
| `preset_code` | text | yes | 0 / 0 |  |
| `status` | ops.request_status | no | 0 / 0 |  |
| `run_id` | uuid | yes | 0 / 0 |  |
| `requested_by_actor` | text | no | 0 / 0 |  |
| `status_detail` | text | yes | 0 / 0 |  |
| `created_at` | timestamp with time zone | no | 0 / 0 |  |
| `updated_at` | timestamp with time zone | no | 0 / 0 |  |

### `ops.v_profile` (view, 11 rows)

Which step versions, models and rules each profile version pins (transparency panel).

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `profile_code` | text | yes | 11 / 11 |  |
| `is_default` | boolean | yes | 11 / 11 |  |
| `profile_version_id` | uuid | yes | 11 / 11 |  |
| `profile_version` | text | yes | 11 / 11 |  |
| `profile_status` | ops.registry_status | yes | 11 / 11 |  |
| `step` | ops.pipeline_step | yes | 11 / 11 |  |
| `component_version_id` | uuid | yes | 11 / 11 |  |
| `component_name` | text | yes | 11 / 11 |  |
| `component_version` | text | yes | 11 / 11 |  |
| `component_status` | ops.registry_status | yes | 11 / 11 |  |
| `code_sha256` | character(64) | yes | 11 / 11 |  |
| `config_sha256` | character(64) | yes | 11 / 11 |  |
| `models` | jsonb | yes | 1 / 11 |  |
| `enabled_rules` | bigint | yes | 11 / 11 |  |

### `ops.v_ruling_timeline` (view, 16,670 rows)

Spans and events of a ruling across runs; order by ts. The transparency timeline of the UI (D-065).

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `ruling_id` | uuid | yes | 16,670 / 16,670 |  |
| `ts` | timestamp with time zone | yes | 16,670 / 16,670 |  |
| `kind` | text | yes | 16,670 / 16,670 |  |
| `run_id` | uuid | yes | 16,670 / 16,670 |  |
| `step` | ops.pipeline_step | yes | 16,670 / 16,670 |  |
| `code` | text | yes | 16,670 / 16,670 |  |
| `level_or_status` | text | yes | 16,670 / 16,670 |  |
| `message` | text | yes | 8,791 / 16,670 |  |
| `attributes` | jsonb | yes | 16,670 / 16,670 |  |
| `span_id` | uuid | yes | 16,670 / 16,670 |  |
| `duration_ms` | bigint | yes | 7,879 / 16,670 |  |

### `ops.v_run_health` (view, 4 rows)

Admin panel: per run and step, spans, errors, p95 duration, failed work items, metrics. A step at 0 is red (G6).

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `run_id` | uuid | yes | 4 / 4 |  |
| `kind` | ops.run_kind | yes | 4 / 4 |  |
| `status` | ops.run_status | yes | 4 / 4 |  |
| `mode` | ops.run_mode | yes | 4 / 4 |  |
| `step` | ops.pipeline_step | yes | 4 / 4 |  |
| `spans` | bigint | yes | 4 / 4 |  |
| `error_spans` | bigint | yes | 4 / 4 |  |
| `p95_duration_ms` | double precision | yes | 4 / 4 |  |
| `failed_items` | bigint | yes | 4 / 4 |  |
| `metrics` | jsonb | yes | 4 / 4 |  |

### `ops.work_item` (table, 0 rows)

The queue of a run: resume ("rerun the same command"), the overnight run, progress bars. A circuit breaker leaves items todo, never failed.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `run_id` | uuid | no | 0 / 0 |  |
| `ruling_id` | uuid | no | 0 / 0 |  |
| `step` | ops.pipeline_step | no | 0 / 0 |  |
| `target_ref` | text | no | 0 / 0 |  |
| `status` | ops.work_status | no | 0 / 0 |  |
| `attempts` | smallint | no | 0 / 0 |  |
| `last_reason_code` | text | yes | 0 / 0 |  |
| `last_error` | text | yes | 0 / 0 |  |
| `last_span_id` | uuid | yes | 0 / 0 |  |
| `created_at` | timestamp with time zone | no | 0 / 0 |  |
| `updated_at` | timestamp with time zone | no | 0 / 0 |  |

### `summ.claim_citation` (table, 0 rows)

Considerations a claim cites, by FK. Trigger: a citable consideration of the version's source segmentation (G1). Append-only.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `claim_id` | uuid | no | 0 / 0 |  |
| `consideration_id` | uuid | no | 0 / 0 |  |
| `ordinal` | smallint | no | 0 / 0 |  |

### `summ.perspective_anchor` (table, 5 rows)

Perspective anchors (D-068): 0 insured advocate, 3 insured-leaning, 5 neutral (suva_house), 7 insurer-leaning, 10 insurer advocate. An anchor is active only once its rubric is written (owner: summarise). A perspective changes emphasis and the practice paragraph, never facts, holding, outcome or citations.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `perspective` | smallint | no | 5 / 5 |  |
| `label_de` | text | no | 5 / 5 |  |
| `label_fr` | text | no | 5 / 5 |  |
| `rubric_de` | text | yes | 0 / 5 |  |
| `rubric_fr` | text | yes | 0 / 5 |  |
| `status` | ops.registry_status | no | 5 / 5 |  |
| `created_at` | timestamp with time zone | no | 5 / 5 |  |
| `updated_at` | timestamp with time zone | no | 5 / 5 |  |

### `summ.preset` (table, 1 rows)

A kind of summary. Stored in the DB (the DB is its source of truth, exported to data/derived/authored/), listed by the UI, picked by code at run time. Exactly one active mandatory preset: suva_house.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `preset_code` | text | no | 1 / 1 |  |
| `name_de` | text | no | 1 / 1 |  |
| `name_fr` | text | no | 1 / 1 |  |
| `description` | text | yes | 1 / 1 |  |
| `perspective` | smallint | no | 1 / 1 |  |
| `style` | ops.summary_style | no | 1 / 1 |  |
| `is_mandatory` | boolean | no | 1 / 1 |  |
| `selectable` | boolean | no | 1 / 1 |  |
| `retired_at` | timestamp with time zone | yes | 0 / 1 |  |
| `created_by_actor` | text | yes | 1 / 1 |  |
| `created_at` | timestamp with time zone | no | 1 / 1 |  |
| `updated_at` | timestamp with time zone | no | 1 / 1 |  |

### `summ.preset_version` (table, 0 rows)

Editorial configuration of a preset (length, sections, few-shot policy, perspective rubric...), jsonb checked against config_schema_id. Insert-only except status. Id = uuid5('preset_version\|<preset_code>\|<major>\|<minor>\|<patch>').

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `preset_version_id` | uuid | no | 0 / 0 |  |
| `preset_code` | text | no | 0 / 0 |  |
| `v_major` | smallint | no | 0 / 0 |  |
| `v_minor` | smallint | no | 0 / 0 |  |
| `v_patch` | smallint | no | 0 / 0 |  |
| `version_label` | text | yes | 0 / 0 |  |
| `config_schema_id` | uuid | no | 0 / 0 |  |
| `config` | jsonb | no | 0 / 0 |  |
| `config_sha256` | character(64) | no | 0 / 0 |  |
| `status` | ops.registry_status | no | 0 / 0 |  |
| `bump_kind` | ops.bump_kind | no | 0 / 0 |  |
| `previous_version_id` | uuid | yes | 0 / 0 |  |
| `changelog` | text | no | 0 / 0 |  |
| `created_by_actor` | text | yes | 0 / 0 |  |
| `created_at` | timestamp with time zone | no | 0 / 0 |  |
| `updated_at` | timestamp with time zone | no | 0 / 0 |  |

### `summ.preset_version_prompt` (table, 0 rows)

The prompt versions a preset version uses, per language and role. Append-only.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `preset_version_id` | uuid | no | 0 / 0 |  |
| `language` | ops.lang_code | no | 0 / 0 |  |
| `prompt_role` | text | no | 0 / 0 |  |
| `prompt_version_id` | uuid | no | 0 / 0 |  |
| `created_at` | timestamp with time zone | no | 0 / 0 |  |

### `summ.summary` (table, 0 rows)

Identity of one (ruling, preset) summary; its content lives in versions. Id = uuid5('summary\|<ruling_id>\|<preset_code>'). Append-only.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `summary_id` | uuid | no | 0 / 0 |  |
| `ruling_id` | uuid | no | 0 / 0 |  |
| `preset_code` | text | no | 0 / 0 |  |
| `created_at` | timestamp with time zone | no | 0 / 0 |  |

### `summ.summary_claim` (table, 0 rows)

One statement of a text. section includes application and practice (D-069): only practice may differ between perspectives. model_text = the model's text (NULL for an expert-written claim). Append-only.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `claim_id` | uuid | no | 0 / 0 |  |
| `summary_text_id` | uuid | no | 0 / 0 |  |
| `ordinal` | smallint | no | 0 / 0 |  |
| `paragraph_no` | smallint | no | 0 / 0 |  |
| `section` | ops.claim_section | no | 0 / 0 |  |
| `model_text` | text | yes | 0 / 0 |  |
| `rendered_text` | text | no | 0 / 0 |  |
| `status` | ops.claim_status | no | 0 / 0 |  |
| `edited_from_claim_id` | uuid | yes | 0 / 0 |  |
| `created_at` | timestamp with time zone | no | 0 / 0 |  |

### `summ.summary_text` (table, 0 rows)

One language of a version. title_line and body are rendered by code (references from consideration ids, D-037; never an author line, D-051). A pipeline text has its own LLM call written from the source, never a translation of the other language (D-014). Append-only.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `summary_text_id` | uuid | no | 0 / 0 |  |
| `summary_version_id` | uuid | no | 0 / 0 |  |
| `language` | ops.lang_code | no | 0 / 0 |  |
| `title_line` | text | no | 0 / 0 |  |
| `body` | text | no | 0 / 0 |  |
| `word_count` | integer | no | 0 / 0 |  |
| `paragraph_count` | smallint | no | 0 / 0 |  |
| `llm_call_id` | uuid | yes | 0 / 0 |  |
| `repair_llm_call_id` | uuid | yes | 0 / 0 |  |
| `created_at` | timestamp with time zone | no | 0 / 0 |  |

### `summ.summary_version` (table, 0 rows)

An immutable version of a summary: always one German and one French text (deferred check at commit, D-067). version_no is assigned by trigger. Only quality_status (verifier) and is_current change, audited. Expert validation is a review (gold.expert_review), not a column.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `summary_version_id` | uuid | no | 0 / 0 |  |
| `summary_id` | uuid | no | 0 / 0 |  |
| `version_no` | integer | no | 0 / 0 |  |
| `origin` | ops.summary_version_origin | no | 0 / 0 |  |
| `parent_version_id` | uuid | yes | 0 / 0 |  |
| `preset_version_id` | uuid | no | 0 / 0 |  |
| `component_version_id` | uuid | no | 0 / 0 |  |
| `source_segmentation_id` | uuid | no | 0 / 0 |  |
| `creator_kind` | ops.creator_kind | no | 0 / 0 |  |
| `creator_run_id` | uuid | yes | 0 / 0 |  |
| `creator_actor` | text | yes | 0 / 0 |  |
| `quality_status` | ops.summary_quality | no | 0 / 0 |  |
| `is_current` | boolean | no | 0 / 0 |  |
| `mode` | ops.run_mode | yes | 0 / 0 |  |
| `span_id` | uuid | yes | 0 / 0 |  |
| `created_at` | timestamp with time zone | no | 0 / 0 |  |
| `updated_at` | timestamp with time zone | no | 0 / 0 |  |

### `summ.v_mandatory_summary_gaps` (view, 0 rows)

Mandatory-summary gaps of the current release of the default pipeline: must be empty (D-067).

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `ruling_id` | uuid | yes | 0 / 0 |  |
| `docket` | text | yes | 0 / 0 |  |
| `decision_date` | date | yes | 0 / 0 |  |

### `summ.v_summary_current` (view, 0 rows)

Current version per (ruling, preset): both texts, verifier status, the latest expert review.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `summary_id` | uuid | yes | 0 / 0 |  |
| `ruling_id` | uuid | yes | 0 / 0 |  |
| `preset_code` | text | yes | 0 / 0 |  |
| `perspective` | smallint | yes | 0 / 0 |  |
| `is_mandatory` | boolean | yes | 0 / 0 |  |
| `summary_version_id` | uuid | yes | 0 / 0 |  |
| `version_no` | integer | yes | 0 / 0 |  |
| `origin` | ops.summary_version_origin | yes | 0 / 0 |  |
| `quality_status` | ops.summary_quality | yes | 0 / 0 |  |
| `creator_kind` | ops.creator_kind | yes | 0 / 0 |  |
| `mode` | ops.run_mode | yes | 0 / 0 |  |
| `created_at` | timestamp with time zone | yes | 0 / 0 |  |
| `title_de` | text | yes | 0 / 0 |  |
| `body_de` | text | yes | 0 / 0 |  |
| `words_de` | integer | yes | 0 / 0 |  |
| `title_fr` | text | yes | 0 / 0 |  |
| `body_fr` | text | yes | 0 / 0 |  |
| `words_fr` | integer | yes | 0 / 0 |  |
| `expert_verdict` | ops.review_verdict | yes | 0 / 0 |  |
| `reviewed_by` | text | yes | 0 / 0 |  |
| `reviewed_at` | timestamp with time zone | yes | 0 / 0 |  |

### `summ.verification_check` (table, 0 rows)

One verifier check (V1 to V6, the perspective invariant) on a claim or a text, with the exact rule version. Append-only.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `check_id` | uuid | no | 0 / 0 |  |
| `target_kind` | text | no | 0 / 0 |  |
| `claim_id` | uuid | yes | 0 / 0 |  |
| `summary_text_id` | uuid | yes | 0 / 0 |  |
| `rule_id` | uuid | no | 0 / 0 |  |
| `status` | ops.check_status | no | 0 / 0 |  |
| `detail` | jsonb | no | 0 / 0 |  |
| `run_id` | uuid | no | 0 / 0 |  |
| `span_id` | uuid | yes | 0 / 0 |  |
| `created_at` | timestamp with time zone | no | 0 / 0 |  |

### `triage.assessment` (table, 6,967 rows)

One step's verdict on one ruling in one run. Append-only (trigger + grants). The step version must be the one the run's profile pins (trigger). input_fingerprint = SHA-256 over every input: a rerun skips identical inputs. docs/DB_DDL_PLANNING.md §10.1.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `assessment_id` | uuid | no | 6,967 / 6,967 |  |
| `run_id` | uuid | no | 6,967 / 6,967 |  |
| `ruling_id` | uuid | no | 6,967 / 6,967 |  |
| `step` | ops.pipeline_step | no | 6,967 / 6,967 |  |
| `repetition_idx` | smallint | no | 6,967 / 6,967 |  |
| `component_version_id` | uuid | no | 6,967 / 6,967 |  |
| `span_id` | uuid | no | 6,967 / 6,967 |  |
| `upstream_assessment_id` | uuid | yes | 912 / 6,967 |  |
| `input_text_id` | uuid | yes | 6,967 / 6,967 |  |
| `input_segmentation_id` | uuid | yes | 0 / 6,967 |  |
| `input_fingerprint` | character(64) | no | 6,967 / 6,967 |  |
| `in_suva_scope` | ops.in_suva_scope | no | 6,967 / 6,967 |  |
| `outcome` | ops.assessment_outcome | no | 6,967 / 6,967 |  |
| `score_raw` | double precision | yes | 6,032 / 6,967 |  |
| `score_0_100` | numeric(5,2) | yes | 6,032 / 6,967 | Layer 2: 100 x P(Ja)/(P(Ja)+P(Nein)) (D-063). Layer 1: the filter's score for a drop (score_source = net). Ranking: the final score. |
| `score_source` | ops.score_source | yes | 6,032 / 6,967 |  |
| `reason_code` | text | yes | 6,055 / 6,967 |  |
| `explanation_de` | text | yes | 6,967 / 6,967 |  |
| `mode` | ops.run_mode | no | 6,967 / 6,967 |  |
| `started_at` | timestamp with time zone | no | 6,967 / 6,967 |  |
| `finished_at` | timestamp with time zone | yes | 6,967 / 6,967 |  |
| `created_at` | timestamp with time zone | no | 6,967 / 6,967 |  |

### `triage.assessment_evidence` (table, 0 rows)

Considerations an assessment cites, by FK. Trigger: from the assessment's input segmentation only (G1). Append-only.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `assessment_id` | uuid | no | 0 / 0 |  |
| `consideration_id` | uuid | no | 0 / 0 |  |
| `role` | text | no | 0 / 0 |  |

### `triage.assessment_reason` (table, 54,495 rows)

The rule-evaluation ledger (F-01, F-02): one row per enabled rule of the assessment's step version (check rules excepted), whatever it did: fired, not_fired, not_applicable (detail.why) or blocked (detail.blocked_by). ordinal = the rule's ordinal in the version. Certified by triggers: rule, reason code, effect (= rule kind), ordinal and evidence per row (t30_check); completeness, blockers that fired and the layer-1 decision (scope and reason = the decisive fired rule) per assessment at commit (t50_ledger). Written in the transaction of its assessment and sealed at its commit: no row is added to a committed assessment, and the version's rule set is sealed once used. Append-only.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `assessment_id` | uuid | no | 54,495 / 54,495 |  |
| `ordinal` | smallint | no | 54,495 / 54,495 | The rule's ordinal in its step version (ops.component_version_rule.ordinal), not the order in which rules fired. |
| `rule_id` | uuid | no | 54,495 / 54,495 |  |
| `reason_code` | text | no | 54,495 / 54,495 |  |
| `effect` | ops.rule_kind | no | 54,495 / 54,495 |  |
| `outcome` | ops.rule_outcome | no | 54,495 / 54,495 | fired = condition true, effect applies; not_fired = evaluated, false; not_applicable = a precondition failed (detail.why, for layer 1 one of court_not_listed, letter_not_listed, rubric_missing, text_absent, gegenstand_absent; text_absent only when the assessment has no input text); blocked = a keep whose condition is true but neutralised (detail.blocked_by = another enabled flag rule of the same version, which fired in the same ledger; layer 1 also detail.closed_rubric_match). |
| `evidence_field` | text | yes | 38,073 / 54,495 | The field the condition examined: docket, rubric:<source>, gegenstand or full_text; set for every outcome but not_applicable (where it may be NULL). Required (CHECK) for a fired or blocked keep or drop. full_text on an assessment with a text: a fired or blocked row has the offsets of its match; on one without a text: only not_applicable, or fired with neither offsets nor match (a rule that fires on the missing text itself). |
| `evidence_consideration_id` | uuid | yes | 0 / 54,495 |  |
| `examined_value` | text | yes | 19,903 / 54,495 | The short value the condition read (docket head, rubric, title head), at most 300 characters; NULL for full-text rules (the text is referenced by assessment.input_text_id, never copied). |
| `char_start` | integer | yes | 323 / 54,495 | Fired or blocked full-text match: start offset (0-based, characters) in the assessment's input text, on full_text evidence only (CHECK), at least one character long; matched_text = left(substr(content, char_start + 1, char_end - char_start), 300) (trigger). |
| `char_end` | integer | yes | 323 / 54,495 |  |
| `matched_text` | text | yes | 8,058 / 54,495 |  |
| `detail` | jsonb | no | 54,495 / 54,495 | Small object (<= 2000 bytes): why, blocked_by, closed_rubric_match, pattern (config key), text_chars, rubric_source. No ruling text beyond the 300-character match. |

### `triage.justification` (table, 0 rows)

Step 4 detail: the JSON protocol output (key statement, cited considerations) and the party check (no act attributed to Suva unless Suva is a party). Append-only.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `assessment_id` | uuid | no | 0 / 0 |  |
| `llm_call_id` | uuid | no | 0 / 0 |  |
| `repair_llm_call_id` | uuid | yes | 0 / 0 |  |
| `json_valid` | boolean | no | 0 / 0 |  |
| `key_statement` | text | yes | 0 / 0 |  |
| `offered_consideration_count` | integer | no | 0 / 0 |  |
| `party_check_status` | ops.party_check_status | no | 0 / 0 |  |
| `party_check_rule_id` | uuid | yes | 0 / 0 |  |
| `party_check_detail` | jsonb | no | 0 / 0 |  |
| `created_at` | timestamp with time zone | no | 0 / 0 |  |

### `triage.llm_judgement` (table, 912 rows)

Layer-2 detail: the Ja/Nein log-probabilities, p_yes, the raw top_logprobs, the truncation applied. Append-only.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `assessment_id` | uuid | no | 912 / 912 |  |
| `llm_call_id` | uuid | no | 912 / 912 |  |
| `prompt_version_id` | uuid | no | 912 / 912 |  |
| `requested_model` | text | no | 912 / 912 |  |
| `served_model` | text | yes | 912 / 912 |  |
| `question_language` | ops.lang_code | no | 912 / 912 |  |
| `logprob_yes` | double precision | yes | 912 / 912 |  |
| `logprob_no` | double precision | yes | 912 / 912 |  |
| `p_yes` | double precision | yes | 912 / 912 |  |
| `top_logprobs` | jsonb | no | 912 / 912 |  |
| `yes_no_in_top` | boolean | no | 912 / 912 |  |
| `text_chars_total` | integer | no | 912 / 912 |  |
| `text_chars_sent` | integer | no | 912 / 912 |  |
| `truncation` | text | no | 912 / 912 |  |
| `input_tokens` | integer | yes | 912 / 912 |  |
| `created_at` | timestamp with time zone | no | 912 / 912 |  |

### `triage.ranking` (table, 0 rows)

A ranking of one population in one run, at one threshold. A rank belongs to (run, population), never to a ruling (D-046, D-050). Append-only.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `ranking_id` | uuid | no | 0 / 0 |  |
| `run_id` | uuid | no | 0 / 0 |  |
| `population_id` | uuid | no | 0 / 0 |  |
| `threshold_id` | uuid | no | 0 / 0 |  |
| `tie_break` | text | no | 0 / 0 |  |
| `created_at` | timestamp with time zone | no | 0 / 0 |  |

### `triage.ranking_entry` (table, 0 rows)

Rank of one ruling in one ranking. assessment_id = the ranking-step assessment (the label); score_assessment_id = the assessment that gave the score (layer 2 if judged, layer 1 if dropped by the filter). final_score is NULL only for a failed judgement (potentially). Append-only.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `ranking_id` | uuid | no | 0 / 0 |  |
| `ruling_id` | uuid | no | 0 / 0 |  |
| `assessment_id` | uuid | no | 0 / 0 |  |
| `score_assessment_id` | uuid | no | 0 / 0 |  |
| `final_score_0_100` | numeric(5,2) | yes | 0 / 0 |  |
| `rank` | integer | no | 0 / 0 |  |
| `above_threshold` | boolean | no | 0 / 0 |  |
| `in_top10` | boolean | yes | 0 / 0 |  |
| `in_top30` | boolean | yes | 0 / 0 |  |

### `triage.threshold` (table, 0 rows)

A frozen F2 threshold and where it comes from (population chosen on and reported on, metrics with CI, policy D-021 point 8). Valid only for scores of the same scorer step, major and minor (D-064; trigger on ranking entries). Append-only.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `threshold_id` | uuid | no | 0 / 0 |  |
| `ranking_component_version_id` | uuid | no | 0 / 0 |  |
| `scorer_component_version_id` | uuid | no | 0 / 0 |  |
| `layer1_component_version_id` | uuid | yes | 0 / 0 |  |
| `metric` | text | no | 0 / 0 |  |
| `value_0_100` | numeric(5,2) | no | 0 / 0 |  |
| `chosen_on_population_id` | uuid | no | 0 / 0 |  |
| `reported_on_population_id` | uuid | yes | 0 / 0 |  |
| `metrics` | jsonb | no | 0 / 0 |  |
| `policy` | text | no | 0 / 0 |  |
| `frozen_at` | timestamp with time zone | no | 0 / 0 |  |
| `created_by_run_id` | uuid | no | 0 / 0 |  |
| `created_at` | timestamp with time zone | no | 0 / 0 |  |

### `triage.v_current_release` (view, 0 rows)

The current release of the default pipeline (at most one row).

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `release_id` | uuid | yes | 0 / 0 |  |
| `profile_code` | text | yes | 0 / 0 |  |
| `profile_version_id` | uuid | yes | 0 / 0 |  |
| `ranking_id` | uuid | yes | 0 / 0 |  |
| `warnings` | jsonb | yes | 0 / 0 |  |
| `ranking_run_id` | uuid | yes | 0 / 0 |  |
| `population_id` | uuid | yes | 0 / 0 |  |
| `threshold_id` | uuid | yes | 0 / 0 |  |

### `triage.v_export_ranked` (view, 0 rows)

The delivered ranked list of the current release (D-046): score, rank, threshold and top-30 marks, both dates and every population of each ruling (D-050). Must equal the hashed results/ file.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `release_id` | uuid | yes | 0 / 0 |  |
| `population_code` | text | yes | 0 / 0 |  |
| `docket` | text | yes | 0 / 0 |  |
| `decision_date` | date | yes | 0 / 0 |  |
| `publication_date` | date | yes | 0 / 0 |  |
| `publication_date_approx` | date | yes | 0 / 0 |  |
| `publication_quality` | text | yes | 0 / 0 |  |
| `quarter_by_decision` | text | yes | 0 / 0 |  |
| `quarter_by_publication` | text | yes | 0 / 0 |  |
| `populations` | _text | yes | 0 / 0 |  |
| `final_score_0_100` | numeric(5,2) | yes | 0 / 0 |  |
| `rank` | integer | yes | 0 / 0 |  |
| `above_threshold` | boolean | yes | 0 / 0 |  |
| `in_top10` | boolean | yes | 0 / 0 |  |
| `in_top30` | boolean | yes | 0 / 0 |  |
| `in_suva_scope` | ops.in_suva_scope | yes | 0 / 0 |  |
| `score_source` | ops.score_source | yes | 0 / 0 |  |
| `reason_code` | text | yes | 0 / 0 |  |
| `explanation_de` | text | yes | 0 / 0 |  |

### `triage.v_layer1_ledger` (view, 54,495 rows)

Layer 1 rule by rule (F-01, F-02): one row per assessment and rule of its version, with the outcome (fired, not_fired, not_applicable, blocked), the evidence, the German and French labels, and is_decisive (the fired rule whose reason code is the decision's). Order by assessment_id, ordinal.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `assessment_id` | uuid | yes | 54,495 / 54,495 |  |
| `run_id` | uuid | yes | 54,495 / 54,495 |  |
| `ruling_id` | uuid | yes | 54,495 / 54,495 |  |
| `docket` | text | yes | 54,495 / 54,495 |  |
| `decision_date` | date | yes | 54,495 / 54,495 |  |
| `profile_code` | text | yes | 54,495 / 54,495 |  |
| `profile_version` | text | yes | 54,495 / 54,495 |  |
| `component_version` | text | yes | 54,495 / 54,495 |  |
| `in_suva_scope` | ops.in_suva_scope | yes | 54,495 / 54,495 |  |
| `decision_reason_code` | text | yes | 54,495 / 54,495 |  |
| `ordinal` | smallint | yes | 54,495 / 54,495 |  |
| `rule_code` | text | yes | 54,495 / 54,495 |  |
| `rule_version` | text | yes | 54,495 / 54,495 |  |
| `effect` | ops.rule_kind | yes | 54,495 / 54,495 |  |
| `outcome` | ops.rule_outcome | yes | 54,495 / 54,495 |  |
| `is_decisive` | boolean | yes | 54,495 / 54,495 |  |
| `evidence_field` | text | yes | 38,073 / 54,495 |  |
| `examined_value` | text | yes | 19,903 / 54,495 |  |
| `char_start` | integer | yes | 323 / 54,495 |  |
| `char_end` | integer | yes | 323 / 54,495 |  |
| `matched_text` | text | yes | 8,058 / 54,495 |  |
| `detail` | jsonb | yes | 54,495 / 54,495 |  |
| `label_de` | text | yes | 54,495 / 54,495 |  |
| `label_fr` | text | yes | 54,495 / 54,495 |  |
| `input_text_id` | uuid | yes | 54,495 / 54,495 |  |
| `text_sha256` | character(64) | yes | 54,495 / 54,495 |  |

### `triage.v_scope_current` (view, 6,055 rows)

The pipeline label plus the latest expert scope review beside it (D-066): expert_implied_label = the pipeline label, flipped when the verdict is incorrect. The delivered list and the metrics never read expert_implied_label.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `ruling_id` | uuid | yes | 6,055 / 6,055 |  |
| `pipeline_label` | ops.in_suva_scope | yes | 6,055 / 6,055 |  |
| `step` | ops.pipeline_step | yes | 6,055 / 6,055 |  |
| `assessment_id` | uuid | yes | 6,055 / 6,055 |  |
| `run_id` | uuid | yes | 6,055 / 6,055 |  |
| `score_0_100` | numeric(5,2) | yes | 6,032 / 6,055 |  |
| `score_source` | ops.score_source | yes | 6,032 / 6,055 |  |
| `reason_code` | text | yes | 5,143 / 6,055 |  |
| `reason_label_de` | text | yes | 5,143 / 6,055 |  |
| `reason_label_fr` | text | yes | 5,143 / 6,055 |  |
| `explanation_de` | text | yes | 6,055 / 6,055 |  |
| `outcome` | ops.assessment_outcome | yes | 6,055 / 6,055 |  |
| `mode` | ops.run_mode | yes | 6,055 / 6,055 |  |
| `label_origin` | text | yes | 6,055 / 6,055 |  |
| `created_at` | timestamp with time zone | yes | 6,055 / 6,055 |  |
| `expert_verdict` | ops.review_verdict | yes | 0 / 6,055 |  |
| `reviewed_label` | ops.in_suva_scope | yes | 0 / 6,055 |  |
| `reviewed_assessment_id` | uuid | yes | 0 / 6,055 |  |
| `review_is_stale` | boolean | yes | 6,055 / 6,055 |  |
| `expert_implied_label` | ops.in_suva_scope | yes | 0 / 6,055 |  |
| `reviewed_by` | text | yes | 0 / 6,055 |  |
| `reviewed_at` | timestamp with time zone | yes | 0 / 6,055 |  |

### `triage.v_scope_pipeline` (view, 6,055 rows)

THE label (D-063): the default pipeline's furthest-step assessment per ruling, from its current release, else from its usable runs (succeeded or partial, not eval) and only along the lineage of its current layer-1 decision (DDL-2). not_assessed = no row.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `ruling_id` | uuid | yes | 6,055 / 6,055 |  |
| `pipeline_label` | ops.in_suva_scope | yes | 6,055 / 6,055 |  |
| `step` | ops.pipeline_step | yes | 6,055 / 6,055 |  |
| `assessment_id` | uuid | yes | 6,055 / 6,055 |  |
| `run_id` | uuid | yes | 6,055 / 6,055 |  |
| `score_0_100` | numeric(5,2) | yes | 6,032 / 6,055 |  |
| `score_source` | ops.score_source | yes | 6,032 / 6,055 |  |
| `reason_code` | text | yes | 5,143 / 6,055 |  |
| `reason_label_de` | text | yes | 5,143 / 6,055 |  |
| `reason_label_fr` | text | yes | 5,143 / 6,055 |  |
| `explanation_de` | text | yes | 6,055 / 6,055 |  |
| `outcome` | ops.assessment_outcome | yes | 6,055 / 6,055 |  |
| `mode` | ops.run_mode | yes | 6,055 / 6,055 |  |
| `label_origin` | text | yes | 6,055 / 6,055 |  |
| `created_at` | timestamp with time zone | yes | 6,055 / 6,055 |  |

### `triage.v_scope_trace` (view, 6,967 rows)

The "show me why" panel: one row per step of the label's lineage, with run, profile and component versions, models, reasons (reason_count = rules that fired; evaluated_rule_count = ledger rows, every rule of the version), LLM call, input text, source snapshot, span and event counts (D-064, D-065). Rule by rule: triage.v_layer1_ledger.

| Column | Type | Null | Filled | Comment |
|---|---|---|---:|---|
| `ruling_id` | uuid | yes | 6,967 / 6,967 |  |
| `hop` | integer | yes | 6,967 / 6,967 |  |
| `step` | ops.pipeline_step | yes | 6,967 / 6,967 |  |
| `assessment_id` | uuid | yes | 6,967 / 6,967 |  |
| `in_suva_scope` | ops.in_suva_scope | yes | 6,967 / 6,967 |  |
| `outcome` | ops.assessment_outcome | yes | 6,967 / 6,967 |  |
| `score_0_100` | numeric(5,2) | yes | 6,032 / 6,967 |  |
| `score_source` | ops.score_source | yes | 6,032 / 6,967 |  |
| `reason_code` | text | yes | 6,055 / 6,967 |  |
| `reason_label_de` | text | yes | 6,055 / 6,967 |  |
| `explanation_de` | text | yes | 6,967 / 6,967 |  |
| `mode` | ops.run_mode | yes | 6,967 / 6,967 |  |
| `run_id` | uuid | yes | 6,967 / 6,967 |  |
| `run_kind` | ops.run_kind | yes | 6,967 / 6,967 |  |
| `git_commit` | character(40) | yes | 6,967 / 6,967 |  |
| `model_override` | boolean | yes | 6,967 / 6,967 |  |
| `profile_code` | text | yes | 6,967 / 6,967 |  |
| `profile_version` | text | yes | 6,967 / 6,967 |  |
| `component_name` | text | yes | 6,967 / 6,967 |  |
| `component_version` | text | yes | 6,967 / 6,967 |  |
| `code_sha256` | character(64) | yes | 6,967 / 6,967 |  |
| `config_sha256` | character(64) | yes | 6,967 / 6,967 |  |
| `declared_models` | jsonb | yes | 912 / 6,967 |  |
| `reason_count` | bigint | yes | 6,967 / 6,967 |  |
| `evaluated_rule_count` | bigint | yes | 6,967 / 6,967 |  |
| `llm_call_id` | uuid | yes | 912 / 6,967 |  |
| `served_model` | text | yes | 912 / 6,967 |  |
| `latency_ms` | integer | yes | 0 / 6,967 |  |
| `input_tokens` | integer | yes | 912 / 6,967 |  |
| `output_tokens` | integer | yes | 912 / 6,967 |  |
| `cache_hit` | boolean | yes | 912 / 6,967 |  |
| `finish_reason` | text | yes | 912 / 6,967 |  |
| `p_yes` | double precision | yes | 912 / 6,967 |  |
| `text_source` | ops.text_source | yes | 6,967 / 6,967 |  |
| `text_sha256` | character(64) | yes | 6,967 / 6,967 |  |
| `source_kind` | ops.source_kind | yes | 6,967 / 6,967 |  |
| `source_revision` | text | yes | 6,967 / 6,967 |  |
| `source_file_sha256` | character(64) | yes | 6,967 / 6,967 |  |
| `span_status` | ops.span_status | yes | 6,967 / 6,967 |  |
| `duration_ms` | bigint | yes | 6,967 / 6,967 |  |
| `event_count` | bigint | yes | 6,967 / 6,967 |  |
| `warning_or_worse_count` | bigint | yes | 6,967 / 6,967 |  |

## Appendix C. Sample records (public rulings outside Suva's data)

Values as stored, text content left out. `4A_554/2025` (French, kept by layer 1, scored by layer 2) and `4A_100/2026` (German, dropped by layer 1).


### `4A_554/2025`

```json
{
 "corpus.v_ruling": {
  "ruling_id": "be3862d0-3f59-5933-9908-d604d450f5dc",
  "docket": "4A_554/2025",
  "decision_date": "2026-06-09",
  "court": "4A",
  "register_letter": "A",
  "filing_year": 2025,
  "language": "fr",
  "gegenstand": "Responsabilité médicale (lien de causalité),",
  "previous_instance": "Tribunal cantonal de l'État de Fribourg, Ie Cour administrative",
  "bger_url": "https://search.bger.ch/ext/eurospider/live/de/php/aza/http/index.php?lang=de&type=show_document&highlight_docid=aza://09-06-2026-4A_554-2025",
  "origin": "base_dataset",
  "quarter_by_decision": "2026Q2",
  "publication_date": "2026-07-27",
  "publication_source": "hf_poller",
  "publication_date_approx": null,
  "publication_quality": "exact",
  "quarter_by_publication": "2026Q3",
  "star": null,
  "sachgebiet": null,
  "primary_text_id": "604658b6-49e7-558c-b863-5c262ea041f6",
  "char_length": 25479,
  "clean_length": null,
  "primary_segmentation_id": null,
  "consideration_count": null
 },
 "populations": [
  "2026Q2_decision",
  "2026Q2_union"
 ],
 "corpus.publication_observation": [
  {
   "observation_id": "e4313d14-cc95-41ac-b2cf-cdb632b8e428",
   "ruling_id": "be3862d0-3f59-5933-9908-d604d450f5dc",
   "source": "hf_poller",
   "quality": "exact",
   "observed_date": "2026-07-27",
   "star": null,
   "sachgebiet": null,
   "snapshot_id": "e92564f3-1d0f-4f32-9f96-d95acdc14a83",
   "created_at": "2026-11-28 09:38:23.409766+00:00"
  }
 ],
 "triage.v_scope_current": {
  "ruling_id": "be3862d0-3f59-5933-9908-d604d450f5dc",
  "pipeline_label": "potentially",
  "step": "layer2_judge",
  "assessment_id": "0d1a096c-853c-5b56-9833-0faa71caad48",
  "run_id": "c3853081-f310-492a-996d-5b7de792c853",
  "score_0_100": "100.00",
  "score_source": "judged",
  "reason_code": null,
  "reason_label_de": null,
  "reason_label_fr": null,
  "explanation_de": "Apertus-Einschätzung (Modell apertus-v1-5-8b, Version V1.0.0): Wahrscheinlichkeit «Ja» > 99,9 %. Über die Relevanz entscheidet erst die Rangierung. Text gekürzt: 14 000 von 25 479 Zeichen gelesen (Anfang und Schluss).",
  "outcome": "ok",
  "mode": "REPLAY",
  "label_origin": "latest_run",
  "created_at": "2026-11-28 09:39:54.042856+00:00",
  "expert_verdict": null,
  "reviewed_label": null,
  "reviewed_assessment_id": null,
  "review_is_stale": false,
  "expert_implied_label": null,
  "reviewed_by": null,
  "reviewed_at": null
 },
 "triage.v_scope_trace": [
  {
   "ruling_id": "be3862d0-3f59-5933-9908-d604d450f5dc",
   "hop": 1,
   "step": "layer1_filter",
   "assessment_id": "0debb8c4-199c-5aa1-84c1-8a7cce72a38f",
   "in_suva_scope": "potentially",
   "outcome": "ok",
   "score_0_100": null,
   "score_source": null,
   "reason_code": "L1_KEEP_ACCIDENT_TERM",
   "reason_label_de": "Text nennt die Suva oder die Unfall- oder Militärversicherung",
   "explanation_de": "Vorauswahl bestanden: Text nennt die Suva oder die Unfall- oder Militärversicherung. (Rechtsgebiet aus dem Gegenstand gelesen: Responsabilité médicale)",
   "mode": "LIVE",
   "run_id": "d6258666-5352-40a2-bc63-004408c10e58",
   "run_kind": "layer1",
   "git_commit": "14caaba355f2062172bc53f6018774d59d160f79",
   "model_override": false,
   "profile_code": "default",
   "profile_version": "V0.3.0",
   "component_name": "layer-1 gate, normalised text, wider accident terms",
   "component_version": "V1.1.0",
   "code_sha256": "1616d1a6f7b4fff6deb32dacfb23bd5df5645024be676093fdbc3bf89bffb3c0",
   "config_sha256": "213a45854f62d2e8afa5ec487035140b414042e6daa9a1b67ee93d27044eedb1",
   "declared_models": null,
   "reason_count": 3,
   "evaluated_rule_count": 9,
   "llm_call_id": null,
   "served_model": null,
   "latency_ms": null,
   "input_tokens": null,
   "output_tokens": null,
   "cache_hit": null,
   "finish_reason": null,
   "p_yes": null,
   "text_source": "hf",
   "text_sha256": "aac9b1e98ee5e2f20e3067eb1294656d4da940cee9a61257f9152e09efd5d0e7",
   "source_kind": "hf_bger",
   "source_revision": "35b17aa9c3fad71011b72f78f6ab79650ec0cf96",
   "source_file_sha256": "d2b2df1dedb05c62d91d834ddb6ba8084c31fae61a427fd4541a72ed35bb3711",
   "span_status": "ok",
   "duration_ms": 0,
   "event_count": 1,
   "warning_or_worse_count": 0
  },
  {
   "ruling_id": "be3862d0-3f59-5933-9908-d604d450f5dc",
   "hop": 0,
   "step": "layer2_judge",
   "assessment_id": "0d1a096c-853c-5b56-9833-0faa71caad48",
   "in_suva_scope": "potentially",
   "outcome": "ok",
   "score_0_100": "100.00",
   "score_source": "judged",
   "reason_code": null,
   "reason_label_de": null,
   "explanation_de": "Apertus-Einschätzung (Modell apertus-v1-5-8b, Version V1.0.0): Wahrscheinlichkeit «Ja» > 99,9 %. Über die Relevanz entscheidet erst die Rangierung. Text gekürzt: 14 000 von 25 479 Zeichen gelesen (Anfang und Schluss).",
   "mode": "REPLAY",
   "run_id": "c3853081-f310-492a-996d-5b7de792c853",
   "run_kind": "layer2",
   "git_commit": "14caaba355f2062172bc53f6018774d59d160f79",
   "model_override": false,
   "profile_code": "default",
   "profile_version": "V0.3.0",
   "component_name": "Apertus 8B zero-shot Ja/Nein, the D-074 chain",
   "component_version": "V1.0.0",
   "code_sha256": "210c49a1ee1be40851594ba58c50e0e963b8ba1ca403b4ff687aed09d5292a01",
   "config_sha256": "4c74c89870add34984f8e75d034170b3b45172d17e06ade6463084af1dee2c75",
   "declared_models": {
    "judge": "apertus-v1-5-8b"
   },
   "reason_count": 0,
   "evaluated_rule_count": 0,
   "llm_call_id": "08607bf8-ca86-5cdc-b0a7-b5c87e6236de",
   "served_model": "apertus-v1-5-8b",
   "latency_ms": null,
   "input_tokens": 4283,
   "output_tokens": 1,
   "cache_hit": true,
   "finish_reason": "length",
   "p_yes": 0.9999982394397653,
   "text_source": "hf",
   "text_sha256": "aac9b1e98ee5e2f20e3067eb1294656d4da940cee9a61257f9152e09efd5d0e7",
   "source_kind": "hf_bger",
   "source_revision": "35b17aa9c3fad71011b72f78f6ab79650ec0cf96",
   "source_file_sha256": "d2b2df1dedb05c62d91d834ddb6ba8084c31fae61a427fd4541a72ed35bb3711",
   "span_status": "ok",
   "duration_ms": 1,
   "event_count": 2,
   "warning_or_worse_count": 0
  }
 ],
 "triage.v_layer1_ledger (selected columns)": [
  {
   "rule_code": "L1_KEEP_RUBRIC",
   "effect": "keep",
   "outcome": "not_fired",
   "is_decisive": false,
   "evidence_field": "rubric:gegenstand_head",
   "examined_value": "Responsabilité médicale",
   "char_start": null,
   "char_end": null,
   "matched_text": null,
   "detail": {
    "pattern": "courts.4.rubrics",
    "rubric_key": "responsabilité médicale"
   },
   "label_de": "Rechtsgebiet in der Liste der Abteilung"
  },
  {
   "rule_code": "L1_KEEP_RUBRIC_MISSING",
   "effect": "keep",
   "outcome": "not_fired",
   "is_decisive": false,
   "evidence_field": "rubric:gegenstand_head",
   "examined_value": "Responsabilité médicale",
   "char_start": null,
   "char_end": null,
   "matched_text": null,
   "detail": {
    "rubric_source": "gegenstand_head"
   },
   "label_de": "Rechtsgebiet fehlt: vorsorglich behalten"
  },
  {
   "rule_code": "L1_KEEP_ACCIDENT_TERM",
   "effect": "keep",
   "outcome": "fired",
   "is_decisive": true,
   "evidence_field": "full_text",
   "examined_value": null,
   "char_start": 23839,
   "char_end": 23858,
   "matched_text": "assurance-accidents",
   "detail": {
    "pattern": "accident_terms"
   },
   "label_de": "Text nennt die Suva oder die Unfall- oder Militärversicherung"
  },
  {
   "rule_code": "L1_KEEP_CONTRACT_TERM",
   "effect": "keep",
   "outcome": "not_fired",
   "is_decisive": false,
   "evidence_field": "full_text",
   "examined_value": null,
   "char_start": null,
   "char_end": null,
   "matched_text": null,
   "detail": {
    "pattern": "contract_terms",
    "text_chars": 25479
   },
   "label_de": "Text nennt das VVG oder eine Taggeldversicherung"
  },
  {
   "rule_code": "L1_FLAG_CLOSED_RUBRIC",
   "effect": "flag",
   "outcome": "not_fired",
   "is_decisive": false,
   "evidence_field": "full_text",
   "examined_value": null,
   "char_start": null,
   "char_end": null,
   "matched_text": null,
   "detail": {
    "pattern": "contract_terms",
    "text_chars": 25479
   },
   "label_de": "VVG-Begriff im Text, aber Rechtsgebiet ausgeschlossen (z. B. Arbeitslosenversicherung)"
  },
  {
   "rule_code": "L1_DROP_WRONG_COURT",
   "effect": "drop",
   "outcome": "not_fired",
   "is_decisive": false,
   "evidence_field": "docket",
   "examined_value": "4A",
   "char_start": null,
   "char_end": null,
   "matched_text": null,
   "detail": {
    "pattern": "courts"
   },
   "label_de": "Abteilung nicht in der Liste der Vorauswahl"
  },
  {
   "rule_code": "L1_DROP_WRONG_LETTER",
   "effect": "drop",
   "outcome": "not_fired",
   "is_decisive": false,
   "evidence_field": "docket",
   "examined_value": "4A",
   "char_start": null,
   "char_end": null,
   "matched_text": null,
   "detail": {
    "pattern": "courts.4.letters"
   },
   "label_de": "Verfahrensart in dieser Abteilung nicht berücksichtigt"
  },
  {
   "rule_code": "L1_DROP_RUBRIC_OUT",
   "effect": "drop",
   "outcome": "fired",
   "is_decisive": false,
   "evidence_field": "rubric:gegenstand_head",
   "examined_value": "Responsabilité médicale",
   "char_start": null,
   "char_end": null,
   "matched_text": "Responsabilité médicale",
   "detail": {
    "pattern": "courts.4.rubrics",
    "rubric_key": "responsabilité médicale"
   },
   "label_de": "Rechtsgebiet nicht in der Liste der Abteilung"
  },
  {
   "rule_code": "L1_SIGNAL_RUBRIC_FROM_TITLE",
   "effect": "signal",
   "outcome": "fired",
   "is_decisive": false,
   "evidence_field": "gegenstand",
   "examined_value": "Responsabilité médicale",
   "char_start": null,
   "char_end": null,
   "matched_text": "Responsabilité médicale",
   "detail": {
    "rubric_source": "gegenstand_head"
   },
   "label_de": "Rechtsgebiet aus dem Gegenstand gelesen"
  }
 ],
 "triage.llm_judgement": {
  "assessment_id": "0d1a096c-853c-5b56-9833-0faa71caad48",
  "llm_call_id": "08607bf8-ca86-5cdc-b0a7-b5c87e6236de",
  "prompt_version_id": "3be66d6a-901a-56c6-a87f-e33775d73dc8",
  "requested_model": "apertus-v1-5-8b",
  "served_model": "apertus-v1-5-8b",
  "question_language": "de",
  "logprob_yes": -1.7812839645292082e-06,
  "logprob_no": -13.24987850515891,
  "p_yes": 0.9999982394397653,
  "top_logprobs": [
   [
    "Ja",
    -1.7881377516459906e-06
   ],
   [
    "Nein",
    -13.250001907348633
   ],
   [
    "Je",
    -17.500001907348633
   ],
   [
    "Yes",
    -18.000001907348633
   ],
   [
    " Ja",
    -19.000001907348633
   ],
   [
    "J",
    -20.500001907348633
   ],
   [
    "Ne",
    -22.250001907348633
   ],
   [
    "Nur",
    -25.250001907348633
   ],
   [
    "We",
    -27.250001907348633
   ],
   [
    "No",
    -28.250001907348633
   ],
   [
    "JA",
    -28.500001907348633
   ],
   [
    "ja",
    -28.500001907348633
   ],
   [
    "G",
    -29.500001907348633
   ],
   [
    "Nicht",
    -30.250001907348633
   ],
   [
    "I",
    -30.500001907348633
   ],
   [
    "Ich",
    -30.625001907348633
   ],
   [
    "Jam",
    -30.875001907348633
   ],
   [
    "Im",
    -31.125001907348633
   ],
   [
    "Oh",
    -31.250001907348633
   ],
   [
    "In",
    -31.375001907348633
   ]
  ],
  "yes_no_in_top": true,
  "text_chars_total": 25479,
  "text_chars_sent": 14000,
  "truncation": "head12000_tail2000",
  "input_tokens": 4283,
  "created_at": "2026-11-28 09:39:54.042856+00:00"
 },
 "ops.llm_call": {
  "llm_call_id": "08607bf8-ca86-5cdc-b0a7-b5c87e6236de",
  "run_id": "c3853081-f310-492a-996d-5b7de792c853",
  "span_id": "f2d3e3da-df5d-5f25-8923-13fd5126aa4a",
  "ruling_id": "be3862d0-3f59-5933-9908-d604d450f5dc",
  "step": "layer2_judge",
  "purpose": "relevance_judgement",
  "language": "de",
  "prompt_version_id": "3be66d6a-901a-56c6-a87f-e33775d73dc8",
  "cache_key": "7ec6c6a29bcc…",
  "cache_hit": true,
  "mode": "REPLAY",
  "endpoint": "/chat/completions",
  "model_role": "judge",
  "requested_model": "apertus-v1-5-8b",
  "served_model": "apertus-v1-5-8b",
  "served_model_header": null,
  "params": {
   "logprobs": true,
   "max_tokens": 1,
   "temperature": 0,
   "top_logprobs": 20
  },
  "repetition_idx": 0,
  "messages_sha256": "2bcbe57232ac5f22dd689eb4c7bd6996ed45dcff623ea1a7f0a524ab57d84cc0",
  "raw_output": "Ja",
  "finish_reason": "length",
  "parsed_ok": true,
  "parse_error": null,
  "http_status": null,
  "error_reason_code": null,
  "attempt": 1,
  "input_tokens": 4283,
  "output_tokens": 1,
  "cached_tokens": 192,
  "latency_ms": null,
  "started_at": "2026-11-28 09:39:53.766000+00:00",
  "created_at": "2026-11-28 09:39:54.042856+00:00"
 },
 "ops.v_ruling_timeline (selected columns)": [
  {
   "kind": "span",
   "step": "layer1_filter",
   "code": "layer1.decide",
   "level_or_status": "ok",
   "message": null,
   "duration_ms": 0
  },
  {
   "kind": "event",
   "step": "layer1_filter",
   "code": "layer1.decision.made",
   "level_or_status": "info",
   "message": "L1_KEEP_ACCIDENT_TERM",
   "duration_ms": null
  },
  {
   "kind": "span",
   "step": "layer2_judge",
   "code": "llm.call",
   "level_or_status": "ok",
   "message": null,
   "duration_ms": 0
  },
  {
   "kind": "span",
   "step": "layer2_judge",
   "code": "layer2.judge",
   "level_or_status": "ok",
   "message": null,
   "duration_ms": 1
  },
  {
   "kind": "event",
   "step": "layer2_judge",
   "code": "llm.cache.hit",
   "level_or_status": "debug",
   "message": "answer from the replay cache",
   "duration_ms": null
  },
  {
   "kind": "event",
   "step": "layer2_judge",
   "code": "layer2.prompt.built",
   "level_or_status": "info",
   "message": "messages built from the primary text",
   "duration_ms": null
  },
  {
   "kind": "event",
   "step": "layer2_judge",
   "code": "layer2.score",
   "level_or_status": "debug",
   "message": "p_yes 0.999998",
   "duration_ms": null
  }
 ]
}
```

### `4A_100/2026`

```json
{
 "corpus.v_ruling": {
  "ruling_id": "0366e52e-3e58-53e6-b614-9724c946ca02",
  "docket": "4A_100/2026",
  "decision_date": "2026-03-02",
  "court": "4A",
  "register_letter": "A",
  "filing_year": 2026,
  "language": "de",
  "gegenstand": "Provisorische Rechtsöffnung,",
  "previous_instance": "Obergerichts des Kantons Zürich, I. Zivilkammer",
  "bger_url": "https://search.bger.ch/ext/eurospider/live/de/php/aza/http/index.php?lang=de&type=show_document&highlight_docid=aza://02-03-2026-4A_100-2026",
  "origin": "base_dataset",
  "quarter_by_decision": "2026Q1",
  "publication_date": null,
  "publication_source": null,
  "publication_date_approx": "2026-03-11",
  "publication_quality": "approx_first_seen",
  "quarter_by_publication": null,
  "star": null,
  "sachgebiet": null,
  "primary_text_id": "1f852a34-626d-5c42-81bd-5e5e1ed7dcd8",
  "char_length": 2709,
  "clean_length": null,
  "primary_segmentation_id": null,
  "consideration_count": null
 },
 "populations": [
  "2026Q1_decision"
 ],
 "corpus.publication_observation": [
  {
   "observation_id": "8804c018-f107-43a5-9ea0-56625d8c68f9",
   "ruling_id": "0366e52e-3e58-53e6-b614-9724c946ca02",
   "source": "hf_first_seen",
   "quality": "approx_first_seen",
   "observed_date": "2026-03-11",
   "star": null,
   "sachgebiet": null,
   "snapshot_id": "e92564f3-1d0f-4f32-9f96-d95acdc14a83",
   "created_at": "2026-11-28 09:38:23.409766+00:00"
  }
 ],
 "triage.v_scope_current": {
  "ruling_id": "0366e52e-3e58-53e6-b614-9724c946ca02",
  "pipeline_label": "out_of_scope",
  "step": "layer1_filter",
  "assessment_id": "7a31a7c7-0103-598e-8c57-4e2fc8969942",
  "run_id": "d6258666-5352-40a2-bc63-004408c10e58",
  "score_0_100": "0.00",
  "score_source": "net",
  "reason_code": "L1_DROP_RUBRIC_OUT",
  "reason_label_de": "Rechtsgebiet nicht in der Liste der Abteilung",
  "reason_label_fr": "Domaine juridique hors de la liste de cette cour",
  "explanation_de": "Von der Vorauswahl ausgeschlossen: Rechtsgebiet nicht in der Liste der Abteilung. Im Urteilstext geprüft, ohne Treffer: Suchbegriffe zu Suva, Unfall- und Militärversicherung; Suchbegriffe zu VVG und Taggeldversicherung (nur die Begriffe der Filterversion; andere Formulierungen erkennt die Prüfung nicht).",
  "outcome": "ok",
  "mode": "LIVE",
  "label_origin": "latest_run",
  "created_at": "2026-11-28 09:39:14.924810+00:00",
  "expert_verdict": null,
  "reviewed_label": null,
  "reviewed_assessment_id": null,
  "review_is_stale": false,
  "expert_implied_label": null,
  "reviewed_by": null,
  "reviewed_at": null
 },
 "triage.v_scope_trace": [
  {
   "ruling_id": "0366e52e-3e58-53e6-b614-9724c946ca02",
   "hop": 0,
   "step": "layer1_filter",
   "assessment_id": "7a31a7c7-0103-598e-8c57-4e2fc8969942",
   "in_suva_scope": "out_of_scope",
   "outcome": "ok",
   "score_0_100": "0.00",
   "score_source": "net",
   "reason_code": "L1_DROP_RUBRIC_OUT",
   "reason_label_de": "Rechtsgebiet nicht in der Liste der Abteilung",
   "explanation_de": "Von der Vorauswahl ausgeschlossen: Rechtsgebiet nicht in der Liste der Abteilung. Im Urteilstext geprüft, ohne Treffer: Suchbegriffe zu Suva, Unfall- und Militärversicherung; Suchbegriffe zu VVG und Taggeldversicherung (nur die Begriffe der Filterversion; andere Formulierungen erkennt die Prüfung nicht).",
   "mode": "LIVE",
   "run_id": "d6258666-5352-40a2-bc63-004408c10e58",
   "run_kind": "layer1",
   "git_commit": "14caaba355f2062172bc53f6018774d59d160f79",
   "model_override": false,
   "profile_code": "default",
   "profile_version": "V0.3.0",
   "component_name": "layer-1 gate, normalised text, wider accident terms",
   "component_version": "V1.1.0",
   "code_sha256": "1616d1a6f7b4fff6deb32dacfb23bd5df5645024be676093fdbc3bf89bffb3c0",
   "config_sha256": "213a45854f62d2e8afa5ec487035140b414042e6daa9a1b67ee93d27044eedb1",
   "declared_models": null,
   "reason_count": 1,
   "evaluated_rule_count": 9,
   "llm_call_id": null,
   "served_model": null,
   "latency_ms": null,
   "input_tokens": null,
   "output_tokens": null,
   "cache_hit": null,
   "finish_reason": null,
   "p_yes": null,
   "text_source": "hf",
   "text_sha256": "7e884b5665099dfe878859300bb938897c6d38e1864d827bd61837e9fff8ad9f",
   "source_kind": "hf_bger",
   "source_revision": "35b17aa9c3fad71011b72f78f6ab79650ec0cf96",
   "source_file_sha256": "d2b2df1dedb05c62d91d834ddb6ba8084c31fae61a427fd4541a72ed35bb3711",
   "span_status": "ok",
   "duration_ms": 0,
   "event_count": 1,
   "warning_or_worse_count": 0
  }
 ],
 "triage.v_layer1_ledger (selected columns)": [
  {
   "rule_code": "L1_KEEP_RUBRIC",
   "effect": "keep",
   "outcome": "not_fired",
   "is_decisive": false,
   "evidence_field": "rubric:hf_legal_area",
   "examined_value": "Schuldbetreibungs- und Konkursrecht",
   "char_start": null,
   "char_end": null,
   "matched_text": null,
   "detail": {
    "pattern": "courts.4.rubrics",
    "rubric_key": "schuldbetreibungs- und konkursrecht"
   },
   "label_de": "Rechtsgebiet in der Liste der Abteilung"
  },
  {
   "rule_code": "L1_KEEP_RUBRIC_MISSING",
   "effect": "keep",
   "outcome": "not_fired",
   "is_decisive": false,
   "evidence_field": "rubric:hf_legal_area",
   "examined_value": "Schuldbetreibungs- und Konkursrecht",
   "char_start": null,
   "char_end": null,
   "matched_text": null,
   "detail": {
    "rubric_source": "hf_legal_area"
   },
   "label_de": "Rechtsgebiet fehlt: vorsorglich behalten"
  },
  {
   "rule_code": "L1_KEEP_ACCIDENT_TERM",
   "effect": "keep",
   "outcome": "not_fired",
   "is_decisive": false,
   "evidence_field": "full_text",
   "examined_value": null,
   "char_start": null,
   "char_end": null,
   "matched_text": null,
   "detail": {
    "pattern": "accident_terms",
    "text_chars": 2709
   },
   "label_de": "Text nennt die Suva oder die Unfall- oder Militärversicherung"
  },
  {
   "rule_code": "L1_KEEP_CONTRACT_TERM",
   "effect": "keep",
   "outcome": "not_fired",
   "is_decisive": false,
   "evidence_field": "full_text",
   "examined_value": null,
   "char_start": null,
   "char_end": null,
   "matched_text": null,
   "detail": {
    "pattern": "contract_terms",
    "text_chars": 2709
   },
   "label_de": "Text nennt das VVG oder eine Taggeldversicherung"
  },
  {
   "rule_code": "L1_FLAG_CLOSED_RUBRIC",
   "effect": "flag",
   "outcome": "not_fired",
   "is_decisive": false,
   "evidence_field": "full_text",
   "examined_value": null,
   "char_start": null,
   "char_end": null,
   "matched_text": null,
   "detail": {
    "pattern": "contract_terms",
    "text_chars": 2709
   },
   "label_de": "VVG-Begriff im Text, aber Rechtsgebiet ausgeschlossen (z. B. Arbeitslosenversicherung)"
  },
  {
   "rule_code": "L1_DROP_WRONG_COURT",
   "effect": "drop",
   "outcome": "not_fired",
   "is_decisive": false,
   "evidence_field": "docket",
   "examined_value": "4A",
   "char_start": null,
   "char_end": null,
   "matched_text": null,
   "detail": {
    "pattern": "courts"
   },
   "label_de": "Abteilung nicht in der Liste der Vorauswahl"
  },
  {
   "rule_code": "L1_DROP_WRONG_LETTER",
   "effect": "drop",
   "outcome": "not_fired",
   "is_decisive": false,
   "evidence_field": "docket",
   "examined_value": "4A",
   "char_start": null,
   "char_end": null,
   "matched_text": null,
   "detail": {
    "pattern": "courts.4.letters"
   },
   "label_de": "Verfahrensart in dieser Abteilung nicht berücksichtigt"
  },
  {
   "rule_code": "L1_DROP_RUBRIC_OUT",
   "effect": "drop",
   "outcome": "fired",
   "is_decisive": true,
   "evidence_field": "rubric:hf_legal_area",
   "examined_value": "Schuldbetreibungs- und Konkursrecht",
   "char_start": null,
   "char_end": null,
   "matched_text": "Schuldbetreibungs- und Konkursrecht",
   "detail": {
    "pattern": "courts.4.rubrics",
    "rubric_key": "schuldbetreibungs- und konkursrecht"
   },
   "label_de": "Rechtsgebiet nicht in der Liste der Abteilung"
  },
  {
   "rule_code": "L1_SIGNAL_RUBRIC_FROM_TITLE",
   "effect": "signal",
   "outcome": "not_fired",
   "is_decisive": false,
   "evidence_field": "rubric:hf_legal_area",
   "examined_value": "Schuldbetreibungs- und Konkursrecht",
   "char_start": null,
   "char_end": null,
   "matched_text": null,
   "detail": {
    "rubric_source": "hf_legal_area"
   },
   "label_de": "Rechtsgebiet aus dem Gegenstand gelesen"
  }
 ],
 "triage.llm_judgement": null,
 "ops.llm_call": null,
 "ops.v_ruling_timeline (selected columns)": [
  {
   "kind": "span",
   "step": "layer1_filter",
   "code": "layer1.decide",
   "level_or_status": "ok",
   "message": null,
   "duration_ms": 0
  },
  {
   "kind": "event",
   "step": "layer1_filter",
   "code": "layer1.decision.made",
   "level_or_status": "info",
   "message": "L1_DROP_RUBRIC_OUT",
   "duration_ms": null
  }
 ]
}
```
