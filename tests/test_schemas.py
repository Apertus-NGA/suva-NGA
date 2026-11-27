"""The frozen contracts (src/schemas.py): they accept valid records and refuse the ones that break a rule."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from src import schemas as s

TEXT = "Sachverhalt ... Erwägungen ... Demnach erkennt das Bundesgericht: Die Beschwerde wird abgewiesen."


def ruling(**over):
    base = dict(
        docket="8C_802/2023",
        decision_date=date(2026, 3, 27),
        publication_date=date(2026, 4, 20),
        publication_date_source="neuheiten",
        publication_date_quality="exact",
        quarter_by_decision="2026Q1",
        quarter_by_publication="2026Q2",
        court="8C",
        register_letter="C",
        language="de",
        url="https://search.bger.ch/...",
        text_source="hf",
        text_hash=s.sha256_text(TEXT),
        full_text=TEXT,
        considerations=[{"id": "c1", "e_number": "1", "text": "x"}, {"id": "c2", "e_number": "2", "text": "y"}],
    )
    base.update(over)
    return s.RulingRecord(**base)


def test_valid_ruling_with_both_dates_and_both_quarters():
    r = ruling()
    assert (r.quarter_by_decision, r.quarter_by_publication) == ("2026Q1", "2026Q2")


def test_quarter_of():
    assert [s.quarter_of(date(2026, m, 1)) for m in (1, 4, 7, 12)] == ["2026Q1", "2026Q2", "2026Q3", "2026Q4"]


@pytest.mark.parametrize(
    "over",
    [
        {"unknown_field": 1},  # extra=forbid
        {"court": "9C"},  # court must match the docket
        {"quarter_by_decision": "2026Q2"},  # quarters are computed, not typed
        {"quarter_by_publication": None},
        {"publication_date_source": None},  # an exact publication date has a source
        {"publication_date": None, "publication_date_source": None, "quarter_by_publication": None},  # still 'exact'
        {"text_hash": "0" * 64},  # hash must be the text's
        {"full_text": None, "text_source": None, "text_hash": None},  # no text without a reason (G5)
        {"full_text": "   ", "text_hash": s.sha256_text("   ")},  # empty text is refused (G4)
        {"considerations": [{"id": "c2", "text": "x"}]},  # ids c1, c2, ... in order
        {"docket": "8C 802/2023"},
    ],
)
def test_ruling_rules(over):
    with pytest.raises(ValidationError):
        ruling(**over)


def test_ruling_without_exact_publication_date():
    r = ruling(
        publication_date=None,
        publication_date_source=None,
        quarter_by_publication=None,
        publication_date_quality="approx_first_seen",
        publication_date_approx=date(2026, 4, 22),
        full_text=None,
        text_source=None,
        text_hash=None,
        text_missing_reason="not_in_hf",
    )
    assert r.publication_date is None and r.publication_date_approx == date(2026, 4, 22)


def test_suva_example_keeps_only_allowed_fields():
    ok = s.SuvaExampleRecord(
        docket="8C_129/2025",
        is_federal_court=True,
        decision_date=date(2025, 11, 11),
        quarter_label="2025 Q4",
        in_list=True,
        text_de="a",
        text_fr="b",
        bger_url="https://search.bger.ch/...",
        source_files=["judgements/BG_Urteile_2025_Q4_2026_Q1.xlsx", "judgements/Export_8C_129_2025.html"],
    )
    assert ok.in_list
    with pytest.raises(ValidationError):  # D-051: no author field can be stored
        s.SuvaExampleRecord(**ok.model_dump(), author="x")
    with pytest.raises(ValidationError):
        s.SuvaExampleRecord(**{**ok.model_dump(), "quarter_label": None})


def test_net_never_drops_without_reason():
    assert s.NetDecision(kept=True).kept
    with pytest.raises(ValidationError):
        s.NetDecision(kept=False)


def test_decision_top30_is_rank_le_30():
    base = dict(
        docket="9C_65/2025",
        decision_date=date(2025, 9, 1),
        score=88.0,
        score_source="judged",
        selected=True,
        rank=30,
        in_top30=True,
        threshold_version="t0",
        explanation_de="Leitentscheid, Beschwerde teilweise gutgeheissen.",
        signals_fired=["suva_party"],
        model_versions=[{"role": "judge", "version": "apertus"}],
        prompt_versions=[{"role": "triage", "version": "p0"}],
        mode="REPLAY",
    )
    assert s.DecisionRecord(**base).in_top30
    with pytest.raises(ValidationError):
        s.DecisionRecord(**{**base, "rank": 31})
    with pytest.raises(ValidationError):
        s.DecisionRecord(**{**base, "explanation_de": ""})  # every ruling has an explanation (G5)


def _objects(node):
    if isinstance(node, dict):
        if node.get("type") == "object" or "properties" in node:
            yield node
        for v in node.values():
            yield from _objects(v)
    elif isinstance(node, list):
        for v in node:
            yield from _objects(v)


def test_every_schema_object_forbids_extra_properties():
    for name, schema in s.json_schemas().items():
        for obj in _objects(schema):
            assert obj.get("additionalProperties") is False, name


def test_llm_outputs_are_strict_ready_and_prefixed_in_order():
    for name in s.LLM_OUTPUTS:
        schema = s.json_schemas()[name]
        for obj in _objects(schema):
            props = list(obj["properties"])
            assert sorted(obj.get("required", [])) == sorted(props), name  # strict mode: all required
            assert props == sorted(props), name  # alphabetical order = generation order (K3)


def test_triage_schema_restricts_evidence_to_ids_sent():
    schema = s.triage_call_schema(["c1", "c3"])
    assert schema["properties"]["a_evidence"]["items"]["enum"] == ["c1", "c3"]
    with pytest.raises(ValueError):
        s.triage_call_schema([])
