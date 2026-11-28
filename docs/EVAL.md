# EVAL: test bench and measurement protocol

> **Status: v0 PROPOSAL (27 Nov 2026), updated after the official template was read.** Owner: evaluation. Thresholds marked `<to set>` are written **before** the first measurement and committed. Facts and counts about Suva's labels and summaries: `docs/SUVA_DATA.md`.

## 1. Principles

1. **Pre-registered thresholds:** written and committed before measuring.
2. **Frozen gold:** every gold set has a SHA-256 manifest and a git tag before any measurement; it is never edited after. Suva's gold is `judgements/` itself, never edited (D-040); its workbook hash and folder manifest are in `docs/SUVA_DATA.md` §1.
3. **Deterministic graders first** (JSON valid, citations verbatim, references exist, numbers preserved, language right, length); an LLM judge only as a complement, open-weights, from another family than Apertus, with κ against humans published.
4. **Two repetitions** outside the replay cache (the repetition index is part of the cache key); a change counts only if it beats the noise; guards (0 invented citation) are decided on the worst repetition.
5. **Confidence intervals:** Wilson lower bound for recall; paired bootstrap (10,000 draws) for differences.
6. **Per language** (DE, FR, IT), never only aggregated.
7. **Baselines and one change per line.**
8. **Counted runs:** the runner checks that the number of cases executed equals the gold size; `failed` and timeouts are counted apart and never as negatives.
9. **Publish the limits** and at least one negative result.

## 2. Triage: protocol that mirrors Suva's scoring

| Step | Data | Output |
|---|---|---|
| Fit | Q4/2025 population by decision date (D-050; the few-shot pool is drawn apart from it, D-021 point 8); positives = the 28 rulings labelled `2025 Q4` in `judgements/BG_Urteile_2025_Q4_2026_Q1.xlsx`; negatives = every other Federal Court ruling decided that quarter, under the closed-world assumption (Q-04; the file has no explicit negatives) | learned weights (A1, A3) and the few-shot pool |
| Choose threshold | Q4/2025, the fitting quarter: from out-of-fold scores under option B, directly under option A | threshold maximising F2, then frozen |
| Report | Q1/2026 population by decision date (31 Federal Court positives), at that frozen threshold | recall (Wilson lower bound), precision, F2, per language and per court, with CIs; precision and hits at 30 (D-046); recall on the must-hit subset (`docs/GLOSSARY.md`, Q-20); the same metrics on the publication-date reading (D-050) |
| Swap | the same three steps with the quarters exchanged: fit and choose the threshold on Q1/2026, report on Q4/2025 (28 positives) | the second fold |
| Headline | both folds | the cross-quarter result, both folds shown; the pitch and the report call it "out-of-quarter" |
| Refit | Q4/2025 + Q1/2026 | final model; the threshold policy after refit is D-021 point 8, fixed before measuring; the threshold is frozen before the Q2 predictions |
| Predict | Q2/2026: the union of the rulings published and the rulings decided in the quarter, each flagged under both definitions (D-050) | the ranked list; the delivered set follows Q-02, D-009 (published in the quarter) by default while D-050 is open (D-052) |

**Closed-world assumption (Q-04), stated in the report.** Suva's list holds positives only. While Q-04 is open, a Federal Court ruling of a labelled quarter that is not on the list counts as not relevant. If Suva says the lists are incomplete, precision becomes a lower bound; recall is unaffected.

**Date definition (D-050, OPEN).** Suva's labels follow the decision date in every dated row. While open, each labelled quarter is measured on its decision-date population (positives: its labelled rows; negatives: every other Federal Court ruling decided in the quarter). The same metrics are reported a second time on its publication-date population (the rulings put online in the quarter); labelled rulings that fall outside it under that reading are counted and listed, not hidden. A local comparison of two cuts on one frozen logistic regression (adaptive Top-K against a probability threshold), split by publication date, is `docs/SELECTION_BENCHMARK.md`. Closed 28 Nov: the F2 gap on the evaluation quarter is not separated from zero, a hybrid of the two cuts equals the threshold, and the production quota is unchanged. It does not replace the folds above and it does not settle D-021 or D-050.

**Folds.** Q4/2025 (28 positives) and Q1/2026 (31 Federal Court positives) are two separate folds. Never tune on the fold being measured: the protocol above chooses the threshold on one quarter and reports on the other (D-021 point 5). Any number measured on the quarter that also chose its threshold (for example after the final refit) is labelled optimistic. Q3/2025 (23 summarised rulings, no list) is for development only: no recall is measured on it (Q-29).

