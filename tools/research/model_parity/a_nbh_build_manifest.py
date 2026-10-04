"""Build MANIFEST.json + consolidated tidy parquet for NBH and NBS from ledger.jsonl and parts/."""
import datetime as dt
import glob
import hashlib
import json
import os

import pandas as pd

ROOT = r"C:\swarm\data"
LEDGER = os.path.join(ROOT, "nbh", "ledger.jsonl")
STATIONS = ["KATL", "KAUS", "KBKF", "KDAL", "KHOU", "KLAX", "KLGA", "KMIA", "KORD", "KSEA", "KSFO"]
START, END = dt.date(2026, 7, 25), dt.date(2026, 9, 29)
DATES = [str(START + dt.timedelta(days=d)) for d in range((END - START).days + 1)]


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


recs = {}
with open(LEDGER, encoding="utf-8") as f:
    for line in f:
        r = json.loads(line)
        recs[(r["product"], r["date"], r["cycle"])] = r  # last record wins

for p, prefix in (("nbh", "blend_nbhtx"), ("nbs", "blend_nbstx")):
    objs = [r for (pp, _, _), r in sorted(recs.items()) if pp == p]
    ok = [r for r in objs if r["status"] == "ok"]
    parts = sorted(glob.glob(os.path.join(ROOT, p, "parts", "*.parquet")))
    tidy = os.path.join(ROOT, p, f"{p}_tidy.parquet")
    if parts:
        df = pd.concat([pd.read_parquet(x) for x in parts], ignore_index=True)
        df = df.sort_values(["cycle_utc", "station", "field", "fhr"]).reset_index(drop=True)
        df["product"] = p.upper()
        lm = {(r["date"], r["cycle"]): r["s3_last_modified"] for r in ok}
        avail = pd.Series({k: pd.Timestamp(v) for k, v in lm.items()})
        keys = list(zip(df["cycle_utc"].dt.strftime("%Y-%m-%d"), df["cycle_utc"].dt.hour))
        df["available_utc"] = pd.to_datetime([lm.get(k) for k in keys], utc=True)
        df.to_parquet(tidy, index=False)
        nrows = len(df)
    else:
        nrows = 0
    # coverage per station x UTC cycle date: number of cycles (0..24) whose bulletin contained the station block
    cov = {}
    for st in STATIONS:
        cov[st] = {}
        for d in DATES:
            cycles = sorted(r["cycle"] for r in ok if r["date"] == d and st in r["stations_found"])
            cov[st][d] = {"n_cycles": len(cycles), "cycles_missing": sorted(set(range(24)) - set(cycles))}
    lags = []
    for r in ok:
        c = pd.Timestamp(f"{r['date']}T{r['cycle']:02d}:00:00Z")
        lags.append({"cycle": r["cycle"], "lag_min": (pd.Timestamp(r["s3_last_modified"]) - c).total_seconds() / 60})
    lagdf = pd.DataFrame(lags)
    lag_by_cycle = {}
    if len(lagdf):
        for c, g in lagdf.groupby("cycle"):
            lag_by_cycle[int(c)] = {"min": round(g.lag_min.min(), 1), "median": round(g.lag_min.median(), 1),
                                    "max": round(g.lag_min.max(), 1), "n": int(len(g))}
    manifest = {
        "source": f"NBM text bulletin {p.upper()} ({prefix}.tHHz)",
        "agent": "a-nbh (model-parity swarm v2); development data",
        "url_pattern": f"https://noaa-nbm-grib2-pds.s3.amazonaws.com/blend.YYYYMMDD/HH/text/{prefix}.tHHz",
        "access": "anonymous HTTPS GET, one raw object staged at a time, raw deleted after extraction",
        "window": {"cycle_dates_utc": [str(START), str(END)], "cycles": "00-23Z; fetch order 09Z..23Z then 00Z..08Z"},
        "availability_basis": "per-object S3 LastModified from ListObjectsV2 (s3_last_modified); also HTTP Last-Modified "
                              "header recorded. Column available_utc in the tidy parquet = that object's LastModified. "
                              "A row is usable at snapshot t only if available_utc <= t. Never a fixed lag.",
        "stations": STATIONS,
        "tidy_file": os.path.relpath(tidy, ROOT) if parts else None,
        "tidy_sha256": sha(tidy) if parts else None,
        "tidy_bytes": os.path.getsize(tidy) if parts else 0,
        "tidy_rows": nrows,
        "tidy_schema": {
            "station": "ICAO", "nbm_version": "header version string", "field": "bulletin row label (TMP, TXN, DPT, SKY, ...)",
            "fhr": "forecast hour (NBH: column k -> k+1 h; NBS: FHR row)", "value": "integer as printed (deg F for TMP/TXN/DPT; "
            "missing/blank cells omitted; CIG -88 = unlimited as printed)", "cycle_utc": "issuance cycle",
            "valid_utc": "cycle_utc + fhr (for NBS TXN/XND: end of the 12-h max/min period)", "product": "NBH or NBS",
            "available_utc": "S3 LastModified of the source object",
        },
        "counts": {"objects_ok": len(ok), "objects_missing": sum(r["status"] == "missing" for r in objs),
                   "objects_error": sum(r["status"] == "error" for r in objs), "expected": len(DATES) * 24,
                   "bytes_transferred": sum(r.get("bytes", 0) for r in ok)},
        "s3_lag_minutes_by_cycle": lag_by_cycle,
        "anomalies": [{"key": r["key"], "anomalies": r["anomalies"]} for r in ok if r.get("anomalies")],
        "objects": [{k: r.get(k) for k in ("key", "url", "status", "s3_last_modified", "http_last_modified", "etag",
                                            "bytes", "sha256", "stations_missing", "rows", "fetched_local")}
                    for r in objs],
        "coverage_per_station_utc_date": cov,
        "built_local": f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}",
    }
    with open(os.path.join(ROOT, p, "MANIFEST.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)
    print(p, manifest["counts"], "rows", nrows)
