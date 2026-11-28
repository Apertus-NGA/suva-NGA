# Technical report — Suva Scout, NGA - Need GPUs for Apertus

A deeper write-up than the README: what you built, how it works, and what the
numbers say.

- **Challenge partner:** Suva
- **Challenge:** Identification of relevant Federal Court judgements and preparation of a legal summary
- **Event:** On-site Zurich
- **Team:** NGA - Need GPUs for Apertus — TheDiRocco, RabahSend, bananagoo
- **Demo:** `<to fill: link to video>`

## 1. Summary

Every quarter Suva's lawyers read the new rulings of the Swiss Federal Supreme Court, pick the ones that matter for accident insurance, and write a short summary of each in German and in French. Suva Scout does the first pass. It loads the rulings, keeps those that could concern Suva, scores each one with the reasons behind the score, writes both summaries for the rulings it flags, and shows everything to the lawyer, who confirms, rejects or edits. The design is a division of labour: **Apertus reads, the code verifies, the lawyer decides, and the system learns from the lawyer's decisions.** Only Apertus v1.5 runs at runtime. The candidate filter kept every ruling Suva listed (59 of 59) <!-- RES:results/triage_pipeline.json relevant_not_kept_by_layer1 0, training_relevant 59 -->. The relevance scorer, tested each time on a quarter it was not fitted on, found 55 of those 59 rulings (recall 0.932) in a list of 120, which gives F2 0.772 <!-- RES:results/triage_pipeline.json out_of_quarter: relevant_found 55, relevant_total 59, recall 0.932, submitted 120, f2 0.772 -->. For the second quarter of 2026, the target of the challenge, it flags 76 rulings and both summaries are written for each <!-- RES:results/triage_pipeline.json by_quarter."2026 Q2".suspected_relevant 76; RES:results/deliverables/Q2_2026_relevant_by_decided.csv (76 rows); RES:results/deliverables/summaries_Q2_2026_flagged.json (96 rulings under either date, all with text_de and text_fr) -->. No lawyer has graded the summaries yet (section 5).

## 2. Architecture

The repository holds two parts that run side by side.

**Suva Scout, the product the judges see.** A pipeline over PostgreSQL, a small API and a React interface.

| Step | What happens | Who |
|---|---|---|
| 1. Load and refresh | Rulings come from the court's daily lists on bger.ch and two public mirrors; when sources disagree, the more official one wins and the conflict is recorded. A stored record is never overwritten. | code |
| 2. Candidate filter | Keeps rulings by court division and legal matter, or because the text names Suva or accident insurance. Where code cannot read the matter, Apertus picks it from a fixed list; a failed call keeps the ruling. | code, Apertus for unclear matters |
| 3. Relevance score | Apertus 70B answers six narrow questions about the ruling. A logistic regression combines their consensus with eleven facts read by code (single judge, Suva is a party, and so on). Each of the twelve rules may push the score only in the direction a lawyer expects, and each rule's push is stored and shown. | Apertus reads, code scores |
| 4. Summaries DE and FR | Apertus names what the summary must say and who says it (the court, the lower court, a party), pointing at sentences of the ruling. Code checks that record. Apertus writes each language from the ruling, never from the other language. Code checks every sentence: language, no new article or number, speaker, and whether the ruling's sentence entails it. A failing sentence is repaired once or removed. | Apertus writes, code verifies |
| 5. Review | The lawyer sees the ruling, the score with its reasons, and both summaries with a confidence score and the ruling sentence behind each summary sentence; confirms or rejects relevance; edits and validates; asks for a summary of any other ruling. Each decision is stored with what the system had shown. | the lawyer |

**The audited data layer.** A six-schema PostgreSQL database, a first filter in which every rule's outcome is stored per ruling with the matched text, a FastAPI service, and a hardened Docker cluster. The Scout scorer is registered in it as a versioned step, and its scores are loaded with a check: the loader recomputes each score from the stored facts and the registered weights and refuses any ruling where they disagree <!-- code src/scorer/, tests/test_scorer_load.py, decision D-094 -->. On the integration run of 28 Nov, 925 rulings were loaded with a score and 205 promoted <!-- integration run, 28 Nov; not in a results/ file -->.

