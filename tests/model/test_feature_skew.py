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
from weather.model.feature_store import FEATURE_COLUMNS, build_historical_feature_record, simulated_reading_at
from weather.model.toronto_model import TORONTO_TZ, TorontoHighTempModel

CUTOFF_HOUR = 14
FORECAST_HIGH = 26.0

# One set of observations, expressed once. The two extractors read different
# row shapes, so we render the same obs into each shape from this source.
OBS = [
    # (hh, mm, temp_c, dewpoint_c, humidity, pressure, wind_kmh, wind, condition)
    (7, 0, 16.0, 10.0, 70.0, 1016.0, 10.0, "W", "Fair"),
    (11, 0, 22.0, 11.0, 55.0, 1015.0, 14.0, "W", "Fair"),
    (14, 0, 24.0, 11.0, 48.0, 1014.0, 18.0, "S", "Fair"),
]

SHARED_FEATURES = list(FEATURE_COLUMNS)


def historical_rows():
    return [
        {
            "minute_of_day": hh * 60 + mm,
            "temp_c": temp, "dewpoint_c": dew, "humidity": hum,
            "pressure": pres, "wind_kmh": wind_kmh,
            "gust_kmh": wind_kmh + 5.0,
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
            "gust_kmh": wind_kmh + 5.0,
            "wind": wind, "condition": cond, "clouds": None,
        }
        for (hh, mm, temp, dew, hum, pres, wind_kmh, wind, cond) in OBS
    ]
    ok = lambda data: {"ok": True, "data": data}
    return {
        "wu_history": ok({"rows": rows, "max_c": 24.0}),
        "wu_current": ok({"temp_c": 24.0, "max_since_7am_c": 24.0}),
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
            microclimate_feature_fn=model.microclimate_features,
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
            "gust_kmh": 23.0,
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
            microclimate_feature_fn=model.microclimate_features,
            wall_minute=CUTOFF_HOUR * 60 + 30,
        )

        sources = live_sources()
        sources["wu_current"]["data"]["temp_c"] = 25.0
        sources["wu_current"]["data"]["max_since_7am_c"] = 25.0
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

    def test_miami_20260615_140914_print_lag_aliases_to_13h_features(self):
        # Item 58 replay fixture:
        # highest-temperature-in-miami-on-june-15-2026 / 20260615T140914-0400.
        # At wall 14:09, WU history latest was a 12:53 settlement-source print
        # at 93 F. That row is part of the 13h trained printed path, even
        # though it is not an exact 13:00 row.
        model = TorontoHighTempModel(target_date="2026-06-15", market_id="miami")
        now = datetime(2026, 6, 15, 14, 9, tzinfo=TORONTO_TZ)

        def row(time, temp, pressure):
            return {
                "time": time,
                "datetime": f"2026-06-15T{time}:00-04:00",
                "temp_c": temp,
                "dewpoint_c": 75.0,
                "humidity": 58.0,
                "pressure": pressure,
                "wind_kmh": 12.0,
                "wind": "S",
                "condition": "Fair",
                "clouds": "Clear",
            }

        live_rows = [
            row("07:00", 80.0, 1016.0),
            row("10:00", 86.0, 1015.0),
            row("11:00", 89.0, 1014.5),
            row("12:00", 91.0, 1014.2),
            row("12:53", 93.0, 1014.0),
        ]
        ok = lambda data: {"ok": True, "data": data}
        live_sources_for_alias = {
            "wu_history": ok({"rows": live_rows, "max_c": 93.0, "max_times": ["12:53"]}),
        }
        cutoff = model.effective_intraday_cutoff_hour(now, live_rows)
        self.assertEqual(cutoff, 13)

        serve_sources = {
            **live_sources_for_alias,
            "wu_current": ok({
                "temp_c": 93.0,
                "dewpoint_c": 75.0,
                "humidity": 58.0,
                "max_since_7am_c": 93.0,
            }),
            "open_meteo": ok({"rows": [], "day_rows": [], "day_max_c": 96.0}),
            "weather_forecast": ok({"rows": []}),
            "eccc_citypage": ok({}),
        }
        serve = model.extract_live_features(serve_sources, cutoff, now=now)

        historical_rows = [
            {**item, "minute_of_day": model.minute_of_day(item["time"])}
            for item in [*live_rows, row("14:00", 93.0, 1013.8)]
        ]
        train = build_historical_feature_record(
            local_date="2026-06-15",
            rows=historical_rows,
            daily={"bucket": 93},
            cutoff_hour=cutoff,
            forecast_high=96.0,
            wind_group_fn=model.wind_group,
            cloud_group_fn=model.cloud_group,
            microclimate_feature_fn=model.microclimate_features,
            wall_minute=14 * 60 + 9,
        )

        self.assertIsNotNone(train)
        for feature in SHARED_FEATURES:
            with self.subTest(feature=feature):
                self.assertEqual(
                    train[feature], serve[feature],
                    f"train/serve skew on {feature}: train={train[feature]} serve={serve[feature]}",
                )
        self.assertEqual(serve["high_so_far"], 93.0)
        self.assertEqual(serve["current_temp"], 93.0)
        self.assertEqual(serve["minutes_since_cutoff"], 69.0)
        self.assertEqual(serve["latest_wu_history_time"], "12:53")
        self.assertEqual(serve["latest_wu_history_minute"], 12 * 60 + 53)
        self.assertEqual(serve["latest_wu_history_temp"], 93.0)

    def test_sanity_of_extracted_values(self):
        # Guards that the test inputs actually exercise the derivations (not all
        # defaults), so the agreement above is meaningful.
        model = TorontoHighTempModel(target_date=None)
        serve = model.extract_live_features(live_sources(), CUTOFF_HOUR)
        self.assertEqual(serve["high_so_far"], 24.0)
        self.assertEqual(serve["rise_from_7am"], 8.0)          # 24 - 16
        self.assertEqual(serve["pressure_trend_3h"], -1.0)     # 1014 - 1015
        self.assertEqual(serve["wind_gust_kmh"], 23.0)
        self.assertEqual(serve["wind_shift_3h_degrees"], 90.0)  # W -> S
        self.assertEqual(serve["forecast_gap"], 2.0)           # 26 - 24
        self.assertEqual(serve["forecast_source_count"], 1)
        # One source provides no cross-source disagreement observation.  It is
        # missing, not evidence of perfect agreement.
        self.assertIsNone(serve["forecast_disagreement"])
        self.assertEqual(serve["wind_group"], "S-SW")
        self.assertEqual(serve["cloud_group"], "Fair/clear")

    def test_station_wind_features_reach_fahrenheit_serving_in_artifact_units(self):
        model = TorontoHighTempModel(target_date="2025-06-15", market_id="nyc")
        ok = lambda data: {"ok": True, "data": data}
        sources = {
            "metar": ok({
                "rows": [
                    {
                        "time": "07:00",
                        "temp_native": 70.0,
                        "wind_dir": 270.0,
                        "wind_gust": None,
                    },
                    {
                        "time": "11:00",
                        "temp_native": 81.0,
                        "wind_dir": 270.0,
                        "wind_gust": 12.0,
                    },
                    {
                        "time": "14:00",
                        "temp_native": 86.0,
                        "wind_dir": 180.0,
                        "wind_gust": 16.0,
                    },
                    {
                        "time": "15:00",
                        "temp_native": 88.0,
                        "wind_dir": 90.0,
                        "wind_gust": 40.0,
                    },
                ],
                "latest": {"time": "15:00", "temp_native": 88.0},
                "max_since_7am_native": 88.0,
            }),
            "open_meteo": ok({"rows": [], "day_rows": [], "day_max_native": 90.0}),
            "weather_forecast": ok({"rows": []}),
            "eccc_citypage": ok({}),
        }

        serve = model.extract_live_features(sources, CUTOFF_HOUR)

        self.assertAlmostEqual(
            serve["wind_gust_kmh"],
            16.0 * 1.1507794480235425,
        )
        self.assertEqual(serve["wind_shift_3h_degrees"], 90.0)

    def test_station_local_meteorology_reaches_fahrenheit_serving_in_native_units(self):
        model = TorontoHighTempModel(target_date="2025-06-15", market_id="nyc")
        ok = lambda data: {"ok": True, "data": data}
        rows = [
            {
                "time": "07:00",
                "temp_native": 70.0,
                "dewpoint_native": 61.0,
                "humidity": 70.0,
                "pressure": 29.98,
                "wind_kmh": 6.0,
            },
            {
                "time": "11:00",
                "temp_native": 81.0,
                "dewpoint_native": 63.0,
                "humidity": 55.0,
                "pressure": 29.95,
                "wind_kmh": 9.0,
            },
            {
                "time": "14:00",
                "temp_native": 86.0,
                "dewpoint_native": 64.0,
                "humidity": 48.0,
                "pressure": 29.92,
                "wind_kmh": 12.0,
            },
        ]
        sources = {
            "metar": ok({
                "rows": rows,
                "latest": rows[-1],
                "max_since_7am_native": 86.0,
            }),
            "open_meteo": ok({"rows": [], "day_rows": [], "day_max_native": 90.0}),
            "weather_forecast": ok({"rows": []}),
            "eccc_citypage": ok({}),
        }

        serve = model.extract_live_features(sources, CUTOFF_HOUR)

        self.assertEqual(serve["rise_from_7am"], 16.0)
        self.assertEqual(serve["warming_rate_2h"], 5.0)
        self.assertEqual(serve["hours_at_peak"], 0.0)
        self.assertEqual(serve["dewpoint_c"], 64.0)
        self.assertEqual(serve["humidity"], 48.0)
        self.assertEqual(serve["pressure"], 29.92)
        self.assertAlmostEqual(serve["pressure_trend_3h"], -0.03)
        self.assertEqual(serve["wind_speed_kmh"], 12.0)

    def test_station_local_meteorology_reparses_retained_swob_xml(self):
        model = TorontoHighTempModel(target_date="2025-06-15", market_id="toronto")
        ok = lambda data: {"ok": True, "data": data}

        def swob_xml(utc_time, temp, dewpoint, humidity, pressure, wind_speed):
            return (
                "<om:Observation xmlns:om=\"urn:om\">"
                f'<element name="date_tm" value="{utc_time}" />'
                f'<element name="air_temp" value="{temp}" />'
                f'<element name="dwpt_temp" value="{dewpoint}" />'
                f'<element name="rel_hum" value="{humidity}" />'
                f'<element name="stn_pres" value="{pressure}" />'
                f'<element name="avg_wnd_spd_10m_pst2mts" value="{wind_speed}" />'
                "</om:Observation>"
            )

        sources = {
            "eccc_swob": ok({
                "rows": [{"local_time": "14:00", "air_temp_native": 24.0}],
                "latest": {"local_time": "14:00", "air_temp_native": 24.0},
                "max_since_7am_native": 24.0,
                "raw_payload": {"files": [
                    {"text": swob_xml("2025-06-15T11:00:00Z", 16, 10, 70, 1016, 10)},
                    {"text": swob_xml("2025-06-15T15:00:00Z", 22, 11, 55, 1015, 14)},
                    {"text": swob_xml("2025-06-15T18:00:00Z", 24, 12, 48, 1014, 18)},
                ]},
            }),
            "open_meteo": ok({"rows": [], "day_rows": [], "day_max_native": 26.0}),
            "weather_forecast": ok({"rows": []}),
            "eccc_citypage": ok({}),
        }

        serve = model.extract_live_features(sources, CUTOFF_HOUR)

        self.assertEqual(serve["rise_from_7am"], 8.0)
        self.assertEqual(serve["warming_rate_2h"], 2.0)
        self.assertEqual(serve["hours_at_peak"], 0.0)
        self.assertEqual(serve["dewpoint_c"], 12.0)
        self.assertEqual(serve["humidity"], 48.0)
        self.assertEqual(serve["pressure"], 1014.0)
        self.assertEqual(serve["pressure_trend_3h"], -1.0)
        self.assertEqual(serve["wind_speed_kmh"], 18.0)

    def test_toronto_uses_alternate_metar_wind_without_aliasing_altimeter_pressure(self):
        model = TorontoHighTempModel(target_date="2025-06-15", market_id="toronto")
        ok = lambda data: {"ok": True, "data": data}
        sources = {
            "eccc_swob": ok({
                "rows": [
                    {"local_time": "07:00", "air_temp_native": 16.0, "humidity": 70.0},
                    {"local_time": "14:00", "air_temp_native": 24.0, "humidity": 48.0},
                ],
                "max_since_7am_native": 24.0,
            }),
            "metar": ok({
                "rows": [
                    {"time": "14:00", "temp_native": 24.0, "wind_speed": 10.0,
                     "pressure_hpa": 1015.0},
                ],
            }),
            "open_meteo": ok({"rows": [], "day_rows": [], "day_max_native": 26.0}),
            "weather_forecast": ok({"rows": []}),
            "eccc_citypage": ok({}),
        }

        serve = model.extract_live_features(sources, CUTOFF_HOUR)

        self.assertEqual(serve["humidity"], 48.0)
        self.assertEqual(serve["wind_speed_kmh"], 18.52)
        self.assertIsNone(serve["pressure"])
        self.assertIsNone(serve["pressure_trend_3h"])

    def test_station_wind_gust_stays_missing_when_provider_reports_none(self):
        model = TorontoHighTempModel(target_date="2025-06-15", market_id="toronto")
        ok = lambda data: {"ok": True, "data": data}
        def swob_xml(utc_time, direction, gust=None):
            gust_element = (
                f'<element name="max_wnd_gst_spd_10m_pst10mts" value="{gust}" />'
                if gust is not None
                else ""
            )
            return (
                "<om:Observation xmlns:om=\"urn:om\">"
                f'<element name="date_tm" value="{utc_time}" />'
                '<element name="air_temp" value="24.0" />'
                f'<element name="avg_wnd_dir_10m_pst2mts" value="{direction}" />'
                f"{gust_element}"
                "</om:Observation>"
            )
        sources = {
            "eccc_swob": ok({
                "rows": [
                    {
                        "local_time": "11:00",
                        "local_date": "2025-06-15",
                        "air_temp_native": 22.0,
                    },
                    {
                        "local_time": "14:00",
                        "local_date": "2025-06-15",
                        "air_temp_native": 24.0,
                    },
                ],
                "latest": {"local_time": "14:00", "air_temp_native": 24.0},
                "max_since_7am_native": 24.0,
                "raw_payload": {
                    "files": [
                        {"text": swob_xml("2025-06-15T15:00:00Z", 270, 19)},
                        {"text": swob_xml("2025-06-15T18:00:00Z", 180)},
                    ],
                },
            }),
            "open_meteo": ok({"rows": [], "day_rows": [], "day_max_native": 26.0}),
            "weather_forecast": ok({"rows": []}),
            "eccc_citypage": ok({}),
        }

        serve = model.extract_live_features(sources, CUTOFF_HOUR)

        self.assertIsNone(serve["wind_gust_kmh"])
        self.assertEqual(serve["wind_shift_3h_degrees"], 90.0)

    def test_toronto_onshore_microclimate_features_match_between_train_and_live(self):
        model = TorontoHighTempModel(target_date="2026-06-02", market_id="toronto")
        obs = [
            (7, 0, 16.0, 10.0, 70.0, 1016.0, 7.0, "E", "Fair"),
            (11, 0, 22.0, 11.0, 55.0, 1015.0, 10.0, "E", "Fair"),
            (14, 0, 24.0, 11.0, 48.0, 1014.0, 12.0, "E", "Fair"),
        ]
        hist_rows = [
            {
                "minute_of_day": hh * 60 + mm,
                "temp_c": temp,
                "dewpoint_c": dew,
                "humidity": hum,
                "pressure": pres,
                "wind_kmh": wind_kmh,
                "wind": wind,
                "condition": cond,
                "clouds": None,
            }
            for (hh, mm, temp, dew, hum, pres, wind_kmh, wind, cond) in obs
        ]
        live_rows = [
            {**row, "time": f"{row['minute_of_day'] // 60:02d}:{row['minute_of_day'] % 60:02d}"}
            for row in hist_rows
        ]
        train = build_historical_feature_record(
            local_date="2026-06-02",
            rows=hist_rows,
            daily={"bucket": 24},
            cutoff_hour=CUTOFF_HOUR,
            forecast_high=FORECAST_HIGH,
            wind_group_fn=model.wind_group,
            cloud_group_fn=model.cloud_group,
            microclimate_feature_fn=model.microclimate_features,
        )
        ok = lambda data: {"ok": True, "data": data}
        serve = model.extract_live_features({
            "wu_history": ok({"rows": live_rows, "max_c": 24.0}),
            "wu_current": ok({"temp_c": 24.0, "max_since_7am_c": 24.0}),
            "weather_forecast": ok({"rows": []}),
            "eccc_citypage": ok({}),
            "open_meteo": ok({"rows": [], "day_max_c": FORECAST_HIGH}),
        }, CUTOFF_HOUR)

        for feature in ("onshore_flow", "onshore_wind_speed_kmh", "lake_breeze_proxy"):
            with self.subTest(feature=feature):
                self.assertEqual(train[feature], serve[feature])
        self.assertEqual(serve["wind_group"], "E-SE/onshore-ish")
        self.assertEqual(serve["onshore_flow"], 1.0)
        self.assertEqual(serve["onshore_wind_speed_kmh"], 12.0)
        self.assertEqual(serve["lake_breeze_proxy"], 1.0)


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


