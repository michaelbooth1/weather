"""Train/serve feature-extraction skew guard.

The feature model is trained on features built by
``feature_store.build_historical_feature_record`` (historical rows keyed by
``minute_of_day``) but served on features built by
``model_features.extract_live_features`` (live source rows keyed by ``time``).
They are two implementations of the *same* feature contract, kept separate only
because their input row shapes differ. The danger of that duplication is silent
drift: edit one path and the served features no longer match what the model was
trained on (train/serve skew).

This pins the contract: given equivalent observations, both extractors must
produce identical core features. If a future edit diverges them, this fails.
"""
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.abspath("src"))

from feature_store import build_historical_feature_record, simulated_reading_at
from toronto_model import TORONTO_TZ, TorontoHighTempModel

CUTOFF_HOUR = 14
FORECAST_HIGH = 26.0

# One set of observations, expressed once. The two extractors read different
# row shapes, so we render the same obs into each shape from this source.
OBS = [
    # (hh, mm, temp_c, dewpoint_c, humidity, pressure, wind_kmh, wind, condition)
    (7, 0, 16.0, 10.0, 70.0, 1016.0, 10.0, "SW", "Fair"),
    (11, 0, 22.0, 11.0, 55.0, 1015.0, 14.0, "SW", "Fair"),
    (14, 0, 24.0, 11.0, 48.0, 1014.0, 18.0, "SW", "Fair"),
]

SHARED_FEATURES = [
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
    "minutes_since_cutoff",
    "live_reading_temp",
    "live_reading_minus_high",
    "wind_group",
    "cloud_group",
]


def historical_rows():
    return [
        {
            "minute_of_day": hh * 60 + mm,
            "temp_c": temp, "dewpoint_c": dew, "humidity": hum,
            "pressure": pres, "wind_kmh": wind_kmh,
            "wind": wind, "condition": cond, "clouds": None,
        }
        for (hh, mm, temp, dew, hum, pres, wind_kmh, wind, cond) in OBS
    ]


def live_sources():
    rows = [
        {
            "time": f"{hh:02d}:{mm:02d}",
            "temp_c": temp, "dewpoint_c": dew, "humidity": hum,
            "pressure": pres, "wind_kmh": wind_kmh,
            "wind": wind, "condition": cond, "clouds": None,
        }
        for (hh, mm, temp, dew, hum, pres, wind_kmh, wind, cond) in OBS
    ]
    ok = lambda data: {"ok": True, "data": data}
    return {
        "wu_history": ok({"rows": rows, "max_c": 24.0}),
        "wu_current": ok({"temp_c": 24.0}),
        "weather_forecast": ok({"rows": []}),
        "eccc_citypage": ok({}),
        "open_meteo": ok({"rows": [], "day_max_c": FORECAST_HIGH}),
    }


