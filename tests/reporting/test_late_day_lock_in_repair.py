import unittest

from weather.reporting.research.late_day_lock_in_repair import (
    bin_covers_value,
    compare_summary,
    lock_in_candidate_rows,
    overlock_guardrail,
)


def row(band, probability, outcome, *, high=70.0, snapshot="s1"):
    return {
        "market_id": "toronto",
        "target_date": "2026-06-07",
        "snapshot_id": snapshot,
        "time_slot_minute": 1080,
        "bin_kind": "eq",
        "bin_value_c": band,
        "model_probability": probability,
        "market_yes": 0.80 if outcome else 0.20,
        "outcome": outcome,
        "feature_high_so_far": high,
    }


class LateDayLockInRepairTests(unittest.TestCase):
    def test_lock_in_candidate_normalizes_and_boosts_high_so_far_band(self):
        rows = [
            row(70.0, 0.40, 1),
            row(71.0, 0.60, 0),
        ]

        transformed = lock_in_candidate_rows(rows, {1080}, factor=3.0)

        self.assertTrue(bin_covers_value(rows[0], 70.0))
        self.assertAlmostEqual(sum(item["model_probability"] for item in transformed), 1.0)
        self.assertGreater(transformed[0]["model_probability"], rows[0]["model_probability"])
        summary = compare_summary(rows, transformed)
        self.assertLess(summary["delta_vs_current"], 0)

    def test_overlock_guardrail_blocks_when_high_so_far_band_is_wrong(self):
        rows = [
            row(70.0, 0.40, 0, snapshot="bad"),
            row(71.0, 0.60, 1, snapshot="bad"),
        ]

        guardrail = overlock_guardrail(rows, {1080}, factor=3.0)

        self.assertEqual(guardrail["status"], "BLOCK")
        self.assertGreater(guardrail["summary"]["delta_vs_current"], 0)


if __name__ == "__main__":
    unittest.main()
