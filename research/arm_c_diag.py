"""Arm C: leave-one-out AUC of each raw neighbour feature over the 221 labelled candidates, overall and within area.
(LOO over both labelled quarters; descriptive only, not the F2 protocol.) -> research/out/arm_c_auc.csv
Also: neighbours restricted to the same area. '~lc' = language-centred variant."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np, pandas as pd
from sklearn.metrics import roc_auc_score
from common import load, OUT
from arm_c_features import emb_features, FEATS, EMB

df = load(); S = df[df.labelled & df.cand]
ids = S.id.values; y = S.pos.values; uv = (S.area_uvmv == 1).values; iv = (S.area_iv == 1).values
combos = [(m, p + s) for m, p in (f.stem.split("__") for f in sorted(EMB.glob("*__*.npz"))) if p != "gold" for s in ("", "~lc")]
rows = []
for model, part in combos:
    F = emb_features(model, part, ids, y, ids, loo=True).fillna(0)
    for c, n in zip(F.columns, FEATS):
        v = F[c].values
        rows.append(dict(model=model, part=part, feat=n, auc=roc_auc_score(y, v), auc_uv=roc_auc_score(y[uv], v[uv]),
                         auc_iv=roc_auc_score(y[iv], v[iv])))
    sa = []
    for m in (uv, iv):   # neighbours among same-area rulings only
        G = emb_features(model, part, ids[m], y[m], ids[m], loo=True).fillna(0)
        sa += [roc_auc_score(y[m], G.iloc[:, 2]), roc_auc_score(y[m], G.iloc[:, 3])]
    rows.append(dict(model=model, part=part, feat="sameArea_knn10", auc=np.nan, auc_uv=sa[0], auc_iv=sa[2]))
    rows.append(dict(model=model, part=part, feat="sameArea_diff5", auc=np.nan, auc_uv=sa[1], auc_iv=sa[3]))
R = pd.DataFrame(rows).round(3); R.to_csv(OUT / "arm_c_auc.csv", index=False)
pd.set_option("display.width", 250)
print(R.pivot_table(index=["model", "part"], columns="feat", values=["auc", "auc_uv", "auc_iv"]).round(2).to_string())
