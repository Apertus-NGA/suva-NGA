# Update 10 — follow-up: the four open items

## 1. XGBoost (now runs; OpenMP library installed with Homebrew)
| Model | Cross-quarter F2 | Repeated-CV F2 (spread) |
|---|---|---|
| Logistic regression, 6 structural features | 0.759 | 0.768 (0.006) |
| XGBoost depth 2, 6 structural | 0.750 | 0.734 (0.020) |
| XGBoost depth 2, class-weighted, 6 structural | 0.745 | 0.771 (0.001) |
| XGBoost depth 2, 11 structural | 0.763 | 0.738 (0.023) |
| XGBoost depth 3, 300 trees, 11 structural | 0.750 | 0.719 (0.028) |
| XGBoost, 20 structural features | 0.728 | 0.712 |
| XGBoost, 6 structural + Apertus principle | 0.681 | 0.711 |
| XGBoost, 6 structural + 9 Apertus answers | 0.675 | 0.697 |
| XGBoost, all 8C/9C, weighted | 0.752 | 0.755 |
| XGBoost, all 3,936 rulings, weighted | 0.738 | 0.747 |
| XGBoost, all 3,936 rulings, unweighted | 0.615 | 0.686 |

Same accuracy as logistic regression on structural features, worse with more features, no gain from wider training sets. Full table: `out/arm_m_xgboost.csv`, top-share cut-offs: `out/arm_m_xgboost_topshare.csv`.

## 2. Thinking mode for 70B (now really tested)
- The gateway's 70B "thinking" model does not reason on its own on these prompts. Prefilling the assistant turn with `<|inner_prefix|>` forces it.
- Run on all 221: reasoning completed in 204, median about 4,000 characters (about 1,100 tokens).
- Own decision: F2 0.696, recall 0.90, 145 of 221 yes. Tuned on its verdict probability: 0.684 / 0.685.
- Ranking inside accident insurance 0.50, inside disability insurance 0.57 (chance is 0.5).
- Added to six structural features: 0.741 / 0.742, slightly below the structural model alone.
- Conclusion: reasoning does not help; label first with token probabilities remains the best Apertus configuration.

## 3. Embedding models
Both restored and verified to load. BGE-M3 takes 4.4 GB (the loader keeps two copies of the weights), multilingual-e5 1.1 GB. Free disk about 3 GB.

## 4. pyproject.toml
Checked and kept. Lock file in sync; a fresh sync changes nothing. The `default-groups` line keeps the research packages installed when another session syncs.

Notebook rebuilt with the XGBoost table and the new thinking section.
