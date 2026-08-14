import json
import pickle
from dataclasses import replace

import pytest
from sklearn.ensemble import HistGradientBoostingClassifier

from weather.calibration.base_model_candidate import fit_market_candidate
from weather.calibration.feature_training_policy import (
    TRAINING_FEATURE_POLICY_ID,
    training_feature_names,
)
from weather.market.market_registry import NYC, TORONTO
from weather.model.feature_store import FEATURE_SCHEMA_VERSION


PARENT_FEATURE_NAMES = [
    "forecast_high",
    "pressure",
    "pressure_trend_3h",
]


def _records(unit):
    base = 20 if unit == "C" else 80
    return [
        {
            "target_date": f"{year}-06-{day:02d}",
            "cutoff_hour": 12,
            "final_bucket": base + (day % 2),
            "forecast_high": base + 1.5,
            "pressure": 1012.0 if unit == "C" else 29.9,
            "pressure_trend_3h": -0.4,
        }
        for year in (2024, 2025)
        for day in (1, 2)
    ]


def _parent_contract():
    return (
        {
            "12": {
                "model": HistGradientBoostingClassifier(
                    max_iter=2,
                    max_leaf_nodes=3,
                    random_state=42,
                ),
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "feature_names": list(PARENT_FEATURE_NAMES),
                "all_wind_groups": [],
                "all_cloud_groups": [],
            }
        },
        {
            "12": {
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "feature_names": list(PARENT_FEATURE_NAMES),
                "scaler_mean": [0.0, 0.0, 0.0],
            }
        },
    )


@pytest.mark.parametrize(
    ("market_spec", "expected_names", "expected_exclusions"),
    [
        (NYC, ["forecast_high"], ["pressure", "pressure_trend_3h"]),
        (TORONTO, PARENT_FEATURE_NAMES, []),
    ],
)
def test_candidate_fit_applies_registry_unit_training_policy(
    tmp_path,
    market_spec,
    expected_names,
    expected_exclusions,
):
    parent_hgb, parent_lr = _parent_contract()
    hgb_path = tmp_path / "hgb.pkl"
    lr_path = tmp_path / "lr.json"
    calibration_path = tmp_path / "calibration.json"
    receipt_path = tmp_path / "receipt.json"
    report_path = tmp_path / "report.md"

    result = fit_market_candidate(
        market_id=market_spec.id,
        unit=market_spec.unit,
        target_date="2026-07-31",
        parent_release_id="parent-r1",
        training_as_of="2026-08-12T04:00:00+00:00",
        feature_contract_id="feature-contract-v1",
        runtime_id="runtime-v1",
        corpus_manifest_sha256="a" * 64,
        pit_forecast_corpus_manifest_sha256="b" * 64,
        pit_forecast_preflight_sha256="c" * 64,
        records=_records(market_spec.unit),
        parent_hgb=parent_hgb,
        parent_lr=parent_lr,
        hgb_path=hgb_path,
        lr_path=lr_path,
        probability_calibration_path=calibration_path,
        receipt_path=receipt_path,
        report_path=report_path,
    )

    with hgb_path.open("rb") as handle:
        hgb = pickle.load(handle)
    lr = json.loads(lr_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert result["hours"]["12"]["feature_names"] == expected_names
    assert hgb["12"]["feature_names"] == expected_names
    assert lr["12"]["feature_names"] == expected_names
    assert len(lr["12"]["scaler_mean"]) == len(expected_names)
    assert receipt["training_feature_policy_id"] == TRAINING_FEATURE_POLICY_ID
    assert receipt["training_feature_exclusions"] == expected_exclusions


def test_a_future_fahrenheit_registry_spec_inherits_pressure_exclusions():
    future_f_market = replace(NYC, id="future-f-market")

    assert training_feature_names(
        PARENT_FEATURE_NAMES,
        market_spec=future_f_market,
    ) == ["forecast_high"]
    assert training_feature_names(
        PARENT_FEATURE_NAMES,
        market_spec=TORONTO,
    ) == PARENT_FEATURE_NAMES
