import csv
import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from unittest import mock
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from weather.market.market_registry import REGISTRY
from weather.backtesting.replay import (
    band_model_probability,
    canonical_replay_record_sha256,
)
from weather.backtesting.replay_ablation import (
    DEFAULT_OUT,
    DEFAULT_JSON_OUT,
    DEFAULT_RESEARCH_JSON_OUT,
    _load_manifest_with_receipt,
    _stable_file_identity,
    ablate_sources,
    add_robustness_to_existing_artifact,
    build_payload,
    paired_inference_sensitivities,
    resolve_outputs_outside_read_only_root,
    run_ablation,
    paired_day_inference,
    paired_market_inference,
    resolve_evidence_output_paths,
    summarize,
    summarize_slice_effects,
    validate_operational_cli_args,
    variant_names_for_spec,
)
from weather.backtesting.source_ablation_contract import ALL_VARIANTS
from weather.backtesting.source_ablation_evidence import (
    applicable_market_ids_for_variant,
)
from weather.model.toronto_model import TORONTO_TZ, TorontoHighTempModel
from weather.reporting.promotion.promotion_corpus import corpus_hash
from weather.reporting.source_gates.source_family_contracts import (
    source_ablation_operational_contract,
)

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


def operational_build_case():
    dates = ["2026-06-01", "2026-06-02"]
    market_ids = sorted(REGISTRY)
    market_day_count = len(market_ids) * len(dates)
    summaries = []
    day_tables = {}
    for variant in ALL_VARIANTS:
        applicable_markets = applicable_market_ids_for_variant(variant)
        if not applicable_markets:
            raise AssertionError(
                f"canonical operational test variant has no market: {variant}"
            )
        market_id = applicable_markets[0]
        summaries.append(
            {
            "variant": variant,
            "n": market_day_count * 10,
            "market_days": 2,
            "base_brier": 0.20,
            "variant_brier": 0.21,
            "delta": 0.01,
            "base_logloss": 0.50,
            "variant_logloss": 0.52,
            "logloss_delta": 0.02,
            "market_days_source_helped": 2,
            "market_days_source_hurt": 0,
            "by_family": {"us_f": 0.01},
            }
        )
        day_tables[variant] = [
            {
                "market_day": f"{market_id} {target_date}",
                "n": market_day_count * 5,
                "base_brier": 0.20,
                "variant_brier": 0.21,
                "delta": 0.01,
                "brier_delta": 0.01,
                "base_logloss": 0.50,
                "variant_logloss": 0.52,
                "logloss_delta": 0.02,
            }
            for target_date in dates
        ]
    day_meta = [
        {
            "market_day": f"{market_id} {target_date}",
            "settlement_source": "daily_summary",
        }
        for market_id in market_ids
        for target_date in dates
    ]
    split_dates = {"tune": [dates[0]], "holdout": [dates[1]]}
    entries = [
        {
            "event_slug": f"{market_id}-{target_date}",
            "market_id": market_id,
            "target_date": target_date,
            "settlement_source": "daily_summary",
        }
        for market_id in market_ids
        for target_date in dates
    ]
    corpus_path = "C:/synthetic/promotion_corpus.json"
    corpus_manifest = {
        "_path": corpus_path,
        "schema_version": "promotion_corpus_v0.2",
        "corpus_hash": corpus_hash(entries),
        "include_reconstructed": False,
        "allow_unsettled": False,
        "market_filter": None,
        "entries": entries,
        "summary": {
            "market_day_count": market_day_count,
            "snapshot_count": market_day_count * 10,
        },
    }
    paired = paired_day_inference(day_tables, split_dates)
    robustness = paired_inference_sensitivities(
        day_tables,
        day_meta,
        split_dates=split_dates,
        required_market_ids=tuple(sorted(REGISTRY)),
    )
    market_inference = paired_market_inference(
        day_tables,
        split_dates,
        day_meta=day_meta,
    )
    input_receipts = {
        "corpus": {
            "path": corpus_path,
            "status": "PASS",
            "sha256": "1" * 64,
            "size_bytes": 100,
            "blockers": [],
        },
        "tune_dates": {
            "path": "C:/synthetic/tune.txt",
            "status": "PASS",
            "sha256": "2" * 64,
            "size_bytes": 10,
            "blockers": [],
        },
        "holdout_dates": {
            "path": "C:/synthetic/holdout.txt",
            "status": "PASS",
            "sha256": "3" * 64,
            "size_bytes": 10,
            "blockers": [],
        },
    }
    model_binding = {
        "status": "BOUND",
        "binding_kind": "verified_active_release",
        "pointer_present": True,
        "base_model_bound": True,
        "release_id": "synthetic-release",
        "release_manifest_sha256": "4" * 64,
        "release_pointer_sha256": "5" * 64,
        "market_ids": market_ids,
        "model_count": len(market_ids),
        "shared_explicit_bundle": True,
        "shared_verified_bundle": True,
        "serving_or_release_authorization": True,
    }
    return {
        "summaries": summaries,
        "day_tables": day_tables,
        "day_meta": day_meta,
        "requested_sources": list(ALL_VARIANTS),
        "include_reconstructed": False,
        "slice_effects": [],
        "corpus_manifest": corpus_manifest,
        "paired_inference": paired,
        "robustness_inference": robustness,
        "market_inference": market_inference,
        "split_dates": split_dates,
        "model_binding": model_binding,
        "input_receipts": input_receipts,
        "evidence_mode": "operational",
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


class TestEvidenceModeCli(unittest.TestCase):
    def test_research_and_operational_defaults_do_not_share_json_path(self):
        _research_out, research_json = resolve_evidence_output_paths(
            operational_evidence=False
        )
        _operational_out, operational_json = resolve_evidence_output_paths(
            operational_evidence=True
        )

        self.assertEqual(research_json, DEFAULT_RESEARCH_JSON_OUT)
        self.assertEqual(operational_json, DEFAULT_JSON_OUT)
        self.assertNotEqual(research_json, operational_json)
        with self.assertRaisesRegex(ValueError, "--operational-evidence"):
            resolve_evidence_output_paths(
                operational_evidence=False,
                json_out=DEFAULT_JSON_OUT,
            )
        with self.assertRaisesRegex(ValueError, "--operational-evidence"):
            resolve_evidence_output_paths(
                operational_evidence=False,
                out=DEFAULT_OUT,
            )

    def test_operational_preflight_requires_full_corpus_and_forbids_subsets(self):
        with self.assertRaisesRegex(ValueError, "corpus"):
            validate_operational_cli_args(
                SimpleNamespace(
                    corpus=None,
                    tune_dates_file=None,
                    holdout_dates_file=None,
                    folders=[],
                    market=None,
                    include_reconstructed=False,
                )
            )
        with self.assertRaisesRegex(ValueError, "forbids folder/market subsets"):
            validate_operational_cli_args(
                SimpleNamespace(
                    corpus="corpus.json",
                    tune_dates_file="tune.txt",
                    holdout_dates_file="holdout.txt",
                    folders=["one-day"],
                    market=None,
                    include_reconstructed=False,
                )
            )
        with self.assertRaisesRegex(ValueError, "exact ordered 22-variant"):
            validate_operational_cli_args(
                SimpleNamespace(
                    corpus="corpus.json",
                    tune_dates_file="tune.txt",
                    holdout_dates_file="holdout.txt",
                    folders=[],
                    market=None,
                    include_reconstructed=False,
                ),
                requested_sources=["open_meteo"],
            )


class TestStableOperationalInputs(unittest.TestCase):
    def test_manifest_payload_and_receipt_share_one_physical_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "promotion_corpus.json"
            manifest = {
                "schema_version": "promotion_corpus_v0.2",
                "entries": [],
                "corpus_hash": corpus_hash([]),
            }
            path.write_text(json.dumps(manifest), encoding="utf-8")
            original_read_bytes = Path.read_bytes
            reads = []

            def counted_read(candidate):
                if candidate == path.resolve():
                    reads.append(str(candidate))
                return original_read_bytes(candidate)

            with mock.patch.object(Path, "read_bytes", counted_read):
                loaded, receipt = _load_manifest_with_receipt(path)

        self.assertEqual(reads, [str(path.resolve())])
        self.assertEqual(loaded["corpus_hash"], corpus_hash([]))
        self.assertEqual(receipt["status"], "PASS")

    def test_stable_identity_includes_device_and_inode(self):
        first = SimpleNamespace(
            st_dev=1,
            st_ino=10,
            st_size=100,
            st_mtime_ns=20,
            st_ctime_ns=30,
        )
        replacement = SimpleNamespace(
            st_dev=1,
            st_ino=11,
            st_size=100,
            st_mtime_ns=20,
            st_ctime_ns=30,
        )
        self.assertNotEqual(
            _stable_file_identity(first),
            _stable_file_identity(replacement),
        )


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
            original_bytes = artifact.read_bytes()
            expected_sha256 = hashlib.sha256(original_bytes).hexdigest()
            augmented_json = Path(tmp) / "augmented.json"
            augmented_report = Path(tmp) / "augmented.md"
            augmented = add_robustness_to_existing_artifact(
                artifact,
                read_only_data_root=data_root,
                expected_sha256=expected_sha256,
                output_json_path=augmented_json,
                report_path=augmented_report,
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
            self.assertEqual(artifact.read_bytes(), original_bytes)
            self.assertTrue(augmented_json.is_file())
            self.assertTrue(augmented_report.is_file())
            self.assertEqual(
                augmented["augmentation_input_receipt"]["sha256"],
                expected_sha256,
            )
            with self.assertRaisesRegex(ValueError, "refuses existing outputs"):
                add_robustness_to_existing_artifact(
                    artifact,
                    read_only_data_root=data_root,
                    expected_sha256=expected_sha256,
                    output_json_path=augmented_json,
                    report_path=augmented_report,
                    split_dates={
                        "tune": ["2026-06-01"],
                        "holdout": ["2026-06-02"],
                    },
                )

            with self.assertRaisesRegex(ValueError, "aliases a protected input"):
                add_robustness_to_existing_artifact(
                    artifact,
                    read_only_data_root=data_root,
                    expected_sha256=expected_sha256,
                    output_json_path=artifact,
                    report_path=Path(tmp) / "alias-report.md",
                    split_dates={
                        "tune": ["2026-06-01"],
                        "holdout": ["2026-06-02"],
                    },
                )

            forbidden = data_root / "ablation.json"
            with self.assertRaisesRegex(ValueError, "read-only data root"):
                add_robustness_to_existing_artifact(
                    artifact,
                    read_only_data_root=data_root,
                    expected_sha256=expected_sha256,
                    output_json_path=forbidden,
                    report_path=Path(tmp) / "forbidden-report.md",
                    split_dates={
                        "tune": ["2026-06-01"],
                        "holdout": ["2026-06-02"],
                    },
                )

    def test_robustness_augmentation_rejects_untrusted_or_non_strict_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_root = root / "data"
            data_root.mkdir()
            artifact = root / "ablation.json"
            split_dates = {"tune": ["2026-06-01"], "holdout": ["2026-06-02"]}

            for name, raw, message in (
                (
                    "duplicate",
                    b'{"day_effects": {}, "day_effects": {}, "market_days": []}',
                    "duplicate key",
                ),
                (
                    "overflow",
                    b'{"day_effects": {}, "market_days": [], "value": 1e999}',
                    "non-finite number",
                ),
            ):
                with self.subTest(name=name):
                    artifact.write_bytes(raw)
                    with self.assertRaisesRegex(ValueError, message):
                        add_robustness_to_existing_artifact(
                            artifact,
                            read_only_data_root=data_root,
                            expected_sha256=hashlib.sha256(raw).hexdigest(),
                            output_json_path=root / f"{name}.json",
                            report_path=root / f"{name}.md",
                            split_dates=split_dates,
                        )

            artifact.write_text(
                json.dumps({"day_effects": {}, "market_days": []}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "trusted receipt"):
                add_robustness_to_existing_artifact(
                    artifact,
                    read_only_data_root=data_root,
                    expected_sha256="0" * 64,
                    output_json_path=root / "mismatch.json",
                    report_path=root / "mismatch.md",
                    split_dates=split_dates,
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

    def test_output_guard_rejects_explicit_input_and_snapshot_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_root = root / "data"
            snapshots_root = root / "captured-snapshots"
            output_root = root / "output"
            data_root.mkdir()
            snapshots_root.mkdir()
            output_root.mkdir()
            corpus = output_root / "corpus.json"
            corpus.write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "protected input"):
                resolve_outputs_outside_read_only_root(
                    data_root,
                    {"json_out": corpus},
                    protected_inputs=(corpus,),
                )
            with self.assertRaisesRegex(ValueError, "protected read-only root"):
                resolve_outputs_outside_read_only_root(
                    data_root,
                    {"json_out": snapshots_root / "report.json"},
                    protected_roots=(snapshots_root,),
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
        self.assertEqual(payload["evidence_mode"], "research")
        self.assertTrue(payload["research_only"])
        self.assertFalse(payload["promotion_preflight_evidence_authorization"])
        self.assertEqual(payload["summary"]["variant_count"], 2)
        self.assertGreater(payload["summary"]["slice_effect_count"], 0)
        self.assertIn("variants", payload)
        self.assertTrue(any(row["slice"] == "market_cutoff_regime" for row in payload["slice_effects"]))
        self.assertEqual(
            next(row for row in payload["variants"] if row["variant"] == "all_forecasts")["ablated_sources"],
            ["open_meteo", "weather_forecast", "eccc_citypage"],
        )
        research_payload = build_payload(
            summaries,
            day_tables,
            day_meta,
            ["open_meteo", "all_forecasts"],
            False,
            slices,
            evidence_mode="research",
        )
        self.assertEqual(
            research_payload["schema_version"], "source_family_ablation_v0.2"
        )
        self.assertTrue(research_payload["research_only"])

    def test_operational_build_requires_all_authorization_inputs(self):
        case = operational_build_case()
        payload = build_payload(**case)
        self.assertEqual(payload["schema_version"], "source_family_ablation_v0.3")
        self.assertEqual(payload["evidence_mode"], "operational")
        self.assertFalse(payload["research_only"])
        self.assertTrue(payload["promotion_preflight_evidence_authorization"])
        self.assertEqual(payload["corpus"]["manifest_sha256"], "1" * 64)
        self.assertEqual(
            source_ablation_operational_contract(payload)["status"],
            "PASS",
        )

        adversarial = [
            (
                "missing corpus",
                {"corpus_manifest": None},
                "promotion corpus manifest",
            ),
            (
                "overlapping splits",
                {
                    "split_dates": {
                        "tune": ["2026-06-01"],
                        "holdout": ["2026-06-01"],
                    }
                },
                "must be disjoint",
            ),
            (
                "detached inference",
                {"paired_inference": []},
                "paired inference differs",
            ),
            (
                "unbound model",
                {"model_binding": {"status": "RESEARCH_UNBOUND"}},
                "model_binding.status must be BOUND",
            ),
            (
                "research-derived corpus",
                {
                    "corpus_manifest": {
                        **copy.deepcopy(case["corpus_manifest"]),
                        "materialization": {
                            "schema_version": "ordinal_smoothing_literal_panel_v0.1",
                            "kind": "fresh",
                        },
                    }
                },
                "research-derived materialization",
            ),
        ]
        for label, replacement, message in adversarial:
            with self.subTest(label=label), self.assertRaisesRegex(
                ValueError, message
            ):
                build_payload(**{**copy.deepcopy(case), **replacement})

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

        self.assertEqual(audit["model_count"], 1)
        self.assertEqual(audit["market_ids"], ["toronto"])
        self.assertIn(audit["status"], {"BOUND", "RESEARCH_UNBOUND"})
        self.assertIn("serving_or_release_authorization", audit)

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

    def test_scoring_frame_is_reverified_after_initial_corpus_preflight(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / SLUG
            self._build_day(folder)
            replay_path = folder / "replay_inputs.jsonl"
            record = json.loads(replay_path.read_text(encoding="utf-8").splitlines()[0])
            manifest = {
                "entries": [
                    {
                        "event_slug": SLUG,
                        "snapshot_ids": ["snap1"],
                        "tape_row_hashes": {},
                        "replay_record_hashes": {
                            "snap1": canonical_replay_record_sha256(record)
                        },
                        "settlement_bucket": 25,
                        "settlement_source": "fixture",
                    }
                ]
            }

            def mutate_after_preflight(*_args, **_kwargs):
                tape = folder / "snapshots_long.csv"
                frame = pd.read_csv(tape)
                frame["snapshot_id"] = "replacement"
                frame.to_csv(tape, index=False)
                return []

            with (
                mock.patch(
                    "weather.backtesting.replay_ablation.verify_corpus_inputs",
                    side_effect=mutate_after_preflight,
                ),
                self.assertRaisesRegex(ValueError, "exact scoring-frame"),
            ):
                run_ablation(
                    [str(folder)],
                    ["open_meteo"],
                    corpus_manifest=manifest,
                )


if __name__ == "__main__":
    unittest.main()
