import csv
import json
import tempfile
import unittest
from pathlib import Path

from weather.reporting.research.predawn_weak_slot_parameter_sweep import (
    SCHEMA_VERSION,
    build_payload,
    write_outputs,
)


FIELDNAMES = [
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
]


def row(date, snapshot, band, probability, current, market, outcome, captured):
    return {
        "variant_id": "candidate_v1",
        "market_id": "toronto",
        "target_date": date,
        "snapshot_id": snapshot,
        "band_key": band,
        "probability": str(probability),
        "current_probability": str(current),
        "market_yes": str(market),
        "outcome": str(outcome),
        "captured_at_local": captured,
    }


def write_rows(path, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


class PredawnWeakSlotParameterSweepTests(unittest.TestCase):
    def test_sweep_passes_when_broad_hourly_and_weak_slot_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ten_minute = root / "ten_minute.json"
            ten_minute.write_text(json.dumps({"weak_slots": {"slot_minutes": [180]}}), encoding="utf-8")
            rows_path = root / "rows.csv"
            rows = []
            for date in ["2026-06-01", "2026-06-02"]:
                rows.extend([
                    row(date, f"{date}-weak", "eq:70", 0.90, 0.50, 0.90, 1, "2026-06-07T03:00:00-04:00"),
                    row(date, f"{date}-weak", "eq:71", 0.10, 0.50, 0.10, 0, "2026-06-07T03:00:00-04:00"),
                ])
            write_rows(rows_path, rows)

            payload = build_payload(
                rows_path,
                ten_minute,
                blend_grid=(0.0,),
                extrapolation_grid=(1.0,),
                power_grid=(1.0,),
            )
            json_out, report_out = write_outputs(payload, root / "sweep.json", root / "sweep.md")
            json_exists = Path(json_out).exists()
            report_text = Path(report_out).read_text(encoding="utf-8")

        self.assertEqual(payload["schema_version"], SCHEMA_VERSION)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["summary"]["pass_both_count"], 1)
        self.assertEqual(payload["summary"]["candidate_hourly_pass_count"], 1)
        self.assertEqual(payload["summary"]["candidate_ten_minute_pass_count"], 1)
        self.assertTrue(json_exists)
        self.assertIn("Predawn Weak-Slot Parameter Sweep", report_text)

    def test_sweep_blocks_when_nonweak_early_rows_keep_broad_gate_bad(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ten_minute = root / "ten_minute.json"
            ten_minute.write_text(json.dumps({"weak_slots": {"slot_minutes": [180]}}), encoding="utf-8")
            rows_path = root / "rows.csv"
            rows = []
            for date in ["2026-06-01", "2026-06-02"]:
                rows.extend([
                    row(date, f"{date}-weak", "eq:70", 0.90, 0.50, 0.90, 1, "2026-06-07T03:00:00-04:00"),
                    row(date, f"{date}-weak", "eq:71", 0.10, 0.50, 0.10, 0, "2026-06-07T03:00:00-04:00"),
                    row(date, f"{date}-bad", "eq:70", 0.10, 0.10, 0.90, 1, "2026-06-07T06:00:00-04:00"),
                    row(date, f"{date}-bad", "eq:71", 0.90, 0.90, 0.10, 0, "2026-06-07T06:00:00-04:00"),
                ])
            write_rows(rows_path, rows)

            payload = build_payload(
                rows_path,
                ten_minute,
                blend_grid=(0.0,),
                extrapolation_grid=(1.0,),
                power_grid=(1.0,),
            )

        self.assertEqual(payload["status"], "BLOCK")
        self.assertEqual(payload["summary"]["pass_both_count"], 0)
        self.assertEqual(payload["summary"]["candidate_hourly_pass_count"], 0)
        self.assertEqual(payload["summary"]["candidate_ten_minute_pass_count"], 1)
        self.assertIn("no swept parameter set", payload["reasons"][0])


if __name__ == "__main__":
    unittest.main()
