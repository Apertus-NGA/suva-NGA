"""Write a Suva fiche in German and in French, each on its own.

Reads the local cache data/cache. Writes nothing to Hugging Face.
The key stays in .env and is never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

if __package__:
    from .prompts import VERSION, category_of, glossary_block, sigil_hint, sigils, system_prompt
else:
    from prompts import VERSION, category_of, glossary_block, sigil_hint, sigils, system_prompt

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache"
# Tone only: one short fiche (remand) and one dismissal.
# The text of those rulings is not put in the prompt: it leaked into the outcome.
FEW_SHOT = ("8C_177/2025", "8C_224/2025")
EXCLUDED = frozenset({"8C_21/2025", "8C_44/2025", "8C_455/2025"})
ORDER_MARKERS = (
    "Demnach erkennt das Bundesgericht",
    "Par ces motifs, le Tribunal fédéral prononce",
    "Per questi motivi, il Tribunale federale pronuncia",
)


def _gate(docket: str, area: object, text: str, title: object = None):
    """The script is launched from src/summarize: courts.py lives in src/."""
    src = str(ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    from courts import area_for_gate, decide

    filled = area_for_gate(area, title)
    return decide(docket, area, text, title), filled


def load_env() -> None:
    env_path = ROOT / ".env"
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def clean(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


OPERATIVE = (
    "Die Beschwerde wird teilweise gutgeheissen",
    "Die Beschwerde wird gutgeheissen",
    "Die Beschwerde wird abgewiesen",
    "Le recours est partiellement admis",
    "Le recours est admis",
    "Le recours est rejeté",
    "Il ricorso è parzialmente accolto",
    "Il ricorso è accolto",
    "Il ricorso è respinto",
)


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", clean(text))


def anchors(text: str) -> str:
    """Short extracts around the rules this ruling applies."""
    norm = flat(text)
    windows = []
    for needle in (
        "15. Februar 2023",
        "mehr als 50",
        "Vermutung der Leistungspflicht",
        "natürlichem Kausalzusammenhang",
        "kein Untersuchungsmangel",
        "peut demeurer ouverte",
        "mois qui suit",
        "offensichtlich unbegründet",
        "sein Einverständnis",
    ):
        at = norm.find(needle)
        if at < 0:
            continue
        windows.append(norm[max(0, at - 160) : at + 220].strip())
    return "\n".join(windows)


def directions(language: str, text: str) -> list[str]:
    """Direction of this ruling's rules. Stops a threshold or an article being reversed."""
    norm = flat(text)
    lines = []
    if "zu mehr als 50 %" in norm and "Abnützung" in norm:
        lines.append(
            "Die Sehnenläsion ist zu mehr als 50 % auf Abnützung oder Erkrankung zurückzuführen. "
            "Der Schwellenwert ist erreicht. Schreibe nicht, er sei nicht erreicht."
            if language == "de"
            else "The tendon lesion is due more than 50% to wear or disease. "
            "The threshold is met. Do not write that it is not met. "
            "In the French fiche use: lésion, usure, plus de 50 %."
        )
    if "Vermutung der Leistungspflicht gemäss Art. 6 Abs. 2 UVG" in norm:
        lines.append(
            "Art. 6 Abs. 2 UVG vermutet die Leistungspflicht. Sie ist umgestossen, weil die Läsion "
            "zu mehr als 50 % auf Abnützung zurückgeht. "
            "Schreibe nicht, die Leistungspflicht bestehe nur bei Abnützung. "
            "Art. 4 ATSG bezeichnet den natürlichen Kausalzusammenhang, nicht diese Vermutung."
            if language == "de"
            else "art. 6 al. 2 LAA presumes the duty to pay. It is rebutted because the lesion "
            "is due more than 50% to wear. Do not write that the duty exists only in case of wear. "
            "art. 4 LPGA is natural causation, not this presumption."
        )
    if "15. Februar 2023" in norm:
        lines.append(
            "Der erste Absatz nennt beide Ereignisse, darunter den Sturz vom 15. Februar 2023 "
            "beim Aussteigen auf gefrorenem Asphalt, ohne erneute Läsion."
            if language == "de"
            else "The first paragraph names both events, including the fall of 15 February 2023 "
            "while getting out of the vehicle on frozen asphalt, with no new lesion."
        )
    if "keine auch nur geringe Teilursache" in norm:
        lines.append(
            "Beide Ereignisse sind keine auch nur geringe Teilursache der Befunde. "
            "Die Frage ist die Unfallkausalität, nicht eine richtungsgebende Verschlimmerung "
            "und nicht der Status quo sine vel ante."
            if language == "de"
            else "Neither event is even a minor partial cause of the findings. "
            "The question is accident causation, not a decisive aggravation "
            "and not the statu quo sine vel ante."
        )
    if "peut demeurer ouverte" in norm or "offen bleiben" in norm or "kann offenbleiben" in norm:
        lines.append(
            "Eine Frage, die der Entscheid offen lässt, bleibt offen. Triff sie nicht."
            if language == "de"
            else "A question the ruling leaves open stays open. Do not decide it."
        )
    if "mois qui suit" in norm or "Monats nach" in norm:
        lines.append(
            "Die Einstellung wirkt ab dem Tag des Monats, der auf die Inhaftierung folgt, "
            "nicht ab dem ersten Tag der Haft, und nur wenn die Haft länger als drei Monate dauert."
            if language == "de"
            else "The suspension takes effect on the day of the month that follows the imprisonment, "
            "not on the first day of detention, and only if the detention lasted more than three months."
        )
    if "offensichtlich unbegründet" in norm:
        lines.append(
            "Die Beschwerde ist offensichtlich unbegründet."
            if language == "de"
            else "Write the outcome as: Le recours est rejeté comme manifestement non fondé."
        )
    if "art. 56" in norm.lower() and "fbis" in norm.lower():
        lines.append(
            "Eine Beschwerde wegen Rechtsverweigerung ist kein Leistungsstreit. "
            "Kantonal dürfen keine Gerichtskosten erhoben werden. "
            "Art. 56 Abs. 2 ATSG verlangt eine Entscheidung innert angemessener Frist. "
            "Art. 61 lit. fbis ATSG betrifft nur Streitigkeiten über Leistungen."
            if language == "de"
            else "An appeal for denial of justice is not a dispute about benefits. "
            "No cantonal court costs may be charged. "
            "art. 56 al. 2 LPGA requires a decision within a reasonable time. "
            "art. 61 let. fbis LPGA covers only disputes about benefits."
        )
    if "sein Einverständnis" in norm and "unterzeichnen" in norm.lower():
        lines.append(
            "Der fallführende Arzt hätte die ergänzenden Stellungnahmen unterzeichnen "
            "oder sein Einverständnis erklären müssen. Schreibe nicht, ein unabhängiger Arzt sei beauftragt."
            if language == "de"
            else "The treating doctor should have signed the further opinions "
            "or given his agreement. Do not write that an independent doctor is appointed."
        )
    if "erübrigt sich" in norm and "Art. 4 ATSG" in norm:
        lines.append(
            "Fehlt der natürliche Kausalzusammenhang nach Art. 4 ATSG, "
            "erübrigt sich die Prüfung nach Art. 6 Abs. 2 UVG. "
            "Art. 4 ATSG muss im Text stehen."
            if language == "de"
            else "Without natural causation under art. 4 LPGA, the review of art. 6 al. 2 LAA is unnecessary. "
            "Do not write 'adequate causation': the ruling does not decide that point. "
            "art. 4 LPGA must appear in the text."
        )
    return lines


