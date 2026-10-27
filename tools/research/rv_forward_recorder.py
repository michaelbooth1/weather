"""Lane L13: forward MOS/NBE day-max recorder for the R-V arms (IEM ``mos.py``, free and keyless).

Design: docs/research/rv-capture-proposal-2026-10-27.md (accepted by master 98a58e36). Research and
shadow only: nothing imports this module, nothing is served, and no outcome, price or label is read.

Contract

* Input-fetch allowlist (master's named exception for post-2026-09-29 model runs): only
  ``https://mesonet.agron.iastate.edu/cgi-bin/request/mos.py``, only the 11 R0 ICAOs, only the
  products GFS, NAM and NBE, only CSV, and never a runtime window that touches 2026-09-30..10-15.
  Every request passes ``check_request`` first; a refusal raises before any socket is opened. There is
  never an outcome join, and this module does not import ``pooled_residual_model`` or its guard.
* Products, runs and lags copy ``RV_SOURCES`` (claude/rv-c1-20261027 @ 51e06ffaa,
  src/weather/calibration/pooled_residual_model.py:7825-7829): GFS ``n_x`` runs 06Z then 00Z, +4h30;
  NAM ``n_x`` 00Z, +4h; NBE ``txn`` 01Z then 00Z, +2h. The day-max for local date D is the row with
  ftime D+1 00Z; values outside -40..130 F are skipped; ``mos_x`` is the mean of >= 2 sources.
* Every stored run carries ``first_seen_utc`` (the time the response that first contained it was
  received) and is written once: its CSV file is created exclusively and never rewritten. A later
  response with different bytes for the same run is logged in ``revisions.jsonl`` only.
* Availability (forward rule): a run is usable at cutoff t only if ``runtime + lag <= t`` AND
  ``first_seen_utc <= t``. Otherwise the selection falls back to the older candidate, exactly as the
  training rule falls back when a run is missing, so a late run can only make the input older.
* Polling: one request per (station, model, UTC day) at the first due time (runtime + lag) of a
  missing run, then retries after 15, 30 and 60 min and hourly, until every used run is stored, the
  run is 8 h overdue, or D+1 01:00Z. Each request covers only that day's used runtimes.
* Guards (as the HRRR forward recorder): below-normal priority, a single-instance lock with
  ``--wait-lock-seconds`` handover, a STOP file, a pause file (pause start/end logged as gaps, never
  backfilled), >= 8 s request spacing with doubling back-off on throttling, an hourly request ceiling,
  a per-process byte cap and a free-disk floor.
"""
from __future__ import annotations

import argparse
import csv
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
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

UTC = dt.timezone.utc
URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/mos.py"
# The 11 R0 stations (R0_MARKETS via the market registry; pinned here and checked by the tests).
STATIONS = {
    "KATL": ("atlanta", "America/New_York"),
    "KAUS": ("austin", "America/Chicago"),
    "KORD": ("chicago", "America/Chicago"),
    "KDAL": ("dallas", "America/Chicago"),
    "KBKF": ("denver", "America/Denver"),
    "KHOU": ("houston", "America/Chicago"),
    "KLAX": ("los-angeles", "America/Los_Angeles"),
    "KMIA": ("miami", "America/New_York"),
    "KLGA": ("nyc", "America/New_York"),
    "KSFO": ("san-francisco", "America/Los_Angeles"),
    "KSEA": ("seattle", "America/Los_Angeles"),
}
# model -> (day-max field, run hours of UTC day D (latest first), availability lag in seconds)
MODELS = {
    "GFS": ("n_x", (6, 0), 4 * 3600 + 1800),
    "NAM": ("n_x", (0,), 4 * 3600),
    "NBE": ("txn", (1, 0), 2 * 3600),
}
RANGE_F = (-40.0, 130.0)
MIN_SOURCES = 2
HOURS = (13, 14, 15, 16)
BLACKOUT = (dt.date(2026, 9, 30), dt.date(2026, 10, 15))
ALLOWED_PARAMS = frozenset({"station", "model", "sts", "ets", "format"})
MAX_WINDOW = dt.timedelta(days=10)
SPACING_S = 8.0
DEADLINE = dt.timedelta(days=1, hours=1)  # D+1 01:00Z: after the latest 16:00 local cutoff (UTC-8)
GIVE_UP = dt.timedelta(hours=8)  # a run still absent 8 h after its due time is not requested again


