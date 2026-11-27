# `eval/tool_bench`: native tool calling vs the JSON protocol

Owner: `tool-calling` (`docs/agents/tool-calling.md`); the statistical method follows `docs/EVAL.md` (owner: `eval`).

Measures, on the gateway, how well Apertus calls tools in each configuration, per model and language,
so that the choice of protocol rests on our own numbers.

## What it measures

| Category | Example (German template) | Gold | What it tests |
|---|---|---|---|
| `simple` | "Zeig mir den Wortlaut von E. 4.2." | `get_consideration(a_id="c7")` | one call, the right id from a closed list |
| `simple` | "Was steht in Art. 6 LAA?" (French) | `find_article(a_act="UVG", b_number="6")` | act names across languages |
| `parallel` | "Zeig mir E. 3 und E. 5.1." | two calls | several calls in one turn (native: one per turn, K4) |
| `parallel_multiple` | "Zeig mir E. 2 und was Art. 6 UVG sagt." | two different tools | |
| `irrelevance` | "Wie spät ist es gerade?" | no call | restraint: correct only if **no call is emitted** (a call validation refused still counts) |
| `evidence` | "Welche Erwägung enthält wörtlich diese Stelle: «…»?" | `c12`, or `none` | **the pipeline's own shape**: choose one offered id or abstain |

Evidence gold is computed by code: the passage (10 words) occurs in exactly one consideration
excerpt; for `none` cases the passage comes from another ruling and occurs in none.

Configurations: `json_strict` (Tier.STRICT), `json_object` (Tier.OBJECT), `native_auto`
(`tools`, `tool_choice: "auto"`, `parallel_tool_calls: true` for the call categories),
`native_forced` (`tool_choice` naming the tool, evidence only). The JSON form calls (evidence) get
the pipeline's single repair turn; the loop and native calls get none, so **every native-vs-JSON
comparison uses `exact_first`** (first reply only). Prompt version `tool_bench-2`: the evidence
system prompt names the tool in every configuration.

