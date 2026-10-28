"""Lane L13: forward GEFS 06Z member recorder for the L6_G forward test (feature G of rule R-O / rule_rn.md).

Records, day by day from 2026-10-28 on, exactly the inputs dev G was built from, so forward G is byte-comparable
with the dev corpus ``C:/t/l11pb/gefs/corpus`` (manifest module_sha256 c898d94a..., rows 8f512ad9...):

* Source: free official NOAA GEFS v12 on the AWS open bucket ``noaa-gefs-pds`` (anonymous HTTPS, no key, no
  credentials). Product ``pgrb2sp25``, the 06Z cycle of target date D, members ``gec00`` + ``gep01..gep30``, steps
  f006..f024, the single ``TMP:2 m above ground`` message located through ``.idx`` and read with a Range request.
* Extraction: ``gefs_member_point_fetch`` (L11, blob 5094c74e, sha256 c898d94a) is imported unchanged: its GRIB2
  decoder, identity checks, ``station_corners`` and ``bilinear``. The station geometry is pinned to the dev manifest
  and the recorder refuses to start if the registry would give different corners. Rows carry the dev row fields
  unchanged plus an availability receipt: our fetch times, the idx sha256 and the listing time.
* Point in time (rule_rn.md L36-38, ``ro_member_highs``): G at (market, D, h) uses only messages whose S3
  ``LastModified`` (max of the ``.grib2`` and its ``.idx``) is at or before h:00 local; a member counts only if every
  needed step qualifies; G needs >= 25 of the 30 perturbed members. ``g_value(..., require_fetched=True)`` is the
  stricter live variant that also requires our own fetch to be at or before h:00 local.

Output: ``<out>/<D>/gefs_member_rows.jsonl`` (append-only, every line fsynced) and ``<out>/<D>/manifest.json``
(written atomically once D is complete or its deadline passes, with the rows sha256 and the G table for h07..h12).
Guards as the HRRR forward recorder: below-normal priority, bytes/s throttle and hourly ceiling, a pause file (gaps
logged, a late fetch is recorded with its true fetch time), a STOP file, a single-instance lock, a free-disk floor
and an output-size cap. Forward dates only (>= FORWARD_FIRST); the archive path for the parity check refuses any date
after 2026-09-29. Research / shadow only: nothing imports this module, nothing is served, no outcome, price or label
is read.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import sys
import time
import traceback
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from tools.research import gefs_member_point_fetch as g
except ImportError:  # run as a script from tools/research
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import gefs_member_point_fetch as g

UTC = dt.timezone.utc
FORWARD_FIRST = dt.date(2026, 10, 28)
DEV_LAST = g.LAST_ALLOWED  # 2026-09-29: the archive (parity) path never reads a later date
HOURS = (7, 8, 9, 10, 11, 12)  # RUNG_HOURS
MIN_MEMBERS = 25
PERTURBED = tuple(f"gep{k:02d}" for k in range(1, 31))
RULE_RN_SHA256 = "a9ca45f063a39b8ad2408414aab4658d5f4f96c855a51d11b34236b8045fa18c"
DEV_MODULE_SHA256 = "c898d94ae10264839cdddab5072b72c7821411acb402e03c262a7106206680a8"
POLL_START = dt.timedelta(hours=9, minutes=15)  # first listing poll after the 06Z cycle (f006..f024 ~09:35-10:01Z)
DEADLINE = dt.timedelta(hours=24)               # D+1 00:00Z: unfinished slots are closed as missing
MAX_TRIES = 3
SCHEMA = "l6g_gefs_forward_points/1"
DEV_ROW_KEYS = ("available_utc", "cycle_hour", "cycle_utc", "date", "ensemble_type", "etag", "fh",
                "grib_last_modified", "idx_last_modified", "idx_record", "key", "kind", "member", "message_sha256",
                "perturbation", "points", "product", "range", "status", "valid_utc")
# Station geometry of the dev corpus manifest (C:/t/l11pb/gefs/corpus/manifest.json); corners recomputed and compared.
DEV_STATIONS = {
    "atlanta": (33.62972, -84.44223, "America/New_York"), "austin": (30.1831, -97.68063, "America/Chicago"),
    "chicago": (41.96017, -87.93161, "America/Chicago"), "dallas": (32.83836, -96.83584, "America/Chicago"),
    "denver": (39.713, -104.758, "America/Denver"), "houston": (29.64582, -95.28214, "America/Chicago"),
    "los-angeles": (33.93817, -118.3866, "America/Los_Angeles"), "miami": (25.78806, -80.31692, "America/New_York"),
    "nyc": (40.7769, -73.874, "America/New_York"), "san-francisco": (37.61961, -122.36561, "America/Los_Angeles"),
    "seattle": (47.44467, -122.31442, "America/Los_Angeles"),
}
DEV_CELLS = {"atlanta": (1102, 225), "austin": (1049, 239), "chicago": (1088, 192), "dallas": (1052, 228),
             "denver": (1020, 201), "houston": (1058, 241), "los-angeles": (966, 224), "miami": (1118, 256),
             "nyc": (1144, 196), "san-francisco": (950, 209), "seattle": (950, 170)}


def _iso(t):
    return t.astimezone(UTC).isoformat()


def _sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pinned_geometry(stations=None):
    """(stations, corners) for the eleven markets, refusing anything that differs from the dev corpus geometry."""
    g.configure()  # R-O defaults: 06Z, sp25, f006..f024, cycle date = D
    if (g.CYCLE_HOUR, g.FHS, g.PRODUCT, g.CYCLE_DAY_OFFSET) != (6, (6, 9, 12, 15, 18, 21, 24), "sp25", 0):
        raise SystemExit("gefs_member_point_fetch is not on the R-O 06Z sp25 configuration")
    stations = stations if stations is not None else g.registry_stations()
    if set(stations) != set(DEV_STATIONS):
        raise SystemExit(f"station set {sorted(stations)} != dev corpus")
    corners = {}
    for m, (lat, lon, tz) in DEV_STATIONS.items():
        s = stations[m]
        if (float(s["lat"]), float(s["lon"]), s["tz"]) != (lat, lon, tz):
            raise SystemExit(f"{m}: registry {s} differs from the dev corpus station")
        c = g.station_corners(lat, lon)
        if (c["i0"], c["j0"]) != DEV_CELLS[m]:
            raise SystemExit(f"{m}: corner {c} differs from the dev corpus")
        corners[m] = c
    return {m: {"lat": v[0], "lon": v[1], "tz": v[2]} for m, v in DEV_STATIONS.items()}, corners


# --------------------------------------------------------------------------- listing and one message
def member_listing(f, day, member):
    """S3 listing of member's f006..f024 objects (+ .idx) of the 06Z cycle of ``day``: {key: {last_modified,...}}."""
    stem = f"{g.cycle_prefix(day)}{member}.t{g.CYCLE_HOUR:02d}z.{g.PRODUCTS[g.PRODUCT]['stem']}.f"
    params = {"list-type": "2", "prefix": stem + "0", "start-after": stem + "005", "max-keys": "40"}
    r = f.get(g.BUCKET + "/", params=params)
    if r.status_code != 200:
        raise RuntimeError(f"listing {member} {day}: HTTP {r.status_code}")
    page, _ = g.parse_listing(r.content)
    return page


