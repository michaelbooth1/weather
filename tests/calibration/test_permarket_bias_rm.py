"""Lane L11 rung R-M: one additive per-market centre shift at 07-12 (C:/t/l11pb/rule_rm.md).

Guards: the R-M family only translates the centre (no width), preserves probability mass, reproduces the
registered arm exactly at s = 0, applies the rule-4 floor mask, picks the grid minimiser with ties to 0, and
fits walk-forward on strictly earlier dates only.
"""
import importlib

import numpy as np
import pandas as pd
import pytest

try:
    prm = importlib.import_module("weather.calibration.pooled_residual_model")
except ImportError as exc:  # pragma: no cover - only on the capture host
    if "pooled_residual_model refuses" in str(exc):
        pytest.skip("research module refuses this host by design", allow_module_level=True)
    raise

from weather.calibration import feature_model as fm  # noqa: E402

DIST = {70: 0.1, 71: 0.2, 72: 0.4, 73: 0.2, 75: 0.1}


def test_grid_contains_zero_and_ties_go_to_zero():
    assert prm.RM_GRID[prm.RM_ZERO] == 0.0 and prm.RM_GRID[0] == -4.0 and prm.RM_GRID[-1] == 4.0
    loss = np.ones(len(prm.RM_GRID))
    assert prm.rm_pick(loss) == 0.0
    loss[prm.RM_GRID.index(-0.3)] = loss[prm.RM_GRID.index(0.3)] = 0.5
    assert prm.rm_pick(loss) == -0.3  # equal |s|: the smaller value, deterministically
    loss[prm.RM_GRID.index(1.2)] = 0.1
    assert prm.rm_pick(loss) == 1.2


def test_translation_is_pure_shift_and_preserves_mass():
    ks, q = prm.rm_shift_dict(list(DIST), list(DIST.values()), (0.0, 1.0, -2.0, 0.5))
    assert np.allclose(q.sum(axis=1), 1.0)
    by = {int(k): q[0, i] for i, k in enumerate(ks)}
    assert all(by[k] == pytest.approx(v, abs=1e-15) for k, v in DIST.items())  # s = 0 is the identity
    one = {int(k): q[1, i] for i, k in enumerate(ks)}
    assert all(one[k + 1] == pytest.approx(v) for k, v in DIST.items())  # whole-degree shift moves keys
    mean = lambda row: float((ks * row).sum())  # noqa: E731
    assert mean(q[2]) - mean(q[0]) == pytest.approx(-2.0)
    assert mean(q[3]) - mean(q[0]) == pytest.approx(0.5)  # the centre moves by exactly s


def test_loyo_losses_match_brier_and_mask_below_floor():
    loss = prm.rm_loyo_losses(DIST, 72, None)
    assert loss[prm.RM_ZERO] == pytest.approx(fm.brier_score(DIST, 72))
    masked = prm.rm_loyo_losses(DIST, 72, 71.4)  # floor 71: key 70 is impossible, renormalised
    ref = {k: v / 0.9 for k, v in DIST.items() if k >= 71}
    assert masked[prm.RM_ZERO] == pytest.approx(fm.brier_score(ref, 72))
    # proper Brier: an actual outside the pmf's keys still scores its (0 - 1)^2 term
    assert prm.rm_loyo_losses(DIST, 90, None)[prm.RM_ZERO] == pytest.approx(fm.brier_score({**DIST, 90: 0.0}, 90))


def test_fix_band_mapping_reproduces_unshifted_bands():
    bands = pd.DataFrame({"row_key": ["a|1"] * 4, "band_index": [0, 1, 2, 3], "kind": ["lte", "eq", "eq", "gte"],
                          "low": [np.nan, 71, 73, np.nan], "high": [70, 72, 74, np.nan]})
    bands.loc[3, "low"] = 75
    prep = prm.rm_fix_prepare({"a|1": DIST}, bands)
    p0 = prm.rm_fix_band_probs(prep, lambda rk: 0.0).p.to_numpy()
    assert np.allclose(p0, [0.1, 0.6, 0.2, 0.1], atol=1e-15)
    p1 = prm.rm_fix_band_probs(prep, lambda rk: 1.0).p.to_numpy()
    assert np.allclose(p1, [0.0, 0.3, 0.6, 0.1]) and p1.sum() == pytest.approx(1.0)


def test_walk_forward_uses_strictly_earlier_dates():
    g = len(prm.RM_GRID)
    briers = np.ones((3, g))
    briers[0, prm.RM_GRID.index(1.0)] = 0.0  # day 1 prefers +1
    briers[1, prm.RM_GRID.index(-1.0)] = -5.0  # day 2 prefers -1 strongly
    dates = np.array(["2026-08-01", "2026-08-02", "2026-08-03"])
    markets = np.array(["dallas"] * 3)
    out = prm.rm_walk_forward(briers, dates, markets, np.ones(3, bool), ["2026-08-01", "2026-08-02", "2026-08-03"])
    assert out[("dallas", "2026-08-01")] == 0.0  # no prior date
    assert out[("dallas", "2026-08-02")] == 1.0
    assert out[("dallas", "2026-08-03")] == -1.0
