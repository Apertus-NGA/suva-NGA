"""Layer 3 without a database: the own splitter, label resolution, sections, title lines, claims, checks, quality,
the registry files and the engine contract (docs/LAYER3.md).

Synthetic texts and fiches only (no ruling text, no Suva text, no person, D-038, D-051).
"""

from __future__ import annotations

import json
import re
from datetime import date

import pytest

from src.db.pg import ROOT
from src.layer3 import segment as seg
from src.layer3.models import (
    CHECK_CODES,
    PresetConfig,
    PresetVersionEntry,
    SegmentConfig,
    SummariseConfig,
    VerifyConfig,
    VerifyRuleDefinition,
    rule_code,
)
from src.layer3.render import (
    FicheRejected,
    count_paragraphs,
    plan_text,
    quality_status,
    section_for,
    title_line,
)
from src.layer3.run import _call_engine, _is_replay_miss
from src.layer3.store import cache_key, error_code
from src.llm.client import ReplayMiss
from src.summarize.engine_types import CallRecord, EngineResult, Fiche, Proposition, RulingSource, Sentence

REG = ROOT / "src" / "layer3" / "registry"
PRESET = PresetConfig.model_validate(
    json.loads((REG / "presets" / "suva_house.json").read_text())["versions"][0]["config"]
)
PASS = dict.fromkeys(CHECK_CODES, "pass")

TEXT_DE = """Bundesgericht
Sachverhalt:
A. Die Beschwerdeführerin meldete einen Unfall.

Erwägungen:

1. Die Beschwerde ist zulässig.

2. Streitig ist der Rückfall.
2.1 Der Rückfall setzt einen Zusammenhang voraus.
7. Mai 2024 ist kein Erwägungstitel.
2.2 Die Vorinstanz hat den Zusammenhang verneint.

3. Die Beschwerde ist abzuweisen.

Demnach erkennt das Bundesgericht:
1. Die Beschwerde wird abgewiesen.
"""


def test_the_splitter_finds_numbered_considerations_with_offsets_and_parents():
    s = seg.split(TEXT_DE)
    assert s.status == "ok" and s.reasons_found
    assert [c.e_number for c in s.considerations] == ["1", "2", "2.1", "2.2", "3"]
    assert [c.depth for c in s.considerations] == [1, 1, 2, 2, 1]
    assert [c.parent_ordinal for c in s.considerations] == [None, None, 2, 2, None]
    for c in s.considerations:
        assert TEXT_DE[c.char_start : c.char_end] == c.content and c.content == c.content.strip()
    assert "7. Mai 2024" in s.considerations[2].content  # a number that does not continue the numbering stays text
    assert all("Demnach" not in c.content for c in s.considerations)  # the operative part is not a consideration
    assert 0 < s.coverage_ratio <= 1


def test_the_splitter_fails_without_a_reasoning_heading_or_without_numbers():
    assert seg.split("Ein Text ohne Erwägungen.\n1. Punkt.") == seg.Segmentation("failed", (), None, False)
    no_numbers = seg.split("Considérant en droit:\nLe recours est rejeté.\nPar ces motifs:\n1. Rejet.")
    assert (no_numbers.status, no_numbers.considerations, no_numbers.reasons_found) == ("failed", (), True)
    fr = seg.split("Faits:\nA.\nConsidérant en droit:\n1.\nLe recours.\n1.1 Recevable.\n2. Fond.\nPar ces motifs:\n1.")
    assert [c.e_number for c in fr.considerations] == ["1", "1.1", "2"]


@pytest.mark.parametrize(
    ("label", "number"),
    [("E.3.1", "3.1"), ("E. 3.1", "3.1"), ("consid. 2", "2"), ("Erw. 4.2", "4.2"), ("facts", None), (None, None)],
)
def test_a_label_resolves_to_the_courts_number_by_code(label, number):
    assert seg.label_number(label) == number


