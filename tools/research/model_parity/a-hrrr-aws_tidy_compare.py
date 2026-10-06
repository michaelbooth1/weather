"""A-HRRR-AWS tidy + compare with A-SingleRuns HRRR + MANIFEST. Development only."""
from __future__ import annotations

import glob
import hashlib
import json
import os
import datetime as dt

import numpy as np
import pandas as pd

OUT = r"C:\swarm\data\hrrr_aws"
RES = r"C:\swarm\out\a-hrrr-aws"
recs = []
for p in sorted(glob.glob(os.path.join(OUT, "parts", "*.jsonl"))):
    for ln in open(p):
        recs.append(json.loads(ln))
status = pd.Series([r["status"] for r in recs]).value_counts().to_dict()
objs, rows = [], []
for r in recs:
    if r["status"] != "ok":
        objs.append({k: r.get(k) for k in ("key", "status")})
        continue
    o = {k: v for k, v in r.items() if k != "rows"}
    objs.append(o)
    for x in r["rows"]:
        rows.append(x | {"available_utc": r["grib_last_modified"], "idx_last_modified": r["idx_last_modified"]})
df = pd.DataFrame(rows)
for c in ("run_utc", "valid_utc", "available_utc", "idx_last_modified"):
    df[c] = pd.to_datetime(df[c], utc=True)
df["avail_delay_min"] = (df.available_utc - df.run_utc).dt.total_seconds() / 60
df.to_parquet(os.path.join(OUT, "hrrr_aws_tmp2m.parquet"), index=False)
ob = pd.DataFrame([o for o in objs if o.get("status") == "ok"])
ob["run_utc"] = pd.to_datetime(ob.key.str.extract(r"hrrr\.(\d{8})")[0] + ob.key.str.extract(r"t(\d\d)z")[0], format="%Y%m%d%H", utc=True)
ob["fh"] = ob.key.str.extract(r"wrfsfcf(\d\d)")[0].astype(int)
ob["lm"] = pd.to_datetime(ob.grib_last_modified, utc=True)
ob["delay_min"] = (ob.lm - ob.run_utc).dt.total_seconds() / 60
ob["cyc"] = ob.run_utc.dt.hour
avail = ob.groupby(["cyc", "fh"]).delay_min.describe(percentiles=[.5, .95])[["count", "min", "50%", "95%", "max"]].round(1)
# f00 after f01?
piv = ob.pivot_table(index="run_utc", columns="fh", values="lm", aggfunc="first")
f00_after_f01 = int((piv[0] > piv[1]).sum())
f00_after_f12 = int((piv[0] > piv[12]).sum())
max_delay = ob.groupby("run_utc").delay_min.max()
over3h = int((ob.delay_min > 180).sum())

# compare with Single-Runs
sr = pd.read_parquet(r"C:\swarm\data\singleruns\singleruns_long.parquet")
sr = sr[(sr.model == "ncep_hrrr_conus") & sr.run_utc.dt.hour.isin([12, 18]) & (sr.lead_h <= 12)]
m = df.merge(sr[["station", "run_utc", "valid_utc", "lead_h", "temperature_2m", "available_utc_design",
                 "grid_lat", "grid_lon"]].rename(columns={"grid_lat": "sr_lat", "grid_lon": "sr_lon"}),
             on=["station", "run_utc", "valid_utc"], how="outer", indicator=True)
merge_counts = m._merge.value_counts().to_dict()
mm = m[(m._merge == "both")].copy()
mm = mm[mm.temperature_2m.notna() & mm.tmp2m_f.notna()]
mm["d"] = mm.temperature_2m - mm.tmp2m_f  # Single-Runs minus AWS, degF
mm["ad"] = mm.d.abs()
def summ(g):
    return pd.Series({"n": len(g), "bias_F": g.d.mean(), "mae_F": g.ad.mean(), "rmse_F": np.sqrt((g.d**2).mean()),
                      "p95_abs_F": g.ad.quantile(.95), "max_abs_F": g.ad.max(), "frac_le_0.5F": (g.ad <= .5).mean(),
                      "frac_le_1F": (g.ad <= 1).mean()})
by_lead = mm.groupby("fh").apply(summ).round(3)
by_station = mm.groupby("station").apply(summ).round(3)
by_cyc = mm.groupby(mm.run_utc.dt.hour).apply(summ).round(3)
overall = summ(mm).round(3)
by_month = mm.groupby(mm.run_utc.dt.strftime("%Y-%m")).apply(summ).round(3)
# run-max over f01..f12 (proxy for a hrrr_high-type quantity)
rm = mm[mm.fh >= 1].groupby(["station", "run_utc"]).agg(aws=("tmp2m_f", "max"), sr=("temperature_2m", "max"), n=("fh", "size"))
rm = rm[rm.n == 12]
rm["d"] = rm.sr - rm.aws
runmax = {"n": len(rm), "bias_F": round(rm.d.mean(), 3), "mae_F": round(rm.d.abs().mean(), 3),
          "max_abs_F": round(rm.d.abs().max(), 3), "frac_le_0.5F": round((rm.d.abs() <= .5).mean(), 3)}
worst = mm.sort_values("ad", ascending=False).head(15)[["station", "run_utc", "fh", "tmp2m_f", "temperature_2m", "d"]]
grid_off = mm.groupby("station").agg(aws_lat=("grid_lat", "first"), aws_lon=("grid_lon", "first"),
                                     sr_lat=("sr_lat", "first"), sr_lon=("sr_lon", "first"))
