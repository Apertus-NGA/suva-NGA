# LAYER2: the Apertus relevance judge on the database

> **Status: V1 implemented, 28 Nov 2026 (branch `triage/layer2-db`).** Decisions D-075 to D-080 in `docs/DECISIONS.md`. Design and reasons: `docs/LAYER2_IMPLEMENTATION_PLANNING.md`. Audit: `tmp/audits/audit-layer2-classifier-2026-11-28.md` (git-ignored). Owner: the layer-2 owner (`docs/agents/finetune.md`).

## 1. What it does

Layer 2 is the pipeline step `layer2_judge`. For every ruling that layer 1 kept (`potentially`), Apertus answers "Ist dieses Urteil für die Suva relevant? Antworte nur mit Ja oder Nein." and the code reads the first token's log-probabilities:

- `score_raw` = ln P(Ja) − ln P(Nein), the logit: lossless, the key for any ranking (D-077);
- `score_0_100` = 100 × P(Ja) / (P(Ja) + P(Nein)), two decimals: what experts read (D-063);
- the label stays `potentially`: the in/out decision is the ranking step's frozen threshold (D-075).

Version V1.0.0 is the chain of the D-074 benchmark, byte for byte, judged by Apertus v1.5 8B (D-076). Its quality is therefore the 8B's in `results/finetune_benchmark_v3.md` (pooled AUC vs hard negatives 0.816, F2 at the transferred threshold 0.686): no zero-shot Apertus model beats the three-signal rule (D-074).

## 2. Files

| Path | What |
|---|---|
| `src/layer2/engine.py` | pure part: messages, neutraliser, cut, first-token reading, German explanation |
| `src/layer2/run.py` | the step: candidates, calls through `src/llm/`, files, one transaction |
| `src/layer2/validate.py` | certification against D-074 (messages and scores parity) |
| `src/layer2/models.py` | configuration, prompt file and judgement record (pydantic) |
| `src/db/llm_registry.py` | models from `MODELS.md`, prompt files, their bindings per step version (called by `python -m src.ingest registry`) |
| `src/layer2/registry/layer2_judge.json` | versions (config, judge model, prompt) |
| `prompts/layer2_judge/question.V1.0.0.json` | the prompt, versioned |
| `expected/layer2/V1.0.0.json` | certified behaviour (counts and digests, no label) |
| `results/layer2_validation.json` | aggregates of the last certification |
| `tests/test_layer2_engine.py`, `tests/test_layer2_db.py` (`-m db`) | unit, parity, end to end |

## 3. Commands

| Situation | Command |
|---|---|
| First run on a fresh database | `make db-up`, `make db-reset`, `make db-registry`, `make ingest-base PARQUET=…`, `make ingest-gold`, `make layer1`, then `make layer2` |
| Live, a slice first | `make layer2 MODE=live ARGS="--limit 3"`, then `ARGS="--all"`. Needs `LLM_API_KEY`, `LLM_BASE_URL` (the gateway of `docs/EVENT.md:56`), `LLM_NAME`, and `LLM_NAME_SMALL` = the 8B, in `.env.local` (git-ignored) or the environment. An exported variable wins over `.env.local`: never export a placeholder (a value without `https://` now stops the run at startup) |
| Live on Q2 only | `make layer2 MODE=live ARGS="--all --population 2026Q2_union"` |
| Replay from the benchmark's answers | `make layer2 ARGS="--store data/derived/layer2/replay_store --population 2025Q4_decision --population 2026Q1_decision"` (the store holds hard links to `data/derived/finetune/bench_v3/llm_store/cache`, so the benchmark's call log is never written) |
| Aggregates of a run for `results/` | `python -m src.layer2 report --run RUN_ID --out results/<file>.json` (no Suva label) |
| Certify a version | `make layer2-validate` (add `ARGS=--write-expected` only for a version that has no expected file) |
| In `make run` | stage S3, after layer 1; skipped with its reason without `DATABASE_URL`, without a succeeded layer-1 run, or in replay without a cache |
| A run ended `partial` | rerun the same command: answered calls come from the cache, failed ones are called again |
| A run ended `failed` | read `ops.pipeline_run.error_summary`, the run's warnings in `ops.log_event`, `data/runs/<run_id>/manifest.json`; fix; rerun |
| Gateway errors rise | stop; `make smoke-llm`; lower `LLM_CONCURRENCY`; never above the team ceiling (G2, D-030) |
| `model_override = true` | the environment did not name the 8B, so `LLM_NAME` judged: scores are not comparable with a threshold fitted on the 8B (D-064) |

## 4. What a run writes

Files (`data/runs/<run_id>/`, git-ignored): `layer2_judgements.jsonl` (one record per candidate), `llm_attempts.jsonl` (every attempt and cache hit), `messages.jsonl` (the exact messages by SHA-256), `manifest.json` (counts, hashes, version, profile, layer-1 run, declared and requested judge).

