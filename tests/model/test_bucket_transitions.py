import os
import sys
import unittest
from datetime import date, datetime
from weather.model.toronto_model import TorontoHighTempModel


def _row(minute, temp):
    return {"minute_of_day": minute, "time": f"{minute // 60:02d}:{minute % 60:02d}", "temp_c": temp}


class TestBucketTransitionModel(unittest.TestCase):
    def test_transition_model_returns_probabilities_skip_and_update_timing(self):
        model = TorontoHighTempModel(target_date="2026-05-28")
        daily = {}
        by_date = {}
        finals = [20, 21, 21, 22, 20, 23]
        updates = [None, 14 * 60, 16 * 60, 13 * 60, None, 15 * 60]
        for idx, final in enumerate(finals, start=1):
            local_date = date(2020, 5, idx)
            daily[local_date] = {"bucket": final}
            rows = [_row(12 * 60, 20.0)]
            if updates[idx - 1] is not None:
                rows.append(_row(updates[idx - 1], float(final)))
            by_date[local_date] = rows
        model.historical_target_cache = lambda: {"daily": daily, "by_date": by_date}
        sources = {
            "wu_history": {
                "ok": True,
                "data": {"max_c": 20.0, "rows": [_row(12 * 60, 20.0)]},
            }
        }

        result = model.bucket_transition_model(
            sources,
            now=datetime(2026, 5, 28, 12, 30),
            min_sample_size=5,
        )

        self.assertEqual(result["sample_size"], 6)
        self.assertGreater(result["probabilities"][20], 0.0)
        self.assertGreater(result["probabilities"][21], 0.0)
        self.assertAlmostEqual(result["update_rate"], 4 / 6)
        self.assertEqual(result["median_first_update_minute"], 15 * 60)
        self.assertGreater(result["skip_rate"], 0.0)

    def test_transition_prior_blends_into_distribution(self):
        model = TorontoHighTempModel(target_date="2026-05-28")
        model.calibrated_weights = None
        model.probability_calibration = None
        model.predict_feature_distribution = lambda sources, cutoff_hour, now: (
            {20: 0.05, 21: 0.95},
            "hgb",
        )
        model.bucket_transition_model = lambda sources, now, min_sample_size=20: {
            "observed_bucket": 20,
            "current_max_bucket": 20,
            "cutoff_hour": 12,
            "sample_size": 100,
            "counts": {20: 90, 21: 10},
            "probabilities": {20: 0.90, 21: 0.10},
            "skip_rate": 0.0,
            "update_rate": 0.10,
            "median_first_update_minute": 14 * 60,
        }
        sources = {
            "local_history": {
                "ok": True,
                "data": {
                    "available": True,
                    "analysis": {
                        "target_window_count": 100,
                        "bucket_probabilities": {"20": 0.10, "21": 0.90},
                    },
                },
            },
            "wu_history": {"ok": True, "data": {"max_c": 20.0, "rows": [_row(12 * 60, 20.0)]}},
            "wu_current": {"ok": True, "data": {"temp_c": 20.0, "max_since_7am_c": 20.0}},
            "eccc_swob": {"ok": True, "data": {}},
            "eccc_citypage": {"ok": True, "data": {}},
            "metar": {"ok": True, "data": {}},
            "weather_forecast": {"ok": True, "data": {"rows": []}},
            "open_meteo": {"ok": True, "data": {"rows": []}},
        }

        distribution = model.estimate_distribution(sources, now=datetime(2026, 5, 28, 12, 30))
        components = model._last_distribution_components["components"]

        self.assertIn("bucket_transition_model", components)
        self.assertIn("bucket_transition_blend", components)
        self.assertGreater(
            components["bucket_transition_blend"][20],
            components["feature_blend"][20],
        )
        self.assertGreater(distribution[20], 0.0)


if __name__ == "__main__":
    unittest.main()
