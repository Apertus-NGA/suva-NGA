# ARCHITECTURE: pipeline, contracts, stack

> **Status: v0 PROPOSAL (27 Nov 2026), updated after the official template was read.** Owner: `lead`. Each block carries its status: **DECIDED**, **PROPOSED** (working direction, not formally validated), **OPEN** (deliberately left open; options, reasoning and how to build meanwhile in `docs/DECISIONS.md` §2). See `docs/DECISIONS.md`.

## 1. Pipeline at a glance

```text
S0 Ingest      Neuheiten lists of every day 1 Oct 2025 to 15 Sep 2026 (D-050) + texts (HF first, bger.ch for gaps)
   │           → one record per ruling: key (docket, decision_date), publication_date, both quarter flags, star, Sachgebiet, language, text
   │           + judgements/ read-only: Suva's labels and examples, D-051 fields dropped; every docket checked against the populations
S1 Signals     code only: the 9 example rules + neighbours, each with its evidence span
   │
S2 Net         optional (OPEN, D-021): would drop ONLY the clearly out-of-domain, with a reason code; audited
   │
S3 Judgement   Apertus on the candidates: relevance judgement + key statement + cited considerations (model, few-shot, score form: OPEN)
   │
S4 Score       score 0-100 (Apertus alone, or learned combination with signals: OPEN, D-021); F2-calibrated threshold → selected; rank → top 30 (D-046)
   │
S5 Explain     German reason for EVERY ruling (selected or not), built from signals and the key statement
   │
S6 Summarise   rulings named by D-047: German summary and French summary, each from the source, Suva style
   │
S7 Verify      every article, E./consid., BGE, docket, number and acting party checked against the source; one repair, then flag
   │
S8 Present     API + UI for legal experts; "add another judgement" re-enters at S0 for one docket
   │
S9 Learn       expert corrections stored as labels → refit S4 (bonus)
   │
S10 Export     ranked list with scores, F2 threshold and top-30 cut marked (D-046), both quarter flags (D-050),
               plus the plain list "8C_691/2024, 9C_612/2025, …" + DE/FR summaries of the D-047 rulings (format Q-03, Q-18)
```

## 2. Stages