def _sentence(ordinal, text, pids, status="written", label=None, checks=None, **kw):
    return Sentence(ordinal, 1, text, tuple(pids), status, label=label, checks=PASS if checks is None else checks, **kw)


PROPS = {
    "P1": Proposition("P1", "fact", "court", "Sachverhalt.", "E.1", True),
    "P2": Proposition("P2", "rule", "court", "Regel.", "E.2.1", True),
    "P3": Proposition("P3", "condition", "court", "Anwendung.", "E.2.2", True),
    "P4": Proposition("P4", "answer", "court", "Antwort.", None, True),
}


def test_sections_follow_the_slot_and_code_sentences_are_the_outcome():
    assert section_for(_sentence(1, "a", ["P1"]), PROPS) == "facts"
    assert section_for(_sentence(1, "a", ["P2", "P1"]), PROPS) == "law"
    assert section_for(_sentence(1, "a", ["P3"]), PROPS) == "application"
    assert section_for(_sentence(1, "a", ["P4"]), PROPS) == "outcome"
    assert section_for(_sentence(1, "a", [], status="code", checks={}), PROPS) == "outcome"
    assert section_for(_sentence(1, "a", ["P9"]), PROPS) is None


def test_the_title_line_is_rendered_by_code_and_the_matter_only_in_the_rulings_language():
    kw = dict(docket="8C_493/2025", decision_date=date(2026, 4, 2), matter="Unfallversicherung,", preset=PRESET)
    assert (
        title_line("de", ruling_language="de", **kw) == "BGer-Urteil 8C_493/2025 vom 2. April 2026 – Unfallversicherung"
    )
    assert title_line("fr", ruling_language="de", **kw) == "Arrêt du TF 8C_493/2025 du 2 avril 2026"
    kw["decision_date"] = date(2026, 5, 1)
    assert title_line("fr", ruling_language="it", **kw) == "Arrêt du TF 8C_493/2025 du 1er mai 2026"


def _fiche(language="de", writer="v3", status="ok", sentences=None, body=None, write="w1"):
    sentences = sentences if sentences is not None else (
        _sentence(1, "Satz eins.", ["P1"], label="E.1"),
        _sentence(2, "Satz zwei.", ["P2"], label="E.9"),  # E.9 is not a consideration: its proposition's E.2.1 is
        _sentence(3, "Entfernt.", ["P3"], status="removed", checks={"entailment": "fail"}, why_not="not entailed"),
        _sentence(4, "Entfernt zwei.", ["P3"], status="removed", checks={}, why_not="duplicate of 2"),
        _sentence(5, "Die Beschwerde wird abgewiesen.", [], status="code", checks={}),
    )  # fmt: skip
    if body is None:  # the body the engine gives: the kept sentences, as they read in it
        body = " ".join(s.text for s in sentences if s.status != "removed") or "Ein Text (v2: ohne Sätze)."
        body = body.replace("Satz eins. ", "Satz eins.\n\n", 1)
    return Fiche(language, writer, status, body, sentences, write_call_id=write)


CITABLE = {"1": "c-1", "2": "c-2", "2.1": "c-21", "2.2": "c-22"}


def _plan(fiche, **kw):
    args = dict(docket="8C_1/2026", decision_date=date(2026, 4, 2), matter=None, ruling_language="de",
                propositions=PROPS, citable=CITABLE, preset=PRESET) | kw  # fmt: skip
    return plan_text(fiche, **args)


