from __future__ import annotations

import json
from datetime import date, timedelta
import os
from pathlib import Path
import shutil
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


def test_input_manifest_rejects_file_replaced_after_corpus_read(tmp_path):
    source = tmp_path / "source.csv"
    source.write_text("value\n1\n", encoding="utf-8")
    with benchmark.read_only_path_trace(tmp_path) as trace:
        assert source.read_text(encoding="utf-8") == "value\n1\n"
    source.write_text("value\n222\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="changed between corpus load"):
        benchmark.build_input_manifest(tmp_path, trace)


def test_read_only_trace_captures_builtin_os_and_path_reads_and_denies_writes(tmp_path):
    forecast_daily = tmp_path / "forecast_daily.csv"
    forecast_daily.write_text("value\n1\n", encoding="utf-8")

    with benchmark.read_only_path_trace(tmp_path) as trace:
        with open(forecast_daily, encoding="utf-8") as handle:
            assert handle.read() == "value\n1\n"
        descriptor = os.open(forecast_daily, os.O_RDONLY)
        try:
            assert os.read(descriptor, 5) == b"value"
        finally:
            os.close(descriptor)
        with forecast_daily.open(encoding="utf-8") as handle:
            assert handle.readline() == "value\n"

        with pytest.raises(PermissionError, match="read-only"):
            open(forecast_daily, "w", encoding="utf-8")
        with pytest.raises(PermissionError, match="read-only"):
            os.open(forecast_daily, os.O_WRONLY)
        with pytest.raises(PermissionError, match="read-only"):
            forecast_daily.open("a", encoding="utf-8")
        with pytest.raises(PermissionError, match="descriptor-based"):
            open(0, "r", closefd=False)
        with pytest.raises(PermissionError, match="dir_fd"):
            os.open("forecast_daily.csv", os.O_RDONLY, dir_fd=0)

    manifest = benchmark.build_input_manifest(tmp_path, trace)
    assert manifest["read_only_guard_contract"] == (
        "python_open_and_common_pathname_mutation_v0.2"
    )
    assert manifest["opened_file_count"] == 1
    assert manifest["files"][0]["path"] == "forecast_daily.csv"
    assert manifest["files"][0]["status"] == "read"


def test_read_only_trace_denies_pathname_mutations_but_allows_copy_out(tmp_path):
    data_root = tmp_path / "data"
    scratch_root = tmp_path / "scratch"
    data_root.mkdir()
    scratch_root.mkdir()
    source = data_root / "source.csv"
    source.write_text("value\n1\n", encoding="utf-8")
    external = scratch_root / "external.csv"
    external.write_text("outside\n", encoding="utf-8")

    with benchmark.read_only_path_trace(data_root):
        with pytest.raises(PermissionError, match="Path.unlink"):
            source.unlink()
        with pytest.raises(PermissionError, match="Path.mkdir"):
            (data_root / "new-directory").mkdir()
        with pytest.raises(PermissionError, match="os.rename source"):
            os.rename(source, scratch_root / "moved.csv")
        with pytest.raises(PermissionError, match="os.replace destination"):
            os.replace(external, data_root / "replacement.csv")
        with pytest.raises(PermissionError, match="Path.rename destination"):
            external.rename(data_root / "renamed.csv")
        with pytest.raises(PermissionError, match="Path.replace destination"):
            external.replace(data_root / "replaced.csv")
        with pytest.raises(PermissionError, match="Path.rename destination"):
            external.rename(target=data_root / "renamed-keyword.csv")
        with pytest.raises(PermissionError, match="shutil.copyfile destination"):
            shutil.copyfile(external, data_root / "copied.csv")
        with pytest.raises(PermissionError, match="shutil.rmtree"):
            shutil.rmtree(data_root)

        copied_out = scratch_root / "copied-out.csv"
        shutil.copyfile(source, copied_out)
        assert copied_out.read_text(encoding="utf-8") == "value\n1\n"

    assert source.read_text(encoding="utf-8") == "value\n1\n"
    assert external.read_text(encoding="utf-8") == "outside\n"
    assert not (data_root / "replacement.csv").exists()
    assert not (data_root / "copied.csv").exists()


def test_read_only_trace_denies_lexical_reparse_entry_inside_data(tmp_path):
    data_root = tmp_path / "data"
    scratch_root = tmp_path / "scratch"
    data_root.mkdir()
    scratch_root.mkdir()
    alias = data_root / "outbound-alias"
    _make_directory_alias(alias, scratch_root)

    with benchmark.read_only_path_trace(data_root):
        with pytest.raises(PermissionError, match="Path.rmdir"):
            alias.rmdir()

    assert alias.exists()


def test_balanced_panel_rejects_duplicate_market_date_hour_key():
    rows = [
        _panel_row("a", "2024-07-15", 7),
        _panel_row("a", "2024-07-15", 7),
    ]

    with pytest.raises(ValueError, match="duplicate market/date/hour"):
        benchmark.complete_panel_dates(
            rows,
            markets=("a",),
            hours=(7,),
            start_year=2024,
            end_year=2024,
        )


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


def test_paired_fleet_date_summary_rejects_silent_key_intersection():
    with pytest.raises(ValueError, match="key sets differ"):
        benchmark.paired_cluster_summary(
            {"2025-07-01": 0.1, "2025-07-02": 0.2},
            {"2025-07-01": 0.1},
        )


def _minimal_run_contract(task_contracts):
    run_contract = {
        "contract_version": "pool_city_checkpoint_run_contract_v0.2",
        "run_id": "1" * 64,
        "task_ids": list(task_contracts),
        "corpus_contract_sha256": "2" * 64,
        "input_manifest_sha256": "3" * 64,
        "native_corpus_sha256": {
            "train": "4" * 64,
            "development": "5" * 64,
            "confirmation": "6" * 64,
        },
        "canonical_corpus_sha256": {
            "train": "7" * 64,
            "development": "8" * 64,
            "confirmation": "9" * 64,
        },
        "feature_contracts": {"14": "f" * 64},
        "grid_f_sha256": "a" * 64,
        "grid_points": 10,
        "configuration_sha256": "b" * 64,
        "source_contract_sha256": "a" * 64,
        "source_tree_sha256": "c" * 64,
        "git_identity": {
            "head_commit": "d" * 40,
            "head_tree": "e" * 40,
            "tracked_worktree_status_sha256": "d" * 64,
            "tracked_worktree_dirty": True,
        },
        "task_contracts_sha256": benchmark.payload_sha256(task_contracts),
    }
    run_contract["run_contract_sha256"] = benchmark.self_digest(
        run_contract,
        digest_field="run_contract_sha256",
    )
    return run_contract


def _checkpoint_contract_fixture():
    task = {
        "task_id": "pooled__all__h14",
        "regime": "pooled",
        "market_id": None,
        "hour": 14,
    }
    expected_keys = [
        ("development", "toronto", "2024-07-01", 14),
        ("confirmation", "toronto", "2025-07-01", 14),
    ]
    task_contract = benchmark.build_task_contract(
        task,
        feature_contract_sha256="f" * 64,
        expected_prediction_keys=expected_keys,
    )
    run_contract = _minimal_run_contract({task["task_id"]: task_contract})
    return task, expected_keys, task_contract, run_contract


def _prediction_row(split: str, target_date: str):
    return {
        "target_date": target_date,
        "market_id": "toronto",
        "unit": "C",
        "cutoff_hour": 14,
        "mean_f": 77.0,
        "target_f": 77.0,
        "sigma_f": 2.0,
        "density_logloss": 0.5,
        "winning_bucket_brier": 0.1,
        "mean_absolute_error_f": 0.0,
        "market_band_rows": 3,
        "market_band_weight": 3.0,
        "market_band_brier_sum": 0.3,
        "market_band_logloss_sum": 1.5,
        "regime": "pooled",
        "scored_market_id": "all",
        "split": split,
        "density_shape_id": "gaussian",
        "task_id": "pooled__all__h14",
    }


def _sealed_checkpoint(
    *,
    run_contract,
    task_contract,
    run_id: str | None = None,
    scored_rows=None,
):
    payload = {
        "schema_version": benchmark.CHECKPOINT_SCHEMA_VERSION,
        "run_id": run_id or run_contract["run_id"],
        "run_contract_sha256": run_contract["run_contract_sha256"],
        "task_contract_sha256": task_contract["task_contract_sha256"],
        "completed_at_utc": "2026-07-23T00:00:00+00:00",
        "task_id": "pooled__all__h14",
        "regime": "pooled",
        "market_id": None,
        "hour": 14,
        "feature_contract_sha256": "f" * 64,
        "scored_rows": scored_rows or [
            _prediction_row("development", "2024-07-01"),
            _prediction_row("confirmation", "2025-07-01"),
        ],
    }
    payload[benchmark.CHECKPOINT_DIGEST_FIELD] = benchmark.self_digest(
        payload,
        digest_field=benchmark.CHECKPOINT_DIGEST_FIELD,
    )
    return payload


def _sealed_status(run_contract, *, resumed_tasks=1, completed_tasks=1):
    status = {
        "schema_version": benchmark.CHECKPOINT_STATUS_SCHEMA_VERSION,
        "run_id": run_contract["run_id"],
        "run_contract_sha256": run_contract["run_contract_sha256"],
        "updated_at_utc": "2026-07-23T00:00:00+00:00",
        "completed_tasks": completed_tasks,
        "total_tasks": 1,
        "resumed_tasks": resumed_tasks,
        "completed_task_ids": ["pooled__all__h14"],
        "checkpoint_sha256_by_task": {"pooled__all__h14": "b" * 64},
        "last_task_id": "pooled__all__h14",
        "elapsed_seconds": 1.0,
    }
    status[benchmark.CHECKPOINT_STATUS_DIGEST_FIELD] = benchmark.self_digest(
        status,
        digest_field=benchmark.CHECKPOINT_STATUS_DIGEST_FIELD,
    )
    return status


def test_checkpoint_identity_mismatch_fails_closed(tmp_path):
    task, expected_keys, task_contract, run_contract = _checkpoint_contract_fixture()
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(json.dumps(_sealed_checkpoint(
        run_contract=run_contract,
        task_contract=task_contract,
        run_id="0" * 64,
    )), encoding="utf-8")

    with pytest.raises(ValueError, match="identity mismatch"):
        benchmark.load_checkpoint(
            checkpoint,
            run_contract=run_contract,
            task_contract=task_contract,
            expected_prediction_keys=expected_keys,
        )


def test_checkpoint_rejects_legacy_schema_and_tampered_self_digest(tmp_path):
    _, expected_keys, task_contract, run_contract = _checkpoint_contract_fixture()
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(
        json.dumps({"run_id": "stable-run", "task_id": "pooled__all__h14"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="schema mismatch"):
        benchmark.load_checkpoint(
            checkpoint,
            run_contract=run_contract,
            task_contract=task_contract,
            expected_prediction_keys=expected_keys,
        )

    payload = _sealed_checkpoint(
        run_contract=run_contract,
        task_contract=task_contract,
    )
    payload["scored_rows"][0]["mean_f"] = 999.0
    checkpoint.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="self-digest mismatch"):
        benchmark.load_checkpoint(
            checkpoint,
            run_contract=run_contract,
            task_contract=task_contract,
            expected_prediction_keys=expected_keys,
        )


def test_checkpoint_rejects_duplicate_malformed_or_mismatched_prediction_keys(tmp_path):
    _, expected_keys, task_contract, run_contract = _checkpoint_contract_fixture()
    checkpoint = tmp_path / "checkpoint.json"

    duplicate = _prediction_row("development", "2024-07-01")
    payload = _sealed_checkpoint(
        run_contract=run_contract,
        task_contract=task_contract,
        scored_rows=[duplicate, dict(duplicate)],
    )
    checkpoint.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicates"):
        benchmark.load_checkpoint(
            checkpoint,
            run_contract=run_contract,
            task_contract=task_contract,
            expected_prediction_keys=expected_keys,
        )

    malformed = _prediction_row("development", "2024-07-01")
    malformed["target_date"] = "2024-07-01T00:00:00"
    payload = _sealed_checkpoint(
        run_contract=run_contract,
        task_contract=task_contract,
        scored_rows=[
            malformed,
            _prediction_row("confirmation", "2025-07-01"),
        ],
    )
    checkpoint.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="malformed prediction target_date"):
        benchmark.load_checkpoint(
            checkpoint,
            run_contract=run_contract,
            task_contract=task_contract,
            expected_prediction_keys=expected_keys,
        )

    wrong_split = _prediction_row("confirmation", "2024-07-01")
    payload = _sealed_checkpoint(
        run_contract=run_contract,
        task_contract=task_contract,
        scored_rows=[
            wrong_split,
            _prediction_row("confirmation", "2025-07-01"),
        ],
    )
    checkpoint.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="key set mismatch"):
        benchmark.load_checkpoint(
            checkpoint,
            run_contract=run_contract,
            task_contract=task_contract,
            expected_prediction_keys=expected_keys,
        )