Per row, two scores: `exact_raw` (calls as written: `E. 4.2` or `LAA` count as wrong) and `exact`
(after the protocol's validation: exact id resolution, act aliases, refusal of invalid calls). Also:
`valid`, `invented_ids` (not resolvable), `noncanonical_ids` (a resolvable alias),
`accepted_invalid_ids` (computed from the case data, not from the validator's table; must be 0),
`unknown_tools`, `leaked_tool_text`, `text_exact` (a native evidence answer given as plain text:
was the id it names right? recorded, never credited), latency.

## Inputs

`--rulings` takes JSONL ruling records with `docket`, `language` and `considerations`
`[{id, e_number, text}]` (or a raw `text` the fallback splitter can handle). **Every other field is
dropped on load.** A consideration without `id` gets `c1` … `cN` in order; its number is read from
`e_number` or `number` (OpenCaseLaw's `structure/erwaegungen_paragraphs` records have no `id`).

**Selection (D-031, EVAL §3b).** Draw a random sample (seed written down) of public 8C and 9C
rulings from DS3, at least 10 per language, **outside** the smoke set DS7 and the labelled quarters
Q4/2025 and Q1/2026. Never select by Suva's lists, labels or summaries. Keep the file out of git: a committed
selection command and seed rebuild it from DS3, and `report.json` records its SHA-256 and the cases'
SHA-256. Case ids are derived from
the case content, so the same case keeps its id across runs.

## Running

```bash
M="--models apertus-v1-5-70b apertus-v1-5-8b"
# size first: cases and jobs, no call, no file (AGENTS.md section 6)
python -m eval.tool_bench.run --rulings data/public/bench_rulings.jsonl --profile quick $M --dry-run \
    --out results/tool_bench/quick_<date>

# quick (30 cases, 199 calls for 2 models x 4 configs, 2 min 22 s at concurrency 4 on 27 Nov)
python -m eval.tool_bench.run --rulings data/public/bench_rulings.jsonl --profile quick $M --all \
    --out results/tool_bench/quick_<date>

# measurement (135 cases, 2 repetitions: ~1,880 calls, ~3.5 M input tokens, ~25 min at concurrency 4; estimates)
python -m eval.tool_bench.run --rulings data/public/bench_rulings.jsonl --profile full --reps 2 $M --all \
    --out results/tool_bench/full_<date>

# re-score a stored run with today's parser and validator (no gateway call; no --all needed)
python -m eval.tool_bench.run --rulings data/public/bench_rulings.jsonl --profile full --reps 2 $M \
    --replay results/tool_bench/full_<date>/replies.jsonl --out results/tool_bench/full_<date>_rescored

# non-regression between two runs on the same cases
python -m eval.tool_bench.score --compare results/tool_bench/A/rows.jsonl results/tool_bench/B/rows.jsonl
```

`--chat module:factory` selects the chat function (`factory(model) -> ChatFn`); the default is the
project client, `llm.client:chat_fn`. A live run spends nothing without `--limit N` (at most N cases)
or `--all`. Each live run has its own `run_id` (the `--out` name and the start time), and repetition
`r` sends `cache_salt="<run_id>/rep<r>"`, which the client puts in its replay cache key: no run and no
repetition is served from another. A reply the client marks `REPLAY` during a live run is counted
(`cache_hits` in `report.json`) and the run exits 3: it is not a measurement. A replay reuses the
stored `run_id`, so its request fingerprints match. Concurrency stays within the
member's share (D-030: 5 while open). Run it in an announced slot, not during the overnight pipeline
run.

`score --compare` exits **2** when the two runs do not hold the same cases (for example a quick run
against a full one): compare a full run with a full run and a quick run with a quick baseline made
on the same rulings and seed. It exits **1** on a regression (paired interval entirely below 0); a
larger point drop whose interval includes 0, or a group under 20 cases, is listed under `watch`.

Outputs in `--out`: `cases.jsonl`, `rows.jsonl` (scores, calls, no prompt text), `replies.jsonl`
(raw replies with the SHA-256 of their request, for replay and golden export), `report.json` and
`report.md` (per model and configuration, by category and language, Wilson 95 % intervals,
thresholds per repetition, paired comparisons per language, the computed decision). While running,
each finished job is appended to `partial.jsonl` (removed at the end), and a job that raises becomes
a row with `request_error = "exception:<type>"`. Commit only `report.md`/`report.json`
(aggregates); the other files contain dockets and excerpts. In replay, `replay_requests_changed`
counts replies whose request differs from today's (a prompt change): such a replay re-scores
parsing, it does not measure the new prompt.

## Acceptance thresholds

Pre-registered in `thresholds.json` (status PROPOSED). Each criterion is evaluated on every
repetition and the worst repetition counts (EVAL §1.4). The exit code is 1 when a blocking criterion
fails. The decision rule between native and JSON is in the same file and `score.decide()` computes
it: the burden of proof is on native tool calling (≥ +0.10 `exact_first` on evidence for the 70B,
with a paired interval above 0, in each of DE, FR and IT with at least 20 cases, and confirmed by
hand on the judges' endpoint). Verdicts: `keep_json`, `native_candidate`, `insufficient_n`.

## Statistics

* Wilson score interval for every proportion (small n, rates near 0 or 1).
* Paired **cluster** bootstrap (10,000 draws, seed 0, EVAL §1.5) for config-vs-config and
  run-vs-run differences: it resamples cases and keeps all repetitions of a case together, because
  repetitions of one case are not independent (a duplicated run must not look more significant).
* Two repetitions in the full profile: the 70B is not deterministic at T = 0 (K10), so a single run
  understates noise. Never compare outputs string for string.

## Credits

Case design, AST scoring, native call extraction and the thread-pool runner adapted from ArchAI's
`tool_bench.py` (MIT), itself modelled on the Berkeley Function Calling Leaderboard. See `NOTICE`.
