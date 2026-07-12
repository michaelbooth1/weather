import csv
import hashlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from weather.backtesting.settlement_ledger import build_label
from weather.market.market_day_labels import finalize_folders, missing_fraction, quality_grade


def _resolved_event(label):
    return {
        "closed": True,
        "markets": [
            {
                "groupItemTitle": label,
                "closed": True,
                "umaResolutionStatus": "resolved",
                "outcomes": json.dumps(["Yes", "No"]),
                "outcomePrices": json.dumps(["1", "0"]),
            }
        ],
    }


def _write_toronto_tape(folder, *, omitted_indexes=None):
    omitted_indexes = set(omitted_indexes or [])
    start = datetime(2026, 5, 27, 11, 0)
    pd.DataFrame([
        {
            "snapshot_id": f"s{i}",
            "captured_at_local": (start + timedelta(minutes=10 * i)).isoformat(),
            "range_label": "25 C",
            "bin_kind": "eq",
            "bin_value_c": 25,
            "model_probability": 0.8,
            "market_yes": 0.4,
            "wu_history_high_c": 25.0,
        }
        for i in range(43)
        if i not in omitted_indexes
    ]).to_csv(folder / "snapshots_long.csv", index=False)


class TestMarketDayLabels(unittest.TestCase):
    def test_quality_grade(self):
        self.assertEqual(quality_grade(0, 0, None, "none"), "missing_settlement")
        self.assertEqual(quality_grade(0, 0, 25, "daily_summary"), "missing_tape")
        self.assertEqual(quality_grade(8, 10, 25, "override"), "manual_override")
        self.assertEqual(quality_grade(3, 10, 25, "daily_summary"), "partial")
        self.assertEqual(quality_grade(8, 10, 25, "daily_summary(sparse)"), "partial")
        self.assertEqual(quality_grade(8, 10, 25, "daily_summary", collection_clean=False), "partial")
        self.assertEqual(quality_grade(8, 10, 25, "daily_summary", 0.25), "stale_source")
        self.assertEqual(quality_grade(8, 10, 25, "daily_summary"), "complete")

    def test_missing_fraction_flags_missing_core_columns(self):
        frame = pd.DataFrame([{"model_probability": 0.5}, {"model_probability": None}])

        self.assertEqual(missing_fraction(frame, ["market_yes"]), 1.0)
        self.assertAlmostEqual(missing_fraction(frame, ["model_probability"]), 0.5)

    def test_finalize_writes_folder_json_and_labels_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "highest-temperature-in-toronto-on-may-27-2026"
            folder.mkdir()
            _write_toronto_tape(folder)
            daily = root / "daily.csv"
            daily.write_text(
                "local_date,row_count,max_temp_bucket_c\n2026-05-27,24,25\n",
                encoding="utf-8",
            )
            labels_csv = root / "labels.csv"
            ledger_root = root / "settlements"

            labels = finalize_folders(
                [folder],
                daily_summary_path=daily,
                labels_csv=labels_csv,
                ledger_root=ledger_root,
            )
            folder_label = json.loads((folder / "settlement.json").read_text(encoding="utf-8"))
            csv_rows = list(csv.DictReader(labels_csv.open(encoding="utf-8", newline="")))
            ledger_rows = [
                json.loads(line)
                for line in (ledger_root / "toronto" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            resolution_specs = json.loads((ledger_root / "resolution_specs.json").read_text(encoding="utf-8"))

            self.assertEqual(labels[0]["quality_grade"], "complete")
            self.assertEqual(labels[0]["schema_version"], "settlement_ledger_v2")
            self.assertTrue(labels[0]["coverage_clean"])
            self.assertIn("quality_reason", folder_label)
            self.assertEqual(folder_label["settlement_bucket"], 25)
            self.assertEqual(csv_rows[0]["event_slug"], folder.name)
            self.assertIn("quality_reason", csv_rows[0])
            self.assertIn("coverage_reason", csv_rows[0])
            self.assertEqual(ledger_rows[0]["event_slug"], folder.name)
            self.assertEqual(ledger_rows[0]["ledger_record_type"], "settlement_revision")
            self.assertEqual(folder_label["revision_id"], ledger_rows[0]["revision_id"])
            self.assertEqual(
                ledger_rows[0]["evidence"]["raw_resolution_hashes"]["snapshot_tape_sha256"],
                hashlib.sha256((folder / "snapshots_long.csv").read_bytes()).hexdigest(),
            )
            self.assertEqual(
                ledger_rows[0]["evidence"]["raw_resolution_hashes"]["daily_summary_sha256"],
                hashlib.sha256(daily.read_bytes()).hexdigest(),
            )
            self.assertEqual(ledger_rows[0]["settlement_unit"], "C")
            self.assertEqual(ledger_rows[0]["resolution_station"], "CYYZ")
            self.assertEqual(resolution_specs["schema_version"], "resolution_spec_v1")

    def test_daily_summary_label_is_countable_without_live_snapshot_high_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "highest-temperature-in-toronto-on-may-27-2026"
            folder.mkdir()
            _write_toronto_tape(folder)
            tape = folder / "snapshots_long.csv"
            frame = pd.read_csv(tape).drop(columns=["wu_history_high_c"])
            frame.to_csv(tape, index=False)
            daily = root / "daily.csv"
            daily.write_text(
                "local_date,row_count,max_temp_bucket_c\n2026-05-27,24,25\n",
                encoding="utf-8",
            )

            label = build_label(
                folder,
                daily_summary_path=daily,
                reconcile_polymarket=True,
                polymarket_event=_resolved_event("25 C"),
            )

        self.assertEqual(label["settlement_source"], "daily_summary")
        self.assertEqual(label["quality_grade"], "complete")
        self.assertEqual(label["material_coverage_grade"], "strict_complete")
        self.assertTrue(label["promotion_countable"])

    def test_minor_gap_partial_label_is_material_promotion_countable_when_reconciled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "highest-temperature-in-toronto-on-may-27-2026"
            folder.mkdir()
            _write_toronto_tape(folder, omitted_indexes={18})
            daily = root / "daily.csv"
            daily.write_text(
                "local_date,row_count,max_temp_bucket_c\n2026-05-27,24,25\n",
                encoding="utf-8",
            )

            label = build_label(
                folder,
                daily_summary_path=daily,
                reconcile_polymarket=True,
                polymarket_event=_resolved_event("25 C"),
            )

        self.assertEqual(label["quality_grade"], "partial")
        self.assertFalse(label["coverage_clean"])
        self.assertEqual(label["material_coverage_grade"], "minor_gap_material")
        self.assertIn("peak_heating_window:20m", label["material_coverage_gap_windows"])
        self.assertTrue(label["promotion_countable"])

    def test_decisive_peak_gap_partial_label_is_not_material_promotion_countable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "highest-temperature-in-toronto-on-may-27-2026"
            folder.mkdir()
            _write_toronto_tape(folder, omitted_indexes=set(range(19, 25)))
            daily = root / "daily.csv"
            daily.write_text(
                "local_date,row_count,max_temp_bucket_c\n2026-05-27,24,25\n",
                encoding="utf-8",
            )

            label = build_label(
                folder,
                daily_summary_path=daily,
                reconcile_polymarket=True,
                polymarket_event=_resolved_event("25 C"),
            )

        self.assertEqual(label["quality_grade"], "partial")
        self.assertEqual(label["material_coverage_grade"], "decisive_gap")
        self.assertEqual(label["material_coverage_decisive_gap_count"], 1)
        self.assertFalse(label["promotion_countable"])


if __name__ == "__main__":
    unittest.main()
