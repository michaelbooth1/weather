import csv
from pathlib import Path

import numpy as np
import pytest

from weather.calibration import calendar_residual_replication as replication
from weather.calibration import multiyear_nwp_residual as prior


class FakeEstimator:
    fit_calls = 0

    def fit(self, matrix, target, *, sample_weight):
        type(self).fit_calls += 1
        assert len(matrix) == len(target) == len(sample_weight)
        return self

    def predict(self, matrix):
        return np.zeros(len(matrix), dtype=float)


def _outcome_path(root: Path, station: str = "cyyz") -> Path:
    return root / "wunderground" / station / "daily" / "daily_summary.csv"


def _write_outcomes(path: Path, dates: list[str]) -> None:
    path.parent.mkdir(parents=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "schema_version",
                "local_date",
                "temperature_unit",
                "row_count",
                "sentinel_outcome",
            ),
            lineterminator="\n",
        )
        writer.writeheader()
        for target_date in dates:
            writer.writerow(
                {
                    "schema_version": "wu_daily_summary_v1",
                    "local_date": target_date,
                    "temperature_unit": "C",
                    "row_count": 24,
                    "sentinel_outcome": 999,
                }
            )


def _one_market(monkeypatch) -> None:
    monkeypatch.setattr(replication, "MARKETS", ("toronto",))
    monkeypatch.setattr(replication, "MARKET_STATIONS", {"toronto": "cyyz"})
    monkeypatch.setattr(replication, "MARKET_UNITS", {"toronto": "C"})


def _outcome_design(root: Path, dates: list[str]) -> dict:
    path = _outcome_path(root)
    inventory = [
        {
            "market": "toronto",
            "station": "cyyz",
            "relative_path": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": replication.sha256_file(path),
        }
    ]
    keys = [f"2025|toronto|{target_date}" for target_date in dates]
    return {
        "input_binding": {
            "mirror_root": str(root),
            "outcome_support_file_inventory": inventory,
            "outcome_support_file_inventory_sha256": replication.canonical_sha256(
                inventory
            ),
        },
        "cohorts": {
            "outcome_support": {
                "terminal_evaluation": {"toronto": dates},
            },
            "terminal_evaluation": {
                "keys_sha256": replication.canonical_sha256(keys),
            },
        },
    }


def test_frozen_dates_exclude_january_and_spent_window() -> None:
    assert len(replication.TRAIN_DATES) == 335
    assert len(replication.EVALUATION_EARLY_DATES) == 98
    assert len(replication.EVALUATION_LATE_DATES) == 122
    assert len(replication.EVALUATION_DATES) == 220
    assert len(set(replication.EVALUATION_DATES)) == 220
    assert not any(value[5:7] == "01" for value in replication.TRAIN_DATES)
    assert not any(value[5:7] == "01" for value in replication.EVALUATION_DATES)
    assert not any("2025-05-10" <= value <= "2025-08-31" for value in replication.EVALUATION_DATES)


def test_frozen_primitives_are_the_prior_residual_contract() -> None:
    assert replication.FIELDS == prior.FIELDS
    assert replication.EXCLUDED_FIELD == "precipitation_probability"
    assert replication.LEADS_PRIMARY == tuple(range(2, 8))
    assert replication.LEADS_SENSITIVITY == tuple(range(1, 8))
    assert replication.BASELINE_FEATURES == prior.BASELINE_FEATURES
    assert replication.CHALLENGER_FEATURES == prior.CHALLENGER_FEATURES
    assert replication.MODEL_CONFIG == prior.MODEL_CONFIG
    assert replication.MODEL_SEED == prior.MODEL_SEED
    assert replication.BOOTSTRAP_SEED == prior.BOOTSTRAP_SEED
    assert replication.BOOTSTRAP_DRAWS == 20_000
    assert replication._new_estimator is prior._new_estimator


