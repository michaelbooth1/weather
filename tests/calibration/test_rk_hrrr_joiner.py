"""Lane L2 rung R-K: the HRRR 13-16 hourly-path joiner (inputs only, no outcome join).

Guards: L2 R-K pre-registration (docs/research/l2-pooled-residual-2026-10-24/rungk/rule_rk.md) - one feature
family (k_max, k_gap, k_tcdc, k_miss), point-in-time cycle selection (availability + 10 min <= h:00), the
valid-time window [h:00, 17:00 local], message identity, Kelvin to Fahrenheit, and fail-closed missingness.
"""
import importlib
import json
import math

import pandas as pd
import pytest

try:
    prm = importlib.import_module("weather.calibration.pooled_residual_model")
except ImportError as exc:  # pragma: no cover - only on the capture host
    if "pooled_residual_model refuses" in str(exc):
        pytest.skip("research module refuses this host by design", allow_module_level=True)
    raise

MARKETS = ("toronto", "atlanta")
STATIONS = {"CYYZ": {"market": "toronto", "tz": "America/Toronto"},
            "KATL": {"market": "atlanta", "tz": "America/New_York"},
            "KXXX": {"market": "elsewhere", "tz": "UTC"}}


def _message(cycle, fh, var, values, key=None, record=None):
    from datetime import datetime

    c = datetime.fromisoformat(cycle)
    prefix = prm.RK_VARIABLES[var]
    return {"cycle_utc": cycle, "fh": fh, "key": key or prm.rk_message_key(c, fh),
            "idx_record": record or f"{prefix}:{fh} hour fcst:",
            "points": {icao: {"nearest": v, "block3x3": [v] * 9} for icao, v in values.items()}}


def _selection(station, day, hour, snapshot, cycle, fhs, latest):
    return {"station": station, "local_date": day, "hour_local": hour, "snapshot_utc": snapshot,
            "cycle_utc": cycle, "fhs": fhs, "latest_available_utc": latest, "depth": 2,
            "window_truncated_at_f18": False if cycle else None}


def _corpus(tmp_path, selections, messages, torn_tail=True):
    (tmp_path / "stations.json").write_text(json.dumps(STATIONS), encoding="utf-8")
    with open(tmp_path / "selections.jsonl", "w", encoding="utf-8") as w:
        for s in selections:
            w.write(json.dumps(s) + "\n")
    with open(tmp_path / "manifest.jsonl", "w", encoding="utf-8") as w:
        for m in messages:
            w.write(json.dumps(m) + "\n")
        if torn_tail:
            w.write('{"cycle_utc": "2023-08-01T16:00')  # a corpus still being appended
    return tmp_path


C = "2023-08-01T15:00:00+00:00"  # 11:00 EDT cycle; 13:00 EDT snapshot is 17:00 UTC
SNAP13 = "2023-08-01T17:00:00+00:00"
OK_LATEST = "2023-08-01T16:45:00+00:00"  # + 10 min <= 17:00


def _good_messages():
    msgs = []
    for fh, k, cloud in ((2, 300.0, 20.0), (3, 301.0, 40.0), (4, 302.0, 60.0), (5, 301.5, 80.0), (6, 300.5, 0.0)):
        msgs.append(_message(C, fh, "TMP", {"CYYZ": k - 5.0, "KATL": k, "KXXX": 1.0}))
        msgs.append(_message(C, fh, "TCDC", {"CYYZ": cloud, "KATL": cloud}))
    msgs.append({"cycle_utc": C, "fh": 2, "key": prm.rk_message_key(pd.Timestamp(C).to_pydatetime(), 2),
                 "idx_record": "DPT:2 m above ground:2 hour fcst:", "points": {}})
    return msgs


def test_rk_joiner_builds_the_path_columns_in_fahrenheit_and_counts_a_torn_line(tmp_path):
    sel = [_selection("KATL", "2023-08-01", 13, SNAP13, C, [2, 3, 4, 5, 6], OK_LATEST),
           _selection("CYYZ", "2023-08-01", 13, SNAP13, C, [2, 3, 4, 5, 6], OK_LATEST),
           _selection("KXXX", "2023-08-01", 13, SNAP13, C, [2], OK_LATEST)]
    hrrr, stats = prm.rk_hrrr_columns(_corpus(tmp_path, sel, _good_messages()), MARKETS)
    assert set(hrrr) == {("atlanta", "2023-08-01", 13), ("toronto", "2023-08-01", 13)}
    atl = hrrr[("atlanta", "2023-08-01", 13)]
    assert atl["k_miss"] == 0.0
    assert atl["k_max"] == pytest.approx((302.0 - 273.15) * 9 / 5 + 32)
    assert atl["k_tcdc"] == pytest.approx(40.0)
    assert stats["manifest_corrupt_line"] == 1 and stats["manifest_other_variable"] == 1
    cols = prm.rk_columns(atl, 80.0)
    assert cols["k_gap"] == pytest.approx(atl["k_max"] - 80.0) and cols["k_miss"] == 0.0
    assert math.isnan(prm.rk_columns(atl, float("nan"))["k_gap"])


