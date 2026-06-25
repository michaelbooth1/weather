import unittest

from weather.reporting.location_analysis.no_market_location_transfer import build_payload, render_report


def _row(location, day, actual, forecast, year_hour=7, **extra):
    row = {
        "location_id": location,
        "target_date": day,
        "cutoff_hour": year_hour,
        "actual": actual,
        "forecast_high": forecast,
        "unit": "F",
    }
    row.update(extra)
    return row


def _rows():
    return [
        _row("nyc", "2024-06-01", 80, 80, market_yes=0.5),
        _row("nyc", "2024-06-02", 81, 81),
        _row("boston", "2024-06-01", 90, 80),
        _row("boston", "2024-06-02", 91, 81),
        _row("philadelphia", "2024-06-01", 89, 80),
        _row("philadelphia", "2024-06-02", 90, 81),
        _row("nyc", "2025-06-01", 80, 80),
        _row("nyc", "2025-06-02", 81, 81),
        _row("boston", "2025-06-01", 99, 80),
        _row("philadelphia", "2025-06-02", 99, 81),
    ]


class TestNoMarketLocationTransfer(unittest.TestCase):
    def test_build_payload_scores_price_free_daily_first_transfer_gate(self):
        payload = build_payload(
            _rows(),
            target_markets=["nyc"],
            extra_locations=["boston", "philadelphia"],
            holdout_years=[2025],
            cutoff_regimes=["early"],
            bootstrap_reps=100,
        )

        comparison = payload["band_summary"]["target_plus_extra_minus_target_only"]
        self.assertEqual(payload["backend_detail"]["market_prices_used"], False)
        self.assertGreater(comparison["daily_first"]["brier"]["mean"], 0)
        self.assertEqual(payload["promotion_gate"]["status"], "BLOCK")
        self.assertGreater(payload["evidence_accounting"]["row_multiplier"], 1.0)
        self.assertGreater(payload["evidence_accounting"]["extra_location_days"], 0)
        self.assertGreater(payload["leakage_audit"]["blocked_same_target_date_rows"], 0)
        self.assertIn("No-Market Location Transfer", render_report(payload))

    def test_missing_extra_coverage_is_explicit(self):
        payload = build_payload(
            [_row("nyc", "2024-06-01", 80, 80), _row("nyc", "2025-06-01", 80, 80)],
            target_markets=["nyc"],
            extra_locations=["boston"],
            holdout_years=[2025],
            bootstrap_reps=20,
        )

        missing_conditions = {row["condition"] for row in payload["missing_extra_location_coverage"]}
        self.assertIn("extra_only", missing_conditions)
        self.assertIn("target_plus_extra", missing_conditions)
        self.assertIn("target_plus_extra_minus_target_only", payload["band_summary"] or {})

    def test_registry_gate_can_keep_blocked_locations_out_of_training(self):
        payload = build_payload(
            _rows(),
            target_markets=["nyc"],
            extra_locations=["boston"],
            holdout_years=[2025],
            extra_location_registry=None,
            require_registry_pass=True,
            bootstrap_reps=20,
        )

        self.assertFalse(payload["registry_gate"]["enabled"])
        self.assertEqual(payload["scope"]["extra_locations"], ["boston"])


if __name__ == "__main__":
    unittest.main()
