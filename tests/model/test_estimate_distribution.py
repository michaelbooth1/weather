import os
import sys
import unittest
from datetime import datetime
from weather.model.toronto_model import TorontoHighTempModel, TORONTO_TZ, _UNLOADED
from weather.model.model_distribution import DistributionPipelineState
from weather.model.model_contracts import DistributionResult


def _wu_row(time, temp, dew=10.0, hum=60.0, press=1015.0,
            wind="SW", wind_kmh=15.0, clouds="Partly Cloudy",
            condition="Partly Cloudy"):
    """A row shaped like fetch_wu_history output."""
    return {
        "time": time,
        "datetime": f"2026-05-29T{time}:00-04:00",
        "temp_c": temp,
        "dewpoint_c": dew,
        "humidity": hum,
        "pressure": press,
        "clouds": clouds,
        "condition": condition,
        "wind": wind,
        "wind_kmh": wind_kmh,
        "gust_kmh": None,
    }


def _sources(rows, max_c):
    max_times = [r["time"] for r in rows if r["temp_c"] == max_c]
    return {
        "wu_history": {
            "ok": True,
            "data": {
                "url": "test",
                "rows": rows,
                "latest": rows[-1] if rows else None,
                "max_c": max_c,
                "max_times": max_times,
            },
        }
    }


