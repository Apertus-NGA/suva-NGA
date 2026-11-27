"""Audit suva-ft-v3 : taux de sélection Suva sur les arrêts UV « sur le fond » par trimestre et par mois,
test exact de Fisher T4 vs T1, et liste des négatifs UV sur le fond (candidats faux négatifs).
Usage : python3 -I -B a05_uv_selection.py a02_features.json [scores_dir]
"""
import json, sys, math, collections, os
F = json.load(open(sys.argv[1], encoding="utf-8"))
runs = sys.argv[2] if len(sys.argv) > 2 else None

def fond(f):  # UV/MV, ni irrecevable, ni juge unique (procédure simplifiée), texte >= 7 000 caractères
    return f["matiere"] in ("UV", "MV") and not f["irrecevable"] and (f["n_juges"] or 0) >= 2 and f["chars"] >= 7000

def fisher(a, b, c, d):  # bilatéral, somme des tables de proba <= observée
    n = a + b + c + d; r1 = a + b; c1 = a + c
    def p(x): return math.comb(r1, x) * math.comb(n - r1, c1 - x) / math.comb(n, c1)
    po = p(a); lo, hi = max(0, c1 - (n - r1)), min(r1, c1)
    return sum(p(x) for x in range(lo, hi + 1) if p(x) <= po * (1 + 1e-9))

out = {}
cnt = {}
for q in ("2025Q3", "2025Q4", "2026Q1"):
    S = [f for f in F.values() if f["q"] == q and fond(f)]
    cnt[q] = (len(S), sum(f["pos"] for f in S))
    m = collections.defaultdict(lambda: [0, 0])
    for f in S:
        m[f["date"][:7]][0] += 1; m[f["date"][:7]][1] += f["pos"]
    out[q] = {"UV_fond_[n,pos]": cnt[q], "par_mois": dict(sorted(m.items()))}
(n4, p4), (n1, p1) = cnt["2025Q4"], cnt["2026Q1"]
out["fisher_T4_vs_T1"] = round(fisher(p4, n4 - p4, p1, n1 - p1), 4)
scores = {}
if runs:
    for d in os.listdir(runs):
        p = os.path.join(runs, d, "test_scores.jsonl")
        if os.path.exists(p):
            for l in open(p, encoding="utf-8"):
                j = json.loads(l); scores.setdefault(j["decision_id"], {})[d.split("_keera_")[1]] = round(j["score"], 3)
neg = sorted((f for f in F.values() if f["q"] in ("2025Q4", "2026Q1") and fond(f) and not f["pos"]), key=lambda f: (f["q"], f["date"]))
out["negatifs_UV_fond"] = [[f["docket"], f["q"], f["date"], f["lang"], f["outcome"], f["chars"], f["n_juges"],
                            "Suva" if f["suva_partie"] else ("autre LAA" if f["uvg_partie"] else "-"), f["title"],
                            scores.get(f["id"], {})] for f in neg]
# combien de ces négatifs les modèles zéro-shot mettent-ils au-dessus de 0,5 ?
for m in ("8b", "70b"):
    out[f"negatifs_UV_fond_score>=0.5_{m}"] = sum(1 for f in neg if scores.get(f["id"], {}).get(m, 0) >= 0.5)
    fp = [i for i, s in scores.items() if s.get(m, 0) >= 0.5 and not F[i]["pos"]]
    out[f"FP@0.5_total_{m}"] = len(fp)
json.dump(out, open(os.path.join(os.path.dirname(sys.argv[1]), "a05_uv_selection.json"), "w"), ensure_ascii=False, indent=1)
for k, v in out.items():
    if k == "negatifs_UV_fond":
        print(k, len(v))
        for x in v: print("   ", x)
    else:
        print(k, ":", json.dumps(v, ensure_ascii=False))
