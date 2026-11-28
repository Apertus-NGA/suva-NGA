# Selection cut — local comparison

Measured Sat 28 Nov 2026, about 03:40 CET. One frozen logistic regression, two ways of cutting its scores: the production adaptive Top-K, and a probability threshold. The production cut is unchanged (`CORE_SHARE = 0.40` in `src/triage/scorer.py`; `src/triage/pipeline.py` was not edited). This note does not settle how relevance is scored (D-021) and does not settle which date defines a quarter (D-050).

Open questions left open, with the "While open" line of `docs/DECISIONS.md`:

- **D-050.** This run splits on the publication date. The decision-date populations of `docs/EVAL.md` §2 stay the protocol. Of the labelled rows in the two windows below, 370 would fall in the other quarter if the split used the decision date. Both dates stay stored.
- **D-021.** The classifier and the production quota stay as they are. The grids below are a comparison, not a new scoring design. The swapped fold of `docs/EVAL.md` §2 (choose on Q1/2026, report on Q4/2025) was not run. Hits at 30 (D-046) were not computed.
- **Q-04.** Closed world, as an assumption: a ruling published in one of the two windows counts as relevant when its basis is `suva_xlsx`, and as not relevant when its basis is `complete_list_negative`. Rows with another basis are outside the counts.
- **D-031.** Per-docket scores, which carry the label, stay in `data/derived/selection_benchmark/scores.json` (git-ignored). `results/` and this note hold aggregates only.

The grid in §3 is copied from `results/selection_benchmark.json` (and the same rows in `results/selection_benchmark.csv`). The chart is `results/selection_benchmark_f2.svg`. The intervals and the hybrid (§4, §5) are copied from `results/selection_benchmark_followup.json`.

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

On the evaluation quarter the point estimates are these. Top-K 0.40 has the highest F2 of the four lines (0.685714). The two parameters chosen on 2025 Q4 do not carry: Top-K 0.60 falls to 0.637255, and the threshold 0.46 falls to 0.644444. The threshold 0.46 misses no relevant ruling on either window. Against Top-K 0.40 on 2026 Q1 it finds 5 more relevant rulings and 45 more false positives (80 against 35), and the list grows from 59 rulings to 109.

The full grids are in `results/selection_benchmark.csv`. The intervals in §4 and the hybrid in §5 were computed afterwards on the same frozen scores. They are in `results/selection_benchmark_followup.json`. Parameters were not chosen again on 2026 Q1.

## 4. Intervals on the evaluation quarter

Wilson 95 % intervals for recall, 29 relevant rulings:

| Cut | Recall | Wilson low | Wilson high |
|---|---|---|---|
| Top-K 0.40 | 24/29 | 0.654512 | 0.924023 |
| Top-K 0.60 | 26/29 | 0.736146 | 0.964186 |
| Threshold 0.46 | 29/29 | 0.883026 | 1.000000 |

The Top-K 0.40 interval and the threshold interval overlap.

Paired bootstrap of the F2 difference, 10,000 draws, seed `20261128`. Each draw resamples the 1,838 evaluation rows with replacement and recomputes both cuts. The parameters stay frozen.

| Difference of F2 | 2.5 % | Median | 97.5 % | Share of draws above 0 |
|---|---|---|---|---|
| Top-K 0.40 minus threshold 0.46 | −0.081057 | 0.043699 | 0.149209 | 0.7626 |
| Top-K 0.60 minus threshold 0.46 | −0.108675 | −0.019481 | 0.058964 | 0.3248 |
| Top-K 0.40 minus `model.threshold` | 0.003668 | 0.092162 | 0.162660 | 0.9779 |

The point-estimate advantage of Top-K 0.40 over the threshold 0.46 (0.041) sits inside an interval that crosses zero. Top-K 0.60 and the threshold 0.46 are not separated either. The one interval that stays positive is Top-K 0.40 against the bar frozen at the fit (`model.threshold` 0.6203008193): that bar selects 102 rulings on this quarter because the scores sit higher than on 2025 Q4. A quota follows the size of the quarter. A bar frozen on the previous quarter does not. The lower end of that interval is 0.004, on 29 relevant rulings and one fold.

## 5. Hybrid, then closed

One further cut was calibrated on 2025 Q4 only: the union of Top-K 0.40 and every kept ruling whose score is at least `t`, with `t` on the same 0.01 grid. The tie-break is the one in §1.

On 2025 Q4 the F2 of that union is flat from `t = 0.22` to `t = 0.46` (19 true positives, 43 false positives, 0 false negatives, 62 selected, F2 0.688406). The higher threshold wins the tie, so `t = 0.46`. The lowest score inside Top-K 0.40 on that quarter is 0.620301, so every ruling the quota keeps is already above 0.46. The union equals the pure threshold. The same equality holds on 2026 Q1, where the lowest Top-K 0.40 score is 0.621067: the union selects the same 109 rulings, with the same 0 false negatives and the same F2 0.644444. Across the 10,000 evaluation resamples the F2 difference against the threshold 0.46 is 0.

The other end of the flat, `t = 0.22`, is the same 62 rulings on 2025 Q4 and a larger pure threshold on 2026 Q1 (115 selected, F2 0.627706, still 0 false negatives). It was not chosen. The value of `t` that would maximise F2 on 2026 Q1 is 1.0, and at that point the union collapses back to Top-K 0.40 (F2 0.685714, 5 false negatives, 59 selected). That value was computed to check it was not used.

The hybrid adds no selection the threshold does not already make. The track stops there. No parameter is retuned on 2026 Q1.

## 6. What is kept

The production cut stays Top-K 0.40. No alternative improved F2 on the evaluation quarter by a margin the bootstrap separates from zero. The classifier is unchanged.

Two reading modes are proposed for the legal-expert UI, and neither is built. **Balanced** is the production quota, Top-K 0.40, 59 rulings on this 2026 Q1 window. **High recall** is the threshold 0.46 chosen on 2025 Q4, 109 rulings on the same window, 0 misses on both labelled windows in this measurement. The default stays Balanced. Switching mode does not rescore.

This comparison does not establish a winning cut (D-021 stays open). It does fix what the two cuts do on these scores: the quota spends recall to keep the reading list shorter; the threshold 0.46 spends 45 false positives to pick up the 5 relevant rulings the quota missed; the hybrid does not sit between them.

Limits, stated with the result. The scores are the structural features alone. A rerun once triage readings sit in the replay cache would fill `consensus` and can move every line. The swapped fold of `docs/EVAL.md` §2 was not run. One evaluation quarter holds 29 relevant rulings, so the intervals are wide. Nothing here is a reason to edit `CORE_SHARE` before that fold exists.

## 7. Where the run lives

The comparison was run locally and the runner is not kept in the tree. The record is `results/selection_benchmark.json`, `results/selection_benchmark.csv`, `results/selection_benchmark_f2.svg` and `results/selection_benchmark_followup.json`, plus the per-docket scores in `data/derived/selection_benchmark/scores.json`. The measurement stamp in the first JSON is git `5bbc2359317b0730cfa7c19e451d89b75be7bd0b`, the commit the scores were computed against.
