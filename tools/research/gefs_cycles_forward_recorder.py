"""Lane L13: forward GEFS 00/12/18Z member recorder (2 m temperature, f003..f072, 31 members, 12 stations).

A sibling of the 06Z recorder (``gefs_forward_recorder.py``, which stays untouched and keeps its own output). Coordinator
GO 2026-10-30.

* **Source.** Free official NOAA GEFS v12 on the AWS open bucket ``noaa-gefs-pds`` (anonymous HTTPS, no key, no
  credentials). Product ``pgrb2sp25``; cycles 00, 12 and 18Z; members ``gec00`` and ``gep01..gep30``; steps
  f003..f072 by 3. Only the ``TMP:2 m above ground`` message is read, located through the ``.idx`` file and fetched
  with a Range request.
* **Extraction.** Uses ``gefs_member_point_fetch`` unchanged (its GRIB2 decoder, ``station_corners`` and
  ``bilinear``) with the same identity checks as the 06Z recorder. Station coordinates come from the market registry
  for the 12 markets of ``forward_local_day.MARKET_TZ``.
* **Point in time.** Every row carries:
  - ``available_utc``: the later of the S3 ``LastModified`` of the ``.grib2`` and its ``.idx``;
  - our listing, idx and range fetch times, the idx and message sha256, and ``fetch_lag_s``;
  - ``backfill``: true when our fetch came more than ``LIVE_WINDOW`` (12 h) after the cycle time. The bucket keeps
    every cycle with its original ``LastModified``, so a backfilled row has a true availability time but no live
    receipt.
* **Back-fill.** On start, every cycle from ``FORWARD_FIRST`` (2026-10-28 00Z) onward that has no manifest is worked
  oldest first, after any live cycle (less than 12 h old). Nothing before ``FORWARD_FIRST`` is ever requested.
* **Local day.** Each point carries ``local_date`` and ``local_time`` from ``forward_local_day``: ZoneInfo, so it is
  DST-correct, and 2026-11-01 is 25 hours long. The values are instantaneous, so they belong to the day that contains
  their valid time.
* **Output.** ``<out>/<YYYYMMDDHH>/rows.jsonl`` is append-only, and every line is fsynced. ``manifest.json`` is
  written atomically once every slot is ok or closed. ``events.jsonl``, ``gaps.jsonl`` and ``status.json`` sit in
  ``<out>``.
* **Guards.** The same as the 06Z recorder: below-normal priority, a bytes/s throttle and hourly ceiling, a pause
  file, a STOP file, a single-instance lock, a free-disk floor, an output-size cap and a per-process network byte cap.

Research / shadow only: nothing imports this module, nothing is served, and no outcome, price or label is read.
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

try:
    from tools.research import forward_local_day as ld
    from tools.research import gefs_forward_recorder as base
    from tools.research import gefs_member_point_fetch as g
except ImportError:  # run as a script from tools/research
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import forward_local_day as ld
    import gefs_forward_recorder as base
    import gefs_member_point_fetch as g

UTC = dt.timezone.utc
SCHEMA = "l13_gefs_cycles_forward/1"
FORWARD_FIRST = dt.datetime(2026, 10, 28, 0, tzinfo=UTC)
CYCLES = (0, 12, 18)
FHS = tuple(range(3, 73, 3))
PRODUCT = "sp25"
POLL_START = dt.timedelta(hours=3, minutes=40)  # f003..f072 of a cycle publish about 3:45-4:30 after the cycle
LIVE_WINDOW = dt.timedelta(hours=12)
CLOSE_AFTER = dt.timedelta(hours=36)  # a slot still unlisted this long after its cycle closes as missing
MAX_TRIES = 8
MESSAGE_BYTES = 800_000  # TMP 2 m in pgrb2sp25 is about 0.76 MB

_iso = base._iso
_sha_file = base._sha_file


def grib_key(cycle, member, fh):
    p = g.PRODUCTS[PRODUCT]
    return (f"gefs.{cycle:%Y%m%d}/{cycle.hour:02d}/atmos/{p['dir']}/"
            f"{member}.t{cycle.hour:02d}z.{p['stem']}.f{fh:03d}")


def stations_from_registry():
    """The 12 markets of forward_local_day, coordinates and timezone from the market registry."""
    src = Path(__file__).resolve().parents[2] / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from weather.market.market_registry import spec_for_id

    out = {}
    for m, tz in ld.MARKET_TZ.items():
        s = spec_for_id(m)
        if s.timezone != tz:
            raise SystemExit(f"{m}: registry timezone {s.timezone} != {tz}")
        out[m] = {"lat": float(s.lat), "lon": float(s.lon), "tz": tz}
    return out


def member_listing(f, cycle, member):
    """S3 listing of the member's f003..f090 objects (and .idx files) of ``cycle``: {key: {last_modified, ...}}."""
    stem = grib_key(cycle, member, 0)[:-3]
    params = {"list-type": "2", "prefix": stem + "0", "start-after": stem + "002", "max-keys": "60"}
    r = f.get(g.BUCKET + "/", params=params)
    if r.status_code != 200:
        raise RuntimeError(f"listing {member} {cycle:%Y%m%d%H}: HTTP {r.status_code}")
    page, _ = g.parse_listing(r.content)
    return page


