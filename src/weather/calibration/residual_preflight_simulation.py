"""Synthetic crossed-date/market uncertainty and power planning, never a skill test."""
from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np
from scipy.stats import t

from weather.calibration.residual_preflight_io import PreflightError

SCENARIOS = (
    {"name": "balanced_independent_dates", "markets": 12, "date_sd": 1.0, "market_sd": .15, "cell_sd": 1.0, "date_ar1": 0.0, "late_sd_multiplier": 1.0},
    {"name": "persistent_dates", "markets": 12, "date_sd": 2.0, "market_sd": .30, "cell_sd": 2.0, "date_ar1": .5, "late_sd_multiplier": 1.0},
    {"name": "market_variation", "markets": 12, "date_sd": 1.0, "market_sd": .75, "cell_sd": 1.0, "date_ar1": .2, "late_sd_multiplier": 1.0},
    {"name": "eight_markets_late_variance", "markets": 8, "date_sd": 2.0, "market_sd": .50, "cell_sd": 2.0, "date_ar1": .6, "late_sd_multiplier": 1.5},
)
DEFAULT_CONFIG = {
    "seed": 112026, "replicates": 2000, "date_counts": [60, 120, 240],
    "effects_c2": [0.0, .10, .25, .50], "planning_hurdle_c2": .25,
    "hac_lags": 7, "batch_size": 100,
}


def wilson(successes, count):
    if count <= 0 or not 0 <= successes <= count:
        raise PreflightError("simulation:binomial_count")
    z = NormalDist().inv_cdf(.975)
    fraction = successes / count
    denominator = 1 + z * z / count
    center = (fraction + z * z / (2 * count)) / denominator
    half = z * math.sqrt(fraction * (1 - fraction) / count + z * z / (4 * count * count)) / denominator
    return {"count": int(successes), "replicates": int(count), "rate": fraction, "mc_95_interval": [max(0., center - half), min(1., center + half)]}


def variance_estimators(panels, *, hac_lags=7):
    """Intercept-only CRV1 date + market - intersection, with optional date HAC.

    Nonpositive results remain invalid. No eigenvalue or zero clipping is used.
    The HAC hybrid is a candidate for this simulation, not an adopted test.
    """
    values = np.asarray(panels, dtype=float)
    if values.ndim == 2:
        values = values[np.newaxis, :, :]
    if values.ndim != 3 or min(values.shape[1:]) < 2 or not np.isfinite(values).all():
        raise PreflightError("simulation:panel_shape")
    if type(hac_lags) is not int or not 0 <= hac_lags <= 31:
        raise PreflightError("simulation:hac_lags")
    dates, markets = values.shape[1:]
    observations = dates * markets
    centered = values - values.mean(axis=(1, 2), keepdims=True)
    date_scores = centered.sum(axis=2)
    market_scores = centered.sum(axis=1)
    date_meat = (date_scores ** 2).sum(axis=1)
    hac_meat = date_meat.copy()
    highest_lag = min(hac_lags, dates - 1)
    for lag in range(1, highest_lag + 1):
        weight = 1 - lag / (highest_lag + 1)
        hac_meat += 2 * weight * (date_scores[:, lag:] * date_scores[:, :-lag]).sum(axis=1)
    market_meat = markets / (markets - 1) * (market_scores ** 2).sum(axis=1)
    intersection = observations / (observations - 1) * (centered ** 2).sum(axis=(1, 2))
    date_correction = dates / (dates - 1)
    return {
        "two_way_crv1": (date_correction * date_meat + market_meat - intersection) / observations ** 2,
        "date_hac7_plus_market_minus_cell": (date_correction * hac_meat + market_meat - intersection) / observations ** 2,
    }


