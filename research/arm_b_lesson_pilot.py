import sys, time
from arm_b_lib import *
ver = sys.argv[1]
df = load(); g = gold(); g = g[g.language=="de"]
ex = pick_examples(); print("examples:", ex.docket.tolist(), ex.cls.tolist(), ex.bl.tolist())
q3 = df[(df.q=="2025 Q3") & ~df.docket.isin(ex.docket)].merge(g, on="docket").head(10)
t=time.time()
res = chat_many([dict(model=M70, messages=lesson_prompt(r, ex.body.tolist(), ver), tag=f"lesson_pilot_{ver}", max_tokens=350) for _,r in q3.iterrows()], progress=0)
print("secs", time.time()-t, "usage", res[0]["usage"])
for (_,r),x in zip(q3.iterrows(), res):
    print("\n=====", r.docket, r.cls, x["error"], x.get("finish")); print("APERTUS:", x["text"]); print("SUVA:", r.body[:900])
