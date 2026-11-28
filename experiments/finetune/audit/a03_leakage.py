"""Audit suva-ft-v3, point 3 : fuites et biais d'entrée.
- chaînes d'affaires entre train et test (citations BGer croisées, même dossier cantonal attaqué, même docket) ;
- indices de label dans le prompt (préfixe 8C/9C, 'Suva' dans le texte, marqueur de troncature) ;
- troncature 14 000 caractères (tête 12 000 + queue 2 000) : dispositif conservé ? considérants perdus ?
- longueur en tokens (Keera) vs max_len du trainer local.
Usage : python3 -I -B a03_leakage.py --parquet bger.parquet --data data_v3 --runs runs_v3 --out out_dir
"""
import argparse, collections, json, os, re
import duckdb

ap = argparse.ArgumentParser()
ap.add_argument("--parquet", required=True); ap.add_argument("--data", required=True)
ap.add_argument("--runs", required=True); ap.add_argument("--out", required=True)
a = ap.parse_args()
R = {}
recs = {}
for fold in ("fold_A", "fold_B"):
    for sp in ("train", "valid", "test"):
        for l in open(os.path.join(a.data, fold, sp + ".jsonl"), encoding="utf-8"):
            j = json.loads(l); m = j["meta"]
            recs[(fold, sp, m["decision_id"])] = {**m, "label": j["completion"][0]["content"], "user": j["prompt"][1]["content"],
                                                  "system": j["prompt"][0]["content"]}
ids = sorted({k[2] for k in recs})
con = duckdb.connect()
con.execute("create temp table w(i varchar)"); con.executemany("insert into w values (?)", [(i,) for i in ids])
meta = {r[0]: {"cited": json.loads(r[1]) if r[1] else [], "appealed": r[2], "docket": r[3], "full": r[4]}
        for r in con.execute(f"select decision_id, cited_decisions, appealed_docket, docket_number, full_text "
                             f"from read_parquet('{a.parquet}') b join w on b.decision_id = w.i").fetchall()}

# 0. prompt système unique et question constante
R["prompts_systeme_distincts"] = len({r["system"] for r in recs.values()})
R["question_finale_constante"] = all(r["user"].endswith("Antworte nur mit Ja oder Nein.") for r in recs.values())

# 1. chaînes d'affaires train <-> test, par pli
BGER = re.compile(r"^\d[A-Z]_\d+/\d{4}$")
for fold in ("fold_A", "fold_B"):
    tr = {k[2]: v for k, v in recs.items() if k[0] == fold and k[1] in ("train", "valid")}
    te = {k[2]: v for k, v in recs.items() if k[0] == fold and k[1] == "test"}
    d_tr = {v["docket"]: i for i, v in tr.items()}; d_te = {v["docket"]: i for i, v in te.items()}
    links = []
    for side, A, dB in (("test cite train", te, d_tr), ("train cite test", tr, d_te)):
        for i, v in A.items():
            for c in meta[i]["cited"]:
                if BGER.match(c) and c in dB and c != v["docket"]:
                    j = dB[c]; other = tr.get(j) or te.get(j)
                    links.append({"sens": side, "de": v["docket"], "label_de": v["label"], "vers": c, "label_vers": other["label"],
                                  "kind_de": v["kind"], "kind_vers": other["kind"]})
    R[f"{fold}_liens_citation_train_test"] = len(links)
    R[f"{fold}_liens_impliquant_un_positif"] = [l for l in links if "Ja" in (l["label_de"], l["label_vers"])]
    # même dossier cantonal attaqué
    app_tr = collections.defaultdict(list)
    for i, v in tr.items():
        if meta[i]["appealed"]:
            app_tr[meta[i]["appealed"]].append(v)
    same = []
    for i, v in te.items():
        ad = meta[i]["appealed"]
        if ad and ad in app_tr:
            for o in app_tr[ad]:
                same.append({"test": v["docket"], "label_test": v["label"], "train": o["docket"], "label_train": o["label"], "appealed": ad})
    R[f"{fold}_meme_dossier_cantonal_train_test"] = len(same)
    R[f"{fold}_meme_dossier_cantonal_avec_positif"] = [s for s in same if "Ja" in (s["label_test"], s["label_train"])]
    R[f"{fold}_meme_dossier_cantonal_exemples"] = same[:8]

