# experiments/finetune — layer-2 benchmark and Apertus fine-tuning (experimental)

Reference: `docs/FINETUNE.md`. Role brief: `docs/agents/finetune.md`.

| Path | What | In git? |
|---|---|---|
| `manifests/suva-ft-v3/MANIFEST_suva_ft_v3.json` | frozen ids per fold/split, file hashes, sources, design (no labels per id) | yes |
| `manifests/suva-ft-v3/*.sha256` | hashes of the data archive and of the ambiguous-negatives list | yes |
| `scripts/04_build_dataset_v2.py`, `05_build_dataset_v3.py` | deterministic builders (v3 imports v2 and `../filtre_couche1/filtre_e.py`) | yes |
| `scripts/verify_dataset.py` | checks a data folder against a manifest (stdlib only) | yes |
| `scripts/metrics_only.py` | metrics used by `02_train_eval.py` (fixed thresholds, superseded by `metrics.py` for reports). `03_keera_baseline.py`, which scored `runs_v3` with a direct gateway call, was removed on 28 Nov (G2; in git history at `6b254ae`) | yes |
| `metrics.py` | **the** layer-2 metrics module (`docs/FINETUNE.md` §5), frozen before the benchmark; reproduces the audit's numbers | yes |
| `tests/` | tests of `metrics.py` (synthetic + reproduction of the audit) and of the runner (3 real rulings, declared mock gateway): `uv run --frozen pytest experiments/finetune/tests` | yes |
| `scripts/06_benchmark_repeat.py` | repeated, resumable zero-shot benchmark through `src/llm/`; stores logprobs; stops on the first failure; `--dry-run`, `--limit N` or `--all` | yes |
| `scripts/07_report_v3.py` | rule vs 8B vs 70B report with paired bootstrap CIs, sensitivity, repeatability; `--combos` adds rule + LLM rank averages (FT-Q3); writes `results/finetune_*_v3.{md,json}` (aggregates only) | yes |
| `scripts/run_benchmark_v3.sh` | the whole §6 benchmark in one resumable command (needs `LLM_*` in the environment) | yes |
| `scripts/02_train_eval.py`, `setup.sh` | LoRA training/eval on a CUDA GPU (untested) | yes |
| `scripts/01_build_dataset.py` | historical v1 builder, do not use | yes |
| `filtre_couche1/filtre_e.py` | layer-1 whitelist E, used only to compute `meta.couche1` | yes |
| `audit/a01..a08_*.py` | the independent audit's read-only scripts (labels, negatives, leakage, metrics, UV selection, sensitivity, 3-signal rule, top-k) | yes |
| `data/derived/finetune/suva-ft-v3/` | the frozen JSONL data (texts + labels) and `suva-ft-v3.zip` | **no** (git-ignored, D-031) |
| `data/derived/finetune/runs_v3/` | per-ruling baseline scores (Keera 8B/70B, both folds) | **no** |
| `data/derived/finetune/bench_v3/` | benchmark outputs: per-repetition scores and logprobs, run metadata, `llm_store/` (cache + call log), `run.log` | **no** |
| `data/derived/finetune/audit_v3/` | audit report (French), ambiguous-negatives list, audit outputs | **no** |
| `data/derived/finetune/population/` | population CSV with Suva labels (`population_tf_hf_2025Q3_2026Q2.csv`, `positifs_suva.csv`) | **no** |
| `data/derived/finetune/reference_fr/` | earlier French notes (specialisation, dataset READMEs v1–v3, baseline results) | **no** |

Quick check: `python3 -I experiments/finetune/scripts/verify_dataset.py --manifest experiments/finetune/manifests/suva-ft-v3/MANIFEST_suva_ft_v3.json --data data/derived/finetune/suva-ft-v3`
