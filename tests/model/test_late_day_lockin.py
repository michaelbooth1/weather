import os
import sys
import unittest
from datetime import datetime
from weather.model.model_distribution import DistributionPipelineState
from weather.model.toronto_model import TorontoHighTempModel


class TestLateDayLockinStrength(unittest.TestCase):
    def setUp(self):
        self.m = TorontoHighTempModel()

    def test_zero_before_late_or_while_still_warm(self):
        self.assertEqual(self.m.late_day_lockin_strength(14, 19.0, 25.0), 0.0)   # too early
        self.assertEqual(self.m.late_day_lockin_strength(20, 25.0, 25.0), 0.0)   # temp still at the high
        self.assertEqual(self.m.late_day_lockin_strength(20, None, 25.0), 0.0)   # no reading

    def test_full_when_late_and_past_peak(self):
        self.assertEqual(self.m.late_day_lockin_strength(20, 19.0, 25.0), 1.0)
        self.assertEqual(self.m.late_day_lockin_strength(23, 18.0, 25.0), 1.0)

    def test_ramps_with_time_and_drop(self):
        # hour 16 -> time (16-15)/(17-15)=0.5; drop 1 -> peak 0.5; strength 0.25
        self.assertAlmostEqual(self.m.late_day_lockin_strength(16, 24.0, 25.0), 0.5 * 0.5)


class TestLearnedLockinStrength(unittest.TestCase):
    """v0.5.6: the lag artifact's revision-up curve floors the lock-in late,
    covering the evening plateau (current == high -> heuristic drop 0) where
    the 2026-06-09 model held 20%+ above the high against a learned ~2-5%
    revision rate."""

    def setUp(self):
        from datetime import datetime
        self.datetime = datetime
        self.m = TorontoHighTempModel()
        self.m.settlement_lag_model = {
            "component": {"min_context_n": 20},
            "revision_contexts": {
                "hour=17": {"n": 600, "revision_up_rate": 0.08},
                "hour=19": {"n": 600, "revision_up_rate": 0.02},
                "hour=20": {"n": 600, "revision_up_rate": 0.003},
            },
        }
        self.history = {"max_c": 24.0, "max_times": ["12:35"]}

    def _now(self, hour, minute=0):
        return self.datetime(2026, 6, 9, hour, minute)

    def test_plateau_evening_gets_learned_lock(self):
        strength = self.m.learned_lockin_strength(19, self.history, self._now(19, 10))
        self.assertAlmostEqual(strength, 0.98)

    def test_zero_before_learned_start_hour(self):
        self.assertEqual(
            self.m.learned_lockin_strength(16, self.history, self._now(16, 30)), 0.0
        )

    def test_zero_while_high_is_fresh(self):
        fresh = {"max_c": 24.0, "max_times": ["18:40"]}
        self.assertEqual(
            self.m.learned_lockin_strength(19, fresh, self._now(19, 30)), 0.0
        )

    def test_zero_without_artifact(self):
        self.m.settlement_lag_model = None
        self.assertEqual(
            self.m.learned_lockin_strength(19, self.history, self._now(19, 10)), 0.0
        )

    def test_late_evening_clamps_to_last_trained_hour(self):
        # hour 22 reuses the 20:00 context.
        strength = self.m.learned_lockin_strength(22, self.history, self._now(22, 0))
        self.assertAlmostEqual(strength, 0.997)

    def test_thin_context_is_ignored(self):
        self.m.settlement_lag_model["revision_contexts"]["hour=19"]["n"] = 5
        self.assertEqual(
            self.m.learned_lockin_strength(19, self.history, self._now(19, 10)), 0.0
        )


