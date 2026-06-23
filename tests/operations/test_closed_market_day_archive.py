import unittest
import json
from pathlib import Path

import pyarrow.parquet as pq

from weather.operations.closed_market_day_archive import (
    ARCHIVE_ROOT_VERSION,
    ARTIFACT_FAMILIES_BY_NAME,
    BACKFILL_SCHEMA_VERSION,
    DEFAULT_PARQUET_CODEC,
    ELIGIBLE_FINALIZATION_STATES,
    MANIFEST_SCHEMA_VERSION,
    READER_FALLBACK_ORDER,
    archive_partition_path,
    build_backfill_payload,
    family_dataset_path,
    manifest_hash_valid,
    manifest_path_for_partition,
    parquet_reader_allowed,
    plan_market_day,
    render_backfill_report,
    sha256_file,
    validate_manifest_shape,
)
from weather.schema_registry import schema_version


def valid_manifest():
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "archive_root_version": ARCHIVE_ROOT_VERSION,
        "generated_at_utc": "2026-06-22T00:00:00+00:00",
        "writer": "weather.operations.closed_market_day_archive",
        "writer_version": "contract-test",
        "source_folder": "data/snapshots/highest-temperature-in-austin-on-june-22-2026",
        "manifest_hash": "manifest-sha256",
        "partition": {
            "local_date": "2026-06-22",
            "market_id": "austin",
            "event_slug": "highest-temperature-in-austin-on-june-22-2026",
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
                        "path": "data/snapshots/demo/order_books_long.csv",
                        "bytes": 123,
                        "sha256": "abc",
                        "role": "analysis_source",
                    },
                    {
                        "path": "data/snapshots/demo/order_books.jsonl",
                        "bytes": 456,
                        "sha256": "def",
                        "role": "raw_evidence",
                    },
                ],
                "parquet": {
                    "path": "artifact_family=order_books_long/data.parquet",
                    "bytes": 78,
                    "sha256": "789",
                    "row_count": 2,
                    "codec": DEFAULT_PARQUET_CODEC,
                    "schema_fingerprint": "fields:a,b",
                },
            }
        ],
    }


class TestClosedMarketDayArchiveContract(unittest.TestCase):
    def test_manifest_schema_is_registered(self):
        self.assertEqual(
            schema_version("closed_market_day_archive_manifest"),
            "closed_market_day_archive_manifest_v0.1",
        )
        self.assertEqual(MANIFEST_SCHEMA_VERSION, "closed_market_day_archive_manifest_v0.1")
        self.assertEqual(
            schema_version("closed_market_day_parquet_backfill"),
            "closed_market_day_parquet_backfill_v0.1",
        )
        self.assertEqual(BACKFILL_SCHEMA_VERSION, "closed_market_day_parquet_backfill_v0.1")

    def test_partition_and_family_paths_are_stable(self):
        root = Path("archive-root")
        partition = archive_partition_path(
            "2026-06-22",
            "austin",
            "highest-temperature-in-austin-on-june-22-2026",
            root=root,
        )

        self.assertEqual(
            partition.as_posix(),
            "archive-root/local_date=2026-06-22/market_id=austin/"
            "event_slug=highest-temperature-in-austin-on-june-22-2026",
        )
        self.assertEqual(
            manifest_path_for_partition(partition).name,
            "closed_market_day_archive_manifest.json",
        )
        self.assertEqual(
            family_dataset_path(partition, "order_books_long").as_posix(),
            "archive-root/local_date=2026-06-22/market_id=austin/"
            "event_slug=highest-temperature-in-austin-on-june-22-2026/"
            "artifact_family=order_books_long/data.parquet",
        )

    def test_artifact_families_preserve_raw_evidence_separate_from_parquet(self):
        required = {
            "snapshots_long",
            "source_status_long",
            "replay_inputs",
            "clob_tokens",
            "order_books_long",
            "price_history",
            "variant_predictions_long",
        }

        self.assertTrue(required.issubset(ARTIFACT_FAMILIES_BY_NAME))
        order_books = ARTIFACT_FAMILIES_BY_NAME["order_books_long"]
        self.assertIn("order_books_long.csv", order_books.source_patterns)
        self.assertIn("order_books.jsonl", order_books.raw_evidence_patterns)
        self.assertTrue(order_books.parquet_default_for_closed_days)
        self.assertTrue(order_books.raw_evidence_permanent)

    def test_manifest_shape_and_reader_gate_require_validated_parquet(self):
        manifest = valid_manifest()

        self.assertEqual(validate_manifest_shape(manifest), [])
        self.assertTrue(parquet_reader_allowed(manifest))

        manifest["validation"] = {"status": "WARN", "checks": []}
        self.assertFalse(parquet_reader_allowed(manifest))

    def test_manifest_shape_rejects_unknown_family_and_missing_partition(self):
        manifest = valid_manifest()
        manifest["partition"].pop("market_id")
        manifest["artifact_families"][0]["artifact_family"] = "made_up_family"

        errors = validate_manifest_shape(manifest)

        self.assertIn("partition.market_id is required", errors)
        self.assertIn("artifact_families[0].artifact_family is unknown", errors)

    def test_reader_fallback_and_finalization_states_are_explicit(self):
        self.assertEqual(READER_FALLBACK_ORDER, ("validated_parquet", "gzip_tiered_text", "text_tape"))
        self.assertIn("settled_countable", ELIGIBLE_FINALIZATION_STATES)
        self.assertIn("closed_unlabeled", ELIGIBLE_FINALIZATION_STATES)


