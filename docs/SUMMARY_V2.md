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

## 4. Same prompt, another model

One comparison, 28 November 2026, about 09:42 to 09:48 CET. The question was fixed before the run: on the 7 fiches section 3 flags for Apertus, and on 3 fiches whose stored `problems` list is empty, how many blocking critiques does the same checker raise for another model. No threshold was set. No person read the fiches. This is not the hold-out of `docs/EVAL.md` §4.

The writer is still `write_fiche` in `src/summarize/summarize.py`: the v2 prompt, temperature 0, at most 1,200 new tokens, and at most two repairs. The only change is who answers. Apertus stays the runtime model (E1). The other model is `Qwen/Qwen2.5-14B-Instruct-AWQ` (Apache-2.0), served for this probe on a Hugging Face Jobs L4 (`l4x1`, 24 GB). A 32B AWQ of the same family loaded (18.14 GiB) and then had no room left for the cache on a 24 GB GPU; that attempt was cancelled and wrote no fiche. A T4 run of the 14B was cancelled for the same reason: that GPU cannot use the attention kernel this build expects. Neither cancelled run is in the table.

The 10 fiches, chosen from section 3 before any Qwen call:

| Role | Docket | Language | Apertus critique | Qwen critique | Qwen calls |
|---|---|---|---|---|---|
| flagged | `8C_626/2024` | French | German sigil | none | 1 |
| flagged | `8F_22/2025` | French | article missing from the ruling (`art. 4 LPGA`) | none | 1 |
| flagged | `8C_258/2026` | German | French sigil | French sigil | 3 |
| flagged | `9C_143/2026` | French | "manifestly ill-founded" copied | Suva absent from the ruling | 3 |
| flagged | `9C_91/2026` | German | dismissal missing from the outcome | none | 1 |
| flagged | `9F_29/2025` | French | fiche is only the operative sentence | none | 2 |
| flagged | `9C_684/2024` | French | operative block pasted | operative block pasted | 3 |
| control | `8C_154/2025` | German | none | none | 1 |
| control | `9C_581/2024` | French | none | none | 1 |
| control | `4A_350/2025` | German | none | Suva absent from the ruling | 3 |

On these 10 fiches the checker raises 7 critiques for Apertus and 4 for Qwen. Of the 7 Apertus critiques, 4 are absent from the Qwen fiche, 2 are unchanged (`8C_258/2026`, `9C_684/2024`), and 1 is replaced by a different critique (`9C_143/2026`). One control that Apertus leaves empty is flagged for Qwen (`4A_350/2025`). Qwen length, in characters: minimum 595, median 855, maximum 1,523. None of the 10 is under 400 characters.

The checker is the same function either way. It reports a wrong sigil, an article absent from the ruling, a copied "manifestly ill-founded", a missing outcome, a pasted operative block, a fiche that is only the operative sentence, and a Suva that the ruling does not name. It does not read the facts. Four of the seven Apertus faults do not recur when another model writes the same prompt. Two recur, and Qwen adds a Suva the ruling does not contain. Those remaining critiques are still the model's wording, which the checker catches.

The counts are the ten `RESULT` lines of Hugging Face job `RabahN/6b0a93e154072e8b716cd98d` (running time 381 seconds). The Apertus column is the re-check, the same morning, of the stored fiches with the current `blocking()`. No fiche text is copied here (D-031).

## 5. Same ten fiches, through the inference router

A second comparison, 28 November 2026, about 10:02 CET, 18 seconds. Same ten fiches, same `write_fiche`, temperature 0, at most 1,200 new tokens, at most two repairs. The call goes to `https://router.huggingface.co/v1/chat/completions` with model `Qwen/Qwen3.8-27B`. The served id was `qwen/qwen3.8-27b`. Thinking is off (`reasoning_effort` set to `none`); the checker reads the reply, not the reasoning trace. Apertus stays the runtime model (E1).

