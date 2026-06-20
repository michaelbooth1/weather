import json
import tempfile
import unittest
from pathlib import Path

from weather.reporting.data_retention_inventory import build_payload, render_report


class TestDataRetentionInventory(unittest.TestCase):
    def test_classifies_data_owners_and_blocks_restore_required_deletion_without_backup(self):
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
                backup_status_path=root / "backtest" / "missing_backup_status.json",
                min_free_bytes=0,
                lookback_hours=48,
                top_n=5,
            )

        by_policy = {row["policy"]: row for row in payload["policy_summaries"]}
        self.assertEqual(payload["status"], "WARN")
        self.assertEqual(by_policy["snapshots"]["owner"], "collection/model/market")
        self.assertEqual(by_policy["snapshots"]["restore_gate"]["status"], "BLOCK")
        self.assertEqual(
            by_policy["snapshots"]["restore_gate"]["delete_permission"],
            "blocked_until_restore_proof",
        )
        self.assertEqual(by_policy["provider_caches"]["restore_gate"]["status"], "NOT_REQUIRED")

    def test_restore_ok_allows_reviewed_manifest_for_irreplaceable_classes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mm = root / "mm_runs" / "run1" / "order_lifecycle.jsonl"
            mm.parent.mkdir(parents=True)
            mm.write_text("{}\n", encoding="utf-8")
            status = root / "backtest" / "tape_backup_status.json"
            status.parent.mkdir()
            status.write_text(json.dumps({
                "status": "OK",
                "restore_drill_sla_status": "OK",
                "missing_critical_files": 0,
                "missing_critical_bytes": 0,
            }), encoding="utf-8")

            payload = build_payload(root, backup_status_path=status, min_free_bytes=0)
            report = render_report(payload)

        by_policy = {row["policy"]: row for row in payload["policy_summaries"]}
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(by_policy["mm_runs"]["restore_gate"]["status"], "PASS")
        self.assertIn("Ownership And Retention", report)
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


if __name__ == "__main__":
    unittest.main()
