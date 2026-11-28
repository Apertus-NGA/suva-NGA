# Update 09 — final summary of the sprint

Sprint ran 18:26 to about 19:15, well inside the two-hour box. I stopped because the remaining ideas were tested and the ceiling diagnostic says more searching will not pay off on this label set.

## Last experiments
| Test | Result |
|---|---|
| 70B thinking model, best prompt, all 221 | F2 0.687, recall 0.85; ranking at chance inside both areas. The 70B model wrote no separate reasoning block (about 130 tokens per ruling). No gain. |
| Tuning-free cut-off: submit the top share of candidates by score | Top 40%: all models equal (recall 0.81 to 0.83, F2 0.74 to 0.76). Top 60%: models with the Apertus principle feature reach recall 0.92 to 0.95 at F2 0.74 to 0.76, against 0.89 to 0.90 at 0.72 without. Top 90%: recall 0.98 to 1.00, F2 0.67 to 0.68. |
| Adding the 21 Q3 summarised rulings as extra positive training examples | No change. |
| Cited law articles as features | No usable signal (too few rulings per article). |

## Answers to the questions asked
1. **Can the 70B model do the task itself with a good prompt?** No: F2 0.72 to 0.73 against 0.76 for six structural features. It says yes too often and does not rank inside an area.
2. **All samples or only gated ones for training?** Gated candidates (221). Training on all 3,936 or on all of 8C/9C is no better.
3. **What prompts work on Apertus?** Rubric with base rates, document first and question last, label first, score read from the token probability of "Ja". Rationale-first, examples, analogies and the plain prompt are all worse.
4. **What to embed?** Nothing, for classification. For product features, BGE-M3 on chunks of the core reasoning.
5. **Which features are best?** Appeal brought by an insurer or authority, area, five judges, publication, manifestly unfounded, Suva as party.
6. **Which need a model?** Only "does the court state a rule or just review evidence", asked as four yes/no questions to Apertus and averaged. Everything else is reliably parsed by code.
7. **Which classical model?** Logistic regression. Tree models are less stable; xgboost itself could not be loaded here.

## Recommended pipeline
Gates (code) -> six structural features (code) -> four Apertus rule-versus-routine answers averaged into one "principle" value -> logistic regression trained on gated candidates -> points score 0 to 100 -> submit the top 60% of candidates (77 of 129 in Q2).
Expected on new data, judging from held-out results: recall about 0.92 to 0.95, F2 about 0.74 to 0.76, with an uncertainty of roughly ±0.08.

## Deliverables
- Notebook: `notebooks/02_relevance_research.ipynb` (executed, 40 cells, two charts).
- Q2 scored lists: `research/out/q2_predictions_A.csv`, `_C.csv`, `_D.csv`.
- Points per rule: `research/out/arm_i_points_C.csv`. Labelled out-of-fold scores: `research/out/labelled_scores_C.csv`.
- Agent reports: `research/out/arm_a_report.md`, `arm_b_report.md`, `arm_c_report.md`.
- All Apertus answers cached: `research/cache/apertus.sqlite` (about 11,200 calls).
- Lesson statements for 373 rulings: `research/out/lessons.parquet`.

## Changes outside `research/` and `notebooks/`
- `pyproject.toml` and `uv.lock`: `research` dependency group added and made a default group.
- `.env` created earlier with the gateway settings (git-ignored).
- Nothing in `src/` was touched; nothing committed.
- The two embedding models were deleted from the Hugging Face cache to free 3.4 GB.
