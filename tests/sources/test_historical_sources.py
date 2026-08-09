import csv
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import requests
from weather.collection.historical_backfill_plan import build_plan, split_ranges
from weather.market.market_registry import ATLANTA, NYC, TORONTO
from weather.sources.historical_coverage import coverage_dashboard, fleet_coverage, write_dashboard_outputs
from weather.sources.forecast_history import (
    DEFAULT_HISTORY_WINDOW_DAYS,
    DEFAULT_TARGET_WINDOW_DAYS,
    FORECAST_HISTORY_COVERAGE_SCHEMA_VERSION,
    RICH_FORECAST_COLUMNS,
    archive_window_for_target,
    backfill,
    daily_issue_rows,
    forecast_history_coverage,
    forecast_history_fleet_coverage,
    historical_forecast_rows,
    load_forecast_daily,
    load_forecast_profiles,
    render_forecast_history_coverage_markdown,
    previous_run_rows,
    target_window_contract,
    write_csv,
)
from weather.sources.noaa_ghcnh_history import GHCNHStore, normalize_psv, resolve_station
from weather.sources.reanalysis_history import (
    RICH_REANALYSIS_HOURLY_VARIABLES,
    ReanalysisStore,
    normalize_payload,
)
from weather.sources.supplemental_stations import SupplementalStationRegistryError, guard_not_canonical_root
from weather.sources.wu_history import (
    AUTH_FAILURE,
    PERMANENT_NO_DATA,
    PUBLIC_WU_HISTORY_SOURCE,
    RATE_LIMITED,
    TRANSIENT_FAILURE,
    PublicWundergroundHistoryClient,
    WundergroundHistoryClient,
    WundergroundHistoryStore,
    normalize_observation,
    redact_api_key,
    summarize_daily,
)


GHCNH_SAMPLE = """STATION|Station_name|DATE|Year|Month|Day|Hour|Minute|LATITUDE|LONGITUDE|ELEVATION|temperature|temperature_Quality_Code|temperature_Report_Type|dew_point_temperature|dew_point_temperature_Quality_Code|station_level_pressure|sea_level_pressure|wind_direction|wind_speed|relative_humidity
USW00014732|LAGUARDIA AP|2023-06-01T12:51:00|2023|06|01|12|51|40.78|-73.88|3.0|23.3||FM-15|12.0||1010.1|1012.4|180|9.3|49
USW00014732|LAGUARDIA AP|2023-06-01T13:51:00|2023|06|01|13|51|40.78|-73.88|3.0|25.0||FM-15|13.0||1009.1|1011.4|190|11.1|47
"""
FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures"