**Recall ceiling (Q-28).** The Q1/2026 list includes one cantonal decision, which a Federal Court crawl cannot find. Q1/2026 recall is reported on the 31 Federal Court rows, and the ceiling on all 32 rows (31/32) is stated next to it.

**Hard negatives (measured, `docs/DATA.md` §6).** Of the negatives, 104 in Q4/2025 and 131 in Q1/2026 are accident, disability or military rulings that Suva did not keep; the other ~1,800 per quarter are easy. The threshold is placed among the hard negatives: report precision and the false-positive count on them apart, per subject area, next to the whole-population numbers. The evaluation sets are rebuilt and frozen as dataset DS6 (`docs/DATA.md` §10), with the expected counts there.

Variants compared out of quarter, on both folds (one line each):
- **A0-kw** the template's keyword baseline ("key words, i.e. Suva or Accident"): Suva/CNA/INSAI or Unfall/accident/infortunio in the full text, in DE, FR and IT (D-021). It is expected to miss the 14 positives that are pure disability rulings naming neither Suva nor accident insurance (`docs/DATA.md` §6): report how many it misses;
- **A0** rules-only baseline (any of the 9 example rules fired);
- **A1** signals only (learned weights, no LLM);
- **A2** Apertus only (probability or label);
- **A3** combination (signals + Apertus, learned);
- **A4** the best variant without the mechanical net (to measure what the net costs in recall).

Which variant is delivered is what these measurements are for: they settle D-021 in `docs/DECISIONS.md`.

Also report: number of rulings to read per week at the chosen threshold, share dropped by the net, and `failed` count; precision and hits at 30 (D-046); recall on the must-hit subset (`docs/GLOSSARY.md`, Q-20).
- **Hits at 30:** the number of labelled rulings among our 30 highest-scored rulings of the quarter. **Precision at 30** = hits ÷ 30. Both need no threshold. While D-046 is open, recall and F2 at the threshold, and precision and hits at 30, are reported on each labelled quarter; a number that depends on something tuned on the quarter being reported is labelled optimistic (see "Folds" above).
- **Must-hit subset:** defined once in `docs/GLOSSARY.md` (22 rulings in Q4/2025, 10 in Q1/2026; the 23 Q3/2025 exports are a population check, T30, not a must-hit). Their recall is reported apart, at the threshold and in the top 30, since what "identified" means is Q-20.

Known limit: a labelled quarter holds only 28 or 31 Federal Court positives (`docs/SUVA_DATA.md` §2), so intervals will be wide; say so.

## 3. Test case catalogue

