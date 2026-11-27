# Role brief: UI and API for legal experts

> **Status: v0 PROPOSAL (27 Nov 2026), updated after the template was read.** Owner: `<handle>`. The owner chooses the UI technology (D-026), keeping it minimal and served by FastAPI. Read `AGENTS.md` and `docs/CHALLENGE.md` §2, §9 first.

## Mission
Give a Suva legal expert, on a Monday morning, a clear and pleasant product that replaces searching an "80s-style web page": see what matters, trust why, read both summaries, correct, and add a missing ruling.

## You own
`src/api/`, `src/ui/`, the demo script, `make serve` and the serving step at the end of `make run` (skipped with `SERVE=0`, as CI does). Start from the API contract in `docs/ARCHITECTURE.md` §3.

## Must-have (slide 21, repeated nearly word for word as step 4 of the template's `challenge_description.md`: the deck adds "and appealing", and we keep "appealing" because the deck scores usability; checked in the demo)
1. **Original documents:** link to the bger.ch ruling and the text shown with considerations.
2. **Relevance score, sortable:** 0-100 with a bar, default sort descending.
3. **Why relevant or not:** German explanation for every ruling, selected or not, with the signals fired as badges and the evidence on click.
4. **Summary in both languages:** German and French side by side, with each claim's verification status.
5. **Summarise additional judgements:** "add another judgement" by docket number or bger.ch link → full pipeline (score, reason, both summaries) → added to the table whatever its score (D-015 covers both readings: a ruling missing from the list, an extra ruling to summarise). Live, this takes minutes (cold start, two long summary calls): show progress per stage, warm the model before a demo, and measure the time in the probe.

Not a must-have while D-033 and Q-21 are open: search over stored rulings and summaries (the template's problem description ends with "a central, searchable and query-enabled knowledge base"). If the team builds it, D-033 option (d) is the cheap form (Postgres full text, no embeddings), and only after the five must-haves pass end to end.

## Table (from Suva's mock-up)
Columns: `RELEVANZ` (score + bar) · `URTEIL` (docket) · `DATUM` (publication or decision date: D-034) · `GEGENSTAND` (subject area or subject, in the ruling's language, Italian included: D-034) · `BEGRÜNDUNG DER RELEVANZ` (German reason, truncated, full on hover). Filters: date range (on either date), court, language, selected / not selected, in our top 30, star, in Q2 by publication date / by decision date (D-050).

Both dates matter: Suva's own list groups rulings by the quarter of their decision date (D-050), while D-009's window is defined by publication date (the default while D-050 is open, D-052). While D-034 is open, `DATUM` shows the decision date, labelled as such, as in the deck's mock-up (slides 13-14); the publication date shows on hover and on the ruling page.

**Export (D-046 while open):** one ranked list with every ruling's score, the F2 threshold and the top-30 cut marked, both dates and both Q2 flags (D-050), plus the plain docket list in Suva's format (D-009's publication-date window by default, D-052; Q-02). Downloadable from the table, and served by `GET /api/export/relevant?quarter=2026Q2` (`docs/ARCHITECTURE.md` §3), from the same files triage writes (`docs/agents/triage.md`).

## Ruling page
Header (docket, decision date and publication date, court, bench, outcome, star) · score with the signals that fired (and their weights if the score is a learned combination, D-021) · German reason · key statement with its consideration · both summaries, each sentence linked to its consideration, unverified ones marked · original text with the cited passages highlighted.

## Corrections (bonus, cheap to show)
- Flip relevance with an optional comment → stored as a label (author, time, before/after); a "refit" button reruns the scoring with the new labels and shows what moved.
- Edit a summary sentence → stored as a correction; shown as "edited by expert".
- Adjust signal weights (if the score has weights, D-021) and the threshold (expert mode) → live re-ranking.

## Rules specific to this role
- Show state honestly: a `REPLAY` or `LIVE` badge on every Apertus output (D-032); `degraded` when a stage fell back; counters of work done per stage on an admin panel (a stage at 0 is red).
- Show the published ruling text as published; never add, infer or join personal data, and never put a person's name in a label, a badge or an explanation (D-038).
- Never display a Suva staff name, staff code or link to Suva's intranet from `judgements/` (D-051). The UI reads only what the S0 parser keeps; where it shows a Suva example, it shows the docket, the dates, the texts and the bger.ch link, never an author line.
- No external service at runtime (no CDN fonts or scripts that phone home): everything is served locally. The template's `.gitignore` ignores `dist/` and `build/`: build the UI inside the Docker image, or un-ignore its output explicitly by PR (appended to `.gitignore`, D-044).
- The API exposes what the UI shows, so judges can query it.
- UI labels in German like the mock-up (Suva's experts read German and French); summaries in their language.

## Demo
Prepare the Monday-morning script of `docs/EVAL.md` §6 and a recorded fallback (screen capture) in case the network fails.

## Done when
The 5 must-haves work on real Q2 data from `make run`; both dates and the export of D-046 are visible; the UI builds inside the image from a fresh clone; the demo script runs in under 3 minutes; a screenshot set exists for the deck, the video and `<TeamName>_Report.pdf` (our registered team name, no spaces; Q-22), with no Suva staff name or intranet link on screen (D-051).
