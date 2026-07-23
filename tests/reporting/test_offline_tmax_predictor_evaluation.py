from __future__ import annotations

import csv
from datetime import date, timedelta
import math
import os
from pathlib import Path
import subprocess

import pytest

from weather.reporting.research import offline_tmax_predictor_evaluation as offline_evaluation
from weather.market.market_registry import MarketSpec
from weather.reporting.research.offline_tmax_predictor_evaluation import (
    FEATURES_BY_FAMILY,
    Thresholds,
    chronological_plan,
    evaluate_rows,
    family_features,
    load_experiment_rows,
    load_market_rows,
    paired_cluster_bootstrap,
    paired_summary,
    resolve_paths_outside_read_only_root,
)


FORECAST_FIELDS = (
    "schema_version",
    "market",
    "station",
    "source",
    "source_model",
    "temperature_unit",
    "target_date",
    "issue_time",
    "issue_time_basis",
    "valid_time",
    "target_temp_native",
    "target_temp_c",
    "temperature_925hpa",
    "temperature_850hpa",
    "geopotential_height_500hpa",
    "soil_temperature_0cm",
    "soil_moisture_0_to_1cm",
    "shortwave_radiation",
    "direct_radiation",
    "diffuse_radiation",
    "cloud_cover",
    "low_cloud",
    "mid_cloud",
    "high_cloud",
)


def _spec(
    market_id: str = "test-c",
    *,
    station: str = "KAAA",
    unit: str = "C",
    timezone: str = "America/Toronto",
) -> MarketSpec:
    return MarketSpec(
        id=market_id,
        city_label=market_id,
        slug_prefix=f"{market_id}-slug",
        timezone=timezone,
        display_unit=unit,
        wu_history_id=f"{station}:9:XX",
        icao=station,
        lat=0.0,
        lon=0.0,
        sources=("wu_history", "open_meteo"),
        leading_obs="wu_history",
    )


def _write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


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


def _forecast_row(**overrides):
    row = {field: "" for field in FORECAST_FIELDS}
    row.update({
        "schema_version": "forecast_history_long_v3",
        "market": "test-c",
        "station": "KAAA",
        "source": "open_meteo_previous_runs",
        "source_model": "best_match",
        "temperature_unit": "C",
        "target_date": "2026-01-03",
        "issue_time": "2026-01-02T23:00:00-05:00",
        "issue_time_basis": "fixed_lead_day_offset",
        "valid_time": "2026-01-03T14:00:00-05:00",
        "target_temp_native": "20",
        "target_temp_c": "20",
    })
    row.update(overrides)
    return row


def _write_settlement(root, spec, rows):
    path = root / "wunderground" / spec.icao.lower() / "daily" / "daily_summary.csv"
    fields = (
        "schema_version",
        "local_date",
        "temperature_unit",
        "max_temp_native",
        "max_temp_c",
        "row_count",
    )
    _write_csv(path, fields, rows)


