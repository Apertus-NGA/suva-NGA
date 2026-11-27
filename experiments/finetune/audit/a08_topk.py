"""Audit suva-ft-v3 : F2 et rappel à liste de taille fixe (top-k), indépendant de la calibration du score.
Usage : python3 -I -B a08_topk.py runs_v3 a02_features.json
"""
import json, os, sys
runs, feat = sys.argv[1], json.load(open(sys.argv[2], encoding="utf-8"))
def rule(f): return 2 * (f["matiere"] in ("UV", "MV")) + (f["matiere"] == "IV") + (not f["irrecevable"]) + min(f["chars"], 60000) / 1e6
def topk(rows, k):
    srt = sorted(rows, key=lambda r: -r[0])[:k]; tp = sum(r[1] for r in srt); P = sum(r[1] for r in rows)
    pr, rc = tp / k, tp / P
    return [tp, round(5 * pr * rc / (4 * pr + rc), 3) if tp else 0]
out = {}
for d in sorted(os.listdir(runs)):
    p = os.path.join(runs, d, "test_scores.jsonl")
    if not os.path.exists(p):
        continue
    rows = [(j["score"], j["label"] == "Ja", j["decision_id"]) for j in map(json.loads, open(p, encoding="utf-8"))]
    out[d] = {f"top{k}_[TP,F2]": topk(rows, k) for k in (30, 45, 60, 80, 100)}
    if d.endswith("_8b"):
        rr = [(rule(feat[i]), y, i) for _, y, i in rows]
        out[d.replace("keera_8b", "regle_minimale")] = {f"top{k}_[TP,F2]": topk(rr, k) for k in (30, 45, 60, 80, 100)}
print(json.dumps(out, indent=1))