| ID | Case | Why it matters | Expected behaviour |
|---|---|---|---|
| T01 | Temporal split Q4/2025 → Q1/2026, then swapped | reproduces Suva's "learn on the past, predict next quarter"; without it our recall is optimistic | protocol §2: the forward fold mirrors Suva's setting; both folds are shown |
| T02 | Implicit negatives | Suva's list holds positives only (`docs/SUVA_DATA.md` §2) | negatives = every other Federal Court ruling of the quarter, by decision date while D-050 is open (closed world, Q-04); flag if Suva provides explicit ones |
| T03 | 8C ruling outside accident insurance (social assistance, unemployment) | 8C ≠ accident insurance | low score unless content says otherwise; never excluded by prefix |
| T04 | Relevant 9C ruling (disability insurance touching accident-insurance notions, or mentioning Suva) | 9C is in scope | can be selected |
| T05 | 9C tax ruling | 9C also handles taxes since 2023 | low score with a reason (or dropped by the net with a reason code, if a net is used) |
| T06 | Italian ruling in accident insurance | in the triage scope; lexicon must cover IT (INSAI, assicurazione contro gli infortuni, ricorso accolto) | signals fire; explanation produced |
| T07 | Inadmissibility (Nichteintreten / irrecevable / inammissibile) in accident insurance | ticks domain rules without adding law | usually low; reason given |
| T08 | Starred ruling (destined for publication) | strong signal; star exists only in the Neuheiten list | star captured at crawl |
| T09 | Five-judge bench, Suva not a party | the deck's top row is like this | can score high |
| T10 | Multi-issue ruling | summary needs one paragraph per issue | structure respected |
| T11 | Decided in Q2 but published in Q3, and the reverse | which date defines the window is OPEN (D-050); D-009 (publication date) is the default (D-052) | in the candidate union, with both quarter flags set; delivered or not according to Q-02 (default: by publication date) |
| T12 | Suva recourse in civil-law court (4A) | Suva mention outside 8C/9C; Suva summarised a 4A ruling (`judgements/Export_4A_106_2025.html`) | not dropped by the net; scope ASK-SUVA (Q-06, Q-31) |
| T13 | "Suva" in the text but not a party | SR1 and SR2 exclude each other | SR2 fires, not SR1 |
| T14 | Same docket with two decisions | key = (docket, decision_date) | two records; export deduplicates by docket |
| T15 | BGE and its original ruling both present | two documents for one case | deduplicated on docket |
| T16 | French summary | must not be a translation; correct French legal vocabulary | generated from source; glossary terms; same paragraphs and consideration references as the German (Q-27); reviewer check |
| T17 | Explanation of a rejected ruling | "explain why selected, or not" | every ruling has a reason, citing the right signal and consideration |
| T18 | "Add another judgement" with a docket the pipeline dropped | the human recall safety net | full processing on demand, added to the table |
| T19 | bger.ch blocked (Incapsula page) | robustness | detected, back-off, fallback to HF/entscheidsuche, counted |
| T20 | Ruling missing from HF | robustness | fetched from bger.ch |
| T21 | Withdrawn ruling ("Dokument nicht gefunden") or corrected after publication | robustness | flagged, not processed as text |
| T22 | Empty or header-only text | input hygiene | refused before the call (`source_empty`) |
| T23 | Ruling containing a delimiter or instruction-like string | injection through data | treated as data; output unaffected |
| T24 | Input longer than the configured input budget (G4) | Keera answered up to 250k tokens on 27 Nov; the judges' endpoint may accept less | split by consideration, no truncation |
| T25 | Served model differs from requested | gateway aliasing seen in other projects | a non-Apertus served model is rejected and counted (G3); an `LLM_NAME` that names no Apertus model fails fast with a clear message (G3, E1); another Apertus v1.5 id of the allow-list is accepted, logged and counted (T26) |
| T26 | `LLM_NAME=swiss-ai/Apertus-v1.5-8B` (Hugging Face id form) on an endpoint that sends no `x-keera-model` header | the judges choose the model and its id form (template `README.md`: "name and version of the model"; D-032, Q-23) | run completes; served model accepted in either id form; missing header logged, not fatal; the 8B never excludes alone |
| T27 | Fresh clone as the template created it (`judgements/` and the pitch PDF present; no `data/private/`, no `data/derived/`, no cache). **Blocked by D-031** until it is settled (hard due Fri 22:00) | the judges' situation; the template asks the submission to "include all prerequisite files and definitions" and to run end to end (D-039) | the instructions in `technical_report.md` §6 run end to end with what D-031 lets us commit; every output labelled `LIVE` or `REPLAY` (D-032). While D-031 is open, a fresh clone has no replay artefacts: CI runs `make check` and the `make run` stages that need no Suva-derived artefact, and `data/derived/` stays git-ignored |
| T28 | Template layout | the template: "Keep the layout as it is: don't rename or move its files" (D-039, D-040) | every template file at its path; `judgements/` matches its SHA-256 manifest (`docs/SUVA_DATA.md` §1); the pitch PDF and `challenge_description.md` match their hashes (`tests/test_template_layout.py`, `docs/agents/platform.md`); `make check` fails otherwise |
| T29 | `Export_8C_176_2025 3.html` (a space and a suffix in the file name), the ordinal day ("1er") in the French title of 8C_330/2025, the suffix after the date in the Italian title of 9C_65/2025, and the other parser quirks of `docs/SUVA_DATA.md` §3 | real files in `judgements/` | parsed as 8C_176/2025, counted once, not as a duplicate; every title date parsed with an ordinal-tolerant pattern and no end anchor, and equal to the `aza://` date of its link (55 of 55); the parser re-derives the counts of `docs/SUVA_DATA.md` (60 list rows, 55 exports, 82 distinct Federal Court rulings) |
| T30 | Every docket of `judgements/` in the crawled populations | the template's "all judgements that have been summarised by a human should also be correctly identified" (Q-20); tests the crawl and the date definition (Q-02, D-050) | 100 % of the 59 listed Federal Court rulings in the decision-date population of their labelled quarter; every other docket found, or listed with its reason (a Q3/2025 ruling put online before 1 Oct 2025 is expected, and is then looked up in HF); the cantonal row reported as out of reach (Q-28); each gap explained |
| T31 | The D-051 output test (`tests/test_no_suva_personal_fields.py`): generated files against the fields dropped by D-051 | Suva's exports name their authors and the workbook links to Suva's intranet (D-051, Q-26) | runs on every file we write (`data/derived/`, `results/`, `expected/`, logs, `llm_calls`, caches, prompts, exports, UI pages, report). Forbidden values, read from `judgements/` at test time and written nowhere: the exact lines of each author section, and each full "given name + surname" pair in both orders, matched case-sensitively on word boundaries; each staff code only in its export form (a standalone upper-case token, or in parentheses, as in the author section); the intranet host and its path prefix. Job titles are not forbidden values: they are ordinary words in rulings, and D-051 drops the field at ingestion. On failure it reports the file and line, never the value |
| T32 | The 11 boundary dockets listed in D-050 (the single home of the list) | their publication dates settle most of D-050 from data | publication dates recorded; each one's quarter under both definitions reported to the lead (Q-02) |

