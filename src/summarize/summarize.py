"""Rédige une fiche Suva en allemand et en français, chacune à part.

Lit le cache local data/cache. N'écrit rien sur Hugging Face.
La clé reste dans .env et n'est pas affichée.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache"
GLOSSARY = json.loads((Path(__file__).parent / "glossary.json").read_text(encoding="utf-8"))
# Ton seulement : une fiche courte (renvoi) et une fiche de rejet.
# Le texte de ces arrêts n'est pas mis dans le prompt : il déteignait sur le dispositif.
FEW_SHOT = ("8C_177/2025", "8C_224/2025")
EXCLUDED = frozenset({"8C_21/2025", "8C_44/2025", "8C_455/2025"})
ORDER_MARKERS = (
    "Demnach erkennt das Bundesgericht",
    "Par ces motifs, le Tribunal fédéral prononce",
    "Per questi motivi, il Tribunale federale pronuncia",
)


def _court_passes(docket: str, area: str) -> bool:
    """Le script est lancé depuis src/summarize : courts.py vit dans src/."""
    src = str(ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    from courts import passes

    return passes(docket, area)


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


def glossary_block(language: str) -> str:
    lines = ["Lois (ne pas traduire le sigle, employer celui de la langue de la fiche) :"]
    for law in GLOSSARY["laws"]:
        if language == "de":
            lines.append(f"- {law['de']} (français : {law['fr']})")
        else:
            lines.append(f"- {law['fr']} (allemand : {law['de']})")
    lines.append("Articles : citer la forme de la langue de la fiche.")
    for art in GLOSSARY["articles"]:
        lines.append(f"- {art['de']} = {art['fr']}")
    lines.append("Tournures :")
    for phrase in GLOSSARY["phrases"]:
        lines.append(f"- {phrase['de']} = {phrase['fr']}")
    return "\n".join(lines)


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
    """Extraits courts autour des règles que cet arrêt applique."""
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
    """Sens des règles de cet arrêt. Empêche d'inverser un seuil ou un article."""
    norm = flat(text)
    lines = []
    if "zu mehr als 50 %" in norm and "Abnützung" in norm:
        lines.append(
            "Die Sehnenläsion ist zu mehr als 50 % auf Abnützung oder Erkrankung zurückzuführen. "
            "Der Schwellenwert ist erreicht. Schreibe nicht, er sei nicht erreicht."
            if language == "de"
            else "La lésion tendineuse est due à plus de 50 % à l'usure ou à une maladie. "
            "Le seuil est atteint. N'écris pas qu'il n'est pas atteint."
        )
    if "Vermutung der Leistungspflicht gemäss Art. 6 Abs. 2 UVG" in norm:
        lines.append(
            "Art. 6 Abs. 2 UVG vermutet die Leistungspflicht. Sie ist umgestossen, weil die Läsion "
            "zu mehr als 50 % auf Abnützung zurückgeht. "
            "Schreibe nicht, die Leistungspflicht bestehe nur bei Abnützung. "
            "Art. 4 ATSG bezeichnet den natürlichen Kausalzusammenhang, nicht diese Vermutung."
            if language == "de"
            else "L'art. 6 al. 2 LAA présume l'obligation de prester. Elle est renversée parce que la lésion "
            "est due à plus de 50 % à l'usure. N'écris pas que l'obligation n'existe qu'en cas d'usure. "
            "L'art. 4 LPGA désigne le lien de causalité naturelle, pas cette présomption."
        )
    if "15. Februar 2023" in norm:
        lines.append(
            "Der erste Absatz nennt beide Ereignisse, darunter den Sturz vom 15. Februar 2023 "
            "beim Aussteigen auf gefrorenem Asphalt, ohne erneute Läsion."
            if language == "de"
            else "Le premier paragraphe nomme les deux événements, dont la chute du 15 février 2023 "
            "en descendant du véhicule sur l'asphalte gelé, sans nouvelle lésion."
        )
    if "keine auch nur geringe Teilursache" in norm:
        lines.append(
            "Beide Ereignisse sind keine auch nur geringe Teilursache der Befunde. "
            "Die Frage ist die Unfallkausalität, nicht eine richtungsgebende Verschlimmerung "
            "und nicht der Status quo sine vel ante."
            if language == "de"
            else "Les deux événements ne sont pas une cause partielle, même minime, des lésions. "
            "La question est la causalité de l'accident, pas une aggravation déterminante "
            "et pas le statu quo sine vel ante."
        )
    if "peut demeurer ouverte" in norm or "offen bleiben" in norm or "kann offenbleiben" in norm:
        lines.append(
            "Eine Frage, die der Entscheid offen lässt, bleibt offen. Triff sie nicht."
            if language == "de"
            else "Une question que l'arrêt laisse ouverte le reste. Ne la tranche pas."
        )
    if "mois qui suit" in norm or "Monats nach" in norm:
        lines.append(
            "Die Einstellung wirkt ab dem Tag des Monats, der auf die Inhaftierung folgt, "
            "nicht ab dem ersten Tag der Haft, und nur wenn die Haft länger als drei Monate dauert."
            if language == "de"
            else "La suspension prend effet le jour du mois qui suit l'incarcération, "
            "pas le premier jour de la détention, et seulement si la détention a duré plus de trois mois."
        )
    if "offensichtlich unbegründet" in norm:
        lines.append(
            "Die Beschwerde ist offensichtlich unbegründet."
            if language == "de"
            else "Le recours est rejeté comme manifestement non fondé."
        )
    if "art. 56" in norm.lower() and "fbis" in norm.lower():
        lines.append(
            "Eine Beschwerde wegen Rechtsverweigerung ist kein Leistungsstreit. "
            "Kantonal dürfen keine Gerichtskosten erhoben werden. "
            "Art. 56 Abs. 2 ATSG verlangt eine Entscheidung innert angemessener Frist. "
            "Art. 61 lit. fbis ATSG betrifft nur Streitigkeiten über Leistungen."
            if language == "de"
            else "Un recours pour déni de justice n'est pas un litige de prestations. "
            "Aucun frais judiciaire cantonal ne peut être perçu. "
            "L'art. 56 al. 2 LPGA impose une décision dans un délai raisonnable. "
            "L'art. 61 let. fbis LPGA ne vise que les contestations de prestations."
        )
    if "sein Einverständnis" in norm and "unterzeichnen" in norm.lower():
        lines.append(
            "Der fallführende Arzt hätte die ergänzenden Stellungnahmen unterzeichnen "
            "oder sein Einverständnis erklären müssen. Schreibe nicht, ein unabhängiger Arzt sei beauftragt."
            if language == "de"
            else "Le médecin en charge aurait dû signer les prises de position complémentaires "
            "ou donner son accord. N'écris pas qu'un médecin indépendant est commis."
        )
    if "erübrigt sich" in norm and "Art. 4 ATSG" in norm:
        lines.append(
            "Fehlt der natürliche Kausalzusammenhang nach Art. 4 ATSG, "
            "erübrigt sich die Prüfung nach Art. 6 Abs. 2 UVG. "
            "Art. 4 ATSG muss im Text stehen."
            if language == "de"
            else "Sans lien de causalité naturelle selon l'art. 4 LPGA, l'examen de l'art. 6 al. 2 LAA est superflu. "
            "N'écris pas « causalité adéquate » : l'arrêt ne tranche pas ce point. "
            "L'art. 4 LPGA doit figurer dans le texte."
        )
    return lines


