# Role brief: PITCH, report, video and submission

> **Status: v0 PROPOSAL (27 Nov 2026), updated after the template was read.** Owner: `<handle>` (pitch spoken by `<handle>` and/or `<handle>`, in English, D-003). Read `AGENTS.md`, `docs/EVENT.md` §3 (what the template imposes), `docs/CHALLENGE.md` §4-5, `docs/DOCTRINE.md` and `docs/ARCHITECTURE.md` §7 first.

## Mission
Turn what we built and measured into a submission that scores on every axis: Suva's axes as the deck states them (recall/F2, Top 5 summary quality, overall product) and as the template's `challenge_description.md` states them (our top 10 summaries, our 30 highest-scored rulings, the Azure bonus), and the event jury's grid (purposeful use of AI, technical rigour, value/cost/scalability, sovereign deployability, implementation feasibility, pitch). Nothing is claimed that `results/` does not prove.

## You own
`technical_report.md` (updated in the repo, the template's headings kept verbatim and in order, D-043) and its PDF **`<TeamName>_Report.pdf`** (our registered team name, no spaces; Q-22), **committed at the repo root** (max **6 pages without references**, with the mandatory **Target architecture** section); the **Demo** field at the top of `technical_report.md` (the video link); the deck (PDF, max **10 slides**, one slide on **exactly how Apertus is used**, a rule of the event guide); the video (max **2 minutes**, public URL); the pitch script, the Q&A sheet, the sprintd submission. The "How to run" block of `technical_report.md` §6 is written with the platform owner (`docs/agents/platform.md` step 8). The template's facts are DECIDED (D-039): the file names, the PDF at the root, the Demo field, the page and slide limits, the public repo.

## What wins (lessons from the 2026 podiums, `docs/LESSONS.md` §4)
- **One thesis sentence**, repeated in deck, report, video: *"Apertus reads, the code verifies, the lawyer decides."* (PROPOSED wording.)
- **One before/after number with its interval**, e.g. out-of-quarter recall at the frozen threshold, rules-only (A0) or the template's keyword baseline (A0-kw) vs the delivered variant, with Wilson CI: the threshold is chosen on one labelled quarter and the number reported on the other, then the quarters are swapped and both folds shown (`docs/EVAL.md` §2). Plus one **business number**: rulings an expert must read per week, minutes saved, CHF per quarter of compute.
- **A dated real case as the hook**: a 2026 ruling where a naive approach misses or mis-cites, and our pipeline catches it with evidence.
- **Full brief coverage, proven line by line**: a criterion → evidence table (the template's 5 steps, success criteria, evaluation criteria and Azure bonus; the deck's four steps and three axes; the jury's dimensions).
- **Both scoring texts answered side by side.** The deck: recall and F2 of our Q2 list, "Top 5" summaries checked against Suva's June 2026 summaries, usability. The template: Suva's experts grade our "top 10 highly relevant summaries" and check our "30 high scored relevant court judgements" ("you didn't miss anything relevant"), with a bonus if the project is "easy to transfer to Azure"; it has no usability criterion. Neither text says it overrides the other (comparison in `docs/CHALLENGE.md` §4). Until Suva answers Q-17 and Q-18, show a result for each: out-of-quarter recall and F2 at the threshold, precision and hits at 30 (D-046), our top 10 summaries (D-047).
- **Honest limits**: a slide and a report section "what we could not measure". One 2026 podium (second place) published no score at all and still placed, on its product, its fit to the criteria and its honesty about what it had not validated; overclaiming loses.
- **Few words on slides, a live demo**, with a recorded fallback.

## Deck outline (10 slides max, PROPOSED)
1. **Hook**: the Monday-morning problem in one image (an "80s-style" list of ~2,000 rulings per quarter) and the dated case.
2. **Thesis** and the result in one line (out-of-quarter recall at threshold with CI, hits at 30; rulings to read per week).
3. **What Suva gets**: the table (score, reason in German), the ruling page, DE and FR summaries side by side. Screenshot.
4. **How relevance is decided**: signals (the 9 examples and neighbours) and the Apertus judgement; the variant chosen by out-of-quarter measurement on Q4/2025 and Q1/2026 (A0-kw, A0-A4); F2 threshold chosen on one quarter and reported on the other, then swapped; refit on both quarters and frozen before Q2 (D-021 point 8).
5. **Exactly how Apertus is used** (mandatory): which model for which role (70B judgement and summaries; 8B never excludes alone), model ids in both forms (Hugging Face and gateway, copied from `MODELS.md`) and revisions, JSON mode, log-probabilities or labels, temperature, thinking off, one repair call, what the code copies (ids → text, references), what the verifier rejects. Two measured numbers on this slide.
6. **Trust**: every claim linked to its consideration; verification rates; one green verified citation and one red rejected one.
7. **Results**: triage per language and court with CIs (out-of-quarter recall and F2 at the threshold, both folds shown; precision and hits at 30, recall on the rulings Suva summarised); summary metrics on the internal hold-out (style and legal precision); robustness tests passed.
8. **Sovereign deployment and cost**: on-prem / Swiss cloud / air-gapped, external services list (target: empty at runtime), CHF per quarter, latency. Say "configured" or "verified" honestly. One line on moving to Azure (the template's bonus, D-049), clearly separate from the sovereign options.
9. **What we could not measure** and next steps (Suva's corrections loop, June delivery format).
10. **Team, repo, `make run`**, model registry pointer (members' names only where G13 allows them).

## Report outline (`technical_report.md`, 6 pages max without references, PROPOSED, D-043)
Keep the template's headings verbatim and in order (D-043); never rename, reorder or delete them. Content under each:
- **Header** (title line; Challenge partner, Challenge, Event, Team, **Demo**): project and team name; members' names or GitHub handles, as each member chooses (G13 in `AGENTS.md`, D-045); the public video link in the **Demo** field.
- **`## 1. Summary`**: problem, thesis, headline number (out-of-quarter) with its interval; the criterion → evidence table (half a page).
- **`## 2. Architecture`**: the method, stage by stage (ingestion, signals, net, Apertus judgement, score and threshold, explanation, summaries, verifier; S0-S10), stores, API; diagrams in `docs/`, referenced from the report.
- **`### Target architecture (mandatory)`**: which of a) on-premise, b) air-gapped, c) sovereign Swiss cloud the project is deployable in, and how it meets each; every external dependency, with build time apart from runtime; the path from the hack build to Suva production (scheduler, on-prem inference, Postgres, audit log, corrections loop, monitoring), with what is built vs designed. A short "Transfer to Azure" paragraph (bonus, D-049), never presented as the sovereign option.
- **`## 3. Use of Apertus`**: Model (the Apertus ids of `MODELS.md`, Hugging Face and gateway forms; the 8B too if used); How it is used (inference; "agents / tool use" only if true); Where it runs (hosted endpoint, Keera/CSCS); prompts, JSON mode, log-probabilities or labels, temperature, thinking off, the repair call, what the code verifies.
- **`## 4. Data`**: sources and licences (Neuheiten lists, the HF dataset, `judgements/` from Suva via the template); the window (Q2/2026, D-009; by publication date via the Neuheiten lists, the default while D-050 is open, D-052; both dates kept); labelled Q4/2025 and Q1/2026; personal data: anonymised published rulings, nothing re-identified (D-038); Suva's exports name their authors and link to Suva's intranet, and we never use or reproduce those fields (D-051); what is not in the repo and why (D-031).
- **`## 5. Limitations`**: limits, risks, what we could not measure; at least one negative result.
- **`## 6. Reproducibility`**: the "How to run" block (prerequisites, the three `LLM_*` variables, the one command `make run`, our convention (D-042), its duration, what is live and what is replayed, D-032); hardware, runtime, seeds, exact commit hash, all from `make claims`.
- **`## 7. Evaluation`** (added, D-043): protocol (temporal split; cross-quarter threshold: chosen on one labelled quarter, reported on the other, then swapped, both folds shown; frozen before Q2; pre-registered thresholds); A0-kw and A0-A4 with CIs per language and court; out-of-quarter recall and F2 at the threshold, precision and hits at 30 (D-046), recall on the rulings Suva summarised (the must-hit subset, `docs/GLOSSARY.md`; Q-20); summary metrics, style and legal precision apart, per style; robustness; failure analysis.
- **`## 8. Model registry and declarations`** (added, D-043; event rule E6): every runtime and development model with version and role, copied from `MODELS.md`; pre-existing material declared (D-029); AI coding assistants.
- **`## License`**: keep the template's line (CC-BY-4.0, D-041); add the licence map (D-048).
- **`## References`**: rulings cited, datasets and their attribution, Suva's examples credited to Suva.

Sections 7 and 8 are additions while Q-25 is open. If the organisers refuse them, move their content into sections 1 and 3 to 6.

## Video (2 minutes, PROPOSED script)
| Time | Content |
|---|---|
| 0:00-0:15 | Hook: the dated case; the Monday problem. |
| 0:15-0:45 | The table: sort by score, read a German reason, open the evidence. |
| 0:45-1:15 | The ruling page: DE and FR summaries side by side, a verified citation in green, a rejected one in red. |
| 1:15-1:35 | "Add another judgement": paste a docket, watch the pipeline progress (cut the wait in editing and say so), the ruling joins the table. |
| 1:35-1:50 | The numbers: out-of-quarter recall at threshold with CI, hits at 30; rulings to read per week. |
| 1:50-2:00 | `make run` reproduces the results (live or replayed, labelled: D-032). Thesis sentence. |
Record in **live mode** (not simulated), show a small panel of Apertus calls per role, add subtitles. Keep the `REPLAY` badge visible if any part is replayed, and say in the video when a wait was cut. Never show a Suva staff name, staff code or intranet link on screen (D-051), and no long passage of Suva's summaries (D-031). Put the public video link in the **Demo** field of `technical_report.md` before exporting the PDF.

## Spoken pitch (7 min + 2 min Q&A; finals 5 min + 1 question)
- 7 min: hook 30 s · thesis and result 30 s · live demo 3 min (Monday script of `docs/EVAL.md` §6) · how Apertus is used 1 min · results and limits 1 min · deployment and cost 30 s · close 30 s.
- 5 min finals version: drop the method detail, keep hook, demo (2 min), result, sovereignty, close.
- Q&A sheet: why not keywords only; how the threshold was chosen and frozen; why a ranked list and a threshold (D-046); which date defines the quarter (D-050); what happens on French or Italian rulings; how hallucinated references are prevented; what the model is never allowed to do; cost per quarter; how Suva's corrections feed back; what is replayed vs live; what we could not measure.

## Steps
1. **Friday evening:** fill the criterion → evidence table with placeholders pointing to `results/` files; draft slide titles; pick the dated case. Check that `technical_report.md` still has the template's headings in order (D-043), and that `docs/STATE.md` §1 names who can switch the repo to public.
2. **Overnight:** screenshots from the real Q2 run; draft `technical_report.md` sections 2 (with the Target architecture), 3 and 4.
3. **Saturday before 12:00 (feature freeze):** `make claims` → paste numbers; record the video; rehearse the demo twice with the fallback capture.
4. **12:00-13:30:** the Demo link in `technical_report.md`; `technical_report.md` final; `<TeamName>_Report.pdf` (our registered team name, no spaces, Q-22) exported and **committed at the repo root**; deck PDF; video public; repo **public** (checked from a logged-out browser); `README.md` with the team name; the ZIP with the deck and report PDFs that the event guide mentions (kept while Q-22 is open); submission on sprintd **by 13:30** (hard deadline 14:30, no extension, one per team, a draft is not a submission).
5. **After submission:** rehearse the 7-minute pitch; prepare the 5-minute finals cut. The repo stays public (D-039).

## Submission checklist (template `README.md`, D-039; event-guide items to confirm with Q-22)
- [ ] Repo <https://github.com/Apertus-NGA/suva-NGA> public, checked from a logged-out browser; every template file at its path (`tests/test_template_layout.py` green); `README.md` with the team name.
- [ ] `technical_report.md`: the template's headings in order (D-043); the **Demo** field holds the public video link; the "How to run" block in §6; every number from `make claims`.
- [ ] `<TeamName>_Report.pdf` at the repo root: at most 6 pages without references; Target architecture present.
- [ ] Video: at most 2 minutes; public URL that plays from a logged-out browser.
- [ ] Deck: PDF, at most 10 slides, the Apertus slide present.
- [ ] On sprintd: the repo URL, the report PDF, the video URL, the deck PDF (the template's list), plus the ZIP with the deck and report PDFs that the event guide mentions (Q-22: until the organisers answer, submit both). Submitted, not left as a draft, by 13:30.
- [ ] No Suva staff name, staff code or intranet link in the report, deck, video or screenshots (D-051); no verbatim Suva text beyond what D-031 and Q-15 allow.

## Rules specific to this role
- Every number comes from `make claims` (no hand-typed figure); every number says what it measured, on which set, with which interval.
- Never present Apertus as judge of our headline metric; never present the replay as live.
- No person's name from rulings (D-038). No Suva staff name, staff code or intranet link anywhere: report, deck, video, screenshots (D-051).
- No long verbatim copy of Suva's texts in the deck, report or video: the report is CC-BY-4.0 and cannot relicense them (D-031, Q-15). Whether short quotations are allowed is Q-15: until Suva answers, paraphrase and refer to the file in `judgements/`; once allowed, keep them short and credited to Suva. Suva material received outside the template stays out entirely (D-019).
- `technical_report.md` keeps the template's headings verbatim and in order (D-043); our sections 7 and 8 go after section 6, before "License".
- The model registry in the report matches `MODELS.md` exactly, including the development tools of every member.
- Declare pre-existing material (D-029) and AI coding assistants.

## Done when
`technical_report.md` complete, with the template's headings and the Demo link; `<TeamName>_Report.pdf` (≤ 6 pages without references, Target architecture present) committed at the repo root; deck PDF (≤ 10 slides, Apertus slide present); public video (≤ 2 min); repo public, checked logged out; the submission checklist ticked; submission sent on sprintd before 13:30; pitch rehearsed with a working fallback.
