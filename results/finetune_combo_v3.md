# FT-Q3 on suva-ft-v3: rule + Apertus combination (rank average)

Machine-written by `experiments/finetune/scripts/07_report_v3.py`. Aggregates only (D-031): no docket, no per-ruling score.

| Item | Value |
|---|---|
| Dataset | `suva-ft-v3`, ids digest `69f8e4b0c7714898d8df0765138f0dbe687e83705d1d793c531c3f80d23785b6`; `verify_dataset.py`: IDENTIQUE au manifeste |
| Population | 2026Q1 (fold_A test): 31 pos, 131 hard, 1843 easy · 2025Q4 (fold_B test): 28 pos, 104 hard, 1799 easy |
| Generated | 2026-11-27 23:38 CET; repo HEAD `6ca53eb` (experiments/ untracked: scripts identified by SHA-256 below) |
| Bootstrap | paired, 1000 resamples, seed 20261127, stratified by quarter × (pos, hard, easy); thresholds re-learnt on every resample |
| Rule, 3 signals (no LLM) | audit/a07_rule_minimal.py on the a02 features; date deterministic; features_sha256 c25af3de6e0dd84cd201be31adc650375088b39738a19cd616a541f15cf0064c |
| Apertus 8B zero-shot | 06_benchmark_repeat.py, 8b_all, repetition file rep000; model apertus-v1-5-8b; gateway Keera; date 2026-11-27T21:46:08+00:00; git_head 6ca53eb; script_sha256 e31cef6d5cfd9c779688983c0c81cb493c5ca4fcdd8212b70911e3849c687317; ids_digest 69f8e4b0c7714898d8df0765138f0dbe687e83705d1d793c531c3f80d23785b6; calls 11808; live_calls 10789; prompt_tokens 35584560; wall_s 935.8; served_models ['apertus-v1-5-8b'] |
| Apertus 70B zero-shot | 06_benchmark_repeat.py, 70b_all, repetition file rep000; model apertus-v1-5-70b; gateway Keera; date 2026-11-27T21:58:51+00:00; git_head 6ca53eb; script_sha256 e31cef6d5cfd9c779688983c0c81cb493c5ca4fcdd8212b70911e3849c687317; ids_digest 69f8e4b0c7714898d8df0765138f0dbe687e83705d1d793c531c3f80d23785b6; calls 3936; live_calls 3930; prompt_tokens 11861520; wall_s 691.7; served_models ['apertus-v1-5-70b'] |
| Rule + 8B (rank average) | mean of within-quarter percentile ranks of the rule and Apertus 8B zero-shot (no weight fitted); inputs rule; 06_benchmark_repeat.py, 8b_all, repetition file rep000 |
| Rule + 70B (rank average) | mean of within-quarter percentile ranks of the rule and Apertus 70B zero-shot (no weight fitted); inputs rule; 06_benchmark_repeat.py, 70b_all, repetition file rep000 |
| Scripts SHA-256 | `metrics.py` ef78550d95d9…; `scripts/07_report_v3.py` 1ac1b11c83c5…; `scripts/06_benchmark_repeat.py` e31cef6d5cfd…; `audit/a07_rule_minimal.py` bec2b8cdb1b4… |
| Ambiguous negatives | 25 dockets, list SHA-256 `4931d15a44d5…` |

## Verdict

**Rule + 8B, the FT-Q3 system, does not beat the three-signal rule.** Pass rule written before measuring (`docs/FINETUNE.md` §6b): paired 95 % CI strictly above 0 on pooled AUC vs hard negatives and pooled F2 at the transferred threshold. Rule + 8B (rank average) does not beat the rule (both paired 95 % CIs include 0). Compared with 8B alone, it does not beat 8B alone: better on AUC vs hard only (the pass rule needs both decision metrics). Rule + 70B (rank average) does not beat the rule (both paired 95 % CIs include 0). Compared with 70B alone, it beats 70B alone on both decision metrics (paired 95 % CIs strictly above 0); on the other primary metrics it is better than 70B alone on top-45 F2, top-45 recall, top-60 F2 and top-60 recall. Point estimates: AUC vs hard Rule 0.858, 8B 0.816, 70B 0.822, Rule+8B 0.843, Rule+70B 0.853; F2 transferred Rule 0.616, 8B 0.686, 70B 0.543, Rule+8B 0.680, Rule+70B 0.659. With 59 positives the intervals are wide: differences of a few points cannot be resolved, so "does not beat" is not "is equal".