Database, in one transaction: `ops.span` (`layer2.run`, `layer2.judge` per ruling, `llm.call` per attempt), `ops.blob` (messages), `ops.llm_call` (per attempt: cache key, cache hit, mode, requested and served model, header, parameters, raw output, finish reason, HTTP status, error code, tokens, latency), `triage.assessment` (`potentially`, score, explanation, upstream layer-1 assessment, input text, fingerprint), `triage.llm_judgement` (log-probabilities, P(Ja), raw top 20, truncation, characters sent), `ops.log_event` (`layer2.prompt.built`, `layer2.score`, `llm.cache.hit`, `llm.retry`, `layer2.yesno.missing`, `layer2.run.summary`…), `ops.run_metric`.

Outcomes: `ok` (judged); `failed` with `L2_FAILED_CALL` (gateway, served model, replay miss) or `L2_FAIL_NO_YESNO_TOKEN` (the answer is kept as evidence); `skipped` with `ING_TEXT_MISSING` (no text, no call). All stay `potentially`, never a negative.

Why a ruling scored as it did: `SELECT * FROM triage.v_scope_trace WHERE ruling_id = …` (run, versions, served model, call, latency, tokens, cache flag, P(Ja), input text and its HF snapshot).

## 5. Measured on 28 Nov 2026 (local PostgreSQL 17, pinned HF file `35b17aa9…`)

| Item | Value | Source |
|---|---|---|
| Layer 1 under profile V0.3.0 | 935 of 6,055 kept; Suva's list 59/59, Q3 summaries 23/23, exports 55/55 | `python -m src.layer1 run`, `recall` |
| Candidates per population | 2025Q4 295, 2026Q1 339, 2026Q2 union 383 | SQL on the layer-1 run |
| Replay run on the two labelled quarters | 634 judged, 0 failed, 634 cache hits, 283 cut texts, 0 control tags | run `8fc08fc1…`, `ops.run_metric` |
| Messages parity on `suva-ft-v3` | 3,936 of 3,936 identical | `expected/layer2/V1.0.0.json` |
| Scores parity with the 8B's pass of D-074 | 634 of 634 identical, max difference 0.0 | same |
| Cut texts on `suva-ft-v3` | 1,683 of 3,936 | `results/layer2_validation.json` |
| Ties at two decimals (634 judged) | `score_0_100` 90 values (123 at 100.00, 277 at 0.00); `p_yes` 597; logit 634 | same |

| Live slice on 3 labelled rulings (run `eval`, de and fr) | identical to the 8B's pass of D-074 (max difference 0.0) | run `bf5163ef…` |
| **Live run on Q2 (`2026Q2_union`)** | **383 of 383 judged, 0 failed**, 380 live calls + 3 from the cache, 37 s at 4 concurrent calls, latency p50 378 ms / p95 528 ms, 1.21 M prompt tokens, served model = 8B on every call | run `8650bb32…`, `results/layer2_q2_2026.json` |
| Q2 by language | de 247, fr 126, it 10 | same |
| Q2 P(Ja) bands | ≥ 0.9: 130; 0.5–0.9: 11; 0.1–0.5: 15; 0.001–0.1: 57; < 0.001: 170 | same |
| Q2 ties | `score_0_100` 81 values (88 at 100.00, 133 at 0.00); `score_raw` 383 distinct | same |

## 6. Protections of a live run

- `LLM_BASE_URL` without `https://` or `http://` stops the run at startup (G3), before any run row.
- Preflight: in live mode the first candidate with a text is judged alone; if its call fails after the client's retries, the run stops at once (files written, run `failed`).
- Breaker: 5 failed calls in a row stop the run (not counted: an answer without Ja/Nein, a replay miss).
- A progress line on stderr every 10 s (`layer2: 216/383 done, 0 failed, 2 from cache, 20 s`).
- Ctrl-C closes the run as `aborted`, never left `running`.

## 7. Known limits

1. The 8B is the judge of V1.0.0; zero-shot Apertus does not beat a three-signal rule (D-074). Layer 2 alone must not decide in/out: ranking combines it with signals (D-021, D-022).
2. 1,683 of 3,936 texts (and most of Suva's listed rulings) are judged on the first 12,000 and last 2,000 characters: recorded per ruling, a candidate for V1.1.0 (`docs/LAYER2_IMPLEMENTATION_PLANNING.md` FC-2).
3. No delimiter around the ruling text: kept for parity with D-074; control-like tags are neutralised.
4. The label view `triage.v_scope_pipeline` still reads failed runs and older profile versions (plan DDL-2): no release from it before that DDL change.
5. No database check yet ties a judgement row to its call (plan DDL-1); the code and `tests/test_layer2_db.py` do.
6. Reloading a run's files writes its log events again: `ops.log_event`'s key holds the insertion time (shared helper `src/db/runs.py:events`, layer 1 alike).
7. Ranking on these scores needs raw-score columns (D-077).
