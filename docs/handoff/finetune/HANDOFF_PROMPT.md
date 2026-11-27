# Handoff prompt — layer-2 benchmark (paste to the repo agent)

> Written 27 Nov 2026 for an agent working in `suva-NGA`. Paste everything below the line.

---

You take over the **layer-2 benchmark and Apertus fine-tuning** workstream of this repo. It is experimental: it must not change the delivered pipeline until a measured gain is proven.

**Read first, in this order:** `AGENTS.md`, `docs/agents/finetune.md` (your role brief), `docs/FINETUNE.md` (the reference: dataset, audit findings, metrics, benchmark plan, decision rule), `experiments/finetune/README.md` (what is where), `docs/DECISIONS.md` D-019 and D-031, `docs/TIPS_LAYER1_FILTER_HANDOFF.md` §8 (the layer-1 flag you consume). Then list the open questions that touch your task (`docs/FINETUNE.md` §8 and any D-0xx/Q-xx you hit) with a one-line recommendation each, before you start.

**Hard rules.**
- Everything Suva-derived (labels, per-ruling scores, prompts with ruling text, the JSONL data, the audit outputs) lives in `data/derived/finetune/` (git-ignored). Only manifests of ids, hashes, scripts and aggregate metrics may be committed, and **nothing is committed or pushed without the lead's explicit go**.
- The evaluation set `suva-ft-v3` is frozen. Never regenerate it in place; any change is `suva-ft-v4` with a new manifest and the lead's approval.
- Thresholds are transferred from the other quarter or come from fixed-size lists. Nothing is chosen on a test quarter; the valid split (6 positives) selects nothing.
- The 3-signal rule (`experiments/finetune/audit/a07_rule_minimal.py`) is a baseline in every table.
- Keera gateway: at most 8 concurrent calls in total; the key comes from the environment (`KEERA_API_KEY`) or the proxy, never from a file; a failed call fails the run.
- Every number states: dataset `suva-ft-v3` + ids digest, model id, gateway, date, commit.

**Task 1 — Freeze the evaluation set.**
1. Check that `data/derived/finetune/suva-ft-v3.zip` matches `experiments/finetune/manifests/suva-ft-v3/suva-ft-v3.zip.sha256`; it is already unpacked in `data/derived/finetune/suva-ft-v3/` (folders `fold_A/`, `fold_B/`).
2. Run `python3 -I experiments/finetune/scripts/verify_dataset.py --manifest experiments/finetune/manifests/suva-ft-v3/MANIFEST_suva_ft_v3.json --data data/derived/finetune/suva-ft-v3`. It must end with `IDENTIQUE au manifeste`. If not, stop and report.
3. Record in `docs/FINETUNE.md` §2 the date of your verification and the ids digest `69f8e4b0c7714898d8df0765138f0dbe687e83705d1d793c531c3f80d23785b6`. Add a short "Freeze record" line: who verified, when, machine, result.
4. Optional but recommended: rebuild from the pinned parquet (`huggingface.co/datasets/voilaj/swiss-caselaw` at commit `35b17aa9c3fad71011b72f78f6ab79650ec0cf96`, SHA-256 `d2b2df1d…bb3711`) with `05_build_dataset_v3.py` and confirm bit equality.

**Task 2 — Freeze the metrics, then run the initial benchmark of base Apertus (no fine-tuning).**
1. Write one metrics module (e.g. `experiments/finetune/metrics.py`) implementing `docs/FINETUNE.md` §5: pooled AUC vs hard negatives, F2 at transferred threshold (with and without layer 1), F2/recall of top-45 and top-60 lists, paired bootstrap 95 % CIs (1,000 resamples), recall UV/IV and DE/FR, sensitivity without the 25 ambiguous negatives (`data/derived/finetune/audit_v3/negatifs_ambigus_v3.csv`, hash in the manifests folder). Test it on the existing scores in `data/derived/finetune/runs_v3/`: it must reproduce the audit table of `docs/FINETUNE.md` §4 (AUC vs hard 8B 0.789/0.853, 70B 0.784/0.874; rule 0.837/0.890; pooled 8B 0.817, 70B 0.821).
2. Run the benchmark of `docs/FINETUNE.md` §6 with `experiments/finetune/scripts/06_benchmark_repeat.py` (resumable; outputs in `data/derived/finetune/bench_v3/`):
   - the rule on both test quarters;
   - Apertus 8B (`apertus-v1-5-8b`) zero-shot: 3 full passes on both folds' test splits (`--subset all --reps 3`); confirm determinism;
   - Apertus 70B (`apertus-v1-5-70b`) zero-shot: 1 full pass (`--subset all --reps 1`) and **100 repetitions on positives + hard negatives** (`--subset pos_hard --reps 100`, 294 rulings, about 2.5 h). The lead chose "100 repetitions of the run" for the "100 epochs" request: zero-shot has no epochs.
   - Store `logprob(Ja)`, `logprob(Nein)` and the logit per ruling (extend the scorer if needed, without changing the prompt or the score definition).
3. Write `results/finetune_benchmark_v3.md` (aggregates only): per primary metric, rule vs 8B vs 70B with paired CIs; per-fold detail (fold_A = deployment view); 70B repetition spread (per-ruling max spread, rulings flipping across thresholds, metric mean/std/min/max over 100 runs); recall UV/IV and DE/FR; sensitivity analysis; a one-paragraph verdict that says plainly whether Apertus beats the rule.

**Then stop.** Do not start the LoRA. Hand back to the lead with: the freeze record, the results file, the open questions with recommendations, and the cost of the runs (calls, tokens, wall time). The fine-tune (recipe in `docs/FINETUNE.md` §7, GPU still to be chosen) starts only on the lead's go.