class TestEstimateDistribution(unittest.TestCase):
    def setUp(self):
        self.model = TorontoHighTempModel(target_date="2026-05-29")

    def _assert_valid_distribution(self, dist):
        self.assertIsInstance(dist, dict)
        if not dist:
            return
        self.assertAlmostEqual(sum(dist.values()), 1.0, places=6)
        self.assertTrue(all(0.0 <= p <= 1.0 for p in dist.values()))
        self.assertTrue(all(isinstance(t, int) for t in dist))

    def test_returns_normalized_distribution(self):
        rows = [
            _wu_row("07:00", 14.0),
            _wu_row("10:00", 18.0),
            _wu_row("12:00", 21.0),
            _wu_row("14:00", 22.0),
        ]
        dist = self.model.estimate_distribution(_sources(rows, 22.0))
        self._assert_valid_distribution(dist)
        self.assertTrue(dist)  # non-empty for real inputs

    def test_floor_suppresses_buckets_below_printed_high(self):
        # A printed high of 26 C is the settlement floor: the final high can
        # only be >= 26, so probability below 26 must be negligible.
        rows = [
            _wu_row("07:00", 18.0),
            _wu_row("10:00", 23.0),
            _wu_row("12:00", 26.0),
            _wu_row("14:00", 25.0),
        ]
        dist = self.model.estimate_distribution(_sources(rows, 26.0))
        self._assert_valid_distribution(dist)
        below = sum(p for t, p in dist.items() if t < 26)
        at_or_above = sum(p for t, p in dist.items() if t >= 26)
        self.assertLess(below, 0.05)
        self.assertGreater(at_or_above, 0.80)

    def test_estimate_distribution_prefers_native_live_max_aliases(self):
        model = TorontoHighTempModel(target_date="2026-05-29", market_id="nyc")
        sources = {
            "wu_history": {
                "ok": True,
                "data": {
                    "max_native": 91.0,
                    "max_c": 31.0,
                    "max_times": ["12:00"],
                    "rows": [{"time": "12:00", "temp_native": 91.0, "temp_c": 31.0}],
                },
            },
            "wu_current": {
                "ok": True,
                "data": {
                    "temp_native": 89.0,
                    "temp_c": 29.0,
                    "max_since_7am_native": 92.0,
                    "max_since_7am_c": 32.0,
                },
            },
            "eccc_swob": {
                "ok": True,
                "data": {"same_day_max_native": 90.0, "same_day_max_c": 30.0},
            },
            "metar": {"ok": True, "data": {"temp_native": 88.0, "temp_c": 28.0}},
            "local_history": {"ok": True, "data": {}},
            "eccc_citypage": {"ok": True, "data": {}},
            "weather_forecast": {"ok": True, "data": {"rows": []}},
            "open_meteo": {"ok": True, "data": {"rows": []}},
        }

        model.estimate_distribution(sources, now=datetime(2026, 5, 29, 14, 0, tzinfo=TORONTO_TZ))

        context = model._last_probability_calibration_context
        self.assertEqual(context["wu_history_floor_bucket"], 91)
        self.assertEqual(context["observed_support_bucket"], 91)
        self.assertGreaterEqual(context["current_observed_bucket"], 91)

    def test_printed_history_floor_is_applied_once(self):
        rows = [
            _wu_row("07:00", 18.0),
            _wu_row("12:00", 26.0),
            _wu_row("14:00", 25.0),
        ]
        calls = []
        original_apply_floor = self.model.apply_floor

        def recording_apply_floor(scores, floor_bucket, multiplier):
            calls.append((floor_bucket, multiplier))
            return original_apply_floor(scores, floor_bucket, multiplier)

        self.model.apply_floor = recording_apply_floor
        self.model.estimate_distribution(_sources(rows, 26.0))

        self.assertEqual(calls, [(26, 0.000001)])

    def test_empty_sources_is_safe(self):
        dist = self.model.estimate_distribution({})
        self._assert_valid_distribution(dist)

    def test_deterministic_with_fixed_now(self):
        # With a pinned `now`, the engine must be fully deterministic — this is
        # what makes backtesting possible.
        rows = [_wu_row("07:00", 14.0), _wu_row("12:00", 21.0), _wu_row("14:00", 22.0)]
        now = datetime(2026, 5, 29, 14, 0, tzinfo=TORONTO_TZ)
        d1 = self.model.estimate_distribution(_sources(rows, 22.0), now=now)
        d2 = self.model.estimate_distribution(_sources(rows, 22.0), now=now)
        self.assertEqual(d1, d2)

    def test_build_threads_now_without_network(self):
        rows = [_wu_row("07:00", 14.0), _wu_row("13:00", 21.0)]
        now = datetime(2026, 5, 29, 14, 0, tzinfo=TORONTO_TZ)
        event = {"markets": [], "slug": "highest-temperature-in-toronto-on-may-29-2026"}
        model = self.model.build(
            event,
            historical_sources={},
            live_sources=_sources(rows, 21.0),
            now=now,
        )
        self.assertIn("distribution", model)
        self._assert_valid_distribution(model["distribution"])
        self.assertEqual(model["model_explanation"]["feature_cutoff_hour"], 13)
        self.assertEqual(model["model_explanation"]["latest_wu_history_time"], "13:00")
        self.assertIn("distribution_result", model)
        self.assertEqual(model["distribution_result"]["distribution"], model["distribution"])
        self.assertEqual(
            model["distribution_result"]["distribution_components"],
            model["distribution_components"],
        )
        self.assertIn("probability_calibration_context", model)
        self.assertIn("source_bundle", model)

    def test_estimate_distribution_result_captures_metadata(self):
        rows = [_wu_row("07:00", 14.0), _wu_row("12:00", 21.0), _wu_row("14:00", 22.0)]
        now = datetime(2026, 5, 29, 14, 0, tzinfo=TORONTO_TZ)

        result = self.model.estimate_distribution_result(_sources(rows, 22.0), now=now)

        self.assertIsInstance(result, DistributionResult)
        self._assert_valid_distribution(result.distribution)
        self.assertEqual(result.component_payload["components"]["final_model"], result.distribution)
        self.assertEqual(result.component_payload["cutoff_hour"], 14)
        self.assertEqual(result.calibration_context["cutoff_hour"], 14)
        self.assertEqual(result.active_model_kind, result.component_payload["active_model_kind"])
        self.assertIn(result.active_model_kind, {"empirical", "hgb", "lr"})

    def test_distribution_results_are_isolated_between_repeated_builds(self):
        first_rows = [_wu_row("07:00", 14.0), _wu_row("12:00", 21.0)]
        second_rows = [_wu_row("07:00", 18.0), _wu_row("15:00", 26.0)]

        first = self.model.estimate_distribution_result(
            _sources(first_rows, 21.0),
            now=datetime(2026, 5, 29, 12, 0, tzinfo=TORONTO_TZ),
        )
        second = self.model.estimate_distribution_result(
            _sources(second_rows, 26.0),
            now=datetime(2026, 5, 29, 15, 0, tzinfo=TORONTO_TZ),
        )

        self.assertEqual(first.component_payload["latest_wu_history_time"], "12:00")
        self.assertEqual(second.component_payload["latest_wu_history_time"], "15:00")
        self.assertEqual(first.calibration_context["wu_history_floor_bucket"], 21)
        self.assertEqual(second.calibration_context["wu_history_floor_bucket"], 26)

    def test_distribution_pipeline_state_payload_matches_returned_distribution(self):
        rows = [_wu_row("07:00", 14.0), _wu_row("12:00", 21.0), _wu_row("14:00", 22.0)]
        now = datetime(2026, 5, 29, 14, 0, tzinfo=TORONTO_TZ)

        dist = self.model.estimate_distribution(_sources(rows, 22.0), now=now)

        payload = self.model._last_distribution_components
        self.assertIsInstance(self.model._last_distribution_pipeline_state, DistributionPipelineState)
        self.assertEqual(payload["schema_version"], "toronto_distribution_components_v0.1")
        self.assertEqual(payload["cutoff_hour"], 14)
        self.assertEqual(payload["latest_wu_history_time"], "14:00")
        self.assertEqual(payload["components"]["final_model"], dist)
        self.assertIn("climatology_prior", payload["components"])
        self.assertIn("post_live_signals", payload["components"])


