# ruff: noqa: E501  (prompt texts are kept on one line each, as in reading_prompts.py)
"""Apertus names the court's own legal statement and quotes it; code verifies the quote (experiment).

The question is the measured ``yes_strict`` reading (``reading_prompts.YES_STRICT``), with one addition: after
its Ja/Nein, Apertus must quote, word for word, the sentence of the reasoning where the court makes that
statement. The answer is read twice:

- ``f_stmt_p``: P(Ja) from the first token's log-probabilities (as the reading does; known to lean towards yes);
- ``f_stmt_verified``: ``f_stmt_p`` when code finds the quote in the ruling's reasoning, else 0. A "Ja" whose
  quote is not in the text, or is too short to carry a statement, counts for nothing (doctrine: Apertus
  interprets, code verifies);
- ``f_stmt_own``: ``f_stmt_verified`` when the quoted sentence does not itself just restate earlier case law
  ("nach der Rechtsprechung", "BGE ...", "selon la jurisprudence" ...), else 0.

The quote is kept for the explanation shown to the lawyer. A failed call gives ``None``, never a negative.
"""

from __future__ import annotations

import math
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

from src.triage import reading_prompts as p

VERSION = "statement_quote@1"
MIN_QUOTE = 40  # characters: shorter is not a statement
MATCH = 0.9  # share of the quote that must appear as one contiguous run of the reasoning

QUESTION = (
    p.YES_STRICT.rsplit("\n\n", 1)[0]
    + "\n\nAntworte in genau zwei Zeilen:\nZeile 1: Ja oder Nein\n"
    "Zeile 2: bei Ja den Satz der Erwägungen, in dem das Gericht diese Aussage trifft, wörtlich und in der Sprache des Urteils (höchstens 60 Wörter); bei Nein einen Bindestrich."
)

_RESTATES = re.compile(
    r"nach (?:der|ständiger|konstanter) rechtsprechung|gemäss (?:der )?rechtsprechung|praxisgemäss|rechtsprechungsgemäss|"
    r"\bbge \d|\batf \d|\bdtf \d|selon (?:la|une) jurisprudence|conformément à la jurisprudence|"
    r"secondo (?:la )?giurisprudenza|giusta la giurisprudenza"
)


def build_messages(ruling_text: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": p.SYS_L},
        {"role": "user", "content": f"{p.doc(p.sections(ruling_text))}\n\n{QUESTION}"},
    ]


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = text.replace("«", '"').replace("»", '"').replace("“", '"').replace("”", '"').replace("’", "'")
    return re.sub(r"\s+", " ", text).strip(" \"'")


def parse(content: str) -> tuple[str | None, str]:
    """(label, quote) from the two-line answer; label is "ja", "nein" or None."""
    lines = [ln.strip() for ln in (content or "").strip().splitlines() if ln.strip()]
    if not lines:
        return None, ""
    head = re.sub(r"^(zeile 1:)\s*", "", lines[0].casefold()).strip(" .:*")
    label = "ja" if head.startswith(("ja", "oui", "sì", "si")) else "nein" if head.startswith(("nein", "non")) else None
    quote = re.sub(r"^(zeile 2:)\s*", "", " ".join(lines[1:]), flags=re.I).strip()
    quote = re.sub(r"^[-–—]\s*", "", quote).strip()
    return label, (quote if label == "ja" else "")  # a quote after "Nein" is an explanation, not evidence


def verified(quote: str, reasoning: str) -> bool:
    """True when at least ``MATCH`` of the quote appears as one contiguous run of the reasoning."""
    q, r = _norm(quote), _norm(reasoning)
    if len(q) < MIN_QUOTE:
        return False
    if q in r:
        return True
    match = SequenceMatcher(None, r, q, autojunk=False).find_longest_match(0, len(r), 0, len(q))
    return match.size >= MATCH * len(q)


def restates_case_law(quote: str) -> bool:
    return bool(_RESTATES.search(_norm(quote)))


def p_yes(logprobs: dict[str, Any] | None) -> float | None:
    if not logprobs or not logprobs.get("content"):
        return None
    yes = no = 0.0
    for alt in logprobs["content"][0].get("top_logprobs", []):
        token = alt["token"].strip().strip(".:*").casefold()
        if token in {"ja", "oui", "si", "sì", "yes"}:
            yes += math.exp(alt["logprob"])
        elif token in {"nein", "non", "no"}:
            no += math.exp(alt["logprob"])
    return yes / (yes + no) if yes + no > 0 else None


def read_statement(client: Any, ruling_text: str, size: str = "large") -> dict[str, Any]:
    empty = {"label": None, "quote": "", "quote_ok": None, "f_stmt_p": None, "f_stmt_verified": None, "f_stmt_own": None}
    try:
        result = client.chat(
            build_messages(ruling_text), max_tokens=160, size=size, prompt_version=VERSION, logprobs=True, top_logprobs=20
        )
    except Exception:  # noqa: BLE001  a failed reading stays empty, never a "no"
        return empty
    prob = p_yes(result.logprobs)
    if prob is None:
        return empty
    label, quote = parse(result.content)
    reasoning = p.sections(ruling_text)["reasoning"] or ruling_text
    ok = bool(quote) and verified(quote, reasoning)
    own = ok and not restates_case_law(quote)
    return {
        "label": label,
        "quote": quote,
        "quote_ok": ok,
        "f_stmt_p": prob,
        "f_stmt_verified": prob if ok else 0.0,
        "f_stmt_own": prob if own else 0.0,
    }
