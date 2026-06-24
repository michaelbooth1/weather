import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import pyarrow as pa
import pyarrow.parquet as pq
from weather.operations.storage_classes import ANALYSIS_PROJECTION, CANONICAL_EVIDENCE
from weather.operations.tape_backup import (  # noqa: E402
    DEDUP_REPOSITORY_SCHEMA_VERSION,
    TapeBackupCapacityError,
    apply_unmanifested_backup_cleanup,
    backup_status,
    build_backup_manifest,
    classify_path,
    dedup_repository_preflight,
    dedup_repository_status,
    default_dedup_manifest_path,
    export_backup,
    load_backup_manifest,
    run_dedup_backup,
    run_dedup_restore_drill,
    run_backup_job,
    run_restore_drill,
    select_dedup_restore_drill_paths,
    sha256_file,
    unmanifested_backup_cleanup_plan,
    write_json,
)


DiskUsage = namedtuple("DiskUsage", "total used free")


def write(path, text="x\n"):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def manifest_time(manifest):
    value = manifest.get("coverage_cutoff_utc") or manifest["generated_at_utc"]
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def set_mtime(path, when):
    ts = when.timestamp()
    os.utime(path, (ts, ts))


def write_closed_day_parquet_fixture(root):
    partition = (
        root
        / "data/archive/closed_market_days/v0.1"
        / "local_date=2026-06-18"
        / "market_id=demo"
        / "event_slug=highest-temperature-in-demo-on-june-18-2026"
    )
    parquet_path = partition / "artifact_family=order_books_long" / "data.parquet"
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table({
            "capture_id": ["b1", "b2"],
            "side": ["bid", "ask"],
            "price": [0.40, 0.45],
        }),
        parquet_path,
    )
    write(
        partition / "closed_market_day_archive_manifest.json",
        json.dumps({
            "schema_version": "closed_market_day_archive_manifest_v0.1",
            "archive_root_version": "v0.1",
            "generated_at_utc": "2026-06-18T00:00:00+00:00",
            "writer": "unit-test",
            "writer_version": "unit-test",
            "source_folder": "data/snapshots/event",
            "manifest_hash": "unit-test-manifest-hash",
            "partition": {
                "local_date": "2026-06-18",
                "market_id": "demo",
                "event_slug": "highest-temperature-in-demo-on-june-18-2026",
            },
            "finalization": {
                "state": "settled_countable",
                "quality_grade": "complete",
                "countable": True,
            },
            "validation": {"status": "PASS", "checks": []},
            "artifact_families": [
                {
                    "artifact_family": "order_books_long",
                    "status": "parquet",
                    "source_files": [
                        {
                            "path": "data/snapshots/event/order_books_long.csv",
                            "bytes": 1,
                            "sha256": "source-sha",
                            "role": "analysis_source",
                        }
                    ],
                    "parquet": {
                        "path": "artifact_family=order_books_long/data.parquet",
                        "bytes": parquet_path.stat().st_size,
                        "sha256": sha256_file(parquet_path),
                        "row_count": 2,
                        "codec": "zstd",
                        "schema_fingerprint": "unit-test",
                    },
                }
            ],
        }),
    )
    return parquet_path


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
    write_closed_day_parquet_fixture(root)
    write(root / "data/backtest/backtest_report.md", "derived report should not be backed up\n")


def operator_review():
    return {
        "approved": True,
        "approved_by": "unit-test",
        "approved_at_utc": "2026-06-23T00:00:00+00:00",
        "note": "reviewed prune-unmanifested dry-run report for unit test",
    }


