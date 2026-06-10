import csv
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.abspath("src"))

from market_registry import REGISTRY
from replay import band_model_probability
from replay_ablation import ablate_sources, run_ablation, summarize, variant_names_for_spec
from toronto_model import TORONTO_TZ, TorontoHighTempModel

NOW = datetime(2026, 6, 3, 14, 30, tzinfo=TORONTO_TZ)
SLUG = "highest-temperature-in-toronto-on-june-3-2026"


def make_sources():
    return {
        "local_history": {"ok": False, "data": {}},
        "wu_history": {"ok": True, "stale": False, "data": {
            "max_c": 24.0,
            "max_times": ["14:00"],
            "rows": [
                {"time": "07:00", "temp_c": 16.0, "dewpoint_c": 10.0, "humidity": 60,
                 "pressure": 1016.0, "wind": "SW", "wind_kmh": 10, "condition": "Fair"},
                {"time": "11:00", "temp_c": 22.0, "dewpoint_c": 11.0, "humidity": 50,
                 "pressure": 1015.0, "wind": "SW", "wind_kmh": 15, "condition": "Fair"},
                {"time": "14:00", "temp_c": 24.0, "dewpoint_c": 11.0, "humidity": 45,
                 "pressure": 1014.0, "wind": "SW", "wind_kmh": 18, "condition": "Fair"},
            ],
            "latest": {"time": "14:00", "temp_c": 24.0},
        }},
        "wu_current": {"ok": True, "stale": False, "data": {
            "temp_c": 23.0, "max_since_7am_c": 24.0, "dewpoint_c": 11.0,
            "humidity": 45, "target_date_match": True, "wind": "SW", "condition": "Fair",
        }},
        "eccc_swob": {"ok": True, "stale": False, "data": {"same_day_max_c": 24.2, "rows": []}},
        "eccc_citypage": {"ok": True, "stale": False, "data": {"forecast_high_c": 26.0}},
        "weather_forecast": {"ok": True, "stale": False, "data": {
            "rows": [{"temp_c": 25.0, "time": "15:00"}]}},
        "open_meteo": {"ok": True, "stale": False, "data": {
            "rows": [{"temp_c": 25.5, "time": "15:00"}], "day_max_c": 26.0}},
        "metar": {"ok": True, "stale": False, "data": {"temp_c": 23.0, "target_date_match": True}},
    }


class TestAblateSources(unittest.TestCase):
    def test_marks_source_failed_without_mutating_original(self):
        sources = make_sources()
        ablated = ablate_sources(sources, ("open_meteo",))
        self.assertFalse(ablated["open_meteo"]["ok"])
        self.assertEqual(ablated["open_meteo"]["data"], {})
        self.assertTrue(sources["open_meteo"]["ok"])          # original untouched
        self.assertIs(ablated["wu_history"], sources["wu_history"])  # others shared

    def test_missing_source_is_ignored(self):
        ablated = ablate_sources({"wu_history": {"ok": True, "data": {}}}, ("eccc_swob",))
        self.assertNotIn("eccc_swob", ablated)


class TestVariantSelection(unittest.TestCase):
    def test_toronto_gets_swob_and_citypage_nyc_does_not(self):
        toronto = variant_names_for_spec(
            REGISTRY["toronto"], ["eccc_swob", "eccc_citypage", "open_meteo", "all_forecasts"]
        )
        nyc = variant_names_for_spec(
            REGISTRY["nyc"], ["eccc_swob", "eccc_citypage", "open_meteo", "all_forecasts"]
        )
        self.assertIn("eccc_swob", toronto)
        self.assertNotIn("eccc_swob", nyc)
        self.assertNotIn("eccc_citypage", nyc)
        self.assertIn("open_meteo", nyc)
        # The combined variant survives for NYC because it includes sources NYC has.
        self.assertIn("all_forecasts", nyc)
        self.assertEqual(toronto["all_forecasts"],
                         ("open_meteo", "weather_forecast", "eccc_citypage"))


class TestRunAblationEndToEnd(unittest.TestCase):
    def _build_day(self, folder):
        model = TorontoHighTempModel(target_date=NOW.date())
        sources = make_sources()
        dist = model.estimate_distribution(sources, now=NOW)
        bands = [
            {"range_label": "24 C or below", "bin_kind": "lte", "bin_value_c": 24, "market_yes": 0.10},
            {"range_label": "25 C", "bin_kind": "eq", "bin_value_c": 25, "market_yes": 0.55},
            {"range_label": "27 C or higher", "bin_kind": "gte", "bin_value_c": 27, "market_yes": 0.05},
        ]
        long_rows = []
        for band in bands:
            long_rows.append({
                "snapshot_id": "snap1",
                "captured_at_local": NOW.isoformat(),
                "event_slug": SLUG,
                "range_label": band["range_label"],
                "bin_kind": band["bin_kind"],
                "bin_value_c": band["bin_value_c"],
                "model_probability": band_model_probability(model, dist, band),
                "market_yes": band["market_yes"],
                "wu_history_high_c": 24.0,
            })
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "snapshots_long.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(long_rows[0].keys()))
            writer.writeheader()
            writer.writerows(long_rows)
        record = {
            "snapshot_id": "snap1",
            "captured_at_local": NOW.isoformat(),
            "event_slug": SLUG,
            "target_date": "2026-06-03",
            "built_at": NOW.isoformat(),
            "sources": sources,
        }
        with (folder / "replay_inputs.jsonl").open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")

    def test_scores_baseline_and_variants(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / SLUG
            self._build_day(folder)
            data, day_meta = run_ablation(
                [str(folder)], ["open_meteo", "all_forecasts"]
            )

        self.assertEqual(len(day_meta), 1)
        self.assertEqual(sorted(data["variant"].unique()), ["all_forecasts", "open_meteo"])
        self.assertEqual(len(data), 6)  # 3 bands x 2 variants
        self.assertTrue(((data["y"] == 0) | (data["y"] == 1)).all())
        # Dropping ALL forecasts must move the distribution: the variant
        # probabilities cannot all equal baseline.
        combined = data[data["variant"] == "all_forecasts"]
        self.assertGreater((combined["variant_p"] - combined["base_p"]).abs().max(), 1e-6)

        summaries, day_tables = summarize(data)
        self.assertEqual(len(summaries), 2)
        for summary in summaries:
            self.assertEqual(summary["days"], 1)
            self.assertIn("toronto", summary["by_family"])
        self.assertIn("all_forecasts", day_tables)


if __name__ == "__main__":
    unittest.main()
