import unittest

from weather.reporting.variant_evidence_growth import build_payload, render_report


def _row(variant_id, day, probability, **extra):
    row = {
        "variant_id": variant_id,
        "variant_family": "f_family",
        "uses_market_features": False,
        "is_control": False,
        "market_id": "nyc",
        "target_date": day,
        "snapshot_id": f"{day}-s1",
        "band_key": "eq:82",
        "probability": probability,
        "current_probability": 0.50,
        "recorded_probability": 0.50,
        "market_yes": 0.50,
        "outcome": 1,
        "artifact_hash": f"{variant_id}-artifact",
        "postprocess_config_hash": f"{variant_id}-post",
        "experiment_start_date": "2026-06-15",
    }
    row.update(extra)
    return row


class TestVariantEvidenceGrowth(unittest.TestCase):
    def test_alerts_when_rows_grow_without_unique_observations(self):
        baseline = [_row("v1", "2026-06-11", 0.60)]
        current = [
            _row("v1", "2026-06-11", 0.60),
            _row("v2", "2026-06-11", 0.65),
        ]

        payload = build_payload(current, baseline_rows=baseline)

        self.assertEqual(payload["status"], "ALERT")
        self.assertEqual(payload["summary"]["scored_rows"], 2)
        self.assertEqual(payload["summary"]["unique_observation_count"], 1)
        self.assertEqual(payload["delta_vs_baseline"]["scored_rows"], 1)
        self.assertEqual(payload["delta_vs_baseline"]["unique_observation_count"], 0)
        self.assertEqual(
            payload["minimum_increment_for_broad_promotion_claim"]["unique_observations"],
            1,
        )
        categories = {row["category"] for row in payload["alerts"]}
        self.assertIn("insufficient_unique_observation_increment", categories)
        self.assertIn("Model Variant Evidence Growth", render_report(payload))


if __name__ == "__main__":
    unittest.main()
