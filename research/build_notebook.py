"""Builds notebooks/02_relevance_research.ipynb from the result files in research/out and executes it."""
import nbformat as nbf
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
nb = nbf.v4.new_notebook()
C = []
md = lambda s: C.append(nbf.v4.new_markdown_cell(s.strip()))
code = lambda s: C.append(nbf.v4.new_code_cell(s.strip()))

md("""
# Relevance triage for Suva: what works, measured

Research sprint of 27 November 2026 (two hours). Goal: the best way to (1) decide whether a Federal Supreme Court ruling is relevant for Suva and (2) give it a score out of 100, using Apertus v1.5 and classical machine learning. The challenge scores recall first, then F2.

**Result in one paragraph.** Three deterministic gates remove 3,715 of 3,936 rulings without losing any of Suva's 59 picks. On the 221 that remain, a logistic regression on six structural features reaches a held-out F2 of about 0.76 at recall 0.83. Nothing else tested beats it: not the Apertus 70B model deciding alone (0.72 to 0.73), not twenty Apertus rubric answers, not embeddings from two models on six parts of the ruling, not gradient boosting or XGBoost. A stronger reader model given the same information also stops at about 0.74, and near-identical rulings carry opposite labels, so about 0.76 to 0.78 looks like the ceiling for this label set. The real choice left is the cut-off: submit the top 40% of candidates (recall about 0.83), the top 60% (recall about 0.93 at the same F2, when four Apertus rule-versus-routine answers are added to the score), or about 90% (recall 1.00, F2 0.68).

Everything here was measured on Q4/2025 and Q1/2026 only. Q2/2026 has no labels and was never used for tuning.
""")
code("""
import json, warnings
import numpy as np, pandas as pd, matplotlib.pyplot as plt
from pathlib import Path
warnings.filterwarnings("ignore")
OUT = Path("../research/out")
pd.set_option("display.max_colwidth", 90); pd.set_option("display.width", 200)
BLUE, ORANGE, INK, MUTED = "#2a78d4", "#eb6834", "#191919", "#666666"   # validated for colour-blind separation
plt.rcParams.update({"figure.dpi": 110, "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": "#cccccc",
                     "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED, "text.color": INK, "font.size": 10})
""")

