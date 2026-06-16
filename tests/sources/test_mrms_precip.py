import gzip
import os
import sys
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from weather.market.market_registry import spec_for_id  # noqa: E402
from weather.sources.mrms_precip import (  # noqa: E402
    MRMS_DEFAULT_PRODUCT,
    build_mrms_listing_url,
    build_mrms_object_key,
    build_mrms_object_url,
    build_mrms_backfill_feature_rows,
    derive_mrms_precip_features,
    extract_mrms_nearest_precip_row,
    fetch_mrms_precip_for_market,
    normalize_mrms_precip_row,
    parse_mrms_key_time,
    parse_s3_listing,
    probe_mrms_grib_payload,
    render_mrms_score_markdown,
    score_mrms_interruption_cases,
    select_recent_objects,
)


S3_LISTING = """<?xml version="1.0" encoding="UTF-8"?>
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
  <Contents>
    <Key>CONUS/PrecipRate_00.00/20260615/MRMS_PrecipRate_00.00_20260615-121800.grib2.gz</Key>
    <LastModified>2026-06-15T12:19:00.000Z</LastModified>
    <Size>1234</Size>
  </Contents>
  <Contents>
    <Key>CONUS/PrecipRate_00.00/20260615/MRMS_PrecipRate_00.00_20260615-122000.grib2.gz</Key>
    <LastModified>2026-06-15T12:21:00.000Z</LastModified>
    <Size>1300</Size>
  </Contents>
</ListBucketResult>
"""


