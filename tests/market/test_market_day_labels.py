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
from unittest import mock

from weather.backtesting import settlement_ledger
from weather.backtesting.settlement_ledger import FolderFinalizationError, build_label
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

    def _partial_failure_fixture(self, root):
        """Two folders; the first one finalized will raise, the second succeed."""
        good = root / "highest-temperature-in-toronto-on-may-27-2026"
        good.mkdir()
        _write_toronto_tape(good)
        bad = root / "highest-temperature-in-nyc-on-may-27-2026"
        bad.mkdir()
        _write_toronto_tape(bad)
        daily = root / "daily.csv"
        daily.write_text(
            "local_date,row_count,max_temp_bucket_c\n2026-05-27,24,25\n",
            encoding="utf-8",
        )
        return good, bad, daily

    def test_one_failing_folder_does_not_discard_the_others(self):
        """A transient ledger error on one market must not cost the whole day.

        On 2026-08-11 a single `[Errno 13] Permission denied` aborted the loop
        before write_labels_csv and all 12 markets lost their 2026-08-10 rows.
        """

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            good, bad, daily = self._partial_failure_fixture(root)
            labels_csv = root / "labels.csv"
            ledger_root = root / "settlements"
            real = settlement_ledger.finalize_folder

            def flaky(folder, **kwargs):
                if Path(folder).name.startswith("highest-temperature-in-nyc"):
                    raise PermissionError(
                        13, "Permission denied", str(ledger_root / "nyc" / "ledger.jsonl")
                    )
                return real(folder, **kwargs)

            with mock.patch.object(settlement_ledger, "finalize_folder", side_effect=flaky):
                with self.assertRaises(FolderFinalizationError) as ctx:
                    finalize_folders(
                        [bad, good],
                        daily_summary_path=daily,
                        labels_csv=labels_csv,
                        ledger_root=ledger_root,
                        folder_attempts=1,
                    )

            # The failure is reported, not swallowed...
            self.assertEqual(len(ctx.exception.failures), 1)
            self.assertIn("PermissionError", ctx.exception.failures[0][1])
            # ...and the market that succeeded was still persisted.
            csv_rows = list(csv.DictReader(labels_csv.open(encoding="utf-8", newline="")))
            self.assertEqual([row["event_slug"] for row in csv_rows], [good.name])
            self.assertEqual([label["event_slug"] for label in ctx.exception.labels], [good.name])

    def test_partial_run_merges_instead_of_truncating_the_labels_csv(self):
        """A partial re-finalize must not delete rows it did not regenerate."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            good, bad, daily = self._partial_failure_fixture(root)
            labels_csv = root / "labels.csv"
            ledger_root = root / "settlements"
            settlement_ledger.write_labels_csv(
                labels_csv,
                [{"event_slug": "highest-temperature-in-denver-on-may-01-2026",
                  "market_id": "denver", "target_date": "2026-05-01"}],
            )
            real = settlement_ledger.finalize_folder

            def flaky(folder, **kwargs):
                if Path(folder).name.startswith("highest-temperature-in-nyc"):
                    raise PermissionError(13, "Permission denied", "ledger.jsonl")
                return real(folder, **kwargs)

            with mock.patch.object(settlement_ledger, "finalize_folder", side_effect=flaky):
                with self.assertRaises(FolderFinalizationError):
                    finalize_folders(
                        [bad, good],
                        daily_summary_path=daily,
                        labels_csv=labels_csv,
                        ledger_root=ledger_root,
                        folder_attempts=1,
                    )

            slugs = {
                row["event_slug"]
                for row in csv.DictReader(labels_csv.open(encoding="utf-8", newline=""))
            }
            self.assertIn("highest-temperature-in-denver-on-may-01-2026", slugs)
            self.assertIn(good.name, slugs)

    def test_transient_folder_error_is_retried_before_failing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            good, _bad, daily = self._partial_failure_fixture(root)
            labels_csv = root / "labels.csv"
            ledger_root = root / "settlements"
            real = settlement_ledger.finalize_folder
            calls = {"n": 0}

            def flaky_once(folder, **kwargs):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise PermissionError(13, "Permission denied", "ledger.jsonl")
                return real(folder, **kwargs)

            with mock.patch.object(settlement_ledger, "finalize_folder", side_effect=flaky_once):
                labels = finalize_folders(
                    [good],
                    daily_summary_path=daily,
                    labels_csv=labels_csv,
                    ledger_root=ledger_root,
                )

            self.assertEqual(calls["n"], 2)
            self.assertEqual([label["event_slug"] for label in labels], [good.name])

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
