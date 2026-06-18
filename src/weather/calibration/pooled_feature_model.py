"""F-family pooled feature model starter.

This is the Roadmap item 33 research path: train one shared native-unit model
across all Fahrenheit markets with city/context features. It deliberately writes
a separate artifact and report; live serving remains per-market until the
promotion gauntlet proves a pooled candidate market by market.
"""
import argparse
import json
import math
import pickle
import time
import warnings
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from weather.paths import data_path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer

from weather.scoring.metrics import (
    binary_log_loss,
    brier,
)
from weather.reporting.formatting import (
    fmt_num,
    markdown_table,
)
from weather.market.market_microstructure_features import CLOB_MODEL_FEATURE_COLUMNS
from weather.market.market_registry import all_specs, spec_for_id
from weather.model.continuous_density import (
    band_probability_from_density,
    canonical_grid_f,
    continuous_density_payload,
)
from weather.model.feature_store import FEATURE_COLUMNS, FEATURE_SCHEMA_VERSION, build_historical_feature_record
from weather.model.model_constants import INTRADAY_CUTOFF_HOURS
from weather.model.toronto_model import TorontoHighTempModel
from weather.reporting.source_redundancy import (
    FALLBACK_ORDER,
    PRIMARY_SOURCE,
    SUPPLEMENTAL_FEATURE_FAMILY,
    SUPPLEMENTAL_SOURCE_PREFIX,
    bias_stats_for_source,
    source_daily_indexes,
)
from weather.sources.forecast_history import daily_path_for, load_forecast_daily, load_forecast_profiles, long_path_for
from weather.sources.reanalysis_synoptic import load_reanalysis_synoptic_features
from weather.artifacts import writable_artifact_path
from weather.calibration.blocked_validation import blocked_validation_audit
from weather.units import round_half_up

DEFAULT_REPORT = data_path() / "backtest" / "f_family_pooled_model_report.md"
DEFAULT_ARTIFACT = writable_artifact_path("feature_model_hgb_f_pooled.pkl")
DEFAULT_BAND_REPORT = data_path() / "backtest" / "f_family_pooled_band_model_v0_3_report.md"
DEFAULT_BAND_ARTIFACT = writable_artifact_path("feature_model_hgb_f_pooled_v0_3.pkl")
DEFAULT_EXACT_WINNER_REPORT = data_path() / "backtest" / "f_family_pooled_exact_winner_model_report.md"
DEFAULT_EXACT_WINNER_ARTIFACT = writable_artifact_path("feature_model_hgb_f_pooled_exact_winner_v0_1.pkl")
DEFAULT_DYNAMIC_SOURCE_REPORT = data_path() / "backtest" / "f_family_pooled_dynamic_source_model_report.md"
DEFAULT_DYNAMIC_SOURCE_ARTIFACT = writable_artifact_path("feature_model_hgb_f_pooled_dynamic_source_v0_1.pkl")
DEFAULT_DENSITY_REPORT = data_path() / "backtest" / "pooled_continuous_density_model_report.md"
DEFAULT_DENSITY_ARTIFACT = writable_artifact_path("pooled_continuous_density_hgb_v0_1.pkl")

WIND_GROUPS = ["E-SE/onshore-ish", "S-SW", "W-NW", "N-NE", "SSE", "Other/variable"]
CLOUD_GROUPS = ["Precip", "Fog/haze", "Fair/clear", "Partly cloudy", "Mostly cloudy/overcast", "Other"]
BAND_KINDS = ("eq", "lte", "gte")
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
DYNAMIC_SOURCE_TRACKED_SOURCES = (
    "wu_history",
    "wu_current",
    "metar",
    "weather_forecast",
    "open_meteo",
    "nws_hourly",
    "global_ensemble",
    "eccc_citypage",
)
DYNAMIC_SOURCE_FORECAST_SOURCES = (
    "weather_forecast",
    "open_meteo",
    "nws_hourly",
    "global_ensemble",
    "eccc_citypage",
)
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


def sigmoid(value):
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def clip_probability(value, epsilon=1e-6):
    if value is None:
        return None
    return max(epsilon, min(1.0 - epsilon, float(value)))


def performance_warning_count(caught_warnings):
    return sum(1 for item in caught_warnings if issubclass(item.category, pd.errors.PerformanceWarning))


