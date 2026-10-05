"""A-SingleRuns acquirer (model-parity swarm v2, development only).

Fetches Open-Meteo Single-Runs API (no key) for the 11 swarm stations, one request per
(run date, run hour) carrying every model initialised at that hour and all 11 locations.

Runs (UTC): 00Z NBM+ECMWF IFS; 06Z HRRR+NBM; 09Z HRRR; 12Z HRRR+NBM+ECMWF IFS; 15Z HRRR;
18Z HRRR+NBM; 21Z HRRR. Run dates 2026-07-25..2026-09-29, forecast_hours=48.

Writes raw JSON to C:\\swarm\\data\\singleruns\\raw\\<YYYYMMDDHH>.json and appends one line per
HTTP request to C:\\swarm\\data\\singleruns\\requests.jsonl. Resumable (skips runs with raw file).
Also samples https://api.open-meteo.com/data/<model>/static/meta.json every ~10 min into
meta_samples.jsonl as live publication-latency evidence.

Guards: stops on HTTP 429, on C:\\swarm\\STOP, at the deadline, or at the weighted budget.
Weighted calls are counted conservatively: locations x max(1, n_vars_total/10).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import sys
import time

import requests

ROOT = r"C:\swarm\data\singleruns"
RAW = os.path.join(ROOT, "raw")
REQLOG = os.path.join(ROOT, "requests.jsonl")
METALOG = os.path.join(ROOT, "meta_samples.jsonl")
STOP = r"C:\swarm\STOP"
URL = "https://single-runs-api.open-meteo.com/v1/forecast"
VARS = ["temperature_2m", "cloud_cover", "precipitation", "wind_speed_10m"]
HRRR, NBM, IFS = "ncep_hrrr_conus", "ncep_nbm_conus", "ecmwf_ifs"
RUN_MODELS = {0: [NBM, IFS], 6: [HRRR, NBM], 9: [HRRR], 12: [HRRR, NBM, IFS],
              15: [HRRR], 18: [HRRR, NBM], 21: [HRRR]}
ORDER = [12, 18, 0, 6, 9, 15, 21]  # priority (PREFLIGHT order, merged by run hour)
START, END = dt.date(2026, 7, 25), dt.date(2026, 9, 29)
BUDGET = int(os.environ.get("SR_BUDGET", "8500"))  # leaves room for P0/probe calls under 9,000
PRIOR_WEIGHTED = int(os.environ.get("SR_PRIOR", "70"))  # P0 ~20 + this agent's probe ~13 (rounded up)
SPACING_S = float(os.environ.get("SR_SPACING", "9"))
DEADLINE = dt.datetime.fromisoformat(os.environ.get("SR_DEADLINE", "2026-10-04T03:20:00"))


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def append(path: str, obj: dict) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, sort_keys=True) + "\n")


def weight(n_loc: int, n_models: int) -> float:
    return n_loc * max(1.0, len(VARS) * n_models / 10.0)


def sample_meta() -> None:
    for m in (HRRR, NBM, IFS):
        try:
            r = requests.get(f"https://api.open-meteo.com/data/{m}/static/meta.json", timeout=30)
            j = r.json()
            init, avail = j.get("last_run_initialisation_time"), j.get("last_run_availability_time")
            append(METALOG, {"model": m, "sampled_utc": now_utc(), "init": init, "avail": avail,
                             "modified": j.get("last_run_modification_time"),
                             "delay_min": round((avail - init) / 60, 1) if init and avail else None})
        except Exception as e:  # evidence only; never fatal
            append(METALOG, {"model": m, "sampled_utc": now_utc(), "error": str(e)[:200]})


def main() -> int:
    os.makedirs(RAW, exist_ok=True)
    st = json.load(open(r"C:\swarm\stations.json"))["stations"]
    ids = sorted(st)
    lat = ",".join(str(st[s]["lat"]) for s in ids)
    lon = ",".join(str(st[s]["lon"]) for s in ids)
    used = float(PRIOR_WEIGHTED)
    if os.path.exists(REQLOG):
        for line in open(REQLOG, encoding="utf-8"):
            used += json.loads(line).get("weight", 0)
    jobs = []
    for hh in ORDER:
        d = START
        while d <= END:
            jobs.append((d, hh))
            d += dt.timedelta(days=1)
    last_meta = 0.0
    n_done = 0
    for d, hh in jobs:
        key = f"{d:%Y%m%d}{hh:02d}"
        out = os.path.join(RAW, key + ".json")
        if os.path.exists(out):
            continue
        if os.path.exists(STOP):
            print("STOP file present; stopping", flush=True); return 2
        if dt.datetime.now() >= DEADLINE:
            print("deadline reached; stopping", flush=True); return 3
        if time.time() - last_meta > 600:
            sample_meta(); last_meta = time.time()
        groups = [RUN_MODELS[hh]]
        for attempt, models in enumerate(groups):
            w = weight(len(ids), len(models))
            if used + w > BUDGET:
                print(f"budget reached used={used:.0f}", flush=True); return 4
            run = f"{d:%Y-%m-%d}T{hh:02d}:00"
            params = dict(latitude=lat, longitude=lon, hourly=",".join(VARS), models=",".join(models),
                          run=run, forecast_hours=48, timezone="GMT", temperature_unit="fahrenheit")
            t0 = now_utc()
            try:
                r = requests.get(URL, params=params, timeout=90)
                status, body = r.status_code, r.content
            except Exception as e:
                status, body = -1, str(e).encode()
            used += w
            sha = hashlib.sha256(body).hexdigest()
            rec = {"key": key, "run": run, "models": models, "request_utc": t0, "status": status,
                   "bytes": len(body), "sha256": sha, "weight": w, "used_after": used,
                   "url": URL + "?" + requests.compat.urlencode(params)}
            ok = False
            if status == 200:
                try:
                    j = json.loads(body)
                    ok = isinstance(j, list) and len(j) == len(ids) and all("hourly" in x for x in j)
                except Exception:
                    ok = False
            if not ok:
                rec["error_body"] = body[:300].decode("utf-8", "replace")
            append(REQLOG, rec)
            if status == 429:
                print("HTTP 429: stopping (no retry)", flush=True); return 5
            if ok:
                fname = out if len(groups) == 1 else os.path.join(RAW, f"{key}_{'+'.join(models)}.json")
                with open(fname + ".tmp", "wb") as f:
                    f.write(body)
                os.replace(fname + ".tmp", fname)
            elif attempt == 0 and len(models) > 1:
                # combined request failed (e.g. one model's run missing): fall back per model
                groups.extend([[m] for m in models])
            time.sleep(SPACING_S)
        if len(groups) > 1 and not os.path.exists(out):
            # mark the run as attempted so a resume does not re-spend calls
            with open(out, "w") as f:
                json.dump({"fallback": True, "groups": groups}, f)
        n_done += 1
        if n_done % 20 == 0:
            print(f"{dt.datetime.now():%H:%M:%S} done={n_done} last={key} used={used:.0f}", flush=True)
    sample_meta()
    print(f"ALL DONE used={used:.0f}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