def test_kept_sentences_become_claims_with_citations_checks_and_status():
    plan = _plan(_fiche())
    assert [c.rendered_text for c in plan.claims] == ["Satz eins.", "Satz zwei.", "Die Beschwerde wird abgewiesen."]
    assert [c.ordinal for c in plan.claims] == [1, 2, 3]
    assert [c.section for c in plan.claims] == ["facts", "law", "outcome"]
    assert [c.citations for c in plan.claims] == [("c-1",), ("c-21",), ()]
    assert [c.status for c in plan.claims] == ["verified", "verified", "verified"]
    assert [c.model_text for c in plan.claims] == [
        "Satz eins.",
        "Satz zwei.",
        None,
    ]  # code's sentence is not the model's
    assert [k.check for k in plan.claims[0].checks] == list(CHECK_CODES)
    entail = next(k for k in plan.claims[0].checks if k.check == "entailment")
    assert set(entail.detail) >= {"entailment", "quote", "why_not", "label"}
    assert [(r.check, r.status, r.detail["attributed"]) for r in plan.removed] == [
        ("entailment", "fail", "engine"),
        ("entailment", "fail", "fallback"),  # the engine named no check at all
    ]
    assert (plan.word_count, plan.paragraph_count, plan.write_call_id) == (8, 2, "w1")


def test_a_sentence_removed_for_length_is_not_stored_as_a_failure():
    """v3 leaves a sentence out for length after it passed every check (verify.trim): no fail is claimed for it."""
    cut = _sentence(2, "Gekürzt.", ["P1"], status="removed", why_not="left out for length",
                    checks=PASS | {"glossary_term": "not_applicable"})  # fmt: skip
    repeat = _sentence(3, "Wieder.", ["P1"], status="removed", why_not="repeats an earlier sentence (P1)",
                       checks=PASS | {"duplicate": "fail"})  # fmt: skip
    plan = _plan(_fiche(sentences=(_sentence(1, "Satz.", ["P1"]), cut, repeat)))
    assert [(r.check, r.status, r.detail["attributed"], r.detail["ordinal"]) for r in plan.removed] == [
        ("entailment", "not_applicable", "none", 2),
        ("duplicate", "fail", "engine", 3),
    ]
    assert plan.removed[0].detail["removed_for"] == "left out for length"


def test_a_claim_not_found_in_the_body_is_flagged_with_the_engines_text():
    """The API carries citations to an expert edit by matching body sentences to rendered_text: a claim must read as
    the stored body does, or it is flagged (D-097)."""
    kept = _sentence(1, "Satz eins.", ["P1"])
    other = _sentence(2, "Satz (E. 9) zwei.", ["P2"])
    plan = _plan(_fiche(sentences=(kept, other), body="Satz eins.\n\nSatz zwei."))
    assert [c.status for c in plan.claims] == ["verified", "flagged"]
    entail = next(k for k in plan.claims[1].checks if k.check == "entailment")
    assert entail.detail["not_in_body"] is True and entail.detail["engine_text"] == "Satz (E. 9) zwei."
    assert plan.claims[1].rendered_text == plan.claims[1].model_text == "Satz (E. 9) zwei."


def test_a_failed_check_or_a_missing_proof_flags_the_claim_and_the_version():
    failed = _sentence(1, "Satz.", ["P1"], checks=PASS | {"speaker": "fail"})
    unproven = _sentence(2, "Ohne Prüfung.", ["P1"], checks={})
    orphan = _sentence(3, "Ohne Aussage.", ["P9"])
    plan = _plan(_fiche(sentences=(failed, unproven, orphan)))
    assert [c.status for c in plan.claims] == ["flagged", "flagged", "flagged"]
    ok = _plan(_fiche(sentences=(_sentence(1, "Satz.", ["P1"]),)))
    assert quality_status([ok, ok]) == "verified"
    assert quality_status([ok, plan]) == "flagged"
    v2 = _plan(_fiche(writer="v2", sentences=()))
    review = _plan(_fiche(status="needs_review", sentences=(_sentence(1, "Satz.", ["P1"]),)))
    assert v2.claims == () and quality_status([ok, v2]) == "flagged" and quality_status([review, ok]) == "flagged"


