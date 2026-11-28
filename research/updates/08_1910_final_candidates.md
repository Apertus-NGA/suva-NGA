# Update 08 — final candidates, more Apertus questions, uncertainty

## Agent B final report (rubric filling)
- No rubric question improves the filter; deterministic features alone stay best.
- Label-first with token probability separates better than rationale-first and is about 9 times faster.
- 8B agrees with 70B on 88 to 95% of answers for five questions, but only about 50% on "transfer", "rule" and "practice".
- Asking the questions on the short lesson statement instead of the ruling loses signal (inside disability insurance 0.59 against 0.71 for "rule").
- Apertus says yes to 90 to 100% on "applies to accident insurance", "affects practice" and "worth a newsletter".
- Hand check of 36 answers: about 78% defensible, errors lean towards yes.
- Lesson statements: on 8 rulings with a Suva summary, 6 hit Suva's point and 2 picked a different issue.

## More Apertus questions (mine)
Seven additional rule-versus-routine questions, plus a forced-choice category question (six categories, to avoid yes-bias).
- Best new single question: "would an experienced accident-insurance lawyer learn something new" (0.64 inside accident insurance, 0.75 inside disability insurance).
- Averaging all eleven answers is no better than averaging four (0.63 / 0.69 against 0.66 / 0.72). The signal saturates at about 0.7.
- The category question is similar (0.68 / 0.63). Apertus put 148 of 221 rulings in "reviews the medical evidence and confirms".

## Final candidates (held-out; cross-quarter / repeated CV, best-F2 cut-off)
| Model | F2 | Recall | Submitted |
|---|---|---|---|
| A. Structural 6 | 0.759 / 0.768 | 0.83 / 0.84 | 87 / 85 |
| B. Structural 11 | 0.756 / 0.766 | 0.83 / 0.84 | 88 / 86 |
| C. Structural 6 + principle (4 Apertus answers) | 0.731 / 0.747 | 0.86 / 0.83 | 113 / 93 |
| D. Structural 6 + principle (11 Apertus answers) | 0.752 / 0.754 | 0.86 / 0.83 | 103 / 90 |
| 70B alone, best prompt | 0.732 / 0.723 | 0.88 / 0.87 | 119 |

## Uncertainty
- Bootstrap 95% interval for model A's held-out F2: 0.69 to 0.85. One ruling more or less found moves F2 by about 0.015.
- Every method tested lands between 0.70 and 0.78, so the differences between them are inside the noise. The safe reading: nothing beats six structural features, and nothing is reliably worse than them except the plain 70B prompt and raw embeddings.
- At the best-F2 cut-off, model A misses 9 picks, all disability insurance, and its 37 false alarms are 25 accident-insurance and 12 disability-insurance rulings.

## Q2/2026 (129 candidates, 34 decided in June)
| Cut-off | Submitted (A) | Submitted (C) |
|---|---|---|
| Best F2 | 53 | 77 |
| Recall first (keeps all training picks) | 113 | 113 |

Files: `out/q2_predictions_A.csv`, `out/q2_predictions_C.csv`, `out/q2_predictions_D.csv`, points per rule in `out/arm_i_points_*.csv`.
Top June rulings are the same under all three models: 8C_365/2025, 8C_254/2025, 8C_184/2026, 8C_63/2026, 8C_343/2025, 8C_17/2026.

## Other
- Thinking mode: found the cause of "no reasoning". It only activates when no custom system message is sent. A full thinking run of the best prompt on all 221 is in progress.
- xgboost still cannot load (needs `brew install libomp`); scikit-learn gradient boosting stood in for it.

## Plan
- Notebook next (`notebooks/02_relevance_research.ipynb`), then a final update with the thinking result. Sprint ends 20:26.
