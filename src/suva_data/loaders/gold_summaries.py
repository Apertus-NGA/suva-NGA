"""Loader for the human-written reference summaries (docs/DATA_LAYER.md, section 3.2).

`read_gold_summaries` is pure (HTML files -> dataclasses); `write_gold_summaries` attaches them to
`rulings` in one transaction. Standard library only.

One file per ruling:

    <h1>title</h1>
    <h2>Text DE</h2> <p>..</p><p>..</p>
    <h2>Text FR</h2> <p>..</p><p>..</p>
    <h2>Link zum Urteil</h2> <p><a href="..">..</a></p>      (one file has the bare URL as text instead)
    <h2>Autor</h2> <p>name</p>

The case number comes from the FILENAME: the title is typed by hand and can be wrong (one lacks its prefix).
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from .. import config
from ..models import normalise_docket
from .labels_xlsx import resolve_dockets

FILE_GLOB = "Export_*.html"
SECTION_DE, SECTION_FR, SECTION_LINK, SECTION_AUTHOR = "Text DE", "Text FR", "Link zum Urteil", "Autor"

TITLE_LANGUAGE_PREFIXES = (("BGer-Urteil", "de"), ("Arrêt du", "fr"), ("Sentenza del", "it"))

# Month names without accents, lower case (titles are compared the same way).
MONTHS = {
    **dict(zip("januar februar marz april mai juni juli august september oktober november dezember".split(), range(1, 13))),
    **dict(zip("janvier fevrier mars avril mai juin juillet aout septembre octobre novembre decembre".split(), range(1, 13))),
    **dict(zip("gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre".split(), range(1, 13))),
}
_TITLE_DATE_RE = re.compile(r"(?<!\d)(\d{1,2})(?:er|\.|º|°)?\s+([^\W\d_]+)\s+(\d{4})(?!\d)")
_HTML_SPACE_RE = re.compile(r"[ \t\r\n\f]+")  # HTML white space; a no-break space is content and is kept


class GoldSummaryError(ValueError):
    """The summaries cannot be read or attached safely. Nothing was written."""


@dataclass(frozen=True)
class GoldSummary:
    docket: str  # from the filename
    source_file: str  # file name, e.g. 'Export_8C_72_2025.html'
    title: str
    title_language: str  # 'de' | 'fr' | 'it': the language of the ruling
    decision_date_from_title: str | None  # ISO date; None if the title has no parseable date
    body_de: str  # paragraphs separated by a blank line
    body_fr: str
    author: str | None  # as written
    source_url: str | None  # the "Link zum Urteil"


def _collapse(text: str) -> str:
    return _HTML_SPACE_RE.sub(" ", text).strip()


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def title_language(title: str) -> str | None:
    for prefix, language in TITLE_LANGUAGE_PREFIXES:
        if title.startswith(prefix):
            return language
    return None


def parse_title_date(title: str) -> str | None:
    """'… vom 4. August 2025' / '… du 1er septembre 2025' / '… del 21 agosto 2025' -> ISO date, else None."""
    for day, month_name, year in _TITLE_DATE_RE.findall(title):
        month = MONTHS.get(_strip_accents(month_name).lower())
        if month:
            try:
                return dt.date(int(year), month, int(day)).isoformat()
            except ValueError:
                return None
    return None


class _ExportParser(HTMLParser):
    """Collects the <h1> title and, per <h2> section: its <p> paragraphs, text outside <p>, and link targets."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)  # entities are unescaped by the parser
        self.title: str | None = None
        self.sections: dict[str, dict[str, list[str]]] = {}
        self.duplicate_sections: list[str] = []
        self._section: dict[str, list[str]] | None = None
        self._heading: tuple[str, list[str]] | None = None  # ('h1' | 'h2', text parts)
        self._paragraph: list[str] | None = None

    def _close_paragraph(self) -> None:
        if self._paragraph is not None and self._section is not None:
            text = _collapse("".join(self._paragraph))
            if text.strip():  # drops empty paragraphs, including ones holding only a no-break space
                self._section["paragraphs"].append(text)
        self._paragraph = None

    def handle_starttag(self, tag, attrs):
        if tag in ("h1", "h2"):
            self._close_paragraph()
            self._heading = (tag, [])
        elif tag == "p":
            self._close_paragraph()  # an unclosed <p> ends where the next one starts
            self._paragraph = []
        elif tag == "br":
            self.handle_data(" ")
        elif tag == "a" and self._section is not None:
            href = dict(attrs).get("href")
            if href:
                self._section["hrefs"].append(href.strip())

    def handle_endtag(self, tag):
        if self._heading and tag == self._heading[0]:
            text = _collapse("".join(self._heading[1]))
            self._heading = None
            if tag == "h1":
                if self.title is None:
                    self.title = text
                return
            if text in self.sections:
                self.duplicate_sections.append(text)
            self._section = self.sections.setdefault(text, {"paragraphs": [], "loose": [], "hrefs": []})
        elif tag == "p":
            self._close_paragraph()

    def handle_data(self, data):
        if self._heading is not None:
            self._heading[1].append(data)
        elif self._paragraph is not None:
            self._paragraph.append(data)
        elif self._section is not None:
            self._section["loose"].append(data)

    def close(self):
        super().close()
        self._close_paragraph()