class TestRampWallOffsets(unittest.TestCase):
    """Item-40 extension: the afternoon ramp cutoff hours (12-14) sample wall
    offsets out to 105 min so training covers the WU print-lag serving range;
    every other hour keeps the base {0,15,30,45} set unchanged, so morning and
    lock-in hours cannot regress by construction."""

    def setUp(self):
        import weather.calibration.feature_model as feature_model
        self.fm = feature_model

    def _offsets_seen(self, hour):
        from datetime import date, timedelta
        return sorted({
            self.fm.wall_offset_for(date(2026, 1, 1) + timedelta(days=d), hour)
            for d in range(400)
        })

    def test_ramp_hours_sample_extended_offsets(self):
        for hour in (12, 13, 14):
            self.assertEqual(self._offsets_seen(hour), [0, 15, 30, 45, 60, 75, 90, 105])

    def test_non_ramp_hours_keep_base_offsets(self):
        for hour in (7, 9, 11, 15, 16, 17):
            self.assertEqual(self._offsets_seen(hour), [0, 15, 30, 45])

    def test_offset_is_deterministic_per_day_hour(self):
        from datetime import date
        day = date(2026, 6, 11)
        self.assertEqual(self.fm.wall_offset_for(day, 13), self.fm.wall_offset_for(day, 13))


if __name__ == "__main__":
    unittest.main()
