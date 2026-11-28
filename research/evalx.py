"""Held-out score tables and recall-first analysis. Complements common.evaluate.

held_out(df, features, make_model, scope) -> DataFrame[id, pos, q, s_xq, s_rcv]
  s_xq  : score from the model trained on the OTHER labelled quarter
  s_rcv : mean out-of-fold score over repeated stratified 5-fold
curve(h, col) -> how many rulings must be submitted to reach each recall level
policy_eval(...) -> honest F2 for threshold policies chosen on training data only
"""
import numpy as np, pandas as pd
from sklearn.model_selection import StratifiedKFold
from common import prf, best_threshold, _oof, f2_counts

def held_out(df, features, make_model, scope="cand", repeats=5):
    L = df[df.labelled]; S = L[L[scope]].copy()
    X, y = S[features].values.astype(float), S.pos.values
    s_xq = np.zeros(len(S))
    for a, b in [("2025 Q4", "2026 Q1"), ("2026 Q1", "2025 Q4")]:
        tr, te = (S.q == a).values, (S.q == b).values
        s_xq[te] = make_model().fit(X[tr], y[tr]).predict_proba(X[te])[:, 1]
    s_rcv = np.zeros(len(S))
    for rep in range(repeats):
        for tr, te in StratifiedKFold(5, shuffle=True, random_state=100 + rep).split(X, y):
            s_rcv[te] += make_model().fit(X[tr], y[tr]).predict_proba(X[te])[:, 1] / repeats
    return pd.DataFrame({"id": S.id.values, "docket": S.docket.values, "q": S.q.values, "cls": S.cls.values, "pos": y, "s_xq": s_xq, "s_rcv": s_rcv})

def curve(h, col="s_xq", total_pos=59, levels=(0.8, 0.85, 0.9, 0.95, 1.0)):
    """Rank within each test quarter (scores of different models are not comparable), pooled."""
    out = {}
    hs = h.copy(); hs["r"] = hs.groupby("q")[col].rank(ascending=False, method="first") / hs.groupby("q")[col].transform("size") if col == "s_xq" else hs[col].rank(ascending=False, method="first") / len(hs)
    hs = hs.sort_values("r")
    cum = hs.pos.cumsum().values
    for lv in levels:
        need = int(np.ceil(lv * total_pos)); idx = np.argmax(cum >= need) if (cum >= need).any() else None
        if idx is None: out[lv] = None
        else:
            kept = idx + 1; tp = int(cum[idx]); out[lv] = {"kept": kept, "precision": round(tp / kept, 3), "f2": round(f2_counts(tp, kept - tp, total_pos - tp), 3)}
    return out

def policy_eval(df, features, make_model, scope="cand", policies=("f2", "r90", "r95", "r100"), repeats=5):
    """Threshold chosen on out-of-fold TRAINING scores: best F2, or lowest cut keeping >=90/95/100% of training positives."""
    L = df[df.labelled]; S = L[L[scope]]
    def thr(s, y, pol):
        if pol == "f2": return best_threshold(s, y)
        need = int(np.ceil({"r90": .90, "r95": .95, "r100": 1.0}[pol] * y.sum())); return np.sort(s[y == 1])[::-1][need - 1]
    res = {}
    for pol in policies:
        tot = dict(tp=0, fp=0, fn=0)
        for a, b in [("2025 Q4", "2026 Q1"), ("2026 Q1", "2025 Q4")]:
            tr, te = S[S.q == a], S[S.q == b]
            Xtr, ytr, Xte, yte = tr[features].values.astype(float), tr.pos.values, te[features].values.astype(float), te.pos.values
            t = thr(_oof(make_model, Xtr, ytr), ytr, pol)
            r = prf(make_model().fit(Xtr, ytr).predict_proba(Xte)[:, 1] >= t, yte, int(L[L.q == b].pos.sum() - yte.sum()))
            for k in tot: tot[k] += r[k]
        X, y = S[features].values.astype(float), S.pos.values; f2s = []; recs = []; kept = []
        for rep in range(repeats):
            pred = np.zeros(len(y), bool)
            for tr, te in StratifiedKFold(5, shuffle=True, random_state=100 + rep).split(X, y):
                t = thr(_oof(make_model, X[tr], y[tr], seed=rep), y[tr], pol)
                pred[te] = make_model().fit(X[tr], y[tr]).predict_proba(X[te])[:, 1] >= t
            r = prf(pred, y, int(L.pos.sum() - y.sum())); f2s.append(r["f2"]); recs.append(r["recall"]); kept.append(r["kept"])
        res[pol] = {"xq_f2": round(f2_counts(**tot), 3), "xq_recall": round(tot["tp"] / 59, 3), "xq_kept": tot["tp"] + tot["fp"],
                    "rcv_f2": round(float(np.mean(f2s)), 3), "rcv_recall": round(float(np.mean(recs)), 3), "rcv_kept": int(np.mean(kept))}
    return res

if __name__ == "__main__":
    from common import load, logreg, DET_FEATURES
    df = load(); h = held_out(df, DET_FEATURES, logreg())
    print("kept needed per recall level, xq:", curve(h, "s_xq")); print("rcv:", curve(h, "s_rcv"))
    for k, v in policy_eval(df, DET_FEATURES, logreg()).items(): print(k, v)
    miss = h[(h.pos == 1)].sort_values("s_rcv").head(14); print(miss[["docket", "cls", "s_xq", "s_rcv"]].round(2).to_string(index=False))
