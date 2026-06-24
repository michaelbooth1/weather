import csv
import tempfile
import unittest
from pathlib import Path

from weather.collection.snapshot_store import backfill_snapshot_cadence_quality


class TestSnapshotCadenceBackfill(unittest.TestCase):
    def test_backfills_missing_cadence_quality_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "snapshots_long.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "snapshot_id",
                        "captured_at_utc",
                        "range_label",
                        "model_probability",
                    ],
                )
                writer.writeheader()
                writer.writerow({
                    "snapshot_id": "s1",
                    "captured_at_utc": "2026-06-24T04:00:00+00:00",
                    "range_label": "low",
                    "model_probability": "0.2",
                })
                writer.writerow({
                    "snapshot_id": "s1",
                    "captured_at_utc": "2026-06-24T04:00:00+00:00",
                    "range_label": "high",
                    "model_probability": "0.8",
                })
                writer.writerow({
                    "snapshot_id": "s2",
                    "captured_at_utc": "2026-06-24T04:30:00+00:00",
                    "range_label": "low",
                    "model_probability": "0.3",
                })

            result = backfill_snapshot_cadence_quality(root)

            self.assertTrue(result["changed"])
            self.assertEqual(result["updated_row_count"], 3)
            with path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["snapshot_cadence_quality_state"], "clean")
            self.assertEqual(rows[0]["snapshot_cadence_permission"], "allow")
            self.assertEqual(rows[0]["snapshot_cadence_gap_count"], "0")
            self.assertEqual(rows[0]["snapshot_cadence_max_gap_seconds"], "")
            self.assertEqual(rows[2]["snapshot_cadence_quality_state"], "gappy")
            self.assertEqual(rows[2]["snapshot_cadence_permission"], "deny")
            self.assertEqual(rows[2]["snapshot_cadence_gap_count"], "1")
            self.assertEqual(rows[2]["snapshot_cadence_max_gap_seconds"], "1800.0")


if __name__ == "__main__":
    unittest.main()
