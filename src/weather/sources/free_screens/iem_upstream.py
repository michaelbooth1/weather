"""IEM ASOS/AWOS observations upstream of and around each US settlement station (lane L6): fetch and build.

Source role: supporting evidence, research only (never settlement). Free, no key, serial and polite
(``common.polite_get``: >= 2 s between requests, backoff on 429/5xx).

Windows (UTC, end exclusive, never after local midnight ending 2026-09-29):
- training: 08-01T00Z .. next 01-01T12Z for 2021..2025 (covers the Aug-Sep and Oct-Dec local months);
- development: 2026-07-30T00Z .. local midnight ending 2026-09-29 in the market's zone.

Stations: the 11 market stations, plus a ring per market chosen by ``select`` from the IEM state
``*_ASOS`` network listings (AWOS sites included): online, archive begun by 2021-06-01, 50-150 km away.
Per 45-degree sector the station nearest 90 km (full ring, <= 8), plus up to 3 extra stations in the
upwind arc (prevailing morning wind-from direction +- 60 deg, from the market station's own Aug-Sep
2021-2025 07-12 local observations). ``select`` therefore needs the market stations fetched first.

CLI::

    python -m weather.sources.free_screens.iem_upstream fetch-market [--root DIR]
    python -m weather.sources.free_screens.iem_upstream select [--root DIR]
    python -m weather.sources.free_screens.iem_upstream fetch-ring [--root DIR]
    python -m weather.sources.free_screens.iem_upstream build [--root DIR]
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
from urllib.parse import urlencode

import numpy as np
import pandas as pd

from weather.sources.free_screens import common

SOURCE = "upstream_obs"
SCHEMA = "free_screens_iem_upstream/1"
DEFAULT_ROOT = Path(r"C:\Users\Michael\Documents\github\weather\data\research")
URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
NETWORK_URL = "https://mesonet.agron.iastate.edu/geojson/network/{net}.geojson"
FIELDS = ("tmpf", "dwpf", "drct", "sknt", "skyc1", "skyc2", "skyc3", "skyl1", "skyl2", "skyl3", "metar")
TRAIN_YEARS = (2021, 2022, 2023, 2024, 2025)
DEV_START = datetime(2026, 7, 30, tzinfo=timezone.utc)
RING_KM = (50.0, 150.0)
RING_TARGET_KM = 90.0
UPWIND_HALF_ARC = 60.0
UPWIND_EXTRA = 3
ARCHIVE_BY = "2021-06-01"

STATES = {
    "KATL": ("GA", "AL", "SC", "TN", "NC"), "KAUS": ("TX",), "KORD": ("IL", "IN", "WI"),
    "KDAL": ("TX", "OK"), "KBKF": ("CO", "WY"), "KHOU": ("TX", "LA"), "KLAX": ("CA",),
    "KMIA": ("FL",), "KLGA": ("NY", "NJ", "CT", "PA"), "KSFO": ("CA",), "KSEA": ("WA",),
}


def haversine_km(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def bearing_deg(a, b):
    """Initial bearing from a to b, degrees clockwise from north."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    y = math.sin(lon2 - lon1) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def ang_diff(a, b):
    return abs((a - b + 180.0) % 360.0 - 180.0)


def windows(tz_name):
    out = [(datetime(y, 8, 1, tzinfo=timezone.utc), datetime(y + 1, 1, 1, 12, tzinfo=timezone.utc))
           for y in TRAIN_YEARS]
    out.append((DEV_START, common.local_day_end_utc(tz_name)))
    return out


def request_url(sid, start, end):
    params = [("station", sid)] + [("data", f) for f in FIELDS] + [
        ("tz", "Etc/UTC"), ("format", "onlycomma"), ("latlon", "no"), ("missing", "M"), ("trace", "T"),
        ("direct", "no"), ("report_type", "3"), ("report_type", "4"),
        ("sts", start.strftime("%Y-%m-%dT%H:%MZ")), ("ets", end.strftime("%Y-%m-%dT%H:%MZ"))]
    return f"{URL}?{urlencode(params)}"


