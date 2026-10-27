"""Free-source screen candidates (lane G): point-in-time running max, serve-product degradation, pmf.

Guards: owner direction 2026-10-23 (lane G) that a source counts only if available point in time at
serve; EF 10q t3-r3 (floor + remaining rise) as the F1 control; train/serve parity of the F1 table.
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from weather.reporting.scorecards.free_source_candidates import remaining_rise as rr
from weather.sources.free_screens import common, iem_onemin


def _obs(rows):
    frame = pd.DataFrame(rows, columns=["station", "local_date", "available_utc", "temp_f"])
    frame["available_utc"] = pd.to_datetime(frame.available_utc, utc=True)
    return frame


def test_running_max_uses_only_rows_available_at_the_query_time():
    obs = _obs([("KX", "2026-08-01", "2026-08-01T15:10Z", 80.0), ("KX", "2026-08-01", "2026-08-01T16:10Z", 84.0),
                ("KX", "2026-08-01", "2026-08-01T17:10Z", 82.0), ("KX", "2026-08-02", "2026-08-02T15:00Z", 99.0)])
    q = pd.DataFrame({"qid": [0, 1, 2, 3, 4], "station": "KX",
                      "local_date": ["2026-08-01"] * 4 + ["2026-08-02"],
                      "t": pd.to_datetime(["2026-08-01T15:09:00.000Z", "2026-08-01T16:09:59.000Z", "2026-08-01T16:10:00.000Z",
                                           "2026-08-01T23:00:00.000Z", "2026-08-02T14:59:00.000Z"], utc=True)})
    out = rr.running_max_asof(obs, q).to_numpy()
    assert np.isnan(out[0]) and out[1] == 80.0 and out[2] == 84.0 and out[3] == 84.0 and np.isnan(out[4])


def test_hf_series_degrades_cadence_resolution_and_latency():
    onemin = pd.DataFrame({"icao": "KX", "valid_utc": pd.to_datetime(
        ["2026-08-01T18:00Z", "2026-08-01T18:01Z", "2026-08-01T18:05Z"], utc=True), "tmpf": [85.0, 99.0, 86.0]})
    hf = rr.hf_series(onemin, {"KX": "America/New_York"}, rr.HF5C)
    assert list(hf.temp_f) == [84.0, 86.0]          # 85 F = 29.4 C -> 29 C -> 84 F; 86 F = 30 C -> 86 F
    assert hf.available_utc.iloc[0] == pd.Timestamp("2026-08-01T18:10Z")
    assert list(hf.local_date) == ["2026-08-01", "2026-08-01"]
    raw = rr.hf_series(onemin, {"KX": "America/New_York"}, rr.M1F)
    assert list(raw.temp_f) == [85.0, 99.0, 86.0] and raw.available_utc.iloc[0] == pd.Timestamp("2026-08-01T18:02Z")


def test_hf_series_refuses_rows_after_the_development_window():
    onemin = pd.DataFrame({"icao": "KX", "valid_utc": pd.to_datetime(["2026-09-30T12:00Z"], utc=True),
                           "tmpf": [70.0]})
    with pytest.raises(AssertionError, match="after 2026-09-29"):
        rr.hf_series(onemin, {"KX": "America/New_York"}, rr.M1F)


def _snap_inputs(captured):
    snaps = pd.DataFrame({"row_key": ["a"], "station": ["KX"], "date": ["2026-08-01"], "local_hour": [14],
                          "captured_at_utc": [captured]})
    bands = pd.DataFrame({"row_key": "a", "band_index": [0, 1, 2], "kind": ["lte", "eq", "gte"],
                          "low": [0, 84, 86], "high": [83, 85, 0]})
    return snaps, bands


def test_pmf_mass_below_the_metar_running_max_is_folded_onto_it():
    metar = _obs([("KX", "2026-08-01", "2026-08-01T17:00Z", 84.0)])
    table = {("KX", 8, 14): (-3, np.array([0.25, 0.25, 0.25, 0.25]), 60)}   # e in {-3..0}
    snaps, bands = _snap_inputs("2026-08-01T18:00Z")
    hf = _obs([("KX", "2026-08-01", "2026-08-01T17:30Z", 86.0)])
    out = rr.predict_frame(table, snaps, bands, metar, hf)
    # R* = 86, values 83..86; 83 is below R = 84 and folds onto 84
    assert out.p.tolist() == pytest.approx([0.0, 0.75, 0.25])
    control = rr.predict_frame(table, snaps, bands, metar, None)
    assert control.p.tolist() == pytest.approx([0.0, 1.0, 0.0])          # R = 84, all of 81..84 folds to 84


def test_no_metar_row_yet_means_no_prediction_so_served_falls_back():
    metar = _obs([("KX", "2026-08-01", "2026-08-01T19:00Z", 84.0)])
    table = {("KX", 8, 14): (0, np.array([1.0]), 60)}
    snaps, bands = _snap_inputs("2026-08-01T18:00Z")
    hf = _obs([("KX", "2026-08-01", "2026-08-01T17:30Z", 86.0)])
    assert rr.predict_frame(table, snaps, bands, metar, hf).empty


def test_history_table_uses_the_same_fresh_high_definition_as_serve():
    days, metar_rows, hf_rows = [], [], []
    for k in range(rr.MIN_CELL_N):
        day = f"2025-08-{k + 1:02d}"
        for hour in range(24):                       # 24 routine rows, the 14 h row is the day's max 90 F
            temp = 90.0 if hour == 14 else 70.0
            metar_rows.append(("KX", day, f"{day}T{hour:02d}:10Z", temp))
        hf_rows.append(("KX", day, f"{day}T13:20Z", 88.0))   # fresh high at 13:20 UTC
    metar, hf = _obs(metar_rows), _obs(hf_rows)
    tz = {"KX": "UTC"}
    t_hf = rr.fit_table(metar, tz, hf)
    t_ctl = rr.fit_table(metar, tz, None)
    base, pmf, n = t_hf[("KX", 8, 13)]              # at 13:30 R = 70 (METAR), R* = 88 -> e* = 2
    assert n == rr.MIN_CELL_N and base + int(np.argmax(pmf)) == 2
    base, pmf, _ = t_ctl[("KX", 8, 13)]
    assert base + int(np.argmax(pmf)) == 20
    assert ("KX", 8, 13) in t_hf and rr.table_digest(t_hf) != rr.table_digest(t_ctl)


def test_requests_end_at_local_midnight_closing_the_last_development_day():
    end = common.local_day_end_utc("America/New_York")
    assert end == datetime(2026, 9, 30, 4, 0, tzinfo=timezone.utc)
    wins = common.month_windows(datetime(2026, 8, 15, tzinfo=timezone.utc), end)
    assert wins[0] == (datetime(2026, 8, 15, tzinfo=timezone.utc), datetime(2026, 9, 1, tzinfo=timezone.utc))
    assert wins[-1][1] == end
    plan = iem_onemin.requests_plan(datetime(2026, 9, 1, tzinfo=timezone.utc))
    assert {p[0].icao for p in plan} >= {"KATL", "KBKF", "KDEN", "KSEA"}
    assert all(p[2] <= common.local_day_end_utc(p[0].timezone) for p in plan)


def test_iem_csv_parser_drops_missing_values():
    text = ("station,station_name,valid(UTC),tmpf\nATL,X,2026-08-01 00:00,84\nATL,X,2026-08-01 00:01,M\n"
            "ATL,X,2026-08-01 00:02,\n")
    assert iem_onemin.parse_csv(text) == [("KATL", "2026-08-01 00:00", 84.0)]


def test_us_stations_match_the_market_registry():
    icaos = {s.icao for s in common.us_stations()}
    assert len(icaos) == 11 and "CYYZ" not in icaos and "KBKF" in icaos


def test_l4_blend_fits_bias_and_inverse_mse_weights_from_training_labels(monkeypatch):
    from weather.reporting.scorecards.free_source_candidates import l4_blend_candidate as l4

    days = [f"2026-08-{d:02d}" for d in range(1, 31)]
    table = pd.DataFrame({("gfs_seamless"): [92.0] * 30, "ecmwf_ifs025": [np.nan] * 30, "icon_seamless": [np.nan] * 30},
                         index=pd.MultiIndex.from_arrays([["KX"] * 30, days], names=["station", "local_date"]))
    monkeypatch.setitem(l4._CACHE, "day1", (table, "sha"))
    snaps = pd.DataFrame({"row_key": [f"k{d}" for d in days], "station": "KX", "date": days, "local_hour": 8,
                          "captured_at_utc": [f"{d}T12:00:00+00:00" for d in days],
                          "v2_available_at": [f"{d}T11:00:00+00:00" for d in days],
                          "v2_mean": [88.0 if i % 2 else 92.0 for i in range(30)], "v2_stddev": 2.0, "floor": np.nan})
    bands = pd.DataFrame({"row_key": np.repeat(snaps.row_key, 3).to_numpy(), "band_index": [0, 1, 2] * 30,
                          "kind": ["lte", "eq", "gte"] * 30, "low": [0, 89, 91] * 30, "high": [88, 90, 0] * 30})
    labels = pd.DataFrame({"row_key": snaps.row_key, "winner": 1})          # centre 89.5
    state = l4.fit({"snapshots": snaps, "bands": bands, "labels": labels})
    assert state["bias"][("KX", "gfs_seamless")] == pytest.approx(2.5)        # 92 - 89.5
    assert state["bias"][("KX", "nbm_v2_mean")] == pytest.approx(0.5)
    w = state["weights"][("KX", 8)]
    assert set(w) == {"nbm_v2_mean", "gfs_seamless"} and w["gfs_seamless"] > w["nbm_v2_mean"]   # GFS error 0 after bias
    out = l4.predict(state, snaps.iloc[:1], bands.iloc[:3])
    assert out.p.sum() == pytest.approx(1.0) and out.p.iloc[1] > 0.3
