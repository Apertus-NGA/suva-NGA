# Update 06 — 19:08 — rubric answers, and evidence of a ceiling

## Rubric filling (agent B; full run on 221 done, final report pending)
Nine yes/no questions answered by Apertus 70B from the ruling text, one call each, stored as P(Ja).

| Question | Ranking inside accident insurance | Inside disability insurance |
|---|---|---|
| Court states or refines a rule | 0.67 | 0.71 |
| Decides something new / changes case law | 0.66 | 0.71 |
| Dispute is essentially factual (inverse) | 0.68 | 0.59 |
| Routine case (inverse) | 0.58 | 0.71 |
| Insurer or authority lost | 0.52 | 0.66 |
| Applies to accident insurance | 0.45 | 0.53 |
| Affects insurer practice | 0.61 | 0.57 |
| Worth a newsletter item | 0.66 | 0.61 |

(AUC: 0.5 is chance, 1.0 is perfect.)

- "Applies to accident insurance" and "affects practice" are useless: Apertus says yes to nearly everything (median P(Ja) 0.998 and 1.0).
- The questions about rule versus facts carry real but modest signal.
- Added one by one or all together to the deterministic model, none raises held-out F2 (0.68 to 0.76 against 0.756). More features on 59 positives adds noise faster than signal.

## One composite Apertus feature (mine)
"Principle" = average of (states a rule, decides something new, not factual, not routine). Signs fixed by meaning, not fitted.
- Ranking inside accident insurance 0.66, inside disability insurance 0.72.
- It does not raise the best F2 (0.731 to 0.746 against 0.759).
- It helps at the high-recall end: to reach 90% recall the model needs 114 to 116 submissions instead of 134 to 136 (cross-quarter), and 131 instead of 177 (repeated CV). At that point F2 is about 0.76 with recall 0.90, instead of 0.76 with recall 0.83.

## Diagnostic: is there more signal to find?
Two blind expert-reader agents (a stronger model than Apertus, development-time only) each studied one labelled quarter (metadata plus lesson statement per ruling) and scored the other quarter.
- Ranking inside accident insurance: 0.57. Inside disability insurance: 0.70.
- Best F2 even with the ideal cut-off chosen after the fact: 0.737.
- Both readers reported the same thing: the area dominates, and near-identical rulings carry opposite labels.

So a stronger reader with the same information does no better than logistic regression on 11 features (0.756). The remaining choices inside an area look largely unpredictable from the ruling itself. F2 of about 0.76 to 0.78 appears to be the ceiling for this label set. Caveat: the readers saw Apertus-written lesson statements, not the full rulings.

## Consequence for the last part of the sprint
Stop searching for new feature families. Use the remaining time on:
1. The operating point. Recall is scored first, so compare "best F2" (about 88 of 221 submitted, recall 0.83) with recall-first cut-offs (0.90 and 0.95).
2. The 0 to 100 score with per-rule points.
3. Q2 predictions with the chosen models.
4. The notebook.

Still due: final reports from agents A and B (about 19:25). Iteration ends 20:00.
