"""Per-model training column allowlist (retrain R0 prerequisite).

Fixtures are built in-test; nothing here reads LFS artifacts.
"""

from __future__ import annotations

import json
import pickle
from datetime import date, timedelta

import numpy as np
import pytest
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer

from weather.calibration.feature_column_allowlist import (
    ColumnAllowlistError,
    bundle_feature_names,
    column_allowlist_plan,
    load_column_allowlist,
    resolve_column_allowlist,
    served_feature_names,
)
from weather.calibration.feature_model import (
    CLOUD_GROUPS,
    WIND_GROUPS,
    feature_model_columns,
    feature_model_frame,
)
from weather.calibration.feature_training_policy import (
    F_MARKET_UNSERVABLE_TRAINING_FEATURES,
)
from weather.market.market_registry import NYC, TORONTO
from weather.model.feature_store import FEATURE_COLUMNS
from weather.model.toronto_model import TorontoHighTempModel

# Shape of a served v0.3 F-market list (numeric block, then the one-hot block),
# including the two pressure columns the current policy excludes for F markets.
SERVED_STYLE_NUMERIC = [
    "high_so_far",
    "current_temp",
    "rise_from_7am",
    "warming_rate_2h",
    "hours_at_peak",
    "dewpoint_c",
    "humidity",
    "pressure",
    "pressure_trend_3h",
    "wind_speed_kmh",
    "forecast_high",
    "forecast_gap",
    "minutes_since_cutoff",
    "live_reading_temp",
    "live_reading_minus_high",
]
SERVED_STYLE = (
    SERVED_STYLE_NUMERIC
    + [f"wind_{group}" for group in WIND_GROUPS]
    + [f"cloud_{group}" for group in CLOUD_GROUPS]
)


def _plan(columns, spec=NYC, source="fixture"):
    return column_allowlist_plan(
        columns,
        market_spec=spec,
        source=source,
        known_wind_groups=WIND_GROUPS,
        known_cloud_groups=CLOUD_GROUPS,
    )


def _records(n=48, *, drop=()):
    rng = np.random.default_rng(7)
    start = date(2024, 6, 1)
    rows = []
    for index in range(n):
        row = {column: float(rng.normal(70, 5)) for column in SERVED_STYLE_NUMERIC}
        # Columns outside the allowlist that the record builder also emits.
        row["sunshine_minutes_so_far"] = float(rng.normal(100, 10))
        row["wind_group"] = WIND_GROUPS[index % len(WIND_GROUPS)]
        row["cloud_group"] = CLOUD_GROUPS[index % len(CLOUD_GROUPS)]
        row["target_date"] = start + timedelta(days=index)
        row["final_bucket"] = 80 + (index % 3)
        for column in drop:
            row.pop(column, None)
        rows.append(row)
    return rows


def _write_served_fixture(tmp_path, hgb_lists, coef_lists):
    hgb = {"schema_version": "fixture"}
    hgb.update({hour: {"feature_names": list(names)} for hour, names in hgb_lists.items()})
    coefs = {"schema_version": "fixture"}
    coefs.update({hour: {"feature_names": list(names)} for hour, names in coef_lists.items()})
    hgb_path = tmp_path / "feature_model_hgb_fixture.pkl"
    coefs_path = tmp_path / "feature_model_coefs_fixture.json"
    hgb_path.write_bytes(pickle.dumps(hgb))
    coefs_path.write_text(json.dumps(coefs), encoding="utf-8")
    return hgb_path, coefs_path


# (a) the allowlist restricts columns exactly, preserving order --------------


