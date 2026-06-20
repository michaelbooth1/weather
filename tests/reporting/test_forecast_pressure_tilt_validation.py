import csv
import tempfile
import unittest
from pathlib import Path

from weather.reporting.forecast_pressure_tilt_validation import (
    SCHEMA_VERSION,
    build_payload,
    score_rows,
    tilted_probabilities,
)


FIELDNAMES = [
    "market_id",
    "target_date",
    "snapshot_id",
    "band_key",
    "probability",
    "current_probability",
    "market_yes",
    "outcome",
    "forecast_bucket_pressure",
    "cutoff_regime",
    "forecast_disagreement_bucket",
    "source_freshness_state",
]


def row(market, date, snapshot, band, probability, market_yes, outcome, pressure):
    return {
        "market_id": market,
        "target_date": date,
        "snapshot_id": snapshot,
        "band_key": band,
        "probability": str(probability),
        "current_probability": str(probability),
        "market_yes": str(market_yes),
        "outcome": str(outcome),
        "forecast_bucket_pressure": pressure,
        "cutoff_regime": "early",
        "forecast_disagreement_bucket": "low",
        "source_freshness_state": "all_fresh",
    }


def write_rows(path, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


class ForecastPressureTiltValidationTests(unittest.TestCase):
    def test_tilted_probabilities_normalize_within_snapshot(self):
        rows = [
            {"market_id": "m", "snapshot_id": "s", "probability": 0.25, "forecast_bucket_pressure": "warm_side", "cutoff_regime": "early"},
            {"market_id": "m", "snapshot_id": "s", "probability": 0.75, "forecast_bucket_pressure": "cool_side", "cutoff_regime": "early"},
        ]

        probabilities = tilted_probabilities(rows, "warm_side", 3.0)

        self.assertAlmostEqual(sum(probabilities), 1.0)
        self.assertAlmostEqual(probabilities[0], 0.5)
        self.assertAlmostEqual(probabilities[1], 0.5)

    def test_score_rows_applies_forecast_pressure_tilt(self):
        rows = [
            {"market_id": "m", "snapshot_id": "s", "probability": 0.25, "current_probability": 0.25, "market_probability": 0.70, "outcome": 1, "forecast_bucket_pressure": "warm_side", "cutoff_regime": "early"},
            {"market_id": "m", "snapshot_id": "s", "probability": 0.75, "current_probability": 0.75, "market_probability": 0.30, "outcome": 0, "forecast_bucket_pressure": "cool_side", "cutoff_regime": "early"},
        ]

        baseline = score_rows(rows)
        tilted = score_rows(rows, "warm_side", 3.0)

        self.assertLess(tilted["candidate_brier"], baseline["candidate_brier"])

    def test_build_payload_selects_policy_on_train_and_blocks_bad_holdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rows.csv"
            write_rows(path, [
                row("m", "2026-06-01", "train", "warm", 0.25, 0.70, 1, "warm_side"),
                row("m", "2026-06-01", "train", "cool", 0.75, 0.30, 0, "cool_side"),
                row("m", "2026-06-02", "eval", "warm", 0.25, 0.30, 0, "warm_side"),
                row("m", "2026-06-02", "eval", "cool", 0.75, 0.70, 1, "cool_side"),
            ])

            payload = build_payload([path], factor_grid="1,3", policies_csv="none,warm_side")

        self.assertEqual(payload["schema_version"], SCHEMA_VERSION)
        self.assertEqual(payload["selected_policy_by_market"]["m"], "warm_side")
        self.assertEqual(payload["selected_factor_by_market"]["m"], 3.0)
        self.assertEqual(payload["readiness_status"], "BLOCK")
        self.assertEqual(payload["market_results"][0]["holdout_status"], "BLOCK")

    def test_build_payload_can_pass_when_tilt_holds_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rows.csv"
            write_rows(path, [
                row("m", "2026-06-01", "train", "warm", 0.25, 0.70, 1, "warm_side"),
                row("m", "2026-06-01", "train", "cool", 0.75, 0.30, 0, "cool_side"),
                row("m", "2026-06-02", "eval", "warm", 0.25, 0.70, 1, "warm_side"),
                row("m", "2026-06-02", "eval", "cool", 0.75, 0.30, 0, "cool_side"),
            ])

            payload = build_payload([path], factor_grid="1,3", policies_csv="none,warm_side", market_tol=0.50)

        self.assertEqual(payload["selected_policy_by_market"]["m"], "warm_side")
        self.assertEqual(payload["readiness_status"], "PASS")


if __name__ == "__main__":
    unittest.main()
