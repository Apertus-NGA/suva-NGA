# STATE: where the project is now

> **Last updated: Friday 27 Nov 2026, 18:00 CET (template facts added after the official template was read; provenance of the 2,096 list and measured populations added; the "Built so far" line still needs the platform owner's check), by `<handle>`.** Owner: `lead`. Update this file at every sync (every 2 hours) and whenever an input arrives. If the time above is more than 3 hours old, ask before trusting it.

## 1. Build

- Hacking started Fri 11:30. Allocated challenge: Suva.
- Repository: <https://github.com/Apertus-NGA/suva-NGA> (in the `Apertus-NGA` GitHub organisation), created from the organisers' Suva template.
- Visibility: `<private/public>`. Who in `Apertus-NGA` can switch it to public: `<handle>`. Needed before submission; the repo then stays public (D-039).
- Registered team name (sprintd): `<to fill>`, used in `README.md`, `LICENSE`, the report header and the PDF name.
- Template: <https://github.com/HackApertus/zurich-suva> (shown as "Public template" on GitHub), read at commit `c6e50ba` (Fri 27 Nov 11:30). Template files, never renamed or moved (D-039); never deleted (our rule, D-044):
  - `README.md` (the organisers' text; fill "Add your team name"), `challenge_description.md` (Suva's written challenge, never edited: our rule, D-044), `technical_report.md` (the report), `LICENSE` (Apache-2.0; its line "Copyright 2026 Your Team" is a placeholder, D-045), `.gitignore` (appended to, never replaced, D-044), `src/.gitkeep`;
  - `judgements/` (never edited: our rule, D-040): Suva's relevance list `BG_Urteile_2025_Q4_2026_Q1.xlsx`, 55 summary exports `Export_<court>_<number>_<year>.html`, and the empty `read.me` and `test.txt`. Content: `docs/SUVA_DATA.md`;
  - `28112026 HackApertus – Challenge Pitch.pdf` at the root: Suva's deck (never edited: our rule, D-040). The name contains spaces and an en dash.
- Not in the template, all ours: `Makefile`, `Dockerfile`, compose file, `.env.example` (the template's `.gitignore` already lets it through), CI, `docs/`, `data/`, tests. `make run` is our convention (D-042).
- Imposed names: `LLM_NAME`, `LLM_BASE_URL`, `LLM_API_KEY`; `<TeamName>_Report.pdf` at the root (our registered team name, no spaces; Q-22); the **Demo** field at the top of `technical_report.md`. All template rules: `docs/EVENT.md` §3.
- Built so far: the template files only `<check: repo created at <time>; pitch PDF present: yes/no; judgements/ manifest = aee08754…: yes/no>`. A repo created from the template before Fri 11:30 lacks the pitch PDF: copy it in unchanged from the template. This kit will be the first team commit (declared pre-existing material, D-029).
- Next step: `docs/agents/platform.md` (check the repo against the template, then skeleton, contracts, gateway probe).

## 2. Inputs inventory

Every role starts by finding its input. Fill the blanks as soon as they are known; never put Suva content itself in this file.

| Input | Status | Where it physically is | Format | SHA-256 | Holder | Notes |
|---|---|---|---|---|---|---|
| List of Q2/2026 rulings ("the 2,096 list") | held by the team; provenance known (27 Nov) | `<path or channel>` | `<csv / txt / json>` | `<hash>` | `<handle>` | **Provenance:** exported by a team member from the search.bger.ch date search, every ruling from 01.04.2026 to 30.06.2026. That search filters on the **decision** date, and 2,096 is exactly the number of Federal Court decisions dated in Q2/2026 in HF and in entscheidsuche (measured on 27 Nov, `docs/DATA.md` §6). So the list is the decision-date population of Q2 (reading (b) of D-050), not the publication-date window that is the default for the delivered list (D-009, D-052). By publication date, Q2 holds about 2,060 rulings, of which about 1,480 are in this list; the union holds about 2,677. It stays one input to the union of D-010 and is checked against dataset DS2 (`docs/DATA.md` §10). Still to fill: where it is, its format, its hash and the date of the export. |
| Suva relevance list Q4/2025 and Q1/2026 | received (template) | `judgements/BG_Urteile_2025_Q4_2026_Q1.xlsx` (stays there, D-040) | xlsx | `f7146cfd9e8419cd0801d30972d1220d8502b0b1a134364265eababe6bd1e86d` | template | Uploaded by the organisers on 25 Nov; public (D-040). 60 rows, positives only: 28 for Q4/2025, 32 for Q1/2026 (31 Federal Court rulings and 1 cantonal decision). Quarter labels follow the decision date in all 52 dated rows (D-050). Its intranet links and file properties are never copied (D-051). Content: `docs/SUVA_DATA.md` §2. Needed by every triage option (D-021). |
| Suva human summaries (DE and FR) | received (template) | `judgements/Export_<court>_<number>_<year>.html`, 55 files (51 in court 8C, 3 in 9C, 1 in 4A; one name has a space: `Export_8C_176_2025 3.html`) | HTML | manifest of `judgements/`: `aee087543de78a7f81b29f1489497fec054acb053f19091c5365901327a548e0` (SHA-256 of the per-file SHA-256 lines sorted by name: `cd judgements && sha256sum * \| LC_ALL=C sort -k2 \| sha256sum`) | template | Each file holds a German and a French text. By decision date: 23 in Q3/2025 (in no list), 22 in Q4/2025, 10 in Q1/2026. Author section dropped at ingestion (D-051). Content: `docs/SUVA_DATA.md` §3-4. Needed by the summary role first (`docs/agents/summarise.md` step 1). |
| Suva pitch deck (22 slides, sensitivity label enabled) | in the template | `28112026 HackApertus – Challenge Pitch.pdf` at the repo root (added to the template Fri 27 Nov 11:30) | PDF | `1ed75386da205c33dc54fc3c09020fe955e77656623a541e3bad1ea16f047cef` | template | Public (D-040); never edited. Same file as the deck the team analysed on Friday morning. Paraphrased in `docs/CHALLENGE.md`. |
| Gateway keys | one personal key per member after check-in | each member's `.env` | | | each member | Never in the repo. |
| Populations Q4/2025 and Q1/2026 (negatives) | measured during preparation (27 Nov); not yet built in the repo | (→ `data/public/`) | | | crawl owner | Expected by decision date: 1,931 decisions in Q4/2025 and 2,005 in Q1/2026, with 104 and 131 hard negatives (`docs/DATA.md` §6). Rebuild them as DS1 and DS6 (`docs/DATA.md` §10; `docs/agents/crawl.md` step 0). While D-050 is open: by decision date from HF cross-checked with entscheidsuche; by publication date from the Neuheiten pages of every day from 1 Oct 2025 to 15 Sep 2026 (the end date is a parameter). Both dates per ruling, so each quarter can be cut either way. Negatives only under the closed-world assumption (Q-04). |

## 3. Access tests

| Test | Result | When |
|---|---|---|
| bger.ch from cloud IPs | challenged by the firewall after ~25 requests in 20 minutes | before the event |
| bger.ch from the venue, automated/built-in browser | challenged | Fri 27 Nov, late morning |
| bger.ch from the venue, ordinary browser at human pace | `<not yet recorded>` | |
| Hugging Face dataset from the venue | `<not yet recorded>` | |
| Gateway probe (`make smoke-llm`) | `<not yet run>` with the repo's client → `results/gateway_probe.json`. A first test ran on 27 Nov, 16:26 to 16:46 CET, outside the repo (one key, 423 calls): results in `docs/LESSONS.md` §1, column "Ours", and §2b; its scripts are not in the repo yet (to commit with the lead's OK) | |
| Template HEAD (`git ls-remote https://github.com/HackApertus/zurich-suva.git main`). Re-check at every sync. If it moved, bring the organisers' change into our repo exactly as they made it (D-039; Q-26 for `judgements/`) and record it here. | `c6e50ba` (the commit this kit was checked against) | Fri 27 Nov, 16:25 CET |
| Publication dates of the 11 boundary dockets listed in D-050 (the single home of the list; T32), from the Neuheiten pages (authoritative, D-010). The HF dataset's publication date is unreliable (D-011): use it only to narrow which days to fetch, from each boundary to about 10 weeks after it | `<not yet run>`; the result goes to D-050 and Q-02 | |
| Questions asked at the partner workshop (Fri 10:30) | `<to fill>`: which Q-ids, if any, and the answers (answers are recorded in `docs/DECISIONS.md` §3) | Fri 27 Nov, 10:30 |

## 4. People and questions

- Owners: not assigned (D-024). Team table: `docs/EVENT.md` §7.
- Questions to Suva and the organisers: status in `docs/DECISIONS.md` §3 (asked by, when, answer).
- Next sync: `<time>`.
