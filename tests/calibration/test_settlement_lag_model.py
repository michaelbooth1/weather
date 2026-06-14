import os
import sys
import unittest

sys.path.insert(0, os.path.abspath("src"))

from settlement_lag_model import (
    build_artifact,
    rows_from_metar_history,
    settlement_catchup_probability,
)
from toronto_model import TorontoHighTempModel


class TestSettlementLagModel(unittest.TestCase):
    def test_metar_history_rows_capture_leads_and_revisions(self):
        wu_rows = {
            "2020-05-27": [
                {"minute_of_day": 480, "temp_c": 20.0},
                {"minute_of_day": 900, "temp_c": 22.0},
            ]
        }
        metar_rows = {
            "2020-05-27": [
                {"minute_of_day": 480, "temp_c": 21.0},
                {"minute_of_day": 900, "temp_c": 22.0},
            ]
        }
        daily = {"2020-05-27": {"bucket": 22, "row_count": 24}}

        rows = rows_from_metar_history(wu_rows, metar_rows, daily)
        lead_rows = [row for row in rows if row["row_kind"] == "lead"]
        revision_rows = [row for row in rows if row["row_kind"] == "revision"]

        self.assertTrue(lead_rows)
        self.assertTrue(revision_rows)
        self.assertEqual(lead_rows[0]["source"], "metar")
        self.assertEqual(lead_rows[0]["caught_up"], 1)

    def test_catchup_probability_uses_context_fallbacks(self):
        artifact = build_artifact([
            {
                "row_kind": "lead",
                "source": "eccc_swob",
                "target_date": "2026-05-27",
                "cutoff_hour": 14,
                "source_bucket": 25,
                "wu_floor_bucket": 24,
                "gap": 1,
                "final_bucket": 25,
                "caught_up": 1,
                "lag_minutes": 120,
            }
            for _ in range(30)
        ], [])

        probability = settlement_catchup_probability(
            artifact,
            "eccc_swob",
            source_bucket=25,
            wu_floor_bucket=24,
            cutoff_hour=14,
        )

        self.assertGreater(probability, 0.90)

    def test_live_swob_floor_strength_comes_from_lag_artifact(self):
        high_model = TorontoHighTempModel()
        high_model.settlement_lag_model = build_artifact([
            {
                "row_kind": "lead",
                "source": "eccc_swob",
                "target_date": f"2026-05-{day:02d}",
                "cutoff_hour": 14,
                "source_bucket": 26,
                "wu_floor_bucket": 25,
                "gap": 1,
                "final_bucket": 26,
                "caught_up": 1,
                "lag_minutes": 60,
            }
            for day in range(1, 31)
        ], [])
        low_model = TorontoHighTempModel()
        low_model.settlement_lag_model = build_artifact([
            {
                "row_kind": "lead",
                "source": "eccc_swob",
                "target_date": f"2026-05-{day:02d}",
                "cutoff_hour": 14,
                "source_bucket": 26,
                "wu_floor_bucket": 25,
                "gap": 1,
                "final_bucket": 25,
                "caught_up": 0,
                "lag_minutes": None,
            }
            for day in range(1, 31)
        ], [])
        scores = {24: 1.0, 25: 1.0, 26: 1.0}

        high = high_model.apply_live_observed_floor(scores, 26.0, 25.0, hour=14)
        low = low_model.apply_live_observed_floor(scores, 26.0, 25.0, hour=14)

        self.assertLess(sum(high[b] for b in (24, 25)), sum(low[b] for b in (24, 25)))


if __name__ == "__main__":
    unittest.main()
