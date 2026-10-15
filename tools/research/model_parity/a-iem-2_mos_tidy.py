"""A-IEM-2: tidy IEM MOS raw CSVs -> one parquet per model with an availability column; write MANIFEST.json.

Development data. Availability basis per model (see MANIFEST 'availability_basis'):
  NBS/NBE: measured per-cycle S3 LastModified of blend_nbstx/blend_nbetx (noaa-nbm-grib2-pds); no listing -> NaT (excluded).
  GFS (MAV): runtime + 4h30 (NCO prodstat: 'GFS MOS FORECAST' completes ~04:12-04:15Z for 00Z, 16:13Z for 12Z).
  MEX: runtime + 5h00 (same GFS MOS job family; extended segment not separately timed; +45 min margin over MAV).
  NAM (MET): runtime + 4h00 (NCO prodstat NAM 12Z '84hr PRODUCTS' complete 14:45Z = +2h45; MOS runs after).
  LAV (GFS-LAMP): runtime + 1h00 (MDL: hourly product; issuance minute not published in sources found).
"""
import datetime as dt
import glob
import hashlib
import json
import os
import re
import time

import pandas as pd
import requests

BASE = r"C:\swarm\data\iem\mos"
RAW = os.path.join(BASE, "raw")
MODELS = ["NBS", "NBE", "GFS", "MEX", "NAM", "LAV"]
STATIONS = ["KATL", "KAUS", "KBKF", "KDAL", "KHOU", "KLAX", "KLGA", "KMIA", "KORD", "KSEA", "KSFO"]
LAG = {"GFS": pd.Timedelta("4h30min"), "MEX": pd.Timedelta("5h"), "NAM": pd.Timedelta("4h"), "LAV": pd.Timedelta("1h")}
CUT = pd.Timestamp("2026-09-30T00:00Z")
LM = os.path.join(BASE, "nbm_text_lastmodified.jsonl")


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def load_lm():
    lm = {}
    for line in open(LM, encoding="utf-8"):
        j = json.loads(line)
        lm[(j["date"], j["hour"])] = j["objects"]
    return lm