md("""
## 1. Data and evaluation protocol

| Set | Rulings | Relevant |
|---|---|---|
| All rulings decided Q4/2025 + Q1/2026 | 3,936 | 59 |
| After gate 1: division 8C or 9C | 693 | 59 |
| After gate 2: area accident, military or disability insurance | 292 | 59 |
| After gate 3: not a single-judge decision ("candidates") | 221 | 59 |
| Candidates in Q2/2026 (prediction target) | 129 | unknown |

Among the 221 candidates, 70 are accident or military insurance (43 relevant, 61%) and 151 are disability insurance (16 relevant, 11%).

**Protocol, identical for every method**
- **Cross-quarter**: train on Q4, test on Q1, then the reverse; counts pooled.
- **Repeated cross-validation**: stratified 5-fold over both quarters, five repeats.
- **Cut-off** chosen for F2 on out-of-fold *training* scores only.
- **All 59 picks count**: a pick outside the scored set is a miss.
- **Leakage controls**: Suva summaries used as prompt examples come from Q3/2025 only; neighbour-based embedding features use training rulings only.

Scores below are written as cross-quarter / repeated CV.
""")
code("""
head = pd.DataFrame([
 ("Submit every candidate (gates only)",                 0.646, 0.646, 1.00, 221, "rule"),
 ("Submit every full accident/military ruling",          0.703, 0.703, 0.73,  70, "rule"),
 ("Original Suva rubric as 9 features, logistic",        0.708, 0.729, 0.76,  82, "classical"),
 ("TF-IDF of the reasoning text, logistic",              0.671, 0.677, 0.90, 159, "classical"),
 ("Gradient boosting, 11 structural features",           0.741, 0.750, 0.81,  88, "classical"),
 ("XGBoost (depth 2), 6 structural features",            0.750, 0.734, 0.81,  84, "classical"),
 ("XGBoost (depth 2), 11 structural features",           0.763, 0.738, 0.83,  85, "classical"),
 ("XGBoost (depth 2), 6 structural + 9 Apertus answers", 0.675, 0.697, 0.83, 127, "combined"),
 ("Logistic regression, 11 structural features",         0.756, 0.766, 0.83,  88, "classical"),
 ("Logistic regression, 6 structural features  (A)",     0.759, 0.768, 0.83,  87, "classical"),
 ("Apertus 70B alone, plain prompt",                     0.674, 0.661, 0.93, 172, "apertus"),
 ("Apertus 70B alone, best prompt (strict rubric)",      0.732, 0.723, 0.88, 119, "apertus"),
 ("Apertus 8B alone, same prompt",                       0.610, 0.659, 0.68,  92, "apertus"),
 ("Apertus 70B alone, forced real reasoning",            0.684, 0.685, 0.88, 144, "apertus"),
 ("Apertus sees picked/non-picked examples",             0.596, np.nan, 0.83, 175, "apertus"),
 ("9 Apertus rubric answers only, logistic",             0.704, 0.701, 0.80,  98, "apertus"),
 ("6 structural + Apertus principle, 4 answers  (C)",    0.731, 0.747, 0.86, 113, "combined"),
 ("6 structural + Apertus principle, 11 answers  (D)",   0.752, 0.754, 0.86, 103, "combined"),
 ("11 structural + all 9 Apertus answers",               0.676, 0.732, 0.76,  97, "combined"),
 ("11 structural + Apertus 70B score",                   0.756, 0.746, 0.83,  88, "combined"),
 ("11 structural + best embedding features",             0.772, 0.717, 0.85,  88, "combined"),
], columns=["method", "F2 cross-quarter", "F2 repeated CV", "recall (cross-quarter)", "submitted of 221", "family"])
head
""")
code("""
h = head.sort_values("F2 cross-quarter"); fig, ax = plt.subplots(figsize=(8.6, 5.6))
ax.axvspan(0.69, 0.85, color="#f0f0f0", zorder=0); ax.text(0.848, -0.75, "95% bootstrap interval of model A", ha="right", va="top", fontsize=8, color=MUTED)
ax.barh(h.method, h["F2 cross-quarter"], height=0.55, color=BLUE, zorder=2)
for y, v in enumerate(h["F2 cross-quarter"]): ax.text(v + 0.004, y, f"{v:.3f}", va="center", fontsize=8.5)
ax.set_xlim(0.55, 0.86); ax.set_xlabel("held-out F2 (cross-quarter)"); ax.grid(axis="x", color="#e6e6e6", zorder=1); ax.tick_params(length=0)
ax.set_title("Every method lands inside the noise band of the simplest model", loc="left", fontsize=11); plt.tight_layout(); plt.show()
""")
md("""
**How to read this.** With 59 relevant rulings, finding one more or one fewer moves F2 by about 0.015, and the 95% bootstrap interval of model A's F2 is 0.69 to 0.85. Differences of 0.01 to 0.03 between methods are not real. What is real: the gates, the jump from "submit all" (0.65) to a structural model (0.76), and the failure of the plain 70B prompt and the examples prompt.
""")

