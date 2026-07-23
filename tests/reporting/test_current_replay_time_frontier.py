import argparse
import json
import tempfile
import unittest
from pathlib import Path

from weather.reporting.research.current_replay_time_frontier import (
    H1_SCHEMA_VERSION,
    SCHEMA_VERSION,
    CacheMetadata,
    ExperimentConfigurationError,
    ReaderStats,
    aggregate_market_dates,
    analyze_split_units,
    aligned_row_pairs,
    aligned_selected_row_pairs,
    build_cache_plan,
    build_complete_panel_fleet_date_rows,
    build_fleet_date_rows,
    build_summaries,
    derive_breakpoints,
    iter_cache_array,
    iter_snapshot_scores,
    load_h1_selection,
    read_cache_metadata,
    run_experiment,
    validate_path_contract,
)
from weather.reporting.research.current_replay_time_frontier_sharpness import (
    analyze_holdout_sharpness,
)


def _row(
    *,
    target_date="2026-06-01",
    market_id="toronto",
    unit="C",
    snapshot_id="s1",
    captured="2026-06-01T03:10:00-04:00",
    winner_probability=0.6,
    market_winner_probability=0.7,
):
    rows = []
    for band, outcome, model_probability, market_probability, value in (
        ("winner", 1, winner_probability, market_winner_probability, 20),
        ("loser", 0, 1.0 - winner_probability, 1.0 - market_winner_probability, 21),
    ):
        rows.append(
            {
                "market_id": market_id,
                "unit": unit,
                "target_date": target_date,
                "snapshot_id": snapshot_id,
                "captured_at_local": captured,
                "capture_minute": int(captured[11:13]) * 60 + int(captured[14:16]),
                "cutoff_hour": int(captured[11:13]),
                "band": band,
                "bin_type": "eq",
                "bin_value_c": value,
                "bin_value_hi": value,
                "outcome": outcome,
                "market_yes": market_probability,
                "replayed_p": model_probability,
            }
        )
    return rows