def test_allowlist_restricts_training_columns_exactly_in_order():
    plan = _plan(SERVED_STYLE)
    frame, feature_cols = feature_model_frame(
        _records(), WIND_GROUPS, CLOUD_GROUPS, market_spec=NYC, column_allowlist=plan,
    )
    numeric_cols, listed = feature_model_columns(
        WIND_GROUPS, CLOUD_GROUPS, market_spec=NYC, column_allowlist=plan,
    )
    assert feature_cols == SERVED_STYLE
    assert listed == SERVED_STYLE
    assert numeric_cols == SERVED_STYLE_NUMERIC
    assert list(frame[feature_cols].columns) == SERVED_STYLE
    assert "sunshine_minutes_so_far" not in feature_cols
    # Kept, not dropped, and reported as an explicit policy override.
    assert plan["training_policy_exclusions_overridden"] == list(
        F_MARKET_UNSERVABLE_TRAINING_FEATURES
    )
    assert frame["pressure"].notna().all()


def test_allowlist_order_is_the_list_order_not_the_schema_order():
    reordered = list(reversed(SERVED_STYLE_NUMERIC)) + ["wind_S-SW", "cloud_Precip"]
    plan = _plan(reordered)
    _, feature_cols = feature_model_frame(
        _records(), WIND_GROUPS, CLOUD_GROUPS, market_spec=NYC, column_allowlist=plan,
    )
    assert feature_cols == reordered
    assert plan["all_wind_groups"] == ["S-SW"]
    assert plan["all_cloud_groups"] == ["Precip"]


def test_celsius_market_has_no_policy_override():
    assert _plan(SERVED_STYLE, spec=TORONTO)["training_policy_exclusions_overridden"] == []


# (b) a missing column fails closed -------------------------------------------


def test_column_missing_from_training_frame_fails_closed():
    plan = _plan(SERVED_STYLE)
    with pytest.raises(ColumnAllowlistError, match="humidity"):
        feature_model_frame(
            _records(drop=("humidity",)),
            WIND_GROUPS,
            CLOUD_GROUPS,
            market_spec=NYC,
            column_allowlist=plan,
        )


def test_missing_group_source_column_fails_closed():
    plan = _plan(SERVED_STYLE)
    with pytest.raises(ColumnAllowlistError, match="cloud_group"):
        feature_model_frame(
            _records(drop=("cloud_group",)),
            WIND_GROUPS,
            CLOUD_GROUPS,
            market_spec=NYC,
            column_allowlist=plan,
        )


@pytest.mark.parametrize(
    ("columns", "message"),
    [
        (["high_so_far", "not_a_feature"], "serving cannot build"),
        (["high_so_far", "wind_Nowhere"], "serving cannot build"),
        (["high_so_far", "high_so_far"], "repeats"),
        (["wind_S-SW", "high_so_far"], "numeric columns must lead"),
        ([], "empty"),
    ],
)
def test_invalid_allowlist_fails_closed(columns, message):
    with pytest.raises(ColumnAllowlistError, match=message):
        _plan(columns)


def test_served_allowlist_for_another_market_is_refused():
    with pytest.raises(ColumnAllowlistError, match="different market"):
        load_column_allowlist("served:toronto", market_spec=NYC)


def test_allowlist_file_round_trip(tmp_path):
    path = tmp_path / "allowlist.json"
    path.write_text(json.dumps(SERVED_STYLE), encoding="utf-8")
    plan = resolve_column_allowlist(
        str(path), market_spec=NYC, known_wind_groups=WIND_GROUPS, known_cloud_groups=CLOUD_GROUPS,
    )
    assert plan["feature_names"] == SERVED_STYLE
    assert plan["source"] == str(path)
    with pytest.raises(ColumnAllowlistError, match="not found"):
        load_column_allowlist(str(tmp_path / "absent.json"), market_spec=NYC)


# (c) default behaviour is unchanged ----------------------------------------


@pytest.mark.parametrize("spec", [NYC, TORONTO])
def test_default_columns_are_the_policy_filtered_schema(spec):
    excluded = set(F_MARKET_UNSERVABLE_TRAINING_FEATURES) if spec.unit == "F" else set()
    expected_numeric = [
        column
        for column in FEATURE_COLUMNS
        if column not in {"wind_group", "cloud_group"} and column not in excluded
    ]
    expected = (
        expected_numeric
        + [f"wind_{group}" for group in WIND_GROUPS]
        + [f"cloud_{group}" for group in CLOUD_GROUPS]
    )
    numeric_cols, feature_cols = feature_model_columns(WIND_GROUPS, CLOUD_GROUPS, market_spec=spec)
    assert numeric_cols == expected_numeric
    assert feature_cols == expected
    frame, frame_cols = feature_model_frame(
        _records(drop=("humidity",)), WIND_GROUPS, CLOUD_GROUPS, market_spec=spec,
    )
    # The default path still reindexes: an absent column is NaN, never an error.
    assert frame_cols == expected
    assert frame["humidity"].isna().all()
    assert ("pressure" in frame_cols) is (spec.unit == "C")


