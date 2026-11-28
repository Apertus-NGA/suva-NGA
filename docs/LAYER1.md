# Layer 1 — the candidate gate

Status: PROPOSED (D-060). Measured Sat 28 Nov 2026, 00:00–00:40 CET, on the data layer's export `data/tables/rulings.parquet` (6,055 rulings: every Federal Supreme Court ruling decided 1 Oct 2025 to 30 Jun 2026, plus 23 rulings decided earlier that Suva summarised). This is the gate in `src/courts.py`. It is not a relevance score (D-021 stays open) and it does not settle which courts can be relevant (Q-06).

Previous version: commit `2d127cb` (985 kept). Section 6 lists what changed.

The log is `data/cache/layer1.json`, rewritten by `python3 src/courts.py --all`. `data/` is git-ignored. The contract is `docs/layer1_log.schema.json`. `text` in each asset action is the text decision (`kept_text`, `kept_contract`, `text_clear`, `text_absent`), not the ruling. The run writes no parquet: a later database is the table.

## 1. The rule

A ruling is kept when **either** decision keeps it. Every ruling gets one reason from each step.

```
                          every ruling
                               │
          ┌────────────────────┴────────────────────┐
          ▼                                         ▼
  SUBJECT DECISION                           TEXT DECISION
  court 4, 8 or 9 with an allowed letter?    text names Suva, CNA, INSAI, or an
     no  → wrong_court / wrong_letter        accident or military insurance term?
     yes → Neuheiten rubric filled?             yes → kept_text
             yes → kept matter?                 no  → text_clear (absent text: text_absent)
                     yes → kept_subject
                     no  → subject_out
             no  → subject line in the ruling?
                     no  → subject_missing  ─┐
                     yes → names a kept      │
                           matter?           │
                             yes → kept_subject
                             no  → subject_unknown
                                             │
                                             ▼
                          APERTUS reads the matter (only when the text decision did not keep it)
                             kept matters ≥ 10% probability, no answer, or failed call → kept
                             kept matters < 10% probability                            → apertus_out
```

Kept matters, by court and proceedings letter:

| Court | Letters | Matters kept (codes of `src/areas.py`) |
|---|---|---|
| 8, 9 | C, D, F, G | accident (UV), military (MV), disability (IV), health insurance (KV), occupational pensions (BV) |
| 4 | A, D, F, G | contract law (CONTRACT), civil liability (LIABILITY) |

The names of each matter in German, French and Italian are in `docs/DATA.md` §5 and in `src/areas.py`.

## 2. How the matter is read

- **The Neuheiten rubric** (`area` in the data layer) is the court's own classification. When it is filled, code decides: a kept matter keeps the ruling, any other matter drops it (`subject_out`).
- **The subject line** (`subject` in the data layer, Hugging Face `title`) is read when the rubric is empty, which is the case for 442 of the 2,096 rulings decided in Q2/2026 (their Neuheiten pages are not in the snapshot). Only the part before the first bracket, comma or semicolon is read: `Invalidenversicherung, Invalidenrente` gives `Invalidenversicherung`.
- **Names are matched by name, not as exact strings** (`src/areas.py`): `Assurance-accident` (singular), `Assicurazione contro le malattie`, typographic apostrophes and a trailing `*` are all read. Whole names only: `invalidit` alone would match `Prévoyance professionnelle (rente d'invalidité)`, and `milit` alone would match `Militärpflichtersatz`.
- **A subject line that names no kept matter is not a decision.** On court 4 the subject line names the dispute (`contrat de travail`, `Mietvertrag`), never the rubric (`Vertragsrecht`). On courts 8 and 9 it usually names the matter, but not always (`Rechtsverweigerung (Prozessvoraussetzung)` for a disability case, `Condition de recevabilité`). In both cases code sets `subject_unknown` and Apertus reads the matter.

## 3. The Apertus reading

`src/area_judge.py`, called through the shared client (`src/llm/`, G2), prompt `area_judge@2`.

- Input: the first 6,000 characters of the ruling (header, parties, subject line, start of the facts), delimited as data; control tags neutralised (G4).
- Apertus picks one of eight letters: the seven matters above, or "another matter". The answer is one token, read from its log-probabilities (`max_tokens` 1, `top_logprobs` 20), so it comes with a probability (D-021 point 4).
- The ruling is dropped (`apertus_out`) only when the probability of the kept matters on its court is below 10%. Otherwise `kept_apertus`. An answer that is not one of the letters (`no_answer`) or a failed call (`failed`) keeps the ruling (D-021 point 7). The matter Apertus read and the probability are stored for every ruling it read.
- Apertus chooses from a list; it never writes an identifier (G1).
- Without `--apertus` the step is not run and those rulings are kept as `pending`.

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

### Measurement

`python -m src.area_judge --court N --limit 300 --seed 1 --mode live`: 300 rulings of one court whose Neuheiten rubric is known, Apertus's reading compared with the rubric. The thresholds were written in `src/area_judge.py` before the first run and not changed.

