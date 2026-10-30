"""Lane L13: ECCC GEM forward recorder: HRDPS, RDPS, GDPS and GEPS point 2 m temperature (and Tmax) at CYYZ.

Free official data from the MSC Datamart dated archive ``https://dd.weather.gc.ca/<YYYYMMDD>/WXO-DD/`` (anonymous
HTTPS, no key, no credentials; about 30 days kept). Design note: ``docs/research/eccc-gem-forward-recorder-2026-10-30.md``.
Research / shadow only: nothing imports this module, nothing is served, and no outcome, price or label is read.

* **What is fetched.** One small single-variable GRIB2 file per model, product, run and step (HRDPS about 3.4 MB,
  RDPS 0.7 MB, GDPS 1.3 MB, GEPS all-members 3.9 MB). HRDPS URLs come from
  ``weather.sources.eccc_gridded.build_hrdps_datamart_url`` re-rooted on the dated archive (the ``today/`` tree it
  defaults to is overwritten daily).
* **Decoding.** The files use JPEG2000 packing (GRIB2 data template 5.40), decoded with Pillow (already in the venv;
  no eccodes or other new package). Pillow returns the samples left-aligned to 16 bits, so they are shifted by
  ``16 - precision`` read from the codestream's SIZ marker and the dropped bits are checked to be zero. Grid templates
  3.0 (regular lat/lon) and 3.1 (rotated pole, rotation angle 0) are handled; product templates 4.0, 4.1, 4.8 and 4.11
  are checked against the expected parameter, statistical process, window, run and step; anything else fails closed.
* **What is kept.** Point extractions only: the four surrounding grid values, the bilinear value and the nearest
  value at each station, per member and step (``points.jsonl``). Raw GRIB is never written to disk.

Point in time by construction: every file row carries the URL, run time, server ``Last-Modified`` and ETag, our fetch
time and the sha256 of the bytes; every point row repeats the run, the file sha256, ``Last-Modified`` and our fetch time,
and carries the market's local settlement day computed with ``zoneinfo`` (``forward_local_day``; DST-correct, a window
crossing local midnight gets ``local_date`` null). Per model and run ``<out>/<model>/<YYYYMMDDHH>/`` holds
``index.jsonl``, ``points.jsonl`` and, once every slot is ok or closed missing, ``manifest.json``. Missed slots close
at ``run + CLOSE_AFTER`` or after ``MAX_TRIES`` and are appended to ``gaps.jsonl``. Guards as the MOSMIX and ENS
recorders: below-normal priority, throttle and hourly ceiling, a per-process byte cap, a pause file, a STOP file, a
single-instance lock, a free-disk floor and an output-size cap. Forward runs only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
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

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
for _p in (str(_REPO / "src"), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from forward_local_day import local_fields  # noqa: E402
from weather.sources.eccc_gridded import (  # noqa: E402
    HRDPS_DATAMART_BASE_URL,
    build_hrdps_datamart_url,
    parse_hrdps_datamart_filename,
)

UTC = dt.timezone.utc
SCHEMA = "eccc_gem_forward/1"
FORWARD_FIRST = dt.datetime(2026, 10, 31, 0, tzinfo=UTC)  # first run the recorder may ask for
ARCHIVE = "https://dd.weather.gc.ca/{date}/WXO-DD"
CLOSE_AFTER = dt.timedelta(days=7)    # the dated archive keeps about 30 days; later slots close as missing
LATE = dt.timedelta(hours=9)          # after first_try + LATE a 404 counts as a failed try, not "not yet"
MAX_TRIES = 8

# market, icao, lat, lon, IANA timezone (the market registry; the test checks them)
STATIONS = (("toronto", "CYYZ", 43.6767, -79.6306, "America/Toronto"),)

# product -> (discipline, category, number, product templates, statistical process or None, window hours)
PRODUCTS = {
    "t2m": (0, 0, 0, (0, 1), None, 0),
    "tmax": (0, 0, 4, (8, 11), 2, 6),
}


def _hourly(a, b, by=1):
    return tuple(range(a, b + 1, by))


# model -> cycles, first try after the run, members (None = deterministic), products -> steps
MODELS = {
    "hrdps": {"cycles": (0, 6, 12, 18), "first_try_h": 2.5, "members": None, "products": {"t2m": _hourly(1, 48)}},
    "rdps": {"cycles": (0, 6, 12, 18), "first_try_h": 2.5, "members": None, "products": {"t2m": _hourly(1, 48)}},
    "gdps": {"cycles": (0, 12), "first_try_h": 3.5, "members": None,
             "products": {"t2m": _hourly(1, 72), "tmax": _hourly(6, 72, 6)}},
    "geps": {"cycles": (0, 12), "first_try_h": 4.5, "members": 21,
             "products": {"t2m": _hourly(3, 72, 3), "tmax": _hourly(6, 72, 6)}},
}
SIZE_HINT = 4_500_000


def _iso(t):
    return t.isoformat() if t is not None else None


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def file_url(model, product, run, step):
    day, hh, fff = run.strftime("%Y%m%d"), run.strftime("%H"), f"{step:03d}"
    base = ARCHIVE.format(date=day)
    stamp = run.strftime("%Y%m%dT%HZ")
    if model == "hrdps":
        if product != "t2m":
            raise ValueError(product)
        url = build_hrdps_datamart_url(run, step)
        if not url.startswith(HRDPS_DATAMART_BASE_URL):
            raise ValueError(url)
        url = base + "/model_hrdps" + url[len(HRDPS_DATAMART_BASE_URL):]
        parsed = parse_hrdps_datamart_filename(url)
        if parsed is None or parsed["forecast_hour"] != step or parsed["run_time_utc"] != run.isoformat():
            raise ValueError(f"HRDPS URL does not parse back: {url}")
        return url
    if model == "rdps":
        return f"{base}/model_rdps/10km/{hh}/{fff}/{stamp}_MSC_RDPS_AirTemp_AGL-2m_RLatLon0.09_PT{fff}H.grib2"
    if model == "gdps":
        var = {"t2m": "AirTemp", "tmax": "AirTemp-Max"}[product]
        return f"{base}/model_gdps/15km/{hh}/{fff}/{stamp}_MSC_GDPS_{var}_AGL-2m_LatLon0.15_PT{fff}H.grib2"
    if model == "geps":
        var = {"t2m": "TMP", "tmax": "TMAX"}[product]
        return (f"{base}/ensemble/geps/grib2/raw/{hh}/{fff}/CMC_geps-raw_{var}_TGL_2m_latlon0p5x0p5_"
                f"{run.strftime('%Y%m%d%H')}_P{fff}_allmbrs.grib2")
    raise ValueError(model)


# --------------------------------------------------------------------------- GRIB2 (templates 3.0/3.1, 5.40)
def _sm16(b):
    v = struct.unpack(">H", b)[0]
    return -(v & 0x7FFF) if v & 0x8000 else v


def _sm32(b):
    v = struct.unpack(">I", b)[0]
    return -(v & 0x7FFFFFFF) if v & 0x80000000 else v


def split_messages(data):
    out, pos = [], 0
    while pos < len(data):
        if data[pos:pos + 4] != b"GRIB" or data[pos + 7] != 2:
            raise ValueError(f"no GRIB2 message at byte {pos}")
        total = struct.unpack(">Q", data[pos + 8:pos + 16])[0]
        msg = data[pos:pos + total]
        if len(msg) != total or msg[-4:] != b"7777":
            raise ValueError("truncated GRIB2 message")
        out.append(msg)
        pos += total
    if not out:
        raise ValueError("empty file")
    return out


def sections(msg):
    out = {0: msg[:16]}
    p = 16
    while msg[p:p + 4] != b"7777":
        n_len = struct.unpack(">I", msg[p:p + 4])[0]
        num = msg[p + 4]
        if num in out or n_len < 5:
            raise ValueError("multi-field or malformed message")
        out[num] = msg[p:p + n_len]
        p += n_len
    for k in (1, 3, 4, 5, 6, 7):
        if k not in out:
            raise ValueError(f"section {k} missing")
    return out


_UNIT_H = {0: 1 / 60, 1: 1, 2: 24, 10: 3, 11: 6, 12: 12}


def grid_of(s3):
    tpl = struct.unpack(">H", s3[12:14])[0]
    if tpl not in (0, 1):
        raise ValueError(f"grid template 3.{tpl} not supported")
    if s3[5] != 0:
        raise ValueError("grid not defined by a template")
    basic, sub = struct.unpack(">II", s3[38:46])
    if basic not in (0,) or sub not in (0, 0xFFFFFFFF):
        raise ValueError("non-default basic angle")
    g = {"template": tpl, "ni": struct.unpack(">I", s3[30:34])[0], "nj": struct.unpack(">I", s3[34:38])[0],
         "la1": _sm32(s3[46:50]) / 1e6, "lo1": _sm32(s3[50:54]) / 1e6, "la2": _sm32(s3[55:59]) / 1e6,
         "lo2": _sm32(s3[59:63]) / 1e6, "di": struct.unpack(">I", s3[63:67])[0] / 1e6,
         "dj": struct.unpack(">I", s3[67:71])[0] / 1e6, "scan": s3[71]}
    if g["scan"] not in (0x00, 0x40):
        raise ValueError(f"scan mode {g['scan']:#x} not supported")
    if tpl == 1:
        if len(s3) < 84 or s3[80:84] != b"\0\0\0\0":
            raise ValueError("rotated grid with a non-zero rotation angle")
        g["splat"], g["splon"] = _sm32(s3[72:76]) / 1e6, _sm32(s3[76:80]) / 1e6
    return g


def rotate(lat, lon, splat, splon):
    """Geographic -> rotated-pole lat/lon (southern pole at splat/splon, rotation angle 0)."""
    th = math.radians(90.0 + splat)
    la, lo = math.radians(lat), math.radians(lon - splon)
    x, y, z = math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la)
    xr = math.cos(th) * x + math.sin(th) * z
    zr = -math.sin(th) * x + math.cos(th) * z
    return math.degrees(math.asin(max(-1.0, min(1.0, zr)))), math.degrees(math.atan2(y, xr))


def corners(g, lat, lon):
    glat, glon = (rotate(lat, lon, g["splat"], g["splon"]) if g["template"] == 1 else (lat, lon))
    fj = (glat - g["la1"]) / g["dj"] if g["scan"] & 0x40 else (g["la1"] - glat) / g["dj"]
    fi = ((glon - g["lo1"]) % 360.0) / g["di"]
    i0, j0 = int(math.floor(fi)), int(math.floor(fj))
    wrap = abs(g["ni"] * g["di"] - 360.0) < 1e-6
    i1 = (i0 + 1) % g["ni"] if wrap else i0 + 1
    if not (0 <= j0 and j0 + 1 < g["nj"] and 0 <= i0 and i1 < g["ni"]):
        raise ValueError("station outside the grid")
    ni = g["ni"]
    return {"idx": [j0 * ni + i0, j0 * ni + i1, (j0 + 1) * ni + i0, (j0 + 1) * ni + i1],
            "wx": fi - i0, "wy": fj - j0, "grid_lat": round(glat, 5), "grid_lon": round(glon, 5)}


def point_values(vals, c):
    v00, v01, v10, v11 = (float(vals[i]) for i in c["idx"])
    wx, wy = c["wx"], c["wy"]
    bil = (v00 * (1 - wx) + v01 * wx) * (1 - wy) + (v10 * (1 - wx) + v11 * wx) * wy
    near = [v00, v01, v10, v11][(1 if wx >= 0.5 else 0) + (2 if wy >= 0.5 else 0)]
    return {"bilinear_k": round(bil, 4), "nearest_k": round(near, 4),
            "corners_k": [round(v, 4) for v in (v00, v01, v10, v11)]}


def j2k_samples(codestream, n_expected):
    """Integer samples of a single-component JPEG2000 codestream, Pillow's 16-bit left alignment undone."""
    from PIL import Image

    if codestream[:4] != b"\xff\x4f\xff\x51":
        raise ValueError("not a JPEG2000 codestream")
    if struct.unpack(">H", codestream[40:42])[0] != 1:
        raise ValueError("JPEG2000 with more than one component")
    ssiz = codestream[42]
    if ssiz & 0x80:
        raise ValueError("signed JPEG2000 samples")
    prec = (ssiz & 0x7F) + 1
    img = Image.open(io.BytesIO(codestream))
    img.load()
    return unshift(np.asarray(img).astype(np.int64), img.mode, prec, n_expected)