class AllowlistError(RuntimeError):
    """A request outside the named input-fetch exception; raised before any network access."""


class Throttled(RuntimeError):
    pass


def _iso(t):
    return t.astimezone(UTC).isoformat().replace("+00:00", "Z") if t is not None else None


def _parse_iso(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def _zfmt(t):
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%MZ")


def _zparse(s):
    try:
        return dt.datetime.strptime(s, "%Y-%m-%dT%H:%MZ").replace(tzinfo=UTC)
    except (TypeError, ValueError) as e:
        raise AllowlistError(f"bad time {s!r}") from e


def check_request(url, params):
    """The allowlist. Returns the full request URL or raises AllowlistError."""
    if url != URL:
        raise AllowlistError(f"URL not allowlisted: {url!r}")
    if set(params) != ALLOWED_PARAMS:
        raise AllowlistError(f"parameters not allowlisted: {sorted(params)}")
    if params["station"] not in STATIONS:
        raise AllowlistError(f"station not allowlisted: {params['station']!r}")
    if params["model"] not in MODELS:
        raise AllowlistError(f"product not allowlisted: {params['model']!r}")
    if params["format"] != "csv":
        raise AllowlistError("format must be csv")
    sts, ets = _zparse(params["sts"]), _zparse(params["ets"])
    if ets < sts or ets - sts > MAX_WINDOW:
        raise AllowlistError(f"window not allowed: {params['sts']}..{params['ets']}")
    if sts.date() <= BLACKOUT[1] and ets.date() >= BLACKOUT[0]:
        raise AllowlistError("window touches 2026-09-30..10-15 (never read)")
    return URL + "?" + urlencode(params)


def request_params(station, model, sts, ets):
    return {"station": station, "model": model, "sts": _zfmt(sts), "ets": _zfmt(ets), "format": "csv"}


# --------------------------------------------------------------------------- HTTP
class LiteSession:
    """Persistent HTTPS GET with one TLS context (same client as the HRRR recorder)."""

    def __init__(self, user_agent="weather-research-l13-rv-forward/1 (serial; free NWS guidance via IEM)"):
        import ssl

        self.ctx = ssl.create_default_context()
        self.headers = {"User-Agent": user_agent, "Accept-Encoding": "identity"}
        self.conn = None

    def get(self, full_url, timeout=120):
        import http.client
        from urllib.parse import urlsplit

        u = urlsplit(full_url)
        for attempt in (0, 1):
            if self.conn is None:
                self.conn = http.client.HTTPSConnection(u.hostname, context=self.ctx, timeout=timeout)
            try:
                self.conn.request("GET", u.path + "?" + u.query, headers=self.headers)
                resp = self.conn.getresponse()
                body = resp.read()
            except (http.client.HTTPException, OSError):
                self.conn.close()
                self.conn = None
                if attempt:
                    raise
                continue
            if (resp.getheader("Connection") or "").lower() == "close":
                self.conn.close()
                self.conn = None
            return resp.status, body


class Client:
    """Allowlisted, spaced IEM client. ``transport(full_url) -> (status, bytes)``."""

    def __init__(self, transport, clock, sleep=time.sleep, spacing=SPACING_S, cap_bytes=2_000_000_000):
        self.transport, self.clock, self.sleep, self.spacing = transport, clock, sleep, spacing
        self.cap, self.used, self.requests, self.last = cap_bytes, 0, 0, None

    def fetch(self, params):
        full = check_request(URL, params)  # refuses before any network access
        if self.used >= self.cap:
            raise SystemExit("per-process byte cap reached")
        if self.last is not None:
            wait = self.spacing - (self.clock() - self.last).total_seconds()
            if wait > 0:
                self.sleep(wait)
        sent = self.clock()
        self.last = sent
        status, body = self.transport(full)
        self.requests += 1
        self.used += len(body)
        text = body.decode("utf-8", "replace")
        if status in (429, 503) or "Too many requests" in text[:500]:
            raise Throttled(f"status {status}")
        if status != 200 or not text.startswith("runtime"):
            raise RuntimeError(f"IEM returned no CSV ({status}): {text[:120]!r}")
        return sent, self.clock(), text


# --------------------------------------------------------------------------- parsing and selection
def num(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return out if math.isfinite(out) else float("nan")


def split_runs(text, station, model):
    """CSV text -> {runtime: bytes of header + that runtime's rows}; rows must match the request."""
    lines = text.splitlines(keepends=True)
    header = lines[0] if lines[0].endswith("\n") else lines[0] + "\n"
    cols = next(csv.reader([lines[0]]))
    i_st, i_mo = cols.index("station"), cols.index("model")
    runs = {}
    for ln in lines[1:]:
        if not ln.strip():
            continue
        row = next(csv.reader([ln]))
        if row[i_st].strip() != station or row[i_mo].strip() != model:
            raise RuntimeError(f"row for {row[i_st]}/{row[i_mo]} in a {station}/{model} response")
        runtime = dt.datetime.fromisoformat(row[0]).replace(tzinfo=UTC)
        runs.setdefault(runtime, [header]).append(ln if ln.endswith("\n") else ln + "\n")
    return {r: "".join(v).encode("utf-8") for r, v in runs.items()}


def run_values(data, model):
    """Run CSV bytes -> {ftime: day-max field value}."""
    field = MODELS[model][0]
    out = {}
    for rec in csv.DictReader(data.decode("utf-8").splitlines()):
        out[dt.datetime.fromisoformat(rec["ftime"]).replace(tzinfo=UTC)] = num(rec.get(field))
    return out


def select_source(values, model, day, instant, first_seen=None):
    """One source's D-max at ``instant``: (value, runtime) or (nan, None).

    ``values``: {(runtime, ftime): value}. ``first_seen`` None is the training rule (lag only, as
    rv_source_value); a dict {runtime: first_seen_utc} adds the forward condition first_seen <= instant
    (a run never seen counts as missing)."""
    _, hours, lag = MODELS[model]
    ftime = dt.datetime(day.year, day.month, day.day, tzinfo=UTC) + dt.timedelta(days=1)
    for hour in hours:
        runtime = dt.datetime(day.year, day.month, day.day, hour, tzinfo=UTC)
        if runtime + dt.timedelta(seconds=lag) > instant:
            continue
        if first_seen is not None:
            seen = first_seen.get(runtime)
            if seen is None or seen > instant:
                continue
        value = values.get((runtime, ftime), float("nan"))
        if math.isfinite(value) and RANGE_F[0] <= value <= RANGE_F[1]:
            return value, runtime
    return float("nan"), None


def cutoff_instant(station, day, hour):
    tz = ZoneInfo(STATIONS[station][1])
    return dt.datetime(day.year, day.month, day.day, int(hour), tzinfo=tz).astimezone(UTC)


def entry(tables, station, day, hour, first_seen=None):
    """``mos_x``, per-source values and selected runtimes at (station, local date, cutoff hour).

    ``tables``: {model: {(runtime, ftime): value}}; ``first_seen``: None or {model: {runtime: t}}."""
    instant = cutoff_instant(station, day, hour)
    src, runs = {}, {}
    for m in MODELS:
        fs = None if first_seen is None else first_seen.get(m, {})
        src[m], runs[m] = select_source(tables.get(m, {}), m, day, instant, fs)
    found = [v for v in src.values() if math.isfinite(v)]
    mos_x = sum(found) / len(found) if len(found) >= MIN_SOURCES else float("nan")
    return {"mos_x": mos_x, **{f"src_{m}": v for m, v in src.items()}, "runs": runs}


# --------------------------------------------------------------------------- store (write-once)
def _append_jsonl(path, rec):
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")


def _read_jsonl(path):
    if not Path(path).exists():
        return []
    return [json.loads(ln) for ln in Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()]


class Store:
    """Write-once run files plus the ``runs.jsonl`` ledger (first_seen_utc per run)."""

    def __init__(self, out):
        self.out = Path(out)
        (self.out / "runs").mkdir(parents=True, exist_ok=True)
        self.runs = {}  # (station, model, runtime) -> ledger record
        for rec in _read_jsonl(self.out / "runs.jsonl"):
            self.runs[(rec["station"], rec["model"], _parse_iso(rec["runtime_utc"]))] = rec
        self.revisions = {(r["station"], r["model"], r["runtime_utc"], r["sha256"])
                          for r in _read_jsonl(self.out / "revisions.jsonl")}

    def path(self, station, model, runtime):
        return self.out / "runs" / station / model / f"{runtime:%Y%m%dT%HZ}.csv"

    def put(self, station, model, runtime, data, sent, seen):
        """Store a run once. Returns "stored", "same" or "revision" (never rewrites)."""
        key = (station, model, runtime)
        sha = hashlib.sha256(data).hexdigest()
        if key in self.runs:
            if self.runs[key]["sha256"] == sha:
                return "same"
            rkey = (station, model, _iso(runtime), sha)
            if rkey not in self.revisions:
                self.revisions.add(rkey)
                _append_jsonl(self.out / "revisions.jsonl", {"station": station, "model": model,
                              "runtime_utc": _iso(runtime), "sha256": sha, "seen_utc": _iso(seen)})
            return "revision"
        path = self.path(station, model, runtime)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "xb") as f:  # exclusive create: an existing file is never overwritten
            f.write(data)
        rec = {"station": station, "model": model, "runtime_utc": _iso(runtime), "first_seen_utc": _iso(seen),
               "request_sent_utc": _iso(sent), "sha256": sha, "bytes": len(data),
               "path": str(path.relative_to(self.out)).replace("\\", "/")}
        _append_jsonl(self.out / "runs.jsonl", rec)
        self.runs[key] = rec
        return "stored"

    def tables(self, station):
        """({model: {(runtime, ftime): value}}, {model: {runtime: first_seen}}) for one station."""
        tables, seen = {}, {}
        for (st, model, runtime), rec in self.runs.items():
            if st != station:
                continue
            p = self.out / rec["path"]
            data = p.read_bytes() if p.exists() else b""
            if hashlib.sha256(data).hexdigest() != rec["sha256"]:
                continue  # missing or altered file: the run counts as unseen
            for ftime, v in run_values(data, model).items():
                tables.setdefault(model, {})[(runtime, ftime)] = v
            seen.setdefault(model, {})[runtime] = _parse_iso(rec["first_seen_utc"])
        return tables, seen


# --------------------------------------------------------------------------- recorder
def due_time(day, model, hour):
    return dt.datetime(day.year, day.month, day.day, hour, tzinfo=UTC) + dt.timedelta(seconds=MODELS[model][2])


def retry_delay(misses):
    """15, 30, 60 min, then hourly: first_seen is at most an hour late once a run is overdue."""
    return dt.timedelta(seconds=min(900 * 2 ** misses, 3600))


def free_bytes(root):
    return shutil.disk_usage(root).free


class Recorder:
    def __init__(self, out, client, clock, sleep=time.sleep, pause_file=None, stop_file=None,
                 hourly_requests=60, min_free_gb=20.0, disk_root="C:\\", stations=tuple(STATIONS)):
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.store = Store(self.out)
        self.client, self.clock, self.sleep = client, clock, sleep
        self.pause_file = Path(pause_file) if pause_file else None
        self.stop_file = Path(stop_file) if stop_file else None
        self.hourly, self.min_free, self.disk_root = hourly_requests, min_free_gb * 2 ** 30, disk_root
        self.stations = tuple(stations)
        meta = self.out / "meta.json"
        if not meta.exists():
            meta.write_text(json.dumps({"first_started_utc": _iso(clock()), "url": URL, "models": MODELS,
                                        "stations": self.stations}, sort_keys=True), encoding="utf-8")
        self.first_day = _parse_iso(json.loads(meta.read_text(encoding="utf-8"))["first_started_utc"]).date()
        self.next_try, self.misses = {}, {}
        self.hour, self.hour_requests, self.paused_since = None, 0, None
        self.backoff_until, self.backoff = None, 60

    def log_event(self, event, **kw):
        _append_jsonl(self.out / "events.jsonl", {"event": event, "at_utc": _iso(self.clock()), **kw})

    def keys(self, now):
        """(station, model, day) still worth requesting at ``now``."""
        out = []
        for day in (now.date() - dt.timedelta(days=1), now.date()):
            if day < self.first_day or now > dt.datetime(day.year, day.month, day.day, tzinfo=UTC) + DEADLINE:
                continue
            for st in self.stations:
                for model, (_, hours, _) in MODELS.items():
                    missing = [h for h in hours if (st, model, dt.datetime(day.year, day.month, day.day, h,
                                                                           tzinfo=UTC)) not in self.store.runs
                               and now <= due_time(day, model, h) + GIVE_UP]
                    if missing and min(due_time(day, model, h) for h in missing) <= now:
                        out.append((st, model, day, missing))
        return out

    def request(self, st, model, day):
        hours = MODELS[model][1]
        base = dt.datetime(day.year, day.month, day.day, tzinfo=UTC)
        params = request_params(st, model, base, base + dt.timedelta(hours=max(hours), minutes=59))
        sent, seen, text = self.client.fetch(params)
        results = {}
        for runtime, data in split_runs(text, st, model).items():
            if runtime.date() == day and runtime.hour in hours:
                results[runtime.hour] = self.store.put(st, model, runtime, data, sent, seen)
        return results

    def step(self):
        now = self.clock()
        paused = bool(self.pause_file and self.pause_file.exists())
        if paused and self.paused_since is None:
            self.paused_since = now
            self.log_event("pause_start")
            _append_jsonl(self.out / "gaps.jsonl", {"gap": "pause_start", "at_utc": _iso(now)})
        elif not paused and self.paused_since is not None:
            _append_jsonl(self.out / "gaps.jsonl", {"gap": "pause_end", "at_utc": _iso(now),
                                                   "started_utc": _iso(self.paused_since)})
            self.log_event("pause_end")
            self.paused_since = None
        if paused or (self.backoff_until and now < self.backoff_until):
            return 0
        stored = 0
        for st, model, day, missing in self.keys(now):
            k = (st, model, day)
            if self.next_try.get(k) and now < self.next_try[k]:
                continue
            t = self.clock()
            hour = t.replace(minute=0, second=0, microsecond=0)
            if hour != self.hour:
                self.hour, self.hour_requests = hour, 0
            if self.hour_requests >= self.hourly:
                self.log_event("hourly_request_ceiling", hour=_iso(hour))
                return stored
            if free_bytes(self.disk_root) < self.min_free:
                self.log_event("low_disk")
                return stored
            self.hour_requests += 1
            try:
                results = self.request(st, model, day)
            except Throttled as e:
                self.backoff_until = self.clock() + dt.timedelta(seconds=self.backoff)
                self.log_event("throttled", error=str(e), backoff_s=self.backoff)
                self.backoff = min(self.backoff * 2, 960)
                return stored
            self.backoff = 60
            stored += sum(r == "stored" for r in results.values())
            left = [h for h in missing if results.get(h) != "stored"]
            after = self.clock()
            if left:
                not_due = [due_time(day, model, h) for h in left if due_time(day, model, h) > after]
                if len(not_due) == len(left):
                    self.next_try[k] = min(not_due)
                else:
                    self.misses[k] = self.misses.get(k, 0) + 1
                    self.next_try[k] = after + retry_delay(self.misses[k] - 1)
            self.log_event("request", station=st, model=model, day=day.isoformat(), results=results)
        return stored

    def next_wake(self, poll_s):
        now = self.clock()
        cands = [t for t in self.next_try.values() if t > now]
        for day in (now.date(), now.date() + dt.timedelta(days=1)):
            for model, (_, hours, _) in MODELS.items():
                cands += [due_time(day, model, h) for h in hours if due_time(day, model, h) > now]
        if self.backoff_until and self.backoff_until > now:
            cands.append(self.backoff_until)
        nxt = min(cands) if cands else now + dt.timedelta(seconds=poll_s)
        return max(1.0, min(float(poll_s), (nxt - now).total_seconds() + 1.0))

    def status(self, state, extra=None):
        tmp = self.out / "status.json.part"
        tmp.write_text(json.dumps({"state": state, "pid": os.getpid(), "updated_utc": _iso(self.clock()),
                                   "runs_stored": len(self.store.runs), "requests_this_process":
                                   self.client.requests, "bytes_this_process": self.client.used,
                                   "paused": self.paused_since is not None, **(extra or {})},
                                  sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.out / "status.json")

    def run(self, poll_s=300, max_steps=None):
        steps = 0
        self.log_event("start", pid=os.getpid(), code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        while True:
            if self.stop_file and self.stop_file.exists():
                self.log_event("stop_file")
                self.status("stopped_by_file")
                return
            try:
                self.status("running", {"stored": self.step()})
            except Exception as e:  # keep recording; the failure is logged, never silently skipped
                self.log_event("step_error", error=repr(e)[:500], tb=traceback.format_exc()[-1500:])
                self.status("running_after_error")
            steps += 1
            if max_steps is not None and steps >= max_steps:
                return
            self.sleep(self.next_wake(poll_s))


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
    """Single-instance lock held for the process life; ``wait_s`` > 0 waits for a handover."""
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


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=r"C:\t\l13\rv_forward")
    ap.add_argument("--pause-file", default=r"C:\t\l13\RECORDER_PAUSE")
    ap.add_argument("--stop-file", default=r"C:\t\l13\rv_forward\STOP")
    ap.add_argument("--wait-lock-seconds", type=float, default=0.0)
    ap.add_argument("--poll-seconds", type=int, default=300)
    ap.add_argument("--hourly-requests", type=int, default=60)
    ap.add_argument("--cap-mb", type=float, default=200.0, help="hard byte cap for this process")
    ap.add_argument("--min-free-gb", type=float, default=20.0)
    ap.add_argument("--max-steps", type=int, default=None)
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    lock = acquire_lock(out / "recorder.lock", args.wait_lock_seconds)  # noqa: F841 - held until exit
    prio = set_below_normal_priority()
    clock = lambda: dt.datetime.now(UTC)  # noqa: E731
    client = Client(LiteSession().get, clock, cap_bytes=int(args.cap_mb * 1e6))
    rec = Recorder(out, client, clock, pause_file=args.pause_file, stop_file=args.stop_file,
                   hourly_requests=args.hourly_requests, min_free_gb=args.min_free_gb)
    rec.log_event("priority", below_normal=prio)
    (out / "recorder.pid").write_text(str(os.getpid()), encoding="ascii")
    rec.run(args.poll_seconds, args.max_steps)


if __name__ == "__main__":
    sys.exit(main())
