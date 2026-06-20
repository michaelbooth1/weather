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
from weather.reporting.artifact_disk_budget import (
    DEFAULT_ARTIFACT_EXPORT_MIN_FREE_BYTES,
    ensure_artifact_disk_headroom,
)
from weather.reporting.weak_input_family_disposition import weak_input_training_preflight
from weather.market.market_microstructure_features import CLOB_MODEL_FEATURE_COLUMNS
from weather.market.market_registry import all_specs, spec_for_id
from weather.model.continuous_density import (
    band_probability_from_density,
    bucket_interval_native,
    canonical_grid_f,
    continuous_density_payload,
    f_to_native,
    native_interval_to_f,
)
from weather.model.feature_store import (
    FEATURE_COLUMNS,
    FEATURE_SCHEMA_VERSION,
    FORECAST_FEATURE_COLUMNS,
    build_historical_feature_record,
)
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
from weather.sources.reanalysis_synoptic import (
    REANALYSIS_SYNOPTIC_FEATURE_COLUMNS,
    load_reanalysis_synoptic_features,
)
from weather.artifacts import writable_artifact_path
from weather.calibration.blocked_validation import blocked_validation_audit
from weather.calibration.probability_calibration import apply_continuous_density_calibration
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
DEFAULT_DENSITY_ARTIFACT = writable_artifact_path("pooled_continuous_density_hgb_v0_7.pkl")
DEFAULT_FORECAST_PROFILE_BAND_REPORT = data_path() / "backtest" / "item134_forecast_profile_band_model_report.md"
DEFAULT_FORECAST_PROFILE_BAND_ARTIFACT = writable_artifact_path("feature_model_hgb_f_pooled_forecast_profile_v0_1.pkl")
DEFAULT_TRAINING_OUTPUT_ESTIMATED_BYTES = 10_000_000
BAND_MERGE_PAYLOAD_KEY = "band_postprocess_merge_payload"

WIND_GROUPS = ["E-SE/onshore-ish", "S-SW", "W-NW", "N-NE", "SSE", "Other/variable"]
CLOUD_GROUPS = ["Precip", "Fog/haze", "Fair/clear", "Partly cloudy", "Mostly cloudy/overcast", "Other"]
FEATURE_SUBSET_ALL = "all"
FEATURE_SUBSET_FORECAST_PROFILE = "forecast_profile"
FEATURE_SUBSET_CHOICES = (FEATURE_SUBSET_ALL, FEATURE_SUBSET_FORECAST_PROFILE)
DENSITY_SIGMA_TUNING_SCALES = (0.35, 0.5, 0.65, 0.8, 1.0, 1.25, 1.5, 2.0)
DENSITY_DEFAULT_SHAPE = {"shape": "gaussian", "id": "gaussian"}
DENSITY_SHAPE_TUNING_CANDIDATES = (
    DENSITY_DEFAULT_SHAPE,
    {"shape": "tail_mixture", "id": "tail_w10_s2", "tail_weight": 0.10, "tail_scale": 2.0},
    {"shape": "tail_mixture", "id": "tail_w15_s3", "tail_weight": 0.15, "tail_scale": 3.0},
    {
        "shape": "anchor_mixture",
        "id": "forecast_w15",
        "anchor": "forecast_high",
        "anchor_weight": 0.15,
        "anchor_sigma_scale": 1.0,
    },
    {
        "shape": "anchor_mixture",
        "id": "forecast_w30",
        "anchor": "forecast_high",
        "anchor_weight": 0.30,
        "anchor_sigma_scale": 1.0,
    },
    {
        "shape": "anchor_mixture",
        "id": "climate_w10",
        "anchor": "climate_normal",
        "anchor_weight": 0.10,
        "anchor_sigma_scale": 1.5,
    },
)
FORECAST_PROFILE_ALLOWED_BASE_COLUMNS = {
    *FORECAST_FEATURE_COLUMNS,
    "latitude",
    "longitude",
    "coastal",
    "climate_normal",
    "climate_std",
    "forecast_anomaly",
    "band_value",
    "band_value_hi",
    "band_width",
    "band_mid",
    "band_mid_minus_forecast",
    "band_mid_anomaly",
}
FORECAST_PROFILE_BLOCKED_COLUMN_PREFIXES = (
    "wind_group_",
    "cloud_group_",
)
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


def feature_subset_contract(feature_subset=FEATURE_SUBSET_ALL):
    feature_subset = feature_subset or FEATURE_SUBSET_ALL
    if feature_subset == FEATURE_SUBSET_ALL:
        return {
            "name": FEATURE_SUBSET_ALL,
            "schema_version": "pooled_feature_subset_v0.1",
            "description": "All default pooled band model features.",
            "allowed_feature_families": ["all"],
            "blocked_feature_families": [],
            "anchor_feature": None,
        }
    if feature_subset == FEATURE_SUBSET_FORECAST_PROFILE:
        return {
            "name": FEATURE_SUBSET_FORECAST_PROFILE,
            "schema_version": "pooled_feature_subset_v0.1",
            "description": (
                "Roadmap item 134 forecast-profile lane: forecast-profile "
                "features plus market/climate context and band geometry "
                "relative to forecast_high. Observed-temperature-path and "
                "live-reading dominance columns are excluded from the model "
                "matrix."
            ),
            "allowed_feature_families": [
                "forecast_high_anchor",
                "forecast_profile_temperature",
                "forecast_cloud_solar_radiation",
                "forecast_gap",
                "forecast_ensemble_spread",
                "forecast_source_state_guardrail",
                "market_climate_context",
                "forecast_relative_band_geometry",
            ],
            "blocked_feature_families": [
                "observed_temp_path",
                "live_reading_path",
                "surface_weather",
                "marine_microclimate",
                "official_guidance",
                "clob_microstructure",
                "dynamic_source_state",
            ],
            "anchor_feature": "forecast_high",
            "postprocess_policy": (
                "Auxiliary forecast-profile fields may only change confidence "
                "around forecast-relative band geometry; promotion still "
                "requires daily-first blocked replay and high-disagreement "
                "guardrails."
            ),
        }
    raise ValueError(f"Unknown pooled feature subset: {feature_subset}")


def feature_names_for_subset(columns, feature_subset=FEATURE_SUBSET_ALL):
    columns = list(columns)
    feature_subset = feature_subset or FEATURE_SUBSET_ALL
    if feature_subset == FEATURE_SUBSET_ALL:
        return columns
    if feature_subset != FEATURE_SUBSET_FORECAST_PROFILE:
        raise ValueError(f"Unknown pooled feature subset: {feature_subset}")

    selected = []
    for column in columns:
        if column in FORECAST_PROFILE_ALLOWED_BASE_COLUMNS:
            selected.append(column)
            continue
        if column.startswith("market_id_") or column.startswith("band_kind_"):
            selected.append(column)
            continue
        if any(column.startswith(prefix) for prefix in FORECAST_PROFILE_BLOCKED_COLUMN_PREFIXES):
            continue
    return selected


def reanalysis_promotion_lane_from_payload(payload):
    if not payload:
        return None
    if payload.get("allowed_markets") is not None or payload.get("quarantined_markets") is not None:
        return payload
    for row in payload.get("inventory") or []:
        if row.get("family_id") == "reanalysis_synoptic":
            return row.get("promotion_lane")
    return None


def load_reanalysis_promotion_lane(path):
    if not path:
        return None
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Reanalysis promotion lane file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return reanalysis_promotion_lane_from_payload(json.load(handle))


def blocked_reanalysis_feature_columns(lane=None):
    lane = lane or {}
    explicit = {
        column
        for column in lane.get("blocked_feature_columns") or []
        if column in REANALYSIS_SYNOPTIC_FEATURE_COLUMNS
    }
    prefixes = tuple(str(prefix) for prefix in lane.get("blocked_feature_prefixes") or [])
    if prefixes:
        explicit.update(
            column
            for column in REANALYSIS_SYNOPTIC_FEATURE_COLUMNS
            if column.startswith(prefixes)
        )
    return explicit


def apply_reanalysis_promotion_lane_to_record(record, lane=None):
    lane = lane or {}
    allowed = set(lane.get("allowed_markets") or [])
    market_id = record.get("market_id")
    blocked_columns = blocked_reanalysis_feature_columns(lane)
    if allowed and market_id not in allowed:
        blocked_columns = set(REANALYSIS_SYNOPTIC_FEATURE_COLUMNS)
    if not blocked_columns:
        return record
    for column in blocked_columns:
        record[column] = None
    if blocked_columns == set(REANALYSIS_SYNOPTIC_FEATURE_COLUMNS):
        record["reanalysis_synoptic_available"] = 0.0
    return record


def apply_reanalysis_lane_to_records(records, lane=None):
    if not lane:
        return records
    return [apply_reanalysis_promotion_lane_to_record(dict(record), lane) for record in records]


def apply_reanalysis_lane_metadata(artifact, lane=None):
    if not lane:
        return artifact
    lane = dict(lane)
    artifact["source_family_lanes"] = {
        **(artifact.get("source_family_lanes") or {}),
        "reanalysis_synoptic": lane,
    }
    artifact["reanalysis_promotion_lane"] = lane
    artifact["objective"] = f"{artifact.get('objective')}_reanalysis_positive_market_lane"
    postprocess = artifact.setdefault("postprocess", {})
    market_alpha = dict(postprocess.get("current_blend_market_alpha") or {})
    for market_id in lane.get("quarantined_markets") or []:
        market_alpha[market_id] = 0.0
    postprocess["current_blend_market_alpha"] = market_alpha
    for bundle in (artifact.get("models") or {}).values():
        if isinstance(bundle, dict):
            bundle["postprocess"] = dict(postprocess)
    return artifact


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


