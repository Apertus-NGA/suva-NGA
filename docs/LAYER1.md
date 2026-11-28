# Layer 1 — the candidate gate

Measured Fri 27 Nov 2026, about 23:20 CET, on the local cache and on one read of Hugging Face `voilaj/swiss-caselaw`. This is the gate in `src/courts.py`. §6 is the same gate made versioned, run on the database (`src/layer1/`). It is not a relevance score (D-021 stays open) and it does not settle which courts can be relevant (Q-06).

The log is `data/cache/layer1.json`, rewritten by `python3 src/courts.py --all`. `data/` is git-ignored. The contract is `docs/layer1_log.schema.json`. `text` in each asset action is the text decision (`kept_text`, `kept_contract`, `text_clear`, `text_absent`), not the ruling. The run writes no parquet: a later database is the table.

## 1. What Hugging Face holds

Dataset `voilaj/swiss-caselaw`, file `data/bger.parquet` (read from the Hub the same evening; the pinned commit used for the population counts in `docs/DATA.md` §6 is `35b17aa9c3fad71011b72f78f6ab79650ec0cf96`). Around the matter, the columns are `language`, then `title`, then `legal_area`, then `regeste`.

`legal_area` is the rubric the gate compares (`Unfallversicherung`, `Vertragsrecht`). `title` is the line just before it. On a filled row the two agree at the start: `8C_78/2025` has `legal_area = Unfallversicherung` and `title = Unfallversicherung (Unfallkausalität),`. `regeste`, the column just after, is the headnote.

The local cache `data/cache/rulings.parquet` has 6,055 rulings (3,747 German, 2,004 French, 304 Italian). Its `area` column is that rubric. When it is filled, `field_sources` says `bger_list`. Its `subject` column is the Hugging Face `title`.

## 2. The 183 blank rubrics

In courts 4, 8 and 9, 183 rulings have an empty `area`. All 183 are in the Hugging Face file. For all 183, `legal_area` is empty and `regeste` is empty. `title` is filled for 178 and empty for 5.

`area_for_gate` does not copy `title` whole (the comma and the parenthesis would miss the list). It keeps the matter at the start, before `(`, and strips a trailing comma or semicolon. `Invalidenversicherung,` becomes `Invalidenversicherung`. `Assurance-accidents (lien de causalité),` becomes `Assurance-accidents`. A rubric that is already filled is left as it is.

After that read, the 183 split as follows (measured on the cache, same evening):

| Gate reason | Rulings | What the title was |
|---|---|---|
| `kept_subject` | 40 | a rubric already in the keep list: 21 Invalidenversicherung, 6 Assurance-accidents, 4 Krankenversicherung, 2 Unfallversicherung, 2 Assurance-maladie, 2 Berufliche Vorsorge, 1 Assurance-invalidité, 1 Assicurazione contro gli infortuni, 1 Assurance militaire |
| `subject_out` | 138 | a real matter the list does not keep (debt enforcement, rent, tax, social assistance, unemployment, employment contracts) |
| `subject_missing` | 5 | no `title` either |

The five with nothing in either column are `4A_206/2026`, `4A_156/2025`, `4A_355/2025`, `4D_9/2026` and `4A_285/2026`. The gate keeps them (`subject_missing`). None of them is marked relevant in the cache. They are left as they are: Hugging Face does not have the Neuheiten rubric, and fetching it would not change recall.

## 3. The whole cache

`data/cache/layer1.json`, 6,055 assets, 993 kept. Rewritten after the insurance-contract terms were added (same evening). The line-by-line partition, with every subtotal summing back to 6,055, is `docs/layer1_trace.json`.

| `subject` | `text` | kept | Rulings |
|---|---|---|---|
| `wrong_court` | `text_clear` | no | 4,061 |
| `subject_out` | `text_clear` | no | 1,001 |
| `kept_subject` | `text_clear` | yes | 693 |
| `kept_subject` | `kept_text` | yes | 224 |
| `kept_subject` | `kept_contract` | yes | 24 |
| `wrong_court` | `kept_text` | yes | 27 |
| `subject_out` | `kept_text` | yes | 12 |
| `wrong_court` | `kept_contract` | yes | 8 |
| `subject_missing` | `text_clear` | yes | 5 |

