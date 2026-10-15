"""A-IEM-1: METAR/SPECI acquisition from IEM asos.py (model-parity swarm v2).

One connection, sequential, >= 2 s between requests, backoff on 429/503/"Too many requests".
Raw CSV chunks are kept gzipped under raw/ (provenance); tidy parquet per station under metar/.
Window: 2026-07-25..2026-09-29 first (priority), then history 2024-05-01..2026-07-24.
Upper bound: local midnight ending 2026-09-29 per station; rows with local date >= 2026-09-30 dropped.
"""
import datetime as dt
import gzip
import hashlib
import io
import json
import os
import re
import sys
import time
from zoneinfo import ZoneInfo

import pandas as pd
import requests

ROOT = r"C:\swarm\data\iem"
RAW = os.path.join(ROOT, "raw_metar")
OUT = os.path.join(ROOT, "metar")
STOP = r"C:\swarm\STOP"
LOG = os.path.join(ROOT, "metar_acquire.log")
os.makedirs(RAW, exist_ok=True)
os.makedirs(OUT, exist_ok=True)

STATIONS = json.load(open(r"C:\swarm\stations.json"))["stations"]
URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
FIELDS = ["tmpf", "dwpf", "sknt", "drct", "gust", "skyc1", "skyc2", "skyc3", "skyc4",
          "skyl1", "skyl2", "skyl3", "skyl4", "metar"]
RTYPES = {3: "routine", 4: "speci"}
FREEZE = dt.datetime(2026, 10, 4, 4, 30)
LAST_LOCAL_DATE = dt.date(2026, 9, 29)


def log(msg):
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def chunks_for(icao):
    tz = ZoneInfo(STATIONS[icao]["tzname"])
    end_utc = dt.datetime(2026, 9, 30, tzinfo=tz).astimezone(dt.timezone.utc).replace(tzinfo=None)
    out = [("w", dt.datetime(2026, 7, 25), end_utc)]
    # history: quarterly chunks 2024-05-01 .. 2026-07-25 (exclusive)
    starts = [dt.datetime(2024, 5, 1)]
    y, m = 2024, 5
    while True:
        m += 3
        if m > 12:
            m -= 12
            y += 1
        d = dt.datetime(y, m, 1)
        if d >= dt.datetime(2026, 7, 25):
            break
        starts.append(d)
    bounds = starts + [dt.datetime(2026, 7, 25)]
    # newest history first
    hist = [("h", bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)][::-1]
    return out + hist


session = requests.Session()
last_req = [0.0]


def fetch(params):
    backoff = 60
    for attempt in range(8):
        wait = 2.0 - (time.time() - last_req[0])
        if wait > 0:
            time.sleep(wait)
        last_req[0] = time.time()
        try:
            r = session.get(URL, params=params, timeout=300)
        except requests.RequestException as e:
            log(f"  network error {e!r}; sleep {backoff}s")
            time.sleep(backoff)
            backoff = min(backoff * 2, 900)
            continue
        body = r.text
        if r.status_code in (429, 503) or "Too many requests" in body[:500]:
            log(f"  HTTP {r.status_code} throttle; sleep {backoff}s")
            time.sleep(backoff)
            backoff = min(backoff * 2, 900)
            continue
        if r.status_code != 200 or not body.startswith("station,valid"):
            log(f"  HTTP {r.status_code} unexpected body {body[:200]!r}; sleep 30s")
            time.sleep(30)
            continue
        return r.url, body
    raise RuntimeError("fetch failed after retries")


def main():
    order = sorted(STATIONS)
    plan = []
    # priority: window for every station first, then history newest-first
    for kind in ("w", "h"):
        for hist_idx in range(20):
            for icao in order:
                ch = [c for c in chunks_for(icao) if c[0] == kind]
                if hist_idx < len(ch):
                    for rt in RTYPES:
                        plan.append((icao, rt) + ch[hist_idx])
            if kind == "w":
                break
    log(f"plan: {len(plan)} requests")
    for i, (icao, rt, kind, s, e) in enumerate(plan):
        if os.path.exists(STOP):
            log("STOP file present; halting")
            return 2
        if dt.datetime.now() >= FREEZE:
            log("freeze time reached; halting")
            return 3
        fn = os.path.join(RAW, f"{icao}_{RTYPES[rt]}_{s:%Y%m%d%H}_{e:%Y%m%d%H}.csv.gz")
        if os.path.exists(fn):
            continue
        params = [("station", STATIONS[icao]["iem_id"])] + [("data", f) for f in FIELDS] + [
            ("sts", s.strftime("%Y-%m-%dT%H:%MZ")), ("ets", e.strftime("%Y-%m-%dT%H:%MZ")),
            ("tz", "Etc/UTC"), ("format", "onlycomma"), ("latlon", "no"), ("elev", "no"),
            ("missing", "M"), ("trace", "T"), ("direct", "no"), ("report_type", str(rt))]
        t0 = time.time()
        url, body = fetch(params)
        meta = {"url": url, "retrieved_utc": dt.datetime.now(dt.timezone.utc).isoformat()}
        tmp = fn + ".tmp"
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            f.write("# " + json.dumps(meta) + "\n")
            f.write(body)
        os.replace(tmp, fn)
        log(f"[{i+1}/{len(plan)}] {icao} {RTYPES[rt]} {s:%Y-%m-%d}..{e:%Y-%m-%d} rows={body.count(chr(10))-1} {time.time()-t0:.1f}s")
    log("all requests done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