md("""
## 2. Can the 70B model do the task itself with a good prompt?

No. It reaches F2 0.72 to 0.73 at best, below six structural features, and adding its score to the structural model changes nothing. Ten prompt variants were run on all 221 candidates.
""")
code("""
a = pd.read_csv(OUT / "arm_a_eval.csv")
cols = [c for c in ["variant", "own_f2", "own_R", "own_P", "own_kept", "xq_f2", "rcv_f2", "auc_uv", "auc_iv", "n@90", "n@100"] if c in a.columns]
a[cols].rename(columns={"own_f2": "own yes/no F2", "own_R": "recall", "own_P": "precision", "own_kept": "said yes", "xq_f2": "score, tuned cut (xq)", "rcv_f2": "(rcv)",
                        "auc_uv": "ranking inside accident ins.", "auc_iv": "inside disability ins.", "n@90": "submit for 90% recall", "n@100": "for 100%"}).round(3)
""")
md("""
- **It says yes too often**: 56 to 97% of rulings against a true rate of 27%.
- **It reproduces "accident insurance yes, disability mostly no"** and barely ranks inside either area (0.5 is chance, 1.0 perfect).
- **Typical errors**: calls every routine confirmation a "clarification"; rejects disability rulings Suva picked as "not transferable".

**What prompt style works on Apertus** (measured here, plus the model's own documentation):

| Choice | Finding |
|---|---|
| Rubric with base rates in the prompt | Essential. The plain prompt says yes to 215 of 221. |
| Label first, score from the token probability of "Ja" | Ranks better than rationale-then-label, and about 9 times faster. |
| Rationale then a 0 to 100 number | Scores cluster on 0, 10, 85, 90, 95 and nothing in between. |
| Suva summaries as examples | No gain. |
| Showing picked and non-picked examples and asking by analogy | Fails: yes to almost everything, ranking worse than chance. |
| Input | Header + reasoning + ruling beat the full text in the pilot (0.71 against 0.56). |
| Document first, question last, own system message, temperature 0 | Followed throughout (from the model card and general practice). |
| Narrow questions | "Applies to accident insurance?", "affects practice?" get 90 to 100% yes and are useless. Questions with a natural "no" ("states a rule?", "something new?") carry signal. |
| Forced choice among six categories | Avoids yes-bias; similar signal to the yes/no questions. |
| 8B instead of 70B | Close on most questions; disagrees about half the time on three of nine. |
| Thinking mode | Has to be forced with a prefill on this gateway; once forced, no gain (0.70) at about 1,100 tokens per ruling. See section 9. |
""")

