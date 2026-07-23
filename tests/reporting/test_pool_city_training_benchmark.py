from __future__ import annotations

import json
from datetime import date, timedelta
import os
from pathlib import Path
import subprocess

import pytest

from weather.calibration.pooled_feature_model import (
    DENSITY_DEFAULT_SHAPE,
    add_city_features,
    canonical_density_records,
    canonical_grid_f,
    density_support_f,
    evaluate_density_sigma,
)
from weather.market.market_registry import NYC, TORONTO
from weather.reporting.research import pool_city_training_benchmark as benchmark
from weather.schema_registry import schema_version


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


def _panel_row(market_id: str, target_date: str, hour: int):
    return {
        "market_id": market_id,
        "date": date.fromisoformat(target_date),
        "cutoff_hour": hour,
    }


def test_balanced_panel_and_chronological_split_exclude_incomplete_date():
    rows = []
    for target_date in ("2023-07-15", "2024-07-15", "2025-07-15"):
        for market_id in ("a", "b"):
            for hour in (7, 8):
                rows.append(_panel_row(market_id, target_date, hour))
    rows.append(_panel_row("a", "2025-07-16", 7))

    panel = benchmark.complete_panel_dates(
        rows,
        markets=("a", "b"),
        hours=(7, 8),
        start_year=2023,
        end_year=2025,
    )
    splits = benchmark.chronological_splits(
        panel,
        development_year=2024,
        confirmation_year=2025,
    )

    assert panel == ["2023-07-15", "2024-07-15", "2025-07-15"]
    assert splits == {
        "train": ["2023-07-15"],
        "development": ["2024-07-15"],
        "confirmation": ["2025-07-15"],
    }


def _native_record(spec, *, target_date: date, index: int, hour: int = 14):
    if spec.display_unit == "C":
        high = 22.0 + (index % 4)
        final = int(high + (index % 3))
        climate = {"climate_normal": 24.0, "climate_std": 3.0}
    else:
        high = 72.0 + (index % 7)
        final = int(high + (index % 3))
        climate = {"climate_normal": 78.0, "climate_std": 5.0}
    row = {
        "date": target_date,
        "target_date": target_date.isoformat(),
        "high_so_far": high,
        "current_temp": high - 0.5,
        "rise_from_7am": 6.0,
        "warming_rate_2h": 1.0,
        "hours_at_peak": 0.5,
        "dewpoint_c": high - 5.0,
        "humidity": 55.0,
        "pressure": 29.9,
        "pressure_trend_3h": -0.1,
        "wind_speed_kmh": 10.0,
        "forecast_high": final + 0.5,
        "forecast_gap": final + 0.5 - high,
        "minutes_since_cutoff": 30.0,
        "live_reading_temp": high - 0.25,
        "live_reading_minus_high": -0.25,
        "wind_group": "S-SW",
        "cloud_group": "Fair/clear",
        "final_bucket": final,
        "cutoff_hour": hour,
        "year": target_date.year,
    }
    return add_city_features(row, spec, climate)


def test_fast_memory_bounded_score_matches_canonical_density_score():
    native = [
        _native_record(TORONTO, target_date=date(2025, 7, 15), index=0),
        _native_record(NYC, target_date=date(2025, 7, 15), index=1),
    ]
    rows = canonical_density_records(native)
    means = [rows[0]["final_bucket_f"] - 1.1, rows[1]["final_bucket_f"] + 0.7]
    low_f, high_f = density_support_f(rows)
    grid_f = canonical_grid_f(low_f, high_f, 0.1)
    dependencies = benchmark._dependencies()

    expected = evaluate_density_sigma(
        rows,
        means,
        grid_f,
        2.25,
        shape_config=DENSITY_DEFAULT_SHAPE,
    )
    actual, scored = benchmark.score_rows(
        rows,
        means,
        grid_f=grid_f,
        sigma_f=2.25,
        shape_config=DENSITY_DEFAULT_SHAPE,
        dependencies=dependencies,
    )

    assert len(scored) == 2
    assert {row["unit"] for row in scored} == {"C", "F"}
    for metric in (
        "density_logloss",
        "winning_bucket_brier",
        "mean_absolute_error_f",
        "market_band_brier",
        "market_band_logloss",
    ):
        assert actual[metric] == pytest.approx(expected[metric], abs=1e-12)
    assert actual["market_band_rows"] == expected["market_band_rows"]