class TestClosedMarketDayParquetBackfill(unittest.TestCase):
    def write_text(self, path: Path, text: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def make_closed_folder(self, root: Path, slug="highest-temperature-in-austin-on-june-22-2026"):
        folder = root / "snapshots" / slug
        self.write_text(
            folder / "snapshots_long.csv",
            "snapshot_id,event_slug,market_id,target_date,range_label,probability\n"
            f"s1,{slug},austin,2026-06-22,94,0.55\n"
            f"s1,{slug},austin,2026-06-22,95,0.45\n",
        )
        self.write_text(
            folder / "order_books_long.csv",
            "snapshot_id,market_id,token_id,bid,ask\n"
            "s1,austin,t1,0.50,0.52\n"
            "s1,austin,t2,0.48,0.50\n",
        )
        self.write_text(
            folder / "price_history.csv",
            "snapshot_id,token_id,price\n"
            "s1,t1,0.51\n"
            "s1,t2,0.49\n",
        )
        self.write_text(
            folder / "clob_tokens.csv",
            "token_id,outcome\n"
            "t1,94\n"
            "t2,95\n",
        )
        self.write_text(
            folder / "replay_inputs.jsonl",
            json.dumps({"snapshot_id": "s1", "sources": {"metar": {"temp": 93}}}) + "\n"
            + json.dumps({"snapshot_id": "s2", "sources": {"metar": {"temp": 94}}}) + "\n",
        )
        self.write_text(folder / "order_books.jsonl", '{"token_id":"t1"}\n')
        self.write_text(folder / "price_history.jsonl", '{"token_id":"t1"}\n')
        self.write_text(folder / "clob_tokens.jsonl", '{"token_id":"t1"}\n')
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
        return folder

    def test_dry_run_plans_closed_day_without_writing_archive(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = self.make_closed_folder(root)
            archive_root = root / "archive"

            payload = build_backfill_payload(
                snapshots_root=root / "snapshots",
                archive_root=archive_root,
                as_of_date="2026-06-23",
                generated_at_utc="2026-06-23T00:00:00+00:00",
            )

            self.assertEqual(payload["status"], "PASS")
            self.assertEqual(payload["mode"], "dry_run")
            self.assertEqual(payload["summary"]["planned"], 1)
            self.assertEqual(payload["summary"]["converted"], 0)
            row = payload["market_days"][0]
            self.assertEqual(row["action"], "convert")
            self.assertEqual(row["status"], "planned")
            self.assertFalse(Path(row["partition_root"]).exists())
            families = {item["artifact_family"]: item for item in row["artifact_families"]}
            self.assertEqual(families["order_books_long"]["status"], "planned_parquet")
            self.assertEqual(families["price_history"]["status"], "planned_parquet")
            self.assertEqual(families["clob_tokens"]["status"], "planned_parquet")
            self.assertEqual(families["replay_inputs"]["status"], "planned_parquet")
            self.assertEqual(families["snapshots_long"]["status"], "planned_parquet")

    def test_apply_writes_valid_manifest_and_parquet_without_touching_sources(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = self.make_closed_folder(root)
            source_hashes = {
                path.name: sha256_file(path)
                for path in folder.iterdir()
                if path.is_file()
            }

            payload = build_backfill_payload(
                snapshots_root=root / "snapshots",
                archive_root=root / "archive",
                apply=True,
                as_of_date="2026-06-23",
                generated_at_utc="2026-06-23T00:00:00+00:00",
            )

            self.assertEqual(payload["status"], "PASS")
            self.assertEqual(payload["summary"]["converted"], 1)
            self.assertEqual(payload["summary"]["source_deleted_count"], 0)
            row = payload["market_days"][0]
            manifest = json.loads(Path(row["manifest_path"]).read_text(encoding="utf-8"))
            self.assertEqual(validate_manifest_shape(manifest), [])
            self.assertTrue(manifest_hash_valid(manifest))
            self.assertTrue(parquet_reader_allowed(manifest))
            order_books = [
                item for item in manifest["artifact_families"]
                if item["artifact_family"] == "order_books_long"
            ][0]
            parquet_path = Path(row["partition_root"]) / order_books["parquet"]["path"]
            self.assertTrue(parquet_path.exists())
            self.assertEqual(pq.ParquetFile(parquet_path).metadata.num_rows, 2)
            self.assertEqual(
                {path.name: sha256_file(path) for path in folder.iterdir() if path.is_file()},
                source_hashes,
            )

    def test_apply_is_idempotent_and_rewrites_stale_source_hashes(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = self.make_closed_folder(root)
            kwargs = {
                "snapshots_root": root / "snapshots",
                "archive_root": root / "archive",
                "apply": True,
                "as_of_date": "2026-06-23",
                "generated_at_utc": "2026-06-23T00:00:00+00:00",
            }

            first = build_backfill_payload(**kwargs)
            second = build_backfill_payload(**kwargs)
            self.assertEqual(first["summary"]["converted"], 1)
            self.assertEqual(second["summary"]["skipped"], 1)
            self.assertEqual(second["market_days"][0]["action"], "skip_current_manifest")

            with (folder / "price_history.csv").open("a", encoding="utf-8") as handle:
                handle.write("s2,t1,0.53\n")
            third = build_backfill_payload(**kwargs)
            self.assertEqual(third["summary"]["converted"], 1)
            self.assertEqual(third["market_days"][0]["action"], "rewrite_stale_manifest")
            manifest = json.loads(Path(third["market_days"][0]["manifest_path"]).read_text(encoding="utf-8"))
            price_history = [
                item for item in manifest["artifact_families"]
                if item["artifact_family"] == "price_history"
            ][0]
            self.assertEqual(price_history["parquet"]["row_count"], 3)

    def test_active_day_and_writer_lock_are_excluded(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            active = self.make_closed_folder(
                root,
                slug="highest-temperature-in-austin-on-june-23-2026",
            )
            self.write_text(active / ".snapshot.lock", "active writer")

            plan = plan_market_day(
                active,
                snapshots_root=root / "snapshots",
                archive_root=root / "archive",
                as_of_date="2026-06-23",
            )

            self.assertEqual(plan["status"], "blocked")
            self.assertIn("active_or_future_target_date", plan["blockers"])
            self.assertIn("active_writer_lock", plan["blockers"])

    def test_report_renders_source_preservation_gate(self):
        payload = {
            "schema_version": BACKFILL_SCHEMA_VERSION,
            "generated_at_utc": "2026-06-23T00:00:00+00:00",
            "mode": "apply",
            "status": "PASS",
            "summary": {
                "market_day_count": 1,
                "planned": 0,
                "converted": 1,
                "skipped": 0,
                "blocked": 0,
                "failed": 0,
                "converted_family_count": 5,
                "source_deleted_count": 0,
                "source_bytes": 100,
                "parquet_bytes": 50,
            },
            "market_days": [
                {
                    "event_slug": "highest-temperature-in-austin-on-june-22-2026",
                    "status": "converted",
                    "action": "convert",
                    "converted_family_count": 5,
                    "blockers": [],
                }
            ],
        }

        report = render_backfill_report(payload)

        self.assertIn("Closed Market-Day Parquet Backfill", report)
        self.assertIn("source_deleted_count", report)
        self.assertIn("Source snapshot tapes are never deleted", report)


if __name__ == "__main__":
    unittest.main()
