# EVENT: the hackathon, its rules, its timetable and the team

> **Status: v0 PROPOSAL (27 Nov 2026), updated after the official template was read.** Owner: `lead`. Facts from the organisers' guide and e-mails, as read by the team before the event, and from the official template `HackApertus/zurich-suva` (commit `c6e50ba`, Fri 27 Nov 11:30). Where two sources disagree, both are given.

## 1. The event

- **HackApertus Zurich**, Friday 27 and Saturday 28 November 2026, AI Startup Center, Technopark Zurich (3rd floor). About 100 participants; teams of 2 to 5; the venue stays open overnight.
- **HackApertus** is a series of hackathons built around **Apertus**, the Swiss open large language model (version 1.5, sizes 8B and 70B). Earlier 2026 editions ran online (tracks 1A, 1B, 2A, 2B) and on site in Liebefeld (Bern); their 245 public projects are the source of `docs/LESSONS.md`. A grand final is announced for 14 May 2027.
- **Zurich challenges:** Suva (ours: case-law monitoring), ti&m (a customer "trust room" in e-banking), Digitec Galaxus (product image classification, run on Kaggle). Teams were allocated on Friday morning.
- **Prizes:** CHF 3,500, 2,500 and 1,000.

## 2. Event rules on models (E1 to E6)

Breaking E1, E3, E5 or E6 removes eligibility for prizes.

| Rule | Text (paraphrased) |
|---|---|
| **E1** | Apertus 1.5 (8B or 70B, fine-tuned versions included) performs the core AI task. |
| **E2** | Any tool or model may be used for development, closed models included. |
| **E3** | At runtime, only Apertus plus open-weights models for supporting tasks (embeddings, OCR, speech-to-text, reranking). No closed model and no proprietary AI API. |
| **E4** | Evaluation judges may be open-weights models. |
| **E5** | The solution must be deployable on-premise, air-gapped, or on a sovereign Swiss cloud. |
| **E6** | The report lists every model used, in development and at runtime, with its version and role (`MODELS.md`). |

The template links these rules as "the model and challenge requirements" (a Notion page) and states one itself: "Submissions must use the v1.5 Apertus model family". Our tools could not render that page on 27 Nov, so E1-E6 are as read before the event: re-read the page in a browser if a rule matters.

Other terms: the work is built during the event; any pre-existing material must be declared and kept separate (see `docs/DECISIONS.md` D-029); the repo is public and open source: code Apache-2.0 (the template's `LICENSE`), the report CC-BY-4.0 (its License section; scope: D-041, Q-24); the licence of `docs/` and of datasets we create is D-048; AI coding assistants are allowed and declared.

## 3. Deliverables and submission

**Imposed by the official template** (`HackApertus/zurich-suva`, a public GitHub template, read at commit `c6e50ba`, Fri 27 Nov 11:30 CET; DECIDED, D-039). Only what the template says is here; our own rules are in the next block.
- **The submission must:** "follow the template repo and include all prerequisite files and definitions", and "run end-to-end when judges try to run it" (template `README.md`). A run that cannot find its prerequisite artefacts on a fresh clone fails both (D-031).
- **Repository:** created with "Use this template", **public**, and kept public after submission. Ours: <https://github.com/Apertus-NGA/suva-NGA> (organisation `Apertus-NGA`). In an organisation, switching to public may need an owner's rights: who can do it is recorded in `docs/STATE.md` §1.
- **Layout:** never rename or move the template's files: `README.md`, `challenge_description.md`, `technical_report.md`, `LICENSE`, `.gitignore`, `src/` ("Your code"), `judgements/` (Suva's data, `docs/SUVA_DATA.md`), the pitch PDF. Diagrams go in `docs/` and are referenced from the report (the template's `technical_report.md`, section 2). The template never asks for documentation in `src/`: it calls `src/` "Your code" (checked Fri 27 Nov against the template and the two Notion pages its README links to). Our layout rule follows from it: `src/` is code, `docs/` is documentation (D-059, `AGENTS.md` §4).
- **Placeholders to fill:** "Add your team name" in `README.md`; the report's title and **Team** line; "Copyright 2026 Your Team" in `LICENSE` (how we fill them: D-045).
- **Run:** the run instructions go **in `technical_report.md`**. Configuration through `LLM_NAME` ("name and version of the model"), `LLM_BASE_URL`, `LLM_API_KEY`.
- **Report:** update `technical_report.md` with all the details, and commit its PDF at the repo root as **`<TeamName>_Report.pdf`** (our registered team name, no spaces; Q-22; the template writes `TeamName_Report.pdf`): max 6 pages without references. The template's `technical_report.md`, section 2 "Target architecture (mandatory)": which of a) on-premise, b) air-gapped, c) sovereign Swiss cloud; how we meet it; external dependencies; build time apart from runtime. Its License section says CC-BY-4.0 (we read it as the report's licence; whether it covers more: D-041, Q-24).
- **Licence:** `LICENSE` is Apache-2.0 (our code, D-041).
- **Video:** max 2 minutes; its link goes in the **Demo** field at the top of `technical_report.md`.
- **Deck:** PDF, max 10 slides.
- **Submit:** the repo URL, the report PDF, the video URL, the deck PDF.