md("""
## 3. Classical models: which model, which features, which training set?
""")
code("""
d = pd.read_csv(OUT / "arm_d_results.csv")
d[["name", "scope", "n_feat", "n_train", "xq_f2", "xq_recall", "xq_kept", "rcv_f2", "rcv_f2_sd"]].rename(columns={"scope": "trained on", "n_feat": "features", "n_train": "rows",
   "xq_f2": "F2 xq", "xq_recall": "recall", "xq_kept": "submitted", "rcv_f2": "F2 rcv", "rcv_f2_sd": "spread"}).round(3)
""")
md("""
- **Model type**: logistic regression is best and far more stable (spread 0.005 against 0.02 to 0.03 for tree models). Deeper boosting overfits (0.67). XGBoost results are in the next table.
- **Training set**: `cand` (the 221 gated candidates) is best or tied. `g_div` (all 693 of 8C/9C) and `_all` (all 3,936) are not better. The easy negatives teach the model nothing about the hard cases.
- **More features hurt**: 20 features or interaction terms score lower than 11, and 6 do as well as 11.
""")
code("""
x = pd.read_csv(OUT / "arm_m_xgboost.csv")
x[["name", "scope", "n_feat", "xq_f2", "xq_recall", "xq_kept", "rcv_f2", "rcv_f2_sd"]].rename(columns={"scope": "trained on", "n_feat": "features", "xq_f2": "F2 xq", "xq_recall": "recall", "xq_kept": "submitted", "rcv_f2": "F2 rcv", "rcv_f2_sd": "spread"}).round(3)
""")
md("""
**XGBoost** (run after installing the OpenMP library it needs on macOS):
- On structural features it matches logistic regression within noise: 0.75 to 0.76 cross-quarter, 0.73 to 0.77 in repeated CV, with three to four times the spread.
- Given more features it gets worse, not better: 20 structural features 0.73 / 0.71; with the nine Apertus answers 0.68 / 0.70. Trees fit noise in the weak features.
- Trained on all of 8C/9C or on all 3,936 rulings (with class weighting) it reaches 0.74 to 0.75, no better than training on the gated candidates. Without class weighting on all rulings it drops to 0.62.
- At the "top 60%" cut-off, XGBoost with the principle feature reaches recall 0.89 to 0.92; logistic regression reaches 0.91 to 0.95.

Logistic regression stays the recommendation: same accuracy, more stable, and its weights translate directly into rubric points.
""")
code("""
ab = pd.read_csv(OUT / "arm_d_ablation.csv").rename(columns={"d_xq_f2": "change in F2 (xq)", "d_rcv_f2": "(rcv)", "d_ap": "change in ranking quality"})
ab.sort_values("(rcv)")
""")
md("""
**Feature verdicts**

| Feature | Built by | Reliable? | Verdict |
|---|---|---|---|
| Area: accident/military vs disability | code (court list, header fallback) | yes; header agrees with list in 99.2% | keep |
| Appeal brought by insurer or authority | code (party block in header) | yes on 35 checked rows | keep: the single most valuable feature (-0.05 to -0.08 F2 without it) |
| Five judges | code | yes | keep |
| Marked for publication | court list only | unknown for 618 Q2 rulings | keep, treat unknown as "no" |
| Dismissed as manifestly unfounded | code (standard phrases, Art. 109) | yes | keep |
| Suva is a party | code | yes; all 108 mentions verified as the same Suva | keep (small weight) |
| Single-judge decision | code | yes | used as a gate |
| Other accident insurer, topics count, star unknown, Suva mentioned | code | yes | no measurable value once the six above are in |
| Text length, citations, remand, language, number of considerations | code | yes | no value or harmful |
| "States a rule", "decides something new", "factual dispute", "routine" | Apertus 70B, one yes/no call each | about 78% of answers defensible on a hand check | modest signal (ranking 0.66 to 0.72 inside an area); usable as one averaged "principle" feature |
| "Applies to accident insurance", "affects practice", "newsletter-worthy" | Apertus 70B | no: 90 to 100% yes | drop |
| Lesson statement of the ruling | Apertus 70B | 6 of 8 match Suva's chosen point | useful for the product, not for classification |
| Similarity to picked rulings / Suva summaries | embedding model | embeddings work, feature does not predict | drop for classification |
""")

md("""
## 4. Apertus as rubric filler: which questions carry signal?

One call per question per ruling, answer stored as the probability of "Ja". Ranking quality (AUC) is shown separately inside each area, because the area itself is already known.
""")
code("""
import sys; sys.path.insert(0, "../research")
from sklearn.metrics import roc_auc_score
from common import load
df = load(); L = df[df.labelled & df.cand]
ans = pd.read_parquet(OUT / "rubric_answers.parquet")
more = pd.read_parquet(OUT / "more_answers_lab.parquet") if (OUT / "more_answers_lab.parquet").exists() else None
D = L.merge(ans, on="id", suffixes=("", "_y"))
if more is not None: D = D.merge(more, on="id")
qs = [c for c in D.columns if c.startswith("q_")]
uv, iv = D[D.area_uvmv == 1], D[D.area_iv == 1]
T = pd.DataFrame([{"question": q, "share yes": (D[q] > .5).mean(), "ranking inside accident ins.": roc_auc_score(uv.pos, uv[q]), "inside disability ins.": roc_auc_score(iv.pos, iv[q])} for q in qs]).round(2)
T["distance from chance"] = ((T["ranking inside accident ins."] - .5).abs() + (T["inside disability ins."] - .5).abs()).round(2)
T.sort_values("distance from chance", ascending=False)
""")
md("""
Values below 0.5 mean "yes" predicts *not* picked (`q_factual`, `q_routine`, `q_stdonly`).

- The useful questions all ask the same thing from different angles: **does the court say something about the law, or only review this case's evidence?**
- Averaging four of them into one "principle" feature gives 0.66 / 0.72. Averaging eleven gives 0.63 / 0.69. The signal saturates near 0.7.
- Added to the structural model, the principle feature does not raise the best F2. It gets a small positive weight (about 5 to 7 points of 100).
- Asking the questions on the short lesson statement instead of the ruling loses signal (0.59 against 0.71 inside disability insurance for "states a rule").
""")

