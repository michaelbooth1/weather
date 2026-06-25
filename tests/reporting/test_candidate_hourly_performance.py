import csv
import tempfile
import unittest
from pathlib import Path

from weather.reporting.hourly.candidate_hourly_performance import (
    build_candidate_hourly_performance,
    hourly_checkpoint_rows,
    read_variant_rows,
    write_outputs,
)


FIELDNAMES = [
    "variant_id",
    "variant_family",
    "uses_market_features",
    "is_control",
    "market_id",
    "target_date",
    "snapshot_id",
    "band_key",
    "probability",
    "current_probability",
    "recorded_probability",
    "market_yes",
    "outcome",
    "captured_at_local",
]


def write_rows(path, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


class TestCandidateHourlyPerformance(unittest.TestCase):
    def test_candidate_hourly_gate_scores_local_hour_checkpoints(self):
        rows = [
            {
                "variant_id": "candidate",
                "variant_family": "test",
                "uses_market_features": "False",
                "is_control": "False",
                "market_id": "austin",
                "target_date": "2026-06-07",
                "snapshot_id": "s0a",
                "band_key": "eq:90",
                "probability": "0.90",
                "current_probability": "0.60",
                "recorded_probability": "0.60",
                "market_yes": "0.70",
                "outcome": "1",
                "captured_at_local": "2026-06-07T00:01:00-04:00",
            },
            {
                "variant_id": "candidate",
                "variant_family": "test",
                "uses_market_features": "False",
                "is_control": "False",
                "market_id": "austin",
                "target_date": "2026-06-07",
                "snapshot_id": "s0b",
                "band_key": "eq:90",
                "probability": "0.01",
                "current_probability": "0.60",
                "recorded_probability": "0.60",
                "market_yes": "0.70",
                "outcome": "1",
                "captured_at_local": "2026-06-07T00:45:00-04:00",
            },
            {
                "variant_id": "candidate",
                "variant_family": "test",
                "uses_market_features": "False",
                "is_control": "False",
                "market_id": "austin",
                "target_date": "2026-06-08",
                "snapshot_id": "s1",
                "band_key": "eq:88",
                "probability": "0.01",
                "current_probability": "0.20",
                "recorded_probability": "0.20",
                "market_yes": "0.10",
                "outcome": "0",
                "captured_at_local": "2026-06-08T01:05:00-04:00",
            },
            {
                "variant_id": "candidate",
                "variant_family": "test",
                "uses_market_features": "False",
                "is_control": "False",
                "market_id": "austin",
                "target_date": "2026-06-08",
                "snapshot_id": "s15",
                "band_key": "eq:88",
                "probability": "0.10",
                "current_probability": "0.20",
                "recorded_probability": "0.20",
                "market_yes": "0.20",
                "outcome": "0",
                "captured_at_local": "2026-06-08T15:05:00-04:00",
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "variants.csv"
            write_rows(path, rows)

            parsed = read_variant_rows(path)
            checkpoints = hourly_checkpoint_rows(parsed)
            payload = build_candidate_hourly_performance(path, min_market_days=1)
            json_path, report_path = write_outputs(
                payload,
                json_out=Path(tmp) / "candidate_hourly.json",
                report_out=Path(tmp) / "candidate_hourly.md",
            )
            json_exists = Path(json_path).exists()
            report = Path(report_path).read_text(encoding="utf-8")

        self.assertEqual(len(parsed), 4)
        self.assertEqual(len(checkpoints), 3)
        self.assertEqual(payload["schema_version"], "candidate_hourly_performance_v0.1")
        self.assertEqual(payload["candidate_hourly_gate"]["status"], "PASS")
        self.assertEqual(payload["candidate_hourly_gate"]["blocker_count"], 0)
        early = payload["candidate_hourly_gate"]["early_morning"]
        self.assertEqual(early["market_days"], 2)
        self.assertLess(early["variant_brier"], early["current_brier"])
        self.assertLess(early["variant_brier"], early["market_brier"])
        self.assertTrue(json_exists)
        self.assertIn("Candidate Hourly Performance Audit", report)

    def test_candidate_hourly_gate_blocks_market_regression(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "variants.csv"
            write_rows(path, [
                {
                    "variant_id": "candidate",
                    "variant_family": "test",
                    "uses_market_features": "False",
                    "is_control": "False",
                    "market_id": "seattle",
                    "target_date": "2026-06-07",
                    "snapshot_id": "s0",
                    "band_key": "eq:65",
                    "probability": "0.10",
                    "current_probability": "0.20",
                    "recorded_probability": "0.20",
                    "market_yes": "0.90",
                    "outcome": "1",
                    "captured_at_local": "2026-06-07T03:01:00-04:00",
                }
            ])

            payload = build_candidate_hourly_performance(path, min_market_days=1)

        self.assertEqual(payload["candidate_hourly_gate"]["status"], "BLOCK")
        self.assertEqual(
            payload["candidate_hourly_gate"]["first_blocker"]["gate"],
            "early_hour_brier_regression",
        )


if __name__ == "__main__":
    unittest.main()
