"""MRMS composite reflectivity near the US settlement stations (screen F2): fetch, decode, extract.

Source: the public NOAA MRMS bucket (``noaa-mrms-pds``, AWS Open Data; no account), product
``MergedReflectivityQCComposite_00.50`` (2-minute CONUS 0.01 deg grid, GRIB2 with PNG packing).
Production captures only the object *listing* of ``PrecipRate_00.00`` ("nearest MRMS extraction is not
configured"), so every value used here is fetched from the archive.

Sampling (fixed a priori, to keep the pull small): for each UTC day, the newest object valid at or
before each UTC :00 and :30 from 16:00Z to 23:30Z (local 12:00-16:30 Eastern .. 09:00-16:30 Pacific).
Raw grids are not kept: each object is hashed (sha256 of the gzip bytes, recorded in the receipt log)
and reduced to the maximum reflectivity within 25 and 50 km of each station. Point in time: MRMS
objects reach the bucket about 1-2 minutes after valid; the screen uses valid + 5 min.

The decoder is a minimal GRIB2 reader for this product only (grid template 3.0, data representation
5.41 PNG, no bitmap); it refuses anything else.
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import math
import re
import struct
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from weather.sources.free_screens import common

SOURCE = "mrms_refl"
SCHEMA = "free_screens_mrms_refl/1"
PRODUCT = "MergedReflectivityQCComposite_00.50"
BUCKET = "https://noaa-mrms-pds.s3.amazonaws.com"
SLOTS_UTC = [(h, m) for h in range(16, 24) for m in (0, 30)]
RADII_KM = (25.0, 50.0)
LATENCY_MIN = 5


def _sm32(raw):
    """GRIB sign-magnitude int32."""
    v = struct.unpack(">I", raw)[0]
    return -(v & 0x7FFFFFFF) if v & 0x80000000 else v


def _sm16(raw):
    v = struct.unpack(">H", raw)[0]
    return -(v & 0x7FFF) if v & 0x8000 else v


def decode_grib2(buf):
    """-> (values float32 [nj, ni], meta dict). Only template 3.0 / 5.41 / no bitmap."""
    from PIL import Image

    if buf[:4] != b"GRIB" or buf[7] != 2:
        raise ValueError("not a GRIB2 message")
    pos, meta, values = 16, {}, None
    while pos < len(buf) - 4:
        if buf[pos:pos + 4] == b"7777":
            break
        length, num = struct.unpack(">IB", buf[pos:pos + 5])
        sec = buf[pos:pos + length]
        if num == 3:
            if struct.unpack(">H", sec[12:14])[0] != 0:
                raise ValueError("grid template is not 3.0")
            ni, nj = struct.unpack(">II", sec[30:38])
            meta.update(ni=ni, nj=nj, la1=_sm32(sec[46:50]) / 1e6, lo1=_sm32(sec[50:54]) / 1e6,
                        la2=_sm32(sec[55:59]) / 1e6, lo2=_sm32(sec[59:63]) / 1e6,
                        di=_sm32(sec[63:67]) / 1e6, dj=_sm32(sec[67:71]) / 1e6, scan=sec[71])
        elif num == 5:
            if struct.unpack(">H", sec[9:11])[0] != 41:
                raise ValueError("data representation is not 5.41 (PNG)")
            meta.update(R=struct.unpack(">f", sec[11:15])[0], E=_sm16(sec[15:17]), D=_sm16(sec[17:19]),
                        nbits=sec[19])
        elif num == 6:
            if sec[5] != 255:
                raise ValueError("bitmap present")
        elif num == 7:
            img = Image.open(io.BytesIO(sec[5:]))
            x = np.asarray(img, dtype=np.float64)
            values = ((meta["R"] + x * 2.0 ** meta["E"]) / 10.0 ** meta["D"]).astype(np.float32)
        pos += length
    if values is None or values.shape != (meta["nj"], meta["ni"]):
        raise ValueError("no data section or shape mismatch")
    return values, meta


def station_windows(meta, stations, radius_km):
    """{icao: (row slice, col slice, boolean disk mask)} on the grid (north-to-south rows, scan 0)."""
    out = {}
    lat0, lon0 = meta["la1"], meta["lo1"] - 360.0 if meta["lo1"] > 180 else meta["lo1"]
    for st in stations:
        dlat = radius_km / 111.2
        dlon = radius_km / (111.2 * math.cos(math.radians(st.lat)))
        r0 = int(math.floor((lat0 - (st.lat + dlat)) / meta["dj"]))
        r1 = int(math.ceil((lat0 - (st.lat - dlat)) / meta["dj"])) + 1
        c0 = int(math.floor((st.lon - dlon - lon0) / meta["di"]))
        c1 = int(math.ceil((st.lon + dlon - lon0) / meta["di"])) + 1
        r0, c0 = max(r0, 0), max(c0, 0)
        r1, c1 = min(r1, meta["nj"]), min(c1, meta["ni"])
        lats = lat0 - np.arange(r0, r1) * meta["dj"]
        lons = lon0 + np.arange(c0, c1) * meta["di"]
        y = (lats[:, None] - st.lat) * 111.2
        x = (lons[None, :] - st.lon) * 111.2 * math.cos(math.radians(st.lat))
        out[st.icao] = (slice(r0, r1), slice(c0, c1), (x ** 2 + y ** 2) <= radius_km ** 2)
    return out


def extract(values, meta, stations):
    rows = {}
    for radius in RADII_KM:
        for icao, (rs, cs, mask) in station_windows(meta, stations, radius).items():
            win = values[rs, cs][mask]
            win = win[win > -900]               # -999 = no coverage
            rows.setdefault(icao, {})[f"max_dbz_{int(radius)}km"] = float(win.max()) if win.size else math.nan
            rows[icao][f"cover_{int(radius)}km"] = float(win.size / mask.sum()) if mask.sum() else 0.0
    return rows


def list_day(session, day):
    prefix = f"CONUS/{PRODUCT}/{day:%Y%m%d}/"
    keys, token = [], None
    while True:
        url = f"{BUCKET}/?list-type=2&prefix={prefix}" + (f"&continuation-token={_q(token)}" if token else "")
        resp = common.polite_get(session, url, spacing_s=1.0)
        text = resp.text
        keys += re.findall(r"<Key>([^<]+)</Key>", text)
        m = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", text)
        if not m:
            return keys
        token = m.group(1)


def _q(text):
    from urllib.parse import quote
    return quote(text, safe="")


def key_valid(key):
    m = re.search(r"_(\d{8})-(\d{6})\.grib2\.gz$", key)
    return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc) if m else None


def pick_slots(keys, day):
    valid = sorted((key_valid(k), k) for k in keys if key_valid(k))
    picks = []
    for h, m in SLOTS_UTC:
        slot = datetime(day.year, day.month, day.day, h, m, tzinfo=timezone.utc)
        cands = [(v, k) for v, k in valid if slot - timedelta(minutes=10) <= v <= slot]
        if cands:
            picks.append((slot, *cands[-1]))
    return picks


def default_days():
    days = []
    for y in (2024, 2025):
        d = date(y, 8, 1)
        while d <= date(y, 9, 30):
            days.append(d)
            d += timedelta(days=1)
    d = date(2026, 7, 31)
    while d <= common.DEV_LAST:
        days.append(d)
        d += timedelta(days=1)
    return days


def fetch(root, days=None, session=None, log=print):
    import requests

    session = session or requests.Session()
    src = Path(root) / SOURCE
    receipts = common.ReceiptLog(src)
    stations = common.us_stations()
    days = days or default_days()
    for n, day in enumerate(days, 1):
        if day > common.DEV_LAST:
            raise ValueError("refused: MRMS day after 2026-09-29")
        key = f"{day.isoformat()}"
        if receipts.is_done(key):
            continue
        picks = pick_slots(list_day(session, day), day)
        rows, objects = [], []
        for slot, valid, obj in picks:
            resp = common.polite_get(session, f"{BUCKET}/{obj}", spacing_s=1.0)
            if resp.status_code != 200:
                objects.append({"key": obj, "status": resp.status_code})
                continue
            raw = resp.content
            try:
                values, meta = decode_grib2(gzip.decompress(raw))
                ext = extract(values, meta, stations)
            except Exception as exc:          # recorded, never silently treated as no-echo
                objects.append({"key": obj, "status": 200, "error": str(exc)[:200], "sha256": common.sha256_bytes(raw)})
                continue
            objects.append({"key": obj, "status": 200, "bytes": len(raw), "sha256": common.sha256_bytes(raw)})
            for icao, vals in ext.items():
                rows.append({"station": icao, "slot_utc": slot.isoformat(), "valid_utc": valid.isoformat(), **vals})
        body = json.dumps({"day": key, "rows": rows, "objects": objects}, sort_keys=True).encode("utf-8")
        rel, sha = common.store_gzip(src, f"{key}.json.gz", body)
        receipts.record({"key": key, "file": rel, "sha256": sha, "objects": len(objects),
                         "bytes": int(sum(o.get("bytes", 0) for o in objects)), "rows": len(rows),
                         "errors": sum(1 for o in objects if "error" in o or o.get("status") != 200),
                         "fetched_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        log(f"[{n}/{len(days)}] {key} objects={len(objects)} rows={len(rows)}")


def build(root):
    src = Path(root) / SOURCE
    receipts = common.ReceiptLog(src)
    rows = []
    for row in sorted(receipts.done.values(), key=lambda r: r["key"]):
        rows += json.loads(gzip.decompress((src / row["file"]).read_bytes()))["rows"]
    frame = pd.DataFrame(rows)
    frame["valid_utc"] = pd.to_datetime(frame.valid_utc, utc=True)
    frame["slot_utc"] = pd.to_datetime(frame.slot_utc, utc=True)
    frame = frame.sort_values(["station", "valid_utc"]).reset_index(drop=True)
    out = src / "station_refl.parquet"
    frame.to_parquet(out, index=False)
    manifest = {"schema": SCHEMA, "file": out.name, "sha256": common.sha256_bytes(out.read_bytes()),
                "rows": int(len(frame)), "days": len(receipts.done),
                "objects": int(sum(r["objects"] for r in receipts.done.values())),
                "bytes_fetched": int(sum(r["bytes"] for r in receipts.done.values())),
                "errors": int(sum(r["errors"] for r in receipts.done.values())),
                "first": frame.valid_utc.min().isoformat(), "last": frame.valid_utc.max().isoformat(),
                "latency_min": LATENCY_MIN, "product": PRODUCT}
    (src / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m weather.sources.free_screens.mrms")
    parser.add_argument("command", choices=("fetch", "build", "decode"))
    parser.add_argument("--root", default=str(common.DEFAULT_ROOT))
    parser.add_argument("--file", help="decode: one local .grib2.gz (probe)")
    args = parser.parse_args(argv)
    if args.command == "fetch":
        fetch(args.root, log=lambda m: print(m, flush=True))
    elif args.command == "decode":
        values, meta = decode_grib2(gzip.decompress(Path(args.file).read_bytes()))
        print(json.dumps({k: v for k, v in meta.items()}, default=float))
        print(json.dumps(extract(values, meta, common.us_stations())))
    else:
        print(json.dumps(build(args.root), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
