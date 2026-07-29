import gzip
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from collections import namedtuple
from pathlib import Path
from unittest.mock import patch

from weather.collection.forecast_payload_cas import (
    RAW_BYTES_HASH_ALGORITHM,
    SHARED_FORECAST_PAYLOAD_CAS_KIND,
    SHARED_FORECAST_PAYLOAD_SCOPE,
    SharedForecastPayloadCAS,
)
from weather.forecast_payload_contracts import NBM_NBP_EXTRACTION_SCHEMA
from weather.sources.nbm_probabilistic_tmax import (
    nbp_cycle_key_from_url,
    nbp_request_key,
)
from weather.operations.closed_market_day_archive import build_backfill_payload, plan_market_day
from weather.operations.event_day_manifest import (
    MANIFEST_FILENAME,
    SCHEMA_VERSION,
    build_event_day_manifest,
    build_backfill_payload as build_event_day_manifest_backfill,
    inventory_content_hash,
    main,
    manifest_hash_valid,
    validate_deletion_candidates,
    validate_event_day_manifest,
    write_event_day_manifest,
)
from weather.reporting.data_quality.data_retention_inventory import build_payload as build_retention_payload
from weather.schema_registry import schema_version


def write_payload_evidence(
    folder: Path,
    family: str,
    payload: dict,
    *,
    snapshot_id: str,
    source: str,
) -> tuple[Path, dict]:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    blob = folder / family / "sha256" / digest[:2] / f"{digest}.json"
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_bytes(canonical + b"\n")
    row = {
        "schema_version": f"{family}_manifest_v1",
        "snapshot_id": snapshot_id,
        "source": source,
        "payload_hash_algorithm": "sha256-canonical-json",
        "payload_hash": digest,
        "payload_bytes": len(canonical),
        "raw_payload_retained": True,
        "raw_payload_path": str(blob),
    }
    return blob, row


def payload_link_issue_codes(manifest: dict) -> set[str]:
    return {
        str(issue.get("code"))
        for family in (manifest.get("payload_blob_links") or {}).get("families") or []
        for issue in family.get("issues") or []
    }


