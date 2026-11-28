# Layer-2 benchmark on suva-ft-v3: rule vs Apertus zero-shot

Machine-written by `experiments/finetune/scripts/07_report_v3.py`. Aggregates only (D-031): no docket, no per-ruling score.

| Item | Value |
|---|---|
| Dataset | `suva-ft-v3`, ids digest `69f8e4b0c7714898d8df0765138f0dbe687e83705d1d793c531c3f80d23785b6`; `verify_dataset.py`: IDENTIQUE au manifeste |
| Population | 2026Q1 (fold_A test): 31 pos, 131 hard, 1843 easy · 2025Q4 (fold_B test): 28 pos, 104 hard, 1799 easy |
| Generated | 2026-11-27 23:39 CET; repo HEAD `6ca53eb` (experiments/ untracked: scripts identified by SHA-256 below) |
| Bootstrap | paired, 1000 resamples, seed 20261127, stratified by quarter × (pos, hard, easy); thresholds re-learnt on every resample |
| Rule, 3 signals (no LLM) | audit/a07_rule_minimal.py on the a02 features; date deterministic; features_sha256 c25af3de6e0dd84cd201be31adc650375088b39738a19cd616a541f15cf0064c |
| Apertus 8B zero-shot | 06_benchmark_repeat.py, 8b_all, repetition file rep000; model apertus-v1-5-8b; gateway Keera; date 2026-11-27T21:46:08+00:00; git_head 6ca53eb; script_sha256 e31cef6d5cfd9c779688983c0c81cb493c5ca4fcdd8212b70911e3849c687317; ids_digest 69f8e4b0c7714898d8df0765138f0dbe687e83705d1d793c531c3f80d23785b6; calls 11808; live_calls 10789; prompt_tokens 35584560; wall_s 935.8; served_models ['apertus-v1-5-8b'] |
| Apertus 70B zero-shot | 06_benchmark_repeat.py, 70b_all, repetition file rep000; model apertus-v1-5-70b; gateway Keera; date 2026-11-27T21:58:51+00:00; git_head 6ca53eb; script_sha256 e31cef6d5cfd9c779688983c0c81cb493c5ca4fcdd8212b70911e3849c687317; ids_digest 69f8e4b0c7714898d8df0765138f0dbe687e83705d1d793c531c3f80d23785b6; calls 3936; live_calls 3930; prompt_tokens 11861520; wall_s 691.7; served_models ['apertus-v1-5-70b'] |
| Scripts SHA-256 | `metrics.py` ef78550d95d9…; `scripts/07_report_v3.py` 1ac1b11c83c5…; `scripts/06_benchmark_repeat.py` e31cef6d5cfd…; `audit/a07_rule_minimal.py` bec2b8cdb1b4… |
| Ambiguous negatives | 25 dockets, list SHA-256 `4931d15a44d5…` |

## Verdict

**No zero-shot Apertus model beats the three-signal rule (no LLM).** The decision metrics were fixed before the run: pooled AUC vs hard negatives and pooled F2 at the transferred threshold. 8B does not beat the rule (both paired 95 % CIs include 0). 70B does not beat the rule (both paired 95 % CIs include 0); on the other primary metrics it is worse than the rule on top-45 F2, top-45 recall, top-60 F2 and top-60 recall. Point estimates: AUC vs hard Rule 0.858, 8B 0.816, 70B 0.822; F2 transferred Rule 0.616, 8B 0.686, 70B 0.543. With 59 positives the intervals are wide: differences of a few points cannot be resolved, so "does not beat" is not "is equal".

## Primary metrics (pooled over both test quarters, 95 % paired bootstrap CI)

