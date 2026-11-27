"""Arm H: seven more 'principle versus routine' questions, to test whether averaging several noisy Apertus judgements gives a stronger feature.
usage: arm_h_more.py lab|q2"""
import sys, time
import pandas as pd
import arm_b_lib as B
from common import load, OUT
from apertus import chat_many, M70

NEW = {
 "q_legalq": ("Ist die für den Ausgang entscheidende Streitfrage eine Rechtsfrage und nicht eine Tatfrage?",
   "Ja: entscheidend ist die Auslegung oder der Anwendungsbereich einer Norm, eine Berechnungs- oder Bemessungsmethode oder eine Verfahrensfrage. "
   "Nein: entscheidend ist, wie Arztberichte, Gutachten oder andere Beweise in diesem Einzelfall zu würdigen sind."),
 "q_headnote": ("Lässt sich aus dem Urteil ein Leitsatz formulieren, der über den Einzelfall hinaus gilt und nicht bloss bekannte Standardrechtsprechung wiederholt?",
   "Ja: es gibt eine eigenständige, verallgemeinerbare Aussage des Gerichts (Kriterium, Abgrenzung, Methode, Verfahrensregel). "
   "Nein: ein Leitsatz würde nur gefestigte Rechtsprechung wiederholen oder sich im Ergebnis des Einzelfalls erschöpfen."),
 "q_depth": ("Setzt sich das Gericht in mindestens einer Erwägung vertieft mit einer Rechtsfrage auseinander?",
   "Ja: eigene Argumentation des Gerichts zu einer Rechtsfrage, z.B. Auslegung nach Wortlaut/Zweck/Systematik, Auseinandersetzung mit Lehre, Materialien, Verwaltungsweisungen oder abweichender Rechtsprechung. "
   "Nein: die rechtlichen Erwägungen bestehen aus Textbausteinen und Verweisen, die eigentliche Prüfung betrifft die Akten."),
 "q_unusual": ("Betrifft das Urteil eine ungewöhnliche oder selten beurteilte Konstellation?",
   "Ja: besonderer Sachverhalt, besondere Leistungsart, besondere Beteiligte oder besondere Verfahrenslage, die nicht dem Alltag der Fallbearbeitung entspricht. "
   "Nein: typischer Fall (z.B. Leistungseinstellung nach Unfall, Rentenanspruch nach Begutachtung) ohne Besonderheit."),
 "q_corrects": ("Korrigiert das Bundesgericht die Vorinstanz oder den Versicherer in einem rechtlichen Punkt?",
   "Ja: das Bundesgericht hält fest, dass die Vorinstanz oder der Versicherer das Recht falsch angewendet hat (falsche Methode, falsches Kriterium, Verfahrensfehler, Verletzung von Bundesrecht ausserhalb der blossen Beweiswürdigung). "
   "Nein: das Bundesgericht bestätigt die rechtliche Beurteilung oder beanstandet höchstens die Sachverhaltsabklärung."),
 "q_learn": ("Würde eine erfahrene Fachperson für Unfallversicherungsrecht aus diesem Urteil etwas lernen, das sie nicht bereits aus der gefestigten Rechtsprechung kennt?",
   "Ja: das Urteil enthält eine neue, präzisierte oder selten ausgesprochene rechtliche Aussage oder eine lehrreiche Anwendung auf eine nicht alltägliche Konstellation. "
   "Nein: das Urteil bestätigt Bekanntes; rund die Hälfte aller Urteile fällt in diese Kategorie."),
 "q_stdonly": ("Bestehen die rechtlichen Erwägungen im Wesentlichen aus der Wiedergabe gefestigter Rechtsprechung, gefolgt von deren Anwendung auf die Akten des Einzelfalls?",
   "Ja: Standardaufbau ohne eigene rechtliche Weiterentwicklung. Nein: das Gericht entwickelt, präzisiert oder begrenzt eine Regel."),
}
B.QUESTIONS.update(NEW)
stage = sys.argv[1]; df = load()
part = df[df.labelled & df.cand] if stage == "lab" else df[(df.q == "2026 Q2") & df.cand]
jobs = [(r.id, q) for _, r in part.iterrows() for q in NEW]; bodies = {r.id: B.doc(r) for _, r in part.iterrows()}
t = time.time(); res = chat_many([B.q_job(M70, bodies[i], q, "label", "more_label") for i, q in jobs], workers=8, progress=200)
rows = {}; bad = 0
for (i, q), x in zip(jobs, res):
    p, h, _ = B.parse_q(x, "label"); bad += p is None; rows.setdefault(i, {"id": i})[q] = p
pd.DataFrame(rows.values()).to_parquet(OUT / f"more_answers_{stage}.parquet"); print("done", stage, len(rows), "unparsed", bad, "secs", round(time.time() - t), flush=True)