def list_cycle(d, h):
    p = f"blend.{d.replace('-', '')}/{h:02d}/text/"
    for a in range(6):
        r = requests.get("https://noaa-nbm-grib2-pds.s3.amazonaws.com/",
                         params={"list-type": "2", "prefix": p}, timeout=60)
        if r.status_code == 200:
            break
        time.sleep(5 * 2 ** a)
    objs = re.findall(r"<Key>([^<]+)</Key><LastModified>([^<]+)</LastModified>.*?<Size>([0-9]+)</Size>", r.text)
    rec = {"date": d, "hour": h, "status": r.status_code,
           "objects": {k.split("/")[-1]: {"last_modified": t, "size": int(s)} for k, t, s in objs}}
    with open(LM, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    time.sleep(0.2)
    return rec["objects"]


AVAIL = {
    "rule": "row usable at snapshot t only if available_utc <= t; available_utc NaT -> excluded",
    "NBS": "measured: S3 LastModified of blend.YYYYMMDD/HH/text/blend_nbstx.tHHz (anonymous ListObjectsV2; nbm_text_lastmodified.jsonl)",
    "NBE": "measured: S3 LastModified of blend_nbetx.tHHz (same listing)",
    "GFS": ("runtime + 4h30. Source: NCEP NCO production status "
            "https://www.nco.ncep.noaa.gov/pmb/nwprod/prodstat_new/prdst_00_UTC_GFS.html ('GFS MOS FORECAST' "
            "scheduled 04:15:00, completed 04:12:19 UTC for 00Z) and prdst_12_UTC_GFS.html (16:13:31 for 12Z), "
            "viewed 2026-10-04 (production schedule page, not weather data). +15 min margin for dissemination."),
    "MEX": ("runtime + 5h00. Assumption: extended GFS MOS comes from the same GFS MOS job family; no separate "
            "timing found; +45 min margin over MAV. Not measured."),
    "NAM": ("runtime + 4h00. Source: NCO prdst_12_UTC_NAM.html '84hr PRODUCTS' completed 14:45 UTC (+2h45); "
            "NAM MOS is not listed and runs after the 84 h products; +1h15 margin. Not measured."),
    "LAV": ("runtime + 1h00. Source: MDL LAMP pages (https://vlab.noaa.gov/web/mdl/lamp-data-availability) state "
            "hourly issuance but give no minute; conservative one-hour lag. Not measured."),
    "note": ("IEM does not expose its MOS ingest time; the IEM AFOS text archive holds no MAV/MEX/MET/LAV bulletins "
             "(KWNO product list for 2026-08-01 checked; retrieve.py pil=MAVATL/MEXATL/METATL/LAVATL -> not found), "
             "so no per-bulletin timestamp exists for those models. Refuters: re-run with +1 h/+2 h."),
}


def main():
    lm = load_lm()
    man = {
        "source": "IEM MOS archive, https://mesonet.agron.iastate.edu/cgi-bin/request/mos.py",
        "agent": "a-iem-2 (model-parity swarm v2); development data",
        "url_pattern": ("https://mesonet.agron.iastate.edu/cgi-bin/request/mos.py?station={ICAO}"
                        "&model={NBS|NBE|GFS|MEX|NAM|LAV}&sts={YYYY-MM-DDTHH:MMZ}&ets={YYYY-MM-DDTHH:MMZ}&format=csv"),
        "access": ("anonymous GET, one connection, >=2 s spacing, 60 s doubling back-off on 429/503/'Too many requests' "
                   "(1 throttle 429 seen at 00:38:30, recovered after 60 s); chunks overlap at boundaries, deduplicated"),
        "window": {"runtime_utc": ["2026-05-01T00:00Z", "2026-09-29T23:59Z"],
                   "evaluation_part": ["2026-07-25", "2026-09-29"],
                   "fitting_history_part": ["2026-05-01", "2026-07-24"],
                   "guard": "rows with runtime >= 2026-09-30T00Z dropped (count reported per model)"},
        "model_names": {"NBS": "NBM short-range text (IEM)", "NBE": "NBM extended text (IEM)",
                        "GFS": "GFS MOS short-range = MAV", "MEX": "GFS MOS extended = MEX/GFSX",
                        "NAM": "NAM MOS = MET", "LAV": "GFS-LAMP = LAV"},
        "units_and_fields": ("values as printed by IEM; tmp/dpt deg F; n_x (GFS/MEX/NAM) and txn (NBS/NBE) are 12-h "
                             "max/min ending at ftime (daytime max for ftime 00Z next day in US zones); LAV has hourly tmp, no max/min"),
        "availability_basis": AVAIL,
        "files": [], "models": {},
    }
    days = pd.date_range("2026-05-01", "2026-09-29").strftime("%Y-%m-%d")
    ev_days = pd.date_range("2026-07-25", "2026-09-29").strftime("%Y-%m-%d")
    for m in MODELS:
        fs = sorted(glob.glob(os.path.join(RAW, f"*_{m}_*.csv")))
        d = pd.concat([pd.read_csv(f, dtype=str) for f in fs], ignore_index=True)
        n_raw = len(d)
        d["runtime"] = pd.to_datetime(d["runtime"], format="ISO8601", utc=True)
        d["ftime"] = pd.to_datetime(d["ftime"], format="ISO8601", utc=True)
        d = d.drop_duplicates()
        # chunk-boundary overlaps: same key printed with different number formats ("66.0" vs "66"); keep first
        n_dup_key = int(d.duplicated(["station", "runtime", "ftime"]).sum())
        d = d.drop_duplicates(["station", "runtime", "ftime"])
        n_late = int((d["runtime"] >= CUT).sum())
        d = d[d["runtime"] < CUT].copy()
        if m in ("NBS", "NBE"):
            obj = "nbs" if m == "NBS" else "nbe"
            av = {}
            for rt in sorted(d["runtime"].unique()):
                rt = pd.Timestamp(rt)
                key = (rt.strftime("%Y-%m-%d"), rt.hour)
                objs = lm.get(key)
                if objs is None:
                    objs = list_cycle(*key)
                    lm[key] = objs
                o = objs.get(f"blend_{obj}tx.t{rt.hour:02d}z")
                av[rt] = pd.Timestamp(o["last_modified"]) if o else pd.NaT
            d["available_utc"] = d["runtime"].map(av)
            d["availability_basis"] = "s3_lastmodified"
        else:
            d["available_utc"] = d["runtime"] + LAG[m]
            d["availability_basis"] = f"runtime+{LAG[m]}"
        for c in ("tmp", "dpt", "n_x", "txn", "xnd", "tsd", "sky", "p06", "p12", "wsp", "wdr"):
            if c in d.columns:
                d[c] = pd.to_numeric(d[c], errors="coerce")
        d = d.sort_values(["station", "runtime", "ftime"]).reset_index(drop=True)
        out = os.path.join(BASE, f"mos_{m}.parquet")
        d.to_parquet(out, index=False)
        runs = d.drop_duplicates(["station", "runtime"]).copy()
        runs["lag_min"] = (runs["available_utc"] - runs["runtime"]).dt.total_seconds() / 60
        runs["rdate"] = runs["runtime"].dt.strftime("%Y-%m-%d")
        per_station = {}
        for st in STATIONS:
            sub = runs[runs["station"] == st]
            c = sub.groupby("rdate").size().reindex(days, fill_value=0)
            ce = c.reindex(ev_days)
            per_station[st] = {"eval_days_with_run": int((ce > 0).sum()), "eval_days": len(ev_days),
                               "eval_missing_runtime_dates": [k for k, v in ce.items() if v == 0],
                               "hist_days_with_run": int((c.reindex(days.difference(ev_days)) > 0).sum()),
                               "runs_per_runtime_date": {k: int(v) for k, v in c.items()}}
        hours = runs.groupby(runs["runtime"].dt.hour).size().to_dict()
        lq = {str(q): (None if runs["lag_min"].isna().all() else round(float(runs["lag_min"].quantile(q)), 1))
              for q in (0, 0.1, 0.5, 0.9, 1.0)}
        lag_by_hour = None
        if m in ("NBS", "NBE"):
            lag_by_hour = {int(h): round(float(v), 1) for h, v in runs.groupby(runs["runtime"].dt.hour)["lag_min"].median().items()}
        man["models"][m] = {"file": "iem\\mos\\" + os.path.basename(out), "rows_raw_incl_overlap": n_raw,
                            "rows": len(d), "boundary_key_duplicates_dropped": n_dup_key, "rows_dropped_runtime_ge_20260930": n_late, "runs": int(len(runs)),
                            "runtime_hour_counts_all_stations": {int(k): int(v) for k, v in hours.items()},
                            "runs_without_availability_excluded": int(runs["available_utc"].isna().sum()),
                            "lag_minutes_quantiles": lq, "median_lag_minutes_by_runtime_hour": lag_by_hour,
                            "columns": list(d.columns), "coverage": per_station}
        print(m, n_raw, len(d), n_late, len(runs), hours, lq, man["models"][m]["runs_without_availability_excluded"])
    files = sorted(glob.glob(os.path.join(BASE, "*.parquet"))) + [LM] + sorted(glob.glob(os.path.join(RAW, "*.csv")))
    for p in files:
        man["files"].append({"path": os.path.relpath(p, r"C:\swarm\data"), "bytes": os.path.getsize(p), "sha256": sha(p)})
    man["total_bytes"] = sum(f["bytes"] for f in man["files"])
    man["finalised_local"] = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}"
    man["fetch_log"] = "iem\\mos\\fetch.log"
    man["scripts"] = ["tools/research/model_parity/a-iem-2_mos_fetch.py",
                      "tools/research/model_parity/a-iem-2_nbm_text_lastmod.py",
                      "tools/research/model_parity/a-iem-2_mos_tidy.py"]
    with open(os.path.join(BASE, "MANIFEST.json"), "w", encoding="utf-8") as f:
        json.dump(man, f, indent=1)
    print("manifest written", len(man["files"]), man["total_bytes"])


if __name__ == "__main__":
    main()
