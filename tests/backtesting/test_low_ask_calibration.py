"""Tiny synthetic implementation checks; never a full calibration study.

Guards: T093 B1-B4 and C1/C2/C4 retained-city nulls, cash, power and bootstrap parity.
"""

import os

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
    panels, sufficient, diagnostics = cal.synthetic_panels(rng, 2, cal.SIZE_ARMS[3])
    assert panels.shape == (2, 75, 12)
    assert panels.min() >= -8.18-1e-12 and panels.max() <= 1.82+1e-12
    assert sufficient.all()
    assert diagnostics["executable_city_days"].tolist() == [810, 810]
    assert diagnostics["adequate_dates"].tolist() == [68, 68]


def test_bootstrap_nondegenerate_components_match_scalar_final_look():
    np, _, _ = cal.libraries()
    rng = np.random.default_rng(902)
    panels = rng.uniform(-1, 1, (3, 75, 12))
    panels += np.array([-.2, .1, .45])[:, None, None]
    components = cal.bootstrap_components(panels, cal.bootstrap_weights(256))
    for j, matrix in enumerate(panels):
        scalar = interval(matrix.tolist(), critical=3, resamples=256)
        for name, result in components.items():
            assert result["pvalue"][j] == pytest.approx(scalar["pvalues"][name], abs=1e-14)
            assert result["lower"][j] == pytest.approx(scalar["intervals"][name][0], abs=1e-12)
            assert result["upper"][j] == pytest.approx(scalar["intervals"][name][1], abs=1e-12)
        means, scales, _ = cal.scales(panels[j:j+1])
        assert means[0]-3*scales[0] == pytest.approx(scalar["intervals"]["calibrated_envelope"][0])


def test_realized_cash_binds_after_losses_and_preserves_gains():
    np, _, _ = cal.libraries()
    available = np.ones((2, 75, 12), dtype=bool)
    outcomes = np.zeros((2, 75, 12), dtype=bool)
    outcomes[1] = True
    delay3 = np.zeros((2, 75, 12, 2), dtype=bool)
    shares, diagnostics = cal.realized_cash(available, outcomes, delay3, ask=.8)
    assert shares[0].sum() == 5*73  # floor(300/4.09); losses are permanent.
    assert diagnostics["cash_cap_slots"][0] == 1800-73
    assert diagnostics["binding"].tolist() == [True, False]
    assert shares[1].sum() == 9000
    assert diagnostics["ending_cash"][0] == pytest.approx(300-73*4.09)
    assert diagnostics["ending_cash"][1] == pytest.approx(300+1800*.91)
    assert (diagnostics["peak_locked"] <= 300+1e-10).all()


def test_retained_gains_cannot_raise_total_locked_cap():
    np, _, _ = cal.libraries()
    available = np.ones((1, 75, 12), dtype=bool)
    shares, diagnostics = cal.realized_cash(available, available, np.ones((1, 75, 12, 2), dtype=bool), ask=.93)
    assert diagnostics["binding"][0] and diagnostics["cash_cap_slots"][0] > 0
    assert diagnostics["ending_cash"][0] > 300
    assert diagnostics["peak_locked"][0] <= 300
    assert 0 < shares.sum() < 9000


def test_fixed_city_offsets_are_centred_and_do_not_randomize_portfolio_mean():
    np, _, _ = cal.libraries()
    offsets = cal.fixed_city_offsets()
    assert offsets.shape == (12,) and offsets.mean() == pytest.approx(0, abs=1e-15)
    assert (offsets**2).mean() == pytest.approx(1)
    for probability in (.818, .943255):
        survival = cal.city_survival(probability, .25)
        assert survival.mean() == pytest.approx(probability, abs=1e-12)
        assert np.ptp(survival) > .01
        assert np.array_equal(survival, cal.city_survival(probability, .25))


