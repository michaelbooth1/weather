import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from weather.reporting.source_gates.weak_input_family_disposition import (
    build_report_payload,
    input_family_for_model_feature,
    weak_input_training_preflight,
    write_markdown_report,
)
from tests.reporting.source_family_contract_fixtures import operational_inventory


def write_family_permutation(path):
    rows = [
        {
            "slice": "all",
            "family": "observed_temp_path",
            "hgb_delta_mae_mean": "0.20",
            "hgb_delta_mae_ci_low": "0.15",
            "hgb_delta_mae_ci_high": "0.25",
            "hgb_importance_q": "0.01",
            "n_features": "2",
        },
        {
            "slice": "all",
            "family": "surface_weather",
            "hgb_delta_mae_mean": "0.004",
            "hgb_delta_mae_ci_low": "-0.003",
            "hgb_delta_mae_ci_high": "0.011",
            "hgb_importance_q": "0.13",
            "n_features": "3",
        },
        {
            "slice": "all",
            "family": "marine_microclimate",
            "hgb_delta_mae_mean": "-0.001",
            "hgb_delta_mae_ci_low": "-0.004",
            "hgb_delta_mae_ci_high": "0.002",
            "hgb_importance_q": "0.77",
            "n_features": "2",
        },
        {
            "slice": "all",
            "family": "forecast_source_state",
            "hgb_delta_mae_mean": "0.02",
            "hgb_delta_mae_ci_low": "0.004",
            "hgb_delta_mae_ci_high": "0.04",
            "hgb_importance_q": "0.02",
            "n_features": "2",
        },
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_coverage(path):
    rows = [
        {
            "feature": "high_so_far",
            "kind": "numeric",
            "family": "observed_temp_path",
            "n_rows_non_missing": "1000",
            "row_coverage": "1.0",
            "n_days_non_missing": "100",
            "n_markets_non_missing": "12",
            "n_unique_raw": "40",
            "n_rows_within_market_variation": "1000",
            "analyzable": "True",
        },
        {
            "feature": "dewpoint_c",
            "kind": "numeric",
            "family": "surface_weather",
            "n_rows_non_missing": "1000",
            "row_coverage": "1.0",
            "n_days_non_missing": "100",
            "n_markets_non_missing": "12",
            "n_unique_raw": "40",
            "n_rows_within_market_variation": "1000",
            "analyzable": "True",
        },
        {
            "feature": "lake_breeze_proxy",
            "kind": "numeric",
            "family": "marine_microclimate",
            "n_rows_non_missing": "220",
            "row_coverage": "0.22",
            "n_days_non_missing": "34",
            "n_markets_non_missing": "12",
            "n_unique_raw": "2",
            "n_rows_within_market_variation": "50",
            "analyzable": "False",
        },
        {
            "feature": "forecast_source_count",
            "kind": "numeric",
            "family": "forecast_source_state",
            "n_rows_non_missing": "500",
            "row_coverage": "0.43",
            "n_days_non_missing": "59",
            "n_markets_non_missing": "12",
            "n_unique_raw": "3",
            "n_rows_within_market_variation": "500",
            "analyzable": "True",
        },
        {
            "feature": "mrms_row_count",
            "kind": "numeric",
            "family": "radar_precip",
            "n_rows_non_missing": "200",
            "row_coverage": "0.20",
            "n_days_non_missing": "32",
            "n_markets_non_missing": "11",
            "n_unique_raw": "1",
            "n_rows_within_market_variation": "0",
            "analyzable": "False",
        },
        {
            "feature": "eccc_gem_high",
            "kind": "numeric",
            "family": "official_multimodel_guidance",
            "n_rows_non_missing": "20",
            "row_coverage": "0.02",
            "n_days_non_missing": "2",
            "n_markets_non_missing": "1",
            "n_unique_raw": "9",
            "n_rows_within_market_variation": "20",
            "analyzable": "False",
        },
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_inventory(path):
    payload = operational_inventory(
        [
            {
                "family_id": "settlement_observation",
                "lineage_status": "PASS",
                "active_model_usage_status": "ACTIVE_FEATURES",
                "active_model_feature_columns": ["dewpoint_c", "cloud_group_Fair/clear"],
                "promotion_decision": {"status": "PROMOTION_CANDIDATE"},
            },
            {
                "family_id": "marine_context",
                "lineage_status": "PARTIAL_SOURCE_STATUS",
                "active_model_usage_status": "NOT_USED_BY_ACTIVE_ARTIFACT",
                "active_model_feature_columns": [],
                "promotion_decision": {"status": "BLOCK_LINEAGE"},
            },
            {
                "family_id": "mrms_precip",
                "lineage_status": "PARTIAL_SOURCE_STATUS",
                "active_model_usage_status": "NOT_USED_BY_ACTIVE_ARTIFACT",
                "active_model_feature_columns": [],
                "promotion_decision": {"status": "BLOCK_LINEAGE"},
            },
            {
                "family_id": "eccc_gridded",
                "lineage_status": "PARTIAL_SOURCE_STATUS",
                "active_model_usage_status": "NOT_USED_BY_ACTIVE_ARTIFACT",
                "active_model_feature_columns": [],
                "promotion_decision": {"status": "BLOCK_LINEAGE"},
            },
        ]
    )
    path.write_text(json.dumps(payload), encoding="utf-8")


class WeakInputFamilyDispositionTests(unittest.TestCase):
    def setUp(self):
        patcher = patch(
            "weather.reporting.source_gates.weak_input_family_disposition."
            "source_family_inventory_consumer_contract",
            return_value={
                "status": "PASS",
                "serving_or_release_authorization": False,
                "blockers": [],
            },
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            family_permutation = root / "family.csv"
            coverage = root / "coverage.csv"
            inventory = root / "inventory.json"
            write_family_permutation(family_permutation)
            write_coverage(coverage)
            write_inventory(inventory)
            return build_report_payload(family_permutation, coverage, inventory)

    def test_classifies_weak_and_sparse_families(self):
        payload = self._payload()
        self.assertEqual(payload["schema_version"], "weak_input_family_disposition_v0.1")
        self.assertFalse(payload["serving_or_release_authorization"])
        rows = {row["family"]: row for row in payload["families"]}

        self.assertEqual(rows["observed_temp_path"]["disposition"], "served")
        self.assertEqual(rows["forecast_source_state"]["disposition"], "served")
        self.assertEqual(rows["surface_weather"]["disposition"], "diagnostic_only")
        self.assertEqual(rows["marine_microclimate"]["disposition"], "regime_backfill")
        self.assertEqual(rows["radar_precip"]["disposition"], "regime_backfill")
        self.assertEqual(rows["official_multimodel_guidance"]["disposition"], "regime_backfill")
        self.assertIn("lake_breeze_proxy", rows["marine_microclimate"]["backfill_plan"]["target_features"])

    def test_training_preflight_warns_for_diagnostic_active_features(self):
        payload = self._payload()
        preflight = weak_input_training_preflight(
            ["forecast_high", "forecast_source_count", "dewpoint_c", "cloud_group_Fair/clear"],
            payload,
        )

        self.assertEqual(preflight["status"], "BLOCK")
        self.assertEqual(preflight["diagnostic_only_families"], ["surface_weather"])
        surface = next(
            row for row in preflight["warnings"] if row["family"] == "surface_weather"
        )
        self.assertEqual(surface["family"], "surface_weather")
        self.assertIn("no positive broad family permutation result", surface["reasons"])
        self.assertIn(
            "no disposition row for referenced feature family open_meteo_forecast_profile",
            preflight["authorization_blockers"],
        )

    def test_training_preflight_blocks_empty_synthetic_policy(self):
        preflight = weak_input_training_preflight(
            ["forecast_high"],
            {"families": []},
        )

        self.assertEqual(preflight["status"], "BLOCK")
        self.assertFalse(preflight["serving_or_release_authorization"])
        self.assertTrue(preflight["authorization_blockers"])

    def test_feature_family_mapping_and_markdown(self):
        self.assertEqual(input_family_for_model_feature("cloud_group_Fair/clear"), "surface_weather")
        self.assertEqual(input_family_for_model_feature("forecast_high"), "open_meteo_forecast_profile")
        self.assertEqual(input_family_for_model_feature("mrms_row_count"), "radar_precip")

        payload = self._payload()
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "report.md"
            write_markdown_report(report, payload)
            text = report.read_text(encoding="utf-8")

        self.assertIn("Disposition Table", text)
        self.assertIn("Training Preflight Warnings", text)
        self.assertIn("Regime Backfill Plans", text)
        self.assertIn("runtime current-input revalidation is required", text)


if __name__ == "__main__":
    unittest.main()
