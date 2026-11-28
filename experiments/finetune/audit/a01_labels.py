"""Audit suva-ft-v3, point 1 : intégrité des labels.
Usage : python3 -I -B a01_labels.py --parquet bger.parquet --pop population_tf_hf_2025Q3_2026Q2.csv \
        --pos positifs_suva.csv --data data_v3 --out out_dir
Lecture seule. Écrit a01_labels.json dans --out.
"""
import argparse, csv, collections, json, os, re
import duckdb

ap = argparse.ArgumentParser()
ap.add_argument("--parquet", required=True); ap.add_argument("--pop", required=True)
ap.add_argument("--pos", required=True); ap.add_argument("--data", required=True); ap.add_argument("--out", required=True)
a = ap.parse_args()
R = {}

pos = list(csv.DictReader(open(a.pos, encoding="utf-8")))
pop = list(csv.DictReader(open(a.pop, encoding="utf-8")))
listed = {p["docket"]: p for p in pos if p["docket"] and p["row"]}
summ = {p["docket"]: p for p in pos if p["docket"] and not p["row"]}
R["n_lignes_positifs_csv"] = len(pos)
R["n_liste_tf"] = len(listed); R["n_resumes_T3"] = len(summ)
R["ligne_sans_docket"] = [p for p in pos if not p["docket"]]
R["dockets_en_double_dans_liste"] = [d for d, c in collections.Counter(p["docket"] for p in pos if p["docket"]).items() if c > 1]

# population : lignes par docket
by_docket = collections.defaultdict(list)
for r in pop:
    by_docket[r["docket"]].append(r)
R["pop_dockets_multi_lignes"] = {d: [(r["decision_id"], r["decision_date"], r["trimestre_decision"], r["label_suva"]) for r in v]
                                 for d, v in by_docket.items() if len(v) > 1}

def q_of(date):
    y, m = date[:4], int(date[5:7]); return f"{y}Q{(m - 1) // 3 + 1}"

chk = []
for d, p in listed.items():
    rows = by_docket.get(d, [])
    exp_q = p["quarter_label"].replace(" ", "")
    chk.append({"docket": d, "n_rows_pop": len(rows), "quarters": [r["trimestre_decision"] for r in rows],
                "dates_pop": [r["decision_date"] for r in rows], "date_xlsx": p["decision_date"],
                "date_match": (not p["decision_date"]) or any(r["decision_date"] == p["decision_date"] for r in rows),
                "q_ok": all(r["trimestre_decision"] == exp_q for r in rows) and len(rows) == 1,
                "matiere": [r["matiere"] for r in rows], "title": [r["title"][:60] for r in rows]})
R["liste_problemes"] = [c for c in chk if not (c["n_rows_pop"] == 1 and c["q_ok"] and c["date_match"])]
R["liste_matieres"] = dict(collections.Counter(c["matiere"][0] if c["matiere"] else "absent" for c in chk))
chk_s = []
for d, p in summ.items():
    rows = by_docket.get(d, [])
    chk_s.append({"docket": d, "rows": [(r["decision_date"], r["trimestre_decision"], r["label_suva"], r["matiere"]) for r in rows],
                  "date_resume": p["decision_date"]})
R["resumes_problemes"] = [c for c in chk_s if len(c["rows"]) != 1 or c["rows"][0][1] != "2025Q3" or c["rows"][0][0] != c["date_resume"]]

# parquet : toutes les lignes (toutes dates) des dockets listés / résumés
con = duckdb.connect()
con.execute(f"create view raw as select decision_id, docket_number, decision_date::varchar dd, publication_date::varchar pd, "
            f"title, language from read_parquet('{a.parquet}')")
alld = list(listed) + list(summ)
con.execute("create temp table w(d varchar)"); con.executemany("insert into w values (?)", [(d,) for d in alld])
rows = con.execute("select decision_id, docket_number, dd, pd, title from raw join w on raw.docket_number = w.d order by 2, 3").fetchall()
pq = collections.defaultdict(list)
for r in rows:
    pq[r[1]].append(r)
