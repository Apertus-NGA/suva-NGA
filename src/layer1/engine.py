"""Layer 1: the recall-safe first filter before Apertus (docs/LAYER1.md §6, D-073).

Deterministic and code-only. Rules are declarative: each rule names a check, its effect (keep, drop, flag,
signal) and its reason code; the parameters of the checks are the configuration of the `layer1_filter`
version (D-064). Version V1.0.0 reproduces `src/courts.py` at commit 4c246a8 decision for decision (a test
asserts it): a ruling is kept when its court, letter and matter rubric are in the keep set, when the rubric
is missing on an allowed court, or when its text names Suva, an accident or military insurance term, or the
insurance-contract act outside the closed rubrics.

Version V1.2.0 (D-083) appends two keeps after the V1.1.0 ordinals and only widens keep vocabularies, so it cannot
drop a ruling V1.1.0 keeps. The decisive rule of such a ruling can still change, through the widened vocabulary only:
a wider term or rubric can fire a keep of lower ordinal (docs/LAYER1.md §7.6). `text_unavailable` keeps a ruling
without text on any court (G5: never dropped on its docket prefix alone; the term checks cannot run), and
`title_rubric_kept` keeps a ruling on an allowed court and letter whose title head, cut at any of
`config.title_rubric.cut_at`, is in the court's keep set (audit F-06, F-08).

Every rule of the version is evaluated on every ruling and recorded with what it did (F-01, F-02): `fired`,
`not_fired`, `not_applicable` (a precondition failed, with why) or `blocked` (true but neutralised by another
rule), with the field it read and, for text, the character offsets in the stored ruling text. The decision is
the fired keep with the lowest ordinal, else the fired drop with the lowest ordinal (F-13). `Decision.hits`
holds the fired rules with their evidence, exactly as before the ledger existed (the golden digest reads it).
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from src.layer1.models import (
    Check,
    CourtKeepSet,
    Effect,
    Evidence,
    Layer1Config,
    NotApplicableWhy,
    Outcome,
    RuleEvaluation,
    RuleHit,
    Scope,
)

# The effect each check may have (the outcome table of the traceability plan, F-13). A rule whose kind differs is
# refused when the engine is built: a keep check bound as a drop would invert a decision silently.
CHECK_EFFECT: dict[Check, Effect] = {
    "court_not_listed": "drop",
    "letter_not_listed": "drop",
    "court_rubric_missing": "keep",
    "court_rubric_kept": "keep",
    "court_rubric_out": "drop",
    "rubric_from_gegenstand": "signal",
    "text_accident_term": "keep",
    "text_contract_term": "keep",
    "text_contract_term_blocked": "flag",
    "text_unavailable": "keep",
    "title_rubric_kept": "keep",
}
SUBJECT_CHECKS: frozenset[Check] = frozenset(
    {"court_rubric_kept", "court_rubric_missing", "court_not_listed", "letter_not_listed", "court_rubric_out"}
)
TEXT_CHECKS: frozenset[Check] = frozenset({"text_accident_term", "text_contract_term", "text_contract_term_blocked"})
REQUIRED_CHECKS = SUBJECT_CHECKS | TEXT_CHECKS  # V1.2.0's text_unavailable and title_rubric_kept are optional
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
    evaluations: tuple[RuleEvaluation, ...] = field(default_factory=tuple)

    @property
    def kept(self) -> bool:
        return self.in_suva_scope == "potentially"


class Layer1Engine:
    """Evaluates one ruling against one `layer1_filter` version."""

    def __init__(self, config: Layer1Config, rules: Sequence[RuleSpec]):
        for r in rules:
            if r.check not in CHECK_EFFECT:
                raise ValueError(
                    f"rule {r.rule_code}: unknown check {r.check!r} (no evaluator in src/layer1/engine.py)"
                )
            if r.effect != CHECK_EFFECT[r.check]:
                raise ValueError(
                    f"rule {r.rule_code}: check {r.check} is a {CHECK_EFFECT[r.check]} rule, not a {r.effect} rule"
                )
            if r.ordinal < 1:
                raise ValueError(f"rule {r.rule_code}: ordinal {r.ordinal} must be at least 1")
        by_check = {r.check: r for r in rules}
        missing = REQUIRED_CHECKS - by_check.keys()
        if missing:
            raise ValueError(f"layer1_filter version lacks rules for checks: {sorted(missing)}")
        if len(by_check) != len(rules):
            raise ValueError("two rules of one layer1_filter version share a check")
        if len({r.ordinal for r in rules}) != len(rules) or len({r.rule_code for r in rules}) != len(rules):
            raise ValueError("two rules of one layer1_filter version share an ordinal or a rule code")
        if "title_rubric_kept" in by_check and config.title_rubric is None:
            raise ValueError("check title_rubric_kept needs config.title_rubric (the characters that cut the title)")
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
            if norm.nbsp and piece == " ":
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

    def title_rubric_head(self, gegenstand: object) -> str | None:
        """The matter at the start of the title for `title_rubric_kept`: cut at the first of `title_rubric.cut_at`."""
        if not isinstance(gegenstand, str) or self.config.title_rubric is None:
            return None
        head = gegenstand.strip()
        for stop in self.config.title_rubric.cut_at:
            head = head.split(stop, 1)[0]
        return head.strip() or None

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

    def _eval(
        self,
        check: Check,
        outcome: Outcome,
        evidence_field: str | None = None,
        examined: str | None = None,
        match: Evidence | None = None,
        **detail: str | int | list[str] | None,
    ) -> RuleEvaluation:
        rule = self.rules[check]
        return RuleEvaluation(
            rule_code=rule.rule_code,
            effect=rule.effect,
            ordinal=rule.ordinal,
            outcome=outcome,
            evidence_field=evidence_field,
            examined_value=examined[:300] if examined is not None else None,
            char_start=match.start if match else None,
            char_end=match.end if match else None,
            matched_text=match.matched if match else None,
            detail=detail,
        )

    def _not_applicable(self, check: Check, why: NotApplicableWhy) -> RuleEvaluation:
        return self._eval(check, "not_applicable", why=why)

    def _search(self, pattern: re.Pattern[str], text: str, folded: str, index: list[int]) -> Evidence | None:
        found = pattern.search(folded)
        if not found:
            return None
        start = index[found.start()]
        end = index[found.end() - 1] + 1
        return Evidence(field="full_text", start=start, end=end, matched=text[start:end][:300])

    def _title_rubric(
        self,
        court: CourtKeepSet | None,
        letter_ok: bool,
        gegenstand: object,
        rubrics_key: str | None,
        hits: list[RuleHit],
    ) -> RuleEvaluation:
        if court is None:
            return self._not_applicable("title_rubric_kept", "court_not_listed")
        if not letter_ok:
            return self._not_applicable("title_rubric_kept", "letter_not_listed")
        head = self.title_rubric_head(gegenstand)
        if head is None:
            return self._not_applicable("title_rubric_kept", "gegenstand_absent")
        key = self.rubric_key(head)
        detail = {"pattern": rubrics_key, "rubric_key": key, "cut_at": self.config.title_rubric.cut_at}
        if key not in court.rubrics:
            return self._eval("title_rubric_kept", "not_fired", "gegenstand", head, **detail)
        title = Evidence(field="gegenstand", matched=head[:300])
        hits.append(self._hit("title_rubric_kept", title))
        return self._eval("title_rubric_kept", "fired", "gegenstand", head, title, **detail)

    def decide(self, docket: str, rubrics: Mapping[str, object], gegenstand: object, text: object) -> Decision:
        hits: list[RuleHit] = []
        evals: list[RuleEvaluation] = []
        rubric, source = self.resolve_rubric(rubrics, gegenstand)
        rubric_field = f"rubric:{source}" if source else None
        if "rubric_from_gegenstand" in self.rules:
            if source == "gegenstand_head":
                title = Evidence(field="gegenstand", matched=rubric[:300])
                hits.append(self._hit("rubric_from_gegenstand", title))
                evals.append(
                    self._eval("rubric_from_gegenstand", "fired", "gegenstand", rubric, title, rubric_source=source)
                )
            else:
                evals.append(
                    self._eval(
                        "rubric_from_gegenstand",
                        "not_fired",
                        rubric_field or "gegenstand",
                        rubric,
                        rubric_source=source,
                    )
                )

        # subject decision: exactly one subject check fires, the others are not_fired or not_applicable
        head = docket.split("_", 1)[0]
        court = self.config.courts.get(head[0]) if len(head) == 2 else None
        letter_ok = court is not None and head[1] in court.letters
        rubric_ev = Evidence(field="rubric", source=source, matched=(rubric or "-")[:300])
        letters = f"courts.{head[0]}.letters" if court is not None else None
        rubrics_key = f"courts.{head[0]}.rubrics" if court is not None else None
        if court is None:
            subject = "wrong_court"
            wrong = Evidence(field="docket", matched=head or docket[:300] or "-")
            hits.append(self._hit("court_not_listed", wrong))
            evals.append(self._eval("court_not_listed", "fired", "docket", wrong.matched, wrong, pattern="courts"))
            evals += [
                self._not_applicable(c, "court_not_listed")
                for c in ("letter_not_listed", "court_rubric_missing", "court_rubric_kept", "court_rubric_out")
            ]
        else:
            evals.append(self._eval("court_not_listed", "not_fired", "docket", head, pattern="courts"))
            if not letter_ok:
                subject = "wrong_letter"
                wrong = Evidence(field="docket", matched=head)
                hits.append(self._hit("letter_not_listed", wrong))
                evals.append(self._eval("letter_not_listed", "fired", "docket", head, wrong, pattern=letters))
                evals += [
                    self._not_applicable(c, "letter_not_listed")
                    for c in ("court_rubric_missing", "court_rubric_kept", "court_rubric_out")
                ]
            else:
                evals.append(self._eval("letter_not_listed", "not_fired", "docket", head, pattern=letters))
                if rubric is None:
                    subject = "subject_missing"
                    blank = Evidence(field="docket", matched=head)
                    hits.append(self._hit("court_rubric_missing", blank))
                    evals.append(
                        self._eval(
                            "court_rubric_missing",
                            "fired",
                            "docket",
                            head,
                            blank,
                            rubric_sources=list(self.config.rubric_sources),
                        )
                    )
                    evals += [
                        self._not_applicable(c, "rubric_missing") for c in ("court_rubric_kept", "court_rubric_out")
                    ]
                else:
                    evals.append(
                        self._eval("court_rubric_missing", "not_fired", rubric_field, rubric, rubric_source=source)
                    )
                    key = self.rubric_key(rubric)
                    fired, other = (
                        ("court_rubric_kept", "court_rubric_out")
                        if key in court.rubrics
                        else ("court_rubric_out", "court_rubric_kept")
                    )
                    subject = "kept_subject" if fired == "court_rubric_kept" else "subject_out"
                    hits.append(self._hit(fired, rubric_ev))
                    evals.append(
                        self._eval(fired, "fired", rubric_field, rubric, rubric_ev, pattern=rubrics_key, rubric_key=key)
                    )
                    evals.append(
                        self._eval(other, "not_fired", rubric_field, rubric, pattern=rubrics_key, rubric_key=key)
                    )
        if "title_rubric_kept" in self.rules:  # V1.2.0: the title head, cut wider, on an allowed court and letter
            evals.append(self._title_rubric(court, letter_ok, gegenstand, rubrics_key, hits))

        # text decision
        absent = not isinstance(text, str) or not text.strip()
        if "text_unavailable" in self.rules:  # V1.2.0: no text, so no term check could keep it (G5)
            chars = len(text) if isinstance(text, str) else 0
            if absent:
                hits.append(self._hit("text_unavailable", Evidence(field="full_text", matched=None)))
            evals.append(
                self._eval("text_unavailable", "fired" if absent else "not_fired", "full_text", text_chars=chars)
            )
        if absent:
            text_reason = "text_absent"
            evals += [self._not_applicable(c, "text_absent") for c in sorted(TEXT_CHECKS)]
        else:
            chars = len(text)
            folded, index = self.fold(text)
            accident = self._search(self._accident, text, folded, index)
            contract = self._search(self._contract, text, folded, index)
            closed = self._closed.search(self.rubric_key(rubric)) if rubric else None
            if accident:
                hits.append(self._hit("text_accident_term", accident))
                evals.append(
                    self._eval("text_accident_term", "fired", "full_text", None, accident, pattern="accident_terms")
                )
            else:
                evals.append(
                    self._eval(
                        "text_accident_term", "not_fired", "full_text", pattern="accident_terms", text_chars=chars
                    )
                )
            if contract and closed:
                blocked = Evidence(field="rubric", source=source, matched=closed.group(0))
                hits.append(self._hit("text_contract_term_blocked", blocked))
                evals.append(
                    self._eval(
                        "text_contract_term_blocked", "fired", rubric_field, rubric, blocked, pattern="closed_rubrics"
                    )
                )
                evals.append(
                    self._eval(
                        "text_contract_term",
                        "blocked",
                        "full_text",
                        None,
                        contract,
                        pattern="contract_terms",
                        blocked_by=self.rules["text_contract_term_blocked"].rule_code,
                        closed_rubric_match=closed.group(0)[:300],
                    )
                )
            elif contract:
                hits.append(self._hit("text_contract_term", contract))
                evals.append(
                    self._eval("text_contract_term", "fired", "full_text", None, contract, pattern="contract_terms")
                )
                if rubric is not None:  # the term matched, the rubric was read and is not closed
                    evals.append(
                        self._eval(
                            "text_contract_term_blocked",
                            "not_fired",
                            rubric_field,
                            rubric,
                            pattern="closed_rubrics",
                            rubric_source=source,
                        )
                    )
                else:  # the term matched, but there is no rubric that could close it
                    evals.append(
                        self._eval(
                            "text_contract_term_blocked",
                            "not_fired",
                            "full_text",
                            pattern="closed_rubrics",
                            rubric_source=None,
                        )
                    )
            else:
                evals.append(
                    self._eval(
                        "text_contract_term", "not_fired", "full_text", pattern="contract_terms", text_chars=chars
                    )
                )
                evals.append(
                    self._eval(
                        "text_contract_term_blocked",
                        "not_fired",
                        "full_text",
                        pattern="contract_terms",
                        text_chars=chars,
                    )
                )
            if accident:
                text_reason = "kept_text"
            elif contract and not closed:
                text_reason = "kept_contract"
            else:
                text_reason = "text_clear"

        ledger = tuple(sorted(evals, key=lambda e: e.ordinal))
        if len(ledger) != len(self.rules):  # a check without its evaluation is a bug of this function, never data
            raise RuntimeError(f"{docket}: {len(ledger)} evaluations for {len(self.rules)} rules")
        fired = [e for e in ledger if e.outcome == "fired"]
        keep = next((e for e in fired if e.effect == "keep"), None)
        if keep is not None:
            return Decision(
                "potentially", keep.rule_code, None, rubric, source, subject, text_reason, tuple(hits), ledger
            )
        drop = next((e for e in fired if e.effect == "drop"), None)
        if drop is None:  # the subject checks are exhaustive: one of them always fires
            raise RuntimeError(f"{docket}: no keep and no drop rule fired")
        return Decision("out_of_scope", drop.rule_code, 0.0, rubric, source, subject, text_reason, tuple(hits), ledger)


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