A ruling is kept when the subject decision keeps it (`kept_subject` or `subject_missing` on an allowed court and letter) or when the text decision keeps it. Both reasons are stored. The accident and insurer terms add 39 rulings the subject decision would have dropped (27 other courts, 12 out-of-list matters). The insurance-contract terms add 8 more, all in other courts: `2C_8/2025`, `2C_9/2025`, `5A_356/2025`, `5A_435/2025`, `5A_631/2024`, `6B_1189/2023`, `6B_1274/2023`, `7B_421/2025`. None of those eight has an unemployment, old-age or tax rubric.

The bare word `Taggeld` is not a term. On this cache it occurs in 24 rulings the gate drops as unemployment insurance, and in the title `Arbeitslosenversicherung (Taggeld)` of `8C_469/2025`, which stays dropped. `LAM` is not a term either: the bare token matches a surname.

The cache column `relevance` marks 82 rulings `relevant`. All 82 are `kept_subject`. This column is the cache's own flag, not Suva's list of 59 (`docs/DATA.md` §6). The list and the Q3 summaries are counted in §5.

## 4. What the code does

`decide` in `src/courts.py` stores the two reasons. Courts 8 and 9 keep the social rubrics in `docs/DATA.md` §5, plus military insurance. Court 4 keeps contract law and civil liability. The letter has to match (8 and 9: C, D, F, G; 4: A, D, F, G). A trailing `*` on the rubric is ignored.

The text decision has two keep reasons. `kept_text` is Suva, CNA, INSAI, or an accident or military insurance term. `kept_contract` is the insurance-contract act (`VVG`, `LCA`, and the spelled-out name in German, French and Italian) or `Taggeldversicherung`. `kept_contract` does not apply when the rubric is unemployment, old-age, tax, supplementary benefits, loss-of-earnings, social assistance or family allowances. An accident or insurer term still keeps such a ruling. Each asset action in the log stores `criterion`, the value that matched: the rubric, the court digit, the letter, the term, the closed-rubric stem, or a named rule (`blank_rubric`, `empty_text`, `no_keep_term`). When a contract term matches and the closed rubric refuses it, `criterion` is that stem and `blocked_term` is the term.

`python3 src/courts.py` with no argument only runs the built-in checks. `python3 src/courts.py --all` reads the cache in batches of 256 rows, so the ruling texts are not all held at once, and writes `data/cache/layer1.json`. That log follows `docs/layer1_log.schema.json`: the run (id, clock, input checksum), the population (assets in, assets out, assets dropped), one object per action with its scope and its checks, and one object per asset with the outcome of each action. `--limit N` writes the first N rows of the cache. `--dry-run` writes nothing. `python3 src/courts.py --recall` scores the two cohorts in §5 and writes `data/derived/layer1_recall.json` in the same schema (`phase_kind` `recall_check`). That file is derived from `judgements/` and stays git-ignored (D-031). The command does not read the intranet link or the author column.

## 5. Recall on the Suva list and the Q3 summaries

