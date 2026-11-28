# Layer 1 — the candidate gate

Measured Fri 27 Nov 2026, about 23:20 CET, on the local cache and on one read of Hugging Face `voilaj/swiss-caselaw`. This is the gate in `src/courts.py`. §6 is the same gate made versioned, run on the database (`src/layer1/`). §7 shows, for every ruling, why it was filtered and which conditions matched or did not (D-081, D-082). It is not a relevance score (D-021 stays open) and it does not settle which courts can be relevant (Q-06).

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

First measured Sat 28 Nov 2026, about 02:20 CET, on a fresh PostgreSQL 17 database loaded from the pinned Hugging Face file (`35b17aa9…`, D-062). Re-measured the same morning with the rule ledger (§7). Sources, aggregates only (D-031):
- kept, dropped and the counts by reason of each version: `expected/layer1/V1.0.0.json`, `expected/layer1/V1.1.0.json` (certified, D-082);
- `V1.0.0` against `V1.1.0`: `results/layer1_validation_reference.json`;
- `V1.1.0` against `V1.2.0`: `results/layer1_validation.json` (§7.6).

The filter decisions are `PROPOSED` in `docs/DECISIONS.md` (D-072, D-073, D-083) until the layer-1 owner agrees. The traceability and governance around them are `DECIDED` (D-081, D-082).

### 6.1 What changed from `src/courts.py`

`src/courts.py` stays the reference. `src/layer1/` takes its rules, writes every decision (kept and dropped) to the data layer (D-061 to D-071), and checks itself against `courts.py` on every ruling of every run.

| Concern | `src/courts.py` | `src/layer1/` |
|---|---|---|
| Rules | constants in the code | `src/layer1/registry/layer1_filter.json`: versioned rules and a configuration checked by a pydantic model (`src/layer1/models.py`), loaded into `ops.rule` and `ops.component_version` |
| Versions | one | `V1.0.0` = `courts.py` at `4c246a8`; `V1.1.0` = text normalised (NFKC, typographic apostrophes, no-break spaces) and the accident terms widened to the forms of PR #36 (`Unfallversicherungsgesetz`, `Unfallversicherer`, `assureur-accidents`, `assicuratore infortuni`) |
| Input | `data/cache/rulings.parquet` | `corpus.ruling`, `corpus.ruling_text`, and the rubric from `corpus.subject_observation` (Neuheiten first, then the HF `legal_area`, then the head of the title, which is signalled) |
| Output | `data/cache/layer1.json` | files first, then one transaction (§6.3) |
| Label | kept or not | `in_suva_scope` = `potentially` (kept) or `out_of_scope` (dropped, score 0), D-063 |
| Reasons | `subject` and `text` | every rule of the version, with its outcome (`fired`, `not_fired`, `not_applicable`, `blocked`) and its evidence: the rubric and its source, the docket head, or the matched term and its offsets in the original text (the rule ledger, §7.1); the reason code is the decisive rule |
| Recall | `--recall`, a separate command | blocking check after each run on Suva's labels in `gold.label`; `make run` fails when a labelled ruling is dropped. That needs `DATABASE_URL` and a loaded `gold.label`: without labels, S2 prints `SKIPPED run S2 recall` (§6.4) |

A version is immutable. Loading a registry whose entry differs from the stored version of the same number fails and asks for a new version (D-064, D-082). That covers the configuration, the rules bound to the version (dropped, reordered or bound at another rule version), the rule definitions and kinds, the decision and the validation file. A code hash that differs from today's code only prints a notice. An engine fix that keeps every certified decision, proven by the golden check (§7.4), needs no new version. Each run records the hash of the code it ran (§7.4).

### 6.2 Rules (reason codes)

| Code | Kind | Fires when |
|---|---|---|
| `L1_KEEP_RUBRIC` | keep | a listed court (4, 8 or 9 in `V1.0.0` to `V1.2.0`), allowed letter, rubric in the court's keep list |
| `L1_KEEP_RUBRIC_MISSING` | keep | a listed court, allowed letter, no rubric from any source |
| `L1_KEEP_ACCIDENT_TERM` | keep | the text names Suva, CNA, INSAI, an accident or military insurance term |
| `L1_KEEP_CONTRACT_TERM` | keep | the text names the insurance-contract act or `Taggeldversicherung`, and the rubric is not a closed one |
| `L1_FLAG_CLOSED_RUBRIC` | flag | a contract term matched but the rubric is closed (unemployment, old-age, tax…): recorded, not kept; the contract keep is then `blocked` (§7.1) |
| `L1_DROP_WRONG_COURT` | drop | the docket head is not a listed court |
| `L1_DROP_WRONG_LETTER` | drop | a listed court with a letter outside the court's list |
| `L1_DROP_RUBRIC_OUT` | drop | a listed court and letter, and the rubric is not in the court's keep list |
| `L1_SIGNAL_RUBRIC_FROM_TITLE` | signal | the rubric was read from the head of the title, not from a rubric field |
| `L1_KEEP_TEXT_UNAVAILABLE` | keep | `V1.2.0` only: the ruling has no text, so its text rules cannot run (G5: never dropped on the docket prefix alone) |
| `L1_KEEP_TITLE_RUBRIC` | keep | `V1.2.0` only: a listed court and letter, and the head of the title, cut at `(`, `;`, `,` or `:`, is in the court's keep list |

