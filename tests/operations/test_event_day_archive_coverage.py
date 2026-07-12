import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from weather.io import write_json_atomic
from weather.operations.closed_market_day_archive_manifest_contract import (
    manifest_content_hash as archive_manifest_content_hash,
)
from weather.operations.event_day_archive_coverage import (
    CURSOR_SCHEMA_VERSION,
    EVENT_MANIFEST_SCHEMA_VERSION,
    SCHEMA_VERSION,
    audit_hash_valid,
    build_payload,
    write_outputs,
)
from weather.operations.event_day_manifest import (
    inventory_content_hash,
    manifest_content_hash,
)


def _event_manifest(slug, target_date, market_id="toronto"):
    payload = {
        "schema_version": EVENT_MANIFEST_SCHEMA_VERSION,
        "writer_version": "event_day_manifest_writer_v0.1",
        "identity": {
            "event_slug": slug,
            "target_date": target_date,
            "local_date": target_date,
            "market_id": market_id,
        },
        "event_metadata_validation": {},
        "release_runtime_identity": {},
        "artifact_families": [
            {
                "artifact_family": "snapshots",
                "status": "missing_optional",
                "files": [],
            }
        ],
        "validation": {"status": "PASS"},
        "protection": {
            "backup": {"status": "PASS"},
            "restore": {"status": "PASS"},
        },
    }
    payload["inventory_hash"] = inventory_content_hash(payload)
    payload["manifest_hash"] = manifest_content_hash(payload)
    return payload


def _archive_manifest(slug, target_date, event_hash, market_id="toronto"):
    payload = {
        "schema_version": "closed_market_day_archive_manifest_v0.1",
        "archive_root_version": "v0.1",
        "generated_at_utc": "2026-07-11T12:00:00+00:00",
        "writer": "test",
        "writer_version": "closed_market_day_parquet_backfill_v0.1",
        "source_folder": slug,
        "partition": {
            "event_slug": slug,
            "local_date": target_date,
            "market_id": market_id,
        },
        "finalization": {"state": "closed_unlabeled", "countable": False},
        "validation": {"status": "PASS"},
        "event_day_manifest": {"manifest_hash": event_hash},
        "artifact_families": [
            {
                "artifact_family": "snapshots_long",
                "status": "missing_source",
                "source_files": [],
            }
        ],
    }
    payload["manifest_hash"] = archive_manifest_content_hash(payload)
    return payload


def _write_archive(root, slug, target_date, manifest, market_id="toronto"):
    path = (
        root
        / f"local_date={target_date}"
        / f"market_id={market_id}"
        / f"event_slug={slug}"
        / "closed_market_day_archive_manifest.json"
    )
    write_json_atomic(path, manifest)
    return path


def _cursor(snapshots, archive, as_of, folders, *, updated="2026-07-11T12:30:00+00:00"):
    return {
        "schema_version": CURSOR_SCHEMA_VERSION,
        "updated_at_utc": updated,
        "snapshots_root": str(snapshots),
        "archive_root": str(archive),
        "as_of_date": as_of,
        "scan": {
            "total_folders": len(list(snapshots.iterdir())),
            "remaining_folders": 0,
            "next_index": 0,
        },
        "folders": folders,
    }


