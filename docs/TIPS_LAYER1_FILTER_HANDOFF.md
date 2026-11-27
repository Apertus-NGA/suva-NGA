# Layer 1 — Recall-safe pre-filter for Suva case-law triage

**Owner:** layer-1 owner (`<handle>`) · **Prepared:** 27 Nov 2026, ~21:00 Zurich · **Status:** PROPOSED (measured, not yet adopted by the team)
**Scope:** layer 1 only. Layer 2 (Apertus judging Suva relevance, incl. the experimental fine-tune) is owned by the layer-2 owner and is out of scope here, except for the interface contract in §8.

---

## Résumé en français

- **Ton rôle.** La couche 1 réduit le volume avant qu'Apertus juge chaque arrêt (couche 2). Sa seule exigence est de **ne perdre aucun arrêt pertinent pour la Suva**. Tout ce qu'elle coupe est perdu définitivement, et le challenge est noté au F2, qui pénalise un oubli quatre fois plus qu'un faux positif.
- **Ce qui est déjà mesuré**, sur la population HF complète (T3/2025 à T2/2026) avec les 59 positifs de la liste Suva et les 23 résumés de T3/2025 :
  - **Filtre A** (cours 8C/9C) : 59/59 et 22/23, coupe 81 à 84 %.
  - **Filtre B** (domaine bger « assurances sociales ») : 59/59 et 22/23, coupe 84 à 87 %.
  - **Filtre E** (liste blanche large) : **59/59 et 23/23, coupe 77 à 80 %.** Sur T2/2026, il garde **478 arrêts sur 2 096**.