def unshift(a, mode, prec, n_expected):
    """Pillow decodes 9-16 bit samples as I;16 left-aligned to 16 bits (verified on ECCC 10- and 12-bit fields)."""
    if a.size != n_expected:
        raise ValueError(f"{a.size} samples != {n_expected}")
    if mode.startswith("I;16") and 9 <= prec <= 16:
        shift = 16 - prec
    elif mode == "L" and prec == 8:
        shift = 0
    else:
        raise ValueError(f"JPEG2000 mode {mode} with precision {prec} not supported")
    if shift and (a & ((1 << shift) - 1)).any():
        raise ValueError("JPEG2000 samples are not left-aligned as expected")
    return (a >> shift).reshape(-1)


def decode_message(msg):
    """(meta, values) for one GRIB2 message with grid 3.0/3.1 and data template 5.40, no bitmap."""
    s = sections(msg)
    s1, s3, s4, s5, s6, s7 = s[1], s[3], s[4], s[5], s[6], s[7]
    g = grid_of(s3)
    if struct.unpack(">H", s5[9:11])[0] != 40:
        raise ValueError(f"data template 5.{struct.unpack('>H', s5[9:11])[0]} not supported")
    if s6[5] != 255:
        raise ValueError("bitmap present")
    n = struct.unpack(">I", s5[5:9])[0]
    if n != g["ni"] * g["nj"]:
        raise ValueError("data point count != grid size")
    ref = struct.unpack(">f", s5[11:15])[0]
    e, d, nb = _sm16(s5[15:17]), _sm16(s5[17:19]), s5[19]
    if nb == 0:
        x = np.zeros(n, dtype=np.int64)
    else:
        x = j2k_samples(s7[5:], n)
        if x.max(initial=0) >= (1 << nb):
            raise ValueError("samples exceed the declared bit width")
    vals = (ref + x * 2.0 ** e) / 10.0 ** d
    tpl = struct.unpack(">H", s4[7:9])[0]
    unit = s4[17]
    if unit not in _UNIT_H:
        raise ValueError(f"time unit {unit}")
    meta = {"discipline": s[0][6], "ref_time": dt.datetime(struct.unpack(">H", s1[12:14])[0], s1[14], s1[15], s1[16],
                                                          s1[17], s1[18], tzinfo=UTC),
            "template": tpl, "category": s4[9], "number": s4[10],
            "forecast_h": struct.unpack(">I", s4[18:22])[0] * _UNIT_H[unit], "grid": g,
            "member": None, "stat": None, "stat_h": 0.0, "end_time": None}
    if tpl in (1, 11):
        meta["member"], meta["n_members"] = s4[35], s4[36]
    if tpl in (8, 11):
        o = 37 if tpl == 11 else 34
        y = struct.unpack(">H", s4[o:o + 2])[0]
        meta["end_time"] = dt.datetime(y, s4[o + 2], s4[o + 3], s4[o + 4], s4[o + 5], s4[o + 6], tzinfo=UTC)
        if s4[o + 7] != 1:
            raise ValueError("more than one time range")
        sunit = s4[o + 14]
        if sunit not in _UNIT_H:
            raise ValueError(f"statistical time unit {sunit}")
        meta["stat"], meta["stat_h"] = s4[o + 12], struct.unpack(">I", s4[o + 15:o + 19])[0] * _UNIT_H[sunit]
    return meta, vals


