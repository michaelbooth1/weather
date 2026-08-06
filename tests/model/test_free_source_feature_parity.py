import json
import os
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

from weather.model.feature_store import build_historical_feature_record
from weather.model.free_source_feature_parity import (
    FREE_SOURCE_FEATURE_PARITY_FLAG,
    build_free_source_feature_overrides,
    free_source_feature_parity_enabled,
)
from weather.model.toronto_model import TorontoHighTempModel


PARITY_FIELDS = (
    "rise_from_7am",
    "warming_rate_2h",
    "hours_at_peak",
    "dewpoint_c",
    "humidity",
    "pressure",
    "pressure_trend_3h",
    "wind_speed_kmh",
    "wind_gust_kmh",
    "wind_shift_3h_degrees",
    "onshore_flow",
    "onshore_wind_speed_kmh",
    "lake_breeze_proxy",
    "wind_group",
    "cloud_group",
)


def source_item(raw_payload, fetched_at, *, stale=False, ok=True):
    return {
        "ok": ok,
        "stale": stale,
        "fetched_at": fetched_at,
        "data": {"raw_payload": raw_payload, "target_date_match": True},
    }


def swob_xml(
    utc_time,
    *,
    station="CYYZ",
    temp=20.0,
    dewpoint=10.0,
    humidity=50.0,
    pressure=990.0,
    wind_degrees=180.0,
    wind_speed=10.0,
    gust=15.0,
    cloud_code="37",
    weather_code="125",
):
    values = {
        "date_tm": utc_time,
        "icao_stn_id": station,
        "air_temp": temp,
        "dwpt_temp": dewpoint,
        "rel_hum": humidity,
        "stn_pres": pressure,
        "avg_wnd_dir_10m_pst2mts": wind_degrees,
        "avg_wnd_spd_10m_pst2mts": wind_speed,
        "max_wnd_gst_spd_10m_pst10mts": gust,
        "cld_amt_code_1": cloud_code,
        "prsnt_wx_1": weather_code,
    }
    elements = "".join(
        f'<element name="{name}" value="{value}" />'
        for name, value in values.items()
    )
    return f"<root>{elements}</root>"


def metar_row(
    report_time,
    *,
    station="KLGA",
    temp=20.0,
    dewpoint=10.0,
    wind_degrees=180,
    wind_speed=10.0,
    gust=15.0,
    cover="BKN",
    raw_ob="METAR KLGA 021800Z 18010G15KT 10SM BKN040",
    receipt_time=None,
):
    return {
        "icaoId": station,
        "reportTime": report_time,
        "receiptTime": receipt_time or report_time,
        "temp": temp,
        "dewp": dewpoint,
        "wdir": wind_degrees,
        "wspd": wind_speed,
        "wgst": gust,
        "cover": cover,
        "clouds": [{"cover": cover, "base": 4000}],
        "rawOb": raw_ob,
    }