A drop rule states one condition only. A ruling is dropped only when no keep rule fired. Its reason code is then the fired drop with the lowest ordinal. A kept ruling's reason code is the fired keep with the lowest ordinal (F-13). So a ruling of another court whose text names an accident term is kept by `L1_KEEP_ACCIDENT_TERM`; its ledger shows `L1_DROP_WRONG_COURT` as fired, not decisive.

Exactly one subject rule fires per ruling (a `KEEP_RUBRIC*` or a `DROP_*`), plus any text rules. In `V1.2.0`, `L1_KEEP_TITLE_RUBRIC` can fire beside it: next to `L1_DROP_RUBRIC_OUT` it keeps the ruling (an umbrella HF rubric that hides the title's matter, or a title such as `Haftpflichtrecht; Revision`), and next to `L1_KEEP_RUBRIC` it only adds an `Ebenso` line to the explanation. Every other rule of the version is recorded with its outcome (§7.1). The text rules never drop.

### 6.3 What a run writes

1. `data/runs/<run_id>/decisions.jsonl`: one record per ruling. It holds **every rule evaluation** of the version (outcome, evidence, detail), the rubric and its source, the scope, the reason code, the German explanation and the fingerprint of the inputs. The database is loaded from the same records in memory, not from this file; `verify` proves the two are equal (§7.4). The fields `subject` and `text` keep the meaning of the two checks of `courts.py` (`kept_subject`, `subject_missing`, `wrong_court`, `wrong_letter`, `subject_out`; `kept_text`, `kept_contract`, `text_clear`, `text_absent`) in every version. A `V1.2.0` keep that `courts.py` does not know shows in `reason_code`, the rule hits and the ledger only: a ruling kept by its title has `subject = subject_out` and `reason_code = L1_KEEP_TITLE_RUBRIC`.
2. `data/runs/<run_id>/layer1_log.json`: the owner's log (`docs/layer1_log.schema.json`, `layer1-log-1`), built by `courts.build_layer1_log`. It carries real UTC start and end times, `input.sha256` (SHA-256 of the sorted input fingerprints), `input.bytes` (UTF-8 bytes of the texts read), and `ruling_id` and `decision_date` on each asset, because a docket is not unique (F-15). The log's closure checks need every kept ruling to pass its subject action or its text action, so a `V1.2.0` keep is logged under the action it belongs to: the title keep as a subject pass (`kept_title_rubric`, criterion = the cut title head), the no-text keep as a text pass (`kept_text_unavailable`, criterion `empty_text`). `V1.0.0` and `V1.1.0` have neither rule, so their log rows are built as before.
3. `data/runs/<run_id>/manifest.json`: the SHA-256 of both files, the version, the profile, the counts, the ledger's outcome counts and the golden status (§7.4).
4. The golden check, before anything is loaded: a run over the whole corpus of the pinned snapshot compares its decisions with `expected/layer1/<version>.json`. A mismatch fails the run and loads nothing (§7.4).
5. One transaction in PostgreSQL:
   - one `ops.span` per ruling under the run's root span;
   - one `triage.assessment` per ruling, with its German explanation;
   - one `triage.assessment_reason` row per rule of the version: the rule ledger (§7.1), certified row by row and, at commit, per assessment;
   - one event `layer1.decision.made` per ruling, and the run events `layer1.run.decided`, `layer1.parity.checked`, `layer1.files.written`, then `layer1.golden.matched` (info) or `layer1.golden.not_comparable` (warning, with the reason);
   - the run metrics (`ops.run_metric`), including `ledger_rows` and one `outcome_<outcome>` count per outcome.

   Nothing is written if one row fails.

The explanation is composed from the ledger:
- kept: `Vorauswahl bestanden: <decisive keep>.`, then `Ebenso: <other fired keeps>.`;
- dropped: `Von der Vorauswahl ausgeschlossen: <decisive drop>.`, then what the text check found:
  - no text: `Kein Urteilstext verfügbar: die Begriffsprüfung war nicht möglich.`;
  - text searched without a match: `Im Urteilstext geprüft, ohne Treffer: <term lists searched> (nur die Begriffe der Filterversion; andere Formulierungen erkennt die Prüfung nicht).` It names the term lists of the version, never a claim about what the ruling is about;
  - a contract term blocked by a closed rubric: `Hinweis: <flag label>: «<term>» im Urteilstext gefunden, Rechtsgebiet «<rubric>».`;
- then, in both cases, the title signal when the rubric was read from the title.

In `V1.2.0`, `L1_KEEP_TEXT_UNAVAILABLE` searches no term list (its `detail` has `text_chars` and no `pattern`), so it never appears in the `ohne Treffer` list of a dropped ruling. `L1_KEEP_TITLE_RUBRIC` also fires, by design, on rulings that another keep already decides, such as a rubric and a title that both name the same matter; their explanation then names it after `Ebenso:` (`Rechtsgebiet laut Gegenstand in der Liste der Abteilung`).

A drop label states only its own condition (`Abteilung nicht in der Liste der Vorauswahl`); the explanation adds the text outcome (F-03).

Assessments are labelled `LIVE`. Layer 1 calls no LLM, so it has nothing to replay: every run computes its decisions anew. `REPLAY` (D-032) concerns recorded Apertus answers only.

Ids are `uuid5` of the run and the ruling. A committed run cannot be loaded again: its ledgers are sealed at commit (§7.1), and `verify` re-reads the files instead. A run with no ruling fails and leaves no assessment. A failed run keeps its status `failed` and its error span. `data/runs/` is git-ignored.

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

The traceability and governance commands (`layer1-golden`, `layer1-verify`, `layer1-validate`, the ingest closure) are in §7.5.

`make run` calls layer 1 as stage S2 when `DATABASE_URL` is set and the corpus is loaded, then checks recall. Otherwise S2 is skipped and says why. When `gold.label` is empty, layer 1 runs and S2 prints `SKIPPED run S2 recall: gold.label is empty, so the blocking recall check did not run (python -m src.ingest gold, then python -m src.layer1 recall)` (F-14). A recall that drops a labelled ruling makes `make run` exit 1.

### 6.5 Measured on the base dataset

6,055 rulings (Q4/2025, Q1/2026, Q2/2026 under both date readings, and the 23 Q3/2025 rulings of `judgements/`).

| | `V1.0.0` (profile `layer1_reference`) | `V1.1.0` (profile `default`) |
|---|---|---|
| Kept (`potentially`), `expected/layer1/` | 931 | 935 |
| Dropped (`out_of_scope`), `expected/layer1/` | 5,124 | 5,120 |
| Same subject and text decision as `courts.py` | 6,055 / 6,055 | 6,038 / 6,055 |
| Suva list, Federal Court rulings (kept/total) | 59/59 | 59/59 |
| Q3/2025 summaries not in the list (kept/total) | 23/23 | 23/23 |
| All summary exports (kept/total) | 55/55 | 55/55 |
| Kept in the Q2/2026 union (2,677, `expected/ingest/V1.0.0.json`) | 380 | 383 |
| Run time on a laptop, files and database (first measurement, before the rule ledger) | about 20 s | about 23 s |

`V1.1.0` keeps 4 more rulings and drops none that `V1.0.0` kept. The 4 are `2C_462/2024`, `2C_533/2025` and `7B_400/2024` (other courts, `assurance-accidents` in the plural) and `8C_170/2026` (an unemployment ruling that names an accident insurer). The 13 other rulings that differ from `courts.py` are kept by both versions and gain an accident-term reason. 931 here against 993 in §3: §3 ran on the local cache `data/cache/rulings.parquet`, which no repo code builds and which was not available for this measure. `courts.py` and `V1.0.0` agree on all 6,055 rulings of the HF file, so the gap of 62 comes from the input, not the code; which columns differ is not measured.

The rubric read from the title is a matter, not a Neuheiten rubric: `4A_127/2025` reads `contratto di assicurazione`, which no court-4 rubric matches, and is kept by its contract term. Fetching the Neuheiten rubric (`corpus.subject_observation`, source `neuheiten`) would replace that reading; the crawl does not write it yet.

## 7. Traceability and governance

Written Sat 28 Nov 2026 (branch `triage/layer1-traceability`; D-081 to D-084). For every ruling, this section shows how to answer three questions: why was it filtered, which condition matched, and which did not. It also covers the source rows that never became a ruling, so never reached layer 1. The decisions behind it are D-081 (ledgers) and D-082 (governance); the open points are D-084.

### 7.1 The rule ledger (D-081)

Every layer-1 assessment has one row in `triage.assessment_reason` per enabled rule of its version, whatever the rule did. `ordinal` is the rule's ordinal in the version (`ops.component_version_rule.ordinal`), not the order in which rules fired.

| Outcome | Meaning | Evidence stored | `detail` |
|---|---|---|---|
| `fired` | the condition is true; the rule's effect applies (keep, drop, flag or signal) | `evidence_field`, `examined_value`; for a text term also `char_start`, `char_end` and `matched_text`, the exact slice of the stored text | `pattern` (the configuration key searched), `rubric_source` |
| `not_fired` | evaluated; the condition is false | `evidence_field`, `examined_value` (docket head, rubric or title head); no offsets | `pattern`, `text_chars` (length of the text searched) |
| `not_applicable` | a precondition failed, so the condition was not evaluated | none | `why`: `court_not_listed`, `letter_not_listed`, `rubric_missing`, `text_absent` or `gegenstand_absent` |
| `blocked` | the condition is true, but another rule neutralises it: a contract term found on a closed rubric (F-02) | the term, its offsets and its matched text | `blocked_by` (the flag that fired), `closed_rubric_match` |

`evidence_field` is `docket`, `rubric:<source>` (`neuheiten`, `hf_legal_area` or `gegenstand_head`), `gegenstand` or `full_text`. `examined_value` and `matched_text` hold at most 300 characters. `examined_value` is NULL for full-text rules: the text is referenced by `triage.assessment.input_text_id`, never copied.

What each rule records:

| Rule (check) | `not_applicable` when | `fired` or `not_fired` on |
|---|---|---|
| `L1_DROP_WRONG_COURT` (`court_not_listed`) | never | the docket head (`docket`) |
| `L1_DROP_WRONG_LETTER` (`letter_not_listed`) | the court is not listed | the letter of the docket head |
| `L1_KEEP_RUBRIC_MISSING` (`court_rubric_missing`) | the court or the letter is not listed | whether any rubric source has a value |
| `L1_KEEP_RUBRIC`, `L1_DROP_RUBRIC_OUT` (`court_rubric_kept`, `court_rubric_out`) | the court or the letter is not listed, or there is no rubric (`rubric_missing`) | the rubric (`rubric:<source>`): exactly one of the two fires |
| `L1_SIGNAL_RUBRIC_FROM_TITLE` (`rubric_from_gegenstand`) | never | whether the rubric came from the title head (`detail.rubric_source`) |
| `L1_KEEP_ACCIDENT_TERM` (`text_accident_term`) | there is no text (`text_absent`) | the full text, with the term list in `detail.pattern` |
| `L1_KEEP_CONTRACT_TERM` (`text_contract_term`) | there is no text | the full text; `blocked` when a contract term matched on a closed rubric |
| `L1_FLAG_CLOSED_RUBRIC` (`text_contract_term_blocked`) | there is no text | fires when a contract term matched on a closed rubric (evidence: the closed rubric) |
| `L1_KEEP_TEXT_UNAVAILABLE` (`text_unavailable`, `V1.2.0`) | never | fires when there is no text (`full_text`, no offsets and no match, which the database accepts only on an assessment without text); otherwise `not_fired` with `detail.text_chars` and no `pattern` |
| `L1_KEEP_TITLE_RUBRIC` (`title_rubric_kept`, `V1.2.0`) | the court or the letter is not listed, or there is no title (`gegenstand_absent`) | the title head cut at the first of `(`, `;`, `,` or `:` and stripped (`gegenstand`; `examined_value` = the cut head), compared with the court's keep list; `detail` names `pattern` (`courts.<digit>.rubrics`), `rubric_key` and `cut_at` |

The database certifies the ledger (`src/db/sql/80_triggers.sql`):
- **Each row, on insert** (`t30_check` on `triage.assessment_reason`):
  - the rule is an enabled rule of the assessment's version, at its ordinal, with its reason code and its kind as effect;
  - a full-text match is the exact slice `[char_start, char_end)` of the stored text, at least one character long; offsets exist only on `full_text` evidence;
  - `not_applicable` names one of the five `why` values, and `text_absent` only when the assessment has no text;
  - only a keep is `blocked`, by another enabled flag of the version, and the row names the closed rubric;
  - the assessment was inserted by the same transaction: a committed ledger is sealed.
- **Each assessment, at commit** (`t50_ledger`, deferred):
  - every enabled rule has exactly one row, and there is no other row;
  - the flag named by a `blocked` row fired;
  - `potentially` if and only if a keep fired;
  - the reason code is the fired keep with the lowest ordinal, else the fired drop with the lowest ordinal (F-13);
  - every drop is certified, whatever the assessment's outcome.
- **Each version** (`t30_check` on `ops.component_version_rule`): the rule set is sealed once an assessment uses it or a profile pins it. A new rule is a new version, so a certified ledger never goes stale.

The engine checks the same contract before the database sees it. A rule whose kind does not match its check, or a version without `text_contract_term_blocked`, raises `ValueError` when the engine is built (F-13).

The `blocked` and the no-text paths are proven by the engine and DB tests (`tests/test_layer1_engine.py`, `tests/sql/31_ledger_test.sql`). On the real corpus, `V1.1.0` writes 0 `blocked` rows.

### 7.2 Why was this ruling filtered?

The view `triage.v_layer1_ledger` has one row per assessment and rule. `is_decisive` marks the fired rule whose reason code is the decision's. The ledger of one ruling in the latest successful `default` run:

```sql
SELECT l.ordinal, l.rule_code, l.effect, l.outcome, l.is_decisive, l.evidence_field, l.examined_value,
       l.char_start, l.char_end, l.matched_text, l.detail, l.label_de
FROM triage.v_layer1_ledger l
WHERE l.docket = '4A_100/2026'
  AND l.run_id = (SELECT pr.run_id FROM ops.pipeline_run pr
                  JOIN ops.pipeline_profile_version pv ON pv.profile_version_id = pr.profile_version_id
                  WHERE pv.profile_code = 'default' AND pr.kind = 'layer1' AND pr.status = 'succeeded'
                  ORDER BY pr.started_at DESC LIMIT 1)
ORDER BY l.ordinal;
```

How to read it:
- **Why:** the row with `is_decisive = true` is the reason. Its `label_de` is the first sentence of the explanation.
- **Which condition matched:** every `fired` row, with the value it read (`examined_value`) and, for a term, its offsets in the stored text (`input_text_id`, `text_sha256`). A `fired` row that is not decisive is a condition that matched without deciding, such as `L1_DROP_WRONG_COURT` on a ruling kept by an accident term.
- **Which did not:** every `not_fired` row, with the value examined, or the term list searched (`detail.pattern`) and the length of the text (`detail.text_chars`). The term list is the version's configuration (`ops.component_version.config`).
- **What could not be checked:** every `not_applicable` row, with the precondition that failed (`detail.why`).
- **What was found but neutralised:** a `blocked` row, with the term, its offsets, the flag that blocked it and the closed rubric.

Example: `4A_100/2026`, a German ruling that is not in Suva's data. In the `default` run (`V1.1.0`) it is dropped. `L1_DROP_RUBRIC_OUT` fired and is decisive, on `rubric:hf_legal_area`, with the rubric it read. The three text rules (accident terms, contract terms, closed-rubric flag) are `not_fired` on `full_text`. Every other rule is `not_fired`.

Counts per rule and outcome for one run:

```sql
SELECT rule_code, outcome, count(*) FROM triage.v_layer1_ledger
WHERE run_id = '<run_id>' GROUP BY rule_code, outcome ORDER BY rule_code, outcome;
```

Never quote the ledger of a ruling Suva labelled in a committed file, a log or a message: it reveals the label (D-031). Use aggregates for those rulings. `triage.v_scope_trace` counts both: `reason_count` (rules that fired) and `evaluated_rule_count` (ledger rows).

### 7.3 Rows that never reached layer 1: the ingest exclusion ledger (D-081)

Every row of the source file is accounted for. A row is either a source reference of a ruling (`corpus.ruling_source_ref`, one per snapshot) or an exclusion (`corpus.ingest_exclusion`), never both. `ops.source_snapshot.row_count` counts every row of the file.

| Reason code | The row was not loaded because | `detail` |
|---|---|---|
| `OUT_OF_WINDOW` | it is in no population window (decision quarters, publication window, Suva's reference rulings) | the dates compared: decision, publication, first seen |
| `ING_TWIN_SAME_DATE` | it is a `-DYYYYMMDD` duplicate row, not kept as a source reference: its same-date base is not loaded, or the base is loaded but the certified window filter does not read the twin | `base_id`, `base_reason`; or `base_loaded = true` and `why = twin_not_read` |
| `ING_DECISION_DATE_MISSING` | it has no decision date | |
| `ING_DOCKET_MALFORMED` | it is in a window, but its docket is not in the Federal Court format | |
| `ING_SOURCE_ID_MISSING`, `ING_SOURCE_ID_DUPLICATE` | it has no usable id of its own: it is recorded as `row:<index>` | |

The loader (`src/ingest/hf_base.py`) classifies every row with one function shared with the loading path. It writes the exclusions in the same transaction as the rulings. Before commit, it checks the closure `row_count` = refs + exclusions: a lost row fails the load and writes nothing. Loading the same file again changes nothing. Writes for one snapshot are serialised by one advisory lock (`corpus.lock_source_rows`), so two loads cannot both load and exclude a row.

The closure, per snapshot:

```sql
SELECT source, revision, row_count, loaded_refs, base_refs, twin_refs, exclusions, exclusions_by_reason,
       unaccounted_rows, closure_ok
FROM corpus.v_ingest_closure;
```

Why a docket is not in the corpus:

```sql
SELECT x.external_id, x.reason_code, x.decision_date, x.detail, rc.label_de
FROM corpus.ingest_exclusion x JOIN ops.reason_code rc ON rc.code = x.reason_code
WHERE x.docket_raw = '5A_1/2020';
```

Exclusivity holds per snapshot, not per ingest version (D-084 point 8).

### 7.4 Governance (D-082)

- **Golden check.** The certified behaviour lives in `expected/`. `expected/layer1/<version>.json` holds the counts and a SHA-256 over the canonical decisions of one version; `expected/ingest/<version>.json` holds the ingestion counters and the population manifests. The digest covers the fired rules only, so traceability added around a decision leaves it unchanged.
  - `make layer1-golden PARQUET=…` checks every version of the registry and the ingestion in memory, without a database.
  - Every `run_layer1` compares itself with the file of its version when four conditions hold: the run covers the whole corpus; the corpus comes from the snapshot the file pins (`ops.source_snapshot` `hf_bger` with that SHA-256 and revision); the rulings were created by the ingest version the file names; and the run decides as many rulings as the file certifies.
  - A mismatch fails the run before anything is loaded. A match writes the event `layer1.golden.matched`. Otherwise the event is `layer1.golden.not_comparable`, with the reason. The manifest records the status.
  - A certified file is never edited. `WRITE=1` (`--write`) writes the file of a version that has none and never overwrites one. A changed decision needs a new version (D-064).
- **`verify`** (F-16), read-only. The manifest's SHA-256 must match both files, and every record of `decisions.jsonl` must equal its assessment and its ledger rows: scope, reason, explanation, fingerprint, text id and every evaluation. Exit 0, or exit 1 with the first differences.
- **`validate`.** It runs a baseline profile and a candidate profile on the same corpus, records recall when Suva's labels are loaded, and compares the runs ruling by ruling. It fails when:
  - a ruling goes `potentially -> out_of_scope`;
  - the candidate does not decide a ruling the baseline keeps, or the two runs decide different rulings;
  - the candidate drops a labelled ruling;
  - a run fails, a golden mismatch included.

  The baseline's recall is reported, not required: a candidate may fix it. The report holds aggregates only (D-031), plus a `validation` block. The candidate run gets the event `layer1.validation.passed` or `layer1.validation.failed`.
- **Code identity** (F-09). Every run records `params.code_paths` and `params.code_sha256`. A layer-1 run hashes `src/layer1/engine.py`, `models.py`, `run.py`, `golden.py` and `recall.py`. Compare a run's hash only with another run's over the same paths, never with its version's `code_sha256`, which hashes the code that created the version.
- **Decision and validation references** (F-12). Every registry version names its decision (`decision`, a `D-NNN` row of `docs/DECISIONS.md`). A step version also names its certified file (`validation`). Both are stored (`ops.component_version.decision_ref`, `validation_ref`; `ops.pipeline_profile_version.decision_ref`) and compared strictly. `tests/test_registry_refs.py` checks that every `D-NNN` exists and that every validation file certifies that step and version.
- **Sealed rule sets.** A version's rules cannot change once it is used or pinned (§7.1). The loader also refuses a registry file that drops, reorders or re-versions a rule of an existing version.
- **Pipeline role** (F-11). Every pipeline session runs `SET ROLE suva_g_pipeline` (`DB_PIPELINE_ROLE`; an exported empty value keeps the login's rights, with a warning). A missing or ungranted role fails the connection and names the fix. The audit log records the role (`audit.change_log.db_role`). Under a superuser login this is advisory, not a security boundary (`.env.example`, D-084 point 9).
- **Recall** (F-14). `python -m src.layer1 recall` exits 1 when a labelled ruling is dropped, and a DB test proves it. `make run` says `SKIPPED run S2 recall` when `gold.label` is empty (§6.4).

### 7.5 Commands

```
make layer1-golden PARQUET=path/to/bger.parquet          # certified decisions, in memory, no DB; WRITE=1 writes a missing file
make layer1-verify RUN=<run_id>                          # the run's files equal its DB rows (read-only)
make layer1-validate BASE=default PROFILE=layer1_candidate   # two runs, recall, compare; fails on a removal
make layer1 PROFILE=layer1_candidate                     # one run of V1.2.0
uv run python -m src.ingest closure [--out PATH]          # every row of the source file accounted for, per snapshot
```

`make layer1-validate` defaults to `BASE=layer1_reference PROFILE=default`. `validate` writes `results/layer1_validation.json` unless `--out` names another file, and the make target passes no `--out`. The committed results files are written as follows: `results/layer1_validation.json` holds `default` → `layer1_candidate` (`V1.1.0` → `V1.2.0`), `results/layer1_validation_reference.json` holds `layer1_reference` → `default` (`V1.0.0` → `V1.1.0`):

```
uv run python -m src.layer1 validate --baseline-profile layer1_reference --profile default --out results/layer1_validation_reference.json
uv run python -m src.layer1 validate --baseline-profile default --profile layer1_candidate --out results/layer1_validation.json
```

So `make layer1-validate` with its defaults overwrites `results/layer1_validation.json` with the reference comparison: pass `BASE=default PROFILE=layer1_candidate` to rewrite that file.

`closure` has no make target yet; it reads `corpus.v_ingest_closure` and writes `results/ingest_closure.json`, counts only. It exits 1 when no snapshot is loaded or one does not close.

### 7.6 `V1.2.0` and the profile `layer1_candidate` (D-083)

`V1.2.0` appends two keep rules after the existing ordinals, at ordinals 10 and 11: `L1_KEEP_TEXT_UNAVAILABLE` and `L1_KEEP_TITLE_RUBRIC` (§6.2, §7.1). Its configuration is `V1.1.0`'s plus three changes:
- `assicurazione contro le malattie` in the keep lists of courts 8 and 9 (F-07);
- an optional `title_rubric.cut_at` (`(;,:`), the cut of the title-rubric check; absent in `V1.0.0` and `V1.1.0`. The engine refuses a version that has the check without the setting;
- `accident_terms` widened to Suva's legal name `Unfallversicherungsanstalt` and the unhyphenated `assurance accident(s)`.

The exact lists are its entry in `src/layer1/registry/layer1_filter.json`. The configuration and rule schemas go to `V1.1.0`, each with a changelog, for the new checks and the optional cut; `V1.0.0` and `V1.1.0` validate unchanged and keep their digests. A test checks that `V1.2.0` is exactly `V1.1.0` plus these changes (`tests/test_layer1_engine.py::test_v120_is_v110_plus_the_approved_changes`). The database holds only the registry file's current schemas, stored as `initial` with no previous version: their history is in the file's changelogs, not in `ops.json_schema` (a change to `src/db/registry.py`, platform).

It is monotone by construction: it only adds keep rules and keep values, so no ruling `V1.1.0` keeps can be dropped. `validate` proves it on the base dataset (§7.7). The decisive rule of a ruling `V1.1.0` keeps can still change in principle, because a wider term or rubric can fire a keep of lower ordinal. The counts by reason (§7.7) are consistent with no such change: every keep count rises or stays equal, and the rises add up to the 9 rulings added.

Registry and profile:
- `V1.2.0`: bump `minor`, previous `V1.1.0`, decision `D-083`, validation `expected/layer1/V1.2.0.json`.
- Profile `layer1_candidate` `V0.1.0` (not default, decision `D-083`) pins ingest `V1.0.0` and `layer1_filter` `V1.2.0`. `default` stays on `V0.2.0`, hence `V1.1.0`, until the layer-1 owner agrees (D-083 is `PROPOSED`); adopting `V1.2.0` means a new `default` profile version.

The acceptance rule was set before measuring: 0 rulings going `potentially -> out_of_scope` and full recall on Suva's labels in `validate --baseline-profile default --profile layer1_candidate`. `expected/layer1/V1.2.0.json` was written with `golden --write` only once that validation passed. Two consequences of that order:
- Between registering a version and writing its file, `make layer1-golden` fails with `no expected file` for that version, and a run of it records `layer1.golden.not_comparable`.
- A new version is registered with `validation: null` (it has no certified file yet); its entry names the file once `golden --write` has written it. The loader compares `validation_ref` strictly (§7.4), so a database that already loaded the version refuses the new value and has to be rebuilt: `make db-reset && make db-deploy`, then `make db-registry`, `make ingest-base`, `make ingest-gold`.

Three real rulings that `V1.2.0` keeps and `V1.1.0` drops, none in Suva's data (checked against `judgements/`):
- `4F_4/2026` (DE): `L1_KEEP_TITLE_RUBRIC` on `gegenstand`, cut head `Haftpflichtrecht` (title `Haftpflichtrecht; Revision`).
- `6B_749/2025` (FR): `L1_KEEP_ACCIDENT_TERM` on `full_text`, `assurance accident`, the exact slice of the stored text.
- `9C_636/2025` (IT): `L1_KEEP_RUBRIC` on `rubric:hf_legal_area`, `Assicurazione contro le malattie`; `L1_KEEP_TITLE_RUBRIC` also fired (`Ebenso`).

### 7.7 Measured on the base dataset

Real corpus: the pinned HF file (`35b17aa9…`), 6,055 rulings (`expected/ingest/V1.0.0.json`). Aggregates only (D-031).

Layer 1, one run per version. Sources: `expected/layer1/<version>.json` for kept and dropped; the `runs[].totals` of `results/layer1_validation_reference.json` (`V1.0.0`) and `results/layer1_validation.json` (`V1.1.0`, `V1.2.0`) for the ledger; the `validation` blocks of both files for the golden status.

| | `V1.0.0` (`layer1_reference`) | `V1.1.0` (`default`) | `V1.2.0` (`layer1_candidate`) |
|---|---|---|---|
| Kept | 931 (`expected/layer1/V1.0.0.json`) | 935 (`expected/layer1/V1.1.0.json`) | 944 |
| Dropped | 5,124 | 5,120 | 5,111 |
| Ledger rows | 54,495 | 54,495 | 66,605 |
| `fired` | 8,041 | 8,058 | 8,659 |
| `not_fired` | 30,032 | 30,015 | 37,409 |
| `not_applicable` | 16,422 | 16,422 | 20,537 |
| `blocked` | 0 | 0 | 0 |
| Golden | `matched` | `matched` | `matched` |

Validation, candidate against baseline:

| | `layer1_reference` → `default` | `default` → `layer1_candidate` |
|---|---|---|
| `potentially -> out_of_scope` | 0 | 0 |
| `out_of_scope -> potentially` | 4 | 9 |
| Candidate recall, all labelled (kept/total) | 82/82 | 82/82 |
| Passed (`validation.passed`) | yes | yes |

What `V1.2.0` adds, by decisive reason (`by_reason` of the two runs in `results/layer1_validation.json`):

| Reason code | `V1.1.0` | `V1.2.0` |
|---|---|---|
| `L1_KEEP_RUBRIC` | 859 | 860 |
| `L1_KEEP_RUBRIC_MISSING` | 19 | 19 |
| `L1_KEEP_ACCIDENT_TERM` | 47 | 51 |
| `L1_KEEP_CONTRACT_TERM` | 10 | 10 |
| `L1_KEEP_TITLE_RUBRIC` | — | 4 |
| `L1_KEEP_TEXT_UNAVAILABLE` | — | 0 |
| `L1_DROP_WRONG_COURT` | 4,058 | 4,055 |
| `L1_DROP_WRONG_LETTER` | 0 | 0 |
| `L1_DROP_RUBRIC_OUT` | 1,062 | 1,056 |

0: the code is absent from `by_reason`, so it decides no ruling. —: the rule is not in the version.

`L1_KEEP_TEXT_UNAVAILABLE` decides no ruling of the base dataset: it is a guard for G5, with no measured gain. Kept per population, `V1.1.0` → `V1.2.0` (`by_population`, same file; the populations overlap, so the rises do not add up to 9): `2025Q4_decision` 295 → 297, `2026Q1_decision` 339 → 345, `2026Q2_decision` 278 → 279, `2026Q2_publication` 312 → 313, `2026Q2_union` 383 → 384, `suva_reference` 23 → 23. None of them carries a Suva label, since `V1.1.0` already keeps every labelled ruling; the recall of every cohort is unchanged (`suva_list` 59/59, `q3_2025_summaries` 23/23, `summary_exports` 55/55, all labelled 82/82, for both runs).

Ingest closure of the pinned file (`results/ingest_closure.json`):

| | Rows |
|---|---|
| Rows of the file (`row_count`) | 194,883 |
| Source references (base + twins) | 6,072 (6,055 + 17) |
| Exclusions | 188,811 |
| `OUT_OF_WINDOW` | 188,788 |
| `ING_TWIN_SAME_DATE` | 23 |
| Unaccounted rows | 0 |
| Closure holds (`closure_ok`) | yes |

The certified ingestion counters are unchanged (`expected/ingest/V1.0.0.json`): 27,286 rows read through the window filter, 21,214 of them out of window, 17 twins, 6,055 rulings. `out_of_window` keeps its meaning: rows the window filter read and did not load. The ledger's `OUT_OF_WINDOW` differs in two ways. It also counts the rows the filter never read. It leaves out the twins the filter read whose base it did not load: those are `ING_TWIN_SAME_DATE`.

