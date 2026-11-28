"""Triage step 3: six one-token readings of a ruling by Apertus, through the shared client (G2).

Each reading asks, in a different way, whether the ruling teaches something beyond its own case. The answer
is one token; the value is read from its log-probabilities, never from text the model writes (D-021 point 4).
Texts and builders are in ``reading_prompts.py``; the prompt versions below are the measured ones.
"""

from __future__ import annotations

import math
from typing import Any

from src.triage import reading_prompts as p

# name -> (prompt version, kind). Kind "yes": P(Ja). Kind "scale": probability-weighted level 1..5.
READINGS: dict[str, tuple[str, str]] = {
    "verdict": ("e1_nofacts", "yes"),
    "yes_strict": ("e13_yes_strict_v1", "yes"),
    "scale_generic": ("e13_scale_generic_v1", "scale"),
    "scale_area": ("e13_scale_area_v1", "scale"),
    "scale_headnote": ("e13_scale_headnote_v1", "scale"),
    "scale_tail": ("e13_scale_tail_v1", "scale"),
}
VERSION = "readings@1"
_YES = {"ja", "yes", "oui", "si", "sì"}
_NO = {"nein", "no", "non"}
_STRIP = ".\"':,*)("


def build_messages(name: str, ruling: dict[str, Any]) -> list[dict[str, str]]:
    """The two messages of one reading. ``ruling`` needs head, facts, reasoning, dispositive and uvmv."""
    if name == "verdict":
        system, user = p.SYS, f"{p.doc(ruling)}\n\n{p.RUBRIC}\n\n{p.Q}"
    elif name == "yes_strict":
        system, user = p.SYS_L, f"{p.doc(ruling)}\n\n{p.YES_STRICT}"
    elif name == "scale_generic":
        system, user = p.SYS_L, f"{p.doc(ruling)}\n\n{p.SCALE_GENERIC}"
    elif name == "scale_area":
        system, user = p.SYS_L, f"{p.doc(ruling)}\n\n{p.scale_area(ruling)}"
    elif name == "scale_headnote":
        system, user = p.SYS_L, f"{p.doc(ruling)}\n\n{p.SCALE_HEADNOTE}"
    elif name == "scale_tail":
        system, user = p.SYS_L, f"{p.tail_doc(ruling)}\n\n{p.SCALE_GENERIC}"
    else:
        raise KeyError(name)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def value_from_logprobs(logprobs: dict[str, Any] | None, kind: str) -> float | None:
    """P(Ja), or the expected level 1..5, from the first token's alternatives. None when none is an answer."""
    if not logprobs or not logprobs.get("content"):
        return None
    yes = no = 0.0
    levels = dict.fromkeys("12345", 0.0)
    for alt in logprobs["content"][0].get("top_logprobs", []):
        token = alt["token"].strip().strip(_STRIP).lower()
        prob = math.exp(alt["logprob"])
        if token in _YES:
            yes += prob
        elif token in _NO:
            no += prob
        elif token in levels:
            levels[token] += prob
    if kind == "yes":
        return yes / (yes + no) if yes + no > 0 else None
    total = sum(levels.values())
    if total <= 0 or any(v == 0.0 for v in levels.values()) and total < 0.5:
        return None
    return sum(int(k) * v for k, v in levels.items()) / total


def read_one(client: Any, name: str, ruling: dict[str, Any]) -> float | None:
    """One reading. A failed call returns None: it is counted by the caller and is never a "no" (D-021 point 7)."""
    version, kind = READINGS[name]
    try:
        result = client.chat(
            build_messages(name, ruling),
            max_tokens=1,
            prompt_version=version,
            logprobs=True,
            top_logprobs=20,
            first_token_only=True,
        )
    except Exception:  # noqa: BLE001  any failure of a reading leaves it empty
        return None
    return value_from_logprobs(result.logprobs, kind)


def read_all(client: Any, ruling: dict[str, Any]) -> dict[str, float | None]:
    """All six readings of one ruling."""
    return {name: read_one(client, name, ruling) for name in READINGS}
