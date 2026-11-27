# Triage outer gate: "possibly relevant"

> **Status: PROPOSED (27 Nov 2026).** Not adopted by the team. Code: `src/triage/outer_gate.py`, tests: `tests/test_outer_gate.py`.
> It is one candidate answer to D-021 point 2 ("is a net needed, and what is clearly out of domain?") and sits next to the layer-1 proposal in `docs/TIPS_LAYER1_FILTER_HANDOFF.md`. Section 7 compares the two.

## 1. Open questions this touches

| Question | Options | Recommendation here | What it changes in the code |
|---|---|---|---|
| D-021 point 2: is a net needed, and how wide? | no net / this gate / the wider filter E+ of the layer-1 handoff | Two tiers. This gate defines the tier a lawyer is told is complete ("possibly relevant"); a score ranks inside it ("suspected relevant"). Rulings outside stay stored and searchable with a reason code. | Nothing is settled in code: the gate is a pure function, and a caller may ignore its result. |
| Q-06, Q-31: are courts and areas outside accident and disability insurance in scope? | area only / add the civil-law daily-allowance cases / add everything the layer-1 filter E+ keeps | Keep this gate to the one rule, and show civil-law daily-allowance rulings as a separately tagged group (not built here). | The gate takes no docket and no court, so widening is an added rule, not a rewrite. |
| D-050: which date defines a quarter? | decision date / publication date | Numbers below use the **decision date**, as Suva's list does. | None: the gate does not look at dates. |
| Q-04: is Suva's list complete? | closed world / not | Precision and F2 below assume it is. Recall does not depend on it. | None. |
| D-031: what derived from Suva's data may be committed? | see D-031 | Only aggregate counts are in this file. No per-docket label, no Suva text. | None. |

## 2. The rule

**A ruling is possibly relevant when its subject area is accident insurance, military insurance or disability insurance.**

Nothing else is checked at this level: not the court, not the docket prefix (G5), not the bench, not the length, not whether Suva is named. No model is involved.

Why these three areas: accident and military insurance are what Suva insures; disability insurance shares the general social-insurance law (ATSG) that Suva applies, and Suva's list contains such rulings.

## 3. How the area is read

Two sources; **either one is enough**.

1. **The court's list of new rulings** (`sachgebiet` of a `RulingRecord`), for example `Unfallversicherung`, `Assurance-invalidité*`, `Assicurazione contro gli infortuni`. The trailing star (proposed for publication) is ignored.
2. **The subject line of the ruling's header**, the line under `Gegenstand`, `Objet` or `Oggetto`, for example `Unfallversicherung (Kausalzusammenhang)`.

Matching, case-insensitive, on the part before the first parenthesis:

| Area | German | French | Italian |
|---|---|---|---|
| Accident insurance (UV) | `Unfallversicherung` | `Assurance-accidents` | `Assicurazione contro gli infortuni` |
| Military insurance (MV) | `Militärversicherung` | `Assurance militaire` | `Assicurazione militare` |
| Disability insurance (IV) | `Invalidenversicherung` | `Assurance-invalidité` | `Assicurazione per l'invalidità` |

Design choices:

- **Whole names, not fragments.** `invalidit` alone would also match an occupational-pension subject such as `Prévoyance professionnelle (rente d'invalidité)`; `milit` alone would match the military service exemption tax (`Militärpflichtersatz`). Both are tested.
- **The parenthesis is not read.** It holds the topic of the dispute, not the area.
- **Fail open.** If the list has no area and the header has no subject line, the ruling is kept and flagged `area_undetermined`.
- **A reason for every outcome.** Kept rulings list the rules that kept them (`list_area:UV`, `header_area:IV`, `area_undetermined`); dropped rulings carry the reason code `area_not_uv_mv_iv`. `OuterGateDecision.net_decision()` returns the shared `NetDecision` contract.
- **The header layout is the court's real one.** The pages put a non-breaking space after the heading; a first version of the reader missed every header because of it. The tests now use that layout in German, French and Italian.

## 4. Measurements

Ours, measured on 27 Nov 2026 with `outer_gate.measure` on the team's data-layer database (every Federal Court ruling decided 1 Oct 2025 to 30 Jun 2026, plus the 23 rulings decided in Q3/2025 that Suva summarised). Quarters by decision date. "Relevant" means on Suva's list `judgements/BG_Urteile_2025_Q4_2026_Q1.xlsx` (59 Federal Court rulings); every other ruling of the two listed quarters counts as not relevant (closed world, Q-04).

| Quarter | Rulings | Kept | Share kept | Relevant kept | Recall | Precision | F2 |
|---|---|---|---|---|---|---|---|
| Q4/2025 | 1,931 | 135 | 7.0% | 28 of 28 | 1.00 | 0.207 | 0.567 |
| Q1/2026 | 2,005 | 165 | 8.2% | 31 of 31 | 1.00 | 0.188 | 0.536 |
| Q4/2025 + Q1/2026 | 3,936 | 300 | 7.6% | 59 of 59 | 1.00 | 0.197 | 0.550 |
| Q2/2026 (no labels) | 2,096 | 189 | 9.0% | unknown | | | |

