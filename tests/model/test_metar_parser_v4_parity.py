"""Item 4: METAR parser v4 adds evidence fields without moving any feature.

Parser v4 retains SPECI rows flagged with ``report_type`` and the RMK T-group
tenths as separate fields. Train/serve parity requires every existing value
(features, station rescue, guidance floor) to be byte-identical to v3.
"""

import unittest
from unittest.mock import patch

from weather.model import model_sources
from weather.model.toronto_model import TorontoHighTempModel

NEW_ROW_KEYS = ("report_type", "obs_time_utc", "tgroup_temp_celsius", "tgroup_dewpoint_celsius")
CUTOFF_HOUR = 14


def payload(day, offset_hours):
    """Routine METARs plus a SPECI; T-group deliberately disagrees with ``temp``
    on the last report so a leak of the new field would move the features."""

    def row(local_hour, minute, temp, raw, metar_type="METAR"):
        hour = (local_hour + offset_hours) % 24
        return {
            "icaoId": "KLGA",
            "reportTime": f"{day}T{hour:02d}:{minute:02d}:00Z",
            "metarType": metar_type,
            "temp": temp,
            "dewp": 12.0,
            "wdir": 200,
            "wspd": 8,
            "rh": 60.0,
            "altim": 1015.0,
            "rawOb": raw,
        }

    return [
        row(8, 51, 18.0, "KLGA 0000Z 20008KT 18/12 RMK AO2 T01780122"),
        row(11, 51, 22.0, "KLGA 0000Z 20008KT 22/12 RMK AO2 T02170117"),
        row(12, 20, 23.0, "SPECI KLGA 0000Z 20008KT 23/12 RMK AO2 T02280117", "SPECI"),
        row(13, 51, 24.0, "KLGA 0000Z 20008KT 24/12 RMK AO2 T02490122"),
    ]


def fetch(model, raw):
    model.get_json = lambda _url, _params: raw
    return model.fetch_metar()


def sources_for(metar):
    ok = lambda data: {"ok": True, "data": data}
    return {
        "metar": ok(metar),
        "open_meteo": ok({"rows": [], "day_rows": [], "day_max_native": 80.0}),
        "weather_forecast": ok({"rows": []}),
        "eccc_citypage": ok({}),
    }


class MetarParserV4ParityTest(unittest.TestCase):
    def _v3_and_v4(self, market_id, target_date, offset_hours):
        raw = payload(target_date, offset_hours)
        v4 = fetch(TorontoHighTempModel(target_date=target_date, market_id=market_id), raw)
        with patch.object(model_sources, "metar_row_annotations", lambda _row: {}):
            v3 = fetch(TorontoHighTempModel(target_date=target_date, market_id=market_id), raw)
        return v3, v4

    def test_speci_retained_and_flagged_with_tgroup_tenths(self):
        _, v4 = self._v3_and_v4("nyc", "2026-07-02", 4)
        types = [row["report_type"] for row in v4["rows"]]
        self.assertEqual(types, ["METAR", "METAR", "SPECI", "METAR"])
        self.assertEqual(v4["rows"][2]["tgroup_temp_celsius"], 22.8)
        self.assertEqual(v4["rows"][-1]["tgroup_temp_celsius"], 24.9)
        self.assertEqual(v4["rows"][-1]["tgroup_dewpoint_celsius"], 12.2)
        self.assertEqual(model_sources.SOURCE_PAYLOAD_CONTRACTS["metar"][0], "metar-parser-v4")

    def test_existing_metar_values_and_features_unchanged(self):
        for market_id, offset in (("nyc", 4), ("toronto", 4)):
            with self.subTest(market=market_id):
                v3, v4 = self._v3_and_v4(market_id, "2026-07-02", offset)
                stripped = [
                    {key: value for key, value in row.items() if key not in NEW_ROW_KEYS}
                    for row in v4["rows"]
                ]
                self.assertEqual(stripped, v3["rows"])
                for key, value in v3.items():
                    if key in ("rows", "latest"):
                        continue
                    self.assertEqual(v4[key], value, key)
                # temp_native is the provider-decoded field, never the T-group.
                expected_latest = 24.0 * 9 / 5 + 32 if market_id == "nyc" else 24.0
                self.assertAlmostEqual(v4["temp_native"], expected_latest)

                model = TorontoHighTempModel(target_date="2026-07-02", market_id=market_id)
                features_v3 = model.extract_live_features(sources_for(v3), CUTOFF_HOUR)
                features_v4 = model.extract_live_features(sources_for(v4), CUTOFF_HOUR)
                self.assertEqual(features_v4, features_v3)
                self.assertEqual(
                    model.derive_station_observation_data(sources_for(v4))["max_since_7am_native"],
                    model.derive_station_observation_data(sources_for(v3))["max_since_7am_native"],
                )
                self.assertEqual(
                    model.guidance_physical_floor(sources=sources_for(v4)),
                    model.guidance_physical_floor(sources=sources_for(v3)),
                )


if __name__ == "__main__":
    unittest.main()
