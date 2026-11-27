# SPDX-License-Identifier: Apache-2.0
"""Unit and contract tests: ids, wire schemas (Keera strict profile), validation and repairs."""
import json
import os
from pathlib import Path

import pytest

from llm.tool_protocol import (
    IdTable,
    Tier,
    Tool,
    bind_enums,
    consideration_table,
    drop_items,
    lint_strict,
    loop_schema,
    placeholder_example,
    response_format,
    strict_profile,
    validate,
)

from .contracts import JUSTIFY, SUMMARY, TAG_SIGNAL

CONS = [{"id": "c1", "e_number": "1"}, {"id": "c2", "e_number": "4.2"}, {"id": "c3", "e_number": "4"},
        {"id": "c4", "e_number": "5"}]


# ---------------------------------------------------------------- ids

@pytest.mark.parametrize("raw, cid", [
    ("c2", "c2"), ("C02", "c2"), (" c2 ", "c2"), ("[c3]", "c3"), ("E. 4.2", "c2"), ("E.4.2", "c2"),
    ("Erw. 4.2", "c2"), ("consid. 4.2", "c2"), ("considerando 4.2", "c2"), ("4.2", "c2"), ("4.2.", "c2"),
    ("E. 4", "c3"), ("E 4", "c3"),
])
def test_id_spellings_resolve_exactly(raw, cid):
    assert consideration_table(CONS).resolve(raw).canonical == cid


@pytest.mark.parametrize("raw, reason", [
    ("4", "not_offered"), ("4.", "not_offered"), ("c9", "not_offered"), ("E. 9.9", "not_offered"),
    ("c22", "not_offered"), (3, "not_a_string"), ("", "empty"),
])
def test_unoffered_or_bare_numbers_are_refused(raw, reason):
    assert consideration_table(CONS).resolve(raw).reason == reason


def test_an_alias_shared_by_two_ids_is_ambiguous():
    t = IdTable(["a1", "a2"], {"a1": ["Art. 6 UVG"], "a2": ["art. 6 uvg"]})
    assert t.resolve("Art. 6 UVG").reason == "ambiguous"


def test_no_fuzzy_matching():
    assert consideration_table(CONS).resolve("E. 4.21").canonical is None


# ---------------------------------------------------------------- schemas (contract tests)

@pytest.mark.parametrize("tool", [JUSTIFY, TAG_SIGNAL, SUMMARY], ids=lambda t: t.name)
def test_every_contract_lints_clean_for_keera_strict(tool):
    errors = [p for p in lint_strict(strict_profile(tool.parameters)) if p.startswith("E:")]
    assert errors == []


