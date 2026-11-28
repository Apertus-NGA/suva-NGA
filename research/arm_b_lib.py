"""Arm B shared: document builder, lesson prompt, rubric questions."""
import re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pandas as pd
from common import load, gold, OUT
from apertus import chat, chat_many, p_yes, M70, M8

def doc(r, facts_cap=1500, reas_cap=20000):
    f = r.facts if len(r.facts) <= facts_cap else r.facts[:facts_cap] + " [...]"
    x = r.reasoning
    if len(x) > reas_cap:
        x = x[:reas_cap - 4000] + "\n[...]\n" + x[-4000:]
    return (f"<urteil dossier=\"{r.docket}\">\n<kopf>\n{r['head'].strip()[:1500]}\n</kopf>\n<sachverhalt>\n{f}\n</sachverhalt>\n"
            f"<erwaegungen>\n{x}\n</erwaegungen>\n<dispositiv>\n{r.dispositive[:800]}\n</dispositiv>\n</urteil>")

SYS_LESSON = ("Du bist Jurist im Rechtsdienst eines Schweizer Unfallversicherers (UVG) und fasst Urteile des "
              "Bundesgerichts für die Schadenpraxis zusammen. Du schreibst sachlich, präzise und auf Deutsch, "
              "auch wenn das Urteil französisch oder italienisch ist. Du stützt dich ausschliesslich auf den Urteilstext.")
EX_DOCKETS = ["8C_180/2025"]  # filled in at runtime by pick_examples

def pick_examples(n=4):
    df = load(); g = gold()
    m = df[df.q == "2025 Q3"].merge(g[g.language == "de"], on="docket")
    m = m[m.cls.isin(["UV", "IV"])].copy()
    m["bl"] = m.body.str.len()
    m = m[(m.bl > 250) & (m.bl < 1100)].sort_values("bl")
    uv = m[m.cls == "UV"].head(n - 1); iv = m[m.cls == "IV"].head(1)
    return pd.concat([uv, iv])

def lesson_prompt(r, examples, version="v2"):
    ex = "\n\n".join(f"<beispiel>\n{b.strip()}\n</beispiel>" for b in examples)
    if version == "v1":
        ins = ("Formuliere die Lehre dieses Urteils in 2 bis 4 Sätzen auf Deutsch: (1) die Rechtsfrage, (2) die Regel, "
               "die das Gericht aufstellt oder anwendet, (3) warum das für einen Unfallversicherer wichtig ist. "
               "Nur was im Urteil steht; keine erfundenen Tatsachen.")
    elif version == "v3":
        ins = ("Formuliere die Lehre dieses Urteils in höchstens 3 Sätzen (maximal 90 Wörter) auf Deutsch, als Fliesstext ohne Einleitung:\n"
               "- Satz 1: die entscheidende Rechtsfrage (welche Leistung oder Verfahrensfrage, welcher Versicherungszweig).\n"
               "- Satz 2: die Regel, die das Bundesgericht aufstellt, präzisiert oder anwendet, mit dem zentralen Artikel und, falls genannt, der Erwägung (E. x.y). "
               "Wenn das Gericht nur die Beweise des Einzelfalls würdigt, sage das.\n"
               "- Satz 3: was ein Unfallversicherer daraus für die Fallführung mitnimmt. Beachte: auch Urteile der Invalidenversicherung sind übertragbar, "
               "wenn der Punkt allgemeines Sozialversicherungsrecht betrifft (Invaliditätsbemessung, Beweiswert von Gutachten, Observation, Revision, Rückerstattung, "
               "ATSG-Verfahren, rechtliches Gehör, Fristen). Nur wenn es um eine reine IV-Leistung geht (z.B. Kinderrente, medizinische Massnahmen), schreibe "
               "\"Keine übertragbare Lehre für die Unfallversicherung.\"\n"
               "Verwende nur, was im Urteilstext steht: keine erfundenen Tatsachen, Zahlen, Artikel oder Urteilszitate. Keine Personennamen.")
    elif version == "v4":
        ins = ("Formuliere die Lehre dieses Urteils in höchstens 3 Sätzen (maximal 90 Wörter) auf Deutsch, als Fliesstext ohne Einleitung:\n"
               "- Satz 1: die entscheidende Rechtsfrage (welche Leistung oder Verfahrensfrage, welcher Versicherungszweig).\n"
               "- Satz 2: die Regel, die das Bundesgericht aufstellt, präzisiert oder anwendet, mit dem zentralen Artikel und, falls genannt, der Erwägung (E. x.y). "
               "Wenn das Gericht nur die Beweise des Einzelfalls würdigt, sage das.\n"
               "- Satz 3: was ein Unfallversicherer daraus für die Fallführung mitnimmt. Bei Urteilen der Invalidenversicherung: nenne den Punkt, der auch in der "
               "Unfallversicherung gilt (z.B. Invaliditätsbemessung, Beweiswert von Gutachten, Observation, Revision, Rückerstattung, ATSG-Verfahren, rechtliches Gehör, Fristen); "
               "betrifft das Urteil ausschliesslich eine IV-eigene Leistung (z.B. Kinderrente, medizinische Massnahmen, Eingliederung), sage in Satz 3 stattdessen, dass der Punkt IV-spezifisch ist.\n"
               "Verwende nur, was im Urteilstext steht: keine erfundenen Tatsachen, Zahlen, Artikel oder Urteilszitate. Keine Personennamen.")
    else:
        ins = ("Formuliere die Lehre dieses Urteils in 2 bis 4 Sätzen auf Deutsch, als Fliesstext ohne Aufzählung und ohne Einleitung:\n"
               "- Satz 1: die entscheidende Rechtsfrage (worüber wurde gestritten, welche Leistung oder Verfahrensfrage, welcher Versicherungszweig).\n"
               "- Satz 2-3: die Regel, die das Bundesgericht aufstellt, präzisiert oder anwendet, mit den zentralen Artikeln (z.B. Art. 6 UVG, Art. 17 ATSG) "
               "und, falls genannt, der Erwägung (E. x.y); sage, ob es eine allgemeine Regel ist oder nur eine Würdigung des Einzelfalls.\n"
               "- Letzter Satz: was ein Unfallversicherer daraus für die Fallführung mitnimmt; wenn das Urteil nur die Invalidenversicherung betrifft "
               "oder nichts Übertragbares enthält, sage das ausdrücklich.\n"
               "Verwende nur, was im Urteilstext steht: keine erfundenen Tatsachen, Zahlen, Artikel oder Urteilszitate. Keine Namen von Personen.")
    return [{"role": "system", "content": SYS_LESSON},
            {"role": "user", "content": f"{doc(r)}\n\nSo formuliert unser Rechtsdienst solche Lehren (Stilbeispiele zu ANDEREN Urteilen, nicht inhaltlich übernehmen):\n\n{ex}\n\n{ins}"}]

