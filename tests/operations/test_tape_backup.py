import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath("src"))

from tape_backup import (  # noqa: E402
    backup_status,
    build_backup_manifest,
    export_backup,
    load_backup_manifest,
    run_restore_drill,
)


def write(path, text="x\n"):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def fixture_source(root):
    write(root / "data/snapshots/event/snapshots.jsonl", "{}\n")
    write(root / "data/snapshots/event/features.jsonl", "{}\n")
    write(root / "data/snapshots/event/replay_inputs.jsonl", "{}\n")
    write(root / "data/snapshots/event/clob_features.jsonl", "{}\n")
    write(root / "data/snapshots/event/clob_tokens.csv", "token\n")
    write(root / "data/snapshots/observation_triggers.jsonl", "{}\n")
    write(root / "data/backtest/market_day_labels.csv", "event_slug,quality_grade\nx,complete\n")
    write(
        root / "data/backtest/promotion_corpus.json",
        json.dumps({"schema_version": "promotion_corpus_v0.1", "entries": [], "corpus_hash": ""}),
    )
    write(root / "data/backtest/f_family_promotion_refresh.json", "{}\n")
    write(root / "data/mm_runs/run-1/quote_tape.jsonl", "{}\n")
    write(root / "data/mm_runs/run-1/order_lifecycle.jsonl", "{}\n")
    write(root / "data/mm_runs/run-1/risk_events.jsonl", "{}\n")
    write(root / "artifacts/models/demo.json", json.dumps({"schema_version": "feature_model_coefs_v0.1"}))
    write(root / "data/wunderground/cyyz/manifest.json", json.dumps({"schema_version": "historical_source_manifest_v1"}))
    write(root / "data/backtest/backtest_report.md", "derived report should not be backed up\n")


class TestTapeBackup(unittest.TestCase):
    def test_manifest_classifies_irreplaceable_tapes_and_excludes_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture_source(root)

            manifest = build_backup_manifest(root)

        self.assertEqual(manifest["schema_version"], "tape_backup_manifest_v0.1")
        self.assertEqual(manifest["summary"]["missing_critical_classes"], [])
        paths = {row["path"] for row in manifest["files"]}
        self.assertIn("data/snapshots/event/snapshots.jsonl", paths)
        self.assertIn("data/mm_runs/run-1/order_lifecycle.jsonl", paths)
        self.assertNotIn("data/backtest/backtest_report.md", paths)
        classes = {
            class_name
            for row in manifest["files"]
            for class_name in row["classes"]
        }
        self.assertIn("snapshot_tapes", classes)
        self.assertIn("clob_tapes", classes)
        self.assertIn("order_lifecycle_and_risk", classes)

    def test_export_backup_writes_manifest_and_restore_drill_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            backup_root = Path(tmp) / "backup"
            fixture_source(root)

            export_manifest = export_backup(root, backup_root)
            loaded, manifest_path = load_backup_manifest(backup_root)
            drill = run_restore_drill(
                backup_root=backup_root,
                restore_root=Path(tmp) / "restore",
                out=Path(tmp) / "drill.json",
                report=Path(tmp) / "drill.md",
                keep_restore=True,
            )
            drill_report_exists = (Path(tmp) / "drill.md").exists()

            self.assertTrue(manifest_path.exists())
            self.assertEqual(loaded["manifest_hash"], export_manifest["manifest_hash"])
            self.assertEqual(drill["status"], "PASS")
            self.assertEqual(drill["files_restored"], export_manifest["summary"]["file_count"])
            self.assertTrue(drill_report_exists)

    def test_backup_status_detects_checksum_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            backup_root = Path(tmp) / "backup"
            fixture_source(root)
            export_backup(root, backup_root)
            backed_up = backup_root / "latest" / "data/snapshots/event/snapshots.jsonl"
            backed_up.write_text("corrupt\n", encoding="utf-8")

            status = backup_status(backup_root, verify_checksums=True)

        self.assertEqual(status["status"], "CHECKSUM_FAIL")
        self.assertEqual(status["checksum_failures"][0]["reason"], "sha256_mismatch")


if __name__ == "__main__":
    unittest.main()
