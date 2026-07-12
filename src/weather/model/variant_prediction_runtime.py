"""Serving-safe runtime helpers for pooled variant prediction artifacts."""

from __future__ import annotations

import bisect
import math
import warnings
from collections import defaultdict

import numpy as np
import pandas as pd

from weather.market.market_microstructure_features import CLOB_MODEL_FEATURE_COLUMNS
from weather.market.market_registry import spec_for_id
from weather.model.calibration_runtime import (
    apply_continuous_density_calibration,
    clip_probability,
    sigmoid,
)
from weather.model.continuous_density import (
    band_probability_from_distribution as density_band_probability_from_distribution,
    bucket_interval_native,
    canonical_grid_f,
    continuous_density_payload,
    density_f_from_payload,
    native_interval_to_f,
    normalize_density,
)
from weather.model.feature_store import FEATURE_COLUMNS
from weather.units import round_half_up


DYNAMIC_SOURCE_NUMERIC_COLUMNS = [
    "source_state_all_fresh",
    "source_state_missing_sources",
    "source_failed_count",
    "source_stale_count",
    "source_unknown_count",
    "source_wu_history_fresh",
    "source_wu_history_stale",
    "source_wu_history_failed",
    "source_wu_history_age_minutes",
    "source_wu_history_latest_minute",
    "source_wu_history_row_count",
    "source_metar_stale",
    "source_metar_failed",
    "source_metar_age_minutes",
    "source_forecast_failed_count",
    "source_forecast_stale_count",
    "source_forecast_payload_age_minutes",
    "source_forecast_max_age_minutes",
    "source_cross_source_max_disagreement",
]
DYNAMIC_SOURCE_CATEGORICAL_COLUMNS = ["source_status_group"]
BAND_NUMERIC_COLUMNS = [
    "band_value",
    "band_value_hi",
    "band_width",
    "band_mid",
    "band_minus_high_so_far",
    "band_hi_minus_high_so_far",
    "band_mid_minus_high_so_far",
    "band_mid_minus_forecast",
    "band_mid_minus_live_reading",
    "band_mid_anomaly",
    "band_below_floor",
    "band_contains_floor",
    "band_above_floor",
    "late_lockin_strength",
    *CLOB_MODEL_FEATURE_COLUMNS,
]
SOURCE_RELIABILITY_COLUMNS = [
    "source_redundant_streams",
    "source_overlap_days",
    "source_best_bucket_match",
    "source_best_mae",
    "source_metar_bias",
    "source_metar_mae",
    "source_metar_bucket_match",
    "source_ghcnh_bias",
    "source_ghcnh_mae",
    "source_ghcnh_bucket_match",
    "source_reanalysis_bias",
    "source_reanalysis_mae",
    "source_reanalysis_bucket_match",
]
HISTORICAL_ONLY_SOURCE_RELIABILITY_COLUMNS = [
    "source_supplemental_available",
    "source_supplemental_count",
    "source_supplemental_overlap_days",
    "source_supplemental_best_mae",
    "source_supplemental_best_bucket_match",
    "source_supplemental_min_distance_km",
]
CANONICAL_F_ABSOLUTE_COLUMNS = (
    "high_so_far",
    "current_temp",
    "dewpoint_c",
    "forecast_high",
    "live_reading_temp",
    "latest_wu_history_temp",
    "observed_floor_bucket",
    "observed_support_bucket",
    "climate_normal",
)
CANONICAL_F_DELTA_COLUMNS = (
    "rise_from_7am",
    "warming_rate_2h",
    "forecast_gap",
    "live_reading_minus_high",
    "forecast_disagreement",
    "high_so_far_anomaly",
    "forecast_anomaly",
    "climate_std",
)
DENSITY_DEFAULT_SHAPE = {"shape": "gaussian", "id": "gaussian"}
MICROSTRUCTURE_NUMERIC_FEATURES = [
    "candidate_p",
    "replayed_p",
    "recorded_p",
    "market_yes",
    "candidate_logit",
    "replayed_logit",
    "market_logit",
    "candidate_minus_market",
    "candidate_minus_replayed",
    "replayed_minus_market",
    "abs_candidate_minus_market",
    "candidate_cutoff_hour",
    *CLOB_MODEL_FEATURE_COLUMNS,
]
MICROSTRUCTURE_CATEGORICAL_FEATURES = [
    "market_id",
    "bin_type",
    "candidate_cutoff_hour_bucket",
]


def feature_names_need_dynamic_source_state(feature_names):
    if not feature_names:
        return False
    dynamic_names = set(DYNAMIC_SOURCE_NUMERIC_COLUMNS + DYNAMIC_SOURCE_CATEGORICAL_COLUMNS)
    return any(
        name in dynamic_names or str(name).startswith("source_status_group_")
        for name in feature_names
    )


def finite_float(value):
    if value in (None, ""):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def temperature_scale_probability(value, temperature=1.0):
    value = clip_probability(value)
    temperature = max(0.05, float(temperature or 1.0))
    logit = math.log(value / (1.0 - value))
    return clip_probability(sigmoid(logit / temperature))


