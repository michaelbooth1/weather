import unittest
from pathlib import Path

from weather.operations.closed_market_day_archive import (
    ARCHIVE_ROOT_VERSION,
    ARTIFACT_FAMILIES_BY_NAME,
    DEFAULT_PARQUET_CODEC,
    ELIGIBLE_FINALIZATION_STATES,
    MANIFEST_SCHEMA_VERSION,
    READER_FALLBACK_ORDER,
    archive_partition_path,
    family_dataset_path,
    manifest_path_for_partition,
    parquet_reader_allowed,
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


if __name__ == "__main__":
    unittest.main()
