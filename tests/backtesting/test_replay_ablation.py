import csv
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from weather.market.market_registry import REGISTRY
from weather.backtesting.replay import (
    band_model_probability,
    canonical_replay_record_sha256,
)
from weather.backtesting.replay_ablation import (
    ablate_sources,
    add_robustness_to_existing_artifact,
    build_payload,
    paired_inference_sensitivities,
    resolve_outputs_outside_read_only_root,
    run_ablation,
    paired_day_inference,
    paired_market_inference,
    summarize,
    summarize_slice_effects,
    variant_names_for_spec,
)
from weather.model.toronto_model import TORONTO_TZ, TorontoHighTempModel

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

    def test_us_markets_get_broader_source_family_variants(self):
        nyc = variant_names_for_spec(
            REGISTRY["nyc"],
            ["official_us_guidance", "multi_model_guidance", "marine_context", "mrms_precip"],
        )

        self.assertEqual(nyc["official_us_guidance"], ("nws_hourly", "nws_grid", "nbm_probabilistic_tmax"))
        self.assertEqual(
            nyc["multi_model_guidance"],
            ("open_meteo_multimodel", "open_meteo_global_models", "global_ensemble"),
        )
        self.assertEqual(nyc["marine_context"], ("marine_context",))
        self.assertEqual(nyc["mrms_precip"], ("mrms_precip",))


