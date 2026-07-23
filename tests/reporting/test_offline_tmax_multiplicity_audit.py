from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest

from weather.reporting.research import offline_tmax_multiplicity_audit as multiplicity
from weather.reporting.research.offline_tmax_multiplicity_audit import (
    analyze,
    clustered_sign_flip_pvalue,
    holm_adjust,
    stable_family_seed,
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


def test_clustered_sign_flip_targets_weighted_primary_delta():
    rows = [
        {"market_dates": 12, "mae_delta_c": -0.2},
        {"market_dates": 6, "mae_delta_c": 0.1},
    ]
    result = clustered_sign_flip_pvalue(rows, replicates=1000, seed=7)
    assert result["observed_mae_delta_c"] == pytest.approx(-0.1)
    assert 0.0 < result["p_two_sided"] <= 1.0
    assert result["cluster_unit"] == "fleet_target_date"


def test_holm_adjustment_is_monotone_and_labels_rejections():
    adjusted = holm_adjust({"a": 0.001, "b": 0.02, "c": 0.5})
    assert adjusted["a"]["holm_adjusted_p"] == pytest.approx(0.003)
    assert adjusted["b"]["holm_adjusted_p"] == pytest.approx(0.04)
    assert adjusted["c"]["holm_adjusted_p"] == pytest.approx(0.5)
    assert adjusted["a"]["reject_fwer_0_05"] is True
    assert adjusted["b"]["reject_fwer_0_05"] is True
    assert adjusted["c"]["reject_fwer_0_05"] is False


def _evaluation_payload(mae_deltas):
    rows = [
        {
            "market_dates": 12,
            "mae_delta_c": delta,
        }
        for delta in mae_deltas
    ]
    primary = sum(row["mae_delta_c"] * row["market_dates"] for row in rows) / sum(
        row["market_dates"] for row in rows
    )
    return {
        "experiment": {"family": "test"},
        "evaluation": {
            "holdout": {
                "metrics": {
                    "fleet_dates": len(rows),
                    "market_dates": sum(row["market_dates"] for row in rows),
                    "mae_delta_c": primary,
                    "rmse_delta_c": primary,
                    "paired_fleet_date_errors": rows,
                    "fleet_date_cluster_bootstrap": {
                        "replicates": 100,
                        "seed": 7,
                        "mae_delta_c_95ci": {"low": -0.2, "high": 0.2},
                        "rmse_delta_c_95ci": {"low": -0.2, "high": 0.2},
                    },
                }
            }
        },
    }


def test_analysis_is_permutation_invariant(tmp_path, monkeypatch):
    alpha_path = tmp_path / "alpha.json"
    beta_path = tmp_path / "beta.json"
    alpha_path.write_text("alpha", encoding="utf-8")
    beta_path.write_text("beta", encoding="utf-8")
    alpha = (alpha_path, _evaluation_payload([-0.2, 0.1, -0.1]))
    beta = (beta_path, _evaluation_payload([0.2, -0.1, 0.3]))
    monkeypatch.setattr(multiplicity, "utc_iso", lambda: "2026-07-22T00:00:00+00:00")

    forward = analyze({"alpha": alpha, "beta": beta}, replicates=1000, seed=29)
    reverse = analyze({"beta": beta, "alpha": alpha}, replicates=1000, seed=29)

    assert forward == reverse
    assert [item["label"] for item in forward["families"]] == ["alpha", "beta"]
    assert stable_family_seed(29, "alpha") == stable_family_seed(29, "alpha")
    assert stable_family_seed(29, "alpha") != stable_family_seed(29, "beta")


def test_run_rejects_direct_output_below_read_only_data_root(tmp_path):
    data_root = tmp_path / "mirror"
    data_root.mkdir()
    evaluation = tmp_path / "evaluation.json"
    evaluation.write_text("{}", encoding="utf-8")
    output = data_root / "analysis" / "multiplicity.json"
    args = multiplicity.build_parser().parse_args(
        [
            "--read-only-data-root",
            str(data_root),
            "--evaluation",
            f"candidate={evaluation}",
            "--out",
            str(output),
        ]
    )

    with pytest.raises(ValueError, match="out resolves inside"):
        multiplicity.run(args)
    assert not output.exists()


def test_run_rejects_junction_aliased_output_below_read_only_data_root(tmp_path):
    data_root = tmp_path / "mirror"
    data_root.mkdir()
    alias = tmp_path / "mirror-alias"
    _make_directory_alias(alias, data_root)
    evaluation = tmp_path / "evaluation.json"
    evaluation.write_text("{}", encoding="utf-8")
    output = alias / "analysis" / "multiplicity.json"
    args = multiplicity.build_parser().parse_args(
        [
            "--read-only-data-root",
            str(data_root),
            "--evaluation",
            f"candidate={evaluation}",
            "--out",
            str(output),
        ]
    )

    with pytest.raises(ValueError, match="out resolves inside"):
        multiplicity.run(args)
    assert not (data_root / "analysis" / "multiplicity.json").exists()


def test_run_rejects_output_equal_to_evaluation_artifact(tmp_path):
    data_root = tmp_path / "mirror"
    data_root.mkdir()
    evaluation = tmp_path / "evaluation.json"
    original = "{}"
    evaluation.write_text(original, encoding="utf-8")
    args = multiplicity.build_parser().parse_args(
        [
            "--read-only-data-root",
            str(data_root),
            "--evaluation",
            f"candidate={evaluation}",
            "--out",
            str(evaluation),
        ]
    )

    with pytest.raises(ValueError, match="must not overwrite an evaluation"):
        multiplicity.run(args)
    assert evaluation.read_text(encoding="utf-8") == original


def test_run_rejects_aliased_output_equal_to_evaluation_artifact(tmp_path):
    data_root = tmp_path / "mirror"
    data_root.mkdir()
    sealed_root = tmp_path / "sealed"
    sealed_root.mkdir()
    alias = tmp_path / "sealed-alias"
    _make_directory_alias(alias, sealed_root)
    evaluation = sealed_root / "evaluation.json"
    original = "{}"
    evaluation.write_text(original, encoding="utf-8")
    args = multiplicity.build_parser().parse_args(
        [
            "--read-only-data-root",
            str(data_root),
            "--evaluation",
            f"candidate={evaluation}",
            "--out",
            str(alias / "evaluation.json"),
        ]
    )

    with pytest.raises(ValueError, match="must not overwrite an evaluation"):
        multiplicity.run(args)
    assert evaluation.read_text(encoding="utf-8") == original


def test_run_rejects_hardlink_output_to_evaluation_artifact(tmp_path):
    data_root = tmp_path / "mirror"
    data_root.mkdir()
    evaluation = tmp_path / "evaluation.json"
    original = json.dumps(_evaluation_payload([-0.2, 0.1]), sort_keys=True)
    evaluation.write_text(original, encoding="utf-8")
    output = tmp_path / "multiplicity.json"
    try:
        os.link(evaluation, output)
    except OSError as exc:
        pytest.skip(f"hard links unavailable: {exc}")
    args = multiplicity.build_parser().parse_args(
        [
            "--read-only-data-root",
            str(data_root),
            "--evaluation",
            f"candidate={evaluation}",
            "--out",
            str(output),
            "--replicates",
            "10",
        ]
    )

    with pytest.raises(ValueError, match="must not overwrite an evaluation"):
        multiplicity.run(args)
    assert evaluation.read_text(encoding="utf-8") == original
