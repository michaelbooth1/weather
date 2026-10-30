"""Lane L13: IEM MOS forward recorder: NBS, NBE, GFS, MEX, NAM and LAV MOS runs for the 12 market stations.

Free public data from the Iowa Environmental Mesonet MOS archive ``https://mesonet.agron.iastate.edu/cgi-bin/request/
mos.py`` (anonymous HTTPS, no key, no credentials): the same service and CSV columns the research corpus was built from
(``tools/research/model_parity/a-iem-2_mos_fetch.py``), so a forward feature can be computed exactly as in training.
Design note: ``docs/research/iem-mos-forward-recorder-2026-10-30.md``. Research / shadow only: nothing imports this
module, nothing is served, and no outcome, price or label is read.

* **What is fetched.** Each sweep asks, per model, for every station's runs with runtime from shortly before the
  newest run already recorded (at most ``WINDOW`` back) up to now: one small CSV request per station and model, spaced
  at least ``SPACING_S`` apart, backing off on HTTP 429/503 or the archive's "Too many requests" text. Station and
  model pairs the archive does not carry (CYYZ has no GFS, MEX, NAM or LAV MOS) are recorded as empty, not errors.
* **What is kept.** Per run (model, station, runtime) the CSV rows exactly as served, as one ``version`` row with the
  sha256 of their canonical text. A run is appended again only when its content changes (an IEM revision or a run
  still filling in); unchanged reappearances are not written.
* **Point in time.** IEM publishes no ingest time, so availability is bounded by our sweeps: ``first_seen_utc`` (the
  fetch that first returned this content) and ``absent_at_utc`` (this process's previous successful fetch for
  that station and model, when its window started at or before the runtime and did not hold it; else null).
  ``backfill`` is true when ``first_seen_utc`` is more than ``LIVE_WINDOW`` after the runtime or no absent
  fetch bounds it, so a catch-up after downtime is never mistaken for a live receipt. One station per request:
  the archive treats ``station=A,B`` as one unknown station and rejects repeated ``station`` parameters.

Per runtime ``<out>/<YYYYMMDD>/<HH>/<model>.jsonl`` is append-only; each version is one fsynced line. Restarts are
idempotent: known (model, station, runtime, sha256) are reloaded from disk and never written twice. Guards as the ENS,
ECCC and NBM recorders: below-normal priority, a per-process byte cap, a pause file, a STOP file, a single-instance
lock, a free-disk floor and an output-size cap.
"""
from __future__ import annotations

import argparse
import csv
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
from pathlib import Path
from urllib.parse import urlencode

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]

UTC = dt.timezone.utc
SCHEMA = "l13_iem_mos_forward/1"
URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/mos.py"
FORWARD_FIRST = dt.datetime(2026, 10, 30, 0, tzinfo=UTC)  # earliest runtime the recorder may ask for
MODELS = ("NBS", "NBE", "GFS", "MEX", "NAM", "LAV")
WINDOW = dt.timedelta(hours=36)      # never ask further back than this per sweep (after the first)
FIRST_LOOKBACK = dt.timedelta(hours=72)
REVISIT = dt.timedelta(hours=6)      # re-ask the newest recorded runs this far back, to catch late rows and revisions
LIVE_WINDOW = dt.timedelta(hours=8)
SPACING_S = 5.0
BACKOFF_S = (60, 120, 240, 480, 960)
MARKETS = ("toronto", "nyc", "atlanta", "miami", "austin", "chicago", "dallas", "houston", "denver", "los-angeles",
           "san-francisco", "seattle")
THROTTLE_TEXT = "Too many requests"


def _iso(t):
    return None if t is None else t.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def request_url(station, model, sts, ets):
    q = {"station": station, "model": model, "sts": sts.strftime("%Y-%m-%dT%H:%MZ"),
         "ets": ets.strftime("%Y-%m-%dT%H:%MZ"), "format": "csv"}
    return f"{URL}?{urlencode(q)}"


def parse_runtime(s):
    return dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)


def parse_csv(text, station, model):
    """{runtime: [row dict, ...]} from one archive CSV; refuses rows of another station or model."""
    if not text.startswith("runtime"):
        raise ValueError(f"not a MOS CSV: {text[:80]!r}")
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        if row.get("station") != station or row.get("model") != model:
            raise ValueError(f"row for {row.get('station')}/{row.get('model')} in a {station}/{model} answer")
        out.setdefault(parse_runtime(row["runtime"]), []).append(row)
    for rows in out.values():
        rows.sort(key=lambda r: r["ftime"])
    return out


def canonical_sha(rows):
    return sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode())


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