## Primary metrics (pooled over both test quarters, 95 % paired bootstrap CI)

| Metric | Rule, 3 signals (no LLM) | Apertus 8B zero-shot | Apertus 70B zero-shot | Rule + 8B (rank average) | Rule + 70B (rank average) |
|---|---|---|---|---|---|
| AUC vs hard negatives (59 pos vs 235 hard) | 0.858 [0.804, 0.914] | 0.816 [0.749, 0.877] | 0.822 [0.764, 0.876] | 0.843 [0.782, 0.901] | 0.853 [0.797, 0.905] |
| F2 at transferred threshold, full quarter | 0.616 [0.543, 0.749] | 0.686 [0.552, 0.775] | 0.543 [0.418, 0.629] | 0.680 [0.508, 0.753] | 0.659 [0.529, 0.740] |
| F2 at transferred threshold, after layer 1 | 0.616 [0.543, 0.749] | 0.686 [0.539, 0.775] | 0.588 [0.479, 0.673] | 0.680 [0.502, 0.753] | 0.659 [0.547, 0.740] |
| F2 of the top-45 list per quarter | 0.706 [0.613, 0.782] | 0.675 [0.567, 0.767] | 0.521 [0.429, 0.629] | 0.706 [0.598, 0.782] | 0.667 [0.567, 0.767] |
| Recall of the top-45 list per quarter | 0.780 [0.678, 0.864] | 0.746 [0.627, 0.847] | 0.576 [0.475, 0.695] | 0.780 [0.661, 0.864] | 0.737 [0.627, 0.847] |
| F2 of the top-60 list per quarter | 0.660 [0.590, 0.744] | 0.632 [0.548, 0.716] | 0.562 [0.463, 0.646] | 0.674 [0.600, 0.758] | 0.674 [0.590, 0.744] |
| Recall of the top-60 list per quarter | 0.797 [0.712, 0.898] | 0.763 [0.661, 0.864] | 0.678 [0.559, 0.780] | 0.814 [0.725, 0.915] | 0.814 [0.712, 0.898] |

Counts at the transferred threshold (TP / FP, pooled, full quarter): Rule, 3 signals (no LLM) 42 / 63; Apertus 8B zero-shot 42 / 28; Apertus 70B zero-shot 38 / 76; Rule + 8B (rank average) 43 / 37; Rule + 70B (rank average) 44 / 54.

### Paired differences (a − b; the decision rule needs the CI strictly above 0)

