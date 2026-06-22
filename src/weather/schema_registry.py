"""Central schema-version registry and migration audit tooling.

The registry is intentionally dependency-free: producer modules import schema
constants from here, while this module never imports producers.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path


SCHEMA_REGISTRY_SCHEMA_VERSION = "schema_registry_v0.1"


@dataclass(frozen=True)
class SchemaSpec:
    name: str
    version: str
    owner: str
    status: str
    description: str = ""
    supersedes: tuple[str, ...] = ()
    migration_notes: str = ""


REGISTERED_SCHEMAS = (
    SchemaSpec(
        "schema_registry",
        SCHEMA_REGISTRY_SCHEMA_VERSION,
        "weather.schema_registry",
        "active",
        "Inventory of public artifact schema versions and migration status.",
    ),
    SchemaSpec(
        "feature_store",
        "toronto_feature_store_v1.13",
        "weather.model.feature_store",
        "active",
        "Shared train/serve feature vector schema.",
        supersedes=("toronto_feature_store_v1.12",),
        migration_notes="Predictors must select by trained feature_names, not by newest column order.",
    ),
    SchemaSpec(
        "historical_coverage",
        "historical_coverage_v1",
        "weather.sources.historical_coverage",
        "active",
        "Fleet source-coverage payload across WU, GHCNh, reanalysis, and supplemental sources.",
    ),
    SchemaSpec(
        "historical_coverage_dashboard",
        "historical_coverage_dashboard_v0.1",
        "weather.sources.historical_coverage",
        "active",
        "Flattened historical coverage, gap, and source-freshness SLA dashboard.",
    ),
    SchemaSpec(
        "market_registry",
        "market_registry_v0.1",
        "weather.market.market_registry",
        "active",
        "External market registry overlay schema.",
    ),
    SchemaSpec(
        "location_registry",
        "location_registry_v0.1",
        "weather.operations.location_config_refresh",
        "active",
        "Durable high-temperature location, station, source-plan, and settlement facts.",
    ),
    SchemaSpec(
        "location_market_events",
        "location_market_events_v0.1",
        "weather.operations.location_config_refresh",
        "active",
        "Generated volatile Polymarket Gamma active-event metadata by location.",
    ),
    SchemaSpec("marine_context", "marine_context_v0.1", "weather.sources.marine_context", "active"),
    SchemaSpec("nbm_probabilistic_tmax", "nbm_probabilistic_tmax_v0.1", "weather.sources.nbm_probabilistic_tmax", "active"),
    SchemaSpec(
        "wu_daily",
        "wu_daily_native_v2",
        "weather.sources.daily_summary",
        "active",
        "Unit-explicit WU normalized daily summary rows.",
        supersedes=("wu_daily_native_v1",),
    ),
    SchemaSpec(
        "settlement_ledger",
        "settlement_ledger_v1",
        "weather.backtesting.settlement_ledger",
        "active",
        "Frozen settlement labels.",
    ),
    SchemaSpec(
        "resolution_spec",
        "resolution_spec_v1",
        "weather.backtesting.settlement_ledger",
        "active",
        "Per-market resolution rules attached to settlement ledgers.",
    ),
    SchemaSpec(
        "daily_refresh",
        "daily_refresh_v0.4",
        "weather.operations.daily_refresh",
        "active",
        "Daily settlement, promotion, audit, and snapshot-evaluation status artifact.",
    ),
    SchemaSpec(
        "variant_learning_operational_gate",
        "variant_learning_operational_gate_v0.1",
        "weather.operations.daily_refresh",
        "active",
        "Fail-closed daily-refresh gate for active-variant shadow freshness and independent evidence growth.",
    ),
    SchemaSpec(
        "observation_trigger",
        "observation_trigger_v0.1",
        "weather.operations.observation_trigger",
        "active",
        "Fast observation-trigger watcher status and event schema.",
    ),
    SchemaSpec(
        "observation_trigger_replay",
        "observation_trigger_replay_v0.1",
        "weather.operations.observation_trigger",
        "active",
        "Triggered-row replay comparison artifact.",
    ),
    SchemaSpec("adjacent_market_hour_floor_gap", "adjacent_market_hour_floor_gap_v1", "weather.calibration.pooled_feature_model", "active"),
    SchemaSpec(
        "market_hour_kind_bias",
        "market_hour_kind_bias_v1",
        "weather.calibration.pooled_feature_model",
        "active",
        "Conservative market/hour/kind postprocess calibration embedded in pooled band artifacts.",
    ),
    SchemaSpec("asos_1min", "asos_1min_v0.1", "weather.sources.asos_one_minute", "active"),
    SchemaSpec("artifact_provenance_manifest", "artifact_provenance_manifest_v0.1", "weather.artifacts", "active"),
    SchemaSpec("calibrated_weights", "calibrated_weights_v0.1", "weather.calibration.intraday_calibration", "active"),
    SchemaSpec(
        "blocked_validation",
        "blocked_validation_v0.1",
        "weather.calibration.blocked_validation",
        "active",
        "Leakage-audit summary for market-day and blocked-date validation splits.",
    ),
    SchemaSpec(
        "blocked_candidate_validation_gate",
        "blocked_candidate_validation_gate_v0.1",
        "weather.calibration.pooled_candidate_scoring",
        "active",
        "Promotion gate requiring daily-first blocked candidate validation.",
    ),
    SchemaSpec("canonical_history_guardrails", "canonical_history_guardrails_v0.1", "weather.sources.canonical_history_guardrails", "active"),
    SchemaSpec(
        "clob_capture_status",
        "clob_capture_status_v0.1",
        "weather.market.market_microstructure_capture",
        "active",
        "Append-only per-folder status rows for CLOB token/book capture attempts.",
    ),
    SchemaSpec(
        "config_inventory",
        "config_inventory_v0.1",
        "weather.operations.config_inventory",
        "active",
        "Config ownership, freshness, generated/deprecated classification, and registry hygiene audit.",
    ),
    SchemaSpec("clob_microstructure_overlay", "clob_microstructure_overlay_v0.2", "weather.calibration.pooled_candidate_replay", "active"),
    SchemaSpec(
        "clob_book_recon",
        "clob_book_recon_v0.1",
        "weather.market.clob_recon",
        "active",
        "Offline CLOB book recon, reward competition, executable depth, and passive-flow toxicity artifact.",
    ),
    SchemaSpec("clob_microstructure_taxonomy_gate", "clob_microstructure_taxonomy_gate_v0.1", "weather.calibration.pooled_candidate_replay", "active"),
    SchemaSpec("conservative_bridge_policy", "conservative_bridge_policy_v0.1", "weather.calibration.pooled_candidate_replay", "active"),
    SchemaSpec(
        "cross_hub_readiness",
        "cross_hub_readiness_v0.1",
        "weather.reporting.cross_hub_readiness",
        "active",
        "Per-market readiness labels that separate source redundancy, trust, model edge, quoteability, and live-forward plumbing.",
    ),
    SchemaSpec(
        "cross_hub_research_audit",
        "cross_hub_research_audit_v0.1",
        "weather.reporting.cross_hub_research_audit",
        "active",
        "Per-location research audit comparing model performance, trust, source health, quote logs, run logs, and transferable hub lessons.",
    ),
    SchemaSpec(
        "source_state_ablation",
        "source_state_ablation_v0.1",
        "weather.calibration.pooled_candidate_scoring",
        "active",
        "Shadow-variant ablation comparing no-source-state serving control with dynamic source-state candidate probabilities.",
    ),
    SchemaSpec(
        "forecast_profile_calibration",
        "forecast_profile_calibration_v0.1",
        "weather.reporting.forecast_profile_calibration",
        "active",
        "Roadmap item 134 report combining forecast-profile replay slices, marginal subfamily value, and high-disagreement guardrails.",
    ),
    SchemaSpec(
        "forecast_profile_guardrails",
        "forecast_profile_guardrails_v0.1",
        "weather.calibration.pooled_candidate_replay",
        "active",
        "Per-market high-disagreement guardrails embedded in pooled candidate replay artifacts.",
    ),
    SchemaSpec(
        "cutoff_regime_weighting",
        "cutoff_regime_weighting_v0.1",
        "weather.reporting.cutoff_regime_weighting",
        "active",
        "Roadmap item 135 report for cutoff-regime family weights, market-day leakage audit, thresholds, and disagreement cases.",
    ),
    SchemaSpec(
        "cutoff_regime_market_day_leakage_audit",
        "cutoff_regime_market_day_leakage_audit_v0.1",
        "weather.reporting.cutoff_regime_weighting",
        "active",
        "Market-day leakage audit embedded in cutoff-regime weighting reports.",
    ),
    SchemaSpec(
        "forecast_source_state_reliability",
        "forecast_source_state_reliability_v0.1",
        "weather.reporting.forecast_source_state_reliability",
        "active",
        "Roadmap item 136 report for forecast source-state confidence shrinkage, calibration curves, and reliability slices.",
    ),
    SchemaSpec(
        "blocked_market_repair_diagnostics",
        "blocked_market_repair_diagnostics_v0.1",
        "weather.reporting.blocked_market_repair_diagnostics",
        "active",
        "Development diagnostic for blocked promotion markets, repair actions, and slice-level market gaps.",
    ),
    SchemaSpec(
        "winner_boost_time_split_validation",
        "winner_boost_time_split_validation_v0.1",
        "weather.reporting.winner_boost_validation",
        "active",
        "Chronological validation for simple exact-winner boost policies on variant row exports.",
    ),
    SchemaSpec(
        "current_blend_time_split_validation",
        "current_blend_time_split_validation_v0.1",
        "weather.reporting.current_blend_validation",
        "active",
        "Chronological validation for current-blend alpha schedules on variant row exports.",
    ),
    SchemaSpec(
        "context_guard_validation",
        "context_guard_validation_v0.1",
        "weather.reporting.context_guard_validation",
        "active",
        "Chronological validation for no-market context guard policies on variant row exports.",
    ),
    SchemaSpec(
        "contextual_winner_time_split_validation_legacy",
        "contextual_winner_time_split_validation_v0.1",
        "weather.reporting.contextual_winner_validation",
        "legacy",
    ),
    SchemaSpec(
        "contextual_winner_time_split_validation",
        "contextual_winner_time_split_validation_v0.2",
        "weather.reporting.contextual_winner_validation",
        "active",
        "Time-split contextual exact-winner factor validation with band-key context and eval-oracle diagnostics.",
        supersedes=["contextual_winner_time_split_validation_v0.1"],
    ),
    SchemaSpec(
        "winner_band_signal_validation",
        "winner_band_signal_validation_v0.1",
        "weather.reporting.winner_band_signal_validation",
        "active",
        "Nested time-split validation for pooled inference-time winner-band row-signal transforms.",
    ),
    SchemaSpec(
        "market_anchor_time_split_validation",
        "market_anchor_time_split_validation_v0.2",
        "weather.reporting.market_anchor_validation",
        "active",
        "Chronological validation for CLOB midpoint and market-price anchor repairs with train-side CLOB coverage gates.",
    ),
    SchemaSpec(
        "clob_coverage_audit_legacy_v0_2",
        "clob_coverage_audit_v0.2",
        "weather.reporting.clob_coverage_audit",
        "legacy",
        "Folder-level CLOB raw tape, token-map, midpoint, and chronological split-coverage audit.",
    ),
    SchemaSpec(
        "clob_coverage_audit",
        "clob_coverage_audit_v0.3",
        "weather.reporting.clob_coverage_audit",
        "active",
        "Folder-level CLOB raw tape, token-map, midpoint, chronological split-coverage, and backup restore-source audit.",
        supersedes=["clob_coverage_audit_v0.2"],
    ),
    SchemaSpec(
        "official_guidance_sparse_coverage",
        "official_guidance_sparse_coverage_v0.1",
        "weather.reporting.official_guidance_sparse_coverage",
        "active",
        "Roadmap item 137 report for official-guidance coverage targets, sparse blockers, and fail-closed promotion gating.",
    ),
    SchemaSpec(
        "weak_input_family_disposition",
        "weak_input_family_disposition_v0.1",
        "weather.reporting.weak_input_family_disposition",
        "active",
        "Roadmap item 138 report for weak/sparse input-family disposition, regime backfill, and training preflight warnings.",
    ),
    SchemaSpec(
        "active_variant_shadow_refresh",
        "active_variant_shadow_refresh_v0.1",
        "weather.reporting.active_variant_shadow_refresh",
        "active",
        "Scheduled active model-variant shadow refresh wrapper for canonical long-table evidence.",
    ),
    SchemaSpec(
        "roadmap_backlog",
        "roadmap_backlog_v0.1",
        "weather.reporting.roadmap_backlog",
        "active",
        "Parsed numbered roadmap item inventory, active backlog report, active-item docs lint, and ROADMAP.md index ownership lint.",
    ),
    SchemaSpec(
        "local_generated_state_cleanup",
        "local_generated_state_cleanup_v0.1",
        "weather.operations.local_generated_state_cleanup",
        "active",
        "Dry-run report for ignored local generated state, scratch outputs, research-tool inventory, dependency pin sync, and line endings.",
    ),
    SchemaSpec(
        "live_variant_predictions",
        "live_variant_predictions_v0.1",
        "weather.collection.live_variant_predictions",
        "active",
        "Append-only live snapshot tape for active model-variant probabilities and explicit skip/failure rows.",
    ),
    SchemaSpec(
        "no_market_extra_location_registry",
        "no_market_extra_location_registry_v0.1",
        "weather.reporting.extra_location_registry",
        "active",
        "Registry schema for no-market extra locations with station provenance, label compatibility, and training eligibility fields.",
    ),
    SchemaSpec(
        "extra_location_compatibility_report",
        "extra_location_compatibility_report_v0.1",
        "weather.reporting.extra_location_registry",
        "active",
        "Machine-readable PASS/SHADOW_ONLY/BLOCKED compatibility report for no-market extra-location labels.",
    ),
    SchemaSpec(
        "location_similarity_features",
        "location_similarity_features_v0.1",
        "weather.reporting.location_similarity_pooling",
        "active",
        "Pairwise climate, geographic, source, and forecast-error similarity features for partial pooling.",
    ),
    SchemaSpec(
        "location_similarity_partial_pooling",
        "location_similarity_partial_pooling_v0.1",
        "weather.reporting.location_similarity_pooling",
        "active",
        "Similarity-weighted no-market extra-location partial-pooling policy and attribution artifact.",
    ),
    SchemaSpec(
        "no_market_location_transfer",
        "no_market_location_transfer_v0.1",
        "weather.reporting.no_market_location_transfer",
        "active",
        "Price-free target-only versus target-plus-extra validation harness with blocked daily-first scoring.",
    ),
    SchemaSpec(
        "no_market_extra_location_gate",
        "no_market_extra_location_gate_v0.1",
        "weather.reporting.no_market_location_transfer",
        "active",
        "Promotion gate for no-market extra-location shadow lanes comparing target-only and target-plus-extra evidence.",
    ),
    SchemaSpec(
        "source_family_ablation",
        "source_family_ablation_v0.1",
        "weather.backtesting.replay_ablation",
        "active",
        "Settlement-scored source-family knockout replay artifact used by input promotion preflight.",
    ),
    SchemaSpec(
        "source_family_inventory",
        "source_family_inventory_v0.1",
        "weather.reporting.source_family_inventory",
        "active",
        "Weather-input family inventory with lineage, train/serve parity, ablation, missingness, and promotion decisions.",
    ),
    SchemaSpec("daily_source_truth", "daily_source_truth_v0.3", "weather.reporting.source_redundancy", "active"),
    SchemaSpec("data_layer_audit", "data_layer_audit_v0.3", "weather.reporting.data_layer_audit", "active"),
    SchemaSpec(
        "data_retention_inventory",
        "data_retention_inventory_v0.1",
        "weather.reporting.data_retention_inventory",
        "active",
        "Data-tree ownership, retention, restore-gate, and disk-growth inventory.",
    ),
    SchemaSpec(
        "daily_learning",
        "daily_learning_v0.1",
        "weather.reporting.daily_learning",
        "active",
        "Daily distilled log-learning artifact for retrain and promotion decisions.",
    ),
    SchemaSpec(
        "daily_flow_analysis",
        "daily_flow_analysis_v0.1",
        "weather.reporting.daily_flow_analysis",
        "active",
        "End-of-day decision record and action queue across model, ops, root-cause, and trading logs.",
    ),
    SchemaSpec("disagreement_casebook", "disagreement_casebook_v0.1", "weather.reporting.disagreement_casebook", "active"),
    SchemaSpec(
        "distribution_stage_attribution",
        "distribution_stage_attribution_v0.1",
        "weather.reporting.distribution_stage_attribution",
        "active",
        "Settled component-snapshot stage attribution by Brier/log-loss delta.",
    ),
    SchemaSpec(
        "settled_day_root_cause",
        "settled_day_root_cause_v0.1",
        "weather.reporting.settled_day_root_cause",
        "active",
        "Settled-day model, taker, market-maker, and roadmap root-cause evidence bundle.",
    ),
    SchemaSpec("eccc_gridded", "eccc_gridded_v0.1", "weather.sources.eccc_gridded", "active"),
    SchemaSpec("family_secondary_artifacts", "family_secondary_artifacts_v0.1", "weather.calibration.family_secondary_artifacts", "active"),
    SchemaSpec("feature_model_coefs", "feature_model_coefs_v0.1", "weather.calibration.feature_model", "active"),
    SchemaSpec("feature_model_hgb_legacy", "feature_model_hgb_v0.1", "weather.calibration.feature_model", "legacy"),
    SchemaSpec("feature_model_hgb", "feature_model_hgb_v0.2", "weather.calibration.feature_model", "active"),
    SchemaSpec(
        "feature_quality_quarantine",
        "feature_quality_quarantine_v0.1",
        "weather.reporting.feature_quality_quarantine",
        "active",
        "Historical feature-quality quarantine manifest for training and promotion exclusion.",
    ),
    SchemaSpec("item27_feature_value_gate", "item27_feature_value_gate_v0.1", "weather.calibration.feature_model", "active"),
    SchemaSpec("fleet_collection_health", "fleet_collection_health_v0.1", "weather.collection.collection_health", "active"),
    SchemaSpec("fleet_observability", "fleet_observability_v0.1", "weather.reporting.fleet_observability", "active"),
    SchemaSpec(
        "loop_current_code_soak",
        "loop_current_code_soak_v0.1",
        "weather.reporting.fleet_observability",
        "active",
        "Current-code loop soak proof with restart budgets, runtime identity, and duplicate-writer counts.",
    ),
    SchemaSpec(
        "snapshot_cadence_proof",
        "snapshot_cadence_proof_v0.1",
        "weather.reporting.fleet_observability",
        "active",
        "Per-market snapshot cadence proof used by broad live-forward SLO countability.",
    ),
    SchemaSpec("forecast_daily_legacy", "forecast_daily_legacy_v1", "weather.sources.forecast_history", "legacy"),
    SchemaSpec("forecast_ensemble_features", "forecast_ensemble_features_v0.1", "weather.sources.forecast_history", "active"),
    SchemaSpec(
        "forecast_history_coverage",
        "forecast_history_coverage_v0.1",
        "weather.sources.forecast_history",
        "active",
        "Fleet coverage payload for rich Open-Meteo forecast-history archives.",
    ),
    SchemaSpec("forecast_history_daily_issue", "forecast_history_daily_issue_v1", "weather.sources.forecast_history", "active"),
    SchemaSpec("forecast_history_long_legacy", "forecast_history_long_v2", "weather.sources.forecast_history", "legacy"),
    SchemaSpec(
        "forecast_history_long",
        "forecast_history_long_v3",
        "weather.sources.forecast_history",
        "active",
        supersedes=("forecast_history_long_v2",),
        migration_notes="Adds expanded rich hourly forecast fields for previous-run forecast history.",
    ),
    SchemaSpec("grib_probe", "grib_probe_v0.1", "weather.sources.grib_probe", "active"),
    SchemaSpec("ghcnh_composite_daily_view", "ghcnh_composite_daily_view_v0.1", "weather.sources.noaa_ghcnh_history", "active"),
    SchemaSpec("historical_backfill_plan", "historical_backfill_plan_v1", "weather.collection.historical_backfill_plan", "active"),
    SchemaSpec("historical_backfill_run", "historical_backfill_run_v1", "weather.collection.historical_backfill_runner", "active"),
    SchemaSpec("historical_backfill_status", "historical_backfill_status_v1", "weather.collection.historical_backfill_runner", "active"),
    SchemaSpec("historical_fallbacks", "historical_fallbacks_v0.1", "weather.sources.historical_fallbacks", "active"),
    SchemaSpec("historical_daily_native", "historical_daily_native_v1", "weather.sources.historical_schema", "active"),
    SchemaSpec("historical_data_audit_fleet", "historical_data_audit_fleet_v0.1", "weather.reporting.data_auditor", "active"),
    SchemaSpec("historical_hourly_native", "historical_hourly_native_v1", "weather.sources.historical_schema", "active"),
    SchemaSpec(
        "hourly_model_performance",
        "hourly_model_performance_v0.3",
        "weather.reporting.hourly_model_performance",
        "active",
        "Hour-by-hour settlement-scored model audit with promotion gate and remediation registry.",
        supersedes=("hourly_model_performance_v0.2",),
    ),
    SchemaSpec(
        "hourly_model_performance_legacy",
        "hourly_model_performance_v0.2",
        "weather.reporting.hourly_model_performance",
        "legacy",
    ),
    SchemaSpec(
        "hourly_performance_gate",
        "hourly_performance_gate_v0.1",
        "weather.reporting.hourly_model_performance",
        "active",
        "Fail-closed hourly-regime promotion gate with early-hour blockers.",
    ),
    SchemaSpec(
        "hourly_remediation_registry",
        "hourly_remediation_registry_v0.1",
        "weather.reporting.hourly_model_performance",
        "active",
        "Comparable registry rows for hourly remediation probe families and owners.",
    ),
    SchemaSpec(
        "price_free_model_learning",
        "price_free_model_learning_v0.1",
        "weather.reporting.price_free_model_learning",
        "active",
        "Settlement-scored model diagnostics for inactive or no-market days without Polymarket prices.",
    ),
    SchemaSpec(
        "candidate_hourly_performance",
        "candidate_hourly_performance_v0.1",
        "weather.reporting.candidate_hourly_performance",
        "active",
        "Local-hour candidate-variant audit over Item-69-style row exports.",
    ),
    SchemaSpec(
        "candidate_hourly_performance_gate",
        "candidate_hourly_performance_gate_v0.1",
        "weather.reporting.candidate_hourly_performance",
        "active",
        "Candidate-side early-hour gate for local capture-hour shadow variant evidence.",
    ),
    SchemaSpec(
        "ten_minute_model_performance",
        "ten_minute_model_performance_v0.1",
        "weather.reporting.ten_minute_model_performance",
        "active",
        "Settlement-scored model audit and weak-slot watchlist by 10-minute local capture slot.",
    ),
    SchemaSpec(
        "ten_minute_performance_gate",
        "ten_minute_performance_gate_v0.1",
        "weather.reporting.ten_minute_model_performance",
        "active",
        "Current-serving promotion gate over top-decile 10-minute weak slots.",
    ),
    SchemaSpec(
        "candidate_ten_minute_performance_gate",
        "candidate_ten_minute_performance_gate_v0.1",
        "weather.reporting.ten_minute_model_performance",
        "active",
        "Candidate-side gate for Item-69-style row exports over the current 10-minute weak-slot watchlist.",
    ),
    SchemaSpec(
        "predawn_weak_slot_repair",
        "predawn_weak_slot_repair_v0.1",
        "weather.reporting.predawn_weak_slot_repair",
        "active",
        "Predawn weak-slot winner-centering repair validation with time-split and non-predawn guardrails.",
    ),
    SchemaSpec(
        "late_day_lock_in_repair",
        "late_day_lock_in_repair_v0.1",
        "weather.reporting.late_day_lock_in_repair",
        "active",
        "Late-day high-has-stood lock-in saturation validation with over-lock guardrails.",
    ),
    SchemaSpec(
        "winner_underpricing_casebook",
        "winner_underpricing_casebook_v0.1",
        "weather.reporting.winner_underpricing_casebook",
        "active",
        "Development casebook of early snapshots where market ranks the eventual winner better than the no-market candidate.",
    ),
    SchemaSpec(
        "forecast_pressure_tilt_validation",
        "forecast_pressure_tilt_validation_v0.1",
        "weather.reporting.forecast_pressure_tilt_validation",
        "active",
        "Development time-split validation for no-market forecast-relative probability tilts.",
    ),
    SchemaSpec(
        "candidate_rank_sharpening_validation",
        "candidate_rank_sharpening_validation_v0.1",
        "weather.reporting.candidate_rank_sharpening_validation",
        "active",
        "Development time-split validation for no-market candidate-rank probability shaping.",
    ),
    SchemaSpec(
        "forecast_side_rank_validation",
        "forecast_side_rank_validation_v0.1",
        "weather.reporting.forecast_side_rank_validation",
        "active",
        "Development time-split validation for no-market forecast-side candidate-rank repairs.",
    ),
    SchemaSpec(
        "variant_basket_selection_validation",
        "variant_basket_selection_validation_v0.1",
        "weather.reporting.variant_basket_selection_validation",
        "active",
        "Development time-split validation for selecting among existing no-market variant branches.",
    ),
    SchemaSpec("historical_source_manifest", "historical_source_manifest_v1", "weather.sources.historical_schema", "active"),
    SchemaSpec("ingest_quality_gate", "ingest_quality_gate_v0.1", "weather.operations.daily_refresh", "active"),
    SchemaSpec("late_day_model_coefs", "late_day_model_coefs_v0.1", "weather.calibration.feature_model", "active"),
    SchemaSpec("live_forward_slo", "live_forward_slo_v0.1", "weather.reporting.fleet_observability", "active"),
    SchemaSpec(
        "live_source_status_cases",
        "live_source_status_cases_v0.1",
        "weather.reporting.source_redundancy",
        "active",
        "Generated cases explaining live source freshness, failure, and stale-source status.",
    ),
    SchemaSpec(
        "info_event_calendar",
        "info_event_calendar_v0.1",
        "weather.market.info_event_calendar",
        "active",
        "Per-market scheduled information-event calendar and quote-pull gate state.",
    ),
    SchemaSpec("mm_known_edge_map", "mm_known_edge_map_v0.2", "weather.market.mm_paper", "active"),
    SchemaSpec("mm_known_edge_map_legacy", "mm_known_edge_map_v0.1", "weather.market.mm_paper", "legacy"),
    SchemaSpec(
        "mm_exchange_adapter",
        "mm_exchange_adapter_v0.1",
        "weather.market.mm_exchange",
        "active",
        "Keyless exchange-adapter diagnostics, live-gate checks, and reconciliation artifact.",
    ),
    SchemaSpec("mm_negative_risk_simulation", "mm_negative_risk_simulation_v0.1", "weather.market.mm_risk", "active"),
    SchemaSpec("mm_paper", "mm_paper_v0.1", "weather.market.mm_paper", "active"),
    SchemaSpec(
        "early_hour_market_guardrail",
        "early_hour_market_guardrail_v0.1",
        "weather.market.mm_policy",
        "active",
        "Market-local early-hour trust bands and risk-only market-aware quote guardrail metadata.",
    ),
    SchemaSpec(
        "early_hour_market_guardrail_shadow",
        "early_hour_market_guardrail_shadow_v0.1",
        "weather.market.mm_paper",
        "active",
        "Paper-trading comparison of base, early-hour capped, and market-aware guardrail policies.",
    ),
    SchemaSpec(
        "mm_platform_verification",
        "mm_platform_verification_v0.1",
        "weather.market.market_making_run",
        "active",
        "Live-pilot platform, account, wallet, fee, reward, and API-semantics verification evidence.",
    ),
    SchemaSpec("mm_policy", "mm_policy_v0.2", "weather.market.mm_policy", "active", supersedes=("mm_policy_v0.1",)),
    SchemaSpec("mm_policy_legacy", "mm_policy_v0.1", "weather.market.mm_policy", "legacy"),
    SchemaSpec("mm_quote_intent", "mm_quote_intent_v0.2", "weather.market.mm_policy", "active", supersedes=("mm_quote_intent_v0.1",)),
    SchemaSpec("mm_quote_intent_legacy", "mm_quote_intent_v0.1", "weather.market.mm_policy", "legacy"),
    SchemaSpec("mm_run", "mm_run_v0.2", "weather.market.market_making_run", "active"),
    SchemaSpec("mm_run_legacy", "mm_run_v0.1", "weather.market.market_making_run", "legacy", supersedes=()),
    SchemaSpec(
        "taker_bot_run",
        "taker_bot_run_v0.1",
        "weather.market.taker_bot",
        "active",
        "Daily keyless paper taker-bot run, pretend fills, spend ledger, and P&L artifact.",
    ),
    SchemaSpec(
        "taker_settlement_finalization",
        "taker_settlement_finalization_v0.1",
        "weather.market.taker_bot",
        "active",
        "Post-settlement taker fill reconciliation against finalized market-day labels.",
    ),
    SchemaSpec(
        "live_forward_gate",
        "live_forward_gate_v0.2",
        "weather.market.live_forward_gate",
        "active",
        "Live-forward countability gate with evidence-mode adjustment fields.",
        supersedes=("live_forward_gate_v0.1",),
    ),
    SchemaSpec("live_forward_gate_legacy", "live_forward_gate_v0.1", "weather.market.live_forward_gate", "legacy"),
    SchemaSpec("mrms_precip", "mrms_precip_v0.1", "weather.sources.mrms_precip", "active"),
    SchemaSpec(
        "toronto_official_source_health",
        "toronto_official_source_health_v0.1",
        "weather.model.model_sources",
        "active",
        "Toronto official-source health artifact for ECCC runtime hardening and fallback diagnostics.",
    ),
    SchemaSpec(
        "reanalysis_synoptic_features",
        "reanalysis_synoptic_features_v0.4",
        "weather.sources.reanalysis_synoptic",
        "active",
        "Gated ERA5/reanalysis antecedent-state, soil-dryness, cloud, radiation, pressure, pressure-level, teleconnection, and static city-context feature sidecar.",
        supersedes=("reanalysis_synoptic_features_v0.3",),
    ),
    SchemaSpec(
        "pressure_level_cache_status",
        "pressure_level_cache_status_v0.1",
        "weather.sources.reanalysis_synoptic",
        "active",
        "Repeatable status report for cached NOAA PSL pressure-level files and requested-date metric coverage.",
    ),
    SchemaSpec(
        "reanalysis_sidecar_coverage_audit",
        "reanalysis_sidecar_coverage_audit_v0.1",
        "weather.reporting.reanalysis_sidecar_coverage_audit",
        "active",
        "Replay-window feature-group coverage audit for reanalysis/synoptic sidecars.",
    ),
    SchemaSpec("model_artifact_registry", "model_artifact_registry_v0.1", "weather.artifacts", "active"),
    SchemaSpec("model_artifact_size_audit", "model_artifact_size_audit_v0.1", "weather.artifacts", "active"),
    SchemaSpec(
        "model_artifact_externalization",
        "model_artifact_externalization_v0.1",
        "weather.artifacts",
        "active",
        "Restore manifest for Git LFS or externally stored model artifacts.",
    ),
    SchemaSpec(
        "model_artifact_promotion_preflight",
        "model_artifact_promotion_preflight_v0.1",
        "weather.artifacts",
        "active",
        "Local/CI preflight for artifact storage thresholds and active variant artifact paths.",
    ),
    SchemaSpec("model_variant_registry", "model_variant_registry_v0.1", "weather.reporting.variant_registry", "active"),
    SchemaSpec(
        "multi_variant_shadow_attribution",
        "multi_variant_shadow_attribution_v0.1",
        "weather.reporting.multi_variant_shadow",
        "active",
        "Optional attribution extension fields and sidecar rows for multi-variant shadow diagnostics.",
    ),
    SchemaSpec(
        "model_variant_registry_audit",
        "model_variant_registry_audit_v0.1",
        "weather.reporting.variant_registry",
        "active",
        "Audit artifact for active model-variant export contracts, artifact paths, and evidence coverage.",
    ),
    SchemaSpec("model_variant_evidence_growth", "model_variant_evidence_growth_v0.1", "weather.reporting.variant_evidence_growth", "active"),
    SchemaSpec(
        "independent_evidence_sla",
        "independent_evidence_sla_v0.1",
        "weather.reporting.variant_evidence_growth",
        "active",
        "Independent settled-evidence growth and sample-SLA artifact for variant evaluation.",
    ),
    SchemaSpec("nightly_retrain", "nightly_retrain_v0.1", "weather.operations.nightly_retrain", "active"),
    SchemaSpec(
        "settled_day_freshness",
        "settled_day_freshness_v0.1",
        "weather.operations.settled_day_freshness",
        "active",
        "Freshness and repair artifact for newly settled market-day labels, ledgers, and folder-local settlement copies.",
    ),
    SchemaSpec(
        "nightly_retrain_sla_status",
        "nightly_retrain_sla_status_v0.1",
        "weather.operations.nightly_retrain",
        "active",
    ),
    SchemaSpec(
        "loop_artifact_integrity",
        "loop_artifact_integrity_v0.1",
        "weather.reporting.fleet_observability",
        "active",
    ),
    SchemaSpec(
        "loop_jsonl_repair",
        "loop_jsonl_repair_v0.1",
        "weather.operations.loop_jsonl_repair",
        "active",
        "Audit and quarantine artifact for malformed loop JSONL/log lines.",
    ),
    SchemaSpec(
        "model_history_cache_legacy",
        "model_history_cache_v0.1",
        "weather.reporting.model_history",
        "legacy",
    ),
    SchemaSpec(
        "model_history_cache",
        "model_history_cache_v0.2",
        "weather.reporting.model_history",
        "active",
        supersedes=("model_history_cache_v0.1",),
        migration_notes="Adds winner-band catch-up diagnostics by location, day, and location-hour.",
    ),
    SchemaSpec("multi_variant_shadow", "multi_variant_shadow_v0.1", "weather.reporting.multi_variant_shadow", "active"),
    SchemaSpec(
        "pooled_feature_subset",
        "pooled_feature_subset_v0.1",
        "weather.calibration.pooled_feature_model",
        "active",
        "Feature-subset contract embedded in pooled band artifacts.",
    ),
    SchemaSpec(
        "pooled_all_market_band_hgb",
        "pooled_all_market_band_hgb_v0.1",
        "weather.calibration.pooled_feature_model",
        "active",
        "All-market native-unit direct market-band candidate artifact for the Item 35 baseline lane.",
    ),
    SchemaSpec(
        "pooled_all_market_band_hgb_exact_winner",
        "pooled_all_market_band_hgb_exact_winner_v0.1",
        "weather.calibration.pooled_feature_model",
        "active",
        "All-market native-unit direct market-band candidate with exact-winner catch-up postprocess.",
    ),
    SchemaSpec(
        "pooled_feature_band_hgb_forecast_profile",
        "pooled_feature_band_hgb_forecast_profile_v0.1",
        "weather.calibration.pooled_feature_model",
        "active",
        "Forecast-profile feature-subset pooled band artifact for early-day calibration probes.",
    ),
    SchemaSpec("pooled_feature_band_hgb_exact_winner", "pooled_feature_band_hgb_v0.4", "weather.calibration.pooled_feature_model", "active"),
    SchemaSpec("pooled_feature_band_hgb_dynamic_source", "pooled_feature_band_hgb_v0.5", "weather.calibration.pooled_feature_model", "active"),
    SchemaSpec("pooled_feature_band_hgb", "pooled_feature_band_hgb_v0.3", "weather.calibration.pooled_feature_model", "active"),
    SchemaSpec(
        "density_forecast_relative",
        "density_forecast_relative_v0.1",
        "weather.calibration.pooled_feature_model",
        "active",
        "Forecast-relative density projection calibration context artifact.",
    ),
    SchemaSpec(
        "density_market_band_postprocess",
        "density_market_band_postprocess_v0.2",
        "weather.calibration.pooled_feature_model",
        "active",
        "Holdout-selected market-band postprocess metadata for continuous-density projections.",
    ),
    SchemaSpec(
        "pooled_continuous_density_hgb",
        "pooled_continuous_density_hgb_v0.7",
        "weather.calibration.pooled_feature_model",
        "active",
        "All-market canonical-F continuous-density candidate artifact with holdout market-band Brier shape tuning and forecast-relative density-band postprocess.",
        supersedes=("pooled_continuous_density_hgb_v0.6",),
    ),
    SchemaSpec("pooled_continuous_density_hgb_v0_6_legacy", "pooled_continuous_density_hgb_v0.6", "weather.calibration.pooled_feature_model", "legacy"),
    SchemaSpec("pooled_continuous_density_hgb_v0_5_legacy", "pooled_continuous_density_hgb_v0.5", "weather.calibration.pooled_feature_model", "legacy"),
    SchemaSpec("pooled_continuous_density_hgb_v0_4_legacy", "pooled_continuous_density_hgb_v0.4", "weather.calibration.pooled_feature_model", "legacy"),
    SchemaSpec("pooled_continuous_density_hgb_v0_3_legacy", "pooled_continuous_density_hgb_v0.3", "weather.calibration.pooled_feature_model", "legacy"),
    SchemaSpec("pooled_continuous_density_hgb_v0_2_legacy", "pooled_continuous_density_hgb_v0.2", "weather.calibration.pooled_feature_model", "legacy"),
    SchemaSpec("pooled_continuous_density_hgb_legacy", "pooled_continuous_density_hgb_v0.1", "weather.calibration.pooled_feature_model", "legacy"),
    SchemaSpec("pooled_feature_hgb", "pooled_feature_hgb_v0.1", "weather.calibration.pooled_feature_model", "legacy"),
    SchemaSpec("progress_audit", "progress_audit_v0.1", "weather.reporting.progress_audit", "active"),
    SchemaSpec(
        "core_model_trend_claim",
        "core_model_trend_claim_v0.1",
        "weather.reporting.progress_audit",
        "active",
        "Core model day-over-day skill trend claim and evidence gate artifact.",
    ),
    SchemaSpec("promotion_corpus", "promotion_corpus_v0.1", "weather.reporting.promotion_corpus", "active"),
    SchemaSpec("promotion_refresh", "promotion_refresh_v0.1", "weather.reporting.promotion_refresh", "active"),
    SchemaSpec(
        "promotion_refresh_lifecycle",
        "promotion_refresh_incomplete_v0.1",
        "weather.reporting.promotion_refresh",
        "active",
        "Started, complete, or incomplete promotion-refresh lifecycle manifest written outside artifact reserve gates.",
    ),
    SchemaSpec(
        "market_skill_gap_experiment",
        "market_skill_gap_experiment_v0.1",
        "weather.reporting.promotion_refresh",
        "active",
        "Per-market skill-gap experiment ownership artifact emitted by promotion refresh.",
    ),
    SchemaSpec("runtime_identity", "runtime_identity_v0.1", "weather.operations.runtime_identity", "active"),
    SchemaSpec("long_job_guard", "long_job_guard_v0.1", "weather.operations.long_job_guard", "active"),
    SchemaSpec(
        "replay_input_status",
        "replay_input_status_v0.1",
        "weather.backtesting.replay",
        "active",
        "Status payload describing reconstructed replay inputs and missing replay material.",
    ),
    SchemaSpec(
        "replay_status_backfill",
        "replay_status_backfill_v0.1",
        "weather.operations.replay_status_backfill",
        "active",
        "Repair-command artifact for settled-day replay status backfills.",
    ),
    SchemaSpec(
        "market_making_daily_roll",
        "market_making_daily_roll_v0.2",
        "weather.operations.market_making_daily_roll",
        "active",
        "Daily launcher status for paper-live-forward market-making runs with evidence-mode classification.",
        supersedes=("market_making_daily_roll_v0.1",),
    ),
    SchemaSpec(
        "market_making_daily_roll_legacy",
        "market_making_daily_roll_v0.1",
        "weather.operations.market_making_daily_roll",
        "legacy",
        "Legacy daily launcher status before evidence-mode classification.",
    ),
    SchemaSpec(
        "taker_bot_daily_roll",
        "taker_bot_daily_roll_v0.1",
        "weather.operations.taker_bot_daily_roll",
        "active",
        "Daily launcher status for paper taker-bot runs.",
    ),
    SchemaSpec(
        "taker_strategy_registry",
        "taker_strategy_registry_v0.1",
        "weather.market.taker_bot",
        "active",
        "Named taker strategy arms, config overrides, attribution, and control/candidate metadata.",
    ),
    SchemaSpec(
        "taker_strategy_report",
        "taker_strategy_report_v0.1",
        "weather.market.taker_bot",
        "active",
        "Per-run taker strategy comparison summary with arm-level P&L and countability.",
    ),
    SchemaSpec(
        "taker_strategy_bakeoff",
        "taker_strategy_bakeoff_v0.1",
        "weather.market.taker_bot",
        "active",
        "Settlement-scored replay bakeoff for taker strategy arms and promotion gates.",
    ),
    SchemaSpec(
        "market_making_tape_encoding",
        "market_making_tape_encoding_v0.1",
        "weather.operations.market_making_tape_encoding",
        "active",
        "Audit and repair artifact for legacy non-UTF-8 market-making and CLOB CSV tapes.",
    ),
    SchemaSpec(
        "module_size_audit",
        "module_size_audit_v0.1",
        "weather.operations.module_size_audit",
        "active",
        "Large-module line-count audit and ownership split map.",
    ),
    SchemaSpec(
        "tape_backup_manifest",
        "tape_backup_manifest_v0.1",
        "weather.operations.tape_backup",
        "active",
        "Checksum manifest for irreplaceable raw/live evidence tape backups.",
    ),
    SchemaSpec(
        "tape_retention_policy",
        "tape_retention_policy_v0.1",
        "weather.operations.tape_backup",
        "active",
        "Recoverability classes and retention rules for backup manifests.",
    ),
    SchemaSpec(
        "tape_restore_drill",
        "tape_restore_drill_v0.1",
        "weather.operations.tape_backup",
        "active",
        "Restore-drill result for verifying backup hashes, schemas, and tape counts.",
    ),
    SchemaSpec(
        "tape_backup_job",
        "tape_backup_job_v0.1",
        "weather.operations.tape_backup",
        "active",
        "Single tape-backup job status emitted by backup orchestration.",
    ),
    SchemaSpec(
        "tape_backup_unmanifested_cleanup",
        "tape_backup_unmanifested_cleanup_v0.1",
        "weather.operations.tape_backup",
        "active",
        "Plan and apply report for removing unmanifested same-root backup leftovers.",
    ),
    SchemaSpec("shadow_ab_monitor", "shadow_ab_monitor_v0.1", "weather.reporting.shadow_ab_monitor", "active"),
    SchemaSpec("snapshot_evaluation", "snapshot_evaluation_v0.1", "weather.reporting.snapshot_evaluation", "active"),
    SchemaSpec(
        "late_day_warm_side_cases",
        "late_day_warm_side_cases_v0.1",
        "weather.reporting.disagreement_casebook",
        "active",
        "Late-day warm-side disagreement casebook slice artifact.",
    ),
    SchemaSpec("source_redundancy", "source_redundancy_v0.3", "weather.reporting.source_redundancy", "active"),
    SchemaSpec("supplemental_station_registry", "supplemental_station_registry_v0.1", "weather.sources.supplemental_stations", "active"),
    SchemaSpec("supplemental_station_validation", "supplemental_station_validation_v0.1", "weather.sources.supplemental_station_validation", "active"),
    SchemaSpec("distribution_components", "toronto_distribution_components_v0.1", "weather.model.model_distribution", "active"),
    SchemaSpec("reanalysis_synoptic_features_legacy_v0_3", "reanalysis_synoptic_features_v0.3", "weather.sources.reanalysis_synoptic", "legacy"),
    SchemaSpec("reanalysis_synoptic_features_legacy_v0_2", "reanalysis_synoptic_features_v0.2", "weather.sources.reanalysis_synoptic", "legacy"),
    SchemaSpec("reanalysis_synoptic_features_legacy", "reanalysis_synoptic_features_v0.1", "weather.sources.reanalysis_synoptic", "legacy"),
    SchemaSpec("feature_store_legacy_v1_12", "toronto_feature_store_v1.12", "weather.model.feature_store", "legacy"),
    SchemaSpec("feature_store_legacy_v1_11", "toronto_feature_store_v1.11", "weather.model.feature_store", "legacy"),
    SchemaSpec("feature_store_legacy_v1_10", "toronto_feature_store_v1.10", "weather.model.feature_store", "legacy"),
    SchemaSpec("feature_store_legacy_v1_9", "toronto_feature_store_v1.9", "weather.model.feature_store", "legacy"),
    SchemaSpec("feature_store_legacy_v1_8", "toronto_feature_store_v1.8", "weather.model.feature_store", "legacy"),
    SchemaSpec("feature_store_legacy_v1_7", "toronto_feature_store_v1.7", "weather.model.feature_store", "legacy"),
    SchemaSpec("feature_store_legacy_v1_6", "toronto_feature_store_v1.6", "weather.model.feature_store", "legacy"),
    SchemaSpec("feature_store_legacy_v1_5", "toronto_feature_store_v1.5", "weather.model.feature_store", "legacy"),
    SchemaSpec("feature_store_legacy_v1_4", "toronto_feature_store_v1.4", "weather.model.feature_store", "legacy"),
    SchemaSpec("feature_store_legacy_v1_2", "toronto_feature_store_v1.2", "weather.model.feature_store", "legacy"),
    SchemaSpec("feature_store_legacy_v1_3", "toronto_feature_store_v1.3", "weather.model.feature_store", "legacy"),
    SchemaSpec("feature_store_legacy_v1_1", "toronto_feature_store_v1.1", "weather.model.feature_store", "legacy"),
    SchemaSpec("feature_store_legacy_v1_0", "toronto_feature_store_v1.0", "weather.model.feature_store", "legacy"),
    SchemaSpec("feature_store_legacy_v0_9", "toronto_feature_store_v0.9", "weather.model.feature_store", "legacy"),
    SchemaSpec("feature_store_legacy_v0_8", "toronto_feature_store_v0.8", "weather.model.feature_store", "legacy"),
    SchemaSpec("feature_store_legacy_v0_7", "toronto_feature_store_v0.7", "weather.model.feature_store", "legacy"),
    SchemaSpec("feature_store_legacy", "toronto_feature_store_v0.6", "weather.model.feature_store", "legacy"),
    SchemaSpec("feature_store_legacy_v0_5", "toronto_feature_store_v0.5", "weather.model.feature_store", "legacy"),
    SchemaSpec("replay_inputs_reconstructed", "toronto_replay_inputs_reconstructed_v0.1", "weather.backtesting.replay", "active"),
    SchemaSpec("replay_inputs", "toronto_replay_inputs_v0.1", "weather.collection.snapshot_tracker", "active"),
    SchemaSpec("weather_model_replay_identity", "weather_model_replay_identity_v0.1", "weather.model.model_identity", "active"),
    SchemaSpec("wu_daily_legacy", "wu_daily_native_v1", "weather.sources.daily_summary", "legacy"),
    SchemaSpec("wu_hourly", "wu_hourly_native_v1", "weather.sources.wu_history", "active"),
    SchemaSpec("wu_max_since_7_validation", "wu_max_since_7_validation_v0.1", "weather.reporting.wu_max_since_7_validation", "active"),
)

SCHEMAS_BY_NAME = {spec.name: spec for spec in REGISTERED_SCHEMAS}
SCHEMAS_BY_VERSION = {spec.version: spec for spec in REGISTERED_SCHEMAS}

SCHEMA_LITERAL_RE = re.compile(
    r"""['"]([a-z][a-z0-9]*(?:_[a-z0-9]+)*_v\d+(?:\.\d+)?|toronto_feature_store_v\d+(?:\.\d+)?)['"]"""
)
DEFAULT_SCAN_SUFFIXES = {".py"}
DEFAULT_IGNORE_DIRS = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "artifacts",
    "data",
    "node_modules",
    "venv",
}


