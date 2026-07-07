import unittest

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
            "data/snapshots/event/snapshots.jsonl": CANONICAL_EVIDENCE,
            "data/snapshots/event/replay_inputs.jsonl": CANONICAL_EVIDENCE,
            "data/snapshots/event/order_books.jsonl": CANONICAL_EVIDENCE,
            "data/snapshots/event/market_ws.jsonl": CANONICAL_EVIDENCE,
            "data/backtest/market_day_labels.csv": CANONICAL_EVIDENCE,
            "data/mm_runs/run-1/order_lifecycle.jsonl": CANONICAL_EVIDENCE,
            "data/taker_runs/run-1/orders.jsonl": CANONICAL_EVIDENCE,
            "data/wunderground/cyyz/manifest.json": CANONICAL_EVIDENCE,
            "data/snapshots/event/snapshots_long.csv": ANALYSIS_PROJECTION,
            "data/snapshots/event/order_books_long.csv": ANALYSIS_PROJECTION,
            "data/archive/closed_market_days/v0.1/local_date=2026-06-22/market_id=austin/event_slug=demo/artifact_family=order_books_long/data.parquet": ANALYSIS_PROJECTION,
            "artifacts/models/hgb/feature_model_hgb.pkl": ANALYSIS_PROJECTION,
            "data/backtest/data_retention_inventory_report.md": OPERATOR_CACHE,
            "data/backtest/fleet_observability.json": OPERATOR_CACHE,
            "data/logs/daily_refresh.log": OPERATOR_CACHE,
        }

        for path, expected in examples.items():
            with self.subTest(path=path):
                classification = classify_storage_path(path)
                self.assertEqual(classification.storage_class, expected)
                self.assertNotEqual(classification.artifact_family, "unclassified")

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
            else:
                probe = f"data/snapshots/event/{family}.csv"
            classification = classify_storage_path(probe)
            if classification.artifact_family == "unclassified":
                missing.append((family, probe))

        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
