# Technical report - `Suva Scout`, `NGA`

A deeper write-up than the README: what you built, how it works, and what the numbers say.

- **Challenge partner:** Suva
- **Challenge:** Identification of relevant Federal Court judgements and preparation of a legal summary
- **Event:** On-site Zurich
- **Team:** `NGA - Ivan Lecomte, Rabah Nini, Katherine Langille`
- **Demo:** `Link: https://www.youtube.com/watch?v=TL9me1PCdXk`

## 1. Summary

Every quarter Suva's lawyers read the new rulings of the Swiss Federal Supreme Court, pick the ones that matter for accident insurance, and write a short summary of each in German and in French. Suva Scout does the first pass. It loads the rulings, keeps those that could concern Suva, scores each one with the reasons behind the score, writes both summaries for the rulings it flags, and shows everything to the lawyer, who confirms, rejects or edits. **Apertus reads, the code verifies, the lawyer decides.** The lawyer's decisions are stored. Only Apertus v1.5 runs as a language model at runtime.

The candidate filter kept every ruling Suva listed (59 of 59). The relevance scorer, tested each time on a quarter it was not fitted on, found 55 of those 59 (recall 0.932) in a list of 120 (F2 0.772, precision 0.458). For Q2/2026 it flags 76 rulings by decision date. Both summaries are written for each flagged ruling under either date definition (96). The decision-date list is ranked by score. Suva's specialists grade the 10 highest summaries and check the 30 highest-scored rulings; the 30th and the 31st are tied, so that cut is not unique. No lawyer has graded the summaries yet (section 5).

## 2. Architecture

Two parts sit in one repository.

**Suva Scout, the product the judges see.** A pipeline over PostgreSQL, a small API and a React interface.

| Step | What happens | Who |
|---|---|---|
| 1. Load and refresh | Rulings come from the court's daily lists on bger.ch and two public mirrors. When sources disagree, the more official one wins and the conflict is recorded. A ruling that already carries an expert decision, a summary or a score is not removed. | code |
| 2. Candidate filter | Keeps rulings by court division and legal matter, or because the text names Suva or accident insurance. Where code cannot read the matter, Apertus picks it from a fixed list. A failed call keeps the ruling. | code, Apertus for unclear matters |
| 3. Relevance score | Apertus 70B answers six narrow questions. A logistic regression combines their consensus with eleven facts read by code (single judge, Suva is a party, and so on). Each of the twelve rules may push the score only in the direction a lawyer expects, and each push is stored and shown. | Apertus reads, code scores |
| 4. Summaries DE and FR | Apertus names what the summary must say and who says it (the court, the lower court, a party), pointing at sentences of the ruling. Code checks that record. Apertus writes each language from the ruling. Code checks every sentence: language, no new article or number, speaker, and whether the ruling's sentence entails it. A failing sentence is repaired once or removed. | Apertus writes, code verifies |
| 5. Review | The lawyer sees the ruling, the score with its reasons, and both summaries, with a confidence score and the ruling sentence behind each summary sentence. The lawyer confirms or rejects relevance, edits, validates, and can ask Apertus to revise. A ruling already in the list with no summary yet has a button that writes both languages. Further rulings are added by publication-date range. Each decision is stored with what the system had shown. | the lawyer |

**The audited data layer.** A six-schema PostgreSQL database, a first filter that stores every rule's outcome per ruling with the matched text, a FastAPI service, and a Docker cluster. Scout's scorer is registered there as a versioned step. The loader recomputes each score from the stored facts and the registered weights and refuses a ruling where they disagree (`src/scorer/`, `tests/test_scorer_load.py`).

**Layer 2 on that database.** For every ruling the first filter keeps, Apertus 8B answers one question: relevant for Suva, Ja or Nein. The code reads the probability of Ja and stores it, with the exact messages, the served model and the layer-1 decision that let the ruling through. Layer 2 stores that probability. Selection is a later ranking step, and that step is not built. Decisions D-076 to D-080 and D-085 are decided (lead, 28 Nov). The profile stays a draft until ranking and a justification by consideration have versions (D-080).