def _benchmark_rows():
    rows = {"train": [], "development": [], "confirmation": []}
    for split, year, count in (
        ("train", 2020, 30),
        ("development", 2024, 5),
        ("confirmation", 2025, 5),
    ):
        for index in range(count):
            target_date = date(year, 7, 1) + timedelta(days=index)
            rows[split].append(_native_record(TORONTO, target_date=target_date, index=index))
            rows[split].append(_native_record(NYC, target_date=target_date, index=index + 1))
    return {
        split: canonical_density_records(values)
        for split, values in rows.items()
    }


def test_loco_task_excludes_target_from_training_and_tuning_but_scores_it():
    dependencies = benchmark._dependencies()
    rows = _benchmark_rows()
    contracts = benchmark.feature_contracts(rows["train"], (14,), dependencies)
    low_f, high_f = density_support_f(rows["train"])
    grid_f = canonical_grid_f(low_f, high_f, 0.5)
    task = {
        "task_id": "loco__toronto__h14",
        "regime": "loco",
        "market_id": "toronto",
        "hour": 14,
    }

    result = benchmark.fit_task(
        task,
        rows_by_split=rows,
        feature_contract=contracts[14],
        grid_f=grid_f,
        dependencies=dependencies,
    )

    assert result["training_markets"] == ["nyc"]
    assert result["tuning_markets"] == ["nyc"]
    assert result["trainer"]["parameters"] == {
        "max_iter": 120,
        "max_leaf_nodes": 31,
        "learning_rate": 0.05,
        "random_state": 42,
    }
    assert result["trainer"]["callable"] == (
        "weather.calibration.pooled_feature_model.train_density_hour_model"
    )
    assert result["feature_contract_sha256"] == contracts[14]["sha256"]
    assert {row["market_id"] for row in result["scored_rows"]} == {"toronto"}
    assert {row["split"] for row in result["scored_rows"]} == {
        "development",
        "confirmation",
    }


def test_task_inventory_has_exact_three_regime_model_counts():
    tasks = benchmark.task_specs(("a", "b", "c"), (7, 8))
    assert len(tasks) == 2 * (1 + 3 + 3)
    assert sum(task["regime"] == "pooled" for task in tasks) == 2
    assert sum(task["regime"] == "per_city" for task in tasks) == 6
    assert sum(task["regime"] == "loco" for task in tasks) == 6


def test_paired_fleet_date_summary_is_deterministic_and_sign_aware():
    left = {f"2025-07-{day:02d}": 0.10 + day / 1000 for day in range(1, 9)}
    right = {target_date: value + 0.01 for target_date, value in left.items()}

    first = benchmark.paired_cluster_summary(
        left,
        right,
        bootstrap_replicates=500,
        seed=42,
    )
    second = benchmark.paired_cluster_summary(
        left,
        right,
        bootstrap_replicates=500,
        seed=42,
    )

    assert first == second
    assert first["paired_dates"] == 8
    assert first["left_better_dates"] == 8
    assert first["right_better_dates"] == 0
    assert first["mean_delta"] == pytest.approx(-0.01)
    assert first["two_sided_exact_sign_p"] == pytest.approx(2 / 256)