def late_lockin_strength_from_features(record):
    try:
        hour = int(record.get("cutoff_hour"))
    except (TypeError, ValueError):
        return 0.0
    high = record.get("high_so_far")
    current = record.get("live_reading_temp")
    if current is None:
        current = record.get("current_temp")
    if high is None or current is None:
        return 0.0
    try:
        high = float(high)
        current = float(current)
    except (TypeError, ValueError):
        return 0.0
    if hour <= 15:
        time_factor = 0.0
    elif hour >= 17:
        time_factor = 1.0
    else:
        time_factor = (hour - 15) / 2.0
    drop = high - current
    if drop <= 0:
        peak_factor = 0.0
    elif drop >= 2.0:
        peak_factor = 1.0
    else:
        peak_factor = drop / 2.0
    return max(0.0, min(1.0, time_factor * peak_factor))


def band_outcome(kind, value, final_bucket, value_hi=None):
    if value is None or final_bucket is None:
        return None
    try:
        lo = int(float(value))
        hi = int(float(value_hi)) if value_hi is not None else lo
        final = int(float(final_bucket))
    except (TypeError, ValueError):
        return None
    if kind == "lte":
        return 1 if final <= lo else 0
    if kind == "gte":
        return 1 if final >= lo else 0
    return 1 if lo <= final <= hi else 0


def hard_floor_probability(kind, value, floor_bucket, value_hi=None):
    if floor_bucket is None or value is None:
        return None
    try:
        floor_bucket = int(float(floor_bucket))
        lo = int(float(value))
        hi = int(float(value_hi)) if value_hi is not None else lo
    except (TypeError, ValueError):
        return None
    if kind == "gte" and floor_bucket >= lo:
        return 1.0
    if kind == "lte" and floor_bucket > lo:
        return 0.0
    if kind not in {"gte", "lte"} and hi < floor_bucket:
        return 0.0
    return None


def support_floor_cap(kind, value, support_bucket, value_hi=None, one_below_cap=0.08, decay=0.25):
    if support_bucket is None or value is None:
        return None
    try:
        support_bucket = int(float(support_bucket))
        lo = int(float(value))
        hi = int(float(value_hi)) if value_hi is not None else lo
    except (TypeError, ValueError):
        return None
    if kind == "gte" and support_bucket >= lo:
        return None
    if kind == "lte" and support_bucket > lo:
        gap = max(1, support_bucket - lo)
        return float(one_below_cap) * (float(decay) ** (gap - 1))
    if kind not in {"gte", "lte"} and hi < support_bucket:
        gap = max(1, support_bucket - hi)
        return float(one_below_cap) * (float(decay) ** (gap - 1))
    return None


def late_lockin_target(kind, value, floor_bucket, value_hi=None):
    if floor_bucket is None:
        return None
    return float(band_outcome(kind, value, floor_bucket, value_hi=value_hi))


def native_value_to_f(value, unit):
    if value in (None, ""):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value * 9.0 / 5.0 + 32.0 if str(unit).upper() == "C" else value


def native_delta_to_f(value, unit):
    if value in (None, ""):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value * 9.0 / 5.0 if str(unit).upper() == "C" else value


def record_unit(record):
    explicit = (record or {}).get("unit") or (record or {}).get("display_unit")
    if explicit:
        return str(explicit).upper()
    return spec_for_id((record or {}).get("market_id")).display_unit


def canonical_density_record(record):
    out = dict(record or {})
    unit = record_unit(record)
    out["native_unit"] = unit
    out["final_bucket_f"] = native_value_to_f(out.get("final_bucket"), unit)
    for column in CANONICAL_F_ABSOLUTE_COLUMNS:
        if column in out:
            out[column] = native_value_to_f(out.get(column), unit)
    for column in CANONICAL_F_DELTA_COLUMNS:
        if column in out:
            out[column] = native_delta_to_f(out.get(column), unit)
    return out


def canonical_density_records(records):
    return [canonical_density_record(record) for record in records or []]


def feature_frame(
    records,
    feature_names=None,
    include_historical_only=False,
    include_dynamic_source_state=False,
):
    frame = pd.DataFrame(records)
    include_dynamic_source_state = (
        include_dynamic_source_state or feature_names_need_dynamic_source_state(feature_names)
    )
    base_numeric = [
        column for column in FEATURE_COLUMNS
        if column not in ("wind_group", "cloud_group")
    ]
    city_numeric = [
        "latitude",
        "longitude",
        "coastal",
        "climate_normal",
        "climate_std",
        "high_so_far_anomaly",
        "forecast_anomaly",
        *SOURCE_RELIABILITY_COLUMNS,
    ]
    if include_historical_only:
        city_numeric += HISTORICAL_ONLY_SOURCE_RELIABILITY_COLUMNS
    if include_dynamic_source_state:
        city_numeric += DYNAMIC_SOURCE_NUMERIC_COLUMNS
    categorical = ["wind_group", "cloud_group", "market_id"]
    if include_dynamic_source_state:
        categorical += DYNAMIC_SOURCE_CATEGORICAL_COLUMNS
    use = base_numeric + city_numeric + categorical
    frame = frame.reindex(columns=use).copy()
    features = pd.get_dummies(frame, columns=categorical, dtype=float)
    if feature_names is not None:
        features = features.reindex(columns=feature_names, fill_value=0.0)
    return features


