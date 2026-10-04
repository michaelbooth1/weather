"""A-SingleRuns tidy + MANIFEST (model-parity swarm v2, development only).

Flattens C:\\swarm\\data\\singleruns\\raw\\*.json into singleruns_long.parquet (one row per
station x model x run x valid hour, wide over variables) and writes MANIFEST.json with files,
bytes, sha256, URLs, window, availability basis and coverage per station x run-date x model.

Availability columns (rule 1: run time + stated publication delay):
  available_utc_design   = run + 3 h (HRRR) / + 6 h (NBM, ECMWF IFS)   [DESIGN section 3]
  available_utc_conservative = run + 3 h (HRRR) / + 6 h (NBM) / + 8 h (ECMWF IFS)
The conservative column is recommended for ECMWF: Open-Meteo's own meta.json showed the
ECMWF IFS run ingested ~6.1 h after initialisation tonight, i.e. +6 h is not conservative.
"""
from __future__ import annotations

import datetime as dt
import glob
import hashlib
import json
import os

import pandas as pd

ROOT = r"C:\swarm\data\singleruns"
RAW = os.path.join(ROOT, "raw")
VARS = ["temperature_2m", "cloud_cover", "precipitation", "wind_speed_10m"]
DELAY_DESIGN = {"ncep_hrrr_conus": 3, "ncep_nbm_conus": 6, "ecmwf_ifs": 6}
DELAY_CONS = {"ncep_hrrr_conus": 3, "ncep_nbm_conus": 6, "ecmwf_ifs": 8}
UNITS = {"temperature_2m": "degF", "cloud_cover": "%", "precipitation": "mm (preceding hour)",
         "wind_speed_10m": "km/h"}


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main() -> None:
    st = json.load(open(r"C:\swarm\stations.json"))["stations"]
    ids = sorted(st)
    reqs = [json.loads(l) for l in open(os.path.join(ROOT, "requests.jsonl"), encoding="utf-8")]
    req_by_file = {}
    for r in reqs:
        if r["status"] == 200 and "error_body" not in r:
            name = r["key"] if len(r["models"]) > 0 else r["key"]
            req_by_file.setdefault(r["key"], []).append(r)
    rows = []
    files = []
    for path in sorted(glob.glob(os.path.join(RAW, "*.json"))):
        body = json.load(open(path, encoding="utf-8"))
        if isinstance(body, dict):  # fallback marker
            continue
        key = os.path.basename(path)[:10]
        run = dt.datetime.strptime(key, "%Y%m%d%H").replace(tzinfo=dt.timezone.utc)
        rq = [r for r in req_by_file.get(key, []) if r["sha256"] == sha256(path)]
        files.append({"path": os.path.relpath(path, ROOT), "bytes": os.path.getsize(path),
                      "sha256": sha256(path), "run_utc": run.isoformat(),
                      "request_utc": rq[0]["request_utc"] if rq else None,
                      "models": rq[0]["models"] if rq else None, "url": rq[0]["url"] if rq else None})
        for sid, loc in zip(ids, body):
            h = loc["hourly"]
            times = pd.to_datetime(h["time"], utc=True)
            models = sorted({k.split("temperature_2m_")[1] for k in h if k.startswith("temperature_2m_")})
            for m in models:
                df = pd.DataFrame({"valid_utc": times})
                for v in VARS:
                    df[v] = pd.to_numeric(pd.Series(h.get(f"{v}_{m}", [None] * len(times))), errors="coerce")
                df["station"], df["model"], df["run_utc"] = sid, m, run
                df["grid_lat"], df["grid_lon"] = loc["latitude"], loc["longitude"]
                df["lead_h"] = ((df["valid_utc"] - run).dt.total_seconds() / 3600).astype(int)
                df["available_utc_design"] = run + pd.Timedelta(hours=DELAY_DESIGN[m])
                df["available_utc_conservative"] = run + pd.Timedelta(hours=DELAY_CONS[m])
                df["request_utc"] = files[-1]["request_utc"]
                rows.append(df)
    long = pd.concat(rows, ignore_index=True)
    long = long[["station", "model", "run_utc", "valid_utc", "lead_h", *VARS, "available_utc_design",
                 "available_utc_conservative", "request_utc", "grid_lat", "grid_lon"]]
    out = os.path.join(ROOT, "singleruns_long.parquet")
    long.to_parquet(out, index=False)

    # coverage per station x run-date x model
    long["run_date"] = long["run_utc"].dt.strftime("%Y-%m-%d")
    long["run_hour"] = long["run_utc"].dt.hour
    ok = long[long["temperature_2m"].notna()]
    cov = (ok.groupby(["station", "run_date", "model"])
             .agg(runs=("run_hour", lambda s: sorted(set(int(x) for x in s))),
                  n_temp=("temperature_2m", "size"))
             .reset_index())
    cov_records = cov.to_dict("records")
    # duplicate-run check: identical temperature series at overlapping valid times vs previous run
    dup = []
    for (sid, m), g in ok.groupby(["station", "model"]):
        piv = g.pivot_table(index="valid_utc", columns="run_utc", values="temperature_2m")
        cols = sorted(piv.columns)
        for a, b in zip(cols, cols[1:]):
            both = piv[[a, b]].dropna()
            if len(both) >= 6 and (both[a] == both[b]).all():
                dup.append({"station": sid, "model": m, "run_prev": str(a), "run": str(b), "n_overlap": len(both)})
    per_model_runs = (ok.groupby(["model", "run_hour"])["run_date"].nunique().reset_index()
                        .rename(columns={"run_date": "n_run_dates_with_data"}).to_dict("records"))
    lead_max = ok.groupby(["model", "run_hour"])["lead_h"].max().reset_index().to_dict("records")
    meta = [json.loads(l) for l in open(os.path.join(ROOT, "meta_samples.jsonl"), encoding="utf-8")]
    weighted = sum(r["weight"] for r in reqs)
    manifest = {
        "source": "Open-Meteo Single-Runs API (no key)", "endpoint": "https://single-runs-api.open-meteo.com/v1/forecast",
        "agent": "a-singleruns", "status": "development", "created_local": dt.datetime.now().isoformat(timespec="seconds"),
        "window_run_dates": ["2026-07-25", "2026-09-29"], "forecast_hours": 48,
        "note_valid_times": "runs issued <= 2026-09-29 contain valid times up to 2026-10-01 (allowed by DESIGN rule 5)",
        "models": {"ncep_hrrr_conus": "HRRR runs 06/09/12/15/18/21Z (09/15/21Z are 18 h runs)",
                   "ncep_nbm_conus": "NBM runs 00/06/12/18Z (lead 0 null)",
                   "ecmwf_ifs": "ECMWF IFS native-res runs 00/12Z"},
        "variables": UNITS,
        "extra_variables_note": "cloud_cover/precipitation/wind_speed_10m were also returned for NBM and ECMWF IFS (requests carry all models of a run hour together)",
        "request_design": "one request per run hour carrying all 11 locations and all models initialised at that hour; timezone=GMT; temperature_unit=fahrenheit",
        "availability_basis": {
            "rule": "run time + stated publication delay (DESIGN rule 1); Single-Runs exposes no per-run publication timestamp",
            "design_delay_h": DELAY_DESIGN, "conservative_delay_h": DELAY_CONS,
            "evidence": [
                "Open-Meteo meta.json (https://api.open-meteo.com/data/<model>/static/meta.json) sampled live during the pull: last_run_availability_time - last_run_initialisation_time per model (meta_samples.jsonl). Tonight's samples only; not a measurement of Aug-Sep ingestion.",
                "AWS LastModified (PREFLIGHT.md section 3): HRRR f00-f12 lands +52..67 min after cycle; ECMWF 00z oper lands ~+7.6 h; NBM text +40..96 min.",
                "Open-Meteo ingests from those upstream feeds, so its availability cannot precede them; the archived Single-Runs values may still differ from what the live API served at the time (Open-Meteo re-processing is not ruled out)."],
            "recommendation": "use available_utc_conservative (ECMWF +8 h); the DESIGN +6 h for ECMWF is not conservative (meta.json delay ~6.1 h tonight; AWS +7.6 h)."},
        "requests": {"n_http": len(reqs), "weighted_calls_counted": weighted,
                     "weighting": "locations x max(1, variables x models / 10) (conservative reading of the free-tier rule)",
                     "status_counts": pd.Series([r["status"] for r in reqs]).value_counts().to_dict(),
                     "log": "requests.jsonl (request_utc, run, models, status, sha256, url)"},
        "files": files + [{"path": "singleruns_long.parquet", "bytes": os.path.getsize(out), "sha256": sha256(out),
                           "rows": int(len(long))},
                          {"path": "requests.jsonl", "bytes": os.path.getsize(os.path.join(ROOT, "requests.jsonl")),
                           "sha256": sha256(os.path.join(ROOT, "requests.jsonl"))},
                          {"path": "meta_samples.jsonl", "bytes": os.path.getsize(os.path.join(ROOT, "meta_samples.jsonl")),
                           "sha256": sha256(os.path.join(ROOT, "meta_samples.jsonl"))}],
        "meta_samples": meta,
        "runs_with_data_by_model_hour": per_model_runs, "max_lead_by_model_hour": lead_max,
        "identical_consecutive_runs": dup,
        "coverage_station_rundate_model": cov_records,
    }
    with open(os.path.join(ROOT, "MANIFEST.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1, default=str)
    print(len(long), "rows;", len(files), "raw files;", "weighted", weighted, "; dup pairs", len(dup))
    print(pd.DataFrame(per_model_runs).to_string())
    print(pd.DataFrame(lead_max).to_string())


if __name__ == "__main__":
    main()
