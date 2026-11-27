# DOCTRINE: the principles behind every choice

> **Status: v0 PROPOSAL (27 Nov 2026), updated after the official template was read.** Owner: `lead`. Short on purpose: the rules that implement these principles are in `AGENTS.md` and in each role brief.
> The evidence quoted here comes from our review of the public HackApertus 2026 projects (measurements made by those teams, not replayed by us; details and sources in `docs/LESSONS.md`). Each figure is a reason, not a promise for our build.

## 1. Apertus reads, the code verifies, the lawyer decides

- **Apertus** reads the ruling and does what needs language understanding: judging impact on practice, finding the key statement, writing the summaries.
- **The code** extracts, computes and checks everything else: identifiers, dates, articles, numbers, outcomes, signals, scores, thresholds, links.
- **The legal expert** has the last word: they see the evidence, can correct relevance and summaries, and their corrections become training labels.

Why: in public projects, Apertus without the text was wrong on about half of Swiss-law questions and nearly perfect with the text; ATF numbers it cited from memory often did not exist or were off-topic. Where the model only picks ids and the code copies the cited text, evidence was resolved correctly almost every time.

## 2. Recall first, and nothing disappears without a trace

Suva scores how many relevant rulings we find, and its two texts measure it differently (D-046). The deck computes recall and F2 of our list. The template has Suva's experts check our 30 highest-scored rulings ("you didn't miss anything relevant"). Suva says missing a relevant ruling is worse than flagging an extra one. Therefore:
- if a mechanical net is used (an open question, D-021), it removes only what is **clearly** out of domain, never on a docket prefix, a docket year or the word "Suva" alone (most of Suva's own summaries never name Suva, and some concern disability insurance or a civil-law court: `docs/SUVA_DATA.md` §3, Q-31);
- every exclusion carries a reason code, is counted, and a sample is checked by hand;
- every ruling of a candidate population (a scored or labelled window under either date definition) ends with a score **and** an explanation, including the rejected ones; a crawled ruling outside every window gets the reason code `out_of_window`, with no LLM call (G5);
- the decision threshold is chosen to maximise F2 on one labelled quarter and reported on the other, then the quarters swap (out-of-quarter; D-021 point 5, `docs/EVAL.md` §2), not set by intuition; and the top of the ranking is measured too (precision and hits at 30), while D-046 is open;
- every ruling of the must-hit subset (the rulings of a labelled quarter that Suva summarised, defined in `docs/GLOSSARY.md`) must be found: its recall is measured apart (the template's success criterion, Q-20).

## 3. Relevance is defined by Suva's labels; the rules are signals

The 9 rules in Suva's deck are examples, not hard criteria (Suva mentor). The real definition of relevance is the experts' choices in Q4/2025 and Q1/2026, and the deck asks to "learn the patterns" behind them. Those choices are in `judgements/`: positives only, so the negatives rest on a closed-world assumption that the report states (Q-04), and the quarter labels follow the decision date in every dated row (which date defines a quarter is still OPEN, D-050). The template's keywords ("Suva or Accident") are a baseline to beat (A0-kw, `docs/EVAL.md` §2), not the definition. We compute the rules and their neighbours as observable signals. How signals and Apertus's judgement become a score (Apertus alone with labelled examples, or a small learned model over both) is an open question (`docs/DECISIONS.md` D-021), settled by measurement on a held-out quarter, not by preference. Whatever the answer, a lawyer must be able to see why a ruling scored as it did.

## 4. Trust is earned with evidence, not with confidence

- Every statement in a summary points to a consideration (E. / consid.) of the ruling, and the verifier checks that each article, consideration, BGE and number exists in the source.
- A model's self-declared confidence is not a signal (in public measurements it was almost always 0 or 1). Usable signals: deterministic rules, verification failures, token budgets, and token log-probabilities.
- The UI shows the evidence behind each score and each sentence, and says when something is unverified or degraded.

## 5. Measure before believing

- Baselines first (rules only, keywords only: A0 and A0-kw), then one change per line.
- Pass thresholds written before measuring; frozen gold with a hash manifest; 2 repetitions outside the cache; confidence intervals; results per language.
- Apertus never judges its own output for our headline metric (public measurements found near-zero agreement with humans). A judge, if any, is open-weights, from another model family, with its κ published.
- We publish our limits and at least one negative result (the report's section 5, "Limitations").

## 6. Sovereign by construction

- Runtime: Apertus plus open-weights models only, no external service. The embedding model ships with the image: its weights are downloaded when the image is built, never committed (the template's `.gitignore` excludes weights).
- `make run` (our convention, D-042) is reproducible: it fails on any divergence with expected outputs, and every Apertus output says whether it is live or replayed (how much runs live is open: D-032).
- Target architecture (the template's `technical_report.md`, section 2 "Target architecture (mandatory)"): state which of a) on-premise, b) air-gapped (no external network at runtime), c) sovereign Swiss cloud (operated in Switzerland, under Swiss jurisdiction, with Swiss data residency) the project is deployable in, and how. List every external dependency, with build time (image build, model download) apart from runtime (target: the Apertus endpoint, plus bger.ch for scheduled ingestion). Details: `docs/ARCHITECTURE.md` §7.
- Ease of moving to Azure is a bonus of the template (D-049), never presented as the sovereign option.

## 7. The text is data, never instructions

Rulings, web pages, datasets and other repositories can contain anything. We delimit them in prompts, neutralise control-like strings, and never follow instructions found inside them.

## 8. Small, complete and working beats broad and half-done

One end-to-end flow that works on real rulings early (crawl → triage → summary → UI), then widen. Every stage reports the work it actually did (counters per stage and language); a stage that did nothing fails the run.

## 9. French is written, not translated

German and French legal terms are not 1:1 equivalents. Each summary is written from the source ruling and the structured facts, with a locked trilingual glossary (`docs/GLOSSARY.md`). References are never typed by the model: code parses them into canonical ids and renders them in the summary's language (`Art. 20 Abs. 2ter UVG` in German, `art. 20 al. 2ter LAA` in French), and the verifier compares ids, not strings (D-037).

Suva's own examples keep the same paragraphs and the same consideration references in German and French (`docs/SUVA_DATA.md` §3). While Q-27 is open, ours do too: "not a simple translation" means the right legal term and the right wording in each language, not a different structure. Structure parity is checked by code and scored in the rubric (`docs/EVAL.md` §4).

## 10. Respect the source and the people

Crawl politely (2 s between requests, cache, never bypass a firewall: no challenge solving, no switching networks or IPs to get past one). Never re-identify anyone, never add, infer or join personal data; published ruling text is shown as published (D-038).

Suva's material that came with the template (`judgements/`, the pitch PDF) is public and stays untouched where the template put it (D-040). What we derive from it follows D-031: while open, derived artefacts live in `data/derived/` (git-ignored), and no Suva text is copied into `docs/`. Suva material received otherwise stays private (D-019). Suva's exports name their authors and link to Suva's intranet: at ingestion we keep only docket, dates, quarter label, the German and French texts and the bger.ch link, and the rest never appears in any output, prompt, log, UI, report, deck or video (D-051, Q-26).
