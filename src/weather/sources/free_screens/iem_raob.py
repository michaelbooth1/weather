"""IEM RAOB soundings for the nearest upper-air site to each US market: fetch and parse.

Source role: supporting evidence, research only. Point in time: a 12Z sounding (balloon launched
about 11:00Z) is treated as available at 14:00Z, a conservative bound on public distribution; that
is before 13:00 local in every US market. Upper bound: no request ends after 2026-09-29T14:00Z.

CLI::

    python -m weather.sources.free_screens.iem_raob fetch [--root DIR] [--start 2024-01-01]
    python -m weather.sources.free_screens.iem_raob build [--root DIR]
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from weather.sources.free_screens import common

SOURCE = "iem_raob"
SCHEMA = "free_screens_iem_raob/1"
URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/raob.py?station={sid}&sts={sts}&ets={ets}"
END_UTC = datetime(2026, 9, 29, 14, 0, tzinfo=timezone.utc)
AVAILABLE_AFTER_H = 2   # 12Z sounding available at 14Z

# NWS upper-air sites near the US markets (lat, lon); IEM ids carry the K prefix.
RAOB_SITES = {
    "KFFC": (33.36, -84.57), "KFWD": (32.83, -97.30), "KCRP": (27.78, -97.51), "KDRT": (29.37, -100.92),
    "KILX": (40.15, -89.34), "KDVN": (41.61, -90.58), "KGRB": (44.48, -88.11), "KDNR": (39.77, -104.87),
    "KLCH": (30.12, -93.22), "KNKX": (32.85, -117.12), "KVBG": (34.75, -120.57), "KMFL": (25.75, -80.38),
    "KOKX": (40.87, -72.86), "KOAK": (37.73, -122.22), "KUIL": (47.93, -124.56), "KSLE": (44.92, -123.02),
}


def haversine_km(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def nearest_sites():
    """{market station icao: (raob site, distance km)}."""
    out = {}
    for st in common.us_stations():
        site = min(RAOB_SITES, key=lambda s: haversine_km((st.lat, st.lon), RAOB_SITES[s]))
        out[st.icao] = (site, round(haversine_km((st.lat, st.lon), RAOB_SITES[site]), 1))
    return out


def parse_csv(text):
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            rows.append((row["station"], row["validUTC"], float(row["pressure_mb"]),
                         float(row["height_m"]) if row.get("height_m") not in ("", None) else math.nan,
                         float(row["tmpc"]) if row.get("tmpc") not in ("", None) else math.nan))
        except (KeyError, ValueError):
            continue
    return rows


def fetch(root, start_utc, session=None, log=print):
    import requests

    session = session or requests.Session()
    src = Path(root) / SOURCE
    receipts = common.ReceiptLog(src)
    sites = sorted({v[0] for v in nearest_sites().values()})
    plan = [(s, a, b) for s in sites for a, b in common.month_windows(start_utc, END_UTC)]
    for i, (site, a, b) in enumerate(plan, 1):
        key = f"{site}|{common.utc_stamp(a)}|{common.utc_stamp(b)}"
        if receipts.is_done(key):
            continue
        url = URL.format(sid=site, sts=a.strftime("%Y-%m-%dT%H:%M:%SZ"), ets=b.strftime("%Y-%m-%dT%H:%M:%SZ"))
        resp = common.polite_get(session, url)
        rows = parse_csv(resp.content.decode("utf-8", "replace")) if resp.status_code == 200 else []
        rel, sha = common.store_gzip(src, f"{site}_{a:%Y%m%d%H}_{b:%Y%m%d%H}.csv.gz", resp.content)
        receipts.record({"key": key, "file": rel, "sha256": sha, "url": url, "status": resp.status_code,
                         "bytes": len(resp.content), "rows": len(rows), "station": site,
                         "start_utc": a.isoformat(), "end_utc": b.isoformat(),
                         "fetched_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        log(f"[{i}/{len(plan)}] {key} rows={len(rows)} bytes={len(resp.content)}")


def build(root):
    """All levels of every sounding -> ``levels.parquet`` (site, valid_utc, pressure_mb, height_m, tmpc)."""
    src = Path(root) / SOURCE
    receipts = common.ReceiptLog(src)
    frames = []
    for row in sorted(receipts.done.values(), key=lambda r: r["key"]):
        parsed = parse_csv(gzip.decompress((src / row["file"]).read_bytes()).decode("utf-8", "replace"))
        if parsed:
            frames.append(pd.DataFrame(parsed, columns=["site", "valid_utc", "pressure_mb", "height_m", "tmpc"]))
    frame = pd.concat(frames, ignore_index=True)
    frame["valid_utc"] = pd.to_datetime(frame.valid_utc, utc=True)
    frame = frame[frame.valid_utc <= END_UTC].drop_duplicates().sort_values(
        ["site", "valid_utc", "pressure_mb"], ascending=[True, True, False]).reset_index(drop=True)
    out = src / "levels.parquet"
    frame.to_parquet(out, index=False)
    soundings = frame.groupby(["site", "valid_utc"]).size()
    manifest = {"schema": SCHEMA, "file": out.name, "sha256": common.sha256_bytes(out.read_bytes()),
                "rows": int(len(frame)), "soundings": int(len(soundings)), "receipts": len(receipts.done),
                "bytes_fetched": int(sum(r["bytes"] for r in receipts.done.values())),
                "nearest_sites": nearest_sites(), "available_after_hours": AVAILABLE_AFTER_H,
                "per_site": {k: {"soundings": int(len(g.groupby("valid_utc"))),
                                 "first": g.valid_utc.min().isoformat(), "last": g.valid_utc.max().isoformat()}
                             for k, g in frame.groupby("site")}}
    (src / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m weather.sources.free_screens.iem_raob")
    parser.add_argument("command", choices=("fetch", "build", "sites"))
    parser.add_argument("--root", default=str(common.DEFAULT_ROOT))
    parser.add_argument("--start", default="2024-01-01")
    args = parser.parse_args(argv)
    if args.command == "fetch":
        fetch(args.root, datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc),
              log=lambda m: print(m, flush=True))
    elif args.command == "sites":
        print(json.dumps(nearest_sites(), indent=1))
    else:
        print(json.dumps(build(args.root), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
