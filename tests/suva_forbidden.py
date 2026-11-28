"""Forbidden values of D-051, read from judgements/ at test time and kept in memory only.

Never print, log or write a value returned here: report the file, the line and the kind of match only.
Forbidden (docs/agents/platform.md step 10, docs/EVAL.md T31):
- the exact lines of each export's author section;
- each full "given name + surname" pair, in both orders, case-sensitive, on word boundaries;
- each staff code in its export form: a standalone upper-case token (which covers the parenthesised form);
- the intranet host of the workbook's hyperlinks, and their common path prefix.
Job titles and single names are not matched: they are ordinary words in rulings.
"""

from __future__ import annotations

import gzip
import html
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

_AUTHOR_SECTION = re.compile(r"<h2>\s*Autor\s*</h2>(.*?)(?:<hr\s*/?>|</body>|<h2>)", re.S | re.I)
_PARAGRAPH = re.compile(r"<p[^>]*>(.*?)</p>", re.S | re.I)
_AUTHOR_LINE = re.compile(r"^(?P<names>[^()]+?)\s*\((?P<code>[^()]+)\)")
_HYPERLINK = re.compile(r"<Relationship\b[^>]*>", re.I)


@dataclass
class Forbidden:
    author_lines: set[str] = field(default_factory=set)
    name_pairs: set[str] = field(default_factory=set)
    staff_codes: set[str] = field(default_factory=set)
    intranet_hosts: set[str] = field(default_factory=set)
    intranet_prefixes: set[str] = field(default_factory=set)
    exports_with_author: int = 0

    def __repr__(self) -> str:  # never show the values, even in a pytest failure report
        return (
            f"Forbidden(author_lines={len(self.author_lines)}, name_pairs={len(self.name_pairs)}, "
            f"staff_codes={len(self.staff_codes)}, intranet_hosts={len(self.intranet_hosts)}, "
            f"intranet_prefixes={len(self.intranet_prefixes)})"
        )


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def load(judgements: Path) -> Forbidden:
    f = Forbidden()
    for export in sorted(judgements.glob("Export_*.html")):
        section = _AUTHOR_SECTION.search(export.read_text(encoding="utf-8", errors="replace"))
        if not section:
            continue
        f.exports_with_author += 1
        for para in _PARAGRAPH.findall(section.group(1)):
            line = _text(para)
            if not line:
                continue
            f.author_lines.add(line)
            m = _AUTHOR_LINE.match(line)
            if not m:
                continue
            tokens = m.group("names").split()
            if len(tokens) >= 2:
                f.name_pairs.add(" ".join(tokens))
                f.name_pairs.add(" ".join(tokens[1:] + tokens[:1]))
            f.staff_codes.add(m.group("code").strip())
    for workbook in sorted(judgements.glob("*.xlsx")):
        with zipfile.ZipFile(workbook) as z:  # cells' hyperlinks only, never the file properties (D-051)
            rels = [n for n in z.namelist() if n.startswith("xl/worksheets/_rels/") and n.endswith(".rels")]
            paths: list[list[str]] = []
            for name in rels:
                for tag in _HYPERLINK.findall(z.read(name).decode("utf-8", "replace")):
                    if "/hyperlink" not in tag or 'TargetMode="External"' not in tag:
                        continue
                    target = re.search(r'Target="([^"]+)"', tag)
                    if not target:
                        continue
                    url = urlsplit(html.unescape(target.group(1)))
                    if url.hostname:
                        f.intranet_hosts.add(url.hostname.lower())
                        paths.append([s for s in url.path.split("/") if s])
            if paths:
                common: list[str] = []
                for parts in zip(*paths, strict=False):
                    if len(set(parts)) != 1:
                        break
                    common.append(parts[0])
                if common:
                    f.intranet_prefixes.add("/" + "/".join(common))
    return f


def _compile(f: Forbidden) -> list[tuple[str, re.Pattern[str]]]:
    def words(values: set[str]) -> str:
        alts = sorted((r"\s+".join(map(re.escape, v.split())) for v in values), key=len, reverse=True)
        return r"(?<!\w)(?:" + "|".join(alts) + r")(?!\w)"

    checks: list[tuple[str, re.Pattern[str]]] = []
    if f.author_lines:
        checks.append(("author line", re.compile(words(f.author_lines))))
    if f.name_pairs:
        checks.append(("author name pair", re.compile(words(f.name_pairs))))
    if f.staff_codes:
        codes = "|".join(sorted(map(re.escape, f.staff_codes), key=len, reverse=True))
        checks.append(("staff code", re.compile(r"(?<![A-Za-z0-9])(?:" + codes + r")(?![A-Za-z0-9])")))
    if f.intranet_hosts:
        checks.append(("intranet host", re.compile("|".join(map(re.escape, f.intranet_hosts)), re.I)))
    if f.intranet_prefixes:
        checks.append(("intranet path prefix", re.compile("|".join(map(re.escape, f.intranet_prefixes)))))
    return checks


def _texts(path: Path) -> list[tuple[str, str]]:
    """(member suffix, text) pairs to scan. A .zip or .gz is read inside, member by member: its compressed bytes
    would hide a real value and match one by chance. Any other file is read as UTF-8, invalid bytes ignored."""
    raw = path.read_bytes()
    suffix = path.suffix.lower()
    try:
        if suffix == ".zip" and zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                return [
                    (f"!{n}", z.read(n).decode("utf-8", errors="ignore")) for n in z.namelist() if not n.endswith("/")
                ]
        if suffix == ".gz":
            return [("", gzip.decompress(raw).decode("utf-8", errors="ignore"))]
    except (zipfile.BadZipFile, gzip.BadGzipFile, EOFError, OSError):
        pass  # not a readable archive after all: scan its bytes as they are
    return [("", raw.decode("utf-8", errors="ignore"))]


def scan(files: list[Path], forbidden: Forbidden, root: Path) -> list[str]:
    """Return 'path[!member]:line: kind' for every match. Never the value."""
    checks = _compile(forbidden)
    hits: list[str] = []
    for path in files:
        try:
            parts = _texts(path)
        except OSError:
            continue
        for member, text in parts:
            for lineno, line in enumerate(text.splitlines(), 1):
                for kind, pattern in checks:
                    if pattern.search(line):
                        hits.append(f"{path.relative_to(root)}{member}:{lineno}: {kind}")
    return hits
