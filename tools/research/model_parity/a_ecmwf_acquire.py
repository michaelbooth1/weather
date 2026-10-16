"""A-ECMWF acquirer (model-parity swarm v2). ECMWF IFS open data (ecmwf-forecasts, anonymous HTTPS).
00Z/12Z oper runs, steps 0..48 h every 3 h, params 2t (all steps) + mx2t3 (steps 3..48), fetched ONLY via
.index byte ranges. Each GRIB2 message is decoded in memory (eccodes) and never written to disk; the
message sha256 is recorded. Nearest 0.25-deg grid point + bilinear value per station. Development data."""
import os, sys, json, time, hashlib, threading, datetime as dt
from concurrent.futures import ThreadPoolExecutor
import requests, numpy as np, eccodes

OUT = r"C:\swarm\data\ecmwf"
B = "https://ecmwf-forecasts.s3.amazonaws.com/"
STOP = r"C:\swarm\STOP"
FREEZE = dt.datetime(2026, 10, 4, 4, 30)
D0, D1 = dt.date(2026, 7, 25), dt.date(2026, 9, 29)
STEPS = list(range(0, 49, 3))
PARAMS = ("2t", "mx2t3")
ST = json.load(open(r"C:\swarm\stations.json"))["stations"]
PROG = os.path.join(OUT, "values.jsonl")       # one line per (run, step, param, station)
RUNLOG = os.path.join(OUT, "runs.jsonl")       # one line per completed/failed run
LOG = os.path.join(OUT, "acquire.log")
lock = threading.Lock()
stats = {"bytes": 0, "requests": 0, "retries": 0}

def log(msg):
    with lock:
        with open(LOG, "a") as f: f.write(f"{dt.datetime.now():%H:%M:%S} {msg}\n")

def grid_ij(lat, lon):
    j = int(round((90.0 - lat) / 0.25)); i = int(round(((lon + 180.0) % 360.0) / 0.25)) % 1440
    return j, i

NEAR = {s: grid_ij(v["lat"], v["lon"]) for s, v in ST.items()}

def bilinear(vals, lat, lon):
    y = (90.0 - lat) / 0.25; x = ((lon + 180.0) % 360.0) / 0.25
    j0, i0 = int(np.floor(y)), int(np.floor(x)); fy, fx = y - j0, x - i0
    g = vals.reshape(721, 1440)
    i1 = (i0 + 1) % 1440
    return float((1-fy)*((1-fx)*g[j0,i0] + fx*g[j0,i1]) + fy*((1-fx)*g[j0+1,i0] + fx*g[j0+1,i1]))

S = requests.Session()
def get(url, rng=None, expect_grib=False):
    delay = 5
    for attempt in range(8):
        hdr = {"Range": f"bytes={rng[0]}-{rng[1]}"} if rng else {}
        try:
            r = S.get(url, headers=hdr, timeout=90)
            with lock: stats["requests"] += 1; stats["bytes"] += len(r.content)
            ok = (r.status_code == 206 and r.content[:4] == b"GRIB" and len(r.content) == rng[1]-rng[0]+1) if expect_grib \
                 else r.status_code == 200
            if ok: return r
            if r.status_code == 404: return None
            log(f"retry {r.status_code} {url} {rng}")
        except Exception as ex:
            log(f"retry exc {ex!r} {url}")
        with lock: stats["retries"] += 1
        time.sleep(delay); delay = min(delay*2, 120)
    raise RuntimeError(f"failed {url} {rng}")