class TestEventDayManifest(unittest.TestCase):
    def write_text(self, path: Path, text: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def write_gzip(self, path: Path, payload: bytes):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as raw:
            with gzip.GzipFile(
                filename="",
                mode="wb",
                fileobj=raw,
                mtime=0,
            ) as handle:
                handle.write(payload)
        return path

    def make_folder(self, root: Path, slug="highest-temperature-in-austin-on-june-22-2026"):
        folder = root / "snapshots" / slug
        proof_identity = {
            "release_id": "release-2026-06-22-a",
            "runtime_identity": {
                "schema_version": "runtime_identity_v0.1",
                "git_branch": "test",
                "git_commit": "a" * 40,
                "source_fingerprint": "source-test-v1",
                "python_version": "3.12",
            },
        }
        self.write_text(
            folder / "snapshots.jsonl",
            json.dumps({
                "schema_version": "snapshot_tape_v0.1",
                "snapshot_id": "s1",
                **proof_identity,
            }) + "\n",
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
        _, forecast_row = write_payload_evidence(
            folder,
            "forecast_payloads",
            {"forecast": [92, 94], "provider": "nbm"},
            snapshot_id="s1",
            source="nbm",
        )
        self.write_text(
            folder / "forecast_payloads.jsonl",
            json.dumps(forecast_row) + "\n",
        )
        self.write_text(
            folder / "source_status.jsonl",
            json.dumps({"schema_version": "source_status_v0.1", "snapshot_id": "s1", "source": "nbm", "status": "OK"}) + "\n",
        )
        _, observation_row = write_payload_evidence(
            folder,
            "observation_payloads",
            {"station_id": "KAUS", "temperature": 94},
            snapshot_id="s1",
            source="metar",
        )
        self.write_text(
            folder / "observation_payloads.jsonl",
            json.dumps(observation_row) + "\n",
        )
        self.write_text(
            folder / "clob_capture_status.jsonl",
            json.dumps({"schema_version": "clob_capture_status_v0.1", "status": "OK"}) + "\n",
        )
        self.write_text(
            folder / "snapshot_explanations.jsonl",
            json.dumps({"schema_version": "snapshot_explanations_v0.1", "snapshot_id": "s1"}) + "\n",
        )
        self.write_text(
            folder / "snapshot_explanations_long.csv",
            "snapshot_id,market_id,explanation\n"
            "s1,austin,forecast anchor\n",
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

    def replace_forecast_with_shared_cas(self, folder: Path, cas_root: Path):
        shutil.rmtree(folder / "forecast_payloads")
        stored = SharedForecastPayloadCAS(cas_root).put(
            b"national NBM bulletin bytes\n"
        )
        source_url = (
            "https://nomads.ncep.noaa.gov/pub/data/nccf/com/blend/prod/"
            "blend.20260622/00/text/blend_nbptx.t00z"
        )
        row = {
            "schema_version": "forecast_payload_manifest_v2",
            "snapshot_id": "s1",
            "event_slug": folder.name,
            "market_id": "austin",
            "target_date": "2026-06-22",
            "source": "nbm_probabilistic_tmax",
            "payload_storage_scope": SHARED_FORECAST_PAYLOAD_SCOPE,
            "payload_cas_kind": SHARED_FORECAST_PAYLOAD_CAS_KIND,
            "payload_hash_algorithm": RAW_BYTES_HASH_ALGORITHM,
            "payload_hash": stored["payload_hash"],
            "payload_bytes": stored["payload_bytes"],
            "payload_ref": stored["payload_ref"],
            "payload_media_type": "text/plain; charset=utf-8",
            "payload_encoding": "utf-8",
            "request_key": nbp_request_key(source_url),
            "cycle_key": nbp_cycle_key_from_url(source_url),
            "extraction_schema": NBM_NBP_EXTRACTION_SCHEMA,
            "extraction_identity": json.dumps(
                {"station_id": "KAUS", "target_date": "2026-06-22"},
                sort_keys=True,
            ),
            "raw_payload_retained": True,
            "source_url": source_url,
            "raw_payload_path": stored["path"],
        }
        self.write_text(
            folder / "forecast_payloads.jsonl",
            json.dumps(row, sort_keys=True) + "\n",
        )
        return row

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
        self.assertEqual(manifest["payload_blob_links"]["status"], "PASS")
        self.assertEqual(
            manifest["payload_blob_links"]["summary"]["linked_blob_count"],
            2,
        )
        self.assertEqual(manifest["identity"]["event_slug"], "highest-temperature-in-austin-on-june-22-2026")
        self.assertGreaterEqual(manifest["summary"]["canonical_evidence_files"], 4)
        self.assertGreaterEqual(manifest["summary"]["analysis_projection_files"], 2)
        families = {row["artifact_family"]: row for row in manifest["artifact_families"]}
        self.assertEqual(families["market_ws_events"]["status"], "missing_optional")
        self.assertEqual(families["observation_payloads"]["status"], "present")
        self.assertEqual(families["clob_capture_status"]["status"], "present")
        self.assertEqual(
            families["observation_payloads"]["required_evidence"]["status"],
            "PASS",
        )
        self.assertEqual(families["market_making_runs"]["status"], "present")
        snapshots = families["snapshots"]["files"]
        by_path = {row["path"]: row for row in snapshots}
        self.assertEqual(by_path["snapshots.jsonl"]["role"], "canonical_evidence")
        self.assertEqual(by_path["snapshots.jsonl"]["row_count"], 1)
        self.assertEqual(by_path["snapshots_long.csv"]["role"], "analysis_projection")
        self.assertEqual(by_path["snapshots_long.csv"]["row_count"], 2)
        self.assertEqual(by_path["snapshots_long.csv"]["rebuild_source"], "snapshot_jsonl_evidence")
        self.assertIn("sha256", by_path["snapshots_long.csv"])
        explanations = {
            row["path"]: row for row in families["snapshot_explanations"]["files"]
        }
        self.assertEqual(
            explanations["snapshot_explanations.jsonl"]["role"],
            "canonical_evidence",
        )
        self.assertEqual(
            explanations["snapshot_explanations_long.csv"]["role"],
            "analysis_projection",
        )
        mm_record = families["market_making_runs"]["files"][0]
        self.assertEqual(mm_record["role"], "canonical_evidence")

    def test_gzip_only_order_books_is_canonical_and_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = self.make_folder(root)
            payload = b'{"token_id":"t1"}\n{"token_id":"t2"}\n'
            (folder / "order_books.jsonl").unlink()
            self.write_gzip(folder / "order_books.jsonl.gz", payload)

            manifest = build_event_day_manifest(
                folder,
                snapshots_root=root / "snapshots",
            )
            validation = validate_event_day_manifest(
                manifest,
                folder,
                snapshots_root=root / "snapshots",
            )

        families = {
            row["artifact_family"]: row
            for row in manifest["artifact_families"]
        }
        order_books = {
            row["path"]: row for row in families["order_books"]["files"]
        }
        compressed = order_books["order_books.jsonl.gz"]
        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(compressed["row_count"], 2)
        self.assertEqual(compressed["validation_status"], "PASS")
        self.assertEqual(compressed["storage_class"], "canonical_evidence")
        self.assertEqual(compressed["artifact_family"], "clob_raw_evidence")
        self.assertTrue(compressed["protected"])

    def test_conflicting_order_book_pair_blocks_before_counting_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = self.make_folder(root)
            self.write_gzip(
                folder / "order_books.jsonl.gz",
                b'{"token_id":"different"}\n{"token_id":"extra"}\n',
            )

            manifest = build_event_day_manifest(
                folder,
                snapshots_root=root / "snapshots",
            )
            validation = validate_event_day_manifest(
                manifest,
                folder,
                snapshots_root=root / "snapshots",
            )

        families = {
            row["artifact_family"]: row
            for row in manifest["artifact_families"]
        }
        order_books = {
            row["path"]: row for row in families["order_books"]["files"]
        }
        for path in ("order_books.jsonl", "order_books.jsonl.gz"):
            with self.subTest(path=path):
                self.assertEqual(
                    order_books[path]["validation_status"],
                    "BLOCK",
                )
                self.assertEqual(order_books[path]["row_count"], 0)
                self.assertIn(
                    "TieredTextConflictError",
                    order_books[path]["validation_detail"],
                )
        self.assertEqual(manifest["validation"]["status"], "BLOCK")
        self.assertEqual(validation["status"], "BLOCK")
        blocked = {
            row["check"]
            for row in validation["checks"]
            if row["status"] == "BLOCK"
        }
        self.assertIn("file_validation", blocked)

    def test_conflicting_order_book_long_pair_blocks_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = self.make_folder(root)
            self.write_gzip(
                folder / "order_books_long.csv.gz",
                (
                    b"snapshot_id,market_id,token_id,bid,ask\n"
                    b"s0,austin,t0,0.40,0.42\n"
                ),
            )

            manifest = build_event_day_manifest(
                folder,
                snapshots_root=root / "snapshots",
            )
            validation = validate_event_day_manifest(
                manifest,
                folder,
                snapshots_root=root / "snapshots",
            )

        families = {
            row["artifact_family"]: row
            for row in manifest["artifact_families"]
        }
        order_books = {
            row["path"]: row for row in families["order_books"]["files"]
        }
        for path in ("order_books_long.csv", "order_books_long.csv.gz"):
            with self.subTest(path=path):
                self.assertEqual(
                    order_books[path]["validation_status"],
                    "BLOCK",
                )
                self.assertEqual(order_books[path]["row_count"], 0)
                self.assertIn(
                    "TieredTextConflictError",
                    order_books[path]["validation_detail"],
                )
        self.assertEqual(manifest["validation"]["status"], "BLOCK")
        self.assertEqual(validation["status"], "BLOCK")

    def test_manifest_cites_event_metadata_validation_hash_when_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            slug = "highest-temperature-in-austin-on-june-22-2026"
            folder = self.make_folder(root, slug=slug)
            validation_payload = {
                "schema_version": "event_metadata_validation_v0.1",
                "status": "PASS",
                "target_date": "2026-06-22",
                "validation_hash": "event-validation-hash",
                "market_rows": [
                    {
                        "market_id": "austin",
                        "target_date": "2026-06-22",
                        "event_slug": slug,
                        "status": "PASS",
                        "ok": True,
                        "reason": "validated",
                    }
                ],
            }

            manifest = build_event_day_manifest(
                folder,
                snapshots_root=root / "snapshots",
                event_metadata_validation_payload=validation_payload,
            )

        self.assertTrue(manifest_hash_valid(manifest))
        self.assertEqual(manifest["event_metadata_validation"]["status"], "PASS")
        self.assertEqual(manifest["summary"]["event_metadata_validation_hash"], "event-validation-hash")
        checks = {row["check"]: row for row in manifest["validation"]["checks"]}
        self.assertEqual(checks["event_metadata_validation"]["status"], "PASS")

    def test_validator_rejects_manifest_with_mismatched_required_event_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            slug = "highest-temperature-in-austin-on-june-22-2026"
            folder = self.make_folder(root, slug=slug)
            validation_payload = {
                "schema_version": "event_metadata_validation_v0.1",
                "status": "PASS",
                "target_date": "2026-06-22",
                "validation_hash": "wrong-day-validation-hash",
                "market_rows": [
                    {
                        "market_id": "austin",
                        "target_date": "2026-06-22",
                        "event_slug": "highest-temperature-in-austin-on-june-23-2026",
                        "status": "PASS",
                        "ok": True,
                        "reason": "validated",
                    }
                ],
            }

            manifest = build_event_day_manifest(
                folder,
                snapshots_root=root / "snapshots",
                event_metadata_validation_payload=validation_payload,
            )
            validation = validate_event_day_manifest(
                manifest,
                folder,
                snapshots_root=root / "snapshots",
            )

        self.assertEqual(manifest["event_metadata_validation"]["status"], "BLOCK")
        self.assertEqual(manifest["validation"]["status"], "BLOCK")
        self.assertEqual(validation["status"], "BLOCK")
        blocked = {
            row["check"]
            for row in validation["checks"]
            if row["status"] == "BLOCK"
        }
        self.assertIn("event_metadata_validation", blocked)
        self.assertIn("embedded_manifest_validation", blocked)

    def test_deletion_candidate_gate_requires_manifest_record(self):
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
            {"candidate_manifest_record"},
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

            payload = build_retention_payload(root, min_free_bytes=0)

        self.assertEqual(payload["event_day_manifests"]["manifest_count"], 1)
        self.assertEqual(payload["event_day_manifests"]["pass_count"], 1)

    def test_manifest_extracts_source_release_runtime_and_file_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = self.make_folder(root)
            payload = {
                "schema_version": "snapshot_tape_v0.2",
                "source": "weather_and_market_collector",
                "release_id": "release-2026-06-22-a",
                "model_version": "model-v7",
                "artifact_hash": "artifact-hash",
                "runtime_identity": {
                    "schema_version": "runtime_identity_v0.1",
                    "git_branch": "master",
                    "git_commit": "abc123",
                    "source_fingerprint": "source-fingerprint",
                    "python_version": "3.12.1",
                },
            }
            self.write_text(folder / "snapshots.jsonl", json.dumps(payload) + "\n")
            self.write_text(
                folder / "features.jsonl",
                json.dumps({"schema_version": "feature_tape_v0.1", "model_version": "model-v7"}) + "\n",
            )

            manifest = build_event_day_manifest(folder, snapshots_root=root / "snapshots")

        records = {
            row["path"]: row
            for family in manifest["artifact_families"]
            for row in family["files"]
        }
        snapshot = records["snapshots.jsonl"]
        self.assertEqual(snapshot["validation_status"], "PASS")
        self.assertEqual(snapshot["schema_versions"], ["snapshot_tape_v0.2"])
        self.assertEqual(snapshot["source"], ["weather_and_market_collector"])
        self.assertEqual(snapshot["release_identities"][0]["release_id"], "release-2026-06-22-a")
        identity = manifest["release_runtime_identity"]
        self.assertEqual(identity["release_identity_status"], "SINGLE")
        self.assertEqual(identity["release_identity_count"], 1)
        self.assertEqual(identity["partial_release_identity_count"], 1)
        self.assertEqual(identity["runtime_identity_status"], "SINGLE")
        self.assertEqual(identity["runtime_identities"][0]["git_commit"], "abc123")
        self.assertEqual(identity["proof_grade_status"], "PASS")
        self.assertEqual(manifest["inventory_hash"], inventory_content_hash(manifest))

    def test_proof_grade_manifest_blocks_missing_core_family_and_missing_identities(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = self.make_folder(root)
            (folder / "observation_payloads.jsonl").unlink()
            shutil.rmtree(folder / "observation_payloads")
            self.write_text(folder / "observation_payloads_long.csv", "snapshot_id,source\ns1,metar\n")
            self.write_text(
                folder / "snapshots.jsonl",
                json.dumps({"schema_version": "snapshot_tape_v0.1", "snapshot_id": "s1"}) + "\n",
            )

            manifest = build_event_day_manifest(folder, snapshots_root=root / "snapshots")
            validation = validate_event_day_manifest(
                manifest,
                folder,
                snapshots_root=root / "snapshots",
            )

        families = {row["artifact_family"]: row for row in manifest["artifact_families"]}
        self.assertEqual(families["observation_payloads"]["status"], "missing_required")
        self.assertEqual(manifest["release_runtime_identity"]["proof_grade_status"], "BLOCK")
        blocked = {row["check"] for row in validation["checks"] if row["status"] == "BLOCK"}
        self.assertTrue({"required_families", "release_identity", "runtime_identity"}.issubset(blocked))

    def test_payload_blob_link_validation_blocks_missing_blob(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = self.make_folder(root)
            next((folder / "forecast_payloads").rglob("*.json")).unlink()

            manifest = build_event_day_manifest(folder, snapshots_root=root / "snapshots")
            validation = validate_event_day_manifest(
                manifest,
                folder,
                snapshots_root=root / "snapshots",
            )

        self.assertEqual(manifest["payload_blob_links"]["status"], "BLOCK")
        self.assertIn("raw_payload_blob_missing", payload_link_issue_codes(manifest))
        self.assertEqual(validation["status"], "BLOCK")

    def test_payload_blob_link_validation_blocks_corrupt_blob(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = self.make_folder(root)
            blob = next((folder / "observation_payloads").rglob("*.json"))
            blob.write_text('{"corrupt":true}\n', encoding="utf-8")

            manifest = build_event_day_manifest(folder, snapshots_root=root / "snapshots")

        self.assertEqual(manifest["payload_blob_links"]["status"], "BLOCK")
        self.assertIn("raw_payload_blob_hash_mismatch", payload_link_issue_codes(manifest))

    def test_payload_blob_link_validation_blocks_mislinked_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = self.make_folder(root)
            observation_blob = next((folder / "observation_payloads").rglob("*.json"))
            manifest_path = folder / "forecast_payloads.jsonl"
            row = json.loads(manifest_path.read_text(encoding="utf-8"))
            row["raw_payload_path"] = str(observation_blob)
            manifest_path.write_text(json.dumps(row) + "\n", encoding="utf-8")

            manifest = build_event_day_manifest(folder, snapshots_root=root / "snapshots")

        self.assertEqual(manifest["payload_blob_links"]["status"], "BLOCK")
        self.assertIn(
            "raw_payload_path_not_content_addressed",
            payload_link_issue_codes(manifest),
        )

    def test_payload_blob_link_validation_blocks_orphan_blob(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = self.make_folder(root)
            orphan, _ = write_payload_evidence(
                folder,
                "forecast_payloads",
                {"orphan": True},
                snapshot_id="unreferenced",
                source="nbm",
            )

            manifest = build_event_day_manifest(folder, snapshots_root=root / "snapshots")

        self.assertTrue(orphan.name.endswith(".json"))
        self.assertEqual(manifest["payload_blob_links"]["status"], "BLOCK")
        self.assertIn("raw_payload_blob_orphan", payload_link_issue_codes(manifest))

    def test_malformed_jsonl_and_unclassified_file_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = self.make_folder(root)
            self.write_text(folder / "order_books.jsonl", '{"token_id":"t1"}\nnot-json\n')
            self.write_text(folder / "unknown.durable", "opaque evidence")

            manifest = build_event_day_manifest(folder, snapshots_root=root / "snapshots")
            validation = validate_event_day_manifest(
                manifest,
                folder,
                snapshots_root=root / "snapshots",
            )

        self.assertEqual(manifest["validation"]["status"], "BLOCK")
        self.assertEqual(validation["status"], "BLOCK")
        blocked = {row["check"] for row in validation["checks"] if row["status"] == "BLOCK"}
        self.assertIn("file_validation", blocked)
        self.assertIn("unclassified_file", blocked)

    def test_backup_and_restore_proof_require_every_canonical_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = self.make_folder(root)
            first = build_event_day_manifest(folder, snapshots_root=root / "snapshots")
            canonical = [
                row
                for family in first["artifact_families"]
                for row in family["files"]
                if row["storage_class"] == "canonical_evidence"
            ]
            canonical_paths = {row["path"] for row in canonical}
            self.assertIn("observation_payloads.jsonl", canonical_paths)
            self.assertTrue(
                any(
                    path.startswith("observation_payloads/sha256/")
                    and path.endswith(".json")
                    for path in canonical_paths
                )
            )
            self.assertIn("clob_capture_status.jsonl", canonical_paths)
            backup_root = root / "off-machine"
            for row in canonical:
                destination = backup_root / row["data_path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(folder / row["path"], destination)
            restore_proof = {
                "status": "PASS",
                "event_slug": folder.name,
                "generated_at_utc": "2026-06-24T00:00:00+00:00",
                "files": [
                    {"data_path": row["data_path"], "sha256": row["sha256"]}
                    for row in canonical
                ],
            }

            proven = build_event_day_manifest(
                folder,
                snapshots_root=root / "snapshots",
                backup_root=backup_root,
                restore_proof_payload=restore_proof,
            )
            first_backup = backup_root / canonical[0]["data_path"]
            first_backup.write_text("changed", encoding="utf-8")
            stale_backup = build_event_day_manifest(
                folder,
                snapshots_root=root / "snapshots",
                backup_root=backup_root,
                restore_proof_payload=restore_proof,
            )
            incomplete_proof = {**restore_proof, "files": restore_proof["files"][:-1]}
            stale_restore = build_event_day_manifest(
                folder,
                snapshots_root=root / "snapshots",
                restore_proof_payload=incomplete_proof,
            )

        self.assertEqual(proven["protection"]["status"], "PASS")
        self.assertEqual(proven["protection"]["backup"]["verified_file_count"], len(canonical))
        self.assertEqual(proven["protection"]["restore"]["verified_file_count"], len(canonical))
        self.assertEqual(stale_backup["protection"]["backup"]["status"], "BLOCK")
        self.assertEqual(stale_restore["protection"]["restore"]["status"], "BLOCK")

    def test_shared_cas_dependency_requires_backup_and_restore_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = self.make_folder(root)
            shared_row = self.replace_forecast_with_shared_cas(
                folder,
                root / "forecast_payload_cas",
            )

            unproven = build_event_day_manifest(
                folder,
                snapshots_root=root / "snapshots",
            )
            dependencies = unproven["shared_payload_dependencies"]
            self.assertEqual(len(dependencies), 1)
            dependency = dependencies[0]
            self.assertEqual(dependency["sha256"], shared_row["payload_hash"])
            self.assertEqual(
                dependency["data_path"],
                f"forecast_payload_cas/{shared_row['payload_ref']}",
            )
            checks = {
                row["check"]: row for row in unproven["validation"]["checks"]
            }
            self.assertEqual(
                checks["shared_payload_backup_restore"]["status"],
                "BLOCK",
            )
            self.assertEqual(unproven["validation"]["status"], "BLOCK")

            canonical = [
                row
                for family in unproven["artifact_families"]
                for row in family["files"]
                if row["storage_class"] == "canonical_evidence"
            ]
            protected = canonical + dependencies
            backup_root = root / "off-machine"
            for row in protected:
                source = (
                    Path(row["raw_payload_path"])
                    if row.get("artifact_family") == "shared_forecast_payload_cas"
                    else folder / row["path"]
                )
                destination = backup_root / row["data_path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            restore_proof = {
                "status": "PASS",
                "event_slug": folder.name,
                "generated_at_utc": "2026-06-24T00:00:00+00:00",
                "files": [
                    {"data_path": row["data_path"], "sha256": row["sha256"]}
                    for row in protected
                ],
            }

            proven = build_event_day_manifest(
                folder,
                snapshots_root=root / "snapshots",
                backup_root=backup_root,
                restore_proof_payload=restore_proof,
            )
            validation = validate_event_day_manifest(
                proven,
                folder,
                snapshots_root=root / "snapshots",
            )
            (backup_root / dependency["data_path"]).unlink()
            missing_shared_backup = build_event_day_manifest(
                folder,
                snapshots_root=root / "snapshots",
                backup_root=backup_root,
                restore_proof_payload=restore_proof,
            )
            incomplete_restore = {
                **restore_proof,
                "files": [
                    row
                    for row in restore_proof["files"]
                    if row["data_path"] != dependency["data_path"]
                ],
            }
            missing_shared_restore = build_event_day_manifest(
                folder,
                snapshots_root=root / "snapshots",
                backup_root=backup_root,
                restore_proof_payload=incomplete_restore,
            )

        self.assertEqual(proven["protection"]["status"], "PASS")
        self.assertEqual(proven["validation"]["status"], "PASS")
        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(
            proven["protection"]["backup"]["verified_file_count"],
            len(protected),
        )
        self.assertEqual(
            proven["protection"]["restore"]["verified_file_count"],
            len(protected),
        )
        self.assertEqual(
            missing_shared_backup["protection"]["backup"]["status"],
            "BLOCK",
        )
        self.assertEqual(
            missing_shared_restore["protection"]["restore"]["status"],
            "BLOCK",
        )

    def test_audit_detects_missing_and_incremental_apply_reuses_then_rewrites_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = self.make_folder(root)

            audit_missing = build_event_day_manifest_backfill(
                snapshots_root=root / "snapshots",
                mode="audit",
                generated_at_utc="2026-06-23T00:00:00+00:00",
            )
            first_apply = build_event_day_manifest_backfill(
                snapshots_root=root / "snapshots",
                mode="apply",
                incremental=True,
                generated_at_utc="2026-06-23T00:00:00+00:00",
            )
            manifest_path = folder / MANIFEST_FILENAME
            first_mtime = manifest_path.stat().st_mtime_ns
            with patch(
                "weather.operations.event_day_manifest._inspect_file",
                side_effect=AssertionError("unchanged files must be reused"),
            ):
                second_apply = build_event_day_manifest_backfill(
                    snapshots_root=root / "snapshots",
                    mode="apply",
                    incremental=True,
                    generated_at_utc="2026-06-24T00:00:00+00:00",
                )
            second_mtime = manifest_path.stat().st_mtime_ns
            with (folder / "price_history.csv").open("a", encoding="utf-8") as handle:
                handle.write("s2,t1,0.52\n")
            changed_apply = build_event_day_manifest_backfill(
                snapshots_root=root / "snapshots",
                mode="apply",
                incremental=True,
                generated_at_utc="2026-06-25T00:00:00+00:00",
            )

        self.assertEqual(audit_missing["status"], "BLOCK")
        self.assertEqual(audit_missing["summary"]["missing_manifest_count"], 1)
        self.assertEqual(first_apply["summary"]["written_count"], 1)
        self.assertEqual(second_apply["summary"]["written_count"], 0)
        self.assertEqual(second_apply["summary"]["reused_count"], 1)
        self.assertEqual(second_apply["market_days"][0]["manifest_state"], "CURRENT")
        self.assertEqual(first_mtime, second_mtime)
        self.assertEqual(changed_apply["summary"]["written_count"], 1)
        self.assertEqual(changed_apply["market_days"][0]["manifest_state"], "CHANGED")

    def test_atomic_writer_and_audit_cli_have_explicit_write_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = self.make_folder(root)
            with patch(
                "weather.operations.event_day_manifest.os.replace",
                wraps=os.replace,
            ) as replace:
                write_event_day_manifest(folder, snapshots_root=root / "snapshots")
            out = root / "audit.json"
            report = root / "audit.md"
            payload = main([
                "audit",
                "--snapshots-root",
                str(root / "snapshots"),
                "--out",
                str(out),
                "--report",
                str(report),
            ])
            out_exists = out.exists()
            report_exists = report.exists()

        self.assertEqual(replace.call_count, 1)
        self.assertEqual(payload["mode"], "audit")
        self.assertFalse(out_exists)
        self.assertFalse(report_exists)

    def test_storage_gate_exposes_thirty_day_headroom_inputs(self):
        usage = namedtuple("usage", "total used free")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_folder(root)
            with patch(
                "weather.operations.event_day_manifest.shutil.disk_usage",
                return_value=usage(total=100_000, used=40_000, free=60_000),
            ):
                payload = build_event_day_manifest_backfill(
                    snapshots_root=root / "snapshots",
                    mode="plan",
                    daily_growth_bytes=1_000,
                    min_growth_headroom_days=30,
                )

        gate = payload["storage_gate"]
        self.assertEqual(gate["growth_headroom_status"], "PASS")
        self.assertEqual(gate["growth_headroom_days"], 60.0)
        self.assertEqual(gate["required_growth_headroom_days"], 30.0)
        self.assertGreater(gate["canonical_evidence_bytes"], 0)
        self.assertGreater(gate["bytes_requiring_off_machine_backup"], 0)


if __name__ == "__main__":
    unittest.main()
