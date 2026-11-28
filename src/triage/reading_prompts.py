"""Prompt texts and document builders of the Apertus readings (triage step 3).

# ruff: noqa: E501, E701, E702
The texts are kept exactly as they were measured (docs/TRIAGE_PIPELINE.md): a changed character is a new
prompt version and a new measurement. German on purpose: the rulings and the lawyers are German-speaking
first, and the readings were developed in German. Ruling text is data: it is delimited by tags.
"""
# ruff: noqa: E501, E701, E702

from __future__ import annotations

import re

from src.signals.structural import header

RE_REASON = re.compile(
    r"\n\s*(Erwägungen|Erwägung|Considérant en droit|Considérants?|En droit|Diritto|Considerando in diritto|Considerando)\s*:?\s*\n",
    re.I,
)
RE_DISP = re.compile(r"(Demnach erkennt|Demnach verfügt|Demnach beschliesst|Par ces motifs|Per questi motivi)")


def sections(t: str) -> dict:
    md = None
    for m in RE_DISP.finditer(t):
        md = m
    end = md.start() if md else len(t)
    h = header(t)
    mr = RE_REASON.search(t[:end])
    start = mr.end() if mr else len(h)
    facts = t[len(h) : mr.start()] if mr and mr.start() > len(h) else ""
    return {"head": h, "facts": facts.strip(), "reasoning": t[start:end].strip(), "dispositive": t[end:].strip()}


def doc(r: dict, reas_cap: int = 20000, facts_cap: int = 1500) -> str:
    x = r["reasoning"]
    if len(x) > reas_cap:
        x = x[: reas_cap - 4000] + "\n[... gekürzt ...]\n" + x[-4000:]
    f = r["facts"] if len(r["facts"]) <= facts_cap else r["facts"][:facts_cap] + " [... gekürzt ...]"
    return (
        f"<urteil>\n<kopf>\n{re.sub(r'[ \\t\\u00a0]*\\n\\s*', chr(10), r['head']).strip()[-1500:]}\n</kopf>\n<sachverhalt>\n{f}\n</sachverhalt>\n"
        f"<erwaegungen>\n{x}\n</erwaegungen>\n<dispositiv>\n{r['dispositive'][:800]}\n</dispositiv>\n</urteil>"
    )


SYS = (
    "Du bist eine erfahrene Juristin der Rechtsabteilung der Suva (Schweizerische Unfallversicherungsanstalt). Du wählst jedes Quartal die "
    "Bundesgerichtsurteile aus, die in die Rechtsprechungsübersicht für die Fallführung in der Unfallversicherung aufgenommen werden. "
    "Du stützt dich nur auf den vorgelegten Urteilstext und die geprüften Angaben."
)

RUBRIC = """So wählt die Rechtsabteilung aus:
- Urteile der Unfall- und Militärversicherung werden in rund 6 von 10 Fällen aufgenommen, gleichgültig ob die Suva oder ein anderer Versicherer Partei ist.
- Urteile der Invalidenversicherung werden nur in rund 1 von 10 Fällen aufgenommen: dann, wenn der entschiedene Punkt auch in der Unfallversicherung gilt (Invaliditätsbemessung, Beweiswert und Form von Gutachten, Hilflosenentschädigung, Revision, Rückerstattung, ATSG-Verfahren, Fristen) und das Gericht dazu eine verwertbare Aussage macht.
- Stark dafür sprechen: Beschwerde eines Versicherers oder einer Behörde; fünf Richter; zur Publikation vorgesehen; das Gericht stellt eine Regel auf, präzisiert sie oder entscheidet eine offene Frage; es korrigiert die Vorinstanz in einem Rechtspunkt.
- Dagegen sprechen: Einzelrichterentscheid (praktisch nie aufgenommen); als offensichtlich unbegründet erledigt; reine Würdigung medizinischer Akten ohne rechtliche Aussage; rein IV-spezifische Leistung."""
Q = "Frage: Nimmt die Rechtsabteilung der Suva dieses Urteil in ihre Rechtsprechungsübersicht auf?\nAntworte mit genau einem Wort: Ja oder Nein."

SYS_L = (
    "Du bist eine erfahrene Juristin im Rechtsdienst eines Schweizer Unfallversicherers. Du liest Urteile des Bundesgerichts und beurteilst nüchtern, "
    "ob sie für die Fallführung in der Unfallversicherung etwas Neues lehren. Du lässt dich nicht davon beeindrucken, dass ein Urteil lang ist oder viele "
    "Rechtssätze zitiert: Die meisten Urteile wenden nur Bekanntes an. Du stützt dich ausschliesslich auf den vorgelegten Text."
)


def tail_doc(r):
    x = r["reasoning"]
    x = x[int(len(x) * 0.35) :] if len(x) > 6000 else x
    if len(x) > 16000:
        x = x[:12000] + "\n[... gekürzt ...]\n" + x[-4000:]
    head = re.sub(r"[ \t ]*\n\s*", "\n", r["head"]).strip()[-900:]
    return f"<urteil>\n<kopf>\n{head}\n</kopf>\n<erwaegungen_ab_der_eigentlichen_pruefung>\n{x}\n</erwaegungen_ab_der_eigentlichen_pruefung>\n<dispositiv>\n{r['dispositive'][:800]}\n</dispositiv>\n</urteil>"