def extract_message(f, day, member, fh, gent, ient, corners, clock):
    """One (member, fh) row: the dev corpus row (fetch_date's fields, same decoder and checks) plus the receipt."""
    key = g.grib_key(day, member, fh)
    cycle = dt.datetime(day.year, day.month, day.day, g.CYCLE_HOUR, tzinfo=UTC)
    base = {"kind": "message", "date": day.isoformat(), "member": member, "fh": fh, "key": key,
            "cycle_utc": cycle.isoformat(), "valid_utc": (cycle + dt.timedelta(hours=fh)).isoformat(),
            "product": g.PRODUCT, "cycle_hour": g.CYCLE_HOUR}
    r = f.get(f"{g.BUCKET}/{key}.idx")
    idx_at = clock()
    receipt = {"idx_fetched_utc": _iso(idx_at), "grib_last_modified": gent["last_modified"],
               "idx_last_modified": ient["last_modified"]}
    if r.status_code != 200:
        return {**base, **receipt, "status": f"idx_http_{r.status_code}"}
    receipt["idx_sha256"] = hashlib.sha256(r.content).hexdigest()
    start, end, rec = g.find_range(g.parse_idx(r.text), g.VAR, gent["size"])
    r = f.get(f"{g.BUCKET}/{key}", headers={"Range": f"bytes={start}-{end}"}, expect=(206,))
    receipt["fetched_utc"] = _iso(clock())
    if r.status_code != 206 or len(r.content) != end - start + 1:
        return {**base, **receipt, "status": f"range_http_{r.status_code}"}
    blob = r.content
    sha = hashlib.sha256(blob).hexdigest()
    try:
        meta, field = g.decode_field(blob)
        want_pert = 0 if member == "gec00" else int(member[3:])
        ident = (meta["discipline"], meta["category"], meta["number"], meta["surface_type"], meta["surface_value"])
        if ident != (0, 0, 0, 103, 2.0):
            raise ValueError(f"identity {ident}")
        if meta["ref_time_utc"] != cycle.isoformat() or meta["fh"] != fh:
            raise ValueError(f"time {meta['ref_time_utc']} f{meta['fh']}")
        if meta["perturbation"] != want_pert:
            raise ValueError(f"perturbation {meta['perturbation']} != {want_pert}")
    except Exception as exc:
        return {**base, **receipt, "status": "decode_error", "error": str(exc), "message_sha256": sha}
    points = {}
    for m, c in corners.items():
        value, four = g.bilinear(field, c)
        points[m] = {"bilinear_k": value, "corners_k": four}
    return {**base, **receipt, "status": "ok", "message_sha256": sha, "range": [start, end], "idx_record": rec,
            "etag": gent["etag"],
            "available_utc": max(g.parse_s3_time(gent["last_modified"]),
                                 g.parse_s3_time(ient["last_modified"])).isoformat(),
            "ensemble_type": meta["ensemble_type"], "perturbation": meta["perturbation"], "points": points,
            "bytes": len(blob)}


