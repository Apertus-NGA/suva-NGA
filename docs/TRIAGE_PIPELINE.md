# Triage pipeline v1: from a ruling to its tier and score

> **Status: PROPOSED (D-061), running as the MVP since Sat 28 Nov 2026.** Code: `src/triage/pipeline.py` (runner), `readings.py`, `reading_prompts.py`, `scorer.py`; layer 1 is `src/courts.py` (D-060, `docs/LAYER1.md`); the facts are `src/signals/structural.py` (`docs/TRIAGE_SIGNALS.md`). Tests: `tests/test_triage_pipeline.py`. Run: `make triage` (dry run from cached answers), `make triage MODE=live WRITE=1`.

## 1. Open questions this touches

| Question | What v1 does | Why | Still open |
|---|---|---|---|
| D-021 point 1: Apertus alone or a learned combination? | Learned combination (option B): logistic regression over code-read facts and an Apertus consensus | Measured: Apertus alone reached F2 0.67 to 0.73 out of quarter, the combination 0.77 (section 4) | The Apertus share of the score is modest; whether that satisfies "Apertus performs the core task" (E1) is for the lead to ask |
| D-021 point 2: a net? | Layer 1 of D-060, unchanged | Keeps every listed ruling | D-060 itself is PROPOSED |
| D-021 point 4: where does Apertus's score come from? | First-token log-probabilities, never a number the model writes | A written number was only ever 0, 10, 85, 90 or 95 in our tests | Falls back to nothing if the judges' endpoint has no `top_logprobs`: the readings would be empty and the score would rest on the facts |
| D-021 point 5: the threshold | No score threshold: in each decision quarter the highest-scored kept rulings are promoted, as many as 40% of that quarter's accident, military and disability rulings | A threshold chosen on one quarter transferred badly to the other (submitted 45 against 79); a fixed share did not | The 40% was chosen among 28% to 60% after seeing results: optimistic. Report hits at 30 next to it (D-046): not done |
| D-021 point 7: a ruling Apertus did not read | Scored from the facts with a neutral consensus; a ruling layer 1 drops has no prediction | A failed call is never a negative | Dropped rulings show as "not assessed" in the UI, not with a score and a reason (G5 asks for both) |
| D-050: which date defines a quarter | Decision date | Suva's list follows it | Open |
| D-031 | Only aggregates here and in `results/triage_pipeline.json` | | Open |

## 2. The steps

```
every ruling in the database
   │
   ▼  1. LAYER 1 (src/courts.py, D-060)                              code, Apertus where code cannot read the matter
   │     kept: accident, military, disability, health insurance, pensions (courts 8, 9),
   │           contract and liability (court 4), or a text naming Suva / accident insurance
   ▼
kept rulings ────────────────────────────────► not kept: no prediction ("not assessed")
   │
   ▼  2. FACTS (src/signals/structural.py)                           code
   │     area · single judge · five judges · appeal by an insurer or authority ·
   │     Suva is a party · manifestly unfounded · publication mark
   ▼
   ├─ core rulings: accident, military or disability insurance, more than one judge
   │     ▼  3. SIX APERTUS READINGS (src/triage/readings.py)         Apertus 70B, one token each
   │        verdict · strict yes/no · four five-level scales
   │        log-probabilities → standardised → averaged = consensus
   ├─ other kept rulings: no reading, consensus 0 (the average)
   ▼
   ▼  4. SCORE (src/triage/scorer.py)                                logistic regression
   │     nine inputs: the facts and the consensus; trained on the kept rulings of Q4/2025 and Q1/2026
   ▼
   ▼  5. CUT                                                         fixed rule
   │     per decision quarter: top rulings by score, as many as 40% of the quarter's core-area rulings
   ▼
suspected relevant (predictions.relevant = true)      possibly relevant (false)
```

**The six readings.** Each sends the ruling first (header, facts up to 1,500 characters, reasoning up to 20,000 with the cut marked, operative part) and the question last, and reads one token.