### S0 Ingest (PROPOSED; details in `docs/DATA.md` §7 and `docs/agents/crawl.md`)
- The daily Neuheiten lists are the ground truth for "published in Q2/2026". Texts come from HF `voilaj/swiss-caselaw` when present, bger.ch otherwise.
- Which date defines a quarter is OPEN (D-050). While open, S0 crawls the Neuheiten pages of every day from 1 Oct 2025 to 15 Sep 2026 (end date a parameter), so that Q4/2025, Q1/2026 and Q2/2026 are complete under both definitions. Every record carries `decision_date`, `publication_date` and its quarter under each definition (`docs/DATA.md` §1).
- The Q4/2025 and Q1/2026 populations are ingested too: they provide the negatives, under the closed-world assumption (Q-04), on decision-date populations while D-050 is open.
- Each record keeps `text_source`, a content hash and the raw page in cache.
- S0 also reads `judgements/` (Suva's labels and examples), read-only and in place: never copied, moved or edited (D-040). It keeps only docket, dates, quarter label, `Text DE`, `Text FR` and the bger.ch link; author fields, staff codes and every intranet link are dropped and never stored (D-051). It reads the workbook's cells only, never its file properties. Each export's docket comes from its bger.ch link (one file name has a space and a suffix, `docs/EVAL.md` T29). Output: the Suva example records of §3, in `data/derived/` while D-031 is open.
- S0 then checks that every docket in `judgements/` is in the crawled populations (or, for a Q3/2025 ruling put online before 1 Oct 2025, in HF), and lists each one that is not with its decision date (`docs/DATA.md` §1, `docs/EVAL.md` T30). A gap shows a crawl hole or a wrong date definition (Q-02).

### S1 Signals (PROPOSED)
Computed by code, no LLM, each with the span that proves it:
- the 9 example rules: Suva/CNA/INSAI party; Suva mentioned; accident or military insurance subject area; another UVG insurer party; publication star; five-judge bench; core themes (lexicon DE/FR/IT); length > 25,000 cleaned characters; appeal (partly) upheld;
- neighbours: court prefix, register letter, language, length, UVG/LAA/LAINF, UVV/OLAA, ATSG/LPGA, MVG/LAM articles cited, BGE cited (especially volume V), outcome class (upheld, partly upheld, dismissed, inadmissible, remanded), previous instance, subject keywords.

Suva example rules SR1 and SR2 exclude each other (party or only mentioned). A word "Suva" in the text does not make Suva a party: the parties block decides.

### S2 Mechanical net (OPEN, D-021 point 2: whether a net is needed, and how it is defined)
A net saves gateway calls; every drop risks recall. The definition formulated so far, if a net is used: a ruling is dropped **only if all three hold**: no mention of Suva/CNA/INSAI; no accident or military insurance term (UVG, LAA, LAINF, Unfallversicherung, assurance-accidents, assicurazione contro gli infortuni, MVG, LAM…); subject area not accident or military insurance. Never on the docket prefix alone. Every drop has a reason code; the count and a hand-checked sample are reported. Checking mentions in the full text is safer for recall than any metadata filter, but requires every text to be ingested first.

### S3 Apertus judgement (shape PROPOSED; model per role, few-shot form and score form OPEN, D-021 and D-022)
- **Implemented (28 Nov, D-075 to D-080, `docs/LAYER2.md`):** `layer2_judge` V1.0.0, the D-074 chain judged by the **8B** (measured at least as good as the 70B, D-076), score = P(Ja)/(P(Ja)+P(Nein)) shown 0-100 and the logit stored for ranking (D-077). The lines below are the design space the next versions explore.
- Model: the 70B is the natural judge, since the 8B never excludes a ruling on its own (doctrine). Whether the 70B can judge every candidate, or every ruling, depends on the measured latency (capacity floor, §6). Measured on 27 Nov (`docs/LESSONS.md` K15): at 4 concurrent calls, the 70B scores all 2,096 Q2 rulings in about 30 min with a score only, about 1 h 50 with a JSON justification. The judges may set `LLM_NAME` to the 8B (§4): the pipeline must still complete, and the 8B still never excludes alone; the signals carry the score (D-022, D-032).
- Input: the whole ruling or a reduced one (parties, subject, bench, main considerations, operative part), under the input budget of G4. Keera answered up to 250,000 tokens on 27 Nov (`docs/LESSONS.md` K6), so size no longer forces a reduced ruling or short few-shot; cost and focus still matter (about 1 s of 70B prefill per 8,000 tokens). Few-shot from labelled Q4/2025 and Q1/2026 rulings; digests, extracts or whole rulings, and how many, are open (D-021 point 3). The pilot's misses were IV and ATSG cases, so the pool covers them (Q-31, `docs/LESSONS.md` §2b). Suva's 55 summaries are a possible source of context (the template's step 2: "use context from provided summaries"). Never the ruling being judged, and never a ruling of the set being measured; the rest of the pool's hygiene is D-021 point 8.
- Output: a relevance judgement, either a score from token log-probabilities (a one-token label such as Ja/Nein or A/B, placed first and outside JSON; `max_tokens 1`, `top_logprobs 20`, on `/chat/completions`, the only Keera endpoint that returns them; score = lp(Ja) − lp(Nein)), or a label (D-021 point 4). Measured on 27 Nov: `top_logprobs` works up to 20 on `/chat/completions`, "Oui" is two tokens, and the 70B's score ranked a 33-ruling pilot with AUC 0.95 (`docs/LESSONS.md` K5, §2b); plus a key statement and the ids of the considerations that support it. A number written by the model as its confidence is not a score.

### S4 Score and threshold (OPEN, D-021 points 1 and 5)
Two options have been formulated, none retained:
- **Option A:** Apertus's judgement (with labelled examples as few-shot) is the score; the signals feed the explanation and the net.
- **Option B:** a small learned model (for example a logistic regression over ~10 signals + the Apertus probability) combines them; readable signal by signal, and its weights can be exposed to experts (bonus "redefine relevance").

Whatever the option: the score is shown 0-100; the F2 threshold is chosen on one labelled quarter and reported on the other at that frozen threshold, then the quarters are swapped (`docs/EVAL.md` §2); after the final refit it follows D-021 point 8 and is frozen before predicting Q2/2026; every ruling also gets a rank, and the top 30 is measured by precision and hits at 30 (D-046); signals only, Apertus only and combination are compared out of quarter, on both folds, with confidence intervals (`docs/EVAL.md` §2). The measurement settles the option.

### S5 Explanation (wording OPEN, D-021 point 6; language ASK-SUVA, Q-09)
German by default, following the mock-up's pattern: ruling type (Suva case, leading case…), outcome (upheld, remanded…), key statement, practical import, signals fired. For a dropped or low-score ruling: the net reason or the score and why.

### S6 Summaries (PROPOSED; scope OPEN, D-047, Q-17; style ASK-SUVA, Q-27, Q-30)
- For the rulings D-047 names (while open: our top 10 by score; then every selected ruling decided from 15 March to 15 June 2026, those decided from late April to late May first, since these are the rulings behind Suva's June 2026 summaries; then the remaining selected Q2 rulings, as capacity allows). Two independent texts: German and French, each generated from the source considerations and a structured fact sheet, never one translated from the other. While Q-27 is open, both keep the same paragraphs and the same consideration references, as Suva's examples do (`docs/SUVA_DATA.md` §3): the structure is shared, the wording is not.
- Suva structure as in the 55 exports (`docs/SUVA_DATA.md` §3): a title line `BGer-Urteil <docket> vom <date>` / `Arrêt du TF <docket> du <date>`, then the paragraphs of the style chosen by Q-30, and the bger.ch link; never an author line (D-051). The deck sample's header and two-part title (`docs/CHALLENGE.md` §8) are not used unless Suva asks for them (Q-08). Suva's examples show two house styles (rule-statement and narrative), and which one the experts expect is Q-30. While open, the style follows the ruling's language: German-language ruling, rule-statement style (as in all 22 German-language examples); French or Italian ruling, narrative style (facts, the rule with its consideration reference, application, outcome). Both texts of one ruling follow the same style; `E.` in German, `consid.` in French. Length: while Q-08 is open, it follows the 55 exports, not the deck's sample of about 300 words, which is longer than most of them (D-053; medians and p25 to p75 in `docs/SUVA_DATA.md` §3); target band `<to set>` in `docs/EVAL.md` §4.
- Few-shot from Suva's human summaries in `judgements/`, matching the ruling's language and style (whether prompts and caches containing them are committed: D-031; while open, `data/derived/`). The internal test set stays out of the pool: the 10 Q1/2026 exports plus the 13 German-language Q4/2025 exports; examples come from the 23 Q3/2025 exports and the 9 French-language Q4/2025 exports (`docs/EVAL.md` §4). A text with a meaning-changing translation error is never an example in that language (`docs/SUVA_DATA.md` §3).
- Locked glossary for terms. References are never typed by the model: the model cites consideration ids, the code renders every reference in the summary's language from canonical ids (D-037). The outcome is taken from the operative part by code when possible.

### S7 Verifier (PROPOSED)
Statuses `verified` / `flagged` / `rejected` per statement, six checks:
1. cited consideration ids belong to the set given to the model;
2. quoted text matches the source verbatim after normalisation (NFKC, spaces, quotes, hyphenation), with offsets;
3. every number, date, amount and deadline appears in the cited consideration; a mandatory one that disappeared is flagged;
4. every BGE/ATF, docket and article cited exists in the source, compared as **canonical ids** (act, article, paragraph, letter; volume, part, page; docket), so `art. 20 al. 2ter LAA` in a French summary matches `Art. 20 Abs. 2ter UVG` in a German ruling (D-037);
5. no statement without a citation;
6. every party named as acting (insurer, office, court) is a party in the ruling's parties block; in particular, no act is attributed to Suva unless Suva is a party (the 70B did so in the 27 Nov pilot, `docs/LESSONS.md` §2b).
One repair call that lists the faults, then fail closed and flag for human review.

### S8 API and UI (PROPOSED; stack chosen by the UI owner)
See `docs/agents/ui.md` and the API contract in §3. FastAPI serves rulings, scores, explanations, summaries, verification statuses and accepts corrections and "add another judgement".

### S9 Learning from corrections (bonus, PROPOSED)
Expert relevance flips and summary edits are stored with author, time and before/after; relevance flips become labels (few-shot candidates under option A, refit data under option B); summary edits become few-shot candidates.

## 3. Contracts to freeze first (PROPOSED)

Field names are prefixed (`a_`, `b_`, `c_`) because the gateway emits JSON keys in alphabetical order: the prefix fixes the generation order. Every object has `additionalProperties: false`. One pydantic model per contract generates the JSON schema, the prompt examples and the validator.

**Ruling record** (`src/schemas.py`): `docket`, `decision_date`, `publication_date` (both stored for every ruling, D-050; `publication_date` is null only with a counted reason, §8), `quarter_by_decision`, `quarter_by_publication` (computed by code, D-050), `court`, `register_letter`, `language`, `sachgebiet`, `gegenstand`, `star`, `text_source`, `text_hash`, `url`, `full_text`, `clean_length` (characters of the cleaned text, for example rule SR8), `considerations[] {id, e_number, text}`, `parties_block`, `bench_size`, `operative_part`, `outcome`.

**Suva example record** (from `judgements/`, built by S0): `docket`, `decision_date`, `quarter_label` (list rows only), `in_list`, `text_de`, `text_fr` (exports only), `bger_url`, `source_file`. Nothing else is parsed or stored: no author, staff code, job title, intranet link or file property (D-051). The cantonal row keeps its title as `docket` and is marked as not a Federal Court ruling.

**Consideration ids:** internally `c1`, `c2`, … in document order (what Apertus sees and returns); `e_number` keeps the court's numbering (`5.1`), which code renders as `E. 5.1` in German and `consid. 5.1` in French and Italian.

**Signals record:** `{name, value, evidence: {consideration_id, start, end}}[]`, plus `net_decision {kept: bool, reason_code}`.

**Triage call** (one ruling per call):
```json
{"a_evidence": ["c3", "c7"], "b_key_statement": "≤ 300 chars", "c_label": "A"}
```
`a_evidence` is an enum of the consideration ids sent. With log-probabilities, only `c_label` (A = relevant, B = not relevant) is read from the first-token probabilities; the rest comes from a second call or the same call depending on the gateway test.

**Summary call** (one call per summary, or per section if the nested list drifts: settled by the gateway probe, D-028):
```json
{"a_claims": [{"a_cites": ["c5"], "b_text": "≤ 300 chars", "c_section": "facts|law|outcome"}],
 "b_outcome": "upheld|partly_upheld|dismissed|inadmissible|remanded|other",
 "c_unknown": []}
```
If the nested list drifts on the gateway, fall back to one call per claim or to strings like `"c3 c4"`.

**Decision record:** `docket`, `score`, `score_source` (`judged` | `signals_only` | `net` | `failed`, D-021 point 7), `selected`, `rank`, `in_top30` (D-046), `threshold_version`, `explanation_de`, `signals_fired[]`, `model_versions`, `prompt_versions`, `mode` (`LIVE` | `REPLAY`).

**API (PROPOSED, for the UI and for judges):**
| Endpoint | Returns or does |
|---|---|
| `GET /api/rulings?from=&to=&court=&lang=&selected=&star=&sort=score` | the table rows (decision records + ruling metadata) |
| `GET /api/rulings/{docket}` | one ruling: metadata, score and signals, explanation, key statement, considerations |
| `GET /api/rulings/{docket}/summaries` | German and French summaries with each claim's citations and verification status |
| `POST /api/rulings` `{docket or url}` | "add another judgement": runs the full pipeline for one ruling (D-015) |
| `POST /api/corrections` | relevance flip or summary edit, with author, time, before/after |
| `GET /api/export/relevant?quarter=2026Q2` | the delivered list, deduplicated by docket, ranked with scores; threshold and top-30 cut marked (D-046); each ruling's quarter under both date definitions (D-050). The default set is D-009's (published in the quarter), a default while D-050 is open (D-052), until Q-02 is answered |
| `GET /api/status` | counters per stage, mode (`LIVE`/`REPLAY`), degraded stages |

## 4. Apertus client (`src/llm/client.py`, PROPOSED)

1. Config from `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_NAME` ("name and version of the model", template `README.md`: the only model name the judges set; they may set the 8B or the 70B, as a gateway id or a Hugging Face id (both forms in `MODELS.md`); the client maps both forms; Q-23), plus optional `LLM_NAME_SMALL` (defaults to `LLM_NAME`), `LLM_CONCURRENCY`, `LLM_TIMEOUT_S`, `LLM_MAX_INPUT_TOKENS` (the input budget of G4). In live mode, fail if a required one is missing; in replay mode they are not needed (D-032). The pipeline completes whichever size `LLM_NAME` names (`docs/EVAL.md` T26).
2. No network at boot. `make smoke-llm` probes `/models`, `json_schema` strict, `json_object`, `logprobs` and `top_logprobs`, streaming, served model; `make warmup` warms the 70B (other teams reported ~50 s of cold start; none was seen on 27 Nov, but the night may differ). Core calls use `/chat/completions`, the only Keera endpoint that returns log-probabilities; Keera also serves `/responses` and `/messages`, but not `/completions` or `/embeddings` (`docs/LESSONS.md` K1, K13). Log `cached_tokens` (K14).
3. Every response: check `model` (and the `x-keera-model` header when present) against the allow-list of G3: the Apertus v1.5 ids recorded by the probe, in both id forms (listed in `MODELS.md`), plus the `LLM_NAME` the runner set, if it names an Apertus model (case-insensitive `apertus`, any id form); otherwise fail fast at startup with a clear message (E1). Reject any non-Apertus served model; a missing header is logged, not fatal (the judges' endpoint may not send it). Log provider, served model, fingerprint, latency, tokens, `finish_reason`, cache hit.
4. Errors classified by structure (rate, quota, content, budget, permanent). Retry 408/409/429/5xx/network/cut streams with exponential back-off and jitter (cap 30 s, honour `Retry-After`); never retry 401/403/404; a 400 naming `response_format` triggers the JSON fallback; any error yields status `failed`, never a negative label.
5. One AIMD limiter per key shared by all processes: start at 4, halve on 429/504/timeout, +1 after a run of successes, capped at the member's share (D-030: 5 while open; team total ≤ 16; 0 errors up to 8 on one key on 27 Nov, 16 untested). A half-open circuit breaker pauses the run and leaves items "to do", never `failed`.
6. T=0, `max_tokens` per role (triage ≤ 400, summary 1,500 to 3,000), thinking off (for a `-thinking` model, `chat_template_kwargs.enable_thinking=false`, and strip any `<|inner_prefix|>` … `<|inner_suffix|>` block from `content`, `docs/LESSONS.md` K11), streaming beyond ~30 s of generation (a ~700-token 70B summary takes 30 to 33 s).
7. JSON cascade: `json_schema` strict → `json_object` with a placeholder example → JSON in the prompt. Tolerant parser (first JSON object; strip fences, think tags and template tokens; fix German quotes). Pydantic `extra=forbid`. One repair with the error, then fail closed.
8. Two stores: `llm_calls` (every raw output, invalid ones included, for audit and offline re-verification) and the replay cache (key: SHA-256 over the **requested** model id, messages, parameters, prompt and schema versions, seed, repetition index; the served model is stored with the answer and checked, and only valid outputs from an allowed model are cached). Caches whose prompts contain Suva material follow D-031 (while open: `data/derived/`, git-ignored). The demo cache lives apart and is never purged.
9. Note: T=0 is not deterministic on shared gateways. Measured on 27 Nov: the 70B gave 4 distinct outputs in 5 at T=0 with a seed; the 8B was deterministic (`docs/LESSONS.md` K10). Measure noise with 2 identical runs; a live slice is checked by schema and verifier, never by string equality with the replay cache (D-032).

The report's section 3 "Use of Apertus" is written from this section and `MODELS.md`: the model (Hugging Face id and gateway id), how it is used (inference), where it runs (hosted endpoint), the prompts, JSON mode, log-probabilities or labels, temperature, thinking off, the repair call and what the code verifies. Prompts built from Suva's examples are disclosed as D-031 allows.

## 5. Stack

| Component | Choice | Status |
|---|---|---|
| Language and models | Python, pydantic, FastAPI | PROPOSED (D-035) |
| Database | PostgreSQL with per-language full-text search (`tsv_de`, `tsv_fr`, `tsv_it`), pgvector (`halfvec`, HNSW), `pg_trgm`; image pinned by digest (pgvector 0.8.x on PG 17) | DECIDED (D-004) |
| Fusion | RRF (k = 60) computed in Python; kept only if it beats each channel alone | DECIDED (D-004); whether search is built at all is OPEN (D-033) |
| Search role | Search (Postgres, or OpenSearch only if the bake-off shows ≥ +3 pts Recall@10) serves exploration, the UI and similar rulings. **It never produces the relevance score.** | DECIDED (engine rule, D-004); PROPOSED (role, D-013) |
| Embeddings | pplx-embed-context-v1-0.6b if search uses embeddings; bge-m3 as a possible baseline | DECIDED (D-005) / OPEN (D-020, D-033) |
| CDC (Debezium, Kafka) | out of the runtime; target architecture only | DECIDED (D-004) |
| Packaging | Docker, docker compose, Makefile (our conventions, not the template's: D-035, D-042); embedding model embedded in the image; snapshot of public data embedded. Weights are downloaded during the image build, never committed (the template's `.gitignore` excludes them): a build-time external dependency listed in the report (§7). The UI is built inside the image (the template's `.gitignore` excludes `dist/` and `build/`) | PROPOSED |
| Not doing | chat (D-006), retrieval for a new claim file (vision slide only, D-016), fine-tuning | PROPOSED |

## 6. Capacity floor (compute at the start of the build)

floor = max( N × tokens ÷ token-rate limit , N ÷ call-rate limit , N × latency ÷ concurrency ), per role, with latencies **measured on the gateway** for a short triage call and a long summary call. Compare with the time left. It decides whether the 70B judges every candidate and how many summaries fit. First measurements (27 Nov, warm gateway, 4 concurrent calls, whole rulings of ~5,100 input tokens; `docs/LESSONS.md` K7, K15): 70B score only, about 30 min per 2,096 rulings; score plus JSON justification, about 1 h 50; 8B with a justification, about 25 min; about half at 8 concurrent calls; a 70B summary of ~700 tokens, 30 to 33 s. With the call count below (about 5 times the Q2 count per variant), a 70B score-only variant takes about 2.5 h at 4 concurrent calls; with a JSON justification on every call, about 9 h. Which calls need a justification is D-021 point 6. These figures assume the night behaves like the afternoon.

Count N honestly. The crawl (1 Oct 2025 to 15 Sep 2026, D-050) lists about 8,000 rulings (2,096 Q2 rulings in 91 days, about 23 per day). Only the candidate populations need triage calls: a crawled ruling outside every window gets the reason code `out_of_window`, with no LLM call (G5). The candidate populations are: Q2/2026 (about 2,060 rulings published, D-009's window, the default while D-050 is open, D-052; plus, while D-050 is open, the Q2 stragglers, decided in Q2 and put online from July to mid-September, about 615; the union holds about 2,677, `docs/DATA.md` §6; fewer if a net is used); the labelled quarters on their decision-date populations (D-050), Q1/2026 (2,005, measured) and Q4/2025 (1,931); and the publication-date extras (rulings put online in a labelled quarter but decided before it). Measurement runs are repeated twice (G10). Triage calls = (Q2 + Q2 stragglers) + 2 × Q1 + 2 × Q4 + the publication-date extras, times the number of LLM variants measured: about 5 times the Q2 count per variant. The 2 × Q4 term holds under option B (to fit) and, with the cross-quarter protocol of `docs/EVAL.md` §2, under option A too. Summaries: 2 per ruling named by D-047 (our top 10, then the selected rulings behind Suva's June 2026 summaries, then the remaining selected Q2 rulings as capacity allows), plus the internal hold-out (23 test rulings, 2 languages, 2 repetitions: at least 92 calls, more if summaries are generated per section, `docs/EVAL.md` §4).

## 7. Target architecture (for the report's mandatory section)

The report must contain the section required by the template's `technical_report.md`, section 2 'Target architecture (mandatory)' (imposed, DECIDED; D-039 mentions it); it is also event rule E5 (`docs/EVENT.md` §2). The template's section asks two things: "State which of the three architectures your project is deployable in, and how it meets that constraint", and "List any external dependencies, and separate build time from runtime". The report states which of a), b) and c) the project meets and how; the build keeps all three possible.

- **a) On-premise** (on Suva's own infrastructure, under its own administration): Apertus served by vLLM, scheduled ingestion of Federal Court (and, later, cantonal insurance court) rulings, Postgres, the app in containers.
- **b) Air-gapped** (no external network connection at runtime): the same, with an offline update path for rulings and images.
- **c) Sovereign Swiss cloud** (a cloud platform operated in Switzerland, under Swiss jurisdiction, with Swiss data residency): the same containers and Postgres on such a platform, with Apertus served in Switzerland.
- **Build time:** base images, Python packages, model weights (the embedding model; Apertus weights when it is self-hosted), the UI build. Weights are downloaded during the image build, never committed.
- **Runtime:** the Apertus endpoint (`LLM_BASE_URL`) only; bger.ch only for scheduled ingestion (none in b, where rulings arrive through the offline update path). No CDN and no other external service.
- Optional search projection fed by CDC or an outbox (D-004). Human validation and an audit log of every expert correction.
- **Transfer to Azure (the template's bonus; D-049, OPEN; while open: option b, a short subsection of the report's section 2):** containers on an Azure container service, Postgres with pgvector on a managed Azure PostgreSQL, Apertus behind any OpenAI-compatible endpoint set by `LLM_BASE_URL`; configuration only through environment variables. Service names and pgvector support are to verify. No Azure call and no Azure-specific code at runtime. Azure is never presented as option c): a US provider's Swiss region is not obviously "under Swiss jurisdiction" (Q-19).