def test_feature_slices_cover_exact_dates_once() -> None:
    for slices, expected in (
        (replication.TRAINING_SLICES, set(replication.TRAIN_DATES)),
        (replication.EVALUATION_SLICES, set(replication.EVALUATION_DATES)),
    ):
        selected = []
        for item in slices:
            selected.extend(replication._date_range(item.start, item.end))
        assert len(selected) == len(set(selected))
        assert set(selected) == expected


def test_support_scan_never_calls_outcome_reader(tmp_path, monkeypatch) -> None:
    _one_market(monkeypatch)
    dates = [
        *replication.TRAIN_DATES,
        *replication.EVALUATION_DATES,
        "2025-01-15",
        "2025-06-15",
    ]
    _write_outcomes(_outcome_path(tmp_path), dates)
    monkeypatch.setattr(
        replication,
        "native_bucket",
        lambda _row: pytest.fail("P0 support scan opened an outcome value"),
    )

    result = replication._scan_outcome_support(tmp_path)

    assert result["outcome_values_accessed"] is False
    assert result["cohorts"]["terminal_evaluation"]["date_clusters"] == 220
    assert result["spent_2025_outcome_values_accessed"] == 0


def test_outcome_loader_skips_january_and_spent_values(tmp_path, monkeypatch) -> None:
    _one_market(monkeypatch)
    path = _outcome_path(tmp_path)
    _write_outcomes(path, ["2025-01-15", "2025-06-15", "2025-02-01"])
    design = _outcome_design(tmp_path, ["2025-02-01"])
    accessed = []

    def read_outcome(row):
        accessed.append(row["local_date"])
        return 7

    monkeypatch.setattr(replication, "native_bucket", read_outcome)
    outcomes, audit = replication.load_outcome_values(
        design, year=2025, cohort="terminal_evaluation"
    )

    assert outcomes == {("toronto", "2025-02-01"): 7}
    assert accessed == ["2025-02-01"]
    assert audit["january_outcome_value_accesses"] == 0
    assert audit["spent_may10_aug31_2025_outcome_value_accesses"] == 0


@pytest.mark.parametrize("forbidden", ("2025-01-15", "2025-06-15"))
def test_outcome_loader_denies_forbidden_selected_dates(
    tmp_path, monkeypatch, forbidden
) -> None:
    _one_market(monkeypatch)
    _write_outcomes(_outcome_path(tmp_path), [forbidden])
    design = _outcome_design(tmp_path, [forbidden])
    monkeypatch.setattr(
        replication,
        "native_bucket",
        lambda _row: pytest.fail("forbidden outcome reached native_bucket"),
    )

    with pytest.raises(replication.IntegrityError, match="forbidden 2025"):
        replication.load_outcome_values(
            design, year=2025, cohort="terminal_evaluation"
        )


def test_terminal_attempt_is_create_only(tmp_path) -> None:
    design = {
        "design_sha256": "design",
        "cohorts": {"evaluation_segments": {"frozen": True}},
    }
    training = {"training_sha256": "training"}
    _, attempt = replication._seal_terminal_attempt(
        terminal_root=tmp_path / "terminal",
        design=design,
        training=training,
    )

    assert attempt["outcome_source_accesses_authorized"] == 1
    assert attempt["spent_2025_outcome_accesses_authorized"] == 0
    assert attempt["january_outcome_accesses_authorized"] == 0
    assert attempt["rerun_authorized"] is False
    with pytest.raises(replication.IntegrityError, match="create-only"):
        replication._seal_terminal_attempt(
            terminal_root=tmp_path / "terminal",
            design=design,
            training=training,
        )


