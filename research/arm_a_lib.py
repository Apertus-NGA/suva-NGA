"""Arm A: Apertus decides relevance on its own. Prompt builders, runner, parser."""
from __future__ import annotations
import re, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load, gold, OUT  # noqa
from apertus import chat_many, p_yes, M70, M70T, M8  # noqa

SYS = ("Du bist eine erfahrene Juristin in der Rechtsabteilung der Suva (Schweizerische Unfallversicherungsanstalt). "
       "Du sichtest neue Urteile des Bundesgerichts und entscheidest, welche in die Rechtsprechungsübersicht für die "
       "Unfallversicherungspraxis aufgenommen werden. Du stützt dich ausschliesslich auf den vorgelegten Urteilstext.")

Q_PLAIN = ("Ist dieses Urteil für die Suva relevant, das heisst: Soll es in die Rechtsprechungsübersicht der Suva "
           "aufgenommen werden?")

RUBRIC = """Die Juristinnen und Juristen der Suva wählen Urteile aus, die eine wiederverwendbare Lehre für die Praxis der Unfallversicherung enthalten.

Erfahrungswerte:
- Urteile aus der Unfallversicherung (UVG) oder Militärversicherung werden mehrheitlich aufgenommen (rund 6 von 10), unabhängig davon, ob die Suva oder ein anderer Unfallversicherer Partei ist.
- Urteile aus der Invalidenversicherung (IV) werden nur selten aufgenommen (rund 1 von 10): nur dann, wenn sich die Aussage auf die Unfallversicherung übertragen lässt (Invaliditätsbemessung, Beweiswert von Gutachten, Hilflosenentschädigung, Revision, Rückerstattung, ATSG-Verfahrensrecht, Fristen). Reine IV-Leistungsfragen (z.B. Eingliederungsmassnahmen, medizinische Massnahmen der IV, IV-spezifische Renten- oder Beitragsfragen) sind nicht relevant.

Zeichen FÜR Relevanz:
- Die Suva ist Partei oder wird im Urteil erwähnt; ein anderer Unfallversicherer ist Partei.
- Die Beschwerde wurde von einem Versicherer oder einer Behörde erhoben.
- Besetzung mit fünf Richterinnen und Richtern; Urteil zur Publikation vorgesehen.
- Kernthemen: Kausalzusammenhang, Unfallbegriff, Invalidenrente/Invaliditätsgrad, Integritätsentschädigung, Beweiswert von Gutachten.
- Das Gericht stellt eine Regel auf, präzisiert oder ändert die Rechtsprechung; ausführliche rechtliche Begründung.
- Die Beschwerde wird (teilweise) gutgeheissen.

Zeichen GEGEN Relevanz:
- Das Gericht prüft nur die Beweiswürdigung des Einzelfalls, ohne rechtliche Aussage von allgemeiner Bedeutung.
- Die Beschwerde wird als offensichtlich unbegründet abgewiesen (besonders bei IV-Urteilen).
"""

FMT_RAT = ("Antworte genau in diesem Format und mit nichts anderem:\n"
           "Begründung: <ein Satz, gestützt auf den Urteilstext>\n"
           "Entscheid: <Ja oder Nein>\n"
           "Score: <ganze Zahl von 0 bis 100; Wahrscheinlichkeit, dass die Suva das Urteil aufnimmt>")
