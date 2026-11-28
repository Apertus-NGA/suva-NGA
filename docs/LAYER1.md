# Layer 1 — the candidate gate

Measured Fri 27 Nov 2026, about 23:20 CET, on the local cache and on one read of Hugging Face `voilaj/swiss-caselaw`. This is the gate in `src/courts.py`. It is not a relevance score (D-021 stays open) and it does not settle which courts can be relevant (Q-06).

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
