import json
import os
import subprocess
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from weather.model.calibration_runtime import ordinal_smooth_distribution
from weather.reporting.research.ordinal_smoothing_physical_refinement import (
    ExperimentConfigurationError,
    PHYSICAL_C_SIGMA_ANCHORS,
    evaluate_cache_pair,
    grouped_scoring_rows,
    native_sigma,
    project_band,
    read_tune_dates,
    render_report,
    run_experiment,
    select_family_sigmas,
    validate_path_contract,
)
from weather.schema_registry import schema_version


H1_SCHEMA_VERSION = schema_version("ordinal_smoothing_sweep")


def _distribution(market_id, unit, probabilities):
    return {
        "market_id": market_id,
        "target_date": "2026-06-03",
        "snapshot_id": f"{market_id}-snapshot",
        "captured_at_local": "2026-06-03T12:00:00-04:00",
        "capture_minute": 720,
        "cutoff_hour": 12,
        "unit": unit,
        "distribution": {str(key): value for key, value in probabilities.items()},
    }


def _rows(distribution, *, duplicate=False):
    probabilities = {int(k): float(v) for k, v in distribution["distribution"].items()}
    output = []
    for bucket in sorted(probabilities):
        output.append(
            {
                "market_id": distribution["market_id"],
                "target_date": distribution["target_date"],
                "snapshot_id": distribution["snapshot_id"],
                "captured_at_local": distribution["captured_at_local"],
                "band": f"{bucket} {distribution['unit']}",
                "bin_type": "eq",
                "bin_value_c": float(bucket),
                "bin_value_hi": float(bucket),
                "unit": distribution["unit"],
                "outcome": int(bucket == 2),
                "market_yes": 1.0 / 3.0,
                "replayed_p": probabilities[bucket],
            }
        )
    if duplicate:
        output.insert(1, dict(output[0]))
    return output


def _write_cache(path, *, weight, distributions, rows):
    payload = {
        "schema_version": H1_SCHEMA_VERSION,
        "fingerprint": ("a" if weight == 0.0 else "b") * 64,
        "arm": {
            "distribution_rows": distributions,
            "rows": rows,
            "sigma": 0.75,
            "split": "tune",
            "weight": weight,
        },
    }
    path.write_text(
        json.dumps(payload, separators=(",", ":"), sort_keys=True), encoding="utf-8"
    )


def _cache_pair(root):
    base = {0: 0.85, 1: 0.10, 2: 0.05}
    w0_distributions = [
        _distribution("c-market", "C", base),
        _distribution("f-market", "F", base),
    ]
    w1_distributions = []
    for row in w0_distributions:
        smoothed = ordinal_smooth_distribution(
            row["distribution"], sigma=0.75, blend_weight=1.0
        )
        w1_distributions.append(
            _distribution(row["market_id"], row["unit"], smoothed)
        )
    w0_rows = []
    w1_rows = []
    for w0, w1 in zip(w0_distributions, w1_distributions):
        w0_rows.extend(_rows(w0, duplicate=True))
        w1_rows.extend(_rows(w1, duplicate=True))
    w0_path = root / "tune-weight-0p00.json"
    w1_path = root / "tune-weight-1p00.json"
    _write_cache(w0_path, weight=0.0, distributions=w0_distributions, rows=w0_rows)
    _write_cache(w1_path, weight=1.0, distributions=w1_distributions, rows=w1_rows)
    return w0_path, w1_path


