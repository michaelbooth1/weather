"""ECMWF ENS open data, 2 m temperature at the US settlement stations (screen F5/G2): fetch, decode, reduce.

Research only. **Decoder: eccodes, installed only in the separate research venv**
(``C:\\venvs\\research-ecmwf``); it is imported lazily inside ``decode_points`` and nothing in the project
imports this module at load time. The project venv never needs eccodes: the scorecard candidate reads
only the reduced station-point table written here.

Source: the public Google Cloud mirror of ECMWF open data (``ecmwf-open-data``; same files as the AWS
``ecmwf-forecasts`` mirror, which throttled range requests; CC BY 4.0, no account),
``<YYYYMMDD>/00z/ifs/0p25/enfo/<run>-<step>h-enfo-ef.grib2`` plus its JSON-lines ``.index``. Only the 51
``2t`` messages (control + 50 perturbed) of steps 18, 21, 24 (target = run date) and 42, 45, 48 (target =
run date + 1) of the 00Z run are range-requested; each range is hashed (sha256, in the receipt), decoded,
bilinearly interpolated to the stations and discarded. Output rows: run date, step, member, station, t2m
(K). Availability used by the screen: 00Z run at 09:00Z (open-data release is about 08Z).

CLI (research venv)::

    python -m weather.sources.free_screens.ecmwf_ens fetch [--root DIR]
    python -m weather.sources.free_screens.ecmwf_ens build [--root DIR]
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from weather.sources.free_screens import common

SOURCE = "ecmwf_ens"
SCHEMA = "free_screens_ecmwf_ens_points/1"
# The AWS mirror (ecmwf-forecasts) answered every range request with S3 SlowDown on 2026-10-24; the Google
# Cloud public mirror of the same open data serves identical paths without throttling.
BUCKET = "https://storage.googleapis.com/ecmwf-open-data"
STEPS = (18, 21, 24, 42, 45, 48)
AVAILABLE_AFTER_H = 9
GAP_TOLERANCE = 1_000_000


def run_dates():
    """00Z runs needed for target dates in Aug-Sep 2024 (from 08-15), Aug-Sep 2025 and 2026-07-31..09-29."""
    spans = ((date(2024, 8, 15), date(2024, 9, 30)), (date(2025, 7, 31), date(2025, 9, 30)),
             (date(2026, 7, 30), date(2026, 9, 29)))
    out = []
    for a, b in spans:
        d = a
        while d <= b:
            out.append(d)
            d += timedelta(days=1)
    return out


def clusters(fields, tol=GAP_TOLERANCE):
    """Group index entries (sorted by offset) into byte ranges whose gaps are <= tol."""
    fields = sorted(fields, key=lambda f: f["_offset"])
    groups = [[fields[0]]] if fields else []
    for f in fields[1:]:
        prev = groups[-1][-1]
        if f["_offset"] - (prev["_offset"] + prev["_length"]) <= tol:
            groups[-1].append(f)
        else:
            groups.append([f])
    return groups


def bilinear_weights(lat, lon, lat0=90.0, lon0=-180.0, step=0.25, ni=1440, nj=721):
    """Four (flat index, weight) pairs on a north-to-south, west-to-east regular grid starting at lon0."""
    x = ((lon - lon0) % 360.0) / step
    y = (lat0 - lat) / step
    i0, j0 = int(math.floor(x)), int(math.floor(y))
    fx, fy = x - i0, y - j0
    out = []
    for dj, wy in ((0, 1 - fy), (1, fy)):
        for di, wx in ((0, 1 - fx), (1, fx)):
            out.append((((j0 + dj) % nj) * ni + (i0 + di) % ni, wx * wy))
    return out


def decode_points(message, stations):
    """One GRIB2 message -> (meta, {icao: value}). eccodes is imported here only."""
    import eccodes

    h = eccodes.codes_new_from_message(message)
    try:
        keys = ("shortName", "number", "step", "dataDate", "dataTime", "Ni", "Nj",
                "latitudeOfFirstGridPointInDegrees", "longitudeOfFirstGridPointInDegrees", "iDirectionIncrementInDegrees")
        meta = {k: eccodes.codes_get(h, k) if eccodes.codes_is_defined(h, k) else None for k in keys}
        values = eccodes.codes_get_values(h)
    finally:
        eccodes.codes_release(h)
    lon0 = meta["longitudeOfFirstGridPointInDegrees"]
    lon0 = lon0 - 360.0 if lon0 > 180 else lon0
    out = {}
    for st in stations:
        w = bilinear_weights(st.lat, st.lon, meta["latitudeOfFirstGridPointInDegrees"], lon0,
                             meta["iDirectionIncrementInDegrees"], meta["Ni"], meta["Nj"])
        out[st.icao] = float(sum(values[i] * wt for i, wt in w))
    return meta, out


def fetch(root, runs=None, session=None, log=print):
    import requests

    session = session or requests.Session()
    src = Path(root) / SOURCE
    receipts = common.ReceiptLog(src)
    stations = common.us_stations()
    runs = runs or run_dates()
    for n, run in enumerate(runs, 1):
        if run > common.DEV_LAST:
            raise ValueError("refused: run after 2026-09-29")
        key = run.isoformat()
        if receipts.is_done(key):
            continue
        rows, pieces, errors = [], [], 0
        for step in STEPS:
            base = f"{BUCKET}/{run:%Y%m%d}/00z/ifs/0p25/enfo/{run:%Y%m%d}000000-{step}h-enfo-ef"
            idx = common.polite_get(session, base + ".index", spacing_s=0.5)
            if idx.status_code != 200:
                pieces.append({"step": step, "index_status": idx.status_code})
                errors += 1
                continue
            fields = [json.loads(x) for x in idx.text.splitlines() if x.strip()]
            t2 = [f for f in fields if f.get("param") == "2t"]
            pieces.append({"step": step, "index_sha256": common.sha256_bytes(idx.content), "fields_2t": len(t2)})
            for group in clusters(t2):
                a = group[0]["_offset"]
                b = group[-1]["_offset"] + group[-1]["_length"] - 1
                resp = None
                for attempt in range(5):
                    resp = session.get(base + ".grib2", headers={"Range": f"bytes={a}-{b}",
                                                                 "User-Agent": common.USER_AGENT}, timeout=300)
                    if resp.status_code == 206:
                        break
                    import time
                    time.sleep(30 * (attempt + 1))
                if resp is None or resp.status_code != 206:
                    errors += 1
                    pieces.append({"step": step, "range": [a, b], "status": getattr(resp, "status_code", None)})
                    continue
                blob = resp.content
                pieces.append({"step": step, "range": [a, b], "bytes": len(blob), "sha256": common.sha256_bytes(blob)})
                for f in group:
                    msg = blob[f["_offset"] - a:f["_offset"] - a + f["_length"]]
                    try:
                        meta, vals = decode_points(msg, stations)
                    except Exception as exc:  # recorded, never silently dropped
                        errors += 1
                        pieces.append({"step": step, "member": f.get("number"), "error": str(exc)[:200]})
                        continue
                    for icao, v in vals.items():
                        rows.append({"run": key, "step": int(meta["step"]), "member": int(meta["number"]),
                                     "station": icao, "t2m_k": v})
        body = json.dumps({"run": key, "rows": rows, "pieces": pieces}, sort_keys=True).encode("utf-8")
        rel, sha = common.store_gzip(src, f"{key}.json.gz", body)
        receipts.record({"key": key, "file": rel, "sha256": sha, "rows": len(rows), "errors": errors,
                         "bytes": int(sum(p.get("bytes", 0) for p in pieces)),
                         "requests": int(sum(1 for p in pieces if "range" in p) + len(STEPS)),
                         "fetched_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        log(f"[{n}/{len(runs)}] {key} rows={len(rows)} errors={errors}")


def build(root):
    """Reduce to one row per (run, station, target_date): member daily maxima of 2t over the run's steps
    for that target date, in F; written to ``points.parquet``."""
    import pandas as pd

    src = Path(root) / SOURCE
    done = {k: v for k, v in common.ReceiptLog(src).done.items() if len(k) == 10}   # run receipts only
    rows = []
    for row in sorted(done.values(), key=lambda r: r["key"]):
        rows += json.loads(gzip.decompress((src / row["file"]).read_bytes()))["rows"]
    frame = pd.DataFrame(rows)
    frame["run"] = pd.to_datetime(frame.run)
    frame["target_date"] = (frame.run + pd.to_timedelta((frame.step >= 36).astype(int), unit="D")).dt.strftime("%Y-%m-%d")
    frame["t2m_f"] = (frame.t2m_k - 273.15) * 1.8 + 32.0
    mx = frame.groupby(["run", "station", "target_date", "member"]).agg(tmax_f=("t2m_f", "max"),
                                                                       n_steps=("step", "size")).reset_index()
    mx = mx[mx.n_steps == 3]
    pts = mx.groupby(["run", "station", "target_date"]).agg(ens_mean_f=("tmax_f", "mean"),
                                                             ens_sd_f=("tmax_f", "std"),
                                                             n_members=("member", "size")).reset_index()
    pts["available_utc"] = (pts.run + pd.Timedelta(hours=AVAILABLE_AFTER_H)).dt.tz_localize("UTC")
    pts["run"] = pts.run.dt.strftime("%Y-%m-%d")
    if (pts.target_date > common.DEV_LAST.isoformat()).any():
        pts = pts[pts.target_date <= common.DEV_LAST.isoformat()]
    out = src / "points.parquet"
    pts.to_parquet(out, index=False)
    manifest = {"schema": SCHEMA, "file": out.name, "sha256": common.sha256_bytes(out.read_bytes()),
                "rows": int(len(pts)), "runs": len(done),
                "bytes_fetched": int(sum(r["bytes"] for r in done.values())),
                "requests": int(sum(r.get("requests", 0) for r in done.values())),
                "errors": int(sum(r["errors"] for r in done.values())),
                "member_rows": int(len(frame)), "steps": list(STEPS), "available_after_hours": AVAILABLE_AFTER_H,
                "first_run": pts.run.min(), "last_run": pts.run.max()}
    (src / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m weather.sources.free_screens.ecmwf_ens")
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
