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

sys.path.insert(0, os.path.abspath("src"))

from feature_store import build_historical_feature_record
from toronto_model import TorontoHighTempModel

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


if __name__ == "__main__":
    unittest.main()
