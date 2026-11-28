"""Texts the judge needs: Suva's reference summaries (read from `judgements/`, never copied), the rulings
(from the project database) and the summaries to judge.

Split of the 55 references, as docs/EVAL.md §4 sets it: the test set is the Q1/2026 exports plus the
German-language Q4/2025 exports; everything else is the development pool. The judge's prompts were tuned on
the development pool only.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DERIVED = ROOT / "data" / "derived" / "judge"  # git-ignored (D-031): everything that holds Suva-derived text
MAX_SOURCE_CHARS = 250_000  # above this the ruling is not sent at all; it is counted, never cut

# House-style examples shown to the tone criteria: summaries written in the ruling's own language, all from
# the development pool. The summary being judged is never among its own examples.
STYLE_EXAMPLES = {
    "de": ("8C_676/2024", "8C_687/2024", "8C_241/2025", "8C_498/2024"),
    "fr": ("8C_154/2025", "8C_330/2025", "9C_581/2024", "8C_62/2025"),
}
# The side that is not the ruling's language carries a meaning-changing translation error (docs/SUVA_DATA.md §3).
MISTRANSLATED = {("8C_656/2024", "fr"), ("8C_498/2024", "fr"), ("8C_185/2025", "fr"), ("8C_172/2025", "de")}


@dataclass(frozen=True)
class Reference:
    docket: str
    ruling_language: str
    decision_date: str
    de: str
    fr: str

    def text(self, language: str) -> str:
        return self.de if language == "de" else self.fr

    @property
    def split(self) -> str:
        q1_2026 = self.decision_date >= "2026-01-01"
        german_q4 = self.ruling_language == "de" and "2025-10-01" <= self.decision_date <= "2025-12-31"
        return "test" if q1_2026 or german_q4 else "dev"


def references() -> dict[str, Reference]:
    from suva_data.loaders.gold_summaries import read_gold_summaries

    return {
        g.docket: Reference(g.docket, g.title_language, g.decision_date_from_title or "", g.body_de, g.body_fr)
        for g in read_gold_summaries(ROOT / "judgements")
    }


def style_examples(refs: dict[str, Reference], language: str, docket: str, count: int = 3) -> tuple[str, ...]:
    picked = [refs[d].text(language) for d in STYLE_EXAMPLES[language] if d != docket and d in refs]
    return tuple(picked[:count])


def tidy(text: str) -> str:
    """The stored rulings carry many empty lines; the wording is untouched."""
    text = text.replace(" ", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text).strip()
    return re.sub(r"\b1\n(er|re)\b", r"1\1", text)  # "1<sup>er</sup> janvier" arrives on two lines


def sources(dockets: list[str]) -> dict[str, dict[str, str]]:
    """docket -> {text, language, outcome}, from the project database (`DATABASE_URL`)."""
    from suva_data import db

    with db.connect() as conn:
        rows = conn.execute(
            "SELECT r.docket, r.language, r.outcome, t.text FROM rulings r "
            "JOIN ruling_texts t ON t.ruling_id = r.id AND t.is_canonical WHERE r.docket = ANY(%s)",
            (list(dockets),),
        ).fetchall()
    return {d: {"language": lang, "outcome": outcome or "", "text": tidy(text)} for d, lang, outcome, text in rows}


def candidates(path: Path) -> list[dict[str, str]]:
    """Summaries to judge: a directory of `<docket>.json` files as `src/summarize/summarize.py` writes them
    ({"docket", "languages": {"de": {"generated"}, "fr": {...}}}), or a JSON-lines file of
    {"docket", "language", "summary"}."""
    rows = []
    if path.is_dir():
        for file in sorted(path.glob("*.json")):
            data = json.loads(file.read_text(encoding="utf-8"))
            for language, payload in data.get("languages", {}).items():
                rows.append({"docket": data["docket"], "language": language, "summary": payload["generated"]})
    else:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


CONSIDERATIONS = ("Erwägungen:", "Considérant en droit", "Considérants :", "Considérants:", "in Erwägung:")


def court_passage(text: str, low: int = 600, high: int = 1300) -> str | None:
    """A passage of the ruling's own reasoning, taken from consideration 3 onwards.

    The court's prose is the standard of Swiss legal terminology and of native legal writing, so it is the
    positive case for the terminology and language criteria (Suva's summaries carry slips of their own).
    """
    start = max((text.find(marker) for marker in CONSIDERATIONS), default=-1)
    body = text[start:] if start >= 0 else text
    match = re.search(r"(?m)^3\.(?:1\.)?\s", body)
    if not match:
        return None
    picked: list[str] = []
    for paragraph in body[match.start() :].split("\n"):
        paragraph = re.sub(r"^\d+(\.\d+)*\.\s*", "", paragraph.strip())
        if len(paragraph) < 80 or paragraph.startswith(("Demnach erkennt", "Par ces motifs")):
            if paragraph.startswith(("Demnach erkennt", "Par ces motifs")):
                break
            continue
        picked.append(paragraph)
        if sum(map(len, picked)) >= low:
            break
    passage = "\n\n".join(picked)
    if len(passage) > high:
        whole = [m.end() for m in re.finditer(r"[.!?](?=\s+[A-ZÄÖÜÀÉÈ])", passage[:high])]
        passage = passage[: whole[-1]] if whole else passage[:high]
    return passage if len(passage) >= low // 2 else None
