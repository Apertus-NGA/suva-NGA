"""A summary as numbered sentences, and the only edits a step may make to it.

The model never rewrites a summary. It names a sentence by its id (`s3`, from a closed list) and proposes one
`Patch`; code applies it. Sentences code owns are `locked`: the outcome sentence (written by `finish.py` from the
operative part) and Suva's closing note. A patch on a locked sentence is refused.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Literal

from src.summarize import finish

# A period after one of these does not end a sentence ("Art. 6 Abs. 1 UVG", "E. 4.2", "vgl. BGE").
_ABBREVIATIONS = frozenset(
    "art abs al lit let bst ziff nr no n e erw consid ch cf vgl bzw resp s p ss ff sog insb dr prof etc rz "
    "bge atf ivm i.v.m z.b u.a m.w.h vol hrsg éd cit op chap seq".split()
)
_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÜÀÂÉÈÊÎÔÛÇ«\"(])")
_TAIL_WORD = re.compile(r"([\w.]+)\.$")

Op = Literal["replace", "delete", "insert_after", "insert_before"]


@dataclass(frozen=True)
class Sentence:
    id: str
    text: str
    paragraph: int
    locked: bool = False


@dataclass(frozen=True)
class Patch:
    """One edit. `sentence` is the id it applies to; `text` is the new sentence (empty for a delete)."""

    op: Op
    sentence: str
    text: str = ""
    span: str | None = None  # replace only `span` inside the sentence (a word-level patch), not the whole sentence

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in (None, "")}


class PatchRefused(ValueError):
    """The patch names no sentence of the draft, touches a locked one, or its span is not in the sentence."""


def split_sentences(paragraph: str) -> list[str]:
    """Sentences of one paragraph. A boundary after an abbreviation, an initial or an ordinal ("1. Januar") is
    not a boundary."""
    pieces = [p for p in _BOUNDARY.split(paragraph.strip()) if p.strip()]
    merged: list[str] = []
    for piece in pieces:
        if merged:
            tail = _TAIL_WORD.search(merged[-1])
            word = tail.group(1).lower() if tail else ""
            # an abbreviation, a single letter or initial ("lit. a.", "A."), an ordinal or day ("1. Januar")
            if word and (word in _ABBREVIATIONS or re.fullmatch(r"[a-zäöü]|\d{1,2}|[a-z]\.[a-z]", word)):
                merged[-1] = f"{merged[-1]} {piece}"
                continue
        merged.append(piece.strip())
    return merged


def _is_locked(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 60 and finish._NOTE.search(stripped):  # Suva's closing note, added from facts
        return True
    residue = finish._STATES_OUTCOME.sub("", stripped).strip(" .;,:")
    return bool(finish._STATES_OUTCOME.search(stripped)) and len(residue) < 25


@dataclass(frozen=True)
class Draft:
    sentences: tuple[Sentence, ...]

    @classmethod
    def from_text(cls, text: str) -> Draft:
        out: list[Sentence] = []
        for number, paragraph in enumerate(p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()):
            for sentence in split_sentences(" ".join(paragraph.split())):
                out.append(Sentence(f"s{len(out) + 1}", sentence, number, _is_locked(sentence)))
        return cls(tuple(out))

    def render(self) -> str:
        paragraphs: dict[int, list[str]] = {}
        for sentence in self.sentences:
            paragraphs.setdefault(sentence.paragraph, []).append(sentence.text)
        return "\n\n".join(" ".join(parts) for _, parts in sorted(paragraphs.items()))

    def ids(self, editable_only: bool = True) -> list[str]:
        return [s.id for s in self.sentences if not (editable_only and s.locked)]

    def get(self, sentence_id: str) -> Sentence:
        for sentence in self.sentences:
            if sentence.id == sentence_id:
                return sentence
        raise PatchRefused(f"no sentence {sentence_id!r}")

    def numbered(self) -> str:
        """The draft as the model sees it: one sentence per line, with its id; locked sentences marked."""
        return "\n".join(f"[{s.id}]{' (fixed)' if s.locked else ''} {s.text}" for s in self.sentences)

    def words(self) -> int:
        return len(self.render().split())

    def apply(self, patch: Patch) -> Draft:
        """The draft with the patch applied, renumbered. Raises PatchRefused; never edits a locked sentence."""
        target = self.get(patch.sentence)
        inserting = patch.op in ("insert_after", "insert_before")
        if target.locked and not inserting:
            raise PatchRefused(f"{patch.sentence} is fixed by code")
        if patch.op != "delete" and not patch.text.strip():
            raise PatchRefused("empty text")
        out: list[Sentence] = []
        for sentence in self.sentences:
            if sentence.id != patch.sentence:
                out.append(sentence)
                continue
            new = Sentence("", " ".join(patch.text.split()), sentence.paragraph)
            if patch.op == "delete":
                continue
            if patch.op == "replace":
                if patch.span is not None:
                    if patch.span not in sentence.text:
                        raise PatchRefused(f"span {patch.span!r} not in {patch.sentence}")
                    new = replace(sentence, text=sentence.text.replace(patch.span, patch.text.strip(), 1))
                out.append(new)
            elif patch.op == "insert_before":
                out += [new, sentence]
            else:
                out += [sentence, new]
        renumbered = tuple(
            Sentence(f"s{n}", s.text, s.paragraph, _is_locked(s.text)) for n, s in enumerate(out, start=1)
        )
        return Draft(renumbered)