| What can be said | Proof |
|---|---|
| Each of the 912 scored rulings traces back to the question sent, the served model, the raw answer, the code version and the layer-1 decision | 18 checks, each 912 of 912 (`results/layer2_traceability.json`, `label_coverage`) |
| The database refuses a score that is not tied to its own Apertus call | trigger `t31_call`, tested in `tests/sql/32_layer2_test.sql` |
| The stored label comes from finished runs only, along the ruling's current layer-1 decision | view `triage.v_scope_pipeline` |
| Layer 2 reproduces the published benchmark | 3,936 of 3,936 messages and 634 of 634 scores identical (`results/layer2_validation.json`) |
| One query answers why a ruling has its score | view `triage.v_scope_trace`; on `8C_441/2025` it returns 2 rows in about 0.15 s (section 6) |

407 of those 912 texts are cut (first 12,000 and last 2,000 characters), and the cut is recorded. The 20 most likely first tokens are stored for 912 of 912, and 912 of 912 answers are cache hits. Five runs are on this database (4 of kind layer 2, 1 eval). Every call has a span: 0 calls without one. The partial run records 552 rulings with no stored answer. On the eval run, 0 of 12 events fall outside the run window. The React interface reads Scout's tables. Which source it should show is still an open choice, so this trace is not what the expert sees on screen.

Diagrams: relevance steps in `docs/TRIAGE_PIPELINE.md` §2; the summary writer in `docs/V3.md` §2; the cluster in `docs/DEPLOY.md` §1; the layer-2 chain in `docs/LAYER2_TRACEABILITY.md` §2.

### Target architecture (mandatory)

**Deployable in a), b) and c).** The project is a set of containers (`docker-compose.yml`, runbook `docs/DEPLOY.md`): PostgreSQL, one app image, and optionally Apertus served by vLLM. Only `.env` changes between targets.

- **a) On-premise.** Any Docker host (`linux/amd64`, no GPU needed). Apertus is reached through `LLM_BASE_URL`: the CSCS / Keera gateway or the organisation's own endpoint.
- **b) Air-gapped.** Images, the dataset and the Apertus weights are carried in. The `sovereign` profile serves Apertus on a local GPU with vLLM on an internal network. This profile is written and has not been run: the team had no GPU. New rulings are then imported as files.
- **c) Sovereign Swiss cloud.** The same containers and a PostgreSQL service on a platform operated in Switzerland, with Apertus served in Switzerland (CSCS).
- **Transfer to Azure** (bonus). Configuration by environment variables, one OCI image, standard PostgreSQL. The mapping is in `docs/DEPLOY.md` §8. Azure is separate from c).

| | Build time (connected machine) | Runtime |
|---|---|---|
| Images, packages | `python:3.12-slim`, `pgvector/pgvector`, vLLM for b), pinned by digest; Python packages pinned by `uv.lock`; Node packages for the UI build | none |
| Data | the corpus, downloaded once from Hugging Face | none in replay; a refresh of new rulings calls bger.ch and two mirrors |
| Model | Apertus v1.5 weights, for b) only | the Apertus endpoint `LLM_BASE_URL`; it must return token log-probabilities |

No other external service at runtime: no telemetry, no closed model. The built UI loads no font and no script from a CDN.

## 3. Use of Apertus

- **Model:** `swiss-ai/Apertus-v1.5-70B` (gateway id `apertus-v1-5-70b`) for Scout's readings and summaries. `swiss-ai/Apertus-v1.5-8B` (`apertus-v1-5-8b`) answers Ja or Nein in layer 2. The code stores the probability. The judges may set either size.
- **How it is used:** inference only. No fine-tuning.
- **Where it runs:** the organisers' Keera gateway during the event; any OpenAI-compatible endpoint set in `LLM_BASE_URL`, including vLLM in the cluster.

| Job | How the answer is taken |
|---|---|
| Six readings per ruling: would the legal department include it; does the court make a reusable legal statement; four five-level scales on how much the ruling teaches beyond the case | one token each, read from its log-probabilities, never a number the model writes; standardised and averaged into one input of the scorer |
| Matter of a ruling when code cannot read it | one token among eight options |
| Summary: record of what to say, writing, sentence-by-sentence entailment check, repair | sentence ids and closed formats for the record; free text for the summary, then checked by code |

