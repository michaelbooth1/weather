import tempfile
import unittest
from collections import namedtuple
from pathlib import Path
from unittest.mock import patch

from weather.operations.storage_classes import ANALYSIS_PROJECTION, CANONICAL_EVIDENCE, OPERATOR_CACHE
from weather.reporting.data_quality.data_retention_inventory import build_payload, render_report


class TestDataRetentionInventory(unittest.TestCase):
    def test_classifies_data_owners_and_marks_review_required_classes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = root / "snapshots" / "market-day" / "snapshots_long.csv"
            snapshot.parent.mkdir(parents=True)
            snapshot.write_text("x" * 32, encoding="utf-8")
            cache = root / "cache" / "provider.json"
            cache.parent.mkdir()
            cache.write_text("{}", encoding="utf-8")

            payload = build_payload(
                root,
                min_free_bytes=0,
                lookback_hours=48,
                top_n=5,
            )

        by_policy = {row["policy"]: row for row in payload["policy_summaries"]}
        by_storage_class = {row["storage_class"]: row for row in payload["storage_class_summaries"]}
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(by_policy["snapshots"]["owner"], "collection/model/market")
        self.assertEqual(by_policy["snapshots"]["delete_gate"]["status"], "REVIEW_REQUIRED")
        self.assertIn(ANALYSIS_PROJECTION, by_storage_class)
        self.assertIn(OPERATOR_CACHE, by_storage_class)
        self.assertEqual(by_storage_class[ANALYSIS_PROJECTION]["delete_gate"]["status"], "REVIEW_REQUIRED")
        self.assertIn("snapshot_csv_long_tables", by_storage_class[ANALYSIS_PROJECTION]["artifact_families"])
        self.assertEqual(
            by_policy["snapshots"]["delete_gate"]["delete_permission"],
            "allowed_only_with_reviewed_manifest",
        )
        self.assertEqual(by_policy["provider_caches"]["delete_gate"]["status"], "NOT_REQUIRED")

    def test_canonical_evidence_delete_gate_requires_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mm = root / "mm_runs" / "run1" / "order_lifecycle.jsonl"
            mm.parent.mkdir(parents=True)
            mm.write_text("{}\n", encoding="utf-8")

            payload = build_payload(root, min_free_bytes=0)
            report = render_report(payload)

        by_policy = {row["policy"]: row for row in payload["policy_summaries"]}
        by_storage_class = {row["storage_class"]: row for row in payload["storage_class_summaries"]}
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(by_policy["mm_runs"]["delete_gate"]["status"], "REVIEW_REQUIRED")
        self.assertEqual(by_storage_class[CANONICAL_EVIDENCE]["delete_gate"]["status"], "REVIEW_REQUIRED")
        self.assertIn("Ownership And Retention", report)
        self.assertIn("Storage Class Summary", report)
        self.assertIn("Operator Procedure", report)

    def test_reports_largest_and_recent_growth(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = root / "backtest" / "old_report.md"
            old.parent.mkdir(parents=True)
            old.write_text("old", encoding="utf-8")
            large = root / "backtest" / "active_variant_shadow_long.csv"
            large.write_text("x" * 64, encoding="utf-8")

            payload = build_payload(root, min_free_bytes=0, lookback_hours=24, top_n=3)

        self.assertEqual(payload["largest_files"][0]["path"], "backtest/active_variant_shadow_long.csv")
        recent_dirs = {row["path"]: row for row in payload["recent_directories"]}
        self.assertIn("backtest", recent_dirs)
        self.assertGreaterEqual(recent_dirs["backtest"]["bytes"], 64)

    def test_blocks_when_recent_write_rate_exhausts_growth_headroom(self):
        disk_usage = namedtuple("disk_usage", "total used free")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recent = root / "backtest" / "large.csv"
            recent.parent.mkdir(parents=True)
            recent.write_text("x" * 200, encoding="utf-8")

            with patch(
                "weather.reporting.data_quality.data_retention_inventory.shutil.disk_usage",
                return_value=disk_usage(total=10_000, used=9_000, free=1_000),
            ):
                payload = build_payload(
                    root,
                    min_free_bytes=0,
                    min_growth_headroom_days=10,
                    lookback_hours=24,
                )

        self.assertEqual(payload["status"], "BLOCK")
        self.assertAlmostEqual(payload["disk"]["growth_headroom_days"], 5.0)
        self.assertAlmostEqual(payload["disk"]["growth_headroom_shortfall_days"], 5.0)
        self.assertIn("Growth headroom", render_report(payload))


if __name__ == "__main__":
    unittest.main()