STRICT = """Wichtig: Auch in der Unfallversicherung werden rund 4 von 10 Urteilen NICHT aufgenommen. Das sind Routinefälle: Das Gericht bestätigt bloss die Beweiswürdigung der Vorinstanz im Einzelfall (z.B. medizinische Aktenlage, natürlicher Kausalzusammenhang im konkreten Fall), wendet nur bekannte Rechtsprechung an, weist die Beschwerde der versicherten Person ohne neue rechtliche Aussage ab oder erledigt sie als offensichtlich unbegründet (Art. 109 BGG). Dass ein Urteil ein Kernthema berührt, genügt nicht. Formulierungen wie "das Urteil präzisiert" darfst du nur verwenden, wenn das Gericht dies ausdrücklich tut.
"""
FMT_CHECK = ("Antworte genau in diesem Format und mit nichts anderem:\n"
             "Gebiet: <UV, MV oder IV>\n"
             "Beschwerdeführer: <versicherte Person, Versicherer oder Behörde>\n"
             "Ausgang: <gutgeheissen, teilweise gutgeheissen, abgewiesen oder nicht eingetreten>\n"
             "Besetzung: <Anzahl Richterinnen und Richter>\n"
             "Kern des Urteils: <Rechtsfrage oder Beweiswürdigung im Einzelfall>\n"
             "Übertragbare Lehre: <ein Satz; oder 'keine'>\n"
             "Begründung: <ein Satz>\n"
             "Entscheid: <Ja oder Nein>\n"
             "Score: <ganze Zahl von 0 bis 100; Wahrscheinlichkeit, dass die Suva das Urteil aufnimmt>")
FMT_LABEL = "Antworte mit genau einem Wort: Ja oder Nein."


AREA_IV = """Dieses Urteil stammt aus der Invalidenversicherung (IV). Die Suva nimmt IV-Urteile nur ausnahmsweise in ihre Rechtsprechungsübersicht auf (rund 1 von 10): nur wenn das Gericht eine Rechtsaussage macht, die über den Einzelfall hinausgeht und sich direkt auf die Unfallversicherung übertragen lässt (Invaliditätsbemessung und Tabellenlöhne, Beweiswert und Anforderungen an Gutachten, Hilflosenentschädigung, Revision und Wiedererwägung, Rückerstattung, ATSG-Verfahrensrecht, Fristen und Zustellung). Nicht aufgenommen werden Urteile, die bloss die Beweiswürdigung im Einzelfall überprüfen, bekannte Rechtsprechung anwenden, IV-spezifische Leistungen betreffen (Eingliederung, medizinische Massnahmen, Hilfsmittel, Assistenzbeitrag) oder die Beschwerde als offensichtlich unbegründet abweisen.

Frage: Enthält dieses IV-Urteil eine solche auf die Unfallversicherung übertragbare, über den Einzelfall hinausgehende Rechtsaussage, so dass die Suva es aufnimmt?"""
AREA_UV = """Dieses Urteil stammt aus der Unfall- oder Militärversicherung. Die Suva nimmt rund 6 von 10 solcher Urteile in ihre Rechtsprechungsübersicht auf. NICHT aufgenommen werden Routinefälle: Das Gericht bestätigt bloss die Beweiswürdigung der Vorinstanz im Einzelfall, wendet nur bekannte Rechtsprechung an, weist die Beschwerde der versicherten Person ohne neue rechtliche Aussage ab oder erledigt sie als offensichtlich unbegründet (Art. 109 BGG). Für die Aufnahme sprechen: Beschwerde eines Versicherers, (teilweise) Gutheissung, Fünferbesetzung, Publikation, eine aufgestellte oder präzisierte Regel.

Frage: Geht dieses Urteil über einen Routinefall hinaus, so dass die Suva es aufnimmt?"""


def _ws(s: str) -> str:
    return re.sub(r"[ \t\xa0]+", " ", re.sub(r"\s*\n\s*", "\n", s or "")).strip()


def doc_text(r, mode: str) -> str:
    if mode == "full":
        return _ws(r["text"])
    rs = _ws(r["reasoning"])
    if len(rs) > 12000:
        rs = rs[:8000] + "\n[...]\n" + rs[-4000:]
    return "KOPF:\n" + _ws(r["head"])[-1200:] + "\n\nERWÄGUNGEN:\n" + rs + "\n\nDISPOSITIV:\n" + _ws(r["dispositive"])[:900]


