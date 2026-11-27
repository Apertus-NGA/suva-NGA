"""Audit suva-ft-v3, points 4 et 6 : métriques des baselines Keera, intervalles de confiance, seuils, baselines triviales.
Usage : python3 -I -B a04_metrics.py --data data_v3 --runs runs_v3 --features a02_features.json \
        [--v1 runs/ --v1data data/ --v2 runs_v2/ --v2data data_v2/] --out out_dir
Réimplémente AUC (rangs moyens, ex aequo à 0,5) et F2 indépendamment de metrics_only.py, puis compare.
"""
import argparse, collections, json, math, os, random

ap = argparse.ArgumentParser()
ap.add_argument("--data", required=True); ap.add_argument("--runs", required=True); ap.add_argument("--features", required=True)
ap.add_argument("--v1"); ap.add_argument("--v1data"); ap.add_argument("--v2"); ap.add_argument("--v2data")
ap.add_argument("--out", required=True); ap.add_argument("--boot", type=int, default=2000)
a = ap.parse_args()
R = {}
rnd = random.Random(12345)
FEAT = json.load(open(a.features, encoding="utf-8"))


def load(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def auc(pos, neg):  # Mann-Whitney par rangs moyens
    if not pos or not neg:
        return None
    allv = sorted([(s, 1) for s in pos] + [(s, 0) for s in neg])
    ranks = {}
    i = 0
    rsum = 0.0
    while i < len(allv):
        j = i
        while j < len(allv) and allv[j][0] == allv[i][0]:
            j += 1
        r = (i + j + 1) / 2.0
        rsum += r * sum(1 for k in range(i, j) if allv[k][1] == 1)
        i = j
    n1, n0 = len(pos), len(neg)
    return (rsum - n1 * (n1 + 1) / 2) / (n1 * n0)


def f2_at(rows, thr):
    tp = sum(1 for r in rows if r["y"] and r["s"] >= thr); fp = sum(1 for r in rows if not r["y"] and r["s"] >= thr)
    npos = sum(r["y"] for r in rows)
    p = tp / (tp + fp) if tp + fp else 0.0; rc = tp / npos if npos else 0.0
    return (5 * p * rc / (4 * p + rc) if p + rc else 0.0), tp, fp, rc


def best_thr(rows):
    best = (-1, None)
    for t in sorted({r["s"] for r in rows}):
        f = f2_at(rows, t)[0]
        if f > best[0]:
            best = (f, t)
    return best


def summary(rows):
    pos = [r["s"] for r in rows if r["y"]]; neg = [r["s"] for r in rows if not r["y"]]
    hard = [r["s"] for r in rows if r["kind"] == "hard_negative"]
    out = {"n": len(rows), "pos": len(pos), "auc": auc(pos, neg), "auc_hard": auc(pos, hard)}
    for t in (0.5, 0.1, 0.01):
        f, tp, fp, rc = f2_at(rows, t); out[f"@{t}"] = [tp, fp, round(f, 3)]
    srt = sorted(rows, key=lambda r: -r["s"])
    out["top100"] = sum(r["y"] for r in srt[:100])
    # top100 avec ex aequo : combien de lignes ont un score >= au 100e score ?
    if len(srt) >= 100:
        s100 = srt[99]["s"]; out["top100_lignes_ex_aequo"] = sum(1 for r in rows if r["s"] >= s100)
    return out


def boot(rows, fn, B):
    P = [r for r in rows if r["y"]]; N = [r for r in rows if not r["y"]]
    vals = []
    for _ in range(B):
        smp = [rnd.choice(P) for _ in P] + [rnd.choice(N) for _ in N]
        v = fn(smp)
        if v is not None:
            vals.append(v)
    vals.sort()
    return [round(vals[int(0.025 * len(vals))], 3), round(vals[int(0.975 * len(vals)) - 1], 3)]


runs = {}
for d in sorted(os.listdir(a.runs)):
    p = os.path.join(a.runs, d, "test_scores.jsonl")
    if os.path.exists(p):
        runs[d] = load(p)
data = {f: {json.loads(l)["meta"]["decision_id"]: json.loads(l) for l in open(os.path.join(a.data, f, "test.jsonl"), encoding="utf-8")}
        for f in ("fold_A", "fold_B")}
# 1. alignement scores <-> jeu
align = {}
for name, rs in runs.items():
    fold = "fold_A" if name.startswith("foldA") else "fold_B"
    D = data[fold]
    ids = [r["decision_id"] for r in rs]
    bad_label = [r["decision_id"] for r in rs if D.get(r["decision_id"]) and D[r["decision_id"]]["completion"][0]["content"] != r["label"]]
    align[name] = {"n": len(rs), "ids_identiques": set(ids) == set(D), "doublons": len(ids) - len(set(ids)),
                   "labels_divergents": len(bad_label), "score_none": sum(r["score"] is None for r in rs),
                   "erreurs": sum(bool(r.get("error")) for r in rs),
                   "mass_min": round(min(r["mass"] for r in rs), 5), "mass_lt_0.99": sum(r["mass"] < 0.99 for r in rs),
                   "scores_distincts": len({r["score"] for r in rs}),
                   "score_eq_0_ou_1": sum(r["score"] in (0.0, 1.0) for r in rs)}
R["alignement"] = align

# 2. recalcul indépendant + IC bootstrap
ref = json.load(open(os.path.join(a.runs, "metrics_v3.json"))) if os.path.exists(os.path.join(a.runs, "metrics_v3.json")) else {}
res = {}
rows_by = {}
for name, rs in runs.items():
    rows = [{"id": r["decision_id"], "s": r["score"], "y": r["label"] == "Ja", "kind": r["kind"], "c1": r.get("couche1"),
             "lang": r["lang"], "docket": r["docket"], "q": r["quarter"]} for r in rs]
    fold = "fold_A" if name.startswith("foldA") else "fold_B"
    for r in rows:
        r["c1"] = data[fold][r["id"]]["meta"]["couche1"]
    rows_by[name] = rows
    c1 = [r for r in rows if r["c1"]]
    out = {"complet": summary(rows), "couche1": summary(c1)}
    for sub, rr in (("complet", rows), ("couche1", c1)):
        out[sub]["IC95_auc"] = boot(rr, lambda s: auc([r["s"] for r in s if r["y"]], [r["s"] for r in s if not r["y"]]), a.boot)
        out[sub]["IC95_auc_hard"] = boot([r for r in rr if r["y"] or r["kind"] == "hard_negative"],
                                         lambda s: auc([r["s"] for r in s if r["y"]], [r["s"] for r in s if not r["y"]]), a.boot)
        out[sub]["IC95_recall@0.5"] = boot(rr, lambda s: f2_at(s, 0.5)[3], a.boot)
        out[sub]["IC95_F2@0.5"] = boot(rr, lambda s: f2_at(s, 0.5)[0], a.boot)
        bf, bt = best_thr(rr); out[sub]["F2_oracle_seuil_choisi_sur_test"] = [round(bf, 3), bt]
    key = name.replace("_keera_", "_")
    if key in ref:
        out["ecart_vs_metrics_v3"] = {sub: {k: (round(out[sub][k], 3) if isinstance(out[sub][k], float) else out[sub][k], ref[key][sub].get(k))
                                            for k in ("auc", "auc_hard", "@0.5", "@0.01", "top100")
                                            if (round(out[sub][k], 3) if isinstance(out[sub][k], float) else out[sub][k]) != ref[key][sub].get(k)}
                                      for sub in ("complet", "couche1")}
    # rappel par langue à 0,5
    lg = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        if r["y"]:
            lg[r["lang"]][0] += 1; lg[r["lang"]][1] += r["s"] >= 0.5
    out["rappel@0.5_par_langue_[pos,trouves]"] = dict(lg)
    res[name] = out
R["metriques"] = res

# 3. seuil transféré d'un trimestre à l'autre (protocole honnête pour le zéro-shot)
tr = {}
for m in ("8b", "70b"):
    A, B = rows_by.get(f"foldA_keera_{m}"), rows_by.get(f"foldB_keera_{m}")
    if not A or not B:
        continue
    for sub in ("complet", "couche1"):
        AA = A if sub == "complet" else [r for r in A if r["c1"]]; BB = B if sub == "complet" else [r for r in B if r["c1"]]
        fB, tB = best_thr(BB); fA, tA = best_thr(AA)
        fA_t, tpA, fpA, rcA = f2_at(AA, tB); fB_t, tpB, fpB, rcB = f2_at(BB, tA)
        tr[f"{m}_{sub}"] = {"seuil_T4_vers_T1": [tB, "F2", round(fA_t, 3), "TP", tpA, "FP", fpA],
                            "seuil_T1_vers_T4": [tA, "F2", round(fB_t, 3), "TP", tpB, "FP", fpB],
                            "moyenne_F2_transfere": round((fA_t + fB_t) / 2, 3),
                            "moyenne_F2_oracle": round((fA + fB) / 2, 3)}
R["seuil_transfere"] = tr

# 4. baselines triviales (sans LLM), mêmes métriques
def rule_score(f):
    s = 0.0
    s += 3 * (f["matiere"] in ("UV", "MV")) + 1.5 * (f["matiere"] == "IV") + 1 * (f["prefixe"] == "8C") + 0.5 * (f["prefixe"] == "9C")
    s += 1 * (f["suva_partie"] or f["uvg_partie"]) - 2 * f["irrecevable"] + 1 * f["long14k"] + 0.5 * f["admis"] + 0.5 * f["cinq_juges"]
    return s + min(f["chars"], 60000) / 1e6  # départage par la longueur

base = {}
for fold, q in (("fold_A", "2026Q1"), ("fold_B", "2025Q4")):
    rows = []
    for did, ex in data[fold].items():
        f = FEAT[did]
        rows.append({"id": did, "s": rule_score(f), "y": ex["completion"][0]["content"] == "Ja", "kind": ex["meta"]["kind"],
                     "c1": ex["meta"]["couche1"], "len": f["chars"]})
    out = {"regle": summary(rows), "regle_couche1": summary([r for r in rows if r["c1"]])}
    lr = [{**r, "s": r["len"] * (1 if r["c1"] else 0)} for r in rows]
    out["longueur_seule_dans_couche1"] = summary([r for r in lr if r["c1"]])
    base[fold] = {"rows": rows, "out": out}
# seuil de la règle transféré
for fold, other in (("fold_A", "fold_B"), ("fold_B", "fold_A")):
    for sub in ("regle", "regle_couche1"):
        src = base[other]["rows"] if sub == "regle" else [r for r in base[other]["rows"] if r["c1"]]
        dst = base[fold]["rows"] if sub == "regle" else [r for r in base[fold]["rows"] if r["c1"]]
        f, t = best_thr(src); fx, tp, fp, rc = f2_at(dst, t)
        base[fold]["out"][sub]["F2_seuil_transfere"] = [round(fx, 3), "TP", tp, "FP", fp]
        base[fold]["out"][sub]["IC95_auc_hard"] = boot([r for r in dst if r["y"] or r["kind"] == "hard_negative"],
                                                       lambda s: auc([r["s"] for r in s if r["y"]], [r["s"] for r in s if not r["y"]]), a.boot)
R["baseline_regle"] = {f: v["out"] for f, v in base.items()}

# 5. reproductibilité Keera : même prompt scoré deux fois (v1 vs v2), et prompts v2 == v3 fold_A
def prompts(path):
    return {json.loads(l)["meta"]["decision_id"]: json.dumps(json.loads(l)["prompt"], ensure_ascii=False) for l in open(path, encoding="utf-8")}

if a.v2data:
    p2 = prompts(os.path.join(a.v2data, "test.jsonl")); p3 = {i: json.dumps(ex["prompt"], ensure_ascii=False) for i, ex in data["fold_A"].items()}
    R["prompts_v2_test_vs_v3_foldA_test"] = {"communs": len(set(p2) & set(p3)), "identiques": sum(p2[i] == p3[i] for i in set(p2) & set(p3)),
                                             "seulement_v2": len(set(p2) - set(p3)), "seulement_v3": len(set(p3) - set(p2))}
if a.v1 and a.v1data and a.v2:
    rep = {}
    pv1 = {}
    for sp in ("test", "valid"):
        pv1.update(prompts(os.path.join(a.v1data, f"{sp}.jsonl")))
    pv3 = {}
    for f in ("fold_A", "fold_B"):
        for sp in ("train", "valid", "test"):
            pv3.update(prompts(os.path.join(a.data, f, f"{sp}.jsonl")))
    for m in ("8b", "70b"):
        s1 = {}
        for sp in ("test", "valid"):
            p = os.path.join(a.v1, f"keera_{m}", f"{sp}_scores.jsonl")
            if os.path.exists(p):
                for r in load(p):
                    s1[r["decision_id"]] = r
        s2 = {}
        for sp in ("test", "valid"):
            p = os.path.join(a.v2, f"keera_{m}", f"{sp}_scores.jsonl")
            if os.path.exists(p):
                for r in load(p):
                    s2[r["decision_id"]] = r
        for r in runs.get(f"foldB_keera_{m}", []):
            s2.setdefault(r["decision_id"], r)
        common = [i for i in s1 if i in s2 and i in pv1 and i in pv3 and pv1[i] == pv3[i]]
        d = [abs(s1[i]["score"] - s2[i]["score"]) for i in common if s1[i]["score"] is not None and s2[i]["score"] is not None]
        flips = sum((s1[i]["score"] >= 0.5) != (s2[i]["score"] >= 0.5) for i in common)
        d.sort()
        rep[m] = {"paires_meme_prompt": len(common), "ecart_abs_median": round(d[len(d) // 2], 5) if d else None,
                  "ecart_abs_max": round(d[-1], 4) if d else None, "ecart_gt_0.05": sum(x > 0.05 for x in d),
                  "bascules_au_seuil_0.5": flips}
    R["repetabilite_keera_v1_vs_v2v3"] = rep

os.makedirs(a.out, exist_ok=True)
json.dump(R, open(os.path.join(a.out, "a04_metrics.json"), "w"), ensure_ascii=False, indent=1)
for k, v in R.items():
    print(k, ":", json.dumps(v, ensure_ascii=False)[:2500])