| Metric | 8B − Rule | 70B − Rule | 70B − 8B | Rule+8B − Rule | Rule+8B − 8B | Rule+70B − Rule | Rule+70B − 70B |
|---|---|---|---|---|---|---|---|
| AUC vs hard negatives (59 pos vs 235 hard) | -0.041 [-0.083, +0.001] includes 0 | -0.035 [-0.080, +0.010] includes 0 | +0.006 [-0.038, +0.051] includes 0 | -0.015 [-0.050, +0.020] includes 0 | +0.027 [+0.013, +0.041] **above 0** | -0.005 [-0.039, +0.031] includes 0 | +0.030 [+0.016, +0.045] **above 0** |
| F2 at transferred threshold, full quarter | +0.070 [-0.074, +0.126] includes 0 | -0.073 [-0.238, +0.008] includes 0 | -0.143 [-0.257, -0.033] **below 0** | +0.065 [-0.161, +0.135] includes 0 | -0.006 [-0.174, +0.088] includes 0 | +0.043 [-0.135, +0.111] includes 0 | +0.116 [+0.010, +0.209] **above 0** |
| F2 at transferred threshold, after layer 1 | +0.070 [-0.088, +0.127] includes 0 | -0.028 [-0.168, +0.051] includes 0 | -0.098 [-0.196, +0.016] includes 0 | +0.065 [-0.165, +0.134] includes 0 | -0.006 [-0.173, +0.099] includes 0 | +0.043 [-0.121, +0.114] includes 0 | +0.070 [-0.020, +0.154] includes 0 |
| F2 of the top-45 list per quarter | -0.031 [-0.107, +0.015] includes 0 | -0.184 [-0.276, -0.061] **below 0** | -0.153 [-0.230, -0.031] **below 0** | +0.000 [-0.061, +0.046] includes 0 | +0.031 [-0.015, +0.092] includes 0 | -0.038 [-0.123, +0.061] includes 0 | +0.146 [+0.061, +0.230] **above 0** |
| Recall of the top-45 list per quarter | -0.034 [-0.119, +0.017] includes 0 | -0.203 [-0.305, -0.068] **below 0** | -0.169 [-0.254, -0.034] **below 0** | +0.000 [-0.068, +0.051] includes 0 | +0.034 [-0.017, +0.102] includes 0 | -0.042 [-0.136, +0.068] includes 0 | +0.161 [+0.068, +0.254] **above 0** |
| F2 of the top-60 list per quarter | -0.028 [-0.112, +0.028] includes 0 | -0.098 [-0.211, -0.028] **below 0** | -0.070 [-0.169, +0.000] includes 0 | +0.014 [-0.046, +0.056] includes 0 | +0.042 [+0.000, +0.084] includes 0 | +0.014 [-0.056, +0.056] includes 0 | +0.112 [+0.042, +0.183] **above 0** |
| Recall of the top-60 list per quarter | -0.034 [-0.136, +0.034] includes 0 | -0.119 [-0.254, -0.034] **below 0** | -0.085 [-0.203, +0.000] includes 0 | +0.017 [-0.055, +0.068] includes 0 | +0.051 [+0.000, +0.102] includes 0 | +0.017 [-0.068, +0.068] includes 0 | +0.136 [+0.051, +0.220] **above 0** |

## Per fold (fold_A = deployment view: trained on 2025Q4, tested on 2026Q1)

