import csv
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from weather.reporting.data_layer_audit import (  # noqa: E402
    build_recommendations,
    build_gates,
    daily_value_rows_from_csv,
    nearby_history_audit,
    scan_snapshot_csv,
    source_status_summary_for_folder,
    season_dates,
)
from weather.sources.supplemental_station_validation import source_fingerprint  # noqa: E402


class TestDataLayerAudit(unittest.TestCase):
    def test_season_dates_respects_requested_bounds(self):
        days = season_dates(date(2025, 6, 29), date(2026, 5, 21))

        self.assertEqual(days[0], date(2025, 6, 29))
        self.assertEqual(days[-1], date(2026, 5, 21))
        self.assertIn(date(2025, 6, 30), days)
        self.assertIn(date(2026, 5, 20), days)
        self.assertNotIn(date(2026, 5, 19), days)

    def test_scan_snapshot_csv_counts_fill_and_missing_token_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshots_long.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["snapshot_id", "market_yes", "best_bid", "clob_token_id"],
                )
                writer.writeheader()
                writer.writerow({
                    "snapshot_id": "s1",
                    "market_yes": "0.4",
                    "best_bid": "",
                    "clob_token_id": "",
                })
                writer.writerow({
                    "snapshot_id": "s1",
                    "market_yes": "0.6",
                    "best_bid": "0.5",
                    "clob_token_id": "123",
                })

            scanned = scan_snapshot_csv(path)

        self.assertEqual(scanned["row_count"], 2)
        self.assertEqual(scanned["nonempty"]["best_bid"], 1)
        self.assertEqual(scanned["rows_with_market_token_ids"], 1)

    def test_daily_value_rows_from_csv_prefers_native_temperature_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "daily_summary.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "local_date",
                        "max_temp_native",
                        "max_temp",
                        "max_temp_c",
                        "max_temp_bucket_native",
                        "max_temp_bucket",
                        "max_temp_bucket_c",
                    ],
                )
                writer.writeheader()
                writer.writerow({
                    "local_date": "2026-06-07",
                    "max_temp_native": "91",
                    "max_temp": "88",
                    "max_temp_c": "33",
                    "max_temp_bucket_native": "91",
                    "max_temp_bucket": "88",
                    "max_temp_bucket_c": "33",
                })

            rows = daily_value_rows_from_csv(path)

        self.assertEqual(rows[date(2026, 6, 7)]["high"], 91.0)
        self.assertEqual(rows[date(2026, 6, 7)]["bucket"], 91)

    def test_recommendations_prioritize_microstructure_and_cadence(self):
        recs = build_recommendations(
            {
                "has_market_token_ids": False,
                "low_fill_fields": [{"field": "best_bid", "fill_rate": 0.45}],
                "artifact_day_counts": {"replay_inputs": 2},
                "folder_count": 3,
            },
            {
                "markets": [
                    {
                        "market_id": "nyc",
                        "sources": {
                            "metar": {
                                "target_season": {
                                    "coverage_rate": 0.5,
                                    "covered_days": 1,
                                    "expected_days": 2,
                                },
                            },
                        },
                    },
                ],
            },
            {"configured_interval_minutes": 10},
        )

        titles = [item["title"] for item in recs]
        self.assertIn("Persist CLOB token IDs and full order-book snapshots", titles)
        self.assertIn("Split weather/model cadence from market-book cadence", titles)
        self.assertIn("Deep-fill redundant historical weather sources for the target season", titles)

    def test_recommendations_respect_managed_clob_loop(self):
        base_snapshot = {
            "has_market_token_ids": True,
            "low_fill_fields": [],
            "artifact_day_counts": {"replay_inputs": 2},
            "folder_count": 3,
        }
        historical = {"markets": []}
        loop = {"configured_interval_minutes": 10}

        running = build_recommendations(
            base_snapshot,
            historical,
            loop,
            {"state": "RUNNING", "status_path": "data/snapshots/clob_loop_status.json"},
        )
        dead = build_recommendations(
            base_snapshot,
            historical,
            loop,
            {"state": "DEAD", "status_path": "data/snapshots/clob_loop_status.json"},
        )

        running_titles = [item["title"] for item in running]
        dead_titles = [item["title"] for item in dead]
        self.assertNotIn("Split weather/model cadence from market-book cadence", running_titles)
        self.assertIn("Start and supervise the CLOB book loop", dead_titles)

    def test_nearby_history_audit_measures_supplemental_coverage_and_bias(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                test_data_root = Path(tmp) / "data"
                spec = SimpleNamespace(id="kxxx", icao="KXXX", lat=10.0, lon=20.0)

                def write_daily(path, rows):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("w", encoding="utf-8", newline="") as handle:
                        writer = csv.DictWriter(handle, fieldnames=["local_date", "max_temp"])
                        writer.writeheader()
                        writer.writerows(rows)

                write_daily(
                    Path("data/noaa_ghcnh/kxxx/daily/daily_summary.csv"),
                    [{"local_date": "2020-05-20", "max_temp": "19.8"}],
                )
                write_daily(
                    Path("data/noaa_ghcnh/kxxx_alt_nearby/daily/daily_summary.csv"),
                    [
                        {"local_date": "2020-05-21", "max_temp": "20.2"},
                        {"local_date": "2020-05-22", "max_temp": "21.0"},
                    ],
                )
                station_path = Path("data/noaa_ghcnh/kxxx_alt_nearby/station.json")
                station_path.write_text(
                    '{"GHCN_ID":"USW00000001","NAME":"Nearby AP","LATITUDE":"10.0","LONGITUDE":"20.0"}\n',
                    encoding="utf-8",
                )
                reference_rows = [
                    {"local_date": "2020-05-21", "max_temp": "20.0"},
                    {"local_date": "2020-05-22", "max_temp": "21.0"},
                ]
                write_daily(Path("data/wunderground/kxxx/daily/daily_summary.csv"), reference_rows)
                write_daily(Path("data/metar/kxxx/daily/daily_summary.csv"), reference_rows)

                expected = [date(2020, 5, 20), date(2020, 5, 21), date(2020, 5, 22)]
                source = {
                    "market_id": "kxxx",
                    "source_id": "ghcnh_kxxx_nearby",
                    "source_type": "noaa_ghcnh",
                    "source_role": "supplemental",
                    "station_id": "USW00000001",
                    "station_name": "Nearby AP",
                    "root_path": str(Path("data/noaa_ghcnh/kxxx_alt_nearby").resolve()),
                    "latitude": 10.0,
                    "longitude": 20.0,
                    "elevation_m": None,
                    "distance_from_canonical_km": 0.0,
                    "canonical_market_id": "kxxx",
                    "canonical_station_id": "KXXX",
                    "validation_status": "candidate",
                    "adopted_date_windows": [{
                        "start": "2020-05-21",
                        "end": "2020-05-22",
                        "reason": "unit test",
                    }],
                    "reason_for_adoption": "unit test registry entry",
                }
                with patch(
                    "weather.reporting.data_layer_audit.data_path",
                    lambda *parts: test_data_root.joinpath(*parts),
                ):
                    out = nearby_history_audit(
                        spec,
                        {"ghcnh": {"target_season": {"covered_days": 1}}},
                        expected,
                        expected,
                        registry={
                            "schema_version": "supplemental_station_registry_v0.1",
                            "sources": [source],
                        },
                        validation_report={
                            "schema_version": "supplemental_station_validation_v0.1",
                            "artifact_path": "unit-test.json",
                            "sources": [{
                                "source_id": "ghcnh_kxxx_nearby",
                                "source_fingerprint": source_fingerprint(source),
                                "promotion_state": "validated_supplemental",
                                "validation_window": {
                                    "start": "2020-05-20",
                                    "end": "2020-05-22",
                                },
                                "validated_weather_regimes": ["mild"],
                                "gates": [{
                                    "name": "distance_from_canonical",
                                    "severity": "hard",
                                    "ok": True,
                                }],
                            }],
                        },
                    )
            finally:
                os.chdir(cwd)

        self.assertEqual(out["composite"]["target_season"]["covered_days"], 3)
        self.assertEqual(out["composite"]["supplemental_target_season_added_days"], 2)
        self.assertEqual(out["supplemental_sources"][0]["source_id"], "ghcnh_kxxx_nearby")
        self.assertEqual(out["supplemental_sources"][0]["source_role"], "supplemental")
        self.assertEqual(out["supplemental_sources"][0]["reason_for_adoption"], "unit test registry entry")
        self.assertEqual(out["supplemental_sources"][0]["station"], "USW00000001")
        self.assertEqual(out["supplemental_sources"][0]["promotion_state"], "validated_supplemental")
        self.assertEqual(out["supplemental_sources"][0]["bias_vs_wu"]["target_season"]["mae"], 0.1)

    def test_recommendations_use_validated_nearby_history_before_deep_fill(self):
        recs = build_recommendations(
            {
                "has_market_token_ids": True,
                "low_fill_fields": [],
                "artifact_day_counts": {"replay_inputs": 1, "source_status": 1},
                "folder_count": 1,
            },
            {
                "markets": [
                    {
                        "market_id": "toronto",
                        "sources": {
                            "ghcnh": {
                                "target_season": {
                                    "coverage_rate": 0.5,
                                    "covered_days": 1,
                                    "expected_days": 2,
                                },
                            },
                        },
                        "nearby_history": {
                            "composite": {
                                "target_season": {
                                    "coverage_rate": 1.0,
                                    "covered_days": 2,
                                    "expected_days": 2,
                                },
                                "supplemental_target_season_added_days": 1,
                            },
                        },
                    },
                ],
            },
            {"configured_interval_minutes": 5},
            {"state": "RUNNING"},
        )

        titles = [item["title"] for item in recs]
        self.assertIn("Promote validated nearby station history as supplemental data", titles)
        self.assertNotIn("Deep-fill redundant historical weather sources for the target season", titles)

    def test_source_status_summary_counts_stale_and_failed_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source_status_long.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["source", "ok", "stale", "status"])
                writer.writeheader()
                writer.writerow({"source": "wu_current", "ok": "True", "stale": "False", "status": "fresh"})
                writer.writerow({"source": "open_meteo", "ok": "True", "stale": "True", "status": "stale_cache"})
                writer.writerow({"source": "metar", "ok": "False", "stale": "False", "status": "failed"})

            summary = source_status_summary_for_folder(tmp)

        self.assertEqual(summary["row_count"], 3)
        self.assertEqual(summary["source_count"], 3)
        self.assertEqual(summary["stale_or_failed_rows"], 2)
        self.assertEqual(summary["status_counts"]["fresh"], 1)

    def test_build_gates_fails_missing_required_artifacts_and_warns_stale_sources(self):
        snapshot = {
            "folder_count": 2,
            "artifact_day_counts": {
                "replay_inputs": 2,
                "source_status": 1,
                "forecasts": 2,
                "forecast_payloads": 1,
            },
            "low_fill_fields": [{"field": "best_bid", "fill_rate": 0.4}],
            "source_status": {
                "row_count": 10,
                "stale_or_failed_rows": 2,
                "stale_or_failed_rate": 0.2,
            },
        }
        historical = {
            "markets": [
                {
                    "sources": {
                        "reanalysis": {"archive_coverage": {"raw_only_normalizable_day_count": 1}},
                        "wu": {"quality": {"quarantined_raw_observations": 1}},
                    },
                },
            ],
        }

        gates = build_gates(snapshot, historical)
        by_name = {row["name"]: row for row in gates}

        self.assertEqual(by_name["snapshot_artifact_replay_input_status"]["status"], "FAIL")
        self.assertEqual(by_name["snapshot_artifact_source_status"]["status"], "WARN")
        self.assertEqual(by_name["forecast_payload_artifact_rate"]["status"], "WARN")
        self.assertEqual(by_name["source_status_stale_or_failed_rate"]["status"], "WARN")
        self.assertEqual(by_name["reanalysis_raw_only_days"]["status"], "WARN")

    def test_build_gates_scopes_snapshot_artifacts_to_training_ready_folders(self):
        snapshot = {
            "folder_count": 2,
            "training_ready_folder_count": 1,
            "artifact_day_counts": {
                "forecasts": 2,
                "clob_features": 2,
                "replay_input_status": 1,
            },
            "artifact_training_ready_day_counts": {
                "forecasts": 1,
                "clob_features": 1,
                "replay_input_status": 1,
            },
            "source_status": {
                "row_count": 1,
                "stale_or_failed_rows": 0,
                "stale_or_failed_rate": 0.0,
            },
        }
        gates = build_gates(snapshot, {"markets": []})
        by_name = {row["name"]: row for row in gates}

        self.assertEqual(by_name["snapshot_artifact_replay_input_status"]["status"], "PASS")
        self.assertIn("training-ready folders", by_name["snapshot_artifact_replay_input_status"]["evidence"])

    def test_build_gates_allows_reanalysis_source_lag_raw_only_days(self):
        snapshot = {
            "folder_count": 1,
            "artifact_day_counts": {
                "replay_input_status": 1,
                "forecasts": 1,
                "clob_features": 1,
                "forecast_payloads": 1,
            },
            "source_status": {
                "row_count": 1,
                "stale_or_failed_rows": 0,
                "stale_or_failed_rate": 0.0,
            },
        }
        historical = {
            "markets": [
                {
                    "sources": {
                        "reanalysis": {
                            "archive_coverage": {
                                "raw_only_normalizable_day_count": 0,
                                "raw_only_source_lag_day_count": 5,
                            },
                        },
                    },
                },
            ],
        }

        gates = build_gates(snapshot, historical)
        by_name = {row["name"]: row for row in gates}

        self.assertEqual(by_name["reanalysis_raw_only_days"]["status"], "PASS")
        self.assertIn("5 raw-only days are all-null source-lag", by_name["reanalysis_raw_only_days"]["evidence"])

    def test_build_gates_fails_unvalidated_supplemental_sources(self):
        snapshot = {
            "folder_count": 1,
            "artifact_day_counts": {
                "replay_input_status": 1,
                "forecasts": 1,
                "clob_features": 1,
                "forecast_payloads": 1,
            },
            "source_status": {
                "row_count": 1,
                "stale_or_failed_rows": 0,
                "stale_or_failed_rate": 0.0,
            },
        }
        historical = {
            "markets": [
                {
                    "market_id": "kxxx",
                    "sources": {},
                    "nearby_history": {
                        "supplemental_sources": [{
                            "source_id": "ghcnh_kxxx_nearby",
                            "promotion_gate": {
                                "ok": False,
                                "promotion_state": "candidate",
                                "reason": "missing current supplemental station validation report",
                            },
                        }],
                    },
                },
            ],
        }

        gates = build_gates(snapshot, historical)
        by_name = {row["name"]: row for row in gates}

        self.assertEqual(by_name["supplemental_station_validation"]["status"], "FAIL")
        self.assertIn("kxxx:ghcnh_kxxx_nearby", by_name["supplemental_station_validation"]["evidence"])

    def test_build_gates_fails_canonical_history_provenance_violations(self):
        snapshot = {
            "folder_count": 1,
            "artifact_day_counts": {
                "replay_input_status": 1,
                "forecasts": 1,
                "clob_features": 1,
                "forecast_payloads": 1,
            },
            "source_status": {
                "row_count": 1,
                "stale_or_failed_rows": 0,
                "stale_or_failed_rate": 0.0,
            },
        }
        historical = {
            "markets": [],
            "canonical_guardrails": {
                "summary": {
                    "status": "FAIL",
                    "violation_count": 2,
                },
            },
        }

        gates = build_gates(snapshot, historical)
        by_name = {row["name"]: row for row in gates}

        self.assertEqual(by_name["canonical_history_provenance"]["status"], "FAIL")
        self.assertIn("2 canonical history", by_name["canonical_history_provenance"]["evidence"])


if __name__ == "__main__":
    unittest.main()
