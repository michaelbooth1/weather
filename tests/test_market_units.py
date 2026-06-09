import json
import os
import sys
import unittest
from datetime import date, datetime

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


class TestFahrenheitPresentation(unittest.TestCase):
    """The presentation layer receives values ALREADY in the market's native
    unit; re-converting rendered 75 F as 167 F and broke every deep-dive
    verdict on the 11 F markets."""

    def setUp(self):
        self.nyc = TorontoHighTempModel(market_id="nyc")
        self.toronto = TorontoHighTempModel()

    def test_format_temp_is_native(self):
        self.assertEqual(self.nyc.format_temp(75.0), "75 F")
        self.assertEqual(self.nyc.format_temp(75.6), "75.6 F")
        self.assertEqual(self.toronto.format_temp(24.0), "24 C")
        self.assertEqual(self.toronto.format_temp(None), "-")

    def _sources(self, wu_max):
        return {
            "wu_history": {"ok": True, "data": {"max_c": wu_max}},
            "wu_current": {"ok": True, "data": {}},
            "local_history": {"ok": True, "data": {}},
            "eccc_citypage": {"ok": True, "data": {}},
            "eccc_swob": {"ok": True, "data": {}},
            "weather_forecast": {"ok": True, "data": {"rows": []}},
            "open_meteo": {"ok": True, "data": {"rows": []}},
        }

    def test_deep_dive_verdict_uses_native_comparison(self):
        # NYC key bucket is 80 F. A printed 82 F high IS a guaranteed floor;
        # the old double conversion turned 82 F into 179.6 and could never
        # produce a correct verdict.
        rows = self.nyc.deep_dive_rows(
            self._sources(82.0), {}, analogs_data={"analogs": []}
        )
        wu_row = rows[0]
        self.assertEqual(wu_row["Answer"], "82 F")
        self.assertIn("Guaranteed floor", wu_row["Impact on 80 F"])

    def test_deep_dive_rise_needed_is_native(self):
        rows = self.nyc.deep_dive_rows(
            self._sources(70.0), {}, analogs_data={"analogs": []}
        )
        wu_row = rows[0]
        self.assertIn("Needs 10.0 F rise", wu_row["Impact on 80 F"])

    def test_explanation_buckets_use_native_unit(self):
        explanation = self.nyc.get_model_explanation(
            self._sources(None), {85: 0.6, 86: 0.4}
        )
        self.assertEqual(explanation["top_buckets"][0]["bucket"], "85 F")

    def test_local_history_answer_reads_producer_keys(self):
        # fetch_local_history emits prob_key/prob_key_plus/prob_key_plus_4;
        # the answer read stale prob_25* keys and rendered blank forever.
        text = self.toronto.local_history_answer({
            "available": True,
            "analysis": {"target_window_count": 50},
            "prob_key": 0.2,
            "prob_key_plus": 0.4,
            "prob_key_plus_4": 0.05,
        })
        self.assertIn("20.0%", text)
        self.assertIn("40.0%", text)
        self.assertIn("5.0%", text)

    def test_transitions_label_native_unit(self):
        m = self.nyc
        daily = {}
        by_date = {}
        for day in range(1, 7):
            d = date(2020, 5, day)
            daily[d] = {"bucket": 85}
            by_date[d] = [{"minute_of_day": 720, "temp_c": 84.6}]
        m.historical_target_cache = lambda: {"daily": daily, "by_date": by_date}
        sources = {
            "wu_history": {
                "ok": True,
                "data": {"max_c": 84.7, "rows": [{"time": "12:00", "temp_c": 84.7}]},
            },
        }
        result = m.get_bucket_transitions(sources, now=datetime(2026, 6, 9, 12, 30))
        self.assertTrue(result["transitions"])
        self.assertEqual(result["transitions"][0]["Target Bucket"], "85 F")
        self.assertEqual(result["transitions"][-1]["Target Bucket"], ">= 88 F")


if __name__ == "__main__":
    unittest.main()
