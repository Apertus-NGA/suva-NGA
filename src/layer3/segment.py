"""segment V0.1.0, the own splitter: the court's numbered considerations of one ruling text (DB plan §8.3).

The heading rules are the v3 engine's evidence passages (summarize/v3@a4a1504, src/summarize/refine/evidence.py),
ported here so the splitter and the engine read the same numbering: a reasoning heading opens the considerations,
the operative part closes them, and a number at the start of a line becomes a heading only when it continues the
numbering (2.1 -> 2.2, 2.1.1 or 3), so "7. Mai 2024" inside consideration 3 stays text. Labels such as "E.3.1" that
the engine attaches to a sentence resolve to a consideration of this segmentation by code (G1, `label_number`).

`split` is pure; `store` writes corpus.segmentation and corpus.consideration (status ok when considerations are
found, failed with consideration_count 0 otherwise), or reuses the segmentation already stored for the same text
and component version (its id is uuid5('segmentation|<text_id>|<component_version_id>')).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import psycopg

from src.db.pg import sha256_text, uuid5

_REASONS = re.compile(
    r"(?mi)^[ \t]*(?:in Erwägung,?|Erwägungen[ \t]*:|Considérant en (?:fait et en )?droit[ \t]*:|Considérant[ \t]*:"
    r"|Considerando in diritto[ \t]*:|Considerando[ \t]*:|Diritto[ \t]*:)"
)
_OPERATIVE = re.compile(r"(?mi)^[ \t]*(?:Demnach (?:erkennt|verfügt|beschliesst)|Par ces motifs|Per questi motivi)")
_NUMBER = re.compile(r"(?m)^[ \t]*(\d{1,2}(?:\.\d{1,2})*)\.?(?=\s)")
_LABEL = re.compile(r"^\s*(?:E|Erw|consid|cons)\.?\s*(\d{1,2}(?:\.\d{1,2})*)\.?\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Consideration:
    ordinal: int  # 1..n in reading order
    e_number: str  # the court's numbering, "2.1"
    depth: int  # number of levels: "2" -> 1, "2.1" -> 2 (citable at depth >= 1)
    parent_ordinal: int | None
    char_start: int  # offsets in the ruling text, the stripped consideration
    char_end: int
    content: str


@dataclass(frozen=True)
class Segmentation:
    status: Literal["ok", "failed"]
    considerations: tuple[Consideration, ...]
    coverage_ratio: float | None  # characters of the considerations / length of the reasoning part
    reasons_found: bool


def _follows(previous: list[int] | None, number: list[int]) -> bool:
    """True when `number` can be the next consideration heading after `previous` (2.1 -> 2.2, 2.1.1 or 3)."""
    if previous is None:
        return len(number) == 1
    if number == [*previous, 1]:
        return True
    return any(
        len(number) == level + 1 and number[:level] == previous[:level] and number[level] == previous[level] + 1
        for level in range(len(previous))
    )


def _stripped(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def split(text: str) -> Segmentation:
    """The numbered considerations of a ruling text, in reading order, with offsets into `text`."""
    operative = _OPERATIVE.search(text)
    end = operative.start() if operative else len(text)
    reasons = _REASONS.search(text, 0, end)
    if reasons is None:
        return Segmentation("failed", (), None, False)
    previous: list[int] | None = None
    starts: list[tuple[int, list[int]]] = []
    for match in _NUMBER.finditer(text, reasons.end(), end):
        number = [int(n) for n in match.group(1).split(".")]
        if _follows(previous, number):
            starts.append((match.start(), number))
            previous = number
    if not starts:  # a reasoning heading without numbered considerations (the engine's passages() raises here)
        return Segmentation("failed", (), None, True)
    out: list[Consideration] = []
    seen: dict[tuple[int, ...], int] = {}
    stops = [s for s, _ in starts[1:]] + [end]
    for (start, number), stop in zip(starts, stops, strict=True):
        a, b = _stripped(text, start, stop)
        if a >= b:
            continue
        ordinal = len(out) + 1
        out.append(
            Consideration(
                ordinal=ordinal,
                e_number=".".join(str(n) for n in number),
                depth=len(number),
                parent_ordinal=seen.get(tuple(number[:-1])) if len(number) > 1 else None,
                char_start=a,
                char_end=b,
                content=text[a:b],
            )
        )
        seen[tuple(number)] = ordinal
    if not out:
        return Segmentation("failed", (), None, True)
    span = max(1, end - reasons.end())
    covered = sum(c.char_end - c.char_start for c in out)
    return Segmentation("ok", tuple(out), round(min(1.0, covered / span), 5), True)


def label_number(label: str | None) -> str | None:
    """The court's numbering in a consideration label: "E. 3.1", "E.3.1", "consid. 3.1" -> "3.1"; None otherwise
    ("facts", "operative", a label without a number)."""
    if not label:
        return None
    match = _LABEL.match(label)
    return match.group(1) if match else None


def segmentation_id(text_id: str, component_version_id: str) -> str:
    return uuid5(f"segmentation|{text_id}|{component_version_id}")


def consideration_id(seg_id: str, ordinal: int) -> str:
    return uuid5(f"consideration|{seg_id}|{ordinal}")


@dataclass(frozen=True)
class Stored:
    segmentation_id: str
    status: str
    consideration_count: int
    citable: dict[str, str]  # e_number -> consideration_id, citable considerations only
    reused: bool


def store(
    cur: psycopg.Cursor,
    *,
    text_id: str,
    component_version_id: str,
    run_id: str,
    span_id: str | None,
    seg: Segmentation,
    min_citable_depth: int = 1,
) -> Stored:
    """Write one segmentation and its considerations, or reuse the stored one of the same text and splitter
    version (its considerations are read back, never rewritten)."""
    sid = segmentation_id(text_id, component_version_id)
    cur.execute("SELECT status::text, consideration_count FROM corpus.segmentation WHERE segmentation_id = %s", (sid,))
    row = cur.fetchone()
    if row is None:
        cur.execute(
            """INSERT INTO corpus.segmentation (segmentation_id, text_id, component_version_id, method, status,
                   consideration_count, expected_count, coverage_ratio, offsets_found_ratio, is_primary,
                   created_by_run_id, span_id)
               VALUES (%s, %s, %s, 'own_splitter', %s, %s, NULL, %s, %s, false, %s, %s)
               ON CONFLICT (segmentation_id) DO NOTHING RETURNING segmentation_id""",
            (
                sid,
                text_id,
                component_version_id,
                seg.status,
                len(seg.considerations),
                seg.coverage_ratio,
                1.0 if seg.considerations else None,
                run_id,
                span_id,
            ),
        )
        if cur.fetchone() is not None:
            cur.executemany(
                """INSERT INTO corpus.consideration (consideration_id, segmentation_id, ordinal, e_number, depth,
                       parent_consideration_id, char_start, char_end, content, content_sha256)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                [
                    (
                        consideration_id(sid, c.ordinal),
                        sid,
                        c.ordinal,
                        c.e_number,
                        c.depth,
                        consideration_id(sid, c.parent_ordinal) if c.parent_ordinal else None,
                        c.char_start,
                        c.char_end,
                        c.content,
                        sha256_text(c.content),
                    )
                    for c in seg.considerations
                ],
            )
            citable = {
                c.e_number: consideration_id(sid, c.ordinal) for c in seg.considerations if c.depth >= min_citable_depth
            }
            return Stored(sid, seg.status, len(seg.considerations), citable, False)
        cur.execute(  # another run stored it between our read and our insert
            "SELECT status::text, consideration_count FROM corpus.segmentation WHERE segmentation_id = %s", (sid,)
        )
        row = cur.fetchone()
    cur.execute(
        "SELECT e_number, consideration_id::text FROM corpus.consideration WHERE segmentation_id = %s "
        "AND is_citable AND depth >= %s ORDER BY ordinal",
        (sid, min_citable_depth),
    )
    citable = {}
    for e_number, cid in cur.fetchall():
        citable.setdefault(e_number, cid)
    return Stored(sid, row[0], row[1], citable, True)
