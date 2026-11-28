"""Metrics shared by 02_train_eval.py and 03_keera_baseline.py (no torch)."""


def auc(pos, neg):
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def metrics(res):
    pos = [r["score"] for r in res if r["label"] == "Ja"]
    neg = [r["score"] for r in res if r["label"] != "Ja"]
    hard = [r["score"] for r in res if r["kind"] == "hard_negative"]
    out = {"n": len(res), "n_pos": len(pos), "auc": auc(pos, neg), "auc_vs_hard": auc(pos, hard),
           "mean_mass_ja_nein": sum(r["mass"] for r in res) / len(res)}
    for thr in (0.5, 0.1, 0.01):
        tp = sum(s >= thr for s in pos); fp = sum(s >= thr for s in neg)
        prec = tp / (tp + fp) if tp + fp else 0.0; rec = tp / len(pos) if pos else 0.0
        f2 = 5 * prec * rec / (4 * prec + rec) if prec + rec else 0.0
        out[f"thr_{thr}"] = {"recall": rec, "precision": prec, "f2": f2, "tp": tp, "fp": fp}
    # threshold giving 100 % recall: how many negatives must a lawyer read?
    if pos:
        m = min(pos)
        out["fp_at_full_recall"] = sum(s >= m for s in neg)
    return out
