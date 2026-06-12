import csv
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.abspath("src"))

from feature_store import (
    FEATURE_AUDIT_COLUMNS,
    FEATURE_COLUMNS,
    FEATURE_SCHEMA_VERSION,
    audit_row,
    build_historical_feature_record,
    build_live_feature_record,
)
from snapshot_tracker import SnapshotStore
from toronto_model import TORONTO_TZ, TorontoHighTempModel


class TestFeatureStore(unittest.TestCase):
    def test_live_feature_record_has_stable_schema(self):
        record = build_live_feature_record(
            "2026-05-28",
            12,
            datetime(2026, 5, 28, 12, 0, tzinfo=TORONTO_TZ),
            "model-v",
            {
                "high_so_far": 20.0,
                "current_temp": 19.5,
                "forecast_gap": 2.0,
                "wind_group": "W-NW",
            },
        )

        self.assertEqual(record["feature_schema_version"], FEATURE_SCHEMA_VERSION)
        self.assertEqual(record["cutoff_hour"], 12)
        self.assertEqual(record["forecast_gap"], 2.0)
        self.assertIn("wind_group", record)

    def test_audit_row_keeps_expected_columns(self):
        row = audit_row(
            {"snapshot_id": "s1", "event_slug": "event"},
            {"feature_schema_version": FEATURE_SCHEMA_VERSION, "high_so_far": 21.0},
        )

        self.assertEqual(set(row), set(FEATURE_AUDIT_COLUMNS))
        self.assertEqual(row["snapshot_id"], "s1")
        self.assertEqual(row["high_so_far"], 21.0)

    def test_model_build_returns_feature_vector(self):
        model = TorontoHighTempModel(target_date="2026-05-28")
        rows = [
            {"time": "07:00", "temp_c": 15.0, "dewpoint_c": 10.0, "humidity": 60.0, "pressure": 1015.0},
            {"time": "12:00", "temp_c": 20.0, "dewpoint_c": 11.0, "humidity": 55.0, "pressure": 1014.0},
        ]
        built = model.build(
            {"slug": "highest-temperature-in-toronto-on-may-28-2026", "markets": []},
            live_sources={
                "wu_history": {"ok": True, "data": {"max_c": 20.0, "rows": rows}},
                "wu_current": {"ok": True, "data": {"temp_c": 20.0}},
                "open_meteo": {"ok": True, "data": {"rows": [], "day_max_c": 23.0}},
            },
            historical_sources={},
            now=datetime(2026, 5, 28, 12, 0, tzinfo=TORONTO_TZ),
        )

        self.assertEqual(built["feature_vector"]["feature_schema_version"], FEATURE_SCHEMA_VERSION)
        self.assertAlmostEqual(built["feature_vector"]["forecast_gap"], 3.0)

    def test_historical_builder_matches_live_feature_extraction(self):
        model = TorontoHighTempModel(target_date="2026-05-28")
        rows = [
            {
                "time": "07:00",
                "minute_of_day": 420,
                "temp_c": 15.0,
                "dewpoint_c": 10.0,
                "humidity": 60.0,
                "pressure": 1015.0,
                "wind": "W",
                "wind_kmh": 12.0,
                "condition": "Clear",
                "clouds": "Clear",
            },
            {
                "time": "09:00",
                "minute_of_day": 540,
                "temp_c": 18.0,
                "dewpoint_c": 10.5,
                "humidity": 58.0,
                "pressure": 1014.5,
                "wind": "W",
                "wind_kmh": 13.0,
                "condition": "Clear",
                "clouds": "Clear",
            },
            {
                "time": "12:00",
                "minute_of_day": 720,
                "temp_c": 20.0,
                "dewpoint_c": 11.0,
                "humidity": 55.0,
                "pressure": 1014.0,
                "wind": "W",
                "wind_kmh": 14.0,
                "condition": "Clear",
                "clouds": "Clear",
            },
        ]
        live = model.extract_live_features({
            "wu_history": {"ok": True, "data": {"rows": rows}},
            "wu_current": {"ok": True, "data": {"temp_c": 20.0}},
            "open_meteo": {"ok": True, "data": {"rows": [], "day_max_c": 23.0}},
        }, cutoff_hour=12)
        historical = build_historical_feature_record(
            "2026-05-28",
            rows,
            {"bucket": 20},
            12,
            forecast_high=23.0,
            wind_group_fn=model.wind_group,
            cloud_group_fn=model.cloud_group,
        )

        for column in FEATURE_COLUMNS:
            self.assertEqual(historical[column], live[column], column)

    def test_live_features_measure_forecast_source_disagreement(self):
        model = TorontoHighTempModel(target_date="2026-05-28")
        features = model.extract_live_features({
            "wu_history": {"ok": True, "data": {"rows": [
                {"time": "12:00", "temp_c": 20.0, "dewpoint_c": 11.0, "humidity": 55.0, "pressure": 1014.0},
            ]}},
            "wu_current": {"ok": True, "data": {"temp_c": 20.0}},
            "open_meteo": {"ok": True, "data": {"rows": [], "day_max_c": 23.0}},
            "weather_forecast": {"ok": True, "data": {"rows": [
                {"time": "13:00", "temp_c": 25.0},
                {"time": "14:00", "temp_c": 24.0},
            ]}},
            "eccc_citypage": {"ok": True, "data": {}},
        }, cutoff_hour=12)

        self.assertEqual(features["forecast_high"], 24.0)
        self.assertEqual(features["forecast_source_count"], 2)
        self.assertEqual(features["forecast_disagreement"], 2.0)

    def test_live_features_include_nws_and_global_ensemble_forecasts(self):
        model = TorontoHighTempModel(target_date="2026-05-28")
        features = model.extract_live_features({
            "wu_history": {"ok": True, "data": {"rows": [
                {"time": "12:00", "temp_c": 20.0, "dewpoint_c": 11.0, "humidity": 55.0, "pressure": 1014.0},
            ]}},
            "wu_current": {"ok": True, "data": {"temp_c": 20.0}},
            "open_meteo": {"ok": True, "data": {"rows": [], "day_max_c": 23.0}},
            "weather_forecast": {"ok": True, "data": {"rows": [{"time": "13:00", "temp_c": 25.0}]}},
            "nws_hourly": {"ok": True, "data": {"rows": [], "day_max_c": 26.0}},
            "global_ensemble": {"ok": True, "data": {"rows": [], "day_max_c": 24.0}},
            "eccc_citypage": {"ok": True, "data": {}},
        }, cutoff_hour=12)

        self.assertEqual(features["forecast_high"], 24.5)
        self.assertEqual(features["forecast_source_count"], 4)
        self.assertEqual(features["forecast_disagreement"], 3.0)

    def test_snapshot_store_persists_feature_vector(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SnapshotStore(root=root, event_slug="event")
            captured_at = datetime(2026, 5, 28, 12, 0, tzinfo=TORONTO_TZ)
            model_client = TorontoHighTempModel(target_date="2026-05-28")
            model = {
                "distribution": {20: 1.0},
                "top_temp": 20,
                "model_version": "model-v",
                "sources": {},
                "distribution_components": {
                    "schema_version": "components-v",
                    "cutoff_hour": 12,
                    "active_model_kind": "hgb",
                    "components": {
                        "feature_model": {19: 0.2, 20: 0.5, 21: 0.3},
                    },
                },
                "feature_vector": {
                    "target_date": "2026-05-28",
                    "feature_schema_version": FEATURE_SCHEMA_VERSION,
                    "cutoff_hour": 12,
                    "high_so_far": 20.0,
                },
            }
            event = {
                "markets": [
                    {
                        "groupItemTitle": "20 C",
                        "outcomes": '["Yes","No"]',
                        "outcomePrices": '["0.40","0.60"]',
                    },
                    {
                        "groupItemTitle": "21 C or higher",
                        "outcomes": '["Yes","No"]',
                        "outcomePrices": '["0.30","0.70"]',
                    },
                ],
                "slug": "event",
            }

            result = store.write(event, model, model_client, captured_at)
            rows = list(csv.DictReader((root / "features_long.csv").open(encoding="utf-8", newline="")))
            component_rows = list(csv.DictReader((root / "components_long.csv").open(encoding="utf-8", newline="")))

            self.assertEqual(result["features_path"], str(root / "features_long.csv"))
            self.assertEqual(result["components_path"], str(root / "components_long.csv"))
            self.assertEqual(rows[0]["snapshot_id"], captured_at.strftime("%Y%m%dT%H%M%S%z"))
            self.assertEqual(rows[0]["feature_schema_version"], FEATURE_SCHEMA_VERSION)
            self.assertEqual(len(component_rows), 2)
            self.assertEqual(component_rows[0]["component_schema_version"], "components-v")
            self.assertEqual(component_rows[0]["component_name"], "feature_model")
            self.assertAlmostEqual(float(component_rows[0]["component_probability"]), 0.5)
            self.assertAlmostEqual(float(component_rows[1]["component_probability"]), 0.3)


if __name__ == "__main__":
    unittest.main()
