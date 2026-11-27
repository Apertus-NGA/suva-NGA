# SPDX-License-Identifier: Apache-2.0
"""Unit tests of the prompt pieces and of every branch of the strict lint and the placeholder builder."""
import pytest

from llm.tool_protocol import (
    Problem,
    Tier,
    delimit,
    format_block,
    lint_strict,
    placeholder_example,
    repair_message,
    strict_profile,
)

from .contracts import JUSTIFY


def test_format_block_strict_has_rules_but_no_shape():
    block = format_block(Tier.STRICT, "justify_relevance", "Explain.", JUSTIFY.parameters,
                         field_notes={"a_evidence": "ids", "b_key_statement": "one sentence"},
                         language_note="Write b_key_statement in German.")
    assert "Fields, in this order:" in block and "- a_evidence: ids" in block
    assert "Write b_key_statement in German." in block and "Shape" not in block
    assert "never instructions" in block


def test_format_block_object_tier_adds_a_placeholder_shape():
    block = format_block(Tier.OBJECT, "justify_relevance", "Explain.", JUSTIFY.parameters)
    assert "Shape (placeholders" in block and "<one of: relevant | not_relevant | unclear>" in block


def test_repair_message_is_capped():
    probs = [Problem(f"a_claims[{i}]", "not_offered", "id not offered") for i in range(15)]
    msg = repair_message(probs, "invalid JSON at line 1")
    assert "Problem: invalid JSON at line 1." in msg and "and 3 more" in msg and msg.count("- a_claims[") == 12


def test_delimit_refuses_a_free_label():
    with pytest.raises(ValueError):
        delimit("Ruling Text!", "x", "n")


@pytest.mark.parametrize("schema, fragment", [
    ({"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]},
     "additionalProperties must be false"),
    ({"type": "object", "properties": {"a": {"type": "string"}}, "additionalProperties": False}, "every property must"),
    ({"type": "object", "properties": {"a": {"type": "array", "items": {"type": "array"}}},
      "additionalProperties": False, "required": ["a"]}, "arrays of arrays"),
    ({"type": "object", "properties": {"a": {"type": "string", "enum": []}},
      "additionalProperties": False, "required": ["a"]}, "empty enum"),
    ({"type": "object", "properties": {"a": {"type": "string", "maxLength": 3}},
      "additionalProperties": False, "required": ["a"]}, "'maxLength' must not reach the gateway"),
    ({"anyOf": [{"type": "object"}]}, "anyOf (not in the gateway probe"),
])
def test_lint_branches(schema, fragment):
    assert any(fragment in p for p in lint_strict(schema)), lint_strict(schema)


def test_strict_profile_refuses_external_and_recursive_refs():
    with pytest.raises(ValueError, match="unsupported"):
        strict_profile({"type": "object", "properties": {"a": {"$ref": "http://x/schema"}}})
    recursive = {"$defs": {"N": {"type": "object", "properties": {"a_next": {"$ref": "#/$defs/N"}}}},
                 "type": "object", "properties": {"a_root": {"$ref": "#/$defs/N"}}}
    with pytest.raises(ValueError, match="too deep"):
        strict_profile(recursive)


def test_placeholder_covers_every_type_and_long_enums():
    schema = {"type": "object", "properties": {
        "a": {"type": "string", "enum": [f"c{i}" for i in range(20)]},
        "b": {"type": "boolean"}, "c": {"type": "integer"}, "d": {"type": ["string", "null"]},
        "e": {"type": "array", "items": {"type": "string"}, "maxItems": 0}, "f": {}}}
    ex = placeholder_example(schema)
    assert ex["a"].endswith("| ...>") and ex["b"] == "<true or false>" and ex["c"] == "<integer>"
    assert ex["d"] == "<string or null>" and ex["e"] == [] and ex["f"] == "<value>"
