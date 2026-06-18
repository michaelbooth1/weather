import unittest

from weather.sources.daily_summary import celsius_high, native_high
from weather.units import (
    c_to_f,
    c_to_native,
    f_to_c,
    f_to_native,
    native_to_c,
    native_to_f,
    round_half_up,
    to_float,
)


class TestWeatherUnits(unittest.TestCase):
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
