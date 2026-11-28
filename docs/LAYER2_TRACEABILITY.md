# LAYER2_TRACEABILITY: what can be traced for layer 2 today, and what we would have wanted

> **Status: state audit, 28 Nov 2026, 11:34 CET, on `main` @ `3edb722`.** No new code: this file records what exists and what is missing, for the presentation, the report and whoever continues. Readers: the teammate who prepares the pitch and the report, then anyone who audits layer 2. Measurements: `results/layer2_traceability.json` (the SQL queries are inside it). Layer 2 itself: `docs/LAYER2.md`. Decisions: D-074 to D-080 and D-085 in `docs/DECISIONS.md`.

## 1. In one minute

Layer 2 asks Apertus one question for every ruling that layer 1 kept: "Is this ruling relevant for Suva? Answer only Ja or Nein." The code reads the probability of "Ja" and stores it as a score. It never decides in or out: that is the ranking step, which is not built (section 6).

What you can say, each with its proof:

| Claim | Proof |
|---|---|
| Every ruling that layer 2 scored can be traced back to the exact question sent to Apertus, the model that answered, the raw answer, the code version and the layer-1 decision that let it through. | 912 of 912 scored rulings pass all 18 checks of section 3 (`results/layer2_traceability.json`, `label_coverage`) |
| The database refuses a score that is not tied to its own Apertus call. | trigger `t31_call` (DDL-1), tested in `tests/sql/32_layer2_test.sql` |
| The label shown for a ruling comes only from finished runs, along the ruling's current layer-1 decision. | view `triage.v_scope_pipeline` (DDL-2), same test file |
| Layer 2 reproduces the published benchmark exactly. | 3,936 of 3,936 prompts and 634 of 634 scores identical to D-074 (`results/layer2_validation.json`) |
| One query answers "why does this ruling have this score?". | `triage.v_scope_trace`, section 4 |

The project's thesis, "Apertus reads, the code verifies, the lawyer decides", holds for layer 2 in this sense: Apertus gives a probability, the code records and checks everything around it, and no ruling is excluded by Apertus.

## 2. The chain behind one score

```
ruling (docket, dates, text, HF snapshot 35b17aa9)
  └─ layer-1 assessment: kept, with its reason code and one ledger row per rule (D-081)
       └─ layer-2 assessment: score_raw (logit), score_0_100, German explanation, input fingerprint
            ├─ llm_judgement: P(Ja), P(Nein), the 20 most likely first tokens, characters sent, cut or not
            └─ llm_call: cache key, requested and served model, parameters, raw output, tokens, latency
                 ├─ prompt_version: the versioned prompt file, its SHA-256
                 └─ blob: the exact messages sent, by SHA-256
  run (all of the above): profile and step versions, code hash, git commit, mode LIVE or REPLAY,
       decision reference (D-076) and certified file (expected/layer2/V1.0.0.json) of the version,
       one span per ruling and per call, events, metrics; the same run also written as files in data/runs/<run_id>/
```

## 3. Measured on 28 Nov 2026

On the layer-2 session's working database (pinned HF file `35b17aa9`, layer 1 V1.1.0, layer 2 V1.0.0). Its runs replay the recorded answers of Apertus v1.5 8B.

**Coverage of the label: 912 rulings carry a layer-2 score.**

| Check | Rulings |
|---|---|
| judged (`ok`), with `score_raw` and a German explanation | 912 / 912 |
| input text and its fingerprint recorded; a span of its own | 912 / 912 |
| previous step is a layer-1 decision, and that decision has its rule ledger | 912 / 912 |
| step version names its decision and its certified file | 912 / 912 |
| a judgement row, tied to a call of the same run, ruling and step | 912 / 912 |
| call's prompt = judgement's prompt; prompt stored with its SHA-256 | 912 / 912 |
| exact messages present in `ops.blob` | 912 / 912 |
| raw output and cache key recorded | 912 / 912 |
| served model recorded and on the allow-list of `MODELS.md` | 912 / 912 |
| 20 most likely tokens stored | 912 / 912 |
| row in `triage.v_scope_trace` with its call | 912 / 912 |
| text cut (first 12,000 + last 2,000 characters), recorded per ruling | 407 / 912 |

**Per run** (5 layer-2 runs on this database): one call row and one call span per answer, one span per ruling, 0 calls without a span; a cache hit is a call row too. The partial run `f15cdec4…` records 552 rulings without a recorded answer as a metric (`replay_misses`) and an event (`layer2.replay.missing`); the list is in its files only.

## 4. How to show it live

On a database built by `make run` (section 6 of `technical_report.md`), for a Q2/2026 ruling scored by layer 2:

```sql
SELECT hop, step, in_suva_scope, score_0_100, p_yes, reason_code, served_model, cache_hit,
       component_version, profile_version, evaluated_rule_count, code_sha256, source_revision, explanation_de
FROM triage.v_scope_trace
WHERE ruling_id = (SELECT ruling_id FROM corpus.ruling WHERE docket = '8C_441/2025')
ORDER BY hop;
```

Two rows come back, about 0.15 s: hop 0 is layer 2 (score, model `apertus-v1-5-8b`, version V1.0.0, its explanation), hop 1 is layer 1 (kept by `L1_KEEP_RUBRIC`, 9 rules evaluated, its explanation). Both name the code hash and the HF revision. A Q2/2026 ruling is used on purpose: Suva's Q2 list is hidden, so the example reveals no Suva label.