class TestHistoricalSources(unittest.TestCase):
    def supplemental_registry(self, root, market_id="nyc"):
        return {
            "schema_version": "supplemental_station_registry_v0.1",
            "sources": [{
                "market_id": market_id,
                "source_id": "ghcnh_test_supplemental",
                "source_type": "noaa_ghcnh",
                "source_role": "supplemental",
                "station_id": "USW00014732",
                "station_name": "LAGUARDIA AP",
                "root_path": str(root),
                "latitude": 40.78,
                "longitude": -73.88,
                "elevation_m": 3.0,
                "distance_from_canonical_km": 0.42,
                "canonical_market_id": market_id,
                "canonical_station_id": "KLGA",
                "validation_status": "candidate",
                "adopted_date_windows": [{
                    "start": "2023-06-01",
                    "end": "2023-06-01",
                    "reason": "unit test",
                }],
                "reason_for_adoption": "unit test supplemental source",
            }],
        }

    def test_wu_manifest_summarizes_quarantined_raw_observation_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WundergroundHistoryStore(
                tmp,
                station_icao="KLGA",
                station_name="New York",
                history_id="KLGA:9:US",
                unit="F",
            )
            store.write_manifest(
                hourly_records=[],
                daily_rows=[],
                quarantined_records=[
                    {
                        "valid_time_gmt": 1716206400,
                        "obs_id": "KLGA",
                        "temp": 160,
                        "dewPt": 61,
                        "heat_index": 160,
                        "wc": 160,
                    }
                ],
            )

            manifest = json.loads((Path(tmp) / "manifest.json").read_text())

        self.assertEqual(manifest["quarantined_raw_observations"], 1)
        self.assertEqual(manifest["quarantined_raw_observation_dates"], {"2024-05-20": 1})
        self.assertEqual(manifest["quarantined_raw_observation_samples"][0]["temp"], 160)
        self.assertEqual(
            manifest["source_details"]["public_collector"]["credential_policy"],
            "no_user_paid_provider_credentials",
        )
        self.assertEqual(
            manifest["source_details"]["legacy_paid_provider"]["credential_policy"],
            "paid_provider_disabled_by_project_policy",
        )

    def test_wu_manifest_does_not_write_credential_material(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WundergroundHistoryStore(tmp, station_icao="KLGA", history_id="KLGA:9:US")
            store.write_manifest(hourly_records=[], daily_rows=[], quarantined_records=[])

            manifest = json.loads((Path(tmp) / "manifest.json").read_text())

        rendered = json.dumps(manifest)
        self.assertNotIn("secret", rendered.lower())
        self.assertEqual(
            manifest["source_details"]["public_collector"]["credential_policy"],
            "no_user_paid_provider_credentials",
        )

    def test_provider_key_defaults_are_not_embedded_in_source(self):
        for path in [
            Path("src/weather/model/model_constants.py"),
            Path("src/weather/sources/wu_history.py"),
        ]:
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(
                re.search(r"PROVIDER_API_KEY\s*=\s*['\"][A-Za-z0-9_-]{16,}['\"]", text),
                f"{path} must not embed a provider key literal",
            )

    def test_wu_paid_provider_fetch_path_is_disabled(self):
        client = WundergroundHistoryClient(history_id="KLGA:9:US")

        with self.assertRaisesRegex(RuntimeError, "disabled by project policy"):
            client.fetch_range(date(2026, 6, 29), date(2026, 6, 29))

    def test_public_wu_client_fetches_page_backed_history_without_stored_credential(self):
        page_text = (FIXTURES_ROOT / "wu_history_page_runtime_config.html").read_text(encoding="utf-8")
        recorded_payload = json.loads(
            (FIXTURES_ROOT / "wu_history_v1_response.json").read_text(encoding="utf-8")
        )

        class FakeResponse:
            def __init__(self, *, text="", payload=None, status_code=200):
                self.text = text
                self._payload = payload
                self.status_code = status_code
                self.url = "https://example.invalid/redacted"

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise requests.HTTPError(f"{self.status_code} Client Error")

            def json(self):
                return self._payload

        class FakeSession:
            def __init__(self):
                self.calls = []

            def get(self, url, **kwargs):
                self.calls.append((url, kwargs))
                if len(self.calls) == 1:
                    return FakeResponse(text=page_text)
                return FakeResponse(payload=recorded_payload)

        session = FakeSession()
        client = PublicWundergroundHistoryClient(
            history_id="KATL:9:US",
            station_icao="KATL",
            units="e",
            session=session,
            page_base="https://www.wunderground.com",
        )

        payload = client.fetch_range(date(2026, 6, 29), date(2026, 6, 29))

        self.assertEqual(len(payload["observations"]), 1)
        self.assertEqual(payload["_wu_collector_provenance"]["source"], PUBLIC_WU_HISTORY_SOURCE)
        self.assertEqual(session.calls[0][0], "https://www.wunderground.com/history/daily/KATL/date/2026-6-29")
        expected_api_root = "https://api." + "weather.com"
        self.assertEqual(
            session.calls[1][0],
            f"{expected_api_root}/v1/location/KATL:9:US/observations/historical.json",
        )
        self.assertEqual(session.calls[1][1]["params"]["apiKey"], "recorded-runtime-page-token")
        self.assertNotEqual(session.calls[1][1]["params"]["apiKey"], "unrelated-script-token")
        self.assertEqual(session.calls[1][1]["params"]["units"], "e")
        self.assertEqual(session.calls[1][1]["params"]["startDate"], "20260629")

    def test_public_wu_client_rejects_unrelated_embedded_api_key_url(self):
        client = PublicWundergroundHistoryClient()
        page_text = (
            '<script src="https://example.invalid/loader.js?'
            'apiKey=unrelated-script-token&amp;format=json"></script>'
        )

        with self.assertRaisesRegex(RuntimeError, "runtime history access configuration"):
            client.public_access_from_page(page_text)

    def test_public_wu_payload_writes_public_provenance_and_rebuilds_daily(self):
        payload = {
            "_wu_collector_provenance": {
                "source": PUBLIC_WU_HISTORY_SOURCE,
                "source_page_url": "https://www.wunderground.com/history/daily/KATL/date/2026-6-29",
                "endpoint_kind": "public_wu_page_backed_history",
                "retrieved_at_utc": "2026-06-30T00:00:00+00:00",
            },
            "observations": [{
                "key": "KATL",
                "obs_id": "KATL",
                "obs_name": "Atlanta",
                "valid_time_gmt": int(datetime(2026, 6, 29, 16, 52, tzinfo=timezone.utc).timestamp()),
                "temp": 94,
                "dewPt": 72,
                "heat_index": 99,
                "wc": 94,
            }],
        }
        with tempfile.TemporaryDirectory() as tmp:
            store = WundergroundHistoryStore(
                tmp,
                station_icao="KATL",
                station_name="Atlanta",
                history_id="KATL:9:US",
                tz=ATLANTA.tz,
                unit="F",
                wu_units="e",
            )
            store.write_payload(date(2026, 6, 29), date(2026, 6, 29), payload)
            _hourly, daily = store.rebuild_normalized_files()
            raw = json.loads((Path(tmp) / "raw" / "year=2026" / "month=06" / "2026-06-29.json").read_text(encoding="utf-8"))

        self.assertEqual(raw["source"], PUBLIC_WU_HISTORY_SOURCE)
        self.assertEqual(raw["endpoint_kind"], "public_wu_page_backed_history")
        self.assertEqual(daily[0]["local_date"], "2026-06-29")
        self.assertEqual(daily[0]["max_temp_bucket"], 94)

    def test_fleet_coverage_includes_all_item29_sources(self):
        payload = fleet_coverage(["nyc"])

        self.assertEqual(payload["schema_version"], "historical_coverage_v1")
        sources = payload["markets"][0]["sources"]
        self.assertIn("wu", sources)
        self.assertIn("ghcnh", sources)
        self.assertIn("reanalysis", sources)

    def test_coverage_dashboard_flags_gap_and_freshness_status(self):
        payload = {
            "schema_version": "historical_coverage_v1",
            "markets": [{
                "market_id": "nyc",
                "city": "NYC",
                "sources": {
                    "wu": {
                        "station": "KLGA",
                        "raw_days": 2,
                        "expected_days": 2,
                        "missing_days": 0,
                        "last_raw_date": "2026-06-14",
                        "manifest_exists": True,
                        "daily_summary_exists": True,
                    },
                    "reanalysis": {
                        "station": "era5:40.0000,-73.0000",
                        "normalized_daily_days": 1,
                        "expected_days": 2,
                        "missing_days": 1,
                        "last_normalized_date": "2026-06-01",
                        "raw_only_normalizable_day_count": 1,
                        "manifest_exists": True,
                        "daily_summary_exists": True,
                    },
                    "ghcnh": {
                        "station": "KLGA",
                        "raw_years": [2023],
                        "expected_years": [2023, 2024, 2025, 2026],
                        "missing_years": [2024, 2025, 2026],
                        "manifest_exists": True,
                        "daily_summary_exists": True,
                    },
                },
                "supplemental_sources": {"ghcnh": []},
            }],
        }

        dashboard = coverage_dashboard(payload, as_of="2026-06-15")
        rows = {row["source"]: row for row in dashboard["rows"]}

        self.assertEqual(dashboard["schema_version"], "historical_coverage_dashboard_v0.1")
        self.assertEqual(rows["wu"]["status"], "OK")
        self.assertEqual(rows["reanalysis"]["coverage_status"], "WARN")
        self.assertEqual(rows["reanalysis"]["status"], "WARN")
        self.assertEqual(rows["ghcnh"]["freshness_status"], "CRITICAL")
        self.assertEqual(rows["ghcnh"]["status"], "CRITICAL")

    def test_coverage_dashboard_writes_report_csv_json_and_parquet(self):
        try:
            import pyarrow  # noqa: F401
        except ImportError:
            self.skipTest("pyarrow not installed")
        payload = {
            "schema_version": "historical_coverage_v1",
            "markets": [{
                "market_id": "nyc",
                "city": "NYC",
                "sources": {
                    "wu": {
                        "station": "KLGA",
                        "raw_days": 1,
                        "expected_days": 1,
                        "missing_days": 0,
                        "last_raw_date": "2026-06-15",
                        "manifest_exists": True,
                        "daily_summary_exists": True,
                    },
                },
                "supplemental_sources": {"ghcnh": []},
            }],
        }
        dashboard = coverage_dashboard(payload, as_of="2026-06-15")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_dashboard_outputs(
                dashboard,
                json_out=root / "dashboard.json",
                markdown_out=root / "dashboard.md",
                csv_out=root / "dashboard.csv",
                parquet_out=root / "dashboard.parquet",
            )

            self.assertTrue((root / "dashboard.json").exists())
            self.assertIn("Historical Coverage Dashboard", (root / "dashboard.md").read_text(encoding="utf-8"))
            self.assertIn("market_id,city,source", (root / "dashboard.csv").read_text(encoding="utf-8"))
            self.assertTrue((root / "dashboard.parquet").exists())

    def test_fleet_coverage_reports_registered_supplemental_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = self.supplemental_registry(Path(tmp) / "supp")
            payload = fleet_coverage(["nyc"], registry=registry)

        supplemental = payload["markets"][0]["supplemental_sources"]["ghcnh"]
        self.assertEqual(len(supplemental), 1)
        self.assertEqual(supplemental[0]["source_id"], "ghcnh_test_supplemental")
        self.assertEqual(supplemental[0]["source_role"], "supplemental")
        self.assertEqual(supplemental[0]["distance_from_canonical_km"], 0.42)

    def test_supplemental_registry_rejects_canonical_root(self):
        registry = self.supplemental_registry(Path("data") / "noaa_ghcnh" / "klga")

        with self.assertRaises(SupplementalStationRegistryError):
            guard_not_canonical_root(registry["sources"][0], NYC)

    def test_backfill_plan_has_stable_shape(self):
        plan = build_plan(
            market_ids=["nyc"],
            sources=["wu"],
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 1),
            python="python",
        )

        self.assertEqual(plan["schema_version"], "historical_backfill_plan_v1")
        self.assertEqual(plan["queue_mode"], "market_source")
        self.assertEqual(plan["market_count"], 1)
        self.assertEqual(plan["sources"], ["wu"])
        self.assertIn("queue", plan)

    def test_market_source_plan_coalesces_missing_ranges(self):
        class FakeStore:
            def missing_ranges(self, start_date, end_date, chunk_days=14):
                return [
                    (date(2026, 1, 1), date(2026, 1, 2)),
                    (date(2026, 1, 5), date(2026, 1, 5)),
                ]

        with patch("weather.collection.historical_backfill_plan.wu_store", return_value=FakeStore()):
            plan = build_plan(
                market_ids=["nyc"],
                sources=["wu"],
                start_date=date(2026, 1, 1),
                end_date=date(2026, 1, 5),
                python="python",
            )

        self.assertEqual(plan["queue_count"], 1)
        item = plan["queue"][0]
        self.assertEqual(item["detail"]["kind"], "market_source_date_window")
        self.assertEqual(item["detail"]["missing_ranges"], 2)
        self.assertEqual(item["detail"]["missing_days"], 3)
        self.assertEqual(item["command"][item["command"].index("--start") + 1], "2026-01-01")
        self.assertEqual(item["command"][item["command"].index("--end") + 1], "2026-01-05")

    def test_backfill_plan_includes_open_meteo_air_quality_source(self):
        class FakeStore:
            def air_quality_missing_ranges(self, spec, start_date, end_date, chunk_days=31):
                return [
                    (date(2026, 6, 1), date(2026, 6, 2)),
                    (date(2026, 6, 5), date(2026, 6, 5)),
                ]

        with patch("weather.collection.historical_backfill_plan.OpenMeteoArchiveStore", return_value=FakeStore()):
            plan = build_plan(
                market_ids=["nyc"],
                sources=["open_meteo_air_quality"],
                start_date=date(2026, 6, 1),
                end_date=date(2026, 6, 5),
                python="python",
                open_meteo_aq_chunk_days=2,
            )

        self.assertEqual(plan["queue_count"], 1)
        item = plan["queue"][0]
        self.assertEqual(item["source"], "open_meteo_air_quality")
        self.assertEqual(item["detail"]["missing_ranges"], 2)
        self.assertEqual(item["detail"]["missing_days"], 3)
        self.assertEqual(item["command"][:3], ["python", "-m", "weather.sources.open_meteo_archives"])
        self.assertIn("air-quality", item["command"])
        self.assertIn("--skip-existing", item["command"])

    def test_backfill_plan_includes_open_meteo_global_models_source(self):
        class FakeStore:
            def global_model_missing_ranges(self, spec, start_date, end_date, chunk_days=31):
                return [
                    (date(2026, 6, 1), date(2026, 6, 2)),
                    (date(2026, 6, 5), date(2026, 6, 5)),
                ]

        with patch("weather.collection.historical_backfill_plan.OpenMeteoArchiveStore", return_value=FakeStore()):
            plan = build_plan(
                market_ids=["nyc"],
                sources=["open_meteo_global_models"],
                start_date=date(2026, 6, 1),
                end_date=date(2026, 6, 5),
                python="python",
                open_meteo_global_model_chunk_days=2,
            )

        self.assertEqual(plan["queue_count"], 1)
        item = plan["queue"][0]
        self.assertEqual(item["source"], "open_meteo_global_models")
        self.assertEqual(item["detail"]["missing_ranges"], 2)
        self.assertEqual(item["detail"]["missing_days"], 3)
        self.assertEqual(item["command"][:3], ["python", "-m", "weather.sources.open_meteo_archives"])
        self.assertIn("global-models", item["command"])
        self.assertIn("--skip-existing", item["command"])

    def test_backfill_plan_includes_marine_water_contrast_source(self):
        class FakeStore:
            def __init__(self, _spec):
                pass

            def missing_ranges(self, start_date, end_date, chunk_days=31):
                return [(date(2026, 6, 1), date(2026, 6, 2))]

        with patch("weather.collection.historical_backfill_plan.MarineWaterContrastStore", FakeStore):
            plan = build_plan(
                market_ids=["nyc"],
                sources=["marine_water_contrast"],
                start_date=date(2026, 6, 1),
                end_date=date(2026, 6, 2),
                python="python",
            )

        self.assertEqual(plan["queue_count"], 1)
        item = plan["queue"][0]
        self.assertEqual(item["source"], "marine_water_contrast")
        self.assertEqual(item["detail"]["missing_days"], 2)
        self.assertEqual(item["command"][:3], ["python", "-m", "weather.sources.marine_water_contrast"])
        self.assertIn("backfill-station-history", item["command"])
        self.assertIn("--skip-existing", item["command"])

    def test_backfill_plan_records_pre_2015_us_wu_as_source_limited(self):
        class FakeStore:
            def missing_ranges(self, start_date, end_date, chunk_days=14):
                return [(date(2000, 1, 1), date(2014, 12, 31))]

        probe = {
            "generated_at_utc": "2026-06-14T22:20:37+00:00",
            "us_wu_candidates": [
                {"market_id": "nyc", "candidates": [{"available": False, "history_id": "KLGA:9:US"}]},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "source_alternate_probe_2026-06-14.json").write_text(
                json.dumps(probe),
                encoding="utf-8",
            )
            with patch("weather.collection.historical_backfill_plan.wu_store", return_value=FakeStore()):
                plan = build_plan(
                    market_ids=["nyc"],
                    sources=["wu"],
                    start_date=date(2000, 1, 1),
                    end_date=date(2014, 12, 31),
                    python="python",
                    backtest_root=tmp,
                )

        self.assertEqual(plan["queue_count"], 0)
        self.assertEqual(plan["source_limited_count"], 1)
        limited = plan["source_limited"][0]
        self.assertEqual(limited["market_id"], "nyc")
        self.assertTrue(limited["source_limited"])
        self.assertIn("provider-unavailable", limited["reason"])

    def test_backfill_plan_splits_mixed_pre_2015_us_wu_window(self):
        class FakeStore:
            def missing_ranges(self, start_date, end_date, chunk_days=14):
                return [
                    (date(2000, 1, 1), date(2014, 12, 31)),
                    (date(2020, 11, 8), date(2020, 11, 8)),
                ]

        probe = {
            "generated_at_utc": "2026-06-14T22:20:37+00:00",
            "us_wu_candidates": [
                {"market_id": "nyc", "candidates": [{"available": False, "history_id": "KLGA:9:US"}]},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "source_alternate_probe_2026-06-14.json").write_text(
                json.dumps(probe),
                encoding="utf-8",
            )
            with patch("weather.collection.historical_backfill_plan.wu_store", return_value=FakeStore()):
                plan = build_plan(
                    market_ids=["nyc"],
                    sources=["wu"],
                    start_date=date(2000, 1, 1),
                    end_date=date(2020, 11, 8),
                    python="python",
                    backtest_root=tmp,
                )

        self.assertEqual(plan["source_limited_count"], 1)
        self.assertEqual(plan["queue_count"], 1)
        queued = plan["queue"][0]
        self.assertEqual(queued["command"][queued["command"].index("--start") + 1], "2015-01-01")
        self.assertTrue(queued["detail"]["source_limited_prefix_removed"])

    def test_split_ranges_chunks_contiguous_missing_days(self):
        ranges = split_ranges(
            [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 5)],
            chunk_days=1,
        )

        self.assertEqual(ranges, [
            (date(2026, 1, 1), date(2026, 1, 1)),
            (date(2026, 1, 2), date(2026, 1, 2)),
            (date(2026, 1, 5), date(2026, 1, 5)),
        ])

    def test_wu_normalizer_quarantines_impossible_temperature(self):
        base = {
            "key": "KMIA",
            "obs_id": "KMIA",
            "obs_name": "Miami Intl",
            "valid_time_gmt": int(datetime(2005, 6, 11, 14, 0, tzinfo=timezone.utc).timestamp()),
            "rh": 72,
            "pressure": 29.95,
            "vis": 10,
            "wdir": 120,
            "wspd": 8,
            "gust": None,
            "clds": "FEW",
            "wx_phrase": "Fair",
        }
        bad = {
            **base,
            "temp": 171,
            "dewPt": 171,
            "heat_index": 403,
            "wc": 171,
        }
        good = {
            **base,
            "valid_time_gmt": int(datetime(2005, 6, 11, 15, 0, tzinfo=timezone.utc).timestamp()),
            "temp": 86,
            "dewPt": 78,
            "heat_index": 95,
            "wc": 86,
        }

        self.assertIsNone(normalize_observation(bad, NYC.tz, unit="F"))
        row = normalize_observation(good, NYC.tz, unit="F")

        self.assertIsNotNone(row)
        daily = summarize_daily([row])
        self.assertEqual(daily[0]["max_temp_bucket"], 86)

    def test_wu_error_redaction_removes_api_key_from_url_text(self):
        text = (
            "400 Client Error for url: "
            "https://example.invalid/history?apiKey=secret123&units=e "
            'runtime={"API_KEY":"runtime-secret"}'
        )

        redacted = redact_api_key(text)

        self.assertNotIn("secret123", redacted)
        self.assertNotIn("runtime-secret", redacted)
        self.assertIn("apiKey=<redacted>", redacted)
        self.assertIn('"API_KEY":"<redacted>"', redacted)

    def wu_http_error(self, status_code):
        response = requests.Response()
        response.status_code = status_code
        response.url = f"https://example.invalid/history?apiKey=secret123&status={status_code}"
        error = requests.HTTPError(f"{status_code} Client Error")
        error.response = response
        return error

    def test_wu_fetch_errors_type_recoverable_failures_without_poisoning_unavailable_dates(self):
        cases = [
            (date(2026, 1, 1), self.wu_http_error(400), PERMANENT_NO_DATA, True),
            (date(2026, 1, 2), self.wu_http_error(401), AUTH_FAILURE, False),
            (date(2026, 1, 3), self.wu_http_error(403), AUTH_FAILURE, False),
            (date(2026, 1, 4), self.wu_http_error(429), RATE_LIMITED, False),
            (date(2026, 1, 5), self.wu_http_error(503), TRANSIENT_FAILURE, False),
            (date(2026, 1, 6), requests.Timeout("timed out"), TRANSIENT_FAILURE, False),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            store = WundergroundHistoryStore(tmp, station_icao="KLGA", history_id="KLGA:9:US")
            for day, exc, expected_class, expected_unavailable in cases:
                row = store.write_fetch_error(day, day, exc)
                self.assertEqual(row["failure_class"], expected_class)
                self.assertEqual(row["treated_as_source_unavailable"], expected_unavailable)

            unavailable = store.unavailable_dates()
            missing = store.missing_dates(date(2026, 1, 1), date(2026, 1, 6))

        self.assertEqual(unavailable, {date(2026, 1, 1)})
        self.assertNotIn(date(2026, 1, 1), missing)
        self.assertEqual(set(missing), {date(2026, 1, 2), date(2026, 1, 3), date(2026, 1, 4), date(2026, 1, 5), date(2026, 1, 6)})

    def test_wu_recover_unavailable_rewrites_legacy_poisoned_error_rows(self):
        legacy_rows = [
            {"start": "2026-01-01", "end": "2026-01-01", "status_code": 401, "treated_as_source_unavailable": True},
            {"start": "2026-01-02", "end": "2026-01-02", "status_code": 429, "treated_as_source_unavailable": True},
            {"start": "2026-01-03", "end": "2026-01-03", "status_code": 500, "treated_as_source_unavailable": True},
            {"start": "2026-01-04", "end": "2026-01-04", "status_code": 404, "treated_as_source_unavailable": True},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            store = WundergroundHistoryStore(tmp, station_icao="KLGA", history_id="KLGA:9:US")
            store.error_log_path.parent.mkdir(parents=True, exist_ok=True)
            store.error_log_path.write_text(
                "\n".join(json.dumps(row, sort_keys=True) for row in legacy_rows) + "\n",
                encoding="utf-8",
            )

            report = store.recover_unavailable_errors()
            rows = [
                json.loads(line)
                for line in store.error_log_path.read_text(encoding="utf-8").splitlines()
                if line
            ]

        self.assertEqual(report["recovered_error_rows"], 3)
        self.assertEqual(report["recovered_days"], 3)
        self.assertEqual(rows[0]["failure_class"], AUTH_FAILURE)
        self.assertFalse(rows[0]["treated_as_source_unavailable"])
        self.assertEqual(rows[1]["failure_class"], RATE_LIMITED)
        self.assertFalse(rows[1]["treated_as_source_unavailable"])
        self.assertEqual(rows[2]["failure_class"], TRANSIENT_FAILURE)
        self.assertFalse(rows[2]["treated_as_source_unavailable"])
        self.assertEqual(rows[3]["failure_class"], PERMANENT_NO_DATA)
        self.assertTrue(rows[3]["treated_as_source_unavailable"])

    def page_backed_http_error(self, status_code):
        response = requests.Response()
        response.status_code = status_code
        response.url = "https://www.wunderground.com/history/daily/CYYZ/date/2026-8-5"
        try:
            PublicWundergroundHistoryClient._raise_for_status(response)
        except requests.HTTPError as exc:
            return exc
        self.fail(f"expected {status_code} to raise")

    def test_wu_page_backed_404_is_transient_and_keeps_the_date_fetchable(self):
        target = date(2026, 8, 5)
        with tempfile.TemporaryDirectory() as tmp:
            store = WundergroundHistoryStore(tmp, station_icao="CYYZ", history_id="CYYZ:9:CA")
            row = store.write_fetch_error(
                target, target, self.page_backed_http_error(404), source=PUBLIC_WU_HISTORY_SOURCE
            )
            unavailable = store.unavailable_dates()
            missing = store.missing_dates(target, target)

        self.assertEqual(row["failure_class"], TRANSIENT_FAILURE)
        self.assertFalse(row["treated_as_source_unavailable"])
        self.assertEqual(unavailable, set())
        self.assertEqual(missing, [target], "a page-backed 404 must leave the date fetchable")

    def test_wu_page_backed_400_stays_permanent(self):
        target = date(2026, 8, 5)
        with tempfile.TemporaryDirectory() as tmp:
            store = WundergroundHistoryStore(tmp, station_icao="CYYZ", history_id="CYYZ:9:CA")
            row = store.write_fetch_error(
                target, target, self.page_backed_http_error(400), source=PUBLIC_WU_HISTORY_SOURCE
            )
            missing = store.missing_dates(target, target)

        self.assertEqual(row["failure_class"], PERMANENT_NO_DATA)
        self.assertTrue(row["treated_as_source_unavailable"])
        self.assertEqual(missing, [])

    def test_wu_paid_api_404_remains_permanent(self):
        target = date(2026, 8, 5)
        with tempfile.TemporaryDirectory() as tmp:
            store = WundergroundHistoryStore(tmp, station_icao="KLGA", history_id="KLGA:9:US")
            row = store.write_fetch_error(target, target, self.wu_http_error(404))
            missing = store.missing_dates(target, target)

        self.assertEqual(row["failure_class"], PERMANENT_NO_DATA)
        self.assertTrue(row["treated_as_source_unavailable"])
        self.assertEqual(missing, [])

    def test_wu_recover_releases_page_backed_404_rows_written_before_the_fix(self):
        poisoned = {
            "start": "2026-08-05",
            "end": "2026-08-05",
            "status_code": 404,
            "failure_class": PERMANENT_NO_DATA,
            "source": PUBLIC_WU_HISTORY_SOURCE,
            "treated_as_source_unavailable": True,
        }
        with tempfile.TemporaryDirectory() as tmp:
            store = WundergroundHistoryStore(tmp, station_icao="CYYZ", history_id="CYYZ:9:CA")
            store.error_log_path.parent.mkdir(parents=True, exist_ok=True)
            store.error_log_path.write_text(
                json.dumps(poisoned, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            report = store.recover_unavailable_errors()
            missing = store.missing_dates(target := date(2026, 8, 5), target)

        self.assertEqual(report["recovered_error_rows"], 1)
        self.assertEqual(missing, [date(2026, 8, 5)])

    def test_forecast_history_writes_source_issue_rows(self):
        payload = {
            "hourly": {
                "time": ["2026-06-11T14:00", "2026-06-11T15:00"],
                "temperature_2m": [82, 85],
                "cloud_cover": [20, 35],
                "cloud_cover_low": [10, 15],
                "cloud_cover_mid": [5, 10],
                "cloud_cover_high": [30, 40],
                "shortwave_radiation": [700, 800],
                "wind_speed_10m": [8, 9],
                "direct_radiation": [500, 600],
                "diffuse_radiation": [120, 130],
                "cape": [10, 40],
                "temperature_925hPa": [76, 78],
                "temperature_850hPa": [68, 69],
                "geopotential_height_500hPa": [5740, 5750],
                "wind_gusts_10m": [15, 18],
                "visibility": [20000, 18000],
                "precipitation_probability": [0, 30],
                "precipitation": [0.0, 0.2],
                "soil_temperature_0cm": [74, 75],
                "soil_moisture_0_to_1cm": [0.22, 0.23],
                "vapour_pressure_deficit": [0.8, 1.0],
                "et0_fao_evapotranspiration": [0.1, 0.2],
                "temperature_2m_previous_day1": [80, 83],
                "temperature_2m_previous_day2": [79, 81],
            }
        }

        stitched = historical_forecast_rows(payload, NYC)
        previous = previous_run_rows(payload, NYC, leads=(1, 2))
        daily_rows = daily_issue_rows(stitched + previous)

        self.assertEqual(stitched[0]["source"], "open_meteo_historical_forecast")
        self.assertEqual(stitched[0]["issue_time_basis"], "stitched_continuous_archive")
        self.assertEqual(stitched[0]["low_cloud"], 10)
        self.assertEqual(stitched[0]["shortwave_radiation"], 700)
        self.assertEqual(stitched[0]["direct_radiation"], 500)
        self.assertEqual(stitched[0]["cape"], 10)
        self.assertEqual(stitched[0]["temperature_925hpa"], 76)
        self.assertEqual(stitched[0]["geopotential_height_500hpa"], 5740)
        self.assertEqual(stitched[0]["wind_gust_kmh"], 15)
        self.assertEqual(stitched[0]["precipitation_probability"], 0)
        self.assertEqual(stitched[0]["precipitation"], 0.0)
        self.assertEqual(stitched[0]["vapour_pressure_deficit"], 0.8)
        self.assertEqual(previous[0]["source"], "open_meteo_previous_runs")
        self.assertEqual(previous[0]["issue_time_basis"], "fixed_lead_day_offset")
        self.assertEqual(previous[0]["lead_days"], 1)
        self.assertIn("2026-06-10T00:00", previous[0]["issue_time"])
        lead_two = [
            row for row in daily_rows
            if row["source"] == "open_meteo_previous_runs" and row["lead_days"] == 2
        ][0]
        self.assertEqual(lead_two["forecast_high_native"], 81)
        self.assertEqual(lead_two["hourly_rows"], 2)

    def test_forecast_profile_loader_reads_new_radiation_and_cloud_layers(self):
        payload = {
            "hourly": {
                "time": ["2026-06-11T12:00", "2026-06-11T13:00"],
                "temperature_2m": [82, 85],
                "cloud_cover": [20, 35],
                "cloud_cover_low": [10, 15],
                "cloud_cover_mid": [5, 10],
                "cloud_cover_high": [30, 40],
                "shortwave_radiation": [700, 800],
                "wind_speed_10m": [8, 9],
                "direct_radiation": [500, 600],
                "diffuse_radiation": [120, 130],
                "cape": [10, 40],
                "temperature_925hPa": [76, 78],
                "temperature_850hPa": [68, 69],
                "geopotential_height_500hPa": [5740, 5750],
                "wind_gusts_10m": [15, 18],
                "visibility": [20000, 18000],
                "precipitation_probability": [0, 30],
                "precipitation": [0.0, 0.2],
                "soil_temperature_0cm": [74, 75],
                "soil_moisture_0_to_1cm": [0.22, 0.23],
                "vapour_pressure_deficit": [0.8, 1.0],
                "et0_fao_evapotranspiration": [0.1, 0.2],
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "forecast_long.csv"
            write_csv(path, RICH_FORECAST_COLUMNS, historical_forecast_rows(payload, NYC))

            profiles = load_forecast_profiles(path)

        self.assertEqual(profiles["2026-06-11"][0]["minute_of_day"], 720)
        self.assertEqual(profiles["2026-06-11"][0]["low_cloud"], 10.0)
        self.assertEqual(profiles["2026-06-11"][0]["direct_radiation"], 500.0)
        self.assertEqual(profiles["2026-06-11"][0]["precipitation_probability"], 0.0)
        self.assertEqual(profiles["2026-06-11"][0]["wind_gust_kmh"], 15.0)
        self.assertEqual(profiles["2026-06-11"][1]["solar"], 800.0)
        self.assertEqual(profiles["2026-06-11"][1]["cape"], 40.0)
        self.assertEqual(profiles["2026-06-11"][1]["temperature_850hpa"], 69.0)
        self.assertEqual(profiles["2026-06-11"][1]["vapour_pressure_deficit"], 1.0)

    def test_forecast_history_coverage_reports_rich_field_completeness(self):
        payload = {
            "hourly": {
                "time": ["2026-06-11T12:00", "2026-06-11T13:00"],
                "temperature_2m": [82, 85],
                "cloud_cover": [20, 35],
                "cloud_cover_low": [10, 15],
                "cloud_cover_mid": [5, 10],
                "cloud_cover_high": [30, 40],
                "shortwave_radiation": [700, 800],
                "wind_speed_10m": [8, 9],
                "direct_radiation": [500, 600],
                "diffuse_radiation": [120, 130],
                "cape": [10, 40],
                "temperature_925hPa": [76, 78],
                "temperature_850hPa": [68, 69],
                "geopotential_height_500hPa": [5740, 5750],
                "wind_gusts_10m": [15, 18],
                "visibility": [20000, 18000],
                "precipitation_probability": [0, 30],
                "precipitation": [0.0, 0.2],
                "soil_temperature_0cm": [74, 75],
                "soil_moisture_0_to_1cm": [0.22, 0.23],
                "vapour_pressure_deficit": [0.8, 1.0],
                "et0_fao_evapotranspiration": [0.1, 0.2],
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "forecast_long.csv"
            write_csv(path, RICH_FORECAST_COLUMNS, historical_forecast_rows(payload, NYC))
            target = target_window_contract(
                "2026-06-11",
                (2026,),
                target_window_days=0,
                history_window_days=0,
            )
            (path.parent / "manifest.json").write_text(
                json.dumps({"target_window": target}),
                encoding="utf-8",
            )

            coverage = forecast_history_coverage(
                NYC,
                path=path,
                required_fields=("low_cloud", "shortwave_radiation", "cape"),
                target_date="2026-06-11",
                required_years=(2026,),
                target_window_days=0,
                history_window_days=0,
            )

        fleet_payload = {
            "schema_version": FORECAST_HISTORY_COVERAGE_SCHEMA_VERSION,
            "status": "PASS",
            "declared_target": target,
            "summary": {
                "market_count": 1,
                "ok_market_count": 1,
                "all_active_markets_backfilled": True,
            },
            "markets": [coverage],
        }
        markdown = render_forecast_history_coverage_markdown(fleet_payload)

        self.assertEqual(coverage["status"], "OK")
        self.assertEqual(coverage["historical_rows"], 2)
        self.assertEqual(coverage["nonnull_fields"]["cape"], 2)
        self.assertFalse(coverage["missing_nonnull_fields"])
        self.assertIn("nyc", markdown)

    def test_forecast_history_window_uses_trainer_target_and_climatology_inputs(self):
        from weather.model.model_constants import HISTORY_WINDOW_DAYS
        from weather.operations.base_retrain import FIRST_RETRAIN_SEASON_RADIUS_DAYS

        self.assertEqual(DEFAULT_HISTORY_WINDOW_DAYS, HISTORY_WINDOW_DAYS)
        self.assertEqual(DEFAULT_TARGET_WINDOW_DAYS, FIRST_RETRAIN_SEASON_RADIUS_DAYS)
        start, end = archive_window_for_target(2023, "2026-07-31")
        self.assertEqual(start, date(2023, 7, 17))
        self.assertEqual(end, date(2023, 8, 14))

    def test_forecast_history_backfill_manifest_declares_its_target_window(self):
        payload = {
            "hourly": {
                "time": ["2023-07-17T12:00"],
                **{field: [1.0] for field in (
                    "temperature_2m",
                    "cloud_cover",
                    "cloud_cover_low",
                    "cloud_cover_mid",
                    "cloud_cover_high",
                    "shortwave_radiation",
                    "wind_speed_10m",
                    "cape",
                    "temperature_925hPa",
                    "temperature_850hPa",
                    "geopotential_height_500hPa",
                    "direct_radiation",
                    "diffuse_radiation",
                    "wind_gusts_10m",
                    "visibility",
                    "precipitation_probability",
                    "precipitation",
                    "soil_temperature_0cm",
                    "soil_moisture_0_to_1cm",
                    "vapour_pressure_deficit",
                    "et0_fao_evapotranspiration",
                )},
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch("weather.sources.forecast_history.data_root_for", return_value=root),
                patch("weather.sources.forecast_history.daily_path_for", return_value=root / "forecast_daily.csv"),
                patch("weather.sources.forecast_history.long_path_for", return_value=root / "forecast_long.csv"),
                patch("weather.sources.forecast_history.daily_issue_path_for", return_value=root / "forecast_daily_by_issue.csv"),
                patch("weather.sources.forecast_history.fetch_historical_forecast_payload", return_value=payload) as fetch,
            ):
                manifest = backfill(
                    2023,
                    2023,
                    NYC,
                    pause=0,
                    include_previous_runs=False,
                    target_date="2026-07-31",
                )

            written = json.loads((root / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(manifest["target_window"], written["target_window"])
        self.assertEqual(manifest["target_window"]["target_date"], "2026-07-31")
        self.assertEqual(
            manifest["target_window"]["requested_by_year"]["2023"],
            {"start": "2023-07-17", "end": "2023-08-14"},
        )
        self.assertEqual(fetch.call_args.kwargs["target_date"], date(2026, 7, 31))

    def test_forecast_history_fleet_coverage_blocks_archive_for_wrong_season(self):
        rows = []
        for year in range(2021, 2026):
            current = date(year, 5, 10)
            end = date(year, 6, 30)
            while current <= end:
                row = {column: "" for column in RICH_FORECAST_COLUMNS}
                row.update({
                    "schema_version": "forecast_history_long_v3",
                    "market": NYC.id,
                    "station": NYC.icao,
                    "source": "open_meteo_historical_forecast",
                    "target_date": current.isoformat(),
                    "valid_time": f"{current.isoformat()}T12:00",
                    "cloud_cover": 1,
                    "low_cloud": 1,
                    "mid_cloud": 1,
                    "high_cloud": 1,
                    "shortwave_radiation": 1,
                    "direct_radiation": 1,
                    "diffuse_radiation": 1,
                })
                rows.append(row)
                current += timedelta(days=1)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "forecast_long.csv"
            write_csv(path, RICH_FORECAST_COLUMNS, rows)
            (path.parent / "manifest.json").write_text(
                json.dumps({
                    "target_window": target_window_contract(
                        "2026-06-15",
                        range(2021, 2026),
                    )
                }),
                encoding="utf-8",
            )
            with patch("weather.sources.forecast_history.long_path_for", return_value=path):
                report = forecast_history_fleet_coverage(
                    "2026-07-31",
                    market_ids=(NYC.id,),
                    required_years=range(2021, 2026),
                )

        market = report["markets"][0]
        self.assertEqual(report["status"], "BLOCK")
        self.assertEqual(market["status"], "FAIL")
        self.assertEqual(market["target_status"], "BLOCK")
        self.assertEqual(market["required_date_count"], 145)
        self.assertEqual(market["covered_required_date_count"], 0)
        self.assertEqual(market["manifest_target_status"], "MISMATCH")
        self.assertIn("declared_target_dates_missing", market["blockers"])
        self.assertIn("archive_target_manifest_mismatch", market["blockers"])

    def test_forecast_loaders_prefer_native_temperature_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            long_path = Path(tmp) / "forecast_long.csv"
            daily_path = Path(tmp) / "forecast_daily.csv"
            with long_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "source",
                        "target_date",
                        "valid_time",
                        "target_temp_native",
                        "target_temp_c",
                    ],
                )
                writer.writeheader()
                writer.writerow({
                    "source": "open_meteo_historical_forecast",
                    "target_date": "2026-06-11",
                    "valid_time": "2026-06-11T12:00",
                    "target_temp_native": "84",
                    "target_temp_c": "28.9",
                })
            with daily_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["local_date", "forecast_high_native", "forecast_high_c"],
                )
                writer.writeheader()
                writer.writerow({
                    "local_date": "2026-06-11",
                    "forecast_high_native": "86",
                    "forecast_high_c": "30",
                })

            profiles = load_forecast_profiles(long_path)
            daily = load_forecast_daily(daily_path)

        self.assertEqual(profiles["2026-06-11"][0]["temp_native"], 84.0)
        self.assertEqual(profiles["2026-06-11"][0]["temp_c"], 84.0)
        self.assertEqual(daily["2026-06-11"], 86.0)

    def test_ghcnh_station_resolves_by_icao(self):
        station = resolve_station(NYC, [
            {"GHCN_ID": "USW00099999", "ICAO": "XXXX", "LATITUDE": "0", "LONGITUDE": "0"},
            {"GHCN_ID": "USW00014732", "ICAO": "KLGA", "LATITUDE": "40.779", "LONGITUDE": "-73.88"},
        ])

        self.assertEqual(station["GHCN_ID"], "USW00014732")

    def test_ghcnh_station_resolves_canadian_blank_icao_by_nearest_wmo(self):
        station = resolve_station(TORONTO, [
            {
                "GHCN_ID": "CAN06158733",
                "ICAO": "",
                "ISO_CODE": "CA",
                "WMO_ID": "",
                "LATITUDE": "43.677",
                "LONGITUDE": "-79.631",
            },
            {
                "GHCN_ID": "CAN06158731",
                "ICAO": "",
                "ISO_CODE": "CA",
                "WMO_ID": "71624",
                "LATITUDE": "43.677",
                "LONGITUDE": "-79.631",
            },
        ])

        self.assertEqual(station["GHCN_ID"], "CAN06158731")

    def test_ghcnh_normalizes_to_native_unit_schema(self):
        station = {"GHCN_ID": "USW00014732", "NAME": "LAGUARDIA AP"}

        records = normalize_psv(GHCNH_SAMPLE, NYC, station)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["source"], "noaa_ghcnh")
        self.assertEqual(records[0]["temperature_unit"], "F")
        self.assertAlmostEqual(records[0]["temp_native"], 73.94)
        self.assertEqual(records[0]["local_date"], "2023-06-01")
        self.assertEqual(records[0]["station"], "USW00014732")

    def test_ghcnh_store_rebuild_writes_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = GHCNHStore(NYC, tmp)
            station = {"GHCN_ID": "USW00014732", "NAME": "LAGUARDIA AP"}
            store.write_station(station)
            store.write_year("USW00014732", 2023, GHCNH_SAMPLE)

            records, daily = store.rebuild()

            self.assertEqual(len(records), 2)
            self.assertEqual(daily[0]["max_temp_bucket"], 77)
            self.assertTrue((Path(tmp) / "manifest.json").exists())
            self.assertTrue((Path(tmp) / "hourly" / "year=2023" / "month=06" / "observations.jsonl").exists())

    def test_ghcnh_supplemental_rebuild_writes_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "supp"
            registry = self.supplemental_registry(root)
            store = GHCNHStore(NYC, root, registry=registry)
            station = {"GHCN_ID": "USW00014732", "NAME": "LAGUARDIA AP"}
            store.write_station(station)
            store.write_year("USW00014732", 2023, GHCNH_SAMPLE)

            records, daily = store.rebuild()
            daily_rows = list(csv.DictReader((root / "daily" / "daily_summary.csv").open(encoding="utf-8", newline="")))
            hourly_record = json.loads((root / "hourly" / "year=2023" / "month=06" / "observations.jsonl").read_text(encoding="utf-8").splitlines()[0])
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(records[0]["source_role"], "supplemental")
        self.assertEqual(records[0]["supplemental_source_id"], "ghcnh_test_supplemental")
        self.assertEqual(daily[0]["source_role"], "supplemental")
        self.assertEqual(daily_rows[0]["source_role"], "supplemental")
        self.assertEqual(daily_rows[0]["supplemental_station_id"], "USW00014732")
        self.assertEqual(hourly_record["source_distance_from_canonical_km"], 0.42)
        self.assertEqual(manifest["metadata"]["source_role"], "supplemental")
        self.assertEqual(manifest["metadata"]["supplemental_source"]["source_id"], "ghcnh_test_supplemental")

    def test_ghcnh_source_unavailable_years_are_not_refetch_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = GHCNHStore(NYC, tmp)
            station = {"GHCN_ID": "USW00014732", "NAME": "LAGUARDIA AP"}
            store.write_station(station)
            store.write_year("USW00014732", 2023, GHCNH_SAMPLE)
            store.record_source_unavailable_year(
                "USW00014732",
                2022,
                "https://example.test/GHCNh_USW00014732_2022.psv",
                "404 Client Error",
            )

            records, daily = store.rebuild()
            coverage = store.coverage(2022, 2023)
            manifest = json.loads((Path(tmp) / "manifest.json").read_text(encoding="utf-8"))

            self.assertEqual(len(records), 2)
            self.assertEqual(daily[0]["local_date"], "2023-06-01")
            self.assertEqual(store.missing_years(2022, 2023), [])
            self.assertEqual(coverage["missing_years"], [])
            self.assertEqual(coverage["source_unavailable_years"], [2022])
            self.assertEqual(coverage["raw_missing_years"], [2022])
            self.assertEqual(manifest["metadata"]["source_unavailable_year_count"], 1)

    def test_reanalysis_normalizes_to_native_unit_schema(self):
        payload = {
            "generationtime_ms": 1.2,
            "hourly": {
                "time": ["2026-06-01T12:00", "2026-06-01T13:00"],
                "temperature_2m": [20.1, 21.6],
                "dew_point_2m": [11.0, 12.0],
                "relative_humidity_2m": [55, 52],
                "pressure_msl": [1012.0, 1011.8],
                "wind_speed_10m": [8.0, 9.0],
                "wind_direction_10m": [180, 190],
                "wind_gusts_10m": [14.0, 15.0],
                "cloud_cover": [20, 25],
            },
        }

        records = normalize_payload(payload, TORONTO)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["source"], "open_meteo_era5_reanalysis")
        self.assertEqual(records[0]["temperature_unit"], "C")
        self.assertEqual(records[1]["temp_native"], 21.6)
        self.assertEqual(records[1]["local_date"], "2026-06-01")

    def test_reanalysis_store_rebuild_writes_manifest(self):
        payload = {
            "hourly": {
                "time": ["2026-06-01T12:00"],
                "temperature_2m": [75.0],
                "dew_point_2m": [60.0],
                "relative_humidity_2m": [60],
                "pressure_msl": [1012.0],
                "wind_speed_10m": [8.0],
                "wind_direction_10m": [180],
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            store = ReanalysisStore(NYC, tmp)
            store.write_payload(__import__("datetime").date(2026, 6, 1), __import__("datetime").date(2026, 6, 1), payload)

            records, daily = store.rebuild()

            self.assertEqual(len(records), 1)
            self.assertEqual(daily[0]["max_temp_bucket"], 75)
            self.assertTrue((Path(tmp) / "manifest.json").exists())
            manifest = json.loads((Path(tmp) / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["source"], "open_meteo_era5_reanalysis")

    def test_reanalysis_coverage_uses_normalized_daily_dates(self):
        payload = {
            "hourly": {
                "time": ["2026-06-01T12:00"],
                "temperature_2m": [75.0],
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            store = ReanalysisStore(NYC, tmp)
            store.write_payload(date(2026, 6, 1), date(2026, 6, 2), payload)
            store.rebuild()

            coverage = store.coverage(date(2026, 6, 1), date(2026, 6, 2))
            ranges = store.missing_ranges(date(2026, 6, 1), date(2026, 6, 2))

            self.assertEqual(coverage["raw_covered_days"], 2)
            self.assertEqual(coverage["normalized_daily_days"], 1)
            self.assertEqual(coverage["covered_days"], 1)
            self.assertEqual(coverage["missing_days"], 1)
            self.assertEqual(coverage["raw_only_days"], ["2026-06-02"])
            self.assertEqual(coverage["raw_only_day_count"], 1)
            self.assertEqual(coverage["raw_only_normalizable_days"], [])
            self.assertEqual(coverage["raw_only_normalizable_day_count"], 0)
            self.assertEqual(coverage["raw_only_source_lag_days"], ["2026-06-02"])
            self.assertEqual(coverage["raw_only_source_lag_day_count"], 1)
            self.assertEqual(ranges, [])

    def test_reanalysis_coverage_flags_normalizable_raw_only_days(self):
        payload = {
            "hourly": {
                "time": ["2026-06-01T12:00", "2026-06-02T12:00"],
                "temperature_2m": [75.0, 76.0],
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            store = ReanalysisStore(NYC, tmp)
            store.write_payload(date(2026, 6, 1), date(2026, 6, 2), payload)

            coverage = store.coverage(date(2026, 6, 1), date(2026, 6, 2))

            self.assertEqual(coverage["raw_only_days"], ["2026-06-01", "2026-06-02"])
            self.assertEqual(coverage["raw_only_normalizable_days"], ["2026-06-01", "2026-06-02"])
            self.assertEqual(coverage["raw_only_normalizable_day_count"], 2)
            self.assertEqual(coverage["raw_only_source_lag_days"], [])
            self.assertEqual(
                store.missing_ranges(date(2026, 6, 1), date(2026, 6, 2)),
                [(date(2026, 6, 1), date(2026, 6, 2))],
            )

    def test_reanalysis_rich_variable_refresh_flags_stale_core_only_payloads(self):
        payload = {
            "hourly": {
                "time": ["2026-06-01T12:00", "2026-06-02T12:00"],
                "temperature_2m": [75.0, 76.0],
                "soil_temperature_0_to_7cm": [None, None],
                "soil_moisture_0_to_7cm": [None, None],
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            store = ReanalysisStore(NYC, tmp)
            store.write_payload(date(2026, 6, 1), date(2026, 6, 2), payload)
            store.rebuild()

            ranges = store.missing_ranges(
                date(2026, 6, 1),
                date(2026, 6, 2),
                required_hourly_variables=[
                    "soil_temperature_0_to_7cm",
                    "soil_moisture_0_to_7cm",
                ],
            )

            self.assertEqual(ranges, [(date(2026, 6, 1), date(2026, 6, 2))])

    def test_reanalysis_rich_variable_refresh_skips_complete_rich_payloads(self):
        payload = {
            "hourly": {
                "time": ["2026-06-01T12:00", "2026-06-02T12:00"],
                "temperature_2m": [75.0, 76.0],
                "soil_temperature_0_to_7cm": [73.0, 74.0],
                "soil_moisture_0_to_7cm": [0.25, 0.26],
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            store = ReanalysisStore(NYC, tmp)
            store.write_payload(date(2026, 6, 1), date(2026, 6, 2), payload)
            store.rebuild()

            ranges = store.missing_ranges(
                date(2026, 6, 1),
                date(2026, 6, 2),
                required_hourly_variables=[
                    "soil_temperature_0_to_7cm",
                    "soil_moisture_0_to_7cm",
                ],
            )

            self.assertEqual(ranges, [])
            self.assertIn("shortwave_radiation", RICH_REANALYSIS_HOURLY_VARIABLES)


if __name__ == "__main__":
    unittest.main()
