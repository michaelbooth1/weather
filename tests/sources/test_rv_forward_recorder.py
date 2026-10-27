"""Offline checks for the L13 R-V forward MOS/NBE recorder and its parity tool (no network).

Guards: tools/research/rv_forward_recorder.py and rv_forward_parity.py. The input-fetch allowlist
(mos.py only, the 11 R0 ICAOs only, GFS/NAM/NBE only, refused before any network access), the
2026-09-30..10-15 blackout, the forward availability rule (runtime + lag AND first_seen <= cutoff, with
fallback to the older run), write-once run storage with first_seen_utc, the HRRR-style guards (STOP,
pause, hourly ceiling, throttle back-off), and parity exact/mismatch against an archive refetch.
"""
import datetime as dt
import math
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from tools.research import rv_forward_parity as par
from tools.research import rv_forward_recorder as rec

UTC = dt.timezone.utc


def T(*a):
    return dt.datetime(*a, tzinfo=UTC)


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += dt.timedelta(seconds=s)


HEADERS = {"GFS": "runtime,ftime,model,n_x,tmp,station", "NAM": "runtime,ftime,model,n_x,tmp,station",
           "NBE": "runtime,ftime,model,tmp,station,txn"}


def value(st, model, runtime):
    return 50 + (sum(map(ord, st)) + sum(map(ord, model)) + runtime.hour + runtime.day) % 30


