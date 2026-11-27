# Update 02 — 18:36 — classical models on deterministic features

Agents A (70B alone), B (rubric filling) and C (embeddings) are running. This update is my own arm.

## Tested
8 model types, 5 feature sets, 4 training scopes, drop-one / add-one ablation, and a TF-IDF text baseline. Full table: `out/arm_d_results.csv`, ablation: `out/arm_d_ablation.csv`, weights: `out/arm_d_weights.csv`.

## Scores (held-out; cross-quarter F2 / repeated-CV F2)
| Method | Cross-quarter | Repeated CV |
|---|---|---|
| Logistic regression, 11 features, candidates | 0.756 | 0.766 |
| Gradient boosting (shallow) | 0.741 | 0.750 |
| Random forest | 0.740 | 0.740 |
| Gradient boosting (deeper) | 0.671 | 0.686 |
| Original Suva rubric as features | 0.708 | 0.729 |
| 11 features + 9 extras | 0.677 | 0.719 |
| TF-IDF of the reasoning text | 0.671 | 0.677 |
| Trained on all 8C/9C | 0.679 | 0.742 |
| Trained on all 3,936 rulings | 0.743 | 0.740 |

## Learned
- Logistic regression beats tree models here and is far more stable (spread 0.005 vs 0.02 to 0.03).
- More features hurt: adding the 9 extras or interactions lowers the score.
- Training on gated candidates is best in both protocols. Wider scopes are not better.
- One feature carries most of the gain: "appeal brought by an insurer or authority" (removing it costs 0.05 to 0.08 F2). Dropping any other single feature changes little.
- Raw text with TF-IDF is worse than 11 hand-made features, so the signal is not in word frequencies.
- Deterministic features plateau at recall about 0.83. The misses are disability-insurance rulings with no structural signal. That is the gap Apertus and embeddings must close.
- The threshold is fragile: the same model scores 0.69 or 0.76 depending on where the cut lands. I am adding a recall-first threshold policy to the comparison, since the challenge scores recall first.

## Next
- Combine agent outputs with these features as they arrive (about 19:25).
- Compare threshold policies: best-F2 vs "keep at least 95% of training positives".
- Planned end of iteration: 20:00, then notebook until 20:26.