class TestDistributionHelpers(unittest.TestCase):
    def setUp(self):
        self.model = TorontoHighTempModel(target_date="2026-05-29")

    def test_pipeline_state_records_named_snapshots_and_metadata(self):
        state = DistributionPipelineState()

        state.snapshot("raw", {20: 2.0})
        state.snapshot_normalized("normalized", {20: 1.0, 21: 1.0}, self.model.normalize_scores)
        state.update_metadata(cutoff_hour=14, active_model_kind="empirical")
        payload = state.payload()

        self.assertEqual(payload["schema_version"], "toronto_distribution_components_v0.1")
        self.assertEqual(payload["cutoff_hour"], 14)
        self.assertEqual(payload["active_model_kind"], "empirical")
        self.assertEqual(payload["components"]["raw"], {20: 2.0})
        self.assertAlmostEqual(payload["components"]["normalized"][20], 0.5)
        self.assertAlmostEqual(payload["components"]["normalized"][21], 0.5)

    def test_blend_distribution_is_convex_combination(self):
        out = self.model.blend_distribution({20: 1.0}, {22: 1.0}, 0.5)
        self.assertAlmostEqual(out[20], 0.5)
        self.assertAlmostEqual(out[22], 0.5)
        self.assertAlmostEqual(sum(out.values()), 1.0, places=6)

    def test_blend_distribution_zero_weight_keeps_base(self):
        out = self.model.blend_distribution({20: 1.0, 21: 1.0}, {25: 1.0}, 0.0)
        self.assertAlmostEqual(out[20], 0.5)
        self.assertAlmostEqual(out[21], 0.5)
        self.assertNotIn(25, out)

    def test_apply_tail_target_moves_tail_mass(self):
        scores = {20: 1, 21: 1, 22: 1, 23: 1, 24: 1}
        out = self.model.apply_tail_target(scores, threshold=22, target_tail=0.8, weight=1.0)
        tail = sum(p for t, p in out.items() if t > 22)
        self.assertAlmostEqual(tail, 0.8, places=5)
        self.assertAlmostEqual(sum(out.values()), 1.0, places=6)

    def test_cap_prior_distribution_peaks_at_cap_and_decays(self):
        out = self.model.cap_prior_distribution(range(20, 30), cap_bucket=25, floor_bucket=22)
        self.assertAlmostEqual(sum(out.values()), 1.0, places=6)
        self.assertEqual(max(out, key=out.get), 25)   # peak at the cap
        self.assertGreater(out[25], out[27])           # decays above the cap
        self.assertLess(out[20], out[25])              # suppressed below the floor

    def test_apply_floor_scales_below_floor_in_place(self):
        scores = {20: 1.0, 21: 1.0, 22: 1.0}
        self.model.apply_floor(scores, floor_bucket=22, multiplier=0.001)
        self.assertAlmostEqual(scores[20], 0.001)
        self.assertAlmostEqual(scores[21], 0.001)
        self.assertAlmostEqual(scores[22], 1.0)

    def test_feature_model_live_signal_stage_clusters_peak_sources(self):
        signals = self.model.distribution_live_signals(
            using_feature_model=True,
            using_calibrated_empirical=False,
            hour=14,
            history_max=24.0,
            current_temp=24.0,
            current_max=24.0,
            eccc_max=25.0,
            metar_live_signal=(26.0, 0.3, 0.9),
            weather_forecast_max=27.2,
            open_meteo_max=26.6,
            nws_forecast_max=None,
            global_ensemble_max=None,
            eccc_forecast_high=26.0,
            observed_bucket=24,
        )

        self.assertEqual(signals[0], (27.2, 1.6, 1.0))
        self.assertEqual(signals[1], (25.0, 0.6, 0.8))
        self.assertEqual(signals[2], (26.0, 0.5, 1.2))

    def test_calibrated_empirical_live_signal_stage_is_minimal(self):
        signals = self.model.distribution_live_signals(
            using_feature_model=False,
            using_calibrated_empirical=True,
            hour=15,
            history_max=24.0,
            current_temp=25.0,
            current_max=26.0,
            eccc_max=25.3,
            metar_live_signal=None,
            weather_forecast_max=27.0,
            open_meteo_max=27.0,
            nws_forecast_max=27.0,
            global_ensemble_max=27.0,
            eccc_forecast_high=27.0,
            observed_bucket=24,
        )

        self.assertEqual(len(signals), 3)
        self.assertEqual(signals[0], (24.0, self.model.history_signal_weight(15), 0.65))
        self.assertEqual(signals[1], (25, 0.6, 0.9))
        self.assertEqual(signals[2], (None, 0.0, 0.90))

    def test_empirical_live_signal_stage_keeps_independent_sources(self):
        signals = self.model.distribution_live_signals(
            using_feature_model=False,
            using_calibrated_empirical=False,
            hour=12,
            history_max=22.0,
            current_temp=23.0,
            current_max=24.0,
            eccc_max=23.4,
            metar_live_signal=(23.0, 0.2, 0.9),
            weather_forecast_max=25.0,
            open_meteo_max=25.4,
            nws_forecast_max=26.1,
            global_ensemble_max=24.7,
            eccc_forecast_high=25.0,
            observed_bucket=22,
        )

        self.assertEqual(len(signals), 10)
        self.assertEqual(signals[0], (22.0, self.model.history_signal_weight(12), 0.65))
        self.assertEqual(signals[1], (23.0, 1.8, 0.65))
        self.assertEqual(signals[2], (24.0, 2.3, 0.75))
        self.assertEqual(signals[4], (23.0, 0.2, 0.9))
        self.assertEqual(signals[-1], (25.0, 0.5, 1.2))

    def test_live_signal_application_stage_records_snapshot(self):
        pipeline = DistributionPipelineState()
        scores = {20: 0.25, 21: 0.5, 22: 0.25}

        out = self.model.distribution_apply_live_signals_stage(
            scores,
            [(21.0, 1.0, 0.5)],
            pipeline,
        )

        self.assertAlmostEqual(sum(out.values()), 1.0, places=6)
        for bucket, probability in out.items():
            self.assertAlmostEqual(
                pipeline.components["post_live_signals"][bucket],
                probability,
            )
        self.assertGreater(out[21], out[20])

    def test_model_path_stage_records_feature_model_snapshots(self):
        pipeline = DistributionPipelineState()
        scores = {20: 0.5, 21: 0.5}
        self.model.predict_feature_distribution = (
            lambda sources, cutoff_hour, now: ({20: 0.2, 21: 0.8}, "unit")
        )
        self.model.feature_blend_weight = lambda cutoff_hour: 1.0
        now = datetime(2026, 5, 29, 12, 0, tzinfo=TORONTO_TZ)

        out, intraday, using_feature_model, using_calibrated_empirical = (
            self.model.distribution_model_path_stage(
                scores,
                sources={},
                cutoff_hour=12,
                now=now,
                observed_bucket=20,
                current={},
                weather_forecast={},
                eccc_city={},
                current_temp=None,
                weather_forecast_max=None,
                open_meteo_max=None,
                nws_forecast_max=None,
                global_ensemble_max=None,
                eccc_forecast_high=None,
                weights_config={},
                weight_map={},
                has_component_weights=False,
                pipeline=pipeline,
            )
        )

        self.assertIsNone(intraday)
        self.assertTrue(using_feature_model)
        self.assertFalse(using_calibrated_empirical)
        self.assertEqual(self.model.active_model_kind, "unit")
        self.assertIn("unit_feature_model", pipeline.components)
        self.assertEqual(pipeline.components["feature_blend"], out)

    def test_forecast_shape_stage_is_noop_for_calibrated_empirical_path(self):
        pipeline = DistributionPipelineState()
        scores = {20: 0.25, 21: 0.75}
        now = datetime(2026, 5, 29, 12, 0, tzinfo=TORONTO_TZ)

        out = self.model.distribution_forecast_shape_stage(
            scores,
            forecast_values=[25.0],
            history={"rows": []},
            now=now,
            observed_bucket=20,
            current_observed_bucket=20,
            using_calibrated_empirical=True,
            pipeline=pipeline,
        )

        self.assertEqual(out, scores)
        self.assertNotIn("forecast_pull", pipeline.components)

    def test_observed_floor_stage_records_each_floor_snapshot(self):
        pipeline = DistributionPipelineState()
        scores = {20: 0.2, 21: 0.3, 22: 0.5}

        out = self.model.distribution_observed_floor_stage(
            scores,
            eccc_max=None,
            current_temp=None,
            metar_temp=None,
            history_max=22.0,
            observed_support_bucket=22,
            hour=14,
            pipeline=pipeline,
        )

        self.assertAlmostEqual(sum(out.values()), 1.0, places=6)
        self.assertEqual(pipeline.components["wu_floor_residual"], out)
        self.assertIn("settlement_lag_adjusted", pipeline.components)
        self.assertIn("current_observed_floor", pipeline.components)

    def test_effective_cutoff_uses_first_trained_hour_when_only_pre_cutoff_rows_printed(self):
        now = datetime(2026, 5, 29, 14, 0, tzinfo=TORONTO_TZ)
        rows = [_wu_row("06:50", 14.0)]

        self.assertEqual(self.model.effective_intraday_cutoff_hour(now, rows), 7)

    def test_effective_cutoff_aliases_near_boundary_settlement_print(self):
        now = datetime(2026, 5, 29, 14, 9, tzinfo=TORONTO_TZ)
        rows = [_wu_row("07:00", 14.0), _wu_row("12:53", 24.0)]

        self.assertEqual(self.model.effective_intraday_cutoff_hour(now, rows), 13)

    def test_effective_cutoff_does_not_alias_stale_or_future_cutoff_prints(self):
        now = datetime(2026, 5, 29, 14, 9, tzinfo=TORONTO_TZ)
        self.assertEqual(
            self.model.effective_intraday_cutoff_hour(
                now,
                [_wu_row("07:00", 14.0), _wu_row("12:49", 24.0)],
            ),
            12,
        )

        before_13h = datetime(2026, 5, 29, 12, 59, tzinfo=TORONTO_TZ)
        self.assertEqual(
            self.model.effective_intraday_cutoff_hour(
                before_13h,
                [_wu_row("07:00", 14.0), _wu_row("12:53", 24.0)],
            ),
            12,
        )

    def test_effective_cutoff_alias_ignores_non_target_date_rows(self):
        now = datetime(2026, 5, 29, 14, 9, tzinfo=TORONTO_TZ)
        stale_row = _wu_row("12:53", 24.0)
        stale_row["datetime"] = "2026-05-28T12:53:00-04:00"
        rows = [_wu_row("07:00", 14.0), _wu_row("12:00", 21.0), stale_row]

        self.assertEqual(self.model.effective_intraday_cutoff_hour(now, rows), 12)


class TestModelLoadCaching(unittest.TestCase):
    """#10: model artifacts should be read from disk once, then reused."""

    def test_feature_model_hgb_is_memoized(self):
        model = TorontoHighTempModel()
        self.assertIs(model._feature_model_hgb, _UNLOADED)
        first = model.load_feature_model_hgb()
        self.assertIsNot(model._feature_model_hgb, _UNLOADED)
        second = model.load_feature_model_hgb()
        self.assertIs(first, second)  # same object, not re-read from disk

    def test_late_day_coefs_is_memoized(self):
        model = TorontoHighTempModel()
        self.assertIs(model._late_day_model_coefs, _UNLOADED)
        first = model.load_late_day_model_coefs()
        second = model.load_late_day_model_coefs()
        self.assertIs(first, second)


if __name__ == "__main__":
    unittest.main()
