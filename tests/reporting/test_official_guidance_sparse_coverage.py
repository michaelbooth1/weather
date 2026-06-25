import csv
import json
import tempfile
import unittest
from pathlib import Path

from weather.reporting.source_gates.official_guidance_sparse_coverage import (
    build_report_payload,
    guidance_family_for_feature,
    write_markdown_report,
)


def write_coverage(path):
    rows = [
        {
            "feature": "nws_grid_high",
            "kind": "numeric",
            "family": "official_multimodel_guidance",
            "n_rows_non_missing": "1200",
            "row_coverage": "0.55",
            "n_days_non_missing": "70",
            "n_markets_non_missing": "11",
            "n_unique_raw": "22",
            "n_rows_within_market_variation": "1200",
            "analyzable": "True",
        },
        {
            "feature": "open_meteo_nam_high_delta",
            "kind": "numeric",
            "family": "official_multimodel_guidance",
            "n_rows_non_missing": "250",
            "row_coverage": "0.18",
            "n_days_non_missing": "22",
            "n_markets_non_missing": "8",
            "n_unique_raw": "30",
            "n_rows_within_market_variation": "250",
            "analyzable": "True",
        },
        {
            "feature": "eccc_gem_high",
            "kind": "numeric",
            "family": "official_multimodel_guidance",
            "n_rows_non_missing": "40",
            "row_coverage": "0.02",
            "n_days_non_missing": "2",
            "n_markets_non_missing": "1",
            "n_unique_raw": "9",
            "n_rows_within_market_variation": "40",
            "analyzable": "False",
        },
        {
            "feature": "mrms_row_count",
            "kind": "numeric",
            "family": "radar_precip",
            "n_rows_non_missing": "500",
            "row_coverage": "0.30",
            "n_days_non_missing": "45",
            "n_markets_non_missing": "9",
            "n_unique_raw": "1",
            "n_rows_within_market_variation": "0",
            "analyzable": "False",
        },
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_summary(path):
    rows = [
        {
            "feature": "nws_grid_high",
            "family": "official_multimodel_guidance",
            "daily_latest_pearson_r": "0.49",
            "hgb_delta_mae_mean": "0.01",
        },
        {
            "feature": "open_meteo_nam_high_delta",
            "family": "official_multimodel_guidance",
            "daily_latest_pearson_r": "-0.50",
            "hgb_delta_mae_mean": "",
        },
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_inventory(path):
    payload = {
        "inventory": [
            {
                "family_id": "nws_grid",
                "lineage_status": "PASS",
                "promotion_decision": {"status": "PASS"},
                "ablation": {
                    "status": "PRESENT",
                    "settlement_scored": True,
                    "days": 25,
                    "rows": 500,
                    "delta": -0.002,
                    "variant": "official_us_guidance",
                },
            },
            {
                "family_id": "multi_model_guidance",
                "lineage_status": "PARTIAL_SOURCE_STATUS",
                "promotion_decision": {"status": "BLOCK_LINEAGE"},
                "ablation": {
                    "status": "PRESENT",
                    "settlement_scored": True,
                    "days": 1,
                    "rows": 50,
                    "delta": 0.0,
                    "variant": "multi_model_guidance",
                },
            },
            {
                "family_id": "eccc_gridded",
                "lineage_status": "PARTIAL_SOURCE_STATUS",
                "promotion_decision": {"status": "BLOCK_LINEAGE"},
                "ablation": {},
            },
            {
                "family_id": "mrms_precip",
                "lineage_status": "PARTIAL_SOURCE_STATUS",
                "promotion_decision": {"status": "BLOCK_LINEAGE"},
                "ablation": {},
            },
        ]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


class OfficialGuidanceSparseCoverageTests(unittest.TestCase):
    def test_guidance_family_mapping(self):
        self.assertEqual(guidance_family_for_feature("nws_grid_high"), "nws_grid")
        self.assertEqual(guidance_family_for_feature("open_meteo_nam_high_delta"), "multi_model_guidance")
        self.assertEqual(guidance_family_for_feature("eccc_gem_high"), "eccc_gridded")
        self.assertEqual(guidance_family_for_feature("mrms_row_count"), "mrms_precip")
        self.assertIsNone(guidance_family_for_feature("forecast_high"))

    def test_report_applies_coverage_targets_and_promotion_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            coverage = root / "coverage.csv"
            summary = root / "summary.csv"
            inventory = root / "inventory.json"
            write_coverage(coverage)
            write_summary(summary)
            write_inventory(inventory)

            payload = build_report_payload(coverage, summary, inventory)

        self.assertEqual(payload["schema_version"], "official_guidance_sparse_coverage_v0.1")
        families = {row["family_id"]: row for row in payload["family_gates"]}
        self.assertEqual(families["nws_grid"]["status"], "PASS")
        self.assertEqual(families["multi_model_guidance"]["status"], "BLOCK")
        self.assertEqual(payload["promotion_gate"]["status"], "BLOCK")
        nam = next(row for row in payload["field_rows"] if row["feature"] == "open_meteo_nam_high_delta")
        self.assertEqual(nam["decision"], "diagnostic_only")
        self.assertTrue(any("market-days" in reason for reason in nam["blockers"]))

    def test_markdown_report_includes_family_gates_and_field_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            coverage = root / "coverage.csv"
            summary = root / "summary.csv"
            inventory = root / "inventory.json"
            report = root / "report.md"
            write_coverage(coverage)
            write_summary(summary)
            write_inventory(inventory)
            payload = build_report_payload(coverage, summary, inventory)

            write_markdown_report(report, payload)

            text = report.read_text(encoding="utf-8")
        self.assertIn("Family Gates", text)
        self.assertIn("Priority Field Coverage", text)
        self.assertIn("nws_grid_high", text)


if __name__ == "__main__":
    unittest.main()
