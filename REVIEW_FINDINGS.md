# REVIEW_FINDINGS: final repository review (28 Nov 2026)

Branch `review/final-cleanup`, cut from `platform/e2e-cleanup` (4cfd955), which already holds `platform/e2e-run`
and the four triage branches. `origin/main` (635723c, PR #37: the lead's data layer, D-061 to D-071) is merged in as
the first step.

**Rule sources checked:** `challenge_description.md`, `docs/EVENT.md` (E1-E6, template rules T1-T13), `AGENTS.md`
(G1-G15, definition of done, git workflow), the DECIDED lines of `docs/DECISIONS.md` on main (D-061 to D-071).
**Review guideline:** there is no `REVIEW_GUIDELINES.md` on any branch; on the requester's instruction,
`docs/CLEANUP_HANDOFF.md` (an audit of 043ab5a) is used as the guideline, re-verified at HEAD (Appendix B).

**Baseline at 4cfd955 (commands run 28 Nov):**

| Command | Output |
|---|---|
| `uv run --frozen pytest -q` | 3 failed: `test_no_network_at_import`, `test_every_model_id_in_code_is_in_models_md`, `test_no_generated_file_contains_a_d051_value` |
| `uv run --frozen ruff check src tests --statistics` | `Found 295 errors.` (247 E501, 14 B008, 8 B905, 7 B006, 6 E702, …) |
| `make run` | every stage prints `STUB …`, then `run: skeleton only, no stage implemented yet`; exit 0 |
| `docker compose ps` | `suva-nga-db-1  postgres:16 … Up 9 hours (healthy)  127.0.0.1:54329->5432/tcp` (the compose file pins pgvector pg17; the running container is an older one) |

## 1. Decisions taken by the requester

| Question | Decision |
|---|---|
| Which data layer does the end-to-end run use? | First: port onto main's data layer (`src/db/sql`, D-061 to D-071). **Changed the same night: keep the working schema** (`db/migrations/001-005`) for the submission and remove the six-schema DDL from this branch (D-074). The port map stays as Appendix C; the start of the port is parked on branch `port/data-layer-wip`. |
| Review guideline | `docs/CLEANUP_HANDOFF.md`, re-verified (Appendix B). |
| UI features to verify | All: list and filters, detail and summaries, expert editing, add a judgement, language switch. |
| Shared files (G7) | Edits approved by the requester on behalf of the lead. |
| Suva author fields and intranet links in our exports, public HF dataset `suva-nga/bger-rulings` | **Accepted by the requester: public data, not a concern.** Recorded as a deviation from D-051 for the lead; not treated as a failure here. |
| Pausing between chunks | No pauses: implement every fix, report at the end. |

## 2. Choices that need the lead's confirmation

| # | Point | Choice |
|---|---|---|
| P1 | Decision-number clash between the branch and main | The branch's D-060 (layer-1 gate) and D-061 (relevance pipeline v1) became **D-072** and **D-073**; main's D-061 to D-071 keep their numbers. |
| P2 | Data layer | **D-074:** the submission keeps the working schema; D-061 to D-071 are superseded for it; their files are removed from this branch (still in git history, PR #37). Merging this branch into main undoes PR #37's files: the lead must agree. |
| P3 | Layer-1 code from two members | `src/courts.py` combines main's text gate and audit log with the branch's matter reading by name and the Apertus reading (merge commit `0addd4d`). |

## 3. Checklist: every rule and guideline item

Status at the end of this review. "Resolved" means fixed on this branch and checked by a command in §5;
"open" means it needs a human or is outside the repo, with the reason.

The per-item evidence (file:line at 4cfd955) is in Appendix A (rules) and Appendix B (guideline). The resolution
column is filled in §4 as each fix lands.

## 4. Resolution log

(Filled in as each commit lands; see the final section.)

## 5. Verification

(Filled in after the end-to-end run.)

---

## Appendix A: rules compliance audit (4cfd955)


Read-only. Nothing in the repo was modified and no network or LLM call was made. The pitch PDF was skipped because neither `pdftotext` nor `pypdf` is available, and PyMuPDF was not used.

**Commands run, with their output:**
- `uv run --frozen pytest -q tests/test_doctrines.py tests/test_template_layout.py tests/test_models_registry.py tests/test_no_suva_personal_fields.py`: **28 tests, 25 passed, 3 failed.**
  - `test_doctrines.py::test_no_network_at_import` failed. The cause is an ImportError, not network: `src/summarize/tally.py:13` runs `from summarize import blocking, flat, load_tables, operative_only, row_for`, and no module `blocking` exists.
  - `test_models_registry.py::test_every_model_id_in_code_is_in_models_md` failed on false positives: `config.py: data/bger.parquet`, `suva-nga/bger-rulings`, `docs/CH_BGer`, and `node.js`/`tsc` blobs. The test scans untracked `src/web/node_modules`.
  - `test_no_suva_personal_fields.py::test_no_generated_file_contains_a_d051_value` failed with 12 "author name pair" hits in `notebooks/01_eda.ipynb` (lines 502-600). The notebook is **untracked** and hidden only by `.git/info/exclude:9`, not by `.gitignore`.
  - `test_template_layout.py`: all passed.
- `SERVE=0 MODE=replay make run`: exit 0. Every stage printed `STUB ...`, then `run: skeleton only, no stage implemented yet`.
- `uv run --frozen ruff check src tests`: **295 errors** (247 E501, 14 B008, 8 B905, ...). `make check` is therefore red.

| ID | Rule (short) | Source (file:line of the rule) | Status | Evidence (file:line) | Fix needed |
|---|---|---|---|---|---|
| E1 | Apertus 1.5 does the core AI task | docs/EVENT.md:18 | pass | src/llm/config.py:87-92 rejects any non-Apertus `LLM_NAME`. Triage readings and summaries both go through `src/llm/client.py` (src/triage/readings.py:76, src/summarize/summarize.py:328-332). | none |
| E2 | Any dev tool or model allowed | docs/EVENT.md:19 | pass | n/a | none |
| E3 | Runtime: Apertus plus open-weights only, no closed or proprietary AI API | docs/EVENT.md:20 | pass | No openai/litellm SDK in src. The judge is eval-only (MODELS.md:17, src/llm/judge.py:7). The scorer is our own LR (MODELS.md:16). | none |
| E4 | Eval judges may be open-weights | docs/EVENT.md:21 | pass | MODELS.md:17-18 (gpt-oss-120b, DeepSeek, Qwen); src/llm/judge.py:7 refuses Apertus | none |
| E5 | Deployable on-prem, air-gapped or Swiss cloud | docs/EVENT.md:22 | unclear | Dockerfile and docker-compose.yml exist. The Dockerfile says "Runtime network: the Apertus endpoint only" (Dockerfile:2), but the app's Update button fetches bger.ch, HF and entscheidsuche at runtime (src/suva_app/updates.py:20-25, src/suva_data/sources/*). The report's target architecture is empty (technical_report.md:21-30). `uv sync --frozen` in the image installs the dev and research groups (pyproject.toml:39-41, Dockerfile:19): torch and the nvidia CUDA wheels. | Choose a/b/c and write it in the report. Declare the runtime crawl as an external dependency, or make it optional/off for air-gapped. Use `uv sync --frozen --no-default-groups` in the Dockerfile. |
| E6 | Every model, dev and runtime, with version and role, listed (MODELS.md + report) | docs/EVENT.md:23 | **fail** | The dev-tool rows are placeholders (MODELS.md:37-39) and so is pre-event prep (MODELS.md:43). `intfloat/multilingual-e5-large-instruct` is used in research/arm_c_embed.py:10 and research/arm_c_download.py:3 but is not in MODELS.md. The `apertus-v1-5-*-thinking` models are used in research (research/apertus.py:27, arm_k_thinking.py, arm_n_thinking2.py) while MODELS.md:25 says "We do not use them". The embedding revisions are `<revision>` (MODELS.md:14-15). The report has no model list (technical_report.md:34). | Fill §2/§3 per member. Add e5 and the thinking models as dev use. Pin revisions. Add report §3 and §8. |
| T1 | Follow template; prerequisite files present | docs/EVENT.md:32 | pass | tests/test_template_layout.py passes. README.md, challenge_description.md, technical_report.md, LICENSE, .gitignore, src/.gitkeep, judgements/ and the pitch PDF are all tracked. | none |
| T2 | Run end-to-end when judges run it | docs/EVENT.md:32 | **fail** | `make run` only prints STUB lines (src/cli.py:56-76, 70-75). `serve` is a stub too (src/cli.py:121, 139). The real pipelines (`make triage` → src/triage/pipeline.py, src/summarize/pipeline.py, src/suva_app/main.py) are not called by `make run`. A fresh clone has no data: `data/` is fully ignored (.gitignore:31). | Wire `make run` to ingest, then triage, summarise, export, serve. Supply a reproducible data path for a fresh clone (D-031/D-061: pinned HF files). |
| T3 | Repo public, kept public | docs/EVENT.md:33 | pass (documented) | docs/STATE.md:9 says public per the GitHub API, 27 Nov 18:12 | Recheck before submission. |
| T4 | Never rename or move template files | docs/EVENT.md:34 | pass | test_template_layout passes. `git log` shows judgements/ and challenge_description.md last changed in organiser commits that are ancestors of c6e50ba. | none |
| T5 | Placeholders filled: README team name, report title/Team, LICENSE copyright | docs/EVENT.md:35 | **fail** | README.md:7 `Add your team name`; technical_report.md:1 `project name`, `team name`; technical_report.md:9 Team line; LICENSE:189 `Copyright 2026 Your Team` | Fill these with the registered team name (D-045). |
| T6 | Run instructions in technical_report.md; uses LLM_NAME, LLM_BASE_URL, LLM_API_KEY | docs/EVENT.md:36 | partial / **fail** | The section exists (technical_report.md:57-92) but describes a skeleton: "pipeline stages are stubs" (technical_report.md:60-61). Expected duration is `<to measure>` (technical_report.md:92). The variables themselves are fine: src/llm/config.py:18, .env.example:5-7. | Rewrite once `make run` is real. Give DB, Docker and data steps and the duration. |
| T7 | Report filled under template headings; Target architecture a/b/c mandatory | docs/EVENT.md:37 | **fail** | Every section is still template text (technical_report.md:12-55): Summary, Architecture, Target architecture, Use of Apertus, Data, Limitations | Write all sections. Target architecture is mandatory. |
| T8 | `<TeamName>_Report.pdf` at the repo root, at most 6 pages | docs/EVENT.md:37 | **fail** | No `*Report*.pdf` at the root (`ls` found none) | Export and commit it. |
| T9 | LICENSE is Apache-2.0 | docs/EVENT.md:38 | pass | LICENSE:1-2; pyproject.toml:5 | none |
| T10 | Video link in the Demo field | docs/EVENT.md:39 | **fail** | technical_report.md:10 `link to video` | Add the URL. |
| T11 | Deck PDF, at most 10 slides; one slide on how Apertus is used | docs/EVENT.md:40,52 | unclear | Not in the repo and not required to be | Check at submission. |
| T12 | Submit repo URL, report PDF, video URL and deck on sprintd by Sat 14:30 | docs/EVENT.md:41,51 | unclear | Outside the repo | none |
| T13 | Diagrams in docs/, referenced from the report | docs/EVENT.md:34; technical_report.md:18 | **fail** | `docs/diagrams/` does not exist and the report references no diagram | Add an architecture diagram and link it in §2. |
| C1 | Deliverables: UI with original documents, sortable score, triage explanation, DE+FR summaries, "add judgement" | challenge_description.md:31-35,72 | partial | The UI and API exist (src/web/, src/suva_app/main.py:54-202: rulings, relevance, summaries, updates). There is no "add a judgement by docket" endpoint in main.py (only `/api/updates` ingest by date range). None of this is started by `make run`. | Add an endpoint for adding a judgement by docket or link (D-015). Serve the UI from `make run`. |
| D-043 | Report keeps headings; §7 Evaluation and §8 Model registry added | docs/DECISIONS.md:51 (branch) | **fail** | technical_report.md has no §7 or §8 (it goes from line 92 straight to License at 95) | Add both. |
| D-044 | .gitignore appended in a marked block, never trimmed | docs/DECISIONS.md:52 | pass | `git diff <initial> HEAD -- .gitignore` is 40 insertions and 0 deletions; marked block at .gitignore:29, 44 | none |
| D-045 | NOTICE says judgements/ and the pitch PDF are Suva's; third-party files listed | docs/DECISIONS.md:53 | partial | NOTICE:13-17 is fine, but NOTICE:22 says "None copied so far" while src/certs/digicert_global_g2_tls_rsa_sha256_2020_ca1.pem (DigiCert CA cert) and tests/fixtures/bger_lists/*.html (bger.ch pages) are third-party | List them in NOTICE. |
| D-048/README | Licence map: "Datasets we create (`data/public/`)" | README.md:97 | **fail** (inconsistent) | `data/` is ignored as a whole (.gitignore:31), so `data/public/` can never be committed. That contradicts AGENTS.md:82 ("data/public/ ... in git") | Narrow the ignore to data/private/, data/derived/ etc. (append-only, so add a `!data/public/` line), or update the map. |
| G1 | Identifiers never come from Apertus; code extracts and validates them; Apertus only chooses from a list | AGENTS.md:50 | unclear / partial | Summaries are free text from Apertus. Code then removes consideration refs that are not in the ruling (src/summarize/finish.py:89-100, 181-182) and checks articles (src/summarize/summarize.py:436-439). The bger.ch link and docket come from data. Whether BGE/ATF refs and dates in summaries are checked is not verified. | Make sure every id class (BGE, docket, date, article) is verified or rendered by code. D-067 on main requires citations as FKs. |
| G2a | Every LLM_BASE_URL call goes through src/llm/ | AGENTS.md:51 | **fail** | research/apertus.py:62-68 builds `LLM_BASE_URL + /chat/completions` with urllib directly. It is used by research/arm_a_lib.py, arm_b_lib.py, arm_f_icl.py, arm_h_more.py, arm_j_category.py, arm_k_thinking.py and arm_n_thinking2.py. The doctrine test only scans `src` and `eval` (tests/test_doctrines.py:12), so it misses this. CLAUDE.md:12 also forbids calling the gateway from one-off scripts. | Route research through `src.llm.client`, or move research out of the repo or declare it dev-only. Extend CODE_DIRS to `research`. |
| G2b | Test fails on any other access | AGENTS.md:51 | partial | The test exists (tests/test_doctrines.py:19-38) but covers only src/ and eval/ | Add research/. |
| G2c | Concurrency ≤ 16 team-wide, member share | AGENTS.md:51 | partial | src passes: per-member cap of 5 (src/llm/config.py:22, 94-97). research fails: `chat_many(workers=8)` by default (research/apertus.py:94; arm_k_thinking.py:20 and others). | Cap research at 5 or route it via src/llm. |
| G3a | No default for LLM_NAME, LLM_BASE_URL, LLM_API_KEY; live startup fails if one is missing | AGENTS.md:52 | pass | src/llm/config.py:78-85; tests/test_doctrines.py env_defaults and .env.example tests pass; .env.example:5-7 is empty | none |
| G3b | max_retries=0 in any SDK; one function classifies errors and decides retries | AGENTS.md:52 | pass (src) / fail (research) | src/llm/client.py:84-98 and 245 (no SDK, httpx direct). research/apertus.py:65-80 has its own 6-retry loop. | as G2a |
| G3c | Timeout on every network call | AGENTS.md:52 | pass | client.py:212; judge.py:96; bger_lists.py:180; entscheidsuche.py:75; hf_daily.py:67; research/apertus.py:68. `git grep "urlopen("` shows no call without a timeout. | none |
| G3d | Thinking mode off | AGENTS.md:52 | pass (src) / fail (research) | client.py:184-185, probe.py:84-85. research/arm_k_thinking.py and arm_n_thinking2.py deliberately use thinking models. | Declare as dev experiments (E6). |
| G3e | Exactly one system message | AGENTS.md:52 | pass | client.py:195-196 | none |
| G3f | finish_reason "length" is a failure, never parsed | AGENTS.md:52 | pass | client.py:270-289 (first-token logprob calls are exempted by design, :148-152) | none |
| G3g | Served model checked against the MODELS.md allow-list; header checked when present | AGENTS.md:52 | pass (src) | client.py:130, 265-287; src/llm/served_model.py loads it from MODELS.md. research/apertus.py has no check. | as G2a |
| G4a | Never send empty or placeholder text | AGENTS.md:53 | pass | client.py:197-199 | none |
| G4b | Reject "meta" outputs (preambles, refusals, requests for the text) | AGENTS.md:53 | **fail** | No meta or refusal detector in src/llm or src/summarize: `git grep -iE "meta.?output\|refus\|preamble"` finds nothing relevant | Add a meta-output check in the client or the summary finisher. |
| G4c | Count tokens; stay under LLM_MAX_INPUT_TOKENS; default from probe, reported | AGENTS.md:53 | partial | Estimate of 3 chars per token, budget 120k (client.py:79-81, 200-205; config.py:24). Not reported in the report. | Report the budget in §3 or §6. |
| G4d | Split by consideration; never truncate silently | AGENTS.md:53 | **fail** | Triage prompts cut text: `x[: reas_cap-4000] + "[... gekürzt ...]" + x[-4000:]`, `head[-1500:]`, `dispositive[:800]` (src/triage/reading_prompts.py:38-42, 71-73). The area judge excerpt is `text[:EXCERPT_CHARS]` (src/area_judge.py:93). These cuts are marked, not split. | Split by Erwägung, or record the cut as a declared design with a count of how often it applies. |
| G4e | Ruling text delimited as data; control tags neutralised | AGENTS.md:53 | partial | area_judge neutralises (src/area_judge.py:89-99). Triage readings delimit with `<urteil>` but do not neutralise (reading_prompts.py:41, 73). Summary prompts are not checked. | Apply the area_judge sanitiser in readings and summaries. |
| G5a | Nothing excluded without a counted, auditable reason code | AGENTS.md:54 | partial | The layer-1 gate gives reasons (src/courts.py:99-135; outer_gate.py:126). Only kept rulings are written to `predictions` (src/triage/pipeline.py:215-235), so the reasons for dropped rulings are not persisted for the UI or audit. | Persist a row and reason for every dropped ruling. |
| G5b | Never exclude on docket prefix alone | AGENTS.md:54 | **fail** | With `wrong_court` or `wrong_letter` and no text (`text_absent`), `kept` is False (src/courts.py:100-108, 120-121, 134). A ruling with no text is then dropped on its docket prefix alone. | Keep the ruling (or send it to Apertus) when the text is absent. |
| G5c | Every ruling of a candidate population gets a score and an explanation | AGENTS.md:54 | **fail** | Score and explanation exist for kept rulings only (src/triage/pipeline.py:215, 233; scorer.py:140) | Give dropped rulings score 0 and an explanation from the reason code. |
| G5d | Outside every window: `out_of_window`, no LLM call | AGENTS.md:54 | **fail** | `git grep out_of_window -- src` finds nothing | Implement it. |
| G6 | Done = called by `make run`, tested e2e on 3 real rulings, output stored and checked | AGENTS.md:55 | **fail** | `make run` calls no stage (src/cli.py:70-75). Triage is only on `make triage` (Makefile:35-36). Summaries and the UI are not on any make target. | Wire the stages into `make run`. |
| G7a | Template files never renamed, moved or deleted | AGENTS.md:56 | pass | test_template_layout passes | none |
| G7b | judgements/, the pitch PDF and challenge_description.md never edited | AGENTS.md:56 | pass | The last commits touching them (1046055, 445f4db) are ancestors of c6e50ba; the PDF has one commit | none |
| G7c | Shared files and template files change only by owner- or lead-approved PR | AGENTS.md:56 | unclear | PR approvals cannot be checked offline | none |
| G8 | At most 3 sub-agents, no recursive delegation | AGENTS.md:57 | unclear | Process rule, not checkable in the repo | none |
| G9a | Tests shown red first; assert on stored output and the prompt sent | AGENTS.md:58 | unclear | Needs PR history | none |
| G9b | Declare every mock | AGENTS.md:58 | **fail** (minor) | tests/test_bger_lists.py (26 fake or monkeypatch uses, 0 declarations) and tests/test_swiss_caselaw.py (12 uses, 0 declarations). Compare tests/test_llm_client.py:3 "MOCK DECLARED (G9)". | Add MOCK DECLARED docstrings. |
| G10a | Threshold written before measuring; 2 repetitions outside the replay cache | AGENTS.md:59 | partial | The judge results carry `thresholds` but `"repetitions": 1` (results/judge_metaeval_dev.json, results/judge_metaeval_dev_deepseek.json) | Run 2 repetitions. |
| G10b | Apertus never judges our headline metric; judge open-weights, other family, κ published | AGENTS.md:59 | partial | src/llm/judge.py:7 refuses Apertus and `human_kappa` is a threshold field. Whether κ is published: MODELS.md:17 says "not measured yet". | Publish κ before quoting judge numbers. |
| G11 | Every number in README, report or deck comes from results/ via `make claims` | AGENTS.md:60 | partial | No numbers in README or report yet (vacuous pass). `make claims` is a stub (src/cli.py:126). | Implement `claims` before numbers go in. |
| G12 | No destructive commands (`rm -r` outside tmp/, ...) | AGENTS.md:61 | pass (minor note) | Only Dockerfile:14 (apt lists), and `shutil.rmtree` of the code's own `.download` staging dir (src/suva_data/sources/swiss_caselaw.py:148, 158) | Optional: none |
| G13a | No key in code, prompts, commits or logs | AGENTS.md:62 | pass | The key-pattern grep found no hits. `.env` is untracked and ignored (.gitignore:2). `git ls-files \| grep -i env` → only .env.example and tests/test_env_settings.py. Client logs hash prompts and never log the key (client.py:339-347). | none |
| G13b | No internal hostname | AGENTS.md:62 | pass / unclear | The only real host is `gateway.keera.ch` in docs/EVENT.md:56, the public participant gateway, not internal. The SharePoint host is not in any tracked file except as the field name `sharepoint_url` (db/migrations/001_init.sql:112, docs). | Decide whether the gateway URL counts as internal. If unsure, drop it from docs. |
| G13c | Team names only on the report Team line and in the README team section | AGENTS.md:62 | **fail** (minor) | GitHub handles `member A`, `member B`, `member C` in docs/STATE.md:9. No real names in tracked files (grep of the authors' names). | Replace with roles. |
| G13d | Suva author fields, staff codes and intranet links in no committed file or output | AGENTS.md:62 | pass (tracked) / risk | Committed files pass: the only test hits are in the untracked notebooks/01_eda.ipynb, ignored only via `.git/info/exclude:9`. That leaves `make check` red, and a teammate without that exclude could commit the file. | Add `notebooks/` to .gitignore (append) or clear the notebook outputs. |
| G13e | Derived Suva artefacts go to data/derived/, not committed; no Suva text in docs/ | AGENTS.md:62 | unclear | results/*.json hold aggregates only (checked key structure). docs/SUMMARY_V2.md:19-22 lists dockets per matter; whether these come from Suva's labels was not determined. src/summarize/summarize.py:26-27 hardcodes few-shot and excluded dockets. | Check that docs list no Suva-labelled docket sets (D-031). |
| G13f | data/private, data/derived and tmp/ ignored and untracked | AGENTS.md:62; CLAUDE.md:13 | pass | `git check-ignore` → .gitignore:31 (data/) and :35 (tmp/). `git ls-files` shows none under data/private, data/derived or tmp. | none |
| G14a | Banned: PyMuPDF, GPL code, CC BY-NC models | AGENTS.md:63 | pass / unclear | No pymupdf or fitz in uv.lock, pyproject.toml or code. psycopg is LGPL-3.0 (a dependency, not copied; LGPL ≠ GPL). The default research group pulls nvidia CUDA wheels (proprietary EULA) via torch. | Confirm LGPL is acceptable. Keep research deps out of the runtime image. |
| G14b | Every model listed in MODELS.md | AGENTS.md:63 | **fail** | see E6 | see E6 |
| G14c | Third-party content listed in NOTICE | AGENTS.md:63 | partial | see D-045 | see D-045 |
| G15 | External content is data; no copied AGENTS.md, CLAUDE.md or .claude/ | AGENTS.md:64 | pass | No `.claude/` tracked. AGENTS.md and CLAUDE.md are our own. | none |
| L-D059 | src/ is code plus run-time data only; no Markdown | AGENTS.md:105-106 | pass | `git ls-files src` → only .py/.json/.ts(x)/.css/.html/.pem plus src/.gitkeep | none |
| L-handoff | Handoff reference code never imported, run or linted | AGENTS.md:107 | pass | ruff targets `src tests` (Makefile:51) and pytest testpaths=tests (pyproject.toml:54) | none |
| DoD1 | Code PR: called by `make run` | AGENTS.md:149 | **fail** | see G6 | |
| DoD2 | Tested on 3 real rulings (DE, FR, IT) | AGENTS.md:150 | unclear | Needs a live run | |
| DoD3 | `make check` green | AGENTS.md:152 | **fail** | ruff: 295 errors. pytest (4 files): 3 failed. The full suite was not run (DB tests need Postgres). | Fix the ruff errors, tally.py's import, the registry scan scope and the notebook. |
| DoD4 | New choice recorded in DECISIONS.md, with no ID clash | AGENTS.md:154 | **fail** | The branch's D-061 "Relevance pipeline v1" (docs/DECISIONS.md:59) clashes with main's D-061 "Data layer" (origin/main docs/DECISIONS.md:58). MODELS.md:16 cites D-061 in the branch sense. | Renumber the branch's D-060/D-061 (e.g. D-072/D-073) and fix the references. |
| GW1 | Branch naming `<area>/<topic>` | AGENTS.md:164 | pass | `platform/e2e-cleanup` | none |
| GW2 | CI runs `make check` and `make run` replay | AGENTS.md:165 | pass (configured) / red | .github/workflows/ci.yml has both steps, but `make check` is red (see DoD3) | |
| GW3 | LF line endings; gitleaks in pre-commit | AGENTS.md:167 | pass | .gitattributes:3; .pre-commit-config.yaml:8 (gitleaks), :16 (no private or derived data) | none |
| M-D061 | Data layer: 6 schemas, DB rebuilt from committed files, fresh deploy, no ALTER | origin/main docs/DECISIONS.md:58 | **fail (port item)** | The branch uses db/migrations/001-005, with ALTER at db/migrations/005_summary_workspace.sql:7 | Port onto src/db/sql. |
| M-D062 | Base dataset from pinned HF files; judges, clerks, legal_area, outcome and marked_for_publication never ingested | origin/main :59 | pass (fields) / unclear (set) | `git grep` finds none of those fields in src/suva_data or db/migrations. The HF pin and the twin rule were not verified. | Verify the pin during the port. |
| M-D063 | Scope label in_scope / out_of_scope / potentially; layer-2 score = 100·P(Ja)/(P(Ja)+P(Nein)); append-only | origin/main :60 | **fail (port item)** | The branch uses tiers and an LR score, writing `predictions.relevant` as a boolean (src/triage/pipeline.py:226-233, scorer.py) | Map to the assessments. If the LR is kept, settle the score form (D-021). |
| M-D064 | Versions V<maj>.<min>.<patch> per step; model ids from MODELS.md; LLM_NAME override warns, never blocks | origin/main :61 | **fail (port item)** | Branch version strings are like `outer_gate_area@1` (src/triage/outer_gate.py:28). A non-Apertus LLM_NAME raises ConfigError (src/llm/config.py:87-92), which is consistent with E1. | Adopt the versions. Reconcile "warn" with the E1 fail-fast. |
| M-D065 | Logs as data (spans, events, metrics); no key, prompt, D-051 value or name in logs | origin/main :62 | partial (port item) | JSONL `llm_calls.jsonl` with the prompt hashed (client.py:339-356). No spans or DB logs yet. | Port. |
| M-D066 | Expert reviews append-only and apart from the pipeline label | origin/main :63 | unclear | `/api/rulings/{id}/relevance` (src/suva_app/main.py:117); pipeline.py:63 ignores UI overrides for training labels | Check during the port. |
| M-D067 | Summaries: version = DE+FR pair → claims → citations FK to considerations; `suva_house` gate | origin/main :64 | **fail (port item)** | The branch has summaries per language via an ALTER-based workspace; no claims or citations tables, no `suva_house` | Port. |
| M-D068 | Presets in the DB (perspective 0-10, suva_house mandatory) | origin/main :65 | **fail (port item)** | No preset or perspective code in src (only the UI date presets) | Port. |
| M-D069 | SummaryCall gains `application` and `practice` | origin/main :66 | **fail (port item)** | src/schemas.py:205 `c_section: Literal["facts","law","outcome"]` | Make the additive schema change in its own PR. |
| M-D070 | Considerations from HF `erwaegungen_paragraphs`, versioned splitter, primary at ≥99%/≥98% | origin/main :67 | **fail (port item)** | `git grep erwaegungen_paragraphs -- src` finds nothing | Port. |
| M-D071 | uuid5 ids, prompts in DB, least-privilege roles, append-only triggers, DB tests in CI | origin/main :68 | **fail (port item)** | No uuid5 in src. CI has no `db` job (.github/workflows/ci.yml has one job). | Port. |

### Failing items by severity

**Critical. These block eligibility or "runs end-to-end"; fix before submission:**
1. **T2 / G6 / DoD1:** `make run` and `make serve` are stubs (src/cli.py:56-76, 121). Nothing real runs end to end, and a fresh clone has no data.
2. **E6 / G14b:** MODELS.md dev-tool and pre-event rows are blank. e5-large-instruct and the thinking models used in research are undeclared. The report lists no models. Breaking E6 removes prize eligibility.
3. **T7 / T8 / T10 / D-043:** the report is still the template text: the mandatory Target architecture section, the Demo link, §7 and §8 are missing, and there is no `<TeamName>_Report.pdf`. E5 cannot be shown until Target architecture is written.
4. **T5:** team-name placeholders in README.md:7, technical_report.md:1/9 and LICENSE:189.

**High. These break golden rules or the CI gate:**
5. **DoD3:** `make check` is red: 295 ruff errors; tally.py's broken import (`from summarize import blocking`); the registry test scans node_modules; the untracked notebook holds D-051 author names.
6. **G2a / G2c / G3b-g:** research/apertus.py calls the gateway directly, with its own retries, 8 workers and no served-model check. The G2 test does not scan research/.
7. **G5b / G5c / G5d / G5a:** a ruling with no text is dropped on its docket prefix alone (src/courts.py:134). Dropped rulings get no score or explanation row. `out_of_window` is not implemented.
8. **G4b / G4d / G4e:** no meta-output rejection; triage prompts truncate instead of splitting by consideration; readings do not neutralise control tags.
9. **DoD4:** the branch's D-060/D-061 IDs clash with main's D-061 (data layer).

**Medium. Port items from main's D-061..D-071, needed for the data-layer migration:** M-D061, M-D063, M-D064, M-D067, M-D068, M-D069, M-D070, M-D071 (and M-D065 partial).

**Low:**
10. **G13c:** GitHub handles in docs/STATE.md:9.
11. **G9b:** undeclared fakes in tests/test_bger_lists.py and tests/test_swiss_caselaw.py.
12. **D-045 / G14c:** the DigiCert pem and the bger.ch HTML fixtures are not in NOTICE.
13. **README licence map:** it names `data/public/`, which `.gitignore:31` makes uncommittable.
14. **T13:** no docs/diagrams.
15. **C1:** no "add a judgement by docket" endpoint.
16. **G10a:** judge evaluations ran 1 repetition, not 2.

---

## Appendix B: CLEANUP_HANDOFF.md re-verified at 4cfd955


Branch `platform/e2e-cleanup`. This was a read-only check: no repo file or git state was changed. `npm run build` rewrote the git-ignored `src/web/dist`, which already existed; `git status` is clean afterwards. `git diff 043ab5a HEAD --stat` shows that only `docs/CLEANUP_HANDOFF.md` changed, so the handoff's line numbers still apply at HEAD.

Status key: **still-true** (holds as written), **changed** (true when written, different now), **wrong** (false or incomplete even at 043ab5a). "Safe to delete?" applies only to deletion rows.

### 0. Context the handoff does not have (read this first)

| ID | Finding | Evidence | Recommended action |
|---|---|---|---|
| X1 | `origin/main` is **5 commits ahead** of HEAD and is not merged: `4c246a8` "Record why every ruling is kept or dropped" (src/courts.py +631/-55 lines, tests/test_courts.py, docs/LAYER1.md, pyproject.toml, uv.lock), `93704a2` PostgreSQL DDL in `src/db/` (6 schemas, deploy.py, tests/sql/*), Makefile `db-*` targets, a CI db job, and `4596663` decisions D-061 to D-071. | `git log HEAD..origin/main`; `git diff --stat HEAD...origin/main` (40 files, +6506) | Merge `origin/main` into the branch **before** any cleanup step. Every `courts.py` line reference in the handoff (§6, §7, §8) will move. The new layer-1 JSON log also partly answers §8 step 2 ("dropped rulings are stored nowhere", G5). |
| X2 | **Two different D-061 entries.** At HEAD, D-061 is "Relevance pipeline v1 (triage MVP)", PROPOSED (docs/DECISIONS.md:59). On origin/main, D-061 is "Data layer, 6 schemas", DECIDED (origin/main docs/DECISIONS.md:58), and D-062 to D-071 exist there too. The handoff cites D-061 throughout as the scorer decision. | `git show origin/main:docs/DECISIONS.md` | Renumber one of the two when merging. Ask the lead which one keeps D-061. |
| X3 | **Two database schemas.** HEAD has `db/migrations/001..005_*.sql` (applied at app startup). origin/main adds `src/db/sql/00..95_*.sql` with a different six-schema design (`corpus`, `triage`, `gold`, `summ`, `ops`, `audit`). The handoff's §7 target layout and §8 step 0 assume only `db/migrations`. | `ls db/migrations`; origin/main `src/db/sql/` | Ask the lead which DDL wins before wiring `make run`. |
| X4 | Five more local worktrees exist under `tmp/` (`classifier-wt`, `e2e-wt`, `gate-wt`, `mvp-wt`, `outer-gate-wt`). None has commits that HEAD lacks. | `git worktree list`; `git rev-list --count HEAD..<branch>` returns 0 for each | No action needed; they are safe to prune later (by a human, per G12). |

### 1. §3: the three failing tests

`uv run --frozen pytest -q` gives the same **3 failed** as the handoff. pytest printed no "N passed" summary line; the progress dots ran to 100%.

| ID | Claim | Status | Evidence | Recommended action |
|---|---|---|---|---|
| T1 | `test_no_network_at_import` fails because `src/summarize/tally.py:12-15` catches only `ModuleNotFoundError`, while `summarize` resolves to a namespace directory and raises `ImportError`. | still-true | tests/test_doctrines.py:88-102; error is `ImportError: cannot import name 'blocking' from 'summarize' (unknown location)` at tally.py:13 | Delete tally.py (see D7). |
| T1b | Implied: deleting tally.py makes the test pass. | **wrong** | Importing each module of `src/` separately: only two fail, `src.summarize.tally` and **`src.suva_data.__main__`**. The second is `raise SystemExit(main())` at import (src/suva_data/__main__.py:3), so argparse exits with code 2 (`the following arguments are required: command`). Importing all modules except tally in one process still exits 2. | The test will stay red after tally is removed. Either exclude `__main__` modules from the test's module list (tests/test_doctrines.py:90-93), or guard `__main__.py` with `if __name__ == "__main__":`. This is a test or source change, so ask first. Do not loosen the assertion. |
| T2 | `test_every_model_id_in_code_is_in_models_md`: the last alternative of `MODEL_ID` (tests/test_models_registry.py:20) matches `bge` (`data/bger.parquet`, `suva-nga/bger-rulings`) and `embed` (`docs/CH_BGer`), and `scanned_files` walks node_modules. | still-true | 6 hits: config.py:94 `data/bger.parquet`, config.py:98 `suva-nga/bger-rulings`, swiss_caselaw.py:28 `data/bger.parquet`, entscheidsuche.py:403 `docs/CH_BGer`, plus `node.js` (a base64 blob) and `tsc` (`internal/abi.Name.IsEmbedded`) under node_modules. scanned_files reads **6,878** node_modules files (:28-30). | Fix as proposed: skip `node_modules`, and require `bge-` or a word boundary. Do not add the strings to MODELS.md. |
| T3 | `test_no_generated_file_contains_a_d051_value`: saved output of the gold-summary author crosstab in `notebooks/01_eda.ipynb`, lines 502-600. Notebook is untracked through `.git/info/exclude`. | still-true (one precision) | 12 hits at :502-600. The cell is cell index 9 (`execution_count` 5), whose source is `display(pd.crosstab(S["author"], ...))`. `git check-ignore` gives `.git/info/exclude:9:notebooks/`, and `git ls-files notebooks` is empty. | The notebook's owner clears that cell's output. Leave the test unchanged. |

Other §1 checks: ruff reports **295 errors** (247 E501, 14 B008, 8 B905, 7 B006, 6 E702, 5 UP035, 4 I001, 2 E741, 1 UP012, 1 F401), of which 118 are in src/suva_data and 28 in src/suva_app; `ruff format --check` reports **27 files**. Both match the handoff. `make run` was **not executed**: the permission classifier refused it. Reading src/cli.py:56-75 and :120-139 confirms it prints STUB.

### 2. §6: deletion candidates

Author counts come from `git log --format='%an' -- <path> | sort | uniq -c` at HEAD. "Refs" means references found by grep over src, eval, tests, Makefile, pyproject, CI, Dockerfile, docs and the local notebooks, excluding node_modules, .venv, .git, tmp and the handoff itself.

| ID | Item | Handoff claim | Status | Evidence (refs found) | Authors (commits) | Recommended action | Safe to delete? |
|---|---|---|---|---|---|---|---|
| D1 | `research/` (42 .py, 10 notes in `research/updates/`; also untracked `cache/`, `out/`) | Nothing imports it; no doc cites it; drop the `research` group and `default-groups`, and `research/cache` from the D-051 test | **wrong in part** | No import from src, eval, tests, Makefile, CI or Dockerfile. But: (a) src/suva_app/queries.py:8 cites `research/common.py` in a docstring; (b) the local **`notebooks/02_relevance_research.ipynb:1790` does `sys.path.insert(0, "../research")`**, and :35 and :3142 point at `research/out` and the reproduce steps; (c) pyproject.toml:28-32 and :43, uv.lock:2678, tests/test_no_suva_personal_fields.py:32, .gitignore:66-67. Its models include `intfloat/multilingual-e5-large-instruct` (not in MODELS.md) and `BAAI/bge-m3` (MODELS.md:15 lists only `bge-m3`). | member D 2 | Ask the notebook's owner first: deleting it breaks notebook 02. Fix the queries.py:8 docstring at the same time. If research is kept, declare the e5 model in MODELS.md (G14). Dependency change: ask first. | **ask** |
| D2 | `docs/handoff/json-tool-protocol/` (47 files) | Not implemented; only docs/STATE.md:31 cites it | still-true (with a caveat) | Only docs/STATE.md:31 cites it, and that line says "D-058 pending its first PR". **D-058 does not exist in docs/DECISIONS.md at HEAD.** | member E 2 | It is a teammate's planned feature: ask its author or the lead whether D-058 is still planned. | **ask** |
| D3 | `docs/TRIAGE_OUTER_GATE.md` | Marks itself superseded | still-true | Its :3 says "SUPERSEDED as the gate by D-060". Still cited by docs/TRIAGE_SIGNALS.md:4 and src/triage/outer_gate.py:16. | member D 2 | Delete together with outer_gate.py (D8), then fix TRIAGE_SIGNALS.md:4. | yes, once D8 is done |
| D4 | `docs/TIPS_LAYER1_FILTER_HANDOFF.md` | Its paths do not exist | still-true | `handoff/layer1-filter`, `population-tf`, `finetune/` are missing. Cited only by docs/TRIAGE_OUTER_GATE.md:5 and :105. | member E 1 | Teammate's handoff: tell its author before deleting. | **ask** |
| D5 | `docs/SUMMARY_MEASUREMENT.md`, `docs/SUMMARY_V2.md` | Describe the legacy runner; move the numbers first | still-true | Cited by docs/STATE.md:29-30, docs/agents/summarise.md:11, and by each other | MEASUREMENT: member C 4, member E 1; V2: member C 1 | Move the numbers first, then fix STATE.md and summarise.md. | ask (author) |
| D6 | `src/summarize/v1/` | Imported only by tests/test_summary_prompts.py:5-6 | still-true | Also mentioned in docstrings at src/summarize/prompts.py:3 and v2/prompts.py:3. v1/prompts.py:66 imports `anchors`, `directions`, `order_of`, `outcome_sentence` and `required_forms` from summarize.py, so it must go **before or with** D8b. | member C 1 | Delete it, along with the v1 cases in test_summary_prompts.py. That edits an existing test, so ask first. | yes (test edit: ask) |
| D7 | `src/summarize/tally.py` | No caller; broken on import; needs `data/trial/holdout10.txt` | still-true | No importer. Its only `tally` refs are internal (:75, :127). | member C 3 | Delete. On its own this does **not** make T1 green (T1b). | yes |
| D8b | Legacy path in `summarize.py`: `_gate`, `load_tables`, `row_for`, `gold_body`, `EXCLUDED`, `summarize()`, `main()` | Superseded by pipeline.py | still-true | Each is used only inside summarize.py (:708-731) and by tally.py. pipeline.py:203 and workspace.py:56 use `load_env`, `chat` and `review`, which are **not** on the list. `load_tables` is the only reason pandas is imported here (:340). eval/judge/data.py still expects that legacy output's `"generated"` key. | member D 3, member C 5 | Delete with D6 and D7. Also update the JUDGE.md §6 example. Shared author: tell member C. | yes, after D6 and D7 |
| D8 | `src/triage/outer_gate.py` except `classify_area` and `header_subject` | `outer_gate()`, `OuterGateDecision`, `measure` and `net_decision` are used only by tests/test_outer_gate.py | still-true | src/signals/structural.py:24 imports the two helpers. tests/test_outer_gate.py:12 and many lines use `og.outer_gate`. It is the only production user of `schemas.NetDecision` (outer_gate.py:26). | member D 1 | Move the readers to `areas.py`, then delete the file and its test. Note that `areas._CUT` splits on `[(,;]` while outer_gate splits on `(`, so moving changes behaviour: write a test first. | yes, after the readers move |
| D9 | `src/bger_news.py` | Shim for the local notebook and tests/test_bger_lists.py:379-395 | still-true | notebooks/01_eda.ipynb:42 and :1125-1130 do `import bger_news`. Its docstring (:3) says it is kept for the notebooks. | member D 2 | Ask the notebook's owner. Deleting it breaks notebook 01 and two test cases. | **ask** |
| D10 | `src/suva_app/stub.py` | Used only by tests/test_app_queries.py; remove it together with the `stub_scores` facet | still-true, with an omission | It is also a **manual CLI** (`python -m suva_app.stub` and `--remove`, stub.py:3-4) that seeds placeholder predictions. The facet path is queries.py:244, src/web/src/lib/api.ts:44, App.tsx:94, Sidebar.tsx:6, :9 and :39, and i18n `app.placeholderScores`. | member D 1 | Remove all of it together: backend, facet, prop and i18n key. First check that nobody's local database still holds stub predictions (`stub.remove` is the clean-up). | yes (as one change) |
| D11 | `src/schemas.py`: 9 of 12 contracts unused | Production imports only `Evidence`, `Signal`, `NetDecision` | still-true; changes after D8 | structural.py:23 imports `Evidence` and `Signal`; outer_gate.py:26 imports `NetDecision`. After D8, production uses only **2** of 12. `triage_call_schema` (:265) is used only by tests. origin/main D-069 plans an **additive change to `SummaryCall`**, so that contract has a planned future use. | member E 1 | Shared file (G7), and the lead has a pending decision on it: do not delete any contract. | **ask** (lead) |
| D12a | `Scorer.threshold`, `n_train`, `n_positive` | threshold is reported but never applied | still-true | threshold is written to results at triage/pipeline.py:173 and :205 but never used for the cut (`promote` at :155-160 does the cut). `n_train` and `n_positive` are read nowhere. | member D | Drop `n_*`. Keep threshold until D-046 settles which cut is reported, or rename it. | n_*: yes; threshold: ask |
| D12b | `reading_prompts.AREA` (:64) | unused | still-true | defined only | — | Delete. | yes |
| D12c | signals `suva_appellant`, `bench_size` | computed, not in FEATURES | **wrong in part** | `bench_size` feeds `single_judge` and `five_judges` (structural.py:101-104), and both are in FEATURES (scorer.py:27, :31). tests/test_structural_signals.py:63-107 assert both signals. | — | Keep the `bench_size` computation. Dropping it as an output signal means editing tests, so ask. | **no** (bench_size), ask (suva_appellant) |
| D12d | `courts.gate_record`, `passes` | unused | **wrong in part** | Used by tests/test_courts.py:4, :17 and :73-94, and by the courts.py self-check (:210-236). origin/main rewrites courts.py and test_courts.py. | member D 3 (courts.py) | Decide after merging origin/main. | **ask** |
| D12e | `bger_lists.fetch_lists` (:418) | unused | still-true | No caller in src, eval or tests | — | Delete. | yes |
| D12f | `workspace.decide_relevance` (:284) | unused | still-true | main.py:121 calls `feedback.decide_relevance` | — | Delete. | yes |
| D12g | `lib/filters.ts:106` `sameFilters` | unused | still-true | defined only, no import | — | Delete. | yes |
| D12h | GET `/api/rulings/{id}` (main.py:102), "if the UI keeps using /workspace" | UI does not call it | still-true, but **the recommendation is harmful** | It is the **only** route that returns the score explanation (queries.py:158-181 `explanation`). `/workspace` (workspace.py:111-147) does not include it. The UI shows no reasoning (U8). | — | Do not delete it. Add `explanation` to `/workspace`, or have the UI call this route. | **no** |
| D13 | `courts.write_layer1`/`main` and `area_judge.main` read `data/cache/rulings.parquet` (55 rows, no `subject`) | still-true | `pyarrow` reads 55 rows, `subject` column absent; courts.py:262-271 | — | Decide after the origin/main merge, which changes courts.py. | ask |

### 3. §7: duplicated logic and path patches

| ID | Claim | Status | Evidence | Recommended action |
|---|---|---|---|---|
| L1 | UV/MV/IV regexes duplicated, and the subject cut differs (`[(,;]` against `(`) | still-true | areas.py:20-49 (`_CUT` :35); outer_gate.py:36-54 | Fold into areas.py. |
| L2 | Suva regex at courts.py:46 and structural.py:28 | still-true (approximate) | courts.py:46-49 `_TEXT_TERMS` (suva, cna, insai, uvg…, which is wider); structural.py:28-31 `_SUVA` | These are two different regexes, so this is not a pure duplicate. Merge only with a test. |
| L3 | Reasoning-heading regex at structural.py:33 and reading_prompts.py:16 | still-true | structural.py:33-36 `_BODY_START`; reading_prompts.py:16-19 `RE_REASON` | Fold. |
| L4 | "Core ruling" defined twice | still-true | triage/pipeline.py:76 excludes single judges; :145 and :156 do not | Define once. Write a failing test first: this inconsistency is a real bug. |
| L5 | Outcome detection in four places | still-true | summarize.py:403-430 (`outcome_sentence`, `outcome_of`), :215 `order_of`; finish.py:103 `outcome_kind`; tally.py:71 `kind_of`; eval/judge/perturb.py:27 `OUTCOME_SENTENCE` | Removing tally leaves three. |
| L6 | Abbreviation maps in five places | still-true | summarize.py:374-400; finish.py:21-29; eval/judge/checks.py:12-15; v2/glossary.json; eval/judge/system_prompt.txt | — |
| L7 | Three `.env` readers | **wrong (there are four)** | cli.py:35; summarize.py:45; llm/judge.py:43; **and suva_data/config.py:16-50 (`setting`)** | Keep `suva_data.config.setting`: it is the only one with a missing-file check and `.env.local`. |
| L8 | triage/pipeline.py uses raw psycopg with its own default | still-true | :35 and :255 | See defect 1. |
| P1 | Five path patches, plus three import styles | **wrong (incomplete)** | The listed sites are all present: courts.py:26-29 and :269; summarize.py:16-19, :36-39, :326-328; summarize/pipeline.py:37-38; v2/prompts.py:14-20; suva_app/workspace.py:17-18. **Missed:** `src/summarize/prompts.py:7` (`if __package__:`) and tally.py:12-15. That makes 8 patch sites in 6 files (7 after tally is deleted), plus 2 `__package__` switches. | Include prompts.py:7 in step 2. |
| P2 | pyproject.toml:39 builds only suva_data and suva_app | still-true | pyproject.toml:39 | Note: because the editable install puts `src/` on sys.path, both `summarize` and `src.summarize` resolve. That is the root of T1. |

### 4. §8: the ten defects

| # | Defect | Still present? | Evidence | Recommended action |
|---|---|---|---|---|
| 1 | Triage DB default `postgres:suva@` against `suva@`; `make triage` does not read `.env` | yes | triage/pipeline.py:35 and :255 (reads `DATABASE_URL` from the environment only); suva_data/config.py:65; docker-compose.yml:16; Makefile:35-36 | Use `suva_data.db.connect()`. Failing test first. |
| 2 | `summarize.load_env()` crashes when `.env` is missing | yes | summarize.py:45-47 (no exists check); workspace.py:55-57; .dockerignore excludes `.env` | Failing test first. |
| 3 | `ConfigError` gives 500 instead of 502 | yes (by reading) | main.py:138-147 maps `NotFound`, `ValueError` and `SystemExit`. `ConfigError(RuntimeError)` (llm/config.py:27) escapes, and summarize.chat:325-336 catches only `LLMError`. main.py has no other exception handler. Not reproduced. | Failing test with TestClient. Note that **no test uses TestClient at all** (N9). |
| 4 | Expert overrides fall out of training | yes, with a correction | triage/pipeline.py:55-63 returns `None` for `expert_override`. **Correction:** `relevance_events` is read by the learning page (queries.py:275) **and** by suva_data/reconcile.py:297. `make refit` is a stub (cli.py:120-127). | D-066 on origin/main says expert reviews "feed the next version's training tagged `expert`" and "never change the delivered list". Settle with the lead. |
| 5 | Dockerfile runs `uv sync --frozen` before `COPY . .`; default groups pull the research packages | yes | Dockerfile:18-21; pyproject.toml:43 `default-groups = ["dev","research"]`; uv.lock:2610 (sentence-transformers → **torch**, uv.lock:2802). There is no Node, so no UI. `CMD ["make","run"]` exits after the stubs. | Use `uv sync --frozen --no-dev --no-install-project`, then `COPY`, then sync again. Add a Node build stage. |
| 6 | Smoke runs with `--limit` overwrite the results file | yes | triage/pipeline.py:258 guards only `write`; :270-271 always write `RESULTS` | Failing test first. |
| 7 | pandas is a dev dependency but imported at runtime | yes | pyproject.toml:24 (dev group only); courts.py:189; area_judge.py:196; **also summarize.py:340** (`load_tables`, which disappears with D8b) | Ask before moving it to the main dependencies. |
| 8 | `metaeval kappa` ignores `--tag`; `run` overwrites the stored file; committed result is v2 while code is v3 | yes | metaeval.py:243-249 reads `metaeval_{split}.jsonl`. `kappa` has no `--tag` argument at all (:283 adds it to `run` only), and a tagged sheet name makes `split` the tag (:245). results/judge_metaeval_dev.json `rubric = judge-v2`; rubric.json `judge-v3`. | — |
| 9 | New rulings stay unassessed after `POST /api/updates` | yes | suva_app/updates.py:20-24 ingests only | — |
| 10 | Ruling-specific code in the generation path | yes | summarize.py:573-663 `problems()` is used only for `8C_78/2025` (:668, :674); `anchors` (:79-98) holds phrases from a few rulings. workspace.py:268 calls `summarize.review`, so the 8C_78 branch is live in the app. | — |

### 5. §10: stale documentation (spot checks)

| Doc | Handoff claim | Status | Evidence |
|---|---|---|---|
| docs/ARCHITECTURE.md | Target design only; never mentions courts.py | still-true | 0 hits for `courts.py`; :29 is S10 Export |
| docs/STATE.md | :20 "not merged, not pushed"; :26 "73 passed"; :27 every stage a stub; :28 next step; :32 `data/cache/layer1.parquet` | still-true, **except :27** | :27 still describes `make run` correctly (src/cli.py:56-75 is all stubs). The stale part is only that `triage` is now real. data/cache holds only gold_summaries.parquet and rulings.parquet. :31 cites D-058, which is missing from DECISIONS.md. origin/main changes STATE.md by 5 lines. |
| AGENTS.md §4-6 | Map names paths that do not exist | still-true | src/crawl, src/summarise, src/verify, src/api, src/ui, prompts/, expected/, data/public/, docs/diagrams/ and src/summarize/glossary.json are all missing |
| docs/agents/triage.md | "v0 PROPOSAL"; promises triage_validation.json and ranked_q2_2026.csv | still-true | :3, :24, :25 |
| docs/agents/summarise.md | Calls src/summarize "the probe" | still-true | :11 |
| docs/LAYER1.md | :3 wrong parquet path; 6,055 rulings | still-true at HEAD; **origin/main edits LAYER1.md (+35/-?)** | :3 cites `data/tables/rulings.parquet`; data/tables has no rulings.parquet. Re-check after the merge. |
| docs/TRIAGE_SIGNALS.md | :4 "outer gate"; :61 contradicts scorer.py:93 | still-true | :61 says unknown publication "must be treated explicitly"; scorer.py:93 `signals.get("proposed_for_publication") is True` folds unknown into False |
| docs/DATA_LAYER.md | §8 commands load/reconcile/attach do not exist; §9 Postgres 16 with port not published | still-true | :238-239; :44 and :321 "Postgres 16"; compose uses pgvector pg17 on 127.0.0.1:54329. The CLI has fetch, build, verify, dump, export, ingest, pull (suva_data/cli.py:258-268). |
| README.md, technical_report.md | Template placeholders | still-true | README.md:7 `Add your team name` |
| MODELS.md | Judge row "not measured yet" | still-true | :17 |
| NOTICE | "Third-party code: none" omits src/certs | still-true | NOTICE:19-22; src/certs/digicert_global_g2_tls_rsa_sha256_2020_ca1.pem |
| Makefile:2, src/cli.py docstring | Say "skeleton" | still-true | Makefile:2; cli.py:3 |
| docs/EVAL.md:111 | Five answer levels against two in the code | still-true | :111 |

### 6. New findings the handoff missed

### 6.1 Broken imports and dead code

vulture is not installed, so these findings come from grep and an AST scan.

| ID | Finding | Evidence | Recommended action | Safe to delete? |
|---|---|---|---|---|
| N1 | `src.suva_data.__main__` exits on import and keeps T1 red after tally is gone | src/suva_data/__main__.py:3 | See T1b | n/a |
| N2 | Of 57 modules imported one at a time with the network denied, only `src.summarize.tally` and `src.suva_data.__main__` fail. There is no network at import. | scratchpad script `imp.py` | — | — |
| N3 | `summarize._tail` is dead | summarize.py:432, no reference (AST) | Delete with D8b | yes |
| N4 | `schemas.triage_call_schema` and `suva_data.models.SourceAdapter` are used by tests only | schemas.py:265; models.py:38 | Keep: Protocol and contract helpers | no |
| N5 | `src/summarize/v1/prompts.py:66` pulls five helpers from summarize.py. Deleting the D8b helpers without D6 breaks v1. | — | Order: D6, then D8b | — |

### 6.2 Secrets, absolute paths, hosts, ports

| ID | Finding | Evidence | Recommended action |
|---|---|---|---|
| S1 | No secrets in tracked files. The only `password=` match is test code that builds a DSN. | tests/test_app_updates.py:44; `.env` untracked; gitleaks runs in pre-commit | none |
| S2 | No `/Users/...` path in tracked files (`git grep` is empty). Untracked `research/out/*.log` (git-ignored) contains the local venv path from uv warnings. | research/out/restore_models.log:1 and others | None, because they are ignored. Delete them with research/. |
| S3 | Hosts in code are all public: bger.ch, entscheidsuche.ch, huggingface.co. Tests use `.invalid` and `example`. | suva_data/config.py, sources/* | none |
| S4 | The participants' gateway URL is in docs. | docs/EVENT.md:56 `https://gateway.keera.ch/api/v1` | G13 forbids "internal hostname". It is an event-provided public endpoint: ask the lead. |
| S5 | Port binding is inconsistent: db on 127.0.0.1:54329, but the app on **all interfaces**. | docker-compose.yml:16 against :40 `"8000:8000"` | Bind to 127.0.0.1 for local use. |
| S6 | Three hard-coded DSN defaults with two different users | suva_data/config.py:65; triage/pipeline.py:35; docker-compose.yml:35 (`db:5432`, fine inside compose) | See defect 1 |

### 6.3 Dependencies (pyproject.toml against imports)

| Dep | Group | Imported in src/eval | tests | research | Finding / action |
|---|---|---|---|---|---|
| fastapi | main | main.py | 0 (**no TestClient anywhere**) | — | used; API routes have no HTTP-level tests (N9) |
| httpx | main | llm/client, judge, probe | 1 | — | used |
| huggingface-hub | main | suva_data/cli, swiss_caselaw | — | 1 | used |
| openpyxl | main | labels_xlsx | 1 | — | used |
| psycopg[binary] | main | 7 files | 8 | 1 | used |
| pyarrow | main | 3 | 4 | — | used |
| pydantic | main | schemas, main | 1 | — | used |
| scikit-learn | main **and** research | triage/scorer | — | 24 | used; the entry in the research group is redundant |
| uvicorn | main | not imported (server CLI) | — | — | used at runtime (main.py:3); keep |
| pandas | dev | courts.py:189, area_judge.py:196, summarize.py:340 | 0 | 3 | **imported at runtime but dev-only** (defect 7) |
| ipykernel, matplotlib, nbconvert | dev | 0 | 0 | 0 | only the untracked notebooks use them; ask whether to keep |
| pytest, ruff | dev | — | 29 | — | used |
| sentence-transformers, xgboost | research | 0 | 0 | 1 each | used only by research/. They pull **torch** into CI (`uv sync --frozen`, ci.yml) and Docker through `default-groups`. |
| **numpy** | **undeclared** | triage/pipeline.py, triage/scorer.py | 1 | 26 | imported directly but arrives only transitively (scikit-learn): declare it (ask first) |

### 6.4 Stale config

| ID | Finding | Evidence | Recommended action |
|---|---|---|---|
| C1 | Env vars read in code but missing from .env.example: `SUVA_DATA_DIR` (suva_data/config.py:55); `SUVA_TEST_DATABASE_URL` (tests/conftest.py:27). `.env.local` is supported (cli.py:37, config.py:16) but not documented in .env.example. | .env.example has LLM_*, LLM_NAME_SMALL, LLM_CONCURRENCY, LLM_TIMEOUT_S, LLM_MAX_INPUT_TOKENS, DATABASE_URL and JUDGE_* (all read in code) | Add the two names with no value (G3 test: tests/test_doctrines.py:80-85). |
| C2 | CI will be red: `make check` fails on ruff (295) and pytest (3). The `make run` step is a stub. CI installs the research group (torch). There is no Postgres service, so DB tests skip (tests/conftest.py:5 and :57). origin/main adds a db job. | .github/workflows/ci.yml | Merge origin/main's CI first. |
| C3 | docker-compose `app` runs `make run`, which prints stubs; then `make serve` is also a stub, so the container exits. | docker-compose.yml:45; Makefile:16-23 | §8 step 5 |
| C4 | pre-commit: gitleaks v8.30.1 plus local guards. Consistent with AGENTS.md §8. | .pre-commit-config.yaml | none |
| C5 | `VIRTUAL_ENV` points at a parent-directory venv (`../.venv`), and uv warns on every run | every `uv run` output | Local shell hygiene only |

### 6.5 Other

| ID | Finding | Evidence |
|---|---|---|
| N6 | The score explanation exists in the DB but is **German only** (`explanation_de`), so it cannot follow the EN/DE/FR switch | triage/pipeline.py:233 `sc.explanation_de(...)` |
| N7 | Checker messages shown in the UI are code-generated mixed-language strings (e.g. "trop long") | SummaryCard.tsx:63-65 shows `summary.problems`; summarize.py:660-662 |
| N8 | The handoff numbers §2's routes by `def` line; the decorators are at the same numbers (54, 59, 64, 102, 117, 150, 156, 162, 168, 174, 179, 185, 197, 202) | main.py |
| N9 | No test exercises the FastAPI routes over HTTP (no `TestClient` in tests/). Defect 3 and the route list are untested. | grep tests |

### 7. UI (`src/web`) against the required feature list

`npx tsc --noEmit -p src/web` exits 0. `npm --prefix src/web run build` exits 0 (2,245 modules, `dist/assets/index-*.js` 360 kB). Every route the UI calls exists in main.py.

| # | Feature | Present? | Component file:line | API route (main.py line) | Notes / gap |
|---|---|---|---|---|---|
| U1 | Sortable score | yes | RulingsTable.tsx:23 (`sort: "score"`), :59; Score.tsx | GET /api/rulings `sort=score` (:64) | The Inbox view sorts by score desc (lib/views.ts) |
| U2 | Decision-date window | yes | FilterBar.tsx:50-56 DateRangeFilter | `decided_from`, `decided_to` (:67-68) | — |
| U3 | Publication-date window | yes | FilterBar.tsx:57-63 | `published_from`, `published_to` (:69-70) | — |
| U4 | Case type | partial | FilterBar.tsx:71 (division multiselect) | `division` (:71) | "Case type" is covered by court division (8C, 9C…). There is no procedure-type field. |
| U5 | Area of law | yes | filters/AreaFilter.tsx:25-32 | `area` (:72) | — |
| U6 | Quick filter for Suva core areas | partial | AreaFilter.tsx:22-23 ("core" section UV, MV, IV inside the Area popover) | `topic` (:73) | Not a one-click chip. Reaching it takes opening the Area popover. |
| U7 | System decision and score filters | yes | filters/AssessmentFilter.tsx:36-48 | `predicted_relevant`, `score_min`, `score_max` (:79-83) | — |
| U8 | Full ruling text in-app | yes | RulingPage.tsx:135-136 | GET /api/rulings/{id}/workspace (:150) | Link to bger.ch as well (:127-129) |
| U9 | **Reasoning (why this score)** | **missing** | none: RulingPage.tsx shows only status and score (:83-86) | The explanation is returned only by GET /api/rulings/{id} (:102, queries.py:181), which **the UI never calls**. `/workspace` omits it (workspace.py:146-147). | Add `explanation` to `/workspace` and render it. Do **not** delete :102 (D12h). Also N6 (German only). |
| U10 | DE and FR summaries | yes | RulingPage.tsx:13 `LANGUAGES = ["de","fr"]`, :163-174 SummaryCard | /workspace (:150) | Suva's reference summaries are shown too (`reference`) |
| U11 | Summarise button | yes | RulingPage.tsx:156-157 `generateSummaries` | POST /api/rulings/{id}/summaries (:156) | Live Apertus call; a missing key gives 500 (defect 3) |
| U12 | Summary edit, confirm and revision buttons | yes | SummaryCard.tsx:79-99 (save+confirm, save, cancel, unconfirm, confirm, edit), :109-147 ReviseMenu | PUT …/{lang} (:162); POST …/confirm (:168), …/unconfirm (:174), …/revise (:179) | — |
| U13 | Relevance status change, 4 statuses recorded as events | partial | StatusCell.tsx:35-47; RulingPage.tsx:89-105 | POST /api/rulings/{id}/relevance (:117), which writes `relevance_events` (feedback.py:63) | All four labels exist in DE (i18n.tsx:325-328: Potenziell relevant, KI-geprüft: relevant, Fachlich bestätigt, Nicht relevant), plus "Nicht bewertet". The user can only **confirm** (expert_confirmed), **reject** (not_relevant) or **reopen**. Potenziell relevant and KI-geprüft are system-only and cannot be set by hand. Each action is recorded as an event. |
| U14 | Learning page | yes | LearningPage.tsx:24 | GET /api/learning (:185) | — |
| U15 | Add another judgement / updates | partial | UpdateControl.tsx:55-64; lib/useUpdates.ts:26-39 | GET and POST /api/updates (:197, :202) | Only by **publication-date range**. There is no way to add a single ruling by docket or URL, although `ingest(…, extra_dockets=…)` exists (updates.py:24) and `UpdateRequest` (:189-194) has no docket field. New rulings are not triaged (defect 9). |
| U16 | EN/DE/FR switch, no hard-coded strings outside i18n.tsx | yes, minor exceptions | LanguageSwitch.tsx; Sidebar.tsx:41; i18n.tsx en :12, de :200, fr :385 | — | Hard-coded strings outside i18n.tsx: the brand "Suva" (Sidebar.tsx:15), and `index.html:2` `lang="en"` and `:6` `<title>`, both overwritten at runtime (i18n.tsx:604-605). Data strings are not translated: the court's area names, checker messages (N7) and the German-only explanation (N6). |

### 8. Summary of changes against the handoff

- **Wrong or incomplete:**
  - T1b: deleting tally.py alone does not fix the doctrine test, because `suva_data/__main__.py` also exits at import.
  - L7: there are four `.env` readers, not three.
  - P1: `summarize/prompts.py:7` is a missed `__package__` switch.
  - D1: research/ is cited by queries.py:8 and used by local notebook 02.
  - D12c: `bench_size` feeds two FEATURES.
  - D12d: `gate_record` and `passes` are used by tests.
  - D12h: deleting GET /api/rulings/{id} would remove the only route that carries the score explanation.
  - Defect 4: `relevance_events` is also read by reconcile.py:297.
  - STATE.md:27 is still accurate.
- **Changed since the audit:** origin/main moved 5 commits ahead. It rewrites courts.py and LAYER1.md, adds `src/db/sql` (a second DDL), and redefines D-061 (an ID collision with the scorer decision).
- **New:**
  - The UI has no reasoning display.
  - numpy is undeclared.
  - torch reaches CI and Docker through `default-groups`.
  - There are no API tests (no TestClient).
  - `.env.example` lacks `SUVA_DATA_DIR` and `SUVA_TEST_DATABASE_URL`.
  - The app port in compose is bound to all interfaces.
  - D-058 is cited but missing from DECISIONS.md.
  - The research e5 model is undeclared in MODELS.md.
  - `summarize._tail` is dead.
  - Adding a judgement works only by publication-date range.
  - The explanation is German only.

---

## Appendix C: port map onto the data layer of main


Read-only audit, 28 Nov 2026. No file in the repo was changed and no network, LLM or DB call was made. The only things executed were local reads: `git show`, a parse of `db/init/10_suva.sql.gz`, and pyarrow on the local pinned HF file.

Notation: `B:` means the branch working tree. `M:` means `git show origin/main:<path>`. Line numbers are file:line.

---

### 0. Headlines (read first)

1. **The two schemas can live in one database.** The old schema is `public.*`, loaded from `db/init/10_suva.sql.gz` plus migrations 001-005. The new one uses the six schemas `ops`, `corpus`, `triage`, `gold`, `summ` and `audit`. Both use the same image, DB name and user (§5). So `make db-deploy` can run beside the working system, and the port can go chunk by chunk.
2. **The base data is already local and complete.** On the local pinned file `data/raw/swiss_caselaw/35b17aa9…/bger.parquet` (same commit and SHA as D-062), the §8.1 Q2 union rule gives exactly **2,677**: 2,096 by decision date, 992 HF-poller, 1,068 first-seen. **All 2,677 are already in the branch dump.** The 581 not decided in Q2 were all decided in Q1/2026. The dump also holds 1,931 (Q4/2025), 2,005 (Q1/2026) and 23 (Q3/2025) by decision date. So corpus rows exist, but publication observations, populations, snapshots and uuid5 ids do not.
3. **Semantic conflict on the score (D-063 vs the branch).** D-063 says layer 2 = 100 × P(Ja)/(P(Ja)+P(Nein)). The branch's score is a different thing (`src/triage/scorer.py:101-131`):
   - it is a logistic regression over 8 code-read facts plus a z-scored consensus of **six** one-token Apertus readings;
   - the cut is 40 % of each quarter's core rulings (`src/triage/pipeline.py:90-95,154-161`), not a frozen F2 threshold.

   Only one of the six readings (`verdict`, `src/triage/readings.py:13`, `value_from_logprobs` kind "yes") is literally D-063's formula. This needs the lead's decision (§6.3).
4. **Summaries are blocked on segmentation.** `summ.summary_version.source_segmentation_id` is NOT NULL (M:`src/db/sql/50_summ.sql:96`). D-070's source is a **4.99 GB** HF file, and this machine has **6.4 GiB free** (`df`, 99 % used). Downloading and parsing it locally is not realistic without freeing disk. An interim `own_splitter` V0.x segmentation is the way round it (§3.3).
5. **The expert write model differs.**
   - Relevance: the branch has 4 expert-visible statuses plus `reopen`. D-066 has `correct`/`incorrect` on `in_scope`/`out_of_scope` only.
   - Summaries: the branch versions free-text bodies per language, with confirm/unconfirm and revision reasons. The new model has DE+FR pair versions, claims (needed for expert edits), and `validated`/`rejected` reviews.
   - Revision-reason telemetry (the "self-improvement" data) has no table.
6. **Urgent, outside the port: a D-051/D-031 leak risk.** These files contain `labels.metadata.sharepoint_url` (Suva intranet links) and `gold_summaries.author` (110/110 rows set):
   - `db/init/10_suva.sql.gz`
   - `data/publish/dump/suva.sql.gz` (byte-identical)
   - `data/publish/tables/labels.parquet`
   - `data/publish/tables/gold_summaries.parquet`

   `B:src/suva_data/config.py:97-101` names `suva-nga/bger-rulings` as a **public** HF dataset, with a "pinned upload" `7eb6025…`. I could not check (no network) whether that upload holds these files. Someone should check it now.

---

### 1. Old schema → new schema, table by table

Old DDL is `B:db/migrations/001..005`. Note that the task brief named only 001/002, but **003, 004 and 005 exist too**: `ingested_rulings`, `relevance_events`, `summary_events` and the summary confirm columns.

The dump `db/init/10_suva.sql.gz` holds only the 001 tables; its `schema_migrations` row is just `001_init.sql`. 002-005 are applied at app start (`B:src/suva_app/main.py:28-32`). Row counts in the dump:

| Table | Rows |
|---|---|
| rulings | 6,055 |
| source_records | 17,557 |
| ruling_texts | 12,125 |
| raw_files | 456 |
| conflicts | 1,103 |
| statute_refs | 74,799 |
| labels | 59 |
| gold_summaries | 110 |

Any rows written later live only in the local volume. **Before porting, count the authored rows in the live DB:** `relevance_events`, `labels` where `label_set='expert_override'`, `summaries` where `origin='expert'` or `confirmed_at` is set, and `summary_events`.

| Old table/view (file:line) | Columns and purpose | New home | Gaps and constraints the old code cannot meet |
|---|---|---|---|
| `ingest_runs` (001:4-13) | id bigserial, command, params jsonb, git_commit, status running/ok/failed/partial, report jsonb, started/finished | `ops.pipeline_run` (M:11_ops_execution.sql:29-50); counters in `ops.run_metric`; report file in `ops.artifact` kind `ingestion_report` | `profile_version_id` NOT NULL, so a profile must exist before any load. Other NOT NULL columns with no old equivalent: `git_dirty`, `params_sha256`, `triggered_by`, `mode`. Status enum differs (`succeeded`/`aborted`, no `ok`). There is **no `report` jsonb**, yet `B:src/suva_app/updates.py:71-110` reads `report` for the UI status, so it must read run_metric/artifact instead. uuid ids, not bigserial. |
| `raw_files` (001:16-22) | every snapshot file: source, path, sha256, bytes | `ops.source_snapshot` (11:14-26) | The `source_kind` ENUM (M:00_extensions.sql:64) has `hf_bger`, `hf_erwaegungen`, `hf_structure`, `bger_neuheiten`, `bger_ruling_page`, `judgements_*`, `models_md`, …. It has **no value for entscheidsuche** (89 files), **HF daily deltas** (`B:src/suva_data/sources/hf_daily.py:60`) or the **statute graph** parquet. Each would need an ENUM change (DDL). |
| `rulings` (001:25-45) | docket, decision_date, division, language (nullable), publication_date, starred, area, subject, outcome, cited_decisions, official_url, field_sources, flags, in_window | Identity: `corpus.ruling` (20_corpus.sql:15-33). Publication date, star and Sachgebiet: `corpus.publication_observation` (51-63). Read through `corpus.v_ruling` (60_views.sql:15-48). `in_window` becomes `corpus.population(_member)` (162-188). | See the field-by-field breakdown below this table. |
| `source_records` (001:49-62) | every source row as-is: fields/record jsonb, status loaded/used/duplicate/rejected, reason | `corpus.ruling_source_ref` (39-47): source, external_id, ruling_id, snapshot_id, is_twin | **Lost:** `fields`, `record` jsonb, `status`, `status_reason`. `ruling_id` is NOT NULL, so rejected or unmatched records (no ruling) have no home. D-061 makes the committed files the truth, so this may be acceptable. Lead to confirm. |
| `ruling_texts` (001:66-79) | text per source record: sha256 of the *normalised* text, char_count, bad_reason, is_canonical | `corpus.ruling_text` (67-82) | See the field-by-field breakdown below this table. |
| `conflicts` (001:82-94) | cross-source disagreements, 1,103 rows | none. Nearest is `corpus.ingest_issue` (150-158) with reason codes | No reason codes for `value_mismatch`/`text_mismatch`/…; the seed has only `ING_*` and `SEG_*` (95_seed_reference.sql:38-47). Consumers: `B:src/suva_data/verify.py`, `export.py:81`. |
| `statute_refs` (001:96-103) | 74,799 (law, article, paragraph) refs from HF `graph/statute_references.parquet` | **none** | No table and no source_kind. Consumers: verify/export/reconcile only; UI and triage do not use it. Drop or ask the lead. |
| `labels` (001:106-116) | label_set (`suva_xlsx_2025Q4_2026Q1`, `expert_override`), value relevant/not_relevant, quarter `YYYY Qn`, metadata (erstellt, **sharepoint_url**, xlsx_title, xlsx_row) | Suva rows go to `gold.label` (40_gold.sql:14-28). `expert_override` rows go to **`gold.expert_review`** (32-51), never gold.label (`label_source` has no expert value). | See the field-by-field breakdown below this table. |
| `gold_summaries` (001:119-134) | 110 rows = 55 exports × de/fr: title, body, **author**, source_url, source_file, version, is_current | `gold.suva_summary` (57-72): **one row per export with `text_de` AND `text_fr` NOT NULL**, `bger_url ^https://`, `source_file LIKE 'judgements/Export\_%'`, id = uuid5(`suva_summary|<source_file>`) | Rows must be paired per file. `author` and `title` are dropped. One `source_url` is `http://relevancy.bger.ch/…` (dump row for `Export_8C_154_2025.html`) and fails `^https://`: build the URL by code. Store the stored filename with a `judgements/` prefix; one name contains a space (`Export_8C_176_2025 3.html`), which is OK. |
| `v_relevance` (001:137-159) | the label: expert_override > suva_xlsx > gold_summary_only > closed-world negative (decided 2025-10-01..2026-03-31) > unknown | Split in three: Suva truth in `gold.v_label_effective` (60_views.sql:185-195); the pipeline label in `triage.v_scope_pipeline` (62-94); expert beside it in `triage.v_scope_current` (98-119) | **Semantics change (D-066):** the expert no longer overrides the label; `expert_implied_label` sits beside it. `gold_summary_only` becomes `has_suva_summary`. The closed world is per labelled population, not a hard-coded date range. |
| `model_runs` (002:7-15) | kind triage/summary, models jsonb array, params jsonb, git_commit | `ops.pipeline_run` + `ops.component_version` (+`_model`, `_prompt`, `_rule`) + `ops.pipeline_profile_step` | See the field-by-field breakdown below this table. |
| `predictions` (002:18-31) | score 0..1, relevant bool (tier), explanation (German), details jsonb (tier, layer1, signals, readings, consensus, contributions), is_current | `triage.assessment` per step (30_triage.sql:15-47), plus `assessment_reason`, `llm_judgement`, `ranking`/`ranking_entry`, `threshold` | See the field-by-field breakdown below this table. |
| `summaries` (002:34-50, +005:7-10) | per (ruling, language) versions: headline, body, origin model/expert, run_id, parent_id, version, is_current, confirmed_at/by | `summ.summary` (ruling × preset) → `summary_version` (**pair**) → `summary_text` ×2 → `summary_claim` → `claim_citation` (50_summ.sql:79-153) | See the field-by-field breakdown below this table. |
| `ingested_rulings` (003) | (docket, decision_date) added by a live ingest, with the publication range | `corpus.ruling.origin` (`base_dataset`/`user_added`) + `publication_observation` + `ops.pipeline_run(kind='ingest').params` | Is a live-ingested ruling `base_dataset` or `user_added`? (`user_added` reads as D-015 "add a judgement".) **Rebuildability (D-061):** live files sit in `data/raw/live` (`B:config.py:59`), which is git-ignored, so a fresh deploy cannot rebuild them. Lead decision. |
| `relevance_events` (004) | append-only expert decisions: action confirm_relevant/mark_not_relevant/reopen, status_before/after (5 statuses), prediction_id, score_shown, reason, comment, actor | `gold.expert_review` target `scope` via `gold.submit_review()` (70_functions.sql:44-88) | Covered in detail in §3.6. |
| `summary_events` (005:12-28) | append-only: generate/revise/edit/confirm/unconfirm, revision `reason` (9 codes), note, before/after ids, `unchanged` | partly `gold.expert_review` (summary_version: validated/rejected), `ops.user_request` (kind summary), `ops.span`/`ops.log_event` | **The 9 revision reasons and notes, the training data of the self-improvement loop, have no home.** Options: `expert_review.payload` (needs a V2 `summary_review.payload` schema, append-only, no DDL change), or a new table. `unchanged` can be derived from `origin` plus the review. `unconfirm` has no form (see §3.6). |
| `schema_migrations` (B:src/suva_data/db.py:56-63) | applied migration files | none; `src/db/deploy.py` re-applies idempotent files, no ALTER (D-061) | Two migration systems would coexist until the old one is retired. |

### 1.1 Field-by-field breakdown for the dense rows

**`rulings` → `corpus.ruling`**
- `division` becomes the generated `court`.
- `language` is NOT NULL; it is set in all 6,055 dump rows, so that is fine.
- `subject` becomes `gegenstand`, NULL when empty.
- `official_url` becomes `bger_url`: NOT NULL, `^https://`, built by code from the aza id.
- New NOT NULL columns: `origin`, `created_by_run_id` (so a pipeline_run must exist).
- `ruling_id` = uuid5(`bger|docket|date`), checked by trigger (80_triggers.sql:31-32).
- The table is append-only (80:58-61).

**`rulings.area`**
- It becomes `publication_observation.sachgebiet`.
- Dump `field_sources.area` breaks down as 5,432 from `bger_list`, **179 from `swiss_caselaw` legal_area** (forbidden by D-062) and 444 none.
- Those 179 lose their area and fall back to the title, which can change layer 1 (see §2.3).

**`rulings.starred` and `rulings.publication_date`**
- `starred` becomes `publication_observation.star`. The branch's star comes from bger_list, which is OK; the swiss_caselaw star is already never canonical (`B:config.py:88`).
- `publication_date` becomes observations of type `neuheiten` (bger_list), `hf_poller` (HF ≥19 May) or `hf_first_seen` (scraped_at, approximate).

**Fields with no home**
- `outcome` is "never ingested" (D-062). Its new home is `corpus.ruling_parse.outcome` (129-147), written by a parse step that does not exist yet.
- That breaks consumers that need it: the UI outcome column and filter (`B:src/web/src/components/RulingsTable.tsx:28,108`, `FilterBar.tsx:42,73`, `RulingPage.tsx:66`), `queries.facets` (`B:queries.py:249`) and `B:eval/judge/data.py:76`.
- `cited_decisions` has no column. §8.1 says it is "taken from HF", but the DDL has none.
- `field_sources` and `flags` have no home.

**`ruling_texts` → `corpus.ruling_text`**
- `source` ENUM becomes hf/bger/entscheidsuche/opencaselaw; `swiss_caselaw` → `hf`.
- `content_sha256` must be the SHA-256 of the **exact** content, checked by trigger (80:246-255). The old column is over the normalised text, so it must be recomputed.
- `content` must be non-blank, so the 7 empty or bad texts cannot be stored. `bad_reason` has no column; use `ingest_issue ING_TEXT_MISSING`.
- `is_canonical` → `is_primary`.
- `snapshot_id` is NOT NULL.

**Primary text and the replay cache**
- The branch's canonical text is **entscheidsuche for 6,053 rulings** (dump `ruling_texts` is_canonical=t). D-062 puts HF first.
- Changing the primary text changes every prompt, so the **replay cache keys** (`B:src/llm/client.py:114-115`, sha of the payload) all miss. Replay then needs live calls.

**`labels` → `gold.label`**
- Fits: `in_suva_scope` = true, `quarter_label` `2025 Q4` (regex OK), `source='suva_relevance_list'`.
- New NOT NULL columns: `source_ref LIKE 'judgements/%'`, `snapshot_id` (judgements_workbook) and `created_by_run_id`.
- `metadata` is dropped, which is right: sharepoint_url and erstellt are D-051.
- DB-13 expects **59 + 1** rows. The +1 is the cantonal row with `external_title`, which the branch drops (`labels.dropped`, `B:src/suva_data/cli.py:119`).
- `UNIQUE NULLS NOT DISTINCT (source, ruling_id, external_title)`.

**`model_runs`**
- There is no "models jsonb". Models are FKs to `ops.model`, loaded from MODELS.md, plus `pipeline_run.resolved_models` and `ops.llm_call.requested_model`/`served_model`.
- `params` (prompt versions, features, threshold, consensus stats, measured metrics) must be split:
  - versioned config goes into `component_version.config` with a json_schema;
  - run params go into `pipeline_run.params` with `params_sha256`;
  - measured metrics go into `triage.threshold.metrics`.
- **The fitted logistic regression has no model slot.** `ops.model` is gateway models, and `model_role` is judge/generator/repair only. Its coefficients change every refit, which would mean a new component_version per run.

**`predictions`**
- `score` 0..1 becomes `score_0_100` numeric(5,2) plus `score_raw`.
- `relevant`/tier becomes the ranking step's `in_suva_scope`.
- `explanation` → `explanation_de`.
- `details.layer1` → `assessment_reason` rows; each needs `rule_id` and `reason_code` from the step's rules, checked by trigger (80:340-360).
- `details.signals`, `contributions` and `consensus` have **no column**. Candidates: `span.attributes` (≤16 KB) or `log_event`.
- `is_current` is gone; the current label is a view (D-063).
- New NOT NULL columns per row: `span_id`, `component_version_id` (must equal the profile's pin; trigger 80:301-336), `input_fingerprint` (sha256 over the inputs), `mode`, `started_at`, `outcome`.
- There is no UPDATE. The branch's `UPDATE predictions SET is_current=false` (`B:src/triage/pipeline.py:214`) becomes "insert a new run".

**`summaries`**
- `headline` becomes `title_line`, which is NOT NULL and rendered by code.
- `origin` model/expert becomes `generated`/`repaired`/`regenerated`/`expert_edit` (a non-generated version needs `parent_version_id`).
- New NOT NULL columns: `preset_version_id` (`suva_house` needs a preset_version and a `preset_config` json_schema, neither seeded), `component_version_id` (summarise step) and **`source_segmentation_id`**.
- A pipeline text needs `llm_call_id` NOT NULL (trigger 80:512-521). `word_count` and `paragraph_count` (1-20) are NOT NULL.
- `confirmed_at`/`confirmed_by` columns: none. Confirmation becomes a `gold.expert_review` with `validated`.
- **A version must hold exactly one DE and one FR text at commit** (deferred trigger 80:510-511). The branch's one-language versions (`B:workspace.py:68-89`) and revisions (`revise`, one language, :226-281) do not fit as they are.

---

### 2. Every DB call site (src/ and eval/) and what it must become

The legend for the "Must become" column (new home):
- **corpus loader**: DB-11, a new module writing `corpus.*` + `ops.source_snapshot`.
- **gold loader**: DB-13.
- **triage writer**: DB-14.
- **summ writer**: DB-15.
- **API**: DB-16.
- **retire**: delete when the old schema goes.

### 2.1 Plumbing — `src/suva_data/db.py`, `config.py`

| file:line | SQL / tables | Must become |
|---|---|---|
| `db.py:26-29` `connect()` | autocommit psycopg3 to `config.DATABASE_URL` | Keep it. Add session settings `SET app.actor`, `SET app.run_id` (required by `gold.submit_review`, `summ.create_expert_version` and the audit log, M:70_functions.sql:13-22, 13_audit.sql:29-44). Use **role-specific logins**: `suva_pipeline` for writers, `suva_api` for the API (90_roles.sql:21-37). |
| `db.py:43-84` `migrate()` | `schema_migrations`, applies `db/migrations/*.sql` | Retire it once the old tables go. The new DDL deploys via `python -m src.db.deploy deploy` (psql subprocess). Note: **no local `psql` binary** on this Mac (`command -v psql` empty), so use `--compose`. `src/suva_app/main.py:28-32` calls `migrate` at every app start; that must stop or be guarded. |
| `db.py:98-116` `start_run`/`finish_run` | `INSERT/UPDATE ingest_runs` | → `ops.pipeline_run` insert, then close with `UPDATE status, finished_at, error_summary` (the only mutable columns, 80_triggers.sql:83). Needs a Python run/span context manager (DB-10 "Telemetry"). |
| `config.py:65` | `DATABASE_URL` default `postgresql://suva@localhost:54329/suva` | That port is **not published on main's compose** (§5). |
| `src/triage/pipeline.py:35` | `DEFAULT_DSN = postgresql://postgres:suva@localhost:54329/suva` | Already wrong today: user `postgres` with password `suva`, while compose has user `suva` and trust auth. Masked when `DATABASE_URL` is set. Fix while porting. |

### 2.2 Ingestion — `src/suva_data/*`

| file:line | SQL / tables | Must become |
|---|---|---|
| `cli.py:74-149` `cmd_build` | migrate, then `ingest_runs`, `raw_files`, `source_records`, reconcile, statute_refs, labels, gold_summaries, verify, manifest | corpus loader (pinned HF + Neuheiten observations, populations) + gold loader, under one `pipeline_run(kind='load')`. |
| `load.py:104,118` | SELECT/INSERT `raw_files` | → `ops.source_snapshot` |
| `load.py:233,304-305,326-329` | INSERT/UPDATE `source_records` (bulk unnest) | → `corpus.ruling_source_ref` (append-only, **no UPDATE**) |
| `load.py:345` | **`DELETE FROM ruling_texts`** | Not allowed: `ruling_text` refuses DELETE by trigger and by grants. A new text is a new row (uuid5 on sha). |
| `load.py:349-350` | INSERT `ruling_texts` | → `corpus.ruling_text` (exact-content sha, snapshot_id) |
| `reconcile.py:132` | SELECT source_records ⨝ ruling_texts | The in-memory hierarchy of truth stays useful to pick the primary text and observations. |
| `reconcile.py:276-280` | INSERT `rulings` | → `corpus.ruling` (uuid5, `created_by_run_id`, `origin`) |
| `reconcile.py:293-299,310` | guard, then **`DELETE FROM rulings`** (stale rulings) | Not possible: append-only, ON DELETE RESTRICT everywhere. A "stale" ruling stays; populations decide membership. |
| `reconcile.py:321-331` | UPDATE source_records.status, ruling_texts.ruling_id/is_canonical | Only `ruling_text.is_primary` may change (80:85). Status → none. |
| `reconcile.py:345-347` | INSERT `conflicts` | → `corpus.ingest_issue` or a log_event (needs reason codes), or drop |
| `reconcile.py:367-369` | INSERT `statute_refs` | no home (§1) |
| `loaders/labels_xlsx.py:135,174,207` | SELECT rulings; SELECT/INSERT `labels` | → `gold.label` (+ the cantonal `external_title` row; metadata dropped) |
| `loaders/gold_summaries.py:255,292` | SELECT/INSERT `gold_summaries` (author, source_url) | → `gold.suva_summary`, one row per export (DE+FR), no author |
| `verify.py` (41 SQL refs, all old tables) | invariants and fingerprint | Rewrite against the new tables. §8.1 says the counts go to `results/ingestion.json` + `ops.run_metric`, and a mismatch fails the run. |
| `export.py:41-87` | SELECT every old table → parquet | Retire, or point at `corpus.v_ruling` etc. Note `--exclude-table-data=ingest_runs` in `cli.py:173-176` (dump). **Do not republish labels/gold (D-051/D-031).** |
| `ingest.py:69` | SELECT `ingested_rulings` | → `corpus.ruling WHERE origin=…` or population/observation |
| `ingest.py:75-80` | `max(params->>'published_to') FROM ingest_runs`; `max(publication_date) FROM rulings` | → `ops.pipeline_run(kind='ingest').params`; `max(observed_date) FROM corpus.publication_observation` |
| `ingest.py:117` | raw_files | → source_snapshot |
| `ingest.py:132` | source_records | → ruling_source_ref |
| `ingest.py:208,218,224-228` | rulings, INSERT `ingested_rulings`, ruling_texts count | → corpus.* + run_metric |

### 2.3 Triage — `src/triage/pipeline.py`

| file:line | SQL / tables | Must become |
|---|---|---|
| `:40-52` `load_rulings` | `rulings ⨝ v_relevance ⨝ ruling_texts(is_canonical)` | → `corpus.v_ruling` (gegenstand, sachgebiet, star, primary_text_id) ⨝ `corpus.ruling_text` ⨝ `gold.v_label_effective` (labels by labelled population, not `decision_quarter`/`basis`). See the note below the table. |
| `:55-63` `label()` | `basis` suva_xlsx / complete_list_negative; quarters `2025 Q4`, `2026 Q1` | → `gold.v_label_effective.in_suva_scope` with `basis` suva_list/closed_world, population codes `2025Q4_decision`, `2026Q1_decision`. |
| `:193-237` `write()` | INSERT `model_runs`; **UPDATE predictions SET is_current=false**; INSERT `predictions` per kept ruling | triage writer. Outline below the table. |
| `src/suva_app/stub.py:42-66` | placeholder predictions: DELETE model_runs, INSERT predictions | Retire (no DELETE possible); use a separate non-default profile if placeholders are still wanted. |

What `load_rulings` loses: `area` loses the 179 swiss_caselaw values; `starred` comes only from a neuheiten observation. The layer-1 and scorer inputs differ slightly from today's: `courts.layer1_record` (`B:src/courts.py:152-182`) and `structural_signals` (`B:src/signals/structural.py:82-125`).

Outline of the triage writer:
1. `pipeline_run` pinned to the default profile.
2. Per ruling, a span.
3. A `layer1_filter` assessment for **every** ruling, not only the kept ones, because the ranking gate needs every population member labelled (60_views.sql:248-260). Each has `assessment_reason` rows. The `area_judge` Apertus call is an `ops.llm_call` with step `layer1_filter`.
4. A `layer2_judge` assessment, with `llm_judgement` for one Ja/Nein call.
5. Optionally a `justification` step.
6. `threshold`, then a `ranking` per population, then `ranking_entry` and the ranking assessments.

### 2.4 Summaries — `src/summarize/pipeline.py` (and `summarize.py`, v2/)

| file:line | SQL / tables | Must become |
|---|---|---|
| `:63-77` `load_ruling` | rulings (area = coalesce(area, subject prefix), starred) ⨝ ruling_texts(canonical, no bad_reason) | → `corpus.v_ruling` + primary text + **primary segmentation** (needed for `source_segmentation_id`) |
| `:80-90` `examples` | `gold_summaries ⨝ rulings` for the few-shot pair | → `gold.suva_summary.text_de`/`text_fr`. Each few-shot use should be logged in `ops.llm_call_example` (trigger refuses the judged ruling as its own example, 80:198-208). |
| `:106-141` `store` | INSERT model_runs; SELECT/UPDATE summaries is_current; INSERT summaries per language | summ writer. Outline below the table. |
| `:153-158,161-173` `routes`/`_selected` | rulings; `suva_app.queries._BASE` status | → `corpus.v_ruling`; status from `triage.v_scope_current` |
| `summarize.py:325-336` `chat` | (LLM only) returns `.content` string | Must also return `LLMResult` metadata (cache_key, served_model, usage, latency) to write `ops.llm_call`. The client already logs `llm_calls.jsonl` (`B:src/llm/client.py:339-353`), which ops.llm_call mirrors by design (11_ops_execution.sql:173). |
| `src/summarize/v2/`, `v1/` | prompts and glossary only, no SQL | Prompts must become `ops.prompt_version` rows (system_template, user_template, sha). Today they are Python builders: `prompts.system_prompt(language, category)` × 6 categories. |

Outline of the summ writer:
1. `pipeline_run`, a span, and one `ops.llm_call` per language.
2. `summ.summary(ruling, 'suva_house')`.
3. A `summary_version(generated, creator_kind pipeline, mode, preset_version_id, component_version_id, source_segmentation_id)`.
4. Two `summary_text` rows in one transaction, with title_line, word/paragraph counts and llm_call_id.
5. Flip `is_current` (pipeline role may UPDATE it).
6. The branch rule "an expert-edited/confirmed fiche stays current" (`:131-134`) must be re-expressed via `v_expert_review_current` and `origin='expert_edit'`.

### 2.5 Web API — `src/suva_app/` (FastAPI, `main.py`)

| Endpoint (main.py:line) | Handler → SQL | Called by UI (`src/web/src/lib/api.ts`)? | Must become |
|---|---|---|---|
| `GET /api/health` (:54-56) | `count(*) FROM rulings` | **no** | `corpus.ruling` |
| `GET /api/facets` (:59-61) | `queries.facets` (:225-252): `_BASE` groupings + `predictions ⨝ model_runs` (stub flag) | **yes** `fetchFacets` (api.ts:125) | On `corpus.v_ruling` + `triage.v_scope_current`. The outcome facet is empty until a parse step exists. Stub flag → profile/run kind. |
| `GET /api/rulings` (:64-99) | `queries.list_rulings` (:132-151) on `_BASE` (:41-65): rulings ⨝ v_relevance ⨝ predictions(current) ⨝ ingested_rulings + EXISTS gold_summaries/summaries; status CASE (:26-30) | **yes** `fetchRulings` (api.ts:127-128) | `corpus.v_ruling ⨝ triage.v_scope_current ⨝ triage.ranking_entry` (planning §5). Statuses re-mapped (§3.6). Filters `published_*` use `v_ruling.publication_date` (exact) and maybe `_approx`. `ingested` → `origin`. |
| `GET /api/rulings/{ruling_id:int}` (:102-108) | `queries.get_ruling` (:154-185): ruling_texts, predictions.explanation, gold_summaries, summaries | **no** (the UI uses `/workspace`) | Retire, or move to the §5 shape. **IDs:** `int` → uuid in the path and in UI types (`api.ts:9,114,135,164-176` all `id: number`). |
| `POST /api/rulings/{id}/relevance` (:117-125) | `feedback.decide_relevance` (feedback.py:36-78): `SELECT … FOR UPDATE rulings`; DELETE/UPSERT `labels(expert_override)`; INSERT `relevance_events` | **yes** `decideRelevance` (api.ts:114-121), used twice | → `gold.submit_review('scope', assessment_id, correct/incorrect)` as `suva_api` with `app.actor`. No DELETE/UPSERT. See §3.6 for reopen. |
| `GET /api/rulings/{id}/workspace` (:150-153) | `workspace.ruling_page` (:111-153): `_BASE`, ruling_texts, summaries ⨝ model_runs.params (category, problems), gold_summaries | **yes** `fetchRuling` (api.ts:166), used twice | `corpus.v_ruling`, primary text, `summ.v_summary_current` (pair), `gold.suva_summary`. The "problems" from the checker → `summ.verification_check` (needs `verify` rules) or span attributes. |
| `POST /api/rulings/{id}/summaries` (:156-159) | `workspace.generate` (:159-172): runs the LLM **inside the API request**, then INSERT summaries + summary_events | **yes** `generateSummaries` | Planning §5: `POST /api/rulings/{docket}/summaries {preset_code}` → `ops.submit_request(kind='summary')`; a pipeline worker writes. **suva_api has no INSERT grant on summ.*** (90_roles.sql:59-61,84-86), so the synchronous path needs a decision (§6). |
| `PUT /api/rulings/{id}/summaries/{lang}` (:162-165) | `workspace.save_edit` (:175-192): new expert version, optional confirm | **yes** `saveSummary` | → `summ.create_expert_version(parent, lang, title, body, claims)`, which **needs a non-empty claims array** (70_functions.sql:119-121), then `submit_review(validated)` if confirm. |
| `POST …/{lang}/confirm` (:168-171) | UPDATE summaries.confirmed_at, INSERT summary_events | **yes** `confirmSummary` | → `gold.submit_review('summary_version', …, 'validated')` |
| `POST …/{lang}/unconfirm` (:174-176) | UPDATE confirmed_at=NULL, INSERT summary_events | **yes** `unconfirmSummary` | No equivalent: a review can only be superseded by another verdict (`rejected` means something else). Decision needed. |
| `POST …/{lang}/revise` (:179-182) | `workspace.revise` (:226-281): LLM in-request, INSERT model_runs, summaries, summary_events(reason) | **yes** `reviseSummary` | Pipeline version `origin='regenerated'`, parent = current. It **must carry both languages** (copy the other text, which keeps its own `llm_call_id`). The reason goes nowhere today (§1). |
| `GET /api/learning` (:185-187) | `queries.learning` (:255-283): v_relevance, labels(expert_override), gold_summaries, summaries, summary_events, relevance_events | **yes** `fetchLearning` | Counts from `gold.expert_review` (+ `assessment.in_suva_scope` for transitions), `summ.summary_version.origin`, revision reasons (wherever they land). |
| `GET /api/updates` (:197-199) | `updates.status` (updates.py:69-90): `ingest_runs.report`, `ingested_rulings` count | **yes** `fetchUpdates`, used twice | `ops.pipeline_run(kind='ingest')` + `run_metric` |
| `POST /api/updates` (:202-215) | background `ingest.ingest` in the API process | **yes** `startUpdate` (api.ts:89-98) | Runs as the pipeline role. Planning §5 lists no ingest endpoint; decision needed (keep it as a pipeline job triggered by the API?). |

New §5 endpoints with no branch equivalent yet: `/trace`, `/timeline`, `/api/presets`, `/api/registry/profiles/{code}`, `/api/export/relevant`, `/api/status`, `POST /api/rulings {docket|url}`, `POST /api/reviews/*`, `POST /api/summaries/{id}/versions`.

### 2.6 eval/

| file:line | SQL | Must become |
|---|---|---|
| `eval/judge/data.py:68-78` `sources()` | `rulings(docket, language, outcome) ⨝ ruling_texts(canonical)` | `corpus.v_ruling` + primary text. `outcome` → `corpus.ruling_parse.outcome`, which does not exist yet, so the judge loses the outcome field until a parse step exists. Should connect as `suva_report` (read-only). |

### 2.7 Tests that touch the DB (branch)

These files test the old schema through the `db_conn` fixture (`tests/conftest.py:1-60`):

| File | Tests |
|---|---|
| `tests/test_db.py` | 17 |
| `test_feedback.py` | 9 |
| `test_workspace.py` | 20 |
| `test_app_queries.py` | 24 |
| `test_model_output.py` | 15 |
| `test_triage_pipeline.py` | 14 |
| `test_ingest.py` | 23 |
| `test_reconcile.py` | 13 |
| `test_reconcile_protects_work.py` | 5 |
| `test_app_updates.py` | 9 |
| `test_export.py` | 4 |
| `test_load.py` | 14 |

Two problems:
- The fixture **skips** when the DB is unreachable (`conftest.py:57`). On main's compose (no host port) these tests would silently skip.
- Porting replaces their subject. Your CLAUDE.md says "never edit existing tests to make them pass", so retiring or replacing old-schema tests needs your explicit OK, chunk by chunk.

---

### 3. What the new DDL needs that no code provides yet

`src/db/seed/` does not exist on main (`git ls-tree origin/main src/db` lists only `__init__.py`, `deploy.py` and `sql/`). `95_seed_reference.sql:7-8` says that step versions, rules, prompts and profiles are written by the registry loader (DB-10), and models come from MODELS.md. **Until that exists, no pipeline_run can be inserted**, because `profile_version_id` is NOT NULL, and so neither can any corpus row (`created_by_run_id` NOT NULL).

The best template is `M:tests/sql/_fixtures.sql` (241 lines). It inserts one row into each of the following, in dependency order:
- ops: `source_snapshot`, `json_schema`, `model`, `component_version`, `component_version_model`, `rule`, `component_version_rule`, `pipeline_profile`, `pipeline_profile_version`, `pipeline_profile_step`, `pipeline_run`, `span`, `llm_call`, `prompt_version`, `release`;
- corpus: `ruling`, `ruling_text`, `segmentation`, `consideration`, `population`, `population_member`;
- triage: `assessment` (×4), `assessment_reason`, `llm_judgement`, `justification`, `assessment_evidence`, `threshold`, `ranking`, `ranking_entry`;
- summ: `preset_version`, `summary`, `summary_version`, `summary_text`, `summary_claim`, `claim_citation`.

It is effectively the reference implementation of every writer.

### 3.1 Registry loader (DB-10)

- **`ops.model` from MODELS.md.** MODELS.md is a prose markdown table (`M:MODELS.md:9-16`). Gateway ids sit in backticks inside the "Exact id / revision" cell (`apertus-v1-5-70b`, `apertus-v1-5-8b`), so the loader needs a parser plus a `source_snapshot(source='models_md', file_sha256)`. ops.model requires `family`, `size_label`, `gateway_id`, `allowed` and `source_snapshot_id` (M:10_ops_registry.sql:52-62). id = uuid5(`model|<gateway_id>`). MODELS.md also differs between branch and main (`git diff HEAD origin/main -- MODELS.md`):
  - the branch adds the area_judge row and the logistic-regression row (citing "D-061", a number main now uses for the data layer);
  - the branch adds gpt-oss and judge rows.

  This needs reconciling first.
- **json_schema rows.** One `step_config` schema per step, `rule_definition` and `preset_config`. Only the two review_payload schemas are seeded (95:80-91). A trigger checks the subject (80:117-138).
- **component_version per step.** It needs `config` + `config_sha256` + `code_path` + `code_sha256` (+ `git_commit` char(40)), with id = uuid5(`cv|step|maj|min|pat`). The steps the branch needs: `ingest`, `segment`, `layer1_filter` (courts.py + area_judge), `layer2_judge`, `ranking`, `summarise`; later `parse`, `justification`, `verify`, `export`.
- **Rules and reason codes for the branch's layer 1.** The seeded L1 codes describe "filter E" (95:20-27: `L1_KEEP_COURT_8C_9C`, `L1_KEEP_SOCIAL_AREA`, …). The branch's layer 1 (D-060, `B:src/courts.py:37-44,99-137`) has different reasons: `wrong_court`, `wrong_letter`, `subject_out`, `subject_missing`, `subject_unknown`, `kept_subject`, `kept_text`, `text_absent`, `text_clear`, plus the Apertus matter reading. That means **new reason codes** (insert is allowed) and `ops.rule` rows per reason. assessment_reason with effect keep/drop needs `evidence_field` or `evidence_consideration_id` (30_triage.sql:66).
- **Prompt versions.** Needed for the 6 readings (`B:src/triage/readings.py:12-19`, already versioned e1/e13), area_judge (`area_judge@2`) and summaries (`prompts.VERSION` × category × language). They must be rendered to text templates; today they are Python code.
- **Default profile.** `ops.pipeline_profile('default', is_default)` + `pipeline_profile_version V0.x` + `pipeline_profile_step` pins. A **V1.x profile refuses V0.x steps** (80:152-166), so start with profile V0.1.0.
- **suva_house preset_version.** Needs `config_schema_id` (preset_config), `config`, `bump_kind='initial'`, `changelog`, plus `preset_version_prompt` per language.

### 3.2 source_snapshot and the pinned HF commit (D-062, §8.1)

- **Same commit as the branch.** `B:config.py:91-96` pins `voilaj/swiss-caselaw@35b17aa9c3fad71011b72f78f6ab79650ec0cf96`, `data/bger.parquet` sha `d2b2df1d…`. That matches D-062 and M:DB_DDL_PLANNING.md:4 exactly. The file is already local (925 MB, `data/raw/swiss_caselaw/35b17aa9…/bger.parquet`, `.sha256_verified.json` present).
- **Populations reproduced locally** (pyarrow, §8.1 rules):

  | Population | Count |
  |---|---|
  | 2026Q2_decision | 2,096 |
  | hf_poller 19 May-30 Jun | 992 |
  | hf_first_seen 1 Apr-18 May, no publication_date | 1,068 |
  | **union** | **2,677** |
  | dump by decision date: Q4/2025 | 1,931 |
  | dump by decision date: Q1/2026 | 2,005 |
  | dump by decision date: Q3/2025 | 23 |

  The union rulings not decided in Q2: 581, all decided in Q1/2026. Every one of the 2,677 is in the branch dump.
- **Needed for D-062:**
  - one `source_snapshot` per input file: hf_bger, bger_neuheiten pages, judgements workbook/exports, models_md;
  - the six populations: `2026Q2_union` (target), `2026Q2_decision`, `2026Q2_publication` (delivery default, D-052), `2025Q4_decision`, `2026Q1_decision` (labelled), `suva_reference`;
  - members with `basis`;
  - freezing with `manifest_sha256`;
  - the twin rule (`-DYYYYMMDD` dropped only when same date; `ruling_source_ref.is_twin`).
- **Branch window vs D-062.** The branch selects by **decision** window 2025-10-01..2026-06-30 plus gold dockets (`B:config.py:107-117`). It has no populations, no exact/approx observation split, and it ingests `legal_area`, `outcome` and `marked_for_publication` from HF (`B:src/suva_data/sources/swiss_caselaw.py:270-276`). D-062 forbids all three.

### 3.3 Segmentation and considerations (D-070), the 4.99 GB risk

- **Not available locally.** `structure/erwaegungen_paragraphs.parquet` is 4.99 GB at the pinned commit, per M:DB_DDL_PLANNING.md §8.2. `structure/structure.parquet` is 6 MB. Neither is local (`find data -iname '*erwaeg*'` returns nothing).
- **Disk.** 6.4 GiB free of 460 GiB (99 % used). Download plus parse plus a DB copy of ~6,000 rulings' considerations will not fit. The planning doc estimates 7-35 min for the download alone (§19.3).
- **Columns are unverified.** "the columns are checked once the file is downloaded (DB-08)", §8.2.
- **What waits on it:** summaries (`source_segmentation_id` NOT NULL), claim citations (G1 trigger, 80:524-541), justification evidence, and `v_ruling.consideration_count`.
- **Workaround (no DDL change):** register the branch's own splitting as `segment` step `own_splitter` **V0.1.0**. Sources: `B:src/triage/reading_prompts.py:23 sections()`, and the consideration handling in `src/summarize/finish.py`.
  - Status `partial`/`ok` is measured, and it becomes primary only if the acceptance criteria pass.
  - A summary_version only needs *a* segmentation, not the primary one.
  - Only `structure.parquet` (6 MB, expected counts) would be downloaded.

### 3.4 Assessments and `in_suva_scope`: the semantic conflict (D-063)

**What D-063 and the DDL want:**
- layer1 → `potentially`/`out_of_scope` (with reason);
- layer2 → `potentially` with `score_0_100 = 100 × P(Ja)/(P(Ja)+P(Nein))`, and one `llm_judgement` row (one llm_call, `p_yes`, `logprob_yes`/`logprob_no`, top_logprobs);
- ranking → `in_scope`/`out_of_scope` at a **frozen F2 threshold** (`triage.threshold.metric DEFAULT 'F2'`, `value_0_100`, `chosen_on_population_id`, `policy`, `frozen_at`).

**What the branch computes:**
- **Layer 1** (`courts.layer1_record`): keep or drop, with no score. The DDL needs a score for drops, because `ranking_entry.final_score_0_100` may be NULL only for a failed judgement (80:432-433), and the comment on `score_0_100` expects "Layer 1: the filter's score for a drop (score_source = net)".
- **Readings.** Six Apertus readings per *core* ruling (UV/MV/IV, not single-judge) (`pipeline.py:132-135`):
  - two are P(Ja)-type: `verdict` is exactly D-063's formula, `yes_strict` is a variant;
  - four are expected levels on a 1-5 scale.
- **Consensus.** The mean of z-scored readings (`scorer.py:55-82`).
- **Score.** `LogisticRegression(class_weight='balanced')` over 8 facts plus the consensus, fitted at each run on Suva's labelled quarters (`scorer.py:101-131`). Kept non-core rulings get a score with consensus 0, which is effectively `score_source='signals_only'`.
- **Cut.** `Scorer.fit` freezes a threshold at 40 % of core rulings on out-of-fold scores (`:121-128`). But `run()` then applies `promote()`, **a top-40 %-per-decision-quarter rank cut** (`pipeline.py:154-161`), not the threshold. Tiers are `suspected_relevant`, `possibly_relevant` and not assessed.

**The conflict, stated plainly:**
- The branch's displayed score is not 100·P(Ja)/(P(Ja)+P(Nein)).
- Its decision is not a fixed score threshold.
- It needs six LLM calls per layer-2 ruling, while `triage.llm_judgement` is 1:1 with the assessment (PK `assessment_id`, one `llm_call_id`).
- The fitted model changes at every run (D-064 component version semantics).

Options for the lead are in §6.3.

### 3.5 Summaries as DE+FR pairs with presets (D-067/D-068)

Needs:
- `summ.preset_version` for `suva_house` (preset row seeded, version not);
- `summary_version` with both texts in one transaction;
- `title_line` rendered by code ("BGer-Urteil <docket> vom <date>" / "Arrêt du TF …", §13.1);
- claims with sections (D-069 adds `application`/`practice` to `src/schemas.py`, "its own PR");
- citations by FK to considerations of the version's segmentation;
- verifier checks (V1-V6 rules).

The branch writes free text per language (`fiche`) with a code checker (`summarize.review`) and finisher (`finish.finish`), and stores no claims or citations. `claims` is not required for a pipeline version (no trigger forces claims), but it **is required for an expert edit** (`create_expert_version` refuses an empty array). Every in-scope ruling of the default pipeline must have a current, non-rejected suva_house pair **before a release can become current** (release gate, 60_views.sql:224-260; 80:225-242). The UI still works without a release, because `v_scope_pipeline` falls back to the latest non-eval run (60_views.sql:69-74).

### 3.6 Expert reviews (D-066) vs the branch's relevance statuses

**Branch statuses** (`B:queries.py:25-30`): `not_assessed`, `potentially_relevant`, `ai_relevant`, `expert_confirmed`, `not_relevant`. Actions: `confirm_relevant`, `mark_not_relevant`, `reopen` (`feedback.py:11,36-78`). The expert decision **overrides** the label (`v_relevance` 001:142-143).

**New model:**
- `gold.expert_review(target_kind='scope', assessment_id, verdict ∈ {correct, incorrect}, reviewed_label ∈ {in_scope, out_of_scope})`;
- written only via `gold.submit_review()` with `app.actor` set (70_functions.sql:44-88);
- it **never** changes the delivered list or the metrics (§12.3);
- `expert_implied_label` flips the label beside it (60_views.sql:105-108).

| Branch status | New pipeline label | Expert action → review |
|---|---|---|
| `not_assessed` (no prediction: layer-1 drop) | `out_of_scope` (layer1, `L1_DROP_*`), **if** layer 1 writes an assessment for every ruling | confirm_relevant → `incorrect`; mark_not_relevant → `correct` |
| `potentially_relevant` (kept, below the cut) | `out_of_scope` (ranking, `RANK_BELOW_THRESHOLD`). **The UI's middle tier disappears**: `potentially` means "not decided or failed", not "possibly relevant". | as above |
| `ai_relevant` (tier suspected_relevant) | `in_scope` (ranking) | confirm_relevant → `correct`; mark_not_relevant → `incorrect` |
| `expert_confirmed` / `not_relevant` | derived: `expert_verdict` + `expert_implied_label` | n/a |

Gaps in that model:
- **`reopen`** has no form: there is no withdraw verdict, only supersede-with-a-verdict.
- A review needs an `assessment_id` and is refused on `potentially`, so rulings with a failed or unfinished pipeline cannot be reviewed.
- `relevance_events.status_before`/`score_shown` become derivable through the assessment.
- `comment` maps to `comment`.
- `reason` (short code) has no column; it could go in `payload` with a V2 schema.

---

### 4. Ingestion now vs what D-062/§8 want

| Aspect | Branch (`src/suva_data`) | D-062 / §8 |
|---|---|---|
| HF repos | `voilaj/swiss-caselaw@35b17aa9` files `data/bger.parquet`, `graph/statute_references.parquet` (`config.py:91-96`, `sources/swiss_caselaw.py:28-29,146-187`, `hf_hub_download` + sha verify). Daily deltas from `…/resolve/main/artifacts/parquet/deltas/YYYY-MM-DD.parquet`, **unpinned** (`sources/hf_daily.py:57-60`). Own published dataset `suva-nga/bger-rulings@7eb6025` (`config.py:97-101`). | Same pinned `bger.parquet`, plus `structure/erwaegungen_paragraphs.parquet` (4.99 GB) and `structure/structure.parquet` (6 MB). No statute graph. |
| Sources and trust | bger_list (Neuheiten pages, tier 1) > entscheidsuche.ch (tier 2) > swiss_caselaw (tier 3), reconciled field by field (`config.py:67-88`, `reconcile.py:123-354`). Canonical text: entscheidsuche for 6,053/6,055. | Base dataset from the pinned HF files only. Neuheiten add `publication_observation` (`neuheiten`) "later" (§8.1, §18). Text source enum still has `entscheidsuche`, but `source_kind` (snapshot) has no entscheidsuche value. |
| Fields | Takes `legal_area`→area, `outcome`, `marked_for_publication`→starred (never canonical), `title`→subject, `source_url`→official_url, `cited_decisions` (`swiss_caselaw.py:267-282`) | Never `judges`, `clerks`, `legal_area`, `outcome`, `marked_for_publication`. Takes decision_id, docket, dates, `scraped_at`, language, title, full_text, appealed_court_raw, cited_decisions, content_hash, source_url. |
| Selection | Decision window 2025-10-01..2026-06-30 + gold dockets + previously ingested dockets (`cli.py:74-80`) | Six populations (decision, publication exact/approx, union, reference), frozen with a manifest |
| `fetch` (`cli.py:57-71`) | network: each adapter writes `data/snapshot/` (bger skipped unless `--include-bger`) | Loader reads pinned files; `source_snapshot` per file |
| `build` (`cli.py:74-149`) | migrate, raw_files, load source_records, reconcile (rulings, canonical texts, conflicts, **deletes stale rulings**), statute_refs, labels, gold, verify invariants, fingerprint vs `data/manifest.json`, quality report | Fresh deploy, then loaders (append-only, uuid5), counts to `results/ingestion.json` + `ops.run_metric`, mismatch fails the run |
| `pull` (`cli.py:236-252`) | `snapshot_download(suva-nga/bger-rulings@7eb6025)`, copies `snapshot/` to `data/snapshot`, and the dump to `db/init/10_suva.sql.gz` (auto-loaded by Postgres on an empty volume, via the compose mount) | No equivalent. Main's compose has **no `db/init` mount**. |
| `ingest` (`cli.py:187-216`, `ingest.py:155-245`) | Publication-date range: bger.ch lists first, then HF daily files, then entscheidsuche mirror; add-only; writes `ingested_rulings`, `ingest_runs` | Not specified in the DDL beyond `ruling.origin`, `publication_observation(source neuheiten/hf_poller)` and `ops.user_request(add_judgement)` for D-015. The DDL has no daily-delta source kind. |
| `dump`/`export` | pg_dump (excl. ingest_runs data) and parquet tables, including labels/gold with D-051 fields | Authored export to `data/derived/authored/` (DB-17). D-031: Suva-derived rows leave the DB only towards `data/derived/`. |

---

### 5. Compose and Makefile, both sides

| | Branch `docker-compose.yml` | Main `docker-compose.yml` |
|---|---|---|
| image | `pgvector/pgvector:0.8.1-pg17@sha256:3e8b3adf…` | identical |
| DB / user | `POSTGRES_DB=suva`, `POSTGRES_USER=suva`, `HOST_AUTH_METHOD=trust` | identical |
| host port | `127.0.0.1:54329:5432` (:14-16) | **none** ("internal-only", M:docker-compose.yml:10-12) |
| init mount | `./db/init:/docker-entrypoint-initdb.d:ro` (:20) | **none** |
| volume | named `pgdata` | named `pgdata` (same name, so the same volume under the same project dir) |
| app | `DATABASE_URL: postgresql://suva@db:5432/suva` | identical |

**Conclusion:** the new DDL deploys onto the same service, database and superuser. `make db-deploy` with `--compose` runs `docker compose exec -T db psql -U suva -d suva` (M:`src/db/deploy.py:53-58`), and the new schemas coexist with `public.*`.

Points to watch:
- `90_roles.sql:45-48` runs `REVOKE ALL ON DATABASE … FROM PUBLIC` and `REVOKE CREATE ON SCHEMA public FROM PUBLIC`. Harmless for the `suva` superuser that the old code uses.
- The new login roles have no password, so trust auth applies. With `suva_api` and `suva_pipeline`, the branch's host-side code (pytest, CLI) still needs the **published port**.
- Merging main's compose as-is would break `config.DATABASE_URL`'s default and silently skip every DB test.

**Makefile targets:**
- Branch: `help run run-live serve smoke-llm warmup crawl triage refit eval eval-private claims check`. **`triage`** is branch-only (B:Makefile:35-36).
- Main: `help run run-live serve smoke-llm warmup crawl refit eval eval-private claims check` plus **`db-up db-deploy db-reset db-test`** (M:Makefile:52-62), with `DB_TARGET ?= $(if $(DATABASE_URL),,--compose)`.

**Conflicting shared files:**
- `pyproject.toml`: main drops fastapi, psycopg, huggingface-hub, openpyxl, scikit-learn and uvicorn, and sets `package=false`.
- `Makefile`, `docker-compose.yml`, `MODELS.md`.

---

### 6. Proposed port order, sizes, risks, and decisions for the lead

### 6.1 Strategy options

| Option | How | Pro | Con |
|---|---|---|---|
| **A. Backfill** | One SQL/Python pass copies `public.*` into the new schemas, then switch reads, then writers | Fastest to a working UI on the new schema; data already validated | Contradicts D-061 ("DB rebuilt from committed files"); carries forbidden fields (legal_area, outcome) and entscheidsuche-primary texts; not reproducible |
| **B. Rebuild via loaders** (recommended for corpus and gold) | Write DB-11 and DB-13 loaders from the local pinned HF file + Neuheiten snapshot + `judgements/`; then port writers and API | D-061/D-062 compliant; the loaders are needed anyway; inputs are already local; counts are verifiable (2,677 reproduced) | More code; HF-primary text breaks the replay cache |
| C. Tee | Writers write both schemas during the transition | No big-bang | Double the code paths; append-only vs is_current mutation makes the two models diverge |

**Recommendation:** B for corpus and gold. Use A only for **authored** rows that already exist in the live DB (expert decisions, expert summary versions): a one-shot, audited migration, if there are any.

### 6.2 Chunks (each independently testable; estimates are rough, for one person)

| # | Chunk | Test | Size | Risk |
|---|---|---|---|---|
| 0 | **Lead decisions** (§6.3). No code. | n/a | n/a | Blocks 7, 9 and 10 |
| 1 | Bring main's `src/db/`, `tests/sql/`, db-* Make targets and the CI job onto the branch. Reconcile compose: keep the 54329 host port; init mount optional. Deploy beside `public.*`. | `make db-up db-deploy db-test` → 8 files pass; deploy twice (idempotent); old `pytest` unchanged | S (1-2 h, mostly merge conflicts in pyproject, Makefile, compose, MODELS.md) | Low |
| 2 | Python store plumbing: `uuid5(namespace 1dd0895a-…)` equal to `ops.uuid5`; `app.actor`/`app.run_id` session helper; run/span context manager (open, close once); role-specific connections | pytest against the DB: Python uuid5 == SQL uuid5 for every key prefix; span close-once trigger; run without a profile refused | S-M (2-3 h) | Low |
| 3 | Minimal registry loader (DB-10 subset). Pieces listed below the table. | Loader runs twice idempotently; `ops.v_profile` lists all pinned steps; a `pipeline_run` can be inserted | M (3-5 h) | **Config, rule and preset shapes are invented here; lead review needed** |
| 4 | Corpus loader (DB-11) from the local `bger.parquet`, plus Neuheiten observations from `data/snapshot/bger_list`. Pieces listed below the table. | Counts **2,677 / 2,096 / 992+1,068 / 1,931 / 2,005 / 23**; the 18 twins; rerun inserts 0 rows | M (3-4 h) | Primary text choice (replay cache); entscheidsuche has no snapshot kind |
| 5 | Gold loader (DB-13): 59 + 1 `gold.label` (cantonal `external_title`), 55 `gold.suva_summary` pairs. D-051 fields never read into the row; https URL built by code. | Counts; `test_no_suva_personal_fields`-style check on the new tables; `gold.v_label_effective` closed-world counts per quarter | S (1-2 h) | Low |
| 6 | Interim segmentation: `own_splitter` V0.1.0 from the branch's section/consideration code, measured against `structure.parquet` (6 MB) | count-match and coverage ratios stored; primary only if ≥ 99 % and ≥ 98 % | M (3-4 h) | **Unknown match rate.** The 4.99 GB path needs free disk (6.4 GiB now). |
| 7 | Triage writer (DB-14), replay mode. Pieces listed below the table. | 3-real-ruling test (G6); every assessment has a span and its pinned version; `v_scope_pipeline` covers all population members; replay with **no live call** | M-L (4-6 h) | **Depends on the D-063 decision**; a cache miss if the primary text changed in chunk 4 |
| 8 | API read port: `queries.py` list/facets/workspace on `corpus.v_ruling` + `triage.v_scope_current` + `summ.v_summary_current`; uuid ids in the API and `api.ts`; status mapping; outcome shown as unknown | the queries tests, rewritten (needs your OK) | M (3-4 h) + S UI | UI tier change (no "possibly relevant") |
| 9 | Expert relevance writes → `gold.submit_review` as `suva_api`; reopen per decision; learning counts | Review on in_scope/out_of_scope OK; on potentially refused; `suva_api` cannot UPDATE an assessment | S-M (2-3 h) | reopen semantics |
| 10 | Summary writer (DB-15) + workspace: generate/revise as pair versions with `llm_call` rows (from the client's `LLMResult`/`llm_calls.jsonl`); expert edit via `create_expert_version` (claims); confirm → `validated`; revision reasons per decision | Pair trigger at commit; expert edit makes a new current version; few-shot hygiene trigger | M-L (5-7 h) | Claims for free-text edits; synchronous API writes vs roles |
| 11 | Live ingest port (`ingest.py`, `updates.py`) onto `pipeline_run(kind='ingest')`, observations, `origin` | `test_ingest`-style with recorded fixtures, no network | M (3-4 h) | Rebuildability (D-061) |
| 12 | Retire old migrations, `public.*` readers, `stub.py`, `export`/`dump`/`pull`; replace old tests (with your OK) | full `make check` + `make db-test` | S-M | Losing statute_refs and conflicts |

Pieces of chunk 3 (registry loader):
- MODELS.md parsed into `ops.model`, with a `models_md` snapshot;
- json_schemas (step_config ×6, rule_definition, preset_config);
- component_versions V0.1.0: ingest, segment (own_splitter), layer1_filter (courts.py + area_judge), layer2_judge, ranking, summarise;
- the D-060 layer-1 reason codes and rules;
- prompt_versions (readings, area_judge, summary prompts);
- the `default` profile V0.1.0;
- the `suva_house` preset_version V0.1.0.

Pieces of chunk 4 (corpus loader):
- `corpus.ruling` (uuid5), `ruling_source_ref` (twins), `publication_observation` (neuheiten, hf_poller, hf_first_seen);
- `ruling_text` (HF primary, entscheidsuche kept as a second row if its snapshot kind is decided);
- the six populations + members.

Pieces of chunk 7 (triage writer):
- layer1 assessments for **every** ruling (+ reasons, area_judge llm_calls);
- layer2 per the decision;
- threshold, ranking per population, ranking_entry, ranking assessments;
- `make triage` writes to the new schema.

Critical path: 1 → 2 → 3 → 4 → 5 → (6 ∥ 7) → 8 → 9 → 10 → 11 → 12. Chunks 8 and 9 can start once 7 has written a real run. Total is roughly **35-50 h**. That is above the planning doc's own estimate (DB-10..16 ≈ 10.5 h, §19.3), which did not include rewriting the branch's UI and workspace semantics.

### 6.3 Riskiest assumptions, and DDL points that need the lead's decision

**Score form (D-063 vs the branch scorer).** Three options:
- **(a) Literal D-063.** layer2 `score_0_100` = 100 × `verdict` reading; `llm_judgement` = that call. The logistic regression over facts + consensus becomes the **ranking** step's `final_score_0_100` (the column comment allows "Ranking: the final score"). Threshold = 100 × `Scorer.threshold` (frozen on out-of-fold scores), applied globally. The five other readings become `ops.llm_call` rows without a detail table. The per-quarter 40 % cut is dropped, so measured results change.
- **(b)** Ask the lead to reopen D-063 for the score form (its own "revisit when D-021 settles another score form").
- **(c)** Six layer2 assessments via `repetition_idx` 0..5. Not recommended: it abuses G10 repetition semantics.

Also, layer-1 drops need a numeric score (`score_source='net'`); the branch has none (propose 0).

**DDL gaps that would need a DDL change:**
- **Enums.**
  - `ops.source_kind` lacks `entscheidsuche`, HF daily deltas and the statute graph.
  - `ops.model_role` and `ops.model` cannot hold the scikit-learn scorer.
  - The fitted scorer changing at every refit forces a new `component_version` per run, or its coefficients go in run params. Not covered by D-064.
- **Summary dependencies.**
  - `summary_version.source_segmentation_id` NOT NULL ties every summary to segmentation (D-070, the 4.99 GB file, and 6.4 GiB free disk). Confirm that an `own_splitter` V0.x segmentation is acceptable for the interim.
  - `create_expert_version` requires non-empty claims (section, paragraph_no, cites). The branch's expert edits are free text. Either the UI collects claims, or the function accepts paragraph-level claims with `section` inferred. That is a function change.
- **Expert semantics.**
  - Branch actions without a form: `reopen` (relevance), `unconfirm` (summary), and reviews on `potentially` / not-yet-assessed rulings.
  - The revision-request reasons (9 codes plus a note) have no home. This is the user's "self-improvement is core" requirement (memory: Suva UI brief). Options: a V2 `summary_review.payload` schema (no DDL change), or a table.
- **Roles vs synchronous API.**
  - `suva_api` may only execute `submit_review`, `create_expert_version` and `submit_request`.
  - The branch API generates and revises summaries, and starts ingests, **inside the request**.
  - Either the API uses `suva_pipeline` for those calls (weakens D-071), or the work goes through `ops.user_request` plus a worker (more moving parts, and a UX change from synchronous to queued).
- **D-061 rebuildability vs live ingest.**
  - Rulings added by `ingest` come from git-ignored `data/raw/live`.
  - It is unclear whether they are `base_dataset` or `user_added`, and how a fresh deploy reproduces them.
- **Fields the UI and eval use but D-062 never ingests:** `outcome` (UI column, filter, facet; eval judge), `cited_decisions` (§8.1 lists it but the DDL has no column), `statute_refs`, `conflicts`, `field_sources`.
- **Primary text: HF vs entscheidsuche.**
  - D-062 implies HF; the branch uses entscheidsuche.
  - Switching changes every prompt, so the replay cache misses everywhere. Replay then needs live calls, which affects cost and judges' reproducibility.
- **Compose.**
  - Main removed the host port and the `db/init` auto-load.
  - The branch's host-side code and tests depend on `localhost:54329`, and DB tests skip silently without it.
- **Possible view subtlety.** `triage.v_scope_pipeline` (60_views.sql:62-94) orders candidates by `prio, step DESC, created_at DESC` across **all** non-eval runs of the default profile. So a ranking assessment from an older run outranks a newer run that has only reached layer 1. This may be intended ("furthest step"), but it means a partial rerun does not refresh the label. Worth confirming.

**Process.**
- Retiring or rewriting the branch's old-schema tests (12 files, ~167 tests) conflicts with "never edit existing tests to make them pass". It needs your explicit OK per chunk.
- **Before chunk 1: D-051/D-031.** `db/init/10_suva.sql.gz` (= `data/publish/dump/suva.sql.gz`) and `data/publish/tables/{labels,gold_summaries}.parquet` contain `sharepoint_url` and `author` (110/110 rows). `config.py:97-101` describes `suva-nga/bger-rulings` as a public HF dataset with a pinned upload `7eb6025`. Check whether that upload holds these files. If it does, this needs the lead now, independent of the port.
