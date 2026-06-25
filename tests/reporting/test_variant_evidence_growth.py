import unittest

from weather.reporting.candidate_lifecycle.variant_evidence_growth import build_payload, render_report


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
        self.assertIn("broad_promotion_claim_blocked", categories)
        self.assertFalse(payload["evidence_sla"]["broad_promotion_claim_allowed"])
        overall_reason = next(
            row for row in payload["no_growth_reasons"]
            if row["scope"] == "overall"
        )
        self.assertEqual(overall_reason["reason"], "variant_rows_only")
        self.assertIn("daily_refresh", overall_reason["action"])
        self.assertIn("Model Variant Evidence Growth", render_report(payload))

    def test_records_trend_and_shadow_market_sample_targets(self):
        baseline = [_row("v1", "2026-06-11", 0.60)]
        current = [
            _row("v1", "2026-06-11", 0.60),
            _row("v1", "2026-06-12", 0.61, snapshot_id="2026-06-12-s1"),
        ]

        payload = build_payload(
            current,
            baseline_rows=baseline,
            per_shadow_market_min_market_days=3,
        )

        self.assertEqual(payload["delta_vs_baseline"]["market_day_count"], 1)
        trend = {row["window"]: row for row in payload["trend"]}
        self.assertIn("latest_day", trend)
        self.assertIn("rolling_7d", trend)
        target = payload["evidence_sla"]["sample_target_rows"][0]
        self.assertEqual(target["market_id"], "nyc")
        self.assertEqual(target["status"], "BLOCK")
        self.assertEqual(target["missing_market_days"], 1)
        report = render_report(payload)
        self.assertIn("Evidence SLA", report)
        self.assertIn("Shadow-Market Sample Targets", report)


if __name__ == "__main__":
    unittest.main()