Apertus never supplies an identifier: docket numbers, dates, articles and links are read from the source by code. Every call goes through one client: temperature 0, a timeout, the served model checked against an allow-list of Apertus v1.5 ids. The client logs each call and keeps the prompt as a hash. The data layer stores the exact messages. A cache replays a run without the gateway. Prompts are in `src/triage/reading_prompts.py` and `src/summarize/v3/`.

**Why Apertus is one input of the score.** On the same out-of-quarter list of 120 (the top 40 % of core-area rulings), code-read facts alone find 52 of 59, facts plus the Apertus readings find 55, and the Apertus readings alone find 42 (`results/triage_features.json`, variants "LR facts8", "LR facts8+consensus (baseline)" and "LR Apertus consensus alone", key `pooled."0.40"`). The gain is tied to that list size: at 89 rulings the readings find 45 where the facts alone find 49, and at 149 and above the two find the same number. Separately, zero-shot Apertus did not beat a three-signal rule with no model. For a list of 45 per quarter, recall was 0.780 for the rule, 0.746 for the 8B and 0.576 for the 70B; F2 was 0.706, 0.675 and 0.521 (`results/finetune_benchmark_v3.md`, top-45 list). That benchmark is 45,144 calls and 144,566,880 prompt tokens (`results/finetune_benchmark_v3.json`). The lawyer has the last word.

**Every model, with its role** (`MODELS.md`). Runtime language models: the two Apertus v1.5 ids above. The relevance score itself is a local logistic regression. Development only, never called by `make run`: Apertus 70B thinking (`apertus-v1-5-70b-thinking`); embeddings `intfloat/multilingual-e5-large-instruct` and `BAAI/bge-m3`, unpinned; locally fitted XGBoost. `pplx-embed-context-v1-0.6b` is registered for a search feature that no runtime code loads. Evaluation judges, open weights, never called by `make run`: `openai/gpt-oss-120b` revision `b5c939de8f`, and `deepseek-ai/DeepSeek-V4-Pro`. `Qwen/Qwen3.5-397B-A17B` is registered as a candidate and has no stored run. Coding assistants: Claude Code with `claude-opus-5-5` for one recorded session. Cursor is named in `MODELS.md`; its model, the other sessions, and any pre-event assistant are not recorded in the repository.

## 4. Data

| Data | Source | Status | In git? |
|---|---|---|---|
| Rulings of the Federal Supreme Court | bger.ch daily lists; entscheidsuche.ch; Hugging Face `voilaj/swiss-caselaw` (OpenCaseLaw) | official texts, not protected by copyright in Switzerland (our non-lawyer reading, `docs/DATA.md` §8) | no; pulled from the team's public dataset `suva-nga/bger-rulings` when the database is empty |
| Suva's relevance list (two quarters) and 55 example summaries DE/FR | the organisers' template, `judgements/` | Suva's material, published by the organisers without a licence; not ours to license (`NOTICE`) | yes, unchanged |
| Recorded Apertus answers | our runs | ours | yes, `replay/llm/` |

**Personal data.** Rulings are published anonymised and contain health information. We store and show the text as published. We do not add, infer or link personal data about anyone in a ruling. Suva's files also name their authors. The team's public dataset carries Suva's summaries with their author and source link as published in the template.

**Consent.** We collected no data from people. Expert decisions made in the application during the event were the team's own.

**Labels.** Suva's list holds only the rulings Suva picked. Every other ruling of those two quarters counts as not relevant, so a ruling Suva would have accepted and did not list counts against us. Each ruling keeps its decision date and its publication date. For Q2/2026 the decision-date list has 76 rulings and is the clean prediction. The publication-date list has 78, and 20 of them were decided in March 2026, a quarter the scorer was fitted on (`results/deliverables/Q2_2026_relevant_by_published.csv`). The union of both dates has 96.

## 5. Limitations

**Integration.** Scout and the audited data layer share a repository and still use separate databases. The React app reads Scout's tables. Scout's candidate filter is separate from the audited first filter. Summaries are not written into the data layer's summary schema. The data-layer pipeline loads Scout's stored scores and does not rerun the readings or the fit. The two filters disagree on some rulings at the margin.

