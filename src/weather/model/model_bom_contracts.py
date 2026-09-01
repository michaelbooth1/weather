"""Owner and semantic contracts used by the deterministic model BOM.

Runtime order itself lives in :mod:`weather.model.model_contracts` and is
consumed by serving code.  This module adds release-facing semantics without
pretending that the base and pooled paths are one linear execution sequence.
"""

from __future__ import annotations

from weather.model.model_contracts import (
    BASE_DISTRIBUTION_STAGE_ORDER,
    POOLED_BAND_STAGE_ORDER,
)

def _stage(
    stage_id,
    owner_module,
    role,
    input_contract,
    output_contract,
    native_unit,
    cutoff,
    *,
    artifact_roles=(),
    artifact_role_suffixes=(),
    forecast_context=None,
    lane_id=None,
    training_evidence_required=False,
):
    return {
        "stage_id": stage_id,
        "owner_module": owner_module,
        "role": role,
        "input_semantic_contract": input_contract,
        "output_semantic_contract": output_contract,
        "native_unit_obligation": native_unit,
        "cutoff_obligation": cutoff,
        "artifact_roles": tuple(artifact_roles),
        "artifact_role_suffixes": tuple(artifact_role_suffixes),
        "forecast_context": forecast_context,
        "lane_id": lane_id,
        "training_evidence_required": bool(training_evidence_required),
    }