| Role | Docket | Language | Apertus critique | Qwen3.8-27B critique | Calls |
|---|---|---|---|---|---|
| flagged | `8C_626/2024` | French | German sigil | German sigil | 3 |
| flagged | `8F_22/2025` | French | article missing from the ruling (`art. 4 LPGA`) | none | 1 |
| flagged | `8C_258/2026` | German | French sigil | none | 1 |
| flagged | `9C_143/2026` | French | "manifestly ill-founded" copied | none | 1 |
| flagged | `9C_91/2026` | German | dismissal missing from the outcome | none | 1 |
| flagged | `9F_29/2025` | French | fiche is only the operative sentence | none | 1 |
| flagged | `9C_684/2024` | French | operative block pasted | none | 1 |
| control | `8C_154/2025` | German | none | none | 1 |
| control | `9C_581/2024` | French | none | none | 1 |
| control | `4A_350/2025` | German | none | none | 1 |

On these 10 fiches the checker raises 7 critiques for Apertus and 1 for Qwen3.8-27B. Of the 7 Apertus critiques, 6 are absent from the Qwen fiche. The one that remains is the German sigil in the French fiche of `8C_626/2024`, still there after two repairs. The three controls stay empty. Length, in characters: minimum 731, median 1,156, maximum 1,621. The router reported 48,878 prompt tokens and 3,086 completion tokens over the 12 calls.

Section 4 used another Qwen, on a rented GPU, because this router then had no provider enabled for the ids that were tried. This run is the inference service. The checker is unchanged. It still does not read the facts. Six of the seven Apertus faults do not recur. The remaining one is the model's wording, which the checker catches.

These counts are the ten `RESULT` lines of that call. No fiche text is copied here (D-031).

## 6. All 100 fiches, through the same router

The whole v2 probe, 28 November 2026, about 10:05 to 10:08 CET (196 seconds). Same 50 rulings as section 2, both languages, 100 fiches. Same writer and the same router call as section 5 (`Qwen/Qwen3.8-27B`, thinking off). No threshold was set. No person read the fiches. The ten fiches of section 5 are called again here, so a fiche can differ. `8C_626/2024` in French was flagged there and is empty here.

The current checker, re-applied to the stored Apertus fiches, still flags the same 7 as section 3 and no others.

| | Fiches | Flagged |
|---|---|---|
| Apertus | 100 | 7 |
| Qwen3.8-27B | 100 | 13 |
| Both empty | 83 | |
| Apertus only | 4 | |
| Qwen only | 10 | |
| Both flagged | 3 | |

Of the 7 fiches Apertus leaves flagged, 4 are empty for Qwen, 1 keeps the same critique (`9C_143/2026` French, "manifestly ill-founded" copied), and 2 are flagged for a different reason (`8F_22/2025` French, Suva absent from the ruling; `8C_258/2026` German, "manifestly ill-founded" copied).

Qwen critiques, 13 fiches, one critique each:

| Critique | Fiches |
|---|---|
| "manifestly ill-founded" copied | 5 |
| article missing from the ruling | 4 |
| German sigil | 2 |
| admission missing from the outcome | 1 |
| Suva absent from the ruling | 1 |

| Docket | Language | Matter | Apertus | Qwen |
|---|---|---|---|---|
| `8C_682/2024` | German | accident | none | article missing (`art. 4 ATSG`) |
| `8C_682/2024` | French | accident | none | article missing (`art. 4 LPGA`) |
| `8C_7/2026` | French | accident | none | article missing (`art. 106 LPGA`) |
| `8C_564/2025` | German | accident | none | admission missing from the outcome |
| `8F_22/2025` | French | accident | article missing (`art. 4 LPGA`) | Suva absent from the ruling |
| `8C_258/2026` | German | accident | French sigil | "manifestly ill-founded" copied |
| `8C_54/2025` | French | disability | none | German sigil |
| `9C_677/2025` | German | disability | none | "manifestly ill-founded" copied |
| `9C_677/2025` | French | disability | none | "manifestly ill-founded" copied |
| `9C_85/2025` | French | disability | none | German sigil |
| `9C_143/2026` | French | disability | "manifestly ill-founded" copied | "manifestly ill-founded" copied |
| `8C_722/2025` | French | disability | none | article missing (`art. 17 LPGA`) |
| `4A_451/2025` | German | contract | none | "manifestly ill-founded" copied |

