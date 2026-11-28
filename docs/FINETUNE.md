# Layer 2 — Apertus relevance benchmark and (later) fine-tuning

> **Production (28 Nov, D-076):** `layer2_judge` V1.0.0 runs this benchmark's chain with the 8B, certified identical on `suva-ft-v3` (`docs/LAYER2.md`). A change to it follows §7's decision rule.
> **Status: EXPERIMENTAL, 27 Nov 2026. Baseline settled 28 Nov (D-074):** the §6 benchmark of standard Apertus is the reference for every later layer-2 change. Owner: `<handle>` (layer 2). This work does not change the delivered pipeline until a measured gain is shown (see §7, decision rule). `docs/ARCHITECTURE.md` currently lists fine-tuning under "Not doing" (PROPOSED); this document is the evidence base for revisiting that line, not a decision.
> Read `AGENTS.md`, `docs/CHALLENGE.md`, `docs/DATA.md` §6 and `docs/agents/finetune.md` first.

## 1. What layer 2 is

The triage has two layers. **Layer 1** (owned by the layer-1 owner, `docs/TIPS_LAYER1_FILTER_HANDOFF.md`) drops rulings that cannot be Suva-relevant, with 100 % recall. **Layer 2** is Apertus judging whether a ruling is in Suva's scope and producing a score. This document covers layer 2 only: a frozen evaluation set, a zero-shot benchmark of base Apertus v1.5 (8B and 70B), and, later, a LoRA fine-tune of the 8B.

Score definition (all systems): the model is asked, in German, "Ist dieses Urteil für die Suva relevant? Antworte nur mit Ja oder Nein." and the score is `P(Ja) / (P(Ja) + P(Nein))` on the first output token. `Ja` and `Nein` are single tokens in the Apertus tokenizer (`docs/LESSONS.md`, Keera facts); `Oui` is two tokens, so French answers are not used.

## 2. Evaluation set `suva-ft-v3` (FROZEN)

| Item | Value |
|---|---|
| Identity | ids digest `69f8e4b0c7714898d8df0765138f0dbe687e83705d1d793c531c3f80d23785b6` |
| Archive | `suva-ft-v3.zip`, SHA-256 in `experiments/finetune/manifests/suva-ft-v3/suva-ft-v3.zip.sha256` |
| Manifest (committable, no labels) | `experiments/finetune/manifests/suva-ft-v3/MANIFEST_suva_ft_v3.json` |
| Data (Suva-derived labels, git-ignored, D-031) | `data/derived/finetune/suva-ft-v3/` |
| Texts | HF `voilaj/swiss-caselaw` `data/bger.parquet` at commit `35b17aa9c3fad71011b72f78f6ab79650ec0cf96`, SHA-256 `d2b2df1d…bb3711` |
| Builder | `experiments/finetune/scripts/05_build_dataset_v3.py` (imports `04_build_dataset_v2.py` and `../filtre_couche1/filtre_e.py`); deterministic, rebuilt bit for bit twice |

**Population and labels.** Every Federal Court decision whose decision date falls in the quarter (closed world, `docs/DATA.md` §6). Positives = Suva's relevance list (`judgements/BG_Urteile_2025_Q4_2026_Q1.xlsx`): 28 in Q4/2025, 31 Federal Court rows in Q1/2026 (the cantonal row is out of the population). The 23 rulings decided in Q3/2025 that Suva summarised are added as **training** positives only. Every other ruling of the quarter is a negative. Hard negatives = accident (UV), invalidity (IV) or military (MV) rulings that Suva did not select.

**Two temporal folds.**

| Fold | Train | Valid | Test |
|---|---|---|---|
| fold_A ("deployment") | Q4/2025 80 % + 23 Q3 positives: 1,567 (45 pos, 83 hard) | Q4/2025 20 %: 387 (6 pos) | **Q1/2026 complete: 2,005 (31 pos, 131 hard)** |
| fold_B | Q1/2026 80 % + 23 Q3 positives: 1,627 (48 pos, 105 hard) | Q1/2026 20 %: 401 (6 pos) | **Q4/2025 complete: 1,931 (28 pos, 104 hard)** |