# (d) served-list extraction on a fixture bundle -----------------------------


def test_served_feature_names_from_fixture_bundle(tmp_path):
    lists = {"7": SERVED_STYLE, "12": SERVED_STYLE, "20": SERVED_STYLE}
    hgb_path, coefs_path = _write_served_fixture(tmp_path, lists, lists)
    assert served_feature_names(NYC, hgb_path=hgb_path, coefs_path=coefs_path) == SERVED_STYLE


def test_served_extraction_fails_when_hgb_and_coefs_disagree(tmp_path):
    hgb_path, coefs_path = _write_served_fixture(
        tmp_path, {"12": SERVED_STYLE}, {"12": SERVED_STYLE[:-1]},
    )
    with pytest.raises(ColumnAllowlistError, match="disagree"):
        served_feature_names(NYC, hgb_path=hgb_path, coefs_path=coefs_path)


def test_served_extraction_fails_when_cutoffs_disagree():
    payload = {"7": {"feature_names": SERVED_STYLE}, "8": {"feature_names": SERVED_STYLE[1:]}}
    with pytest.raises(ColumnAllowlistError, match="cutoff bundles disagree"):
        bundle_feature_names(payload)


def test_served_extraction_refuses_an_lfs_pointer(tmp_path):
    hgb_path, coefs_path = _write_served_fixture(tmp_path, {"12": SERVED_STYLE}, {"12": SERVED_STYLE})
    hgb_path.write_text("version https://git-lfs.github.com/spec/v1\noid sha256:00\nsize 1\n")
    with pytest.raises(ColumnAllowlistError, match="LFS pointer"):
        served_feature_names(NYC, hgb_path=hgb_path, coefs_path=coefs_path)


# Smoke fit on fixtures: the trained bundle serves through the HGB path ------


def test_smoke_fit_bundle_feature_names_equal_allowlist_and_serving_accepts():
    plan = _plan(SERVED_STYLE)
    frame, feature_cols = feature_model_frame(
        _records(), WIND_GROUPS, CLOUD_GROUPS, market_spec=NYC, column_allowlist=plan,
    )
    matrix = frame[feature_cols]
    imputer = SimpleImputer(strategy="median", keep_empty_features=True)
    hgb = HistGradientBoostingClassifier(max_iter=5, max_leaf_nodes=4, random_state=42)
    hgb.fit(imputer.fit_transform(matrix), frame["final_bucket"])
    bundle = {
        "12": {
            "model": hgb,
            "imputer": imputer,
            "feature_names": feature_cols,
            "all_wind_groups": list(plan["all_wind_groups"]),
            "all_cloud_groups": list(plan["all_cloud_groups"]),
        }
    }
    assert bundle["12"]["feature_names"] == SERVED_STYLE
    assert list(imputer.feature_names_in_) == SERVED_STYLE

    model = TorontoHighTempModel(target_date="2026-07-15", market_id="nyc")
    live = {column: 70.0 for column in FEATURE_COLUMNS}
    live.update({"pressure": None, "pressure_trend_3h": None})
    live.update({"wind_group": "S-SW", "cloud_group": "Precip"})
    model.extract_live_features = lambda sources, cutoff_hour, now=None: dict(live)
    distribution, kind = model._evaluate_feature_model_for_cutoff({}, 12, bundle, None)
    assert kind == "hgb"
    assert set(distribution) == {80, 81, 82}
    assert sum(distribution.values()) == pytest.approx(1.0)
