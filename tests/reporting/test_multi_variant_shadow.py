import csv
import json
import tempfile
import unittest
from pathlib import Path

from weather.reporting.multi_variant_shadow import (
    build_payload,
    read_prediction_rows,
    render_report,
    write_long_csv,
)


def _row(variant_id, day, probability, current=0.50, market=0.50, outcome=1, **extra):
    row = {
        "variant_id": variant_id,
        "variant_family": "f_family",
        "uses_market_features": False,
        "is_control": False,
        "market_id": "nyc",
        "target_date": day,
        "snapshot_id": f"{day}-s1",
        "band_key": "eq:82",
        "probability": probability,
        "current_probability": current,
        "recorded_probability": current,
        "market_yes": market,
        "outcome": outcome,
        "artifact_hash": f"{variant_id}-artifact",
        "postprocess_config_hash": f"{variant_id}-post",
        "experiment_start_date": "2026-06-15",
    }
    row.update(extra)
    return row


class TestMultiVariantShadow(unittest.TestCase):
    def test_build_payload_scores_daily_first_and_separates_tracks(self):
        rows = [
            _row("exact_catchup", "2026-06-11", 0.80, current=0.60, market=0.70, outcome=1),
            _row("exact_catchup", "2026-06-12", 0.20, current=0.40, market=0.30, outcome=0),
            _row("clob_overlay", "2026-06-11", 0.75, current=0.60, market=0.70, outcome=1, uses_market_features=True),
            _row("clob_overlay", "2026-06-12", 0.25, current=0.40, market=0.30, outcome=0, uses_market_features=True),
        ]

        payload = build_payload(rows)
        variants = {row["variant_id"]: row for row in payload["variants"]}

        self.assertEqual(payload["status"], "OK")
        self.assertEqual(payload["tracks"]["no_market"]["variant_ids"], ["exact_catchup"])
        self.assertEqual(payload["tracks"]["market_informed"]["variant_ids"], ["clob_overlay"])
        self.assertLess(variants["exact_catchup"]["daily_first"]["delta_vs_current"], 0)
        self.assertEqual(variants["exact_catchup"]["daily_first"]["n_days"], 2)
        self.assertEqual(payload["summary"]["unique_observation_count"], 2)
        self.assertEqual(payload["summary"]["scored_rows"], 4)
        self.assertIn("Daily-first scores are the primary comparison", render_report(payload))

    def test_governance_limits_non_control_variants_by_family(self):
        rows = [
            _row(f"variant_{idx}", "2026-06-11", 0.50, outcome=idx % 2)
            for idx in range(5)
        ]

        payload = build_payload(rows, max_non_control_variants=4)

        self.assertEqual(payload["status"], "ERROR")
        self.assertTrue(
            any(issue["category"] == "variant_limit" for issue in payload["governance_issues"])
        )

    def test_missing_metadata_warns_but_scores(self):
        row = _row("missing_meta", "2026-06-11", 0.70)
        row["artifact_hash"] = ""

        payload = build_payload([row])

        self.assertEqual(payload["status"], "WARN")
        self.assertEqual(payload["summary"]["scored_rows"], 1)
        self.assertTrue(
            any(issue["category"] == "variant_metadata" for issue in payload["governance_issues"])
        )

    def test_duplicate_variant_observation_warns(self):
        rows = [
            _row("candidate_control", "2026-06-11", 0.60, is_control=True),
            _row(
                "candidate_control",
                "2026-06-11",
                0.60,
                is_control=True,
                variant_family="bridge_control",
            ),
        ]

        payload = build_payload(rows)
        categories = {issue["category"] for issue in payload["governance_issues"]}

        self.assertEqual(payload["status"], "WARN")
        self.assertIn("duplicate_variant_observation", categories)
        self.assertIn("variant_metadata_conflict", categories)

    def test_duplicate_variant_observation_can_be_error(self):
        rows = [
            _row("candidate_control", "2026-06-11", 0.60, is_control=True),
            _row("candidate_control", "2026-06-11", 0.60, is_control=True),
        ]

        payload = build_payload(rows, duplicate_observation_policy="error")

        self.assertEqual(payload["status"], "ERROR")
        self.assertTrue(
            any(
                issue["category"] == "duplicate_variant_observation"
                and issue["severity"] == "error"
                for issue in payload["governance_issues"]
            )
        )

    def test_dedupes_identical_shared_control_rows_before_governance(self):
        rows = [
            _row("candidate_control", "2026-06-11", 0.60, is_control=True),
            _row(
                "candidate_control",
                "2026-06-11",
                0.60,
                is_control=True,
                variant_family="bridge_control",
            ),
        ]

        payload = build_payload(
            rows,
            dedupe_shared_controls=True,
            duplicate_observation_policy="error",
        )

        self.assertEqual(payload["status"], "OK")
        self.assertEqual(payload["summary"]["scored_rows"], 1)
        self.assertEqual(payload["summary"]["deduplicated_rows"], 1)
        self.assertFalse(payload["governance_issues"])

    def test_variant_registry_separates_active_from_archived_headlines(self):
        registry = {
            "schema_version": "model_variant_registry_v0.1",
            "exists": True,
            "path": "inline",
            "variants": [
                {
                    "variant_id": "active_v",
                    "lifecycle": "active",
                    "track": "no_market",
                    "active_for_headline": True,
                },
                {
                    "variant_id": "archived_v",
                    "lifecycle": "archived",
                    "track": "no_market",
                    "active_for_headline": False,
                },
            ],
            "by_id": {
                "active_v": {
                    "variant_id": "active_v",
                    "lifecycle": "active",
                    "track": "no_market",
                    "active_for_headline": True,
                },
                "archived_v": {
                    "variant_id": "archived_v",
                    "lifecycle": "archived",
                    "track": "no_market",
                    "active_for_headline": False,
                },
            },
        }
        rows = [
            _row("active_v", "2026-06-11", 0.80, current=0.60),
            _row("archived_v", "2026-06-11", 0.70, current=0.60),
        ]

        payload = build_payload(rows, variant_registry=registry)

        self.assertEqual(payload["variant_registry"]["active_headline_variant_ids"], ["active_v"])
        self.assertEqual(payload["summary"]["archived_or_historical_variant_count"], 1)
        self.assertEqual(payload["active_tracks"]["no_market"]["variant_ids"], ["active_v"])

    def test_long_csv_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rows.csv"
            payload = build_payload([_row("exact_catchup", "2026-06-11", 0.80)])
            write_long_csv(path, payload["rows"])
            rows = read_prediction_rows([path])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["variant_id"], "exact_catchup")
        self.assertEqual(rows[0]["band_key"], "eq:82")

    def test_reads_json_object_with_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rows.json"
            path.write_text(json.dumps({"rows": [_row("v1", "2026-06-11", 0.60)]}), encoding="utf-8")
            rows = read_prediction_rows([path])

        self.assertEqual(rows[0]["variant_id"], "v1")


if __name__ == "__main__":
    unittest.main()
