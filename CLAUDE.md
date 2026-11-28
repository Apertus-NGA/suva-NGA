# CLAUDE.md

> **Status: v0 PROPOSAL (27 Nov 2026), updated after the official template was read.** The shared rules live in `AGENTS.md`, imported below, so Claude Code and Cursor follow the same text.

@AGENTS.md

## Claude Code specifics

- Before any change, follow the reading order of `AGENTS.md` §2 (`docs/STATE.md`, `docs/EVENT.md`, `docs/DOCTRINE.md`, `docs/DECISIONS.md`, then your role brief in `docs/agents/`, and `docs/SUVA_DATA.md` if your task touches `judgements/`), and list the open questions your task touches with your recommendation. If the task spans two roles, say so and ask the lead.
- Sub-agents: no recursive delegation, at most 3 in parallel, a cheaper model for search and reading tasks, the highest effort only for targeted reviews. *(Default while D-023 is open in `docs/DECISIONS.md`.)*
- Use plan mode for any change that touches more than one owned area or a frozen contract (`src/schemas.py`, prompts, JSON schemas).
- Do not write notes, memories or scratch files into the repo. Decisions go into `docs/DECISIONS.md` through a PR; scratch work goes into `tmp/` at the repo root (git-ignored).
- Never call the Apertus gateway from a one-off script: use `src/llm/` (the client, or the probe before the client exists) so that every call is limited, cached and logged.
- Never commit anything from `data/private/`, `data/derived/` (while D-031 is open), `.env` or `tmp/`. Never rename or move a template file (imposed, D-039). Never delete one, and never edit `judgements/`, the pitch PDF or `challenge_description.md` (our rules, D-040, D-044; `AGENTS.md` G7). Append to `.gitignore`, never replace it (D-044).
- When you read `judgements/`, never copy its author section, staff codes or intranet links into any file, prompt, commit, log or message (D-051). Keep only docket, dates, quarter label, `Text DE`, `Text FR` and the bger.ch link (`docs/SUVA_DATA.md`). The one exception is the data layer's database, which may store the author field and the workbook's hyperlink target as data (D-051 as amended).
- When you finish, report: what changed, how it was tested (the 3 real rulings used), what `make check` and `make run` returned, and any rule of `AGENTS.md` you could not respect.
