# MODELS.md: registry of every model used (event rule E6)

> **Status: v0 PROPOSAL (27 Nov 2026), updated after the official template was read.** Owner: `lead`. Every team member adds the tools and models they use. `technical_report.md` copies this table: the Apertus rows into section 3 "Use of Apertus" (Model, How it is used, Where it runs), the whole table into section 8 "Model registry and declarations" (D-043).
> Event rules (`docs/EVENT.md` §2): Apertus 1.5 must perform the core AI task (E1). Any tool or model is allowed during development, closed ones included (E2). At runtime, only Apertus and open-weights models for supporting tasks (E3). Evaluation judges may be open-weights (E4); ours are open-weights (our choice, consistent with E3). The report lists every model with version and role (E6). Breaking E1, E3, E5 or E6 removes eligibility for prizes.
> The template adds: "Submissions must use the v1.5 Apertus model family" (`README.md`) and "Apertus v1.5 (8B or 70B) from Hugging Face (huggingface.co/swiss-ai), accessed via the CSCS / Keera Gateway" (`challenge_description.md`).

## 1. Runtime (what `make run` and the product use)

| Role | Model | Exact id / revision | Endpoint or source | Licence | Status |
|---|---|---|---|---|---|
| Core: key statement, summaries DE/FR; relevance judgement only in a future `layer2_judge` V2.0.0 (D-076) | Apertus 1.5 70B (instruct, thinking off) | gateway `apertus-v1-5-70b`; Hugging Face `swiss-ai/Apertus-v1.5-70B` | Keera gateway (`LLM_BASE_URL`), or the endpoint the judges set in `LLM_BASE_URL` (CSCS possible) | check model card | DECIDED (Apertus mandatory); role split OPEN (D-021, D-022) |
| Layer-2 relevance judge (`layer2_judge` V1.0.0, D-076: the D-074 chain; layer 2 never excludes, D-075); light tasks: query translation, quick prioritisation, demo fallback | Apertus 1.5 8B | gateway `apertus-v1-5-8b`; Hugging Face `swiss-ai/Apertus-v1.5-8B` | Keera gateway, or the endpoint the judges set | check model card | OPEN (D-022); never excludes a ruling alone whatever the answer |
| Embeddings for search and similar rulings | pplx-embed-context-v1-0.6b | `<revision>`; query-side model to fix | local; weights downloaded at image build time and never committed (the template's `.gitignore` excludes weight files), so a **build-time** external dependency listed in the report's Target architecture | MIT | DECIDED if search uses embeddings (D-005); whether it does is OPEN (D-033) |
| Embedding baseline | bge-m3 | `<revision>` | local (weights downloaded at build time, as above) | MIT | OPEN (D-020) |
| Learned relevance score | logistic regression on signals + Apertus probability | trained artefact `results/models/<hash>` | local (scikit-learn) | n/a (our model) | OPEN (D-021, option B only) |
| Evaluation judge (optional) | open-weights, other family than Apertus | `<id>` | `<endpoint>` | `<licence>` | OPEN (`docs/EVAL.md` §4); used only with published κ |
| Core: relevance judgement on candidate rulings, key statement, summaries DE/FR | Apertus 1.5 70B (instruct, thinking off) | gateway `apertus-v1-5-70b`; Hugging Face `swiss-ai/Apertus-v1.5-70B` | Keera gateway (`LLM_BASE_URL`), or the endpoint the judges set in `LLM_BASE_URL` (CSCS possible) | check model card | DECIDED (Apertus mandatory); role split OPEN (D-021, D-022) |
| Candidate gate: read a ruling's matter where code cannot (`src/area_judge.py`, D-060) | Apertus 1.5 70B (instruct, thinking off) | `LLM_NAME` (gateway `apertus-v1-5-70b`) | Keera gateway, through `src/llm/` | as the core row | PROPOSED (D-060) |
| Light tasks: query translation, quick prioritisation, demo fallback | Apertus 1.5 8B | gateway `apertus-v1-5-8b`; Hugging Face `swiss-ai/Apertus-v1.5-8B` | Keera gateway, or the endpoint the judges set | check model card | OPEN (D-022); never excludes a ruling alone whatever the answer |
| Embeddings for search and similar rulings | pplx-embed-context-v1-0.6b | unpinned (latest at use; no code loads it yet); query-side model to fix | local; weights downloaded at image build time and never committed (the template's `.gitignore` excludes weight files), so a **build-time** external dependency listed in the report's Target architecture | MIT | DECIDED if search uses embeddings (D-005); whether it does is OPEN (D-033) |
| Embedding baseline | bge-m3 | Hugging Face `BAAI/bge-m3`, unpinned (latest at use; no runtime code loads it yet) | local (weights downloaded at build time, as above) | MIT | OPEN (D-020) |
| Learned relevance score (`src/triage/scorer.py`, D-061) | logistic regression over code-read facts and the consensus of six Apertus 70B readings (`src/triage/readings.py`) | fitted at each run on Suva's list; parameters stored in `model_runs.params` | local (scikit-learn); the readings go through `src/llm/` | n/a (our model) | PROPOSED (D-061; D-021 option B) |
| Evaluation judge of the summaries (evaluation only, never called by `make run`) | gpt-oss 120B, reasoning effort high | Hugging Face `openai/gpt-oss-120b`, revision `b5c939de8f` | any OpenAI-compatible endpoint set in `JUDGE_BASE_URL` (Hugging Face router, or local) | Apache-2.0 | PROPOSED (`docs/JUDGE.md` §4); not measured yet; used in a headline number only with its validation and κ published |
| Judge candidates for the comparison of `docs/JUDGE.md` §4 | DeepSeek V4 Pro; Qwen 3.5 397B | Hugging Face `deepseek-ai/DeepSeek-V4-Pro`; `Qwen/Qwen3.5-397B-A17B` | as above | MIT; Apache-2.0 | OPEN: kept only if measured better than the default |

`LLM_NAME` is "name and version of the model" (template `README.md`): the judges may set either size, in either form (gateway id or Hugging Face id). The client maps both forms, and the pipeline must complete when `LLM_NAME` is the 8B (`AGENTS.md` G3; D-032, Q-23).

**Allow-list of served models** (PROPOSED, D-032, Q-23). This is the single home of these ids: `AGENTS.md` G3 states the rule, and other files point here instead of listing them.
- The Apertus v1.5 ids, in both forms: gateway `apertus-v1-5-8b` and `apertus-v1-5-70b`; Hugging Face `swiss-ai/Apertus-v1.5-8B` and `swiss-ai/Apertus-v1.5-70B`. Any other form the gateway probe records (`results/gateway_probe.json`) is added here, and nowhere else.
- Plus the `LLM_NAME` the runner set, if it names an Apertus model (case-insensitive `apertus`, any id form); otherwise the run fails fast with a clear message (E1).
- Keera also serves `apertus-v1-5-8b-thinking` and `apertus-v1-5-70b-thinking` (measured 27 Nov, `docs/LESSONS.md` K1). The runtime does not use them (thinking off), so they are not on the allow-list unless `LLM_NAME` names one. Development experiments in `research/` did use `apertus-v1-5-70b-thinking` (§4); those answers are replayed from a local cache, and the shared client refuses new thinking calls. Keera serves no embedding model (K13).

Runtime checks:
- Every response: compare the `model` field (and the `x-keera-model` header when present) with the allow-list above (rule: `AGENTS.md` G3); log provider, served model, latency, tokens, `finish_reason`, cache hit. A missing header is logged, not fatal.
- `tests/test_models_registry.py` fails if the code references a model id that is not in this table.

## 2. Development tools (E2 and E6)

Each member fills their own rows: tool, every model actually used, and what for. Members are named by handle, as in `docs/EVENT.md` §7, never by name (G13).

| Member | Tool | Model(s) and version | Used for |
|---|---|---|---|
| to be confirmed by each member | Claude Code (coding agent; reads `CLAUDE.md`, which imports `AGENTS.md`) | Anthropic `claude-opus-5-5` (the session that wrote the compliance fixes of 28 Nov); other sessions' models to be confirmed | code, research, review |
| to be confirmed by each member | Cursor (IDE agent; named as a reader of `AGENTS.md`) | to be confirmed by each member: the repo does not show whether or with which model it was used | to be confirmed |
| to be confirmed by each member | any other chat or IDE assistant | to be confirmed by each member | to be confirmed |

Only what the repository itself shows is filled in above. Each member confirms or completes their own rows (tool, every model and version actually used, purpose) before submission; nothing here is inferred.

## 3. Pre-event preparation

Research and preparation notes written before the event with AI assistants are declared here and in section 8 of `technical_report.md` (D-043, D-029). To be confirmed by each member: the repository holds no record of pre-event tools or models, so none is listed yet.

## 4. Development-time models (research experiments; never called by `make run`)

The relevance experiments in `research/` (E2, E6). They are not part of the runtime and are listed here so that every model used in development is declared.

| Role | Model | Exact id / revision | Where it runs | Licence | Used in |
|---|---|---|---|---|---|
| Relevance judgements, rubric answers, lesson statements | Apertus 1.5 70B (instruct) | gateway `apertus-v1-5-70b`; unpinned (served by the gateway) | Keera gateway, through `src/llm/` (`research/apertus.py` is a front-end to the shared client) | as the core row | most `research/arm_*.py` arms |
| Comparison with the small model | Apertus 1.5 8B (instruct) | gateway `apertus-v1-5-8b`; unpinned (served by the gateway) | as above | as the core row | `research/arm_b_*.py` (the `m8` stage) |
| Reasoning experiments (thinking mode on) | Apertus 1.5 70B thinking | gateway `apertus-v1-5-70b-thinking`; unpinned (served by the gateway) | Keera gateway; answers from before the routing through `src/llm/` are replayed from `research/cache/apertus.sqlite` (git-ignored); new calls are refused (G3, thinking off) | as the core row | `research/arm_k_thinking.py`, `research/arm_n_thinking2.py`, the `*_think` variants of `research/arm_a_pilot.py` and `research/arm_a_full.py` |
| (declared constant only) | Apertus 1.5 8B thinking | gateway `apertus-v1-5-8b-thinking` | none: defined in `research/apertus.py`, called by no experiment | as the core row | none |
| Embeddings of ruling parts for neighbour features | multilingual-e5-large-instruct | Hugging Face `intfloat/multilingual-e5-large-instruct`, unpinned (latest at use) | local (sentence-transformers); weights downloaded by `research/arm_c_download.py`, never committed | MIT | `research/arm_c_embed.py`, `research/arm_c_download.py` |
| Embeddings of ruling parts (same experiment) | bge-m3 | Hugging Face `BAAI/bge-m3`, unpinned (latest at use) | as above | MIT | `research/arm_c_embed.py`, `research/arm_c_download.py` |
| Classical baselines and combiners | logistic regression, XGBoost (our own models, fitted locally) | fitted per experiment; no pretrained weights | local (scikit-learn, xgboost) | n/a (our models) | `research/arm_d_classical.py`, `research/arm_m_xgboost.py` and others |
