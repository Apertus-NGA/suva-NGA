# MODELS.md: registry of every model used (event rule E6)

> **Status: v0 PROPOSAL (27 Nov 2026), updated after the official template was read.** Owner: `lead`. Every team member adds the tools and models they use. `technical_report.md` copies this table: the Apertus rows into section 3 "Use of Apertus" (Model, How it is used, Where it runs), the whole table into section 8 "Model registry and declarations" (D-043).
> Event rules (`docs/EVENT.md` §2): Apertus 1.5 must perform the core AI task (E1). Any tool or model is allowed during development, closed ones included (E2). At runtime, only Apertus and open-weights models for supporting tasks (E3). Evaluation judges may be open-weights (E4); ours are open-weights (our choice, consistent with E3). The report lists every model with version and role (E6). Breaking E1, E3, E5 or E6 removes eligibility for prizes.
> The template adds: "Submissions must use the v1.5 Apertus model family" (`README.md`) and "Apertus v1.5 (8B or 70B) from Hugging Face (huggingface.co/swiss-ai), accessed via the CSCS / Keera Gateway" (`challenge_description.md`).

## 1. Runtime (what `make run` and the product use)

| Role | Model | Exact id / revision | Endpoint or source | Licence | Status |
|---|---|---|---|---|---|
| Core: relevance judgement on candidate rulings, key statement, summaries DE/FR | Apertus 1.5 70B (instruct, thinking off) | gateway `apertus-v1-5-70b`; Hugging Face `swiss-ai/Apertus-v1.5-70B` | Keera gateway (`LLM_BASE_URL`), or the endpoint the judges set in `LLM_BASE_URL` (CSCS possible) | check model card | DECIDED (Apertus mandatory); role split OPEN (D-021, D-022) |
| Candidate gate: read a ruling's matter where code cannot (`src/area_judge.py`, D-060) | Apertus 1.5 70B (instruct, thinking off) | `LLM_NAME` (gateway `apertus-v1-5-70b`) | Keera gateway, through `src/llm/` | as the core row | PROPOSED (D-060) |
| Light tasks: query translation, quick prioritisation, demo fallback | Apertus 1.5 8B | gateway `apertus-v1-5-8b`; Hugging Face `swiss-ai/Apertus-v1.5-8B` | Keera gateway, or the endpoint the judges set | check model card | OPEN (D-022); never excludes a ruling alone whatever the answer |
| Embeddings for search and similar rulings | pplx-embed-context-v1-0.6b | `<revision>`; query-side model to fix | local; weights downloaded at image build time and never committed (the template's `.gitignore` excludes weight files), so a **build-time** external dependency listed in the report's Target architecture | MIT | DECIDED if search uses embeddings (D-005); whether it does is OPEN (D-033) |
| Embedding baseline | bge-m3 | `<revision>` | local (weights downloaded at build time, as above) | MIT | OPEN (D-020) |
| Learned relevance score | logistic regression on signals + Apertus probability | trained artefact `results/models/<hash>` | local (scikit-learn) | n/a (our model) | OPEN (D-021, option B only) |
| Evaluation judge (optional) | open-weights, other family than Apertus | `<id>` | `<endpoint>` | `<licence>` | OPEN (`docs/EVAL.md` §4); used only with published κ |

`LLM_NAME` is "name and version of the model" (template `README.md`): the judges may set either size, in either form (gateway id or Hugging Face id). The client maps both forms, and the pipeline must complete when `LLM_NAME` is the 8B (`AGENTS.md` G3; D-032, Q-23).

**Allow-list of served models** (PROPOSED, D-032, Q-23). This is the single home of these ids: `AGENTS.md` G3 states the rule, and other files point here instead of listing them.
- The Apertus v1.5 ids, in both forms: gateway `apertus-v1-5-8b` and `apertus-v1-5-70b`; Hugging Face `swiss-ai/Apertus-v1.5-8B` and `swiss-ai/Apertus-v1.5-70B`. Any other form the gateway probe records (`results/gateway_probe.json`) is added here, and nowhere else.
- Plus the `LLM_NAME` the runner set, if it names an Apertus model (case-insensitive `apertus`, any id form); otherwise the run fails fast with a clear message (E1).
- Keera also serves `apertus-v1-5-8b-thinking` and `apertus-v1-5-70b-thinking` (measured 27 Nov, `docs/LESSONS.md` K1). We do not use them (thinking off), so they are not on the allow-list unless `LLM_NAME` names one. Keera serves no embedding model (K13).

Runtime checks:
- Every response: compare the `model` field (and the `x-keera-model` header when present) with the allow-list above (rule: `AGENTS.md` G3); log provider, served model, latency, tokens, `finish_reason`, cache hit. A missing header is logged, not fatal.
- `tests/test_models_registry.py` fails if the code references a model id that is not in this table.

## 2. Development tools (E2 and E6)

Each member fills their own rows: tool, every model actually used, and what for. Members are named by handle, as in `docs/EVENT.md` §7, never by name (G13).

| Member | Tool | Model(s) and version | Used for |
|---|---|---|---|
| `<handle>` | `<coding assistant>` | `<model, version>` | `<code, research, review…>` |
| `<handle>` | `<chat assistant>` | `<model, version>` | `<…>` |
| `<handle>` | `<IDE assistant>` | `<model, version>` | `<…>` |

## 3. Pre-event preparation

Research and preparation notes written before the event with AI assistants are declared here and in section 8 of `technical_report.md` (D-043, D-029): `<tool, model, purpose>`.
