"""Audit suva-ft-v3 : plancher sans LLM, règle minimale à 3 signaux (matière, recevabilité, longueur), aucun poids appris.
score = 2*[UV ou MV] + 1*[IV] + 1*[pas irrecevable] + longueur/1e6. Seuil F2 choisi sur l'autre trimestre.
Usage : python3 -I -B a07_rule_minimal.py a02_features.json
"""
import json, sys
F = json.load(open(sys.argv[1], encoding="utf-8"))
def s(f): return 2 * (f["matiere"] in ("UV", "MV")) + (f["matiere"] == "IV") + (not f["irrecevable"]) + min(f["chars"], 60000) / 1e6
def auc(p, n): return sum((x > y) + 0.5 * (x == y) for x in p for y in n) / (len(p) * len(n))
def f2(rows, t):
    tp = sum(1 for r in rows if r[1] and r[0] >= t); fp = sum(1 for r in rows if not r[1] and r[0] >= t); P = sum(r[1] for r in rows)
    pr = tp / (tp + fp) if tp + fp else 0; rc = tp / P
    return (5 * pr * rc / (4 * pr + rc) if pr + rc else 0), tp, fp
Q = {q: [(s(f), f["pos"], f["matiere"] in ("UV", "IV", "MV")) for f in F.values() if f["q"] == q] for q in ("2025Q4", "2026Q1")}
out = {}
for q, o in (("2026Q1", "2025Q4"), ("2025Q4", "2026Q1")):
    t = max({r[0] for r in Q[o]}, key=lambda t: f2(Q[o], t)[0])
    f, tp, fp = f2(Q[q], t)
    P = [r[0] for r in Q[q] if r[1]]; H = [r[0] for r in Q[q] if r[2] and not r[1]]; N = [r[0] for r in Q[q] if not r[1]]
    out[q] = {"auc": round(auc(P, N), 3), "auc_hard": round(auc(P, H), 3), "F2_seuil_transfere": round(f, 3), "TP": tp, "FP": fp}
print(json.dumps(out, indent=1))
