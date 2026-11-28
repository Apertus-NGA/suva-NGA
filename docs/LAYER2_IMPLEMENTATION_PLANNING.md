# LAYER2_IMPLEMENTATION_PLANNING: the Apertus relevance judge (layer 2) on the database

> **Status: v0.2 — V1 implemented, 28 Nov 2026, 06:23 CET (branch `triage/layer2-db`).** G0 answered by the lead: the six-schema DB; branch `review/final-cleanup` is never merged. Decisions recorded as D-075 (DECIDED) and D-076 to D-080 (PROPOSED, implemented on the lead's request) in `docs/DECISIONS.md`. Execution report: §26. Operations: `docs/LAYER2.md`.
> Owner: the layer-2 owner (`docs/agents/finetune.md`), with the triage brief's S3 duties (`docs/agents/triage.md` step 5). Shared files are changed only with the lead's approval (G7).
> Evidence: the read-only audit of 28 Nov (`tmp/audits/audit-layer2-classifier-2026-11-28.md`, git-ignored; aggregate scripts in `tmp/audits/layer2/`). Base: `origin/main` @ `e1bc7c2`. Numbers measured by us carry their command or file; none quotes a Suva label per docket (D-031).
> Method: the seven-phase feature method already used by `docs/DB_DDL_PLANNING.md` §1.4, plus the scope → analysis → plan → validation gate of the team's feature workflow. Work items are `L2-NN`, decisions `L2-Dnn` (mapped to D-lines in §21).
> Reading order: §0, §A, §3, §7 (decisions), §15 (work items), §16 (critical path), §17 (gates).

---

## 0. TL;DR

- **Layer 2 is a scorer, not a labeller.** It is the pipeline step `layer2_judge`: Apertus reads one ruling that layer 1 kept and returns how likely Suva finds it relevant. It writes a score and keeps the label `potentially` (D-063). The in/out decision is the ranking step's frozen threshold, outside this plan; this plan states what ranking needs from layer 2 (§12).
- **Nothing of it runs today.** `make run` prints `STUB run S3 judgement` (`src/cli.py:25, :107-115`); there is no `src/layer2/`, no registry entry, no prompt or model loader, and the `default` profile pins no `layer2_judge` version. The DB tables are ready (`src/db/sql/30_triage.sql:71-90`, `11_ops_execution.sql:139-172`). Audit score: **5.1/10** (§B).
- **V1.0.0 = the D-074 chain, byte for byte, with the 8B as judge.** Same system prompt and question, same 14,000-character cut, `max_tokens 1`, top 20 log-probabilities, score = P(Ja) / (P(Ja) + P(Nein)). It is the only chain measured under the frozen protocol, and the 8B is at least as good as the 70B on every primary metric where a difference can be resolved (`results/finetune_benchmark_v3.md`).
- **Parity is proved, not assumed:** the messages built from the database must be byte-identical to the frozen `suva-ft-v3` prompts, and replaying the benchmark's cache must give the 8B's scores exactly. Then the D-074 metrics apply to V1.0.0 without a new gateway call.
- **The score is stored without loss.** `score_raw` = the logit ln P(Ja) − ln P(Nein); `score_0_100` = 100 × P(Ja)/(P(Ja)+P(Nein)) rounded to 2 decimals, for display (D-063). Why: at 2 decimals the 8B's 3,867 distinct scores become 124 values and 45 of the 59 listed rulings tie at 100.00 (§B.3). Ranking must therefore order and threshold on `score_raw` (requirement R-1, a DDL change for the ranking step).
- **Every call is traceable:** one span per ruling, one child span and one `ops.llm_call` row per attempt (cache hits included), the exact messages in `ops.blob` by SHA-256, the prompt and model versions, requested and served model, log-probabilities, truncation, tokens, latency. Files first, then one transaction (D-061).
- **Failures are data, never negatives:** no text → `skipped`; failed call → `failed` (`L2_FAILED_CALL`); no Ja/Nein in the top 20 → `failed` (`L2_FAIL_NO_YESNO_TOKEN`). The next run retries them; answered calls come back from the cache.
- **Two blocking questions come first (gate G0):** which data layer the submission uses (main's six schemas, D-061, against the working schema of branch `review/final-cleanup`, which deletes them, `882dd88`), and which D-numbers are free (D-072..D-074 are reused on that branch).
- **Layer 1 is still changing** (branch `triage/layer1-traceability`, uncommitted): a rule ledger, `decision_ref` / `validation_ref` on versions, certified `expected/` files. Layer 2 is designed to fit them (§13): no rules in V1.0.0, a decision and an expected file per version. Half of the work can start before layer 1 merges (§16).
- **Cost and time:** about 400 Q2 candidates; the 8B answers about 11.6 calls/s at 4 concurrent calls (`docs/FINETUNE.md` §6), so a full live pass takes under 2 minutes. Building it: about 7 h for one agent, about 4.5 h wall time on two tracks (§16). Feature freeze: Sat 12:00.

---

## A. Scope understanding

### A.1 Variables detected in the request

| Variable | Value | Kind |
|---|---|---|
| Scope | layer 2: Apertus judging, from Suva's point of view, whether a ruling is in Suva's scope | explicit |
| Depth | "enterprise grade", "à la perfection": full audit with scores, then a plan that settles every choice | explicit |
| Target | the database (`src/db/sql/`, D-061) | explicit ("sur la DB du layer2") |
| Method | `docs/TEMPLATE_FEATURE_PLANNING.md` (a Gfaim document, never committed here) and the team's feature workflow | explicit |
| Autonomy | decide in the plan; the lead validates the plan before any code (validation gate) | explicit + workflow rule |
| Dependency | layer 1 is still being changed; the plan must hold when it lands | explicit |
| Next step | an audit of traceability and transparency of every decision | explicit → every decision in §7 carries alternatives, evidence, reason, reversal trigger |
| Time | Sat 28 Nov 05:00 CET; feature freeze 12:00; submission target 13:30 (`docs/EVENT.md:80-82`) | inferred |
| Branch | none yet; proposed `triage/layer2-db` (`AGENTS.md` §8: `<area>/<short-topic>`) | inferred |
| Test target | local PostgreSQL 17 (`make db-up`), CI `db` job; no HTTP API in scope, so no Postman collection | inferred |
| Who owns layer 2 | unassigned (D-024) | unknown, to confirm (L2-D16) |
| Which data layer is submitted | main's six schemas vs the branch's working schema | unknown, blocking (G0) |

### A.2 Objectives

1. A production step `layer2_judge` that `make run` calls (G6), scoring every layer-1 candidate of a population, live or from the replay cache (D-032).
2. Every judgement stored in the six-schema database with its full lineage (run, profile, version, prompt, model, call, input text, upstream layer-1 assessment).
3. Version V1.0.0 certified identical to the D-074 baseline, so its quality is known before it runs on Q2.
4. A documented interface to ranking (§12) that keeps D-021 open.

### A.3 Non-objectives

- The in/out decision, the threshold, the top-30 cut and the export (ranking and export steps; D-021, D-046).
- The justification step (key statement, cited considerations, party check: `triage.justification`).
- A better model or prompt: any change to scores goes through the D-074 decision rule (`docs/FINETUNE.md` §7). Candidates are listed in §19 with their triggers.
- UI and API.
- Porting the branch pipeline (`origin/triage/mvp-pipeline`): it stays a candidate (§19, FC-3).

### A.4 Assumptions (each checked or to check)

| # | Assumption | Status |
|---|---|---|
| H1 | The texts in `corpus.ruling_text` are the HF `full_text` of the pinned file, unmodified | checked: stored as read (`src/ingest/hf_base.py:106, :229`) |
| H2 | Keera returns `top_logprobs` on `/chat/completions` | checked on 45,156 calls (D-074); unknown on the judges' endpoint (Q-23) |
| H3 | `Ja` and `Nein` are single tokens and hold the probability mass | checked: Ja+Nein mass ≥ 0.998 on all 3,936 rulings, both models (`tmp/audits/layer2/agg_l2.py`) |
| H4 | The 8B served as "small" in the benchmark cache | checked: `data/derived/finetune/bench_v3/llm_store/replay_models.json` |
| H5 | Layer 1 writes `potentially` with a keep reason for every candidate | checked (`src/layer1/run.py:141-157`) |

### A.5 Risks

| Risk | Effect | Mitigation |
|---|---|---|
| The team submits the branch data layer (C-01) | this plan's DB part is void | gate G0 before any code |
| Layer-1 DDL changes conflict with layer-2 work | rebase cost | prep track touches no file layer 1 edits (§16) |
| Prompt parity fails on some rulings | V1.0.0 is not the measured chain | parity test lists every difference; no release until 100 % or each case explained |
| The judges set `LLM_NAME` to the 70B only | scores not comparable with an 8B threshold | override recorded, warning, requirement R-2 on ranking |
| 80 % of listed rulings are judged on a cut text | recall risk inherited from D-074 | recorded per ruling; disclosed in the report's Limitations; FC-2 |
| Time | freeze at 12:00 | P0/P1 split (§16) |

### A.6 Impacted components

New: `src/layer2/` (6 files), `src/layer2/registry/layer2_judge.json`, `prompts/layer2_judge/question.V1.0.0.json`, `tests/test_layer2_engine.py`, `tests/test_layer2_db.py`, `expected/layer2/V1.0.0.json`, `results/layer2_validation.json`.
Shared, additive changes (lead's approval, G7): `src/llm/client.py` (observer hook), `src/db/runs.py` (`resolved_models`, `model_override`), `src/db/registry.py` (prompt and model loaders), `src/ingest/__main__.py` (`REGISTRIES`), `src/db/seed/profiles.json` (`default` V0.3.0), `src/cli.py` (S3), `Makefile` (`layer2`), `MODELS.md` (judge row).
DDL (lead, plan mode, after the layer-1 merge): DDL-1, DDL-2 (§14); DDL-3 and DDL-4 belong to the ranking step.
Docs: `docs/DECISIONS.md`, `docs/STATE.md`, `docs/FINETUNE.md` (pointer), `docs/DB_DDL_PLANNING.md` §7.7 and §10.2, `docs/ARCHITECTURE.md` S3, a new operational `docs/LAYER2.md`.

### A.7 Conventions kept

Files first, then one transaction (D-061); versions immutable, MAJOR/MINOR/PATCH (D-064); deterministic `uuid5` ids and `ON CONFLICT DO NOTHING` (D-071, `src/layer1/run.py:127-129`); the gateway only through `src/llm/` (G2); no default for `LLM_*` (G3); input hygiene (G4); recall first and a reason for every non-judgement (G5); done = called by `make run`, tested on 3 real rulings, stored output checked (G6); tests red before green (G9); aggregates only for Suva-derived numbers (D-031); no D-051 value anywhere.

---

## B. Analysis of the existing system (summary of the audit)

### B.1 What exists

| Area | State | Proof |
|---|---|---|
| Measured chain | `experiments/finetune/scripts/06_benchmark_repeat.py` through `src/llm/`; prompt only in `04_build_dataset_v2.py:14-28` and in the git-ignored dataset | audit §3.1 |
| Measurement | D-074: frozen set `suva-ft-v3`, frozen metrics, paired CIs, 100 repetitions of the 70B | `results/finetune_benchmark_v3.md` |
| DB envelope | `triage.assessment`, `triage.llm_judgement`, `ops.llm_call`, `ops.blob`, `ops.prompt_version`, `ops.model`, comparability trigger, SQL tests | audit §3.3 |
| Gateway client | timeout, one classifier, retries, served-model check, cache and replay | `src/llm/client.py` |
| Production step | none | audit L2-F01 |
| Alternative | branch `triage/mvp-pipeline`: six readings + logistic regression, writes `public.predictions` | audit §3.6 |

### B.2 Scores

| Axis | Weight | Score |
|---|---|---|
| Implementation on main | 20 % | 1 |
| DB contract fitness | 15 % | 6 |
| Traceability, as implementable | 15 % | 5 |
| Model and scoring design | 15 % | 4 |
| Measurement quality | 10 % | 8 |
| Tests | 10 % | 5 |
| Governance and coherence | 10 % | 3 |
| Gateway client | 5 % | 7 |
| Security and confidentiality | 5 % | 8 |
| Operability | 5 % | 5 |
| **Weighted** | | **5.1 / 10** |

### B.3 Findings this plan answers

| Finding | Severity | Answered by |
|---|---|---|
| L2-F01 no production layer 2 | critical | L2-01..L2-08 |
| L2-F02 `numeric(5,2)` destroys the 8B ranking: measured on the 8B's pass of D-074 (3,936 rulings), 3,867 distinct scores become 124 values; 135 rulings tie at 100.00, including 45 of the 59 listed rulings and 61 hard negatives (`tmp/audits/layer2/agg_q.py`) | critical | L2-D05, R-1, DDL-3 |
| L2-F03 data-layer fork, D-number reuse | critical | G0, L2-D01 |
| L2-F04 label view ignores run status and profile version | high | DDL-2 |
| L2-F05 no prompt or model loader | high | L2-03 |
| L2-F06 client log cannot fill `ops.llm_call` | high | L2-04 (observer) |
| L2-F07 measured prompt: no delimiter, no neutralisation, cut: 1,682 of 3,936 rulings (42.7 %) and **47 of 59 listed rulings** are cut at 14,000 characters (`agg_l2.py`) | high | L2-D11, FC-2 |
| L2-F08 D-074 "after layer 1" used filter E, not layer 1 V1.1.0 | high | FC-8, U-2 |
| L2-F09 no DB check tying a judgement to its call | medium | DDL-1 |
| L2-F10 comparability blind to model override | medium | L2-D13, R-2, DDL-4 |
| L2-F11 LIVE/REPLAY only per call | medium | L2-D09 (per-call truth stored) |
| L2-F12 docs contradict D-074 (model, score form) | medium | L2-10 docs sync |
| L2-F13 experiments tests outside CI | medium | L2-D18 |
| L2-F14 prompt not versioned | medium | L2-D10 |
| L2-F15 no layer-2 explanation | medium | L2-D12 |
| L2-F16 no owner | medium | L2-D16 |

### B.4 Points challenged

- **"The 70B is the natural judge"** (`docs/ARCHITECTURE.md` S3, `MODELS.md:10`): an expectation written before D-074. The measurement says otherwise (L2-D04).
- **"Score = lp(Ja) − lp(Nein)"** (ARCHITECTURE) vs **"score = 100 × P(Ja)/(P(Ja)+P(Nein))"** (D-063): both are monotone in each other; the first is lossless, the second is what experts read. Both are kept, each for its use (L2-D05).
- **"Stages never write SQL; protocols and a file Tee"** (`docs/DB_DDL_PLANNING.md` §4): layer 1 writes SQL in its runner. Layer 2 follows layer 1 for consistency now; the protocols stay a further consideration (FC-9).
- **The branch pipeline's F2 0.772** beats D-074's 8B (0.686) on its authors' numbers, but its 40 % cut was chosen after seeing the results and the design was developed on the two test quarters (its `docs/TRIAGE_PIPELINE.md:88-96`). It enters only through the D-074 decision rule (FC-3).

---

## 1. Vision and architectural frame

Thesis of the project: **Apertus reads, the code verifies, the lawyer decides** (`docs/DOCTRINE.md` §1). Layer 2 is where Apertus reads for relevance. It sits between a code filter that must lose nothing (layer 1, recall 82/82, D-073) and a ranking that decides with a frozen threshold (D-063). Its job is to put every candidate on one ordered scale, with a trace a lawyer and an auditor can follow.

```text
corpus.ruling ─ ingest ─▶ layer1_filter ──▶ potentially ──▶ layer2_judge ──▶ potentially + score ──▶ justification ──▶ ranking ──▶ in_scope / out_of_scope
                               │                                │ failed/skipped ─▶ potentially, retried
                               └─▶ out_of_scope (reason)        └─ never judges a layer-1 drop in a non-eval run
```

**Future-proof check ("if we replace X by Y tomorrow"):**

| Change | What changes | What does not |
|---|---|---|
| 8B → 70B | new version V2.0.0 (MAJOR), new profile version; thresholds refitted | runner, tables, views |
| new prompt wording, delimiters, few-shot | new prompt version + `layer2_judge` V1.x (MINOR), re-measured | runner, tables |
| a LoRA adapter served elsewhere | new model row + MAJOR | everything else |
| several readings per ruling (FC-3) | MAJOR + DDL: `llm_judgement` 1:N | assessment envelope |
| Azure PostgreSQL (D-049) | connection string | all |

---

## 2. Business model: four entities never merged

| Entity | Table | Never merged with |
|---|---|---|
| **Judgement** (what Apertus said, with its evidence of reading) | `triage.assessment` (step `layer2_judge`) + `triage.llm_judgement` | the label (a view), the expert review (`gold.expert_review`) |
| **Call** (what was sent and received, each attempt) | `ops.llm_call` + `ops.blob` | the judgement (a judgement points to its successful call) |
| **Version** (how the judgement is made) | `ops.component_version` + `ops.prompt_version` + `ops.model` | the run (a run pins versions through its profile) |
| **Run** (when, by whom, with what resolved models) | `ops.pipeline_run` + `ops.span` + `ops.log_event` + `ops.run_metric` | the version |

Anti-pattern rejected: a `predictions` table carrying score, label, explanation and model in one row (the branch's `public.predictions`): it mixes the judgement, the label and the version, and loses the attempt history.

---

## 3. Capability separation

| Capability | Source of truth | Projection | Forbidden coupling |
|---|---|---|---|
| Judging a ruling | `triage.assessment` + `llm_judgement` | `v_scope_trace` | layer 2 writing `in_scope` / `out_of_scope` |
| The label | `triage.v_scope_pipeline` (furthest step of the default pipeline) | `v_scope_current`, export | any column holding the label |
| The prompt | `prompts/layer2_judge/*.json` (file) → `ops.prompt_version` | the messages in `ops.blob` | prompt text in Python code or in a dataset only |
| The model | `MODELS.md` → `ops.model` | `component_version_model`, `pipeline_run.resolved_models` | a model id typed in code or SQL |
| Answers | the client cache (`data/derived/llm/`) | `ops.llm_call` | treating a cache hit as a live answer |
| Quality | `results/finetune_benchmark_v3.json` (D-074) + `expected/layer2/<version>.json` | the report | quality numbers without a file |

---

## 4. Internal contract

```python
# src/layer2/engine.py — pure, no I/O, no network
def build_messages(docket: str, text: str, prompt: PromptV) -> tuple[list[dict], Prepared]: ...
    # Prepared: chars_total, chars_sent, truncation ("none" | "head12000_tail2000"), neutralised_count
def read_first_token(logprobs: dict | None, tokens: AnswerTokens) -> Reading: ...
    # Reading: p_yes, p_ja, p_nein, mass, logprob_yes, logprob_no, logit, top20_floor, top20 (raw), yes_no_in_top
def explanation_de(reading: Reading | None, outcome: str, ctx: ExplainCtx) -> str: ...

# src/layer2/run.py — the step
def run_layer2(conn, *, profile="default", population=None, mode="replay"|"live",
               limit=None, store=DEFAULT_STORE, repetition=0, kind="layer2") -> dict: ...

# src/llm/client.py — additive (PATCH): an observer sees every attempt and every cache hit
LLMClient(cfg, store_dir, observer: Callable[[CallAttempt], None] | None = None)
```

`Layer2JudgementRecord` (pydantic, `src/layer2/models.py`, layer-1 precedent `Layer1DecisionRecord`): run, ruling, docket, decision date, upstream assessment, input text id and SHA-256, input fingerprint, outcome, reason code, reading fields, score raw and 0-100, explanation, messages SHA-256, prompt version, requested/served model, attempts, cache hit, latency, tokens. `src/schemas.py` (frozen) is not changed.

---

## 5. API boundary

No HTTP route in this plan. Reads that the API will use already exist: `GET /api/rulings/{docket}/trace` reads `triage.v_scope_trace`, which shows the layer-2 row (served model, latency, tokens, cache hit, `p_yes`) (`src/db/sql/60_views.sql:123-162`). Not in any API: writing a judgement, re-running a judgement from the UI (it goes through `ops.request_work()` for "add another judgement", D-015).

---

## 6. The step in detail

### 6.1 Candidates
The `potentially` assessments of the **latest succeeded layer-1 run that used the `layer1_filter` version the same profile version pins** (same filter, same candidates; changed at implementation from "of the same profile version", so a new profile version that keeps layer 1 does not force a layer-1 rerun), optionally limited to one or more populations (`corpus.population.code`). Each layer-2 assessment carries `upstream_assessment_id` = that layer-1 assessment. No succeeded layer-1 run → the step stops: "run layer 1 first" (G6: 0 input fails).

### 6.2 Messages (V1.0.0 = D-074, byte for byte)
- system = the D-074 system prompt (`experiments/finetune/scripts/04_build_dataset_v2.py:14-22`), copied verbatim into `prompts/layer2_judge/question.V1.0.0.json`;
- user = `Urteil <docket>:\n\n<text>\n\n<question>` with the question of `:23`;
- text = the full text if ≤ 14,000 characters, else the first 12,000 + `\n[…]\n` + the last 2,000 (`:27-28`);
- then the neutraliser: control-like tags (`<|…|>` of at most 40 characters) become `‹|…|›`; identity on every text without them; the count per ruling is stored (L2-D11).

### 6.3 Call
`client.chat(messages, size=<resolved>, prompt_version="suva-ft-v3/zero-shot-ja-nein", max_tokens=1, logprobs=True, top_logprobs=20, first_token_only=True, repetition=<n>)`. The `prompt_version` string is part of the cache key (`src/llm/client.py:165-176`): keeping D-074's string makes the benchmark's answers reusable and proves parity. The registry row is still `layer2_judge.question` V1.0.0; the string is a field of its configuration (`cache_namespace`).

### 6.4 Reading and score
P(Ja) = sum of exp(logprob) of the top-20 tokens in {`ja`, `j`}; P(Nein) over {`nein`, `nei`, `ne`}, case and spaces ignored (`06_benchmark_repeat.py:45, :53-79`). `p_yes` = P(Ja)/(P(Ja)+P(Nein)); `logit` = ln P(Ja) − ln P(Nein); if one side is absent, its log-probability is bounded by the top-20 floor and flagged (`yes_no_in_top = false`; never seen in D-074). Stored: `assessment.score_raw = logit`, `score_0_100 = round(100 × p_yes, 2)`, `score_source = 'judged'`; `llm_judgement`: `logprob_yes`, `logprob_no`, `p_yes`, raw top 20, `yes_no_in_top`, chars total and sent, truncation, input tokens.

### 6.5 Outcomes

| Case | outcome | score_source | reason_code | llm_judgement | Call row |
|---|---|---|---|---|---|
| judged | `ok` | `judged` | NULL | yes | yes |
| no text | `skipped` | NULL | `ING_TEXT_MISSING` | no | no (no call, G4) |
| input refused (over budget, placeholder) | `skipped` | NULL | `L2_FAILED_CALL` + event `layer2.input.rejected` | no | no |
| gateway failure after retries, served model rejected, replay miss | `failed` | `failed` | `L2_FAILED_CALL` | no | one row per attempt (none for a replay miss) |
| no Ja/Nein in the top 20 | `failed` | `failed` | `L2_FAIL_NO_YESNO_TOKEN` | no | yes (`parsed_ok = false`) |

Every row stays `potentially` (`30_triage.sql:41, :43`). The run is `succeeded` with no failure, `partial` when failed + skipped ≤ `max_failed_share` (configuration, 0.02), `failed` above: then the files are written, the DB gets only the failed run row (`fail_run`), and nothing reaches the label.

### 6.6 Explanation (German, by code)
Judged: "Apertus-Einschätzung (Modell `<served>`, Version V1.0.0): Wahrscheinlichkeit «Ja» = 97,3 %. Entscheid über die Relevanz erst in der Rangierung." plus "Text gekürzt: 14 000 von 31 245 Zeichen gelesen." when cut. Failed or skipped: the German label of the reason code (`95_seed_reference.sql:31-32`). No model-written sentence at this step (L2-D12).

### 6.7 Persistence (files first, then one transaction)
1. `data/runs/<run_id>/layer2_judgements.jsonl` (one record per candidate), `llm_attempts.jsonl` (one per attempt or cache hit), `manifest.json` (counts, SHA-256 of both files, version, profile, resolved models, mode, store path label).
2. One transaction: per ruling a span `layer2.judge` (parent = root span) and per attempt a child span `llm.call`; `ops.blob` (messages JSON, `ON CONFLICT DO NOTHING`); `ops.llm_call`; `triage.assessment`; `triage.llm_judgement`; events; metrics; `finish_run` with `succeeded` or `partial`.
3. Ids: `uuid5(span|run|ruling|layer2_judge)`, `uuid5(assessment|run|ruling|layer2_judge|rep)`, `uuid5(llm_call|run|ruling|rep|attempt)`, `uuid5(span|llm|run|ruling|rep|attempt)`: reloading the same run is a no-op.

### 6.8 Events and metrics
Events: `layer2.run.started`, `layer2.model.resolved` (declared, requested, override), `layer2.prompt.built` (chars, estimated tokens, truncation, neutralised count; no text), `layer2.score` (debug), `layer2.yesno.missing` (warning), `llm.retry` (warning), `llm.cache.hit` (debug), `layer2.run.summary`. Metrics: `rulings_in`, `judged`, `failed`, `skipped`, `llm_attempts`, `llm_errors`, `cache_hits`, `live_calls`, `tokens_in`, `latency_p50_ms`, `latency_p95_ms`, `truncated`, `model_override`. A step with 0 judged fails the run (G6).

### 6.9 Models
Declared: judge = `apertus-v1-5-8b` (`component_version_model`). Resolution at run start: the size whose configured name has the same canonical id (`src/llm/served_model.py` `canonical`), `small` first (D-074 ran the 8B as small, H4), then `large`. If neither matches: use `LLM_NAME` (large), set `pipeline_run.resolved_models = {"judge": <id>}` and `model_override = true`, emit a warning event. Every call checks the served model (G3).

---

## 7. Decisions (each one: alternatives, evidence, reason, what reverses it)

| Id | Decision | Alternatives rejected | Evidence | Why | Reversed by |
|---|---|---|---|---|---|
| **L2-D01** | Layer 2 writes to main's six-schema DB (D-061). | the branch working schema (`public.predictions`, `review/final-cleanup`) | D-061 DECIDED on main; layer 1 writes there (PR #39); the fork deletes it (`882dd88`), "lead to confirm" | one envelope, one lineage, one label view; layer 1 already lives there | the lead keeps the branch schema for the submission (G0) |
| **L2-D02** | Layer 2 = step `layer2_judge`: a score, label `potentially`; the boundary is ranking's. | layer 2 labels with a fixed cut (0.5, 40 %) | D-063 DECIDED; DDL CHECK `30_triage.sql:43` | thresholds on uncalibrated scores are meaningless (`docs/FINETUNE.md` §3, B2); the threshold must be frozen on another quarter | a new D-line replacing D-063 |
| **L2-D03** | V1.0.0 = the D-074 chain, byte-identical (prompt, cut, parameters, token sets, score). | a new prompt; the six readings of the branch; few-shot | D-074 DECIDED: the reference of every layer-2 change, same chain | only measured chain; parity makes its quality known before Q2 | any candidate passing the D-074 decision rule (`docs/FINETUNE.md` §7) |
| **L2-D04** | Judge model of V1.0.0 = Apertus v1.5 **8B**; 70B = V2.0.0 (MAJOR) in profile `layer2_70b`, off by default. | 70B as default (ARCHITECTURE S3, `MODELS.md:10`) | AUC vs hard 0.816 vs 0.822, difference includes 0; F2 transferred after layer 1 0.686 vs 0.588; top-45 F2 70B − 8B = −0.153 [−0.230, −0.031], top-45 recall −0.169 [−0.254, −0.034]; 70B per-ruling spread up to 0.342 over 100 repetitions (`results/finetune_benchmark_v3.md`, `docs/FINETUNE.md` §6) | at least as good where resolvable, better on the top lists that D-046 grades, more repeatable, ~3× the throughput. D-022's "the 8B never excludes alone" holds: layer 2 excludes nothing (R-3) | a frozen-protocol measurement where the 70B beats the 8B, or judges who serve only the 70B (then FC-1) |
| **L2-D05** | `score_raw` = logit; `score_0_100` = round(100 p_yes, 2), display only; ranking orders and thresholds on `score_raw` (R-1, DDL-3). | `score_0_100` as the ranking key; changing D-063's definition | quantisation measured: 3,867 → 124 values, 45/59 listed rulings tie at 100.00 (B.3) | keeps D-063 for people, keeps the information for machines | DDL makes `score_0_100` double precision (then R-1 is met by it) |
| **L2-D06** | Candidates = `potentially` of the latest succeeded layer-1 run of the same profile version; a layer-1 drop is judged only in a run of kind `eval`. | judging every ruling; the 10 % safety net in normal runs (`docs/TIPS_LAYER1_FILTER_HANDOFF.md` §8, L1-Q3) | `v_scope_pipeline` takes the furthest step (`60_views.sql:62-96`), so a judged drop would turn `potentially` | protects the label and G5's reason code of every drop | DDL-2 lineage rule lands and the team wants the safety net in normal runs |
| **L2-D07** | Files first, then one transaction; resume = rerun (cache); statuses `succeeded` / `partial` / `failed`. | per-batch commits with `ops.work_item` | D-061; layer-1 pattern `src/layer1/run.py:296-336`; run cost < 2 min live | no partial label state; cache already makes reruns free | runs long enough to need checkpoints (> 30 min live), then FC-6 |
| **L2-D08** | Failures and skips stay `potentially` with a reason; never a negative; retried next run. | dropping failures; treating them as "no" | D-063, G5, D-021 point 7 | recall first | never |
| **L2-D09** | One `ops.llm_call` row per attempt and per cache hit; messages in `ops.blob`; child span per attempt; additive observer hook in the client. | parse `llm_calls.jsonl`; record only the final answer | the client log has no run/span/ruling and skips cache hits (`client.py:177-179, :339-356`) | the next audit must see every attempt; the hook changes no behaviour or cache key | — |
| **L2-D10** | Prompts are versioned JSON files in `prompts/layer2_judge/`, loaded into `ops.prompt_version`; models loaded from `MODELS.md` into `ops.model`; V1.0.0's client prompt string = `suva-ft-v3/zero-shot-ja-nein`. | prompt in Python; a new client string | `AGENTS.md` §4 (`prompts/` at the root); `ops.prompt_version` (`10_ops_registry.sql:66-90`); no loader today (L2-F05) | one home per prompt, hashed; cache parity with D-074 | — |
| **L2-D11** | G4 in V1.0.0: neutraliser added (identity on the measured texts, count stored); no delimiter and the head/tail cut kept, both recorded per ruling and disclosed. | delimiters now; consideration-aware reduction now | parity requires D-074's messages; 47/59 listed rulings are cut (B.3) | changing the text changes the scores: that is V1.1.0 with a measurement (FC-2) | FC-2 passes the D-074 rule, or a control tag is found in a candidate |
| **L2-D12** | Layer-2 explanation written by code (probability, model, version, cut); no model text. | a JSON justification in the same call | doctrine §4 (no self-declared confidence); the justification step owns the key statement (`triage.justification`) | G5 for every judged ruling without hallucination risk | — |
| **L2-D13** | Declared judge vs environment: resolve by canonical id, `small` first; otherwise use `LLM_NAME`, record `model_override`, warn. | refusing to run; silently using whatever is set | D-064 ("an override warns, never blocks"); D-032 | judges' run must complete | — |
| **L2-D14** | Each layer-2 version carries `decision_ref` and `validation_ref` (`expected/layer2/<version>.json`: parity digests and counts, no label). | no certification file | layer-1 F-12 pattern (worktree `10_ops_registry.sql` diff) | the follow-up audit can tie every version to its decision and its proof | — |
| **L2-D15** | Code in `src/layer2/` (models, engine, run, validate, CLI, registry); `src/schemas.py` unchanged; `experiments/` never imported. | code in `src/triage/`; importing `experiments/finetune` | layer-1 layout; `AGENTS.md` §4 ("never imported") | parallel to layer 1; the benchmark stays an experiment | — |
| **L2-D16** | The layer-2 owner owns the step; the lead approves every shared file. | the triage owner | D-024 open; two briefs touch layer 2 (C-11) | one owner for the score from benchmark to production | D-024 |
| **L2-D17** | V1.0.0 has no rules (`rules: []`); failure reasons are reason codes; signals are columns. | `L2_*` as `check` or `signal` rules | layer-1 ledger applies to any version with enabled non-`check` rules (worktree `check_assessment_ledger`) | no ledger rows to maintain, no conflict with layer 1's work | a layer-2 signal that needs evidence offsets |
| **L2-D18** | Layer-2 tests live in `tests/` (CI); data-dependent tests skip without `data/derived/`, like `test_metrics.py`. | tests in `experiments/` | `pyproject.toml:32` (`testpaths = ["tests"]`) | CI must guard the production step | — |

---

## 8. Data flow (one run)

```text
profile default V0.3.0 ─▶ layer2_judge V1.0.0 (config, prompt V1.0.0, model judge = 8B)
latest succeeded layer-1 run (same profile version) ─▶ candidates (potentially) ─┐
corpus.ruling_text (primary) ────────────────────────────────────────────────────┤
                                                                                 ▼
               build_messages ─▶ neutralise ─▶ client.chat (cache | live, observer) ─▶ read_first_token ─▶ explanation
                                                                                 ▼
             data/runs/<run_id>/{layer2_judgements.jsonl, llm_attempts.jsonl, manifest.json}
                                                                                 ▼ one transaction
   ops.span (judge + llm.call) · ops.blob · ops.llm_call · triage.assessment · triage.llm_judgement · ops.log_event · ops.run_metric
                                                                                 ▼
                         triage.v_scope_pipeline (label potentially + score) · triage.v_scope_trace (why)
```

| Step | Input guaranteed | Output guaranteed | Failure |
|---|---|---|---|
| select | succeeded layer-1 run of the same profile version | ≥ 1 candidate | stop, run `failed` |
| build | text present | messages + chars + truncation | `skipped` |
| call | messages under budget | served model allowed, uncut | `failed` after retries |
| read | top-20 log-probabilities | p_yes, logit | `failed` (`L2_FAIL_NO_YESNO_TOKEN`) |
| files | records | 3 files + SHA-256 | exception, run `failed` |
| load | files | all rows or none | rollback, `fail_run` |

---

## 9. The scope label after layer 2

Unchanged from D-063: `v_scope_pipeline` shows `potentially` with the layer-2 score for a judged ruling, `potentially` with the reason for a failed or skipped one, `out_of_scope` with the layer-1 reason for a drop. Until DDL-2 lands, the view also reads failed runs and older profile versions (L2-F04): no release may be made from it before DDL-2 (gate G-H).

---

## 10. Traceability: what the follow-up audit can check

For any judged ruling, from the database alone: the run (git commit, dirty flag, mode, actor, parameters hash), the profile version and its decision, the component version (config hash, code hash, decision, validation file), the prompt version (template hash), the declared and resolved models, every attempt (status, error class, latency, tokens, cache flag, served model and header), the exact messages (blob, hash equal to the client's `messages_sha256`), the log-probabilities and the score, the input text (hash, HF snapshot), the upstream layer-1 assessment and its reasons. From the files alone: the same, in `data/runs/<run_id>/`, plus the manifest's hashes. Checks: §17 gate G-E.

---

## 11. Observability

Health: `ops.v_run_health` per run and step (a step at 0 is red). Timeline: `ops.v_ruling_timeline`. Cost: `tokens_in`, `live_calls`, `cache_hits`. Alarms during a long live run: failure share above `max_failed_share` stops the run (§6.5). Redaction: no key, no prompt, no D-051 value, no person's name in events (`docs/DB_DDL_PLANNING.md` §11.5); prompts only in `ops.blob`.

---

## 12. Interface with ranking (requirements, not built here)

| Id | Requirement | Why | Where |
|---|---|---|---|
| R-1 | Order and threshold on `score_raw` (logit), not on `score_0_100` | L2-F02 | DDL-3 |
| R-2 | Refuse a layer-2 score whose served model differs from the model the threshold was fitted on | L2-F10, D-064 | DDL-4 |
| R-3 | The in/out boundary does not rest on the 8B score alone while D-022 says so: the ranking score combines signals and layer 2, per D-021 | D-022, `docs/agents/triage.md` rules | ranking design (D-021) |
| R-4 | A `failed` or `skipped` layer-2 ruling gets a `signals_only` score at ranking, never "no" | D-021 point 7, G5 | ranking design |
| R-5 | "After layer 1" thresholds are fitted with production layer 1 (V1.1.0), not filter E | L2-F08 | FC-8 |

---

## 13. Dependencies on layer 1 (in progress)

| Layer-1 change (worktree, uncommitted) | Effect on layer 2 | Plan |
|---|---|---|
| Rule ledger for any version with enabled non-`check` rules | none if layer 2 has no rules | L2-D17 |
| `decision_ref` / `validation_ref` on component and profile versions | layer-2 registry must fill them | L2-D14; the loader writes them once the columns exist, NULL before |
| `expected/<step>/<version>.json` certified files | layer 2 writes `expected/layer2/V1.0.0.json` | L2-07 |
| Ingest exclusions and closure | none | — |
| Upstream contract: `potentially` + keep reason | consumed | §6.1 |

Rule: the **prep track** (§16) touches only new files and files layer 1 does not edit (`src/llm/client.py`, `src/db/registry.py`, `src/ingest/__main__.py`, `prompts/`). Everything that needs the final DDL waits for the layer-1 merge; if that merge is not in by 08:30 CET, layer 2 proceeds on main's current DDL (the new columns are nullable) and rebases after.

---

## 14. DDL changes (owner: lead, plan mode, after the layer-1 merge)

| Id | Change | Blocking for | File |
|---|---|---|---|
| DDL-1 | Trigger on `triage.llm_judgement`: its call has the assessment's run and ruling, step `layer2_judge`; its prompt version is one the component version declares; `requested_model` equals the call's | release (G-H), not the first run | `80_triggers.sql` |
| DDL-2 | `v_scope_pipeline`: only runs `succeeded` or `partial`; a downstream assessment counts only if its upstream chain reaches the ruling's latest layer-1 assessment of the current default profile version | any release | `60_views.sql` |
| DDL-3 | `triage.threshold.value_raw double precision`, `triage.ranking_entry.final_score_raw double precision`; the ranking trigger compares raw values | ranking on V1.0.0 scores | `30_triage.sql`, `80_triggers.sql` |
| DDL-4 | Ranking trigger compares the served model of the layer-2 judgement with the threshold's scorer model | ranking under an override | `80_triggers.sql` |

Each with SQL tests red on the old DDL (G9), `make db-reset && make db-deploy && make db-test` green twice.

---

## 15. Work items

| Id | What | Deliverables | Acceptance | Depends on | Track | Est. |
|---|---|---|---|---|---|---|
| **L2-00** | Gate G0: the lead confirms L2-D01 and reserves the D-numbers | answer at the sync | written in `docs/DECISIONS.md` | — | lead | 15 min |
| **L2-01** | Prompt file and configuration | `prompts/layer2_judge/question.V1.0.0.json`; `src/layer2/models.py` (`Layer2Config`, `Layer2JudgementRecord`, `PromptV`, `AnswerTokens`) | prompt hash recorded; config validates | — | prep A | 30 min |
| **L2-02** | Engine (pure) | `src/layer2/engine.py`; `tests/test_layer2_engine.py` | message parity on 3 real rulings (de, fr, it) from `suva-ft-v3` (skip without data); reading identical to `read_first_token` on stored top-20s; mutants (wrong cut, missing `j`) go red | L2-01 | prep A | 1 h |
| **L2-03** | Prompt and model loaders; registry entry; profile | `load_prompts`, `load_models` in `src/db/registry.py`; `src/layer2/registry/layer2_judge.json` (V1.0.0, `rules: []`); `REGISTRIES` entry; `default` V0.3.0 pins `layer2_judge` V1.0.0 | `make db-registry` twice on a fresh DB, no error, same rows | L2-01 | prep B | 1 h |
| **L2-04** | Client observer and run model resolution | `observer` in `src/llm/client.py`; `resolved_models`, `model_override` in `src/db/runs.py:begin_run` | the 21 client tests stay green; new tests: one event per attempt, one per cache hit, cache keys unchanged | — | prep B | 45 min |
| **L2-05** | Runner and DB load | `src/layer2/run.py`, `src/layer2/__main__.py` (`run`, `validate`) | §6 behaviour; reload of the same run is a no-op | L2-02..04, layer-1 merge or 08:30 | main | 1 h 30 |
| **L2-06** | Wiring | `make layer2`; `make run` S3 calls it when `DATABASE_URL` and a succeeded layer-1 run exist, else prints SKIPPED with the reason | `SERVE=0 make run` green in CI (stage skipped there) | L2-05 | main | 20 min |
| **L2-07** | Validation and certification | `src/layer2/validate.py`; `expected/layer2/V1.0.0.json`; `results/layer2_validation.json` (aggregates: parity counts, truncation, quantisation, cost) | messages parity 100 % on the `suva-ft-v3` rulings in the DB (or every difference listed); replayed 8B scores equal to `rep000` exactly | L2-05 | main | 45 min |
| **L2-08** | DB end-to-end tests | `tests/test_layer2_db.py` (`-m db`, declared mock gateway) | 3 rulings: every table filled, triggers green, failure and skip cases, `partial` status, reload no-op, no key or prompt in events | L2-05 | main | 1 h |
| **L2-09** | Live slice, then Q2 | 3 rulings live (de, fr, it); then the Q2 candidates live | live scores within the 8B's measured spread (≤ 0.086) of `rep000` where comparable; Q2 run `succeeded`, metrics non-zero | L2-07 | main | 20 min |
| **L2-10** | Docs sync | D-lines (§21); `docs/STATE.md`; new `docs/LAYER2.md` (operations, runbook §18); `docs/FINETUNE.md` pointer; `MODELS.md` judge row; `docs/DB_DDL_PLANNING.md` §7.7, §10.2; `docs/ARCHITECTURE.md` S3 | §17 G-G | L2-07 | docs | 45 min |
| **L2-11** | DDL-1, DDL-2 | §14 | SQL tests red then green | layer-1 merge | lead | 1 h |
| **L2-12** | Report lines | `technical_report.md` §3 (use of Apertus) and §5 (limits: cut text, 8B choice, no in/out at layer 2), numbers through `make claims` | G11 | L2-07 | pitch | 20 min |

---

## 16. Critical path and time (*estimates*)

```text
05:45  L2-00 gate G0 (lead) ─────────────────────────────────────────────┐
06:00  prep A: L2-01 ─▶ L2-02            prep B: L2-04 ─▶ L2-03          │ (no file layer 1 edits)
07:30  ─────────────── both done ───────────────                          │
07:30-08:30  wait for layer-1 merge (or proceed at 08:30 on current DDL)  │
08:30  L2-05 ─▶ L2-06 ─▶ L2-07 ─▶ L2-09        in parallel: L2-08, L2-11 (lead)
10:45  L2-10, L2-12 ─▶ PR review ─▶ merge
11:30  margin before the 12:00 feature freeze
```

- **One agent:** about 7 h of work. **Two tracks** (allowed: at most 3 sub-agents, `AGENTS.md` G8): about 4.5 h wall time.
- **P0 for the freeze:** L2-00 to L2-09 (a working, traced step on Q2). **P1 if time runs out:** L2-11 (but then no release from the view, G-H), L2-12 after the freeze in the report only.
- Gateway budget: Q2 candidates about 400 calls with the 8B (*estimate* from the branch's 416 kept in Q2, agent inventory), under 2 minutes at 4 concurrent calls; the labelled quarters replay from the benchmark cache (0 calls).

---

## 17. Production-readiness gates

| Gate | Criterion | Proof | Owner |
|---|---|---|---|
| G0 | Data layer and D-numbers confirmed | `docs/DECISIONS.md` line | lead |
| G-A Foundation | DDL deployed twice; a succeeded layer-1 run on the target DB | `make db-reset && make db-deploy && make db-test`; `ops.pipeline_run` row | platform |
| G-B Registry | V1.0.0, prompt, model loaded; reload is a no-op | `make db-registry` ×2 | layer-2 owner |
| G-C Parity | messages 100 % identical to `suva-ft-v3`; replayed scores equal `rep000` | `expected/layer2/V1.0.0.json`, `results/layer2_validation.json` | layer-2 owner |
| G-D End to end | 3 real rulings (de, fr, it) live; every table filled; triggers green | `pytest -m db tests/test_layer2_db.py`; SQL counts | layer-2 owner |
| G-E Traceability | for every judged ruling: `v_scope_trace` row with version, served model, call, latency, tokens, cache flag; `count(llm_call) = attempts`; every `messages_sha256` in `ops.blob` | SQL checks in L2-08 | layer-2 owner |
| G-F Operations | `make layer2` documented; metrics non-zero; failure share ≤ 2 %; cost recorded | `ops.v_run_health`; `docs/LAYER2.md` | layer-2 owner |
| G-G Docs | D-lines, STATE, MODELS, FINETUNE, DDL plan, ARCHITECTURE aligned; no contradiction left from audit §7 | grep of the D-numbers; review | lead |
| G-H Release | DDL-1 and DDL-2 deployed before any release built on the label view | SQL tests | lead |
| G-I Confidentiality | no key, prompt or D-051 value in events; no Suva label per docket in committed files | `make check` (T31), review of `expected/` and `results/` | all |

---

## 18. Runbook (goes to `docs/LAYER2.md`)

| Situation | Command or action |
|---|---|
| First run on a fresh DB | `make db-up`, `make db-reset`, `make db-registry`, `make ingest-base PARQUET=…`, `make layer1`, `MODE=live make layer2 ARGS="--limit 3"`, then `--all` |
| Replay from the benchmark cache | `make layer2 MODE=replay ARGS="--store data/derived/finetune/bench_v3/llm_store --population 2026Q1_decision"` |
| A run ended `partial` | rerun the same command: answered calls come from the cache, failed ones are called again |
| A run ended `failed` | read `ops.pipeline_run.error_summary`, `ops.log_event` of the run (warning and above), `data/runs/<run_id>/manifest.json`; fix; rerun |
| Gateway errors rise | stop; check `make smoke-llm`; lower `LLM_CONCURRENCY`; never above the team ceiling (G2, D-030) |
| `model_override = true` | expected when judges set another model; scores are not comparable with a threshold of another model (R-2) |
| Diagnostic queries | latest runs: `SELECT run_id, status, mode, started_at FROM ops.pipeline_run WHERE kind = 'layer2' ORDER BY started_at DESC`; failures: `SELECT reason_code, count(*) FROM triage.assessment WHERE run_id = … GROUP BY 1`; trace: `SELECT * FROM triage.v_scope_trace WHERE ruling_id = …` |

---

## 19. Further considerations (each with its trigger)

| Id | Item | Trigger |
|---|---|---|
| FC-1 | V2.0.0 with the 70B in profile `layer2_70b` | the judges' endpoint serves only the 70B, or a frozen-protocol run shows the 70B better after layer 1 V1.1.0 |
| FC-2 | V1.1.0: delimiters and consideration-aware reduction instead of the head/tail cut | measured on `suva-ft-v3` and passing the D-074 rule; or a control tag found in a candidate |
| FC-3 | The branch's six readings as V3.0.0 (needs `llm_judgement` 1:N) | its scores on `suva-ft-v3` under `metrics.py` beat the rule and the best zero-shot with paired CIs above 0 |
| FC-4 | LoRA (`docs/FINETUNE.md` §7) | the lead's go and a GPU; served where Keera cannot |
| FC-5 | Safety-net sample of layer-1 drops (L1-Q3) as `eval` runs | the layer-1 owner asks for it |
| FC-6 | Checkpoints through `ops.work_item`, cross-process limiter, circuit breaker | a live run longer than 30 min, or two runs at once |
| FC-7 | Few-shot (D-021 point 3) | after V1.0.0 is certified, as a MINOR measured version |
| FC-8 | Re-measure "after layer 1" with V1.1.0 instead of filter E | before the ranking threshold is fitted (R-5) |
| FC-9 | `Registry` / `Store` / `Telemetry` protocols of `docs/DB_DDL_PLANNING.md` §4 | a third step writer is written |

---

## 20. Anti-patterns (forbidden)

1. Layer 2 writing `in_scope` or `out_of_scope` (D-063).
2. Ranking or thresholding on `score_0_100` (L2-F02).
3. Reading a number the model wrote as a score (`docs/DOCTRINE.md` §4).
4. Any gateway access outside `src/llm/` (G2).
5. Judging a layer-1 drop in a non-`eval` run (L2-D06).
6. Counting a failed or skipped judgement as "not relevant" (G5).
7. Editing a registered version, prompt or configuration instead of creating the next version (D-064).
8. Changing the prompt or the cut without a MINOR version and a measurement; changing the model without a MAJOR.
9. A prompt or a committed file containing Suva's texts or labels per docket (D-031, D-051).
10. A key, a prompt or a D-051 value in an event or a span attribute (§11).
11. A DB state for a failed run beyond its run row (L2-D07).
12. Importing `experiments/` from `src/` (`AGENTS.md` §4).
13. A threshold chosen on the quarter it is reported on (`docs/EVAL.md` §2).
14. Using a model other than the declared one without recording `model_override` (D-064).
15. A second relevance table beside `triage.assessment` (`public.predictions`).
16. A model-written sentence that claims relevance at this step (L2-D12).

---

## 21. Phase 1: D-lines to record (numbers given at recording; D-075 onward if free)

| Proposed | Content | Status |
|---|---|---|
| D-075 | L2-D01 + L2-D02: layer 2 on the six-schema DB, a scorer that keeps `potentially` | PROPOSED, needs G0 |
| D-076 | L2-D03 + L2-D04 + L2-D10 + L2-D11: V1.0.0 = D-074 chain byte-identical, 8B judge, prompt file, neutraliser, cut kept and disclosed; 70B = V2.0.0 off by default | PROPOSED |
| D-077 | L2-D05: `score_raw` = logit, `score_0_100` display; requirement R-1 for ranking | PROPOSED |
| D-078 | L2-D06 + L2-D07 + L2-D08: candidates, persistence, failures | PROPOSED |
| D-079 | L2-D09 + L2-D13 + L2-D14: traceability, model resolution, certification | PROPOSED |
| D-080 | Supersedes in part the S3 line of `docs/ARCHITECTURE.md` and the judge row of `MODELS.md` (70B → 8B for layer 2), with the D-074 evidence | PROPOSED |

Also: L2-D16 is recorded as a while-open line of D-024; FT-Q3's answer stays with D-021.

---

## 22. Mandatory cleanup and global consistency (run at the end of Phase 5)

| Check | How |
|---|---|
| Every new file is called (no dead module) | `make run` S3 → `src.layer2.run`; `grep -rn "src.layer2" src tests Makefile` |
| `make run` no longer prints `STUB run S3` | `SERVE=0 make run` output |
| Docs that described layer 2 differently are aligned | `docs/ARCHITECTURE.md` S3, `MODELS.md`, `docs/DB_DDL_PLANNING.md` §7.7, §10.2, `docs/STATE.md`, `docs/agents/triage.md` step 5, `docs/agents/finetune.md` |
| The prompt has one home | `grep -rn "Ist dieses Urteil für die Suva relevant" src prompts experiments`: `prompts/` and the frozen builder only |
| No model id typed in code | `tests/test_models_registry.py` |
| No experiments import | `grep -rn "experiments" src` empty |
| Fixtures and SQL tests use the real reason codes | `tests/sql/_fixtures.sql` vs `95_seed_reference.sql` |
| Collisions with branches recorded | `docs/DECISIONS.md` notes on D-060, D-061, D-072..D-074 reuse |

## 23. Final conformity audit (checklist for the follow-up audit)

1. Each L2-D decision has its D-line, its evidence and its reversal trigger (§7, §21).
2. Each work item's acceptance is met with a stored proof (§15).
3. Gates G0 to G-I pass, with the proof listed (§17).
4. Audit findings L2-F01..F16 are closed or carried with an owner (§B.3).
5. No contradiction of audit §7 remains unexplained.
6. Residual risks written in `docs/LAYER2.md` and the report's Limitations.

## 24. Test strategy (in place of Postman: no HTTP surface in this scope)

| Level | What | Where |
|---|---|---|
| Unit | message building, neutraliser identity, cut, reading (both answer sets, bound), explanation | `tests/test_layer2_engine.py` |
| Parity (data-dependent, skips without `data/derived/`) | 3 real rulings then the whole `suva-ft-v3`: messages SHA-256 equal; replayed scores equal | `tests/test_layer2_engine.py`, `src/layer2/validate.py` |
| Client | observer per attempt and per cache hit; cache keys unchanged | `tests/test_llm_client.py` |
| DB end to end (`-m db`, declared mock) | rows in every table, statuses, failure and skip, override, reload no-op, no key or prompt in events | `tests/test_layer2_db.py` |
| SQL | DDL-1..DDL-4, red then green | `tests/sql/30_triage_test.sql` |
| Live slice | 3 rulings de/fr/it, within the measured spread | L2-09 |
| Regression | none of the existing tests change; `make check` green | CI |

## 25. Validation request

Approve or amend, in this order:
1. G0: main's six-schema DB for the submission (L2-D01), and the D-numbers to use.
2. The 8B as the V1.0.0 judge (L2-D04) and the lossless score (L2-D05).
3. The shared-file changes of §A.6 (client observer, `begin_run`, registry loaders, profile V0.3.0, CLI, Makefile).
4. The schedule of §16 and the P0/P1 split.

Nothing in §15 starts before 1 and 2 are answered.

## 26. Execution report (28 Nov 2026, 05:50–06:23 CET)

### 26.1 Done

| Item | State | Proof |
|---|---|---|
| L2-00 G0 | answered: six-schema DB; `review/final-cleanup` never merged | D-075 |
| L2-01 prompt and configuration | done; the prompt file is generated from the measured constants (`ast`) | `prompts/layer2_judge/question.V1.0.0.json`; `test_prompt_file_is_the_measured_prompt` |
| L2-02 engine | done | `tests/test_layer2_engine.py` (14 tests; reading compared with the benchmark's own function; 3 real rulings de/fr/it) |
| L2-03 loaders, registry, profile | done: `load_models` (MODELS.md), `load_prompt`, model and prompt bindings per version; `default` V0.3.0 | `make db-registry` twice, no error |
| L2-04 client observer, run models | done: cache hits logged, trace per call, observer; `begin_run(resolved_models, model_override)`, `finish_run(status)` | `tests/test_llm_client.py` (2 new tests; the 21 others unchanged and green) |
| L2-05 runner | done | run `8fc08fc1…`: 634 judged |
| L2-06 wiring | done: `make layer2`, `make layer2-validate`, `make run` S3 | `SERVE=0 make run` (S3 skipped with its reason in CI) |
| L2-07 certification | done: messages 3,936/3,936, scores 634/634, max difference 0.0 | `expected/layer2/V1.0.0.json`, `results/layer2_validation.json` |
| L2-08 DB end-to-end tests | done: lineage, blobs, spans, replay, failures and retries, failure share, override, reload | `tests/test_layer2_db.py` (6 tests, `-m db`) |
| L2-09 live | done: 3 labelled rulings live identical to D-074 (max difference 0.0); Q2 383/383 judged, 0 failed, 37 s | runs `bf5163ef…`, `8650bb32…`; `results/layer2_q2_2026.json` |
| L2-10 docs | done: D-075..D-080, `docs/LAYER2.md`, STATE, MODELS, ARCHITECTURE S3, AGENTS map, FINETUNE pointer | this branch |
| L2-11 DDL-1, DDL-2 | **not done** (lead, after the layer-1 merge: same files) | `docs/LAYER2.md` §7 |
| L2-12 report lines | not done | — |

Mutation checks (G9): a head cut off by one character, `j` removed from the Ja tokens, and a neutraliser that changes length each turn `tests/test_layer2_engine.py` red; restored, green.

### 26.2 Deviations from the plan

1. Candidates: same pinned `layer1_filter` version instead of same profile version (§6.1): a new profile version that keeps layer 1 needs no layer-1 rerun.
2. `--population` accepts several codes (one run for both labelled quarters).
3. Certification of scores is tied to the `layer1_filter` version that defines the compared subset (`expected/…scores.layer1_filter`); under another layer-1 version only the messages part is compared.
4. `make run` S3 skips, with its reason, a replay without a cache, a database without a layer-1 run, or no `DATABASE_URL`.
5. The client also writes cache hits to `llm_calls.jsonl` (mode `REPLAY`, `cache_hit: true`): every answer a step uses now has a record.
6. Live-run protections, added after a first live attempt whose `LLM_BASE_URL` was a pasted placeholder: every call failed with `UnsupportedProtocol`, was retried 4 times, for each of 383 rulings, with no output, until Ctrl-C left the run `running`. Now: `LLM_BASE_URL` scheme checked at startup (`src/llm/config.py`), preflight call, breaker after 5 failed calls in a row, progress on stderr, `fail_run(status="aborted")` on Ctrl-C (`docs/LAYER2.md` §6). The interrupted run was closed as `aborted` after the fact.
7. `python -m src.layer2 report` writes a run's aggregates to `results/` (G11).

### 26.3 Found while implementing

- Reloading a run's files duplicates its `ops.log_event` rows: the key `(run_id, seq, ts)` takes `ts = clock_timestamp()` at insert (`src/db/runs.py:events`), so `ON CONFLICT` never fires. Layer 1 alike. For the platform owner.
- 1,683 cut texts on `suva-ft-v3` (the audit's 1,682 counted `chars_full > chars_sent` from the dataset's meta, which misses a text of 14,001 to 14,004 characters whose marked text is longer than it).
- `p_yes` in double precision also ties (597 values for 634 rulings): only the logit orders them all (D-077).

### 26.4 Situation check, 08:19 CET: PR #42 (`handoff/components`) and later branches

- PR #42 is open, up to date with `main`, and deletes nothing: it adds a second data layer (`db/migrations`, schema `public`) and the other relevance pipeline (`src/triage/`, read by the UI), and changes `src/courts.py`. Merged with this branch in a throwaway worktree: one conflict (`docs/STATE.md`), all tests green (270 DB tests), layer 2 unchanged (634/634, certification intact), layer 1 unchanged in its decisions but with 386 parity warnings per run (the reference `courts.py` moved).
- `triage/apertus-features`, `summarize/refine` and `summarize/extract` contain `review/final-cleanup`: merging any of them deletes the DDL and `src/layer1/` (D-075).
- Open for the lead: which relevance output the UI and the export show (`triage.*` from `layer2_judge`, or `public.predictions` from the branch pipeline), D-021 and D-046. Detail: the audit dossier §11.

### 26.5 Coordination with the layer-1 traceability work (message of 08:20 CET, merge order decided by the lead)

- **Order:** layer 1 merges first, then this branch is merged with `origin/main` (one `git merge`); the layer-1 session resolves the conflicts and hands over around 11:00. DDL-1 to DDL-4 (§14) are written only on the merged DDL. No push, no merge to `main` before that.
- **Decision numbers:** D-075 to D-080 are this work; D-081 to D-084 are reserved by layer 1; a new layer-2 line takes D-085 or above, announced to the lead.
- **Made compatible on 28 Nov, 08:30 CET:**
  - the model and prompt loaders moved out of `src/db/registry.py` (now identical to `main`) into `src/db/llm_registry.py`; `src/ingest/__main__.py` calls `load_models` first and `bind_resources` after each step registry;
  - registry version V1.0.0 carries `decision: D-076` and `validation: expected/layer2/V1.0.0.json`; profile `default` V0.3.0 carries `decision: D-080` (the other versions untouched);
  - `CODE_PATHS` in `src/layer2/run.py`, for `begin_run(..., code_paths=CODE_PATHS)` after the merge;
  - `Makefile`: the main `.PHONY` line untouched, the layer-2 targets declare their own; `AGENTS.md`: only the `src/layer2/` line;
  - every write of `tests/test_layer2_db.py` (registry, ingest, layer 1, layer 2) runs under `SET ROLE suva_g_pipeline`: green. Layer 2 issues no UPDATE or DELETE; the only UPDATEs are `ops.pipeline_run` (status, finished_at, error_summary) and `ops.span` (status, ended_at, error_message) through `src/db/runs.py`, all granted in `90_roles.sql`.
- **Shared files this branch changes** (beyond the list of the layer-1 message): `src/llm/client.py` (trace, cache-hit log, observer; additive), `src/llm/config.py` (scheme check of `LLM_BASE_URL`), `src/db/runs.py` (`begin_run(resolved_models=, model_override=)`, `finish_run(status=)`, `fail_run(status=)`: keyword arguments with defaults, needed because the run row cannot be updated after insert), `MODELS.md`, `docs/ARCHITECTURE.md`, `docs/FINETUNE.md`, `tests/test_llm_client.py`; new: `src/db/llm_registry.py`, `src/layer2/`, `prompts/layer2_judge/`, `expected/layer2/`, `results/layer2_*.json`, `docs/LAYER2.md`, this file, `tests/test_layer2_*.py`.
- **Not touched:** `src/db/sql/*`, `tests/sql/*`, every layer-1 file (`src/layer1/*`, `src/courts.py`, `src/ingest/hf_base.py`, `src/ingest/gold.py`, registries, `expected/layer1/*`, `expected/ingest/*`, `tests/test_layer1_*`, `tests/test_ingest_*`), the Postgres `suva-l1-pg`, the worktree `tmp/worktrees/layer1-traceability`, layer-1 audits and handoffs.
- **Note:** `tmp/worktrees/l2-pr42-check` was this session's throwaway merge check (§26.4); it was removed at 08:16 CET, before the message arrived. Nothing of layer 1 was in it.

