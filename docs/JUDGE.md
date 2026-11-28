# JUDGE: how the German and French summaries are graded by a model

> **Status: PROPOSED (27 Nov 2026).** Fills the "Optional judge" line of `docs/EVAL.md` §4. Owner: evaluation. Code: `eval/judge/` and `src/llm/judge.py`. Tests: `tests/test_judge.py`. The judge is an evaluation tool: `make run` never calls it, and it never sees a live user request.

## 1. What it is for, and what it is not

Suva's experts will grade our summaries on style and legal precision (`challenge_description.md`). We cannot ask a lawyer to read every summary after every prompt change, so a model does a first reading, criterion by criterion, and people check the model (section 5).

The judge answers up to eleven yes-or-no questions about one summary. It does not produce a mark out of ten, it does not rank two summaries, and it does not replace the human review of `docs/EVAL.md` §4. A criterion counts in a headline number only once it has passed the validation of section 5.

Order of priority, set by the team member who owns the data layer and reflected in the weights: (1) the right legal terms and the right tone; (2) everything the summary says is true and comes from the ruling; (3) what matters in the ruling is in the summary.

## 2. Design choices, each with its reason

| Choice | Reason |
|---|---|
| One call per criterion, binary answer | A single overall mark lets a strong impression on one point colour the others, and a 1 to 5 scale is not reproducible between runs. A yes or no on one narrow question is. |
| Deterministic checks first (`eval/judge/checks.py`) | What code can decide is not asked of a model (`docs/EVAL.md` §1.3): statute abbreviations and citation forms of the right language, headings and lists, anonymisation placeholders, a repeated sentence, length against Suva's 55 summaries. |
| The model lists the units it checked, each with a verbatim quote, before it concludes | Reasoning before verdict. The quotes make every verdict auditable by a lawyer in seconds. |
| The verdict is recomputed by code | FAIL as soon as one unit is marked not ok. An answer whose stated verdict contradicts its own units is discarded. |
| A FAIL must quote real text | Code looks for the quote in the summary, the ruling or the reference. A FAIL built on a quote that does not exist is discarded: this is the guard against a judge that invents a defect. |
| A PASS on tone or language must quote every sentence | Seen in a trial run: a model cleared a summary after skipping its one bad sentence. Code now checks that every sentence was examined. |
| Unusable answers are counted apart | Bad JSON, a contradiction or a missing quote is retried once, then reported as "no verdict". It is never read as a pass or as a fail (`docs/EVAL.md` §1.8). |
| Each criterion says what does not belong to it and what to do in doubt | Stops one defect from failing five criteria, and stops the model from choosing its own default. For faithfulness the burden is on the summary; for style a FAIL needs a quotable passage. |
| The judge is not told who wrote the text | It grades Suva's own summaries and ours with the same prompt. This is also what makes the validation of section 5 possible. |
| The judge is of another model family than Apertus | A model tends to favour its own output, and Apertus agreed with humans at chance level as a quality judge (`docs/LESSONS.md`). Rule G10. |
| Highest reasoning effort, temperature 0, fixed seed, pinned model and provider | Legal texts of 10 to 30 pages against a summary: the judge has to find one changed word. Pinning makes a run repeatable. |
| The ruling is sent whole, in its own language | No retrieval step that could hide the passage that contradicts the summary. A ruling above 250,000 characters is not judged at all, and is counted. |
| Calibration examples in the rubric are invented | None comes from a ruling or from Suva's summaries, so the prompt can be committed (D-031) and no test ruling leaks into it. |
| Suva's summaries are read from `judgements/` at run time | They are shown to the judge as house-style examples (tone criteria) and as the reference (R1). Nothing of them is copied into the repo. |

## 3. The rubric

The single home of the wording is `eval/judge/rubric.json`; the system prompt is `eval/judge/system_prompt.txt`. This table is a reading aid.

