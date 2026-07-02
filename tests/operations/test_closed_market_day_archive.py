import unittest
import gzip
import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
from pandas.testing import assert_frame_equal

from weather.operations.closed_market_day_archive import (
    ARCHIVE_ROOT_VERSION,
    ARTIFACT_FAMILIES_BY_NAME,
    BACKFILL_SCHEMA_VERSION,
    DEFAULT_PARQUET_CODEC,
    ELIGIBLE_FINALIZATION_STATES,
    INCREMENTAL_SCHEMA_VERSION,
    MANIFEST_SCHEMA_VERSION,
    READER_FALLBACK_ORDER,
    archive_partition_path,
    build_backfill_payload,
    build_incremental_payload,
    family_dataset_path,
    manifest_hash_valid,
    manifest_path_for_partition,
    parquet_reader_allowed,
    plan_market_day,
    read_market_day_artifact,
    render_backfill_report,
    render_incremental_report,
    sha256_file,
    validate_manifest_shape,
    write_incremental_outputs,
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
    def test_source_frame_stringifies_ints_arrow_cannot_hold(self):
        # Polymarket CLOB token ids are 256-bit integers; without coercion
        # pyarrow raises OverflowError and the whole market-day fails.
        import tempfile

        import pyarrow as pa

        from weather.operations.closed_market_day_archive import _read_source_frame

        token = 2**255 + 7
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clob_features_long.csv"
            path.write_text(
                "snapshot_id,clob_token_id,clob_midpoint\n"
                f"s1,{token},0.55\n"
                "s2,,0.60\n",
                encoding="utf-8",
            )
            frame = _read_source_frame(path)
            table = pa.Table.from_pandas(frame, preserve_index=False)

        self.assertEqual(frame["clob_token_id"].iloc[0], str(token))
        self.assertEqual(table.num_rows, 2)

    def test_source_frame_replaces_undecodable_bytes_with_provenance(self):
        # A single corrupt byte in a large historical tape must not fail the
        # whole market-day: raw evidence keeps the exact bytes, the analysis
        # view reads tolerantly and records the fallback in provenance.
        import tempfile

        from weather.operations.closed_market_day_archive import _read_source_frame

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "order_books_long.csv"
            path.write_bytes(b"snapshot_id,note\ns1,20\xb0C\ns2,ok\n")
            frame = _read_source_frame(path)

        self.assertEqual(len(frame), 2)
        self.assertEqual(
            frame.attrs.get("reader_fallback_reason"),
            "csv_decode_fallback_replaced_bytes",
        )
        self.assertIn("�", str(frame["note"].iloc[0]))

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
        self.assertEqual(
            schema_version("closed_market_day_parquet_incremental"),
            "closed_market_day_parquet_incremental_v0.1",
        )
        self.assertEqual(INCREMENTAL_SCHEMA_VERSION, "closed_market_day_parquet_incremental_v0.1")

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
        price_history = ARTIFACT_FAMILIES_BY_NAME["price_history"]
        self.assertIn("price_history_raw_manifest.jsonl", price_history.raw_evidence_patterns)
        self.assertIn("price_history_raw/*.json", price_history.raw_evidence_patterns)

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
            self.make_closed_folder(root)
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

    def test_reader_prefers_validated_parquet_with_text_parity_and_provenance(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = self.make_closed_folder(root)
            payload = build_backfill_payload(
                snapshots_root=root / "snapshots",
                archive_root=root / "archive",
                apply=True,
                as_of_date="2026-06-23",
                generated_at_utc="2026-06-23T00:00:00+00:00",
            )
            manifest_hash = payload["market_days"][0]["manifest_hash"]

            parquet_result = read_market_day_artifact(
                folder,
                "order_books_long",
                snapshots_root=root / "snapshots",
                archive_root=root / "archive",
                as_of_date="2026-06-23",
            )
            text_result = read_market_day_artifact(
                folder,
                "order_books_long",
                snapshots_root=root / "snapshots",
                archive_root=root / "archive",
                as_of_date="2026-06-23",
                prefer_archive=False,
            )

            self.assertEqual(parquet_result.provenance.source_mode, "validated_parquet")
            self.assertEqual(parquet_result.provenance.manifest_hash, manifest_hash)
            self.assertEqual(parquet_result.provenance.row_count, 2)
            self.assertEqual(parquet_result.provenance.source_file_hash, sha256_file(folder / "order_books_long.csv"))
            self.assertIsNone(parquet_result.provenance.fallback_reason)
            self.assertEqual(text_result.provenance.source_mode, "text_tape")
            self.assertEqual(text_result.provenance.fallback_reason, "archive_disabled")
            assert_frame_equal(parquet_result.frame, text_result.frame, check_dtype=False)

    def test_reader_parity_for_representative_snapshot_clob_replay_and_price_history_families(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = self.make_closed_folder(root)
            build_backfill_payload(
                snapshots_root=root / "snapshots",
                archive_root=root / "archive",
                apply=True,
                as_of_date="2026-06-23",
                generated_at_utc="2026-06-23T00:00:00+00:00",
            )

            for family in ("snapshots_long", "order_books_long", "price_history", "clob_tokens", "replay_inputs"):
                with self.subTest(family=family):
                    parquet_result = read_market_day_artifact(
                        folder,
                        family,
                        snapshots_root=root / "snapshots",
                        archive_root=root / "archive",
                        as_of_date="2026-06-23",
                    )
                    text_result = read_market_day_artifact(
                        folder,
                        family,
                        snapshots_root=root / "snapshots",
                        archive_root=root / "archive",
                        as_of_date="2026-06-23",
                        prefer_archive=False,
                    )

                    self.assertEqual(parquet_result.provenance.source_mode, "validated_parquet")
                    self.assertEqual(text_result.provenance.source_mode, "text_tape")
                    assert_frame_equal(parquet_result.frame, text_result.frame, check_dtype=False)

    def test_reader_falls_back_to_text_for_active_or_unarchived_days(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = self.make_closed_folder(root)

            active_result = read_market_day_artifact(
                folder,
                "order_books_long",
                snapshots_root=root / "snapshots",
                archive_root=root / "archive",
                as_of_date="2026-06-22",
            )
            closed_unarchived_result = read_market_day_artifact(
                folder,
                "order_books_long",
                snapshots_root=root / "snapshots",
                archive_root=root / "archive",
                as_of_date="2026-06-23",
            )

            self.assertEqual(active_result.provenance.source_mode, "text_tape")
            self.assertEqual(active_result.provenance.fallback_reason, "active_or_future_target_date")
            self.assertEqual(active_result.provenance.row_count, 2)
            self.assertEqual(closed_unarchived_result.provenance.source_mode, "text_tape")
            self.assertEqual(closed_unarchived_result.provenance.fallback_reason, "missing_archive_manifest")

    def test_reader_prefers_gzip_tiered_text_when_parquet_is_unavailable(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = self.make_closed_folder(root)
            csv_text = (folder / "snapshots_long.csv").read_text(encoding="utf-8")
            (folder / "snapshots_long.csv").unlink()
            with gzip.open(folder / "snapshots_long.csv.gz", "wt", encoding="utf-8", newline="") as handle:
                handle.write(csv_text)

            result = read_market_day_artifact(
                folder,
                "snapshots_long",
                snapshots_root=root / "snapshots",
                archive_root=root / "archive",
                as_of_date="2026-06-23",
            )

            expected = pd.read_csv(folder / "snapshots_long.csv.gz")
            self.assertEqual(result.provenance.source_mode, "gzip_tiered_text")
            self.assertEqual(result.provenance.fallback_reason, "missing_archive_manifest")
            self.assertEqual(result.provenance.row_count, 2)
            assert_frame_equal(result.frame, expected, check_dtype=False)

    def test_reader_tolerates_legacy_csv_rows_with_extra_fields(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = self.make_closed_folder(root)
            (folder / "snapshots_long.csv").write_text(
                "snapshot_id,event_slug,market_id\n"
                "s1,highest-temperature-in-austin-on-june-22-2026,austin\n"
                "s2,highest-temperature-in-austin-on-june-22-2026,austin,legacy-extra\n",
                encoding="utf-8",
            )

            result = read_market_day_artifact(
                folder,
                "snapshots_long",
                snapshots_root=root / "snapshots",
                archive_root=root / "archive",
                as_of_date="2026-06-23",
            )

            self.assertEqual(result.provenance.source_mode, "text_tape")
            self.assertIn("csv_parser_fallback_bad_lines", result.provenance.fallback_reason)
            self.assertEqual(result.provenance.row_count, 2)
            self.assertEqual(list(result.frame.columns), ["snapshot_id", "event_slug", "market_id"])
            self.assertEqual(result.frame.iloc[1]["market_id"], "austin")

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

    def test_incremental_payload_uses_bounded_scan_cursor_and_skips_unchanged_folders(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_folder = self.make_closed_folder(
                root,
                slug="highest-temperature-in-austin-on-june-21-2026",
            )
            self.make_closed_folder(
                root,
                slug="highest-temperature-in-austin-on-june-22-2026",
            )

            first = build_incremental_payload(
                snapshots_root=root / "snapshots",
                archive_root=root / "archive",
                as_of_date="2026-06-23",
                max_scan_folders=1,
                cursor_path=None,
                generated_at_utc="2026-06-23T00:00:00+00:00",
            )
            second = build_incremental_payload(
                snapshots_root=root / "snapshots",
                archive_root=root / "archive",
                as_of_date="2026-06-23",
                max_scan_folders=1,
                cursor=first["cursor"],
                cursor_path=None,
                generated_at_utc="2026-06-23T00:01:00+00:00",
            )
            third = build_incremental_payload(
                snapshots_root=root / "snapshots",
                archive_root=root / "archive",
                as_of_date="2026-06-23",
                max_scan_folders=1,
                cursor=second["cursor"],
                cursor_path=None,
                generated_at_utc="2026-06-23T00:02:00+00:00",
            )

        self.assertEqual(first["schema_version"], INCREMENTAL_SCHEMA_VERSION)
        self.assertEqual(first["summary"]["scanned"], 1)
        self.assertEqual(first["summary"]["changed"], 1)
        self.assertEqual(first["summary"]["planned"], 1)
        self.assertEqual(first["scan"]["remaining_folders"], 1)
        self.assertEqual(second["summary"]["scanned"], 1)
        self.assertEqual(second["scan"]["next_index"], 0)
        self.assertEqual(third["summary"]["scanned"], 1)
        self.assertEqual(third["summary"]["unchanged"], 1)
        self.assertEqual(third["market_days"][0]["action"], "skip_unchanged")
        self.assertIn(first_folder.name, third["cursor"]["folders"])

    def test_incremental_apply_writes_status_report_and_cursor(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = self.make_closed_folder(root)
            cursor_path = root / "backtest" / "cursor.json"
            json_path = root / "backtest" / "incremental.json"
            report_path = root / "backtest" / "incremental.md"

            payload = build_incremental_payload(
                snapshots_root=root / "snapshots",
                archive_root=root / "archive",
                apply=True,
                as_of_date="2026-06-23",
                event_slugs=[folder.name],
                cursor_path=cursor_path,
                generated_at_utc="2026-06-23T00:00:00+00:00",
            )
            json_out, report_out, cursor_out = write_incremental_outputs(
                payload,
                json_path=json_path,
                report_path=report_path,
                cursor_path=cursor_path,
            )
            report = render_incremental_report(payload)
            cursor = json.loads(Path(cursor_out).read_text(encoding="utf-8"))
            json_exists = Path(json_out).exists()
            report_exists = Path(report_out).exists()

        self.assertEqual(payload["summary"]["converted"], 1)
        self.assertEqual(payload["summary"]["failed"], 0)
        self.assertEqual(payload["summary"]["source_deleted_count"], 0)
        self.assertTrue(json_exists)
        self.assertTrue(report_exists)
        self.assertEqual(cursor["schema_version"], INCREMENTAL_SCHEMA_VERSION)
        self.assertIn(folder.name, cursor["folders"])
        self.assertIn("Incremental Closed Market-Day Parquet Conversion", report)
        self.assertIn("Source snapshot tapes are never deleted", report)

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
