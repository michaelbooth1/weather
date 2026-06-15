import os
import sys
import unittest
import math
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.abspath("src"))

from forecast_error_model import (
    build_artifact,
    forecast_error_distribution,
    forecast_rows_from_daily_archive,
    forecast_rows_from_snapshot_folders,
    score_component_rows,
    summarize_error_rows,
)
from toronto_model import TorontoHighTempModel


def _artifact():
    rows = [
        {
            "target_date": "2020-05-27",
            "year": 2020,
            "source": "open_meteo",
            "source_kind": "daily_archive",
            "capture_hour": None,
            "horizon_bucket": "daily",
            "forecast_high_c": 24.0,
            "observed_high_c": 25.0,
            "observed_bucket": 25,
        },
        {
            "target_date": "2021-05-27",
            "year": 2021,
            "source": "open_meteo",
            "source_kind": "daily_archive",
            "capture_hour": None,
            "horizon_bucket": "daily",
            "forecast_high_c": 25.0,
            "observed_high_c": 26.0,
            "observed_bucket": 26,
        },
        {
            "target_date": "2022-05-27",
            "year": 2022,
            "source": "open_meteo",
            "source_kind": "daily_archive",
            "capture_hour": None,
            "horizon_bucket": "daily",
            "forecast_high_c": 26.0,
            "observed_high_c": 27.0,
            "observed_bucket": 27,
        },
    ]
    return build_artifact(rows, [])


