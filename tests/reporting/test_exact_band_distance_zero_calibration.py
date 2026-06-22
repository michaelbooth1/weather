import csv
import tempfile
import unittest
from pathlib import Path

from weather.reporting.exact_band_distance_zero_calibration import (
    SCHEMA_VERSION,
    build_payload,
    read_variant_rows,
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
    "settlement_distance_bucket",
]


def row(
    snapshot,
    band,
    probability,
    current,
    market,
    outcome,
    captured="2026-06-13T04:00:00-04:00",
    regime="",
    market_id="seattle",
):
    bin_value = band.split(":", 1)[1].split("-", 1)[0]
    return {
        "variant_id": "exact_distance_v1",
        "market_id": market_id,
        "target_date": "2026-06-13",
        "snapshot_id": snapshot,
        "band_key": band,
        "probability": str(probability),
        "current_probability": str(current),
        "market_yes": str(market),
        "outcome": str(outcome),
        "captured_at_local": captured,
        "bin_type": "eq" if band.startswith("eq:") else "gte",
        "bin_value": bin_value,
        "cutoff_regime": regime,
        "settlement_distance_bucket": "0" if outcome else "1",
    }


def snapshot_rows(
    snapshot,
    *,
    winner_probability=0.72,
    current_winner_probability=0.42,
    market_winner_probability=0.70,
    one_above_probability=0.14,
    current_one_above_probability=0.20,
    market_one_above_probability=0.15,
    captured="2026-06-13T04:00:00-04:00",
    regime="",
):
    return [
        row(
            snapshot,
            "eq:70.0-71.0",
            0.14,
            0.20,
            0.15,
            0,
            captured=captured,
            regime=regime,
        ),
        row(
            snapshot,
            "eq:72.0-73.0",
            winner_probability,
            current_winner_probability,
            market_winner_probability,
            1,
            captured=captured,
            regime=regime,
        ),
        row(
            snapshot,
            "eq:74.0-75.0",
            one_above_probability,
            current_one_above_probability,
            market_one_above_probability,
            0,
            captured=captured,
            regime=regime,
        ),
    ]


def write_rows(path, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


class ExactBandDistanceZeroCalibrationTests(unittest.TestCase):
    def test_build_payload_passes_targets_and_guardrails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows_path = root / "rows.csv"
            write_rows(rows_path, [
                *snapshot_rows("early-1"),
                *snapshot_rows(
                    "ramp-1",
                    winner_probability=0.50,
                    current_winner_probability=0.50,
                    market_winner_probability=0.52,
                    captured="2026-06-13T10:00:00-04:00",
                ),
                *snapshot_rows(
                    "late-1",
                    winner_probability=0.50,
                    current_winner_probability=0.50,
                    market_winner_probability=0.52,
                    captured="2026-06-13T16:00:00-04:00",
                ),
                *snapshot_rows(
                    "lock-1",
                    winner_probability=0.50,
                    current_winner_probability=0.50,
                    market_winner_probability=0.52,
                    captured="2026-06-13T21:00:00-04:00",
                ),
            ])

            payload = build_payload(rows_path)
            json_out, report_out = write_outputs(payload, root / "out.json", root / "out.md")
            json_exists = Path(json_out).exists()
            report_text = Path(report_out).read_text(encoding="utf-8")

        self.assertEqual(payload["schema_version"], SCHEMA_VERSION)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["blocker_count"], 0)
        self.assertTrue(json_exists)
        self.assertIn("Exact-Band", report_text)
        slices = {row["slice"]: row for row in payload["by_slice"]}
        self.assertEqual(slices["exact_band_early"]["status"], "PASS")
        self.assertEqual(slices["settlement_distance_0_early"]["status"], "PASS")
        self.assertEqual(slices["one_above_early"]["status"], "PASS")
        self.assertEqual(slices["ramp"]["status"], "PASS")

    def test_signed_offsets_use_adjacent_band_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows_path = Path(tmp) / "rows.csv"
            write_rows(rows_path, snapshot_rows("early-1"))

            rows = read_variant_rows(rows_path)

        by_band = {row["band_key"]: row for row in rows}
        self.assertEqual(by_band["eq:70.0-71.0"]["signed_band_offset"], -1)
        self.assertEqual(by_band["eq:72.0-73.0"]["signed_band_offset"], 0)
        self.assertEqual(by_band["eq:74.0-75.0"]["signed_band_offset"], 1)

    def test_one_above_regression_blocks_even_when_targets_improve(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows_path = Path(tmp) / "rows.csv"
            write_rows(rows_path, [
                *snapshot_rows(
                    "early-1",
                    winner_probability=0.90,
                    current_winner_probability=0.20,
                    market_winner_probability=0.80,
                    one_above_probability=0.20,
                    current_one_above_probability=0.10,
                    market_one_above_probability=0.18,
                ),
                *snapshot_rows(
                    "ramp-1",
                    winner_probability=0.50,
                    current_winner_probability=0.50,
                    market_winner_probability=0.52,
                    captured="2026-06-13T10:00:00-04:00",
                ),
            ])

            payload = build_payload(rows_path)

        self.assertEqual(payload["status"], "BLOCK")
        guardrail_blockers = [
            blocker for blocker in payload["blockers"]
            if blocker["category"] == "guardrail_slice" and blocker["slice"] == "one_above_early"
        ]
        self.assertEqual(len(guardrail_blockers), 1)
        self.assertIn("regresses current", guardrail_blockers[0]["detail"])


if __name__ == "__main__":
    unittest.main()
