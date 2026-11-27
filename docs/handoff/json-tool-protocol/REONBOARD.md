# Réonboarder un agent sur le protocole JSON

Ce fichier sert à lancer, ou relancer, l'agent qui développe le protocole JSON dans suva-NGA : la
première fois, après une nouvelle session, après une compaction ou sur une autre machine. Le prompt
est en anglais, comme le kit. Il complète `BOOTSTRAP.md` sur trois points :

- il trouve le handoff là où il est, commité dans `docs/handoff/json-tool-protocol/` ou décompressé
  dans `tmp/json-tool-protocol/` ;
- il établit d'abord, depuis le repo, où en sont les étapes 0 à 13 du brief, puis reprend à la
  première qui n'est pas faite ;
- il donne les écarts entre le handoff et le repo relevés le vendredi 27 novembre vers 21:00, que
  le handoff ne pouvait pas connaître.

Ouvrir une session de code à la racine du clone, avec les variables `LLM_*` dans `.env` (jamais
commité), puis coller le prompt tel quel.

## Prompt à coller

```text
You are joining, or rejoining, the suva-NGA repository (Suva challenge, HackApertus Zurich,
27-28 Nov 2026) as the agent that develops Apertus tool calling: the JSON tool protocol
(src/llm/tool_protocol/), its benchmark against native tool calling (eval/tool_bench/), and their
tests. The area is called tool-calling; the lead created it on 27 Nov (D-058, which lands in the
area's first PR). You may be its first agent or a later one: find out which before you change
anything.

0. Find the handoff. Use docs/handoff/json-tool-protocol/ if it exists, otherwise
   tmp/json-tool-protocol/ (git-ignored, never committed). Below it is called HANDOFF_ROOT. If
   neither exists, stop and ask the team member you work for: the archive
   json-tool-protocol_2026-11-27.zip unzips into tmp/. HANDOFF_ROOT holds HANDOFF.md (the detailed
   reference), BOOTSTRAP.md (the first-start procedure), this prompt (REONBOARD.md), NOTICE.fragment
   and reference/ (implementation v0.2.1, whose paths mirror the repo). The committed copy leaves
   out upstream/, reference/examples/ and smoke/; you never need them in the repo. Wherever the
   brief or BOOTSTRAP.md says tmp/json-tool-protocol/, read HANDOFF_ROOT.

1. Read, in this order: AGENTS.md, CLAUDE.md, docs/STATE.md, docs/EVENT.md, docs/DOCTRINE.md,
   docs/DECISIONS.md, docs/LESSONS.md, then your brief (docs/agents/tool-calling.md once it has
   landed, otherwise HANDOFF_ROOT/reference/docs/agents/tool-calling.md), then HANDOFF.md sections
   3, 5 to 12 and 14. Follow the onboarding protocol of AGENTS.md section 2. If you do not know the
   GitHub handle of the team member you work for, ask for it now.

2. Establish where the work stands from the repository, not from memory or from this prompt.
   Build a table of the brief's steps 0 to 13: done, in review, not started or blocked, each with
   its evidence.
   - Sources: git log on main and on the tool-calling/* branches; open and merged PRs
     (gh pr list --state all --search "tool-calling") when gh is available; docs/STATE.md.
   - Step 1 is done when docs/agents/tool-calling.md exists, AGENTS.md section 5 has the
     tool-calling row and the exclusions in the platform and evaluation rows, and
     docs/DECISIONS.md holds D-054 to D-058 (or the ids they were renumbered to).
   - Step 2 is done when src/llm/tool_protocol/ and eval/tool_bench/ exist, NOTICE holds the
     ArchAI MIT notice, and make check is green.
   - Step 4 is done when src/llm/client.py exposes chat_fn(model). Steps 5 to 13: the brief's
     "Done when" column.
   - Inputs: are D-055, D-056 and D-057 settled (DECIDED lines)? Has Q-23 named the judges'
     endpoint? Is DS3 available (docs/DATA.md, the crawl owner)? Has the team announced a
     benchmark slot (ask the team member)?
   Resume at the first step that is not done. Never redo merged work. If one of your branches is
   in review, answer its review before you start the next step.

3. Facts checked in the repo on Fri 27 Nov around 21:00 CET that the handoff does not state.
   Re-check each one: the repo moves.
   - make check runs `ruff check src tests`, `ruff format --check src tests` and pytest
     (testpaths ["tests"]), all through `uv run --frozen`. Ruff: line-length 120, target py312,
     rules E, F, W, I, B, UP. Python 3.12 or later.
   - Under these settings the import (step 2) needs, on the copied files:
     `ruff format` (28 of 34 files change, formatting only: the 263 reference tests still pass
     after it); `ruff check --fix --select UP017` (3 places, datetime.UTC); in
     tests/tool_bench/test_bench.py, turn the `strip = lambda ...` into a def (E731: after
     formatting, its noqa sits on the wrong line); in src/llm/tool_protocol/schema.py,
     `class Tier(str, Enum)` raises UP042: switch to StrEnum only if the whole suite stays green,
     otherwise keep it with `# noqa: UP042` and a one-line reason. Keep every SPDX and ArchAI
     header.
   - make check lints src and tests, not eval/. In the import PR, propose to platform (owner of
     the Makefile) to add eval to both ruff commands, or state in the PR that eval/tool_bench is
     linted only by the brief's D command.
   - tests/test_doctrines.py scans src/ and eval/ for gateway access outside src/llm/
     (LLM_BASE_URL, LLM_API_KEY, /chat/completions). The reference passes it: its only mention is
     a docstring inside src/llm/. tests/test_no_suva_personal_fields.py scans every file outside
     tmp/.
   - The dev dependency group holds pytest and ruff only. Add hypothesis and pytest-cov with
     `uv add --dev`; it changes uv.lock, which platform approves.
   - src/llm/client.py has LLMClient.chat(...) with its own replay cache and LIVE/REPLAY modes,
     and no chat_fn yet. Step 4 adds a chat_fn adapter on top of it. What its cache stores is
     D-057.
   - src/schemas.py: TriageCall.c_label is Literal["A", "B"] (D-055 option (a) today);
     SummaryCall, SummaryClaim and Signal exist. A contract changes only through a PR the
     platform owner approves.
   - docs/DECISIONS.md ended at D-053, so D-054 was free. docs/LESSONS.md ended at K16: ask the
     lead whether K17 and K18 are still reserved before you use K19 and K20.
   - Branches are named <area>/<short-topic>, so tool-calling/<topic>. Small PRs; the owner of
     the touched area reviews; the lead merges.
   - The repository is public: every push is published at once.
   - When the brief lands in PR 1 as docs/agents/tool-calling.md, replace its tmp/json-tool-protocol/
     paths with the handoff's committed path if it is committed, and replace its "The handoff
     itself" never-commit item with: never copy upstream/, examples/, smoke/ or the reference
     conftest.py into the code tree.

