"""Shadow replay for the pooled F-family feature-model candidate.

This is the cutover guard for Roadmap item 33. It replays the pinned promotion
corpus with the current serving model, then scores the separate pooled-F
artifact against the same settled rows as a shadow candidate. Live serving is
not changed by this module.
"""
import argparse
import csv
import hashlib
import io
import json
import math
import os
import pickle
import stat
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from weather.paths import data_path

import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer

from weather.scoring.metrics import (
    expected_calibration_error,
    group_sort_key,
    score_rows,
    winner_band_catchup,
)
from weather.reporting.formatting import (
    fmt_num,
    fmt_pct,
    fmt_signed,
    markdown_table,
)
from weather.model.feature_store import (
    FEATURE_COLUMNS,
    FEATURE_DIAGNOSTIC_COLUMNS,
    FEATURE_SCHEMA_VERSION,
    row_temp_native,
)
from weather.sources.reanalysis_synoptic import (
    REANALYSIS_SYNOPTIC_FEATURE_COLUMNS,
    load_reanalysis_synoptic_features,
)
from weather.sources.marine_context import MARINE_CONTEXT_FEATURE_COLUMNS
from weather.sources.marine_water_contrast import load_marine_water_contrast_features
from weather.model.variant_prediction_runtime import (
    apply_continuous_density_calibration,
    apply_density_band_postprocessing,
    density_projection_index,
    density_projection_probability,
    pooled_band_regime_route,
)
from weather.reporting.location_analysis.location_trust import score_all_markets
from weather.market.market_microstructure_features import (
    CLOB_MODEL_FEATURE_COLUMNS,
    feature_index_for_folder,
    snapshot_band_key,
)
from weather.market.market_registry import REGISTRY, spec_for_slug
from weather.model.continuous_density import (
    band_probability_from_distribution as density_band_probability_from_distribution,
)
from weather.model.residual_distribution_v1 import (
    PREDICTION_MODE as RESIDUAL_DISTRIBUTION_V1_MODE,
    predict_residual_distribution_v1,
    residual_band_key,
)
from weather.model.current_blend import (
    blend_with_current,
    current_blend_context_rule_matches,
    current_blend_context_value,
    resolve_current_blend_alpha as current_blend_alpha,
    source_freshness_state_from_diagnostics,
)
from weather.calibration.residual_distribution_corpus import (
    source_diagnostics_from_replay,
)
from weather.calibration.pooled_feature_model import (
    DEFAULT_BAND_ARTIFACT,
    FEATURE_SUBSET_FORECAST_PROFILE,
    MARINE_WATER_CONTRAST_COLUMNS,
    SOURCE_RELIABILITY_COLUMNS,
    add_dynamic_source_state_features,
    add_city_features,
    apply_band_postprocessing,
    band_prediction_record,
    apply_reanalysis_promotion_lane_to_record,
    market_climate_stats,
    market_source_reliability,
    predict_band_rows_for_bundle,
    predict_density_rows_for_bundle,
    predict_rows,
)
from weather.reporting.promotion.promotion_corpus import (
    DEFAULT_OUT as DEFAULT_CORPUS,
    entry_for_folder,
    folders_from_manifest,
    load_manifest,
    summarize_entries,
    verify_entry_inputs,
)
from weather.reporting.data_quality.feature_quality_quarantine import (
    audit_folder_feature_quality_from_rows,
)
from weather.backtesting.settlement_io import (
    band_value_hi,
    ledger_label_matches_folder,
    resolve_outcome,
)
from weather.backtesting.settlement_ledger import ledger_label_for_slug
from weather.backtesting.replay import (
    index_records_by_snapshot,
    is_reconstructed,
    load_replay_records,
    parse_built_at,
    record_target_date,
    source_freshness_group,
)
from weather.backtesting import replay_cache
from weather.backtesting.replay_backtest import (
    FIDELITY_FAITHFUL_L1,
    comparison as current_replay_comparison,
    daily_first_comparison as current_replay_daily_first_comparison,
    fidelity_summary as current_replay_fidelity_summary,
    grouped_comparison as current_replay_grouped_comparison,
    run_replay_backtest,
    write_report as write_replay_backtest_report,
)
from weather.backtesting.tape_scoring import last_pre_close_rows
from weather.backtesting.settled_days import DEFAULT_SNAPSHOTS_ROOT, folder_market_id
from weather.model.toronto_model import TorontoHighTempModel
from weather.artifacts import sha256_file, writable_artifact_path
from weather.operations.long_job_guard import (
    DEFAULT_LOCK_PATH as DEFAULT_LONG_JOB_LOCK_PATH,
    DEFAULT_STATE_PATH as DEFAULT_LONG_JOB_STATE_PATH,
    long_job_guard,
)
from weather.reporting.candidate_lifecycle.variant_registry import (
    DEFAULT_REGISTRY_PATH as DEFAULT_VARIANT_REGISTRY_PATH,
    load_registry as load_variant_registry,
    variant_contract_for_artifact,
)
from weather.reporting.data_quality.artifact_disk_budget import ensure_artifact_disk_headroom

from weather.calibration.pooled_candidate_scoring import (
    CONSERVATIVE_BRIDGE_ALPHA_BY_MARKET,
    CONSERVATIVE_BRIDGE_SCHEMA_VERSION,
    DEFAULT_BRIDGE_VARIANT_OUT,
    DEFAULT_CANDIDATE_VARIANT_OUT,
    DEFAULT_MICROSTRUCTURE_VARIANT_OUT,
    DEFAULT_SOURCE_STATE_ABLATION_VARIANT_OUT,
    DEFAULT_VARIANT_EXPORT_MIN_FREE_BYTES,
    EXACT_WINNER_TARGET_MARKETS,
    MICROSTRUCTURE_GATE_MAX_DELTA_VS_CANDIDATE,
    MICROSTRUCTURE_GATE_MAX_DELTA_VS_MARKET,
    MICROSTRUCTURE_GATE_MAX_ECE,
    MICROSTRUCTURE_GATE_MAX_LOGLOSS_DELTA_VS_CANDIDATE,
    MICROSTRUCTURE_GATE_MAX_OVERCONFIDENT_ERROR_RATE,
    MICROSTRUCTURE_GATE_MIN_ROWS,
    MICROSTRUCTURE_GATE_SCHEMA_VERSION,
    MICROSTRUCTURE_SCHEMA_VERSION,
    MICROSTRUCTURE_SHADOW_VARIANT_COLUMNS,
    MICROSTRUCTURE_TARGET_TAXONOMIES,
    _bin_type,
    _clamp_probability,
    _cutoff_hour,
    _distance_bucket,
    _micro_gate_reason,
    _score_probability_field,
    _settled_shadow_source_rows,
    _shadow_band_key,
    _shadow_variant_row,
    _valid_probability,
    apply_conservative_bridge,
    apply_microstructure_gate,
    artifact_hash_for_path,
    band_probability_from_distribution,
    blocked_candidate_validation_gate,
    bridge_alpha_for_market,
    bridge_comparison,
    bridge_policy_payload,
    build_microstructure_gate,
    calibration_diagnostics,
    candidate_comparison,
    candidate_shadow_variant_rows,
    conservative_bridge_report,
    conservative_bridge_shadow_variant_rows,
    daily_first_candidate_comparison,
    exact_winner_candidate_diagnostics,
    exact_winner_probability_summary,
    exact_winner_scope_comparison,
    family_unit_matches,
    grouped_bridge_comparison,
    grouped_candidate_comparison,
    grouped_microstructure_comparison,
    load_artifact,
    microstructure_comparison,
    microstructure_shadow_variant_rows,
    payload_hash,
    probability_view,
    source_state_ablation_report,
    write_candidate_shadow_variants,
    write_conservative_bridge_shadow_variants,
    write_microstructure_shadow_variants,
)

from weather.calibration.pooled_candidate_replay_diagnostics import (
    DEFAULT_CASEBOOK,
    MICROSTRUCTURE_CATEGORICAL_FEATURES,
    MICROSTRUCTURE_NUMERIC_FEATURES,
    POOLED_REPLAY_PREDICTION_FUNCTION,
    _manifest_summary,
    _micro_float,
    _micro_group_key,
    _per_market,
    annotate_casebook_rows,
    candidate_variant_defaults,
    cutoff_hour_bucket,
    cutover_decision,
    eligible_microstructure_rows,
    final_microstructure_artifact,
    forecast_profile_guardrails,
    load_casebook_index,
    market_verdict,
    microstructure_feature_frame,
    microstructure_feature_record,
    microstructure_shadow_report,
    out_of_fold_microstructure_predictions,
    overall_verdict,
    predict_microstructure_model,
    probability_logit,
    replay_gate_status,
    row_band_key_text,
    sidecar_eligibility_summary_from_audit,
    train_microstructure_model,
    write_microstructure_artifact,
)
DEFAULT_OUT = data_path() / "backtest" / "pooled_candidate_replay_report.md"
DEFAULT_JSON_OUT = data_path() / "backtest" / "pooled_candidate_replay.json"
DEFAULT_REPLAY_REPORT = data_path() / "backtest" / "pooled_candidate_current_replay_report.md"
DEFAULT_DATA_LAYER_AUDIT = data_path() / "backtest" / "data_layer_audit.json"
DEFAULT_MICROSTRUCTURE_ARTIFACT = writable_artifact_path("feature_model_hgb_f_pooled_clob_overlay_v0_2.pkl")

BOUNDED_CANDIDATE_REPLAY_SCHEMA_VERSION = "pooled_candidate_replay_day_rows_v0.1"
_SETTLEMENT_LABEL_FIELDS = frozenset({
    "label",
    "outcome",
    "settled_label",
    "is_winner",
    "settlement_bucket",
    "settlement_distance",
    "settlement_distance_bucket",
})


class BoundedCandidateReplayError(RuntimeError):
    """A fail-closed identity, lineage, or resource-bound violation."""


def cutoff_regime(hour):
    try:
        hour = int(float(hour))
    except (TypeError, ValueError):
        return "unknown"
    if hour <= 8:
        return "early"
    if hour <= 14:
        return "midday"
    return "late"


def forecast_source_count_bucket(value):
    try:
        value = int(float(value))
    except (TypeError, ValueError):
        return "unknown"
    if value <= 1:
        return "low_count"
    if value == 2:
        return "two_sources"
    return "three_plus_sources"


def forecast_disagreement_bucket(value):
    try:
        value = abs(float(value))
    except (TypeError, ValueError):
        return "unknown"
    if value < 1.0:
        return "low_disagreement"
    if value < 2.5:
        return "moderate_disagreement"
    return "high_disagreement"


