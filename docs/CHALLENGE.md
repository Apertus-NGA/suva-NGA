# CHALLENGE: Suva, "Agentify Suva's case-law monitoring"

> **Status: v0 PROPOSAL (27 Nov 2026), updated after the official template was read.** Sources: the template's `challenge_description.md` (Suva's written challenge, 23 Nov; the template's README calls it the "Complete Challenge description incl. deliverables"), Suva's pitch deck (27 Nov 2026, 22 slides, also at the repo root), Suva's data in `judgements/` (`docs/SUVA_DATA.md`), the partner speech (noisy automatic transcript), statements of the Suva mentor reported by the team. The two texts differ on several points, and neither says it overrides the other (§3, §4, §10; questions Q-16 to Q-21 in `docs/DECISIONS.md` §3).
> The deck (with an enabled sensitivity label), Suva's relevance list and its 55 human summaries are in the organisers' public template, hence in our public repo (`judgements/` and the PDF at the root; D-040). This file **paraphrases** them. Whether we may copy or derive more is D-031 and Q-15. The author fields and intranet links in Suva's files are never reproduced (D-051).

## 1. In one sentence

Build an agent that, for rulings published on bger.ch between 1 April and 30 June 2026 (the deck's window and our default, D-009; the template says "the last 3 months", Q-16; which date defines a quarter is D-050), gives each one a relevance score for Suva with an explanation, writes a German and a French summary in Suva's style for the relevant ones, and presents everything in a UI for Suva's legal experts.

## 2. Users and job to be done

- **User:** a Suva legal expert, on a Monday morning. Suva is Switzerland's largest accident insurer; Federal Supreme Court rulings directly shape how it handles claims.
- **Today:** experts search bger.ch by hand, read every new ruling, write the summaries themselves. Hundreds of new rulings per month, two languages, hours of expert time every month.
- **Going forward:** the agent finds the relevant rulings; experts evaluate them, then validate and improve the generated summaries. Searching should no longer be part of their job.
- **The expert's reading pattern** (deck): read the facts, find the legal issue, follow the reasoning, extract the key statement, judge the relevance.
- **The real problem is trust.** Suva says the "nearly impossible part" is to convince its experts that every relevant decision was found and that the summaries meet their standard, adding "Trust us, we tried". Our answer must prove **exhaustiveness** (measured recall, nothing dropped silently) and **fidelity** (every statement tied to a consideration of the ruling).

## 3. The four steps (all mandatory)

| Step | What Suva asks | Notes |
|---|---|---|
| 01 Crawl | Pull 3 months of published rulings from the official website: April, May, June 2026. | The deck shows bger.ch's "Liste der Neuheiten" (daily list of newly published rulings). |
| 02 Triage | Score each ruling for relevance to Suva and explain why it was selected, **or not**. | Every ruling gets a score and a reason, including rejected ones. |
| 03 Summarise | German and French summaries in Suva's style. **The French is its own text, not a translation.** | The speech insists on correct French legal vocabulary. |
| 04 Present | A UI for legal experts: sources, sortable score, reasoning, both summaries, and "add another judgement". | "Judgement" = a Federal Supreme Court ruling, identified by its docket number. |

**Bonus** (not required): experts redefine what counts as relevant; experts shape the summaries to their standard; the system learns from every correction.

**The template's wording** (`challenge_description.md`, "Problem Description") describes the same four steps, with these differences:
- step 1: "search for available publications from the last 3 months" (the window: Q-16, D-009, D-050);
- step 2: "key words, i.e. Suva or Accident + use context from provided summaries": a keyword baseline (variant A0-kw, `docs/EVAL.md` §2) and Suva's 55 summaries as context for relevance, not only for style (D-021);
- step 3: "according to style, structure and language in the provided summary examples", and "a German and a French version of the summary (not a simple translation) taking specific vocabulary into account" (§8; Q-27);
- step 4 is nearly word for word the deck's slide 21 (the deck adds "and appealing"; §9);
- step 5: "Bonus: improve and extend the 4 steps to provide a better customer experience" (broader than the deck's bonus).

Its introduction also describes prioritising rulings "in relation to the specific case" and storing all summaries in "a central, searchable and query-enabled knowledge base". Its numbered steps and criteria do not mention either (Q-21; D-016, D-033). Its "Main Objective" puts the summaries first: "Preparation of a legally and stylistically accurate summary of selected relevant Federal Court judgements and presentation in UI".

## 4. How we are scored

| Axis | Measure | Who | What we know |
|---|---|---|---|
| Recall ("hit score") | Recall and **F2** of our list of relevant Q2/2026 rulings against Suva's hidden list | Suva, automatic | The deck asks for a plain list of docket numbers: `8C_691/2024, 9C_612/2025, …`. A ranked list with scores may be needed (D-046, Q-18). Which date defines Q2/2026: D-050. |
| Top 5 ("quality score") | Our summaries of the rulings behind Suva's June 2026 summaries, against those hidden human summaries | Suva's on-site team and a legal expert | "Convince our legal expert". Slide 20 dates Suva's summaries, not the rulings: by Suva's 17 to 76 day lag, they cover rulings decided from about mid-March to mid-June 2026 (our reading, D-047; Q-17 asks). Who picks the 5 is unknown (Q-01); the template says our top 10 (Q-17, D-047). |
| Overall product | Usability of the prototype | Suva | "Convince us with usability". |

F2 = 5·P·R / (4·P + R). Recall weighs much more than precision, but including everything collapses precision and therefore F2: a calibrated threshold is needed.

The table above is the deck's version. **The template's version differs.** Suva's scoring, as its two texts state it; neither says it overrides the other, and both stand until Suva answers:

| | Deck (27 Nov, slides 18-21) | Template `challenge_description.md` (23 Nov) |
|---|---|---|
| Finding rulings ("hit score") | "Recall / Hit score: Did you find all the relevant court judgements?"; recall and F2 on our list of Q2/2026 rulings | "Your 30 high scored relevant court judgements are really relevant in the view of Suva's legal experts (provides a clear hit score)"; "(you didn't miss anything relevant)" |
| Summaries ("quality score") | "Top 5 / Quality score: Are your top summaries from June 2026 accurate?"; checked against Suva's hold-out of summaries published in June 2026 (slide 20; which rulings: D-047) | "Suva's legal specialists qualify your top 10 highly relevant summaries as accurate according to the provided examples and to a hold-out set of summaries not provided to the hacking team" |
| Success criteria | none stated | "The summary should be comparable to the human-generated summary in terms of style and legal precision. Furthermore, all judgements that have been summarised by a human should also be correctly identified by the prototype. Any additional summaries must be correctly identified in a justifiable manner." |
| Product | "Overall product … convince us with usability" | the UI is an expected output; no usability criterion |
| Bonus | redefine relevance; customise summaries; learn from corrections | "Project/Code is easy to transfer to Azure"; "improve and extend the 4 steps to provide a better customer experience" |

Questions: Q-17 (top 10 or Top 5), Q-18 (top 30 or recall/F2), Q-19 (Azure), Q-20 (summarised rulings), Q-11 (how the axes combine), Q-16 and D-050 (which window, and which date defines it). Working assumptions while open: D-046 (a ranked list with scores, the F2 threshold and the top-30 cut marked), D-047 (our top 10 summaries first, then the selected rulings behind Suva's June 2026 summaries), D-049 (a "Transfer to Azure" paragraph in the report).

What the template's success criteria add for the build: while Q-20 is open, every ruling of the **must-hit subset** must be identified by our triage, and recall on this subset is reported apart (`docs/EVAL.md` §2). The subset is defined once, in `docs/GLOSSARY.md`: the rulings of a labelled quarter that Suva summarised, 22 in Q4/2025 and 10 in Q1/2026; the 23 Q3/2025 exports are a population check (T30), not a must-hit. Any extra ruling we summarise needs an explanation a lawyer accepts (golden rule G5).

How these axes combine with each other and with the event jury is not stated (Q-11).

## 5. Event rules that constrain the build

- **Models:** Apertus 1.5 performs the core AI task. At runtime only Apertus plus open-weights models for supporting tasks (embeddings, OCR, reranking). No closed model or proprietary AI API at runtime. Evaluation judges may be open-weights (E4); ours are, by our choice. Deployable on-premise, air-gapped or on a sovereign Swiss cloud. Every model used in development and at runtime is listed with version and role (`MODELS.md`). Model ids, in the template's Hugging Face form and the gateway form: `MODELS.md` §1; the template says Apertus is "accessed via the CSCS / Keera Gateway".
- **Repo:** <https://github.com/Apertus-NGA/suva-NGA>, created with "Use this template", public and kept public; template files never renamed or moved (D-039); never deleted (our rule, D-044); Suva's files never edited (our rule, D-040); code Apache-2.0, report CC-BY-4.0 (D-041; scope: Q-24). All template rules: `docs/EVENT.md` §3.
- **Run:** the project must "run end-to-end when judges try to run it", with the instructions **in `technical_report.md`** (template `README.md`), configured through `LLM_NAME` ("name and version of the model"), `LLM_BASE_URL`, `LLM_API_KEY`. `make run` in Docker is our convention (D-042). We keep `data/` under 100 MB (our rule: GitHub refuses files over 100 MB). Whether a run calls Apertus live or may replay recorded answers is open (D-032, Q-14, Q-23).
- **Submission** on sprintd before **Saturday 28 Nov 2026, 14:30** (event guide: no extension, one per team, a draft is not a submission): repo URL, report PDF (max 6 pages **without references**, with a mandatory "Target architecture" section; also committed at the root as `<TeamName>_Report.pdf`, with our registered team name, no spaces, Q-22), video URL (max 2 min; also in the report's **Demo** field), deck PDF (max 10 slides). The event guide also mentions a ZIP and one slide on exactly how Apertus is used (Q-22).
- **Pitch** to Suva Saturday 15:00: 7 minutes plus 2 minutes of questions. Finalists announced 17:30 (top 6 per the event guide, top 3 per an organiser e-mail: to check).
- **Event jury** (event guide; not in the template; 6 criteria, 0 to 5 each): purposeful use of AI, technical rigour, value/cost/scalability, sovereign deployability (no external service = max), implementation feasibility, pitch.

## 6. Data by period

| Period | Relevant list | Human summaries | Our use |
|---|---|---|---|
| Q3/2025 | not provided | provided: 23 (rulings in no list) | summaries: examples and development; triage: development only (no recall can be measured without a list); crawl: a population check (T30) |
| Q4/2025 | provided: 28 rulings | provided: 22 | triage: one labelled fold; summaries: the 13 German-language exports join the internal test set, the 9 French-language ones are examples |
| Q1/2026 | provided: 32 rows (31 Federal Court rulings, 1 cantonal decision) | provided: 10 | triage: the other labelled fold (the F2 threshold is chosen on one fold and reported on the other, then the folds swap: D-021 point 5); summaries: all 10 exports in the internal test set |
| Q2/2026 (1 Apr to 30 Jun) | **hidden** | none | the recall test |
| Suva's June 2026 summaries (rulings decided from about mid-March to mid-June 2026, D-047) | none | **hidden** | the quality test |

Suva's lists hold **positives only**: negatives exist only under the closed-world assumption (Q-04). Suva's quarters follow the **decision** date in every dated row, while the deck defines Q2/2026 by publication (D-009); which date defines a quarter is open (D-050). The 28 listed rulings without a summary are all German-language (Q-29). How the two folds and the summary test set are used: D-021 point 5, `docs/EVAL.md` §2 and `docs/SUVA_DATA.md` §5 (working assumptions).

Ruling texts come from bger.ch ("all data is on a website"). Suva's list and summaries are in the template's `judgements/` (uploaded by the organisers on 25 Nov): the relevance list `BG_Urteile_2025_Q4_2026_Q1.xlsx` and 55 summary exports, each with a German and a French text. Counts, formats and quirks: `docs/SUVA_DATA.md`. Sources and licences: `docs/DATA.md`.

## 7. What "relevant for Suva" means

A ruling is relevant when it **can change how Suva handles its files**:
- it sets or clarifies a rule Suva applies (example in the deck: the Court holds that a disability-insurance provision does not apply by analogy in accident insurance, so every pension calculation follows);
- Suva is a party, especially when it loses (it must correct its practice);
- another accident insurer under the UVG/LAA is a party (the case law applies to Suva the same way);
- it will carry weight as precedent: destined for the official reports (BGE/ATF), or decided by five judges.

It is **not** relevant when it does not touch Suva's business (criminal, tax, family law), or touches it without adding anything (inadmissibility for a missed deadline, routine application of settled law, a three-page ruling). Relevance is about **impact on practice**, not topic. Disability-insurance (IV/AI) rulings in court 9C can matter because accident and disability insurance share notions such as the income with disability. Suva's own examples confirm a wide scope: three 9C rulings and one civil-law **4A** ruling (`judgements/Export_4A_106_2025.html`, private daily-allowance insurance); at least 7 of the 55 summaries concern disability insurance; only 20 of 55 name Suva (`docs/SUVA_DATA.md` §3). Whether relevance goes beyond accident insurance is Q-31; meanwhile, everything Suva summarised is in scope, and we never require "Suva" in the text or an `8C_` prefix.

**The deck's 9 "base rules" are examples, not hard criteria** (Suva mentor, 27 Nov). Suva published them with their weights blurred. Paraphrased, and cited in this kit as **SR1 to SR9**:
1. Suva (Suva / CNA / INSAI) is a party.
2. Suva is mentioned in the ruling without being a party.
3. The subject area is accident or military insurance.
4. Another UVG insurer is a party (the case law applies the same).
5. Destined for publication (BGE candidate, star in the Neuheiten list).
6. Five-judge bench (question of principle).
7. Core accident-insurance themes in the text (causality, notion of accident, pension, integrity compensation, expert report…).
8. Detailed considerations (ruling longer than 25,000 characters).
9. Appeal (partly) upheld in a Suva or accident-insurance case.

We implement them as **signals** computed by code, and learn relevance from Suva's labelled quarters (the deck: "learn the patterns that distinguish these judgments from irrelevant ones"; the labels are in `judgements/`, positives only), through few-shot examples, a trained combination, or both: an open question (`docs/DECISIONS.md` D-021). The template adds a keyword baseline ("Suva or Accident") and Suva's summaries as context: variant A0-kw and D-021 point 3. See `docs/ARCHITECTURE.md`.

## 8. Summary style (Suva's 55 examples in `judgements/`; first read on the deck's sample)

**The evidence base is now Suva's 55 summary exports**, measured in `docs/SUVA_DATA.md` §3. The summary role builds `docs/summary_style.md` from them (`docs/agents/summarise.md` step 1). What they show:
- **Length:** median 177 words in German and 226 in French, median 3 paragraphs; ranges and quartiles per language are in `docs/SUVA_DATA.md` §3 (the single home of these statistics). The deck's sample (about 300 words) is longer than most of them. While Q-08 is open, the target length follows the exports (D-053).
- **Two house styles:** the **rule-statement style** states the legal rule directly, almost never with a consideration reference; the **narrative style** gives the facts, the rule the Court recalled with its `E.` / `consid.` reference, the application to the case, and an outcome sentence. For a German-language ruling, only the rule-statement style exists in the set. The recent Q1/2026 exports are mostly narrative, but they cover only 1 of the 22 German-language Q1/2026 rulings: "most recent" is not evidence of a change of style. Which style and fields Suva's experts expect is Q-30. While open, style follows the ruling's language: German-language ruling, rule-statement style (as in all 22 German-language examples); French or Italian ruling, narrative style. Both texts of one ruling follow the same style; `E.` in German, `consid.` in French.
- **German and French are parallel texts:** the same number of paragraphs in 54 of 55 files, the same consideration references in 55 of 55. While Q-27 is open, our two versions do the same, with the right legal term in each language and no literal translation.
- **Format:** a title line in the ruling's language, the German text, the French text, the bger.ch link; plain paragraphs, no headings or lists. No summary cites a precedent (no BGE/ATF volume, no other docket).
- **Reference forms:** French almost always `consid.` (one file writes "voir point"); German mixes `E.`, `Erw.` and `Erwägung`. Code renders references (D-037); the form is Q-30.
- **The template's criterion:** "comparable to the human-generated summary in terms of style and legal precision".

The deck shows one complete German summary (about 300 words) of a ruling destined for publication, on slide 13 of the deck at the repo root. Observable features (where they differ from the 55 exports, the exports win while Q-08 and Q-30 are open: no capitalised header and no two-part title unless Suva asks for them):
- **Header** in French and in capitals: "ARRÊT DU TF <docket> DU <date> (DESTINÉ À PUBLICATION AUX ATF)", above a German text (is the header common to both languages? Q-08). Suva's exports open instead with a title line in the ruling's language.
- **Two-part title** joined by a dash: the theme, then the solution.
- **Paragraph 1, context:** publication status, ruling type (accident-insurance ruling), insurer in brackets, bench composition, quantified facts (year of birth, date and type of accident, rates), then "the disputed issues were…" with consideration references.
- **One paragraph per legal issue**, opening "On…", stating the Court's solution, consideration reference in brackets at the end of the sentence (`E. 5.1`), norms in exact format (`Art. 20 Abs. 2ter UVG`), case law and legislative materials cited.
- **One closing sentence** with the outcome.
- **Tenses:** past for facts and outcome, present for legal holdings.
- **No "relevance for Suva" paragraph:** relevance lives in the UI's reasoning column.
- No French sample in the deck: French conventions come from the French texts of the 55 exports in `judgements/` (`docs/SUVA_DATA.md` §3).

Every article, consideration and BGE number in a summary must exist in the source; a wrong one is visible at once to a lawyer.

## 9. UI expectations (deck mock-up and slide "Overall product")

A table sorted by relevance, descending, with columns:
- **RELEVANZ:** score out of 100 with a bar (mock-up values 90 to 98);
- **URTEIL:** docket number;
- **DATUM:** a date. Decision or publication is open (D-034). While open: the decision date, labelled as such, as in the deck's mock-up (slide 14 dates 8C_317/2025 06.08.2026, the decision date in the title of slide 13's sample); the publication date on hover and on the ruling page. Suva's own list groups rulings by decision date (D-050);
- **GEGENSTAND:** the subject area from the Neuheiten list, **in the ruling's language**, Italian included;
- **BEGRÜNDUNG DER RELEVANZ:** a short reason, **always in German** in the mock-up, following a visible pattern: type (Suva case, leading case), outcome (upheld, remanded), key statement, practical import ("directly relevant to practice").

Blurred badges appear under the docket and subject columns (probably fired rules or outcome). A high score does not require Suva as a party: the top row is a five-judge BGE candidate with another insurer.

Explicit requirements (slide 21: "a clear and appealing UI"; step 4 of the template's `challenge_description.md` repeats it nearly word for word, without "and appealing"; the deck scores usability, so "appealing" stays a must-have): original judgement documents, sortable relevance score, explanation why relevant or not, summary in both languages, possibility to summarise additional judgements.

## 10. Scope notes

- **Published = put online.** The Neuheiten page states that its date is not the decision date. The lag the team observed during preparation is 9 days to about 10 weeks (an observation before the event, not a systematic measurement; the deck's capture of the list shows 6 to 7 weeks); the crawl measures the real distribution (`docs/agents/crawl.md`). The deck says "published", so the delivered list follows the publication date by default (D-009, D-052). But Suva's own list dates its quarters by **decision** date (52 of 52 dated rows, `docs/SUVA_DATA.md` §4), so which date defines a quarter is open (D-050, Q-02). If the 9-day minimum holds, the four summarised rulings decided on 23 to 26 Sep 2025 went online in October yet are absent from Suva's Q4 list, and the two Q1-labelled rulings decided on 27 March went online in April, so Suva's labels must follow decision dates; D-050's boundary check confirms the lag on those dockets. While open: every ruling carries its decision date and its publication date; the crawl reads the Neuheiten pages of every day from 1 Oct 2025 to 15 Sep 2026 (the end date is a parameter: a ruling decided on 30 June can go online in early September), so each quarter is complete under both definitions; the labelled quarters are evaluated on decision-date populations, with the publication-date reading also reported; the export flags every ruling under both definitions. The template's "the last 3 months" is a separate question (Q-16).
- **Not only court 8C.** The deck's example list contains a 9C ruling; a Suva mention can appear in any court (Suva recourse actions exist in civil-law court 4A). Suva's list holds 53 rulings of 8C, 6 of 9C and one cantonal decision, which a Federal Court crawl cannot find (Q-28); its summaries add a 4A ruling (Q-06).
- **Italian rulings are in the triage** (the mock-up shows one), even though summaries are asked in German and French only. Suva summarised two Italian-language rulings, in German and French (`docs/SUVA_DATA.md` §3; Q-07).
- **Out of scope:** finding case law for a new claim file (a research product, not monitoring). It can be a vision slide in the pitch. The template's introduction mentions prioritising "in relation to the specific case" and a "searchable and query-enabled knowledge base": Q-21 (D-016, D-033).

## 11. Questions for Suva

The ranked list, with what changes with each answer, what to assume meanwhile and who asked when, is kept in one place: `docs/DECISIONS.md` §3 (Q-01 to Q-31).