Diagrams: relevance steps `docs/TRIAGE_PIPELINE.md` §2; summary writer `docs/V3.md` §2; cluster `docs/DEPLOY.md` §1. <!-- CHECK: these three files exist on main after the merge -->

### Target architecture (mandatory)

**Deployable in a), b) and c).** The project is a set of containers (`docker-compose.yml`, runbook `docs/DEPLOY.md`): PostgreSQL, one app image, and optionally Apertus served by vLLM. Only `.env` changes between targets.

- **a) On-premise** — any Docker host (`linux/amd64`, no GPU needed). Apertus is reached through `LLM_BASE_URL`: the CSCS / Keera gateway or the organisation's own endpoint.
- **b) Air-gapped** — images, the dataset and the Apertus weights are carried in; the `sovereign` profile serves Apertus on a local GPU with vLLM on an internal network. Written, not tested: we had no GPU. New rulings are then imported as files.
- **c) Sovereign Swiss cloud** — the same containers and a PostgreSQL service on a platform operated in Switzerland, with Apertus served in Switzerland (CSCS).
- **Transfer to Azure** (bonus) — configuration by environment variables, one OCI image, standard PostgreSQL; mapping in `docs/DEPLOY.md` §8. Azure is not presented as c).

| | Build time (connected machine) | Runtime |
|---|---|---|
| Images, packages | `python:3.12-slim`, `pgvector/pgvector`, vLLM for b), pinned by digest; Python packages pinned by `uv.lock`; Node packages for the UI build | none |
| Data | the corpus, downloaded once from Hugging Face | none in replay; a refresh of new rulings calls bger.ch and two mirrors |
| Model | Apertus v1.5 weights, for b) only | the Apertus endpoint `LLM_BASE_URL`; it must return token log-probabilities |

No other external service at runtime: no telemetry, no closed model. <!-- CHECK: the built UI loads no font or script from a CDN -->

## 3. Use of Apertus

- **Model:** `swiss-ai/Apertus-v1.5-70B` (gateway id `apertus-v1-5-70b`) for readings and summaries. `swiss-ai/Apertus-v1.5-8B` runs an earlier yes/no judge in the data layer and can be set by the judges.
- **How it is used:** inference only. No fine-tuning.
- **Where it runs:** the organisers' Keera gateway during the event; any OpenAI-compatible endpoint set in `LLM_BASE_URL`, including vLLM in the cluster.

| Job | How the answer is taken |
|---|---|
| Six readings per ruling: would the legal department include it; does the court make a reusable legal statement; four five-level scales on how much the ruling teaches beyond the case | one token each, read from its log-probabilities, never a number the model writes; standardised and averaged into one input of the scorer |
| Matter of a ruling when code cannot read it | one token among eight options |
| Summary: record of what to say, writing, sentence-by-sentence entailment check, repair | sentence ids and closed formats for the record; free text for the summary, then checked by code |

Apertus never supplies an identifier: docket numbers, dates, articles and links are read from the source by code. Every call goes through one client: temperature 0, a timeout, the served model checked against an allow-list of Apertus v1.5 ids, the full request and answer logged, and a cache that replays a run without the gateway. Prompts are in `src/triage/reading_prompts.py` and `src/summarize/v3/`. <!-- CHECK paths after merge -->

**Why Apertus is one input and not the whole score.** We first tested zero-shot Apertus against a three-signal rule with no model, on 59 relevant rulings. For a list of 45 rulings per quarter, recall was 0.780 for the rule, 0.746 for the 8B and 0.576 for the 70B; F2 was 0.706, 0.675 and 0.521 <!-- API:results/finetune_benchmark_v3.md, Primary metrics: Recall / F2 of the top-45 list per quarter -->. So the scorer combines facts and readings, and the lawyer has the last word.

