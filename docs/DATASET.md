<!-- Same text as the Hugging Face dataset card (suva-nga/bger-rulings). Edit both together. -->
# Swiss Federal Supreme Court rulings for the Suva challenge (Hack Apertus Zurich 2026)

Every ruling of the Swiss Federal Supreme Court (Bundesgericht, BGer) **decided between 1 October 2025 and 30 June 2026** (6,032 rulings, all divisions), plus 23 earlier rulings that have a human reference summary: **6,055 rulings** with full text, metadata, Suva's relevance labels and Suva's human-written summaries.

Built by team `suva-nga` for the Suva challenge at Hack Apertus Zurich. The code that builds it is in the team's GitHub repository (`Apertus-NGA/suva-NGA`, `src/suva_data/`, plan in `docs/ARCHITECTURE.md`).

## What is in this repository

| Path | What it is |
|---|---|
| `dump/suva.sql.gz` | PostgreSQL 16 dump of the finished database (65 MB). Loading this is all a user needs. |
| `snapshot/` | The raw inputs the database was built from (147 MB), so the build can be repeated offline. |
| `snapshot/bger_list/` | bger.ch daily "Neue Entscheide" list pages, 1 July 2025 to 30 June 2026 |
| `snapshot/entscheidsuche/` | entscheidsuche.ch search-API responses (full texts) and 22 per-ruling HTML files |
| `snapshot/swiss_caselaw/` | The rows of `voilaj/swiss-caselaw` (pinned revision) that fall in the window |
| `tables/*.parquet` | The same data as Parquet tables (68 MB), readable without a database. See "Parquet tables" below. |
| `tables/schema.sql` | The readable PostgreSQL table definitions |
| `manifest.json` | sha256 of every snapshot file and every table file, the pinned upstream revision, and the dataset fingerprint |
| `quality_report.md` | Counts per source, where each value comes from, conflicts between sources, known gaps |

## Numbers

| Decision quarter | Rulings | Relevance |
|---|---|---|
| 2025 Q3 (extra cases) | 23 | 23 relevant (they have a Suva summary) |
| 2025 Q4 | 1,931 | 28 relevant, 1,903 not relevant |
| 2026 Q1 | 2,005 | 31 relevant, 1,974 not relevant |
| 2026 Q2 | 2,096 | unknown (the prediction target of the challenge) |

- 59 relevance labels from Suva's list for Q4/2025 and Q1/2026. That list is complete, so every other ruling decided in those quarters counts as not relevant (view `v_relevance`).
- 55 rulings have a human reference summary in German and in French (110 texts, table `gold_summaries`).
- Quarters are defined by **decision date**, as confirmed by the challenge organiser.

## Sources and hierarchy of truth

When sources disagree, the higher one wins, and the disagreement is recorded in the `conflicts` table.

1. **bger.ch** (official website): daily lists. Only source of the publication date and the "marked for publication" star.
2. **entscheidsuche.ch** (open-data mirror): full text for 6,053 rulings.
3. **Swiss Case Law** (`voilaj/swiss-caselaw`, revision `35b17aa9c3fad71011b72f78f6ab79650ec0cf96`): full text for all rulings, plus outcome, cited rulings and cited statute articles. These three are extracted by a third party and should be treated as hints.

Every source's own record and text is kept (`source_records`, `ruling_texts`); `rulings.field_sources` says where each value came from.

## Parquet tables

Exported from the database by `uv run python -m suva_data export`, in a fixed order, so the same database always gives identical files.

| File | Rows | Content |
|---|---|---|
| `tables/rulings.parquet` | 6,055 | **Start here.** One row per ruling: metadata, the full text to use (`text`), `relevance` (`relevant` / `not_relevant` / `unknown`) and its basis, `has_gold_summary`. |
| `tables/gold_summaries.parquet` | 110 | Suva's reference summaries (German and French) |
| `tables/labels.parquet` | 59 | Suva's relevance labels with the Excel metadata |
| `tables/ruling_texts.parquet` | 12,125 | Every source's text for every ruling; `is_canonical` marks the one used |
| `tables/source_records.parquet` | 17,557 | Every source record with its status |
| `tables/conflicts.parquet` | 1,103 | Disagreements between sources |
| `tables/statute_refs.parquet` | 74,799 | Law articles cited by each ruling |

```python
import pandas as pd
rulings = pd.read_parquet("hf://datasets/suva-nga/bger-rulings/tables/rulings.parquet")
train = rulings[rulings.relevance != "unknown"]            # labelled quarters (Q4/2025, Q1/2026) plus 23 extra positives
target = rulings[rulings.decision_quarter == "2026 Q2"]    # the prediction target

from datasets import load_dataset
gold = load_dataset("suva-nga/bger-rulings", "gold_summaries", split="train")
```

In `rulings.parquet`, an empty `starred` or `publication_date` means "not known", not "no".

## Database tables

