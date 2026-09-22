from datetime import datetime, timedelta, timezone
import math

import numpy as np
import pandas as pd
import pytest

from tools.research.missing_information.methods import (
    Band, band_probabilities, crossed_weights, empirical_probabilities,
    peak_time, quantile_cdf, summary,
)


def test_probability_support_and_native_fahrenheit_floor():
    bands = [Band("lte", 79, 79), Band("eq", 80, 81), Band("gte", 82, 82)]
    q = [76, 78, 80, 82, 84]
    raw = band_probabilities(bands, q, 80, 3)
    floored = band_probabilities(bands, q, 80, 3, floor=80.1)
    assert raw.sum() == pytest.approx(1)
    assert floored[0] == 0
    assert floored[1:].sum() == pytest.approx(1)
    assert floored[1] / floored[2] == pytest.approx(raw[1] / raw[2])


def test_celsius_negative_rounding_and_open_tails():
    bands = [Band("lte", -2, -2), Band("eq", -1, -1), Band("gte", 0, 0)]
    p = empirical_probabilities(bands, -1.5, [0, .01, 2, -2])
    assert p.tolist() == [.25, .5, .25]


def test_cdf_joins_normal_tails_without_mass_loss():
    q = [10, 12, 14, 16, 18]
    assert quantile_cdf(q, q, 14, 3) == pytest.approx([.1, .25, .5, .75, .9])
    curve = quantile_cdf(np.linspace(-20, 50, 1000), q, 14, 3)
    assert np.all(np.diff(curve) >= 0)
    assert curve[0] == pytest.approx(0, abs=1e-9)
    assert curve[-1] == pytest.approx(1, abs=1e-9)


def test_repeated_quantiles_are_right_continuous():
    assert quantile_cdf([10], [8, 10, 10, 10, 12], 10, 2)[0] == .75


@pytest.mark.parametrize("q,std", [([1, 3, 2, 4, 5], 1), ([1, 2, math.nan, 4, 5], 1), ([1, 2, 3, 4, 5], 0)])
def test_invalid_guidance_refused(q, std):
    with pytest.raises(ValueError):
        quantile_cdf([3], q, 3, std)


def test_missing_band_does_not_renormalize_away():
    with pytest.raises(ValueError, match="gap or overlap"):
        empirical_probabilities([Band("lte", 1, 1), Band("gte", 3, 3)], 2, [0])


def test_peak_frozen_rule_and_nonmonotonic_sensitivity_differ():
    t = [datetime(2026, 8, 1, tzinfo=timezone.utc) + timedelta(hours=h) for h in range(5)]
    values = [None, 28, 30, 29, 29]
    assert peak_time(t, values) == t[3]
    assert peak_time(t, values, envelope=True) == t[2]
    assert peak_time(t, [None] * 5) is None
    assert peak_time(t, [27, 29, 29, 29, 29]) == t[1]


def test_peak_rejects_timezone_free_or_unsorted_times():
    with pytest.raises(ValueError, match="aware"):
        peak_time([datetime(2026, 8, 1)], [30])
    t = datetime(2026, 8, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="order"):
        peak_time([t + timedelta(hours=1), t], [28, 30])


def test_crossed_bootstrap_shares_date_and_market_multiplicities():
    w = crossed_weights([1, 1, 2, 2], ["a", "b", "a", "b"], seed=11)
    assert w.shape == (2000, 4)
    assert np.all(w[:, 0] * w[:, 3] == w[:, 1] * w[:, 2])
    assert np.all(w.sum(axis=1) == 4)
    assert np.array_equal(w, crossed_weights([1, 1, 2, 2], ["a", "b", "a", "b"], seed=11))


def test_duplicate_snapshots_cannot_increase_cluster_support():
    frame = pd.DataFrame({"date": [1, 1, 2, 2, 3, 3], "market": ["a", "b"] * 3,
                          "loss": [1, 2, 3, 4, 5, 6]})
    repeated = pd.concat([frame, frame.iloc[[0]]] * 3, ignore_index=True)
    a = summary(frame, "loss", alternative=1)
    b = summary(repeated, "loss", alternative=1)
    assert a == b
    assert a["market_days"] == 6
    assert a["date_clusters"] == 3
    assert a["market_clusters"] == 2
    assert a["estimate"] == 3.5
    assert a["ci95"][0] < a["estimate"] < a["ci95"][1]


def test_ratio_is_ratio_of_means_and_one_market_is_not_crossed_inference():
    f = pd.DataFrame({"date": [1, 2], "market": ["a", "a"], "x": [1, 9], "y": [1, 3]})
    r = summary(f, "x", "y", null=1)
    assert r["estimate"] == 2.5
    assert r["status"] == "INSUFFICIENT_CLUSTERS"
    assert r["ci95"] is None
