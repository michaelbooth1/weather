"""R-ODC serve-side low_so_far / dewpoint_c from captured METAR (``odc_metar_features``): synthetic rows only."""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from weather.calibration import odc_metar_features as odc
from weather.calibration.mg2_p3d_n import as_of_capture
from weather.model.mg_serve_core import wu_whole_f
from weather.model.observed_running_max import running_max_since_midnight

TZ = ZoneInfo("America/New_York")
D = date(2026, 8, 5)


def _f(c):
    return 32.0 + 9.0 * c / 5.0  # a T-group value in F


def _row(utc_hhmm, c, dew_c=None, day=5, report_day=None):
    hh, mm = utc_hhmm.split(":")
    report = f"2026-08-{report_day or day:02d}T{hh}:00:00Z"
    row = {"raw": f"KATL {day:02d}{hh}{mm}Z 00000KT 10SM CLR", "report_time": report, "temp_native": _f(c)}
    if dew_c is not None:
        row["dewpoint_native"] = _f(dew_c)
    return row


def _now(local_hhmm, day=5):
    hh, mm = local_hhmm.split(":")
    return datetime(2026, 8, day, int(hh), int(mm), tzinfo=TZ)


# EDT = UTC-4: 10:52Z is 06:52 local
ROWS = [
    _row("03:52", 30.0, 20.0, day=5),        # 23:52 on 08-04 local: previous day
    _row("04:52", 26.0, 21.0),               # 00:52
    _row("08:52", 22.6, 19.4),               # 04:52, the minimum
    _row("10:52", 23.3, 20.2),               # 06:52
    _row("11:00", 24.0, None),               # 07:00 exactly: in the h07 window, no dewpoint
    _row("11:01", 10.0, 5.0),                # 07:01: after h07:00
    {"temp_native": 5.0, "local_time": "05:00"},  # undated: never placed by wall clock
]


def test_window_minimum_and_latest_dewpoint():
    out = odc.odc_features({"rows": ROWS}, target_date=D, tz=TZ, unit="F", cutoff_hour=7, now=_now("07:40"))
    assert out["low_so_far"] == wu_whole_f(_f(22.6), "half_up") == 73
    assert out["dewpoint_c"] is None  # the latest kept row (07:00) has none: no earlier-row fallback
    assert out["n_rows"] == 4 and out["reason"] is None
    assert out["skipped"] == {"undated": 1, "other_date": 1, "after_cutoff": 1, "after_capture": 0}


def test_look_ahead_rows_after_capture_or_cutoff_never_enter():
    early = odc.odc_features({"rows": ROWS}, target_date=D, tz=TZ, unit="F", cutoff_hour=7, now=_now("05:00"))
    assert early["n_rows"] == 2 and early["low_so_far"] == 73  # 06:52 and 07:00 not yet captured
    assert early["dewpoint_c"] == wu_whole_f(_f(19.4), "half_up")
    assert early["skipped"]["after_capture"] == 2
    late = odc.odc_features({"rows": ROWS}, target_date=D, tz=TZ, unit="F", cutoff_hour=8, now=_now("08:30"))
    assert late["low_so_far"] == wu_whole_f(_f(10.0), "half_up") == 50  # 07:01 is inside h08


def test_obs_time_from_raw_payload_wins_over_the_raw_group():
    row = _row("10:52", 15.0, 12.0)
    payload = [{"rawOb": row["raw"], "obsTime": datetime(2026, 8, 5, 12, 30, tzinfo=timezone.utc).timestamp()}]
    out = odc.odc_features({"rows": [row], "raw_payload": payload}, target_date=D, tz=TZ, unit="F", cutoff_hour=8,
                           now=_now("09:00"))
    assert out["n_rows"] == 0 and out["reason"] == "no_metar_row"  # obsTime 08:30 local is after h08:00


def test_no_row_and_naive_now_refuse_or_flag():
    out = odc.odc_features({}, target_date=D, tz=TZ, unit="F", cutoff_hour=7, now=_now("07:30"))
    assert out["low_so_far"] is None and out["dewpoint_c"] is None and out["reason"] == "no_metar_row"
    with pytest.raises(odc.OdcMetarRefused, match="timezone-aware"):
        odc.odc_features({"rows": ROWS}, target_date=D, tz=TZ, unit="F", cutoff_hour=7, now=datetime(2026, 8, 5, 7))


def test_metar_only_no_station_fallback_argument_exists():
    import inspect

    assert "station" not in inspect.signature(odc.odc_features).parameters


def test_kept_set_matches_the_served_high_so_far_row_set():
    for hour in (5, 7, 8, 12):
        rows, _ = odc.kept_rows({"rows": ROWS[:-1]}, target_date=D, tz=TZ, unit="F", cutoff_hour=hour,
                                now=_now("12:30"))
        high, _ = running_max_since_midnight({}, {"rows": ROWS[:-1]}, target_date=D, tz=TZ, unit="F",
                                             cutoff_hour=hour, now=_now("12:30"), metar_only=True)
        assert max(r[2] for r in rows) == high


def test_choose_snapshot_rules_match_mg2_p3d_n():
    caps = [_now(t) for t in ("06:58", "07:05", "07:40", "07:20", "08:10")] + [_now("07:30", day=6)]
    assert odc.choose_snapshot(caps, target_date=D, tz=TZ, cutoff_hour=7, rule="last_in_hour") == 3  # file order
    assert odc.choose_snapshot(caps, target_date=D, tz=TZ, cutoff_hour=7, rule="receipt_by", grace_minutes=10) == 1
    assert odc.choose_snapshot(caps, target_date=D, tz=TZ, cutoff_hour=9, rule="last_in_hour") is None
    index = [(c, i, 0) for i, c in enumerate(caps) if c.date() == D]
    for at in (_now("07:00"), _now("07:35"), _now("09:00"), _now("06:00")):
        got = odc.choose_snapshot(caps, target_date=D, tz=TZ, cutoff_hour=7, rule="as_of_capture", at_local=at)
        ref = as_of_capture(index, at)
        assert got == (None if ref is None else ref[1])
    with pytest.raises(odc.OdcMetarRefused):
        odc.choose_snapshot(caps, target_date=D, tz=TZ, cutoff_hour=7, rule="nearest")


def test_check_bounds_refuses_each_violation():
    good = {7: {"low_so_far": 70, "high_so_far": 75, "current_temp": 71}, 8: {"low_so_far": 70, "high_so_far": 76}}
    assert odc.check_bounds(good) == 2
    for bad in ({7: {"low_so_far": 70}, 8: {"low_so_far": 71}},
                {7: {"low_so_far": 76, "high_so_far": 75}},
                {7: {"low_so_far": 72, "current_temp": 71}}):
        with pytest.raises(odc.OdcMetarRefused, match="bound violations"):
            odc.check_bounds(bad)


def test_half_up_on_the_tgroup_grid():
    # 21.5 C -> 70.7 F -> 71; a 0.5 F tie (e.g. 26.5 C = 79.7 -> 80) rounds up
    out = odc.odc_features({"rows": [_row("10:00", 21.5, -3.0)]}, target_date=D, tz=TZ, unit="F", cutoff_hour=7,
                           now=_now("07:10"))
    assert out["low_so_far"] == 71 and out["dewpoint_c"] == wu_whole_f(_f(-3.0), "half_up") == 27
