"""Lane L13: ECMWF ENS open-data forward recorder: 50-member point 3-hour maximum 2 m temperature for the 12 markets.

Free official data from ``data.ecmwf.int/forecasts`` (ECMWF open data, CC-BY-4.0, anonymous HTTPS, no key, no
credentials). Design note: ``docs/research/ecmwf-ens-forward-recorder-2026-10-30.md``. Research / shadow only: nothing
imports this module, nothing is served, and no outcome, price or label is read.

* **What is fetched.** For each ENS cycle (default 00 and 12 UTC) and step (default 3..72 h by 3) the step's JSON-lines
  ``.index`` is read, then only the ``mx2t3`` message of each perturbed member is fetched with an HTTP byte range
  (about 0.3 MB each; the step file itself is about 100 MB and is never downloaded). The open-data ``ef`` file carries
  members 1-50; a control (``type cf``) is recorded too if it ever appears. ``--params mx2t3,2t`` adds instantaneous
  2 m temperature.
* **Decoding.** The messages are GRIB2 with CCSDS/AEC packing (data template 5.42). The decoder below is a
  pure-Python/numpy implementation of the CCSDS 121.0-B adaptive Rice decoder with the unit-delay preprocessor (no
  eccodes, libaec or other new package). Every RSI block is skipped cheaply; only the RSIs that hold a station's grid
  corners are fully decoded. Grid, product and packing templates are checked and anything else fails closed.
* **What is kept.** Point extractions only: the four surrounding 0.25 deg grid values, the bilinear value and the
  nearest value per station, member and step (``points.jsonl``). Raw GRIB is never written to disk.

Point in time by construction: every index and message row carries the URL, the model run time, the server
``Last-Modified`` and ETag, our fetch time and the sha256 of the bytes received; every point row repeats the run,
the message sha256, ``Last-Modified`` and our fetch time. Per run ``<out>/<YYYYMMDDHH>/`` holds ``index.jsonl``,
``points.jsonl`` and, once every slot is ok or closed missing, ``manifest.json`` pinning both files by sha256.
Missed slots close at ``run + CLOSE_AFTER`` (open data keeps about four days) and are appended to ``gaps.jsonl``.
Guards as the MOSMIX recorder: below-normal priority, throttle and hourly ceiling, a per-process byte cap, a pause
file, a STOP file, a single-instance lock, a free-disk floor and an output-size cap. Forward runs only.
"""
from __future__ import annotations

import argparse
import bisect
import datetime as dt
import hashlib
import json
import math
import os
import shutil
import struct
import sys
import time
import traceback
from collections import defaultdict
from email.utils import parsedate_to_datetime
from pathlib import Path

import numpy as np

UTC = dt.timezone.utc
SCHEMA = "ecmwf_ens_forward/1"
FORWARD_FIRST = dt.datetime(2026, 10, 31, 0, tzinfo=UTC)  # first run the recorder may ask for
BASE = "https://data.ecmwf.int/forecasts"
DEFAULT_CYCLES = (0, 12)
DEFAULT_STEPS = tuple(range(3, 73, 3))
DEFAULT_PARAMS = ("mx2t3",)
FIRST_TRY = dt.timedelta(hours=6)     # ENS 00z step files appear from about +6.7 h
CLOSE_AFTER = dt.timedelta(hours=72)  # open data keeps about four days; later slots close as missing
MAX_TRIES = 8

# market, icao, lat, lon (the market registry, weather.market.market_registry; the test checks them)
STATIONS = (
    ("toronto", "CYYZ", 43.6767, -79.6306),
    ("nyc", "KLGA", 40.7769, -73.874),
    ("atlanta", "KATL", 33.62972, -84.44223),
    ("austin", "KAUS", 30.1831, -97.68063),
    ("chicago", "KORD", 41.96017, -87.93161),
    ("dallas", "KDAL", 32.83836, -96.83584),
    ("denver", "KBKF", 39.713, -104.758),
    ("houston", "KHOU", 29.64582, -95.28214),
    ("los-angeles", "KLAX", 33.93817, -118.3866),
    ("miami", "KMIA", 25.78806, -80.31692),
    ("san-francisco", "KSFO", 37.61961, -122.36561),
    ("seattle", "KSEA", 47.44467, -122.31442),
)
GRID = {"ni": 1440, "nj": 721, "la1": 90.0, "lo1": 180.0, "di": 0.25, "dj": 0.25}
# param -> (discipline, category, number, product templates, statistical process or None)
PARAMS = {
    "mx2t3": (0, 0, 0, (11, 8), 2),  # temperature with statistical process 2 (maximum) over 3 h
    "2t": (0, 0, 0, (1, 0), None),
}


def _iso(t):
    return t.astimezone(UTC).isoformat()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------- CCSDS / AEC decoder (template 5.42)
