"""Serving-time calibration artifact helpers.

Calibration training modules produce artifacts and reports. Model runtime code
uses this module to load those artifacts and apply the small pure transforms
needed during live distribution and market-bin scoring.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path

from weather.artifacts import resolve_artifact_path
from weather.model.continuous_density import (
    continuous_density_payload,
    density_f_from_payload,
    native_to_f,
    normalize_density,
)
from weather.scoring.metrics import safe_float
from weather.units import round_half_up


PROBABILITY_EPSILON = 1e-6
FORECAST_EPSILON = 1e-9
SETTLEMENT_CUTOFF_HOURS = tuple(range(8, 21))

DEFAULT_PROBABILITY_ARTIFACT = resolve_artifact_path("probability_calibration.json")
DEFAULT_FORECAST_ERROR_ARTIFACT = resolve_artifact_path("forecast_error_model.json")
DEFAULT_AFTERNOON_CENTERING_ARTIFACT = resolve_artifact_path("afternoon_residual_centering.json")
DEFAULT_SETTLEMENT_LAG_ARTIFACT = resolve_artifact_path("settlement_lag_model.json")
DEFAULT_FAMILY_SECONDARY_MANIFEST = resolve_artifact_path("f_family_secondary_artifacts.json")
logger = logging.getLogger(__name__)
FORECAST_SOURCE_ALIASES = {
    "nws": "nws_hourly",
    "nws_forecast": "nws_hourly",
}


def _load_json_artifact(path, label):
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Error loading %s artifact: %s", label, exc)
        return None


def load_probability_calibration(path=DEFAULT_PROBABILITY_ARTIFACT):
    return _load_json_artifact(path, "probability calibration")


def load_forecast_error_model(path=DEFAULT_FORECAST_ERROR_ARTIFACT):
    return _load_json_artifact(path, "forecast error model")


def load_afternoon_residual_centering(path=DEFAULT_AFTERNOON_CENTERING_ARTIFACT):
    return _load_json_artifact(path, "afternoon residual centering")


def load_settlement_lag_model(path=DEFAULT_SETTLEMENT_LAG_ARTIFACT):
    return _load_json_artifact(path, "settlement lag model")


def load_family_secondary_manifest(path=DEFAULT_FAMILY_SECONDARY_MANIFEST):
    return _load_json_artifact(path, "family secondary artifact manifest")


def clip_probability(value, epsilon=PROBABILITY_EPSILON):
    if value is None:
        return None
    return max(epsilon, min(1.0 - epsilon, float(value)))


def logit(value):
    value = clip_probability(value)
    return math.log(value / (1.0 - value))


def sigmoid(value):
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def normalize_distribution(scores):
    cleaned = {
        int(bucket): max(0.0, float(probability))
        for bucket, probability in (scores or {}).items()
        if probability is not None
    }
    total = sum(cleaned.values())
    if total <= 0:
        return {}
    return {bucket: value / total for bucket, value in sorted(cleaned.items())}


def temperature_scale_distribution(probabilities, temperature=1.0):
    distribution = normalize_distribution(probabilities)
    if not distribution:
        return {}
    try:
        temperature = float(temperature)
    except (TypeError, ValueError):
        temperature = 1.0
    temperature = max(0.05, temperature)
    if abs(temperature - 1.0) <= 1e-12:
        return distribution
    scaled = {
        bucket: (probability ** (1.0 / temperature)) if probability > 0 else 0.0
        for bucket, probability in distribution.items()
    }
    return normalize_distribution(scaled)


def distribution_mean(distribution):
    normalized = normalize_distribution(distribution)
    if not normalized:
        return None
    return sum(float(bucket) * probability for bucket, probability in normalized.items())


def shift_bucket_distribution(distribution, shift):
    normalized = normalize_distribution(distribution)
    if not normalized or abs(float(shift or 0.0)) <= 1e-12:
        return normalized
    shifted = {}
    for bucket, probability in normalized.items():
        target = float(bucket) + float(shift)
        low = math.floor(target)
        high = math.ceil(target)
        if low == high:
            shifted[int(low)] = shifted.get(int(low), 0.0) + probability
            continue
        high_weight = target - low
        low_weight = 1.0 - high_weight
        shifted[int(low)] = shifted.get(int(low), 0.0) + probability * low_weight
        shifted[int(high)] = shifted.get(int(high), 0.0) + probability * high_weight
    return normalize_distribution(shifted)


def ordinal_smooth_distribution(distribution, sigma=0.75, blend_weight=0.0):
    base = normalize_distribution(distribution)
    if not base or sigma <= 0 or blend_weight <= 0:
        return base
    smoothed = {}
    for bucket in base:
        weighted_sum = 0.0
        weight_total = 0.0
        for other_bucket, probability in base.items():
            distance = bucket - other_bucket
            weight = math.exp(-0.5 * (distance / float(sigma)) ** 2)
            weighted_sum += probability * weight
            weight_total += weight
        smoothed[bucket] = weighted_sum / weight_total if weight_total else 0.0
    keys = set(base) | set(smoothed)
    return normalize_distribution({
        key: (1.0 - blend_weight) * base.get(key, 0.0) + blend_weight * smoothed.get(key, 0.0)
        for key in keys
    })


def afternoon_centering_context_keys(market_id, regime_id, hour):
    market = market_id or "unknown"
    regime = regime_id or "unknown"
    hour = str(int(hour)) if hour is not None else "unknown"
    return [
        f"market={market}|hour={hour}",
        f"market={market}|afternoon",
        f"regime={regime}|hour={hour}",
        f"regime={regime}|afternoon",
        f"global|hour={hour}",
        "global",
    ]


def select_afternoon_centering_context(artifact, market_id, regime_id, hour):
    cfg = (artifact or {}).get("component") or {}
    contexts = (artifact or {}).get("contexts") or {}
    min_n = int(cfg.get("min_context_n", 4))
    allow_global = bool(cfg.get("allow_global_fallback", False))
    for key in afternoon_centering_context_keys(market_id, regime_id, hour):
        if key.startswith("global") and not allow_global:
            continue
        row = contexts.get(key)
        if row and int(row.get("n", 0)) >= min_n:
            return key, row
    return None, None


def apply_afternoon_residual_centering(
    distribution,
    artifact,
    *,
    market_id,
    regime_id,
    hour,
    forecast_disagreement=None,
):
    normalized = normalize_distribution(distribution)
    context = {
        "active": False,
        "reason": "inactive",
        "market_id": market_id,
        "regime_id": regime_id,
        "hour": hour,
        "context_key": None,
        "shift": 0.0,
        "mean_before": distribution_mean(normalized),
        "mean_after": None,
        "forecast_disagreement": forecast_disagreement,
        "spread_blend_weight": 0.0,
    }
    if not normalized:
        context["reason"] = "empty_distribution"
        return normalized, context
    if not artifact:
        context["reason"] = "missing_artifact"
        context["mean_after"] = context["mean_before"]
        return normalized, context
    cfg = artifact.get("component") or {}
    if not cfg.get("enabled", True):
        context["reason"] = "artifact_disabled"
        context["mean_after"] = context["mean_before"]
        return normalized, context
    try:
        hour_int = int(hour)
    except (TypeError, ValueError):
        context["reason"] = "missing_hour"
        context["mean_after"] = context["mean_before"]
        return normalized, context
    if hour_int < int(cfg.get("start_hour", 15)) or hour_int > int(cfg.get("end_hour", 18)):
        context["reason"] = "outside_hour_window"
        context["mean_after"] = context["mean_before"]
        return normalized, context
    key, row = select_afternoon_centering_context(artifact, market_id, regime_id, hour_int)
    if not row:
        context["reason"] = "no_context"
        context["mean_after"] = context["mean_before"]
        return normalized, context

    max_abs_shift = float(cfg.get("max_abs_shift", 2.0))
    shift = max(-max_abs_shift, min(max_abs_shift, float(row.get("mean_residual") or 0.0)))
    adjusted = shift_bucket_distribution(normalized, shift)
    disagreement = safe_float(forecast_disagreement)
    if disagreement is not None:
        reference = float(cfg.get("disagreement_reference", 3.0))
        excess = max(0.0, disagreement - reference)
        blend = min(
            float(cfg.get("spread_blend_max", 0.35)),
            float(cfg.get("spread_blend_base", 0.0)) + excess * float(cfg.get("spread_blend_per_unit", 0.05)),
        )
        sigma = float(cfg.get("spread_sigma_base", 0.75)) + excess * float(cfg.get("spread_sigma_per_unit", 0.05))
        if blend > 0:
            adjusted = ordinal_smooth_distribution(adjusted, sigma=sigma, blend_weight=blend)
            context["spread_blend_weight"] = blend

    context.update({
        "active": abs(shift) > 1e-12 or context["spread_blend_weight"] > 0,
        "reason": "afternoon_residual_centering_applied",
        "context_key": key,
        "shift": shift,
        "mean_after": distribution_mean(adjusted),
        "context_n": row.get("n"),
        "mean_residual": row.get("mean_residual"),
        "mean_expected_minus_settlement": row.get("mean_expected_minus_settlement"),
    })
    return adjusted, context


def floor_distance_bucket(bin_value, floor_bucket):
    if bin_value is None or floor_bucket is None:
        return "unknown"
    diff = int(bin_value) - int(floor_bucket)
    if diff <= -1:
        return "below_floor"
    if diff == 0:
        return "at_floor"
    if diff == 1:
        return "one_above"
    if diff == 2:
        return "two_above"
    return "three_plus_above"


def hard_bin_probability(bin_kind, bin_value, floor_bucket, bin_value_hi=None):
    if floor_bucket is None or bin_value is None:
        return None
    bin_value = int(bin_value)
    floor_bucket = int(floor_bucket)
    if bin_kind == "gte" and floor_bucket >= bin_value:
        return 1.0
    if bin_kind == "lte" and floor_bucket > bin_value:
        return 0.0
    if bin_kind not in {"gte", "lte"}:
        upper = int(bin_value_hi) if bin_value_hi is not None else bin_value
        if upper < floor_bucket:
            return 0.0
        return None
    return None


def observed_support_blocks_floor_lift(bin_kind, bin_value, floor_bucket, context):
    if bin_kind != "eq":
        return False
    value_bucket = round_half_up(bin_value)
    support_bucket = round_half_up((context or {}).get("observed_support_bucket"))
    if value_bucket is None or support_bucket is None:
        return False
    floor_bucket = round_half_up(floor_bucket)
    if floor_bucket is not None and value_bucket < floor_bucket:
        return True
    return value_bucket < support_bucket


def probability_context_keys(bin_kind, cutoff_hour, distance_bucket):
    kind = bin_kind or "eq"
    hour = str(cutoff_hour) if cutoff_hour is not None else "unknown"
    distance = distance_bucket or "unknown"
    return [
        f"kind={kind}|hour={hour}|distance={distance}",
        f"kind={kind}|distance={distance}",
        f"kind={kind}|hour={hour}",
        f"kind={kind}",
        "global",
    ]


def select_context_base_rate(artifact, bin_kind, cutoff_hour, distance_bucket):
    market_cfg = (artifact or {}).get("market_bin", {})
    contexts = market_cfg.get("contexts") or {}
    min_n = int(market_cfg.get("min_context_n", 40))
    for key in probability_context_keys(bin_kind, cutoff_hour, distance_bucket):
        row = contexts.get(key)
        if row and int(row.get("n", 0)) >= min_n:
            return float(row["base_rate"]), key, int(row.get("n", 0))
    global_row = contexts.get("global") or {}
    return (
        float(global_row.get("base_rate", market_cfg.get("base_rate", 0.10))),
        "global",
        int(global_row.get("n", 0)),
    )


def apply_exact_distribution_calibration(
    distribution,
    artifact,
    floor_bucket=None,
    resolution_weight=0.0,
    cutoff_hour=None,
):
    if not distribution:
        return {}
    cfg = (artifact or {}).get("exact_distribution") or {}
    if not cfg.get("enabled", True):
        return normalize_distribution(distribution)
    resolution_weight = max(0.0, min(1.0, float(resolution_weight or 0.0)))

    floor_bucket = int(floor_bucket) if floor_bucket is not None else None
    kept = {}
    for bucket, probability in distribution.items():
        bucket = int(bucket)
        if floor_bucket is not None and bucket < floor_bucket:
            kept[bucket] = 0.0
        else:
            kept[bucket] = max(0.0, float(probability))
    kept = normalize_distribution(kept)
    if not kept:
        return {}

    base_temperature = float(cfg.get("temperature", 1.0))
    by_hour = cfg.get("temperature_by_hour") or {}
    if cutoff_hour is not None and str(int(cutoff_hour)) in by_hour:
        base_temperature = float(by_hour[str(int(cutoff_hour))])
    temperature = max(0.05, base_temperature)
    if resolution_weight > 0:
        temperature = 1.0 + (temperature - 1.0) * (1.0 - resolution_weight)
    if abs(temperature - 1.0) > 1e-9:
        transformed = {
            bucket: (probability ** (1.0 / temperature)) if probability > 0 else 0.0
            for bucket, probability in kept.items()
        }
        kept = normalize_distribution(transformed)

    prior_weight = max(0.0, min(1.0, float(cfg.get("prior_weight", 0.0))))
    prior_weight *= (1.0 - resolution_weight)
    if prior_weight > 0:
        eligible = [
            bucket for bucket in kept
            if floor_bucket is None or bucket >= floor_bucket
        ]
        if eligible:
            uniform = 1.0 / len(eligible)
            kept = normalize_distribution({
                bucket: (
                    0.0 if floor_bucket is not None and bucket < floor_bucket
                    else (1.0 - prior_weight) * kept.get(bucket, 0.0) + prior_weight * uniform
                )
                for bucket in kept
            })

    if floor_bucket is not None:
        for bucket in list(kept):
            if bucket < floor_bucket:
                kept[bucket] = 0.0
    return normalize_distribution(kept)


def continuous_floor_threshold_f(floor_bucket, unit):
    if floor_bucket is None:
        return None
    try:
        return native_to_f(float(floor_bucket) - 0.5, unit)
    except (TypeError, ValueError):
        return None


def apply_continuous_density_calibration(
    density_payload,
    artifact,
    floor_bucket=None,
    unit="F",
    resolution_weight=0.0,
    cutoff_hour=None,
):
    density = density_f_from_payload(density_payload)
    if density is None:
        return density_payload
    payload = dict(density_payload or {})
    cfg = (artifact or {}).get("exact_distribution") or {}
    if not cfg.get("enabled", True):
        payload["density_f"] = normalize_density(density)
        return payload

    resolution_weight = max(0.0, min(1.0, float(resolution_weight or 0.0)))
    floor_threshold_f = continuous_floor_threshold_f(floor_bucket, unit)
    kept = {}
    for grid_value, probability in (density or {}).items():
        grid_value = float(grid_value)
        if floor_threshold_f is not None and grid_value < floor_threshold_f:
            kept[grid_value] = 0.0
        else:
            kept[grid_value] = max(0.0, float(probability))
    kept = normalize_density(kept)
    if not kept:
        payload["density_f"] = {}
        return payload

    base_temperature = float(cfg.get("temperature", 1.0))
    by_hour = cfg.get("temperature_by_hour") or {}
    if cutoff_hour is not None and str(int(cutoff_hour)) in by_hour:
        base_temperature = float(by_hour[str(int(cutoff_hour))])
    temperature = max(0.05, base_temperature)
    if resolution_weight > 0:
        temperature = 1.0 + (temperature - 1.0) * (1.0 - resolution_weight)
    if abs(temperature - 1.0) > 1e-9:
        kept = normalize_density({
            grid_value: (probability ** (1.0 / temperature)) if probability > 0 else 0.0
            for grid_value, probability in kept.items()
        })

    prior_weight = max(0.0, min(1.0, float(cfg.get("prior_weight", 0.0))))
    prior_weight *= (1.0 - resolution_weight)
    if prior_weight > 0 and kept:
        eligible = [
            grid_value for grid_value in kept
            if floor_threshold_f is None or grid_value >= floor_threshold_f
        ]
        if eligible:
            uniform = 1.0 / len(eligible)
            kept = normalize_density({
                grid_value: (
                    0.0 if floor_threshold_f is not None and grid_value < floor_threshold_f
                    else (1.0 - prior_weight) * kept.get(grid_value, 0.0) + prior_weight * uniform
                )
                for grid_value in kept
            })

    payload = continuous_density_payload(
        kept,
        **{key: value for key, value in payload.items() if key not in {"kind", "density_f"}}
    )
    if payload["density_f"]:
        payload["mean_f"] = sum(
            grid_value * probability
            for grid_value, probability in payload["density_f"].items()
        )
    payload["continuous_calibration"] = {
        "floor_bucket": floor_bucket,
        "floor_unit": unit,
        "floor_threshold_f": floor_threshold_f,
        "cutoff_hour": cutoff_hour,
        "resolution_weight": resolution_weight,
    }
    return payload


def calibrate_market_probability(probability, bin_data, artifact, context=None, market_yes=None):
    if probability is None:
        return None
    artifact = artifact or {}
    cfg = artifact.get("market_bin") or {}
    if not cfg:
        return probability
    if not cfg.get("enabled", True):
        return probability

    context = context or {}
    bin_kind = bin_data.get("kind") or bin_data.get("bin_kind") or "eq"
    bin_value = bin_data.get("value", bin_data.get("bin_value_c"))
    bin_value_hi = bin_data.get("value_hi", bin_data.get("bin_value_hi"))
    floor_bucket = context.get("observed_floor_bucket")
    cutoff_hour = context.get("cutoff_hour")
    hard = hard_bin_probability(bin_kind, bin_value, floor_bucket, bin_value_hi=bin_value_hi)
    if hard is not None:
        return hard

    raw_probability = max(0.0, min(1.0, float(probability)))
    if cfg.get("preserve_distribution_coherence", True):
        return raw_probability

    raw = clip_probability(probability)
    distance = floor_distance_bucket(bin_value, floor_bucket)
    method = cfg.get("method", "prior_shrink")
    if method == "temperature":
        temperature = max(0.05, float(cfg.get("temperature", 1.0)))
        calibrated = sigmoid(logit(raw) / temperature)
    elif method == "platt":
        slope = float(cfg.get("slope", 1.0))
        intercept = float(cfg.get("intercept", 0.0))
        calibrated = sigmoid(slope * logit(raw) + intercept)
    elif method == "market_shrink" and market_yes is not None:
        weight = max(0.0, min(1.0, float(cfg.get("market_weight", 0.0))))
        calibrated = (1.0 - weight) * raw + weight * clip_probability(market_yes)
    else:
        base_rate, _, context_n = select_context_base_rate(
            artifact,
            bin_kind,
            cutoff_hour,
            distance,
        )
        weight = max(0.0, min(1.0, float(cfg.get("weight", 0.0))))
        shrink_k = max(1.0, float(cfg.get("context_shrink_k", 50.0)))
        effective_weight = weight * (context_n / (context_n + shrink_k)) if context_n else weight
        calibrated = (1.0 - effective_weight) * raw + effective_weight * base_rate

    if observed_support_blocks_floor_lift(bin_kind, bin_value, floor_bucket, context):
        calibrated = min(calibrated, raw)
    if bin_kind == "eq" and not cfg.get("allow_exact_lift", False):
        calibrated = min(calibrated, raw)

    min_probability = max(0.0, float(cfg.get("min_probability", PROBABILITY_EPSILON)))
    max_probability = min(1.0, float(cfg.get("max_probability", 1.0 - PROBABILITY_EPSILON)))
    return max(min_probability, min(max_probability, calibrated))


def normal_bucket_distribution(support, mean, sigma, floor_bucket=None):
    sigma = max(0.10, float(sigma))
    scores = {}
    for bucket in support:
        bucket = int(bucket)
        if floor_bucket is not None and bucket < floor_bucket:
            scores[bucket] = 0.0
        else:
            scores[bucket] = math.exp(-0.5 * ((bucket - mean) / sigma) ** 2)
    return normalize_distribution(scores)


def canonical_forecast_source(source, artifact=None):
    if source is None:
        return None
    source = str(source)
    aliases = {}
    aliases.update(FORECAST_SOURCE_ALIASES)
    aliases.update((artifact or {}).get("source_aliases") or {})
    return aliases.get(source, source)


def forecast_error_stats_for_source(artifact, source, capture_hour):
    source_stats = artifact.get("source_stats") or {}
    global_stats = artifact.get("global_stats") or {}
    canonical_source = canonical_forecast_source(source, artifact)
    if capture_hour is not None:
        try:
            hour = int(float(capture_hour))
        except (TypeError, ValueError):
            hour = None
        if hour is not None:
            hour_stats = artifact.get("hour_stats") or {}
            stats = hour_stats.get(f"{canonical_source}|hour={hour}") or hour_stats.get(f"{source}|hour={hour}")
            if stats:
                return stats
    return source_stats.get(canonical_source) or source_stats.get(source) or global_stats


def forecast_source_reliability(stats):
    if not stats:
        return 0.0
    learned = safe_float(stats.get("learned_reliability"))
    if learned is not None:
        return max(0.0, learned)
    sigma = safe_float(stats.get("rmse"))
    if sigma is None:
        sigma = safe_float(stats.get("mae"))
    if sigma is None:
        return 0.0
    return 1.0 / max(sigma * sigma, 0.01)


def forecast_source_weight(stats, component_config=None):
    component_config = component_config or {}
    reliability = forecast_source_reliability(stats)
    if reliability <= 0:
        return 0.0
    n = int(safe_float(stats.get("n")) or 0)
    shrink_k = safe_float(stats.get("source_weight_shrink_k"))
    if shrink_k is None:
        by_source = component_config.get("source_weight_shrink_k_by_source") or {}
        shrink_k = safe_float(by_source.get(stats.get("source")))
    if shrink_k is None:
        shrink_k = safe_float(component_config.get("source_weight_shrink_k"))
    if shrink_k is None:
        shrink_k = 20.0
    return reliability * (n / (n + shrink_k) if n > 0 else 0.25)


def forecast_error_distribution(
    support,
    forecast_values,
    artifact,
    floor_bucket=None,
    capture_hour=None,
):
    if not artifact or not forecast_values:
        return None
    cfg = artifact.get("component") or {}
    if not cfg.get("enabled", True):
        return None
    min_sigma = float(cfg.get("min_sigma", 0.75))
    max_sigma = float(cfg.get("max_sigma", 3.0))

    cleaned = []
    legacy_forecast_key = "forecast_high" + "_c"
    for item in forecast_values:
        value = safe_float(item.get("value", item.get(legacy_forecast_key)))
        source = item.get("source")
        if value is None or not source:
            continue
        stats = forecast_error_stats_for_source(artifact, source, capture_hour)
        if not stats:
            continue
        cleaned.append((source, value, stats))
    if not cleaned:
        return None

    centers = [
        value + float(stats.get("bias_observed_minus_forecast", 0.0))
        for _, value, stats in cleaned
    ]
    spread = max(centers) - min(centers) if len(centers) > 1 else 0.0
    disagreement_widen = float(cfg.get("disagreement_sigma_per_c", 0.20)) * spread

    combined = {int(bucket): 0.0 for bucket in support}
    total_weight = 0.0
    for (_, value, stats), center in zip(cleaned, centers):
        sigma = max(min_sigma, float(stats.get("rmse") or stats.get("mae") or min_sigma))
        sigma = min(max_sigma, sigma + disagreement_widen)
        weight = forecast_source_weight(stats, cfg)
        distribution = normal_bucket_distribution(support, center, sigma, floor_bucket)
        for bucket, probability in distribution.items():
            combined[bucket] = combined.get(bucket, 0.0) + weight * probability
        total_weight += weight
    if total_weight <= 0:
        return None
    return normalize_distribution(combined)


def settlement_context_keys(source, cutoff_hour, gap):
    source = source or "unknown"
    hour = str(cutoff_hour) if cutoff_hour is not None else "unknown"
    gap_bucket = "3_plus" if gap is not None and int(gap) >= 3 else str(gap or "unknown")
    return [
        f"source={source}|hour={hour}|gap={gap_bucket}",
        f"source={source}|gap={gap_bucket}",
        f"source={source}|hour={hour}",
        f"source={source}",
        "global",
    ]


def revision_up_probability(artifact, cutoff_hour):
    if not artifact or cutoff_hour is None:
        return None
    contexts = artifact.get("revision_contexts") or {}
    cfg = artifact.get("component") or {}
    min_n = int(cfg.get("min_context_n", 20))
    hour = max(SETTLEMENT_CUTOFF_HOURS[0], min(SETTLEMENT_CUTOFF_HOURS[-1], int(cutoff_hour)))
    row = contexts.get(f"hour={hour}")
    if row and int(row.get("n", 0)) >= min_n:
        return float(row["revision_up_rate"])
    return None


def settlement_catchup_probability(
    artifact,
    source,
    source_bucket,
    wu_floor_bucket,
    cutoff_hour=None,
):
    if not artifact or source_bucket is None or wu_floor_bucket is None:
        return None
    if source_bucket <= wu_floor_bucket:
        return 1.0
    cfg = artifact.get("component") or {}
    contexts = artifact.get("catchup_contexts") or {}
    min_n = int(cfg.get("min_context_n", 20))
    gap = int(source_bucket) - int(wu_floor_bucket)
    for key in settlement_context_keys(source, cutoff_hour, gap):
        row = contexts.get(key)
        if row and int(row.get("n", 0)) >= min_n:
            return float(row["catchup_rate"])
    row = contexts.get("global")
    if row:
        return float(row["catchup_rate"])
    return None
