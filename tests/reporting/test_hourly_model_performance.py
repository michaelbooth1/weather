import csv
import tempfile
import unittest
from pathlib import Path

from weather.reporting.hourly.hourly_model_performance import (
    build_hourly_performance,
    early_hour_market_deltas,
    forecast_anchor_probability,
    forecast_centering_rows,
    write_outputs,
)


SLUG = "highest-temperature-in-toronto-on-june-3-2026"


def write_snapshot_folder(root):
    folder = Path(root) / "snapshots" / SLUG
    folder.mkdir(parents=True)
    rows = [
        {
            "snapshot_id": "s9",
            "captured_at_utc": "2026-06-03T13:00:00+00:00",
            "captured_at_local": "2026-06-03T09:00:00-04:00",
            "event_slug": SLUG,
            "model_version": "test-v1",
            "range_label": "9 C or below",
            "bin_kind": "lte",
            "bin_value_c": "9",
            "model_probability": "0.10",
            "market_yes": "0.20",
            "market_no": "0.80",
        },
        {
            "snapshot_id": "s9",
            "captured_at_utc": "2026-06-03T13:00:00+00:00",
            "captured_at_local": "2026-06-03T09:00:00-04:00",
            "event_slug": SLUG,
            "model_version": "test-v1",
            "range_label": "10 C",
            "bin_kind": "eq",
            "bin_value_c": "10",
            "model_probability": "0.80",
            "market_yes": "0.70",
            "market_no": "0.30",
        },
        {
            "snapshot_id": "s10",
            "captured_at_utc": "2026-06-03T14:00:00+00:00",
            "captured_at_local": "2026-06-03T10:00:00-04:00",
            "event_slug": SLUG,
            "model_version": "test-v1",
            "range_label": "9 C or below",
            "bin_kind": "lte",
            "bin_value_c": "9",
            "model_probability": "0.70",
            "market_yes": "0.20",
            "market_no": "0.80",
        },
        {
            "snapshot_id": "s10",
            "captured_at_utc": "2026-06-03T14:00:00+00:00",
            "captured_at_local": "2026-06-03T10:00:00-04:00",
            "event_slug": SLUG,
            "model_version": "test-v1",
            "range_label": "10 C",
            "bin_kind": "eq",
            "bin_value_c": "10",
            "model_probability": "0.40",
            "market_yes": "0.70",
            "market_no": "0.30",
        },
    ]
    with (folder / "snapshots_long.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return folder


def write_labels_csv(root, folder):
    path = Path(root) / "labels.csv"
    rows = [
        {
            "event_slug": SLUG,
            "market_id": "toronto",
            "city": "Toronto",
            "target_date": "2026-06-03",
            "settlement_bucket": "10",
            "settlement_unit": "C",
            "settlement_source": "test",
            "quality_grade": "complete",
            "snapshot_count": "2",
            "band_count": "2",
            "snapshot_tape_path": str(folder / "snapshots_long.csv"),
        }
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_promotion_countable_partial_labels_csv(root, folder):
    path = Path(root) / "labels.csv"
    rows = [
        {
            "event_slug": SLUG,
            "market_id": "toronto",
            "city": "Toronto",
            "target_date": "2026-06-03",
            "settlement_bucket": "10",
            "settlement_unit": "C",
            "settlement_source": "test",
            "quality_grade": "partial",
            "material_coverage_grade": "minor_gap_material",
            "material_coverage_reason": "fixture minor gap",
            "promotion_countable": "True",
            "promotion_countable_reason": "independent source and market reconciliation match",
            "snapshot_count": "2",
            "band_count": "2",
            "snapshot_tape_path": str(folder / "snapshots_long.csv"),
        }
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_stale_labels_csv(root, folder):
    path = Path(root) / "labels.csv"
    rows = [
        {
            "event_slug": SLUG,
            "market_id": "toronto",
            "city": "Toronto",
            "target_date": "2026-06-03",
            "settlement_bucket": "10",
            "settlement_unit": "C",
            "settlement_source": "test",
            "quality_grade": "complete",
            "snapshot_count": "2",
            "band_count": "2",
            "snapshot_tape_path": str(folder / "snapshots_long.csv"),
        },
        {
            "event_slug": "highest-temperature-in-nyc-on-june-4-2026",
            "market_id": "nyc",
            "city": "New York",
            "target_date": "2026-06-04",
            "settlement_bucket": "82",
            "settlement_unit": "F",
            "settlement_source": "test",
            "quality_grade": "complete",
            "snapshot_count": "0",
            "band_count": "0",
            "snapshot_tape_path": str(Path(root) / "missing" / "snapshots_long.csv"),
        },
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


class TestHourlyModelPerformance(unittest.TestCase):
    def test_build_hourly_performance_scores_and_ranks_hours(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = write_snapshot_folder(tmp)
            labels_csv = write_labels_csv(tmp, folder)

            payload = build_hourly_performance(
                labels_csv=labels_csv,
                snapshots_root=Path(tmp) / "snapshots",
                context_root=Path(tmp),
                quality_grades=("complete",),
                min_rows=1,
                top_hours=1,
            )
            out_dir = Path(tmp) / "out"
            json_out, report_out, csv_out = write_outputs(
                payload,
                json_out=out_dir / "hourly.json",
                report_out=out_dir / "hourly.md",
                csv_out=out_dir / "hourly.csv",
            )

            by_hour = {row["hour"]: row for row in payload["by_hour"]}
            json_exists = Path(json_out).exists()
            report = Path(report_out).read_text(encoding="utf-8")
            csv_exists = Path(csv_out).exists()

        self.assertEqual(payload["schema_version"], "hourly_model_performance_v0.3")
        self.assertEqual(payload["last_scored_target_date"], "2026-06-03")
        self.assertEqual(payload["latest_settled_label_date"], "2026-06-03")
        self.assertEqual(payload["scoring_liveness"]["status"], "PASS")
        self.assertEqual(payload["corpus"]["scored_market_days"], 1)
        self.assertEqual(payload["corpus"]["hourly_checkpoint_rows"], 4)
        self.assertEqual(set(by_hour), {9, 10})
        self.assertEqual(by_hour[9]["partition_snapshots"], 1)
        self.assertIn("partition_model_effective_bands", by_hour[9])
        self.assertIn("ramp_midday", {row["regime"] for row in payload["by_hour_regime"]})
        self.assertLess(by_hour[9]["model_brier"], by_hour[10]["model_brier"])
        self.assertEqual(payload["best_hours"][0]["hour"], 9)
        self.assertEqual(payload["worst_hours"][0]["hour"], 10)
        self.assertIn("market_blend", payload["remediation_candidates"])
        self.assertIn("partition_power", payload["remediation_candidates"])
        self.assertIn("forecast_centering", payload["remediation_candidates"])
        self.assertEqual(payload["hourly_performance_gate"]["schema_version"], "hourly_performance_gate_v0.1")
        self.assertEqual(payload["hourly_performance_gate"]["status"], "BLOCK")
        self.assertEqual(
            payload["hourly_performance_gate"]["first_blocker"]["gate"],
            "early_hour_regime_missing",
        )
        registry = payload["remediation_registry"]
        self.assertEqual(registry["schema_version"], "hourly_remediation_registry_v0.1")
        self.assertTrue(registry["rows"])
        first_registry_row = registry["rows"][0]
        self.assertIn("probe_name", first_registry_row)
        self.assertIn("hour_regime", first_registry_row)
        self.assertIn("metric_delta", first_registry_row)
        self.assertIn("market_count", first_registry_row)
        self.assertIn("row_count", first_registry_row)
        self.assertIn("serving_mitigation_status", first_registry_row)
        self.assertFalse(first_registry_row["serving_mitigation_allowed"])
        self.assertIn("interpretation", first_registry_row)
        self.assertIn("early_hour_market_deltas", registry)
        self.assertIn("active_remediation_owners", payload["daily_summary"])
        self.assertIn("forecast_centering", registry["summary"]["probe_names"])
        self.assertFalse(
            payload["deep_diagnostics"]["variable_weight_context"]["cutoff_regime_weighting"]["available"]
        )
        self.assertTrue(json_exists)
        self.assertIn("Hourly Model Performance Audit", report)
        self.assertIn("Deep Diagnostics", report)
        self.assertIn("Hourly Performance Gate", report)
        self.assertIn("Remediation Registry", report)
        self.assertIn("Spread And Winner Recognition", report)
        self.assertIn("Remediation Probes", report)
        self.assertTrue(csv_exists)

    def test_scoring_liveness_blocks_when_latest_settled_label_is_unscored(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = write_snapshot_folder(tmp)
            labels_csv = write_stale_labels_csv(tmp, folder)

            payload = build_hourly_performance(
                labels_csv=labels_csv,
                snapshots_root=Path(tmp) / "snapshots",
                context_root=Path(tmp),
                quality_grades=("complete",),
                min_rows=1,
                top_hours=1,
            )

        self.assertEqual(payload["last_scored_target_date"], "2026-06-03")
        self.assertEqual(payload["latest_settled_label_date"], "2026-06-04")
        self.assertEqual(payload["scoring_liveness"]["status"], "BLOCK")
        self.assertEqual(payload["hourly_performance_gate"]["status"], "BLOCK")
        self.assertEqual(
            payload["hourly_performance_gate"]["first_blocker"]["gate"],
            "model_scoring_liveness_stale",
        )
        self.assertIn(
            "python -m weather.reporting.hourly.hourly_model_performance",
            payload["hourly_performance_gate"]["first_blocker"]["remediation_command"],
        )

    def test_promotion_countable_partial_labels_are_scored_with_quality_annotations(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = write_snapshot_folder(tmp)
            labels_csv = write_promotion_countable_partial_labels_csv(tmp, folder)

            payload = build_hourly_performance(
                labels_csv=labels_csv,
                snapshots_root=Path(tmp) / "snapshots",
                context_root=Path(tmp),
                quality_grades=("complete",),
                min_rows=1,
                top_hours=1,
            )

        self.assertEqual(payload["corpus"]["scored_market_days"], 1)
        self.assertEqual(payload["corpus"]["skipped_labels"], {})
        self.assertEqual(payload["last_scored_target_date"], "2026-06-03")
        self.assertEqual(payload["latest_settled_label_date"], "2026-06-03")
        self.assertEqual(payload["scoring_liveness"]["status"], "PASS")
        self.assertEqual(payload["scoring_liveness"]["selected_quality_counts"], {"partial": 1})
        day = payload["days"][0]
        self.assertEqual(day["quality_grade"], "partial")
        self.assertEqual(day["material_coverage_grade"], "minor_gap_material")
        self.assertTrue(day["promotion_countable"])

    def test_strict_quality_only_excludes_promotion_countable_partial_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = write_snapshot_folder(tmp)
            labels_csv = write_promotion_countable_partial_labels_csv(tmp, folder)

            payload = build_hourly_performance(
                labels_csv=labels_csv,
                snapshots_root=Path(tmp) / "snapshots",
                context_root=Path(tmp),
                quality_grades=("complete",),
                include_promotion_countable_labels=False,
                min_rows=1,
                top_hours=1,
            )

        self.assertEqual(payload["corpus"]["scored_market_days"], 0)
        self.assertEqual(payload["corpus"]["skipped_labels"], {"quality": 1})
        self.assertIsNone(payload["last_scored_target_date"])
        self.assertIsNone(payload["latest_settled_label_date"])
        self.assertEqual(payload["scoring_liveness"]["status"], "UNKNOWN")

    def test_forecast_centering_probe_uses_forecast_anchor_without_market_prices(self):
        rows = [
            {
                "market_id": "toronto",
                "target_date": "2026-06-03",
                "snapshot_id": "s1",
                "cutoff_hour": 3,
                "bin_type": "eq",
                "bin_value_c": 10,
                "bin_value_hi": 10,
                "feature_forecast_high": 10,
                "model_probability": 0.10,
                "market_yes": 0.99,
                "outcome": 1,
            },
            {
                "market_id": "toronto",
                "target_date": "2026-06-03",
                "snapshot_id": "s1",
                "cutoff_hour": 3,
                "bin_type": "eq",
                "bin_value_c": 13,
                "bin_value_hi": 13,
                "feature_forecast_high": 10,
                "model_probability": 0.30,
                "market_yes": 0.01,
                "outcome": 0,
            },
        ]

        centered = forecast_centering_rows(rows, 0.5)

        self.assertGreater(forecast_anchor_probability(rows[0]), forecast_anchor_probability(rows[1]))
        self.assertGreater(centered[0]["model_probability"], rows[0]["model_probability"])
        self.assertLess(centered[1]["model_probability"], rows[1]["model_probability"])

    def test_early_hour_market_deltas_surface_blocked_markets(self):
        rows = [
            {
                "market_id": "toronto",
                "target_date": "2026-06-03",
                "snapshot_id": "s1",
                "cutoff_hour": 3,
                "model_probability": 0.90,
                "market_yes": 0.20,
                "outcome": 0,
            },
            {
                "market_id": "toronto",
                "target_date": "2026-06-03",
                "snapshot_id": "s1",
                "cutoff_hour": 3,
                "model_probability": 0.10,
                "market_yes": 0.80,
                "outcome": 1,
            },
            {
                "market_id": "austin",
                "target_date": "2026-06-03",
                "snapshot_id": "s1",
                "cutoff_hour": 4,
                "model_probability": 0.80,
                "market_yes": 0.20,
                "outcome": 1,
            },
            {
                "market_id": "austin",
                "target_date": "2026-06-03",
                "snapshot_id": "s1",
                "cutoff_hour": 4,
                "model_probability": 0.20,
                "market_yes": 0.80,
                "outcome": 0,
            },
        ]

        deltas = early_hour_market_deltas(rows, early_brier_regression_tolerance=0.003)
        by_market = {row["market_id"]: row for row in deltas}

        self.assertEqual(by_market["toronto"]["status"], "BLOCK")
        self.assertIn("early_hour_brier_regression", by_market["toronto"]["blocking_gates"])
        self.assertEqual(by_market["austin"]["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
