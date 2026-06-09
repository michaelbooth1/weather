import csv
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.abspath("src"))

from toronto_model import TORONTO_TZ, TorontoHighTempModel
from replay import (
    as_int_distribution,
    band_model_probability,
    distribution_l1,
    load_replay_records,
    parse_built_at,
    reconstruct_corpus_for_folder,
    reconstruct_sources,
    record_target_date,
    replay_distribution,
)
from replay_backtest import gate, run_replay_backtest, save_baseline

NOW = datetime(2026, 6, 3, 14, 30, tzinfo=TORONTO_TZ)
SLUG = "highest-temperature-in-toronto-on-june-3-2026"


def make_sources():
    """A realistic merged sources dict (the shape estimate_distribution consumes)."""
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


class TestReplayHelpers(unittest.TestCase):
    def test_as_int_distribution_coerces_string_keys(self):
        # JSON round-trips int keys to strings; replay must compare them equal.
        self.assertEqual(as_int_distribution({"24": 0.5, "25": 0.5}), {24: 0.5, 25: 0.5})

    def test_distribution_l1_zero_for_identical(self):
        self.assertEqual(distribution_l1({24: 0.5, 25: 0.5}, {"24": 0.5, "25": 0.5}), 0.0)

    def test_distribution_l1_measures_difference(self):
        self.assertAlmostEqual(distribution_l1({25: 1.0}, {25: 0.6, 26: 0.4}), 0.8)

    def test_parse_built_at_reads_built_at(self):
        parsed = parse_built_at({"built_at": NOW.isoformat()})
        self.assertEqual(parsed.hour, 14)
        self.assertIsNotNone(parsed.tzinfo)

    def test_record_target_date_from_slug(self):
        self.assertEqual(record_target_date({"event_slug": SLUG}).isoformat(), "2026-06-03")


class TestReplayRoundTrip(unittest.TestCase):
    """The corpus must replay byte-faithfully: persisting sources to JSON and
    re-running with the same code reproduces the original distribution exactly."""

    def setUp(self):
        self.model = TorontoHighTempModel(target_date=NOW.date())

    def test_json_roundtrip_reproduces_distribution(self):
        sources = make_sources()
        dist1 = self.model.estimate_distribution(sources, now=NOW)
        self.assertTrue(dist1, "expected a non-empty distribution")

        # Persist exactly as the corpus does (json with default=str), reload, replay.
        persisted = json.loads(json.dumps(sources, sort_keys=True, default=str))
        record = {
            "event_slug": SLUG,
            "target_date": "2026-06-03",
            "built_at": NOW.isoformat(),
            "sources": persisted,
        }
        dist2 = replay_distribution(self.model, record)
        self.assertLess(distribution_l1(dist1, dist2), 1e-9)

    def test_band_probabilities_are_valid(self):
        dist = self.model.estimate_distribution(make_sources(), now=NOW)
        p_all = band_model_probability(self.model, dist, {"bin_kind": "lte", "bin_value_c": 40})
        self.assertGreater(p_all, 0.98)
        p_none = band_model_probability(self.model, dist, {"bin_kind": "gte", "bin_value_c": 40})
        self.assertLess(p_none, 0.02)


