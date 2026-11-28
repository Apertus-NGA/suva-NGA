"""Audit suva-ft-v3 : sensibilité des métriques au bruit des négatifs UV « sur le fond », métriques groupées
sur les deux plis, et quasi-doublons de texte entre train et test.
Usage : python3 -I -B a06_sensitivity.py --data data_v3 --runs runs_v3 --out out_dir
(lit out_dir/a05_uv_selection.json et out_dir/a02_features.json)
"""
import argparse, json, os, re, random

ap = argparse.ArgumentParser()
ap.add_argument("--data", required=True); ap.add_argument("--runs", required=True); ap.add_argument("--out", required=True)
a = ap.parse_args()
S = json.load(open(os.path.join(a.out, "a05_uv_selection.json"), encoding="utf-8"))
FEAT = json.load(open(os.path.join(a.out, "a02_features.json"), encoding="utf-8"))
sus = {x[0] for x in S["negatifs_UV_fond"]}
R = {"n_negatifs_UV_fond": len(sus)}
rnd = random.Random(7)


def auc(p, n):
    if not p or not n:
        return None
    return sum((x > y) + 0.5 * (x == y) for x in p for y in n) / (len(p) * len(n))


def f2(rows, t):
    tp = sum(1 for r in rows if r["y"] and r["s"] >= t); fp = sum(1 for r in rows if not r["y"] and r["s"] >= t)
    P = sum(r["y"] for r in rows); pr = tp / (tp + fp) if tp + fp else 0; rc = tp / P if P else 0
    return round(5 * pr * rc / (4 * pr + rc), 3) if pr + rc else 0.0


def best_t(rows):
    return max(((f2(rows, t), t) for t in {r["s"] for r in rows}), key=lambda x: x[0])[1]


def met(rows, t_transf):
    P = [r["s"] for r in rows if r["y"]]; H = [r["s"] for r in rows if r["hard"] and not r["y"]]
    return {"pos": len(P), "auc_hard": round(auc(P, H), 3), "F2@0.5": f2(rows, 0.5), "F2_seuil_transfere": f2(rows, t_transf)}


def rows_of(run):
    out = []
    for l in open(os.path.join(a.runs, run, "test_scores.jsonl"), encoding="utf-8"):
        j = json.loads(l)
        out.append({"docket": j["docket"], "s": j["score"], "y": j["label"] == "Ja", "hard": j["kind"] != "easy_negative",
                    "c1": None})
    return out


for m in ("8b", "70b"):
    A, B = rows_of(f"foldA_keera_{m}"), rows_of(f"foldB_keera_{m}")
    res = {}
    for scen in ("tel_quel", "exclure_25_UV_fond", "25_UV_fond_comptes_positifs"):
        def tr(rows):
            if scen == "tel_quel":
                return rows
            if scen == "exclure_25_UV_fond":
                return [r for r in rows if r["docket"] not in sus]
            return [{**r, "y": True} if r["docket"] in sus else r for r in rows]
        AA, BB = tr(A), tr(B)
        tA, tB = best_t(AA), best_t(BB)
        res[scen] = {"T1 (pli A)": met(AA, tB), "T4 (pli B)": met(BB, tA)}
        # groupé sur les deux trimestres (micro), seuil transféré de l'autre trimestre pour chaque moitié
        both = AA + BB
        P = [r["s"] for r in both if r["y"]]; H = [r["s"] for r in both if r["hard"] and not r["y"]]
        tp = sum(1 for r in AA if r["y"] and r["s"] >= tB) + sum(1 for r in BB if r["y"] and r["s"] >= tA)
        fp = sum(1 for r in AA if not r["y"] and r["s"] >= tB) + sum(1 for r in BB if not r["y"] and r["s"] >= tA)
        npos = len(P); pr = tp / (tp + fp) if tp + fp else 0; rc = tp / npos
        res[scen]["groupe_2_trimestres"] = {"pos": npos, "auc_hard": round(auc(P, H), 3), "TP": tp, "FP": fp,
                                            "rappel": round(rc, 3), "F2_seuil_transfere": round(5 * pr * rc / (4 * pr + rc), 3) if tp else 0}
    R[m] = res

# quasi-doublons : Jaccard de 5-grammes de mots, positifs + négatifs durs + résumés T3, train vs test de chaque pli
def sh(t):
    w = re.findall(r"\w+", t.lower())
    return {" ".join(w[i:i + 5]) for i in range(0, max(0, len(w) - 4))}

dups = {}
for fold in ("fold_A", "fold_B"):
    docs = {}
    for sp in ("train", "valid", "test"):
        for l in open(os.path.join(a.data, fold, sp + ".jsonl"), encoding="utf-8"):
            j = json.loads(l); mm = j["meta"]
            if mm["kind"] != "easy_negative":
                body = j["prompt"][1]["content"]
                docs[(sp, mm["docket"], j["completion"][0]["content"])] = sh(body)
    te = [k for k in docs if k[0] == "test"]; trn = [k for k in docs if k[0] != "test"]
    hits = []
    for x in te:
        for y in trn:
            sx, sy = docs[x], docs[y]
            if not sx or not sy:
                continue
            j = len(sx & sy) / len(sx | sy)
            if j >= 0.3:
                hits.append([x[1], x[2], y[1], y[2], round(j, 2)])
    dups[fold] = sorted(hits, key=lambda h: -h[4])
R["quasi_doublons_jaccard_ge_0.3"] = dups
json.dump(R, open(os.path.join(a.out, "a06_sensitivity.json"), "w"), ensure_ascii=False, indent=1)
print(json.dumps(R, ensure_ascii=False, indent=1)[:6000])
