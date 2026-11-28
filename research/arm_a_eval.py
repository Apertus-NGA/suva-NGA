import sys, json
import numpy as np, pandas as pd
from sklearn.metrics import roc_auc_score
from arm_a_lib import *
from common import prf, evaluate, logreg, DET_FEATURES

df = load(); L = df[df.labelled]
rows = []
for k in sys.argv[1:]:
    d = pd.read_parquet(OUT / f"arm_a_{k}.parquet")
    m = df.merge(d[["id", "decision", "score", "rationale"]], on="id", how="left")
    m["dec"] = m.decision.fillna(0).astype(int)
    m["llm"] = m.score.fillna(m.dec * 100).fillna(0)
    Lm = m[m.labelled]; Cm = Lm[Lm.cand]
    r = prf(Lm.dec.values.astype(bool), Lm.pos.values)
    acc = {c: round(float((Cm[Cm.cls == c].dec == Cm[Cm.cls == c].pos).mean()), 3) for c in ["UV", "IV"]}
    yes = {c: f"{int(Cm[Cm.cls == c].dec.sum())}/{int((Cm.cls == c).sum())}" for c in ["UV", "IV"]}
    auc = {c: round(roc_auc_score(Cm[Cm.cls == c].pos, Cm[Cm.cls == c].llm), 3) for c in ["UV", "IV"]}
    print(f"\n=== {k}: own decision F2={r['f2']:.3f} R={r['recall']:.3f} P={r['precision']:.3f} kept={r['kept']} tp={r['tp']} | unparsed={int(Cm.decision.isna().sum())} noscore={int(Cm.score.isna().sum())}")
    print("   acc", acc, "yes", yes, "AUC all", round(roc_auc_score(Cm.pos, Cm.llm), 3), "within-class AUC", auc)
    vc = Cm.llm.round().value_counts().sort_index()
    print("   score dist:", {int(a): int(b) for a, b in vc.items()} if len(vc) < 25 else Cm.llm.describe().round(1).to_dict(),
          "| share multiples of 5:", round(float((Cm.llm.round() % 5 == 0).mean()), 2), "| share >=50:", round(float((Cm.llm >= 50).mean()), 2))
    def need(sub, rec):
        P = int(sub.pos.sum()); best = len(sub)
        for t in np.unique(sub.llm):
            if (sub[sub.llm >= t].pos.sum()) >= np.ceil(rec * P - 1e-9): best = min(best, int((sub.llm >= t).sum()))
        return best
    nd = {f"n@{int(x*100)}": need(Cm, x) for x in (0.9, 0.95, 1.0)}
    ndiv = {f"iv_n@{int(x*100)}": need(Cm[Cm.cls == "IV"], x) for x in (0.9, 1.0)}
    ivs = Cm[Cm.cls == "IV"]; uvs = Cm[Cm.cls == "UV"]
    cm = {c: dict(tp=int(((x.dec == 1) & (x.pos == 1)).sum()), fp=int(((x.dec == 1) & (x.pos == 0)).sum()), fn=int(((x.dec == 0) & (x.pos == 1)).sum()), tn=int(((x.dec == 0) & (x.pos == 0)).sum())) for c, x in (("UV", uvs), ("IV", ivs))}
    print("   submit-count for recall (ties included):", nd, "| IV only (151, 16 pos):", ndiv, "| confusion", cm)
    e = evaluate(m, ["llm"], logreg(), "cand", f"{k} score only")
    e2 = evaluate(m, DET_FEATURES + ["llm"], logreg(), "cand", f"{k} score + 11 deterministic")
    rows.append(dict(variant=k, own_f2=r["f2"], own_R=r["recall"], own_P=r["precision"], own_kept=r["kept"], acc_uv=acc["UV"], acc_iv=acc["IV"],
                     auc=roc_auc_score(Cm.pos, Cm.llm), auc_uv=auc["UV"], auc_iv=auc["IV"],
                     xq_f2=e["xq_f2"], xq_R=e["xq_recall"], xq_P=e["xq_precision"], xq_kept=e["xq_kept"], rcv_f2=e["rcv_f2"],
                     det_xq_f2=e2["xq_f2"], det_rcv_f2=e2["rcv_f2"], **nd, **ndiv, iv_tp=cm["IV"]["tp"], iv_fp=cm["IV"]["fp"], uv_tp=cm["UV"]["tp"], uv_fp=cm["UV"]["fp"]))
t = pd.DataFrame(rows).round(3); print("\n" + t.to_string()); t.to_csv(OUT / "arm_a_eval.csv", index=False)