def build_market_records(
    spec,
    cutoff_hours=INTRADAY_CUTOFF_HOURS,
    max_days=None,
    reanalysis_promotion_lane=None,
):
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
            apply_reanalysis_promotion_lane_to_record(record, reanalysis_promotion_lane)
            add_dynamic_source_state_features(record, historical_default=True)
            record["year"] = int(local_date.year)
            records.append(record)
    return records


def build_family_dataset(
    unit="F",
    cutoff_hours=INTRADAY_CUTOFF_HOURS,
    max_days_per_market=None,
    reanalysis_promotion_lane=None,
):
    specs = family_specs(unit)
    records = []
    counts = {}
    for spec in specs:
        market_records = build_market_records(
            spec,
            cutoff_hours=cutoff_hours,
            max_days=max_days_per_market,
            reanalysis_promotion_lane=reanalysis_promotion_lane,
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
    if isinstance(support, dict):
        unit = record_unit(record)
        unit_support = support.get(unit) or support.get(str(unit).upper())
        if not unit_support:
            unit_support = support.get("F") or next(iter(support.values()), [])
        support = unit_support
    support = sorted(int(value) for value in support)
    if not support:
        return []
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


def band_training_support(records, family_unit="F"):
    """Return native support for synthetic market-band training rows."""
    if str(family_unit or "").lower() != "all":
        return sorted({int(row["final_bucket"]) for row in records})
    by_unit = defaultdict(set)
    for row in records:
        bucket = round_half_up(row.get("final_bucket"))
        if bucket is None:
            continue
        by_unit[record_unit(row)].add(int(bucket))
    return {
        unit: sorted(values)
        for unit, values in sorted(by_unit.items())
        if values
    }


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


def density_shape_id(shape_config=None):
    return density_shape_config(shape_config).get("id") or "gaussian"


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


def density_winner_bucket_score(rows, means, grid_f, sigma_f, shape_config=None):
    """Score winner-bucket probabilities without materializing payload dicts.

    Full replay still uses ``continuous_density_f`` payloads. During training,
    sigma tuning only needs each holdout row's probability assigned to its
    final rounded bucket, so a vectorized Gaussian-grid calculation avoids
    repeatedly building and normalizing thousands of Python dictionaries.
    """
    if not rows or not means:
        return None
    usable = []
    for row, mean_f in zip(rows or [], means or []):
        final_bucket = row.get("final_bucket")
        if final_bucket is None or mean_f is None:
            continue
        try:
            final_bucket = float(final_bucket)
            mean_f = float(mean_f)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(final_bucket) or not math.isfinite(mean_f):
            continue
        unit = record_unit(row)
        low_f = native_value_to_f(final_bucket - 0.5, unit)
        high_f = native_value_to_f(final_bucket + 0.5, unit)
        target_f = native_value_to_f(final_bucket, unit)
        usable.append((row, mean_f, low_f, high_f, target_f))
    if not usable:
        return None

    sigma = max(0.1, float(sigma_f or 1.0))
    grid = np.asarray([float(value) for value in grid_f], dtype=float)
    source_rows = [row[0] for row in usable]
    means_array = np.asarray([row[1] for row in usable], dtype=float)
    lows = np.asarray([row[2] for row in usable], dtype=float)
    highs = np.asarray([row[3] for row in usable], dtype=float)
    targets = np.asarray([row[4] for row in usable], dtype=float)
    weights = density_weight_matrix(source_rows, means_array, grid, sigma, shape_config=shape_config)
    totals = weights.sum(axis=1)
    mask = (grid[None, :] >= lows[:, None]) & (grid[None, :] < highs[:, None])
    bucket_mass = (weights * mask).sum(axis=1)
    probabilities = np.divide(
        bucket_mass,
        totals,
        out=np.zeros_like(bucket_mass, dtype=float),
        where=totals > 0,
    )
    probabilities = np.clip(probabilities, 1e-15, 1.0)
    losses = -np.log(probabilities)
    briers = (probabilities - 1.0) ** 2
    absolute_errors = np.abs(means_array - targets)
    return {
        "n": int(len(probabilities)),
        "density_logloss": float(losses.mean()),
        "winning_bucket_brier": float(briers.mean()),
        "mean_absolute_error_f": float(absolute_errors.mean()),
    }


def density_synthetic_market_band_rows(row, exact_radius=7, tail_stride=1):
    final = round_half_up((row or {}).get("final_bucket"))
    if final is None:
        return []
    unit = record_unit(row)
    centers = [final]
    for column in ("high_so_far", "forecast_high", "current_temp", "live_reading_temp", "climate_normal"):
        value = (row or {}).get(column)
        if value is None:
            continue
        try:
            native_value = f_to_native(float(value), unit)
        except (TypeError, ValueError):
            continue
        center = round_half_up(native_value)
        if center is not None:
            centers.append(center)
    low = min(centers) - int(exact_radius)
    high = max(centers) + int(exact_radius)
    rows = []

    def add(kind, value, value_hi=None):
        outcome = band_outcome(kind, value, final, value_hi=value_hi)
        if outcome is None:
            return
        distance = 0
        if kind == "lte":
            distance = max(0, final - int(value))
        elif kind == "gte":
            distance = max(0, int(value) - final)
        else:
            hi = int(value_hi) if value_hi is not None else int(value)
            distance = 0 if int(value) <= final <= hi else min(abs(final - int(value)), abs(final - hi))
        weight = 1.0
        if outcome:
            weight *= 4.0 if kind == "eq" else 2.0
        if distance == 0:
            weight *= 1.5
        if int((row or {}).get("cutoff_hour") or 0) >= 16:
            weight *= 2.0
        rows.append({
            "kind": kind,
            "value": int(value),
            "value_hi": int(value_hi) if value_hi is not None else None,
            "outcome": int(outcome),
            "unit": unit,
            "settlement_distance": int(distance),
            "_sample_weight": float(weight),
        })

    for value in range(low, high + 1):
        add("eq", value)
    for value in range(low, high):
        add("eq", value, value_hi=value + 1)
    for value in range(low, high + 1, max(1, int(tail_stride))):
        add("lte", value)
        add("gte", value)
    return rows


def canonical_row_to_native_band_record(row):
    """Return a density row with temperature coordinates restored to native units."""
    out = dict(row or {})
    unit = record_unit(row)
    for column in CANONICAL_F_ABSOLUTE_COLUMNS:
        value = out.get(column)
        if value in (None, ""):
            continue
        try:
            out[column] = f_to_native(float(value), unit)
        except (TypeError, ValueError):
            continue
    for column in CANONICAL_F_DELTA_COLUMNS:
        value = out.get(column)
        if value in (None, ""):
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        out[column] = value * 5.0 / 9.0 if str(unit).upper() == "C" else value
    out["unit"] = unit
    out["display_unit"] = unit
    return out


def density_market_band_training_rows(row):
    native_record = canonical_row_to_native_band_record(row)
    rows = []
    for band_row in density_synthetic_market_band_rows(row):
        record = band_prediction_record(
            native_record,
            band_row["kind"],
            band_row["value"],
            value_hi=band_row.get("value_hi"),
        )
        record["outcome"] = int(band_row["outcome"])
        record["unit"] = band_row["unit"]
        record["settlement_distance"] = int(band_row["settlement_distance"])
        record["_sample_weight"] = float(band_row.get("_sample_weight", 1.0))
        rows.append(record)
    return rows


def density_projected_market_band_rows_and_probabilities(rows, means, grid_f, sigma_f, shape_config=None):
    band_rows = []
    probabilities = []
    for row, mean_f in zip(rows or [], means or []):
        if mean_f is None:
            continue
        try:
            mean_f = float(mean_f)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(mean_f):
            continue
        payload = gaussian_density_f(
            mean_f,
            sigma_f,
            grid_f,
            shape_config=shape_config,
            row=row,
        )
        for band_row in density_market_band_training_rows(row):
            calibrated_payload = apply_continuous_density_calibration(
                payload,
                {},
                floor_bucket=band_row.get("observed_floor_bucket"),
                unit=band_row.get("unit") or record_unit(row),
                resolution_weight=band_row.get("late_lockin_strength", 0.0),
                cutoff_hour=row.get("cutoff_hour"),
            )
            probability = band_probability_from_density(
                calibrated_payload.get("density_f") or {},
                band_row.get("unit") or record_unit(row),
                band_row.get("band_kind"),
                band_row.get("band_value"),
                value_hi=band_row.get("band_value_hi"),
            )
            band_rows.append(band_row)
            probabilities.append(clip_probability(probability))
    return band_rows, probabilities


def density_postprocess_probabilities(rows, probabilities, config):
    config = config or {}
    adjusted = []
    for row, probability in zip(rows or [], probabilities or []):
        probability = clip_probability(probability)
        if config.get("adjacent_calibration_enabled", False):
            probability = apply_adjacent_calibration(probability, row, config=config)
        if config.get("exact_winner_catchup_enabled", False):
            probability = apply_exact_winner_catchup(probability, row, config=config)
        if config.get("forecast_relative_calibration_enabled", False):
            probability = apply_forecast_relative_density_calibration(probability, row, config=config)
        adjusted.append(clip_probability(probability))
    if config.get("partition_normalization_enabled", False):
        adjusted = normalize_band_probabilities_for_rows(
            rows,
            adjusted,
            gamma=float(config.get("partition_normalization_gamma", 1.25)),
        )
    return adjusted


def weighted_market_band_brier(rows, probabilities):
    total_weight = 0.0
    total_loss = 0.0
    for row, probability in zip(rows or [], probabilities or []):
        if row.get("outcome") is None:
            continue
        try:
            outcome = int(row.get("outcome"))
            weight = float(row.get("_sample_weight", 1.0))
        except (TypeError, ValueError):
            continue
        if weight <= 0:
            continue
        total_weight += weight
        total_loss += weight * brier(clip_probability(probability), outcome)
    if total_weight <= 0:
        return None
    return total_loss / total_weight


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


def _forecast_relative_strength_grid(values=None):
    if values is None:
        values = (1.0, 0.75, 0.50, 0.25, 0.0)
    cleaned = []
    for value in values:
        try:
            strength = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            continue
        if strength not in cleaned:
            cleaned.append(strength)
    return cleaned or [0.0]


def _with_forecast_relative_strength(calibration, strength):
    copy = dict(calibration or {})
    copy["strength"] = max(0.0, min(1.0, float(strength)))
    return copy


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
    factor = forecast_relative_density_factor(row, config={"forecast_relative_calibration": calibration})
    strength = max(0.0, min(1.0, float(calibration.get("strength", 1.0))))
    if factor == 1.0 or strength <= 0.0:
        return clip_probability(probability)
    return clip_probability(float(probability) * (float(factor) ** strength))


def select_forecast_relative_density_strength(rows, probabilities, calibration, strength_grid=None):
    rows = list(rows or [])
    probabilities = [clip_probability(probability) for probability in (probabilities or [])]
    grid = _forecast_relative_strength_grid(strength_grid)
    baseline_brier = weighted_market_band_brier(rows, probabilities)
    candidates = []
    for strength in grid:
        adjusted = [
            apply_forecast_relative_density_calibration(
                probability,
                row,
                config={
                    "forecast_relative_calibration": _with_forecast_relative_strength(
                        calibration,
                        strength,
                    ),
                },
            )
            for row, probability in zip(rows, probabilities)
        ]
        candidates.append({
            "strength": float(strength),
            "market_band_brier": weighted_market_band_brier(rows, adjusted),
        })
    candidates = sorted(
        candidates,
        key=lambda row: (
            float(row.get("market_band_brier", float("inf"))),
            0 if float(row.get("strength", 0.0)) == 0.0 else 1,
        ),
    )
    selected = candidates[0] if candidates else {"strength": 0.0, "market_band_brier": baseline_brier}
    return {
        "baseline_market_band_brier": baseline_brier,
        "selected_strength": float(selected.get("strength", 0.0)),
        "selected_market_band_brier": selected.get("market_band_brier"),
        "candidates": candidates,
    }


def fit_forecast_relative_density_calibration(
    rows,
    probabilities,
    min_rows=120,
    prior_rows=240.0,
    factor_min=0.50,
    factor_max=1.60,
):
    stats = defaultdict(lambda: {"n": 0, "outcome_sum": 0.0, "prob_sum": 0.0})
    for row, probability in zip(rows or [], probabilities or []):
        try:
            probability = clip_probability(probability)
            outcome = float(row.get("outcome") or 0.0)
        except (TypeError, ValueError):
            continue
        for context in density_forecast_relative_contexts(row):
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
        "version": "density_forecast_relative_v0.1",
        "min_rows": int(min_rows),
        "prior_rows": float(prior_rows),
        "factor_min": float(factor_min),
        "factor_max": float(factor_max),
        "strength": 1.0,
        "context_count": len(contexts),
        "contexts": contexts,
    }
    diagnostics = select_forecast_relative_density_strength(rows, probabilities, calibration)
    calibration["strength"] = diagnostics["selected_strength"]
    calibration["strength_diagnostics"] = diagnostics
    return calibration


