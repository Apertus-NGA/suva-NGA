import numpy as np
from sklearn.metrics import roc_auc_score
from arm_b_lib import *
df = load(); a = pd.read_parquet(OUT/"arm_b_rubric_lab.parquet").set_index("id"); b = pd.read_parquet(OUT/"arm_b_rubric_m8.parquet").set_index("id")
pos = df.set_index("id").pos.reindex(b.index)
print("n", len(b), "pos", int(pos.sum()), "| 8B missing:", b[list(QUESTIONS)].isna().sum().sum())
print("| question | agree (hard) | corr P(Ja) | Ja% 70B | Ja% 8B | AUC 70B (60) | AUC 8B (60) |"); print("|---|---|---|---|---|---|---|")
for q in QUESTIONS:
    x, y = a.loc[b.index, q], b[q].fillna(0.5)
    print(f"| {q} | {((x>.5)==(y>.5)).mean():.2f} | {np.corrcoef(x,y)[0,1]:.2f} | {100*(x>.5).mean():.0f} | {100*(y>.5).mean():.0f} | {roc_auc_score(pos,x):.2f} | {roc_auc_score(pos,y):.2f} |")
