import os
import sys
import tempfile
import unittest
from pathlib import Path
from weather.schema_registry import (  # noqa: E402
    SCHEMA_REGISTRY_SCHEMA_VERSION,
    audit_payload,
    registry_payload,
    schema_version,
    validate_schema_version,
)


class TestSchemaRegistry(unittest.TestCase):
    def test_registry_lookup_returns_public_versions(self):
        self.assertEqual(schema_version("feature_store"), "toronto_feature_store_v1.15")
        self.assertEqual(schema_version("feature_quality_quarantine"), "feature_quality_quarantine_v0.1")
        self.assertEqual(schema_version("reanalysis_synoptic_features"), "reanalysis_synoptic_features_v0.5")
        self.assertEqual(schema_version("pressure_level_cache_status"), "pressure_level_cache_status_v0.1")
        self.assertEqual(schema_version("reanalysis_sidecar_coverage_audit"), "reanalysis_sidecar_coverage_audit_v0.1")
        self.assertEqual(schema_version("historical_coverage"), "historical_coverage_v1")
        self.assertEqual(schema_version("forecast_history_coverage"), "forecast_history_coverage_v0.1")
        self.assertEqual(schema_version("forecast_history_long"), "forecast_history_long_v3")
        self.assertEqual(schema_version("daily_learning"), "daily_learning_v0.1")
        self.assertEqual(schema_version("variant_learning_operational_gate"), "variant_learning_operational_gate_v0.1")
        self.assertEqual(schema_version("live_variant_predictions"), "live_variant_predictions_v0.1")
        self.assertEqual(schema_version("multi_variant_shadow_attribution"), "multi_variant_shadow_attribution_v0.1")
        self.assertEqual(schema_version("model_variant_registry_audit"), "model_variant_registry_audit_v0.1")
        self.assertEqual(schema_version("roadmap_backlog"), "roadmap_backlog_v0.1")
        self.assertEqual(
            schema_version("settlement_source_revision_audit"),
            "settlement_source_revision_audit_v0.1",
        )
        self.assertEqual(
            schema_version("proper_scoring_reliability_scorecard"),
            "proper_scoring_reliability_scorecard_v0.1",
        )
        self.assertEqual(schema_version("winner_rank_parity"), "winner_rank_parity_v0.1")
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
            schema_version("item186_soil_antecedent_gate"),
            "item186_soil_antecedent_gate_v0.1",
        )
        self.assertEqual(schema_version("forecast_radiation_gate"), "forecast_radiation_gate_v0.1")
        self.assertEqual(schema_version("forecast_smoke_gate"), "forecast_smoke_gate_v0.1")
        self.assertEqual(schema_version("global_model_guidance_gate"), "global_model_guidance_gate_v0.1")
        self.assertEqual(schema_version("nbm_probabilistic_tmax_gate"), "nbm_probabilistic_tmax_gate_v0.1")
        self.assertEqual(schema_version("marine_contrast_gate"), "marine_contrast_gate_v0.1")
        self.assertEqual(schema_version("winner_band_signal_validation"), "winner_band_signal_validation_v0.1")
        self.assertEqual(schema_version("market_anchor_time_split_validation"), "market_anchor_time_split_validation_v0.2")
        self.assertEqual(schema_version("clob_coverage_audit"), "clob_coverage_audit_v0.3")
        self.assertEqual(schema_version("clob_capture_status"), "clob_capture_status_v0.1")
        self.assertEqual(schema_version("data_retention_inventory"), "data_retention_inventory_v0.1")
        self.assertEqual(
            schema_version("closed_market_day_archive_manifest"),
            "closed_market_day_archive_manifest_v0.1",
        )
        self.assertEqual(schema_version("model_artifact_externalization"), "model_artifact_externalization_v0.1")
        self.assertEqual(schema_version("model_artifact_promotion_preflight"), "model_artifact_promotion_preflight_v0.1")
        self.assertEqual(schema_version("module_size_audit"), "module_size_audit_v0.1")
        self.assertEqual(schema_version("structure_inventory"), "structure_inventory_v0.1")
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
            schema_version("taker_profitability_artifact_verification"),
            "taker_profitability_artifact_verification_v0.1",
        )
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

    def test_audit_classifies_registered_and_unregistered_literals(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "demo.py"
            path.write_text(
                'KNOWN = "historical_coverage_v1"\n'
                'UNKNOWN = "made_up_payload_v9"\n',
                encoding="utf-8",
            )

            payload = audit_payload([tmp])

        by_version = {row["version"]: row for row in payload["discovered_literals"]}
        self.assertTrue(by_version["historical_coverage_v1"]["registered"])
        self.assertFalse(by_version["made_up_payload_v9"]["registered"])
        self.assertIn("made_up_payload_v9", payload["unregistered_versions"])


if __name__ == "__main__":
    unittest.main()