| Id | Question the judge answers | Sees | Weight | Critical |
|---|---|---|---|---|
| T1 | Does every legal term of art use the established Swiss term in the summary's language? | summary, ruling | 0.15 | yes |
| T2 | Is the whole summary in the impersonal, neutral, declarative register of a case-law digest? | summary, 3 house examples | 0.10 | |
| T3 | Is it written entirely in correct, idiomatic German or French? | summary | 0.10 | |
| T4 | Does it contain only digest content, each point stated once? | summary, 3 house examples | 0.05 | |
| F1 | Is every factual statement stated in, or directly entailed by, the ruling? | summary, ruling | 0.10 | yes |
| F2 | Is every statement of law attributed to the Federal Supreme Court faithful in content and strength? | summary, ruling | 0.12 | yes |
| F3 | Is everything said about the appeal and its outcome correct? | summary, ruling | 0.08 | yes |
| F4 | Is every legal reference present in the ruling and attached to the same point? | summary, ruling | 0.05 | |
| C1 | Does the summary state at least one legal holding with its reason? | summary, ruling | 0.09 | yes |
| C2 | Does it give the court's answer to the main disputed question? | summary, ruling | 0.08 | |
| R1 | Does it convey every legal point of Suva's own summary of the same ruling? | summary, Suva's summary | 0.08 | |

Style 0.40, faithfulness 0.35, coverage 0.25. R1 runs only for the rulings Suva summarised; elsewhere its weight is left out and the rest is rescaled.

Where the criteria come from. We read Suva's summaries against their rulings, then generated summaries of nine of the same rulings with the team's summariser and read those too. The defects seen in the generated texts are the ones the criteria name: facts and outcome with no legal point (C1); a condition reversed, a party's position swapped (F2, F1); a rate the court did not fix presented as confirmed (F3); French words left in a German text and calqued terms (T3, T1); the anonymisation placeholder kept and the outcome sentence repeated (T2, T4, and the code checks). Suva's own texts set what is not a defect: no outcome sentence, no consideration reference, a single-sentence rule, no facts at all.

Two results per summary, computed by code (`core.score`):
- **score**: the weighted share of passed criteria among those that got a verdict;
- **usable**: true when every critical criterion passed. A summary with a wrong outcome is not usable whatever its score.

Per-criterion pass rates with their 95 % Wilson intervals, per language, are the primary result. The score is a convenience.

## 4. The judge model

Requirements: open weights under a permissive licence (G14 bans non-commercial licences); another family than Apertus (G10); a reasoning model whose effort can be set to its maximum; reads German, French and Italian legal text; returns JSON under a schema; a fixed, dated checkpoint so that a run can be repeated; small enough to be hosted on premise if the team ever wants the judge inside the sovereign perimeter.

| Candidate | Licence (Hugging Face model card, read 27 Nov) | Why it is on the list | Open point |
|---|---|---|---|
| `openai/gpt-oss-120b` | Apache-2.0 | Reasoning effort settable (low, medium, high); structured output; 131k context; one 120B checkpoint that fits a single 80 GB GPU; the cheapest of the three by a wide margin | Released August 2025: newer open models may reason better |
| `deepseek-ai/DeepSeek-V4-Pro` | MIT | The strongest MIT-licensed reasoning model listed by the hosting route we looked at; 1M context | Much larger and dearer; structured output not offered by every host; how its reasoning effort is set is to be confirmed |
| `Qwen/Qwen3.5-397B-A17B` | Apache-2.0 | Large Apache-2.0 model with broad language coverage | Dearer; German and French legal reading untested by us |

Models excluded for their licence tag ("other", to be read before any use): `mistralai/Mistral-Large-4-1T-A52B`, `zai-org/GLM-5.3`, `moonshotai/Kimi-K3`.

