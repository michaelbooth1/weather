import csv
import json
import tempfile
import unittest
from pathlib import Path

from weather.reporting.bottom_location_winner_centering import (
    DEFAULT_TEN_MINUTE_REPORT,
    DEFAULT_VARIANT_ROWS,
    SCHEMA_VERSION,
    build_payload,
    write_outputs,
)


FIELDS = [
    "variant_id",
    "market_id",
    "target_date",
    "snapshot_id",
    "band_key",
    "probability",
    "current_probability",
    "market_yes",
    "outcome",
    "captured_at_local",
    "bin_type",
    "bin_value",
    "cutoff_regime",
]


def row(market_id, date, snapshot, band, probability, current, market_probability, outcome, captured, regime):
    return {
        "variant_id": "repair_v1",
        "market_id": market_id,
        "target_date": date,
        "snapshot_id": snapshot,
        "band_key": band,
        "probability": str(probability),
        "current_probability": str(current),
        "market_yes": str(market_probability),
        "outcome": str(outcome),
        "captured_at_local": captured,
        "bin_type": "eq",
        "bin_value": band.split(":", 1)[1],
        "cutoff_regime": regime,
    }


def write_rows(path, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def winning_pair(market, date, label, winner_p, current_p, market_p, captured, regime):
    return [
        row(market, date, f"{label}-{market}", "eq:70", winner_p, current_p, market_p, 1, captured, regime),
        row(
            market,
            date,
            f"{label}-{market}",
            "eq:72",
            1.0 - winner_p,
            1.0 - current_p,
            1.0 - market_p,
            0,
            captured,
            regime,
        ),
    ]


class BottomLocationWinnerCenteringTests(unittest.TestCase):
    def test_default_gate_uses_active_timesplit_no_market_candidate(self):
        self.assertEqual(
            Path(DEFAULT_VARIANT_ROWS).name,
            "item224_active_timesplit_logistic_repair_rows.csv",
        )
        self.assertEqual(
            Path(DEFAULT_TEN_MINUTE_REPORT).name,
            "item224_active_timesplit_logistic_repair_ten_minute.json",
        )

    def test_build_payload_requires_hard_markets_to_clear_required_slices(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows_path = root / "rows.csv"
            ten_minute = root / "ten.json"
            ten_minute.write_text(json.dumps({"weak_slots": {"slot_minutes": [180]}}), encoding="utf-8")
            rows = []
            for market in ["seattle", "nyc", "miami"]:
                rows.extend(winning_pair(market, "2026-06-01", "weak", 0.72, 0.42, 0.70, "2026-06-01T03:00:00-04:00", "early"))
                rows.extend(winning_pair(market, "2026-06-01", "midday", 0.66, 0.45, 0.64, "2026-06-01T12:00:00-04:00", "midday"))
                rows.extend(winning_pair(market, "2026-06-01", "late", 0.50, 0.50, 0.55, "2026-06-01T17:00:00-04:00", "late"))
                rows.extend(winning_pair(market, "2026-06-01", "lock", 0.50, 0.50, 0.55, "2026-06-01T21:00:00-04:00", "lock_in"))
            write_rows(rows_path, rows)

            payload = build_payload(rows_path, ten_minute, bottom_markets=("seattle", "nyc", "miami"))
            json_out, report_out = write_outputs(payload, root / "out.json", root / "out.md")
            json_exists = Path(json_out).exists()
            report_text = Path(report_out).read_text(encoding="utf-8")

        self.assertEqual(payload["schema_version"], SCHEMA_VERSION)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["blocker_count"], 0)
        self.assertEqual(payload["summary"]["required_slice_block_count"], 0)
        self.assertTrue(json_exists)
        self.assertIn("Bottom-Location Winner-Centering", report_text)

    def test_build_payload_blocks_market_that_still_trails_market(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows_path = root / "rows.csv"
            ten_minute = root / "ten.json"
            ten_minute.write_text(json.dumps({"weak_slots": {"slot_minutes": [180]}}), encoding="utf-8")
            rows = []
            rows.extend(winning_pair("seattle", "2026-06-01", "weak", 0.30, 0.42, 0.70, "2026-06-01T03:00:00-04:00", "early"))
            rows.extend(winning_pair("seattle", "2026-06-01", "midday", 0.30, 0.45, 0.64, "2026-06-01T12:00:00-04:00", "midday"))
            for market in ["nyc", "miami"]:
                rows.extend(winning_pair(market, "2026-06-01", "weak", 0.72, 0.42, 0.70, "2026-06-01T03:00:00-04:00", "early"))
                rows.extend(winning_pair(market, "2026-06-01", "midday", 0.66, 0.45, 0.64, "2026-06-01T12:00:00-04:00", "midday"))
            write_rows(rows_path, rows)

            payload = build_payload(rows_path, ten_minute, bottom_markets=("seattle", "nyc", "miami"))

        self.assertEqual(payload["status"], "BLOCK")
        self.assertGreater(payload["summary"]["required_slice_block_count"], 0)
        first = payload["first_blocker"]
        self.assertEqual(first["market_id"], "seattle")
        self.assertIn(first["slice"], {"weak_slot", "early", "midday"})


if __name__ == "__main__":
    unittest.main()
