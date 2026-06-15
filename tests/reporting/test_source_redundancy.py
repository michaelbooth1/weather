import csv
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.abspath("src"))

from source_redundancy import (  # noqa: E402
    build_payload,
    forecast_ensemble_features,
    supplemental_source_key,
    truth_csv_rows,
)
from supplemental_station_validation import source_fingerprint  # noqa: E402


def write_daily(root, icao, rows):
    path = Path(root) / icao.lower() / "daily" / "daily_summary.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "schema_version",
                "local_date",
                "temperature_unit",
                "row_count",
                "max_temp",
                "max_temp_bucket",
                "max_temp_times",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "schema_version": "historical_daily_native_v1",
                "temperature_unit": "C",
                "row_count": 24,
                **row,
            })


class TestSourceRedundancy(unittest.TestCase):
    def supplemental_source(self, root):
        return {
            "market_id": "toronto",
            "source_id": "ghcnh_cyyz_nearby",
            "source_type": "noaa_ghcnh",
            "source_role": "supplemental",
            "station_id": "CAN00000001",
            "station_name": "Nearby Toronto",
            "root_path": str(root),
            "latitude": 43.677,
            "longitude": -79.631,
            "elevation_m": 173.0,
            "distance_from_canonical_km": 0.5,
            "canonical_market_id": "toronto",
            "canonical_station_id": "CYYZ",
            "validation_status": "candidate",
            "adopted_date_windows": [{
                "start": "2000-05-20",
                "end": "2000-05-21",
                "reason": "unit test",
            }],
            "reason_for_adoption": "unit test supplemental source",
        }

    def validation_report(self, source):
        return {
            "schema_version": "supplemental_station_validation_v0.1",
            "artifact_path": "unit-test.json",
            "sources": [{
                "source_id": source["source_id"],
                "source_fingerprint": source_fingerprint(source),
                "promotion_state": "validated_supplemental",
                "validation_window": {"start": "2000-05-20", "end": "2000-05-21"},
                "validated_weather_regimes": ["mild"],
                "references": {
                    "wu": {
                        "metrics": {
                            "target_season": {
                                "mean_bias": 0.1,
                                "mae": 0.2,
                                "bucket_match_rate": 0.99,
                            },
                        },
                    },
                },
                "gates": [{"name": "distance_from_canonical", "severity": "hard", "ok": True}],
            }],
        }

    def test_build_payload_fills_missing_wu_from_redundant_source_and_learns_bias(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wu_root = root / "wu"
            metar_root = root / "metar"
            swob_root = root / "swob"
            ghcnh_root = root / "ghcnh"
            reanalysis_root = root / "reanalysis"
            snapshots_root = root / "snapshots"
            snapshots_root.mkdir()

            write_daily(wu_root, "cyyz", [
                {"local_date": "2026-06-01", "max_temp": 20.0, "max_temp_bucket": 20, "max_temp_times": "15:00"},
            ])
            write_daily(ghcnh_root, "cyyz", [
                {"local_date": "2026-06-01", "max_temp": 21.0, "max_temp_bucket": 21, "max_temp_times": "14:00"},
                {"local_date": "2026-06-02", "max_temp": 22.0, "max_temp_bucket": 22, "max_temp_times": "16:00"},
            ])
            write_daily(metar_root, "cyyz", [
                {"local_date": "2026-06-02", "max_temp": 23.0, "max_temp_bucket": 23, "max_temp_times": "15:30"},
            ])
            write_daily(reanalysis_root, "cyyz", [
                {"local_date": "2026-06-02", "max_temp": 21.5, "max_temp_bucket": 22, "max_temp_times": "17:00"},
            ])

            payload = build_payload(
                market_ids=["toronto"],
                start_date=date(2026, 6, 1),
                end_date=date(2026, 6, 2),
                source_roots={
                    "wu": wu_root,
                    "metar": metar_root,
                    "swob": swob_root,
                    "ghcnh": ghcnh_root,
                    "reanalysis": reanalysis_root,
                },
                snapshots_root=snapshots_root,
                disagreement_threshold=0.5,
            )

        market = payload["markets"]["toronto"]
        self.assertEqual(market["summary"]["filled_days"], 1)
        self.assertEqual(market["summary"]["disagreement_alert_days"], 1)
        filled = [row for row in market["daily_truth"] if row["fill_candidate"]]
        self.assertEqual(filled[0]["local_date"], "2026-06-02")
        self.assertEqual(filled[0]["selected_source"], "metar")
        self.assertEqual(filled[0]["selected_bucket"], 23)
        self.assertAlmostEqual(market["source_bias_vs_wu"]["ghcnh"]["bias_source_minus_wu"], 1.0)
        self.assertAlmostEqual(market["source_bias_vs_wu"]["ghcnh"]["mean_peak_time_lead_minutes"], -60.0)
        commands = market["gap_fill"]["refetch_commands"]
        self.assertTrue(any(command["source"] == "wu" and command["start"] == "2026-06-02" for command in commands))

    def test_daily_truth_includes_toronto_swob_and_consensus_high(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wu_root = root / "wu"
            metar_root = root / "metar"
            swob_root = root / "swob"
            ghcnh_root = root / "ghcnh"
            reanalysis_root = root / "reanalysis"
            snapshots_root = root / "snapshots"
            snapshots_root.mkdir()

            write_daily(wu_root, "cyyz", [
                {"local_date": "2026-06-01", "max_temp": 20.0, "max_temp_bucket": 20},
            ])
            write_daily(metar_root, "cyyz", [
                {"local_date": "2026-06-01", "max_temp": 21.0, "max_temp_bucket": 21},
            ])
            write_daily(swob_root, "cyyz", [
                {"local_date": "2026-06-01", "max_temp": 23.0, "max_temp_bucket": 23},
            ])
            write_daily(ghcnh_root, "cyyz", [
                {"local_date": "2026-06-01", "max_temp": 22.0, "max_temp_bucket": 22},
            ])
            write_daily(reanalysis_root, "cyyz", [
                {"local_date": "2026-06-01", "max_temp": 19.0, "max_temp_bucket": 19},
            ])

            payload = build_payload(
                market_ids=["toronto"],
                start_date=date(2026, 6, 1),
                end_date=date(2026, 6, 1),
                source_roots={
                    "wu": wu_root,
                    "metar": metar_root,
                    "swob": swob_root,
                    "ghcnh": ghcnh_root,
                    "reanalysis": reanalysis_root,
                },
                snapshots_root=snapshots_root,
            )

        row = payload["markets"]["toronto"]["daily_truth"][0]
        self.assertEqual(row["schema_version"], "daily_source_truth_v0.3")
        self.assertIn("swob", row["source_values"])
        self.assertEqual(row["source_count"], 5)
        self.assertEqual(row["consensus_source_count"], 5)
        self.assertEqual(row["consensus_high"], 21.0)
        self.assertEqual(row["consensus_bucket"], 21)
        self.assertEqual(
            row["consensus_sources"],
            ["ghcnh", "metar", "reanalysis", "swob", "wu"],
        )
        self.assertAlmostEqual(
            payload["markets"]["toronto"]["source_bias_vs_wu"]["swob"]["bias_source_minus_wu"],
            3.0,
        )
        csv_row = list(truth_csv_rows(payload))[0]
        self.assertEqual(csv_row["consensus_sources"], "ghcnh|metar|reanalysis|swob|wu")

    def test_forecast_ensemble_features_extract_source_count_and_disagreement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "highest-temperature-in-toronto-on-june-2-2026"
            folder.mkdir(parents=True)
            path = folder / "forecasts_long.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "snapshot_id",
                        "captured_at_utc",
                        "captured_at_local",
                        "event_slug",
                        "target_date",
                        "source",
                        "forecast_high_native",
                        "forecast_high_c",
                        "target_temp_native",
                        "target_temp_c",
                    ],
                )
                writer.writeheader()
                writer.writerow({
                    "snapshot_id": "s1",
                    "captured_at_local": "2026-06-02T09:00:00-04:00",
                    "event_slug": folder.name,
                    "target_date": "2026-06-02",
                    "source": "open_meteo",
                    "forecast_high_native": "",
                    "forecast_high_c": "",
                    "target_temp_native": 84.0,
                    "target_temp_c": 24.0,
                })
                writer.writerow({
                    "snapshot_id": "s1",
                    "captured_at_local": "2026-06-02T09:00:00-04:00",
                    "event_slug": folder.name,
                    "target_date": "2026-06-02",
                    "source": "weather_forecast",
                    "forecast_high_native": "",
                    "forecast_high_c": "",
                    "target_temp_native": 86.0,
                    "target_temp_c": 26.0,
                })

            rows = forecast_ensemble_features(snapshots_root=root, market_ids=["toronto"])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["forecast_source_count"], 2)
        self.assertEqual(rows[0]["ensemble_forecast_high"], 85.0)
        self.assertEqual(rows[0]["forecast_disagreement"], 2.0)

    def test_validated_supplemental_features_do_not_replace_truth_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wu_root = root / "wu"
            metar_root = root / "metar"
            swob_root = root / "swob"
            ghcnh_root = root / "ghcnh"
            reanalysis_root = root / "reanalysis"
            supplemental_root = root / "supplemental"
            snapshots_root = root / "snapshots"
            snapshots_root.mkdir()

            write_daily(wu_root, "cyyz", [
                {"local_date": "2000-05-20", "max_temp": 20.0, "max_temp_bucket": 20},
            ])
            write_daily(supplemental_root, "", [
                {"local_date": "2000-05-20", "max_temp": 20.2, "max_temp_bucket": 20},
                {"local_date": "2000-05-21", "max_temp": 21.0, "max_temp_bucket": 21},
            ])
            source = self.supplemental_source(supplemental_root)
            payload = build_payload(
                market_ids=["toronto"],
                start_date=date(2000, 5, 20),
                end_date=date(2000, 5, 21),
                source_roots={
                    "wu": wu_root,
                    "metar": metar_root,
                    "swob": swob_root,
                    "ghcnh": ghcnh_root,
                    "reanalysis": reanalysis_root,
                },
                registry={"schema_version": "supplemental_station_registry_v0.1", "sources": [source]},
                supplemental_validation_report=self.validation_report(source),
                snapshots_root=snapshots_root,
            )

        market = payload["markets"]["toronto"]
        rows = market["daily_truth"]
        source_key = supplemental_source_key(source)

        self.assertEqual(rows[0]["selected_source"], "wu")
        self.assertTrue(rows[0]["supplemental_source_available"])
        self.assertEqual(rows[0]["supplemental_source_ids"], ["ghcnh_cyyz_nearby"])
        self.assertAlmostEqual(rows[0]["supplemental_same_day_delta_vs_primary"], 0.2)
        self.assertTrue(rows[0]["supplemental_same_day_bucket_match"])
        self.assertFalse(rows[0]["source_values"][source_key]["live_serving_eligible"])
        self.assertTrue(rows[0]["source_values"][source_key]["historical_only_feature"])

        self.assertEqual(rows[1]["status"], "missing_all_sources")
        self.assertIsNone(rows[1]["selected_source"])
        self.assertFalse(rows[1]["fill_candidate"])
        self.assertNotIn(source_key, market["source_bias_vs_wu"])
        self.assertIn(source_key, market["supplemental_source_bias_vs_wu"])
        self.assertEqual(market["summary"]["supplemental_source_days"], 2)
        self.assertEqual(market["summary"]["supplemental_same_day_primary_overlap_days"], 1)

        feature_summary = payload["supplemental_nearby_features"]["markets"][0]
        self.assertTrue(feature_summary["historical_only"])
        self.assertFalse(feature_summary["live_serving_eligible"])
        self.assertEqual(feature_summary["two_plus_source_day_delta"], 1)
        self.assertEqual(feature_summary["redundant_source_day_delta"], 2)
        parity = payload["supplemental_nearby_features"]["train_serve_parity"]
        self.assertEqual(parity["status"], "historical_only_excluded_from_live_serving")
        self.assertEqual(parity["serving_columns"], [])
        self.assertIn("supplemental_source_available", parity["training_columns"])
        ablation = payload["supplemental_nearby_features"]["ablation"]
        self.assertEqual(ablation["status"], "diagnostic_ablation_ready")
        self.assertEqual(
            ablation["settlement_scored_replay_status"],
            "not_run_historical_only_excluded_from_live_serving",
        )
        csv_row = list(truth_csv_rows(payload))[0]
        self.assertEqual(csv_row["supplemental_source_ids"], "ghcnh_cyyz_nearby")


if __name__ == "__main__":
    unittest.main()