SERVING_STAGE_CONTRACTS = (
    _stage(
        "release_route_binding", "weather.release_serving", "release_and_variant_router",
        "verified_manifest_roles_and_market_route", "content_bound_serving_graph",
        "route_preserves_market_spec_native_unit", "route_cannot_supply_or_relabel_source_time",
        artifact_roles=("base_model_serving_graph", "market_route_table", "model_variant_registry"),
    ),
    _stage(
        "market_contract", "weather.market.market_registry", "market_specification",
        "market_id_target_date_reviewed_registry", "market_spec_bands_station_timezone_unit",
        "select_once_and_preserve_settlement_unit", "bind_target_date_and_timezone_before_source_use",
        artifact_roles=("location_market_events_config", "locations_config", "markets_config"),
    ),
    _stage(
        "source_bundle", "weather.model.toronto_model", "point_in_time_source_bundle",
        "historical_and_live_source_groups", "named_source_payloads_with_diagnostics",
        "source_values_convert_only_through_market_spec", "no_post_cutoff_row_may_enter_live_state",
    ),
    _stage(
        "effective_cutoff_and_observed_state", "weather.model.model_distribution", "cutoff_safe_observed_state",
        "source_bundle_target_date_build_clock", "effective_cutoff_and_observed_floor_context",
        "observations_and_floors_remain_native", "effective_wu_print_cutoff_is_authoritative",
    ),
    _stage(
        "distribution_stage_forecast_context", "weather.model.model_distribution", "distribution_forecast_context",
        "runtime_selected_distribution_forecast_sources", "forecast_signals_for_distribution_transforms",
        "forecast_signals_use_market_native_unit", "only_values_available_at_effective_cutoff",
        forecast_context="distribution_stage_forecast_context",
    ),
    _stage(
        "target_date_prior", "weather.model.model_climatology", "target_date_aligned_prior",
        "historical_target_window_or_climatology", "normalized_native_temperature_prior",
        "prior_support_uses_market_native_degree_grid", "historical_inputs_end_before_target_information",
    ),
    _stage(
        "feature_extraction_forecast_ensemble", "weather.model.model_features", "feature_forecast_context",
        "runtime_selected_feature_forecast_sources", "cutoff_safe_forecast_feature_summary",
        "forecast_highs_use_market_native_unit", "only_issue_or_retrieval_qualified_values",
        forecast_context="feature_extraction_forecast_ensemble",
    ),
    _stage(
        "live_feature_extraction", "weather.model.model_features", "stored_feature_order_input_vector",
        "cutoff_safe_sources_and_feature_context", "named_feature_values_selected_by_stored_order",
        "temperature_features_remain_native", "feature_values_must_be_knowable_at_effective_cutoff",
        artifact_role_suffixes=(".feature_hgb", ".feature_lr_coefficients"),
    ),
    _stage(
        "base_estimator_and_prior_blend", "weather.model.model_distribution", "base_distribution_model_path",
        "stored_order_features_prior_and_bound_estimators", "base_native_temperature_distribution",
        "all_bucket_keys_are_native_degrees", "estimator_inputs_share_effective_cutoff",
        artifact_role_suffixes=(".calibrated_weights", ".feature_hgb", ".feature_lr_coefficients"),
        lane_id="toronto_base_distribution", training_evidence_required=True,
    ),
    _stage(
        "bucket_transition", "weather.model.model_distribution", "bucket_transition_transform",
        "base_distribution_and_cutoff_safe_sources", "transition_adjusted_distribution",
        "transition_edges_use_native_degrees", "transition_state_uses_no_later_observation",
        lane_id="toronto_base_distribution",
    ),
    _stage(
        "live_signal_adjustment", "weather.model.model_distribution", "live_signal_transform",
        "distribution_and_cutoff_safe_live_signals", "live_signal_adjusted_distribution",
        "signals_and_buckets_share_native_unit", "signals_are_bounded_by_effective_cutoff",
        lane_id="toronto_base_distribution",
    ),
    _stage(
        "observed_hard_floor", "weather.model.model_distribution", "settlement_support_floor",
        "distribution_and_trusted_observed_high", "zero_mass_below_observed_support",
        "floor_bucket_is_native_whole_degree", "floor_uses_only_cutoff_admitted_observation",
        lane_id="toronto_base_distribution",
    ),
    _stage(
        "intraday_tail_adjustment", "weather.model.model_distribution", "intraday_tail_transform",
        "floored_distribution_and_intraday_signals", "intraday_tail_adjusted_distribution",
        "tail_distance_uses_native_degree_scale", "intraday_state_is_cutoff_safe",
        lane_id="toronto_base_distribution",
    ),
    _stage(
        "plausible_upper_cap", "weather.model.model_distribution", "forecast_plausibility_cap",
        "distribution_observed_state_forecast_signals", "plausibility_capped_distribution",
        "cap_uses_native_degree_scale", "forecast_cap_uses_cutoff_safe_guidance",
        lane_id="toronto_base_distribution",
    ),
    _stage(
        "forecast_shape", "weather.model.model_distribution", "forecast_shape_transform",
        "distribution_and_distribution_forecast_context", "forecast_shaped_distribution",
        "shape_centres_use_native_degrees", "context_is_bound_to_effective_cutoff",
        lane_id="toronto_base_distribution",
    ),
    _stage(
        "ramp_warm_tail_dampening", "weather.model.model_distribution", "warm_tail_safety_transform",
        "distribution_observed_state_forecast_context", "warm_tail_dampened_distribution",
        "tail_gaps_use_native_degree_scale", "warm_tail_evidence_is_cutoff_safe",
        lane_id="toronto_base_distribution",
    ),
    _stage(
        "afternoon_residual_centering", "weather.model.model_distribution", "intraday_residual_centering",
        "distribution_hour_and_forecast_context", "residual_centered_distribution",
        "centering_offsets_are_native_degrees", "hour_and_context_share_effective_cutoff",
        artifact_roles=("base_model.shared.afternoon_residual_centering",),
        lane_id="toronto_base_distribution", training_evidence_required=True,
    ),
    _stage(
        "validated_current_max_floor", "weather.model.model_distribution", "trusted_current_max_floor",
        "distribution_and_validated_current_max", "distribution_floored_at_trusted_current_max",
        "floor_value_is_native_whole_degree", "untrusted_or_post_cutoff_max_is_quarantined",
        lane_id="toronto_base_distribution",
    ),
    _stage(
        "observation_support_floor", "weather.model.model_distribution", "multi_source_observation_floor",
        "distribution_and_admitted_observation_support", "support_constrained_distribution",
        "support_values_share_market_native_unit", "support_sources_are_cutoff_admitted",
        lane_id="toronto_base_distribution",
    ),
    _stage(
        "late_day_continuation", "weather.model.model_distribution", "late_day_continuation_transform",
        "distribution_sources_hour_and_model_state", "continuation_adjusted_distribution",
        "continuation_deltas_use_native_degrees", "continuation_features_are_cutoff_safe",
        artifact_role_suffixes=(".forecast_error_model", ".late_day_lr_coefficients", ".settlement_lag_model"),
        lane_id="toronto_base_distribution", training_evidence_required=True,
    ),
    _stage(
        "late_day_lockin", "weather.model.model_distribution", "late_day_lockin_transform",
        "distribution_history_current_and_forecast_state", "lockin_adjusted_distribution_and_strength",
        "lockin_support_uses_native_degrees", "lockin_uses_only_effective_cutoff_state",
        lane_id="toronto_base_distribution",
    ),
    _stage(
        "pre_calibration_normalization", "weather.model.model_distribution", "probability_simplex_normalization",
        "post_transform_nonnegative_scores", "unit_mass_native_temperature_distribution",
        "normalization_does_not_change_bucket_units", "normalization_adds_no_information",
        lane_id="toronto_base_distribution",
    ),
    _stage(
        "exact_distribution_calibration", "weather.model.calibration_runtime", "exact_distribution_calibration",
        "normalized_distribution_and_calibration_context", "calibrated_unit_mass_distribution",
        "calibration_preserves_native_bucket_support", "calibration_context_uses_effective_cutoff",
        artifact_role_suffixes=(".probability_calibration",),
        lane_id="toronto_base_distribution", training_evidence_required=True,
    ),
    _stage(
        "current_max_boundary_guard", "weather.model.model_distribution", "current_max_overlock_guard",
        "calibrated_distribution_and_boundary_context", "boundary_safe_distribution",
        "boundary_is_native_whole_degree", "boundary_uses_only_trusted_cutoff_state",
        lane_id="toronto_base_distribution",
    ),
    _stage(
        "native_band_projection", "weather.model.model_presentation", "market_band_projection",
        "native_temperature_distribution_and_market_bands", "raw_market_band_probability",
        "band_and_distribution_units_must_match_exactly", "projection_adds_no_later_information",
        artifact_roles=("settlement_rules",),
    ),
    _stage(
        "binary_market_calibration", "weather.model.model_presentation", "exact_bin_probability_calibration",
        "raw_band_probability_and_calibration_context", "bounded_market_yes_probability",
        "calibration_cannot_reinterpret_band_unit", "calibration_context_uses_effective_cutoff",
        artifact_roles=("family_secondary_calibration",), artifact_role_suffixes=(".probability_calibration",),
        training_evidence_required=True,
    ),
    _stage(
        "final_model_build_result", "weather.model.toronto_model", "normalized_model_build_result",
        "distribution_rows_features_and_diagnostics", "model_build_result_with_countable_lineage",
        "all_public_temperature_outputs_name_native_unit", "one_build_clock_and_effective_cutoff_are_reused",
    ),
    _stage(
        "candidate_variant_router", "weather.collection.live_variant_predictions", "candidate_or_base_model_route",
        "verified_route_and_available_model_roles", "one_named_model_path_or_named_abstention",
        "candidate_family_unit_must_match_market_unit", "cutoff_hour_router_cannot_use_later_inputs",
        artifact_roles=("model_variant_registry", "market_route_table"),
    ),
    _stage(
        "candidate_raw", "weather.collection.live_variant_predictions", "pooled_candidate_raw_prediction",
        "captured_feature_row_frozen_schema_imputer_and_model", "raw_candidate_band_probabilities",
        "temperature_features_keep_declared_family_unit", "model_inputs_are_from_the_captured_cutoff",
        artifact_roles=("pooled_band_model", "pooled_feature_schema", "pooled_imputer_metadata"),
        lane_id="pooled_band_live_variant", training_evidence_required=True,
    ),
    _stage(
        "candidate_postprocessed", "weather.model.variant_prediction_runtime", "pooled_candidate_postprocessor",
        "raw_candidate_probability_and_frozen_postprocess", "postprocessed_candidate_probability",
        "postprocess_preserves_native_band_keys", "postprocess_adds_no_later_information",
        artifact_roles=("pooled_calibrator_metadata", "pooled_postprocessor_metadata"),
        lane_id="pooled_band_live_variant", training_evidence_required=True,
    ),
    _stage(
        "candidate_preblend", "weather.collection.live_variant_predictions", "candidate_partition_normalization",
        "postprocessed_candidate_partition", "normalized_preblend_partition",
        "normalization_preserves_native_band_keys", "normalization_adds_no_information",
        artifact_roles=("pooled_postprocessor_metadata",), lane_id="pooled_band_live_variant",
        training_evidence_required=True,
    ),
    _stage(
        "candidate_current_blend", "weather.model.current_blend", "candidate_current_blend",
        "normalized_candidate_partition_and_current_context", "current_blended_partition",
        "blend_preserves_native_band_keys", "current_context_is_cutoff_safe",
        artifact_roles=("pooled_postprocessor_metadata",), lane_id="pooled_band_live_variant",
        training_evidence_required=True,
    ),
    _stage(
        "candidate_final", "weather.collection.live_variant_predictions", "candidate_final_normalization",
        "current_blended_partition", "final_candidate_probability_partition",
        "final_partition_preserves_native_band_keys", "finalization_adds_no_information",
        artifact_roles=("pooled_postprocessor_metadata",), lane_id="pooled_band_live_variant",
        training_evidence_required=True,
    ),
)