def forecast_bucket_pressure(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "unknown"
    if value <= -1.0:
        return "cool_side"
    if value >= 1.0:
        return "warm_side"
    return "near_forecast"


def current_max_boundary_slice(feature_row):
    """Replay slice for support-only current max near a printed WU boundary."""

    feature_row = feature_row or {}
    disposition = str(feature_row.get("current_max_disposition") or "").strip().lower()
    state = str(feature_row.get("current_max_state") or "").strip().lower()
    try:
        gap = float(feature_row.get("current_max_gap_to_history"))
    except (TypeError, ValueError):
        gap = None
    if not disposition:
        return "unknown"
    if disposition == "support_only":
        if gap is not None and 0.0 < gap <= 1.5:
            return "support_only_one_bucket_up"
        if gap is not None and gap > 1.5:
            return "support_only_multi_bucket_up"
        return "support_only"
    if disposition in {"quarantined", "null_before_reset", "missing"}:
        return f"stale_{disposition}"
    if disposition == "validated":
        return "confirmed"
    return state or disposition


MARINE_REPLAY_FEATURES = (
    "marine_station_count",
    "marine_latest_age_minutes",
    "marine_missing_sensor_count",
    "marine_water_temp_native",
    "marine_water_minus_forecast_high",
    "marine_onshore_flow",
    "marine_offshore_flow",
    "marine_onshore_water_minus_forecast_high",
    "marine_onshore_cooling_potential",
    "marine_breeze_risk",
    "marine_layer_suppression",
)


def _has_replay_float(value):
    return _replay_float(value) is not None


def apply_marine_water_contrast_sidecar(feature_row, sidecar_features):
    """Fill missing replay marine fields from the cutoff-aware sidecar."""

    if not sidecar_features:
        return {
            "applied": False,
            "reason": "missing_sidecar_row",
            "filled_columns": [],
            "observed_columns": [],
        }
    filled_columns = []
    observed_columns = []
    for column in MARINE_CONTEXT_FEATURE_COLUMNS:
        value = sidecar_features.get(column)
        if not _has_replay_float(value):
            continue
        observed_columns.append(column)
        if _has_replay_float(feature_row.get(column)):
            continue
        feature_row[column] = value
        filled_columns.append(column)
    return {
        "applied": bool(filled_columns),
        "reason": "applied" if filled_columns else "no_missing_replay_columns_filled",
        "filled_columns": filled_columns,
        "observed_columns": observed_columns,
    }


def _replay_float(value):
    if value in (None, ""):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def marine_breeze_slice(feature_row):
    """Replay slice for item 191 onshore lake/sea-breeze settlement scoring."""

    feature_row = feature_row or {}
    onshore = _replay_float(feature_row.get("marine_onshore_flow"))
    breeze = _replay_float(feature_row.get("marine_breeze_risk"))
    suppression = _replay_float(feature_row.get("marine_layer_suppression"))
    cooling = _replay_float(feature_row.get("marine_onshore_cooling_potential"))
    water_temp = _replay_float(feature_row.get("marine_water_temp_native"))
    contrast = _replay_float(feature_row.get("marine_water_minus_forecast_high"))
    has_marine = any(value is not None for value in (water_temp, contrast, onshore, breeze, suppression, cooling))
    if not has_marine:
        return "missing_marine_context"
    if onshore is not None and onshore >= 0.5:
        if (breeze is not None and breeze >= 0.5) or (suppression is not None and suppression >= 0.5):
            return "onshore_breeze"
        if cooling is not None and cooling > 0.0:
            return "onshore_breeze"
        return "onshore"
    if contrast is not None:
        return "water_contrast_no_onshore"
    return "marine_observed_no_onshore"


def attach_forecast_profile_slice_context(copy, feature_row=None, band_row=None):
    feature_row = feature_row or {}
    if band_row is None:
        band_row = {}
    source_count = feature_row.get("forecast_source_count")
    disagreement = feature_row.get("forecast_disagreement")
    forecast_gap = feature_row.get("forecast_gap")
    pressure = band_row.get("band_mid_minus_forecast")
    copy["forecast_source_count"] = source_count
    copy["forecast_disagreement"] = disagreement
    copy["forecast_gap"] = forecast_gap
    copy["forecast_source_count_bucket"] = forecast_source_count_bucket(source_count)
    copy["forecast_disagreement_bucket"] = forecast_disagreement_bucket(disagreement)
    copy["forecast_bucket_pressure"] = forecast_bucket_pressure(pressure)
    for column in (
        "current_max_state",
        "current_max_disposition",
        "current_max_quarantine_reason",
        "current_max_gap_to_history",
    ):
        value = feature_row.get(column)
        copy[column] = value
        band_row[column] = value
    boundary_slice = current_max_boundary_slice(feature_row)
    copy["current_max_boundary_slice"] = boundary_slice
    band_row["current_max_boundary_slice"] = boundary_slice


def attach_marine_contrast_slice_context(copy, feature_row=None, band_row=None):
    feature_row = feature_row or {}
    if band_row is None:
        band_row = {}
    slice_name = marine_breeze_slice(feature_row)
    copy["marine_breeze_slice"] = slice_name
    band_row["marine_breeze_slice"] = slice_name
    for column in MARINE_REPLAY_FEATURES:
        value = feature_row.get(column)
        copy[column] = value
        band_row[column] = value

def _model_for_market(models, market_id):
    if market_id not in models:
        models[market_id] = TorontoHighTempModel(market_id=market_id)
    return models[market_id]


def _verified_production_static_context(artifact):
    training = (artifact or {}).get("point_in_time_training")
    if not isinstance(training, dict):
        return None
    context = (artifact or {}).get("production_static_context")
    if not isinstance(context, dict):
        raise ValueError("production artifact is missing its static feature context")
    unhashed = dict(context)
    actual = str(unhashed.pop("context_sha256", "") or "")
    expected = hashlib.sha256(
        json.dumps(
            unhashed,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    lock = training.get("preselection_lock") or {}
    if (
        actual != expected
        or context.get("preselection_hash") != lock.get("preselection_hash")
        or context.get("window_lock_id") != lock.get("window_lock_id")
        or tuple(context.get("context_fields") or ())
        != ("climate_normal", "climate_std", *SOURCE_RELIABILITY_COLUMNS)
        or context.get("external_sidecar_policy")
        != {
            "reanalysis_synoptic": "disabled_unpinned",
            "marine_water_contrast": "disabled_unpinned",
        }
        or not isinstance(context.get("markets"), dict)
    ):
        raise ValueError("production artifact static feature context is invalid")
    return context


def _climate_for_market(climates, model, market_id, production_context=None):
    if production_context is not None:
        values = (production_context.get("markets") or {}).get(market_id)
        if not isinstance(values, dict):
            raise ValueError(
                f"production static feature context has no market {market_id}"
            )
        return {
            "climate_normal": values.get("climate_normal"),
            "climate_std": values.get("climate_std"),
        }
    if market_id not in climates:
        climates[market_id] = market_climate_stats(model.historical_target_cache())
    return climates[market_id]


def _source_reliability_for_market(
    source_reliability, spec, production_context=None
):
    if production_context is not None:
        values = (production_context.get("markets") or {}).get(spec.id)
        if not isinstance(values, dict):
            raise ValueError(
                f"production static feature context has no market {spec.id}"
            )
        return {
            field: values.get(field) for field in SOURCE_RELIABILITY_COLUMNS
        }
    if spec.id not in source_reliability:
        source_reliability[spec.id] = market_source_reliability(spec)
    return source_reliability[spec.id]


def _artifact_feature_names(artifact):
    names = set()
    for bundle in ((artifact or {}).get("models") or {}).values():
        if isinstance(bundle, dict):
            names.update(str(name) for name in bundle.get("feature_names") or [])
    return names


def _artifact_reanalysis_lane(artifact):
    return (
        (artifact or {}).get("reanalysis_promotion_lane")
        or ((artifact or {}).get("source_family_lanes") or {}).get("reanalysis_synoptic")
    )


def _artifact_needs_reanalysis(artifact):
    lane = _artifact_reanalysis_lane(artifact)
    if lane:
        return True
    return any(name.startswith("reanalysis_") for name in _artifact_feature_names(artifact))


def _artifact_needs_marine_water_contrast(artifact):
    feature_names = _artifact_feature_names(artifact)
    return any(name in feature_names for name in MARINE_CONTEXT_FEATURE_COLUMNS)


def _reanalysis_index_for_market(indexes, spec):
    if spec.id not in indexes:
        indexes[spec.id] = load_reanalysis_synoptic_features(spec=spec)
    return indexes[spec.id]


def _marine_water_contrast_index_for_market(indexes, spec):
    if spec.id not in indexes:
        indexes[spec.id] = load_marine_water_contrast_features(spec=spec)
    return indexes[spec.id]


def _record_feature_row(
    model,
    spec,
    climate,
    record,
    source_reliability=None,
    reanalysis_synoptic_features=None,
    reanalysis_promotion_lane=None,
):
    now = parse_built_at(record)
    if now is None:
        raise ValueError("replay record is missing a parseable built_at/captured_at_local timestamp")
    target_date = record_target_date(record)
    if target_date is not None:
        model.set_target_date(target_date)
    sources = record.get("sources") or {}
    history = model.source_data(sources, "wu_history")
    cutoff_hour = model.effective_intraday_cutoff_hour(now, history.get("rows") or [])
    features = model.extract_live_features(sources, cutoff_hour, now=now)
    current = model.source_data(sources, "wu_current")
    metar = model.source_data(sources, "metar")
    support_values = [
        features.get("high_so_far"),
        row_temp_native(current),
        row_temp_native(metar),
    ]
    observed_support = model.max_value(*support_values)
    row = {column: features.get(column) for column in FEATURE_COLUMNS}
    for column in FEATURE_DIAGNOSTIC_COLUMNS:
        row[column] = features.get(column)
    for column in REANALYSIS_SYNOPTIC_FEATURE_COLUMNS:
        if reanalysis_synoptic_features and column in reanalysis_synoptic_features:
            row[column] = reanalysis_synoptic_features.get(column)
    row["feature_schema_version"] = FEATURE_SCHEMA_VERSION
    row["cutoff_hour"] = int(cutoff_hour)
    row["target_date"] = target_date.isoformat() if target_date else record.get("target_date")
    row["observed_support_bucket"] = model.round_half_up(observed_support)
    add_city_features(row, spec, climate, source_reliability=source_reliability)
    apply_reanalysis_promotion_lane_to_record(row, reanalysis_promotion_lane)
    add_dynamic_source_state_features(row, sources=sources, captured_at=now)
    return row


def build_candidate_features(manifest, snapshots_root, family_unit, artifact=None):
    """Return (market_id, snapshot_id) -> feature row for candidate scoring."""
    models = {}
    climates = {}
    source_reliability = {}
    reanalysis_indexes = {}
    marine_water_contrast_indexes = {}
    production_context = _verified_production_static_context(artifact)
    reanalysis_promotion_lane = _artifact_reanalysis_lane(artifact)
    needs_reanalysis = production_context is None and _artifact_needs_reanalysis(artifact)
    needs_marine_water_contrast = (
        production_context is None
        and _artifact_needs_marine_water_contrast(artifact)
    )
    diagnostics = {
        "family_unit": family_unit,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "candidate_snapshots": 0,
        "predicted_snapshots": 0,
        "excluded_non_family_snapshots": 0,
        "missing_replay_records": 0,
        "reconstructed_excluded": 0,
        "missing_hour_models": 0,
        "feature_errors": [],
        "hour_counts": {},
        "reanalysis_sidecar_loaded_markets": [],
        "reanalysis_promotion_lane": reanalysis_promotion_lane or {},
        "marine_water_contrast_sidecar_loaded_markets": [],
        "marine_water_contrast_sidecar_rows_applied": 0,
        "marine_water_contrast_sidecar_rows_missing": 0,
        "marine_water_contrast_sidecar_rows_without_observed_features": 0,
        "marine_water_contrast_sidecar_filled_columns": {},
        "production_static_context_sha256": (
            production_context.get("context_sha256")
            if production_context is not None
            else None
        ),
    }
    include_reconstructed = bool(manifest.get("include_reconstructed"))
    features = {}

    for folder in folders_from_manifest(manifest, snapshots_root):
        market_id = folder_market_id(folder)
        spec = REGISTRY.get(market_id)
        entry = entry_for_folder(manifest, folder)
        pinned_ids = [str(item) for item in (entry or {}).get("snapshot_ids") or []]
        if not family_unit_matches(spec, family_unit):
            diagnostics["excluded_non_family_snapshots"] += len(pinned_ids)
            continue

        model = _model_for_market(models, market_id)
        climate = _climate_for_market(
            climates, model, market_id, production_context
        )
        reliability = _source_reliability_for_market(
            source_reliability, spec, production_context
        )
        records = index_records_by_snapshot(load_replay_records(folder))
        for snapshot_id in pinned_ids:
            record = records.get(snapshot_id)
            if not record:
                diagnostics["missing_replay_records"] += 1
                continue
            if is_reconstructed(record) and not include_reconstructed:
                diagnostics["reconstructed_excluded"] += 1
                continue
            diagnostics["candidate_snapshots"] += 1
            try:
                reanalysis_features = None
                target_date = record_target_date(record)
                if needs_reanalysis and target_date is not None:
                    reanalysis_features = _reanalysis_index_for_market(
                        reanalysis_indexes,
                        spec,
                    ).get(target_date.isoformat())
                feature_row = _record_feature_row(
                    model,
                    spec,
                    climate,
                    record,
                    source_reliability=reliability,
                    reanalysis_synoptic_features=reanalysis_features,
                    reanalysis_promotion_lane=reanalysis_promotion_lane,
                )
                if production_context is not None:
                    for column in {
                        *REANALYSIS_SYNOPTIC_FEATURE_COLUMNS,
                        *MARINE_WATER_CONTRAST_COLUMNS,
                    }:
                        feature_row[column] = None
                if needs_marine_water_contrast and target_date is not None:
                    sidecar_features = _marine_water_contrast_index_for_market(
                        marine_water_contrast_indexes,
                        spec,
                    ).get((target_date.isoformat(), int(feature_row["cutoff_hour"])))
                    fill_result = apply_marine_water_contrast_sidecar(
                        feature_row,
                        sidecar_features,
                    )
                    if fill_result["applied"]:
                        diagnostics["marine_water_contrast_sidecar_rows_applied"] += 1
                        for column in fill_result["filled_columns"]:
                            counts = diagnostics["marine_water_contrast_sidecar_filled_columns"]
                            counts[column] = counts.get(column, 0) + 1
                    elif fill_result["reason"] == "missing_sidecar_row":
                        diagnostics["marine_water_contrast_sidecar_rows_missing"] += 1
                    elif not fill_result["observed_columns"]:
                        diagnostics["marine_water_contrast_sidecar_rows_without_observed_features"] += 1
            except Exception as exc:  # noqa: BLE001 - diagnostics should survive bad rows
                if len(diagnostics["feature_errors"]) < 20:
                    diagnostics["feature_errors"].append({
                        "market_id": market_id,
                        "snapshot_id": snapshot_id,
                        "error": str(exc),
                })
                continue
            diagnostics["predicted_snapshots"] += 1
            diagnostics["hour_counts"][str(feature_row["cutoff_hour"])] = (
                diagnostics["hour_counts"].get(str(feature_row["cutoff_hour"]), 0) + 1
            )
            features[(market_id, snapshot_id)] = feature_row
    diagnostics["reanalysis_sidecar_loaded_markets"] = sorted(reanalysis_indexes)
    diagnostics["marine_water_contrast_sidecar_loaded_markets"] = sorted(marine_water_contrast_indexes)
    return features, diagnostics


def build_clob_feature_index(manifest, snapshots_root, family_unit, max_age_seconds=180):
    """Return band-level CLOB features keyed by replay row identity."""
    output = {}
    diagnostics = {
        "clob_feature_folders": 0,
        "clob_feature_rows": 0,
        "clob_feature_available_rows": 0,
        "clob_feature_missing_folders": 0,
    }
    for folder in folders_from_manifest(manifest, snapshots_root):
        market_id = folder_market_id(folder)
        spec = REGISTRY.get(market_id)
        if not family_unit_matches(spec, family_unit):
            continue
        if not (Path(folder) / "order_books_summary.csv").exists():
            diagnostics["clob_feature_missing_folders"] += 1
            continue
        folder_index = feature_index_for_folder(
            folder,
            max_age_seconds=max_age_seconds,
            market_id=market_id,
        )
        diagnostics["clob_feature_folders"] += 1
        diagnostics["clob_feature_rows"] += len(folder_index)
        diagnostics["clob_feature_available_rows"] += sum(
            1 for row in folder_index.values()
            if row.get("clob_feature_available")
        )
        output.update(folder_index)
    return output, diagnostics


def build_source_freshness_index(manifest, snapshots_root, family_unit):
    """Return (market_id, snapshot_id) -> compact source freshness group."""
    output = {}
    counts = Counter()
    diagnostics = {
        "source_freshness_snapshots": 0,
        "source_freshness_missing_records": 0,
        "source_freshness_states": {},
    }
    include_reconstructed = bool(manifest.get("include_reconstructed"))
    for folder in folders_from_manifest(manifest, snapshots_root):
        market_id = folder_market_id(folder)
        spec = REGISTRY.get(market_id)
        if not family_unit_matches(spec, family_unit):
            continue
        entry = entry_for_folder(manifest, folder)
        records = index_records_by_snapshot(load_replay_records(folder))
        pinned_ids = [str(item) for item in (entry or {}).get("snapshot_ids") or records.keys()]
        for snapshot_id in pinned_ids:
            record = records.get(str(snapshot_id))
            if not record:
                diagnostics["source_freshness_missing_records"] += 1
                continue
            if is_reconstructed(record) and not include_reconstructed:
                continue
            # Use the same diagnostic collapse as live serving.  In particular,
            # an absent/empty source envelope is explicit missingness, never a
            # distinct replay-only health state.
            group = source_freshness_state_from_diagnostics(record.get("sources"))
            output[(market_id, str(snapshot_id))] = group
            counts[group] += 1
    diagnostics["source_freshness_snapshots"] = len(output)
    diagnostics["source_freshness_states"] = dict(sorted(counts.items()))
    return output, diagnostics


def _captured_residual_source_diagnostics(record):
    """Return captured diagnostics without inventing a healthy source state.

    ResidualDistributionV1 requires the replay input to carry either a
    ``source_diagnostics``/``source_status`` field or captured ``sources``
    envelopes with explicit ``status``/``ok``/``stale`` evidence.  The source
    envelopes are canonicalized by the same helper as the residual corpus,
    relative to the captured timestamp.  A mapping keyed by source is accepted
    only as a lossless representation of the same captured status rows.
    """

    for field in ("source_diagnostics", "source_status"):
        value = (record or {}).get(field)
        if isinstance(value, (list, tuple)):
            rows = [dict(row) for row in value if isinstance(row, dict)]
            return rows if rows else None
        if isinstance(value, dict):
            rows = []
            for source, raw in value.items():
                if not isinstance(raw, dict):
                    continue
                row = dict(raw)
                row.setdefault("source", source)
                rows.append(row)
            return rows if rows else None
    sources = (record or {}).get("sources")
    if isinstance(sources, dict) and sources:
        has_explicit_status = any(
            isinstance(item, dict)
            and any(field in item for field in ("status", "ok", "stale"))
            for item in sources.values()
        )
        captured_at = parse_built_at(record)
        if has_explicit_status and captured_at is not None:
            rows = source_diagnostics_from_replay(sources, captured_at=captured_at)
            return rows if rows else None
    return None


def build_residual_source_diagnostics_index(manifest, snapshots_root, family_unit):
    """Index captured point-in-time source diagnostics for residual replay."""

    output = {}
    diagnostics = {
        "residual_source_diagnostics_snapshots": 0,
        "residual_source_diagnostics_missing_snapshots": 0,
        "residual_source_diagnostics_expected_fields": [
            "source_diagnostics",
            "source_status",
            "sources.*.(status|ok|stale)",
        ],
    }
    include_reconstructed = bool(manifest.get("include_reconstructed"))
    for folder in folders_from_manifest(manifest, snapshots_root):
        market_id = folder_market_id(folder)
        spec = REGISTRY.get(market_id)
        if not family_unit_matches(spec, family_unit):
            continue
        entry = entry_for_folder(manifest, folder)
        records = index_records_by_snapshot(load_replay_records(folder))
        pinned_ids = [str(item) for item in (entry or {}).get("snapshot_ids") or records.keys()]
        for snapshot_id in pinned_ids:
            record = records.get(str(snapshot_id))
            if not record or (is_reconstructed(record) and not include_reconstructed):
                continue
            captured = _captured_residual_source_diagnostics(record)
            if captured is None:
                diagnostics["residual_source_diagnostics_missing_snapshots"] += 1
                continue
            output[(market_id, str(snapshot_id))] = captured
    diagnostics["residual_source_diagnostics_snapshots"] = len(output)
    return output, diagnostics


def _residual_replay_band_row(row):
    kind, value, value_hi = snapshot_band_key(row)
    return {
        "bin_kind": kind,
        "bin_value_c": value,
        "bin_value_hi_c": value_hi,
        "range_label": row.get("range_label"),
    }


def residual_distribution_v1_replay_payload(
    *,
    artifact,
    feature_vector,
    source_diagnostics,
    market_id,
    unit,
    band_rows,
):
    """Thin replay adapter over the exact pure function used by live capture."""

    return predict_residual_distribution_v1(
        artifact=artifact,
        feature_vector=feature_vector,
        source_diagnostics=source_diagnostics,
        market_id=market_id,
        unit=unit,
        band_rows=band_rows,
    )


def attach_residual_distribution_v1_probabilities(
    replay_results,
    feature_rows,
    source_diagnostics,
    artifact,
    family_unit="all",
):
    """Score complete replay partitions without any incumbent postprocessing.

    A skipped/failed snapshot remains in coverage with ``candidate_p=None`` and
    its exact named reason.  No serving probability is substituted.
    """

    rows = []
    grouped = defaultdict(list)
    coverage = {
        "family_unit": family_unit,
        "total_replay_rows": len(replay_results.get("all_rows") or []),
        "family_rows": 0,
        "candidate_rows": 0,
        "excluded_non_family_rows": 0,
        "missing_candidate_rows": 0,
        "candidate_snapshots": 0,
        "predicted_snapshots": 0,
        "abstained_snapshots": 0,
        "failed_snapshots": 0,
        "source_diagnostics_missing_snapshots": 0,
        "prediction_status_counts": {},
        "failure_reason_counts": {},
    }
    for raw in replay_results.get("all_rows") or []:
        market_id = str(raw.get("market_id") or "")
        spec = REGISTRY.get(market_id)
        in_family = family_unit_matches(spec, family_unit) or (
            spec is None and str(family_unit or "").lower() == "all"
        )
        if not in_family:
            coverage["excluded_non_family_rows"] += 1
            continue
        coverage["family_rows"] += 1
        copy = dict(raw)
        copy.update(
            {
                "candidate_p": None,
                "candidate_cutoff_hour": None,
                "candidate_prediction_status": "unscored",
                "candidate_failure_reason": "",
                "candidate_failure_detail": "",
                "candidate_countable": False,
            }
        )
        row_index = len(rows)
        rows.append(copy)
        grouped[(market_id, str(raw.get("snapshot_id")))].append(row_index)

    status_counts = Counter()
    reason_counts = Counter()
    for (market_id, snapshot_id), indexes in grouped.items():
        coverage["candidate_snapshots"] += 1
        spec = REGISTRY.get(market_id)
        feature_vector = feature_rows.get((market_id, snapshot_id)) or {}
        captured_diagnostics = source_diagnostics.get((market_id, snapshot_id))
        replay_band_rows = [_residual_replay_band_row(rows[index]) for index in indexes]
        if captured_diagnostics is None:
            coverage["source_diagnostics_missing_snapshots"] += 1
        payload = residual_distribution_v1_replay_payload(
            artifact=artifact,
            feature_vector=feature_vector,
            source_diagnostics=captured_diagnostics,
            market_id=market_id,
            unit=spec.display_unit if spec is not None else None,
            band_rows=replay_band_rows,
        )
        status = str(payload.get("status") or "failed").lower()
        failure_reason = str(payload.get("failure_reason") or "")
        failure_detail = str(payload.get("failure_detail") or "")
        status_counts[status] += 1
        if failure_reason:
            reason_counts[failure_reason] += 1
        if status == "predicted":
            coverage["predicted_snapshots"] += 1
        elif status in {"skipped", "skip"}:
            coverage["abstained_snapshots"] += 1
        else:
            coverage["failed_snapshots"] += 1

        probabilities = payload.get("probabilities") if status == "predicted" else {}
        for index, band_row in zip(indexes, replay_band_rows):
            row = rows[index]
            probability = (probabilities or {}).get(residual_band_key(band_row))
            if status == "predicted" and _valid_probability(probability):
                row["candidate_p"] = float(probability)
                row["candidate_countable"] = True
            row["candidate_prediction_status"] = status
            row["candidate_failure_reason"] = failure_reason
            row["candidate_failure_detail"] = failure_detail
            row["candidate_cutoff_hour"] = feature_vector.get("cutoff_hour")
            row["feature_schema_version"] = feature_vector.get("feature_schema_version")
            row["candidate_density_mean_f"] = payload.get("mean_f")
            row["candidate_density_sigma_f"] = payload.get("sigma_f")
            row["candidate_density_floor_bucket"] = payload.get(
                "printed_observed_floor_bucket"
            )
            row["candidate_calibration_temperature"] = payload.get(
                "calibration_temperature"
            )

    candidate_rows = sum(1 for row in rows if _valid_probability(row.get("candidate_p")))
    coverage["candidate_rows"] = candidate_rows
    coverage["missing_candidate_rows"] = coverage["family_rows"] - candidate_rows
    coverage["prediction_status_counts"] = dict(sorted(status_counts.items()))
    coverage["failure_reason_counts"] = dict(sorted(reason_counts.items()))
    return rows, coverage


def build_candidate_distributions(manifest, snapshots_root, artifact):
    """Return (market_id, snapshot_id) -> pooled candidate distribution."""
    family_unit = artifact.get("family_unit") or "F"
    models_by_hour = artifact.get("models") or {}
    support = artifact.get("support")
    feature_rows, diagnostics = build_candidate_features(manifest, snapshots_root, family_unit, artifact=artifact)
    by_hour = defaultdict(list)
    for (market_id, snapshot_id), feature_row in feature_rows.items():
        hour = str(feature_row["cutoff_hour"])
        if hour not in models_by_hour:
            diagnostics["missing_hour_models"] += 1
            continue
        by_hour[hour].append((market_id, snapshot_id, feature_row))

    predictions = {}
    for hour, items in sorted(by_hour.items(), key=lambda item: int(item[0])):
        bundle = models_by_hour[hour]
        rows = [item[2] for item in items]
        distributions = predict_rows(
            bundle["model"],
            bundle["imputer"],
            bundle["feature_names"],
            rows,
            support=support,
        )
        for (market_id, snapshot_id, feature_row), distribution in zip(items, distributions):
            predictions[(market_id, snapshot_id)] = {
                "distribution": distribution,
                "cutoff_hour": feature_row["cutoff_hour"],
                "feature_schema_version": feature_row.get("feature_schema_version") or FEATURE_SCHEMA_VERSION,
            }
    diagnostics["predicted_snapshots"] = len(predictions)
    return predictions, diagnostics


def attach_candidate_probabilities(replay_results, predictions, family_unit, source_freshness=None):
    rows = []
    coverage = {
        "family_unit": family_unit,
        "total_replay_rows": len(replay_results.get("all_rows") or []),
        "family_rows": 0,
        "candidate_rows": 0,
        "excluded_non_family_rows": 0,
        "missing_candidate_rows": 0,
    }
    for row in replay_results.get("all_rows") or []:
        market_id = row.get("market_id")
        spec = REGISTRY.get(market_id)
        if not family_unit_matches(spec, family_unit):
            coverage["excluded_non_family_rows"] += 1
            continue
        coverage["family_rows"] += 1
        copy = dict(row)
        snapshot_id = str(row.get("snapshot_id"))
        copy["source_freshness_state"] = (source_freshness or {}).get(
            (market_id, snapshot_id),
            "missing_source_status",
        )
        candidate = predictions.get((market_id, snapshot_id))
        if candidate:
            kind, value, value_hi = snapshot_band_key(row)
            copy["candidate_cutoff_hour"] = candidate.get("cutoff_hour")
            copy["feature_schema_version"] = candidate.get("feature_schema_version")
            copy["candidate_p"] = band_probability_from_distribution(
                candidate.get("distribution"),
                kind,
                value,
                value_hi,
            )
        else:
            copy["candidate_cutoff_hour"] = None
            copy["candidate_p"] = None
        if _valid_probability(copy.get("candidate_p")):
            coverage["candidate_rows"] += 1
        else:
            coverage["missing_candidate_rows"] += 1
        rows.append(copy)
    return rows, coverage


def attach_band_candidate_probabilities(
    replay_results,
    feature_rows,
    artifact,
    family_unit,
    clob_features=None,
    source_freshness=None,
):
    rows = []
    coverage = {
        "family_unit": family_unit,
        "total_replay_rows": len(replay_results.get("all_rows") or []),
        "family_rows": 0,
        "candidate_rows": 0,
        "excluded_non_family_rows": 0,
        "missing_candidate_rows": 0,
    }
    models_by_hour = artifact.get("models") or {}
    by_hour = defaultdict(list)
    for row in replay_results.get("all_rows") or []:
        market_id = row.get("market_id")
        spec = REGISTRY.get(market_id)
        if not family_unit_matches(spec, family_unit):
            coverage["excluded_non_family_rows"] += 1
            continue
        coverage["family_rows"] += 1
        copy = dict(row)
        copy["candidate_p"] = None
        copy["candidate_cutoff_hour"] = None
        snapshot_id = str(row.get("snapshot_id"))
        copy["source_freshness_state"] = (source_freshness or {}).get(
            (market_id, snapshot_id),
            "missing_source_status",
        )
        feature_row = feature_rows.get((market_id, snapshot_id))
        if feature_row:
            copy["feature_schema_version"] = feature_row.get("feature_schema_version") or FEATURE_SCHEMA_VERSION
            kind, value, value_hi = snapshot_band_key(row)
            band_row = band_prediction_record(
                feature_row,
                kind,
                value,
                value_hi=value_hi,
            )
            copy["_band_postprocess_row"] = band_row
            attach_forecast_profile_slice_context(copy, feature_row=feature_row, band_row=band_row)
            attach_marine_contrast_slice_context(copy, feature_row=feature_row, band_row=band_row)
            clob_key = (market_id, snapshot_id, kind, value, value_hi)
            clob_row = (clob_features or {}).get(clob_key)
            if clob_row:
                for column in CLOB_MODEL_FEATURE_COLUMNS:
                    band_row[column] = clob_row.get(column)
                    copy[column] = clob_row.get(column)
            hour = str(band_row.get("cutoff_hour"))
            copy["candidate_cutoff_hour"] = band_row.get("cutoff_hour")
            if (
                pooled_band_regime_route(band_row) == "pooled_band_default"
                and hour in models_by_hour
            ):
                by_hour[hour].append((len(rows), band_row))
            else:
                coverage["missing_candidate_rows"] += 1
        else:
            coverage["missing_candidate_rows"] += 1
        rows.append(copy)

    postprocess = artifact.get("postprocess") or {}
    band_postprocess_enabled = any(
        key in postprocess
        for key in (
            "hard_floor_enabled",
            "support_floor_enabled",
            "late_lockin_enabled",
            "adjacent_calibration_enabled",
            "exact_winner_catchup_enabled",
            "forecast_centering_enabled",
        )
    )
    for hour, items in sorted(by_hour.items(), key=lambda item: int(item[0])):
        bundle = models_by_hour[hour]
        band_rows = [item[1] for item in items]
        probabilities = predict_band_rows_for_bundle(bundle, band_rows, postprocess=False)
        for (row_index, band_row), probability in zip(items, probabilities):
            if band_postprocess_enabled:
                probability = apply_band_postprocessing(
                    probability,
                    rows[row_index].get("_band_postprocess_row") or band_row,
                    config=postprocess,
                )
            rows[row_index]["candidate_p"] = probability

    if postprocess.get("partition_normalization_enabled", True):
        normalize_partition_probabilities(
            rows,
            gamma=float(postprocess.get("partition_normalization_gamma", 1.25)),
        )
    if postprocess.get("current_blend_enabled", False):
        apply_current_blend_guardrail(rows, postprocess)
    for row in rows:
        row.pop("_band_postprocess_row", None)

    candidate_rows = sum(1 for row in rows if _valid_probability(row.get("candidate_p")))
    coverage["candidate_rows"] = candidate_rows
    coverage["missing_candidate_rows"] = coverage["family_rows"] - candidate_rows
    return rows, coverage


def attach_density_candidate_probabilities(
    replay_results,
    feature_rows,
    artifact,
    family_unit,
    source_freshness=None,
):
    rows = []
    coverage = {
        "family_unit": family_unit,
        "total_replay_rows": len(replay_results.get("all_rows") or []),
        "family_rows": 0,
        "candidate_rows": 0,
        "excluded_non_family_rows": 0,
        "missing_candidate_rows": 0,
    }
    snapshot_rows = []
    payload_indexes = {}
    for row in replay_results.get("all_rows") or []:
        market_id = row.get("market_id")
        spec = REGISTRY.get(market_id)
        if not family_unit_matches(spec, family_unit):
            coverage["excluded_non_family_rows"] += 1
            continue
        coverage["family_rows"] += 1
        copy = dict(row)
        copy["candidate_p"] = None
        copy["candidate_cutoff_hour"] = None
        snapshot_id = str(row.get("snapshot_id"))
        copy["source_freshness_state"] = (source_freshness or {}).get(
            (market_id, snapshot_id),
            "missing_source_status",
        )
        feature_row = feature_rows.get((market_id, snapshot_id))
        if feature_row:
            copy["candidate_cutoff_hour"] = feature_row.get("cutoff_hour")
            copy["feature_schema_version"] = feature_row.get("feature_schema_version") or FEATURE_SCHEMA_VERSION
            key = (market_id, snapshot_id)
            if key not in payload_indexes:
                payload_indexes[key] = len(snapshot_rows)
                snapshot_rows.append(feature_row)
        else:
            coverage["missing_candidate_rows"] += 1
        rows.append(copy)

    payloads = predict_density_rows_for_bundle(artifact, snapshot_rows)
    payload_by_snapshot = {
        key: payloads[index] if index < len(payloads) else None
        for key, index in payload_indexes.items()
    }
    projection_cache = {}
    density_postprocess = artifact.get("density_postprocess") or {}
    for row in rows:
        if _valid_probability(row.get("candidate_p")):
            continue
        market_id = row.get("market_id")
        snapshot_id = str(row.get("snapshot_id"))
        payload = payload_by_snapshot.get((market_id, snapshot_id))
        spec = REGISTRY.get(market_id)
        if not payload or not spec:
            continue
        feature_row = feature_rows.get((market_id, snapshot_id)) or {}
        kind, value, value_hi = snapshot_band_key(row)
        band_row = (
            band_prediction_record(feature_row, kind, value, value_hi=value_hi)
            if feature_row
            else {}
        )
        band_row["source_freshness_state"] = row.get("source_freshness_state")
        attach_forecast_profile_slice_context(row, feature_row=feature_row, band_row=band_row)
        cache_key = (market_id, snapshot_id)
        cached = projection_cache.get(cache_key)
        if cached is None:
            calibrated_payload = apply_continuous_density_calibration(
                payload,
                artifact,
                floor_bucket=band_row.get("observed_floor_bucket"),
                unit=spec.display_unit,
                resolution_weight=band_row.get("late_lockin_strength", 0.0),
                cutoff_hour=feature_row.get("cutoff_hour"),
            )
            cached = {
                "payload": calibrated_payload,
                "projection_index": density_projection_index(calibrated_payload),
                "floor_bucket": band_row.get("observed_floor_bucket"),
                "lockin_strength": band_row.get("late_lockin_strength"),
            }
            projection_cache[cache_key] = cached
        payload = cached.get("payload") or payload
        probability = density_projection_probability(
            cached.get("projection_index"),
            spec.display_unit,
            kind,
            value,
            value_hi=value_hi,
        )
        if probability is None:
            probability = density_band_probability_from_distribution(
                payload,
                spec,
                {
                    "kind": kind,
                    "value": value,
                    "value_hi": value_hi,
                    "unit": spec.display_unit,
                },
            )
        if _valid_probability(probability):
            probability = apply_density_band_postprocessing(
                probability,
                band_row,
                config=density_postprocess,
            )
            row["candidate_p"] = _clamp_probability(probability)
            row["candidate_density_mean_f"] = payload.get("mean_f")
            row["candidate_density_sigma_f"] = payload.get("sigma_f")
            row["candidate_density_floor_bucket"] = cached.get("floor_bucket")
            row["candidate_density_lockin_strength"] = cached.get("lockin_strength")

    if density_postprocess.get("enabled") and density_postprocess.get("partition_normalization_enabled", False):
        normalize_partition_probabilities(
            rows,
            gamma=float(density_postprocess.get("partition_normalization_gamma", 1.25)),
        )

    candidate_rows = sum(1 for row in rows if _valid_probability(row.get("candidate_p")))
    coverage["candidate_rows"] = candidate_rows
    coverage["missing_candidate_rows"] = coverage["family_rows"] - candidate_rows
    return rows, coverage


def normalize_partition_probabilities(rows, gamma=1.25):
    """Normalize direct band probabilities across each snapshot's band partition."""
    gamma = max(0.1, float(gamma or 1.0))
    grouped = defaultdict(list)
    for idx, row in enumerate(rows):
        if _valid_probability(row.get("candidate_p")):
            grouped[(row.get("market_id"), row.get("snapshot_id"))].append(idx)
    for indexes in grouped.values():
        weights = [
            max(1e-12, float(rows[idx]["candidate_p"])) ** gamma
            for idx in indexes
        ]
        total = sum(weights)
        if total <= 0:
            continue
        for idx, weight in zip(indexes, weights):
            rows[idx]["candidate_p"] = weight / total
    return rows


def apply_current_blend_guardrail(rows, config):
    """Blend pooled candidate probabilities with incumbent replay probabilities."""
    for row in rows:
        if not _valid_probability(row.get("candidate_p")):
            continue
        if not _valid_probability(row.get("replayed_p")):
            continue
        blend_context = dict(row.get("_band_postprocess_row") or {})
        blend_context.update(row)
        row["candidate_p"] = blend_with_current(
            row["candidate_p"],
            row["replayed_p"],
            row=blend_context,
            config=config,
        )
    return rows


def _single_entry_manifest(manifest, folder, snapshots_root):
    entry = entry_for_folder(manifest, folder)
    if not entry:
        return manifest
    single = {key: value for key, value in (manifest or {}).items() if key != "_path"}
    single["entries"] = [entry]
    single["summary"] = summarize_entries([entry])
    single["corpus_hash"] = replay_cache.fingerprint({
        "source_corpus_hash": (manifest or {}).get("corpus_hash"),
        "event_slug": entry.get("event_slug"),
        "inputs_fp": replay_cache.entry_inputs_fingerprint(entry),
    })
    single["snapshots_root"] = str(snapshots_root)
    return single


def _sum_numeric_dicts(dicts):
    out = {}
    for payload in dicts:
        for key, value in (payload or {}).items():
            if isinstance(value, bool):
                out[key] = value
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                out[key] = out.get(key, 0) + value
            elif isinstance(value, dict):
                current = out.get(key)
                if isinstance(current, dict):
                    out[key] = _sum_numeric_dicts([current, value])
                else:
                    out[key] = dict(value)
            elif isinstance(value, list):
                current = out.setdefault(key, [])
                if isinstance(current, list):
                    current.extend(value)
                else:
                    out[key] = list(value)
            elif key not in out or out.get(key) in (None, "", []):
                out[key] = value
    return out


def _merge_candidate_coverage(items, family_unit):
    merged = _sum_numeric_dicts(items)
    merged["family_unit"] = family_unit
    return merged


def _merge_candidate_diagnostics(items, family_unit):
    merged = _sum_numeric_dicts(items)
    merged["family_unit"] = family_unit
    for key in (
        "feature_errors",
        "reanalysis_sidecar_loaded_markets",
        "marine_water_contrast_sidecar_loaded_markets",
    ):
        if key not in merged:
            continue
        if key == "feature_errors":
            merged[key] = list(merged[key])[:20]
        else:
            merged[key] = sorted({str(item) for item in merged[key]})
    return merged


def _compact_replay_results(results):
    return {
        "folders": results.get("folders") or [],
        "days": results.get("days") or [],
        "total_rows": results.get("total_rows", 0),
        "all_rows": results.get("all_rows") or [],
        "snaps_in_corpus": results.get("snaps_in_corpus", 0),
        "snaps_scored": results.get("snaps_scored", 0),
        "replayed_versions": results.get("replayed_versions") or [],
        "fidelity_rows": results.get("fidelity_rows") or [],
        "band_semantics": results.get("band_semantics") or {},
        "include_reconstructed": bool(results.get("include_reconstructed")),
        "corpus_warnings": results.get("corpus_warnings") or [],
    }


def _aggregate_replay_results(day_results, *, manifest, include_reconstructed, long_job_guard_info=None):
    all_rows = []
    days = []
    fidelity_rows = []
    corpus_warnings = []
    folders = []
    band_semantics = Counter()
    snaps_in_corpus = 0
    snaps_scored = 0
    replayed_versions = set()
    for payload in day_results:
        folders.extend(payload.get("folders") or [])
        rows = payload.get("all_rows") or []
        all_rows.extend(rows)
        days.extend(payload.get("days") or [])
        fidelity = payload.get("fidelity_rows") or []
        fidelity_rows.extend(fidelity)
        corpus_warnings.extend(payload.get("corpus_warnings") or [])
        snaps_in_corpus += int(payload.get("snaps_in_corpus") or 0)
        snaps_scored += int(payload.get("snaps_scored") or 0)
        replayed_versions.update(str(item) for item in (payload.get("replayed_versions") or []) if item)
        for key, value in (payload.get("band_semantics") or {}).items():
            try:
                band_semantics[key] += int(value or 0)
            except (TypeError, ValueError):
                pass
    last_rows = last_pre_close_rows(all_rows)
    return {
        "folders": folders,
        "days": days,
        "total_rows": len(all_rows),
        "all_rows": all_rows,
        "snaps_in_corpus": snaps_in_corpus,
        "snaps_scored": snaps_scored,
        "replayed_versions": sorted(replayed_versions),
        "aggregate": current_replay_comparison(all_rows),
        "daily_first": current_replay_daily_first_comparison(days),
        "last_pre_close": current_replay_comparison(last_rows),
        "by_day": current_replay_grouped_comparison(all_rows, "target_date"),
        "by_hour": current_replay_grouped_comparison(all_rows, "cutoff_hour"),
        "by_bin_type": current_replay_grouped_comparison(all_rows, "bin_type"),
        "fidelity": current_replay_fidelity_summary(fidelity_rows),
        "fidelity_rows": fidelity_rows,
        "band_semantics": dict(band_semantics),
        "include_reconstructed": bool(include_reconstructed),
        "promotion_corpus": _manifest_summary(manifest),
        "corpus_warnings": corpus_warnings,
        "long_job_guard": long_job_guard_info or {},
    }


DEFAULT_REPLAY_CACHE_FRESH_WINDOW_DAYS = 14

HEAVY_DIAGNOSTICS_MANIFEST_SCHEMA_VERSION = "promotion_heavy_diagnostics_v0.1"
_HEAVY_DIAGNOSTIC_SECTIONS = ("microstructure", "source_state_ablation", "conservative_bridge")


def _heavy_diagnostics_manifest_path(args):
    return Path(args.corpus).parent / "promotion_heavy_diagnostics.json"


def _load_heavy_diagnostics_carry(args, artifact_hash):
    """Reuse microstructure/ablation/bridge diagnostics for an unchanged model.

    These recompute over the full corpus row set (~5.5h at corpus 297) yet
    their inputs only materially change when the candidate artifact changes,
    so daily recompute on a stable model is waste. Disabled by default
    (max-age 0) so shadow contract runs, which share this code path with
    per-contract artifacts, never touch the shared manifest.
    """
    max_age_days = float(getattr(args, "heavy_analysis_max_age_days", 0.0) or 0.0)
    if max_age_days <= 0 or getattr(args, "force_heavy_analysis", False):
        return None
    try:
        payload = json.loads(_heavy_diagnostics_manifest_path(args).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not artifact_hash or payload.get("artifact_hash") != artifact_hash:
        return None
    generated = payload.get("generated_at_utc")
    try:
        age_days = (
            datetime.now(timezone.utc) - datetime.fromisoformat(str(generated))
        ).total_seconds() / 86400.0
    except (TypeError, ValueError):
        return None
    if age_days < 0 or age_days > max_age_days:
        return None
    for key in _HEAVY_DIAGNOSTIC_SECTIONS:
        section = payload.get(key)
        if isinstance(section, dict):
            section["carried_forward"] = True
            section["carried_from_utc"] = generated
            section["carry_age_days"] = round(age_days, 2)
    return payload


def _write_heavy_diagnostics_manifest(args, artifact_hash, sections):
    from weather.io import write_json_atomic

    if float(getattr(args, "heavy_analysis_max_age_days", 0.0) or 0.0) <= 0:
        return None
    payload = {
        "schema_version": HEAVY_DIAGNOSTICS_MANIFEST_SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "artifact_hash": artifact_hash,
    }
    payload.update({key: sections.get(key) for key in _HEAVY_DIAGNOSTIC_SECTIONS})
    try:
        return write_json_atomic(
            _heavy_diagnostics_manifest_path(args), payload, trailing_newline=True,
        )
    except OSError:
        return None


def replay_cache_fresh_window_cutoff(window_days, today=None):
    """ISO date; entries on/after it are recomputed instead of cache-read.

    Sized to exceed the reanalysis recent-refresh lag (10 days) so daily
    sidecar rewrites can never serve stale cached predictions.
    """
    days = int(window_days or 0)
    if days <= 0:
        return None
    today = today or datetime.now(timezone.utc).date()
    return (today - timedelta(days=days)).isoformat()


def entry_in_replay_fresh_window(entry, cutoff):
    if not cutoff:
        return False
    target_date = str((entry or {}).get("target_date") or "")
    return bool(target_date) and target_date >= cutoff


def _pooled_replay_cache_config(args, manifest, artifact, *, prediction_mode, family_unit, registry_contract):
    postprocess = artifact.get("postprocess") or {}
    density_postprocess = artifact.get("density_postprocess") or {}
    return {
        "consumer_row_contract": "pooled_candidate_replay_day_rows_v0.1",
        "prediction_mode": prediction_mode,
        "family_unit": family_unit,
        "artifact_schema_version": artifact.get("schema_version"),
        "artifact_feature_schema_version": artifact.get("feature_schema_version"),
        "include_reconstructed": bool((manifest or {}).get("include_reconstructed")),
        "clob_max_age_seconds": getattr(args, "clob_max_age_seconds", None),
        "postprocess_schema_version": postprocess.get("schema_version"),
        "density_postprocess_schema_version": density_postprocess.get("schema_version"),
        "registry_postprocess_config_hash": (registry_contract or {}).get("postprocess_config_hash"),
        "replay_cache_schema_version": replay_cache.REPLAY_CACHE_SCHEMA_VERSION,
    }


def _candidate_replay_row_identity(row):
    """Identity stable before and after the settlement-label join."""

    return (
        str((row or {}).get("market_id") or ""),
        str((row or {}).get("target_date") or ""),
        str((row or {}).get("snapshot_id") or ""),
        str((row or {}).get("band") or ""),
        str((row or {}).get("bin_type") or ""),
        str((row or {}).get("bin_value_c") or ""),
        str((row or {}).get("bin_value_hi") or ""),
    )


def _prediction_only_replay_results(replay_results):
    """Remove settlement-derived values before candidate prediction.

    ``run_replay_backtest`` remains the canonical captured-input row
    enumerator.  It resolves settlement to decide which tape rows are
    scoreable, but none of those settlement-derived fields are allowed across
    the candidate prediction boundary in the bounded production adapter.
    """

    labels_by_identity = {}
    prediction_rows = []
    for source_row in (replay_results or {}).get("all_rows") or ():
        identity = _candidate_replay_row_identity(source_row)
        if not all(identity[:4]) or identity in labels_by_identity:
            raise BoundedCandidateReplayError(
                "candidate replay row identity is missing or duplicated before prediction"
            )
        labels_by_identity[identity] = {
            key: source_row.get(key)
            for key in _SETTLEMENT_LABEL_FIELDS
            if key in source_row
        }
        prediction_rows.append({
            key: value
            for key, value in source_row.items()
            if key not in _SETTLEMENT_LABEL_FIELDS
        })
    prediction_results = dict(replay_results or {})
    prediction_results["all_rows"] = prediction_rows
    return prediction_results, labels_by_identity


def _join_deferred_settlement_labels(candidate_rows, labels_by_identity):
    joined = []
    for candidate_row in candidate_rows:
        identity = _candidate_replay_row_identity(candidate_row)
        labels = labels_by_identity.get(identity)
        if labels is None:
            raise BoundedCandidateReplayError(
                "candidate prediction cannot be joined to its pinned settlement row"
            )
        row = dict(candidate_row)
        row.update(labels)
        joined.append(row)
    return joined


def _compute_pooled_candidate_day(
    args,
    manifest,
    folder,
    artifact,
    *,
    family_unit,
    prediction_mode,
    defer_settlement_join=False,
):
    day_manifest = _single_entry_manifest(manifest, folder, args.snapshots_root)
    replay_results = run_replay_backtest(
        [str(folder)],
        daily_summary_path=None,
        overrides={},
        out_path=None,
        include_reconstructed=day_manifest.get("include_reconstructed", False),
        write=False,
        corpus_manifest=day_manifest,
        long_job_guard_info=getattr(args, "long_job_guard_info", None),
    )
    if prediction_mode == "band_binary":
        labels_by_identity = None
        prediction_replay_results = replay_results
        if defer_settlement_join:
            prediction_replay_results, labels_by_identity = (
                _prediction_only_replay_results(replay_results)
            )
        feature_rows, diagnostics = build_candidate_features(
            day_manifest,
            args.snapshots_root,
            family_unit,
            artifact=artifact,
        )
        clob_features, clob_diagnostics = build_clob_feature_index(
            day_manifest,
            args.snapshots_root,
            family_unit,
            max_age_seconds=args.clob_max_age_seconds,
        )
        source_freshness, source_freshness_diagnostics = build_source_freshness_index(
            day_manifest,
            args.snapshots_root,
            family_unit,
        )
        diagnostics.update(clob_diagnostics)
        diagnostics.update(source_freshness_diagnostics)
        candidate_rows, coverage = attach_band_candidate_probabilities(
            prediction_replay_results,
            feature_rows,
            artifact,
            family_unit,
            clob_features=clob_features,
            source_freshness=source_freshness,
        )
        if labels_by_identity is not None:
            candidate_rows = _join_deferred_settlement_labels(
                candidate_rows, labels_by_identity
            )
    elif prediction_mode == RESIDUAL_DISTRIBUTION_V1_MODE:
        feature_rows, diagnostics = build_candidate_features(
            day_manifest,
            args.snapshots_root,
            family_unit,
            artifact=artifact,
        )
        source_diagnostics, source_diagnostics_summary = (
            build_residual_source_diagnostics_index(
                day_manifest,
                args.snapshots_root,
                family_unit,
            )
        )
        diagnostics.update(source_diagnostics_summary)
        candidate_rows, coverage = attach_residual_distribution_v1_probabilities(
            replay_results,
            feature_rows,
            source_diagnostics,
            artifact,
            family_unit=family_unit,
        )
    elif prediction_mode == "continuous_density_f":
        feature_rows, diagnostics = build_candidate_features(
            day_manifest,
            args.snapshots_root,
            family_unit,
            artifact=artifact,
        )
        source_freshness, source_freshness_diagnostics = build_source_freshness_index(
            day_manifest,
            args.snapshots_root,
            family_unit,
        )
        diagnostics.update(source_freshness_diagnostics)
        candidate_rows, coverage = attach_density_candidate_probabilities(
            replay_results,
            feature_rows,
            artifact,
            family_unit,
            source_freshness=source_freshness,
        )
    else:
        predictions, diagnostics = build_candidate_distributions(day_manifest, args.snapshots_root, artifact)
        source_freshness, source_freshness_diagnostics = build_source_freshness_index(
            day_manifest,
            args.snapshots_root,
            family_unit,
        )
        diagnostics.update(source_freshness_diagnostics)
        candidate_rows, coverage = attach_candidate_probabilities(
            replay_results,
            predictions,
            family_unit,
            source_freshness=source_freshness,
        )
    return {
        "candidate_rows": candidate_rows,
        "coverage": coverage,
        "diagnostics": diagnostics,
        "replay_results": _compact_replay_results(replay_results),
    }


def _bounded_required_identity(value, field):
    normalized = str(value or "").strip()
    if not normalized:
        raise BoundedCandidateReplayError(f"{field} is required")
    return normalized


def _bounded_expected_sha256(value, field):
    normalized = str(value or "").strip()
    if (
        len(normalized) != 64
        or normalized != normalized.lower()
        or any(char not in "0123456789abcdef" for char in normalized)
    ):
        raise BoundedCandidateReplayError(
            f"{field} must be a lowercase SHA-256 digest"
        )
    return normalized


def _bounded_positive_int(value, field):
    if isinstance(value, bool):
        raise BoundedCandidateReplayError(f"{field} must be a positive integer")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise BoundedCandidateReplayError(
            f"{field} must be a positive integer"
        ) from exc
    if normalized <= 0:
        raise BoundedCandidateReplayError(f"{field} must be a positive integer")
    return normalized


def _bounded_locked_date(value):
    normalized = str(value or "").strip()
    try:
        parsed = date.fromisoformat(normalized)
    except ValueError as exc:
        raise BoundedCandidateReplayError(
            f"locked date {normalized!r} must be YYYY-MM-DD"
        ) from exc
    if normalized != parsed.isoformat():
        raise BoundedCandidateReplayError(
            f"locked date {normalized!r} is not canonical"
        )
    return normalized


def _bounded_manifest_snapshot_hash(entry, field, snapshot_id):
    value = ((entry or {}).get(field) or {}).get(snapshot_id)
    return _bounded_expected_sha256(
        value,
        f"manifest {field}[{snapshot_id!r}]",
    )


def _bounded_locked_manifest_entries(
    manifest,
    *,
    snapshots_root,
    locked_dates,
    locked_folders,
    max_market_days,
    max_rows_per_market_day,
):
    dates = {_bounded_locked_date(value) for value in (locked_dates or ())}
    folder_values = [str(value).strip() for value in (locked_folders or ())]
    if any(not value for value in folder_values):
        raise BoundedCandidateReplayError("locked folders cannot contain blanks")
    if not dates and not folder_values:
        raise BoundedCandidateReplayError(
            "at least one explicit locked date or manifest-pinned folder is required"
        )

    entries = list((manifest or {}).get("entries") or ())
    try:
        folders = list(folders_from_manifest(manifest, snapshots_root))
    except (OSError, RuntimeError, ValueError) as exc:
        raise BoundedCandidateReplayError(
            f"manifest folder is outside the explicit snapshots root: {exc}"
        ) from exc
    if len(entries) != len(folders):
        raise BoundedCandidateReplayError(
            "promotion manifest entries and resolved folders differ"
        )

    rows = []
    by_slug = {}
    by_resolved_path = {}
    for entry, folder in zip(entries, folders):
        slug = _bounded_required_identity(entry.get("event_slug"), "event_slug")
        if slug in by_slug:
            raise BoundedCandidateReplayError(
                f"duplicate promotion-manifest event_slug: {slug}"
            )
        folder = Path(folder)
        if not folder.exists() or not folder.is_dir():
            raise BoundedCandidateReplayError(
                f"manifest-pinned market-day folder is missing: {folder}"
            )
        resolved = folder.resolve()
        if folder.name != slug:
            raise BoundedCandidateReplayError(
                f"manifest event_slug {slug!r} does not match folder {folder.name!r}"
            )
        resolved_key = os.path.normcase(str(resolved))
        if resolved_key in by_resolved_path:
            raise BoundedCandidateReplayError(
                f"duplicate resolved promotion-manifest folder: {resolved}"
            )
        row = (entry, resolved)
        rows.append(row)
        by_slug[slug] = row
        by_resolved_path[resolved_key] = row

    selected = []
    if folder_values:
        seen_folders = set()
        for value in folder_values:
            matched = by_slug.get(value)
            if matched is None:
                path_key = os.path.normcase(str(Path(value).resolve()))
                matched = by_resolved_path.get(path_key)
            if matched is None:
                raise BoundedCandidateReplayError(
                    f"locked folder is not pinned by the promotion manifest: {value}"
                )
            slug = str(matched[0]["event_slug"])
            if slug in seen_folders:
                raise BoundedCandidateReplayError(
                    f"duplicate locked folder: {value}"
                )
            seen_folders.add(slug)
            selected.append(matched)
    else:
        selected = [
            row for row in rows if str(row[0].get("target_date") or "") in dates
        ]

    selected_dates = {
        _bounded_locked_date(entry.get("target_date"))
        for entry, _folder in selected
    }
    if dates:
        outside_lock = sorted(selected_dates - dates)
        missing_dates = sorted(dates - selected_dates)
        if outside_lock:
            raise BoundedCandidateReplayError(
                "locked folders include dates outside the explicit lock: "
                + ", ".join(outside_lock)
            )
        if missing_dates:
            raise BoundedCandidateReplayError(
                "explicit locked dates have no selected manifest folder: "
                + ", ".join(missing_dates)
            )
    if not selected:
        raise BoundedCandidateReplayError("the explicit lock selected no market-days")
    if len(selected) > max_market_days:
        raise BoundedCandidateReplayError(
            f"market-day bound exceeded: {len(selected)} > {max_market_days}"
        )

    market_days = set()
    validated = []
    for entry, folder in selected:
        target_date = _bounded_locked_date(entry.get("target_date"))
        market_id = _bounded_required_identity(entry.get("market_id"), "market_id")
        market_day = (target_date, market_id)
        if market_day in market_days:
            raise BoundedCandidateReplayError(
                f"duplicate manifest market-day identity: {market_day}"
            )
        market_days.add(market_day)

        raw_row_count = _bounded_positive_int(
            entry.get("row_count"), f"manifest row_count for {entry['event_slug']}"
        )
        if raw_row_count > max_rows_per_market_day:
            raise BoundedCandidateReplayError(
                f"manifest row bound exceeded for {entry['event_slug']}: "
                f"{raw_row_count} > {max_rows_per_market_day}"
            )
        snapshot_ids = [str(item) for item in entry.get("snapshot_ids") or ()]
        if not snapshot_ids or len(snapshot_ids) != len(set(snapshot_ids)):
            raise BoundedCandidateReplayError(
                f"manifest snapshot identities are missing or duplicated for {entry['event_slug']}"
            )
        if int(entry.get("snapshot_count") or -1) != len(snapshot_ids):
            raise BoundedCandidateReplayError(
                f"manifest snapshot_count mismatch for {entry['event_slug']}"
            )
        for snapshot_id in snapshot_ids:
            _bounded_manifest_snapshot_hash(
                entry, "replay_record_hashes", snapshot_id
            )
            _bounded_manifest_snapshot_hash(entry, "tape_row_hashes", snapshot_id)
        _bounded_expected_sha256(
            entry.get("label_hash"),
            f"manifest label_hash for {entry['event_slug']}",
        )
        if entry.get("settlement_bucket") is None:
            raise BoundedCandidateReplayError(
                f"manifest settlement is missing for {entry['event_slug']}"
            )
        validated.append((entry, folder))
    return sorted(
        validated,
        key=lambda item: (
            str(item[0]["target_date"]),
            str(item[0]["market_id"]),
            str(item[0]["event_slug"]),
        ),
    )


def _bounded_load_band_artifact(
    artifact_path,
    *,
    expected_artifact_sha256,
    candidate_id,
    release_id,
):
    path = Path(artifact_path).resolve()
    if not path.is_file():
        raise BoundedCandidateReplayError(f"candidate artifact is missing: {path}")
    actual_sha256 = sha256_file(path)
    if actual_sha256 != expected_artifact_sha256:
        raise BoundedCandidateReplayError(
            "candidate artifact SHA-256 does not match the predeclared identity"
        )
    artifact = load_artifact(path)
    if artifact.get("prediction_mode") != "band_binary":
        raise BoundedCandidateReplayError(
            "bounded pooled replay accepts only a serialized band_binary artifact"
        )
    if not isinstance(artifact.get("models"), dict) or not artifact.get("models"):
        raise BoundedCandidateReplayError("candidate artifact has no band models")
    for field in ("artifact_hash", "candidate_artifact_sha256"):
        embedded = str(artifact.get(field) or "").strip()
        if embedded and embedded != expected_artifact_sha256:
            raise BoundedCandidateReplayError(
                f"candidate artifact embedded {field} does not match its exact file SHA"
            )
    for field, expected in (
        ("candidate_id", candidate_id),
        ("variant_id", candidate_id),
        ("release_id", release_id),
    ):
        embedded = str(artifact.get(field) or "").strip()
        if embedded and embedded != expected:
            raise BoundedCandidateReplayError(
                f"candidate artifact embedded {field}={embedded!r}; expected {expected!r}"
            )
    return path, artifact


def _bounded_optional_float(value, field):
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise BoundedCandidateReplayError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise BoundedCandidateReplayError(f"{field} must be finite")
    return number


_PRESELECTION_MAX_MARKET_DAYS = 60
_PRESELECTION_MAX_ROWS_PER_MARKET_DAY = 250_000
_PRESELECTION_MAX_TAPE_BYTES = 128 * 1024 * 1024
_PRESELECTION_MAX_TAPE_FIELD_BYTES = 1024 * 1024
_PRESELECTION_MAX_REPLAY_BYTES = 64 * 1024 * 1024
_PRESELECTION_MAX_REPLAY_LINE_BYTES = 8 * 1024 * 1024
_PRESELECTION_MAX_REPLAY_MANIFEST_BYTES = 16 * 1024 * 1024
_PRESELECTION_MAX_SETTLEMENT_BYTES = 1024 * 1024


def _bounded_preselection_file_bytes(path, *, max_bytes, description):
    source_path = Path(path)
    if source_path.is_symlink():
        raise BoundedCandidateReplayError(
            f"{description} cannot be a symlink: {source_path}"
        )
    path = source_path.resolve(strict=True)
    try:
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_size <= 0
                or before.st_size > max_bytes
            ):
                raise BoundedCandidateReplayError(
                    f"{description} byte bound exceeded: {before.st_size}"
                )
            raw = handle.read(max_bytes + 1)
            after = os.fstat(handle.fileno())
    except OSError as exc:
        raise BoundedCandidateReplayError(
            f"{description} cannot be read within bounds: {exc}"
        ) from exc
    if (
        len(raw) != before.st_size
        or len(raw) > max_bytes
        or before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
    ):
        raise BoundedCandidateReplayError(
            f"{description} changed or exceeded its byte bound during read"
        )
    return path, raw, hashlib.sha256(raw).hexdigest()


def _bounded_preselection_file_unchanged(
    path,
    *,
    expected_sha256,
    max_bytes,
    description,
):
    _path, _raw, observed = _bounded_preselection_file_bytes(
        path,
        max_bytes=max_bytes,
        description=description,
    )
    return observed == expected_sha256


def _bounded_preselection_tape(path, *, max_rows):
    path, raw, raw_sha256 = _bounded_preselection_file_bytes(
        path,
        max_bytes=_PRESELECTION_MAX_TAPE_BYTES,
        description="preselection tape",
    )
    prior_limit = csv.field_size_limit()
    row_count = 0
    try:
        csv.field_size_limit(_PRESELECTION_MAX_TAPE_FIELD_BYTES)
        text = raw.decode("utf-8-sig")
        with io.StringIO(text, newline="") as handle:
            reader = csv.reader(handle)
            try:
                header = next(reader)
            except StopIteration as exc:
                raise BoundedCandidateReplayError(
                    "preselection tape is empty"
                ) from exc
            required = {
                "snapshot_id",
                "captured_at_local",
                "range_label",
                "bin_kind",
                "bin_value_c",
            }
            if not required <= set(header):
                raise BoundedCandidateReplayError(
                    "preselection tape is missing required columns"
                )
            for row_count, _row in enumerate(reader, start=1):
                if row_count > max_rows:
                    raise BoundedCandidateReplayError(
                        f"raw tape row bound exceeded: > {max_rows}"
                    )
    except (csv.Error, UnicodeError, OSError) as exc:
        raise BoundedCandidateReplayError(
            f"preselection tape cannot be read within bounds: {exc}"
        ) from exc
    finally:
        csv.field_size_limit(prior_limit)
    if row_count <= 0:
        raise BoundedCandidateReplayError("preselection tape has no data rows")
    frame = pd.read_csv(io.BytesIO(raw), low_memory=False)
    return path, raw_sha256, row_count, frame


def _bounded_preselection_replay_records(
    path,
    *,
    pinned_snapshot_ids,
    max_records,
    require_all_pinned=True,
):
    path, raw, raw_sha256 = _bounded_preselection_file_bytes(
        path,
        max_bytes=_PRESELECTION_MAX_REPLAY_BYTES,
        description="preselection replay",
    )
    records = {}
    record_count = 0
    try:
        with io.BytesIO(raw) as handle:
            for line_no, raw_line in enumerate(handle, start=1):
                if len(raw_line) > _PRESELECTION_MAX_REPLAY_LINE_BYTES:
                    raise BoundedCandidateReplayError(
                        f"preselection replay line {line_no} exceeds the byte bound"
                    )
                if not raw_line.strip():
                    continue
                record_count += 1
                if record_count > max_records:
                    raise BoundedCandidateReplayError(
                        f"preselection replay record bound exceeded: > {max_records}"
                    )
                record = _bounded_json_object(
                    raw_line,
                    description=f"preselection replay line {line_no}",
                )
                if not isinstance(record, dict):
                    raise BoundedCandidateReplayError(
                        f"preselection replay line {line_no} is not an object"
                    )
                snapshot_id = str(record.get("snapshot_id") or "").strip()
                if not snapshot_id:
                    raise BoundedCandidateReplayError(
                        f"preselection replay line {line_no} has no snapshot_id"
                    )
                if snapshot_id in pinned_snapshot_ids:
                    if snapshot_id in records:
                        raise BoundedCandidateReplayError(
                            f"duplicate pinned replay record: {snapshot_id}"
                        )
                    records[snapshot_id] = record
    except OSError as exc:
        raise BoundedCandidateReplayError(
            f"preselection replay cannot be read within bounds: {exc}"
        ) from exc
    missing = sorted(set(pinned_snapshot_ids) - set(records))
    if require_all_pinned and missing:
        raise BoundedCandidateReplayError(
            f"preselection replay is missing {len(missing)} pinned record(s)"
        )
    return path, raw_sha256, records


def _bounded_preselection_auxiliary_csv(path, *, max_rows):
    """Preflight a CSV consumed by the legacy feature-quality audit."""

    path = Path(path).resolve()
    if not path.exists():
        return None
    path, raw, raw_sha256 = _bounded_preselection_file_bytes(
        path,
        max_bytes=_PRESELECTION_MAX_TAPE_BYTES,
        description="preselection auxiliary CSV",
    )
    prior_limit = csv.field_size_limit()
    rows = []
    try:
        csv.field_size_limit(_PRESELECTION_MAX_TAPE_FIELD_BYTES)
        with io.StringIO(raw.decode("utf-8-sig"), newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise BoundedCandidateReplayError(
                    f"preselection auxiliary CSV is empty: {path}"
                )
            for row in reader:
                rows.append(dict(row))
                if len(rows) > max_rows:
                    raise BoundedCandidateReplayError(
                        f"preselection auxiliary CSV row bound exceeded: {path}"
                    )
    except (csv.Error, UnicodeError, OSError) as exc:
        raise BoundedCandidateReplayError(
            f"preselection auxiliary CSV cannot be read within bounds: {path}: {exc}"
        ) from exc
    finally:
        csv.field_size_limit(prior_limit)
    return path, raw_sha256, rows


def _bounded_preselection_optional_file(path, *, max_bytes):
    path = Path(path).resolve()
    if not path.exists():
        return None
    path, raw, raw_sha256 = _bounded_preselection_file_bytes(
        path,
        max_bytes=max_bytes,
        description="preselection auxiliary file",
    )
    return path, raw_sha256, raw


def _bounded_json_pairs(pairs):
    payload = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate JSON key {key!r}")
        payload[key] = value
    return payload


def _reject_bounded_json_constant(value):
    raise ValueError(f"non-finite JSON value {value}")


def _reject_bounded_json_nonfinite(value, *, path="$"):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"non-finite JSON number at {path}")
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_bounded_json_nonfinite(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_bounded_json_nonfinite(item, path=f"{path}[{index}]")


def _bounded_json_object(raw, *, description):
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            parse_constant=_reject_bounded_json_constant,
            object_pairs_hook=_bounded_json_pairs,
        )
        _reject_bounded_json_nonfinite(payload)
    except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise BoundedCandidateReplayError(
            f"{description} is not strict UTF-8 JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise BoundedCandidateReplayError(f"{description} must be a JSON object")
    return payload


def _require_preselection_folder_file(path, *, folder):
    path = Path(path).resolve(strict=True)
    if path.parent != Path(folder).resolve(strict=True):
        raise BoundedCandidateReplayError(
            f"preselection source file escaped its market-day folder: {path}"
        )
    return path


def load_bounded_preselection_folder_inputs(
    folder,
    *,
    snapshots_root,
    max_rows_per_market_day,
):
    """Load one folder for grade-only manifest construction within hard bounds.

    The ordinary promotion-corpus builder predates production resource limits.
    This adapter supplies its already-validated inputs so it never executes its
    unbounded CSV, replay, settlement, or feature-audit input reads.
    """

    max_rows_per_market_day = _bounded_positive_int(
        max_rows_per_market_day, "max_rows_per_market_day"
    )
    if max_rows_per_market_day > _PRESELECTION_MAX_ROWS_PER_MARKET_DAY:
        raise BoundedCandidateReplayError(
            "production preselection row bound exceeds the reviewed maximum"
        )
    root = Path(snapshots_root).resolve(strict=True)
    folder = Path(folder).resolve(strict=True)
    try:
        folder.relative_to(root)
    except ValueError as exc:
        raise BoundedCandidateReplayError(
            f"preselection folder is outside the snapshots root: {folder}"
        ) from exc

    tape_path, tape_sha256, _tape_rows, frame = _bounded_preselection_tape(
        folder / "snapshots_long.csv",
        max_rows=max_rows_per_market_day,
    )
    _require_preselection_folder_file(tape_path, folder=folder)
    if "snapshot_id" not in frame:
        raise BoundedCandidateReplayError(
            f"snapshot_id is missing from {folder.name} tape"
        )
    tape_snapshot_ids = frozenset(
        value
        for value in frame["snapshot_id"].dropna().astype(str)
        if value and value != "nan"
    )
    if not tape_snapshot_ids:
        raise BoundedCandidateReplayError(
            f"preselection tape has no snapshot identities: {folder}"
        )
    replay_path, replay_sha256, records = _bounded_preselection_replay_records(
        folder / "replay_inputs.jsonl",
        pinned_snapshot_ids=tape_snapshot_ids,
        max_records=max_rows_per_market_day,
        require_all_pinned=False,
    )
    _require_preselection_folder_file(replay_path, folder=folder)
    if any(is_reconstructed(record) for record in records.values()):
        raise BoundedCandidateReplayError(
            "production preselection captured replay file contains reconstructed inputs"
        )

    features_binding = _bounded_preselection_auxiliary_csv(
        folder / "features_long.csv",
        max_rows=max_rows_per_market_day,
    )
    settlement_binding = _bounded_preselection_optional_file(
        folder / "settlement.json",
        max_bytes=_PRESELECTION_MAX_SETTLEMENT_BYTES,
    )
    if features_binding is not None:
        _require_preselection_folder_file(features_binding[0], folder=folder)
    if settlement_binding is not None:
        _require_preselection_folder_file(settlement_binding[0], folder=folder)
    label = ledger_label_for_slug(folder.name)
    if not (isinstance(label, dict) and ledger_label_matches_folder(label, folder)):
        label = (
            _bounded_json_object(
                settlement_binding[2],
                description=f"settlement label for {folder.name}",
            )
            if settlement_binding is not None
            else None
        )
    if not isinstance(label, dict):
        raise BoundedCandidateReplayError(
            f"preselection folder has no readable settlement label: {folder}"
        )
    spec = spec_for_slug(folder.name)
    settlement_unit = str(
        label.get("settlement_unit")
        or getattr(spec, "display_unit", None)
        or ""
    ).strip()
    if not settlement_unit:
        raise BoundedCandidateReplayError(
            f"preselection settlement unit is missing: {folder}"
        )
    feature_quality = audit_folder_feature_quality_from_rows(
        folder,
        feature_rows=(features_binding[2] if features_binding is not None else ()),
        snapshot_rows=frame.to_dict(orient="records"),
        replay_records=records,
        settlement_unit=settlement_unit,
    )

    changed = (
        not _bounded_preselection_file_unchanged(
            tape_path,
            expected_sha256=tape_sha256,
            max_bytes=_PRESELECTION_MAX_TAPE_BYTES,
            description="preselection tape",
        )
        or not _bounded_preselection_file_unchanged(
            replay_path,
            expected_sha256=replay_sha256,
            max_bytes=_PRESELECTION_MAX_REPLAY_BYTES,
            description="preselection replay",
        )
        or (
            features_binding is not None
            and not _bounded_preselection_file_unchanged(
                features_binding[0],
                expected_sha256=features_binding[1],
                max_bytes=_PRESELECTION_MAX_TAPE_BYTES,
                description="preselection auxiliary CSV",
            )
        )
        or (
            settlement_binding is not None
            and not _bounded_preselection_file_unchanged(
                settlement_binding[0],
                expected_sha256=settlement_binding[1],
                max_bytes=_PRESELECTION_MAX_SETTLEMENT_BYTES,
                description="preselection auxiliary file",
            )
        )
    )
    if changed:
        raise BoundedCandidateReplayError(
            f"preselection folder changed during manifest construction: {folder}"
        )
    return {
        "label": label,
        "frame": frame,
        "records": records,
        "feature_quality": feature_quality,
    }


def _bounded_preselection_label_hash(entry):
    basis = {
        key: entry.get(key)
        for key in (
            "event_slug",
            "market_id",
            "target_date",
            "settlement_bucket",
            "settlement_unit",
            "settlement_source",
            "quality_grade",
            "winning_band",
        )
    }
    encoded = json.dumps(
        basis,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _bounded_captured_times(row):
    captured_local = str(
        (row or {}).get("captured_at_local")
        or (row or {}).get("captured_at_utc")
        or ""
    ).strip()
    if not captured_local:
        raise BoundedCandidateReplayError(
            "candidate replay row is missing its captured timestamp"
        )
    normalized = captured_local[:-1] + "+00:00" if captured_local.endswith("Z") else captured_local
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise BoundedCandidateReplayError(
            f"candidate replay captured timestamp is invalid: {captured_local!r}"
        ) from exc
    if parsed.tzinfo is None:
        raise BoundedCandidateReplayError(
            "candidate replay captured timestamp must include a timezone"
        )
    return captured_local, parsed.astimezone(timezone.utc).isoformat()


def _bounded_preselection_source_row(
    row,
    *,
    entry,
    pinned_snapshot_ids,
):
    """Project one manifest-pinned replay row without candidate output.

    This is the population source used before a production candidate exists.
    It intentionally contains no model, variant, release, probability, or
    runtime identity.  The later candidate replay must reproduce the same
    coordinate, prediction boundary, and settlement label.
    """

    target_date = _bounded_locked_date(row.get("target_date"))
    market_id = _bounded_required_identity(row.get("market_id"), "row market_id")
    if (
        target_date != str(entry.get("target_date"))
        or market_id != str(entry.get("market_id"))
    ):
        raise BoundedCandidateReplayError(
            "preselection replay row escaped its manifest-pinned market-day"
        )
    snapshot_id = _bounded_required_identity(
        row.get("snapshot_id"), "row snapshot_id"
    )
    if snapshot_id not in pinned_snapshot_ids:
        raise BoundedCandidateReplayError(
            f"preselection replay snapshot {snapshot_id!r} is not manifest-pinned"
        )
    band = _bounded_required_identity(row.get("band"), "row band")
    label = _bounded_optional_float(row.get("outcome"), "outcome")
    if label not in {0.0, 1.0}:
        raise BoundedCandidateReplayError(
            "preselection replay requires a binary settled outcome"
        )
    row_settlement = _bounded_optional_float(
        row.get("settlement_bucket"), "row settlement_bucket"
    )
    entry_settlement = _bounded_optional_float(
        entry.get("settlement_bucket"), "manifest settlement_bucket"
    )
    if row_settlement != entry_settlement:
        raise BoundedCandidateReplayError(
            "preselection replay settlement does not match the pinned manifest label"
        )
    _captured_local, captured_utc = _bounded_captured_times(row)
    if abs(
        (
            datetime.fromisoformat(captured_utc).date()
            - date.fromisoformat(target_date)
        ).days
    ) > 1:
        raise BoundedCandidateReplayError(
            "preselection capture timestamp is implausible for its target date"
        )
    _bounded_manifest_snapshot_hash(entry, "replay_record_hashes", snapshot_id)
    _bounded_manifest_snapshot_hash(entry, "tape_row_hashes", snapshot_id)
    _bounded_expected_sha256(entry.get("label_hash"), "manifest label_hash")
    label_quality = str(entry.get("quality_grade") or "").strip().lower()
    if (
        label_quality not in {"complete", "manual_override"}
        or entry.get("admitted_by") != "quality_grade"
    ):
        raise BoundedCandidateReplayError(
            "production preselection requires a complete or manual_override "
            "manifest label admitted by quality grade"
        )
    return {
        "target_date": target_date,
        "market_id": market_id,
        "cutoff_or_snapshot": snapshot_id,
        "band": band,
        "feature_available_at_utc": captured_utc,
        "prediction_boundary_at_utc": captured_utc,
        "label_quality": label_quality,
        "countable": True,
        "claim_lane": "weather_only",
        "source_quality": "healthy",
        "label": label,
    }


def iter_bounded_preselection_source_market_days(
    *,
    corpus_manifest_path,
    expected_manifest_sha256,
    snapshots_root,
    max_market_days,
    max_rows_per_market_day,
):
    """Yield candidate-independent, manifest-pinned rows one market-day at a time."""

    expected_manifest_sha256 = _bounded_expected_sha256(
        expected_manifest_sha256, "expected_manifest_sha256"
    )
    max_market_days = _bounded_positive_int(max_market_days, "max_market_days")
    max_rows_per_market_day = _bounded_positive_int(
        max_rows_per_market_day, "max_rows_per_market_day"
    )
    if (
        max_market_days > _PRESELECTION_MAX_MARKET_DAYS
        or max_rows_per_market_day > _PRESELECTION_MAX_ROWS_PER_MARKET_DAY
    ):
        raise BoundedCandidateReplayError(
            "production preselection bounds exceed the reviewed maximum"
        )
    snapshots_root = Path(snapshots_root).resolve(strict=True)
    manifest_path, _manifest_raw, manifest_sha256 = _bounded_preselection_file_bytes(
        corpus_manifest_path,
        max_bytes=_PRESELECTION_MAX_REPLAY_MANIFEST_BYTES,
        description="promotion corpus manifest",
    )
    if manifest_sha256 != expected_manifest_sha256:
        raise BoundedCandidateReplayError(
            "promotion corpus manifest SHA-256 does not match the explicit lock"
        )
    manifest = load_manifest(
        manifest_path,
        max_bytes=_PRESELECTION_MAX_REPLAY_MANIFEST_BYTES,
    )
    if not _bounded_preselection_file_unchanged(
        manifest_path,
        expected_sha256=manifest_sha256,
        max_bytes=_PRESELECTION_MAX_REPLAY_MANIFEST_BYTES,
        description="promotion corpus manifest",
    ):
        raise BoundedCandidateReplayError(
            "promotion corpus manifest changed during bounded validation"
        )
    if manifest.get("include_reconstructed") is not False:
        raise BoundedCandidateReplayError(
            "production preselection requires include_reconstructed=false; "
            "reconstructed replay inputs are not allowed"
        )
    if manifest.get("allow_unsettled") is not False:
        raise BoundedCandidateReplayError(
            "production preselection requires allow_unsettled=false; "
            "unsettled replay inputs are not allowed"
        )
    if manifest.get("admit_promotion_countable") is not False:
        raise BoundedCandidateReplayError(
            "production preselection requires admit_promotion_countable=false "
            "and quality-grade admission"
        )
    try:
        as_of = date.fromisoformat(str(manifest.get("as_of") or ""))
    except ValueError as exc:
        raise BoundedCandidateReplayError(
            "production preselection replay manifest has no valid as_of date"
        ) from exc
    fleet_dates = sorted(
        {
            _bounded_locked_date(entry.get("target_date"))
            for entry in manifest.get("entries") or ()
        }
    )
    selected = _bounded_locked_manifest_entries(
        manifest,
        snapshots_root=snapshots_root,
        locked_dates=fleet_dates,
        locked_folders=(),
        max_market_days=max_market_days,
        max_rows_per_market_day=max_rows_per_market_day,
    )
    for entry, folder in selected:
        folder = Path(folder).resolve(strict=True)
        try:
            folder.relative_to(snapshots_root)
        except ValueError as exc:
            raise BoundedCandidateReplayError(
                f"manifest-pinned folder is outside the snapshots root: {folder}"
            ) from exc
        if date.fromisoformat(str(entry.get("target_date") or "")) >= as_of:
            raise BoundedCandidateReplayError(
                f"manifest contains an unsettled market-day: {entry['event_slug']}"
            )
        if _bounded_preselection_label_hash(entry) != str(
            entry.get("label_hash") or ""
        ):
            raise BoundedCandidateReplayError(
                f"manifest label hash is invalid for {entry['event_slug']}"
            )
        tape_path = folder / "snapshots_long.csv"
        replay_path = folder / "replay_inputs.jsonl"
        if not tape_path.is_file() or not replay_path.is_file():
            raise BoundedCandidateReplayError(
                f"preselection source files are missing for {entry['event_slug']}"
            )
        pinned_snapshot_ids = frozenset(
            str(item) for item in entry.get("snapshot_ids") or ()
        )
        tape_path, tape_sha256, _tape_rows, frame = _bounded_preselection_tape(
            tape_path,
            max_rows=max_rows_per_market_day,
        )
        _require_preselection_folder_file(tape_path, folder=folder)
        replay_path, replay_sha256, records = _bounded_preselection_replay_records(
            replay_path,
            pinned_snapshot_ids=pinned_snapshot_ids,
            max_records=max_rows_per_market_day,
        )
        _require_preselection_folder_file(replay_path, folder=folder)
        warnings = verify_entry_inputs(entry, folder, frame, records)
        if warnings:
            raise BoundedCandidateReplayError(
                "manifest-pinned captured inputs changed: "
                + "; ".join(map(str, warnings))
            )
        if any(
            is_reconstructed(records.get(snapshot_id) or {})
            for snapshot_id in pinned_snapshot_ids
        ):
            raise BoundedCandidateReplayError(
                "production preselection cannot use reconstructed replay inputs"
            )
        if "snapshot_id" not in frame:
            raise BoundedCandidateReplayError(
                f"snapshot_id is missing from {entry['event_slug']} tape"
            )
        pinned_frame = frame[
            frame["snapshot_id"].astype(str).isin(pinned_snapshot_ids)
        ]
        expected_rows = _bounded_positive_int(
            entry.get("row_count"), f"manifest row_count for {entry['event_slug']}"
        )
        if pinned_frame.empty or len(pinned_frame) != expected_rows:
            raise BoundedCandidateReplayError(
                f"preselection tape row count changed for {entry['event_slug']}: "
                f"{len(pinned_frame)} != {expected_rows}"
            )
        rows = []
        for band_series in pinned_frame.itertuples(index=False):
            band = band_series._asdict()
            explicit_value_hi = band.get("bin_value_hi_c")
            if explicit_value_hi in (None, "") or pd.isna(explicit_value_hi):
                explicit_value_hi = band.get("bin_value_hi")
            value_hi = band_value_hi(
                band.get("range_label"),
                band.get("bin_value_c"),
                explicit=explicit_value_hi,
            )
            outcome = resolve_outcome(
                band.get("bin_kind"),
                band.get("bin_value_c"),
                entry.get("settlement_bucket"),
                value_hi=value_hi,
            )
            if outcome not in {0, 1}:
                raise BoundedCandidateReplayError(
                    f"preselection band cannot be settled for {entry['event_slug']}"
                )
            rows.append(
                {
                    "target_date": entry.get("target_date"),
                    "market_id": entry.get("market_id"),
                    "snapshot_id": band.get("snapshot_id"),
                    "band": band.get("range_label"),
                    "captured_at_local": band.get("captured_at_local"),
                    "outcome": outcome,
                    "settlement_bucket": entry.get("settlement_bucket"),
                }
            )
        rows.sort(key=_candidate_replay_row_identity)
        seen_coordinates = set()
        winner_counts = Counter()
        for index, row in enumerate(rows):
            canonical = _bounded_preselection_source_row(
                row,
                entry=entry,
                pinned_snapshot_ids=pinned_snapshot_ids,
            )
            coordinate = (
                canonical["target_date"],
                canonical["market_id"],
                canonical["cutoff_or_snapshot"],
                canonical["band"],
            )
            if coordinate in seen_coordinates:
                raise BoundedCandidateReplayError(
                    f"duplicate preselection coordinate for {entry['event_slug']}: "
                    f"{coordinate}"
                )
            seen_coordinates.add(coordinate)
            winner_counts[canonical["cutoff_or_snapshot"]] += int(
                canonical["label"]
            )
            rows[index] = canonical
        if set(winner_counts) != set(pinned_snapshot_ids) or any(
            count != 1 for count in winner_counts.values()
        ):
            raise BoundedCandidateReplayError(
                f"preselection bands do not have exactly one winner per snapshot "
                f"for {entry['event_slug']}"
            )
        if (
            not _bounded_preselection_file_unchanged(
                tape_path,
                expected_sha256=tape_sha256,
                max_bytes=_PRESELECTION_MAX_TAPE_BYTES,
                description="preselection tape",
            )
            or not _bounded_preselection_file_unchanged(
                replay_path,
                expected_sha256=replay_sha256,
                max_bytes=_PRESELECTION_MAX_REPLAY_BYTES,
                description="preselection replay",
            )
        ):
            raise BoundedCandidateReplayError(
                f"preselection source changed during read for {entry['event_slug']}"
            )
        del frame, pinned_frame, records, warnings, seen_coordinates, winner_counts
        row = None
        yield rows
        rows = None

    if not _bounded_preselection_file_unchanged(
        manifest_path,
        expected_sha256=expected_manifest_sha256,
        max_bytes=_PRESELECTION_MAX_REPLAY_MANIFEST_BYTES,
        description="promotion corpus manifest",
    ):
        raise BoundedCandidateReplayError(
            "promotion corpus manifest changed while preselection replay was running"
        )


def _bounded_canonical_candidate_row(
    row,
    *,
    entry,
    pinned_snapshot_ids,
    folder,
    manifest,
    manifest_path,
    manifest_sha256,
    artifact,
    artifact_sha256,
    candidate_id,
    release_id,
    replayed_at_utc,
):
    target_date = _bounded_locked_date(row.get("target_date"))
    market_id = _bounded_required_identity(row.get("market_id"), "row market_id")
    if (
        target_date != str(entry.get("target_date"))
        or market_id != str(entry.get("market_id"))
    ):
        raise BoundedCandidateReplayError(
            "candidate replay row escaped its manifest-pinned market-day"
        )
    snapshot_id = _bounded_required_identity(
        row.get("snapshot_id"), "row snapshot_id"
    )
    if snapshot_id not in pinned_snapshot_ids:
        raise BoundedCandidateReplayError(
            f"candidate replay snapshot {snapshot_id!r} is not manifest-pinned"
        )
    band = _bounded_required_identity(row.get("band"), "row band")
    probability = _bounded_optional_float(row.get("candidate_p"), "candidate_p")
    if probability is None or not 0.0 <= probability <= 1.0:
        raise BoundedCandidateReplayError(
            "every bounded candidate replay row requires a probability in [0, 1]"
        )
    label = _bounded_optional_float(row.get("outcome"), "outcome")
    if label not in {0.0, 1.0}:
        raise BoundedCandidateReplayError(
            "settled outcome must be binary and joined after prediction"
        )
    row_settlement = _bounded_optional_float(
        row.get("settlement_bucket"), "row settlement_bucket"
    )
    entry_settlement = _bounded_optional_float(
        entry.get("settlement_bucket"), "manifest settlement_bucket"
    )
    if row_settlement != entry_settlement:
        raise BoundedCandidateReplayError(
            "candidate replay settlement does not match the pinned manifest label"
        )
    captured_local, captured_utc = _bounded_captured_times(row)
    replay_record_sha256 = _bounded_manifest_snapshot_hash(
        entry, "replay_record_hashes", snapshot_id
    )
    tape_rows_sha256 = _bounded_manifest_snapshot_hash(
        entry, "tape_row_hashes", snapshot_id
    )
    label_sha256 = _bounded_expected_sha256(
        entry.get("label_hash"), "manifest label_hash"
    )
    label_quality = str(entry.get("quality_grade") or "").strip().lower()
    if (
        label_quality not in {"complete", "manual_override"}
        or entry.get("admitted_by") not in {None, "quality_grade"}
    ):
        raise BoundedCandidateReplayError(
            "production candidate replay requires a complete or manual_override "
            "manifest label admitted by quality grade"
        )
    source_integrity = {
        "manifest_pinned": True,
        "snapshot_pinned": True,
        "replay_record_hash_verified": True,
        "snapshot_tape_hash_verified": True,
        "feature_quality_quarantine_applied": True,
    }
    lineage = {
        "source_mode": "promotion_manifest_pinned_captured_replay",
        "manifest_path": str(manifest_path),
        "manifest_schema_version": manifest.get("schema_version"),
        "manifest_sha256": manifest_sha256,
        "corpus_hash": manifest.get("corpus_hash"),
        "event_slug": entry.get("event_slug"),
        "market_day_folder": str(folder),
        "target_date": target_date,
        "market_id": market_id,
        "snapshot_id": snapshot_id,
        "captured_at_local": captured_local,
        "captured_at_utc": captured_utc,
        "replay_record_sha256": replay_record_sha256,
        "snapshot_tape_rows_sha256": tape_rows_sha256,
        "settlement_label_sha256": label_sha256,
        "label_quality": label_quality,
        "source_integrity": source_integrity,
    }
    lineage_json = json.dumps(
        lineage,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return {
        "schema_version": BOUNDED_CANDIDATE_REPLAY_SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "candidate_artifact_sha256": artifact_sha256,
        "candidate_artifact_hash": artifact_sha256,
        "candidate_prediction_mode": "band_binary",
        "candidate_trained_at": str(artifact.get("trained_at") or ""),
        "target_date": target_date,
        "market_id": market_id,
        "cutoff_or_snapshot": snapshot_id,
        "snapshot_id": snapshot_id,
        "band": band,
        "range_label": band,
        "bin_type": str(row.get("bin_type") or ""),
        "bin_value_c": _bounded_optional_float(row.get("bin_value_c"), "bin_value_c"),
        "bin_value_hi": _bounded_optional_float(row.get("bin_value_hi"), "bin_value_hi"),
        "candidate_cutoff_hour": _bounded_optional_float(
            row.get("candidate_cutoff_hour"), "candidate_cutoff_hour"
        ),
        "feature_schema_version": str(row.get("feature_schema_version") or ""),
        "source_freshness_state": str(
            row.get("source_freshness_state") or "missing_source_status"
        ),
        "market_yes": _bounded_optional_float(row.get("market_yes"), "market_yes"),
        "market_no": _bounded_optional_float(row.get("market_no"), "market_no"),
        "recorded_p": _bounded_optional_float(row.get("recorded_p"), "recorded_p"),
        "replayed_p": _bounded_optional_float(row.get("replayed_p"), "replayed_p"),
        "prediction_probability": probability,
        "candidate_p": probability,
        "label": label,
        "outcome": int(label),
        "settlement_bucket": entry_settlement,
        "settlement_unit": str(entry.get("settlement_unit") or ""),
        "settlement_source": str(entry.get("settlement_source") or ""),
        "label_quality": label_quality,
        "countable": True,
        "claim_lane": "weather_only",
        "replay_serve_parity": "pass",
        "source_quality": "healthy",
        "source_integrity": source_integrity,
        "variant_id": candidate_id,
        "release_id": release_id,
        "runtime_identity": f"pooled_band_sha256:{artifact_sha256}",
        "captured_at_local": captured_local,
        "captured_at_utc": captured_utc,
        "feature_available_at_utc": captured_utc,
        "prediction_made_at_utc": captured_utc,
        "replayed_at_utc": replayed_at_utc,
        "source_manifest_sha256": manifest_sha256,
        "source_corpus_hash": str(manifest.get("corpus_hash") or ""),
        "source_lineage": lineage,
        "source_lineage_json": lineage_json,
        "source_provenance_json": lineage_json,
    }


def iter_bounded_pooled_band_candidate_replay_market_days(
    *,
    artifact_path,
    expected_artifact_sha256,
    candidate_id,
    corpus_manifest_path,
    expected_manifest_sha256,
    preselection_lock_path,
    expected_preselection_hash,
    expected_window_lock_id,
    snapshots_root,
    locked_dates=(),
    locked_folders=(),
    max_market_days,
    max_rows_per_market_day,
    release_id=None,
    clob_max_age_seconds=180,
):
    """Yield freshly scored, label-deferred batches one market-day at a time.

    Each yielded list owns exactly one pinned market-day.  The producer does
    not compute the next market-day until the consumer requests the next
    batch, which lets bounded writers flush and release the current batch
    before scorer state for another day is allocated.  Callers must discard
    already-consumed batches if iteration raises; the companion atomic writer
    provides that fail-closed behavior for persisted evidence.
    """

    candidate_id = _bounded_required_identity(candidate_id, "candidate_id")
    release_id = _bounded_required_identity(
        release_id or candidate_id, "release_id"
    )
    expected_artifact_sha256 = _bounded_expected_sha256(
        expected_artifact_sha256, "expected_artifact_sha256"
    )
    expected_manifest_sha256 = _bounded_expected_sha256(
        expected_manifest_sha256, "expected_manifest_sha256"
    )
    expected_preselection_hash = _bounded_expected_sha256(
        expected_preselection_hash, "expected_preselection_hash"
    )
    expected_window_lock_id = _bounded_expected_sha256(
        expected_window_lock_id, "expected_window_lock_id"
    )
    max_market_days = _bounded_positive_int(max_market_days, "max_market_days")
    max_rows_per_market_day = _bounded_positive_int(
        max_rows_per_market_day, "max_rows_per_market_day"
    )
    clob_max_age_seconds = _bounded_positive_int(
        clob_max_age_seconds, "clob_max_age_seconds"
    )

    manifest_path = Path(corpus_manifest_path).resolve()
    if not manifest_path.is_file():
        raise BoundedCandidateReplayError(
            f"promotion corpus manifest is missing: {manifest_path}"
        )
    actual_manifest_sha256 = sha256_file(manifest_path)
    if actual_manifest_sha256 != expected_manifest_sha256:
        raise BoundedCandidateReplayError(
            "promotion corpus manifest SHA-256 does not match the explicit lock"
        )
    manifest = load_manifest(manifest_path)
    artifact_path, artifact = _bounded_load_band_artifact(
        artifact_path,
        expected_artifact_sha256=expected_artifact_sha256,
        candidate_id=candidate_id,
        release_id=release_id,
    )
    from weather.calibration.pooled_training import (
        load_production_point_in_time_preselection,
        verify_pooled_point_in_time_training_evidence,
    )

    try:
        preselection = load_production_point_in_time_preselection(
            preselection_lock_path
        )
        training = verify_pooled_point_in_time_training_evidence(artifact)
    except (OSError, TypeError, ValueError) as exc:
        raise BoundedCandidateReplayError(
            f"candidate replay preselection/training evidence is invalid: {exc}"
        ) from exc
    training_lock = training.get("preselection_lock") or {}
    if (
        preselection.get("preselection_hash") != expected_preselection_hash
        or (preselection.get("window_lock") or {}).get("window_lock_id")
        != expected_window_lock_id
        or training_lock.get("preselection_hash") != expected_preselection_hash
        or training_lock.get("window_lock_id") != expected_window_lock_id
        or training_lock.get("selection_universe_sha256")
        != (preselection.get("selection_universe") or {}).get("sha256")
        or training_lock.get("locked_dates")
        != (preselection.get("window_lock") or {}).get("target_dates")
        or training_lock.get("locked_dates_used_for_selection") is not False
    ):
        raise BoundedCandidateReplayError(
            "candidate artifact is not bound to the exact production preselection lock"
        )
    source_binding = preselection.get("source") or {}
    if (
        source_binding.get("replay_manifest_sha256") != expected_manifest_sha256
        or source_binding.get("replay_corpus_hash") != manifest.get("corpus_hash")
    ):
        raise BoundedCandidateReplayError(
            "candidate replay manifest differs from the preselected source population"
        )
    if locked_folders:
        raise BoundedCandidateReplayError(
            "production candidate replay requires the preselected fleet-date universe"
        )
    replay_dates = sorted({_bounded_locked_date(value) for value in locked_dates or ()})
    expected_replay_dates = list(
        (preselection.get("selection_universe") or {}).get("fleet_dates") or ()
    )
    if replay_dates != expected_replay_dates:
        raise BoundedCandidateReplayError(
            "candidate replay dates differ from the preselected selection universe"
        )
    selected = _bounded_locked_manifest_entries(
        manifest,
        snapshots_root=snapshots_root,
        locked_dates=locked_dates,
        locked_folders=locked_folders,
        max_market_days=max_market_days,
        max_rows_per_market_day=max_rows_per_market_day,
    )
    family_unit = artifact.get("family_unit") or "F"
    args = argparse.Namespace(
        snapshots_root=str(Path(snapshots_root).resolve()),
        clob_max_age_seconds=clob_max_age_seconds,
        long_job_guard_info=None,
    )
    for entry, folder in selected:
        computed = _compute_pooled_candidate_day(
            args,
            manifest,
            folder,
            artifact,
            family_unit=family_unit,
            prediction_mode="band_binary",
            defer_settlement_join=True,
        )
        warnings = (
            (computed.get("replay_results") or {}).get("corpus_warnings") or []
        )
        if warnings:
            raise BoundedCandidateReplayError(
                "manifest-pinned captured inputs changed: " + "; ".join(map(str, warnings))
            )
        candidate_rows = computed.get("candidate_rows") or []
        if not isinstance(candidate_rows, list):
            candidate_rows = list(candidate_rows)
        if not candidate_rows:
            raise BoundedCandidateReplayError(
                f"candidate produced no rows for explicit market-day {entry['event_slug']}"
            )
        if len(candidate_rows) > max_rows_per_market_day:
            raise BoundedCandidateReplayError(
                f"candidate row bound exceeded for {entry['event_slug']}: "
                f"{len(candidate_rows)} > {max_rows_per_market_day}"
            )
        coverage = computed.get("coverage") or {}
        if int(coverage.get("missing_candidate_rows") or 0) != 0:
            raise BoundedCandidateReplayError(
                f"candidate scoring is incomplete for {entry['event_slug']}"
            )
        seen_row_identities = set()
        pinned_snapshot_ids = frozenset(
            str(item) for item in entry.get("snapshot_ids") or ()
        )
        replayed_at_utc = datetime.now(timezone.utc).isoformat()
        candidate_rows.sort(key=_candidate_replay_row_identity)
        for index, row in enumerate(candidate_rows):
            identity = _candidate_replay_row_identity(row)
            if identity in seen_row_identities:
                raise BoundedCandidateReplayError(
                    f"duplicate candidate replay row for {entry['event_slug']}: {identity}"
                )
            seen_row_identities.add(identity)
            # Replace the scorer row in place so the market-day batch never
            # retains a second full list of canonical output rows.
            candidate_rows[index] = _bounded_canonical_candidate_row(
                row,
                entry=entry,
                pinned_snapshot_ids=pinned_snapshot_ids,
                folder=folder,
                manifest=manifest,
                manifest_path=manifest_path,
                manifest_sha256=expected_manifest_sha256,
                artifact=artifact,
                artifact_sha256=expected_artifact_sha256,
                candidate_id=candidate_id,
                release_id=release_id,
                replayed_at_utc=replayed_at_utc,
            )
        # The generator frame survives while the consumer flushes this batch.
        # Drop the compute graph and its raw replay payload before yielding so
        # only this one canonical market-day remains retained by the producer.
        del computed, warnings, coverage, seen_row_identities
        row = None
        yield candidate_rows
        # Clear the producer's reference before the next scorer invocation.
        candidate_rows = None

    # Detect mutation during a long stream.  The artifact was loaded once, so
    # every prediction above used the bytes identified at entry; persisted
    # output is accepted only when both source identities remain unchanged.
    if sha256_file(artifact_path) != expected_artifact_sha256:
        raise BoundedCandidateReplayError(
            "candidate artifact changed while bounded replay was running"
        )
    if sha256_file(manifest_path) != expected_manifest_sha256:
        raise BoundedCandidateReplayError(
            "promotion corpus manifest changed while bounded replay was running"
        )


def iter_bounded_pooled_band_candidate_replay(**replay_kwargs):
    """Preserve the public row iterator over the bounded day-batch producer."""

    day_iterator = iter_bounded_pooled_band_candidate_replay_market_days(
        **replay_kwargs
    )
    for market_day_rows in day_iterator:
        yield from market_day_rows
        # Avoid retaining the completed batch while requesting the next one.
        del market_day_rows


def write_bounded_pooled_band_candidate_replay_jsonl(out_path, **replay_kwargs):
    """Atomically write canonical JSONL from the bounded replay iterator."""

    out_path = Path(out_path).resolve()
    if out_path.exists():
        raise FileExistsError(f"bounded candidate replay already exists: {out_path}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = out_path.with_name(f".{out_path.name}.{os.getpid()}.tmp")
    digest = hashlib.sha256()
    row_count = 0
    market_days = set()
    identities = None
    try:
        with temp_path.open("xb") as handle:
            for row in iter_bounded_pooled_band_candidate_replay(**replay_kwargs):
                line = (
                    json.dumps(
                        row,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                        allow_nan=False,
                    )
                    + "\n"
                ).encode("utf-8")
                handle.write(line)
                digest.update(line)
                row_count += 1
                market_days.add((row["target_date"], row["market_id"]))
                row_identities = (
                    row["candidate_id"],
                    row["candidate_artifact_sha256"],
                    row["source_manifest_sha256"],
                )
                if identities is None:
                    identities = row_identities
                elif identities != row_identities:
                    raise BoundedCandidateReplayError(
                        "candidate or source identity changed within replay output"
                    )
            if row_count <= 0:
                raise BoundedCandidateReplayError(
                    "bounded candidate replay produced no persisted rows"
                )
            handle.flush()
            os.fsync(handle.fileno())
        if out_path.exists():
            raise FileExistsError(
                f"bounded candidate replay appeared during write: {out_path}"
            )
        os.replace(temp_path, out_path)
    except Exception:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
        raise
    return {
        "schema_version": BOUNDED_CANDIDATE_REPLAY_SCHEMA_VERSION,
        "path": str(out_path),
        "sha256": digest.hexdigest(),
        "bytes": out_path.stat().st_size,
        "row_count": row_count,
        "market_day_count": len(market_days),
        "candidate_id": identities[0],
        "candidate_artifact_sha256": identities[1],
        "source_manifest_sha256": identities[2],
        "write_mode": "market_day_streaming_atomic_jsonl",
        "raw_market_days_retained_at_once": 1,
    }


def _run_replay_cache_sentinel(
    *,
    args,
    consumer,
    cache_root,
    cached_entries,
    manifest,
    artifact,
    family_unit,
    prediction_mode,
):
    selected = replay_cache.select_sentinel(cached_entries, consumer=consumer)
    if not selected:
        return {"status": "SKIPPED", "reason": "no_cached_hits"}
    fresh = _compute_pooled_candidate_day(
        args,
        manifest,
        selected["folder"],
        artifact,
        family_unit=family_unit,
        prediction_mode=prediction_mode,
    )
    cached_rows = selected["payload"].get("rows") or []
    fresh_rows = fresh["candidate_rows"]
    divergence = replay_cache.rows_divergence(cached_rows, fresh_rows)
    if (
        not divergence["structural"]
        and divergence["max_numeric_diff"] <= replay_cache.SENTINEL_NUMERIC_ABS_TOLERANCE
    ):
        return {
            "status": "PASS",
            "event_slug": selected["key"].event_slug,
            "path": selected["payload"].get("path"),
            "comparison": "tolerant",
            "abs_tolerance": replay_cache.SENTINEL_NUMERIC_ABS_TOLERANCE,
            "max_numeric_diff": divergence["max_numeric_diff"],
        }
    # The responses below destroy evidence of WHAT drifted, so persist the
    # mismatching pair first (2026-07-09: first live trip flushed 901 entries
    # and left no way to tell stale-input from nondeterminism).
    forensics_path = None
    try:
        forensics_path = str(_write_sentinel_forensics(
            consumer=consumer,
            key=selected["key"],
            cached_rows=cached_rows,
            fresh_rows=fresh_rows,
            cached_path=selected["payload"].get("path"),
        ))
    except OSError:
        pass
    if (
        not divergence["structural"]
        and divergence["max_numeric_diff"] <= replay_cache.SENTINEL_ESCALATION_ABS_DIFF
    ):
        # Noise beyond the pass tolerance but far below the input-drift
        # regime: a 5e-3 probability wobble moves Brier by ~1e-5 at most.
        # Refresh just this entry and keep the run alive — aborting promotion
        # and flushing the whole consumer over it cost three days this week.
        replay_cache.delete_entry(cache_root, selected["key"])
        return {
            "status": "WARN_REFRESHED",
            "event_slug": selected["key"].event_slug,
            "path": selected["payload"].get("path"),
            "max_numeric_diff": divergence["max_numeric_diff"],
            "abs_tolerance": replay_cache.SENTINEL_NUMERIC_ABS_TOLERANCE,
            "escalation_abs_diff": replay_cache.SENTINEL_ESCALATION_ABS_DIFF,
            "forensics": forensics_path,
        }
    flush = replay_cache.flush_consumer(cache_root, consumer)
    raise RuntimeError(
        "replay cache sentinel mismatch for "
        f"{consumer}/{selected['key'].event_slug} "
        f"(structural={divergence['structural']}, max_diff={divergence['max_numeric_diff']}); "
        f"flushed {flush.get('removed_count')} cache entries"
        + (f"; forensics: {forensics_path}" if forensics_path else "")
    )


def _write_sentinel_forensics(*, consumer, key, cached_rows, fresh_rows, cached_path):
    from weather.io import write_json_atomic
    from weather.paths import data_path

    differing = []
    for index, (cached, fresh) in enumerate(zip(cached_rows, fresh_rows)):
        if replay_cache.canonical_json(cached) != replay_cache.canonical_json(fresh):
            changed_fields = sorted(
                field
                for field in set(cached) | set(fresh)
                if replay_cache.canonical_json(cached.get(field))
                != replay_cache.canonical_json(fresh.get(field))
            )
            differing.append({
                "row_index": index,
                "changed_fields": changed_fields,
                "cached": {field: cached.get(field) for field in changed_fields},
                "fresh": {field: fresh.get(field) for field in changed_fields},
            })
        if len(differing) >= 20:
            break
    out_path = (
        data_path() / "logs"
        / f"replay_cache_sentinel_mismatch_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    write_json_atomic(out_path, {
        "consumer": consumer,
        "key": key.metadata(),
        "cached_path": cached_path,
        "cached_row_count": len(cached_rows),
        "fresh_row_count": len(fresh_rows),
        "differing_row_sample": differing,
    }, trailing_newline=True)
    return out_path


def run_pooled_candidate_replay(args):
    manifest = load_manifest(args.corpus)
    artifact = load_artifact(args.artifact)
    variant_registry = load_variant_registry(getattr(args, "variant_registry", DEFAULT_VARIANT_REGISTRY_PATH))
    registry_contract = variant_contract_for_artifact(
        variant_registry,
        args.artifact,
        prediction_function=POOLED_REPLAY_PREDICTION_FUNCTION,
    )
    artifact_hash = artifact.get("artifact_hash") or artifact_hash_for_path(args.artifact)
    prediction_mode = artifact.get("prediction_mode") or "bucket_distribution"
    family_unit = artifact.get("family_unit") or (
        "all" if prediction_mode == RESIDUAL_DISTRIBUTION_V1_MODE else "F"
    )
    default_variant_id, default_variant_family = candidate_variant_defaults(
        artifact,
        variant_registry=variant_registry,
        artifact_path=args.artifact,
    )
    candidate_variant_id = getattr(args, "candidate_variant_id", None) or default_variant_id
    candidate_variant_family = getattr(args, "candidate_variant_family", None) or default_variant_family
    candidate_variant_out = getattr(args, "candidate_variant_out", None)
    if (
        not candidate_variant_out
        and registry_contract
        and not getattr(args, "disable_candidate_variant_export", False)
    ):
        candidate_variant_out = registry_contract.get("default_export_path")
    postprocess_config_hash = (
        (registry_contract or {}).get("postprocess_config_hash")
        or artifact.get("schema_version")
        or ""
    )
    folders = [str(folder) for folder in folders_from_manifest(manifest, args.snapshots_root)]
    cache_policy = replay_cache.replay_cache_policy(getattr(args, "replay_cache", "read_write"))
    cache_root = replay_cache.cache_root_for_corpus(
        args.corpus,
        getattr(args, "replay_cache_root", None),
    )
    cache_consumer = getattr(args, "replay_cache_consumer", "") or "pooled_candidate_replay"
    config_fp = replay_cache.config_fingerprint(
        _pooled_replay_cache_config(
            args,
            manifest,
            artifact,
            prediction_mode=prediction_mode,
            family_unit=family_unit,
            registry_contract=registry_contract,
        )
    )
    candidate_rows = []
    coverage_parts = []
    diagnostic_parts = []
    replay_parts = []
    cached_hits = []
    fresh_window_cutoff = replay_cache_fresh_window_cutoff(
        getattr(args, "replay_cache_fresh_window_days", DEFAULT_REPLAY_CACHE_FRESH_WINDOW_DAYS)
    )
    cache_stats = {
        "schema_version": replay_cache.REPLAY_CACHE_SCHEMA_VERSION,
        "mode": cache_policy["mode"],
        "root": str(cache_root),
        "consumer": cache_consumer,
        "config_fp": config_fp,
        "fresh_window_cutoff": fresh_window_cutoff,
        "fresh_window_skip_count": 0,
        "hit_count": 0,
        "miss_count": 0,
        "write_count": 0,
        "write_error_count": 0,
        "sentinel": {"status": "SKIPPED", "reason": "not_run"},
    }
    for folder in folders:
        entry = entry_for_folder(manifest, folder)
        key = None
        cached = None
        if entry:
            key = replay_cache.key_for_entry(
                entry,
                consumer=cache_consumer,
                model_fp=artifact_hash,
                config_fp=config_fp,
            )
            # Sidecar stores refreshed daily (reanalysis lags 10 days) change
            # recent days' replay features without touching any folder-content
            # hash, so recent entries are recomputed fresh instead of read
            # (2026-07-09 sentinel trip: candidate_p drift on a 7-day-old day).
            if entry_in_replay_fresh_window(entry, fresh_window_cutoff):
                cache_stats["fresh_window_skip_count"] += 1
            elif cache_policy["read"]:
                cached = replay_cache.read_entry(cache_root, key)
                if cached and not isinstance(cached.get("replay_results"), dict):
                    cached = None
        if cached:
            cache_stats["hit_count"] += 1
            rows = [dict(row) for row in (cached.get("rows") or [])]
            candidate_rows.extend(rows)
            coverage_parts.append(cached.get("coverage") or {})
            diagnostic_parts.append(cached.get("diagnostics") or {})
            replay_parts.append(cached.get("replay_results") or {})
            cached_hits.append({"folder": folder, "key": key, "payload": cached})
            continue

        cache_stats["miss_count"] += 1
        computed = _compute_pooled_candidate_day(
            args,
            manifest,
            folder,
            artifact,
            family_unit=family_unit,
            prediction_mode=prediction_mode,
        )
        rows = computed["candidate_rows"]
        candidate_rows.extend(rows)
        coverage_parts.append(computed["coverage"])
        diagnostic_parts.append(computed["diagnostics"])
        replay_parts.append(computed["replay_results"])
        if key and cache_policy["write"]:
            try:
                replay_cache.write_entry(
                    cache_root,
                    key,
                    rows=rows,
                    replay_results=computed["replay_results"],
                    coverage=computed["coverage"],
                    diagnostics=computed["diagnostics"],
                    metadata={
                        "artifact_path": str(args.artifact),
                        "corpus_path": str(args.corpus),
                        "target_date": entry.get("target_date"),
                        "market_id": entry.get("market_id"),
                    },
                )
                cache_stats["write_count"] += 1
            except OSError as exc:
                cache_stats["write_error_count"] += 1
                cache_stats.setdefault("write_errors", []).append({
                    "event_slug": key.event_slug,
                    "error": str(exc),
                })
    if cache_policy["read"] and not getattr(args, "disable_replay_cache_sentinel", False):
        cache_stats["sentinel"] = _run_replay_cache_sentinel(
            args=args,
            consumer=cache_consumer,
            cache_root=cache_root,
            cached_entries=cached_hits,
            manifest=manifest,
            artifact=artifact,
            family_unit=family_unit,
            prediction_mode=prediction_mode,
        )
    replay_results = _aggregate_replay_results(
        replay_parts,
        manifest=manifest,
        include_reconstructed=manifest.get("include_reconstructed", False),
        long_job_guard_info=getattr(args, "long_job_guard_info", None),
    )
    if args.replay_report:
        write_replay_backtest_report(replay_results, args.replay_report)
    replay_gate = replay_gate_status(
        replay_results,
        max_fidelity_l1=getattr(args, "max_fidelity_l1", FIDELITY_FAITHFUL_L1),
        require_exact_identity=getattr(args, "require_exact_identity", False),
    )
    coverage = _merge_candidate_coverage(coverage_parts, family_unit)
    diagnostics = _merge_candidate_diagnostics(diagnostic_parts, family_unit)
    for row in candidate_rows:
        row["candidate_artifact_hash"] = artifact_hash
        row["candidate_cutoff_regime"] = cutoff_regime(row.get("candidate_cutoff_hour"))
        row.setdefault("forecast_source_count_bucket", "unknown")
        row.setdefault("forecast_disagreement_bucket", "unknown")
        row.setdefault("forecast_bucket_pressure", "unknown")
        row.setdefault("current_max_boundary_slice", "unknown")
        row.setdefault("marine_breeze_slice", "missing_marine_context")

    trust_rows = score_all_markets(
        root=args.snapshots_root,
        as_of=manifest.get("as_of"),
    )
    trust_by_market = {row["market"]: row for row in trust_rows}
    blocked_validation = blocked_candidate_validation_gate(
        candidate_rows,
        current_tol=args.current_tol,
        market_tol=args.market_tol,
        min_days=args.min_days,
    )
    market_rows = _per_market(candidate_rows, trust_by_market, args)
    aggregate = candidate_comparison(candidate_rows)
    daily_first = daily_first_candidate_comparison(candidate_rows)
    by_market = grouped_candidate_comparison(candidate_rows, "market_id")
    by_hour = grouped_candidate_comparison(candidate_rows, "candidate_cutoff_hour")
    by_cutoff_regime = grouped_candidate_comparison(candidate_rows, "candidate_cutoff_regime")
    by_bin_type = grouped_candidate_comparison(candidate_rows, "bin_type")
    by_settlement_distance = grouped_candidate_comparison(candidate_rows, "settlement_distance_bucket")
    by_source_freshness = grouped_candidate_comparison(candidate_rows, "source_freshness_state")
    by_forecast_source_count = grouped_candidate_comparison(candidate_rows, "forecast_source_count_bucket")
    by_forecast_disagreement = grouped_candidate_comparison(candidate_rows, "forecast_disagreement_bucket")
    by_forecast_bucket_pressure = grouped_candidate_comparison(candidate_rows, "forecast_bucket_pressure")
    by_current_max_boundary = grouped_candidate_comparison(candidate_rows, "current_max_boundary_slice")
    by_marine_breeze_slice = grouped_candidate_comparison(candidate_rows, "marine_breeze_slice")
    candidate_variant_path, candidate_variant_rows_count = write_candidate_shadow_variants(
        candidate_variant_out,
        candidate_rows,
        variant_id=candidate_variant_id,
        variant_family=candidate_variant_family,
        uses_market_features=getattr(args, "candidate_variant_uses_market_features", False),
        is_control=getattr(args, "candidate_variant_control", False),
        artifact_hash=artifact_hash,
        postprocess_config_hash=postprocess_config_hash,
        min_free_bytes=getattr(args, "min_artifact_free_bytes", 0),
    )
    candidate_shadow_variants = None
    if candidate_variant_path:
        candidate_shadow_variants = {
            "path": candidate_variant_path,
            "rows": candidate_variant_rows_count,
            "variant_id": candidate_variant_id,
            "variant_family": candidate_variant_family,
            "uses_market_features": bool(getattr(args, "candidate_variant_uses_market_features", False)),
            "is_control": bool(getattr(args, "candidate_variant_control", False)),
            "registry_contract": bool(registry_contract),
        }
    postprocess = artifact.get("postprocess") or {}
    exact_winner_diagnostics = None
    if (
        postprocess.get("exact_winner_catchup_enabled")
        or "exact_winner" in str(candidate_variant_family)
    ):
        exact_winner_diagnostics = exact_winner_candidate_diagnostics(candidate_rows)
    heavy_carry = _load_heavy_diagnostics_carry(args, artifact_hash)
    if heavy_carry is not None:
        microstructure = heavy_carry.get("microstructure")
        source_state_ablation = heavy_carry.get("source_state_ablation")
        conservative_bridge = heavy_carry.get("conservative_bridge")
    else:
        microstructure = None
        if not getattr(args, "skip_microstructure_overlay", False):
            microstructure = microstructure_shadow_report(
                candidate_rows,
                casebook_path=getattr(args, "casebook", DEFAULT_CASEBOOK),
                artifact_path=getattr(args, "microstructure_artifact", DEFAULT_MICROSTRUCTURE_ARTIFACT),
                min_train_rows=getattr(args, "microstructure_min_train_rows", 500),
                variant_out_path=getattr(args, "microstructure_variant_out", DEFAULT_MICROSTRUCTURE_VARIANT_OUT),
                candidate_artifact_hash=artifact_hash,
                min_free_bytes=getattr(args, "min_artifact_free_bytes", 0),
            )
        source_state_ablation = source_state_ablation_report(
            candidate_rows,
            artifact,
            candidate_artifact_hash=artifact_hash,
            variant_out_path=getattr(args, "source_state_ablation_variant_out", DEFAULT_SOURCE_STATE_ABLATION_VARIANT_OUT),
            min_free_bytes=getattr(args, "min_artifact_free_bytes", 0),
        )
        conservative_bridge = conservative_bridge_report(
            candidate_rows,
            variant_out_path=getattr(args, "bridge_variant_out", DEFAULT_BRIDGE_VARIANT_OUT),
            min_free_bytes=getattr(args, "min_artifact_free_bytes", 0),
        )
        _write_heavy_diagnostics_manifest(args, artifact_hash, {
            "microstructure": microstructure,
            "source_state_ablation": source_state_ablation,
            "conservative_bridge": conservative_bridge,
        })
    candidate_market_verdict = overall_verdict(market_rows, require_all_markets=args.require_all_markets)
    verdict = candidate_market_verdict if replay_gate["global_ok"] and blocked_validation.get("passed") else "BLOCK"
    adjacent_calibration = postprocess.get("adjacent_calibration") or {}
    market_bias_calibration = postprocess.get("market_bias_calibration") or {}
    market_bias_selection = market_bias_calibration.get("selection") or {}
    density_postprocess = artifact.get("density_postprocess") or {}
    density_postprocess_selection = density_postprocess.get("selection") or {}
    density_forecast_relative = density_postprocess.get("forecast_relative_calibration") or {}
    sidecar_eligibility = sidecar_eligibility_summary_from_audit(
        getattr(args, "data_layer_audit", DEFAULT_DATA_LAYER_AUDIT),
        candidate_variant_id=candidate_variant_id,
        candidate_variant_family=candidate_variant_family,
    )

    report = {
        "generated_at": datetime.now().isoformat(),
        "verdict": verdict,
        "candidate_market_verdict": candidate_market_verdict,
        "cutover_decision": cutover_decision(verdict),
        "artifact": {
            "path": str(args.artifact),
            "artifact_hash": artifact_hash,
            "schema_version": artifact.get("schema_version"),
            "feature_schema_version": artifact.get("feature_schema_version"),
            "family_unit": family_unit,
            "prediction_mode": prediction_mode,
            "objective": artifact.get("objective"),
            "feature_subset": artifact.get("feature_subset"),
            "feature_subset_contract": artifact.get("feature_subset_contract") or {},
            "feature_names": sorted(_artifact_feature_names(artifact)),
            "forecast_profile_calibration": artifact.get("forecast_profile_calibration") or {},
            "forecast_radiation_calibration": artifact.get("forecast_radiation_calibration") or {},
            "marine_contrast_calibration": artifact.get("marine_contrast_calibration") or {},
            "trained_at": artifact.get("trained_at"),
            "support_min": min(artifact.get("support") or []) if artifact.get("support") else None,
            "support_max": max(artifact.get("support") or []) if artifact.get("support") else None,
            "hour_models": sorted(int(hour) for hour in (artifact.get("models") or {})),
            "adjacent_calibration_contexts": adjacent_calibration.get("context_count"),
            "density_postprocess": {
                "schema_version": density_postprocess.get("schema_version"),
                "enabled": bool(density_postprocess.get("enabled")),
                "policy_id": density_postprocess.get("policy_id"),
                "calibration_rows": density_postprocess.get("calibration_rows", 0),
                "baseline_market_band_brier": density_postprocess_selection.get("baseline_market_band_brier"),
                "selected_market_band_brier": density_postprocess_selection.get("selected_market_band_brier"),
                "adjacent_contexts": (density_postprocess.get("adjacent_calibration") or {}).get("context_count", 0),
                "exact_winner_contexts": (density_postprocess.get("exact_winner_catchup") or {}).get("context_count", 0),
                "exact_winner_strength": (density_postprocess.get("exact_winner_catchup") or {}).get("strength"),
                "forecast_relative_calibration_enabled": bool(
                    density_postprocess.get("forecast_relative_calibration_enabled")
                ),
                "forecast_relative_contexts": density_forecast_relative.get("context_count", 0),
                "forecast_relative_strength": density_forecast_relative.get("strength"),
            },
            "current_blend_default_alpha": postprocess.get("current_blend_default_alpha"),
            "current_blend_market_alpha": postprocess.get("current_blend_market_alpha") or {},
            "current_blend_source_freshness_default_alpha": (
                postprocess.get("current_blend_source_freshness_default_alpha")
            ),
            "current_blend_source_freshness_alpha": (
                postprocess.get("current_blend_source_freshness_alpha") or {}
            ),
            "current_blend_context_alpha": postprocess.get("current_blend_context_alpha") or [],
            "market_bias_calibration_enabled": bool(postprocess.get("market_bias_calibration_enabled")),
            "market_bias_calibration_contexts": market_bias_calibration.get("context_count", 0),
            "market_bias_baseline_brier": market_bias_selection.get("baseline_brier"),
            "market_bias_candidate_brier": market_bias_selection.get("candidate_brier"),
            "market_bias_delta_brier": market_bias_selection.get("delta_brier"),
            "market_bias_excluded_markets": market_bias_calibration.get("excluded_markets") or [],
            "market_bias_allowed_source_freshness_states": (
                market_bias_calibration.get("allowed_source_freshness_states") or []
            ),
            "forecast_centering_enabled": bool(postprocess.get("forecast_centering_enabled")),
            "forecast_centering_sigma": postprocess.get("forecast_centering_sigma"),
            "forecast_centering_default_alpha": postprocess.get("forecast_centering_default_alpha"),
            "forecast_centering_early_alpha": postprocess.get("forecast_centering_early_alpha"),
            "forecast_centering_alpha_by_hour": postprocess.get("forecast_centering_alpha_by_hour") or {},
            "blocked_validation": {
                "schema_version": blocked_validation.get("schema_version"),
                "split_mode": blocked_validation.get("split_mode"),
                "verdict": blocked_validation.get("verdict"),
            },
        },
        "corpus": _manifest_summary(manifest),
        "coverage": coverage,
        "sidecar_eligibility": sidecar_eligibility,
        "diagnostics": diagnostics,
        "replay_cache": cache_stats,
        "replay_gate": replay_gate,
        "blocked_validation": blocked_validation,
        "aggregate": aggregate,
        "daily_first": daily_first,
        "market_rows": market_rows,
        "by_market": by_market,
        "by_hour": by_hour,
        "by_cutoff_regime": by_cutoff_regime,
        "by_bin_type": by_bin_type,
        "by_settlement_distance": by_settlement_distance,
        "by_source_freshness": by_source_freshness,
        "by_forecast_source_count": by_forecast_source_count,
        "by_forecast_disagreement": by_forecast_disagreement,
        "by_forecast_bucket_pressure": by_forecast_bucket_pressure,
        "by_current_max_boundary": by_current_max_boundary,
        "by_marine_breeze_slice": by_marine_breeze_slice,
        "forecast_profile_guardrails": forecast_profile_guardrails(candidate_rows),
        "candidate_shadow_variants": candidate_shadow_variants,
        "active_registry_contract": registry_contract or {},
        "exact_winner_diagnostics": exact_winner_diagnostics,
        "microstructure": microstructure,
        "source_state_ablation": source_state_ablation,
        "conservative_bridge": conservative_bridge,
        "replay_summary": {
            "snaps_scored": replay_results.get("snaps_scored"),
            "total_rows": replay_results.get("total_rows"),
            "fidelity": replay_results.get("fidelity") or {},
            "corpus_warnings": replay_results.get("corpus_warnings") or [],
        },
        "long_job_guard": getattr(args, "long_job_guard_info", None) or {},
    }
    write_report(
        report,
        args.out,
        min_free_bytes=getattr(args, "min_artifact_free_bytes", 0),
    )
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(report, indent=2, sort_keys=True)
        ensure_artifact_disk_headroom(
            args.json_out,
            estimated_bytes=len(text.encode("utf-8")),
            min_free_bytes=getattr(args, "min_artifact_free_bytes", 0),
            context="pooled candidate JSON report export",
        )
        Path(args.json_out).write_text(text, encoding="utf-8")
    return report

from weather.calibration.pooled_candidate_replay_report import write_report  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Replay-score the pooled F-family candidate as a shadow model.")
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--artifact", default=str(DEFAULT_BAND_ARTIFACT))
    parser.add_argument("--variant-registry", default=str(DEFAULT_VARIANT_REGISTRY_PATH))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--replay-report", default=str(DEFAULT_REPLAY_REPORT),
                        help="Current-serving replay report path. Empty string disables it.")
    parser.add_argument("--data-layer-audit", default=str(DEFAULT_DATA_LAYER_AUDIT),
                        help="Data-layer audit JSON used to annotate sidecar eligibility coverage.")
    parser.add_argument(
        "--replay-cache",
        default="read_write",
        choices=["read_write", "write_only", "off"],
        help="Per-market-day replay cache mode. Use off for the historical full recompute behavior.",
    )
    parser.add_argument(
        "--replay-cache-root",
        default="",
        help="Replay cache root. Defaults to <corpus parent>/replay_cache.",
    )
    parser.add_argument(
        "--disable-replay-cache-sentinel",
        action="store_true",
        help="Skip the one-hit re-replay determinism sentinel for this run.",
    )
    parser.add_argument(
        "--replay-cache-fresh-window-days",
        type=int,
        default=DEFAULT_REPLAY_CACHE_FRESH_WINDOW_DAYS,
        help=(
            "Recompute (never cache-read) market-days newer than this many days; "
            "sized past the reanalysis recent-refresh lag so daily sidecar rewrites "
            "cannot serve stale cached predictions."
        ),
    )
    parser.add_argument("--current-tol", type=float, default=0.003,
                        help="Hard-block tolerance for candidate Brier regression vs current replay.")
    parser.add_argument("--market-tol", type=float, default=0.003,
                        help="Shadow threshold for candidate Brier gap versus Polymarket.")
    parser.add_argument("--min-days", type=int, default=2)
    parser.add_argument("--min-trust", type=int, default=25)
    parser.add_argument("--max-fidelity-l1", type=float, default=FIDELITY_FAITHFUL_L1)
    parser.add_argument("--clob-max-age-seconds", type=float, default=180.0)
    parser.add_argument("--casebook", default=str(DEFAULT_CASEBOOK),
                        help="Disagreement casebook JSON used to score Item 38 target slices.")
    parser.add_argument("--candidate-variant-out", default=None,
                        help="Item-69-compatible candidate variant CSV. Defaults to the active registry contract when available.")
    parser.add_argument("--candidate-variant-id", default=None)
    parser.add_argument("--candidate-variant-family", default=None)
    parser.add_argument("--candidate-variant-uses-market-features", action="store_true")
    parser.add_argument("--candidate-variant-control", action="store_true")
    parser.add_argument("--disable-candidate-variant-export", action="store_true",
                        help="Disable registry-default candidate variant export.")
    parser.add_argument("--min-artifact-free-bytes", type=int, default=DEFAULT_VARIANT_EXPORT_MIN_FREE_BYTES,
                        help="Require this much free disk headroom after estimated variant CSV exports. Use 0 to disable.")
    parser.add_argument("--microstructure-artifact", default=str(DEFAULT_MICROSTRUCTURE_ARTIFACT),
                        help="Shadow CLOB overlay artifact path. Empty string disables artifact writing.")
    parser.add_argument("--microstructure-variant-out", default=str(DEFAULT_MICROSTRUCTURE_VARIANT_OUT),
                        help="Item-69-compatible CLOB overlay variant CSV. Empty string disables variant export.")
    parser.add_argument("--microstructure-min-train-rows", type=int, default=500,
                        help="Minimum rows required for each out-of-fold CLOB overlay train fold.")
    parser.add_argument("--skip-microstructure-overlay", action="store_true",
                        help="Disable the non-serving Item 38 CLOB overlay score.")
    parser.add_argument("--source-state-ablation-variant-out", default=str(DEFAULT_SOURCE_STATE_ABLATION_VARIANT_OUT),
                        help="Item-69-compatible source-state ablation variant CSV. Empty string disables variant export.")
    parser.add_argument("--bridge-variant-out", default=str(DEFAULT_BRIDGE_VARIANT_OUT),
                        help="Item-69-compatible conservative bridge variant CSV. Empty string disables variant export.")
    parser.add_argument("--require-exact-identity", action="store_true",
                        help="Fail the candidate promotion gate if the corpus has no exact replay-identity canary rows.")
    parser.add_argument("--require-all-markets", action="store_true")
    parser.add_argument("--fail-on-block", action="store_true",
                        help="Exit nonzero when the candidate is blocked.")
    parser.add_argument("--long-job-state", default=str(DEFAULT_LONG_JOB_STATE_PATH))
    parser.add_argument("--long-job-lock", default=str(DEFAULT_LONG_JOB_LOCK_PATH))
    parser.add_argument("--long-job-priority", default="below_normal", choices=["normal", "below_normal", "idle"])
    parser.add_argument("--disable-long-job-guard", action="store_true")
    parser.add_argument("--force-long-job-lock", action="store_true")
    args = parser.parse_args()
    if args.replay_report == "":
        args.replay_report = None
    if args.json_out == "":
        args.json_out = None
    if args.candidate_variant_out == "":
        args.candidate_variant_out = None
    if args.microstructure_artifact == "":
        args.microstructure_artifact = None
    if args.microstructure_variant_out == "":
        args.microstructure_variant_out = None
    if args.source_state_ablation_variant_out == "":
        args.source_state_ablation_variant_out = None
    if args.bridge_variant_out == "":
        args.bridge_variant_out = None
    if args.replay_cache_root == "":
        args.replay_cache_root = None

    with long_job_guard(
        "pooled_candidate_replay",
        state_path=args.long_job_state,
        lock_path=args.long_job_lock,
        priority=args.long_job_priority,
        enabled=not args.disable_long_job_guard,
        force_lock=args.force_long_job_lock,
    ) as guard:
        args.long_job_guard_info = guard
        report = run_pooled_candidate_replay(args)
    print(f"Pooled candidate replay: {report['verdict']} ({report['cutover_decision']})")
    print(f"Report written to {args.out}")
    if args.json_out:
        print(f"JSON written to {args.json_out}")
    if args.replay_report:
        print(f"Current replay report written to {args.replay_report}")
    if args.fail_on_block and report["verdict"] == "BLOCK":
        sys.exit(1)


if __name__ == "__main__":
    main()
