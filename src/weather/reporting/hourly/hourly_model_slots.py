"""Implementation slice extracted from src/weather/reporting/hourly_model_performance.py."""

from weather.reporting.hourly.hourly_model_scoring import *  # noqa: F403

# The extracted functions below intentionally resolve globals from the
# previous slice to preserve the original module namespace.

def summarize_by_hour(rows):
    output = []
    grouped = rows_for_group(rows, "cutoff_hour")
    for hour, hour_rows in sorted(grouped.items(), key=lambda item: int(item[0]) if item[0] is not None else 99):
        if hour is None:
            continue
        summary = summarize_rows(hour_rows)
        if summary:
            summary["hour"] = int(hour)
            summary["hour_label"] = f"{int(hour):02d}:00"
            output.append(summary)
    return output


def summarize_by_hour_regime(rows):
    output = []
    grouped = rows_for_group(rows, lambda row: hour_regime(row.get("cutoff_hour")))
    order = list(HOUR_REGIME_LABELS)
    for regime in order:
        regime_rows = grouped.get(regime, [])
        summary = summarize_rows(regime_rows)
        if summary:
            summary["regime"] = regime
            summary["regime_label"] = HOUR_REGIME_LABELS[regime]
            output.append(summary)
    return output


def early_hour_market_deltas(
    rows,
    *,
    early_brier_regression_tolerance=DEFAULT_EARLY_BRIER_REGRESSION_TOLERANCE,
    early_logloss_regression_tolerance=DEFAULT_EARLY_LOGLOSS_REGRESSION_TOLERANCE,
):
    output = []
    grouped = rows_for_group(
        [
            row for row in rows
            if hour_regime(row.get("cutoff_hour")) == "early_morning"
        ],
        "market_id",
    )
    for market_id, market_rows in sorted(grouped.items(), key=lambda item: str(item[0])):
        if not market_id:
            continue
        summary = summarize_rows(market_rows)
        if not summary:
            continue
        brier_delta = safe_float(summary.get("brier_delta"))
        logloss_delta = safe_float(summary.get("logloss_delta"))
        blocking_gates = []
        if brier_delta is not None and brier_delta < -float(early_brier_regression_tolerance):
            blocking_gates.append("early_hour_brier_regression")
        if logloss_delta is not None and logloss_delta < -float(early_logloss_regression_tolerance):
            blocking_gates.append("early_hour_logloss_regression")
        output.append({
            "market_id": market_id,
            "status": "BLOCK" if blocking_gates else "PASS",
            "blocking_gates": blocking_gates,
            "n": summary.get("n"),
            "market_days": summary.get("market_days"),
            "snapshots": summary.get("snapshots"),
            "model_brier": summary.get("model_brier"),
            "market_brier": summary.get("market_brier"),
            "brier_delta": brier_delta,
            "model_logloss": summary.get("model_logloss"),
            "market_logloss": summary.get("market_logloss"),
            "logloss_delta": logloss_delta,
            "model_ece": summary.get("model_ece"),
            "winner_model_probability": summary.get("winner_model_probability"),
            "winner_market_probability": summary.get("winner_market_probability"),
        })
    return sorted(
        output,
        key=lambda row: (
            row.get("status") != "BLOCK",
            safe_float(row.get("brier_delta")) if row.get("brier_delta") is not None else math.inf,
            str(row.get("market_id") or ""),
        ),
    )


def rank_hours(by_hour, min_rows=DEFAULT_MIN_ROWS, top_hours=DEFAULT_TOP_HOURS):
    eligible = [row for row in by_hour if int(row.get("n") or 0) >= int(min_rows)]
    best = sorted(
        eligible,
        key=lambda row: (row.get("model_brier", math.inf), row.get("model_logloss", math.inf), -int(row.get("n") or 0)),
    )[:top_hours]
    worst = sorted(
        eligible,
        key=lambda row: (row.get("model_brier", -math.inf), row.get("model_logloss", -math.inf), int(row.get("n") or 0)),
        reverse=True,
    )[:top_hours]
    return best, worst


def clamp_probability(value):
    return max(0.0, min(1.0, float(value)))


def rows_with_probability(rows, probability_fn):
    output = []
    for row in rows:
        copy = dict(row)
        probability = probability_fn(row)
        if probability is None:
            continue
        copy["model_probability"] = clamp_probability(probability)
        output.append(copy)
    return output


def market_blend_rows(rows, alpha):
    alpha = max(0.0, min(1.0, float(alpha)))
    return rows_with_probability(
        rows,
        lambda row: (
            (1.0 - alpha) * float(row["model_probability"])
            + alpha * float(row["market_yes"])
        ),
    )


def partition_power_rows(rows, gamma):
    """Normalize each snapshot's band partition after applying p**gamma.

    This is a pure model-output probe.  It deliberately does not use market
    prices or outcomes at serving time, but it can reveal whether the hour's
    failure is mostly calibration/sharpness versus the distribution being
    centered on the wrong band.
    """
    gamma = max(0.05, float(gamma))
    output = [dict(row) for row in rows]
    grouped = defaultdict(list)
    for index, row in enumerate(output):
        grouped[(
            row.get("market_id"),
            row.get("target_date"),
            row.get("snapshot_id"),
            row.get("cutoff_hour"),
        )].append(index)
    for indexes in grouped.values():
        weights = [
            max(1e-12, float(output[index]["model_probability"])) ** gamma
            for index in indexes
        ]
        total = sum(weights)
        if total <= 0:
            continue
        for index, weight in zip(indexes, weights):
            output[index]["model_probability"] = weight / total
    return output


