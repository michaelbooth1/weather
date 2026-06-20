import csv
import json
import tempfile
import unittest
from pathlib import Path

from weather.reporting.predawn_weak_slot_repair import (
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


def write_rows(path, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def row(date, snapshot, band, probability, current, market, outcome, captured="2026-06-07T03:00:00-04:00"):
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


class PredawnWeakSlotRepairTests(unittest.TestCase):
    def test_build_payload_scores_scoped_predawn_candidate_and_guardrails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ten_minute = root / "ten_minute.json"
            ten_minute.write_text(json.dumps({"weak_slots": {"slot_minutes": [180]}}), encoding="utf-8")
            rows_path = root / "candidate_rows.csv"
            rows = []
            for date in ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04"]:
                rows.extend([
                    row(date, f"{date}-weak", "eq:70", 0.75, 0.45, 0.70, 1),
                    row(date, f"{date}-weak", "eq:71", 0.25, 0.55, 0.30, 0),
                    row(
                        date,
                        f"{date}-ramp",
                        "eq:70",
                        0.01,
                        0.60,
                        0.55,
                        1,
                        captured="2026-06-07T10:00:00-04:00",
                    ),
                    row(
                        date,
                        f"{date}-ramp",
                        "eq:71",
                        0.99,
                        0.40,
                        0.45,
                        0,
                        captured="2026-06-07T10:00:00-04:00",
                    ),
                ])
            write_rows(rows_path, rows)

            payload = build_payload(rows_path, ten_minute, market_tol=0.10)
            json_out, report_out = write_outputs(
                payload,
                json_out=root / "predawn.json",
                report_out=root / "predawn.md",
            )
            report = Path(report_out).read_text(encoding="utf-8")
            json_exists = Path(json_out).exists()

        self.assertEqual(payload["schema_version"], SCHEMA_VERSION)
        self.assertEqual(payload["status"], "PASS")
        self.assertLessEqual(payload["weak_slot_summary"]["delta_vs_current"], -0.003)
        self.assertGreater(
            payload["weak_slot_summary"]["winner_variant_probability"],
            payload["weak_slot_summary"]["winner_current_probability"],
        )
        self.assertLess(payload["weak_slot_summary"]["effective_band_delta_vs_current"], 0)
        self.assertTrue(all(row["status"] == "PASS" for row in payload["guardrails"]))
        self.assertTrue(json_exists)
        self.assertIn("Predawn Weak-Slot Repair Validation", report)


if __name__ == "__main__":
    unittest.main()