def test_a_fiche_without_text_or_without_its_call_is_never_stored():
    with pytest.raises(FicheRejected) as missing:
        _plan(_fiche(body="  ", status="failed"))
    assert missing.value.reason_code == "L3_LANGUAGE_MISSING"
    with pytest.raises(FicheRejected) as untraced:
        _plan(_fiche(write=None))
    assert untraced.value.reason_code == "L3_FICHE_UNTRACED"
    long = "x" * 301
    plan = _plan(_fiche(sentences=(_sentence(1, long, ["P1"]),)))
    claim = plan.claims[0]
    assert claim.rendered_text == long and len(claim.model_text) == 300 and claim.model_text.endswith("…")
    entail = next(k for k in claim.checks if k.check == "entailment")  # never NULL: NULL means an expert's claim
    assert entail.detail["model_text_truncated"] is True and entail.detail["model_text_full"] == long
    assert count_paragraphs("a\n\n\nb\n \nc") == 3


def _call(**kw):
    base = dict(call_id="c1", purpose="write", prompt_version="v3-write@2/de", language="de",
                messages=({"role": "user", "content": "x"},), response_text="y", requested_model="apertus-v1-5-70b",
                served_model="apertus-v1-5-70b", size="large", params={"temperature": 0, "max_tokens": 10}, usage={},
                latency_ms=1, cache_hit=False, error=None, started_at="2026-11-28T10:00:00+00:00",
                finished_at="2026-11-28T10:00:01+00:00")  # fmt: skip
    return CallRecord(**(base | kw))


def test_the_client_cache_key_is_taken_from_the_engines_copy_of_the_client_log():
    key = "a" * 64
    assert cache_key(_call(params={"max_tokens": 10, "client_log": {"cache_key": key}})) == (key, "client")
    formula, source = cache_key(_call(params={"max_tokens": 10, "client_log": {"attempted": False}}))
    assert source == "writer_formula" and re.fullmatch(r"[0-9a-f]{64}", formula)
    assert (error_code("timeout"), error_code("rate"), error_code("server"), error_code(None)) == (
        "WORK_TIMEOUT",
        "WORK_RATE_LIMITED",
        "WORK_HTTP_ERROR",
        None,
    )


def test_the_engine_gets_only_the_arguments_it_names():
    source = RulingSource("r", "8C_1/2026", date(2026, 4, 2), "de", "t", "text")
    built = []

    def with_client(src, client, *, writer="v3"):
        return (src.docket, client)

    def bare(src):
        return src.docket

    available = {"mode": "replay", "store": "s", "client": lambda: built.append(1) or "client!"}
    assert _call_engine(with_client, source, available) == ("8C_1/2026", "client!") and built == [1]
    assert _call_engine(bare, source, available) == "8C_1/2026" and built == [1]  # no client built for it
    wrapped = RuntimeError("engine")
    wrapped.__cause__ = ReplayMiss("no cached answer")
    assert _is_replay_miss(wrapped) and not _is_replay_miss(RuntimeError("other"))


def test_the_registry_files_validate_and_bind_one_rule_per_engine_check_code():
    from src.db.registry import StepVersionEntry

    segment = json.loads((REG / "segment.json").read_text())
    summarise = json.loads((REG / "summarise.json").read_text())
    verify = json.loads((REG / "verify.json").read_text())
    for reg, model in ((segment, SegmentConfig), (summarise, SummariseConfig), (verify, VerifyConfig)):
        for raw in reg["versions"]:
            ver = StepVersionEntry.model_validate(raw)
            model.model_validate(ver.config)
            assert ver.decision == "D-094" and ver.validation is None
    assert [r["rule_code"] for r in verify["rules"]] == [rule_code(c) for c in CHECK_CODES]
    assert verify["versions"][0]["rules"] == [rule_code(c) for c in CHECK_CODES]
    assert all(r["kind"] == "check" for r in verify["rules"]) and verify["step"] == "verify"
    for rule in verify["rules"]:
        VerifyRuleDefinition.model_validate(rule["definition"])
    assert summarise["versions"][0]["models"] == dict.fromkeys(("generator", "repair", "judge"), "apertus-v1-5-70b")
    preset = json.loads((REG / "presets" / "suva_house.json").read_text())
    entry = PresetVersionEntry.model_validate(preset["versions"][0])
    assert (preset["preset"], PresetConfig.model_validate(entry.config).perspective) == ("suva_house", 5)


