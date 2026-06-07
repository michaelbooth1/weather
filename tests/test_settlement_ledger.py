import json
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath("src"))

from market_registry import NYC
from settlement_ledger import reconcile_with_polymarket, resolution_spec_for


class TestSettlementLedger(unittest.TestCase):
    def test_resolution_spec_pins_market_rules(self):
        spec = resolution_spec_for(NYC)

        self.assertEqual(spec["market_id"], "nyc")
        self.assertEqual(spec["market_unit"], "F")
        self.assertEqual(spec["wu_history_id"], "KLGA:9:US")
        self.assertEqual(spec["station_icao"], "KLGA")
        self.assertEqual(spec["daily_max_window"]["timezone"], "America/New_York")
        self.assertEqual(spec["rounding"]["method"], "round_half_up")

    def test_polymarket_reconciliation_matches_resolved_yes_band(self):
        event = {
            "closed": True,
            "markets": [
                {
                    "groupItemTitle": "88-89F",
                    "closed": True,
                    "umaResolutionStatus": "resolved",
                    "outcomes": json.dumps(["Yes", "No"]),
                    "outcomePrices": json.dumps(["0", "1"]),
                },
                {
                    "groupItemTitle": "90-91F",
                    "closed": True,
                    "umaResolutionStatus": "resolved",
                    "outcomes": json.dumps(["Yes", "No"]),
                    "outcomePrices": json.dumps(["1", "0"]),
                },
            ],
        }

        result = reconcile_with_polymarket(event, 90, {"label": "90-91F"})

        self.assertEqual(result["status"], "match")
        self.assertEqual(result["matching_winning_markets"][0]["label"], "90-91F")

    def test_polymarket_reconciliation_flags_mismatch(self):
        event = {
            "closed": True,
            "markets": [
                {
                    "groupItemTitle": "88-89F",
                    "closed": True,
                    "umaResolutionStatus": "resolved",
                    "outcomes": json.dumps(["Yes", "No"]),
                    "outcomePrices": json.dumps(["1", "0"]),
                },
            ],
        }

        result = reconcile_with_polymarket(event, 90, {"label": "90-91F"})

        self.assertEqual(result["status"], "mismatch")
        self.assertEqual(result["winning_markets"][0]["label"], "88-89F")


if __name__ == "__main__":
    unittest.main()
