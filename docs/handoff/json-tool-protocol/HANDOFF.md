# JSON tool protocol for Apertus: handoff

| | |
|---|---|
| Date | 27 Nov 2026 (HackApertus Zurich, day 1) |
| Status | **PROPOSED.** A reference implementation, tested offline and smoke-tested on Keera, then revised after an independent adversarial review (19 findings, all addressed: §14). **Revision 2** (27 Nov, evening): made ready for one repo agent that owns tool calling (role brief, bootstrap prompt, copy map, never-commit list, validation order; §12), then corrected after a second independent cold read (§14.2). Nothing is in the product repository yet; nothing was pushed anywhere. |
| For | the `tool-calling` agent, owner of this work in the repo (an area the lead created on 27 Nov; its brief is `reference/docs/agents/tool-calling.md`, its start-up prompt `BOOTSTRAP.md`); the owners it works with: `platform` (client, probe, `src/schemas.py`), `eval` (method, `make claims`), `triage` and `summarise` (usage), `lead` (decisions, `NOTICE`) |
| Folder | `handoff/json-tool-protocol/` (inventory in §13) |
| Rules followed | `AGENTS.md` G1 to G15; no secret, no Suva text, no team member's name; open questions are described, never decided (§11) |

---

## Résumé en français

**Ce que c'est.** Une méthode pour faire « proposer » à Apertus une action ou un formulaire typé, en
un seul objet JSON, que le code valide puis accepte, répare une fois ou rejette. Apertus propose, le
code valide et décide. La méthode vient du projet ArchAI (HackApertus 2026) ; d'autres équipes ont
écrit indépendamment le même schéma (AlpenRecht, b2bern, Connect-Bern, apertus-qa…).

**Pourquoi chez nous.** Sur Keera, le `json_schema` strict fonctionne (K2) : les ids proposés
deviennent une énumération, donc le modèle ne peut pas citer une considération qu'on n'a pas
offerte. Le JSON est aussi portable vers le point d'accès des juges (`json_schema`, puis
`json_object`, puis le prompt), se rejoue octet pour octet, et laisse le score hors du protocole.
Le smoke ne départage pas natif et JSON pour une décision unique : avec un `tool_choice` nommé, le
70B fait 9 sur 9, comme en JSON strict. En mode `auto` il a répondu en texte au lieu d'appeler
l'outil, mais ses 9 réponses étaient justes ; notre prompt ne nommait pas l'outil (corrigé). Le
natif reste limité à un appel par tour (0 sur 6 cas à plusieurs appels). Ce smoke tournait sur le
jeu de smoke DS7 : EVAL §3b interdit d'en tirer une mesure ou un choix, il prouve seulement que le
banc marche.

**Ce qui est livré.**
- Un module de référence `llm.tool_protocol` (parseur tolérant, ids fermés à résolution exacte,
  schémas au profil strict de Keera, validation, un tour de réparation, échec fermé, boucle bornée).
  Il valide aussi les schémas générés par pydantic (`$ref`, `Optional`) et refuse tout mot-clé de
  schéma qu'il n'applique pas. 263 tests hors ligne verts, 95 % de couverture, ruff propre.
- Un banc reproductible natif contre JSON (DE/FR/IT, 8B/70B, 4 configurations, comparaison au
  premier essai, intervalles de Wilson, bootstrap apparié par cas, seuils pré-enregistrés jugés sur la
  pire répétition, règle de décision calculée, rejeu hors ligne, non-régression à cas identiques).
- Une stratégie de tests de niveau entreprise (§8), des tests live, les textes prêts à coller dans
  `DECISIONS.md`, `LESSONS.md`, `NOTICE` et le rapport (§10), un plan pas à pas pour les agents (§12).

**Crédits.** Le code adapté d'ArchAI (licence MIT, « The ArchAI contributors ») porte la notice
dans chaque fichier (six fichiers) et dans `NOTICE.fragment`. Onze autres projets sont crédités pour
leurs idées ou leurs constats, sans code copié. Toutes les licences lues sont compatibles avec
Apache-2.0.

**Ce qui reste ouvert (non tranché ici).** Le score n'est pas produit par ce protocole, quelle que
soit la réponse à D-021 point 4. La rédaction de l'explication (D-021 point 6), le choix des arrêts
qui reçoivent une justification (aucune entrée ne le tranche encore ; coût mesuré dans D-022), le
rôle du 8B (D-022), les listes d'objets imbriquées (K12) et trois changements proposés (§6, dont le
remplacement de la validation pydantic) restent des décisions d'équipe. Le banc complet n'a pas
tourné.

**Prêt pour un agent propriétaire (révision 2).** Un seul agent porte désormais ce travail dans le
repo : le propriétaire du tool calling, un domaine créé par le lead le 27 novembre. Son brief de
rôle, au format du kit, est `reference/docs/agents/tool-calling.md` ; il entre dans le repo et y
fait foi. Il fixe le périmètre exact (ce qu'il possède, ce qu'il apporte par PR aux autres
propriétaires, ce qui n'est pas à lui), les fichiers à créer, ce qui ne doit jamais être commité et
l'ordre de validation : tests hors ligne, puis tests rouges puis verts, client, tests live des
contrats, et enfin banc rapide puis complet. `BOOTSTRAP.md` donne la procédure en 3 étapes et le
prompt d'amorçage à coller. Une seconde relecture indépendante, à froid, a trouvé 8 défauts majeurs
et des mineurs, tous corrigés (§14.2) : entre autres, chaque exécution du banc a désormais son propre
sel de cache, le banc ne dépense aucun appel sans `--limit` ou `--all`, les tests live demandent
`RUN_LIVE=1`, et les décisions D-054 à D-058 entrent dès la première PR. Les 6 tests live ont été
relancés sur Keera après ces corrections : 6 sur 6 au premier essai.

**Prochaine étape recommandée.** Décompresser ce dossier dans `tmp/` du clone de suva-NGA, puis
coller le prompt de `BOOTSTRAP.md` dans une session de code à la racine du repo. L'agent ouvre
d'abord une PR de documentation, puis une PR par étape ; le banc complet (environ 25 min,
1 880 appels) attend un créneau annoncé et un échantillon public tiré sans les labels de la Suva
(§9.4).

---

## 1. Context

### 1.1 What the method is

The model never acts. It writes **one JSON object** that proposes something:

* a **form** to fill (the pipeline's case): `{"a_evidence": ["c3", "c7"], "b_key_statement": "…", "c_label": "relevant"}`;
* or a **list of tool calls** (a bounded loop, benchmark only): `{"a_calls": [{"a_tool": "get_consideration", "b_args": {"a_id": "c7"}}]}`.

Code then parses the reply tolerantly, validates its shape, resolves every id **exactly** against a
closed list it built itself, runs grounding checks, and either accepts the proposal, sends **one**
repair turn listing what was wrong, or fails closed. The gateway's native `tools` API is not used.

### 1.2 Where it comes from

ArchAI (HackApertus 2026, Swiss archival records) built it after its native tool calls on Keera
underperformed: the agent's replies became `{"calls": [...]}` with the tool schemas in the prompt,
plus argument repair and a deterministic "not done yet" round (`upstream/archai/agent.py`,
`run_record_v4`). Other teams wrote the same idea independently, with variations worth keeping: a
JSON step protocol with one repair round (Connect-Bern), schema validation and a name allow-list
(b2bern), choose-a-label-not-a-position (AlpenRecht), an explicit refusal action (apertus-qa),
placeholder examples (gemeindesim). The audit's fiches sometimes label these as "reuse of ArchAI's
protocol"; that is imprecise: they are independent implementations of one pattern (and CORA is an
MCP server for external agents, not Apertus tool calling).

### 1.3 What the gateway does (measured unless marked)

