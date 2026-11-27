# SPDX-License-Identifier: Apache-2.0
"""Property-based and fuzz tests (hypothesis): invariants that must hold for *any* model output."""
import json
import time

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from llm.tool_protocol import consideration_table, parse_object, validate

from .contracts import JUSTIFY

IDS = [f"c{i}" for i in range(1, 9)]
TABLE = consideration_table([{"id": c, "e_number": f"{i}.1"} for i, c in enumerate(IDS, 1)])
text_st = st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=300)
noise = st.sampled_from(["", "Sure!\n", "```json\n", "<think>x</think>", "<|inner_prefix|>r<|inner_suffix|>",
                         "Here: ", "<|assistant_end|>"])
tail = st.sampled_from(["", "\n```", " Hope this helps.", "\n<|assistant_end|>"])
proposal = st.fixed_dictionaries({
    "a_evidence": st.lists(st.sampled_from(IDS), max_size=3, unique=True),
    "b_key_statement": text_st,
    "c_label": st.sampled_from(["relevant", "not_relevant", "unclear"]),
})
FAST = settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])


@FAST
@given(proposal, noise, tail, st.booleans())
def test_round_trip_through_any_wrapping(obj, pre, post, ascii_only):
    """A valid object wrapped in fences, reasoning, template tokens or prose comes back unchanged."""
    raw = pre + json.dumps(obj, ensure_ascii=ascii_only) + post
    r = parse_object(raw)
    if "<|" in obj["b_key_statement"] or "<think" in obj["b_key_statement"].lower() or "```" in obj["b_key_statement"]:
        return  # content that itself contains markers we strip is out of the round-trip contract
    assert r.obj == obj


@FAST
@given(st.text(max_size=2000))
def test_never_raises_and_is_fast_on_arbitrary_text(s):
    t0 = time.perf_counter()
    r = parse_object(s)
    assert r.status in {"ok", "no_object", "truncated", "invalid_json", "top_level_array", "too_long"}
    assert (r.obj is None) == (r.status != "ok")
    assert time.perf_counter() - t0 < 0.5


@FAST
@given(proposal, st.integers(min_value=0, max_value=10_000), st.sampled_from(["delete", "truncate", "dup", "swapq"]))
def test_mutated_json_never_yields_an_unoffered_id(obj, seed, how):
    """Safety invariant: whatever the parser returns, validation never accepts an id we did not offer."""
    s = json.dumps(obj, ensure_ascii=False)
    i = seed % max(1, len(s))
    s = {"delete": s[:i] + s[i + 1:], "truncate": s[:i], "dup": s[:i] + s[i:i + 5] + s[i:],
         "swapq": s.replace('"', "'", 1 + seed % 3)}[how]
    r = parse_object(s)
    if r.obj is None:
        return
    v = validate(r.obj, JUSTIFY.parameters, id_tables={"a_evidence[]": TABLE})
    if not v.fatal and isinstance(v.obj.get("a_evidence"), list):
        assert set(v.obj["a_evidence"]) <= set(IDS)


@FAST
@given(proposal)
def test_parse_is_idempotent(obj):
    once = parse_object(json.dumps(obj)).obj
    assert parse_object(json.dumps(once)).obj == once


@FAST
@given(st.lists(st.text(min_size=1, max_size=12), min_size=1, max_size=6))
def test_resolution_never_invents(raw_ids):
    for raw in raw_ids:
        res = TABLE.resolve(raw)
        assert res.canonical is None or res.canonical in IDS


@FAST
@given(proposal)
def test_nested_trap_never_returns_inner_object(obj):
    broken = '{"outer": ' + json.dumps(obj) + ", oops}"
    assert parse_object(broken).obj is None