class TestMrmsPrecip(unittest.TestCase):
    def test_mrms_key_url_and_listing_helpers(self):
        valid = datetime(2026, 6, 15, 12, 18, tzinfo=timezone.utc)
        key = build_mrms_object_key(MRMS_DEFAULT_PRODUCT, valid)
        url = build_mrms_object_url(MRMS_DEFAULT_PRODUCT, valid)
        listing_url = build_mrms_listing_url(MRMS_DEFAULT_PRODUCT, "2026-06-15")
        parsed = parse_mrms_key_time(key)
        objects = parse_s3_listing(S3_LISTING)

        self.assertEqual(
            key,
            "CONUS/PrecipRate_00.00/20260615/MRMS_PrecipRate_00.00_20260615-121800.grib2.gz",
        )
        self.assertTrue(url.endswith(key))
        self.assertIn("prefix=CONUS%2FPrecipRate_00.00%2F20260615%2F", listing_url)
        self.assertEqual(parsed["valid_time_utc"], "2026-06-15T12:18:00+00:00")
        self.assertEqual(len(objects), 2)
        self.assertEqual(objects[-1]["size_bytes"], 1300)

    def test_recent_object_selection_and_source_lag_payload(self):
        objects = parse_s3_listing(S3_LISTING)
        recent = select_recent_objects(
            objects,
            now=datetime(2026, 6, 15, 12, 21, tzinfo=timezone.utc),
            lookback_minutes=5,
        )
        lagged = fetch_mrms_precip_for_market(
            spec_for_id("nyc"),
            "2026-06-15",
            get_text=lambda _url: S3_LISTING,
            now=datetime(2026, 6, 15, 12, 50, tzinfo=timezone.utc),
            lookback_minutes=5,
        )

        self.assertEqual(len(recent), 2)
        self.assertFalse(lagged["available"])
        self.assertIn("source lag", lagged["reason"])
        self.assertEqual(lagged["latest_object_age_minutes"], 30.0)
        self.assertEqual(lagged["recent_objects"], [])

    def test_probe_compressed_mrms_grib_payload_uses_grib_probe(self):
        raw_grib2 = b"GRIB\x00\x00\x00\x02payload"
        compressed = gzip.compress(raw_grib2)
        key = build_mrms_object_key(
            MRMS_DEFAULT_PRODUCT,
            datetime(2026, 6, 15, 12, 18, tzinfo=timezone.utc),
        )

        probe = probe_mrms_grib_payload(
            compressed,
            source_url="https://example.test/" + key,
            object_key=key,
        )

        self.assertEqual(probe["schema_version"], "mrms_precip_v0.1")
        self.assertEqual(probe["source"], "mrms_precip")
        self.assertEqual(probe["model"], "MRMS")
        self.assertEqual(probe["grib_edition"], 2)
        self.assertEqual(probe["payload_bytes"], len(raw_grib2))
        self.assertEqual(probe["compressed_payload_bytes"], len(compressed))

    def test_extract_nearest_precip_row_uses_wgrib2_foundation(self):
        spec = spec_for_id("nyc")
        captured = {}

        def fake_runner(command, capture_output, text, timeout):
            captured["command"] = command
            return SimpleNamespace(returncode=0, stdout="1:0:lon=-73.87 lat=40.77 val=7.5\n", stderr="")

        row = extract_mrms_nearest_precip_row(
            spec,
            "tiny.grib2",
            "2026-06-15T16:25:00+00:00",
            source_url="https://example.test/mrms.grib2.gz",
            object_key="CONUS/PrecipRate_00.00/20260615/MRMS_PrecipRate_00.00_20260615-162500.grib2.gz",
            wgrib2_path="wgrib2",
            runner=fake_runner,
        )

        self.assertEqual(row["precip_rate_mm_per_hr"], 7.5)
        self.assertTrue(row["precip_detected"])
        self.assertEqual(row["extraction"]["method"], "wgrib2_lon")
        self.assertIn("-lon", captured["command"])

    def test_normalize_rows_and_rolling_features(self):
        spec = spec_for_id("nyc")
        rows = [
            normalize_mrms_precip_row(spec, "2026-06-15T12:00:00+00:00", precip_rate_mm_per_hr=0.0),
            normalize_mrms_precip_row(spec, "2026-06-15T16:25:00+00:00", precip_rate_mm_per_hr=12.0),
            normalize_mrms_precip_row(spec, "2026-06-15T16:55:00+00:00", precip_rate_mm_per_hr=6.0),
        ]
        # NYC local time is UTC-4 on this date: 16:55 UTC -> 12:55 local.
        features = derive_mrms_precip_features(
            {"rows": rows, "latest_object_age_minutes": 4.0},
            cutoff_hour=12,
            wall_minute=12 * 60 + 55,
            forecast_next_3h_cape_max=800.0,
            forecast_next_3h_precip_probability_max=20.0,
            warming_rate_2h=1.0,
        )

        self.assertEqual(rows[-1]["minute_of_day"], 12 * 60 + 55)
        self.assertEqual(features["mrms_row_count"], 3.0)
        self.assertEqual(features["mrms_source_lag_minutes"], 4.0)
        self.assertEqual(features["mrms_any_precip_last_15m"], 1.0)
        self.assertEqual(features["mrms_any_precip_last_30m"], 1.0)
        self.assertEqual(features["mrms_any_precip_last_60m"], 1.0)
        self.assertAlmostEqual(features["mrms_precip_since_cutoff_mm"], 0.6)
        self.assertEqual(features["mrms_max_rate_peak_heating_mm_per_hr"], 12.0)
        self.assertEqual(features["mrms_max_rate_since_cutoff_mm_per_hr"], 12.0)
        self.assertEqual(features["mrms_convective_interruption"], 1.0)

    def test_backfill_feature_rows_preserve_product_version_and_archive_warning(self):
        spec = spec_for_id("nyc")
        rows = [
            normalize_mrms_precip_row(
                spec,
                "2026-06-15T16:25:00+00:00",
                precip_rate_mm_per_hr=12.0,
                object_key="object-a",
            )
        ]

        backfill = build_mrms_backfill_feature_rows(
            spec,
            {"2026-06-15": rows},
            "2026-06-15",
            "2026-06-16",
        )

        self.assertTrue(backfill[0]["archive_available"])
        self.assertEqual(backfill[0]["product_version"], "MRMS_CONUS_precip_rate_public_s3")
        self.assertEqual(backfill[0]["object_keys"], ["object-a"])
        self.assertIn("pre/post-upgrade", backfill[0]["archive_warning"])
        self.assertFalse(backfill[1]["archive_available"])
        self.assertEqual(backfill[1]["mrms_row_count"], 0.0)

    def test_score_report_groups_forecast_overcall_late_day_and_market_move_cases(self):
        payload = score_mrms_interruption_cases([
            {
                "market": "nyc",
                "features": {"mrms_convective_interruption": 1.0},
                "forecast_overcall_error": 2.0,
                "late_day_continuation_failed": True,
                "market_moved_after_storm": True,
                "market_move_after_storm_bps": 120,
            },
            {
                "market": "nyc",
                "features": {"mrms_convective_interruption": 0.0},
                "forecast_overcall_error": 0.0,
            },
        ])
        by_case = {row["case_type"]: row for row in payload["cases"]}
        markdown = render_mrms_score_markdown(payload)

        self.assertEqual(payload["summary"]["rows"], 2)
        self.assertEqual(payload["summary"]["interruption_rows"], 1)
        self.assertEqual(by_case["forecast_overcall"]["mrms_interruption_rate"], 1.0)
        self.assertEqual(by_case["late_day_continuation_failed"]["mean_market_move_after_storm_bps"], 120.0)
        self.assertIn("market_moved_after_storm", markdown)

    def test_non_us_market_returns_explicit_unavailable_metadata(self):
        payload = fetch_mrms_precip_for_market(
            spec_for_id("toronto"),
            "2026-06-15",
            get_text=lambda _url: S3_LISTING,
            now=datetime(2026, 6, 15, 12, 21, tzinfo=timezone.utc),
        )

        self.assertFalse(payload["available"])
        self.assertIn("US-only", payload["reason"])
        self.assertEqual(payload["rows"], [])


if __name__ == "__main__":
    unittest.main()
