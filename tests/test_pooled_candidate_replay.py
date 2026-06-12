import os
import sys
import unittest

sys.path.insert(0, os.path.abspath("src"))

from pooled_candidate_replay import (
    apply_current_blend_guardrail,
    band_probability_from_distribution,
    candidate_comparison,
    market_verdict,
    normalize_partition_probabilities,
)


class TestPooledCandidateReplay(unittest.TestCase):
    def test_band_probability_handles_thresholds_and_ranges(self):
        distribution = {70: 0.10, 71: 0.20, 72: 0.30, 73: 0.40}

        self.assertAlmostEqual(
            band_probability_from_distribution(distribution, "lte", 71),
            0.30,
        )
        self.assertAlmostEqual(
            band_probability_from_distribution(distribution, "gte", 72),
            0.70,
        )
        self.assertAlmostEqual(
            band_probability_from_distribution(distribution, "eq", 71, 72),
            0.50,
        )

    def test_candidate_comparison_scores_all_probability_columns_on_same_rows(self):
        rows = [
            {
                "candidate_p": 0.90,
                "replayed_p": 0.70,
                "recorded_p": 0.60,
                "market_yes": 0.50,
                "outcome": 1,
            },
            {
                "candidate_p": 0.20,
                "replayed_p": 0.30,
                "recorded_p": 0.40,
                "market_yes": 0.60,
                "outcome": 0,
            },
        ]

        comp = candidate_comparison(rows)

        self.assertEqual(comp["n"], 2)
        self.assertLess(comp["candidate_brier"], comp["current_brier"])
        self.assertLess(comp["candidate_brier"], comp["market_brier"])
        self.assertLess(comp["delta_vs_current"], 0)

    def test_market_verdict_blocks_large_current_regression(self):
        verdict, reasons = market_verdict(
            {
                "candidate_brier": 0.20,
                "current_brier": 0.10,
                "market_brier": 0.15,
                "delta_vs_current": 0.10,
            },
            day_count=3,
            trust={"trust_score": 80},
            current_tol=0.003,
            market_tol=0.003,
            min_days=2,
            min_trust=25,
        )

        self.assertEqual(verdict, "BLOCK")
        self.assertIn("regresses current", reasons[0])

    def test_market_verdict_shadows_when_not_better_than_current(self):
        verdict, reasons = market_verdict(
            {
                "candidate_brier": 0.101,
                "current_brier": 0.100,
                "market_brier": 0.130,
                "delta_vs_current": 0.001,
            },
            day_count=3,
            trust={"trust_score": 80},
            current_tol=0.003,
            market_tol=0.003,
            min_days=2,
            min_trust=25,
        )

        self.assertEqual(verdict, "SHADOW")
        self.assertIn("not proven better than current replay", reasons)

    def test_partition_normalization_makes_snapshot_bands_sum_to_one(self):
        rows = [
            {"market_id": "nyc", "snapshot_id": "s1", "candidate_p": 0.8},
            {"market_id": "nyc", "snapshot_id": "s1", "candidate_p": 0.6},
            {"market_id": "nyc", "snapshot_id": "s1", "candidate_p": 0.1},
            {"market_id": "nyc", "snapshot_id": "s2", "candidate_p": 0.4},
        ]

        normalize_partition_probabilities(rows, gamma=1.0)

        self.assertAlmostEqual(sum(row["candidate_p"] for row in rows[:3]), 1.0)
        self.assertAlmostEqual(rows[3]["candidate_p"], 1.0)

    def test_current_blend_guardrail_uses_market_specific_alpha(self):
        rows = [
            {
                "market_id": "denver",
                "candidate_p": 0.80,
                "replayed_p": 0.20,
            },
            {
                "market_id": "chicago",
                "candidate_p": 0.80,
                "replayed_p": 0.20,
            },
        ]

        apply_current_blend_guardrail(rows, {
            "current_blend_default_alpha": 1.0,
            "current_blend_market_alpha": {"denver": 0.25},
        })

        self.assertAlmostEqual(rows[0]["candidate_p"], 0.35)
        self.assertAlmostEqual(rows[1]["candidate_p"], 0.80)


if __name__ == "__main__":
    unittest.main()
