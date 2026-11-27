"""Audit suva-ft-v3, point 2 : validité des négatifs (hypothèse « reste du trimestre = négatif »).
Calcule, pour chaque arrêt T3/2025, T4/2025, T1/2026, les signaux de la grille Suva (Basisregeln) lisibles
dans le texte : Suva/CNA/INSAI partie (rubrum), autre assureur LAA partie, matière UV/IV/MV, 5 juges,
issue (admis / rejeté / irrecevable), longueur > 25 000 caractères, publication prévue (mfp HF).
Puis compare positifs et négatifs et liste les négatifs « suspects ».
Usage : python3 -I -B a02_negatives.py --parquet bger.parquet --pop population.csv --out out_dir
"""
import argparse, collections, csv, json, os, re
import duckdb

ap = argparse.ArgumentParser()
ap.add_argument("--parquet", required=True); ap.add_argument("--pop", required=True); ap.add_argument("--out", required=True)
a = ap.parse_args()
pop = {r["decision_id"]: r for r in csv.DictReader(open(a.pop, encoding="utf-8"))
       if r["trimestre_decision"] in ("2025Q3", "2025Q4", "2026Q1")}
con = duckdb.connect()
con.execute("create temp table w(i varchar)"); con.executemany("insert into w values (?)", [(i,) for i in pop])
rows = con.execute(f"select decision_id, full_text, outcome, marked_for_publication, cited_decisions, appealed_docket "
                   f"from read_parquet('{a.parquet}') b join w on b.decision_id = w.i").fetchall()

RUB_END = re.compile(r"\n\s*(Gegenstand|Objet|Oggetto)\s*\n")
SUVA = re.compile(r"\bSuva\b|Schweizerische Unfallversicherungsanstalt|Caisse nationale suisse d.assurance|\(CNA\)|\bCNA\b|"
                  r"\bINSAI\b|Istituto nazionale svizzero di assicurazione", re.I)
UVG_INS = re.compile(r"\b(AXA|Allianz|Zürich Versicherung|Zurich Versicherung|Zurich Compagnie|Zurich Insurance|Zürich Insurance|"
                     r"Helsana|Generali|Baloise|Bâloise|Basler|Mobiliar|Visana|CSS|Sanitas|SWICA|Vaudoise|Helvetia|"
                     r"Groupe Mutuel|Mutuel Assurance|Concordia|Sympany|ÖKK|KPT|Atupri|Assura|Elvia|Winterthur|Emmental|"
                     r"Unfallversicherung|assurance-accidents|assicurazione contro gli infortuni|Militärversicherung|"
                     r"assurance militaire|assicurazione militare)\b", re.I)
BES = re.compile(r"(Besetzung|Composition|Composizione)\s*\n(.*?)\n\s*(Gerichtsschreiber|Greffi|Cancellier)", re.S)
ROLEW = re.compile(r"\b(Bundesrichter(in|innen)?|Präsident(in)?|Juges?|fédéra(l|le|ux|les)|présidente?|Giudic[ei]|federal[ei]|"
                   r"president[ea]|MM?\.|Mmes?|Mme|und|et|e|ed|nebenamtliche[r]?|suppléant[e]?s?|supplente|Bundesrichterinnen)\b", re.I)
DISP = re.compile(r"(Demnach erkennt das Bundesgericht|Par ces motifs|Per questi motivi)", re.I)


def n_judges(t):
    m = BES.search(t[:6000])
    if not m:
        return None
    s = ROLEW.sub(" ", m.group(2))
    parts = [p.strip(" .\n") for p in re.split(r"[,\n]", s) if p.strip(" .\n")]
    return len([p for p in parts if re.match(r"^[A-ZÄÖÜÉÈ]", p)])