def required_forms(language: str, text: str) -> list[str]:
    """Wordings that must appear, taken from this ruling only."""
    norm = flat(text)
    forms = []
    if "Art. 6 Abs. 2 UVG" in norm or "art. 6 al. 2 LAA" in norm.lower():
        forms.append("Art. 6 Abs. 2 UVG" if language == "de" else "art. 6 al. 2 LAA")
    if "Art. 4 ATSG" in norm or "art. 4 LPGA" in norm.lower():
        forms.append("Art. 4 ATSG" if language == "de" else "art. 4 LPGA")
    if "50" in norm and ("Abnützung" in norm or "usure" in norm.lower()):
        forms.append("mehr als 50 %" if language == "de" else "plus de 50 %")
    if "Untersuchungsmangel" in norm:
        forms.append(
            "kein Untersuchungsmangel, die Kosten des privaten Gutachters trägt die Suva nicht"
            if language == "de"
            else "no gap in the investigation: the private expert's fees are not charged to Suva"
        )
    return forms


def order_of(text: str) -> str:
    """One sentence of the outcome, not the signature block."""
    for sentence in OPERATIVE:
        if sentence in text:
            return sentence + "."
    for marker in ORDER_MARKERS:
        at = text.find(marker)
        if at >= 0:
            return text[at : at + 220].split("\n\n")[0].strip()
    return ""


