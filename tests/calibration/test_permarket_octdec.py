"""Light checks for L3's ledger row 92 module (no data read; synthetic arrays only)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from weather.calibration import permarket_octdec as m
from weather.calibration import season_matched_l6 as sm


def _synthetic(n=600, bias=0.0, seed=0, floor_gap=None):
    rng = np.random.default_rng(seed)
    truth = rng.normal(60.0, 6.0, n)
    dmax = np.round(truth)
    R = dmax - (rng.integers(0, 6, n) if floor_gap is None else floor_gap)
    mu = truth + rng.normal(0.0, 1.5, n) - bias
    sig = np.full(n, 2.0)
    return mu, sig, R, dmax


def test_constants_and_grid():
    assert len(m.RULE_SHA256) == 64 and int(m.RULE_SHA256, 16) >= 0
    assert len(m.GRID) == 81 and m.GRID[0] == -4.0 and m.GRID[-1] == 4.0 and 0.0 in m.GRID
    assert m.REOPEN_SHIFT_F == 1.0 and m.REOPEN_MIN_FOLDS == 3 and m.PLANT_MARKET == "austin"


def test_fit_shift_recovers_a_planted_bias_and_prefers_zero_on_ties():
    # far floor (no truncation): an unbiased centre fits near 0 and a -2 bias fits near +2
    mu, sig, R, dmax = _synthetic(bias=2.0, floor_gap=8)
    s, at_s, at_0 = m.fit_shift(mu, sig, R, dmax)
    assert 1.5 <= s <= 2.5 and at_s <= at_0
    mu0, sig0, R0, d0 = _synthetic(bias=0.0, seed=1, floor_gap=8)
    s0, _, _ = m.fit_shift(mu0, sig0, R0, d0)
    assert abs(s0) <= 0.5
    flat = m.fit_shift(np.full(4, 50.0), np.full(4, 1e-6), np.full(4, 0.0), np.full(4, 50.0), grid=(-0.2, 0.0, 0.2))
    assert flat[0] == 0.0


def test_reopen_condition_needs_three_same_sign_folds():
    years = ("2021", "2022", "2023", "2024", "2025")
    assert m.reopen_condition({"a": dict(zip(years, (1.1, 1.2, 1.5, 0.0, -2.0)))})[0]
    assert not m.reopen_condition({"a": dict(zip(years, (1.1, 1.2, -1.5, -1.2, 0.3)))})[0]
    assert not m.reopen_condition({"a": dict(zip(years, (1.0, 1.0, 1.0, 1.0, 1.0)))})[0]


def test_apply_shifts_zero_is_identity_and_plant_moves_one_market():
    rows = pd.DataFrame({"market": ["austin", "miami", "austin"], "year": [2021, 2021, 2022]})
    mu = np.array([60.0, 70.0, 65.0])
    zero = {"austin": {"2021": 0.0, "2022": 0.0}, "miami": {"2021": 0.0}}
    assert np.array_equal(m.apply_shifts(rows, mu, zero), mu)
    out = m.apply_shifts(rows, mu, {"austin": {"2022": 0.5}}, plant=("austin", -2.0))
    assert np.allclose(out, [58.0, 70.0, 63.5])


def test_stack_mu_matches_season_matched_stack_brier():
    rng = np.random.default_rng(3)
    n = 40
    frame = pd.DataFrame({"v": rng.normal(60, 5, n), "s": rng.uniform(0.5, 3, n), "hour": rng.integers(7, 13, n),
                          "r": rng.normal(55, 5, n), "dmax": np.round(rng.normal(61, 5, n))})
    nn = frame.v.to_numpy() + rng.normal(0, 1, n)
    coef = {str(h): (0.1 * h, 0.4, None) for h in range(7, 13)}
    part, _, mu_ref = sm.stack_brier(frame, nn, coef)
    mu, sig, ok = m.stack_mu(frame, nn, coef)
    assert np.array_equal(mu, mu_ref) and ok.all()
    assert np.array_equal(m.brier(mu, sig, frame.r.to_numpy(), frame.dmax.to_numpy()), part)


def test_nested_shifts_recovers_plant_relative_to_unplanted():
    years = (2021, 2022, 2023, 2024, 2025)
    per = 200
    rows = pd.DataFrame({"market": ["austin"] * per * 5, "year": np.repeat(years, per)})
    mu, sig, R, dmax = _synthetic(n=per * 5, seed=7)
    rows["r"], rows["dmax"] = R, dmax
    inner = {frozenset((x, y)): mu for i, x in enumerate(years) for y in years[i + 1:]}
    ok = np.ones(len(rows), bool)
    nat, train_ok = m.nested_shifts(rows, inner, sig, ok, years)
    planted, _ = m.nested_shifts(rows, inner, sig, ok, years, plant=("austin", -2.0))
    assert train_ok
    for y in nat["austin"]:
        assert 1.5 <= planted["austin"][y] - nat["austin"][y] <= 2.5
