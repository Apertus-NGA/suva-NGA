"""The judge: one binary call per rubric criterion, with evidence checked by code (docs/JUDGE.md).

Nothing here talks to a network. `judge_one` takes a `transport` (the real one is `src.llm.judge.chat`;
tests pass a fake), builds the two messages, and turns the model's JSON into a verdict:

- PASS or FAIL is recomputed by code from the units the model listed (FAIL as soon as one unit is not ok);
- a FAIL must rest on a verbatim quote that code finds in the summary, the source or the reference;
- anything else (bad JSON, verdict that contradicts its own units, quote not found) is INVALID. An INVALID
  call is retried once, then counted apart. It is never read as a pass or as a fail.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from eval.judge.checks import sentences

HERE = Path(__file__).parent
RUBRIC: dict[str, Any] = json.loads((HERE / "rubric.json").read_text(encoding="utf-8"))
SYSTEM_PROMPT = (HERE / "system_prompt.txt").read_text(encoding="utf-8").strip()
VERSION: str = RUBRIC["version"]
CRITERIA: dict[str, dict[str, Any]] = {c["id"]: c for c in RUBRIC["criteria"]}
LANGUAGE_NAMES = {"de": "German", "fr": "French", "it": "Italian"}
MIN_FRAGMENT = 12  # characters: a shorter piece of a quote proves nothing
MAX_SKIPPED_SHARE = 0.1  # tone and language criteria: at most a tenth of the sentences may go unquoted
MAX_TOKENS = 24_000  # room for the reasoning of a model at its highest effort, plus the JSON

Transport = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class Item:
    """One summary to judge. `reference` and `examples` are only sent to the criteria that list them."""

    docket: str
    language: str  # "de" or "fr": the language the summary must be in
    summary: str
    source: str = ""
    source_language: str = ""
    reference: str = ""
    reference_language: str = ""
    examples: tuple[str, ...] = ()


@dataclass
class Verdict:
    criterion: str
    status: str  # PASS, FAIL or INVALID
    why_invalid: str = ""
    units: list[dict[str, Any]] = field(default_factory=list)
    reasoning: str = ""
    attempts: int = 1
    usage: dict[str, Any] = field(default_factory=dict)
    served_model: str = ""
    confirmation: str = ""  # for a FAIL that got a second reading: "kept", "overturned" or "not done"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["units", "reasoning", "verdict"],
    "properties": {
        "units": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["unit", "summary_quote", "source_quote", "ok", "note"],
                "properties": {
                    "unit": {"type": "string"},
                    "summary_quote": {"type": "string"},
                    "source_quote": {"type": "string"},
                    "ok": {"type": "boolean"},
                    "note": {"type": "string"},
                },
            },
        },
        "reasoning": {"type": "string"},
        "verdict": {"type": "string", "enum": ["PASS", "FAIL"]},
    },
}


def applicable(criterion_id: str, item: Item) -> bool:
    """A criterion runs only when the texts it needs are there (R1 needs Suva's reference summary)."""
    needs = CRITERIA[criterion_id]["inputs"]
    return not (("source" in needs and not item.source) or ("reference" in needs and not item.reference))


def _neutralise(text: str) -> str:
    """The texts are data (G4): a closing tag inside one must not end its block."""
    return re.sub(r"<(/?)(summary|source|reference|style_examples|criterion)\b", r"<\1\2_", text)


def criterion_block(c: dict[str, Any]) -> str:
    lines = [
        f"Criterion {c['id']}: {c['name']}",
        f"Question: {c['question']}",
        f"Units to check: {c['units']}",
        f"PASS when: {c['pass']}",
        "FAIL when at least one unit shows:",
        *[f"- {f}" for f in c["fail"]],
        f"Not part of this criterion (never a reason to fail here): {c['ignore']}",
        f"In case of doubt: {c['doubt']}",
        "Calibration examples (invented, about other texts):",
        *[f"- {e['text']} -> {e['verdict']} ({e['why']})" for e in c["examples"]],
    ]
    return "\n".join(lines)


def build_messages(criterion_id: str, item: Item) -> list[dict[str, str]]:
    """Documents first, the criterion last. One system message; the texts sit inside tags."""
    c = CRITERIA[criterion_id]
    language = LANGUAGE_NAMES[item.language]
    parts = []
    if "examples" in c["inputs"] and item.examples:
        shown = "\n\n---\n\n".join(_neutralise(e) for e in item.examples)
        parts.append(
            f'<style_examples language="{language}">\n{shown}\n</style_examples>\n'
            "These expert-written digests of OTHER rulings show the house style. Their content is irrelevant."
        )
    if "source" in c["inputs"]:
        src_language = LANGUAGE_NAMES.get(item.source_language, "unknown")
        parts.append(f'<source language="{src_language}">\n{_neutralise(item.source)}\n</source>')
    if "reference" in c["inputs"]:
        ref_language = LANGUAGE_NAMES.get(item.reference_language, "unknown")
        parts.append(
            f'<reference language="{ref_language}">\n{_neutralise(item.reference)}\n</reference>\n'
            "The reference is an expert's digest of the same ruling. Quote it in `source_quote`."
        )
    parts.append(f'<summary language="{language}">\n{_neutralise(item.summary)}\n</summary>')
    parts.append(
        f"The summary must be in {language}. Judge it on this single criterion.\n\n"
        f"<criterion>\n{criterion_block(c)}\n</criterion>\n\n"
        "Return the JSON object: `units`, then `reasoning`, then `verdict`."
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": "\n\n".join(parts)}]


def normalise(text: str) -> str:
    """What a quote is compared on: same letters, any spacing, any apostrophe or quotation mark."""
    text = unicodedata.normalize("NFKC", text).replace("­", "")
    text = re.sub(r"[‘’‚′`´]", "'", text)
    text = re.sub(r"[“”„«»‹›]", '"', text)
    text = re.sub(r"[‐-―]", "-", text)
    return re.sub(r"\s+", " ", text).strip()


def quote_found(quote: str, text: str) -> bool:
    """True when every piece of the quote (split at an ellipsis) stands in the text, word for word."""
    haystack = normalise(text)
    pieces = [p.strip(" \"'") for p in re.split(r"\s*(?:\.\.\.|…|\[…\]|\[\.\.\.\])\s*", normalise(quote))]
    pieces = [p for p in pieces if p]
    if not pieces:
        return False
    if len(pieces) == 1:
        return pieces[0] in haystack
    return all(len(p) >= MIN_FRAGMENT and p in haystack for p in pieces)


def _extract_json(raw: str) -> Any:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", raw)
    return json.loads(raw)


def read_answer(raw: str, criterion_id: str, item: Item) -> Verdict:
    """Turn the model's text into a verdict, or say why it cannot be used."""
    out = Verdict(criterion=criterion_id, status="INVALID")
    try:
        data = _extract_json(raw)
        units, said = data["units"], data["verdict"]
        out.reasoning = str(data.get("reasoning", ""))
    except (ValueError, KeyError, TypeError):
        out.why_invalid = "not the JSON object asked for"
        return out
    if said not in ("PASS", "FAIL") or not isinstance(units, list) or not units:
        out.why_invalid = "verdict or units missing"
        return out
    if not all(isinstance(u, dict) and isinstance(u.get("ok"), bool) for u in units):
        out.why_invalid = "a unit has no boolean `ok`"
        return out
    out.units = units
    computed = "PASS" if all(u["ok"] for u in units) else "FAIL"
    if computed != said:
        out.why_invalid = f"verdict {said} contradicts its own units ({computed})"
        return out
    if computed == "FAIL":
        where = CRITERIA[criterion_id]["evidence"]
        text = {"summary": item.summary, "source": item.source, "reference": item.reference}[where]
        key = "summary_quote" if where == "summary" else "source_quote"
        # A defect in the summary is shown by the failing unit itself. Something missing from the summary is
        # shown by the passage of the source or reference that holds it, which may sit in a neighbouring unit.
        proof = [u for u in units if not u["ok"]] if where == "summary" else units
        if not any(quote_found(str(u.get(key, "")), text) for u in proof):
            out.why_invalid = f"the FAIL quotes nothing verbatim from the {where}"
            return out
    # Clearing a summary on tone or language requires having looked at all of it. A FAIL already rests on a
    # verified quote, so it stands even when the model listed only the defective sentences.
    if computed == "PASS" and CRITERIA[criterion_id].get("cover_every_sentence"):
        skipped = sentences_not_examined(item.summary, units)
        if len(skipped) > MAX_SKIPPED_SHARE * max(1, len(sentences(item.summary))):
            out.why_invalid = f"{len(skipped)} sentence(s) of the summary were not examined"
            return out
    out.status = computed
    return out


def sentences_not_examined(summary: str, units: list[dict[str, Any]]) -> list[str]:
    """Sentences of the summary that no unit quotes. A judge that skips a sentence cannot clear it.

    A quote counts when it contains the sentence, is contained in it, or is the same sentence but for a few
    characters (models silently correct a typo when they copy).
    """
    quotes = [normalise(str(u.get("summary_quote", ""))) for u in units]
    quotes = [q for q in quotes if len(q) >= MIN_FRAGMENT]
    missing = []
    for sentence in sentences(summary):
        plain = normalise(sentence)
        if len(plain) < MIN_FRAGMENT:
            continue
        if not any(q in plain or plain in q or SequenceMatcher(None, q, plain).ratio() >= 0.85 for q in quotes):
            missing.append(sentence)
    return missing


def cache_key(model: str, effort: str, messages: list[dict[str, str]], repetition: int, attempt: int) -> str:
    blob = json.dumps([VERSION, model, effort, messages, repetition, attempt], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def confirmation_messages(criterion_id: str, item: Item, failing: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Second reading of a FAIL: the claims said to lack support are searched for again, one by one."""
    c = CRITERIA[criterion_id]
    claims = "\n".join(
        f'{n}. Statement of the summary: "{u.get("summary_quote", "")}"\n'
        f"   First reviewer's objection: {u.get('note', '')}"
        for n, u in enumerate(failing, start=1)
    )
    src_language = LANGUAGE_NAMES.get(item.source_language, "unknown")
    user = (
        f'<source language="{src_language}">\n{_neutralise(item.source)}\n</source>\n\n'
        f'<summary language="{LANGUAGE_NAMES[item.language]}">\n{_neutralise(item.summary)}\n</summary>\n\n'
        f"Criterion {c['id']}: {c['name']}. {c['question']}\n\n"
        "A first reviewer marked the statements below as not supported by the source. First reviewers miss "
        "support that is worded differently, translated, or placed in another part of the ruling. You are the "
        "second reviewer. For each statement, search the whole source again (facts and considerations, "
        "synonyms, translations, paraphrases) and decide independently.\n\n"
        f"{claims}\n\n"
        "Return the JSON object with exactly one unit per statement, in the same order: `unit` = the number, "
        "`summary_quote` = the statement, `ok` = true if the source supports it (same meaning, same figures, "
        "same actor, same strength), false if the source contradicts it or holds nothing of the kind. "
        "`source_quote` = the supporting passage copied word for word when `ok` is true, the closest or "
        "contradicting passage when it is false. `verdict` = PASS if every unit is ok, else FAIL."
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def confirm_fail(verdict: Verdict, item: Item, ask: Callable[[list[dict[str, str]], int], dict[str, Any]]) -> Verdict:
    """Keeps the FAIL unless the second reading clears every failing unit with a quote found in the source."""
    failing = [u for u in verdict.units if not u["ok"]]
    answer = ask(confirmation_messages(verdict.criterion, item, failing), 1)
    verdict.confirmation = "kept"
    try:
        second = _extract_json(answer.get("content") or "")["units"]
    except (ValueError, KeyError, TypeError):
        return verdict
    if not isinstance(second, list) or len(second) != len(failing):
        return verdict
    cleared = [
        isinstance(u, dict) and u.get("ok") is True and quote_found(str(u.get("source_quote", "")), item.source)
        for u in second
    ]
    for first, again, ok in zip(failing, second, cleared, strict=True):
        first["second_reading"] = {
            "cleared": ok,
            "source_quote": again.get("source_quote", ""),
            "note": again.get("note", ""),
        }
        if ok:
            first["ok"] = True
    if all(cleared):
        verdict.status, verdict.confirmation = "PASS", "overturned"
    return verdict


def judge_one(
    criterion_id: str,
    item: Item,
    transport: Transport,
    *,
    repetition: int = 0,
    cache: dict[str, Any] | None = None,
    model: str = "",
    effort: str = "",
) -> Verdict:
    """One criterion on one summary. At most two calls for the verdict (the second only if the first answer
    is unusable or the call failed), plus one confirmation call when a faithfulness criterion fails."""

    def ask(messages: list[dict[str, str]], attempt: int) -> dict[str, Any]:
        key = cache_key(model, effort, messages, repetition, attempt)
        if cache is not None and key in cache:
            return cache[key]
        answer = transport(
            messages=messages, schema=RESPONSE_SCHEMA, max_tokens=MAX_TOKENS, seed=repetition + attempt - 1
        )
        if cache is not None:
            cache[key] = answer
        return answer

    messages = build_messages(criterion_id, item)
    verdict = Verdict(criterion=criterion_id, status="INVALID", why_invalid="no answer")
    for attempt in (1, 2):
        try:
            answer = ask(messages, attempt)
        except Exception as exc:  # noqa: BLE001  a failed call is recorded, then tried once more
            verdict = Verdict(criterion=criterion_id, status="ERROR", why_invalid=f"{type(exc).__name__}: {exc}"[:300])
            verdict.attempts = attempt
            continue
        verdict = read_answer(answer.get("content") or "", criterion_id, item)
        verdict.attempts = attempt
        verdict.usage = answer.get("usage") or {}
        verdict.served_model = answer.get("model") or ""
        if verdict.status != "INVALID":
            break
    if verdict.status == "FAIL" and CRITERIA[criterion_id].get("confirm_fail"):
        try:
            verdict = confirm_fail(verdict, item, ask)
        except Exception:  # noqa: BLE001  no second reading: the first verdict stands
            verdict.confirmation = "not done"
    return verdict


def score(verdicts: dict[str, str]) -> dict[str, Any]:
    """One summary's result from its verdicts (criterion id -> PASS/FAIL/INVALID).

    `score` is the weighted share of passed criteria among those judged; `usable` says whether every critical
    criterion passed. Criteria with no verdict (INVALID answer, failed call) are left out of both and listed.
    """
    judged = {k: v for k, v in verdicts.items() if v in ("PASS", "FAIL")}
    weight = sum(CRITERIA[k]["weight"] for k in judged)
    got = sum(CRITERIA[k]["weight"] for k, v in judged.items() if v == "PASS")
    by_dimension = {}
    for name in RUBRIC["dimensions"]:
        ids = [k for k in judged if CRITERIA[k]["dimension"] == name]
        total = sum(CRITERIA[k]["weight"] for k in ids)
        passed = sum(CRITERIA[k]["weight"] for k in ids if judged[k] == "PASS")
        by_dimension[name] = round(passed / total, 4) if total else None
    critical = [k for k in judged if CRITERIA[k]["critical"]]
    return {
        "score": round(got / weight, 4) if weight else None,
        "by_dimension": by_dimension,
        "usable": bool(critical) and all(judged[k] == "PASS" for k in critical),
        "failed": sorted(k for k, v in judged.items() if v == "FAIL"),
        "invalid": sorted(k for k, v in verdicts.items() if v not in ("PASS", "FAIL")),
    }


def wilson(passed: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """95 % Wilson interval of a proportion (docs/EVAL.md §1, principle 5)."""
    if total == 0:
        return (0.0, 1.0)
    p = passed / total
    centre = p + z * z / (2 * total)
    spread = z * ((p * (1 - p) / total + z * z / (4 * total * total)) ** 0.5)
    return (
        round(max(0.0, (centre - spread) / (1 + z * z / total)), 4),
        round(min(1.0, (centre + spread) / (1 + z * z / total)), 4),
    )


def cohen_kappa(a: list[str], b: list[str]) -> float | None:
    """Agreement beyond chance between two lists of PASS/FAIL labels."""
    if not a or len(a) != len(b):
        return None
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    expected = sum((a.count(label) / n) * (b.count(label) / n) for label in ("PASS", "FAIL"))
    return None if expected == 1 else round((observed - expected) / (1 - expected), 4)