**What layer 2 still lacks.** Three gaps, in this order. There is no ranking step: no threshold, no order, no selected or not-selected mark, so layer 2's score is not yet a decision. The interface and this database are two sources, and which one the interface should read is still open. The layer-2 explanation names the probability, the model and the version. A justification that cites the ruling's considerations, checked by code, is not built.

**Learning.** Every expert decision and summary edit is stored as a labelled example. Refitting the scorer on those labels is not built. The scorer is fitted on Suva's list only.

**Relevance.**
- With 59 relevant rulings, one ruling moves recall by 0.017.
- Both labelled quarters shaped the features, the prompts and the list size. The test fits the weights on one quarter and tests on the other, but the design saw both, so the numbers are optimistic. The clean prediction is the Q2/2026 list by decision date (76 rulings). The list by publication date is not: 20 of its 78 rulings were decided in a quarter the scorer was fitted on.
- The cut is a quota, not a calibrated threshold. In each quarter the flagged rulings are the top 40 % of the kept accident, military and disability rulings (`CORE_SHARE = 0.40` in `src/triage/scorer.py`; the same share is the `0.40` key in `results/triage_pipeline.json` and `results/triage_features.json`). A quota does not tell a quiet quarter from a busy one.
- Apertus's share of the score is modest: its consensus weighs 0.3245 per standard deviation, and the strongest code-read rule weighs 2.2695. Facts alone find 52 of 59 on the list of 120; with the readings, 55; the readings alone, 42. At a list of 89 the readings find fewer rulings than the facts alone, and from a list of 149 the two agree (`results/triage_features.json`).
- 68 feature variants were tried against the baseline, and none beat it (`results/triage_features.json`, `beats_baseline` false on all 68). 45 claim variants were tried against a rule written beforehand: 44 fail it, and the remaining row is the baseline itself (`results/triage_claims.json`, `passes`). None was added.
- Where code cannot read the matter, Apertus picks it from a fixed list. On rulings whose rubric is known, it kept 459 of 460 in-scope rulings (157 of 158, 178 of 178, 124 of 124 on courts 4, 8 and 9). Three thresholds were written before the first run: keep at least 97 % of in-scope rulings, drop at least 70 % of out-of-scope rulings, and agree on at least 98 % of 50 repeated calls. The in-scope bar holds. The drop bar does not, on two courts: 5 of 142 out-of-scope rulings in court 4, and 79 of 122 in court 8. Court 8 also repeats the same decision on 48 of 50 calls (`results/area_judge_court4.json`, `area_judge_court8.json`, `area_judge_court9.json`; bars in `src/area_judge.py`).
- Of 23 rulings Suva summarised in an earlier quarter, never used as labels, 16 score above the cut and 2 score very low.
- A ruling the filter drops gets no score. Only accident, military and disability rulings decided by more than one judge are read by Apertus. Other kept rulings are scored from the facts.

**Summaries.**
- No lawyer has graded them. The current writer has no measurement on unseen rulings.
- An earlier writer was rated by an open-weights judge with an unvalidated rubric: 13 of 42 summaries usable (0.31; German 0.14, French 0.48). That result is why the current writer exists. It says nothing about the current writer.
- The writer fails in the open: a sentence that fails twice is removed, the summary is marked for review, and a confidence score computed by code is shown. Of the 96 Q2/2026 summaries, the German text fell back to the earlier writer for 3 and the French for 5. One German text is an expert text.
- Italian rulings give the weakest summaries. Grammar slips survive.

**Operation.** bger.ch challenges automated access, so a refresh may rest on the mirrors. A replayed run proves the code path. It does not prove the gateway. Without log-probabilities the readings are empty and the score rests on the facts. The air-gapped profile and a run by someone outside the team have not been tested. In the interface, "Update" ingests rulings and then scores every ruling again, refits the scorer and re-cuts the list (`src/suva_app/updates.py`). Without the `LLM_*` variables that path runs in replay, fails on the first new ruling and writes nothing. It is not a step to press unrehearsed: the flagged set can change, and `results/triage_pipeline.json` is overwritten.