class TestApplyLateDayLockin(unittest.TestCase):
    def setUp(self):
        self.m = TorontoHighTempModel()

    def test_replays_june2_evening_locks_onto_observed_high(self):
        # The real failure: evening model kept ~35% on 26 while WU settled 25.
        peaked = {24: 0.10, 25: 0.50, 26: 0.35, 27: 0.05}
        out = self.m.apply_late_day_lockin(peaked, history_max=25.0, current_reading=19.0, hour=22)
        self.assertAlmostEqual(sum(out.values()), 1.0, places=9)
        self.assertEqual(max(out, key=out.get), 25)   # concentrates onto the observed high
        self.assertLess(out[26], peaked[26])           # upper tail suppressed
        self.assertGreater(out[26], 0.0)               # but soft (WU could revise up a degree)

    def test_noop_when_not_locked_in(self):
        peaked = {24: 0.10, 25: 0.50, 26: 0.40}
        out = self.m.apply_late_day_lockin(peaked, history_max=25.0, current_reading=25.5, hour=14)
        # Strength 0 -> proportions preserved.
        self.assertAlmostEqual(out[26] / out[25], 0.40 / 0.50)

    def test_does_not_touch_at_or_below_observed(self):
        peaked = {23: 0.2, 24: 0.2, 25: 0.4, 26: 0.2}
        out = self.m.apply_late_day_lockin(peaked, history_max=25.0, current_reading=18.0, hour=21)
        # 23, 24, 25 keep their pre-norm ratios; only 26 is suppressed.
        self.assertAlmostEqual(out[23] / out[24], 1.0)
        self.assertAlmostEqual(out[24] / out[25], 0.2 / 0.4)


class TestLateDayContinuationBlend(unittest.TestCase):
    def test_feature_path_blends_late_day_continuation_tail(self):
        model = TorontoHighTempModel(target_date="2026-05-28")
        model.calibrated_weights = None
        model.probability_calibration = None
        model.predict_feature_distribution = lambda sources, cutoff_hour, now: (
            {20: 0.70, 21: 0.20, 22: 0.10},
            "hgb",
        )
        model.predict_late_day_continuation = lambda sources, cutoff_hour, now: {
            "active": True,
            "continuation_probability": 0.85,
        }
        sources = {
            "local_history": {
                "ok": True,
                "data": {
                    "available": True,
                    "analysis": {
                        "target_window_count": 100,
                        "bucket_probabilities": {"20": 0.50, "21": 0.30, "22": 0.20},
                    },
                },
            },
            "wu_history": {
                "ok": True,
                "data": {"max_c": 20.0, "rows": [{"time": "15:00", "temp_c": 20.0}]},
            },
            "wu_current": {"ok": True, "data": {"temp_c": 20.0, "max_since_7am_c": 20.0}},
            "eccc_swob": {"ok": True, "data": {}},
            "eccc_citypage": {"ok": True, "data": {}},
            "metar": {"ok": True, "data": {}},
            "weather_forecast": {"ok": True, "data": {"rows": []}},
            "open_meteo": {"ok": True, "data": {"rows": []}},
        }

        model.estimate_distribution(sources, now=datetime(2026, 5, 28, 15, 30))
        components = model._last_distribution_components["components"]
        before_tail = sum(
            probability
            for bucket, probability in components["wu_floor_residual"].items()
            if bucket > 20
        )
        after_tail = sum(
            probability
            for bucket, probability in components["late_day_continuation_blend"].items()
            if bucket > 20
        )

        self.assertGreater(after_tail, before_tail)
        self.assertEqual(
            model._last_distribution_components["late_day_continuation"]["continuation_probability"],
            0.85,
        )