By matter, fiches flagged, Apertus then Qwen: accident 3 and 6 of 32, disability 2 and 6 of 32, health 1 and 0 of 16, occupational pension 1 and 0 of 10, contract 0 and 1 of 10. By language: German 2 and 5 of 50, French 5 and 8 of 50.

Eighty-six fiches took one call. Fourteen took the two repairs. One of those fourteen ends empty (`8F_22/2025` German). Length of the Qwen text, in characters: minimum 511, median 1,079, maximum 1,865. None is under 400 characters. The router reported 405,366 prompt tokens and 33,103 completion tokens over 128 calls.

The checker flags Qwen on more of these fiches than Apertus. Four of Apertus's seven faults do not recur. The other faults, on either model, are the wording the checker catches. It still does not read the facts.

These counts are the 100 `RESULT` lines of that run, and a re-check of the stored Apertus fiches with the current `blocking()`. No fiche text is copied here (D-031).

## 7. Same 100 fiches, after finishing, with an extra list for Qwen only

28 November 2026, 10:31 to 10:33 CET (141 seconds). Same 50 rulings, both languages, 100 fiches. No threshold was set. No person read the fiches. Apertus stays the runtime model (E1).

Two differences from section 6. The checker reads the fiche after `finish()` in `src/summarize/finish.py` (the statute abbreviations of the fiche's language, an article the ruling does not contain removed, and "manifestly ill-founded" removed unless the ruling contains `offensichtlich` or `manifestement`). Qwen also receives `qwen_comparison` in `src/summarize/v2/prompts.py`, four general lines appended to the v2 system prompt for this probe only. `system_prompt` does not include them. The stored Apertus fiches are not regenerated. They go through the same `finish()`, then the same checker.

| | Fiches | Flagged |
|---|---|---|
| Apertus, stored fiche after `finish()` | 100 | 12 |
| Qwen3.8-27B, with `qwen_comparison`, after `finish()` | 100 | 2 |
| Both empty | 87 | |
| Apertus only | 11 | |
| Qwen only | 1 | |
| Both flagged | 1 | |

The one fiche flagged for both is `8C_500/2025` in German (dismissal missing from the outcome).

Of the 7 critiques stored for Apertus in section 3, `finish()` clears 3 (the German sigil, the French sigil, and the article absent from the ruling). Four remain. `finish()` also flags 8 fiches whose stored list was empty, each because the dismissal is no longer in the last sentences. That is the 12.

| Docket | Language | Matter | Apertus after `finish()` | Qwen after `finish()` |
|---|---|---|---|---|
| `8C_223/2025` | French | accident | dismissal missing | none |
| `8C_682/2024` | German | accident | none | dismissal missing |
| `8C_500/2025` | German | accident | dismissal missing | dismissal missing |
| `8C_564/2025` | German | accident | none | Suva absent from the ruling |
| `8C_66/2026` | German | accident | dismissal missing | none |
| `8C_54/2025` | German | disability | dismissal missing | none |
| `8C_567/2025` | French | disability | none | Suva absent from the ruling |
| `9C_143/2026` | French | disability | "manifestly ill-founded" copied | none |
| `9C_91/2026` | German | disability | dismissal missing | none |
| `9F_29/2025` | French | health | fiche is only the operative sentence | none |
| `9C_684/2024` | French | pension | operative block pasted | none |

By matter, fiches flagged, Apertus then Qwen: accident 3 and 3 of 32, disability 3 and 1 of 32, health 1 and 0 of 16, occupational pension 1 and 0 of 10, contract 0 and 0 of 10. By language: German 4 and 3 of 50, French 4 and 1 of 50.

Ninety-four Qwen fiches took one call, one took two, five took three (111 calls). Length of the Qwen text, in characters: minimum 426, median 1,022, maximum 2,335. The router reported 406,543 prompt tokens and 28,252 completion tokens. `finish()` removed an article absent from the ruling on 2 Qwen fiches and swapped a sigil on 2.

These counts are the 100 `RESULT` lines of that run, and the same `finish()` plus checker on the stored Apertus fiches. No fiche text is copied here (D-031).