def test_checkpoint_strict_json_rejects_duplicate_object_keys(tmp_path):
    _, expected_keys, task_contract, run_contract = _checkpoint_contract_fixture()
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(
        '{"schema_version":"pool_city_task_checkpoint_v0.2",'
        '"run_id":"111","run_id":"replacement"}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate JSON object key"):
        benchmark.load_checkpoint(
            checkpoint,
            run_contract=run_contract,
            task_contract=task_contract,
            expected_prediction_keys=expected_keys,
        )


def test_strict_json_rejects_overflow_numbers_before_digest_validation(tmp_path):
    artifact = tmp_path / "overflow.json"
    artifact.write_text(
        '{"status":{"elapsed_seconds":1e999}}',
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=r"non-finite JSON number at \$\.status\.elapsed_seconds",
    ):
        benchmark.load_json_mapping_strict(
            artifact,
            label="overflow fixture",
        )


def test_checkpoint_status_is_authoritative_for_resume_accounting(tmp_path):
    _, _, _, run_contract = _checkpoint_contract_fixture()
    status_path = tmp_path / "checkpoint_status.json"
    status = _sealed_status(run_contract)
    status_path.write_text(json.dumps(status), encoding="utf-8")

    loaded = benchmark.load_authoritative_checkpoint_status(
        status_path,
        run_contract=run_contract,
        expected_task_ids=["pooled__all__h14"],
    )
    assert loaded["resumed_tasks"] == 1

    status = _sealed_status(run_contract, resumed_tasks=2)
    status_path.write_text(json.dumps(status), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid resumed_tasks"):
        benchmark.load_authoritative_checkpoint_status(
            status_path,
            run_contract=run_contract,
            expected_task_ids=["pooled__all__h14"],
        )

    status = _sealed_status(run_contract, completed_tasks=0)
    status_path.write_text(json.dumps(status), encoding="utf-8")
    with pytest.raises(ValueError, match="not complete"):
        benchmark.load_authoritative_checkpoint_status(
            status_path,
            run_contract=run_contract,
            expected_task_ids=["pooled__all__h14"],
        )


def test_checkpoint_status_rejects_legacy_or_tampered_ledger(tmp_path):
    _, _, _, run_contract = _checkpoint_contract_fixture()
    status_path = tmp_path / "checkpoint_status.json"
    status_path.write_text(json.dumps({
        "schema_version": "pool_city_checkpoint_status_v0.1",
        "run_id": run_contract["run_id"],
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="schema mismatch"):
        benchmark.load_authoritative_checkpoint_status(
            status_path,
            run_contract=run_contract,
            expected_task_ids=["pooled__all__h14"],
        )

    status = _sealed_status(run_contract)
    status["resumed_tasks"] = 0
    status_path.write_text(json.dumps(status), encoding="utf-8")
    with pytest.raises(ValueError, match="self-digest mismatch"):
        benchmark.load_authoritative_checkpoint_status(
            status_path,
            run_contract=run_contract,
            expected_task_ids=["pooled__all__h14"],
        )


def test_execute_tasks_authenticates_checkpoints_and_resume_ledger(tmp_path, monkeypatch):
    tasks = benchmark.task_specs(("toronto",), (14,))
    rows_by_split = {
        "train": [_panel_row("toronto", "2023-07-01", 14)],
        "development": [_panel_row("toronto", "2024-07-01", 14)],
        "confirmation": [_panel_row("toronto", "2025-07-01", 14)],
    }
    task_contracts = {}
    for task in tasks:
        task_contracts[task["task_id"]] = benchmark.build_task_contract(
            task,
            feature_contract_sha256="f" * 64,
            expected_prediction_keys=benchmark.expected_task_prediction_keys(
                task,
                rows_by_split,
            ),
        )
    run_contract = _minimal_run_contract(task_contracts)

    def fake_fit_task(task, **_kwargs):
        scored_rows = []
        for split, target_date in (
            ("development", "2024-07-01"),
            ("confirmation", "2025-07-01"),
        ):
            row = _prediction_row(split, target_date)
            row["regime"] = task["regime"]
            row["scored_market_id"] = (
                "all" if task["regime"] == "pooled" else "toronto"
            )
            row["task_id"] = task["task_id"]
            scored_rows.append(row)
        return {
            **task,
            "feature_contract_sha256": "f" * 64,
            "scored_rows": scored_rows,
        }

    monkeypatch.setattr(benchmark, "fit_task", fake_fit_task)
    status_path = tmp_path / "checkpoint_status.json"
    first = benchmark.execute_tasks(
        tasks=tasks,
        rows_by_split=rows_by_split,
        contracts={14: {"sha256": "f" * 64}},
        grid_f=[0.0],
        dependencies={},
        checkpoint_root=tmp_path / "checkpoints",
        run_contract=run_contract,
        task_contracts=task_contracts,
        status_path=status_path,
    )
    assert len(first) == 3
    status = benchmark.load_authoritative_checkpoint_status(
        status_path,
        run_contract=run_contract,
        expected_task_ids=[task["task_id"] for task in tasks],
    )
    assert status["resumed_tasks"] == 0

    monkeypatch.setattr(
        benchmark,
        "fit_task",
        lambda *args, **kwargs: pytest.fail("valid checkpoints should resume"),
    )
    second = benchmark.execute_tasks(
        tasks=tasks,
        rows_by_split=rows_by_split,
        contracts={14: {"sha256": "f" * 64}},
        grid_f=[0.0],
        dependencies={},
        checkpoint_root=tmp_path / "checkpoints",
        run_contract=run_contract,
        task_contracts=task_contracts,
        status_path=status_path,
    )
    assert [row["task_id"] for row in second] == [
        task["task_id"] for task in tasks
    ]
    status = benchmark.load_authoritative_checkpoint_status(
        status_path,
        run_contract=run_contract,
        expected_task_ids=[task["task_id"] for task in tasks],
    )
    assert status["resumed_tasks"] == 3


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


def test_plan_and_run_require_explicit_season_anchor_before_output(tmp_path):
    output = tmp_path / "must-not-exist"

    with pytest.raises(ValueError, match="explicit season_anchor_date"):
        benchmark.run_benchmark(
            data_root=tmp_path / "data",
            out_dir=output,
            mode="plan",
        )

    assert not output.exists()


def test_season_anchor_must_postdate_confirmation_before_output(tmp_path):
    output = tmp_path / "must-not-exist"

    with pytest.raises(ValueError, match="later than confirmation_year"):
        benchmark.run_benchmark(
            data_root=tmp_path / "data",
            out_dir=output,
            mode="plan",
            season_anchor_date="2025-07-22",
            confirmation_year=2025,
        )

    assert not output.exists()


def _exact_regime_panel_rows():
    rows = []
    for split, target_date in (
        ("development", "2024-07-01"),
        ("confirmation", "2025-07-01"),
    ):
        for regime in benchmark.REGIMES:
            row = _prediction_row(split, target_date)
            row["regime"] = regime
            row["scored_market_id"] = "all" if regime == "pooled" else "toronto"
            row["task_id"] = (
                "pooled__all__h14"
                if regime == "pooled"
                else f"{regime}__toronto__h14"
            )
            rows.append(row)
    return rows


def test_exact_regime_panels_reject_missing_or_duplicate_city_keys():
    rows = _exact_regime_panel_rows()
    benchmark.validate_exact_regime_panels(rows)

    missing = [
        row for row in rows
        if not (
            row["regime"] == "per_city"
            and row["split"] == "confirmation"
        )
    ]
    with pytest.raises(ValueError, match="missing a geographic regime"):
        benchmark.validate_exact_regime_panels(missing)

    duplicate = [*rows, dict(rows[0])]
    with pytest.raises(ValueError, match="duplicate scored panel key"):
        benchmark.validate_exact_regime_panels(duplicate)


def test_source_provenance_seals_model_reader_registry_and_config_closure():
    provenance = benchmark.source_provenance(benchmark._dependencies())
    paths = {row["path"] for row in provenance["source_files"]}

    assert "src/weather/reporting/research/pool_city_training_benchmark.py" in paths
    assert "src/weather/calibration/pooled_feature_model.py" in paths
    assert "src/weather/sources/forecast_history.py" in paths
    assert "src/weather/market/market_registry.py" in paths
    assert "src/weather/schema_registry_data.py" in paths
    assert "config/locations.json" in paths
    assert provenance["source_tree_sha256"] == benchmark.payload_sha256(
        provenance["source_files"]
    )
    assert provenance["git_identity"]["head_commit"]


def test_completion_source_verification_requires_exact_initial_closure():
    initial = {
        "source_contract_sha256": "a" * 64,
        "source_tree_sha256": "b" * 64,
        "git_identity": {"head_commit": "c" * 40},
        "source_files": [{"path": "src/weather/example.py", "sha256": "d" * 64}],
    }

    receipt = benchmark.verify_source_provenance_unchanged(initial, dict(initial))

    assert receipt["status"] == "PASS"
    assert receipt["exact_initial_completion_match"] is True
    assert receipt["source_contract_sha256"] == "a" * 64

    changed = {**initial, "source_tree_sha256": "e" * 64}
    with pytest.raises(RuntimeError, match="source_tree_sha256"):
        benchmark.verify_source_provenance_unchanged(initial, changed)


def test_complete_publication_writes_marker_last(tmp_path, monkeypatch):
    events = []
    monkeypatch.setattr(
        benchmark,
        "write_csv_atomic",
        lambda path, rows: events.append(("csv", Path(path).name)),
    )
    monkeypatch.setattr(
        benchmark,
        "write_text_atomic",
        lambda path, text: events.append(("text", Path(path).name)),
    )
    monkeypatch.setattr(
        benchmark,
        "write_json_atomic",
        lambda path, payload: events.append(
            ("json", Path(path).name, payload.get("status"))
        ),
    )
    payload = {
        "schema_version": benchmark.SCHEMA_VERSION,
        "status": "COMPLETE",
        "run_id": "sealed-run",
        "runtime": {},
        "corpus": {},
        "results": {},
        "paired_evidence": [],
    }

    benchmark.publish_benchmark_outputs(tmp_path, payload, scored_rows=[])

    assert events == [
        ("csv", "predictions.csv"),
        ("text", "pool_city_training_benchmark.md"),
        ("json", "pool_city_training_benchmark.json", "COMPLETE"),
    ]


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
    assert schema_version("pool_city_checkpoint_status") == "pool_city_checkpoint_status_v0.2"
    assert schema_version("pool_city_task_checkpoint") == "pool_city_task_checkpoint_v0.2"
    assert benchmark.CHECKPOINT_SCHEMA_VERSION == "pool_city_task_checkpoint_v0.2"
    assert benchmark.CHECKPOINT_STATUS_SCHEMA_VERSION == "pool_city_checkpoint_status_v0.2"
    assert schema_version("pool_city_input_manifest") == "pool_city_input_manifest_v0.1"
    assert schema_version("pool_city_runtime_plan") == "pool_city_runtime_plan_v0.1"
