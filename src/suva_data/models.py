"""The contract between source adapters and the rest of the pipeline."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Protocol

from .config import Window

DOCKET_RE = re.compile(r"^\d{1,2}[A-Z]_\d+/\d{4}$")


def normalise_docket(raw: str) -> str | None:
    """'8C-72-2025', '8C_72_2025', ' 8C_72/2025 ' -> '8C_72/2025'. None if it is not a BGer case number."""
    m = re.search(r"(\d{1,2}[A-Z])[_\-\s](\d+)[/_\-\s](\d{4})", raw or "")
    return f"{m[1]}_{int(m[2])}/{m[3]}" if m else None


def division_of(docket: str) -> str:
    return docket.split("_", 1)[0]


@dataclass(frozen=True)
class SourceRecord:
    """One ruling as one source describes it. Adapters emit these; they never write to the database."""

    source: str  # a key of config.SOURCE_TIER
    source_key: str  # unique and stable within the source (e.g. HF decision_id, entscheidsuche id, 'YYYYMMDD:docket')
    docket: str  # canonical form, see normalise_docket
    decision_date: str | None  # ISO 'YYYY-MM-DD'
    fields: dict = field(
        default_factory=dict
    )  # subset of config.CANONICAL_FIELDS; omit a key when unknown (never '' / False as a default)
    record: dict = field(default_factory=dict)  # the source's own record, JSON-serialisable, WITHOUT the full text
    text: str | None = None  # full text exactly as the source gives it (no cleaning), or None
    raw_file: str | None = None  # path of the snapshot file it came from, relative to SNAPSHOT_DIR


class SourceAdapter(Protocol):
    """Every source implements this. `fetch` is the only method allowed to use the network."""

    name: str

    def fetch(self, window: Window, extra_dockets: frozenset[str] = frozenset()) -> list[str]:
        """Download what is missing into SNAPSHOT_DIR/<name>/ (idempotent, resumable).

        Returns relative paths written."""
        ...

    def parse(self, window: Window, extra_dockets: frozenset[str] = frozenset()) -> Iterator[SourceRecord]:
        """Offline. Yield one SourceRecord per ruling decided in the window or whose docket is in extra_dockets.

        Must be deterministic (sorted by source_key) and must not drop duplicates or bad texts:
        that is the reconciler's job, so every row stays accounted for.
        """
        ...
