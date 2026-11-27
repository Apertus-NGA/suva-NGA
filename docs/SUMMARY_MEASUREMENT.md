# TECHNICAL REPORT — SUMMARY MEASUREMENT

A measurement of generated Suva fiches, written so a reader of the technical report finds the same sections in the same order. One run, 27 November 2026. The official summary hold-out remains `docs/EVAL.md` §4. Thresholds there stay unset.

Open questions left open, with the "While open" line of `docs/DECISIONS.md`: D-047 (which rulings are summarised: top 10 first), Q-30 (style follows the ruling's language), Q-08 / D-053 (length follows the 55 exports; this run used no character band), Q-27 (same paragraph plan in both languages; parity was not scored), D-031 (nothing derived from Suva's files is committed here; the lead decides before Friday 22:00).

- **Challenge partner:** Suva
- **Challenge:** Identification of relevant Federal Court judgements and preparation of a legal summary
- **Event:** On-site Zurich
- **Team:** `team name`
- **Demo:** `link to video`

## 1. SUMMARY

The question was whether a program can count the legal failures of a fiche by reading only the fiche and the ruling, and whether that count matches a human reading.

One prompt was frozen. Ten rulings were drawn before any of them was generated (seed `20261127`), outside Suva's relevance list. German and French were written separately from the ruling with Apertus v1.5 70B. A person read each fiche against the ruling. A counter was then compared with that reading.

After the counter was corrected, it agrees on 20 fiches out of 20. On the 134 fiches already written in that working copy, 3 German texts are the operative sentence alone (`8C_54/2025`, `9C_63/2025`, `9C_719/2025`). The count covers the disposition, the phrase "manifestement non fondé" / "offensichtlich unbegründet", a fiche that is only the operative sentence, an article or a party absent from the ruling, a sigil in the wrong language, and the 50 % wear rule stated backwards. Style, gender, and facts the program cannot see in the ruling stay outside it. It is not a score out of 100, not recall, and not F2.

## 2. ARCHITECTURE

The generator and the counter are separate. The generator calls the model once per language. The counter never calls the model. It reads a fiche already written and the ruling text.

**Disposition.** The operative block is the text after the last "Demnach erkennt", "erkennt die Präsidentin", "erkennt der Präsident", "Par ces motifs" or "Per questi motivi". Point 1 of that block is the appeal, so a later grant of legal aid is not the outcome. The fiche uses the last sentence that states an outcome. Both sides map to inadmissible, partial, admitted or rejected. "tritt … nicht ein" and "nicht eingetreten" are inadmissible. "rejette" and "rejeté" are a rejection. "soweit darauf eingetreten wird" stays a decision on the merits.

**Phrase.** A French fiche is flagged for "manifestement non fondé" or "manifestement infondé", and a German fiche for "offensichtlich unbegründet", unless the ruling contains that phrase. The bare word "offensichtlich" also appears in the article 42 formula and does not count. "manifestement inexacte" is the standard for facts, not this phrase.

**Only the operative sentence.** The operative sentence is removed. If fewer than 80 characters remain, the fiche is only the disposition. A long fiche stays valid. There is no character ceiling.

**Other checks**, taken from the generator's own blocking list: an article whose number and statute are absent from the ruling; Suva named when neither "Suva" nor "CNA" is in the ruling; a sigil in the wrong language; the 50 % wear rule inverted.

### TARGET ARCHITECTURE (MANDATORY)

Generation ran against the hosted Apertus endpoint (a Swiss gateway, configuration only through `LLM_NAME`, `LLM_BASE_URL`, `LLM_API_KEY`). The counter runs on the machine that holds the fiches and the ruling texts. It opens no network connection. Build time is the prompt and the counter. Runtime for a new fiche is the gateway. The three deployment lines of the project (on-premise, air-gapped, sovereign Swiss cloud) are unchanged by this measurement: an air-gapped run needs the weights on site, because this probe used the hosted endpoint.

## 3. USE OF APERTUS

- **Model:** Apertus v1.5 70B, id in `MODELS.md`, via the gateway.
- **How it is used:** inference. The counter is code. Apertus does not grade its own fiches.
- **Where it runs:** hosted endpoint. The measured run used a generator that called the gateway directly (`urllib`). Since `acd3f2d` (27 Nov, 21:05 CET), `src/summarize/summarize.py` calls it through the kit client `src/llm/client.py` (`client_from_env("live")`), so the G2 check (`tests/test_doctrines.py`) passes on that file.

Temperature 0.1. German and French each from the ruling. The prompt carried two human fiches as style only, `8C_177/2025` and `8C_224/2025`, without the full rulings. Three one-line human fiches stayed out of the examples: `8C_21/2025`, `8C_44/2025`, `8C_455/2025`.

## 4. DATA

The draw was written down before generation. Seed `20261127`. Pool: courts 8C and 9C, accident insurance and disability insurance, absent from Suva's relevance list, decision date before 1 April 2026. The pool had 254 rulings. Ten were drawn:

