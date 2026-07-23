import gc
import json
import math
import tempfile
import unittest
import weakref
from pathlib import Path

from weather.reporting.research.ordinal_smoothing_sweep import (
    SCHEMA_VERSION,
    SMOOTHING_SIGMA,
    SWEEP_WEIGHTS,
    ExperimentConfigurationError,
    alignment_gate,
    analyze_holdout_arms,
    analyze_holdout_arms_incremental,
    analyze_tune_arms,
    analyze_tune_arms_incremental,
    analyze_weight_zero_control,
    cache_fingerprint,
    cluster_bootstrap_ci,
    exact_determinism_gate,
    mass_gate,
    load_or_run_arm,
    ordinal_smoothing_config,
    partition_manifest_entries,
    scope_effect_audit,
    read_predeclared_dates,
    render_report,
    validate_staged_daily_inputs,
    validate_path_contract,
)
from weather.reporting.research.ordinal_smoothing_sweep_impl import (
    COMPATIBLE_ARM_CODE_DIGESTS,
    MAX_CACHE_BYTES,
)


TUNE_DATES = ("2026-06-01", "2026-06-02")
HOLDOUT_DATES = ("2026-06-03", "2026-06-04")


def _winner_probability(weight, unit):
    if weight == 0.0:
        return 0.55
    by_unit = {
        "C": {0.10: 0.62, 0.25: 0.82, 0.50: 0.74, 0.75: 0.68, 1.0: 0.60},
        "F": {0.10: 0.61, 0.25: 0.70, 0.50: 0.84, 0.75: 0.72, 1.0: 0.59},
    }
    return by_unit[unit][weight]


def make_arm(weight, split, dates, *, bad_mass=False):
    rows = []
    distributions = []
    for target_date in dates:
        for unit, market_id in (("C", "toronto"), ("F", "nyc")):
            for hour in (3, 9):
                snapshot_id = f"{target_date}-{market_id}-{hour}"
                captured = f"{target_date}T{hour:02d}:00:00-04:00"
                probability = _winner_probability(weight, unit)
                for band, outcome, replayed, market_yes in (
                    ("winner", 1, probability, 0.65),
                    ("loser", 0, 1.0 - probability, 0.35),
                ):
                    rows.append(
                        {
                            "market_id": market_id,
                            "unit": unit,
                            "target_date": target_date,
                            "snapshot_id": snapshot_id,
                            "captured_at_local": captured,
                            "cutoff_hour": hour,
                            "band": band,
                            "bin_type": "eq",
                            "bin_value_c": 20 if band == "winner" else 21,
                            "bin_value_hi": 20 if band == "winner" else 21,
                            "outcome": outcome,
                            "market_yes": market_yes,
                            "replayed_p": replayed,
                        }
                    )
                distribution = {"20": probability, "21": 1.0 - probability}
                if bad_mass and weight == 0.25 and unit == "C" and hour == 9:
                    distribution = {"20": probability, "21": 0.0}
                distributions.append(
                    {
                        "market_id": market_id,
                        "unit": unit,
                        "target_date": target_date,
                        "snapshot_id": snapshot_id,
                        "captured_at_local": captured,
                        "cutoff_hour": hour,
                        "distribution": distribution,
                    }
                )
    snapshots = len(distributions)
    return {
        "split": split,
        "weight": weight,
        "sigma": SMOOTHING_SIGMA,
        "rows": rows,
        "distribution_rows": distributions,
        "replay": {
            "snaps_in_corpus": snapshots,
            "snaps_scored": snapshots,
            "blockers": [],
        },
    }