def required_forms(language: str, text: str) -> list[str]:
    """Formes à faire apparaître, déduites de cet arrêt seulement."""
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
            else "pas de lacune d'instruction : les frais de l'expert privé ne sont pas mis à la charge de la Suva"
        )
    return forms


def order_of(text: str) -> str:
    """Une phrase du dispositif, pas le bloc de signature."""
    for sentence in OPERATIVE:
        if sentence in text:
            return sentence + "."
    for marker in ORDER_MARKERS:
        at = text.find(marker)
        if at >= 0:
            return text[at : at + 220].split("\n\n")[0].strip()
    return ""


def system_prompt(language: str) -> str:
    if language == "de":
        return (
            "Du schreibst ein Suva-Merkblatt auf Deutsch, in zwei bis vier Absätzen, "
            "ohne Titel, ohne Aufzählung, ohne Rubriken. "
            "Absatz 1: was geschehen ist, in einem Zug, ohne medizinische Details. "
            "Absatz 2: die Regel, die das Bundesgericht für diesen Fall ausspricht. "
            "Letzter Satz: das Dispositiv in einem Satz. "
            "Kopiere nicht den Block «Demnach erkennt», keine Gerichtskosten, "
            "keine Unterschriften, kein Ort und kein Datum der Ausfertigung. "
            "Die Beispiele zeigen nur Länge und Ton. Ihre Sachverhalte und ihre Ausgänge "
            "gehören zu anderen Fällen. "
            "Zitiere nur Artikel, die dieser Entscheid anwendet, in deutscher Form "
            "(UVG, ATSG, UVV). Art. 17 ATSG ist die Revision, nicht der Status quo. "
            "Nichts erfinden. Antworte nur mit dem Merkblatt."
        )
    return (
        "Tu rédiges une fiche Suva en français, en deux à quatre paragraphes, "
        "sans titre, sans liste à puces, sans rubriques. "
        "Premier paragraphe : ce qui s'est passé, en une fois, sans détail médical. "
        "Deuxième : la règle que le Tribunal fédéral pose pour cet arrêt. "
        "Dernière phrase : le dispositif en une phrase, dans ta langue. "
        "Ne recopie pas le bloc du jugement, ni les frais de justice, ni les signatures, ni le lieu. "
        "S'il y a deux événements, les deux figurent dans le premier paragraphe. "
        "Si l'arrêt applique l'Art. 4 ATSG, écris art. 4 LPGA. "
        "Les exemples montrent seulement la longueur et le ton. "
        "Leurs faits et leur issue sont ceux d'autres affaires. "
        "Ne cite qu'un article que cet arrêt applique, dans la forme française "
        "(LAA, LPGA, OLAA). L'art. 17 LPGA est la révision, pas le statu quo. "
        "N'invente rien. Réponds uniquement par la fiche."
    )


