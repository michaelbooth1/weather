import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.abspath("src"))

from weather.sources.grib_probe import (  # noqa: E402
    GRIB_PROBE_SCHEMA_VERSION,
    GribBoundingBox,
    GribCachePolicy,
    GribToolUnavailable,
    build_nomads_subset_params,
    cache_path_for_request,
    cleanup_grib_cache,
    extract_nearest_with_wgrib2,
    fetch_grib_probe,
    grib_provider_for_url,
    is_grib2,
    normalize_grib_row,
    parse_idx_lines,
    probe_grib_payload,
    select_idx_records,
)


GRIB2_BYTES = b"GRIB\x00\x00\x00\x02tiny-fixture"
IDX_TEXT = (
    "1:0:d=2026061520:TMP:2 m above ground:1 hour fcst:\n"
    "2:1480:d=2026061520:DPT:2 m above ground:1 hour fcst:\n"
    "3:2908:d=2026061520:GUST:surface:1 hour fcst:\n"
)


class TestGribProbe(unittest.TestCase):
    def test_grib2_magic_and_probe_metadata(self):
        self.assertTrue(is_grib2(GRIB2_BYTES))
        self.assertFalse(is_grib2(b"not-grib"))

        payload = probe_grib_payload(
            GRIB2_BYTES,
            source="nomads",
            model="hrrr",
            source_url="https://example.test/hrrr.grib2",
            idx_text=IDX_TEXT,
            run_time="2026-06-15T20:00:00Z",
            forecast_hour=1,
            valid_time="2026-06-15T21:00:00Z",
            grid="conus",
            domain="hrrr",
        )

        self.assertEqual(payload["schema_version"], GRIB_PROBE_SCHEMA_VERSION)
        self.assertEqual(payload["payload_bytes"], len(GRIB2_BYTES))
        self.assertEqual(len(payload["payload_hash"]), 40)
        self.assertEqual(payload["idx_record_count"], 3)
        self.assertEqual(payload["idx_records"][0]["variable"], "TMP")

    def test_idx_parser_filters_and_byte_ranges(self):
        records = parse_idx_lines(IDX_TEXT)

        self.assertEqual(records[0]["byte_offset"], 0)
        self.assertEqual(records[0]["byte_end"], 1479)
        self.assertIsNone(records[-1]["byte_end"])

        selected = select_idx_records(records, variable="TMP", level_contains="2 m")
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["raw_line"], records[0]["raw_line"])

    def test_nomads_subset_params(self):
        params = build_nomads_subset_params(
            file="hrrr.t21z.wrfsfcf00.grib2",
            directory="/hrrr.20260615/conus",
            variables=("TMP", "GUST"),
            levels=("2 m above ground", "surface"),
            bbox=GribBoundingBox(leftlon=-85.0, rightlon=-84.0, toplat=34.0, bottomlat=33.0),
        )

        self.assertEqual(params["file"], "hrrr.t21z.wrfsfcf00.grib2")
        self.assertEqual(params["dir"], "/hrrr.20260615/conus")
        self.assertEqual(params["var_TMP"], "on")
        self.assertEqual(params["var_GUST"], "on")
        self.assertEqual(params["lev_2_m_above_ground"], "on")
        self.assertEqual(params["bottomlat"], 33.0)

    def test_fetch_grib_probe_with_fake_session(self):
        class Response:
            def __init__(self, content=b"", text=""):
                self.content = content
                self.text = text

            def raise_for_status(self):
                return None

        class Session:
            def get(self, url, timeout):
                if url.endswith(".idx"):
                    return Response(text=IDX_TEXT)
                return Response(content=GRIB2_BYTES)

        payload = fetch_grib_probe(
            "https://example.test/file.grib2",
            idx_url="https://example.test/file.grib2.idx",
            session=Session(),
            source="nomads",
            model="nbm",
        )

        self.assertEqual(payload["source"], "nomads")
        self.assertEqual(payload["model"], "nbm")
        self.assertEqual(payload["idx_record_count"], 3)
        self.assertEqual(payload["cache_policy"]["provider"], "nomads")

    def test_provider_policy_detects_public_grib_hosts(self):
        self.assertEqual(grib_provider_for_url("https://nomads.ncep.noaa.gov/cgi-bin/filter_hrrr_2d.pl"), "nomads")
        self.assertEqual(grib_provider_for_url("https://noaa-mrms-pds.s3.amazonaws.com/file.grib2.gz"), "s3")
        self.assertEqual(grib_provider_for_url("https://dd.weather.gc.ca/model_hrdps/file.grib2"), "eccc_datamart")

    def test_fetch_grib_probe_uses_cache_and_provider_pause(self):
        class Response:
            def __init__(self, content=b"", text=""):
                self.content = content
                self.text = text

            def raise_for_status(self):
                return None

        class Session:
            def __init__(self):
                self.calls = []

            def get(self, url, timeout):
                self.calls.append(url)
                if url.endswith(".idx"):
                    return Response(text=IDX_TEXT)
                return Response(content=GRIB2_BYTES)

        pauses = []
        with tempfile.TemporaryDirectory() as tmp:
            session = Session()
            first = fetch_grib_probe(
                "https://nomads.ncep.noaa.gov/file.grib2",
                idx_url="https://nomads.ncep.noaa.gov/file.grib2.idx",
                session=session,
                source="nomads",
                model="hrrr",
                cache_root=tmp,
                sleep_fn=pauses.append,
                now=datetime(2026, 6, 15, tzinfo=timezone.utc),
            )
            second = fetch_grib_probe(
                "https://nomads.ncep.noaa.gov/file.grib2",
                idx_url="https://nomads.ncep.noaa.gov/file.grib2.idx",
                session=session,
                source="nomads",
                model="hrrr",
                cache_root=tmp,
                sleep_fn=pauses.append,
                now=datetime(2026, 6, 15, tzinfo=timezone.utc),
            )

        self.assertEqual(session.calls, [
            "https://nomads.ncep.noaa.gov/file.grib2",
            "https://nomads.ncep.noaa.gov/file.grib2.idx",
        ])
        self.assertEqual(len(pauses), 2)
        self.assertFalse(first["cache_status"]["cache_hit"])
        self.assertTrue(second["cache_status"]["cache_hit"])
        self.assertTrue(second["cache_status"]["idx_cache_hit"])

    def test_cleanup_grib_cache_removes_expired_and_caps_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_path = cache_path_for_request(root, "https://example.test/old.grib2", suffix=".grib2")
            old_path.write_bytes(b"x" * 10)
            fresh_path = cache_path_for_request(root, "https://example.test/fresh.grib2", suffix=".grib2")
            fresh_path.write_bytes(b"y" * 10)
            too_large_path = cache_path_for_request(root, "https://example.test/large.grib2", suffix=".grib2")
            too_large_path.write_bytes(b"z" * 40)
            now = datetime(2026, 6, 15, tzinfo=timezone.utc)
            old_ts = now.timestamp() - 3600
            fresh_ts = now.timestamp()
            os.utime(old_path, (old_ts, old_ts))
            os.utime(fresh_path, (fresh_ts, fresh_ts))
            os.utime(too_large_path, (fresh_ts + 1, fresh_ts + 1))

            result = cleanup_grib_cache(
                root,
                GribCachePolicy(max_age_minutes=10, max_bytes=45, provider_pause_seconds=0, provider="test"),
                now=now,
            )

        self.assertGreaterEqual(result["removed_count"], 2)
        reasons = {row["reason"] for row in result["removed"]}
        self.assertIn("expired", reasons)
        self.assertIn("max_bytes", reasons)
        self.assertLessEqual(result["remaining_bytes"], 45)

    def test_wgrib2_nearest_extraction_uses_runner(self):
        captured = {}

        def fake_runner(command, capture_output, text, timeout):
            captured["command"] = command
            return SimpleNamespace(
                returncode=0,
                stdout="1:0:lon=-84.44 lat=33.63 val=295.25\n",
                stderr="",
            )

        result = extract_nearest_with_wgrib2(
            "tiny.grib2",
            lon=-84.44,
            lat=33.63,
            match=":TMP:2 m above ground:",
            wgrib2_path="wgrib2",
            runner=fake_runner,
        )

        self.assertEqual(result["value"], 295.25)
        self.assertIn("-lon", captured["command"])
        self.assertEqual(captured["command"][-2:], ["-84.44", "33.63"])

    def test_wgrib2_missing_is_explicit(self):
        with patch("weather.sources.grib_probe.shutil.which", return_value=None):
            with self.assertRaises(GribToolUnavailable):
                extract_nearest_with_wgrib2(
                    "tiny.grib2",
                    lon=-84.44,
                    lat=33.63,
                    match=":TMP:2 m above ground:",
                )

    def test_normalized_grib_row_carries_provenance(self):
        row = normalize_grib_row(
            source="nomads",
            model="hrrr",
            field="TMP_2m",
            value=295.25,
            unit="K",
            run_time="2026-06-15T20:00:00Z",
            forecast_hour=1,
            valid_time="2026-06-15T21:00:00Z",
            grid="conus",
            domain="hrrr",
            source_url="https://example.test/file.grib2",
            payload_hash_value="abc123",
            idx_line="1:0:d=2026061520:TMP:2 m above ground:1 hour fcst:",
        )

        self.assertEqual(row["schema_version"], GRIB_PROBE_SCHEMA_VERSION)
        self.assertEqual(row["field"], "TMP_2m")
        self.assertEqual(row["payload_hash"], "abc123")
        self.assertEqual(row["forecast_hour"], 1)


if __name__ == "__main__":
    unittest.main()