def schema_version(name: str) -> str:
    """Return the active schema version for a registered schema name."""
    try:
        return SCHEMAS_BY_NAME[name].version
    except KeyError as exc:
        raise KeyError(f"unknown schema registry name: {name}") from exc


def registered_schema(name: str) -> dict:
    return asdict(SCHEMAS_BY_NAME[name])


def registry_payload() -> dict:
    return {
        "schema_version": SCHEMA_REGISTRY_SCHEMA_VERSION,
        "schemas": [asdict(spec) for spec in REGISTERED_SCHEMAS],
    }


def validate_schema_version(name: str, version: str) -> bool:
    return schema_version(name) == version


def _iter_scan_files(paths, suffixes=DEFAULT_SCAN_SUFFIXES):
    for item in paths:
        path = Path(item)
        if not path.exists():
            continue
        if path.is_file():
            if path.suffix in suffixes:
                yield path
            continue
        for child in path.rglob("*"):
            if any(part in DEFAULT_IGNORE_DIRS for part in child.parts):
                continue
            if child.is_file() and child.suffix in suffixes:
                yield child


def scan_schema_literals(paths=("src",), suffixes=DEFAULT_SCAN_SUFFIXES):
    """Find schema-looking string literals in source files."""
    rows = []
    for path in sorted(set(_iter_scan_files(paths, suffixes=suffixes))):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_no, line in enumerate(lines, start=1):
            for match in SCHEMA_LITERAL_RE.finditer(line):
                version = match.group(1)
                spec = SCHEMAS_BY_VERSION.get(version)
                rows.append({
                    "path": str(path),
                    "line": line_no,
                    "version": version,
                    "registered": spec is not None,
                    "schema_name": spec.name if spec else None,
                })
    return rows


