import json
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath("src"))

from toronto_model import TorontoHighTempModel


class TestCelsiusUnchanged(unittest.TestCase):
    """The Celsius path must be byte-identical: eq/lte/gte still exact bucket sums."""

    def setUp(self):
        self.m = TorontoHighTempModel()  # toronto -> display_unit C
        self.dist = {24: 0.2, 25: 0.5, 26: 0.3}

    def test_eq_lte_gte(self):
        self.assertAlmostEqual(self.m.bin_probability(self.dist, {"kind": "eq", "value": 25}), 0.5)
        self.assertAlmostEqual(self.m.bin_probability(self.dist, {"kind": "lte", "value": 24}), 0.2)
        self.assertAlmostEqual(self.m.bin_probability(self.dist, {"kind": "gte", "value": 25}), 0.8)

    def test_interval_reproduces_exact_bucket(self):
        # An aligned Celsius interval integrates to the exact bucket probability.
        self.assertAlmostEqual(self.m.interval_probability(self.dist, 24.5, 25.5), 0.5)


class TestFahrenheitBands(unittest.TestCase):
    def setUp(self):
        self.m = TorontoHighTempModel(market_id="nyc")  # display_unit F
        # canonical Celsius distribution (~86 F is 30 C)
        self.dist = {29: 0.2, 30: 0.5, 31: 0.3}

    def test_range_band_integrates_celsius(self):
        # 86-87F -> true temp [85.5,87.5]F -> [29.72, 30.83]C
        p = self.m.fahrenheit_bin_probability(self.dist, {"kind": "eq", "value": 86, "value_hi": 87})
        # bucket30 overlap .778*0.5 + bucket31 overlap .333*0.3
        self.assertAlmostEqual(p, 0.5 * 0.7778 + 0.3 * 0.3333, places=3)

    def test_tails(self):
        below = self.m.fahrenheit_bin_probability(self.dist, {"kind": "lte", "value": 80})
        above = self.m.fahrenheit_bin_probability(self.dist, {"kind": "gte", "value": 94})
        self.assertLess(below, 0.05)   # 80F ~ 26.7C, below our mass
        self.assertLess(above, 0.05)   # 94F ~ 34.4C, above our mass

    def test_bands_partition_probability(self):
        # A full set of contiguous F bands should sum to ~1 over the distribution.
        bands = ([{"kind": "lte", "value": 75, "value_hi": 75}]
                 + [{"kind": "eq", "value": lo, "value_hi": lo + 1} for lo in range(76, 94, 2)]
                 + [{"kind": "gte", "value": 94, "value_hi": 94}])
        total = sum(self.m.fahrenheit_bin_probability(self.dist, b) for b in bands)
        self.assertAlmostEqual(total, 1.0, places=6)


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
        bins = {b["label"]: b for b in m.market_bins(self._event(
            ["75°F or below", "76-77°F", "94°F or higher"]))}
        below = next(b for b in bins.values() if b["kind"] == "lte")
        rng = next(b for b in bins.values() if b["kind"] == "eq")
        above = next(b for b in bins.values() if b["kind"] == "gte")
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
