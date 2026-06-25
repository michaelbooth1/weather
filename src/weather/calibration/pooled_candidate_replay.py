"""Shadow replay for the pooled F-family feature-model candidate.

This is the cutover guard for Roadmap item 33. It replays the pinned promotion
corpus with the current serving model, then scores the separate pooled-F
artifact against the same settled rows as a shadow candidate. Live serving is
not changed by this module.
"""
import argparse
import bisect
import csv
import hashlib
import json
import math
import pickle
import sys
from collections import Counter, defaultdict
from datetime import datetime
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
from weather.model.variant_prediction_runtime import apply_continuous_density_calibration
from weather.reporting.location_analysis.location_trust import score_all_markets
from weather.market.market_microstructure_features import (
    CLOB_MODEL_FEATURE_COLUMNS,
    feature_index_for_folder,
    snapshot_band_key,
)
from weather.market.market_registry import REGISTRY
from weather.model.continuous_density import (
    band_probability_from_distribution as density_band_probability_from_distribution,
    bucket_interval_native,
    density_f_from_payload,
    native_interval_to_f,
    normalize_density,
)
from weather.calibration.pooled_feature_model import (
    DEFAULT_BAND_ARTIFACT,
    FEATURE_SUBSET_FORECAST_PROFILE,
    add_dynamic_source_state_features,
    add_city_features,
    apply_adjacent_calibration,
    apply_band_postprocessing,
    apply_exact_winner_catchup,
    apply_forecast_relative_density_calibration,
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
)
from weather.backtesting.replay import (
    index_records_by_snapshot,
    is_reconstructed,
    load_replay_records,
    parse_built_at,
    record_target_date,
    source_freshness_group,
)
from weather.backtesting.replay_backtest import FIDELITY_FAITHFUL_L1, run_replay_backtest
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


def _climate_for_market(climates, model, market_id):
    if market_id not in climates:
        climates[market_id] = market_climate_stats(model.historical_target_cache())
    return climates[market_id]


