"""Lane L11 rung R-O: point-in-time GEFS member 2 m temperature at the US settlement stations (research corpus).

Free official NOAA GEFS v12 on the AWS Open Data bucket ``noaa-gefs-pds`` (anonymous HTTPS). For each target date D
this reads, from the 06Z cycle of D, product ``pgrb2sp25`` (0.25 deg), members ``gec00`` and ``gep01..gep30``,
forecast hours f006..f024 every 3 h, the single ``TMP:2 m above ground`` message located through the ``.idx`` sidecar
and fetched with an HTTP Range request. Messages are decoded in memory by the pure-numpy GRIB2 decoder below (grid
template 3.0, product template 4.1, data template 5.3; the bit arithmetic is lane L13's ``hrrr_point_fetch`` decoder)
and only the four surrounding grid points and the bilinear value per station are kept, with the message sha256, the
byte range, the ETag and both S3 ``LastModified`` values. Raw GRIB is never written, except in ``--probe`` mode, which
keeps one date's messages for the eccodes bit-exact check (``gefs_eccodes_check.py``, run in a scratch venv).

Rule: ``docs/research/gefs-members-l11-2026-10-26/rule_rn.md`` (sha256 a9ca45f0..., rung R-O). Research / acquisition
only: no production path imports this module, nothing is served, and it refuses any date after ``LAST_ALLOWED``.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import shutil
import struct
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

BUCKET = "https://noaa-gefs-pds.s3.amazonaws.com"
LAST_ALLOWED = dt.date(2026, 9, 29)
UTC = dt.timezone.utc
CYCLE_HOUR = 6
FHS = (6, 9, 12, 15, 18, 21, 24)
MEMBERS = ("gec00",) + tuple(f"gep{k:02d}" for k in range(1, 31))
VAR = "TMP:2 m above ground"
MARKETS = ("atlanta", "austin", "chicago", "dallas", "denver", "houston", "los-angeles", "miami", "nyc",
           "san-francisco", "seattle")
GEFS_GRID = {"ni": 1440, "nj": 721, "la1": 90.0, "lo1": 0.0, "la2": -90.0, "lo2": 359.75, "di": 0.25, "dj": 0.25}
# Products. The defaults (06Z of D, sp25, f006..f024) are R-O's pinned inputs. The 18Z D-1 ap5 pass (f018..f036) is
# lane L15's R-Q scope, approved by the coordinator 2026-10-25 and written to a separate corpus.
PRODUCTS = {
    "sp25": {"dir": "pgrb2sp25", "stem": "pgrb2s.0p25", "grid": GEFS_GRID},
    "ap5": {"dir": "pgrb2ap5", "stem": "pgrb2a.0p50",
            "grid": {"ni": 720, "nj": 361, "la1": 90.0, "lo1": 0.0, "la2": -90.0, "lo2": 359.5, "di": 0.5, "dj": 0.5}},
}
PRODUCT = "sp25"
CYCLE_DAY_OFFSET = 0  # cycle date = target date + offset (days)


def configure(cycle_hour=6, product="sp25", fhs=FHS, cycle_day_offset=0):
    """Select the cycle, product and steps (module-wide; defaults are R-O's pinned 06Z sp25 f006..f024)."""
    global CYCLE_HOUR, FHS, PRODUCT, CYCLE_DAY_OFFSET, GEFS_GRID
    if product not in PRODUCTS or cycle_hour not in (0, 6, 12, 18) or cycle_day_offset not in (0, -1):
        raise SystemExit(f"unsupported configuration {cycle_hour} {product} {cycle_day_offset}")
    if any(fh < 0 or fh % 3 for fh in fhs):
        raise SystemExit(f"unsupported steps {fhs}")
    CYCLE_HOUR, FHS, PRODUCT, CYCLE_DAY_OFFSET = int(cycle_hour), tuple(int(x) for x in fhs), product, cycle_day_offset
    GEFS_GRID = PRODUCTS[product]["grid"]


# --------------------------------------------------------------------------- GRIB2 decoding (L13 arithmetic)
def _sm(value, bits):
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
    """Grid template 3.0 (regular lat/lon) parameters."""
    tmpl = struct.unpack(">H", sec3[12:14])[0]
    if tmpl != 0:
        raise ValueError(f"unsupported grid template {tmpl}")
    s = sec3

    def i4(o):
        return struct.unpack(">I", s[o:o + 4])[0]

    basic, sub = i4(38), i4(42)
    if basic not in (0, 0xFFFFFFFF) or sub not in (0, 0xFFFFFFFF):
        raise ValueError("non-default basic angle / subdivisions")
    return {"npts": i4(6), "shape_of_earth": s[14], "ni": i4(30), "nj": i4(34),
            "la1": _sm(i4(46), 32) / 1e6, "lo1": i4(50) / 1e6, "la2": _sm(i4(55), 32) / 1e6,
            "lo2": i4(59) / 1e6, "di": i4(63) / 1e6, "dj": i4(67) / 1e6, "scan": s[71]}


def check_gefs_grid(grid):
    for key in ("ni", "nj"):
        if grid[key] != GEFS_GRID[key]:
            raise ValueError(f"grid {key} {grid[key]} != {GEFS_GRID[key]}")
    for key in ("la1", "lo1", "la2", "lo2", "di", "dj"):
        if abs(grid[key] - GEFS_GRID[key]) > 1e-6:
            raise ValueError(f"grid {key} {grid[key]} != {GEFS_GRID[key]}")
    if grid["scan"] != 0:
        raise ValueError(f"scanning mode {grid['scan']} is not 0 (west->east, north->south, i fastest)")


def product_info(sec0, sec1, sec4):
    """Product template 4.1 (individual ensemble forecast at a point in time)."""
    tmpl = struct.unpack(">H", sec4[7:9])[0]
    if tmpl != 1:
        raise ValueError(f"unsupported product template {tmpl}")
    year, month, day, hour, minute = struct.unpack(">HBBBB", sec1[12:18])
    if sec4[17] != 1:
        raise ValueError(f"forecast time unit {sec4[17]} is not hours")
    scale = _sm(sec4[23], 8)
    value = struct.unpack(">I", sec4[24:28])[0]
    return {"discipline": sec0[6], "category": sec4[9], "number": sec4[10],
            "ref_time_utc": dt.datetime(year, month, day, hour, minute, tzinfo=UTC).isoformat(),
            "fh": struct.unpack(">I", sec4[18:22])[0], "surface_type": sec4[22],
            "surface_value": value / (10 ** scale) if sec4[22] != 255 else None,
            "ensemble_type": sec4[34], "perturbation": sec4[35], "ensemble_size": sec4[36]}


def _unpack_complex(sec5, data, nbits, npts):
    """Template 5.3: complex packing with spatial differencing (NCEP g2clib arithmetic), all points."""
    s = sec5
    if s[22] != 0:
        raise ValueError(f"missing-value management {s[22]} not supported")
    ng = struct.unpack(">I", s[31:35])[0]
    wref, wbits = s[35], s[36]
    lref = struct.unpack(">I", s[37:41])[0]
    lincr = s[41]
    llast = struct.unpack(">I", s[42:46])[0]
    lbits = s[46]
    order = s[47]
    nd = s[48] * 8
    if order not in (1, 2) or nd == 0:
        raise ValueError(f"unsupported spatial differencing order {order}")
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
    first_of = np.concatenate([[0], np.cumsum(glen)[:-1]])
    gstart_bits = pos + np.concatenate([[0], np.cumsum(glen * gwidth)[:-1]])
    owner = np.repeat(np.arange(ng), glen)
    within = np.arange(npts, dtype=np.int64) - first_of[owner]
    width = gwidth[owner]
    out = (gref[owner] + _bits(data, gstart_bits[owner] + within * width, width)).astype(np.int64)
    if order == 1:
        out[0] = firsts[0]
        out[1:] = firsts[0] + np.cumsum(out[1:] + minsd)
    else:
        out[0] = firsts[0]
        out[1] = firsts[1]
        diff = (firsts[1] - firsts[0]) + np.cumsum(out[2:] + minsd)
        out[2:] = firsts[1] + np.cumsum(diff)
    return out


def unpack_values(sec5, sec6, sec7):
    if sec6[5] != 255:
        raise ValueError("bitmap present; not supported")
    npts = struct.unpack(">I", sec5[5:9])[0]
    tmpl = struct.unpack(">H", sec5[9:11])[0]
    ref = struct.unpack(">f", sec5[11:15])[0]
    escale = _sm(struct.unpack(">H", sec5[15:17])[0], 16)
    dscale = _sm(struct.unpack(">H", sec5[17:19])[0], 16)
    nbits = sec5[19]
    if tmpl != 3:
        raise ValueError(f"unsupported data template {tmpl}")
    ints = _unpack_complex(sec5, sec7[5:], nbits, npts)
    # eccodes order: (x * 2^E + R) * 10^-D, multiplying by the reciprocal power (bit-exact vs eccodes 2.49)
    return (ints.astype(np.float64) * (2.0 ** escale) + ref) * (10.0 ** (-dscale))


def decode_field(blob):
    """(meta, values[nj, ni]) for one GEFS 0.25 deg message; fails closed on any template or grid mismatch."""
    secs = parse_sections(blob)
    meta = product_info(secs[0], secs[1], secs[4])
    grid = grid_info(secs[3])
    check_gefs_grid(grid)
    vals = unpack_values(secs[5], secs[6], secs[7])
    if vals.size != grid["ni"] * grid["nj"]:
        raise ValueError("value count != grid size")
    return meta, vals.reshape(grid["nj"], grid["ni"])


# --------------------------------------------------------------------------- station geometry
def station_corners(lat, lon):
    """The four surrounding grid points (j0, i0, j1, i1) and weights (wy, wx) for bilinear interpolation."""
    lonp = lon % 360.0
    fi = (lonp - GEFS_GRID["lo1"]) / GEFS_GRID["di"]
    fj = (GEFS_GRID["la1"] - lat) / GEFS_GRID["dj"]  # rows run north to south
    i0, j0 = int(math.floor(fi)), int(math.floor(fj))
    i1, j1 = (i0 + 1) % GEFS_GRID["ni"], j0 + 1
    if not (0 <= j0 and j1 < GEFS_GRID["nj"]):
        raise ValueError("station outside the latitude range")
    return {"j0": j0, "i0": i0, "j1": j1, "i1": i1, "wy": fj - j0, "wx": fi - i0}


def bilinear(field, c):
    v00, v01 = field[c["j0"], c["i0"]], field[c["j0"], c["i1"]]
    v10, v11 = field[c["j1"], c["i0"]], field[c["j1"], c["i1"]]
    top = v00 * (1 - c["wx"]) + v01 * c["wx"]
    bot = v10 * (1 - c["wx"]) + v11 * c["wx"]
    return float(top * (1 - c["wy"]) + bot * c["wy"]), [float(v00), float(v01), float(v10), float(v11)]


def registry_stations():
    src = Path(__file__).resolve().parents[2] / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from weather.market.market_registry import spec_for_id

    out = {}
    for m in MARKETS:
        s = spec_for_id(m)
        out[m] = {"lat": float(s.lat), "lon": float(s.lon), "tz": s.timezone}
    return out


# --------------------------------------------------------------------------- idx, listing, network
def parse_idx(text):
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
    root = ET.fromstring(xml_bytes)
    ns = root.tag.split("}")[0].strip("{") if root.tag.startswith("{") else ""
    q = (lambda t: f"{{{ns}}}{t}") if ns else (lambda t: t)
    out = {}
    for c in root.findall(q("Contents")):
        out[c.find(q("Key")).text] = {"last_modified": c.find(q("LastModified")).text,
                                      "size": int(c.find(q("Size")).text), "etag": c.find(q("ETag")).text}
    trunc = root.find(q("IsTruncated"))
    token = root.find(q("NextContinuationToken"))
    more = trunc is not None and trunc.text == "true"
    return out, (token.text if more and token is not None else None)


def cycle_prefix(day):
    return f"gefs.{day:%Y%m%d}/{CYCLE_HOUR:02d}/atmos/{PRODUCTS[PRODUCT]['dir']}/"


def grib_key(day, member, fh):
    return f"{cycle_prefix(day)}{member}.t{CYCLE_HOUR:02d}z.{PRODUCTS[PRODUCT]['stem']}.f{fh:03d}"


def parse_s3_time(text):
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


class Fetcher:
    """Serial HTTPS client with exponential backoff and a hard byte cap."""

    def __init__(self, cap_bytes, used_bytes=0, pause=0.02, tries=7, session=None):
        if session is None:
            import requests

            session = requests.Session()
            session.headers["User-Agent"] = "weather-research-l11-gefs-point/1 (serial; free NOAA open data)"
        self.s, self.cap, self.used, self.pause, self.tries, self.requests = session, cap_bytes, used_bytes, pause, tries, 0

    def get(self, url, headers=None, params=None, expect=(200,)):
        if self.used >= self.cap:
            raise CapReached(self.used)
        delay, last = 2.0, None
        for _ in range(self.tries):
            try:
                r = self.s.get(url, headers=headers or {}, params=params, timeout=90)
                self.requests += 1
                self.used += len(r.content)
                time.sleep(self.pause)
                if r.status_code in expect or r.status_code == 404:
                    return r
                last = f"HTTP {r.status_code}"
            except Exception as exc:  # retried; the final failure is raised
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


def append_jsonl(path, rec):
    with Path(path).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def done_dates(path):
    path = Path(path)
    if not path.exists():
        return set()
    out = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            if rec.get("kind") == "date_done":
                out.add(rec["date"])
    return out


# --------------------------------------------------------------------------- driver
def fetch_date(f, day, stations, corners, rows_path, raw_dir=None, members=MEMBERS):
    """All members x steps for one date. Appends one row per (member, fh) and a date_done record."""
    if day > LAST_ALLOWED:
        raise SystemExit(f"refusing date after {LAST_ALLOWED}: {day}")
    cday = day + dt.timedelta(days=CYCLE_DAY_OFFSET)
    listing = f.list_prefix(cycle_prefix(cday))
    cycle = dt.datetime(cday.year, cday.month, cday.day, CYCLE_HOUR, tzinfo=UTC)
    n_ok = n_missing = n_bytes = 0
    for member in members:
        for fh in FHS:
            key = grib_key(cday, member, fh)
            g, i = listing.get(key), listing.get(key + ".idx")
            base = {"kind": "message", "date": day.isoformat(), "member": member, "fh": fh, "key": key,
                    "cycle_utc": cycle.isoformat(), "valid_utc": (cycle + dt.timedelta(hours=fh)).isoformat(),
                    "product": PRODUCT, "cycle_hour": CYCLE_HOUR}
            if not g or not i:
                append_jsonl(rows_path, {**base, "status": "object_missing"})
                n_missing += 1
                continue
            r = f.get(f"{BUCKET}/{key}.idx")
            if r.status_code != 200:
                append_jsonl(rows_path, {**base, "status": f"idx_http_{r.status_code}"})
                n_missing += 1
                continue
            start, end, rec = find_range(parse_idx(r.text), VAR, g["size"])
            r = f.get(f"{BUCKET}/{key}", headers={"Range": f"bytes={start}-{end}"}, expect=(206,))
            if r.status_code != 206 or len(r.content) != end - start + 1:
                append_jsonl(rows_path, {**base, "status": f"range_http_{r.status_code}"})
                n_missing += 1
                continue
            blob = r.content
            n_bytes += len(blob)
            sha = hashlib.sha256(blob).hexdigest()
            if raw_dir is not None:
                (Path(raw_dir) / f"{cday:%Y%m%d}{CYCLE_HOUR:02d}_{PRODUCT}_{member}_f{fh:03d}.grib2").write_bytes(blob)
            try:
                meta, field = decode_field(blob)
                want_pert = 0 if member == "gec00" else int(member[3:])
                ident = (meta["discipline"], meta["category"], meta["number"], meta["surface_type"],
                         meta["surface_value"])
                if ident != (0, 0, 0, 103, 2.0):
                    raise ValueError(f"identity {ident}")
                if meta["ref_time_utc"] != cycle.isoformat() or meta["fh"] != fh:
                    raise ValueError(f"time {meta['ref_time_utc']} f{meta['fh']}")
                if meta["perturbation"] != want_pert:
                    raise ValueError(f"perturbation {meta['perturbation']} != {want_pert}")
            except Exception as exc:
                append_jsonl(rows_path, {**base, "status": "decode_error", "error": str(exc), "message_sha256": sha})
                n_missing += 1
                continue
            points = {}
            for m, c in corners.items():
                value, four = bilinear(field, c)
                points[m] = {"bilinear_k": value, "corners_k": four}
            append_jsonl(rows_path, {**base, "status": "ok", "message_sha256": sha, "range": [start, end],
                                     "idx_record": rec, "etag": g["etag"], "grib_last_modified": g["last_modified"],
                                     "idx_last_modified": i["last_modified"],
                                     "available_utc": max(parse_s3_time(g["last_modified"]),
                                                          parse_s3_time(i["last_modified"])).isoformat(),
                                     "ensemble_type": meta["ensemble_type"], "perturbation": meta["perturbation"],
                                     "points": points})
            n_ok += 1
    append_jsonl(rows_path, {"kind": "date_done", "date": day.isoformat(), "ok": n_ok, "missing": n_missing,
                             "bytes": n_bytes})
    return n_ok, n_missing, n_bytes


def date_list(spec):
    """'YYYY-MM-DD..YYYY-MM-DD' ranges joined by commas, or '@file' with one date per line."""
    if spec.startswith("@"):
        days = [dt.date.fromisoformat(x.strip()) for x in Path(spec[1:]).read_text().splitlines() if x.strip()]
    else:
        days = []
        for part in spec.split(","):
            a, _, b = part.partition("..")
            d0, d1 = dt.date.fromisoformat(a), dt.date.fromisoformat(b or a)
            while d0 <= d1:
                days.append(d0)
                d0 += dt.timedelta(days=1)
    for d in days:
        if d > LAST_ALLOWED:
            raise SystemExit(f"refusing date after {LAST_ALLOWED}: {d}")
    return sorted(set(days))


def main(argv=None, session=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dates", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cap-gb", type=float, default=55.0)
    ap.add_argument("--probe-raw-dir", default=None, help="probe only: keep raw messages for the eccodes check")
    ap.add_argument("--min-free-gb", type=float, default=20.0)
    ap.add_argument("--cycle-hour", type=int, default=6)
    ap.add_argument("--product", default="sp25", choices=sorted(PRODUCTS))
    ap.add_argument("--fhs", default="6,9,12,15,18,21,24")
    ap.add_argument("--cycle-day-offset", type=int, default=0, help="cycle date = target date + offset (0 or -1)")
    ap.add_argument("--members", default="", help="probe only: comma-separated member subset (default: all 31)")
    args = ap.parse_args(argv)
    configure(args.cycle_hour, args.product, tuple(int(x) for x in args.fhs.split(",")), args.cycle_day_offset)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    repo = Path(__file__).resolve().parents[2]
    if repo in out.resolve().parents or out.resolve() == repo:
        raise SystemExit("output must be outside the repository")
    raw_dir = None
    if args.probe_raw_dir:
        raw_dir = Path(args.probe_raw_dir)
        raw_dir.mkdir(parents=True, exist_ok=True)
    members = tuple(args.members.split(",")) if args.members else MEMBERS
    if any(m not in MEMBERS for m in members):
        raise SystemExit(f"unknown members {members}")
    if members != MEMBERS and not raw_dir:
        raise SystemExit("--members is for probes only (with --probe-raw-dir)")
    stations = registry_stations()
    corners = {m: station_corners(s["lat"], s["lon"]) for m, s in stations.items()}
    rows_path = out / "gefs_member_rows.jsonl"
    done = done_dates(rows_path)
    days = [d for d in date_list(args.dates) if d.isoformat() not in done]
    f = Fetcher(int(args.cap_gb * 1e9), session=session)
    t0 = time.time()
    for k, day in enumerate(days, 1):
        if shutil.disk_usage(out).free < args.min_free_gb * 1e9:
            raise SystemExit("free disk below the floor; stopping")
        ok, miss, nb = fetch_date(f, day, stations, corners, rows_path, raw_dir, members)
        print(f"[{k}/{len(days)}] {day} ok={ok} missing={miss} bytes={nb} total_gb={f.used / 1e9:.2f} "
              f"requests={f.requests} elapsed_s={time.time() - t0:.0f}", flush=True)
    manifest = {"schema": "l11_gefs_member_points/1", "rows_file": rows_path.name,
                "rows_sha256": hashlib.sha256(rows_path.read_bytes()).hexdigest(),
                "stations": stations, "corners": corners, "cycle_hour_utc": CYCLE_HOUR, "fhs": list(FHS),
                "product": PRODUCT, "product_dir": PRODUCTS[PRODUCT]["dir"], "grid": GEFS_GRID,
                "cycle_day_offset": CYCLE_DAY_OFFSET,
                "members": list(MEMBERS), "variable": VAR, "bucket": BUCKET,
                "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "bytes_this_run": f.used, "requests_this_run": f.requests}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
