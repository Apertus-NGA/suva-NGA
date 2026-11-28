# Update 01 — 18:30 — setup and baselines

Time box: 18:26 to 20:26.

## Done
- Dependencies added in a `research` group: scikit-learn, xgboost, sentence-transformers.
- `research/common.py`: one dataset for all experiments (6,055 rulings, sections split into header / facts / reasoning / ruling), deterministic features, gates, and one evaluation function everyone uses.
- `research/apertus.py`: cached, threaded client for the gateway. Every answer is stored in `research/cache/apertus.sqlite`.
- Prompt research finished (see `out/prompt_research.md`).

## Evaluation protocol (same for every experiment)
- Cross-quarter: train on Q4/2025, test on Q1/2026, then swap; counts pooled over both.
- Repeated 5-fold cross-validation over both labelled quarters (5 repeats).
- The decision threshold is chosen for F2 on out-of-fold training scores, never on test data.
- A relevant ruling outside the scored set counts as a miss.

## Scores so far (held-out)
| Method | Cross-quarter F2 | Recall | Precision | Submitted | Repeated-CV F2 |
|---|---|---|---|---|---|
| Submit every candidate (221) | 0.646 | 1.00 | 0.27 | 221 | n/a |
| Submit every full accident/military ruling | 0.703 | 0.73 | 0.61 | 70 | n/a |
| Logistic regression, 11 deterministic features, trained on candidates | 0.756 | 0.83 | 0.56 | 88 | 0.766 |
| Same, trained on all of 8C/9C | 0.679 | 0.90 | 0.34 | 154 | 0.742 |
| Same, trained on all 3,936 rulings | 0.743 | 0.81 | 0.55 | 87 | 0.740 |

## Learned
- Training on the gated candidates is best or tied in both protocols.
- xgboost cannot load on this Mac (needs `brew install libomp`). Using scikit-learn's gradient boosting as the tree model instead.
- Disk has 11 GB free, so embedding models are limited to two large ones.

## Next (three agents in parallel, about 50 minutes)
- A: can the 70B model decide alone, with different prompt styles.
- B: Apertus writes the lesson statement and answers rubric questions; 8B vs 70B.
- C: embeddings of different parts of the ruling with two models.
- Me: feature selection and model comparison on deterministic features, then combining everything.
