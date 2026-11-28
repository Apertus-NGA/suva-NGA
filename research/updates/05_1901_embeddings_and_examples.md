# Update 05 — 19:03 — embeddings (final) and learning from examples

## Embeddings: negative result (agent C, finished)
Two models (BGE-M3, multilingual-e5-large-instruct), six parts (subject line, facts, reasoning, core reasoning, reasoning chunks, Apertus lesson statement), three feature families plus PCA and kNN. Full table: `out/arm_c_results.csv`, report: `out/arm_c_report.md`.

| Added to deterministic features | Cross-quarter F2 | Repeated-CV F2 |
|---|---|---|
| Nothing (baseline) | 0.756 | 0.766 |
| Best cross-quarter result (e5, core reasoning) | 0.772 | 0.717 |
| Best repeated-CV result (BGE-M3, facts) | 0.742 | 0.768 |
| Apertus lesson statement, either model | 0.69 to 0.76 | 0.73 to 0.76 |

- No combination beats the baseline on both protocols; the two "bests" are one ruling of noise each.
- The embeddings work as embeddings: a ruling finds its own Suva summary first among 55 in 75% of cases. But similar topic does not mean "picked".
- Inside accident insurance and inside disability insurance, embedding features rank at chance level (0.2 to 0.64, where 0.5 is chance). Overall they only rediscover the area, which a flag already gives.
- Recommendation from this arm: no embedding features in the classifier. BGE-M3 on core reasoning remains the choice if embeddings are needed for something else, such as finding similar summarised rulings.

## Learning from examples in the prompt: negative result (mine)
Apertus 70B saw lesson statements of picked and non-picked rulings from the other quarter, then judged a new one.
- It answered yes with probability near 1.0 for almost everything.
- Ranking was worse than chance inside accident insurance (0.27) and near chance inside disability insurance (0.42).
- Alone: cross-quarter F2 0.596.
- Likely cause: every lesson statement ends by explaining why the point matters for accident insurance, which makes every ruling look relevant.

## Housekeeping
- Another session's install removed the research packages at 18:42; fixed by making them default groups in `pyproject.toml`.
- Disk dropped to 1.4 GB free. I deleted the two embedding models this sprint downloaded (3.4 GB); they can be downloaded again.

## Emerging picture
Nothing so far ranks rulings inside an area better than the structural features: not the 70B model, not embeddings, not examples. Either the remaining signal needs better questions (agent B, due about 19:20) or the picks inside an area are close to arbitrary.

## Next
- Diagnostic: two blind expert-reader agents predict one quarter from the other using only the cards. This shows whether learnable signal exists at all beyond the structural features. Development-time only, not part of the pipeline.
- Combine agent B's rubric answers.
- Iteration ends 20:00; notebook 20:00 to 20:26.