## 6. Reproducibility

- **Commit:** `42a7b04339779b167c9663520c6993ffb80f9174` on `main`. The measurements in `results/` belong to that history.
- **Hardware:** a laptop with Docker; no GPU. The model runs behind `LLM_BASE_URL`.
- **Determinism:** every Apertus call at temperature 0. The committed answers under `replay/llm/` reproduce the run without the gateway.
- **Expected duration:** no duration is stored in `results/`. Replay does not call the gateway.

### Measured results

Recall first. F2 = 5·TP / (4·N + submitted), N being the number of truly relevant rulings. Every figure below is taken from the file named in the row.

| Measure | Result | Source |
|---|---|---|
| Candidate filter: Suva's listed rulings kept | 59 of 59, keeping 1,201 of 6,464 | `results/triage_pipeline.json` |
| Relevance, out of quarter (fit on one labelled quarter, list the other, pooled) | recall 0.932 (55 of 59), F2 0.772, 120 listed, precision 0.458 | same file, `out_of_quarter` |
| Per quarter | 29 of 31 in a list of 66; 26 of 28 in a list of 54 | same file, `per_quarter` |
| Apertus readings | 422 rulings read six times, 0 failed | same file |
| Q2/2026 list, by decision date, ranked by score | 76 flagged of 421 kept. The 10 highest summaries and the 30 highest rulings are the head of this list; ranks 30 and 31 are tied | same file, `by_quarter`; `results/deliverables/Q2_2026_relevant_by_decided.csv` |
| Q2/2026 summaries, either date | 96 rulings, German and French text on each; writer v3 for 92 DE and 91 FR, v2 for 3 DE and 5 FR, one expert German text | `results/deliverables/summaries_Q2_2026_flagged.json` |
| Audited first filter (data layer) | keeps 935 of 6,055; 82 of 82 rulings Suva listed or summarised | `results/layer1_validation.json` |
| What the Apertus readings add, same quota of 40 %, list of 120 | facts alone 52 of 59; facts plus readings 55; readings alone 42. At 89 rulings the readings find 45 and the facts alone 49; at 149 and above the two find the same number | `results/triage_features.json` |
| Variants tried and not adopted | 68 feature variants, none beats the baseline; 45 claim variants, 44 fail the pre-written rule and 1 row is the baseline | `results/triage_features.json`, `results/triage_claims.json` |
| Zero-shot Apertus vs a three-signal rule, top 45 per quarter | recall 0.780 / 0.746 / 0.576 and F2 0.706 / 0.675 / 0.521 (rule / 8B / 70B). The benchmark file sums to 45,144 calls and 144,566,880 prompt tokens | `results/finetune_benchmark_v3.md`, `results/finetune_benchmark_v3.json` |
| Matter read by Apertus, courts 4, 8 and 9 | in-scope rulings kept: 157 of 158, 178 of 178, 124 of 124 (459 of 460). Out-of-scope dropped: 5 of 142, 79 of 122, 153 of 176. Repeated decisions: 50 of 50, 48 of 50, 50 of 50. Pre-written bars: 97 % kept in scope, 70 % dropped out of scope, 98 % repeat agreement | `results/area_judge_court4.json`, `area_judge_court8.json`, `area_judge_court9.json` |
| Q2/2026 list by publication date | 78 rulings; 20 decided in March 2026 | `results/deliverables/Q2_2026_relevant_by_published.csv` |
| Earlier summary writer, open-weights judge | 13 of 42 usable (0.3095; German 0.1429, French 0.4762) | `results/judge_run_pipeline_v1.json` |
| Layer 2 trace | 18 checks, each 912 of 912; 407 of 912 texts cut; 912 of 912 cache hits; 0 calls without a span; partial run lists 552 rulings with no answer; eval run 0 of 12 events outside its window | `results/layer2_traceability.json` |
| Layer 2 against the benchmark | 3,936 of 3,936 messages identical (0 missing, 0 different); 634 of 634 scores identical, max absolute difference 0. On the 634 scores: 634 distinct raw scores, 597 distinct P(Ja), 90 distinct scores on 0–100, 123 tied at 100 and 277 tied at 0. Of 3,936 texts, 1,683 are cut (first 12,000 and last 2,000 characters) and 2,253 are not | `results/layer2_validation.json` |
| Layer 2 live, Q2/2026 union | 383 in, 383 judged, 0 failed, 0 errors, 0 skipped; 380 live calls, 3 cache hits, 383 attempts; 190 texts cut; 1,206,304 input tokens; latency p50 378 ms, p95 528 ms; from 06:58:35 to 06:59:11. Languages: 247 German, 126 French, 10 Italian. P(Ja): 170 below 0.001, 57 from 0.001 to 0.1, 15 from 0.1 to 0.5, 11 from 0.5 to 0.9, 130 at 0.9 or above. Scores: 383 distinct raw scores, 81 distinct scores on 0–100, 88 at 100, 133 at 0. Model `apertus-v1-5-8b`. By division, count and mean P(Ja): 8C 168 / 0.547, 9C 100 / 0.361, 4A 68 / 0.139, 4D 12 / 0, 6B 9 / 0.118, 2C 7 / 0.009, 9F 5 / 0.226, 8F 5 / 0.4, 5A 3 / 0, 4F 3 / 0, 7B 2 / 0, 9G 1 / 0.014 | `results/layer2_q2_2026.json` |