| Metric | Rule, 3 signals (no LLM) | Apertus 8B zero-shot | Apertus 70B zero-shot |
|---|---|---|---|
| AUC vs hard negatives (59 pos vs 235 hard) | 0.858 [0.804, 0.914] | 0.816 [0.749, 0.877] | 0.822 [0.764, 0.876] |
| F2 at transferred threshold, full quarter | 0.616 [0.543, 0.749] | 0.686 [0.552, 0.775] | 0.543 [0.418, 0.629] |
| F2 at transferred threshold, after layer 1 | 0.616 [0.543, 0.749] | 0.686 [0.539, 0.775] | 0.588 [0.479, 0.673] |
| F2 of the top-45 list per quarter | 0.706 [0.613, 0.782] | 0.675 [0.567, 0.767] | 0.521 [0.429, 0.629] |
| Recall of the top-45 list per quarter | 0.780 [0.678, 0.864] | 0.746 [0.627, 0.847] | 0.576 [0.475, 0.695] |
| F2 of the top-60 list per quarter | 0.660 [0.590, 0.744] | 0.632 [0.548, 0.716] | 0.562 [0.463, 0.646] |
| Recall of the top-60 list per quarter | 0.797 [0.712, 0.898] | 0.763 [0.661, 0.864] | 0.678 [0.559, 0.780] |

Counts at the transferred threshold (TP / FP, pooled, full quarter): Rule, 3 signals (no LLM) 42 / 63; Apertus 8B zero-shot 42 / 28; Apertus 70B zero-shot 38 / 76.

### Paired differences (a − b; the decision rule needs the CI strictly above 0)

| Metric | 8B − Rule | 70B − Rule | 70B − 8B |
|---|---|---|---|
| AUC vs hard negatives (59 pos vs 235 hard) | -0.041 [-0.083, +0.001] includes 0 | -0.035 [-0.080, +0.010] includes 0 | +0.006 [-0.038, +0.051] includes 0 |
| F2 at transferred threshold, full quarter | +0.070 [-0.074, +0.126] includes 0 | -0.073 [-0.238, +0.008] includes 0 | -0.143 [-0.257, -0.033] **below 0** |
| F2 at transferred threshold, after layer 1 | +0.070 [-0.088, +0.127] includes 0 | -0.028 [-0.168, +0.051] includes 0 | -0.098 [-0.196, +0.016] includes 0 |
| F2 of the top-45 list per quarter | -0.031 [-0.107, +0.015] includes 0 | -0.184 [-0.276, -0.061] **below 0** | -0.153 [-0.230, -0.031] **below 0** |
| Recall of the top-45 list per quarter | -0.034 [-0.119, +0.017] includes 0 | -0.203 [-0.305, -0.068] **below 0** | -0.169 [-0.254, -0.034] **below 0** |
| F2 of the top-60 list per quarter | -0.028 [-0.112, +0.028] includes 0 | -0.098 [-0.211, -0.028] **below 0** | -0.070 [-0.169, +0.000] includes 0 |
| Recall of the top-60 list per quarter | -0.034 [-0.136, +0.034] includes 0 | -0.119 [-0.254, -0.034] **below 0** | -0.085 [-0.203, +0.000] includes 0 |

## Per fold (fold_A = deployment view: trained on 2025Q4, tested on 2026Q1)

| Metric | Rule, 3 signals (no LLM) 2026Q1 | Rule, 3 signals (no LLM) 2025Q4 | Apertus 8B zero-shot 2026Q1 | Apertus 8B zero-shot 2025Q4 | Apertus 70B zero-shot 2026Q1 | Apertus 70B zero-shot 2025Q4 |
|---|---|---|---|---|---|---|
| AUC vs hard | 0.837 [0.752, 0.919] | 0.890 [0.810, 0.948] | 0.788 [0.687, 0.878] | 0.853 [0.758, 0.924] | 0.787 [0.703, 0.866] | 0.871 [0.794, 0.934] |
| F2 transferred, full | 0.604 [0.534, 0.780] | 0.634 [0.437, 0.784] | 0.685 [0.467, 0.794] | 0.688 [0.534, 0.833] | 0.515 [0.352, 0.628] | 0.582 [0.380, 0.723] |
| F2 transferred, L1 | 0.604 [0.534, 0.780] | 0.634 [0.437, 0.784] | 0.685 [0.467, 0.794] | 0.688 [0.534, 0.833] | 0.565 [0.396, 0.679] | 0.614 [0.452, 0.740] |
| F2 top-45 | 0.680 [0.533, 0.799] | 0.732 [0.605, 0.828] | 0.680 [0.518, 0.799] | 0.669 [0.510, 0.796] | 0.473 [0.355, 0.621] | 0.573 [0.414, 0.732] |
| F2 top-60 | 0.625 [0.516, 0.761] | 0.698 [0.610, 0.785] | 0.652 [0.516, 0.761] | 0.610 [0.494, 0.727] | 0.516 [0.380, 0.652] | 0.610 [0.465, 0.727] |
| AUC full quarter (sanity) | 0.989 [0.984, 0.995] | 0.994 [0.990, 0.997] | 0.963 [0.937, 0.986] | 0.978 [0.959, 0.992] | 0.957 [0.929, 0.981] | 0.967 [0.944, 0.985] |