class OrdinalSmoothingSweepTests(unittest.TestCase):
    def test_model_arm_changes_only_weight_when_feature_path_exists(self):
        self.assertEqual(
            ordinal_smoothing_config(0.0, 6),
            {
                "enabled": False,
                "sigma": 0.0,
                "blend_weight": 0.0,
                "source": "research_h1_fixed_sweep",
            },
        )
        self.assertEqual(
            ordinal_smoothing_config(0.25, 6),
            {
                "enabled": True,
                "sigma": 0.75,
                "blend_weight": 0.25,
                "source": "research_h1_fixed_sweep",
            },
        )
        with self.assertRaises(ExperimentConfigurationError):
            ordinal_smoothing_config(0.30, 7)

    def test_path_contract_rejects_every_output_under_an_input_data_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mirror = root / "mirror"
            snapshots = mirror / "snapshots"
            staged = root / "staged"
            output = root / "output"
            snapshots.mkdir(parents=True)
            staged.mkdir()
            output.mkdir()
            corpus = mirror / "backtest" / "corpus.json"
            corpus.parent.mkdir()
            corpus.write_text("{}", encoding="utf-8")
            tune = root / "tune.txt"
            holdout = root / "holdout.txt"
            tune.write_text("2026-06-01\n", encoding="utf-8")
            holdout.write_text("2026-06-02\n", encoding="utf-8")

            paths = validate_path_contract(
                mirror_data_root=mirror,
                staged_data_root=staged,
                snapshots_root=snapshots,
                corpus_path=corpus,
                tune_dates_path=tune,
                holdout_dates_path=holdout,
                json_out=output / "result.json",
                report_out=output / "result.md",
                cache_root=output / "cache",
                lock_path=output / "run.lock",
            )
            self.assertEqual(paths["mirror_data_root"], mirror.resolve())

            for unsafe_key in ("json_out", "report_out", "cache_root", "lock_path"):
                kwargs = {
                    "mirror_data_root": mirror,
                    "staged_data_root": staged,
                    "snapshots_root": snapshots,
                    "corpus_path": corpus,
                    "tune_dates_path": tune,
                    "holdout_dates_path": holdout,
                    "json_out": output / "result.json",
                    "report_out": output / "result.md",
                    "cache_root": output / "cache",
                    "lock_path": output / "run.lock",
                }
                kwargs[unsafe_key] = mirror / "unsafe" / unsafe_key
                with self.assertRaises(ExperimentConfigurationError):
                    validate_path_contract(**kwargs)

    def test_date_manifests_are_sorted_disjoint_and_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dates.txt"
            path.write_text("# fixed before replay\n2026-06-01\n2026-06-02\n", encoding="utf-8")
            self.assertEqual(read_predeclared_dates(path), TUNE_DATES)

        manifest = {
            "entries": [
                {"event_slug": f"slug-{day}", "target_date": day, "market_id": "toronto"}
                for day in TUNE_DATES + HOLDOUT_DATES
            ]
        }
        partitions = partition_manifest_entries(manifest, TUNE_DATES, HOLDOUT_DATES)
        self.assertEqual(len(partitions["tune"]), 2)
        self.assertEqual(len(partitions["holdout"]), 2)
        with self.assertRaises(ExperimentConfigurationError):
            partition_manifest_entries(manifest, TUNE_DATES, (TUNE_DATES[-1],) + HOLDOUT_DATES)

    def test_summary_only_staging_fails_closed_without_hourly_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            staged = Path(tmp)
            daily = staged / "wunderground" / "cyyz" / "daily" / "daily_summary.csv"
            daily.parent.mkdir(parents=True)
            daily.write_text("local_date,max_temp_native\n", encoding="utf-8")
            entries = [{"market_id": "toronto", "target_date": "2026-06-01"}]
            with self.assertRaises(ExperimentConfigurationError):
                validate_staged_daily_inputs(entries, staged)

    def test_tune_selects_c_and_f_independently_and_holdout_tests_only_selection(self):
        tune_arms = [make_arm(weight, "tune", TUNE_DATES) for weight in SWEEP_WEIGHTS]
        control = make_arm(0.0, "tune-determinism-control", TUNE_DATES[:1])
        first = analyze_tune_arms(
            tune_arms, TUNE_DATES, baseline_control=control
        )
        second = analyze_tune_arms(
            tune_arms, TUNE_DATES, baseline_control=control
        )

        self.assertEqual(first, second)
        self.assertEqual(first["status"], "PASS")
        self.assertEqual(first["weight_zero_determinism"]["status"], "PASS")
        self.assertEqual(first["selected_weights"], {"C": 0.25, "F": 0.50})
        self.assertTrue(
            all(
                gate["scope_effect"]["windows"]["00-06"]["changed_exact"] > 0
                for weight, gate in first["arm_gates"].items()
                if float(weight) > 0.0
            )
        )

        holdout_arms = [
            make_arm(weight, "holdout", HOLDOUT_DATES)
            for weight in (0.0, 0.25, 0.50)
        ]
        holdout = analyze_holdout_arms(
            holdout_arms, HOLDOUT_DATES, first["selected_weights"]
        )
        self.assertEqual(holdout["status"], "PASS")
        self.assertEqual(holdout["paired"]["C"]["weight"], 0.25)
        self.assertEqual(holdout["paired"]["F"]["weight"], 0.50)
        self.assertEqual(holdout["dispositions"], {"C": "SUPPORTED", "F": "SUPPORTED"})

    def test_incremental_orchestration_matches_schema_and_releases_each_candidate(self):
        tune_baseline = make_arm(0.0, "tune", TUNE_DATES)
        control = make_arm(0.0, "tune-determinism-control", TUNE_DATES[:1])
        expected_tune = analyze_tune_arms(
            [make_arm(weight, "tune", TUNE_DATES) for weight in SWEEP_WEIGHTS],
            TUNE_DATES,
            baseline_control=control,
        )
        compact_control = analyze_weight_zero_control(tune_baseline, control)

        candidate_refs = []
        load_order = []

        class TrackedArm(dict):
            pass

        def tune_loader(weight):
            gc.collect()
            self.assertTrue(all(reference() is None for reference in candidate_refs))
            arm = TrackedArm(make_arm(weight, "tune", TUNE_DATES))
            candidate_refs.append(weakref.ref(arm))
            load_order.append(weight)
            return arm

        actual_tune = analyze_tune_arms_incremental(
            tune_baseline,
            TUNE_DATES,
            weight_zero_control=compact_control,
            candidate_loader=tune_loader,
        )
        gc.collect()
        self.assertEqual(actual_tune, expected_tune)
        self.assertEqual(load_order, list(SWEEP_WEIGHTS[1:]))
        self.assertTrue(all(reference() is None for reference in candidate_refs))

        holdout_baseline = make_arm(0.0, "holdout", HOLDOUT_DATES)
        expected_holdout = analyze_holdout_arms(
            [
                make_arm(weight, "holdout", HOLDOUT_DATES)
                for weight in (0.0, 0.25, 0.50)
            ],
            HOLDOUT_DATES,
            actual_tune["selected_weights"],
        )
        candidate_refs.clear()
        load_order.clear()

        def holdout_loader(weight):
            gc.collect()
            self.assertTrue(all(reference() is None for reference in candidate_refs))
            arm = TrackedArm(make_arm(weight, "holdout", HOLDOUT_DATES))
            candidate_refs.append(weakref.ref(arm))
            load_order.append(weight)
            return arm

        actual_holdout = analyze_holdout_arms_incremental(
            holdout_baseline,
            HOLDOUT_DATES,
            actual_tune["selected_weights"],
            candidate_loader=holdout_loader,
        )
        gc.collect()
        self.assertEqual(actual_holdout, expected_holdout)
        self.assertEqual(load_order, [0.25, 0.50])
        self.assertTrue(all(reference() is None for reference in candidate_refs))

    def test_resume_accepts_exact_pre_refactor_fingerprint_and_large_arm_size(self):
        self.assertGreater(MAX_CACHE_BYTES, 2_219_661_481)
        entries = [
            {
                "event_slug": "slug-a",
                "target_date": "2026-06-01",
                "market_id": "toronto",
                "snapshot_ids": ["snapshot-a"],
            }
        ]
        manifest = {"corpus_hash": "fixture-corpus"}
        legacy_digest = COMPATIBLE_ARM_CODE_DIGESTS[0]
        fingerprint = cache_fingerprint(
            split="tune",
            weight=0.10,
            manifest=manifest,
            entries=entries,
            code_digest=legacy_digest,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_path = root / "tune-weight-0p10.json"
            arm = make_arm(0.10, "tune", TUNE_DATES)
            cache_path.write_text(
                json.dumps(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "fingerprint": fingerprint,
                        "arm": arm,
                    }
                ),
                encoding="utf-8",
            )
            loaded = load_or_run_arm(
                split="tune",
                weight=0.10,
                entries=entries,
                folders=[],
                manifest=manifest,
                staged_data_root=root,
                cache_root=root,
                code_digest="post-refactor-code-digest",
                resume=True,
            )
            self.assertEqual(loaded, arm)

    def test_scope_effect_is_reported_and_determinism_or_simplex_fail_closed(self):
        baseline = make_arm(0.0, "tune", TUNE_DATES)
        candidate = make_arm(0.25, "tune", TUNE_DATES)
        effect = scope_effect_audit(
            baseline["distribution_rows"], candidate["distribution_rows"]
        )
        self.assertEqual(effect["status"], "PASS")
        self.assertGreater(effect["windows"]["00-06"]["changed_exact"], 0)

        control = make_arm(0.0, "tune-determinism-control", TUNE_DATES[:1])
        control["rows"][0]["replayed_p"] += 0.01
        determinism = exact_determinism_gate(baseline, control)
        self.assertEqual(determinism["status"], "BLOCK")
        self.assertGreater(determinism["row_mismatches"], 0)

        bad = make_arm(0.25, "tune", TUNE_DATES, bad_mass=True)
        mass = mass_gate(bad["distribution_rows"])
        self.assertEqual(mass["status"], "BLOCK")
        self.assertGreater(mass["violations"], 0)

    def test_scoring_equivalent_duplicates_collapse_but_conflicts_block(self):
        baseline = make_arm(0.0, "tune", TUNE_DATES)
        candidate = make_arm(0.25, "tune", TUNE_DATES)
        baseline_duplicate = dict(baseline["rows"][0])
        baseline_duplicate["recorded_p"] = 0.11
        candidate_duplicate = dict(candidate["rows"][0])
        candidate_duplicate["recorded_p"] = 0.89
        baseline["rows"].append(baseline_duplicate)
        candidate["rows"].append(candidate_duplicate)

        equivalent = alignment_gate(baseline["rows"], candidate["rows"])
        self.assertEqual(equivalent["status"], "PASS")
        self.assertEqual(equivalent["baseline_rows"], len(baseline["rows"]) - 1)

        conflict = dict(candidate_duplicate)
        conflict["replayed_p"] += 0.01
        candidate["rows"].append(conflict)
        blocked = alignment_gate(baseline["rows"], candidate["rows"])
        self.assertEqual(blocked["status"], "BLOCK")
        self.assertTrue(
            any("conflicting duplicate comparison key" in item for item in blocked["blockers"])
        )

    def test_weight_zero_determinism_is_nan_safe(self):
        baseline = make_arm(0.0, "tune", TUNE_DATES)
        control = make_arm(0.0, "tune-determinism-control", TUNE_DATES[:1])
        for row in baseline["rows"]:
            if row["target_date"] == TUNE_DATES[0]:
                row["feature_missing"] = math.nan
        for row in control["rows"]:
            row["feature_missing"] = math.nan

        determinism = exact_determinism_gate(baseline, control)
        self.assertEqual(determinism["status"], "PASS")
        self.assertEqual(determinism["row_mismatches"], 0)

    def test_bootstrap_is_deterministic_and_report_labels_research_only(self):
        first = cluster_bootstrap_ci([-0.1, -0.2, 0.05], seed=42, replicates=500)
        second = cluster_bootstrap_ci([-0.1, -0.2, 0.05], seed=42, replicates=500)
        self.assertEqual(first, second)

        tune = analyze_tune_arms(
            [make_arm(weight, "tune", TUNE_DATES) for weight in SWEEP_WEIGHTS],
            TUNE_DATES,
            baseline_control=make_arm(
                0.0, "tune-determinism-control", TUNE_DATES[:1]
            ),
        )
        holdout = analyze_holdout_arms(
            [make_arm(weight, "holdout", HOLDOUT_DATES) for weight in (0.0, 0.25, 0.50)],
            HOLDOUT_DATES,
            tune["selected_weights"],
        )
        payload = {
            "generated_at_utc": "2026-07-22T00:00:00+00:00",
            "status": "COMPLETE",
            "technical_blockers": [],
            "inputs": {"opened_read_only": True},
            "outputs": {"outside_input_data_roots": True},
            "split": {"tune_dates": list(TUNE_DATES), "holdout_dates": list(HOLDOUT_DATES)},
            "tune": tune,
            "holdout": holdout,
        }
        report = render_report(payload)
        self.assertIn("research-only", report)
        self.assertIn("native settlement units", report)
        self.assertIn("Paired Fleet-Date Results", report)


if __name__ == "__main__":
    unittest.main()