**Our conventions** (PROPOSED; the template does not require them, and it does not forbid editing or deleting its files):
- Template files: never renamed or moved (D-039); never deleted (our rule, D-044).
- `judgements/` and the pitch PDF are never edited, so that our copy stays identical to the organisers' and the manifest check holds (D-040). `challenge_description.md`, the organisers' text, is never edited either (D-044).
- `.gitignore` is appended to in a marked block, never replaced, reordered or trimmed (D-044).
- The report keeps the template's headings verbatim and in order; run instructions go in section 6; sections 7 "Evaluation" and 8 "Model registry and declarations" are added after section 6 (D-043).
- `make run` is our single command for the end-to-end run, named in section 6 (D-042); live or replay: D-032.

**From the event guide, not in the template** (as read before the event; to confirm with Q-22 and Q-23):
- submission on **sprintd**, the event platform (registration, challenge choice, perks, submission): one submission per team, any member can edit it, **a draft is not a submission**, no extension; deadline **Sat 28 Nov 14:30**; a ZIP with the deck and the report PDFs;
- one deck slide on exactly how Apertus is used.

## 4. Inference: the Keera gateway

- An OpenAI-compatible gateway provided to participants: `https://gateway.keera.ch/api/v1`. The gateway has its own model ids; the template names the models by their Hugging Face ids (`README.md`). Both forms, and the allow-list our client checks: `MODELS.md` §1 (the single home of the ids).
- The template says Apertus is "accessed via the CSCS / Keera Gateway" (`challenge_description.md`): the judges' endpoint and model id may differ from ours (`AGENTS.md` G3; D-032, Q-23).
- Access: a **personal code per participant**, redeemed on sprintd after check-in (from Friday 08:00). Each member keeps their key in their own `.env`; keys never enter the repo or a message.
- Known behaviour and limits: `docs/LESSONS.md` §1. Using two members' keys in one run: open question D-030.

## 5. Scoring

**Suva's scoring** comes in two versions: the deck's (27 Nov, slides 18-21) and the template's `challenge_description.md` (23 Nov). Neither says it overrides the other; both stand until Suva answers. The comparison table, the questions (Q-11, Q-16 to Q-20, D-050) and the working assumptions while open (D-046, D-047, D-049) have one home: `docs/CHALLENGE.md` §4.

- **Event jury** (event guide; not in the template), 6 criteria scored 0 to 5: purposeful use of AI, technical rigour, value/cost/scalability, sovereign deployability (no external service at runtime scores highest), implementation feasibility, pitch.
- How Suva's scores and the event jury combine is not stated (Q-11).

## 6. Timetable (CET)

| When | What |
|---|---|
| Fri 27 Nov 08:00-09:00 | Check-in; gateway codes and perks unlock; repo created from the template |
| Fri 09:00 | Challenge pitches by the partners |
| Fri 09:30-10:15 | Challenge choice on sprintd, then allocation |
| Fri 10:30 | Partner workshop with Suva (about 60 min); Suva mentors stay reachable on site |
| Fri 11:30 | Hacking starts. At the same time the organisers add Suva's deck (the pitch PDF) to the template: a repo created from it earlier lacks the PDF (`docs/STATE.md` §1) |
| Fri 12:15, 18:15, ~23:00 | Lunch, dinner, late snack (coffee and snacks around the clock) |
| Fri night | Venue open; the full Q2/2026 run is planned overnight (D-027) |
| Sat 28 Nov 08:00 | Breakfast |
| Sat 12:00 | Team feature freeze (D-027) |
| Sat 13:30 | Team submission target, one hour of margin |
| **Sat 14:30** | **Submission deadline on sprintd, no extension** |
| Sat 15:00-16:45 | Pitch to the partner: 7 minutes plus 2 minutes of questions |
| Sat 17:30 | Finalists announced: **top 6** per the event guide, **top 3** per an organiser e-mail (Q-13); finalists pitch 5 minutes on the main stage plus one jury question |
| Sat 18:00 | Apéro |

## 7. The team

Three members. The process (D-002): the lead decides and integrates by default, a deputy holds delegated authority, the carrier of a decoupled feature decides on it; sync every 2 hours; team chat outside the repo; **GitHub is the source of truth**. The pitch is in English (D-003). Ownership of areas is open (D-024).

| Handle | Role | Reads DE / FR / IT | Machine | Coding tools |
|---|---|---|---|---|
| `<lead-handle>` | lead | `<to fill>` | macOS, plus Windows by remote desktop | `<see MODELS.md>` |
| `<deputy-handle>` | deputy | `<to fill>` | Windows | `<see MODELS.md>` |
| `<handle>` | member (joined on the event day) | `<to fill>` | `<to fill>` | `<see MODELS.md>` |

Who reads which language matters: hand checks of the triage, the French summaries and the glossary need German, French and some Italian readers.

**How an agent reaches the team:** an agent works for one member. It raises a question by writing it at the top of its plan or PR description and telling that member; the member brings it to the next sync, or to the lead at once if it blocks.