- **Le piège 4A_106/2025.** C'est un arrêt civil (assurance d'indemnités journalières, droit des contrats) résumé par la Suva. A et B le perdent ; seul le mot « Taggeld » du titre le rattrape dans E. **E a été élargi après avoir vu ce cas** : son 23/23 est donc optimiste.
- **Alerte n° 1 : dérive des métadonnées sur T2/2026.** Le champ `legal_area` (domaine) est vide pour **1 683 des 2 096 arrêts T2**, contre 0 à 44 sur les trimestres d'entraînement. Un filtre fondé sur le domaine, validé sur T4 et T1, se comportera différemment le jour J. E tient grâce à ses autres règles (cour, titre, texte), mais il faut le revérifier sur T2.
- **Alerte n° 2 : les 47 arrêts T2 sans titre sont tous coupés par E** (surtout 4A et 5A). Recommandation : **les laisser toujours passer** (+47 arrêts, coût négligeable).
- **Contrat avec la couche 2.** Chaque arrêt reçoit `layer1.pass` (booléen) et `layer1.reasons` (liste des règles qui l'ont gardé). C'est un indice, jamais un label. La couche 2 ne juge que les arrêts qui passent.
- **Prochaines étapes conseillées.** (1) Adopter E + « sans titre, on garde », (2) relancer `mesure_filtres.py` sur la vraie liste T2 du crawl, (3) mettre en place un filet : un échantillon aléatoire des arrêts coupés passe quand même par Apertus 8B, (4) trancher les questions ouvertes du §10.

---

## 1. Goal and success criteria

The pipeline triages every Federal Court (BGer) ruling of a quarter and returns, for each one, a Suva-relevance score with an explanation. It has two layers:

| Layer | Job | Owner | Cost per ruling |
|---|---|---|---|
| **1. Filter (this doc)** | Drop rulings that cannot be Suva-relevant | layer-1 owner | ~0 (metadata, regex) |
| 2. Judge | Apertus decides whether the ruling is in Suva's scope; score + reasoning | layer-2 owner | 1 LLM call (measured wall-clock at 4 workers: 8B ~0.17 s, 70B ~0.29 s per ruling) |

**Hard requirement: recall = 100 %** on every labelled positive we have. Anything layer 1 drops never reaches layer 2 and is a guaranteed miss in the official Recall/F2 score (F2 weights recall 4× precision).
**Secondary objective:** cut as much volume as possible, so that layer 2 gets a smaller, harder set of rulings (which also improves its precision; see §7).
**Non-goals:** ranking, relevance judgement, explanations. Layer 1 never says "relevant", only "cannot be excluded".

Acceptance criteria proposed for adoption:
1. 59/59 positives of the Suva list (Q4/2025 + Q1/2026) pass.
2. 23/23 Q3/2025 Suva summaries pass.
3. Every rule is explainable in one line to a Suva lawyer (`layer1.reasons`).
4. Measured volume cut ≥ 70 % per quarter on Q3/2025–Q1/2026, and reported on Q2/2026.
5. Deterministic, metadata-only or cheap text checks, runs on 2,100 rulings in seconds.

## 2. Population and labels (what "recall" is measured on)

Source: the population audit in `/mnt/project-files/hackapertus/population-tf/` (README in French).

- **Population** = every BGer decision with a decision date in the quarter, from Hugging Face `voilaj/swiss-caselaw` `data/bger.parquet` at commit `35b17aa9c3fad71011b72f78f6ab79650ec0cf96` (export 26 Nov 2026, SHA-256 `d2b2df1d…bb3711`). Twins removed. Cross-checked against entscheidsuche.ch: 7,780 of 7,781 decisions match.
- **One CSV** holds everything: `population-tf/donnees/population_tf_hf_2025Q3_2026Q2.csv` (7,781 rows). Useful columns: `decision_id`, `docket`, `decision_date`, `lang`, `chamber`, `title` (the bger "Gegenstand"), `legal_area`, `prefixe`, `trimestre_decision`, `matiere` (UV/IV/MV/autre derived from title), `txt_suva`, `txt_cna`, `txt_insai`, `txt_loi_laa`, `txt_assurance_accidents` (keyword hits in the full text), `label_suva`.
- **Labels** (`label_suva`): `positif 2025 Q4` (28), `positif 2026 Q1` (31), `resume Q3/2025 (hors liste)` (23), empty = not selected by Suva. The 60th entry of the Suva list is a cantonal ruling (KG BL) and is outside the BGer population.

| Quarter (decision date) | Rulings | Suva positives | Use for layer 1 |
|---|---|---|---|
| Q3/2025 | 1,749 | 23 summaries (list incomplete) | recall check only, on the 23 |
| Q4/2025 | 1,931 | 28 | recall + volume |
| Q1/2026 | 2,005 | 31 | recall + volume |
| Q2/2026 | 2,096 | unknown (this is the evaluation) | volume only |

**Label caveat.** Q3/2025 only has summaries, not the full Suva list. 79 % of Q4 positives have a summary, but only 32 % of Q1 positives do, so Q3 probably has 6 to 15 unlabelled positives. Q3 negatives are therefore unreliable: use Q3 only to check that the 23 summaries pass, never to estimate precision.

**What Suva selects (facts from the audit):** all 59 listed positives are in subject UV (accident) or IV (invalidity); none are elsewhere. Suva keeps about half of UV rulings and fewer than one IV ruling in ten. 14 of the 59 are pure IV cases (IV office vs insured person) that mention neither Suva, CNA, LAA/UVG nor accident insurance. **A keyword filter on "Suva" would lose all 14** (see doctrine G5 in the kit: never filter on "Suva").

## 3. Filters measured

Script: `mesure_filtres.py` (this folder). Run it with `python3 -I mesure_filtres.py <population csv>`. Output in `mesure_filtres.json`.

| Filter | Definition | Suva list | Q3 summaries | Cut Q3/25 | Cut Q4/25 | Cut Q1/26 | Cut Q2/26 (kept) |
|---|---|---|---|---|---|---|---|
| **A** social courts | `prefixe ∈ {8C, 9C}` | 59/59 | 22/23 | 82.4 % | 83.9 % | 80.9 % | 81.3 % (392) |
| **B** bger domain | `legal_area` matches social insurance (AA, AI, AM, AVS, PC, LPP, chômage, maladie, APG, allocations familiales; DE/FR/IT); if `legal_area` empty, same regex on `title` | 59/59 | 22/23 | 85.6 % | 86.9 % | 84.4 % | 85.1 % (312) |
| C | B ∪ `matiere ∈ {UV, IV, MV}` | 59/59 | 22/23 | same as B | | | |
| D | A ∪ C ∪ text mentions Suva/CNA/INSAI/LAA/assurance-accidents | 59/59 | 22/23 | 80.6 % | 82.6 % | 79.5 % | 79.8 % (424) |
| **E** broad whitelist | D ∪ `title` matches insurance / liability / daily allowance / recourse / social-insurance acronyms (`filtre_e.py`) | **59/59** | **23/23** | 78.0 % | 80.4 % | 76.8 % | **77.2 % (478)** |

What E keeps on Q2/2026, by court: 8C 229, 9C 163, 4A 22, 5A 15, 6B 13, 2C 8, 8F 6, 9F 6, 7B 5, 1C 5, others 6.
What E keeps that a lawyer would look at on the labelled quarters: Q4/2025 378 rulings = 28 positives + 104 UV/IV/MV non-selected + 246 others; Q1/2026 466 = 31 + 131 + 304.

### 3.1 Rule-by-rule anatomy (82 labelled positives, Q2/2026 volume)

| Rule | Positives hit | Q2 kept by this rule | Q2 rulings kept **only** by this rule |
|---|---|---|---|
| court 8C/9C | 81/82 | 392 | 96 (68 in 9C, mostly tax; 28 in 8C, e.g. public-staff law) |
| `legal_area` social | 81/82 | 59 (!) | 1 |
| title social regex (when no `legal_area`) | 0 | 253 | 2 |
| `matiere` UV/IV/MV | 81/82 | 188 | 0 |
| text Suva/CNA/LAA/accident insurance | 62/82 | 86 | 9 |
| title keywords | 82/82 | 330 | 54 |

- 62 positives are caught by 5 rules, 19 by 4, and **1 by a single rule**: `4A_106/2025`, kept only by the title keyword `Taggeld`. That is the single point of failure of the whole filter.
- The court rule adds 96 rulings on Q2 by itself: 68 in 9C, mostly tax and public-finance rulings, and 28 in 8C (9C also handles tax law: 244 "Öffentliche Finanzen & Abgaberecht" rulings in 8C/9C over the year). Dropping 9C tax rulings is the obvious next volume cut, **but only once it is shown that no Suva positive is a 9C tax ruling** (none is today).

### 3.2 The `4A_106/2025` case

Civil law (First Civil Division), title `Taggeldversicherung` (daily-allowance insurance under contract law, VVG), `legal_area = Vertragsrecht`. Suva summarised it in Q3/2025 because private daily-allowance insurance interacts with UVG benefits (coordination, overinsurance). A court-only or domain-only filter loses it. It shows that **Suva relevance crosses court boundaries**: private insurance, liability/recourse (Regress, Haftpflicht), and labour law can matter. Expect 0 to 2 such rulings per quarter.

### 3.3 Tuning bias in E (be honest about it)

E's title keywords were widened **after** seeing that A and B miss `4A_106/2025`. Its 23/23 on Q3 summaries is therefore in-sample. The 59/59 on the Suva list was not tuned (all positives were already caught by A). To get an unbiased number, freeze E now and measure it on any new labelled data (e.g. Suva's Q2 answer list after the event, or summaries we have not looked at).

