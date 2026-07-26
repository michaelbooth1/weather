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
from datetime import date, datetime
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
from weather.reporting.data_quality.artifact_disk_budget import (
    DEFAULT_ARTIFACT_EXPORT_MIN_FREE_BYTES,
    ensure_artifact_disk_headroom,
)
from weather.reporting.source_gates.weak_input_family_disposition import weak_input_training_preflight
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
from weather.reporting.source_gates.source_redundancy import (
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
from weather.sources.marine_water_contrast import load_marine_water_contrast_features
from weather.artifacts import writable_artifact_path
from weather.calibration.blocked_validation import blocked_validation_audit
from weather.calibration.pooled_feature_source_state import (
    DYNAMIC_SOURCE_CATEGORICAL_COLUMNS,
    DYNAMIC_SOURCE_NUMERIC_COLUMNS,
    add_dynamic_source_state_features,
    default_dynamic_source_state_features,
    dynamic_source_state_features,
    feature_names_need_dynamic_source_state,
    latest_source_minute,
    source_age_minutes,
    source_items_from_status_rows,
    source_list_label,
    source_row_count,
    source_status_group_from_items,
    source_status_kind,
)
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
DEFAULT_FORECAST_RADIATION_BAND_REPORT = data_path() / "backtest" / "item187_forecast_radiation_band_model_report.md"
DEFAULT_FORECAST_RADIATION_BAND_ARTIFACT = writable_artifact_path("feature_model_hgb_f_pooled_forecast_radiation_v0_1.pkl")
DEFAULT_MARINE_CONTRAST_BAND_REPORT = data_path() / "backtest" / "item191_marine_contrast_band_model_report.md"
DEFAULT_MARINE_CONTRAST_BAND_ARTIFACT = writable_artifact_path("feature_model_hgb_f_pooled_marine_contrast_v0_1.pkl")
DEFAULT_TRAINING_OUTPUT_ESTIMATED_BYTES = 10_000_000
BAND_MERGE_PAYLOAD_KEY = "band_postprocess_merge_payload"

WIND_GROUPS = ["E-SE/onshore-ish", "S-SW", "W-NW", "N-NE", "SSE", "Other/variable"]
CLOUD_GROUPS = ["Precip", "Fog/haze", "Fair/clear", "Partly cloudy", "Mostly cloudy/overcast", "Other"]
FEATURE_SUBSET_ALL = "all"
FEATURE_SUBSET_FORECAST_PROFILE = "forecast_profile"
FEATURE_SUBSET_FORECAST_CLOUD_SOLAR_RADIATION = "forecast_cloud_solar_radiation"
FEATURE_SUBSET_MARINE_WATER_CONTRAST = "marine_water_contrast"
FEATURE_SUBSET_CHOICES = (
    FEATURE_SUBSET_ALL,
    FEATURE_SUBSET_FORECAST_PROFILE,
    FEATURE_SUBSET_FORECAST_CLOUD_SOLAR_RADIATION,
    FEATURE_SUBSET_MARINE_WATER_CONTRAST,
)
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
FORECAST_CLOUD_SOLAR_RADIATION_COLUMNS = {
    "forecast_remaining_solar_sum",
    "forecast_next_3h_solar_mean",
    "forecast_total_cloud_mean",
    "forecast_total_cloud_max",
    "forecast_low_cloud_mean",
    "forecast_low_cloud_max",
    "forecast_mid_cloud_mean",
    "forecast_high_cloud_mean",
    "forecast_cloud_trend_3h",
    "forecast_remaining_direct_radiation_sum",
    "forecast_remaining_diffuse_radiation_sum",
    "forecast_next_3h_direct_radiation_mean",
    "forecast_next_3h_diffuse_radiation_mean",
    "forecast_remaining_direct_radiation_share",
    "forecast_next_3h_direct_radiation_share",
}
FORECAST_CLOUD_SOLAR_RADIATION_CONTEXT_COLUMNS = {
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
MARINE_WATER_CONTRAST_COLUMNS = {
    "marine_station_count",
    "marine_latest_age_minutes",
    "marine_missing_sensor_count",
    "marine_water_temp_native",
    "marine_water_minus_forecast_high",
    "marine_wind_speed_kmh",
    "marine_onshore_flow",
    "marine_offshore_flow",
    "marine_onshore_water_minus_forecast_high",
    "marine_onshore_cooling_potential",
    "marine_breeze_risk",
    "marine_layer_suppression",
}
MARINE_WATER_CONTRAST_CONTEXT_COLUMNS = {
    "latitude",
    "longitude",
    "coastal",
    "climate_normal",
    "climate_std",
    "band_value",
    "band_value_hi",
    "band_width",
    "band_mid",
    "band_mid_anomaly",
}
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
    if feature_subset == FEATURE_SUBSET_FORECAST_CLOUD_SOLAR_RADIATION:
        return {
            "name": FEATURE_SUBSET_FORECAST_CLOUD_SOLAR_RADIATION,
            "schema_version": "pooled_feature_subset_v0.1",
            "description": (
                "Roadmap item 187 forecast radiation lane: forecast "
                "shortwave/direct/diffuse radiation and peak-window cloud "
                "features plus market/climate context and band geometry "
                "relative to forecast_high. Observed-temperature-path and "
                "live-reading dominance columns are excluded from the model "
                "matrix."
            ),
            "allowed_feature_families": [
                "forecast_cloud_solar_radiation",
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
                "forecast_profile_temperature",
                "forecast_gap",
                "forecast_ensemble_spread",
                "forecast_source_state_guardrail",
            ],
            "anchor_feature": "forecast_high",
            "postprocess_policy": (
                "Auxiliary radiation and cloud fields may only change "
                "confidence around forecast-relative band geometry; promotion "
                "still requires daily-first blocked replay and cutoff-regime "
                "guardrails."
            ),
        }
    if feature_subset == FEATURE_SUBSET_MARINE_WATER_CONTRAST:
        return {
            "name": FEATURE_SUBSET_MARINE_WATER_CONTRAST,
            "schema_version": "pooled_feature_subset_v0.1",
            "description": (
                "Roadmap item 191 marine lane: lake/sea water-temperature "
                "contrast, onshore-flow gating, and marine cooling-potential "
                "features plus market/climate and direct band geometry. Broad "
                "forecast-profile, observed-temperature-path, live-reading, "
                "CLOB, and dynamic source-state columns are excluded."
            ),
            "allowed_feature_families": [
                "marine_context",
                "market_climate_context",
                "market_band_geometry",
            ],
            "blocked_feature_families": [
                "observed_temp_path",
                "live_reading_path",
                "surface_weather",
                "forecast_profile_temperature",
                "forecast_cloud_solar_radiation",
                "forecast_gap",
                "forecast_ensemble_spread",
                "forecast_source_state_guardrail",
                "official_guidance",
                "clob_microstructure",
                "dynamic_source_state",
            ],
            "anchor_feature": "marine_water_minus_forecast_high",
            "postprocess_policy": (
                "Promotion requires a marine-contrast scoped settlement replay "
                "with positive onshore/breeze-slice lift and no aggregate "
                "regression."
            ),
        }
    raise ValueError(f"Unknown pooled feature subset: {feature_subset}")


def feature_names_for_subset(columns, feature_subset=FEATURE_SUBSET_ALL):
    columns = list(columns)
    feature_subset = feature_subset or FEATURE_SUBSET_ALL
    if feature_subset == FEATURE_SUBSET_ALL:
        return columns
    if feature_subset == FEATURE_SUBSET_FORECAST_CLOUD_SOLAR_RADIATION:
        selected = []
        allowed = FORECAST_CLOUD_SOLAR_RADIATION_COLUMNS | FORECAST_CLOUD_SOLAR_RADIATION_CONTEXT_COLUMNS
        for column in columns:
            if column in allowed:
                selected.append(column)
                continue
            if column.startswith("market_id_") or column.startswith("band_kind_"):
                selected.append(column)
        return selected
    if feature_subset == FEATURE_SUBSET_MARINE_WATER_CONTRAST:
        selected = []
        allowed = MARINE_WATER_CONTRAST_COLUMNS | MARINE_WATER_CONTRAST_CONTEXT_COLUMNS
        for column in columns:
            if column in allowed:
                selected.append(column)
                continue
            if column.startswith("market_id_") or column.startswith("band_kind_"):
                selected.append(column)
        return selected
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


def family_specs(unit="F"):
    if str(unit or "").lower() == "all":
        return all_specs()
    return [spec for spec in all_specs() if spec.display_unit == unit]


def _normalized_target_dates(values):
    return {
        value.isoformat() if hasattr(value, "isoformat") else str(value)
        for value in (values or ())
    }


def _target_date_is_excluded(local_date, excluded_target_dates):
    if not excluded_target_dates:
        return False
    value = local_date.isoformat() if hasattr(local_date, "isoformat") else str(local_date)
    return value in excluded_target_dates


def market_climate_stats(cache, excluded_target_dates=None):
    excluded_target_dates = _normalized_target_dates(excluded_target_dates)
    buckets = [
        row.get("bucket")
        for local_date, row in (cache.get("daily") or {}).items()
        if not _target_date_is_excluded(local_date, excluded_target_dates)
    ]
    buckets = [float(value) for value in buckets if value is not None]
    if not buckets:
        return {"climate_normal": None, "climate_std": None}
    mean = sum(buckets) / len(buckets)
    if len(buckets) < 2:
        std = 0.0
    else:
        std = math.sqrt(sum((value - mean) ** 2 for value in buckets) / (len(buckets) - 1))
    return {"climate_normal": mean, "climate_std": std}


def market_source_reliability(
    spec,
    include_historical_only=False,
    excluded_target_dates=None,
):
    """Static per-market source-quality priors for pooled training.

    These are learned from available daily-source overlaps versus WU, not from
    the same intraday record being scored. They give the pooled model a compact
    city/source trust context without using final redundant-source highs as
    same-day features.
    """
    try:
        import sys

        facade = sys.modules.get("weather.calibration.pooled_feature_model")
        source_daily_indexer = getattr(facade, "source_daily_indexes", source_daily_indexes)
        indexes = source_daily_indexer(spec)
    except Exception:  # noqa: BLE001 - pooled training should survive missing optional stores
        indexes = {}
    excluded_target_dates = _normalized_target_dates(excluded_target_dates)
    if excluded_target_dates:
        indexes = {
            source: {
                local_date: row
                for local_date, row in (rows or {}).items()
                if not _target_date_is_excluded(local_date, excluded_target_dates)
            }
            for source, rows in indexes.items()
        }
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
    excluded_target_dates=None,
    included_target_dates=None,
    prior_as_of_exclusive=None,
    _available_target_dates=None,
):
    excluded_target_dates = _normalized_target_dates(excluded_target_dates)
    included_target_dates = _normalized_target_dates(included_target_dates)
    prior_cutoff = (
        date.fromisoformat(str(prior_as_of_exclusive))
        if prior_as_of_exclusive
        else None
    )
    model = TorontoHighTempModel(market_id=spec.id)
    # Serving keeps its prior-year +/- seasonal-window cache. Production PIT
    # extraction names its exact prelocked universe here so current-year days
    # are addressable for coverage checks; locked rows and post-cutoff priors
    # remain excluded below.
    cache = model.historical_target_cache(
        coverage_target_dates=excluded_target_dates | included_target_dates
    )
    daily = cache.get("daily") or {}
    by_date = cache.get("by_date") or {}
    dates = sorted(daily.keys())
    if max_days and max_days > 0:
        dates = dates[-int(max_days):]
    if _available_target_dates is not None:
        _available_target_dates.update(
            local_date.isoformat()
            for local_date in dates
            if by_date.get(local_date)
        )
    prior_excluded_dates = set(excluded_target_dates)
    if included_target_dates and prior_cutoff is None:
        prior_excluded_dates.update(
            local_date.isoformat()
            for local_date in dates
            if local_date.isoformat() not in included_target_dates
        )
    if prior_cutoff is not None:
        prior_excluded_dates.update(
            local_date.isoformat()
            for local_date in daily
            if local_date >= prior_cutoff
        )
    dates = [
        local_date
        for local_date in dates
        if (
            not included_target_dates
            or local_date.isoformat() in included_target_dates
        )
        and not _target_date_is_excluded(local_date, excluded_target_dates)
    ]
    forecast_index = load_forecast_daily(daily_path_for(spec))
    forecast_profiles = load_forecast_profiles(long_path_for(spec))
    marine_water_contrast_index = load_marine_water_contrast_features(spec=spec)
    reanalysis_synoptic_index = load_reanalysis_synoptic_features(spec=spec)
    climate = market_climate_stats(
        cache,
        excluded_target_dates=prior_excluded_dates,
    )
    source_reliability = market_source_reliability(
        spec,
        excluded_target_dates=prior_excluded_dates,
    )

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
                marine_context_features=marine_water_contrast_index.get((local_date.isoformat(), int(hour))),
                reanalysis_synoptic_features=reanalysis_synoptic_index.get(local_date.isoformat()),
                wind_group_fn=model.wind_group,
                cloud_group_fn=model.cloud_group,
                microclimate_feature_fn=model.microclimate_features,
                wall_minute=int(hour) * 60 + offset,
                unit=spec.display_unit,
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
    excluded_target_dates=None,
    included_target_dates=None,
    prior_as_of_exclusive=None,
):
    specs = family_specs(unit)
    records = []
    counts = {}
    available_target_dates = set()
    excluded_target_dates = _normalized_target_dates(excluded_target_dates)
    included_target_dates = _normalized_target_dates(included_target_dates)
    for spec in specs:
        market_records = build_market_records(
            spec,
            cutoff_hours=cutoff_hours,
            max_days=max_days_per_market,
            reanalysis_promotion_lane=reanalysis_promotion_lane,
            excluded_target_dates=excluded_target_dates,
            included_target_dates=included_target_dates,
            prior_as_of_exclusive=prior_as_of_exclusive,
            _available_target_dates=available_target_dates,
        )
        counts[spec.id] = len(market_records)
        records.extend(market_records)
    missing_excluded_dates = sorted(
        excluded_target_dates - available_target_dates
    )
    if missing_excluded_dates:
        raise ValueError(
            "pooled training corpus does not cover every locked evaluation date: "
            + ", ".join(missing_excluded_dates)
        )
    missing_included_dates = sorted(
        included_target_dates - available_target_dates
    )
    if missing_included_dates:
        raise ValueError(
            "pooled training corpus does not cover every preselected fleet date: "
            + ", ".join(missing_included_dates)
        )
    return records, counts


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


from weather.model.variant_prediction_runtime import (  # noqa: E402
    band_feature_frame,
    band_outcome,
    band_prediction_record,
    canonical_density_record,
    canonical_density_records,
    feature_frame,
    finite_float,
    hard_floor_probability,
    late_lockin_strength_from_features,
    late_lockin_target,
    native_delta_to_f,
    native_value_to_f,
    record_unit,
    support_floor_cap,
    temperature_scale_probability,
)

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]