## 3b. Smoke set (dataset DS7 of `docs/DATA.md` §10)

The 33 rulings of the team's gateway test on 27 Nov. A quick end-to-end check, run before every long or overnight run and after any change to a prompt, a parser or the client. It is not a calibration and not a result: never choose a threshold, a prompt or a variant on it, and never report it as a measurement.

- **With an export in `judgements/` (14):** 9C_65/2025 (it), 4A_106/2025 (de), 8C_607/2024 (fr), 8C_184/2025 (fr), 8C_508/2025 (fr), 8C_525/2025 (fr), 8C_348/2025 (fr), 8C_179/2025 (fr), 8C_531/2025 (de), 8C_172/2025 (fr), 8C_656/2024 (de), 8C_330/2025 (fr), 9C_382/2025 (de), 8C_517/2024 (fr).
- **Negatives from courts 8C, 9C and 9D (14):** 8C_358/2025 (it), 8C_603/2025 (it), 9C_317/2025 (de), 9C_186/2025 (de), 9C_481/2025 (de, tax), 9C_531/2025 (de, tax), 9C_64/2025 (fr), 8C_112/2025 (de), 8C_541/2024 (de), 8C_468/2025 (de), 9D_9/2025 (de), 8C_503/2025 (de), 9C_291/2025 (fr), 9C_435/2025 (fr).
- **Easy negatives (5):** 1C_550/2024 (de), 2C_470/2025 (de), 4A_510/2025 (de), 5A_49/2025 (de), 6B_776/2025 (fr).

Build: the docket list goes to `eval/smoke_set.txt`, without labels; texts come from DS3, labels from DS4 and DS5, into `data/derived/` while D-031 is open. Expected: 33 of 33 judged, 0 failed; the 5 easy negatives at the bottom of the ranking; the ranking AUC reported. Reference, one run without few-shot on 27 Nov (`docs/LESSONS.md` §2b): AUC 0.95 with the 70B's log-probability score, 0.86 with the 8B's. A large drop points first to a broken prompt, parser or label token. Some of these rulings are few-shot candidates: a smoke run may include them, a measurement never does (D-021 point 8).

## 4. Summaries

- **Internal hold-out (time split, stratified by style):** the internal test set is the 10 Q1/2026 exports plus the 13 German-language Q4/2025 exports (23 rulings, both styles); the 23 Q3/2025 exports and the 9 French-language Q4/2025 exports are the pool for examples and development. Write summaries of the 23 test rulings without showing their summaries to the model; compare after. Never put a ruling in both the prompt and the test. Report the results per style.
  - Count **55 independent summaries, not 110**: each export is one text in two languages. Evaluate German and French jointly per docket.
  - Q1/2026 alone holds one German-language export, too few for the majority case: this is why the 13 German-language Q4/2025 exports join the test set (`docs/SUVA_DATA.md` §5). Rule-statement and narrative results are reported apart.
  - Never use a text with a meaning-changing translation error as an example or a reference in that language (`docs/SUVA_DATA.md` §3); prefer the ruling-language side.