def _write_cache(
    path,
    *,
    split,
    weight,
    rows,
    fingerprint_char,
    distribution_rows=None,
):
    payload = {
        "schema_version": H1_SCHEMA_VERSION,
        "fingerprint": fingerprint_char * 64,
        "arm": {
            "split": split,
            "weight": weight,
            "sigma": 0.75,
            "rows": rows,
            "distribution_rows": list(distribution_rows or ()),
            "replay": {"blockers": [], "snaps_scored": len(rows) // 2},
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _distribution_row(
    *,
    market_id,
    unit,
    distribution,
    snapshot_id,
    target_date="2026-06-02",
    captured="2026-06-02T03:00:00-04:00",
):
    return {
        "capture_minute": 180,
        "captured_at_local": captured,
        "cutoff_hour": 3,
        "distribution": distribution,
        "market_id": market_id,
        "snapshot_id": snapshot_id,
        "target_date": target_date,
        "unit": unit,
    }


def _h1_payload(*, cache_root, tune_dates, holdout_dates, selected=None):
    selected = selected or {"C": 0.1, "F": 0.0}
    holdout_weights = {0.0} | {float(value) for value in selected.values() if value > 0}
    tune_weights = {0.0} | {float(value) for value in selected.values()}
    return {
        "schema_version": H1_SCHEMA_VERSION,
        "status": "COMPLETE",
        "experiment": {"selection_uses_holdout": False},
        "split": {
            "tune_dates": list(tune_dates),
            "holdout_dates": list(holdout_dates),
        },
        "outputs": {"cache_root": str(cache_root)},
        "tune": {
            "status": "PASS",
            "arm_gates": {
                str(weight): {"status": "PASS"} for weight in tune_weights
            },
            "selected_weights": selected,
            "selection": {
                unit: {"selected_weight": weight} for unit, weight in selected.items()
            },
        },
        "holdout": {
            "status": "PASS",
            "arm_gates": {
                str(weight): {"status": "PASS"} for weight in holdout_weights
            },
            "dispositions": {"C": "DIRECTIONAL_ONLY", "F": "NO_TUNE_CANDIDATE"},
        },
    }


def _blocked_h1_payload(*, cache_root, tune_dates, holdout_dates, selected=None):
    payload = _h1_payload(
        cache_root=cache_root,
        tune_dates=tune_dates,
        holdout_dates=holdout_dates,
        selected=selected or {"C": 1.0, "F": 1.0},
    )
    payload["status"] = "BLOCK"
    payload["tune"]["status"] = "BLOCK"
    payload["tune"]["blockers"] = ["duplicate comparison key: fixture"]
    payload["tune"]["weight_zero_determinism"] = {
        "status": "BLOCK",
        "row_mismatches": 4,
        "distribution_mismatches": 0,
        "baseline_row_hash": "a" * 64,
        "control_row_hash": "a" * 64,
        "baseline_distribution_hash": "b" * 64,
        "control_distribution_hash": "b" * 64,
    }
    payload["technical_blockers"] = ["duplicate comparison key: fixture"]
    payload["holdout"] = {
        "status": "NOT_TOUCHED",
        "reason": "tune technical gates blocked before candidate selection",
    }
    return payload


class CurrentReplayTimeFrontierTests(unittest.TestCase):
    def test_streaming_reader_is_bounded_across_adversarial_chunk_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            expected = _row(snapshot_id="snapshot-with-a-somewhat-long-identifier")
            _write_cache(
                path,
                split="tune",
                weight=0.0,
                rows=expected,
                fingerprint_char="a",
            )
            stats = ReaderStats("rows", chunk_chars=37, max_item_chars=4096)
            actual = list(
                iter_cache_array(
                    path,
                    "rows",
                    chunk_chars=37,
                    max_item_chars=4096,
                    stats=stats,
                )
            )

        self.assertEqual(actual, expected)
        self.assertEqual(stats.items_yielded, 2)
        self.assertLessEqual(stats.maximum_buffer_chars, 37 + 4096)
        self.assertLess(stats.maximum_item_chars, 4096)

    def test_streaming_reader_fails_closed_on_oversize_or_noncanonical_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            oversized = root / "oversized.json"
            rows = _row()
            rows[0]["large"] = "x" * 500
            _write_cache(
                oversized,
                split="tune",
                weight=0.0,
                rows=rows,
                fingerprint_char="b",
            )
            with self.assertRaisesRegex(ExperimentConfigurationError, "exceeds"):
                list(
                    iter_cache_array(
                        oversized,
                        chunk_chars=64,
                        max_item_chars=200,
                    )
                )

            pretty = root / "pretty.json"
            pretty.write_text('{\n  "arm": {}\n}\n', encoding="utf-8")
            with self.assertRaisesRegex(ExperimentConfigurationError, "canonical"):
                list(iter_cache_array(pretty, chunk_chars=64, max_item_chars=200))

    def test_cache_metadata_reads_only_canonical_tail_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            _write_cache(
                path,
                split="holdout",
                weight=0.25,
                rows=_row(),
                fingerprint_char="c",
            )
            metadata = read_cache_metadata(path)

        self.assertIsInstance(metadata, CacheMetadata)
        self.assertEqual(metadata.split, "holdout")
        self.assertEqual(metadata.weight, 0.25)
        self.assertEqual(metadata.sigma, 0.75)
        self.assertEqual(metadata.fingerprint, "c" * 64)

    def test_holdout_selection_gate_rejects_incomplete_or_unselected_arm(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = root / "h1.json"
            tune_dates = ("2026-06-01",)
            holdout_dates = ("2026-06-02",)
            payload = _h1_payload(
                cache_root=root / "cache",
                tune_dates=tune_dates,
                holdout_dates=holdout_dates,
            )
            payload["status"] = "BLOCK"
            result.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ExperimentConfigurationError, "not COMPLETE"):
                load_h1_selection(
                    result, tune_dates=tune_dates, holdout_dates=holdout_dates
                )

            payload["status"] = "COMPLETE"
            payload["holdout"]["arm_gates"]["0.5"] = {}
            result.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ExperimentConfigurationError, "permitted evidence mode"):
                load_h1_selection(
                    result, tune_dates=tune_dates, holdout_dates=holdout_dates
                )

    def test_selection_gate_requires_each_opened_h1_arm_to_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = root / "h1.json"
            tune_dates = ("2026-06-01",)
            holdout_dates = ("2026-06-02",)
            payload = _h1_payload(
                cache_root=root / "cache",
                tune_dates=tune_dates,
                holdout_dates=holdout_dates,
            )
            payload["holdout"]["arm_gates"]["0.1"]["status"] = "BLOCK"
            result.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                ExperimentConfigurationError, "holdout arm gate 0.1.*not individually PASS"
            ):
                load_h1_selection(
                    result, tune_dates=tune_dates, holdout_dates=holdout_dates
                )

            payload["holdout"]["arm_gates"]["0.1"]["status"] = "PASS"
            payload["tune"]["arm_gates"]["0.1"]["status"] = "BLOCK"
            result.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                ExperimentConfigurationError, "tune arm gate 0.1.*not individually PASS"
            ):
                load_h1_selection(
                    result, tune_dates=tune_dates, holdout_dates=holdout_dates
                )

    def test_selection_gate_rejects_cross_field_disagreement_or_residual_blockers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = root / "h1.json"
            tune_dates = ("2026-06-01",)
            holdout_dates = ("2026-06-02",)
            payload = _h1_payload(
                cache_root=root / "cache",
                tune_dates=tune_dates,
                holdout_dates=holdout_dates,
            )
            payload["tune"]["selection"]["C"]["selected_weight"] = 0.25
            result.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                ExperimentConfigurationError, "selected-weight records disagree"
            ):
                load_h1_selection(
                    result, tune_dates=tune_dates, holdout_dates=holdout_dates
                )

            payload["tune"]["selection"]["C"]["selected_weight"] = 0.1
            payload["technical_blockers"] = ["residual contradiction"]
            result.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                ExperimentConfigurationError, "still records 1 technical blockers"
            ):
                load_h1_selection(
                    result, tune_dates=tune_dates, holdout_dates=holdout_dates
                )

    def test_blocked_tune_only_gate_requires_explicit_mode_and_sealed_holdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = root / "h1.json"
            tune_dates = ("2026-06-01",)
            holdout_dates = ("2026-06-02",)
            payload = _blocked_h1_payload(
                cache_root=root / "cache",
                tune_dates=tune_dates,
                holdout_dates=holdout_dates,
            )
            result.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ExperimentConfigurationError, "not COMPLETE"):
                load_h1_selection(
                    result, tune_dates=tune_dates, holdout_dates=holdout_dates
                )

            selection = load_h1_selection(
                result,
                tune_dates=tune_dates,
                holdout_dates=holdout_dates,
                allow_blocked_tune_only=True,
            )
            self.assertEqual(selection["evidence_mode"], "BLOCKED_TUNE_ONLY")

            payload["holdout"]["arm_gates"] = {"0.0": {}}
            result.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ExperimentConfigurationError, "permitted evidence mode"):
                load_h1_selection(
                    result,
                    tune_dates=tune_dates,
                    holdout_dates=holdout_dates,
                    allow_blocked_tune_only=True,
                )

    def test_cache_plan_never_discovers_an_unselected_holdout_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for split in ("tune", "holdout"):
                for weight, token, character in (
                    (0.0, "0p00", "a" if split == "tune" else "b"),
                    (0.1, "0p10", "c" if split == "tune" else "d"),
                    (0.5, "0p50", "e" if split == "tune" else "f"),
                ):
                    _write_cache(
                        root / f"{split}-weight-{token}.json",
                        split=split,
                        weight=weight,
                        rows=_row(),
                        fingerprint_char=character,
                    )
            plan = build_cache_plan(
                cache_root=root, selected_weights={"C": 0.1, "F": 0.0}
            )

        self.assertEqual(set(plan["holdout"]), {"0.0", "0.1"})
        self.assertNotIn("0.5", plan["holdout"])

    def test_blocked_tune_cache_plan_constructs_no_holdout_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for weight, token, character in (
                (0.0, "0p00", "a"),
                (1.0, "1p00", "b"),
            ):
                _write_cache(
                    root / f"tune-weight-{token}.json",
                    split="tune",
                    weight=weight,
                    rows=_row(),
                    fingerprint_char=character,
                )
            plan = build_cache_plan(
                cache_root=root,
                selected_weights={"C": 1.0, "F": 1.0},
                splits=("tune",),
            )

        self.assertEqual(set(plan), {"tune"})
        self.assertEqual(set(plan["tune"]), {"0.0", "1.0"})

    def test_path_contract_rejects_outputs_under_cache_or_read_only_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            data = root / "data"
            output = root / "scratch" / "out"
            cache.mkdir()
            data.mkdir()
            h1 = root / "h1.json"
            tune = root / "tune.txt"
            holdout = root / "holdout.txt"
            h1.write_text("{}", encoding="utf-8")
            tune.write_text("2026-06-01\n", encoding="utf-8")
            holdout.write_text("2026-06-02\n", encoding="utf-8")

            safe = validate_path_contract(
                h1_result=h1,
                cache_root=cache,
                tune_dates_file=tune,
                holdout_dates_file=holdout,
                output_root=output,
                report_out=root / "report.md",
                read_only_roots=(data,),
            )
            self.assertEqual(safe["output_root"], output.resolve())
            with self.assertRaisesRegex(
                ExperimentConfigurationError, "explicit read-only data root"
            ):
                validate_path_contract(
                    h1_result=h1,
                    cache_root=cache,
                    tune_dates_file=tune,
                    holdout_dates_file=holdout,
                    output_root=output,
                    report_out=root / "report.md",
                )
            for unsafe in (cache / "output", data / "output"):
                with self.assertRaisesRegex(ExperimentConfigurationError, "outside"):
                    validate_path_contract(
                        h1_result=h1,
                        cache_root=cache,
                        tune_dates_file=tune,
                        holdout_dates_file=holdout,
                        output_root=unsafe,
                        report_out=root / "report.md",
                        read_only_roots=(data,),
                    )
            alias = root / "data-alias"
            try:
                alias.symlink_to(data, target_is_directory=True)
            except OSError:
                pass
            else:
                with self.assertRaisesRegex(ExperimentConfigurationError, "outside"):
                    validate_path_contract(
                        h1_result=h1,
                        cache_root=cache,
                        tune_dates_file=tune,
                        holdout_dates_file=holdout,
                        output_root=alias / "output",
                        report_out=root / "report.md",
                        read_only_roots=(data,),
                    )

    def test_alignment_fails_closed_before_scoring(self):
        current = _row(snapshot_id="same")
        selected = _row(snapshot_id="different")
        with self.assertRaisesRegex(ExperimentConfigurationError, "alignment mismatch"):
            list(aligned_row_pairs(current, selected))

    def test_lockstep_alignment_routes_distinct_selected_weights_by_unit(self):
        current = _row(unit="C", market_id="toronto", winner_probability=0.5)
        current += _row(unit="F", market_id="nyc", winner_probability=0.5)
        weight_010 = _row(unit="C", market_id="toronto", winner_probability=0.8)
        weight_010 += _row(unit="F", market_id="nyc", winner_probability=0.6)
        weight_025 = _row(unit="C", market_id="toronto", winner_probability=0.7)
        weight_025 += _row(unit="F", market_id="nyc", winner_probability=0.9)

        pairs = aligned_selected_row_pairs(
            current,
            {0.1: weight_010, 0.25: weight_025},
            {"C": 0.1, "F": 0.25},
        )
        scores = list(iter_snapshot_scores(pairs))

        self.assertEqual([row["unit"] for row in scores], ["C", "F"])
        self.assertAlmostEqual(scores[0]["selected_winner_probability"], 0.8)
        self.assertAlmostEqual(scores[1]["selected_winner_probability"], 0.9)

    def test_lockstep_alignment_collapses_only_score_equivalent_duplicate_keys(self):
        current = _row(winner_probability=0.6)
        selected = _row(winner_probability=0.8)
        current_duplicate = [dict(row, recorded_p=0.01) for row in current]
        selected_duplicate = [dict(row, recorded_p=0.99) for row in selected]
        diagnostics = {}

        pairs = list(
            aligned_selected_row_pairs(
                current + current_duplicate,
                {1.0: selected + selected_duplicate},
                {"C": 1.0, "F": 1.0},
                diagnostics=diagnostics,
            )
        )

        self.assertEqual(len(pairs), 2)
        self.assertEqual(diagnostics["raw_rows"], 4)
        self.assertEqual(diagnostics["unique_rows"], 2)
        self.assertEqual(diagnostics["equivalent_duplicate_rows_collapsed"], 2)
        conflicting = [dict(row) for row in selected_duplicate]
        conflicting[0]["replayed_p"] = 0.79
        with self.assertRaisesRegex(
            ExperimentConfigurationError, "conflicting duplicate comparison key"
        ):
            list(
                aligned_selected_row_pairs(
                    current + current_duplicate,
                    {1.0: selected + conflicting},
                    {"C": 1.0, "F": 1.0},
                )
            )

    def test_snapshot_scoring_matches_h1_binary_band_metrics(self):
        current = _row(winner_probability=0.6, market_winner_probability=0.7)
        selected = _row(winner_probability=0.8, market_winner_probability=0.7)
        scores = list(iter_snapshot_scores(aligned_row_pairs(current, selected)))

        self.assertEqual(len(scores), 1)
        score = scores[0]
        self.assertAlmostEqual(score["current_brier"], 0.16)
        self.assertAlmostEqual(score["selected_brier"], 0.04)
        self.assertAlmostEqual(score["market_brier"], 0.09)
        self.assertAlmostEqual(score["current_winner_probability"], 0.6)
        self.assertAlmostEqual(score["selected_winner_probability"], 0.8)

    def test_split_manifest_is_exact_while_native_units_may_cover_date_subsets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current_rows = _row(target_date="2026-06-01", unit="C", market_id="toronto")
            current_rows += _row(
                target_date="2026-06-02",
                unit="F",
                market_id="nyc",
                snapshot_id="s2",
            )
            selected_rows = _row(
                target_date="2026-06-01",
                unit="C",
                market_id="toronto",
                winner_probability=0.8,
            )
            selected_rows += _row(
                target_date="2026-06-02",
                unit="F",
                market_id="nyc",
                snapshot_id="s2",
                winner_probability=0.8,
            )
            current = root / "tune-weight-0p00.json"
            selected = root / "tune-weight-1p00.json"
            _write_cache(
                current,
                split="tune",
                weight=0.0,
                rows=current_rows,
                fingerprint_char="a",
            )
            _write_cache(
                selected,
                split="tune",
                weight=1.0,
                rows=selected_rows,
                fingerprint_char="b",
            )

            _, diagnostics = analyze_split_units(
                split="tune",
                current_cache=current,
                selected_caches_by_weight={1.0: selected},
                selected_weights={"C": 1.0, "F": 1.0},
                expected_dates=("2026-06-01", "2026-06-02"),
            )

        self.assertEqual(
            diagnostics["observed_split_dates"],
            ["2026-06-01", "2026-06-02"],
        )
        self.assertEqual(diagnostics["units"]["C"]["observed_dates"], ["2026-06-01"])
        self.assertEqual(diagnostics["units"]["F"]["observed_dates"], ["2026-06-02"])

    def test_market_date_then_fleet_date_weighting_defeats_snapshot_density(self):
        snapshots = []
        for index in range(100):
            snapshots.append(
                {
                    "market_id": "toronto",
                    "unit": "C",
                    "target_date": "2026-06-01",
                    "hour": 3,
                    "band_rows": 2,
                    **{
                        f"{model}_{metric}": 0.0
                        for model in ("current", "selected", "market")
                        for metric in ("brier", "logloss", "winner_probability")
                    },
                }
            )
        snapshots.append(
            {
                "market_id": "toronto",
                "unit": "C",
                "target_date": "2026-06-02",
                "hour": 3,
                "band_rows": 2,
                **{
                    f"{model}_{metric}": 1.0
                    for model in ("current", "selected", "market")
                    for metric in ("brier", "logloss", "winner_probability")
                },
            }
        )
        market_rows, _ = aggregate_market_dates(
            snapshots, split="holdout", selected_weight=0.1
        )
        fleet_rows = build_fleet_date_rows(market_rows)
        summaries = build_summaries(market_rows, fleet_rows)
        fleet = next(
            row
            for row in summaries
            if row["market_id"] == "__fleet__" and row["scope"] == "all_hours"
        )

        self.assertAlmostEqual(fleet["metrics"]["current"]["brier"], 0.5)
        self.assertNotAlmostEqual(fleet["metrics"]["current"]["brier"], 1.0 / 101)

    def test_complete_panel_sensitivity_drops_partial_dates_without_imputation(self):
        snapshots = []
        for target_date, unit, markets in (
            ("2026-06-01", "C", (("toronto", 0.25),)),
            ("2026-06-02", "C", (("toronto", 0.75),)),
            ("2026-06-01", "F", (("chicago", 1.0), ("nyc", 0.0))),
            ("2026-06-02", "F", (("nyc", 0.0),)),
        ):
            for market_id, score in markets:
                snapshots.append(
                    {
                        "market_id": market_id,
                        "unit": unit,
                        "target_date": target_date,
                        "hour": 3,
                        "band_rows": 2,
                        **{
                            f"{model}_{metric}": score
                            for model in ("current", "selected", "market")
                            for metric in ("brier", "logloss", "winner_probability")
                        },
                    }
                )
        market_rows, _ = aggregate_market_dates(
            snapshots,
            split="holdout",
            selected_weight=0.1,
        )

        fleet_rows, coverage = build_complete_panel_fleet_date_rows(
            market_rows,
            configured={"C": ("toronto",), "F": ("chicago", "nyc")},
            splits=("holdout",),
        )

        f_all_hours = next(
            row
            for row in fleet_rows
            if row["unit"] == "F" and row["scope"] == "all_hours"
        )
        self.assertEqual(f_all_hours["target_date"], "2026-06-01")
        self.assertEqual(f_all_hours["markets"], 2)
        self.assertAlmostEqual(f_all_hours["current_brier"], 0.5)
        self.assertEqual(
            f_all_hours["panel_scope"],
            "COMPLETE_CONFIGURED_NATIVE_UNIT_PANEL",
        )
        f_coverage = next(
            row
            for row in coverage
            if row["split"] == "holdout"
            and row["unit"] == "F"
            and row["scope"] == "all_hours"
        )
        self.assertEqual(f_coverage["available_case_fleet_dates"], 2)
        self.assertEqual(f_coverage["complete_panel_fleet_dates"], 1)
        self.assertEqual(f_coverage["dropped_incomplete_fleet_dates"], 1)
        self.assertFalse(f_coverage["imputation_used"])
        self.assertEqual(
            f_coverage["incomplete_target_dates"],
            [
                {
                    "target_date": "2026-06-02",
                    "observed_market_count": 1,
                    "observed_markets": ["nyc"],
                    "missing_markets": ["chicago"],
                }
            ],
        )

    def test_sharpness_mechanics_uses_exact_buckets_and_converts_f_width(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = root / "holdout-weight-0p00.json"
            selected = root / "holdout-weight-1p00.json"
            current_distributions = [
                _distribution_row(
                    market_id="toronto",
                    unit="C",
                    distribution={"0": 0.5, "2": 0.5},
                    snapshot_id="c",
                ),
                _distribution_row(
                    market_id="nyc",
                    unit="F",
                    distribution={"68": 0.5, "70": 0.5},
                    snapshot_id="f",
                ),
            ]
            selected_distributions = [
                _distribution_row(
                    market_id="toronto",
                    unit="C",
                    distribution={"-1": 0.5, "3": 0.5},
                    snapshot_id="c",
                ),
                _distribution_row(
                    market_id="nyc",
                    unit="F",
                    distribution={"67": 0.5, "71": 0.5},
                    snapshot_id="f",
                ),
            ]
            _write_cache(
                current,
                split="holdout",
                weight=0.0,
                rows=_row(target_date="2026-06-02"),
                distribution_rows=current_distributions,
                fingerprint_char="a",
            )
            _write_cache(
                selected,
                split="holdout",
                weight=1.0,
                rows=_row(target_date="2026-06-02"),
                distribution_rows=selected_distributions,
                fingerprint_char="b",
            )

            payload = analyze_holdout_sharpness(
                current_cache=current,
                selected_caches_by_weight={1.0: selected},
                selected_weights={"C": 1.0, "F": 1.0},
                expected_dates=("2026-06-02",),
            )

        f_all = next(
            row
            for row in payload["summaries"]
            if row["unit"] == "F"
            and row["market_id"] == "__fleet__"
            and row["scope"] == "all_hours"
        )
        self.assertAlmostEqual(f_all["metrics"]["current"]["std_native"], 1.0)
        self.assertAlmostEqual(f_all["metrics"]["selected"]["std_native"], 2.0)
        self.assertAlmostEqual(
            f_all["selected_vs_current"]["std_c_equivalent"]["mean_delta"],
            5.0 / 9.0,
        )
        native_ci = f_all["selected_vs_current"]["std_native"][
            "paired_fleet_date_bootstrap_95ci"
        ]
        physical_ci = f_all["selected_vs_current"]["std_c_equivalent"][
            "paired_fleet_date_bootstrap_95ci"
        ]
        self.assertAlmostEqual(physical_ci["low"], native_ci["low"] * 5.0 / 9.0)
        self.assertAlmostEqual(physical_ci["high"], native_ci["high"] * 5.0 / 9.0)
        self.assertEqual(payload["diagnostics"]["alignment"]["unique_rows"], 2)
        self.assertFalse(payload["selection_or_gate_use"])

    def test_breakpoints_require_sustained_later_hour_condition(self):
        summaries = []
        for hour, model_brier, model_logloss, model_winner in (
            (15, 0.10, 0.20, 0.70),
            (16, 0.30, 0.40, 0.40),
            (17, 0.10, 0.20, 0.70),
            (18, 0.30, 0.40, 0.40),
            (19, 0.30, 0.40, 0.40),
        ):
            summaries.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "split": "holdout",
                    "unit": "C",
                    "market_id": "__fleet__",
                    "scope": f"hour_{hour:02d}",
                    "fleet_dates": 10,
                    "metrics": {
                        "current": {
                            "brier": model_brier,
                            "logloss": model_logloss,
                            "winner_probability": model_winner,
                        },
                        "selected": {
                            "brier": model_brier,
                            "logloss": model_logloss,
                            "winner_probability": model_winner,
                        },
                        "market": {
                            "brier": 0.20,
                            "logloss": 0.30,
                            "winner_probability": 0.60,
                        },
                    },
                }
            )
        result = next(
            row for row in derive_breakpoints(summaries) if row["model"] == "selected"
        )

        self.assertEqual(result["first_joint_edge_failure_after_positive_hour"], 16)
        self.assertEqual(result["sustained_joint_edge_collapse_hour"], 18)
        self.assertEqual(result["first_market_catchup_hour"], 16)
        self.assertEqual(result["sustained_market_catchup_hour"], 18)

    def test_small_end_to_end_run_writes_integrity_and_never_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_root = root / "h1-cache"
            data_root = root / "data"
            output_root = root / "scratch" / "time-frontier"
            data_root.mkdir()
            tune_dates = ("2026-06-01",)
            holdout_dates = ("2026-06-02",)
            tune_file = root / "tune.txt"
            holdout_file = root / "holdout.txt"
            tune_file.write_text("\n".join(tune_dates) + "\n", encoding="utf-8")
            holdout_file.write_text("\n".join(holdout_dates) + "\n", encoding="utf-8")

            fingerprint_chars = iter("abcd")
            for split, target_date in (("tune", tune_dates[0]), ("holdout", holdout_dates[0])):
                baseline_rows = []
                selected_rows = []
                baseline_distributions = []
                selected_distributions = []
                for unit, market in (("C", "toronto"), ("F", "nyc")):
                    baseline_rows.extend(
                        _row(
                            target_date=target_date,
                            unit=unit,
                            market_id=market,
                            snapshot_id=f"{split}-{unit}",
                            captured=f"{target_date}T03:10:00-04:00",
                            winner_probability=0.6,
                        )
                    )
                    selected_rows.extend(
                        _row(
                            target_date=target_date,
                            unit=unit,
                            market_id=market,
                            snapshot_id=f"{split}-{unit}",
                            captured=f"{target_date}T03:10:00-04:00",
                            winner_probability=0.8 if unit == "C" else 0.6,
                        )
                    )
                    if split == "holdout":
                        distribution_arguments = {
                            "market_id": market,
                            "unit": unit,
                            "snapshot_id": f"{split}-{unit}",
                            "target_date": target_date,
                            "captured": f"{target_date}T03:10:00-04:00",
                        }
                        baseline_distributions.append(
                            _distribution_row(
                                distribution={"20": 0.6, "21": 0.4},
                                **distribution_arguments,
                            )
                        )
                        selected_distributions.append(
                            _distribution_row(
                                distribution=(
                                    {"20": 0.8, "21": 0.2}
                                    if unit == "C"
                                    else {"20": 0.6, "21": 0.4}
                                ),
                                **distribution_arguments,
                            )
                        )
                _write_cache(
                    cache_root / f"{split}-weight-0p00.json",
                    split=split,
                    weight=0.0,
                    rows=baseline_rows,
                    distribution_rows=baseline_distributions,
                    fingerprint_char=next(fingerprint_chars),
                )
                _write_cache(
                    cache_root / f"{split}-weight-0p10.json",
                    split=split,
                    weight=0.1,
                    rows=selected_rows,
                    distribution_rows=selected_distributions,
                    fingerprint_char=next(fingerprint_chars),
                )
            h1_result = root / "h1-result.json"
            h1_result.write_text(
                json.dumps(
                    _h1_payload(
                        cache_root=cache_root,
                        tune_dates=tune_dates,
                        holdout_dates=holdout_dates,
                    )
                ),
                encoding="utf-8",
            )
            historical = root / "hourly.json"
            historical.write_text(
                json.dumps(
                    {
                        "schema_version": "hourly_model_performance_v0.3",
                        "generated_at_utc": "2026-07-19T00:00:00+00:00",
                        "corpus": {
                            "date_min": "2026-05-01",
                            "date_max": "2026-07-18",
                            "scored_market_days": 100,
                            "markets": ["toronto", "nyc"],
                        },
                        "hourly_performance_gate": {
                            "status": "BLOCK",
                            "blockers": [{"gate": "early"}],
                        },
                        "by_hour": [
                            {
                                "hour": hour,
                                "market_days": 100,
                                "markets": 2,
                                "model_brier": 0.2,
                                "market_brier": 0.1,
                                "model_logloss": 0.3,
                                "market_logloss": 0.2,
                                "winner_model_probability": 0.4,
                                "winner_market_probability": 0.6,
                            }
                            for hour in range(24)
                        ],
                    }
                ),
                encoding="utf-8",
            )
            report = root / "tracked-report.md"
            args = argparse.Namespace(
                h1_result=str(h1_result),
                cache_root=str(cache_root),
                tune_dates_file=str(tune_file),
                holdout_dates_file=str(holdout_file),
                output_root=str(output_root),
                report_out=str(report),
                historical_hourly_json=str(historical),
                read_only_root=[str(data_root)],
            )
            payload = run_experiment(args)

            self.assertEqual(payload["status"], "COMPLETE")
            self.assertEqual(payload["selection"]["holdout_arms_opened"], [0.0, 0.1])
            self.assertEqual(payload["reader_diagnostics"]["holdout"]["unique_cache_scans"], 2)
            self.assertTrue((output_root / "integrity_manifest.json").is_file())
            self.assertTrue(
                (output_root / "complete_panel_fleet_date_metrics.csv").is_file()
            )
            self.assertTrue(
                (output_root / "complete_panel_summary_metrics.csv").is_file()
            )
            self.assertTrue((output_root / "complete_panel_coverage.json").is_file())
            self.assertTrue((output_root / "sharpness_mechanics.json").is_file())
            self.assertTrue(report.is_file())
            self.assertEqual(
                payload["historical_context"]["schema_version"],
                "hourly_model_performance_v0.3",
            )
            self.assertEqual(len(payload["historical_pattern_reproduction"]), 2)
            sensitivity = payload["complete_panel_sensitivity"]
            self.assertEqual(
                payload["sharpness_mechanics"]["status"],
                "COMPLETE_DESCRIPTIVE",
            )
            self.assertEqual(sensitivity["configured_market_count"], 12)
            self.assertEqual(
                {unit: len(markets) for unit, markets in sensitivity["configured_markets_by_unit"].items()},
                {"C": 1, "F": 11},
            )
            self.assertFalse(sensitivity["imputation_used"])
            f_all_hours_coverage = next(
                row
                for row in sensitivity["coverage"]
                if row["split"] == "holdout"
                and row["unit"] == "F"
                and row["scope"] == "all_hours"
            )
            self.assertEqual(f_all_hours_coverage["available_case_fleet_dates"], 1)
            self.assertEqual(f_all_hours_coverage["complete_panel_fleet_dates"], 0)
            self.assertEqual(f_all_hours_coverage["dropped_incomplete_fleet_dates"], 1)
            c_slot = next(
                row
                for row in payload["summaries"]
                if row["split"] == "holdout"
                and row["unit"] == "C"
                and row["market_id"] == "__fleet__"
                and row["scope"] == "ten_minute_0310"
            )
            self.assertAlmostEqual(
                c_slot["selected_vs_current"]["brier"]["mean_delta"],
                -0.12,
            )
            f_slot_coverage = next(
                row
                for row in sensitivity["coverage"]
                if row["split"] == "holdout"
                and row["unit"] == "F"
                and row["scope"] == "ten_minute_0310"
            )
            self.assertEqual(f_slot_coverage["available_case_fleet_dates"], 1)
            self.assertEqual(f_slot_coverage["complete_panel_fleet_dates"], 0)
            report_text = report.read_text(encoding="utf-8")
            self.assertIn("Fixed predawn ten-minute evidence", report_text)
            self.assertIn("03:10-03:19", report_text)
            self.assertEqual(list(data_root.iterdir()), [])
            holdout_c = next(
                row
                for row in payload["summaries"]
                if row["split"] == "holdout"
                and row["unit"] == "C"
                and row["market_id"] == "__fleet__"
                and row["scope"] == "predawn_03_05"
            )
            self.assertAlmostEqual(
                holdout_c["selected_vs_current"]["brier"]["mean_delta"], -0.12
            )
            self.assertEqual(
                holdout_c["selected_effect_disposition"], "SUPPORTED_ALL_THREE"
            )
            holdout_f = next(
                row
                for row in payload["summaries"]
                if row["split"] == "holdout"
                and row["unit"] == "F"
                and row["market_id"] == "__fleet__"
                and row["scope"] == "predawn_03_05"
            )
            self.assertEqual(
                holdout_f["selected_vs_current"]["brier"]["mean_delta"], 0.0
            )
            self.assertEqual(
                holdout_f["selected_effect_disposition"], "NO_SELECTED_CHANGE"
            )

    def test_blocked_h1_can_produce_only_exploratory_tune_result_without_holdout_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_root = root / "h1-cache"
            data_root = root / "data"
            output_root = root / "scratch" / "time-frontier"
            data_root.mkdir()
            tune_dates = ("2026-06-01",)
            holdout_dates = ("2026-06-02",)
            tune_file = root / "tune.txt"
            holdout_file = root / "holdout.txt"
            tune_file.write_text("2026-06-01\n", encoding="utf-8")
            holdout_file.write_text("2026-06-02\n", encoding="utf-8")

            current_rows = _row(target_date=tune_dates[0], winner_probability=0.6)
            selected_rows = _row(target_date=tune_dates[0], winner_probability=0.8)
            current_rows += _row(
                target_date=tune_dates[0],
                market_id="nyc",
                unit="F",
                snapshot_id="s2",
                winner_probability=0.6,
            )
            selected_rows += _row(
                target_date=tune_dates[0],
                market_id="nyc",
                unit="F",
                snapshot_id="s2",
                winner_probability=0.8,
            )
            # Repeating the same snapshot-band identity is the exact fail-closed
            # condition observed in the sealed H1 tune cache.
            _write_cache(
                cache_root / "tune-weight-0p00.json",
                split="tune",
                weight=0.0,
                rows=current_rows + current_rows,
                fingerprint_char="a",
            )
            _write_cache(
                cache_root / "tune-weight-1p00.json",
                split="tune",
                weight=1.0,
                rows=selected_rows + selected_rows,
                fingerprint_char="b",
            )
            # Intentionally create no holdout cache. The blocked mode must not
            # discover or require one.
            h1_result = root / "h1-result.json"
            h1_result.write_text(
                json.dumps(
                    _blocked_h1_payload(
                        cache_root=cache_root,
                        tune_dates=tune_dates,
                        holdout_dates=holdout_dates,
                    )
                ),
                encoding="utf-8",
            )
            report = root / "blocked-report.md"
            args = argparse.Namespace(
                h1_result=str(h1_result),
                cache_root=str(cache_root),
                tune_dates_file=str(tune_file),
                holdout_dates_file=str(holdout_file),
                output_root=str(output_root),
                report_out=str(report),
                historical_hourly_json=None,
                read_only_root=[str(data_root)],
                allow_blocked_tune_only=True,
            )

            payload = run_experiment(args)

            self.assertEqual(payload["status"], "BLOCK")
            self.assertEqual(payload["analysis_status"], "COMPLETE_TUNE_ONLY_EXPLORATORY")
            self.assertEqual(payload["selection"]["holdout_arms_opened"], [])
            self.assertEqual(payload["split"]["analyzed_splits"], ["tune"])
            self.assertEqual(set(payload["cache_metadata"]), {"tune:0.0", "tune:1.0"})
            self.assertEqual(payload["analysis_blockers"], [])
            self.assertGreater(len(payload["summaries"]), 0)
            self.assertEqual(
                payload["reader_diagnostics"]["tune"]["alignment"]
                ["equivalent_duplicate_rows_collapsed"],
                4,
            )
            self.assertTrue((output_root / "integrity_manifest.json").is_file())
            self.assertIn("TUNE-ONLY EXPLORATORY", report.read_text(encoding="utf-8"))
            self.assertEqual(list(data_root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
