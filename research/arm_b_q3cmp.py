from arm_b_lib import *
df=load(); g=gold(); g=g[g.language=="de"].set_index("docket").body
l=pd.read_parquet(OUT/"lessons.parquet"); print(len(l), l.lesson.str.len().describe().round().to_dict(), l.finish.value_counts().to_dict())
print("ends without period:", (~l.lesson.str.strip().str.endswith((".",'"'))).sum(), "| contains 'IV-spezifisch':", l.lesson.str.contains("IV-spezifisch").sum(), "| 'Keine übertragbare':", l.lesson.str.contains("Keine übertragbare").sum())
m=l.merge(df[["id","q","cls","pos"]],on="id")
print(m.groupby(["cls","pos"]).lesson.apply(lambda s:s.str.contains("IV-spezifisch").mean()).round(2).to_dict())
for _,r in m[m.q=="2025 Q3"].head(8).iterrows():
    print("\n==",r.docket,r.cls,"\nAPERTUS:",r.lesson,"\nSUVA:",g.get(r.docket,"")[:600])
