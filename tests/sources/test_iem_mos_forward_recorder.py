"""Lane L13 IEM MOS forward recorder (tools/research/iem_mos_forward_recorder.py).

Guards: CSV parsing grouped by runtime (rows of another station or model refused, a non-CSV body refused), one version
per changed run and none for an unchanged one, revisions numbered, the absent-at bound and backfill flag, the request
window (first lookback, revisit before the newest run, never before the forward start), empty answers logged not
failed, throttle back-off then give-up, request spacing, restart idempotence, the byte cap, and pause and STOP files.
No network: an in-memory fake serves the archive answers.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from urllib.parse import parse_qs, urlsplit

import pytest

from weather.paths import REPO_ROOT

_spec = importlib.util.spec_from_file_location("iem_mos_forward_recorder",
                                               REPO_ROOT / "tools/research/iem_mos_forward_recorder.py")
rc = importlib.util.module_from_spec(_spec)
sys.modules["iem_mos_forward_recorder"] = rc
_spec.loader.exec_module(rc)

UTC = dt.timezone.utc
STATIONS = {"CYYZ": "toronto", "KLGA": "nyc"}
HEADER = "runtime,ftime,model,tmp,dpt,n_x,station"
RT1 = dt.datetime(2026, 10, 30, 12, tzinfo=UTC)
RT2 = dt.datetime(2026, 10, 30, 18, tzinfo=UTC)


def rows(station, model, rt, temps):
    return [f"{rt:%Y-%m-%d %H:%M:%S},{rt + dt.timedelta(hours=3 * (i + 1)):%Y-%m-%d %H:%M:%S},{model},{t},40,{t + 5},"
            f"{station}" for i, t in enumerate(temps)]


def csv_text(lines):
    return "\n".join([HEADER, *lines]) + "\n"


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class FakeHttp:
    """Serves ``answers[(station, model)]`` (a body or a list of bodies, consumed in order); records each URL."""

    def __init__(self, answers, cap=10**9):
        self.answers, self.cap, self.used, self.requests, self.urls = answers, cap, 0, 0, []

    def get(self, url, timeout=120):
        if self.used >= self.cap:
            raise rc.CapReached(self.used)
        q = parse_qs(urlsplit(url).query)
        self.urls.append(url)
        a = self.answers.get((q["station"][0], q["model"][0]), "runtime,ftime,model,station\n")
        if isinstance(a, list):
            a = a.pop(0) if len(a) > 1 else a[0]
        status, body = a if isinstance(a, tuple) else (200, a)
        data = body.encode()
        self.requests += 1
        self.used += len(data)
        return rc.Resp(status, data, {})


def make(tmp_path, answers, now, models=("NBS",), **kw):
    sleeps = []
    clock = Clock(now)
    mono = [0.0]

    def sleep(s):
        sleeps.append(s)
        mono[0] += s

    http = kw.pop("http", None) or FakeHttp(answers)
    r = rc.Recorder(tmp_path / "out", http, stations=STATIONS, clock=clock, sleep=sleep, monotonic=lambda: mono[0],
                    models=models, min_free_gb=0, **kw)
    return r, http, clock, sleeps


def versions(tmp_path):
    out = []
    for p in sorted((tmp_path / "out").glob("*/*/*.jsonl")):
        out += [r for r in rc.read_jsonl(p) if r.get("kind") == "version"]
    return out


def events(tmp_path):
    return rc.read_jsonl(tmp_path / "out" / "events.jsonl")


def test_parse_csv_groups_by_runtime_and_refuses_foreign_rows():
    text = csv_text(rows("KLGA", "NBS", RT1, [50, 51]) + rows("KLGA", "NBS", RT2, [52]))
    runs = rc.parse_csv(text, "KLGA", "NBS")
    assert sorted(runs) == [RT1, RT2] and [r["tmp"] for r in runs[RT1]] == ["50", "51"]
    with pytest.raises(ValueError, match="row for KATL/NBS"):
        rc.parse_csv(csv_text(rows("KATL", "NBS", RT1, [1])), "KLGA", "NBS")
    with pytest.raises(ValueError, match="not a MOS CSV"):
        rc.parse_csv("Too many requests from your IP address, slow down.", "KLGA", "NBS")


def test_first_sweep_writes_one_version_per_run_and_logs_empty_pairs(tmp_path):
    now = dt.datetime(2026, 10, 30, 21, 30, tzinfo=UTC)
    ans = {("KLGA", "NBS"): csv_text(rows("KLGA", "NBS", RT1, [50, 51]) + rows("KLGA", "NBS", RT2, [52]))}
    r, http, _, _ = make(tmp_path, ans, now)
    assert r.step() == {"new_versions": 2, "requests": 2, "paused": False}
    v = versions(tmp_path)
    assert [(x["station"], x["runtime_utc"], x["n_rows"]) for x in v] == [
        ("KLGA", "2026-10-30T12:00:00Z", 2), ("KLGA", "2026-10-30T18:00:00Z", 1)]
    assert all(x["backfill"] and x["absent_at_utc"] is None and x["revision"] == 0 for x in v)
    assert v[0]["market"] == "nyc" and v[0]["schema"] == rc.SCHEMA and v[0]["rows"][0]["tmp"] == "50"
    assert (tmp_path / "out" / "20261030" / "18" / "NBS.jsonl").exists()
    assert [e["station"] for e in events(tmp_path) if e["event"] == "empty"] == ["CYYZ"]
    # first window: FIRST_LOOKBACK clipped to the forward start
    q = parse_qs(urlsplit(http.urls[0]).query)
    assert q["sts"] == ["2026-10-30T00:00Z"] and q["ets"] == ["2026-10-30T21:30Z"] and q["format"] == ["csv"]


def test_unchanged_run_is_not_rewritten_a_changed_one_is_a_revision_and_new_runs_get_absent_bound(tmp_path):
    t0 = dt.datetime(2026, 10, 30, 17, 0, tzinfo=UTC)
    first = csv_text(rows("KLGA", "NBS", RT1, [50]))
    second = csv_text(rows("KLGA", "NBS", RT1, [50]) + rows("KLGA", "NBS", RT2, [60]))
    third = csv_text(rows("KLGA", "NBS", RT1, [49]) + rows("KLGA", "NBS", RT2, [60]))
    r, http, clock, _ = make(tmp_path, {("KLGA", "NBS"): [first, second, third]}, t0)
    r.step()
    clock.t = dt.datetime(2026, 10, 30, 19, 40, tzinfo=UTC)
    assert r.step()["new_versions"] == 1  # RT2 new; RT1 unchanged
    clock.t = dt.datetime(2026, 10, 30, 20, 0, tzinfo=UTC)
    assert r.step()["new_versions"] == 1  # RT1 revised
    v = versions(tmp_path)
    rt2 = [x for x in v if x["runtime_utc"] == "2026-10-30T18:00:00Z"]
    assert len(rt2) == 1 and rt2[0]["absent_at_utc"] == "2026-10-30T17:00:00Z" and rt2[0]["backfill"] is False
    rt1 = [x for x in v if x["runtime_utc"] == "2026-10-30T12:00:00Z"]
    assert [x["revision"] for x in rt1] == [0, 1] and rt1[1]["rows"][0]["tmp"] == "49"
    # later windows revisit REVISIT before the newest recorded run
    assert parse_qs(urlsplit(http.urls[-1]).query)["sts"] == ["2026-10-30T12:00Z"]


def test_late_first_sighting_is_backfill_even_with_an_absent_bound(tmp_path):
    t0 = dt.datetime(2026, 10, 30, 11, 0, tzinfo=UTC)
    r, _, clock, _ = make(tmp_path, {("KLGA", "NBS"): ["runtime,ftime,model,station\n",
                                                       csv_text(rows("KLGA", "NBS", RT1, [50]))]}, t0)
    r.step()
    clock.t = RT1 + rc.LIVE_WINDOW + dt.timedelta(minutes=1)
    r.step()
    (v,) = versions(tmp_path)
    assert v["absent_at_utc"] == "2026-10-30T11:00:00Z" and v["backfill"] is True


def test_window_never_starts_before_forward_start_and_is_capped(tmp_path):
    now = dt.datetime(2026, 11, 5, 12, tzinfo=UTC)
    r, _, _, _ = make(tmp_path, {}, now)
    assert r.window_start("NBS", "KLGA", now) == now - rc.FIRST_LOOKBACK
    r.newest[("NBS", "KLGA")] = dt.datetime(2026, 11, 1, 0, tzinfo=UTC)
    assert r.window_start("NBS", "KLGA", now) == now - rc.WINDOW
    r.newest[("NBS", "KLGA")] = dt.datetime(2026, 11, 5, 6, tzinfo=UTC)
    assert r.window_start("NBS", "KLGA", now) == dt.datetime(2026, 11, 5, 0, tzinfo=UTC)
    with pytest.raises(SystemExit):
        make(tmp_path, {}, now, models=("XYZ",))


def test_throttle_backs_off_then_succeeds_and_gives_up_after_schedule(tmp_path):
    now = dt.datetime(2026, 10, 30, 21, tzinfo=UTC)
    slow = "Too many requests from your IP address, slow down."
    good = csv_text(rows("KLGA", "NBS", RT1, [50]))
    r, _, _, sleeps = make(tmp_path, {("KLGA", "NBS"): [slow, (429, "x"), good],
                                      ("CYYZ", "NBS"): [slow]}, now)
    out = r.step()
    assert out["new_versions"] == 1
    assert sleeps.count(60) >= 2 and 960 in sleeps  # KLGA backed off twice; CYYZ ran the whole schedule
    ev = events(tmp_path)
    assert [e["station"] for e in ev if e["event"] == "fetch_failed"] == ["CYYZ"]
    assert sum(e["event"] == "throttled" for e in ev) == 2 + len(rc.BACKOFF_S) + 1


def test_requests_are_spaced(tmp_path):
    now = dt.datetime(2026, 10, 30, 21, tzinfo=UTC)
    r, http, _, sleeps = make(tmp_path, {}, now, models=("NBS", "NBE"), spacing_s=5.0)
    r.step()
    assert http.requests == 4 and sleeps == [5.0, 5.0, 5.0]


def test_restart_is_idempotent(tmp_path):
    now = dt.datetime(2026, 10, 30, 21, tzinfo=UTC)
    ans = {("KLGA", "NBS"): csv_text(rows("KLGA", "NBS", RT1, [50]))}
    make(tmp_path, ans, now)[0].step()
    r2, http2, _, _ = make(tmp_path, dict(ans), now + dt.timedelta(minutes=20))
    assert r2.step()["new_versions"] == 0 and len(versions(tmp_path)) == 1
    assert parse_qs(urlsplit(http2.urls[-1]).query)["sts"] == ["2026-10-30T06:00Z"]


def test_byte_cap_stops_the_run(tmp_path):
    now = dt.datetime(2026, 10, 30, 21, tzinfo=UTC)
    http = FakeHttp({}, cap=0)
    r, _, _, _ = make(tmp_path, {}, now, http=http)
    r.run(poll_s=1, max_steps=3)
    assert json.loads((tmp_path / "out" / "status.json").read_text())["state"] == "cap_reached"


def test_pause_and_stop_files(tmp_path):
    now = dt.datetime(2026, 10, 30, 21, tzinfo=UTC)
    r, http, clock, _ = make(tmp_path, {}, now)
    r.pause_file.write_text("")
    assert r.step() == {"new_versions": 0, "requests": 0, "paused": True}
    r.pause_file.unlink()
    clock.t = now + dt.timedelta(minutes=20)
    r.step()
    gaps = rc.read_jsonl(tmp_path / "out" / "gaps.jsonl")
    assert [g["gap"] for g in gaps] == ["pause_start", "pause_end"] and http.requests == 2
    r.stop_file.write_text("")
    r.run(poll_s=1, max_steps=5)
    assert json.loads((tmp_path / "out" / "status.json").read_text())["state"] == "stopped_by_file"
    assert http.requests == 2


def test_output_inside_repo_is_refused():
    with pytest.raises(SystemExit, match="outside the repository"):
        rc.main(["--out", str(REPO_ROOT / "data" / "x"), "--once"])