## 5. What the database enforces (not just records)

| Guarantee | Where |
|---|---|
| A layer-2 judgement must point to its own call: same run, ruling and step, the call's prompt declared by the version, the call's models | trigger `t31_call` (`src/db/sql/80_triggers.sql`) |
| The label reads only `succeeded` or `partial` runs, never `failed`, `aborted`, `running` or `eval`, and only along the current layer-1 decision | view `triage.v_scope_pipeline` (`src/db/sql/60_views.sql`) |
| Every layer-1 decision has one ledger row per rule, sealed at commit | D-081, triggers `t30_check`, `t50_ledger` |
| A rule set used by an assessment cannot change; a changed behaviour needs a new version | D-082, D-064 |
| The pipeline writes under a restricted role, recorded in the audit log | D-082 point 6 |
| A run's files are written before its rows; the rows go in one transaction (all or nothing) | D-078, `src/layer2/run.py` |

## 6. What is not traceable today, and what we would have wanted

Not implemented, by lack of time. Effort figures are estimates.

| # | Gap | Effect | What we wanted | Effort (est.) |
|---|---|---|---|---|
| 1 | **No ranking step**: no threshold, no ranking, no `in_scope` (the three tables are empty) | the final "selected / not selected" has no trace; layer 2's score is consumed by nothing in this data layer | the ranking step on `score_raw`, its frozen F2 threshold and top 30 recorded per release (D-021, D-046, D-077) | 1 day |
| 2 | **The UI of PR #42 reads another data layer** (`public.predictions`, triage v2) | an expert in that UI does not see this trace; two pipelines, two separate traces | one source for the UI and the export; the decision is open with the lead | depends on the decision |
| 3 | **Explanation by template**: probability, model, version, cut | the "why" is a number, not legal reasons | the justification step (`triage.justification`, empty) with consideration references checked by code | 1 day |
| 4 | **Expert review loop unused**: `gold.expert_review` is empty | no expert correction traced yet | reviews written from the UI, shown next to the pipeline's label (`triage.v_scope_current`) | with the UI |
| 5 | **No per-run certification**: parity with the benchmark is a separate command (`make layer2-validate`) | a run does not prove by itself that it behaved as certified | each run compares itself with `expected/layer2/V1.0.0.json` and writes an event, as layer 1 does (D-082) | 2 h |
| 6 | **No `verify` for layer 2** (files = rows), unlike layer 1 | the files of a run are not checked against its rows | `python -m src.layer2 verify --run` | 2 h |
| 7 | **Replay misses only in files**: the 552 rulings are listed in `replay_misses.jsonl`, the database has the count | a database reader sees how many, not which | one row per missed ruling, without a score | 1 h plus a DDL change |
| 8 | **Live runs not in the working database**: it was rebuilt; the live Q2 run `8650bb32…` and the live slice `bf5163ef…` remain as files on one machine and as aggregates in `results/layer2_q2_2026.json` | the live evidence is not queryable | load a run from its files, or keep a dump (`ops` profile, D-090) | 2 h |
| 9 | **Every run is marked `git_dirty`**: an untracked file counts (`git status --porcelain`) | the flag says little; the code hash of the step still identifies the code | dirty = changes to tracked files of the run's code paths | 30 min |
| 10 | **Event times of runs written before PR #48 lie after the run's close** | a time-window query misses them | fixed on `main` @ `3edb722`; measured on the eval run `404d0225…`: 0 of 12 events outside its window | done |
| 11 | **CI cannot replay real answers** while D-031 is open | CI proves the code (stubbed client, SQL tests), not the scores | a committed replay cache, if D-031 allows it | after D-031 |
| 12 | **Decisions D-076 to D-080 and D-085 were PROPOSED** | the choices were written and argued, not confirmed | DECIDED by the lead on 28 Nov (gate G0) | done |
| 13 | **407 of 912 texts are cut** (first 12,000 + last 2,000 characters), recorded per ruling | the model did not read the middle of those rulings | a reduction by consideration (V1.1.0, `docs/LAYER2_IMPLEMENTATION_PLANNING.md` FC-2) | half a day plus a measurement |

## 7. What not to claim

- Not "Apertus decides relevance": layer 2 scores, nothing more; the decision belongs to the ranking step, which does not exist yet.
- Not "Apertus beats the rules": no zero-shot Apertus model beats the three-signal rule of the benchmark (D-074).
- Not "the experts see this trace in the UI": the UI of PR #42 reads another data layer (gap 2).
- Not "every ruling is read in full": 407 of 912 are cut (gap 13), and the cut is recorded.
- No number in the deck or the report without its file in `results/` (G11): the numbers above come from `results/layer2_traceability.json`, `results/layer2_validation.json` and `results/layer2_q2_2026.json`.

## 8. Sources

| Need | File |
|---|---|
| layer 2: what it does, commands, limits | `docs/LAYER2.md` |
| design and reasons | `docs/LAYER2_IMPLEMENTATION_PLANNING.md` §7, §26 |
| decisions | `docs/DECISIONS.md` D-074 to D-080, D-085 |
| tables, views and columns for the UI | `docs/DATA_CATALOG.md` |
| the measurements of this file, with their queries | `results/layer2_traceability.json` |
| certification against the benchmark | `expected/layer2/V1.0.0.json`, `results/layer2_validation.json` |
| live run on Q2/2026 | `results/layer2_q2_2026.json` |
