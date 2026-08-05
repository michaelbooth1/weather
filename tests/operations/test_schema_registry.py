import os
import sys
import tempfile
import unittest
from pathlib import Path
from weather.schema_registry import (  # noqa: E402
    EXCLUDED_SCHEMA_LITERALS,
    REGISTERED_SCHEMAS,
    SCHEMA_REGISTRY_SCHEMA_VERSION,
    audit_payload,
    registry_payload,
    schema_version,
    validate_schema_version,
)
from weather.schema_registry_data import INTENTIONAL_SCHEMA_VERSION_ALIASES  # noqa: E402


class TestSchemaRegistry(unittest.TestCase):
    def test_registry_lookup_returns_public_versions(self):
        self.assertEqual(
            schema_version("residual_distribution_v1"),
            "residual_distribution_v1_v0.2",
        )
        self.assertEqual(
            schema_version("residual_distribution_training_corpus"),
            "residual_distribution_training_corpus_v2",
        )
        self.assertEqual(
            schema_version("residual_distribution_v1_forward_attestation"),
            "residual_distribution_v1_forward_attestation_v1",
        )
        self.assertEqual(schema_version("feature_store"), "toronto_feature_store_v1.15")
        self.assertEqual(schema_version("model_history_cache"), "model_history_cache_v0.4")
        self.assertEqual(schema_version("feature_quality_quarantine"), "feature_quality_quarantine_v0.1")
        self.assertEqual(schema_version("reanalysis_synoptic_features"), "reanalysis_synoptic_features_v0.5")
        self.assertEqual(schema_version("pressure_level_cache_status"), "pressure_level_cache_status_v0.1")
        self.assertEqual(schema_version("reanalysis_sidecar_coverage_audit"), "reanalysis_sidecar_coverage_audit_v0.1")
        self.assertEqual(schema_version("historical_coverage"), "historical_coverage_v1")
        self.assertEqual(schema_version("forecast_history_coverage"), "forecast_history_coverage_v0.1")
        self.assertEqual(schema_version("forecast_history_long"), "forecast_history_long_v3")
        self.assertEqual(schema_version("daily_learning"), "daily_learning_v0.1")
        self.assertEqual(schema_version("automatic_experiment_queue"), "automatic_experiment_queue_v0.2")
        self.assertEqual(schema_version("experiment_queue_results"), "experiment_queue_results_v0.1")
        self.assertEqual(
            schema_version("executable_experiment_manifest"),
            "executable_experiment_manifest_v0.1",
        )
        self.assertEqual(
            schema_version("executable_experiment_result"),
            "executable_experiment_result_v0.1",
        )
        self.assertEqual(
            schema_version("mm_scoring_projection"),
            "mm_scoring_projection_v0.1",
        )
        self.assertEqual(
            schema_version("maker_scoring_input_binding"),
            "maker_scoring_input_binding_v0.1",
        )
        self.assertEqual(
            schema_version("mm_execution_evidence"),
            "mm_execution_evidence_v0.1",
        )
        self.assertEqual(schema_version("variant_learning_operational_gate"), "variant_learning_operational_gate_v0.1")
        self.assertEqual(schema_version("live_variant_predictions"), "live_variant_predictions_v0.2")
        self.assertEqual(schema_version("replay_inputs"), "toronto_replay_inputs_v0.2")
        self.assertEqual(schema_version("multi_variant_shadow_attribution"), "multi_variant_shadow_attribution_v0.1")
        self.assertEqual(schema_version("model_variant_registry_audit"), "model_variant_registry_audit_v0.1")
        self.assertEqual(schema_version("roadmap_backlog"), "roadmap_backlog_v0.1")
        self.assertEqual(
            schema_version("settlement_source_revision_audit"),
            "settlement_source_revision_audit_v0.1",
        )
        self.assertEqual(
            schema_version("observed_floor_safety_monitor"),
            "observed_floor_safety_monitor_v0.1",
        )
        self.assertEqual(
            schema_version("proper_scoring_reliability_scorecard"),
            "proper_scoring_reliability_scorecard_v0.1",
        )
        self.assertEqual(schema_version("winner_rank_parity"), "winner_rank_parity_v0.1")
        self.assertEqual(
            schema_version("live_variant_settlement_scorecard"),
            "live_variant_settlement_scorecard_v0.1",
        )
        self.assertEqual(
            schema_version("model_market_skill_history"),
            "model_market_skill_history_v0.1",
        )
        self.assertEqual(
            schema_version("model_market_skill_summary"),
            "model_market_skill_summary_v0.1",
        )
        self.assertEqual(schema_version("release_manifest"), "release_manifest_v0.1")
        self.assertEqual(
            schema_version("first_inactive_release_bootstrap"),
            "first_inactive_release_bootstrap_v0.1",
        )
        self.assertEqual(
            schema_version("active_release_pointer"),
            "active_release_pointer_v0.1",
        )
        self.assertEqual(
            schema_version("release_promotion_decision"),
            "release_promotion_decision_v0.1",
        )
        self.assertEqual(
            schema_version("release_market_day_boundary"),
            "release_market_day_boundary_v0.1",
        )
        self.assertEqual(
            schema_version("capture_resource_gate"),
            "capture_resource_gate_v0.1",
        )
        self.assertEqual(
            schema_version("release_admissibility_receipt"),
            "release_admissibility_receipt_v1",
        )
        self.assertEqual(
            schema_version("release_admissibility_clock"),
            "release_admissibility_clock_v1",
        )
        self.assertEqual(
            schema_version("all_shadow_release_bootstrap_receipt"),
            "all_shadow_release_bootstrap_receipt_v1",
        )
        self.assertEqual(
            schema_version("point_in_time_analytical_contract"),
            "point_in_time_analytical_contract_v0.1",
        )
        self.assertEqual(
            schema_version("point_in_time_materializer"),
            "point_in_time_materializer_v0.1",
        )
        self.assertEqual(
            schema_version("point_in_time_validation_plan"),
            "point_in_time_validation_plan_v0.1",
        )
        self.assertEqual(
            schema_version("production_point_in_time_preselection"),
            "production_point_in_time_preselection_v1",
        )
        self.assertEqual(
            schema_version("production_point_in_time_preselection_source"),
            "production_point_in_time_preselection_source_v1",
        )
        self.assertEqual(
            schema_version("point_in_time_candidate_training_graph"),
            "point_in_time_candidate_training_graph_v1",
        )
        self.assertEqual(
            schema_version("point_in_time_streaming_evaluation"),
            "point_in_time_streaming_evaluation_v0.1",
        )
        self.assertEqual(
            schema_version("base_model_serving_graph"),
            "base_model_serving_graph_v0.1",
        )
        self.assertEqual(
            schema_version("density_live_replay_parity"),
            "density_live_replay_parity_v0.1",
        )
        self.assertEqual(schema_version("clean_day_ledger"), "clean_day_ledger_v0.1")
        self.assertEqual(
            schema_version("unattended_cycle_ledger"),
            "unattended_cycle_ledger_v0.1",
        )
        self.assertEqual(
            schema_version("production_readiness_gate"),
            "production_readiness_gate_v0.1",
        )
        self.assertEqual(schema_version("june23_location_bias_repair"), "june23_location_bias_repair_v0.1")
        self.assertEqual(schema_version("afternoon_residual_centering"), "afternoon_residual_centering_v0.1")
        self.assertEqual(
            schema_version("weather_only_model_proof_packet"),
            "weather_only_model_proof_packet_v0.1",
        )
        self.assertEqual(
            schema_version("austin_hgb_requalification"),
            "austin_hgb_requalification_v0.1",
        )
        self.assertEqual(
            schema_version("austin_weather_model_hardening"),
            "austin_weather_model_hardening_v0.1",
        )
        self.assertEqual(schema_version("local_generated_state_cleanup"), "local_generated_state_cleanup_v0.1")
        self.assertEqual(schema_version("hourly_model_performance"), "hourly_model_performance_v0.3")
        self.assertEqual(schema_version("hourly_performance_gate"), "hourly_performance_gate_v0.1")
        self.assertEqual(schema_version("hourly_remediation_registry"), "hourly_remediation_registry_v0.1")
        self.assertEqual(schema_version("price_free_model_learning"), "price_free_model_learning_v0.1")
        self.assertEqual(schema_version("candidate_hourly_performance"), "candidate_hourly_performance_v0.1")
        self.assertEqual(schema_version("candidate_hourly_performance_gate"), "candidate_hourly_performance_gate_v0.1")
        self.assertEqual(schema_version("candidate_variant_replay_summary"), "candidate_variant_replay_summary_v0.1")
        self.assertEqual(schema_version("repair_integration"), "repair_integration_v0.1")
        self.assertEqual(schema_version("ten_minute_model_performance"), "ten_minute_model_performance_v0.1")
        self.assertEqual(schema_version("ten_minute_performance_gate"), "ten_minute_performance_gate_v0.1")
        self.assertEqual(
            schema_version("candidate_ten_minute_performance_gate"),
            "candidate_ten_minute_performance_gate_v0.1",
        )
        self.assertEqual(schema_version("predawn_weak_slot_repair"), "predawn_weak_slot_repair_v0.1")
        self.assertEqual(
            schema_version("predawn_weak_slot_parameter_sweep"),
            "predawn_weak_slot_parameter_sweep_v0.1",
        )
        self.assertEqual(
            schema_version("bottom_location_winner_centering"),
            "bottom_location_winner_centering_v0.1",
        )
        self.assertEqual(
            schema_version("exact_band_distance_zero_calibration"),
            "exact_band_distance_zero_calibration_v0.1",
        )
        self.assertEqual(
            schema_version("market_residual_repair_program"),
            "market_residual_repair_program_v0.1",
        )
        self.assertEqual(
            schema_version("current_max_trust_retrain_gate"),
            "current_max_trust_retrain_gate_v0.1",
        )
        self.assertEqual(
            schema_version("current_max_trust_retrain_evidence"),
            "current_max_trust_retrain_evidence_v0.1",
        )
        self.assertEqual(schema_version("config_inventory"), "config_inventory_v0.1")
        self.assertEqual(schema_version("location_registry"), "location_registry_v0.1")
        self.assertEqual(schema_version("location_market_events"), "location_market_events_v0.1")
        self.assertEqual(schema_version("nbm_probabilistic_tmax"), "nbm_probabilistic_tmax_v0.1")
        self.assertEqual(
            schema_version("forecast_payload_manifest"),
            "forecast_payload_manifest_v2",
        )
        self.assertEqual(
            schema_version("forecast_payload_extraction_identity_nbm_nbp"),
            "nbm_nbp_station_target_v1",
        )
        self.assertEqual(
            schema_version("forecast_payload_cas_migration_dry_run"),
            "forecast_payload_cas_migration_dry_run_v0.2",
        )
        self.assertEqual(
            schema_version("forecast_payload_storage_observability"),
            "forecast_payload_storage_observability_v0.1",
        )
        self.assertEqual(schema_version("late_day_lock_in_repair"), "late_day_lock_in_repair_v0.1")
        self.assertEqual(schema_version("winner_underpricing_casebook"), "winner_underpricing_casebook_v0.1")
        self.assertEqual(schema_version("forecast_pressure_tilt_validation"), "forecast_pressure_tilt_validation_v0.1")
        self.assertEqual(schema_version("candidate_rank_sharpening_validation"), "candidate_rank_sharpening_validation_v0.1")
        self.assertEqual(schema_version("forecast_side_rank_validation"), "forecast_side_rank_validation_v0.1")
        self.assertEqual(schema_version("forecast_profile_guardrails"), "forecast_profile_guardrails_v0.1")
        self.assertEqual(
            schema_version("item134_forecast_profile_disposition"),
            "item134_forecast_profile_disposition_v0.1",
        )
        self.assertEqual(
            schema_version("item135_cutoff_regime_disposition"),
            "item135_cutoff_regime_disposition_v0.1",
        )
        self.assertEqual(
            schema_version("item136_source_state_disposition"),
            "item136_source_state_disposition_v0.1",
        )
        self.assertEqual(
            schema_version("item138_weak_input_family_gate"),
            "item138_weak_input_family_gate_v0.1",
        )
        self.assertEqual(
            schema_version("item224_active_timesplit_logistic_repair"),
            "item224_active_timesplit_logistic_repair_v0.1",
        )
        self.assertEqual(
            schema_version("item48_promotion_readiness_acceptance"),
            "item48_promotion_readiness_acceptance_v0.1",
        )
        self.assertEqual(
            schema_version("item186_soil_antecedent_gate"),
            "item186_soil_antecedent_gate_v0.1",
        )
        self.assertEqual(
            schema_version("item186_soil_antecedent_settlement_gate"),
            "item186_soil_antecedent_settlement_gate_v0.1",
        )
        self.assertEqual(schema_version("forecast_radiation_gate"), "forecast_radiation_gate_v0.1")
        self.assertEqual(schema_version("forecast_smoke_gate"), "forecast_smoke_gate_v0.1")
        self.assertEqual(schema_version("global_model_guidance_gate"), "global_model_guidance_gate_v0.1")
        self.assertEqual(schema_version("nbm_probabilistic_tmax_gate"), "nbm_probabilistic_tmax_gate_v0.1")
        self.assertEqual(
            schema_version("nbm_probabilistic_tmax_settlement_scoring"),
            "nbm_probabilistic_tmax_settlement_scoring_v0.1",
        )
        self.assertEqual(schema_version("marine_contrast_gate"), "marine_contrast_gate_v0.1")
        self.assertEqual(schema_version("marine_water_contrast_features"), "marine_water_contrast_features_v0.1")
        self.assertEqual(schema_version("marine_water_contrast_backfill"), "marine_water_contrast_backfill_v0.1")
        self.assertEqual(schema_version("marine_gridded_sst_point"), "marine_gridded_sst_point_v0.1")
        self.assertEqual(schema_version("winner_band_signal_validation"), "winner_band_signal_validation_v0.1")
        self.assertEqual(schema_version("market_anchor_time_split_validation"), "market_anchor_time_split_validation_v0.2")
        self.assertEqual(schema_version("clob_coverage_audit"), "clob_coverage_audit_v0.3")
        self.assertEqual(schema_version("clob_capture_status"), "clob_capture_status_v0.1")
        self.assertEqual(
            schema_version("clob_enrichment_capture_status"),
            "clob_enrichment_capture_status_v0.1",
        )
        self.assertEqual(
            schema_version("clob_enrichment_loop_status"),
            "clob_enrichment_loop_status_v0.1",
        )
        self.assertEqual(schema_version("data_retention_inventory"), "data_retention_inventory_v0.1")
        self.assertEqual(
            schema_version("closed_market_day_archive_manifest"),
            "closed_market_day_archive_manifest_v0.1",
        )
        self.assertEqual(
            schema_version("closed_market_day_parquet_backfill"),
            "closed_market_day_parquet_backfill_v0.1",
        )
        self.assertEqual(
            schema_version("closed_market_day_parquet_incremental"),
            "closed_market_day_parquet_incremental_v0.1",
        )
        self.assertEqual(schema_version("event_day_manifest"), "event_day_manifest_v0.1")
        self.assertEqual(schema_version("event_metadata_validation"), "event_metadata_validation_v0.1")
        self.assertEqual(schema_version("event_day_manifest_backfill"), "event_day_manifest_backfill_v0.1")
        self.assertEqual(schema_version("event_day_manifest_writer"), "event_day_manifest_writer_v0.1")
        self.assertEqual(schema_version("cleanup_manifest"), "cleanup_manifest_v0.1")
        self.assertEqual(schema_version("cleanup_preflight"), "cleanup_preflight_v0.1")
        self.assertEqual(schema_version("model_artifact_externalization"), "model_artifact_externalization_v0.1")
        self.assertEqual(schema_version("model_artifact_promotion_preflight"), "model_artifact_promotion_preflight_v0.1")
        self.assertEqual(schema_version("module_size_audit"), "module_size_audit_v0.1")
        self.assertEqual(schema_version("structure_inventory"), "structure_inventory_v0.2")
        self.assertEqual(schema_version("pooled_continuous_density_hgb"), "pooled_continuous_density_hgb_v0.7")
        self.assertEqual(schema_version("pooled_all_market_band_hgb"), "pooled_all_market_band_hgb_v0.1")
        self.assertEqual(schema_version("promotion_allowlist"), "promotion_allowlist_v0.1")
        self.assertEqual(schema_version("source_missingness_location_gate"), "source_missingness_location_gate_v0.1")
        self.assertEqual(schema_version("pooled_all_market_band_hgb_exact_winner"), "pooled_all_market_band_hgb_exact_winner_v0.1")
        self.assertEqual(schema_version("pooled_f_retrain_location_gate"), "pooled_f_retrain_location_gate_v0.1")
        self.assertEqual(schema_version("serving_ordinal_smoothing_gate"), "serving_ordinal_smoothing_gate_v0.1")
        self.assertEqual(
            schema_version("served_distribution_calibration_contract"),
            "served_distribution_calibration_contract_v0.1",
        )
        self.assertEqual(
            schema_version("early_hour_positive_daily_first_gate"),
            "early_hour_positive_daily_first_gate_v0.1",
        )
        self.assertEqual(
            schema_version("physical_feature_family_ratchet"),
            "physical_feature_family_ratchet_v0.1",
        )
        self.assertEqual(
            schema_version("market_benchmark_residual_edge"),
            "market_benchmark_residual_edge_v0.1",
        )
        self.assertEqual(
            schema_version("market_beating_objective_scoreboard"),
            "market_beating_objective_scoreboard_v0.1",
        )
        self.assertEqual(
            schema_version("item147_winner_centering_disposition"),
            "item147_winner_centering_disposition_v0.1",
        )
        self.assertEqual(schema_version("market_hour_kind_bias"), "market_hour_kind_bias_v1")
        self.assertEqual(schema_version("live_forward_gate"), "live_forward_gate_v0.2")
        self.assertEqual(schema_version("market_making_daily_roll"), "market_making_daily_roll_v0.2")
        self.assertEqual(schema_version("early_hour_market_guardrail"), "early_hour_market_guardrail_v0.1")
        self.assertEqual(schema_version("early_hour_market_guardrail_shadow"), "early_hour_market_guardrail_shadow_v0.1")
        self.assertEqual(schema_version("taker_bot_run"), "taker_bot_run_v0.1")
        self.assertEqual(schema_version("taker_settlement_finalization"), "taker_settlement_finalization_v0.1")
        self.assertEqual(
            schema_version("taker_settled_finalization_projection"),
            "taker_settled_finalization_projection_v0.1",
        )
        self.assertEqual(
            schema_version("taker_settlement_finalization_watchdog"),
            "taker_settlement_finalization_watchdog_v0.1",
        )
        self.assertEqual(schema_version("taker_tail_casebook"), "taker_tail_casebook_v0.1")
        self.assertEqual(schema_version("trading_evidence_summary"), "trading_evidence_summary_v0.1")
        self.assertEqual(schema_version("taker_bot_daily_roll"), "taker_bot_daily_roll_v0.1")
        self.assertEqual(schema_version("taker_strategy_registry"), "taker_strategy_registry_v0.1")
        self.assertEqual(schema_version("taker_strategy_report"), "taker_strategy_report_v0.1")
        self.assertEqual(schema_version("taker_strategy_bakeoff"), "taker_strategy_bakeoff_v0.1")
        self.assertEqual(
            schema_version("taker_strategy_bakeoff_ledger_projection"),
            "taker_strategy_bakeoff_ledger_projection_v0.1",
        )
        self.assertEqual(
            schema_version("taker_profitability_artifact_verification"),
            "taker_profitability_artifact_verification_v0.1",
        )
        self.assertEqual(
            schema_version("taker_current_replay_profitability_verification"),
            "taker_current_replay_profitability_verification_v0.1",
        )
        self.assertEqual(
            schema_version("taker_profitability_artifact_verification_composite"),
            "taker_profitability_artifact_verification_v0.2",
        )
        self.assertEqual(schema_version("exchange_economics_snapshot"), "exchange_economics_snapshot_v0.1")
        self.assertEqual(schema_version("exchange_economics_drift"), "exchange_economics_drift_v0.1")
        self.assertEqual(schema_version("backtest_artifact_retention"), "backtest_artifact_retention_v0.1")
        self.assertEqual(schema_version("backtest_artifact_cleanup"), "backtest_artifact_cleanup_v0.1")
        self.assertEqual(schema_version("clob_order_book_tiering"), "clob_order_book_tiering_v0.1")
        self.assertEqual(schema_version("daily_progress_ledger"), "daily_progress_ledger_v0.1")
        self.assertEqual(
            schema_version("daily_refresh_step_child"),
            "daily_refresh_step_child_v0.2",
        )
        self.assertEqual(
            schema_version("daily_refresh_step_child_legacy"),
            "daily_refresh_step_child_v0.1",
        )
        self.assertEqual(schema_version("daily_refresh_disk_preflight"), "daily_refresh_disk_preflight_v0.1")
        self.assertEqual(schema_version("daily_refresh_stale_lock_repair"), "daily_refresh_stale_lock_repair_v0.1")
        self.assertEqual(schema_version("daily_rollup_freshness"), "daily_rollup_freshness_v0.1")
        self.assertEqual(schema_version("python_runtime_audit"), "python_runtime_audit_v0.1")
        self.assertEqual(schema_version("python_runtime_audit_baseline"), "python_runtime_audit_baseline_v0.1")
        self.assertEqual(schema_version("nightly_health_checks"), "nightly_health_checks_v0.1")
        self.assertEqual(schema_version("runtime_identity_evidence"), "runtime_identity_evidence_v0.1")
        self.assertEqual(schema_version("runtime_identity_reconciliation"), "runtime_identity_reconciliation_v0.1")
        self.assertEqual(schema_version("snapshot_core_sidecar_backfill"), "snapshot_core_sidecar_backfill_v0.1")
        self.assertEqual(schema_version("snapshot_explanation_backfill"), "snapshot_explanation_backfill_v0.1")
        self.assertEqual(schema_version("snapshot_explanations"), "snapshot_explanations_v0.1")
        self.assertEqual(schema_version("taker_edge_permission_map"), "taker_edge_permission_map_v0.1")
        self.assertEqual(
            schema_version("taker_champion_challenger_ledger"),
            "taker_champion_challenger_ledger_v0.1",
        )
        self.assertEqual(
            schema_version("taker_market_benchmark_scoreboard"),
            "taker_market_benchmark_scoreboard_v0.1",
        )
        self.assertEqual(schema_version("settled_day_root_cause"), "settled_day_root_cause_v0.1")
        self.assertEqual(schema_version("promotion_refresh_lifecycle"), "promotion_refresh_incomplete_v0.1")
        self.assertTrue(validate_schema_version("feature_store_legacy_v1_14", "toronto_feature_store_v1.14"))
        self.assertTrue(validate_schema_version("feature_store_legacy_v1_11", "toronto_feature_store_v1.11"))
        self.assertTrue(validate_schema_version("market_registry", "market_registry_v0.1"))
        self.assertTrue(validate_schema_version("live_forward_gate_legacy", "live_forward_gate_v0.1"))
        self.assertTrue(validate_schema_version("market_making_daily_roll_legacy", "market_making_daily_roll_v0.1"))

    def test_registry_payload_has_stable_schema(self):
        payload = registry_payload()

        self.assertEqual(payload["schema_version"], SCHEMA_REGISTRY_SCHEMA_VERSION)
        names = {row["name"] for row in payload["schemas"]}
        self.assertIn("feature_store", names)
        self.assertIn("observation_trigger_replay", names)
        self.assertIn("daily_learning", names)
        self.assertIn("taker_edge_permission_map", names)

    def test_registry_name_version_registrations_are_unique(self):
        registrations = [(spec.name, spec.version) for spec in REGISTERED_SCHEMAS]

        self.assertEqual(len(registrations), len(set(registrations)))

    def test_shared_versions_are_only_deliberate_compatibility_aliases(self):
        names_by_version = {}
        for spec in REGISTERED_SCHEMAS:
            names_by_version.setdefault(spec.version, set()).add(spec.name)
        shared_versions = {
            version: tuple(sorted(names))
            for version, names in names_by_version.items()
            if len(names) > 1
        }
        expected_aliases = {
            version: tuple(sorted((entry["canonical"], *entry["deprecated_aliases"])))
            for version, entry in INTENTIONAL_SCHEMA_VERSION_ALIASES.items()
        }

        self.assertEqual(shared_versions, expected_aliases)
        specs_by_name = {spec.name: spec for spec in REGISTERED_SCHEMAS}
        for version, entry in INTENTIONAL_SCHEMA_VERSION_ALIASES.items():
            canonical = entry["canonical"]
            aliases = entry["deprecated_aliases"]
            self.assertEqual(specs_by_name[canonical].status, "active")
            for name in aliases:
                self.assertEqual(specs_by_name[name].status, "deprecated")
            for name in (canonical, *aliases):
                self.assertEqual(schema_version(name), version)

    def test_audit_classifies_registered_and_unregistered_literals(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "demo.py"
            path.write_text(
                'KNOWN = "historical_coverage_v1"\n'
                'EXCLUDED = "maker_default_v0"\n'
                'UNKNOWN = "made_up_payload_v9"\n',
                encoding="utf-8",
            )

            payload = audit_payload([tmp])

        by_version = {row["version"]: row for row in payload["discovered_literals"]}
        self.assertTrue(by_version["historical_coverage_v1"]["registered"])
        self.assertFalse(by_version["maker_default_v0"]["registered"])
        self.assertTrue(by_version["maker_default_v0"]["excluded"])
        self.assertIn("maker_default_v0", payload["excluded_versions"])
        self.assertNotIn("maker_default_v0", payload["unregistered_versions"])
        self.assertFalse(by_version["made_up_payload_v9"]["registered"])
        self.assertIn("made_up_payload_v9", payload["unregistered_versions"])

    def test_source_tree_strict_audit_has_only_explicit_exclusions(self):
        payload = audit_payload(["src"])

        self.assertEqual(payload["unregistered_versions"], [])
        excluded_versions = {row.version for row in EXCLUDED_SCHEMA_LITERALS}
        self.assertEqual(set(payload["excluded_versions"]), excluded_versions)
        for exclusion in payload["excluded_schema_literals"]:
            self.assertTrue(exclusion["owner"])
            self.assertTrue(exclusion["classification"])
            self.assertIn("not a", exclusion["reason"])

    def test_new_unregistered_artifact_schema_still_fails_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "demo.py"
            path.write_text('UNKNOWN = "new_storage_artifact_v9"\n', encoding="utf-8")

            payload = audit_payload([tmp])

        self.assertEqual(payload["unregistered_versions"], ["new_storage_artifact_v9"])
        self.assertEqual(payload["unregistered_version_count"], 1)


if __name__ == "__main__":
    unittest.main()