Measured Fri 27 Nov 2026, about 23:55 CET, with `python3 src/courts.py --recall`, on the local cache. Rubric and ruling text are the cache columns. The quarter of a summary is its decision date (D-050 is open; Suva's own labels follow the decision date).

| Cohort | Kept | How |
|---|---|---|
| Suva list, 59 Federal Court rulings (`data/cache/labels.parquet`; the cantonal row is not in that table) | 59/59 | all `kept_subject`: 45 also `kept_text`, 3 also `kept_contract`, 11 `text_clear` |
| Q3/2025 summaries, 23 rulings decided 9 Jul–26 Sep 2025 with an export and not in the list | 23/23 | all `kept_subject`: 17 also `kept_text`, 1 also `kept_contract`, 5 `text_clear` |

The 11 list rulings and the 5 summaries with `text_clear` are disability insurance. They name neither Suva nor the accident or insurance-contract terms. The rubric is what keeps them.

`4A_106/2025` is kept by `Vertragsrecht`, and its text is `kept_contract` (it names `VVG` and `Taggeldversicherung`). A wrong rubric on that ruling would still keep it. The three list rulings whose text is `kept_contract` are disability rulings already kept by the rubric: `9C_382/2025`, `8C_377/2025`, `9C_311/2025`.

No positive needed `subject_missing` or a text reason to pass. The contract terms are the second path, not the one that carried this set.

## 6. Layer 1 on the database (`src/layer1/`)

Measured Sat 28 Nov 2026, about 02:20 CET, on a fresh PostgreSQL 17 database loaded from the pinned Hugging Face file (`35b17aa9…`, D-062). Every number in this section is in `results/layer1_validation.json` (aggregates only, D-031). The decisions are `PROPOSED` in `docs/DECISIONS.md` (D-072, D-073) until the layer-1 owner agrees.

### 6.1 What changed from `src/courts.py`

`src/courts.py` stays the reference. `src/layer1/` takes its rules, writes every decision (kept and dropped) to the data layer (D-061 to D-071), and checks itself against `courts.py` on every ruling of every run.

| Concern | `src/courts.py` | `src/layer1/` |
|---|---|---|
| Rules | constants in the code | `src/layer1/registry/layer1_filter.json`: versioned rules and a configuration checked by a pydantic model (`src/layer1/models.py`), loaded into `ops.rule` and `ops.component_version` |
| Versions | one | `V1.0.0` = `courts.py` at `4c246a8`; `V1.1.0` = text normalised (NFKC, typographic apostrophes, no-break spaces) and the accident terms widened to the forms of PR #36 (`Unfallversicherungsgesetz`, `Unfallversicherer`, `assureur-accidents`, `assicuratore infortuni`) |
| Input | `data/cache/rulings.parquet` | `corpus.ruling`, `corpus.ruling_text`, and the rubric from `corpus.subject_observation` (Neuheiten first, then the HF `legal_area`, then the head of the title, which is signalled) |
| Output | `data/cache/layer1.json` | files first, then one transaction (§6.3) |
| Label | kept or not | `in_suva_scope` = `potentially` (kept) or `out_of_scope` (dropped, score 0), D-063 |
| Reasons | `subject` and `text` | one reason code per rule that fired, with its evidence: rubric and its source, or the matched term and its offsets in the original text |
| Recall | `--recall`, a separate command | blocking check after each run on Suva's labels in `gold.label`; `make run` fails when a labelled ruling is dropped |

A version is immutable: loading a registry whose configuration, rules or code hash differ from the stored ones under the same version number fails and asks for a new version (D-064).

### 6.2 Rules (reason codes)

| Code | Kind | Fires when |
|---|---|---|
| `L1_KEEP_RUBRIC` | keep | court 4, 8 or 9, allowed letter, rubric in the court's keep list |
| `L1_KEEP_RUBRIC_MISSING` | keep | court 4, 8 or 9, allowed letter, no rubric from any source |
| `L1_KEEP_ACCIDENT_TERM` | keep | the text names Suva, CNA, INSAI, an accident or military insurance term |
| `L1_KEEP_CONTRACT_TERM` | keep | the text names the insurance-contract act or `Taggeldversicherung`, and the rubric is not a closed one |
| `L1_FLAG_CLOSED_RUBRIC` | flag | a contract term matched but the rubric is closed (unemployment, old-age, tax…): recorded, not kept |
| `L1_DROP_WRONG_COURT` | drop | the docket is not court 4, 8 or 9 |
| `L1_DROP_WRONG_LETTER` | drop | court 4, 8 or 9 with a letter outside the list |
| `L1_DROP_RUBRIC_OUT` | drop | the rubric is not in the court's keep list |
| `L1_SIGNAL_RUBRIC_FROM_TITLE` | signal | the rubric was read from the head of the title, not from a rubric field |

Each ruling gets exactly one subject rule (a `KEEP_RUBRIC*` or a `DROP_*`) and any text rules. A ruling is kept if any keep rule fires. The text rules never drop: a ruling dropped by its subject and kept by a term carries both reasons.

### 6.3 What a run writes

1. `data/runs/<run_id>/decisions.jsonl`: one record per ruling (rules fired, evidence, rubric source, fingerprint of the inputs).
2. `data/runs/<run_id>/layer1_log.json`: the owner's log (`docs/layer1_log.schema.json`, `layer1-log-1`), built by `courts.build_layer1_log`.
3. `data/runs/<run_id>/manifest.json`: SHA-256 of both files, the version and the profile.
4. One transaction in PostgreSQL: one `ops.span` per ruling under the run's root span, one `triage.assessment` per ruling with a German explanation (`Vorauswahl bestanden: …` or `Von der Vorauswahl ausgeschlossen: …`), one `triage.assessment_reason` per rule fired with its evidence offsets, one `ops.log_event` per decision, and the run metrics (`ops.run_metric`).

Ids are `uuid5` of the run and the ruling: loading the same files twice changes nothing. A run with no ruling fails and leaves no assessment. A failed run keeps its status `failed` and its error span. `data/runs/` is git-ignored.

### 6.4 Commands

```
make db-up && make db-deploy                       # or DATABASE_URL=... for another server
make db-registry                                   # versions, rules, profiles
make ingest-base PARQUET=path/to/bger.parquet      # HF file at the pinned commit
make ingest-gold                                   # Suva's labels, columns A-B and export links only (D-051)
make layer1                                        # default profile (V1.1.0); PROFILE=layer1_reference for V1.0.0
make layer1-recall                                 # blocking recall of the latest run
uv run python -m src.layer1 report --run A --run B # aggregates into results/layer1_validation.json
```

`make run` calls layer 1 as stage S2 when `DATABASE_URL` is set and the corpus is loaded, then checks recall; otherwise S2 is skipped and says why.

### 6.5 Measured on the base dataset

6,055 rulings (Q4/2025, Q1/2026, Q2/2026 under both date readings, and the 23 Q3/2025 rulings of `judgements/`).

| | `V1.0.0` (profile `layer1_reference`) | `V1.1.0` (profile `default`) |
|---|---|---|
| Kept (`potentially`) | 931 | 935 |
| Dropped (`out_of_scope`) | 5,124 | 5,120 |
| Same subject and text decision as `courts.py` | 6,055 / 6,055 | 6,038 / 6,055 |
| Suva list, 59 Federal Court rulings | 59/59 | 59/59 |
| Q3/2025 summaries not in the list | 23/23 | 23/23 |
| All 55 summary exports | 55/55 | 55/55 |
| Kept in the Q2/2026 union (2,677) | 380 | 383 |
| Run time on a laptop, files and database | about 20 s | about 23 s |

`V1.1.0` keeps 4 more rulings and drops none that `V1.0.0` kept. The 4 are `2C_462/2024`, `2C_533/2025` and `7B_400/2024` (other courts, `assurance-accidents` in the plural) and `8C_170/2026` (an unemployment ruling that names an accident insurer). The 13 other rulings that differ from `courts.py` are kept by both versions and gain an accident-term reason. 931 here against 993 in §3: §3 ran on the local cache `data/cache/rulings.parquet`, which no repo code builds and which was not available for this measure. `courts.py` and `V1.0.0` agree on all 6,055 rulings of the HF file, so the gap of 62 comes from the input, not the code; which columns differ is not measured.

The rubric read from the title is a matter, not a Neuheiten rubric: `4A_127/2025` reads `contratto di assicurazione`, which no court-4 rubric matches, and is kept by its contract term. Fetching the Neuheiten rubric (`corpus.subject_observation`, source `neuheiten`) would replace that reading; the crawl does not write it yet.