md("""
## 5. Embeddings: what to embed, which model?

Two open-weights multilingual models (BGE-M3, multilingual-e5-large-instruct; both MIT licence), six parts of the ruling, three families of neighbour features plus PCA and kNN, evaluated with leak-free neighbours.
""")
code("""
c = pd.read_csv(OUT / "arm_c_results.csv"); c = c[c.det == 1]
p = c.pivot_table(index=["model", "part"], columns="fs", values=["xq_f2", "rcv_f2"], aggfunc="max")
best = c.sort_values("rcv_f2", ascending=False).groupby(["model", "part"]).head(1)[["model", "part", "fs", "xq_f2", "rcv_f2", "auc_uv", "auc_iv"]]
print("Best feature set per model and part, ADDED to the 11 structural features (baseline 0.756 / 0.766):")
best.sort_values(["model", "part"]).rename(columns={"fs": "feature set", "xq_f2": "F2 xq", "rcv_f2": "F2 rcv", "auc_uv": "ranking inside accident ins.", "auc_iv": "inside disability ins."}).round(3)
""")
md("""
- **No combination beats the structural baseline on both protocols.** The best cross-quarter result (0.772) drops to 0.717 in repeated CV; the best repeated-CV result (0.768) is 0.742 cross-quarter.
- **The embeddings themselves work**: a ruling retrieves its own Suva summary first among 55 in 75% of cases (BGE-M3 on reasoning chunks). Similar topic simply does not mean "picked".
- **Inside an area the neighbour features rank at chance level.** Overall they rediscover the area.
- **Apertus lesson statements** embed no better than raw text for this purpose.
- **Recommendation**: no embedding features in the classifier. If embeddings are wanted for the product (finding similar summarised rulings), use BGE-M3 on 1,500-character chunks of the core reasoning.
""")

md("""
## 6. Is there more signal to find? A ceiling diagnostic

Two blind reader agents running a stronger model than Apertus (development only, not part of any pipeline) each studied one labelled quarter (metadata plus lesson statement per ruling) and scored the other quarter.
""")
code("""
b = pd.read_csv(OUT / "diag/blind_reader_scores.csv")
def f2(tp, fp, fn): return 5 * tp / (5 * tp + 4 * fn + fp)
best = max(f2(((b.score >= t) & (b.pos == 1)).sum(), ((b.score >= t) & (b.pos == 0)).sum(), ((b.score < t) & (b.pos == 1)).sum()) for t in b.score.unique())
print("ranking inside accident insurance:", round(roc_auc_score(b[b.cls != "IV"].pos, b[b.cls != "IV"].score), 2),
      "| inside disability insurance:", round(roc_auc_score(b[b.cls == "IV"].pos, b[b.cls == "IV"].score), 2),
      "| best F2 with the ideal cut-off chosen afterwards:", round(best, 3))
""")
md("""
A stronger reader with the same information does no better than six structural features, and both readers reported that near-identical rulings carry opposite labels (two premium rulings, two relapse rulings, usable-work-capacity rulings on both sides). The choice inside an area is largely not predictable from the ruling. Treating the labels as ground truth, **about 0.76 to 0.78 F2 is the practical ceiling** at the best-F2 cut-off.

Caveat: the readers saw Apertus-written lesson statements, not the full rulings.
""")

