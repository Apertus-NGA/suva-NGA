# Selection cut — local comparison

Measured Sat 28 Nov 2026, about 03:40 CET. One frozen logistic regression, two ways of cutting its scores: the production adaptive Top-K, and a probability threshold. The production cut is unchanged (`CORE_SHARE = 0.40` in `src/triage/scorer.py`; `src/triage/pipeline.py` was not edited). This note does not settle how relevance is scored (D-021) and does not settle which date defines a quarter (D-050).

Open questions left open, with the "While open" line of `docs/DECISIONS.md`:

- **D-050.** This run splits on the publication date. The decision-date populations of `docs/EVAL.md` §2 stay the protocol. Of the labelled rows in the two windows below, 370 would fall in the other quarter if the split used the decision date. Both dates stay stored.
- **D-021.** The classifier and the production quota stay as they are. The grids below are a comparison, not a new scoring design. The swapped fold of `docs/EVAL.md` §2 (choose on Q1/2026, report on Q4/2025) was not run. Hits at 30 (D-046) were not computed.
- **Q-04.** Closed world, as an assumption: a ruling published in one of the two windows counts as relevant when its basis is `suva_xlsx`, and as not relevant when its basis is `complete_list_negative`. Rows with another basis are outside the counts.
- **D-031.** Per-docket scores, which carry the label, stay in `data/derived/selection_benchmark/scores.json` (git-ignored). `results/` and this note hold aggregates only.

Numbers below are copied from `results/selection_benchmark.json` (and the same rows in `results/selection_benchmark.csv`). The chart is `results/selection_benchmark_f2.svg`.

## 1. What was compared

The score is the existing logistic regression in `src/triage/scorer.py` (`scorer@1`): `C = 1.0`, `class_weight = "balanced"`, `max_iter = 3000`, features `area_uvmv`, `area_iv`, `appeal_by_institution`, `five_judges`, `publication`, `manifestly_unfounded`, `suva_party`, `single_judge`, `consensus`. It is fit once, on the rulings kept by layer 1 and published in 2025 Q4 (229 rows, 19 relevant, 105 in the core areas UV, MV and IV). Probabilities on that quarter are out of fold. Probabilities on 2026 Q1 are `predict_proba` of that frozen fit. The grids do not fit again.

`consensus` is 0 on every row. The replay cache has no triage readings, so no Apertus feature entered the score. The run made no gateway call.

Two cuts, on the same scores:

- **Adaptive Top-K.** Among the kept rulings of the quarter that sit in the core areas, keep the `n` highest scores, with `n = max(1, round(quota × n_core))`. The production quota is 0.40. The grid is 0.20 to 0.80, step 0.05.
- **Probability threshold.** Keep every kept ruling whose score is at least `t`. The grid is 0.00 to 1.00, step 0.01, plus the frozen `model.threshold`. That value is the production rule applied to the out-of-fold scores of the fit: the score at which `CORE_SHARE` of the core training rows are promoted. Here it is 0.6203008193.

A relevant ruling dropped by layer 1 counts as a false negative and is never selected. In this cache that count is 0 on both windows. F2 is `5×TP / (5×TP + 4×FN + FP)`, the same formula as `src/triage/pipeline.py`.

The parameter of each grid is the one with the highest F2 on 2025 Q4. Ties break toward higher recall, then higher precision, then fewer selected rulings, then the smaller quota or the higher threshold. That parameter is applied unchanged to 2026 Q1. A number measured on 2025 Q4, the quarter that chose it, is optimistic.

## 2. Populations

Publication date. Labelled rows only (Q-04, as above).

| Window | Role | Labelled rulings | Relevant | Kept by layer 1 | Core among kept |
|---|---|---|---|---|---|
| 2025 Q4 | calibration, and the fit | 1,560 | 19 | 229 | 105 |
| 2026 Q1 | evaluation; labels never enter the fit | 1,838 | 29 | 307 | 147 |

These relevant counts are the publication-date reading. They are not the 28 and 31 Federal Court positives of the decision-date folds in `docs/EVAL.md` §2.

## 3. Results

| Cut | Quarter | TP | FP | FN | Precision | Recall | F2 | Selected |
|---|---|---|---|---|---|---|---|---|
| Top-K 0.40 (production) | 2025 Q4 | 12 | 30 | 7 | 0.285714 | 0.631579 | 0.508475 | 42 |
| Top-K 0.40 (production) | 2026 Q1 | 24 | 35 | 5 | 0.406780 | 0.827586 | 0.685714 | 59 |
| Top-K 0.60 (best F2 on 2025 Q4) | 2025 Q4 | 19 | 44 | 0 | 0.301587 | 1.000000 | 0.683453 | 63 |
| Top-K 0.60 (best F2 on 2025 Q4) | 2026 Q1 | 26 | 62 | 3 | 0.295455 | 0.896552 | 0.637255 | 88 |
| Threshold 0.46 (best F2 on 2025 Q4) | 2025 Q4 | 19 | 43 | 0 | 0.306452 | 1.000000 | 0.688406 | 62 |
| Threshold 0.46 (best F2 on 2025 Q4) | 2026 Q1 | 29 | 80 | 0 | 0.266055 | 1.000000 | 0.644444 | 109 |
| `model.threshold` 0.6203008193 | 2025 Q4 | 12 | 30 | 7 | 0.285714 | 0.631579 | 0.508475 | 42 |
| `model.threshold` 0.6203008193 | 2026 Q1 | 26 | 76 | 3 | 0.254902 | 0.896552 | 0.596330 | 102 |

Checks on the counts: `round(0.40 × 105) = 42`, `round(0.60 × 105) = 63`, `round(0.40 × 147) = 59`, `round(0.60 × 147) = 88`. On the calibration quarter, `model.threshold` selects the same 42 rulings as Top-K 0.40. On the evaluation quarter the same frozen bar selects 102, because the scores sit higher.

On the evaluation quarter, Top-K 0.40 has the highest F2 of the four lines (0.685714). The two parameters chosen on 2025 Q4 do not carry: Top-K 0.60 falls to 0.637255, and the threshold 0.46 falls to 0.644444. The threshold 0.46 misses no relevant ruling on either window and selects 109 rulings on 2026 Q1, against 59 for the production quota. Five extra true positives do not offset 45 extra false positives in F2.

The full grids are in `results/selection_benchmark.csv`.

## 4. What this leaves in place

Keep the production cut at Top-K 0.40. Use the threshold 0.46 only if missing no relevant ruling matters more than F2: the list to read on a quarter the size of this 2026 Q1 window is 109 rulings instead of 59.

Limit of the scores: they are the structural features alone. A rerun once triage readings sit in the replay cache would fill `consensus` and can move every line in the table. The swapped fold is still to run before any change to `CORE_SHARE`.

## 5. Where the run lives

The comparison was run locally and the runner is not kept in the tree. The record is the three files under `results/` named above, plus the per-docket scores in `data/derived/selection_benchmark/scores.json`. The measurement stamp in the JSON is git `5bbc2359317b0730cfa7c19e451d89b75be7bd0b`, the commit the scores were computed against.