Transferred thresholds (learnt on the other quarter, full / after L1): Rule, 3 signals (no LLM) 2026Q1: 2.0184 / 2.0184; Rule, 3 signals (no LLM) 2025Q4: 3.0093 / 3.0093; Apertus 8B zero-shot 2026Q1: 1 − 3.6e-10 / 1 − 3.6e-10; Apertus 8B zero-shot 2025Q4: 1 − 3.6e-10 / 1 − 3.6e-10; Apertus 70B zero-shot 2026Q1: 0.0372 / 0.0372; Apertus 70B zero-shot 2025Q4: 0.2668 / 0.0032.
fold_B trains on rulings later than its test quarter (soft temporal leak; it does not touch labels).

## Recall by subject and language (pooled)

At the transferred threshold (full quarter), then in the top-60 list per quarter. IT has 1 positive: not measurable.

| Group | Rule, 3 signals (no LLM) @thr | Apertus 8B zero-shot @thr | Apertus 70B zero-shot @thr | Rule, 3 signals (no LLM) top-60 | Apertus 8B zero-shot top-60 | Apertus 70B zero-shot top-60 |
|---|---|---|---|---|---|---|
| UV (43 pos) | 0.930 [0.833, 1.000] | 0.977 [0.829, 1.000] | 0.814 [0.634, 0.923] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 0.837 [0.714, 0.930] |
| IV (16 pos) | 0.125 [0.000, 0.619] | 0.000 [0.000, 0.133] | 0.188 [0.000, 0.400] | 0.250 [0.077, 0.550] | 0.125 [0.000, 0.333] | 0.250 [0.000, 0.467] |
| DE (41 pos) | 0.634 [0.533, 0.846] | 0.659 [0.500, 0.805] | 0.488 [0.348, 0.658] | 0.756 [0.639, 0.897] | 0.707 [0.590, 0.850] | 0.537 [0.385, 0.682] |
| FR (17 pos) | 0.882 [0.667, 1.000] | 0.882 [0.647, 1.000] | 1.000 [0.700, 1.000] | 0.941 [0.786, 1.000] | 0.941 [0.750, 1.000] | 1.000 [0.929, 1.000] |
| IT (1 pos) | 1.000 [0.000, 1.000] | 0.000 [0.000, 0.000] | 1.000 [0.000, 1.000] | 0.000 [0.000, 1.000] | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] |

## Sensitivity: without the 25 ambiguous negatives (audit finding M1)

| Metric | Rule, 3 signals (no LLM) | Apertus 8B zero-shot | Apertus 70B zero-shot | 8B − Rule | 70B − Rule |
|---|---|---|---|---|---|
| AUC vs hard negatives (59 pos vs 235 hard) | 0.900 [0.847, 0.943] | 0.877 [0.810, 0.933] | 0.870 [0.815, 0.914] | -0.023 [-0.069, +0.020] includes 0 | -0.030 [-0.072, +0.015] includes 0 |
| F2 at transferred threshold, full quarter | 0.665 [0.581, 0.813] | 0.742 [0.595, 0.827] | 0.572 [0.446, 0.660] | +0.077 [-0.075, +0.134] includes 0 | -0.092 [-0.258, -0.002] **below 0** |
| F2 at transferred threshold, after layer 1 | 0.665 [0.581, 0.813] | 0.742 [0.570, 0.827] | 0.625 [0.513, 0.716] | +0.077 [-0.089, +0.135] includes 0 | -0.040 [-0.196, +0.054] includes 0 |
| F2 of the top-45 list per quarter | 0.736 [0.644, 0.798] | 0.690 [0.583, 0.782] | 0.583 [0.475, 0.675] | -0.046 [-0.123, +0.031] includes 0 | -0.153 [-0.261, -0.061] **below 0** |