def test_rk_joiner_fails_closed_on_pit_window_identity_and_absent_messages(tmp_path):
    late = "2023-08-01T16:55:00+00:00"  # + 10 min > 17:00 snapshot
    sel = [_selection("KATL", "2023-08-01", 13, SNAP13, C, [2, 3], late),                  # PIT violation
           _selection("KATL", "2023-08-01", 14, "2023-08-01T18:00:00+00:00", C, [2, 3], OK_LATEST),  # valid < t
           _selection("KATL", "2023-08-01", 15, "2023-08-01T19:00:00+00:00", C, [4, 5, 6], OK_LATEST),  # absent
           _selection("KATL", "2023-08-01", 16, "2023-08-01T20:00:00+00:00", None, [], None),   # no cycle
           _selection("CYYZ", "2023-08-01", 13, SNAP13, C, [2, 3], OK_LATEST)]                  # mismatched key
    msgs = _good_messages()
    for m in msgs:
        if m["fh"] == 3 and m["idx_record"].startswith("TMP"):
            m["key"] = "hrrr.20230801/conus/hrrr.t15z.wrfsfcf04.grib2"
        if m["fh"] == 6 and m["idx_record"].startswith("TCDC"):
            del m["points"]["KATL"]
    hrrr, stats = prm.rk_hrrr_columns(_corpus(tmp_path, sel, msgs, torn_tail=False), MARKETS)
    reasons = {k: v["reason"] for k, v in hrrr.items()}
    assert reasons == {("atlanta", "2023-08-01", 13): "pit_violation",
                       ("atlanta", "2023-08-01", 14): "window_violation",
                       ("atlanta", "2023-08-01", 15): "message_absent",
                       ("atlanta", "2023-08-01", 16): "no_cycle",
                       ("toronto", "2023-08-01", 13): "identity_mismatch"}
    assert all(v["k_miss"] == 1.0 and math.isnan(v["k_max"]) for v in hrrr.values())
    assert stats["manifest_identity_mismatch"] == 1 and stats["selection_identity_mismatch_used"] == 1
    gate = prm.rk_parity_training(stats, {"rows": 1, "rows_covered": 1})
    assert not gate["pass"] and not gate["checks"]["pit_violation"] and not gate["checks"]["identity_mismatch_used"]


def test_rk_training_columns_key_on_market_date_hour_and_mark_missing_rows(tmp_path):
    sel = [_selection("KATL", "2023-08-01", 13, SNAP13, C, [2, 3, 4, 5, 6], OK_LATEST)]
    hrrr, _ = prm.rk_hrrr_columns(_corpus(tmp_path, sel, _good_messages()), MARKETS)
    frame = pd.DataFrame({"market": ["atlanta", "atlanta", "toronto"],
                          "target_date": ["2023-08-01", "2023-08-02", "2023-08-01"],
                          "hour": [13, 13, 13], "fh": [81.0, 81.0, 75.0]})
    out, stats = prm.rk_training_columns(frame, hrrr)
    assert list(out["k_miss"]) == [0.0, 1.0, 1.0]
    assert out.at[0, "k_gap"] == pytest.approx(out.at[0, "k_max"] - 81.0)
    assert stats == {"rows": 3, "rows_no_selection": 2, "rows_covered": 1}
    assert set(prm.RK_ARMS["B_H"]["extra_ols"]) | set(prm.RK_ARMS["P3d_H"]["extra_hgb"]) == set(prm.RK_FEATURES)


def test_rk_control_requires_identical_keys_and_incumbent_scores():
    row = {"hour": 13, "year": 2021, "market": "nyc", "date": "2021-08-01", "B_N_brier": 0.5, "B_N_log": 1.0,
           "P3d_N_fix_brier": 0.4, "P3d_N_fix_log": 0.9}
    assert prm.rk_control([row], [row, {**row, "hour": 9}])["pass"]
    assert not prm.rk_control([{**row, "B_N_brier": 0.5 + 1e-9}], [row])["pass"]
    assert not prm.rk_control([row], [row, {**row, "date": "2021-08-02"}])["pass"]
