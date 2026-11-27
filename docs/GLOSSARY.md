# GLOSSARY: legal terms DE / FR / IT

> **Status: v0 PROPOSAL (27 Nov 2026), to validate; updated after the official template was read.** Owner: summaries. Check every line against real rulings and Suva's human summaries (in `judgements/`, `docs/SUVA_DATA.md` §3) before locking it; a locked line is then used by prompts and by the verifier. Lines marked ⚠ are the least certain.
> Rules: references (dockets, BGE/ATF/DTF, articles, E./consid.) are never typed by the model; code parses them into canonical ids and renders them in the summary's language with the abbreviations below (D-037). The French summary uses the French term, not a calque of the German one.
>
> §0 defines the project's own terms; the tables after it are legal vocabulary.

## 0. Project terms

| Term | Meaning |
|---|---|
| **Neuheiten** (Liste der Neuheiten) | bger.ch's daily list of rulings newly put online; the only source of the publication date and the star |
| **Star** (`*`) | mark in the Neuheiten list: ruling destined for publication in the official reports (BGE/ATF) |
| **Publication date / decision date** | publication date: the date a ruling was put online (the Neuheiten page date), not the decision date. Decision date: the date the Court decided, written in the ruling and in its bger.ch `docid`. The gap is 9 days to about 10 weeks (`docs/CHALLENGE.md` §10). The deck defines Q2/2026 by publication date (D-009); Suva's list labels its quarters by decision date. Which date defines a quarter is open (D-050): every ruling carries both |
| **Docket** | the case number, e.g. `8C_802/2023` (court 8C, number, year of filing) |
| **8C, 9C, 4A…** | Federal Court divisions by docket prefix (`docs/DATA.md` §5) |
| **E. / consid.** | a numbered consideration (reasoning paragraph) of a ruling. Suva's German examples mix `E.`, `Erw.` and `Erwägung`; its French examples almost always use `consid.` (one writes "voir point"). While Q-30 is open we render `E.` and `consid.` (D-037) |
| **Signal** | an observable fact about a ruling computed by code, with the text span that proves it (e.g. "Suva is a party") |
| **SR1-SR9** | Suva's nine example relevance rules (`docs/CHALLENGE.md` §7) |
| **Net** (mechanical net) | an optional code filter that would drop only clearly out-of-domain rulings, with a reason code (D-021) |
| **Key statement** | the one or two sentences of a ruling that change practice, with the consideration that holds them |
| **Digest** | a short few-shot example built from a labelled ruling: subject, parties, 2-3 lines of the key consideration, label, one-sentence reason |
| **A0-A4, A0-kw** | the triage variants compared in evaluation (`docs/EVAL.md` §2); A0-kw is the template's keyword baseline ("Suva or Accident") |
| **Capacity floor** | the minimum time a stage needs given gateway latency and concurrency (`docs/ARCHITECTURE.md` §6) |
| **Hit score** | Suva's "did you find them" axis: recall and F2 of our list (deck), or Suva's experts' check of our 30 highest-scored rulings (template). What we deliver while open: D-046; Q-18 (`docs/CHALLENGE.md` §4) |
| **Quality score / Top 5 / top 10** | Suva's summary-quality axis: "Top 5" June 2026 summaries (deck), or "your top 10 highly relevant summaries" (template). What we summarise while open: D-047; Q-17 (`docs/CHALLENGE.md` §4) |
| **Must-hit subset** | **(single definition; other files point here)** the rulings of a labelled quarter that Suva summarised: 22 in Q4/2025 and 10 in Q1/2026 (`docs/EVAL.md` §2). The template says summarised rulings "should also be correctly identified by the prototype"; while Q-20 is open, our triage must find every one of them, and their recall is reported apart. The 23 Q3/2025 exports are in no labelled quarter: they are a population check (T30), not a must-hit. The rulings behind Suva's June 2026 summaries (D-047) are the Q2 analogue: not measurable, but the reason they must rank high |
| **Closed-world negatives** | the assumption that every Federal Court ruling of a labelled quarter that is not in Suva's list is not relevant. Suva's list holds positives only, so negatives exist only under this assumption (Q-04). The quarter is cut by decision date, with the publication-date reading also reported, while D-050 is open (`docs/SUVA_DATA.md` §5) |
| **Hard negative** | a ruling of a labelled quarter in accident, disability or military insurance (from its `Gegenstand`) that Suva did not keep: 104 in Q4/2025, 131 in Q1/2026 (`docs/DATA.md` §6). The other negatives are **easy**. The threshold is placed among the hard ones (`docs/EVAL.md` §2) |
| **Smoke set** | the 33 rulings of the team's gateway test, run end to end before any long run; never a calibration or a result (`docs/EVAL.md` §3b, dataset DS7) |
| **DS1-DS8** | the datasets the team's agents build, each with its expected counts (`docs/DATA.md` §10, the single home of the list) |
| **Hold-out** | Suva's hidden material used to score us: the relevant Q2/2026 rulings and human summaries not given to teams. Our **internal** hold-out is different: 23 summary exports kept out of the prompts to test our summaries, the 10 Q1/2026 exports plus the 13 German-language Q4/2025 exports, so that both styles are tested (working assumption, `docs/SUVA_DATA.md` §5) |
| **Rule-statement style / narrative style** | Suva's two house styles in its 55 examples. Rule-statement: the legal rule stated directly, almost never with a consideration reference. Narrative: the facts, the rule the Court recalled with its `E.` / `consid.` reference, the application, the outcome (`docs/SUVA_DATA.md` §3; which one experts expect: Q-30) |
| **F2** | F-score weighting recall four times as much as precision: 5·P·R / (4·P + R) |
| **κ (kappa)** | agreement between two annotators corrected for chance |
| **REPLAY / LIVE** | an answer served from the recorded cache / obtained from the gateway now |
| **AIMD** | additive-increase, multiplicative-decrease: how the rate limiter adapts |
| **RRF** | reciprocal rank fusion of several search result lists |
| **Keera** | the event's inference gateway for Apertus (`docs/EVENT.md` §4). The template says "CSCS / Keera Gateway" (`challenge_description.md`), so the judges' endpoint may be a CSCS one (D-032, Q-23) |
| **sprintd** | the event's platform for registration and submission |
| **Template** | the organisers' public GitHub template `HackApertus/zurich-suva`, from which our repo was created; its files are never renamed or moved (imposed, D-039) and never deleted (our rule, D-044); list in `docs/STATE.md` §1, rules in `docs/EVENT.md` §3 |
| **`judgements/`** | the template folder with Suva's relevance list (xlsx) and 55 summary exports; public, never edited (our rule, D-040); content in `docs/SUVA_DATA.md` |
| **`technical_report.md`, `<TeamName>_Report.pdf`** | the template's report file, and its PDF committed at the repo root (max 6 pages without references; D-039, D-043). The template writes `TeamName_Report.pdf`: `TeamName` is a placeholder for our registered team name, without spaces (Q-22; recorded in `docs/STATE.md` §1) |
| **Demo field** | the line at the top of `technical_report.md` that holds the video link |
| **Target architecture** | the report's mandatory section: a) on-premise, b) air-gapped, c) sovereign Swiss cloud; external dependencies, build time apart from runtime |
| **`data/derived/`** | git-ignored folder for artefacts derived from `judgements/` (labels per docket, digests, prompts, replay caches, fixtures) while D-031 is open; `make run` reads it when present and regenerates it otherwise |
| **HF** | Hugging Face, which hosts the `voilaj/swiss-caselaw` dataset |
| **AZA, CLIR** | bger.ch's applications for rulings and for leading cases (BGE) |
| **CopA** | Swiss Copyright Act (art. 5: court rulings are not protected) |
| **D-0xx, Q-xx** | entries of `docs/DECISIONS.md` |
| **G1-G15, E1-E6, S0-S10** | golden rules (`AGENTS.md` §3), event rules (`docs/EVENT.md` §2), pipeline stages (`docs/ARCHITECTURE.md`) |

