"""Lane L13: forward HRRR shadow recorder for the R-K (13-16) and R-R (07-12) parity clock.

Read-only shadow capture of free NOAA HRRR (AWS ``noaa-hrrr-bdp-pds``, anonymous HTTPS). It reuses
``hrrr_point_fetch``'s listing, idx byte-range reads, pure-numpy GRIB2 decoder, station geometry and
point-in-time ``select_cycle`` unchanged, and stores only point values (nearest, the 3x3 block and the
RN-1 land-aware cell) plus message sha256 - never raw GRIB.

Contract (L2 drafts ``hrrr_forward_recorder_parity_plan_DRAFT.md`` 66ad9599 and its R-R addendum
ba49f48b; rules R-K 21b5dfe1, R-R e3d92e1a, RN-1 e4869491):

* Every (station, local date, h in 07..16) snapshot row records exactly what a live server could
  have seen at the snapshot instant ``h:00 local``: the selection uses only messages whose bytes were
  retrieved at or before the snapshot AND whose listing ``LastModified`` + 10 min is at or before it
  (the training rule). A cycle that arrives late leaves the row on an older cycle or absent
  (``k_miss`` = 1). Rows are written once, after the snapshot, and never revised or backfilled.
* Only messages that can still serve an upcoming snapshot are read: for each future snapshot, the
  newest candidate cycle whose needed forecast hours are all listed and could qualify. Nothing for a
  past snapshot is ever fetched.
* Footprint guards built into the process: below-normal priority, a bytes-per-second throttle, an
  hourly byte ceiling, a pause flag file (``RECORDER_PAUSE``; pause start/end logged as gaps, never
  backfilled), a STOP file, a single-instance lock and a free-disk floor.

Research / shadow only: nothing imports this module, nothing is served, no Scheduler or capture-host
state is touched, and no outcome, price or label is read.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import sys
import time
import traceback
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from tools.research import hrrr_point_fetch as h
except ImportError:  # run as a script from tools/research
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import hrrr_point_fetch as h

UTC = dt.timezone.utc
HOURS = tuple(range(7, 17))          # R-R 07-12 plus R-K 13-16
VALID_END_LOCAL = 17
STRIDE = 1
LOOKBACK = 4
MARGIN = dt.timedelta(minutes=10)
MAX_FH = h.MAX_FH
VARS = ("TMP:2 m above ground", "TCDC:entire atmosphere")
POINT_RULE = "RN-1"
LAND_SHA256 = "22069beebb5609755b35621bac05e91a1b35e434670c993a93a8aca9434fd7d6"
STATIONS_JSON_SHA256 = "52e8bb5f22513828cb5edbfc16b77afb293cfcb9df62a92abd4db30ab7a0abe3"
RULE_SHAS = {
    "rule_rk": "21b5dfe1870c03bcab143903b8fccc37a446c49de97b3889377039c7c8327221",
    "rule_rr": "e3d92e1aa779957db90c9627f3ccdc9052d7f9f2d6f7ae50843ebadbd0f5bb22",
    "rule_rn_cl1": "e4869491a8480f302c0bb4c33b0d55d4110ef98551f0db26e59d3441e204004b",
    "parity_plan_draft": "66ad95993180fd09f836e07fe18b0b2cbedf241158c60d10ae29cbceb937eba8",
    "parity_rr_addendum_draft": "ba49f48bf5f70018188a388c6cdc184ab3e880cba745d511b67feb24ae649f82",
    "land_3x3": LAND_SHA256,
}
_OFFSETS = [(dj, di) for dj in (-1, 0, 1) for di in (-1, 0, 1)]


def _iso(t):
    return t.astimezone(UTC).isoformat()


def _sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stations_json_bytes(stations, cells):
    """The exact bytes ``hrrr_point_fetch.run`` wrote as stations.json on the Windows workstation
    (``Path.write_text`` translates newlines to CRLF there); the land file pins their sha."""
    obj = {st: {**stations[st], **cells[st]} for st in stations}
    return json.dumps(obj, indent=1, sort_keys=True).replace("\n", "\r\n").encode("utf-8")


# --------------------------------------------------------------------------- RN-1 point rule
def rn1_index(cell, land_block):
    """RN-1: the land cell (LAND == 1) of the 3x3 block nearest (fi, fj); ties to the lower index."""
    if len(land_block) != 9:
        raise ValueError("land block must have 9 cells")
    best = None
    for k, (dj, di) in enumerate(_OFFSETS):
        if land_block[k] != 1.0:
            continue
        d = math.hypot(cell["i"] + di - cell["fi"], cell["j"] + dj - cell["fj"])
        if best is None or d < best[0]:
            best = (d, k)
    return None if best is None else best[1]


def load_point_rule(land_path, stations, cells, expect_land_sha=LAND_SHA256,
                    expect_stations_sha=STATIONS_JSON_SHA256):
    """Verify the pinned land file against this station set and return {station: rn1 index}."""
    got = _sha_file(land_path)
    if got != expect_land_sha:
        raise SystemExit(f"land file sha {got} != pinned {expect_land_sha}")
    land = json.loads(Path(land_path).read_text(encoding="utf-8"))
    st_sha = hashlib.sha256(stations_json_bytes(stations, cells)).hexdigest()
    if st_sha != expect_stations_sha or land.get("stations_json_sha256") != st_sha:
        raise SystemExit(f"stations.json sha {st_sha} does not match the pinned point rule")
    out = {}
    for st, c in cells.items():
        rec = land["stations"].get(st)
        if rec is None or (rec["i"], rec["j"], rec["flat"]) != (c["i"], c["j"], c["flat"]):
            raise SystemExit(f"{st}: land file cell does not match the station cell")
        k = rn1_index(c, rec["land_block3x3"])
        if k != rec["rn1_chosen_index"]:
            raise SystemExit(f"{st}: recomputed RN-1 index {k} != pinned {rec['rn1_chosen_index']}")
        out[st] = k
    return out


# --------------------------------------------------------------------------- snapshots and wants
def window_end_utc(day, tz):
    return (dt.datetime(day.year, day.month, day.day, tzinfo=ZoneInfo(tz))
            + dt.timedelta(hours=VALID_END_LOCAL)).astimezone(UTC)


def snapshots_between(stations, lo, hi, hours=HOURS):
    """Snapshot keys with lo < snapshot <= hi: (station, local_date, hour, snapshot_utc, end_utc)."""
    out = []
    for st, m in stations.items():
        tz = ZoneInfo(m["tz"])
        d0 = lo.astimezone(tz).date() - dt.timedelta(days=1)
        d1 = hi.astimezone(tz).date() + dt.timedelta(days=1)
        d = d0
        while d <= d1:
            for hr in hours:
                s = h.snapshot_utc(d, m["tz"], hr)
                if lo < s <= hi:
                    out.append((st, d, hr, s, window_end_utc(d, m["tz"])))
            d += dt.timedelta(days=1)
    return sorted(out, key=lambda r: (r[3], r[0]))


def lm_availability(listing, cycles):
    """Training-rule availability {cycle: {fh: max(LastModified .grib2, .idx)}} from listings seen."""
    return {c: h.cycle_availability(listing, c, MAX_FH) for c in cycles}


def wanted_messages(now, upcoming, listing):
    """(cycle, fh) slots to read now: for each future snapshot, the newest candidate cycle (already
    started) whose needed fhs are all listed and published early enough to qualify by the snapshot."""
    want = set()
    for _st, _d, _hr, s, end in upcoming:
        for c in h.candidate_cycles(s, STRIDE, LOOKBACK):
            if c > now:
                continue
            fhs, _ = h.needed_fhs(c, s, end, MAX_FH)
            if not fhs:
                continue
            avail = h.cycle_availability(listing, c, MAX_FH)
            if all(fh in avail and avail[fh] + MARGIN <= s for fh in fhs):
                want.update((c, fh) for fh in fhs)
                break
    return want


def cycles_to_poll(now, upcoming, listing):
    """Started candidate cycles of future snapshots whose needed objects are not all listed yet."""
    out = set()
    for _st, _d, _hr, s, end in upcoming:
        for c in h.candidate_cycles(s, STRIDE, LOOKBACK):
            if c > now:
                continue
            fhs, _ = h.needed_fhs(c, s, end, MAX_FH)
            avail = h.cycle_availability(listing, c, MAX_FH)
            if any(fh not in avail for fh in fhs):
                out.add(c)
    return sorted(out)


# --------------------------------------------------------------------------- selection at a snapshot
def forward_availability(msgs, listing, snapshot):
    """{cycle: {fh: t}} usable at ``snapshot``: both variables retrieved at or before it and
    max(LastModified) + margin at or before it; t = max(LM + margin, retrieval) so margin 0 applies."""
    per = {}
    for (cyc, fh, var), rec in msgs.items():
        per.setdefault((cyc, fh), {})[var] = rec
    out = {}
    for (cyc, fh), recs in per.items():
        if any(v not in recs for v in VARS):
            continue
        got = max(dt.datetime.fromisoformat(recs[v]["retrieved_at_utc"]) for v in VARS)
        if got > snapshot:
            continue
        c = dt.datetime.fromisoformat(cyc)
        lm = h.cycle_availability(listing, c, MAX_FH).get(fh)
        if lm is None:
            continue
        out.setdefault(c, {})[fh] = max(lm + MARGIN, got)
    return out


def retrieved_only_availability(msgs, snapshot):
    per = {}
    for (cyc, fh, var), rec in msgs.items():
        per.setdefault((cyc, fh), {})[var] = dt.datetime.fromisoformat(rec["retrieved_at_utc"])
    out = {}
    for (cyc, fh), t in per.items():
        if all(v in t for v in VARS) and max(t.values()) <= snapshot:
            out.setdefault(dt.datetime.fromisoformat(cyc), {})[fh] = max(t.values())
    return out


def snapshot_row(key, msgs, listing, rn1, meta, now, last_poll, paused):
    """The once-written forward row for one snapshot (what a live server could have seen)."""
    st, d, hr, s, end = key
    cands = h.candidate_cycles(s, STRIDE, LOOKBACK)
    sel = h.select_cycle(s, end, forward_availability(msgs, listing, s), STRIDE, dt.timedelta(0),
                         MAX_FH, LOOKBACK)
    train = h.select_cycle(s, end, lm_availability(listing, cands), STRIDE, MARGIN, MAX_FH, LOOKBACK)
    ronly = h.select_cycle(s, end, retrieved_only_availability(msgs, s), STRIDE, dt.timedelta(0),
                           MAX_FH, LOOKBACK)
    row = {
        "station": st, "market": meta.get("market"), "local_date": d.isoformat(), "hour_local": hr,
        "snapshot_utc": _iso(s), "window_end_utc": _iso(end), "written_at_utc": _iso(now),
        "written_late_s": round((now - s).total_seconds(), 1),
        "last_poll_before_snapshot_utc": _iso(last_poll) if last_poll else None,
        "paused_at_snapshot": paused,
        **{k: sel[k] for k in ("cycle_utc", "fhs", "depth", "window_truncated_at_f18")},
        "training_rule_cycle_utc": train["cycle_utc"], "retrieved_only_cycle_utc": ronly["cycle_utc"],
        "point_rule": POINT_RULE, "rn1_index": rn1, "land_sha256": LAND_SHA256, "rule_shas": RULE_SHAS,
    }
    tmp, tcdc, tmp_near, shas, keys, etags, cap = [], [], [], {}, [], [], []
    if sel["cycle_utc"]:
        for fh in sel["fhs"]:
            for v in VARS:
                rec = msgs[(sel["cycle_utc"], fh, v)]
                shas.setdefault(v.split(":")[0], []).append(rec["msg_sha256"])
                cap.append(rec["captured_at_utc"])
                if v == VARS[0]:
                    keys.append(rec["key"])
                    etags.append(rec["grib_etag"])
                    tmp.append(rec["points"][st]["rn1"])
                    tmp_near.append(rec["points"][st]["nearest"])
                else:
                    tcdc.append(rec["points"][st]["rn1"])
    ok = bool(sel["cycle_utc"]) and rn1 is not None and all(math.isfinite(x) for x in tmp + tcdc)
    to_f = lambda k: (k - 273.15) * 9.0 / 5.0 + 32.0  # noqa: E731
    row.update({
        "tmp_k_rn1": tmp, "tcdc_pct_rn1": tcdc, "hrrr_msg_sha256": shas, "keys": keys, "grib_etags": etags,
        "captured_at_utc_max": max(cap) if cap else None,
        "k_max_f": max(to_f(x) for x in tmp) if ok else None,
        "k_tcdc": sum(tcdc) / len(tcdc) if ok else None,
        "k_max_f_nearest_cell": max(to_f(x) for x in tmp_near) if ok else None,
        "k_miss": 0 if ok else 1,
    })
    return row


# --------------------------------------------------------------------------- process guards
def set_below_normal_priority():
    try:
        if os.name == "nt":
            import ctypes

            k32 = ctypes.windll.kernel32
            k32.GetCurrentProcess.restype = ctypes.c_void_p
            k32.SetPriorityClass.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
            k32.GetPriorityClass.restype = ctypes.c_uint32
            k32.GetPriorityClass.argtypes = (ctypes.c_void_p,)
            me = k32.GetCurrentProcess()
            return bool(k32.SetPriorityClass(me, 0x00004000)) and k32.GetPriorityClass(me) == 0x00004000
        os.nice(5)
        return True
    except Exception:  # pragma: no cover - best effort, recorded in status
        return False


def acquire_lock(path):
    """Single-instance lock held for the life of the process (released by the OS on exit)."""
    fh = open(path, "a+")
    try:
        if os.name == "nt":
            import msvcrt

            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        raise SystemExit(f"another recorder holds {path}")
    return fh


class Throttle:
    """Bandwidth cap inside the recorder: average bytes/s plus a per-clock-hour ceiling."""

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
    def __init__(self, out, stations, land_path, fetcher, clock=None, sleep=time.sleep,
                 pause_file=None, stop_file=None, bytes_per_s=2_000_000, hourly_mb=50.0, min_free_gb=20.0,
                 disk_root="C:\\", expect_land_sha=LAND_SHA256, expect_stations_sha=STATIONS_JSON_SHA256):
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.stations = stations
        self.cells = {st: h.station_cell(m["lat"], m["lon"]) for st, m in stations.items()}
        if any(not c["inside"] for c in self.cells.values()):
            raise SystemExit("station outside the HRRR grid")
        self.rn1 = load_point_rule(land_path, stations, self.cells, expect_land_sha, expect_stations_sha)
        self.f = fetcher
        self.clock = clock or (lambda: dt.datetime.now(UTC))
        self.sleep = sleep
        self.pause_file = Path(pause_file) if pause_file else None
        self.stop_file = Path(stop_file) if stop_file else None
        self.throttle = Throttle(bytes_per_s, int(hourly_mb * 1_000_000), sleep)
        self.min_free = min_free_gb * h.GIB
        self.disk_root = disk_root
        self.code_sha = {"hrrr_forward_recorder.py": _sha_file(__file__),
                         "hrrr_point_fetch.py": _sha_file(h.__file__)}
        self.listing, self.listed_at, self.msgs, self.written = {}, {}, {}, set()
        self.idx_cache, self.last_poll, self.paused_since = {}, None, None
        self.fail_counts = {}
        self.foot = {"hour": None, "bytes": 0, "requests": 0, "cpu_s": 0.0, "messages": 0, "listings": 0}
        self._load()
        (self.out / "stations.json").write_bytes(stations_json_bytes(stations, self.cells))

    # ---- persistence
    def _p(self, name):
        return self.out / name

    def _load(self):
        meta = self._p("meta.json")
        if meta.exists():
            self.meta = json.loads(meta.read_text(encoding="utf-8"))
        else:
            self.meta = {"first_started_utc": _iso(self.clock()), "rule_shas": RULE_SHAS,
                         "point_rule": POINT_RULE, "rn1_index": self.rn1}
            h.write_json_atomic(meta, self.meta)
        if self.meta["rn1_index"] != self.rn1:
            raise SystemExit("point rule changed since this directory was started")
        self.first_started = dt.datetime.fromisoformat(self.meta["first_started_utc"])
        for rec in h.read_jsonl(self._p("listings.jsonl")):
            self.listing[rec["key"]] = {k: rec[k] for k in ("last_modified", "size", "etag")}
            self.listed_at.setdefault(rec["key"], rec["listed_at_utc"])
        for rec in h.read_jsonl(self._p("messages.jsonl")):
            if rec.get("status") == "ok":
                self.msgs[(rec["cycle_utc"], rec["fh"], rec["var"])] = rec
        for rec in h.read_jsonl(self._p("snapshots.jsonl")):
            self.written.add((rec["station"], rec["local_date"], rec["hour_local"]))

    def _account(self, now, nbytes=0, requests=0, messages=0, listings=0):
        hour = now.replace(minute=0, second=0, microsecond=0)
        cpu = time.process_time()
        if self.foot["hour"] != hour:
            if self.foot["hour"] is not None:
                h.append_jsonl(self._p("footprint.jsonl"), {
                    "hour_utc": _iso(self.foot["hour"]), "mb": round(self.foot["bytes"] / 1e6, 3),
                    "requests": self.foot["requests"], "cpu_s": round(cpu - self.foot["cpu0"], 3),
                    "messages": self.foot["messages"], "listings": self.foot["listings"]})
            self.foot = {"hour": hour, "bytes": 0, "requests": 0, "cpu0": cpu, "messages": 0, "listings": 0}
        self.foot["bytes"] += nbytes
        self.foot["requests"] += requests
        self.foot["messages"] += messages
        self.foot["listings"] += listings

    # ---- one pass
    def write_due(self, now):
        lo = max(self.first_started, now - dt.timedelta(days=2))
        n = 0
        for key in snapshots_between(self.stations, lo, now):
            st, d, hr, s, _ = key
            if (st, d.isoformat(), hr) in self.written:
                continue
            last = self.last_poll if self.last_poll and self.last_poll <= s else None
            row = snapshot_row(key, self.msgs, self.listing, self.rn1[st], self.stations[st], now, last,
                               self.paused_since is not None and self.paused_since <= s)
            h.append_jsonl(self._p("snapshots.jsonl"), row)
            self.written.add((st, d.isoformat(), hr))
            n += 1
        return n

    def poll(self, now):
        upcoming = snapshots_between(self.stations, now, now + dt.timedelta(hours=26))
        b0, r0 = self.f.used, self.f.requests
        for c in cycles_to_poll(now, upcoming, self.listing):
            page = self.f.list_prefix(h.cycle_prefix(c))
            t = _iso(self.clock())
            for key, ent in page.items():
                if self.listing.get(key) != ent:
                    self.listing[key] = ent
                    self.listed_at.setdefault(key, t)
                    h.append_jsonl(self._p("listings.jsonl"), {"key": key, "listed_at_utc": t, **ent})
            self._account(now, listings=1)
        self.last_poll = now
        fetched = 0
        for c, fh in sorted(wanted_messages(now, upcoming, self.listing)):
            for var in VARS:
                k = (_iso(c), fh, var)
                if k in self.msgs or self.fail_counts.get(k, 0) >= 3:
                    continue
                t_now = self.clock()
                if not self.throttle.allow(t_now, 1_300_000):
                    self.log_event("hourly_byte_ceiling", hour=_iso(t_now))
                    return fetched
                if h.free_bytes(self.disk_root) < self.min_free:
                    self.log_event("low_disk")
                    return fetched
                u0, w0 = self.f.used, time.time()
                try:
                    rec = h.fetch_message(self.f, c, fh, var, self.listing, self.cells, self.idx_cache)
                except (ValueError, LookupError) as e:
                    rec = {"key": h.grib_key(c, fh), "var": var, "cycle_utc": _iso(c), "fh": fh,
                           "status": "decode_error", "error": str(e)[:300]}
                got = self.clock()
                self.throttle.spent(self.f.used - u0, time.time() - w0)
                rec.update({"retrieved_at_utc": _iso(got), "captured_at_utc": _iso(got), "fxx": fh,
                            "listed_at_utc": self.listed_at.get(h.grib_key(c, fh))})
                if rec.get("status") == "ok":
                    for st, p in rec["points"].items():
                        p["rn1"] = p["block3x3"][self.rn1[st]] if self.rn1[st] is not None else None
                        p["rn1_index"] = self.rn1[st]
                    self.msgs[k] = rec
                    fetched += 1
                else:
                    self.fail_counts[k] = self.fail_counts.get(k, 0) + 1
                h.append_jsonl(self._p("messages.jsonl"), rec)
                self._account(got, messages=1)
        if len(self.idx_cache) > 64:
            self.idx_cache.clear()
        self._account(now, nbytes=self.f.used - b0, requests=self.f.requests - r0)
        return fetched

    def log_event(self, event, **kw):
        h.append_jsonl(self._p("events.jsonl"), {"event": event, "at_utc": _iso(self.clock()), **kw})

    def step(self):
        now = self.clock()
        written = self.write_due(now)
        paused = bool(self.pause_file and self.pause_file.exists())
        if paused and self.paused_since is None:
            self.paused_since = now
            self.log_event("pause_start")
            h.append_jsonl(self._p("gaps.jsonl"), {"gap": "pause_start", "at_utc": _iso(now)})
        elif not paused and self.paused_since is not None:
            h.append_jsonl(self._p("gaps.jsonl"), {"gap": "pause_end", "at_utc": _iso(now),
                                                  "started_utc": _iso(self.paused_since)})
            self.log_event("pause_end")
            self.paused_since = None
        fetched = 0 if paused else self.poll(now)
        self._account(self.clock())
        return {"written": written, "fetched": fetched, "paused": paused}

    def status(self, state, extra=None):
        h.write_json_atomic(self._p("status.json"), {
            "state": state, "pid": os.getpid(), "updated_utc": _iso(self.clock()),
            "first_started_utc": self.meta["first_started_utc"], "messages_ok": len(self.msgs),
            "snapshots_written": len(self.written), "bytes_this_process": self.f.used,
            "paused": self.paused_since is not None, "code_sha256": self.code_sha, **(extra or {})})

    def next_wake(self, now, poll_s):
        nxt = snapshots_between(self.stations, now, now + dt.timedelta(seconds=poll_s))
        if nxt:
            return max(1.0, (nxt[0][3] - now).total_seconds() + 2.0)
        return float(poll_s)

    def run(self, poll_s=120, max_steps=None):
        steps = 0
        self.log_event("start", pid=os.getpid(), code_sha256=self.code_sha)
        while True:
            if self.stop_file and self.stop_file.exists():
                self.log_event("stop_file")
                self.status("stopped_by_file")
                return
            try:
                res = self.step()
                self.status("running", res)
            except h.CapReached:
                self.log_event("cap_reached")
                self.status("cap_reached")
                return
            except Exception as e:  # keep recording; the failure is logged, never silently skipped
                self.log_event("step_error", error=repr(e)[:500], tb=traceback.format_exc()[-1500:])
                self.status("running_after_error")
            steps += 1
            if max_steps is not None and steps >= max_steps:
                return
            self.sleep(self.next_wake(self.clock(), poll_s))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=r"C:\t\l13\hrrr_forward")
    ap.add_argument("--land", default=r"C:\t\l13\land\land_3x3.json")
    ap.add_argument("--pause-file", default=r"C:\t\l13\RECORDER_PAUSE")
    ap.add_argument("--stop-file", default=r"C:\t\l13\hrrr_forward\STOP")
    ap.add_argument("--poll-seconds", type=int, default=120)
    ap.add_argument("--bytes-per-second", type=int, default=2_000_000, help="in-process bandwidth cap")
    ap.add_argument("--hourly-mb", type=float, default=50.0, help="per-clock-hour download ceiling")
    ap.add_argument("--cap-gb", type=float, default=15.0, help="hard byte cap for this process")
    ap.add_argument("--min-free-gb", type=float, default=20.0)
    ap.add_argument("--max-steps", type=int, default=None)
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    lock = acquire_lock(out / "recorder.lock")  # noqa: F841 - held until exit
    prio = set_below_normal_priority()
    rec = Recorder(out, h.registry_stations(), args.land, h.Fetcher(int(args.cap_gb * h.GIB)),
                   pause_file=args.pause_file, stop_file=args.stop_file, bytes_per_s=args.bytes_per_second,
                   hourly_mb=args.hourly_mb, min_free_gb=args.min_free_gb)
    rec.log_event("priority", below_normal=prio)
    (out / "recorder.pid").write_text(str(os.getpid()), encoding="ascii")
    rec.run(args.poll_seconds, args.max_steps)


if __name__ == "__main__":
    main()