def user_prompt(language: str, examples: list[dict], target: dict, category: str) -> str:
    label = "Merkblatt" if language == "de" else "Fiche"
    chunks = [
        glossary_block(language, category),
        "",
        "Tone examples only. Do not reuse their facts or their outcome.",
        "",
    ]
    for example in examples:
        chunks.append(f"{label} of another ruling ({example['docket']}):")
        chunks.append(example["body"])
        chunks.append("")
    chunks.append("Ruling to summarise, and only this one:")
    chunks.append(
        f"{target['docket']} of {target['decision_date']}, court {target['division']}, matter {target['area']}."
    )
    chunks.append(target["text"])
    chunks.append("")
    held = anchors(target["text"])
    if held:
        if language == "de":
            chunks.append(
                "Diese Sätze dieses Entscheids gehören in den Text, "
                "in Prosa und mit deutschen Siglen. Nicht weglassen, nicht als Zitatblock anhängen:"
            )
        else:
            chunks.append(
                "These sentences of this ruling belong in the fiche, in French prose, "
                f"with the French sigils of this matter ({sigil_hint(category)}). "
                "Do not drop them, and do not paste them in German:"
            )
        chunks.append(held)
        chunks.append("")
    forms = required_forms(language, target["text"])
    if forms:
        joined = " ; ".join(forms)
        if language == "de":
            chunks.append(f"Der Text enthält diese Formulierungen, im Satz und nur einmal: {joined}.")
        else:
            chunks.append(f"The text contains these wordings, inside a sentence and only once: {joined}.")
        chunks.append("")
    held_sense = directions(language, target["text"])
    if held_sense:
        if language == "de":
            chunks.append("Richtung, die dieser Entscheid vorgibt. Nicht umkehren:")
        else:
            chunks.append("Direction this ruling imposes. Do not reverse it:")
        chunks.extend(held_sense)
        chunks.append("")
    order = order_of(target["text"])
    if order:
        sentence = outcome_sentence(language, order)
        if language == "de":
            chunks.append(f"Ausgang dieses Entscheids, auf Deutsch, in einem Satz und nur einmal: {sentence}")
        else:
            chunks.append(f"Outcome of this ruling, in French, in one sentence and only once: {sentence}")
        chunks.append("")
    if language == "de":
        chunks.append("Schreibe ausschliesslich Deutsch, auch wenn der Entscheid französisch oder italienisch ist.")
    else:
        chunks.append("Write in French only, even if the ruling is in German or Italian.")
    chunks.append(f"{label} :")
    return "\n".join(chunks)


def repair_prompt(
    language: str,
    draft: str,
    forms: list[str],
    issue: list[str],
    sense: list[str],
    category: str,
) -> str:
    must = " ; ".join(forms)
    wrong = ", ".join(issue)
    way = " ".join(sense)
    laws = sigils(language, category)
    if language == "de":
        return (
            "Überarbeite das Merkblatt. Keine Aufzählung, kein kopierter Urteilsblock, "
            "das Dispositiv nur im letzten Satz. "
            f"Siglen dieser Materie: {laws}. "
            f"Zu beheben: {wrong}. "
            f"Richtung: {way} "
            f"Diese Formulierungen müssen im Text stehen: {must}.\n\n"
            f"{draft}"
        )
    return (
        "Rewrite the fiche. No list, no pasted operative block, "
        "the outcome only in the last sentence. "
        f"Sigils of this matter: {laws}. "
        f"Fix: {wrong}. "
        f"Direction: {way} "
        f"These wordings must appear in the text: {must}.\n\n"
        f"{draft}"
    )


def chat(messages: list[dict]) -> str:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from src.llm.client import LLMError, client_from_env

    client = client_from_env("live")
    try:
        return client.chat(messages, max_tokens=1200, prompt_version=VERSION).content
    except LLMError as exc:
        raise SystemExit(f"gateway: {exc}") from exc
    finally:
        client.close()