class FakeIEM:
    """Publishes run ``runtime`` of (station, model) at ``published(st, model, runtime)``."""

    def __init__(self, clock, published=None, override=None, status=200):
        self.clock, self.calls, self.status = clock, [], status
        self.published = published or (lambda st, m, rt: rt + dt.timedelta(seconds=rec.MODELS[m][2] - 600))
        self.override = override or {}

    def rows(self, st, model, runtime):
        out = []
        for k in range(1, 13):
            ftime = runtime + dt.timedelta(hours=6 * k)
            ftime = ftime.replace(hour=ftime.hour // 6 * 6)
            v = self.override.get((st, model, runtime, ftime), value(st, model, runtime) + k % 3)
            f = lambda t: t.strftime("%Y-%m-%d %H:%M:%S")  # noqa: E731
            if model == "NBE":
                out.append(f"{f(runtime)},{f(ftime)},NBE,{v - 5}.0,{st},{v}.0\n")
            else:
                out.append(f"{f(runtime)},{f(ftime)},{model},{v},{v - 5},{st}\n")
        return out

    def __call__(self, full_url):
        self.calls.append(full_url)
        if self.status != 200:
            return self.status, b"Too many requests"
        q = {k: v[0] for k, v in parse_qs(urlsplit(full_url).query).items()}
        sts = dt.datetime.strptime(q["sts"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=UTC)
        ets = dt.datetime.strptime(q["ets"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=UTC)
        body = [HEADERS[q["model"]] + "\n"]
        t = sts.replace(minute=0)
        while t <= ets:
            if t.hour in (0, 1, 6, 7, 12, 13, 18, 19) and not (q["model"] == "NBE" and t.hour == 1 and t.year == 2026):
                if self.published(q["station"], q["model"], t) <= self.clock():
                    body += self.rows(q["station"], q["model"], t)
            t += dt.timedelta(hours=1)
        return 200, "".join(body).encode()


def client(clock, iem):
    return rec.Client(iem, clock, sleep=clock.sleep)


def recorder(tmp_path, clock, iem, **kw):
    return rec.Recorder(tmp_path / "fwd", client(clock, iem), clock, sleep=clock.sleep, disk_root=str(tmp_path),
                        min_free_gb=0.0, **kw)


def run_until(r, clock, end):
    while clock() < end:
        r.step()
        clock.sleep(r.next_wake(300))


# --------------------------------------------------------------------------- allowlist
def test_allowlist_refuses_other_url_station_product_and_params_before_any_network():
    clock = Clock(T(2026, 11, 2, 12))
    iem = FakeIEM(clock)
    c = client(clock, iem)
    good = rec.request_params("KATL", "GFS", T(2026, 11, 2), T(2026, 11, 2, 6, 59))
    assert rec.check_request(rec.URL, good).startswith(rec.URL + "?")
    with pytest.raises(rec.AllowlistError):
        rec.check_request("https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py", good)
    with pytest.raises(rec.AllowlistError):
        rec.check_request(rec.URL.replace("https", "http"), good)
    for bad in ({**good, "station": "KDEN"}, {**good, "model": "LAV"}, {**good, "model": "NBS"},
                {**good, "format": "json"}, {**good, "extra": "1"}):
        with pytest.raises(rec.AllowlistError):
            c.fetch(bad)
    assert iem.calls == []


@pytest.mark.parametrize("sts,ets", [
    (T(2026, 9, 30), T(2026, 9, 30, 6, 59)),
    (T(2026, 10, 15), T(2026, 10, 15, 6, 59)),
    (T(2026, 10, 10), T(2026, 10, 20, 0, 0)),
    (T(2026, 9, 29), T(2026, 9, 30, 0, 0)),
    (T(2026, 10, 15, 23, 59), T(2026, 10, 16, 6, 0)),
])
def test_blackout_window_is_refused(sts, ets):
    iem = FakeIEM(Clock(T(2026, 11, 2)))
    with pytest.raises(rec.AllowlistError):
        client(Clock(T(2026, 11, 2)), iem).fetch(rec.request_params("KATL", "NBE", sts, ets))
    assert iem.calls == []


def test_windows_next_to_the_blackout_and_long_windows():
    rec.check_request(rec.URL, rec.request_params("KATL", "GFS", T(2026, 9, 29), T(2026, 9, 29, 23, 59)))
    rec.check_request(rec.URL, rec.request_params("KATL", "GFS", T(2026, 10, 16), T(2026, 10, 25, 23, 59)))
    with pytest.raises(rec.AllowlistError):
        rec.check_request(rec.URL, rec.request_params("KATL", "GFS", T(2026, 10, 16), T(2026, 10, 27)))


def test_stations_are_the_registry_r0_eleven():
    from weather.market.market_registry import spec_for_id

    assert len(rec.STATIONS) == 11
    for icao, (market, tz) in rec.STATIONS.items():
        spec = spec_for_id(market)
        assert (spec.icao, spec.timezone) == (icao, tz)


def test_module_is_standalone():
    for name in ("rv_forward_recorder.py", "rv_forward_parity.py"):
        src = (Path(rec.__file__).parent / name).read_text(encoding="utf-8")
        assert "import pooled_residual_model" not in src and "pooled_residual_model import" not in src


def test_models_copy_rv_sources():
    assert rec.MODELS == {"GFS": ("n_x", (6, 0), 16200), "NAM": ("n_x", (0,), 14400), "NBE": ("txn", (1, 0), 7200)}


# --------------------------------------------------------------------------- availability rule
def test_cutoff_rule_needs_lag_and_first_seen_and_falls_back_to_the_older_run():
    day = dt.date(2026, 11, 2)
    f = T(2026, 11, 3)
    g00, g06 = T(2026, 11, 2, 0), T(2026, 11, 2, 6)
    values = {(g00, f): 70.0, (g06, f): 72.0}
    sel = rec.select_source
    # training rule: 06Z usable from 10:30Z
    assert sel(values, "GFS", day, T(2026, 11, 2, 10, 29)) == (70.0, g00)
    assert sel(values, "GFS", day, T(2026, 11, 2, 10, 30)) == (72.0, g06)
    assert sel(values, "GFS", day, T(2026, 11, 2, 4, 29)) == (pytest.approx(float("nan"), nan_ok=True), None)
    # forward rule: also first_seen <= cutoff
    seen = {g00: T(2026, 11, 2, 4, 31), g06: T(2026, 11, 2, 18, 30)}  # 06Z first seen late
    assert sel(values, "GFS", day, T(2026, 11, 2, 18), seen) == (70.0, g00)
    assert sel(values, "GFS", day, T(2026, 11, 2, 18, 30), seen) == (72.0, g06)
    assert sel(values, "GFS", day, T(2026, 11, 2, 4, 30), seen)[1] is None  # lag met, not yet seen
    assert sel(values, "GFS", day, T(2026, 11, 2, 18), {g06: seen[g06]})[1] is None  # 00Z never seen
    # out-of-range value is skipped like a missing one
    assert sel({(g00, f): 70.0, (g06, f): 140.0}, "GFS", day, T(2026, 11, 2, 12))[1] == g00


def test_mos_x_needs_two_sources_and_uses_local_cutoff():
    day = dt.date(2026, 11, 2)
    f = T(2026, 11, 3)
    tables = {"GFS": {(T(2026, 11, 2, 6), f): 70.0}, "NBE": {(T(2026, 11, 2, 0), f): 74.0}}
    e = rec.entry(tables, "KATL", day, 13)  # 13:00 EST = 18Z
    assert e["mos_x"] == 72.0 and e["runs"]["NAM"] is None
    assert rec.cutoff_instant("KSFO", day, 16) == T(2026, 11, 3, 0)
    assert math.isnan(rec.entry({"GFS": tables["GFS"]}, "KATL", day, 13)["mos_x"])


# --------------------------------------------------------------------------- write-once store
def test_write_once_keeps_first_bytes_and_first_seen_and_logs_revisions(tmp_path):
    s = rec.Store(tmp_path)
    rt = T(2026, 11, 2, 6)
    a, b = b"runtime,ftime\nx\n", b"runtime,ftime\ny\n"
    assert s.put("KATL", "GFS", rt, a, T(2026, 11, 2, 10, 30), T(2026, 11, 2, 10, 31)) == "stored"
    assert s.put("KATL", "GFS", rt, a, T(2026, 11, 2, 11), T(2026, 11, 2, 11, 1)) == "same"
    assert s.put("KATL", "GFS", rt, b, T(2026, 11, 2, 12), T(2026, 11, 2, 12, 1)) == "revision"
    assert s.put("KATL", "GFS", rt, b, T(2026, 11, 2, 13), T(2026, 11, 2, 13, 1)) == "revision"
    path = s.path("KATL", "GFS", rt)
    assert path.read_bytes() == a
    again = rec.Store(tmp_path)
    assert again.runs[("KATL", "GFS", rt)]["first_seen_utc"] == "2026-11-02T10:31:00Z"
    assert len((tmp_path / "revisions.jsonl").read_text().splitlines()) == 1
    assert again.put("KATL", "GFS", rt, b, T(2026, 11, 3), T(2026, 11, 3)) == "revision"
    assert path.read_bytes() == a
    (tmp_path / "runs.jsonl").unlink()  # even with the ledger lost, the file layer refuses a rewrite
    with pytest.raises(FileExistsError):
        rec.Store(tmp_path).put("KATL", "GFS", rt, b, T(2026, 11, 3), T(2026, 11, 3))
    assert path.read_bytes() == a


# --------------------------------------------------------------------------- recorder
def test_recorder_records_first_seen_requests_when_due_and_applies_the_forward_rule(tmp_path):
    clock = Clock(T(2026, 11, 2, 0, 0))
    late = T(2026, 11, 2, 17, 20)
    pub = lambda st, m, rt: late if (m == "GFS" and rt == T(2026, 11, 2, 6)) else rt + dt.timedelta(  # noqa: E731
        seconds=rec.MODELS[m][2] - 600)
    iem = FakeIEM(clock, published=pub)
    r = recorder(tmp_path, clock, iem)
    run_until(r, clock, T(2026, 11, 3, 2))
    runs = r.store.runs
    # every needed run except NBE 01Z (not issued in 2026) is stored for every station
    assert len(runs) == 11 * 4
    for st in rec.STATIONS:
        nbe = runs[(st, "NBE", T(2026, 11, 2, 0))]
        assert rec._parse_iso(nbe["first_seen_utc"]) <= T(2026, 11, 2, 2, 5)
        g06 = rec._parse_iso(runs[(st, "GFS", T(2026, 11, 2, 6))]["first_seen_utc"])
        assert late <= g06 <= late + dt.timedelta(hours=1)
        assert rec._parse_iso(runs[(st, "GFS", T(2026, 11, 2, 0))]["first_seen_utc"]) >= T(2026, 11, 2, 4, 30)
    # nothing was requested before a run's lag had passed
    for url in iem.calls:
        q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        assert q["sts"].startswith("2026-11-02")
    assert len(iem.calls) < 300  # NBE 01Z (absent in 2026) is retried hourly until 8 h overdue
    tables, seen = r.store.tables("KATL")
    day = dt.date(2026, 11, 2)
    assert rec.entry(tables, "KATL", day, 13, seen)["runs"]["GFS"] == T(2026, 11, 2, 0)  # 18Z < first_seen
    assert rec.entry(tables, "KATL", day, 14, seen)["runs"]["GFS"] == T(2026, 11, 2, 6)
    assert rec.entry(tables, "KATL", day, 13)["runs"]["GFS"] == T(2026, 11, 2, 6)  # training rule alone


def test_restart_does_not_rewrite_or_backfill_days_before_the_first_start(tmp_path):
    clock = Clock(T(2026, 11, 2, 12, 0))
    iem = FakeIEM(clock)
    r = recorder(tmp_path, clock, iem)
    r.step()
    first = dict(r.store.runs)
    assert first and all(k[2].date() == dt.date(2026, 11, 2) for k in first)  # 11-01 is before the start
    clock.sleep(3600)
    r2 = recorder(tmp_path, clock, iem)
    r2.step()
    for k, v in first.items():
        assert r2.store.runs[k] == v


def test_stop_pause_ceiling_and_throttle_guards(tmp_path):
    clock = Clock(T(2026, 11, 2, 12, 0))
    iem = FakeIEM(clock)
    pause, stop = tmp_path / "PAUSE", tmp_path / "STOP"
    r = recorder(tmp_path, clock, iem, pause_file=pause, stop_file=stop, hourly_requests=3)
    pause.write_text("")
    assert r.step() == 0 and iem.calls == []
    pause.unlink()
    r.step()
    assert len(iem.calls) == 3  # hourly ceiling
    events = (tmp_path / "fwd" / "events.jsonl").read_text()
    assert "hourly_request_ceiling" in events and "pause_start" in events and "pause_end" in events
    assert "pause_start" in (tmp_path / "fwd" / "gaps.jsonl").read_text()
    stop.write_text("")
    r.run(max_steps=5)
    assert len(iem.calls) == 3
    t_iem = FakeIEM(clock, status=429)
    t = recorder(tmp_path / "t", clock, t_iem)
    assert t.step() == 0 and len(t_iem.calls) == 1 and t.backoff_until > clock()
    assert t.step() == 0 and len(t_iem.calls) == 1


# --------------------------------------------------------------------------- parity
def _forward(tmp_path):
    clock = Clock(T(2026, 11, 2, 0, 0))
    r = recorder(tmp_path, clock, FakeIEM(clock))
    run_until(r, clock, T(2026, 11, 4, 2))
    return r


def test_parity_exact_then_mismatch(tmp_path):
    _forward(tmp_path)
    day0, day1 = dt.date(2026, 11, 2), dt.date(2026, 11, 3)
    now = Clock(T(2026, 11, 5, 18))
    par.refetch(tmp_path / "arc", day0, day1, client(now, FakeIEM(now)), now())
    ok = par.compare(tmp_path / "fwd", tmp_path / "arc", day0, day1)
    assert ok["pass"] and ok["selected_compared"] == 2 * 11 * 4 and ok["rows_identical"] == 2 * 11 * 4
    assert ok["mos_x_compared"] == 2 * 11 * 4 and ok["late_share"] == 0.0
    bad_key = ("KMIA", "NBE", T(2026, 11, 3, 0), T(2026, 11, 4, 0))
    par.refetch(tmp_path / "arc2", day0, day1, client(now, FakeIEM(now, override={bad_key: 99})), now())
    bad = par.compare(tmp_path / "fwd", tmp_path / "arc2", day0, day1)
    assert not bad["pass"]
    assert [m["run"] for m in bad["selected_mismatches"]] == ["KMIA/NBE/2026-11-03T00:00:00Z"]
    assert bad["mos_x_mismatches"] and bad["rows_differ"] == ["KMIA/NBE/2026-11-03T00:00:00Z"]


def test_parity_refetch_window_rules(tmp_path):
    now = Clock(T(2026, 11, 5, 18))
    c = client(now, FakeIEM(now))
    with pytest.raises(rec.AllowlistError):  # not yet over
        par.refetch(tmp_path, dt.date(2026, 11, 2), dt.date(2026, 11, 4), c, now())
    with pytest.raises(rec.AllowlistError):  # blackout
        par.refetch(tmp_path, dt.date(2026, 10, 14), dt.date(2026, 10, 17), c, now())
    with pytest.raises(rec.AllowlistError):  # too long
        par.refetch(tmp_path, dt.date(2026, 10, 16), dt.date(2026, 10, 30), c, now())