**Proposed default: `openai/gpt-oss-120b` at reasoning effort `high`**, its highest level. It is the only candidate whose behaviour on every requirement is documented, and its price lets us run the whole validation twice. The choice is not final: the same validation command runs with any `JUDGE_MODEL`, and the model with the best measured sensitivity and specificity on the development split is the one to keep. First measurements are in section 5: gpt-oss-120b is adequate for the faithfulness, outcome, reference and coverage criteria with the second reading, and not for T1 and T3, where DeepSeek V4 Pro was clean on a small sample.

Settings, in the environment or `.env` (names only in `.env.example`; no default, so a run cannot silently use another model):

```
JUDGE_MODEL=openai/gpt-oss-120b        # add ":<provider>" to pin one host on the Hugging Face router
JUDGE_BASE_URL=https://router.huggingface.co/v1
JUDGE_API_KEY=<a token allowed to call the hosted models>
JUDGE_REASONING_EFFORT=high            # optional; "high" is the default
```

Any OpenAI-compatible endpoint works, including a local one. The transport refuses an Apertus model, in the setting and in the answer.

## 5. Validation: is the judge right?

A judge is a measuring instrument and is measured like one, on cases whose true label is known. Thresholds were written before any measurement (`eval/judge/metaeval.py`, `THRESHOLDS`): sensitivity ≥ 0.80, specificity ≥ 0.80, agreement with itself over two runs ≥ 0.90, answers without a verdict ≤ 5 %, Cohen's κ against a human ≥ 0.60. A criterion below a bar is reported as **not validated** and stays out of headline numbers.

**Known-label cases.**
- Expected PASS: the summary Suva's experts wrote, in the ruling's own language. (The other language side is a translation with known artefacts, `docs/SUVA_DATA.md` §3, so it is not used as a positive for style.)
- Expected FAIL: the same summary after one controlled defect that targets one criterion (`eval/judge/perturb.py`): foreign-law terms; an opinion and an address to the reader; an assistant-style opening; one sentence left in the other language; costs boilerplate and a repeated sentence; a changed figure; an invented fact; a reversed qualifier ("in principle" to "always"); an invented holding; the opposite outcome; a wrong article or consideration; a text with procedure and outcome only; the first paragraph only (for R1).
- For R1 the expected PASS is the expert's own text in the other language against the original.

**Split.** The split of `docs/EVAL.md` §4: test = the Q1/2026 summaries plus the German-language Q4/2025 ones (533 cases); development = the rest (738 cases). The rubric wording is tuned on the development split only. The test split is run once, twice over, and reported.

