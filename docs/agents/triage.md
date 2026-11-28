# Role brief: TRIAGE (signals, net, Apertus judgement, score, explanation)

> **Status: v0 PROPOSAL (27 Nov 2026), updated after the template was read.** Owner: `<handle>`. Read `AGENTS.md`, `docs/CHALLENGE.md` §7, `docs/SUVA_DATA.md` §2, §4-5 and `docs/ARCHITECTURE.md` §2-3 first. The triage design is an **OPEN** question in eight points (D-021): its options and reasoning are in `docs/DECISIONS.md` §2. Build behind interfaces that keep the alternatives open, and start your plan by stating your recommendation on each point.

## Mission
Give every ruling of a candidate population (a scored or labelled window under either date definition, D-050) a relevance score for Suva and a German explanation, and select the list that maximises F2 on held-out labelled data. A crawled ruling outside every window gets the reason code `out_of_window`, with no LLM call (G5). Also rank: Suva may check our 30 highest-scored rulings rather than compute F2 on a list (the template's "hit score"; D-046, OPEN). While open, deliver both: one ranked list with every ruling's score, the F2 threshold and the top-30 cut marked.

## You own
`src/signals/`, `src/triage/`, `prompts/triage_*`, the decision records, the delivered list and the ranked export (D-046).

Layer 1, the first filter before Apertus (`src/layer1/`), is described in `docs/LAYER1.md`. Every ruling it drops keeps its reason code and the outcome of every rule of its version (`triage.v_layer1_ledger`, D-081). Every row of the source file outside every window is recorded as `OUT_OF_WINDOW` in `corpus.ingest_exclusion` (D-081). Its open points are D-084.

## Inputs
- Ruling records from crawl, each with its decision date and its publication date (D-050).
- Suva's relevance list `judgements/BG_Urteile_2025_Q4_2026_Q1.xlsx` (template, read-only, D-040), read through the S0 parser of the crawl role (`docs/agents/crawl.md`), which keeps only the fields D-051 allows. It holds 28 positives for Q4/2025 and 31 Federal Court positives for Q1/2026, plus one cantonal row that a Federal Court crawl cannot reach (Q-28). Counts and quirks: `docs/SUVA_DATA.md` §2.
- The labels are **positives only**: no negatives, no scores. Negatives exist only under the closed-world assumption of Q-04: every other Federal Court ruling of the quarter. State that assumption wherever a precision is reported.
- The populations of the labelled quarters from crawl, under both date definitions. Suva's labels follow the decision date in every dated row (`docs/SUVA_DATA.md` §2); which date defines a quarter is D-050 (OPEN). While open: fit and measure on the decision-date populations, and also report the publication-date reading.
- Suva's 55 summaries in `judgements/` as context (the template's step 2: "key words, i.e. Suva or Accident + use context from provided summaries"). The 23 summarised rulings decided in Q3/2025 are in no list: use them for development only; no recall is measured on them (Q-29). They are a population check (T30), not a must-hit.
- Derived files (labels per docket, few-shot digests, prompts that contain Suva's text) go to `data/derived/` (git-ignored) while D-031 is open.

## Outputs
- Signals record per ruling (value + evidence span).
- Net decision per ruling (`kept` or `reason_code`).
- Apertus result per candidate (probability or label, key statement, consideration ids).
- Decision record: score 0-100, selected, threshold version, German explanation, signals fired, model and prompt versions.
- `results/triage_validation.json` (validation, both folds; aggregates only while D-031 is open, per-docket rows in `data/derived/`) and the Q2 list `results/relevant_q2_2026.txt` in Suva's format: `8C_691/2024, 9C_612/2025, …` (dedupe by docket). Which Q2 set it covers follows Q-02, with D-009's publication-date window as the default while D-050 is open (D-052).
- While D-046 is open, the ranked export `results/ranked_q2_2026.csv`: docket, score, rank, above the F2 threshold (yes/no), in our top 30 (yes/no), decision date, publication date, in Q2 by publication date (yes/no), in Q2 by decision date (yes/no). Every Q2 candidate of either definition is in it (D-050), and the plain list above is derived from it.

## Steps
The scoring design is open (D-021, D-022). Steps 1 to 3 are needed by every option; steps 4 to 6 lay out the options to compare, not a chosen path.

1. **Signals (code only):** the 9 example rules and neighbours (`docs/ARCHITECTURE.md` §2 S1). Lexicons in DE, FR and IT. Each signal stores the span that proves it. Unit tests per language.
2. **Baselines first:** A0-kw (the template's keyword baseline, "Suva or Accident": Suva/CNA/INSAI and Unfall/accident/infortunio, in DE, FR and IT), A0 rules-only and A1 signals-only on both labelled quarters (protocol in `docs/EVAL.md` §2). These numbers exist before any Apertus call and are the yardstick for everything after.
3. **Your plan's first section:** your recommendation on each point of D-021, on D-022 and on D-046 (what the hit score measures), with the reason and what it changes; raise them with the team before building the scorer.
4. **Net (if any, D-021 point 2):** the definition formulated so far drops a ruling only if it has no Suva/CNA/INSAI mention, no accident or military insurance term, and a subject area that is not accident or military insurance. Build it as a signal first; if used as a net, write the reason code, report the count, hand-check a sample of 30, and measure its cost in recall (A4).
5. **Apertus judgement on candidates (D-021 points 3 and 4):** the whole ruling or a reduced one (parties, subject, bench, main considerations, operative part), under the input budget of G4 (Keera answered up to 250,000 tokens on 27 Nov, so size is no longer the constraint; cost and focus are); few-shot from labelled examples (short digests or extracts, balanced positives and negatives, never the ruling being judged; negatives from the closed-world populations, Q-04; never an author field or intranet link, D-051). A question such as "does this ruling change how an accident insurer handles claims?" asked with a one-token label (Ja/Nein or A/B; "Oui" is two tokens), first and outside JSON, on `/chat/completions`; with `top_logprobs`, score = lp(Ja) − lp(Nein) with `max_tokens 1`, otherwise the label. The few-shot pool covers IV and ATSG cases: the 4 positives both models missed in the 27 Nov pilot were such cases (`docs/LESSONS.md` §2b, Q-31). Then (same or second call) the key statement and the ids of supporting considerations.
6. **Score and threshold (D-021 points 1 and 5):** compare option A (Apertus judgement as the score) and option B (a learned combination, for example logistic regression over signals + Apertus score) on both labelled quarters with CIs, alongside A0-kw, A0 and A1; choose the F2 threshold by the cross-quarter protocol (rules below; `docs/EVAL.md` §2), freeze it, then predict Q2. On each labelled quarter, report precision and hits at 30 next to recall and F2 (D-046), and recall on the must-hit subset, at the threshold and in the top 30 (defined once in `docs/GLOSSARY.md`: 22 rulings in Q4/2025, 10 in Q1/2026; Q-20).
7. **Explanation in German** for every ruling (wording open, D-021 point 6). The mock-up's pattern: type ("Suva-Fall", "Leitentscheid", "UV-Fall eines anderen Versicherers"), outcome ("mit Gutheissung", "Rückweisung"), key statement, practical import, signals fired. For a dropped ruling: the net reason; for a low score: the main missing signals.
8. **Corrections loop (bonus):** an expert's relevance flip becomes a label; `make refit` reruns the scoring (new few-shot pool under option A, refit under option B).

## Rules specific to this role
- Recall first: no exclusion without a counted reason; never on docket prefix alone; the 8B never excludes alone.
- Scope while Q-31 is open: everything Suva summarised is in scope. Besides accident insurance (UVG), that is disability insurance (IV), ATSG procedure and private insurance (VVG, court 4A). Signals, few-shot and explanations cover them. Never require the word "Suva" in the text (35 of Suva's 55 summaries never name Suva) or an `8C_` prefix.
- A model's stated confidence is not a score. Use log-probabilities, or a label (possibly combined with signals).
- Apertus picks consideration ids from the enum; the code copies the text and builds the citation.
- A "relevant" label without evidence ids is downgraded to "uncertain" by code.
- Example rules SR1 and SR2 exclude each other; the parties block decides who is a party.
- Cross-quarter threshold (D-021 points 5 and 8, `docs/EVAL.md` §2): choose the F2 threshold on one labelled quarter (from out-of-fold scores under option B, directly under option A), report on the other quarter at that frozen threshold, then swap. The headline is the cross-quarter result, with both folds shown. The final refit on Q4/2025 + Q1/2026 uses the threshold policy of D-021 point 8, and the threshold is frozen before Q2 predictions.
- The top 30 is cut by score, never edited by hand. Every ruling of the ranked export has a rank and an explanation, even below the threshold (G5).
- Report per language and per court; report the number of rulings an expert must read per week at the chosen threshold.
- Prompts, explanations and logs never contain an author field, staff code or intranet link from `judgements/` (D-051).

## Known risks
- Few positives per quarter (28 in Q4/2025, 31 Federal Court ones in Q1/2026): wide intervals; say so.
- The labels are positives only. If Suva's lists are not complete (Q-04), some "negatives" are unlabelled positives, and precision and F2 are understated: say so.
- If Suva's quarters follow decision dates (D-050), negatives built from publication-date populations are wrong, and the reverse. Build both populations while open, and report both readings.
- Suva's list holds 53 rulings of court 8C, 6 of 9C and 1 cantonal decision; Suva's summaries also include one civil-law 4A ruling (`judgements/Export_4A_106_2025.html`) and two Italian-language rulings (Q-06, Q-07). Courts outside 8C and Italian rulings are in scope in practice: keep every court and language in the candidate set.
- The cantonal row cannot be found by a Federal Court crawl: recall on Q1/2026 is measured on its 31 Federal Court positives, and the row is reported as out of reach (Q-28).
- `top_logprobs` works on Keera's `/chat/completions` (measured 27 Nov) but may not on the judges' endpoint: fall back to labels (D-021 point 4).
- The 27 Nov pilot (`docs/LESSONS.md` §2b, 33 rulings, no few-shot): the 70B's log-probability score reached AUC 0.95 but needed a threshold near 5·10⁻⁵ to find all positives; the values are extreme, so the score is a ranking to calibrate on Suva's lists. It is a probe, not a calibration.
- When the prompt names Suva, the 70B may attribute acts to Suva where another insurer is the party. An explanation says "Suva-Fall" only if the parties block names Suva (verifier check 6, `docs/ARCHITECTURE.md` S7).
- Court 9C also decides tax cases: a 9C prefix is not a sign of social insurance (signals, net).

## Done when
Cross-quarter metrics for A0-kw and A0-A4 with CIs in `results/`, both folds shown (recall and F2 at the threshold, precision and hits at 30, recall on the must-hit subset; on the decision-date populations, with the publication-date reading also reported), and the D-021 answer they support recorded in `docs/DECISIONS.md`; Q2 list and ranked export produced, with both date flags (D-046, D-050); every Q2 ruling has a decision record with a German explanation; `make run` replays it.