def band_prediction_record(record, kind, value, value_hi=None):
    out = dict(record)
    kind = kind or "eq"
    try:
        lo = float(value)
        hi = float(value_hi) if value_hi is not None else lo
    except (TypeError, ValueError):
        lo = None
        hi = None
    high_so_far = record.get("high_so_far")
    forecast_high = record.get("forecast_high")
    live_reading = record.get("live_reading_temp")
    if live_reading is None:
        live_reading = record.get("current_temp")
    normal = record.get("climate_normal")
    floor_bucket = round_half_up(high_so_far)
    support_bucket = record.get("observed_support_bucket")
    if support_bucket is None:
        support_bucket = floor_bucket
    else:
        support_bucket = round_half_up(support_bucket)
    mid = ((lo + hi) / 2.0) if lo is not None and hi is not None else None

    def diff(left, right):
        if left is None or right is None:
            return None
        try:
            return float(left) - float(right)
        except (TypeError, ValueError):
            return None

    out.update({
        "band_kind": kind,
        "band_value": lo,
        "band_value_hi": hi,
        "band_width": (hi - lo + 1.0) if lo is not None and hi is not None else None,
        "band_mid": mid,
        "band_minus_high_so_far": diff(lo, high_so_far),
        "band_hi_minus_high_so_far": diff(hi, high_so_far),
        "band_mid_minus_high_so_far": diff(mid, high_so_far),
        "band_mid_minus_forecast": diff(mid, forecast_high),
        "band_mid_minus_live_reading": diff(mid, live_reading),
        "band_mid_anomaly": diff(mid, normal),
        "band_below_floor": (
            1.0 if hi is not None and floor_bucket is not None and hi < floor_bucket else 0.0
        ),
        "band_contains_floor": (
            1.0 if lo is not None and hi is not None and floor_bucket is not None
            and lo <= floor_bucket <= hi else 0.0
        ),
        "band_above_floor": (
            1.0 if lo is not None and floor_bucket is not None and lo > floor_bucket else 0.0
        ),
        "late_lockin_strength": late_lockin_strength_from_features(record),
        "observed_floor_bucket": floor_bucket,
        "observed_support_bucket": support_bucket,
    })
    return out


def band_feature_frame(
    records,
    feature_names=None,
    include_historical_only=False,
    include_dynamic_source_state=False,
):
    frame = pd.DataFrame(records)
    include_dynamic_source_state = (
        include_dynamic_source_state or feature_names_need_dynamic_source_state(feature_names)
    )
    base_numeric = [
        column for column in FEATURE_COLUMNS
        if column not in ("wind_group", "cloud_group")
    ]
    city_numeric = [
        "latitude",
        "longitude",
        "coastal",
        "climate_normal",
        "climate_std",
        "high_so_far_anomaly",
        "forecast_anomaly",
        *SOURCE_RELIABILITY_COLUMNS,
    ]
    if include_historical_only:
        city_numeric += HISTORICAL_ONLY_SOURCE_RELIABILITY_COLUMNS
    if include_dynamic_source_state:
        city_numeric += DYNAMIC_SOURCE_NUMERIC_COLUMNS
    categorical = ["wind_group", "cloud_group", "market_id", "band_kind"]
    if include_dynamic_source_state:
        categorical += DYNAMIC_SOURCE_CATEGORICAL_COLUMNS
    use = base_numeric + city_numeric + BAND_NUMERIC_COLUMNS + categorical
    frame = frame.reindex(columns=use).copy()
    if feature_names is None:
        use = [
            column for column in use
            if column not in CLOB_MODEL_FEATURE_COLUMNS or not frame[column].isna().all()
        ]
    features = pd.get_dummies(
        frame[use],
        columns=categorical,
        dtype=float,
    )
    if feature_names is not None:
        features = features.reindex(columns=feature_names, fill_value=0.0)
    return features


def predict_band_probabilities(model, imputer, feature_names, rows, temperature=1.0):
    if not rows:
        return []
    frame = band_feature_frame(rows, feature_names=feature_names)
    x_eval = imputer.transform(frame)
    probabilities = model.predict_proba(x_eval)
    classes = [int(value) for value in model.classes_]
    if 1 not in classes:
        return [1.0 if classes and classes[0] == 1 else 0.0 for _ in rows]
    idx = classes.index(1)
    return [
        temperature_scale_probability(float(row[idx]), temperature=temperature)
        for row in probabilities
    ]


