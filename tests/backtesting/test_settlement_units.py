import os
import sys
import unittest

sys.path.insert(0, os.path.abspath("src"))

from backtest import band_value_hi, resolve_outcome


class TestNativeOutcome(unittest.TestCase):
    """Each market settles in its native unit, so resolve_outcome is a direct
    comparison of the native realized bucket to the native bands (range-aware)."""

    def test_celsius_bucket_unchanged(self):
        self.assertEqual(resolve_outcome("eq", 25, 25), 1)
        self.assertEqual(resolve_outcome("eq", 25, 26), 0)
        self.assertEqual(resolve_outcome("lte", 24, 22), 1)
        self.assertEqual(resolve_outcome("gte", 28, 30), 1)
        self.assertIsNone(resolve_outcome("eq", 25, None))

    def test_fahrenheit_range_native(self):
        # A 90F day: native settlement bucket 90. Bands are native F ranges.
        self.assertEqual(resolve_outcome("eq", 90, 90, value_hi=91), 1)   # 90-91F YES
        self.assertEqual(resolve_outcome("eq", 88, 90, value_hi=89), 0)   # 88-89F NO
        self.assertEqual(resolve_outcome("eq", 92, 90, value_hi=93), 0)   # 92-93F NO
        self.assertEqual(resolve_outcome("lte", 75, 90), 0)               # 75F or below NO
        self.assertEqual(resolve_outcome("gte", 94, 90), 0)               # 94F or higher NO

    def test_range_endpoints(self):
        self.assertEqual(resolve_outcome("eq", 76, 76, value_hi=77), 1)   # 76 in 76-77
        self.assertEqual(resolve_outcome("eq", 76, 77, value_hi=77), 1)   # 77 in 76-77
        self.assertEqual(resolve_outcome("eq", 76, 78, value_hi=77), 0)   # 78 not in 76-77

    def test_band_value_hi_from_label(self):
        self.assertEqual(band_value_hi("90-91°F", 90), 91)
        self.assertEqual(band_value_hi("75°F or below", 75), 75)
        self.assertEqual(band_value_hi("94°F or higher", 94), 94)


if __name__ == "__main__":
    unittest.main()
