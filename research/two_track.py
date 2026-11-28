"""Two-track decision: every full accident/military ruling is submitted; a model decides only the disability-insurance (IV) ones.

two_track(df, iv_features, make_model) -> dict with honest cross-quarter and repeated-CV scores.
The IV threshold is picked on out-of-fold training scores to maximise OVERALL F2 (UV counts included).
"""
import numpy as np, pandas as pd
from sklearn.model_selection import StratifiedKFold
from common import prf, _oof, f2_counts

def _thr(s, y, uv_tp, uv_fp, pol="f2"):
    if pol != "f2":
        need = int(np.ceil(float(pol) * y.sum())); return np.sort(s[y == 1])[::-1][max(need, 1) - 1]
    best, thr = -1, np.inf
    for t in np.r_[np.unique(s), np.inf]:
        m = s >= t; tp = uv_tp + (m & (y == 1)).sum(); fp = uv_fp + (m & (y == 0)).sum(); fn = (~m & (y == 1)).sum()
        f = f2_counts(tp, fp, fn)
        if f > best + 1e-12: best, thr = f, t
    return thr

def two_track(df, iv_features, make_model, name="", pol="f2", repeats=5, verbose=True):
    L = df[df.labelled & df.cand]; UV = L[L.area_uvmv == 1]; IV = L[L.area_iv == 1]
    tot = dict(tp=0, fp=0, fn=0); ivstat = dict(tp=0, kept=0)
    for a, b in [("2025 Q4", "2026 Q1"), ("2026 Q1", "2025 Q4")]:
        tr, te = IV[IV.q == a], IV[IV.q == b]; uvtr, uvte = UV[UV.q == a], UV[UV.q == b]
        Xtr, ytr, Xte, yte = tr[iv_features].values.astype(float), tr.pos.values, te[iv_features].values.astype(float), te.pos.values
        t = _thr(_oof(make_model, Xtr, ytr), ytr, uvtr.pos.sum(), (uvtr.pos == 0).sum(), pol)
        m = make_model().fit(Xtr, ytr).predict_proba(Xte)[:, 1] >= t
        tot["tp"] += int(uvte.pos.sum() + (m & (yte == 1)).sum()); tot["fp"] += int((uvte.pos == 0).sum() + (m & (yte == 0)).sum()); tot["fn"] += int((~m & (yte == 1)).sum())
        ivstat["tp"] += int((m & (yte == 1)).sum()); ivstat["kept"] += int(m.sum())
    X, y = IV[iv_features].values.astype(float), IV.pos.values; f2s, recs, kept = [], [], []
    for rep in range(repeats):
        pred = np.zeros(len(y), bool)
        for tr, te in StratifiedKFold(5, shuffle=True, random_state=100 + rep).split(X, y):
            # UV counts scaled to the training share (4/5) for the threshold choice
            t = _thr(_oof(make_model, X[tr], y[tr], seed=rep), y[tr], UV.pos.sum() * .8, (UV.pos == 0).sum() * .8, pol)
            pred[te] = make_model().fit(X[tr], y[tr]).predict_proba(X[te])[:, 1] >= t
        tp = int(UV.pos.sum() + (pred & (y == 1)).sum()); fp = int((UV.pos == 0).sum() + (pred & (y == 0)).sum()); fn = int((~pred & (y == 1)).sum())
        f2s.append(f2_counts(tp, fp, fn)); recs.append(tp / 59); kept.append(tp + fp)
    r = {"name": name, "xq_f2": f2_counts(**tot), "xq_recall": tot["tp"] / 59, "xq_precision": tot["tp"] / (tot["tp"] + tot["fp"]), "xq_kept": tot["tp"] + tot["fp"],
         "iv_found": ivstat["tp"], "iv_submitted": ivstat["kept"], "rcv_f2": float(np.mean(f2s)), "rcv_f2_sd": float(np.std(f2s)), "rcv_recall": float(np.mean(recs)), "rcv_kept": float(np.mean(kept))}
    if verbose:
        print(f"{name:52s} xq F2={r['xq_f2']:.3f} R={r['xq_recall']:.2f} P={r['xq_precision']:.2f} kept={r['xq_kept']:3d} (IV found {r['iv_found']}/16 in {r['iv_submitted']}) | rcv F2={r['rcv_f2']:.3f}±{r['rcv_f2_sd']:.3f} R={r['rcv_recall']:.2f} kept={r['rcv_kept']:.0f}")
    return r

if __name__ == "__main__":
    from common import load, logreg
    df = load()
    IVF = ["app_inst", "five", "star", "obv"]
    two_track(df, IVF, logreg(), "two-track, IV model on 4 structural features")
    two_track(df, IVF + ["granted", "principle", "lang_fr"], logreg(), "two-track, IV model on 7 structural features")
    for p in ("0.75", "0.9", "1.0"):
        two_track(df, IVF, logreg(), f"two-track, IV threshold keeps {p} of training IV picks", pol=p)
