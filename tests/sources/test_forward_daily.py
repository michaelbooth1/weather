"""Lane L13 forward recorders: per-series local-day maximum and what "complete" means for a 6-hour Tmax.

Guards: L13 forward-recorder daily summaries refuse mixed runs or members, never sum overlapping coverage, and grade a
day exact / bounded / partial (windows) or hourly / partial (instants) on ZoneInfo bounds across the 2026-11-01 DST
change.
"""
from __future__ import annotations

import datetime as dt

import pytest

from tools.research import eccc_gem_daily as daily
from tools.research import forward_daily as fd

UTC = dt.timezone.utc
TOR = "America/Toronto"


def _t(*a):
    return dt.datetime(*a, tzinfo=UTC)


def _tmax_run(run, hours=72, window=6, hot=None, member=None):
    rows = []
    for step in range(window, hours + 1, window):
        end = run + dt.timedelta(hours=step)
        rows.append({"run_utc": run.isoformat(), "member": member, "start_utc": end - dt.timedelta(hours=window),
                     "end_utc": end, "value": 300.0 if end == hot else 280.0 + step / 100})
    return rows


def test_six_hour_tmax_is_bounded_not_exact_when_midnight_is_off_boundary():
    # Toronto midnight is 04Z (EDT) on 10-31 and 11-01 and 05Z (EST) on 11-02: 6 h windows end at 00/06/12/18Z, so
    # only 18 hours of each day are wholly inside; the windows crossing midnight close the rest.
    out = fd.local_day_summary(_tmax_run(_t(2026, 10, 31, 0), hot=_t(2026, 11, 1, 6)), TOR)
    d = out["2026-10-31"]
    assert (d["day_hours"], d["covered_hours"], d["spanned_hours"], d["edge_windows"]) == (24.0, 18.0, 24.0, 2)
    assert d["status"] == "bounded" and d["max_upper"] == 300.0 and d["max"] < 300.0
    d = out["2026-11-01"]  # 25 hours: edges 00-06Z and 11-02 00-06Z, inside 06Z..24Z
    assert (d["day_hours"], d["covered_hours"], d["spanned_hours"]) == (25.0, 18.0, 25.0)
    assert d["status"] == "bounded" and d["max_upper"] == 300.0
    d = out["2026-11-02"]  # the run ends at 11-03 00Z: 11-03 00Z..05Z is not covered
    assert (d["covered_hours"], d["spanned_hours"], d["status"], d["max_upper"]) == (18.0, 19.0, "partial", None)
    assert out["2026-10-30"]["status"] == "partial"


def test_three_hour_windows_on_a_boundary_day_are_exact():
    rows, t = [], _t(2026, 11, 1, 0)
    while t < _t(2026, 11, 4, 0):
        rows.append({"run_utc": "r", "start_utc": t, "end_utc": t + dt.timedelta(hours=3), "value": 290.0})
        t += dt.timedelta(hours=3)
    d = fd.local_day_summary(rows, "America/Chicago")["2026-11-02"]  # CST: midnight 06Z
    assert d["status"] == "exact" and d["covered_hours"] == d["day_hours"] == 24.0 and d["max_upper"] == 290.0


def test_mixed_runs_or_members_are_refused():
    a = _tmax_run(_t(2026, 10, 31, 0))
    with pytest.raises(ValueError, match="mixed series"):
        fd.local_day_summary(a + _tmax_run(_t(2026, 10, 31, 12)), TOR)
    with pytest.raises(ValueError, match="mixed series"):
        fd.local_day_summary(_tmax_run(_t(2026, 10, 31, 0), member=1) + _tmax_run(_t(2026, 10, 31, 0), member=2), TOR)


def test_duplicate_rows_never_inflate_coverage():
    rows = _tmax_run(_t(2026, 10, 31, 0))
    d = fd.local_day_summary(rows + rows, TOR)["2026-10-31"]
    assert d["covered_hours"] == 18.0 and d["spanned_hours"] == 24.0


def test_hourly_instants_need_every_local_hour_of_the_25_hour_day():
    start = _t(2026, 11, 1, 4)
    rows = [{"run_utc": "r", "start_utc": start + dt.timedelta(hours=h), "end_utc": start + dt.timedelta(hours=h),
             "value": 280.0 + h} for h in range(25)]
    d = fd.local_day_summary(rows, TOR)["2026-11-01"]
    assert (d["status"], d["instants"], d["max"], d["max_upper"]) == ("hourly", 25, 304.0, None)
    d = fd.local_day_summary(rows[:12] + rows[13:], TOR)["2026-11-01"]
    assert d["status"] == "partial" and d["instants"] == 24
    with pytest.raises(ValueError, match="mixed"):
        fd.local_day_summary(rows + [{"run_utc": "r", "start_utc": _t(2026, 11, 1, 6), "end_utc": _t(2026, 11, 1, 12),
                                      "value": 1.0}], TOR)


def test_eccc_daily_rows_summarise_each_run_and_member_separately():
    pts = []
    for run in (_t(2026, 10, 31, 0), _t(2026, 10, 31, 12)):
        for step in range(6, 73, 6):
            end = run + dt.timedelta(hours=step)
            for member in (0, 1):
                pts.append({"kind": "point", "model": "geps", "product": "tmax", "run_utc": run.isoformat(),
                            "step": step, "valid_utc": end.isoformat(), "window_h": 6, "member": member,
                            "market": "toronto", "icao": "CYYZ", "tz": TOR, "bilinear_k": 280.0 + member,
                            "nearest_k": 0.0})
    rows = daily.daily_rows(pts)
    by = {(r["run_utc"], r["member"], r["local_date"]): r for r in rows}
    assert len({(r["run_utc"], r["member"]) for r in rows}) == 4
    r = by[(_t(2026, 10, 31, 0).isoformat(), 1, "2026-11-01")]
    assert r["status"] == "bounded" and r["max"] == 281.0 and r["covered_hours"] == 18.0 and r["tz"] == TOR
    r = by[(_t(2026, 10, 31, 12).isoformat(), 0, "2026-11-02")]  # the 12Z run reaches 11-03 12Z
    assert r["status"] == "bounded" and r["day_hours"] == 24.0
