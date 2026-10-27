"""R0 OLS + floor dev fit (weather.calibration.r0_ols_floor_devfit; lane L3).

Guards: pre-declared L3 pick rule and blocked leave-one-year-out validation; train/serve feature parity of the floor.
"""
import json

import pandas as pd
import pytest

from tests.host_guard import import_or_skip_on_capture_host

devfit = import_or_skip_on_capture_host("weather.calibration.r0_ols_floor_devfit")


def _snaps(n_dates=40):
    rows = []
    for d in range(n_dates):
        date = f"2026-08-{d % 28 + 1:02d}" if d < 28 else f"2026-09-{d - 27:02d}"
        rows.append({"row_key": f"atlanta|s{d}", "market": "atlanta", "target_date": date, "local_hour": 9,
                     "cutoff_hour": "9", "v2_mean": 90.0 + d % 3, "v2_stddev": 2.0,
                     "v2_available_at": "2026-08-01T00:00:00Z", "captured_at_utc": "2026-08-01T13:00:00Z"})
    rows.append({"row_key": "atlanta|early", "market": "atlanta", "target_date": "2026-08-01", "local_hour": 3,
                 "cutoff_hour": "9", "v2_mean": 90.0, "v2_stddev": 2.0,
                 "v2_available_at": "2026-08-01T00:00:00Z", "captured_at_utc": "2026-08-01T07:00:00Z"})
    return pd.DataFrame(rows)


@pytest.fixture()
def features(tmp_path, monkeypatch):
    snaps = _snaps()
    path = tmp_path / "dev_features.jsonl"
    with open(path, "w", encoding="utf-8") as handle:
        for i, r in enumerate(snaps.itertuples()):
            handle.write(json.dumps({"market": "atlanta", "target_date": r.target_date, "hour": 9,
                                     "pit_forecast_high": 88.0 + i % 5, "high_so_far_l8": 80.0 + i % 4,
                                     "current_temp": 79.0}) + "\n")
    monkeypatch.setenv("L3_DEV_FEATURES", str(path))
    devfit._CACHE.clear()
    return snaps


def test_band_frame_sums_integer_mass_onto_bands():
    bands = pd.DataFrame({"row_key": ["k"] * 3, "band_index": [0, 1, 2], "kind": ["lte", "eq", "gte"],
                          "low": [None, 90, 92], "high": [89, 91, None]})
    out = devfit.band_frame({"k": {88: 0.2, 90: 0.3, 91: 0.1, 93: 0.4}}, bands)
    assert out.p.round(9).tolist() == [0.2, 0.4, 0.4]


def test_snapshot_before_its_cutoff_gets_no_record(features):
    recs = {k: r for k, _, _, r in devfit.snapshot_records(features, with_nbm=True)}
    assert recs["atlanta|early"] is None
    assert recs["atlanta|s0"]["nbm_mean"] == 90.0


def test_ols_devfit_fits_and_predicts_floored_mass(features):
    snaps = features
    labels = pd.DataFrame({"row_key": snaps.row_key, "settlement_bucket": [92 + i % 3 for i in range(len(snaps))]})
    state = devfit.fit_ols({"snapshots": snaps, "labels": labels}, with_nbm=True)
    assert ("atlanta", 9) in state["fits"] and state["features"][-1] == "nbm_mean"
    bands = pd.DataFrame({"row_key": ["atlanta|s1"] * 3, "band_index": [0, 1, 2], "kind": ["lte", "eq", "gte"],
                          "low": [None, 90, 92], "high": [89, 91, None]})
    out = devfit.predict_ols(state, snaps[snaps.row_key == "atlanta|s1"], bands)
    assert abs(out.p.sum() - 1.0) < 1e-9