RUNTIME_LANE_CONTRACTS = (
    {
        "lane_id": "toronto_base_distribution",
        "runtime_owner": "weather.model.model_distribution",
        "runtime_contract_symbol": "BASE_DISTRIBUTION_STAGE_ORDER",
        "stage_order": BASE_DISTRIBUTION_STAGE_ORDER,
    },
    {
        "lane_id": "pooled_band_live_variant",
        "runtime_owner": "weather.collection.live_variant_predictions",
        "runtime_contract_symbol": "POOLED_BAND_STAGE_ORDER",
        "stage_order": POOLED_BAND_STAGE_ORDER,
    },
)


SERVING_GRAPH_EDGES = (
    ("release_route_binding", "market_contract", "required"),
    ("market_contract", "source_bundle", "required"),
    ("source_bundle", "effective_cutoff_and_observed_state", "required"),
    ("effective_cutoff_and_observed_state", "distribution_stage_forecast_context", "required"),
    ("distribution_stage_forecast_context", "target_date_prior", "required"),
    ("effective_cutoff_and_observed_state", "feature_extraction_forecast_ensemble", "conditional_feature_model"),
    ("feature_extraction_forecast_ensemble", "live_feature_extraction", "conditional_feature_model"),
    ("target_date_prior", BASE_DISTRIBUTION_STAGE_ORDER[0], "required"),
    ("live_feature_extraction", BASE_DISTRIBUTION_STAGE_ORDER[0], "conditional_feature_model"),
    *tuple(
        (left, right, "required")
        for left, right in zip(BASE_DISTRIBUTION_STAGE_ORDER, BASE_DISTRIBUTION_STAGE_ORDER[1:])
    ),
    (BASE_DISTRIBUTION_STAGE_ORDER[-1], "native_band_projection", "required"),
    ("native_band_projection", "binary_market_calibration", "required"),
    ("binary_market_calibration", "final_model_build_result", "required"),
    ("final_model_build_result", "candidate_variant_router", "conditional_pooled_variant"),
    ("candidate_variant_router", POOLED_BAND_STAGE_ORDER[0], "conditional_pooled_variant"),
    *tuple(
        (left, right, "conditional_pooled_variant")
        for left, right in zip(POOLED_BAND_STAGE_ORDER, POOLED_BAND_STAGE_ORDER[1:])
    ),
)
