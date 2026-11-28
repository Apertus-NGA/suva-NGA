# Triage pipeline v2: thirteen rules, each in the direction a lawyer expects

> **Status: PROPOSED, working version since Sat 28 Nov 2026.** `triage_pipeline@2`, `scorer@2`,
> `structural_signals@2`. Code: `src/triage/scorer.py`, `src/signals/structural.py`, `src/triage/pipeline.py`.
> Tests: `tests/test_triage_pipeline.py`, `tests/test_structural_signals.py`. Layer 1, the six Apertus readings
> and the 40% cut are unchanged from v1 (`docs/TRIAGE_PIPELINE.md` where present).
> Run: `make triage` (from cached answers, writes nothing to the database), `make triage WRITE=1`.

## 1. What changed from v1

1. **Four more code-read facts** (`src/signals/structural.py`): another accident insurer is the party, the number
   of core accident-insurance topics the text names (German, French, Italian wording), a ruling longer than
   25,000 characters, and whether the operative part upholds the appeal.
2. **Thirteen inputs instead of nine.** The long ruling counts separately in accident / military insurance and in
   disability insurance, because it means opposite things there (section 3).
3. **A sign-constrained logistic regression** (`scorer.SignedLogistic`). Each rule has one allowed direction,
   fixed in `scorer.SIGNS` before fitting. A rule the labels do not support gets weight 0; it can never count
   against its own meaning. Otherwise the model is v1's: L2, C = 1, balanced classes, standardised inputs.
4. **The rule table is stored** with every run (`model_runs.params.rule_weights`, `intercept`) and in
   `results/triage_pipeline.json`, so any score can be recomputed by hand (section 4).

## 2. The rules (fitted on the 646 kept rulings of Q4/2025 and Q1/2026, 59 relevant)

| Rule | Read by | Direction | Weight per standard deviation |
|---|---|---|---|
| Disability insurance | code | up | +2.41 |
| Single-judge decision | code | down | −2.30 |
| Accident or military insurance | code | up | +1.33 |
| Suva is a party | code | up | +1.11 |
| Long disability ruling (over 25,000 characters) | code | down | −0.86 |
| Another accident insurer is the party | code | up | +0.60 |
| Five judges | code | up | +0.45 |
| Appeal brought by an insurer or an authority | code | up | +0.37 |
| Long accident or military ruling | code | up | +0.33 |
| Dismissed as manifestly unfounded | code | down | −0.30 |
| Apertus: the ruling teaches beyond the single case (consensus of six readings, 70B) | Apertus | up | +0.28 |
| Core accident-insurance topics in the text (count) | code | up | +0.21 |
| Marked for publication | code | up | +0.05 |

"Disability insurance: up" is relative to the other areas layer 1 keeps (health insurance, pensions, contract
law), not to accident insurance. "Appeal upheld" is read and stored as a fact for the UI; it is not an input:
offered to the model, it got weight 0.

## 3. Measured (out of quarter: fit on one listed quarter, rank the other, both pooled; 59 relevant)

The list is the top share of the test quarter's accident, military and disability rulings.

| | Found at 30 / 40 / 50 / 60 / 70% | Recall at 40% | F2 at 40% | List for 95% / 100% recall | Found in Q1/2026 at 40% (of 31) |
|---|---|---|---|---|---|
| v1: nine inputs, unconstrained | 45 / 55 / 56 / 58 / 58 | 0.932 | 0.772 | 135 / 200 | 28 |
| **v2: thirteen inputs, sign-constrained** | 48 / 55 / 58 / 59 / 59 | 0.932 | 0.772 | 130 / 144 | 29 |

- At the current cut (40%) v2 finds the same 55; it finds more at 30%, 50% and 60%, and reaches every relevant
  ruling with 144 rulings instead of 200.
- The long ruling: in the listed quarters all 7 long accident rulings were relevant and none of the 19 long
  disability rulings (4 of 4 and 0 of 7 in Q4/2025; 3 of 3 and 0 of 12 in Q1/2026). Without the disability
  rule the list for 100% recall is 175.
- Regularisation was swept (L2 and L1, C from 0.003 to 3): C = 1 is best or tied; a stronger penalty loses
  recall; L1 is never better. XGBoost was worse on every feature set (`results/triage_model_sweep.json`).

Limits: 59 relevant rulings, so one ruling is 0.017 of recall. The long-ruling split and the 25,000-character
cut were found after looking at both listed quarters (20,000 does worse, 30,000 the same): optimistic for Q2/2026.
The reason why long disability rulings are not picked (our guess: long assessments of one person's medical
evidence) is not confirmed by Suva. A long disability ruling is ranked lower, never excluded.

## 4. How a score is computed, so that it can be checked by hand

    z_i     = (value_i − mean_i) / scale_i            for each of the thirteen rules
    logit   = intercept + Σ weight_i · z_i
    score   = 100 / (1 + exp(−logit))                 shown out of 100 in the UI

`mean`, `scale`, `weight` and `sign` of every rule and the `intercept` are in `model_runs.params` of the run and
in `results/triage_pipeline.json` (`rule_weights`, `intercept`). Each prediction stores `details.contributions`
(the terms `weight_i · z_i`, the push of each rule relative to an average ruling), `details.signals` (every fact,
including `core_topic_names`, `long_ruling`, `other_accident_insurer`, `appeal_upheld`) and
`details.apertus_readings` (the six readings).

## 5. For the UI

- New facts to show without points: `details.signals.appeal_upheld`, `core_topic_names`.
- The rule table for an "how the score is computed" view: `model_runs.params.rule_weights` of the current run.
- The German sentence in `predictions.explanation` is still built by code from the rules that apply.