def stations_from_registry():
    """{icao: market} for the 12 markets, from the market registry."""
    src = _REPO / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from weather.market.market_registry import spec_for_id

    out = {}
    for m in MARKETS:
        icao = spec_for_id(m).icao
        if not re.fullmatch(r"[A-Z0-9]{4}", icao or ""):
            raise SystemExit(f"{m}: bad icao {icao!r}")
        out[icao] = m
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

    def __init__(self, cap_bytes, user_agent="weather-research-l13-iem-mos-forward/1 (serial; >=5 s between requests)"):
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
        target = u.path + (f"?{u.query}" if u.query else "")
        for attempt in (0, 1):
            if self.conn is None or self.host != u.hostname:
                self._close()
                self.conn = http.client.HTTPSConnection(u.hostname, context=self.ctx, timeout=timeout)
                self.host = u.hostname
            try:
                self.conn.request("GET", target, headers=self.base_headers)
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
            return Resp(resp.status, body, {})


# --------------------------------------------------------------------------- recorder
class Recorder:
    def __init__(self, out, http, stations=None, clock=None, sleep=time.sleep, monotonic=time.monotonic,
                 models=MODELS, pause_file=None, stop_file=None, min_free_gb=20.0, cap_gb=5.0, spacing_s=SPACING_S,
                 first_runtime=FORWARD_FIRST):
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.http = http
        self.stations = dict(stations) if stations is not None else stations_from_registry()
        self.clock = clock or (lambda: dt.datetime.now(UTC))
        self.sleep, self.monotonic = sleep, monotonic
        self.models = tuple(models)
        if not self.models or set(self.models) - set(MODELS):
            raise SystemExit(f"models must be within {MODELS}")
        self.pause_file = Path(pause_file) if pause_file else self.out / "RECORDER_PAUSE"
        self.stop_file = Path(stop_file) if stop_file else self.out / "STOP"
        self.min_free, self.cap = min_free_gb * 1e9, cap_gb * 1e9
        self.spacing = spacing_s
        self.first_runtime = max(first_runtime, FORWARD_FIRST)
        self.paused_since = None
        self.last_request = None
        self.code_sha256 = sha256(Path(__file__).read_bytes())
        self.seen = {}      # (model, station, runtime) -> set of sha256 already written
        self.newest = {}    # (model, station) -> newest runtime recorded
        self.coverage = {}  # (model, station) -> (window start, fetch time) of the last successful fetch this process
        self._load()

    def _p(self, *parts):
        return self.out.joinpath(*parts)

    def _file(self, runtime, model):
        return self._p(f"{runtime:%Y%m%d}", f"{runtime:%H}", f"{model}.jsonl")

    def log_event(self, event, **kw):
        append_jsonl(self._p("events.jsonl"), {"event": event, "at_utc": _iso(self.clock()), **kw})

    def _load(self):
        for path in self.out.glob("*/*/*.jsonl"):
            for r in read_jsonl(path):
                if r.get("kind") != "version":
                    continue
                rt = _parse_iso(r["runtime_utc"])
                self.seen.setdefault((r["model"], r["station"], rt), set()).add(r["sha256"])
                key = (r["model"], r["station"])
                if key not in self.newest or rt > self.newest[key]:
                    self.newest[key] = rt

    def _space(self):
        if self.last_request is not None:
            wait = self.spacing - (self.monotonic() - self.last_request)
            if wait > 0:
                self.sleep(wait)
        self.last_request = self.monotonic()

    def _get_csv(self, url):
        """Body text, or raises after the back-off schedule is exhausted."""
        for backoff in (*BACKOFF_S, None):
            self._space()
            r = self.http.get(url)
            text = r.content.decode("utf-8", errors="replace")
            if r.status_code in (429, 503) or THROTTLE_TEXT in text[:500]:
                self.log_event("throttled", status=r.status_code, backoff_s=backoff)
                if backoff is None:
                    raise ValueError("throttled after the full back-off schedule")
                self.sleep(backoff)
                continue
            if r.status_code != 200:
                raise ValueError(f"http {r.status_code}")
            return text
        raise AssertionError("unreachable")

    def window_start(self, model, station, now):
        newest = self.newest.get((model, station))
        if newest is None:
            start = now - FIRST_LOOKBACK
        else:
            start = max(newest - REVISIT, now - WINDOW)
        start = max(start, self.first_runtime)
        return start.replace(minute=0, second=0, microsecond=0)

    def fetch_pair(self, station, model, now):
        """One request; returns the number of new versions written."""
        sts = self.window_start(model, station, now)
        url = request_url(station, model, sts, now)
        try:
            text = self._get_csv(url)
            fetched = self.clock()
            runs = parse_csv(text, station, model) if text.strip() != "runtime" and text.strip() else {}
        except CapReached:
            raise
        except Exception as e:
            self.log_event("fetch_failed", station=station, model=model, url=url, error=repr(e)[:300])
            return 0
        prev = self.coverage.get((model, station))
        new = 0
        for rt in sorted(runs):
            if rt < self.first_runtime:
                continue
            rows = runs[rt]
            digest = canonical_sha(rows)
            shas = self.seen.setdefault((model, station, rt), set())
            if digest in shas:
                continue
            absent_at = None
            # the previous fetch's window started at or before rt, so it would have held rt had rt been published
            if prev is not None and not shas and prev[0] <= rt:
                absent_at = prev[1]
            rec = {"kind": "version", "schema": SCHEMA, "model": model, "station": station,
                   "market": self.stations[station], "runtime_utc": _iso(rt), "sha256": digest, "n_rows": len(rows),
                   "revision": len(shas), "first_seen_utc": _iso(fetched), "absent_at_utc": _iso(absent_at),
                   "backfill": absent_at is None or fetched - rt > LIVE_WINDOW, "request_url": url,
                   "rows": rows}
            append_jsonl(self._file(rt, model), rec)
            shas.add(digest)
            if (model, station) not in self.newest or rt > self.newest[(model, station)]:
                self.newest[(model, station)] = rt
            new += 1
        self.coverage[(model, station)] = (sts, fetched)
        if not runs:
            self.log_event("empty", station=station, model=model, url=url)
        return new

    def _guard(self):
        if shutil.disk_usage(self.out).free < self.min_free or dir_bytes(self.out) > self.cap:
            self.log_event("disk_guard")
            return False
        return True

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
        new, asked = 0, 0
        if not paused and self._guard():
            for model in self.models:
                for station in sorted(self.stations):
                    if self.stop_file.exists():
                        return {"new_versions": new, "requests": asked, "paused": paused, "stopped": True}
                    new += self.fetch_pair(station, model, self.clock())
                    asked += 1
        return {"new_versions": new, "requests": asked, "paused": paused}

    def status(self, state, extra=None):
        write_json_atomic(self._p("status.json"), {
            "state": state, "pid": os.getpid(), "updated_utc": _iso(self.clock()), "bytes_this_process": self.http.used,
            "requests_this_process": self.http.requests, "cpu_s": round(time.process_time(), 2),
            "paused": self.paused_since is not None, "recorder_sha256": self.code_sha256, **(extra or {})})

    def run(self, poll_s=1800, max_steps=None):
        self.log_event("start", pid=os.getpid(), code=code_identity(), models=list(self.models),
                       stations=self.stations)
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
    ap.add_argument("--out", default=r"C:\t\iem_mos\forward")
    ap.add_argument("--models", default=",".join(MODELS))
    ap.add_argument("--pause-file", default=None, help="default <out>/RECORDER_PAUSE")
    ap.add_argument("--stop-file", default=None, help="default <out>/STOP")
    ap.add_argument("--wait-lock-seconds", type=float, default=0.0)
    ap.add_argument("--poll-seconds", type=int, default=1800)
    ap.add_argument("--spacing-seconds", type=float, default=SPACING_S)
    ap.add_argument("--net-cap-gb", type=float, default=20.0, help="network byte cap for this process")
    ap.add_argument("--cap-gb", type=float, default=5.0, help="output directory size cap")
    ap.add_argument("--min-free-gb", type=float, default=20.0)
    ap.add_argument("--max-steps", type=int, default=None)
    ap.add_argument("--first-runtime", default=None, help="UTC ISO; not before the built-in forward start")
    ap.add_argument("--once", action="store_true", help="one foreground sweep, then exit")
    args = ap.parse_args(argv)
    models = tuple(m.strip().upper() for m in args.models.split(",") if m.strip())
    out = Path(args.out)
    if _REPO in out.resolve().parents or out.resolve() == _REPO:
        raise SystemExit("output must be outside the repository")
    out.mkdir(parents=True, exist_ok=True)
    lock = acquire_lock(out / "recorder.lock", args.wait_lock_seconds)  # noqa: F841 - held until exit
    prio = set_below_normal_priority()
    first = _parse_iso(args.first_runtime) if args.first_runtime else FORWARD_FIRST
    rec = Recorder(out, Http(int(args.net_cap_gb * 1e9)), models=models, pause_file=args.pause_file,
                   stop_file=args.stop_file, min_free_gb=args.min_free_gb, cap_gb=args.cap_gb,
                   spacing_s=args.spacing_seconds, first_runtime=first)
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