def user_prompt(language: str, examples: list[dict], target: dict) -> str:
    label = "Merkblatt" if language == "de" else "Fiche"
    chunks = [
        glossary_block(language),
        "",
        "Exemples de ton seulement. N'en reprends ni les faits ni l'issue.",
        "",
    ]
    for example in examples:
        chunks.append(f"{label} d'un autre arrêt ({example['docket']}) :")
        chunks.append(example["body"])
        chunks.append("")
    chunks.append("Arrêt à résumer, et seulement celui-ci :")
    chunks.append(
        f"{target['docket']} du {target['decision_date']}, cour {target['division']}, matière {target['area']}."
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
                "Ces phrases de cet arrêt figurent dans la fiche, en prose française, "
                "avec les sigles français du glossaire (UVG devient LAA, ATSG devient LPGA). "
                "Ne pas les omettre, ne pas les coller en allemand:"
            )
        chunks.append(held)
        chunks.append("")
    forms = required_forms(language, target["text"])
    if forms:
        joined = " ; ".join(forms)
        if language == "de":
            chunks.append(f"Der Text enthält diese Formulierungen, im Satz und nur einmal: {joined}.")
        else:
            chunks.append(f"Le texte contient ces formulations, dans la phrase et une seule fois : {joined}.")
        chunks.append("")
    held_sense = directions(language, target["text"])
    if held_sense:
        if language == "de":
            chunks.append("Richtung, die dieser Entscheid vorgibt. Nicht umkehren:")
        else:
            chunks.append("Sens que cet arrêt impose. Ne pas l'inverser :")
        chunks.extend(held_sense)
        chunks.append("")
    order = order_of(target["text"])
    if order:
        sentence = outcome_sentence(language, order)
        if language == "de":
            chunks.append(f"Ausgang dieses Entscheids, auf Deutsch, in einem Satz und nur einmal: {sentence}")
        else:
            chunks.append(f"Issue de cet arrêt, en français, en une phrase et une seule fois : {sentence}")
        chunks.append("")
    if language == "de":
        chunks.append("Schreibe ausschliesslich Deutsch, auch wenn der Entscheid französisch oder italienisch ist.")
    else:
        chunks.append("Écris exclusivement en français, même si l'arrêt est allemand ou italien.")
    chunks.append(f"{label} :")
    return "\n".join(chunks)


def repair_prompt(
    language: str,
    draft: str,
    forms: list[str],
    issue: list[str],
    sense: list[str],
) -> str:
    must = " ; ".join(forms)
    wrong = ", ".join(issue)
    way = " ".join(sense)
    if language == "de":
        return (
            "Überarbeite das Merkblatt. Keine Aufzählung, kein kopierter Urteilsblock, "
            "das Dispositiv nur im letzten Satz. "
            f"Zu beheben: {wrong}. "
            f"Richtung: {way} "
            f"Diese Formulierungen müssen im Text stehen: {must}.\n\n"
            f"{draft}"
        )
    return (
        "Réécris la fiche. Pas de liste, pas de bloc d'arrêt collé, "
        "le dispositif seulement dans la dernière phrase. "
        f"À corriger : {wrong}. "
        f"Sens : {way} "
        f"Ces formulations doivent figurer dans le texte : {must}.\n\n"
        f"{draft}"
    )