def normal_cdf(value, mean_value, sigma):
    sigma = max(0.05, float(sigma))
    z = (float(value) - float(mean_value)) / (sigma * math.sqrt(2.0))
    return 0.5 * (1.0 + math.erf(z))


def forecast_anchor_probability(row, sigma=FORECAST_CENTERING_SIGMA):
    forecast_high = first_present(
        row,
        "feature_forecast_high",
        "raw_weather_forecast_max_c",
        "raw_open_meteo_max_c",
    )
    value = safe_float(row.get("bin_value_c"))
    value_hi = safe_float(row.get("bin_value_hi"))
    if forecast_high is None or value is None:
        return None
    forecast_high = safe_float(forecast_high)
    if forecast_high is None:
        return None
    value_hi = value if value_hi is None else value_hi
    kind = row.get("bin_type") or row.get("bin_kind") or "eq"
    if kind == "lte":
        probability = normal_cdf(value + 0.5, forecast_high, sigma)
    elif kind == "gte":
        probability = 1.0 - normal_cdf(value - 0.5, forecast_high, sigma)
    else:
        lo = min(value, value_hi)
        hi = max(value, value_hi)
        probability = normal_cdf(hi + 0.5, forecast_high, sigma) - normal_cdf(lo - 0.5, forecast_high, sigma)
    return clamp_probability(probability)


def forecast_centering_rows(rows, alpha):
    """Blend model probabilities toward a forecast-high anchored band projection.

    This is a no-market probe for Item 147. It uses only serve-time forecast
    geometry, not outcomes or market prices, to test whether early-hour failure
    is mostly poor centering around the forecast anchor.
    """
    alpha = max(0.0, min(1.0, float(alpha)))
    def probability(row):
        anchor_probability = forecast_anchor_probability(row)
        if anchor_probability is None:
            return float(row["model_probability"])
        return (1.0 - alpha) * float(row["model_probability"]) + alpha * float(anchor_probability)

    return rows_with_probability(rows, probability)


def score_variant_by_hour(rows, transform_fn, parameter_values):
    by_hour_rows = rows_for_group(rows, "cutoff_hour")
    output = []
    for hour, hour_rows in sorted(by_hour_rows.items(), key=lambda item: int(item[0]) if item[0] is not None else 99):
        if hour is None:
            continue
        base = score_rows(hour_rows)
        if not base:
            continue
        variants = []
        for value in parameter_values:
            variant_rows = transform_fn(hour_rows, value)
            score = score_rows(variant_rows)
            if not score:
                continue
            variants.append({
                "parameter": value,
                "model_brier": score["model_brier"],
                "model_logloss": score["model_logloss"],
                "brier_delta_vs_base": score["model_brier"] - base["model_brier"],
                "logloss_delta_vs_base": score["model_logloss"] - base["model_logloss"],
            })
        if variants:
            best = min(variants, key=lambda row: (row["model_brier"], row["model_logloss"]))
            output.append({
                "hour": int(hour),
                "hour_label": f"{int(hour):02d}:00",
                "base_model_brier": base["model_brier"],
                "base_model_logloss": base["model_logloss"],
                "best": best,
                "variants": variants,
            })
    return output


def remediation_candidates(rows):
    market_blend = score_variant_by_hour(
        rows,
        lambda hour_rows, alpha: market_blend_rows(hour_rows, alpha),
        MARKET_BLEND_GRID,
    )
    partition_power = score_variant_by_hour(
        rows,
        lambda hour_rows, gamma: partition_power_rows(hour_rows, gamma),
        PARTITION_POWER_GRID,
    )
    forecast_centering = score_variant_by_hour(
        rows,
        lambda hour_rows, alpha: forecast_centering_rows(hour_rows, alpha),
        FORECAST_CENTERING_BLEND_GRID,
    )
    early_hours = {0, 1, 2, 3, 4, 5, 6, 7, 8}
    return {
        "market_blend": {
            "description": "Blend model probability toward market yes price: (1-alpha)*model + alpha*market.",
            "uses_market_prices": True,
            "grid": list(MARKET_BLEND_GRID),
            "by_hour": market_blend,
            "early_hours": [row for row in market_blend if row["hour"] in early_hours],
        },
        "partition_power": {
            "description": "Normalize each snapshot partition after p**gamma; gamma < 1 softens, gamma > 1 sharpens.",
            "uses_market_prices": False,
            "grid": list(PARTITION_POWER_GRID),
            "by_hour": partition_power,
            "early_hours": [row for row in partition_power if row["hour"] in early_hours],
        },
        "forecast_centering": {
            "description": (
                "Blend model probability toward a forecast-high anchored Gaussian "
                "band projection; no market prices are used."
            ),
            "uses_market_prices": False,
            "grid": list(FORECAST_CENTERING_BLEND_GRID),
            "sigma": FORECAST_CENTERING_SIGMA,
            "by_hour": forecast_centering,
            "early_hours": [row for row in forecast_centering if row["hour"] in early_hours],
        },
    }

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]
