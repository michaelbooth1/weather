import json
import math
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path


sys.path.insert(0, os.path.abspath("src"))

from intraday_calibration import (
    cap_prior_distribution,
    market_group_distribution,
    weighted_component_dist,
)
import toronto_model
from toronto_model import TorontoHighTempModel


class TestIntradayCalibrationPrimitives(unittest.TestCase):
    def test_weighted_component_dist_normalizes_available_components(self):
        support = [24, 25, 26]
        components = {
            "climatology": {24: 0.2, 25: 0.6, 26: 0.2},
            "intraday_high": {24: 0.1, 25: 0.1, 26: 0.8},
            "wind_regime": None,
        }
        weights = {
            "climatology": 1.0,
            "intraday_high": 3.0,
            "wind_regime": 100.0,
        }

        result = weighted_component_dist(components, weights, support)

        self.assertAlmostEqual(sum(result.values()), 1.0)
        self.assertGreater(result[26], result[25])

    def test_cap_prior_distribution_penalizes_above_cap_and_below_floor(self):
        result = cap_prior_distribution([23, 24, 25, 26, 27], cap_bucket=25, floor_bucket=24)

        self.assertAlmostEqual(sum(result.values()), 1.0)
        self.assertGreater(result[25], result[27])
        self.assertGreater(result[24], result[23])

    def test_market_group_distribution_keeps_cumulative_bins_separate(self):
        grouped = market_group_distribution({18: 0.2, 20: 0.3, 29: 0.1, 31: 0.4})

        self.assertAlmostEqual(grouped["lte_19"], 0.2)
        self.assertAlmostEqual(grouped["eq_20"], 0.3)
        self.assertAlmostEqual(grouped["gte_29"], 0.5)