def chat(messages: list[dict]) -> str:
    base = os.environ["LLM_BASE_URL"].rstrip("/")
    payload = {
        "model": os.environ["LLM_NAME"],
        "temperature": 0.1,
        "max_tokens": 1200,
        "messages": messages,
    }
    request = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": "Bearer " + os.environ["LLM_API_KEY"],
            "Content-Type": "application/json",
        },
    )
    last_error = ""
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=240) as response:
                body = json.loads(response.read().decode())
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:500]
            last_error = f"passerelle HTTP {exc.code}: {detail}"
            if exc.code not in (502, 503, 504) or attempt == 2:
                raise SystemExit(last_error) from exc
            time.sleep(8)
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = f"passerelle injoignable: {exc}"
            if attempt == 2:
                raise SystemExit(last_error) from exc
            time.sleep(8)
    else:
        raise SystemExit(last_error)
    return body["choices"][0]["message"]["content"].strip()


def load_tables() -> tuple[pd.DataFrame, pd.DataFrame]:
    rulings_path = CACHE / "rulings.parquet"
    gold_path = CACHE / "gold_summaries.parquet"
    if not rulings_path.exists() or not gold_path.exists():
        raise SystemExit(f"cache local absent : {CACHE}")
    rulings = pd.read_parquet(rulings_path)
    gold = pd.read_parquet(gold_path)
    gold = gold[gold.is_current]
    return rulings, gold


def row_for(rulings: pd.DataFrame, docket: str) -> dict:
    found = rulings[rulings.docket == docket]
    if found.empty:
        raise SystemExit(f"arrêt absent du cache : {docket}")
    row = found.iloc[0]
    return {
        "docket": row.docket,
        "decision_date": str(row.decision_date)[:10],
        "division": row.division,
        "area": row.area,
        "text": clean(row.text),
    }


def gold_body(gold: pd.DataFrame, docket: str, language: str) -> str:
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
    """Le dispositif, dans la langue de la fiche, sans recopier la langue de l'arrêt."""
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


