# DATA: sources, licences, uses, pitfalls

> **Status: v0 PROPOSAL (27 Nov 2026), updated after the official template was read.** Owner: crawl and ingestion. Based on a full map of bger.ch and an independent adversarial review done before the build (27 Nov 2026), kept outside the repo. What Suva's data in `judgements/` contains, with every count: `docs/SUVA_DATA.md`.
> Evidence codes: **verified** = read directly on 27 Nov 2026; **indirect** = seen in search results or third-party code; **inferred** = deduction, not checked.

## 1. The data categories of the challenge

| # | Category | Provider | Period | Our use | Where it lives | Public? |
|---|---|---|---|---|---|---|
| 1 | Rulings published 1 Apr to 30 Jun 2026 (D-009; the default while D-050 is open, D-052). The team's list of **2,096** is not this set: it holds the rulings *decided* 1 Apr to 30 Jun 2026 (`docs/STATE.md` §2). While D-050 is open, also the rulings decided in Q2/2026 and published up to 15 Sep 2026, each flagged under both date definitions | bger.ch | Q2/2026 | material to triage and summarise | `data/public/` (manifest + snapshot) | yes: rulings are not protected by copyright (art. 5 CopA) |
| 2 | Rulings labelled relevant: 28 rows for Q4/2025 and 32 for Q1/2026 (31 Federal Court rulings and 1 cantonal decision), **positives only** | Suva | Q4/2025, Q1/2026 (each dated row falls in its labelled quarter by **decision** date, D-050) | learning the relevance; internal recall/F2, precision and hits at 30 (D-046) | `judgements/BG_Urteile_2025_Q4_2026_Q1.xlsx` (template, read-only) | public in the template (D-040); derivatives: D-031, Q-15 |
| 3 | Human summaries: 55 exports, each with a German and a French text (rulings in German 22, French 31, Italian 2) | Suva | by decision date: Q3/2025 (23, in no list), Q4/2025 (22), Q1/2026 (10) | few-shot style; internal quality hold-out (time split stratified by style, `docs/EVAL.md` §4); must-hit subset (`docs/GLOSSARY.md`, Q-20) | `judgements/Export_*.html`, 55 files (template, read-only) | public in the template (D-040); derivatives: D-031, Q-15 |
| 4 | The 9 example rules (weights blurred) | Suva deck | n/a | signals | slide 12 of the deck at the repo root; paraphrase in `docs/CHALLENGE.md` | public in the template (D-040); quoting: D-031 |
| 5 | Hidden hold-out: relevant Q2 list and Suva's human summaries published in June 2026, which by Suva's 17 to 76 day lag cover the rulings decided from about mid-March to mid-June 2026 (our reading, D-047, Q-17; what is graded: our top 10 summaries and our 30 highest-scored rulings in the template's text, Q-17, Q-18) | Suva | Q2/2026; summaries published in June 2026 | final scoring | never seen | n/a |
| 5b | **All** Federal Court rulings of Q4/2025 and Q1/2026, under both date definitions (D-050) | bger.ch / HF | Q4/2025, Q1/2026 | the negatives for learning and validation (everything not in category 2, under the closed-world assumption of Q-04) | `data/public/` | yes |
| 6 | Suva's deck (22 slides: four steps, example rules, sample summary, UI mock-up, scoring) | Suva, through the organisers | n/a | context, rules, mock-up | `28112026 HackApertus – Challenge Pitch.pdf` at the repo root (template, read-only) | public in the template (D-040) |

Counts, file formats and parser quirks of categories 2 and 3: `docs/SUVA_DATA.md`. Never copy Suva's texts into `docs/` (D-031).

Category 5b is ours, not Suva's: without the full population of the labelled quarters we cannot learn or measure anything. **Origin of the 2,096 list (known, 27 Nov):** a team member exported it from the search.bger.ch date search, every ruling from 01.04.2026 to 30.06.2026. That search filters on the *decision* date, and 2,096 is exactly the number of Federal Court decisions dated in Q2/2026 in HF and in entscheidsuche (§6). So the list is the **decision-date** population of Q2, while the deck's window is the *publication* date (D-009, the default while D-050 is open, D-052) and Suva's own lists follow the decision date (59 of 59, D-050). By publication date, Q2 holds about 2,060 rulings, of which only about 1,480 are in the 2,096 list. Build the Q2 candidate set as the union of both populations (about 2,677 rulings, dataset DS2 of §10), and stamp every ruling with its publication date **and** its decision date.

**Which date defines a quarter (D-050, OPEN).** While open:
- **Crawl range:** the Neuheiten pages of every day from **1 Oct 2025 to 15 Sep 2026**, so that Q4/2025, Q1/2026 and Q2/2026 are complete under both definitions. The end date is a parameter: publication lags reach about 10 weeks, so a ruling decided on 30 June can go online in early September; if Q2 decisions are still being put online at the end date, extend it.
- **Two populations per quarter:** *by publication date* (the rulings on the Neuheiten pages dated inside the quarter) and *by decision date* (the rulings decided inside the quarter, whatever the date they were put online). Every ruling carries `decision_date`, `publication_date` and its quarter under each definition.
- **Labelled quarters:** evaluated on their decision-date populations, as Suva's labels suggest; the publication-date reading is reported too (`docs/EVAL.md` §2).
- **Q2/2026:** the candidate set is the union of both populations; the delivered set follows Q-02, with D-009 (published 1 Apr to 30 Jun) as the default (D-052).
- **Cheap check:** the publication dates of the 11 boundary dockets listed in D-050 (the single home of the list) settle most of the question from data. Record them at crawl time and tell the lead.

**Completeness check against `judgements/`.** Every Federal Court docket of `judgements/` (the rows of the relevance list and the 55 exports: 82 distinct rulings) must be found, with its decision date and, when it was put online inside the crawl range, its publication date. The 59 listed Federal Court rulings must be in the decision-date population of their labelled quarter. Measured during preparation (27 Nov, §6): all 59 are in HF with their full text, and all 59 fall in their labelled quarter by decision date, the 8 rows without a date included (decided 12 to 30 March 2026); the 23 Q3/2025 summaries are in HF too. The 23 summarised rulings decided in Q3/2025 must be found by docket: on the crawled pages if they were put online from 1 Oct 2025, otherwise in HF. A missing one shows a crawl gap or a wrong window definition, and helps answer Q-02 from data. The cantonal row cannot be found by a Federal Court crawl: it is reported as out of reach (Q-28). Test: `docs/EVAL.md` T30.

## 2. Sources

| Source | What it gives | Access | Licence | Use | Do not |
|---|---|---|---|---|---|
| **bger.ch Neuheiten** (daily list of newly published rulings) | decision date, docket, link, subject area (`Sachgebiet`, **in the ruling's language**, with a trailing `*` if destined for publication), subject (`Gegenstand`), publication date = the page's date | `search.bger.ch` HTML, one page per day (verified for dates back to 2015) | art. 5 CopA | **ground truth for "published in Q2"** (D-010) and for every ruling's publication date (D-050); the publication star exists only here | take the publication date from any other source; drop a ruling decided in Q2 and put online from July to mid-September while D-050 is open |
| **bger.ch ruling pages (AZA)** | full text, parties, bench, previous instance, operative part | `search.bger.ch` HTML, ISO-8859-1, `div.content`, no PDF | art. 5 CopA | signals that need the text; verification | count length with the site menu (it doubles) |
| **bger.ch BGE/ATF (CLIR)** | leading cases, trilingual headnotes | `search.bger.ch` HTML | art. 5 CopA | context, future BGE of starred rulings | treat a BGE and its original ruling as two cases (deduplicate on docket) |
| **HF `voilaj/swiss-caselaw`** (OpenCaseLaw) | ~195,000 Federal Court rulings since 2000 and ~36,000 BGE rows; full text faithful to the source; `structure/erwaegungen_paragraphs` (considerations pre-split: `e_number`, `depth`, `parent`, `text`); `graph/citations.parquet`; daily commits (last seen 26 Nov 2026) | Parquet (`data/bger.parquet` ~925 MB), DuckDB over `hf://`; pin a revision | CC0 packaging, MIT code; attribution appreciated ("Source: OpenCaseLaw.ch") | **text source** for Q2 and for history; few-shot candidates; considerations; citation graph; cross-check of the crawl | trust `publication_date` (empty ~91 %; filled from 19 May 2026 by its Neuheiten poller, which `docs/agents/crawl.md` allows as a source), `marked_for_publication` (null 99 %), `legal_area`, `judges` (often empty) or `outcome` (sometimes wrong: an inadmissibility labelled "dismissed") |
| **opencaselaw.ch API** | point look-ups, search, citations | REST `mcp.opencaselaw.ch/api`, no auth, ~5 req/s | CC0 / MIT | check one docket fast | bulk download (use HF) |
| **entscheidsuche.ch** | JSON + HTML per ruling | HTTP; sync through `Jobs/` (the `Index/` folder stops on 19 Jun 2026) | free use, citation requested | fallback if bger.ch blocks | use `Scrapedate` as publication date (no runs 7 May to 3 Jun 2026); trust its court labels for 8C/9C after 2023 |
| **HF `ipst/slds`** | ~20,500 BGE with official headnotes DE/FR/IT, 1954-2024 | Parquet | **CC BY 4.0** (attribution mandatory, arXiv 2410.13456) | secondary summary bench only | treat headnotes as Suva style (different genre: short, no facts, no consideration references) |
| **Fedlex** | LAA/UVG (RS 832.20), OLAA/UVV (832.202), LPGA/ATSG (830.1), LAM/MVG (833.1), LAMal/KVG (832.10); dated consolidated versions | SPARQL `fedlex.data.admin.ch/sparqlendpoint`, filestore | official acts | resolve and verify cited norms | quote a norm from memory |
| Jurivoc thesaurus | ~10,800 trilingual legal descriptors | file on request | © Federal Court, conditions | optional | use without the required mention |
| `rcds` datasets | older rulings | Parquet | **CC BY-SA 4.0** | avoid | ship in a closed deliverable |
| lexifina | mirror | n/a | **no licence** | do not use | |

## 3. bger.ch access recipe

### URL templates (verified unless noted)

| Use | Template |
|---|---|
| One day's Neuheiten | `https://search.bger.ch/ext/eurospider/live/de/php/aza/http/index_aza.php?date={YYYYMMDD}&lang={de\|fr\|it}&mode=news` |
| Last 14 days index | `…/aza/http/index_aza.php?lang=de&mode=index&search=false` |
| A ruling | `https://search.bger.ch/ext/eurospider/live/de/php/aza/http/index.php?lang=de&type=show_document&highlight_docid=aza://{DD}-{MM}-{YYYY}-{docket with "/" replaced by "-"}` (printable: `&print=yes`). **The decision date is part of the id.** |
| AZA search | `…/aza/http/index.php?lang=de&type=simple_query&query_words={q}&top_subcollection_aza=all&from_date={dd.mm.yyyy}&to_date={dd.mm.yyyy}&sort=relevance&page={n}`: **filters on decision date**, 10 per page, plan for a **cap of 100 results per query** (one-day windows, split further if more) |
| A BGE/ATF | `…/clir/http/index.php?lang=de&type=show_document&highlight_docid=atf://{VOL}-{PART}-{PAGE}:{de\|fr\|it}`; headnote: `…:{lang}:regeste` |
| BGE of one volume and part | `…/clir/http/index_atf.php?year={VOL}&volume={I..V}&lang=de&zoom=&system=clir` (vol. 152 = 2026) |

The `/live/{de,fr,it}/` path does not set the display language: always pass `lang=`.

### Which field is where

| Field | Neuheiten list | Ruling page | BGE page |
|---|---|---|---|
| Decision date | yes | yes | yes |
| **Publication date** | **yes (page date)** | no | no |
| Docket | yes | yes | yes (title line) |
| Subject area (`Sachgebiet`) | **yes**, in the ruling's language | no | no |
| Subject (`Gegenstand`) | yes | yes | no |
| **Publication star** | **yes, only here** | no | n/a |
| Bench (`Besetzung`) | no | yes | no |
| Parties | no | yes (anonymised; institutions and lawyers named) | partly |
| Operative part | no | yes | extract |

### Key and identifiers

- **Key: (docket, decision date).** One docket can carry several decisions (an interim decision, then the final one).
- Docket since 2007: `8C_802/2023` = court digit + proceedings letter, sequence, **year the case was filed** (not the decision year). The digit is the court, the letter is the kind of proceedings; neither is the subject (§5). Before 2007: `U 457/06` (former Federal Insurance Court: U = accident insurance, I = disability, K = health, M = military…).
- No official ECLI in Federal Court documents.

### Constraints for the crawler

| Constraint | What to do |
|---|---|
| `robots.txt`: `Crawl-delay: 2`; `/ext/eurospider/` allowed; `/php/jurivoc`, `/php/taf`, `/php/azabvger` forbidden | ≥ 2 s between requests; never touch forbidden paths |
| Imperva/Incapsula firewall: challenge pages after ~25 requests in 20 min from cloud IPs (verified); the venue's network was also challenged on 27 Nov in an automated browser | Crawl from a normal workstation at ≥ 2 s per request; detect `_Incapsula_Resource` and pages without the results table; exponential back-off; cache every page; **never bypass the protection**: no CAPTCHA solving, no switching networks or IP addresses to get past a challenge. A human may check once, in an ordinary browser, whether the site loads at all. If challenged: back off, fall back to HF / entscheidsuche, ask Suva for guidance (Q-10) |
| Encoding ISO-8859-1 | decode from bytes |
| Withdrawn ruling = HTTP 200 with "Dokument nicht gefunden" | test the text, not the status |
| Ruling sometimes missing for 30 to 90 min on its publication day | retry within 24 h |
| `www.bger.ch` serves an incomplete TLS chain (missing "DigiCert Global G2 TLS RSA SHA256 2020 CA1") | prefer `search.bger.ch`; if needed add the intermediate to a CA bundle; **never disable TLS verification** |
| Unstable result counters | never use them to measure completeness |

## 4. Where each signal comes from

| Signal (example rule) | Source | Example (verified) |
|---|---|---|
| Suva/CNA/INSAI is a party | parties block of the ruling ("Verfahrensbeteiligte" / "Participants à la procédure" / "Partecipanti al procedimento") | "Schweizerische Unfallversicherungsanstalt (Suva), Rechtsabteilung, … Luzern"; "Caisse nationale suisse d'assurance en cas d'accidents (CNA), Division juridique" |
| Suva mentioned, not a party | full text | |
| Subject area accident or military insurance | **Neuheiten list** | "Unfallversicherung", "Assurance-accidents", "Assicurazione contro gli infortuni", "Militärversicherung", "Assurance militaire", "Assicurazione militare" |
| Another UVG insurer is a party | parties block | Helsana Unfälle, Visana, SWICA, Allianz Suisse, AXA, Zurich |
| Destined for publication | **Neuheiten list only** (`*`) | |
| Five-judge bench | "Besetzung" (count the judges) | |
| Core themes | `Gegenstand` in brackets + full text | "Unfallversicherung (Kausalzusammenhang)", "Assurance-accidents (rechute)" |
| > 25,000 characters | length of the **cleaned** `div.content` text | |
| Appeal (partly) upheld | operative part | "Die Beschwerde wird teilweise gutgeheissen"; "Par ces motifs, le Tribunal fédéral prononce :" |

Fully worked example: 8C_802/2023 (decided 27 Mar 2026, became BGE 152 V 79): Suva party, accident insurance, five judges, > 25,000 characters, partly upheld.

## 5. Courts and docket prefixes (do not filter on the digit alone)

Since 2007 the Court builds the docket as `{digit}{letter}_{sequence}/{year}` ([Formation du numéro de procédure](https://www.bger.ch/fr/home/juridiction/jurisdiction-recht/bildung-der-verfahrensnummer.html), read 27 Nov 2026). `8C_177/2025` is court 8, a public-law appeal, the 177th case filed in 2025.

The digit is the court. Digit 3 is reserved and unused. Digits 11 to 15 are special files, not ordinary rulings.

| Digit | Court | Since |
|---|---|---|
| 1 | 1st public-law division | 2007 |
| 2 | 2nd public-law division | 2007 |
| 4 | 1st civil division | 2007 |
| 5 | 2nd civil division | 2007 |
| 6 | 1st criminal division | 1 Jul 2023 |
| 7 | 2nd criminal division | 1 Jul 2023 |
| 8 | 4th public-law division, Lucerne | 1 Jan 2023 (before that: 1st social-law division; the digit did not change) |
| 9 | 3rd public-law division, Lucerne | 1 Jan 2023 (before that: 2nd social-law division; the digit did not change) |

The letter is the kind of proceedings, on every court. C is a public-law appeal, A a civil appeal, B a criminal appeal, D a subsidiary constitutional appeal, F a revision, G an interpretation or a correction. Letters E and T to Z exist in the same note and almost never appear on the Neuheiten list.

The subject is not in the number. It is the Neuheiten `Sachgebiet`, in the language of the decision, with a trailing `*` when the ruling is proposed for the official reporter (§3). Court 8 also hears unemployment insurance, supplementary benefits, family allowances and social assistance. Court 9 also hears old-age insurance, loss-of-earnings allowances and tax. Court 4 also hears general obligations, debt enforcement, company law and civil liability. On the Neuheiten pages of every day from 1 Aug 2025 to 31 Mar 2026 (243 pages, read 27 Nov in an ordinary browser): 209 rulings in 8C, of which 72 accident insurance, 62 disability insurance and 75 in the other subjects of that court (unemployment 30, supplementary benefits 26, social assistance 16, family allowances 3). Accident insurance is about a third of court 8. A gate on the digit 8 keeps the other two thirds, and it drops the six 9C rulings of Suva's list and `4A_106/2025`. Letters other than C are rare on that court in the same window (8F: 5, 8G: 1, no 8D). Military insurance is in this court's competence and in the signal list (§4); it did not appear on these pages. The candidate gate keeps the rubric anyway.

| Prefix | Court | Matters on the Neuheiten line | For Suva |
|---|---|---|---|
| **8C** | 4th public-law court | **accident insurance (only on this court)**, disability insurance, unemployment, social assistance, military insurance, supplementary benefits, family allowances | accident, disability and military insurance; the other subjects of the court are out |
| **9C** | 3rd public-law court | **taxes** (since 2023; 96 of 203 rows in the window above), old-age, disability, health insurance, occupational pensions, loss-of-earnings allowances | disability, health insurance, occupational pensions; tax, old-age and loss-of-earnings are out |
| 8D, 8F, 8G, 9D, 9F, 9G | same courts | D a subsidiary constitutional appeal, F a revision, G an interpretation or a correction. An 8F can be accident insurance (8F_12/2026) | same subjects as 8C and 9C; the letter does not add a subject |
| 4A, 4D, 4F, 4G | 1st civil-law court | contract law, and separately liability, general obligations, debt enforcement, company law. Suva recourse actions exist (BGE 152 III 7) | contract law and civil liability. Suva summarised one 4A ruling, `judgements/Export_4A_106_2025.html`: daily sickness benefits under the Insurance Contract Act, filed under contract law (`Vertragsrecht`), not under its own rubric |

Disability insurance is handled by both 8C and 9C: it cannot be sorted by digit. Suva's own data confirms it: its list holds 53 rulings in 8C, 6 in 9C and 1 cantonal decision, and at least 7 of its 55 summaries concern disability insurance (`docs/SUVA_DATA.md` §2-3; scope: Q-06, Q-31).

`src/courts.py` is the candidate gate (layer 1); its rules, reason codes and measured counts are in `docs/LAYER1.md`, and the proposal to adopt it is D-060. It makes two decisions and keeps a ruling when either keeps it. The **subject decision** needs an allowed digit and letter, then reads the matter: from the Neuheiten rubric when it is filled, otherwise from the start of the ruling's subject line (Hugging Face `title`, cut at the first bracket, comma or semicolon: `Invalidenversicherung, Invalidenrente` gives `Invalidenversicherung`). Matter names are matched by name, not as exact strings, by `src/areas.py`, the one reading of matter names that the gate and the summariser share. A filled rubric outside the tables below drops the ruling. When the rubric is empty and the subject line names no kept matter, or there is no subject line, code does not decide: Apertus reads the matter (`src/area_judge.py`), and the ruling is dropped only when Apertus gives the kept matters less than 10% probability. A failed or absent reading keeps it. The **text decision** keeps a ruling when the text names Suva, CNA, INSAI or an accident or military insurance term (`UVG`, `LAA`, `LAINF`, `MVG`, `Unfallversicherung`, `Unfallversicherungsgesetz`, `Unfallversicherer`, `assurance-accidents`, `assureur-accidents`, `assicurazione contro gli infortuni`, and the military rubrics). Both reasons are kept. The `*` is stripped before the subject comparison. Ingestion still stores every court (`docs/agents/crawl.md`); whether a net is used at all stays open (D-021). While Q-06 is open, this is the candidate gate, not a claim that no other court can be relevant.

Courts 8 and 9, letters C, D, F and G:

| DE | FR | IT |
|---|---|---|
| Unfallversicherung | Assurance-accidents | Assicurazione contro gli infortuni |
| Invalidenversicherung | Assurance-invalidité | Assicurazione per l'invalidità |
| Krankenversicherung | Assurance-maladie | Assicurazione malattie ⚠, Assicurazione contro le malattie |
| Berufliche Vorsorge | Prévoyance professionnelle | Previdenza professionale |
| Militärversicherung | Assurance militaire | Assicurazione militare |

The Italian health-insurance line did not occur in the window above; the usual Tribunal rubric is kept so a later Italian ruling is not dropped. The Neuheiten page wrote `Assicurazione contro le malattie` for `9C_636/2025`: that form is kept too. The site spelled occupational pensions `Previdenza professionnale` once: that spelling is accepted too.

Court 4, letters A, D, F and G:

| DE | FR | IT |
|---|---|---|
| Vertragsrecht | Droit des contrats | Diritto contrattuale |
| Haftpflichtrecht | Assurance responsabilité civile | |

On those pages the insurance cases inside contract law are a sub-line (`Taggeldversicherung`, `Krankentaggeldversicherung`, `Versicherungsvertrag`, `contrat d'assurance`), not a separate subject. Keeping the whole subject is wide: 115 of 197 rows in 4A were contract law. Liability (`Haftpflichtrecht`, `Assurance responsabilité civile`) is a different line and is kept. No Italian liability rubric was read on these pages, so none is listed.

## 6. Volumes (measured on 27 Nov where stated; the datasets of §10 confirm them)

- **Federal Court populations by decision date (measured, 27 Nov).** Counted on HF `voilaj/swiss-caselaw` (`data/bger.parquet`, commit `35b17aa9c3fad71011b72f78f6ab79650ec0cf96`, the export of 26 Nov 2026) and, independently, on entscheidsuche.ch (read on 27 Nov): 7,781 and 7,780 decisions dated 1 Jul 2025 to 30 Jun 2026, 7,780 in common on the key (docket, decision date). The one difference is 2E_5/2024 (HF only). Unit = one decision: 18 HF twin rows (a `-DYYYYMMDD` suffix on `decision_id`, same date as the base row) are removed; 6B_920/2025 carries a wrong 2022 date on its base row and counts once; 7B_1356/2025 holds two decisions.

| Quarter (decision date) | 8C | 9C | Other courts | Total | German / French / Italian | Suva positives | Negatives (closed world, Q-04) |
|---|---|---|---|---|---|---|---|
| Q3/2025 | 150 | 158 | 1,441 | 1,749 | | 23 summaries, no list | not measurable |
| Q4/2025 | 164 | 147 | 1,620 | 1,931 | 1,244 / 597 / 90 | 28 (25 in 8C, 3 in 9C) | 1,903 |
| Q1/2026 | 210 | 172 | 1,623 | 2,005 | 1,279 / 627 / 99 | 31 (28 in 8C, 3 in 9C) | 1,974 |
| Q2/2026 | 229 | 163 | 1,704 | 2,096 | 1,261 / 728 / 107 | unknown (Suva's hidden hold-out) | unknown |

- **Q2/2026 by publication date (estimate).** HF knows the publication date only for the rulings its Neuheiten poller found, from 19 May 2026: 992 rulings put online 19 May to 30 Jun 2026 (34.2 per publication day). For 1 Apr to 18 May, the first-collection date stands in for it: 1,068 rulings (median lag 23 days, against a true median of 24; p10 14, p90 45). Total: about 2,060 (±50), of which about 580 decided in Q1 and about 1,480 decided in Q2. About 615 rulings decided in Q2 went online after 30 June or were seen late. The union of both Q2 populations holds about 2,677 rulings: about 580 more than the 2,096, 105 of them in 8C or 9C and 51 in accident, disability or military insurance. Possible poller gaps: 21 May (2 rulings) and 1 June (none). Before 19 May 2026, only the Neuheiten pages give an exact publication date.
- **Subject areas** (from `Gegenstand`, matched in German, French and Italian; HF's `legal_area` is often empty):

| Quarter | Accident (UV): total / positives / negatives | Disability (IV): total / positives / negatives | Military (MV) | Other subjects (no positive) |
|---|---|---|---|---|
| Q4/2025 | 37 / 20 / 17 | 95 / 8 / 87 | 0 | 1,799 |
| Q1/2026 | 54 / 23 / 31 | 107 / 8 / 99 | 1 (negative) | 1,842, plus 1 without a subject |
| Q2/2026 | 60 | 125 | 3 | 1,861, plus 47 without a subject (mostly 4A and 5A) |

  Every listed positive is an accident or disability ruling; the only summary outside both is 4A_106/2025 (Q3/2025, private daily-allowance insurance). Suva keeps about half of the accident rulings (20 of 37, then 23 of 54) and fewer than 1 disability ruling in 10 (8 of 95, then 8 of 107). The **hard negatives** (accident, disability and military rulings Suva did not keep) number **104 in Q4/2025 and 131 in Q1/2026**: they are where a threshold is placed. The other ~1,800 negatives per quarter are easy.
- **Keyword trap:** 14 of the 59 positives are pure disability rulings (an IV office against an insured person) whose text names neither Suva, CNA, INSAI, the LAA/UVG nor accident insurance. A filter on those words loses all 14 (G5; A0-kw in `docs/EVAL.md` §2).
- **Length:** in 8C, the median text is about 17,400 characters for positives and about 8,000 for negatives (many short inadmissibility rulings).
- **Not cross-checked with bger.ch** during preparation: the firewall challenged both the cloud and a laptop on the venue network, and it was not circumvented. Check for whoever can open the Neuheiten pages from an ordinary browser (never switch networks to get past a challenge): compare a day's count with HF (19 May 2026: 31; 2 Jun: 38; 17 Jun: 52; 30 Jun: 26), and look first at 21 May and 1 June.
- The whole crawl (every day from 1 Oct 2025 to 15 Sep 2026, D-050): about 8,000 rulings at the Q2 rate (2,096 in 91 days, about 23 per day). Only the candidate populations are triaged; a crawled ruling outside every window gets the reason code `out_of_window`, with no LLM call (G5).
- Suva's relevant rulings per labelled quarter (a fact, not an estimate): 28 in Q4/2025 and 32 in Q1/2026, one of them cantonal (`docs/SUVA_DATA.md` §2).
- Languages of Federal Court rulings in 2025: 61.5 % German, 33.8 % French, 4.7 % Italian.
- Daily lists sampled: 15 Apr 2026: 49 rulings (8 in 8C, 2 in 9C); 10 Jun 2026: 47 (4 in 8C, 4 in 9C of which 3 tax); 30 Jun 2026: 26.

## 7. Ingestion strategy (PROPOSED)

**Measured during preparation (27 Nov, §6): the decision-date populations do not need bger.ch.** HF and entscheidsuche, collected independently from bger.ch, agree on 7,780 of 7,781 decisions. Build them first (DS1 and DS2 of §10). The Neuheiten pages remain the only exact source of the publication date before 19 May 2026 and of the star (D-010): they no longer block the decision-date work.

1. **Lists from bger.ch:** the 91 daily Neuheiten pages of Q2/2026, plus the ~182 pages of Q4/2025 and Q1/2026 (needed for negatives), plus the ~77 pages of 1 July to 15 September 2026 (rulings decided in Q2 and put online later, D-050): every day from 1 Oct 2025 to 15 Sep 2026, ~350 pages. At 2 s per request they take about 12 minutes if never challenged; at the rate observed from cloud IPs (a challenge after ~25 requests in 20 minutes) they take about 4.7 hours; this assumes each block clears. If it does not, stop and use the fallbacks of §3 (no circumvention). Plan for the slow case, start early, fetch Q2/2026 first, and cache raw HTML with a hash and timestamp so nothing is fetched twice.
2. **Texts from HF first:** look up each docket in `bger.parquet` (DuckDB, pinned revision) and take `full_text` and `erwaegungen_paragraphs`. This avoids about 6,000 or more page fetches on a firewalled site (the texts of Q4/2025, Q1/2026 and Q2/2026 under both date definitions).
3. **Fetch from bger.ch only** what HF lacks, plus a random sample to check text fidelity.
4. **Union** with the team's list of 2,096 (the decision-date population of Q2, `docs/STATE.md` §2); every ruling carries `decision_date`, `publication_date`, its quarter under both definitions (D-050), `text_source` (`bger` | `hf` | `entscheidsuche`) and a content hash.
5. **Cross-check:** anti-join of 8C/9C between the lists and HF over the same period; inspect every gap.
6. **Counters at the end** of ingestion: rulings per day, per court, per language; missing texts; failures by reason. A stage that produces 0 fails the run.
7. **Suva's files, read-only (D-040, D-051):** parse `judgements/` in place; never copy, move or edit it. Keep only docket, dates, quarter label, `Text DE`, `Text FR` and the bger.ch link. Drop the author section, staff codes and every intranet (SharePoint) link; parse the workbook's cells only, never its file properties. Take each export's docket from its bger.ch link, not from the file name alone (one name has a space and a suffix). Derived files go to `data/derived/` while D-031 is open. Then run the completeness check of §1.

DuckDB starter (to adapt after reading the actual schema):

```sql
INSTALL httpfs; LOAD httpfs;
CREATE VIEW bger AS SELECT * FROM 'hf://datasets/voilaj/swiss-caselaw/data/bger.parquet';
SELECT docket_number, decision_date, publication_date, language, length(full_text) AS n_chars
FROM bger
WHERE decision_date BETWEEN '2025-06-01' AND '2026-06-30';  -- wide window (publication can lag decision by ~10 weeks): join on docket afterwards
```

## 8. Licences and legal (non-lawyer reading; Suva to confirm)

- Federal Court rulings and BGE are not protected by copyright (art. 5 para. 1 let. c and para. 2 CopA): copy, transform, embed, redistribute. Cite docket, date and "Federal Supreme Court".
- Systematic copying of the search application's database could touch unfair-competition law: keep the crawl for our use; do not republish the site's index structure.
- Rulings are anonymised but rich in health data, and they name lawyers and institutions: never try to re-identify, never add, infer or join personal data; show and log the published text as published (D-038). Hosting and inference in Switzerland in the target architecture.
- Suva's files in `judgements/` carry personal data of Suva staff: the exports name their authors (with staff codes and job titles), and the workbook links to Suva's intranet and carries personal names in its file properties. We keep only docket, dates, quarter label, `Text DE`, `Text FR` and the bger.ch link; the rest never appears in any output, prompt, log, UI, report, deck or video, and a test checks it; only the data layer's database may keep the author field and the hyperlink target as data, in git-ignored stores (D-051 as amended, PROPOSED; D-038; Q-26). `judgements/` itself is never edited (D-040).
- Suva's summaries are Suva's own texts, not rulings: art. 5 CopA does not free them. The organisers published them, with Suva's list and deck, in the public template without a licence. Keep them unchanged in `judgements/` (D-040), credit Suva, and do not relicense them: `NOTICE` says they are not covered by our licences (D-045, Q-15). Copies or derivatives follow D-031.
- Our licences (D-041): code Apache-2.0 (the template's `LICENSE`, imposed); report CC-BY-4.0 (the template's License section, which we read as covering the report; its scope is asked in Q-24); `docs/` and the datasets we create: D-048 (while open: CC-BY-4.0 and CDLA-Permissive-2.0, in a licence map in `README.md`).
- SLDS requires attribution; `rcds` is share-alike; lexifina has no licence.
- The report's section 4 "Data" is written from this file (§1, §2, §8, §9): what we used, where it came from, its licence, what is personal and how it is kept out of outputs, and the consent question (we use only published, anonymised rulings and the partner's own material, and collect no data from people). Its "References" credit Suva's examples and OpenCaseLaw.

## 9. What may be committed

| Data | Git | Notes |
|---|---|---|
| Crawl manifests (docket, dates, subject area, star, URL, hash) | yes, `data/public/` | |
| Snapshot of public ruling texts used by `make run` | yes if ≤ 100 MB total in `data/`; otherwise a release asset with a hash and a download script | GitHub refuses files over 100 MB |
| Derived features, signals, our scores and summaries of public rulings | yes | |
| Anything derived from `judgements/`: labels per docket, few-shot digests, prompts, replay caches and `llm_calls` that contain them, test fixtures, style notes that quote Suva | **OPEN** (D-031, Q-15). While open: `data/derived/` (git-ignored), which `make run` reads when present and regenerates otherwise; nothing derived is committed before the answer (hard due: Fri 22:00, D-031) | aggregate metrics (recall, F2, precision and hits at 30, counts) are fine in any case; refer to Suva's files by path (`judgements/…`) |
| Suva's list, summaries and deck supplied by the template (`judgements/`, the pitch PDF) | **already in git** (template, D-040); never moved, renamed, edited or deleted | the SHA-256 manifest of `judgements/` (`docs/SUVA_DATA.md` §1) guards against edits (`docs/EVAL.md` T28) |
| Suva material received outside the template | **no**: `data/private/` (git-ignored) until Suva clears it (D-019) | share it through the team's private channel |
| Author names, staff codes, intranet links and file properties of Suva's files | **never**, in any file we write (D-051) | they stay only where the template put them |
| Model weights and checkpoints | **never** (the template's `.gitignore`: `*.bin`, `*.safetensors`, `*.gguf`, `*.ckpt`, `*.pt`) | downloaded at image build time: a build-time dependency listed in the report's target architecture |
| `<TeamName>_Report.pdf` (our registered team name, no spaces; Q-22) | **yes**, at the repo root (D-039) | the PDF of `technical_report.md`, max 6 pages without references |
| Keys, `.env` | never | `.env.example` only (the template's `.gitignore` already ignores `.env` and `.env.*` and keeps `.env.example`) |

**`.gitignore` (D-044, PROPOSED):** our lines are appended at the end of the template's file, in a marked block; the template's lines are never replaced, reordered or deleted. The block, and what is not ignored on purpose, live in one place: `docs/agents/platform.md` step 3. Change them there, not here.

## 10. Datasets to build (instructions for the team's agents)

**Single home of the dataset list: other files point here.** The kit ships no dataset. The team's agents rebuild each one below with code in `src/` or `eval/`, never by hand, and check it against the expected values. Those values were measured during preparation (27 Nov, §6) with reference scripts kept outside the repo: rewrite the logic in `src/crawl/`, do not copy them. A mismatch is never fixed by editing data: investigate it, record the reason in `docs/STATE.md` §3, and tell the lead. No build settles an open question: each one stores both dates and both readings while D-050 is open.

| Id | Dataset | Built from | Code (role) | Output | Expected values and checks |
|---|---|---|---|---|---|
| DS1 | **Federal Court population**: one row per decision (docket, decision date), decided 1 Jul 2025 to 30 Jun 2026, extended to the rulings put online up to 15 Sep 2026 (D-050). Fields: docket, decision date, `publication_date` and its source (`neuheiten`; `hf_poller` from 19 May 2026) or empty, `publication_date_approx` and its quality (`exact`, `approx_first_seen`, `unknown`), language, court, `Gegenstand`, subject area (UV, IV, MV, other) and the rule that set it, cleaned length, text signals (mentions of Suva, CNA, INSAI, LAA/UVG, accident insurance), quarter under each definition. No Suva label | HF `data/bger.parquet` at a pinned commit (`35b17aa9c3fad71011b72f78f6ab79650ec0cf96` reproduces the counts); entscheidsuche as an independent cross-check; the Neuheiten pages where reachable (§3) | `src/crawl/population.py` (crawl) | `data/public/population.parquet`, `data/public/manifest_<quarter>.csv` (two flags per ruling); counts and source revisions in `results/ingestion.json` | by decision date 1,749 / 1,931 / 2,005 / 2,096 (Q3/2025 to Q2/2026), with the court and language split of §6; HF and entscheidsuche agree on all decisions but one (2E_5/2024, HF only). A newer HF commit may add a few late rulings: report the difference with its dockets |
| DS2 | **Q2/2026 candidate set**: the union of the decision-date and publication-date populations of Q2, each ruling flagged under both definitions | DS1; the team's 2,096 list (`docs/STATE.md` §2) | `src/crawl/population.py` (crawl) | `data/public/manifest_2026Q2.csv` | about 2,677 rulings; the decision-date part equals the team's 2,096 list exactly (a docket on one side only goes to the review list, `docs/agents/crawl.md` step 3); about 2,060 by publication date, flagged `approx_first_seen` before 19 May 2026 until the Neuheiten pages give the exact date |
| DS3 | **Texts and considerations** of every ruling of DS2 and of the labelled quarters | HF `full_text` and `structure/erwaegungen_paragraphs`; bger.ch only for gaps (§7) | `src/crawl/` (crawl) | `data/public/` snapshot (size rule of §9) | a text, or a counted reason, for every ruling; all 59 listed Federal Court rulings and the 23 Q3/2025 summaries have a text in HF; fidelity sample of about 20 rulings (`docs/agents/crawl.md` step 5) |
| DS4 | **Suva labels per docket**: the 60 rows of the relevance list joined to DS1 | `judgements/` through the S0 parser (D-051); DS1 | S0 parser (crawl) | `data/derived/` (git-ignored while D-031 is open); counts only in `results/` | 59 Federal Court rows (28 in Q4/2025, 31 in Q1/2026) and 1 cantonal row out of reach (Q-28); 59 of 59 in their labelled quarter by decision date (T30) |
| DS5 | **Suva summaries, parsed**: docket, dates, `Text DE`, `Text FR` and the bger.ch link only | the 55 exports, S0 parser | S0 parser (crawl; used by summarise) | `data/derived/` while D-031 is open | 55 exports; 82 distinct Federal Court rulings with DS4 (T29); nothing from the author section (T31) |
| DS6 | **Evaluation sets**: per labelled quarter, the decision-date population with positives, hard negatives, easy negatives and the must-hit subset (`docs/GLOSSARY.md`), plus its publication-date reading; the summary hold-out (`docs/EVAL.md` §4) | DS1, DS4, DS5 | `eval/` (eval) | frozen manifest with SHA-256 and a git tag (`docs/agents/eval.md` step 2); per-docket gold in `data/derived/` while D-031 is open | Q4/2025: 28 positives, 104 hard negatives, 1,799 easy negatives; Q1/2026: 31 positives, 131 hard negatives, 1,843 easy negatives; must-hit 22 and 10; hold-out 23 test and 32 development rulings |
| DS7 | **Smoke set**: the 33 rulings of the team's gateway test (`docs/EVAL.md` §3b) | DS1, DS3, DS4, DS5 | `eval/` (eval) | docket list without labels in `eval/smoke_set.txt`; texts and labels in `data/derived/` while D-031 is open | 33 rulings: 14 with an export in `judgements/`, 14 negatives from courts 8C, 9C and 9D, 5 easy negatives |
| DS8 | **Boundary check**: publication dates of the 11 boundary dockets of D-050 | the Neuheiten pages (§3); HF dates only to narrow the days | `src/crawl/` (crawl) | `results/boundary_check.json` and `docs/STATE.md` §3 | T32; reported to the lead at once |

**Order.** DS1 and DS2 in the first hour: they need no access to bger.ch. Then DS4 and DS5 (the S0 parser), DS7 (so the first model call already runs on it), DS3, and DS6 before the first measurement. DS8 as soon as bger.ch answers a polite request. Every builder writes its counts and its source revisions (HF commit, entscheidsuche read date, crawl dates) to `results/ingestion.json`, so `make run` can replay them and the report can cite them.