class TestFeatureSkew(unittest.TestCase):
    def test_train_and_serve_extractors_agree(self):
        model = TorontoHighTempModel(target_date=None)

        train = build_historical_feature_record(
            local_date="2026-06-02",
            rows=historical_rows(),
            daily={"bucket": 24},
            cutoff_hour=CUTOFF_HOUR,
            forecast_high=FORECAST_HIGH,
            wind_group_fn=model.wind_group,
            cloud_group_fn=model.cloud_group,
        )
        serve = model.extract_live_features(live_sources(), CUTOFF_HOUR)

        self.assertIsNotNone(train)
        for feature in SHARED_FEATURES:
            with self.subTest(feature=feature):
                self.assertEqual(
                    train[feature], serve[feature],
                    f"train/serve skew on {feature}: train={train[feature]} serve={serve[feature]}",
                )

    def test_intra_hour_live_reading_parity(self):
        # Item 40 (schema v0.3): at wall 14:30 with prints through 14:00, the
        # live side reads wu_current 25.0; the training side simulates the
        # same contemporaneous reading by interpolating the bracketing obs
        # (24.0 @14:00, 26.0 @15:00 -> 25.0 @14:30). Printed-path features
        # must stay at the 14:00 cutoff on BOTH sides.
        model = TorontoHighTempModel(target_date=None)

        hist_rows = historical_rows() + [{
            "minute_of_day": 15 * 60, "temp_c": 26.0, "dewpoint_c": 11.0,
            "humidity": 45.0, "pressure": 1013.0, "wind_kmh": 18.0,
            "wind": "SW", "condition": "Fair", "clouds": None,
        }]
        train = build_historical_feature_record(
            local_date="2026-06-02",
            rows=hist_rows,
            daily={"bucket": 26},
            cutoff_hour=CUTOFF_HOUR,
            forecast_high=FORECAST_HIGH,
            wind_group_fn=model.wind_group,
            cloud_group_fn=model.cloud_group,
            wall_minute=CUTOFF_HOUR * 60 + 30,
        )

        sources = live_sources()
        sources["wu_current"]["data"]["temp_c"] = 25.0
        serve = model.extract_live_features(
            sources, CUTOFF_HOUR,
            now=datetime(2026, 6, 2, 14, 30, tzinfo=TORONTO_TZ),
        )

        for feature in SHARED_FEATURES:
            with self.subTest(feature=feature):
                self.assertEqual(
                    train[feature], serve[feature],
                    f"train/serve skew on {feature}: train={train[feature]} serve={serve[feature]}",
                )
        self.assertEqual(serve["minutes_since_cutoff"], 30.0)
        self.assertEqual(serve["live_reading_temp"], 25.0)
        self.assertEqual(serve["live_reading_minus_high"], 1.0)
        self.assertEqual(serve["high_so_far"], 24.0)   # printed path untouched

    def test_sanity_of_extracted_values(self):
        # Guards that the test inputs actually exercise the derivations (not all
        # defaults), so the agreement above is meaningful.
        model = TorontoHighTempModel(target_date=None)
        serve = model.extract_live_features(live_sources(), CUTOFF_HOUR)
        self.assertEqual(serve["high_so_far"], 24.0)
        self.assertEqual(serve["rise_from_7am"], 8.0)          # 24 - 16
        self.assertEqual(serve["pressure_trend_3h"], -1.0)     # 1014 - 1015
        self.assertEqual(serve["forecast_gap"], 2.0)           # 26 - 24
        self.assertEqual(serve["wind_group"], "S-SW")
        self.assertEqual(serve["cloud_group"], "Fair/clear")


class TestSimulatedReading(unittest.TestCase):
    """simulated_reading_at: a real obs within the exact window wins;
    otherwise interpolate the bracketing obs; never read past the wall
    minute for the printed path (only the reading proxy)."""

    ROWS = [
        {"minute_of_day": 840, "temp_c": 24.0},
        {"minute_of_day": 878, "temp_c": 24.8},   # an intra-hour special obs
        {"minute_of_day": 900, "temp_c": 26.0},
    ]

    def test_exact_obs_within_window_wins(self):
        # 14:42, special at 14:38 (4 min before): use it directly.
        self.assertEqual(simulated_reading_at(self.ROWS, 882), 24.8)

    def test_interpolates_between_brackets(self):
        # 14:30 between 14:00 (24.0) and 14:38 (24.8): 24 + 0.8*(30/38)
        self.assertAlmostEqual(
            simulated_reading_at(self.ROWS, 870), 24.0 + 0.8 * 30 / 38, places=9
        )

    def test_trailing_minutes_fall_back_to_latest_within_lookback(self):
        # 15:40 with nothing after 15:00: the 15:00 obs (40 min old) stands in.
        self.assertEqual(simulated_reading_at(self.ROWS, 940), 26.0)

    def test_too_stale_returns_none(self):
        self.assertIsNone(simulated_reading_at(self.ROWS, 900 + 76))

    def test_empty_rows_return_none(self):
        self.assertIsNone(simulated_reading_at([], 870))


if __name__ == "__main__":
    unittest.main()
