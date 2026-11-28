# Role brief: LAYER 2 benchmark and Apertus fine-tuning (experimental)

> **Status: v0 (27 Nov 2026).** Owner: `<handle>` (layer 2). Read `AGENTS.md`, `docs/FINETUNE.md` (the reference for everything below), `docs/DATA.md` §6, `docs/EVAL.md` and `docs/DECISIONS.md` D-031 first.

## Mission
Give the team an honest answer to one question: **does Apertus, zero-shot and later fine-tuned, judge Suva relevance better than a three-line rule?** Measured on the frozen set `suva-ft-v3`, with intervals, without touching the delivered pipeline until a gain is proven.

## You own
`experiments/finetune/`, `data/derived/finetune/` (git-ignored), `docs/FINETUNE.md`, the layer-2 rows of `results/` (aggregates only) and the fine-tune lines of `MODELS.md` (base model ids, adapter if any, training data hash).

## Steps
1. **Freeze and verify the evaluation set.** Unpack `suva-ft-v3.zip` into `data/derived/finetune/suva-ft-v3/`, check the zip hash against `experiments/finetune/manifests/suva-ft-v3/suva-ft-v3.zip.sha256`, run `verify_dataset.py` (must print `IDENTIQUE au manifeste`). Record the ids digest `69f8e4b0…85b6` in `docs/FINETUNE.md` and in `results/`. Never regenerate in place; any change becomes `suva-ft-v4` with its own manifest. Optional: rebuild from the pinned parquet with `05_build_dataset_v3.py` and confirm bit equality.
2. **Freeze the metrics before running.** Implement the primary and secondary metrics of `docs/FINETUNE.md` §5 in one module (pooled AUC vs hard, F2 at transferred threshold, top-45 / top-60, paired bootstrap, recall UV/IV and DE/FR, sensitivity without the 25 ambiguous negatives). Unit-test it on the existing per-ruling scores: it must reproduce the audit's numbers (§4 table).
3. **Run the initial benchmark** (`docs/FINETUNE.md` §6): rule (`audit/a07_rule_minimal.py`), 8B zero-shot (3 passes), 70B zero-shot (1 full pass + 100 repetitions on positives + hard negatives) with `06_benchmark_repeat.py`. Max 8 concurrent gateway calls. Store logprobs.
4. **Report** in `results/finetune_benchmark_v3.md`: one table per primary metric with the three systems side by side and CIs, the per-fold detail, the repetition spread of the 70B, the sensitivity analysis, and a one-paragraph verdict. Aggregates only in git.
5. **Stop and hand back to the lead** before any fine-tuning. The LoRA (§7) starts only on the lead's go, with the GPU the lead chooses.

## Rules specific to this role
- Labels, per-ruling scores, prompts and ruling texts are Suva-derived: `data/derived/` only, never committed while D-031 is open (D-019, D-031). Only manifests of ids, hashes, scripts and aggregate metrics are committed.
- Thresholds are transferred from the other quarter or fixed lists; never chosen on the test quarter. The valid split (6 positives) selects nothing.
- Every number cites the dataset (`suva-ft-v3`, ids digest), model id, gateway, date and commit.
- The rule is a baseline in every table. A system that does not beat it is reported as such.
- Layer 1 is not yours: use `meta.couche1` as an input subset, never change the filter (layer-1 owner, `docs/TIPS_LAYER1_FILTER_HANDOFF.md`).
- No commit or push without the lead's explicit go.

## Done when
`suva-ft-v3` is verified and its digest recorded; the metrics module is tested against the audit's numbers; `results/finetune_benchmark_v3.md` shows rule vs 8B vs 70B on the frozen primary metrics with paired CIs, the 70B spread over 100 repetitions, the sensitivity analysis and a verdict; nothing Suva-derived is staged in git.