R["parquet_dockets_listes_multi_lignes"] = {d: [(x[0], x[2], x[3]) for x in v] for d, v in pq.items() if len(v) > 1}
R["parquet_dockets_absents"] = [d for d in alld if d not in pq]
# variantes de docket proches (8C_458 vs 9C_458) pour la ligne « prefix missing »
pm = [p for p in pos if "prefix" in p["kind"]]
R["prefix_missing"] = []
for p in pm:
    num = p["docket"].split("_", 1)[1]
    alt = con.execute("select decision_id, docket_number, dd, title from raw where docket_number like ? order by 2",
                      [f"%\\_{num}"]).fetchall() if False else con.execute(
        "select decision_id, docket_number, dd, title from raw where regexp_matches(docket_number, ?)", [f"^[0-9][A-Z]_{re.escape(num)}$"]).fetchall()
    R["prefix_missing"].append({"docket": p["docket"], "date_xlsx": p["decision_date"],
                                "candidats": [(x[1], x[2], (x[3] or "")[:50]) for x in alt]})

# jeu v3 : chaque positif listé présent une fois, bon pli, label Ja ; aucun docket listé/résumé avec Nein
recs = []
for fold in ("fold_A", "fold_B"):
    for sp in ("train", "valid", "test"):
        for l in open(os.path.join(a.data, fold, sp + ".jsonl"), encoding="utf-8"):
            j = json.loads(l); m = j["meta"]
            recs.append({"fold": fold, "split": sp, "id": m["decision_id"], "docket": m["docket"], "q": m["quarter"],
                         "label": j["completion"][0]["content"], "kind": m["kind"], "src": m["label_source"]})
R["v3_nein_sur_docket_liste_ou_resume"] = [r for r in recs if r["label"] == "Nein" and (r["docket"] in listed or r["docket"] in summ)]
R["v3_ja_hors_liste"] = [r for r in recs if r["label"] == "Ja" and r["docket"] not in listed and r["docket"] not in summ]
place = collections.defaultdict(list)
for r in recs:
    if r["docket"] in listed:
        place[r["docket"]].append((r["fold"], r["split"]))
bad = {}
for d, p in listed.items():
    q = p["quarter_label"].replace(" ", "")
    pl = place[d]
    exp_test = "fold_A" if q == "2026Q1" else "fold_B"
    exp_train = "fold_B" if q == "2026Q1" else "fold_A"
    ok = (len(pl) == 2 and (exp_test, "test") in pl and any(f == exp_train and s in ("train", "valid") for f, s in pl))
    if not ok:
        bad[d] = pl
R["v3_placement_positifs_ko"] = bad
# un même docket ou decision_id dans plusieurs splits d'un même pli
for fold in ("fold_A", "fold_B"):
    seen = collections.defaultdict(set)
    for r in recs:
        if r["fold"] == fold:
            seen[r["docket"]].add(r["split"])
    R[f"{fold}_docket_multi_split"] = {d: sorted(s) for d, s in seen.items() if len(s) > 1}
    ids = [r["id"] for r in recs if r["fold"] == fold]
    R[f"{fold}_decision_id_dupliques"] = [i for i, c in collections.Counter(ids).items() if c > 1]
# couverture : population T4/T1 entièrement dans le test de son pli
for fold, q in (("fold_A", "2026Q1"), ("fold_B", "2025Q4")):
    pid = {r["decision_id"] for r in pop if r["trimestre_decision"] == q}
    tid = {r["id"] for r in recs if r["fold"] == fold and r["split"] == "test"}
    R[f"{fold}_test_vs_pop"] = {"pop": len(pid), "test": len(tid), "manquants": sorted(pid - tid)[:20], "en_trop": sorted(tid - pid)[:20]}
# jumeaux exclus : docket et date
R["jumeaux_dans_v3"] = [r for r in recs if re.search(r"-D\d{8}$", r["id"])]
# même docket, plusieurs décisions dans la population T3-T2 et dans v3
dd = collections.defaultdict(set)
for r in recs:
    dd[r["docket"]].add((r["id"], r["q"], r["label"]))
R["v3_docket_plusieurs_decisions"] = {d: sorted(v) for d, v in dd.items() if len({x[0] for x in v}) > 1}
os.makedirs(a.out, exist_ok=True)
json.dump(R, open(os.path.join(a.out, "a01_labels.json"), "w"), ensure_ascii=False, indent=1)
for k, v in R.items():
    s = json.dumps(v, ensure_ascii=False)
    print(f"{k}: {s[:600]}")
