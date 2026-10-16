"""A-GOES acquisition (model-parity swarm v2). Acquisition only, development data.

GOES-19 (east) ABI-L2-ACMC for eastern/central markets, GOES-18 (west) ABI-L2-ACMC for SEA/SFO/LAX.
First scene of each UTC hour 11Z..02Z per local target date window. Anonymous HTTPS, one object at a
time, held in memory only (never staged on disk), extracted then discarded.
Per station-hour: nearest pixel + 3x3 window clear-sky-mask cloud fraction (BCM==1 share of valid pixels).
Availability = max(scene end time, S3 LastModified). Hard stop at 04:00 local.
Never requests any object dated >= 2026-09-30 UTC.
"""
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET

import netCDF4
import numpy as np
import requests

OUT = r"C:\swarm\data\goes"
ROWS = os.path.join(OUT, "goes_acm_station_hour.jsonl")
SCENES = os.path.join(OUT, "goes_scenes.jsonl")
STOP_FILE = r"C:\swarm\STOP"
DEADLINE_LOCAL = dt.datetime(2026, 10, 4, 4, 0, 0)
CUTOFF_UTC = dt.datetime(2026, 9, 30, 0, 0, 0)  # never touch objects at/after this
WEST = {"KSEA", "KSFO", "KLAX"}
HOURS = list(range(11, 24)) + [0, 1, 2]  # 00-02Z belong to D+1 UTC
NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"

stations = json.load(open(r"C:\swarm\stations.json"))["stations"]
sess = requests.Session()


def log(msg):
    print(f"{dt.datetime.now():%H:%M:%S} {msg}", flush=True)


def get(url, **kw):
    delay = 5
    for attempt in range(6):
        try:
            r = sess.get(url, timeout=60, **kw)
            if r.status_code in (200, 206):
                return r
            if r.status_code == 404:
                return r
            log(f"HTTP {r.status_code} {url[:120]}; backoff {delay}s")
        except requests.RequestException as e:
            log(f"ERR {e!r}; backoff {delay}s")
        time.sleep(delay)
        delay *= 2
    raise RuntimeError(f"failed {url}")


def list_hour(bucket, t):
    prefix = f"ABI-L2-ACMC/{t:%Y}/{t.timetuple().tm_yday:03d}/{t:%H}/"
    url = f"https://{bucket}.s3.amazonaws.com/?list-type=2&prefix={prefix}"
    r = get(url)
    root = ET.fromstring(r.content)
    out = []
    for c in root.findall(f"{NS}Contents"):
        out.append((c.find(f"{NS}Key").text, c.find(f"{NS}LastModified").text, int(c.find(f"{NS}Size").text)))
    out.sort()
    return out


def parse_stamp(s):  # sYYYYDDDHHMMSSt
    base = dt.datetime.strptime(s[:13], "%Y%j%H%M%S")
    return base + dt.timedelta(milliseconds=100 * int(s[13]))


def latlon_to_xy(proj, lat, lon):
    req = proj.semi_major_axis
    rpol = proj.semi_minor_axis
    H = proj.perspective_point_height + req
    lon0 = np.deg2rad(proj.longitude_of_projection_origin)
    phi = np.deg2rad(lat)
    lam = np.deg2rad(lon)
    e2 = (req**2 - rpol**2) / req**2
    phic = np.arctan((rpol**2 / req**2) * np.tan(phi))
    rc = rpol / np.sqrt(1 - e2 * np.cos(phic) ** 2)
    sx = H - rc * np.cos(phic) * np.cos(lam - lon0)
    sy = -rc * np.cos(phic) * np.sin(lam - lon0)
    sz = rc * np.sin(phic)
    y = np.arctan(sz / sx)
    x = np.arcsin(-sy / np.sqrt(sx**2 + sy**2 + sz**2))
    return x, y


grid_cache = {}


def pixel_index(ds, sat, stids):
    xv = ds.variables["x"]
    yv = ds.variables["y"]
    x = xv[:].astype(np.float64)  # scaled to radians by netCDF4
    y = yv[:].astype(np.float64)
    key = (sat, len(x), len(y), round(float(x[0]), 7), round(float(y[0]), 7))
    if key in grid_cache:
        return grid_cache[key]
    proj = ds.variables["goes_imager_projection"]
    idx = {}
    for st in stids:
        sx, sy = latlon_to_xy(proj, stations[st]["lat"], stations[st]["lon"])
        i = int(np.argmin(np.abs(y - sy)))
        j = int(np.argmin(np.abs(x - sx)))
        idx[st] = (i, j, float(abs(x[j] - sx)), float(abs(y[i] - sy)))
    grid_cache[key] = idx
    log(f"grid {sat} {len(y)}x{len(x)} idx={ {k: v[:2] for k, v in idx.items()} }")
    return idx


def done_keys():
    s = set()
    if os.path.exists(SCENES):
        for line in open(SCENES):
            try:
                s.add(json.loads(line)["slot"])
            except Exception:
                pass
    return s