class TestFreeSourceFeatureParity(unittest.TestCase):
    def test_flag_defaults_off(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(FREE_SOURCE_FEATURE_PARITY_FLAG, None)
            self.assertFalse(free_source_feature_parity_enabled())
        self.assertFalse(free_source_feature_parity_enabled("unexpected"))
        self.assertTrue(free_source_feature_parity_enabled("true"))

    def test_default_off_does_not_enter_population_path_and_bytes_stay_equal(self):
        model = TorontoHighTempModel(target_date="2026-06-02", market_id="toronto")
        rows = [
            {
                "time": "07:00",
                "temp_c": 16.0,
                "dewpoint_c": 10.0,
                "humidity": 70.0,
                "pressure": 1016.0,
                "wind_kmh": 10.0,
                "wind": "W",
                "condition": "Fair",
            },
            {
                "time": "14:00",
                "temp_c": 24.0,
                "dewpoint_c": 11.0,
                "humidity": 48.0,
                "pressure": 1014.0,
                "wind_kmh": 18.0,
                "wind": "S",
                "condition": "Fair",
            },
        ]
        sources = {
            "wu_history": {"ok": True, "data": {"rows": rows, "max_c": 24.0}},
            "wu_current": {
                "ok": True,
                "data": {"temp_c": 24.0, "max_since_7am_c": 24.0},
            },
            "open_meteo": {"ok": True, "data": {"rows": [], "day_max_c": 26.0}},
        }
        captured = datetime(2026, 6, 2, 14, 5, tzinfo=timezone.utc)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(FREE_SOURCE_FEATURE_PARITY_FLAG, None)
            with patch(
                "weather.model.model_features.build_free_source_feature_overrides",
                side_effect=AssertionError("dark path entered"),
            ):
                default_record = model.live_feature_record(sources, 14, captured)
        with patch.dict(os.environ, {FREE_SOURCE_FEATURE_PARITY_FLAG: "0"}):
            explicit_off_record = model.live_feature_record(sources, 14, captured)
        canonical = lambda value: json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        self.assertEqual(canonical(default_record), canonical(explicit_off_record))

    def test_eccc_matches_historical_formulas_and_station_pressure_semantics(self):
        model = TorontoHighTempModel(target_date="2026-06-02", market_id="toronto")
        observations = [
            ("2026-06-02T11:00:00Z", 16.0, 10.0, 70.0, 1000.0, 270.0, 7.0),
            ("2026-06-02T15:00:00Z", 22.0, 11.0, 55.0, 995.0, 270.0, 10.0),
            ("2026-06-02T18:00:00Z", 24.0, 11.0, 48.0, 994.0, 180.0, 12.0),
        ]
        raw = {
            "files": [
                {
                    "filename": f"row-{index}.xml",
                    "text": swob_xml(
                        timestamp,
                        temp=temp,
                        dewpoint=dewpoint,
                        humidity=humidity,
                        pressure=pressure,
                        wind_degrees=wind,
                        wind_speed=speed,
                        gust=speed + 5.0,
                    ),
                }
                for index, (timestamp, temp, dewpoint, humidity, pressure, wind, speed)
                in enumerate(observations)
            ]
        }
        sources = {
            "eccc_swob": source_item(
                raw,
                "2026-06-02T14:04:00-04:00",
            )
        }
        served = build_free_source_feature_overrides(
            model,
            sources,
            14,
            datetime(2026, 6, 2, 14, 5, tzinfo=model.spec.tz),
        )
        historical_rows = [
            {
                "minute_of_day": minute,
                "temp_c": temp,
                "dewpoint_c": dewpoint,
                "humidity": humidity,
                "pressure": pressure,
                "wind_kmh": speed,
                "gust_kmh": speed + 5.0,
                "wind_degrees": wind,
                "wind": cardinal,
                "clouds": "BKN",
                "condition": None,
            }
            for minute, (_, temp, dewpoint, humidity, pressure, wind, speed), cardinal
            in zip((420, 660, 840), observations, ("W", "W", "S"))
        ]
        trained = build_historical_feature_record(
            local_date="2026-06-02",
            rows=historical_rows,
            daily={"bucket": 24},
            cutoff_hour=14,
            wind_group_fn=model.wind_group,
            cloud_group_fn=model.cloud_group,
            microclimate_feature_fn=model.microclimate_features,
        )
        for field in PARITY_FIELDS:
            with self.subTest(field=field):
                self.assertEqual(trained[field], served[field])
        self.assertEqual(served["pressure"], 994.0)
        self.assertEqual(served["pressure_trend_3h"], -1.0)
        self.assertEqual(served["humidity"], 48.0)

    def test_toronto_uses_one_source_without_splicing_metar_gaps(self):
        model = TorontoHighTempModel(target_date="2026-06-02", market_id="toronto")
        eccc = {
            "files": [{
                "filename": "eccc.xml",
                "text": swob_xml(
                    "2026-06-02T18:00:00Z",
                    humidity="MSNG",
                    pressure="MSNG",
                ),
            }]
        }
        metar = [metar_row("2026-06-02T18:00:00Z", station="CYYZ")]
        values = build_free_source_feature_overrides(
            model,
            {
                "eccc_swob": source_item(eccc, "2026-06-02T14:03:00-04:00"),
                "metar": source_item(metar, "2026-06-02T14:04:00-04:00"),
            },
            14,
            datetime(2026, 6, 2, 14, 5, tzinfo=model.spec.tz),
        )
        self.assertEqual(values["dewpoint_c"], 10.0)
        self.assertIsNone(values["humidity"])
        self.assertIsNone(values["pressure"])

    def test_metar_converts_celsius_and_knots_but_leaves_rh_and_pressure_absent(self):
        model = TorontoHighTempModel(target_date="2026-06-02", market_id="nyc")
        raw = [
            metar_row(
                "2026-06-02T11:00:00Z",
                temp=-5.0,
                dewpoint=-8.0,
                wind_degrees=270,
                wind_speed=8.0,
            ),
            metar_row(
                "2026-06-02T15:00:00Z",
                temp=10.0,
                dewpoint=2.0,
                wind_degrees=270,
                wind_speed=9.0,
            ),
            metar_row(
                "2026-06-02T18:00:00Z",
                temp=20.0,
                dewpoint=5.0,
                wind_degrees=180,
                wind_speed=10.0,
                raw_ob="METAR KLGA 021800Z 18010KT 5SM -RA BKN040",
            ),
        ]
        served = build_free_source_feature_overrides(
            model,
            {"metar": source_item(raw, "2026-06-02T14:04:00-04:00")},
            14,
            datetime(2026, 6, 2, 14, 5, tzinfo=model.spec.tz),
        )
        self.assertEqual(served["dewpoint_c"], 41.0)
        self.assertEqual(served["rise_from_7am"], 45.0)
        self.assertAlmostEqual(served["wind_speed_kmh"], 11.507794480235425)
        self.assertIsNone(served["humidity"])
        self.assertIsNone(served["pressure"])
        self.assertIsNone(served["pressure_trend_3h"])
        self.assertEqual(served["wind_group"], "S-SW")
        self.assertEqual(served["cloud_group"], "Precip")

    def test_metar_sky_clear_code_maps_to_training_clear_group(self):
        model = TorontoHighTempModel(target_date="2026-06-02", market_id="nyc")
        raw = [
            metar_row(
                "2026-06-02T18:00:00Z",
                cover="SKC",
                raw_ob="METAR KLGA 021800Z 18010KT 10SM SKC",
            )
        ]
        served = build_free_source_feature_overrides(
            model,
            {"metar": source_item(raw, "2026-06-02T14:04:00-04:00")},
            14,
            datetime(2026, 6, 2, 14, 5, tzinfo=model.spec.tz),
        )
        self.assertEqual(served["cloud_group"], "Fair/clear")

    def test_pit_and_station_guards_fail_closed(self):
        model = TorontoHighTempModel(target_date="2026-06-02", market_id="nyc")
        raw = [metar_row("2026-06-02T18:00:00Z")]
        captured = datetime(2026, 6, 2, 14, 5, tzinfo=model.spec.tz)
        cases = {
            "stale": source_item(raw, "2026-06-02T14:04:00-04:00", stale=True),
            "fetched_after_capture": source_item(raw, "2026-06-02T14:06:00-04:00"),
            "wrong_station": source_item(
                [metar_row("2026-06-02T18:00:00Z", station="KJFK")],
                "2026-06-02T14:04:00-04:00",
            ),
            "wrong_date": source_item(
                [metar_row("2026-06-01T18:00:00Z")],
                "2026-06-02T14:04:00-04:00",
            ),
            "after_cutoff": source_item(
                [metar_row("2026-06-02T18:30:00Z")],
                "2026-06-02T14:04:00-04:00",
            ),
        }
        for name, item in cases.items():
            with self.subTest(name=name):
                values = build_free_source_feature_overrides(
                    model,
                    {"metar": item},
                    14,
                    captured,
                )
                self.assertTrue(all(values[field] is None for field in (
                    "rise_from_7am",
                    "dewpoint_c",
                    "humidity",
                    "pressure",
                    "wind_speed_kmh",
                    "wind_group",
                    "cloud_group",
                )))

    def test_unknown_eccc_weather_and_cloud_codes_stay_absent(self):
        model = TorontoHighTempModel(target_date=date(2026, 6, 2), market_id="toronto")
        raw = {
            "files": [{
                "filename": "unknown.xml",
                "text": swob_xml(
                    "2026-06-02T18:00:00Z",
                    cloud_code="99",
                    weather_code="125",
                ),
            }]
        }
        values = build_free_source_feature_overrides(
            model,
            {"eccc_swob": source_item(raw, "2026-06-02T14:04:00-04:00")},
            14,
            datetime(2026, 6, 2, 14, 5, tzinfo=model.spec.tz),
        )
        self.assertIsNone(values["cloud_group"])


if __name__ == "__main__":
    unittest.main()