def load_tables():
    import pandas as pd

    rulings_path = CACHE / "rulings.parquet"
    gold_path = CACHE / "gold_summaries.parquet"
    if not rulings_path.exists() or not gold_path.exists():
        raise SystemExit(f"local cache missing: {CACHE}")
    rulings = pd.read_parquet(rulings_path)
    gold = pd.read_parquet(gold_path)
    gold = gold[gold.is_current]
    return rulings, gold


def row_for(rulings, docket: str) -> dict:
    found = rulings[rulings.docket == docket]
    if found.empty:
        raise SystemExit(f"ruling missing from the cache: {docket}")
    row = found.iloc[0]
    return {
        "docket": row.docket,
        "decision_date": str(row.decision_date)[:10],
        "division": row.division,
        "area": row.area if isinstance(row.area, str) and row.area.strip() else None,
        "title": row.subject if isinstance(row.subject, str) and row.subject.strip() else None,
        "text": clean(row.text),
    }


def gold_body(gold, docket: str, language: str) -> str:
    found = gold[(gold.docket == docket) & (gold.language == language)]
    if found.empty:
        return ""
    return clean(found.iloc[0].body)


LAW_ALIASES = {
    "uvg": ("uvg", "laa"),
    "atsg": ("atsg", "lpga"),
    "uvv": ("uvv", "olaa"),
    "atsv": ("atsv", "opga"),
    "bgg": ("bgg", "ltf"),
}
CITE_DE = re.compile(
    r"art\.\s*(\d+[a-z]?)(?:\s*abs\.\s*\d+)?(?:\s*lit\.\s*[a-z])?\s*(uvg|atsg|uvv|atsv|bgg)\b",
    re.IGNORECASE,
)
CITE_FR = re.compile(
    r"art\.\s*(\d+[a-z]?)(?:\s*al\.\s*\d+)?(?:\s*let\.\s*[a-z])?\s*(laa|lpga|olaa|opga|ltf)\b",
    re.IGNORECASE,
)
TO_CANON = {
    "uvg": "uvg",
    "atsg": "atsg",
    "uvv": "uvv",
    "atsv": "atsv",
    "bgg": "bgg",
    "laa": "uvg",
    "lpga": "atsg",
    "olaa": "uvv",
    "opga": "atsv",
    "ltf": "bgg",
}


def outcome_sentence(language: str, order: str) -> str:
    """The outcome, in the fiche language, without copying the ruling's language."""
    kind = outcome_of(order)
    sentences = {
        "de": {
            "rejected": "Die Beschwerde wird abgewiesen.",
            "admitted": "Die Beschwerde wird gutgeheissen.",
            "partial": "Die Beschwerde wird teilweise gutgeheissen.",
        },
        "fr": {
            "rejected": "Le recours est rejeté.",
            "admitted": "Le recours est admis.",
            "partial": "Le recours est partiellement admis.",
        },
    }
    return sentences.get(language, {}).get(kind, order)


def outcome_of(order: str) -> str:
    low = order.lower()
    if "teilweise" in low or "partiellement" in low or "parzialmente" in low:
        return "partial"
    if "abgewiesen" in low or "rejeté" in low or "respinto" in low:
        return "rejected"
    if "gutgeheissen" in low or "admis" in low or "accolto" in low:
        return "admitted"
    return ""


def _tail(text: str) -> str:
    return text.strip()[-280:].lower()


def _article_in_source(number: str, law: str, source: str) -> bool:
    if not any(alias in source for alias in LAW_ALIASES[law]):
        return False
    return re.search(rf"art\.\s*{re.escape(number)}\b", source) is not None