feat = {}
for did, t, outcome, mfp, cited, appd in rows:
    r = pop[did]; t = t or ""
    m = RUB_END.search(t[:8000]); rub = t[: m.start()] if m else t[:3000]
    nj = n_judges(t)
    feat[did] = {
        "id": did, "docket": r["docket"], "q": r["trimestre_decision"], "date": r["decision_date"], "lang": r["lang"],
        "prefixe": r["prefixe"], "matiere": r["matiere"], "title": (r["title"] or "")[:70],
        "pos": r["label_suva"] != "", "label": r["label_suva"],
        "suva_partie": bool(SUVA.search(rub)), "uvg_partie": bool(UVG_INS.search(rub)) and not bool(SUVA.search(rub)),
        "suva_texte": r["txt_suva"] == "true", "laa_texte": r["txt_loi_laa"] == "true",
        "aucun_signal_txt": not any(r[k] == "true" for k in ("txt_suva", "txt_cna", "txt_insai", "txt_loi_laa", "txt_assurance_accidents")),
        "n_juges": nj, "cinq_juges": nj is not None and nj >= 5, "outcome": outcome or "",
        "admis": outcome in ("approved", "partial_approval"), "irrecevable": outcome == "inadmissible",
        "long25k": len(t) > 25000, "long14k": len(t) > 14000, "chars": len(t), "mfp": bool(mfp),
        "rubrum_trouve": bool(m),
    }

def rate(sel):
    n = len(sel); p = sum(f["pos"] for f in sel)
    return {"n": n, "pos": p, "taux": round(p / n, 3) if n else None}

R = {"n": len(feat), "rubrum_trouve": sum(f["rubrum_trouve"] for f in feat.values()),
     "n_juges_distrib": dict(collections.Counter(str(f["n_juges"]) for f in feat.values())),
     "mfp_true": sum(f["mfp"] for f in feat.values())}
for q in ("2025Q4", "2026Q1", "2025Q3"):
    F = [f for f in feat.values() if f["q"] == q]
    d = {}
    for name, cond in [
        ("tous", lambda f: True),
        ("UV", lambda f: f["matiere"] == "UV"),
        ("IV", lambda f: f["matiere"] == "IV"),
        ("UV & suva_partie", lambda f: f["matiere"] == "UV" and f["suva_partie"]),
        ("UV & uvg_partie (autre assureur)", lambda f: f["matiere"] == "UV" and f["uvg_partie"]),
        ("UV & suva_partie & irrecevable", lambda f: f["matiere"] == "UV" and f["suva_partie"] and f["irrecevable"]),
        ("UV & suva_partie & !irrecevable", lambda f: f["matiere"] == "UV" and f["suva_partie"] and not f["irrecevable"]),
        ("UV & !irrecevable", lambda f: f["matiere"] == "UV" and not f["irrecevable"]),
        ("UV & irrecevable", lambda f: f["matiere"] == "UV" and f["irrecevable"]),
        ("UV & admis", lambda f: f["matiere"] == "UV" and f["admis"]),
        ("UV & long25k", lambda f: f["matiere"] == "UV" and f["long25k"]),
        ("UV & cinq_juges", lambda f: f["matiere"] == "UV" and f["cinq_juges"]),
        ("IV & suva_texte", lambda f: f["matiere"] == "IV" and f["suva_texte"]),
        ("IV & !suva_texte", lambda f: f["matiere"] == "IV" and not f["suva_texte"]),
        ("IV & 8C", lambda f: f["matiere"] == "IV" and f["prefixe"] == "8C"),
        ("IV & 9C", lambda f: f["matiere"] == "IV" and f["prefixe"] == "9C"),
        ("autre & suva_partie", lambda f: f["matiere"] not in ("UV", "IV", "MV") and f["suva_partie"]),
        ("autre & suva_texte", lambda f: f["matiere"] not in ("UV", "IV", "MV") and f["suva_texte"]),
        ("cinq_juges (toutes matières)", lambda f: f["cinq_juges"]),
        ("8C", lambda f: f["prefixe"] == "8C"), ("9C", lambda f: f["prefixe"] == "9C"),
    ]:
        d[name] = rate([f for f in F if cond(f)])
    # positifs par mois (UV) : la liste T1 est-elle tronquée en fin de trimestre ?
    mois = collections.defaultdict(lambda: [0, 0])
    for f in F:
        if f["matiere"] == "UV":
            mois[f["date"][:7]][0] += 1; mois[f["date"][:7]][1] += f["pos"]
    d["UV_par_mois_[n,pos]"] = dict(sorted(mois.items()))
    R[q] = d

