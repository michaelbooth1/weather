import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath("src"))

from market_registry import NYC, TORONTO  # noqa: E402
from weather.sources.asos_one_minute import (  # noqa: E402
    ASOS_1MIN_SCHEMA_VERSION,
    SOURCE,
    AsosOneMinuteStore,
    adoption_gate,
    availability_summary,
    build_iem_1min_params,
    compare_asos_1min_to_wu,
    high_timing_features,
    late_day_lockin_evidence,
    load_daily_summary,
    normalize_iem_1min_csv,
    resolve_iem_1min_station,
)


CSV_TEXT = """station,valid,tmpf,dwpf,sknt,drct,alti
LGA,2025-06-14 16:00,82,61,8,180,29.91
LGA,2025-06-14 16:01,85,62,10,190,29.90
LGA,2025-06-14 16:02,85,62,11,190,29.90
LGA,2025-06-14 16:03,83,62,9,200,29.89
"""


class TestAsosOneMinute(unittest.TestCase):
    def test_station_resolver_omits_leading_k_for_us_markets(self):
        resolved = resolve_iem_1min_station(NYC)

        self.assertTrue(resolved["supported"])
        self.assertEqual(resolved["station"], "LGA")
        self.assertEqual(resolved["icao"], "KLGA")

    def test_station_resolver_records_unsupported_non_us_market(self):
        resolved = resolve_iem_1min_station(TORONTO)

        self.assertFalse(resolved["supported"])
        self.assertIsNone(resolved["station"])
        self.assertIn("US-only", resolved["reason"])

    def test_iem_request_params_include_minute_window(self):
        params = build_iem_1min_params(
            "LGA",
            "2025-06-14T16:00:00+00:00",
            "2025-06-14T18:00:00+00:00",
        )

        self.assertEqual(params["station"], "LGA")
        self.assertEqual(params["hour1"], 16)
        self.assertEqual(params["minute1"], 0)
        self.assertEqual(params["hour2"], 18)
        self.assertEqual(params["vars"], "tmpf,dwpf,sknt,drct,alti")

    def test_normalize_iem_csv_preserves_one_minute_source(self):
        rows = normalize_iem_1min_csv(CSV_TEXT, NYC)

        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["schema_version"], ASOS_1MIN_SCHEMA_VERSION)
        self.assertEqual(rows[0]["source"], SOURCE)
        self.assertEqual(rows[0]["station"], "KLGA")
        self.assertEqual(rows[0]["iem_station"], "LGA")
        self.assertEqual(rows[0]["local_date"], "2025-06-14")
        self.assertEqual(rows[1]["minute_of_day"], 721)
        self.assertEqual(rows[1]["temp_native"], 85.0)
        self.assertEqual(rows[1]["wind_speed_kmh"], 18.52)
        self.assertEqual(len(rows[1]["payload_hash"]), 40)

    def test_availability_summary_counts_temperature_minutes(self):
        rows = normalize_iem_1min_csv(CSV_TEXT, NYC)
        summary = availability_summary(NYC, "2025-06-14", rows, expected_minutes=4)

        self.assertTrue(summary["available"])
        self.assertEqual(summary["row_count"], 4)
        self.assertEqual(summary["temp_row_count"], 4)
        self.assertEqual(summary["coverage_ratio"], 1.0)
        self.assertEqual(summary["first_minute"], 720)
        self.assertEqual(summary["last_minute"], 723)

    def test_availability_summary_keeps_unsupported_reason(self):
        summary = availability_summary(TORONTO, "2025-06-14", [], expected_minutes=4)

        self.assertFalse(summary["available"])
        self.assertFalse(summary["supported"])
        self.assertIn("US-only", summary["reason"])

    def test_high_timing_features_find_short_spike_missed_by_hourly(self):
        rows = normalize_iem_1min_csv(CSV_TEXT, NYC)
        features = high_timing_features(
            rows,
            cutoff_hour=12,
            wall_minute=723,
            hourly_rows=[{"time": "12:00", "temp_native": 83.0}],
        )

        self.assertEqual(features["asos_1min_row_count"], 4)
        self.assertEqual(features["asos_1min_max_so_far"], 85.0)
        self.assertEqual(features["asos_1min_first_reached_minute"], 721)
        self.assertEqual(features["asos_1min_high_duration_minutes"], 2)
        self.assertEqual(features["asos_1min_spike_persistence_minutes"], 2)
        self.assertEqual(features["asos_1min_intrahour_max_since_last_print"], 85.0)
        self.assertEqual(features["asos_1min_minus_hourly_metar_high"], 2.0)

    def test_store_backfill_writes_raw_rows_hourly_daily_and_manifest(self):
        class Client:
            def __init__(self):
                self.calls = []

            def fetch(self, station, start_utc, end_utc):
                self.calls.append((station, start_utc, end_utc))
                return CSV_TEXT

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "nyc"
            store = AsosOneMinuteStore(NYC, root=root)
            result = store.backfill("2025-06-14", "2025-06-14", client=Client())
            daily = load_daily_summary(root, NYC, "2025-06-14")

        self.assertEqual(result["records"], 4)
        self.assertEqual(result["hourly_rows"], 1)
        self.assertEqual(result["daily_rows"], 1)
        self.assertEqual(daily["source"], SOURCE)
        self.assertEqual(float(daily["max_temp_native"]), 85.0)
        self.assertEqual(int(float(daily["first_reached_minute"])), 721)
        self.assertEqual(result["manifest"]["station_resolution"]["station"], "LGA")
        self.assertEqual(result["manifest"]["adoption_gate"]["status"], "DO_NOT_ADOPT")

    def test_header_only_backfill_records_unavailable_day(self):
        class EmptyClient:
            def fetch(self, station, start_utc, end_utc):
                return "station,valid,tmpf,dwpf,sknt,drct,alti\n"

        with tempfile.TemporaryDirectory() as tmp:
            store = AsosOneMinuteStore(NYC, root=Path(tmp) / "nyc")
            result = store.backfill("2025-06-14", "2025-06-14", client=EmptyClient())

        self.assertEqual(result["records"], 0)
        self.assertEqual(result["manifest"]["availability"][0]["local_date"], "2025-06-14")
        self.assertFalse(result["manifest"]["availability"][0]["available"])
        self.assertEqual(result["manifest"]["availability"][0]["reason"], "no one-minute rows with temperature")

    def test_adoption_gate_requires_coverage_bias_agreement_and_lag(self):
        availability = [{"available": True, "coverage_ratio": 0.95}]
        comparison = [{
            "asos_1min_minus_settlement_bucket": 0.0,
            "asos_1min_bucket": 85,
            "settlement_bucket": 85,
            "source_lag_minutes": 15,
        }]

        accepted = adoption_gate(availability, comparison)
        rejected = adoption_gate(availability, [{**comparison[0], "source_lag_minutes": 400}])

        self.assertTrue(accepted["adopt"])
        self.assertEqual(accepted["mean_abs_bias"], 0.0)
        self.assertFalse(rejected["adopt"])
        self.assertIn("source_lag", rejected["reason"])

    def test_late_day_evidence_compares_one_minute_high_to_wu_print_and_settlement(self):
        rows = normalize_iem_1min_csv(CSV_TEXT, NYC)
        comparison = compare_asos_1min_to_wu(
            rows,
            NYC,
            local_date="2025-06-14",
            settlement_bucket=85,
            wu_print_time="2025-06-14T16:10:00+00:00",
        )
        evidence = late_day_lockin_evidence(
            rows,
            NYC,
            local_date="2025-06-14",
            now="2025-06-14T17:30:00+00:00",
            current_reading=83.0,
            settlement_bucket=85,
            wu_print_time="2025-06-14T16:10:00+00:00",
        )

        self.assertEqual(comparison["asos_1min_minus_settlement_bucket"], 0.0)
        self.assertEqual(comparison["asos_1min_minutes_from_first_high_to_wu_print"], 9)
        self.assertTrue(evidence["supports_lockin"])
        self.assertEqual(evidence["stood_minutes"], 89)
        self.assertEqual(evidence["current_minus_asos_1min_high"], -2.0)


if __name__ == "__main__":
    unittest.main()