def date_scale(dates, scenario):
    scale = np.ones(dates)
    scale[dates // 2:] = scenario["late_sd_multiplier"]
    return scale


def oracle_variance(dates, scenario):
    """Exact variance of the simulated average under the declared Gaussian DGP."""
    markets = scenario["markets"]
    scale = date_scale(dates, scenario)
    lag = np.abs(np.arange(dates)[:, None] - np.arange(dates)[None, :])
    correlation = scenario["date_ar1"] ** lag
    date_component = scenario["date_sd"] ** 2 * float(scale @ correlation @ scale) / dates ** 2
    market_component = scenario["market_sd"] ** 2 / markets
    cell_component = scenario["cell_sd"] ** 2 * float(scale @ scale) / (dates ** 2 * markets)
    return {
        "date": date_component, "market": market_component, "cell": cell_component,
        "total": date_component + market_component + cell_component,
    }


def _noise(rng, count, dates, scenario):
    markets, rho = scenario["markets"], scenario["date_ar1"]
    dates_raw = rng.normal(size=(count, dates))
    innovations = math.sqrt(1 - rho * rho)
    for index in range(1, dates):
        dates_raw[:, index] = rho * dates_raw[:, index - 1] + innovations * dates_raw[:, index]
    scale = date_scale(dates, scenario)
    date_effect = scenario["date_sd"] * dates_raw * scale
    market_effect = scenario["market_sd"] * rng.normal(size=(count, markets))
    individual = scenario["cell_sd"] * rng.normal(size=(count, dates, markets)) * scale[None, :, None]
    return date_effect[:, :, None] + market_effect[:, None, :] + individual


def _validate_config(config):
    if set(config) != set(DEFAULT_CONFIG):
        raise PreflightError("simulation:configuration_keys")
    if (type(config["seed"]) is not int or not 0 <= config["seed"] < 2 ** 32
            or type(config["replicates"]) is not int or not 100 <= config["replicates"] <= 10000
            or type(config["batch_size"]) is not int or not 1 <= config["batch_size"] <= 200
            or config["date_counts"] != [60, 120, 240]
            or config["effects_c2"] != [0.0, .10, .25, .50]
            or config["planning_hurdle_c2"] != .25 or config["hac_lags"] != 7):
        raise PreflightError("simulation:configuration_scope")


def run_grid(config):
    _validate_config(config)
    output = []
    repetitions = config["replicates"]
    normal = NormalDist()
    for scenario_index, scenario in enumerate(SCENARIOS):
        for dates in config["date_counts"]:
            rng = np.random.default_rng(np.random.SeedSequence([config["seed"], scenario_index, dates]))
            components = oracle_variance(dates, scenario)
            degrees = min(dates - 1, scenario["markets"] - 1)
            quantiles = {
                "two_way_crv1": (float(t.ppf(.95, degrees)), float(t.ppf(.975, degrees))),
                "date_hac7_plus_market_minus_cell": (float(t.ppf(.95, degrees)), float(t.ppf(.975, degrees))),
                "known_covariance_oracle": (normal.inv_cdf(.95), normal.inv_cdf(.975)),
            }
            counts = {
                method: {"valid": 0, "coverage": 0, "positive": [0] * 4, "practical": [0] * 4}
                for method in quantiles
            }
            means = []
            for start in range(0, repetitions, config["batch_size"]):
                size = min(config["batch_size"], repetitions - start)
                panels = _noise(rng, size, dates, scenario)
                mean = panels.mean(axis=(1, 2))
                estimates = variance_estimators(panels, hac_lags=config["hac_lags"])
                estimates["known_covariance_oracle"] = np.full(size, components["total"])
                means.extend(mean.tolist())
                for method, estimate in estimates.items():
                    valid = np.isfinite(estimate) & (estimate > 0)
                    standard_error = np.full(size, np.nan)
                    standard_error[valid] = np.sqrt(estimate[valid])
                    one_sided, two_sided = quantiles[method]
                    target = counts[method]
                    target["valid"] += int(valid.sum())
                    target["coverage"] += int((valid & (np.abs(mean) <= two_sided * standard_error)).sum())
                    for effect_index, effect in enumerate(config["effects_c2"]):
                        lower = mean + effect - one_sided * standard_error
                        target["positive"][effect_index] += int((valid & (lower > 0)).sum())
                        target["practical"][effect_index] += int((valid & (lower > config["planning_hurdle_c2"])).sum())
            for method, result in counts.items():
                valid = result["valid"]
                coverage = wilson(result["coverage"], repetitions)
                false_positive = wilson(result["positive"][0], repetitions)
                # Prespecified diagnostics only; real test qualification remains open.
                screen = (valid == repetitions and false_positive["mc_95_interval"][1] <= .075
                          and coverage["mc_95_interval"][0] >= .925)
                output.append({
                    "scenario": scenario, "date_clusters": dates, "market_clusters": scenario["markets"],
                    "market_days": dates * scenario["markets"], "method": method,
                    "critical_distribution": "normal" if method == "known_covariance_oracle" else "t",
                    "critical_degrees_of_freedom": None if method == "known_covariance_oracle" else degrees,
                    "true_mean_variance_c4": components,
                    "empirical_mean_variance_c4": float(np.var(means, ddof=1)),
                    "invalid_variance": wilson(repetitions - valid, repetitions),
                    "null_one_sided_false_positive": false_positive,
                    "null_two_sided_95_coverage": coverage,
                    "coverage_given_valid": None if not valid else wilson(result["coverage"], valid),
                    "prespecified_diagnostic_screen": "PASS" if screen else "FAIL",
                    "effect_scenarios": [{
                        "effect_c2": effect,
                        "positive_lower_bound_probability": wilson(result["positive"][index], repetitions),
                        "lower_bound_above_planning_hurdle_probability": wilson(result["practical"][index], repetitions),
                    } for index, effect in enumerate(config["effects_c2"])],
                })
    return {
        "status": "SYNTHETIC_PLANNING_ONLY", "config": config, "rows": output,
        "loss_difference": "Baseline squared error minus challenger squared error, in Celsius-equivalent squared units.",
        "dgp": "Gaussian date AR(1) plus persistent independent market effects and independent cell noise; all variances assumed, never estimated from held-out outcomes.",
        "missingness": "The eight-market scenario fixes four absent markets for all dates; it cannot support a twelve-market claim.",
        "screen": "Diagnostic only: no invalid variance, false-positive Wilson upper <= .075 and coverage Wilson lower >= .925. No method is adopted from this screen.",
        "invalid_handling": "Nonpositive/nonfinite variance refuses inference; counts as noncoverage and no rejection in unconditional rates; valid-only coverage is separate.",
        "hurdle_note": "0.25 C-equivalent squared is a planning sensitivity, not a frozen confirmatory hurdle.",
        "real_dates_required": None, "alpha_spent": 0, "model_or_market_edge_established": False,
        "sources": [
            "https://cameron.econ.ucdavis.edu/research/JBESpaper2009version.pdf",
            "https://www.statsmodels.org/dev/generated/statsmodels.stats.sandwich_covariance.cov_cluster_2groups.html",
            "https://www.statsmodels.org/stable/generated/statsmodels.stats.sandwich_covariance.cov_hac.html",
        ],
        "limitations": "Only the declared artificial dependence/variance processes are evaluated. The HAC hybrid and finite-cluster t choice require further qualification; more dates do not eliminate a persistent market component.",
    }