| Court | In-scope kept (threshold ≥ 97%) | Out-of-scope dropped (≥ 70%) | Same decision on a repeat of 50 (≥ 98%) | Exact matter |
|---|---|---|---|---|
| 4 | 157 of 158, pass | 5 of 142, **fail** | 50 of 50, pass | 181 of 300 |
| 8 | 178 of 178, pass | 79 of 122 (65%), **fail** | 48 of 50 (96%), **fail** | 268 of 300 |
| 9 | 124 of 124, pass | 153 of 176, pass | 50 of 50, pass | 230 of 300 |

Files: `results/area_judge_court4.json`, `_court8.json`, `_court9.json`.

Reading: the step is safe (1 in-scope ruling of 460 dropped) and filters on courts 8 and 9, but barely on court 4, where it reads almost every ruling as contract law. On court 4 most rulings it reads really are contract law (employment, lease, sale), so keeping them is correct; its weakness is the few out-of-scope court-4 rulings it does not drop, which costs scoring work, not recall. An earlier prompt (`area_judge@1`, other options list) was measured once on court 4 (300 rulings, seed 0) before this version.

## 4. The whole data set

`python3 src/courts.py --all --apertus live` on the 6,055 rulings, then again with `--apertus replay`: the two tables are identical.

| Subject | Text | Apertus | Rulings | Kept |
|---|---|---|---|---|
| `kept_subject` | `kept_text` | `not_asked` | 237 | 237 |
| `kept_subject` | `text_clear` | `not_asked` | 705 | 705 |
| `subject_unknown` | `text_clear` | `kept_apertus` | 92 | 92 |
| `subject_unknown` | `text_clear` | `apertus_out` | 43 | 0 |
| `subject_unknown` | `kept_text` | `not_asked` | 3 | 3 |
| `subject_missing` | `text_clear` | `kept_apertus` | 5 | 5 |
| `subject_out` | `kept_text` | `not_asked` | 10 | 10 |
| `subject_out` | `text_clear` | `not_asked` | 864 | 0 |
| `wrong_court` | `kept_text` | `not_asked` | 30 | 30 |
| `wrong_court` | `text_clear` | `not_asked` | 4,066 | 0 |
| | | | **6,055** | **1,082** |

Read by Apertus, by court: court 4, 92 (6 dropped, all `mainlevée définitive`); court 8, 24 (14 dropped: social assistance, unemployment insurance, family allowances); court 9, 24 (23 dropped: tax, old-age insurance).

Against the data layer's relevance column (Suva's list of 59 for Q4/2025 and Q1/2026, plus the 23 summarised rulings): 59 of 59 and 82 of 82 kept, all of them by `kept_subject`. None went through the Apertus step. This is measured on the labels the kept set was written against, so it is not an independent test; zero misses in 59 is consistent with a true miss rate of up to about 5%.

| | Rulings | Kept |
|---|---|---|
| Q4/2025 + Q1/2026 (decision date) | 3,936 | 643 |
| Q2/2026 | 2,096 | 416 |
| of which decided in June 2026 | 773 | 154 |

## 5. The table and the commands

`data/cache/layer1.parquet` (git-ignored, under `data/`), one row per ruling: `docket`, `subject`, `text`, `apertus`, `matter`, `in_scope_probability`, `kept`. `text` is the text decision, not the ruling.

| Command | What it does |
|---|---|
| `python3 src/courts.py` | the built-in checks only |
| `python3 src/courts.py --all --apertus replay` | rewrites the table from the replay cache (no gateway call) |
| `python3 src/courts.py --all --apertus live` | the same with live calls (needs `LLM_*`) |
| `python3 src/courts.py --limit N` | the first N rows; `--dry-run` writes nothing; `--apertus off` (default) leaves those rulings `pending` and kept |
| `python -m src.area_judge --court N --limit 300 --mode live` | the measurement of section 3 |

Not yet done: `make run` does not call the gate, and its table is a file, not a database table.

## 6. What changed from `2d127cb`

| | `2d127cb` | This version |
|---|---|---|
| Matter names | exact strings | by name (`src/areas.py`), shared with the summariser's `category_of` |
| Subject line | cut at the first bracket | cut at the first bracket, comma or semicolon |
| Subject line names no kept matter | dropped (`subject_out`) | `subject_unknown`, read by Apertus |
| No subject line | kept, not read | `subject_missing`, read by Apertus, kept without an answer |
| Text terms | short and long act names | also `Unfallversicherungsgesetz`, `Unfallversicherer`, `assureur-accidents` |
| Kept (6,055 rulings) | 985 | 1,082 |
| Kept in Q2/2026 / June 2026 | 321 / 88 | 416 / 154 |
| Relevant kept | 82 of 82 | 82 of 82 |

## 7. Open points

- D-021 point 2 and Q-06: this gate and the narrower area-only gate on branch `triage/outer-gate` (`src/triage/outer_gate.py`: accident, military or disability insurance on any court) are both proposals. On the same data the narrower one keeps 300 rulings in the labelled quarters instead of 643, and 81 of the 82 relevant rulings (`4A_106/2025` is the one it does not keep).
- `tests/test_doctrines.py::test_no_network_at_import` fails on this branch and on `2d127cb` alike: `src/summarize/tally.py` imports `blocking` from `summarize`, which does not resolve. Not changed here.

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