class TestEventDayArchiveCoverage(unittest.TestCase):
    def test_complete_hash_linked_index_passes_without_source_or_parquet_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots, archive = root / "snapshots", root / "archive"
            slug, target = "highest-temperature-in-toronto-on-june-1-2026", "2026-06-01"
            folder = snapshots / slug
            folder.mkdir(parents=True)
            event = _event_manifest(slug, target)
            write_json_atomic(folder / "event_day_manifest.json", event)
            archive_manifest = _archive_manifest(slug, target, event["manifest_hash"])
            _write_archive(archive, slug, target, archive_manifest)
            cursor_path = root / "cursor.json"
            write_json_atomic(
                cursor_path,
                _cursor(
                    snapshots,
                    archive,
                    "2026-06-02",
                    {slug: {"status": "converted", "action": "convert", "manifest_hash": archive_manifest["manifest_hash"]}},
                ),
            )
            with patch("pathlib.Path.rglob", side_effect=AssertionError("recursive scan forbidden")), patch(
                "os.walk", side_effect=AssertionError("tree walk forbidden")
            ):
                payload = build_payload(
                    snapshots_root=snapshots,
                    archive_root=archive,
                    cursor_path=cursor_path,
                    as_of_date="2026-06-02",
                    generated_at_utc="2026-07-11T13:00:00+00:00",
                )
            self.assertEqual(payload["status"], "PASS")
            self.assertEqual(payload["schema_version"], "event_day_archive_coverage_audit_v0.2")
            self.assertEqual(payload["summary"]["closed_fully_linked_archive_evidence_count"], 1)
            self.assertTrue(audit_hash_valid(payload))
            self.assertFalse(payload["scope"]["source_tape_walked"])
            self.assertFalse(payload["scope"]["parquet_files_opened"])

    def test_invalid_archive_shape_and_partition_identity_never_count_as_declared_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots, archive = root / "snapshots", root / "archive"
            slug, target = "highest-temperature-in-toronto-on-june-1-2026", "2026-06-01"
            folder = snapshots / slug
            folder.mkdir(parents=True)
            event = _event_manifest(slug, target)
            write_json_atomic(folder / "event_day_manifest.json", event)
            invalid = _archive_manifest(slug, target, event["manifest_hash"])
            invalid["artifact_families"] = []
            invalid["manifest_hash"] = archive_manifest_content_hash(invalid)
            _write_archive(archive, slug, target, invalid)
            cursor_path = root / "cursor.json"
            write_json_atomic(cursor_path, _cursor(snapshots, archive, "2026-06-02", {slug: {"status": "skipped", "action": "skip_current_manifest"}}))
            payload = build_payload(
                snapshots_root=snapshots,
                archive_root=archive,
                cursor_path=cursor_path,
                as_of_date="2026-06-02",
                generated_at_utc="2026-07-11T13:00:00+00:00",
            )
            self.assertEqual(payload["status"], "BLOCK")
            self.assertEqual(payload["summary"]["closed_declared_archive_manifest_count"], 0)
            self.assertEqual(payload["market_days"][0]["archive_manifest_state"], "SHAPE_INVALID")

    def test_cursor_contract_and_archive_hash_link_fail_closed_including_skipped_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots, archive = root / "snapshots", root / "archive"
            slug, target = "highest-temperature-in-toronto-on-june-1-2026", "2026-06-01"
            folder = snapshots / slug
            folder.mkdir(parents=True)
            event = _event_manifest(slug, target)
            write_json_atomic(folder / "event_day_manifest.json", event)
            archived = _archive_manifest(slug, target, event["manifest_hash"])
            _write_archive(archive, slug, target, archived)
            cursor_path = root / "cursor.json"
            cursor = _cursor(
                snapshots,
                archive,
                "2026-06-02",
                {slug: {"status": "skipped", "action": "skip_current_manifest"}},
            )
            cursor["archive_root"] = str(root / "wrong-archive")
            cursor["as_of_date"] = "2026-06-01"
            cursor["updated_at_utc"] = "2026-07-09T12:30:00+00:00"
            cursor["scan"]["remaining_folders"] = 1
            write_json_atomic(cursor_path, cursor)
            payload = build_payload(
                snapshots_root=snapshots,
                archive_root=archive,
                cursor_path=cursor_path,
                as_of_date="2026-06-02",
                generated_at_utc="2026-07-11T13:00:00+00:00",
            )
            self.assertEqual(payload["summary"]["cursor_state"], "INVALID")
            self.assertIn("cursor_archive_root_mismatch", payload["cursor_contract_errors"])
            self.assertIn("cursor_as_of_date_mismatch", payload["cursor_contract_errors"])
            self.assertIn("cursor_stale", payload["cursor_contract_errors"])
            self.assertIn("cursor_scan_incomplete", payload["cursor_contract_errors"])
            self.assertEqual(payload["gaps"]["cursor_archive_hash_missing_or_mismatch"], [slug])
            self.assertEqual(payload["market_days"][0]["cursor_archive_manifest_link_state"], "MISSING_HASH")

    def test_archive_partition_date_market_and_slug_identity_are_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots, archive = root / "snapshots", root / "archive"
            slug, target = "highest-temperature-in-toronto-on-june-1-2026", "2026-06-01"
            folder = snapshots / slug
            folder.mkdir(parents=True)
            event = _event_manifest(slug, target)
            write_json_atomic(folder / "event_day_manifest.json", event)
            archived = _archive_manifest(slug, target, event["manifest_hash"])
            archived["partition"]["market_id"] = "nyc"
            archived["manifest_hash"] = archive_manifest_content_hash(archived)
            _write_archive(archive, slug, target, archived)
            cursor_path = root / "cursor.json"
            write_json_atomic(
                cursor_path,
                _cursor(snapshots, archive, "2026-06-02", {slug: {"status": "converted", "manifest_hash": archived["manifest_hash"]}}),
            )
            payload = build_payload(
                snapshots_root=snapshots,
                archive_root=archive,
                cursor_path=cursor_path,
                as_of_date="2026-06-02",
                generated_at_utc="2026-07-11T13:00:00+00:00",
            )
            self.assertEqual(
                payload["market_days"][0]["archive_manifest_state"],
                "PARTITION_IDENTITY_MISMATCH",
            )
            self.assertEqual(payload["status"], "BLOCK")

    def test_output_self_hash_and_input_digests_are_tamper_evident(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = build_payload(
                snapshots_root=root / "snapshots",
                archive_root=root / "archive",
                cursor_path=root / "missing-cursor.json",
                as_of_date="2026-06-02",
                generated_at_utc="2026-07-11T13:00:00+00:00",
            )
            json_out, report_out = write_outputs(
                payload, out_path=root / "audit.json", report_path=root / "audit.md"
            )
            written = json.loads(json_out.read_text(encoding="utf-8"))
            self.assertTrue(audit_hash_valid(written))
            self.assertIn("snapshot_folder_index", written["input_evidence"])
            self.assertIn("Audit SHA-256", report_out.read_text(encoding="utf-8"))
            tampered = deepcopy(written)
            tampered["status"] = "PASS"
            self.assertFalse(audit_hash_valid(tampered))


if __name__ == "__main__":
    unittest.main()