md("""
## 7. The decision that matters: where to cut

The cut-off is chosen on training folds only. "Recall + F2" is shown because the challenge names both.
""")
code("""
o = pd.read_csv(OUT / "arm_i_operating_points.csv")
o["cut-off"] = o.policy.map({"f2": "best F2", "r90": "keep 90% of training picks", "r95": "keep 95%", "r100": "keep 100%"})
o[o.model.str[0].isin(list("ACD"))][["model", "cut-off", "xq_f2", "xq_recall", "xq_kept", "xq_sum", "rcv_f2", "rcv_recall", "rcv_kept", "rcv_sum"]].rename(columns={
  "xq_f2": "F2 xq", "xq_recall": "recall xq", "xq_kept": "submitted xq", "xq_sum": "recall+F2 xq", "rcv_f2": "F2 rcv", "rcv_recall": "recall rcv", "rcv_kept": "submitted rcv", "rcv_sum": "recall+F2 rcv"})
""")
code("""
s = {k: pd.read_csv(OUT / f"labelled_scores_{k}.csv") for k in "AC"}
fig, ax = plt.subplots(figsize=(7.6, 4.2))
for (k, lab, col) in (("A", "A. six structural features", BLUE), ("C", "C. + Apertus principle", ORANGE)):
    d = s[k].sort_values("oof_score", ascending=False); rec = d.pos.cumsum().values / 59; n = np.arange(1, len(d) + 1)
    ax.plot(n, rec, color=col, lw=2, label=lab); ax.text(n[-1] + 2, rec[-1] - (0.03 if k == "A" else -0.02), lab.split(".")[0], color=INK, fontsize=9)
ax.plot([0, 221], [0, 1], color="#cccccc", lw=1, ls="--"); ax.text(150, 0.62, "no model (random order)", color=MUTED, fontsize=8, rotation=27)
ax.axvline(87, color="#bbbbbb", lw=1); ax.text(89, 0.05, "best-F2 cut", fontsize=8, color=MUTED); ax.axvline(197, color="#bbbbbb", lw=1); ax.text(165, 0.05, "recall-first cut", fontsize=8, color=MUTED)
ax.set_xlabel("rulings submitted, in score order (of 221 candidates)"); ax.set_ylabel("share of Suva's 59 picks found"); ax.set_ylim(0, 1.03); ax.set_xlim(0, 236)
ax.grid(color="#eeeeee"); ax.legend(frameon=False, loc="lower right", bbox_to_anchor=(0.98, 0.18)); ax.set_title("Out-of-fold recall by number submitted", loc="left", fontsize=11); plt.tight_layout(); plt.show()
""")
md("""
- **Best-F2 cut**: about 87 of 221 submitted, recall 0.83 to 0.84, F2 0.76 to 0.77. The 9 misses are all disability-insurance rulings without any structural signal.
- **Recall-first cut**: 197 of 221 submitted, recall 1.00, F2 0.68. At this point the model equals a plain rule: submit every candidate except disability rulings dismissed as manifestly unfounded (24 rulings, none picked).
- **In between** the curve is steep and flat in turns: the last 10 picks are spread among about 110 disability rulings. The Apertus principle feature pulls a few of them forward in some folds but not reliably.
- If recall and F2 count equally, recall-first wins (1.68 against 1.59 to 1.61). If F2 dominates, best-F2 wins (0.76 against 0.68).
""")

md("""
### A cut-off that needs no tuning: submit the top share of candidates

Choosing a score threshold on 59 positives is fragile. Fixing the share in advance ("submit the top 60% of candidates by score") is honest by construction and easier to explain.
""")
code("""
t = pd.read_csv(OUT / "arm_l_topshare.csv"); t = t[t.model.str[0].isin(list("ACD"))]
w = t.pivot(index="top share", columns="model", values=["recall xq", "recall rcv", "F2 xq", "F2 rcv"]).round(3); w
""")
md("""
- **Top 40%**: all models equal (recall 0.81 to 0.83, F2 0.74 to 0.76). This is the best-F2 region.
- **Top 60%**: the models with the Apertus principle feature reach recall 0.92 to 0.95 at F2 0.74 to 0.76; the structural model alone reaches 0.89 to 0.90 at 0.72. That is two to three more picks found for the same number submitted, consistent across both protocols but still within noise.
- **Top 90%**: recall 0.98 to 1.00, F2 0.67 to 0.68, all models equal.
- **Recall + F2** is highest around the top 60% with model C or D (1.66 to 1.71) and at the top 90% (1.65 to 1.68).

So the Apertus answers do not move the best F2, but they improve the order in the middle of the list, where the disability-insurance picks sit. For Q2 the top 60% is 77 of 129 candidates.
""")