def _build_corpus_day(folder):
    """Write a one-snapshot tape + replay corpus where the recorded model
    probabilities were produced by the current code (so replay must reproduce
    them: code effect 0, fidelity 0)."""
    model = TorontoHighTempModel(target_date=NOW.date())
    sources = make_sources()
    dist = model.estimate_distribution(sources, now=NOW)
    version = model.get_model_version_string()

    bands = [
        {"range_label": "24 C or below", "bin_kind": "lte", "bin_value_c": 24, "market_yes": 0.10},
        {"range_label": "25 C", "bin_kind": "eq", "bin_value_c": 25, "market_yes": 0.55},
        {"range_label": "27 C or higher", "bin_kind": "gte", "bin_value_c": 27, "market_yes": 0.05},
    ]
    long_rows = []
    for band in bands:
        recorded_p = band_model_probability(model, dist, band)
        long_rows.append({
            "snapshot_id": "snap1",
            "captured_at_local": NOW.isoformat(),
            "event_slug": SLUG,
            "model_version": version,
            "range_label": band["range_label"],
            "bin_kind": band["bin_kind"],
            "bin_value_c": band["bin_value_c"],
            "model_probability": recorded_p,
            "market_yes": band["market_yes"],
            "market_no": 1.0 - band["market_yes"],
            "wu_history_high_c": 24.0,
        })

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    columns = list(long_rows[0].keys())
    with (folder / "snapshots_long.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(long_rows)

    record = {
        "schema_version": "toronto_replay_inputs_v0.1",
        "snapshot_id": "snap1",
        "captured_at_local": NOW.isoformat(),
        "event_slug": SLUG,
        "target_date": "2026-06-03",
        "model_version": version,
        "built_at": NOW.isoformat(),
        "recorded_distribution": dist,
        "sources": sources,
    }
    with (folder / "replay_inputs.jsonl").open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
    return version


class TestReplayBacktest(unittest.TestCase):
    def test_unchanged_code_has_zero_effect_and_faithful_fidelity(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / SLUG
            _build_corpus_day(folder)
            results = run_replay_backtest(
                [str(folder)],
                daily_summary_path=str(Path(tmp) / "missing.csv"),
                overrides={"2026-06-03": 25},  # settle so outcomes resolve
                out_path=str(Path(tmp) / "replay_report.md"),
                write=True,
            )

        self.assertEqual(results["snaps_scored"], 1)
        self.assertEqual(results["total_rows"], 3)

        fidelity = results["fidelity"]
        self.assertEqual(fidelity["same_version_n"], 1)
        self.assertTrue(fidelity["same_version_faithful"])
        self.assertLess(fidelity["same_version_mean_l1"], 1e-9)

        aggregate = results["aggregate"]
        # Recorded probs were produced by this code, so replay reproduces them.
        self.assertAlmostEqual(aggregate["code_effect"], 0.0, places=9)
        self.assertAlmostEqual(aggregate["replayed_brier"], aggregate["recorded_brier"], places=9)

    def test_report_file_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / SLUG
            _build_corpus_day(folder)
            out = Path(tmp) / "replay_report.md"
            run_replay_backtest(
                [str(folder)], str(Path(tmp) / "missing.csv"),
                {"2026-06-03": 25}, str(out), write=True,
            )
            self.assertTrue(out.exists())
            text = out.read_text(encoding="utf-8")
            self.assertIn("Replay Fidelity Canary", text)
            self.assertIn("Code Effect", text)


class TestReconstruction(unittest.TestCase):
    def _snapshot(self):
        return {
            "snapshot_id": "snapA",
            "captured_at_utc": "2026-06-03T18:30:00+00:00",
            "captured_at_local": "2026-06-03T14:30:00-04:00",
            "event_slug": SLUG,
            "model_version": "toronto_hgb_vX",
            "distribution": {"24": 0.3, "25": 0.5, "26": 0.2},
            "source_values": {
                "wu_history_high_c": 24.0, "wu_current_c": 22.0,
                "wu_max_since_7am_c": 24.0, "eccc_swob_max_c": 24.2,
                "weather_forecast_max_c": 25.0, "open_meteo_max_c": 25.5,
                "eccc_forecast_high_c": 26.0,
            },
            "feature_vector": {
                "cutoff_hour": 14, "high_so_far": 24.0, "current_temp": 22.0,
                "rise_from_7am": 8.0, "dewpoint_c": 10.0, "humidity": 55,
                "pressure": 1015.0, "pressure_trend_3h": -1.5, "wind_speed_kmh": 20.0,
                "forecast_high": 26.0, "forecast_gap": 2.0,
                "wind_group": "S-SW", "cloud_group": "Fair/clear",
            },
        }

    def test_reconstructed_sources_reproduce_feature_vector(self):
        snap = self._snapshot()
        model = TorontoHighTempModel(target_date=NOW.date())
        sources = reconstruct_sources(snap, NOW.date())
        feats = model.extract_live_features(sources, 14)

        self.assertEqual(feats["high_so_far"], 24.0)
        self.assertEqual(feats["current_temp"], 22.0)
        self.assertAlmostEqual(feats["rise_from_7am"], 8.0)
        self.assertEqual(feats["dewpoint_c"], 10.0)
        self.assertEqual(feats["humidity"], 55)
        self.assertEqual(feats["pressure"], 1015.0)
        self.assertAlmostEqual(feats["pressure_trend_3h"], -1.5)
        self.assertEqual(feats["wind_speed_kmh"], 20.0)
        self.assertEqual(feats["wind_group"], "S-SW")
        self.assertEqual(feats["cloud_group"], "Fair/clear")
        self.assertEqual(feats["forecast_high"], 26.0)
        self.assertAlmostEqual(feats["forecast_gap"], 2.0)

    def test_reconstruction_uses_snapshot_market(self):
        # An Austin snapshot must reconstruct with the Austin model (its own
        # climatology/data root), not Toronto's.
        import toronto_model as tm

        captured = {}
        real_model = tm.TorontoHighTempModel

        class RecordingModel(real_model):
            def __init__(self, *args, **kwargs):
                captured["market_id"] = kwargs.get("market_id")
                super().__init__(*args, **kwargs)

        snap = self._snapshot()
        snap["event_slug"] = "highest-temperature-in-austin-on-june-3-2026"
        tm.TorontoHighTempModel = RecordingModel
        try:
            reconstruct_sources(snap, NOW.date())
        finally:
            tm.TorontoHighTempModel = real_model

        self.assertEqual(captured["market_id"], "austin")

    def test_reconstruct_corpus_writes_labelled_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / SLUG
            folder.mkdir(parents=True)
            with (folder / "snapshots.jsonl").open("w", encoding="utf-8") as handle:
                handle.write(json.dumps(self._snapshot(), sort_keys=True) + "\n")

            added, skipped = reconstruct_corpus_for_folder(folder)
            self.assertEqual(added, 1)
            self.assertEqual(skipped, 0)

            records = load_replay_records(folder)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["source"], "reconstructed")

            # A reconstructed record replays to a non-empty distribution.
            model = TorontoHighTempModel(target_date=NOW.date())
            dist = replay_distribution(model, records[0])
            self.assertTrue(dist)

            # Re-running does not duplicate an already-present snapshot.
            added2, skipped2 = reconstruct_corpus_for_folder(folder)
            self.assertEqual(added2, 0)
            self.assertEqual(skipped2, 1)


class TestRegressionGate(unittest.TestCase):
    def test_gate_passes_within_tolerance_and_fails_on_regression(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline_path = Path(tmp) / "baseline.json"
            base_results = {
                "aggregate": {"replayed_brier": 0.1000, "market_brier": 0.12},
                "daily_first": {"replayed_brier": 0.1000},
                "replayed_versions": ["v1"], "snaps_scored": 10,
            }
            save_baseline(baseline_path, base_results)

            improved = {"aggregate": {"replayed_brier": 0.0980}}
            passed, message = gate(baseline_path, improved, tol=0.003)
            self.assertTrue(passed, message)

            regressed = {"aggregate": {"replayed_brier": 0.1100}}
            passed, message = gate(baseline_path, regressed, tol=0.003)
            self.assertFalse(passed, message)


if __name__ == "__main__":
    unittest.main()
