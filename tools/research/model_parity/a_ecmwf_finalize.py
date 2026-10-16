"""Build MANIFEST.json, values.parquet and per-station-day coverage for A-ECMWF."""
import json, os, hashlib, datetime as dt, collections
from email.utils import parsedate_to_datetime
import pandas as pd
OUT = r"C:\swarm\data\ecmwf"
ST = json.load(open(r"C:\swarm\stations.json"))["stations"]
rows = [json.loads(l) for l in open(os.path.join(OUT, "values.jsonl"))]
df = pd.DataFrame(rows).drop_duplicates(["date","cycle","step","param","station"], keep="last")
df["run_utc"] = pd.to_datetime(df["date"]) + pd.to_timedelta(df["cycle"], unit="h")
df["valid_utc"] = pd.to_datetime(df["valid_utc"].str.replace("Z",""))
df["grib_lm_utc"] = df["grib_last_modified"].map(lambda s: parsedate_to_datetime(s).replace(tzinfo=None))
df["index_lm_utc"] = df["index_last_modified"].map(lambda s: parsedate_to_datetime(s).replace(tzinfo=None))
df["usable"] = ~((df["param"] == "mx2t3") & (df["step"] == 0))
df["window_start_utc"] = df["valid_utc"] - pd.to_timedelta((df["param"] == "mx2t3").astype(int) * 3, unit="h")
df["available_utc_assumed"] = df["run_utc"] + pd.Timedelta(hours=8)
df["available_utc_measured"] = df[["grib_lm_utc","index_lm_utc"]].max(axis=1)
df["lm_lag_h"] = (df["available_utc_measured"] - df["run_utc"]).dt.total_seconds()/3600
df["available_utc_conservative"] = df[["available_utc_assumed","available_utc_measured"]].max(axis=1)
df.to_parquet(os.path.join(OUT, "values.parquet"), index=False)
runs = {}
for l in open(os.path.join(OUT, "runs.jsonl")):
    m = json.loads(l); runs[(m["date"], m["cycle"])] = m
ok = [k for k, m in runs.items() if m["status"] == "ok"]
# coverage: per station x local target day, count of 2t steps from runs available (+8h) by local midnight... simple:
# for each station-local day: number of runs whose 2t covers all 3-hourly valid times of that local day.
cov = collections.defaultdict(dict)
t2 = df[df.param == "2t"]
for s, v in ST.items():
    sub = t2[t2.station == s].copy()
    sub["local"] = sub["valid_utc"].dt.tz_localize("UTC").dt.tz_convert(v["tzname"])
    sub["ldate"] = sub["local"].dt.date.astype(str)
    for (ld, run), g in sub.groupby(["ldate", "run_utc"]):
        cov[s].setdefault(ld, {"runs_with_full_day": 0, "runs_partial": 0})
        key = "runs_with_full_day" if len(g) >= 8 else "runs_partial"
        cov[s][ld][key] += 1
lag = df.groupby("cycle")["lm_lag_h"].describe().to_dict()
files = []
for fn in ("values.jsonl", "values.parquet", "runs.jsonl"):
    p = os.path.join(OUT, fn); files.append({"file": fn, "bytes": os.path.getsize(p),
        "sha256": hashlib.sha256(open(p, "rb").read()).hexdigest()})
man = {
 "source": "ECMWF IFS open data, AWS bucket ecmwf-forecasts (anonymous HTTPS, Range GETs via .index only; no whole files)",
 "url_pattern": "https://ecmwf-forecasts.s3.amazonaws.com/YYYYMMDD/HHz/ifs/0p25/oper/YYYYMMDDHH0000-<step>h-oper-fc.{index,grib2}",
 "stream": "oper (no scda directory exists in this window; 00z/12z only)", "grid": "0.25 deg regular lat-lon, 721x1440, lat 90..-90, lon -180..179.75",
 "window_run_dates": "2026-07-25..2026-09-29", "cycles": [0, 12], "steps_h": list(range(0, 49, 3)),
 "params": {"2t": "2 m temperature, instantaneous, steps 0..48 every 3 h",
            "mx2t3": "max 2 m temperature over the preceding 3 h (stepRange s-3..s), steps 3..48. The step-0 file also carries an mx2t3 message (stepRange '0-3') whose values are all 0 K: a placeholder, flagged usable=False; never use it."},
 "columns": "date,cycle,step,stepRange,param,station,valid_utc (window end for mx2t3),window_start_utc,grid_lat,grid_lon,nearest_K,nearest_F,bilinear_K,usable,index/grib_last_modified,msg_sha256,run_utc,available_utc_assumed(+8h),available_utc_measured(LastModified),lm_lag_h,available_utc_conservative",
 "extraction": "nearest grid point (index = j*1440+i, verified against eccodes codes_grib_find_nearest on the first message of every run) plus bilinear value; units K, nearest_F derived",
 "raw_policy": "GRIB2 messages decoded in memory, never written to disk; per-message sha256 recorded in values.jsonl and runs.jsonl",
 "availability_basis": "run time + 8 h assumed (DESIGN); measured per-object S3 Last-Modified of the .index and the grib2 (Range GET response) recorded per row; available_utc_conservative = max(assumed, measured). A candidate must use available_utc_conservative <= snapshot t.",
 "last_modified_lag_hours_by_cycle": lag,
 "undersampling": "Instantaneous 2t is 3-hourly: the max over 3-hourly 2t samples under-samples the daily (hourly-row) max, biased low, worst when the peak falls between synoptic hours (e.g. 15/18/21Z vs a 20Z local peak). mx2t3 (3-h window max) covers the gaps but is a model-internal continuous max, not an hourly-row max, so it can exceed an hourly-row settlement max; it can also be marginally below 2t at the window end (observed 0.05 K at KATL 2026-07-25 00z step 18). Neither matches the hourly-row settlement shape exactly.",
 "runs_total_expected": 134, "runs_ok": len(ok), "runs_failed": [f"{k[0]} {k[1]:02d}z: {m['status']}" for k, m in sorted(runs.items()) if m["status"] != "ok"],
 "runs_missing": sorted(f"{(dt.date(2026,7,25)+dt.timedelta(days=d)).strftime('%Y%m%d')} {c:02d}z" for d in range(67) for c in (0,12)
                        if ((dt.date(2026,7,25)+dt.timedelta(days=d)).strftime('%Y%m%d'), c) not in runs),
 "rows": len(df), "files": files, "coverage_per_station_local_day_2t": cov,
 "frozen_local": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "label": "development",
}
json.dump(man, open(os.path.join(OUT, "MANIFEST.json"), "w"), indent=1, default=str)
print(len(df), len(ok), man["runs_failed"], man["runs_missing"][:5], lag)
