"""Generate lesson statements (prompt v3, M70). Writes research/out/lessons.parquet incrementally."""
import sys
from arm_b_lib import *
W = int(sys.argv[1]) if len(sys.argv) > 1 else 4
df = load(); g = gold(); ex = pick_examples()
parts = [df[df.labelled & df.cand], df[(df.q == "2025 Q3") & df.docket.isin(g.docket)], df[(df.q == "2026 Q2") & df.cand]]
rows = []
for part in parts:
    res = chat_many([dict(model=M70, messages=lesson_prompt(r, ex.body.tolist(), "v4"), tag="lesson_v4", max_tokens=220) for _, r in part.iterrows()], workers=W, progress=40)
    for (_, r), x in zip(part.iterrows(), res):
        rows.append(dict(id=r.id, docket=r.docket, lesson=x["text"], model=M70, prompt_version="v4", finish=x.get("finish"), error=x["error"]))
    pd.DataFrame(rows).to_parquet(OUT / "lessons.parquet")
    print("written", len(rows), "errors", sum(x["error"] is not None for x in rows), flush=True)