def do_run(day, cyc):
    ymd = day.strftime("%Y%m%d"); rows = []; meta = {"date": ymd, "cycle": cyc, "steps": {}}
    first_check = True
    for step in STEPS:
        base = f"{ymd}/{cyc:02d}z/ifs/0p25/oper/{ymd}{cyc:02d}0000-{step}h-oper-fc"
        ir = get(B + base + ".index")
        if ir is None:
            meta["steps"][step] = "missing_index"; continue
        idx = [json.loads(l) for l in ir.text.splitlines() if l.strip()]
        smeta = {"index_last_modified": ir.headers.get("Last-Modified"), "msgs": {}}
        for p in PARAMS:
            ent = [e for e in idx if e["param"] == p and e.get("levtype") == "sfc"]
            if not ent:
                smeta["msgs"][p] = "absent"; continue
            e = ent[0]; rng = (e["_offset"], e["_offset"] + e["_length"] - 1)
            r = get(B + base + ".grib2", rng, expect_grib=True)
            sha = hashlib.sha256(r.content).hexdigest()
            g = eccodes.codes_new_from_message(r.content)
            try:
                sn = eccodes.codes_get(g, "shortName"); dd = eccodes.codes_get(g, "dataDate"); tt = eccodes.codes_get(g, "dataTime")
                sr = eccodes.codes_get(g, "stepRange")
                assert sn == p and str(dd) == ymd and int(tt) == cyc*100, (sn, dd, tt)
                assert eccodes.codes_get(g, "Ni") == 1440 and eccodes.codes_get(g, "Nj") == 721
                assert eccodes.codes_get(g, "latitudeOfFirstGridPointInDegrees") == 90.0
                assert eccodes.codes_get(g, "longitudeOfFirstGridPointInDegrees") == 180.0
                vals = eccodes.codes_get_values(g)
                if first_check:
                    for s, v in ST.items():
                        n = eccodes.codes_grib_find_nearest(g, v["lat"], v["lon"])[0]
                        j, i = NEAR[s]; assert n["index"] == j*1440 + i, (s, n, j, i)
                    first_check = False
            finally:
                eccodes.codes_release(g)
            smeta["msgs"][p] = {"offset": e["_offset"], "length": e["_length"], "sha256": sha, "stepRange": sr,
                                "grib_last_modified": r.headers.get("Last-Modified")}
            for s, v in ST.items():
                j, i = NEAR[s]
                kn = float(vals[j*1440 + i])
                rows.append({"date": ymd, "cycle": cyc, "step": step, "stepRange": sr, "param": p, "station": s,
                             "valid_utc": (dt.datetime.strptime(ymd, "%Y%m%d") + dt.timedelta(hours=cyc+step)).strftime("%Y-%m-%dT%H:%MZ"),
                             "grid_lat": 90.0 - j*0.25, "grid_lon": -180.0 + i*0.25,
                             "nearest_K": kn, "nearest_F": (kn - 273.15)*9/5 + 32,
                             "bilinear_K": bilinear(vals, v["lat"], v["lon"]),
                             "index_last_modified": smeta["index_last_modified"],
                             "grib_last_modified": r.headers.get("Last-Modified"), "msg_sha256": sha})
        meta["steps"][step] = smeta
    return meta, rows

def main():
    done = set()
    if os.path.exists(RUNLOG):
        for l in open(RUNLOG):
            m = json.loads(l)
            if m.get("status") == "ok": done.add((m["date"], m["cycle"]))
    tasks = []
    d = D0
    while d <= D1:
        for c in (0, 12):
            if (d.strftime("%Y%m%d"), c) not in done: tasks.append((d, c))
        d += dt.timedelta(days=1)
    log(f"start pid={os.getpid()} tasks={len(tasks)} done={len(done)}")
    def worker(t):
        if os.path.exists(STOP) or dt.datetime.now() >= FREEZE:
            return None
        try:
            meta, rows = do_run(*t); meta["status"] = "ok"
        except Exception as ex:
            meta, rows = {"date": t[0].strftime("%Y%m%d"), "cycle": t[1], "status": f"fail {ex!r}"}, []
        with lock:
            with open(PROG, "a") as f:
                for r in rows: f.write(json.dumps(r) + "\n")
            with open(RUNLOG, "a") as f: f.write(json.dumps(meta) + "\n")
        log(f"run {meta['date']} {meta['cycle']:02d}z {meta['status'][:60]} rows={len(rows)} stats={stats}")
    with ThreadPoolExecutor(max_workers=int(sys.argv[1]) if len(sys.argv) > 1 else 3) as ex:
        list(ex.map(worker, tasks))
    log(f"end stats={stats}")

if __name__ == "__main__":
    main()
