import unittest

from weather.sources.daily_summary import celsius_high, native_high
from weather.units import (
    c_to_f,
    c_to_native,
    f_to_c,
    f_to_native,
    native_to_c,
    native_to_f,
    parse_temperature_band,
    round_half_up,
    temperature_band_key,
    to_float,
)


class TestWeatherUnits(unittest.TestCase):
    def test_signed_native_bands_and_supported_display_spellings(self):
        for label, expected in (
            ("-5 C or below", ("lte", -5, -5, "C")),
            ("-5°C", ("eq", -5, -5, "C")),
            ("−5–−4℃", ("eq", -5, -4, "C")),
            ("-1—0 C", ("eq", -1, 0, "C")),
            ("80-81°F", ("eq", 80, 81, "F")),
            ("80 F - 81 F", ("eq", 80, 81, "F")),
            ("+5 F or higher", ("gte", 5, 5, "F")),
            ("0 or above", ("gte", 0, 0, None)),
        ):
            with self.subTest(label=label):
                band = parse_temperature_band(label)
                self.assertIsNotNone(band)
                self.assertEqual((band.kind, band.value, band.value_hi, band.unit), expected)

    def test_ambiguous_or_non_native_labels_do_not_manufacture_buckets(self):
        for label in ("81-80 F", "-4--5 C", "5 C-6 F", "80-81 F or below",
                      "80.5 F", "80 81 F", "Will 80 F win on September 6?", "", None, 80):
            with self.subTest(label=label):
                self.assertIsNone(parse_temperature_band(label))
        self.assertIsNone(parse_temperature_band("80 F", expected_unit="C"))
        self.assertEqual(parse_temperature_band("80", expected_unit="F").unit, "F")

    def test_row_bands_preserve_zero_and_validate_explicit_endpoints(self):
        self.assertEqual(temperature_band_key({"range_label": "80-81 F"}), ("eq", 80, 81))
        self.assertEqual(temperature_band_key({"range_label": "-1-0 C", "bin_value_hi": 0}), ("eq", -1, 0))
        self.assertEqual(temperature_band_key({"range_label": "0-1 C", "bin_value_c": 0,
                                              "winning_band_value": 42}), ("eq", 0, 1))
        # Historical display labels sometimes omitted an explicit range endpoint.
        self.assertEqual(temperature_band_key({"range_label": "90 F", "bin_value_hi": 91}), ("eq", 90, 91))
        for row in (
            {"range_label": "-5 C or below", "bin_value": 5},
            {"range_label": "80-81 F", "bin_value_hi": 82},
            {"range_label": "80-81 F", "bin_kind": "gte"},
            {"bin_value": 81, "bin_value_hi": 80},
            {"bin_value": "nan", "range_label": "80 F"},
            {"bin_value": True, "range_label": "1 C"},
            {"bin_value": 1.5},
        ):
            with self.subTest(row=row):
                self.assertIsNone(temperature_band_key(row)[1])

    def test_round_half_up_is_project_canonical_for_positive_and_negative_values(self):
        self.assertEqual(round_half_up(12.4), 12)
        self.assertEqual(round_half_up(12.5), 13)
        self.assertEqual(round_half_up(12.6), 13)
        self.assertEqual(round_half_up(-1.6), -2)
        self.assertEqual(round_half_up(-1.5), -1)
        self.assertEqual(round_half_up(-1.4), -1)

    def test_nullable_numeric_coercion(self):
        for value in (None, "", "None", "none", "null", "NaN", "nan", "MSNG"):
            self.assertIsNone(to_float(value))
        self.assertEqual(to_float("12.5"), 12.5)

    def test_unit_conversions_are_null_safe(self):
        self.assertAlmostEqual(f_to_c(86), 30.0)
        self.assertAlmostEqual(c_to_f(30), 86.0)
        self.assertAlmostEqual(native_to_c(86, "F"), 30.0)
        self.assertAlmostEqual(c_to_native(30, "F"), 86.0)
        self.assertAlmostEqual(native_to_f(30, "C"), 86.0)
        self.assertAlmostEqual(f_to_native(86, "C"), 30.0)
        self.assertIsNone(f_to_c(None))
        self.assertIsNone(c_to_native("MSNG", "F"))

    def test_daily_summary_legacy_fahrenheit_c_columns_are_interpreted_as_native(self):
        row = {
            "schema_version": "wu_daily_native_v1",
            "temperature_unit": "F",
            "max_temp_c": "86.0",
        }
        self.assertEqual(native_high(row), 86.0)
        self.assertAlmostEqual(celsius_high(row), 30.0)


if __name__ == "__main__":
    unittest.main()