# design availability check: Single-Runs +3h vs AWS LastModified
mm["sr_avail_minus_aws_min"] = (mm.available_utc_design - mm.available_utc).dt.total_seconds() / 60
sr_avail_ok = float((mm.sr_avail_minus_aws_min >= 0).mean())


def md(df, index=True):
    d = df.reset_index() if index else df
    cols = [str(c) for c in d.columns]
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for row in d.itertuples(index=False):
        out.append("| " + " | ".join(str(v) for v in row) + " |")
    return chr(10).join(out)

summary = {
    "agent": "a-hrrr-aws", "status": "development",
    "objects_status": status, "n_rows": len(df), "n_runs": int(df.run_utc.nunique()),
    "merge_counts": {str(k): int(v) for k, v in merge_counts.items()}, "n_compared": len(mm),
    "overall": overall.to_dict(), "runmax_f01_f12": runmax,
    "f00_after_f01_runs": f00_after_f01, "f00_after_f12_runs": f00_after_f12, "n_runs_obj": int(piv.shape[0]),
    "objects_lm_over_3h": over3h, "max_run_delay_min_quantiles": max_delay.quantile([.5, .95, 1]).round(1).to_dict(),
    "singleruns_plus3h_not_earlier_than_aws_lm_frac": sr_avail_ok,
}
with open(os.path.join(RES, "compare_tables.md"), "w") as f:
    f.write("## Overall (Single-Runs minus AWS, degF)\n" + md(overall.to_frame().T, index=False) + "\n\n")
    f.write("## By lead (fh)\n" + md(by_lead) + "\n\n## By station\n" + md(by_station) + "\n\n")
    f.write("## By cycle\n" + md(by_cyc) + "\n\n## By month\n" + md(by_month) + "\n\n")
    f.write("## Run max f01-f12\n" + json.dumps(runmax) + "\n\n## Worst 15\n" + md(worst, index=False) + "\n\n")
    f.write("## Grid points\n" + md(grid_off) + "\n\n## AWS availability delay (min after cycle) by cycle x fh\n" + md(avail) + "\n")
json.dump(summary, open(os.path.join(RES, "compare_summary.json"), "w"), indent=1, default=str)

# MANIFEST
def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()
files = []
for p in sorted(glob.glob(os.path.join(OUT, "*.parquet")) + glob.glob(os.path.join(OUT, "*.json")) +
                glob.glob(os.path.join(OUT, "parts", "*.jsonl"))):
    if p.endswith("MANIFEST.json"):
        continue
    files.append({"path": os.path.relpath(p, OUT), "bytes": os.path.getsize(p), "sha256": sha(p)})
cov = df.groupby(["station", df.run_utc.dt.strftime("%Y-%m-%d")]).agg(n_msgs=("fh", "size")).reset_index()
coverage = {st: {"days_with_any": int((g.n_msgs > 0).sum()), "days_full_26": int((g.n_msgs == 26).sum())}
            for st, g in cov.groupby("station")}
manifest = {
    "source": "NOAA HRRR on AWS Open Data, bucket noaa-hrrr-bdp-pds (anonymous HTTPS, Range GET of the TMP:2 m above ground message located via the .idx)",
    "agent": "a-hrrr-aws", "status": "development", "created_local": dt.datetime.now().isoformat(timespec="seconds"),
    "url_pattern": "https://noaa-hrrr-bdp-pds.s3.amazonaws.com/hrrr.YYYYMMDD/conus/hrrr.tHHz.wrfsfcfFF.grib2 (+ .idx)",
    "window": {"run_dates": ["2026-07-25", "2026-09-29"], "cycles_utc": [12, 18], "forecast_hours": "f00-f12"},
    "variable": "TMP 2 m above ground (K in GRIB; tmp2m_f = (K-273.15)*9/5+32)",
    "grid_point": "nearest HRRR 3 km Lambert grid point (haversine) to C:\\swarm\\stations.json lat/lon; see nearest_points.json (all <= 1.8 km)",
    "decode": "grid lat/lon from cfgrib (backend_kwargs indexpath '') on 2026-07-25 12Z f01; per-message values via eccodes codes_new_from_message in memory (no raw staged on disk); asserts shortName/level 2/dataDate/dataTime/endStep/grid size",
    "availability_basis": "available_utc = S3 LastModified of the .grib2 object itself (per object, from ListObjectsV2); f00 is often written after f01, never assume monotone in fh. Per-object grib_last_modified and idx_last_modified kept in objects (parts/*.jsonl).",
    "transfer_bytes": 2193074324, "transfer_cap_bytes": 3000000000,
    "objects_status": status,
    "coverage_per_station": coverage,
    "coverage_note": "26 messages per station-day = 2 cycles x 13 fh; per-station-day counts in hrrr_aws_tmp2m.parquet",
    "files": files,
    "code": ["C:\\pt\\swarm\\tools\\research\\model_parity\\a-hrrr-aws_fetch.py", "C:\\pt\\swarm\\tools\\research\\model_parity\\a-hrrr-aws_tidy_compare.py"],
}
json.dump(manifest, open(os.path.join(OUT, "MANIFEST.json"), "w"), indent=1)
print(json.dumps(summary, indent=1, default=str))
print(open(os.path.join(RES, "compare_tables.md")).read())
