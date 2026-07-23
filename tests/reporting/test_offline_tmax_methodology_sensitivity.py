from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest

from weather.reporting.research import offline_tmax_methodology_sensitivity as sensitivity
from weather.reporting.research.offline_tmax_methodology_sensitivity import (
    _bootstrap,
    _weighted_metrics,
    analyze,
)


def _make_directory_alias(alias: Path, target: Path) -> None:
    try:
        alias.symlink_to(target, target_is_directory=True)
        return
    except (NotImplementedError, OSError) as symlink_error:
        if os.name == "nt":
            junction = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(alias), str(target)],
                capture_output=True,
                text=True,
                check=False,
            )
            if junction.returncode == 0:
                return
        pytest.skip(f"directory aliases unavailable: {symlink_error}")


def _payload():
    rows = [
        {
            "target_date": "2026-05-10",
            "market_dates": 12,
            "baseline_mae_c": 1.0,
            "variant_mae_c": 0.8,
            "mae_delta_c": -0.2,
            "baseline_rmse_c": 1.2,
            "variant_rmse_c": 1.0,
            "rmse_delta_c": -0.2,
        },
        {
            "target_date": "2026-05-11",
            "market_dates": 6,
            "baseline_mae_c": 1.0,
            "variant_mae_c": 1.3,
            "mae_delta_c": 0.3,
            "baseline_rmse_c": 1.2,
            "variant_rmse_c": 1.5,
            "rmse_delta_c": 0.3,
        },
    ]
    point = _weighted_metrics(rows)
    bootstrap = _bootstrap(
        rows, seed=17, replicates=100, metric_fn=_weighted_metrics
    )
    return {
        "experiment": {
            "family": "radiation",
            "market_ids": [f"market-{index}" for index in range(12)],
            "bootstrap_seed": 17,
        },
        "evaluation": {
            "holdout": {
                "metrics": {
                    **point,
                    "fleet_date_cluster_bootstrap": bootstrap,
                    "paired_fleet_date_errors": rows,
                }
            }
        },
    }


def test_sensitivity_reproduces_primary_and_separates_estimands():
    result = analyze(_payload(), sensitivity_replicates=200, sensitivity_seed=23)

    assert result["primary_reproduction"]["status"] == "PASS"
    assert result["primary_reproduction"]["max_absolute_difference"] <= 1e-12
    assert result["primary_verbatim"]["point"]["mae_delta_c"] == pytest.approx(
        -1 / 30
    )
    assert result["equal_fleet_date_sensitivity"]["point"]["mae_delta_c"] == pytest.approx(
        0.05
    )
    complete = result["exact_complete_fleet_date_sensitivity"]
    assert complete["included_fleet_dates"] == 1
    assert complete["excluded_incomplete_fleet_dates"] == 1
    assert complete["point"]["mae_delta_c"] == pytest.approx(-0.2)
    assert result["no_refit"] is True
    assert result["raw_outcomes_read"] is False


def test_sensitivity_requires_sealed_date_summaries():
    with pytest.raises(ValueError, match="no sealed holdout"):
        analyze({"evaluation": {"holdout": {"metrics": {}}}})


def test_run_rejects_direct_output_below_read_only_data_root(tmp_path):
    data_root = tmp_path / "mirror"
    data_root.mkdir()
    evaluation = tmp_path / "evaluation.json"
    evaluation.write_text("{}", encoding="utf-8")
    output = data_root / "analysis" / "sensitivity.json"
    args = sensitivity.build_parser().parse_args(
        [
            "--read-only-data-root",
            str(data_root),
            "--evaluation",
            str(evaluation),
            "--out",
            str(output),
        ]
    )

    with pytest.raises(ValueError, match="out resolves inside"):
        sensitivity.run(args)
    assert not output.exists()


def test_run_rejects_junction_aliased_output_below_read_only_data_root(tmp_path):
    data_root = tmp_path / "mirror"
    data_root.mkdir()
    alias = tmp_path / "mirror-alias"
    _make_directory_alias(alias, data_root)
    evaluation = tmp_path / "evaluation.json"
    evaluation.write_text("{}", encoding="utf-8")
    output = alias / "analysis" / "sensitivity.json"
    args = sensitivity.build_parser().parse_args(
        [
            "--read-only-data-root",
            str(data_root),
            "--evaluation",
            str(evaluation),
            "--out",
            str(output),
        ]
    )

    with pytest.raises(ValueError, match="out resolves inside"):
        sensitivity.run(args)
    assert not (data_root / "analysis" / "sensitivity.json").exists()


def test_run_rejects_hardlink_output_to_evaluation_artifact(tmp_path):
    data_root = tmp_path / "mirror"
    data_root.mkdir()
    evaluation = tmp_path / "evaluation.json"
    original = json.dumps(_payload(), sort_keys=True)
    evaluation.write_text(original, encoding="utf-8")
    output = tmp_path / "sensitivity.json"
    try:
        os.link(evaluation, output)
    except OSError as exc:
        pytest.skip(f"hard links unavailable: {exc}")
    args = sensitivity.build_parser().parse_args(
        [
            "--read-only-data-root",
            str(data_root),
            "--evaluation",
            str(evaluation),
            "--out",
            str(output),
            "--replicates",
            "10",
        ]
    )

    with pytest.raises(ValueError, match="must not overwrite the evaluation"):
        sensitivity.run(args)
    assert evaluation.read_text(encoding="utf-8") == original
