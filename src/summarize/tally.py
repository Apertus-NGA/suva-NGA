"""Count errors a reader can check against the ruling, with no quality score.

Does not call the model again. Reads fiches already written in data/trial.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

try:
    from summarize import blocking, flat, load_tables, operative_only, row_for
except ModuleNotFoundError:
    from src.summarize.summarize import blocking, flat, load_tables, operative_only, row_for

ROOT = Path(__file__).resolve().parents[2]
TRIAL = ROOT / "data" / "trial"

# What the reading of the ten rulings found, before this count was run.
# Corrected reading: these rulings themselves say "offensichtlich unbegründet".
READ = {
    ("8C_54/2025", "de"): {"pas_un_resume"},
    ("9C_63/2025", "de"): {"pas_un_resume"},
    ("9C_719/2025", "de"): {"pas_un_resume"},
}


def operative_block(source: str) -> str:
    norm = flat(source).lower()
    start = 0
    for marker in (
        "demnach erkennt",
        "erkennt die präsidentin",
        "erkennt der präsident",
        "par ces motifs",
        "per questi motivi",
    ):
        at = norm.rfind(marker)
        if at > start:
            start = at
    return norm[start:]


def kind_of_sentence(sentence: str) -> str:
    low = sentence.lower()
    if re.search(r"nicht eingetreten|tritt .{0,60}nicht ein|n'entre pas en matière|irrecevable", low):
        return "inadmissible"
    if "teilweise" in low or "partiellement" in low or "parzialmente" in low:
        return "partial"
    if re.search(r"\brejet", low) or "abgewiesen" in low or "respinto" in low:
        return "rejected"
    if re.search(r"gutgeheissen|\badmis\b|\baccolto\b", low):
        return "admitted"
    return ""


def focus(text: str) -> str:
    """Point 1 of the outcome, or the last sentence that states the fate of the appeal."""
    low = flat(text).lower()
    point = re.search(r"(?:^|:)\s*1\.\s+([^.]{0,240})", low)
    if point and re.search(r"beschwerde|recours|ricorso", point.group(1)):
        return point.group(1)
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", low) if part.strip()]
    carrying = [part for part in parts if kind_of_sentence(part)]
    if carrying:
        return carrying[-1]
    return parts[-1] if parts else low[-300:]


def kind_of(text: str) -> str:
    return kind_of_sentence(focus(text))


def tally_one(language: str, text: str, source: str) -> list[str]:
    found: list[str] = []
    order = operative_block(source)
    fiche = kind_of(text)
    held = kind_of(order)
    if held and fiche and held != fiche:
        found.append("dispositif_incorrect")
    elif held and not fiche:
        found.append("dispositif_absent")
    obvious = (
        "offensichtlich unbegründet" in flat(source).lower()
        or "manifestement non fondé" in flat(source).lower()
        or "manifestement infondé" in flat(source).lower()
    )
    low = text.lower()
    if language == "fr" and re.search(r"manifestement (?:non |in)?fondé", low) and not obvious:
        found.append("manifestement_invente")
    if language == "de" and "offensichtlich unbegründet" in low and not obvious:
        found.append("manifestement_invente")
    if operative_only(text):
        found.append("pas_un_resume")
    for item in blocking(language, text, source):
        if not str(item).startswith("critique"):
            continue
        if item.startswith("critique: article"):
            found.append("article_invente")
        elif "Suva absent" in item:
            found.append("partie_absente")
        elif "sigil" in item:
            found.append("sigle_mauvaise_langue")
        elif "inverted" in item:
            found.append("condition_inversee")
    return found


def load_holdout() -> list[str]:
    path = TRIAL / "holdout10.txt"
    return [line.split("\t", 1)[0] for line in path.read_text().splitlines() if line.strip()]


def score_file(path: Path, rulings) -> list[tuple[str, str, list[str]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    docket = data.get("docket")
    if not docket or "languages" not in data:
        return []
    try:
        source = row_for(rulings, docket)["text"]
    except SystemExit:
        return []
    rows = []
    for language, payload in data["languages"].items():
        text = payload.get("generated") or ""
        rows.append((docket, language, tally_one(language, text, source)))
    return rows


def main() -> None:
    rulings, _ = load_tables()
    holdout = set(load_holdout())
    files = sorted(TRIAL.glob("*.json"))
    all_rows: list[tuple[str, str, list[str]]] = []
    for path in files:
        all_rows.extend(score_file(path, rulings))

    print("Frozen trial, ten rulings")
    missed = []
    extra = []
    for docket, language, flags in all_rows:
        if docket not in holdout:
            continue
        expected = READ.get((docket, language), set())
        got = set(flags)
        mark = "ok" if got == expected else "gap"
        if got != expected:
            missed.extend(sorted(expected - got))
            extra.extend(f"{docket} {language}: {name}" for name in sorted(got - expected))
        print(f"  {docket} {language}: {sorted(got) or '—'}  read: {sorted(expected) or '—'}  {mark}")

    print()
    print(
        "agreement with the reading:",
        sum(
            1
            for docket, language, flags in all_rows
            if docket in holdout and set(flags) == READ.get((docket, language), set())
        ),
        "/",
        sum(1 for docket, _, _ in all_rows if docket in holdout),
    )
    if extra:
        print("extra:", "; ".join(extra))
    if missed:
        print("missed:", ", ".join(missed))

    print()
    print("Every fiche already written")
    counts: dict[str, int] = {}
    fiches = 0
    touched = 0
    for docket, language, flags in all_rows:
        fiches += 1
        if flags:
            touched += 1
        for name in flags:
            counts[name] = counts.get(name, 0) + 1
        if flags:
            print(f"  {docket} {language}: {', '.join(flags)}")
    print()
    print(f"{fiches} fiches, {touched} with at least one counted error")
    for name in sorted(counts):
        print(f"  {name}: {counts[name]}")


if __name__ == "__main__":
    main()
