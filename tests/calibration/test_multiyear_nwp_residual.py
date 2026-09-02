from __future__ import annotations

import csv
from datetime import date, timedelta

import pytest

from weather.calibration import multiyear_nwp_residual as subject


def test_feature_contract_excludes_holdout_only_precipitation_probability():
    assert subject.EXCLUDED_FIELD == "precipitation_probability"
    assert subject.EXCLUDED_FIELD not in subject.FIELDS
    assert not any(
        subject.EXCLUDED_FIELD in name
        for name in subject.CHALLENGER_FEATURES
    )
    assert subject.CHALLENGER_FEATURES[: len(subject.BASELINE_FEATURES)] == (
        subject.BASELINE_FEATURES
    )


def test_fixed_windows_and_summary_modes_are_exact():
    assert subject._summary_targets("cloud_cover", 8) == ()
    assert subject._summary_targets("cloud_cover", 9) == (
        "cloud_cover_09_18_mean",
    )
    assert subject._summary_targets("cloud_cover", 18) == (
        "cloud_cover_09_18_mean",
    )
    assert subject._summary_targets("cloud_cover", 19) == ()
    assert subject._summary_targets("wind_speed_10m", 7) == (
        "wind_speed_10m_07_20_mean",
        "wind_speed_10m_07_20_max",
    )
    assert subject._summary_targets("wind_speed_10m", 20) == (
        "wind_speed_10m_07_20_mean",
        "wind_speed_10m_07_20_max",
    )
    assert subject._summary_targets("wind_speed_10m", 21) == ()

    mean = subject._Accumulator()
    for value in range(10):
        mean.add(float(value))
    assert subject._finish_accumulator("cloud_cover_09_18_mean", mean) == 4.5

    integral = subject._Accumulator()
    for _ in range(14):
        integral.add(2.0)
    assert subject._finish_accumulator(
        "shortwave_radiation_07_20_integral", integral
    ) == 28.0


def _surface():
    return {
        lead: {
            name: float(lead * 10 + index)
            for index, name in enumerate(subject.SUMMARY_NAMES)
        }
        for lead in subject.LEADS_SENSITIVITY
    }


def test_primary_and_no_refit_sensitivity_share_exact_feature_order():
    surface = _surface()
    primary_baseline, primary_anchor = subject.feature_vector(
        market="toronto",
        target_date="2025-06-15",
        leads=surface,
        selected_leads=subject.LEADS_PRIMARY,
        challenger=False,
    )
    primary_challenger, challenger_anchor = subject.feature_vector(
        market="toronto",
        target_date="2025-06-15",
        leads=surface,
        selected_leads=subject.LEADS_PRIMARY,
        challenger=True,
    )
    sensitivity_baseline, sensitivity_anchor = subject.feature_vector(
        market="toronto",
        target_date="2025-06-15",
        leads=surface,
        selected_leads=subject.LEADS_SENSITIVITY,
        challenger=False,
    )
    assert len(primary_baseline) == len(subject.BASELINE_FEATURES)
    assert len(primary_challenger) == len(subject.CHALLENGER_FEATURES)
    assert len(sensitivity_baseline) == len(subject.BASELINE_FEATURES)
    assert primary_anchor == challenger_anchor == 45.0
    assert sensitivity_anchor == 40.0


def test_model_contract_fits_exactly_two_identically_configured_estimators():
    first = subject._new_estimator()
    second = subject._new_estimator()
    assert first.get_params()["max_iter"] == 120
    assert first.get_params()["early_stopping"] is False
    assert first.get_params() == second.get_params()


def test_outcome_loader_rejects_cross_year_cohort_before_opening_sources():
    with pytest.raises(subject.IntegrityError, match="cohort/year isolation"):
        subject.load_outcome_values({}, year=2025, cohort="training")