def test_loader_excludes_stitched_and_at_cutoff_then_selects_latest_admissible_issue(tmp_path):
    spec = _spec()
    forecast_path = tmp_path / "forecast_history" / "kaaa" / "forecast_long.csv"
    rows = [
        _forecast_row(
            source="open_meteo_historical_forecast",
            issue_time="",
            issue_time_basis="stitched_continuous_archive",
            target_temp_native="99",
            target_temp_c="99",
            temperature_925hpa="30",
            temperature_850hpa="20",
        ),
        _forecast_row(
            issue_time="2026-01-02T20:00:00-05:00",
            target_temp_native="18",
            target_temp_c="18",
            temperature_925hpa="10",
            temperature_850hpa="5",
        ),
        _forecast_row(
            issue_time="2026-01-02T23:00:00-05:00",
            target_temp_native="20",
            target_temp_c="20",
            temperature_925hpa="12",
            temperature_850hpa="7",
        ),
        _forecast_row(
            issue_time="2026-01-03T00:00:00-05:00",
            target_temp_native="80",
            target_temp_c="80",
            temperature_925hpa="15",
            temperature_850hpa="10",
        ),
        _forecast_row(
            issue_time="2026-01-02T23:30:00",
            target_temp_native="70",
            target_temp_c="70",
            temperature_925hpa="15",
            temperature_850hpa="10",
        ),
    ]
    _write_csv(forecast_path, FORECAST_FIELDS, rows)
    _write_settlement(tmp_path, spec, [{
        "schema_version": "wu_daily_native_v2",
        "local_date": "2026-01-03",
        "temperature_unit": "C",
        "max_temp_native": "21",
        "max_temp_c": "21",
        "row_count": "24",
    }])

    loaded, audit, support = load_market_rows(
        data_root=tmp_path,
        spec=spec,
        family="pressure",
        cutoff_local="00:00",
    )

    assert len(loaded) == 1
    assert loaded[0]["selected_issue_time"] == "2026-01-02T23:00:00-05:00"
    assert loaded[0]["baseline_forecast_high_c"] == 20.0
    assert loaded[0]["settlement_high_c"] == 21.0
    assert loaded[0]["baseline_residual_c"] == 1.0
    assert loaded[0]["family_supported"] is True
    assert support[0]["issue_time_basis"] == "fixed_lead_day_offset"
    assert audit["forbidden_stitched_rows"] == 1
    assert audit["forbidden_stitched_family_rows"] == 1
    assert audit["rows_rejected_at_or_after_cutoff"] == 1
    assert audit["rows_rejected_missing_or_naive_issue_time"] == 1
    assert audit["admissible_rows"] == 2


def test_celsius_normalization_makes_c_and_f_market_rows_physically_equal(tmp_path):
    c_spec = _spec("c-market", station="KCCC", unit="C", timezone="America/Toronto")
    f_spec = _spec("f-market", station="KFFF", unit="F", timezone="America/New_York")
    c_row = _forecast_row(
        market="c-market",
        station="KCCC",
        temperature_unit="C",
        target_temp_native="20",
        target_temp_c="20",
        soil_temperature_0cm="10",
        soil_moisture_0_to_1cm="0.2",
    )
    f_row = _forecast_row(
        market="f-market",
        station="KFFF",
        temperature_unit="F",
        target_temp_native="68",
        target_temp_c="",
        soil_temperature_0cm="50",
        soil_moisture_0_to_1cm="0.2",
    )
    _write_csv(
        tmp_path / "forecast_history" / "kccc" / "forecast_long.csv",
        FORECAST_FIELDS,
        [c_row],
    )
    _write_csv(
        tmp_path / "forecast_history" / "kfff" / "forecast_long.csv",
        FORECAST_FIELDS,
        [f_row],
    )
    _write_settlement(tmp_path, c_spec, [{
        "schema_version": "wu_daily_native_v2",
        "local_date": "2026-01-03",
        "temperature_unit": "C",
        "max_temp_native": "21",
        "max_temp_c": "21",
        "row_count": "24",
    }])
    _write_settlement(tmp_path, f_spec, [{
        "schema_version": "wu_daily_native_v2",
        "local_date": "2026-01-03",
        "temperature_unit": "F",
        "max_temp_native": "69.8",
        "max_temp_c": "",
        "row_count": "24",
    }])

    loaded = load_experiment_rows(
        data_root=tmp_path,
        family="soil",
        specs=(c_spec, f_spec),
    )
    assert len(loaded["rows"]) == 2
    c_loaded, f_loaded = loaded["rows"]
    assert c_loaded["baseline_forecast_high_c"] == pytest.approx(20.0)
    assert f_loaded["baseline_forecast_high_c"] == pytest.approx(20.0)
    assert c_loaded["settlement_high_c"] == pytest.approx(21.0)
    assert f_loaded["settlement_high_c"] == pytest.approx(21.0)
    assert c_loaded["baseline_residual_c"] == pytest.approx(1.0)
    assert f_loaded["baseline_residual_c"] == pytest.approx(1.0)
    assert c_loaded["features"]["soil_temperature_mean_c"] == pytest.approx(10.0)
    assert f_loaded["features"]["soil_temperature_mean_c"] == pytest.approx(10.0)
    assert c_loaded["features"]["surface_minus_soil_mean_c"] == pytest.approx(10.0)
    assert f_loaded["features"]["surface_minus_soil_mean_c"] == pytest.approx(10.0)


