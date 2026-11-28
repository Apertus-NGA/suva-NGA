# Triage pipeline v2: twelve rules, each in the direction a lawyer expects

> **Status: PROPOSED, working version since Sat 28 Nov 2026.** `triage_pipeline@2`, `scorer@2`,
> `structural_signals@2`. Code: `src/triage/scorer.py`, `src/signals/structural.py`, `src/triage/pipeline.py`.
> Tests: `tests/test_triage_pipeline.py`, `tests/test_structural_signals.py`. Layer 1, the six Apertus readings
> and the 40% cut are unchanged from v1 (`docs/TRIAGE_PIPELINE.md` where present).
> Run: `make triage` (from cached answers, writes nothing to the database), `make triage WRITE=1`.

## 1. What changed from v1

1. **Four more code-read facts** (`src/signals/structural.py`): another accident insurer is the party, the number
   of core accident-insurance topics the text names (German, French, Italian wording), a ruling longer than
   25,000 characters, and whether the operative part upholds the appeal.
2. **Twelve inputs instead of nine**: v1's nine, plus the other accident insurer, the topic count, and the long
   ruling in accident or military insurance.
3. **A sign-constrained logistic regression** (`scorer.SignedLogistic`). Each rule has one allowed direction,
   fixed in `scorer.SIGNS` before fitting. A rule the labels do not support gets weight 0; it can never count
   against its own meaning. Otherwise the model is v1's: L2, C = 1, balanced classes, standardised inputs.
4. **The rule table is stored** with every run (`model_runs.params.rule_weights`, `intercept`) and in
   `results/triage_pipeline.json`, so any score can be recomputed by hand (section 4).
5. **A check the fit cannot have learned**: the 23 rulings Suva summarised in Q3/2025 are relevant to Suva and
   are never used as labels. Every run reports how many of them score above the threshold
   (`summarised_by_suva_not_in_training`).

## 2. The rules (fitted on the 646 kept rulings of Q4/2025 and Q1/2026, 59 relevant)

| Rule | Read by | Direction | Weight per standard deviation |
|---|---|---|---|
| Single-judge decision | code | down | −2.26 |
| Disability insurance | code | up | +2.25 |
| Accident or military insurance | code | up | +1.28 |
| Suva is a party | code | up | +1.08 |
| Another accident insurer is the party | code | up | +0.58 |
| Appeal brought by an insurer or an authority | code | up | +0.37 |
| Five judges | code | up | +0.35 |
| Long accident or military ruling (over 25,000 characters) | code | up | +0.34 |
| Dismissed as manifestly unfounded | code | down | −0.29 |
| Apertus: the ruling teaches beyond the single case (consensus of six readings, 70B) | Apertus | up | +0.28 |
| Core accident-insurance topics in the text (count) | code | up | +0.24 |
| Marked for publication | code | up | +0.06 |

"Disability insurance: up" is relative to the other areas layer 1 keeps (health insurance, pensions, contract
law), not to accident insurance. "Appeal upheld" is read and stored as a fact for the UI; it is not an input:
offered to the model, it got weight 0.

## 3. Measured

Out of quarter: fit on one listed quarter, rank the other, both pooled; 59 relevant. The list is the top share of
the test quarter's accident, military and disability rulings.

| | Found at 30 / 40 / 50 / 60 / 70% | Recall at 40% | F2 at 40% | List for 95% / 100% recall | Found in Q1/2026 at 40% (of 31) |
|---|---|---|---|---|---|
| v1: nine inputs, unconstrained | 45 / 55 / 56 / 58 / 58 | 0.932 | 0.772 | 135 / 200 | 28 |
| **v2: twelve inputs, sign-constrained** | 47 / 55 / 56 / 58 / 59 | 0.932 | 0.772 | 149 / 175 | 29 |

v2 finds what v1 finds at the current cut. What it adds is that every rule points the way a lawyer expects, and
the table is stored. It reaches every relevant ruling with 175 rulings instead of 200, and needs 149 instead of
135 for 95%.

**A rule that was tried and removed: "a long disability ruling lowers the score".** In the two listed quarters
none of the 19 long disability rulings was picked (0 of 7 and 0 of 12), and with that rule the list for 100%
recall was 144. But Suva summarised all three long disability rulings of Q3/2025, which the fit never saw, and
the rule sent them to a score of 0 (v1: 34 to 41). It was an accident of two quarters. Without it those three
score 31 to 42 again. The same check supports the accident rule: Suva summarised all five long accident rulings
of Q3/2025, and they score 86 to 100.

On the 23 rulings Suva summarised in Q3/2025 (never labels): 16 score above the threshold, mean score 75
(v1: 16, mean 74); 2 score below 10 in both versions.

Regularisation was swept (L2 and L1, C from 0.003 to 3): C = 1 is best or tied; a stronger penalty loses
recall; L1 is never better. XGBoost was worse on every feature set (`results/triage_model_sweep.json`).

Limits: 59 relevant rulings, so one ruling is 0.017 of recall. The 25,000-character cut was chosen after looking
at both listed quarters. The Q3/2025 check holds only rulings Suva picked, so it can show a rule that hides
relevant rulings, not one that promotes irrelevant ones.

## 4. How a score is computed, so that it can be checked by hand

    z_i     = (value_i − mean_i) / scale_i            for each of the twelve rules
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