## Institutions and sources

| DE | FR | IT | Notes |
|---|---|---|---|
| Suva (Schweizerische Unfallversicherungsanstalt) | CNA (Caisse nationale suisse d'assurance en cas d'accidents) | INSAI (Istituto nazionale svizzero di assicurazione contro gli infortuni) | all three names mark Suva as a party |
| Bundesgericht (BGer) | Tribunal fédéral (TF) | Tribunale federale (TF) | |
| BGE (Leitentscheid) | ATF | DTF | official reports; part V = social insurance |
| Urteil | arrêt | sentenza | "judgement" in the deck = a ruling |
| Liste der Neuheiten / Neue Entscheide | liste des nouveautés | lista delle novità ⚠ | daily list of published rulings |
| zur Publikation vorgesehen | destiné à publication | destinata alla pubblicazione ⚠ | the star `*` |
| Fünferbesetzung | composition à cinq juges | composizione a cinque giudici | |
| Besetzung | composition | composizione | bench block of a ruling |
| Verfahrensbeteiligte | participants à la procédure | partecipanti al procedimento | parties block |
| Sachgebiet | domaine juridique / matière | materia ⚠ | column of the Neuheiten list |
| Gegenstand | objet | oggetto | |
| Erwägung (E.) | considérant (consid.) | considerando (consid.) | rendered in the summary's language: `E. 5.1` / `consid. 5.1` |
| Absatz (Abs.) | alinéa (al.) | capoverso (cpv.) | `Art. 20 Abs. 2ter UVG` / `art. 20 al. 2ter LAA` (D-037) |
| Buchstabe (Bst.; also lit.) | lettre (let.) | lettera (lett.) | Suva's German examples use both `Bst.` and `lit.` (`docs/SUVA_DATA.md` §3) |
| Dispositiv | dispositif | dispositivo | |
| Regeste | regeste | regesto | BGE headnote |