def check_meta(meta, product, run, step, ensemble):
    disc, cat, num, tpls, stat, window = PRODUCTS[product]
    if (meta["discipline"], meta["category"], meta["number"]) != (disc, cat, num):
        raise ValueError(f"parameter {(meta['discipline'], meta['category'], meta['number'])} for {product}")
    if meta["template"] != tpls[1 if ensemble else 0]:
        raise ValueError(f"product template 4.{meta['template']} for {product}")
    if meta["ref_time"] != run:
        raise ValueError(f"reference time {meta['ref_time']} != {run}")
    if stat is not None:
        if meta["stat"] != stat or meta["stat_h"] != window:
            raise ValueError(f"statistic {meta['stat']} over {meta['stat_h']} h for {product}")
        if meta["end_time"] != run + dt.timedelta(hours=step):
            raise ValueError(f"window end {meta['end_time']} != step {step}")
    if abs(meta["forecast_h"] + meta["stat_h"] - step) > 1e-6:
        raise ValueError(f"forecast end {meta['forecast_h'] + meta['stat_h']} != step {step}")


# --------------------------------------------------------------------------- storage and guards
def append_jsonl(path, rec):
    append_jsonl_many(path, [rec])


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
    out = {}
    for p in (Path(__file__), _HERE / "forward_local_day.py", _REPO / "src" / "weather" / "sources" / "eccc_gridded.py"):
        raw = p.read_bytes()
        out[p.name] = {"git_blob_lf": git_blob_id(raw.replace(b"\r\n", b"\n")), "sha256": sha256(raw)}
    return out


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
    """Persistent HTTPS GET client with a per-process byte cap."""

    def __init__(self, cap_bytes, user_agent="weather-research-l13-eccc-gem-forward/1 (serial; MSC Datamart)"):
        import ssl

        self.ctx = ssl.create_default_context()
        self.base_headers = {"User-Agent": user_agent, "Accept-Encoding": "identity"}
        self.conn, self.host, self.cap = None, None, cap_bytes
        self.used, self.requests = 0, 0

    def _close(self):
        if self.conn is not None:
            self.conn.close()
        self.conn = None

    def get(self, url, timeout=120):
        import http.client
        from urllib.parse import urlsplit

        if self.used >= self.cap:
            raise CapReached(self.used)
        u = urlsplit(url)
        for attempt in (0, 1):
            if self.conn is None or self.host != u.hostname:
                self._close()
                self.conn = http.client.HTTPSConnection(u.hostname, context=self.ctx, timeout=timeout)
                self.host = u.hostname
            try:
                self.conn.request("GET", u.path, headers=self.base_headers)
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
            keep = {k: resp.getheader(k) for k in ("Last-Modified", "ETag", "Content-Length")}
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
    def __init__(self, out, http, clock=None, sleep=time.sleep, models=None, pause_file=None, stop_file=None,
                 bytes_per_s=4_000_000, hourly_mb=1500.0, min_free_gb=20.0, cap_gb=20.0, first_run=FORWARD_FIRST):
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.http = http
        self.clock = clock or (lambda: dt.datetime.now(UTC))
        self.sleep = sleep
        self.models = {m: MODELS[m] for m in (models or MODELS)} if not isinstance(models, dict) else models
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

    def _run_dir(self, model, run):
        return self._p(model, run.strftime("%Y%m%d%H"))

    def log_event(self, event, **kw):
        append_jsonl(self._p("events.jsonl"), {"event": event, "at_utc": _iso(self.clock()), **kw})

    def slots(self, model):
        return [(p, s) for p, steps in self.models[model]["products"].items() for s in steps]

    def open_runs(self, now):
        out = []
        for model, spec in self.models.items():
            first_try = dt.timedelta(hours=spec["first_try_h"])
            t = (now - CLOSE_AFTER - dt.timedelta(hours=24)).replace(minute=0, second=0, microsecond=0)
            while t <= now:
                if t.hour in spec["cycles"] and t >= self.first_run and now >= t + first_try:
                    if not self.run_state(model, t)["done"]:
                        out.append((model, t))
                t += dt.timedelta(hours=1)
        return out

    def run_state(self, model, run):
        key = (model, run)
        st = self.runs.get(key)
        if st is None:
            rows = read_jsonl(self._run_dir(model, run) / "index.jsonl")
            st = {"rows": rows, "ok": set(), "closed": set(), "tries": defaultdict(int),
                  "done": (self._run_dir(model, run) / "manifest.json").exists()}
            for r in rows:
                if r.get("kind") != "file":
                    continue
                slot = (r["product"], r["step"])
                if r.get("status") == "ok":
                    st["ok"].add(slot)
                elif r.get("status") == "missing":
                    st["closed"].add(slot)
                elif r.get("status") != "not_yet":
                    st["tries"][slot] += 1
            self.runs[key] = st
        return st

    def _append(self, model, run, rec):
        append_jsonl(self._run_dir(model, run) / "index.jsonl", rec)
        self.runs[(model, run)]["rows"].append(rec)

    def _guard(self):
        if not self.throttle.allow(self.clock(), SIZE_HINT):
            self.log_event("hourly_byte_ceiling")
            return False
        if shutil.disk_usage(self.out).free < self.min_free or dir_bytes(self.out) > self.cap:
            self.log_event("disk_guard")
            return False
        return True

    def fetch_file(self, model, product, run, step):
        """One file; returns (file row, point rows). Status ok, not_yet (404), http_*, fetch_error or invalid."""
        url = file_url(model, product, run, step)
        base = {"kind": "file", "model": model, "product": product, "run_utc": run.isoformat(), "step": step,
                "url": url}
        u0, w0 = self.http.used, time.time()
        try:
            r = self.http.get(url)
        except CapReached:
            raise
        except Exception as e:
            return {**base, "status": "fetch_error", "error": repr(e)[:300], "fetched_utc": _iso(self.clock())}, []
        fetched = self.clock()
        self.throttle.spent(self.http.used - u0, time.time() - w0)
        if r.status_code == 404:
            return {**base, "status": "not_yet", "fetched_utc": _iso(fetched)}, []
        if r.status_code != 200:
            return {**base, "status": f"http_{r.status_code}", "fetched_utc": _iso(fetched)}, []
        rec = {**base, "fetched_utc": _iso(fetched), "sha256": sha256(r.content), "bytes": len(r.content),
               "last_modified_utc": _lm(r.headers), "etag": r.headers.get("ETag")}
        ensemble = self.models[model]["members"] is not None
        window = PRODUCTS[product][5]
        points = []
        try:
            if rec["last_modified_utc"] is None:
                raise ValueError("no Last-Modified header")
            msgs = split_messages(r.content)
            want = self.models[model]["members"] or 1
            if len(msgs) != want:
                raise ValueError(f"{len(msgs)} messages, expected {want}")
            members, grid = [], None
            for msg in msgs:
                meta, vals = decode_message(msg)
                check_meta(meta, product, run, step, ensemble)
                member = meta["member"] if ensemble else None
                if ensemble and meta.get("n_members") != want:
                    raise ValueError(f"ensemble size {meta.get('n_members')} != {want}")
                members.append(member)
                grid = meta["grid"]
                end = run + dt.timedelta(hours=step)
                start = end - dt.timedelta(hours=window)
                for market, icao, lat, lon, tz in STATIONS:
                    c = corners(grid, lat, lon)
                    pv = point_values(vals, c)
                    if not 150.0 < pv["bilinear_k"] < 350.0:
                        raise ValueError(f"{icao}: implausible {pv['bilinear_k']} K")
                    points.append({"kind": "point", "model": model, "product": product, "run_utc": run.isoformat(),
                                   "step": step, "valid_utc": _iso(end), "window_h": window,
                                   "start_utc": _iso(start), "member": member, "market": market, "icao": icao,
                                   **pv, "grid_lat": c["grid_lat"], "grid_lon": c["grid_lon"],
                                   **local_fields(start, end, tz), "file_sha256": rec["sha256"],
                                   "last_modified_utc": rec["last_modified_utc"], "fetched_utc": rec["fetched_utc"]})
            if ensemble and sorted(members) != list(range(want)):
                raise ValueError(f"members {sorted(members)} != 0..{want - 1}")
            rec.update(status="ok", messages=len(msgs), points=len(points),
                       grid={k: grid[k] for k in ("template", "ni", "nj", "la1", "lo1", "di", "dj", "scan")})
        except CapReached:
            raise
        except Exception as e:
            rec.update(status="invalid", error=repr(e)[:300])
            points = []
        return rec, points

    def work_run(self, model, run, now):
        st = self.run_state(model, run)
        late = now >= run + dt.timedelta(hours=self.models[model]["first_try_h"]) + LATE
        fetched, blocked = 0, set()
        for product, step in self.slots(model):
            slot = (product, step)
            if slot in st["ok"] or slot in st["closed"] or product in blocked:
                continue
            if now >= run + CLOSE_AFTER or st["tries"][slot] >= MAX_TRIES:
                rec = {"kind": "file", "model": model, "product": product, "run_utc": run.isoformat(), "step": step,
                       "status": "missing", "tries": st["tries"][slot], "closed_utc": _iso(self.clock())}
                self._append(model, run, rec)
                st["closed"].add(slot)
                append_jsonl(self._p("gaps.jsonl"), {"gap": "missing", **rec})
                continue
            if not self._guard():
                return fetched
            rec, points = self.fetch_file(model, product, run, step)
            if rec["status"] == "not_yet" and not late:
                blocked.add(product)  # later steps of this product are not published either
                continue
            if rec["status"] == "not_yet":
                rec["status"] = "http_404_late"
            if points:
                append_jsonl_many(self._run_dir(model, run) / "points.jsonl", points)
            self._append(model, run, rec)
            if rec["status"] == "ok":
                st["ok"].add(slot)
                fetched += 1
            else:
                st["tries"][slot] += 1
                self.log_event("fetch_failed", model=model, run=run.isoformat(), product=product, step=step,
                               status=rec["status"])
        if all(s in st["ok"] or s in st["closed"] for s in self.slots(model)):
            self.finalize(model, run)
        return fetched

    def finalize(self, model, run):
        st = self.run_state(model, run)
        d = self._run_dir(model, run)
        self._append(model, run, {"kind": "run_done", "model": model, "run_utc": run.isoformat(), "ok": len(st["ok"]),
                                  "missing": len(st["closed"]), "closed_utc": _iso(self.clock())})
        ok = [r for r in st["rows"] if r.get("kind") == "file" and r.get("status") == "ok"]
        pts = d / "points.jsonl"
        write_json_atomic(d / "manifest.json", {
            "schema": SCHEMA, "model": model, "run_utc": run.isoformat(),
            "source": "ECCC MSC Datamart (dd.weather.gc.ca), dated archive",
            "slots": {p: list(s) for p, s in self.models[model]["products"].items()},
            "slots_ok": sorted([list(s) for s in st["ok"]]), "slots_missing": sorted([list(s) for s in st["closed"]]),
            "files": len(ok), "file_sha256": {f"{r['product']}:{r['step']}": r["sha256"] for r in ok},
            "index_sha256": sha256((d / "index.jsonl").read_bytes()),
            "points_sha256": sha256(pts.read_bytes()) if pts.exists() else None,
            "max_last_modified_utc": max((r["last_modified_utc"] for r in ok), default=None),
            "max_fetched_utc": max((r["fetched_utc"] for r in ok), default=None),
            "stations": [{"market": m, "icao": i, "lat": la, "lon": lo, "tz": tz} for m, i, la, lo, tz in STATIONS],
            "recorder_sha256": self.code_sha256, "written_utc": _iso(self.clock())})
        st["done"] = True
        self.log_event("run_done", model=model, run=run.isoformat(), ok=len(st["ok"]), missing=len(st["closed"]))

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
            for model, run in self.open_runs(now):
                runs.append(f"{model}:{run.isoformat()}")
                fetched += self.work_run(model, run, now)
        return {"fetched_files": fetched, "open_runs": runs, "paused": paused}

    def status(self, state, extra=None):
        write_json_atomic(self._p("status.json"), {
            "state": state, "pid": os.getpid(), "updated_utc": _iso(self.clock()), "bytes_this_process": self.http.used,
            "requests_this_process": self.http.requests, "cpu_s": round(time.process_time(), 2),
            "paused": self.paused_since is not None, "recorder_sha256": self.code_sha256, **(extra or {})})

    def run(self, poll_s=600, max_steps=None):
        self.log_event("start", pid=os.getpid(), code=code_identity(), models=sorted(self.models))
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


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=r"C:\t\eccc_gem\forward")
    ap.add_argument("--models", default="hrdps,rdps,gdps,geps")
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
    args = ap.parse_args(argv)
    models = tuple(m.strip() for m in args.models.split(",") if m.strip())
    if not models or set(models) - set(MODELS):
        raise SystemExit(f"--models must be within {sorted(MODELS)}")
    out = Path(args.out)
    if _REPO in out.resolve().parents or out.resolve() == _REPO:
        raise SystemExit("output must be outside the repository")
    out.mkdir(parents=True, exist_ok=True)
    lock = acquire_lock(out / "recorder.lock", args.wait_lock_seconds)  # noqa: F841 - held until exit
    prio = set_below_normal_priority()
    first = dt.datetime.fromisoformat(args.first_run) if args.first_run else FORWARD_FIRST
    rec = Recorder(out, Http(int(args.net_cap_gb * 1e9)), models=models, pause_file=args.pause_file,
                   stop_file=args.stop_file, bytes_per_s=args.bytes_per_second, hourly_mb=args.hourly_mb,
                   min_free_gb=args.min_free_gb, cap_gb=args.cap_gb, first_run=first)
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