Sources named `RAPPORT_TESTS_KEERA.md` or "Keera test report" (the team's gateway test of 27 Nov) and
`audit/…` (the team's audit of past projects) are preparation files outside the repository. The
facts they support are restated in this table, so the repo agent does not need them.

| Fact | Source | Consequence for the protocol |
|---|---|---|
| `json_schema` strict works when every object has `additionalProperties: false`: 12/12 probes, 33/33 whole rulings per model | `LESSONS.md` K2 | STRICT is the default tier |
| Under strict mode keys come out in **alphabetical order** | K3 | fields prefixed `a_`, `b_`, `c_`; the lint fails any other order |
| `top_logprobs` works only on `/chat/completions`; under strict JSON key names are tokenised character by character | K5 | the score is a separate one-token call, outside JSON; never a field of a form |
| Two `system` messages return HTTP 400 | K11 | one system message |
| A replayed `assistant` turn was accepted on Keera, but at least 7 other projects saw replayed assistant turns refused by their endpoint's template | `RAPPORT_TESTS_KEERA.md` (27 Nov); audit T1a #13, reported | the repair turn replays the reply as `assistant`; on `RequestRejected("message_roles")` it re-sends the repair as one `user` message that quotes the reply inside data tags |
| The 70B-thinking variant writes reasoning inside `content` between `<|inner_prefix|>` and `<|inner_suffix|>` | K11 | the parser strips it |
| The 70B is not deterministic at T = 0; the 8B is | K10 | tests never compare outputs string for string; prompts are byte-stable so replay works |
| A prefix cache is active (`cached_tokens`) | K14 | the format block is identical for every call of a tool: put stable text first, the ruling after |
| Native tools make one call per turn | K4 (reported by other teams; seen again in our smoke, §9.5, which did not send `parallel_tool_calls`) | parallel calls need the JSON loop |
| `json_schema` strict on another gateway (CSCS) gave 11 valid replies of 24 from the 8B: endless whitespace until `max_tokens` | gemeindesim (`audit/deep/gemeindesim.md`), reported; the judges may run us on CSCS (D-032) | after a `length` stop under STRICT whose tail is whitespace, `propose` retries once at OBJECT (not counted as a repair); the probe tests strict mode on the judges' endpoint (§5.3) |
| The 8B used the "E. x" format in 15 of 33 replies; 11 of its 100 cited numbers did not exist. The 70B cited 78 numbers, all existing | Keera test report, 27 Nov | ids are chosen from a list and resolved exactly; court numbers are accepted only as exact aliases |
| `-thinking` variants refuse `tool_choice` (HTTP 400 "requires --tool-call-parser") | mutz, reported | another reason not to depend on native tools |
| Native parsers leaked `<|tools_prefix|>` into text (8B), lost `tool_call_id` (template), failed parallel tools 11/11 | rosetta-flow, apertus-fracture, gemeindesim, reported | the parser strips template tokens; nothing relies on native parsing |

### 1.4 What ArchAI's benchmark showed, read honestly

ArchAI ran 64 single-turn cases (seed 5; simple 26, parallel 16, parallel_multiple 12, irrelevance
10; German 23, French 16, English 25), exact match of the call multiset (BFCL "AST" style):

| Model / format | Exact overall | Simple | Parallel | Parallel multiple | Irrelevance | Single-call (simple + irrelevance) |
|---|---|---|---|---|---|---|
| 70B / JSON | **0.812** | 1.000 | 0.438 | 0.750 | 1.0 | 36/36 |
| 70B / native | 0.500 | 0.846 | 0.0 | 0.0 | 1.0 | 32/36 |
| 8B / native | 0.562 | 1.000 | 0.0 | 0.0 | 1.0 | 36/36 |
| 8B / JSON | 0.594 | 0.923 | 0.562 | 0.0 | 0.5 | 29/36 |

What it says: JSON's advantage is **multi-call** (native never made two calls in one turn). For a
**single decision**, which is all our pipeline needs, native and JSON were indistinguishable for the
70B at that sample size, and native was better for the 8B (irrelevance 1.0 vs 0.5). The 70B JSON
French score (0.56) comes from 16 cases and its misses are all multi-call; every French single-call
case was right. So ArchAI's numbers alone do **not** justify JSON for us. Our reasons are below,
and our own benchmark (§9) measures the single-decision case directly.

### 1.5 Why JSON for this pipeline, and what would change it

1. **Strict decoding with per-call enums.** The considerations offered (`c1` … `cN`) become an enum
   in the `json_schema`: under STRICT the model cannot emit an id we did not offer. Native tools on
   vLLM constrain arguments only with a named `tool_choice`.
2. **The score stays a plain chat call** (K5), and the justification is a second, optional call
   (D-021 point 6). Nothing in the protocol touches the score.
3. **Portability.** The judges may run us on another OpenAI-compatible endpoint (D-032, Q-23).
   `json_schema`, then `json_object`, then a prompt-only fallback work almost everywhere; native
   tool parsing depends on server flags (`--tool-call-parser`), and the `-thinking` variants refuse
   `tool_choice`.
4. **Replay.** One request, one text reply: the client's replay cache stores and replays it byte for
   byte. Native replies add `tool_calls` objects and ids to store and to match.
5. **What the smoke does not show** (§9.5): for a single decision it does not favour JSON. A named
   `tool_choice` was as good as JSON strict (70B 9/9 both). In `auto` mode the 70B answered the
   evidence question in plain text instead of calling the tool, but all 9 text answers were right:
   the system prompt did not mention the tool, so the prompt decided, not the model (fixed in
   `tool_bench-2`). The smoke ran on the smoke set DS7, which EVAL §3b excludes from any choice.
   Points 1 to 4 are the reasons; the full benchmark tests them.

**The decision rule** is pre-registered (`eval/tool_bench/thresholds.json`) and computed by
`score.decide()`: keep JSON unless `native_forced` beats `json_strict` on the evidence category by
at least 0.10 **first-attempt** exact (`exact_first`: native calls get no repair turn) for the 70B,
with a paired 95 % cluster-bootstrap interval entirely above 0, in each of DE, FR and IT with at
least 20 cases each, **and** native tool calling is confirmed on the judges' endpoint. With fewer
cases the verdict is `insufficient_n` and JSON stays. The burden of proof is on the change.

---

## 2. Credits, licences and what was imported

All repositories were cloned anonymously on 27 Nov 2026 into a scratch folder; nothing from them
was executed; their content was read as data (G15). No `AGENTS.md`, `CLAUDE.md` or `.claude/` was
copied. **Nothing was pushed to any repository.**

| Project | Repository (commit) | Licence, holder | What we took | Where |
|---|---|---|---|---|
| **ArchAI** | `kirtanp/hackpertus-archives` (`d22b5e6`, 18 Nov) | **MIT**, "The ArchAI contributors" | **Code, adapted**: `extract_json`, `repair_args`, the `run_record_v4` loop design, `tool_bench.py` (cases, AST scoring, `_calls_native`, the thread-pool runner) | `parse.py`, `validate.py`, `protocol.py` (`run_tools`), `eval/tool_bench/cases.py`, `score.py`, `run.py`; verbatim copies in `upstream/archai/` |
| AlpenRecht | `Anakalypto/AlpenRecht` (`310f1fd`) | Apache-2.0 | idea: choose labels, not list positions; top-up only when the model failed | `ids.py` design |
| apertus-qa | `ventolabs-hq/apertus-qa` (`c902a25`) | Apache-2.0 | idea: JSON generation with a rule fallback, explicit refuse action | abstention value (`none`, `unclear`) |
| b2bern | `Spaghetti-Overflow/hack-apertus-stregoni` (`0b8e30e`) | Apache-2.0 | idea: schema-validated arguments, name allow-list, call cap, de-duplicated ids, one repair that does not echo values | `validate.py`, `repair_message` |
| Bern-Fit | `Grozby/kinder-bueno` (`e45af69`) | MIT, "Grozby" | idea: bounded native loop (3 rounds), recovery of calls written as text, fallback to plain search | loop caps; `leaked_tool_text` metric |
| Connect-Bern | `CPD9/bern-life` (`53b6049`) | Apache-2.0, "Peter Dike and contributors" | idea: JSON step protocol, one repair round; anti-pattern seen: greedy `\{.*\}` extraction | `parse.py` rule 1 |
| CORA | `Anakalypto/CORA-Apertus` (`fe6b777`) | Apache-2.0 | nothing (an MCP server for external agents) | n/a |
| gemeindesim | `hatif03/gemeindesim` (`8a7b606`) | Apache-2.0 | measurement: placeholder example 49/49 valid, a filled example copied 53 %; report: strict mode on CSCS 11/24 (whitespace runaway); idea: drop an unclosed reasoning span (`strip_reasoning_spans`), mirrored by `parse.py` `_INNER` (rewritten, same rule) | `placeholder_example`, `parse.py`, the whitespace-runaway step |
| mutz | `beSaif/mutz` (`e125edf`) | MIT, "beSaif and Jumainah Khan" | report: `-thinking` refuses `tool_choice` | §1.3 |
| rosetta-flow | `anesask/rosetta-flow` (`537b8d7`) | Apache-2.0 | report: the 8B leaks `<|tools_prefix|>` in text; idea: nonce-fenced data markers | `parse.py` strips template tokens; `delimit()` |
| apertus-fracture | `RishiksaiP/BEA-16B` (not read: private or absent) | per the audit index: Apache-2.0 (code), CDLA-Permissive-2.0 (evidence), CC-BY-4.0 (report) | report only: the Apertus 1.5 template drops `tool_call_id`; parallel tool results lose their identity | §1.3 |
| guptachetan1995/apertus | (`88eb265`) | Apache-2.0, "Chetan Gupta" | idea: one `invoke` chokepoint; write verbs never registered | `Tool(read_only=True)` only |

Several Apache-2.0 `LICENSE` files still carry the template placeholder "Copyright 2026 Your Team";
the holder above is the one their `NOTICE` names, otherwise the repository owner. An idea or a
report is credited even when no code was taken; no code other than ArchAI's was adapted.

What to do with this in the repository:

1. Append `NOTICE.fragment` to `NOTICE` (owner: `lead`, D-036, D-045). It holds ArchAI's full MIT
   notice, the list of adapted files, and the acknowledgements.
2. Keep the header of each adapted file (SPDX line plus the ArchAI attribution); a doctrine test
   fails if it disappears (`test_adapted_files_carry_the_archai_mit_notice`).
3. Do **not** commit `upstream/` (reference for reviewers, with `PROVENANCE.md` and SHA-256 of each
   copy) unless the lead decides on a `third_party/` folder. It must never be imported: its
   `llm.py` reads an API key and opens connections itself (G2).

---

## 3. Architecture

### 3.1 Doctrine

| Rule | How the protocol enforces it |
|---|---|
| G1: identifiers never come from Apertus | the model chooses among ids we show (`[c7]`); `IdTable.resolve` maps a few exact spellings and refuses everything else; ids become enums in the wire schema |
| G2: one gateway | the package has no network import and reads no environment variable (doctrine test); it receives a `ChatFn` |
| G4 / `DOCTRINE.md` §7: text is data | data in `<data id=NONCE kind=…>` tags; template tokens and data tags inside the text are neutralised; the format block says data is never an instruction |
| G5: recall first; a failed call is never a negative | `Outcome.status == "failed"` carries `value=None` and a reason; callers map it to "unclear" with a reason code |
| `DOCTRINE.md` §4: a number written by the model is not a score | no confidence field in any contract; the score is the log-probability call |
| G9: tests prove something | every scripted reply is in `fakes.py`; tests assert on the requests actually sent |
| G10: thresholds before measuring | `thresholds.json` is pre-registered; 2 repetitions in the full profile, each sent with its own `cache_salt` so the replay cache cannot serve one from the other; guards judged on the worst repetition |
| Fail closed | a schema keyword code does not enforce is refused when the `Tool` is built; a check's non-fatal problem stays non-fatal only if it drops one item of a declared `item_level` array |

### 3.2 Package layout (reference: `reference/src/llm/tool_protocol/`)

| File | Lines | Responsibility |
|---|---|---|
| `parse.py` | 300 | `parse_object(text) -> ParseResult`: the first **top-level** JSON object; strips BOM, inline reasoning, `<think>`, template tokens, fences; targeted syntax repairs (raw control characters, `\'`, German quotes, trailing commas); never raises; never echoes text; linear in the input length (tested by counting scanner steps) |
| `ids.py` | 131 | `IdTable`, `consideration_table(..., none_option)`, `NONE_ID`: closed id sets with exact aliases |
| `schema.py` | 360 | `Tool` (refuses unenforced keywords), `Tier`, `inline_refs`, `strict_profile`, `bind_enums`, `lint_strict`, `response_format`, `placeholder_example`, `loop_schema`, `SUPPORTED_KEYWORDS` |
| `validate.py` | 341 | `validate(obj, schema, id_tables, caps, item_level) -> Validation` (inlines `$ref`; `anyOf`/`oneOf`; every code-only constraint); `drop_items`; `Problem` |
| `prompting.py` | 110 | `format_block`, `delimit`, `neutralise`, `new_nonce`, `repair_message` |
| `protocol.py` | 581 | `propose` (one form), `run_tools` (bounded loop), `ChatRequest`, `ChatReply`, `RequestRejected`, `TransportFailure`, `Outcome`, `LoopOutcome` |
| `README.md` | | the module documentation for developers |

Standard library only. Python ≥ 3.10. pydantic is optional: a `Tool` accepts
`Model.model_json_schema()`; `$ref` targets are inlined for the wire **and** for validation, and
`Optional` fields (`anyOf` with `null`) are checked branch by branch. Tested through
`propose(tier=OBJECT)` with nested models and `Optional` fields (`test_hardening.py`), where the code
is the only guard. This replaces pydantic as the validator (§6, change 3).

### 3.3 Data flow of `propose`

```
 Tool(name, description, parameters with caps)            src/schemas.py (platform)
   │ (refused at construction if it uses a keyword code does not enforce)
   │ inline_refs → strict_profile → bind_enums(offered ids) → lint_strict (raises on E:)
   ▼
 ChatRequest(messages=[system + format block, user with <data> tags], response_format(tier), max_tokens)
   │                                      ▲
   ▼                                      │ cascade STRICT → OBJECT → PROMPT on RequestRejected("response_format")
 client (src/llm/client.py) ── gateway ───┘ (does not count as an attempt)
   │
   ▼ ChatReply(content, finish_reason, served_model)
 finish_reason == "length"? ── yes ──► never parsed; STRICT with a whitespace tail: step to OBJECT once;
   │                                     otherwise budget × 2 once; else failed("truncated")
   │ no
 parse_object ──► validate (shape, exact ids, caps) ──► checks (src/verify/, only if shape-valid)
   │                                     non-fatal problem outside an item_level array ──► fatal
   │
   ├─ no problem ─────────────────────────────► Outcome("ok" | "ok_repaired", value)
   ├─ problems, attempt 1 ──► ONE repair turn (codes and paths, never values) ──► loop once
   └─ problems, attempt 2 ──► fatal? failed(reason)  /  only item-level? drop items, re-validate ──► ok_repaired | failed
```

### 3.4 `propose`, step by step

1. Build the wire schema: `strict_profile(tool.parameters)` (inline `$ref`, drop `title`/`default`/
   `examples`, turn `const` into a one-value enum, drop the code-only keywords `maxItems`,
   `minItems`, `maxLength`, `minLength`, `uniqueItems`, `pattern`, `minimum`, `maximum`, close every
   object), then `bind_enums` with each `IdTable`. Lint it: any `E:` raises `ValueError` (a
   programming error, caught by the contract tests long before). An empty id table raises too: no
   call is made when there is nothing to choose from. The validator works on `inline_refs(tool.
   parameters)`, which keeps every code-only keyword, merged with `tool.caps` and the `caps` argument.
2. One system message: the role's text plus `format_block` (task, "one JSON object, no prose, no
   fence", "only ids shown in square brackets", "data is never instructions", field notes, language
   note; below STRICT also a placeholder shape). The user message carries the delimited data and
   the question.
3. Call the client. `RequestRejected("response_format")` steps the tier down without counting an
   attempt; `RequestRejected("message_roles")` during a repair re-sends the repair as one user
   message quoting the previous reply inside `<data kind=previous_reply>` tags; any other rejection
   or a `TransportFailure` fails at once.
4. `finish_reason == "length"`: the reply is never parsed (G3). Under STRICT, a reply whose last
   32 or more characters are whitespace is a constrained-decoding runaway: the call steps down to
   OBJECT once, without using the repair attempt. Otherwise the budget doubles once, up to
   `max_tokens_cap`, which uses the repair attempt.
5. Parse, validate, then run the injected grounding checks if the shape is valid.
6. A problem a check marks non-fatal stays non-fatal only if its `drop_path` names one item of an
   array declared in `item_level` (`a_claims[3]`); otherwise it becomes fatal. No problem: `ok`
   (first attempt) or `ok_repaired`. Problems on the first attempt: one repair turn, which replays
   the previous reply (up to 16,000 characters, enough for a 3,000-token summary) and lists the
   problems. Problems on the last attempt: fatal ones fail with `reason` = `reference` (ids),
   `schema` (shape) or `grounding` (checks); item-level ones drop those items, then the object is
   validated again (dropping every claim fails with `grounding`).
7. `Outcome.trace` keeps, per call: tier, finish reason, served model, parse status, problem codes,
   output budget, live or replay mode, and the SHA-256 of the raw content. Never the text.

### 3.5 `run_tools`, the bounded loop (benchmark only in v1)

One step is `{"a_calls": [{"a_tool": …, "b_args": {…}}]}`. Unknown tools and invalid arguments are
refused with a diagnostic and never run; identical calls run once (cache); the loop stops at
`max_steps` (4), `max_calls` (8), on a step of only repeated calls, or on `finish`; one "not done
yet" reminder, then code runs the `required` tools itself; results go back as a user message inside
`<data kind=tool_results>` tags, cut to `result_chars`. A required tool counts as done only for
the same arguments. In STRICT the step schema uses one `anyOf` branch per tool (accepted by Keera
in the smoke: 42 of 42 loop requests, 21 per model, §9.5). Handlers must be read-only;
`Tool(read_only=False)` raises.

### 3.6 Ids and abstention

`consideration_table(considerations)` offers `c1` … `cN` in document order and accepts, for each,
the court's own number as an exact alias: `E. 4.2`, `E.4.2`, `Erw. 4.2`, `consid. 4.2`,
`cons. 4.2`, and the bare `4.2` when it is dotted. A bare `4` is refused (`not_offered`): it is
ambiguous with `c4`. An alias shared by two ids is refused (`ambiguous_id`). There is no edit
distance and no "closest id": `E. 4.21` does not become `E. 4.2`. `none_option=True` adds `none`
(aliases `null`, `keine`, `aucun(e)`, `nessuno/a`) so that abstaining is a valid choice under strict
decoding: a schema without an abstention value makes the model fill the field anyway.

### 3.7 Prompt construction

* Exactly one system message (K11), stable per tool and tier so the prefix cache works (K14); the
  ruling goes in the user message, after the stable part.
* Data blocks: `delimit(kind, text, new_nonce(text))`. The nonce is derived from the text, so the
  same input gives the same prompt (replay, D-032); inside the text, `<|token|>` becomes `<¦token¦>`
  and `<data …>` becomes `‹data …›`. `src/verify/` compares quotes against the text **as sent**.
* Descriptions say what a field is for, never with a filled-in example; below STRICT the shape is
  shown with placeholders (`"<one of: relevant | not_relevant | unclear>"`).
* The repair turn lists `path: code (message)` lines, at most 12, never a value and never source
  text. b2bern's repair also leaves input values out (it replays the faulty output, as we do); the
  reason is the copying effect measured for filled examples (gemeindesim, 53 %).

### 3.8 Failure model

| Situation | Behaviour | `Outcome` |
|---|---|---|
| `json_schema` refused by the endpoint | step down to `json_object`, then prompt-only | tier recorded; not an attempt |
| HTTP 400 on the replayed assistant turn | re-send the repair as one user message | |
| Transport failure after the client's retries | stop | `failed`, `transport` |
| Reply cut by `max_tokens` | not parsed; budget × 2 once | `failed`, `truncated` if cut again |
| Strict reply that ends in whitespace at `max_tokens` (runaway) | not parsed; step to OBJECT once, not counted | tier `json_object` recorded; `cascade: whitespace_runaway` in the trace |
| No JSON, broken JSON, several objects in a list | one repair turn | `failed`, `no_object` / `invalid_json` |
| Unknown or missing key, wrong type, value outside an enum, a value matching no `anyOf` branch, too many or too few items, too long or too short, pattern, bounds | one repair turn (near-identical key names repaired silently and logged) | `failed`, `schema` |
| An id that was not offered | one repair turn | `failed`, `reference` |
| A quote not in the cited consideration (check) | one repair turn | `failed`, `grounding` |
| One unsupported claim of a summary | repair turn, then that claim is dropped and counted | `ok_repaired`, `dropped=("a_claims[3]",)` |
| A check returns a non-fatal problem without a valid item path | treated as fatal | `failed`, `grounding` |
| A contract uses `format`, `allOf`, `not`, tuple `items` or a schema-valued `additionalProperties` | `Tool(...)` raises `ValueError` when the contract is defined | programming error, never a model call |

### 3.9 Where it sits in the pipeline

| Stage (`ARCHITECTURE.md`) | Use | Contract |
|---|---|---|
| S3 judgement | **score**: **not this protocol**, whatever D-021 point 4 decides; **justification** (key statement, supporting considerations), for the rulings the team chooses (§11) | `justify_relevance` |
| Signals | "where does the ruling state X?" with a verbatim quote that code checks; the signal fires only if the check passes ("Apertus tags, code decides") | `tag_signal` (flat, one signal per call) |
| S6 summaries | claims citing considerations; S7 verifies each claim; an unsupported claim is dropped and counted | `summary_claims` |
| S7 verify | provides the `checks` the protocol runs (`src/verify/`) | |
| Search (only if D-033 builds it) | optional query rewriting into a closed set of fields | to design then |

---

## 4. Usage, stage by stage

### 4.1 Triage: score first, justification second

```python
# 1) The score: NOT the protocol, whatever form D-021 point 4 settles on
#    (the gateway test used a one-token log-probability call outside JSON, K5).
score = scorer.score(ruling)

# 2) The justification: the protocol, for the rulings the team chooses to justify (§11).
cons = ruling["considerations"]
data = "\n".join(f"[{c['id']}] E. {c['e_number']}: {c['text']}" for c in cons)
out = propose(
    client.chat_fn(LLM_NAME), JUSTIFY,
    system=prompts.TRIAGE_SYSTEM,
    user=delimit("ruling", data, new_nonce(data)) + "\n\n" + prompts.TRIAGE_QUESTION,
    purpose="triage_justify", prompt_version=prompts.TRIAGE_VERSION,
    tier=Tier(probe.json_tier),
    id_tables={"a_evidence[]": consideration_table(cons)},
    field_notes={"a_evidence": "up to 3 ids of the considerations that decide it",
                 "b_key_statement": "the holding, one or two sentences",
                 "c_label": "your reading; it is not the score"},
    language_note="Write b_key_statement in the language of the ruling.",
    max_tokens=400,
)
```

Store `out.value`, `out.status`, `out.repairs`, `out.trace` with the ruling. On `failed`, store the
reason and show "justification unavailable" in the UI: the ruling keeps its score and its rank.

### 4.2 Signal tagging

```python
out = propose(chat, TAG_SIGNAL, system=prompts.SIGNAL_SYSTEM,
              user=delimit("ruling", data, new_nonce(data)) + "\n\nFact asked: " + signal.question,
              purpose=f"signal_{signal.code}", prompt_version=prompts.SIGNAL_VERSION,
              id_tables={"a_consideration": consideration_table(cons, none_option=True)},
              checks=[verify.quote_in_cited, verify.value_in_quote], context=ruling)
fired = out.ok and out.value["a_consideration"] != NONE_ID
```

The signal fires only when the quote was found verbatim (after normalisation) in the cited
consideration and the value was copied from the quote. `tests/tool_protocol/checks_example.py`
shows the check's shape; the real one lives in `src/verify/` (owner: the verifier, `AGENTS.md` §5).

### 4.3 Summary claims

```python
out = propose(chat, SUMMARY, system=prompts.SUMMARY_SYSTEM[lang], user=...,
              purpose=f"summary_{lang}", prompt_version=prompts.SUMMARY_VERSION,
              id_tables={"a_claims[].a_cites[]": consideration_table(cons)},
              item_level=["a_claims"], checks=[verify.claim_supported], context=ruling,
              max_tokens=1500, max_tokens_cap=3000)
```

The summary's prose is then written from the accepted claims (or the claims are the summary,
depending on the summarise brief). `out.dropped` is counted in the run report.