class PhysicalRefinementUnitTests(unittest.TestCase):
    def test_preregistered_native_mapping(self):
        self.assertEqual(PHYSICAL_C_SIGMA_ANCHORS, (0.25, 0.5, 0.75, 1.0, 1.25))
        self.assertEqual(native_sigma(0.75, "C"), 0.75)
        self.assertAlmostEqual(native_sigma(0.75, "F"), 1.35)
        with self.assertRaises(ExperimentConfigurationError):
            native_sigma(0.60, "C")
        with self.assertRaises(ExperimentConfigurationError):
            native_sigma(0.75, "K")

    def test_band_projection_supports_observed_contract(self):
        distribution = {0: 0.2, 1: 0.3, 2: 0.5}
        self.assertAlmostEqual(
            project_band(distribution, {"bin_type": "eq", "bin_value_c": 1}), 0.3
        )
        self.assertAlmostEqual(
            project_band(distribution, {"bin_type": "lte", "bin_value_c": 1}), 0.5
        )
        self.assertAlmostEqual(
            project_band(distribution, {"bin_type": "gte", "bin_value_c": 1}), 0.8
        )
        with self.assertRaises(ExperimentConfigurationError):
            project_band(distribution, {"bin_type": "range", "bin_value_c": 1})

    def test_grouped_rows_deduplicate_only_equivalent_scoring_inputs(self):
        distribution = _distribution("c-market", "C", {0: 0.5, 1: 0.5})
        rows = _rows(distribution, duplicate=True)
        groups = list(grouped_scoring_rows(rows))
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0][1]), 2)
        self.assertEqual(groups[0][2], 1)
        conflict = list(rows)
        conflict[1] = dict(conflict[1], outcome=1)
        with self.assertRaises(ExperimentConfigurationError):
            list(grouped_scoring_rows(conflict))

    def test_selection_requires_both_metrics_and_uses_declared_tiebreak(self):
        summaries = {
            unit: [
                {
                    "physical_c_sigma": 0.25,
                    "mean_brier_delta_vs_w0": -0.01,
                    "mean_logloss_delta_vs_w0": 0.01,
                },
                {
                    "physical_c_sigma": 0.50,
                    "mean_brier_delta_vs_w0": -0.02,
                    "mean_logloss_delta_vs_w0": -0.01,
                },
                {
                    "physical_c_sigma": 0.75,
                    "mean_brier_delta_vs_w0": -0.015,
                    "mean_logloss_delta_vs_w0": -0.02,
                },
            ]
            for unit in ("C", "F")
        }
        selected, details = select_family_sigmas(summaries)
        self.assertEqual(selected, {"C": 0.5, "F": 0.5})
        self.assertEqual(details["C"]["eligible_physical_c_sigmas"], [0.5, 0.75])