@pytest.mark.parametrize("tool", [JUSTIFY, TAG_SIGNAL, SUMMARY], ids=lambda t: t.name)
def test_wire_schema_snapshot(tool):
    """The wire schema is a contract: a change shows up here and needs a reviewed snapshot update."""
    snap = Path(__file__).parent / "golden" / f"wire_{tool.name}.schema.json"
    wire = strict_profile(tool.parameters)
    if os.environ.get("UPDATE_GOLDEN") == "1":  # explicit, reviewed in the PR diff
        snap.write_text(json.dumps(wire, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    assert snap.exists(), f"missing snapshot {snap.name}: run with UPDATE_GOLDEN=1 and commit it"
    assert json.loads(snap.read_text(encoding="utf-8")) == wire


def test_strict_profile_closes_objects_and_moves_caps_to_code():
    wire = strict_profile(JUSTIFY.parameters)
    assert wire["additionalProperties"] is False
    assert wire["required"] == ["a_evidence", "b_key_statement", "c_label"]
    assert "maxItems" not in json.dumps(wire) and "maxLength" not in json.dumps(wire)
    assert "maxItems" in json.dumps(JUSTIFY.parameters)  # the original keeps them for validation


def test_lint_catches_wrong_generation_order_and_open_objects():
    bad = {"type": "object", "properties": {"label": {"type": "string"}, "evidence": {"type": "string"}},
           "additionalProperties": False, "required": ["label", "evidence"]}
    assert any("alphabetical" in p for p in lint_strict(bad))
    assert any("open object" in p for p in lint_strict({"type": "object"}))
    ints = strict_profile({"type": "object", "properties": {"a": {"type": "array", "items": {"type": "integer"}}}})
    assert any("arrays of numbers" in p for p in lint_strict(ints))


def test_lint_warns_on_untested_shapes():
    assert any(p.startswith("W:") and "K12" in p for p in lint_strict(strict_profile(SUMMARY.parameters)))


def test_pydantic_generated_schema_is_supported():
    pydantic = pytest.importorskip("pydantic")

    class Claim(pydantic.BaseModel):
        model_config = pydantic.ConfigDict(extra="forbid")
        a_cites: list[str]
        b_text: str

    class Form(pydantic.BaseModel):
        model_config = pydantic.ConfigDict(extra="forbid")
        a_claims: list[Claim]
        b_outcome: str

    wire = strict_profile(Form.model_json_schema())
    assert "$ref" not in json.dumps(wire) and "title" not in json.dumps(wire)
    assert [p for p in lint_strict(wire) if p.startswith("E:")] == []


def test_bind_enums_and_errors():
    wire = bind_enums(strict_profile(SUMMARY.parameters), {"a_claims[].a_cites[]": ["c1", "c2"]})
    assert wire["properties"]["a_claims"]["items"]["properties"]["a_cites"]["items"]["enum"] == ["c1", "c2"]
    with pytest.raises(ValueError, match="empty enum"):
        bind_enums(strict_profile(JUSTIFY.parameters), {"a_evidence[]": []})
    with pytest.raises(ValueError, match="unknown field"):
        bind_enums(strict_profile(JUSTIFY.parameters), {"zz[]": ["c1"]})


def test_response_format_per_tier():
    wire = strict_profile(JUSTIFY.parameters)
    assert response_format(Tier.STRICT, wire, "justify")["json_schema"]["strict"] is True
    assert response_format(Tier.OBJECT, wire, "justify") == {"type": "json_object"}
    assert response_format(Tier.PROMPT, wire, "justify") is None
    assert Tier.STRICT.weaker() is Tier.OBJECT and Tier.PROMPT.weaker() is None


def test_placeholder_example_holds_no_plausible_value():
    ex = placeholder_example(bind_enums(JUSTIFY.parameters, {"a_evidence[]": ["c1", "c2"]}))
    flat = json.dumps(ex, ensure_ascii=False)
    assert flat.count("<") >= 3 and "relevant |" in flat and "max 300" in flat


def test_tool_spec_guards():
    with pytest.raises(ValueError):
        Tool("Bad-Name", "x", {"type": "object", "properties": {}})
    with pytest.raises(ValueError):
        Tool("send_mail", "x", {"type": "object", "properties": {}}, read_only=False)
    with pytest.raises(ValueError):
        Tool("finish", "x", {"type": "object", "properties": {}})


def test_loop_schema_free_args_are_not_strict_capable():
    t = Tool("get_x", "d", {"type": "object", "properties": {"a_id": {"type": "string"}}})
    assert any(p.startswith("E:") for p in lint_strict(strict_profile(loop_schema([t]))))
    assert not any(p.startswith("E:") for p in lint_strict(strict_profile(loop_schema([t], strict_args=True))))


# ---------------------------------------------------------------- validation

def tables():
    return {"a_evidence[]": consideration_table(CONS)}


def test_valid_justification_normalises_ids_and_dedupes():
    v = validate({"a_evidence": ["E. 4.2", "c2", "c4"], "b_key_statement": "x", "c_label": "relevant"},
                 JUSTIFY.parameters, id_tables=tables())
    assert v.problems == []
    assert v.obj["a_evidence"] == ["c2", "c4"]
    assert any(r.startswith("id_normalised") for r in v.repairs) and "deduplicated:a_evidence" in v.repairs


@pytest.mark.parametrize("obj, code", [
    ({"a_evidence": ["c9"], "b_key_statement": "x", "c_label": "relevant"}, "not_offered"),
    ({"a_evidence": ["c1"], "b_key_statement": "x", "c_label": "maybe"}, "enum"),
    ({"a_evidence": ["c1"], "c_label": "relevant"}, "missing"),
    ({"a_evidence": ["c1"], "b_key_statement": "x", "c_label": "relevant", "d_confidence": 0.9}, "unexpected_key"),
    ({"a_evidence": ["c1", "c2", "c3", "c4"], "b_key_statement": "x", "c_label": "relevant"}, "too_many"),
    ({"a_evidence": ["c1"], "b_key_statement": "x" * 301, "c_label": "relevant"}, "too_long"),
    ({"a_evidence": [1], "b_key_statement": "x", "c_label": "relevant"}, "type"),
])
def test_invalid_justifications(obj, code):
    v = validate(obj, JUSTIFY.parameters, id_tables=tables())
    assert code in {p.code for p in v.problems}


def test_boolean_is_not_an_integer():
    schema = {"type": "object", "properties": {"a_n": {"type": "integer"}}, "additionalProperties": False}
    assert validate({"a_n": True}, schema).problems[0].code == "type"
    assert validate({"a_n": 3}, schema).problems == []


def test_scalar_wrapped_but_never_split_on_commas():
    v = validate({"a_evidence": "c1", "b_key_statement": "x", "c_label": "unclear"}, JUSTIFY.parameters,
                 id_tables=tables())
    assert v.obj["a_evidence"] == ["c1"] and "wrapped_scalar:a_evidence" in v.repairs
    schema = {"type": "object", "properties": {"a_refs": {"type": "array", "items": {"type": "string"}}}}
    assert validate({"a_refs": "Art. 6 Abs. 1, UVG"}, schema).obj["a_refs"] == ["Art. 6 Abs. 1, UVG"]


def test_key_rename_only_for_near_identical_names():
    v = validate({"a_evidance": ["c1"], "b_key_statement": "x", "c_label": "relevant"}, JUSTIFY.parameters,
                 id_tables=tables())
    assert "key_renamed:a_evidance->a_evidence" in v.repairs and v.problems == []
    v2 = validate({"evidence": ["c1"], "key_statement": "x", "label": "relevant"}, JUSTIFY.parameters,
                  id_tables=tables())
    assert v2.problems == [] and sum(r.startswith("key_prefix_restored") for r in v2.repairs) == 3
    v3 = validate({"proof": ["c1"], "b_key_statement": "x", "c_label": "relevant"}, JUSTIFY.parameters,
                  id_tables=tables())
    # ArchAI (difflib cutoff 0.5 plus the lone-argument rule) would have renamed "proof" to "a_evidence".
    assert {"unexpected_key", "missing"} <= {p.code for p in v3.problems}


def test_item_level_problems_drop_only_that_item():
    obj = {"a_claims": [{"a_cites": ["c1"], "b_text": "ok", "c_section": "law"},
                        {"a_cites": ["c9"], "b_text": "bad", "c_section": "law"}],
           "b_outcome": "dismissed", "c_unknown": []}
    v = validate(obj, SUMMARY.parameters, id_tables={"a_claims[].a_cites[]": consideration_table(CONS)},
                 item_level=["a_claims"])
    assert v.fatal == [] and len(v.droppable) == 1 and v.droppable[0].drop_path == "a_claims[1]"
    new, dropped = drop_items(v.obj, v.droppable)
    assert dropped == ["a_claims[1]"] and len(new["a_claims"]) == 1 and len(obj["a_claims"]) == 2


def test_input_object_is_not_mutated():
    obj = {"a_evidence": "E. 4.2", "b_key_statement": "x", "c_label": "relevant"}
    validate(obj, JUSTIFY.parameters, id_tables=tables())
    assert obj["a_evidence"] == "E. 4.2"
