# Technical report — `project name`, `team name`

A deeper write-up than the README: what you built, how it works, and what the
numbers say.

- **Challenge partner:** Suva
- **Challenge:** Identification of relevant Federal Court judgements and preparation of a legal summary
- **Event:** On-site Zurich
- **Team:** `team name` — `member`, `member`, `member`
- **Demo:** `link to video`

## 1. Summary

The problem, your approach, and the headline result in one paragraph.

## 2. Architecture

Components, data flow, and where each one runs. Put diagrams in `docs/` and
reference them here.

### Target architecture (mandatory)

**Deployable in a), b) and c).** The project is a cluster of containers (`docker-compose.yml`, runbook
`docs/DEPLOY.md`): PostgreSQL with pgvector, one app image for the loaders, the pipeline jobs and the app, and,
optionally, Apertus served by vLLM inside the cluster. The same files serve the three targets; only `.env` changes.

- **a) On-premise** — `make cluster-env && make cluster-up` on any Docker host (`linux/amd64`, no GPU needed).
  Apertus is reached through `LLM_BASE_URL`: the CSCS / Keera gateway or the organisation's own endpoint.
- **b) Air-gapped** — the images (`docker save`), the pinned base dataset and the Apertus weights are carried in.
  The `sovereign` profile serves Apertus on a local GPU with vLLM. The database and the model sit on an internal
  network with no route out; the fetch step checks the carried file by SHA-256 and makes no network call.
- **c) Sovereign Swiss cloud** — the same containers and a PostgreSQL service on a platform operated in
  Switzerland, with Apertus served in Switzerland (CSCS).
- **Transfer to Azure** (bonus) — configuration by environment variables only, one OCI image, standard
  PostgreSQL; the service mapping is in `docs/DEPLOY.md` §8. Azure is not presented as c).

External dependencies:

| | Build time (once, on a connected machine) | Runtime |
|---|---|---|
| Images | `python:3.12-slim`, `pgvector/pgvector` (PostgreSQL 17), vLLM for b); all pinned by digest | none |
| Packages | Debian (`make`, PostgreSQL client); Python packages pinned by `uv.lock` | none |
| Data | Hugging Face `voilaj/swiss-caselaw`, `data/bger.parquet` at a pinned commit, SHA-256 checked | none |
| Model | Apertus v1.5 weights, for b) only | the Apertus endpoint `LLM_BASE_URL` (inside the cluster in b) |

No other external service at runtime: no CDN, no telemetry (vLLM usage statistics off), no closed model.

## 3. Use of Apertus

- **Model:** `e.g. swiss-ai/Apertus-v1.5-8B`
- **How it is used:** inference | fine-tuning | evaluation | red-teaming | agents / tool use
- **Where it runs:** `local weights, hosted endpoint, ...`

Prompts, adapters, quantisation, serving stack — whatever a reader needs to
rebuild your setup.

## 4. Data

What you used, where it came from, and its licence. Flag anything personal or
non-redistributable, and keep it out of the repository (see `.gitignore`).
If data comes from human subjects or contains personal information, describe
how consent was obtained.

## 5. Limitations

Where it breaks, what you did not test, and known failure modes.

## 6. Reproducibility

What a judge needs to get your numbers back: hardware, runtime, seeds, and the
exact commit.

### How to run

> Draft by the platform owner, to finish with the pitch owner (`docs/agents/platform.md` step 8). Status on
> Fri 27 Nov: **skeleton**. The commands below work; the pipeline stages are stubs that print what they will
> do. This block is updated as stages land.

**Prerequisites:** git; either Docker with compose (images for `linux/amd64`, no GPU needed), or Python 3.12+
with [uv](https://docs.astral.sh/uv/). Network at runtime: the Apertus endpoint only.

**Configuration:** copy `.env.example` to `.env` and set the three variables the template imposes:

```
LLM_NAME      name and version of the model: an Apertus v1.5 id, 8B or 70B, gateway or Hugging Face form
LLM_BASE_URL  endpoint base URL (OpenAI-compatible)
LLM_API_KEY   your API key
```

They are needed for live calls only. A replayed run needs none of them.

**Run:**

```
make run            # end-to-end, then serves the app; SERVE=0 make run to stop after the pipeline
make check          # lint and tests
make smoke-llm      # optional: probe the endpoint, writes results/gateway_probe.json
```

With Docker instead of a local Python (the cluster, `docs/DEPLOY.md`):

```
make cluster-env
make cluster-up
```

`make cluster-env` generates the database secrets into `.env` (it never overwrites or prints a value).
`make cluster-up` builds the image, then runs the database, the schema, the base dataset, Suva's labels and
`make run`. The first run downloads the pinned base dataset once. Images are pinned by digest.

**Live or replayed:** how much of `make run` calls Apertus live is still open (D-032). The working default:
a small live slice when the `LLM_*` variables are set, recorded answers for the rest, and every output
labelled `LIVE` or `REPLAY`. The served model is checked on every answer; any Apertus v1.5 id is accepted in
either form.

**Expected duration:** `<to measure once the stages exist>`.


## License

Creative Commons Attribution 4.0 (CC-BY-4.0). All HackApertus projects are open-sourced.

## References