SCALE_GENERIC = """Wie viel lehrt dieses Urteil über den Einzelfall hinaus? Wähle eine Stufe:
1 = Routine. Das Gericht gibt Standarderwägungen wieder und prüft, ob die Vorinstanz die Akten und Gutachten dieses Falls vertretbar gewürdigt hat. Auch wenn dabei viele Rechtssätze zitiert werden: nichts davon ist neu.
2 = Im Wesentlichen Routine, mit einer kurzen rechtlichen Bemerkung, die aber nur Bekanntes wiederholt.
3 = Das Gericht wendet eine bekannte Regel auf eine nicht alltägliche Konstellation an und sagt dazu etwas Verwertbares.
4 = Das Gericht präzisiert oder begrenzt eine Regel, legt eine Norm aus oder korrigiert die Vorinstanz in einem Rechtspunkt, und diese Aussage trägt das Ergebnis.
5 = Grundsatzentscheid: neue Regel, Änderung oder ausdrückliche Präzisierung der Rechtsprechung, oder erstmalige Klärung einer offenen Frage.
Die grosse Mehrheit der Urteile gehört zu Stufe 1 oder 2.

Antworte nur mit einer Ziffer von 1 bis 5."""


def scale_area(r):
    if r["uvmv"]:
        return """Dieses Urteil betrifft die Unfall- oder Militärversicherung. Ein Rechtsdienst nimmt rund 6 von 10 solcher Urteile in seine Übersicht auf; weggelassen werden reine Aktenfälle.
Wie wahrscheinlich gehört dieses Urteil in die Übersicht? Wähle eine Stufe:
1 = sicher nicht: reiner Aktenfall (z.B. Kausalität oder Arbeitsfähigkeit anhand der Arztberichte dieses Falls), Beschwerde offensichtlich unbegründet oder rein prozessual erledigt.
2 = eher nicht: Standardfall ohne verwertbare rechtliche Aussage.
3 = offen: typischer Fall, der eine bekannte Regel anschaulich anwendet.
4 = eher ja: enthält eine rechtliche Aussage zu Leistungen, Verfahren oder Berechnung, die sich auf andere Fälle übertragen lässt, oder der Versicherer unterliegt in einem Rechtspunkt.
5 = sicher ja: Grundsatzfrage, neue oder präzisierte Regel, ungewöhnliche Konstellation.

Antworte nur mit einer Ziffer von 1 bis 5."""
    return """Dieses Urteil betrifft die Invalidenversicherung. Ein Rechtsdienst der Unfallversicherung nimmt nur rund 1 von 10 solcher Urteile in seine Übersicht auf: nur wenn das Gericht eine rechtliche Aussage macht, die genauso in der Unfallversicherung gilt (z.B. zu Invaliditätsbemessung und Einkommensvergleich, Form und Beweiswert von Gutachten, Hilflosenentschädigung, Revision, Rückerstattung, Verfahrenspflichten, Fristen, Kosten).
Wie wahrscheinlich gehört dieses Urteil in die Übersicht? Wähle eine Stufe:
1 = sicher nicht: das Gericht würdigt nur die medizinischen Akten dieses Falls, oder es geht um eine Leistung, die es nur in der IV gibt.
2 = eher nicht: Standardfall; die zitierten Regeln sind bekannt und werden nur angewendet.
3 = offen: bekannte Regel, auf eine nicht alltägliche Konstellation angewendet, die auch in der Unfallversicherung vorkommen kann.
4 = eher ja: das Gericht präzisiert oder begrenzt eine Regel, die auch in der Unfallversicherung gilt, oder korrigiert die Vorinstanz oder die Verwaltung in einem solchen Rechtspunkt.
5 = sicher ja: Grundsatzfrage oder neue Regel mit Bedeutung über die IV hinaus.
Die grosse Mehrheit gehört zu Stufe 1 oder 2.

Antworte nur mit einer Ziffer von 1 bis 5."""


SCALE_HEADNOTE = """Stell dir vor, du müsstest zu diesem Urteil einen Leitsatz für Kolleginnen und Kollegen schreiben, der ihnen in künftigen Fällen hilft.
Wie gehaltvoll wäre dieser Leitsatz? Wähle eine Stufe:
1 = Es gäbe keinen: Der Leitsatz könnte nur lauten "Beschwerde abgewiesen, Beweiswürdigung der Vorinstanz nicht zu beanstanden".
2 = Er würde nur einen längst bekannten Rechtssatz wiederholen.
3 = Er würde eine bekannte Regel an einer anschaulichen, nicht alltäglichen Konstellation zeigen.
4 = Er würde eine Präzisierung, Abgrenzung oder Berechnungsweise festhalten, die man so noch nicht überall nachlesen kann.
5 = Er würde eine neue Regel oder eine Praxisänderung festhalten.
Die meisten Urteile ergeben Stufe 1 oder 2.

Antworte nur mit einer Ziffer von 1 bis 5."""
YES_STRICT = """Frage: Trifft das Bundesgericht in diesem Urteil eine eigene rechtliche Aussage, die über den Einzelfall hinaus verwendbar ist?
Zähle NICHT: die Wiedergabe gefestigter Rechtsprechung ("nach der Rechtsprechung ...", "praxisgemäss ..."), Ausführungen zur Kognition und zum Beweisgrad, die Würdigung von Arztberichten und Gutachten dieses Falls, die Feststellung, eine Rüge sei unbegründet.
Zähle: Das Gericht legt eine Norm aus, zieht eine Grenze, legt eine Berechnungs- oder Vorgehensweise fest, korrigiert die Vorinstanz oder die Verwaltung in einem Rechtspunkt, oder entscheidet eine Frage, die es als offen bezeichnet.
In rund zwei Dritteln der Urteile lautet die Antwort Nein.

Antworte mit genau einem Wort: Ja oder Nein."""