def test_the_engine_and_the_writer_share_the_check_codes():
    engine = pytest.importorskip("src.summarize.engine")
    assert tuple(engine.CHECK_CODES) == CHECK_CODES
    assert engine.ENGINE_VERSION == json.loads((REG / "summarise.json").read_text())["versions"][0]["config"]["engine"]


def test_the_seed_labels_every_verify_rule_and_layer3_reason_in_german_and_french():
    sql = (ROOT / "src" / "db" / "sql" / "95_seed_reference.sql").read_text(encoding="utf-8")
    rows = dict(re.findall(r"\('((?:V3|L3)_[A-Z_]+)',\s*'(\w+)',\s*'[^']+(?:''[^']*)*',\s*'[^']+", sql))
    assert {rule_code(c) for c in CHECK_CODES} <= set(rows)
    assert {rows[rule_code(c)] for c in CHECK_CODES} == {"verify"}
    for code in ("L3_ENGINE_FAILED", "L3_REPLAY_MISS", "L3_LANGUAGE_MISSING", "L3_FICHE_UNTRACED"):
        assert rows[code] == "summary"


def test_the_default_profile_pins_the_layer3_steps():
    profiles = json.loads((ROOT / "src" / "db" / "seed" / "profiles.json").read_text())
    latest = profiles["profiles"][0]["versions"][-1]
    assert latest["version"] == [0, 4, 0] and latest["previous"] == [0, 3, 0]
    assert {k: tuple(v) for k, v in latest["steps"].items() if k in ("segment", "summarise", "verify")} == {
        "segment": (0, 1, 0),
        "summarise": (1, 0, 0),
        "verify": (1, 0, 0),
    }


