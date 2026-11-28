"""The refine loop: the fixed list of steps, in order, each patch verified before it is kept.

    result = refine(text, ctx)          # -> Result(text, trace, checks_before, checks_after, calls)

The order of steps is a list in code (`STEPS`); the model never chooses what runs next. A step that fails (a
model call that errors, an invalid answer, an exhausted budget) is recorded as `needs_review` and the loop goes on.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from src.summarize.refine import checks
from src.summarize.refine.draft import Draft, PatchRefused
from src.summarize.refine.model import ModelFailed
from src.summarize.refine.step import Candidate, Context, Outcome, Step

VERSION = "refine@1"


@dataclass
class Result:
    text: str
    draft: str
    trace: list[Outcome]
    checks_before: dict[str, int]
    checks_after: dict[str, int]
    calls: int

    def as_dict(self) -> dict:
        return {
            "version": VERSION,
            "text": self.text,
            "draft": self.draft,
            "calls": self.calls,
            "checks_before": self.checks_before,
            "checks_after": self.checks_after,
            "trace": [o.as_dict() for o in self.trace],
        }


def _resolve(draft: Draft, candidate: Candidate):
    """The patch with its sentence id taken from the current draft (ids change when a patch is kept)."""
    patch = candidate.patch
    if patch is None or candidate.sentence is None:
        return patch
    for sentence in draft.sentences:
        if sentence.text == candidate.sentence:
            return type(patch)(patch.op, sentence.id, patch.text, patch.span)
    raise PatchRefused("the sentence changed since the step read it")


def attempt(draft: Draft, candidate: Candidate, step: Step, ctx: Context) -> tuple[Draft, str | None]:
    """Apply one candidate's patch if it passes every guard. Returns (draft, None) or (old draft, why refused)."""
    try:
        patch = _resolve(draft, candidate)
        if patch is None:
            return draft, "no patch proposed"
        after = draft.apply(patch)
    except PatchRefused as exc:
        return draft, f"refused: {exc}"
    problems = candidate.verify(draft, after) if candidate.verify else []
    if problems:
        return draft, "refused: " + "; ".join(problems)
    before_checks = checks.run(draft.render(), ctx.language, ctx.source)
    after_checks = checks.run(after.render(), ctx.language, ctx.source)
    worse = checks.regressions(before_checks, after_checks, step.allow)
    if worse:
        return draft, "refused: would break " + ", ".join(worse)
    return after, None


def run_step(step: Step, draft: Draft, ctx: Context) -> tuple[Draft, Outcome]:
    start, calls_before = time.perf_counter(), ctx.model.calls
    try:
        candidates = step.propose(draft, ctx)
    except ModelFailed as exc:
        ms = int((time.perf_counter() - start) * 1000)
        return draft, Outcome(step.id, step.version, "needs_review", [], ctx.model.calls - calls_before, ms, str(exc))
    findings: list[dict] = []
    refused = 0
    for candidate in candidates:
        draft, why = attempt(draft, candidate, step, ctx)
        entry = candidate.as_dict()
        entry["accepted"] = why is None
        if why:
            entry["why_not"] = why
            refused += 1
        findings.append(entry)
    # passed: nothing found; corrected: every finding fixed and verified; needs_review: something left for a person
    status = "passed" if not candidates else ("needs_review" if refused else "corrected")
    ms = int((time.perf_counter() - start) * 1000)
    return draft, Outcome(step.id, step.version, status, findings, ctx.model.calls - calls_before, ms)


def refine(text: str, ctx: Context, steps: list[Step] | None = None) -> Result:
    from src.summarize.refine.steps import STEPS

    draft = Draft.from_text(text)
    before = checks.failing(checks.run(text, ctx.language, ctx.source))
    calls_start = ctx.model.calls
    trace: list[Outcome] = []
    for step in steps if steps is not None else STEPS:
        draft, outcome = run_step(step, draft, ctx)
        trace.append(outcome)
    final = draft.render()
    after = checks.failing(checks.run(final, ctx.language, ctx.source))
    return Result(final, text, trace, before, after, ctx.model.calls - calls_start)