_FS = None
def fewshot_block(n_uv: int = 3, n_iv: int = 2) -> str:
    """German Suva summaries of rulings decided in 2025 Q3 only (leakage rule)."""
    global _FS
    if _FS is None:
        df = load(); g = gold()
        q3 = df[df.q == "2025 Q3"][["docket", "cls"]]
        assert not set(q3.docket) & set(df[df.labelled].docket)
        m = g[g.language == "de"].merge(q3, on="docket").sort_values("docket")
        m = m[m.body.str.len().between(400, 2500)]
        rs = np.random.RandomState(7)
        pick = pd.concat([m[m.cls == "UV"].sample(n_uv, random_state=rs), m[m.cls == "IV"].sample(n_iv, random_state=rs)])
        pick = pick.sample(frac=1, random_state=rs)
        name = {"UV": "Unfallversicherung", "IV": "Invalidenversicherung"}
        _FS = "\n\n".join(f"<beispiel gebiet=\"{name[c]}\" urteil=\"{d}\">\n{_ws(b)[:1100]}\n</beispiel>"
                          for d, c, b in zip(pick.docket, pick.cls, pick.body))
    return _FS


def messages(r, prompt: str, inp: str, out: str) -> list[dict]:
    u = "<urteil>\n" + doc_text(r, inp) + "\n</urteil>\n\n"
    if prompt in ("rubric", "fewshot", "strict", "check"):
        u += RUBRIC + "\n"
    if prompt in ("strict", "check"):
        u += STRICT + "\n"
    if prompt == "fewshot":
        u += ("Beispiele: Zusammenfassungen früherer Urteile, die die Suva aufgenommen hat (alle diese Beispiele waren relevant; "
              "die meisten Urteile werden aber NICHT aufgenommen):\n\n" + fewshot_block() + "\n\n")
    if prompt == "area":
        return [{"role": "system", "content": SYS}, {"role": "user", "content": u + (AREA_IV if r["cls"] == "IV" else AREA_UV) + "\n\n" + (FMT_LABEL if out == "label" else FMT_RAT)}]
    u += "Frage: " + Q_PLAIN + "\n\n" + (FMT_LABEL if out == "label" else FMT_CHECK if prompt == "check" else FMT_RAT)
    return [{"role": "system", "content": SYS}, {"role": "user", "content": u}]


def parse(text: str | None) -> dict:
    t = text or ""
    md = re.search(r"Entscheid\W*\s*(Ja|Nein|Oui|Non)", t, re.I)
    ms = re.search(r"Score\W*\s*(\d{1,3})", t, re.I)
    mr = re.search(r"Begründung\W*\s*(.+?)(?:\n\s*\**Entscheid|$)", t, re.S | re.I)
    dec = None if not md else int(md.group(1).lower() in ("ja", "oui"))
    if dec is None:
        m2 = re.match(r"\W*(Ja|Nein)\b", t.strip(), re.I)
        dec = None if not m2 else int(m2.group(1).lower() == "ja")
    return {"decision": dec, "score": float(ms.group(1)) if ms else np.nan, "rationale": mr.group(1).strip() if mr else t.strip()[:600]}


def run(rows: pd.DataFrame, name: str, model=M70, prompt="rubric", inp="trim", out="rat", workers=8) -> pd.DataFrame:
    jobs = []
    for _, r in rows.iterrows():
        kw = dict(model=model, messages=messages(r, prompt, inp, out), tag="arm_a_" + name)
        if model.endswith("thinking"):
            kw.update(temperature=0.6, top_p=0.95, max_tokens=6000)
        elif out == "label":
            kw.update(max_tokens=3, logprobs=True, top_logprobs=10)
        else:
            kw.update(max_tokens=350 if prompt == "check" else 220)
        jobs.append(kw)
    res = chat_many(jobs, workers=workers, progress=50)
    recs = []
    for (_, r), x in zip(rows.iterrows(), res):
        p = parse(x["text"])
        py = p_yes(x) if out == "label" else None
        recs.append({"id": r["id"], "decision": p["decision"], "score": p["score"], "p_yes": py, "rationale": p["rationale"],
                     "raw": x["text"], "error": x.get("error"), "ptok": (x.get("usage") or {}).get("prompt_tokens"),
                     "ctok": (x.get("usage") or {}).get("completion_tokens")})
    d = pd.DataFrame(recs)
    if out == "label":
        d["score"] = d.p_yes * 100
    return d
