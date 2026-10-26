"""R-U P0 statistics (rule_ru.md, sha 9441cc94...).

Guards: R-U's P0 uses L3's R-Z thresholds unchanged (pooled rho >= 0.05, at most one opposite-sign year), centres
z per market and hour on the training years only (leave-one-year-out), reports per hour and on the rise subset,
and the rule sha is the one pushed before any run.
"""
import importlib

import numpy as np
import pandas as pd
import pytest

prm = importlib.import_module("weather.calibration.pooled_residual_model")
rz = pytest.importorskip("weather.calibration.rz_hrrr_spread")


def _frame(signs, n=400, seed=0):
    rng = np.random.default_rng(seed)
    parts = []
    for year, sign in zip(range(2021, 2026), signs):
        z = rng.normal(size=n)
        e = np.exp(sign * 0.5 * z) * np.abs(rng.normal(size=n))  # |error| rises with z when sign > 0
        parts.append(pd.DataFrame({"year": year, "market": rng.choice(["atlanta", "miami"], n),
                                   "hour": rng.choice([13, 14, 15, 16], n), "z": z,
                                   "e": e, "rise": rng.random(n) < 0.3}))
    return pd.concat(parts, ignore_index=True)


def test_ru_p0_survives_on_a_consistent_positive_anomaly():
    out = prm.ru_p0_stats(_frame([1, 1, 1, 1, 1]))
    assert not out["closed"] and out["pooled"]["rho"] > 0.05 and out["opposite_sign_years"] == []
    assert set(out["per_hour"]) == {"h13", "h14", "h15", "h16"}
    assert out["rise_reported_only"]["pooled"]["n"] > 0


def test_ru_p0_closes_on_two_opposite_years_or_a_weak_pool():
    two_flips = prm.ru_p0_stats(_frame([1, 1, 1, -1, -1]))
    assert two_flips["closed"] and len(two_flips["opposite_sign_years"]) == 2
    assert prm.ru_p0_stats(_frame([0, 0, 0, 0, 0]))["closed"]


def test_ru_p0_centres_out_of_year():
    # z shifted by +5 in 2021 only: centring on the other years leaves 2021's za high, so the pooled rho (z vs e)
    # is unchanged in sign and every 2021 row is still scored
    frame = _frame([1, 1, 1, 1, 1])
    frame.loc[frame["year"] == 2021, "z"] += 5.0
    out = prm.ru_p0_stats(frame)
    assert out["per_year"]["2021"]["n"] == int((frame["year"] == 2021).sum())
    assert out["per_year"]["2021"]["rho"] > 0.05


def test_ru_rule_sha_is_pinned():
    assert prm.RU_RULE_SHA256.startswith("9441cc94") and prm.RU_STATE_SHA256.startswith("e891d884")
    assert rz.P0_RHO_MIN == 0.05 and rz.P0_FLIP_MAX == 1
