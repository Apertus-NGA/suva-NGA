"""Layer 1: the recall-safe first filter before Apertus (docs/LAYER1.md §6, D-073).

Deterministic and code-only. Rules are declarative: each rule names a check, its effect (keep, drop, flag,
signal) and its reason code; the parameters of the checks are the configuration of the `layer1_filter`
version (D-064). Version V1.0.0 reproduces `src/courts.py` at commit 4c246a8 decision for decision (a test
asserts it): a ruling is kept when its court, letter and matter rubric are in the keep set, when the rubric
is missing on an allowed court, or when its text names Suva, an accident or military insurance term, or the
insurance-contract act outside the closed rubrics. Every rule that fires is recorded with its evidence: the
field it read and, for text, the character offsets in the stored ruling text.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from src.layer1.models import Check, Effect, Evidence, Layer1Config, RuleHit, Scope

SUBJECT_CHECKS: frozenset[Check] = frozenset(
    {"court_rubric_kept", "court_rubric_missing", "court_not_listed", "letter_not_listed", "court_rubric_out"}
)
REQUIRED_CHECKS = SUBJECT_CHECKS | {"text_accident_term", "text_contract_term"}
_APOSTROPHES = {"’": "'", "‘": "'", "ʼ": "'"}


@dataclass(frozen=True)
class RuleSpec:
    """A rule as the registry binds it to a `layer1_filter` version."""

    rule_code: str
    check: Check
    effect: Effect
    ordinal: int


@dataclass(frozen=True)
class Decision:
    in_suva_scope: Scope
    reason_code: str
    score_0_100: float | None
    rubric: str | None
    rubric_source: str | None
    subject: str
    text: str
    hits: tuple[RuleHit, ...] = field(default_factory=tuple)

    @property
    def kept(self) -> bool:
        return self.in_suva_scope == "potentially"


class Layer1Engine:
    """Evaluates one ruling against one `layer1_filter` version."""

    def __init__(self, config: Layer1Config, rules: Sequence[RuleSpec]):
        by_check = {r.check: r for r in rules}
        missing = REQUIRED_CHECKS - by_check.keys()
        if missing:
            raise ValueError(f"layer1_filter version lacks rules for checks: {sorted(missing)}")
        if len(by_check) != len(rules):
            raise ValueError("two rules of one layer1_filter version share a check")
        self.config = config
        self.rules = by_check
        self._accident = re.compile(config.accident_terms)
        self._contract = re.compile(config.contract_terms)
        self._closed = re.compile(config.closed_rubrics)

    # --- normalisation -------------------------------------------------------------------------------------

    def fold(self, text: str) -> tuple[str, list[int]]:
        """Normalised, case-folded text and, for each of its characters, the index in the original text."""
        out: list[str] = []
        index: list[int] = []
        norm = self.config.normalise
        for i, ch in enumerate(text):
            piece = ch
            if norm.apostrophes:
                piece = _APOSTROPHES.get(piece, piece)
            if norm.nbsp and piece == " ":
                piece = " "
            if norm.nfkc:
                piece = unicodedata.normalize("NFKC", piece)
            if norm.casefold:
                piece = piece.casefold()
            out.append(piece)
            index.extend([i] * len(piece))
        return "".join(out), index

    def rubric_key(self, rubric: str) -> str:
        folded, _ = self.fold(rubric.strip())
        return folded.rstrip("*").strip()

    def title_head(self, gegenstand: object) -> str | None:
        if not isinstance(gegenstand, str):
            return None
        head = gegenstand.strip()
        for stop in self.config.title_head.cut_at:
            head = head.split(stop, 1)[0]
        head = head.strip().rstrip(self.config.title_head.strip_trailing).strip()
        return head or None

    # --- decision --------------------------------------------------------------------------------------------

    def resolve_rubric(self, rubrics: Mapping[str, object], gegenstand: object) -> tuple[str | None, str | None]:
        for source in self.config.rubric_sources:
            value = self.title_head(gegenstand) if source == "gegenstand_head" else rubrics.get(source)
            if isinstance(value, str) and value.strip():
                return value, source
        return None, None

    def _hit(self, check: Check, evidence: Evidence) -> RuleHit:
        rule = self.rules[check]
        return RuleHit(rule_code=rule.rule_code, effect=rule.effect, evidence=evidence)

    def _search(self, pattern: re.Pattern[str], text: str, folded: str, index: list[int]) -> Evidence | None:
        found = pattern.search(folded)
        if not found:
            return None
        start = index[found.start()]
        end = index[found.end() - 1] + 1
        return Evidence(field="full_text", start=start, end=end, matched=text[start:end][:300])

    def decide(self, docket: str, rubrics: Mapping[str, object], gegenstand: object, text: object) -> Decision:
        hits: list[RuleHit] = []
        rubric, source = self.resolve_rubric(rubrics, gegenstand)
        if source == "gegenstand_head" and "rubric_from_gegenstand" in self.rules:
            hits.append(self._hit("rubric_from_gegenstand", Evidence(field="gegenstand", matched=rubric[:300])))

        # subject decision (exactly one subject check fires)
        head = docket.split("_", 1)[0]
        court = self.config.courts.get(head[0]) if len(head) == 2 else None
        rubric_ev = Evidence(field="rubric", source=source, matched=(rubric or "-")[:300])
        if court is None:
            subject = "wrong_court"
            hits.append(self._hit("court_not_listed", Evidence(field="docket", matched=head or docket[:300] or "-")))
        elif head[1] not in court.letters:
            subject = "wrong_letter"
            hits.append(self._hit("letter_not_listed", Evidence(field="docket", matched=head)))
        elif rubric is None:
            subject = "subject_missing"
            hits.append(self._hit("court_rubric_missing", Evidence(field="docket", matched=head)))
        elif self.rubric_key(rubric) in court.rubrics:
            subject = "kept_subject"
            hits.append(self._hit("court_rubric_kept", rubric_ev))
        else:
            subject = "subject_out"
            hits.append(self._hit("court_rubric_out", rubric_ev))

        # text decision
        if not isinstance(text, str) or not text.strip():
            text_reason = "text_absent"
        else:
            folded, index = self.fold(text)
            accident = self._search(self._accident, text, folded, index)
            contract = self._search(self._contract, text, folded, index)
            closed = self._closed.search(self.rubric_key(rubric)) if rubric else None
            if accident:
                hits.append(self._hit("text_accident_term", accident))
            if contract and closed:
                if "text_contract_term_blocked" in self.rules:
                    blocked = Evidence(field="rubric", source=source, matched=closed.group(0))
                    hits.append(self._hit("text_contract_term_blocked", blocked))
            elif contract:
                hits.append(self._hit("text_contract_term", contract))
            if accident:
                text_reason = "kept_text"
            elif contract and not closed:
                text_reason = "kept_contract"
            else:
                text_reason = "text_clear"

        keeps = [h for h in hits if h.effect == "keep"]
        if keeps:
            return Decision("potentially", keeps[0].rule_code, None, rubric, source, subject, text_reason, tuple(hits))
        drop = next(h for h in hits if h.effect == "drop")
        return Decision("out_of_scope", drop.rule_code, 0.0, rubric, source, subject, text_reason, tuple(hits))


def fingerprint(
    component_version_id: str,
    docket: str,
    decision_date: str,
    rubrics: Mapping[str, object],
    gegenstand: object,
    text_sha256: str | None,
) -> str:
    """SHA-256 over every input of a decision: the same inputs under the same version give the same value."""
    payload = {
        "cv": component_version_id,
        "docket": docket,
        "decision_date": decision_date,
        "rubrics": {k: rubrics[k] for k in sorted(rubrics)},
        "gegenstand": gegenstand,
        "text_sha256": text_sha256,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
