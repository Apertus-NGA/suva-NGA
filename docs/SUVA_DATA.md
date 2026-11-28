# SUVA_DATA: what Suva's data in `judgements/` contains

> **Status: v0 PROPOSAL (27 Nov 2026).** Owner: `lead` until D-024 names a data owner. Facts measured on the official template at commit `c6e50ba` (Fri 27 Nov 11:30), read-only. Facts are labelled as such; §5 holds **inferences** and working assumptions, each tied to an open question. This file quotes no Suva text, names no person and reproduces no intranet link (D-051). Re-derive every number with the parser in `src/` once it exists (`docs/EVAL.md` T29).

## 1. The folder

`judgements/` came with the template (D-040): it is public, read-only for us, and never moved, renamed or edited.

| File | What it is |
|---|---|
| `BG_Urteile_2025_Q4_2026_Q1.xlsx` | Suva's list of the rulings it summarised in Q4/2025 and Q1/2026 (one sheet, 60 rows). SHA-256 `f7146cfd9e8419cd0801d30972d1220d8502b0b1a134364265eababe6bd1e86d`. |
| `Export_<court>_<number>_<year>.html` | 55 summary exports, one per ruling, each with a German and a French text. One file name has a space and a suffix: `Export_8C_176_2025 3.html` (it is the only file for 8C_176/2025, not a duplicate). |
| `read.me`, `test.txt` | Empty placeholders. |

Manifest of the folder (SHA-256 of the sorted per-file SHA-256 lines): `aee087543de78a7f81b29f1489497fec054acb053f19091c5365901327a548e0`. The deck PDF at the repo root is the same file as the deck the team analysed on Friday morning.

## 2. The relevance list (xlsx)

**Columns:** `Jahr / Quartal` (`2025 Q4` or `2026 Q1`), `Urteilsnummer / Titel` (docket, or the title of Suva's page), `Erstellt` (a timestamp), `SharePoint-Link` (a hyperlink to a page on Suva's intranet; never copy it, D-051).

| Measure | 2025 Q4 | 2026 Q1 | Total |
|---|---|---|---|
| Rows | 28 | 32 | 60 |
| Federal Court rulings | 28 | 31 | 59 |
| Cantonal decision (Kantonsgericht Basel-Landschaft, 5 Feb 2026) | 0 | 1 | 1 |
| Rows with a summary export in `judgements/` | 22 | 10 | 32 |
| Rows without one | 6 | 22 | 28 |

- **Positives only:** no negatives, no scores, no duplicates. Whether an unlisted ruling counts as "not relevant" is Q-04.
- **Courts:** 53× `8C`, 6× `9C`, 1 cantonal. One cell lacks the court prefix (`458/2025`, which resolves to `8C_458/2025` through its export).
- **Docket years** run from 2023 to 2026 (13 rows carry a 2024 docket): the docket year is the year of filing, not of the decision.
- **`Erstellt`** is when Suva created its intranet page: 17 to 76 days after the decision (median 34), always on a weekday in office hours. It is not the quarter key: 26 of 60 rows were created in the quarter after their label.
- **Quarter label:** every one of the 52 rows whose decision date is known falls inside its labelled quarter **by decision date**. Publication dates were not checked. This is the evidence behind D-050 (§4).
- The workbook's file properties carry personal names and an internal path, and a sensitivity-label stamp. Parse the cells only.

## 3. The summaries (55 HTML exports)

**Format (all 55):** a title line in the ruling's language (`BGer-Urteil <docket> vom <date>`, `Arrêt du TF <docket> du <date>`, `Sentenza del TF <docket> del <date>`), then a section `Text DE`, a section `Text FR`, a link to the ruling on bger.ch (its `docid` has the form `aza://DD-MM-YYYY-<docket>`, a stable key for docket plus decision date), and an author section. Plain paragraphs: no headings, lists or bold text.

**Languages:** all 55 have both a German and a French text. By ruling language: 22 German, 31 French, 2 Italian.

| Length | min | p25 | median | p75 | max |
|---|---|---|---|---|---|
| German words | 8 | 101 | 177 | 242 | 679 |
| French words | 11 | 129 | 226 | 287 | 697 |
| Paragraphs (both) | 1 | 2 | 3 | 4 | 8 |

The deck's sample (about 300 words) is longer than most of the set (Q-08).

**Two house styles, tied to the author** (three authors, called A, B and C here):

| | Rule-statement style (author A, 38 files) | Narrative style (authors B and C, 17 files) |
|---|---|---|
| Ruling languages | German 22, French 15, Italian 1 | French 16, Italian 1, German 0 |
| Median German length | ~160 words, 2 paragraphs | 220-290 words, 3-5 paragraphs |
| Shape | the legal rule stated directly, sometimes after a short facts paragraph | facts; "the Federal Court recalled that … (consideration reference)"; application to the case; outcome sentence |
| Consideration references | 1 file of 38 | 17 files of 17 |
| Outcome sentence | 10 of 38 | 13 of 17 |