_OUTCOME = re.compile(
    r"die beschwerde wird (?:teilweise )?gutgeheissen"
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


def operative_only(text: str) -> bool:
    """True when nothing remains once the outcome sentences are removed."""
    residue = _OUTCOME.sub(" ", text)
    residue = re.sub(r"\s+", " ", residue).strip(" .")
    return len(residue) < 80


def blocking(language: str, text: str, source: str) -> list[str]:
    """Blocking checks taken from this ruling. They hold for every docket."""
    low = text.lower()
    source_low = flat(source).lower()
    found: list[str] = []
    if re.search(r"(?m)^\s*[-•]", text):
        found.append("minor: bullet list")
    kind = outcome_of(order_of(source))
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part.strip()]
    tail = parts[-1].lower() if parts else ""
    if language == "de":
        if re.search(r"\b(laa|lpga|olaa|opga)\b", low):
            found.append("critique: French sigil")
        if kind == "rejected":
            if "abgewiesen" not in tail:
                found.append("critique: outcome, dismissal missing")
            if "gutgeheissen" in tail and "abgewiesen" not in tail:
                found.append("critique: outcome inverted")
        elif kind == "admitted":
            if "gutgeheissen" not in tail:
                found.append("critique: outcome, admission missing")
            if "abgewiesen" in tail:
                found.append("critique: outcome inverted")
        elif kind == "partial" and "teilweise" not in low and "zurückgewies" not in low:
            found.append("critique: partial admission missing")
        cites = CITE_DE.findall(text)
    else:
        if re.search(r"\b(uvg|atsg|uvv|atsv)\b", low):
            found.append("critique: German sigil")
        if kind == "rejected":
            if "rejet" not in tail:
                found.append("critique: outcome, dismissal missing")
            if re.search(r"\badmis\b", tail) and "rejet" not in tail:
                found.append("critique: outcome inverted")
        elif kind == "admitted":
            if not re.search(r"\badmis\b", tail):
                found.append("critique: outcome, admission missing")
            if "rejet" in tail:
                found.append("critique: outcome inverted")
        elif kind == "partial" and "partiellement" not in low and "renvoy" not in low:
            found.append("critique: partial admission missing")
        cites = CITE_FR.findall(text)
    invented = []
    for number, sigil in cites:
        law = TO_CANON[sigil.lower()]
        if not _article_in_source(number, law, source_low):
            invented.append(f"art. {number} {sigil}")
    if invented:
        unique = list(dict.fromkeys(invented))
        found.append("critique: article missing from the ruling (" + ", ".join(unique) + ")")
    if "zu mehr als 50" in source_low and "abnützung" in source_low:
        if language == "de":
            if re.search(r"nicht erreicht|weniger als 50|unter 50", low):
                found.append("critique: 50% threshold inverted")
            if re.search(r"leistungspflicht nur.{0,220}abnützung", low):
                found.append("critique: art. 6 condition inverted")
        elif re.search(r"pas atteint|non atteint|moins de 50|inférieur à 50", low):
            found.append("critique: 50% threshold inverted")
        elif re.search(r"obligation[^.]{0,80}seulement[^.]{0,80}usure|n'existe qu", low):
            found.append("critique: art. 6 condition inverted")
    if re.search(r"art\. 17[^\n]{0,80}statu|statu[^\n]{0,80}art\. 17", low):
        found.append("critique: art. 17 confused with the status quo")
    if language == "de" and "offensichtlich" in low and "offensichtlich" not in source_low:
        found.append("critique: manifestly ill-founded copied")
    if (
        language == "fr"
        and "manifestement" in low
        and "manifestement" not in source_low
        and "offensichtlich" not in source_low
    ):
        found.append("critique: manifestly ill-founded copied")
    if "demnach erkennt" in low or "par ces motifs" in low or "per questi motivi" in low:
        found.append("critique: operative block pasted")
    if language == "de" and ("le recours" in low or "l'assuré" in low or "l’assuré" in low):
        found.append("critique: fiche written in French")
    if language == "fr" and ("die beschwerde" in low or "il ricorso" in low):
        found.append("critique: fiche in another language")
    foreign_notions = (
        (
            ("causalité adéquate", "adäquater kausal", "kausalzusammenhang adäquat"),
            ("adéquate", "adäquat", "adeguat"),
            "adequate causation absent from the ruling",
        ),
        (
            ("lésion assimilée", "listenverletzung", "unfallähnliche"),
            ("assimil", "listenverletzung", "unfallähnlich"),
            "assimilated injury absent from the ruling",
        ),
    )
    for fiche_forms, source_forms, label in foreign_notions:
        if any(form in low for form in fiche_forms) and not any(form in source_low for form in source_forms):
            found.append(f"critique: {label}")
    if "unabhängigen arzt" in low and "unabhäng" not in source_low:
        found.append("critique: independent doctor absent from the ruling")
    if "peut demeurer ouverte" in source_low:
        if language == "de" and not re.search(r"psychisch[^.]{0,120}offen|offen[^.]{0,120}psychisch", low):
            found.append("critique: open question decided")
        if language == "fr" and not re.search(r"psychique[^.]{0,160}ouverte|ouverte[^.]{0,160}psychique", low):
            found.append("critique: open question decided")
    if "suva" in low and "suva" not in source_low and "cna" not in source_low:
        found.append("critique: Suva absent from the ruling")
    if "rixe" in low and "rixe" not in source_low:
        found.append("critique: meaningless word")
    if operative_only(text):
        found.append("critique: fiche is only the operative sentence")
    return found


