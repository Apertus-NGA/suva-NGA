"""Layer 2, the Apertus relevance judge: the pure part (no I/O, no network). docs/LAYER2.md.

V1.0.0 is the scoring chain measured by the D-074 benchmark, byte for byte (docs/FINETUNE.md §1, §6):
- system = the versioned prompt; user = `Urteil <docket>:\\n\\n<text>\\n\\n<question>`;
- a text longer than 14,000 characters is sent as its first 12,000 + `\\n[…]\\n` + its last 2,000;
- one token, top 20 log-probabilities; P(Ja) sums the alternatives `ja`/`j`, P(Nein) `nein`/`nei`/`ne`
  (case and spaces ignored); score = P(Ja) / (P(Ja) + P(Nein)), as `experiments/finetune/scripts/
  06_benchmark_repeat.py:read_first_token`.
Added for G4, identity on every text without them: control-like tags `<|…|>` become `‹|…|›` (same length).
The logit ln P(Ja) − ln P(Nein) is the lossless score (`score_raw`): at two decimals, P(Ja) × 100 ties most of
the 8B's scores at 0.00 or 100.00 (docs/LAYER2_IMPLEMENTATION_PLANNING.md L2-D05).
"""

from __future__ import annotations

import hashlib
import json
import math
import re

from src.layer2.models import AnswerTokens, Prepared, Prompt, Reading, TextCap

CONTROL_TAG = re.compile(r"<\|([^|<>]{0,40})\|>")
ABSENT_LOGPROB = -99.0  # what read_first_token of the benchmark assumes for a token without a logprob


class NoYesNoAnswer(ValueError):
    """Neither Ja nor Nein among the first token's alternatives, or no log-probabilities: the call cannot give a
    score. The judgement is `failed` (L2_FAIL_NO_YESNO_TOKEN), never a negative (D-063)."""


def messages_sha256(messages: list[dict]) -> str:
    """The hash the client logs for a request's messages (src/llm/client.py `_sha`); the key of ops.blob."""
    return hashlib.sha256(canonical_messages(messages).encode("utf-8")).hexdigest()


def canonical_messages(messages: list[dict]) -> str:
    return json.dumps(messages, sort_keys=True, ensure_ascii=False)


def neutralise(text: str) -> tuple[str, int]:
    """Control-like tags become harmless look-alikes of the same length (G4: the ruling is data)."""
    return CONTROL_TAG.subn(lambda m: f"‹|{m.group(1)}|›", text)


def cut(text: str, cap: TextCap) -> tuple[str, int, str]:
    """(text sent, source characters sent, truncation label): the D-074 head/tail cut, recorded (G4)."""
    if len(text) <= cap.max_chars:
        return text, len(text), "none"
    tail = cap.max_chars - cap.head
    return text[: cap.head] + cap.marker + text[-tail:], cap.max_chars, f"head{cap.head}_tail{tail}"


def build_messages(
    docket: str, text: str, prompt: Prompt, cap: TextCap, neutralise_tags: bool = True
) -> tuple[list[dict[str, str]], Prepared]:
    """The two messages of one judgement and what was done to the text."""
    clean, replaced = neutralise(text) if neutralise_tags else (text, 0)
    sent, chars_sent, truncation = cut(clean, cap)
    user = prompt.user_template.replace("{docket}", docket).replace("{text}", sent)
    messages = [{"role": "system", "content": prompt.system_template}, {"role": "user", "content": user}]
    return messages, Prepared(chars_total=len(text), chars_sent=chars_sent, truncation=truncation, neutralised=replaced)


def read_first_token(logprobs: dict | None, tokens: AnswerTokens) -> Reading:
    """Score and log-probabilities from the first token's top_logprobs (D-074 chain)."""
    try:
        top = logprobs["content"][0]["top_logprobs"]  # type: ignore[index]
    except (TypeError, KeyError, IndexError) as exc:
        raise NoYesNoAnswer(f"no top_logprobs in the answer: {exc!r}") from exc
    if not top:
        raise NoYesNoAnswer("empty top_logprobs")
    yes, no = {t.lower() for t in tokens.yes}, {t.lower() for t in tokens.no}
    p_ja = p_nein = 0.0
    for t in top:
        tok = (t.get("token") or "").strip().lower()
        p = math.exp(t.get("logprob", ABSENT_LOGPROB))
        if tok in yes:
            p_ja += p
        elif tok in no:
            p_nein += p
    if p_ja + p_nein <= 0:
        raise NoYesNoAnswer("neither Ja nor Nein in the top alternatives")
    floor = min(t.get("logprob", ABSENT_LOGPROB) for t in top)
    lp_ja = math.log(p_ja) if p_ja > 0 else None
    lp_nein = math.log(p_nein) if p_nein > 0 else None
    # one side absent from the top 20: its log-probability is at most the floor, so the logit is a bound
    logit = (lp_ja if lp_ja is not None else floor) - (lp_nein if lp_nein is not None else floor)
    return Reading(
        p_ja=p_ja,
        p_nein=p_nein,
        p_yes=p_ja / (p_ja + p_nein),
        mass=p_ja + p_nein,
        logprob_yes=lp_ja,
        logprob_no=lp_nein,
        logit=logit,
        yes_no_in_top=lp_ja is not None and lp_nein is not None,
        top20_floor=floor,
        top_logprobs=[(t.get("token"), t.get("logprob")) for t in top],
    )


def score_0_100(reading: Reading) -> float:
    """The score experts read (D-063): 100 × P(Ja) / (P(Ja) + P(Nein)), two decimals."""
    return round(100 * reading.p_yes, 2)


def _percent(p: float) -> str:
    if p < 0.0005:
        return "< 0,1 %"
    if p > 0.9995:
        return "> 99,9 %"
    return f"{100 * p:.1f} %".replace(".", ",")


def _thousands(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def explanation_de(
    *,
    outcome: str,
    version: str,
    model: str | None,
    reading: Reading | None,
    prepared: Prepared | None,
    reason_label: str | None,
) -> str:
    """The German reason a lawyer reads (G5). Written by code: no model text at this step (L2-D12)."""
    if outcome == "ok" and reading is not None:
        text = (
            f"Apertus-Einschätzung (Modell {model}, Version {version}): Wahrscheinlichkeit «Ja» "
            f"{_percent(reading.p_yes)}. Über die Relevanz entscheidet erst die Rangierung."
        )
        if prepared is not None and prepared.truncation != "none":
            text += (
                f" Text gekürzt: {_thousands(prepared.chars_sent)} von {_thousands(prepared.chars_total)} "
                "Zeichen gelesen (Anfang und Schluss)."
            )
        return text
    label = reason_label or "Keine Beurteilung"
    return f"Keine Apertus-Einschätzung ({version}): {label}. Das Urteil bleibt in der Auswahl."


def fingerprint(
    component_version_id: str, prompt_sha256: str, model: str | None, text_sha256: str | None, repetition: int
) -> str:
    """SHA-256 over every input of one judgement: same inputs, same fingerprint (DB_DDL_PLANNING §10.1)."""
    payload = json.dumps(
        {"cv": component_version_id, "prompt": prompt_sha256, "model": model, "text": text_sha256, "rep": repetition},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
