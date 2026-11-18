"""Lane L13: DWD MOSMIX forward-capture recorder (MOSMIX-L every issue, MOSMIX-S every hour) for the 12 markets.

Free official data from ``opendata.dwd.de`` (anonymous HTTPS, no key, no credentials). Design note:
``docs/research/mosmix-forward-recorder-2026-10-29.md``. Research / shadow only: nothing imports this module,
nothing is served, and no outcome, price or label is read. No model work on MOSMIX until about 45 days exist.

* **MOSMIX-L** (issues 03, 09, 15, 21 UTC, 247 hourly steps, 114 elements): the per-station product
  ``MOSMIX_L/single_stations/<id>/kml/MOSMIX_L_<YYYYMMDDHH>_<id>.kmz`` (about 11-17 KB each). Its placemark is
  byte-identical to the station's placemark in the 78 MB all-stations file (checked 2026-10-29 on the 09Z issue,
  station 72494) and carries the same server ``Last-Modified``. The raw KMZ is kept for every issue.
* **MOSMIX-S** (hourly issues, 240 steps, 40 elements): only an all-stations file exists (about 36 MB). It is
  downloaded, its sha256 recorded, and our stations' placemarks are cut out byte-exact into a small subset KMZ (the
  original header up to the first placemark, our placemarks in pinned order, the original trailer). The raw file
  is kept for ``--s-raw-retain-days`` (default 7) and then pruned; the index keeps its sha256, size and
  ``Last-Modified`` forever, and the subset records the raw sha it was cut from.

Point in time by construction: every file gets an index row with the issue time (file name and the document's
``IssueTime``), the server ``Last-Modified`` and ETag, our fetch time and the sha256. ``issue_available`` picks, for
a cutoff, the newest issue whose ``Last-Modified`` (and, for the live variant, our fetch time) is at or before it.
A late fetch (backfill after an outage; DWD keeps about 48 h of issues) is recorded with its true fetch time.

Per UTC issue date D: ``<out>/<D>/index.jsonl`` (append-only, fsynced) and, once every issue of D is fetched or
closed missing, ``<out>/<D>/manifest.json`` pinning the index sha256, every kept file's sha256, the station map and
the recorder's own sha256. Guards as the GEFS forward recorder: below-normal priority, bytes/s throttle and hourly
ceiling, a per-process network byte cap, a pause file (gaps logged), a STOP file, a single-instance lock, a
free-disk floor and an output-size cap. Forward issues only (>= FORWARD_FIRST).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import os
import re
import shutil
import sys
import time
import traceback
import zipfile
from collections import defaultdict
from email.utils import parsedate_to_datetime
from pathlib import Path

UTC = dt.timezone.utc
SCHEMA = "mosmix_forward/1"
FORWARD_FIRST = dt.datetime(2026, 10, 29, 15, tzinfo=UTC)  # first issue the recorder may ask for
BASE = "https://opendata.dwd.de/weather/local_forecasts/mos"
L_ISSUE_HOURS = (3, 9, 15, 21)
S_ISSUE_HOURS = tuple(range(24))
FIRST_TRY = {"L": dt.timedelta(minutes=60), "S": dt.timedelta(minutes=30)}  # published ~+72-77 min (L), ~+40 (S)
CLOSE_AFTER = dt.timedelta(hours=44)  # DWD keeps ~48 h (8 L issues, 48 S issues); later slots close as missing
MAX_TRIES = 8                         # failed GETs (not 404 before publication) per slot before it is closed

# market -> pinned MOSMIX station. Coordinates and elevation are the placemark's (2-decimal degrees, metres); ours
# are config/locations.json. ``role``: primary (nearest point), secondary (recorded because the primary is poor).
STATIONS = (
    # market,         id,      icao,  mos_lat, mos_lon,  mos_el, our_lat,   our_lon,    our_el, role
    ("toronto",       "71624", "CYYZ", 43.67,  -79.63,   173.0,  43.679,    -79.629,    171,  "primary"),
    ("nyc",           "72503", "KLGA", 40.77,  -73.90,   7.0,    40.7769,   -73.874,    9,    "primary"),
    ("atlanta",       "72219", "KATL", 33.65,  -84.42,   312.0,  33.62972,  -84.44223,  309,  "primary"),
    ("austin",        "72254", "KAUS", 30.30,  -97.70,   193.0,  30.1831,   -97.68063,  148,  "primary"),
    ("chicago",       "72530", "KORD", 41.98,  -87.90,   203.0,  41.96017,  -87.93161,  202,  "primary"),
    ("dallas",        "72259", "KDAL", 32.90,  -97.03,   182.0,  32.83836,  -96.83584,  148,  "primary"),
    ("denver",        "72469", "KBKF", 39.75,  -104.87,  1625.0, 39.713,    -104.758,   1703, "primary"),
    ("denver",        "72565", "KBKF", 39.87,  -104.67,  1656.0, 39.713,    -104.758,   1703, "secondary"),
    ("houston",       "72243", "KHOU", 29.97,  -95.35,   30.0,   29.64582,  -95.28214,  13,   "primary"),
    ("houston",       "72242", "KHOU", 29.30,  -94.80,   2.0,    29.64582,  -95.28214,  13,   "secondary"),
    ("los-angeles",   "72295", "KLAX", 33.93,  -118.40,  38.0,   33.93817,  -118.3866,  30,   "primary"),
    ("miami",         "72202", "KMIA", 25.82,  -80.28,   3.0,    25.78806,  -80.31692,  1,    "primary"),
    ("san-francisco", "72494", "KSFO", 37.62,  -122.38,  6.0,    37.61961,  -122.36561, 2,    "primary"),
    ("seattle",       "72793", "KSEA", 47.45,  -122.30,  130.0,  47.44467,  -122.31442, 115,  "primary"),
)
STATION_IDS = tuple(s[1] for s in STATIONS)
NS_DWD = "https://opendata.dwd.de/weather/lib/pointforecast_dwd_extension_V1_0.xsd"
PM_OPEN, PM_CLOSE = b"<kml:Placemark>", b"</kml:Placemark>"
NAME_RE = re.compile(rb"<kml:name>([^<]*)</kml:name>")
COORD_RE = re.compile(rb"<kml:coordinates>([^<]*)</kml:coordinates>")
ISSUE_RE = re.compile(rb"<dwd:IssueTime>([^<]*)</dwd:IssueTime>")
MODEL_RE = re.compile(rb'<dwd:Model dwd:name="([^"]*)" dwd:referenceTime="([^"]*)"/>')


def _iso(t):
    return t.astimezone(UTC).isoformat()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def haversine_km(lat1, lon1, lat2, lon2):
    import math

    p = math.radians
    x = math.sin(p(lat2 - lat1) / 2) ** 2 + math.cos(p(lat1)) * math.cos(p(lat2)) * math.sin(p(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(x))


def station_table():
    """The mapping table of the design note: our station -> MOSMIX id, distance and elevation difference."""
    out = []
    for market, sid, icao, mlat, mlon, mel, olat, olon, oel, role in STATIONS:
        out.append({"market": market, "icao": icao, "mosmix_id": sid, "role": role,
                    "distance_km": round(haversine_km(olat, olon, mlat, mlon), 1),
                    "elevation_diff_m": round(mel - oel, 1), "mosmix_lat": mlat, "mosmix_lon": mlon,
                    "mosmix_elev_m": mel, "our_lat": olat, "our_lon": olon, "our_elev_m": oel})
    return out


# --------------------------------------------------------------------------- names and parsing
def issue_name(product, issue, sid=None):
    stamp = issue.strftime("%Y%m%d%H")
    if product == "L":
        return f"MOSMIX_L_{stamp}_{sid}.kmz"
    return f"MOSMIX_S_{stamp}_240.kmz"


def issue_url(product, issue, sid=None):
    if product == "L":
        return f"{BASE}/MOSMIX_L/single_stations/{sid}/kml/{issue_name('L', issue, sid)}"
    return f"{BASE}/MOSMIX_S/all_stations/kml/{issue_name('S', issue)}"


def issues_between(product, start, end):
    """Nominal issue instants of ``product`` in [start, end]."""
    hours = L_ISSUE_HOURS if product == "L" else S_ISSUE_HOURS
    t = start.replace(minute=0, second=0, microsecond=0)
    if t < start:
        t += dt.timedelta(hours=1)
    out = []
    while t <= end:
        if t.hour in hours:
            out.append(t)
        t += dt.timedelta(hours=1)
    return out


def kml_of(kmz_bytes):
    """The single KML member of a KMZ (refuses anything else)."""
    with zipfile.ZipFile(io.BytesIO(kmz_bytes)) as z:
        names = z.namelist()
        if len(names) != 1 or not names[0].endswith(".kml"):
            raise ValueError(f"unexpected KMZ members {names}")
        return names[0], z.read(names[0])


def header_meta(kml_head):
    m = ISSUE_RE.search(kml_head)
    if not m:
        raise ValueError("no IssueTime")
    return {"issue_time_doc": m.group(1).decode(),
            "referenced_models": [[a.decode(), b.decode()] for a, b in MODEL_RE.findall(kml_head)]}


def check_placemark(pm, sid):
    """Placemark identity against the pin: name and coordinates (lon, lat, elevation)."""
    name = NAME_RE.search(pm)
    if not name or name.group(1).decode() != sid:
        raise ValueError(f"placemark name {name.group(1) if name else None!r} != {sid}")
    lon, lat, el = (float(x) for x in COORD_RE.search(pm).group(1).decode().split(","))
    pin = next(s for s in STATIONS if s[1] == sid)
    if (round(lat, 2), round(lon, 2), el) != (pin[3], pin[4], pin[5]):
        raise ValueError(f"{sid}: coordinates {(lat, lon, el)} differ from pin {pin[3:6]}")


def split_placemarks(stream, wanted, chunk=1 << 22):
    """Stream a KML: (head bytes before the first placemark, {id: placemark bytes} for ``wanted``, tail bytes)."""
    buf, head, found, tail = b"", None, {}, b""
    while True:
        data = stream.read(chunk)
        buf += data
        if head is None:
            i = buf.find(PM_OPEN)
            if i < 0:
                if not data:
                    raise ValueError("no placemark")
                continue
            head, buf = buf[:i], buf[i:]
        while True:
            i = buf.find(PM_OPEN)
            j = buf.find(PM_CLOSE, i + 1) if i >= 0 else -1
            if i < 0 or j < 0:
                break
            pm = buf[i:j + len(PM_CLOSE)]
            name = NAME_RE.search(pm)
            if name and name.group(1).decode() in wanted:
                found[name.group(1).decode()] = pm
            buf = buf[j + len(PM_CLOSE):]
        if not data:
            tail = buf
            break
    return head, found, tail


def s_subset(kmz_bytes, wanted=STATION_IDS):
    """Byte-exact 12(+2)-station cut of an all-stations S file: (subset KML bytes, meta)."""
    with zipfile.ZipFile(io.BytesIO(kmz_bytes)) as z:
        names = z.namelist()
        if len(names) != 1:
            raise ValueError(f"unexpected KMZ members {names}")
        with z.open(names[0]) as fh:
            head, found, tail = split_placemarks(fh, set(wanted))
    missing = [s for s in wanted if s not in found]
    for sid, pm in found.items():
        check_placemark(pm, sid)
    body = head + b"".join(found[s] for s in wanted if s in found) + tail
    return names[0], body, {**header_meta(head), "stations_missing": missing}


def read_series(kml_bytes, sid, elements=("TTT", "TX", "TN")):
    """{element: [values]} plus the time steps for one station (validation and tests only; no model work)."""
    import xml.etree.ElementTree as ET

    root = ET.fromstring(kml_bytes)
    steps = [e.text for e in root.iter(f"{{{NS_DWD}}}TimeStep")]
    for pm in root.iter("{http://www.opengis.net/kml/2.2}Placemark"):
        if pm.find("{http://www.opengis.net/kml/2.2}name").text != sid:
            continue
        out = {"steps": steps}
        for fc in pm.iter(f"{{{NS_DWD}}}Forecast"):
            name = fc.get(f"{{{NS_DWD}}}elementName")
            if name in elements:
                out[name] = [None if v == "-" else float(v) for v in fc[0].text.split()]
        return out
    raise KeyError(sid)


# --------------------------------------------------------------------------- point in time
def issue_available(rows, product, cutoff_utc, sid=None, require_fetched=False):
    """Newest ok index row of ``product`` (and station) whose Last-Modified (and our fetch, if required) is at
    or before ``cutoff_utc``; None if there is none."""
    best = None
    for r in rows:
        if r.get("product") != product or r.get("status") != "ok" or (sid and r.get("station") != sid):
            continue
        avail = dt.datetime.fromisoformat(r["last_modified_utc"])
        if require_fetched:
            avail = max(avail, dt.datetime.fromisoformat(r["fetched_utc"]))
        if avail <= cutoff_utc and (best is None or r["issue_utc"] > best["issue_utc"]):
            best = r
    return best


# --------------------------------------------------------------------------- storage and guards
def append_jsonl(path, rec):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")
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


def write_bytes_atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def write_json_atomic(path, obj):
    write_bytes_atomic(path, (json.dumps(obj, indent=1, sort_keys=True) + "\n").encode("utf-8"))


def dir_bytes(path):
    return sum(p.stat().st_size for p in Path(path).rglob("*") if p.is_file())


def git_blob_id(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def code_identity():
    raw = Path(__file__).read_bytes()
    return {"mosmix_forward_recorder.py": {"git_blob_lf": git_blob_id(raw.replace(b"\r\n", b"\n")),
                                           "sha256": sha256(raw)}}


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
    """Persistent HTTPS GET client with a per-process byte cap; returns status, body and the headers we keep."""

    def __init__(self, cap_bytes, user_agent="weather-research-l13-mosmix-forward/1 (serial; DWD open data)"):
        import ssl

        self.ctx = ssl.create_default_context()
        self.headers = {"User-Agent": user_agent, "Accept-Encoding": "identity"}
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
                self.conn.request("GET", u.path, headers=self.headers)
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


# --------------------------------------------------------------------------- recorder
class Recorder:
    def __init__(self, out, http, clock=None, sleep=time.sleep, products=("L", "S"), pause_file=None,
                 stop_file=None, bytes_per_s=2_000_000, hourly_mb=200.0, min_free_gb=20.0, cap_gb=60.0,
                 s_raw_retain_days=7, first_issue=FORWARD_FIRST):
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.http = http
        self.clock = clock or (lambda: dt.datetime.now(UTC))
        self.sleep = sleep
        self.products = tuple(products)
        self.pause_file = Path(pause_file) if pause_file else self.out / "RECORDER_PAUSE"
        self.stop_file = Path(stop_file) if stop_file else self.out / "STOP"
        self.throttle = Throttle(bytes_per_s, int(hourly_mb * 1e6), sleep)
        self.min_free, self.cap = min_free_gb * 1e9, cap_gb * 1e9
        self.s_retain = dt.timedelta(days=s_raw_retain_days)
        self.first_issue = max(first_issue, FORWARD_FIRST)
        self.paused_since = None
        self.days = {}
        self.code_sha256 = sha256(Path(__file__).read_bytes())

    def _p(self, *parts):
        return self.out.joinpath(*parts)

    def log_event(self, event, **kw):
        append_jsonl(self._p("events.jsonl"), {"event": event, "at_utc": _iso(self.clock()), **kw})

    # slots: (product, issue_iso, station or "ALL")
    def slots_of_day(self, day):
        start = dt.datetime(day.year, day.month, day.day, tzinfo=UTC)
        out = []
        for product in self.products:
            for issue in issues_between(product, start, start + dt.timedelta(hours=23)):
                if issue < self.first_issue:
                    continue
                stations = STATION_IDS if product == "L" else ("ALL",)
                out.extend((product, issue.isoformat(), s) for s in stations)
        return out

    def day_state(self, day):
        st = self.days.get(day)
        if st is None:
            rows = read_jsonl(self._p(day.isoformat(), "index.jsonl"))
            st = {"rows": rows, "ok": set(), "closed": set(), "tries": defaultdict(int),
                  "done": self._p(day.isoformat(), "manifest.json").exists()}
            for r in rows:
                slot = (r.get("product"), r.get("issue_utc"), r.get("station"))
                if r.get("status") == "ok":
                    st["ok"].add(slot)
                elif r.get("status") == "missing":
                    st["closed"].add(slot)
                elif r.get("kind") == "file":
                    st["tries"][slot] += 1
            self.days[day] = st
        return st

    def active_days(self, now):
        out = []
        for back in (2, 1, 0):
            day = now.date() - dt.timedelta(days=back)
            if dt.datetime(day.year, day.month, day.day, 23, tzinfo=UTC) < self.first_issue:
                continue
            if not self.day_state(day)["done"]:
                out.append(day)
        return out

    def _append(self, day, rec):
        append_jsonl(self._p(day.isoformat(), "index.jsonl"), rec)
        self.days[day]["rows"].append(rec)

    def _guard(self, size_hint):
        if not self.throttle.allow(self.clock(), size_hint):
            self.log_event("hourly_byte_ceiling")
            return False
        if shutil.disk_usage(self.out).free < self.min_free or dir_bytes(self.out) > self.cap:
            self.log_event("disk_guard")
            return False
        return True

    def fetch_slot(self, day, slot):
        """One GET. Returns the index row (status ok / not_yet / http_<n> / invalid / fetch_error)."""
        product, issue_iso, sid = slot
        issue = dt.datetime.fromisoformat(issue_iso)
        url = issue_url(product, issue, None if sid == "ALL" else sid)
        base = {"kind": "file", "product": product, "issue_utc": issue_iso, "station": sid, "url": url}
        u0, w0 = self.http.used, time.time()
        try:
            r = self.http.get(url)
        except CapReached:
            raise
        except Exception as e:
            return {**base, "status": "fetch_error", "error": repr(e)[:300], "fetched_utc": _iso(self.clock())}
        fetched = self.clock()
        self.throttle.spent(self.http.used - u0, time.time() - w0)
        if r.status_code == 404:
            return {**base, "status": "not_yet", "fetched_utc": _iso(fetched)}
        if r.status_code != 200:
            return {**base, "status": f"http_{r.status_code}", "fetched_utc": _iso(fetched)}
        lm = r.headers.get("Last-Modified")
        rec = {**base, "fetched_utc": _iso(fetched), "bytes": len(r.content), "sha256": sha256(r.content),
               "etag": r.headers.get("ETag"),
               "last_modified_utc": _iso(parsedate_to_datetime(lm)) if lm else None}
        try:
            if rec["last_modified_utc"] is None:
                raise ValueError("no Last-Modified header")
            if r.headers.get("Content-Length") and int(r.headers["Content-Length"]) != len(r.content):
                raise ValueError("short body")
            rel = Path(product) / issue.strftime("%Y%m%d%H") / issue_name(product, issue, sid)
            if product == "L":
                member, kml = kml_of(r.content)
                head = kml[:kml.find(PM_OPEN)]
                pm = kml[kml.find(PM_OPEN):kml.find(PM_CLOSE) + len(PM_CLOSE)]
                check_placemark(pm, sid)
                meta = header_meta(head)
                write_bytes_atomic(self.out / rel, r.content)
                rec.update(path=rel.as_posix(), kml_member=member, kml_sha256=sha256(kml), retained="raw")
            else:
                member, body, meta = s_subset(r.content)
                sub = io.BytesIO()
                with zipfile.ZipFile(sub, "w", zipfile.ZIP_DEFLATED) as z:
                    info = zipfile.ZipInfo(member, date_time=(1980, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    z.writestr(info, body)
                sub_rel = rel.with_name(rel.stem + "_subset.kmz")
                write_bytes_atomic(self.out / rel, r.content)
                write_bytes_atomic(self.out / sub_rel, sub.getvalue())
                rec.update(path=rel.as_posix(), subset_path=sub_rel.as_posix(), subset_sha256=sha256(sub.getvalue()),
                           subset_kml_sha256=sha256(body), retained="raw+subset")
            if dt.datetime.fromisoformat(meta["issue_time_doc"].replace("Z", "+00:00")) != issue:
                raise ValueError(f"IssueTime {meta['issue_time_doc']} != {issue_iso}")
            rec.update(meta)
            rec["status"] = "ok"
        except Exception as e:
            rec.update(status="invalid", error=repr(e)[:300])
        return rec

    def work_day(self, day, now):
        st = self.day_state(day)
        fetched = 0
        not_yet = set()  # (product, issue): first 404 skips the issue's other stations this pass
        for slot in self.slots_of_day(day):
            product, issue_iso, sid = slot
            if slot in st["ok"] or slot in st["closed"] or (product, issue_iso) in not_yet:
                continue
            issue = dt.datetime.fromisoformat(issue_iso)
            if now < issue + FIRST_TRY[product]:
                continue
            if now >= issue + CLOSE_AFTER or st["tries"][slot] >= MAX_TRIES:
                rec = {"kind": "file", "product": product, "issue_utc": issue_iso, "station": sid,
                       "status": "missing", "tries": st["tries"][slot], "closed_utc": _iso(self.clock())}
                self._append(day, rec)
                st["closed"].add(slot)
                append_jsonl(self._p("gaps.jsonl"), {"gap": "missing", **rec})
                continue
            if not self._guard(40_000_000 if product == "S" else 20_000):
                return fetched
            rec = self.fetch_slot(day, slot)
            if rec["status"] == "not_yet":
                not_yet.add((product, issue_iso))
                continue  # publication not visible yet: not a failure, not indexed
            self._append(day, rec)
            if rec["status"] == "ok":
                st["ok"].add(slot)
                fetched += 1
            else:
                st["tries"][slot] += 1
                self.log_event("fetch_failed", slot=list(slot), status=rec["status"])
        slots = self.slots_of_day(day)
        if slots and all(s in st["ok"] or s in st["closed"] for s in slots):
            self.finalize(day)
        return fetched

    def finalize(self, day):
        st = self.day_state(day)
        ok = [r for r in st["rows"] if r.get("status") == "ok"]
        self._append(day, {"kind": "date_done", "date": day.isoformat(), "ok": len(st["ok"]),
                           "missing": len(st["closed"]), "closed_utc": _iso(self.clock())})
        idx = self._p(day.isoformat(), "index.jsonl")
        files = {}
        for r in ok:
            files[r["path"]] = r["sha256"]
            if r.get("subset_path"):
                files[r["subset_path"]] = r["subset_sha256"]
        write_json_atomic(self._p(day.isoformat(), "manifest.json"), {
            "schema": SCHEMA, "date": day.isoformat(), "index_file": idx.name,
            "index_sha256": sha256(idx.read_bytes()), "files_sha256": dict(sorted(files.items())),
            "stations": station_table(), "products": list(self.products),
            "recorder_sha256": self.code_sha256, "ok": len(st["ok"]), "missing": len(st["closed"]),
            "max_last_modified_utc": max((r["last_modified_utc"] for r in ok), default=None),
            "max_fetched_utc": max((r["fetched_utc"] for r in ok), default=None),
            "written_utc": _iso(self.clock())})
        st["done"] = True
        self.log_event("date_done", date=day.isoformat(), ok=len(st["ok"]), missing=len(st["closed"]))

    def prune_s_raw(self, now):
        """Delete raw S files older than the retention; their sha256, size and Last-Modified stay in the index and
        the subset (byte-exact for our stations) stays. Logged per file in pruned.jsonl."""
        root = self._p("S")
        if not root.exists() or self.s_retain <= dt.timedelta(0):
            return 0
        n = 0
        for d in sorted(root.iterdir()):
            try:
                issue = dt.datetime.strptime(d.name, "%Y%m%d%H").replace(tzinfo=UTC)
            except ValueError:
                continue
            if issue >= now - self.s_retain:
                break
            for f in d.glob("MOSMIX_S_*_240.kmz"):
                append_jsonl(self._p("pruned.jsonl"), {"path": f.relative_to(self.out).as_posix(),
                                                       "sha256": sha256(f.read_bytes()), "bytes": f.stat().st_size,
                                                       "pruned_utc": _iso(now)})
                f.unlink()
                n += 1
        return n

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
        fetched, days = 0, []
        if not paused:
            for day in self.active_days(now):
                days.append(day.isoformat())
                fetched += self.work_day(day, now)
            pruned = self.prune_s_raw(now)
            if pruned:
                self.log_event("pruned_s_raw", files=pruned)
        return {"fetched": fetched, "active_days": days, "paused": paused}

    def status(self, state, extra=None):
        write_json_atomic(self._p("status.json"), {
            "state": state, "pid": os.getpid(), "updated_utc": _iso(self.clock()), "bytes_this_process": self.http.used,
            "requests_this_process": self.http.requests, "cpu_s": round(time.process_time(), 2),
            "paused": self.paused_since is not None, "recorder_sha256": self.code_sha256, **(extra or {})})

    def run(self, poll_s=300, max_steps=None):
        self.log_event("start", pid=os.getpid(), code=code_identity(), products=list(self.products))
        steps = 0
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
            steps += 1
            if max_steps is not None and steps >= max_steps:
                return
            self.sleep(poll_s)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=r"C:\t\mosmix\forward")
    ap.add_argument("--products", default="L,S", help="comma list of L and S")
    ap.add_argument("--pause-file", default=None, help="default <out>/RECORDER_PAUSE")
    ap.add_argument("--stop-file", default=None, help="default <out>/STOP")
    ap.add_argument("--wait-lock-seconds", type=float, default=0.0)
    ap.add_argument("--poll-seconds", type=int, default=300)
    ap.add_argument("--bytes-per-second", type=int, default=2_000_000)
    ap.add_argument("--hourly-mb", type=float, default=200.0)
    ap.add_argument("--net-cap-gb", type=float, default=50.0, help="network byte cap for this process")
    ap.add_argument("--cap-gb", type=float, default=60.0, help="output directory size cap")
    ap.add_argument("--min-free-gb", type=float, default=20.0)
    ap.add_argument("--s-raw-retain-days", type=float, default=7.0)
    ap.add_argument("--max-steps", type=int, default=None)
    ap.add_argument("--once", action="store_true", help="one foreground pass over the open issues, then exit")
    ap.add_argument("--first-issue", default=None, help="UTC ISO; not before the built-in forward start")
    ap.add_argument("--print-stations", action="store_true")
    args = ap.parse_args(argv)
    if args.print_stations:
        print(json.dumps(station_table(), indent=1))
        return 0
    out = Path(args.out)
    repo = Path(__file__).resolve().parents[2]
    if repo in out.resolve().parents or out.resolve() == repo:
        raise SystemExit("output must be outside the repository")
    out.mkdir(parents=True, exist_ok=True)
    lock = acquire_lock(out / "recorder.lock", args.wait_lock_seconds)  # noqa: F841 - held until exit
    prio = set_below_normal_priority()
    first = dt.datetime.fromisoformat(args.first_issue) if args.first_issue else FORWARD_FIRST
    products = tuple(p.strip().upper() for p in args.products.split(",") if p.strip())
    if not products or set(products) - {"L", "S"}:
        raise SystemExit(f"--products must be L and/or S: {args.products}")
    rec = Recorder(out, Http(int(args.net_cap_gb * 1e9)), products=products, pause_file=args.pause_file,
                   stop_file=args.stop_file, bytes_per_s=args.bytes_per_second, hourly_mb=args.hourly_mb,
                   min_free_gb=args.min_free_gb, cap_gb=args.cap_gb, s_raw_retain_days=args.s_raw_retain_days,
                   first_issue=first)
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
