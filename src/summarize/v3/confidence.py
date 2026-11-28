"""How far a v3 fiche was verified, as a number the expert can read and the reasons behind it.

    confidence(record, fiche) -> {"score": 0…100, "level": "high" | "medium" | "low", "reasons": [...], "parts": {...}}

It is computed by code from the fiche's own trace (no model call), so it replays exactly. It measures
verification, not truth: what share of what the fiche had to say is stated, what share of the written sentences
passed their checks, and how clearly the ruling's sentences entail them. The weights and the levels are set by
hand (28 Nov) and are not calibrated against expert ratings: the number orders fiches for review, it is not a
probability. A fiche the prompt writer (v2) wrote as a stand-in has no trace and gets no score ("unverified").
"""

from __future__ import annotations

from src.summarize.v3.types import Fiche, Record

VERSION = "confidence@1"
WEIGHTS = {"coverage": 0.4, "kept": 0.3, "entailment": 0.2, "first_pass": 0.1}
HIGH, MEDIUM = 85, 65
RECORD_REVIEW_CAP = 60  # the record itself could not be checked (no court rule or answer): never above this


def confidence(record: Record, fiche: Fiche) -> dict:
    required = [p.id for p in record.required()]
    kept = [s for s in fiche.sentences if s.status != "removed"]
    removed = [s for s in fiche.sentences if s.status == "removed"]
    stated = {i for s in kept for i in s.propositions}
    readings = [s.entailment for s in kept if s.entailment is not None]
    parts = {
        "coverage": len([i for i in required if i in stated]) / len(required) if required else 0.0,
        "kept": len(kept) / len(fiche.sentences) if fiche.sentences else 0.0,
        "entailment": sum(readings) / len(readings) if readings else 0.0,
        "first_pass": len([s for s in kept if s.status == "written"]) / len(kept) if kept else 0.0,
    }
    score = round(100 * sum(WEIGHTS[k] * v for k, v in parts.items()))
    reasons = []
    if record.status != "ok":
        score = min(score, RECORD_REVIEW_CAP)
        reasons.append("the court's rule or its answer could not be checked in the ruling")
    lost = [i for i in required if i not in stated]
    if lost:
        score = min(score, HIGH - 1)  # a fiche that lacks a required point is never "high"
        reasons.append(f"{len(lost)} of {len(required)} required points not stated ({', '.join(lost)})")
    if removed:
        reasons.append(
            f"{len(removed)} of {len(fiche.sentences)} written sentences failed their checks and were left out"
        )
    repaired = len([s for s in kept if s.status == "repaired"])
    if repaired:
        reasons.append(f"{repaired} sentences were rewritten once before they passed")
    if not reasons:
        reasons.append("every required point is stated and every sentence passed its checks")
    level = "high" if score >= HIGH else "medium" if score >= MEDIUM else "low"
    return {"version": VERSION, "score": score, "level": level, "reasons": reasons,
            "parts": {k: round(v, 3) for k, v in parts.items()}}  # fmt: skip
