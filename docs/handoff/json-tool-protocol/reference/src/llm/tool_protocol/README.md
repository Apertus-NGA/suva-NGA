# `llm.tool_protocol`: the JSON tool protocol

**Apertus proposes, code validates and decides.** This package turns one model call into a typed,
checked proposal, or into an explicit failure. It never opens a network connection: every call goes
through the project client (`src/llm/client.py`, golden rule G2), which this package receives as a
plain function (`ChatFn`).

Owner: `tool-calling` (`docs/agents/tool-calling.md`); `src/llm/client.py` stays `platform`'s.
Version: `0.2.1`. Licence: Apache-2.0; parts adapted from ArchAI under the MIT licence (see `NOTICE`).

## 1. When to use it, when not

| Use it for | Do not use it for |
|---|---|
| The triage **justification**: which considerations support the judgement, and the key statement (S3) | The relevance **score**, whatever form D-021 point 4 gives it. The gateway test used a one-token log-probability call outside JSON; under strict JSON the key names are tokenised character by character, so a score field would not work (K5) |
| Signal **tagging**: "where does the ruling state X?", with a verbatim quote that code checks ("Apertus tags, code decides") | Identifiers of any kind (dockets, article numbers, BGE references): code extracts them (G1). The model may only **choose** among ids we offer |
| Summary **claims**, each citing considerations (S6), checked by `src/verify/` (S7) | Final decisions: thresholds, exclusions, labels shown to Suva |
| Anything where the model must choose from a closed list we build | Anything code can compute (dates, quarters, counts, the docket prefix) |

## 2. Quick start

```python
from llm.client import chat_fn                      # the project client (platform); returns a ChatFn
from llm.tool_protocol import Tier, consideration_table, delimit, new_nonce, propose
from schemas import JUSTIFY                           # contracts live in src/schemas.py

ruling = load_ruling("8C_123/2025")                   # ruling record with considerations [{id, e_number, text}]
data = "\n".join(f"[{c['id']}] E. {c['e_number']}: {c['text']}" for c in ruling["considerations"])
out = propose(
    chat_fn(model=LLM_NAME), JUSTIFY,
    system=TRIAGE_SYSTEM,                             # the role text; the protocol appends the format block
    user=delimit("ruling", data, new_nonce(data)) + "\n\n" + TRIAGE_QUESTION,
    purpose="triage_justify", prompt_version="triage-3",
    tier=Tier(probe["json_tier"]),                    # from results/gateway_probe.json
    id_tables={"a_evidence[]": consideration_table(ruling["considerations"])},
)
if out.ok:
    store_justification(ruling, out.value, status=out.status, repairs=out.repairs)
else:
    store_failure(ruling, reason=out.reason)          # never a negative label (G5): "unclear", flagged
```

Signal tagging with a grounding check (from `src/verify/`):

```python
out = propose(chat, TAG_SIGNAL, system=..., user=...,
              purpose="signal_integrity_rate", prompt_version="signals-2",
              id_tables={"a_consideration": consideration_table(cons, none_option=True)},  # "none" = abstain
              checks=[verify.quote_in_cited], context=ruling)
```

Summary claims where one unsupported claim is dropped, not the whole summary:

```python
out = propose(chat, SUMMARY, ..., id_tables={"a_claims[].a_cites[]": consideration_table(cons)},
              item_level=["a_claims"], checks=[verify.claim_supported], context=ruling,
              max_tokens=1500, max_tokens_cap=3000)
out.dropped    # ("a_claims[3]",): counted and reported, never silent
```

## 3. How it works

```
 Tool (name, description, parameters with caps)
   │ strict_profile: inline $refs, close objects, drop code-only keywords (maxItems, maxLength ...)
   │ bind_enums: the offered ids become enums
   │ lint_strict: prefixes a_/b_/c_ in alphabetical = generation order (K3), no open object ... (raises if not)
   ▼
 ChatRequest ──► client ──► gateway            one system message (K11); data in <data id=NONCE> tags
   ▲                │
   │ cascade        ▼
   │ STRICT → OBJECT → PROMPT    on HTTP 400 "response_format" (does not count as an attempt)
   │
 ChatReply ──► parse_object ──► validate ──► checks (src/verify/) ──► Outcome
                 │                 │              │
                 │ fences, think,  │ shape, ids   │ grounding
                 │ template tokens │ (exact),     │ (quote in source,
                 │ syntax repairs  │ caps         │  number in cited)
                 ▼                 ▼              ▼
              problems ──► ONE repair turn (codes and paths only, never values) ──► else fail closed
```

