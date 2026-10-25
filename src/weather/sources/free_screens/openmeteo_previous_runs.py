"""Open-Meteo Previous Runs (day-1 lag) per-model 2 m temperature at the US stations (lever L4 blend).

Free public API (``previous-runs-api.open-meteo.com``; no key; the owner accepted the non-commercial
licence 2026-08-05). ``temperature_2m_previous_day1`` is each valid hour's value from the model run
issued about 24-48 h earlier, so every hour of station-local day D comes from runs issued before D starts:
point in time for every snapshot on D. Output: one row per (station, model, local date) with the day's max
over the 24 local hours (F). Requests end on 2026-09-29.

CLI::

    python -m weather.sources.free_screens.openmeteo_previous_runs fetch [--root DIR]
    python -m weather.sources.free_screens.openmeteo_previous_runs build [--root DIR]
"""
from __future__ import annotations

import argparse
import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

from weather.sources.free_screens import common

SOURCE = "openmeteo_previous_runs"
SCHEMA = "free_screens_openmeteo_previous_runs/1"
URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
MODELS = ("gfs_seamless", "ecmwf_ifs025", "icon_seamless")
START, END = "2026-07-30", common.DEV_LAST.isoformat()


def params(st, model):
    return {"latitude": st.lat, "longitude": st.lon, "hourly": "temperature_2m_previous_day1", "models": model,
            "start_date": START, "end_date": END, "temperature_unit": "fahrenheit", "timezone": st.timezone}


def fetch(root, session=None, log=print):
    import requests

    session = session or requests.Session()
    src = Path(root) / SOURCE
    receipts = common.ReceiptLog(src)
    for st in common.us_stations():
        for model in MODELS:
            key = f"{st.icao}|{model}|{START}|{END}"
            if receipts.is_done(key):
                continue
            req = requests.Request("GET", URL, params=params(st, model)).prepare()
            resp = common.polite_get(session, req.url, spacing_s=2.0)
            body = resp.content
            n = 0
            if resp.status_code == 200:
                vals = json.loads(body).get("hourly", {}).get("temperature_2m_previous_day1") or []
                n = sum(v is not None for v in vals)
            rel, sha = common.store_gzip(src, f"{st.icao}_{model}.json.gz", body)
            receipts.record({"key": key, "file": rel, "sha256": sha, "status": resp.status_code, "bytes": len(body),
                             "rows": n, "station": st.icao, "model": model, "url": req.url,
                             "fetched_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")})
            log(f"{key} status={resp.status_code} values={n}")


def build(root):
    import pandas as pd

    src = Path(root) / SOURCE
    receipts = common.ReceiptLog(src)
    rows = []
    for r in receipts.done.values():
        if r["status"] != 200:
            continue
        hourly = json.loads(gzip.decompress((src / r["file"]).read_bytes()))["hourly"]
        frame = pd.DataFrame({"time": hourly["time"], "t": hourly["temperature_2m_previous_day1"]}).dropna()
        frame["local_date"] = frame.time.str[:10]
        day = frame.groupby("local_date").agg(high_f=("t", "max"), n_hours=("t", "size")).reset_index()
        day = day[(day.n_hours >= 20) & (day.local_date <= END)]
        for d, h in zip(day.local_date, day.high_f):
            rows.append({"station": r["station"], "model": r["model"], "local_date": d, "high_f": float(h)})
    out = src / "day1_highs.parquet"
    frame = pd.DataFrame(rows).sort_values(["station", "model", "local_date"]).reset_index(drop=True)
    frame.to_parquet(out, index=False)
    manifest = {"schema": SCHEMA, "file": out.name, "sha256": common.sha256_bytes(out.read_bytes()),
                "rows": int(len(frame)), "requests": len(receipts.done),
                "bytes_fetched": int(sum(r["bytes"] for r in receipts.done.values())),
                "models": list(MODELS), "span": [START, END],
                "fill": frame.groupby("model").size().to_dict()}
    (src / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m weather.sources.free_screens.openmeteo_previous_runs")
    parser.add_argument("command", choices=("fetch", "build"))
    parser.add_argument("--root", default=str(common.DEFAULT_ROOT))
    args = parser.parse_args(argv)
    if args.command == "fetch":
        fetch(args.root, log=lambda m: print(m, flush=True))
    else:
        print(json.dumps(build(args.root), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
