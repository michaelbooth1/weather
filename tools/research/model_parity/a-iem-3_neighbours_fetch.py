"""A-IEM-3: neighbour ASOS/AWOS METAR (tmpf, valid, report type, raw metar) within 50 km of each market station.
Single connection, >= 2 s spacing, back off on 429/503/'Too many requests' text. Window 2026-05-01..2026-09-29 (UTC
valid; the sts/ets end is 2026-09-30T00:00Z exclusive). Freeze 04:30 local; deadline 03:45 local.
"""
import csv, datetime as dt, gzip, hashlib, io, json, math, os, sys, time
from pathlib import Path
import requests

ROOT = Path(r"C:\swarm\data\iem\neighbours")
RAW = ROOT / "raw"
RAW.mkdir(parents=True, exist_ok=True)
LOG = ROOT / "fetch.log"
STOP = Path(r"C:\swarm\STOP")
DEADLINE = dt.datetime(2026, 10, 4, 3, 45)
STS, ETS = "2026-05-01T00:00Z", "2026-09-30T00:00Z"
RADIUS_KM, CAP = 50.0, 6
NETWORKS = ["GA_ASOS", "TX_ASOS", "CO_ASOS", "CA_ASOS", "NY_ASOS", "FL_ASOS", "IL_ASOS", "WA_ASOS",
            # adjacent-state networks a 50 km circle can reach (LGA -> NJ/CT, ORD -> IN/WI)
            "NJ_ASOS", "CT_ASOS", "IN_ASOS", "WI_ASOS"]
S = requests.Session()
S.headers["User-Agent"] = "weather-research-swarm/1.0 (single connection, 1 req/2s)"
_last = [0.0]


def log(msg):
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def guard():
    if STOP.exists():
        log("STOP file present; exiting"); sys.exit(2)
    if dt.datetime.now() >= DEADLINE:
        log("deadline reached; exiting"); sys.exit(3)


def get(url, params=None):
    backoff = 60
    for attempt in range(6):
        guard()
        wait = 2.0 - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            r = S.get(url, params=params, timeout=180)
        except requests.RequestException as e:
            log(f"error {e}; sleep 30"); time.sleep(30); continue
        body = r.text
        if r.status_code in (429, 503) or "Too many requests" in body[:300]:
            log(f"throttled status={r.status_code}; backoff {backoff}s"); time.sleep(backoff); backoff *= 2; continue
        if r.status_code != 200:
            log(f"status {r.status_code} body={body[:200]!r}; sleep 30"); time.sleep(30); continue
        return r
    raise RuntimeError(f"failed after retries: {url} {params}")


def hav(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return 2 * 6371.0088 * math.asin(math.sqrt(a))


def main():
    stations = json.load(open(r"C:\swarm\stations.json"))["stations"]
    # 1) metadata
    cands = []
    meta_files = {}
    for net in NETWORKS:
        url = f"https://mesonet.agron.iastate.edu/geojson/network/{net}.geojson"
        r = get(url)
        p = RAW / f"network_{net}.geojson"
        p.write_bytes(r.content)
        meta_files[net] = url
        for ft in r.json()["features"]:
            pr = ft["properties"]; lon, lat = ft["geometry"]["coordinates"]
            cands.append(dict(sid=pr["sid"], network=net, name=pr.get("sname"), lat=lat, lon=lon,
                              elevation_m=pr.get("elevation"), archive_begin=pr.get("archive_begin"),
                              archive_end=pr.get("archive_end"), online=pr.get("online"),
                              is_awos=(pr.get("attributes") or {}).get("IS_AWOS") == "1"))
        log(f"meta {net}: {len(r.json()['features'])} stations")
    selection = {}
    for st, m in stations.items():
        near = []
        for c in cands:
            if c["sid"] == m["iem_id"]:
                continue
            if c["archive_begin"] and c["archive_begin"] > "2026-09-29":
                continue
            if c["archive_end"] and c["archive_end"] < "2026-05-01":
                continue
            d = hav(m["lat"], m["lon"], c["lat"], c["lon"])
            if d <= RADIUS_KM:
                near.append(dict(c, dist_km=round(d, 2)))
        near.sort(key=lambda x: x["dist_km"])
        # de-duplicate the same sid listed in two networks
        seen, uniq = set(), []
        for c in near:
            if c["sid"] not in seen:
                seen.add(c["sid"]); uniq.append(c)
        selection[st] = dict(within_50km=len(uniq), selected=uniq[:CAP], not_selected=[c["sid"] for c in uniq[CAP:]])
        log(f"{st}: {len(uniq)} within 50 km; selected {[ (c['sid'], c['dist_km']) for c in uniq[:CAP]]}")
    json.dump(selection, open(ROOT / "selection.json", "w"), indent=1)
    # 2) METAR per neighbour, routine (3) and SPECI (4) separately so report type is explicit
    jobs = []
    for st, s in selection.items():
        for c in s["selected"]:
            for rt, rname in ((3, "routine"), (4, "speci")):
                jobs.append((st, c, rt, rname))
    done = {}
    for i, (st, c, rt, rname) in enumerate(jobs, 1):
        out = RAW / f"{c['sid']}_{rname}.csv.gz"
        if out.exists():
            log(f"[{i}/{len(jobs)}] {c['sid']} {rname} exists; skip"); continue
        params = [("station", c["sid"]), ("data", "tmpf"), ("data", "metar"), ("tz", "Etc/UTC"),
                  ("format", "onlycomma"), ("latlon", "no"), ("missing", "M"), ("trace", "T"),
                  ("direct", "no"), ("report_type", str(rt)), ("sts", STS), ("ets", ETS)]
        t0 = time.time()
        r = get("https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py", params)
        txt = r.text
        if not txt.startswith("station,valid"):
            log(f"[{i}/{len(jobs)}] {c['sid']} {rname} unexpected body {txt[:200]!r}")
            continue
        with gzip.open(out, "wt", encoding="utf-8", newline="") as f:
            f.write(txt)
        nrows = txt.count("\n") - 1
        log(f"[{i}/{len(jobs)}] {st} nb={c['sid']} {rname} rows={nrows} {time.time()-t0:.1f}s url={r.url}")
    log("all requests done")


if __name__ == "__main__":
    main()