- **Deterministic graders:** every article, consideration, BGE and docket exists in the source; numbers, dates and amounts preserved; an outcome, when stated, matches the operative part; language right; length within a band `<to set>` from the 55 exports before measuring (D-053: while Q-08 is open, the exports set the length, not the deck's sample of about 300 words; medians and p25 to p75 in `docs/SUVA_DATA.md` §3); structure, graded per style (the style is Q-30; while open it follows the ruling's language, `docs/ARCHITECTURE.md` S6): every summary has the title line `BGer-Urteil <docket> vom <date>` / `Arrêt du TF <docket> du <date>`, as in the 55 exports; **rule-statement** style: the legal rule stated directly, with no outcome sentence and no consideration reference required; **narrative** style: facts, the rule with its consideration reference, the application, the outcome; **structure parity**: the same number of paragraphs and the same sequence of consideration references in German and French, as in Suva's examples (`docs/SUVA_DATA.md` §3; Q-27); no author line and no intranet link (D-051).
- **French independence:** generated from the source, not from the German text (pipeline check); glossary terms used; structure parity with the German (Q-27); a French-speaking reviewer reads a sample.
- **Human review:** a team member compares side by side with Suva's summary using a short rubric (facts right, issues complete, holdings right, references right, style), blind to which system produced which text when possible. Report the template's two criteria separately ("comparable to the human-generated summary in terms of style and legal precision", `challenge_description.md`): **legal precision** (facts right, issues complete, holdings right, references right) and **style** (Suva's house style, length, terms). Add a **structure parity** item: same paragraphs and consideration references in both languages (Q-27).
- **Optional judge:** open-weights, other family, criteria-based (met / partial / missing / contradicted / uncertain, each with a verbatim quote), label computed by code, κ on ~60 double-annotated items; otherwise human only.
- **Error taxonomy to track:** right outcome with wrong legal reasoning; added conditions that restrict a right; stricter criteria than the ruling states; wrong or invented reference.

## 5. Explanations

For a sample per class (selected, rejected by net, rejected by score): the explanation exists (100 % of rulings), cites signals that actually fired and a consideration that supports the key statement.

## 6. Usability: the Monday-morning script

Played in front of a Suva legal expert or mentor, timed:
1. Open the app: the week's rulings sorted by score; scores, dates, subject areas and German reasons visible.
2. Open the top ruling: original document link, signals with evidence, German and French summaries, verification status.
3. Sort and filter (score, date, court, language).
4. Open a rejected ruling: see why.
5. Disagree: mark a rejected ruling relevant; mark a selected one not relevant (bonus: watch the scores update).
6. Add another judgement by docket number: get score, reason and summaries.
7. Edit a summary sentence; the change is stored.

Checklist of the 5 explicit requirements: originals, sortable score, why relevant/not, both summaries, summarise additional judgements.

## 7. Gateway probe (first hour of the build)

`/models` and ids; `json_schema` strict with `additionalProperties:false`; `json_object`; `logprobs` and `top_logprobs` (decides S3); streaming; `x-keera-model` and `model` fields; 70B cold start; concurrency ramp 1, 2, 4, 8, 16 in a slot announced to the team (its scope, per key or per team, is unknown: Q-14); input size that triggers 504; 8B vs 70B identity on 20 greedy prompts (alert if > 90 % identical outputs); latency of a short triage call and a long summary call; 2 identical runs for noise. A first run of these items was made on 27 Nov, outside the repo, by the team's gateway test (`docs/LESSONS.md` §1, column "Ours"): the repo's probe reruns them with our client, then adds what is still unknown (16 concurrent calls in an announced slot, the night's behaviour, the judges' endpoint). Results go to `results/gateway_probe.json`, update the "Ours" column of `docs/LESSONS.md` §1, record the allow-list of served model ids used by the client (both id forms, G3), and feed the capacity floor. `make smoke-llm` runs it.

## 8. Results layout

`results/*.json` written by code only, aggregate numbers only when derived from Suva's data (D-031; while open, per-docket results that reveal Suva's labels go to `data/derived/`, git-ignored); `expected/` (repo root) holds what `make run` must reproduce (its Suva-derived parts follow D-031 too); `make claims` regenerates every number quoted in `README.md`, `technical_report.md`, `<TeamName>_Report.pdf` (our registered team name, no spaces; Q-22) and the deck.

The report's section 7 "Evaluation" (D-043, PROPOSED) is written from §2 to §4: the protocol, A0-kw and A0 to A4 out of quarter (both folds) with CIs per language and court, precision and hits at 30, recall on the must-hit subset, both date readings, the closed-world assumption, summary metrics, robustness. Section 6 "Reproducibility" gives the run instructions, hardware, runtime, seeds and the exact commit.