md("""
## 8. Score out of 100

Suva's own rubric is a points system, so the score is built the same way: each rule adds or subtracts points, with weights fitted on the labelled data (logistic regression, rescaled so the lowest possible total is 0 and the highest 100).
""")
code("""
pts = pd.read_csv(OUT / "arm_i_points_C.csv"); fin = json.load(open(OUT / "arm_i_final_C.json"))
names = {"area_uvmv": "Area is accident or military insurance", "app_inst": "Appeal brought by an insurer or authority", "five": "Five judges", "star": "Marked for publication",
         "obv": "Dismissed as manifestly unfounded", "suva_party": "Suva is a party", "principle": "Apertus: court states or refines a rule (0 to 1, average of 4 answers)"}
pts["rule"] = pts.rule.map(names); print("base points:", round(fin["base_points"]), "| cut-offs on this scale:", {k: round(v, 1) for k, v in fin["cuts"].items()})
pts[["rule", "points"]]
""")
code("""
sc = s["C"]; bins = [0, 12, 17, 30, 45, 60, 101]
sc["band"] = pd.cut(sc.oof_score, bins, right=False)
g = sc.groupby("band", observed=True).pos.agg(["count", "sum"]); g["share picked"] = (g["sum"] / g["count"]).round(2)
g.rename(columns={"count": "labelled rulings (out-of-fold score)", "sum": "picked by Suva"})
""")
md("""
The points total rises with the share actually picked, so it can be shown to lawyers as a relevance score with a per-rule explanation. Rulings outside the gates get 0. A displayed percentage ("share of similar rulings Suva picked") can be read off the band table.

The Apertus principle rule is in the score with a small weight. It adds explanation and ranking detail, not measurable accuracy.
""")

md("""
## 9. Thinking mode

On this gateway the 70B model does not reason by itself, even through the `-thinking` model name: with a custom system message nothing happens, and without one it still answers directly on long prompts. Real reasoning has to be forced by prefilling the assistant turn with the reasoning-start token `<|inner_prefix|>` (thinking model, no system message, `continue_final_message`). The model then writes a structured analysis and closes it itself. A second call asks the base 70B model for a one-word verdict given that reasoning, so the result can be ranked by token probability.
""")
code("""
t = pd.read_parquet(OUT / "arm_n_thinking2.parquet").merge(L[["id", "pos", "area_uvmv", "area_iv"]], on="id")
t["decision"] = t.decision.fillna((t.p_yes > .5).astype(int)); tp = int(((t.decision == 1) & (t.pos == 1)).sum()); fp = int(((t.decision == 1) & (t.pos == 0)).sum()); fn = 59 - tp
print(f"reasoning block completed in {int(t.closed.sum())} of {len(t)} rulings | median length {int(t.think_chars.median())} characters, about {int(t.ctok.median())} tokens")
print(f"own decision after reasoning: F2 {5*tp/(5*tp+4*fn+fp):.3f} | recall {tp/59:.2f} | said yes {tp+fp} of {len(t)}")
print("ranking inside accident ins.:", round(roc_auc_score(t[t.area_uvmv==1].pos, t[t.area_uvmv==1].p_yes), 2), "| inside disability ins.:", round(roc_auc_score(t[t.area_iv==1].pos, t[t.area_iv==1].p_yes), 2))
""")
md("""
| 70B configuration | F2 | Recall | Said yes |
|---|---|---|---|
| Label first, no reasoning (best) | 0.70 own / 0.73 tuned | 0.92 / 0.88 | 148 / 119 |
| "Thinking" model without the prefill (no real reasoning) | 0.69 | 0.85 | 128 |
| Forced real reasoning, about 1,100 tokens per ruling | 0.70 own / 0.68 tuned | 0.90 / 0.88 | 145 / 144 |

- Reasoning does not help. The decisions are no better, and the ranking inside each area falls to chance (0.50 and 0.57).
- Added to the six structural features it lowers the score slightly (0.741 / 0.742 against 0.759 / 0.768).
- The reasoning reads well but argues towards yes: it finds a transferable point in most rulings.
- It costs about 1,100 output tokens per ruling against 1 for the label-first prompt.

Label first with token probabilities stays the best Apertus configuration.
""")