Models not used at runtime: `openai/gpt-oss-120b` and DeepSeek V4 Pro (open weights), as evaluation judges of summaries during development <!-- RES:results/judge_run_pipeline_v1.json judge_model; RES:results/judge_metaeval_dev_deepseek.json -->; Apertus 70B thinking, in research experiments only; coding assistants, including closed models, listed in `MODELS.md`. <!-- CHECK: MODELS.md §2 is filled by each member -->

## 4. Data

| Data | Source | Status | In git? |
|---|---|---|---|
| Rulings of the Federal Supreme Court | bger.ch daily lists; entscheidsuche.ch; Hugging Face `voilaj/swiss-caselaw` (OpenCaseLaw) | official texts, not protected by copyright in Switzerland (our non-lawyer reading, `docs/DATA.md` §8) | no; pulled from the team's public dataset `suva-nga/bger-rulings` when the database is empty |
| Suva's relevance list (two quarters) and 55 example summaries DE/FR | the organisers' template, `judgements/` | Suva's material, published by the organisers without a licence; not ours to license (`NOTICE`) | yes, unchanged |
| Recorded Apertus answers | our runs | ours | yes, `replay/llm/` |

**Personal data.** Rulings are published anonymised but contain health information. We store and show the text as published and never add, infer or link personal data about anyone in a ruling. Suva's files also name their authors; our public dataset carries Suva's summaries with their author and source link as published in the template. <!-- CHECK: team to confirm this sentence matches the dataset as published (D-051) -->

**Consent.** We collected no data from people. Expert decisions made in the application during the event were the team's own.

**Labels.** Suva's list holds only the rulings Suva picked. We count every other ruling of those two quarters as not relevant, so a ruling Suva would have accepted but did not list counts against us.

## 5. Limitations

**Integration.** The two parts share a repository, not yet a database: the React app reads Suva Scout's own tables, not the FastAPI service; Scout's candidate filter is not a version of the audited first filter; summaries are not written to the data layer's summary schema; and the data-layer pipeline loads Scout's stored scores without rerunning the readings or the fit. On the integration run, 165 rulings Scout scored were not loaded because the audited filter drops them <!-- integration run, 28 Nov; not in a results/ file -->: the two filters disagree at the margin.

**Learning.** Every expert decision and summary edit is stored as a labelled example. Refitting the scorer on them is not built; it is fitted on Suva's list only.

**Relevance.**
- With 59 relevant rulings, one ruling moves recall by 0.017 (1 of 59).
- Both labelled quarters shaped the features, the prompts and the list size. The test fits the weights on one quarter and tests on the other, but the design saw both, so the numbers are optimistic. Only the Q2/2026 list is a true prediction.
- Apertus's share is modest: its consensus weighs 0.32 per standard deviation against 2.27 for the strongest code-read rule <!-- RES:results/triage_pipeline.json rule_weights.consensus.weight 0.3245, rule_weights.area_iv.weight 2.2695 -->.
- Of 23 rulings Suva summarised in an earlier quarter, never used as labels, 16 score above the cut and 2 score very low <!-- RES:results/triage_pipeline.json summarised_by_suva_not_in_training -->.
- A ruling the filter drops gets no score. Only accident, military and disability rulings decided by more than one judge are read by Apertus; other kept rulings are scored from the facts.

**Summaries.**
- No lawyer has graded them, and the current writer has no measurement on unseen rulings.
- The earlier writer was rated by an open-weights judge with an unvalidated rubric: 13 of 42 summaries usable (0.31; German 0.14, French 0.48) <!-- RES:results/judge_run_pipeline_v1.json summaries 42, usable_share 0.3095, by_language de 0.1429, fr 0.4762 -->. That result is why the current writer exists; it says nothing about the current writer.
- The writer fails visibly: a sentence that fails twice is removed, the summary is marked for review, and a confidence score computed by code is shown. Of the 96 Q2/2026 summaries exported, the German text fell back to the earlier writer for 3 and the French for 5 <!-- RES:results/deliverables/summaries_Q2_2026_flagged.json writer_de: v3 92, v2 3, expert 1; writer_fr: v3 91, v2 5 -->.
- Italian rulings give the weakest summaries; grammar slips survive.