* **Tiers** (`Tier`): `STRICT` sends `response_format: json_schema` with `strict: true` (works on
  Keera, K2); `OBJECT` sends `json_object` and a placeholder example in the prompt; `PROMPT` sends
  no `response_format`. The probe records the strongest tier the endpoint accepts; `propose` steps
  down by itself when the client raises `RequestRejected("response_format")`.
* **Ids** (`IdTable`, `consideration_table`): the model chooses among `c1`, `c2`, ... shown in square
  brackets. A few deterministic spellings are accepted (`C02`, `E. 4.2`, `consid. 4.2`, `4.2`); a
  bare `4` is refused because it is ambiguous with `c4`; no fuzzy matching, ever. `none_option=True`
  offers `none`, so abstaining is a valid answer under strict decoding.
* **Validation** (`validate`): local `$ref` inlined first (nested pydantic models are checked);
  types (`true` is not an integer), enums and `const` (`1` never equals `true`), `anyOf`/`oneOf`
  branch by branch (`Optional` fields), every declared key required, unknown keys, ids, and every
  code-only constraint removed from the wire schema: `maxItems`, `minItems`, `uniqueItems`,
  `maxLength`, `minLength`, `pattern`, `minimum`, `maximum`. `Tool` refuses any other keyword
  (`format`, `allOf` ...), so nothing is dropped from the wire and ignored by code. A few repairs,
  each logged: a dropped `a_` prefix restored, a near-identical key renamed (ratio ≥ 0.85, one
  candidate), a string wrapped into a one-item list (never split on commas), repeated ids kept once,
  an alias resolved to its canonical id.
* **Repair turn**: at most one (`repair_turns=1`). It replays the previous reply (up to 16,000
  characters) and lists problem codes and paths, never values and never source text. A reply cut by
  `max_tokens` is never parsed; the budget doubles once. Under STRICT, a cut reply that ends in 32
  or more whitespace characters (a constrained-decoding runaway, seen on another gateway) steps
  down to OBJECT once instead, without using the repair.
* **Fail closed**: `Outcome.status == "failed"` with a `reason` and `value is None`. The caller turns
  that into "unclear" or a flag, never into a negative label (G5). A check's non-fatal problem stays
  non-fatal only if its `drop_path` names one item of an `item_level` array; otherwise it is fatal.
* **Determinism for replay** (D-032): the same inputs produce the same request, byte for byte
  (`new_nonce(text)` derives the tag nonce from the data). The client's replay cache keys on it.
* **Trace**: one entry per call with tier, finish reason, served model, parse status, problem codes
  and the SHA-256 of the raw content. No raw text: the client's `llm_calls` store keeps it.

## 4. Writing a contract (checklist)

A contract is a `Tool` in `src/schemas.py`. Each one gets a snapshot test and the strict lint.

1. Fields prefixed `a_`, `b_`, `c_` in the order the model should write them: evidence first, the
   label last (K3: strict mode emits keys alphabetically).
2. `additionalProperties: false` and every key `required` on every object (the strict profile adds
   them; the lint fails a schema that cannot get them).
3. Closed sets as enums (bound per call with `id_tables`); an explicit abstention value (`none`,
   `unclear`) wherever "no answer" is a correct answer.
4. No arrays of numbers, no arrays of arrays; avoid lists of objects (K12: not in the gateway probe
   yet, the lint warns) until the probe covers them.
5. Caps and minimums (`maxItems`, `minItems`, `maxLength`, `minLength` ...) stay in the contract:
   code enforces them, the wire never carries them. Give every required text `minLength: 1` and
   every required list `minItems: 1`. Use only the keywords of `SUPPORTED_KEYWORDS`; `Tool` refuses
   the others when the contract is defined. A pydantic model works as the source
   (`Tool(..., parameters=Model.model_json_schema())`): its `$ref` and `Optional` fields are handled.