AEC_DATA_SIGNED, AEC_DATA_3BYTE, AEC_DATA_MSB, AEC_DATA_PREPROCESS, AEC_RESTRICTED, AEC_PAD_RSI = 1, 2, 4, 8, 16, 32
ROS = 5
_SE_DIAG = []
for _k in range(13):
    _SE_DIAG.extend([_k] * (_k + 1))  # m -> k with k(k+1)/2 <= m < (k+1)(k+2)/2 (libaec SE_TABLE_SIZE 90)


class AecError(ValueError):
    pass


class _Bits:
    def __init__(self, data):
        self.data = bytes(data)
        self.nbits = len(self.data) * 8
        self.ones = np.flatnonzero(np.unpackbits(np.frombuffer(self.data, dtype=np.uint8))).tolist()

    def get(self, pos, n):
        if n == 0:
            return 0
        if pos + n > self.nbits:
            raise AecError("read past the end of the stream")
        b, off = pos >> 3, pos & 7
        nb = (off + n + 7) >> 3
        v = int.from_bytes(self.data[b:b + nb], "big")
        return (v >> (nb * 8 - off - n)) & ((1 << n) - 1)

    def fs_ends(self, pos, count):
        """Positions of the terminating 1 bits of ``count`` consecutive fundamental-sequence codes from ``pos``."""
        j = bisect.bisect_left(self.ones, pos)
        ends = self.ones[j:j + count]
        if len(ends) != count:
            raise AecError("fundamental sequence runs past the end of the stream")
        return ends


def _inverse_preprocess(mapped, bps):
    """Unit-delay predictor inverse (CCSDS 121.0-B section 4, unsigned): first value is the reference sample."""
    xmax = (1 << bps) - 1
    x = mapped[0]
    out = [x]
    for d in mapped[1:]:
        th = x if x <= xmax - x else xmax - x
        if d <= 2 * th:
            x = x - ((d + 1) >> 1) if d & 1 else x + (d >> 1)
        elif th == x:
            x = d
        else:
            x = xmax - d
        out.append(x)
    return out