def normal_cdf(value, mean_value, sigma):
    sigma = max(0.05, float(sigma or 1.0))
    z = (float(value) - float(mean_value)) / (sigma * math.sqrt(2.0))
    return 0.5 * (1.0 + math.erf(z))


def forecast_anchor_probability(row, sigma=1.25):
    forecast_high = finite_float((row or {}).get("forecast_high"))
    value = finite_float((row or {}).get("band_value"))
    value_hi = finite_float((row or {}).get("band_value_hi"))
    if forecast_high is None or value is None:
        return None
    value_hi = value if value_hi is None else value_hi
    kind = (row or {}).get("band_kind") or "eq"
    if kind == "lte":
        probability = normal_cdf(value + 0.5, forecast_high, sigma)
    elif kind == "gte":
        probability = 1.0 - normal_cdf(value - 0.5, forecast_high, sigma)
    else:
        lo = min(value, value_hi)
        hi = max(value, value_hi)
        probability = normal_cdf(hi + 0.5, forecast_high, sigma) - normal_cdf(lo - 0.5, forecast_high, sigma)
    return clip_probability(probability)


def forecast_centering_alpha(row, config=None):
    config = config or {}
    try:
        hour = int(float((row or {}).get("cutoff_hour") or (row or {}).get("candidate_cutoff_hour")))
    except (TypeError, ValueError):
        hour = None
    alpha_by_hour = config.get("forecast_centering_alpha_by_hour") or {}
    if hour is not None and str(hour) in alpha_by_hour:
        return max(0.0, min(1.0, float(alpha_by_hour[str(hour)])))
    if hour is not None and hour in alpha_by_hour:
        return max(0.0, min(1.0, float(alpha_by_hour[hour])))
    if hour is not None and 0 <= hour <= 8:
        return max(0.0, min(1.0, float(config.get("forecast_centering_early_alpha", 0.0))))
    return max(0.0, min(1.0, float(config.get("forecast_centering_default_alpha", 0.0))))


def apply_forecast_centering(probability, row, config=None):
    config = config or {}
    alpha = forecast_centering_alpha(row, config=config)
    if alpha <= 0.0:
        return clip_probability(probability)
    anchor = forecast_anchor_probability(
        row,
        sigma=float(config.get("forecast_centering_sigma", 1.25)),
    )
    if anchor is None:
        return clip_probability(probability)
    return clip_probability((1.0 - alpha) * float(probability) + alpha * float(anchor))


def calibration_hour_bucket(hour):
    try:
        hour = int(hour)
    except (TypeError, ValueError):
        return "na"
    if hour <= 8:
        return "07-08"
    if hour <= 13:
        return "09-13"
    if hour <= 16:
        return "14-16"
    return "17-20"