class TestHighHasStoodLockin(unittest.TestCase):
    def setUp(self):
        self.m = TorontoHighTempModel(target_date="2026-06-15", market_id="miami")
        self.m.settlement_lag_model = {
            "component": {"min_context_n": 20},
            "revision_contexts": {
                "hour=14": {"n": 600, "revision_up_rate": 0.27},
            },
        }
        self.history = {"max_native": 93.0, "max_c": 33.0, "max_times": ["12:53"]}
        self.now = datetime(2026, 6, 15, 14, 10)

    def _forecast(self, value):
        return {"rows": [{"time": "15:00", "temp_c": value}]}

    def test_activates_when_high_stood_current_rolled_and_forecasts_below(self):
        context = self.m.high_has_stood_lockin_context(
            14,
            self.history,
            92.0,
            self.now,
            self._forecast(90.0),
            self._forecast(92.1),
            self._forecast(90.0),
            self._forecast(89.6),
            {},
        )

        self.assertTrue(context["active"])
        self.assertEqual(context["reason"], "high_stood_current_rolled_forecasts_below")
        self.assertEqual(context["strength"], 1.0)
        self.assertEqual(context["stood_minutes"], 77)
        self.assertEqual(context["forecast_source_count"], 4)
        self.assertAlmostEqual(context["remaining_forecast_ceiling"], 92.1)
        self.assertEqual(context["remaining_degree_hours_above_high"], 0.0)
        self.assertAlmostEqual(context["revision_up_rate"], 0.27)

    def test_blocks_when_remaining_forecast_can_clear_the_high(self):
        context = self.m.high_has_stood_lockin_context(
            14,
            self.history,
            92.0,
            self.now,
            self._forecast(90.0),
            self._forecast(94.0),
            self._forecast(90.0),
            {},
            {},
        )

        self.assertFalse(context["active"])
        self.assertEqual(context["reason"], "forecast_ceiling_above_high")

    def test_blocks_when_live_temperature_has_not_rolled_below_high(self):
        context = self.m.high_has_stood_lockin_context(
            14,
            self.history,
            93.0,
            self.now,
            self._forecast(90.0),
            self._forecast(92.1),
            self._forecast(90.0),
            {},
            {},
        )

        self.assertFalse(context["active"])
        self.assertEqual(context["reason"], "current_not_below_high")

    def test_official_rollover_activates_when_third_party_current_is_flat(self):
        context = self.m.high_has_stood_lockin_context(
            14,
            self.history,
            93.0,
            self.now,
            self._forecast(90.0),
            self._forecast(92.1),
            self._forecast(90.0),
            {},
            {},
            official_current_reading=92.3,
            official_source="metar",
        )

        self.assertTrue(context["active"])
        self.assertEqual(context["reason"], "high_stood_official_rollover_forecasts_below")
        self.assertEqual(context["current_source_for_rollover"], "metar")
        self.assertTrue(context["official_rollover_signal"])
        self.assertAlmostEqual(context["third_party_current_minus_high"], 0.0)
        self.assertAlmostEqual(context["official_current_minus_high"], -0.7)
        self.assertAlmostEqual(context["current_minus_high"], -0.7)

    def test_stale_official_rollover_is_diagnostic_not_active(self):
        context = self.m.high_has_stood_lockin_context(
            14,
            self.history,
            93.0,
            self.now,
            self._forecast(90.0),
            self._forecast(92.1),
            official_current_reading=92.3,
            official_source="metar",
            official_current_stale=True,
        )

        self.assertFalse(context["active"])
        self.assertEqual(context["reason"], "official_current_stale")
        self.assertFalse(context["official_rollover_signal"])
        self.assertTrue(context["official_current_stale"])