- Q3/2025 **negatives are not used**: Q3 has summaries only, not a list (79 % of Q4 positives have a summary, 32 % of Q1), so the rest of Q3 holds unlabelled positives.
- fold_B trains on rulings later than its test quarter: a soft temporal leak, stated in every report; it does not touch labels.
- `meta.couche1` = the ruling passes layer-1 whitelist E (`filtre_e.py`, SHA-256 `da941909…`). A hint, **never a label**.
- Prompt: system prompt (German, Suva's scope in one paragraph) + `Urteil <docket>:\n\n<text>\n\n<question>`; text capped at 14,000 characters (first 12,000 + last 2,000).

**Verification** (anyone, any machine): `python3 -I experiments/finetune/scripts/verify_dataset.py --manifest experiments/finetune/manifests/suva-ft-v3/MANIFEST_suva_ft_v3.json --data data/derived/finetune/suva-ft-v3` must end with `IDENTIQUE au manifeste` (exit 0). Two people comparing results must both pass this check first.

**Freeze record.**

| When | Who | Machine | Result |
|---|---|---|---|
| Fri 27 Nov 2026, 21:50 CET | layer-2 agent (Claude Code), for the lead | the lead's Mac (macOS, Python 3.13.12) | Archive SHA-256 `def7a58b…0918` = `suva-ft-v3.zip.sha256`. `verify_dataset.py`: `IDENTIQUE au manifeste`, exit 0, all 6 splits OK, ids digest `69f8e4b0c7714898d8df0765138f0dbe687e83705d1d793c531c3f80d23785b6`. Ambiguous-negatives list SHA-256 `4931d15a…` = `ambiguous_negatives.sha256`. |
| Fri 27 Nov 2026, 21:58 CET | same | same | **Rebuilt from the pinned sources, bit for bit:** parquet downloaded at commit `35b17aa9…` (SHA-256 `d2b2df1d…bb3711`, checked), population CSV `c412ac65…`, builder `05_build_dataset_v3.py` `0ba116fa…` and `filtre_e.py` `da941909…` (all four as in the manifest), duckdb 2.0.1 in a throwaway venv. The 6 rebuilt split files and `stats.json` are byte-identical to `data/derived/finetune/suva-ft-v3/`, and the rebuilt folder passes `verify_dataset.py`. |
| Sat 28 Nov 2026, 00:09 CET | same | same | **Documented edit, not a new version (G13, the lead's go):** in the committed manifest, the `status` text named a team member; the name is replaced by "le lead". Splits, file hashes and ids digest are unchanged and `verify_dataset.py` still prints `IDENTIQUE au manifeste`. The manifest copy inside `suva-ft-v3.zip` keeps the original text, so the zip hash is unchanged. |

## 3. Independent audit of `suva-ft-v3` (27 Nov, verdict: fit with corrections)

Full report (French) in `data/derived/finetune/audit_v3/AUDIT_V3.md`; scripts in `experiments/finetune/audit/` (read-only, reproducible).

What holds: the 59 listed dockets each map to one decision in the right quarter and fold; no positive labelled `Nein`; the cantonal row is excluded; only 2 twins, both legitimate; the manifest and the zip verify; the set and the population rebuild bit for bit; baseline metrics recompute identically.

Findings that change the protocol (the set itself stays frozen):

| # | Severity | Finding | What we do |
|---|---|---|---|
| B1 | blocking | A **3-signal rule without any LLM** (subject UV/MV ×2, IV ×1, not inadmissible ×1, length) reaches AUC vs hard negatives 0.84 / 0.89 and F2 at transferred threshold 0.60 / 0.63, at or above zero-shot Apertus. The old "LoRA bar" (F2 0.58) is below this floor. | The rule (`audit/a07_rule_minimal.py`) is an **official baseline in every table**. |
| B2 | blocking | Fixed thresholds 0.5 / 0.01 are meaningless on uncalibrated scores (the 8B saturates: its F2-optimal threshold is 1 − 3.6e-10; the 70B's is ~0.04). The previous bar was picked post hoc. Full-quarter AUC saturates (~0.99 for the rule). | Primary metrics of §5, thresholds **transferred** from the other quarter, fixed-size lists. |
| B3 | blocking | "100 epochs": zero-shot has no epochs; 100 LoRA epochs on 45 positives is certain overfitting. | Settled by the lead (27 Nov): **100 repetitions of the run** for the zero-shot benchmark (§6). LoRA recipe stays 2–3 fixed epochs. |
| M1 | major | Q1/2026 negatives are probably noisy: Suva kept 80 % of UV merit rulings in Q4 but 53 % in Q1 (Fisher p = 0.038; 2/10 in February); 8 Q1 list rows have no SharePoint page. 25 "ambiguous" UV-merit negatives carry 16 of the 70B's 38 false positives at 0.5. | Report a **sensitivity analysis** without the 25 (list `data/derived/finetune/audit_v3/negatifs_ambigus_v3.csv`, SHA-256 `4931d15a…`). |
| M2 | major | Valid has 6 positives (AUC 95 % CI 0.74–1.00): unusable for selection. | No choice on valid: fixed recipe, out-of-fold or transferred thresholds. |
| M3 | major | 28–31 positives per quarter: wide intervals. | Pooled metrics over both quarters (59 positives, 235 hard negatives), paired bootstrap. |
| M4 | major | Measured recall is UV recall: the 8B finds 0 of the 16 IV positives. | Report recall per subject (UV / IV) and per language (DE / FR). |
| M5 | major | Two scoring chains (Keera API vs local transformers in `02_train_eval.py`). | Compare the LoRA only with the base model scored **in the same chain**. |
| M6 | major | Labels come from Suva's workbook. | Labels and per-ruling outputs stay in `data/derived/` (D-031 while open); commit aggregates and hashes only. |

Suggested v4 items (not done; only if the team decides): ask Suva to requalify the 25 ambiguous negatives and the 8 page-less Q1 rows; join labels on (docket, decision date); fix the subject regex ("Assurance-accident", "Unfall- und Invalidenversicherung"); pin every input in the manifest; one shared metrics module; use Suva's Q2/2026 list as the true hold-out once known.

## 4. Baselines already measured (zero-shot, Keera gateway, 27 Nov)

Per-ruling scores: `data/derived/finetune/runs_v3/fold{A,B}_keera_{8b,70b}/test_scores.jsonl`. Old fixed-threshold numbers (`RESULTATS_BASELINE_V3.md`, French) are **superseded** by the audit's protocol; the audit's recomputation, pooled where stated:

| System | AUC vs hard, fold_A · fold_B | F2 at transferred threshold, A · B | F2 top 45, A · B |
|---|---|---|---|
| Rule, 3 signals (no LLM) | 0.837 · 0.890 | 0.604 · 0.634 | 0.680 · 0.732 |
| Apertus 8B zero-shot | 0.789 · 0.853 | 0.685 · 0.688 | 0.680 · 0.669 |
| Apertus 70B zero-shot | 0.784 · 0.874 | 0.522 · 0.613 | 0.473 · 0.573 |

Pooled AUC vs hard: 8B 0.817, 70B 0.821; without the 25 ambiguous negatives 0.877 / 0.868. Five IV positives score ≈ 0 with both models.

Every number of this table (and the top-60, layer-1 and sensitivity numbers of the audit) is reproduced exactly by `experiments/finetune/metrics.py`, checked by `experiments/finetune/tests/test_metrics.py` (27 Nov). The same module gives the rule's pooled AUC vs hard: 0.858. Paired CIs and the §6 benchmark: `results/finetune_benchmark_v3.md`. The 70B at T=0 is not deterministic, but a 3-repetition probe on 40 rulings gave a max per-ruling score spread of 0.057 and no flip at 0.5.

## 5. Metrics (frozen before the benchmark run)

Primary (pooled over both test quarters, 95 % paired bootstrap CI, 1,000 resamples):
1. AUC vs hard negatives (59 positives vs 235 hard negatives).
2. F2 at the **transferred threshold**: threshold maximising F2 on one quarter, applied to the other; layer 2 applied after layer 1 (`couche1`), and on the full quarter.
3. F2 and recall of a **fixed-size list**: top 45 and top 60 per quarter.

Secondary: per-fold detail (fold_A = deployment view); recall UV / IV; DE / FR (IT not measurable, ~1 positive); sensitivity without the 25 ambiguous negatives; full-quarter AUC as a sanity check only; for repeated runs, mean/std/min/max of each metric and the per-ruling score spread.

Hygiene: store `logprob(Ja)`, `logprob(Nein)` and the logit, not only the normalised score; any failed call fails the run (no silent drop); every result names the dataset (`suva-ft-v3` + ids digest), model id, gateway, date, script commit.

**Implementation (frozen 27 Nov, before any benchmark call):** `experiments/finetune/metrics.py`, standard library only. Choices the text above left open, fixed there:
- Ties at the F2 optimum: the **lowest** threshold (recall first; same as the audit's `a04`). Candidate thresholds are the scores of the rulings counted (after layer 1: only `couche1` rulings).
- After layer 1: a ruling is flagged only if `couche1` and score ≥ threshold; the threshold is learnt on the other quarter's `couche1` rulings; a positive dropped by layer 1 is a miss.
- Top-k pooled = both quarters' lists together (2k rulings, 59 positives). A tie at the cut counts its expected share of positives.
- Bootstrap: 1,000 resamples, seed `20261127`, with replacement inside each quarter × stratum (positive, hard, easy); every system on the same resamples (paired); thresholds re-learnt on every resample, so the CI includes threshold selection. Percentile CI.
- Tests: `uv run --frozen pytest experiments/finetune/tests` (15 tests; the data-dependent ones skip without `data/derived/finetune/`). They go red on a mutant that takes the highest tied threshold and on one that ignores layer 1.

## 6. Baseline benchmark of standard Apertus (DONE, settled as the baseline: D-074)

Systems side by side: (a) 3-signal rule, (b) Apertus 8B zero-shot, (c) Apertus 70B zero-shot.

Repetitions (the lead, 27 Nov: "100 repetitions of the run"):
- 8B: 3 full passes on both test quarters, to confirm determinism; if the 3 are identical, report 1.
- 70B: 1 full pass on both test quarters, plus **100 repetitions on positives + hard negatives** (294 rulings, ~1.5 min per repetition at 4 workers, ~2.5 h). Report the spread and the metrics' distribution over repetitions.
- Script: `experiments/finetune/scripts/06_benchmark_repeat.py` (resumable, `--subset all|couche1|pos_hard`). Since 27 Nov it calls the gateway **through `src/llm/`** (G2: concurrency cap, timeout, one retry policy, served-model check, `llm_calls` log, cache in `data/derived/finetune/bench_v3/llm_store/`), stores `logprob(Ja)`, `logprob(Nein)`, the logit and the raw top-20 per ruling, and stops on the first failed call or unreadable answer (the old version wrote `score: null` and went on). Prompt, parameters and score definition unchanged. Repetition *i* is sent as repetition id `offset + i` (part of the cache key), so each repetition is a fresh call; the 100 repetitions use ids 1 to 100, the full pass id 0.
- Everything in one command: `experiments/finetune/scripts/run_benchmark_v3.sh` (smoke test on 3 rulings per fold and model, then the three runs, then the report). Report: `07_report_v3.py --source bench` writes `results/finetune_benchmark_v3.{md,json}` (aggregates only).
- Estimated cost (from the audit's passes, 4 workers): 45,144 calls, about 145 M prompt tokens, about 3.3 h.
- Gateway etiquette: at most 8 concurrent calls in total (16+ untested, 32 reportedly froze the gateway); D-030 while open caps one member at 5. `--slot-concurrency N` (≤ 16, the G2 team ceiling) lifts the member cap for a slot the lead approves; it is recorded in `run_args.json`, `invocations.jsonl` and every repetition's `meta.json`.
- **Concurrency ramp (Fri 27 Nov, 22:20–22:45 CET, one key, on real repetitions, the lead's request):**

  | Model | Concurrent calls | Calls/s | Latency p50 / p95 | Errors |
  |---|---|---|---|---|
  | 70B (294 calls each) | 4 | 3.26 | 1.17 / 2.09 s | 0 |
  | | 8 | 3.25 | 2.37 / 5.56 s | 0 |
  | | 12 | 3.57 | 3.34 / 4.26 s | 0 |
  | | 16 | 3.56 | 4.62 / 5.73 s | 0 |
  | 8B (full fold pass) | 4 | 11.6 | 0.34 / 0.48 s | 0 in 2,412 calls |
  | | 16 | stalled | normal for 1 min, then minutes without answers | 21 dropped connections (retried); stopped by hand |

  The 70B is throughput-bound at about 3.5 calls/s per key: more concurrency only lengthens the queue. The 8B backend did not hold 16. Both models answered normally again at 4 right after. Settings kept: **8B 4, 70B 12** (`BENCH_CONC_8B`, `BENCH_CONC_70B` in `run_benchmark_v3.sh`). Repetitions 1–4 of the 70B ran at 4, 8, 12 and 16; part of the 8B fold_B first pass ran at 16 (answers kept in the cache).
- **8B determinism (3 full passes, done 23:00 CET):** not bit-deterministic at T=0 on Keera. 3,652/3,936 rulings have the same score in every pass, max spread 0.086, 5 rulings above 0.05. The differences are spread evenly over every pair of passes, including the three fold_A passes run entirely at 4 concurrent calls, and over the audit's earlier pass: they come from the gateway, not from the concurrency ramp. Effect on results: none measurable. Every primary metric is the same in the three passes (AUC vs hard 0.816–0.817, F2 transferred 0.686, top-45 F2 0.675), and 0 rulings cross the transferred threshold. This corrects "the 8B is deterministic" (D-020 measured facts, `docs/LESSONS.md`) for large runs: worth a line there (lead's files).
- **Status: DONE, Fri 27 Nov 2026, 22:12–23:23 CET** (Keera, one key, repo HEAD `6ca53eb`, scripts untracked and identified by SHA-256 in the report). Report: `results/finetune_benchmark_v3.md` (+ `.json`), aggregates only. Smoke test first: on its rulings the new chain gave the audit's 8B scores exactly and the 70B's within 2.4e-6.
- **Cost:** 45,156 answered calls (8B 11,814; 70B 33,342) and 21 failed attempts (all in the 8B test at 16, all retried); 144.6 M prompt tokens; 71 min wall time, ramp and stops included.
- **Result:** no zero-shot Apertus model beats the 3-signal rule. Pooled AUC vs hard negatives: rule 0.858, 8B 0.816, 70B 0.822; pooled F2 at the transferred threshold: rule 0.616, 8B 0.686, 70B 0.543. On the decision metrics every paired 95 % CI against the rule includes 0. The 70B is worse than the rule on the top-45 and top-60 lists (CI below 0) and worse than the 8B on F2 transferred. In none of the 100 repetitions does the 70B reach the rule on any primary metric.
- **70B repeatability (100 repetitions, 294 rulings):** metrics are stable (AUC vs hard 0.819–0.824, F2 transferred 0.511–0.565), but single rulings are not: max per-ruling spread 0.342, 43 rulings above 0.05, none identical in every repetition, 7 cross the transferred threshold. The earlier 40-ruling probe (max 0.057) underestimated this. The 70B's F2-optimal threshold is unstable: learnt on 2026Q1 it was 0.047 in the audit's pass and 0.267 in this one, from a few moved scores.
- **Gateway fact (for `docs/LESSONS.md`, lead's file):** repetitions 5–100, sent back to back on the same 294 prompts at 12 concurrent calls, ran at about 34 calls/s with 0.14 s median latency, about 10× the 70B's normal rate: very likely prefix caching. Answers still varied, so it is not a response cache.

## 6b. FT-Q3: rule + LLM combination (pre-registered Fri 27 Nov 2026, 23:40 CET, before any combined score was computed)

Go from the lead, 27 Nov. No gateway call: it uses the stored scores.
- **Systems.** (d) **rule + 8B**: the FT-Q3 system. (e) rule + 70B: reported for completeness. Inputs: the rule (`a07`), the 8B's pass 1 and the 70B's full pass of §6 (`bench_v3/*/rep000.jsonl`). Choosing the 8B for (d) uses the §6 results on the same test quarters: stated as such.
- **Combination, fixed, no weight fitted:** inside each quarter, each component becomes a percentile rank (rank / n, ties get their average rank); the combined score is the plain mean of the two percentiles. Per quarter because a deployed triage ranks the quarter it scores.
- **Metrics:** the frozen ones of §5, same module, same bootstrap (1,000 paired resamples, seed `20261127`), thresholds transferred between quarters.
- **Pass rule, written before measuring:** (d) "beats the rule" only if, on pooled AUC vs hard negatives **and** pooled F2 at the transferred threshold, the paired 95 % CI of (d) − rule is strictly above 0. It "beats the 8B" under the same test against the 8B alone. Anything else is reported as "not shown better", whatever the point estimates.
- **Output:** `results/finetune_combo_v3.md` (+ `.json`), aggregates only.
- **Result (Fri 27 Nov, 23:55 CET): rule + 8B does not beat the rule.** Pooled AUC vs hard: rule 0.858, rule + 8B 0.843 (difference −0.015, CI −0.050 to +0.020); pooled F2 transferred: rule 0.616, rule + 8B 0.680 (+0.065, CI −0.161 to +0.135). Against the 8B alone it is better on AUC vs hard only (+0.027, CI +0.013 to +0.041), so it does not beat the 8B either. Rule + 70B does not beat the rule, but beats the 70B alone on every primary metric. Same picture without the 25 ambiguous negatives. Reading: adding the rule repairs each LLM's ranking, and adding an LLM to the rule brings no measurable gain. The point estimates on lists favour the combinations slightly (top-60 recall 0.814 for both vs 0.797 for the rule), within the noise of 59 positives.

## 7. Fine-tuning (after the benchmark, not before)

Recipe fixed in advance: LoRA r16, α 32, dropout 0.05, on the text decoder's linear layers only; loss = cross-entropy on the single answer token (variant: 2-class CE on [Ja, Nein]); positives oversampled ×4 (or class weights); 2–3 epochs fixed; evaluate the **final** adapter; threshold transferred. Script `02_train_eval.py` (untested, needs a CUDA GPU ≥ 40 GB for the 8B in bf16).

Apertus v1.5 specifics: gated on Hugging Face (accept terms, then login); multimodal class `Apertus1p5ForConditionalGeneration`, 8.61 G bf16 + 0.29 G fp32 params; needs the swiss-ai transformers fork at commit `3797303dda74844e3d1f8977ff5518bb91f818b4`; logits are padded from 131,072 text tokens to 266,752 (keep only the last position); never `.half()` or `.to(dtype)` (vision/audio tokenizers stay fp32); thinking mode off. Keera serves base models only: a LoRA cannot be served there.

**Decision rule.** The LoRA is kept only if, on the pooled primary metrics (AUC vs hard **and** F2 at transferred threshold), its difference with the rule **and** with the best zero-shot model has a paired 95 % CI strictly above 0, measured in the same scoring chain.

## 8. Open questions (raise with a recommendation; do not settle silently)

| # | Question | Recommendation |
|---|---|---|
| FT-Q1 | Requalify the 25 ambiguous negatives with Suva (v4)? | Ask Suva at the next contact; meanwhile report the sensitivity analysis. |
| FT-Q2 | Where does the GPU come from (HF credits L40S, Kaggle T4 QLoRA, other)? | The lead is costing it; nothing runs on Keera. |
| FT-Q3 | If the rule beats Apertus, should the delivered triage combine rule + LLM? | Measured (§6b, 27 Nov): rule + 8B does not beat the rule. For ranking, an LLM adds nothing measurable on top of the rule; the case for Apertus in triage rests on what the rule cannot give (the written explanation G5 asks for, the IV and civil-law rulings the rule misses), not on ranking. For the triage owner (D-021). |
| FT-Q4 | D-031: may labels or per-ruling outputs ever be committed? | No until D-031 is settled; aggregates only. |
| FT-Q5 | G2 was not enforced on `experiments/`. | **Done 28 Nov:** `tests/test_doctrines.py` scans `experiments/` (its test folders aside, as the root `tests/`); shown red on `03_keera_baseline.py` (direct gateway call) and on two variable names in a docstring of `06`, then green after removing `03` (in git history at `6b254ae`) and rewording the docstring. |
| FT-Q6 | When may the 3.3 h, 45,144-call benchmark run? It shares the gateway with the delivered pipeline's overnight run (D-030, Q-14; key price or quota unknown). | In a slot the team agrees on, at 4 workers, after the delivered pipeline's overnight calls are budgeted. The 8B passes and the 70B full pass (≈ 50 min) first; the 100 repetitions (≈ 2.5 h) can wait. |
| FT-Q7 | `experiments/` was not in the repo map. | **Done 28 Nov:** one line in `AGENTS.md` §4. |
| FT-Q8 | G13: team members' names were in files to be published (manifest `status`, `verify_dataset.py` docstring, `docs/agents/finetune.md` step 5). | **Done 28 Nov:** replaced by "the lead" before the first commit; the manifest edit is in the §2 freeze record. |
| FT-Q9 | `make check` was red on any machine holding `data/derived/finetune/`: the D-051 test read the compressed bytes of `suva-ft-v3.zip` and matched a staff code by chance (6 hits, all inside the deflate stream). | **Done 28 Nov:** the scanner reads `.zip` and `.gz` archives member by member (`tests/suva_forbidden.py`), with a self-test shown red on the old scanner; 0 hits on the 45,654 local data files. |