6. The description says what the field is for, in one or two sentences, with **no filled-in
   example** (another team saw a filled example copied in 53 % of replies; placeholders: 49/49 valid).
7. A field the model writes is never an identifier we could compute.
8. Run `pytest tests/tool_protocol -k snapshot` with `UPDATE_GOLDEN=1` once, review the new
   `golden/wire_<name>.schema.json` in the PR, and commit it.

## 5. The bounded loop (`run_tools`)

Not used by the v1 pipeline. It lets the model call read-only tools for a few steps
(`{"a_calls": [{"a_tool": ..., "b_args": {...}}]}`), with: unknown tools and invalid arguments refused
and fed back, identical calls run once, `max_steps`/`max_calls` caps, a stop on a step of only
repeated calls, one "not done yet" reminder, then required tools run by code. It exists for the
benchmark and for a later feature that needs several lookups. Tools must be read-only
(`Tool(read_only=False)` raises).

## 6. What the client must do for this package

| The protocol sends / expects | The client does |
|---|---|
| `ChatRequest.messages` (one `system`), `response_format`, `max_tokens`, `temperature` | Adds `model`, thinking off, timeouts, streaming beyond ~30 s, the served-model check (G3) |
| `purpose`, `prompt_version`, `cache_salt` | Logs them, puts them in the replay cache key, never sends them (`cache_salt` is the benchmark's run and repetition, `<run_id>/rep<r>`, and each live-test session's own salt) |
| `tools`, `tool_choice`, `parallel_tool_calls` (benchmark only) | Sends them as given (`parallel_tool_calls` only when not `None`) |
| A repaired call's first, invalid reply | Stores **every** reply in the replay cache, not only valid ones: the repair request embeds the first reply, so replay needs it (amend ARCHITECTURE §4.8) |
| `RequestRejected(kind)` on HTTP 400/422 | Classifies the error body: `response_format` (schema or guided decoding refused), `message_roles` (a replayed assistant turn or a second system message refused), `other` |
| `TransportFailure` | Raised only after its own retries (408/409/429/5xx, honouring `Retry-After`; never 401/403/404) |
| `ChatReply(content, finish_reason, served_model, tool_calls, mode)` | Fills them from the response; strips nothing (the parser does) |

`examples/chatfn_mapping.py` in the handoff shows the mapping and the classification in 100 lines.

## 7. Codes

| Where | Codes |
|---|---|
| `ParseResult.status` | `ok`, `no_object`, `truncated`, `invalid_json`, `top_level_array`, `too_long` |
| Parse repairs | `lenient_control_chars`, `backslash_quote`, `german_quotes`, `trailing_comma`, `unwrapped_singleton_list` |
| Stripped | `bom`, `inner_reasoning`, `think`, `control_token`, `fence` |
| `Problem.code` | `missing`, `unexpected_key`, `type`, `enum`, `not_offered`, `ambiguous_id`, `ambiguous_form`, `too_many`, `too_few`, `too_long`, `too_short`, `pattern`, `not_unique`, `too_small`, `too_large`, plus grounding codes from `src/verify/` |
| Validation repairs | `key_prefix_restored:x->a_x`, `key_renamed:x->y`, `wrapped_scalar:path`, `deduplicated:path`, `id_normalised:path` |
| `Outcome.reason` | `transport`, `rejected`, `truncated`, `invalid_json`, `no_object`, `schema`, `reference`, `grounding` |
| Trace entries | `rejected: response_format`, `rejected: message_roles`, `transport`, `cascade: whitespace_runaway`, `parse`, `problems`, `content_sha256` |

## 8. Tests

```
pytest tests/tool_protocol                 # unit, hardening, contract, golden, property, doctrine, doctest (offline, ~5 s)
RUN_LIVE=1 pytest -m live tests/tool_protocol   # one call per contract and model on the gateway (opt-in twice)
python -m eval.tool_bench.run --help       # the native-vs-JSON benchmark
```

The strategy, the thresholds and the release gates are in the handoff (`HANDOFF.md` §8 and §9).