def fit_density_market_band_postprocess(rows, probabilities, min_improvement=0.003):
    rows = list(rows or [])
    probabilities = [clip_probability(probability) for probability in (probabilities or [])]
    adjacent = fit_adjacent_calibration(rows, probabilities)
    exact = fit_exact_winner_catchup(
        rows,
        probabilities,
        factor_min=1.0,
        guardrail_rows=rows,
        guardrail_probabilities=probabilities,
    )
    forecast_relative = fit_forecast_relative_density_calibration(rows, probabilities)
    base_config = {
        "schema_version": "density_market_band_postprocess_v0.2",
        "adjacent_calibration": adjacent,
        "exact_winner_catchup": exact,
        "forecast_relative_calibration": forecast_relative,
        "partition_normalization_gamma": 1.25,
        "calibration_rows": len(rows),
    }
    candidates = []
    policy_grid = [
        ("disabled", False, False, False, False),
        ("forecast_relative", False, False, True, False),
        ("adjacent_only", True, False, False, False),
        ("exact_only", False, True, False, False),
        ("adjacent_exact", True, True, False, False),
        ("forecast_adjacent", True, False, True, False),
        ("forecast_exact", False, True, True, False),
        ("forecast_adjacent_exact", True, True, True, False),
        ("forecast_normalized", False, False, True, True),
        ("adjacent_normalized", True, False, False, True),
        ("exact_normalized", False, True, False, True),
        ("adjacent_exact_normalized", True, True, False, True),
        ("forecast_adjacent_exact_normalized", True, True, True, True),
    ]
    for policy_id, adjacent_enabled, exact_enabled, forecast_enabled, normalized in policy_grid:
        config = {
            **base_config,
            "enabled": policy_id != "disabled",
            "policy_id": policy_id,
            "adjacent_calibration_enabled": bool(adjacent_enabled),
            "exact_winner_catchup_enabled": bool(exact_enabled),
            "forecast_relative_calibration_enabled": bool(forecast_enabled),
            "partition_normalization_enabled": bool(normalized),
        }
        candidate_probabilities = density_postprocess_probabilities(rows, probabilities, config)
        candidates.append({
            "policy_id": policy_id,
            "enabled": policy_id != "disabled",
            "adjacent_calibration_enabled": bool(adjacent_enabled),
            "exact_winner_catchup_enabled": bool(exact_enabled),
            "forecast_relative_calibration_enabled": bool(forecast_enabled),
            "partition_normalization_enabled": bool(normalized),
            "market_band_brier": weighted_market_band_brier(rows, candidate_probabilities),
        })
    baseline = next(row for row in candidates if row["policy_id"] == "disabled")
    candidates = sorted(
        candidates,
        key=lambda row: (
            float(row.get("market_band_brier", float("inf"))),
            0 if row["policy_id"] == "disabled" else 1,
        ),
    )
    best = candidates[0]
    baseline_brier = baseline.get("market_band_brier")
    best_brier = best.get("market_band_brier")
    if (
        baseline_brier is None
        or best_brier is None
        or best["policy_id"] == "disabled"
        or (float(baseline_brier) - float(best_brier)) < float(min_improvement)
    ):
        selected = baseline
    else:
        selected = best
    return {
        **base_config,
        "enabled": bool(selected.get("enabled")),
        "policy_id": selected.get("policy_id"),
        "adjacent_calibration_enabled": bool(selected.get("adjacent_calibration_enabled")),
        "exact_winner_catchup_enabled": bool(selected.get("exact_winner_catchup_enabled")),
        "forecast_relative_calibration_enabled": bool(selected.get("forecast_relative_calibration_enabled")),
        "partition_normalization_enabled": bool(selected.get("partition_normalization_enabled")),
        "selection": {
            "baseline_market_band_brier": baseline_brier,
            "selected_market_band_brier": selected.get("market_band_brier"),
            "selected_policy_id": selected.get("policy_id"),
            "min_improvement": float(min_improvement),
            "candidates": candidates,
        },
    }


def density_market_band_score(rows, means, grid_f, sigma_f, shape_config=None):
    """Score Gaussian density width on replay-shaped native market bands."""
    if not rows or not means:
        return None
    usable = []
    for row, mean_f in zip(rows or [], means or []):
        if mean_f is None:
            continue
        try:
            mean_f = float(mean_f)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(mean_f):
            continue
        for band_row in density_synthetic_market_band_rows(row):
            low_native, high_native = bucket_interval_native(
                band_row["kind"],
                band_row["value"],
                band_row.get("value_hi"),
            )
            low_f, high_f = native_interval_to_f(
                low_native,
                high_native,
                band_row["unit"],
            )
            usable.append((
                row,
                mean_f,
                float("-inf") if low_f is None else float(low_f),
                float("inf") if high_f is None else float(high_f),
                float(band_row["outcome"]),
                float(band_row.get("_sample_weight", 1.0)),
            ))
    if not usable:
        return None

    sigma = max(0.1, float(sigma_f or 1.0))
    grid = np.asarray([float(value) for value in grid_f], dtype=float)
    source_rows = [row[0] for row in usable]
    means_array = np.asarray([row[1] for row in usable], dtype=float)
    lows = np.asarray([row[2] for row in usable], dtype=float)
    highs = np.asarray([row[3] for row in usable], dtype=float)
    outcomes = np.asarray([row[4] for row in usable], dtype=float)
    sample_weights = np.asarray([row[5] for row in usable], dtype=float)
    weights = density_weight_matrix(source_rows, means_array, grid, sigma, shape_config=shape_config)
    totals = weights.sum(axis=1)
    mask = (grid[None, :] >= lows[:, None]) & (grid[None, :] < highs[:, None])
    bucket_mass = (weights * mask).sum(axis=1)
    probabilities = np.divide(
        bucket_mass,
        totals,
        out=np.zeros_like(bucket_mass, dtype=float),
        where=totals > 0,
    )
    probabilities = np.clip(probabilities, 1e-15, 1.0 - 1e-15)
    briers = (probabilities - outcomes) ** 2
    losses = -(
        outcomes * np.log(probabilities)
        + (1.0 - outcomes) * np.log(1.0 - probabilities)
    )
    weight_sum = float(sample_weights.sum())
    if weight_sum <= 0:
        sample_weights = np.ones_like(sample_weights)
        weight_sum = float(sample_weights.sum())
    return {
        "market_band_rows": int(len(probabilities)),
        "market_band_brier": float(np.average(briers, weights=sample_weights)),
        "market_band_logloss": float(np.average(losses, weights=sample_weights)),
        "market_band_positive_rate": float(np.average(outcomes, weights=sample_weights)),
    }


