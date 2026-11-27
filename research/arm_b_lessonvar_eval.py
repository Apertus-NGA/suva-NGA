from arm_b_lib import *
from common import evaluate, logreg, DET_FEATURES
from sklearn.metrics import roc_auc_score
df = load(); QS = ["q_rule", "q_new", "q_routine", "q_insurer_lost"]
for nm in ["arm_b_rubric_lab.parquet", "arm_b_rubric_lesson.parquet"]:
    d = df.merge(pd.read_parquet(OUT / nm)[["id"] + QS], on="id", how="left"); d[QS] = d[QS].fillna(0.5)
    C = d[d.labelled & d.cand]
    print(nm, {q: (round(roc_auc_score(C[C.cls=="UV"].pos, C[C.cls=="UV"][q]), 2), round(roc_auc_score(C[C.cls=="IV"].pos, C[C.cls=="IV"][q]), 2)) for q in QS}, "(AUC UV, AUC IV)")
    evaluate(d, DET_FEATURES + QS, logreg(), "cand", "DET + 4 questions: " + nm[12:-8])
l = pd.read_parquet(OUT / "lessons.parquet"); print(len(l), l.finish.value_counts().to_dict(), l.lesson.isna().sum())
