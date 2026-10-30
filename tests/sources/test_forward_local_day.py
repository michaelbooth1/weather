"""Lane L13 forward recorders: timezone-aware local-day bucketing across the 2026-11-01 DST change."""
from __future__ import annotations

import datetime as dt

import pytest

from tools.research import forward_local_day as ld

UTC = dt.timezone.utc


def _t(*a):
    return dt.datetime(*a, tzinfo=UTC)


def test_market_timezones_match_registry():
    from weather.market.market_registry import spec_for_id

    for market, tz in ld.MARKET_TZ.items():
        assert spec_for_id(market).timezone == tz, market


def test_day_bounds_across_fall_back():
    s, e = ld.local_day_bounds(dt.date(2026, 10, 31), "America/New_York")
    assert (s, e) == (_t(2026, 10, 31, 4), _t(2026, 11, 1, 4))
    s, e = ld.local_day_bounds(dt.date(2026, 11, 1), "America/New_York")
    assert (s, e) == (_t(2026, 11, 1, 4), _t(2026, 11, 2, 5))  # 25 hours
    s, e = ld.local_day_bounds(dt.date(2026, 11, 2), "America/Toronto")
    assert (s, e) == (_t(2026, 11, 2, 5), _t(2026, 11, 3, 5))
    s, e = ld.local_day_bounds(dt.date(2027, 3, 14), "America/Chicago")
    assert (e - s) == dt.timedelta(hours=23)


def test_window_assignment_and_midnight_edges():
    ny = "America/New_York"
    # 3 h windows ending 03Z/06Z: the 03-06Z window on 11-01 crosses local midnight (04Z EDT).
    assert ld.window_local_day(_t(2026, 11, 1, 0), _t(2026, 11, 1, 3), ny)[0] == dt.date(2026, 10, 31)
    assert ld.window_local_day(_t(2026, 11, 1, 3), _t(2026, 11, 1, 6), ny)[0] is None
    # On 11-02 local midnight is 05Z (EST): the 03-06Z window crosses it too, the 06-09Z window is inside 11-02.
    assert ld.window_local_day(_t(2026, 11, 2, 3), _t(2026, 11, 2, 6), ny)[0] is None
    assert ld.window_local_day(_t(2026, 11, 2, 6), _t(2026, 11, 2, 9), ny)[0] == dt.date(2026, 11, 2)
    # A window ending exactly at local midnight belongs to the day before; one starting at it, to the day after.
    assert ld.window_local_day(_t(2026, 11, 2, 2), _t(2026, 11, 2, 5), ny)[0] == dt.date(2026, 11, 1)
    assert ld.window_local_day(_t(2026, 11, 2, 5), _t(2026, 11, 2, 8), ny)[0] == dt.date(2026, 11, 2)
    # Instants: the repeated 01:00 local hour on 11-01 maps both UTC instants into 11-01.
    a = ld.window_local_day(_t(2026, 11, 1, 5), _t(2026, 11, 1, 5), ny)
    b = ld.window_local_day(_t(2026, 11, 1, 6), _t(2026, 11, 1, 6), ny)
    assert a[0] == b[0] == dt.date(2026, 11, 1) and a[1].hour == b[1].hour == 1 and a[1].utcoffset() != b[1].utcoffset()
    f = ld.local_fields(_t(2026, 11, 1, 3), _t(2026, 11, 1, 6), ny)
    assert f["local_date"] is None and f["straddles_local_midnight"] and f["window_end_local"].endswith("-05:00")
    with pytest.raises(ValueError):
        ld.window_local_day(dt.datetime(2026, 11, 1, 3), _t(2026, 11, 1, 6), ny)


def test_daily_max_hourly_covers_25_hour_day():
    rows = [{"start_utc": _t(2026, 11, 1, 4) + dt.timedelta(hours=h), "end_utc": _t(2026, 11, 1, 5) + dt.timedelta(hours=h),
             "value": 280.0 + h} for h in range(25)]
    d = ld.daily_max(rows, "America/New_York")["2026-11-01"]
    assert d["day_hours"] == 25.0 and d["covered_hours"] == 25.0 and d["max"] == 304.0 and d["edge_windows"] == 0


def test_daily_max_never_mixes_edge_windows():
    # 3 h windows every 3 h from 10-31 00Z to 11-03 00Z; a hot window crossing local midnight on 11-01.
    rows = []
    t = _t(2026, 10, 31, 0)
    while t < _t(2026, 11, 3, 0):
        hot = t == _t(2026, 11, 2, 3)
        rows.append({"start_utc": t, "end_utc": t + dt.timedelta(hours=3), "value": 320.0 if hot else 290.0})
        t += dt.timedelta(hours=3)
    out = ld.daily_max(rows, "America/New_York")
    assert out["2026-11-01"]["max"] == 290.0 and out["2026-11-01"]["edge_max"] == 320.0
    assert out["2026-11-02"]["max"] == 290.0 and out["2026-11-02"]["edge_max"] == 320.0
    # 11-01 (25 h, 04Z-05Z next day): inside windows 06Z..03Z = 21 h; edges 03-06Z on both ends.
    assert out["2026-11-01"]["covered_hours"] == 21.0 and out["2026-11-01"]["edge_windows"] == 2


def test_ens_daily_rows_flags_completeness():
    from tools.research import ecmwf_ens_daily as daily

    pts = []
    for step in range(3, 73, 3):
        valid = _t(2026, 11, 1, 0) + dt.timedelta(hours=step)
        for member in (1, 2):
            pts.append({"kind": "point", "param": "mx2t3", "run_utc": "2026-11-01T00:00:00+00:00", "step": step,
                        "valid_utc": valid.isoformat(), "window_h": 3, "member": member, "market": "toronto",
                        "icao": "CYYZ", "bilinear_k": 280.0 + member + (step == 18) * 5, "nearest_k": 0.0})
    rows = daily.daily_rows(pts)
    by = {(r["member"], r["local_date"]): r for r in rows}
    r = by[(1, "2026-11-01")]
    assert r["tz"] == "America/Toronto" and r["day_hours"] == 25.0 and r["tmax_k"] == 286.0 and not r["complete"]
    r = by[(2, "2026-11-02")]  # 11-02 05Z..11-03 05Z: inside windows 06Z..03Z = 21 h of 24, edges 03-06Z
    assert r["covered_hours"] == 21.0 and not r["complete"] and r["edge_windows"] == 2
