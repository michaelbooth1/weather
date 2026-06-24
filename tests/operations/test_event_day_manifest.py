import json
import tempfile
import unittest
from pathlib import Path

from weather.operations.closed_market_day_archive import build_backfill_payload, plan_market_day
from weather.operations.event_day_manifest import (
    MANIFEST_FILENAME,
    SCHEMA_VERSION,
    build_event_day_manifest,
    manifest_hash_valid,
    validate_deletion_candidates,
    validate_event_day_manifest,
    write_event_day_manifest,
)
from weather.reporting.data_retention_inventory import build_payload as build_retention_payload
from weather.schema_registry import schema_version


class TestEventDayManifest(unittest.TestCase):
    def write_text(self, path: Path, text: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def make_folder(self, root: Path, slug="highest-temperature-in-austin-on-june-22-2026"):
        folder = root / "snapshots" / slug
        self.write_text(
            folder / "snapshots.jsonl",
            json.dumps({"schema_version": "snapshot_tape_v0.1", "snapshot_id": "s1"}) + "\n",
        )
        self.write_text(
            folder / "snapshots_long.csv",
            "snapshot_id,event_slug,market_id,target_date,range_label,probability\n"
            f"s1,{slug},austin,2026-06-22,94,0.55\n"
            f"s1,{slug},austin,2026-06-22,95,0.45\n",
        )
        self.write_text(
            folder / "replay_inputs.jsonl",
            json.dumps({"schema_version": "toronto_replay_inputs_v0.1", "snapshot_id": "s1"}) + "\n",
        )
        self.write_text(folder / "order_books.jsonl", '{"token_id":"t1"}\n')
        self.write_text(
            folder / "order_books_long.csv",
            "snapshot_id,market_id,token_id,bid,ask\n"
            "s1,austin,t1,0.50,0.52\n"
            "s1,austin,t2,0.48,0.50\n",
        )
        self.write_text(folder / "price_history.jsonl", '{"token_id":"t1"}\n')
        self.write_text(
            folder / "price_history.csv",
            "snapshot_id,token_id,price\n"
            "s1,t1,0.51\n",
        )
        self.write_text(
            folder / "settlement.json",
            json.dumps({
                "event_slug": slug,
                "market_id": "austin",
                "target_date": "2026-06-22",
                "settlement_bucket": 94,
                "settlement_source": "test",
                "quality_grade": "complete",
            }),
        )
        self.write_text(folder / "mm_runs" / "run-1" / "order_lifecycle.jsonl", '{"order_id":"o1"}\n')
        return folder

    def test_schema_is_registered(self):
        self.assertEqual(schema_version("event_day_manifest"), "event_day_manifest_v0.1")
        self.assertEqual(SCHEMA_VERSION, "event_day_manifest_v0.1")

    def test_manifest_lists_roles_hashes_counts_and_rebuild_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = self.make_folder(root)

            manifest = build_event_day_manifest(
                folder,
                snapshots_root=root / "snapshots",
                generated_at_utc="2026-06-23T00:00:00+00:00",
            )
            validation = validate_event_day_manifest(manifest, folder, snapshots_root=root / "snapshots")

        self.assertTrue(manifest_hash_valid(manifest))
        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(manifest["identity"]["event_slug"], "highest-temperature-in-austin-on-june-22-2026")
        self.assertGreaterEqual(manifest["summary"]["canonical_evidence_files"], 4)
        self.assertGreaterEqual(manifest["summary"]["analysis_projection_files"], 2)
        families = {row["artifact_family"]: row for row in manifest["artifact_families"]}
        self.assertEqual(families["market_ws_events"]["status"], "missing_optional")
        self.assertEqual(families["market_making_runs"]["status"], "present")
        snapshots = families["snapshots"]["files"]
        by_path = {row["path"]: row for row in snapshots}
        self.assertEqual(by_path["snapshots.jsonl"]["role"], "canonical_evidence")
        self.assertEqual(by_path["snapshots.jsonl"]["row_count"], 1)
        self.assertEqual(by_path["snapshots_long.csv"]["role"], "analysis_projection")
        self.assertEqual(by_path["snapshots_long.csv"]["row_count"], 2)
        self.assertEqual(by_path["snapshots_long.csv"]["rebuild_source"], "snapshot_jsonl_evidence")
        self.assertIn("sha256", by_path["snapshots_long.csv"])
        mm_record = families["market_making_runs"]["files"][0]
        self.assertEqual(mm_record["role"], "canonical_evidence")

    def test_deletion_candidate_gate_requires_manifest_record_and_backup_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = self.make_folder(root)
            manifest = build_event_day_manifest(folder, snapshots_root=root / "snapshots")

            gate = validate_deletion_candidates(
                manifest,
                ["snapshots.jsonl", "not_in_manifest.jsonl", "snapshots_long.csv"],
            )

        self.assertEqual(gate["status"], "BLOCK")
        blocked = [row for row in gate["checks"] if row["status"] == "BLOCK"]
        self.assertEqual(
            {row["check"] for row in blocked},
            {"canonical_backup_proof", "candidate_manifest_record"},
        )

    def test_validation_fails_closed_for_stale_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = self.make_folder(root)
            manifest = build_event_day_manifest(folder, snapshots_root=root / "snapshots")
            with (folder / "snapshots_long.csv").open("a", encoding="utf-8") as handle:
                handle.write("s2,highest-temperature-in-austin-on-june-22-2026,austin,2026-06-22,96,0.10\n")

            validation = validate_event_day_manifest(manifest, folder, snapshots_root=root / "snapshots")

        self.assertEqual(validation["status"], "BLOCK")
        checks = {row["check"] for row in validation["checks"] if row["status"] == "BLOCK"}
        self.assertTrue({"file_size", "row_count"} & checks)

    def test_archive_planning_consumes_current_manifest_and_blocks_stale_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = self.make_folder(root)
            manifest_path = write_event_day_manifest(
                folder,
                snapshots_root=root / "snapshots",
                generated_at_utc="2026-06-23T00:00:00+00:00",
            )

            plan = plan_market_day(
                folder,
                snapshots_root=root / "snapshots",
                archive_root=root / "archive",
                as_of_date="2026-06-23",
            )
            apply_payload = build_backfill_payload(
                snapshots_root=root / "snapshots",
                archive_root=root / "archive",
                apply=True,
                as_of_date="2026-06-23",
                generated_at_utc="2026-06-23T00:00:00+00:00",
            )
            archive_manifest = json.loads(Path(apply_payload["market_days"][0]["manifest_path"]).read_text(encoding="utf-8"))
            with (folder / "snapshots_long.csv").open("a", encoding="utf-8") as handle:
                handle.write("s2,highest-temperature-in-austin-on-june-22-2026,austin,2026-06-22,96,0.10\n")
            stale_plan = plan_market_day(
                folder,
                snapshots_root=root / "snapshots",
                archive_root=root / "archive",
                as_of_date="2026-06-23",
            )

        self.assertEqual(manifest_path.name, MANIFEST_FILENAME)
        self.assertEqual(plan["event_day_manifest"]["status"], "PASS")
        self.assertEqual(archive_manifest["event_day_manifest"]["manifest_hash"], plan["event_day_manifest"]["manifest_hash"])
        self.assertIn("stale_event_day_manifest", stale_plan["blockers"])

    def test_data_retention_inventory_summarizes_event_day_manifests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = self.make_folder(root)
            write_event_day_manifest(folder, snapshots_root=root / "snapshots")

            payload = build_retention_payload(root, backup_status_path=root / "missing.json", min_free_bytes=0)

        self.assertEqual(payload["event_day_manifests"]["manifest_count"], 1)
        self.assertEqual(payload["event_day_manifests"]["pass_count"], 1)


if __name__ == "__main__":
    unittest.main()