def blocking(language: str, text: str, source: str) -> list[str]:
    """Contrôles bloquants déduits de cet arrêt. Vrais pour n'importe quel dossier."""
    low = text.lower()
    source_low = flat(source).lower()
    found: list[str] = []
    if re.search(r"(?m)^\s*[-•]", text):
        found.append("mineure: liste à puces")
    kind = outcome_of(order_of(source))
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part.strip()]
    tail = parts[-1].lower() if parts else ""
    if language == "de":
        if re.search(r"\b(laa|lpga|olaa|opga)\b", low):
            found.append("critique: sigle français")
        if kind == "rejected":
            if "abgewiesen" not in tail:
                found.append("critique: dispositif, rejet absent")
            if "gutgeheissen" in tail and "abgewiesen" not in tail:
                found.append("critique: dispositif inversé")
        elif kind == "admitted":
            if "gutgeheissen" not in tail:
                found.append("critique: dispositif, admission absente")
            if "abgewiesen" in tail:
                found.append("critique: dispositif inversé")
        elif kind == "partial" and "teilweise" not in low and "zurückgewies" not in low:
            found.append("critique: admission partielle absente")
        cites = CITE_DE.findall(text)
    else:
        if re.search(r"\b(uvg|atsg|uvv|atsv)\b", low):
            found.append("critique: sigle allemand")
        if kind == "rejected":
            if "rejet" not in tail:
                found.append("critique: dispositif, rejet absent")
            if re.search(r"\badmis\b", tail) and "rejet" not in tail:
                found.append("critique: dispositif inversé")
        elif kind == "admitted":
            if not re.search(r"\badmis\b", tail):
                found.append("critique: dispositif, admission absente")
            if "rejet" in tail:
                found.append("critique: dispositif inversé")
        elif kind == "partial" and "partiellement" not in low and "renvoy" not in low:
            found.append("critique: admission partielle absente")
        cites = CITE_FR.findall(text)
    invented = []
    for number, sigil in cites:
        law = TO_CANON[sigil.lower()]
        if not _article_in_source(number, law, source_low):
            invented.append(f"art. {number} {sigil}")
    if invented:
        unique = list(dict.fromkeys(invented))
        found.append("critique: article absent de l'arrêt (" + ", ".join(unique) + ")")
    if "zu mehr als 50" in source_low and "abnützung" in source_low:
        if language == "de":
            if re.search(r"nicht erreicht|weniger als 50|unter 50", low):
                found.append("critique: seuil de 50 % inversé")
            if re.search(r"leistungspflicht nur.{0,220}abnützung", low):
                found.append("critique: condition de l'art. 6 inversée")
        elif re.search(r"pas atteint|non atteint|moins de 50|inférieur à 50", low):
            found.append("critique: seuil de 50 % inversé")
        elif re.search(r"obligation[^.]{0,80}seulement[^.]{0,80}usure|n'existe qu", low):
            found.append("critique: condition de l'art. 6 inversée")
    if re.search(r"art\. 17[^\n]{0,80}statu|statu[^\n]{0,80}art\. 17", low):
        found.append("critique: art. 17 confondu avec le statu quo")
    if language == "de" and "offensichtlich" in low and "offensichtlich" not in source_low:
        found.append("critique: manifestement infondé recopié")
    if (
        language == "fr"
        and "manifestement" in low
        and "manifestement" not in source_low
        and "offensichtlich" not in source_low
    ):
        found.append("critique: manifestement infondé recopié")
    if "demnach erkennt" in low or "par ces motifs" in low or "per questi motivi" in low:
        found.append("critique: bloc du jugement collé")
    if language == "de" and ("le recours" in low or "l'assuré" in low or "l’assuré" in low):
        found.append("critique: fiche en français")
    if language == "fr" and ("die beschwerde" in low or "il ricorso" in low):
        found.append("critique: fiche dans une autre langue")
    foreign_notions = (
        (
            ("causalité adéquate", "adäquater kausal", "kausalzusammenhang adäquat"),
            ("adéquate", "adäquat", "adeguat"),
            "causalité adéquate absente de l'arrêt",
        ),
        (
            ("lésion assimilée", "listenverletzung", "unfallähnliche"),
            ("assimil", "listenverletzung", "unfallähnlich"),
            "lésion assimilée absente de l'arrêt",
        ),
    )
    for fiche_forms, source_forms, label in foreign_notions:
        if any(form in low for form in fiche_forms) and not any(form in source_low for form in source_forms):
            found.append(f"critique: {label}")
    if "unabhängigen arzt" in low and "unabhäng" not in source_low:
        found.append("critique: médecin indépendant absent de l'arrêt")
    if "peut demeurer ouverte" in source_low:
        if language == "de" and not re.search(r"psychisch[^.]{0,120}offen|offen[^.]{0,120}psychisch", low):
            found.append("critique: question laissée ouverte tranchée")
        if language == "fr" and not re.search(r"psychique[^.]{0,160}ouverte|ouverte[^.]{0,160}psychique", low):
            found.append("critique: question laissée ouverte tranchée")
    if "suva" in low and "suva" not in source_low and "cna" not in source_low:
        found.append("critique: Suva absente de l'arrêt")
    if "rixe" in low and "rixe" not in source_low:
        found.append("critique: mot dénué de sens")
    return found