## 4. Critical risks found

| # | Risk | Evidence | Mitigation |
|---|---|---|---|
| R1 | **Metadata drift on Q2/2026.** `legal_area` is empty for 1,683 of 2,096 Q2 rulings (Q3 0, Q4 1, Q1 44). Rules validated on Q4/Q1 lean on a field that is mostly missing on the evaluation quarter. | measured on the HF CSV | Never rely on `legal_area` alone; keep the court, `title` and text rules; recompute `legal_area` from `title` + court if needed; re-measure on the crawled Q2 list |
| R2 | **47 untitled Q2 rulings all dropped by E** (4A 13, 5A 13, 7B 8, 4D 4…). No title means no title rule and no `matiere`. | measured | **Rule: no title ⇒ pass** (+47 rulings) |
| R3 | Single-rule positive (`4A_106/2025`) ⇒ cross-court positives are fragile | §3.1 | Keep the title keyword list broad; add text keywords on insurance contracts (VVG/LCA, Taggeld) for non-social courts; random safety net (R5) |
| R4 | Source drift: the official crawl is bger.ch "Liste der Neuheiten" (publication date), our population is HF by decision date | `population-tf/README.md` §3 | Run the filter on whatever list the crawl produces; metadata fields may differ (titles from bger.ch vs HF); map them before filtering |
| R5 | Unknown unknowns: a positive with no social-insurance signal anywhere | 14 pure IV cases show Suva's scope is wider than keywords | **Safety net:** send a random 5–10 % sample of the ~1,600 dropped rulings to Apertus 8B (80 to 160 calls, under a minute); any "Ja" there is reviewed and becomes a new rule |
| R6 | Italian rulings (~5 %) under-covered by DE/FR keywords | regexes include IT terms but were not tested on IT positives (only 1 IT positive in the list) | Keep IT terms; check the IT share of dropped rulings |