# 2. indices de label dans l'entrée
def tab(sel, key):
    c = collections.defaultdict(lambda: [0, 0])
    for v in sel:
        c[key(v)][0] += 1; c[key(v)][1] += v["label"] == "Ja"
    return {str(k): {"n": n, "pos": p, "taux": round(p / n, 3)} for k, (n, p) in sorted(c.items(), key=lambda x: str(x[0]))}

tests = [v for k, v in recs.items() if k[1] == "test"]
R["test_par_prefixe_groupe"] = tab(tests, lambda v: v["prefixe"] if v["prefixe"] in ("8C", "9C") else "autres")
TRUNC = "\n[…]\n"
R["test_tronque_par_kind"] = tab(tests, lambda v: (v["kind"], v["chars_full"] > 14000))
# la question finale contient « für die Suva » : on la retire avant de chercher la mention dans l'arrêt
R["test_suva_dans_texte_par_kind"] = tab(tests, lambda v: (v["kind"], bool(re.search(r"(?i)\bsuva\b|\(CNA\)|\bINSAI\b",
                                                                                      v["user"].rsplit("\n\n", 1)[0]))))
hard = [v for v in tests if v["kind"] in ("positive", "hard_negative")]
R["durs_tronques_vs_positifs"] = tab(hard, lambda v: ("tronqué" if v["chars_full"] > 14000 else "entier"))
R["durs_par_lang"] = tab(hard, lambda v: v["lang"])
R["tous_test_par_lang"] = tab(tests, lambda v: v["lang"])

# 3. troncature : dispositif et issue dans le texte envoyé ?
DISP = re.compile(r"(Demnach erkennt das Bundesgericht|Par ces motifs|Per questi motivi)", re.I)
ISSUE = re.compile(r"(abgewiesen|gutgeheissen|nicht eingetreten|rejeté|admis|irrecevable|respinto|accolto|inammissibile|"
                   r"abgeschrieben|sans objet|gegenstandslos|stralciat)", re.I)
tr_stats = {"tronques": 0, "disp_dans_envoye": 0, "issue_dans_queue": 0, "disp_coupe_mais_present_dans_full": 0,
            "chars_perdus_median": None, "part_perdue_median": None}
lost, frac = [], []
seen = set()
for (fold, sp, i), v in recs.items():
    if i in seen:
        continue
    seen.add(i)
    if v["chars_full"] <= 14000:
        continue
    tr_stats["tronques"] += 1
    body = v["user"]
    has_disp = bool(DISP.search(body))
    tr_stats["disp_dans_envoye"] += has_disp
    tail = body.split(TRUNC, 1)[1] if TRUNC in body else ""
    tr_stats["issue_dans_queue"] += bool(ISSUE.search(tail))
    if not has_disp and DISP.search(meta[i]["full"] or ""):
        tr_stats["disp_coupe_mais_present_dans_full"] += 1
    lost.append(v["chars_full"] - 14000); frac.append((v["chars_full"] - 14000) / v["chars_full"])
lost.sort(); frac.sort()
tr_stats["chars_perdus_median"] = lost[len(lost) // 2]; tr_stats["part_perdue_median"] = round(frac[len(frac) // 2], 3)
tr_stats["part_perdue_p90"] = round(frac[int(len(frac) * 0.9)], 3)
R["troncature"] = tr_stats
pos_all = {i: v for (f, s, i), v in recs.items() if v["label"] == "Ja"}
R["positifs_tronques"] = f"{sum(v['chars_full'] > 14000 for v in pos_all.values())}/{len(pos_all)}"
R["positifs_sans_dispositif_envoye"] = sorted(v["docket"] for v in pos_all.values() if not DISP.search(v["user"]))

# 4. tokens Keera vs max_len 6144 du trainer local
toks = []
for d in sorted(os.listdir(a.runs)):
    p = os.path.join(a.runs, d, "test_scores.jsonl")
    if os.path.exists(p):
        for l in open(p, encoding="utf-8"):
            j = json.loads(l)
            if j.get("n_tokens"):
                toks.append(j["n_tokens"])
toks.sort()
R["tokens_prompt_keera"] = {"n": len(toks), "median": toks[len(toks) // 2], "p99": toks[int(len(toks) * 0.99)], "max": toks[-1],
                            "gt_6144": sum(t > 6144 for t in toks), "gt_4096": sum(t > 4096 for t in toks)}
os.makedirs(a.out, exist_ok=True)
json.dump(R, open(os.path.join(a.out, "a03_leakage.json"), "w"), ensure_ascii=False, indent=1)
for k, v in R.items():
    print(k, ":", json.dumps(v, ensure_ascii=False)[:1200])
