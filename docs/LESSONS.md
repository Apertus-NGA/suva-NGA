# LESSONS: known facts and lessons learned before the build

> **Status: v0 PROPOSAL (27 Nov 2026), updated after the official template was read and after the team's gateway test.** Owner: `lead`. Sources: the public repositories and reports of the 245 HackApertus 2026 projects (online tracks and the Liebefeld on-site edition), reviewed on 26 Nov 2026. Figures in the "Fact" column of §1 and in §2 are **other teams' measurements**: a reason for a design choice, not a promise. Our own measurements go in the column "Ours" and in §2b. The first ones come from **the team's gateway test of 27 Nov 2026** (16:26 to 16:46 CET, one key, a warm gateway on a Friday afternoon, 423 calls, 3.4 M input tokens; logs and scripts kept outside the repo until the lead approves committing the scripts). They are measured, but on one afternoon: the night, under the other teams' load, may differ.
> Evidence levels: **reported** = stated in another team's code or report; **observed** = seen by us; **measured** = our own test, with logs; **inferred** = deduction.

## 1. The Keera gateway

| # | Fact | Evidence | How we re-check (probe, `docs/EVAL.md` §7) | Ours |
|---|---|---|---|---|
| K1 | OpenAI-compatible; model ids `apertus-v1-5-8b`, `apertus-v1-5-70b` (plus `-thinking` variants). The template names the models by their Hugging Face ids (`README.md`) and "the CSCS / Keera Gateway" (`challenge_description.md`): the judges may use either id form and another endpoint (both forms and the allow-list: `MODELS.md` §1; the rule: `AGENTS.md` G3; Q-23) | reported; the template's wording observed by us | `GET /models` | measured: 4 ids (`apertus-v1-5-8b`, `apertus-v1-5-70b` and their `-thinking` variants); `max_context_tokens` 262,144; served endpoints `/chat/completions`, `/responses`, `/messages`; `/completions` and `/embeddings` return 404 |
| K2 | `response_format` `json_schema` with `strict` works when every object has `additionalProperties: false`; `json_object` works too | reported | one call per mode | measured: `json_schema` strict valid 12/12 (on `/chat/completions` and `/responses`), `json_object` 6/6; 33/33 valid on whole rulings for each model |
| K3 | JSON keys come out in **alphabetical order**, so field names are prefixed (`a_`, `b_`, `c_`) to fix the generation order | reported | 3-field schema with unprefixed names | measured: confirmed in strict mode; `json_object` and unconstrained output keep the prompt's order |
| K4 | Native tool calling makes only one call per turn: teams used their own JSON protocol instead | reported | not needed | not tested (not needed) |
| K5 | `logprobs` accepted; **`top_logprobs` untested** | reported / untested | A/B question with `top_logprobs: 20`, `max_tokens: 1` | measured: `top_logprobs` 0 to 20 work on `/chat/completions` (21 returns 400); `/responses` ignores the request without error; "Oui" is 2 tokens, while "Ja", "Nein", "A", "B", "1" and "0" are 1 token each; under strict JSON the key names are split character by character, so the label goes first, outside JSON |
| K6 | HTTP **504 above ~20,000 input tokens** | reported | calls at 8k, 16k, 24k tokens | **not reproduced** (measured): status 200 up to 250,624 input tokens, uncached and without streaming; the 70B took 81 s at 250k and 23 s at 128k, with no cut at 60 s; the start of the context was always read |
| K7 | 70B cold start ~49 s; ~10 s per 70B call seen at the on-site edition | reported | first call, then 5 warm calls, short and long | measured: no cold start seen (first 70B call 0.27 s, warm gateway); still possible at night, so keep the warm-up. Warm latencies: score only on a whole ruling, median 1.0 s (70B) and 0.5 s (8B); JSON justification 9 s median, 21 s max (70B); a ~700-token summary 30 to 33 s (70B), 4 to 5 s (8B); generation ~22 to 32 tokens/s (70B), ~165 (8B) |
| K8 | **16 concurrent calls worked, 32 were blocked**; whether the limit is per key, per team or global is unknown | reported | ramp 1 → 4 → 8 → 16 in an announced slot | measured: 1, 2, 4 and 8 concurrent calls on one key with 0 errors, no 429 and no rate-limit header; 16 not tested (it needs an announced slot, D-030); the limit's scope is still unknown (Q-14) |
| K9 | The served model can differ from the requested one: one team saw the "8B" route answered by the 70B in 91.9 % of calls. Check the `x-keera-model` header and the `model` field (another endpoint may not send the header: `AGENTS.md` G3) | reported | log both on every probe call | measured: 0 mismatches in 411 successful calls (header and `model` field agree with the request); 8B and 70B outputs never identical (0 of 25 pairs at T=0). Keep the check: it costs nothing |
| K10 | Temperature 0 is **not deterministic** on the shared gateway | reported | 2 identical runs of 20 calls | measured: the 70B gave 4 distinct outputs in 5 at T=0 with a seed (not deterministic); the 8B was deterministic, even at T=0.7 with a seed. Replay is what makes `make run` reproducible (D-032) |
| K11 | Keep thinking off; send one `system` message; stream generations longer than ~30 s | reported | | measured: two `system` messages return 400; `chat_template_kwargs.enable_thinking=false` turns thinking off; the 70B-thinking variant writes its reasoning inside `content`, between `<|inner_prefix|>` and `<|inner_suffix|>`; `/responses` hides reasoning but counts it in `output_tokens`; thinking multiplied output tokens by 4 to 9 with the same verdicts |
| K12 | Nested JSON lists (lists of objects inside objects) can drift | inferred from other teams' fallbacks | summary contract on 3 rulings | not tested |
| K13 | Keera serves **no embedding model** (`/embeddings` returns 404): any embedder runs on our side (D-020, D-033) | measured (27 Nov) | one `/embeddings` call | this row |
| K14 | A **prefix cache** is active: `usage` returns `cached_tokens` (1,600 of 1,618 tokens for a ruling sent twice). Latencies on repeated prefixes are optimistic: put a random id at the start of the prompt when timing | measured (27 Nov) | log `cached_tokens` on every call | this row |
| K15 | **Throughput on whole rulings** (~5,100 input tokens each), 4 concurrent calls: projected for 2,096 rulings, the 70B takes about 30 min with a score only (1 output token), about 1 h 50 with a JSON justification; the 8B about 25 min with a justification; about half at 8 concurrent calls | measured (projection from 66 calls on 33 rulings) | rerun on the first batch of the overnight run | this row |
| K16 | Keera exposes **no price and no quota** (`/models` shows none): cost is counted in tokens | measured (27 Nov) | ask the organisers (Q-14) | this row |

