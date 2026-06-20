"""Target-versus-extra location validation harness.

The harness evaluates extra-location labels without using market prices. It
compares target-only, flat target-plus-extra, extra-only, and
similarity-weighted transfer on the same held-out target labels.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import data_path
from weather.reporting.extra_location_registry import (
    build_compatibility_report,
    load_registry,
    location_status_map,
    training_eligible_ids,
)
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.reporting.location_similarity_pooling import (
    blend_prediction,
    build_similarity_table,
    pooling_weights,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("no_market_location_transfer")
GATE_SCHEMA_VERSION = schema_version("no_market_extra_location_gate")
DEFAULT_BACKTEST_ROOT = data_path("backtest")
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "no_market_location_transfer.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "no_market_location_transfer_report.md"
DEFAULT_CSV_OUT = DEFAULT_BACKTEST_ROOT / "no_market_location_transfer_paired.csv"
DEFAULT_BOOTSTRAP_REPS = 500
RANDOM_SEED = 20260618

CONDITIONS = ("target_only", "target_plus_extra", "extra_only", "similarity_weighted")
PROMOTION_METRICS = ("brier", "logloss", "absolute_error")
BACKENDS = ("fast_residual", "pooled_band_hgb", "continuous_density")


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _float(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _int(value: Any) -> int | None:
    number = _float(value)
    return int(round(number)) if number is not None else None


def _first(raw: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = raw.get(key)
        if value not in (None, ""):
            return value
    return None


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def cutoff_regime(hour: float | int | None) -> str:
    if hour is None:
        return "unknown"
    hour = float(hour)
    if hour < 10:
        return "early"
    if hour < 15:
        return "midday"
    return "late"


def normalize_history_row(raw: dict[str, Any], row_number: int | None = None) -> tuple[dict[str, Any] | None, list[str]]:
    errors = []
    location_id = str(_first(raw, "location_id", "market_id", "target_market", "city_id") or "").strip()
    target_date = _parse_date(_first(raw, "target_date", "date", "local_date", "market_date"))
    cutoff_hour = _float(_first(raw, "cutoff_hour", "hour", "candidate_cutoff_hour"))
    actual = _float(_first(raw, "actual", "final_bucket", "actual_bucket", "label", "settlement_bucket"))
    forecast = _float(_first(raw, "forecast_high", "forecast", "model_mean", "predicted_mean"))
    if forecast is None:
        forecast = _float(_first(raw, "high_so_far", "current_temp"))
    if not location_id:
        errors.append("missing location_id")
    if target_date is None:
        errors.append("missing or invalid target_date")
    if cutoff_hour is None:
        errors.append("missing cutoff_hour")
    if actual is None:
        errors.append("missing actual label")
    if forecast is None:
        errors.append("missing forecast_high/model_mean")
    if errors:
        return None, errors
    row = {
        "row_number": row_number,
        "location_id": location_id,
        "target_date": target_date.isoformat(),
        "year": int(target_date.year),
        "cutoff_hour": float(cutoff_hour),
        "cutoff_regime": cutoff_regime(cutoff_hour),
        "actual": float(actual),
        "actual_bucket": int(round(float(actual))),
        "forecast": float(forecast),
        "unit": str(_first(raw, "unit", "market_unit") or "").upper() or None,
        "market_yes_present": _first(raw, "market_yes", "market_probability") is not None,
        "raw": dict(raw),
    }
    return row, []


def normalize_history_rows(raw_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = []
    errors = []
    for index, raw in enumerate(raw_rows, start=1):
        row, row_errors = normalize_history_row(raw, row_number=index)
        if row_errors:
            errors.append({"row_number": index, "errors": row_errors})
        else:
            rows.append(row)
    return rows, errors


def mean(values: list[float | int | None]) -> float | None:
    clean = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return sum(clean) / len(clean) if clean else None


def stdev(values: list[float | int | None], default: float = 3.0) -> float:
    clean = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    if len(clean) < 2:
        return default
    value = statistics.pstdev(clean)
    return max(0.75, min(8.0, value if value > 0 else default))


def quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lo = int(math.floor(position))
    hi = int(math.ceil(position))
    if lo == hi:
        return ordered[lo]
    frac = position - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


def bootstrap_ci(
    values: list[float | int | None],
    *,
    reps: int = DEFAULT_BOOTSTRAP_REPS,
    seed: int = RANDOM_SEED,
) -> dict[str, Any]:
    clean = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    if not clean:
        return {"n": 0, "mean": None, "median": None, "ci_low": None, "ci_high": None}
    rng = random.Random(seed)
    draws = []
    for _ in range(int(reps)):
        draws.append(sum(clean[rng.randrange(len(clean))] for _ in clean) / len(clean))
    return {
        "n": len(clean),
        "mean": sum(clean) / len(clean),
        "median": statistics.median(clean),
        "ci_low": quantile(draws, 0.025),
        "ci_high": quantile(draws, 0.975),
        "positive_rate": sum(1 for value in clean if value > 0) / len(clean),
        "negative_rate": sum(1 for value in clean if value < 0) / len(clean),
    }


def normal_cdf(value: float, mean_value: float, sigma: float) -> float:
    z = (float(value) - float(mean_value)) / max(1e-9, float(sigma))
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def support_for_rows(rows: list[dict[str, Any]]) -> list[int]:
    values = [row["actual_bucket"] for row in rows]
    values += [int(round(row["forecast"])) for row in rows]
    if not values:
        return list(range(0, 1))
    return list(range(min(values) - 6, max(values) + 7))


def distribution_for_prediction(prediction: float, sigma: float, support: list[int]) -> dict[int, float]:
    masses = {}
    for bucket in support:
        mass = normal_cdf(bucket + 0.5, prediction, sigma) - normal_cdf(bucket - 0.5, prediction, sigma)
        masses[int(bucket)] = max(0.0, mass)
    total = sum(masses.values())
    if total <= 0:
        fallback = int(round(prediction))
        return {bucket: 1.0 if bucket == fallback else 0.0 for bucket in support}
    return {bucket: value / total for bucket, value in masses.items()}


def compact_bands(eval_row: dict[str, Any], support: list[int]) -> list[dict[str, Any]]:
    actual = int(eval_row["actual_bucket"])
    forecast = int(round(eval_row["forecast"]))
    values = {actual - 1, actual, actual + 1, forecast - 1, forecast, forecast + 1}
    low = min(support)
    high = max(support)
    output = []
    for value in sorted(item for item in values if low <= item <= high):
        output.extend([
            {"band_kind": "eq", "band_value": value, "outcome": 1 if actual == value else 0},
            {"band_kind": "lte", "band_value": value, "outcome": 1 if actual <= value else 0},
            {"band_kind": "gte", "band_value": value, "outcome": 1 if actual >= value else 0},
        ])
    return output


def band_probability(distribution: dict[int, float], band: dict[str, Any]) -> float:
    value = int(band["band_value"])
    if band["band_kind"] == "lte":
        return sum(prob for bucket, prob in distribution.items() if bucket <= value)
    if band["band_kind"] == "gte":
        return sum(prob for bucket, prob in distribution.items() if bucket >= value)
    return float(distribution.get(value, 0.0))


def logloss_binary(probability: float, outcome: int) -> float:
    p = max(1e-15, min(1.0 - 1e-15, float(probability)))
    y = int(outcome)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def _train_pool(
    rows: list[dict[str, Any]],
    eval_row: dict[str, Any],
    *,
    target_id: str,
    extra_ids: set[str],
    condition: str,
) -> tuple[list[dict[str, Any]], int]:
    blocked_same_date = 0
    pool = []
    for row in rows:
        if row["target_date"] == eval_row["target_date"]:
            blocked_same_date += 1
            continue
        if row["cutoff_regime"] != eval_row["cutoff_regime"]:
            continue
        if row["year"] == eval_row["year"]:
            continue
        location_id = row["location_id"]
        if condition == "target_only" and location_id == target_id:
            pool.append(row)
        elif condition == "target_plus_extra" and (location_id == target_id or location_id in extra_ids):
            pool.append(row)
        elif condition == "extra_only" and location_id in extra_ids:
            pool.append(row)
        elif condition == "similarity_weighted" and (location_id == target_id or location_id in extra_ids):
            pool.append(row)
    return pool, blocked_same_date


def _residual_prediction(train_rows: list[dict[str, Any]], eval_row: dict[str, Any]) -> tuple[float | None, float, int]:
    if not train_rows:
        return None, 3.0, 0
    residuals = [row["actual"] - row["forecast"] for row in train_rows]
    residual_mean = mean(residuals) or 0.0
    sigma = stdev(residuals)
    return float(eval_row["forecast"]) + residual_mean, sigma, len(train_rows)


def _condition_prediction(
    rows: list[dict[str, Any]],
    eval_row: dict[str, Any],
    *,
    target_id: str,
    extra_ids: set[str],
    condition: str,
    similarity_rows: list[dict[str, Any]],
    target_local_weight: float,
    min_similarity: float,
) -> tuple[dict[str, Any] | None, int]:
    train_rows, blocked_same_date = _train_pool(
        rows,
        eval_row,
        target_id=target_id,
        extra_ids=extra_ids,
        condition=condition,
    )
    if condition != "similarity_weighted":
        prediction, sigma, train_count = _residual_prediction(train_rows, eval_row)
        if prediction is None:
            return None, blocked_same_date
        return {
            "condition": condition,
            "prediction": prediction,
            "sigma": sigma,
            "train_rows": train_count,
            "target_local_labels_present": any(row["location_id"] == target_id for row in train_rows),
            "extra_location_ids": sorted({row["location_id"] for row in train_rows if row["location_id"] != target_id}),
            "attribution": [],
        }, blocked_same_date

    target_train = [row for row in train_rows if row["location_id"] == target_id]
    target_prediction, target_sigma, target_train_count = _residual_prediction(target_train, eval_row)
    extra_predictions = {}
    sigma_values = [target_sigma]
    for extra_id in sorted(extra_ids):
        extra_train = [row for row in train_rows if row["location_id"] == extra_id]
        prediction, sigma, _count = _residual_prediction(extra_train, eval_row)
        if prediction is not None:
            extra_predictions[extra_id] = prediction
            sigma_values.append(sigma)
    weights = pooling_weights(
        similarity_rows,
        target_location_id=target_id,
        target_local_weight=target_local_weight,
        min_similarity=min_similarity,
    )
    blended = blend_prediction(target_prediction, extra_predictions, weights)
    if blended["prediction"] is None:
        return None, blocked_same_date
    return {
        "condition": condition,
        "prediction": blended["prediction"],
        "sigma": mean(sigma_values) or 3.0,
        "train_rows": len(train_rows),
        "target_local_labels_present": bool(target_train),
        "extra_location_ids": sorted(extra_predictions),
        "attribution": blended["attribution"],
        "pooling_weights": weights,
    }, blocked_same_date


def _score_prediction(
    eval_row: dict[str, Any],
    prediction: dict[str, Any],
    support: list[int],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    distribution = distribution_for_prediction(prediction["prediction"], prediction["sigma"], support)
    actual_bucket = int(eval_row["actual_bucket"])
    winning_probability = float(distribution.get(actual_bucket, 0.0))
    source = {
        "target_market_id": eval_row["location_id"],
        "target_date": eval_row["target_date"],
        "year": eval_row["year"],
        "cutoff_hour": eval_row["cutoff_hour"],
        "cutoff_regime": eval_row["cutoff_regime"],
        "condition": prediction["condition"],
        "predicted_mean": prediction["prediction"],
        "actual_bucket": actual_bucket,
        "absolute_error": abs(prediction["prediction"] - eval_row["actual"]),
        "squared_error": (prediction["prediction"] - eval_row["actual"]) ** 2,
        "winning_probability": winning_probability,
        "winning_brier": (winning_probability - 1.0) ** 2,
        "winning_logloss": -math.log(max(1e-15, winning_probability)),
        "train_rows": prediction["train_rows"],
        "sigma": prediction["sigma"],
        "target_local_labels_present": prediction["target_local_labels_present"],
        "extra_location_ids": prediction["extra_location_ids"],
        "attribution": prediction.get("attribution") or [],
    }
    band_rows = []
    for band in compact_bands(eval_row, support):
        probability = band_probability(distribution, band)
        band_rows.append({
            "target_market_id": eval_row["location_id"],
            "target_date": eval_row["target_date"],
            "year": eval_row["year"],
            "cutoff_hour": eval_row["cutoff_hour"],
            "cutoff_regime": eval_row["cutoff_regime"],
            "condition": prediction["condition"],
            "band_kind": band["band_kind"],
            "band_value": band["band_value"],
            "band_key": f"{band['band_kind']}:{band['band_value']}",
            "outcome": band["outcome"],
            "probability": probability,
            "brier": (probability - int(band["outcome"])) ** 2,
            "logloss": logloss_binary(probability, int(band["outcome"])),
            "target_local_labels_present": prediction["target_local_labels_present"],
            "extra_location_ids": prediction["extra_location_ids"],
        })
    return source, band_rows


def _pair_key(row: dict[str, Any], include_band: bool) -> tuple[Any, ...]:
    key = (
        row["target_market_id"],
        row["target_date"],
        row["cutoff_regime"],
        row["cutoff_hour"],
    )
    if include_band:
        key += (row.get("band_key"),)
    return key


def pair_rows(rows: list[dict[str, Any]], metric_fields: tuple[str, ...], *, include_band: bool) -> list[dict[str, Any]]:
    grouped = defaultdict(dict)
    for row in rows:
        grouped[_pair_key(row, include_band=include_band)][row["condition"]] = row
    output = []
    for key, conditions in grouped.items():
        target = conditions.get("target_only")
        if not target:
            continue
        for condition in ("target_plus_extra", "extra_only", "similarity_weighted"):
            other = conditions.get(condition)
            if not other:
                continue
            row = {
                "comparison": f"{condition}_minus_target_only",
                "target_market_id": key[0],
                "target_date": key[1],
                "cutoff_regime": key[2],
                "cutoff_hour": key[3],
                "condition": condition,
                "target_local_labels_present": other.get("target_local_labels_present"),
                "extra_location_ids": ",".join(other.get("extra_location_ids") or []),
            }
            if include_band:
                row["band_key"] = key[4]
            for field in metric_fields:
                row[f"delta_{field}"] = other[field] - target[field]
            output.append(row)
    return output


def group_mean_rows(rows: list[dict[str, Any]], group_keys: tuple[str, ...], metric_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    grouped = defaultdict(list)
    for row in rows:
        grouped[tuple(row.get(key) for key in group_keys)].append(row)
    output = []
    for key, items in grouped.items():
        row = {name: value for name, value in zip(group_keys, key)}
        row["n"] = len(items)
        for field in metric_fields:
            row[field] = mean([item.get(field) for item in items])
        output.append(row)
    return output


def summarize_paired(
    paired: list[dict[str, Any]],
    metric_fields: tuple[str, ...],
    *,
    reps: int = DEFAULT_BOOTSTRAP_REPS,
) -> dict[str, Any]:
    summary = {}
    for comparison in sorted({row["comparison"] for row in paired}):
        rows = [row for row in paired if row["comparison"] == comparison]
        delta_fields = tuple(f"delta_{field}" for field in metric_fields)
        daily_rows = group_mean_rows(
            rows,
            ("comparison", "target_market_id", "target_date"),
            delta_fields,
        )
        regime_rows = group_mean_rows(
            rows,
            ("comparison", "cutoff_regime"),
            delta_fields,
        )
        summary[comparison] = {
            "row_count": len(rows),
            "daily_count": len(daily_rows),
            "row_level": {
                field: bootstrap_ci([row.get(f"delta_{field}") for row in rows], reps=reps)
                for field in metric_fields
            },
            "daily_first": {
                field: bootstrap_ci([row.get(f"delta_{field}") for row in daily_rows], reps=reps)
                for field in metric_fields
            },
            "by_market_daily": {
                market_id: {
                    "days": len(items),
                    **{
                        field: mean([row.get(f"delta_{field}") for row in items])
                        for field in metric_fields
                    },
                }
                for market_id, items in sorted(_group_by(daily_rows, "target_market_id").items())
            },
            "by_cutoff_regime": {
                str(row["cutoff_regime"]): {
                    "rows": row["n"],
                    **{
                        field: row.get(f"delta_{field}")
                        for field in metric_fields
                    },
                }
                for row in regime_rows
            },
        }
    return summary


def _group_by(rows: list[dict[str, Any]], key: str) -> dict[Any, list[dict[str, Any]]]:
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.get(key)].append(row)
    return grouped


def evidence_accounting(
    rows: list[dict[str, Any]],
    source_scores: list[dict[str, Any]],
    band_scores: list[dict[str, Any]],
    *,
    target_markets: set[str],
    extra_locations: set[str],
) -> dict[str, Any]:
    source_location_days = {
        (row["location_id"], row["target_date"])
        for row in rows
    }
    target_days = {
        (row["location_id"], row["target_date"])
        for row in rows
        if row["location_id"] in target_markets
    }
    extra_days = {
        (row["location_id"], row["target_date"])
        for row in rows
        if row["location_id"] in extra_locations
    }
    target_scored_days = {
        (row["target_market_id"], row["target_date"])
        for row in source_scores
        if row["condition"] == "target_only"
    }
    return {
        "source_rows": len(rows),
        "prediction_source_rows": len(source_scores),
        "prediction_band_rows": len(band_scores),
        "independent_location_days": len(source_location_days),
        "target_market_days_available": len(target_days),
        "target_market_days_scored": len(target_scored_days),
        "extra_location_days": len(extra_days),
        "target_market_count": len(target_markets),
        "extra_location_count": len(extra_locations),
        "row_multiplier": (len(band_scores) / len(target_scored_days)) if target_scored_days else 0.0,
    }


def transfer_gate(
    band_summary: dict[str, Any],
    source_summary: dict[str, Any],
    *,
    comparison: str = "target_plus_extra_minus_target_only",
    tolerance: float = 0.0,
) -> dict[str, Any]:
    reasons = []
    metric_checks = {}
    daily_band = ((band_summary.get(comparison) or {}).get("daily_first") or {})
    daily_source = ((source_summary.get(comparison) or {}).get("daily_first") or {})
    for metric in ("brier", "logloss"):
        ci = daily_band.get(metric) or {}
        ci_low = ci.get("ci_low")
        ci_high = ci.get("ci_high")
        if ci_low is not None and ci_low > tolerance:
            status = "BLOCK"
            reasons.append(f"{metric} CI is clearly positive versus target-only")
        elif ci_high is not None and ci_high <= tolerance:
            status = "PASS"
        else:
            status = "SHADOW_ONLY"
        metric_checks[metric] = {"status": status, "ci": ci}
    for metric in ("absolute_error",):
        ci = daily_source.get(metric) or {}
        ci_low = ci.get("ci_low")
        ci_high = ci.get("ci_high")
        if ci_low is not None and ci_low > tolerance:
            status = "BLOCK"
            reasons.append(f"{metric} CI is clearly positive versus target-only")
        elif ci_high is not None and ci_high <= tolerance:
            status = "PASS"
        else:
            status = "SHADOW_ONLY"
        metric_checks[metric] = {"status": status, "ci": ci}
    statuses = {row["status"] for row in metric_checks.values()}
    if "BLOCK" in statuses:
        gate_status = "BLOCK"
    elif statuses == {"PASS"}:
        gate_status = "PASS"
    else:
        gate_status = "SHADOW_ONLY"
    if not reasons and gate_status == "PASS":
        reasons.append("target-plus-extra beats or ties target-only within tolerance")
    elif not reasons:
        reasons.append("target-plus-extra does not have decisive daily-first clearance")
    return {
        "schema_version": GATE_SCHEMA_VERSION,
        "status": gate_status,
        "comparison": comparison,
        "tolerance": tolerance,
        "metric_checks": metric_checks,
        "reasons": reasons,
        "serving_promotion_allowed": gate_status == "PASS",
    }


def _load_registry_report(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    registry = load_registry(path)
    return build_compatibility_report(registry)


def _registry_filter(
    extra_locations: set[str],
    registry_report: dict[str, Any] | None,
    *,
    require_registry_pass: bool,
) -> tuple[set[str], dict[str, Any]]:
    if not registry_report:
        return set(extra_locations), {
            "enabled": False,
            "require_registry_pass": bool(require_registry_pass),
            "allowed_extra_location_ids": sorted(extra_locations),
            "blocked_extra_location_ids": [],
            "status_by_location": {},
        }
    allowed = training_eligible_ids(registry_report)
    statuses = location_status_map(registry_report)
    if require_registry_pass:
        selected = set(extra_locations) & allowed
    else:
        selected = set(extra_locations)
    blocked = sorted(set(extra_locations) - selected)
    return selected, {
        "enabled": True,
        "require_registry_pass": bool(require_registry_pass),
        "allowed_extra_location_ids": sorted(selected),
        "blocked_extra_location_ids": blocked,
        "status_by_location": statuses,
    }


def _location_descriptors(rows: list[dict[str, Any]], ids: set[str]) -> list[dict[str, Any]]:
    grouped = defaultdict(list)
    for row in rows:
        if row["location_id"] in ids:
            grouped[row["location_id"]].append(row)
    descriptors = []
    for location_id, items in grouped.items():
        descriptor = {
            "location_id": location_id,
            "climate_normal": mean([row["actual"] for row in items]),
            "climate_std": stdev([row["actual"] for row in items], default=4.0),
            "source_reliability_prior": 0.75,
            "forecast_error_mae": mean([abs(row["actual"] - row["forecast"]) for row in items]),
            "coordinates": {"lat": None, "lon": None, "elevation_m": None},
        }
        for item in items:
            raw = item.get("raw") or {}
            coords = raw.get("coordinates") or {}
            lat = _float(raw.get("lat") or coords.get("lat"))
            lon = _float(raw.get("lon") or coords.get("lon"))
            elev = _float(raw.get("elevation_m") or coords.get("elevation_m"))
            if lat is not None and lon is not None:
                descriptor["coordinates"] = {"lat": lat, "lon": lon, "elevation_m": elev or 0.0}
                descriptor["coastal"] = bool(raw.get("coastal", False))
                break
        descriptors.append(descriptor)
    return descriptors


def build_payload(
    raw_rows: list[dict[str, Any]],
    *,
    target_markets: list[str] | tuple[str, ...] | None = None,
    extra_locations: list[str] | tuple[str, ...] | None = None,
    holdout_years: list[int] | tuple[int, ...] | None = None,
    cutoff_regimes: list[str] | tuple[str, ...] | None = None,
    scoring_backend: str = "fast_residual",
    extra_location_registry: str | Path | None = None,
    require_registry_pass: bool = False,
    bootstrap_reps: int = DEFAULT_BOOTSTRAP_REPS,
    target_local_weight: float = 0.70,
    min_similarity: float = 0.15,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    if scoring_backend not in BACKENDS:
        raise ValueError(f"unsupported scoring backend: {scoring_backend}")
    rows, errors = normalize_history_rows(raw_rows)
    all_locations = sorted({row["location_id"] for row in rows})
    target_ids = set(target_markets or [all_locations[0]] if all_locations else [])
    extra_ids = set(extra_locations or [location_id for location_id in all_locations if location_id not in target_ids])
    registry_report = _load_registry_report(extra_location_registry)
    extra_ids, registry_gate = _registry_filter(
        extra_ids,
        registry_report,
        require_registry_pass=require_registry_pass,
    )
    holdout = set(int(year) for year in (holdout_years or sorted({row["year"] for row in rows})[-1:]))
    regimes = set(cutoff_regimes or sorted({row["cutoff_regime"] for row in rows}))
    eval_rows = [
        row for row in rows
        if row["location_id"] in target_ids
        and row["year"] in holdout
        and row["cutoff_regime"] in regimes
    ]
    support = support_for_rows(rows)
    target_descriptors = _location_descriptors(rows, target_ids)
    extra_descriptors = _location_descriptors(rows, extra_ids)
    similarity_rows = build_similarity_table(target_descriptors, extra_descriptors)

    source_scores = []
    band_scores = []
    missing_coverage = []
    blocked_same_date_rows = 0
    attribution = []
    for eval_row in eval_rows:
        condition_results = {}
        for condition in CONDITIONS:
            result, blocked = _condition_prediction(
                rows,
                eval_row,
                target_id=eval_row["location_id"],
                extra_ids=extra_ids,
                condition=condition,
                similarity_rows=similarity_rows,
                target_local_weight=target_local_weight,
                min_similarity=min_similarity,
            )
            blocked_same_date_rows += blocked
            if result is None:
                missing_coverage.append({
                    "target_market_id": eval_row["location_id"],
                    "target_date": eval_row["target_date"],
                    "cutoff_regime": eval_row["cutoff_regime"],
                    "condition": condition,
                    "reason": "no non-leaking training labels for condition",
                })
                continue
            if condition == "target_plus_extra" and not result.get("extra_location_ids"):
                missing_coverage.append({
                    "target_market_id": eval_row["location_id"],
                    "target_date": eval_row["target_date"],
                    "cutoff_regime": eval_row["cutoff_regime"],
                    "condition": condition,
                    "reason": "target-plus-extra has no extra-location labels and is equivalent to target-only",
                })
            source, bands = _score_prediction(eval_row, result, support)
            source_scores.append(source)
            band_scores.extend(bands)
            condition_results[condition] = result
            if condition == "similarity_weighted":
                for row in result.get("attribution") or []:
                    attribution.append({
                        "target_market_id": eval_row["location_id"],
                        "target_date": eval_row["target_date"],
                        "cutoff_regime": eval_row["cutoff_regime"],
                        **row,
                    })
        if "target_only" not in condition_results:
            missing_coverage.append({
                "target_market_id": eval_row["location_id"],
                "target_date": eval_row["target_date"],
                "cutoff_regime": eval_row["cutoff_regime"],
                "condition": "all",
                "reason": "target-only baseline missing; paired comparison skipped",
            })

    source_paired = pair_rows(
        source_scores,
        ("winning_brier", "winning_logloss", "absolute_error", "squared_error"),
        include_band=False,
    )
    band_paired = pair_rows(band_scores, ("brier", "logloss"), include_band=True)
    source_summary = summarize_paired(
        source_paired,
        ("winning_brier", "winning_logloss", "absolute_error", "squared_error"),
        reps=bootstrap_reps,
    )
    band_summary = summarize_paired(band_paired, ("brier", "logloss"), reps=bootstrap_reps)
    gate = transfer_gate(band_summary, source_summary)
    evidence = evidence_accounting(
        rows,
        source_scores,
        band_scores,
        target_markets=target_ids,
        extra_locations=extra_ids,
    )
    price_fields_present = any(row.get("market_yes_present") for row in rows)
    status = "BLOCK" if gate["status"] == "BLOCK" else ("WARN" if missing_coverage else "OK")
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or utc_iso(),
        "status": status,
        "scoring_backend": scoring_backend,
        "backend_detail": {
            "price_free": True,
            "market_price_fields_present": price_fields_present,
            "market_prices_used": False,
            "implementation": (
                "fast residual density"
                if scoring_backend == "fast_residual"
                else f"{scoring_backend} compatibility backend over the same blocked residual interface"
            ),
        },
        "scope": {
            "target_markets": sorted(target_ids),
            "extra_locations": sorted(extra_ids),
            "holdout_years": sorted(holdout),
            "cutoff_regimes": sorted(regimes),
        },
        "registry_gate": registry_gate,
        "evidence_accounting": evidence,
        "leakage_audit": {
            "status": "PASS",
            "blocked_same_target_date_rows": blocked_same_date_rows,
            "split_policy": "exclude same target_date and same holdout year from every training condition",
        },
        "missing_extra_location_coverage": missing_coverage,
        "prediction_rows": {
            "source": len(source_scores),
            "band": len(band_scores),
            "source_paired": len(source_paired),
            "band_paired": len(band_paired),
        },
        "source_summary": source_summary,
        "band_summary": band_summary,
        "promotion_gate": gate,
        "similarity_weighted_transfer": {
            "target_local_weight": target_local_weight,
            "min_similarity": min_similarity,
            "similarity_rows": similarity_rows,
            "attribution": attribution,
        },
        "validation_errors": errors,
        "paired_rows": band_paired,
    }


def write_json(path: str | Path, payload: dict[str, Any], *, include_rows: bool = False) -> Path:
    copy = dict(payload)
    if not include_rows:
        copy.pop("paired_rows", None)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(copy, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def write_paired_csv(path: str | Path, paired_rows: list[dict[str, Any]]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "comparison",
        "target_market_id",
        "target_date",
        "cutoff_regime",
        "cutoff_hour",
        "band_key",
        "delta_brier",
        "delta_logloss",
        "target_local_labels_present",
        "extra_location_ids",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(paired_rows)
    return path


def _ci_text(ci: dict[str, Any]) -> str:
    return (
        f"{fmt_signed(ci.get('mean'), 5)} "
        f"[{fmt_signed(ci.get('ci_low'), 5)}, {fmt_signed(ci.get('ci_high'), 5)}], "
        f"n={ci.get('n', 0)}"
    )


def _summary_rows(summary: dict[str, Any], metrics: tuple[str, ...]) -> list[list[Any]]:
    rows = []
    for comparison, item in sorted(summary.items()):
        daily = item.get("daily_first") or {}
        rows.append([
            comparison,
            item.get("daily_count", 0),
            item.get("row_count", 0),
            *[_ci_text(daily.get(metric) or {}) for metric in metrics],
        ])
    return rows


def render_report(payload: dict[str, Any]) -> str:
    evidence = payload.get("evidence_accounting") or {}
    gate = payload.get("promotion_gate") or {}
    lines = [
        "# No-Market Location Transfer",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: `{payload.get('status')}`",
        f"Scoring backend: `{payload.get('scoring_backend')}`",
        "",
        "Negative deltas mean the extra-location condition scored better than target-only on the same held-out target labels.",
        "",
        "## Evidence Accounting",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Source rows", evidence.get("source_rows", 0)],
            ["Independent location-days", evidence.get("independent_location_days", 0)],
            ["Target market-days scored", evidence.get("target_market_days_scored", 0)],
            ["Extra location-days", evidence.get("extra_location_days", 0)],
            ["Band prediction rows", evidence.get("prediction_band_rows", 0)],
            ["Row multiplier", fmt_num(evidence.get("row_multiplier"))],
            ["Market prices used", (payload.get("backend_detail") or {}).get("market_prices_used")],
        ],
    )
    lines += ["", "## Promotion Gate", ""]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Status", gate.get("status")],
            ["Comparison", gate.get("comparison")],
            ["Serving promotion allowed", gate.get("serving_promotion_allowed")],
            ["Reasons", "; ".join(gate.get("reasons") or [])],
        ],
    )
    lines += ["", "## Synthetic Band Daily-First Deltas", ""]
    lines += markdown_table(
        ["Comparison", "Days", "Rows", "Brier", "LogLoss"],
        _summary_rows(payload.get("band_summary") or {}, ("brier", "logloss")),
    )
    lines += ["", "## Exact-Bucket Daily-First Deltas", ""]
    lines += markdown_table(
        ["Comparison", "Days", "Rows", "Winning Brier", "Winning LogLoss", "MAE", "Squared Error"],
        _summary_rows(
            payload.get("source_summary") or {},
            ("winning_brier", "winning_logloss", "absolute_error", "squared_error"),
        ),
    )
    missing = payload.get("missing_extra_location_coverage") or []
    if missing:
        lines += ["", "## Missing Coverage", ""]
        lines += markdown_table(
            ["Target", "Date", "Regime", "Condition", "Reason"],
            [
                [
                    row.get("target_market_id"),
                    row.get("target_date"),
                    row.get("cutoff_regime"),
                    row.get("condition"),
                    row.get("reason"),
                ]
                for row in missing[:50]
            ],
        )
    lines += ["", "## Similarity Attribution", ""]
    attribution = (payload.get("similarity_weighted_transfer") or {}).get("attribution") or []
    lines += markdown_table(
        ["Target", "Date", "Regime", "Location", "Source", "Weight", "Contribution"],
        [
            [
                row.get("target_market_id"),
                row.get("target_date"),
                row.get("cutoff_regime"),
                row.get("location_id"),
                row.get("source"),
                fmt_num(row.get("weight")),
                fmt_num(row.get("contribution")),
            ]
            for row in attribution[:50]
        ],
    )
    return "\n".join(lines) + "\n"


def write_report(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(payload), encoding="utf-8")
    return path


def read_rows(path: str | Path) -> list[dict[str, Any]]:
    path = Path(path)
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return payload
        for key in ("rows", "records", "observations"):
            if isinstance(payload.get(key), list):
                return payload[key]
        raise ValueError(f"{path} does not contain rows/records/observations")
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _split_int_csv(value: str | None) -> list[int]:
    return [int(item) for item in _split_csv(value)]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate target-only versus extra-location no-market transfer."
    )
    parser.add_argument("observations", help="CSV or JSON observation rows.")
    parser.add_argument("--target-markets", default="")
    parser.add_argument("--extra-locations", default="")
    parser.add_argument("--holdout-years", default="")
    parser.add_argument("--cutoff-regimes", default="")
    parser.add_argument("--scoring-backend", choices=BACKENDS, default="fast_residual")
    parser.add_argument("--extra-location-registry", default="")
    parser.add_argument("--require-registry-pass", action="store_true")
    parser.add_argument("--bootstrap-reps", type=int, default=DEFAULT_BOOTSTRAP_REPS)
    parser.add_argument("--target-local-weight", type=float, default=0.70)
    parser.add_argument("--min-similarity", type=float, default=0.15)
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--csv-out", default=str(DEFAULT_CSV_OUT))
    parser.add_argument("--include-rows-in-json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> dict[str, Any]:
    parser = build_parser()
    args = parser.parse_args(argv)
    payload = build_payload(
        read_rows(args.observations),
        target_markets=_split_csv(args.target_markets),
        extra_locations=_split_csv(args.extra_locations),
        holdout_years=_split_int_csv(args.holdout_years),
        cutoff_regimes=_split_csv(args.cutoff_regimes),
        scoring_backend=args.scoring_backend,
        extra_location_registry=args.extra_location_registry or None,
        require_registry_pass=args.require_registry_pass,
        bootstrap_reps=args.bootstrap_reps,
        target_local_weight=args.target_local_weight,
        min_similarity=args.min_similarity,
    )
    json_path = write_json(args.json_out, payload, include_rows=args.include_rows_in_json)
    csv_path = write_paired_csv(args.csv_out, payload.get("paired_rows") or [])
    report_path = write_report(args.report_out, payload)
    print(f"No-market location transfer: {payload['status']}")
    print(f"JSON written to {json_path}")
    print(f"CSV written to {csv_path}")
    print(f"Report written to {report_path}")
    return payload


if __name__ == "__main__":
    main()
