# Update 07 — operating points: best F2 versus recall first

(Clock note: earlier update file names ran a few minutes ahead of the system clock. Sprint started 18:26 and is on schedule.)

## Agent A final report (70B alone)
Ten prompt variants on all 221. Best: strict rubric with base rates, label first, score from token probability: F2 0.732 cross-quarter, 0.723 repeated CV. Baseline 0.756 / 0.766.
- A rubric with base rates in the prompt is essential; the plain prompt says yes to 215 of 221.
- Label-first with token probability ranks better than rationale-first. Rationale variants only ever output scores 0, 10, 85, 90 or 95.
- Suva summaries as examples did not help. 8B is close to 70B.
- Sending the full text instead of header + reasoning + ruling was worse in the pilot (0.56 against 0.71).
- The thinking model returned no reasoning through the gateway, so thinking mode is effectively untested.
- Typical errors: calls every routine confirmation a "clarification"; rejects disability rulings Suva picked as "not transferable".

## Honest operating points (cut-off chosen on training folds only)
| Model | Cut-off policy | F2 | Recall | Submitted of 221 | Recall + F2 |
|---|---|---|---|---|---|
| Structural 6 features | best F2 | 0.759 / 0.768 | 0.83 / 0.84 | 87 / 85 | 1.59 / 1.61 |
| Structural 6 features | keep 90% of training picks | 0.688 / 0.704 | 0.90 / 0.93 | 149 / 152 | 1.59 / 1.63 |
| Structural 6 features | keep 95% or 100% | 0.681 / 0.681 | 1.00 / 1.00 | 197 / 197 | 1.68 / 1.68 |
| Structural 6 + Apertus "principle" | best F2 | 0.731 / 0.747 | 0.86 / 0.83 | 113 / 93 | 1.60 / 1.58 |
| Structural 6 + Apertus "principle" | keep 95% | 0.671 / 0.695 | 0.98 / 0.98 | 196 / 179 | 1.65 / 1.68 |
| Submit all candidates | none | 0.646 | 1.00 | 221 | 1.65 |

(cross-quarter / repeated CV)

## Learned
- Six structural features do as well as eleven: area, appeal by insurer or authority, five judges, publication, manifestly unfounded, Suva as party.
- If recall and F2 count equally, the recall-first cut-off wins (1.68 against 1.59 to 1.61). At that point the model keeps 197 of 221 and loses no relevant ruling in either protocol.
- At that cut-off the model is equivalent to a simple rule: submit every candidate except disability-insurance rulings dismissed as manifestly unfounded (24 rulings, none relevant).
- Between those two points the trade-off is steep: going from recall 0.83 to 0.90 costs about 60 extra submissions with structural features, about 30 with the Apertus "principle" feature added.
- For Q2 (129 candidates): the best-F2 cut-off would submit about 77, the recall-first cut-off about 113.

## Points score (first version)
Rules and points on a 0 to 100 scale for "structural 6 + principle": accident or military area +25, appeal by insurer or authority +18, five judges +16, Suva party +14, publication +8, Apertus principle up to +7, manifestly unfounded -13, base 13. The scale is compressed (cut-off near 17), so the notebook will show a calibrated percentage next to the points.

## In flight
- Seven more rule-versus-routine questions on Apertus (400 of 1,547 answers), to test whether averaging eleven answers makes a stronger "principle" feature and allows trimming more at full recall.
- Agent B final report.

## Plan
- 19:25 evaluate the 11-answer composite; 19:35 freeze candidates; notebook by 20:15; final update and summary by 20:26.
