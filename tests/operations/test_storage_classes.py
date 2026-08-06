import unittest

from weather.market.mm_paper_constants import (
    EXECUTION_CANONICAL_TAPE_FILENAME,
    EXECUTION_RAW_TAPE_FILENAME,
    EXECUTION_SESSION_FILENAME,
)
from weather.operations.closed_market_day_archive import ARTIFACT_FAMILY_NAMES
from weather.operations.storage_classes import (
    ANALYSIS_PROJECTION,
    CANONICAL_EVIDENCE,
    OPERATOR_CACHE,
    STORAGE_CLASSES,
    classify_storage_path,
    storage_class_contracts_payload,
)


class TestStorageClassRegistry(unittest.TestCase):
    def test_three_storage_classes_have_operator_contracts(self):
        contracts = {row["name"]: row for row in storage_class_contracts_payload()}

        self.assertEqual(set(STORAGE_CLASSES), {CANONICAL_EVIDENCE, ANALYSIS_PROJECTION, OPERATOR_CACHE})
        self.assertEqual(set(contracts), set(STORAGE_CLASSES))
        self.assertIn("reviewed cleanup manifest", contracts[CANONICAL_EVIDENCE]["protection_requirement"].lower())
        self.assertIn("rebuild", contracts[ANALYSIS_PROJECTION]["deletion_prerequisite"].lower())
        self.assertIn("ttl", contracts[OPERATOR_CACHE]["retention_default"].lower())

    def test_representative_current_data_artifacts_are_classified(self):
        examples = {
            "data/forecast_payload_cas/sha256/ab/abcdef.blob": CANONICAL_EVIDENCE,
            "data/snapshots/event/snapshots.jsonl": CANONICAL_EVIDENCE,
            "data/snapshots/event/replay_inputs.jsonl": CANONICAL_EVIDENCE,
            "data/snapshots/event/observation_payloads.jsonl": CANONICAL_EVIDENCE,
            "data/snapshots/event/observation_payloads/s1_metar_hash.json": CANONICAL_EVIDENCE,
            "data/snapshots/event/clob_capture_status.jsonl": CANONICAL_EVIDENCE,
            "data/snapshots/event/order_books.jsonl": CANONICAL_EVIDENCE,
            "data/snapshots/event/market_ws.jsonl": CANONICAL_EVIDENCE,
            "data/snapshots/event/snapshot_explanations.jsonl": CANONICAL_EVIDENCE,
            "data/snapshots/event/variant_predictions.jsonl": CANONICAL_EVIDENCE,
            "data/backtest/market_day_labels.csv": CANONICAL_EVIDENCE,
            "data/mm_runs/run-1/order_lifecycle.jsonl": CANONICAL_EVIDENCE,
            "data/taker_runs/run-1/orders.jsonl": CANONICAL_EVIDENCE,
            "data/taker_runs/2026-07-13/run-1/incremental_state.sqlite3": ANALYSIS_PROJECTION,
            "data/wunderground/cyyz/manifest.json": CANONICAL_EVIDENCE,
            "data/snapshots/event/snapshots_long.csv": ANALYSIS_PROJECTION,
            "data/snapshots/event/observation_payloads_long.csv": ANALYSIS_PROJECTION,
            "data/snapshots/event/snapshot_explanations_long.csv": ANALYSIS_PROJECTION,
            "data/snapshots/event/variant_predictions_long.csv": ANALYSIS_PROJECTION,
            "data/snapshots/event/order_books_long.csv": ANALYSIS_PROJECTION,
            "data/archive/closed_market_days/v0.1/local_date=2026-06-22/market_id=austin/event_slug=demo/artifact_family=order_books_long/data.parquet": ANALYSIS_PROJECTION,
            "artifacts/models/hgb/feature_model_hgb.pkl": ANALYSIS_PROJECTION,
            "data/backtest/data_retention_inventory_report.md": OPERATOR_CACHE,
            "data/backtest/fleet_observability.json": OPERATOR_CACHE,
            "data/backtest/replay_cache/event/key.json": OPERATOR_CACHE,
            "data/backtest/cache/replay/event/key.json": OPERATOR_CACHE,
            "data/logs/daily_refresh.log": OPERATOR_CACHE,
            "data/snapshots/observation_source_cache/toronto.json": OPERATOR_CACHE,
        }

        for path, expected in examples.items():
            with self.subTest(path=path):
                classification = classify_storage_path(path)
                self.assertEqual(classification.storage_class, expected)
                self.assertNotEqual(classification.artifact_family, "unclassified")

    def test_replay_cache_layouts_have_exact_rebuildable_cache_contract(self):
        for path in (
            "data/backtest/replay_cache/event/key.json",
            "data/backtest/cache/replay/event/key.json",
        ):
            with self.subTest(path=path):
                classification = classify_storage_path(path)
                self.assertEqual(classification.artifact_family, "replay_cache")
                self.assertEqual(classification.storage_class, OPERATOR_CACHE)
                self.assertIn("exact pinned promotion corpus", classification.rebuild_source)
                self.assertIn("reachability", classification.notes)

    def test_dedicated_maker_execution_tapes_are_permanent_canonical_evidence(self):
        filenames = (
            EXECUTION_RAW_TAPE_FILENAME,
            EXECUTION_CANONICAL_TAPE_FILENAME,
            EXECUTION_SESSION_FILENAME,
        )

        for filename in filenames:
            with self.subTest(filename=filename):
                classification = classify_storage_path(
                    f"data/snapshots/event/{filename}"
                )
                self.assertEqual(
                    classification.artifact_family,
                    "maker_execution_tape",
                )
                self.assertEqual(classification.storage_class, CANONICAL_EVIDENCE)
                self.assertEqual(
                    classification.retention_class,
                    "permanent_maker_execution_evidence",
                )
                self.assertTrue(classification.protected)
                self.assertTrue(classification.durable)
                self.assertIn("not rebuildable", classification.rebuild_source)

    def test_order_book_long_projection_has_specific_rebuild_contract(self):
        for path in (
            "data/snapshots/event/order_books_long.csv",
            "data/snapshots/event/order_books_long.csv.gz",
        ):
            with self.subTest(path=path):
                classification = classify_storage_path(path)
                self.assertEqual(
                    classification.artifact_family,
                    "clob_order_book_long_projection",
                )
                self.assertEqual(
                    classification.rebuild_source,
                    "snapshots/<event>/order_books.jsonl",
                )
                self.assertEqual(
                    classification.delete_gate,
                    "projection_rebuild_source_and_reader_fallback_gate",
                )

    def test_closed_archive_families_have_projection_or_canonical_registry_coverage(self):
        missing = []
        for family in ARTIFACT_FAMILY_NAMES:
            if family == "replay_input_status":
                probe = "data/snapshots/event/replay_input_status_long.csv"
            elif family == "replay_inputs":
                probe = "data/snapshots/event/replay_inputs.jsonl"
            elif family == "market_ws_events":
                probe = "data/snapshots/event/market_ws_events.csv"
            elif family == "variant_predictions_long":
                probe = "data/snapshots/event/variant_predictions_long.csv"
            elif family == "clob_capture_status":
                probe = "data/snapshots/event/clob_capture_status.jsonl"
            elif family == "maker_execution_tape":
                probe = (
                    f"data/snapshots/event/{EXECUTION_CANONICAL_TAPE_FILENAME}"
                )
            else:
                probe = f"data/snapshots/event/{family}.csv"
            classification = classify_storage_path(probe)
            if classification.artifact_family == "unclassified":
                missing.append((family, probe))

        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
