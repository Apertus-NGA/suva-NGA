"""Suva's two example fiches per language, read from judgements/ at run time for v3's write prompt (D-031, D-051).

    shots = examples_for("8C_78/2025")   # {"de": [{"docket", "body"}, ...], "fr": [...]}, the target never among them

v3's write prompt shows two of Suva's own fiches in the fiche's language, for tone and length only
(src/summarize/v3/write.py `_examples`). The two dockets are the ones the summary owner fixed
(`summarize.FEW_SHOT`): one short remand and one dismissal. The branch read them from its own database table; on
main they are read straight from the template's exports, `judgements/Export_<court>_<number>_<year>.html`
(docs/SUVA_DATA.md §3).

Only the two summary bodies are read: the `<p>` paragraphs under the `Text DE` and `Text FR` headings, joined by a
blank line as the branch's loader joined them. Every other section (the title, the bger.ch link, the author
section) is skipped while parsing and never held in memory, so no author name, staff code or intranet link can
reach a prompt, a cache or a log (D-051). The texts stay in memory: nothing here writes a file (D-031: a prompt
holding them lives only in the client's git-ignored cache and in the database).
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

from src.summarize.summarize import FEW_SHOT, clean

ROOT = Path(__file__).resolve().parents[2]
JUDGEMENTS = ROOT / "judgements"
FEW_SHOT_DOCKETS: tuple[str, ...] = FEW_SHOT  # the writer never summarises these (they are in every prompt)
SECTIONS = {"Text DE": "de", "Text FR": "fr"}
LANGUAGES = ("de", "fr")
_DOCKET = re.compile(r"^([0-9]{1,2}[A-Z]_[0-9]+)/([0-9]{4})$")
_SPACE = re.compile(r"[ \t\r\n\f]+")  # HTML white space; a no-break space is content (summarize.clean handles it)


class ExampleMissing(LookupError):
    """An example export is missing or holds no text in one language."""


class _Bodies(HTMLParser):
    """Keeps the paragraphs of the `Text DE` and `Text FR` sections only; any other text is dropped as it is read."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.bodies: dict[str, list[str]] = {language: [] for language in LANGUAGES}
        self._language: str | None = None  # the section being read, None outside the two summary sections
        self._heading: list[str] | None = None
        self._paragraph: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in ("h1", "h2"):
            self._close()
            self._heading = []
        elif tag == "p":
            self._close()
            self._paragraph = [] if self._language else None
        elif tag == "br" and self._paragraph is not None:
            self._paragraph.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("h1", "h2") and self._heading is not None:
            name = _SPACE.sub(" ", "".join(self._heading)).strip()
            self._heading = None
            self._language = SECTIONS.get(name) if tag == "h2" else None  # any other heading ends the section
        elif tag == "p":
            self._close()

    def handle_data(self, data: str) -> None:
        if self._heading is not None:
            self._heading.append(data[:40])  # a heading is short; only the two section names are compared
        elif self._paragraph is not None:
            self._paragraph.append(data)

    def _close(self) -> None:
        if self._paragraph is not None and self._language:
            text = _SPACE.sub(" ", "".join(self._paragraph)).strip()
            if text:
                self.bodies[self._language].append(text)
        self._paragraph = None

    def close(self) -> None:
        super().close()
        self._close()


def export_path(docket: str, directory: Path = JUDGEMENTS) -> Path:
    """The export of one docket: `Export_8C_177_2025.html` (one file name carries a suffix, docs/SUVA_DATA.md)."""
    found = _DOCKET.match(docket)
    if not found:
        raise ValueError(f"not a Federal Supreme Court docket: {docket!r}")
    head, year = found.groups()
    matches = sorted(directory.glob(f"Export_{head}_{year}.html")) or sorted(
        directory.glob(f"Export_{head}_{year} *.html")
    )
    if len(matches) != 1:
        raise ExampleMissing(f"{docket}: {len(matches)} export files in {directory.name}/")
    return matches[0]


def bodies(docket: str, directory: Path = JUDGEMENTS) -> dict[str, str]:
    """{"de": body, "fr": body} of one export: paragraphs joined by a blank line, cleaned as the branch did."""
    parser = _Bodies()
    parser.feed(export_path(docket, directory).read_text(encoding="utf-8", errors="replace"))
    parser.close()
    out = {language: clean("\n\n".join(parser.bodies[language])) for language in LANGUAGES}
    empty = [language for language, body in out.items() if not body.strip()]
    if empty:
        raise ExampleMissing(f"{docket}: no summary text in {', '.join(empty)}")
    return out


def examples_for(target_docket: str | None = None, directory: Path = JUDGEMENTS) -> dict[str, list[dict]]:
    """The example fiches per language, in FEW_SHOT_DOCKETS order, the target's own excluded (as the branch did)."""
    read = {docket: bodies(docket, directory) for docket in FEW_SHOT_DOCKETS if docket != target_docket}
    return {
        language: [{"docket": docket, "body": texts[language]} for docket, texts in read.items()]
        for language in LANGUAGES
    }


__all__ = ["FEW_SHOT_DOCKETS", "ExampleMissing", "bodies", "examples_for", "export_path"]