- **For a German-language ruling, only the rule-statement style exists in the set.** The recent Q1/2026 exports are mostly narrative (7 of 10), but they cover only 1 of the 22 German-language Q1/2026 rulings of the list: "most recent" says which rulings were exported, not that Suva changed its style. Which style the experts expect is Q-30; while it is open, the style follows the ruling's language (Q-30).
- **Reference forms:** French almost always `consid. x` (one file writes "voir point x"); German mixes `E. x`, `Erw. x` and `Erwägung x` (Q3/2025 narrative files mostly `Erw.`, every Q1/2026 narrative file `E.`). Multi-references appear as "E. 4.3.2 und 4.3.3" / "consid. 4.3.2 et 4.3.3".
- **Statutes cited:** German `Art. … UVG / UVV / ATSG / BGG / EMRK / IVV`, with both `lit.` and `Bst.` for letters; French `art. … LAA / OLAA / LPGA / LTF / CEDH / RAI`, with `let.` and `par.`. This feeds the canonical references of D-037.
- **No summary cites a precedent** (no BGE/ATF volume, no other docket).
- **German and French are parallel texts:** the same number of paragraphs in 54 of 55 files and the same sequence of consideration references in 55 of 55. In 18 files the language that is not the ruling's language shows translation artefacts; in a few they change the meaning (French of 8C_656/2024, 8C_498/2024 and 8C_185/2025; German of 8C_172/2025). This sits uneasily with the challenge's "not a simple translation" (Q-27).
- **Scope:** only 20 of 55 summaries name Suva; at least 7 concern disability insurance (IV), one private daily-allowance insurance (VVG, court 4A), others another accident insurer or the substitute fund (Q-31).

**Quirks a parser must survive:** the space in `Export_8C_176_2025 3.html`; a title "Arrêt du TC" instead of "TF" in two files (8C_154, 8C_178); the missing court prefix in the title of 8C_458; a `<title>` that differs from the `<h1>` in 8C_613; one file (8C_275) with no `lang`, no `<a>` around the link and a raw `&` in the URL; the French section is never tagged `lang="fr"` (the document says `lang="de"`); straight and typographic apostrophes mixed in 23 French texts; an ordinal day in one French title ("du 1er septembre 2025", 8C_330/2025); a suffix after the date in the Italian title of 9C_65/2025 ("…, destinata alla pubblicazione negli DTF"). Parse the title date with an ordinal-tolerant pattern and no end anchor, then cross-check it against the `aza://` date of the link (equal in 55 of 55).

## 4. Joining the list and the summaries; what a "quarter" is

| | Q3/2025 (by decision date) | Q4/2025 | Q1/2026 | Total |
|---|---|---|---|---|
| List rows | (no list) | 28 | 32 | 60 |
| Summaries of listed rulings | | 22 | 10 | 32 |
| Summaries of rulings in no list | 23 | 0 | 0 | 23 |
| Distinct Federal Court rulings, list ∪ summaries | 23 | 28 | 31 | 82 |

- The 28 list rows without a summary are **all German-language** (Q-29).
- The 23 unlisted summaries were all decided between 9 Jul and 26 Sep 2025: plausibly Suva's Q3/2025 list, which the template does not ship.
- **Quarter semantics (D-050):** by decision date, 52 of 52 dated rows fit their label. By publication date, some would need implausibly fast publication: 8C_613/2025, decided Fri 27 Mar 2026 and labelled Q1, would have been put online within 4 days; 8C_366/2024, decided 23 Dec 2025 and labelled Q4, within 8 days over Christmas. Four rulings decided on 23-26 Sep 2025 that Suva summarised (8C_318, 8C_7, 8C_172, 8C_62, all /2025) are absent from the Q4 list, although any of them put online in October would belong there by publication date. The boundary dockets listed in D-050 settle it once their publication dates are looked up; 8C_802/2023, labelled Q1 and decided on 27 March 2026 like 8C_613/2025, is among them although its row carries no date. Measured on 27 Nov (HF and entscheidsuche): the rows without a date were decided 12 to 30 March 2026, so all 59 Federal Court rows fit their label by decision date (`docs/DATA.md` §6).

## 5. What follows (inferences and working assumptions, not facts)

- **Labelled sets for triage** (`docs/EVAL.md` §2): Q4/2025 (28 positives) and Q1/2026 (31 Federal Court positives) are two separate folds; never tune on the fold being measured. Negatives exist only under a closed-world assumption (Q-04): every other Federal Court ruling of the quarter, by the date definition of D-050. Q3/2025 (23 summarised rulings, no list) is for development only: no recall can be measured on it.
- **Recall ceiling:** the cantonal row cannot be found by a Federal Court crawl (59 of 60 at best, Q-28).
- **Must-hit subset:** defined once in `docs/GLOSSARY.md` (the template's "all judgements that have been summarised by a human should also be correctly identified", Q-20): the summarised rulings of a labelled quarter, 22 in Q4/2025 and 10 in Q1/2026. The 23 Q3/2025 exports are a population check (T30): the crawl checks that every ruling with an export is in its populations (`docs/agents/crawl.md`).
- **Style pool for summaries:** 55 independent summaries, not 110 (each pair is one text in two languages). For the internal hold-out, split by time and stratify by style: the internal test set is the 10 Q1/2026 exports plus the 13 German-language Q4/2025 exports (23 rulings, both styles); examples and development use the 23 Q3/2025 exports and the 9 French-language Q4/2025 exports; never put a ruling in both the prompt and the test; report the results per style. (Q1/2026 alone holds one German-language export, too few for the majority case.) Do not use a text with a meaning-changing translation error as a target in that language; prefer the ruling-language side.
- **Never filter** on the `8C_` prefix, on the docket year, or on the word "Suva" in the text (G5).
- **Personal data:** the author section, staff codes and intranet links are never reproduced in any file we write, prompt, log, UI or report; the data layer's database may keep the author field, a style key derived from it and the workbook's hyperlink target as data (D-051 as amended).

## 6. Questions this data raises

Q-02 and D-050 (which date defines a quarter), Q-04 (are the lists complete), Q-08 and Q-30 (length, style, fields), Q-15 (may derived artefacts be committed), Q-20 (must-hit subset), Q-26 (personal data in the template), Q-27 (parallel or independent French), Q-28 (cantonal decisions), Q-29 (missing German summaries, the Q3/2025 list), Q-31 (scope beyond accident insurance). All in `docs/DECISIONS.md` §3.
