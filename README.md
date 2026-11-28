# Hack Apertus Zurich — Challenge Partner: Suva

## 🎯 The Challenge

### Identification of relevant Federal Court judgements and preparation of a legal summary

`Add your team name`
<br>
<br>

Template repository for [Hack Apertus](https://hackapertus.ch/) submissions.
Every project keeps the same layout, so organizers and judges find the same
things in the same place.

Submissions must use the v1.5 Apertus model family.
The submission must comply with the [HackApertus T&C](https://hackapertus.ch/terms-and-conditions) and the [model and challenge requirements](https://hackapertus.notion.site/zurich-challenges-model-requirements)


## 🔧 Resources & Tools

Check our resources & tools page for more information:
[Resources & Tools](https://hackapertus.notion.site/zurich-resources-tools)

| Models           | URL                                      |
|------------------|------------------------------------------|
| Apertus v1.5 8B  | [huggingface.co/swiss-ai/Apertus-v1.5-8B](https://huggingface.co/swiss-ai/Apertus-v1.5-8B)  |
| Apertus v1.5 70B | [huggingface.co/swiss-ai/Apertus-v1.5-70B](https://huggingface.co/swiss-ai/Apertus-v1.5-70B) |

## The structure

Keep the files and directories as shown below — don't rename or move them.

| Path | What it is |
| --- | --- |
| `README.md` | The challenge description and submission requirements |
| `technical_report.md` | The deeper write-up: architecture, evaluation, limitations |
| `challenge_description.md` | Complete Challenge description incl. deliverables 
| `LICENSE` | Apache-2.0 |
| `src/` | Your code |

## Environment

- Include instructions for running the project in your technical report.
- Use the following environment variables:
```
LLM_NAME — name and version of the model
LLM_BASE_URL — endpoint base URL
LLM_API_KEY — your API key
```

### How to run this project

> Added by the team. Full instructions: [technical_report.md](technical_report.md), section 6 "Reproducibility", "How to run".

**Replay (the default, no key, no call to Apertus).** Needs git, Docker with compose, Python 3.12+ with [uv](https://docs.astral.sh/uv/), and Node for the UI build.

```
cp .env.example .env
make run
```

`make run` starts a local database, loads the rulings from the team's public dataset when the database is empty, scores them and writes the German and French summaries from the Apertus answers committed in `replay/llm/`, then serves Suva Scout on <http://127.0.0.1:8000>. Every line it prints is labelled `REPLAY` or `LIVE`. `SERVE=0 make run` stops before serving.

**Live (real Apertus calls).** Set the three variables in `.env`, then name how much to run:

```
LLM_NAME=      # an Apertus v1.5 id
LLM_BASE_URL=  # OpenAI-compatible endpoint; it must return log-probabilities (top_logprobs)
LLM_API_KEY=

make run-live ARGS="--limit 5"   # a smoke run: the first 5 rulings read live (scores not stored), at most 5 summaries
make run-live ARGS="--all"       # everything, live
```

**The six-schema data layer and its API** (`src/db/sql`, `src/layer1`, `src/layer2`, `src/api`, cluster in `docs/DEPLOY.md`): `make pipeline`, `make api`, `make cluster-up`. `make bridge` copies Suva Scout's scores into that database as its layer 2 and ranking step.

## 📦 Submission Requirements & Deliverables

The submission must:
1. follow the template repo and include all prerequisite files and definitions
2. run end-to-end when judges try to run it

### Git repo (URL)
- Create your repo from this template (**Use this template**).
- Keep the layout as it is: don't rename or move its files.
- Set the repo to PUBLIC (Settings --> Collaborators --> Manage Visibility)
- Submit the URL of YOUR Git repo (keep it to 'public').

### Technical Report (pdf)
- Update [technical_report.md](technical_report.md) in this repository with all the details for your submission.
- Upload a pdf of your technical report to the root of the repo, named as `TeamName_Report.pdf`.
- Format: pdf, max. 6 pages w/o references
- Submit the pdf of the technical report.

### Demo video (URL)
- Max. 2 min demo video of your prototype
- Add the link to the **Demo** field at the top of [technical_report.md](technical_report.md)
- Submit the URL of the video.

### Pitch deck (pdf)
- Max. 10 slides

## Getting started

1. Click **Use this template** to create your own repository.

## License

All Hack Apertus projects are open-sourced. Please check our Terms & Conditions for specific licensing details (6. What you build is open source): https://hackapertus.ch/terms-and-conditions

### Licences of this project (PROPOSED, D-048)

> Added by the team. The organisers' text above is unchanged. Status: PROPOSED until the lead has read section 6 of the Terms & Conditions (D-048; Q-24 to the organisers if unclear).

| What | Licence |
| --- | --- |
| Our code (`src/`, `tests/`, `eval/`, `Makefile`, Docker and CI files) | Apache-2.0 (`LICENSE`) |
| Our documentation: `docs/`, `AGENTS.md`, `CLAUDE.md`, `MODELS.md`, `technical_report.md`, the report PDF | CC-BY-4.0 |
| Datasets we create (published on Hugging Face as `suva-nga/bger-rulings`, not in git: `data/` is git-ignored) | CDLA-Permissive-2.0 |
| Suva's material from the template (`judgements/`, the pitch PDF) and the organisers' `challenge_description.md` | not ours: their own terms (`NOTICE`) |
| Other third-party material | its own licence (`NOTICE`) |

## Support

### FAQ
💡 https://hackapertus.ch/faq

### Contact

💬 In case you have questions, join the conversation on Discord. Alternatively, send an email to “hello@hackapertus.ch”.