def parse_export(html_text: str, source_file: str) -> GoldSummary:
    """Parse one export file. Raises GoldSummaryError on anything that would lose or misattribute content."""

    def fail(reason: str):
        raise GoldSummaryError(f"{source_file}: {reason}")

    docket = normalise_docket(Path(source_file).stem.removeprefix("Export_"))
    if docket is None:
        fail("no Federal Supreme Court case number in the file name")

    parser = _ExportParser()
    parser.feed(html_text)
    parser.close()
    if not parser.title:
        fail("no <h1> title")
    if parser.duplicate_sections:
        fail(f"section(s) appear more than once: {parser.duplicate_sections}")
    language = title_language(parser.title)
    if language is None:
        fail(f"cannot tell the ruling's language from the title {parser.title!r}")
    docket_in_title = normalise_docket(parser.title)
    if docket_in_title is not None and docket_in_title != docket:
        fail(f"file name says {docket} but the title says {docket_in_title}")

    bodies = {}
    for name in (SECTION_DE, SECTION_FR):
        section = parser.sections.get(name)
        if section is None:
            fail(f"section {name!r} is missing")
        loose = _collapse("".join(section["loose"]))
        if loose.strip():
            fail(f"section {name!r} has text outside <p> paragraphs: {loose[:80]!r}")
        if not section["paragraphs"]:
            fail(f"section {name!r} is empty")
        bodies[name] = "\n\n".join(section["paragraphs"])

    def section_text(name: str) -> str:
        section = parser.sections.get(name, {"paragraphs": [], "loose": []})
        return _collapse(" ".join(section["paragraphs"] + ["".join(section["loose"])]))

    link = parser.sections.get(SECTION_LINK, {"hrefs": []})
    link_text = section_text(SECTION_LINK)
    if link["hrefs"]:
        source_url = link["hrefs"][0]
    elif re.fullmatch(r"https?://\S+", link_text):  # the URL pasted as plain text instead of a link
        source_url = link_text
    else:
        source_url = None

    return GoldSummary(
        docket=docket,
        source_file=source_file,
        title=parser.title,
        title_language=language,
        decision_date_from_title=parse_title_date(parser.title),
        body_de=bodies[SECTION_DE],
        body_fr=bodies[SECTION_FR],
        author=section_text(SECTION_AUTHOR) or None,
        source_url=source_url,
    )