def problems(language: str, text: str) -> list[str]:
    """Écarts nets avec la fiche de 8C_78/2025. Sert à l'essai, pas au score."""
    low = text.lower()
    found: list[str] = []
    if re.search(r"(?m)^\s*[-•]", text):
        found.append("liste à puces")
    if language == "de":
        if "abgewiesen" not in low:
            found.append("recours non rejeté")
        if "zurückverwies" in low or "zurückgewies" in low:
            found.append("renvoi recopié")
        if "uvg" not in low:
            found.append("UVG absent")
        if "atsg" not in low:
            found.append("ATSG absent")
        if "offensichtlich" in low:
            found.append("rejet manifestement infondé recopié")
        if re.search(r"\b(laa|lpga|olaa)\b", low):
            found.append("sigle français dans la fiche allemande")
        if "art. 6 abs. 2" not in low:
            found.append("art. 6 al. 2 absent")
        if "sagittal" in low or "ischio" in low or "hamstring" in low:
            found.append("fait d'un autre arrêt")
        if "mehr als 50" not in low or "abnützung" not in low:
            found.append("seuil de 50 % absent")
        if re.search(r"nicht erreicht|nicht überschritten|weniger als 50|unter 50", low):
            found.append("seuil de 50 % inversé")
        if re.search(r"leistungspflicht nur.{0,220}abnützung", low):
            found.append("condition de l'art. 6 inversée")
        if re.search(r"vermutung[^.]{0,100}art\. 4", low):
            found.append("présomption rattachée à l'art. 4")
        if not re.search(r"februar|15\.", low):
            found.append("seconde chute absente")
        if "richtungsgebende" in low:
            found.append("mauvaise question juridique")
        if low.count("beschwerde wird abgewiesen") > 1:
            found.append("dispositif répété")
        if "suva" not in low:
            found.append("médecin Suva absent")
        if "demnach erkennt" in low or "viscione" in low or "gerichtskosten" in low:
            found.append("bloc du jugement collé")
    else:
        if "rejet" not in low:
            found.append("recours non rejeté")
        if "renvoy" in low:
            found.append("renvoi recopié")
        if "laa" not in low:
            found.append("LAA absent")
        if "lpga" not in low:
            found.append("LPGA absent")
        if "manifestement" in low:
            found.append("rejet manifestement infondé recopié")
        if low.count("recours est rejeté") > 1:
            found.append("dispositif répété")
        if re.search(r"\b(uvg|atsg|uvv)\b", low):
            found.append("sigle allemand dans la fiche française")
        if "art. 6 al. 2" not in low:
            found.append("art. 6 al. 2 absent")
        if "art. 4" not in low:
            found.append("art. 4 absent")
        if "bandelette" in low or "ischio" in low:
            found.append("fait d'un autre arrêt")
        if "plus de 50" not in low or "usure" not in low:
            found.append("seuil de 50 % absent")
        if re.search(r"pas atteint|non atteint|moins de 50|inférieur à 50", low):
            found.append("seuil de 50 % inversé")
        if re.search(r"pr[ée]somption[^.]{0,80}art\. 4", low):
            found.append("présomption rattachée à l'art. 4")
        if "suva" not in low:
            found.append("médecin Suva absent")
        if "expert" not in low:
            found.append("expert privé absent")
        if not re.search(r"deux|second|autre chute|février|fevrier", low):
            found.append("seconde chute absente")
        if "demnach" in low or "viscione" in low or "polla" in low:
            found.append("bloc du jugement collé")
        if re.search(r"art\. 17[^\n]{0,80}statu|statu[^\n]{0,80}art\. 17", low):
            found.append("art. 17 confondu avec le statu quo")
        if "adéquate" in low or "adequate" in low:
            found.append("causalité adéquate inventée")
        if "arrondissement" in low:
            found.append("médecin d'arrondissement inventé")
        if "ouvrier" in low:
            found.append("métier inventé")
        if re.search(r"obligation[^.]{0,80}seulement[^.]{0,80}usure|n'existe qu", low):
            found.append("condition de l'art. 6 inversée")
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


def summarize(docket: str) -> dict:
    rulings, gold = load_tables()
    target = row_for(rulings, docket)
    if docket in FEW_SHOT or docket in EXCLUDED:
        raise SystemExit(f"{docket} sert d'exemple ou est écarté du few-shot")
    if not _court_passes(target["docket"], target["area"]):
        raise SystemExit(f"{docket} ne passe pas le filtre ({target['division']}, {target['area']})")
    out = {
        "docket": docket,
        "model": os.environ["LLM_NAME"],
        "filter": True,
        "languages": {},
    }
    for language in ("de", "fr"):
        examples = [{"docket": shot, "body": gold_body(gold, shot, language)} for shot in FEW_SHOT]
        text = chat(
            [
                {"role": "system", "content": system_prompt(language)},
                {"role": "user", "content": user_prompt(language, examples, target)},
            ]
        )
        forms = required_forms(language, target["text"])
        sense = directions(language, target["text"])
        for _ in range(2):
            issue = _critical(language, text, target["text"], docket)
            if not issue:
                break
            revised = chat(
                [
                    {"role": "system", "content": system_prompt(language)},
                    {
                        "role": "user",
                        "content": repair_prompt(language, text, forms, issue, sense),
                    },
                ]
            )
            revised_issue = _critical(language, revised, target["text"], docket)
            if len(revised_issue) < len(issue):
                text = revised
        issue = review(language, text, target["text"], docket)
        out["languages"][language] = {
            "generated": text,
            "gold": gold_body(gold, docket, language),
            "problems": issue,
        }
        print(f"{language} {len(text)} caractères {issue or 'ok'}", flush=True)
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
            print(f"{index}/{len(dockets)} {docket} déjà écrit", flush=True)
            continue
        print(f"{index}/{len(dockets)} {docket}", flush=True)
        try:
            result = summarize(docket)
        except (SystemExit, TimeoutError, urllib.error.URLError) as exc:
            failed.append(f"{docket}: {exc}")
            print(f"échec {docket}: {exc}", flush=True)
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