### 4.4 What every caller does

* Count `status`, `reason`, `repairs` and `dropped` per stage; they go into `results/` and into
  the report (G11: every number has a source).
* Never retry `propose` in a loop: it already made its one repair. A transport failure is retried
  by the client, and a stage that ends `failed` leaves the item "to do" or flagged, per D-021 point 7.
* Bump `prompt_version` whenever the system text, a field note, a contract or the format block
  changes: it is part of the replay key.

---

## 5. Integration plan for our repository

### 5.1 Where each piece goes

Since revision 2 one owner carries this work: the `tool-calling` area. The exact copy map, file by
file, is in its brief (`reference/docs/agents/tool-calling.md`, "Files to create in the repo"); this
table is the summary. "Approves" names the owner of a shared file (G7).

| From `reference/` | To the repo | Owner | Approves |
|---|---|---|---|
| `src/llm/tool_protocol/` (package, README) | `src/llm/tool_protocol/` | `tool-calling` | |
| `tests/tool_protocol/contracts.py` | the three `Tool` definitions move to `src/schemas.py` (after §6 is settled) | `tool-calling` | `platform` |
| `tests/tool_protocol/checks_example.py` | stays as a test example; the real checks go in `src/verify/` (verifier's owner) | `tool-calling` | |
| `tests/tool_protocol/*` except `test_client_mapping.py` | `tests/tool_protocol/` (imports of `contracts` then point at `schemas`) | `tool-calling` | |
| `test_doctrine.py` | stays in `tests/tool_protocol/`, beside the kit's `tests/test_doctrines.py` | `tool-calling` | |
| `eval/tool_bench/`, `tests/tool_bench/` | same paths (carved out of the evaluation area) | `tool-calling` | `eval` keeps `docs/EVAL.md` |
| `pyproject.toml` | merged, not copied, as the brief's "Settings to merge" says: **append** the two test paths to `testpaths`, add the `live` marker and `-m 'not live'` to the repo's `addopts`; ruff gets `line-length = 120` or per-file `E501` ignores, plus a separate docstring (`D`) command | `tool-calling` | `platform`, `lead` |
| `NOTICE.fragment` | append to `NOTICE`, in the same PR as the code (G14) | `tool-calling` | `lead` |
| `examples/chatfn_mapping.py` | **not copied**: its mapping and error classification go into `src/llm/client.py` (a file outside `src/llm/` must not call the gateway, G2) | `tool-calling` | `platform` |
| `tests/tool_protocol/test_client_mapping.py` | **not copied**: its assertions move to the client's tests | `tool-calling` | `platform` |
| `docs/agents/tool-calling.md` | `docs/agents/tool-calling.md`, with a row in `AGENTS.md` §5 | `tool-calling` | `lead` |
| `conftest.py`, `upstream/`, `smoke/`, this `HANDOFF.md`, `BOOTSTRAP.md` | not committed (the brief's "Never commit") | | |

### 5.2 What `src/llm/client.py` must provide

* `chat_fn(model) -> ChatFn`: sends `ChatRequest` to `/chat/completions`, adds `model`, thinking off,
  timeouts and streaming, checks the served model (G3), logs every raw output to `llm_calls`, uses
  the replay cache keyed on the full request (messages, `response_format`, `tools`, `tool_choice`,
  `parallel_tool_calls`, `max_tokens`, `purpose`, `prompt_version`, requested model, and
  `cache_salt`, which is the repetition index: the benchmark sends `rep1` for its second
  repetition). `purpose`, `prompt_version` and `cache_salt` are never sent to the gateway. The
  benchmark's default `--chat` is `llm.client:chat_fn`; `test_live.py` uses it too.
* **Replay of repaired calls (amend ARCHITECTURE §4.8).** §4.8 caches "only valid outputs", but
  validity is decided inside `propose`, after the client returned. A repaired call has a first,
  invalid reply that the repair request embeds; if that reply is not cached, the call cannot be
  replayed (D-032). Proposed wording for §4.8: "the replay cache stores **every** reply of an
  allowed model, keyed by its request; the caller's verdict (`Outcome.status`, `reason`) is stored
  beside it in `llm_calls`". Alternative: `propose` reports validity back through a callback. This
  is D-057 (OPEN, §10.2); while it is open the client caches every reply. Measurement runs are not
  affected either way: each run and repetition sends its own `cache_salt`.
* `ChatReply(content, finish_reason, served_model, tool_calls, mode)`, with `mode` set to `LIVE` or
  `REPLAY`: the benchmark and the live tests refuse a reply served from the cache.
* Error classification in one function (G3): HTTP 400/422 become `RequestRejected(kind)` by reading
  the error body (`response_format`: schema or guided decoding refused; `message_roles`: roles or a
  second system message refused; `other`); 408/409/429/5xx/network are retried with back-off and
  `Retry-After`, then `TransportFailure`; 401/403/404 are never retried. Catch `HTTPError` before
  `URLError` (ArchAI retried 400s because `HTTPError` is a subclass of `URLError`).
* `examples/chatfn_mapping.py` is the 100-line reference for the mapping; its tests
  (`test_client_mapping.py`) move to the client's tests.

### 5.3 What `make smoke-llm` and the probe add

* The strongest JSON tier the endpoint accepts, written to `results/gateway_probe.json`
  (`json_tier`), which every `propose` call reads.
* `RUN_LIVE=1 pytest -m live tests/tool_protocol`: each contract once per model, STRICT, synthetic
  ruling, with a salt of its own.
* A list-of-objects schema (K12) and an `anyOf` schema in strict mode.
* Once Q-23 names the judges' endpoint: strict mode on that endpoint with the 8B, 10 calls: count `length` stops whose tail is
  whitespace (the CSCS runaway, §1.3). The protocol handles one; a high rate means the probe should
  record `json_tier = json_object` for that endpoint.
* For information: named `tool_choice` and `parallel_tool_calls` on the endpoint (the decision
  rule's portability condition). Keera accepted `parallel_tool_calls: true` on 27 Nov (one probe
  call per model, 18:40 UTC); both models still made one call for a two-call request.

### 5.4 Make targets (proposed names)

| Target | Runs | When |
|---|---|---|
| `make check` | ruff, `pytest` (offline: unit, contract, golden, property, doctrine, bench offline) | pre-commit and CI, every push |
| `make smoke-llm` | probe plus `RUN_LIVE=1 pytest -m live tests/tool_protocol` | first hour, before the overnight run, before the demo; its concurrency ramp only in an announced slot (the live tests alone may run any time) |
| `make bench-tools PROFILE=quick\|full` | `python -m eval.tool_bench.run … --dry-run`, then the run with `--all` | quick after a protocol change; full once, in an announced slot |

---

## 6. Contracts: proposed shapes and two changes to flag

The three example contracts are in `reference/tests/tool_protocol/contracts.py`; their wire schemas
are pinned in `golden/wire_*.schema.json`. Required values carry code-only minimums (`a_evidence`
at least one id, `b_key_statement` and each claim's `b_text` at least one character). They follow
`ARCHITECTURE.md` §3 with **three proposed changes that their owners decide** (G7: frozen
contracts change by PR only):

1. **`c_label`** uses `relevant | not_relevant | unclear` instead of `A | B`. Reasons: an explicit
   abstention value (a strict schema without one forces a guess), readable logs, and a name that
   cannot be mistaken for the score's one-token label. Option kept open: `A | B | unclear`.
2. **Signals are flat** (one signal per call: `a_consideration`, `b_quote`, `c_value`) instead of a
   list of signal objects, because lists of objects are not in the gateway probe yet (K12). Option
   kept open: a list, once the probe covers K12.
3. **The protocol's validator replaces pydantic as the validator** (architecture change, owner
   `lead` with `platform`). ARCHITECTURE §3 says "one pydantic model per contract generates the JSON
   schema, the prompt examples and the validator", and §4 item 7 says "Pydantic `extra=forbid`".
   Pydantic cannot resolve an id alias against a per-call table, drop one unsupported claim, or
   count repairs, so the protocol validates. Options: (a) pydantic models stay the source of the
   schema (`Tool(parameters=Model.model_json_schema())`, tested) and the protocol validates;
   (b) the same, plus `Model.model_validate(out.value)` as a second check after `propose`;
   (c) hand-written JSON schemas, no pydantic. Recommendation to weigh: (a), or (b) if the team wants
   pydantic objects downstream. Either way, update ARCHITECTURE §3 and §4 item 7 in the same PR.

The summary contract keeps its list of claim objects (`a_claims[]`), which is exactly K12's case:
the live contract test covers it (format only): valid at the first attempt in 3 runs × 2 models on
a synthetic ruling (§9.5).

---

## 7. Pitfalls and how they are handled

| Pitfall | Seen in | Consequence | Our handling | Test that pins it |
|---|---|---|---|---|
| The extractor retries at the next `{` after a broken span | ArchAI `extract_json` | returns an **inner** object of a broken reply as the answer | only top-level candidates; the scan never enters a failed one | `test_nested_object_of_a_broken_reply_is_never_returned`, property `test_nested_trap_never_returns_inner_object` |
| Greedy `\{.*\}` extraction | Connect-Bern | swallows prose between two objects | balanced, string-aware scan | `test_first_top_level_object_wins`, `test_prose_braces_before_the_object_are_skipped` |
| Truncated reply "repaired" by closing brackets | common | a guess presented as the model's answer | `finish_reason == "length"` is never parsed; an unterminated object is `truncated` | `test_length_is_never_parsed_and_budget_doubles_once`, `test_truncated_reply_is_a_failure_not_a_guess` |
| Key repair with difflib cutoff 0.5 and "any unknown key to the lone missing argument" | ArchAI `repair_args` | a value routed into the wrong field | rename only at ratio ≥ 0.85 with exactly one candidate; dropped `a_` prefix restored explicitly; everything logged | `test_key_rename_only_for_near_identical_names` |
| String split on `,` and `;` to make a list | ArchAI `repair_args` | "Art. 6 Abs. 1, UVG" becomes two references | a string becomes a one-item list, never split | `test_scalar_wrapped_but_never_split_on_commas` |
| `null` treated as missing, `true` accepted as integer, input mutated | ArchAI `check_schema` | silent type errors, side effects | explicit types, `bool` is not `int`, deep copy | `test_boolean_is_not_an_integer`, `test_input_object_is_not_mutated` |
| HTTP 400 retried (`HTTPError` ⊂ `URLError`), `Retry-After` ignored, a circuit breaker that never closes | ArchAI `llm.py` | load on a refusing gateway; a stuck run | client rule (§5.2); classification, ordering and back-off tested on the reference mapping | `test_400_classification`, `test_http_error_is_classified_before_the_url_error_branch`, `test_429_is_retried_honouring_retry_after`, `test_auth_and_missing_routes_are_never_retried` |
| Fuzzy id matching | several | a wrong consideration cited with confidence | exact aliases only | `test_no_fuzzy_matching`, property `test_resolution_never_invents` |
| Bare court numbers as ids | our pilot (8B: "E. x" in 15/33) | `4` could mean `c4` or `E. 4` | `4` refused; `E. 4` and dotted `4.2` accepted | `test_unoffered_or_bare_numbers_are_refused` |
| A filled example in the prompt | gemeindesim (53 % copied) | the example's values come back | placeholders only | `test_placeholder_example_holds_no_plausible_value`, doctrine test on descriptions |
| The repair turn echoes values | b2bern | the model copies its own mistake | codes and paths only | `test_repair_turn_and_trace_never_echo_reply_text` |
| Inline reasoning, `<think>`, leaked template tokens | K11, rosetta-flow | JSON hidden in noise, or a reasoning object parsed | stripped before the scan; an unclosed reasoning block means no answer | `test_inline_reasoning_of_70b_thinking_is_removed`, `test_unclosed_inline_reasoning_means_no_answer` |
| Data that closes its own tag or injects a template token | prompt injection | instructions smuggled through a ruling or a tool result | neutralised text, nonce from the text | `test_data_cannot_close_its_tag_or_inject_template_tokens`, `test_tool_results_are_neutralised_before_they_reach_the_model` |
| Random nonces in prompts | common | the replay cache never hits | nonce derived from the text | `test_same_inputs_same_requests_for_propose`, `…_for_the_loop` |
| Empty argument objects in native history | ArchAI | history rejected by the template | the JSON protocol has no native history | n/a |
| Write tools offered to the model | general | the model acts | `Tool(read_only=False)` raises | `test_only_read_only_tools_can_be_registered` |
| Validation that ignores `$ref` and `anyOf` (pydantic schemas) | our first version (review F1) | below STRICT a nested model or an `Optional` field is not checked at all | `$ref` inlined for validation; branches tried one by one; unenforced keywords refused | `test_ref_and_optional_are_validated_not_waved_through`, `test_pydantic_nested_and_optional_through_propose`, `test_tool_refuses_keywords_code_does_not_enforce` |
| Constraints dropped from the wire and not enforced either | our first version (review F4) | `minLength`, `pattern` silently ignored | every code-only keyword enforced; `Tool.caps` read | `test_constraints_dropped_from_the_wire_are_enforced_by_code`, `test_tool_caps_are_read_by_propose` |
| A check's soft problem with no item to drop | our first version (review F8) | an ungrounded value accepted as `ok_repaired` | made fatal unless it names an `item_level` item | `test_non_fatal_check_problem_outside_item_level_is_fatal` |
| Quadratic scans (unclosed `[` rescanned, German-quote repair rescanned) | our first version (review F7) | minutes of CPU on a 200,000-character reply | resume after an unclosed `[` at the next `{`; single-pass quote repair | `test_parser_work_is_linear_on_adversarial_input` (counts steps, not seconds) |
| Strict decoding that emits whitespace until `max_tokens` | gemeindesim on CSCS | every call `truncated` | one step to OBJECT | `test_whitespace_runaway_steps_down_once_without_using_the_repair` |

---

## 8. Test strategy

### 8.1 Principles

* **Offline by default.** Everything except `-m live` and the benchmark runs without a network, in
  seconds, on every push. Scripted gateways are declared in `fakes.py` (G9).
* **Assert on what was sent and stored**, not on a status: the tests read `ScriptedChat.requests`
  (roles, schema, enums, repair text) and the `Outcome` (value, reason, trace).
* **Red before green** (G9): each pitfall of §7 has a test written against the failure mode; the
  PR that ports the module shows them red against a deliberately broken copy (for example
  `parse.py` with ArchAI's retry-at-next-brace) before green.
* **Never compare model outputs string for string** (K10): live checks are schema, ids, verifier.
* **No Suva text, no real ruling text in fixtures**: golden replies and contract tests use
  synthetic text; the benchmark reads public rulings at run time and commits aggregates only (D-031).
* **Thresholds before measurements** (G10), in `thresholds.json`. The review changed *metric
  definitions* (first-attempt comparison, "no call emitted", worst repetition, cluster bootstrap)
  after the smoke and before any full run; no target value changed.
* **Measure work, not time**: complexity tests count scanner steps, so they cannot flake on a slow
  runner.

### 8.2 Suites

| # | Suite | File(s) | Tests | Guarantees | Runs |
|---|---|---|---|---|---|
| 1 | Unit: parser | `test_parse.py` | 31 | one test per rule of `parse.py` and per known failure (fences, reasoning, template tokens, nested trap, truncation, German quotes, `\'`, trailing commas, singleton list, no echo) | `make check` |
| 2 | Unit: ids, schemas, validation, contract snapshots | `test_schema_ids_validate.py` | 50 | id spellings, refusals, ambiguity, no fuzzy; strict profile, lint, pydantic input, enums, tiers, placeholders, tool guards; every validation code and repair; item-level drops; no mutation; each contract's wire schema pinned (a change needs `UPDATE_GOLDEN=1` and a reviewed diff) and lint-clean | `make check` |
| 3 | Unit: prompt pieces and lint branches | `test_prompting_and_lint.py` | 12 | format block per tier, repair cap, delimit, every lint branch, `$ref` refusals, placeholder per type | `make check` |
| 4 | Behaviour of `propose` and `run_tools` | `test_protocol.py` | 19 | one system message, strict enum sent, repair turn shape, fail closed with reason, truncation, cascade without counting attempts, role-refusal fallback, transport failure, hashes not text, grounding repair, abstention, claim drops, loop batching, refusals, caps, reminder then required tools | `make check` |
| 5 | Fail-closed hardening | `test_hardening.py` | 40 | `$ref`, `anyOf`, `oneOf`, `const`, pydantic nested and `Optional` through `propose(OBJECT)`; refused keywords; every code-only constraint; `Tool.caps`; soft check problems made fatal; linear parser (step counts); whitespace runaway; `cache_salt`; long repair replay; `rejected` other; top-level arrays; loop transport, handler errors, finish with calls, required calls by arguments | `make check` |
| 6 | Client contract | `test_client_mapping.py` | 17 | body shape, one system message, thinking off, `parallel_tool_calls`, nothing internal sent; 400/422 classification; `HTTPError` before `URLError`; `Retry-After`; 401/403/404 never retried; network retries; no URL default in code | `make check` (skips without `examples/`) |
| 7 | Golden | `test_golden.py`, `golden/replies.jsonl` | 21 | 20 hand-written replies reproducing reported failure shapes give the same parse status, repairs and verdict (the expected values were recorded from this code and reviewed: they pin behaviour, they are not independent truth) | `make check` |
| 8 | Property and fuzz (hypothesis) | `test_properties.py` | 6 | for **any** input: the parser never raises; a valid object round-trips through any wrapping; parsing is idempotent; a mutated reply never yields an unoffered id; resolution never invents | `make check` (300 examples) |
| 9 | Doctrine and security | `test_doctrine.py` | 34 | no network or environment access; the score path never imports the protocol (files named `score` or asking for `logprobs`, outside `src/llm/`, whose client serves both paths; the check is itself tested); byte-identical requests for identical inputs; for any pair of replies `failed` has no value and `ok` is valid (property); data cannot close its tag; tool results neutralised; no echo in repair or trace; only read-only tools; every public name documented; SPDX headers; the ArchAI MIT notice on all six adapted files | `make check` |
| 10 | Doctest | `test_doctest.py` | 1 | the docstring examples of `parse.py` run with the suite | `make check` |
| 11 | Benchmark, offline | `tests/tool_bench/test_bench.py` | 33 | cases deterministic, content-derived ids, free of non-allowed fields; loader numbers considerations without ids; evidence gold unique; scoring multiset, no id mapping; irrelevance counts any emitted call; text answers recorded, not credited; Wilson; cluster bootstrap invariant to a duplicated run; decision rule per language; non-regression needs identical cases and ignores one flip; worst repetition; distinct cache salts per repetition **and per run**; a live run needs `--limit` or `--all`, `--dry-run` calls nothing, a reply served from the cache makes the run exit 3; a raising job becomes a row; oracle, noisy and garbage gateways; live-then-replay identical | `make check` |
| 12 | Live contracts | `test_live.py` (`-m live` and `RUN_LIVE=1`) | 6 | each contract, each model, STRICT, usable on the real gateway; a salt of its own and no reply from the cache; attempts printed; format only, not content | `make smoke-llm` |
| 13 | Benchmark, live | `eval/tool_bench` | 30 or 135 cases × configs × models × reps | §9 | quick after protocol changes; full once |
| 14 | Mutation (optional) | `mutmut` on `parse.py`, `ids.py`, `validate.py` | | the suites kill at least 80 % of mutants | before the demo freeze, if time allows |

Current totals (27 Nov, reference tree, revision 2): **263 offline tests pass, 1 skipped**
(the score-path test skips until a score module exists; without pydantic installed, 2 more skip:
one in `test_hardening.py`, one in `test_schema_ids_validate.py`). In the repo, without
`test_client_mapping.py`, the two test paths give **246 passed, 1 skipped, 6 deselected**
(simulated port, 27 Nov). 6 live tests. Coverage 95 % (coverage.py's combined line and branch
figure; 94 to 100 % per protocol module, 96 % for the package; 89 to 100 % for the benchmark).
Ruff (pycodestyle, pyflakes, isort, bugbear, pyupgrade, pydocstyle Google) clean.

### 8.3 Golden tests: adding recorded replies

`run.py --export-golden FILE` writes the first raw reply of every JSON evidence case with the
verdict today's code gives. To promote some: review each (public ruling only, no Suva material),
copy the reviewed lines into `tests/tool_bench/golden/recorded.jsonl` and, in the same PR, add the
parametrised test that reads it (copy the pattern of `test_golden.py`; neither exists yet), then
commit. Unlike the hand-written file, these are real replies; their
verdict is still today's code, so review each one by eye before it becomes a reference. A
behaviour change then shows as a golden diff; updating needs `UPDATE_GOLDEN=1` and a PR that
explains the diff.

### 8.4 Replay

Three levels: (1) `ScriptedChat` replays scripted replies in unit tests; (2) `run.py --replay
replies.jsonl` re-scores a whole stored benchmark run with today's parser and validator, without a
gateway call (`test_cli_live_then_replay_gives_identical_rows` proves it is exact). Each stored
reply carries the SHA-256 of its request; when today's code sends a different request (a prompt
change), the reply is still used but counted in `replay_requests_changed`: such a replay re-scores
parsing, it does not measure the new prompt. (3) The client's replay cache replays pipeline calls,
which works because requests are byte-stable (doctrine test) and every reply is stored (§5.2).

### 8.5 Non-regression

What each guard covers: the benchmark uses its own tools and prompts, so it guards the parser, the
validator, the format block, the repair turn, the client mapping and the model. It does not exercise
the pipeline's contracts or the stages' prompts: for those, rerun the live contract tests and the
stage's own evaluation (`docs/EVAL.md`).

* Offline: the golden files and wire snapshots fail on any behaviour or contract change.
* Live: `python -m eval.tool_bench.score --compare BASE/rows.jsonl NEW/rows.jsonl` gives, per model,
  configuration and category, the paired difference with a cluster-bootstrap interval. Both runs
  must hold **the same cases**: same rulings file, profile and seed (`report.json` records
  `rulings_sha256` and `cases_sha256`; case ids are derived from the case content). If any group's
  cases differ it exits **2** ("not comparable"): a quick run cannot be compared with a full one.
  It exits **1** when an interval lies entirely below 0 (a regression). A drop larger than 0.05 whose
  interval still includes 0, or a group with fewer than 20 cases, is listed under `watch`: with the
  70B not deterministic (K10), one flipped case out of 9 is noise, not a regression.
* So keep two baselines: the last full run (compare full with full) and a quick run made right
  after it on the same rulings (compare quick with quick after small changes).

### 8.6 Release gate: "validated chez nous"

The implementation counts as validated in our repository when all of these hold, each with its
evidence in the PR:

1. `make check` green, including the offline tests ported (246 in the two test paths before a
   score module exists; the client-mapping assertions run in the client's tests), with the
   contracts imported from `src/schemas.py`.
2. The doctrine tests run against the real tree, including the score-path test (no longer skipped).
3. The pitfall tests shown red against a broken parser, then green (G9).
4. The live contract tests (`RUN_LIVE=1 pytest -m live tests/tool_protocol`, inside `make smoke-llm`) green on
   both models: the 6 tests pass at STRICT, none served from the cache, with the number
   that passed at the first attempt reported. They check the format only; content (for example
   which party appealed, LESSONS §2b) is the evaluation's job.
5. The benchmark's full profile run once, 2 repetitions, in an announced slot; every **blocking**
   criterion of `thresholds.json` passes, or the failure is reported with a decision entry.
6. Three real rulings run through each stage that uses the protocol, end to end, with stored,
   non-empty outputs (G6).
7. `NOTICE` updated; headers present; module README and docstrings complete (ruff `D` clean).

### 8.7 Flakiness and non-determinism

The 70B varies at T = 0 (K10). Offline tests are deterministic by construction (no network, fixed
hypothesis profiles with `deadline=None`). Live tests assert properties (validity, ids offered,
quote found), never exact text. A live failure is re-run **once**; a second failure is a finding,
reported with the trace hashes and the `llm_calls` rows, never retried until green.

### 8.8 CI sketch (GitHub Actions)

```yaml
jobs:
  check:                                    # every push and PR
    steps:
      - run: pip install pytest hypothesis pytest-cov ruff pydantic   # or the repo's own dev install
      - run: ruff check src eval tests      # add .hypothesis/ and .coverage to .gitignore
      - run: pytest --cov=src/llm/tool_protocol --cov-branch --cov-fail-under=90
  # no live job in CI: the gateway key is not a CI secret (G13); live runs are manual (make smoke-llm)
```

---

## 9. Benchmark: native tool calling vs the JSON protocol

### 9.1 Design

Adapted from ArchAI's `tool_bench.py` (BFCL categories, one request per case, AST-style scoring,
native call extraction, thread-pool runner).

| Category | Per language (full / quick) | Gold |
|---|---|---|
| `simple` | 4 / 1 per tool (`get_consideration`, `lookup_ruling`, `find_article`) | one call |
| `parallel` | 4 / 1 | two calls, same tool |
| `parallel_multiple` | 4 / 1 | two calls, two tools |
| `irrelevance` | 5 / 2 | no call |
| `evidence` | 16 + 4 / 2 + 1 | `locate_passage(a_consideration = cN or none)`, computed by code |

Languages DE, FR, IT (questions in the language; acts written as a lawyer of that language writes
them: `LAA` for `UVG` in French, `LAINF` in Italian). Configurations: `json_strict`, `json_object`,
`native_auto` (with `parallel_tool_calls: true` for the call categories), `native_forced` (evidence
only). Models: both Apertus sizes, by their `MODELS.md` ids. Prompt version `tool_bench-2`: the
evidence system prompt names the `locate_passage` tool for every configuration (`tool_bench-1`, the
smoke's, did not).

### 9.2 Metrics and statistics

Per row: `exact_raw` (as written), `exact` (after validation and, for JSON forms, the repair turn:
the pipeline's view), `exact_first` (first reply only: the fair view for native vs JSON, since
native calls get no repair), `valid`, ids emitted, invented, non-canonical, accepted-invalid
(computed from the case data, independently of the `IdTable`, must be 0), unknown tools, leaked tool
text, `text_exact` (a native evidence reply in plain text: was the id it names right?), latency.

* **Irrelevance** is correct only if the model emitted **no call**: a call that validation refused
  still counts as a call (the 8B's invented `translate` tool is a failure of restraint, not a pass).
* Aggregates per model × configuration × category × language with Wilson 95 % intervals.
* Paired **cluster** bootstrap, 10,000 draws (EVAL §1.5): it resamples cases and keeps a case's
  repetitions together, so a duplicated run does not look more significant.
* Thresholds are evaluated on **each repetition** and the worst one counts (EVAL §1.4);
  `value_by_rep` keeps them all.
* Native vs JSON comparisons, overall and per language, use `exact_first`; `score.decide()` applies
  the decision rule and writes `keep_json`, `native_candidate` or `insufficient_n` to `report.json`.
* A job that raises becomes a row (`request_error = "exception:<type>"`) and the run goes on; each
  finished job is appended to `partial.jsonl` at once, so an interrupted run keeps what it measured.

### 9.3 Pre-registered thresholds (PROPOSED, `thresholds.json`)

| Id | Criterion | Target | Blocking |
|---|---|---|---|
| T1 | 70B, JSON strict, evidence: usable after ≤ 1 repair, per language | ≥ 0.99 | yes |
| T2 | 8B, same | ≥ 0.97 | yes |
| T3 | Any configuration: ids accepted without being offered | = 0 | yes |
| T4 | 70B, JSON strict, evidence exact after the pipeline's repair turn, per language | ≥ 0.85 | yes |
| T4b | same, lower Wilson bound | ≥ 0.70 | no (reported) |
| T5 | 70B, JSON configurations: **no call emitted** when no tool fits | ≥ 0.90 | yes |
| T6 | 8B, JSON strict, evidence exact, per language | ≥ 0.75 | no (the 8B never excludes alone) |
| T7 | JSON strict requests accepted by the gateway | 0 errors | no |

With 20 evidence cases per language and 2 repetitions, a Wilson interval around 0.9 is about
± 0.10: this benchmark is a gate against gross failure, not a precise estimate. T3 is now computed
from the case data rather than from the `IdTable` that validated the call, so it can actually fail.

### 9.4 Running it and what it costs

```bash
python -m eval.tool_bench.run --rulings data/public/bench_rulings.jsonl --profile full --reps 2 --all \
    --models apertus-v1-5-70b apertus-v1-5-8b --out results/tool_bench/full_<date>
```

Full profile: 135 cases; about 1,880 calls and 3.5 M input tokens; about 25 minutes at 4 concurrent
calls (estimates scaled from the smoke). Run it in an announced slot (D-030), never during the
overnight pipeline run. Commit `report.md` and `report.json` only.

**Choosing the input rulings (D-031, EVAL §3b).** The selection must not depend on Suva's labels:

* draw a random sample (seed written down) of 30 to 50 public 8C and 9C rulings from DS3, with their
  considerations, at least 10 per language;
* exclude the 33 rulings of DS7 (the smoke set, `eval/smoke_set.txt`) and every ruling of the
  labelled quarters Q4/2025 and Q1/2026 (they belong to the evaluation of the scorer, D-021 point 8);
* keep the file in `data/public/` but out of git: a committed selection command and seed rebuild it
  from DS3 (crawl approves the file's place); commit the command, the seed and the file's SHA-256 (the run writes `rulings_sha256` and `cases_sha256` to
  `report.json`).

The loader keeps only docket, language and considerations. A consideration without `id` gets
`c1` … `cN` in order and its number is read from `e_number` or `number` (OpenCaseLaw's
`erwaegungen_paragraphs` records have no `id`); check one record by eye before the run.

### 9.5 Smoke results, 27 Nov 2026, 17:52 to 17:55 UTC (a smoke, **not a measurement**)

**Input: the smoke set DS7** (the 33 rulings of the team's gateway test; 29 of them yielded cases;
14 of the 33 were chosen from Suva's list). EVAL §3b: a smoke run checks that things work; "never
choose a threshold, a prompt or a variant on it, and never report it as a measurement". So nothing
below supports D-054, a LESSONS row or a choice between native and JSON; the full benchmark on an
independent sample (§9.4) does that.

Quick profile, 30 cases, 1 repetition, 199 calls, both models, 4 concurrent calls, via
`examples/chatfn_mapping.py`, prompt version `tool_bench-1`, `parallel_tool_calls` not sent. The
table below is the same stored replies **re-scored offline with today's code** (`--replay`, after
mapping the old positional case ids to the content-derived ones; all 199 requests differ from
today's because the prompt changed, so this re-scores parsing and validation, not the new prompt).
Aggregates are in `smoke/quick_2026-11-27_rescored/`; the first scoring is kept in
`smoke/quick_2026-11-27/`. **n = 3 evidence cases per language.**

| Model / configuration | n | exact | 95 % CI | exact first | exact raw | valid | text answers (right) | median s (live) |
|---|---|---|---|---|---|---|---|---|
| 70B / json_strict | 30 | 0.933 | 0.787 to 0.982 | 0.933 | 0.933 | 1.000 | | 2.8 |
| 70B / json_object | 30 | 0.967 | 0.833 to 0.994 | 0.933 | 0.833 | 1.000 | | 2.7 |
| 70B / native_auto | 30 | 0.500 | 0.332 to 0.668 | 0.500 | 0.500 | 0.700 | 9 (9) | 2.1 |
| 70B / native_forced (evidence) | 9 | 1.000 | 0.701 to 1.000 | 1.000 | 1.000 | 1.000 | | 1.9 |
| 8B / json_strict | 30 | 0.700 | 0.521 to 0.833 | 0.700 | 0.700 | 1.000 | | 4.0 |
| 8B / json_object | 30 | 0.700 | 0.521 to 0.833 | 0.700 | 0.633 | 0.967 | | 4.2 |
| 8B / native_auto | 30 | 0.633 | 0.455 to 0.781 | 0.633 | 0.567 | 0.900 | 1 (0) | 1.4 |
| 8B / native_forced (evidence) | 9 | 0.889 | 0.565 to 0.980 | 0.889 | 0.889 | 1.000 | | 0.3 |

What changed with today's scoring: two 8B rows dropped (`json_object` 0.733 to 0.700, `native_auto`
0.700 to 0.633) because an irrelevant question answered with a call that validation refused (the
invented `translate` tool twice in `native_auto`, `find_article(a_act="none")` in `json_object`) is
now a failure of restraint, not a pass.

What the smoke shows, as observations only:

* **The harness runs end to end on Keera**, both models, all four configurations, and replays
  offline.
* **Native `auto`, 70B, evidence: 0/9 as tool calls, 9/9 right as text.** It answered `c9`,
  `E. 4.2.1` (= `c6`), `none`, `c4`, `c2`, `none`, `c3`, `c1`, `none`, all equal to the gold. The
  `tool_bench-1` system prompt never mentioned the tool, so this is a prompt effect, not evidence
  against native calling; `tool_bench-2` names the tool. With a named `tool_choice` the 70B made 9/9,
  the same as JSON strict.
* **One call per turn in native mode** in every multi-call case (70B and 8B, parallel and parallel
  multiple 0/6 each), with `parallel_tool_calls` not sent; a later probe call with it set to `true`
  was accepted and still produced one call for a two-call request (one call per model, 18:40 UTC).
  The 8B also made one call per step in JSON.
* **STRICT with one `anyOf` branch per tool inside a list of objects was accepted**: 42 of 42
  `json_strict` loop requests (21 per model), no rejection. The other 18 `json_strict` requests were
  evidence form calls without `anyOf`.
* **The validation layer changes the numbers below STRICT**: 70B `json_object` 0.833 as written,
  0.933 after exact id and act-alias resolution (`LAA`, `LAI`, `LPGA` mapped to `UVG`, `IVG`,
  `ATSG`), 0.967 after the repair turn (one missing key).
* **No id outside the offered set was accepted**: 0 in 198 scored rows (199 calls; one evidence
  case took a repair turn). The check is now independent of the validator (§9.3).
* **The decision rule refuses to decide on it**: the computed verdict on the smoke is
  `insufficient_n` (3 evidence cases per language, 20 needed), as intended.

**Live contract tests** (`pytest -m live`, from revision 2 with `RUN_LIVE=1`, STRICT, a synthetic 4-consideration ruling), format only:

| Run (UTC) | Code | Result | Wall time |
|---|---|---|---|
| 17:54 to 18:01 | before the review | 6 of 6 usable (attempts not recorded) | 7 min 16 s; cause not visible (no retry logging in the reference mapping; it overlapped the end of the benchmark smoke) |
| about 18:05 | before the review | 6 of 6 at the first attempt; 70B 2.1 to 13.8 s per call (summary the longest), 8B 0.5 to 1.4 s | about 22 s |
| 18:38 to 18:40 | after the review fixes | 6 of 6 at the first attempt (`ok`, 1 attempt, 0 dropped) | 1 min 50 s |
| about 19:26 to 19:28 | revision 2 (`RUN_LIVE=1`, a salt per session, cache check) | 6 of 6 at the first attempt (`ok`, 1 attempt, 0 dropped) | 1 min 38 s |

The summary contract's list of claim objects (K12's shape) passed in every run: "works on a short
synthetic text", not "tested on whole rulings". One content observation the format tests cannot
catch: a 70B justification said "the insurer's appeal was rejected" although the synthetic ruling
names no appellant (the party bias of LESSONS §2b). Content belongs to the evaluation. The
client's timeouts and logging (ARCHITECTURE §4) must cover slow spells like run 1.

---

## 10. Documentation instructions

### 10.1 Code

* Google-style docstrings on every public module, class, function and method, with `Args`,
  `Returns`, `Raises` where they apply; enforced by ruff `D` with `convention = "google"` (tests
  exempt). The doctest example on `parse_object` runs inside the suite (`test_doctest.py`), so it
  cannot be forgotten.
* Each module's docstring states what it guarantees and cites the `LESSONS.md` row or decision
  behind each choice. Keep that habit: a rule without its source is deleted at review.
* `src/llm/tool_protocol/README.md` (delivered) is the developer documentation: when to use, quick
  start, how it works, how to write a contract, the loop, the client's obligations, the codes,
  the tests. Update it in the same PR as any behaviour change.
* `eval/tool_bench/README.md` (delivered) documents the benchmark.
* Version: `__version__ = "0.2.1"` (0.1.0 ran the smoke; 0.2.0 is the reviewed version; 0.2.1 changes only the
  benchmark's runner, §14.2); bump the
  minor version on a behaviour change, the patch on a fix; the benchmark records it in `report.json`.

### 10.2 `docs/DECISIONS.md` (owner: `lead`; next free id at the time of writing: D-054)

These entries go in the **first** PR of the `tool-calling` owner (its brief, step 1), because
`AGENTS.md` §2 and §9 want a choice recorded in the PR that first meets it: D-054 (PROPOSED), the
three OPEN questions D-055, D-056 and D-057, and the ownership line D-058. If an id is taken when
the PR is written, use the next free ones and give the mapping in the PR description. The full
benchmark later adds only its measured verdict to D-054.

The ADR, as a §1 line:

```
| D-054 | 2026-11-27 | Structured outputs and model-proposed actions use the JSON tool protocol (`src/llm/tool_protocol/`, adapted from ArchAI, MIT, credited in `NOTICE`): one JSON object per call under the JSON cascade (json_schema strict → json_object → prompt), ids chosen from closed lists and resolved exactly, code-side constraints, one repair turn listing codes only, fail closed. Native `tools` are not used by the pipeline. The relevance score is not produced by this protocol, whatever D-021 point 4 decides. | PROPOSED | `LESSONS.md` K2 (strict works), K3 (key order), K11 (one system message); design reasons: ids as enums under strict decoding, portability of the cascade to the judges' endpoint (D-032), byte-stable replay; handoff `json-tool-protocol` §1.5 | the full benchmark's computed verdict (`eval/tool_bench/thresholds.json`, `score.decide()`) is `native_candidate` **and** native tool calling works on the judges' endpoint |
```

The basis cites no benchmark: the smoke ran on DS7 and cannot support a choice (EVAL §3b), and
ArchAI's numbers do not separate native from JSON for a single decision (§1.4). The full run
either confirms D-054 or triggers its "revisit if".

And one `OPEN` entry in §2, because the contract change is the platform owner's to make (G7):

```
### D-055 Shape of the triage label and of the signal form
- **Options:** label (a) `A | B` as in ARCHITECTURE §3; (b) `relevant | not_relevant | unclear`; (c) `A | B | unclear`. Signals (a) a list of signal objects per call; (b) one flat signal per call.
- **Reasoning:** an abstention value is needed under strict decoding, or the model guesses; words are readable in logs and cannot be confused with the score's label. Lists of objects are not in the gateway probe yet (K12); a list of claim objects passed the live format test on a short synthetic ruling (handoff §9.5), whole rulings are untested. One signal per call multiplies calls, but each call is short and cacheable (K14).
- **Recommendation for the owner to weigh:** label (b); signals (b) until the probe covers K12, then (a) if it passes.
- **Settled by:** the owner of `src/schemas.py` (`platform`), with the live contract test. **Due:** before `src/schemas.py` freezes the triage contract; if it is already frozen, the change is a PR its owner approves (G7) and the frozen shape stays until then.
- **While open:** build with (b)/(b) behind the contract name; nothing else depends on the field values.
```

Two more `OPEN` entries in §2, for the architecture changes of §6 point 3 and §5.2:

```
### D-056 Which layer validates structured outputs: pydantic or the JSON tool protocol?
- **Options:** (a) pydantic models stay the source of the schema (`Tool(parameters=Model.model_json_schema())`) and the protocol validates; (b) the same, plus `Model.model_validate(out.value)` after `propose`; (c) hand-written JSON schemas, no pydantic.
- **Reasoning:** ARCHITECTURE §3 has pydantic generate the validator and §4 item 7 says "Pydantic `extra=forbid`", but pydantic cannot resolve an id alias against a per-call table, drop one unsupported claim, or count repairs; the protocol validates `$ref`, `anyOf` and the code-only constraints of pydantic schemas (handoff `json-tool-protocol` §6).
- **Recommendation for the owners to weigh:** (a), or (b) if the team wants pydantic objects downstream.
- **Settled by:** the lead with the owner of `src/schemas.py` (`platform`). **Due:** before the contracts move into `src/schemas.py`.
- **While open:** (a); the PR that settles it edits ARCHITECTURE §3 and §4 item 7.

### D-057 What does the replay cache store?
- **Options:** (a) every reply of an allowed model, keyed by its request, with the caller's verdict (`Outcome.status`, `reason`) beside it in `llm_calls`; (b) only valid outputs, as ARCHITECTURE §4 item 8 says, with `propose` reporting validity back to the client through a callback.
- **Reasoning:** validity is decided inside `propose`, after the client returned; a repaired call embeds its first, invalid reply in the repair request, so under (b) as written today a repaired call cannot be replayed (D-032). Measurement runs never read the cache either way: each run and repetition has its own `cache_salt` (G10).
- **Recommendation for the owners to weigh:** (a).
- **Settled by:** the lead with `platform`. **Due:** before the client's replay cache is written.
- **While open:** (a); the PR that settles it edits ARCHITECTURE §4 item 8.
```

And the ownership line, as a §1 line (the lead's own decision of 27 Nov, a partial answer to D-024):

```
| D-058 | 2026-11-27 | The lead creates the area "Apertus tool calling" (`tool-calling`): `src/llm/tool_protocol/`, `eval/tool_bench/`, `tests/tool_protocol/`, `tests/tool_bench/` and `results/tool_bench/`, owned by one agent working for a team member (brief `docs/agents/tool-calling.md`). It contributes to the client, the probe, `src/schemas.py` and the shared docs by PRs their owners approve (G7). Partial answer to D-024: the other areas stay open. | DECIDED (lead) | the lead's request of 27 Nov | the team settles D-024 differently |
```

### 10.3 `docs/LESSONS.md` (owner: `lead`)

K17 and K18 are already proposed by the team's gateway test report (`RAPPORT_TESTS_KEERA.md`,
outside the repo), so the rows below take the next free numbers at the time of writing, K19 and K20;
renumber if others land first. In the repo: if `docs/LESSONS.md` already has K17 and K18, take the
next free numbers; if it ends at K16, ask the lead whether K17 and K18 are still reserved. They are **observations from a smoke on DS7, not measurements**, and
say so; replace their numbers with the full benchmark's once it has run (G11).

```
| K4 | … (unchanged) … | reported | not needed | observed again (27 Nov smoke on DS7, not a measurement; `parallel_tool_calls` not sent): native `tool_choice: auto` made one call per turn in every multi-call case (70B 0/6, 8B 0/6); with `parallel_tool_calls: true` Keera accepts the field (one probe call per model). The full benchmark measures it |
| K19 | `json_schema` strict accepts `anyOf` branches inside a list of objects (one branch per tool) | observed (27 Nov smoke on DS7, not a measurement) | 42 loop requests, 2 models, 0 rejected | to add to the gateway probe; nested lists in a form contract: see K12 |
| K20 | Below STRICT the validation layer changes the result: 70B `json_object` 0.833 exact as written, 0.933 after exact id and act-alias resolution, 0.967 after one repair turn; refused calls (invented tool names) are failures of restraint, not passes | observed (27 Nov smoke on DS7, not a measurement) | 30 cases × 2 models | the full benchmark reports exact_raw, exact_first and exact for every configuration |
```

Update K12's "Ours" cell: "a list of claim objects (STRICT) passed the live format test at the
first attempt in 3 runs × 2 models on a synthetic 4-consideration ruling (27 Nov); whole rulings
untested".

### 10.4 Other files

* `docs/ARCHITECTURE.md`:
  * §4 item 7: replace "Pydantic `extra=forbid`" by "Implemented by `src/llm/tool_protocol/` (D-054):
    closed objects, exact id resolution, code-side constraints; the client provides `chat_fn` and the
    `RequestRejected` classification."
  * §3: "one pydantic model per contract generates the JSON schema, the prompt examples and the
    validator" becomes "… generates the JSON schema; the protocol validates it" (or the option the
    lead picks, §6 point 3); add the D-055 note under the triage contract.
  * §4 item 8, once D-057 is settled: under its option (a), the replay cache stores every reply of an
    allowed model, valid or not, keyed by its request (§5.2); the run and repetition are the
    request's `cache_salt`.
* `MODELS.md`: no runtime change. The protocol and the benchmark use the two Apertus v1.5 models
  already listed; no new model, judge or tool at runtime. §2 gets one development row: this
  reference was written during the event, outside the repo, with Claude Code and Claude Opus 5.5
  (the brief's "Model declaration"). Development tools: hypothesis and pytest-cov join
  the dev dependencies (not models); pydantic is already in the stack (D-035).
* `NOTICE`: append `NOTICE.fragment` (§2).
* `docs/STATE.md`: one line when the module lands.
* Report, section 3 "Use of Apertus" (draft, numbers to be filled from `results/` by `make claims`):

  > Apertus proposes and code decides. Every structured output (justifications, signal tags,
  > summary claims) is one JSON object under the gateway's strict JSON schema mode, with field names
  > ordered for generation and the ids of the ruling's considerations offered as a closed list.
  > Code parses the reply tolerantly, validates its shape, resolves each cited id exactly, checks
  > quotes against the source, allows one repair turn that lists the problems without repeating any
  > text, and otherwise marks the item as failed, never as irrelevant. The relevance score is not
  > produced by this protocol. [After the full benchmark: one sentence on what it showed for native
  > tool calling against JSON, with the numbers from `results/tool_bench/full_<date>/report.md`.]
  > The protocol adapts code from the ArchAI project (MIT licence).

---

## 11. Open questions this work touches (described, not decided)

| Question | How this work touches it | Options | Recommendation (for the team to weigh) | Code impact |
|---|---|---|---|---|
| D-021 point 4: score form | none: the score is not produced by this protocol in any option | log-probability, label | unchanged | none |
| D-021 point 6: how the explanation is worded (built by code, written by Apertus, or both) | the part Apertus writes, if any, is `propose(JUSTIFY)` | code only; Apertus only; both | unchanged | none |
| Which rulings get a JSON justification (no entry settles it yet) | a justification costs about 9 s median per 70B call vs about 1 s for the score (K7, K15): about 1 h 50 instead of 30 min for 2,096 rulings at 4 concurrent calls (D-022, new facts) | every ruling; candidates above a score band; top N | justify what the UI shows first (the selected and the borderline), score everything; raise it with D-021 point 6 | a filter before `propose`; nothing inside it |
| D-056 (new): validator, pydantic or the protocol (ARCHITECTURE §3, §4 item 7) | §6 point 3 | (a) pydantic generates the schema, the protocol validates; (b) the same plus `model_validate` after; (c) no pydantic | (a), or (b) if pydantic objects are wanted downstream | none in the protocol; a line in each caller for (b) |
| D-057 (new): replay cache content (ARCHITECTURE §4 item 8, D-032) | repaired calls need their first, invalid reply cached (§5.2) | cache every reply; or let `propose` report validity back | cache every reply, store the verdict in `llm_calls` | the client only |
| D-022: role of the 8B | the protocol works with either size (live tests, both models); the 8B is weaker on multi-call and restraint in the smoke | (a)/(b)/(c) | unchanged; (c) stays excluded | none |
| D-028: gateway facts | adds the JSON tier, K12, `anyOf`, the strict whitespace runaway (judges' endpoint) and `parallel_tool_calls` to the probe | | add them to `make smoke-llm` | probe writes `json_tier` |
| D-031: what is committed | golden files are synthetic; benchmark files with excerpts and dockets stay out of git | | commit `report.*` only | `.gitignore` for `results/tool_bench/*/{cases,rows,replies}.jsonl` |
| D-032: live or replay | byte-stable requests make replay hit; live checks never compare text | (a)/(b)/(c) | unchanged | none |
| D-033: search | query rewriting would use the protocol only if search is built | | unchanged | none |
| K12: nested lists | the summary contract has one | probe on whole rulings, or flatten | keep the list: it passed the live format test in every run on a synthetic ruling (§9.5); confirm on whole rulings in `make smoke-llm` | none unless the probe fails |
| D-055 (new): label and signal shapes | §6 | §10.2 | label (b), signals (b) | `src/schemas.py` |

---

## 12. Plan for the agents

Since revision 2, one agent carries this work in the repository: the `tool-calling` owner. The lead
created this area on 27 Nov, and D-024 stays open for the other areas. Its brief,
`reference/docs/agents/tool-calling.md` (to land as `docs/agents/tool-calling.md`), is the authority
for the steps, the scope, the copy map and the never-commit list. `BOOTSTRAP.md` holds the prompt
that starts it. This table summarises the steps; each is one small PR.

| # | Step | Owner | Approves | Done when |
|---|---|---|---|---|
| 0 | Preconditions: the kit is in the repo; `tmp/json-tool-protocol/` is git-ignored | tool-calling | | both checks pass, otherwise stop |
| 1 | Docs PR: the brief, `tool-calling` in `AGENTS.md` §2, its row in §5 and the exclusions in the platform and evaluation rows, D-054 to D-058 (§10.2), the open questions listed with recommendations | tool-calling | lead | merged |
| 2 | Offline import: copy map, settings, exact ignore lines, `NOTICE`, the `MODELS.md` §2 row, `make bench-tools` | tool-calling | platform, lead | `make check`: 246 passed, 1 skipped, 6 deselected for the two test paths; ruff and the `D` command clean; package coverage ≥ 90 % |
| 3 | Pitfall tests shown red against a broken parser and validator (scratch branch), then green | tool-calling | | both logs in the PR (G9) |
| 4 | `chat_fn(model)` in the client (§5.2); client tests from `test_client_mapping.py` | tool-calling | platform | client tests green; `chat/completions` only in `src/llm/` |
| 5 | D-055 and the validator settled by their owners; contracts to `src/schemas.py`; snapshots regenerated with `UPDATE_GOLDEN=1`; ARCHITECTURE §3, §4 items 7 and 8 | tool-calling | platform, lead | snapshot test green; D-055 closed (does not block steps 6 to 10) |
| 6 | Probe items (§5.3; the judges' endpoint once Q-23 names it); `RUN_LIVE=1 pytest -m live tests/tool_protocol` only (not the ramp) | tool-calling | platform (probe) | 6 live tests green at STRICT on both models, none from the cache; first-attempt count reported |
| 7 | Benchmark inputs from DS3 (§9.4; needs crawl's DS3) | tool-calling | crawl | selection command, seed and SHA-256 committed; file not committed |
| 8 | Quick benchmark (about 200 calls): `--dry-run`, then `--all` | tool-calling | | the run completes with exit 0 or 1, not 3 (cache); nothing is concluded from it |
| 9 | Full benchmark, 2 repetitions, `--all`, announced slot outside the overnight run and before the feature freeze (about 1,880 calls, 25 min) | tool-calling | lead (D-054 verdict) | `report.md` and `report.json` committed; thresholds judged on the worst repetition; verdict reported |
| 10 | Quick baseline on the same file and seed | tool-calling | | run folder kept on disk |
| 11 | The measured verdict in D-054, LESSONS rows, the remaining ARCHITECTURE edits, `docs/STATE.md`, report §3 via `make claims` | tool-calling | lead, eval (`make claims`) | merged |
| 12 | 3 real rulings end to end through each stage that uses the protocol (G6) | triage, summarise, verifier, with tool-calling | | stored, non-empty outputs; statuses and reasons counted |
| 13 | After a change of parser, validator, format block, repair turn, client mapping or model: quick profile, then `score --compare` against the quick baseline. After a change of contract or stage prompt: the live contract tests and the stage's own evaluation (§8.5) | tool-calling | | exit 0, or a decision entry for a regression; exit 2 means the inputs differ |

The stages keep their own work. Triage calls `propose(JUSTIFY)` after the score, for the rulings the
team chooses (§11). The verifier's owner writes the `src/verify/` checks (a non-fatal problem must
name an `a_claims[i]` item), and summarise calls `propose(TAG_SIGNAL)` and
`propose(SUMMARY, item_level=["a_claims"])`.

---

## 13. Inventory of this folder

```
handoff/json-tool-protocol/
  HANDOFF.md                     this document
  BOOTSTRAP.md                   the 3-step procedure (French) and the prompt to paste (English)
  NOTICE.fragment                append to the repository's NOTICE
  reference/                     the reference implementation; paths mirror the repo (Apache-2.0; ArchAI-derived parts MIT)
    pyproject.toml               pytest and ruff settings to merge
    conftest.py                  test bootstrap for this tree only (not copied)
    docs/agents/tool-calling.md  the owner's role brief, in the kit's format
    src/llm/tool_protocol/       the package and its README
    eval/tool_bench/             the benchmark (cases, tools, run, score, thresholds.json, README)
    examples/chatfn_mapping.py   client mapping illustration (not copied)
    tests/tool_protocol/         unit, hardening, contract, golden, property, doctrine, doctest, client mapping, live
    tests/tool_bench/            offline benchmark tests and synthetic gateways
  smoke/quick_2026-11-27/        report.md and report.json of the 27 Nov smoke, first scoring (aggregates only)
  smoke/quick_2026-11-27_rescored/  the same replies re-scored offline with today's code (aggregates only)
  upstream/archai/               ArchAI files, unchanged, with LICENSE and PROVENANCE.md (reference only)
```

The same folder is zipped as `handoff/json-tool-protocol_2026-11-27.zip`, to unzip into `tmp/` of a
clone (`BOOTSTRAP.md`).

How to run the reference tree locally:

```bash
cd handoff/json-tool-protocol/reference
pip install pytest hypothesis ruff pytest-cov pydantic
pytest                                   # 263 passed, 1 skipped (offline; without pydantic: 261 and 3)
ruff check src eval tests examples
# reference tree only, never from a repo clone (examples/ would call the gateway outside src/llm/, G2):
RUN_LIVE=1 LLM_BASE_URL=<gateway https URL> LIVE_CHAT_FACTORY=examples.chatfn_mapping:make_chat_fn \
    pytest -m live -s tests/tool_protocol   # key in LLM_API_KEY, or an injecting proxy
```

---

## 14. Independent adversarial review and what changed

### 14.1 Before the first delivery

Before delivery, a separate reviewer (another agent, told to break the work, not to confirm it)
read the code, ran the tests, wrote probe scripts and checked every number and citation against
its source. It found 1 blocker, 13 major and 4 minor findings, and 1 detail. All are addressed in
this version; the live contract tests were re-run on Keera after the fixes (6 of 6 at the first
attempt, §9.5).

| # | Severity | Finding | What changed |
|---|---|---|---|
| F1 | blocker | Validation ignored `$ref` and `anyOf`: a pydantic schema's nested models and `Optional` fields were not checked; binding a nested id table raised | `validate` and `bind_enums` inline `$ref`; `anyOf`/`oneOf` tried branch by branch; `Tool` refuses keywords code does not enforce; tests through `propose(OBJECT)` with pydantic (§3.2, §7) |
| F2 | major | The smoke headline was misleading (the 70B's 9 text answers were right; `native_forced` equalled JSON) and the smoke ran on DS7, which EVAL §3b excludes from any choice | French summary, §1.5, §9.5, D-054 and LESSONS rewritten; the smoke supports nothing; `tool_bench-2` names the tool; text answers recorded (`text_exact`) |
| F3 | major | Native vs JSON compared after JSON's repair turn; a refused call on an irrelevant question counted as restraint; the per-language rule was not computed | comparisons and the decision rule use `exact_first`; irrelevance = no call emitted; `score.decide()` per language |
| F4 | major | `minLength`, `pattern`, `uniqueItems` dropped from the wire and not enforced; `Tool.caps` unused | all enforced (plus `minimum`, `maximum`, `const`); `caps` merged; contracts gained minimums |
| F5 | major | No repetition index in the request (rep 1 could be a cache hit on rep 0); bootstrap treated repetitions as independent; 4,000 draws; guards pooled over repetitions | `ChatRequest.cache_salt`; cluster bootstrap by case, 10,000 draws; thresholds on the worst repetition |
| F6 | major | Non-regression compared quick with full (0 pairs, silent pass) and fired on one flipped case | content-derived case ids; exit 2 when cases differ; regression only when the interval is below 0; `watch` list; hashes in `report.json` |
| F7 | major | Parser quadratic on some inputs (about 35 min extrapolated at 200,000 characters) | linear scan and single-pass quote repair; step-count tests |
| F8 | major | A check's non-fatal problem without an item path let an ungrounded value through | made fatal unless it names an `item_level` item |
| F9 | major | Integration steps failed when followed literally (default factories, imports, `pip install -e .[dev]`, doctest outside the suite, `testpaths` merge, OpenCaseLaw records without `id`, a URL default in code) | defaults point at `llm.client:chat_fn`; client tests skip without `examples/`; explicit install line; `test_doctest.py`; merge instructions; loader numbers considerations; `LLM_BASE_URL` required |
| F10 | major | Repaired calls could not be replayed (ARCHITECTURE §4.8 caches only valid outputs) | §5.2 and §10.4 propose caching every reply; listed in §11 |
| F11 | major | The benchmark inputs could be selected from Suva's labels and committed | §9.4 and §12 step 9: random public sample outside DS7 and the labelled quarters, not committed, hashed |
| F12 | major | A known strict-mode failure (whitespace runaway on CSCS, 11/24) was missing and the cascade could not handle it | §1.3 row; one step to OBJECT; probe item |
| F13 | major | "60 of 60 `anyOf` requests" was really 42; K17 and K18 were already taken | 42; rows renumbered K19 and K20 |
| F14 | major | D-054 and the report draft said the score *is* a log-probability call (D-021 point 4 is open) | "not produced by this protocol, whatever D-021 point 4 decides" |
| F15 | minor | Attribution gaps: `run.py` adapted from ArchAI without a notice; header test partial; gemeindesim and rosetta-flow ideas and apertus-fracture uncredited | header and `NOTICE` entry for `run.py`; the header test covers all six files; §2 rows added |
| F16 | minor | Citation errors (replayed assistant turn attributed to K11; the b2bern claim; D-021 point 6; the pydantic change not flagged; ArchAI cited as evidence in D-054) | each corrected (§1.3, §3.7, §11, §6 point 3, §10.2) |
| F17 | minor | Test-strategy gaps (live tests check format only; "first attempt" not asserted; untested branches; client ordering and back-off; golden provenance; replay ignoring the request; name-based score-path test) | `test_hardening.py` and client tests cover the branches; live tests print attempts and say "format only"; golden docstring corrected; replay counts changed requests; score-path test also matches `logprobs` |
| F18 | minor | Smaller defects (repair replay cut at 4,000 characters; fallback not delimited; required tool counted by name; bench lost a run on one exception; `parallel_tool_calls` not sent; stale docstrings) | 16,000 characters; data tags; counted by arguments; per-job rows and `partial.jsonl`; sent; docstrings fixed |
| F19 | detail | Line and suite counts, the coverage figure's meaning, T3 being tautological, a model id not in MODELS.md, caches to ignore | recounted (§3.2, §8.2); "combined line and branch"; T3 independent of the validator; neutral test model id; `.gitignore` note |

The reviewer also confirmed, by re-deriving them: the test and coverage figures of the first
version, ArchAI's commit, licence and file hashes, all eleven repositories' licences and holders,
the upstream pitfalls, the §1.4 table, the smoke's aggregates and timings, the `json_object` lift,
the second live run, the LESSONS citations other than K11's, that `thresholds.json` predates the
smoke, that D-054 is the next free id, that the package holds no secret, no team member's name and
no Suva text, and that `IdTable.resolve` cannot return an id that was not offered.

### 14.2 Revision 2 (27 Nov, evening): ready for a repo agent that owns tool calling

Asked: make this handoff self-sufficient for one agent working in the repository as the owner of
Apertus tool calling, aligned with the starter kit (`AGENTS.md`, G1 to G15, the role briefs,
`DECISIONS.md`, `MODELS.md`). A cold read against the kit found these gaps.

| # | Gap | What changed |
|---|---|---|
| R1 | No single owner: the steps were split across platform, eval, triage, summarise and lead | a `tool-calling` area with a role brief in the kit's format (`reference/docs/agents/tool-calling.md`): what it owns, what it brings by PR with the approving owner per file (G7), what is not its, its interfaces, inputs, copy map, never-commit list, steps in validation order, open questions, rules, done when. §5.1 and §12 point to it |
| R2 | The score-path doctrine test would have failed as soon as the client existed: `src/llm/client.py` mentions `logprobs` (the score call) and imports the protocol's types | the check skips `src/llm/` (the gateway layer serves both paths by design) and `tool_bench`; the check itself is tested on a temporary tree (a mixed triage module is flagged, the client is not) |
| R3 | No start-up procedure or prompt | `BOOTSTRAP.md`: 3 steps, and a prompt that checks the preconditions before anything else |
| R4 | The folder could be committed by mistake once dropped into a clone | it goes in `tmp/` (git-ignored by the kit); the prompt stops if `git check-ignore` fails; the brief lists the handoff files never to commit |
| R5 | The expected test counts were those of the reference tree | counts for the repo after the port (243 passed then; 246 after R10), checked on a simulated port without `examples/`, `conftest.py` and `test_client_mapping.py` |
| R6 | Sources outside the repo (`RAPPORT_TESTS_KEERA.md`, `audit/…`) and the K17/K18 reservation cannot be checked from the repo | §1.3 says they are outside and restates their facts; §10.3 and the brief say what to do if LESSONS ends at K16 |
| R7 | Owner lines in the code said `platform` and `eval` | the package README, the benchmark README and the two `__init__.py` docstrings name `tool-calling` |
| R8 | Benchmark baselines (`rows.jsonl`) are not committed, so non-regression depends on one machine | the brief says so: keep run folders on disk for the event, copy them by hand if the machine changes, never through git |
| R9 | `.hypothesis/`, `.coverage` and `htmlcov/` are not in the kit's `.gitignore` block | the brief appends them (D-044) |

`MODELS.md` gets no new runtime model; §2 gets the development tool and model that wrote the
reference (brief, "Model declaration"). The score-path fix added one test (260 then; 263 after R10).

A second independent reviewer then read revision 2 cold, as the repo agent would, against the kit:
no blocker, 8 major findings and a set of minor ones. All are addressed.

| # | Severity | Finding | What changed |
|---|---|---|---|
| R10 | major | Every benchmark run sent the same salts (`""`, `rep1`), so a later run or the quick baseline could be served from the client's replay cache; the live tests sent no salt at all | each live run has a `run_id` (`--out` name and start time) and sends `<run_id>/rep<r>`; a replay reuses the stored `run_id`; replies the client marks `REPLAY` are counted and a live run with any exits 3; the live tests send a salt per session and fail on a cached reply; tested offline, live tests re-run on Keera (6 of 6, §9.5); version 0.2.1 |
| R11 | major | Non-regression was promised for prompt and contract changes, which the benchmark does not exercise | the promise is narrowed (brief step 13, §8.5, §12); contracts and stage prompts are guarded by the live tests and the stage's evaluation |
| R12 | major | Ownership overlapped the platform row (`src/llm/`) and the evaluation row (`eval/`, `results/`); `json_tier` was claimed in platform's probe output | step 1 writes the exclusions into both rows; `json_tier` stays platform's, the owner defines the probe items |
| R13 | major | D-054, D-055 and the validator question were recorded only after the benchmark; the area itself had no decision entry; the procedure asked the person to settle questions whose owners are others | D-054 to D-058 enter in the first PR (§10.2 has the texts, including the new D-056 validator, D-057 replay cache content and D-058 ownership); the procedure says who settles what |
| R14 | major | `NOTICE` landed after the MIT-derived code (G14) | appended in the import PR |
| R15 | major | The ignore lines were not spelled out, and the one written used brace expansion, which git does not do | exact lines in the brief, checked with `git check-ignore` on a scratch repository |
| R16 | major | The docstring check and the 120-character lines depended on settings the brief did not carry | exact `D` command; `line-length = 120` or per-file `E501` ignores plus a one-time import rewrap, checked on a simulated port |
| R17 | major | The `MODELS.md` §2 declaration could not be made (tool and model not named), and D-029 was the wrong rule for work done during the event | tool and model named in the brief; D-029 no longer cited |
| R18 | minor | The CLI spent calls by default (`AGENTS.md` §6); live tests could run if a command passed its own `-m`; step 6 ran the whole `make smoke-llm` with its ramp; the input file's place in crawl's `data/` had no approval; `make claims` was not in the PR table; inputs gated by Q-23 and the owner's handle were not named; the freeze times were not mentioned; the prompt's "no URL" contradicted public links; reporting omitted `make run` and the 3 rulings; the `AGENTS.md` §7 checklist could not be met before step 12 | `--limit`/`--all` required, `--dry-run` added; `RUN_LIVE=1` guard; step 6 runs the live tests only; crawl and eval rows added; Q-23 and the handle named; Sat 12:00 freeze and the frozen-contract path stated; prompt and reporting reworded; pending §7 boxes stated per PR |
| R19 | minor | Small inconsistencies: `conftest.py` recommended `pythonpath = ["src"]`; §8.3 cited a test that does not exist; coverage figures were stale; `checks_example.py` and `src/verify/` owners; `docs/STATE.md` approver; the README and docstring examples lacked `--models`; `test_doctrine.py` located the benchmark by a fixed path; the reference live command could be run from a clone; `__init__.py` files in other owners' areas | each corrected; the benchmark is located by import; the live command says "reference tree only"; the `__init__.py` rows name their approvers |