@pytest.mark.parametrize("support", [810, 900, 825])
@pytest.mark.parametrize("persistent", [0, .25])
def test_support_boundary_null_is_centred_over_retained_cities(support, persistent):
    np, _, _ = cal.libraries()
    retained = np.ones(12, dtype=bool)
    if support == 825:
        retained[sorted(cal.CITIES).index("chicago")] = False
    survival = cal.city_survival(.818, persistent, support=support)
    assert survival[retained].mean() == pytest.approx(.818, rel=0, abs=1e-12)
    assert (10*(survival[retained]-.818)).mean() == pytest.approx(0, abs=1e-12)


@pytest.mark.parametrize("support", [810, 900, 825])
def test_high_ask_generator_uses_exact_zero_mean_boundary_null(support, monkeypatch):
    from decimal import Decimal
    np, _, _ = cal.libraries()
    exact_cost = float(Decimal(".93")+Decimal(".05")*Decimal(".93")*Decimal(".07")+Decimal(".01"))
    original = cal.city_survival
    def capture(probability, persistent, **kwargs):
        assert probability == pytest.approx(exact_cost, rel=0, abs=1e-12)
        survival = original(probability, persistent, **kwargs)
        retained = np.ones(12, dtype=bool)
        if support == 825:
            retained[sorted(cal.CITIES).index("chicago")] = False
        assert (10*(survival[retained]-exact_cost)).mean() == pytest.approx(0, abs=1e-12)
        return survival
    monkeypatch.setattr(cal, "city_survival", capture)
    arm = dict(phi=.5, common=.5, persistent=.25, mechanism="spread", support=support, ask=.93)
    cal.synthetic_panels(np.random.default_rng(156), 1, arm)


def test_bootstrap_near_ties_use_conservative_margin():
    np, _, _ = cal.libraries()
    components = cal.bootstrap_components(np.full((1, 75, 12), 2.5e-11), cal.bootstrap_weights(128))
    assert all(result["pvalue"][0] == 1 for result in components.values())


def test_size_supports_and_planning_power_scope_are_explicit():
    assert len(cal.SIZE_ARMS) == 120
    assert len(cal.POWER_ARMS) == 108
    planning = [a for a in cal.SIZE_ARMS if cal.is_planning_arm(a)]
    assert len(planning) == 2
    assert {a["mechanism"] for a in planning} == {"spread", "clustered"}
    assert all(a["support"] == 810 and a["ask"] == .8 for a in planning)
    assert len([a for a in cal.SIZE_ARMS if a["ask"] == .93]) == 12
    assert cal.TRAIN_QUANTILE == .9925


def test_receipt_power_gate_uses_only_planning_but_size_uses_every_stress():
    reports = [dict(arm_index=i, arm=a, size_upper=.01, null_diagnostics={"binding_probability": .2},
                    planning_power_lower=.81 if cal.is_planning_arm(a) else .1,
                    power=[{"intended_city_day_effect": e, "lower": .1} for e in cal.EFFECTS]
                          if a["ask"] == .8 else [])
               for i, a in enumerate(cal.SIZE_ARMS)]
    result = cal.summarize_reports(reports)
    assert result["status"] == "CALIBRATED" and result["power_lower"] == .81
    assert len(result["power_cells"]) == 432  # Includes all original 144 cells.
    reports[-1]["size_upper"] = .013
    assert cal.summarize_reports(reports)["status"] == "SCREEN_ONLY"
    reports[-1]["size_upper"] = .01
    reports[result["planning_arm_indices"][0]]["planning_power_lower"] = .79
    result = cal.summarize_reports(reports)
    assert result["status"] == "SCREEN_ONLY" and result["power_lower"] == .79
    reports[0]["power"].pop()
    with pytest.raises(ValueError, match="diagnostic power cells"):
        cal.summarize_reports(reports)


