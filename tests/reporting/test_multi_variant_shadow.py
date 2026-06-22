import csv
import json
import tempfile
import unittest
from pathlib import Path

from weather.reporting.multi_variant_shadow import (
    ATTRIBUTION_SCHEMA_VERSION,
    attribution_sidecar_rows,
    build_payload,
    read_prediction_rows,
    render_report,
    write_attribution_sidecar,
    write_json,
    write_long_csv,
    write_report,
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

        payload = build_payload(rows, use_variant_registry=False)
        variants = {row["variant_id"]: row for row in payload["variants"]}

        self.assertEqual(payload["status"], "OK")
        self.assertEqual(payload["tracks"]["no_market"]["variant_ids"], ["exact_catchup"])
        self.assertEqual(payload["tracks"]["market_informed"]["variant_ids"], ["clob_overlay"])
        self.assertEqual(payload["claim_lanes"]["weather_only_core_model"]["rows"], 2)
        self.assertEqual(payload["claim_lanes"]["market_informed_quote_risk"]["rows"], 2)
        self.assertEqual(
            payload["claim_lanes"]["weather_only_core_model"]["counts_toward_weather_model_promotion_rows"],
            2,
        )
        self.assertEqual(
            payload["claim_lanes"]["market_informed_quote_risk"]["counts_toward_weather_model_promotion_rows"],
            0,
        )
        self.assertLess(variants["exact_catchup"]["daily_first"]["delta_vs_current"], 0)
        self.assertEqual(variants["exact_catchup"]["daily_first"]["n_days"], 2)
        self.assertEqual(payload["summary"]["unique_observation_count"], 2)
        self.assertEqual(payload["summary"]["scored_rows"], 4)
        report = render_report(payload)
        self.assertIn("Daily-first scores are the primary comparison", report)
        self.assertIn("Claim Lane Separation", report)
        self.assertIn("market_informed_quote_risk", report)

    def test_governance_limits_non_control_variants_by_family(self):
        rows = [
            _row(f"variant_{idx}", "2026-06-11", 0.50, outcome=idx % 2)
            for idx in range(5)
        ]

        payload = build_payload(rows, max_non_control_variants=4, use_variant_registry=False)

        self.assertEqual(payload["status"], "ERROR")
        self.assertTrue(
            any(issue["category"] == "variant_limit" for issue in payload["governance_issues"])
        )

    def test_missing_metadata_warns_but_scores(self):
        row = _row("missing_meta", "2026-06-11", 0.70)
        row["artifact_hash"] = ""

        payload = build_payload([row], use_variant_registry=False)

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

        payload = build_payload(rows, use_variant_registry=False)
        categories = {issue["category"] for issue in payload["governance_issues"]}

        self.assertEqual(payload["status"], "WARN")
        self.assertIn("duplicate_variant_observation", categories)
        self.assertIn("variant_metadata_conflict", categories)

    def test_duplicate_variant_observation_can_be_error(self):
        rows = [
            _row("candidate_control", "2026-06-11", 0.60, is_control=True),
            _row("candidate_control", "2026-06-11", 0.60, is_control=True),
        ]

        payload = build_payload(rows, duplicate_observation_policy="error", use_variant_registry=False)

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
            use_variant_registry=False,
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

    def test_variant_registry_missing_active_variant_warns(self):
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
                    "variant_id": "missing_v",
                    "lifecycle": "active",
                    "track": "no_market",
                    "active_for_headline": True,
                },
            ],
            "by_id": {
                "active_v": {
                    "variant_id": "active_v",
                    "lifecycle": "active",
                    "track": "no_market",
                    "active_for_headline": True,
                },
                "missing_v": {
                    "variant_id": "missing_v",
                    "lifecycle": "active",
                    "track": "no_market",
                    "active_for_headline": True,
                },
            },
        }

        payload = build_payload([_row("active_v", "2026-06-11", 0.80)], variant_registry=registry)

        self.assertEqual(payload["status"], "WARN")
        self.assertEqual(payload["variant_registry"]["missing_active_headline_variant_ids"], ["missing_v"])
        self.assertTrue(
            any(issue["category"] == "active_registry_variant_missing" for issue in payload["governance_issues"])
        )

    def test_extra_location_track_is_shadow_only_and_excluded_from_headline(self):
        registry = {
            "schema_version": "model_variant_registry_v0.1",
            "exists": True,
            "path": "inline",
            "variants": [
                {
                    "variant_id": "ordinary_v",
                    "lifecycle": "active",
                    "track": "no_market",
                    "active_for_headline": True,
                },
                {
                    "variant_id": "extra_v",
                    "lifecycle": "shadow",
                    "track": "no_market_extra_locations",
                    "active_for_headline": False,
                },
            ],
            "by_id": {
                "ordinary_v": {
                    "variant_id": "ordinary_v",
                    "lifecycle": "active",
                    "track": "no_market",
                    "active_for_headline": True,
                },
                "extra_v": {
                    "variant_id": "extra_v",
                    "lifecycle": "shadow",
                    "track": "no_market_extra_locations",
                    "active_for_headline": False,
                },
            },
        }
        rows = [
            _row("ordinary_v", "2026-06-11", 0.80, current=0.60),
            _row(
                "extra_v",
                "2026-06-11",
                0.85,
                current=0.60,
                used_extra_location_labels=True,
                extra_location_ids="boston,philadelphia",
                target_local_labels_present=True,
                extra_location_gate_status="BLOCK",
                extra_location_gate_reason="target-plus-extra regressed target-only",
            ),
        ]

        payload = build_payload(rows, variant_registry=registry)

        self.assertEqual(payload["tracks"]["no_market_extra_locations"]["variant_ids"], ["extra_v"])
        self.assertEqual(payload["extra_location_shadow_lane"]["status"], "BLOCK")
        self.assertEqual(payload["headline_selection"]["selected_variant_id"], "ordinary_v")
        self.assertTrue(
            any(issue["category"] == "extra_location_transfer_gate" for issue in payload["governance_issues"])
        )
        self.assertIn("No-Market Extra-Location Shadow Lane", render_report(payload))

    def test_long_csv_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rows.csv"
            payload = build_payload([_row("exact_catchup", "2026-06-11", 0.80)], use_variant_registry=False)
            write_long_csv(path, payload["rows"])
            rows = read_prediction_rows([path])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["variant_id"], "exact_catchup")
        self.assertEqual(rows[0]["band_key"], "eq:82")

    def test_output_writers_fail_before_creating_files_when_headroom_is_low(self):
        payload = build_payload([_row("exact_catchup", "2026-06-11", 0.80)], use_variant_registry=False)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = {
                "long": root / "rows.csv",
                "sidecar": root / "rows.jsonl",
                "json": root / "payload.json",
                "report": root / "report.md",
            }

            with self.assertRaises(OSError):
                write_long_csv(paths["long"], payload["rows"], min_free_bytes=10**18)
            with self.assertRaises(OSError):
                write_attribution_sidecar(paths["sidecar"], payload["rows"], min_free_bytes=10**18)
            with self.assertRaises(OSError):
                write_json(paths["json"], payload, min_free_bytes=10**18)
            with self.assertRaises(OSError):
                write_report(paths["report"], payload, min_free_bytes=10**18)

            for path in paths.values():
                self.assertFalse(path.exists())

    def test_attribution_extension_round_trips_and_reports_slices(self):
        raw = _row(
            "diagnostic_v",
            "2026-06-11",
            0.80,
            current=0.60,
            source_freshness_state="stale:open_meteo",
            settlement_distance_bucket="0",
            cutoff_regime="early",
            casebook_taxonomy="market_lead",
            feature_schema_version="toronto_feature_store_v1.6",
            feature_family_hash="feature-hash",
            feature_missingness_hash="missingness-hash",
            clob_feature_available=1.0,
            clob_midpoint=0.72,
            uses_market_features=True,
            claim_lane="market_informed_quote_risk",
            counts_toward_weather_model_promotion=False,
            quote_risk_eligible=True,
            quote_risk_gate_reason="allowed taxonomy: market_lead",
        )

        payload = build_payload([raw], use_variant_registry=False)
        row = payload["rows"][0]
        report = render_report(payload)
        sidecar = attribution_sidecar_rows(payload["rows"])

        self.assertEqual(row["attribution_schema_version"], ATTRIBUTION_SCHEMA_VERSION)
        self.assertEqual(row["source_freshness_state"], "stale:open_meteo")
        self.assertEqual(row["claim_lane"], "market_informed_quote_risk")
        self.assertFalse(row["counts_toward_weather_model_promotion"])
        self.assertTrue(row["quote_risk_eligible"])
        self.assertEqual(row["quote_risk_gate_reason"], "allowed taxonomy: market_lead")
        self.assertEqual(payload["attribution"]["attributed_row_count"], 1)
        self.assertEqual(payload["claim_lanes"]["market_informed_quote_risk"]["quote_risk_eligible_rows"], 1)
        self.assertEqual(payload["variants"][0]["by_source_freshness"][0]["group"], "stale:open_meteo")
        self.assertEqual(payload["variants"][0]["by_settlement_distance"][0]["group"], "0")
        self.assertEqual(payload["variants"][0]["by_casebook_taxonomy"][0]["group"], "market_lead")
        self.assertEqual(sidecar[0]["feature_family_hash"], "feature-hash")
        self.assertEqual(sidecar[0]["attribution"]["casebook_taxonomy"], "market_lead")
        self.assertIn("Attribution Slices", report)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rows.csv"
            write_long_csv(path, payload["rows"])
            round_trip = build_payload(read_prediction_rows([path]), use_variant_registry=False)

        self.assertEqual(round_trip["rows"][0]["source_freshness_state"], "stale:open_meteo")
        self.assertEqual(round_trip["rows"][0]["casebook_taxonomy"], "market_lead")
        self.assertEqual(round_trip["rows"][0]["claim_lane"], "market_informed_quote_risk")
        self.assertTrue(round_trip["rows"][0]["quote_risk_eligible"])

    def test_reads_json_object_with_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rows.json"
            path.write_text(json.dumps({"rows": [_row("v1", "2026-06-11", 0.60)]}), encoding="utf-8")
            rows = read_prediction_rows([path])

        self.assertEqual(rows[0]["variant_id"], "v1")


if __name__ == "__main__":
    unittest.main()