### How to run

**Prerequisites:** git, Docker with Compose, Python 3.12+ with [uv](https://docs.astral.sh/uv/), Node for the UI build. `linux/amd64`. No GPU for replay.

**Configuration:** copy `.env.example` to `.env`. For live calls set:

```
LLM_NAME      an Apertus v1.5 id, e.g. apertus-v1-5-70b or swiss-ai/Apertus-v1.5-70B
LLM_BASE_URL  endpoint base URL (OpenAI-compatible; it must return log-probabilities)
LLM_API_KEY   your API key
```

**Run:**

```
make run                      # replay: no gateway call, no key; then serves the app on http://127.0.0.1:8000
make run-live ARGS="--limit 5"   # real Apertus calls, a smoke run
make run-live ARGS="--all"       # the full live run
```

`make run` starts the database, pulls the corpus from the team's public dataset when the database is empty, scores the rulings and writes the summaries from the committed answers, then serves the interface. `SERVE=0 make run` stops before serving. Every output is labelled `LIVE` or `REPLAY`.

The six-schema data layer (`src/db/sql`, `src/layer1`, `src/layer2`, `src/api`, cluster in `docs/DEPLOY.md`) has its own commands: `make pipeline`, `make api`, `make cluster-up`. `make bridge` copies Scout's scores into that database.

**Layer 2, live.** On a database built by `make pipeline`, this query uses a Q2/2026 ruling on purpose: Suva's Q2 list is hidden, so the example shows no Suva label. Two rows come back in about 0.15 s. Hop 0 is layer 2: the score, model `apertus-v1-5-8b`, version V1.0.0, and its explanation. Hop 1 is layer 1: kept by `L1_KEEP_RUBRIC`, 9 rules evaluated, and its explanation. Both rows name the code hash and the Hugging Face revision.

```sql
SELECT hop, step, in_suva_scope, score_0_100, p_yes, reason_code, served_model
FROM triage.v_scope_trace
WHERE ruling_id = (SELECT ruling_id FROM corpus.ruling WHERE docket = '8C_441/2025')
ORDER BY hop;
```


## License

Creative Commons Attribution 4.0 (CC-BY-4.0). All HackApertus projects are open-sourced.

Code is Apache-2.0 (`LICENSE`). This report is CC-BY-4.0. Datasets we publish are CDLA-Permissive-2.0. Suva's files in `judgements/` and the pitch PDF remain Suva's (`NOTICE`).

## References

- HackApertus Zurich, Suva challenge template: <https://github.com/HackApertus/zurich-suva>.
- Apertus v1.5: <https://huggingface.co/swiss-ai/Apertus-v1.5-70B>, <https://huggingface.co/swiss-ai/Apertus-v1.5-8B>.
- OpenCaseLaw, dataset `voilaj/swiss-caselaw`; entscheidsuche.ch; Swiss Federal Supreme Court, <https://www.bger.ch>.
