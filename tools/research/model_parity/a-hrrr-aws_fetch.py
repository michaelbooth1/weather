"""A-HRRR-AWS: byte-range fetch of HRRR TMP:2 m above ground (12Z/18Z, f00-f12) from
noaa-hrrr-bdp-pds (anonymous HTTPS), nearest grid point for the 11 swarm stations.

Development / acquisition only. Output: C:\\swarm\\data\\hrrr_aws\\parts\\YYYYMMDD_HH.jsonl (resumable).
Availability basis: per-object S3 LastModified of the .grib2 file (f00 can be written after f01).
One raw message staged per worker; temp file deleted after decode.
"""
from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import hashlib
import json
import os
import re
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET

import numpy as np
import requests

BUCKET = "https://noaa-hrrr-bdp-pds.s3.amazonaws.com"
OUT = r"C:\swarm\data\hrrr_aws"
PARTS = os.path.join(OUT, "parts")
STOPFILE = r"C:\swarm\STOP"
CAP_BYTES = 3_000_000_000
DEADLINE = dt.datetime(2026, 10, 4, 4, 25)  # local; manifests freeze 04:30
CYCLES = [12, 18]
FHS = list(range(0, 13))
START = dt.date(2026, 7, 25)
END = dt.date(2026, 9, 29)
NWORK = int(os.environ.get("HRRR_WORKERS", "6"))

_lock = threading.Lock()
_bytes = {"n": 0}
_session = threading.local()
NEAREST = {}  # station -> (flat index, lat, lon)
GRID_N = {"n": None}


def sess():
    if not hasattr(_session, "s"):
        _session.s = requests.Session()
    return _session.s


def get(url, headers=None, expect=(200,), tries=6):
    delay = 2.0
    for i in range(tries):
        try:
            r = sess().get(url, headers=headers or {}, timeout=60)
            if r.status_code in expect:
                return r
            if r.status_code in (403, 404):
                return r
        except requests.RequestException:
            pass
        time.sleep(delay)
        delay *= 2
    raise RuntimeError(f"failed {url}")


def list_lastmod(date, cyc):
    prefix = f"hrrr.{date:%Y%m%d}/conus/hrrr.t{cyc:02d}z.wrfsfcf"
    out = {}
    token = None
    while True:
        url = f"{BUCKET}/?list-type=2&prefix={prefix}"
        params = {}
        if token:
            params["continuation-token"] = token
        r = sess().get(url, params=params, timeout=60)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        ns = {"s": root.tag.split("}")[0].strip("{")}
        for c in root.findall("s:Contents", ns):
            out[c.find("s:Key", ns).text] = {
                "last_modified": c.find("s:LastModified", ns).text,
                "size": int(c.find("s:Size", ns).text),
            }
        if root.find("s:IsTruncated", ns).text == "true":
            token = root.find("s:NextContinuationToken", ns).text
        else:
            break
    with _lock:
        _bytes["n"] += len(r.content)
    return out


def find_range(idx_text):
    lines = idx_text.strip().splitlines()
    for i, ln in enumerate(lines):
        if ":TMP:2 m above ground:" in ln:
            start = int(ln.split(":")[1])
            end = int(lines[i + 1].split(":")[1]) - 1 if i + 1 < len(lines) else None
            return start, end, ln
    return None


def init_grid(stations):
    """Decode one message with cfgrib (indexpath '') to get lat/lon; compute nearest points."""
    import cfgrib  # noqa
    import xarray as xr

    d = dt.date(2026, 7, 25)
    base = f"{BUCKET}/hrrr.{d:%Y%m%d}/conus/hrrr.t12z.wrfsfcf01.grib2"
    idx = get(base + ".idx").text
    s, e, _ = find_range(idx)
    r = get(base, headers={"Range": f"bytes={s}-{e}"}, expect=(206,))
    assert r.content[:4] == b"GRIB"
    fd, path = tempfile.mkstemp(suffix=".grib2", dir=OUT)
    os.write(fd, r.content)
    os.close(fd)
    try:
        ds = xr.open_dataset(path, engine="cfgrib", backend_kwargs={"indexpath": ""})
        lat = ds.latitude.values
        lon = ds.longitude.values
        lon = np.where(lon > 180, lon - 360, lon)
        shape = lat.shape
        t2m_cfgrib = ds["t2m"].values
        ds.close()
    finally:
        os.remove(path)
    flat_lat, flat_lon = lat.ravel(), lon.ravel()
    for st, m in stations.items():
        p1, p2 = np.radians(m["lat"]), np.radians(flat_lat)
        dl = np.radians(flat_lon - m["lon"])
        a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
        dist = 2 * 6371.0 * np.arcsin(np.sqrt(a))
        k = int(np.argmin(dist))
        NEAREST[st] = (k, float(flat_lat[k]), float(flat_lon[k]), float(dist[k]))
    GRID_N["n"] = lat.size
    return shape, t2m_cfgrib.ravel()