def density_sigma_candidates(base_sigma_f, scales=DENSITY_SIGMA_TUNING_SCALES, floor=0.35, cap=10.0):
    base = residual_sigma_f([float(base_sigma_f or 3.0)], floor=floor, cap=cap)
    candidates = {base}
    for scale in scales or ():
        try:
            value = float(base) * float(scale)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            candidates.add(max(float(floor), min(float(cap), value)))
    return sorted(round(value, 6) for value in candidates)


def evaluate_density_sigma(rows, means, grid_f, sigma_f, shape_config=None):
    winner_score = density_winner_bucket_score(
        rows,
        means,
        grid_f,
        sigma_f,
        shape_config=shape_config,
    ) or {}
    band_score = density_market_band_score(
        rows,
        means,
        grid_f,
        sigma_f,
        shape_config=shape_config,
    ) or {}
    if not winner_score and not band_score:
        return None
    return {**winner_score, **band_score}


def tune_density_sigma_f(rows, means, grid_f, base_sigma_f):
    """Choose density width against holdout market-band Brier.

    The replay gate scores projected market-band probabilities, not raw
    temperature RMSE or winner-bucket probability alone. A Gaussian width that
    is optimal for the true bucket can still overprice nearby losing bands, so
    the v0.4 density artifact selects sigma from a small holdout grid using
    synthetic native market bands that mirror replay's eq/lte/gte scoring.
    """
    if not rows or not means:
        return None
    candidates = []
    for sigma_f in density_sigma_candidates(base_sigma_f):
        score = evaluate_density_sigma(rows, means, grid_f, sigma_f)
        if not score:
            continue
        candidates.append({
            "sigma_f": sigma_f,
            "density_logloss": score.get("density_logloss"),
            "winning_bucket_brier": score.get("winning_bucket_brier"),
            "mean_absolute_error_f": score.get("mean_absolute_error_f"),
            "market_band_rows": score.get("market_band_rows"),
            "market_band_brier": score.get("market_band_brier"),
            "market_band_logloss": score.get("market_band_logloss"),
            "market_band_positive_rate": score.get("market_band_positive_rate"),
            "n": score.get("n"),
        })
    if not candidates:
        return None
    candidates = sorted(
        candidates,
        key=lambda row: (
            float(row.get("market_band_brier", float("inf"))),
            float(row.get("winning_bucket_brier", float("inf"))),
            float(row.get("density_logloss", float("inf"))),
            abs(float(row.get("sigma_f")) - float(base_sigma_f or row.get("sigma_f"))),
        ),
    )
    return {
        "selected_sigma_f": candidates[0]["sigma_f"],
        "selected_score": candidates[0],
        "base_sigma_f": float(base_sigma_f or candidates[0]["sigma_f"]),
        "candidates": candidates,
    }


def tune_density_shape_policy(rows, means, grid_f, base_sigma_f):
    """Choose sigma and density shape against holdout market-band Brier."""
    if not rows or not means:
        return None
    candidates = []
    for sigma_f in density_sigma_candidates(base_sigma_f):
        for shape_config in DENSITY_SHAPE_TUNING_CANDIDATES:
            shape_cfg = density_shape_config(shape_config)
            score = evaluate_density_sigma(
                rows,
                means,
                grid_f,
                sigma_f,
                shape_config=shape_cfg,
            )
            if not score:
                continue
            candidates.append({
                "sigma_f": sigma_f,
                "density_shape_id": shape_cfg["id"],
                "density_shape": shape_cfg,
                "density_logloss": score.get("density_logloss"),
                "winning_bucket_brier": score.get("winning_bucket_brier"),
                "mean_absolute_error_f": score.get("mean_absolute_error_f"),
                "market_band_rows": score.get("market_band_rows"),
                "market_band_brier": score.get("market_band_brier"),
                "market_band_logloss": score.get("market_band_logloss"),
                "market_band_positive_rate": score.get("market_band_positive_rate"),
                "n": score.get("n"),
            })
    if not candidates:
        return None
    base_shape_id = density_shape_id(DENSITY_DEFAULT_SHAPE)
    candidates = sorted(
        candidates,
        key=lambda row: (
            float(row.get("market_band_brier", float("inf"))),
            float(row.get("winning_bucket_brier", float("inf"))),
            float(row.get("density_logloss", float("inf"))),
            0 if row.get("density_shape_id") == base_shape_id else 1,
            abs(float(row.get("sigma_f")) - float(base_sigma_f or row.get("sigma_f"))),
        ),
    )
    return {
        "selected_sigma_f": candidates[0]["sigma_f"],
        "selected_density_shape_id": candidates[0]["density_shape_id"],
        "selected_density_shape": candidates[0]["density_shape"],
        "selected_score": candidates[0],
        "base_sigma_f": float(base_sigma_f or candidates[0]["sigma_f"]),
        "base_density_shape_id": base_shape_id,
        "candidate_shape_ids": [density_shape_id(row) for row in DENSITY_SHAPE_TUNING_CANDIDATES],
        "candidates": candidates,
    }


def train_band_hour_model(
    train_rows,
    feature_names=None,
    include_dynamic_source_state=False,
    feature_subset=FEATURE_SUBSET_ALL,
):
    build_started = time.perf_counter()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", pd.errors.PerformanceWarning)
        train_frame = band_feature_frame(
            train_rows,
            feature_names=feature_names,
            include_dynamic_source_state=include_dynamic_source_state,
        )
        if feature_names is None:
            train_frame = train_frame.reindex(
                columns=feature_names_for_subset(train_frame.columns, feature_subset),
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
        "feature_subset": feature_subset or FEATURE_SUBSET_ALL,
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
    if config.get("forecast_centering_enabled", False):
        p = apply_forecast_centering(p, row, config=config)
    if config.get("market_bias_calibration_enabled", False):
        p = apply_market_bias_calibration(p, row, config=config)
    return clip_probability(p)


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


def market_bias_calibration_contexts(row):
    """Inference-available fallbacks for broad market/hour/kind bias repair."""
    market_id = row.get("market_id") or "unknown"
    kind = row.get("band_kind") or "unknown"
    hour_bucket = calibration_hour_bucket(row.get("cutoff_hour") or row.get("candidate_cutoff_hour"))
    return [
        f"market={market_id}|hour={hour_bucket}|kind={kind}",
        f"market={market_id}|kind={kind}",
        f"market={market_id}|hour={hour_bucket}",
        f"market={market_id}",
    ]


def _brier_for_probabilities(rows, probabilities):
    pairs = [
        (row, probability)
        for row, probability in zip(rows or [], probabilities or [])
        if probability is not None and row.get("outcome") is not None
    ]
    if not pairs:
        return None
    return sum(
        brier(clip_probability(probability), int(row["outcome"]))
        for row, probability in pairs
    ) / len(pairs)


def _market_brier_map(rows, probabilities):
    grouped = defaultdict(list)
    for row, probability in zip(rows or [], probabilities or []):
        if probability is None or row.get("outcome") is None:
            continue
        grouped[row.get("market_id") or "unknown"].append((row, probability))
    return {
        market_id: sum(
            brier(clip_probability(probability), int(row["outcome"]))
            for row, probability in pairs
        ) / len(pairs)
        for market_id, pairs in grouped.items()
        if pairs
    }


def fit_market_bias_calibration(
    rows,
    probabilities,
    min_rows=120,
    prior_rows=400.0,
    factor_min=0.40,
    factor_max=2.25,
    min_improvement=0.0002,
    max_market_regression=0.0010,
):
    """Fit a conservative multiplicative market/hour/kind calibration.

    The contexts deliberately use only fields available before settlement. The
    calibration is enabled only if it improves holdout Brier and does not create
    a material market-level regression on the same holdout partition.
    """
    stats = defaultdict(lambda: {"n": 0, "outcome_sum": 0.0, "prob_sum": 0.0})
    clean_rows = []
    clean_probabilities = []
    for row, probability in zip(rows or [], probabilities or []):
        if row.get("outcome") is None or probability is None:
            continue
        probability = clip_probability(probability)
        clean_rows.append(row)
        clean_probabilities.append(probability)
        outcome = float(row.get("outcome") or 0.0)
        for context in market_bias_calibration_contexts(row):
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
        "version": "market_hour_kind_bias_v1",
        "enabled": False,
        "min_rows": int(min_rows),
        "prior_rows": float(prior_rows),
        "factor_min": float(factor_min),
        "factor_max": float(factor_max),
        "min_improvement": float(min_improvement),
        "max_market_regression": float(max_market_regression),
        "context_count": len(contexts),
        "contexts": contexts,
    }
    baseline_brier = _brier_for_probabilities(clean_rows, clean_probabilities)
    trial_calibration = {**calibration, "enabled": True}
    candidate_probabilities = [
        apply_market_bias_calibration(
            probability,
            row,
            config={"market_bias_calibration": trial_calibration},
        )
        for row, probability in zip(clean_rows, clean_probabilities)
    ]
    candidate_brier = _brier_for_probabilities(clean_rows, candidate_probabilities)
    baseline_by_market = _market_brier_map(clean_rows, clean_probabilities)
    candidate_by_market = _market_brier_map(clean_rows, candidate_probabilities)
    market_regressions = {
        market_id: candidate_by_market[market_id] - baseline_brier
        for market_id, baseline_brier in baseline_by_market.items()
        if market_id in candidate_by_market
        and candidate_by_market[market_id] - baseline_brier > float(max_market_regression)
    }
    enabled = (
        baseline_brier is not None
        and candidate_brier is not None
        and candidate_brier <= baseline_brier - float(min_improvement)
        and not market_regressions
        and bool(contexts)
    )
    calibration.update({
        "enabled": bool(enabled),
        "selection": {
            "baseline_brier": baseline_brier,
            "candidate_brier": candidate_brier,
            "delta_brier": (
                candidate_brier - baseline_brier
                if baseline_brier is not None and candidate_brier is not None
                else None
            ),
            "market_regressions": market_regressions,
        },
    })
    if not enabled:
        calibration["disabled_reason"] = (
            "holdout_brier_or_market_regression_gate_failed"
            if contexts else
            "no_contexts"
        )
    return calibration


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
    grouped = _band_validation_groups(rows)
    return _normalize_band_probabilities_for_groups(probabilities, grouped, gamma=gamma)