def aec_decode(data, bps, block, rsi, flags, nsamples, wanted=None):
    """Decode an AEC stream. ``wanted`` (iterable of sample indexes) limits full decoding to the RSIs holding them
    and returns {index: value}; otherwise all samples are returned as an int64 array and the stream must be consumed
    to within one byte of its end."""
    if flags & (AEC_DATA_SIGNED | AEC_PAD_RSI | AEC_RESTRICTED):
        raise AecError(f"unsupported AEC flags {flags}")
    if not 1 <= bps <= 24 or block not in (8, 16, 32, 64) or rsi < 1:
        raise AecError(f"unsupported AEC parameters bps={bps} block={block} rsi={rsi}")
    pp = bool(flags & AEC_DATA_PREPROCESS)
    id_len = 5 if bps > 16 else 4 if bps > 8 else 3
    max_id = (1 << id_len) - 1
    bits = _Bits(data)
    rsi_n = rsi * block
    n_rsi = -(-nsamples // rsi_n)
    want_r = None
    if wanted is not None:
        wanted = sorted(set(int(i) for i in wanted))
        if wanted and (wanted[0] < 0 or wanted[-1] >= nsamples):
            raise AecError("wanted index out of range")
        want_r = {i // rsi_n for i in wanted}
        last_r = max(want_r) if want_r else -1
    full = np.zeros(nsamples, dtype=np.int64) if wanted is None else None
    found = {}
    pos = 0
    for r in range(n_rsi):
        if want_r is not None and r > last_r:
            break
        start = r * rsi_n
        count = min(nsamples, start + rsi_n) - start
        nblocks = -(-count // block)
        need = want_r is None or r in want_r
        mapped = []
        b = 0
        while b < nblocks:
            ref = pp and b == 0
            ident = bits.get(pos, id_len)
            pos += id_len
            if ident == 0:
                se = bits.get(pos, 1)
                pos += 1
                if ref:
                    refv = bits.get(pos, bps)
                    pos += bps
                if se == 0:  # zero block run
                    end = bits.fs_ends(pos, 1)[0]
                    zb = end - pos + 1
                    pos = end + 1
                    if zb == ROS:
                        zb = min(rsi - b, 64 - (b % 64))
                    elif zb > ROS:
                        zb -= 1
                    zb = min(zb, nblocks - b)
                    if need:
                        if ref:
                            mapped.append(refv)
                        mapped.extend([0] * (zb * block - (1 if ref else 0)))
                    b += zb
                else:  # second extension
                    i = 1 if ref else 0
                    codes = (block - i + 1) // 2
                    ends = bits.fs_ends(pos, codes)
                    if need:
                        if ref:
                            mapped.append(refv)
                        prev = pos - 1
                        for e in ends:
                            m = e - prev - 1
                            prev = e
                            if m >= len(_SE_DIAG):
                                raise AecError("second-extension code out of range")
                            k = _SE_DIAG[m]
                            d1 = m - k * (k + 1) // 2
                            if i % 2 == 0:
                                mapped.append(k - d1)
                                i += 1
                            mapped.append(d1)
                            i += 1
                    pos = ends[-1] + 1
                    b += 1
            elif ident == max_id:  # uncompressed block
                if need:
                    mapped.extend(bits.get(pos + bps * j, bps) for j in range(block))
                pos += bps * block
                b += 1
            else:  # split sample, k = id - 1
                k = ident - 1
                if ref:
                    refv = bits.get(pos, bps)
                    pos += bps
                cnt = block - (1 if ref else 0)
                ends = bits.fs_ends(pos, cnt)
                if need:
                    hi = [ends[0] - pos] + [ends[t] - ends[t - 1] - 1 for t in range(1, cnt)]
                pos = ends[-1] + 1
                if need:
                    if ref:
                        mapped.append(refv)
                    if k:
                        mapped.extend((hi[t] << k) | bits.get(pos + k * t, k) for t in range(cnt))
                    else:
                        mapped.extend(hi)
                pos += k * cnt
                b += 1
        if need:
            vals = _inverse_preprocess(mapped[:count], bps) if pp else mapped[:count]
            if full is not None:
                full[start:start + count] = vals
            else:
                for i in wanted:
                    if start <= i < start + count:
                        found[i] = vals[i - start]
    if full is not None:
        if pos > bits.nbits or bits.nbits - pos >= 8:
            raise AecError(f"stream length mismatch: used {pos} of {bits.nbits} bits")
        return full
    if len(found) != len(wanted):
        raise AecError("wanted samples not decoded")
    return found


# --------------------------------------------------------------------------- GRIB2 (one message)
def _s16(b):
    v = struct.unpack(">H", b)[0]
    return -(v & 0x7FFF) if v & 0x8000 else v


def sections(msg):
    if msg[:4] != b"GRIB" or msg[7] != 2:
        raise ValueError("not a GRIB2 message")
    total = struct.unpack(">Q", msg[8:16])[0]
    if total != len(msg) or msg[-4:] != b"7777":
        raise ValueError(f"message length {len(msg)} != declared {total}")
    out = {0: msg[:16]}
    p = 16
    while msg[p:p + 4] != b"7777":
        n_len = struct.unpack(">I", msg[p:p + 4])[0]
        num = msg[p + 4]
        if num in out:
            raise ValueError("multi-field messages are not supported")
        out[num] = msg[p:p + n_len]
        p += n_len
    return out


def message_meta(sec):
    s1, s3, s4, s5 = sec[1], sec[3], sec[4], sec[5]
    if struct.unpack(">H", s3[12:14])[0] != 0:
        raise ValueError("grid template is not 3.0")
    grid = {"ni": struct.unpack(">I", s3[30:34])[0], "nj": struct.unpack(">I", s3[34:38])[0],
            "la1": struct.unpack(">i", s3[46:50])[0] / 1e6, "lo1": struct.unpack(">i", s3[50:54])[0] / 1e6,
            "di": struct.unpack(">I", s3[63:67])[0] / 1e6, "dj": struct.unpack(">I", s3[67:71])[0] / 1e6,
            "scan": s3[71]}
    for key, want in GRID.items():
        if abs(grid[key] - want) > 1e-6:
            raise ValueError(f"grid {key} {grid[key]} != {want}")
    if grid["scan"] != 0:
        raise ValueError(f"scan mode {grid['scan']}")
    tmpl = struct.unpack(">H", s4[7:9])[0]
    meta = {"discipline": sec[0][6], "category": s4[9], "number": s4[10], "product_template": tmpl,
            "ref_time": dt.datetime(struct.unpack(">H", s1[12:14])[0], s1[14], s1[15], s1[16], s1[17], s1[18],
                                    tzinfo=UTC),
            "time_unit": s4[17], "forecast_time": struct.unpack(">I", s4[18:22])[0], "member": None,
            "stat_process": None, "stat_length": None}
    if tmpl in (1, 11):
        meta["member"] = s4[35]
        meta["ensemble_type"] = s4[34]
    if tmpl in (8, 11):
        o = 37 if tmpl == 11 else 34  # start of "year of end of overall time interval"
        meta["stat_process"] = s4[o + 12]
        meta["stat_length"] = struct.unpack(">I", s4[o + 15:o + 19])[0]
        meta["stat_unit"] = s4[o + 14]
    dtmpl = struct.unpack(">H", s5[9:11])[0]
    if dtmpl != 42:
        raise ValueError(f"data template 5.{dtmpl} is not 5.42 (CCSDS)")
    meta["packing"] = {"R": struct.unpack(">f", s5[11:15])[0], "E": _s16(s5[15:17]), "D": _s16(s5[17:19]),
                       "bps": s5[19], "flags": s5[21], "block": s5[22], "rsi": struct.unpack(">H", s5[23:25])[0],
                       "npts": struct.unpack(">I", s5[5:9])[0]}
    if meta["packing"]["npts"] != GRID["ni"] * GRID["nj"]:
        raise ValueError("point count differs from the grid")
    if sec.get(6, b"\0\0\0\0\0\xff")[5] != 255:
        raise ValueError("bitmapped fields are not supported")
    return meta


def decode_points(msg, indexes=None):
    """(meta, {index: value}) for the wanted grid indexes, or (meta, full float array) when ``indexes`` is None."""
    sec = sections(msg)
    meta = message_meta(sec)
    pk = meta["packing"]
    data = sec[7][5:]
    scale = 2.0 ** pk["E"] / 10.0 ** pk["D"]
    off = pk["R"] / 10.0 ** pk["D"]
    if pk["bps"] == 0:
        vals = {i: off for i in indexes} if indexes is not None else np.full(pk["npts"], off)
        return meta, vals
    raw = aec_decode(data, pk["bps"], pk["block"], pk["rsi"], pk["flags"], pk["npts"], indexes)
    if indexes is None:
        return meta, off + raw.astype(np.float64) * scale
    return meta, {i: off + v * scale for i, v in raw.items()}


def check_param(meta, param):
    disc, cat, num, tmpls, stat = PARAMS[param]
    if (meta["discipline"], meta["category"], meta["number"]) != (disc, cat, num):
        raise ValueError(f"{param}: parameter {(meta['discipline'], meta['category'], meta['number'])}")
    if meta["product_template"] not in tmpls:
        raise ValueError(f"{param}: product template 4.{meta['product_template']}")
    if stat is not None and (meta["stat_process"] != stat or meta["stat_length"] != 3 or meta.get("stat_unit") != 1):
        raise ValueError(f"{param}: statistical process {meta['stat_process']} over {meta['stat_length']}")


# --------------------------------------------------------------------------- stations and points
def station_corners(lat, lon):
    lonp = (lon - GRID["lo1"]) % 360.0
    fi, fj = lonp / GRID["di"], (GRID["la1"] - lat) / GRID["dj"]
    i0, j0 = int(math.floor(fi)), int(math.floor(fj))
    i1, j1 = (i0 + 1) % GRID["ni"], j0 + 1
    if not (0 <= j0 and j1 < GRID["nj"]):
        raise ValueError("station outside the grid")
    idx = [j0 * GRID["ni"] + i0, j0 * GRID["ni"] + i1, j1 * GRID["ni"] + i0, j1 * GRID["ni"] + i1]
    return {"idx": idx, "wy": fj - j0, "wx": fi - i0, "j0": j0, "i0": i0}


def point_values(vals, c):
    v00, v01, v10, v11 = (float(vals[i]) for i in c["idx"])
    wx, wy = c["wx"], c["wy"]
    bil = (v00 * (1 - wx) + v01 * wx) * (1 - wy) + (v10 * (1 - wx) + v11 * wx) * wy
    near = [v00, v01, v10, v11][(1 if wx >= 0.5 else 0) + (2 if wy >= 0.5 else 0)]
    return {"bilinear_k": round(bil, 4), "nearest_k": round(near, 4),
            "corners_k": [round(v, 4) for v in (v00, v01, v10, v11)]}


def station_table():
    out = []
    for market, icao, lat, lon in STATIONS:
        c = station_corners(lat, lon)
        out.append({"market": market, "icao": icao, "lat": lat, "lon": lon, "grid_j0": c["j0"], "grid_i0": c["i0"],
                    "wy": round(c["wy"], 4), "wx": round(c["wx"], 4), "corner_index": c["idx"]})
    return out


CORNERS = {s[1]: station_corners(s[2], s[3]) for s in STATIONS}
WANTED = sorted({i for c in CORNERS.values() for i in c["idx"]})


# --------------------------------------------------------------------------- names
def step_stem(run, step):
    return f"{BASE}/{run:%Y%m%d}/{run:%H}z/ifs/0p25/enfo/{run:%Y%m%d%H}0000-{step}h-enfo-ef"


def parse_index(text):
    rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    for r in rows:
        if not {"_offset", "_length", "param", "type"} <= set(r):
            raise ValueError("index row without _offset/_length/param/type")
    return rows


def select_messages(rows, params, run, step):
    out = []
    for r in rows:
        if r["param"] not in params or r["type"] not in ("pf", "cf") or r.get("levtype") != "sfc":
            continue
        if r.get("date") != f"{run:%Y%m%d}" or r.get("time") != f"{run:%H}00" or int(r.get("step", -1)) != step:
            raise ValueError(f"index row for another run/step: {r}")
        member = 0 if r["type"] == "cf" else int(r["number"])
        out.append({"param": r["param"], "member": member, "type": r["type"],
                    "offset": int(r["_offset"]), "length": int(r["_length"])})
    out.sort(key=lambda m: (m["param"], m["member"]))
    return out


# --------------------------------------------------------------------------- storage and guards
def append_jsonl(path, rec):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def append_jsonl_many(path, recs):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("".join(json.dumps(r, sort_keys=True) + "\n" for r in recs))
        fh.flush()
        os.fsync(fh.fileno())


def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:  # a torn last line after a hard kill
                continue
    return out


def write_json_atomic(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(obj, indent=1, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def dir_bytes(path):
    return sum(p.stat().st_size for p in Path(path).rglob("*") if p.is_file())


def git_blob_id(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def code_identity():
    raw = Path(__file__).read_bytes()
    return {Path(__file__).name: {"git_blob_lf": git_blob_id(raw.replace(b"\r\n", b"\n")), "sha256": sha256(raw)}}


def set_below_normal_priority():
    try:
        if os.name == "nt":
            import ctypes

            k32 = ctypes.windll.kernel32
            k32.GetCurrentProcess.restype = ctypes.c_void_p
            k32.SetPriorityClass.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
            return bool(k32.SetPriorityClass(k32.GetCurrentProcess(), 0x00004000))
        os.nice(5)
        return True
    except Exception:  # pragma: no cover - best effort, recorded in events
        return False


def acquire_lock(path, wait_s=0.0, sleep=time.sleep):
    deadline = time.monotonic() + wait_s
    while True:
        fh = open(path, "a+")
        try:
            if os.name == "nt":
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fh
        except OSError:
            fh.close()
            if time.monotonic() >= deadline:
                raise SystemExit(f"another recorder holds {path}")
            sleep(1.0)


class CapReached(RuntimeError):
    pass


class Resp:
    def __init__(self, status, content, headers):
        self.status_code, self.content, self.headers = status, content, headers


class Http:
    """Persistent HTTPS GET client (optional byte range) with a per-process byte cap."""

    def __init__(self, cap_bytes, user_agent="weather-research-l13-ecmwf-ens-forward/1 (serial; ECMWF open data)"):
        import ssl

        self.ctx = ssl.create_default_context()
        self.base_headers = {"User-Agent": user_agent, "Accept-Encoding": "identity"}
        self.conn, self.host, self.cap = None, None, cap_bytes
        self.used, self.requests = 0, 0

    def _close(self):
        if self.conn is not None:
            self.conn.close()
        self.conn = None

    def get(self, url, byte_range=None, timeout=120):
        import http.client
        from urllib.parse import urlsplit

        if self.used >= self.cap:
            raise CapReached(self.used)
        u = urlsplit(url)
        headers = dict(self.base_headers)
        if byte_range is not None:
            headers["Range"] = f"bytes={byte_range[0]}-{byte_range[1]}"
        for attempt in (0, 1):
            if self.conn is None or self.host != u.hostname:
                self._close()
                self.conn = http.client.HTTPSConnection(u.hostname, context=self.ctx, timeout=timeout)
                self.host = u.hostname
            try:
                self.conn.request("GET", u.path, headers=headers)
                resp = self.conn.getresponse()
                body = resp.read()
            except (http.client.HTTPException, OSError):
                self._close()
                if attempt:
                    raise
                continue
            self.requests += 1
            self.used += len(body)
            if (resp.getheader("Connection") or "").lower() == "close":
                self._close()
            keep = {k: resp.getheader(k) for k in ("Last-Modified", "ETag", "Content-Length", "Content-Range")}
            return Resp(resp.status, body, keep)


class Throttle:
    """Average bytes/s plus a per-clock-hour byte ceiling."""

    def __init__(self, bytes_per_s, hourly_bytes, sleep=time.sleep):
        self.rate, self.hourly, self.sleep = bytes_per_s, hourly_bytes, sleep
        self.hour, self.hour_bytes = None, 0

    def allow(self, now, size_hint):
        hour = now.replace(minute=0, second=0, microsecond=0)
        if hour != self.hour:
            self.hour, self.hour_bytes = hour, 0
        return self.hour_bytes + size_hint <= self.hourly

    def spent(self, nbytes, elapsed_s):
        self.hour_bytes += nbytes
        floor = nbytes / self.rate if self.rate > 0 else 0.0
        if floor > elapsed_s:
            self.sleep(floor - elapsed_s)


def _lm(headers):
    lm = headers.get("Last-Modified")
    return _iso(parsedate_to_datetime(lm)) if lm else None


# --------------------------------------------------------------------------- recorder
class Recorder:
    def __init__(self, out, http, clock=None, sleep=time.sleep, cycles=DEFAULT_CYCLES, steps=DEFAULT_STEPS,
                 params=DEFAULT_PARAMS, pause_file=None, stop_file=None, bytes_per_s=4_000_000, hourly_mb=1500.0,
                 min_free_gb=20.0, cap_gb=20.0, first_run=FORWARD_FIRST):
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.http = http
        self.clock = clock or (lambda: dt.datetime.now(UTC))
        self.sleep = sleep
        self.cycles, self.steps, self.params = tuple(cycles), tuple(steps), tuple(params)
        self.pause_file = Path(pause_file) if pause_file else self.out / "RECORDER_PAUSE"
        self.stop_file = Path(stop_file) if stop_file else self.out / "STOP"
        self.throttle = Throttle(bytes_per_s, int(hourly_mb * 1e6), sleep)
        self.min_free, self.cap = min_free_gb * 1e9, cap_gb * 1e9
        self.first_run = max(first_run, FORWARD_FIRST)
        self.paused_since = None
        self.runs = {}
        self.code_sha256 = sha256(Path(__file__).read_bytes())

    def _p(self, *parts):
        return self.out.joinpath(*parts)

    def _run_dir(self, run):
        return self._p(run.strftime("%Y%m%d%H"))

    def log_event(self, event, **kw):
        append_jsonl(self._p("events.jsonl"), {"event": event, "at_utc": _iso(self.clock()), **kw})

    def open_runs(self, now):
        out = []
        t = (now - CLOSE_AFTER - dt.timedelta(hours=24)).replace(minute=0, second=0, microsecond=0)
        while t <= now:
            if t.hour in self.cycles and t >= self.first_run and now >= t + FIRST_TRY:
                if not self.run_state(t)["done"]:
                    out.append(t)
            t += dt.timedelta(hours=1)
        return out

    def run_state(self, run):
        st = self.runs.get(run)
        if st is None:
            rows = read_jsonl(self._run_dir(run) / "index.jsonl")
            st = {"rows": rows, "ok": set(), "closed": set(), "tries": defaultdict(int),
                  "done": (self._run_dir(run) / "manifest.json").exists()}
            for r in rows:
                if r.get("kind") != "step":
                    continue
                if r.get("status") == "ok":
                    st["ok"].add(r["step"])
                elif r.get("status") == "missing":
                    st["closed"].add(r["step"])
                else:
                    st["tries"][r["step"]] += 1
            self.runs[run] = st
        return st

    def _append(self, run, rec):
        append_jsonl(self._run_dir(run) / "index.jsonl", rec)
        self.runs[run]["rows"].append(rec)

    def _guard(self, size_hint):
        if not self.throttle.allow(self.clock(), size_hint):
            self.log_event("hourly_byte_ceiling")
            return False
        if shutil.disk_usage(self.out).free < self.min_free or dir_bytes(self.out) > self.cap:
            self.log_event("disk_guard")
            return False
        return True

    def _timed_get(self, url, byte_range=None):
        u0, w0 = self.http.used, time.time()
        r = self.http.get(url, byte_range) if byte_range else self.http.get(url)
        self.throttle.spent(self.http.used - u0, time.time() - w0)
        return r, self.clock()

    def fetch_step(self, run, step):
        """Index plus every selected member message of one step; returns (step row, point rows)."""
        stem = step_stem(run, step)
        base = {"kind": "step", "run_utc": run.isoformat(), "step": step, "index_url": stem + ".index",
                "grib_url": stem + ".grib2", "params": list(self.params)}
        try:
            r, fetched = self._timed_get(stem + ".index")
        except CapReached:
            raise
        except Exception as e:
            return {**base, "status": "fetch_error", "error": repr(e)[:300], "fetched_utc": _iso(self.clock())}, []
        if r.status_code == 404:
            return {**base, "status": "not_yet", "fetched_utc": _iso(fetched)}, []
        if r.status_code != 200:
            return {**base, "status": f"http_{r.status_code}", "fetched_utc": _iso(fetched)}, []
        rec = {**base, "index_fetched_utc": _iso(fetched), "index_sha256": sha256(r.content),
               "index_bytes": len(r.content), "index_last_modified_utc": _lm(r.headers),
               "index_etag": r.headers.get("ETag")}
        points, messages = [], []
        try:
            sel = select_messages(parse_index(r.content.decode("utf-8")), set(self.params), run, step)
            for p in self.params:
                if sum(1 for m in sel if m["param"] == p) < 50:
                    raise ValueError(f"{p}: {sum(1 for m in sel if m['param'] == p)} members in the index")
            for m in sel:
                rng = (m["offset"], m["offset"] + m["length"] - 1)
                g, gf = self._timed_get(stem + ".grib2", rng)
                if g.status_code != 206 or len(g.content) != m["length"]:
                    raise ValueError(f"range GET {rng}: status {g.status_code}, {len(g.content)} bytes")
                lm = _lm(g.headers)
                if lm is None:
                    raise ValueError("no Last-Modified header")
                meta, vals = decode_points(g.content, WANTED)
                check_param(meta, m["param"])
                if meta["ref_time"] != run:
                    raise ValueError(f"reference time {meta['ref_time']} != {run}")
                if meta["time_unit"] != 1:
                    raise ValueError(f"time unit {meta['time_unit']}")
                fc_end = meta["forecast_time"] + (meta["stat_length"] or 0)
                if fc_end != step:
                    raise ValueError(f"forecast end {fc_end} != step {step}")
                if m["type"] == "pf" and meta["member"] != m["member"]:
                    raise ValueError(f"member {meta['member']} != index {m['member']}")
                msha = sha256(g.content)
                messages.append({"param": m["param"], "member": m["member"], "offset": m["offset"],
                                 "length": m["length"], "sha256": msha, "last_modified_utc": lm,
                                 "etag": g.headers.get("ETag"), "fetched_utc": _iso(gf)})
                for market, icao, lat, lon in STATIONS:
                    pv = point_values(vals, CORNERS[icao])
                    if not 150.0 < pv["bilinear_k"] < 350.0:
                        raise ValueError(f"{icao}: implausible {pv['bilinear_k']} K")
                    points.append({"kind": "point", "run_utc": run.isoformat(), "step": step,
                                   "valid_utc": _iso(run + dt.timedelta(hours=step)), "param": m["param"],
                                   "window_h": 3 if m["param"] == "mx2t3" else 0, "member": m["member"],
                                   "market": market, "icao": icao, **pv, "msg_sha256": msha,
                                   "last_modified_utc": lm, "fetched_utc": _iso(gf)})
            rec.update(status="ok", messages=messages, members=len({m["member"] for m in sel}),
                       max_last_modified_utc=max(m["last_modified_utc"] for m in messages),
                       max_fetched_utc=max(m["fetched_utc"] for m in messages), points=len(points))
        except CapReached:
            raise
        except Exception as e:
            rec.update(status="invalid", error=repr(e)[:300], fetched_utc=_iso(self.clock()))
            points = []
        return rec, points

    def work_run(self, run, now):
        st = self.run_state(run)
        fetched = 0
        for step in self.steps:
            if step in st["ok"] or step in st["closed"]:
                continue
            if now >= run + CLOSE_AFTER or st["tries"][step] >= MAX_TRIES:
                rec = {"kind": "step", "run_utc": run.isoformat(), "step": step, "status": "missing",
                       "tries": st["tries"][step], "closed_utc": _iso(self.clock())}
                self._append(run, rec)
                st["closed"].add(step)
                append_jsonl(self._p("gaps.jsonl"), {"gap": "missing", **rec})
                continue
            if not self._guard(50 * 400_000 * len(self.params)):
                return fetched
            rec, points = self.fetch_step(run, step)
            if rec["status"] == "not_yet":
                break  # later steps of this run are not published either
            if points:
                append_jsonl_many(self._run_dir(run) / "points.jsonl", points)
            self._append(run, rec)
            if rec["status"] == "ok":
                st["ok"].add(step)
                fetched += 1
            else:
                st["tries"][step] += 1
                self.log_event("fetch_failed", run=run.isoformat(), step=step, status=rec["status"])
        if all(s in st["ok"] or s in st["closed"] for s in self.steps):
            self.finalize(run)
        return fetched

    def finalize(self, run):
        st = self.run_state(run)
        d = self._run_dir(run)
        self._append(run, {"kind": "run_done", "run_utc": run.isoformat(), "ok": len(st["ok"]),
                           "missing": len(st["closed"]), "closed_utc": _iso(self.clock())})
        ok = [r for r in st["rows"] if r.get("kind") == "step" and r.get("status") == "ok"]
        pts = d / "points.jsonl"
        write_json_atomic(d / "manifest.json", {
            "schema": SCHEMA, "run_utc": run.isoformat(), "source": "ECMWF open data (CC-BY-4.0)",
            "url_stem": step_stem(run, 0).rsplit("-0h-", 1)[0], "params": list(self.params),
            "steps": list(self.steps), "steps_ok": sorted(st["ok"]), "steps_missing": sorted(st["closed"]),
            "index_sha256": sha256((d / "index.jsonl").read_bytes()),
            "points_sha256": sha256(pts.read_bytes()) if pts.exists() else None,
            "messages": sum(len(r.get("messages", [])) for r in ok),
            "max_last_modified_utc": max((r["max_last_modified_utc"] for r in ok), default=None),
            "max_fetched_utc": max((r["max_fetched_utc"] for r in ok), default=None),
            "stations": station_table(), "recorder_sha256": self.code_sha256, "written_utc": _iso(self.clock())})
        st["done"] = True
        self.log_event("run_done", run=run.isoformat(), ok=len(st["ok"]), missing=len(st["closed"]))

    def step(self):
        now = self.clock()
        paused = self.pause_file.exists()
        if paused and self.paused_since is None:
            self.paused_since = now
            self.log_event("pause_start")
            append_jsonl(self._p("gaps.jsonl"), {"gap": "pause_start", "at_utc": _iso(now)})
        elif not paused and self.paused_since is not None:
            append_jsonl(self._p("gaps.jsonl"), {"gap": "pause_end", "at_utc": _iso(now),
                                                 "started_utc": _iso(self.paused_since)})
            self.log_event("pause_end")
            self.paused_since = None
        fetched, runs = 0, []
        if not paused:
            for run in self.open_runs(now):
                runs.append(run.isoformat())
                fetched += self.work_run(run, now)
        return {"fetched_steps": fetched, "open_runs": runs, "paused": paused}

    def status(self, state, extra=None):
        write_json_atomic(self._p("status.json"), {
            "state": state, "pid": os.getpid(), "updated_utc": _iso(self.clock()), "bytes_this_process": self.http.used,
            "requests_this_process": self.http.requests, "cpu_s": round(time.process_time(), 2),
            "paused": self.paused_since is not None, "recorder_sha256": self.code_sha256, **(extra or {})})

    def run(self, poll_s=600, max_steps=None):
        self.log_event("start", pid=os.getpid(), code=code_identity(), cycles=list(self.cycles),
                       steps=list(self.steps), params=list(self.params))
        n = 0
        while True:
            if self.stop_file.exists():
                self.log_event("stop_file")
                self.status("stopped_by_file")
                return
            try:
                self.status("running", self.step())
            except CapReached:
                self.log_event("cap_reached")
                self.status("cap_reached")
                return
            except Exception as e:  # keep recording; the failure is logged
                self.log_event("step_error", error=repr(e)[:500], tb=traceback.format_exc()[-1500:])
                self.status("running_after_error")
            n += 1
            if max_steps is not None and n >= max_steps:
                return
            self.sleep(poll_s)


def _int_list(text):
    return tuple(int(x) for x in text.split(",") if x.strip())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=r"C:\t\ecmwf_ens\forward")
    ap.add_argument("--cycles", default="0,12", help="comma list of 0,6,12,18")
    ap.add_argument("--steps", default=",".join(str(s) for s in DEFAULT_STEPS))
    ap.add_argument("--params", default="mx2t3", help="comma list of mx2t3 and 2t")
    ap.add_argument("--pause-file", default=None, help="default <out>/RECORDER_PAUSE")
    ap.add_argument("--stop-file", default=None, help="default <out>/STOP")
    ap.add_argument("--wait-lock-seconds", type=float, default=0.0)
    ap.add_argument("--poll-seconds", type=int, default=600)
    ap.add_argument("--bytes-per-second", type=int, default=4_000_000)
    ap.add_argument("--hourly-mb", type=float, default=1500.0)
    ap.add_argument("--net-cap-gb", type=float, default=200.0, help="network byte cap for this process")
    ap.add_argument("--cap-gb", type=float, default=20.0, help="output directory size cap")
    ap.add_argument("--min-free-gb", type=float, default=20.0)
    ap.add_argument("--max-steps", type=int, default=None)
    ap.add_argument("--first-run", default=None, help="UTC ISO; not before the built-in forward start")
    ap.add_argument("--once", action="store_true", help="one foreground pass over the open runs, then exit")
    ap.add_argument("--print-stations", action="store_true")
    args = ap.parse_args(argv)
    if args.print_stations:
        print(json.dumps(station_table(), indent=1))
        return 0
    cycles, steps = _int_list(args.cycles), _int_list(args.steps)
    params = tuple(p.strip() for p in args.params.split(",") if p.strip())
    if not cycles or set(cycles) - {0, 6, 12, 18}:
        raise SystemExit(f"--cycles must be within 0,6,12,18: {args.cycles}")
    if not steps or any(s < 3 or s % 3 for s in steps):
        raise SystemExit("--steps must be positive multiples of 3")
    if not params or set(params) - set(PARAMS):
        raise SystemExit(f"--params must be within {sorted(PARAMS)}")
    out = Path(args.out)
    repo = Path(__file__).resolve().parents[2]
    if repo in out.resolve().parents or out.resolve() == repo:
        raise SystemExit("output must be outside the repository")
    out.mkdir(parents=True, exist_ok=True)
    lock = acquire_lock(out / "recorder.lock", args.wait_lock_seconds)  # noqa: F841 - held until exit
    prio = set_below_normal_priority()
    first = dt.datetime.fromisoformat(args.first_run) if args.first_run else FORWARD_FIRST
    rec = Recorder(out, Http(int(args.net_cap_gb * 1e9)), cycles=cycles, steps=steps, params=params,
                   pause_file=args.pause_file, stop_file=args.stop_file, bytes_per_s=args.bytes_per_second,
                   hourly_mb=args.hourly_mb, min_free_gb=args.min_free_gb, cap_gb=args.cap_gb, first_run=first)
    rec.log_event("priority", below_normal=prio)
    if args.once:
        rec.log_event("once", code=code_identity())
        result = rec.step()
        rec.status("once_done", result)
        print(json.dumps(result))
        return 0
    (out / "recorder.pid").write_text(str(os.getpid()), encoding="ascii")
    rec.run(args.poll_seconds, args.max_steps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
