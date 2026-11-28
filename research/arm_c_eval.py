"""Arm C: evaluate embedding features. Mirrors common.evaluate (xq + repeated CV, inner-OOF threshold),
but recomputes neighbour features per split from training rulings only.
usage: arm_c_eval.py [model,model] [part,part]   -> research/out/arm_c_results.csv (appends/replaces rows)"""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np, pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.decomposition import PCA
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from common import load, DET_FEATURES, prf, best_threshold, _oof, f2_counts, logreg, OUT
from arm_c_features import emb_features, doc_vectors, FEATS, EMB

df = load()
L = df[df.labelled]
S = L[L.cand].reset_index(drop=True)
IDS, Y, Q = S.id.values, S.pos.values, S.q.values
DET = S[DET_FEATURES].values.astype(float)
ND = DET.shape[1]
UV, IV = (S.area_uvmv == 1).values, (S.area_iv == 1).values


def pca_model(k, with_det):
    def mk():
        if with_det:
            ct = ColumnTransformer([("det", StandardScaler(), list(range(ND))),
                                    ("emb", make_pipeline(PCA(k, random_state=0), StandardScaler()), slice(ND, None))])
        else:
            ct = make_pipeline(PCA(k, random_state=0), StandardScaler())
        return make_pipeline(ct, LogisticRegression(C=1.0, class_weight="balanced", max_iter=2000))
    return mk


def knn_model():
    return lambda: KNeighborsClassifier(n_neighbors=10, metric="cosine", weights="distance")


def make_builder(kind, model, part, cols, with_det):
    """returns f(tr_idx, te_idx) -> Xtr, Xte using training rulings only for neighbour features."""
    if kind == "nb":
        def f(tr, te):
            a = emb_features(model, part, IDS[tr], Y[tr], IDS[tr], loo=True)
            b = emb_features(model, part, IDS[tr], Y[tr], IDS[te])
            c = [f"{model}_{part}_{x}" for x in cols]
            A, B = a[c].fillna(0).values, b[c].fillna(0).values
            return (np.hstack([DET[tr], A]), np.hstack([DET[te], B])) if with_det else (A, B)
    elif kind == "det":
        f = lambda tr, te: (DET[tr], DET[te])
    else:
        u, V = doc_vectors(model, part)
        p = {v: i for i, v in enumerate(u)}
        E = np.vstack([V[p[i]] if i in p else np.zeros(V.shape[1], np.float32) for i in IDS])
        def f(tr, te):
            return (np.hstack([DET[tr], E[tr]]), np.hstack([DET[te], E[te]])) if with_det else (E[tr], E[te])
    return f


def evaluate(name, build, mk, repeats=5):
    res = {"name": name}
    tot = {"tp": 0, "fp": 0, "fn": 0}
    for a, b in [("2025 Q4", "2026 Q1"), ("2026 Q1", "2025 Q4")]:
        tr, te = np.where(Q == a)[0], np.where(Q == b)[0]
        Xtr, Xte = build(tr, te)
        miss_tr = int(L[L.q == a].pos.sum() - Y[tr].sum()); miss_te = int(L[L.q == b].pos.sum() - Y[te].sum())
        thr = best_threshold(_oof(mk, Xtr, Y[tr]), Y[tr], miss_tr)
        s = mk().fit(Xtr, Y[tr]).predict_proba(Xte)[:, 1]
        r = prf(s >= thr, Y[te], miss_te)
        for k in tot:
            tot[k] += r[k]
    res.update(xq_f2=f2_counts(**tot), xq_recall=tot["tp"] / (tot["tp"] + tot["fn"]),
               xq_precision=tot["tp"] / max(tot["tp"] + tot["fp"], 1), xq_kept=tot["tp"] + tot["fp"])
    miss = int(L.pos.sum() - Y.sum())
    f2s, aps, auv, aiv = [], [], [], []
    for rep in range(repeats):
        pred = np.zeros(len(Y), bool); sc = np.zeros(len(Y))
        for tr, te in StratifiedKFold(5, shuffle=True, random_state=100 + rep).split(DET, Y):
            Xtr, Xte = build(tr, te)
            thr = best_threshold(_oof(mk, Xtr, Y[tr], seed=rep), Y[tr], 0)
            s = mk().fit(Xtr, Y[tr]).predict_proba(Xte)[:, 1]
            pred[te] = s >= thr; sc[te] = s
        f2s.append(prf(pred, Y, miss)["f2"]); aps.append(average_precision_score(Y, sc))
        auv.append(roc_auc_score(Y[UV], sc[UV])); aiv.append(roc_auc_score(Y[IV], sc[IV]))
    res.update(rcv_f2=np.mean(f2s), rcv_sd=np.std(f2s), rcv_min=np.min(f2s), rcv_max=np.max(f2s), ap=np.mean(aps),
               auc_uv=np.mean(auv), auc_iv=np.mean(aiv))
    print(f"{name:44s} xq F2={res['xq_f2']:.3f} R={res['xq_recall']:.2f} P={res['xq_precision']:.2f} kept={res['xq_kept']:3d} | "
          f"rcv F2={res['rcv_f2']:.3f}±{res['rcv_sd']:.3f} AP={res['ap']:.3f} | AUC UV={res['auc_uv']:.3f} IV={res['auc_iv']:.3f}", flush=True)
    return res


if __name__ == "__main__":
    models = sys.argv[1].split(",") if len(sys.argv) > 1 else ["bge-m3", "e5-instruct"]
    want = sys.argv[2].split(",") if len(sys.argv) > 2 else ["subject", "facts", "reasoning", "core", "chunks", "lesson"]
    print(f"cand {len(S)} pos {Y.sum()} | UV/MV n={UV.sum()} pos={Y[UV].sum()} | IV n={IV.sum()} pos={Y[IV].sum()}")
    rows = [dict(evaluate("DET alone", make_builder("det", None, None, None, True), logreg()), model="-", part="-", fs="det", det=1)]
    SETS = {"nb4": FEATS[:4], "gold": ["gold_max"], "nb4+gold": FEATS, "diff5": ["diff5"], "diff5+gold": ["diff5", "gold_max"]}
    for model in models:
        for part in want:
            if not (EMB / f"{model}__{part.removesuffix('~lc')}.npz").exists():
                print("skip (no matrix)", model, part); continue
            t0 = time.time()
            for wd in (0, 1):
                tag = "+DET" if wd else "alone"
                for fs, cols in SETS.items():
                    rows.append(dict(evaluate(f"{model}/{part}/{fs} {tag}", make_builder("nb", model, part, cols, wd), logreg()),
                                     model=model, part=part, fs=fs, det=wd))
                for k in (8, 16):
                    rows.append(dict(evaluate(f"{model}/{part}/pca{k} {tag}", make_builder("vec", model, part, None, wd), pca_model(k, wd)),
                                     model=model, part=part, fs=f"pca{k}", det=wd))
            rows.append(dict(evaluate(f"{model}/{part}/knn10clf alone", make_builder("vec", model, part, None, 0), knn_model()),
                             model=model, part=part, fs="knn10clf", det=0))
            print(f"  [{time.time()-t0:.0f}s]")
    new = pd.DataFrame(rows)
    p = OUT / "arm_c_results.csv"
    if p.exists():
        old = pd.read_csv(p); new = pd.concat([old[~old.name.isin(new.name)], new])
    new.to_csv(p, index=False)
