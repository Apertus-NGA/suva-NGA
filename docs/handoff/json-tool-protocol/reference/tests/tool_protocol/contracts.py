# SPDX-License-Identifier: Apache-2.0
"""Example contracts used by the tests. In the repo they live in ``src/schemas.py`` (owner: platform).

Caps and minimums (``minItems``, ``minLength`` ...) stay here: the wire schema drops them and the
validator enforces them. They follow ``docs/ARCHITECTURE.md`` §3, with two proposed changes flagged
in the handoff:
``c_label`` uses words plus an abstention value (``unclear``) instead of ``A``/``B``, and the signal
form is flat (one signal per call) because lists of objects are not yet in the gateway probe (K12).
"""
from llm.tool_protocol import Tool

JUSTIFY = Tool(
    name="justify_relevance",
    description=("Point to the considerations that decide whether this ruling matters for an accident "
                 "insurer's practice, and state the key holding in one or two sentences. This is an "
                 "explanation for a lawyer, not the score."),
    parameters={
        "type": "object",
        "properties": {
            "a_evidence": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 3},
            "b_key_statement": {"type": "string", "minLength": 1, "maxLength": 300},
            "c_label": {"type": "string", "enum": ["relevant", "not_relevant", "unclear"]},
        },
        "additionalProperties": False,
        "required": ["a_evidence", "b_key_statement", "c_label"],
    },
)

TAG_SIGNAL = Tool(
    name="tag_signal",
    description=("Find where the ruling states the asked fact. Copy the shortest exact passage that states "
                 "it, then give the value as written in that passage. Choose 'none' if the ruling does "
                 "not state it."),
    parameters={
        "type": "object",
        "properties": {
            "a_consideration": {"type": "string"},
            "b_quote": {"type": "string", "maxLength": 400},
            "c_value": {"type": "string", "maxLength": 120},
        },
        "additionalProperties": False,
        "required": ["a_consideration", "b_quote", "c_value"],
    },
)

SUMMARY = Tool(
    name="summary_claims",
    description="Write the summary as claims, each citing the considerations that support it.",
    parameters={
        "type": "object",
        "properties": {
            "a_claims": {"type": "array", "minItems": 1, "items": {
                "type": "object",
                "properties": {
                    "a_cites": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 3},
                    "b_text": {"type": "string", "minLength": 1, "maxLength": 300},
                    "c_section": {"type": "string", "enum": ["facts", "law", "outcome"]},
                },
                "additionalProperties": False,
                "required": ["a_cites", "b_text", "c_section"],
            }},
            "b_outcome": {"type": "string",
                          "enum": ["upheld", "partly_upheld", "dismissed", "inadmissible", "remanded", "other"]},
            "c_unknown": {"type": "array", "items": {"type": "string"}},
        },
        "additionalProperties": False,
        "required": ["a_claims", "b_outcome", "c_unknown"],
    },
)
