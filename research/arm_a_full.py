import sys
from arm_a_lib import *
V = {
 "rubric":        dict(prompt="rubric"),
 "rubric_label":  dict(prompt="rubric", out="label"),
 "strict":        dict(prompt="strict"),
 "check":         dict(prompt="check"),
 "strict_label":  dict(prompt="strict", out="label"),
 "area_label":    dict(prompt="area", out="label"),
 "area":          dict(prompt="area"),
 "area_label_8b": dict(prompt="area", out="label", model=M8),
 "strict_label_8b": dict(prompt="strict", out="label", model=M8),
 "fewshot_label": dict(prompt="fewshot", out="label"),
 "plain_label":   dict(prompt="plain", out="label"),
 "rubric_8b":     dict(prompt="rubric", model=M8),
 "strict_think":  dict(prompt="strict", model=M70T),
 "rubric_think":  dict(prompt="rubric", model=M70T),
}
df = load(); C = df[df.labelled & df.cand]
for k in sys.argv[1:]:
    d = run(C, "full_" + k, **V[k])
    print(k, "errors", int(d.error.notna().sum()), "unparsed", int(d.decision.isna().sum()), "yes", int((d.decision == 1).sum()), flush=True)
    d[["id", "decision", "score", "p_yes", "rationale", "raw", "error"]].to_parquet(OUT / f"arm_a_{k}.parquet")
