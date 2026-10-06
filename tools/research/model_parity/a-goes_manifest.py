"""Build C:\\swarm\\data\\goes\\MANIFEST.json from the A-GOES scene/row logs (development data)."""
import collections
import datetime as dt
import hashlib
import json
import os

OUT = r"C:\swarm\data\goes"
sc = [json.loads(l) for l in open(os.path.join(OUT, "goes_scenes.jsonl"))]
rows = [json.loads(l) for l in open(os.path.join(OUT, "goes_acm_station_hour.jsonl"))]
stations = json.load(open(r"C:\swarm\stations.json"))["stations"]
WEST = {"KSEA", "KSFO", "KLAX"}

# de-dup (resume safety)
seen = {}
for s in sc:
    seen[s["slot"]] = s
sc = list(seen.values())
rseen = {}
for r in rows:
    rseen[(r["station"], r["hour_utc"], r["target_local_date"])] = r
rows = list(rseen.values())

status = collections.Counter(s["status"] for s in sc)
dates = [dt.date(2026, 7, 25) + dt.timedelta(d) for d in range(67)]
cov = {}
for st in sorted(stations):
    per = {}
    for d in dates:
        rr = [r for r in rows if r["station"] == st and r["target_local_date"] == d.isoformat()]
        per[d.isoformat()] = {"hours": len(rr), "hours_valid": sum(1 for r in rr if r["n_valid_3x3"] > 0)}
    cov[st] = per
lat = []
for s in sc:
    if s["status"] == "ok":
        st_ = dt.datetime.fromisoformat(s["scene_start_utc"].rstrip("Z"))
        av = dt.datetime.fromisoformat(s["available_utc"].rstrip("Z"))
        lat.append((av - st_).total_seconds() / 60)
lat.sort()


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


files = []
for fn in ["goes_acm_station_hour.jsonl", "goes_scenes.jsonl", "a_goes_fetch.py", "a_goes_manifest.py"]:
    p = os.path.join(OUT, fn)
    files.append({"file": fn, "bytes": os.path.getsize(p), "sha256": sha(p)})

man = {
    "source": "A-GOES: NOAA GOES-R ABI L2 Clear Sky Mask, CONUS sector (ABI-L2-ACMC), anonymous AWS Open Data",
    "agent": "a-goes",
    "built_local": dt.datetime.now().isoformat(timespec="seconds"),
    "label": "development",
    "buckets": {"noaa-goes19": sorted(s for s in stations if s not in WEST), "noaa-goes18": sorted(WEST)},
    "url_pattern": "https://<bucket>.s3.amazonaws.com/ABI-L2-ACMC/YYYY/DOY/HH/OR_ABI-L2-ACMC-M6_G1x_s..._e..._c....nc",
    "window": {"target_local_dates": "2026-07-25..2026-09-29 (08-01.. fetched first)",
               "hours_utc": "11Z..23Z on D and 00Z..02Z on D+1 (first scene of each hour)",
               "excluded": "slots with UTC hour >= 2026-09-30T00Z (09-29 00-02Z of 09-30) never requested (COMMON date boundary)"},
    "extraction": "nearest fixed-grid pixel (2 km) to station lat/lon (stations.json) via GOES-R PUG projection; 3x3 window; "
                  "cloud_frac_3x3 = share of valid pixels with BCM==1 (BCM 0 clear/1 cloudy; other values invalid); also BCM/ACM centre, "
                  "ACM mean (0 clear,1 prob clear,2 prob cloudy,3 cloudy), DQF==0 count. No parallax correction (cloud-top displacement "
                  "of a few km poleward/away from sub-satellite point is not corrected). Geolocation check: pixel centres within 0.02 deg of stations.",
    "availability_basis": "available_utc = max(scene end time from filename _e stamp, S3 LastModified from ListObjectsV2). "
                          "Point-in-time use: value enters a snapshot t only if available_utc <= t.",
    "availability_minutes_after_scan_start": {"n": len(lat), "min": lat[0] if lat else None,
                                              "median": lat[len(lat) // 2] if lat else None, "max": lat[-1] if lat else None},
    "raw_handling": "one object at a time, held in memory only (never written to disk), sha256 recorded per object, discarded after extract",
    "scene_status_counts": dict(status),
    "scenes_ok": status.get("ok", 0),
    "station_hour_rows": len(rows),
    "files": files,
    "coverage_per_station_day": cov,
}
json.dump(man, open(os.path.join(OUT, "MANIFEST.json"), "w"), indent=1)
print(json.dumps({k: man[k] for k in ["scene_status_counts", "station_hour_rows", "availability_minutes_after_scan_start"]}))
