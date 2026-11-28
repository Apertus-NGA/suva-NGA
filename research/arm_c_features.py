"""Arm C: leakage-safe neighbour features from cached embeddings (research/cache/emb/<model>__<part>.npz).

emb_features(model_name, part, ids_train, y_train, ids_target, loo=False) -> DataFrame indexed by target id with
  max_pos   max cosine to a relevant training ruling
  knn5/10   share of relevant among the 5 / 10 nearest training rulings
  diff5     mean cosine to top-5 relevant minus mean cosine to top-5 non-relevant training rulings
  gold_max  max cosine to a Suva German gold summary; reference = 2025 Q3 summaries + summaries of
            ids_train only, never the target's own summary
For part 'chunks' the similarity of two rulings is the best-matching chunk pair (ruling-gold: best chunk).
loo=True: targets that are themselves in ids_train do not see themselves (use for training rows).
A target is never its own neighbour and never sees its own summary, whatever `loo` says.
model_name: 'bge-m3' | 'e5-instruct'; part: subject | facts | reasoning | core | chunks | lesson;
append '~lc' to a part (e.g. 'core~lc') for the language-centred variant.
"""
from __future__ import annotations
import sys
from functools import lru_cache
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np, pandas as pd

EMB = Path(__file__).resolve().parent / "cache" / "emb"
FEATS = ["max_pos", "knn5", "knn10", "diff5", "gold_max"]


@lru_cache(None)
def load_part(model: str, part: str):
    lc = part.endswith("~lc")      # variant: subtract the per-language mean vector (unsupervised), renormalise
    z = np.load(EMB / f"{model}__{part.removesuffix('~lc')}.npz")
    ids, X = z["ids"], z["X"].astype(np.float32)
    if lc:
        from common import load
        lang = load().set_index("id").language.reindex(ids).values if part != "gold~lc" else np.array(["g"] * len(ids))
        X = X.copy()
        for l in np.unique(lang):
            X[lang == l] -= X[lang == l].mean(0)
        X /= np.linalg.norm(X, axis=1, keepdims=True) + 1e-9
    o = np.argsort(ids, kind="stable")
    return ids[o], X[o]


def _groupmax(M: np.ndarray, ids: np.ndarray, axis: int):
    u, start = np.unique(ids, return_index=True)   # ids sorted
    return u, np.maximum.reduceat(M, start, axis=axis)


@lru_cache(None)
def sim_all(model: str, part: str):
    """(ruling ids, ruling x ruling similarity); chunked parts reduced with max over chunk pairs."""
    ids, X = load_part(model, part)
    S = X @ X.T
    u, S = _groupmax(S, ids, 0)
    _, S = _groupmax(S, ids, 1)
    return u, S


@lru_cache(None)
def gold_all(model: str, part: str):
    """(ruling ids, gold ruling ids, ruling x gold-summary similarity)."""
    ids, X = load_part(model, part)
    gid, G = load_part(model, "gold~lc" if part.endswith("~lc") else "gold")
    u, S = _groupmax(X @ G.T, ids, 0)
    return u, gid, S


@lru_cache(None)
def doc_vectors(model: str, part: str):
    """One L2-normalised vector per ruling (mean of chunks for chunked parts)."""
    ids, X = load_part(model, part)
    u, inv = np.unique(ids, return_inverse=True)
    V = np.zeros((len(u), X.shape[1]), np.float32); np.add.at(V, inv, X)
    return u, V / np.linalg.norm(V, axis=1, keepdims=True)


@lru_cache(None)
def _q3_ids() -> frozenset:
    from common import load
    d = load()
    return frozenset(d[d.q == "2025 Q3"].id.tolist())


def emb_features(model_name, part, ids_train, y_train, ids_target, loo=False) -> pd.DataFrame:
    ids_train, y_train, ids_target = np.asarray(ids_train), np.asarray(y_train).astype(int), np.asarray(ids_target)
    u, S = sim_all(model_name, part)
    pos = {v: i for i, v in enumerate(u)}
    keep = np.array([i in pos for i in ids_train])
    tr_ids, ytr = ids_train[keep], y_train[keep]
    tr = np.array([pos[i] for i in tr_ids], int)
    gu, gid, GS = gold_all(model_name, part)
    gpos = {v: i for i, v in enumerate(gu)}
    ref_ok = np.isin(gid, list(_q3_ids() | set(ids_train.tolist())))
    out = np.full((len(ids_target), len(FEATS)), np.nan)
    for r, t in enumerate(ids_target):
        if t not in pos:
            continue
        s = S[pos[t], tr]
        m = tr_ids != t                       # never a neighbour of itself
        s, y = s[m], ytr[m]
        sp, sn = np.sort(s[y == 1])[::-1], np.sort(s[y == 0])[::-1]
        o = np.argsort(-s)
        g = GS[gpos[t], ref_ok & (gid != t)]
        out[r] = [sp[0] if len(sp) else 0, y[o[:5]].mean(), y[o[:10]].mean(),
                  (sp[:5].mean() if len(sp) else 0) - (sn[:5].mean() if len(sn) else 0),
                  g.max() if len(g) else 0]
    cols = [f"{model_name}_{part}_{f}" for f in FEATS]
    return pd.DataFrame(out, index=pd.Index(ids_target, name="id"), columns=cols)
