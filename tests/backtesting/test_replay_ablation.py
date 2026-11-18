import csv
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from weather.backtesting import replay_ablation
from weather.market.market_registry import REGISTRY
from weather.backtesting.replay import band_model_probability
from weather.backtesting.replay_ablation import (
    ablate_sources,
    build_payload,
    run_ablation,
    settlement_distance_bucket,
    summarize,
    summarize_slice_effects,
    variant_names_for_spec,
)
from weather.model.toronto_model import TORONTO_TZ, TorontoHighTempModel

NOW = datetime(2026, 6, 3, 14, 30, tzinfo=TORONTO_TZ)
SLUG = "highest-temperature-in-toronto-on-june-3-2026"


@pytest.mark.parametrize(("band", "settled", "expected"), [
    ({"bin_kind": "eq", "bin_value_c": 90, "range_label": "90–91°F"}, 91, "exact"),
    ({"bin_kind": "eq", "bin_value": -2, "bin_value_hi": 0}, 0, "exact"),
    ({"bin_kind": "eq", "bin_value_c": -5, "bin_value_hi_c": "nan", "range_label": "-5--4 C"}, -3, "adjacent"),
    ({"bin_kind": "eq", "bin_value_c": 0}, 2, "far"),
    ({"bin_kind": "lte", "bin_value": 0}, -10, "exact"),
    ({"bin_kind": "lte", "bin_value": 0}, 1, "adjacent"),
    ({"range_label": "0°C or higher"}, 5, "exact"),
    ({"range_label": "0°C or higher"}, -2, "far"),
    ({"bin_kind": "eq", "bin_value": 90, "bin_value_hi": 89}, 90, "unknown"),
    ({"range_label": "5°C"}, None, "unknown"),
    ({"range_label": "5°C"}, 5.5, "unknown"),
])
def test_native_ablation_distance(band, settled, expected):
    assert settlement_distance_bucket(band, settled) == expected


def test_ablation_labels_and_distance_use_the_same_native_band(tmp_path, monkeypatch):
    # All evidence is synthetic. Model I/O, replay inputs and settlement files are isolated.
    folder = tmp_path / "highest-temperature-in-nyc-on-june-3-2026"
    folder.mkdir()
    (folder / "snapshots_long.csv").write_text(
        "snapshot_id,bin_kind,bin_value,bin_value_hi,range_label\n"
        "s1,eq,90,91,90 F\n"       # old single-end display label and explicit high
        "s1,eq,92,,92-93F\n"      # legacy upper endpoint from label
        "s1,lte,88,,88F or below\n"
        "s1,eq,92,90,92 F\n",     # contradictory range is unscored
        encoding="utf-8",
    )
    record = {"snapshot_id": "s1", "sources": {"open_meteo": {"ok": True, "data": {}}}}
    monkeypatch.setattr(replay_ablation, "load_replay_records", lambda _: [record])
    monkeypatch.setattr(replay_ablation, "load_daily_summary", lambda _: {})
    monkeypatch.setattr(replay_ablation, "settlement_for_tape", lambda *args: (91, "synthetic", ""))
    model = Mock()
    model.bin_probability.return_value = 0.25
    monkeypatch.setattr(replay_ablation, "TorontoHighTempModel", lambda **_: model)
    monkeypatch.setattr(replay_ablation, "replay_distribution", lambda *args: {91: 1.0})
    data, _ = run_ablation([folder], ["open_meteo"])
    assert list(zip(data["settlement_distance"], data["y"])) == [("exact", 1), ("adjacent", 0), ("far", 0)]


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

    def test_us_markets_get_broader_source_family_variants(self):
        nyc = variant_names_for_spec(
            REGISTRY["nyc"],
            ["official_us_guidance", "multi_model_guidance", "coastal_context", "precip_context"],
        )

        self.assertEqual(nyc["official_us_guidance"], ("nws_hourly", "nws_grid", "nbm_probabilistic_tmax"))
        self.assertEqual(
            nyc["multi_model_guidance"],
            ("open_meteo_multimodel", "open_meteo_global_models", "global_ensemble"),
        )
        self.assertEqual(nyc["coastal_context"], ("marine_context",))
        self.assertEqual(nyc["precip_context"], ("mrms_precip",))


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

        slices = summarize_slice_effects(data)
        payload = build_payload(summaries, day_tables, day_meta, ["open_meteo", "all_forecasts"], False, slices)
        self.assertEqual(payload["schema_version"], "source_family_ablation_v0.1")
        self.assertEqual(payload["summary"]["variant_count"], 2)
        self.assertGreater(payload["summary"]["slice_effect_count"], 0)
        self.assertIn("variants", payload)
        self.assertTrue(any(row["slice"] == "market_cutoff_regime" for row in payload["slice_effects"]))
        self.assertEqual(
            next(row for row in payload["variants"] if row["variant"] == "all_forecasts")["ablated_sources"],
            ["open_meteo", "weather_forecast", "eccc_citypage"],
        )


if __name__ == "__main__":
    unittest.main()