def test_fit_models_invokes_exactly_two_fit_calls(tmp_path, monkeypatch) -> None:
    FakeEstimator.fit_calls = 0
    design = {"design_sha256": "design", "cohorts": {"training": {"keys_sha256": "keys"}}}
    records = [
        {
            "market": "toronto",
            "target_date": "2024-02-01",
            "month": 2,
            "segment": "training",
            "native_unit": "C",
            "outcome_native": 4,
            "primary_anchor_native": 3.0,
        }
    ]
    monkeypatch.setattr(replication, "_validate_design", lambda _path: design)
    monkeypatch.setattr(replication, "_assert_design_committed", lambda *_args: None)
    monkeypatch.setattr(replication, "load_feature_surfaces", lambda *_args, **_kwargs: ({}, {"ok": True}))
    monkeypatch.setattr(replication, "load_outcome_values", lambda *_args, **_kwargs: ({}, {"ok": True}))
    monkeypatch.setattr(
        replication,
        "_prediction_rows",
        lambda **_kwargs: (
            records,
            np.zeros((1, len(replication.BASELINE_FEATURES))),
            np.zeros((1, len(replication.CHALLENGER_FEATURES))),
            np.ones(1),
        ),
    )
    monkeypatch.setattr(replication, "_new_estimator", FakeEstimator)
    design_path = tmp_path / "design.json"
    design_path.write_text("{}", encoding="utf-8")

    receipt = replication.fit_models(
        design_path=design_path, artifact_root=tmp_path / "training"
    )

    assert FakeEstimator.fit_calls == 2
    assert receipt["models_fitted"] == 2
    assert len(receipt["artifacts"]) == 2


def _decision_payload(*, mse_lower: float, mse_upper: float) -> dict:
    endpoints = {
        "primary__squared_error_improvement": {
            "point": 0.3,
            "lower_95": mse_lower,
            "upper_95": mse_upper,
            "achieved_power": 0.9,
            "mde_80": 0.2,
        },
        "primary__mae_improvement": {
            "point": 0.1,
            "lower_95": -0.01,
            "upper_95": 0.2,
        },
        "all_leads_sensitivity__squared_error_improvement": {"point": 0.2},
    }
    return {
        "combined": {
            "crossed_bootstrap": {"endpoints": endpoints},
            "market_contributions": {"maximum_single_market_contribution": 0.3},
            "support": {"date_clusters": 220, "markets": list(replication.MARKETS)},
            "integrity": {
                "outcome_isolation": "PASS",
                "native_units": "PASS",
                "corpus_integrity": "PASS",
                "matched_rows": "PASS",
            },
        },
        "segments": {
            name: {
                "crossed_bootstrap": {
                    "endpoints": {
                        "primary__squared_error_improvement": {"point": 0.1}
                    }
                }
            }
            for name in (
                "february_through_may09",
                "september_through_december",
            )
        },
    }


def test_decision_rule_distinguishes_go_no_go_and_inconclusive() -> None:
    assert (
        replication._decision(_decision_payload(mse_lower=0.1, mse_upper=0.5))[
            "verdict"
        ]
        == "GO_TO_PROSPECTIVE_POINT_SHADOW"
    )
    assert (
        replication._decision(_decision_payload(mse_lower=-0.5, mse_upper=-0.1))[
            "verdict"
        ]
        == "NO_GO"
    )
    assert (
        replication._decision(_decision_payload(mse_lower=-0.1, mse_upper=0.5))[
            "verdict"
        ]
        == "INCONCLUSIVE_UNDERPOWERED"
    )


def test_crossed_bootstrap_is_shared_weight_and_deterministic() -> None:
    endpoints = {
        "a": [("2025-02-01", "toronto", 1.0), ("2025-02-02", "toronto", 2.0)],
        "b": [("2025-02-01", "toronto", 3.0), ("2025-02-02", "toronto", 4.0)],
    }
    first = prior.crossed_bootstrap(endpoints, draws=100, seed=replication.BOOTSTRAP_SEED)
    second = prior.crossed_bootstrap(endpoints, draws=100, seed=replication.BOOTSTRAP_SEED)

    assert first == second
    assert first["method"].startswith("shared-weight crossed")

