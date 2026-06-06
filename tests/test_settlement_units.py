import os
import sys
import unittest

sys.path.insert(0, os.path.abspath("src"))

from backtest import band_value_hi, resolve_outcome, resolve_outcome_fahrenheit


class TestFahrenheitOutcome(unittest.TestCase):
    def test_nyc_90F_day(self):
        # Realized 32.0 C == 90 F. The 90-91F band must resolve YES, others NO.
        c = 32.0
        self.assertEqual(resolve_outcome_fahrenheit("eq", 90, 91, c), 1)
        self.assertEqual(resolve_outcome_fahrenheit("eq", 88, 89, c), 0)
        self.assertEqual(resolve_outcome_fahrenheit("eq", 92, 93, c), 0)
        # The old Celsius logic wrongly marked "75F or below" YES on a 32C day.
        self.assertEqual(resolve_outcome_fahrenheit("lte", 75, 75, c), 0)
        self.assertEqual(resolve_outcome_fahrenheit("gte", 94, 94, c), 0)

    def test_tails(self):
        self.assertEqual(resolve_outcome_fahrenheit("lte", 75, 75, 20.0), 1)   # 68F <= 75
        self.assertEqual(resolve_outcome_fahrenheit("gte", 94, 94, 35.5), 1)   # 95.9F >= 94

    def test_band_value_hi_from_label(self):
        self.assertEqual(band_value_hi("90-91°F", 90), 91)
        self.assertEqual(band_value_hi("75°F or below", 75), 75)
        self.assertEqual(band_value_hi("94°F or higher", 94), 94)

    def test_none_realized(self):
        self.assertIsNone(resolve_outcome_fahrenheit("eq", 90, 91, None))


class TestCelsiusUnchanged(unittest.TestCase):
    def test_celsius_bucket_logic(self):
        self.assertEqual(resolve_outcome("eq", 25, 25), 1)
        self.assertEqual(resolve_outcome("eq", 25, 26), 0)
        self.assertEqual(resolve_outcome("lte", 24, 22), 1)
        self.assertEqual(resolve_outcome("gte", 28, 30), 1)
        self.assertIsNone(resolve_outcome("eq", 25, None))


if __name__ == "__main__":
    unittest.main()
