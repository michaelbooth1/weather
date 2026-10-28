"""Lane L8 research module: fail-closed import, dev-date guard, MG-1 rule, derived-feature check, verdict.

Guards: lane L8 pre-registration docs/research/high-so-far-parity-shadow-2026-10-24/rule.md (dev dates <=
2026-09-29, MG-1 rule, research-only import).
"""
import json

import numpy as np
import pandas as pd
import pytest

from tests.host_guard import import_or_skip_on_capture_host

hs = import_or_skip_on_capture_host("weather.calibration.high_so_far_parity_shadow")


def test_import_refuses_on_the_capture_host_or_when_unprovable():
    with pytest.raises(ImportError, match="capture host"):
        hs.refuse_production_import(os_name="nt", identity=lambda: ("host-a", "host-a"))
    with pytest.raises(ImportError, match="not provable"):
        hs.refuse_production_import(os_name="nt", identity=lambda: (_ for _ in ()).throw(OSError("no id")))
    hs.refuse_production_import(os_name="nt", identity=lambda: ("ws", "capture"))
    hs.refuse_production_import(os_name="posix")


@pytest.mark.parametrize("start,end", [("2026-08-01", "2026-09-30"), ("2026-07-30", "2026-08-10"),
                                       ("2026-09-10", "2026-09-01")])
def test_dev_range_is_refused_outside_the_window(start, end):
    with pytest.raises(hs.ShadowError, match="refused"):
        hs.check_range(start, end)


def test_read_emitted_refuses_a_row_after_the_window(tmp_path):
    (tmp_path / "atlanta").mkdir()
    (tmp_path / "atlanta" / "f.jsonl").write_text(json.dumps({"market": "atlanta", "snapshot_id": "x",
                                                              "target_date": "2026-09-30"}) + "\n")
    with pytest.raises(hs.ShadowError):
        hs.read_emitted(tmp_path)


def _snaps(floor, mean=90.0, sd=2.0):
    return pd.DataFrame({"row_key": ["m|a"], "v2_available_at": ["2026-08-20T10:00:00Z"],
                         "captured_at_utc": ["2026-08-20T12:00:00Z"], "v2_mean": [mean], "v2_stddev": [sd],
                         "floor": [floor]})


BANDS = pd.DataFrame({"row_key": ["m|a"] * 4, "band_index": [0, 1, 2, 3], "kind": ["lte", "range", "range", "gte"],
                      "low": [np.nan, 86, 88, 90], "high": [85, 87, 89, np.nan]})


def test_mg1_rule_and_the_floor_override_only_raise_b():
    frame, b0, ok = hs.mg1_frame(_snaps(80.0), BANDS)
    assert ok.tolist() == [True] and b0.tolist() == [80.0]
    assert frame.p.sum() == pytest.approx(1.0)
    raised, b1, _ = hs.mg1_frame(_snaps(80.0), BANDS, {"m|a": 88.2})
    assert b1.tolist() == [88.0]
    assert raised.p.iloc[0] == 0.0 and raised.p.iloc[1] == 0.0
    lower, b2, _ = hs.mg1_frame(_snaps(80.0), BANDS, {"m|a": 70.0})
    assert b2.tolist() == [80.0]  # max(F, override): never weaker
    np.testing.assert_allclose(lower.p.to_numpy(), frame.p.to_numpy())


def test_mg1_needs_guidance_available_before_capture():
    s = _snaps(80.0)
    s.loc[0, "v2_available_at"] = "2026-08-20T13:00:00Z"
    frame, _, ok = hs.mg1_frame(s, BANDS)
    assert not ok.any() and frame.empty


def _row(hsf_b, hsf_f, floor_b, floor_f, fc=90.0, live=80.0):
    def feats(h):
        return {"high_so_far": h, "forecast_high": fc, "forecast_gap": fc - h, "hours_at_peak": 1.0,
                "live_reading_minus_high": live - h, "live_reading_temp": live, "current_temp": live,
                "guidance_physical_floor": h}
    return {"market": "m", "snapshot_id": "s", "target_date": "2026-08-20",
            "feat_base": feats(hsf_b), "feat_fix": feats(hsf_f),
            "floor_base": {"observed_floor_bucket": floor_b, "effective_observed_floor_high": floor_b},
            "floor_fix": {"observed_floor_bucket": floor_f, "effective_observed_floor_high": floor_f}}


def test_derived_feature_check_counts_a_weaker_floor_and_a_stale_gap():
    good = _row(76.0, 84.0, 76, 84)
    weaker = _row(84.0, 80.0, 84, 80)
    stale = _row(76.0, 84.0, 76, 84)
    stale["feat_fix"]["forecast_gap"] = stale["feat_base"]["forecast_gap"]
    out = hs.derived_feature_check([good, weaker, stale])
    assert out["rows"] == 3
    assert out["violations"]["floor_weaker"] == 1
    assert out["violations"]["floor_high_weaker"] == 1
    assert out["violations"]["forecast_gap"] == 1
    assert out["violations"]["live_reading_minus_high"] == 0


def _pooled(block, served_r, contrasts):
    return {"market": "ALL", "block": block, "R": {"served": {"estimate": served_r}},
            "dR": {c: {"date": {"estimate": sum(ci) / 2, "ci95": list(ci)}} for c, ci in contrasts.items()}}


def _result(fix_mg1, mg1fix_mg1, fix_base=(-0.02, -0.01), above=0, served=(1.774, 1.526)):
    rows = []
    for block in ("00-05", "06-09", "10-12", "13-16", "17-23", "00-16", "all"):
        r = served[0] if block == "all" else served[1]
        rows.append(_pooled(block, r, {"fix-base": fix_base if block == "00-16" else (-0.01, 0.01),
                                       "fix-mg1": fix_mg1 if block == "00-16" else (-0.01, 0.01),
                                       "mg1_fix-mg1": mg1fix_mg1 if block == "00-16" else (-0.01, 0.01)}))
    return {"rows": rows, "census": {"fix_only_above": above}}


def test_verdict_binds_only_an_arm_whose_whole_interval_beats_mg1():
    out = hs.verdict(_result((-0.03, -0.001), (-0.01, 0.002)))
    assert out["positive_control_pass"] and out["decision"].startswith("BIND as MG-2: fix")
    assert out["parity_fix_vs_base"]["decision"] == "KEEP"
    assert hs.verdict(_result((-0.03, 0.001), (-0.01, 0.002)))["decision"].startswith("NOT BOUND")


def test_verdict_refuses_on_a_failed_control_and_holds_on_new_above_settlement_floors():
    assert hs.verdict(_result((-0.03, -0.001), (-0.01, 0.002), served=(1.70, 1.526)))["decision"].startswith("NO CLAIM")
    held = hs.verdict(_result((-0.03, -0.001), (-0.01, 0.002), above=3))
    assert held["decision"].startswith("BEATS MG-1 but new above-settlement")


def test_read_emitted_skips_the_scorer_scratch_folder(tmp_path):
    (tmp_path / "atlanta").mkdir()
    (tmp_path / "_score_inputs").mkdir()
    (tmp_path / "atlanta" / "f.jsonl").write_text(json.dumps({"market": "atlanta", "snapshot_id": "x",
                                                              "target_date": "2026-09-01"}) + "\n")
    (tmp_path / "_score_inputs" / "base.jsonl").write_text(json.dumps({"market": "atlanta", "snapshot_id": "x",
                                                                       "target_date": "2026-09-01"}) + "\n")
    assert len(hs.read_emitted(tmp_path)) == 1