# --------------------------------------------------------------------------- feature G (rule R-O, L36-49)
def kelvin_to_f(k):
    return (float(k) - 273.15) * 9.0 / 5.0 + 32.0


def table_from_rows(rows, require_fetched=False):
    """{(market, date): [(member, valid, available, value_F)]} as ro_load_gefs; with ``require_fetched`` the
    availability is max(LastModified, our fetch time) (live variant)."""
    table = defaultdict(list)
    for r in rows:
        if r.get("kind") != "message" or r.get("status") != "ok":
            continue
        valid = dt.datetime.fromisoformat(r["valid_utc"])
        avail = dt.datetime.fromisoformat(r["available_utc"])
        if require_fetched:
            if "fetched_utc" not in r:
                continue
            avail = max(avail, dt.datetime.fromisoformat(r["fetched_utc"]))
        for market, p in r["points"].items():
            table[(market, r["date"])].append((r["member"], valid, avail, kelvin_to_f(p["bilinear_k"])))
    return table


def member_highs(table, market, day, cutoff_utc, tz):
    """ro_member_highs: {member: max over the 06Z f006..f024 nodes valid on local date ``day``} for members whose
    every such node is present with available <= ``cutoff_utc``."""
    zone = ZoneInfo(tz)
    d = day if isinstance(day, dt.date) else dt.date.fromisoformat(str(day)[:10])
    cycle = dt.datetime(d.year, d.month, d.day, 6, tzinfo=UTC)
    want = {cycle + dt.timedelta(hours=fh) for fh in (6, 9, 12, 15, 18, 21, 24)}
    want = {v for v in want if v.astimezone(zone).date() == d}
    if not want:
        return {}
    by_member = defaultdict(dict)
    for member, valid, avail, value in table.get((market, d.isoformat()), []):
        if valid in want and avail <= cutoff_utc:
            by_member[member][valid] = value
    return {m: max(v.values()) for m, v in by_member.items() if set(v) == want}