def extract_message(f, cycle, member, fh, gent, ient, stations, corners, clock):
    """One (member, fh) row: identity-checked decode, the 12 station points, and the availability receipt."""
    key = grib_key(cycle, member, fh)
    valid = cycle + dt.timedelta(hours=fh)
    row = {"kind": "message", "cycle_utc": cycle.isoformat(), "cycle_hour": cycle.hour, "member": member, "fh": fh,
           "key": key, "valid_utc": valid.isoformat(), "product": PRODUCT, "variable": g.VAR,
           "grib_last_modified": gent["last_modified"], "idx_last_modified": ient["last_modified"],
           "available_utc": max(g.parse_s3_time(gent["last_modified"]),
                                g.parse_s3_time(ient["last_modified"])).isoformat()}
    r = f.get(f"{g.BUCKET}/{key}.idx")
    row["idx_fetched_utc"] = _iso(clock())
    if r.status_code != 200:
        return {**row, "status": f"idx_http_{r.status_code}"}
    row["idx_sha256"] = hashlib.sha256(r.content).hexdigest()
    start, end, rec = g.find_range(g.parse_idx(r.text), g.VAR, gent["size"])
    r = f.get(f"{g.BUCKET}/{key}", headers={"Range": f"bytes={start}-{end}"}, expect=(206,))
    fetched = clock()
    row["fetched_utc"] = _iso(fetched)
    row["fetch_lag_s"] = round((fetched - dt.datetime.fromisoformat(row["available_utc"])).total_seconds(), 1)
    row["backfill"] = fetched > cycle + LIVE_WINDOW
    if r.status_code != 206 or len(r.content) != end - start + 1:
        return {**row, "status": f"range_http_{r.status_code}"}
    blob = r.content
    row.update(message_sha256=hashlib.sha256(blob).hexdigest(), range=[start, end], idx_record=rec,
               etag=gent["etag"], bytes=len(blob))
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
        return {**row, "status": "decode_error", "error": str(exc)[:300]}
    points = {}
    for m, c in corners.items():
        value, four = g.bilinear(field, c)
        if not 150.0 < value < 350.0:
            return {**row, "status": "decode_error", "error": f"{m}: implausible {value} K"}
        day, sl, _ = ld.window_local_day(valid, valid, stations[m]["tz"])
        points[m] = {"bilinear_k": value, "corners_k": four, "local_date": day.isoformat(),
                     "local_time": sl.isoformat()}
    return {**row, "status": "ok", "ensemble_type": meta["ensemble_type"], "perturbation": meta["perturbation"],
            "points": points}