def _source_reliability_for_market(source_reliability, spec):
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
    reanalysis_promotion_lane = _artifact_reanalysis_lane(artifact)
    needs_reanalysis = _artifact_needs_reanalysis(artifact)
    needs_marine_water_contrast = _artifact_needs_marine_water_contrast(artifact)
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
        climate = _climate_for_market(climates, model, market_id)
        reliability = _source_reliability_for_market(source_reliability, spec)
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
            group = source_freshness_group(record)
            output[(market_id, str(snapshot_id))] = group
            counts[group] += 1
    diagnostics["source_freshness_snapshots"] = len(output)
    diagnostics["source_freshness_states"] = dict(sorted(counts.items()))
    return output, diagnostics


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
            if hour in models_by_hour:
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

    for row in rows:
        row.pop("_band_postprocess_row", None)
    if postprocess.get("partition_normalization_enabled", True):
        normalize_partition_probabilities(
            rows,
            gamma=float(postprocess.get("partition_normalization_gamma", 1.25)),
        )
    if postprocess.get("current_blend_enabled", False):
        apply_current_blend_guardrail(rows, postprocess)

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
            if density_postprocess.get("enabled"):
                if density_postprocess.get("adjacent_calibration_enabled", False):
                    probability = apply_adjacent_calibration(
                        probability,
                        band_row,
                        config={"adjacent_calibration": density_postprocess.get("adjacent_calibration") or {}},
                    )
                if density_postprocess.get("exact_winner_catchup_enabled", False):
                    probability = apply_exact_winner_catchup(
                        probability,
                        band_row,
                        config={"exact_winner_catchup": density_postprocess.get("exact_winner_catchup") or {}},
                    )
                if density_postprocess.get("forecast_relative_calibration_enabled", False):
                    probability = apply_forecast_relative_density_calibration(
                        probability,
                        band_row,
                        config={
                            "forecast_relative_calibration": (
                                density_postprocess.get("forecast_relative_calibration") or {}
                            ),
                        },
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


def current_blend_alpha(row, config):
    market_alpha = config.get("current_blend_market_alpha") or {}
    market_id = row.get("market_id")
    if market_id in market_alpha:
        alpha = market_alpha[market_id]
    else:
        alpha = config.get("current_blend_default_alpha", 1.0)
    source_alpha = config.get("current_blend_source_freshness_alpha") or {}
    if source_alpha:
        source_state = row.get("source_freshness_state") or row.get("source_status_group") or "unknown"
        source_default = config.get("current_blend_source_freshness_default_alpha", 0.0)
        source_state_alpha = source_alpha.get(source_state, source_default)
        try:
            alpha = min(float(alpha), float(source_state_alpha))
        except (TypeError, ValueError):
            alpha = source_state_alpha
    for rule in config.get("current_blend_context_alpha") or []:
        if current_blend_context_rule_matches(row, rule):
            alpha = rule.get("alpha", alpha)
    try:
        return max(0.0, min(1.0, float(alpha)))
    except (TypeError, ValueError):
        return 1.0


def current_blend_context_value(row, key):
    if key == "source_freshness_state":
        return row.get("source_freshness_state") or row.get("source_status_group") or "unknown"
    if key == "cutoff_regime":
        return (
            row.get("cutoff_regime")
            or row.get("candidate_cutoff_regime")
            or cutoff_regime(row.get("cutoff_hour") or row.get("candidate_cutoff_hour"))
            or ""
        )
    if key == "cutoff_hour":
        return row.get("cutoff_hour") or row.get("candidate_cutoff_hour") or ""
    return row.get(key)


def current_blend_context_rule_matches(row, rule):
    for key, expected in (rule or {}).items():
        if key in {"alpha", "policy_id", "description"}:
            continue
        if key.endswith("_min") or key.endswith("_max"):
            base_key = key[:-4]
            actual = current_blend_context_value(row, base_key)
            try:
                actual_value = float(actual)
                expected_value = float(expected)
            except (TypeError, ValueError):
                return False
            if key.endswith("_min") and actual_value < expected_value:
                return False
            if key.endswith("_max") and actual_value > expected_value:
                return False
            continue
        actual = current_blend_context_value(row, key)
        expected_values = expected if isinstance(expected, list) else [expected]
        if str(actual) not in {str(value) for value in expected_values}:
            return False
    return True


def apply_current_blend_guardrail(rows, config):
    """Blend pooled candidate probabilities with incumbent replay probabilities."""
    for row in rows:
        if not _valid_probability(row.get("candidate_p")):
            continue
        if not _valid_probability(row.get("replayed_p")):
            continue
        alpha = current_blend_alpha(row, config)
        if alpha >= 1.0:
            continue
        candidate = _clamp_probability(row["candidate_p"])
        incumbent = _clamp_probability(row["replayed_p"])
        row["candidate_p"] = (alpha * candidate) + ((1.0 - alpha) * incumbent)
    return rows


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
    family_unit = artifact.get("family_unit") or "F"
    prediction_mode = artifact.get("prediction_mode") or "bucket_distribution"
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
    replay_results = run_replay_backtest(
        folders,
        daily_summary_path=None,
        overrides={},
        out_path=args.replay_report,
        include_reconstructed=manifest.get("include_reconstructed", False),
        write=bool(args.replay_report),
        corpus_manifest=manifest,
        long_job_guard_info=getattr(args, "long_job_guard_info", None),
    )
    replay_gate = replay_gate_status(
        replay_results,
        max_fidelity_l1=getattr(args, "max_fidelity_l1", FIDELITY_FAITHFUL_L1),
        require_exact_identity=getattr(args, "require_exact_identity", False),
    )
    if prediction_mode == "band_binary":
        feature_rows, diagnostics = build_candidate_features(
            manifest,
            args.snapshots_root,
            family_unit,
            artifact=artifact,
        )
        clob_features, clob_diagnostics = build_clob_feature_index(
            manifest,
            args.snapshots_root,
            family_unit,
            max_age_seconds=args.clob_max_age_seconds,
        )
        source_freshness, source_freshness_diagnostics = build_source_freshness_index(
            manifest,
            args.snapshots_root,
            family_unit,
        )
        diagnostics.update(clob_diagnostics)
        diagnostics.update(source_freshness_diagnostics)
        candidate_rows, coverage = attach_band_candidate_probabilities(
            replay_results,
            feature_rows,
            artifact,
            family_unit,
            clob_features=clob_features,
            source_freshness=source_freshness,
        )
    elif prediction_mode == "continuous_density_f":
        feature_rows, diagnostics = build_candidate_features(
            manifest,
            args.snapshots_root,
            family_unit,
            artifact=artifact,
        )
        source_freshness, source_freshness_diagnostics = build_source_freshness_index(
            manifest,
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
        predictions, diagnostics = build_candidate_distributions(manifest, args.snapshots_root, artifact)
        source_freshness, source_freshness_diagnostics = build_source_freshness_index(
            manifest,
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
    market_verdict = overall_verdict(market_rows, require_all_markets=args.require_all_markets)
    verdict = market_verdict if replay_gate["global_ok"] and blocked_validation.get("passed") else "BLOCK"
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
        "candidate_market_verdict": market_verdict,
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


from weather.model.variant_prediction_runtime import (  # noqa: E402
    density_projection_index,
    density_projection_probability,
)


if __name__ == "__main__":
    main()