Kept rulings by area:

| Quarter | Accident | Military | Disability |
|---|---|---|---|
| Q4/2025 | 39 | 0 | 96 |
| Q1/2026 | 56 | 1 | 108 |
| Q2/2026 | 60 | 3 | 126 |

How the kept rulings were recognised:

| Quarter | List and header agree | Header only | List only | Area undetermined |
|---|---|---|---|---|
| Q4/2025 | 132 | 2 | 1 | 0 |
| Q1/2026 | 162 | 2 | 1 | 0 |
| Q2/2026 | 156 | 32 | 1 | 0 |

- In Q2/2026, 442 rulings have no area from the court's list in our database (the daily lists after 30 June could not be fetched). The header decides for them: 32 are kept, 410 name another area.
- In the two listed quarters the list and the header disagree on in or out for 6 of 3,930 rulings that have both.
- Kept rulings come from courts 8C and 9C and their revision or correction proceedings (8F, 9F, 9G). No rule names a court: this is what the area produces.
- Languages of the kept Q2/2026 rulings: 119 German, 67 French, 3 Italian.

**Check on rulings that played no part in the design.** Of the 23 rulings decided in Q3/2025 that Suva summarised (`judgements/Export_*.html`), the gate keeps 22. The one it drops is the civil-law ruling filed under contract law (its header subject is daily-allowance insurance). Q3 has no complete list, so only this recall can be read from it.

## 5. What "none missed" does and does not mean

The gate kept 59 of 59 in the two listed quarters. That is not proof of 100% recall. With zero misses observed, the 95% upper limit for the share of relevant rulings among those dropped (rule of three) is:

| Dropped group, Q4/2025 + Q1/2026 | Dropped | Relevant among them | Could still be up to | Per quarter |
|---|---|---|---|---|
| All dropped rulings | 3,636 | 0 | 0.08% | about 1.5 rulings |

The claim to make: none missed in two complete quarters, 22 of 23 on an independent set, and up to one or two possible misses a quarter that this data cannot rule out. The hidden Q2/2026 list is the real test.

## 6. What it leaves out, knowingly

| Group | Size | What we know |
|---|---|---|
| Other non-tax rulings of the two social-law courts (unemployment, pensions, supplementary benefits, health, old-age, social assistance) | 256 in the two listed quarters, 147 in Q2/2026 | None on Suva's list in the two listed quarters |
| Civil-law rulings on private daily-allowance insurance and liability | about 5 a quarter that lean on social-insurance law | Suva summarised one in Q3/2025; none on the list in the two listed quarters |
| Rulings outside the three areas that mention Suva (criminal, bankruptcy, immigration, other insurance) | 23 of the 108 that mention Suva in the two listed quarters, 7 of 59 in Q2/2026 | None on Suva's list; Suva is a party in 3 of them, all bankruptcy cases |
| Everything else the court decides | about 1,600 a quarter | None on Suva's list |

Single-judge rulings are **not** excluded. An earlier version dropped them (none of about 70 was on the list), but there was no reason behind that rule beyond the count, and Suva summarised one such ruling in Q3/2025. They stay in this tier and lose rank in the score.

## 7. Relation to the layer-1 proposal

`docs/TIPS_LAYER1_FILTER_HANDOFF.md` measures filters A to E on the Hugging Face population and recommends E+. Its numbers are that document's measurements, not ours.

| | This gate | Filter E+ (layer-1 handoff) |
|---|---|---|
| Rule | area is accident, military or disability insurance | court 8C/9C, or social-insurance domain, or Suva/accident terms in the text, or insurance, liability and daily-allowance keywords in the title, or no title |
| Kept in Q2/2026 | 189 | about 525 |
| Suva list (59) | 59 of 59 | 59 of 59 |
| Q3/2025 summaries (23) | 22 of 23 | 23 of 23 (keywords widened after seeing the miss) |
| Uses the docket prefix | no | yes, as one of several rules |
| Purpose | the tier shown to a lawyer as "possibly relevant" | the set Apertus judges |

The handoff's rule "subject UV, IV or MV" is the same idea as this gate and gives nearly the same count (188 in Q2/2026 there, 189 here).

The two can coexist: E+ as the set that is scored, this gate as the tier presented as complete. Which one is the net of D-021 is the team's call; this file does not settle it.

## 8. Not done yet

- **Not called by `make run`.** There is no triage stage on `main` to call it from. It is a tested function with no caller.
- **No stored output.** `measure` returns counts; nothing is written to `results/`, so the numbers above are not yet reproducible through `make claims` (G11 applies once they are quoted in the README, the report or the deck).
- **End-to-end on real rulings:** run by hand on three listed rulings, one German (accident insurance), one French (accident insurance) and one Italian (disability insurance), each kept through both the list area and the header subject; and on one German health-insurance ruling, dropped with `area_not_uv_mv_iv`. Their header layout is in the tests; the rulings themselves are not in the repo.
- **The civil-law watch group** of section 6 is described, not built.
- **Measured on the data-layer database, not on the crawl.** When the crawled Q2 list exists, rerun `measure` on it.
