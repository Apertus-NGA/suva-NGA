from arm_b_lib import *
df=load(); g=gold(); g=g[g.language=="de"].set_index("docket").body
o=pd.read_parquet(OUT/"arm_b_pilot.parquet"); o=o[o.fmt=="rat"]
ids=o.drop_duplicates("id"); ids=pd.concat([ids[ids.pos==1].head(5), ids[ids.pos==0].head(4)])
for i in ids.id:
    r=df[df.id==i].iloc[0]
    print("\n#####",r.docket,r.cls,"pos",r.pos,"| subj:",str(r.hsubj)[:80],"| disp:",re.sub(r"\s+"," ",r.dispositive[:260]))
    if r.docket in g.index: print("SUVA:",g[r.docket][:500])
    else: print("REASONING TAIL:",re.sub(r"\s+"," ",r.reasoning[-900:]))
    for _,x in o[o.id==i].iterrows(): print(" >",x.q,"|",re.sub(r"\s+"," ",x.text)[:420])
