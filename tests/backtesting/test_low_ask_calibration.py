"""Tiny synthetic implementation checks; never a full calibration study.

Guards: T093 exact scale/bootstrap parity and predeclared synthetic-only envelope.
"""

import pytest

from weather.backtesting import low_ask_calibration as cal
from weather.backtesting.low_ask.inference import interval, robust_scale


def test_vectorized_scale_matches_actual_final_statistic():
    np, _, _ = cal.libraries()
    rng = np.random.default_rng(123)
    panels = rng.normal(0, .7, size=(3, 75, 12))
    _, scales, _ = cal.scales(panels)
    for matrix, scale in zip(panels, scales):
        assert scale == pytest.approx(robust_scale(matrix.tolist()), rel=1e-12)


def test_small_bootstrap_matches_scalar_pass_and_negative_control():
    np, _, _ = cal.libraries()
    rng = np.random.default_rng(124)
    panels = np.stack([np.full((75, 12), .5), np.full((75, 12), -.5), rng.normal(.2, 1, (75, 12))])
    weights = cal.bootstrap_weights(256)
    passed = cal.bootstrap_success(panels, 3.0, weights)
    expected = []
    for matrix in panels:
        report = interval(matrix.tolist(), critical=3.0, resamples=256)
        expected.append(report["mean"] > .25 and report["lower"] > 0 and report["pvalue"] <= .0125)
    assert passed.tolist() == expected
    assert expected[:2] == [True, False]


def test_generator_uses_bounded_paid_cash_and_minimum_completeness():
    np, _, _ = cal.libraries()
    rng = np.random.default_rng(125)
    panels, sufficient = cal.synthetic_panels(rng, 2, (0, .25, .25, "clustered"))
    assert panels.shape == (2, 75, 12)
    assert panels.min() >= -8.18-1e-12 and panels.max() <= 1.82+1e-12
    assert sufficient.all()
    assert ((panels != 0).sum(axis=2) >= 11).sum(axis=1).tolist() == [68, 68]


def test_monte_carlo_bounds_are_conservative_and_cli_requires_admission(tmp_path, monkeypatch):
    assert cal.upper_error(0, 20_000, tail=.05/36) < .0125
    assert cal.lower_power(1800, 2000, tail=.05/(36*4)) < .9
    monkeypatch.delenv("WEATHER_WORKSTATION_WRAPPER_ACTIVE", raising=False)
    with pytest.raises(SystemExit):
        cal.main(["train", "--out", str(tmp_path)])
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("k,n", [(0, 20_000), (150, 20_000), (1800, 2000), (2000, 2000)])
def test_monte_carlo_beta_bounds_match_independent_binomial_inversion(k, n):
    from scipy.stats import binomtest
    tail = .05/36
    upper = binomtest(k, n, alternative="less").proportion_ci(1-tail, method="exact").high
    lower = binomtest(k, n, alternative="greater").proportion_ci(1-tail, method="exact").low
    assert cal.upper_error(k, n, tail=tail) == pytest.approx(upper, abs=1e-10)
    assert cal.lower_power(k, n, tail=tail) == pytest.approx(lower, abs=1e-10)