| Metric | Rule, 3 signals (no LLM) 2026Q1 | Rule, 3 signals (no LLM) 2025Q4 | Apertus 8B zero-shot 2026Q1 | Apertus 8B zero-shot 2025Q4 | Apertus 70B zero-shot 2026Q1 | Apertus 70B zero-shot 2025Q4 | Rule + 8B (rank average) 2026Q1 | Rule + 8B (rank average) 2025Q4 | Rule + 70B (rank average) 2026Q1 | Rule + 70B (rank average) 2025Q4 |
|---|---|---|---|---|---|---|---|---|---|---|
| AUC vs hard | 0.837 [0.752, 0.919] | 0.890 [0.810, 0.948] | 0.788 [0.687, 0.878] | 0.853 [0.758, 0.924] | 0.787 [0.703, 0.866] | 0.871 [0.794, 0.934] | 0.812 [0.714, 0.900] | 0.870 [0.780, 0.934] | 0.820 [0.739, 0.897] | 0.893 [0.821, 0.950] |
| F2 transferred, full | 0.604 [0.534, 0.780] | 0.634 [0.437, 0.784] | 0.685 [0.467, 0.794] | 0.688 [0.534, 0.833] | 0.515 [0.352, 0.628] | 0.582 [0.380, 0.723] | 0.653 [0.265, 0.763] | 0.714 [0.564, 0.839] | 0.652 [0.397, 0.757] | 0.667 [0.524, 0.791] |
| F2 transferred, L1 | 0.604 [0.534, 0.780] | 0.634 [0.437, 0.784] | 0.685 [0.467, 0.794] | 0.688 [0.534, 0.833] | 0.565 [0.396, 0.679] | 0.614 [0.452, 0.740] | 0.653 [0.265, 0.763] | 0.714 [0.563, 0.839] | 0.652 [0.411, 0.751] | 0.667 [0.528, 0.791] |
| F2 top-45 | 0.680 [0.533, 0.799] | 0.732 [0.605, 0.828] | 0.680 [0.518, 0.799] | 0.669 [0.510, 0.796] | 0.473 [0.355, 0.621] | 0.573 [0.414, 0.732] | 0.680 [0.533, 0.799] | 0.732 [0.605, 0.828] | 0.636 [0.503, 0.769] | 0.701 [0.573, 0.828] |
| F2 top-60 | 0.625 [0.516, 0.761] | 0.698 [0.610, 0.785] | 0.652 [0.516, 0.761] | 0.610 [0.494, 0.727] | 0.516 [0.380, 0.652] | 0.610 [0.465, 0.727] | 0.652 [0.516, 0.761] | 0.698 [0.591, 0.785] | 0.652 [0.543, 0.761] | 0.698 [0.581, 0.785] |
| AUC full quarter (sanity) | 0.989 [0.984, 0.995] | 0.994 [0.990, 0.997] | 0.963 [0.937, 0.986] | 0.978 [0.959, 0.992] | 0.957 [0.929, 0.981] | 0.967 [0.944, 0.985] | 0.985 [0.977, 0.993] | 0.992 [0.986, 0.996] | 0.984 [0.975, 0.993] | 0.992 [0.985, 0.997] |

Transferred thresholds (learnt on the other quarter, full / after L1): Rule, 3 signals (no LLM) 2026Q1: 2.0184 / 2.0184; Rule, 3 signals (no LLM) 2025Q4: 3.0093 / 3.0093; Apertus 8B zero-shot 2026Q1: 1 − 3.6e-10 / 1 − 3.6e-10; Apertus 8B zero-shot 2025Q4: 1 − 3.6e-10 / 1 − 3.6e-10; Apertus 70B zero-shot 2026Q1: 0.0372 / 0.0372; Apertus 70B zero-shot 2025Q4: 0.2668 / 0.0032; Rule + 8B (rank average) 2026Q1: 0.9671 / 0.9671; Rule + 8B (rank average) 2025Q4: 0.9807 / 0.9807; Rule + 70B (rank average) 2026Q1: 0.9549 / 0.9549; Rule + 70B (rank average) 2025Q4: 0.9653 / 0.9653.
fold_B trains on rulings later than its test quarter (soft temporal leak; it does not touch labels).

## Recall by subject and language (pooled)

At the transferred threshold (full quarter), then in the top-60 list per quarter. IT has 1 positive: not measurable.

