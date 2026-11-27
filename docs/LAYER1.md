# Layer 1 — the candidate gate

Measured Fri 27 Nov 2026, about 23:20 CET, on the local cache and on one read of Hugging Face `voilaj/swiss-caselaw`. This is the gate in `src/courts.py`. It is not a relevance score (D-021 stays open) and it does not settle which courts can be relevant (Q-06).

The table is `data/cache/layer1.parquet`, rewritten by `python3 src/courts.py --all`. `data/` is git-ignored. Columns: `docket`, `subject`, `text`, `kept`. `text` is the text decision (`kept_text`, `text_clear`, `text_absent`), not the ruling.

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

`data/cache/layer1.parquet`, 6,055 rows, 985 kept.

| `subject` | `text` | kept | Rulings |
|---|---|---|---|
| `wrong_court` | `text_clear` | no | 4,069 |
| `subject_out` | `text_clear` | no | 1,001 |
| `kept_subject` | `text_clear` | yes | 717 |
| `kept_subject` | `kept_text` | yes | 224 |
| `wrong_court` | `kept_text` | yes | 27 |
| `subject_out` | `kept_text` | yes | 12 |
| `subject_missing` | `text_clear` | yes | 5 |

A ruling is kept when the subject decision keeps it (`kept_subject` or `subject_missing` on an allowed court and letter) or when the text names Suva, CNA, INSAI, or an accident or military insurance term. Both reasons are stored. The text decision adds 39 rulings the subject decision would have dropped (27 other courts, 12 out-of-list matters).

The cache column `relevance` marks 82 rulings `relevant`. All 82 are `kept_subject` (62 also `kept_text`, 20 `text_clear`). None of them needed the empty-subject rule or the text rule. This column is the cache's own flag, not Suva's list of 59 (`docs/DATA.md` §6).

## 4. What the code does

`decide` in `src/courts.py` stores the two reasons. Courts 8 and 9 keep the social rubrics in `docs/DATA.md` §5, plus military insurance. Court 4 keeps contract law and civil liability. The letter has to match (8 and 9: C, D, F, G; 4: A, D, F, G). A trailing `*` on the rubric is ignored.

`python3 src/courts.py` with no argument only runs the built-in checks. `python3 src/courts.py --all` rewrites the parquet. `--limit N` writes the first N rows of the cache. `--dry-run` writes nothing.
