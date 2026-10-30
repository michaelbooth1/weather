"""Lane L13 GEFS 00/12/18Z forward recorder (tools/research/gefs_cycles_forward_recorder.py).

Offline: a clock-driven fake S3 serves listings, .idx files and Range reads; the GRIB decoder is stubbed (it is the
unchanged gefs_member_point_fetch decoder, tested on its own).

Guards: forward-only cycles from 2026-10-28 00Z, back-fill oldest first after the live cycle with ``backfill`` on every
row, true S3 LastModified as ``available_utc``, identity checks, slot closing and retries, restart without refetch,
pause and STOP, the 12 registry stations and DST-correct local dates.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from urllib.parse import unquote

import numpy as np
import pytest

from tools.research import gefs_cycles_forward_recorder as rc
from tools.research import gefs_member_point_fetch as g

UTC = dt.timezone.utc
MEMBERS = ("gec00", "gep01", "gep02")
FHS = (3, 6)


def _t(*a):
    return dt.datetime(*a, tzinfo=UTC)


class _Resp:
    def __init__(self, status, content):
        self.status_code, self.content = status, content
        self.text = content.decode("latin-1")


class _Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += dt.timedelta(seconds=s)


class _FakeS3:
    def __init__(self):
        self.objects, self.calls = {}, []

    def publish(self, cycle, member, fh, lm, ref=None):
        key = rc.grib_key(cycle, member, fh)
        blob = f"{(ref or cycle).isoformat()}|{member}|{fh}#".encode() * 4
        idx = f"1:0:d={cycle:%Y%m%d%H}:TMP:2 m above ground:{fh} hour fcst:ENS=+1\n".encode()
        stamp = lm.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        self.objects[key] = (blob, stamp)
        self.objects[key + ".idx"] = (idx, stamp)

    def publish_cycle(self, cycle, lm, members=MEMBERS, fhs=FHS):
        for m in members:
            for fh in fhs:
                self.publish(cycle, m, fh, lm)

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append((url, dict(params or {}), dict(headers or {})))
        if params:
            keys = sorted(k for k in self.objects if k.startswith(params["prefix"]) and k > params["start-after"])
            keys = keys[:int(params["max-keys"])]
            body = "".join(f"<Contents><Key>{k}</Key><LastModified>{self.objects[k][1]}</LastModified>"
                           f"<Size>{len(self.objects[k][0])}</Size><ETag>\"{hashlib.md5(self.objects[k][0]).hexdigest()}"
                           f"\"</ETag></Contents>" for k in keys)
            return _Resp(200, f"<ListBucketResult><IsTruncated>false</IsTruncated>{body}</ListBucketResult>".encode())
        key = unquote(url.split(".amazonaws.com/", 1)[1])
        if key not in self.objects:
            return _Resp(404, b"")
        blob = self.objects[key][0]
        if headers and "Range" in headers:
            a, b = (int(x) for x in headers["Range"].split("=")[1].split("-"))
            return _Resp(206, blob[a:b + 1])
        return _Resp(200, blob)


@pytest.fixture
def small(monkeypatch):
    def decode(blob):
        ref, member, fh = blob.decode().split("#")[0].split("|")
        pert = 0 if member == "gec00" else int(member[3:])
        meta = {"discipline": 0, "category": 0, "number": 0, "surface_type": 103, "surface_value": 2.0,
                "ref_time_utc": ref, "fh": int(fh), "ensemble_type": 3 if pert else 1, "perturbation": pert}
        return meta, np.full((721, 1440), 280.0 + pert)

    monkeypatch.setattr(g, "decode_field", decode)
    monkeypatch.setattr(g, "MEMBERS", MEMBERS)
    monkeypatch.setattr(rc, "FHS", FHS)


def _recorder(tmp_path, clock, s3, **kw):
    kw.setdefault("bytes_per_s", 0)  # no throttle sleep, so the fake clock stays exact
    return rc.Recorder(tmp_path / "out", g.Fetcher(10**12, session=s3, pause=0.0), clock=clock, sleep=clock.sleep,
                       **kw)


def _rows(tmp_path, cycle):
    return [json.loads(x) for x in (tmp_path / "out" / f"{cycle:%Y%m%d%H}" / "rows.jsonl").read_text().splitlines()]


def _manifest(tmp_path, cycle):
    return json.loads((tmp_path / "out" / f"{cycle:%Y%m%d%H}" / "manifest.json").read_text())


def test_stations_are_the_twelve_registry_markets():
    st = rc.stations_from_registry()
    assert len(st) == 12 and st["toronto"]["tz"] == "America/Toronto"
    for s in st.values():
        c = g.station_corners(s["lat"], s["lon"])
        assert 0 <= c["j0"] < 720 and 0 <= c["i0"] < 1440


def test_live_cycle_first_then_backfill_oldest_first_with_flags(tmp_path, small):
    s3 = _FakeS3()
    for c in (_t(2026, 10, 28, 0), _t(2026, 10, 28, 12), _t(2026, 10, 28, 18), _t(2026, 10, 29, 0)):
        s3.publish_cycle(c, c + dt.timedelta(hours=3, minutes=50))
    clock = _Clock(_t(2026, 10, 29, 6, 0))
    r = _recorder(tmp_path, clock, s3)
    res = r.step()
    assert res["active_cycles"] == ["2026102900", "2026102800", "2026102812", "2026102818"]
    assert res["fetched"] == 4 * len(MEMBERS) * len(FHS)
    assert not any("gefs.20261027" in c[0] or "gefs.20261027" in str(c[1]) for c in s3.calls)
    assert not any("/06/atmos/" in c[0] or "/06/atmos/" in str(c[1]) for c in s3.calls)  # 06Z is the other recorder
    live = [x for x in _rows(tmp_path, _t(2026, 10, 29, 0)) if x.get("status") == "ok"]
    old = [x for x in _rows(tmp_path, _t(2026, 10, 28, 12)) if x.get("status") == "ok"]
    assert all(x["backfill"] is False for x in live) and all(x["backfill"] is True for x in old)
    x = old[0]
    assert x["available_utc"] == "2026-10-28T15:50:00+00:00" and x["fetched_utc"] == "2026-10-29T06:00:00+00:00"
    assert x["fetch_lag_s"] == 14 * 3600 + 600
    assert {"grib_last_modified", "idx_last_modified", "idx_sha256", "message_sha256", "listed_utc",
            "idx_fetched_utc"} <= set(x)
    assert len(x["points"]) == 12
    man = _manifest(tmp_path, _t(2026, 10, 28, 12))
    assert man["ok"] == 6 and man["backfill_rows"] == 6 and man["live_rows"] == 0 and man["slots_missing"] == []
    rows_path = tmp_path / "out" / "2026102812" / "rows.jsonl"
    assert man["rows_sha256"] == hashlib.sha256(rows_path.read_bytes()).hexdigest()
    assert _manifest(tmp_path, _t(2026, 10, 29, 0))["live_rows"] == 6


def test_local_dates_follow_zoneinfo_across_the_fall_back(tmp_path, small):
    s3 = _FakeS3()
    c = _t(2026, 11, 1, 0)
    s3.publish_cycle(c, c + dt.timedelta(hours=4), fhs=(3, 6))
    r = _recorder(tmp_path, _Clock(_t(2026, 11, 1, 5)), s3, first_cycle=c)
    r.step()
    pts = {x["fh"]: x["points"] for x in _rows(tmp_path, c) if x.get("status") == "ok" and x["member"] == "gec00"}
    # valid 03Z = 23:00 EDT on 10-31; valid 06Z = 01:00 EST on 11-01 (after the repeated hour)
    assert pts[3]["nyc"]["local_date"] == "2026-10-31" and pts[3]["nyc"]["local_time"].endswith("-04:00")
    assert pts[6]["nyc"]["local_date"] == "2026-11-01" and pts[6]["nyc"]["local_time"] == "2026-11-01T01:00:00-05:00"
    assert pts[6]["denver"]["local_time"] == "2026-11-01T00:00:00-06:00"  # Denver falls back at 08Z


def test_unlisted_slots_close_after_36_h_but_failed_slots_keep_retrying(tmp_path, small, monkeypatch):
    s3 = _FakeS3()
    c = _t(2026, 10, 28, 0)
    s3.publish_cycle(c, c + dt.timedelta(hours=4), members=MEMBERS[:2])
    s3.publish(c, "gep02", 3, c + dt.timedelta(hours=4), ref=c - dt.timedelta(hours=6))  # wrong reference time
    clock = _Clock(_t(2026, 10, 28, 5))
    r = _recorder(tmp_path, clock, s3)
    assert r.step()["fetched"] == 4
    bad = [x for x in _rows(tmp_path, c) if x.get("status") == "decode_error"]
    assert len(bad) == 1 and "time" in bad[0]["error"] and bad[0]["backfill"] is False
    clock.t = c + rc.CLOSE_AFTER + dt.timedelta(minutes=1)
    r.step()  # gep02 f003 failed once: still retried, so the cycle stays open
    assert not (tmp_path / "out" / "2026102800" / "manifest.json").exists()
    for _ in range(rc.MAX_TRIES):
        r.step()
    man = _manifest(tmp_path, c)
    assert man["ok"] == 4 and sorted(map(tuple, man["slots_missing"])) == [("gep02", 3), ("gep02", 6)]
    rows = _rows(tmp_path, c)
    assert sum(x.get("status") == "decode_error" for x in rows) == rc.MAX_TRIES
    assert sum(x.get("status") == "object_missing" for x in rows) == 1 and rows[-1]["kind"] == "cycle_done"
    gaps = [json.loads(x) for x in (tmp_path / "out" / "gaps.jsonl").read_text().splitlines()]
    assert {(x["member"], x["fh"]) for x in gaps if x["gap"] == "slot_missing"} == {("gep02", 3), ("gep02", 6)}


def test_restart_reloads_without_refetching(tmp_path, small):
    s3 = _FakeS3()
    c = _t(2026, 10, 30, 12)
    s3.publish_cycle(c, c + dt.timedelta(hours=4), members=MEMBERS[:1])
    clock = _Clock(_t(2026, 10, 30, 16, 30))
    assert _recorder(tmp_path, clock, s3, first_cycle=c).step()["fetched"] == 2
    r2 = _recorder(tmp_path, clock, s3, first_cycle=c)
    n = len(s3.calls)
    assert r2.step()["fetched"] == 0 and all(call[1] for call in s3.calls[n:])  # listings only
    s3.publish_cycle(c, c + dt.timedelta(hours=4, minutes=20), members=MEMBERS[1:])
    assert r2.step()["fetched"] == 4 and _manifest(tmp_path, c)["ok"] == 6


def test_hourly_ceiling_stops_the_pass(tmp_path, small):
    s3 = _FakeS3()
    c = _t(2026, 10, 28, 0)
    s3.publish_cycle(c, c + dt.timedelta(hours=4))
    r = _recorder(tmp_path, _Clock(_t(2026, 10, 28, 5)), s3, hourly_mb=rc.MESSAGE_BYTES * 0.5 / 1e6)
    res = r.step()
    assert res["fetched"] == 0 and res["active_cycles"] == ["2026102800"]  # one message's size hint is over the cap
    assert not (tmp_path / "out" / "2026102800" / "manifest.json").exists()
    events = [json.loads(x)["event"] for x in (tmp_path / "out" / "events.jsonl").read_text().splitlines()]
    assert "hourly_byte_ceiling" in events


def test_pause_and_stop(tmp_path, small):
    s3 = _FakeS3()
    clock = _Clock(_t(2026, 10, 28, 5))
    r = _recorder(tmp_path, clock, s3)
    (tmp_path / "out" / "RECORDER_PAUSE").write_text("")
    assert r.step() == {"fetched": 0, "active_cycles": [], "paused": True} and s3.calls == []
    (tmp_path / "out" / "RECORDER_PAUSE").unlink()
    r.step()
    gaps = [json.loads(x)["gap"] for x in (tmp_path / "out" / "gaps.jsonl").read_text().splitlines()]
    assert gaps[:2] == ["pause_start", "pause_end"]
    (tmp_path / "out" / "STOP").write_text("")
    r.run(poll_s=1, max_steps=5)
    assert json.loads((tmp_path / "out" / "status.json").read_text())["state"] == "stopped_by_file"
