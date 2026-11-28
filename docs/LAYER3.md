# LAYER3: German and French summaries on the database

> **Status: V1 on branch `layer3/summ-writer` (merged with `main` @ `42a7b043`, which carries the frontend developer's Suva Scout merge), 28 Nov 2026, run live on 12 real rulings.** Decisions D-095 to D-098 in `docs/DECISIONS.md` (all PROPOSED). Audit: `tmp/audits/audit-layer3-summaries-2026-11-28.md` (git-ignored). Database changes: `docs/DDL_CHANGES.md` (entry of 28 Nov, layer 3). Owners: the summary engine (`src/summarize/`) is the summary owner's; the writer (`src/layer3/`), the registry and this page are the lead's while D-024 is open. **Not measured yet:** no live run on the 70B, no quality measure on unseen rulings (§10, §11).

## 1. What it does

Layer 3 is the pipeline step `summarise` (stage S6 of `make run`, with S7 `verify` inside it). For each selected ruling it writes **one German and one French summary** in Suva's style, each written from the ruling, never translated from the other (D-014), and stores them in `summ.*` as one version of the mandatory preset `suva_house` (D-067, D-068), with every sentence checked and every Apertus call traced.

Thesis, applied: **Apertus reads, the code verifies, the lawyer decides.**
- Apertus chooses which ruling sentences the summary must state (by sentence id), writes each fiche, and reads entailment (Ja/Nein).
- Code copies the ruling sentences, checks who says them, adds the outcome sentence, renders the title line, finds the consideration labels, splits the considerations, runs ten checks per sentence and decides the version's quality.
- The lawyer reads the version in the UI, edits it (`summ.create_expert_version`) or validates it (`gold.submit_review`); a pipeline rerun never displaces a current expert edit (D-098).

Which rulings, while Q-17 is open: the **top 10 by layer-2 `score_raw` in `2026Q2_union`**, plus every pending summary request of the API (D-096).

## 2. The flow

```text
select ──► per ruling: load ──► segment ──► engine (record ──► write DE ║ write FR ──► verify ──► finish) ──► plan ──► files ──► one transaction
```

| # | Step | Who | What happens | Where |
|---|---|---|---|---|
| 1 | Select | code | top `limit` rulings of `population` by `score_raw` in the latest usable `layer2_judge` run of the profile, minus the two few-shot dockets; or `--dockets`; plus the pending `ops.user_request` rows of kind `summary` (D-096) | `src/layer3/run.py` `top_rulings`, `pending_requests` |
| 2 | Load | code | the primary `corpus.ruling_text`, the decision date, the language, `gegenstand`, the matter rubric (`corpus.subject_observation`, Neuheiten first) | `run.py` `load_source` |
| 3 | Segment | code | the court's numbered considerations after the reasoning heading and before the operative part (segment V0.1.0, D-097) | `src/layer3/segment.py` `split` |
| 4 | Record | Apertus + code | once per ruling, shared by both languages: code builds candidate sentences; Apertus names 3 to 8 propositions by sentence id with a slot (`question`, `fact`, `rule`, `condition`, `answer`) and a speaker (`court`, `lower_court`, `appellant`, `respondent`, `expert`); code copies each sentence, checks the speaker, refuses a party's or the lower court's sentence given as the court's, finds the court's answer when missing; one retry | `src/summarize/v3/record.py`, `src/summarize/extract/` |
| 5 | Write | Apertus | one call per language, in parallel: the whole fiche as sentences, each naming 1 or 2 proposition ids (an enum, G1); the prompt holds the record, the parties, two of Suva's example fiches of that language, the required glossary terms and the ruling text (delimited, G4) | `src/summarize/v3/write.py`, `src/summarize/examples.py` |
| 6 | Verify | code + Apertus | per sentence: the code checks, the speaker check, then an entailment reading P(Ja) ≥ 0.9 against the ruling sentence(s); a failed sentence gets one repair call, else it is removed; one call per required proposition no sentence states; near-duplicates out; trim to 0.9 of the upper end of Suva's length band | `src/summarize/v3/verify.py`, `src/summarize/refine/entail.py` |
| 7 | Finish | code | the outcome sentence from the operative part, once; the closing bench note; statute abbreviations in the fiche's language; references not in the ruling dropped | `src/summarize/finish.py` |
| 8 | Fallback | Apertus + code | a failed record sends both languages to the prompt writer v2; a failed v3 fiche (fewer than 2 kept sentences, or no required proposition) sends that language only; v2 = one call, up to two repairs, then `finish` | `src/summarize/engine.py` `_v2_fiche`, `src/summarize/summarize.py` |
| 9 | Review | code | the deterministic checker on every fiche (outcome sentence, articles present in the source, sigils of the wrong language, Suva named only if the ruling names it, pasted operative part); a v3 fiche gets its confidence by code (not calibrated) | `summarize.review`, `src/summarize/v3/confidence.py` |
| 10 | Plan | code | title lines, claims, sections, citations, checks, removed sentences, the version's quality (D-098) | `src/layer3/render.py` |
| 11 | Files | code | `data/runs/<run_id>/` written before any row (D-061) | `run.py` `_write_files` |
| 12 | Store | code | one transaction for the whole run; a version with a missing language never reaches the database (deferred pair trigger, D-067) | `src/layer3/store.py` |

Every Apertus call goes through the run's one `src/llm/client.py` client (G2), live or from the replay cache, with the large model (`LLM_NAME`). The engine wraps the client's observer and turns every attempt and every cache hit into one `CallRecord`; the writer stores each as one `ops.llm_call` (§5).

## 3. The engine: `v3@a4a1504`, ported as a snapshot (D-095)

- **Origin.** The summary owner's v3 writer, branch `summarize/v3` at commit `a4a1504` (lineage `refine` → `extract` → `v3`). That branch also deletes `main`'s data layer (`src/db/sql`) and stores into its own `public.*` tables; it is **never merged** (the rule of D-075). Its summary code is ported onto `main` unchanged; its storage (`pipeline.py`, `suva_data`, `suva_app`, `db/migrations`, `src/web`) is not.
- **Snapshot.** `ENGINE_VERSION = "v3@a4a1504"` in `src/summarize/engine.py`, and `config.engine` of `summarise` V1.0.0. A later change of the engine comes by PR on `main` and gets a new `summarise` version (D-064).
- **Entry point.** `summarise(source: RulingSource, client, *, examples=None, writer="v3") -> EngineResult` (`src/summarize/engine.py`). The contract is `src/summarize/engine_types.py`: `RulingSource`, `Proposition`, `Sentence`, `Fiche`, `CallRecord`, `EngineResult`. No database, no file: the engine is tested with a fake gateway, the writer with a fake engine.
- **What differs from the branch** (outside v3's logic): a v2 call that fails gives a `failed` fiche (the branch stopped with `SystemExit` and stored nothing). A replay miss propagates as `ReplayMiss` and is never a fallback, also when v3 caught it as a sentence problem ("entailment not read: … ReplayMiss"): the engine checks its calls after v3 and raises, so a replayed version is the recorded one or none. A kept sentence's `text` is the sentence as it reads in the body (the per-sentence part of `finish`: full stop, markdown, abbreviations in the fiche's language, references the ruling lacks dropped). Any exception leaving `summarise()` after its first call carries `engine_calls` (the CallRecords made) and `engine_version`, so the writer stores those calls. A call whose answer the refine `Model` rejected (invalid JSON or schema, before its `/retry`; a reading with no Ja or Nein) is marked `client_log.invalid_answer`.
- **Local fixes on top of `a4a1504`** (to report to the summary owner, the bugs are upstream): `refine/evidence.py` `passages()` raised `ValueError` (zip) on a ruling with a reasoning heading but no numbered consideration, so the ruling never reached the v2 fallback; `as_data()` now neutralises every closing tag (`</ruling_sentence>`, `</sentence>`, `</a>`, `</b>`…), not only `</ruling>` (G4); `refine/entail.py` refuses a premise over 8,000 characters (`ModelFailed`, "not read") instead of cutting it silently (G4). A text without such a tag or premise gives the same prompt, so the same cache key, as on the branch.
- **Code identity.** The engine's prompts are not in `ops.prompt_version`, so the code hash is their identity (F-09): `summarise` V1.0.0's `code_sha256` and each run's `params.code_sha256` cover the writer, the contract and the engine's whole import closure (`ENGINE_CODE_GLOBS` in `src/layer3/models.py`: `engine.py`, `examples.py`, `finish.py`, `summarize.py`, `prompts.py`, `v2/`, `v2/glossary.json`, `v3/`, `refine/**`, `extract/`, `src/areas.py`). A test checks that every module the engine loads is covered. A changed prompt changes the hash.
- **Few-shot examples.** Two of Suva's 55 exports, fixed by the summary owner (`FEW_SHOT_DOCKETS` in `src/summarize/examples.py`). Only the `<p>` paragraphs under `Text DE` and `Text FR` are read from `judgements/Export_*.html`; every other section, the author section included, is dropped while parsing and never held in memory (D-051). A prompt holding them lives only in the git-ignored client cache, the git-ignored run files and `ops.blob` (D-031). Those two dockets are never summarised: selection skips them and `--dockets` refuses them (`L3_FEW_SHOT_EXAMPLE` for a request).

### 3.1 Calls per ruling

| Purpose (`ops.llm_call.purpose`) | Prompt tag (`params.prompt_tag`) | Step | Model role | Parameters |
|---|---|---|---|---|
| `record` | `record@1/read`, `record@1/again`, `…/retry` | `summarise` | `judge` | JSON mode, T = 0 |
| `write` | `v3-write@2/de`, `v3-write@2/fr` | `summarise` | `generator` | JSON mode, T = 0, max 1,500 tokens |
| `repair` | `v3-verify@1/repair` | `summarise` | `repair` | JSON mode, T = 0 |
| `missing` | `v3-verify@1/missing` | `summarise` | `generator` | JSON mode, T = 0 |
| `entail` | `entail@1/v3` | `verify` | `judge` | 1 token, top 20 log-probabilities, T = 0 |
| `v2_write`, `v2_repair` | `v2` | `summarise` | `generator`, `repair` | plain text, T = 0, max 1,200 tokens |

Budgets in code: the record at most 12 calls; each language at most 6 + 3 × (2 × propositions + 2) calls (`src/summarize/v3/__init__.py`). The summary owner measured about 10 to 16 calls per fiche and 20 to 50 s per ruling live, 0.3 s replayed, on 4 tuning rulings (branch `summarize/v3`, `docs/V3.md`): **the summary owner's measurement, not ours**. `ops.model_role` has no labeller role, so the reading calls (`record`, `verify`, `entail`) are bound to `judge` (`summarise.json` `config.call_roles`).

## 4. Files

| Path | What |
|---|---|
| `src/summarize/engine.py` | the engine: the branch's per-ruling logic, the gateway shim (`CallRecord` per attempt or cache hit), the mapping of v3's problems to the ten check codes |
| `src/summarize/engine_types.py` | the contract between the engine and the writer |
| `src/summarize/examples.py` | Suva's two example fiches per language, read from `judgements/` at run time (D-031, D-051) |
| `src/summarize/v3/`, `extract/`, `refine/`, `finish.py`, `src/areas.py` | ported unchanged from `a4a1504` (`extract/` and `refine/` are in v3's import closure; refine rounds and the extractive writer are not wired) |
| `src/summarize/summarize.py`, `v2/prompts.py`, `v2/glossary.json` | the v2 fallback, the branch's version (matter routing through `src/areas.py`); the old trial entry point (`summarize.py <docket>`, `data/trial/`) is removed |
| `src/layer3/run.py` | the step: selection, requests, engine calls, files, the run's transaction, statuses |
| `src/layer3/segment.py` | segment V0.1.0, the own splitter (D-097) |
| `src/layer3/render.py` | what code decides before storage: title line, claims, sections, citations, checks, quality (D-098) |
| `src/layer3/store.py` | the database load: spans, blobs, calls, segmentation, summary, version, texts, claims, citations, checks, the current-version switch |
| `src/layer3/presets.py` | `summ.preset_version` from `src/layer3/registry/presets/*.json` |
| `src/layer3/models.py` | configuration models of segment, summarise, verify and the preset; the shared `CHECK_CODES` |
| `src/layer3/registry/{segment,summarise,verify}.json`, `registry/presets/suva_house.json` | the versions (D-064), loaded by `python -m src.ingest registry` |
| `src/db/seed/profiles.json` | profile `default` V0.4.0 pins segment V0.1.0, summarise V1.0.0, verify V1.0.0 |
| `src/db/sql/95_seed_reference.sql`, `80_triggers.sql` | 16 reason codes; the version trigger runs as owner (`docs/DDL_CHANGES.md`) |
| `tests/test_engine.py` (32), `tests/test_layer3_unit.py` (19), `tests/test_layer3_db.py` (8, `-m db`) | engine with a declared fake gateway; writer without a database; end to end on PostgreSQL with a declared fake engine and a fake layer-2 gateway |
| `tests/test_v3_*.py`, `test_refine.py`, `test_extract.py`, `test_summary_finish.py`, `test_areas.py`, `test_summary_prompts.py` | the branch's tests, ported (minus the 8 that need its database or `suva_data`) |

## 5. What a run writes, and why

### 5.1 Files first (`data/runs/<run_id>/`, git-ignored)

| File | One record = | Keys |
|---|---|---|
| `summaries.jsonl` | one ruling | `ruling_id, docket, decision_date, rank_score, requests, outcome, reason_code, error, quality, segmentation {status, considerations, coverage_ratio}, texts[] (the stored plan per language), result (the EngineResult without its calls), started_at, finished_at` |
| `calls.jsonl` | one call or cache hit | every `CallRecord` field but the messages, plus `ruling_id, messages_sha256, cache_key` |
| `messages.jsonl` | one message set | `sha256, content` (holds Suva's example fiches: D-031, never committed) |
| `manifest.json` | the run | `run_id, step, versions, preset, profile, mode, population, layer2_run, engine_declared, model_declared, model_resolved, model_override, files` (SHA-256 of each), then after the commit `status, metrics, outcomes` |

### 5.2 Database, in one transaction

| Table | Rows | Columns that matter | Why |
|---|---|---|---|
| `ops.pipeline_run` | 1 per run, kind `summarise` | `profile_version_id`, `component_version_id` (summarise), `params` (versions, preset, population, limit, layer-2 run, few-shot dockets, `code_paths`, `code_sha256`), `mode`, `resolved_models`, `model_override`, `status` | one execution = one trace (D-065); `model_override` when `LLM_NAME` is not the declared 70B (D-064) |
| `ops.span` | per ruling `layer3.summarise`; per call `llm.call`; per stored ruling `segment.split` and `verify.checks` | `step` (`summarise`, `verify`, `segment`), `status`, `error_reason_code`, `attributes` (calls, engine, record status, quality; purpose, prompt tag, cache hit) | every call, segmentation and check links to its span (D-065) |
| `ops.blob` | 1 per distinct message set | `sha256`, `content` (canonical JSON) | the exact messages sent, content-addressed |
| `ops.llm_call` | 1 per attempt or cache hit | `step`, `purpose`, `language`, `cache_key`, `cache_hit`, `mode`, `endpoint`, `model_role`, `requested_model`, `served_model`, `served_model_header`, `params` (request parameters, `prompt_tag`, `size`, `cache_key_source`), `messages_sha256`, `raw_output`, `finish_reason`, `parsed_ok` (false for an answer the engine rejected: `invalid_answer`, or followed by its `/retry`), `parse_error` (that reason, or the client's `length` / `json_format_unsupported`; never an HTTP kind), `http_status`, `error_reason_code` (`L3_REPLAY_MISS` for a replay miss), `attempt`, tokens, `latency_ms` | G2, G3: every call, its model and its answer; recorded for every ruling the engine made calls for, failed, skipped or unchanged included, also in a run that ends `failed` (§8). A call refused before any attempt (a replay miss) carries the run's mode and the client's cache key recomputed (`cache_key_source` `writer_formula`) |
| `corpus.segmentation` | 1 per (text, segment version), reused when stored | `method` `own_splitter`, `status` `ok` \| `failed`, `consideration_count`, `expected_count` NULL, `coverage_ratio`, `offsets_found_ratio`, `is_primary` **false** | `summary_version.source_segmentation_id` is NOT NULL and citations must point into it (D-097) |
| `corpus.consideration` | 1 per numbered consideration | `ordinal`, `e_number` (the court's numbering), `depth`, `parent_consideration_id`, `char_start`, `char_end`, `content`, `content_sha256`; `cid` and `is_citable` generated | what a claim cites, by id (G1) |
| `summ.summary` | 1 per (ruling, `suva_house`) | uuid5 of ruling and preset | identity |
| `summ.summary_version` | 1 per ruling stored | `origin` `generated`, `parent_version_id` NULL, `preset_version_id` (suva_house V1.0.0), `component_version_id` (summarise V1.0.0), `source_segmentation_id`, `creator_kind` `pipeline`, `creator_run_id`, `quality_status` `verified` \| `flagged`, `is_current`, `mode` (`LIVE` \| `REPLAY`), `span_id`; `version_no` by trigger | an immutable DE + FR pair (D-067) |
| `summ.summary_text` | exactly 2 per version (`de`, `fr`) | `title_line` (code), `body` (engine, after `finish`), `word_count`, `paragraph_count` (1..20), `llm_call_id` (the language's write call), `repair_llm_call_id` | each text tied to the call that wrote it from the ruling (D-014, trigger) |
| `summ.summary_claim` | 1 per kept sentence | `ordinal`, `paragraph_no`, `section`, `model_text` (the model's sentence; over 300 characters cut at 300 with "…", the full text in its entailment check's `detail.model_text_full`; NULL only for code's sentences), `rendered_text` (the sentence as it reads in the body), `status` `verified` \| `flagged` (also flagged when the sentence is not found in the body: `detail.not_in_body`) | the sentences the UI shows and marks (D-098) |
| `summ.claim_citation` | 0..n per claim | `consideration_id`, `ordinal` | label → consideration, resolved by code; never guessed (D-098) |
| `summ.verification_check` | per claim, 1 per check code the engine read; per removed sentence, 1 text-level `fail` per failed code, or 1 `not_applicable` under `V3_ENTAILMENT` when the engine read its checks and none failed (left out for length: `detail.removed_for`), or 1 `fail` under `V3_ENTAILMENT` when the engine named no check (`attributed` `fallback`) | `target_kind` `claim` \| `text`, `rule_id` (V3_*), `status` `pass` \| `fail` \| `not_applicable`, `detail` (entailment, label, quote, why_not), `run_id`, `span_id` | the verify step's evidence (S7), one rule per code (D-098) |
| `ops.user_request` | the run's summary requests | `status` `accepted` → `done` \| `failed`, or `rejected`; `run_id`; `status_detail` (version, or reason code and label) | the API's "summarise this ruling" closed with an answer |
| `ops.log_event` | per run and per ruling | `layer3.run.selected`, `layer3.run.summary`, `layer3.files.written`, `layer3.checks.unknown`, `layer3.summary.stored` \| `unchanged` \| `not_made` | logs as data (D-065) |
| `ops.run_metric` | per run | `rulings_in, stored, unchanged, failed, replay_misses, verified_versions, flagged_versions, v2_fallback_fiches, llm_calls, cache_hits, live_calls, llm_errors, claims, claims_flagged, claims_cited, checks_failed, removed_sentences, segmentations_ok, segmentations_failed, expert_current_kept, requests_done, requests_failed, requests_rejected, model_override` | the run's counts, queryable |

Not written: `ops.prompt_version` and `summ.preset_version_prompt` (the engine's prompts are code, not versioned prompt files; the write prompt holds Suva's fiches, D-031), so `ops.llm_call.prompt_version_id` is NULL and the prompt tag is in `params.prompt_tag`; `ops.llm_call_example` (the result does not say which examples a call carried); `ops.work_item` (the run is bounded and a rerun is idempotent).

### 5.3 Ids and reruns

Ids are uuid5: `summary|<ruling>|suva_house`, `summary_version|<run>|<ruling>|suva_house`, `summary_text|<version>|<lang>`, `summary_claim|<text>|<ordinal>`, `segmentation|<text_id>|<segment version>`, `consideration|<segmentation>|<ordinal>`, `llm_call|<run>|<ruling>|<call_id>`. Reloading the same run is refused by primary keys, never duplicated. A rerun whose titles, bodies, summarise version, preset version and segmentation all equal the latest version the pipeline wrote adds no version (outcome `unchanged`), also when an expert edit is current (it was compared with the expert's text before, so every rerun added a version); a changed text adds version n+1 and makes it current, unless an expert edit is current.

## 6. The trace: from a sentence to the ruling

Every sentence of a stored summary answers four questions from the database alone:

```sql
-- 1. Which sentences, with their status and section (the API's query)
SELECT t.language, c.ordinal, c.section, c.status, c.rendered_text
FROM summ.v_summary_current v JOIN summ.summary_text t USING (summary_version_id)
JOIN summ.summary_claim c USING (summary_text_id)
WHERE v.ruling_id = :ruling AND v.preset_code = 'suva_house' ORDER BY t.language, c.ordinal;

-- 2. Which consideration each sentence rests on (offsets into the stored ruling text)
SELECT c.claim_id, k.e_number, k.char_start, k.char_end, k.content
FROM summ.claim_citation cc JOIN summ.summary_claim c USING (claim_id)
JOIN corpus.consideration k USING (consideration_id) WHERE c.summary_text_id = :text;

-- 3. Which checks passed or failed, with the evidence (entailment, ruling sentence, label)
SELECT c.ordinal, r.rule_code, vc.status, vc.detail
FROM summ.verification_check vc JOIN ops.rule r USING (rule_id)
LEFT JOIN summ.summary_claim c USING (claim_id)
WHERE vc.claim_id IN (SELECT claim_id FROM summ.summary_claim WHERE summary_text_id = :text)
   OR vc.summary_text_id = :text;            -- text-level rows = removed sentences

-- 4. Which call wrote the text, and every call of that ruling in that run
SELECT l.purpose, l.params->>'prompt_tag', l.served_model, l.cache_hit, l.finish_reason, l.latency_ms,
       b.content AS messages, l.raw_output
FROM ops.llm_call l JOIN ops.blob b ON b.sha256 = l.messages_sha256
WHERE l.run_id = :run AND l.ruling_id = :ruling ORDER BY l.started_at;
```

The record's propositions (slot, speaker, ruling sentence, label, accepted or refused by code) and every sentence the engine wrote, repaired or removed are in `summaries.jsonl` (`result.propositions`, `result.fiches.<lang>.sentences`); a removed sentence is also a text-level `verification_check` with its text and `why_not` in `detail`.

## 7. Commands

| Situation | Command |
|---|---|
| After pulling this branch, an existing database | `make db-deploy` (a function and seed rows, no structural change: no reset; the cluster's `migrate` passes its schema guard), then `make db-registry` (segment, summarise, verify, preset suva_house V1.0.0, profile `default` V0.4.0) |
| A fresh database | `make db-up`, `make db-reset`, `make db-registry`, `make ingest-base PARQUET=…`, `make ingest-gold`, `make layer1`, `make layer2 … --population 2026Q2_union`, then `make layer3` |
| Live, a slice first | `make layer3 MODE=live ARGS="--limit 3"`, then `make layer3 MODE=live` (top 10). Needs `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_NAME` = the 70B (in `.env.local` or the environment; an exported variable wins) |
| Given rulings | `make layer3 MODE=live ARGS="--dockets 8C_493/2025 8C_307/2025"` |
| Another population or size | `make layer3 ARGS="--population 2026Q2_decision --limit 20"`; `--population ''` = the whole layer-2 run |
| Replay | `make layer3` (default `MODE=replay`, store `data/derived/llm`); `ARGS="--store DIR"` for another cache |
| The UI's pending requests only | `make layer3-requests` (`MODE=live` to call Apertus) |
| Leave the requests for later | `make layer3 ARGS="--no-requests"` |
| More rulings at once | `ARGS="--workers 2"`; each ruling already writes DE and FR in parallel, and the client's limiter caps concurrent calls (`LLM_CONCURRENCY`, D-030) |
| In `make run` | stage S6 (top 10, `2026Q2_union`, requests included); S7 prints that it runs inside S6 |
| In the cluster | the `pipeline` job runs `make run SERVE=0`, so S6 runs there with no compose change (D-090); in replay it needs the answers in the `data/derived` slot, in live `MODE=live` and `LLM_*` |
| A run ended `partial` | rerun the same command: answered calls come from the cache, unchanged texts add no version |
| A run ended `failed` | read `ops.pipeline_run.error_summary`, the run's events, `data/runs/<run_id>/manifest.json` and `summaries.jsonl` (`reason_code`, `error`); fix; rerun |

`make run` S6 is **skipped with its reason, never faked**: without `DATABASE_URL`; in replay without `data/derived/llm/cache`; in live without `LLM_*`; without a usable layer-2 run of the pinned `layer2_judge` version; when the profile does not pin the layer-3 steps (`make db-registry` not run); when nothing is selected; when no selected ruling has a recorded answer in replay. It fails (exit 1) on any other failed run.


**While G-14 is open** (the default profile's layer 2 is the scorer, which `src/layer2` cannot run): run layer 2 and layer 3 on profile `summaries_8b`, which pins the 8B judge:

```
make layer2 MODE=live PROFILE=summaries_8b ARGS="--population 2026Q2_union --all"
make layer3 MODE=live PROFILE=summaries_8b ARGS="--limit 10"
```

## 8. Modes and failures

**Modes.** `live` calls the gateway through the client (G3: no default for `LLM_*`, served model checked against `MODELS.md`). `replay` answers from the client's cache only; a miss raises `ReplayMiss`, the engine lets it through (also one v3 had caught as a sentence problem), and the ruling is `skipped` with `L3_REPLAY_MISS`: no version, no fallback; the cache hits before the miss and the missed call are stored. Each `ops.llm_call` row says `LIVE` or `REPLAY` (a cache hit in a live run is `REPLAY`); each version carries the run's mode.

**Per ruling.**

| Outcome | Reason code | What is stored |
|---|---|---|
| `stored` | | the version, its texts, claims, citations, checks; current unless the current one is an expert edit |
| `unchanged` | | no version; the calls and the span |
| `failed` | `ING_TEXT_MISSING` | no call (G4); the span |
| `failed` | `L3_ENGINE_FAILED` | an engine exception (the calls it made, handed back as `engine_calls`, and the span), an answer for another ruling, more than 20 paragraphs, or any other error while planning the texts (the calls and the span); never the run's failure |
| `failed` | `L3_LANGUAGE_MISSING` | a fiche without text: no version (D-067); the calls and the span |
| `failed` | `L3_FICHE_UNTRACED` | a fiche whose write call is not in the result: no version (D-014); the calls and the span |
| `skipped` | `L3_REPLAY_MISS` | the calls made before the miss, the missed call (`error_reason_code` `L3_REPLAY_MISS`) and the span |

When the engine raises (a replay miss, a bug), the exception carries the calls it made (`engine_calls`); the writer keeps them as a `failed` result with no fiche, so they reach `ops.llm_call` and `calls.jsonl` like any other ruling's.

A v3 fiche that fails falls back to v2 for that language inside the engine: the ruling is still `stored`, its version `flagged`, and the fiche's problems start with `v3: <reason>`. A v2 call that fails gives a `failed` fiche, so the ruling ends `L3_LANGUAGE_MISSING`.

**Per request.** `pending` → `accepted` (with the run id) → `done` (the version id and its quality) or `failed` (the ruling's reason code and label). A request for another preset is `rejected` with `L3_PRESET_UNAVAILABLE`; a request for a few-shot docket with `L3_FEW_SHOT_EXAMPLE`. A failed run never leaves a request `accepted`.

**Per run.** `succeeded` (every ruling stored or unchanged), `partial` (some failed or skipped: rerun), `failed` (none could be stored: every attempted ruling's span, the blobs and one `ops.llm_call` per call, the requests' failure, events and metrics are committed first, then the run is closed `failed`; on an error while loading, nothing but the run row and the requests' failure), `aborted` (Ctrl-C). On any failure `manifest.json` is rewritten with status `failed` (or `aborted`) and the error, never left `loading`.

**Per call.** The client retries (at most 4 attempts, timeout per call) and classifies errors; a failed call keeps its `error_reason_code` (`WORK_TIMEOUT`, `WORK_RATE_LIMITED`, `WORK_MODEL_MISMATCH`, `WORK_PARSE_ERROR`, `WORK_HTTP_ERROR`).

## 9. Versions (D-064)

| Registry row | Version | Config, in one line |
|---|---|---|
| step `segment` | V0.1.0 | `own_splitter`, heading rules from `refine/evidence.py` @ `a4a1504`, citable at depth ≥ 1, offsets located, never primary (D-097) |
| step `summarise` | V1.0.0 | engine `v3@a4a1504`, fallback `v2`, languages `de` + `fr`, a model role per call purpose, quality rule, keep an expert edit current, skip unchanged texts; models generator, repair, judge = `apertus-v1-5-70b` (D-095) |
| step `verify` | V1.0.0 | the ten check codes in order, rule prefix `V3_`, entailment ≥ 0.9, one repair, removed sentence = one text check per failed code (`V3_ENTAILMENT` `not_applicable` when none failed, `fail` when the engine named none); model judge = `apertus-v1-5-70b` (D-098) |
| preset `suva_house` | V1.0.0 | perspective 5, style by the ruling's language (Q-30), writer v3, title lines `BGer-Urteil {docket} vom {date}` and `Arrêt du TF {docket} du {date}`, the matter appended only in the ruling's language |
| profile `default` | V0.4.0 | ingest V1.0.0, layer1_filter V1.1.0, layer2_judge V1.0.0, segment V0.1.0, summarise V1.0.0, verify V1.0.0 (draft V0 until justification and ranking have versions) |

The ten check codes, the same list in the engine (`Sentence.checks`) and in the writer (rule `V3_<CODE>`): `language`, `placeholder`, `new_identifier`, `modal_strength`, `glossary_term`, `suva_named`, `outcome_restated`, `speaker`, `entailment`, `duplicate`. They are not the verifier checks V1 to V6 of `docs/ARCHITECTURE.md` S7 (`V3_NUMBERS_PRESENT` is one of those, an unrelated planned check that shares the prefix).

## 10. Measured

| Item | Value | Source |
|---|---|---|
| Database change | structure identical (1,291 objects), 1 function changed, 16 reason codes added (48 → 64); no view, trigger or grant change | two fresh deploys, `main` @ `95d744a` vs this branch, 28 Nov (`docs/DDL_CHANGES.md`) |
| SQL tests on the new DDL | 11 of 11 | `python -m src.db.deploy test`, same database |
| Layer-3 database tests | 9 of 9 on a fresh PostgreSQL 17, after the review fixes (a run with no ruling stored commits its calls; a rerun after an expert edit adds no version) | `pytest -m db tests/test_layer3_db.py` (fake engine and fake layer-2 gateway, declared) |
| Every database test (layers 1 to 3), before the merge with the frontend developer's merge | 59 of 59 | `pytest -m db`, same server, 28 Nov |
| Every database test after merging `main` @ `42a7b043` | layer 1 and layer 3 green; **10 layer-2 tests fail, identically on a clean `main` @ `42a7b043`** (the scorer pinned as `layer2_judge` V2.0.0 in the default profile does not fit `src/layer2/run.py`'s config: `max_failed_share`); not caused by layer 3 (gap G-14) | `pytest -m db`, 28 Nov 13:11 |
| Tests without a database | ruff clean; 593 passed, 60 skipped | 28 Nov, after the review fixes |
| Engine tests | 34 of 34; 3 deliberate breaks (language slot, fallback, check mapping) turned them red, then green; the replay miss v3 caught and the engine bug that hands its calls back added after review | `tests/test_engine.py` (fake gateway behind a real client, declared) |
| Engine on 3 real rulings (DE, FR, IT) | no crash, every problem mapped to a check code, fallbacks as expected; **fake gateway, no Apertus call** | engine port session, 28 Nov; files deleted |
| Live run, 3 rulings, one per language (8C_514/2025 DE, 8C_256/2025 FR, 8C_254/2025 IT) | 3 stored, 3 `flagged`; 81 Apertus calls, 81 without error; 6 of 6 texts linked to the call that wrote them; median 135 words DE, 221 FR; 49 claims, 39 cited to a consideration; checks 344 pass, 6 fail, 46 not applicable; fiche bands 5 high, 1 low; v3 wrote all 6 fiches (no v2 fallback); 117 s | `results/layer3_live.json`, run `42cd8fa7` |
| Live run, top 10 by layer-2 `score_raw` in `2026Q2_union` | 10 in: 9 stored + 1 unchanged (8C_514/2025, stored by the run above: same texts, no new version); 4 `verified`, 5 `flagged`; 232 calls, 232 without error; 18 of 18 texts linked; median 149 words DE, 192 FR; 126 claims, 103 cited; checks 888 pass, 20 fail, 142 not applicable; fiche bands 17 high, 3 medium; v3 wrote all 20 fiches; 303 s | `results/layer3_live.json`, run `8711b14b` |
| Live smoke (frozen copy of the code before the review fixes) | 1 ruling (8C_514/2025): 26 calls, 0 errors, 18 claims, 16 cited, 67 s; the API's view showed DE + FR | integration database, 28 Nov 12:55 (not in `results/`: superseded by the two runs above) |
| Quality on unseen rulings | **not measured** (no hold-out run, `docs/agents/summarise.md` step 5) | n/a |

## 11. Known gaps

Each gap: what is missing, the evidence, what it costs (the graded outputs, traceability, operations), and the next step that closes it. Nothing below is solved by this version; a gap closes only with its own change and its own evidence.

| # | Gap | Evidence | Impact | Next step |
|---|---|---|---|---|
| G-1 | **v3 is not measured on unseen rulings.** No hold-out, no human reading, no comparison with v2. | Summary owner's `docs/V3.md` (4 tuning rulings, not committed here); `docs/agents/summarise.md` done-when (hold-out on 23 rulings, `results/summaries_holdout.json`) not met | The top 10 graded by Suva's experts come from an unmeasured writer; the confidence band is the only quality signal | Run the hold-out of `summarise.md` step 5 (23 Q3/2025 rulings with Suva's exports), human-read, write `results/summaries_holdout.json`; threshold written before measuring (G10) |
| G-2 | **Confidence is not calibrated** and lives only in `summaries.jsonl`. | `src/summarize/v3/confidence.py` (hand-set weights 0.4/0.3/0.2/0.1) | A "high" band is not a probability of being correct; the UI cannot sort on it from the DB | Calibrate on G-1's hold-out; store it (a `verification_check` text-level row or a DDL column, DDL owner) |
| G-3 | **Splitter V0** (`own_splitter`, never primary), not measured against the HF considerations. | D-097; `src/layer3/segment.py`; `corpus.segmentation.expected_count` NULL | A citation can be missing where the splitter found no numbered consideration (never wrong: an unresolved label stays uncited) | DB-12: the HF `erwaegungen_paragraphs` segmentation and D-070's acceptance criteria; then make it primary |
| G-4 | **A v2 fallback fiche has no claims and no checks.** | `src/layer3/store.py` (claims only from v3 sentences); D-098 | That language is stored `flagged` with a body and an empty sentence list: no sentence-level trace for it | Count fallbacks per run (metric `v2_fallback_fiches`); reduce them with G-1; verify v2 bodies sentence by sentence (a v2 trace) |
| G-5 | **Prompts are not registered in `ops.prompt_version`; `ops.llm_call_example` is not written.** | `src/layer3/registry/summarise.json` (no prompt rows); §5.2 | Every call is traced (messages in `ops.blob`, prompt tag in `ops.llm_call`), but the prompt templates are versioned by code tag, not by a row; few-shot hygiene is proven by code (`FEW_SHOT_DOCKETS` never summarised), not by rows | Register the v3 prompt templates as `ops.prompt_version` rows (marked `contains_suva_material`) and write `ops.llm_call_example` for the two example fiches |
| G-6 | **Engine snapshot, three local fixes.** The engine is `v3@a4a1504` plus three fixes made here: `passages()` zip crash, `as_data()` closing tags, entailment premise over 8,000 characters refused instead of cut (G4). | `src/summarize/engine.py` docstring; `src/summarize/refine/evidence.py`; `src/summarize/refine/entail.py:31` | The summary owner's branch and `main` diverge; a later v3 change does not reach `main` by itself | The summary owner takes the three fixes upstream; later engine changes come to `main` by PR on this code, with a new `summarise` version (D-064) |
| G-7 | **No ranking (S4), so no release and no release gate.** | `src/cli.py` S4 stub; `summ.mandatory_summary_gaps` reads a release's ranking (`60_views.sql`) | "Top 10" is layer 2's `score_raw` (D-096), not the frozen F2 ranking; the gate that every in-scope ruling has a `suva_house` summary cannot run | Build S4 (D-021, D-046); then the release gate checks layer 3's coverage |
| G-8 | **Selection while Q-17 is open.** | D-096 | If Suva grades the June 2026 summaries (deck) rather than our top 10 (template), the summarised set may miss them | When Q-17 is answered, change `selection` in a new `summarise` version; D-047's window is a parameter |
| G-9 | **A full replay is incomplete.** Layer 2 has no recorded answer for the 23 Q3/2025 reference rulings, so a replayed `make run` stops at S3 there (above the 2 % share); layer 3 replays only the rulings it ran live. | `docs/DEPLOY.md` §10 (measured 28 Nov); `L3_REPLAY_MISS` | The judges' replay path summarises only what was recorded | One live pass of layer 2 on the 23 rulings; record the layer-3 run of the top 10 in the replay store shipped with the demo |
| G-10 | **The publication mark is not read** (`RulingSource.starred` unset). | `corpus.ruling.star` empty for every ruling (no Neuheiten feed) | The closing note never says "zur Publikation vorgesehen" | Crawl the Neuheiten rubric and star (`corpus.subject_observation` source `neuheiten`) |
| G-11 | **Italian rulings**: both fiches are written from the Italian text; no matter in the title of an Italian ruling. | Summary owner's report (weakest fiche on their one Italian ruling); `src/layer3/render.py` | Lower quality expected for Italian rulings | Measure Italian separately in G-1 |
| G-12 | **The trial script is gone** (`python3 src/summarize/summarize.py <docket>`, `data/trial`); `docs/SUMMARY_MEASUREMENT.md` and `docs/SUMMARY_V2.md` describe it. | `src/summarize/summarize.py` (branch version, trial `main()` removed) | Those two docs' numbers are the probes', not layer 3's | Mark both docs as historical, pointing here |
| G-13 | **The frontend V1 is not wired to `main`'s API.** It was built on PR #42's API (`/api/rulings/{id}/workspace`, confirm, revise) over its own `public` schema. | `docs/API.md` (PR #53) vs PR #42's `src/suva_app/` | The summaries stored here reach the UI only once the frontend reads `main`'s API | The consolidation phase: map each screen to `docs/API.md` and `summ.v_summary_current` |
| G-14 | **Layer 2's database tests fail on `main`** since the scorer became `layer2_judge` V2.0.0 in the default profile (V0.4.0, kept in V0.5.0). | 10 failures in `tests/test_layer2_db.py` and errors in `tests/test_api_db.py` (`Layer2Config`: `max_failed_share` and 12 more fields, `src/layer2/run.py:147`), identical on a clean `main` @ `42a7b043`; also `tests/test_triage_features.py::test_xgboost_variant_runs_weighted` fails on `main` | `make run` S3 and layer 3's selection depend on a layer-2 run of the default profile; a profile whose layer 2 does not run leaves layer 3 nothing to select | Meanwhile: profile `summaries_8b` V0.1.0 (the default's steps with the 8B judge as layer 2, plus layer 3): `make layer2 PROFILE=summaries_8b`, then `make layer3 PROFILE=summaries_8b`. Closing it: the consolidation conversation and the layer-2 owner make `src/layer2` (or `make run` S3) run the scorer |

Detail of the engine-side limits, as written when the step was built:

1. **v3 is not measured on unseen rulings.** The summary owner ran it live on 4 tuning rulings (their `docs/V3.md`); the hold-out of `docs/agents/summarise.md` step 5 has not run. Nothing here says v3 beats v2. `verified` means "every check passed", not "a lawyer accepts it".
2. **The splitter is V0** (D-097): never primary, not measured against the HF considerations (D-070's criteria), `expected_count` NULL. A ruling without a reasoning heading or without numbered considerations gets a `failed` segmentation with no considerations: its version is stored, its claims uncited.
3. **Citations need a label with a number.** v3's evidence labels are `E.3.1`, `facts`, `text` or `reasons`; only numbered ones resolve. A number the segmentation lacks is left uncited, never cited wrongly.
4. **Confidence is not calibrated** (`v3/confidence.py`: weights 0.4 coverage, 0.3 kept, 0.2 entailment, 0.1 first pass, set by hand). It is in `summaries.jsonl`, not in the database, and decides nothing.
5. **A v2 fallback fiche has no claims and no checks** (nothing verified it sentence by sentence): its version is `flagged`, and the UI shows the body with an empty sentence list.
6. **Selection reads one layer-2 run** (D-096): the latest usable run of the profile. Run layer 2 on `2026Q2_union` before layer 3, or the top 10 comes from another population or from nothing. The ranking step (S4) does not exist, so "top 10" is layer 2's score, not a delivered list.
7. **A claim reads as the body, with one gap.** The engine applies `finish`'s per-sentence transforms to each kept sentence, so `rendered_text` is found in the stored body; v3's raw sentence is in its write or repair call's `raw_output` (the contract has no field for it). `finish.outcome_once` can still drop a model sentence that is nothing but the outcome: such a claim is `flagged` with `detail.not_in_body`. A model sentence over 300 characters has `model_text` cut at 300 with "…" and its full text in the entailment check's detail.
8. **The publication mark is not read.** `RulingSource.starred` exists, but the writer leaves it unset: `corpus.ruling.star` is empty for every ruling (no Neuheiten feed). So the closing note can say "Fünfer-Entscheid" when the bench says so, never that the ruling is marked for publication.
9. **Prompts are not registered** in `ops.prompt_version`, and `ops.llm_call_example` is not written (§5.2): the few-shot hygiene is proven by code (two fixed dockets, never summarised), not by rows. The hold-out of `docs/agents/summarise.md` step 5, when it runs, must leave those two dockets out; whether they fall in its test set is not checked.
10. **References in the text are the model's, checked, not rendered.** A consideration, article or number the model writes must exist in the ruling (`V3_NEW_IDENTIFIER`), and `finish` normalises statute abbreviations and drops references the ruling lacks; nothing renders them from canonical ids yet (D-037), and the six verifier checks of `docs/ARCHITECTURE.md` S7 are not built. Citations in `summ.claim_citation` do come from code (D-098).
11. **Italian rulings** get both fiches written from the Italian text; the summary owner reported the weakest fiche on the one Italian ruling they ran. No title carries a matter for an Italian ruling (code never translates it).
12. **`docs/SUMMARY_MEASUREMENT.md` and `docs/SUMMARY_V2.md`** still describe the removed trial script; their numbers are the probes', not layer 3's.

## 12. Assets

What exists, works and is measured, each with its source. Read with §11 (gaps): an asset is not a claim of quality on unseen rulings (G-1).

| # | Asset | Source |
|---|---|---|
| A-1 | **Summaries on the data layer, end to end.** 12 real rulings summarised live in German and French (3 by language, top 10 of `2026Q2_union`), 0 call errors, stored in `summ.*` and read by the API's `summ.v_summary_current` | §10; `results/layer3_live.json` |
| A-2 | **Every Apertus call traced.** One `ops.llm_call` per call or cache hit (313 for the two runs), exact messages in `ops.blob`, prompt tag, requested and served model, latency; each German and French text points to the call that wrote it (24 of 24) | `results/layer3_live.json`; trigger on `summ.summary_text` (`80_triggers.sql`) |
| A-3 | **Sentence-level evidence.** Each kept sentence is a `summ.summary_claim` with its section, its checks (`summ.verification_check`, rules `V3_*`) and, when the label resolves, its consideration (`summ.claim_citation`): 142 of 175 claims cited in the live runs | §6; `results/layer3_live.json` |
| A-4 | **The summary owner's v3 engine on `main`** (snapshot `a4a1504` + 3 fixes), with v2 fallback; DE and FR written independently from the ruling (D-014) | `src/summarize/engine.py`; §3 |
| A-5 | **Three engine fixes** made here and documented for upstream: `passages()` zip crash (the frontend developer made the same fix upstream), `as_data()` closing tags (G4), entailment premise refused over 8,000 characters instead of cut (G4) | `src/summarize/refine/evidence.py`, `entail.py:31`; G-6 |
| A-6 | **Code decides, Apertus reads** (thesis): title line, outcome sentence, consideration labels, splitter, 10 checks per sentence and the version's quality are code; Apertus picks propositions by sentence id (G1) and writes | §1; `src/layer3/render.py`, `segment.py` |
| A-7 | **Expert work is never overwritten**: a pipeline rerun stores its version without making it current while an expert edit is current; unchanged texts add no version | `src/layer3/store.py` (`keep_expert_current`, `skip_unchanged`); `tests/test_layer3_db.py` |
| A-8 | **The API's summary requests are processed**: `ops.user_request` of kind `summary` moves pending → accepted → done or failed, with the run and the version | `src/layer3/run.py`; `make layer3-requests` |
| A-9 | **Versioned and immutable**: `segment` V0.1.0, `summarise` V1.0.0, `verify` V1.0.0, preset `suva_house` V1.0.0, profile `default` V0.5.0 (D-064); the run records the engine's code hash | `src/layer3/registry/`; `src/db/seed/profiles.json` |
| A-10 | **Tests**: engine 34, ported v3/extract/refine tests, layer-3 unit tests, 9 layer-3 database tests on PostgreSQL 17; deliberate breaks turned them red | §10 |
| A-11 | **DDL fix for every summary writer**: `summ.before_insert_version()` runs as its owner, so the pipeline group can insert versions (function change, no reset) | `80_triggers.sql`; `docs/DDL_CHANGES.md` |
| A-12 | **Runs in the cluster with no compose change**: `make run` S6 in the `pipeline` job (D-090) | `src/cli.py`; `docs/DEPLOY.md` §10 |

## 13. Checks to run

| What | Command | Expected |
|---|---|---|
| Lint, unit, doctrine (G2, G3), models registry, D-051, registry references | `make check` | green |
| Layer 3 on PostgreSQL | `DATABASE_URL=… uv run --frozen pytest -m db tests/test_layer3_db.py` (it creates and drops its own database) | 8 passed |
| SQL tests | `make db-test` | all ok, `50_summ_test.sql` included |
| Structure | `make db-structure` | matches `expected/db/structure.json` |
| End to end | `SERVE=0 make run` | S6 prints `stored … verified … flagged`, or `SKIPPED` with its reason |
| A run's counts | `SELECT metric_code, value FROM ops.run_metric WHERE run_id = :run` | `stored + unchanged + failed + replay_misses = rulings_in` |
| What the API reads | `SELECT ruling_id, version_no, quality_status, mode, words_de, words_fr FROM summ.v_summary_current` | one row per summarised ruling, both languages |
| Every text tied to its call | `SELECT count(*) FROM summ.summary_text t JOIN summ.summary_version v USING (summary_version_id) WHERE v.creator_kind = 'pipeline' AND t.llm_call_id IS NULL` | 0 (the trigger refuses it) |
| No author line or staff code anywhere (D-051) | `uv run --frozen pytest tests/test_no_suva_personal_fields.py tests/test_engine.py` | green (the engine tests scan the 55 export bodies and every prompt sent with Suva's examples) |
