import sys; sys.path.insert(0, r"C:\pt\swarm")
import numpy as np, pandas as pd, json
from tools.research.model_parity import harness as h
from tools.research.model_parity import t3_baselines as t3
snaps, bands = h.candidate_inputs()
m = t3.load_metar(-10)  # available = valid exactly
m = m[m.local_date >= "2026-07-25"].sort_values(["station","local_date","valid_utc"]).copy()
m["cmx"] = m.groupby(["station","local_date"]).temp_f.cummax()
m["prev"] = m.groupby(["station","local_date"])["cmx"].shift(1)
m["newmax"] = m.cmx > m.prev
m["key"] = m.station + "|" + m.local_date
s = snaps[["row_key","station","date","captured_at_utc","high_so_far","trusted_current_max","local_hour"]].copy()
s["t"] = pd.to_datetime(s.captured_at_utc, utc=True).astype("datetime64[us, UTC]")
s["key"] = s.station + "|" + s.date
s = s.sort_values("t"); mm = m.sort_values("valid_utc")
mm["valid_utc"] = mm.valid_utc.astype("datetime64[us, UTC]")
j = pd.merge_asof(s, mm[["key","valid_utc","cmx","prev","newmax"]], left_on="t", right_on="valid_utc", by="key", direction="backward")
j = j[j.newmax == True]
j["age"] = (j.t - j.valid_utc).dt.total_seconds()/60
j["obs"] = j[["high_so_far","trusted_current_max"]].max(axis=1)
j = j[j.obs.notna() & (j.local_hour >= 10)]
j["has"] = j.obs >= j.cmx
j["hasprev"] = j.obs >= j.prev
for lo, hi in [(0,5),(5,10),(10,15),(15,20),(20,30),(30,45),(45,60),(60,90)]:
    g = j[(j.age >= lo) & (j.age < hi)]
    print(f"age {lo:>2}-{hi:<2} min n={len(g):5d} captured_obs>=new_metar_max {g.has.mean():.3f}  >=prev_max {g.hasprev.mean():.3f}")
g = j[(j.age >= 20) & (j.age < 60) & (~j.has)]
print("non-matching at 20-60 min: cmx-obs value counts", (g.cmx - g.obs).round(1).value_counts().head(6).to_dict())
print("hsf present share", g.high_so_far.notna().mean(), "tcm present", g.trusted_current_max.notna().mean())
j["has5"] = (j.obs + 0.5) >= j.cmx
for lo, hi in [(0,5),(5,10),(10,15),(15,20),(20,30),(30,45),(45,60)]:
    g = j[(j.age >= lo) & (j.age < hi)]
    print(f"TOL0.5 age {lo:>2}-{hi:<2} n={len(g):5d} captured_obs+0.5>=new_metar_max {g.has5.mean():.3f}")
