"""Arm C sanity: does a ruling retrieve its OWN Suva summary (top-1 among the 55 German summaries)? And kNN purity for area/language."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
from common import load
from arm_c_features import gold_all, sim_all, EMB
df = load().set_index("id")
for f in sorted(EMB.glob("*__*.npz")):
    model, part = f.stem.split("__")
    if part == "gold":
        continue
    u, gid, G = gold_all(model, part)
    rows = [i for i, v in enumerate(u) if v in set(gid)]
    top1 = np.mean([gid[G[i].argmax()] == u[i] for i in rows])
    fr = [i for i in rows if df.language[u[i]] == "fr"]
    top1fr = np.mean([gid[G[i].argmax()] == u[i] for i in fr]) if fr else np.nan
    _, S = sim_all(model, part); S = S.copy(); np.fill_diagonal(S, -1)
    nn = S.argmax(1); cls = df.cls.reindex(u).values; lang = df.language.reindex(u).values
    print(f"{model:12s} {part:10s} own-summary top1 {top1:.2f} (n={len(rows)}; French rulings {top1fr:.2f}, n={len(fr)}) | "
          f"nearest neighbour same area {np.mean(cls[nn]==cls):.2f} same language {np.mean(lang[nn]==lang):.2f}")