SYS_Q = ("Du bist Jurist im Rechtsdienst eines Schweizer Unfallversicherers (UVG) und prüfst Urteile des Bundesgerichts "
         "anhand eng gefasster Kriterien. Du beantwortest genau die gestellte Frage, gestützt nur auf den vorgelegten Text.")

QUESTIONS = {
 "q_transfer": ("Ist der entschiedene Punkt auf die Praxis der Unfallversicherung (UVG) anwendbar und nicht nur auf die Invalidenversicherung?",
   "Ja: das Urteil betrifft UVG-Leistungen oder eine Frage, die sich in der Unfallversicherung gleich stellt (Invaliditätsbemessung/Einkommensvergleich, Beweiswert von Gutachten, Hilflosenentschädigung, Revision/Wiedererwägung, Rückerstattung, ATSG-Verfahren, Fristen). "
   "Nein: der Punkt betrifft nur IV-spezifische Leistungen oder Regeln (z.B. Kinderrente, medizinische Massnahmen, Eingliederungsmassnahmen der IV, Assistenzbeitrag, Versicherungsunterstellung/Beitragszeiten der IV)."),
 "q_rule": ("Stellt das Gericht eine allgemeine Regel auf, präzisiert oder klärt es eine solche, statt nur die Beweise und Tatsachen dieses Einzelfalls zu überprüfen?",
   "Ja: das Urteil enthält eine über den Fall hinaus verwendbare rechtliche Aussage (Auslegung einer Norm, Abgrenzungskriterium, Methode), die das Ergebnis trägt. "
   "Nein: das Gericht gibt nur die bekannte Standardrechtsprechung wieder und prüft dann, ob die Vorinstanz die Akten/Gutachten willkürfrei gewürdigt hat."),
 "q_practice": ("Wirkt sich das Urteil darauf aus, wie ein Versicherer Fälle bearbeiten soll?",
   "Ja: das Urteil enthält eine konkrete Vorgabe zu Verfahren, Abklärungspflicht, Fristen, Berechnungsmethode (z.B. versicherter Verdienst, Einkommensvergleich, Tabellenlöhne), Einholung/Verwertung von Gutachten, Leistungseinstellung, Kürzung oder Rückerstattung. "
   "Nein: es ergibt sich keine Handlungsanweisung über den entschiedenen Einzelfall hinaus."),
 "q_new": ("Entscheidet das Gericht eine bisher nicht geklärte Frage, oder präzisiert bzw. ändert es ausdrücklich seine Rechtsprechung?",
   "Ja: das Gericht sagt ausdrücklich, dass die Frage bisher offen war, oder es präzisiert, bestätigt nach vertiefter Prüfung oder ändert seine Praxis, oder es legt eine Norm erstmals aus. "
   "Nein: das Urteil wendet nur gefestigte Rechtsprechung an."),
 "q_insurer_lost": ("Wurde der Standpunkt des Versicherers bzw. der Behörde (Unfallversicherer, IV-Stelle) vom Bundesgericht ganz oder teilweise verworfen?",
   "Ja: das Bundesgericht entscheidet ganz oder teilweise gegen den Versicherer/die Behörde (Beschwerde der versicherten Person gutgeheissen oder Sache zurückgewiesen, oder Beschwerde des Versicherers abgewiesen). "
   "Nein: der Versicherer/die Behörde obsiegt vollständig."),
 "q_factual": ("Geht es im Streit im Wesentlichen um die Würdigung medizinischer Beweise im Einzelfall?",
   "Ja: Kern des Urteils ist, ob bestimmte Arztberichte/Gutachten in diesem Fall beweiskräftig sind, wie arbeitsfähig die Person ist oder ob der Gesundheitsschaden in diesem Fall unfallkausal ist, ohne neue rechtliche Aussage. "
   "Nein: im Zentrum steht eine Rechtsfrage (Auslegung, Methode, Verfahren, Berechnung)."),
 "q_newsletter": ("Würde der Rechtsdienst eines Unfallversicherers dieses Urteil in seine vierteljährliche Auswahl lehrreicher Urteile für die Schadensachbearbeitenden aufnehmen?",
   "Ja: das Urteil enthält eine Lehre, die Sachbearbeitende in künftigen Unfallversicherungsfällen wiederverwenden können (auch die anschauliche Anwendung einer wichtigen Regel auf eine typische Konstellation). "
   "Nein: Routinefall ohne wiederverwendbare Lehre, oder Thema ausserhalb der Unfallversicherungspraxis."),
 "q_routine": ("Ist das Urteil ein Routineentscheid, der bloss den vorinstanzlichen Entscheid mit Standarderwägungen bestätigt?",
   "Ja: die Beschwerde wird abgewiesen (oder es wird nicht darauf eingetreten), die Erwägungen beschränken sich auf Textbausteine zur Kognition und die Feststellung, die Rügen seien unbegründet oder appellatorisch. "
   "Nein: das Gericht setzt sich vertieft mit einer Rechtsfrage auseinander, heisst die Beschwerde gut oder weist die Sache zurück."),
 "q_uvcore": ("Behandelt das Urteil in der Sache eine Kernfrage des Unfallversicherungsrechts?",
   "Ja: Unfallbegriff oder unfallähnliche Körperschädigung, natürlicher/adäquater Kausalzusammenhang, Rückfall/Spätfolgen, Fallabschluss, Heilbehandlung, Taggeld, versicherter Verdienst, Invalidenrente UVG, Integritätsentschädigung, Berufskrankheit, Kürzung wegen Wagnis/Grobfahrlässigkeit, Versicherungsdeckung, Zuständigkeit der Versicherer. "
   "Nein: das Urteil behandelt keine dieser Fragen in der Sache (z.B. nur Prozessuales wie Eintreten, Kosten, unentgeltliche Rechtspflege, oder nur IV-Themen)."),
}