**Rerun with the repo's probe** (`make smoke-llm`, `src/llm/probe.py`; 27 Nov, 18:16 CET, one key, 27 sequential calls, synthetic prompts; `results/gateway_probe.json`). Confirms K1 (the same 4 ids), K3 (strict JSON keys in alphabetical order; `json_object` keeps the prompt's order), K5 (`top_logprobs` 20 on `/chat/completions`; "Ja" first at −0.014, "Nein" −4.26), K9 (served model = requested in 27 of 27 calls, `x-keera-model` header present in 27 of 27), K11 (two `system` messages: 400). Short calls: warm median 0.16 s (70B) and 0.11 s (8B), first call 0.44 s (70B): no cold start seen. Two identical short calls at T=0 with a seed gave identical outputs for both models (a 40-token output; K10's non-determinism was seen on longer outputs). 8B and 70B gave the same output on 1 of 5 greedy prompts (no aliasing alert). Not rerun yet: K6 (input sizes, `--sizes`), K7 long generation (`--long`), K8 concurrency ramp (`--ramp`, 16 only in an announced slot, D-030).

## 2. Apertus on Swiss law (other teams' measurements)

- Closed-book (no text given), about **52 % of answers to Swiss-law questions were wrong**; with the relevant text in the prompt, **96 to 99 %** were right.
- Of the BGE/ATF references Apertus cited from memory, **6 % did not exist** and **57 % were off-topic**.
- The 8B cited **3 law numbers out of 4 wrongly** from memory.
- As a judge of answer quality, Apertus agreed with humans at **κ 0.01 to 0.08** (near chance). That was quality judging, not relevance.
- A model's self-declared confidence was almost always 0 or 1: useless as a score.
- The 8B used **alone to exclude** documents cost **0.28 to 0.44 of recall** in other projects.
- Query translation by the 8B raised top-5 retrieval across languages from 63 % to 97 % in one project.

What follows for us: the model picks ids and the code copies text and references (`docs/DOCTRINE.md` §1); Apertus never judges our headline metric; the 8B never excludes alone.

## 2b. Apertus on our task: the team's pilot (27 Nov, measured, small samples)

A probe, not the product: whole rulings, a German system prompt, **no few-shot and no Suva rules**. Small samples: these are orders of magnitude and calibrate nothing.

- **Triage pilot on 33 public rulings:** 14 positives (rulings of Suva's list that have an export, plus 9C_65/2025 and 4A_106/2025, which Suva summarised), 14 hard negatives (courts 8C, 9C, 8F and 9D, decided September to November 2025, not in the list: negative only if Suva's lists are complete, Q-04) and 5 easy negatives (other courts).
- **Score from log-probabilities** (a Ja/Nein question, `max_tokens` 1, score = P(Ja) / (P(Ja) + P(Nein))): AUC **0.95** for the 70B, 0.86 for the 8B. At 0.5 the 70B finds 10 of 14 positives (95 % CI 0.45 to 0.88) with no false positive; it finds all 14 at about 5·10⁻⁵, with 4 false positives of 19. The values are extreme: the score is a ranking, not a probability, and the threshold is calibrated on Suva's lists (D-021 point 5).
- **The 8B must not exclude alone** (§2 confirmed): asked for a justified JSON verdict, it called a criminal and a public-law ruling relevant, and 7 hard negatives; with the log-probability score at 0.5 it missed 5 of 14 positives.
- **The 4 positives that both models missed are disability insurance (IV) or ATSG cases:** helplessness allowance, a social wage, the liability of an IV office, and procedure and costs under the ATSG. The probe prompt did not say that Suva follows these questions. Relevance is broader than accident insurance (Q-31): if the few-shot does not show it, recall stays near 0.7.
- **Court 9C also decides tax cases** (two in the sample). A 9C prefix is not a sign of social insurance; both models rejected them.
- **Party bias:** when the prompt named Suva, the 70B attributed acts to Suva where another insurer was the party (a German summary of 8C_508/2025; a triage justification of 8C_184/2025). Check every party named as acting against the ruling's parties block before a text says "Suva".
- **Consideration citations in JSON:** the 70B cited 78 consideration numbers, all present in the ruling, in the form "E. x" 33 times of 33; the 8B cited 100, of which 89 exist, "E. x" 15 times of 33. Justifications were in German 33 times of 33, for French and Italian sources too.
- **Summary pilot** (4 rulings; each model wrote German, French from the source, and French translated from its German; the prompt asked for ~300 words): the 70B invented no consideration and no article; it added Markdown (bold, headings) to 6 outputs of 12 and exceeded the target length. French written from the source cited considerations more often than French translated from German (3 of 4 against 1 of 4). The 8B once wrote Italian when asked for French. No "ß" was seen. Suva's examples are more compact and have no headings (`docs/SUVA_DATA.md` §3).

## 3. Engineering patterns that worked

- **The LLM chooses ids, the code copies and verifies.** The universal winner across projects: Apertus selects consideration ids from an enum; code copies the text and builds citations; a verifier rejects anything absent from the source.
- **`make run` that replays recorded answers offline and fails on divergence** with expected outputs (a first-placed project); frozen gold sets with hashes; counted runs; published limits.
- **One gateway client** with an adaptive limiter (halve on 429/504/timeout, +1 after successes), a half-open circuit breaker, no network call at start-up, a full log of raw outputs, and a replay cache whose key includes the repetition index (so measurements are not served from cache). A demo cache kept apart, never purged.
- Retrieval, when needed: per-language full text plus embeddings fused by reciprocal rank (k = 60) in Python; keep fusion or reranking only if it beats each channel alone; bge-m3 is the usual multilingual baseline.
- No extractor for BGE, `8C_` dockets or LAA/UVG articles exists in the public projects: we write ours.

## 4. What separated podiums from the rest (HackApertus 2026)

| Signal | Podiums (15) | Other winners (10) | Others online |
|---|---|---|---|
| Baseline or control | 15/15 | 7/10 | 70 % |
| Tests | 14/15 | 7/10 | 74 % |
| Confidence intervals in the report | 10/12 | 6/10 | 35 % |
| Agreement (κ) measured | 7/12 | 2/10 | 7 % |
| `make run` | 12/15 | 10/10 | 83 % |

The Zurich template does not impose `make run`: it asks that judges can run the project end to end, with the instructions in `technical_report.md`. `make run` is our convention (D-042), chosen partly because of the row above.

- First places shared **one thesis, one before/after number with its interval, a dated real case as the hook, and written limits**. One opened its report with a criterion → evidence table; one turned a pre-registered claim that failed into its finding.
- At the on-site edition: one podium per challenge; podium teams had 4-5 members; all three covered the whole brief with a product facing the partner, provenance on every output, and a human or validator with the last word. One placed **second without publishing any score**: it won on product, fit to the criteria and honesty about what it had not validated.
- Thesis sentences that worked: "Apertus proposes, the code has the last word"; "Apertus understands. Code checks. People decide."
- Decks were short (7 to 10 slides, little text) with a live demo and a recorded fallback.

## 5. Licences and tools to avoid

PyMuPDF (AGPL, used by several projects including a winner), GPL code, CC BY-NC models, share-alike datasets in a closed deliverable, any closed model at runtime (E3). Read a repository's `LICENSE` before copying anything and list it in `NOTICE`.
