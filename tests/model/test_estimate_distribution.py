import os
import sys
import unittest
from datetime import datetime
from weather.model.toronto_model import TorontoHighTempModel, TORONTO_TZ, _UNLOADED
from weather.model.model_distribution import (
    DistributionPipelineState,
    EMPIRICAL_FORECAST_SHAPE_ALLOWED_MARKETS,
)
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

    def test_distribution_result_rebuilds_and_isolates_legacy_last_fields(self):
        self.model._last_distribution_components = {
            "components": {"final_model": {999: 1.0}},
            "active_model_kind": "stale",
        }
        self.model._last_probability_calibration_context = {"cutoff_hour": 99}
        self.model._last_family_secondary_gate = {"mode": "stale"}
        rows = [_wu_row("07:00", 14.0), _wu_row("13:00", 23.0)]

        result = self.model.estimate_distribution_result(
            _sources(rows, 23.0),
            now=datetime(2026, 5, 29, 13, 0, tzinfo=TORONTO_TZ),
        )

        self.assertNotIn(999, result.component_payload["components"]["final_model"])
        self.assertEqual(result.calibration_context["cutoff_hour"], 13)
        self.assertEqual(self.model._last_distribution_result, result)
        self.assertEqual(self.model._last_distribution_components, result.component_payload)
        self.assertEqual(self.model._last_probability_calibration_context, result.calibration_context)
        self.assertEqual(self.model._last_family_secondary_gate, result.family_secondary_gate)

        self.model._last_distribution_components["components"]["final_model"] = {999: 1.0}
        self.assertNotEqual(
            self.model._last_distribution_components["components"]["final_model"],
            result.component_payload["components"]["final_model"],
        )

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

        self.assertLess(signals[0][0], 27.2)
        self.assertEqual(signals[0][0], 27.0)
        self.assertLessEqual(signals[0][1], 1.6)
        self.assertEqual(signals[0][2], 1.0)
        self.assertEqual(signals[1], (25.0, 0.6, 0.8))
        self.assertEqual(signals[2], (26.0, 0.5, 1.2))

    def test_feature_model_live_signal_uses_robust_forecast_cluster(self):
        model = TorontoHighTempModel(target_date="2026-06-22", market_id="austin")

        signals = model.distribution_live_signals(
            using_feature_model=True,
            using_calibrated_empirical=False,
            hour=14,
            history_max=94.0,
            current_temp=94.0,
            current_max=94.0,
            eccc_max=None,
            metar_live_signal=None,
            weather_forecast_max=94.0,
            open_meteo_max=93.0,
            nws_forecast_max=95.0,
            global_ensemble_max=95.9,
            eccc_forecast_high=None,
            observed_bucket=94,
        )

        self.assertEqual(signals[0][0], 94.5)
        self.assertLess(signals[0][0], 96.0)
        self.assertLessEqual(signals[0][1], 1.6)

    def test_live_signal_stage_nulls_pre_reset_current_max(self):
        feature_signals = self.model.distribution_live_signals(
            using_feature_model=True,
            using_calibrated_empirical=False,
            hour=6,
            history_max=20.0,
            current_temp=20.0,
            current_max=30.0,
            eccc_max=None,
            metar_live_signal=None,
            weather_forecast_max=None,
            open_meteo_max=None,
            nws_forecast_max=None,
            global_ensemble_max=None,
            eccc_forecast_high=None,
            observed_bucket=20,
        )
        empirical_signals = self.model.distribution_live_signals(
            using_feature_model=False,
            using_calibrated_empirical=False,
            hour=6,
            history_max=20.0,
            current_temp=20.0,
            current_max=30.0,
            eccc_max=None,
            metar_live_signal=None,
            weather_forecast_max=None,
            open_meteo_max=None,
            nws_forecast_max=None,
            global_ensemble_max=None,
            eccc_forecast_high=None,
            observed_bucket=20,
        )

        self.assertEqual(feature_signals[0], (None, 1.1, 1.0))
        self.assertEqual(empirical_signals[2], (None, 2.3, 0.75))

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

        expected_cluster = self.model.forecast_source_cluster_signal(
            12,
            weather_forecast_max=25.0,
            open_meteo_max=25.4,
            nws_forecast_max=26.1,
            global_ensemble_max=24.7,
            eccc_forecast_high=25.0,
        )

        self.assertEqual(len(signals), 6)
        self.assertEqual(signals[0], (22.0, self.model.history_signal_weight(12), 0.65))
        self.assertEqual(signals[1], (23.0, 1.8, 0.65))
        self.assertEqual(signals[2], (24.0, 2.3, 0.75))
        self.assertEqual(signals[3], (23, 0.6, 0.9))
        self.assertEqual(signals[4], (23.0, 0.2, 0.9))
        self.assertEqual(signals[5], expected_cluster)
        self.assertEqual(expected_cluster[0], 25.0)
        self.assertGreater(expected_cluster[1], self.model.forecast_signal_weight(12))
        self.assertLess(expected_cluster[1], 4.4)

    def test_forecast_source_cluster_caps_and_penalizes_correlated_votes(self):
        agreed = self.model.forecast_source_cluster_signal(
            12,
            weather_forecast_max=25.0,
            open_meteo_max=25.0,
            nws_forecast_max=25.0,
            global_ensemble_max=25.0,
            eccc_forecast_high=25.0,
        )
        split = self.model.forecast_source_cluster_signal(
            12,
            weather_forecast_max=23.0,
            open_meteo_max=26.0,
            nws_forecast_max=27.0,
            global_ensemble_max=24.0,
            eccc_forecast_high=25.0,
        )

        self.assertEqual(agreed, (25.0, 2.4, 1.1))
        self.assertEqual(split[0], 25.0)
        self.assertLess(split[1], agreed[1])

    def test_forecast_ensemble_metrics_flags_native_scaled_warm_outlier(self):
        model = TorontoHighTempModel(target_date="2026-06-20", market_id="nyc")

        metrics = model.forecast_ensemble_metrics(
            {"rows": [{"time": "14:00", "temp_native": 98.0, "temp_c": 36.7}]},
            {"rows": [{"time": "14:00", "temp_native": 88.0, "temp_c": 31.1}]},
            {"forecast_high_native": 89.0, "forecast_high_c": 31.7},
            nws_hourly={"rows": [{"time": "14:00", "temp_native": 88.0, "temp_c": 31.1}]},
        )

        self.assertEqual(metrics["forecast_warm_outlier_flag"], 1.0)
        self.assertLess(metrics["forecast_robust_high"], 98.0)
        self.assertGreaterEqual(
            metrics["forecast_warm_outlier_gap"],
            model.spec.scale_delta(3.0),
        )

    def test_robust_forecast_signal_caps_isolated_warm_source(self):
        context = {
            "forecast_robust_high": 25.0,
            "forecast_disagreement": 6.0,
            "forecast_warm_outlier_flag": 1.0,
        }

        capped = self.model.robust_forecast_signal_value(30.0, context)

        self.assertEqual(capped, 26.0)

    def test_ramp_warm_tail_dampening_suppresses_tail_above_robust_anchor(self):
        scores = {23: 0.15, 24: 0.25, 25: 0.20, 26: 0.18, 27: 0.14, 28: 0.08}

        out, context = self.model.apply_ramp_warm_tail_dampening(
            scores,
            hour=12,
            observed_bucket=24,
            current_observed_bucket=24,
            robust_forecast_high=24.5,
            forecast_disagreement=5.0,
            warm_outlier_flag=True,
        )

        before_tail = sum(probability for bucket, probability in scores.items() if bucket > context["cap_bucket"])
        after_tail = sum(probability for bucket, probability in out.items() if bucket > context["cap_bucket"])
        self.assertTrue(context["active"])
        self.assertAlmostEqual(sum(out.values()), 1.0, places=6)
        self.assertLess(after_tail, before_tail)

    def test_afternoon_residual_centering_stage_shifts_distribution(self):
        model = TorontoHighTempModel(target_date="2026-06-22", market_id="nyc")
        model.afternoon_residual_centering = {
            "component": {
                "enabled": True,
                "start_hour": 15,
                "end_hour": 18,
                "min_context_n": 1,
                "max_abs_shift": 2.0,
                "disagreement_reference": 3.0,
                "spread_blend_per_unit": 0.05,
                "spread_blend_max": 0.35,
            },
            "contexts": {
                "market=nyc|hour=16": {
                    "n": 5,
                    "mean_residual": -1.0,
                    "mean_expected_minus_settlement": 1.0,
                }
            },
        }
        pipeline = DistributionPipelineState()
        scores = {88: 0.2, 89: 0.3, 90: 0.5}

        out, context = model.distribution_afternoon_residual_centering_stage(
            scores,
            hour=16,
            forecast_context={"forecast_disagreement": 6.0},
            pipeline=pipeline,
        )

        self.assertTrue(context["active"])
        self.assertIn("afternoon_residual_centering", pipeline.components)
        self.assertLess(sum(bucket * probability for bucket, probability in out.items()), 89.3)

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
        self.assertEqual(pipeline.components["unit_feature_model"], {20: 0.2, 21: 0.8})
        self.assertFalse(pipeline.metadata["feature_ordinal_smoothing"]["enabled"])
        self.assertEqual(pipeline.components["feature_blend"], out)

    def test_model_path_stage_applies_feature_smoothing_only_when_artifact_enables_it(self):
        pipeline = DistributionPipelineState()
        scores = {18: 0.2, 19: 0.2, 20: 0.2, 21: 0.2, 22: 0.2}
        raw = {18: 0.06, 19: 0.44, 20: 0.02, 21: 0.28, 22: 0.20}
        self.model.predict_feature_distribution = lambda sources, cutoff_hour, now: (raw, "unit")
        self.model.feature_blend_weight = lambda cutoff_hour: 1.0
        self.model.feature_ordinal_smoothing_config = lambda cutoff_hour: {
            "enabled": True,
            "sigma": 0.75,
            "blend_weight": 0.50,
            "source": "artifact",
        }
        now = datetime(2026, 5, 29, 12, 0, tzinfo=TORONTO_TZ)

        out, _intraday, using_feature_model, _using_calibrated_empirical = (
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

        self.assertTrue(using_feature_model)
        self.assertTrue(pipeline.metadata["feature_ordinal_smoothing"]["enabled"])
        self.assertGreater(pipeline.components["unit_feature_model"][20], raw[20])
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
            using_feature_model=False,
            using_calibrated_empirical=True,
            pipeline=pipeline,
        )

        self.assertEqual(out, scores)
        self.assertNotIn("forecast_pull", pipeline.components)

    def test_forecast_shape_stage_is_noop_for_feature_model_path(self):
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
            using_feature_model=True,
            using_calibrated_empirical=False,
            pipeline=pipeline,
        )

        self.assertEqual(out, scores)
        self.assertNotIn("forecast_pull", pipeline.components)

    def test_forecast_shape_stage_applies_to_validated_empirical_fallback_market(self):
        pipeline = DistributionPipelineState()
        scores = {20: 0.70, 21: 0.20, 22: 0.10}
        now = datetime(2026, 5, 29, 10, 0, tzinfo=TORONTO_TZ)

        self.assertIn("toronto", EMPIRICAL_FORECAST_SHAPE_ALLOWED_MARKETS)
        out = self.model.distribution_forecast_shape_stage(
            scores,
            forecast_values=[22.0, 22.1],
            history={"rows": []},
            now=now,
            observed_bucket=20,
            current_observed_bucket=20,
            using_feature_model=False,
            using_calibrated_empirical=False,
            pipeline=pipeline,
        )

        self.assertNotEqual(out, scores)
        self.assertIn("forecast_pull", pipeline.components)
        self.assertTrue(pipeline.metadata["forecast_shape_policy"]["enabled"])

    def test_forecast_shape_stage_blocks_unvalidated_empirical_fallback_market(self):
        model = TorontoHighTempModel(target_date="2026-05-29", market_id="atlanta")
        pipeline = DistributionPipelineState()
        scores = {20: 0.70, 21: 0.20, 22: 0.10}
        now = datetime(2026, 5, 29, 10, 0, tzinfo=TORONTO_TZ)

        out = model.distribution_forecast_shape_stage(
            scores,
            forecast_values=[22.0, 22.1],
            history={"rows": []},
            now=now,
            observed_bucket=20,
            current_observed_bucket=20,
            using_feature_model=False,
            using_calibrated_empirical=False,
            pipeline=pipeline,
        )

        self.assertEqual(out, scores)
        self.assertNotIn("forecast_pull", pipeline.components)
        self.assertFalse(pipeline.metadata["forecast_shape_policy"]["enabled"])
        self.assertEqual(
            pipeline.metadata["forecast_shape_policy"]["reason"],
            "empirical_fallback_market_not_validated",
        )
        self.assertAlmostEqual(sum(out.values()), 1.0, places=6)

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