def q_prompt(body, q, fmt):
    frage, defi = QUESTIONS[q]
    if fmt == "label":
        tail = "Antworte nur mit einem Wort: Ja oder Nein."
    else:
        tail = ("Begründe zuerst in genau einem Satz mit Bezug auf den Text. Schreibe danach auf einer neuen Zeile "
                "\"Antwort: Ja\" oder \"Antwort: Nein\".")
    return [{"role": "system", "content": SYS_Q},
            {"role": "user", "content": f"{body}\n\nFrage: {frage}\nDefinition: {defi}\n\n{tail}"}]

def q_job(model, body, q, fmt, tag):
    return dict(model=model, messages=q_prompt(body, q, fmt), tag=tag, logprobs=True, top_logprobs=10,
                max_tokens=4 if fmt == "label" else 130)

import math
def parse_q(res, fmt):
    """returns (p_ja, hard 0/1, text)"""
    t = res.get("text")
    if t is None:
        return (None, None, None)
    if fmt == "label":
        p = p_yes(res)
        h = None
        w = t.strip().lower()
        if w.startswith("ja"): h = 1
        elif w.startswith("nein"): h = 0
        if p is None and h is not None: p = float(h)
        return (p, h, t)
    m = re.findall(r"Antwort\s*:?\s*\**\s*(Ja|Nein)", t, re.I)
    h = None if not m else int(m[-1].lower() == "ja")
    p = None
    lp = res.get("logprobs") or []
    for i in range(len(lp) - 1, -1, -1):
        if lp[i]["token"].strip().lower().strip('."*:') in ("ja", "nein"):
            p = p_yes(res, position=i); break
    if p is None and h is not None: p = float(h)
    return (p, h, t)