class TestTapeBackup(unittest.TestCase):
    def test_manifest_classifies_irreplaceable_tapes_and_excludes_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture_source(root)

            manifest = build_backup_manifest(root)

        self.assertEqual(manifest["schema_version"], "tape_backup_manifest_v0.1")
        self.assertEqual(manifest["summary"]["missing_critical_classes"], [])
        paths = {row["path"] for row in manifest["files"]}
        by_path = {row["path"]: row for row in manifest["files"]}
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
        self.assertEqual(by_path["data/snapshots/event/snapshots.jsonl"]["storage_class"], CANONICAL_EVIDENCE)
        self.assertEqual(by_path["data/snapshots/event/order_books_long.csv"]["storage_class"], ANALYSIS_PROJECTION)
        self.assertNotIn("unclassified", {
            row["artifact_family"] for row in manifest["files"]
        })
        self.assertGreater(manifest["storage_class_summaries"][CANONICAL_EVIDENCE]["file_count"], 0)
        self.assertGreater(manifest["storage_class_summaries"][ANALYSIS_PROJECTION]["file_count"], 0)

    def test_manifest_includes_closed_market_day_parquet_archives(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parquet_path = write_closed_day_parquet_fixture(root)

            manifest = build_backup_manifest(root)

        paths = {row["path"] for row in manifest["files"]}
        self.assertIn(parquet_path.relative_to(root).as_posix(), paths)
        self.assertIn(
            "data/archive/closed_market_days/v0.1/local_date=2026-06-18/"
            "market_id=demo/event_slug=highest-temperature-in-demo-on-june-18-2026/"
            "closed_market_day_archive_manifest.json",
            paths,
        )
        self.assertGreater(
            manifest["class_summaries"]["closed_market_day_parquet_archives"]["file_count"],
            0,
        )

    def test_dedup_repository_preflight_fails_closed_without_config_or_binary(self):
        preflight, _ = dedup_repository_preflight(env={"PATH": "", "RESTIC_PASSWORD": "secret-value"})

        self.assertEqual(preflight["status"], "CONFIGURATION_INCOMPLETE")
        self.assertIn("RESTIC_PASSWORD", preflight["credential_sources"])
        self.assertNotIn("secret-value", json.dumps(preflight))
        self.assertIn("repository", {row["check"] for row in preflight["failures"]})
        self.assertIn("restic_binary", {row["check"] for row in preflight["failures"]})

    def test_dedup_backup_writes_restic_file_list_and_control_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            fixture_source(root)
            env = {"PATH": "fake", "RESTIC_REPOSITORY": str(Path(tmp) / "repo"), "RESTIC_PASSWORD": "secret"}
            captured_file_list = {}

            def fake_run(command, **kwargs):
                if command[1] == "snapshots":
                    return subprocess.CompletedProcess(command, 0, stdout="[]", stderr="")
                if command[1] == "backup":
                    files_from = Path(command[command.index("--files-from") + 1])
                    captured_file_list["paths"] = files_from.read_text(encoding="utf-8").splitlines()
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout=json.dumps({"message_type": "summary", "snapshot_id": "snap123"}) + "\n",
                        stderr="",
                    )
                raise AssertionError(command)

            with patch("weather.operations.tape_backup.shutil.which", return_value="restic"), patch(
                "weather.operations.tape_backup.subprocess.run",
                side_effect=fake_run,
            ):
                payload = run_dedup_backup(
                    source_root=root,
                    out=Path(tmp) / "backup.json",
                    report=Path(tmp) / "backup.md",
                    env=env,
                )
                control_manifest_exists = default_dedup_manifest_path(root).exists()

        self.assertEqual(payload["schema_version"], DEDUP_REPOSITORY_SCHEMA_VERSION)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["snapshot_id"], "snap123")
        self.assertTrue(control_manifest_exists)
        self.assertIn("data/backtest/tape_dedup_repository_manifest.json", captured_file_list["paths"])
        self.assertIn("data/snapshots/event/order_books.jsonl", captured_file_list["paths"])
        self.assertTrue(any(path.endswith("data.parquet") for path in captured_file_list["paths"]))

    def test_dedup_status_requires_restore_drill_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"PATH": "fake", "RESTIC_REPOSITORY": str(Path(tmp) / "repo"), "RESTIC_PASSWORD": "secret"}
            now = datetime.now(timezone.utc).isoformat()

            def fake_run(command, **kwargs):
                self.assertEqual(command[1], "snapshots")
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps([{"id": "snap123", "time": now, "tags": ["weather-tape"]}]),
                    stderr="",
                )

            with patch("weather.operations.tape_backup.shutil.which", return_value="restic"), patch(
                "weather.operations.tape_backup.subprocess.run",
                side_effect=fake_run,
            ):
                payload = dedup_repository_status(
                    restore_drill_path=Path(tmp) / "missing-restore.json",
                    env=env,
                )

        self.assertEqual(payload["status"], "RESTORE_DRILL_MISSING")
        self.assertEqual(payload["restore_drill_sla_status"], "RESTORE_DRILL_MISSING")

    def test_dedup_restore_drill_verifies_raw_parquet_manifest_and_replay_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            restore_root = Path(tmp) / "restore"
            fixture_source(root)
            manifest = build_backup_manifest(root)
            control_manifest = default_dedup_manifest_path(root)
            write_json(control_manifest, manifest)
            env = {"PATH": "fake", "RESTIC_REPOSITORY": str(Path(tmp) / "repo"), "RESTIC_PASSWORD": "secret"}
            now = datetime.now(timezone.utc).isoformat()

            def fake_run(command, **kwargs):
                if command[1] == "snapshots":
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout=json.dumps([{"id": "snap123", "time": now, "tags": ["weather-tape"]}]),
                        stderr="",
                    )
                if command[1] == "restore":
                    target = Path(command[command.index("--target") + 1])
                    includes = [
                        command[index + 1]
                        for index, value in enumerate(command)
                        if value == "--include"
                    ]
                    for rel in includes:
                        src = root / rel
                        if src.exists():
                            dst = target / rel
                            dst.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(src, dst)
                    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
                raise AssertionError(command)

            with patch("weather.operations.tape_backup.shutil.which", return_value="restic"), patch(
                "weather.operations.tape_backup.subprocess.run",
                side_effect=fake_run,
            ):
                payload = run_dedup_restore_drill(
                    restore_root=restore_root,
                    keep_restore=True,
                    out=Path(tmp) / "restore.json",
                    report=Path(tmp) / "restore.md",
                    env=env,
                )

        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["snapshot_id"], "snap123")
        self.assertEqual(payload["drill_selection"]["missing_categories"], [])
        self.assertGreaterEqual(payload["verified_files"], 4)
        self.assertEqual(payload["parquet_failures"], [])
        self.assertEqual(payload["parquet_checks"][0]["row_count"], 2)
        self.assertEqual(payload["parquet_checks"][0]["expected_row_count"], 2)

    def test_dedup_restore_drill_selection_requires_expected_evidence_classes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture_source(root)
            manifest = build_backup_manifest(root)

            selection = select_dedup_restore_drill_paths(
                manifest,
                control_manifest_rel_path="data/backtest/tape_dedup_repository_manifest.json",
            )

        self.assertEqual(selection["missing_categories"], [])
        self.assertIn("data/snapshots/event/order_books.jsonl", selection["paths"])
        self.assertTrue(any(path.startswith("artifacts/") for path in selection["paths"]))
        self.assertTrue(any(path.endswith("data.parquet") for path in selection["paths"]))

    def test_market_microstructure_store_artifact_names_are_classified(self):
        names = [
            "clob_tokens.csv",
            "clob_tokens.jsonl",
            "order_books_summary.csv",
            "order_books_long.csv",
            "order_books_long.csv.gz",
            "order_books.jsonl",
            "price_history.csv",
            "price_history.jsonl",
            "market_ws_events.csv",
            "market_ws.jsonl",
        ]

        for name in names:
            with self.subTest(name=name):
                self.assertIn("clob_tapes", classify_path(f"data/snapshots/event/{name}"))

    def test_manifest_retains_lifecycle_manifest_and_skips_zero_byte_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            backup_root = Path(tmp) / "backup"
            fixture_source(root)
            write(
                root / "data/backtest/f_family_promotion_refresh_incomplete.json",
                json.dumps({
                    "schema_version": "promotion_refresh_incomplete_v0.1",
                    "status": "INCOMPLETE",
                }),
            )
            write(root / "data/mm_runs/run-1/preflight.json", "")
            write(root / "data/mm_runs/run-1/order_lifecycle_empty.jsonl", "")

            manifest = export_backup(root, backup_root, capacity_margin_bytes=0)
            drill = run_restore_drill(
                backup_root=backup_root,
                restore_root=Path(tmp) / "restore",
                out=Path(tmp) / "drill.json",
                report=Path(tmp) / "drill.md",
                keep_restore=True,
            )

        paths = {row["path"] for row in manifest["files"]}
        self.assertIn("data/backtest/f_family_promotion_refresh_incomplete.json", paths)
        self.assertNotIn("data/mm_runs/run-1/preflight.json", paths)
        self.assertNotIn("data/mm_runs/run-1/order_lifecycle_empty.jsonl", paths)
        self.assertEqual(drill["status"], "PASS")

    def test_export_backup_writes_manifest_and_restore_drill_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            backup_root = Path(tmp) / "backup"
            fixture_source(root)

            export_manifest = export_backup(root, backup_root, capacity_margin_bytes=0)
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
            export_backup(root, backup_root, capacity_margin_bytes=0)

            status = backup_status(backup_root)

        self.assertEqual(status["status"], "RESTORE_DRILL_MISSING")
        self.assertEqual(status["restore_drill_sla_status"], "RESTORE_DRILL_MISSING")

    def test_backup_status_detects_stale_restore_drill(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            backup_root = Path(tmp) / "backup"
            fixture_source(root)
            export_backup(root, backup_root, capacity_margin_bytes=0)
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
            export_backup(root, backup_root, capacity_margin_bytes=0)
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
            manifest = export_backup(root, backup_root, capacity_margin_bytes=0)
            run_restore_drill(
                backup_root=backup_root,
                restore_root=Path(tmp) / "restore",
                out=Path(tmp) / "drill.json",
                report=Path(tmp) / "drill.md",
                keep_restore=True,
            )
            missing_path = write(
                root / "data/snapshots/event/order_books_long_extra.csv",
                "capture_id,side,level_index,price,size\nb2,ask,1,0.46,10\n",
            )
            set_mtime(missing_path, manifest_time(manifest) - timedelta(seconds=1))

            with patch(
                "weather.operations.tape_backup.shutil.disk_usage",
                return_value=DiskUsage(total=10_000, used=1_000, free=9_000_000_000),
            ):
                status = backup_status(backup_root)

        self.assertEqual(status["status"], "MISSING_CRITICAL_FILES")
        self.assertEqual(status["missing_critical_files"], 1)
        self.assertIn("order_books_long_extra.csv", status["missing_critical_file_samples"][0]["path"])
        self.assertEqual(status["capacity_preflight"]["status"], "PASS")

    def test_backup_status_reports_insufficient_capacity_for_missing_critical_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            backup_root = Path(tmp) / "backup"
            fixture_source(root)
            manifest = export_backup(root, backup_root, capacity_margin_bytes=0)
            run_restore_drill(
                backup_root=backup_root,
                restore_root=Path(tmp) / "restore",
                out=Path(tmp) / "drill.json",
                report=Path(tmp) / "drill.md",
                keep_restore=True,
            )
            missing_path = write(
                root / "data/snapshots/event/order_books_long_extra.csv",
                "capture_id,side,level_index,price,size\nb2,ask,1,0.46,10\n",
            )
            set_mtime(missing_path, manifest_time(manifest) - timedelta(seconds=1))

            with patch(
                "weather.operations.tape_backup.shutil.disk_usage",
                return_value=DiskUsage(total=10_000, used=9_999, free=1),
            ):
                status = backup_status(backup_root)

        self.assertEqual(status["status"], "INSUFFICIENT_BACKUP_CAPACITY")
        self.assertGreater(status["capacity_preflight"]["insufficient_bytes"], 0)

    def test_backup_status_tracks_post_manifest_critical_files_without_failing_current_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            backup_root = Path(tmp) / "backup"
            fixture_source(root)
            manifest = export_backup(root, backup_root, capacity_margin_bytes=0)
            run_restore_drill(
                backup_root=backup_root,
                restore_root=Path(tmp) / "restore",
                out=Path(tmp) / "drill.json",
                report=Path(tmp) / "drill.md",
                keep_restore=True,
            )
            post_manifest_path = write(
                root / "data/snapshots/event/order_books_long_after_manifest.csv",
                "capture_id,side,level_index,price,size\nb3,bid,1,0.44,12\n",
            )
            set_mtime(post_manifest_path, manifest_time(manifest) + timedelta(seconds=1))

            with patch(
                "weather.operations.tape_backup.shutil.disk_usage",
                return_value=DiskUsage(total=10_000, used=1_000, free=9_000_000_000),
            ):
                status = backup_status(backup_root)

        coverage = status["local_manifest_coverage"]
        self.assertEqual(status["status"], "OK")
        self.assertEqual(status["missing_critical_files"], 0)
        self.assertEqual(coverage["post_manifest_critical_files"], 1)
        self.assertIn(
            "order_books_long_after_manifest.csv",
            coverage["post_manifest_critical_samples"][0]["path"],
        )

    def test_export_backup_capacity_preflight_prevents_partial_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            backup_root = Path(tmp) / "backup"
            fixture_source(root)

            with patch(
                "weather.operations.tape_backup.shutil.disk_usage",
                return_value=DiskUsage(total=10_000, used=9_999, free=1),
            ), patch("weather.operations.tape_backup.shutil.copy2") as copy2:
                with self.assertRaises(TapeBackupCapacityError) as raised:
                    export_backup(root, backup_root, capacity_margin_bytes=0)

        self.assertEqual(raised.exception.preflight["status"], "INSUFFICIENT_BACKUP_CAPACITY")
        self.assertEqual(copy2.call_count, 0)
        self.assertFalse((backup_root / "latest" / "tape_backup_manifest.json").exists())

    def test_run_backup_job_writes_status_when_capacity_preflight_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            backup_root = Path(tmp) / "backup"
            fixture_source(root)
            status_out = Path(tmp) / "status.json"

            with patch(
                "weather.operations.tape_backup.shutil.disk_usage",
                return_value=DiskUsage(total=10_000, used=9_999, free=1),
            ):
                payload = run_backup_job(
                    source_root=root,
                    backup_root=backup_root,
                    status_out=status_out,
                    status_report=Path(tmp) / "status.md",
                    restore_out=Path(tmp) / "restore.json",
                    restore_report=Path(tmp) / "restore.md",
                    restore_root=Path(tmp) / "restore",
                    capacity_margin_bytes=0,
                )
            written = json.loads(status_out.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"]["status"], "INSUFFICIENT_BACKUP_CAPACITY")
        self.assertEqual(payload["restore_drill"]["status"], "SKIPPED")
        self.assertEqual(written["status"], "INSUFFICIENT_BACKUP_CAPACITY")

    def test_backup_status_detects_checksum_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            backup_root = Path(tmp) / "backup"
            fixture_source(root)
            export_backup(root, backup_root, capacity_margin_bytes=0)
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
                manifest = export_backup(root, backup_root, capacity_margin_bytes=0)

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
                capacity_margin_bytes=0,
            )
            status_exists = (Path(tmp) / "status.json").exists()
            status_report = (Path(tmp) / "status.md").read_text(encoding="utf-8")

        self.assertEqual(payload["status"]["status"], "OK")
        self.assertEqual(payload["restore_drill"]["status"], "PASS")
        self.assertTrue(status_exists)
        self.assertIn("Restore drill SLA: **OK**", status_report)
        self.assertIn("## Storage Class Summary", status_report)
        self.assertIn("canonical_evidence", status_report)
        self.assertIn("## CLOB Artifact Coverage", status_report)
        self.assertIn("order_book_long", status_report)

    def test_unmanifested_backup_cleanup_apply_refuses_without_manifest_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            backup_root = Path(tmp) / "backup"
            fixture_source(root)
            export_backup(root, backup_root, capacity_margin_bytes=0)
            source_extra = write(root / "data/snapshots/event/partial_copy.csv", "source\n")
            backup_extra = write(backup_root / "latest/data/snapshots/event/partial_copy.csv", "source\n")

            plan = unmanifested_backup_cleanup_plan(backup_root=backup_root, source_root=root)
            (backup_root / "latest" / "tape_backup_manifest.json").unlink()
            applied = apply_unmanifested_backup_cleanup(plan, operator_review=operator_review())
            backup_extra_exists = backup_extra.exists()
            source_extra_exists = source_extra.exists()

        self.assertEqual(applied["status"], "BLOCK")
        self.assertTrue(backup_extra_exists)
        self.assertTrue(source_extra_exists)
        self.assertIn("manifest_valid", {
            gate["check"]
            for gate in applied["gates"]
            if gate["status"] == "BLOCK"
        })

    def test_unmanifested_backup_cleanup_apply_refuses_without_restore_drill_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            backup_root = Path(tmp) / "backup"
            fixture_source(root)
            export_backup(root, backup_root, capacity_margin_bytes=0)
            source_extra = write(root / "data/snapshots/event/partial_copy.csv", "source\n")
            backup_extra = write(backup_root / "latest/data/snapshots/event/partial_copy.csv", "source\n")

            plan = unmanifested_backup_cleanup_plan(backup_root=backup_root, source_root=root)
            applied = apply_unmanifested_backup_cleanup(plan, operator_review=operator_review())
            backup_extra_exists = backup_extra.exists()
            source_extra_exists = source_extra.exists()

        self.assertEqual(applied["status"], "BLOCK")
        self.assertTrue(backup_extra_exists)
        self.assertTrue(source_extra_exists)
        self.assertIn("restore_drill_current", {
            gate["check"]
            for gate in applied["gates"]
            if gate["status"] == "BLOCK"
        })

    def test_unmanifested_backup_cleanup_apply_refuses_without_operator_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
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
            source_extra = write(root / "data/snapshots/event/partial_copy.csv", "source\n")
            backup_extra = write(backup_root / "latest/data/snapshots/event/partial_copy.csv", "source\n")

            plan = unmanifested_backup_cleanup_plan(backup_root=backup_root, source_root=root)
            applied = apply_unmanifested_backup_cleanup(plan)
            backup_extra_exists = backup_extra.exists()
            source_extra_exists = source_extra.exists()

        self.assertEqual(applied["status"], "BLOCK")
        self.assertTrue(backup_extra_exists)
        self.assertTrue(source_extra_exists)
        self.assertIn("operator_review", {
            gate["check"]
            for gate in applied["gates"]
            if gate["status"] == "BLOCK"
        })

    def test_unmanifested_backup_cleanup_apply_blocks_when_any_row_lacks_source_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
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
            source_extra = write(root / "data/snapshots/event/partial_copy.csv", "source\n")
            backup_extra = write(backup_root / "latest/data/snapshots/event/partial_copy.csv", "source\n")
            missing_source_extra = write(backup_root / "latest/data/snapshots/event/missing_source.csv", "only backup\n")

            plan = unmanifested_backup_cleanup_plan(backup_root=backup_root, source_root=root)
            applied = apply_unmanifested_backup_cleanup(plan, operator_review=operator_review())
            backup_extra_exists = backup_extra.exists()
            missing_source_extra_exists = missing_source_extra.exists()
            source_extra_exists = source_extra.exists()

        self.assertEqual(plan["summary"]["candidate_files"], 1)
        self.assertEqual(plan["summary"]["blocked_files"], 1)
        self.assertEqual(applied["status"], "BLOCK")
        self.assertTrue(backup_extra_exists)
        self.assertTrue(source_extra_exists)
        self.assertTrue(missing_source_extra_exists)
        self.assertEqual(applied["summary"]["deleted_files"], 0)
        self.assertGreaterEqual(applied["summary"]["skipped_files"], 1)

    def test_unmanifested_backup_cleanup_deletes_only_after_manifest_restore_and_operator_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
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
            source_extra = write(root / "data/snapshots/event/partial_copy.csv", "source\n")
            backup_extra = write(backup_root / "latest/data/snapshots/event/partial_copy.csv", "source\n")

            plan = unmanifested_backup_cleanup_plan(backup_root=backup_root, source_root=root)
            applied = apply_unmanifested_backup_cleanup(plan, operator_review=operator_review())
            backup_extra_exists = backup_extra.exists()
            source_extra_exists = source_extra.exists()

        self.assertEqual(plan["summary"]["candidate_files"], 1)
        self.assertEqual(plan["summary"]["blocked_files"], 0)
        self.assertTrue(plan["apply_permission"])
        self.assertEqual(applied["status"], "PASS")
        self.assertFalse(backup_extra_exists)
        self.assertTrue(source_extra_exists)
        self.assertEqual(applied["summary"]["deleted_files"], 1)
        self.assertEqual(applied["restore_drill_evidence"]["sla_status"], "OK")
        self.assertEqual(applied["post_cleanup_backup_status"]["status"], "OK")


if __name__ == "__main__":
    unittest.main()
