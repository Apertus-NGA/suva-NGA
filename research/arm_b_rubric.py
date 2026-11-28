"""Full rubric run. usage: arm_b_rubric.py <fmt> <workers> <stage>   stage: lab | q2 | m8 | lesson"""
import sys, time
from arm_b_lib import *
fmt, W, stage = sys.argv[1], int(sys.argv[2]), sys.argv[3]
df = load()
LAB = df[df.labelled & df.cand]; Q2 = df[(df.q == "2026 Q2") & df.cand]
def run(part, model, bodies, tag, name, QUESTIONS=QUESTIONS):
    jobs = [(r.id, r.docket, q) for _, r in part.iterrows() for q in QUESTIONS]  # doc-major: consecutive calls share the document prefix (gateway prefix cache)
    t = time.time()
    res = chat_many([q_job(model, bodies[i], q, fmt, tag) for i, _, q in jobs], workers=W, progress=200)
    rows = {}
    nerr = 0
    for (i, d, q), x in zip(jobs, res):
        p, h, t_ = parse_q(x, fmt); nerr += p is None
        rows.setdefault(i, dict(id=i, docket=d))[q] = p
        if fmt == "rat": rows[i][q + "_txt"] = t_
    o = pd.DataFrame(rows.values()); o.to_parquet(OUT / name)
    print(name, len(o), "unparsed/errors", nerr, "secs", round(time.time() - t), flush=True)
    return o
if stage == "lab":
    run(LAB, M70, {r.id: doc(r) for _, r in LAB.iterrows()}, f"rubric_{fmt}", "arm_b_rubric_lab.parquet")
elif stage == "q2":
    run(Q2, M70, {r.id: doc(r) for _, r in Q2.iterrows()}, f"rubric_{fmt}", "arm_b_rubric_q2.parquet")
elif stage == "m8":
    S = LAB.sample(60, random_state=7)
    run(S, M8, {r.id: doc(r) for _, r in S.iterrows()}, f"rubric_{fmt}_m8", "arm_b_rubric_m8.parquet")
elif stage == "lesson":
    les = pd.read_parquet(OUT / "lessons.parquet").set_index("id").lesson
    S = LAB[LAB.id.isin(les.index)]
    bodies = {r.id: f"<urteil dossier=\"{r.docket}\">\n<gegenstand>{r.cls}: {str(r.hsubj)[:200]}</gegenstand>\n<zusammenfassung>\n{les[r.id]}\n</zusammenfassung>\n</urteil>" for _, r in S.iterrows()}
    run(S, M70, bodies, f"rubric_{fmt}_lesson", "arm_b_rubric_lesson.parquet", QUESTIONS=["q_rule", "q_new", "q_routine", "q_insurer_lost"])