def _band_validation_groups(rows):
    grouped = defaultdict(list)
    for idx, row in enumerate(rows):
        grouped[_band_validation_partition_key(row)].append(idx)
    return grouped


def _normalize_band_probabilities_for_groups(probabilities, grouped, gamma=1.25):
    gamma = max(0.1, float(gamma or 1.0))
    output = [clip_probability(probability) for probability in probabilities]
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


def _slice_brier_indexes(outcomes, probabilities, indexes):
    pairs = [
        (int(outcomes[idx]), float(probabilities[idx]))
        for idx in indexes
        if outcomes[idx] is not None
    ]
    if not pairs:
        return {"n": 0, "brier": None, "base_rate": None, "mean_probability": None}
    return {
        "n": len(pairs),
        "brier": sum(brier(probability, outcome) for outcome, probability in pairs) / len(pairs),
        "base_rate": sum(outcome for outcome, _ in pairs) / len(pairs),
        "mean_probability": sum(probability for _, probability in pairs) / len(pairs),
    }


def _exact_winner_factor_delta(row, contexts):
    if not contexts:
        return 0.0
    for context in exact_winner_catchup_contexts(row):
        entry = contexts.get(context)
        if entry is None:
            continue
        if isinstance(entry, dict):
            factor = float(entry.get("factor", 1.0))
        else:
            factor = float(entry)
        return factor - 1.0
    return 0.0


def _strength_candidate_probabilities_precomputed(
    probabilities,
    factor_deltas,
    groups,
    strength,
    normalization_gamma=1.25,
):
    adjusted = [
        clip_probability(probability * (1.0 + float(strength) * delta))
        for probability, delta in zip(probabilities, factor_deltas)
    ]
    return _normalize_band_probabilities_for_groups(
        adjusted,
        groups,
        gamma=normalization_gamma,
    )


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
    groups = _band_validation_groups(rows)
    baseline = _normalize_band_probabilities_for_groups(
        probabilities,
        groups,
        gamma=normalization_gamma,
    )
    outcomes = []
    distance0_indexes = []
    one_above_indexes = []
    eq_indexes = []
    for idx, row in enumerate(rows):
        try:
            outcome = int(row["outcome"]) if row.get("outcome") is not None else None
        except (TypeError, ValueError):
            outcome = None
        outcomes.append(outcome)
        distance = _settlement_distance_value(row)
        if distance == 0:
            distance0_indexes.append(idx)
        if distance == 1:
            one_above_indexes.append(idx)
        if row.get("band_kind") == "eq":
            eq_indexes.append(idx)
    factor_deltas = [
        _exact_winner_factor_delta(row, calibration.get("contexts") or {})
        for row in rows
    ]
    baseline_distance0 = _slice_brier_indexes(outcomes, baseline, distance0_indexes)
    baseline_one_above = _slice_brier_indexes(outcomes, baseline, one_above_indexes)
    baseline_eq = _slice_brier_indexes(outcomes, baseline, eq_indexes)

    candidates = []
    selected = None
    for strength in grid:
        candidate = _strength_candidate_probabilities_precomputed(
            probabilities,
            factor_deltas,
            groups,
            strength,
            normalization_gamma=normalization_gamma,
        )
        distance0 = _slice_brier_indexes(outcomes, candidate, distance0_indexes)
        one_above = _slice_brier_indexes(outcomes, candidate, one_above_indexes)
        eq = _slice_brier_indexes(outcomes, candidate, eq_indexes)
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


def default_band_postprocess(
    exact_winner_catchup_enabled=False,
    exact_winner_shadow_blend=True,
):
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
        "forecast_centering_enabled": False,
        "forecast_centering_sigma": 1.25,
        "forecast_centering_default_alpha": 0.0,
        "forecast_centering_early_alpha": 0.0,
        "forecast_centering_alpha_by_hour": {},
        "market_bias_calibration_enabled": False,
        "market_bias_calibration": {},
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
    if exact_winner_catchup_enabled and exact_winner_shadow_blend:
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


def apply_source_freshness_guardrail(
    artifact,
    policy_id="item35_all_fresh_only_candidate_v0_1",
):
    """Blend non-all-fresh replay rows fully back to incumbent serving."""
    postprocess = artifact.setdefault("postprocess", {})
    postprocess["current_blend_source_freshness_default_alpha"] = 0.0
    postprocess["current_blend_source_freshness_alpha"] = {
        "all_fresh": 1.0,
    }
    postprocess["source_freshness_guardrail_policy"] = policy_id
    for bundle in (artifact.get("models") or {}).values():
        bundle["postprocess"] = dict(postprocess)
    return artifact


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
        "schema_version": "pooled_continuous_density_hgb_v0.7",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "family_unit": "all",
        "prediction_mode": "continuous_density_f",
        "objective": "canonical_f_density_shape_holdout_forecast_relative_band_postprocess",
        "trained_at": datetime.now().isoformat(),
        "grid_low_f": low_f,
        "grid_high_f": high_f,
        "grid_step_f": float(grid_step_f),
        "sigma_policy": {
            "preferred": "holdout_market_band_brier_grid_search",
            "fallback": "in_sample_residual_rmse",
            "min_validation_residuals": int(min_sigma_validation_residuals),
            "candidate_scales": list(DENSITY_SIGMA_TUNING_SCALES),
        },
        "density_shape_policy": {
            "preferred": "holdout_market_band_brier_shape_grid_search",
            "fallback": "gaussian_in_sample_residual_rmse",
            "candidate_shape_ids": [
                density_shape_id(row)
                for row in DENSITY_SHAPE_TUNING_CANDIDATES
            ],
        },
        "blocked_validation": blocked_validation_audit(canonical_records),
        "models": {},
    }
    validation_rows = []
    density_calibration_rows = []
    density_calibration_probabilities = []
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
        baseline_eval_score = None
        market_scores = []
        eval_residuals = []
        sigma_tuning = None
        shape_tuning = None
        if eval_rows:
            eval_means = predict_density_means(
                model,
                imputer,
                feature_names,
                eval_rows,
            )
            eval_residuals = density_residuals_from_means(eval_rows, eval_means)
            baseline_eval_score = evaluate_density_sigma(eval_rows, eval_means, grid_f, sigma_f)
            sigma_tuning = tune_density_sigma_f(eval_rows, eval_means, grid_f, sigma_f)
            shape_tuning = tune_density_shape_policy(eval_rows, eval_means, grid_f, sigma_f)
            tuned_sigma_f = (
                (shape_tuning or {}).get("selected_sigma_f")
                if len(eval_residuals) >= int(min_sigma_validation_residuals)
                else None
            )
            tuned_shape = (
                (shape_tuning or {}).get("selected_density_shape")
                if len(eval_residuals) >= int(min_sigma_validation_residuals)
                else None
            )
            eval_sigma_f = tuned_sigma_f if tuned_sigma_f is not None else sigma_f
            eval_shape = density_shape_config(tuned_shape)
            eval_score = evaluate_density_sigma(
                eval_rows,
                eval_means,
                grid_f,
                eval_sigma_f,
                shape_config=eval_shape,
            )
            post_rows, post_probabilities = density_projected_market_band_rows_and_probabilities(
                eval_rows,
                eval_means,
                grid_f,
                eval_sigma_f,
                shape_config=eval_shape,
            )
            density_calibration_rows.extend(post_rows)
            density_calibration_probabilities.extend(post_probabilities)
            for market_id in sorted({row["market_id"] for row in eval_rows}):
                subset = [
                    (row, mean)
                    for row, mean in zip(eval_rows, eval_means)
                    if row["market_id"] == market_id
                ]
                score = evaluate_density_sigma(
                    [row for row, _ in subset],
                    [mean for _, mean in subset],
                    grid_f,
                    eval_sigma_f,
                    shape_config=eval_shape,
                )
                if score:
                    market_scores.append({
                        "market_id": market_id,
                        "density_shape_id": eval_shape["id"],
                        **score,
                    })

        final_model, final_imputer, final_feature_names, final_residuals, final_metrics = train_density_hour_model(hour_rows)
        if len(eval_residuals) >= int(min_sigma_validation_residuals) and (shape_tuning or {}).get("selected_sigma_f"):
            final_sigma_source = "holdout_market_band_brier_shape_grid_search"
            final_sigma_residuals = eval_residuals
            final_sigma_f = float(shape_tuning["selected_sigma_f"])
            final_density_shape = density_shape_config(shape_tuning.get("selected_density_shape"))
            final_density_shape_source = "holdout_market_band_brier_shape_grid_search"
        else:
            final_sigma_source = "in_sample_residual_rmse"
            final_sigma_residuals = final_residuals
            final_sigma_f = residual_sigma_f(final_sigma_residuals)
            final_density_shape = density_shape_config(DENSITY_DEFAULT_SHAPE)
            final_density_shape_source = "gaussian_fallback"
        artifact["models"][str(hour)] = {
            "model": final_model,
            "imputer": final_imputer,
            "feature_names": final_feature_names,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "train_rows": len(hour_rows),
            "sigma_f": final_sigma_f,
            "sigma_source": final_sigma_source,
            "sigma_residual_count": len(final_sigma_residuals),
            "density_shape_id": final_density_shape["id"],
            "density_shape": final_density_shape,
            "density_shape_source": final_density_shape_source,
            "sigma_tuning": sigma_tuning,
            "density_shape_tuning": shape_tuning,
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
            "final_density_shape_id": final_density_shape["id"],
            "final_density_shape_source": final_density_shape_source,
            "holdout_sigma_residual_count": len(eval_residuals),
            "eval_score": eval_score,
            "baseline_eval_score": baseline_eval_score,
            "sigma_tuning": sigma_tuning,
            "density_shape_tuning": shape_tuning,
            "market_scores": market_scores,
            "training_metrics": train_metrics,
            "blocked_validation": blocked_validation_audit(hour_rows),
        })
    if density_calibration_rows:
        artifact["density_postprocess"] = fit_density_market_band_postprocess(
            density_calibration_rows,
            density_calibration_probabilities,
        )
    else:
        artifact["density_postprocess"] = {
            "schema_version": "density_market_band_postprocess_v0.2",
            "enabled": False,
            "calibration_rows": 0,
            "reason": "no holdout market-band calibration rows",
        }
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