class TestRobustnessScopes(unittest.TestCase):
    def test_settlement_and_complete_panel_scopes_are_defined_before_outcomes(self):
        day_meta = []
        day_tables = {"open_meteo": [], "official_us_guidance": []}
        for target_date in ("2026-06-01", "2026-06-02"):
            for index in range(12):
                day = f"market-{index:02d} {target_date}"
                source = "daily_summary"
                if target_date == "2026-06-02" and index == 11:
                    source = "snapshot_high"
                day_meta.append({"day": day, "settlement_source": source})
                day_tables["open_meteo"].append(
                    {
                        "day": day,
                        "brier_delta": -0.01,
                        "logloss_delta": -0.02,
                    }
                )
                if index < 11:
                    day_tables["official_us_guidance"].append(
                        {
                            "day": day,
                            "brier_delta": -0.01,
                            "logloss_delta": -0.02,
                        }
                    )

        required_markets = {f"market-{index:02d}" for index in range(12)}
        rows = paired_inference_sensitivities(
            day_tables,
            day_meta,
            required_market_ids=required_markets,
        )
        by_scope = {
            row["scope"]: row
            for row in rows
            if row["variant"] == "open_meteo" and row["split"] == "all"
        }
        self.assertEqual(by_scope["all_pinned"]["market_days"], 24)
        self.assertEqual(by_scope["configured_daily_summary_only"]["market_days"], 23)
        self.assertEqual(by_scope["complete_12_market_panel"]["fleet_dates"], 2)
        self.assertEqual(
            by_scope["daily_summary_complete_exact_market_panel"]["market_days"],
            12,
        )
        official_complete = next(
            row
            for row in rows
            if row["variant"] == "official_us_guidance"
            and row["split"] == "all"
            and row["scope"] == "complete_12_market_panel"
        )
        self.assertEqual(official_complete["fleet_dates"], 0)
        self.assertEqual(official_complete["market_days"], 0)
        by_market = paired_market_inference(
            day_tables,
            {"holdout": ["2026-06-02"]},
        )
        open_meteo_holdout = [
            row
            for row in by_market
            if row["variant"] == "open_meteo" and row["split"] == "holdout"
        ]
        self.assertEqual(len(open_meteo_holdout), 12)
        self.assertTrue(
            all(row["market_days"] == 1 for row in open_meteo_holdout)
        )

        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            data_root.mkdir()
            artifact = Path(tmp) / "ablation.json"
            artifact.write_text(
                json.dumps(
                    {
                        "day_effects": day_tables,
                        "market_days": day_meta,
                        "include_reconstructed": False,
                    }
                ),
                encoding="utf-8",
            )
            augmented = add_robustness_to_existing_artifact(
                artifact,
                read_only_data_root=data_root,
                split_dates={
                    "tune": ["2026-06-01"],
                    "holdout": ["2026-06-02"],
                },
            )
            self.assertEqual(len(augmented["robustness_inference"]), 24)
            self.assertTrue(
                augmented["robustness_contract"][
                    "outcome_independent_scope_selection"
                ]
            )
            self.assertTrue(augmented["market_inference"])

            with self.assertRaisesRegex(ValueError, "must not alias"):
                add_robustness_to_existing_artifact(
                    artifact,
                    read_only_data_root=data_root,
                    report_path=artifact,
                    split_dates={
                        "tune": ["2026-06-01"],
                        "holdout": ["2026-06-02"],
                    },
                )

            forbidden = data_root / "ablation.json"
            forbidden.write_text(artifact.read_text(encoding="utf-8"), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "read-only data root"):
                add_robustness_to_existing_artifact(
                    forbidden,
                    read_only_data_root=data_root,
                    split_dates={
                        "tune": ["2026-06-01"],
                        "holdout": ["2026-06-02"],
                    },
                )

    def test_supplied_read_only_root_rejects_direct_and_aliased_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_root = root / "data"
            data_root.mkdir()
            with self.assertRaisesRegex(ValueError, "read-only data root"):
                resolve_outputs_outside_read_only_root(
                    data_root,
                    {"json_out": data_root / "report.json"},
                )
            alias = root / "alias"
            try:
                alias.symlink_to(data_root, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlinks unavailable: {exc}")
            with self.assertRaisesRegex(ValueError, "read-only data root"):
                resolve_outputs_outside_read_only_root(
                    data_root,
                    {"json_out": alias / "report.json"},
                )


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
            self.assertEqual(summary["market_days"], 1)
            self.assertIn("toronto", summary["by_family"])
            self.assertIn("logloss_delta", summary)
        self.assertIn("all_forecasts", day_tables)
        self.assertIn("logloss_delta", day_tables["all_forecasts"][0])
        inference = paired_day_inference(
            day_tables,
            {"tune": ["2026-06-03"], "holdout": ["2026-06-04"]},
        )
        tune = next(
            row for row in inference
            if row["variant"] == "all_forecasts" and row["split"] == "tune"
        )
        self.assertEqual(tune["fleet_dates"], 1)
        self.assertEqual(tune["brier_delta"]["cluster_bootstrap_95ci"]["replicates"], 10_000)
        self.assertEqual(tune["brier_delta"]["sign_test"]["non_ties"], 1)

        slices = summarize_slice_effects(data)
        payload = build_payload(summaries, day_tables, day_meta, ["open_meteo", "all_forecasts"], False, slices)
        self.assertEqual(payload["schema_version"], "source_family_ablation_v0.2")
        self.assertEqual(payload["summary"]["variant_count"], 2)
        self.assertGreater(payload["summary"]["slice_effect_count"], 0)
        self.assertIn("variants", payload)
        self.assertTrue(any(row["slice"] == "market_cutoff_regime" for row in payload["slice_effects"]))
        self.assertEqual(
            next(row for row in payload["variants"] if row["variant"] == "all_forecasts")["ablated_sources"],
            ["open_meteo", "weather_forecast", "eccc_citypage"],
        )

    def test_model_binding_audit_keyword_is_accepted_by_non_hardened_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / SLUG
            self._build_day(folder)
            audit = {}
            run_ablation(
                [str(folder)],
                ["open_meteo"],
                model_binding_audit=audit,
            )

        self.assertEqual(audit, {})

    def test_pinned_corpus_filters_rows_and_uses_pinned_settlement(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / SLUG
            self._build_day(folder)
            tape_path = folder / "snapshots_long.csv"
            with tape_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            with tape_path.open("a", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writerows([{**row, "snapshot_id": "snap2"} for row in rows])
            replay_path = folder / "replay_inputs.jsonl"
            record = json.loads(replay_path.read_text(encoding="utf-8").splitlines()[0])
            with replay_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({**record, "snapshot_id": "snap2"}, sort_keys=True) + "\n")
            manifest = {
                "entries": [{
                    "event_slug": SLUG,
                    "snapshot_ids": ["snap1"],
                    "tape_row_hashes": {},
                    "replay_record_hashes": {
                        "snap1": canonical_replay_record_sha256(record)
                    },
                    "settlement_bucket": 25,
                    "settlement_source": "fixture",
                }]
            }

            data, day_meta = run_ablation(
                [str(folder)],
                ["open_meteo", "all_forecasts"],
                corpus_manifest=manifest,
            )

        self.assertEqual(len(data), 6)
        self.assertEqual(day_meta[0]["snapshots"], 1)
        self.assertEqual(day_meta[0]["settlement"], 25)
        self.assertEqual(day_meta[0]["settlement_source"], "fixture")
        self.assertEqual(day_meta[0]["settlement_binding"], "promotion_corpus")

    def test_pinned_corpus_fails_before_model_construction_on_missing_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / SLUG
            self._build_day(folder)
            manifest = {
                "entries": [{
                    "event_slug": SLUG,
                    "snapshot_ids": ["missing-snapshot"],
                    "tape_row_hashes": {},
                    "replay_record_hashes": {"missing-snapshot": "0" * 64},
                    "settlement_bucket": 25,
                }]
            }
            created = []

            with self.assertRaisesRegex(ValueError, "input verification failed"):
                run_ablation(
                    [str(folder)],
                    ["open_meteo"],
                    corpus_manifest=manifest,
                    model_factory=lambda market_id: created.append(market_id),
                )

        self.assertEqual(created, [])


if __name__ == "__main__":
    unittest.main()