| Docket | Decision date | Subject on the news page |
|---|---|---|
| `8C_180/2025` | 2025-08-25 | Unfallversicherung |
| `8C_287/2025` | 2026-01-28 | Invalidenversicherung |
| `8C_54/2025` | 2025-11-04 | Invalidenversicherung |
| `8C_542/2025` | 2025-10-14 | Unfallversicherung |
| `8C_567/2025` | 2025-10-16 | Invalidenversicherung |
| `8C_660/2025` | 2026-01-15 | Invalidenversicherung |
| `8C_743/2024` | 2025-11-10 | Invalidenversicherung |
| `9C_551/2025` | 2025-11-13 | Invalidenversicherung |
| `9C_63/2025` | 2026-03-10 | Assurance-invalidité |
| `9C_719/2025` | 2026-03-03 | Assurance-invalidité |

`src/courts.py` on this branch has since widened the keep set. These ten were not redrawn.

Suva's own exports in `judgements/` were not the target of this reading. The comparison with those 23 exports is `docs/EVAL.md` §4 and has not been run. This note quotes no text from `judgements/`. Ruling texts and generated fiches are public-court material and our output. They lived under `data/trial/`, which is git-ignored. Personal fields from Suva's exports are not in this note (D-051).

The wider pile, 134 fiches, is the classeur batch plus earlier trials plus these ten. It is the pile on disk that evening, not a sample drawn to estimate a rate.

## 5. LIMITATIONS

The first counter agreed with the first human labels on 16 of 20 fiches. The gap was the research.

`8C_287/2025` and `9C_551/2025` in French call the appeal manifestly ill-founded. A first reading treated that as invented, because the operative sentence is a plain dismissal and an earlier "offensichtlich" belongs to the article 42 formula. The rulings say the phrase in the reasoning, for the simplified procedure: "erweist sich als offensichtlich unbegründet" and "ist offensichtlich unbegründet". The French sentence follows the ruling.

`8C_567/2025` in French says the facts were established in a "manifestement inexacte" way. That is the standard for facts. A counter that flags every "manifestement" is too wide.

A numbered point "1." matched inside a date ("21. März"). A grant of legal aid ("wird gutgeheissen") was read as an admission of the appeal when point 1 dismissed it.

`8C_567/2025` in French calls the appellant "un assuré" where the ruling has a female appellant. The counter does not see gender.

Ten rulings do not make a percentage for the report. The per-fiche JSON is not on this working copy (`data/` is empty) and `make claims` cannot regenerate the table. The next measurement, if the prompt changes, uses ten new dockets. These ten stay frozen.

A fiche that passes this count can still invent a fact the program cannot check. House style was read by a person and is not in the number.

## 6. REPRODUCIBILITY

| Item | Value |
|---|---|
| Date | 27 November 2026, one run |
| Model | Apertus v1.5 70B, temperature 0.1 |
| Seed of the draw | `20261127`, list fixed before generation |
| Fiches in the frozen ten | 20 (10 rulings, German and French) |
| Agreement after the counter was corrected | 20 / 20 |
| Fiches already written that evening | 134, of which 3 failed the count |
| Failures | German only-the-disposition: `8C_54/2025`, `9C_63/2025`, `9C_719/2025` |

### HOW TO RUN

The counter and the generator are in `src/summarize/` (`tally.py`, `summarize.py`, plus `glossary.json`). `tmp/pre-kit/` is empty. The generator now calls the gateway through `src/llm/client.py`; the run measured here used the earlier version, which called it directly. Re-running the count needs the ruling texts and the fiches that were under `data/trial/`. Those files are not in the repository, and they are not on this working copy. The numbers in section 6 are the stdout of that one run.

From the repo root, with the cache in `data/cache/` and `LLM_*` in `.env`:

```bash
python src/summarize/summarize.py 8C_78/2025
python src/summarize/tally.py
```

`make check` does not run this probe. It does scan `src/`: G2 flagged the version committed at 20:51 (`f140bb0`: `LLM_BASE_URL`, `LLM_API_KEY`, `/chat/completions`) and passes since `acd3f2d`. On 27 November `make check` reported 73 passed, both while the probe scripts were outside `src/` and at 21:11 CET with them under `src/`.

## LICENSE

Creative Commons Attribution 4.0 (CC-BY-4.0), the same licence section as `technical_report.md`. Suva's files in `judgements/` and the pitch PDF stay Suva's.

## REFERENCES

- `technical_report.md`, sections 1 to 6, the heading order this note follows.
- `docs/EVAL.md` §4, the summary hold-out this note does not replace.
- `docs/agents/summarise.md`, the role brief.
- `docs/DECISIONS.md`, D-047, D-053, D-031, Q-08, Q-27, Q-30.
- `docs/SUVA_DATA.md`, what the 55 exports contain. This note does not copy them.
- `MODELS.md`, the model ids.