| Group | Rule, 3 signals (no LLM) @thr | Apertus 8B zero-shot @thr | Apertus 70B zero-shot @thr | Rule + 8B (rank average) @thr | Rule + 70B (rank average) @thr | Rule, 3 signals (no LLM) top-60 | Apertus 8B zero-shot top-60 | Apertus 70B zero-shot top-60 | Rule + 8B (rank average) top-60 | Rule + 70B (rank average) top-60 |
|---|---|---|---|---|---|---|---|---|---|---|
| UV (43 pos) | 0.930 [0.833, 1.000] | 0.977 [0.829, 1.000] | 0.814 [0.634, 0.923] | 1.000 [0.651, 1.000] | 0.953 [0.739, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 0.837 [0.714, 0.930] | 1.000 [1.000, 1.000] | 0.977 [0.925, 1.000] |
| IV (16 pos) | 0.125 [0.000, 0.619] | 0.000 [0.000, 0.133] | 0.188 [0.000, 0.400] | 0.000 [0.000, 0.412] | 0.188 [0.000, 0.524] | 0.250 [0.077, 0.550] | 0.125 [0.000, 0.333] | 0.250 [0.000, 0.467] | 0.312 [0.100, 0.545] | 0.375 [0.125, 0.588] |
| DE (41 pos) | 0.634 [0.533, 0.846] | 0.659 [0.500, 0.805] | 0.488 [0.348, 0.658] | 0.683 [0.455, 0.829] | 0.634 [0.462, 0.789] | 0.756 [0.639, 0.897] | 0.707 [0.590, 0.850] | 0.537 [0.385, 0.682] | 0.756 [0.632, 0.895] | 0.732 [0.587, 0.850] |
| FR (17 pos) | 0.882 [0.667, 1.000] | 0.882 [0.647, 1.000] | 1.000 [0.700, 1.000] | 0.882 [0.529, 1.000] | 1.000 [0.750, 1.000] | 0.941 [0.786, 1.000] | 0.941 [0.750, 1.000] | 1.000 [0.929, 1.000] | 1.000 [0.889, 1.000] | 1.000 [1.000, 1.000] |
| IT (1 pos) | 1.000 [0.000, 1.000] | 0.000 [0.000, 0.000] | 1.000 [0.000, 1.000] | 0.000 [0.000, 0.000] | 1.000 [0.000, 1.000] | 0.000 [0.000, 1.000] | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] |

## Sensitivity: without the 25 ambiguous negatives (audit finding M1)

| Metric | Rule, 3 signals (no LLM) | Apertus 8B zero-shot | Apertus 70B zero-shot | Rule + 8B (rank average) | Rule + 70B (rank average) | 8B − Rule | 70B − Rule | Rule+8B − Rule | Rule+70B − Rule |
|---|---|---|---|---|---|---|---|---|---|
| AUC vs hard negatives (59 pos vs 235 hard) | 0.900 [0.847, 0.943] | 0.877 [0.810, 0.933] | 0.870 [0.815, 0.914] | 0.888 [0.826, 0.942] | 0.896 [0.845, 0.938] | -0.023 [-0.069, +0.020] includes 0 | -0.030 [-0.072, +0.015] includes 0 | -0.012 [-0.051, +0.027] includes 0 | -0.004 [-0.038, +0.033] includes 0 |
| F2 at transferred threshold, full quarter | 0.665 [0.581, 0.813] | 0.742 [0.595, 0.827] | 0.572 [0.446, 0.660] | 0.739 [0.534, 0.819] | 0.707 [0.563, 0.785] | +0.077 [-0.075, +0.134] includes 0 | -0.092 [-0.258, -0.002] **below 0** | +0.074 [-0.196, +0.144] includes 0 | +0.043 [-0.149, +0.118] includes 0 |
| F2 at transferred threshold, after layer 1 | 0.665 [0.581, 0.813] | 0.742 [0.570, 0.827] | 0.625 [0.513, 0.716] | 0.739 [0.534, 0.819] | 0.707 [0.589, 0.781] | +0.077 [-0.089, +0.135] includes 0 | -0.040 [-0.196, +0.054] includes 0 | +0.074 [-0.196, +0.144] includes 0 | +0.043 [-0.135, +0.117] includes 0 |
| F2 of the top-45 list per quarter | 0.736 [0.644, 0.798] | 0.690 [0.583, 0.782] | 0.583 [0.475, 0.675] | 0.721 [0.629, 0.813] | 0.721 [0.629, 0.798] | -0.046 [-0.123, +0.031] includes 0 | -0.153 [-0.261, -0.061] **below 0** | -0.015 [-0.077, +0.061] includes 0 | -0.015 [-0.077, +0.061] includes 0 |

## How to read this

- Thresholds are never chosen on the quarter they are measured on; the valid split selects nothing.
- A tie at a top-k cut counts its expected share of positives. Ties at the F2 optimum take the lowest threshold (recall first).
- Full-quarter AUC saturates (easy negatives) and is a sanity check only.
- Labels come from Suva's workbook; Q1/2026 negatives are probably noisy (M1): read the sensitivity table with the main one.