def read_gold_summaries(directory: Path | str = config.JUDGEMENTS_DIR) -> list[GoldSummary]:
    """All `Export_*.html` files of the directory, sorted by file name. Fails on two files for one docket."""
    summaries = [
        parse_export(path.read_text(encoding="utf-8"), path.name)
        for path in sorted(Path(directory).glob(FILE_GLOB), key=lambda p: p.name)
    ]
    files_by_docket: dict[str, list[str]] = {}
    for summary in summaries:
        files_by_docket.setdefault(summary.docket, []).append(summary.source_file)
    duplicates = {docket: files for docket, files in files_by_docket.items() if len(files) > 1}
    if duplicates:
        raise GoldSummaryError(f"{directory}: more than one file for the same docket: {duplicates}")
    return summaries


def write_gold_summaries(conn, summaries: list[GoldSummary]) -> dict[str, int]:
    """Insert two rows per summary ('de', 'fr'), version 1. All or nothing; running it again changes nothing.

    Raises GoldSummaryError, listing every offending docket, if a docket matches no ruling or several,
    if the date in a title is not the ruling's decision date (the summary would sit on the wrong ruling),
    or if a stored version 1 differs from the file (title, body, author or link). Changed files are never
    overwritten: versioning of edits is a later feature. Later versions written by experts are left alone.
    """
    files_by_docket: dict[str, list[str]] = {}
    for summary in summaries:
        files_by_docket.setdefault(summary.docket, []).append(summary.source_file)
    duplicates = {docket: files for docket, files in files_by_docket.items() if len(files) > 1}
    if duplicates:
        raise GoldSummaryError(f"gold summaries not written. more than one summary for the same docket: {duplicates}")

    with conn.transaction():
        resolved, missing, ambiguous = resolve_dockets(conn, files_by_docket)
        date_mismatch = [
            f"{s.docket}: title {s.decision_date_from_title}, ruling {resolved[s.docket][1].isoformat()} ({s.source_file})"
            for s in summaries
            if s.docket in resolved
            and s.decision_date_from_title is not None
            and s.decision_date_from_title != resolved[s.docket][1].isoformat()
        ]

        ruling_ids = [ruling_id for ruling_id, _ in resolved.values()]
        existing = {
            (ruling_id, language): content
            for ruling_id, language, *content in conn.execute(
                "SELECT ruling_id, language, title, body, author, source_url FROM gold_summaries"
                " WHERE version = 1 AND ruling_id = ANY(%s)",
                (ruling_ids,),
            )
        }
        to_insert, changed, unchanged = [], [], 0
        for s in summaries:
            if s.docket not in resolved:
                continue
            ruling_id = resolved[s.docket][0]
            for language, body in (("de", s.body_de), ("fr", s.body_fr)):
                content = [s.title, body, s.author, s.source_url]
                stored = existing.get((ruling_id, language))
                if stored is None:
                    to_insert.append((ruling_id, language, *content, s.source_file))
                elif stored == content:
                    unchanged += 1
                else:
                    changed.append(f"{s.docket} [{language}] ({s.source_file})")

        problems = []
        if missing:
            problems.append(f"no ruling for {len(missing)} docket(s): {missing}")
        if ambiguous:
            problems.append(f"more than one ruling for {len(ambiguous)} docket(s) (docket: decision dates): {ambiguous}")
        if date_mismatch:
            problems.append(f"the date in the title is not the ruling's decision date for {len(date_mismatch)} summary(ies): {date_mismatch}")
        if changed:
            problems.append(
                f"{len(changed)} stored summary(ies) differ from the file; changed files are not overwritten"
                f" (versioning of edits is not implemented yet): {changed}"
            )
        if problems:
            raise GoldSummaryError("gold summaries not written. " + "; ".join(problems))

        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO gold_summaries (ruling_id, language, title, body, author, source_url, source_file, version, is_current)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, 1, true)",
                to_insert,
            )
    return {"read": len(summaries), "inserted": len(to_insert), "unchanged": unchanged}