class TestStandingHighPartialLockin(unittest.TestCase):
    def setUp(self):
        self.m = TorontoHighTempModel(target_date="2026-06-22", market_id="austin")
        self.history = {"max_native": 93.9, "max_times": ["13:53"]}
        self.now = datetime(2026, 6, 22, 14, 53)

    def _forecast(self, value):
        return {"rows": [{"time": "15:30", "temp_native": value}]}

    def test_activates_when_official_rollover_and_warm_ceiling_blocks_hard_lockin(self):
        context = self.m.standing_high_partial_lockin_context(
            14,
            self.history,
            93.9,
            self.now,
            self._forecast(95.5),
            self._forecast(95.8),
            official_current_reading=93.0,
            official_source="metar",
        )

        self.assertTrue(context["active"])
        self.assertEqual(
            context["reason"],
            "standing_high_partial_official_rollover_warm_forecast",
        )
        self.assertEqual(context["stage"], "partial_dampening")
        self.assertGreater(context["strength"], 0.0)
        self.assertLessEqual(context["strength"], 0.55)
        self.assertEqual(context["stood_minutes"], 60)
        self.assertAlmostEqual(context["official_current_minus_high"], -0.9)
        self.assertAlmostEqual(context["forecast_upside"], 1.9)

    def test_apply_reduces_warm_tail_but_preserves_one_and_two_up_rebound(self):
        scores = {93: 0.08, 94: 0.25, 95: 0.24, 96: 0.25, 97: 0.18}
        context = self.m.standing_high_partial_lockin_context(
            14,
            self.history,
            93.9,
            self.now,
            self._forecast(95.5),
            self._forecast(95.8),
            official_current_reading=93.0,
            official_source="metar",
        )

        out, context = self.m.apply_standing_high_partial_lockin(
            scores,
            self.history["max_native"],
            context,
        )

        self.assertAlmostEqual(sum(out.values()), 1.0, places=9)
        self.assertLess(
            context["tail_mass_above_high_after"],
            context["tail_mass_above_high_before"],
        )
        self.assertGreater(out[95], 0.0)
        self.assertGreater(out[96], 0.0)
        self.assertTrue(context["one_up_tail_preserved"])
        self.assertTrue(context["two_up_tail_preserved"])
        self.assertGreater(context["moved_probability"], 0.0)

    def test_partial_stage_is_recorded_when_hard_lockin_is_blocked_by_ceiling(self):
        pipeline = DistributionPipelineState()
        scores = {93: 0.08, 94: 0.25, 95: 0.24, 96: 0.25, 97: 0.18}

        out, strength, context = self.m.distribution_late_day_lockin_stage(
            scores,
            history=self.history,
            current_temp=93.9,
            metar_temp=93.0,
            history_max=self.history["max_native"],
            now=self.now,
            weather_forecast=self._forecast(95.5),
            open_meteo=self._forecast(95.8),
            nws_hourly={},
            global_ensemble={},
            eccc_city={},
            pipeline=pipeline,
        )

        partial = context["standing_high_partial_lockin"]
        self.assertEqual(context["stage_attribution"]["final_stage"], "partial_dampening")
        self.assertGreater(strength, 0.0)
        self.assertTrue(partial["active"])
        self.assertIn("standing_high_partial_lockin", pipeline.components)
        self.assertLess(
            partial["tail_mass_above_high_after"],
            partial["tail_mass_above_high_before"],
        )
        self.assertLess(out[97], scores[97])

    def test_stale_official_rollover_is_not_an_active_partial_dampener(self):
        context = self.m.standing_high_partial_lockin_context(
            14,
            self.history,
            93.9,
            self.now,
            self._forecast(95.5),
            official_current_reading=93.0,
            official_source="metar",
            official_current_stale=True,
        )

        self.assertFalse(context["active"])
        self.assertEqual(context["stage"], "no_action")
        self.assertEqual(context["reason"], "official_current_stale")

    def test_late_rebound_ceiling_is_not_partially_locked(self):
        context = self.m.standing_high_partial_lockin_context(
            14,
            self.history,
            93.9,
            self.now,
            self._forecast(98.0),
            self._forecast(98.5),
            official_current_reading=93.0,
            official_source="metar",
        )

        self.assertFalse(context["active"])
        self.assertEqual(context["reason"], "forecast_ceiling_too_high_for_partial")


class TestExpandedLateDayLockin(unittest.TestCase):
    def setUp(self):
        self.m = TorontoHighTempModel(target_date="2026-06-20")
        self.history = {"max_c": 24.0, "max_times": ["12:20"]}
        self.now = datetime(2026, 6, 20, 16, 10)

    def _forecast(self, value):
        return {"rows": [{"time": "17:00", "temp_c": value}]}

    def test_covers_late_day_high_that_has_stood_and_current_has_rolled(self):
        context = self.m.expanded_late_day_lockin_context(
            16,
            self.history,
            23.0,
            self.now,
            self._forecast(24.0),
            self._forecast(23.5),
        )

        self.assertTrue(context["active"])
        self.assertEqual(context["reason"], "expanded_late_day_current_below_high")
        self.assertGreater(
            context["strength"],
            self.m.late_day_lockin_strength(16, 23.0, 24.0),
        )
        self.assertEqual(context["stood_minutes"], 230)

    def test_blocks_when_remaining_forecast_can_clear_high(self):
        context = self.m.expanded_late_day_lockin_context(
            16,
            self.history,
            23.0,
            self.now,
            self._forecast(25.5),
        )

        self.assertFalse(context["active"])
        self.assertEqual(context["reason"], "forecast_ceiling_above_high")

    def test_expanded_lockin_uses_official_rollover_when_current_flat(self):
        context = self.m.expanded_late_day_lockin_context(
            16,
            self.history,
            24.0,
            self.now,
            self._forecast(24.0),
            self._forecast(23.5),
            official_current_reading=23.4,
            official_source="metar",
        )

        self.assertTrue(context["active"])
        self.assertEqual(context["reason"], "expanded_late_day_official_rollover")
        self.assertEqual(context["current_source_for_rollover"], "metar")
        self.assertTrue(context["official_rollover_signal"])


if __name__ == "__main__":
    unittest.main()