def boolish(value):
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def finite_float(value):
    if value in (None, ""):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def parse_iso_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def minute_of_day(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if ":" not in text:
        return None
    parts = text.split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except (TypeError, ValueError, IndexError):
        return None
    return hour * 60 + minute


def source_status_kind(item):
    item = item or {}
    status = str(item.get("status") or "").strip().lower()
    ok = boolish(item.get("ok"))
    stale = boolish(item.get("stale"))
    if ok is False or status in {"failed", "error", "missing"}:
        return "failed"
    if stale is True or status in {"stale", "stale_cache", "expired"}:
        return "stale"
    if ok is True or status in {"fresh", "ok", "available"}:
        return "fresh"
    return "unknown"


def source_row_count(item):
    item = item or {}
    explicit = finite_float(item.get("row_count"))
    if explicit is not None:
        return explicit
    data = item.get("data")
    if data is None:
        return 0.0
    if isinstance(data, list):
        return float(len(data))
    if not isinstance(data, dict):
        return 1.0
    for key in ("rows", "observations", "periods", "forecasts", "history"):
        value = data.get(key)
        if isinstance(value, list):
            return float(len(value))
    if data.get("available") is False:
        return 0.0
    return 1.0 if data else 0.0


def source_age_minutes(item, captured_at=None):
    item = item or {}
    for key in ("age_minutes", "cache_age_minutes"):
        value = finite_float(item.get(key))
        if value is not None:
            return value
    if captured_at is None:
        return None
    fetched = parse_iso_datetime(item.get("fetched_at"))
    if fetched is None:
        return None
    captured = captured_at
    if isinstance(captured, str):
        captured = parse_iso_datetime(captured)
    if captured is None:
        return None
    if fetched.tzinfo is None or captured.tzinfo is None:
        return None
    return max(0.0, (captured - fetched).total_seconds() / 60.0)


def latest_source_minute(item):
    item = item or {}
    data = item.get("data")
    rows = []
    if isinstance(data, dict):
        rows = data.get("rows") or data.get("observations") or data.get("history") or []
    elif isinstance(data, list):
        rows = data
    minutes = [
        minute
        for minute in (minute_of_day(row.get("time") or row.get("local_time")) for row in rows)
        if minute is not None
    ]
    return max(minutes) if minutes else None


def source_list_label(sources, limit=3):
    names = sorted(str(source) for source in sources if source not in (None, ""))
    if len(names) <= limit:
        return ",".join(names)
    head = ",".join(names[:limit])
    return f"{head},+{len(names) - limit}"


def source_status_group_from_items(items):
    if not items:
        return "missing_sources"
    by_state = {}
    for source, item in sorted(items.items()):
        state = source_status_kind(item)
        if state == "fresh":
            continue
        by_state.setdefault(state, []).append(source)
    parts = []
    for state in ("failed", "stale", "unknown"):
        if by_state.get(state):
            parts.append(f"{state}:{source_list_label(by_state[state])}")
    return ";".join(parts) if parts else "all_fresh"


def source_items_from_status_rows(rows):
    output = {}
    for row in rows or []:
        source = row.get("source") or "unknown"
        output[source] = {
            "ok": row.get("ok"),
            "status": row.get("status"),
            "stale": row.get("stale"),
            "age_minutes": row.get("age_minutes"),
            "fetched_at": row.get("fetched_at"),
            "row_count": row.get("row_count"),
        }
    return output


def default_dynamic_source_state_features(row=None):
    row = row or {}
    cutoff_hour = finite_float(row.get("cutoff_hour")) or 0.0
    minutes_since_cutoff = finite_float(row.get("minutes_since_cutoff")) or 0.0
    latest_minute = int(cutoff_hour) * 60
    forecast_disagreement = finite_float(row.get("forecast_disagreement")) or 0.0
    features = {
        column: 0.0
        for column in DYNAMIC_SOURCE_NUMERIC_COLUMNS
    }
    features.update({
        "source_status_group": "all_fresh",
        "source_state_all_fresh": 1.0,
        "source_state_missing_sources": 0.0,
        "source_wu_history_fresh": 1.0,
        "source_wu_history_age_minutes": minutes_since_cutoff,
        "source_wu_history_latest_minute": float(latest_minute),
        "source_wu_history_row_count": 1.0,
        "source_forecast_payload_age_minutes": 0.0,
        "source_forecast_max_age_minutes": 0.0,
        "source_cross_source_max_disagreement": forecast_disagreement,
    })
    return features


def dynamic_source_state_features(
    sources=None,
    source_status_rows=None,
    captured_at=None,
    base_features=None,
):
    items = source_items_from_status_rows(source_status_rows) if source_status_rows is not None else {}
    if not items:
        items = {
            source: (sources or {}).get(source) or {}
            for source in DYNAMIC_SOURCE_TRACKED_SOURCES
            if source in (sources or {})
        }
    if not items:
        features = default_dynamic_source_state_features(base_features)
        features["source_status_group"] = "missing_sources"
        features["source_state_all_fresh"] = 0.0
        features["source_state_missing_sources"] = 1.0
        return features

    features = {
        column: 0.0
        for column in DYNAMIC_SOURCE_NUMERIC_COLUMNS
    }
    status_group = source_status_group_from_items(items)
    features["source_status_group"] = status_group
    features["source_state_all_fresh"] = 1.0 if status_group == "all_fresh" else 0.0
    features["source_state_missing_sources"] = 0.0

    state_by_source = {source: source_status_kind(item) for source, item in items.items()}
    features["source_failed_count"] = float(sum(1 for state in state_by_source.values() if state == "failed"))
    features["source_stale_count"] = float(sum(1 for state in state_by_source.values() if state == "stale"))
    features["source_unknown_count"] = float(sum(1 for state in state_by_source.values() if state == "unknown"))

    wu_history = items.get("wu_history") or {}
    wu_state = state_by_source.get("wu_history", "unknown")
    features["source_wu_history_fresh"] = 1.0 if wu_state == "fresh" else 0.0
    features["source_wu_history_stale"] = 1.0 if wu_state == "stale" else 0.0
    features["source_wu_history_failed"] = 1.0 if wu_state == "failed" else 0.0
    features["source_wu_history_row_count"] = source_row_count(wu_history)
    latest_minute = finite_float((base_features or {}).get("latest_wu_history_minute"))
    if latest_minute is None:
        latest_minute = latest_source_minute(wu_history)
    features["source_wu_history_latest_minute"] = latest_minute
    age = source_age_minutes(wu_history, captured_at=captured_at)
    if age is None and latest_minute is not None:
        cutoff_hour = finite_float((base_features or {}).get("cutoff_hour")) or 0.0
        minutes_since_cutoff = finite_float((base_features or {}).get("minutes_since_cutoff")) or 0.0
        wall_minute = int(cutoff_hour) * 60 + minutes_since_cutoff
        age = max(0.0, wall_minute - float(latest_minute))
    features["source_wu_history_age_minutes"] = age

    metar = items.get("metar") or {}
    metar_state = state_by_source.get("metar", "unknown")
    features["source_metar_stale"] = 1.0 if metar_state == "stale" else 0.0
    features["source_metar_failed"] = 1.0 if metar_state == "failed" else 0.0
    features["source_metar_age_minutes"] = source_age_minutes(metar, captured_at=captured_at)

    forecast_ages = []
    for source in DYNAMIC_SOURCE_FORECAST_SOURCES:
        item = items.get(source) or {}
        state = state_by_source.get(source)
        if state == "failed":
            features["source_forecast_failed_count"] += 1.0
        elif state == "stale":
            features["source_forecast_stale_count"] += 1.0
        age = source_age_minutes(item, captured_at=captured_at)
        if age is not None:
            forecast_ages.append(age)
    if forecast_ages:
        features["source_forecast_payload_age_minutes"] = min(forecast_ages)
        features["source_forecast_max_age_minutes"] = max(forecast_ages)
    forecast_disagreement = finite_float((base_features or {}).get("forecast_disagreement"))
    features["source_cross_source_max_disagreement"] = (
        forecast_disagreement if forecast_disagreement is not None else 0.0
    )
    return features


def add_dynamic_source_state_features(
    record,
    sources=None,
    source_status_rows=None,
    captured_at=None,
    historical_default=False,
):
    features = (
        default_dynamic_source_state_features(record)
        if historical_default
        else dynamic_source_state_features(
            sources=sources,
            source_status_rows=source_status_rows,
            captured_at=captured_at,
            base_features=record,
        )
    )
    record.update(features)
    return record


def feature_names_need_dynamic_source_state(feature_names):
    if not feature_names:
        return False
    dynamic_names = set(DYNAMIC_SOURCE_NUMERIC_COLUMNS + DYNAMIC_SOURCE_CATEGORICAL_COLUMNS)
    return any(
        name in dynamic_names or str(name).startswith("source_status_group_")
        for name in feature_names
    )


def temperature_scale_probability(value, temperature=1.0):
    value = clip_probability(value)
    temperature = max(0.05, float(temperature or 1.0))
    logit = math.log(value / (1.0 - value))
    return clip_probability(sigmoid(logit / temperature))


def late_lockin_strength_from_features(record):
    """Serving-side late lock-in proxy for the pooled band candidate.

    It mirrors the production heuristic from ``DistributionMixin`` without
    needing settlement-lag artifacts in this research artifact. The direct band
    model also sees this value as a feature, and replay postprocessing uses it
    to concentrate late, cooling days onto the printed high.
    """
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
    """Deterministic probabilities implied by the printed WU high."""
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
    """Soft cap from non-resolution live support such as METAR/current temp.

    Unlike the WU-history printed high this is not a hard settlement floor, but
    a band entirely below a live observed support bucket should not keep a high
    candidate probability.
    """
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
    """Band probability if the day resolves exactly at the printed high."""
    if floor_bucket is None:
        return None
    return float(band_outcome(kind, value, floor_bucket, value_hi=value_hi))


def family_specs(unit="F"):
    if str(unit or "").lower() == "all":
        return all_specs()
    return [spec for spec in all_specs() if spec.display_unit == unit]


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
    """Return a feature row whose temperature-like values are canonical F.

    The mixed C/F density candidate still uses ``market_id`` as a city feature,
    but the numeric temperature coordinates must share one scale or the model
    learns unit artifacts instead of weather structure.
    """
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


def market_climate_stats(cache):
    buckets = [row.get("bucket") for row in (cache.get("daily") or {}).values()]
    buckets = [float(value) for value in buckets if value is not None]
    if not buckets:
        return {"climate_normal": None, "climate_std": None}
    mean = sum(buckets) / len(buckets)
    if len(buckets) < 2:
        std = 0.0
    else:
        std = math.sqrt(sum((value - mean) ** 2 for value in buckets) / (len(buckets) - 1))
    return {"climate_normal": mean, "climate_std": std}


def market_source_reliability(spec, include_historical_only=False):
    """Static per-market source-quality priors for pooled training.

    These are learned from available daily-source overlaps versus WU, not from
    the same intraday record being scored. They give the pooled model a compact
    city/source trust context without using final redundant-source highs as
    same-day features.
    """
    try:
        indexes = source_daily_indexes(spec)
    except Exception:  # noqa: BLE001 - pooled training should survive missing optional stores
        indexes = {}
    primary_rows = indexes.get(PRIMARY_SOURCE) or {}
    reliability = {column: None for column in SOURCE_RELIABILITY_COLUMNS}
    if include_historical_only:
        reliability.update({column: None for column in HISTORICAL_ONLY_SOURCE_RELIABILITY_COLUMNS})
    if not primary_rows:
        reliability["source_redundant_streams"] = 0.0
        reliability["source_overlap_days"] = 0.0
        return reliability

    overlap_days = 0
    streams = 0
    best_match = None
    best_mae = None
    for source in FALLBACK_ORDER:
        source_rows = indexes.get(source) or {}
        days = sorted(set(primary_rows) & set(source_rows))
        if not days:
            continue
        streams += 1
        overlap_days += len(days)
        truth_rows = []
        for local_date in days:
            truth_rows.append({
                "source_values": {
                    PRIMARY_SOURCE: primary_rows[local_date],
                    source: source_rows[local_date],
                },
            })
        stats = bias_stats_for_source(truth_rows, source)
        prefix = {
            "metar": "source_metar",
            "ghcnh": "source_ghcnh",
            "reanalysis": "source_reanalysis",
        }.get(source)
        if not prefix:
            continue
        match = stats.get("exact_bucket_match_rate")
        mae = stats.get("mae_vs_wu")
        reliability[f"{prefix}_bias"] = stats.get("bias_source_minus_wu")
        reliability[f"{prefix}_mae"] = mae
        reliability[f"{prefix}_bucket_match"] = match
        if match is not None:
            best_match = match if best_match is None else max(best_match, match)
        if mae is not None:
            best_mae = mae if best_mae is None else min(best_mae, mae)
    reliability["source_redundant_streams"] = float(streams)
    reliability["source_overlap_days"] = float(overlap_days)
    reliability["source_best_bucket_match"] = best_match
    reliability["source_best_mae"] = best_mae
    if include_historical_only:
        supplemental_sources = [
            source for source in indexes
            if source.startswith(SUPPLEMENTAL_SOURCE_PREFIX)
        ]
        supplemental_mae = []
        supplemental_match = []
        supplemental_distances = []
        supplemental_overlap_days = 0
        for source in supplemental_sources:
            source_rows = indexes.get(source) or {}
            days = sorted(set(primary_rows) & set(source_rows))
            if not days:
                continue
            supplemental_overlap_days += len(days)
            truth_rows = [
                {
                    "source_values": {
                        PRIMARY_SOURCE: primary_rows[local_date],
                        source: source_rows[local_date],
                    },
                }
                for local_date in days
            ]
            stats = bias_stats_for_source(truth_rows, source)
            if stats.get("mae_vs_wu") is not None:
                supplemental_mae.append(stats.get("mae_vs_wu"))
            if stats.get("exact_bucket_match_rate") is not None:
                supplemental_match.append(stats.get("exact_bucket_match_rate"))
            for row in source_rows.values():
                value = row.get("supplemental_distance_km")
                if value is not None:
                    try:
                        supplemental_distances.append(float(value))
                    except (TypeError, ValueError):
                        pass
        reliability["source_supplemental_available"] = 1.0 if supplemental_sources else 0.0
        reliability["source_supplemental_count"] = float(len(supplemental_sources))
        reliability["source_supplemental_overlap_days"] = float(supplemental_overlap_days)
        reliability["source_supplemental_best_mae"] = min(supplemental_mae) if supplemental_mae else None
        reliability["source_supplemental_best_bucket_match"] = (
            max(supplemental_match) if supplemental_match else None
        )
        reliability["source_supplemental_min_distance_km"] = (
            min(supplemental_distances) if supplemental_distances else None
        )
    return reliability


def historical_only_source_feature_manifest():
    return {
        "feature_family": SUPPLEMENTAL_FEATURE_FAMILY,
        "columns": HISTORICAL_ONLY_SOURCE_RELIABILITY_COLUMNS,
        "historical_only": True,
        "live_serving_eligible": False,
        "default_in_feature_frame": False,
    }


def add_city_features(record, spec, climate, source_reliability=None, include_historical_only=False):
    normal = climate.get("climate_normal")
    high_so_far = record.get("high_so_far")
    forecast_high = record.get("forecast_high")
    record.update({
        "market_id": spec.id,
        "city": spec.city_label,
        "latitude": spec.lat,
        "longitude": spec.lon,
        "coastal": 1.0 if spec.coastal else 0.0,
        "climate_normal": normal,
        "climate_std": climate.get("climate_std"),
        "high_so_far_anomaly": high_so_far - normal
        if high_so_far is not None and normal is not None else None,
        "forecast_anomaly": forecast_high - normal
        if forecast_high is not None and normal is not None else None,
    })
    for column in SOURCE_RELIABILITY_COLUMNS:
        record[column] = (source_reliability or {}).get(column)
    if include_historical_only:
        for column in HISTORICAL_ONLY_SOURCE_RELIABILITY_COLUMNS:
            record[column] = (source_reliability or {}).get(column)
    return record


def plausible_native_bucket(bucket, unit):
    if bucket is None:
        return False
    try:
        bucket = int(bucket)
    except (TypeError, ValueError):
        return False
    if unit == "F":
        return 30 <= bucket <= 125
    return -45 <= bucket <= 55


def build_market_records(spec, cutoff_hours=INTRADAY_CUTOFF_HOURS, max_days=None):
    model = TorontoHighTempModel(market_id=spec.id)
    cache = model.historical_target_cache()
    daily = cache.get("daily") or {}
    by_date = cache.get("by_date") or {}
    forecast_index = load_forecast_daily(daily_path_for(spec))
    forecast_profiles = load_forecast_profiles(long_path_for(spec))
    reanalysis_synoptic_index = load_reanalysis_synoptic_features(spec=spec)
    climate = market_climate_stats(cache)
    source_reliability = market_source_reliability(spec)
    dates = sorted(daily.keys())
    if max_days and max_days > 0:
        dates = dates[-int(max_days):]

    records = []
    wall_offsets = (0, 15, 30, 45)
    for local_date in dates:
        rows = by_date.get(local_date, [])
        if not rows:
            continue
        for hour in cutoff_hours:
            offset = wall_offsets[(local_date.toordinal() + int(hour)) % len(wall_offsets)]
            record = build_historical_feature_record(
                local_date,
                rows,
                daily[local_date],
                int(hour),
                forecast_high=forecast_index.get(local_date.isoformat()),
                forecast_profile_rows=forecast_profiles.get(local_date.isoformat()),
                reanalysis_synoptic_features=reanalysis_synoptic_index.get(local_date.isoformat()),
                wind_group_fn=model.wind_group,
                cloud_group_fn=model.cloud_group,
                microclimate_feature_fn=model.microclimate_features,
                wall_minute=int(hour) * 60 + offset,
            )
            if not record or record.get("final_bucket") is None:
                continue
            if not plausible_native_bucket(record.get("final_bucket"), spec.display_unit):
                continue
            record["cutoff_hour"] = int(hour)
            add_city_features(record, spec, climate, source_reliability=source_reliability)
            add_dynamic_source_state_features(record, historical_default=True)
            record["year"] = int(local_date.year)
            records.append(record)
    return records


def build_family_dataset(unit="F", cutoff_hours=INTRADAY_CUTOFF_HOURS, max_days_per_market=None):
    specs = family_specs(unit)
    records = []
    counts = {}
    for spec in specs:
        market_records = build_market_records(
            spec,
            cutoff_hours=cutoff_hours,
            max_days=max_days_per_market,
        )
        counts[spec.id] = len(market_records)
        records.extend(market_records)
    return records, counts


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
    """Add market-band context to one pooled feature row.

    The v0.2 candidate predicts the binary market contract directly. These
    features tell the model where the band sits relative to the printed floor,
    forecast, live reading, and city climate.
    """
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
    use = (
        base_numeric
        + city_numeric
        + BAND_NUMERIC_COLUMNS
        + categorical
    )
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


def synthetic_band_rows_for_record(record, support, exact_radius=7, tail_stride=1):
    final = round_half_up(record.get("final_bucket"))
    if final is None:
        return []
    support = sorted(int(value) for value in support)
    centers = [
        value for value in (
            final,
            round_half_up(record.get("high_so_far")),
            round_half_up(record.get("forecast_high")),
            round_half_up(record.get("live_reading_temp")),
            round_half_up(record.get("climate_normal")),
        )
        if value is not None
    ]
    if not centers:
        centers = [final]
    low = max(min(support), min(centers) - exact_radius)
    high = min(max(support), max(centers) + exact_radius)
    rows = []

    def add(kind, value, value_hi=None):
        band = band_prediction_record(record, kind, value, value_hi=value_hi)
        outcome = band_outcome(kind, value, final, value_hi=value_hi)
        if outcome is None:
            return
        band["outcome"] = outcome
        distance = 0
        if kind == "lte":
            distance = max(0, final - int(value))
        elif kind == "gte":
            distance = max(0, int(value) - final)
        else:
            hi = int(value_hi) if value_hi is not None else int(value)
            distance = 0 if int(value) <= final <= hi else min(abs(final - int(value)), abs(final - hi))
        band["settlement_distance"] = distance
        # The replay blocker was overwhelmingly exact winning buckets and
        # late-day lock-in, so positives and late rows receive extra weight.
        weight = 1.0
        if outcome:
            weight *= 4.0 if kind == "eq" else 2.0
        if distance == 0:
            weight *= 1.5
        if int(record.get("cutoff_hour") or 0) >= 16:
            weight *= 2.0
        band["_sample_weight"] = weight
        rows.append(band)

    for value in range(low, high + 1):
        add("eq", value)
    for value in range(low, high):
        add("eq", value, value_hi=value + 1)
    for value in range(low, high + 1, max(1, int(tail_stride))):
        add("lte", value)
        add("gte", value)
    return rows


def build_band_rows(records, support):
    rows = []
    for record in records:
        rows.extend(synthetic_band_rows_for_record(record, support))
    return rows


def train_hour_model(train_rows, feature_names=None):
    build_started = time.perf_counter()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", pd.errors.PerformanceWarning)
        train_frame = feature_frame(train_rows, feature_names=feature_names)
    build_seconds = time.perf_counter() - build_started
    feature_names = list(train_frame.columns)
    imputer = SimpleImputer(strategy="median")
    x_train = imputer.fit_transform(train_frame)
    y_train = np.array([int(row["final_bucket"]) for row in train_rows])
    model = HistGradientBoostingClassifier(
        max_iter=80,
        max_leaf_nodes=21,
        learning_rate=0.05,
        random_state=42,
    )
    fit_started = time.perf_counter()
    model.fit(x_train, y_train)
    fit_seconds = time.perf_counter() - fit_started
    metrics = {
        "matrix_rows": int(train_frame.shape[0]),
        "matrix_columns": int(train_frame.shape[1]),
        "matrix_build_seconds": round(build_seconds, 6),
        "model_fit_seconds": round(fit_seconds, 6),
        "performance_warning_count": performance_warning_count(caught),
    }
    return model, imputer, feature_names, metrics


def predict_rows(model, imputer, feature_names, rows, support=None, epsilon=1e-4):
    frame = feature_frame(rows, feature_names=feature_names)
    x_eval = imputer.transform(frame)
    probabilities = model.predict_proba(x_eval)
    classes = [int(value) for value in model.classes_]
    support = sorted(set(support or classes) | set(classes))
    output = []
    for row in probabilities:
        dist = {bucket: float(epsilon) for bucket in support}
        for bucket, probability in zip(classes, row):
            dist[int(bucket)] = dist.get(int(bucket), 0.0) + float(probability)
        total = sum(dist.values())
        output.append({bucket: probability / total for bucket, probability in dist.items()})
    return output


def distribution_probability(distribution, bucket):
    return float(distribution.get(int(bucket), 0.0))


def evaluate_distributions(rows, distributions):
    if not rows:
        return None
    losses = []
    briers = []
    classes = sorted({int(row["final_bucket"]) for row in rows} | {
        bucket for dist in distributions for bucket in dist
    })
    for row, dist in zip(rows, distributions):
        y_bucket = int(row["final_bucket"])
        probs = [float(dist.get(bucket, 0.0)) for bucket in classes]
        total = sum(probs)
        if total <= 0:
            probs = [1.0 / len(classes)] * len(classes)
        else:
            probs = [p / total for p in probs]
        p_true = max(1e-15, probs[classes.index(y_bucket)])
        losses.append(-math.log(p_true))
        briers.append(brier(distribution_probability(dist, y_bucket), 1.0))
    return {
        "n": len(rows),
        "logloss": sum(losses) / len(losses),
        "winning_bucket_brier": sum(briers) / len(briers),
    }


def train_density_hour_model(train_rows, feature_names=None):
    build_started = time.perf_counter()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", pd.errors.PerformanceWarning)
        train_frame = feature_frame(train_rows, feature_names=feature_names)
    build_seconds = time.perf_counter() - build_started
    feature_names = list(train_frame.columns)
    imputer = SimpleImputer(strategy="median")
    x_train = imputer.fit_transform(train_frame)
    y_train = np.array([float(row["final_bucket_f"]) for row in train_rows])
    model = HistGradientBoostingRegressor(
        max_iter=120,
        max_leaf_nodes=31,
        learning_rate=0.05,
        random_state=42,
    )
    fit_started = time.perf_counter()
    model.fit(x_train, y_train)
    fit_seconds = time.perf_counter() - fit_started
    fitted = model.predict(x_train)
    residuals = [float(actual - predicted) for actual, predicted in zip(y_train, fitted)]
    metrics = {
        "matrix_rows": int(train_frame.shape[0]),
        "matrix_columns": int(train_frame.shape[1]),
        "matrix_build_seconds": round(build_seconds, 6),
        "model_fit_seconds": round(fit_seconds, 6),
        "performance_warning_count": performance_warning_count(caught),
    }
    return model, imputer, feature_names, residuals, metrics


def residual_sigma_f(residuals, floor=0.75, cap=10.0):
    clean = [float(value) for value in residuals or [] if value is not None and math.isfinite(float(value))]
    if not clean:
        return 3.0
    rmse = math.sqrt(sum(value * value for value in clean) / len(clean))
    return max(float(floor), min(float(cap), rmse))


def density_residuals_from_means(rows, means):
    residuals = []
    for row, mean_f in zip(rows or [], means or []):
        target_f = row.get("final_bucket_f")
        if target_f is None or mean_f is None:
            continue
        try:
            residual = float(target_f) - float(mean_f)
        except (TypeError, ValueError):
            continue
        if math.isfinite(residual):
            residuals.append(residual)
    return residuals


def density_support_f(rows, margin_f=15.0):
    targets = [
        float(row["final_bucket_f"])
        for row in rows or []
        if row.get("final_bucket_f") is not None
    ]
    if not targets:
        return 30.0, 125.0
    low = math.floor(min(targets) - float(margin_f))
    high = math.ceil(max(targets) + float(margin_f))
    return max(-40.0, float(low)), min(130.0, float(high))


def gaussian_density_f(mean_f, sigma_f, grid_f):
    sigma_f = max(0.1, float(sigma_f or 1.0))
    density = {
        float(value): math.exp(-0.5 * ((float(value) - float(mean_f)) / sigma_f) ** 2)
        for value in grid_f
    }
    return continuous_density_payload(density, mean_f=float(mean_f), sigma_f=sigma_f)


def predict_density_means(model, imputer, feature_names, rows):
    if not rows:
        return []
    frame = feature_frame(rows, feature_names=feature_names)
    x_eval = imputer.transform(frame)
    return [float(value) for value in model.predict(x_eval)]


def predict_density_payloads(model, imputer, feature_names, rows, sigma_f, grid_f):
    means = predict_density_means(model, imputer, feature_names, rows)
    return [gaussian_density_f(mean, sigma_f, grid_f) for mean in means]


def density_winning_probability(row, payload):
    unit = record_unit(row)
    final_bucket = row.get("final_bucket")
    if final_bucket is None:
        return None
    return band_probability_from_density(
        payload.get("density_f") or {},
        unit,
        "eq",
        final_bucket,
    )


def evaluate_density_predictions(rows, payloads):
    if not rows:
        return None
    losses = []
    briers = []
    absolute_errors = []
    for row, payload in zip(rows, payloads):
        probability = density_winning_probability(row, payload)
        if probability is None:
            continue
        probability = max(1e-15, min(1.0, float(probability)))
        losses.append(-math.log(probability))
        briers.append(brier(probability, 1.0))
        target_f = native_value_to_f(row.get("final_bucket"), record_unit(row))
        mean_f = (payload or {}).get("mean_f")
        if target_f is not None and mean_f is not None:
            absolute_errors.append(abs(float(mean_f) - float(target_f)))
    if not losses:
        return None
    return {
        "n": len(losses),
        "density_logloss": sum(losses) / len(losses),
        "winning_bucket_brier": sum(briers) / len(briers),
        "mean_absolute_error_f": (
            sum(absolute_errors) / len(absolute_errors)
            if absolute_errors else None
        ),
    }


def train_band_hour_model(train_rows, feature_names=None, include_dynamic_source_state=False):
    build_started = time.perf_counter()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", pd.errors.PerformanceWarning)
        train_frame = band_feature_frame(
            train_rows,
            feature_names=feature_names,
            include_dynamic_source_state=include_dynamic_source_state,
        )
    build_seconds = time.perf_counter() - build_started
    feature_names = list(train_frame.columns)
    imputer = SimpleImputer(strategy="median")
    x_train = imputer.fit_transform(train_frame)
    y_train = np.array([int(row["outcome"]) for row in train_rows])
    weights = np.array([float(row.get("_sample_weight", 1.0)) for row in train_rows])
    model = HistGradientBoostingClassifier(
        max_iter=90,
        max_leaf_nodes=31,
        learning_rate=0.05,
        random_state=42,
    )
    fit_started = time.perf_counter()
    model.fit(x_train, y_train, sample_weight=weights)
    fit_seconds = time.perf_counter() - fit_started
    metrics = {
        "matrix_rows": int(train_frame.shape[0]),
        "matrix_columns": int(train_frame.shape[1]),
        "matrix_build_seconds": round(build_seconds, 6),
        "model_fit_seconds": round(fit_seconds, 6),
        "performance_warning_count": performance_warning_count(caught),
    }
    return model, imputer, feature_names, metrics


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


def apply_band_postprocessing(probability, row, config=None):
    """Hard floor first, then calibrated live-floor postprocessing."""
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
    return clip_probability(p)


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
    """Context fallbacks for market-specific above-floor eq/range leakage."""
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


def fit_adjacent_calibration(
    rows,
    probabilities,
    min_rows=80,
    prior_rows=120.0,
    factor_min=0.15,
    factor_max=2.50,
):
    """Fit multiplicative calibration factors for above-floor eq/range bands."""
    stats = defaultdict(lambda: {"n": 0, "outcome_sum": 0.0, "prob_sum": 0.0})
    for row, probability in zip(rows, probabilities):
        contexts = adjacent_calibration_contexts(row)
        if not contexts:
            continue
        try:
            probability = clip_probability(probability)
            outcome = float(row.get("outcome") or 0.0)
        except (TypeError, ValueError):
            continue
        for context in contexts:
            stats[context]["n"] += 1
            stats[context]["outcome_sum"] += outcome
            stats[context]["prob_sum"] += probability

    contexts = {}
    for context, stat in sorted(stats.items()):
        n = int(stat["n"])
        if n < int(min_rows):
            continue
        prob_sum = float(stat["prob_sum"])
        if prob_sum <= 0:
            continue
        mean_probability = prob_sum / n
        # Smooth toward factor 1.0 by adding prior rows with the model's own
        # mean probability. This keeps sparse city/hour cells from becoming a
        # second model trained on noise.
        smoothed_observed = (
            float(stat["outcome_sum"]) + mean_probability * float(prior_rows)
        ) / (n + float(prior_rows))
        smoothed_predicted = (
            prob_sum + mean_probability * float(prior_rows)
        ) / (n + float(prior_rows))
        if smoothed_predicted <= 0:
            continue
        factor = smoothed_observed / smoothed_predicted
        factor = max(float(factor_min), min(float(factor_max), factor))
        contexts[context] = {
            "factor": factor,
            "n": n,
            "observed_rate": float(stat["outcome_sum"]) / n,
            "mean_probability": mean_probability,
        }

    return {
        "version": "adjacent_market_hour_floor_gap_v1",
        "min_rows": int(min_rows),
        "prior_rows": float(prior_rows),
        "factor_min": float(factor_min),
        "factor_max": float(factor_max),
        "context_count": len(contexts),
        "contexts": contexts,
    }


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
    """Context fallbacks for no-market exact/range winner catch-up.

    Contexts only use fields available at inference. Outcome and settlement
    distance are used to fit the calibration, never to apply it live.
    """
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


def fit_exact_winner_catchup(
    rows,
    probabilities,
    min_rows=80,
    prior_rows=160.0,
    factor_min=0.50,
    factor_max=1.80,
    guardrail_rows=None,
    guardrail_probabilities=None,
    strength_grid=None,
    one_above_tolerance=0.0002,
    normalization_gamma=1.25,
):
    """Fit smoothed factors for exact/range winner catch-up contexts."""
    stats = defaultdict(lambda: {"n": 0, "outcome_sum": 0.0, "prob_sum": 0.0})
    for row, probability in zip(rows, probabilities):
        contexts = exact_winner_catchup_contexts(row)
        if not contexts:
            continue
        probability = clip_probability(probability)
        try:
            outcome = float(row.get("outcome") or 0.0)
        except (TypeError, ValueError):
            continue
        for context in contexts:
            stats[context]["n"] += 1
            stats[context]["outcome_sum"] += outcome
            stats[context]["prob_sum"] += probability

    contexts = {}
    for context, stat in sorted(stats.items()):
        n = int(stat["n"])
        if n < int(min_rows):
            continue
        prob_sum = float(stat["prob_sum"])
        if prob_sum <= 0:
            continue
        mean_probability = prob_sum / n
        smoothed_observed = (
            float(stat["outcome_sum"]) + mean_probability * float(prior_rows)
        ) / (n + float(prior_rows))
        smoothed_predicted = (
            prob_sum + mean_probability * float(prior_rows)
        ) / (n + float(prior_rows))
        if smoothed_predicted <= 0:
            continue
        factor = smoothed_observed / smoothed_predicted
        factor = max(float(factor_min), min(float(factor_max), factor))
        contexts[context] = {
            "factor": factor,
            "n": n,
            "observed_rate": float(stat["outcome_sum"]) / n,
            "mean_probability": mean_probability,
        }

    calibration = {
        "version": "pooled_feature_band_hgb_v0.4",
        "min_rows": int(min_rows),
        "prior_rows": float(prior_rows),
        "factor_min": float(factor_min),
        "factor_max": float(factor_max),
        "strength": 1.0,
        "context_count": len(contexts),
        "contexts": contexts,
    }
    if guardrail_rows is not None and guardrail_probabilities is not None:
        diagnostics = select_exact_winner_catchup_strength(
            guardrail_rows,
            guardrail_probabilities,
            calibration,
            strength_grid=strength_grid,
            one_above_tolerance=one_above_tolerance,
            normalization_gamma=normalization_gamma,
        )
        calibration["strength"] = diagnostics["selected_strength"]
        calibration["strength_diagnostics"] = diagnostics
    return calibration


def _exact_strength_grid(values=None):
    if values is None:
        values = (1.0, 0.90, 0.80, 0.70, 0.60, 0.50, 0.40, 0.30, 0.20, 0.10, 0.0)
    cleaned = []
    for value in values:
        try:
            strength = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            continue
        if strength not in cleaned:
            cleaned.append(strength)
    return cleaned or [0.0]


def _with_exact_strength(calibration, strength):
    copy = dict(calibration or {})
    copy["strength"] = max(0.0, min(1.0, float(strength)))
    return copy


def _settlement_distance_value(row):
    value = row.get("settlement_distance")
    if value in (None, ""):
        value = row.get("settlement_distance_bucket")
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _band_validation_partition_key(row):
    return (
        row.get("market_id") or "unknown",
        row.get("target_date") or row.get("date") or "unknown",
        row.get("cutoff_hour") or row.get("candidate_cutoff_hour") or "unknown",
    )


def normalize_band_probabilities_for_rows(rows, probabilities, gamma=1.25):
    """Mirror replay partition normalization for held-out training rows."""
    gamma = max(0.1, float(gamma or 1.0))
    output = [clip_probability(probability) for probability in probabilities]
    grouped = defaultdict(list)
    for idx, row in enumerate(rows):
        grouped[_band_validation_partition_key(row)].append(idx)
    for indexes in grouped.values():
        weights = [max(1e-12, output[idx]) ** gamma for idx in indexes]
        total = sum(weights)
        if total <= 0:
            continue
        for idx, weight in zip(indexes, weights):
            output[idx] = weight / total
    return output


def _slice_brier(rows, probabilities, predicate):
    pairs = [
        (row, float(probability))
        for row, probability in zip(rows, probabilities)
        if predicate(row) and row.get("outcome") is not None
    ]
    if not pairs:
        return {"n": 0, "brier": None, "base_rate": None, "mean_probability": None}
    return {
        "n": len(pairs),
        "brier": sum(brier(probability, int(row["outcome"])) for row, probability in pairs) / len(pairs),
        "base_rate": sum(int(row["outcome"]) for row, _ in pairs) / len(pairs),
        "mean_probability": sum(probability for _, probability in pairs) / len(pairs),
    }


def _strength_candidate_probabilities(rows, probabilities, calibration, strength, normalization_gamma=1.25):
    config = {"exact_winner_catchup": _with_exact_strength(calibration, strength)}
    adjusted = [
        apply_exact_winner_catchup(probability, row, config=config)
        for row, probability in zip(rows, probabilities)
    ]
    return normalize_band_probabilities_for_rows(rows, adjusted, gamma=normalization_gamma)


def select_exact_winner_catchup_strength(
    rows,
    probabilities,
    calibration,
    strength_grid=None,
    one_above_tolerance=0.0002,
    normalization_gamma=1.25,
):
    """Select the strongest exact-winner boost that protects adjacent rows."""
    rows = list(rows or [])
    probabilities = [clip_probability(probability) for probability in (probabilities or [])]
    grid = _exact_strength_grid(strength_grid)
    baseline = normalize_band_probabilities_for_rows(rows, probabilities, gamma=normalization_gamma)
    baseline_distance0 = _slice_brier(rows, baseline, lambda row: _settlement_distance_value(row) == 0)
    baseline_one_above = _slice_brier(rows, baseline, lambda row: _settlement_distance_value(row) == 1)
    baseline_eq = _slice_brier(rows, baseline, lambda row: row.get("band_kind") == "eq")

    candidates = []
    selected = None
    for strength in grid:
        candidate = _strength_candidate_probabilities(
            rows,
            probabilities,
            calibration,
            strength,
            normalization_gamma=normalization_gamma,
        )
        distance0 = _slice_brier(rows, candidate, lambda row: _settlement_distance_value(row) == 0)
        one_above = _slice_brier(rows, candidate, lambda row: _settlement_distance_value(row) == 1)
        eq = _slice_brier(rows, candidate, lambda row: row.get("band_kind") == "eq")
        distance0_delta = (
            distance0["brier"] - baseline_distance0["brier"]
            if distance0["brier"] is not None and baseline_distance0["brier"] is not None
            else None
        )
        one_above_delta = (
            one_above["brier"] - baseline_one_above["brier"]
            if one_above["brier"] is not None and baseline_one_above["brier"] is not None
            else None
        )
        eq_delta = (
            eq["brier"] - baseline_eq["brier"]
            if eq["brier"] is not None and baseline_eq["brier"] is not None
            else None
        )
        passed = (
            (distance0_delta is None or distance0_delta <= 0.0)
            and (one_above_delta is None or one_above_delta <= float(one_above_tolerance))
        )
        item = {
            "strength": strength,
            "passed": bool(passed),
            "distance0_brier": distance0["brier"],
            "distance0_delta_vs_base": distance0_delta,
            "one_above_brier": one_above["brier"],
            "one_above_delta_vs_base": one_above_delta,
            "eq_brier": eq["brier"],
            "eq_delta_vs_base": eq_delta,
        }
        candidates.append(item)
        if passed and selected is None:
            selected = item
    if selected is None:
        fallback_strength = 0.0 if 0.0 in grid else grid[-1]
        selected = next(
            (item for item in candidates if item["strength"] == fallback_strength),
            candidates[-1] if candidates else {"strength": 0.0},
        )
    return {
        "selected_strength": float(selected["strength"]),
        "one_above_tolerance": float(one_above_tolerance),
        "normalization_gamma": float(normalization_gamma),
        "baseline": {
            "distance0_brier": baseline_distance0["brier"],
            "distance0_n": baseline_distance0["n"],
            "one_above_brier": baseline_one_above["brier"],
            "one_above_n": baseline_one_above["n"],
            "eq_brier": baseline_eq["brier"],
            "eq_n": baseline_eq["n"],
        },
        "selected": selected,
        "candidates": candidates,
    }


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


def evaluate_band_predictions(rows, probabilities):
    if not rows:
        return None
    losses = [
        brier(float(probability), int(row["outcome"]))
        for row, probability in zip(rows, probabilities)
    ]
    log_losses = [
        binary_log_loss(float(probability), int(row["outcome"]))
        for row, probability in zip(rows, probabilities)
    ]
    positives = [
        (row, probability)
        for row, probability in zip(rows, probabilities)
        if int(row["outcome"]) == 1
    ]
    exact_winners = [
        (row, probability)
        for row, probability in positives
        if row.get("band_kind") == "eq" and int(row.get("settlement_distance") or 0) == 0
    ]
    late_rows = [
        (row, probability)
        for row, probability in zip(rows, probabilities)
        if int(row.get("cutoff_hour") or 0) >= 16
    ]
    return {
        "n": len(rows),
        "base_rate": sum(int(row["outcome"]) for row in rows) / len(rows),
        "brier": sum(losses) / len(losses),
        "logloss": sum(log_losses) / len(log_losses),
        "positive_mean_p": (
            sum(float(probability) for _, probability in positives) / len(positives)
            if positives else None
        ),
        "exact_winner_mean_p": (
            sum(float(probability) for _, probability in exact_winners) / len(exact_winners)
            if exact_winners else None
        ),
        "late_brier": (
            sum(brier(float(probability), int(row["outcome"])) for row, probability in late_rows) / len(late_rows)
            if late_rows else None
        ),
    }


def tune_temperature(rows, raw_probabilities):
    if not rows:
        return 1.0, None
    grid = [0.45, 0.55, 0.65, 0.75, 0.85, 1.0, 1.15, 1.30, 1.50, 1.75, 2.0]
    best = (1.0, float("inf"))
    for temperature in grid:
        probs = [temperature_scale_probability(p, temperature=temperature) for p in raw_probabilities]
        score = sum(brier(p, int(row["outcome"])) for row, p in zip(rows, probs)) / len(rows)
        if score < best[1]:
            best = (temperature, score)
    return best[0], best[1]


def train_pooled_models(records, holdout_year=None):
    by_hour = defaultdict(list)
    for row in records:
        by_hour[int(row["cutoff_hour"])].append(row)

    artifact = {
        "schema_version": "pooled_feature_hgb_v0.1",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "family_unit": "F",
        "trained_at": datetime.now().isoformat(),
        "support": sorted({int(row["final_bucket"]) for row in records}),
        "blocked_validation": blocked_validation_audit(records),
        "models": {},
    }
    support = artifact["support"]
    validation_rows = []
    for hour, hour_rows in sorted(by_hour.items()):
        if holdout_year is None:
            train_rows = hour_rows
            eval_rows = []
        else:
            train_rows = [row for row in hour_rows if int(row["year"]) != int(holdout_year)]
            eval_rows = [row for row in hour_rows if int(row["year"]) == int(holdout_year)]
        if len(train_rows) < 50:
            continue
        model, imputer, feature_names, train_metrics = train_hour_model(train_rows)
        eval_score = None
        market_scores = []
        if eval_rows:
            predictions = predict_rows(model, imputer, feature_names, eval_rows, support=support)
            eval_score = evaluate_distributions(eval_rows, predictions)
            for market_id in sorted({row["market_id"] for row in eval_rows}):
                market_eval = [row for row in eval_rows if row["market_id"] == market_id]
                market_predictions = [
                    pred for row, pred in zip(eval_rows, predictions)
                    if row["market_id"] == market_id
                ]
                score = evaluate_distributions(market_eval, market_predictions)
                if score:
                    market_scores.append({"market_id": market_id, **score})

        final_model, final_imputer, final_feature_names, final_metrics = train_hour_model(hour_rows)
        artifact["models"][str(hour)] = {
            "model": final_model,
            "imputer": final_imputer,
            "feature_names": final_feature_names,
            "classes": [int(value) for value in final_model.classes_],
            "train_rows": len(hour_rows),
            "training_metrics": final_metrics,
        }
        validation_rows.append({
            "hour": hour,
            "train_rows": len(train_rows),
            "eval_rows": len(eval_rows),
            "eval_score": eval_score,
            "market_scores": market_scores,
            "training_metrics": train_metrics,
            "blocked_validation": blocked_validation_audit(hour_rows),
        })
    return artifact, validation_rows


def default_band_postprocess(exact_winner_catchup_enabled=False):
    config = {
        "hard_floor_enabled": True,
        "support_floor_enabled": True,
        "support_floor_one_below_cap": 0.08,
        "support_floor_decay": 0.25,
        "late_lockin_enabled": True,
        "late_lockin_max_strength": 0.85,
        "adjacent_calibration_enabled": True,
        "adjacent_calibration": {},
        "exact_winner_catchup_enabled": bool(exact_winner_catchup_enabled),
        "exact_winner_catchup": {},
        "partition_normalization_enabled": True,
        "partition_normalization_gamma": 1.25,
        "current_blend_enabled": True,
        "current_blend_default_alpha": 1.0,
        "current_blend_market_alpha": {
            "dallas": 0.0,
            "denver": 0.20,
            "houston": 0.20,
            "los-angeles": 0.20,
            "miami": 0.0,
            "nyc": 0.20,
            "san-francisco": 0.0,
            "seattle": 0.20,
        },
    }
    if exact_winner_catchup_enabled:
        # Item 70 is a catch-up shadow lane. Keep incumbent blending disabled
        # except for markets that cleared paired full-replay guardrails.
        config["current_blend_default_alpha"] = 0.0
        config["current_blend_market_alpha"] = {
            "chicago": 0.10,
            "houston": 0.10,
            "nyc": 0.10,
            "seattle": 0.10,
        }
    return config


def train_pooled_density_models(records, holdout_year=None, grid_step_f=0.1, min_sigma_validation_residuals=20):
    canonical_records = [
        row for row in canonical_density_records(records)
        if row.get("final_bucket_f") is not None
    ]
    by_hour = defaultdict(list)
    for row in canonical_records:
        by_hour[int(row["cutoff_hour"])].append(row)

    low_f, high_f = density_support_f(canonical_records)
    grid_f = canonical_grid_f(low_f, high_f, grid_step_f)
    artifact = {
        "schema_version": "pooled_continuous_density_hgb_v0.2",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "family_unit": "all",
        "prediction_mode": "continuous_density_f",
        "objective": "canonical_f_density_gaussian_residual_holdout_sigma",
        "trained_at": datetime.now().isoformat(),
        "grid_low_f": low_f,
        "grid_high_f": high_f,
        "grid_step_f": float(grid_step_f),
        "sigma_policy": {
            "preferred": "holdout_residual_rmse",
            "fallback": "in_sample_residual_rmse",
            "min_validation_residuals": int(min_sigma_validation_residuals),
        },
        "blocked_validation": blocked_validation_audit(canonical_records),
        "models": {},
    }
    validation_rows = []
    for hour, hour_rows in sorted(by_hour.items()):
        if holdout_year is None:
            train_rows = hour_rows
            eval_rows = []
        else:
            train_rows = [row for row in hour_rows if int(row["year"]) != int(holdout_year)]
            eval_rows = [row for row in hour_rows if int(row["year"]) == int(holdout_year)]
        if len(train_rows) < 20:
            continue
        model, imputer, feature_names, residuals, train_metrics = train_density_hour_model(train_rows)
        sigma_f = residual_sigma_f(residuals)
        eval_score = None
        market_scores = []
        eval_residuals = []
        if eval_rows:
            eval_means = predict_density_means(
                model,
                imputer,
                feature_names,
                eval_rows,
            )
            eval_residuals = density_residuals_from_means(eval_rows, eval_means)
            predictions = [gaussian_density_f(mean, sigma_f, grid_f) for mean in eval_means]
            eval_score = evaluate_density_predictions(eval_rows, predictions)
            for market_id in sorted({row["market_id"] for row in eval_rows}):
                subset = [
                    (row, payload)
                    for row, payload in zip(eval_rows, predictions)
                    if row["market_id"] == market_id
                ]
                score = evaluate_density_predictions(
                    [row for row, _ in subset],
                    [payload for _, payload in subset],
                )
                if score:
                    market_scores.append({"market_id": market_id, **score})

        final_model, final_imputer, final_feature_names, final_residuals, final_metrics = train_density_hour_model(hour_rows)
        if len(eval_residuals) >= int(min_sigma_validation_residuals):
            final_sigma_source = "holdout_residual_rmse"
            final_sigma_residuals = eval_residuals
        else:
            final_sigma_source = "in_sample_residual_rmse"
            final_sigma_residuals = final_residuals
        final_sigma_f = residual_sigma_f(final_sigma_residuals)
        artifact["models"][str(hour)] = {
            "model": final_model,
            "imputer": final_imputer,
            "feature_names": final_feature_names,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "train_rows": len(hour_rows),
            "sigma_f": final_sigma_f,
            "sigma_source": final_sigma_source,
            "sigma_residual_count": len(final_sigma_residuals),
            "training_metrics": final_metrics,
        }
        validation_rows.append({
            "hour": hour,
            "train_rows": len(train_rows),
            "eval_rows": len(eval_rows),
            "sigma_f": sigma_f,
            "final_sigma_f": final_sigma_f,
            "final_sigma_source": final_sigma_source,
            "final_sigma_residual_count": len(final_sigma_residuals),
            "holdout_sigma_residual_count": len(eval_residuals),
            "eval_score": eval_score,
            "market_scores": market_scores,
            "training_metrics": train_metrics,
            "blocked_validation": blocked_validation_audit(hour_rows),
        })
    return artifact, validation_rows


def predict_density_rows_for_bundle(bundle, rows):
    if not bundle or not rows:
        return []
    rows = canonical_density_records(rows)
    grid_f = canonical_grid_f(
        bundle.get("grid_low_f", 30.0),
        bundle.get("grid_high_f", 125.0),
        bundle.get("grid_step_f", 0.1),
    )
    output = []
    for row in rows:
        hour = str(int(row.get("cutoff_hour")))
        model_bundle = (bundle.get("models") or {}).get(hour)
        if not model_bundle:
            output.append(None)
            continue
        output.append(
            predict_density_payloads(
                model_bundle["model"],
                model_bundle["imputer"],
                model_bundle["feature_names"],
                [row],
                model_bundle.get("sigma_f", 3.0),
                grid_f,
            )[0]
        )
    return output


def train_pooled_band_models(
    records,
    holdout_year=None,
    exact_winner_catchup=False,
    dynamic_source_state=False,
):
    if exact_winner_catchup and dynamic_source_state:
        raise ValueError("exact_winner_catchup and dynamic_source_state are separate shadow variants")
    by_hour = defaultdict(list)
    for row in records:
        by_hour[int(row["cutoff_hour"])].append(row)

    support = sorted({int(row["final_bucket"]) for row in records})
    schema_version = "pooled_feature_band_hgb_v0.3"
    objective = "binary_market_band_brier_source_reliability"
    if exact_winner_catchup:
        schema_version = "pooled_feature_band_hgb_v0.4"
        objective = "binary_market_band_brier_source_reliability_exact_winner_catchup"
    if dynamic_source_state:
        schema_version = "pooled_feature_band_hgb_v0.5"
        objective = "binary_market_band_brier_dynamic_source_state"
    artifact = {
        "schema_version": schema_version,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "family_unit": "F",
        "prediction_mode": "band_binary",
        "objective": objective,
        "dynamic_source_state_enabled": bool(dynamic_source_state),
        "dynamic_source_state_columns": (
            DYNAMIC_SOURCE_NUMERIC_COLUMNS + DYNAMIC_SOURCE_CATEGORICAL_COLUMNS
            if dynamic_source_state else []
        ),
        "trained_at": datetime.now().isoformat(),
        "support": support,
        "blocked_validation": blocked_validation_audit(records),
        "models": {},
        "postprocess": default_band_postprocess(
            exact_winner_catchup_enabled=exact_winner_catchup,
        ),
    }
    if dynamic_source_state:
        artifact["postprocess"]["current_blend_source_freshness_default_alpha"] = 0.0
        artifact["postprocess"]["current_blend_source_freshness_alpha"] = {
            "all_fresh": 1.0,
            "failed:local_history": 1.0,
            "failed:metar,wu_history": 1.0,
            "failed:wu_history;stale:metar": 1.0,
            "stale:metar": 1.0,
            "failed:metar": 0.0,
            "failed:wu_history": 0.0,
        }
        artifact["postprocess"]["current_blend_market_alpha"] = {
            **(artifact["postprocess"].get("current_blend_market_alpha") or {}),
            "miami": 0.0,
        }
    validation_rows = []
    calibration_rows = []
    calibration_probabilities = []
    for hour, hour_rows in sorted(by_hour.items()):
        if holdout_year is None:
            train_source_rows = hour_rows
            eval_source_rows = []
        else:
            train_source_rows = [row for row in hour_rows if int(row["year"]) != int(holdout_year)]
            eval_source_rows = [row for row in hour_rows if int(row["year"]) == int(holdout_year)]
        train_band_rows = build_band_rows(train_source_rows, support)
        if len(train_band_rows) < 200 or len({row["outcome"] for row in train_band_rows}) < 2:
            continue

        model, imputer, feature_names, train_metrics = train_band_hour_model(
            train_band_rows,
            include_dynamic_source_state=dynamic_source_state,
        )
        eval_score = None
        raw_eval_score = None
        temperature = 1.0
        tuned_brier = None
        market_scores = []
        eval_band_rows = []
        post_probs = []
        if eval_source_rows:
            eval_band_rows = build_band_rows(eval_source_rows, support)
            if eval_band_rows:
                raw_probs = predict_band_probabilities(
                    model,
                    imputer,
                    feature_names,
                    eval_band_rows,
                    temperature=1.0,
                )
                raw_eval_score = evaluate_band_predictions(eval_band_rows, raw_probs)
                temperature, tuned_brier = tune_temperature(eval_band_rows, raw_probs)
                tuned_probs = [
                    temperature_scale_probability(probability, temperature=temperature)
                    for probability in raw_probs
                ]
                post_probs = [
                    apply_band_postprocessing(
                        probability,
                        row,
                        config=artifact["postprocess"],
                    )
                    for row, probability in zip(eval_band_rows, tuned_probs)
                ]
                calibration_rows.extend(eval_band_rows)
                calibration_probabilities.extend(post_probs)
                eval_score = evaluate_band_predictions(eval_band_rows, post_probs)
                for market_id in sorted({row["market_id"] for row in eval_band_rows}):
                    subset = [
                        (row, probability)
                        for row, probability in zip(eval_band_rows, post_probs)
                        if row["market_id"] == market_id
                    ]
                    score = evaluate_band_predictions(
                        [row for row, _ in subset],
                        [probability for _, probability in subset],
                    )
                    if score:
                        market_scores.append({"market_id": market_id, **score})

        final_band_rows = build_band_rows(hour_rows, support)
        final_model, final_imputer, final_feature_names, final_metrics = train_band_hour_model(
            final_band_rows,
            include_dynamic_source_state=dynamic_source_state,
        )
        artifact["models"][str(hour)] = {
            "model": final_model,
            "imputer": final_imputer,
            "feature_names": final_feature_names,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "classes": [int(value) for value in final_model.classes_],
            "train_rows": len(final_band_rows),
            "source_rows": len(hour_rows),
            "temperature": temperature,
            "postprocess": dict(artifact["postprocess"]),
            "training_metrics": final_metrics,
        }
        validation_rows.append({
            "hour": hour,
            "source_train_rows": len(train_source_rows),
            "band_train_rows": len(train_band_rows),
            "source_eval_rows": len(eval_source_rows),
            "temperature": temperature,
            "tuned_brier": tuned_brier,
            "raw_eval_score": raw_eval_score,
            "eval_score": eval_score,
            "market_scores": market_scores,
            "training_metrics": train_metrics,
            "blocked_validation": blocked_validation_audit(hour_rows),
            "_eval_band_rows": eval_band_rows if eval_source_rows else [],
            "_post_probs": post_probs if eval_source_rows else [],
        })
    calibration = fit_adjacent_calibration(calibration_rows, calibration_probabilities)
    artifact["postprocess"]["adjacent_calibration"] = calibration
    exact_rows = []
    exact_probabilities = []
    for validation in validation_rows:
        eval_band_rows = validation.pop("_eval_band_rows", [])
        post_probs = validation.pop("_post_probs", [])
        if not eval_band_rows or not post_probs:
            continue
        adjacent_probs = [
            apply_adjacent_calibration(
                probability,
                row,
                config=artifact["postprocess"],
            )
            for row, probability in zip(eval_band_rows, post_probs)
        ]
        if exact_winner_catchup:
            exact_rows.extend(eval_band_rows)
            exact_probabilities.extend(adjacent_probs)
        validation["_eval_band_rows_for_exact"] = eval_band_rows
        validation["_adjacent_probs_for_exact"] = adjacent_probs

    if exact_winner_catchup:
        exact_calibration = fit_exact_winner_catchup(
            exact_rows,
            exact_probabilities,
            guardrail_rows=exact_rows,
            guardrail_probabilities=exact_probabilities,
            normalization_gamma=artifact["postprocess"].get("partition_normalization_gamma", 1.25),
        )
        artifact["postprocess"]["exact_winner_catchup"] = exact_calibration

    for validation in validation_rows:
        eval_band_rows = validation.pop("_eval_band_rows_for_exact", [])
        adjacent_probs = validation.pop("_adjacent_probs_for_exact", [])
        if not eval_band_rows or not adjacent_probs:
            continue
        calibrated_probs = adjacent_probs
        if exact_winner_catchup:
            calibrated_probs = [
                apply_exact_winner_catchup(
                    probability,
                    row,
                    config=artifact["postprocess"],
                )
                for row, probability in zip(eval_band_rows, adjacent_probs)
            ]
        validation["eval_score"] = evaluate_band_predictions(eval_band_rows, calibrated_probs)
        market_scores = []
        for market_id in sorted({row["market_id"] for row in eval_band_rows}):
            subset = [
                (row, probability)
                for row, probability in zip(eval_band_rows, calibrated_probs)
                if row["market_id"] == market_id
            ]
            score = evaluate_band_predictions(
                [row for row, _ in subset],
                [probability for _, probability in subset],
            )
            if score:
                market_scores.append({"market_id": market_id, **score})
        validation["market_scores"] = market_scores
    for bundle in artifact["models"].values():
        bundle["postprocess"] = dict(artifact["postprocess"])
    return artifact, validation_rows


def write_artifact(artifact, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        pickle.dump(artifact, handle)
    return path


def training_metric_rows(validation_rows):
    rows = []
    for row in validation_rows:
        metrics = row.get("training_metrics") or {}
        if not metrics:
            continue
        rows.append([
            f"{row['hour']:02d}:00",
            metrics.get("matrix_rows"),
            metrics.get("matrix_columns"),
            fmt_num(metrics.get("matrix_build_seconds"), 6),
            fmt_num(metrics.get("model_fit_seconds"), 6),
            metrics.get("performance_warning_count", 0),
        ])
    return rows


def blocked_validation_metric_rows(validation_rows):
    rows = []
    for row in validation_rows:
        audit = row.get("blocked_validation") or {}
        rows.append([
            f"{row['hour']:02d}:00",
            "PASS" if audit.get("ok") else "FAIL",
            audit.get("market_day_count", 0),
            audit.get("target_date_count", 0),
            audit.get("split_count", 0),
            audit.get("leak_count", 0),
        ])
    return rows


def write_report(path, records, counts, validation_rows, holdout_year, artifact_path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# F-Family Pooled Feature Model",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Feature schema: `{FEATURE_SCHEMA_VERSION}`",
        f"Artifact: `{artifact_path}`",
        f"Holdout year: {holdout_year or '-'}",
        "",
        "## Dataset",
        "",
    ]
    lines += markdown_table(
        ["Market", "Rows"],
        [[market_id, count] for market_id, count in sorted(counts.items())],
    )
    lines += [
        "",
        f"Total rows: {len(records)}",
        "",
        "## Training Throughput",
        "",
    ]
    lines += markdown_table(
        ["Hour", "Matrix Rows", "Matrix Columns", "Build Seconds", "Fit Seconds", "Warnings"],
        training_metric_rows(validation_rows),
    )
    lines += [
        "",
        "## Blocked Validation Audit",
        "",
    ]
    lines += markdown_table(
        ["Hour", "Audit", "Market Days", "Target Dates", "Splits", "Leaks"],
        blocked_validation_metric_rows(validation_rows),
    )
    lines += [
        "",
        "## Hourly Validation",
        "",
    ]
    lines += markdown_table(
        ["Hour", "Train Rows", "Eval Rows", "Eval LogLoss", "Winning-Bucket Brier"],
        [
            [
                f"{row['hour']:02d}:00",
                row["train_rows"],
                row["eval_rows"],
                fmt_num((row.get("eval_score") or {}).get("logloss")),
                fmt_num((row.get("eval_score") or {}).get("winning_bucket_brier")),
            ]
            for row in validation_rows
        ],
    )
    lines += ["", "## Holdout By Market", ""]
    market_rows = []
    for row in validation_rows:
        for score in row.get("market_scores") or []:
            market_rows.append([
                score["market_id"],
                f"{row['hour']:02d}:00",
                score["n"],
                fmt_num(score.get("logloss")),
                fmt_num(score.get("winning_bucket_brier")),
            ])
    lines += markdown_table(
        ["Market", "Hour", "Rows", "LogLoss", "Winning-Bucket Brier"],
        market_rows,
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_density_report(path, records, counts, validation_rows, holdout_year, artifact_path, artifact=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    artifact = artifact or {}
    lines = [
        "# Pooled Continuous-Density Model",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Schema: `{artifact.get('schema_version') or 'pooled_continuous_density_hgb_v0.2'}`",
        f"Feature schema: `{FEATURE_SCHEMA_VERSION}`",
        f"Artifact: `{artifact_path}`",
        f"Holdout year: {holdout_year or '-'}",
        f"Grid: `{artifact.get('grid_low_f')}` to `{artifact.get('grid_high_f')}` F "
        f"step `{artifact.get('grid_step_f')}`",
        "",
        "## Objective",
        "",
        "This candidate trains one pooled regressor over all configured markets,",
        "converts temperature-like features and targets to canonical Fahrenheit,",
        "and emits a Gaussian residual density on the canonical-F grid. Market C/F",
        "bands are projected only at serving/replay time through",
        "`continuous_density_f` payloads.",
        "v0.2 estimates the final Gaussian width from holdout residuals when",
        "enough holdout rows exist, falling back to in-sample residuals only when",
        "validation evidence is too sparse.",
        "",
        "## Dataset",
        "",
    ]
    lines += markdown_table(
        ["Market", "Source Rows"],
        [[market_id, count] for market_id, count in sorted(counts.items())],
    )
    lines += [
        "",
        f"Total source rows: {len(records)}",
        "",
        "## Training Throughput",
        "",
    ]
    lines += markdown_table(
        ["Hour", "Matrix Rows", "Matrix Columns", "Build Seconds", "Fit Seconds", "Warnings"],
        training_metric_rows(validation_rows),
    )
    lines += [
        "",
        "## Blocked Validation Audit",
        "",
    ]
    lines += markdown_table(
        ["Hour", "Audit", "Market Days", "Target Dates", "Splits", "Leaks"],
        blocked_validation_metric_rows(validation_rows),
    )
    lines += [
        "",
        "## Hourly Holdout Validation",
        "",
    ]
    lines += markdown_table(
        ["Hour", "Train Rows", "Eval Rows", "Eval Sigma F", "Final Sigma F", "Sigma Source", "Density LogLoss", "Winner Brier", "MAE F"],
        [
            [
                f"{row['hour']:02d}:00",
                row["train_rows"],
                row["eval_rows"],
                fmt_num(row.get("sigma_f")),
                fmt_num(row.get("final_sigma_f")),
                row.get("final_sigma_source") or "-",
                fmt_num((row.get("eval_score") or {}).get("density_logloss")),
                fmt_num((row.get("eval_score") or {}).get("winning_bucket_brier")),
                fmt_num((row.get("eval_score") or {}).get("mean_absolute_error_f")),
            ]
            for row in validation_rows
        ],
    )
    lines += ["", "## Holdout By Market", ""]
    market_rows = []
    for row in validation_rows:
        for score in row.get("market_scores") or []:
            market_rows.append([
                score["market_id"],
                f"{row['hour']:02d}:00",
                score["n"],
                fmt_num(score.get("density_logloss")),
                fmt_num(score.get("winning_bucket_brier")),
                fmt_num(score.get("mean_absolute_error_f")),
            ])
    lines += markdown_table(
        ["Market", "Hour", "Rows", "Density LogLoss", "Winner Brier", "MAE F"],
        market_rows,
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_band_report(path, records, counts, validation_rows, holdout_year, artifact_path, artifact=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    artifact = artifact or {}
    postprocess = artifact.get("postprocess") or {}
    schema = artifact.get("schema_version") or "pooled_feature_band_hgb_v0.3"
    lines = [
        f"# F-Family Pooled Band Model {schema}",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Feature schema: `{FEATURE_SCHEMA_VERSION}`",
        f"Artifact: `{artifact_path}`",
        f"Objective: `{artifact.get('objective') or 'binary_market_band_brier_source_reliability'}`",
        f"Holdout year: {holdout_year or '-'}",
        "",
        "## Objective",
        "",
        "This candidate trains a binary model directly on market-band outcomes",
        "(`eq`/range, `lte`, and `gte`) instead of training an exact-bucket",
        "classifier and summing it after the fact. Training rows are generated",
        "from historical WU feature records and synthetic market-style bands;",
        "the pinned promotion corpus remains out-of-sample replay evidence.",
        "",
        "Hard WU-floor rules are applied deterministically, and a late-day",
        "lock-in blend concentrates probabilities toward the printed high when",
        "the day is late and cooling.",
        "",
        "v0.3 adds static per-market source-reliability priors learned from",
        "WU-vs-METAR/ASOS/GHCNh/reanalysis daily overlaps. These are source",
        "trust features, not same-day final redundant highs, so the candidate",
        "does not leak settlement information into intraday training rows.",
        "",
        "Exact-winner catch-up is "
        f"{'enabled' if postprocess.get('exact_winner_catchup_enabled') else 'disabled'}"
        " for this artifact.",
        "Dynamic source-state features are "
        f"{'enabled' if artifact.get('dynamic_source_state_enabled') else 'disabled'}"
        " for this artifact.",
        "",
        "## Training Throughput",
        "",
    ]
    lines += markdown_table(
        ["Hour", "Matrix Rows", "Matrix Columns", "Build Seconds", "Fit Seconds", "Warnings"],
        training_metric_rows(validation_rows),
    )
    lines.append("")
    lines += [
        "## Blocked Validation Audit",
        "",
    ]
    lines += markdown_table(
        ["Hour", "Audit", "Market Days", "Target Dates", "Splits", "Leaks"],
        blocked_validation_metric_rows(validation_rows),
    )
    lines.append("")
    exact_calibration = postprocess.get("exact_winner_catchup") or {}
    strength_diagnostics = exact_calibration.get("strength_diagnostics") or {}
    selected_strength = strength_diagnostics.get("selected") or {}
    baseline_strength = strength_diagnostics.get("baseline") or {}
    if postprocess.get("exact_winner_catchup_enabled"):
        lines += [
            "## Exact-Winner Catch-Up Guardrail",
            "",
        ]
        lines += markdown_table(
            ["Field", "Value"],
            [
                ["Contexts", exact_calibration.get("context_count", 0)],
                ["Selected strength", fmt_num(exact_calibration.get("strength"))],
                ["One-above tolerance", fmt_num(strength_diagnostics.get("one_above_tolerance"))],
                ["Normalization gamma", fmt_num(strength_diagnostics.get("normalization_gamma"))],
                ["Baseline settlement-distance-0 Brier", fmt_num(baseline_strength.get("distance0_brier"))],
                ["Selected settlement-distance-0 delta", fmt_num(selected_strength.get("distance0_delta_vs_base"))],
                ["Baseline one-above Brier", fmt_num(baseline_strength.get("one_above_brier"))],
                ["Selected one-above delta", fmt_num(selected_strength.get("one_above_delta_vs_base"))],
                ["Baseline exact-band Brier", fmt_num(baseline_strength.get("eq_brier"))],
                ["Selected exact-band delta", fmt_num(selected_strength.get("eq_delta_vs_base"))],
            ],
        )
        lines += ["", "### Strength Candidates", ""]
        lines += markdown_table(
            [
                "Strength", "Passed", "Distance-0 Brier", "Distance-0 Delta",
                "One-Above Brier", "One-Above Delta", "EQ Brier", "EQ Delta",
            ],
            [
                [
                    fmt_num(row.get("strength")),
                    "yes" if row.get("passed") else "no",
                    fmt_num(row.get("distance0_brier")),
                    fmt_num(row.get("distance0_delta_vs_base")),
                    fmt_num(row.get("one_above_brier")),
                    fmt_num(row.get("one_above_delta_vs_base")),
                    fmt_num(row.get("eq_brier")),
                    fmt_num(row.get("eq_delta_vs_base")),
                ]
                for row in strength_diagnostics.get("candidates") or []
            ],
        )
        lines += [""]
    lines += [
        "## Dataset",
        "",
    ]
    lines += markdown_table(
        ["Market", "Source Rows"],
        [[market_id, count] for market_id, count in sorted(counts.items())],
    )
    lines += [
        "",
        f"Total source rows: {len(records)}",
        "",
        "## Hourly Holdout Validation",
        "",
    ]
    lines += markdown_table(
        [
            "Hour", "Source Train", "Band Train", "Source Eval",
            "Temp", "Raw Brier", "Post Brier", "LogLoss",
            "Positive Mean P", "Exact Winner Mean P", "Late Brier",
        ],
        [
            [
                f"{row['hour']:02d}:00",
                row["source_train_rows"],
                row["band_train_rows"],
                row["source_eval_rows"],
                fmt_num(row.get("temperature")),
                fmt_num((row.get("raw_eval_score") or {}).get("brier")),
                fmt_num((row.get("eval_score") or {}).get("brier")),
                fmt_num((row.get("eval_score") or {}).get("logloss")),
                fmt_num((row.get("eval_score") or {}).get("positive_mean_p")),
                fmt_num((row.get("eval_score") or {}).get("exact_winner_mean_p")),
                fmt_num((row.get("eval_score") or {}).get("late_brier")),
            ]
            for row in validation_rows
        ],
    )
    lines += ["", "## Holdout By Market", ""]
    market_rows = []
    for row in validation_rows:
        for score in row.get("market_scores") or []:
            market_rows.append([
                score["market_id"],
                f"{row['hour']:02d}:00",
                score["n"],
                fmt_num(score.get("brier")),
                fmt_num(score.get("logloss")),
                fmt_num(score.get("positive_mean_p")),
                fmt_num(score.get("exact_winner_mean_p")),
                fmt_num(score.get("late_brier")),
            ])
    lines += markdown_table(
        ["Market", "Hour", "Rows", "Brier", "LogLoss", "Positive Mean P",
         "Exact Winner Mean P", "Late Brier"],
        market_rows,
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def parse_hours(value):
    if not value:
        return tuple(INTRADAY_CUTOFF_HOURS)
    return tuple(int(item.strip()) for item in str(value).split(",") if item.strip())


def main():
    parser = argparse.ArgumentParser(description="Train the F-family pooled feature model starter.")
    parser.add_argument("--family-unit", default=None, choices=["F", "all"])
    parser.add_argument("--objective", default="bucket", choices=["bucket", "band", "density"],
                        help=("bucket=v0.1 exact-bucket classifier; band=v0.2 direct market-band "
                              "classifier; density=canonical-F continuous-density candidate."))
    parser.add_argument("--hours", default=",".join(str(hour) for hour in INTRADAY_CUTOFF_HOURS))
    parser.add_argument("--max-days-per-market", type=int, default=0,
                        help="Optional newest-day cap for quick research/smoke runs; 0 uses all days.")
    parser.add_argument("--holdout-year", type=int, default=2025)
    parser.add_argument("--exact-winner-catchup", action="store_true",
                        help="Train the opt-in exact/range winner catch-up postprocess variant.")
    parser.add_argument("--dynamic-source-state", action="store_true",
                        help="Train the opt-in dynamic source-state feature variant.")
    parser.add_argument("--artifact", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    if args.exact_winner_catchup and args.dynamic_source_state:
        raise SystemExit("--exact-winner-catchup and --dynamic-source-state are separate shadow variants")
    family_unit = args.family_unit or ("all" if args.objective == "density" else "F")
    if args.objective in {"bucket", "band"} and family_unit != "F":
        raise SystemExit("--family-unit all is currently only supported with --objective density")

    records, counts = build_family_dataset(
        unit=family_unit,
        cutoff_hours=parse_hours(args.hours),
        max_days_per_market=args.max_days_per_market or None,
    )
    if not records:
        raise SystemExit("No pooled family records available.")
    if args.objective == "density":
        artifact_path_arg = args.artifact or str(DEFAULT_DENSITY_ARTIFACT)
        report_path_arg = args.out or str(DEFAULT_DENSITY_REPORT)
        artifact, validation_rows = train_pooled_density_models(
            records,
            holdout_year=args.holdout_year,
        )
        artifact_path = write_artifact(artifact, artifact_path_arg)
        report_path = write_density_report(
            report_path_arg,
            records,
            counts,
            validation_rows,
            args.holdout_year,
            artifact_path,
            artifact=artifact,
        )
    elif args.objective == "band":
        artifact_path_arg = args.artifact or str(
            DEFAULT_EXACT_WINNER_ARTIFACT
            if args.exact_winner_catchup else
            DEFAULT_DYNAMIC_SOURCE_ARTIFACT
            if args.dynamic_source_state else
            DEFAULT_BAND_ARTIFACT
        )
        report_path_arg = args.out or str(
            DEFAULT_EXACT_WINNER_REPORT
            if args.exact_winner_catchup else
            DEFAULT_DYNAMIC_SOURCE_REPORT
            if args.dynamic_source_state else
            DEFAULT_BAND_REPORT
        )
        artifact, validation_rows = train_pooled_band_models(
            records,
            holdout_year=args.holdout_year,
            exact_winner_catchup=args.exact_winner_catchup,
            dynamic_source_state=args.dynamic_source_state,
        )
        artifact_path = write_artifact(artifact, artifact_path_arg)
        report_path = write_band_report(
            report_path_arg,
            records,
            counts,
            validation_rows,
            args.holdout_year,
            artifact_path,
            artifact=artifact,
        )
    else:
        artifact_path_arg = args.artifact or str(DEFAULT_ARTIFACT)
        report_path_arg = args.out or str(DEFAULT_REPORT)
        artifact, validation_rows = train_pooled_models(records, holdout_year=args.holdout_year)
        artifact_path = write_artifact(artifact, artifact_path_arg)
        report_path = write_report(
            report_path_arg,
            records,
            counts,
            validation_rows,
            args.holdout_year,
            artifact_path,
        )
    print(
        f"Wrote pooled {family_unit}-family {args.objective} artifact to {artifact_path} "
        f"and report to {report_path} over {len(records)} rows."
    )


if __name__ == "__main__":
    main()