def test_radiation_family_requires_total_cloud_but_not_optional_cloud_layers():
    features, missing = family_features([
        _forecast_row(
            shortwave_radiation="500",
            direct_radiation="350",
            diffuse_radiation="150",
            cloud_cover="25",
            low_cloud="",
            mid_cloud="",
            high_cloud="",
        )
    ], "radiation")
    assert missing == []
    assert features == {
        "shortwave_sum": 500.0,
        "shortwave_max": 500.0,
        "direct_sum": 350.0,
        "diffuse_sum": 150.0,
        "direct_fraction": 0.7,
        "cloud_cover_mean": 25.0,
        "cloud_cover_max": 25.0,
    }


def test_pressure850_family_is_distinct_from_the_two_level_pressure_contract():
    features, missing = family_features(
        [
            _forecast_row(
                target_temp_native="24",
                target_temp_c="24",
                temperature_850hpa="10",
                temperature_925hpa="",
            ),
            _forecast_row(
                valid_time="2026-01-03T20:00:00-05:00",
                target_temp_native="26",
                target_temp_c="26",
                temperature_850hpa="12",
                temperature_925hpa="",
            ),
        ],
        "pressure850",
    )

    assert missing == []
    assert features == {
        "temperature_850_mean_c": 11.0,
        "temperature_850_max_c": 12.0,
        "surface_minus_850_mean_c": 14.0,
    }
    two_level, two_level_missing = family_features(
        [_forecast_row(temperature_850hpa="10", temperature_925hpa="")],
        "pressure",
    )
    assert two_level is None
    assert "temperature_925hpa" in two_level_missing


def test_hrrr_smoke_family_keeps_mass_density_distinct_from_pm25():
    features, missing = family_features(
        [
            _forecast_row(
                hrrr_aerosol_optical_depth="0.1",
                hrrr_smoke_mass_density_ug_m3="4",
            ),
            _forecast_row(
                valid_time="2026-01-03T20:00:00-05:00",
                hrrr_aerosol_optical_depth="0.3",
                hrrr_smoke_mass_density_ug_m3="8",
            ),
        ],
        "hrrr_smoke",
    )

    assert missing == []
    assert features == {
        "hrrr_aerosol_optical_depth_mean": pytest.approx(0.2),
        "hrrr_aerosol_optical_depth_max": pytest.approx(0.3),
        "hrrr_smoke_mass_density_log1p_ug_m3_mean": pytest.approx(
            (math.log1p(4.0) + math.log1p(8.0)) / 2
        ),
        "hrrr_smoke_mass_density_log1p_ug_m3_max": pytest.approx(math.log1p(8.0)),
    }
    blocked, blocked_missing = family_features(
        [_forecast_row(hrrr_aerosol_optical_depth="0.1")],
        "hrrr_smoke",
    )
    assert blocked is None
    assert blocked_missing == ["hrrr_smoke_mass_density_ug_m3"]


def _pressure_feature_vector(x):
    return {
        column: float(x) * (index + 1)
        for index, column in enumerate(FEATURES_BY_FAMILY["pressure"])
    }


def _synthetic_rows(days=60):
    start = date(2025, 1, 1)
    rows = []
    for index in range(days):
        target_date = (start + timedelta(days=index)).isoformat()
        x = -1.0 if index % 2 == 0 else 1.0
        for market in ("alpha", "beta"):
            baseline = 20.0
            settlement = baseline + 2.0 * x
            rows.append({
                "market_id": market,
                "target_date": target_date,
                "family_supported": True,
                "baseline_forecast_high_c": baseline,
                "settlement_high_c": settlement,
                "baseline_residual_c": settlement - baseline,
                "features": _pressure_feature_vector(x),
            })
    return rows


def test_chronological_holdout_and_blocked_folds_are_strictly_ordered():
    dates = [(date(2025, 1, 1) + timedelta(days=index)).isoformat() for index in range(50)]
    plan = chronological_plan(
        dates,
        holdout_fraction=0.2,
        folds=4,
        min_train_dates=10,
        min_holdout_dates=5,
    )
    assert plan["status"] == "READY"
    assert max(plan["development_dates"]) < min(plan["holdout_dates"])
    assert len(plan["holdout_dates"]) == 10
    for fold in plan["folds"]:
        assert max(fold["train_dates"]) < min(fold["validation_dates"])