## Repeatability

**8B, 3 full passes.** 3652/3936 rulings have the same score in every pass; max spread 0.0865; 5 rulings differ by more than 0.05. Rulings that cross the first pass's transferred threshold in at least one pass: 0; at 0.5: 2. Primary metrics per pass (the tables above use pass 1):

| Metric | pass 1 | pass 2 | pass 3 |
|---|---|---|---|
| AUC vs hard negatives (59 pos vs 235 hard) | 0.816 | 0.817 | 0.817 |
| F2 at transferred threshold, full quarter | 0.686 | 0.686 | 0.686 |
| F2 at transferred threshold, after layer 1 | 0.686 | 0.686 | 0.686 |
| F2 of the top-45 list per quarter | 0.675 | 0.675 | 0.675 |
| Recall of the top-45 list per quarter | 0.746 | 0.746 | 0.746 |
| F2 of the top-60 list per quarter | 0.632 | 0.632 | 0.632 |
| Recall of the top-60 list per quarter | 0.763 | 0.763 | 0.763 |

100 repetitions of the 70B on the 294 positives + hard negatives. F2 and top-k per repetition use the full pass's scores for the easy negatives (they are not repeated).

| Metric | mean | std | min | max | repetitions ≥ rule |
|---|---|---|---|---|---|
| AUC vs hard negatives (59 pos vs 235 hard) | 0.822 | 0.001 | 0.819 | 0.824 | 0/100 (rule 0.858) |
| F2 at transferred threshold, full quarter | 0.534 | 0.009 | 0.511 | 0.565 | 0/100 (rule 0.616) |
| F2 at transferred threshold, after layer 1 | 0.580 | 0.005 | 0.574 | 0.593 | 0/100 (rule 0.616) |
| F2 of the top-45 list per quarter | 0.517 | 0.010 | 0.491 | 0.537 | 0/100 (rule 0.706) |
| Recall of the top-45 list per quarter | 0.572 | 0.011 | 0.542 | 0.593 | 0/100 (rule 0.780) |
| F2 of the top-60 list per quarter | 0.561 | 0.004 | 0.548 | 0.562 | 0/100 (rule 0.660) |
| Recall of the top-60 list per quarter | 0.677 | 0.005 | 0.661 | 0.678 | 0/100 (rule 0.797) |

Throughput by concurrency: 4 concurrent calls, 1 repetitions: 3.3 calls/s, median latency 1.17 s; 8 concurrent calls, 1 repetitions: 3.2 calls/s, median latency 2.37 s; 12 concurrent calls, 97 repetitions: 34.0 calls/s, median latency 0.14 s; 16 concurrent calls, 1 repetitions: 3.6 calls/s, median latency 4.62 s. Repetitions 1–4 ran during the concurrency ramp, before the full pass; the later ones, sent back to back on the same 294 prompts, were about 10× faster (very likely prefix caching at the gateway), yet no ruling got the same score in every repetition.

Per-ruling score spread (max − min over repetitions): max 0.342, median 0.0000, 95th percentile 0.215; 43 rulings above 0.05, 33 above 0.1, 0 identical in every repetition.
Rulings that cross a threshold in at least one repetition: 7 at 0.5; 7 at the full pass's transferred threshold (0.0372 for 2026Q1, 0.2668 for 2025Q4).
Cost: 29400 calls (29400 live), 97,120,800 prompt tokens, 0.31 h wall time.

## How to read this

- Thresholds are never chosen on the quarter they are measured on; the valid split selects nothing.
- A tie at a top-k cut counts its expected share of positives. Ties at the F2 optimum take the lowest threshold (recall first).
- Full-quarter AUC saturates (easy negatives) and is a sanity check only.
- Labels come from Suva's workbook; Q1/2026 negatives are probably noisy (M1): read the sensitivity table with the main one.