def problems(language: str, text: str) -> list[str]:
    """Clear gaps against the 8C_78/2025 fiche. Used for the trial, not for the score."""
    low = text.lower()
    found: list[str] = []
    if re.search(r"(?m)^\s*[-•]", text):
        found.append("bullet list")
    if language == "de":
        if "abgewiesen" not in low:
            found.append("appeal not dismissed")
        if "zurückverwies" in low or "zurückgewies" in low:
            found.append("remand copied")
        if "uvg" not in low:
            found.append("UVG absent")
        if "atsg" not in low:
            found.append("ATSG absent")
        if "offensichtlich" in low:
            found.append("manifestly ill-founded dismissal copied")
        if re.search(r"\b(laa|lpga|olaa)\b", low):
            found.append("French sigil in the German fiche")
        if "art. 6 abs. 2" not in low:
            found.append("art. 6 al. 2 absent")
        if "sagittal" in low or "ischio" in low or "hamstring" in low:
            found.append("fact from another ruling")
        if "mehr als 50" not in low or "abnützung" not in low:
            found.append("50% threshold missing")
        if re.search(r"nicht erreicht|nicht überschritten|weniger als 50|unter 50", low):
            found.append("50% threshold inverted")
        if re.search(r"leistungspflicht nur.{0,220}abnützung", low):
            found.append("art. 6 condition inverted")
        if re.search(r"vermutung[^.]{0,100}art\. 4", low):
            found.append("presumption tied to art. 4")
        if not re.search(r"februar|15\.", low):
            found.append("second fall missing")
        if "richtungsgebende" in low:
            found.append("wrong legal question")
        if low.count("beschwerde wird abgewiesen") > 1:
            found.append("outcome repeated")
        if "suva" not in low:
            found.append("Suva doctor missing")
        if "demnach erkennt" in low or "viscione" in low or "gerichtskosten" in low:
            found.append("operative block pasted")
    else:
        if "rejet" not in low:
            found.append("appeal not dismissed")
        if "renvoy" in low:
            found.append("remand copied")
        if "laa" not in low:
            found.append("LAA absent")
        if "lpga" not in low:
            found.append("LPGA absent")
        if "manifestement" in low:
            found.append("manifestly ill-founded dismissal copied")
        if low.count("recours est rejeté") > 1:
            found.append("outcome repeated")
        if re.search(r"\b(uvg|atsg|uvv)\b", low):
            found.append("German sigil in the French fiche")
        if "art. 6 al. 2" not in low:
            found.append("art. 6 al. 2 absent")
        if "art. 4" not in low:
            found.append("art. 4 absent")
        if "bandelette" in low or "ischio" in low:
            found.append("fact from another ruling")
        if "plus de 50" not in low or "usure" not in low:
            found.append("50% threshold missing")
        if re.search(r"pas atteint|non atteint|moins de 50|inférieur à 50", low):
            found.append("50% threshold inverted")
        if re.search(r"pr[ée]somption[^.]{0,80}art\. 4", low):
            found.append("presumption tied to art. 4")
        if "suva" not in low:
            found.append("Suva doctor missing")
        if "expert" not in low:
            found.append("private expert missing")
        if not re.search(r"deux|second|autre chute|février|fevrier", low):
            found.append("second fall missing")
        if "demnach" in low or "viscione" in low or "polla" in low:
            found.append("operative block pasted")
        if re.search(r"art\. 17[^\n]{0,80}statu|statu[^\n]{0,80}art\. 17", low):
            found.append("art. 17 confused with the status quo")
        if "adéquate" in low or "adequate" in low:
            found.append("adequate causation invented")
        if "arrondissement" in low:
            found.append("district doctor invented")
        if "ouvrier" in low:
            found.append("occupation invented")
        if re.search(r"obligation[^.]{0,80}seulement[^.]{0,80}usure|n'existe qu", low):
            found.append("art. 6 condition inverted")
    if len(text) > 2500:
        found.append(f"trop long ({len(text)})")
    if len(text) < 400:
        found.append(f"trop court ({len(text)})")
    return found


