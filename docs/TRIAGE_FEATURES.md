# Apertus as a feature extractor, then logistic regression or XGBoost

> **Status: EXPERIMENT, 28 Nov 2026.** Branch `triage/apertus-features`. The pipeline (`src/triage/pipeline.py`,
> D-073) is unchanged. Numbers: `results/triage_features.json` (aggregates only, D-031), written by
> `research/arm_o_variants.py`. Per-ruling answers: `data/derived/triage_features/` (git-ignored).

## 1. Question and answer

Can narrow Apertus readings, used as features of a logistic regression or of XGBoost, find more of Suva's relevant
rulings than the current classifier (8 code-read facts plus the consensus of six Apertus readings)?

**Answer: not by a margin we can claim.** One new reading, the 8B's probability that the court makes its own reusable
legal statement when it must also point to it, is the only variant better than the baseline on every recall
measure, and the gain repeats under a second protocol and a second repetition of the calls. But it is one ruling at
the current list size, below the pass rule written before measuring, and it was the best of about 40 variants.
XGBoost never beats logistic regression. The research sprint of 27 Nov (`research/updates/`) reached the same
ceiling with other features: F2 about 0.76 to 0.78 on these labels.

## 2. Protocol (fixed before any variant was measured)

- Rulings: the 646 kept by layer 1 in the two listed quarters; 59 relevant (Suva's list, closed world, Q-04).
- Out of quarter: fit on one quarter, rank the other, both directions pooled. New prompts were written on
  2025 Q4 only, so "Q1 @ 40%" (fit on Q4, test on Q1) is the clean number; the pooled one is optimistic for them.
- The submitted list: the top `share` x (the test quarter's accident, military and disability rulings), as the
  pipeline cuts. Shares 30% to 70%.
- Recall first: the shortest list that reaches 95% and 100% of the relevant rulings.
- **Pass rule:** pooled, at least 2 more found at 40%, none fewer at any share, no longer list for 95% recall.
- Checks: paired bootstrap of the rulings found at 40% (1,000 draws); 10 repeats of stratified 5-fold
  cross-validation over both quarters, paired with the baseline (`src/triage/variants.py`).

## 3. What was tried

| Feature | How Apertus is asked | Code's part |
|---|---|---|
| Topic (`src/triage/features.py`) | which legal question the ruling decides: one letter of ten (forced choice, avoids the yes-bias of yes/no questions) | maps the topics to "also holds in accident insurance" by a table fixed from Suva's rubric |
| Statement + quote (`src/triage/evidence.py` v1) | the measured `yes_strict` question, then the sentence where the court says it, word for word | checks that the quote is in the reasoning and is not a restatement of case law |
| Statement + consideration (`evidence.py` v2) | the same question, then the number of the consideration, chosen from the list code read in the ruling (G1) | checks the number is on the list, fetches that consideration's text, rejects standard-of-review parts |
| Research answers (27 Nov) | nine rubric questions and the "principle" composite, joined by docket | none |
| Code only | none | procedural subject; topic of the subject line's bracket |

Each Apertus reading was run on all 1,090 kept rulings, with both the 8B and the 70B (about 7,600 calls in total,
through `src/llm/`; every call answered HTTP 200, and 52 consideration answers that ran past their 12-token
limit were discarded as failures, G3). Answers are one token read from its log-probabilities, plus at most one short line.

## 4. Results (pooled over both quarters, 59 relevant)

| Variant | Found @ 30/40/50/60/70% | F2 @ 40% | Mean F2 | List for 95% / 100% recall | Q1 @ 40% | vs baseline @ 40% (95% CI) |
|---|---|---|---|---|---|---|
| Apertus `verdict` reading alone (raw Apertus) | 44 / 49 / 55 / 57 / 57 | 0.688 | 0.681 | 154 / 602 | 24 | −4.5 [−10, +1] |
| 8 facts, logistic regression | 49 / 52 / 56 / 58 / 58 | 0.730 | 0.713 | 154 / 184 | 28 | −2.3 [−7, +3] |
| 8 facts, XGBoost | 48 / 52 / 57 / 58 / 59 | 0.730 | 0.714 | 149 / 175 | 28 | −2.5 [−8, +3] |
| **Baseline: 8 facts + consensus, LR** | 45 / 55 / 56 / 58 / 58 | 0.772 | 0.709 | 135 / 200 | 28 | — |
| Baseline features, XGBoost | 46 / 48 / 54 / 55 / 57 | 0.674 | 0.677 | 196 / 238 | 25 | −4.9 [−10, −1] |
| + research "principle" | 45 / 53 / 56 / 58 / 58 | 0.744 | 0.703 | 143 / 202 | 28 | −0.9 [−4, +1] |
| + topic "shared", inside IV (8B) | 46 / 54 / 56 / 58 / 59 | 0.758 | 0.711 | 146 / 192 | 27 | −0.2 [−3, +4] |
| **+ statement P(Ja), log-odds (8B)** | **46 / 56 / 57 / 58 / 59** | **0.787** | **0.720** | **131 / 181** | **29** | **+0.9 [0, +4]** |
| + statement P(Ja), log-odds (70B) | 45 / 53 / 55 / 58 / 58 | 0.744 | 0.700 | 159 / 201 | 28 | −1.2 [−5, +2] |
| + consideration P(Ja), log-odds (8B) | 45 / 55 / 57 / 58 / 58 | 0.772 | 0.711 | 134 / 193 | 28 | +0.7 [−2, +4] |

Every XGBoost variant is at or below its logistic-regression twin. The full table (68 variants) is in
`results/triage_features.json`.

**Second protocol** (10 repeats of 5-fold cross-validation, found at 40%, paired): baseline 52.6; + statement
P(Ja) 8B 54.3 (better in 8 of 10 repeats, worse in none); + statement 70B 51.4 (worse in 8); 8 facts alone 51.0;
XGBoost on 8 facts 51.1. At 50%: baseline 55.2, + statement 8B 56.4 (better in 6, worse in 1).

**Second repetition** of the 8B statement reading, outside the cache (G10): 98.5% of the probabilities identical,
rank correlation 0.9999, the same labels on all 1,090 rulings, and the same evaluation numbers.

**On Q2/2026** the 8B statement feature changes 4 of the 76 rulings in the 40% list.

## 5. What we learned about Apertus

- **Asking for evidence removes the yes-bias.** The same question with no evidence says yes about a third of the
  time; with a quote or a consideration required, the 8B said yes to 16 to 23 of 1,090 rulings and the 70B to 2 to
  40. Its probability of "Ja" then ranks well inside an area on 2025 Q4 (70B: 0.94 accident, 0.80 disability,
  against 0.81 and 0.66 for the current consensus), less well on 2026 Q1 (0.78 and 0.77).
- **Apertus does not quote.** Asked for a sentence word for word, it paraphrases ("Das Bundesgericht legt fest,
  dass ...") and translates French rulings into German: 0 of the 70B's 40 quotes and 1 of the 8B's 16 were found in
  the text. Letting it **choose a consideration number from a list** works: 20 of the 8B's 23 "Ja" point to a real
  consideration, whose text code then shows. That is the form to use for evidence in the UI (principles 4 and 7).
- **Topic signals did not transfer.** "Shared with accident insurance" ranked disability rulings at 0.84 on 2025 Q4
  and 0.57 on 2026 Q1.
- **More fitted weights cost more than they bring** with 59 relevant rulings: every extra feature family lowered
  the held-out count, as in the research sprint. A consensus that adds the new readings with no fitted weight did
  not help either.
- **8B and 70B differ more than expected.** The 8B feature helps and is stable across repetitions; the 70B feature
  ranks better alone on Q4 but lowers the model's result.

## 6. Recommendation

1. **Keep the current pipeline as the default.** No variant meets the pass rule; the observed gain is one or two
   rulings out of 59, which is inside the noise of this label set.
2. **If the team wants the recall margin anyway**, add the 8B statement reading as a ninth input: 1,090 8B calls
   (about 4 minutes), stable, changes 4 of 76 Q2 rulings, list for 100% recall 181 instead of 200. Say in the report
   that it was chosen among about 40 variants.
3. **Do not use XGBoost** on this data.
4. **Use the consideration pointer for explanations, not for the score:** the lawyer sees the consideration where
   Apertus says the court states its rule, fetched by code.
5. **The list size moves recall more than any feature.** Going from 40% to 50% finds one more relevant ruling
   (56 instead of 55) for 29 more submissions, and F2 falls from 0.772 to 0.727. That choice (D-021 point 5, D-046)
   matters more than the features tested here.

## 7. Run it again

```
uv run --frozen pytest -q tests/test_triage_features.py
# per feature and model, live, about 2 to 7 minutes each (needs LLM_*; LLM_NAME_SMALL=apertus-v1-5-8b for the 8B)
uv run --frozen python research/arm_o_features_run.py --feature statement --size small
# every variant, from the replay cache and the stored features; no gateway call
uv run --frozen python research/arm_o_variants.py --out results/triage_features.json
```

`--feature` is one of `topic`, `statement`, `cons`, `statement_rep1`; `--size` is `small` (8B) or `large` (70B).

## 8. Limits

- 59 relevant rulings in two quarters: one ruling moves recall by 0.017 and F2 by about 0.015.
- About 40 variants were compared on the same data; the best of them is optimistic.
- The new prompts were written on 2025 Q4, so only the fit-on-Q4, test-on-Q1 direction is clean for them.
- Rulings outside the core get the mean value of a reading they were not asked, as the consensus does.
- 52 consideration readings (46 of them the 70B's) ran past their token limit and 38 rulings have no numbered
  reasoning; they count as "no reading", never as "no".