def main():
    east = [s for s in stations if s not in WEST]
    west = [s for s in stations if s in WEST]
    sats = [("noaa-goes19", "G19", east), ("noaa-goes18", "G18", west)]
    dates = [dt.date(2026, 8, 1) + dt.timedelta(d) for d in range(60)]  # 08-01..09-29
    dates += [dt.date(2026, 7, 25) + dt.timedelta(d) for d in range(7)]  # 07-25..07-31
    done = done_keys()
    log(f"resume: {len(done)} slots done")
    frows = open(ROWS, "a")
    fsc = open(SCENES, "a")
    n = 0
    for d in dates:
        for h in HOURS:
            t = dt.datetime(d.year, d.month, d.day, h) + (dt.timedelta(days=1) if h < 11 else dt.timedelta(0))
            for bucket, sat, stids in sats:
                slot = f"{sat}|{d.isoformat()}|{t:%Y-%m-%dT%HZ}"
                if slot in done:
                    continue
                if dt.datetime.now() >= DEADLINE_LOCAL:
                    log("DEADLINE 04:00 local reached; stopping")
                    return "deadline"
                if os.path.exists(STOP_FILE):
                    log("STOP file present; stopping")
                    return "stop"
                rec = {"slot": slot, "sat": sat, "bucket": bucket, "target_local_date": d.isoformat(),
                       "hour_utc": f"{t:%Y-%m-%dT%H:00Z}"}
                if t >= CUTOFF_UTC:
                    rec["status"] = "excluded_date_ge_20260930"
                    fsc.write(json.dumps(rec) + "\n"); fsc.flush()
                    continue
                objs = list_hour(bucket, t)
                if not objs:
                    rec["status"] = "missing_no_objects"
                    fsc.write(json.dumps(rec) + "\n"); fsc.flush()
                    continue
                key, lastmod, size = objs[0]
                m = re.search(r"_s(\d{14})_e(\d{14})_c(\d{14})", key)
                s_t, e_t, c_t = (parse_stamp(g) for g in m.groups())
                lm = dt.datetime.strptime(lastmod[:19], "%Y-%m-%dT%H:%M:%S")
                url = f"https://{bucket}.s3.amazonaws.com/{key}"
                r = get(url)
                raw = r.content
                sha = hashlib.sha256(raw).hexdigest()
                rec.update({"key": key, "url": url, "bytes": len(raw), "sha256": sha,
                            "scene_start_utc": s_t.isoformat() + "Z", "scene_end_utc": e_t.isoformat() + "Z",
                            "created_utc": c_t.isoformat() + "Z", "s3_last_modified_utc": lastmod,
                            "available_utc": max(e_t, lm).isoformat() + "Z"})
                try:
                    ds = netCDF4.Dataset("mem.nc", memory=raw)
                    idx = pixel_index(ds, sat, stids)
                    bcm = ds.variables["BCM"]; bcm.set_auto_mask(False); bcm.set_auto_scale(False)
                    acm = ds.variables["ACM"]; acm.set_auto_mask(False); acm.set_auto_scale(False)
                    dqf = ds.variables["DQF"]; dqf.set_auto_mask(False); dqf.set_auto_scale(False)
                    for st in stids:
                        i, j, dx, dy = idx[st]
                        b = np.asarray(bcm[i - 1:i + 2, j - 1:j + 2]).astype(int)
                        a = np.asarray(acm[i - 1:i + 2, j - 1:j + 2]).astype(int)
                        q = np.asarray(dqf[i - 1:i + 2, j - 1:j + 2]).astype(int)
                        valid = (b == 0) | (b == 1)
                        nv = int(valid.sum())
                        row = {"station": st, "sat": sat, "target_local_date": d.isoformat(),
                               "hour_utc": rec["hour_utc"], "scene_start_utc": rec["scene_start_utc"],
                               "scene_end_utc": rec["scene_end_utc"],
                               "s3_last_modified_utc": lastmod, "available_utc": rec["available_utc"],
                               "key": key, "pix_i": i, "pix_j": j,
                               "n_valid_3x3": nv,
                               "cloud_frac_3x3": (float(b[valid].mean()) if nv else None),
                               "bcm_center": int(b[1, 1]), "acm_center": int(a[1, 1]),
                               "acm_mean_3x3": (float(a[valid].mean()) if nv else None),
                               "dqf_good_3x3": int((q == 0).sum())}
                        frows.write(json.dumps(row) + "\n")
                    ds.close()
                    rec["status"] = "ok"
                except Exception as e:
                    rec["status"] = f"extract_error: {e!r}"
                    log(f"extract error {slot}: {e!r}")
                del raw
                frows.flush()
                fsc.write(json.dumps(rec) + "\n"); fsc.flush()
                n += 1
                if n % 50 == 0:
                    log(f"{n} scenes this run; at {slot}")
    return "complete"


if __name__ == "__main__":
    res = main()
    log(f"EXIT {res}")
    print(res)