class TestForecastErrorModel(unittest.TestCase):
    def test_summarize_error_rows_learns_source_bias(self):
        summary = summarize_error_rows([
            {"forecast_high_c": 24.0, "observed_high_c": 25.0},
            {"forecast_high_c": 26.0, "observed_high_c": 25.0},
        ])

        self.assertEqual(summary["n"], 2)
        self.assertAlmostEqual(summary["bias_observed_minus_forecast"], 0.0)
        self.assertAlmostEqual(summary["mae"], 1.0)
        self.assertAlmostEqual(summary["rmse"], 1.0)

    def test_daily_archive_rows_use_native_forecast_high_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "forecast_daily.csv"
            path.write_text(
                "\n".join([
                    "local_date,forecast_high_native,forecast_high_c",
                    "2026-06-07,91,33",
                ]) + "\n",
                encoding="utf-8",
            )
            rows = forecast_rows_from_daily_archive(
                path,
                {"2026-06-07": {"high_c": 92.0, "bucket": 92, "row_count": 24}},
            )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["forecast_high_c"], 91.0)

    def test_snapshot_forecast_rows_use_native_temperature_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "highest-temperature-in-toronto-on-june-7-2026"
            folder.mkdir()
            (folder / "snapshots_long.csv").write_text(
                "\n".join([
                    "event_slug,wu_history_high_c",
                    f"{folder.name},91",
                ]) + "\n",
                encoding="utf-8",
            )
            (folder / "forecasts_long.csv").write_text(
                "\n".join([
                    "snapshot_id,target_date,source,captured_at_local,forecast_high_native,forecast_high_c,target_temp_native,target_temp_c",
                    "s1,2026-06-07,open_meteo,2026-06-07T12:00:00-04:00,89,33,92,34",
                ]) + "\n",
                encoding="utf-8",
            )

            rows = forecast_rows_from_snapshot_folders(
                [folder],
                {"2026-06-07": {"high_c": 92.0, "bucket": 92, "row_count": 24}},
            )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["forecast_high_c"], 92.0)

    def test_distribution_is_normalized_and_respects_wu_floor(self):
        distribution = forecast_error_distribution(
            range(22, 29),
            [{"source": "open_meteo", "forecast_high_c": 25.0}],
            _artifact(),
            floor_bucket=25,
        )

        self.assertAlmostEqual(sum(distribution.values()), 1.0, places=6)
        self.assertEqual(distribution[24], 0.0)
        self.assertEqual(max(distribution, key=distribution.get), 26)

    def test_component_score_beats_point_cap_for_biased_source(self):
        rows = [
            {
                "target_date": f"202{i}-05-27",
                "year": 2020 + i,
                "source": "open_meteo",
                "source_kind": "daily_archive",
                "capture_hour": None,
                "horizon_bucket": "daily",
                "forecast_high_c": 24.0 + i,
                "observed_high_c": 25.0 + i,
                "observed_bucket": 25 + i,
            }
            for i in range(4)
        ]
        artifact = build_artifact(rows, [])
        score = score_component_rows(rows, artifact)

        self.assertLess(score["learned_brier"], score["cap_brier"])
        self.assertLess(score["learned_logloss"], score["cap_logloss"])

    def test_model_uses_forecast_error_artifact_for_forecast_component(self):
        model = TorontoHighTempModel(target_date="2026-05-28")
        model.forecast_error_model = _artifact()
        distribution = model.forecast_error_component_distribution(
            range(22, 29),
            observed_bucket=23,
            weather_forecast_max=None,
            open_meteo_max=25.0,
            eccc_forecast_high=None,
            hour=12,
        )

        self.assertAlmostEqual(sum(distribution.values()), 1.0, places=6)
        self.assertEqual(max(distribution, key=distribution.get), 26)

    def test_late_day_continuation_reports_forecast_tail_feature(self):
        model = TorontoHighTempModel(target_date="2026-05-28")
        model.forecast_error_model = _artifact()
        model.load_late_day_model_coefs = lambda: {
            "15": {
                "feature_names": [
                    "time_since_reached",
                    "high_so_far",
                    "current_temp",
                    "rise_from_7am",
                    "dewpoint_c",
                    "humidity",
                    "pressure",
                    "pressure_trend_3h",
                    "wind_speed_kmh",
                ],
                "coef": [0.0] * 9,
                "intercept": math.log(0.20 / 0.80),
                "scaler_mean": [0.0] * 9,
                "scaler_scale": [1.0] * 9,
                "imputer_median": [0.0] * 9,
                "empirical_prior": 0.20,
            }
        }
        sources = {
            "wu_history": {
                "ok": True,
                "data": {
                    "max_c": 20.0,
                    "rows": [
                        {
                            "time": "07:00",
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
                            "time": "15:00",
                            "temp_c": 20.0,
                            "dewpoint_c": 11.0,
                            "humidity": 55.0,
                            "pressure": 1014.0,
                            "wind": "W",
                            "wind_kmh": 14.0,
                            "condition": "Clear",
                            "clouds": "Clear",
                        },
                    ],
                },
            },
            "wu_current": {"ok": True, "data": {"temp_c": 20.0}},
            "weather_forecast": {"ok": True, "data": {"rows": []}},
            "open_meteo": {"ok": True, "data": {"rows": [], "day_max_c": 25.0}},
            "eccc_citypage": {"ok": True, "data": {}},
        }

        result = model.predict_late_day_continuation(
            sources,
            15,
            datetime(2026, 5, 28, 15, 30),
        )

        self.assertIsNotNone(result["forecast_tail_probability"])
        self.assertGreater(result["continuation_probability"], 0.20)
        self.assertEqual(result["forecast_high"], 25.0)

    def test_late_day_continuation_uses_forecast_gap_coefficient(self):
        model = TorontoHighTempModel(target_date="2026-05-28")
        model.forecast_error_component_distribution = lambda *args, **kwargs: None
        numeric = [
            "time_since_reached",
            "high_so_far",
            "current_temp",
            "rise_from_7am",
            "dewpoint_c",
            "humidity",
            "pressure",
            "pressure_trend_3h",
            "wind_speed_kmh",
            "forecast_high",
            "forecast_gap",
        ]
        model.load_late_day_model_coefs = lambda: {
            "15": {
                "feature_names": numeric,
                "numeric_feature_names": numeric,
                "numeric_feature_count": len(numeric),
                "coef": [0.0] * (len(numeric) - 1) + [1.0],
                "intercept": -2.0,
                "scaler_mean": [0.0] * len(numeric),
                "scaler_scale": [1.0] * len(numeric),
                "imputer_median": [0.0] * len(numeric),
                "empirical_prior": 0.20,
            }
        }
        sources = {
            "wu_history": {
                "ok": True,
                "data": {
                    "max_c": 20.0,
                    "rows": [
                        {
                            "time": "07:00",
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
                            "time": "15:00",
                            "temp_c": 20.0,
                            "dewpoint_c": 11.0,
                            "humidity": 55.0,
                            "pressure": 1014.0,
                            "wind": "W",
                            "wind_kmh": 14.0,
                            "condition": "Clear",
                            "clouds": "Clear",
                        },
                    ],
                },
            },
            "wu_current": {"ok": True, "data": {"temp_c": 20.0}},
            "weather_forecast": {"ok": True, "data": {"rows": []}},
            "open_meteo": {"ok": True, "data": {"rows": [], "day_max_c": 25.0}},
            "eccc_citypage": {"ok": True, "data": {}},
        }

        result = model.predict_late_day_continuation(
            sources,
            15,
            datetime(2026, 5, 28, 15, 30),
        )

        self.assertEqual(result["forecast_gap"], 5.0)
        self.assertGreater(result["continuation_probability"], 0.90)

    def test_late_day_continuation_uses_wind_gust_coefficient(self):
        model = TorontoHighTempModel(target_date="2026-05-28")
        model.forecast_error_component_distribution = lambda *args, **kwargs: None
        numeric = [
            "time_since_reached",
            "high_so_far",
            "current_temp",
            "rise_from_7am",
            "dewpoint_c",
            "humidity",
            "pressure",
            "pressure_trend_3h",
            "wind_speed_kmh",
            "wind_gust_kmh",
            "wind_shift_3h_degrees",
        ]
        model.load_late_day_model_coefs = lambda: {
            "15": {
                "feature_names": numeric,
                "numeric_feature_names": numeric,
                "numeric_feature_count": len(numeric),
                "coef": [0.0] * (len(numeric) - 2) + [0.2, 0.0],
                "intercept": -2.0,
                "scaler_mean": [0.0] * len(numeric),
                "scaler_scale": [1.0] * len(numeric),
                "imputer_median": [0.0] * len(numeric),
                "empirical_prior": 0.20,
            }
        }
        sources = {
            "wu_history": {
                "ok": True,
                "data": {
                    "max_c": 20.0,
                    "rows": [
                        {
                            "time": "12:00",
                            "temp_c": 18.0,
                            "dewpoint_c": 10.0,
                            "humidity": 60.0,
                            "pressure": 1015.0,
                            "wind": "W",
                            "wind_kmh": 12.0,
                            "gust_kmh": 12.0,
                            "condition": "Clear",
                            "clouds": "Clear",
                        },
                        {
                            "time": "15:00",
                            "temp_c": 20.0,
                            "dewpoint_c": 11.0,
                            "humidity": 55.0,
                            "pressure": 1014.0,
                            "wind": "S",
                            "wind_kmh": 14.0,
                            "gust_kmh": 30.0,
                            "condition": "Clear",
                            "clouds": "Clear",
                        },
                    ],
                },
            },
            "wu_current": {"ok": True, "data": {"temp_c": 20.0}},
            "weather_forecast": {"ok": True, "data": {"rows": []}},
            "open_meteo": {"ok": True, "data": {"rows": [], "day_max_c": 20.0}},
            "eccc_citypage": {"ok": True, "data": {}},
        }

        result = model.predict_late_day_continuation(
            sources,
            15,
            datetime(2026, 5, 28, 15, 30),
        )

        self.assertGreater(result["continuation_probability"], 0.95)


if __name__ == "__main__":
    unittest.main()
