"""Lane L13: point-in-time HRRR 2 m temperature at the market settlement stations (research corpus).

Free official NOAA HRRR on the AWS Open Data bucket ``noaa-hrrr-bdp-pds`` (anonymous HTTPS). For
every (local date, station, snapshot hour) the fetcher picks the newest HRRR cycle whose needed
forecast-hour objects were all published (S3 ``LastModified`` of the ``.grib2`` and its ``.idx``,
plus a poll margin) before the snapshot, then reads only the wanted GRIB2 messages with HTTP Range
requests located through the ``.idx`` sidecar. Full files are never downloaded and raw messages are
never written to disk: each message is decoded in memory by the pure-numpy GRIB2 decoder below
(grid template 3.30, product template 4.0, data templates 5.0 and 5.3) and only the nearest grid
point plus its 3x3 neighbourhood per station is kept, with the message sha256 in the manifest.

Research / acquisition only: no production path imports this module, nothing here is served, and
it refuses any date after ``LAST_ALLOWED``. The plan and sizing live in ``C:\\t\\l13\\hrrr_plan.md``.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import random
import shutil
import struct
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

BUCKET = "https://noaa-hrrr-bdp-pds.s3.amazonaws.com"
LAST_ALLOWED = dt.date(2026, 9, 29)
UTC = dt.timezone.utc
MAX_FH = 18  # every hourly HRRR cycle reaches f18 (f48 only at 00/06/12/18Z)
GIB = 1_000_000_000

# idx search key -> (GRIB2 discipline, parameter category, parameter number, surface type, value)
VARIABLES = {
    "TMP:2 m above ground": (0, 0, 0, 103, 2),
    "DPT:2 m above ground": (0, 0, 6, 103, 2),
    "TCDC:entire atmosphere": (0, 6, 1, 10, None),
    "UGRD:10 m above ground": (0, 2, 2, 103, 10),
    "VGRD:10 m above ground": (0, 2, 3, 103, 10),
}
UNITS = {"TMP:2 m above ground": "K", "DPT:2 m above ground": "K", "TCDC:entire atmosphere": "%",
         "UGRD:10 m above ground": "m/s grid-relative", "VGRD:10 m above ground": "m/s grid-relative"}

# HRRR CONUS grid (GRIB2 grid template 3.30), checked against every decoded message.
HRRR_GRID = {
    "nx": 1799, "ny": 1059, "la1": 21.138123, "lo1": 237.280472, "lov": 262.5,
    "latin1": 38.5, "latin2": 38.5, "dx": 3000.0, "dy": 3000.0, "scan": 0x40, "radius": 6371229.0,
}


# --------------------------------------------------------------------------- GRIB2 decoding
def _sm(value, bits):
    """Decode a GRIB2 sign-and-magnitude integer of ``bits`` bits."""
    sign = 1 << (bits - 1)
    return -(value & (sign - 1)) if value & sign else value


def _bits(data, bitpos, width):
    """Vectorised read of unsigned ``width``-bit fields (width <= 56) at absolute bit positions."""
    bitpos = np.asarray(bitpos, dtype=np.int64)
    width = np.broadcast_to(np.asarray(width, dtype=np.int64), bitpos.shape)
    out = np.zeros(bitpos.shape, dtype=np.int64)
    if bitpos.size == 0:
        return out
    buf = np.frombuffer(bytes(data) + b"\0" * 8, dtype=np.uint8)
    byte = bitpos >> 3
    word = np.zeros(bitpos.shape, dtype=np.uint64)
    for k in range(8):
        word = (word << np.uint64(8)) | buf[byte + k].astype(np.uint64)
    shift = (64 - (bitpos & 7) - width).astype(np.uint64)
    mask = ((np.uint64(1) << width.astype(np.uint64)) - np.uint64(1))
    vals = ((word >> shift) & mask).astype(np.int64)
    return np.where(width > 0, vals, 0)


def _scalar_bits(data, bitpos, width):
    return int(_bits(data, [bitpos], width)[0]) if width else 0


def parse_sections(blob):
    """Split one GRIB2 message into {section number: bytes}; fail closed on any framing error."""
    if blob[:4] != b"GRIB" or blob[7] != 2:
        raise ValueError("not a GRIB2 message")
    total = struct.unpack(">Q", blob[8:16])[0]
    if total != len(blob) or blob[-4:] != b"7777":
        raise ValueError(f"GRIB2 length mismatch: header {total}, got {len(blob)}")
    secs = {0: blob[:16]}
    p = 16
    while p < len(blob) - 4:
        length, num = struct.unpack(">IB", blob[p:p + 5])
        if length < 5 or p + length > len(blob) - 4 or num in secs:
            raise ValueError(f"bad section {num} at {p}")
        secs[num] = blob[p:p + length]
        p += length
    for need in (1, 3, 4, 5, 6, 7):
        if need not in secs:
            raise ValueError(f"missing section {need}")
    return secs


def grid_info(sec3):
    """Grid template 3.30 (Lambert conformal) parameters from section 3."""
    tmpl = struct.unpack(">H", sec3[12:14])[0]
    if tmpl != 30:
        raise ValueError(f"unsupported grid template {tmpl}")
    s = sec3

    def i4(o):
        return struct.unpack(">I", s[o:o + 4])[0]

    def lat(o):
        return _sm(i4(o), 32) / 1e6

    return {
        "npts": i4(6), "shape_of_earth": s[14], "nx": i4(30), "ny": i4(34),
        "la1": lat(38), "lo1": i4(42) / 1e6, "lad": lat(47), "lov": i4(51) / 1e6,
        "dx": i4(55) / 1e3, "dy": i4(59) / 1e3, "scan": s[64],
        "latin1": lat(65), "latin2": lat(69),
    }


def product_info(sec0, sec1, sec4):
    tmpl = struct.unpack(">H", sec4[7:9])[0]
    if tmpl != 0:
        raise ValueError(f"unsupported product template {tmpl}")
    year, month, day, hour, minute = struct.unpack(">HBBBB", sec1[12:18])
    unit = sec4[17]
    if unit != 1:
        raise ValueError(f"forecast time unit {unit} is not hours")
    scale = _sm(sec4[23], 8)
    value = struct.unpack(">I", sec4[24:28])[0]
    return {
        "discipline": sec0[6], "category": sec4[9], "number": sec4[10],
        "ref_time_utc": dt.datetime(year, month, day, hour, minute, tzinfo=UTC).isoformat(),
        "fh": struct.unpack(">I", sec4[18:22])[0], "surface_type": sec4[22],
        "surface_value": value / (10 ** scale) if sec4[22] != 255 else None,
    }


def unpack_values(sec5, sec6, sec7, upto):
    """Decoded field values 0..upto (inclusive) for data templates 5.0 and 5.3."""
    if sec6[5] != 255:
        raise ValueError("bitmap present; not supported")
    npts = struct.unpack(">I", sec5[5:9])[0]
    tmpl = struct.unpack(">H", sec5[9:11])[0]
    ref = struct.unpack(">f", sec5[11:15])[0]
    escale = _sm(struct.unpack(">H", sec5[15:17])[0], 16)
    dscale = _sm(struct.unpack(">H", sec5[17:19])[0], 16)
    nbits = sec5[19]
    upto = min(int(upto), npts - 1)
    data = sec7[5:]
    if tmpl == 0:
        if nbits == 0:
            ints = np.zeros(upto + 1, dtype=np.int64)
        else:
            ints = _bits(data, np.arange(upto + 1, dtype=np.int64) * nbits, nbits)
    elif tmpl == 3:
        ints = _unpack_complex(sec5, data, nbits, npts, upto)
    else:
        raise ValueError(f"unsupported data template {tmpl}")
    return (ref + ints.astype(np.float64) * (2.0 ** escale)) / (10.0 ** dscale)


def _unpack_complex(sec5, data, nbits, npts, upto):
    """Template 5.3: complex packing with spatial differencing (same arithmetic as NCEP g2clib)."""
    s = sec5
    missing_mgmt = s[22]
    if missing_mgmt != 0:
        raise ValueError(f"missing-value management {missing_mgmt} not supported")
    ng = struct.unpack(">I", s[31:35])[0]
    wref, wbits = s[35], s[36]
    lref = struct.unpack(">I", s[37:41])[0]
    lincr = s[41]
    llast = struct.unpack(">I", s[42:46])[0]
    lbits = s[46]
    order = s[47]
    nd = s[48] * 8
    if order not in (1, 2) or nd == 0:
        raise ValueError(f"unsupported spatial differencing order {order} / octets {nd // 8}")
    pos = 0
    firsts = []
    for _ in range(order):
        firsts.append(_sm(_scalar_bits(data, pos, nd), nd))
        pos += nd
    minsd = _sm(_scalar_bits(data, pos, nd), nd)
    pos += nd

    def align(p):
        return (p + 7) // 8 * 8

    pos = align(pos)
    gref = _bits(data, pos + np.arange(ng, dtype=np.int64) * nbits, nbits)
    pos = align(pos + ng * nbits)
    gwidth = _bits(data, pos + np.arange(ng, dtype=np.int64) * wbits, wbits) + wref
    pos = align(pos + ng * wbits)
    glen = _bits(data, pos + np.arange(ng, dtype=np.int64) * lbits, lbits) * lincr + lref
    glen[-1] = llast
    pos = align(pos + ng * lbits)
    if int(glen.sum()) != npts:
        raise ValueError(f"group lengths sum {int(glen.sum())} != {npts}")
    # Only the groups holding values 0..upto are needed (spatial differencing integrates forward).
    first_of = np.concatenate([[0], np.cumsum(glen)[:-1]])
    last_group = int(np.searchsorted(first_of, upto, side="right")) - 1
    gl = glen[: last_group + 1]
    gw = gwidth[: last_group + 1]
    gstart_bits = pos + np.concatenate([[0], np.cumsum(gl * gw)[:-1]])
    owner = np.repeat(np.arange(last_group + 1), gl)[: upto + 1]
    within = np.arange(upto + 1, dtype=np.int64) - first_of[owner]
    width = gw[owner]
    ints = gref[owner] + _bits(data, gstart_bits[owner] + within * width, width)
    out = ints.astype(np.int64)
    if order == 1:
        out[0] = firsts[0]
        out[1:] = firsts[0] + np.cumsum(out[1:] + minsd)
    else:
        out[0] = firsts[0]
        if upto >= 1:
            out[1] = firsts[1]
            if upto >= 2:
                diff = (firsts[1] - firsts[0]) + np.cumsum(out[2:] + minsd)
                out[2:] = firsts[1] + np.cumsum(diff)
    return out


def decode_message(blob):
    """Section metadata for one GRIB2 message (no values)."""
    secs = parse_sections(blob)
    meta = product_info(secs[0], secs[1], secs[4])
    meta["grid"] = grid_info(secs[3])
    meta["data_template"] = struct.unpack(">H", secs[5][9:11])[0]
    return secs, meta


def check_hrrr_grid(grid):
    for key in ("nx", "ny", "scan"):
        if grid[key] != HRRR_GRID[key]:
            raise ValueError(f"grid {key} {grid[key]} != HRRR {HRRR_GRID[key]}")
    for key in ("la1", "lo1", "lov", "latin1", "latin2", "dx", "dy"):
        if abs(grid[key] - HRRR_GRID[key]) > 1e-3:
            raise ValueError(f"grid {key} {grid[key]} != HRRR {HRRR_GRID[key]}")
    if grid["shape_of_earth"] != 6:
        raise ValueError(f"shape of earth {grid['shape_of_earth']} is not the 6371229 m sphere")


# --------------------------------------------------------------------------- grid geometry
def lcc_xy(lat, lon, grid=HRRR_GRID):
    """Spherical Lambert conformal forward projection (metres) for grid template 3.30."""
    r = grid["radius"]
    p1, p2 = math.radians(grid["latin1"]), math.radians(grid["latin2"])
    if abs(p1 - p2) < 1e-12:
        n = math.sin(p1)
    else:
        n = math.log(math.cos(p1) / math.cos(p2)) / math.log(
            math.tan(math.pi / 4 + p2 / 2) / math.tan(math.pi / 4 + p1 / 2))
    f = math.cos(p1) * math.tan(math.pi / 4 + p1 / 2) ** n / n
    rho = r * f / math.tan(math.pi / 4 + math.radians(lat) / 2) ** n
    dlon = ((lon - grid["lov"] + 180.0) % 360.0) - 180.0
    theta = n * math.radians(dlon)
    return rho * math.sin(theta), -rho * math.cos(theta)


def station_cell(lat, lon, grid=HRRR_GRID):
    """Nearest grid (i, j, flat index) and fractional position; i east, j north from (la1, lo1)."""
    x0, y0 = lcc_xy(grid["la1"], grid["lo1"], grid)
    x, y = lcc_xy(lat, lon, grid)
    fi, fj = (x - x0) / grid["dx"], (y - y0) / grid["dy"]
    i, j = int(round(fi)), int(round(fj))
    inside = 1 <= i < grid["nx"] - 1 and 1 <= j < grid["ny"] - 1
    return {"i": i, "j": j, "fi": fi, "fj": fj, "flat": j * grid["nx"] + i, "inside": inside,
            "offset_km": math.hypot(fi - i, fj - j) * grid["dx"] / 1000.0}


def neighbourhood(cell, grid=HRRR_GRID):
    """Flat indices of the 3x3 block around the nearest point, row-major south to north."""
    return [(cell["j"] + dj) * grid["nx"] + cell["i"] + di for dj in (-1, 0, 1) for di in (-1, 0, 1)]


def point_values(blob, cells, expect):
    """Decode one message and return (meta, {station: {nearest, 3x3}}); validates identity."""
    secs, meta = decode_message(blob)
    check_hrrr_grid(meta["grid"])
    disc, cat, num, surf, sval = expect["param"]
    got = (meta["discipline"], meta["category"], meta["number"], meta["surface_type"])
    if got != (disc, cat, num, surf) or (sval is not None and meta["surface_value"] != sval):
        raise ValueError(f"message identity {got}/{meta['surface_value']} != {expect['param']}")
    if meta["ref_time_utc"] != expect["cycle_utc"] or meta["fh"] != expect["fh"]:
        raise ValueError(f"message time {meta['ref_time_utc']} f{meta['fh']} != expected")
    upto = max(max(neighbourhood(c)) for c in cells.values())
    vals = unpack_values(secs[5], secs[6], secs[7], upto)
    out = {}
    for st, c in cells.items():
        block = [float(vals[k]) for k in neighbourhood(c)]
        out[st] = {"nearest": float(vals[c["flat"]]), "block3x3": block}
    return meta, out


# --------------------------------------------------------------------------- idx and listing
def parse_idx(text):
    """[(byte offset, record text)] in file order from a wgrib2-style .idx sidecar."""
    rows = []
    for line in text.strip().splitlines():
        parts = line.split(":")
        if len(parts) < 6:
            raise ValueError(f"bad idx line {line!r}")
        rows.append((int(parts[1]), ":".join(parts[3:])))
    if [r[0] for r in rows] != sorted(r[0] for r in rows):
        raise ValueError("idx offsets are not increasing")
    return rows


def find_range(idx_rows, key, object_size):
    """Inclusive (start, end) of the single message whose idx record starts with ``key + ':'``."""
    hits = [k for k, (_, rec) in enumerate(idx_rows) if rec.startswith(key + ":")]
    if len(hits) != 1:
        raise LookupError(f"{key!r}: {len(hits)} idx records")
    k = hits[0]
    start = idx_rows[k][0]
    end = (idx_rows[k + 1][0] if k + 1 < len(idx_rows) else object_size) - 1
    if end <= start:
        raise ValueError(f"empty range for {key!r}")
    return start, end, idx_rows[k][1]


def parse_listing(xml_bytes):
    """ListObjectsV2 page -> ({key: {last_modified, size, etag}}, next continuation token)."""
    root = ET.fromstring(xml_bytes)
    ns = {"s": root.tag.split("}")[0].strip("{")} if root.tag.startswith("{") else {"s": ""}
    q = (lambda t: f"s:{t}") if ns["s"] else (lambda t: t)
    out = {}
    for c in root.findall(q("Contents"), ns):
        out[c.find(q("Key"), ns).text] = {
            "last_modified": c.find(q("LastModified"), ns).text,
            "size": int(c.find(q("Size"), ns).text),
            "etag": c.find(q("ETag"), ns).text,
        }
    trunc = root.find(q("IsTruncated"), ns)
    token = root.find(q("NextContinuationToken"), ns)
    more = trunc is not None and trunc.text == "true"
    return out, (token.text if more and token is not None else None)


def cycle_prefix(cycle):
    return f"hrrr.{cycle:%Y%m%d}/conus/hrrr.t{cycle:%H}z.wrfsfcf"


def grib_key(cycle, fh):
    return f"{cycle_prefix(cycle)}{fh:02d}.grib2"


def parse_s3_time(text):
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


def cycle_availability(listing, cycle, max_fh=MAX_FH):
    """{fh: available_utc} where available = max(LastModified of .grib2, of .idx)."""
    out = {}
    for fh in range(0, max_fh + 1):
        g = listing.get(grib_key(cycle, fh))
        i = listing.get(grib_key(cycle, fh) + ".idx")
        if g and i:
            out[fh] = max(parse_s3_time(g["last_modified"]), parse_s3_time(i["last_modified"]))
    return out


# --------------------------------------------------------------------------- point-in-time plan
def snapshot_utc(day, tz, hour):
    return dt.datetime(day.year, day.month, day.day, hour, tzinfo=ZoneInfo(tz)).astimezone(UTC)


def needed_fhs(cycle, snapshot, window_end, max_fh=MAX_FH):
    """Forecast hours valid in [snapshot, window_end], capped at ``max_fh`` (may be truncated)."""
    lo = math.ceil((snapshot - cycle).total_seconds() / 3600.0)
    hi = math.floor((window_end - cycle).total_seconds() / 3600.0)
    hi_cap = min(hi, max_fh)
    return list(range(max(lo, 0), hi_cap + 1)), hi > max_fh


def candidate_cycles(snapshot, stride, lookback=4):
    """Newest cycles on the stride grid at or before the snapshot hour, newest first."""
    c = snapshot.replace(minute=0, second=0, microsecond=0)
    out = []
    while len(out) < lookback:
        if c.hour % stride == 0:
            out.append(c)
        c -= dt.timedelta(hours=1)
    return out


def select_cycle(snapshot, window_end, availability, stride, margin, max_fh=MAX_FH, lookback=4):
    """Newest cycle whose every needed fh was published at least ``margin`` before the snapshot.

    ``availability`` maps cycle datetime -> {fh: available_utc}. Returns a selection dict or one
    with ``cycle_utc`` None when no candidate qualifies (the row is then absent, never imputed).
    """
    for depth, cycle in enumerate(candidate_cycles(snapshot, stride, lookback)):
        fhs, truncated = needed_fhs(cycle, snapshot, window_end, max_fh)
        if not fhs:
            continue
        avail = availability.get(cycle, {})
        if all(fh in avail and avail[fh] + margin <= snapshot for fh in fhs):
            return {
                "cycle_utc": cycle.isoformat(), "fhs": fhs, "depth": depth,
                "window_truncated_at_f18": truncated,
                "latest_available_utc": max(avail[fh] for fh in fhs).isoformat(),
            }
    return {"cycle_utc": None, "fhs": [], "depth": None, "window_truncated_at_f18": None,
            "latest_available_utc": None}


def plan_day(day, stations, hours, valid_end_local, stride, margin, availability, max_fh=MAX_FH, lookback=4):
    """Per (station, hour) selections and the union of (cycle, fh) messages they need."""
    selections, messages = [], set()
    for st, meta in stations.items():
        tz = meta["tz"]
        end = (dt.datetime(day.year, day.month, day.day, tzinfo=ZoneInfo(tz))
               + dt.timedelta(hours=valid_end_local)).astimezone(UTC)
        for h in hours:
            t = snapshot_utc(day, tz, h)
            sel = select_cycle(t, end, availability, stride, margin, max_fh, lookback)
            selections.append({"local_date": day.isoformat(), "station": st, "hour_local": h,
                               "snapshot_utc": t.isoformat(), **sel})
            if sel["cycle_utc"]:
                c = dt.datetime.fromisoformat(sel["cycle_utc"])
                messages.update((c, fh) for fh in sel["fhs"])
    return selections, sorted(messages)


def cycles_to_list(day, stations, hours, stride, lookback=4):
    out = set()
    for meta in stations.values():
        for h in hours:
            out.update(candidate_cycles(snapshot_utc(day, meta["tz"], h), stride, lookback))
    return sorted(out)


def season_dates(years, months, seed, first=None, last=None):
    """Dates of ``months`` x ``years`` inside [first, last], seeded-shuffled; refuses > LAST_ALLOWED."""
    days = []
    for y in years:
        for m in months:
            d = dt.date(y, m, 1)
            while d.month == m:
                if (first and d < first) or (last and d > last):
                    d += dt.timedelta(days=1)
                    continue
                if d > LAST_ALLOWED:
                    raise SystemExit(f"refusing date after {LAST_ALLOWED}: {d}")
                days.append(d)
                d += dt.timedelta(days=1)
    # Seeded shuffle: if the byte cap stops the run, the missing dates are spread over all years.
    random.Random(seed).shuffle(days)
    return days


# --------------------------------------------------------------------------- network
class Fetcher:
    """Serial, polite HTTPS client with exponential backoff and a hard byte cap."""

    def __init__(self, cap_bytes, used_bytes=0, pause=0.05, tries=7, session=None):
        if session is None:
            import requests

            session = requests.Session()
            session.headers["User-Agent"] = "weather-research-l13-hrrr-point/1 (serial; free NOAA open data)"
        self.s = session
        self.cap = cap_bytes
        self.used = used_bytes
        self.pause = pause
        self.tries = tries
        self.requests = 0

    def get(self, url, headers=None, params=None, expect=(200,)):
        if self.used >= self.cap:
            raise CapReached(self.used)
        delay = 2.0
        last = None
        for _ in range(self.tries):
            try:
                t0 = time.time()
                r = self.s.get(url, headers=headers or {}, params=params, timeout=90)
                r.elapsed_s = time.time() - t0
                self.requests += 1
                self.used += len(r.content)
                time.sleep(self.pause)
                if r.status_code in expect or r.status_code in (404, 412):
                    return r
                last = f"HTTP {r.status_code}"
            except Exception as exc:  # network errors are retried, never swallowed at the end
                last = f"{type(exc).__name__}: {exc}"
            time.sleep(delay)
            delay = min(delay * 2, 300)
        raise RuntimeError(f"giving up on {url}: {last}")

    def list_prefix(self, prefix):
        out, token = {}, None
        while True:
            params = {"list-type": "2", "prefix": prefix}
            if token:
                params["continuation-token"] = token
            r = self.get(BUCKET + "/", params=params)
            if r.status_code != 200:
                raise RuntimeError(f"listing {prefix}: HTTP {r.status_code}")
            page, token = parse_listing(r.content)
            out.update(page)
            if not token:
                return out


class CapReached(Exception):
    pass


# --------------------------------------------------------------------------- driver
def registry_stations():
    """Settlement stations of the built-in markets (lat/lon/tz) from the market registry."""
    src = Path(__file__).resolve().parents[2] / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from weather.market.market_registry import all_specs

    out = {}
    for s in all_specs():
        if getattr(s, "icao", None):
            out[s.icao] = {"lat": float(s.lat), "lon": float(s.lon), "tz": s.timezone, "market": s.id}
    return dict(sorted(out.items()))


def free_bytes(path):
    return shutil.disk_usage(path).free


def write_json_atomic(path, obj):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def append_jsonl(path, rec):
    with Path(path).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass  # torn last line after a crash: that unit is redone
    return rows


def fetch_message(f, cycle, fh, var, listing, cells, idx_cache):
    """Range-read and decode one message; returns a manifest record (status ok or a failure)."""
    key = grib_key(cycle, fh)
    url = f"{BUCKET}/{key}"
    obj, idx_obj = listing.get(key), listing.get(key + ".idx")
    rec = {"key": key, "var": var, "cycle_utc": cycle.isoformat(), "fh": fh,
           "valid_utc": (cycle + dt.timedelta(hours=fh)).isoformat()}
    if not obj or not idx_obj:
        return {**rec, "status": "missing_object"}
    if key not in idx_cache:
        ri = f.get(url + ".idx", headers={"If-Match": idx_obj["etag"]})
        if ri.status_code != 200:
            return {**rec, "status": f"idx_http_{ri.status_code}"}
        idx_cache[key] = (ri.text, hashlib.sha256(ri.content).hexdigest(), len(ri.content))
    idx_text, idx_sha, idx_bytes = idx_cache[key]
    start, end, record = find_range(parse_idx(idx_text), var, obj["size"])
    r = f.get(url, headers={"Range": f"bytes={start}-{end}", "If-Match": obj["etag"]}, expect=(206,))
    if r.status_code != 206:
        return {**rec, "status": f"grib_http_{r.status_code}"}
    blob = r.content
    if len(blob) != end - start + 1:
        return {**rec, "status": "short_read", "got": len(blob)}
    expect = {"param": VARIABLES[var], "cycle_utc": cycle.isoformat(), "fh": fh}
    meta, points = point_values(blob, cells, expect)
    return {
        **rec, "status": "ok", "url": url, "range": f"bytes={start}-{end}", "idx_record": record,
        "msg_bytes": len(blob), "msg_sha256": hashlib.sha256(blob).hexdigest(),
        "grib_last_modified": obj["last_modified"], "grib_etag": obj["etag"], "grib_size": obj["size"],
        "idx_last_modified": idx_obj["last_modified"], "idx_sha256": idx_sha, "idx_bytes": idx_bytes,
        "data_template": meta["data_template"], "units": UNITS[var],
        "points": points, "elapsed_s": round(r.elapsed_s, 3),
    }


def run(args, session=None):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stations = registry_stations()
    if args.stations:
        stations = {k: v for k, v in stations.items() if k in set(args.stations.split(","))}
    cells = {st: station_cell(m["lat"], m["lon"]) for st, m in stations.items()}
    outside = [st for st, c in cells.items() if not c["inside"]]
    if outside:
        raise SystemExit(f"stations outside the HRRR grid: {outside}")
    write_json_atomic(out / "stations.json", {st: {**stations[st], **cells[st]} for st in stations})
    hours = list(range(args.first_hour, args.last_hour + 1))
    if args.max_fh > MAX_FH and (args.cycle_stride % 6 or args.max_fh > 48):
        raise SystemExit("--max-fh above 18 needs synoptic cycles (--cycle-stride 6) and at most 48")
    margin = dt.timedelta(minutes=args.margin_minutes)
    variables = args.variables.split(",")
    days = season_dates([int(y) for y in args.years.split(",")], [int(m) for m in args.months.split(",")], args.seed,
                        _date_arg(args.first_date), _date_arg(args.last_date))
    if args.limit_days:
        days = days[: args.limit_days]
    manifest, selections_path = out / "manifest.jsonl", out / "selections.jsonl"
    done_msgs = {(r["key"], r["var"]) for r in read_jsonl(manifest) if r.get("status") == "ok"}
    done_days = {r["local_date"] for r in read_jsonl(out / "days.jsonl")}
    counters_path = out / "counters.json"
    counters = json.loads(counters_path.read_text()) if counters_path.exists() else {"bytes": 0, "requests": 0}
    f = Fetcher(int(args.cap_gb * GIB), used_bytes=counters["bytes"], pause=args.pause, session=session)
    status = {"state": "running", "days_total": len(days), "days_done": len(done_days & {d.isoformat() for d in days}),
              "planned_messages_estimate": args.planned_messages, "pid": os.getpid(),
              "started_local": dt.datetime.now().isoformat(timespec="seconds"), "config": vars(args)}

    def flush(state=None, **extra):
        counters.update(bytes=f.used, requests=counters.get("requests_base", 0) + f.requests)
        write_json_atomic(counters_path, {**counters})
        status.update(extra, state=state or status["state"], bytes_downloaded=f.used,
                      gb_downloaded=round(f.used / GIB, 3), messages_ok=len(done_msgs),
                      updated_local=dt.datetime.now().isoformat(timespec="seconds"))
        if args.planned_messages:
            status["fraction_done"] = round(len(done_msgs) / (args.planned_messages * len(variables)), 4)
        write_json_atomic(out / "status.json", status)

    counters["requests_base"] = counters.get("requests", 0)
    try:
        for day in days:
            if day.isoformat() in done_days:
                continue
            while True:
                if Path(args.stop_file).exists():
                    flush("stopped_by_file")
                    return 0
                if free_bytes(args.disk_root) < args.min_free_gb * GIB:
                    flush("paused_low_disk", free_gb=round(free_bytes(args.disk_root) / GIB, 1))
                    time.sleep(300)
                    continue
                break
            listing, availability = {}, {}
            for cycle in cycles_to_list(day, stations, hours, args.cycle_stride, args.lookback):
                page = f.list_prefix(cycle_prefix(cycle))
                listing.update(page)
                availability[cycle] = cycle_availability(page, cycle, args.max_fh)
            sels, msgs = plan_day(day, stations, hours, args.valid_end_local, args.cycle_stride, margin, availability,
                                  args.max_fh, args.lookback)
            idx_cache, failures = {}, 0
            for cycle, fh in msgs:
                for var in variables:
                    if (grib_key(cycle, fh), var) in done_msgs:
                        continue
                    try:
                        rec = fetch_message(f, cycle, fh, var, listing, cells, idx_cache)
                    except (ValueError, LookupError) as exc:  # one bad message: record, never impute
                        rec = {"key": grib_key(cycle, fh), "var": var, "cycle_utc": cycle.isoformat(),
                               "fh": fh, "status": "decode_error", "error": f"{type(exc).__name__}: {exc}"}
                    rec["local_dates"] = [day.isoformat()]
                    append_jsonl(manifest, rec)
                    if rec["status"] == "ok":
                        done_msgs.add((rec["key"], var))
                    else:
                        failures += 1
            for s in sels:
                append_jsonl(selections_path, s)
            append_jsonl(out / "days.jsonl", {
                "local_date": day.isoformat(), "messages": len(msgs) * len(variables), "failures": failures,
                "cycles_listed": len(availability), "no_cycle_rows": sum(1 for s in sels if not s["cycle_utc"]),
                "finished_local": dt.datetime.now().isoformat(timespec="seconds")})
            done_days.add(day.isoformat())
            status["days_done"] += 1
            flush()
    except CapReached:
        flush("cap_reached")
        return 0
    except Exception as exc:
        flush("failed", error=f"{type(exc).__name__}: {exc}")
        raise
    flush("complete")
    return 0


def probe(args):
    """~N timed range reads of random (date, cycle, fh) TMP messages; prints a JSON summary."""
    rng = random.Random(args.seed)
    stations = registry_stations()
    cells = {st: station_cell(m["lat"], m["lon"]) for st, m in stations.items()}
    f = Fetcher(int(args.cap_gb * GIB))
    days = season_dates([int(y) for y in args.years.split(",")], [int(m) for m in args.months.split(",")], args.seed)
    rows = []
    while len(rows) < args.probe:
        d = rng.choice(days)
        cycle = dt.datetime(d.year, d.month, d.day, rng.choice(range(9, 22)), tzinfo=UTC)
        page = f.list_prefix(cycle_prefix(cycle))
        for fh in rng.sample(range(2, MAX_FH + 1), 2):
            t0 = time.time()
            rec = fetch_message(f, cycle, fh, "TMP:2 m above ground", page, cells, {})
            rec["wall_s"] = round(time.time() - t0, 3)
            av = cycle_availability(page, cycle).get(fh)
            rec["latency_min"] = round((av - cycle).total_seconds() / 60, 1) if av else None
            rows.append(rec)
    ok = [r for r in rows if r["status"] == "ok"]
    summary = {
        "n": len(rows), "ok": len(ok), "requests": f.requests, "bytes_total": f.used,
        "msg_bytes_mean": float(np.mean([r["msg_bytes"] for r in ok])),
        "msg_bytes_min": min(r["msg_bytes"] for r in ok), "msg_bytes_max": max(r["msg_bytes"] for r in ok),
        "grib_get_s_median": float(np.median([r["elapsed_s"] for r in ok])),
        "grib_get_s_p90": float(np.percentile([r["elapsed_s"] for r in ok], 90)),
        "wall_s_per_message_median": float(np.median([r["wall_s"] for r in ok])),
        "wall_s_per_message_mean": float(np.mean([r["wall_s"] for r in ok])),
        "latency_min_by_fh": sorted({(r["fh"], r["latency_min"]) for r in ok}),
    }
    Path(args.out).mkdir(parents=True, exist_ok=True)
    (Path(args.out) / "probe_rows.jsonl").write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n")
    write_json_atomic(Path(args.out) / "probe_summary.json", summary)
    print(json.dumps(summary, indent=1, default=str))
    return 0


def _date_arg(text):
    return dt.date.fromisoformat(text) if text else None


def main(argv=None, session=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=r"C:\t\l13\hrrr")
    ap.add_argument("--years", default="2021,2022,2023,2024,2025")
    ap.add_argument("--months", default="8,9,10,11,12")
    ap.add_argument("--stations", help="comma list; default: the market registry's settlement stations")
    ap.add_argument("--variables", default="TMP:2 m above ground,TCDC:entire atmosphere")
    ap.add_argument("--first-hour", type=int, default=13, help="first local snapshot hour")
    ap.add_argument("--last-hour", type=int, default=16, help="last local snapshot hour")
    ap.add_argument("--valid-end-local", type=int, default=17, help="last valid local hour of the window")
    ap.add_argument("--cycle-stride", type=int, default=1, help="use cycles whose UTC hour is a multiple")
    ap.add_argument("--max-fh", type=int, default=MAX_FH, help="18; 48 only with synoptic cycles (stride 6)")
    ap.add_argument("--lookback", type=int, default=4, help="candidate cycles tried per snapshot")
    ap.add_argument("--margin-minutes", type=int, default=10, help="poll margin after LastModified")
    ap.add_argument("--cap-gb", type=float, default=60.0)
    ap.add_argument("--min-free-gb", type=float, default=60.0)
    ap.add_argument("--disk-root", default="C:\\")
    ap.add_argument("--stop-file", default=r"C:\t\l13\hrrr\STOP")
    ap.add_argument("--seed", type=int, default=20261025)
    ap.add_argument("--first-date", default="", help="ISO date; skip earlier dates")
    ap.add_argument("--last-date", default="", help="ISO date; skip later dates (still refused after 2026-09-29)")
    ap.add_argument("--limit-days", type=int, default=0)
    ap.add_argument("--planned-messages", type=int, default=0, help="for status fraction only")
    ap.add_argument("--probe", type=int, default=0, help="run N timed probe reads instead of the fetch")
    ap.add_argument("--pause", type=float, default=0.05, help="seconds between requests")
    args = ap.parse_args(argv)
    return probe(args) if args.probe else run(args, session=session)


if __name__ == "__main__":
    raise SystemExit(main())
