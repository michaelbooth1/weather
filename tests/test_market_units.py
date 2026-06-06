import json
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath("src"))

from toronto_model import TorontoHighTempModel


class TestNativeBinProbability(unittest.TestCase):
    """Each market runs in its native unit, so bin_probability is a native sum
    over the band's bucket range (range bands sum [value, value_hi])."""

    def test_celsius_eq_lte_gte(self):
        m = TorontoHighTempModel()  # C market
        dist = {24: 0.2, 25: 0.5, 26: 0.3}
        self.assertAlmostEqual(m.bin_probability(dist, {"kind": "eq", "value": 25}), 0.5)
        self.assertAlmostEqual(m.bin_probability(dist, {"kind": "lte", "value": 24}), 0.2)
        self.assertAlmostEqual(m.bin_probability(dist, {"kind": "gte", "value": 25}), 0.8)

    def test_fahrenheit_range_native(self):
        m = TorontoHighTempModel(market_id="nyc")  # F market (native F buckets)
        dist = {88: 0.1, 89: 0.1, 90: 0.5, 91: 0.3}
        self.assertAlmostEqual(m.bin_probability(dist, {"kind": "eq", "value": 90, "value_hi": 91}), 0.8)
        self.assertAlmostEqual(m.bin_probability(dist, {"kind": "eq", "value": 88, "value_hi": 89}), 0.2)
        self.assertAlmostEqual(m.bin_probability(dist, {"kind": "lte", "value": 89}), 0.2)
        self.assertAlmostEqual(m.bin_probability(dist, {"kind": "gte", "value": 90}), 0.8)


class TestMarketBinsParsing(unittest.TestCase):
    def _event(self, labels):
        return {"markets": [
            {"groupItemTitle": label,
             "outcomes": json.dumps(["Yes", "No"]),
             "outcomePrices": json.dumps(["0.5", "0.5"])}
            for label in labels
        ]}

    def test_nyc_range_and_tails(self):
        m = TorontoHighTempModel(market_id="nyc")
        bins = m.market_bins(self._event(["75°F or below", "76-77°F", "94°F or higher"]))
        rng = next(b for b in bins if b["kind"] == "eq")
        below = next(b for b in bins if b["kind"] == "lte")
        above = next(b for b in bins if b["kind"] == "gte")
        self.assertEqual((rng["value"], rng["value_hi"], rng["unit"]), (76, 77, "F"))
        self.assertEqual(below["value"], 75)
        self.assertEqual(above["value"], 94)

    def test_toronto_single_eq_unchanged(self):
        m = TorontoHighTempModel()
        bins = m.market_bins(self._event(["28 C", "18 C or below", "30 C or higher"]))
        eq = next(b for b in bins if b["kind"] == "eq")
        self.assertEqual((eq["value"], eq["value_hi"], eq["unit"]), (28, 28, "C"))


if __name__ == "__main__":
    unittest.main()