class Recorder:
    def __init__(self, out, fetcher, stations=None, clock=None, sleep=time.sleep, pause_file=None, stop_file=None,
                 bytes_per_s=3_000_000, hourly_mb=1500.0, min_free_gb=20.0, cap_mb=5000.0, disk_root=None,
                 first_cycle=FORWARD_FIRST):
        if g.GEFS_GRID != g.PRODUCTS[PRODUCT]["grid"]:
            raise SystemExit("gefs_member_point_fetch is not configured for the sp25 grid")
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.stations = stations if stations is not None else stations_from_registry()
        if set(self.stations) != set(ld.MARKET_TZ):
            raise SystemExit(f"station set {sorted(self.stations)} != the 12 markets")
        self.corners = {m: g.station_corners(s["lat"], s["lon"]) for m, s in self.stations.items()}
        self.f = fetcher
        self.clock = clock or (lambda: dt.datetime.now(UTC))
        self.sleep = sleep
        self.pause_file = Path(pause_file) if pause_file else self.out / "RECORDER_PAUSE"
        self.stop_file = Path(stop_file) if stop_file else self.out / "STOP"
        self.throttle = base.Throttle(bytes_per_s, int(hourly_mb * 1e6), sleep)
        self.min_free, self.cap = min_free_gb * 1e9, cap_mb * 1e6
        self.disk_root = disk_root or str(self.out)
        self.first_cycle = max(first_cycle, FORWARD_FIRST)
        self.paused_since = None
        self.cycles = {}
        here = Path(__file__).resolve().parent
        self.code = {name: _sha_file(here / name) for name in (
            "gefs_cycles_forward_recorder.py", "gefs_member_point_fetch.py", "gefs_forward_recorder.py",
            "forward_local_day.py")}

    def _p(self, *parts):
        return self.out.joinpath(*parts)

    def log_event(self, event, **kw):
        g.append_jsonl(self._p("events.jsonl"), {"event": event, "at_utc": _iso(self.clock()), **kw})

    def state(self, cycle):
        st = self.cycles.get(cycle)
        if st is None:
            d = self._p(f"{cycle:%Y%m%d%H}")
            rows = base.read_jsonl(d / "rows.jsonl")
            st = {"rows": rows, "ok": {(r["member"], r["fh"]) for r in rows if r.get("status") == "ok"},
                  "tries": defaultdict(int), "listing": {}, "listed_at": {},
                  "done": (d / "manifest.json").exists() or any(r.get("kind") == "cycle_done" for r in rows)}
            for r in rows:
                if r.get("kind") == "message" and r.get("status") != "ok":
                    st["tries"][(r["member"], r["fh"])] += 1
            self.cycles[cycle] = st
        return st

    def all_cycles(self, now):
        out = []
        day = self.first_cycle.date()
        while day <= now.date():
            for h in CYCLES:
                c = dt.datetime(day.year, day.month, day.day, h, tzinfo=UTC)
                if c >= self.first_cycle and now >= c + POLL_START:
                    out.append(c)
            day += dt.timedelta(days=1)
        return out

    def active_cycles(self, now):
        """Unfinished cycles: live ones (younger than LIVE_WINDOW) newest first, then the back-fill oldest first."""
        todo = [c for c in self.all_cycles(now) if not self.state(c)["done"]]
        live = sorted((c for c in todo if now - c < LIVE_WINDOW), reverse=True)
        return live + [c for c in todo if now - c >= LIVE_WINDOW]

    def _append(self, cycle, rec):
        d = self._p(f"{cycle:%Y%m%d%H}")
        d.mkdir(parents=True, exist_ok=True)
        g.append_jsonl(d / "rows.jsonl", rec)
        self.cycles[cycle]["rows"].append(rec)

    def _closed(self, st, slot):
        return slot in st["ok"] or st["tries"][slot] >= MAX_TRIES

    def work_cycle(self, cycle, now):
        """Fetch what is listed; returns (fetched, stopped_by_guard)."""
        st = self.state(cycle)
        fetched = 0
        for member in g.MEMBERS:
            if all(self._closed(st, (member, fh)) for fh in FHS):
                continue
            page = member_listing(self.f, cycle, member)
            t = _iso(self.clock())
            for key, ent in page.items():
                if st["listing"].get(key) != ent:
                    if key in st["listing"]:
                        self.log_event("listing_changed", key=key, old=st["listing"][key], new=ent)
                    st["listing"][key] = ent
                    st["listed_at"].setdefault(key, t)
            for fh in FHS:
                slot = (member, fh)
                if self._closed(st, slot):
                    continue
                key = grib_key(cycle, member, fh)
                gent, ient = st["listing"].get(key), st["listing"].get(key + ".idx")
                if not gent or not ient:
                    continue
                if not self.throttle.allow(self.clock(), MESSAGE_BYTES):
                    self.log_event("hourly_byte_ceiling")
                    return fetched, True
                if shutil.disk_usage(self.disk_root).free < self.min_free or base.dir_bytes(self.out) > self.cap:
                    self.log_event("disk_guard")
                    return fetched, True
                u0, w0 = self.f.used, time.time()
                try:
                    rec = extract_message(self.f, cycle, member, fh, gent, ient, self.stations, self.corners,
                                          self.clock)
                except (ValueError, LookupError, RuntimeError) as e:
                    rec = {"kind": "message", "cycle_utc": cycle.isoformat(), "member": member, "fh": fh,
                           "key": key, "status": "fetch_error", "error": str(e)[:300],
                           "backfill": self.clock() > cycle + LIVE_WINDOW}
                self.throttle.spent(self.f.used - u0, time.time() - w0)
                rec["listed_utc"] = st["listed_at"].get(key)
                self._append(cycle, rec)
                if rec["status"] == "ok":
                    st["ok"].add(slot)
                    fetched += 1
                else:
                    st["tries"][slot] += 1
                    self.log_event("fetch_failed", key=key, status=rec["status"])
        open_slots = [(m, fh) for m in g.MEMBERS for fh in FHS if not self._closed(st, (m, fh))]
        # Past CLOSE_AFTER only never-listed slots close as missing; a slot that failed keeps its MAX_TRIES retries.
        if not open_slots or (now >= cycle + CLOSE_AFTER and not any(st["tries"][s] for s in open_slots)):
            self.finalize(cycle)
        return fetched, False

    def finalize(self, cycle):
        st = self.state(cycle)
        missing = []
        for m in g.MEMBERS:
            for fh in FHS:
                if (m, fh) in st["ok"]:
                    continue
                missing.append([m, fh])
                if st["tries"][(m, fh)] == 0:
                    self._append(cycle, {"kind": "message", "cycle_utc": cycle.isoformat(), "member": m, "fh": fh,
                                         "key": grib_key(cycle, m, fh), "status": "object_missing",
                                         "closed_utc": _iso(self.clock())})
                g.append_jsonl(self._p("gaps.jsonl"), {"gap": "slot_missing", "cycle_utc": cycle.isoformat(),
                                                      "member": m, "fh": fh, "at_utc": _iso(self.clock())})
        ok_rows = [r for r in st["rows"] if r.get("status") == "ok"]
        self._append(cycle, {"kind": "cycle_done", "cycle_utc": cycle.isoformat(), "ok": len(st["ok"]),
                             "missing": len(missing), "closed_utc": _iso(self.clock())})
        rows_path = self._p(f"{cycle:%Y%m%d%H}", "rows.jsonl")
        write_json = base.write_json_atomic
        write_json(self._p(f"{cycle:%Y%m%d%H}", "manifest.json"), {
            "schema": SCHEMA, "cycle_utc": cycle.isoformat(), "rows_file": rows_path.name,
            "rows_sha256": _sha_file(rows_path), "stations": self.stations, "corners": self.corners,
            "fhs": list(FHS), "members": list(g.MEMBERS), "product": PRODUCT,
            "product_dir": g.PRODUCTS[PRODUCT]["dir"], "variable": g.VAR, "bucket": g.BUCKET,
            "ok": len(st["ok"]), "slots_missing": missing,
            "backfill_rows": sum(1 for r in ok_rows if r.get("backfill")),
            "live_rows": sum(1 for r in ok_rows if not r.get("backfill")),
            "max_available_utc": max((r["available_utc"] for r in ok_rows), default=None),
            "max_fetched_utc": max((r["fetched_utc"] for r in ok_rows), default=None),
            "bytes": sum(r.get("bytes", 0) for r in ok_rows), "code_sha256": self.code,
            "written_utc": _iso(self.clock())})
        st["done"] = True
        self.log_event("cycle_done", cycle=cycle.isoformat(), ok=len(st["ok"]), missing=len(missing))

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
        fetched, worked = 0, []
        if not paused:
            for cycle in self.active_cycles(now):
                worked.append(f"{cycle:%Y%m%d%H}")
                n, stopped = self.work_cycle(cycle, now)
                fetched += n
                if stopped:
                    break
        return {"fetched": fetched, "active_cycles": worked, "paused": paused}

    def next_wake(self, now, poll_s):
        if self.active_cycles(now):
            return float(poll_s)
        later = [c + POLL_START for c in self.all_cycles(now + dt.timedelta(days=1)) if c + POLL_START > now]
        nxt = min(later) if later else now + dt.timedelta(seconds=900)
        return float(max(1.0, min(900.0, (nxt - now).total_seconds())))  # wakes at least every 15 min (STOP)

    def status(self, state, extra=None):
        base.write_json_atomic(self._p("status.json"), {
            "state": state, "pid": os.getpid(), "updated_utc": _iso(self.clock()), "bytes_this_process": self.f.used,
            "requests_this_process": self.f.requests, "cpu_s": round(time.process_time(), 2),
            "paused": self.paused_since is not None, "code_sha256": self.code, **(extra or {})})

    def run(self, poll_s=120, max_steps=None):
        self.log_event("start", pid=os.getpid(), code=self.code)
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


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=r"C:\t\gefs_cycles\forward")
    ap.add_argument("--pause-file", default=None, help="default <out>/RECORDER_PAUSE")
    ap.add_argument("--stop-file", default=None, help="default <out>/STOP")
    ap.add_argument("--wait-lock-seconds", type=float, default=0.0)
    ap.add_argument("--poll-seconds", type=int, default=120)
    ap.add_argument("--bytes-per-second", type=int, default=3_000_000)
    ap.add_argument("--hourly-mb", type=float, default=1500.0)
    ap.add_argument("--cap-gb", type=float, default=200.0, help="hard network byte cap for this process")
    ap.add_argument("--cap-mb", type=float, default=5000.0, help="output directory size cap")
    ap.add_argument("--min-free-gb", type=float, default=20.0)
    ap.add_argument("--max-steps", type=int, default=None)
    ap.add_argument("--once-cycle", default=None, help="YYYYMMDDHH: fetch one forward cycle in the foreground, exit")
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    repo = Path(__file__).resolve().parents[2]
    if repo in out.resolve().parents or out.resolve() == repo:
        raise SystemExit("output must be outside the repository")
    lock = base.acquire_lock(out / "recorder.lock", args.wait_lock_seconds)  # noqa: F841 - held until exit
    prio = base.set_below_normal_priority()
    session = base.LiteSession("weather-research-l13-gefs-cycles/1 (serial; free NOAA open data)")
    rec = Recorder(out, g.Fetcher(int(args.cap_gb * 1e9), session=session), pause_file=args.pause_file,
                   stop_file=args.stop_file, bytes_per_s=args.bytes_per_second, hourly_mb=args.hourly_mb,
                   min_free_gb=args.min_free_gb, cap_mb=args.cap_mb)
    rec.log_event("priority", below_normal=prio)
    if args.once_cycle:
        c = dt.datetime.strptime(args.once_cycle, "%Y%m%d%H").replace(tzinfo=UTC)
        if c < FORWARD_FIRST or c.hour not in CYCLES or c + POLL_START > rec.clock():
            raise SystemExit(f"--once-cycle must be a published 00/12/18Z cycle from {FORWARD_FIRST:%Y%m%d%H}")
        n, _ = rec.work_cycle(c, rec.clock())
        st = rec.state(c)
        print(json.dumps({"cycle": args.once_cycle, "fetched": n, "ok": len(st["ok"]), "done": st["done"]}))
        return 0
    (out / "recorder.pid").write_text(str(os.getpid()), encoding="ascii")
    rec.run(args.poll_seconds, args.max_steps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