The report's section 2 "Architecture" is written from §1 to §3 of this file and this section, with its diagrams in `docs/diagrams/` (the template: "Put diagrams in `docs/` and reference them here").

## 8. Plan B (when something fails)

| Failure | Fallback |
|---|---|
| Suva's labels unusable (format, ambiguity, window definition; they are in `judgements/`) | A0 rules plus the Apertus label; top-K threshold sized to what an expert can read per week; say so in the report (D-021) |
| A docket of `judgements/` missing from the crawled populations | list it with its decision date; look it up in HF and on its bger.ch page; report whether it shows a crawl gap or a wrong date definition (D-050, Q-02) |
| The judges set `LLM_NAME` to the 8B, or to an id form we did not test | the client maps both id forms (§4); the pipeline completes with the 8B, the signals carry the score, the 8B never excludes alone (D-022, D-032); a missing `x-keera-model` header is logged, not fatal |
| bger.ch challenged by the firewall | back off; texts from HF; lists: Neuheiten pages already cached, then HF/entscheidsuche for decision dates, with every ruling whose publication date is unknown flagged; ask Q-10; never switch networks or IPs to get past a challenge |
| Gateway slow, overloaded or down | lower the member's concurrency; replay cache for anything already answered; prioritise the candidates decided from 15 March to 15 June 2026 (the rulings behind Suva's June 2026 summaries, D-047); summaries for the top-ranked first |
| No `top_logprobs` on the judges' endpoint (Keera has them on `/chat/completions`, measured 27 Nov) | labels (D-021 point 4) |
| Nested JSON drifts | one call per claim or flat strings (§3) |
| Summaries too slow | stream; summarise in the order of D-047 (our top 10 first, then the selected rulings behind Suva's June 2026 summaries, then the remaining selected Q2 rulings); flag the rest as pending, never silently missing |
| Overnight run interrupted | rerun the same command: done items are skipped and answered calls come from the cache (`docs/agents/platform.md`) |
