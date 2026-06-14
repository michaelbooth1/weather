"""Item 12: quantitative, bucket-agnostic model explanation.

Covers the pure telescoping driver-waterfall helper, the unit-aware
driver_breakdown presentation method, and the bucket-agnostic deep dive.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath("src"))

from model_presentation import driver_waterfall, _component_prob
from toronto_model import TorontoHighTempModel


# A synthetic distribution_components pipeline. climatology_prior is the
# baseline; feature_blend/post_live_signals/current_observed_floor/
# late_day_lockin/final_model are running snapshots; hgb_feature_model is a
# STANDALONE input (not in the waterfall).
COMPONENTS = {
    "climatology_prior": {24: 0.30, 25: 0.40, 26: 0.30},
    "hgb_feature_model": {24: 0.10, 25: 0.20, 26: 0.70},
    "feature_blend": {24: 0.20, 25: 0.30, 26: 0.50},
    "post_live_signals": {24: 0.10, 25: 0.30, 26: 0.60},
    "current_observed_floor": {24: 0.05, 25: 0.25, 26: 0.70},
    "late_day_lockin": {24: 0.05, 25: 0.35, 26: 0.60},
    "final_model": {24: 0.08, 25: 0.32, 26: 0.60},
}


class TestDriverWaterfall(unittest.TestCase):
    def test_telescopes_to_final(self):
        # For every bucket, baseline + sum(deltas) must equal the final stage.
        waterfall = driver_waterfall(COMPONENTS, [24, 25, 26])
        for bucket in (24, 25, 26):
            total = sum(contrib[bucket] for _k, _l, contrib in waterfall)
            self.assertAlmostEqual(total, COMPONENTS["final_model"][bucket])

    def test_first_stage_is_baseline_rest_are_deltas(self):
        waterfall = driver_waterfall(COMPONENTS, [26])
        keys = [k for k, _l, _c in waterfall]
        # hgb_feature_model is a standalone input, never a waterfall stage.
        self.assertNotIn("hgb_feature_model", keys)
        self.assertEqual(keys[0], "climatology_prior")
        self.assertEqual(keys[-1], "final_model")
        # baseline = absolute; first delta = feature_blend - climatology_prior.
        self.assertAlmostEqual(waterfall[0][2][26], 0.30)
        self.assertAlmostEqual(waterfall[1][2][26], 0.50 - 0.30)

    def test_skips_absent_stages(self):
        sparse = {
            "climatology_prior": {26: 0.5},
            "final_model": {26: 0.7},
        }
        waterfall = driver_waterfall(sparse, [26])
        self.assertEqual([k for k, _l, _c in waterfall], ["climatology_prior", "final_model"])
        self.assertAlmostEqual(waterfall[1][2][26], 0.7 - 0.5)

    def test_empirical_weighted_occupies_blend_slot(self):
        emp = dict(COMPONENTS)
        del emp["feature_blend"]
        emp["empirical_weighted"] = {24: 0.25, 25: 0.35, 26: 0.40}
        keys = [k for k, _l, _c in driver_waterfall(emp, [26])]
        self.assertIn("empirical_weighted", keys)
        self.assertNotIn("feature_blend", keys)

    def test_tolerates_string_keys(self):
        # JSON-loaded snapshot tapes have string bucket keys.
        as_str = {
            stage: {str(b): p for b, p in dist.items()}
            for stage, dist in COMPONENTS.items()
        }
        waterfall = driver_waterfall(as_str, [26])
        total = sum(contrib[26] for _k, _l, contrib in waterfall)
        self.assertAlmostEqual(total, 0.60)

    def test_component_prob_int_and_str(self):
        self.assertAlmostEqual(_component_prob({26: 0.4}, 26), 0.4)
        self.assertAlmostEqual(_component_prob({"26": 0.4}, 26), 0.4)
        self.assertAlmostEqual(_component_prob({}, 26), 0.0)
        self.assertAlmostEqual(_component_prob(None, 26), 0.0)


class TestDriverBreakdown(unittest.TestCase):
    def setUp(self):
        self.model = TorontoHighTempModel()
        self.model._last_distribution_components = {"components": COMPONENTS}

    def test_empty_when_no_build(self):
        fresh = TorontoHighTempModel()
        out = fresh.driver_breakdown([25])
        self.assertEqual(out["waterfall"], [])
        self.assertEqual(out["inputs"], [])

    def test_waterfall_rows_unit_aware_and_closed(self):
        out = self.model.driver_breakdown([26])
        # First row is the absolute baseline, last row is the final probability.
        self.assertEqual(out["waterfall"][0]["Driver"], "Base climatology")
        self.assertEqual(out["waterfall"][0]["26 C"], "30.0%")
        final_row = out["waterfall"][-1]
        self.assertEqual(final_row["Driver"], "= Final model probability")
        self.assertEqual(final_row["26 C"], "60.0%")
        # Delta rows are signed.
        blend_row = next(r for r in out["waterfall"] if r["Driver"] == "ML feature blend")
        self.assertEqual(blend_row["26 C"], "+20.0%")
        lockin_row = next(r for r in out["waterfall"] if r["Driver"] == "Late-day lock-in")
        self.assertEqual(lockin_row["26 C"], "-10.0%")

    def test_inputs_table_resolves_feature_model_dynamically(self):
        out = self.model.driver_breakdown([26])
        labels = [r["Input"] for r in out["inputs"]]
        self.assertIn("HGB feature model", labels)
        hgb_row = next(r for r in out["inputs"] if r["Input"] == "HGB feature model")
        self.assertEqual(hgb_row["26 C"], "70.0%")

    def test_fahrenheit_columns(self):
        nyc = TorontoHighTempModel(market_id="nyc")
        nyc._last_distribution_components = {"components": {
            "climatology_prior": {90: 0.5},
            "final_model": {90: 0.8},
        }}
        out = nyc.driver_breakdown([90])
        self.assertIn("90 F", out["waterfall"][0])


class TestBucketAgnosticDeepDive(unittest.TestCase):
    def _sources(self, wu_max=22.0):
        return {
            "wu_history": {"ok": True, "data": {"max_c": wu_max}},
            "wu_current": {"ok": True, "data": {}},
            "local_history": {"ok": True, "data": {
                "available": True,
                "analysis": {"bucket_probabilities": {24: 0.30, 25: 0.50, 26: 0.20}},
            }},
            "eccc_citypage": {"ok": True, "data": {}},
            "eccc_swob": {"ok": True, "data": {}},
            "weather_forecast": {"ok": True, "data": {"rows": []}},
            "open_meteo": {"ok": True, "data": {"rows": []}},
        }

    def setUp(self):
        self.model = TorontoHighTempModel()
        self.analogs = {"analogs": [{"final_bucket": 26}, {"final_bucket": 25}]}

    def test_focus_defaults_to_top_bucket(self):
        rows = self.model.deep_dive_rows(
            self._sources(), {24: 0.2, 25: 0.3, 26: 0.5}, analogs_data=self.analogs
        )
        # impact_key is keyed on the focus bucket (top = 26 C), not key_bucket 25.
        self.assertIn("Impact on 26 C", rows[0])
        # Local-history base-rate row reflects the focus bucket's seasonal rate.
        base_row = next(r for r in rows if r["Question"] == "What does local WU history say?")
        self.assertIn("26 C is 20.0%", base_row["Impact on 26 C"])
        # Analog row counts analogs that settled at the focus bucket (1 of 2).
        analog_row = next(r for r in rows if r["Question"] == "What do historical analogs say?")
        self.assertIn("50% resolved to exactly 26 C", analog_row["Impact on 26 C"])

    def test_explicit_focus_bucket_overrides(self):
        rows = self.model.deep_dive_rows(
            self._sources(), {24: 0.2, 25: 0.3, 26: 0.5},
            analogs_data=self.analogs, focus_bucket=24,
        )
        self.assertIn("Impact on 24 C", rows[0])
        base_row = next(r for r in rows if r["Question"] == "What does local WU history say?")
        self.assertIn("24 C is 30.0%", base_row["Impact on 24 C"])

    def test_empty_distribution_falls_back_to_key_bucket(self):
        rows = self.model.deep_dive_rows(self._sources(), {}, analogs_data=self.analogs)
        self.assertIn("Impact on 25 C", rows[0])  # toronto key_bucket


if __name__ == "__main__":
    unittest.main()