**Operation.** bger.ch challenges automated access, so a refresh may rest on the mirrors. A replayed run proves the code path, not the gateway. Without log-probabilities from the endpoint the readings are empty and the score rests on the facts. The air-gapped profile and a run by someone outside the team were not tested.

## 6. Reproducibility

- **Commit:** the commit tagged `submission` on `main`.
- **Hardware:** a laptop with Docker; no GPU. The model runs behind `LLM_BASE_URL`.
- **Determinism:** every Apertus call at temperature 0; the committed answers under `replay/llm/` reproduce the run without the gateway.

### Measured results

Recall first, then F2 = 5·TP / (4·N + submitted), N being the number of truly relevant rulings.

| Measure | Result |
|---|---|
| Candidate filter: Suva's listed rulings kept | 59 of 59, keeping 1,201 of 6,464 rulings <!-- RES:results/triage_pipeline.json relevant_not_kept_by_layer1 0, kept_by_layer1 1201, rulings 6464 --> |
| Relevance, out of quarter (fit on one labelled quarter, list the other, pooled) | recall **0.932** (55 of 59), F2 **0.772**, 120 listed, precision 0.458 <!-- RES:results/triage_pipeline.json out_of_quarter --> |
| — per quarter | 29 of 31 in a list of 66; 26 of 28 in a list of 54 <!-- same, per_quarter --> |
| Apertus readings | 422 rulings read six times, 0 failed <!-- RES:results/triage_pipeline.json core_rulings_read_by_apertus 422, apertus_readings_failed 0 --> |
| Q2/2026 list, by decision date | 76 flagged of 421 kept <!-- RES:results/triage_pipeline.json by_quarter."2026 Q2" --> |
| Audited first filter (data layer) | keeps 935 of 6,055; 82 of 82 rulings Suva listed or summarised <!-- API:results/layer1_validation.json run V1.1.0 totals, recall --> |

### How to run

**Prerequisites:** git, Docker with compose, Python 3.12+ with [uv](https://docs.astral.sh/uv/), Node for the UI build. <!-- CHECK: exact prerequisites and whether a Docker-only path exists -->

**Configuration:** copy `.env.example` to `.env`. For live calls set:

```
LLM_NAME      an Apertus v1.5 id, e.g. apertus-v1-5-70b or swiss-ai/Apertus-v1.5-70B
LLM_BASE_URL  endpoint base URL (OpenAI-compatible)
LLM_API_KEY   your API key
```

**Run:**

```
make run        # replay: no gateway call, no key; then serves the app on http://127.0.0.1:8000
make run-live ARGS="--limit 5"   # real Apertus calls, a smoke run; ARGS="--all" for everything
```

`make run` starts the database, pulls the corpus from the team's public dataset when the database is empty, scores the rulings and writes the summaries from the committed answers, then serves the interface. Every output is labelled `LIVE` or `REPLAY`. <!-- CHECK: commands, port and the ARGS run-live needs (the Scout Makefile takes ARGS="--limit N" or "--all") -->

**Expected duration:** `<to fill: measured duration of make run>`.


## License

Creative Commons Attribution 4.0 (CC-BY-4.0). All HackApertus projects are open-sourced.

## References

- HackApertus Zurich, Suva challenge template: <https://github.com/HackApertus/zurich-suva>.
- Apertus v1.5: <https://huggingface.co/swiss-ai/Apertus-v1.5-70B>, <https://huggingface.co/swiss-ai/Apertus-v1.5-8B>.
- OpenCaseLaw, dataset `voilaj/swiss-caselaw`; entscheidsuche.ch; Swiss Federal Supreme Court, <https://www.bger.ch>.
