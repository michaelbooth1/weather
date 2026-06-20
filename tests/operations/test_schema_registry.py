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
        self.assertEqual(schema_version("feature_store"), "toronto_feature_store_v1.6")
        self.assertEqual(schema_version("reanalysis_synoptic_features"), "reanalysis_synoptic_features_v0.3")
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
        self.assertEqual(schema_version("hourly_model_performance"), "hourly_model_performance_v0.3")
        self.assertEqual(schema_version("hourly_performance_gate"), "hourly_performance_gate_v0.1")
        self.assertEqual(schema_version("hourly_remediation_registry"), "hourly_remediation_registry_v0.1")
        self.assertEqual(schema_version("price_free_model_learning"), "price_free_model_learning_v0.1")
        self.assertEqual(schema_version("candidate_hourly_performance"), "candidate_hourly_performance_v0.1")
        self.assertEqual(schema_version("candidate_hourly_performance_gate"), "candidate_hourly_performance_gate_v0.1")
        self.assertEqual(schema_version("winner_underpricing_casebook"), "winner_underpricing_casebook_v0.1")
        self.assertEqual(schema_version("forecast_pressure_tilt_validation"), "forecast_pressure_tilt_validation_v0.1")
        self.assertEqual(schema_version("candidate_rank_sharpening_validation"), "candidate_rank_sharpening_validation_v0.1")
        self.assertEqual(schema_version("forecast_side_rank_validation"), "forecast_side_rank_validation_v0.1")
        self.assertEqual(schema_version("forecast_profile_guardrails"), "forecast_profile_guardrails_v0.1")
        self.assertEqual(schema_version("winner_band_signal_validation"), "winner_band_signal_validation_v0.1")
        self.assertEqual(schema_version("market_anchor_time_split_validation"), "market_anchor_time_split_validation_v0.2")
        self.assertEqual(schema_version("clob_coverage_audit"), "clob_coverage_audit_v0.3")
        self.assertEqual(schema_version("clob_capture_status"), "clob_capture_status_v0.1")
        self.assertEqual(schema_version("pooled_continuous_density_hgb"), "pooled_continuous_density_hgb_v0.7")
        self.assertEqual(schema_version("pooled_all_market_band_hgb"), "pooled_all_market_band_hgb_v0.1")
        self.assertEqual(schema_version("pooled_all_market_band_hgb_exact_winner"), "pooled_all_market_band_hgb_exact_winner_v0.1")
        self.assertEqual(schema_version("market_hour_kind_bias"), "market_hour_kind_bias_v1")
        self.assertEqual(schema_version("live_forward_gate"), "live_forward_gate_v0.2")
        self.assertEqual(schema_version("market_making_daily_roll"), "market_making_daily_roll_v0.2")
        self.assertEqual(schema_version("early_hour_market_guardrail"), "early_hour_market_guardrail_v0.1")
        self.assertEqual(schema_version("early_hour_market_guardrail_shadow"), "early_hour_market_guardrail_shadow_v0.1")
        self.assertEqual(schema_version("taker_bot_run"), "taker_bot_run_v0.1")
        self.assertEqual(schema_version("taker_settlement_finalization"), "taker_settlement_finalization_v0.1")
        self.assertEqual(schema_version("taker_bot_daily_roll"), "taker_bot_daily_roll_v0.1")
        self.assertEqual(schema_version("promotion_refresh_lifecycle"), "promotion_refresh_incomplete_v0.1")
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
