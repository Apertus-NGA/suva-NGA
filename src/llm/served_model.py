"""Which models may answer us (AGENTS.md G3, event rule E1).

The allow-list has a single home, `MODELS.md` §1 ("Allow-list of served models"): this module reads it
there instead of repeating the ids. Accepted: the Apertus v1.5 ids of that list, in both forms (gateway id
and Hugging Face id), plus the `LLM_NAME` the runner set if it names an Apertus model. Anything else
served is rejected. A missing `x-keera-model` header is logged, never fatal (the judges' endpoint may
not send it).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MODELS_MD = REPO_ROOT / "MODELS.md"

_ALLOW_LIST_HEADING = "**Allow-list of served models**"
_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)?$")


class ServedModelError(RuntimeError):
    """A response came from a model outside the allow-list (G3)."""


def names_apertus(model_id: str | None) -> bool:
    """True if the id names an Apertus model, in any id form (case-insensitive `apertus`)."""
    return bool(model_id) and "apertus" in model_id.lower()


def canonical(model_id: str) -> str:
    """One form for both id forms: `swiss-ai/Apertus-v1.5-70B` and `apertus-v1-5-70b` -> `apertus-v1-5-70b`."""
    s = model_id.strip().lower()
    s = s.split("/", 1)[1] if "/" in s else s
    return s.replace(".", "-").replace("_", "-")


@lru_cache(maxsize=4)
def load_allow_list(path: Path = MODELS_MD) -> frozenset[str]:
    """The Apertus ids of the first bullet under "Allow-list of served models" in MODELS.md."""
    if not path.is_file():
        raise ServedModelError(f"{path.name} not found: it holds the allow-list of served models (G3)")
    text = path.read_text(encoding="utf-8")
    start = text.find(_ALLOW_LIST_HEADING)
    if start < 0:
        raise ServedModelError(f"{path.name} has no '{_ALLOW_LIST_HEADING}' section (G3)")
    first_bullet = next((line for line in text[start:].splitlines() if line.lstrip().startswith("- ")), "")
    ids = {
        token for token in re.findall(r"`([^`]+)`", first_bullet) if _ID_PATTERN.match(token) and names_apertus(token)
    }
    if not ids:
        raise ServedModelError(f"no model id found in the allow-list of {path.name} (G3)")
    return frozenset(ids)


@dataclass(frozen=True)
class ServedModelCheck:
    requested: str
    served: str | None  # the `model` field of the response
    header: str | None  # the `x-keera-model` header, when present
    accepted: bool
    mismatch: bool  # served differs from requested (another allowed Apertus id): logged and counted (T25)
    reason: str

    def as_log(self) -> dict:
        return {
            "requested": self.requested,
            "served": self.served,
            "header": self.header,
            "header_present": self.header is not None,
            "accepted": self.accepted,
            "mismatch": self.mismatch,
            "reason": self.reason,
        }


def check_served(
    requested: str,
    served: str | None,
    header: str | None,
    llm_name: str | None,
    allow_list: frozenset[str] | None = None,
) -> ServedModelCheck:
    """Check one response's served model against the allow-list. Never raises: the caller decides."""
    allowed = {canonical(m) for m in (allow_list if allow_list is not None else load_allow_list())}
    if llm_name and names_apertus(llm_name):
        allowed.add(canonical(llm_name))
    seen = [m for m in (served, header) if m]
    if not seen:
        return ServedModelCheck(requested, served, header, False, False, "no served model reported")
    outside = [m for m in seen if canonical(m) not in allowed]
    if outside:
        return ServedModelCheck(requested, served, header, False, True, "served model outside the allow-list")
    mismatch = any(canonical(m) != canonical(requested) for m in seen)
    reason = "another allowed Apertus id was served" if mismatch else "ok"
    if header is None:
        reason += "; no x-keera-model header"
    return ServedModelCheck(requested, served, header, True, mismatch, reason)