## Insurance branches and acts

| DE | FR | IT | Abbreviations DE / FR / IT |
|---|---|---|---|
| Unfallversicherung (UV) | assurance-accidents (AA) | assicurazione contro gli infortuni (AINF) | UVG / LAA / LAINF; UVV / OLAA / OAINF |
| Militärversicherung (MV) | assurance militaire (AM) | assicurazione militare (AM) | MVG / LAM / LAM |
| Invalidenversicherung (IV) | assurance-invalidité (AI) | assicurazione per l'invalidità (AI) | IVG / LAI / LAI; IVV / RAI / OAI |
| Krankenversicherung | assurance-maladie | assicurazione malattie | KVG / LAMal / LAMal |
| Berufliche Vorsorge | prévoyance professionnelle | previdenza professionale | BVG / LPP / LPP |
| Allgemeiner Teil des Sozialversicherungsrechts | partie générale du droit des assurances sociales | parte generale del diritto delle assicurazioni sociali | ATSG / LPGA / LPGA |
| Versicherungsvertrag (private Versicherung) | contrat d'assurance (assurance privée) | contratto d'assicurazione (assicurazione privata) | VVG / LCA / LCA |
| Bundesgerichtsgesetz | loi sur le Tribunal fédéral | legge sul Tribunale federale | BGG / LTF / LTF |
| Europäische Menschenrechtskonvention | Convention européenne des droits de l'homme | Convenzione europea dei diritti dell'uomo | EMRK / CEDH / CEDU |

## Core accident-insurance themes (example rule SR7 lexicon)

| DE | FR | IT |
|---|---|---|
| Unfallbegriff | notion d'accident | nozione d'infortunio |
| Kausalzusammenhang (natürlicher, adäquater) | lien de causalité (naturelle, adéquate) | nesso causale (naturale, adeguato) |
| unfallähnliche Körperschädigung / Listenverletzung | lésion corporelle assimilée à un accident | lesione corporale parificabile ai postumi d'infortunio ⚠ |
| Rückfall / Spätfolgen | rechute / séquelles tardives | ricaduta / postumi tardivi |
| Invalidenrente | rente d'invalidité | rendita d'invalidità |
| Invaliditätsgrad | taux d'invalidité | grado d'invalidità |
| Integritätsentschädigung (IE) | indemnité pour atteinte à l'intégrité (IPAI) | indennità per menomazione dell'integrità (IMI) |
| Valideneinkommen | revenu sans invalidité | reddito senza invalidità |
| Invalideneinkommen | revenu d'invalide | reddito da invalido |
| Taggeld | indemnité journalière | indennità giornaliera |
| Heilbehandlung | traitement médical | cura medica |
| Gutachten | expertise | perizia |
| Referenzalter | âge de référence | età di riferimento |
| Leistungskürzung | réduction des prestations | riduzione delle prestazioni |
| Regress | recours (de l'assureur) | regresso |

## Outcomes (operative part)

| DE | FR | IT | Class |
|---|---|---|---|
| Die Beschwerde wird gutgeheissen | le recours est admis | il ricorso è accolto | upheld |
| teilweise gutgeheissen | partiellement admis | parzialmente accolto | partly_upheld |
| abgewiesen | rejeté | respinto | dismissed |
| Nichteintreten / nicht eingetreten | irrecevable / n'entre pas en matière | inammissibile / non entra nel merito | inadmissible |
| Rückweisung (zur neuen Entscheidung) | renvoi (pour nouvelle décision) | rinvio (per nuova decisione) | remanded |
| gegenstandslos / abgeschrieben | sans objet / rayé du rôle | privo di oggetto / stralciato | other |