| Reading | Prompt version | Asks | Value |
|---|---|---|---|
| `verdict` | `e1_nofacts` | would the legal department include this ruling (rubric with base rates) | P(Ja) |
| `yes_strict` | `e13_yes_strict_v1` | does the court make its own reusable legal statement, with a list of what does not count | P(Ja) |
| `scale_generic` | `e13_scale_generic_v1` | how much does the ruling teach beyond the case, 1 to 5 | expected level |
| `scale_area` | `e13_scale_area_v1` | the same, worded for the ruling's area with its base rate | expected level |
| `scale_headnote` | `e13_scale_headnote_v1` | how substantial would a headnote be, 1 to 5 | expected level |
| `scale_tail` | `e13_scale_tail_v1` | the generic scale on the later 65% of the reasoning | expected level |

The consensus standardises each reading over the core rulings (no labels) and averages them with equal weights. A reading that says the same for every ruling is left out automatically. The prompt versions keep their development names so that cached answers stay valid.

## 3. What is stored for the UI

One `model_runs` row per run and one current `predictions` row per kept ruling: `score` (0 to 1), `relevant` (suspected relevant or not), `explanation` (one German sentence built by code from the rules that apply), and `details` (tier, the layer-1 row, the facts, the six readings, the consensus, each rule's contribution). Earlier predictions are kept and marked not current. `src/suva_app/queries.py` turns this into the statuses `ai_relevant`, `potentially_relevant` and `not_assessed`.

## 4. Measurements

Ours, from `results/triage_pipeline.json`, run of Sat 28 Nov 2026 on the data-layer database (6,234 rulings). Labels: Suva's list for Q4/2025 and Q1/2026, every other ruling of those quarters counted as not relevant (closed world, Q-04). Aggregates only (D-031).

| | Count |
|---|---|
| Rulings | 6,234 |
| Kept by layer 1 | 1,115 |
| Core rulings read by Apertus (six readings each, none failed) | 391 |
| Training rulings (kept, listed quarters) / relevant among them | 643 / 59 |
| Listed rulings not kept by layer 1 | 0 |

**Out of quarter** (fit on one listed quarter; on the other, apply the cut; both folds pooled):

| Submitted | Relevant found | Recall | Precision | F2 |
|---|---|---|---|---|
| 120 | 55 of 59 | 0.932 | 0.458 | 0.772 |

Per fold: tested on Q1/2026, 66 submitted, 28 of 31 found; tested on Q4/2025, 54 submitted, 27 of 28 found.

**What was stored** (suspected relevant / kept, by decision quarter): Q3/2025 9 / 23; Q4/2025 54 / 295; Q1/2026 66 / 348; **Q2/2026 76 / 416**; Q3/2026 0 / 2; Q4/2026 6 / 31.

Earlier exploratory runs on a narrower candidate set (not reproduced by this command) put the same design at recall 0.91 and F2 0.75 under repeated cross-validation, and the facts alone at recall 0.88 and F2 0.73 for the same number submitted.

## 5. Limits

- 59 relevant rulings: one more or less moves recall by 0.017 and F2 by about 0.015; a 95% interval on F2 is roughly ±0.08.
- The Apertus consensus adds about two to four found rulings at this list size; a paired bootstrap put the chance that the gain is real at 94%, and it shrinks under stronger regularisation. It does not help a list shorter than about 90 rulings.
- The design, the 40% share and the prompts were developed on the same two quarters. Q1/2026 was held back while the prompts were written on Q4/2025, but both quarters shaped the features.
- Scores of the listed quarters' rulings come from a model that saw them. Only Q2/2026 and later are true predictions.
- Health insurance, pensions, contract and liability rulings are kept by layer 1 but not read by Apertus in v1; none is on Suva's list, so the model ranks them low from the area alone.
- The publication star is unknown where the court's list was not seen and is treated as "no".
- `make run` does not call this yet; `make triage` does.

## 6. Not done

- Hits at 30 and the must-hit subset (D-046, `docs/EVAL.md` §2).
- A score and a reason for rulings layer 1 drops.
- `make refit` with expert corrections: the labels read are Suva's list only.
- A second repetition outside the replay cache (G10).
- End-to-end by hand on three real rulings was done on the listed quarters during development (German, French, Italian), not repeated on this branch.
