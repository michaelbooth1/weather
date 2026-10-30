"""Lane L8: Open-Meteo Previous Runs forward recorder, receipt-dated, so that run-to-run drift becomes testable.

Ledger row 81 recorded Previous Runs drift as UNTESTABLE. The capture writes ``run_to_run_high_change: None``, the
replay has no previous-runs source, and the archive caches carry no capture-time receipt. This recorder supplies
that receipt going forward. Design note: ``docs/research/om-prev-runs-forward-recorder-2026-10-30.md``.

Research / shadow only. Nothing imports this module and nothing is served. It reads no outcome, settlement, label
or price.

* **What is fetched.** Once per UTC hour, in the hour's window [HH:20, HH:50), one public request per market:
  ``GET https://previous-runs-api.open-meteo.com/v1/forecast`` with a fixed query:
  - ``hourly=temperature_2m,temperature_2m_previous_day1..7``;
  - ``models=best_match,gfs_seamless,gfs_global,ncep_hrrr_conus,ncep_nbm_conus,ecmwf_ifs025,gem_seamless``
    (``gfs_global`` is the pure GFS run: on this endpoint ``gfs_seamless`` repeats HRRR in its range and equals
    ``best_match`` in the US);
  - the market's settlement unit;
  - ``timezone=GMT``, ``past_days=2``, ``forecast_days=3``.

  The request uses the free endpoint over plain HTTPS: no key, no cookies, no auth header. Station coordinates,
  unit and time zone come from the built-in market registry (``weather.market.market_registry.BUILTIN_SPECS``).
* **What is kept, per market.**
  - The raw response body, verbatim, with ``response_sha256`` over its bytes.
  - ``fetched_at_utc``: the local clock once the body has been read in full. This is the receipt.
  - ``request_started_utc``, the server ``Date`` header, the HTTP status and the exact URL.
  - A parse summary: hours returned, the series present and missing, and non-null counts.
* **Per cycle.** All rows of the hour and one ``cycle`` record go into a single fsynced append to
  ``<out>/<YYYYMMDD>/prev_runs.jsonl`` (UTC day). The cycle record carries ``rows_sha256`` and either ``complete``
  or the reasons the cycle is incomplete.
  - Readers trust rows only when a cycle record with the same ``slot_utc`` and a matching ``rows_sha256`` follows
    them.
  - When a UTC day is over, ``<out>/<YYYYMMDD>/manifest.json`` records the counts and the file sha256.
* **No backfill.** A slot is attempted only inside its window, and a missed slot is written to ``gaps.jsonl``. A
  late fetch would carry a later receipt, so it would not be the same evidence.

The guards follow the L13 and L3 recorders: below-normal priority, a request throttle, an hourly request ceiling,
a per-process byte cap, a pause file, a STOP file, a single-instance lock, a free-disk floor and an output-size
cap. The URL allowlist refuses anything except the fixed query above, at the registry's coordinates.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import shutil
import sys
import time
import traceback
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]

UTC = dt.timezone.utc
SCHEMA = "l8_om_prev_runs_forward/1"
HOST = "previous-runs-api.open-meteo.com"
PATH = "/v1/forecast"
MARKETS = ("toronto", "nyc", "atlanta", "miami", "austin", "chicago", "dallas", "houston", "denver", "los-angeles",
           "san-francisco", "seattle")
MODELS = ("best_match", "gfs_seamless", "gfs_global", "ncep_hrrr_conus", "ncep_nbm_conus", "ecmwf_ifs025",
          "gem_seamless")
PREVIOUS_DAYS = 7
VARIABLES = ("temperature_2m",) + tuple(f"temperature_2m_previous_day{n}" for n in range(1, PREVIOUS_DAYS + 1))
PAST_DAYS, FORECAST_DAYS = 2, 3
UNITS = {"F": "fahrenheit", "C": "celsius"}
SLOT = dt.timedelta(hours=1)
SLOT_OFFSET = dt.timedelta(minutes=20)
SLOT_GRACE = dt.timedelta(minutes=30)
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
COORD_DECIMALS = 5


def _iso(t):
    return None if t is None else t.astimezone(UTC).isoformat().replace("+00:00", "Z")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def slot_floor(t):
    t = t.astimezone(UTC)
    return t.replace(minute=0, second=0, microsecond=0)


def series_names():
    """Every hourly key the response must carry: ``<variable>_<model>`` (Open-Meteo's multi-model naming)."""
    return tuple(f"{v}_{m}" for m in MODELS for v in VARIABLES)


def coord(x):
    return f"{float(x):.{COORD_DECIMALS}f}"


def query_for(lat, lon, unit):
    """The fixed query, in a fixed order."""
    if unit not in UNITS:
        raise ValueError(f"unit must be one of {sorted(UNITS)}: {unit!r}")
    return [("latitude", coord(lat)), ("longitude", coord(lon)), ("hourly", ",".join(VARIABLES)),
            ("models", ",".join(MODELS)), ("temperature_unit", UNITS[unit]), ("timezone", "GMT"),
            ("past_days", str(PAST_DAYS)), ("forecast_days", str(FORECAST_DAYS))]


def url_for(lat, lon, unit):
    return f"https://{HOST}{PATH}?{urlencode(query_for(lat, lon, unit), safe=',')}"


# --------------------------------------------------------------------------- parsing
def _finite(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return False
    return math.isfinite(x)


def parse_response(content):
    """Summary of a Previous Runs reply: hours, the series present or missing, and non-null counts per series.

    The body is never altered; this summary only says whether the reply is usable. ``ok`` requires every series of
    ``series_names()``, a ``time`` axis of the expected length, every series as long as the axis, and at least
    one finite value overall."""
    try:
        payload = json.loads(content)
    except (ValueError, UnicodeDecodeError):
        return {"ok": False, "reason": "bad_json"}
    if not isinstance(payload, dict):
        return {"ok": False, "reason": "not_an_object"}
    if payload.get("error"):
        return {"ok": False, "reason": "api_error", "api_reason": str(payload.get("reason"))[:300]}
    hourly = payload.get("hourly")
    if not isinstance(hourly, dict) or not isinstance(hourly.get("time"), list):
        return {"ok": False, "reason": "no_hourly_time"}
    times = hourly["time"]
    expected_hours = 24 * (PAST_DAYS + FORECAST_DAYS)
    present, missing, bad_length, non_null = [], [], [], {}
    for name in series_names():
        values = hourly.get(name)
        if not isinstance(values, list):
            missing.append(name)
            continue
        present.append(name)
        if len(values) != len(times):
            bad_length.append(name)
        non_null[name] = sum(_finite(v) for v in values)
    extra = sorted(k for k in hourly if k != "time" and k not in set(series_names()))
    units = payload.get("hourly_units") or {}
    unit_values = sorted({str(units.get(n)) for n in present})
    out = {"n_times": len(times), "first_time": times[0] if times else None, "last_time": times[-1] if times else None,
           "series_present": len(present), "series_missing": missing, "series_bad_length": bad_length,
           "series_extra": extra, "non_null": non_null, "units": unit_values,
           "utc_offset_seconds": payload.get("utc_offset_seconds"), "grid_latitude": payload.get("latitude"),
           "grid_longitude": payload.get("longitude"), "grid_elevation": payload.get("elevation"),
           "generationtime_ms": payload.get("generationtime_ms")}
    reasons = []
    if len(times) != expected_hours:
        reasons.append(f"n_times_{len(times)}_not_{expected_hours}")
    if missing:
        reasons.append("series_missing")
    if bad_length:
        reasons.append("series_bad_length")
    if payload.get("utc_offset_seconds") not in (0, None):
        reasons.append("not_gmt")
    if not any(non_null.values()):
        reasons.append("all_null")
    out["ok"] = not reasons
    out["reason"] = ",".join(reasons) if reasons else None
    return out


# --------------------------------------------------------------------------- storage and guards
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


def markets_from_registry():
    """{market: {icao, lat, lon, unit, tz}} from the built-in registry only (never an external override)."""
    if os.environ.get("WEATHER_MARKET_REGISTRY"):
        raise SystemExit("WEATHER_MARKET_REGISTRY is set; this recorder reads the built-in registry only")
    src = _REPO / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from weather.market.market_registry import BUILTIN_SPECS

    specs = {s.id: s for s in BUILTIN_SPECS}
    out = {}
    for m in MARKETS:
        s = specs.get(m)
        if s is None or s.display_unit not in UNITS or not (-90 <= s.lat <= 90 and -180 <= s.lon <= 180):
            raise SystemExit(f"{m}: missing or unexpected built-in spec")
        out[m] = {"icao": s.icao, "lat": float(s.lat), "lon": float(s.lon), "unit": s.display_unit,
                  "tz": s.timezone}
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


class Refused(ValueError):
    pass


def check_url(method, url, allowed_coords=None):
    """Only GET of the fixed Previous Runs query; with ``allowed_coords`` the coordinates must be one of them."""
    u = urlsplit(url)
    if (method != "GET" or u.scheme != "https" or u.hostname != HOST or u.path != PATH or u.username
            or u.password or u.port or u.fragment or not u.query):
        raise Refused(f"not the allowlisted Previous Runs read: {method} {url}")
    pairs = parse_qsl(u.query, keep_blank_values=True, strict_parsing=True)
    keys = [k for k, _ in pairs]
    want = [k for k, _ in query_for(0, 0, "F")]
    if keys != want:
        raise Refused(f"query keys {keys} != {want}")
    q = dict(pairs)
    for unit in UNITS:
        fixed = dict(query_for(q["latitude"], q["longitude"], unit)) if _is_coord(q) else None
        if fixed is not None and fixed == q:
            break
    else:
        raise Refused(f"not the fixed Previous Runs query: {url}")
    if allowed_coords is not None and (q["latitude"], q["longitude"]) not in allowed_coords:
        raise Refused(f"coordinates not in the registry: {q['latitude']},{q['longitude']}")


def _is_coord(q):
    try:
        lat, lon = float(q["latitude"]), float(q["longitude"])
    except (KeyError, ValueError):
        return False
    return (-90 <= lat <= 90 and -180 <= lon <= 180 and q["latitude"] == coord(lat)
            and q["longitude"] == coord(lon))


class Resp:
    def __init__(self, status, content, headers):
        self.status_code, self.content, self.headers = status, content, headers


class Http:
    """HTTPS client for the one allowlisted public read, with a per-process byte cap. No cookies, no auth, no key."""

    def __init__(self, cap_bytes, allowed_coords=None,
                 user_agent="weather-research-l8-om-prev-runs-forward/1 (public read-only)"):
        import ssl

        self.ctx = ssl.create_default_context()
        self.base_headers = {"User-Agent": user_agent, "Accept": "application/json", "Accept-Encoding": "identity"}
        self.conn, self.cap, self.allowed = None, cap_bytes, allowed_coords
        self.used, self.requests = 0, 0

    def _close(self):
        if self.conn is not None:
            self.conn.close()
        self.conn = None

    def request(self, method, url, timeout=30):
        import http.client

        check_url(method, url, self.allowed)
        if self.used >= self.cap:
            raise CapReached(self.used)
        u = urlsplit(url)
        for attempt in (0, 1):
            if self.conn is None:
                self.conn = http.client.HTTPSConnection(HOST, context=self.ctx, timeout=timeout)
            try:
                self.conn.request("GET", f"{u.path}?{u.query}", headers=dict(self.base_headers))
                resp = self.conn.getresponse()
                data = resp.read(MAX_RESPONSE_BYTES + 1)
            except (http.client.HTTPException, OSError):
                self._close()
                if attempt:
                    raise
                continue
            self.requests += 1
            self.used += len(data)
            if len(data) > MAX_RESPONSE_BYTES:
                self._close()
                raise ValueError("public reply exceeds byte bound")
            if (resp.getheader("Connection") or "").lower() == "close":
                self._close()
            return Resp(resp.status, data, {"Date": resp.getheader("Date")})


# --------------------------------------------------------------------------- recorder
class Recorder:
    def __init__(self, out, http, markets=None, clock=None, sleep=time.sleep, pause_file=None, stop_file=None,
                 min_interval_s=1.0, hourly_requests=60, min_free_gb=20.0, cap_gb=5.0):
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.http = http
        self.markets = dict(markets) if markets is not None else markets_from_registry()
        self.clock = clock or (lambda: dt.datetime.now(UTC))
        self.sleep = sleep
        self.pause_file = Path(pause_file) if pause_file else self.out / "RECORDER_PAUSE"
        self.stop_file = Path(stop_file) if stop_file else self.out / "STOP"
        self.min_interval, self.hourly_requests = min_interval_s, hourly_requests
        self.min_free, self.cap = min_free_gb * 1e9, cap_gb * 1e9
        self.hour, self.hour_requests, self.last_request = None, 0, None
        self.paused_since = None
        self.last_slot = None
        self.done = {}
        self.code_sha256 = sha256(Path(__file__).read_bytes())

    def _p(self, *parts):
        return self.out.joinpath(*parts)

    def log_event(self, event, **kw):
        append_jsonl_many(self._p("events.jsonl"), [{"event": event, "at_utc": _iso(self.clock()), **kw}])

    def gap(self, **kw):
        append_jsonl_many(self._p("gaps.jsonl"), [{"at_utc": _iso(self.clock()), **kw}])

    def slot_done(self, slot):
        day = f"{slot:%Y%m%d}"
        if day not in self.done:  # read a day's cycle records once per process, then track in memory
            self.done[day] = {r.get("slot_utc") for r in read_jsonl(self._p(day, "prev_runs.jsonl"))
                              if r.get("kind") == "cycle"}
        return _iso(slot) in self.done[day]

    def _guard(self):
        """True when another request may go out now (disk floor, output cap, hourly ceiling, throttle)."""
        if shutil.disk_usage(self.out).free < self.min_free:
            self.log_event("disk_floor")
            return False
        if dir_bytes(self.out) > self.cap:
            self.log_event("output_cap")
            return False
        now = self.clock()
        hour = now.replace(minute=0, second=0, microsecond=0)
        if hour != self.hour:
            self.hour, self.hour_requests = hour, 0
        if self.hour_requests >= self.hourly_requests:
            self.log_event("hourly_ceiling", requests=self.hour_requests)
            return False
        if self.last_request is not None:
            wait = self.min_interval - (time.monotonic() - self.last_request)
            if wait > 0:
                self.sleep(wait)
        self.hour_requests += 1
        self.last_request = time.monotonic()
        return True

    def fetch_market(self, slot, market):
        spec = self.markets[market]
        url = url_for(spec["lat"], spec["lon"], spec["unit"])
        row = {"kind": "fetch", "schema": SCHEMA, "slot_utc": _iso(slot), "market": market, "icao": spec["icao"],
               "lat": spec["lat"], "lon": spec["lon"], "unit": spec["unit"], "models": list(MODELS),
               "variables": list(VARIABLES), "url": url, "request_started_utc": None, "fetched_at_utc": None,
               "http_status": None, "server_date": None, "response_sha256": None, "response_bytes": None,
               "body": None, "parse": None}
        if not self._guard():
            row["status"] = "guard"
            return row
        row["request_started_utc"] = _iso(self.clock())
        try:
            r = self.http.request("GET", url)
        except CapReached:
            raise
        except Exception as e:  # recorded per row; the cycle is marked incomplete
            row.update(status=f"error:{type(e).__name__}", fetched_at_utc=_iso(self.clock()))
            return row
        row["fetched_at_utc"] = _iso(self.clock())
        row.update(http_status=r.status_code, server_date=(r.headers or {}).get("Date"),
                   response_sha256=sha256(r.content), response_bytes=len(r.content))
        try:
            row["body"] = r.content.decode("utf-8")
        except UnicodeDecodeError:
            row["status"] = "not_utf8"
            return row
        parsed = parse_response(r.content)
        row["parse"] = parsed
        if r.status_code != 200:
            row["status"] = f"http_{r.status_code}"
        else:
            row["status"] = "ok" if parsed["ok"] else f"unusable:{parsed['reason']}"
        return row

    def run_slot(self, slot):
        """Fetch every market for the slot; one fsynced append of the rows plus the cycle record."""
        started = self.clock()
        rows, stopped = [], False
        for market in self.markets:
            if self.stop_file.exists():
                stopped = True
                break
            rows.append(self.fetch_market(slot, market))
        reasons = ["stop_file"] if stopped else []
        reasons += [f"{r['market']}:{r['status']}" for r in rows if r["status"] != "ok"]
        if len(rows) < len(self.markets) and not stopped:
            reasons.append("markets_missing")
        body = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows).encode()
        cycle = {"kind": "cycle", "schema": SCHEMA, "slot_utc": _iso(slot), "started_utc": _iso(started),
                 "finished_utc": _iso(self.clock()), "late": started - slot > SLOT_OFFSET + SLOT_GRACE,
                 "markets_expected": len(self.markets), "rows": len(rows),
                 "rows_ok": sum(r["status"] == "ok" for r in rows), "complete": not reasons, "reasons": reasons,
                 "rows_sha256": sha256(body), "recorder_sha256": self.code_sha256}
        append_jsonl_many(self._p(f"{slot:%Y%m%d}", "prev_runs.jsonl"), rows + [cycle])
        self.slot_done(slot)
        self.done[f"{slot:%Y%m%d}"].add(_iso(slot))
        self.log_event("cycle", slot=_iso(slot), complete=cycle["complete"], reasons=reasons[:20])
        return cycle

    def close_day(self, day):
        d = self._p(f"{day:%Y%m%d}")
        f = d / "prev_runs.jsonl"
        if (d / "manifest.json").exists() or not f.exists():
            return
        cycles = [r for r in read_jsonl(f) if r.get("kind") == "cycle"]
        write_json_atomic(d / "manifest.json", {
            "schema": SCHEMA, "utc_day": f"{day:%Y-%m-%d}", "cycles": len(cycles),
            "cycles_complete": sum(c["complete"] for c in cycles),
            "slots_missing": 24 - len({c["slot_utc"] for c in cycles}),
            "file_sha256": sha256(f.read_bytes()), "markets": sorted(self.markets), "models": list(MODELS),
            "recorder_sha256": self.code_sha256, "written_utc": _iso(self.clock())})
        self.log_event("day_closed", day=f"{day:%Y-%m-%d}")

    def in_window(self, now, slot):
        return SLOT_OFFSET <= now - slot < SLOT_OFFSET + SLOT_GRACE

    def step(self):
        """Run the current slot if it is in its window and not done; record missed slots."""
        now = self.clock()
        paused = self.pause_file.exists()
        if paused and self.paused_since is None:
            self.paused_since = now
            self.log_event("pause_start")
            self.gap(gap="pause_start")
        elif not paused and self.paused_since is not None:
            self.gap(gap="pause_end", started_utc=_iso(self.paused_since))
            self.log_event("pause_end")
            self.paused_since = None
        slot = slot_floor(now)
        if self.last_slot is None:  # first step of this process: close any earlier UTC day left open by a restart
            for d in sorted(self.out.glob("[0-9]" * 8)):
                day = dt.datetime.strptime(d.name, "%Y%m%d").replace(tzinfo=UTC)
                if day.date() < slot.date():
                    self.close_day(day)
        else:
            t = self.last_slot
            while t < slot:
                if not self.slot_done(t):
                    self.gap(gap="slot_missed", slot_utc=_iso(t))
                t += SLOT
            if self.last_slot.date() != slot.date():
                self.close_day(self.last_slot)
        self.last_slot = slot
        if paused or not self.in_window(now, slot) or self.slot_done(slot):
            return {"slot": _iso(slot), "ran": False, "paused": paused}
        cycle = self.run_slot(slot)
        return {"slot": _iso(slot), "ran": True, "complete": cycle["complete"], "paused": False}

    def status(self, state, extra=None):
        write_json_atomic(self._p("status.json"), {
            "state": state, "pid": os.getpid(), "updated_utc": _iso(self.clock()), "bytes_this_process": self.http.used,
            "requests_this_process": self.http.requests, "cpu_s": round(time.process_time(), 2),
            "paused": self.paused_since is not None, "recorder_sha256": self.code_sha256, **(extra or {})})

    def run(self, poll_s=30, max_steps=None):
        self.log_event("start", pid=os.getpid(), code=code_identity(), markets=self.markets, models=list(MODELS),
                       variables=list(VARIABLES))
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
    ap.add_argument("--out", default=r"C:\t\om_prev_runs\forward")
    ap.add_argument("--pause-file", default=None, help="default <out>/RECORDER_PAUSE")
    ap.add_argument("--stop-file", default=None, help="default <out>/STOP")
    ap.add_argument("--wait-lock-seconds", type=float, default=0.0)
    ap.add_argument("--poll-seconds", type=int, default=30)
    ap.add_argument("--min-interval-seconds", type=float, default=1.0)
    ap.add_argument("--hourly-requests", type=int, default=60)
    ap.add_argument("--net-cap-gb", type=float, default=5.0, help="network byte cap for this process")
    ap.add_argument("--cap-gb", type=float, default=5.0, help="output directory size cap")
    ap.add_argument("--min-free-gb", type=float, default=20.0)
    ap.add_argument("--max-steps", type=int, default=None)
    ap.add_argument("--once", action="store_true", help="one foreground cycle for the current hour, then exit")
    args = ap.parse_args(argv)
    out = Path(args.out)
    if _REPO in out.resolve().parents or out.resolve() == _REPO:
        raise SystemExit("output must be outside the repository")
    out.mkdir(parents=True, exist_ok=True)
    lock = acquire_lock(out / "recorder.lock", args.wait_lock_seconds)  # noqa: F841 - held until exit
    prio = set_below_normal_priority()
    markets = markets_from_registry()
    allowed = {(coord(m["lat"]), coord(m["lon"])) for m in markets.values()}
    rec = Recorder(out, Http(int(args.net_cap_gb * 1e9), allowed), markets=markets, pause_file=args.pause_file,
                   stop_file=args.stop_file, min_interval_s=args.min_interval_seconds,
                   hourly_requests=args.hourly_requests, min_free_gb=args.min_free_gb, cap_gb=args.cap_gb)
    rec.log_event("priority", below_normal=prio)
    if args.once:
        slot = slot_floor(rec.clock())
        rec.log_event("once", slot=_iso(slot), code=code_identity())
        cycle = rec.run_slot(slot)
        result = {k: cycle[k] for k in ("slot_utc", "complete", "markets_expected", "rows", "rows_ok", "reasons")}
        result.update(bytes=rec.http.used, requests=rec.http.requests)
        rec.status("once_done", result)
        print(json.dumps(result))
        return 0
    (out / "recorder.pid").write_text(str(os.getpid()), encoding="ascii")
    rec.run(args.poll_seconds, args.max_steps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
