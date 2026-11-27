# SUMMARY V2 — 50 RULINGS

One live run of the v2 fiche prompt, 27 November 2026, about 21:29 to 21:43 CET (823 seconds). The v1 measurement stays in `docs/SUMMARY_MEASUREMENT.md`. This is not the hold-out of `docs/EVAL.md` §4. No threshold was set. No person read these 100 fiches against the rulings.

Open questions left open, with the "While open" line of `docs/DECISIONS.md`: D-047 (which rulings are summarised: top 10 first; these 50 are a probe, not that list), Q-30 (style follows the ruling's language; not scored here), Q-08 / D-053 (length follows the 55 exports; this run used no character band), Q-27 (same paragraph plan in both languages; parity was not scored), D-031 (the fiches stay in `data/trial/`, which is not committed).

## 1. What was run

v2 is `src/summarize/v2/`: one system prompt and one glossary per matter kept by `src/courts.py` (accident, disability, health, occupational pension, contract). v1, one glossary and one prompt for every ruling, is `src/summarize/v1/` and is not called. The runner is `src/summarize/summarize.py`. It calls Apertus through `src/llm/client.py` (`prompt_version` `v2`). The client sets temperature to 0. German and French are each written from the ruling. Two human fiches are tone only: `8C_177/2025` and `8C_224/2025`. Three one-line human fiches stay out of the examples: `8C_21/2025`, `8C_44/2025`, `8C_455/2025`.

The checker is `blocking()` in `src/summarize/summarize.py`. It flags a wrong-language sigil, an article absent from the ruling, a copied "manifestly ill-founded", a missing or inverted outcome, a pasted operative block, and a fiche that is only the operative sentence (fewer than 80 characters left once the outcome sentences are removed). It does not judge facts, style, or whether a short fiche is still too thin. A fiche under 400 characters is not, by itself, a flag.

## 2. Which rulings

Not a seeded draw. From the local cache `data/cache/rulings.parquet`: rulings that pass `src/courts.py`, whose text is between 2,500 and 20,000 characters, that were not already in `data/trial/`, and that are not the few-shot examples above. Spread by matter, 50 rulings, 100 fiches.

| Matter | Rulings | Dockets |
|---|---|---|
| Accident (`uv`) | 16 | `8C_154/2025`, `8C_466/2025`, `8C_573/2025`, `8C_626/2024`, `8C_356/2025`, `8C_682/2024`, `8C_223/2025`, `8C_7/2026`, `8C_500/2025`, `8C_564/2025`, `8C_175/2026`, `8C_307/2025`, `8F_22/2025`, `8C_580/2025`, `8C_258/2026`, `8C_66/2026` |
| Disability (`iv`) | 16 | `9C_581/2024`, `8C_567/2025`, `8C_54/2025`, `8C_531/2025`, `8C_252/2025`, `9C_369/2024`, `8C_726/2025`, `9C_677/2025`, `8C_335/2025`, `8C_537/2025`, `9C_155/2026`, `9C_85/2025`, `9C_143/2026`, `8C_722/2025`, `9C_91/2026`, `8C_526/2025` |
| Health (`kv`) | 8 | `9C_526/2025`, `9C_497/2025`, `9C_543/2024`, `9C_700/2025`, `9C_540/2025`, `9C_28/2026`, `9F_29/2025`, `9F_8/2026` |
| Occupational pension (`bv`) | 5 | `9C_503/2025`, `9C_684/2024`, `9C_557/2025`, `9C_721/2024`, `9C_193/2026` |
| Contract (`vvg`) | 5 | `4A_350/2025`, `4A_451/2025`, `4A_420/2025`, `4D_1/2026`, `4A_156/2026` |

## 3. What the checker returned

100 fiches. 93 with an empty `problems` list. 7 flagged. The process exited 1 because those 7 critiques are reported as failures. Every fiche was still written under `data/trial/`, with `"prompt": "v2"`.

| Matter | Flagged fiches | Fiches |
|---|---|---|
| Accident | 3 | 32 |
| Disability | 2 | 32 |
| Health | 1 | 16 |
| Occupational pension | 1 | 10 |
| Contract | 0 | 10 |
| German | 2 | 50 |
| French | 5 | 50 |

| Docket | Language | Matter | Flag |
|---|---|---|---|
| `8C_626/2024` | French | accident | German sigil |
| `8F_22/2025` | French | accident | article missing from the ruling (`art. 4 LPGA`) |
| `8C_258/2026` | German | accident | French sigil |
| `9C_143/2026` | French | disability | "manifestly ill-founded" copied |
| `9C_91/2026` | German | disability | dismissal missing from the outcome |
| `9F_29/2025` | French | health | fiche is only the operative sentence (79 characters) |
| `9C_684/2024` | French | pension | operative block pasted |

Length of the generated text, in characters: German minimum 226, median 708, maximum 1,959. French minimum 79, median 651, maximum 2,214. Eighteen fiches are under 400 characters. Only `9F_29/2025` in French is short enough for the operative-sentence check to fire.

These numbers are the stdout of that run and a count of the stored `problems` lists. They are not recall, not F2, and not a lawyer's reading.
