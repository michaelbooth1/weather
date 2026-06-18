import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from weather.operations.tape_backup import (  # noqa: E402
    backup_status,
    build_backup_manifest,
    classify_path,
    export_backup,
    load_backup_manifest,
    run_backup_job,
    run_restore_drill,
    sha256_file,
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
    write(root / "data/snapshots/event/clob_tokens.jsonl", "{}\n")
    write(root / "data/snapshots/event/order_books_summary.csv", "capture_id,best_bid,best_ask\nb1,0.40,0.45\n")
    write(root / "data/snapshots/event/order_books_long.csv", "capture_id,side,level_index,price,size\nb1,bid,1,0.40,10\n")
    write(root / "data/snapshots/event/order_books.jsonl", "{}\n")
    write(root / "data/snapshots/event/price_history.csv", "clob_token_id,point_time_utc,price\n1,2026-06-18T00:00:00+00:00,0.40\n")
    write(root / "data/snapshots/event/price_history.jsonl", "{}\n")
    write(root / "data/snapshots/event/market_ws_events.csv", "received_at_utc,event_type,price\n2026-06-18T00:00:00+00:00,price_change,0.41\n")
    write(root / "data/snapshots/event/market_ws.jsonl", "{}\n")
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
        self.assertIn("data/snapshots/event/order_books_long.csv", paths)
        self.assertIn("data/snapshots/event/order_books.jsonl", paths)
        self.assertIn("data/snapshots/event/price_history.csv", paths)
        self.assertIn("data/snapshots/event/market_ws.jsonl", paths)
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
        self.assertGreaterEqual(manifest["class_summaries"]["clob_tapes"]["file_count"], 8)

    def test_market_microstructure_store_artifact_names_are_classified(self):
        names = [
            "clob_tokens.csv",
            "clob_tokens.jsonl",
            "order_books_summary.csv",
            "order_books_long.csv",
            "order_books.jsonl",
            "price_history.csv",
            "price_history.jsonl",
            "market_ws_events.csv",
            "market_ws.jsonl",
        ]

        for name in names:
            with self.subTest(name=name):
                self.assertIn("clob_tapes", classify_path(f"data/snapshots/event/{name}"))

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
            self.assertGreaterEqual(
                drill["clob_restore_evidence"]["summary"]["required_classes_restored"],
                6,
            )
            self.assertTrue(drill_report_exists)

    def test_backup_status_requires_restore_drill_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            backup_root = Path(tmp) / "backup"
            fixture_source(root)
            export_backup(root, backup_root)

            status = backup_status(backup_root)

        self.assertEqual(status["status"], "RESTORE_DRILL_MISSING")
        self.assertEqual(status["restore_drill_sla_status"], "RESTORE_DRILL_MISSING")

    def test_backup_status_detects_stale_restore_drill(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            backup_root = Path(tmp) / "backup"
            fixture_source(root)
            export_backup(root, backup_root)
            run_restore_drill(
                backup_root=backup_root,
                restore_root=Path(tmp) / "restore",
                out=Path(tmp) / "drill.json",
                report=Path(tmp) / "drill.md",
                keep_restore=True,
            )
            drill_path = backup_root / "latest" / "tape_restore_drill.json"
            drill = json.loads(drill_path.read_text(encoding="utf-8"))
            drill["generated_at_utc"] = "2026-01-01T00:00:00+00:00"
            drill_path.write_text(json.dumps(drill), encoding="utf-8")

            status = backup_status(backup_root, max_restore_age_hours=1)

        self.assertEqual(status["status"], "RESTORE_DRILL_STALE")

    def test_backup_status_detects_missing_critical_class_even_with_restore_drill(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            backup_root = Path(tmp) / "backup"
            write(root / "data/snapshots/event/snapshots.jsonl", "{}\n")
            export_backup(root, backup_root)
            run_restore_drill(
                backup_root=backup_root,
                restore_root=Path(tmp) / "restore",
                out=Path(tmp) / "drill.json",
                report=Path(tmp) / "drill.md",
                keep_restore=True,
            )

            status = backup_status(backup_root)

        self.assertEqual(status["status"], "MISSING_CRITICAL_CLASS")
        self.assertIn("clob_tapes", status["missing_critical_classes"])

    def test_backup_status_detects_local_critical_files_missing_from_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            backup_root = Path(tmp) / "backup"
            fixture_source(root)
            export_backup(root, backup_root)
            run_restore_drill(
                backup_root=backup_root,
                restore_root=Path(tmp) / "restore",
                out=Path(tmp) / "drill.json",
                report=Path(tmp) / "drill.md",
                keep_restore=True,
            )
            write(
                root / "data/snapshots/event/order_books_long_extra.csv",
                "capture_id,side,level_index,price,size\nb2,ask,1,0.46,10\n",
            )

            status = backup_status(backup_root)

        self.assertEqual(status["status"], "MISSING_CRITICAL_FILES")
        self.assertEqual(status["missing_critical_files"], 1)
        self.assertIn("order_books_long_extra.csv", status["missing_critical_file_samples"][0]["path"])

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

    def test_export_manifest_hashes_backed_up_bytes_when_source_changes_during_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            backup_root = Path(tmp) / "backup"
            fixture_source(root)
            real_copy2 = __import__("shutil").copy2

            def mutating_copy(src, dst, *args, **kwargs):
                result = real_copy2(src, dst, *args, **kwargs)
                if str(src).endswith("snapshots.jsonl"):
                    Path(dst).write_text("mutated backup bytes\n", encoding="utf-8")
                return result

            with patch("weather.operations.tape_backup.shutil.copy2", mutating_copy):
                manifest = export_backup(root, backup_root)

            backed_up = backup_root / "latest" / "data/snapshots/event/snapshots.jsonl"
            entry = next(row for row in manifest["files"] if row["path"] == "data/snapshots/event/snapshots.jsonl")
            backed_up_hash = sha256_file(backed_up)

        self.assertEqual(entry["sha256"], backed_up_hash)

    def test_run_backup_job_exports_restores_and_writes_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            backup_root = Path(tmp) / "backup"
            fixture_source(root)

            payload = run_backup_job(
                source_root=root,
                backup_root=backup_root,
                status_out=Path(tmp) / "status.json",
                status_report=Path(tmp) / "status.md",
                restore_out=Path(tmp) / "restore.json",
                restore_report=Path(tmp) / "restore.md",
                restore_root=Path(tmp) / "restore",
                keep_restore=True,
                verify_checksums=True,
            )
            status_exists = (Path(tmp) / "status.json").exists()
            status_report = (Path(tmp) / "status.md").read_text(encoding="utf-8")

        self.assertEqual(payload["status"]["status"], "OK")
        self.assertEqual(payload["restore_drill"]["status"], "PASS")
        self.assertTrue(status_exists)
        self.assertIn("Restore drill SLA: **OK**", status_report)
        self.assertIn("## CLOB Artifact Coverage", status_report)
        self.assertIn("order_book_long", status_report)


if __name__ == "__main__":
    unittest.main()