def test_synthetic_family_signal_is_scored_on_identical_rows_and_untouched_holdout():
    rows = _synthetic_rows()
    evaluation = evaluate_rows(
        rows,
        family="pressure",
        holdout_fraction=0.2,
        folds=3,
        bootstrap_replicates=200,
        bootstrap_seed=11,
        thresholds=Thresholds(
            min_markets=1,
            min_train_dates=10,
            min_validation_dates=3,
            min_holdout_dates=5,
            min_train_rows=10,
            min_validation_rows=4,
            min_holdout_rows=6,
        ),
    )

    assert evaluation["status"] == "RESEARCH_ONLY_EVALUATED"
    assert evaluation["cross_validation"]["aggregate"]["mae_delta_c"] < 0
    assert evaluation["holdout"]["metrics"]["mae_delta_c"] < 0
    assert evaluation["holdout"]["metrics"]["market_dates"] == 24
    assert evaluation["holdout"]["metrics"]["fleet_dates"] == 12
    assert evaluation["holdout"]["metrics"]["predicted_family_residual_distribution_c"]["n"] == 24
    assert [row["market_id"] for row in evaluation["holdout"]["metrics"]["by_market"]] == [
        "alpha",
        "beta",
    ]
    assert evaluation["holdout"]["model"]["fit_intercept"] is False
    assert len(evaluation["holdout"]["model"]["standardized_coefficients"]) == len(
        FEATURES_BY_FAMILY["pressure"]
    )
    assert evaluation["holdout"]["metrics"]["fleet_date_sign_counts"] == {
        "improvements": 12,
        "regressions": 0,
        "ties": 0,
        "non_ties": 12,
        "two_sided_sign_test_p": pytest.approx(2 / (2**12)),
    }
    assert evaluation["signal_assessment"] == "holdout_improvement_with_cluster_ci_below_zero"


def test_cluster_bootstrap_is_deterministic_and_resamples_fleet_dates():
    predicted = []
    for day, variant_error in (("2026-01-01", 0.5), ("2026-01-02", 1.5), ("2026-01-03", 0.25)):
        for market in ("alpha", "beta"):
            predicted.append({
                "target_date": day,
                "baseline_forecast_high_c": 22.0,
                "variant_forecast_high_c": 20.0 + variant_error,
                "settlement_high_c": 20.0,
                "market_id": market,
            })
    first = paired_cluster_bootstrap(predicted, seed=7, replicates=250)
    second = paired_cluster_bootstrap(predicted, seed=7, replicates=250)
    assert first == second
    assert first["cluster_unit"] == "fleet_target_date"
    assert first["clusters"] == 3
    assert first["mae_delta_c_95ci"]["high"] < 0


def test_sign_counts_are_numerically_stable_for_fleet_scale_pairs():
    rows = [
        {
            "target_date": f"2026-01-{(index % 28) + 1:02d}",
            "baseline_forecast_high_c": 22.0,
            "variant_forecast_high_c": 21.0,
            "settlement_high_c": 20.0,
        }
        for index in range(2_000)
    ]
    summary = paired_summary(rows, bootstrap_replicates=0)
    assert summary["market_date_sign_counts"]["improvements"] == 2_000
    assert summary["market_date_sign_counts"]["two_sided_sign_test_p"] >= 0.0


def test_zero_family_support_blocks_before_model_or_holdout_scoring():
    rows = _synthetic_rows(days=20)
    for row in rows:
        row["family_supported"] = False
        row["features"] = None
    evaluation = evaluate_rows(
        rows,
        family="pressure",
        thresholds=Thresholds(
            min_markets=1,
            min_train_dates=3,
            min_validation_dates=1,
            min_holdout_dates=2,
            min_train_rows=2,
            min_validation_rows=1,
            min_holdout_rows=2,
        ),
    )
    assert evaluation["status"] == "BLOCKED"
    assert evaluation["holdout"] is None
    assert evaluation["cross_validation"] is None
    assert "zero market-dates" in evaluation["blockers"][0]


