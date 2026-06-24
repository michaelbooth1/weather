import tempfile
import unittest
from pathlib import Path

from weather.operations.cleanup_preflight import (
    build_cleanup_preflight,
    cleanup_manifest_for_paths,
)
from weather.operations.tape_backup import backup_status, export_backup, run_restore_drill


def write(path: Path, text: str = "x\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def fixture_source(root: Path) -> None:
    write(root / "data/snapshots/event/snapshots.jsonl", "{}\n")
    write(root / "data/snapshots/event/features.jsonl", "{}\n")
    write(root / "data/snapshots/event/replay_inputs.jsonl", "{}\n")
    write(root / "data/snapshots/event/clob_tokens.csv", "token\n")
    write(root / "data/snapshots/event/order_books.jsonl", "{}\n")
    write(root / "data/snapshots/event/price_history.jsonl", "{}\n")
    write(root / "data/snapshots/event/market_ws.jsonl", "{}\n")
    write(root / "data/snapshots/observation_triggers.jsonl", "{}\n")
    write(root / "data/backtest/market_day_labels.csv", "event_slug,quality_grade\nx,complete\n")
    write(root / "data/backtest/promotion_corpus.json", "{}\n")
    write(root / "data/mm_runs/run-1/order_lifecycle.jsonl", "{}\n")
    write(root / "data/mm_runs/run-1/risk_events.jsonl", "{}\n")


def review() -> dict:
    return {
        "approved": True,
        "approved_by": "unit-test",
        "approved_at_utc": "2026-06-23T00:00:00+00:00",
        "note": "reviewed cleanup manifest for unit test",
    }


class CleanupPreflightTests(unittest.TestCase):
    def ok_backup_status(self, tmp: str) -> tuple[Path, dict]:
        root = Path(tmp) / "repo"
        backup_root = Path(tmp) / "backup"
        fixture_source(root)
        export_backup(root, backup_root, capacity_margin_bytes=0)
        run_restore_drill(
            backup_root=backup_root,
            restore_root=Path(tmp) / "restore",
            out=Path(tmp) / "restore.json",
            report=Path(tmp) / "restore.md",
            keep_restore=True,
        )
        status = backup_status(backup_root, source_root=root)
        self.assertEqual(status["status"], "OK")
        return root, status

    def canonical_manifest(self, root: Path, status: dict) -> dict:
        return cleanup_manifest_for_paths(
            [root / "data/snapshots/event/snapshots.jsonl"],
            root=root / "data",
            deletion_reason="delete canonical snapshot only after external archive proof",
            operator_review=review(),
            backup_status=status,
        )

    def test_canonical_cleanup_passes_with_fresh_backup_restore_and_manifest_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, status = self.ok_backup_status(tmp)
            manifest = self.canonical_manifest(root, status)

            preflight = build_cleanup_preflight(manifest, root=root / "data", backup_status=status)

        self.assertEqual(preflight["status"], "PASS")
        self.assertTrue(preflight["delete_permission"])

    def test_canonical_cleanup_blocks_stale_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, status = self.ok_backup_status(tmp)
            status["status"] = "STALE"
            manifest = self.canonical_manifest(root, status)

            preflight = build_cleanup_preflight(manifest, root=root / "data", backup_status=status)

        self.assertEqual(preflight["status"], "BLOCK")
        self.assertIn("backup_restore_status", {
            check["check"]
            for row in preflight["candidates"]
            for check in row["checks"]
            if check["status"] == "BLOCK"
        })

    def test_canonical_cleanup_blocks_stale_restore_drill(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, status = self.ok_backup_status(tmp)
            status["restore_drill_sla_status"] = "RESTORE_DRILL_STALE"
            manifest = self.canonical_manifest(root, status)

            preflight = build_cleanup_preflight(manifest, root=root / "data", backup_status=status)

        self.assertEqual(preflight["status"], "BLOCK")

    def test_missing_critical_files_is_hard_block_with_samples_for_canonical_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, status = self.ok_backup_status(tmp)
            status["status"] = "MISSING_CRITICAL_FILES"
            status["missing_critical_files"] = 1
            status["missing_critical_bytes"] = 12
            status["missing_critical_file_samples"] = [{"path": "data/snapshots/event/order_books_extra.jsonl"}]
            manifest = self.canonical_manifest(root, status)

            preflight = build_cleanup_preflight(manifest, root=root / "data", backup_status=status)

        self.assertEqual(preflight["status"], "BLOCK")
        top_blocks = [row for row in preflight["checks"] if row["status"] == "BLOCK"]
        self.assertEqual(top_blocks[0]["check"], "missing_critical_files")
        self.assertEqual(top_blocks[0]["missing_samples"][0]["path"], "data/snapshots/event/order_books_extra.jsonl")

    def test_canonical_cleanup_blocks_checksum_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, status = self.ok_backup_status(tmp)
            status["status"] = "CHECKSUM_FAIL"
            status["checksum_failures"] = [{"path": "data/snapshots/event/snapshots.jsonl"}]
            manifest = self.canonical_manifest(root, status)

            preflight = build_cleanup_preflight(manifest, root=root / "data", backup_status=status)

        self.assertEqual(preflight["status"], "BLOCK")

    def test_projection_only_cleanup_can_pass_without_backup_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            projection = write(data_root / "backtest" / "active_variant_shadow_long.csv", "a\n1\n")
            manifest = cleanup_manifest_for_paths(
                [projection],
                root=data_root,
                deletion_reason="delete rebuildable projection",
                operator_review=review(),
                backup_status={"status": "MISSING_CRITICAL_FILES", "missing_critical_files": 99},
            )

            preflight = build_cleanup_preflight(
                manifest,
                root=data_root,
                backup_status={"status": "MISSING_CRITICAL_FILES", "missing_critical_files": 99},
            )

        self.assertEqual(preflight["status"], "PASS")
        self.assertTrue(preflight["delete_permission"])


if __name__ == "__main__":
    unittest.main()