class TestTorontoModelCalibrationConfig(unittest.TestCase):
    def test_calibrated_hour_config_supports_new_schema(self):
        model = TorontoHighTempModel()
        model.calibrated_weights = {"hours": {"12": {"weights": {"climatology": 1.0}}}}

        self.assertEqual(
            model.calibrated_hour_config(12),
            {"weights": {"climatology": 1.0}},
        )

    def test_model_weighted_component_distribution(self):
        model = TorontoHighTempModel()
        result = model.weighted_component_distribution(
            {
                "climatology": {24: 0.5, 25: 0.5},
                "forecast_cap": {24: 0.9, 25: 0.1},
            },
            {"climatology": 1.0, "forecast_cap": 1.0},
        )

        self.assertFalse(any(math.isnan(value) for value in result.values()))
        self.assertAlmostEqual(sum(result.values()), 1.0)
        self.assertGreater(result[24], result[25])

    def test_ordinal_smoothing_fills_single_bucket_hole(self):
        model = TorontoHighTempModel()
        raw = {18: 0.06, 19: 0.44, 20: 0.02, 21: 0.28, 22: 0.20}

        result = model.ordinal_smooth_distribution(raw, sigma=0.75, blend_weight=0.50)

        self.assertAlmostEqual(sum(result.values()), 1.0)
        self.assertGreater(result[20], raw[20])
        self.assertLess(result[20], result[19])
        self.assertLess(result[20], result[21])

    def test_wunderground_observed_floor_suppresses_lower_buckets(self):
        model = TorontoHighTempModel(target_date="2026-05-28")
        model.calibrated_weights = None
        sources = {
            "local_history": {"ok": True, "data": {"available": False}},
            "wu_history": {"ok": True, "data": {"max_c": 16.0}},
            "wu_current": {
                "ok": True,
                "data": {"temp_c": 14.0, "max_since_7am_c": 14.0},
            },
            "eccc_swob": {"ok": True, "data": {"same_day_max_c": 16.9}},
            "eccc_citypage": {"ok": True, "data": {}},
            "metar": {"ok": True, "data": {}},
            "weather_forecast": {"ok": True, "data": {"rows": []}},
            "open_meteo": {"ok": True, "data": {"rows": []}},
        }

        distribution = model.estimate_distribution(sources)

        self.assertLess(distribution[15], 0.001)
        self.assertGreater(distribution[16], distribution[15])

    def test_feature_model_path_does_not_double_count_current_bucket(self):
        model = TorontoHighTempModel(target_date="2026-05-28")
        model.calibrated_weights = None
        model.predict_feature_distribution = lambda sources, cutoff_hour, now: (
            {17: 0.03, 18: 0.05, 19: 0.30, 20: 0.10, 21: 0.30, 22: 0.20},
            "hgb",
        )
        sources = {
            "local_history": {
                "ok": True,
                "data": {
                    "available": True,
                    "analysis": {
                        "target_window_count": 100,
                        "bucket_probabilities": {
                            "17": 0.06,
                            "18": 0.08,
                            "19": 0.10,
                            "20": 0.12,
                            "21": 0.16,
                            "22": 0.18,
                        },
                    },
                },
            },
            "wu_history": {"ok": True, "data": {"max_c": 16.0, "rows": []}},
            "wu_current": {
                "ok": True,
                "data": {"temp_c": 17.0, "max_since_7am_c": 17.0},
            },
            "eccc_swob": {"ok": True, "data": {"same_day_max_c": 16.9}},
            "eccc_citypage": {"ok": True, "data": {"forecast_high_c": 21.0}},
            "metar": {"ok": True, "data": {"temp_c": 17.0}},
            "weather_forecast": {
                "ok": True,
                "data": {"rows": [{"temp_c": 19.0, "cloud_cover": 30}]},
            },
            "open_meteo": {
                "ok": True,
                "data": {"rows": [{"temp_c": 20.0, "solar": 900}]},
            },
        }

        distribution = model.estimate_distribution(sources)

        self.assertLess(distribution[17], 0.08)
        self.assertGreater(sum(prob for bucket, prob in distribution.items() if bucket >= 18), 0.9)

    def test_current_max_since_7am_is_not_hard_resolution_floor(self):
        model = TorontoHighTempModel(target_date="2026-05-28")
        model.calibrated_weights = None
        model.predict_feature_distribution = lambda sources, cutoff_hour, now: (
            {18: 0.35, 19: 0.30, 20: 0.20, 21: 0.10, 22: 0.05},
            "hgb",
        )
        sources = {
            "local_history": {
                "ok": True,
                "data": {
                    "available": True,
                    "analysis": {
                        "target_window_count": 100,
                        "bucket_probabilities": {
                            "18": 0.08,
                            "19": 0.10,
                            "20": 0.12,
                            "21": 0.16,
                            "22": 0.18,
                        },
                    },
                },
            },
            "wu_history": {"ok": True, "data": {"max_c": 17.0, "rows": []}},
            "wu_current": {
                "ok": True,
                "data": {"temp_c": 18.0, "max_since_7am_c": 19.0},
            },
            "eccc_swob": {"ok": True, "data": {"same_day_max_c": 17.9}},
            "eccc_citypage": {"ok": True, "data": {"forecast_high_c": 22.0}},
            "metar": {"ok": True, "data": {"temp_c": 18.0}},
            "weather_forecast": {"ok": True, "data": {"rows": [{"temp_c": 20.0}]}},
            "open_meteo": {"ok": True, "data": {"rows": [{"temp_c": 20.0}]}},
        }

        distribution = model.estimate_distribution(sources)

        self.assertLess(distribution[17], 0.001)
        self.assertGreater(distribution[18], 0.05)

    def test_feature_model_uses_current_max_since_7am_as_soft_signal_only(self):
        model = TorontoHighTempModel(target_date="2026-05-28")
        model.calibrated_weights = None
        model.predict_feature_distribution = lambda sources, cutoff_hour, now: (
            {18: 0.55, 19: 0.20, 20: 0.15, 21: 0.07, 22: 0.03},
            "hgb",
        )

        def sources_with_current_max(current_max):
            return {
                "local_history": {
                    "ok": True,
                    "data": {
                        "available": True,
                        "analysis": {
                            "target_window_count": 100,
                            "bucket_probabilities": {
                                "18": 0.08,
                                "19": 0.10,
                                "20": 0.12,
                                "21": 0.16,
                                "22": 0.18,
                            },
                        },
                    },
                },
                "wu_history": {"ok": True, "data": {"max_c": 17.0, "rows": []}},
                "wu_current": {
                    "ok": True,
                    "data": {"temp_c": 18.0, "max_since_7am_c": current_max},
                },
                "eccc_swob": {"ok": True, "data": {"same_day_max_c": 17.9}},
                "eccc_citypage": {"ok": True, "data": {"forecast_high_c": 22.0}},
                "metar": {"ok": True, "data": {"temp_c": 18.0}},
                "weather_forecast": {"ok": True, "data": {"rows": [{"temp_c": 18.0}]}},
                "open_meteo": {"ok": True, "data": {"rows": [{"temp_c": 18.2}]}},
            }

        without_soft_max = model.estimate_distribution(sources_with_current_max(18.0))
        with_soft_max = model.estimate_distribution(sources_with_current_max(19.0))

        self.assertLess(with_soft_max[17], 0.001)
        self.assertGreater(with_soft_max[18], 0.05)
        self.assertGreater(with_soft_max[19], without_soft_max[19])
        self.assertLess(with_soft_max[18], without_soft_max[18])

    def test_current_temperature_is_not_hard_resolution_floor(self):
        model = TorontoHighTempModel(target_date="2026-05-28")
        model.calibrated_weights = None
        model.predict_feature_distribution = lambda sources, cutoff_hour, now: (
            {18: 0.45, 19: 0.30, 20: 0.15, 21: 0.07, 22: 0.03},
            "hgb",
        )
        sources = {
            "local_history": {
                "ok": True,
                "data": {
                    "available": True,
                    "analysis": {
                        "target_window_count": 100,
                        "bucket_probabilities": {
                            "18": 0.08,
                            "19": 0.10,
                            "20": 0.12,
                            "21": 0.16,
                            "22": 0.18,
                        },
                    },
                },
            },
            "wu_history": {"ok": True, "data": {"max_c": 18.0, "rows": []}},
            "wu_current": {
                "ok": True,
                "data": {"temp_c": 19.0, "max_since_7am_c": 19.0},
            },
            "eccc_swob": {"ok": True, "data": {"same_day_max_c": 17.9}},
            "eccc_citypage": {"ok": True, "data": {"forecast_high_c": 22.0}},
            "metar": {"ok": True, "data": {"temp_c": 18.0}},
            "weather_forecast": {"ok": True, "data": {"rows": [{"temp_c": 19.0}]}},
            "open_meteo": {"ok": True, "data": {"rows": [{"temp_c": 19.7}]}},
        }

        distribution = model.estimate_distribution(sources)
        explanation = model.get_model_explanation(sources, distribution)

        self.assertEqual(explanation["observed_floor"], 18)
        self.assertGreater(distribution[18], 0.01)
        self.assertGreater(distribution[19], 0.10)

    def test_eccc_swob_is_not_hard_resolution_floor(self):
        model = TorontoHighTempModel(target_date="2026-05-28")
        model.calibrated_weights = None
        model.predict_feature_distribution = lambda sources, cutoff_hour, now: (
            {19: 0.75, 20: 0.20, 21: 0.05},
            "hgb",
        )
        sources = {
            "local_history": {
                "ok": True,
                "data": {
                    "available": True,
                    "analysis": {
                        "target_window_count": 100,
                        "bucket_probabilities": {
                            "19": 0.20,
                            "20": 0.20,
                            "21": 0.20,
                            "22": 0.20,
                        },
                    },
                },
            },
            "wu_history": {"ok": True, "data": {"max_c": 19.0, "rows": []}},
            "wu_current": {
                "ok": True,
                "data": {"temp_c": 19.0, "max_since_7am_c": 21.0},
            },
            "eccc_swob": {"ok": True, "data": {"same_day_max_c": 19.6}},
            "eccc_citypage": {"ok": True, "data": {"forecast_high_c": 22.0}},
            "metar": {"ok": True, "data": {"temp_c": 19.0}},
            "weather_forecast": {"ok": True, "data": {"rows": [{"temp_c": 20.0}]}},
            "open_meteo": {"ok": True, "data": {"rows": [{"temp_c": 19.8}]}},
        }

        distribution = model.estimate_distribution(sources)
        explanation = model.get_model_explanation(sources, distribution)

        self.assertEqual(explanation["observed_floor"], 19)
        self.assertGreater(distribution[19], 0.10)
        self.assertGreater(distribution[20], 0.05)

    def test_feature_model_waits_for_wunderground_history_cutoff_row(self):
        model = TorontoHighTempModel(target_date="2026-05-28")
        model.calibrated_weights = None
        model.intraday_cutoff_hour = lambda _now: 15
        seen_cutoffs = []

        def capture_cutoff(_sources, cutoff_hour, _now):
            seen_cutoffs.append(cutoff_hour)
            return {19: 0.80, 20: 0.20}, "hgb"

        model.predict_feature_distribution = capture_cutoff
        sources = {
            "local_history": {
                "ok": True,
                "data": {
                    "available": True,
                    "analysis": {
                        "target_window_count": 100,
                        "bucket_probabilities": {"19": 0.25, "20": 0.25},
                    },
                },
            },
            "wu_history": {
                "ok": True,
                "data": {
                    "max_c": 19.0,
                    "rows": [{"time": "13:00", "temp_c": 19.0}, {"time": "14:00", "temp_c": 19.0}],
                },
            },
            "wu_current": {"ok": True, "data": {"temp_c": 19.0}},
            "eccc_swob": {"ok": True, "data": {}},
            "eccc_citypage": {"ok": True, "data": {}},
            "metar": {"ok": True, "data": {}},
            "weather_forecast": {"ok": True, "data": {"rows": []}},
            "open_meteo": {"ok": True, "data": {"rows": []}},
        }

        model.estimate_distribution(sources)

        self.assertEqual(seen_cutoffs, [13])

    def test_feature_model_collapses_correlated_peak_signals(self):
        model = TorontoHighTempModel(target_date="2026-05-28")
        model.calibrated_weights = None
        model.predict_feature_distribution = lambda sources, cutoff_hour, now: (
            {19: 0.30, 20: 0.40, 21: 0.10, 22: 0.15, 23: 0.05},
            "hgb",
        )
        sources = {
            "local_history": {
                "ok": True,
                "data": {
                    "available": True,
                    "analysis": {
                        "target_window_count": 100,
                        "bucket_probabilities": {
                            "19": 0.08,
                            "20": 0.10,
                            "21": 0.12,
                            "22": 0.16,
                            "23": 0.08,
                        },
                    },
                },
            },
            "wu_history": {"ok": True, "data": {"max_c": 19.0, "rows": []}},
            "wu_current": {
                "ok": True,
                "data": {"temp_c": 19.0, "max_since_7am_c": 20.0},
            },
            "eccc_swob": {"ok": True, "data": {"same_day_max_c": 18.6}},
            "eccc_citypage": {"ok": True, "data": {"forecast_high_c": 22.0}},
            "metar": {"ok": True, "data": {"temp_c": 19.0}},
            "weather_forecast": {"ok": True, "data": {"rows": [{"temp_c": 20.0}]}},
            "open_meteo": {"ok": True, "data": {"rows": [{"temp_c": 19.6}]}},
        }

        distribution = model.estimate_distribution(sources)

        self.assertGreater(distribution[20], distribution[19])
        self.assertLess(distribution[20], 0.60)
        self.assertGreater(
            sum(prob for bucket, prob in distribution.items() if bucket >= 21),
            0.10,
        )

    def test_feature_model_uses_cutoff_history_rows_for_live_features(self):
        class CapturingImputer:
            def __init__(self):
                self.seen = None

            def transform(self, frame):
                self.seen = frame.copy()
                return frame.to_numpy(dtype=float)

        class DummyHgb:
            classes_ = [18, 20]

            def predict_proba(self, _features):
                return [[0.75, 0.25]]

        model = TorontoHighTempModel(target_date="2026-05-28")
        imputer = CapturingImputer()
        feature_names = [
            "high_so_far",
            "current_temp",
            "rise_from_7am",
            "dewpoint_c",
            "humidity",
            "pressure",
            "pressure_trend_3h",
            "wind_speed_kmh",
        ]
        model.load_feature_model_hgb = lambda: {
            "12": {
                "model": DummyHgb(),
                "imputer": imputer,
                "feature_names": feature_names,
                "all_wind_groups": [],
                "all_cloud_groups": [],
            }
        }
        model.load_feature_model_coefs = lambda: None

        sources = {
            "wu_history": {
                "ok": True,
                "data": {
                    "rows": [
                        {
                            "time": "07:00",
                            "temp_c": 13.0,
                            "dewpoint_c": 8.0,
                            "humidity": 75.0,
                            "pressure": 101.0,
                            "wind_kmh": 8.0,
                            "wind": "W",
                            "condition": "Clear",
                            "clouds": "Clear",
                        },
                        {
                            "time": "12:00",
                            "temp_c": 18.0,
                            "dewpoint_c": 10.0,
                            "humidity": 55.0,
                            "pressure": 100.5,
                            "wind_kmh": 12.0,
                            "wind": "W",
                            "condition": "Partly Cloudy",
                            "clouds": "Partly Cloudy",
                        },
                        {
                            "time": "12:40",
                            "temp_c": 20.0,
                            "dewpoint_c": 12.0,
                            "humidity": 45.0,
                            "pressure": 100.1,
                            "wind_kmh": 20.0,
                            "wind": "SW",
                            "condition": "Sunny",
                            "clouds": "Clear",
                        },
                    ]
                },
            },
            "wu_current": {
                "ok": True,
                "data": {
                    "temp_c": 20.0,
                    "dewpoint_c": 12.0,
                    "humidity": 45.0,
                    "pressure": 100.1,
                    "wind_kmh": 20.0,
                    "wind": "SW",
                    "condition": "Sunny",
                    "cloud_phrase": "Clear",
                },
            },
            "weather_forecast": {"ok": True, "data": {"rows": []}},
            "eccc_citypage": {"ok": True, "data": {}},
        }

        probs, kind = model.predict_feature_distribution(
            sources,
            12,
            datetime(2026, 5, 28, 12, 45),
        )

        self.assertEqual(kind, "hgb")
        self.assertEqual(probs, {18: 0.75, 20: 0.25})
        self.assertAlmostEqual(imputer.seen.iloc[0]["high_so_far"], 18.0)
        self.assertAlmostEqual(imputer.seen.iloc[0]["current_temp"], 18.0)
        self.assertAlmostEqual(imputer.seen.iloc[0]["rise_from_7am"], 5.0)
        self.assertAlmostEqual(imputer.seen.iloc[0]["dewpoint_c"], 10.0)
        self.assertAlmostEqual(imputer.seen.iloc[0]["wind_speed_kmh"], 12.0)

    def test_analog_search_uses_cutoff_history_rows_for_today_features(self):
        model = TorontoHighTempModel(target_date="2026-05-28")
        model.historical_target_cache = lambda: {
            "daily": {date(2020, 5, 28): {"max_temp_c": 21.0, "bucket": 21}},
            "by_date": {
                date(2020, 5, 28): [
                    {
                        "minute_of_day": 420,
                        "temp_c": 13.0,
                        "dewpoint_c": 8.0,
                        "wind": "W",
                        "condition": "Clear",
                        "clouds": "Clear",
                    },
                    {
                        "minute_of_day": 720,
                        "temp_c": 18.0,
                        "dewpoint_c": 10.0,
                        "wind": "W",
                        "condition": "Partly Cloudy",
                        "clouds": "Partly Cloudy",
                    },
                    {
                        "minute_of_day": 780,
                        "temp_c": 20.0,
                        "dewpoint_c": 12.0,
                        "wind": "SW",
                        "condition": "Sunny",
                        "clouds": "Clear",
                    },
                ],
            },
        }
        sources = {
            "wu_history": {
                "ok": True,
                "data": {
                    "rows": [
                        {
                            "time": "07:00",
                            "temp_c": 13.0,
                            "dewpoint_c": 8.0,
                            "wind": "W",
                            "condition": "Clear",
                            "clouds": "Clear",
                        },
                        {
                            "time": "12:00",
                            "temp_c": 18.0,
                            "dewpoint_c": 10.0,
                            "wind": "W",
                            "condition": "Partly Cloudy",
                            "clouds": "Partly Cloudy",
                        },
                        {
                            "time": "12:40",
                            "temp_c": 20.0,
                            "dewpoint_c": 12.0,
                            "wind": "SW",
                            "condition": "Sunny",
                            "clouds": "Clear",
                        },
                    ]
                },
            },
            "wu_current": {
                "ok": True,
                "data": {"temp_c": 20.0, "dewpoint_c": 12.0, "wind": "SW"},
            },
            "weather_forecast": {"ok": True, "data": {"rows": []}},
            "eccc_citypage": {"ok": True, "data": {}},
        }

        result = model.find_analog_days(
            sources,
            12,
            datetime(2026, 5, 28, 12, 45),
            limit=1,
        )

        self.assertAlmostEqual(result["today_features"]["high_so_far"], 18.0)
        self.assertAlmostEqual(result["today_features"]["rise_from_7am"], 5.0)
        self.assertAlmostEqual(result["today_features"]["dewpoint_c"], 10.0)

    def test_last_good_cache_does_not_use_old_live_source(self):
        old_root = toronto_model.DEFAULT_DATA_ROOT
        with tempfile.TemporaryDirectory() as tmpdir:
            toronto_model.DEFAULT_DATA_ROOT = Path(tmpdir)
            try:
                now = datetime.now(toronto_model.TORONTO_TZ)
                cache_path = Path(tmpdir) / "last_good_sources.json"
                cache_path.write_text(
                    json.dumps(
                        {
                            "wu_current": {
                                "target_date": "2026-05-28",
                                "fetched_at": (now - timedelta(hours=3)).isoformat(),
                                "data": {"temp_c": 99.0},
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                model = TorontoHighTempModel(target_date="2026-05-28")
                blended = model.blend_with_last_good(
                    {
                        "wu_current": {
                            "ok": False,
                            "error": "feed failed",
                            "fetched_at": now.isoformat(),
                        }
                    }
                )
            finally:
                toronto_model.DEFAULT_DATA_ROOT = old_root

        self.assertFalse(blended["wu_current"]["ok"])
        self.assertFalse(blended["wu_current"]["stale"])
        self.assertEqual(blended["wu_current"]["data"], {})

    def test_transition_bucket_ignores_current_max_since_7am_floor(self):
        model = TorontoHighTempModel(target_date="2026-05-28")
        model.historical_target_cache = lambda: {
            "daily": {date(2020, 5, 28): {"bucket": 18}},
            "by_date": {
                date(2020, 5, 28): [{"minute_of_day": 720, "temp_c": 18.0}],
            },
        }
        sources = {
            "wu_history": {"ok": True, "data": {"max_c": 17.0}},
            "wu_current": {
                "ok": True,
                "data": {"temp_c": 19.0, "max_since_7am_c": 19.0},
            },
            "eccc_swob": {"ok": True, "data": {"same_day_max_c": 17.9}},
        }

        result = model.get_bucket_transitions(sources, now=datetime(2026, 5, 28, 12, 0))

        self.assertEqual(result["observed_bucket"], 17)
        self.assertEqual(result["current_max_bucket"], 17)


if __name__ == "__main__":
    unittest.main()