def test_the_code_identity_covers_every_module_the_engine_loads():
    """F-09: the engine's prompts are not in ops.prompt_version, so the run's code hash must cover its import closure.
    Red before the fix: code_paths() named src/summarize/engine.py only."""
    import subprocess
    import sys

    from src.ingest.__main__ import REGISTRIES
    from src.layer3.run import code_paths

    code = (
        "import sys, pathlib, src.summarize.engine, src.summarize.examples\n"
        "root = pathlib.Path.cwd().resolve()\n"
        "for m in list(sys.modules.values()):\n"
        "    f = getattr(m, '__file__', None)\n"
        "    if f and pathlib.Path(f).resolve().is_relative_to(root / 'src'):\n"
        "        print(pathlib.Path(f).resolve().relative_to(root).as_posix())\n"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    loaded = {p for p in out.split() if p.startswith(("src/summarize/", "src/areas"))}
    assert "src/summarize/v3/write.py" in loaded and "src/summarize/refine/steps/facts.py" in loaded
    paths = set(code_paths())
    assert loaded <= paths, sorted(loaded - paths)
    assert "src/summarize/v2/glossary.json" in paths and "src/layer3/run.py" in paths
    registry = next(code for path, _, _, code in REGISTRIES if path.endswith("summarise.json"))
    assert loaded <= set(registry) and "src/summarize/engine_types.py" in registry


def _real_work(text_id="t-1"):
    from src.layer3.store import Work
    from tests.test_engine import SOURCE

    w = Work(SOURCE.ruling_id, SOURCE.docket)
    w.decision_date, w.language, w.text_id, w.text = SOURCE.decision_date, "de", text_id, SOURCE.text
    w.title = SOURCE.title
    return w


SEG_CFG = SegmentConfig.model_validate(json.loads((REG / "segment.json").read_text())["versions"][0]["config"])


def test_a_real_engine_result_is_planned_for_both_languages_with_the_question_in_the_facts(tmp_path):
    """No database, no network: src.summarize.engine on the invented ruling through the real client and the declared
    FakeGateway of tests/test_engine.py (G9), then the writer's plan. Red before SLOT_SECTION had `question`."""
    from src.layer3.run import summarise_one
    from src.summarize import engine
    from tests.test_engine import SHOTS, FakeGateway, client

    def real(source, client):
        return engine.summarise(source, client, examples=SHOTS)

    llm = client(tmp_path, FakeGateway())
    w = summarise_one(_real_work(), real, {"client": lambda: llm}, PRESET, SEG_CFG, "cv-segment")
    assert (w.outcome, w.reason_code, w.quality) == ("ready", None, "verified"), w.error
    question = next(p.pid for p in w.result.propositions if p.slot == "question")
    for plan in w.texts:
        first = plan.claims[0]
        assert first.section == "facts" and first.status == "verified"
        sentence = next(s for s in w.result.fiches[plan.language].sentences if s.ordinal == 1)
        assert sentence.propositions == (question,)
        assert all(" ".join(c.rendered_text.split()) in " ".join(plan.body.split()) for c in plan.claims)
        assert plan.claims[-1].section == "outcome" and plan.claims[-1].model_text is None
    assert any(c.citations for t in w.texts for c in t.claims)  # E.2.1 resolved by code to the own splitter


def test_an_unexpected_error_fails_the_ruling_and_keeps_the_calls_it_made():
    """A bug in the plan (an unknown slot) or in the engine fails that ruling only; the calls already made stay on
    the Work, so the writer stores one ops.llm_call each (red before: the first escaped and failed the run, the
    second lost its calls)."""
    from src.layer3.run import summarise_one

    made = (_call(call_id="c1"), _call(call_id="c2"))

    def odd_slot(source):
        sentence = _sentence(1, "Satz.", ["P1"])
        fiche = Fiche("de", "v3", "ok", "Satz.", (sentence,), write_call_id="c1")
        props = (Proposition("P1", "practice", "court", "S.", None, True),)
        return EngineResult(source.ruling_id, "v3@test", "ok", props, {"de": fiche, "fr": fiche}, made)

    w = summarise_one(_real_work(), odd_slot, {}, PRESET, SEG_CFG, "cv-segment")
    assert (w.outcome, w.reason_code) == ("failed", "L3_ENGINE_FAILED") and w.error.startswith("KeyError")
    assert w.result.calls == made

    def raises_after_two_calls(source):
        exc = ValueError("unclassified v3 problem")
        exc.engine_calls, exc.engine_version = made, "v3@test"
        raise exc

    w = summarise_one(_real_work(), raises_after_two_calls, {}, PRESET, SEG_CFG, "cv-segment")
    assert (w.outcome, w.reason_code, w.result.record_status, w.result.fiches) == (
        "failed", "L3_ENGINE_FAILED", "failed", {}
    )  # fmt: skip
    assert w.result.calls == made and w.result.engine_version == "v3@test"


def test_rejected_answers_are_found_by_the_engines_mark_or_by_their_retry():
    from src.layer3.store import rejected_answers

    first = _call(call_id="a", prompt_version="record@1/read", language=None)
    retry = _call(call_id="b", prompt_version="record@1/read/retry", language=None)
    marked = _call(call_id="c", params={"client_log": {"invalid_answer": "invalid answer: not valid JSON"}})
    fine = _call(call_id="d")
    assert rejected_answers((first, retry, marked, fine)) == {
        "a": "invalid answer, retried",
        "c": "invalid answer: not valid JSON",
    }
    assert error_code("ReplayMiss: no cached answer") == "L3_REPLAY_MISS"