# négatifs suspects T4/T1 : UV, partie Suva ou assureur LAA, sur le fond (pas irrecevable)
sus = [f for f in feat.values() if f["q"] in ("2025Q4", "2026Q1") and not f["pos"] and f["matiere"] in ("UV", "MV")
       and (f["suva_partie"] or f["uvg_partie"]) and not f["irrecevable"]]
sus_strong = [f for f in sus if f["long25k"] or f["cinq_juges"] or f["admis"] or f["mfp"]]
R["neg_suspects_UV_partie_fond"] = len(sus); R["neg_suspects_forts"] = len(sus_strong)
R["neg_suspects_liste"] = sorted(([f["docket"], f["q"], f["lang"], f["outcome"], f["chars"], f["n_juges"],
                                   "Suva" if f["suva_partie"] else "autre LAA", f["title"]] for f in sus), key=lambda x: (x[1], x[0]))
# positifs : profil
P = [f for f in feat.values() if f["pos"] and f["q"] in ("2025Q4", "2026Q1")]
R["profil_positifs_T4T1"] = {k: sum(bool(f[k]) for f in P) for k in ("suva_partie", "uvg_partie", "suva_texte", "irrecevable",
                                                                         "admis", "long25k", "long14k", "cinq_juges", "mfp")}
R["profil_positifs_T4T1"]["n"] = len(P)
R["positifs_irrecevables"] = [[f["docket"], f["outcome"], f["chars"]] for f in P if f["irrecevable"]]
R["positifs_sans_aucun_signal_txt"] = [[f["docket"], f["matiere"], f["prefixe"]] for f in P if f["aucun_signal_txt"]]
# T3 : estimation des positifs manquants avec les taux T4+T1 par cellule (matière x partie x irrecevable)
def cell(f):
    return (f["matiere"] if f["matiere"] in ("UV", "IV") else "autre", "suva" if f["suva_partie"] else ("laa" if f["uvg_partie"] else "-"),
            "irr" if f["irrecevable"] else "fond")
ref = collections.defaultdict(lambda: [0, 0])
for f in feat.values():
    if f["q"] in ("2025Q4", "2026Q1"):
        ref[cell(f)][0] += 1; ref[cell(f)][1] += f["pos"]
exp3 = 0.0; obs3 = 0; cells3 = {}
for f in feat.values():
    if f["q"] == "2025Q3":
        n, p = ref[cell(f)]; e = p / n if n else 0
        exp3 += e; obs3 += f["pos"]
        c = cells3.setdefault("/".join(cell(f)), [0, 0.0, 0]); c[0] += 1; c[1] += e; c[2] += f["pos"]
R["T3_positifs_attendus_vs_resumes"] = {"attendus": round(exp3, 1), "resumes": obs3,
                                         "par_cellule_[n,attendus,resumes]": {k: [v[0], round(v[1], 1), v[2]] for k, v in cells3.items() if v[1] >= 0.5}}
R["taux_par_cellule_T4T1_[n,pos]"] = {"/".join(k): v for k, v in sorted(ref.items()) if v[1] or v[0] >= 20}
os.makedirs(a.out, exist_ok=True)
json.dump(R, open(os.path.join(a.out, "a02_negatives.json"), "w"), ensure_ascii=False, indent=1)
json.dump(feat, open(os.path.join(a.out, "a02_features.json"), "w"), ensure_ascii=False)
for k, v in R.items():
    print(k, ":", json.dumps(v, ensure_ascii=False)[:1500])