4. Rules:
   - Never commit what the brief's "Never commit" section lists.
   - No key, internal hostname or gateway URL in any file (G13).
   - No gateway call outside src/llm/ (G2).
   - No Suva text, DS7 text or Suva-derived data in fixtures or golden files.
   - No team member's name outside the places G13 allows.
   - No destructive command.
   - At most 3 sub-agents, no recursive delegation (D-023 while open).
   - Live calls stay within your concurrency share (D-030 while open).
   - The full benchmark runs only in a slot the team announced, outside the overnight run and
     before the feature freeze (Sat 12:00 CET, D-027).
   - A shared file changes only through a PR its owner approves (G7).
   - Never answer an open question in code: list it with its options and your recommendation.
   - When a step's input is missing, stop at that step and report it. Do not work around it.

5. Before your first change, post a plan: the status table of point 2, the next step, the open
   questions it touches with your recommendation, and what you need from the team member.
   After each PR, report as CLAUDE.md asks:
   - what changed;
   - the make check counts;
   - the make run result, once the protocol is called from make run;
   - the 3 real rulings used, from step 12 on;
   - every live call you made: how many, on which model;
   - the open questions you raised, with your recommendation;
   - the AGENTS.md section 7 boxes still pending, and why;
   - any golden rule (G1-G15) you could not apply.

6. Leave a clean handover for the next agent. Keep this area's line in docs/STATE.md current. When
   you stop in the middle of a step, write in your PR, or in a comment on it, what is done, what is
   left and the exact command to resume.
```