def calibration_gap_bucket(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "na"
    if value < -0.5:
        return "below"
    if value < 0.5:
        return "0"
    if value < 1.5:
        return "+1"
    if value < 2.5:
        return "+2"
    if value < 3.5:
        return "+3"
    return "+4"


def _band_width_label(row):
    try:
        lo = float(row.get("band_value"))
        hi = float(row.get("band_value_hi"))
    except (TypeError, ValueError):
        return "single"
    return "range" if hi > lo else "single"


def adjacent_calibration_contexts(row):
    if row.get("band_kind") != "eq":
        return []
    try:
        if float(row.get("band_contains_floor") or 0.0) >= 0.5:
            return []
        if float(row.get("band_below_floor") or 0.0) >= 0.5:
            return []
    except (TypeError, ValueError):
        return []
    market_id = row.get("market_id") or "unknown"
    hour_bucket = calibration_hour_bucket(row.get("cutoff_hour") or row.get("candidate_cutoff_hour"))
    floor_gap = calibration_gap_bucket(row.get("band_mid_minus_high_so_far"))
    width = _band_width_label(row)
    return [
        f"market={market_id}|hour={hour_bucket}|width={width}|floor_gap={floor_gap}",
        f"market={market_id}|hour={hour_bucket}|floor_gap={floor_gap}",
        f"market={market_id}|floor_gap={floor_gap}",
        f"hour={hour_bucket}|floor_gap={floor_gap}",
        f"floor_gap={floor_gap}",
    ]


def adjacent_calibration_factor(row, config=None):
    config = config or {}
    calibration = config.get("adjacent_calibration") or config
    contexts = calibration.get("contexts") or {}
    if not contexts:
        return 1.0
    for context in adjacent_calibration_contexts(row):
        entry = contexts.get(context)
        if entry is None:
            continue
        if isinstance(entry, dict):
            return float(entry.get("factor", 1.0))
        return float(entry)
    return 1.0


def apply_adjacent_calibration(probability, row, config=None):
    factor = adjacent_calibration_factor(row, config=config)
    if factor == 1.0:
        return clip_probability(probability)
    return clip_probability(float(probability) * factor)


def market_bias_calibration_contexts(row):
    market_id = row.get("market_id") or "unknown"
    kind = row.get("band_kind") or "unknown"
    hour_bucket = calibration_hour_bucket(row.get("cutoff_hour") or row.get("candidate_cutoff_hour"))
    return [
        f"market={market_id}|hour={hour_bucket}|kind={kind}",
        f"market={market_id}|kind={kind}",
        f"market={market_id}|hour={hour_bucket}",
        f"market={market_id}",
    ]


def market_bias_calibration_factor(row, config=None):
    config = config or {}
    calibration = config.get("market_bias_calibration") or config
    if not calibration.get("enabled", False):
        return 1.0
    excluded_markets = set(calibration.get("excluded_markets") or [])
    if row.get("market_id") in excluded_markets:
        return 1.0
    allowed_source_states = set(calibration.get("allowed_source_freshness_states") or [])
    if allowed_source_states:
        source_state = row.get("source_freshness_state") or row.get("source_status_group") or "unknown"
        if source_state not in allowed_source_states:
            return 1.0
    contexts = calibration.get("contexts") or {}
    if not contexts:
        return 1.0
    for context in market_bias_calibration_contexts(row):
        entry = contexts.get(context)
        if entry is None:
            continue
        if isinstance(entry, dict):
            return float(entry.get("factor", 1.0))
        return float(entry)
    return 1.0


def apply_market_bias_calibration(probability, row, config=None):
    factor = market_bias_calibration_factor(row, config=config)
    if factor == 1.0:
        return clip_probability(probability)
    return clip_probability(float(probability) * factor)


def source_trust_bucket(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "na"
    if value < 0.34:
        return "low"
    if value < 0.67:
        return "mid"
    return "high"


def exact_winner_catchup_contexts(row):
    if row.get("band_kind") != "eq":
        return []
    try:
        if float(row.get("band_below_floor") or 0.0) >= 0.5:
            return []
    except (TypeError, ValueError):
        return []
    market_id = row.get("market_id") or "unknown"
    hour_bucket = calibration_hour_bucket(row.get("cutoff_hour") or row.get("candidate_cutoff_hour"))
    floor_gap = calibration_gap_bucket(row.get("band_mid_minus_high_so_far"))
    forecast_gap = calibration_gap_bucket(row.get("band_mid_minus_forecast"))
    width = _band_width_label(row)
    source_bucket = source_trust_bucket(row.get("source_best_bucket_match"))
    source_state = row.get("source_freshness_state") or row.get("source_status_group") or "na"
    return [
        (
            f"market={market_id}|hour={hour_bucket}|width={width}|"
            f"floor_gap={floor_gap}|forecast_gap={forecast_gap}|"
            f"source_trust={source_bucket}|source_state={source_state}"
        ),
        (
            f"market={market_id}|hour={hour_bucket}|width={width}|"
            f"floor_gap={floor_gap}|forecast_gap={forecast_gap}|source_trust={source_bucket}"
        ),
        f"market={market_id}|hour={hour_bucket}|floor_gap={floor_gap}|forecast_gap={forecast_gap}",
        f"market={market_id}|floor_gap={floor_gap}|forecast_gap={forecast_gap}",
        f"hour={hour_bucket}|floor_gap={floor_gap}|forecast_gap={forecast_gap}",
        f"floor_gap={floor_gap}|forecast_gap={forecast_gap}",
        f"floor_gap={floor_gap}",
    ]


def exact_winner_catchup_factor(row, config=None):
    config = config or {}
    calibration = config.get("exact_winner_catchup") or config
    contexts = calibration.get("contexts") or {}
    if not contexts:
        return 1.0
    try:
        strength = max(0.0, min(1.0, float(calibration.get("strength", 1.0))))
    except (TypeError, ValueError):
        strength = 1.0
    for context in exact_winner_catchup_contexts(row):
        entry = contexts.get(context)
        if entry is None:
            continue
        if isinstance(entry, dict):
            factor = float(entry.get("factor", 1.0))
        else:
            factor = float(entry)
        return 1.0 + strength * (factor - 1.0)
    return 1.0


def apply_exact_winner_catchup(probability, row, config=None):
    factor = exact_winner_catchup_factor(row, config=config)
    if factor == 1.0:
        return clip_probability(probability)
    return clip_probability(float(probability) * factor)


def density_forecast_source_count_bucket(value):
    try:
        value = int(float(value))
    except (TypeError, ValueError):
        return "unknown"
    if value <= 1:
        return "low_count"
    if value == 2:
        return "two_sources"
    return "three_plus_sources"


def density_forecast_disagreement_bucket(value):
    try:
        value = abs(float(value))
    except (TypeError, ValueError):
        return "unknown"
    if value < 1.0:
        return "low_disagreement"
    if value < 2.5:
        return "moderate_disagreement"
    return "high_disagreement"


def density_forecast_pressure_bucket(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "unknown"
    if value <= -1.0:
        return "cool_side"
    if value >= 1.0:
        return "warm_side"
    return "near_forecast"


def density_forecast_relative_contexts(row):
    """Serve-time context fallbacks for density projection calibration."""
    market_id = row.get("market_id") or "unknown"
    kind = row.get("band_kind") or "unknown"
    width = _band_width_label(row)
    hour_bucket = calibration_hour_bucket(row.get("cutoff_hour") or row.get("candidate_cutoff_hour"))
    pressure = density_forecast_pressure_bucket(row.get("band_mid_minus_forecast"))
    disagreement = density_forecast_disagreement_bucket(row.get("forecast_disagreement"))
    source_count = density_forecast_source_count_bucket(row.get("forecast_source_count"))
    floor_gap = calibration_gap_bucket(row.get("band_mid_minus_high_so_far"))
    return [
        (
            f"market={market_id}|hour={hour_bucket}|kind={kind}|width={width}|"
            f"pressure={pressure}|disagreement={disagreement}|source_count={source_count}|"
            f"floor_gap={floor_gap}"
        ),
        (
            f"market={market_id}|hour={hour_bucket}|kind={kind}|"
            f"pressure={pressure}|disagreement={disagreement}|source_count={source_count}"
        ),
        (
            f"market={market_id}|kind={kind}|pressure={pressure}|"
            f"disagreement={disagreement}|source_count={source_count}"
        ),
        f"hour={hour_bucket}|kind={kind}|pressure={pressure}|disagreement={disagreement}",
        f"kind={kind}|pressure={pressure}|disagreement={disagreement}",
        f"pressure={pressure}|disagreement={disagreement}",
        f"pressure={pressure}",
    ]


def forecast_relative_density_factor(row, config=None):
    config = config or {}
    calibration = config.get("forecast_relative_calibration") or config
    contexts = calibration.get("contexts") or {}
    if not contexts:
        return 1.0
    for context in density_forecast_relative_contexts(row):
        entry = contexts.get(context)
        if entry is None:
            continue
        if isinstance(entry, dict):
            return float(entry.get("factor", 1.0))
        return float(entry)
    return 1.0


def apply_forecast_relative_density_calibration(probability, row, config=None):
    config = config or {}
    calibration = config.get("forecast_relative_calibration") or config
    factor = forecast_relative_density_factor(
        row,
        config={"forecast_relative_calibration": calibration},
    )
    strength = max(0.0, min(1.0, float(calibration.get("strength", 1.0))))
    if factor == 1.0 or strength <= 0.0:
        return clip_probability(probability)
    return clip_probability(float(probability) * (float(factor) ** strength))


def apply_density_band_postprocessing(probability, row, config=None):
    """Apply the density-specific replay postprocessors in canonical order."""
    config = config or {}
    if not config.get("enabled"):
        return max(0.0, min(1.0, float(probability)))
    probability = clip_probability(probability)
    if config.get("adjacent_calibration_enabled", False):
        probability = apply_adjacent_calibration(
            probability,
            row,
            config={"adjacent_calibration": config.get("adjacent_calibration") or {}},
        )
    if config.get("exact_winner_catchup_enabled", False):
        probability = apply_exact_winner_catchup(
            probability,
            row,
            config={"exact_winner_catchup": config.get("exact_winner_catchup") or {}},
        )
    if config.get("forecast_relative_calibration_enabled", False):
        probability = apply_forecast_relative_density_calibration(
            probability,
            row,
            config={
                "forecast_relative_calibration": (
                    config.get("forecast_relative_calibration") or {}
                ),
            },
        )
    return clip_probability(probability)


def apply_band_postprocessing(probability, row, config=None):
    config = config or {}
    kind = row.get("band_kind")
    value = row.get("band_value")
    value_hi = row.get("band_value_hi")
    floor_bucket = row.get("observed_floor_bucket")
    hard = hard_floor_probability(kind, value, floor_bucket, value_hi=value_hi)
    if hard is not None:
        return hard
    p = clip_probability(probability)
    if config.get("support_floor_enabled", True):
        cap = support_floor_cap(
            kind,
            value,
            row.get("observed_support_bucket"),
            value_hi=value_hi,
            one_below_cap=config.get("support_floor_one_below_cap", 0.08),
            decay=config.get("support_floor_decay", 0.25),
        )
        if cap is not None:
            p = min(p, clip_probability(cap))
    if config.get("late_lockin_enabled", True):
        strength = max(0.0, min(1.0, float(row.get("late_lockin_strength") or 0.0)))
        if strength > 0:
            target = late_lockin_target(kind, value, floor_bucket, value_hi=value_hi)
            if target is not None:
                max_strength = max(0.0, min(1.0, float(config.get("late_lockin_max_strength", 0.85))))
                effective = min(strength, max_strength)
                p = clip_probability((1.0 - effective) * p + effective * target)
    if config.get("adjacent_calibration_enabled", False):
        p = apply_adjacent_calibration(p, row, config=config)
    if config.get("exact_winner_catchup_enabled", False):
        p = apply_exact_winner_catchup(p, row, config=config)
    if config.get("forecast_centering_enabled", False):
        p = apply_forecast_centering(p, row, config=config)
    if config.get("market_bias_calibration_enabled", False):
        p = apply_market_bias_calibration(p, row, config=config)
    return clip_probability(p)


def predict_band_rows_for_bundle(bundle, rows, postprocess=True):
    probabilities = predict_band_probabilities(
        bundle["model"],
        bundle["imputer"],
        bundle["feature_names"],
        rows,
        temperature=bundle.get("temperature", 1.0),
    )
    if not postprocess:
        return probabilities
    config = bundle.get("postprocess") or {}
    return [
        apply_band_postprocessing(probability, row, config=config)
        for row, probability in zip(rows, probabilities)
    ]


def density_shape_config(shape_config=None):
    cfg = dict(DENSITY_DEFAULT_SHAPE)
    if isinstance(shape_config, dict):
        cfg.update({
            key: value
            for key, value in shape_config.items()
            if value is not None
        })
    shape = str(cfg.get("shape") or "gaussian")
    if shape not in {"gaussian", "tail_mixture", "anchor_mixture"}:
        shape = "gaussian"
    cfg["shape"] = shape
    cfg["id"] = str(cfg.get("id") or shape)
    return cfg


def density_shape_components(rows, means_array, sigma_f, shape_config=None):
    cfg = density_shape_config(shape_config)
    sigma = max(0.1, float(sigma_f or 1.0))
    base_weight = 1.0
    components = []

    def add_component(weight, centers, sigma_scale):
        weight = max(0.0, min(0.95, float(weight or 0.0)))
        sigma_scale = max(0.05, float(sigma_scale or 1.0))
        if weight <= 0:
            return
        components.append((weight, np.asarray(centers, dtype=float), sigma * sigma_scale))

    if cfg["shape"] == "tail_mixture":
        tail_weight = max(0.0, min(0.80, float(cfg.get("tail_weight") or 0.0)))
        base_weight -= tail_weight
        add_component(tail_weight, means_array, cfg.get("tail_scale") or 2.0)
    elif cfg["shape"] == "anchor_mixture":
        anchor_weight = max(0.0, min(0.80, float(cfg.get("anchor_weight") or 0.0)))
        anchor = cfg.get("anchor")
        anchor_values = []
        for row, mean_f in zip(rows or [], means_array):
            anchor_value = finite_float((row or {}).get(anchor))
            anchor_values.append(float(mean_f) if anchor_value is None else anchor_value)
        base_weight -= anchor_weight
        add_component(anchor_weight, anchor_values, cfg.get("anchor_sigma_scale") or 1.0)

    components.insert(0, (max(0.0, base_weight), np.asarray(means_array, dtype=float), sigma))
    total_weight = sum(component[0] for component in components)
    if total_weight <= 0:
        return [(1.0, np.asarray(means_array, dtype=float), sigma)]
    return [
        (weight / total_weight, centers, component_sigma)
        for weight, centers, component_sigma in components
        if weight > 0
    ]


def density_weight_matrix(rows, means_array, grid, sigma_f, shape_config=None):
    matrix = None
    for weight, centers, component_sigma in density_shape_components(
        rows,
        means_array,
        sigma_f,
        shape_config=shape_config,
    ):
        with np.errstate(over="ignore", under="ignore", invalid="ignore"):
            component = np.exp(-0.5 * ((grid[None, :] - centers[:, None]) / component_sigma) ** 2)
        matrix = component * weight if matrix is None else matrix + component * weight
    return matrix if matrix is not None else np.zeros((len(means_array), len(grid)), dtype=float)


def gaussian_density_f(mean_f, sigma_f, grid_f, shape_config=None, row=None):
    sigma_f = max(0.1, float(sigma_f or 1.0))
    grid = np.asarray([float(value) for value in grid_f], dtype=float)
    weights = density_weight_matrix(
        [row or {}],
        np.asarray([float(mean_f)], dtype=float),
        grid,
        sigma_f,
        shape_config=shape_config,
    )[0]
    density = {float(value): float(weight) for value, weight in zip(grid, weights)}
    shape_cfg = density_shape_config(shape_config)
    payload = continuous_density_payload(density, mean_f=float(mean_f), sigma_f=sigma_f)
    payload["density_shape_id"] = shape_cfg["id"]
    payload["density_shape"] = shape_cfg
    return payload


def predict_density_means(model, imputer, feature_names, rows):
    if not rows:
        return []
    frame = feature_frame(rows, feature_names=feature_names)
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Skipping features without any observed values",
            category=UserWarning,
        )
        x_eval = imputer.transform(frame)
    return [float(value) for value in model.predict(x_eval)]


def predict_density_payloads(model, imputer, feature_names, rows, sigma_f, grid_f, shape_config=None):
    means = predict_density_means(model, imputer, feature_names, rows)
    return [
        gaussian_density_f(mean, sigma_f, grid_f, shape_config=shape_config, row=row)
        for mean, row in zip(means, rows or [])
    ]


def predict_density_rows_for_bundle(bundle, rows):
    if not bundle or not rows:
        return []
    rows = canonical_density_records(rows)
    grid_f = canonical_grid_f(
        bundle.get("grid_low_f", 30.0),
        bundle.get("grid_high_f", 125.0),
        bundle.get("grid_step_f", 0.1),
    )
    output = [None] * len(rows)
    by_hour = defaultdict(list)
    for index, row in enumerate(rows):
        try:
            hour = str(int(row.get("cutoff_hour")))
        except (TypeError, ValueError):
            continue
        by_hour[hour].append((index, row))
    for hour, indexed_rows in by_hour.items():
        model_bundle = (bundle.get("models") or {}).get(hour)
        if not model_bundle:
            continue
        payloads = predict_density_payloads(
            model_bundle["model"],
            model_bundle["imputer"],
            model_bundle["feature_names"],
            [row for _, row in indexed_rows],
            model_bundle.get("sigma_f", 3.0),
            grid_f,
            shape_config=model_bundle.get("density_shape"),
        )
        for (index, _row), payload in zip(indexed_rows, payloads):
            output[index] = payload
    return output


def density_projection_index(payload):
    density = normalize_density(density_f_from_payload(payload) or {})
    if not density:
        return None
    grid = sorted(float(value) for value in density)
    cumulative = [0.0]
    total = 0.0
    for value in grid:
        total += float(density.get(value, 0.0))
        cumulative.append(total)
    return grid, cumulative


def density_projection_probability(index, unit, kind, value, value_hi=None):
    if not index:
        return None
    grid, cumulative = index
    low_native, high_native = bucket_interval_native(kind, value, value_hi)
    low_f, high_f = native_interval_to_f(low_native, high_native, unit)
    left = 0 if low_f is None else bisect.bisect_left(grid, float(low_f))
    right = len(grid) if high_f is None else bisect.bisect_left(grid, float(high_f))
    if right < left:
        return 0.0
    return max(0.0, min(1.0, float(cumulative[right] - cumulative[left])))


def probability_logit(value, epsilon=1e-6):
    value = max(float(epsilon), min(1.0 - float(epsilon), float(value)))
    return math.log(value / (1.0 - value))


def cutoff_hour_bucket(value):
    try:
        hour = int(value)
    except (TypeError, ValueError):
        return "na"
    if hour <= 8:
        return "07-08"
    if hour <= 13:
        return "09-13"
    if hour <= 16:
        return "14-16"
    return "17-20"


def _micro_float(value):
    if value in (None, ""):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def microstructure_feature_record(row):
    candidate = _micro_float(row.get("candidate_p"))
    current = _micro_float(row.get("replayed_p"))
    recorded = _micro_float(row.get("recorded_p"))
    market = _micro_float(row.get("market_yes"))
    output = {
        "market_id": row.get("market_id") or "unknown",
        "bin_type": row.get("bin_type") or row.get("bin_kind") or "eq",
        "candidate_cutoff_hour": _micro_float(row.get("candidate_cutoff_hour")),
        "candidate_cutoff_hour_bucket": cutoff_hour_bucket(row.get("candidate_cutoff_hour")),
        "candidate_p": candidate,
        "replayed_p": current,
        "recorded_p": recorded,
        "market_yes": market,
        "candidate_logit": probability_logit(candidate) if candidate is not None else None,
        "replayed_logit": probability_logit(current) if current is not None else None,
        "market_logit": probability_logit(market) if market is not None else None,
        "candidate_minus_market": candidate - market if candidate is not None and market is not None else None,
        "candidate_minus_replayed": candidate - current if candidate is not None and current is not None else None,
        "replayed_minus_market": current - market if current is not None and market is not None else None,
        "abs_candidate_minus_market": abs(candidate - market) if candidate is not None and market is not None else None,
    }
    for column in CLOB_MODEL_FEATURE_COLUMNS:
        output[column] = _micro_float(row.get(column))
    return output


def microstructure_feature_frame(records, feature_names=None):
    frame = pd.DataFrame(records)
    for column in MICROSTRUCTURE_NUMERIC_FEATURES:
        if column not in frame:
            frame[column] = None
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    for column in MICROSTRUCTURE_CATEGORICAL_FEATURES:
        if column not in frame:
            frame[column] = "unknown"
        frame[column] = frame[column].fillna("unknown").astype(str)
    features = pd.get_dummies(
        frame[MICROSTRUCTURE_NUMERIC_FEATURES + MICROSTRUCTURE_CATEGORICAL_FEATURES],
        columns=MICROSTRUCTURE_CATEGORICAL_FEATURES,
        dtype=float,
    )
    if feature_names is not None:
        features = features.reindex(columns=feature_names, fill_value=0.0)
    return features


__all__ = [name for name in globals() if not name.startswith("__")]
