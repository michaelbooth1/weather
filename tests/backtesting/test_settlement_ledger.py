import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from weather.market.market_registry import NYC
from weather.backtesting.settlement_ledger import (
    ledger_label_for_slug,
    read_jsonl,
    reconcile_with_polymarket,
    resolution_spec_for,
    upsert_ledger_record,
    verify_ledger_history,
)


class TestSettlementLedger(unittest.TestCase):
    @staticmethod
    def _label(bucket):
        return {
            "schema_version": "settlement_ledger_v2",
            "event_slug": "highest-temperature-in-nyc-on-july-12-2026",
            "market_id": "nyc",
            "target_date": "2026-07-12",
            "settlement_bucket": bucket,
            "settlement_source": "daily_summary",
            "finalized_at_utc": "2026-07-13T04:00:00+00:00",
            "evidence": {
                "five_time_provenance": {"first_seen_at": "2026-07-13T03:59:00+00:00"},
                "raw_resolution_hashes": {"daily_summary_sha256": "abc"},
                "override_provenance": {},
            },
        }

    def test_ledger_revisions_are_append_only_superseding_and_current_read_is_compatible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = self._label(82)
            upsert_ledger_record(first, root)
            second = self._label(83)
            upsert_ledger_record(second, root)
            rows = read_jsonl(root / "nyc" / "ledger.jsonl")
            current = ledger_label_for_slug(second["event_slug"], root)

            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["settlement_bucket"], 82)
            self.assertEqual(rows[1]["settlement_bucket"], 83)
            self.assertEqual(rows[0]["revision_number"], 1)
            self.assertEqual(rows[1]["revision_number"], 2)
            self.assertEqual(rows[1]["supersedes_revision_id"], rows[0]["revision_id"])
            self.assertEqual(rows[1]["previous_label_hash"], rows[0]["label_hash"])
            self.assertEqual(current["settlement_bucket"], 83)
            bucket_change = next(
                change for change in rows[1]["revision_changes"]
                if change["field"] == "settlement_bucket"
            )
            self.assertEqual(bucket_change, {"field": "settlement_bucket", "old": 82, "new": 83})
            self.assertEqual(
                rows[1]["revision_provenance"]["raw_resolution_hashes"],
                {"daily_summary_sha256": "abc"},
            )
            self.assertEqual(verify_ledger_history(rows)["status"], "PASS")

            tampered = [dict(row) for row in rows]
            tampered[1]["settlement_bucket"] = 84
            self.assertEqual(verify_ledger_history(tampered)["status"], "BLOCK")

    def test_identical_settlement_write_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = self._label(82)
            upsert_ledger_record(first, root)
            duplicate = self._label(82)
            upsert_ledger_record(duplicate, root)
            rows = read_jsonl(root / "nyc" / "ledger.jsonl")

            self.assertEqual(len(rows), 1)
            self.assertEqual(duplicate["revision_id"], first["revision_id"])

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

    def test_polymarket_reconciliation_marks_missing_local_settlement_as_candidate(self):
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

        result = reconcile_with_polymarket(event, None, {})

        self.assertEqual(result["status"], "local_missing")
        self.assertEqual(result["polymarket_repair_candidate"]["status"], "available")
        self.assertEqual(result["polymarket_repair_candidate"]["winning_band"], "88-89F")
        self.assertFalse(result["polymarket_repair_candidate"]["promotion_countable"])


if __name__ == "__main__":
    unittest.main()
