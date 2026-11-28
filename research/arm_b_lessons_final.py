"""Write lessons.parquet from the cache (whatever is finished): labelled 221 + Q3 gold 23 + Q2 done so far."""
import sqlite3, json
from arm_b_lib import *
df = load(); con = sqlite3.connect("research/cache/apertus.sqlite")
rows = []
for rq, rs in con.execute("select request,response from calls where tag='lesson_v4'"):
    d = re.search(r'dossier="([^"]+)"', json.loads(rq)["messages"][1]["content"]).group(1)
    x = json.loads(rs)["choices"][0]
    rows.append(dict(docket=d, lesson=x["message"]["content"], finish=x["finish_reason"]))
o = pd.DataFrame(rows).drop_duplicates("docket").merge(df[["id", "docket", "q", "cand"]], on="docket")
o["model"] = M70; o["prompt_version"] = "v4"; o["error"] = None
o[["id", "docket", "lesson", "model", "prompt_version", "finish", "error"]].to_parquet(OUT / "lessons.parquet")
print(o.q.value_counts().to_dict(), "of Q2 cand", int(((df.q == "2026 Q2") & df.cand).sum()), "| finish", o.finish.value_counts().to_dict())
