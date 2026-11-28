# ruff: noqa: E501  (test data: whole sentences of an invented ruling and its fiches, kept on one line to stay readable)
"""The summary engine (src/summarize/engine.py): v3 on an invented ruling, through the real client, no network.

MOCK DECLARED (G9): the gateway is `httpx.MockTransport` behind a real src.llm.client.LLMClient (store in tmp_path).
The fake endpoint answers by the system message of each request (record, write, entailment reading, repair, v2),
records every request, and never reaches a network. No database. The ruling is the invented one of
tests/test_refine.py. Assertions are on the EngineResult, on the messages actually sent and on the client's log.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import uuid
from datetime import date
from pathlib import Path

import httpx
import pytest

from src.ingest.judgements import export_refs
from src.llm.client import LLMClient, ReplayMiss
from src.llm.config import LLMConfig
from src.summarize import engine, examples
from src.summarize.engine_types import EngineResult, RulingSource
from src.summarize.extract import candidates as cand
from src.summarize.v3 import record as v3record
from src.summarize.v3 import verify as v3verify
from src.summarize.v3 import write as v3write
from src.summarize.v3.types import Proposition, Record
from src.summarize.v3.types import Sentence as V3Sentence
from tests.suva_forbidden import load, scan
from tests.test_refine import RULING

ROOT = Path(__file__).resolve().parents[1]
ENV = {"LLM_NAME": "apertus-v1-5-70b", "LLM_BASE_URL": "https://endpoint.invalid/v1", "LLM_API_KEY": "k"}
SOURCE = RulingSource(
    ruling_id=str(uuid.uuid5(uuid.NAMESPACE_URL, "test-ruling")),
    docket="8C_1/2025",
    decision_date=date(2025, 6, 3),
    language="de",
    text_id="text-1",
    text=RULING,
    title="Unfallversicherung (Kausalzusammenhang)",
)
SHOTS = {  # invented example fiches: tests never put Suva's texts in a committed file (D-031)
    "de": [{"docket": "8C_900/2025", "body": "Ein erfundenes Beispiel einer Zusammenfassung."}],
    "fr": [{"docket": "8C_900/2025", "body": "Un exemple inventé de résumé."}],
}
IDS = {c.text[:24]: c.id for c in cand.candidates(RULING).kept}
FACT, RULE, LIMIT, ANSWER = (
    IDS[k]
    for k in (
        "Der Versicherte stürzte ",
        "Die Leistungspflicht des",
        "Fällt dieser dahin, ende",
        "Die Vorinstanz hat die L",
    )
)
RECORD = {
    "a_point": "Ende der Leistungspflicht",
    "b_propositions": [
        {"a_id": ANSWER, "b_speaker": "court", "c_slot": "answer"},
        {"a_id": LIMIT, "b_speaker": "court", "c_slot": "condition"},
        {"a_id": RULE, "b_speaker": "court", "c_slot": "rule"},
        {"a_id": FACT, "b_speaker": "court", "c_slot": "fact"},
    ],
}  # code's record: P1 question (code), P2 fact, P3 rule, P4 condition, P5 answer
FICHE = {
    "de": [
        ("Streitig ist, ob die Suva ihre Leistungen zu Recht per 30. Juni 2023 eingestellt hat.", ["P1"]),
        ("Der Versicherte stürzte am 7. Mai 2023 von einer Leiter.", ["P2"]),
        (
            "Die Leistungspflicht des Unfallversicherers setzt einen natürlichen Kausalzusammenhang voraus (Art. 6 Abs. 1 UVG).",
            ["P3"],
        ),
        ("Fällt der Kausalzusammenhang dahin, endet die Leistungspflicht.", ["P4"]),
        ("Das Bundesgericht hält fest, dass die Vorinstanz die Leistungseinstellung zu Recht bestätigt hat.", ["P5"]),
    ],
    "fr": [
        (
            "Le litige porte sur le point de savoir si la Suva a supprimé à bon droit ses prestations au 30 juin 2023.",
            ["P1"],
        ),
        ("L'assuré est tombé d'une échelle le 7 mai 2023.", ["P2"]),
        (
            "Le droit aux prestations de l'assureur-accidents suppose un lien de causalité naturelle avec l'accident.",
            ["P3"],
        ),
        ("Lorsque ce lien disparaît, l'obligation de verser des prestations prend fin.", ["P4"]),
        (
            "Le Tribunal fédéral retient que la juridiction cantonale a confirmé à juste titre la suppression des prestations.",
            ["P5"],
        ),
    ],
}
V2 = {
    "de": "Der Versicherte stürzte von einer Leiter. Die Leistungspflicht des Unfallversicherers setzt einen natürlichen Kausalzusammenhang voraus (Art. 6 Abs. 1 UVG). Die Vorinstanz hat die Leistungseinstellung zu Recht bestätigt. Die Beschwerde wird abgewiesen.",
    "fr": "L'assuré est tombé d'une échelle. Le droit aux prestations suppose un lien de causalité naturelle (art. 6 al. 1 LAA). La juridiction cantonale a confirmé à juste titre la suppression des prestations. Le recours est rejeté.",
}


class FakeGateway:
    """A declared fake of the OpenAI-compatible endpoint (G9). It reads the system message to tell the call apart:
    v3's record, v3's write (language from the system message), the entailment reading (logprobs), v3's repair,
    else v2. `record`, `fiche` and `repair` can be replaced to make a part fail."""

    def __init__(self, record=None, fiche=None, repair=None, yes: float = -0.03) -> None:
        self.record = RECORD if record is None else record
        self.fiche = FICHE if fiche is None else fiche
        self.repair = repair
        self.yes = yes
        self.requests: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        system = body["messages"][0]["content"]
        logprobs, finish = None, "stop"
        if system.startswith(v3record.SYSTEM[:30]):
            content = self.record if isinstance(self.record, str) else json.dumps(self.record)
        elif system.startswith("You write the case-law digest (fiche)"):
            language = "fr" if "Swiss legal French" in system else "de"
            content = json.dumps({"a_sentences": [{"a_text": t, "b_propositions": p} for t, p in self.fiche[language]]})
        elif system.startswith("Du vergleichst zwei Texte"):
            content, finish = "Ja", "length"
            top = [{"token": "Ja", "logprob": self.yes}, {"token": "Nein", "logprob": -3.5}]
            logprobs = {"content": [{"token": "Ja", "logprob": self.yes, "top_logprobs": top}]}
        elif system.startswith(v3verify.SYSTEM[:40]):
            content = json.dumps({"a_sentence": self.repair or "Unbrauchbar."})
        else:
            language = "fr" if "in French" in system else "de"
            content = V2[language]
        choice = {"message": {"content": content}, "finish_reason": finish, "logprobs": logprobs}
        answer = {"model": ENV["LLM_NAME"], "choices": [choice], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
        return httpx.Response(200, json=answer, headers={"x-keera-model": ENV["LLM_NAME"]})

    def kinds(self) -> list[str]:
        out = []
        for body in self.requests:
            system = body["messages"][0]["content"]
            out.append(
                "record" if system.startswith(v3record.SYSTEM[:30])
                else "write" if system.startswith("You write the case-law digest (fiche)")
                else "entail" if system.startswith("Du vergleichst zwei Texte")
                else "repair" if system.startswith(v3verify.SYSTEM[:40])
                else "v2"
            )  # fmt: skip
        return out


def client(tmp_path: Path, gateway: FakeGateway | None, mode: str = "live") -> LLMClient:
    cfg = LLMConfig.from_env(mode, ENV if mode == "live" else {})
    transport = httpx.MockTransport(gateway) if gateway is not None else None
    return LLMClient(cfg, store_dir=tmp_path, transport=transport, sleep=lambda s: None)


def run(tmp_path: Path, gateway: FakeGateway, **kwargs) -> EngineResult:
    return engine.summarise(SOURCE, client(tmp_path, gateway), examples=SHOTS, **kwargs)


# --- the result -------------------------------------------------------------------------------------------------


def test_v3_writes_both_languages_from_one_shared_record_and_verifies_every_sentence(tmp_path):
    gateway = FakeGateway()
    result = run(tmp_path, gateway)
    assert set(result.fiches) == {"de", "fr"} and result.engine_version == engine.ENGINE_VERSION
    assert result.record_status == "ok"
    assert [(p.pid, p.slot, p.accepted) for p in result.propositions] == [
        ("P1", "question", True), ("P2", "fact", True), ("P3", "rule", True), ("P4", "condition", True), ("P5", "answer", True),
    ]  # fmt: skip
    assert result.propositions[2].sentence.startswith("Die Leistungspflicht des Unfallversicherers")  # copied by code
    assert result.propositions[2].label == "E.2.1"
    assert gateway.kinds().count("record") == 1  # one reading for both languages
    for language, outcome in (("de", "Die Beschwerde wird abgewiesen."), ("fr", "Le recours est rejeté.")):
        fiche = result.fiches[language]
        assert (fiche.language, fiche.writer, fiche.status) == (language, "v3", "ok")
        assert fiche.body.endswith(outcome) and fiche.body.count(outcome) == 1
        written = [s for s in fiche.sentences if s.status != "code"]
        assert [s.text for s in written] == [t for t, _ in FICHE[language]]
        flat = " ".join(fiche.body.split())  # every kept sentence reads as the body says it (claims, D-098)
        assert all(" ".join(s.text.split()) in flat for s in fiche.sentences if s.status != "removed")
        assert [s.ordinal for s in fiche.sentences] == [1, 2, 3, 4, 5, 6]
        assert all(s.entailment == pytest.approx(0.97, abs=0.01) for s in written)
        assert all(s.checks and set(s.checks.values()) <= {"pass", "not_applicable"} for s in written)
        assert set(written[0].checks) == set(engine.CHECK_CODES)
        assert written[2].label == "E.2.1" and written[2].quote.startswith("Die Leistungspflicht")
        code = fiche.sentences[-1]
        assert (code.status, code.text, code.propositions, code.checks) == ("code", outcome, (), {})
        assert fiche.confidence == 99.0 and fiche.band == "high" and fiche.repair_call_id is None  # 0.2 x P(Ja) 0.97
        write = next(c for c in result.calls if c.call_id == fiche.write_call_id)
        assert (write.purpose, write.language, write.prompt_version) == (
            "write",
            language,
            f"{v3write.VERSION}/{language}",
        )
    assert result.fiches["fr"].body != result.fiches["de"].body
    json.dumps(result.as_json(), default=str)  # the writer stores it as JSON


def test_every_call_is_recorded_once_with_its_purpose_prompt_version_and_the_messages_actually_sent(tmp_path):
    gateway = FakeGateway()
    result = run(tmp_path, gateway)
    calls = result.calls
    assert len(calls) == len(gateway.requests) == 13  # record, then per language one write and five readings
    assert sorted(c.purpose for c in calls) == sorted(
        ["record"] + ["write", "entail", "entail", "entail", "entail", "entail"] * 2
    )
    by_purpose = {c.purpose: c for c in calls}
    assert by_purpose["record"].prompt_version == v3record.READ_VERSION and by_purpose["record"].language is None
    assert by_purpose["entail"].prompt_version == "entail@1/v3" and by_purpose["entail"].params["max_tokens"] == 1
    assert by_purpose["entail"].params["top_logprobs"] == 20
    assert {c.language for c in calls if c.purpose in ("write", "entail")} == {"de", "fr"}
    sent = sorted(json.dumps(r["messages"], sort_keys=True) for r in gateway.requests)
    assert sorted(json.dumps(list(c.messages), sort_keys=True) for c in calls) == sent  # exactly what was sent
    for c in calls:
        assert uuid.UUID(c.call_id).version == 4 and c.error is None and not c.cache_hit
        assert (c.requested_model, c.served_model, c.size) == (ENV["LLM_NAME"], ENV["LLM_NAME"], "large")
        assert c.params["temperature"] == 0 and c.usage == {"prompt_tokens": 10, "completion_tokens": 5}
        assert (
            re.fullmatch(r"[0-9a-f]{64}", c.params["client_log"]["cache_key"]) and c.params["client_log"]["attempted"]
        )
        assert c.latency_ms is not None and c.started_at <= c.finished_at
    assert len({c.call_id for c in calls}) == len(calls)
    logged = [json.loads(line) for line in (tmp_path / "llm_calls.jsonl").read_text().splitlines()]
    assert len(logged) == 13 and all(r["trace"]["step"] == "summarise" for r in logged)
    assert {r["trace"]["ruling_id"] for r in logged} == {SOURCE.ruling_id}


def test_a_replayed_run_answers_every_call_from_the_cache_and_records_each_hit(tmp_path):
    live = run(tmp_path, FakeGateway())
    replayed = engine.summarise(SOURCE, client(tmp_path, None, mode="replay"), examples=SHOTS)
    assert {k: f.body for k, f in replayed.fiches.items()} == {k: f.body for k, f in live.fiches.items()}
    assert len(replayed.calls) == 13 and all(c.cache_hit and c.error is None for c in replayed.calls)
    assert all(c.requested_model == ENV["LLM_NAME"] for c in replayed.calls)
    other = RulingSource(**{**SOURCE.__dict__, "text": RULING.replace("Leiter", "Treppe")})
    with pytest.raises(ReplayMiss) as missed:  # a miss is never a fallback to v2
        engine.summarise(other, client(tmp_path, None, mode="replay"), examples=SHOTS)
    made = missed.value.engine_calls  # the calls already made travel with the exception (here: the missed record)
    assert [(c.purpose, c.cache_hit, c.error.split(":")[0]) for c in made] == [("record", False, "ReplayMiss")]
    assert made[0].params["client_log"] == {"attempted": False}


def test_a_replay_miss_v3_catches_as_a_sentence_problem_still_raises(tmp_path):
    """Red before the fix: v3 wraps a missed entailment reading in ModelFailed (verify.examine) and removes the
    sentence ("entailment not read: ... ReplayMiss"), so a replayed fiche differed from the live one."""
    live = run(tmp_path, FakeGateway())
    entail = next(c for c in live.calls if c.purpose == "entail" and c.language == "fr")
    key = entail.params["client_log"]["cache_key"]
    (tmp_path / "cache" / key[:2] / f"{key}.json").unlink()
    with pytest.raises(ReplayMiss, match="entail call entail@1/v3") as missed:
        engine.summarise(SOURCE, client(tmp_path, None, mode="replay"), examples=SHOTS)
    made = missed.value.engine_calls
    misses = [c for c in made if (c.error or "").startswith("ReplayMiss")]
    assert (misses[0].purpose, misses[0].language) == ("entail", "fr")  # then v3 tried a repair: missed as well
    assert {c.language for c in misses} == {"fr"} and [c.purpose for c in misses[1:]] == ["repair"]
    assert sum(c.cache_hit for c in made) == len(made) - len(misses) >= 6  # record, writes and readings before it


def test_an_engine_bug_after_the_calls_hands_the_calls_back(tmp_path, monkeypatch):
    def broken(*args, **kwargs):
        raise ValueError("unclassified v3 problem: invented")

    monkeypatch.setattr(engine, "_propositions", broken)
    with pytest.raises(ValueError, match="unclassified") as failed:
        run(tmp_path, FakeGateway())
    assert len(failed.value.engine_calls) == 13 and failed.value.engine_version == engine.ENGINE_VERSION


# --- the fallback to the prompt-written fiche (v2) ----------------------------------------------------------------


def test_a_failed_record_sends_both_languages_to_v2(tmp_path):
    gateway = FakeGateway(record="not json")
    result = run(tmp_path, gateway)
    assert result.record_status == "failed" and result.propositions == ()
    assert gateway.kinds()[:2] == ["record", "record"]  # the read and its one retry, then no v3 call
    assert "write" not in gateway.kinds() and gateway.kinds().count("v2") == 2
    for language in ("de", "fr"):
        fiche = result.fiches[language]
        assert (fiche.writer, fiche.status, fiche.sentences, fiche.confidence) == ("v2", "needs_review", (), None)
        assert fiche.body.startswith(V2[language][:30])
        assert fiche.problems[0].startswith("v3: record failed")
        write = next(c for c in result.calls if c.call_id == fiche.write_call_id)
        assert (write.purpose, write.language, write.prompt_version) == ("v2_write", language, "v2")
        assert write.params["max_tokens"] == engine.V2_MAX_TOKENS
    assert [c.prompt_version for c in result.calls if c.purpose == "record"] == [
        v3record.READ_VERSION,
        f"{v3record.READ_VERSION}/retry",
    ]
    rejected = [c.params["client_log"].get("invalid_answer") for c in result.calls if c.purpose == "record"]
    assert rejected == ["invalid answer: not valid JSON"] * 2  # both answers arrived and were rejected by the Model
    assert all("invalid_answer" not in c.params["client_log"] for c in result.calls if c.purpose != "record")


def test_a_failed_v3_fiche_sends_only_that_language_to_v2(tmp_path):
    german_for_french = {"de": FICHE["de"], "fr": FICHE["de"]}  # every French sentence is in German
    gateway = FakeGateway(fiche=german_for_french, repair="Die Leistungspflicht endet mit dem Kausalzusammenhang.")
    result = run(tmp_path, gateway)
    de, fr = result.fiches["de"], result.fiches["fr"]
    assert (de.writer, de.status) == ("v3", "ok")
    assert (fr.writer, fr.status, fr.sentences) == ("v2", "needs_review", ())
    assert fr.problems[0].startswith("v3: no usable fiche")
    repairs = [c for c in result.calls if c.purpose == "repair"]
    assert repairs and {c.language for c in repairs} == {"fr"}  # each refused sentence got its one repair
    assert all(c.prompt_version == "v3-verify@1/repair" for c in repairs)
    assert next(c for c in result.calls if c.call_id == fr.write_call_id).purpose == "v2_write"


def test_writer_v2_writes_both_fiches_without_a_record(tmp_path):
    gateway = FakeGateway()
    result = run(tmp_path, gateway, writer="v2")
    assert set(gateway.kinds()) == {"v2"} and result.record_status == "failed"
    assert all(f.writer == "v2" and f.problems[:1] != ("v3",) for f in result.fiches.values())
    with pytest.raises(ValueError, match="writer"):
        run(tmp_path, gateway, writer="extract")


def test_a_ruling_without_text_is_not_summarisable_and_calls_nothing(tmp_path):
    gateway = FakeGateway()
    with pytest.raises(engine.NotSummarisable):
        engine.summarise(RulingSource(**{**SOURCE.__dict__, "text": "  \n"}), client(tmp_path, gateway), examples=SHOTS)
    assert gateway.requests == []


# --- the shared check codes ---------------------------------------------------------------------------------------


def _record() -> Record:
    props = (
        Proposition("P1", "fact", "court", "facts", "S1", "Der Versicherte stürzte am 7. Mai 2023 von einer Leiter."),
        Proposition(
            "P2",
            "rule",
            "court",
            "E.2.1",
            "S4",
            "Die Leistungspflicht des Unfallversicherers setzt einen natürlichen Kausalzusammenhang voraus (Art. 6 Abs. 1 UVG).",
        ),
        Proposition(
            "P3",
            "answer",
            "court",
            "E.3",
            "S7",
            "Die Vorinstanz hat die Leistungseinstellung daher zu Recht bestätigt.",
        ),
    )
    return Record(props, "rejected", False, {"insured_female": False, "appellant": "insured", "insurer": "Suva"}, None)


RULING_DICT = {"text": RULING, "language": "de", "category": "uv", "docket": "8C_1/2025", "starred": None}


def test_checks_of_a_sentence_that_passed_and_of_one_removed_at_its_check():
    rec = _record()
    passed = engine.sentence_checks(
        V3Sentence("Der Versicherte stürzte von einer Leiter.", ("P1",), "written", [], 0.97), rec, "de", RULING_DICT
    )
    assert passed == {**dict.fromkeys(engine.CHECK_CODES, "pass"), "glossary_term": "not_applicable"}
    answer = engine.sentence_checks(V3Sentence("x", ("P3",), "written", [], 0.97), rec, "de", RULING_DICT)
    assert answer["outcome_restated"] == "not_applicable"  # the court's answer may say what is confirmed
    removed = V3Sentence(
        "Die Vorinstanz erwog, …",
        ("P2",),
        "removed",
        [
            "attempt 1: speaker: this is the Federal Supreme Court's own statement, but the sentence gives the lower court as its author",
            "attempt 2: entailment 0.40 below 0.9: the source does not say this",
        ],
        0.4,
    )
    checks = engine.sentence_checks(removed, rec, "de", RULING_DICT)
    assert checks["speaker"] == "fail" and checks["entailment"] == "not_applicable"  # code said no: not read
    assert checks["duplicate"] == "not_applicable" and checks["language"] == "pass"
    assert engine._entailment(removed) is None  # the kept (first) text was never read; 0.4 was the repair's
    two = engine.sentence_checks(V3Sentence("x", ("P1", "P2"), "written", [], 0.95), rec, "de", RULING_DICT)
    assert two["modal_strength"] == "not_applicable"  # two propositions: no modal reading by code


def test_checks_of_a_repeat_a_length_cut_and_a_sentence_without_proposition():
    rec = _record()
    repeat = engine.sentence_checks(
        V3Sentence("x", ("P1",), "removed", ["repeats an earlier sentence (P1)"], 0.97), rec, "de", RULING_DICT
    )
    assert repeat["duplicate"] == "fail" and repeat["entailment"] == "pass"
    cut = engine.sentence_checks(
        V3Sentence("x", ("P1",), "removed", ["left out for length"], 0.97), rec, "de", RULING_DICT
    )
    assert set(cut.values()) == {"pass", "not_applicable"} and cut["duplicate"] == "pass"
    orphan = engine.sentence_checks(
        V3Sentence("x", (), "removed", ["attempt 1: no proposition of the record behind this sentence"]),
        rec,
        "de",
        RULING_DICT,
    )
    assert orphan == {**dict.fromkeys(engine.CHECK_CODES, "not_applicable"), "entailment": "fail"}
    entail = engine.sentence_checks(
        V3Sentence(
            "x", ("P1",), "removed", ["attempt 1: entailment 0.50 below 0.9: the source does not say this"], 0.5
        ),
        rec,
        "de",
        RULING_DICT,
    )
    assert entail["entailment"] == "fail" and entail["speaker"] == "pass"


@pytest.mark.parametrize(
    ("problem", "code"),
    [
        ("written in German, not French", "language"),
        ("anonymisation placeholder left", "placeholder"),
        ("a placeholder in brackets: [Name]", "placeholder"),
        ("article 99 UVG not in the ruling", "new_identifier"),
        ("consideration 7.2 not in the ruling", "new_identifier"),
        ("number 4500 not in the ruling", "new_identifier"),
        ("stronger than the ruling: 'must' where the ruling says 'may'", "modal_strength"),
        ("weaker than the ruling: 'may' where the ruling says 'must'", "modal_strength"),
        ("glossary term missing: décision sur opposition", "glossary_term"),
        ("names Suva, but the ruling does not: the insurer is Generali", "suva_named"),
        ("states the outcome of the appeal, which code adds as the last sentence", "outcome_restated"),
        ("speaker: P2 is said by the lower court, not by the Federal Supreme Court", "speaker"),
        ("entailment 0.42 below 0.9: the source does not say this", "entailment"),
        ("entailment not read: call budget exhausted", "entailment"),
        ("no ruling text to check the new sentence against", "entailment"),
        ("proposition P9 is not in the record", "entailment"),
        ("repeats an earlier sentence (P2)", "duplicate"),
    ],
)
def test_every_problem_v3_writes_maps_to_one_shared_check_code(problem, code):
    assert engine._classify(problem) == code


def test_an_unknown_problem_is_never_mapped_silently():
    with pytest.raises(ValueError, match="unclassified"):
        engine._classify("something v3 never wrote")


def test_purposes_follow_v3s_prompt_tags():
    assert engine.purpose_of("record@1/again/retry") == "record"
    assert engine.purpose_of("v3-write@2/fr/retry") == "write"
    assert engine.purpose_of("v3-verify@1/missing") == "missing"
    assert engine.purpose_of("v3-verify@1/repair/retry") == "repair"
    assert engine.purpose_of("entail@1/v3") == "entail"


# --- Suva's examples (D-051, D-031) and the engine's imports ------------------------------------------------------


def test_the_example_fiches_hold_both_summaries_and_no_author_field(tmp_path):
    shots = examples.examples_for("8C_1/2025")
    assert [e["docket"] for e in shots["de"]] == list(examples.FEW_SHOT_DOCKETS) == ["8C_177/2025", "8C_224/2025"]
    assert all(e["body"].strip() and len(e["body"].split()) > 30 for lang in ("de", "fr") for e in shots[lang])
    assert examples.examples_for("8C_177/2025")["fr"][0]["docket"] == "8C_224/2025"  # never the target's own
    every = {ref.docket: examples.bodies(ref.docket) for ref in export_refs()}
    assert len(every) == 55 and all(b["de"] and b["fr"] for b in every.values())
    out = tmp_path / "examples.txt"  # scanned, then deleted with tmp_path: the texts are never committed
    out.write_text("\n".join(b[lang] for b in every.values() for lang in ("de", "fr")), encoding="utf-8")
    assert scan([out], load(ROOT / "judgements"), tmp_path) == []


def test_the_write_prompt_carries_suvas_examples_and_no_author_field(tmp_path):
    result = engine.summarise(SOURCE, client(tmp_path, FakeGateway()))  # examples read from judgements/
    write = next(c for c in result.calls if c.purpose == "write" and c.language == "fr")
    prompt = write.messages[-1]["content"]
    assert '<example ruling="8C_177/2025">' in prompt and '<example ruling="8C_224/2025">' in prompt
    dump = tmp_path / "calls.json"
    dump.write_text(json.dumps([list(c.messages) for c in result.calls], ensure_ascii=False), encoding="utf-8")
    assert scan([dump, tmp_path / "llm_calls.jsonl"], load(ROOT / "judgements"), tmp_path) == []


def test_the_engine_imports_nothing_from_the_database():
    code = (
        "import sys, src.summarize.engine, src.summarize.examples; "
        "print(sorted({m.split('.')[0] for m in sys.modules} & {'psycopg', 'suva_data', 'suva_app', 'src'}))"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "['src']"
    loaded = subprocess.run(
        [sys.executable, "-c", "import sys, src.summarize.engine; print(sorted(m for m in sys.modules if m.startswith('src.')))"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    assert "src.db" not in loaded and "src.layer2" not in loaded


def test_code_adds_the_outcome_sentence_and_the_bench_note_as_code_sentences():
    five = RULING.replace(
        "Bundesrichter Métral, Bundesrichterin Viscione,",
        "Bundesrichter Métral, Bundesrichterin Viscione, Bundesrichter Muster, Bundesrichterin Beispiel,",
    )  # invented names: a bench of five
    ruling = {**RULING_DICT, "text": five}
    body = "Der Versicherte stürzte von einer Leiter. Die Beschwerde wird abgewiesen.\n\nFünfer-Entscheid."
    assert engine._code_sentences(body, "de", ruling) == [
        ("Die Beschwerde wird abgewiesen.", 1),
        ("Fünfer-Entscheid.", 2),
    ]
    assert engine._code_sentences("Der Versicherte stürzte von einer Leiter.", "de", RULING_DICT) == []
