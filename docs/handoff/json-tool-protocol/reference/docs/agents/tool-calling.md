# Role brief: TOOL CALLING (Apertus structured outputs and tool calls)

> **Status: v0 PROPOSAL (27 Nov 2026).** The lead created this area on 27 Nov 2026 and gave it to one owner: `<handle>`, an agent working for a team member (if you do not know that member's GitHub handle, ask before step 1). Step 1 records it as a row of `AGENTS.md` §5 and as the decision D-058, through a PR the lead approves. D-024 stays open for the other areas.
>
> Read `AGENTS.md`, `docs/STATE.md`, `docs/EVENT.md`, `docs/DOCTRINE.md` and `docs/DECISIONS.md` first, then `docs/LESSONS.md` §1 (K2, K3, K4, K10, K11, K12, K14), `docs/ARCHITECTURE.md` §3-4 and `docs/EVAL.md` §1, §3b and §7. Then read the handoff, `tmp/json-tool-protocol/HANDOFF.md`, which is outside git (§3 and §5 to §11 at least).

## Mission
Make Apertus's structured outputs and tool calls dependable on every endpoint the pipeline meets: Keera today, and the judges' endpoint at evaluation (Q-23). Apertus proposes one JSON object. Code parses it, validates it, and resolves every id exactly against the list it offered (G1). It allows one repair turn, then fails closed.

Measure native tool calling against this protocol honestly, and keep the protocol from regressing. Serve the stages that use it: the triage justification, signal tagging and summary claims.

The relevance score is never yours. It is not produced by this protocol, whatever D-021 point 4 decides.

## You own
- **`src/llm/tool_protocol/`**, the package and its `README.md`: the tolerant parser, closed id tables, the strict schema profile, validation, the format block and the repair turn, `propose` and `run_tools`.
- **`tests/tool_protocol/`**: unit, hardening, contract, golden, property, doctrine, doctest and live tests. This includes the wire snapshots `golden/wire_*.schema.json`, the synthetic golden replies, and the example contracts and check (`contracts.py`, `checks_example.py`) until step 5.
- **`eval/tool_bench/`**: cases, tools, runner, scorer, `thresholds.json` and `README.md`, and also `tests/tool_bench/`. This is carved out of the evaluation area. The eval owner keeps `docs/EVAL.md`, its statistical method (EVAL §1.4 worst repetition, §1.5 bootstrap) and `make claims`.
- **`results/tool_bench/<run>/report.md` and `report.json`**, aggregates only.
- **The probe items about structured outputs**, which you define and platform merges (step 6). The probe and its output `results/gateway_probe.json`, `json_tier` included, stay platform's; you read `json_tier`.

## You contribute by PR to another owner (G7)

| File | Approved by | What you bring |
|---|---|---|
| `AGENTS.md` §2 and §5, `docs/agents/`, `docs/DECISIONS.md` | lead | **Step 1.** This brief, `tool-calling` in the role list, and your row in §5. The exclusions in two existing rows: lead/platform keeps `src/llm/` **except** `src/llm/tool_protocol/`, and evaluation keeps `eval/` and `results/` **except** `eval/tool_bench/` and `results/tool_bench/`. Also D-054 to D-058 (texts in HANDOFF §10.2) |
| `NOTICE` | lead | **Step 2.** `tmp/json-tool-protocol/NOTICE.fragment` (the ArchAI MIT notice and the credits), in the same PR as the code it covers (G14) |
| `pyproject.toml`, `Makefile`, CI, `.gitignore` (append only, D-044) | platform, lead | **Step 2.** Test paths, the `live` marker, the ruff settings, `make bench-tools`, and the ignore lines below |
| `src/llm/__init__.py`, `eval/__init__.py` | platform, eval | **Step 2**, only if the repo has none. The reference's files are one-line docstrings |
| `MODELS.md` §2 | lead | **Step 2.** The development tool and model that wrote the reference (below) |
| `src/llm/client.py` (or a separate `src/llm/chat_fn.py`: platform's call) | platform | **Step 4.** `chat_fn(model) -> ChatFn`. It maps `ChatRequest` to `/chat/completions` (`response_format`, `tools`, `tool_choice`, `parallel_tool_calls`). It returns `ChatReply` with `mode` set to `LIVE` or `REPLAY`. The `RequestRejected(kind)` kinds and `TransportFailure` go **inside** the client's single error classifier (G3). The replay key includes `cache_salt`, which is never sent. What the cache stores follows D-057 |
| `src/llm/probe.py`, `make smoke-llm` | platform | **Step 6.** The probe items of HANDOFF §5.3, and `RUN_LIVE=1 pytest -m live tests/tool_protocol` inside `make smoke-llm` |
| `src/schemas.py` | platform | **Step 5.** The three `Tool` contracts (`JUSTIFY`, `TAG_SIGNAL`, `SUMMARY`), once D-055 and D-056 are settled |
| `data/public/` | crawl | **Step 7.** The benchmark's input file, git-ignored, and its selection command reading DS3 |
| `make claims` | eval | **Step 11.** Read `results/tool_bench/<run>/report.json` for the report's §3 sentence |
| `docs/LESSONS.md`, `docs/ARCHITECTURE.md` | lead | **Steps 5 and 11.** HANDOFF §10.3 and §10.4 |
| `docs/STATE.md` | lead (with platform) | One line per milestone |
| `technical_report.md` §3 and §8 | pitch, lead | The "Use of Apertus" paragraph (HANDOFF §10.4), with numbers from `make claims`, and the model declaration |

## Not yours
- **Triage** owns the score (S4) and its prompt, `src/triage/` and `prompts/triage_*`. It also chooses which rulings get a JSON justification, together with D-021 point 6.
- **The verifier's owner** (`AGENTS.md` §5) owns the checks in `src/verify/`: the `Check` callables passed to `propose`.
- **Summarise** owns the summary prompts.
- **The stage owner** writes the task text given to `propose` (`system=`, `user=`), in `prompts/`. Yours is what the package adds around it: the format block, data delimiting and neutralisation, and the repair turn.
- **Platform** owns the client's core: configuration, timeouts, retries and back-off, the limiter, the served-model check, `llm_calls` and the replay cache.

## Interfaces you hold with the others
- **With platform.** `ChatFn = Callable[[ChatRequest], ChatReply]`, `RequestRejected(kind)` and `TransportFailure` are all defined in `llm.tool_protocol.protocol`, and the client imports them. A change to them needs both owners.
- **With triage, summarise and the verifier.** `propose(chat, tool, *, system, user, purpose, prompt_version, tier, id_tables, caps, item_level, checks, context, field_notes, language_note, max_tokens, max_tokens_cap, repair_turns, cache_salt) -> Outcome`.
  - `Outcome` carries `status` (`ok`, `ok_repaired` or `failed`), `value`, `reason`, `tier`, `attempts`, `problems`, `repairs`, `dropped` and `trace`.
  - A check has the type `Check = Callable[[value, context], Sequence[Problem]]`. A non-fatal problem must name an item of an `item_level` array in its `drop_path`; otherwise the protocol makes it fatal.
  - The stage owners count `status` and `reason` per run.
  - The score and the justification live in **separate modules**: `test_score_path_does_not_import_the_protocol` fails on a module outside `src/llm/` that asks for log-probabilities and also uses the protocol.

## Inputs
- **The handoff folder**, unzipped into `tmp/json-tool-protocol/` of your clone (git-ignored by the kit's `.gitignore` block). It holds:
  - `HANDOFF.md`, the detailed reference ("HANDOFF §n" below points to it);
  - `NOTICE.fragment`;
  - the reference implementation v0.2.1 under `reference/`, whose paths mirror the repo;
  - the 27 Nov smoke reports under `smoke/`. They ran on DS7 and are **not a measurement** (EVAL §3b);
  - ArchAI's original files under `upstream/archai/` (MIT, reference only).
- **Gateway facts** in `docs/LESSONS.md`:
  - K2: strict mode works when every object has `additionalProperties: false`.
  - K3: keys are generated in alphabetical order, so field names carry `a_`, `b_` and `c_` prefixes to fix the generation order.
  - K4: native tool calling makes one call per turn.
  - K10: the 70B is not deterministic at T = 0.
  - K11: one system message, thinking off.
  - K12: nested lists are not probed yet.
  - K14: there is a prefix cache.
- **From platform:** the client and the probe. Until the client exists, the module lands and its offline suite runs, and the live steps wait.
- **From crawl:** DS3 (`docs/DATA.md` §10, texts and considerations), for the benchmark's input sample (step 7). Until DS3 exists, only the offline suite and the live contract tests run.
- **From the lead:** the answer to Q-23 (the judges' endpoint). Until then, skip the probe items aimed at the judges' endpoint.

## Files to create in the repo (copy map)
Source paths are relative to `tmp/json-tool-protocol/reference/`. Copy the files unchanged unless the row says otherwise.

| Source | Destination | Note |
|---|---|---|
| `src/llm/tool_protocol/` (7 modules and `README.md`) | `src/llm/tool_protocol/` | stdlib only, no runtime dependency |
| `src/llm/__init__.py`, `eval/__init__.py` | same paths | only if the repo has none (platform and eval approve) |
| `tests/tool_protocol/`: `__init__.py`, `checks_example.py`, `contracts.py`, `fakes.py`, `golden/` (3 wire snapshots and `replies.jsonl`), and every `test_*.py` **except** `test_client_mapping.py` | `tests/tool_protocol/` | the contracts stay here until step 5 moves them to `src/schemas.py` |
| `tests/tool_protocol/test_client_mapping.py` | not copied as is | its assertions move to the client's tests in step 4 |
| `eval/tool_bench/` (5 modules, `thresholds.json`, `README.md`) | `eval/tool_bench/` | if the team moves `eval/` under `src/` (`AGENTS.md` §4, PROPOSED), it moves with it; the tests find it by import |
| `tests/tool_bench/` (`__init__.py`, `fakes.py`, `test_bench.py`) | `tests/tool_bench/` | |
| `pyproject.toml` | **merged**, not copied | see "Settings to merge" |
| `docs/agents/tool-calling.md` | `docs/agents/tool-calling.md` | this brief (step 1) |
| `../NOTICE.fragment` | appended to `NOTICE` | step 2, with the lead's approval |

### Settings to merge
These go into platform's files, and their owner approves.
- **pytest.**
  - Set `pythonpath = ["src", "."]`, or the skeleton's equivalent.
  - **Append** `tests/tool_protocol` and `tests/tool_bench` to `testpaths`.
  - Add the marker `live: calls the gateway; run with RUN_LIVE=1 pytest -m live`, and add `-m 'not live'` to the repo's own `addopts`.
  - The live tests also skip unless `RUN_LIVE=1`, so a command that passes its own `-m` still cannot reach the gateway.
- **ruff.**
  - The code uses lines up to 120 characters. Platform chooses between two settings:
    - the repo sets `line-length = 120`;
    - or `[tool.ruff.lint.per-file-ignores]` gets `"src/llm/tool_protocol/**" = ["E501"]`, `"eval/tool_bench/**" = ["E501"]`, `"tests/tool_protocol/**" = ["E501"]` and `"tests/tool_bench/**" = ["E501"]`. In that case, also run `ruff check --fix --select I` on those four folders in the import commit: it only rewraps 2 import blocks (checked on a simulated port).
  - Docstrings are checked by a step of `make check`, whatever the repo selects elsewhere: `ruff check --no-cache --select D --ignore D105,D107 --config 'lint.pydocstyle.convention="google"' src/llm/tool_protocol eval/tool_bench`.
- **Imports.** The code assumes that `src/` and the repo root are both on the import path (`llm.tool_protocol`, `eval.tool_bench`). If the skeleton uses another convention, adapt the imports mechanically in the import commit and change nothing else.
- **Development dependencies.** `pytest`, `hypothesis`, `pytest-cov` and `ruff`. `pydantic` is already in the stack (D-035). Without it, 2 tests skip: one in `test_hardening.py`, one in `test_schema_ids_validate.py`.

### Ignore lines
Append these to `.gitignore` in step 2. Git has no brace expansion, so each file needs its own line.
```gitignore

# --- Added for tool calling (docs/agents/tool-calling.md; D-044: appended, never replacing) ---
results/tool_bench/*/cases.jsonl
results/tool_bench/*/rows.jsonl
results/tool_bench/*/replies.jsonl
results/tool_bench/*/partial.jsonl
data/public/bench_rulings.jsonl
.hypothesis/
.coverage
.coverage.*
htmlcov/
```
Check them with `git check-ignore -v results/tool_bench/x/rows.jsonl data/public/bench_rulings.jsonl .hypothesis/x .coverage`.

### Model declaration
`MODELS.md` §2 needs one row (event rule E6).
- **What it declares.** The reference implementation, its tests, the benchmark and the two reviews of this handoff were written on 27 Nov 2026, during the event, outside the repo, with Claude Code and the model Claude Opus 5.5.
- **Whose row.** Add it under the handle of the member whose session produced it; ask the lead which handle that is.
- **The commit.** Label the import commit "imported from the json-tool-protocol handoff, reference v0.2.1".
- **The report.** Its §8 copies the row (pitch owner).

## Never commit
- **Secrets and addresses.** No key, no `.env`, no internal hostname and no gateway URL, in code, tests, prompts, logs or fixtures (G13). Live runs read `LLM_*` from the environment. Public links in `NOTICE` and in the credits are fine.
- **Benchmark run files.** Commit `report.md` and `report.json` only, never `results/tool_bench/*/cases.jsonl`, `rows.jsonl`, `replies.jsonl` or `partial.jsonl`: they hold dockets and excerpts and can be regenerated. Keep the run folders on your machine for the whole event, because they are your non-regression baselines. If you change machines, copy them by hand, never through git.
- **`data/public/bench_rulings.jsonl`.** A committed selection command and seed rebuild it from DS3, and its SHA-256 checks it (step 7). Committing it would duplicate DS3 text that the snapshot already holds.
- **Suva data and DS7.** Nothing from `judgements/`, `data/derived/` or `data/private/`, and none of DS7's texts or labels (EVAL §3b).
- **Goldens and fixtures stay synthetic** (G13, D-031, D-051). Export a real reply as a golden only from a public ruling outside DS7 and outside the labelled quarters, after reading it.
- **The benchmark's replay cache and its `llm_calls` rows** (ARCHITECTURE §4 item 8; D-031 when a prompt holds Suva material).
- **The handoff itself:**
  - `tmp/json-tool-protocol/`;
  - `examples/`, which would call the gateway outside `src/llm/` (G2);
  - `upstream/`: the MIT notice travels in the file headers and in `NOTICE`;
  - `smoke/`: DS7, not a measurement;
  - the reference `conftest.py`: use `pythonpath` instead;
  - `HANDOFF.md` and `BOOTSTRAP.md`: their lasting content lands through the PRs above.
- **Caches:** `.hypothesis/`, `.coverage`, `htmlcov/`, `.pytest_cache/`, `.ruff_cache/` and `__pycache__/`.

## Steps, in order (this is the validation order)
Make one small PR per step. Stop at a step whose input is missing and report it instead of working around it. Missing inputs include no client, no DS3, no announced slot, or no answer to an open question the step needs.

Steps 1 to 9 belong before the feature freeze, Sat 12:00 CET (D-027, fixed while open). After it, only fixes.

0. **Preconditions.** `AGENTS.md` is at the repo root, and `git check-ignore -q tmp/json-tool-protocol/HANDOFF.md` succeeds. Otherwise stop: the kit and its `.gitignore` block land first (`docs/agents/platform.md` step 3).
1. **Docs PR (the lead approves).**
   - Add this brief as `docs/agents/tool-calling.md`.
   - Add `tool-calling` to the role list of `AGENTS.md` §2.
   - Add this row to §5: `| Apertus tool calling (src/llm/tool_protocol/, eval/tool_bench/, tests/tool_protocol/, tests/tool_bench/, results/tool_bench/) | <handle> | |`. Write the exclusions into the lead/platform row and the evaluation row.
   - Add to `docs/DECISIONS.md`, from HANDOFF §10.2: D-054 (PROPOSED), D-055, D-056 and D-057 (OPEN), and D-058 (DECIDED by the lead).
   - At the top of the PR, list the open questions below, each with its options and your recommendation.
2. **Offline import PR.**
   - Apply the copy map and the settings. Append the ignore lines and the `NOTICE` fragment, and add the `MODELS.md` §2 row.
   - Add `make bench-tools PROFILE=quick|full`. It prints `--dry-run` first and passes `--all` only when asked (HANDOFF §5.4).
   - Done when `make check` is green for the two test paths, with pydantic installed: **246 passed, 1 skipped, 6 deselected**. The skip is the score-path doctrine test, which skips until a score module exists. The 6 deselected are the live tests.
   - Ruff is clean, and so is the `D` command above.
   - Branch coverage of `src/llm/tool_protocol` is ≥ 90 % (96 % on a simulated port).
3. **Red, then green (G9).**
   - In a scratch branch, break the parser: let it return a nested object of a broken reply (HANDOFF §7 row 1).
   - Break the validator too: make it skip `anyOf`.
   - Show the pitfall tests red: `test_nested_object_of_a_broken_reply_is_never_returned`, `test_ref_and_optional_are_validated_not_waved_through` and their neighbours.
   - Restore the code, show them green, and paste both logs into the PR.
4. **Client wiring PR (platform approves).**
   - Add `chat_fn(model)`, as the client row of the PR table says.
   - Port the assertions of `test_client_mapping.py` to the client's tests:
     - 400 responses are classified;
     - `HTTPError` is caught before `URLError`;
     - `Retry-After` is honoured on 429;
     - 401, 403 and 404 are never retried;
     - there is no default URL;
     - `mode` is set.
   - Done when the client's tests are green and `grep -rn "chat/completions" src eval` hits only `src/llm/`.
5. **Contracts PR (platform and lead approve).**
   - Raise D-055 (the label and signal shapes) and D-056 (the validator).
   - Once their owners settle them, move the three contracts to `src/schemas.py` and point the test imports at it.
   - Regenerate the snapshots with `UPDATE_GOLDEN=1 pytest tests/tool_protocol/test_golden.py tests/tool_protocol/test_schema_ids_validate.py`. Review the diff line by line.
   - Amend ARCHITECTURE §3 and §4 item 7 in the same PR. Amend §4 item 8 when D-057 is settled.
   - D-027 anchors the contracts freeze on Fri ~16:00, so `src/schemas.py` may already be frozen. Adding the contracts is then still a PR its owner approves (G7). A change to a frozen field, such as D-055's label, keeps the frozen shape until that approval.
   - This step does not block steps 6 to 10. Rerun step 6 after it.
6. **Live contract tests (12 calls or fewer).**
   - Send the probe items to platform by PR. Skip those aimed at the judges' endpoint until Q-23 names it.
   - Then run only `RUN_LIVE=1 pytest -m live -s tests/tool_protocol`, with the `LLM_*` variables set.
   - Do not run the whole `make smoke-llm` outside an announced slot: it includes the concurrency ramp.
   - Done when the 6 live tests are green at STRICT on both models, none was served from the replay cache, and the first-attempt count is reported. They check the format only.
   - A failure is re-run **once**, with a new `LIVE_SALT`. A second failure is a finding: report it with the trace hashes and the `llm_calls` rows. Never re-run until green (HANDOFF §8.7).
7. **Benchmark inputs (needs DS3; crawl approves).**
   - Write a selection command that draws, with a written seed, 30 to 50 public 8C and 9C rulings from DS3, with at least 10 per language.
   - Exclude the 33 rulings of DS7 (`eval/smoke_set.txt`) and every ruling of Q4/2025 and Q1/2026 under **both** date definitions (D-050). The selection never reads Suva's labels (HANDOFF §9.4).
   - The output is `data/public/bench_rulings.jsonl`. Check one record by eye. The loader numbers considerations that have no `id`.
   - Commit the command, the seed and the SHA-256.
8. **Quick benchmark.** Run it with `--dry-run` first, then for real:
   ```
   python -m eval.tool_bench.run --rulings data/public/bench_rulings.jsonl --profile quick --all \
       --models apertus-v1-5-70b apertus-v1-5-8b --out results/tool_bench/quick_<date>
   ```
   - It checks the plumbing and measures nothing. It costs about 200 calls (the 27 Nov smoke used 199), within your share.
   - Exit 3 means some replies came from the replay cache, so the run is not a measurement. Fix the client's salt handling first.
9. **Full benchmark, in a slot announced to the team** (D-030). Run it outside the overnight run and before the feature freeze.
   - Run the same command with `--profile full --reps 2 --all` and `--out results/tool_bench/full_<date>`. Expect about 1,880 calls, 3.5 M input tokens and 25 minutes at 4 concurrent calls (estimates scaled from the smoke).
   - Commit `report.md` and `report.json`.
   - The thresholds T1 to T7 of `thresholds.json` are judged on the worst repetition. `score.decide()` writes `keep_json`, `native_candidate` or `insufficient_n`.
   - Report the verdict to the lead: it confirms D-054, or triggers its "revisit if".
   - Each run has its own salt, so no reply is served from an earlier run.
10. **Quick baseline.** Right after the full run, run one quick profile on the same file and seed. From then on, compare a quick run with this quick baseline, and a full run with the full one.
11. **Docs PRs (the lead approves).**
    - Add the measured verdict to D-054.
    - In `docs/LESSONS.md`, update K4 and K12 and add the two new rows. Replace the smoke's numbers with the full run's numbers.
      - If the file already has K17 and K18, take the next free numbers.
      - If it ends at K16, ask the lead whether K17 and K18 are still reserved for the team's gateway test report.
    - Make the ARCHITECTURE edits that step 5 did not make.
    - Add a `docs/STATE.md` line, and the report's §3 paragraph through `make claims`.
12. **End to end, with triage, summarise and the verifier (G6).** Run 3 real rulings through each stage that uses the protocol: one German, one French and one Italian. Done when the stored outputs are non-empty and the statuses and reasons are counted per run.
13. **After a later change:**
    - **Parser, validator, format block, repair turn, client mapping or model:**
      - Rerun the quick profile on the same rulings file and seed.
      - Then run `python -m eval.tool_bench.score --compare <baseline>/rows.jsonl <new>/rows.jsonl`.
      - Exit 0: no regression. Exit 1: a regression; fix it or write a decision entry. Exit 2: the cases differ; fix the inputs and do not read the numbers.
    - **A contract or a stage prompt:** the benchmark does not exercise these, because it uses its own tools and prompts. Rerun the live contract tests (step 6), and ask the stage's owner for its own evaluation (`docs/EVAL.md`).
    - Bump `__version__` (minor for a behaviour change, patch for a fix) and the `prompt_version` of every affected contract.

**Definition of done for each PR** (`AGENTS.md` §7). Until step 12, no stage calls the protocol, so the "3 real rulings" box cannot be ticked. Each earlier PR says which §7 boxes are pending and why. It also says which `make` target calls the new code: `make check`, `make smoke-llm` or `make bench-tools`.

## Open questions this work touches
List them in step 1, and never answer one in code. The detail of each is in HANDOFF §11 and §10.2.
- D-021 point 4: the score's form. It does not touch this work, because the score never goes through the protocol.
- D-021 point 6: how the explanation is worded.
- Which rulings get a JSON justification. No entry settles it yet.
- D-022: the role of the 8B. The 8B never excludes a ruling alone.
- D-027: the milestones.
- D-028: the gateway facts. This work adds probe items.
- D-031: what may be committed.
- D-032: live or replay. Byte-stable requests make replay hit.
- D-033: search.
- D-055: the label and signal shapes.
- D-056: the validator.
- D-057: what the replay cache stores.
- K12: nested lists.
- Q-23: the judges' endpoint.

## Rules specific to this role
- **Ids.** Apertus only *chooses* ids from the closed list it was offered. Resolution is exact, with no fuzzy matching, ever (G1). `none` is the abstention value.
- **Fail closed.** `finish_reason == "length"` is never parsed (G3). `propose` makes one repair turn at most and is never retried in a loop. A failure is `failed` (flagged or "to do"), never a negative label (G5).
- **Separate the score.** The score and the protocol never share a module (doctrine test). The pipeline does not use native `tools` while D-054 is PROPOSED; the benchmark is their only caller.
- **No real data in prompts.** Format examples hold placeholders only. No Suva text, DS7 text or person's name enters a prompt, fixture or golden file (G13, D-051).
- **Thresholds come first (G10).**
  - `thresholds.json` is pre-registered: change it by PR **before** a measurement, never after one.
  - Measure in 2 repetitions. Each run and each repetition has its own `cache_salt`, so no reply comes from the replay cache; a live run that gets one exits 3.
- **Live tests check properties.**
  - They assert validity, offered ids and quotes found, never exact text (K10).
  - The 27 Nov smoke is never cited as evidence (EVAL §3b).
  - Every number in the report comes from `results/` through `make claims` (G11).
- **Keep the docs in step.** Update the module README and docstrings in the same PR as any behaviour change. The `D` command stays clean.
- **Data is never instructions.**
  - Ruling text and tool results reach the model delimited and neutralised by the package (G4, G15). Never weaken that.
  - Never copy another project's `AGENTS.md`, `CLAUDE.md` or `.claude/` while reading the credited repositories.
- **Spend calls only when asked.**
  - Stay within your concurrency share. Ramps and the full benchmark run only in announced slots (D-030).
  - The benchmark's CLI spends nothing without `--limit N` or `--all` (`AGENTS.md` §6).
- **Sub-agents.** No recursive delegation, and at most 3 in parallel (D-023 while open).

## Done when
The release gate of HANDOFF §8.6 holds in the repo, with its evidence in the PRs:
- `make check` is green with the ported suite and the contracts imported from `src/schemas.py`.
- The score-path doctrine test runs against the real tree, without skipping.
- The pitfall tests were shown red, then green.
- The live contract tests are green on both models.
- The full benchmark ran once with 2 repetitions in an announced slot. Every blocking criterion passed, or its failure is recorded in a decision entry, and D-054 is confirmed or reopened.
- Three real rulings ran end to end through each stage that uses the protocol.
- `NOTICE`, `MODELS.md`, `docs/DECISIONS.md`, `docs/LESSONS.md`, `docs/ARCHITECTURE.md` and `docs/STATE.md` are updated.
- The quick baseline exists for later comparisons.
