import json,sys,collections
p=sys.argv[1];T=1e-9
B=[("00-05",0,5),("06-09",6,9),("10-12",10,12),("13-16",13,16),("17-23",17,23)]
def blk(h): return next((n for n,a,b in B if h is not None and a<=h<=b),"none")
st=collections.OrderedDict((n,dict(rows=0,lit_pos=0,lit_max=0.0,exceeds_old=0,floored=0,pre_lockin=0,below_floor_viol=0,below_floor_max=0.0)) for n,_,_ in B+[("none",0,0)])
dmin=dmax=None;ver=collections.Counter();other=collections.Counter()
with open(p,encoding="utf-8") as f:
  for line in f:
    r=json.loads(line)
    if "new_final" not in r: other[str(r.get("status"))]+=1; continue
    d=r["target_date"];dmin=min(dmin or d,d);dmax=max(dmax or d,d);ver[str(r.get("anchor_version"))]+=1
    s=st[blk(r.get("hour"))];s["rows"]+=1
    nb,ob=r.get("new_mass_below_anchor"),r.get("old_mass_below_anchor")
    if nb is not None and nb>T: s["lit_pos"]+=1;s["lit_max"]=max(s["lit_max"],nb)
    if nb is not None and ob is not None and nb>ob+T and not r.get("carried_prior_day_rows"): s["exceeds_old"]+=1
    a=r.get("lockin_anchor") or {};fb=a.get("observed_floor_bucket")
    if fb is not None:
      s["floored"]+=1;s["pre_lockin"]+=a.get("observed_floor_stage")=="pre_lockin"
      m=sum(v for k,v in r["new_final"].items() if int(k)<fb);s["below_floor_max"]=max(s["below_floor_max"],m);s["below_floor_viol"]+=m>T
blocks=[s for n,s in st.items() if n!="none"]
dates_ok=dmin is not None and dmin>="2026-08-25" and dmax<="2026-09-29"
r1=all(s["exceeds_old"]==0 for s in blocks)
r3=all(s["rows"]>0 and s["below_floor_viol"]==0 for s in blocks) and sum(s["pre_lockin"] for s in blocks)>0 and set(ver)<={"lockin-anchor-v4","None"}
r2=all(s["lit_pos"]==0 for s in blocks)
v="FAIL" if not(dates_ok and r1 and r3) else ("PASS_LITERAL" if r2 else "PASS_B_FLOOR_ONLY_NEEDS_JUDGEMENT")
print(json.dumps(dict(verdict=v,dates=[dmin,dmax],dates_ok=dates_ok,R1_floor_check=r1,R3_b_floor_invariant=r3,R2_literal_zero_below_anchor=r2,anchor_versions=ver,non_compared=other,blocks=st),indent=1))
sys.exit({"PASS_LITERAL":0,"PASS_B_FLOOR_ONLY_NEEDS_JUDGEMENT":10}.get(v,1))