def test_checkpoint_identity_mismatch_fails_closed(tmp_path):
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(
        json.dumps({"run_id": "old", "task_id": "task"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="identity mismatch"):
        benchmark.load_checkpoint(checkpoint, run_id="new", task_id="task")


def test_checkpoint_status_is_authoritative_for_resume_accounting(tmp_path):
    status_path = tmp_path / "checkpoint_status.json"
    status = {
        "schema_version": "pool_city_checkpoint_status_v0.1",
        "run_id": "stable-run",
        "completed_tasks": 3,
        "total_tasks": 3,
        "resumed_tasks": 1,
    }
    status_path.write_text(json.dumps(status), encoding="utf-8")

    loaded = benchmark.load_authoritative_checkpoint_status(
        status_path,
        run_id="stable-run",
        expected_tasks=3,
    )
    assert loaded["resumed_tasks"] == 1

    status["resumed_tasks"] = 4
    status_path.write_text(json.dumps(status), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid resumed_tasks"):
        benchmark.load_authoritative_checkpoint_status(
            status_path,
            run_id="stable-run",
            expected_tasks=3,
        )

    status["resumed_tasks"] = 1
    status["completed_tasks"] = 2
    status_path.write_text(json.dumps(status), encoding="utf-8")
    with pytest.raises(ValueError, match="not complete"):
        benchmark.load_authoritative_checkpoint_status(
            status_path,
            run_id="stable-run",
            expected_tasks=3,
        )


def test_corpus_contract_explicitly_excludes_runtime_timing():
    first = {
        "panel_contract": "balanced",
        "input_manifest_sha256": "abc",
        "corpus_contract_excludes": ["non_contractual_runtime"],
        "non_contractual_runtime": {"load_seconds": 1.25},
    }
    second = {
        **first,
        "non_contractual_runtime": {"load_seconds": 99.0},
    }

    assert benchmark.corpus_contract_sha256(first) == benchmark.corpus_contract_sha256(second)
    second["input_manifest_sha256"] = "changed"
    assert benchmark.corpus_contract_sha256(first) != benchmark.corpus_contract_sha256(second)


def test_scratch_output_rejects_data_subtree_before_mkdir(tmp_path, monkeypatch):
    from weather import paths as weather_paths

    repo_root = tmp_path / "repo"
    data_root = repo_root / "data"
    data_root.mkdir(parents=True)
    monkeypatch.setattr(weather_paths, "REPO_ROOT", repo_root)
    unsafe = data_root / "scratch" / "pool-city"

    with pytest.raises(ValueError, match="inside the supplied read-only data root"):
        benchmark.ensure_scratch_output(unsafe, data_root=data_root)
    assert not unsafe.exists()


def test_scratch_output_rejects_junction_alias_into_data_root(tmp_path, monkeypatch):
    from weather import paths as weather_paths

    repo_root = tmp_path / "repo"
    data_root = repo_root / "data"
    scratch_root = repo_root / "scratch"
    data_root.mkdir(parents=True)
    scratch_root.mkdir()
    monkeypatch.setattr(weather_paths, "REPO_ROOT", repo_root)
    alias = scratch_root / "mirror-alias"
    _make_directory_alias(alias, data_root)
    unsafe = alias / "pool-city"

    with pytest.raises(ValueError, match="inside the supplied read-only data root"):
        benchmark.ensure_scratch_output(unsafe, data_root=data_root)
    assert not (data_root / "pool-city").exists()


def test_scratch_output_allows_resolved_repo_scratch_path(tmp_path, monkeypatch):
    from weather import paths as weather_paths

    repo_root = tmp_path / "repo"
    data_root = repo_root / "data"
    data_root.mkdir(parents=True)
    monkeypatch.setattr(weather_paths, "REPO_ROOT", repo_root)
    output = repo_root / "scratch" / "pool-city"

    assert benchmark.ensure_scratch_output(output, data_root=data_root) == output.resolve()
    assert output.is_dir()


def test_schema_is_registered():
    assert benchmark.SCHEMA_VERSION == "pool_city_training_benchmark_v0.1"
    assert schema_version("pool_city_training_benchmark") == benchmark.SCHEMA_VERSION
    assert schema_version("balanced_market_date_hour_panel") == "balanced_market_date_hour_panel_v1"
    assert schema_version("pool_city_checkpoint_status") == "pool_city_checkpoint_status_v0.1"
    assert schema_version("pool_city_input_manifest") == "pool_city_input_manifest_v0.1"
    assert schema_version("pool_city_runtime_plan") == "pool_city_runtime_plan_v0.1"