@pytest.mark.parametrize("support,dates", [(810, 68), (900, 75), (825, 75)])
def test_generated_support_counts_ignore_realized_cash_blocking(support, dates):
    np, _, _ = cal.libraries()
    arm = dict(phi=.22, common=.5, persistent=0, mechanism="clustered", support=support, ask=.8)
    _, sufficient, diagnostics = cal.synthetic_panels(np.random.default_rng(712), 2, arm)
    assert sufficient.all()
    assert diagnostics["executable_city_days"].tolist() == [support, support]
    assert diagnostics["adequate_dates"].tolist() == [dates, dates]


@pytest.mark.skipif(os.name != "nt", reason="Task output-root contract is Windows-specific")
def test_output_root_refuses_escape_and_sibling(tmp_path):
    from pathlib import Path
    assert cal.output_root(Path(r"C:\t\codex\T093\out\calibration-r1")).is_absolute()
    for invalid in (Path(r"C:\outside\out"), Path(r"C:\t\codex\T093evil\out"),
                    Path(r"C:\t\codex\T093\..\other"), Path("relative")):
        with pytest.raises(ValueError, match="T093"):
            cal.output_root(invalid)


@pytest.mark.parametrize("ask", [.8, .9, .93])
def test_grouped_cash_matches_scalar_decimal_policy(ask):
    import heapq
    from decimal import Decimal
    np, _, _ = cal.libraries()
    rng = np.random.default_rng(411)
    available = rng.random((3, 75, 12)) < .92
    outcomes = rng.random((3, 75, 12)) < .83
    outcomes[0] = False
    delay3 = rng.random((3, 75, 12, 2)) < .3
    actual, diagnostics = cal.realized_cash(available, outcomes, delay3, ask=ask)
    price = Decimal(str(ask))
    cost = 5*(price+Decimal(".05")*price*(1-price)+Decimal(".01"))
    for b in range(3):
        cash, locked, blocked, peak = Decimal(300), Decimal(0), 0, Decimal(0)
        pending = []
        expected = np.zeros((75, 12))
        for at, _, _, d, j, k in cal.execution_slots():
            while pending and pending[0][0] <= at:
                _, payout = heapq.heappop(pending)
                cash += payout
                locked -= cost
            if not available[b, d, j]:
                continue
            if cash < cost or locked+cost > 300:
                blocked += 1
                continue
            cash -= cost
            locked += cost
            peak = max(peak, locked)
            expected[d, j] += 5
            heapq.heappush(pending, (at+(3 if delay3[b, d, j, k] else 1)*86400,
                                    Decimal(5 if outcomes[b, d, j] else 0)))
        cash += sum((payout for _, payout in pending), Decimal(0))
        assert np.array_equal(actual[b], expected)
        assert diagnostics["cash_cap_slots"][b] == blocked
        assert diagnostics["ending_cash"][b] == pytest.approx(float(cash))
        assert diagnostics["peak_locked"][b] == pytest.approx(float(peak))


def test_monte_carlo_bounds_are_conservative_and_cli_requires_admission(tmp_path, monkeypatch):
    assert cal.upper_error(0, 20_000, tail=.05/120) < .0125
    assert cal.lower_power(1800, 2000, tail=.05/(108*4)) < .9
    monkeypatch.delenv("WEATHER_WORKSTATION_WRAPPER_ACTIVE", raising=False)
    with pytest.raises(SystemExit):
        cal.main(["train", "--out", str(tmp_path)])
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("tail", [.05/120, .05/432, .05/2])
@pytest.mark.parametrize("k,n", [(0, 20_000), (150, 20_000), (1800, 2000), (2000, 2000)])
def test_monte_carlo_beta_bounds_match_independent_binomial_inversion(k, n, tail):
    from scipy.stats import binomtest
    upper = binomtest(k, n, alternative="less").proportion_ci(1-tail, method="exact").high
    lower = binomtest(k, n, alternative="greater").proportion_ci(1-tail, method="exact").low
    assert cal.upper_error(k, n, tail=tail) == pytest.approx(upper, abs=1e-10)
    assert cal.lower_power(k, n, tail=tail) == pytest.approx(lower, abs=1e-10)
