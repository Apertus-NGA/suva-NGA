# Triage structural signals

> **Status: PROPOSED (27 Nov 2026).** Code: `src/signals/structural.py`, tests: `tests/test_structural_signals.py`.
> First chunk of the relevance scorer (D-021, option B: a learned combination of code signals and Apertus answers). It settles nothing: the signals are plain functions that any scoring design can read. They apply to rulings kept by the outer gate (`docs/TRIAGE_OUTER_GATE.md`).

## 1. What is read, and from where

No model is involved. Every signal carries the field or the text span it was read from (`Evidence`).

| Signal | Value | Read from |
|---|---|---|
| `area` | UV, MV, IV or other | the court's list, else the header subject line (same reader as the outer gate) |
| `bench_size` | number of judges | the bench block of the header (`Besetzung` / `Composition` / `Composizione`) |
| `single_judge` | yes / no | bench size is 1 |
| `five_judges` | yes / no | bench size is 5 or more |
| `appeal_by_institution` | yes / no | the parties block: the appellant is an insurer, an authority or a company, not an anonymised person |
| `suva_appellant` | yes / no | the appellant names Suva, CNA or INSAI |
| `suva_party` | yes / no | Suva, CNA or INSAI is named in the header |
| `manifestly_unfounded` | yes / no | the standard phrases in three languages, or Art. 109 para. 2 BGG, anywhere in the text |
| `proposed_for_publication` | yes / no / unknown | the star of the court's list; **unknown** when the list was not seen, never "no" |

A signal that cannot be read is absent, not guessed: a ruling without a bench block has no `bench_size`.

## 2. Measurements

Ours, measured on 27 Nov 2026 on the team's data-layer database, quarters by decision date, on the rulings the outer gate keeps. "Picked" means on Suva's list (`judgements/BG_Urteile_2025_Q4_2026_Q1.xlsx`); other rulings of the two listed quarters count as not picked (closed world, Q-04). Aggregates only (D-031).

**Coverage.** Bench size and the appellant were read for all 300 gated rulings of Q4/2025 + Q1/2026 and all 189 of Q2/2026. The publication star is unknown for 37 of the 189 gated Q2/2026 rulings.

**How often each signal fires, and how often those rulings were picked** (Q4/2025 + Q1/2026; the 223 gated rulings decided by more than one judge, 59 picked, base rate 26%):

| Signal | Fires | Picked | Rate |
|---|---|---|---|
| `suva_appellant` | 8 | 8 | 100% |
| `proposed_for_publication` | 6 | 5 | 83% |
| `five_judges` | 14 | 10 | 71% |
| `suva_party` | 44 | 28 | 64% |
| `appeal_by_institution` | 35 | 22 | 63% |
| `manifestly_unfounded` | 39 | 6 | 15% |
| `single_judge` (all 300 gated rulings) | 77 | 0 | 0% |

**Signals-only baseline (variant A1 of `docs/EVAL.md` §2).** Logistic regression on area, `appeal_by_institution`, `five_judges`, `proposed_for_publication`, `manifestly_unfounded`, `suva_party` and `single_judge`, trained on the gated rulings. Out of quarter: fit and choose the F2 threshold (on out-of-fold scores) on one listed quarter, report on the other, both folds pooled. All 59 picks count.

| Protocol | F2 | Recall | Submitted of 300 |
|---|---|---|---|
| Out of quarter, both folds pooled | 0.763 | 0.83 | 85 |
| Repeated 5-fold over both quarters (5 repeats; in-quarter, for stability only) | 0.760 | 0.83 | 85 |
| Out of quarter, top 40% by score (no threshold tuned) | 0.730 | 0.88 | 120 |
| Out of quarter, top 60% by score (no threshold tuned) | 0.685 | 0.97 | 180 |
| For comparison: submit every gated ruling | 0.550 | 1.00 | 300 |

Without `single_judge` the same model drops to 0.714 out of quarter, because single-judge rulings are inside the gate and must be ranked down by the score.

These numbers match an earlier exploratory run on a narrower candidate set (F2 0.76), which is the check that the packaged code reads the same facts.

## 3. Limits

- 59 picks. One ruling more or less moves F2 by about 0.015; a bootstrap interval for this baseline was 0.69 to 0.85 in the exploratory run.
- The signals were chosen by looking at these same two quarters, so the out-of-quarter numbers are mildly optimistic.
- `appeal_by_institution` rests on a keyword list for institutions and on the court's anonymisation pattern for persons. It was hand-checked on the 35 rulings where it fires, not on the 188 where it does not.
- The publication star comes only from the court's list. Where the list is missing the value is "unknown"; a scorer must treat that explicitly.
- Tested end to end by hand on three listed rulings (one German accident-insurance, one French accident-insurance, one Italian disability-insurance): area, bench size, parties and publication mark were read correctly in each.

## 4. Not done yet

- Not called by `make run`; no stored output in `results/`.
- The scorer itself (weights, points out of 100, threshold) is the next chunk, together with the Apertus answers through `src/llm/`.