def test_support_inventory_never_reads_outcome_column(tmp_path):
    fieldnames = [
        "schema_version",
        "local_date",
        "temperature_unit",
        "row_count",
        "max_temp_bucket_native",
    ]
    for market, station in subject.MARKET_STATIONS.items():
        path = tmp_path / "wunderground" / station / "daily" / "daily_summary.csv"
        path.parent.mkdir(parents=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for year in (subject.TRAIN_YEAR, subject.EVALUATION_YEAR):
                start = date(year, 5, 10)
                for offset in range(100):
                    writer.writerow(
                        {
                            "schema_version": "fixture_v1",
                            "local_date": (start + timedelta(days=offset)).isoformat(),
                            "temperature_unit": subject.MARKET_UNITS[market],
                            "row_count": subject.COMPLETE_DAY_MIN_ROWS,
                            "max_temp_bucket_native": "DO_NOT_PARSE_DURING_P0",
                        }
                    )

    scanned = subject._scan_outcome_support(tmp_path)

    assert scanned["outcome_values_accessed"] is False
    assert "max_temp_bucket_native" not in scanned["support_columns_accessed"]
    assert scanned["cohorts"]["2024"]["date_clusters"] == 100
    assert scanned["cohorts"]["2025"]["date_clusters"] == 100


def test_native_unit_conversion_preserves_c_and_scales_f_differences():
    assert subject._celsius_error(2.0, "C") == 2.0
    assert subject._celsius_error(9.0, "F") == 5.0


def test_crossed_bootstrap_is_deterministic_and_uses_both_cluster_axes():
    endpoints = {
        "effect": [
            (target_date, market, value)
            for target_date, value in (("2025-01-01", 1.0), ("2025-01-02", 3.0))
            for market in ("a", "b")
        ]
    }
    first = subject.crossed_bootstrap(endpoints, draws=2000, seed=123)
    second = subject.crossed_bootstrap(endpoints, draws=2000, seed=123)
    assert first == second
    assert first["date_clusters"] == 2
    assert first["market_clusters"] == 2
    assert first["effective_cluster_cells"] == 4
    assert first["endpoints"]["effect"]["point"] == 2.0


def _evaluation(squared, mae, sensitivity, contribution=0.2):
    endpoint = lambda values: {
        "point": values[0],
        "lower_95": values[1],
        "upper_95": values[2],
        "achieved_power": 0.8,
        "mde_80": 0.1,
    }
    return {
        "crossed_bootstrap": {
            "endpoints": {
                "primary__squared_error_improvement": endpoint(squared),
                "primary__mae_improvement": endpoint(mae),
                "all_leads_sensitivity__squared_error_improvement": endpoint(
                    sensitivity
                ),
            }
        },
        "market_contributions": {
            "maximum_single_market_contribution": contribution
        },
        "support": {"date_clusters": 114, "markets": list(subject.MARKETS)},
        "integrity": {
            "outcome_isolation": "PASS",
            "native_units": "PASS",
            "corpus_parity": "PASS",
            "matched_rows": "PASS",
        },
    }


def test_decision_rule_distinguishes_go_harm_and_underpowered():
    go = subject._decision(
        _evaluation((0.2, 0.1, 0.3), (0.03, -0.01, 0.07), (0.1, -0.1, 0.2))
    )
    assert go["verdict"] == "GO_TO_DISTRIBUTION_CHALLENGER"

    harm = subject._decision(
        _evaluation((-0.2, -0.3, -0.1), (-0.01, -0.03, 0.01), (-0.1, -0.2, 0.0))
    )
    assert harm["verdict"] == "NO_GO"

    inconclusive = subject._decision(
        _evaluation((0.02, -0.1, 0.2), (0.01, -0.03, 0.04), (0.01, -0.1, 0.1))
    )
    assert inconclusive["verdict"] == "INCONCLUSIVE_UNDERPOWERED"


def test_terminal_attempt_seal_is_create_only(tmp_path):
    design = {"design_sha256": "d" * 64}
    training = {"training_sha256": "t" * 64}
    path, attempt = subject._seal_terminal_attempt(
        terminal_root=tmp_path, design=design, training=training
    )
    assert path.is_file()
    assert attempt["rerun_authorized"] is False
    with pytest.raises(subject.IntegrityError, match="second source read"):
        subject._seal_terminal_attempt(
            terminal_root=tmp_path, design=design, training=training
        )


def test_support_threshold_leaves_date_cluster_not_value_logic():
    start = date(2025, 5, 10)
    dates = [start + timedelta(days=offset) for offset in range(100)]
    assert len({value.isoformat() for value in dates}) == 100
    assert subject.COMPLETE_DAY_MIN_ROWS == 18