def train_pooled_band_models(
    records,
    holdout_year=None,
    exact_winner_catchup=False,
    dynamic_source_state=False,
    feature_subset=FEATURE_SUBSET_ALL,
    weak_family_disposition=None,
    reanalysis_promotion_lane=None,
    family_unit="F",
    source_freshness_guardrail=False,
    write_merge_payload=False,
):
    if exact_winner_catchup and dynamic_source_state:
        raise ValueError("exact_winner_catchup and dynamic_source_state are separate shadow variants")
    feature_subset = feature_subset or FEATURE_SUBSET_ALL
    if feature_subset not in FEATURE_SUBSET_CHOICES:
        raise ValueError(f"Unknown pooled feature subset: {feature_subset}")
    if feature_subset != FEATURE_SUBSET_ALL and (exact_winner_catchup or dynamic_source_state):
        raise ValueError("feature subsets are separate candidate lanes from exact/dynamic source variants")
    by_hour = defaultdict(list)
    for row in records:
        by_hour[int(row["cutoff_hour"])].append(row)

    support = band_training_support(records, family_unit=family_unit)
    all_market_band = str(family_unit or "").lower() == "all"
    schema_version = (
        "pooled_all_market_band_hgb_v0.1"
        if all_market_band else
        "pooled_feature_band_hgb_v0.3"
    )
    objective = (
        "binary_native_market_band_brier_all_market_source_reliability"
        if all_market_band else
        "binary_market_band_brier_source_reliability"
    )
    if exact_winner_catchup:
        schema_version = (
            "pooled_all_market_band_hgb_exact_winner_v0.1"
            if all_market_band else
            "pooled_feature_band_hgb_v0.4"
        )
        objective = (
            "binary_native_market_band_brier_all_market_exact_winner_catchup"
            if all_market_band else
            "binary_market_band_brier_source_reliability_exact_winner_catchup"
        )
    if dynamic_source_state:
        schema_version = "pooled_feature_band_hgb_v0.5"
        objective = "binary_market_band_brier_dynamic_source_state"
    if feature_subset == FEATURE_SUBSET_FORECAST_PROFILE:
        schema_version = "pooled_feature_band_hgb_forecast_profile_v0.1"
        objective = "binary_market_band_brier_forecast_profile_calibrated"
    artifact = {
        "schema_version": schema_version,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "family_unit": family_unit,
        "prediction_mode": "band_binary",
        "objective": objective,
        "feature_subset": feature_subset,
        "feature_subset_contract": feature_subset_contract(feature_subset),
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
            exact_winner_shadow_blend=not all_market_band,
        ),
    }
    if feature_subset == FEATURE_SUBSET_FORECAST_PROFILE:
        artifact["forecast_profile_calibration"] = {
            "schema_version": "forecast_profile_calibration_v0.1",
            "status": "shadow_candidate",
            "anchor_feature": "forecast_high",
            "feature_subset": feature_subset,
            "daily_first_replay_required": True,
            "promotion_blocker": (
                "Forecast-profile weighting cannot promote unless replay "
                "proves early-day lift, midday/late guardrails, and "
                "per-market high-disagreement safety."
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
    if source_freshness_guardrail:
        apply_source_freshness_guardrail(artifact)
    apply_reanalysis_lane_metadata(artifact, reanalysis_promotion_lane)
    validation_rows = []
    calibration_rows = []
    calibration_probabilities = []
    merge_payload_rows = []
    merge_payload_probabilities = []
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
            feature_subset=feature_subset,
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
                if write_merge_payload:
                    merge_payload_rows.extend(eval_band_rows)
                    merge_payload_probabilities.extend(post_probs)
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
            feature_subset=feature_subset,
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

    market_bias_rows = []
    market_bias_probabilities = []
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
        validation["_eval_band_rows_for_market_bias"] = eval_band_rows
        validation["_probabilities_for_market_bias"] = calibrated_probs
        market_bias_rows.extend(eval_band_rows)
        market_bias_probabilities.extend(calibrated_probs)

    market_bias_calibration = fit_market_bias_calibration(
        market_bias_rows,
        market_bias_probabilities,
    )
    artifact["postprocess"]["market_bias_calibration"] = market_bias_calibration
    artifact["postprocess"]["market_bias_calibration_enabled"] = bool(
        market_bias_calibration.get("enabled")
    )

    for validation in validation_rows:
        eval_band_rows = validation.pop("_eval_band_rows_for_market_bias", [])
        calibrated_probs = validation.pop("_probabilities_for_market_bias", [])
        if not eval_band_rows or not calibrated_probs:
            continue
        final_probs = [
            apply_market_bias_calibration(
                probability,
                row,
                config=artifact["postprocess"],
            )
            for row, probability in zip(eval_band_rows, calibrated_probs)
        ]
        validation["eval_score"] = evaluate_band_predictions(eval_band_rows, final_probs)
        market_scores = []
        for market_id in sorted({row["market_id"] for row in eval_band_rows}):
            subset = [
                (row, probability)
                for row, probability in zip(eval_band_rows, final_probs)
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
    model_feature_names = sorted({
        feature
        for bundle in artifact["models"].values()
        for feature in (bundle.get("feature_names") or [])
    })
    artifact["weak_input_family_preflight"] = weak_input_training_preflight(
        model_feature_names,
        weak_family_disposition,
    )
    if write_merge_payload:
        artifact[BAND_MERGE_PAYLOAD_KEY] = {
            "holdout_year": holdout_year,
            "hours": sorted(int(hour) for hour in artifact["models"]),
            "rows": merge_payload_rows,
            "probabilities": merge_payload_probabilities,
        }
    return artifact, validation_rows


def write_artifact(artifact, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        pickle.dump(artifact, handle)
    return path


def load_artifact(path):
    with Path(path).open("rb") as handle:
        return pickle.load(handle)


MERGE_COMPATIBILITY_KEYS = (
    "schema_version",
    "feature_schema_version",
    "family_unit",
    "prediction_mode",
    "objective",
    "feature_subset",
    "feature_subset_contract",
    "dynamic_source_state_enabled",
    "dynamic_source_state_columns",
    "source_family_lanes",
    "reanalysis_promotion_lane",
    "support",
)


def _merge_signature(artifact):
    return {
        key: artifact.get(key)
        for key in MERGE_COMPATIBILITY_KEYS
    }


def _artifact_model_hours(artifact):
    return sorted(int(hour) for hour in (artifact.get("models") or {}))


def _validate_band_merge_payload(artifact, label):
    payload = artifact.get(BAND_MERGE_PAYLOAD_KEY) or {}
    rows = payload.get("rows") or []
    probabilities = payload.get("probabilities") or []
    if not rows or not probabilities:
        raise ValueError(f"{label} is missing {BAND_MERGE_PAYLOAD_KEY}; retrain shard with --write-merge-payload")
    if len(rows) != len(probabilities):
        raise ValueError(
            f"{label} merge payload has mismatched rows/probabilities "
            f"({len(rows)} != {len(probabilities)})"
        )
    return payload


def merge_band_postprocess(rows, probabilities, base_postprocess):
    postprocess = dict(base_postprocess or {})
    adjacent = fit_adjacent_calibration(rows, probabilities)
    postprocess["adjacent_calibration"] = adjacent
    adjacent_probabilities = [
        apply_adjacent_calibration(probability, row, config=postprocess)
        for row, probability in zip(rows, probabilities)
    ]
    calibrated_probabilities = adjacent_probabilities
    if postprocess.get("exact_winner_catchup_enabled", False):
        exact = fit_exact_winner_catchup(
            rows,
            adjacent_probabilities,
            guardrail_rows=rows,
            guardrail_probabilities=adjacent_probabilities,
            normalization_gamma=postprocess.get("partition_normalization_gamma", 1.25),
        )
        postprocess["exact_winner_catchup"] = exact
        calibrated_probabilities = [
            apply_exact_winner_catchup(probability, row, config=postprocess)
            for row, probability in zip(rows, adjacent_probabilities)
        ]
    market_bias = fit_market_bias_calibration(rows, calibrated_probabilities)
    postprocess["market_bias_calibration"] = market_bias
    postprocess["market_bias_calibration_enabled"] = bool(market_bias.get("enabled"))
    return postprocess


def merge_pooled_band_artifacts(artifacts, required_hours=None, shard_paths=None):
    artifacts = list(artifacts or [])
    shard_paths = [str(path) for path in (shard_paths or [])]
    if not artifacts:
        raise ValueError("At least one band artifact shard is required.")
    base_signature = _merge_signature(artifacts[0])
    if base_signature.get("prediction_mode") != "band_binary":
        raise ValueError("Only band_binary artifacts can be merged.")

    merged = {
        key: value
        for key, value in artifacts[0].items()
        if key not in {"models", BAND_MERGE_PAYLOAD_KEY}
    }
    merged["models"] = {}
    merged_hours = set()
    merge_rows = []
    merge_probabilities = []
    shard_summaries = []
    for index, artifact in enumerate(artifacts):
        label = shard_paths[index] if index < len(shard_paths) else f"shard {index + 1}"
        signature = _merge_signature(artifact)
        if signature != base_signature:
            raise ValueError(f"{label} is incompatible with the first shard.")
        payload = _validate_band_merge_payload(artifact, label)
        hours = _artifact_model_hours(artifact)
        duplicates = sorted(set(hours) & merged_hours)
        if duplicates:
            raise ValueError(f"{label} duplicates already-merged hour(s): {duplicates}")
        merged_hours.update(hours)
        merged["models"].update(artifact.get("models") or {})
        merge_rows.extend(payload.get("rows") or [])
        merge_probabilities.extend(payload.get("probabilities") or [])
        shard_summaries.append({
            "path": label,
            "hours": hours,
            "merge_rows": len(payload.get("rows") or []),
        })

    required = set(int(hour) for hour in (required_hours or []))
    missing = sorted(required - merged_hours)
    if missing:
        raise ValueError(f"Merged artifact is missing required hour(s): {missing}")

    merged["postprocess"] = merge_band_postprocess(
        merge_rows,
        merge_probabilities,
        artifacts[0].get("postprocess") or {},
    )
    for bundle in merged["models"].values():
        if isinstance(bundle, dict):
            bundle["postprocess"] = dict(merged["postprocess"])
    model_feature_names = sorted({
        feature
        for bundle in merged["models"].values()
        for feature in (bundle.get("feature_names") or [])
    })
    merged["weak_input_family_preflight"] = weak_input_training_preflight(
        model_feature_names,
        None,
    )
    merged["trained_at"] = datetime.now().isoformat()
    merged["training_shards"] = {
        "shard_count": len(artifacts),
        "hours": sorted(merged_hours),
        "required_hours": sorted(required),
        "postprocess_fit_rows": len(merge_rows),
        "shards": shard_summaries,
    }
    return merged


def merge_pooled_band_artifact_shards(paths, required_hours=None):
    paths = [Path(path) for path in (paths or [])]
    artifacts = [load_artifact(path) for path in paths]
    return merge_pooled_band_artifacts(
        artifacts,
        required_hours=required_hours,
        shard_paths=paths,
    )


def write_band_shard_merge_report(path, artifact, artifact_path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    shards = artifact.get("training_shards") or {}
    postprocess = artifact.get("postprocess") or {}
    market_bias = postprocess.get("market_bias_calibration") or {}
    lines = [
        "# F-Family Pooled Band Shard Merge",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Artifact: `{artifact_path}`",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Schema", artifact.get("schema_version")],
            ["Feature schema", artifact.get("feature_schema_version")],
            ["Objective", artifact.get("objective")],
            ["Family unit", artifact.get("family_unit")],
            ["Merged hours", ", ".join(str(hour) for hour in shards.get("hours") or [])],
            ["Required hours", ", ".join(str(hour) for hour in shards.get("required_hours") or [])],
            ["Shard count", shards.get("shard_count")],
            ["Postprocess fit rows", shards.get("postprocess_fit_rows")],
            ["Adjacent contexts", (postprocess.get("adjacent_calibration") or {}).get("context_count", 0)],
            ["Market bias enabled", bool(market_bias.get("enabled"))],
            ["Market bias contexts", market_bias.get("context_count", 0)],
        ],
    )
    rows = []
    for shard in shards.get("shards") or []:
        rows.append([
            shard.get("path"),
            ", ".join(str(hour) for hour in shard.get("hours") or []),
            shard.get("merge_rows"),
        ])
    if rows:
        lines += [
            "",
            "## Shards",
            "",
        ]
        lines += markdown_table(["Path", "Hours", "Merge Rows"], rows)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
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
    density_postprocess = artifact.get("density_postprocess") or {}
    lines = [
        "# Pooled Continuous-Density Model",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Schema: `{artifact.get('schema_version') or 'pooled_continuous_density_hgb_v0.7'}`",
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
        "and emits a continuous density on the canonical-F grid. Market C/F",
        "bands are projected only at serving/replay time through",
        "`continuous_density_f` payloads.",
        "v0.4 estimates the final Gaussian width by grid-searching holdout",
        "market-band Brier on synthetic native eq/lte/gte bands when enough",
        "holdout rows exist, falling back to in-sample residuals only when",
        "validation evidence is too sparse.",
        "v0.5 extends that search to density-shape policies, including modest",
        "tail mixtures and forecast/climatology anchor mixtures, while retaining",
        "Gaussian fallback when holdout evidence is too sparse.",
        "v0.6 fits a holdout market-band postprocess for density projections,",
        "using exact-winner catch-up and adjacent-band shrinkage before replay",
        "partition normalization.",
        "v0.7 adds a holdout-selected forecast-relative calibration layer for",
        "band-vs-forecast pressure, forecast disagreement, source count, hour,",
        "market, and floor-gap contexts.",
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
        "## Density Market-Band Postprocess",
        "",
    ]
    exact = density_postprocess.get("exact_winner_catchup") or {}
    adjacent = density_postprocess.get("adjacent_calibration") or {}
    forecast_relative = density_postprocess.get("forecast_relative_calibration") or {}
    selection = density_postprocess.get("selection") or {}
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Schema", density_postprocess.get("schema_version") or "-"],
            ["Enabled", bool(density_postprocess.get("enabled"))],
            ["Selected policy", density_postprocess.get("policy_id") or "-"],
            ["Baseline band Brier", fmt_num(selection.get("baseline_market_band_brier"))],
            ["Selected band Brier", fmt_num(selection.get("selected_market_band_brier"))],
            ["Calibration rows", density_postprocess.get("calibration_rows", 0)],
            ["Adjacent contexts", adjacent.get("context_count", 0)],
            ["Exact-winner contexts", exact.get("context_count", 0)],
            ["Exact selected strength", fmt_num(exact.get("strength"))],
            ["Forecast-relative enabled", bool(density_postprocess.get("forecast_relative_calibration_enabled"))],
            ["Forecast-relative contexts", forecast_relative.get("context_count", 0)],
            ["Forecast-relative strength", fmt_num(forecast_relative.get("strength"))],
            ["Partition normalization", bool(density_postprocess.get("partition_normalization_enabled"))],
            ["Partition gamma", fmt_num(density_postprocess.get("partition_normalization_gamma"))],
        ],
    )
    lines += [
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
        ["Hour", "Train Rows", "Eval Rows", "RMSE Sigma F", "Final Sigma F", "Shape", "Sigma Source",
         "RMSE Band Brier", "Tuned Band Brier", "Winner Brier", "Density LogLoss", "MAE F"],
        [
            [
                f"{row['hour']:02d}:00",
                row["train_rows"],
                row["eval_rows"],
                fmt_num(row.get("sigma_f")),
                fmt_num(row.get("final_sigma_f")),
                row.get("final_density_shape_id") or "gaussian",
                row.get("final_sigma_source") or "-",
                fmt_num((row.get("baseline_eval_score") or {}).get("market_band_brier")),
                fmt_num((row.get("eval_score") or {}).get("market_band_brier")),
                fmt_num((row.get("eval_score") or {}).get("winning_bucket_brier")),
                fmt_num((row.get("eval_score") or {}).get("density_logloss")),
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
                score.get("density_shape_id") or row.get("final_density_shape_id") or "gaussian",
                fmt_num(score.get("market_band_brier")),
                fmt_num(score.get("density_logloss")),
                fmt_num(score.get("winning_bucket_brier")),
                fmt_num(score.get("mean_absolute_error_f")),
            ])
    lines += markdown_table(
        ["Market", "Hour", "Rows", "Shape", "Band Brier", "Density LogLoss", "Winner Brier", "MAE F"],
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
    family_unit = artifact.get("family_unit") or "F"
    family_label = "All-Market" if str(family_unit).lower() == "all" else f"{family_unit}-Family"
    subset_contract = artifact.get("feature_subset_contract") or feature_subset_contract(
        artifact.get("feature_subset") or FEATURE_SUBSET_ALL
    )
    lines = [
        f"# {family_label} Pooled Band Model {schema}",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Feature schema: `{FEATURE_SCHEMA_VERSION}`",
        f"Artifact: `{artifact_path}`",
        f"Family unit: `{family_unit}`",
        f"Objective: `{artifact.get('objective') or 'binary_market_band_brier_source_reliability'}`",
        f"Feature subset: `{subset_contract.get('name')}`",
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
        "## Feature Subset Contract",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Subset", subset_contract.get("name")],
            ["Schema", subset_contract.get("schema_version")],
            ["Anchor", subset_contract.get("anchor_feature") or "-"],
            ["Description", subset_contract.get("description") or "-"],
            ["Allowed families", ", ".join(subset_contract.get("allowed_feature_families") or []) or "-"],
            ["Blocked families", ", ".join(subset_contract.get("blocked_feature_families") or []) or "-"],
            ["Postprocess policy", subset_contract.get("postprocess_policy") or "-"],
        ],
    )
    market_bias = postprocess.get("market_bias_calibration") or {}
    market_bias_selection = market_bias.get("selection") or {}
    lines += [
        "",
        "## Postprocess Calibration",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Adjacent calibration contexts", (postprocess.get("adjacent_calibration") or {}).get("context_count", 0)],
            ["Market bias calibration enabled", bool(postprocess.get("market_bias_calibration_enabled"))],
            ["Market bias calibration contexts", market_bias.get("context_count", 0)],
            [
                "Market bias holdout Brier",
                (
                    f"{fmt_num(market_bias_selection.get('baseline_brier'))} -> "
                    f"{fmt_num(market_bias_selection.get('candidate_brier'))}"
                ),
            ],
            ["Market bias holdout delta", fmt_num(market_bias_selection.get("delta_brier"))],
            ["Market bias disabled reason", market_bias.get("disabled_reason") or "-"],
        ],
    )
    lines += [
        "",
        "## Training Throughput",
        "",
    ]
    lines += markdown_table(
        ["Hour", "Matrix Rows", "Matrix Columns", "Build Seconds", "Fit Seconds", "Warnings"],
        training_metric_rows(validation_rows),
    )
    lines.append("")
    weak_preflight = artifact.get("weak_input_family_preflight") or {}
    lines += [
        "## Weak Input-Family Preflight",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Status", weak_preflight.get("status") or "-"],
            ["Features checked", weak_preflight.get("feature_count", 0)],
            ["Diagnostic families", ", ".join(weak_preflight.get("diagnostic_only_families") or []) or "-"],
            ["Warning count", len(weak_preflight.get("warnings") or [])],
        ],
    )
    if weak_preflight.get("warnings"):
        lines += ["", "### Weak-Family Warnings", ""]
        lines += markdown_table(
            ["Family", "Disposition", "Features", "Reasons"],
            [
                [
                    row.get("family"),
                    row.get("disposition"),
                    row.get("feature_count"),
                    "; ".join(row.get("reasons") or []),
                ]
                for row in weak_preflight.get("warnings") or []
            ],
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


def training_output_paths(args):
    if args.objective == "density":
        return (
            args.artifact or str(DEFAULT_DENSITY_ARTIFACT),
            args.out or str(DEFAULT_DENSITY_REPORT),
        )
    if args.objective == "band":
        artifact = args.artifact or str(
            DEFAULT_FORECAST_PROFILE_BAND_ARTIFACT
            if args.feature_subset == FEATURE_SUBSET_FORECAST_PROFILE else
            DEFAULT_EXACT_WINNER_ARTIFACT
            if args.exact_winner_catchup else
            DEFAULT_DYNAMIC_SOURCE_ARTIFACT
            if args.dynamic_source_state else
            DEFAULT_BAND_ARTIFACT
        )
        report = args.out or str(
            DEFAULT_FORECAST_PROFILE_BAND_REPORT
            if args.feature_subset == FEATURE_SUBSET_FORECAST_PROFILE else
            DEFAULT_EXACT_WINNER_REPORT
            if args.exact_winner_catchup else
            DEFAULT_DYNAMIC_SOURCE_REPORT
            if args.dynamic_source_state else
            DEFAULT_BAND_REPORT
        )
        return artifact, report
    return (
        args.artifact or str(DEFAULT_ARTIFACT),
        args.out or str(DEFAULT_REPORT),
    )


def preflight_training_artifacts(
    artifact_path,
    report_path,
    min_free_bytes=DEFAULT_ARTIFACT_EXPORT_MIN_FREE_BYTES,
):
    min_free_bytes = int(min_free_bytes or 0)
    if not min_free_bytes:
        return []
    checks = []
    checks.append(ensure_artifact_disk_headroom(
        artifact_path,
        estimated_bytes=DEFAULT_TRAINING_OUTPUT_ESTIMATED_BYTES,
        min_free_bytes=min_free_bytes,
        context="pooled feature model training outputs",
    ))
    artifact_parent = Path(artifact_path).parent.resolve()
    report_parent = Path(report_path).parent.resolve()
    if report_parent != artifact_parent:
        checks.append(ensure_artifact_disk_headroom(
            report_path,
            estimated_bytes=1_000_000,
            min_free_bytes=min_free_bytes,
            context="pooled feature model training report",
        ))
    return [check for check in checks if check is not None]


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
    parser.add_argument("--source-freshness-guardrail", action="store_true",
                        help="Blend non-all-fresh replay rows fully back to current serving.")
    parser.add_argument("--feature-subset", default=FEATURE_SUBSET_ALL, choices=FEATURE_SUBSET_CHOICES,
                        help="Optional band-model feature subset. Use forecast_profile for roadmap item 134.")
    parser.add_argument("--reanalysis-lane-json", default=None,
                        help="Source-family inventory JSON or promotion-lane JSON for Item 32 allowed-market masking.")
    parser.add_argument("--min-artifact-free-bytes", type=int, default=DEFAULT_ARTIFACT_EXPORT_MIN_FREE_BYTES,
                        help="Require this much free disk headroom before fitting and writing model artifacts. Use 0 to disable.")
    parser.add_argument("--write-merge-payload", action="store_true",
                        help="Embed holdout band rows/probabilities needed to merge hour-sharded band artifacts.")
    parser.add_argument("--merge-band-shards", nargs="+", default=None,
                        help="Merge hour-sharded band artifacts trained with --write-merge-payload.")
    parser.add_argument("--artifact", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    if args.merge_band_shards:
        required_hours = parse_hours(args.hours)
        artifact_path_arg = args.artifact or str(DEFAULT_BAND_ARTIFACT)
        report_path_arg = args.out or str(DEFAULT_BAND_REPORT)
        preflight_training_artifacts(
            artifact_path_arg,
            report_path_arg,
            min_free_bytes=args.min_artifact_free_bytes,
        )
        artifact = merge_pooled_band_artifact_shards(
            args.merge_band_shards,
            required_hours=required_hours,
        )
        artifact_path = write_artifact(artifact, artifact_path_arg)
        report_path = write_band_shard_merge_report(
            report_path_arg,
            artifact,
            artifact_path,
        )
        print(
            f"Merged {len(args.merge_band_shards)} pooled band shard(s) into {artifact_path} "
            f"and report {report_path}."
        )
        return
    if args.exact_winner_catchup and args.dynamic_source_state:
        raise SystemExit("--exact-winner-catchup and --dynamic-source-state are separate shadow variants")
    if args.source_freshness_guardrail and args.objective != "band":
        raise SystemExit("--source-freshness-guardrail is currently supported only with --objective band")
    if args.source_freshness_guardrail and args.dynamic_source_state:
        raise SystemExit("--source-freshness-guardrail and --dynamic-source-state are separate guardrails")
    if args.feature_subset != FEATURE_SUBSET_ALL and args.objective != "band":
        raise SystemExit("--feature-subset is currently supported only with --objective band")
    if args.feature_subset != FEATURE_SUBSET_ALL and (args.exact_winner_catchup or args.dynamic_source_state):
        raise SystemExit("--feature-subset lanes cannot be combined with exact/dynamic source variants")
    reanalysis_promotion_lane = load_reanalysis_promotion_lane(args.reanalysis_lane_json)
    family_unit = args.family_unit or ("all" if args.objective == "density" else "F")
    if args.objective == "bucket" and family_unit != "F":
        raise SystemExit("--family-unit all is currently only supported with --objective band or density")
    if (
        args.objective == "band"
        and str(family_unit).lower() == "all"
        and (
            args.dynamic_source_state
            or args.feature_subset != FEATURE_SUBSET_ALL
            or args.reanalysis_lane_json
        )
    ):
        raise SystemExit(
            "--family-unit all --objective band is an Item 35 direct-band baseline "
            "and cannot be combined with F-family shadow lanes"
        )

    artifact_path_arg, report_path_arg = training_output_paths(args)
    preflight_training_artifacts(
        artifact_path_arg,
        report_path_arg,
        min_free_bytes=args.min_artifact_free_bytes,
    )

    records, counts = build_family_dataset(
        unit=family_unit,
        cutoff_hours=parse_hours(args.hours),
        max_days_per_market=args.max_days_per_market or None,
        reanalysis_promotion_lane=reanalysis_promotion_lane,
    )
    if not records:
        raise SystemExit("No pooled family records available.")
    if args.objective == "density":
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
        artifact, validation_rows = train_pooled_band_models(
            records,
            holdout_year=args.holdout_year,
            exact_winner_catchup=args.exact_winner_catchup,
            dynamic_source_state=args.dynamic_source_state,
            feature_subset=args.feature_subset,
            reanalysis_promotion_lane=reanalysis_promotion_lane,
            family_unit=family_unit,
            source_freshness_guardrail=args.source_freshness_guardrail,
            write_merge_payload=args.write_merge_payload,
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