md("""
## 10. Q2/2026 preview (unlabelled; nothing here was tuned on it)
""")
code("""
q = pd.read_csv(OUT / "q2_predictions_C.csv"); qa = pd.read_csv(OUT / "q2_predictions_A.csv")
sub = [c for c in q.columns if c.startswith("submit_")]
print("Q2 candidates:", len(q), "| decided in June:", (q.decision_date >= "2026-06-01").sum())
print("submitted, model C:", {c.replace("submit_", ""): int(q[c].sum()) for c in sub}); print("submitted, model A:", {c.replace("submit_", ""): int(qa[c].sum()) for c in sub})
print("\\nTop June rulings by score (model C):"); q[q.decision_date >= "2026-06-01"][["docket", "decision_date", "cls", "score", "subject"]].head(8)
""")

md("""
## 11. Recommended pipeline and open decisions

**Pipeline**
1. **Gates (code)**: division 8C or 9C; area accident, military or disability insurance (header fallback when the list value is missing); not a single-judge decision. Keeps every labelled pick.
2. **Structural features (code)**: appeal by insurer or authority, five judges, publication, manifestly unfounded, Suva as party, area.
3. **Apertus 70B (one call per question, label first, token probability)**: four rule-versus-routine questions averaged into one "principle" value, each with a one-sentence reason for the lawyer; plus the lesson statement that seeds the summary.
4. **Logistic regression trained on the gated candidates** combines 2 and 3 into the 0 to 100 points score.
5. **Cut-off** according to the scoring priority (below).

**Decisions for you**
- **Cut-off**: three defensible points. Top 40% (about 52 of 129 Q2 candidates; recall about 0.82, F2 about 0.75), top 60% with model C (77 of 129; recall about 0.93, F2 about 0.75), or recall first (113 to 116 of 129; recall about 1.00, F2 about 0.68). I recommend the top 60% with model C: it keeps F2 at the ceiling while raising recall by about ten points, which matters when recall is scored first.
- **Apertus in the classifier or not**: at the best-F2 point model A (no Apertus) and model C (with the principle feature) are indistinguishable. In the middle of the list C orders rulings better. C also keeps Apertus inside the scoring, which matters for the "Apertus performs the core task" rule. Apertus deciding alone costs about 0.03 F2.
- **Embeddings**: not for classification. Optional for a "similar rulings" feature in the UI.

**Caveats**
- 59 positives. Every number carries about ±0.08 F2 of uncertainty.
- Labels inside an area look partly arbitrary (February 2026: 2 of 10 accident rulings picked), which caps what any model can reach.
- The publication star is unknown for 618 Q2 rulings and is treated as "no" there.
- The feature set was shaped by analysis of these same two quarters, so held-out scores are mildly optimistic.

**Reproduce**: `uv run python research/common.py`, then `arm_d_classical.py`, `arm_g_composite.py`, `arm_i_final.py C`, all in `research/`. Apertus answers are cached in `research/cache/apertus.sqlite`; agent reports are in `research/out/arm_*_report.md`; the progress log is in `research/updates/`.
""")

nb["cells"] = C
nb.metadata["kernelspec"] = {"display_name": "Python 3", "language": "python", "name": "python3"}
p = ROOT / "notebooks" / "02_relevance_research.ipynb"
nbf.write(nb, p)
print("written", p)