def cutoff_utc(day, hour, tz):
    d = dt.date.fromisoformat(str(day)[:10])
    return dt.datetime(d.year, d.month, d.day, int(hour), tzinfo=ZoneInfo(tz)).astimezone(UTC)


def g_value(table, market, day, hour, tz):
    """ro_gefs_value: mean of the perturbed members' highs at cutoff h:00 local, None below 25 members."""
    d = dt.date.fromisoformat(str(day)[:10])
    highs = [v for m, v in member_highs(table, market, d, cutoff_utc(d, hour, tz), tz).items() if m in PERTURBED]
    if len(highs) < MIN_MEMBERS:
        return None
    return float(sum(highs) / len(highs))


def g_table(rows, stations, day, require_fetched=False):
    table = table_from_rows(rows, require_fetched)
    return {m: {f"h{h:02d}": g_value(table, m, day, h, s["tz"]) for h in HOURS} for m, s in sorted(stations.items())}


# --------------------------------------------------------------------------- storage and guards
def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:  # a torn last line after a hard kill; later lines are still read
                continue
    return out


def write_json_atomic(path, obj):
    path = Path(path)
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
    for name, path in (("gefs_forward_recorder.py", Path(__file__)), ("gefs_member_point_fetch.py", Path(g.__file__))):
        raw = path.read_bytes()
        out[name] = {"git_blob_lf": git_blob_id(raw.replace(b"\r\n", b"\n")), "sha256": hashlib.sha256(raw).hexdigest()}
    try:
        import subprocess

        head = subprocess.run(["git", "-C", str(Path(__file__).parent), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=20)
        out["head"] = head.stdout.strip() or None
    except Exception as e:  # pragma: no cover - git absent
        out["head"] = None
        out["git_error"] = repr(e)[:200]
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
    """Single-instance lock for the life of the process; ``wait_s`` > 0 allows a handover."""
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


class _LiteResp:
    def __init__(self, status, content):
        self.status_code, self.content = status, content

    @property
    def text(self):
        return self.content.decode("utf-8", "replace")


class LiteSession:
    """Persistent-HTTPS GET client with one TLS context (the HRRR forward recorder's client)."""

    def __init__(self, user_agent="weather-research-l13-gefs-forward/1 (serial; free NOAA open data)"):
        import ssl

        self.ctx = ssl.create_default_context()
        self.headers = {"User-Agent": user_agent, "Accept-Encoding": "identity"}
        self.conn, self.host = None, None

    def _close(self):
        if self.conn is not None:
            self.conn.close()
        self.conn = None

    def get(self, url, headers=None, params=None, timeout=90):
        import http.client
        from urllib.parse import urlencode, urlsplit

        u = urlsplit(url)
        path = (u.path or "/") + ("?" + urlencode(params) if params else ("?" + u.query if u.query else ""))
        for attempt in (0, 1):
            if self.conn is None or self.host != u.hostname:
                self._close()
                self.conn = http.client.HTTPSConnection(u.hostname, context=self.ctx, timeout=timeout)
                self.host = u.hostname
            try:
                self.conn.request("GET", path, headers={**self.headers, **(headers or {})})
                resp = self.conn.getresponse()
                body = resp.read()
            except (http.client.HTTPException, OSError):
                self._close()
                if attempt:
                    raise
                continue
            if (resp.getheader("Connection") or "").lower() == "close":
                self._close()
            return _LiteResp(resp.status, body)


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
    def __init__(self, out, fetcher, stations=None, clock=None, sleep=time.sleep, pause_file=None, stop_file=None,
                 bytes_per_s=2_000_000, hourly_mb=600.0, min_free_gb=20.0, cap_mb=2000.0, disk_root=None,
                 first_day=FORWARD_FIRST):
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.stations, self.corners = pinned_geometry(stations)
        self.f = fetcher
        self.clock = clock or (lambda: dt.datetime.now(UTC))
        self.sleep = sleep
        self.pause_file = Path(pause_file) if pause_file else self.out / "RECORDER_PAUSE"
        self.stop_file = Path(stop_file) if stop_file else self.out / "STOP"
        self.throttle = Throttle(bytes_per_s, int(hourly_mb * 1e6), sleep)
        self.min_free, self.cap = min_free_gb * 1e9, cap_mb * 1e6
        self.disk_root = disk_root or str(self.out)
        self.first_day = max(first_day, FORWARD_FIRST)
        self.paused_since = None
        self.days = {}
        self.code = {"gefs_forward_recorder.py": _sha_file(__file__),
                     "gefs_member_point_fetch.py": _sha_file(g.__file__)}

    def _p(self, *parts):
        return self.out.joinpath(*parts)

    def log_event(self, event, **kw):
        g.append_jsonl(self._p("events.jsonl"), {"event": event, "at_utc": _iso(self.clock()), **kw})

    def day_state(self, day):
        st = self.days.get(day)
        if st is None:
            d = self._p(day.isoformat())
            rows = read_jsonl(d / "gefs_member_rows.jsonl")
            st = {"rows": rows, "ok": {(r["member"], r["fh"]) for r in rows if r.get("status") == "ok"},
                  "tries": defaultdict(int), "listing": {}, "listed_at": {},
                  "done": (d / "manifest.json").exists() or any(r.get("kind") == "date_done" for r in rows)}
            for r in rows:
                if r.get("kind") == "message" and r.get("status") != "ok":
                    st["tries"][(r["member"], r["fh"])] += 1
            self.days[day] = st
        return st

    def active_days(self, now):
        """Cycle dates to work on now: today and yesterday (UTC), forward only, not finished."""
        out = []
        for back in (1, 0):
            day = now.date() - dt.timedelta(days=back)
            start = dt.datetime(day.year, day.month, day.day, tzinfo=UTC)
            if day < self.first_day or now < start + POLL_START:
                continue
            if not self.day_state(day)["done"]:
                out.append(day)
        return out

    def _append(self, day, rec):
        d = self._p(day.isoformat())
        d.mkdir(parents=True, exist_ok=True)
        g.append_jsonl(d / "gefs_member_rows.jsonl", rec)
        self.days[day]["rows"].append(rec)

    def work_day(self, day, now):
        st = self.day_state(day)
        fetched = 0
        for member in g.MEMBERS:
            if all((member, fh) in st["ok"] or st["tries"][(member, fh)] >= MAX_TRIES for fh in g.FHS):
                continue
            page = member_listing(self.f, day, member)
            t = _iso(self.clock())
            for key, ent in page.items():
                if st["listing"].get(key) != ent:
                    if key in st["listing"]:
                        self.log_event("listing_changed", key=key, old=st["listing"][key], new=ent)
                    st["listing"][key] = ent
                    st["listed_at"].setdefault(key, t)
            for fh in g.FHS:
                slot = (member, fh)
                if slot in st["ok"] or st["tries"][slot] >= MAX_TRIES:
                    continue
                key = g.grib_key(day, member, fh)
                gent, ient = st["listing"].get(key), st["listing"].get(key + ".idx")
                if not gent or not ient:
                    continue
                if not self.throttle.allow(self.clock(), 1_000_000):
                    self.log_event("hourly_byte_ceiling")
                    return fetched
                if shutil.disk_usage(self.disk_root).free < self.min_free or dir_bytes(self.out) > self.cap:
                    self.log_event("disk_guard")
                    return fetched
                u0, w0 = self.f.used, time.time()
                try:
                    rec = extract_message(self.f, day, member, fh, gent, ient, self.corners, self.clock)
                except (ValueError, LookupError, RuntimeError) as e:
                    rec = {"kind": "message", "date": day.isoformat(), "member": member, "fh": fh, "key": key,
                           "status": "fetch_error", "error": str(e)[:300]}
                self.throttle.spent(self.f.used - u0, time.time() - w0)
                rec["listed_utc"] = st["listed_at"].get(key)
                self._append(day, rec)
                if rec["status"] == "ok":
                    st["ok"].add(slot)
                    fetched += 1
                else:
                    st["tries"][slot] += 1
                    self.log_event("fetch_failed", key=key, status=rec["status"])
        start = dt.datetime(day.year, day.month, day.day, tzinfo=UTC)
        complete = all((m, fh) in st["ok"] or st["tries"][(m, fh)] >= MAX_TRIES for m in g.MEMBERS for fh in g.FHS)
        if complete or now >= start + DEADLINE:
            self.finalize(day)
        return fetched

    def finalize(self, day):
        st = self.day_state(day)
        for m in g.MEMBERS:
            for fh in g.FHS:
                if (m, fh) not in st["ok"] and st["tries"][(m, fh)] == 0:
                    self._append(day, {"kind": "message", "date": day.isoformat(), "member": m, "fh": fh,
                                       "key": g.grib_key(day, m, fh), "status": "object_missing",
                                       "closed_utc": _iso(self.clock())})
        ok_rows = [r for r in st["rows"] if r.get("status") == "ok"]
        self._append(day, {"kind": "date_done", "date": day.isoformat(), "ok": len(st["ok"]),
                           "missing": len(g.MEMBERS) * len(g.FHS) - len(st["ok"]),
                           "bytes": sum(r.get("bytes", 0) for r in ok_rows), "closed_utc": _iso(self.clock())})
        rows_path = self._p(day.isoformat(), "gefs_member_rows.jsonl")
        lm = [r["available_utc"] for r in ok_rows]
        fetched = [r["fetched_utc"] for r in ok_rows]
        write_json_atomic(self._p(day.isoformat(), "manifest.json"), {
            "schema": SCHEMA, "date": day.isoformat(), "rows_file": rows_path.name,
            "rows_sha256": _sha_file(rows_path), "stations": self.stations, "corners": self.corners,
            "cycle_hour_utc": g.CYCLE_HOUR, "fhs": list(g.FHS), "product": g.PRODUCT,
            "product_dir": g.PRODUCTS[g.PRODUCT]["dir"], "grid": g.GEFS_GRID, "members": list(g.MEMBERS),
            "variable": g.VAR, "bucket": g.BUCKET, "module_sha256": self.code["gefs_member_point_fetch.py"],
            "recorder_sha256": self.code["gefs_forward_recorder.py"], "rule_rn_sha256": RULE_RN_SHA256,
            "ok": len(st["ok"]), "max_available_utc": max(lm) if lm else None,
            "max_fetched_utc": max(fetched) if fetched else None,
            "g_lastmodified_rule": g_table(ok_rows, self.stations, day),
            "g_fetched_rule": g_table(ok_rows, self.stations, day, require_fetched=True),
            "written_utc": _iso(self.clock())})
        st["done"] = True
        self.log_event("date_done", date=day.isoformat(), ok=len(st["ok"]))

    def step(self):
        now = self.clock()
        paused = self.pause_file.exists()
        if paused and self.paused_since is None:
            self.paused_since = now
            self.log_event("pause_start")
            g.append_jsonl(self._p("gaps.jsonl"), {"gap": "pause_start", "at_utc": _iso(now)})
        elif not paused and self.paused_since is not None:
            g.append_jsonl(self._p("gaps.jsonl"), {"gap": "pause_end", "at_utc": _iso(now),
                                                  "started_utc": _iso(self.paused_since)})
            self.log_event("pause_end")
            self.paused_since = None
        fetched, days = 0, []
        if not paused:
            for day in self.active_days(now):
                days.append(day.isoformat())
                fetched += self.work_day(day, now)
        return {"fetched": fetched, "active_days": days, "paused": paused}

    def next_wake(self, now, poll_s):
        if any(not self.day_state(d)["done"] for d in self.active_days(now)):
            return float(poll_s)
        nxt = dt.datetime(now.year, now.month, now.day, tzinfo=UTC) + POLL_START
        if nxt <= now:
            nxt += dt.timedelta(days=1)
        return float(max(1.0, min(900.0, (nxt - now).total_seconds())))  # wakes at least every 15 min (STOP)

    def status(self, state, extra=None):
        write_json_atomic(self._p("status.json"), {
            "state": state, "pid": os.getpid(), "updated_utc": _iso(self.clock()), "bytes_this_process": self.f.used,
            "requests_this_process": self.f.requests, "cpu_s": round(time.process_time(), 2),
            "paused": self.paused_since is not None, "code_sha256": self.code, **(extra or {})})

    def run(self, poll_s=120, max_steps=None):
        self.log_event("start", pid=os.getpid(), code=code_identity())
        steps = 0
        while True:
            if self.stop_file.exists():
                self.log_event("stop_file")
                self.status("stopped_by_file")
                return
            try:
                self.status("running", self.step())
            except g.CapReached:
                self.log_event("cap_reached")
                self.status("cap_reached")
                return
            except Exception as e:  # keep recording; the failure is logged
                self.log_event("step_error", error=repr(e)[:500], tb=traceback.format_exc()[-1500:])
                self.status("running_after_error")
            steps += 1
            if max_steps is not None and steps >= max_steps:
                return
            self.sleep(self.next_wake(self.clock(), poll_s))


# --------------------------------------------------------------------------- archive path for the parity check
def parity_day(f, day, corners, clock=None):
    """The recorder's listing + extraction for an archived dev date (<= 2026-09-29 only); returns the rows."""
    if day > DEV_LAST:
        raise SystemExit(f"parity refuses dates after {DEV_LAST}: {day}")
    clock = clock or (lambda: dt.datetime.now(UTC))
    rows = []
    for member in g.MEMBERS:
        listing = member_listing(f, day, member)
        for fh in g.FHS:
            key = g.grib_key(day, member, fh)
            if key in listing and key + ".idx" in listing:
                rows.append(extract_message(f, day, member, fh, listing[key], listing[key + ".idx"], corners, clock))
            else:
                rows.append({"kind": "message", "date": day.isoformat(), "member": member, "fh": fh, "key": key,
                             "status": "object_missing"})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=r"C:\t\l6g\forward\gefs")
    ap.add_argument("--pause-file", default=None, help="default <out>/RECORDER_PAUSE")
    ap.add_argument("--stop-file", default=None, help="default <out>/STOP")
    ap.add_argument("--wait-lock-seconds", type=float, default=0.0)
    ap.add_argument("--poll-seconds", type=int, default=120)
    ap.add_argument("--bytes-per-second", type=int, default=2_000_000)
    ap.add_argument("--hourly-mb", type=float, default=600.0)
    ap.add_argument("--cap-gb", type=float, default=30.0, help="hard network byte cap for this process")
    ap.add_argument("--cap-mb", type=float, default=2000.0, help="output directory size cap")
    ap.add_argument("--min-free-gb", type=float, default=20.0)
    ap.add_argument("--max-steps", type=int, default=None)
    ap.add_argument("--once-day", default=None, help="manual foreground fetch of one forward cycle date, then exit")
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    repo = Path(__file__).resolve().parents[2]
    if repo in out.resolve().parents or out.resolve() == repo:
        raise SystemExit("output must be outside the repository")
    lock = acquire_lock(out / "recorder.lock", args.wait_lock_seconds)  # noqa: F841 - held until exit
    prio = set_below_normal_priority()
    rec = Recorder(out, g.Fetcher(int(args.cap_gb * 1e9), session=LiteSession()), pause_file=args.pause_file,
                   stop_file=args.stop_file, bytes_per_s=args.bytes_per_second, hourly_mb=args.hourly_mb,
                   min_free_gb=args.min_free_gb, cap_mb=args.cap_mb)
    rec.log_event("priority", below_normal=prio)
    if args.once_day:
        day = dt.date.fromisoformat(args.once_day)
        if day < FORWARD_FIRST or day > rec.clock().date():
            raise SystemExit(f"--once-day must be a forward cycle date in [{FORWARD_FIRST}, today]")
        rec.log_event("once_day", date=day.isoformat(), code=code_identity())
        n = rec.work_day(day, rec.clock())
        rec.status("once_day_done", {"date": day.isoformat(), "fetched": n})
        print(json.dumps({"date": day.isoformat(), "fetched": n, "ok": len(rec.day_state(day)["ok"]),
                          "done": rec.day_state(day)["done"]}))
        return 0
    (out / "recorder.pid").write_text(str(os.getpid()), encoding="ascii")
    rec.run(args.poll_seconds, args.max_steps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