def audit_payload(paths=("src",)) -> dict:
    discovered = scan_schema_literals(paths)
    unregistered_versions = sorted({
        row["version"] for row in discovered if not row["registered"]
    })
    return {
        "schema_version": SCHEMA_REGISTRY_SCHEMA_VERSION,
        "registered_count": len(REGISTERED_SCHEMAS),
        "discovered_literal_count": len(discovered),
        "unregistered_version_count": len(unregistered_versions),
        "registered_schemas": [asdict(spec) for spec in REGISTERED_SCHEMAS],
        "unregistered_versions": unregistered_versions,
        "discovered_literals": discovered,
    }


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def cmd_list(args):
    payload = registry_payload()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    for spec in REGISTERED_SCHEMAS:
        print(f"{spec.name}: {spec.version} ({spec.status})")


def cmd_audit(args):
    payload = audit_payload(args.paths)
    if args.out:
        write_json(args.out, payload)
        print(f"Wrote schema registry audit to {args.out}")
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    print(
        "registered={registered_count} discovered={discovered_literal_count} "
        "unregistered_versions={unregistered_version_count}".format(**payload)
    )
    if args.strict and payload["unregistered_version_count"]:
        raise SystemExit(1)


def build_parser():
    parser = argparse.ArgumentParser(description="Schema registry and migration audit tooling.")
    sub = parser.add_subparsers(dest="command", required=True)

    list_cmd = sub.add_parser("list")
    list_cmd.add_argument("--json", action="store_true")
    list_cmd.set_defaults(func=cmd_list)

    audit_cmd = sub.add_parser("audit")
    audit_cmd.add_argument("--paths", nargs="+", default=["src"])
    audit_cmd.add_argument("--out", default="")
    audit_cmd.add_argument("--strict", action="store_true")
    audit_cmd.set_defaults(func=cmd_audit)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