def test_provider_coverage_window_is_selected_without_using_outcomes_before_split():
    rows = _synthetic_rows(days=60)
    unsupported_dates = sorted({row["target_date"] for row in rows})[:10]
    for row in rows:
        if row["target_date"] in unsupported_dates:
            row["family_supported"] = False
            row["features"] = None
    evaluation = evaluate_rows(
        rows,
        family="pressure",
        holdout_fraction=0.2,
        folds=3,
        bootstrap_replicates=50,
        thresholds=Thresholds(
            min_markets=1,
            min_train_dates=10,
            min_validation_dates=3,
            min_holdout_dates=5,
            min_train_rows=10,
            min_validation_rows=4,
            min_holdout_rows=6,
        ),
    )
    assert evaluation["status"] == "RESEARCH_ONLY_EVALUATED"
    assert evaluation["temporal_plan"]["all_date_count"] == 50
    assert evaluation["temporal_plan"]["development_start"] > max(unsupported_dates)


def test_resolved_output_contract_rejects_relative_dotdot_alias(tmp_path, monkeypatch):
    data_root = tmp_path / "mirror"
    data_root.mkdir()
    working = tmp_path / "working"
    working.mkdir()
    monkeypatch.chdir(working)

    with pytest.raises(ValueError, match="out resolves inside"):
        resolve_paths_outside_read_only_root(
            read_only_root=Path("..") / "mirror",
            paths={"out": Path("..") / "working" / ".." / "mirror" / "result.json"},
        )

    resolved_root, resolved = resolve_paths_outside_read_only_root(
        read_only_root=Path("..") / "mirror",
        paths={"out": Path("..") / "scratch" / "result.json"},
    )
    assert resolved_root == data_root.resolve()
    assert resolved["out"] == (tmp_path / "scratch" / "result.json").resolve()


def test_resolved_output_contract_rejects_symlink_alias(tmp_path):
    data_root = tmp_path / "mirror"
    data_root.mkdir()
    alias = tmp_path / "mirror-alias"
    _make_directory_alias(alias, data_root)

    with pytest.raises(ValueError, match="report resolves inside"):
        resolve_paths_outside_read_only_root(
            read_only_root=data_root,
            paths={"report": alias / "report.md"},
        )


def test_resolved_output_contract_requires_existing_directory_root(tmp_path):
    missing = tmp_path / "missing"
    with pytest.raises(ValueError, match="cannot resolve read-only root"):
        resolve_paths_outside_read_only_root(
            read_only_root=missing,
            paths={"out": tmp_path / "scratch" / "result.json"},
        )

    root_file = tmp_path / "not-a-directory"
    root_file.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="not a directory"):
        resolve_paths_outside_read_only_root(
            read_only_root=root_file,
            paths={"out": tmp_path / "scratch" / "result.json"},
        )


def test_resolved_output_contract_rejects_direct_out_report_collision(tmp_path):
    data_root = tmp_path / "mirror"
    data_root.mkdir()
    output = tmp_path / "scratch" / "result.json"
    with pytest.raises(ValueError, match="report collides with out"):
        resolve_paths_outside_read_only_root(
            read_only_root=data_root,
            paths={"out": output, "report": output},
        )


def test_resolved_output_contract_rejects_aliased_out_report_collision(tmp_path):
    data_root = tmp_path / "mirror"
    data_root.mkdir()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    alias = tmp_path / "scratch-alias"
    _make_directory_alias(alias, scratch)
    with pytest.raises(ValueError, match="report collides with out"):
        resolve_paths_outside_read_only_root(
            read_only_root=data_root,
            paths={
                "out": scratch / "result.json",
                "report": alias / "result.json",
            },
        )


def test_run_rejects_mirror_output_before_building_payload(tmp_path, monkeypatch):
    data_root = tmp_path / "mirror"
    data_root.mkdir()
    out = data_root / "research" / "result.json"
    report = tmp_path / "scratch" / "result.md"
    args = offline_evaluation.build_parser().parse_args([
        "--data-root",
        str(data_root),
        "--family",
        "pressure",
        "--out",
        str(out),
        "--report",
        str(report),
    ])

    def forbidden_build(**_kwargs):
        pytest.fail("payload construction must not start for an unsafe output path")

    monkeypatch.setattr(offline_evaluation, "build_payload", forbidden_build)
    with pytest.raises(ValueError, match="out resolves inside"):
        offline_evaluation.run(args)
    assert not out.exists()