def decode_values(blob):
    import eccodes

    gid = eccodes.codes_new_from_message(blob)
    try:
        vals = eccodes.codes_get_values(gid)
        meta = {
            "shortName": eccodes.codes_get(gid, "shortName"),
            "typeOfLevel": eccodes.codes_get(gid, "typeOfLevel"),
            "level": eccodes.codes_get(gid, "level"),
            "dataDate": eccodes.codes_get(gid, "dataDate"),
            "dataTime": eccodes.codes_get(gid, "dataTime"),
            "step": eccodes.codes_get(gid, "endStep"),
            "Nx": eccodes.codes_get(gid, "Nx"),
            "Ny": eccodes.codes_get(gid, "Ny"),
        }
    finally:
        eccodes.codes_release(gid)
    return vals, meta


def do_fh(date, cyc, fh, lastmods):
    key = f"hrrr.{date:%Y%m%d}/conus/hrrr.t{cyc:02d}z.wrfsfcf{fh:02d}.grib2"
    url = f"{BUCKET}/{key}"
    lm = lastmods.get(key)
    lm_idx = lastmods.get(key + ".idx")
    if lm is None:
        return {"status": "missing_object", "key": key}
    ri = get(url + ".idx")
    if ri.status_code != 200:
        return {"status": f"idx_http_{ri.status_code}", "key": key}
    rng = find_range(ri.text)
    if rng is None:
        return {"status": "no_tmp2m_in_idx", "key": key}
    s, e, line = rng
    hdr = {"Range": f"bytes={s}-{e}" if e is not None else f"bytes={s}-"}
    r = get(url, headers=hdr, expect=(206,))
    blob = r.content
    with _lock:
        _bytes["n"] += len(blob) + len(ri.content)
    if r.status_code != 206 or blob[:4] != b"GRIB" or blob[-4:] != b"7777":
        return {"status": f"bad_msg_{r.status_code}", "key": key}
    sha = hashlib.sha256(blob).hexdigest()
    vals, meta = decode_values(blob)  # in-memory; nothing staged on disk
    assert meta["shortName"] in ("2t", "t") and meta["level"] == 2, meta
    assert vals.size == GRID_N["n"], (vals.size, GRID_N["n"])
    assert meta["dataDate"] == int(f"{date:%Y%m%d}") and meta["dataTime"] == cyc * 100, meta
    assert meta["step"] == fh, meta
    run = dt.datetime(date.year, date.month, date.day, cyc, tzinfo=dt.timezone.utc)
    valid = run + dt.timedelta(hours=fh)
    rows = []
    for st, (k, glat, glon, dkm) in NEAREST.items():
        tk = float(vals[k])
        rows.append({
            "station": st, "run_utc": run.isoformat(), "fh": fh, "valid_utc": valid.isoformat(),
            "tmp2m_k": tk, "tmp2m_f": (tk - 273.15) * 9 / 5 + 32,
            "grid_lat": glat, "grid_lon": glon, "grid_dist_km": dkm,
        })
    return {
        "status": "ok", "key": key, "url": url, "range": hdr["Range"], "idx_line": line,
        "msg_bytes": len(blob), "msg_sha256": sha,
        "grib_last_modified": lm["last_modified"], "grib_size": lm["size"],
        "idx_last_modified": lm_idx["last_modified"] if lm_idx else None,
        "available_utc": lm["last_modified"],
        "rows": rows,
    }


def do_cycle(date, cyc):
    part = os.path.join(PARTS, f"{date:%Y%m%d}_{cyc:02d}.jsonl")
    if os.path.exists(part):
        return "skip"
    lastmods = list_lastmod(date, cyc)
    recs = []
    for fh in FHS:
        if os.path.exists(STOPFILE) or dt.datetime.now() > DEADLINE or _bytes["n"] > CAP_BYTES:
            return "halt"
        recs.append(do_fh(date, cyc, fh, lastmods))
    tmp = part + ".tmp"
    with open(tmp, "w") as f:
        for rec in recs:
            f.write(json.dumps(rec) + "\n")
    os.replace(tmp, part)
    return "done"


def main():
    os.makedirs(PARTS, exist_ok=True)
    stations = json.load(open(r"C:\swarm\stations.json"))["stations"]
    shape, _ = init_grid(stations)
    json.dump({st: {"flat_index": v[0], "grid_lat": v[1], "grid_lon": v[2], "dist_km": v[3]}
               for st, v in NEAREST.items()} | {"_grid_shape": list(shape)},
              open(os.path.join(OUT, "nearest_points.json"), "w"), indent=1)
    jobs = []
    d = START
    while d <= END:
        for c in CYCLES:
            jobs.append((d, c))
        d += dt.timedelta(days=1)
    t0 = time.time()
    done = 0
    with cf.ThreadPoolExecutor(NWORK) as ex:
        futs = {ex.submit(do_cycle, d, c): (d, c) for d, c in jobs}
        for fu in cf.as_completed(futs):
            d, c = futs[fu]
            try:
                st = fu.result()
            except Exception as exc:  # noqa
                st = f"error {exc!r}"
            done += 1
            print(f"{d} {c:02d}Z {st} bytes={_bytes['n']/1e6:.1f}MB n={done}/{len(jobs)} "
                  f"t={time.time()-t0:.0f}s", flush=True)
    print("TOTAL_BYTES", _bytes["n"], flush=True)


if __name__ == "__main__":
    main()