## 5. Recommended configuration (proposal)

`E+` = E ∪ (`title` empty), i.e. E plus the no-title rule.

- Expected Q2/2026 volume: about **525 rulings** (478 + 47), a **75 % cut**.
- Keep the 96 court-only rulings (9C tax, 8C public-staff) for now: about 16 s of 8B calls. Revisit after the event.
- Output `layer1.reasons` for every kept ruling, and `layer1.reasons = []` with `pass = false` for dropped ones, so that the UI can show "why was this ruling not reviewed?" (Suva's trust concern: "Trust us, we tried").

## 6. How to validate (protocol)

1. **Recall gate (blocking).** On Q4/2025 + Q1/2026: 59/59 must pass. On Q3/2025: 23/23 must pass. Any failure blocks a filter change.
2. **Volume report.** Kept/total per quarter Q3/2025 to Q2/2026, plus by court and language.
3. **Leave-one-quarter-out sanity check.** Design any new rule on one quarter and check recall on the other two before adopting it. Do not tune on Q2 (no labels) and never on test labels.
4. **Hard-negative report.** How many UV/IV/MV rulings Suva did not select are kept (Q4: 104/104, Q1: 131/131 with E). Layer 1 should keep them all: separating them is layer 2's job.
5. **Drift check on the real crawl.** As soon as the crawled Q2 list exists, rerun step 2 on it, compare with the HF numbers above, and list rulings present in one source and not the other.
6. **Safety-net log** (R5): number of dropped rulings sampled, number of "Ja", decisions taken.

## 7. Why layer 1 also helps layer 2 (measured, 27 Nov)

Zero-shot Apertus on the full quarter vs after filter E (score = P(Ja) normalised, threshold 0.5, `suva-ft-v3` data, `finetune/runs_v3/RESULTATS_BASELINE_V3.md`):

| | Q1/2026 full (2,005) | Q1/2026 after E (466) | Q4/2025 full (1,931) | Q4/2025 after E (378) |
|---|---|---|---|---|
| 8B: TP / FP / F2 | 26 / 116 / 0.489 | 26 / 89 / **0.544** | 24 / 82 / 0.550 | 24 / 57 / **0.622** |
| 70B: TP / FP / F2 | 15 / 28 / 0.449 | 15 / 24 / 0.460 | 14 / 10 / 0.515 | 14 / 5 / 0.534 |

The filter removes false positives without removing any true positive, so F2 rises. It also cuts LLM cost by ~4×.

## 8. Interface contract with layer 2

Per ruling, layer 1 emits (JSON, one object per ruling, same id as the crawl):

```json
{
  "decision_id": "bger_8C_464_2025",
  "docket": "8C_464/2025",
  "layer1": {
    "pass": true,
    "reasons": ["court_8C9C", "matiere_UV", "title_kw"],
    "filter_version": "E+@2026-11-27",
    "rules_sha256": "<sha256 of filtre_e.py>"
  }
}
```

Rules:
- `layer1.pass` is a **hint, never a label**. Layer 2 never treats `pass=true` as "relevant".
- Layer 2 scores only `pass=true` rulings, plus the safety-net sample (R5), flagged `layer1.sampled=true`.
- Dropped rulings stay in the output with `pass=false`, so the UI can list them ("not reviewed by the model, reason: no social-insurance signal").
- `filter_version` + `rules_sha256` are written into every run's metadata, so results stay reproducible.
- The fine-tune datasets already carry this flag as `meta.couche1` (`suva-ft-v3`, computed with `filtre_e.py` version of 27 Nov). If the filter changes, the training data does not change; only the subset used for layer-2 evaluation does.

## 9. Files and paths

| Path | What |
|---|---|
| `handoff/layer1-filter/LAYER1_FILTER_HANDOFF.md` | this document |
| `handoff/layer1-filter/filtre_e.py` | filter E as a function `passe(row) -> bool` on a population-CSV row (stdlib only) |
| `handoff/layer1-filter/mesure_filtres.py` | measures filters A–E: recall on the 59 + 23 positives, volume per quarter |
| `handoff/layer1-filter/mesure_filtres.json` | output of the run of 27 Nov |
| `population-tf/donnees/population_tf_hf_2025Q3_2026Q2.csv` | population + labels + signals (7,781 rows) |
| `population-tf/donnees/positifs_suva.csv` | the Suva list as extracted from the xlsx (dates, summary flag) |
| `population-tf/README.md` | population audit, sources, date-window caveats (French) |
| `finetune/runs_v3/RESULTATS_BASELINE_V3.md` | layer-2 baselines with and without the filter (French) |
| HF parquet | `https://huggingface.co/datasets/voilaj/swiss-caselaw/resolve/35b17aa9c3fad71011b72f78f6ab79650ec0cf96/data/bger.parquet` (925 MB) |

Note: the population CSV's `txt_*` columns come from the full text. If layer 1 runs on the crawl output, recompute them with the same regexes (see `population-tf/scripts/02_population_hf_duckdb.py`).

## 10. Open questions (do not settle silently; raise with a recommendation)

| # | Question | Options | Recommendation | What settles it |
|---|---|---|---|---|
| L1-Q1 | Does the Q2 window use publication or decision date? | decision (2,096) / publication (≈2,060) / union (≈2,677) | filter the **union** until Suva answers | Suva (same as kit Q-02 / D-050) |
| L1-Q2 | Keep 9C tax rulings? | keep / drop | keep for the event (cost ~16 s of 8B) | a check that no Suva positive was ever a 9C tax ruling over a longer history |
| L1-Q3 | Safety-net sampling rate | 0 % / 5 % / 10 % / all dropped rulings with 8B | 10 % (≈160 calls, under a minute) | LLM budget on the day |
| L1-Q4 | Recompute `legal_area` for Q2 from title/court? | yes / no | no for the event (other rules cover), yes after | drift check on the crawl (§6.5) |
| L1-Q5 | Should layer 1 widen to labour law / liability / VVG courts (4A, 4D) by text keywords? | keep E / add text rules | add a text rule for VVG/LCA + Taggeld on 4A/4D | review of Q3 summaries outside 8C/9C |

## 11. Next steps (suggested order, ~2 h of work)

1. Read §2 and §4, run `mesure_filtres.py` and reproduce the table in §3 (10 min).
2. Implement `E+` (no-title rule) and the `reasons` output (30 min); re-run the recall gate.
3. Plug it into the pipeline after the crawl, before triage, with the JSON contract of §8 (30 min).
4. Rerun the volume report on the crawled Q2 list and compare with §3 (R1, R4) (20 min).
5. Add the safety-net sample (R5) and its log (20 min).
6. Record the decision in `docs/DECISIONS.md` (filter version, numbers, open questions).
