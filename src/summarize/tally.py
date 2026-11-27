"""Compte des erreurs lisibles sur l'arrêt, sans note de qualité.

Ne relance pas le modèle. Lit les fiches déjà écrites dans data/trial.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from summarize import blocking, flat, load_tables, row_for

ROOT = Path(__file__).resolve().parents[2]
TRIAL = ROOT / "data" / "trial"

# Ce que la lecture des dix arrêts a relevé, avant de lancer ce compte.
# Lecture corrigée : ces deux arrêts disent eux-mêmes « offensichtlich unbegründet ».
READ = {
    ("8C_54/2025", "de"): {"pas_un_resume"},
    ("9C_63/2025", "de"): {"pas_un_resume"},
    ("9C_719/2025", "de"): {"pas_un_resume"},
}

DISPOSITION = re.compile(
    r"die beschwerde wird teilweise gutgeheissen"
    r"|die beschwerde wird gutgeheissen"
    r"|die beschwerde wird abgewiesen(?:, soweit darauf eingetreten wird)?"
    r"|auf die beschwerde wird nicht eingetreten"
    r"|le recours est partiellement admis"
    r"|le recours est admis"
    r"|le recours est rejeté(?: dans la mesure où il est recevable)?"
    r"|le recours (?:est|doit être déclaré) irrecevable"
    r"|le recours est irrecevable"
    r"|il ricorso è parzialmente accolto"
    r"|il ricorso è accolto"
    r"|il ricorso è respinto",
    re.IGNORECASE,
)


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
    """Le point 1 du dispositif, ou la dernière phrase qui dit le sort du recours."""
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


def residue(text: str) -> str:
    stripped = DISPOSITION.sub(" ", text)
    return re.sub(r"\s+", " ", stripped).strip(" .")


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
    if len(residue(text)) < 80:
        found.append("pas_un_resume")
    for item in blocking(language, text, source):
        if not str(item).startswith("critique"):
            continue
        if item.startswith("critique: article"):
            found.append("article_invente")
        elif "Suva absente" in item:
            found.append("partie_absente")
        elif "sigle" in item:
            found.append("sigle_mauvaise_langue")
        elif "invers" in item:
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

    print("Essai figé, dix arrêts")
    missed = []
    extra = []
    for docket, language, flags in all_rows:
        if docket not in holdout:
            continue
        expected = READ.get((docket, language), set())
        got = set(flags)
        mark = "ok" if got == expected else "écart"
        if got != expected:
            missed.extend(sorted(expected - got))
            extra.extend(f"{docket} {language}: {name}" for name in sorted(got - expected))
        print(f"  {docket} {language}: {sorted(got) or '—'}  lu: {sorted(expected) or '—'}  {mark}")

    print()
    print(
        "accord avec la lecture:",
        sum(
            1
            for docket, language, flags in all_rows
            if docket in holdout and set(flags) == READ.get((docket, language), set())
        ),
        "/",
        sum(1 for docket, _, _ in all_rows if docket in holdout),
    )
    if extra:
        print("en trop:", "; ".join(extra))
    if missed:
        print("manqué:", ", ".join(missed))

    print()
    print("Toutes les fiches déjà écrites")
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
    print(f"{fiches} fiches, {touched} avec au moins une erreur comptée")
    for name in sorted(counts):
        print(f"  {name}: {counts[name]}")


if __name__ == "__main__":
    main()
