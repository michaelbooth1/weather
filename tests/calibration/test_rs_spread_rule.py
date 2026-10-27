"""Lane L2 rung R-S: NBM's own spread as a scale-model input only (inputs and synthetic fits, no outcome join).

Guards: the R-S pre-registration (rule_rs.md sha 5fb593f4...) - the two columns enter the scale HGB only, so the
mean predictions equal the base arm's exactly (control C-mean); base arms keep their old fit path; G-s is s_new /
s_old on the same OOF errors; training columns come from the cycle nbm_at_cutoff selects; gate 1b matches the
captured v2 spread to the dev NBP row of the captured cycle; the floor / 2% climatology code is pinned.
"""
import hashlib
import importlib
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

try:
    prm = importlib.import_module("weather.calibration.pooled_residual_model")
except ImportError as exc:  # pragma: no cover - only on the capture host
    if "pooled_residual_model refuses" in str(exc):
        pytest.skip("research module refuses this host by design", allow_module_level=True)
    raise

RULE = Path(__file__).resolve().parents[2] / "docs/research/l2-pooled-residual-2026-10-24/rungs/rule_rs.md"


def _frame(n_days=14, years=(2021, 2022, 2023, 2024), markets=("atlanta", "nyc"), hour=10, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for market in markets:
        for year in years:
            for d in range(n_days):
                sd = float(rng.integers(1, 6))
                fh = 70.0 + rng.normal(0, 4)
                y = round(fh + rng.normal(0, sd))
                F = y - abs(round(rng.normal(0, 2)))
                rows.append({
                    "market": market, "centre": prm.VALIDATION_CENTRE, "season": "aug_sep", "hour": hour,
                    "target_date": f"{year}-08-{1 + d:02d}", "year": year, "y": float(y), "F": float(F), "fh": fh,
                    "lat": 33.6, "lon": -84.4, "elev": 300.0, "doy_sin": 0.0, "doy_cos": 1.0,
                    "market_code": float(prm.R0_MARKETS.index(market)), "nbm_sd": sd, "nbm_qw": 2.5 * sd,
                })
    return pd.DataFrame(rows)


def test_rule_sha_is_recorded_in_code():
    assert hashlib.sha256(RULE.read_bytes()).hexdigest() == prm.RS_RULE_SHA256


def test_pinned_floor_and_climatology_code_is_byte_identical():
    got = prm.rs_pinned_check()
    assert got["predictive_distribution_sha256"] == prm.RS_PD_SHA256
    assert got["FLOOR_MIX_CLIM"] == 0.02 and got["MIN_SCALE"] == 0.5


def test_extra_scale_leaves_the_mean_model_untouched_and_reports_gs():
    frame = _frame()
    base = prm.fit_pooled(frame, market_id=False, doy=True, raw_columns=False)
    spread = prm.fit_pooled(frame, market_id=False, doy=True, raw_columns=False, extra_scale=prm.RS_COLUMNS)
    a, Xa = base["mean"].predict(frame)
    b, Xb = spread["mean"].predict(frame)
    assert np.array_equal(a, b) and np.array_equal(Xa, Xb)  # control C-mean
    assert "gs_ratio" not in base and len(spread["gs_ratio"]) == len(frame)
    gap = np.nan_to_num(a - frame["F"].to_numpy(float), nan=0.0)
    assert prm._scale_input(base, Xa, gap, frame).shape[1] == Xa.shape[1] + 1
    assert prm._scale_input(spread, Xa, gap, frame).shape[1] == Xa.shape[1] + 3
    # s_old inside the S fit is the base arm's own training scale: s_new / s_old * z_new == z_old
    assert np.allclose(spread["z"] * spread["gs_ratio"], base["z"], equal_nan=True)
    assert np.all(spread["gs_ratio"] > 0)
    with pytest.raises(prm.PooledModelError):
        prm.fit_pooled(frame, market_id=False, doy=True, raw_columns=False, simple=True, extra_scale=prm.RS_COLUMNS)


def test_rung_loyo_records_c_mean_and_keeps_base_scores():
    frame = _frame(n_days=31, years=(2021, 2022, 2023, 2024))  # enough rows for min_samples_leaf 40 splits
    buckets = {m: list(range(40, 110)) for m in ("atlanta", "nyc")}
    arms = {"P3d_N_fix": False, "P3d_N_fix_S": prm.RS_S_SPEC}
    out = {}
    rows = prm.rung_loyo(frame, buckets, (10,), arms=arms, mean_pairs={"P3d_N_fix_S": "P3d_N_fix"}, mean_out=out)
    plain = prm.rung_loyo(frame, buckets, (10,), arms={"P3d_N_fix": False})
    assert out == {"P3d_N_fix_S": 0.0}
    assert [r["P3d_N_fix_brier"] for r in rows] == [r["P3d_N_fix_brier"] for r in plain]
    assert any(r["P3d_N_fix_S_brier"] != r["P3d_N_fix_brier"] for r in rows)


def test_arm_spec_is_four_wide_and_base_specs_unchanged():
    assert prm._arm_spec(False) == (False, (), (), ())
    assert prm._arm_spec(prm.RK_ARMS["P3d_H"])[3] == ()
    assert prm._arm_spec(prm.RS_WINDOWS["07-12"]["arms"]["P3d_H_S"])[2:] == (("k_max", "k_gap", "k_tcdc"),
                                                                             prm.RS_COLUMNS)
    for cfg in prm.RS_WINDOWS.values():
        s_arm, base = cfg["primary"]
        assert cfg["pairs"][s_arm] == base and base in cfg["control_arms"]


def test_training_columns_follow_the_selected_cycle():
    frame = pd.DataFrame({"market": ["atlanta", "atlanta"], "target_date": ["2021-08-01", "2021-08-02"],
                          "hour": [9, 9]})
    spread = {("atlanta", "2021-08-01", "01"): (2.0, 80.0, 86.0), ("atlanta", "2021-08-01", "07"): (3.0, 79.0, 88.0)}

    def at_cutoff(table, market, day, hour, tz):
        return (85.0, "01") if day == "2021-08-01" else (None, None)

    out, stats = prm.rs_training_columns(frame, {}, spread, at_cutoff, {"atlanta": "America/New_York"})
    assert out["nbm_sd"].iloc[0] == 2.0 and out["nbm_qw"].iloc[0] == 6.0
    assert math.isnan(out["nbm_sd"].iloc[1])
    assert stats["anchor_rows"] == 1 and stats["no_anchor"] == 1
    assert out["nbm_version"].iloc[0] is None  # a 3-wide spread entry carries no version
    gate = prm.rs_parity_training(stats)
    assert gate["pass"]
    assert not prm.rs_parity_training({"anchor_rows": 100, "sd_present": 94, "qw_present": 100})["pass"]
    assert not prm.rs_parity_training({"anchor_rows": 1, "sd_present": 1, "qw_present": 1,
                                       "qw_out_of_range": 1})["pass"]


def test_cycle_key_parse():
    assert prm._rs_cycle("nbm-nbp:20260801T01Z") == "2026-08-01T01"
    assert prm._rs_cycle(None) is None and prm._rs_cycle("nbm-x:1") is None


def test_dev_parity_matches_the_captured_cycle(tmp_path, monkeypatch):
    pytest.importorskip("weather.calibration.r0_ols_floor_devfit")
    corpus = tmp_path / "corpus.jsonl"
    rows = [{"available": True, "mean": 90.0, "market_id": "atlanta", "target_date": "2026-08-01",
             "issued_at": "2026-08-01T01:00:00+00:00", "cycle": "01", "sd": 3.0, "p10": 83.0, "p90": 91.0},
            {"available": True, "mean": 90.0, "market_id": "atlanta", "target_date": "2026-08-01",
             "issued_at": "2026-08-01T07:00:00+00:00", "cycle": "07", "sd": 4.0, "p10": 82.0, "p90": 92.0}]
    corpus.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    monkeypatch.setattr(prm, "RS_DEV_CORPUS_SHA256", hashlib.sha256(corpus.read_bytes()).hexdigest())
    cap = datetime(2026, 8, 1, 13, 0, tzinfo=timezone.utc).isoformat()
    snaps = pd.DataFrame({
        "market": ["atlanta"] * 3, "target_date": ["2026-08-01"] * 3, "local_hour": [9, 9, 9],
        "cutoff_hour": ["9", "9", "9"], "v2_mean": [90.0] * 3, "v2_stddev": [3.0, 4.0, 3.0],
        "v2_available_at": [cap] * 3, "captured_at_utc": [cap] * 3, "v2_p10": [83.0, 82.0, 83.0],
        "v2_p90": [91.0, 92.0, 90.0],
        "v2_cycle_key": ["nbm-nbp:20260801T01Z", "nbm-nbp:20260801T07Z", "nbm-nbp:20260801T01Z"]})
    snaps.to_parquet(tmp_path / "inputs_snapshots.parquet")
    gate = prm.rs_parity_dev(tmp_path, corpus, (9,), markets=("atlanta",))
    assert gate["rows"] == 3
    assert gate["share"]["sd"] == 1.0 and gate["share"]["p10"] == 1.0
    assert gate["share"]["p90"] == pytest.approx(2 / 3)
    assert not gate["pass"]
    assert date.fromisoformat("2026-08-01") <= prm.N_DEV_LAST


def test_era_guard_reports_versions_and_stops_outside_the_band():
    frame = pd.DataFrame({"year": [2021, 2021, 2025, 2025, 2025], "hour": [13, 14, 13, 14, 14],
                          "nbm_version": ["4.0", "4.0", "4.3", "4.3", None],
                          "nbm_sd": [2.0, 2.0, 3.0, 3.0, float("nan")], "nbm_qw": [6.0, 6.0, 8.0, 8.0, float("nan")]})
    dev = pd.DataFrame({"cutoff_hour": ["13", "14"], "v2_stddev": [2.5, 2.5], "v2_p10": [80.0, 80.0],
                        "v2_p90": [87.0, 87.0]})
    gv = prm.rs_era_guard(frame, dev, "13-16")
    sd = gv["columns"]["nbm_sd"]
    assert sd["cells"]["train_all"]["n"] == 4 and sd["cells"]["train_2021_v4.0"]["median"] == 2.0
    assert sd["ratio_dev_over_train_median"] == pytest.approx(1.0) and gv["pass"]
    assert gv["addendum1_sha256"] == prm.RS_ADDENDUM1_SHA256
    shifted = dev.assign(v2_stddev=[1.0, 1.0])  # median 1.0 / 2.5 = 0.4 -> stop
    assert not prm.rs_era_guard(frame, shifted, "13-16")["pass"]


def test_addendum_sha_is_recorded_in_code():
    path = RULE.with_name("rule_rs_addendum1.md")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == prm.RS_ADDENDUM1_SHA256