| Table / view | Rows | What it holds |
|---|---|---|
| `rulings` | 6,055 | One row per ruling (case number + decision date): division, language, publication date, star, subject area, subject line, outcome, cited rulings, official link. `field_sources` says which source each value came from; `flags` marks anything unusual. |
| `ruling_texts` | 12,125 | Full text per source, stored exactly as received. `is_canonical` marks the one to use; `bad_reason` marks rejected texts. |
| `source_records` | 17,557 | Every record from every source, unchanged, with a status: used, duplicate, or left out (with the reason). |
| `conflicts` | 1,103 | Every disagreement between sources and every rejected value. |
| `labels` | 59 | Suva's relevance labels. `metadata` keeps the Excel title, row, "Erstellt" date and SharePoint link. |
| `gold_summaries` | 110 | Suva's human summaries: one German and one French text for each of 55 rulings, with title, author and source link. |
| `statute_refs` | 74,799 | Which law articles each ruling cites (extracted by a third party). |
| `v_relevance` (view) | 6,055 | `relevant`, `not_relevant` or `unknown` for every ruling, with the basis. |
| `raw_files`, `ingest_runs` | | Checksums of the snapshot files; a log of pipeline runs. |

Useful queries:

```sql
-- text to use for a ruling
SELECT t.text FROM rulings r JOIN ruling_texts t ON t.ruling_id = r.id AND t.is_canonical WHERE r.docket = '8C_72/2025';
-- training set for triage (labelled quarters)
SELECT r.*, v.relevance FROM rulings r JOIN v_relevance v ON v.ruling_id = r.id WHERE v.relevance <> 'unknown' AND r.in_window;
-- prediction target
SELECT * FROM rulings WHERE decision_date BETWEEN '2026-04-01' AND '2026-06-30';
-- reference summaries
SELECT r.docket, g.language, g.title, g.body FROM gold_summaries g JOIN rulings r ON r.id = g.ruling_id WHERE g.is_current;
```

## How Suva's files were handled

- **Excel list** (60 rows): 59 loaded. The cantonal row (Kantonsgericht Basel-Landschaft, 5 February 2026) is dropped: the organiser confirmed it was a mistake. The row "BGer-Urteil 458/2025 vom 18. November 2025" lacks its division prefix and is mapped to `8C_458/2025`. The "Erstellt" column is Suva's internal workflow date: it is stored but never used (for 25 of 59 rows it falls in a different quarter than Suva's own quarter column).
- **Summary files** (55): the case number comes from the file name; the decision date in each title matches the ruling's date for all 55. 32 of the 55 rulings are also in the Excel list; the other 23 were decided in Q3/2025.

## What combining the sources found

| Finding | Count | What the pipeline did |
|---|---|---|
| Exact duplicate rows in Swiss Case Law | 17 | Collapsed into one ruling; fields merged |
| Same case number, two real rulings (7B_1356/2025) | 1 | Kept as two rulings |
| Swiss Case Law text is an error page | 3 | entscheidsuche.ch text used |
| entscheidsuche.ch search API cuts the text at ~100,000 characters | 22 | Full text read from the per-ruling HTML file |
| Ruling not on entscheidsuche.ch | 2 | Swiss Case Law text used, flagged |
| Language differs between the two text sources | 45 | entscheidsuche.ch value used (checked against the ruling header: correct in at least 43) |
| Texts differ in a few characters | 185 | Both stored; entscheidsuche.ch is canonical |
| Subject line / area worded differently | 776 / 58 | bger.ch list value used |

Texts are compared ignoring whitespace (the sources space the same HTML differently); every letter, digit and punctuation mark must match.

## Reproducibility

- Building twice from an empty database gives the same fingerprint (`e0fc5cd51da0e579598f50092d3cd3ae0ed65698dbaa1769cab28226f2911699`, also in `manifest.json`). The fingerprint is a hash of the content, without row ids and timestamps.
- A fresh PostgreSQL loaded from `dump/suva.sql.gz` has the same fingerprint.
- Every snapshot file has its sha256 in `manifest.json`; the build refuses to run on a snapshot that does not match.
- The bger.ch list pages cannot be downloaded again by a script (the site refuses non-browser clients), so the copies in `snapshot/bger_list/` are the reproducible input for that source. The other two sources can be re-fetched and are checked by checksum.

## Known gaps and limits

- **Publication star and publication date are not known for 618 and 176 of the Q2/2026 rulings.** bger.ch refused automated requests, so the daily lists after 30 June 2026 are missing. In the database these values are NULL (not known), never "false".
- 2 rulings (2E_5/2024, 8C_646/2025) are not on entscheidsuche.ch and have only the Swiss Case Law text.
- 3 Swiss Case Law texts are error pages; the entscheidsuche.ch text is used for them.
- In 185 rulings the two full-text sources differ in a few characters (for example a corrected citation). Both texts are stored.
- One row of Suva's list is a cantonal decision; the organiser confirmed it is out of scope and it is not included.

## How to use

```bash
# from the code repository
uv sync
uv run python -m suva_data pull      # downloads this dataset; puts the dump where Postgres loads it
docker compose up -d db              # database ready on localhost:54329
uv run python -m suva_data verify    # checks + fingerprint
```

To rebuild the database from the raw snapshot instead of loading the dump: `uv run python -m suva_data build`. The result has the same fingerprint as `manifest.json`.

## Licences and origin

- Court rulings are official texts and not protected by copyright (Art. 5 Swiss Copyright Act).
- The Swiss Case Law rows are CC0. entscheidsuche.ch is an open-data project.
- The relevance labels and the reference summaries were written by **Suva** and published in the public challenge repository (`HackApertus/zurich-suva`). They are included here for the hackathon; ask Suva before reusing them elsewhere.
