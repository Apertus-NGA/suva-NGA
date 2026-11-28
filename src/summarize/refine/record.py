"""The shared reading of a ruling: what the court decided and why, every item a sentence code copied from the ruling.

One Apertus call per ruling, used by the German and the French fiche alike (so both refine against the same
points). Code splits the ruling into passages. The model never copies text: for each item it names a passage from
a closed list and the opening words of the sentence; code finds that sentence (`evidence.find`) and copies it, or
moves the item to the passage that really holds it, or drops it. The rule may only come from a consideration where
a rule can stand (`evidence.rule_candidates`).

    record = read(source, parts, model)  -> {"question", "rules": [...], "answer", "status", "issues"}
"""

from __future__ import annotations

import json
import re

from src.summarize import finish
from src.summarize.refine import evidence
from src.summarize.refine.model import STRING, Model, ModelFailed, array, enum, obj  # noqa: F401

VERSION = "record@5"
CHECK_VERSION = "anchor@1"  # code's test of what can be a rule; changes the record without a new model call

# A rule the court applies is anchored in law: an article, a case-law reference, or the court's case-law formula.
# Measured on the cached run-r3 records: the model sometimes lists a sentence of the facts or of the parties'
# arguments as a "rule" ("Il ricorrente contesta in questa sede…"); none of those carries an anchor.
_ANCHOR = re.compile(
    r"\b(?:BGE|ATF|DTF)\s+\d+|\b(?:SVR|RKUV|SZS)\b|\bUrteil(?:e)?\s+\d[A-Z]_\d+|\barrêts?\s+\d[A-Z]_\d+"
    r"|\bsentenz[ae]\s+\d[A-Z]_\d+|Rechtsprechung|jurisprudence|giurisprudenza|praxisgemäss|nach ständiger"
    r"|selon (?:la|une) (?:jurisprudence|pratique)|setzt voraus|suppose que|presuppone",
    re.IGNORECASE,
)


def anchored(quote: str) -> bool:
    return bool(evidence.articles(quote) or _ANCHOR.search(quote))


MAX_RULES = 3

TASK = (
    "Point at these sentences of the ruling:\n"
    "- a_question: where the court states what is in dispute before it ('Streitig ist', 'Est litigieux', "
    "'Le litige porte sur', 'È litigioso', 'Zu prüfen ist').\n"
    "- b_rules: the legal rules the court states and applies to decide this case, one to three: general statements "
    "a lawyer can reuse (a test, a condition, a presumption, the meaning of an article), not the facts. Only from "
    "the considerations listed for rules. Give each rule once, the most important first.\n"
    "- c_answer: where the court applies the rule to the facts of this case and gives its reason (why the "
    "appeal fails or succeeds); not the sentence that only states the outcome ('Le recours doit être rejeté', "
    "'Die Beschwerde ist abzuweisen').\n"
    "For each: a_label (the passage), b_opening (the first eight to twelve words of the sentence, exactly), "
    "c_sentences ('1', or '2' when the point needs the next sentence too)."
)


def _pointer(labels: list[str]) -> dict:
    return obj({"a_label": enum(labels), "b_opening": STRING, "c_sentences": enum(["1", "2"])})


def schema(parts: dict[str, str], candidates: list[str]) -> dict:
    reasoning = evidence.considerations(parts)
    return obj(
        {
            "a_question": _pointer(reasoning),
            "b_rules": array(_pointer(candidates), MAX_RULES),
            "c_answer": _pointer(reasoning),
        }
    )


def messages(parts: dict[str, str], candidates: list[str]) -> list[dict]:
    return evidence.messages(parts, f"{TASK}\nConsiderations listed for rules: {', '.join(candidates)}.")


def _check(item: dict | None, parts: dict[str, str], allowed: list[str], issues: list[str], name: str) -> dict | None:
    if not item:
        issues.append(f"{name}: missing")
        return None
    scope = {label: parts[label] for label in allowed if label in parts}
    found = evidence.find(item["b_opening"], scope, item["a_label"], int(item["c_sentences"]))
    if found is None:
        issues.append(f"{name}: no sentence of the allowed passages opens with {item['b_opening'][:60]!r}")
        return None
    out = {"label": found[0], "quote": found[1]}
    if found[0] != item["a_label"]:
        out["moved_from"] = item["a_label"]
    return out


def validate(answer: dict, parts: dict[str, str], candidates: list[str]) -> dict:
    reasoning = evidence.considerations(parts)
    issues: list[str] = []
    rules = []
    for n, item in enumerate(answer["b_rules"]):
        rule = _check(item, parts, candidates, issues, f"rule {n}")
        if rule and not anchored(rule["quote"]):
            issues.append(f"rule {n}: no legal anchor (article, case law), not a rule: {rule['quote'][:60]!r}")
        elif rule and rule["quote"] not in [r["quote"] for r in rules]:
            rules.append(rule)
    if not answer["b_rules"]:
        issues.append("rules: none given")
    record = {
        "version": VERSION,
        "check": CHECK_VERSION,
        "question": _check(answer["a_question"], parts, reasoning, issues, "question"),
        "rules": rules,
        "answer": _check(answer["c_answer"], parts, reasoning, issues, "answer"),
        "issues": issues,
    }
    record["status"] = "ok" if rules and record["answer"] else "needs_review"
    return record


def read(source: str, parts: dict[str, str], model: Model) -> dict:
    """The checked record: one call, and one repair call naming what failed. Never an unchecked item."""
    merits = finish.outcome_kind(source) in ("rejected", "admitted", "partial")
    candidates, excluded = evidence.rule_candidates(parts, merits)
    sent = messages(parts, candidates)
    shape = schema(parts, candidates)
    best: dict | None = None
    for attempt in range(2):
        try:
            answer = model.ask(sent, "ruling_record", shape, f"{VERSION}/{attempt}", max_tokens=1200)
        except ModelFailed as exc:
            best = best or {
                "version": VERSION,
                "status": "needs_review",
                "issues": [str(exc)],
                "rules": [],
                "facts": [],
            }
            break
        record = validate(answer, parts, candidates)
        if best is None or len(record["issues"]) < len(best["issues"]):
            best = record
        if record["status"] == "ok" and record["question"] is not None:
            break  # the points refine relies on are checked
        listed = "\n".join(f"- {issue}" for issue in record["issues"])
        sent = [
            *sent[:2],
            {"role": "assistant", "content": json.dumps(answer, ensure_ascii=False)},
            {"role": "user", "content": f"These items failed the check:\n{listed}\nAnswer again with the whole "
             "record. Copy the opening words exactly as they stand in the passage you name."},
        ]  # fmt: skip
    assert best is not None
    best["rule_candidates"], best["excluded"] = candidates, excluded
    return best