class PhysicalRefinementIntegrationTests(unittest.TestCase):
    def test_cache_pair_reproduces_w1_and_scores_tune_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            w0, w1 = _cache_pair(root)
            result = evaluate_cache_pair(w0, w1, ("2026-06-03",))
        self.assertEqual(result["status"], "PASS")
        parity = result["alignment_and_parity"]
        self.assertEqual(parity["distributions"], 2)
        self.assertEqual(parity["raw_scoring_rows"], 8)
        self.assertEqual(parity["unique_scoring_rows"], 6)
        self.assertEqual(parity["equivalent_duplicate_extras"], 2)
        self.assertLessEqual(parity["maximum_w1_probability_difference"], 1e-12)
        self.assertEqual(parity["projection_mismatches"], 0)
        self.assertEqual(set(result["selected_physical_c_sigmas"]), {"C", "F"})

    def test_cache_pair_blocks_a_nonreproducing_w1(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            w0, w1 = _cache_pair(root)
            payload = json.loads(w1.read_text(encoding="utf-8"))
            payload["arm"]["distribution_rows"][0]["distribution"] = {
                "0": 0.2,
                "1": 0.3,
                "2": 0.5,
            }
            _write_cache(
                w1,
                weight=1.0,
                distributions=payload["arm"]["distribution_rows"],
                rows=payload["arm"]["rows"],
            )
            with self.assertRaisesRegex(
                ExperimentConfigurationError, "does not reproduce"
            ):
                evaluate_cache_pair(w0, w1, ("2026-06-03",))

    def test_path_contract_requires_explicit_output_containment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            w0, w1 = _cache_pair(root)
            dates = root / "dates.txt"
            dates.write_text("2026-06-03\n", encoding="utf-8")
            data_root = root / "data"
            data_root.mkdir()
            output = root / "output"
            with self.assertRaises(ExperimentConfigurationError):
                validate_path_contract(
                    read_only_data_root=data_root,
                    tune_w0_cache=w0,
                    tune_w1_cache=w1,
                    tune_dates_file=dates,
                    output_root=output,
                    json_out=root / "outside.json",
                    report_out=output / "report.md",
                    lock_path=output / "run.lock",
                )

    def test_run_writes_compact_evidence_and_freezes_no_serving_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            w0, w1 = _cache_pair(root)
            dates = root / "dates.txt"
            dates.write_text("2026-06-03\n", encoding="utf-8")
            data_root = root / "data"
            data_root.mkdir()
            output = root / "output"
            args = Namespace(
                read_only_data_root=str(data_root),
                tune_w0_cache=str(w0),
                tune_w1_cache=str(w1),
                tune_dates_file=str(dates),
                output_root=str(output),
                json_out=str(output / "result.json"),
                report_out=str(output / "result.md"),
                lock_path=str(output / "run.lock"),
            )
            payload = run_experiment(args)
            written = json.loads((output / "result.json").read_text(encoding="utf-8"))
            report = (output / "result.md").read_text(encoding="utf-8")
        self.assertEqual(payload["status"], "COMPLETE")
        self.assertEqual(written["disposition"], "FROZEN_TUNE_ONLY_FOR_FUTURE_CONFIRMATION")
        self.assertFalse(written["holdout_opened"])
        self.assertFalse(written["fresh_panel_opened"])
        self.assertFalse(written["serving_changed"])
        self.assertIn("does not open or score an H1 holdout", report)

    def test_path_contract_rejects_direct_output_under_read_only_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            w0, w1 = _cache_pair(root)
            dates = root / "dates.txt"
            dates.write_text("2026-06-03\n", encoding="utf-8")
            data_root = root / "data"
            data_root.mkdir()
            unsafe = data_root / "research-output"
            with self.assertRaisesRegex(
                ExperimentConfigurationError, "inside the read-only data root"
            ):
                validate_path_contract(
                    read_only_data_root=data_root,
                    tune_w0_cache=w0,
                    tune_w1_cache=w1,
                    tune_dates_file=dates,
                    output_root=unsafe,
                    json_out=unsafe / "result.json",
                    report_out=unsafe / "result.md",
                    lock_path=unsafe / "run.lock",
                )
            self.assertFalse(unsafe.exists())

    def test_path_contract_rejects_junction_alias_into_read_only_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            w0, w1 = _cache_pair(root)
            dates = root / "dates.txt"
            dates.write_text("2026-06-03\n", encoding="utf-8")
            data_root = root / "data"
            scratch = root / "scratch"
            data_root.mkdir()
            scratch.mkdir()
            alias = scratch / "data-alias"
            try:
                alias.symlink_to(data_root, target_is_directory=True)
            except (NotImplementedError, OSError) as symlink_error:
                if os.name != "nt":
                    self.skipTest(f"directory alias unavailable: {symlink_error}")
                result = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(alias), str(data_root)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode != 0:
                    self.skipTest(f"directory alias unavailable: {symlink_error}")
            unsafe = alias / "research-output"
            with self.assertRaisesRegex(
                ExperimentConfigurationError, "inside the read-only data root"
            ):
                validate_path_contract(
                    read_only_data_root=data_root,
                    tune_w0_cache=w0,
                    tune_w1_cache=w1,
                    tune_dates_file=dates,
                    output_root=unsafe,
                    json_out=unsafe / "result.json",
                    report_out=unsafe / "result.md",
                    lock_path=unsafe / "run.lock",
                )
            self.assertFalse((data_root / "research-output").exists())

    def test_tune_dates_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dates.txt"
            path.write_text("2026-06-04\n2026-06-03\n", encoding="utf-8")
            with self.assertRaises(ExperimentConfigurationError):
                read_tune_dates(path)

    def test_report_labels_tune_evidence_as_nonpromotional(self):
        payload = {
            "status": "COMPLETE",
            "disposition": "FROZEN_TUNE_ONLY_FOR_FUTURE_CONFIRMATION",
            "experiment": {"tune_dates": ["2026-06-03"]},
            "alignment_and_parity": {},
            "selected_physical_c_sigmas": {},
            "summaries": {"C": [], "F": []},
            "frozen_candidate": {},
        }
        report = render_report(payload)
        self.assertIn("Tune evidence is not holdout support", report)
        self.assertIn("No release or serving artifact was written", report)


if __name__ == "__main__":
    unittest.main()