**Human agreement.** `metaeval sheet` writes a blind sheet (the annotator sees the texts and the question, not the expected label, not the judge's answer). `metaeval kappa` compares. About 60 rows, one hour of a lawyer or of a careful team member per language. Until this is done, the judge is validated against constructed labels only, and the report must say so.

**Results so far (28 Nov, development split only, small samples).** The held-out test split has not been run: the numbers below come from the first eight development rulings and were used to tune the wording, so they are optimistic.

- `openai/gpt-oss-120b`, rubric v2, 190 known-label cases (`results/judge_metaeval_dev.json`): every planted defect caught on ten of eleven criteria (T1: 5 of 6). Expert or court text accepted: 8 of 8 on F3, C1; 7 of 8 on T1, T2, T4; 6 of 7 on F4; 6 of 8 on F1, F2; 5 of 8 on C2; 3 of 7 on T3. Reading the disputed cases showed that most F1 and F2 objections were the judge failing to find a passage that was there, which led to the second reading (rubric v3).
- `deepseek-ai/DeepSeek-V4-Pro`, rubric v3, 75 cases on T1, T3, F1, F2, C2 (`results/judge_metaeval_dev_deepseek.json`): every planted defect caught; court or expert text accepted 6 of 6 on T1, T3, F2, 5 of 6 on F1, 4 of 6 on C2; no answer without a verdict. About ten times the cost per case of gpt-oss-120b.
- Rubric v3 on gpt-oss-120b was not measured on known-label cases (the run was stopped). It was used once on 42 generated summaries (`results/judge_run_pipeline_v1.json`); reading its failures showed that on T1 and T3 it still marks correct Swiss usage as wrong ("gutgeheissen", "Fristerstreckung", "vor Bundesgericht"), and that it reads the closing bench note ("Fünfer-Entscheid") as an unsupported fact.

**What follows.** (1) T1 and T3 are **not validated** on gpt-oss-120b; use DeepSeek V4 Pro for these two criteria, or do not report them. (2) C2 fails about a third of Suva's own summaries on both models: the experts often digest the legally interesting point rather than the main dispute. C2 is a diagnostic and should carry no weight until reworded. (3) Judge the summary without its closing bench note; check that note by code. (4) Run the test split and the human sheet before any of these numbers goes into the report.

One plumbing run was also made with Apertus standing in for the judge, to test the code path only. It is not a result, and Apertus is not a candidate.

```
uv run python -m eval.judge.metaeval run --split dev --dry-run   # counts the cases, calls nothing
uv run python -m eval.judge.metaeval run --split dev             # tune here, per candidate model
uv run python -m eval.judge.metaeval run --split test --reps 2   # report this
uv run python -m eval.judge.metaeval sheet --split test          # then: kappa --sheet <file>
```

Numbers go to `results/judge_metaeval_<split>.json` (aggregates only). The per-case detail, with its quotes of Suva's texts, goes to `data/derived/judge/` (git-ignored, D-031).

## 6. Judging our summaries

```
uv run python -m eval.judge.run --candidates data/trial --name v2
```

Reads the files `src/summarize/summarize.py` writes, or a JSON-lines file of `{"docket", "language", "summary"}`. Output: `results/judge_run_<name>.json` with, per language, the pass rate of each criterion and its interval, the mean score, the usable share, the count of code-check flags and the count of calls without a verdict.

To compare two prompt versions, judge both on the same rulings and compare criterion by criterion with a paired bootstrap (`docs/EVAL.md` §1.5). Never put a ruling in a summariser prompt and in the set it is judged on (`docs/EVAL.md` §4).

## 7. Limits

- Validated, so far, against constructed defects. Real defects of generated text are subtler than an appended sentence: sensitivity on the constructed set is an upper bound until the human sheet is done.
- Suva's summaries are not perfect positives: some digest a side point of the ruling (C2 may fail them) and some carry a typo. A few expected-PASS cases will be judged FAIL for good reason; they are read one by one, not averaged away.
- R1 treats Suva's choice of what to keep as the truth. Where two lawyers would keep different points, R1 punishes a defensible summary.
- The coverage criteria ask the judge to find the holding of a ruling by itself. On a long multi-issue ruling this is the hardest thing the judge does.
- One judge model. A second model of a third family on a sample would show how much a verdict depends on the judge.
- Structure parity between the German and the French text (Q-27) is not judged here: it compares two summaries, and belongs to a code check.
- Cost and time: eleven calls per summary at the highest reasoning effort. For the 46 summaries of the internal hold-out this is about 500 calls.

## 8. Open questions this touches

| Question | Position taken while open |
|---|---|
| D-031 (may artefacts derived from Suva's texts be committed) | Nothing derived is committed: prompts hold invented examples, Suva's texts are read at run time, details go to `data/derived/`. |
| Q-30 (which house style the experts expect) | The judge accepts both shapes (rule statement, narrative) and requires neither an outcome sentence nor consideration references. |
| Q-08, D-053 (length) | Length is a code check against the 10th to 90th percentile of the 55 summaries, reported, not a judge criterion. |
| Q-27 (French written independently, same paragraphs) | Not judged here; see Limits. |
| `docs/EVAL.md` §4 proposes five answer levels per criterion (met, partial, missing, contradicted, uncertain) | This design uses two, with the doubt rule written in each criterion, as the team member asked. To raise at the next sync. |
