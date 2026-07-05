import csv
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from weather.reporting.data_quality.data_layer_audit import (  # noqa: E402
    build_remediation_manifest,
    build_recommendations,
    build_gates,
    daily_value_rows_from_csv,
    nearby_history_audit,
    scan_snapshot_csv,
    sidecar_eligibility_for_folder,
    snapshot_audit,
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
        self.assertIn("Persist model explanation sidecars for root-cause joins", titles)

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

    def test_recommendations_call_out_missing_observation_payloads(self):
        recs = build_recommendations(
            {
                "has_market_token_ids": True,
                "low_fill_fields": [],
                "artifact_day_counts": {
                    "replay_inputs": 1,
                    "source_status": 2,
                    "observation_payloads": 1,
                },
                "folder_count": 2,
            },
            {"markets": []},
            {"configured_interval_minutes": 10},
        )

        titles = [item["title"] for item in recs]
        self.assertIn("Capture raw observation payload sidecars", titles)

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
                    "weather.reporting.data_quality.data_layer_audit.data_path",
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

    def test_nearby_history_audit_scopes_supplemental_gate_to_adopted_window(self):
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

                write_daily(Path("data/noaa_ghcnh/kxxx/daily/daily_summary.csv"), [])
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

                expected = [date(2020, 5, 20), date(2020, 5, 21), date(2020, 5, 22), date(2020, 5, 23)]
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
                with patch("weather.reporting.data_quality.data_layer_audit.data_path", lambda *parts: test_data_root.joinpath(*parts)):
                    out = nearby_history_audit(
                        spec,
                        {"ghcnh": {"target_season": {"covered_days": 0}}},
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
                                    "start": "2020-05-21",
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

        self.assertTrue(out["supplemental_sources"][0]["promotion_gate"]["ok"])

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
            fields = ["source", "ok", "stale", "status", "source_family", "http_status", "degradation_state"]
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow({"source": "wu_current", "ok": "True", "stale": "False", "status": "fresh"})
                writer.writerow({"source": "open_meteo", "ok": "True", "stale": "True", "status": "stale_cache"})
                writer.writerow({"source": "metar", "ok": "False", "stale": "False", "status": "failed"})
                writer.writerow({
                    "source": "wu_history",
                    "ok": "False",
                    "stale": "False",
                    "status": "settlement_source_auth_failure",
                    "source_family": "wu_history",
                    "http_status": "401",
                    "degradation_state": "settlement_source_auth_failure",
                })

            summary = source_status_summary_for_folder(tmp)

        self.assertEqual(summary["row_count"], 4)
        self.assertEqual(summary["source_count"], 4)
        self.assertEqual(summary["stale_or_failed_rows"], 3)
        self.assertEqual(summary["settlement_source_auth_failure_rows"], 1)
        self.assertEqual(summary["settlement_source_auth_failure_sources"], ["wu_history"])
        self.assertEqual(summary["status_counts"]["fresh"], 1)

    def test_recent_auth_failure_markets_scopes_to_newest_data_days(self):
        # Regression (2026-07-03): the fail-closed WU auth gate aggregated the
        # whole folder window, so the repaired June 26-30 outage kept 12
        # markets failing the gate days after auth recovered. The gate list
        # must cover only the newest two data days.
        from weather.reporting.data_quality.data_layer_audit_collectors import (
            _recent_auth_failure_markets,
        )

        folders = [
            {"target_date": "2026-07-02"},
            {"target_date": "2026-07-03"},
        ]

        # Resolved outage: failures ended June 30, data runs through July 3.
        self.assertEqual(
            _recent_auth_failure_markets(
                {"atlanta": "2026-06-30", "nyc": "2026-06-29"}, folders
            ),
            [],
        )
        # Live outage: failure on the newest data day still fails.
        self.assertEqual(
            _recent_auth_failure_markets({"atlanta": "2026-07-03"}, folders),
            ["atlanta"],
        )
        # Yesterday (second newest data day) still counts as live.
        self.assertEqual(
            _recent_auth_failure_markets({"nyc": "2026-07-02"}, folders),
            ["nyc"],
        )
        # Collection outage: no newer folders exist, so the failure days ARE
        # the newest data and the gate stays fail-closed.
        self.assertEqual(
            _recent_auth_failure_markets(
                {"atlanta": "2026-06-30"}, [{"target_date": "2026-06-30"}]
            ),
            ["atlanta"],
        )
        # Missing folder dates: fail closed with the full market list.
        self.assertEqual(
            _recent_auth_failure_markets({"atlanta": "2026-06-30"}, [{}]),
            ["atlanta"],
        )

    def test_snapshot_audit_tracks_raw_clob_artifact_presence(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "highest-temperature-in-nyc-on-june-16-2026"
            folder.mkdir(parents=True)
            with (folder / "snapshots_long.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["snapshot_id", "captured_at_local", "event_slug", "market_yes"],
                )
                writer.writeheader()
                writer.writerow({
                    "snapshot_id": "snap-1",
                    "captured_at_local": "2026-06-16T14:00:00-04:00",
                    "event_slug": folder.name,
                    "market_yes": "0.5",
                })
            (folder / "clob_tokens.csv").write_text("snapshot_id,clob_token_id\nsnap-1,token\n", encoding="utf-8")
            (folder / "order_books.jsonl").write_text('{"snapshot_id":"snap-1"}\n', encoding="utf-8")
            (folder / "clob_capture_status.jsonl").write_text('{"status":"OK"}\n', encoding="utf-8")
            (folder / "snapshot_explanations_long.csv").write_text(
                "snapshot_id,section,item_key\nsnap-1,model_explanation,driver_breakdown\n",
                encoding="utf-8",
            )
            (folder / "observation_payloads_long.csv").write_text(
                "snapshot_id,source,payload_hash\nsnap-1,wu_history,abc\n",
                encoding="utf-8",
            )

            audit = snapshot_audit(snapshots_root=tmp)

        folder_row = audit["folders"][0]
        self.assertTrue(folder_row["artifact_presence"]["clob_capture_status"])
        self.assertTrue(folder_row["artifact_presence"]["clob_tokens"])
        self.assertTrue(folder_row["artifact_presence"]["order_books_raw"])
        self.assertTrue(folder_row["artifact_presence"]["snapshot_explanations"])
        self.assertTrue(folder_row["artifact_presence"]["observation_payloads"])
        self.assertFalse(folder_row["artifact_presence"]["order_books_summary"])
        self.assertEqual(audit["artifact_day_counts"]["clob_capture_status"], 1)
        self.assertEqual(audit["artifact_day_counts"]["clob_tokens"], 1)
        self.assertEqual(audit["artifact_day_counts"]["order_books_raw"], 1)
        self.assertEqual(audit["artifact_day_counts"]["snapshot_explanations"], 1)
        self.assertEqual(audit["artifact_day_counts"]["observation_payloads"], 1)
        self.assertEqual(audit["clob_raw_artifacts"]["capture_status_days"], 1)
        self.assertEqual(audit["clob_raw_artifacts"]["token_artifact_days"], 1)
        self.assertEqual(audit["clob_raw_artifacts"]["raw_book_artifact_days"], 1)

    def test_snapshot_audit_counts_gzip_tiered_order_books_as_raw_clob_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "highest-temperature-in-nyc-on-june-16-2026"
            folder.mkdir(parents=True)
            with (folder / "snapshots_long.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["snapshot_id", "captured_at_local", "event_slug", "market_yes"],
                )
                writer.writeheader()
                writer.writerow({
                    "snapshot_id": "snap-1",
                    "captured_at_local": "2026-06-16T14:00:00-04:00",
                    "event_slug": folder.name,
                    "market_yes": "0.5",
                })
            (folder / "clob_tokens.csv").write_text("snapshot_id,clob_token_id\nsnap-1,token\n", encoding="utf-8")
            (folder / "order_books_long.csv.gz").write_bytes(b"compressed book bytes\n")

            audit = snapshot_audit(snapshots_root=tmp)

        folder_row = audit["folders"][0]
        self.assertTrue(folder_row["artifact_presence"]["order_books_long_gzip"])
        self.assertEqual(audit["artifact_day_counts"]["order_books_long_gzip"], 1)
        self.assertEqual(audit["clob_raw_artifacts"]["raw_book_artifact_days"], 1)

    def test_snapshot_audit_excludes_evaluation_only_replay_status_from_training_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "highest-temperature-in-nyc-on-june-16-2026"
            folder.mkdir(parents=True)
            with (folder / "snapshots_long.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["snapshot_id", "captured_at_local", "event_slug", "market_yes"],
                )
                writer.writeheader()
                writer.writerow({
                    "snapshot_id": "snap-1",
                    "captured_at_local": "2026-06-16T14:00:00-04:00",
                    "event_slug": folder.name,
                    "market_yes": "0.5",
                })
            (folder / "replay_input_status.json").write_text(
                json.dumps({
                    "folder_status": "evaluation_only",
                    "snapshot_count": 1,
                    "evaluation_only_count": 1,
                    "counts": {"evaluation_only": 1},
                }),
                encoding="utf-8",
            )
            with (folder / "replay_input_status_long.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "snapshot_id",
                        "captured_at_utc",
                        "captured_at_local",
                        "event_slug",
                        "replay_input_status",
                        "replay_input_source",
                        "reason",
                    ],
                )
                writer.writeheader()
                writer.writerow({
                    "snapshot_id": "snap-1",
                    "captured_at_utc": "2026-06-16T18:00:00+00:00",
                    "captured_at_local": "2026-06-16T14:00:00-04:00",
                    "event_slug": folder.name,
                    "replay_input_status": "evaluation_only",
                    "replay_input_source": "",
                    "reason": "no captured or reconstructable replay input",
                })

            audit = snapshot_audit(snapshots_root=tmp)

        self.assertEqual(audit["folder_count"], 1)
        self.assertEqual(audit["training_ready_folder_count"], 0)
        self.assertEqual(audit["folders"][0]["training_ready_reason"], "replay_status_evaluation_only")

    def test_snapshot_audit_scopes_artifact_counts_to_sidecar_training_ready_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "highest-temperature-in-nyc-on-june-16-2026"
            folder.mkdir(parents=True)
            with (folder / "snapshots_long.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["snapshot_id", "captured_at_local", "event_slug", "market_yes"],
                )
                writer.writeheader()
                writer.writerow({
                    "snapshot_id": "snap-1",
                    "captured_at_local": "2026-06-16T14:00:00-04:00",
                    "event_slug": folder.name,
                    "market_yes": "0.5",
                })
            (folder / "replay_inputs.jsonl").write_text('{"snapshot_id": "snap-1"}\n', encoding="utf-8")
            (folder / "replay_input_status.json").write_text(
                json.dumps({
                    "folder_status": "captured",
                    "snapshot_count": 1,
                    "captured_count": 1,
                    "counts": {"captured": 1},
                }),
                encoding="utf-8",
            )
            with (folder / "replay_input_status_long.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "snapshot_id",
                        "captured_at_utc",
                        "captured_at_local",
                        "event_slug",
                        "replay_input_status",
                        "replay_input_source",
                        "reason",
                    ],
                )
                writer.writeheader()
                writer.writerow({
                    "snapshot_id": "snap-1",
                    "captured_at_utc": "2026-06-16T18:00:00+00:00",
                    "captured_at_local": "2026-06-16T14:00:00-04:00",
                    "event_slug": folder.name,
                    "replay_input_status": "captured",
                    "replay_input_source": "replay_inputs.jsonl",
                    "reason": "training_ready",
                })

            audit = snapshot_audit(snapshots_root=tmp)

        folder_row = audit["folders"][0]
        self.assertTrue(folder_row["training_ready"])
        self.assertFalse(folder_row["sidecar_eligibility"]["labels"]["training_ready"])
        self.assertEqual(audit["training_ready_folder_count"], 0)
        self.assertEqual(audit["artifact_training_ready_day_counts"], {})

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
                "settlement_source_auth_failure_market_count": 2,
                "settlement_source_auth_failure_markets": ["atlanta", "nyc"],
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
        self.assertEqual(by_name["settlement_source_auth_failure"]["status"], "FAIL")
        self.assertEqual(by_name["reanalysis_raw_only_days"]["status"], "WARN")

    def test_low_fill_gate_counts_only_required_fields(self):
        snapshot = {
            "folder_count": 1,
            "training_ready_folder_count": 1,
            "artifact_day_counts": {
                "replay_input_status": 1,
                "forecasts": 1,
                "forecast_payloads": 1,
                "clob_features": 1,
            },
            "artifact_training_ready_day_counts": {
                "replay_input_status": 1,
                "forecasts": 1,
                "clob_features": 1,
            },
            "low_fill_fields": [
                {"field": "best_bid", "fill_rate": 0.4},
                {"field": "snapshot_cadence_max_gap_seconds", "fill_rate": 0.1},
                {"field": "runtime_git_dirty", "fill_rate": 0.4},
                {"field": "eccc_forecast_high_c", "fill_rate": 0.1},
            ],
            "source_status": {"row_count": 1, "stale_or_failed_rows": 0, "stale_or_failed_rate": 0.0},
        }

        gates = build_gates(snapshot, {"markets": []})
        by_name = {row["name"]: row for row in gates}

        self.assertEqual(by_name["snapshot_low_fill_fields"]["status"], "PASS")
        self.assertIn("0 required fields", by_name["snapshot_low_fill_fields"]["evidence"])

    def test_low_fill_gate_warns_on_required_cadence_fields(self):
        snapshot = {
            "folder_count": 1,
            "training_ready_folder_count": 1,
            "artifact_day_counts": {
                "replay_input_status": 1,
                "forecasts": 1,
                "forecast_payloads": 1,
                "clob_features": 1,
            },
            "artifact_training_ready_day_counts": {
                "replay_input_status": 1,
                "forecasts": 1,
                "clob_features": 1,
            },
            "low_fill_fields": [
                {"field": "snapshot_cadence_quality_state", "fill_rate": 0.4},
                {"field": "best_bid", "fill_rate": 0.4},
            ],
            "source_status": {"row_count": 1, "stale_or_failed_rows": 0, "stale_or_failed_rate": 0.0},
        }

        gates = build_gates(snapshot, {"markets": []})
        by_name = {row["name"]: row for row in gates}

        self.assertEqual(by_name["snapshot_low_fill_fields"]["status"], "WARN")
        self.assertIn("1 required fields", by_name["snapshot_low_fill_fields"]["evidence"])

    def test_quarantine_gate_counts_target_season_quarantines_only(self):
        snapshot = {
            "folder_count": 1,
            "training_ready_folder_count": 1,
            "artifact_day_counts": {
                "replay_input_status": 1,
                "forecasts": 1,
                "forecast_payloads": 1,
                "clob_features": 1,
            },
            "artifact_training_ready_day_counts": {
                "replay_input_status": 1,
                "forecasts": 1,
                "clob_features": 1,
            },
            "low_fill_fields": [],
            "source_status": {"row_count": 1, "stale_or_failed_rows": 0, "stale_or_failed_rate": 0.0},
        }
        historical = {
            "markets": [{
                "sources": {
                    "wu": {
                        "quality": {
                            "quarantined_raw_observations": 6,
                            "target_season_quarantined_raw_observations": 2,
                            "undated_quarantined_raw_observations": 0,
                        }
                    }
                }
            }]
        }

        gates = build_gates(snapshot, historical)
        by_name = {row["name"]: row for row in gates}

        self.assertEqual(by_name["quarantined_impossible_observations"]["status"], "PASS")
        self.assertIn("0 undated raw quarantine", by_name["quarantined_impossible_observations"]["evidence"])
        self.assertIn("2 target-season", by_name["quarantined_impossible_observations"]["evidence"])
        self.assertIn("6 all-history", by_name["quarantined_impossible_observations"]["evidence"])

    def test_build_recommendations_marks_multi_market_settlement_auth_as_p0(self):
        recs = build_recommendations(
            {
                "folder_count": 2,
                "artifact_day_counts": {"source_status": 2, "replay_inputs": 2},
                "source_status": {
                    "settlement_source_auth_failure_market_count": 2,
                    "settlement_source_auth_failure_markets": ["atlanta", "nyc"],
                },
            },
            {"markets": []},
            {},
        )

        by_title = {row["title"]: row for row in recs}
        self.assertEqual(by_title["Fail closed on WU settlement-source auth outage"]["priority"], "P0")

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

    def test_sidecar_eligibility_labels_backfillable_and_market_aware_gaps(self):
        row = {
            "folder": "data/snapshots/highest-temperature-in-nyc-on-june-20-2026",
            "training_ready_reason": "target_date_before_cutoff",
            "artifact_presence": {
                "snapshots_jsonl": True,
                "replay_inputs": True,
                "replay_input_status": True,
                "source_status": True,
                "features": False,
                "components": False,
                "forecasts": True,
                "snapshot_explanations": False,
                "clob_features": False,
                "clob_tokens": True,
                "order_books_summary": True,
                "price_history": True,
                "market_ws_events": False,
            },
            "replay_input_status": {"folder_status": "captured"},
        }

        eligibility = sidecar_eligibility_for_folder(row, settled_scope_ready=True)

        self.assertEqual(eligibility["primary_label"], "replay_only")
        self.assertTrue(eligibility["labels"]["replay_only"])
        self.assertFalse(eligibility["labels"]["training_ready"])
        self.assertIn("missing_features", eligibility["evaluation_only_reasons"])
        self.assertIn("missing_market_ws_events", eligibility["market_aware_exclusion_reasons"])
        commands = {item["artifact"]: item["command"] for item in eligibility["backfill_commands"]}
        self.assertIn("features_components", commands)
        self.assertIn("backfill-core-sidecars", commands["features_components"])
        self.assertIn("snapshot_explanations", commands)

    def test_sidecar_eligibility_marks_observation_payload_gap_non_reconstructable_without_source_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "forecast_payloads_long.csv").write_text(
                "snapshot_id,source,payload_hash\ns1,weather_forecast,h1\n",
                encoding="utf-8",
            )
            row = {
                "folder": str(folder),
                "training_ready_reason": "not_settled_cutoff",
                "artifact_presence": {
                    "snapshots_jsonl": True,
                    "replay_inputs": True,
                    "replay_input_status": True,
                    "source_status": True,
                    "features": True,
                    "components": True,
                    "forecasts": True,
                    "forecast_payloads": True,
                    "observation_payloads": False,
                    "snapshot_explanations": True,
                    "clob_features": True,
                    "clob_tokens": True,
                    "order_books_summary": True,
                    "price_history": True,
                    "market_ws_events": True,
                },
                "replay_input_status": {"folder_status": "captured"},
            }

            eligibility = sidecar_eligibility_for_folder(row, settled_scope_ready=False, active_day=True)

        obs_command = next(
            item for item in eligibility["backfill_commands"]
            if item["artifact"] == "observation_payloads"
        )
        self.assertFalse(obs_command["reconstructable"])
        self.assertIn("restart live snapshot loop", obs_command["command"])

    def test_sidecar_eligibility_blocks_training_for_feature_quality_exclusions(self):
        row = {
            "folder": "data/snapshots/highest-temperature-in-austin-on-june-20-2026",
            "training_ready_reason": "target_date_before_cutoff",
            "artifact_presence": {
                "snapshots_jsonl": True,
                "replay_inputs": True,
                "replay_input_status": True,
                "source_status": True,
                "features": True,
                "components": True,
                "forecasts": True,
                "snapshot_explanations": True,
                "clob_features": True,
                "clob_tokens": True,
                "order_books_summary": True,
                "price_history": True,
                "market_ws_events": True,
                "variant_predictions": True,
            },
            "replay_input_status": {"folder_status": "captured"},
            "feature_quality": {
                "quarantine_row_count": 2,
                "training_excluded_row_count": 2,
                "reason_counts": {"startup_live_observation_implausible": 2},
            },
        }

        eligibility = sidecar_eligibility_for_folder(row, settled_scope_ready=True)

        self.assertFalse(eligibility["labels"]["training_ready"])
        self.assertEqual(eligibility["primary_label"], "replay_only")
        self.assertIn(
            "feature_quality_training_excluded_rows:2",
            eligibility["promotion_exclusion_reasons"],
        )

    def test_build_gates_warns_on_active_day_sidecar_regression(self):
        snapshot = {
            "folder_count": 1,
            "artifact_day_counts": {
                "replay_input_status": 1,
                "forecasts": 1,
                "clob_features": 1,
                "forecast_payloads": 1,
            },
            "sidecar_eligibility": {"active_day_sidecar_regression_count": 1},
            "source_status": {
                "row_count": 1,
                "stale_or_failed_rows": 0,
                "stale_or_failed_rate": 0.0,
            },
        }

        gates = build_gates(snapshot, {"markets": []})
        by_name = {row["name"]: row for row in gates}

        self.assertEqual(by_name["active_day_sidecar_regression"]["status"], "WARN")
        self.assertIn("1 active/future", by_name["active_day_sidecar_regression"]["evidence"])

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

    def test_build_remediation_manifest_classifies_low_fill_and_artifact_gaps(self):
        snapshot = {
            "folder_count": 1,
            "training_ready_folder_count": 1,
            "artifact_training_ready_day_counts": {
                "replay_input_status": 1,
                "forecasts": 1,
                "clob_features": 1,
                "replay_inputs": 0,
            },
            "artifact_day_counts": {
                "replay_input_status": 1,
                "forecasts": 1,
                "clob_features": 1,
                "replay_inputs": 0,
            },
            "low_fill_fields": [
                {"field": "snapshot_cadence_quality_state", "nonempty": 4, "total": 10, "fill_rate": 0.4},
                {"field": "best_bid", "nonempty": 4, "total": 10, "fill_rate": 0.4},
                {"field": "eccc_forecast_high_c", "nonempty": 1, "total": 10, "fill_rate": 0.1},
                {"field": "runtime_git_commit", "nonempty": 4, "total": 10, "fill_rate": 0.4},
            ],
            "folders": [{
                "training_ready": True,
                "market_id": "nyc",
                "target_date": "2026-06-16",
                "folder": "data/snapshots/nyc",
                "artifact_presence": {
                    "replay_inputs": False,
                    "replay_input_status": True,
                    "forecasts": True,
                    "clob_features": True,
                },
            }],
            "source_status": {"row_count": 1, "stale_or_failed_rows": 0, "stale_or_failed_rate": 0.0},
        }
        gates = build_gates(snapshot, {"markets": []})
        manifest = build_remediation_manifest(gates, snapshot, {"markets": []})
        by_gate = {row["gate"]: row for row in manifest}
        low_fields = {
            row["field"]: row["classification"]
            for row in by_gate["snapshot_low_fill_fields"]["affected_fields"]
        }

        self.assertEqual(low_fields["snapshot_cadence_quality_state"], "required")
        self.assertEqual(low_fields["best_bid"], "market_microstructure_optional")
        self.assertEqual(low_fields["eccc_forecast_high_c"], "intentionally_sparse")
        self.assertEqual(low_fields["runtime_git_commit"], "retired")
        self.assertEqual(by_gate["snapshot_artifact_replay_inputs"]["affected_folder_count"], 1)
        self.assertIn("replay_status_backfill", by_gate["snapshot_artifact_replay_inputs"]["command"])


if __name__ == "__main__":
    unittest.main()
