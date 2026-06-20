import csv
import tempfile
import unittest
from pathlib import Path

from weather.reporting.price_free_model_learning import (
    build_price_free_learning,
    classify_current_max_state,
    write_outputs,
)


SLUG = "highest-temperature-in-toronto-on-june-3-2026"


def write_snapshot_folder(root):
    folder = Path(root) / "snapshots" / SLUG
    folder.mkdir(parents=True)
    rows = [
        {
            "snapshot_id": "s6",
            "captured_at_utc": "2026-06-03T10:15:00+00:00",
            "captured_at_local": "2026-06-03T06:15:00-04:00",
            "event_slug": SLUG,
            "model_version": "test-v1",
            "range_label": "9 C or below",
            "bin_kind": "lte",
            "bin_value_c": "9",
            "model_probability": "0.10",
            "market_yes": "",
            "market_no": "",
            "market_status": "inactive",
            "wu_history_high_c": "70",
            "wu_current_c": "68",
            "wu_max_since_7am_c": "90",
        },
        {
            "snapshot_id": "s6",
            "captured_at_utc": "2026-06-03T10:15:00+00:00",
            "captured_at_local": "2026-06-03T06:15:00-04:00",
            "event_slug": SLUG,
            "model_version": "test-v1",
            "range_label": "10 C",
            "bin_kind": "eq",
            "bin_value_c": "10",
            "model_probability": "0.80",
            "market_yes": "",
            "market_no": "",
            "market_status": "inactive",
            "wu_history_high_c": "70",
            "wu_current_c": "68",
            "wu_max_since_7am_c": "90",
        },
        {
            "snapshot_id": "s8",
            "captured_at_utc": "2026-06-03T12:05:00+00:00",
            "captured_at_local": "2026-06-03T08:05:00-04:00",
            "event_slug": SLUG,
            "model_version": "test-v1",
            "range_label": "9 C or below",
            "bin_kind": "lte",
            "bin_value_c": "9",
            "model_probability": "0.05",
            "market_yes": "",
            "market_no": "",
            "market_status": "inactive",
            "wu_history_high_c": "72",
            "wu_current_c": "73",
            "wu_max_since_7am_c": "88",
        },
        {
            "snapshot_id": "s8",
            "captured_at_utc": "2026-06-03T12:05:00+00:00",
            "captured_at_local": "2026-06-03T08:05:00-04:00",
            "event_slug": SLUG,
            "model_version": "test-v1",
            "range_label": "10 C",
            "bin_kind": "eq",
            "bin_value_c": "10",
            "model_probability": "0.90",
            "market_yes": "",
            "market_no": "",
            "market_status": "inactive",
            "wu_history_high_c": "72",
            "wu_current_c": "73",
            "wu_max_since_7am_c": "88",
        },
    ]
    with (folder / "snapshots_long.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return folder


def write_labels_csv(root, folder):
    path = Path(root) / "labels.csv"
    row = {
        "event_slug": SLUG,
        "market_id": "toronto",
        "city": "Toronto",
        "target_date": "2026-06-03",
        "settlement_bucket": "10",
        "settlement_high": "95",
        "settlement_unit": "C",
        "settlement_source": "test",
        "quality_grade": "complete",
        "snapshot_count": "2",
        "band_count": "2",
        "snapshot_tape_path": str(folder / "snapshots_long.csv"),
    }
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    return path


class TestPriceFreeModelLearning(unittest.TestCase):
    def test_scores_inactive_market_without_market_prices(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = write_snapshot_folder(tmp)
            labels_csv = write_labels_csv(tmp, folder)

            payload = build_price_free_learning(
                labels_csv=labels_csv,
                snapshots_root=Path(tmp) / "snapshots",
                quality_grades=("complete",),
            )
            out_dir = Path(tmp) / "out"
            json_out, report_out, hourly_csv, current_max_csv = write_outputs(
                payload,
                json_out=out_dir / "price_free.json",
                report_out=out_dir / "price_free.md",
                hourly_csv_out=out_dir / "price_free_by_hour.csv",
                current_max_csv_out=out_dir / "price_free_current_max.csv",
            )
            report = Path(report_out).read_text(encoding="utf-8")
            json_exists = Path(json_out).exists()
            hourly_csv_exists = Path(hourly_csv).exists()
            current_max_csv_exists = Path(current_max_csv).exists()

        self.assertEqual(payload["schema_version"], "price_free_model_learning_v0.1")
        self.assertEqual(payload["status"], "OK")
        self.assertFalse(payload["evidence_classification"]["uses_market_prices"])
        self.assertEqual(payload["corpus"]["scored_market_days"], 1)
        self.assertEqual(payload["corpus"]["hourly_checkpoint_rows"], 4)
        self.assertIn("absent_market_prices", payload["corpus"]["price_free_reason_counts"])
        self.assertIn("inactive_market", payload["corpus"]["price_free_reason_counts"])
        self.assertEqual(payload["overall"]["hourly_checkpoint"]["partition_model_top_is_winner_rate"], 1.0)
        current = payload["current_max_carryover"]
        self.assertEqual(current["summary"]["risky_or_guarded_count"], 2)
        self.assertEqual(current["summary"]["pre_reset_null_count"], 1)
        self.assertEqual(current["summary"]["support_only_count"], 1)
        self.assertEqual(current["summary"]["early_large_gap_count"], 1)
        states = {row["snapshot_id"]: row["current_max_state"] for row in current["rows"]}
        self.assertEqual(states["s6"], "pre_reset_current_max_null")
        self.assertEqual(states["s8"], "early_current_max_history_gap")
        self.assertIn("Price-Free Model Learning Audit", report)
        self.assertIn("Current-Max Carryover Guard", report)
        self.assertTrue(json_exists)
        self.assertTrue(hourly_csv_exists)
        self.assertTrue(current_max_csv_exists)

    def test_current_max_classifier_nulls_pre_reset_and_validates_history(self):
        pre_reset = classify_current_max_state(
            current_max=90,
            wu_history_high=70,
            current_temp=68,
            cutoff_hour=6,
            final_high=95,
        )
        validated = classify_current_max_state(
            current_max=72,
            wu_history_high=72,
            current_temp=72,
            cutoff_hour=9,
            final_high=80,
        )

        self.assertEqual(pre_reset["feature_disposition"], "null_before_reset")
        self.assertEqual(pre_reset["current_max_state"], "pre_reset_current_max_null")
        self.assertEqual(validated["feature_disposition"], "validated")
        self.assertEqual(validated["current_max_state"], "wu_history_validated_current_max")


if __name__ == "__main__":
    unittest.main()