def _fetch_station(session, src, receipts, sid, tz_name, role, market, log, tag):
    for a, b in windows(tz_name):
        key = f"{sid}|{common.utc_stamp(a)}|{common.utc_stamp(b)}"
        if receipts.is_done(key):
            continue
        url = request_url(sid, a, b)
        resp = common.polite_get(session, url)
        body = resp.content
        rows = max(0, body.count(b"\n") - 1) if resp.status_code == 200 else 0
        rel, sha = common.store_gzip(src, f"{sid}_{a:%Y%m%d%H}_{b:%Y%m%d%H}.csv.gz", body)
        receipts.record({"key": key, "file": rel, "sha256": sha, "url": url, "status": resp.status_code,
                         "bytes": len(body), "rows": rows, "station": sid, "role": role, "market": market,
                         "start_utc": a.isoformat(), "end_utc": b.isoformat(),
                         "fetched_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        log(f"{tag} {key} status={resp.status_code} rows={rows} bytes={len(body)}")


def fetch_market(root, session=None, log=print):
    import requests

    session = session or requests.Session()
    src = Path(root) / SOURCE
    receipts = common.ReceiptLog(src)
    stations = common.us_stations()
    for i, st in enumerate(stations, 1):
        _fetch_station(session, src, receipts, st.icao[1:], st.timezone, "market", st.market, log,
                       f"[market {i}/{len(stations)}]")


def network_stations(root, session=None, log=print):
    """IEM network listings for every state used, cached under ``<src>/networks``."""
    import requests

    session = session or requests.Session()
    src = Path(root) / SOURCE / "networks"
    src.mkdir(parents=True, exist_ok=True)
    out = []
    for state in sorted({s for v in STATES.values() for s in v}):
        net = f"{state}_ASOS"
        path = src / f"{net}.geojson"
        if not path.is_file():
            resp = common.polite_get(session, NETWORK_URL.format(net=net))
            resp.raise_for_status()
            path.write_bytes(resp.content)
            log(f"network {net} bytes={len(resp.content)}")
        for feat in json.loads(path.read_text(encoding="utf-8"))["features"]:
            p = feat["properties"]
            lon, lat = feat["geometry"]["coordinates"][:2]
            out.append({"sid": p["sid"], "network": net, "name": p.get("sname"), "lat": float(lat),
                        "lon": float(lon), "elevation_m": p.get("elevation"),
                        "archive_begin": p.get("archive_begin"), "archive_end": p.get("archive_end"),
                        "online": bool(p.get("online")),
                        "is_awos": str((p.get("attributes") or {}).get("IS_AWOS", "0")) == "1"})
    return out


def parse_csv(body):
    text = body.decode("utf-8", "replace")
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows or "valid" not in rows[0]:
        return pd.DataFrame(columns=["station", "valid", *FIELDS])
    return pd.DataFrame(rows)


def load_raw(root, role=None):
    src = Path(root) / SOURCE
    receipts = common.ReceiptLog(src)
    frames = []
    for row in sorted(receipts.done.values(), key=lambda r: r["key"]):
        if role and row.get("role") != role:
            continue
        frame = parse_csv(gzip.decompress((src / row["file"]).read_bytes()))
        if len(frame):
            frame["role"], frame["market"] = row.get("role"), row.get("market")
            frames.append(frame)
    return pd.concat(frames, ignore_index=True), receipts


def _num(series):
    return pd.to_numeric(series.replace({"M": np.nan, "T": np.nan}), errors="coerce")


def prevailing_wind(root):
    """Vector-mean morning (07-12 local) wind-from direction per market station, Aug-Sep 2021-2025."""
    frame, _ = load_raw(root, role="market")
    out = {}
    for st in common.us_stations():
        g = frame[frame.station == st.icao[1:]]
        valid = pd.to_datetime(g.valid, utc=True)
        local = valid.dt.tz_convert(st.timezone)
        sel = (local.dt.month.isin([8, 9]) & local.dt.hour.between(7, 12) & (local.dt.year <= 2025)).to_numpy()
        d, s = _num(g.drct).to_numpy()[sel], _num(g.sknt).to_numpy()[sel]
        ok = np.isfinite(d) & np.isfinite(s) & (s > 0)
        u = -(s[ok] * np.sin(np.radians(d[ok]))).mean()
        v = -(s[ok] * np.cos(np.radians(d[ok]))).mean()
        from_dir = (math.degrees(math.atan2(-u, -v)) + 360.0) % 360.0
        out[st.icao] = {"from_deg": round(from_dir, 1), "resultant_kt": round(math.hypot(u, v), 2),
                        "mean_speed_kt": round(float(s[ok].mean()), 2), "n": int(ok.sum())}
    return out


def select(root, session=None, log=print):
    cands = network_stations(root, session, log)
    wind = prevailing_wind(root)
    market_sids = {s.icao[1:] for s in common.us_stations()}
    selection = {}
    for st in common.us_stations():
        here = (st.lat, st.lon)
        pool = {}
        for c in cands:
            if c["network"][:2] not in STATES[st.icao] or c["sid"] in market_sids or not c["online"]:
                continue
            if not c["archive_begin"] or c["archive_begin"] > ARCHIVE_BY or c["archive_end"]:
                continue
            d = haversine_km(here, (c["lat"], c["lon"]))
            if RING_KM[0] <= d <= RING_KM[1]:
                pool[c["sid"]] = dict(c, dist_km=round(d, 2), bearing_deg=round(bearing_deg(here, (c["lat"], c["lon"])), 1))
        chosen = {}
        for sector in range(8):
            inside = [c for c in pool.values() if int(c["bearing_deg"] // 45) % 8 == sector]
            if inside:
                best = min(inside, key=lambda c: (abs(c["dist_km"] - RING_TARGET_KM), c["sid"]))
                chosen[best["sid"]] = dict(best, why=f"ring sector {sector * 45}-{sector * 45 + 45}")
        up = wind[st.icao]["from_deg"]
        arc = sorted((c for c in pool.values() if c["sid"] not in chosen and ang_diff(c["bearing_deg"], up) <= UPWIND_HALF_ARC),
                     key=lambda c: (abs(c["dist_km"] - RING_TARGET_KM), c["sid"]))
        for c in arc[:UPWIND_EXTRA]:
            chosen[c["sid"]] = dict(c, why="upwind extra")
        for c in chosen.values():
            c["upwind_prevailing"] = ang_diff(c["bearing_deg"], up) <= UPWIND_HALF_ARC
        selection[st.icao] = {"market": st.market, "lat": st.lat, "lon": st.lon, "timezone": st.timezone,
                              "prevailing_morning_wind": wind[st.icao], "candidates_in_ring": len(pool),
                              "selected": sorted(chosen.values(), key=lambda c: c["bearing_deg"])}
        log(f"{st.icao}: ring pool {len(pool)}, selected {len(chosen)}, prevailing from {up}")
    rule = {"ring_km": RING_KM, "ring_target_km": RING_TARGET_KM, "upwind_half_arc_deg": UPWIND_HALF_ARC,
            "upwind_extra": UPWIND_EXTRA, "archive_begun_by": ARCHIVE_BY, "states": STATES,
            "prevailing": "vector mean of the market station's 07-12 local wind, Aug-Sep 2021-2025"}
    path = Path(root) / SOURCE / "selection.json"
    path.write_text(json.dumps({"rule": rule, "markets": selection}, indent=1, sort_keys=True), encoding="utf-8")
    return selection


def fetch_ring(root, session=None, log=print):
    import requests

    session = session or requests.Session()
    src = Path(root) / SOURCE
    receipts = common.ReceiptLog(src)
    sel = json.loads((src / "selection.json").read_text(encoding="utf-8"))["markets"]
    plan = [(icao, m, c) for icao, m in sorted(sel.items()) for c in m["selected"]]
    for i, (icao, m, c) in enumerate(plan, 1):
        _fetch_station(session, src, receipts, c["sid"], m["timezone"], "ring", m["market"], log,
                       f"[ring {i}/{len(plan)} {icao}]")


_TGROUP = r" T([01])(\d{3})([01])(\d{3})"


def build(root):
    """Every report -> ``obs.parquet``: station, role, market, valid_utc, tmpf, dwpf, drct, sknt, cover
    (max oktas-like fraction of the three layers: CLR/SKC 0, FEW .25, SCT .5, BKN .75, OVC/VV 1),
    ceiling_ft (lowest BKN/OVC/VV base, NaN when none), tgroup_f, is_cor."""
    frame, receipts = load_raw(root)
    out = pd.DataFrame({"station": frame.station.astype(str), "role": frame.role, "market": frame.market,
                        "valid_utc": pd.to_datetime(frame.valid, utc=True)})
    for f in ("tmpf", "dwpf", "drct", "sknt"):
        out[f] = _num(frame[f]).to_numpy()
    cover_map = {"CLR": 0.0, "SKC": 0.0, "NCD": 0.0, "NSC": 0.0, "FEW": .25, "SCT": .5, "BKN": .75, "OVC": 1.0, "VV": 1.0}
    covers, ceil = [], np.full(len(frame), np.nan)
    for k in (1, 2, 3):
        c = frame[f"skyc{k}"].map(cover_map).to_numpy(float)
        h = _num(frame[f"skyl{k}"]).to_numpy(float)
        covers.append(c)
        is_ceiling = np.isin(frame[f"skyc{k}"].to_numpy(), ["BKN", "OVC", "VV"])
        ceil = np.where(is_ceiling & np.isnan(ceil), h, ceil)
    out["cover"] = np.nanmax(np.vstack(covers), axis=0) if len(frame) else []
    out["ceiling_ft"] = ceil
    metar = frame.metar.fillna("").astype(str)
    tg = metar.str.extract(_TGROUP)
    tc = np.where(tg[0] == "1", -1.0, 1.0) * pd.to_numeric(tg[1], errors="coerce") / 10.0
    out["tgroup_f"] = tc * 1.8 + 32.0
    out["is_cor"] = metar.str.contains(r" COR ", regex=True).to_numpy()
    out = out.dropna(subset=["valid_utc"]).drop_duplicates(["station", "valid_utc", "role", "market"])
    tz = {s.market: s.timezone for s in common.us_stations()}
    for market, g in out.groupby("market"):
        end = common.local_day_end_utc(tz[market])
        if (g.valid_utc >= end).any():
            raise AssertionError(f"{market}: rows at or after local midnight ending {common.DEV_LAST}")
    out = out.sort_values(["market", "role", "station", "valid_utc"]).reset_index(drop=True)
    path = Path(root) / SOURCE / "obs.parquet"
    out.to_parquet(path, index=False)
    per = out.groupby(["role", "station"]).agg(rows=("valid_utc", "size"), first=("valid_utc", "min"),
                                                last=("valid_utc", "max"), tmpf_fill=("tmpf", lambda s: float(s.notna().mean())))
    manifest = {"schema": SCHEMA, "file": path.name, "sha256": common.sha256_bytes(path.read_bytes()),
                "rows": int(len(out)), "receipts": len(receipts.done),
                "requests_non_200": sum(1 for r in receipts.done.values() if r["status"] != 200),
                "bytes_fetched": int(sum(r["bytes"] for r in receipts.done.values())),
                "windows": "train 08-01T00Z..next 01-01T12Z for 2021-2025; dev 2026-07-30T00Z..local midnight ending 2026-09-29",
                "selection_sha256": common.sha256_bytes((Path(root) / SOURCE / "selection.json").read_bytes()),
                "per_station": {f"{r}|{s}": {"rows": int(v.rows), "first": v["first"].isoformat(),
                                             "last": v["last"].isoformat(), "tmpf_fill": round(v.tmpf_fill, 3)}
                                for (r, s), v in per.iterrows()}}
    (Path(root) / SOURCE / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    return {k: v for k, v in manifest.items() if k != "per_station"}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m weather.sources.free_screens.iem_upstream")
    parser.add_argument("command", choices=("fetch-market", "select", "fetch-ring", "build"))
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    args = parser.parse_args(argv)
    log = lambda m: print(m, flush=True)  # noqa: E731
    if args.command == "fetch-market":
        fetch_market(args.root, log=log)
    elif args.command == "select":
        select(args.root, log=log)
    elif args.command == "fetch-ring":
        fetch_ring(args.root, log=log)
    else:
        print(json.dumps(build(args.root), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