def review(language: str, text: str, source: str, docket: str) -> list[str]:
    found = blocking(language, text, source)
    if docket == "8C_78/2025":
        found.extend(problems(language, text))
    return found


def _critical(language: str, text: str, source: str, docket: str) -> list[str]:
    if docket == "8C_78/2025":
        return review(language, text, source, docket)
    return [item for item in blocking(language, text, source) if item.startswith("critique")]


def write_fiche(language: str, target: dict, examples: list[dict], category: str, ask=None) -> tuple[str, list[str]]:
    """One fiche in one language: generate, let the checker ask for up to two repairs, return (text, problems).

    `target` is {"docket", "decision_date", "division", "area", "text"}; `examples` are [{"docket", "body"}].
    `ask` sends the messages to the model and returns its text (default: `chat`, the gateway client).
    The prompt is the one of the ruling's matter (`category`), in the fiche's language.
    """
    ask = ask or chat
    system = system_prompt(language, category)
    user = user_prompt(language, examples, target, category)
    text = ask([{"role": "system", "content": system}, {"role": "user", "content": user}])
    forms = required_forms(language, target["text"])
    sense = directions(language, target["text"])
    for _ in range(2):
        issue = _critical(language, text, target["text"], target["docket"])
        if not issue:
            break
        revised = ask(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": repair_prompt(language, text, forms, issue, sense, category)},
            ]
        )
        if len(_critical(language, revised, target["text"], target["docket"])) < len(issue):
            text = revised
    return text, review(language, text, target["text"], target["docket"])


def summarize(docket: str) -> dict:
    rulings, gold = load_tables()
    target = row_for(rulings, docket)
    if docket in FEW_SHOT or docket in EXCLUDED:
        raise SystemExit(f"{docket} is a few-shot example or is excluded from it")
    decision, filled = _gate(target["docket"], target["area"], target["text"], target["title"])
    if not decision.kept:
        raise SystemExit(
            f"{docket} does not pass the filter ({target['division']}, {filled}, {decision.subject}, {decision.text})"
        )
    category = category_of(filled if isinstance(filled, str) else None)
    out = {
        "docket": docket,
        "model": os.environ["LLM_NAME"],
        "filter": {"kept": decision.kept, "subject": decision.subject, "text": decision.text},
        "prompt": VERSION,
        "category": category,
        "languages": {},
    }
    for language in ("de", "fr"):
        examples = [{"docket": shot, "body": gold_body(gold, shot, language)} for shot in FEW_SHOT]
        text, issue = write_fiche(language, target, examples, category)
        out["languages"][language] = {
            "generated": text,
            "gold": gold_body(gold, docket, language),
            "problems": issue,
        }
        print(f"{language} {len(text)} characters {issue or 'ok'}", flush=True)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dockets", nargs="*")
    args = parser.parse_args()
    load_env()
    dockets = args.dockets or ["8C_78/2025"]
    failed: list[str] = []
    dest = ROOT / "data" / "trial"
    dest.mkdir(parents=True, exist_ok=True)
    for index, docket in enumerate(dockets, start=1):
        path = dest / (docket.replace("/", "_") + ".json")
        if path.exists():
            print(f"{index}/{len(dockets)} {docket} already written", flush=True)
            continue
        print(f"{index}/{len(dockets)} {docket}", flush=True)
        try:
            result = summarize(docket)
        except (SystemExit, TimeoutError) as exc:
            failed.append(f"{docket}: {exc}")
            print(f"failed {docket}: {exc}", flush=True)
            continue
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(path, flush=True)
        for language, payload in result["languages"].items():
            critical = [item for item in payload["problems"] if str(item).startswith("critique")]
            if critical:
                failed.append(f"{docket} {language}: {', '.join(critical)}")
    if failed:
        raise SystemExit(" ; ".join(failed))


if __name__ == "__main__":
    main()
