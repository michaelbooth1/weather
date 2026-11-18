"""Per-model training column allowlist (retrain R0 prerequisite).

Fixtures are built in-test; nothing here reads LFS artifacts.

Guards: retrain R0 train/serve column parity (a refit uses only the served model's feature columns).
"""

from __future__ import annotations

import json
import pickle
from collections import defaultdict
from datetime import date, timedelta

import numpy as np
import pytest
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer

from weather.artifacts import CandidateArtifactPathError
from weather.calibration.feature_column_allowlist import (
    ALLOWLIST_RECORD_KEYS,
    ColumnAllowlistError,
    allowlist_record,
    bundle_feature_names,
    column_allowlist_plan,
    load_column_allowlist,
    resolve_column_allowlist,
    served_feature_names,
)
from weather.calibration.feature_model import (
    CLOUD_GROUPS,
    WIND_GROUPS,
    base_only_output_paths,
    feature_model_columns,
    feature_model_frame,
    parse_cli_args,
)
from weather.calibration.feature_training_policy import (
    F_MARKET_UNSERVABLE_TRAINING_FEATURES,
    TRAINING_FEATURE_POLICY_ID,
    training_feature_exclusions,
)
from weather.market.market_registry import NYC, TORONTO
from weather.model.feature_store import FEATURE_COLUMNS
from weather.model.toronto_model import TorontoHighTempModel
from weather.paths import ARTIFACTS_ROOT, REPO_ROOT, SRC_ROOT

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


# R0 mode: served-policy:<market> (owner 2026-10-21, "Drop pressure") ---------


@pytest.fixture
def served_fixture(monkeypatch):
    """Serve SERVED_STYLE for every market without touching LFS artifacts."""
    import weather.calibration.feature_column_allowlist as allowlist_module

    monkeypatch.setattr(
        allowlist_module, "served_feature_names", lambda spec, **_: list(SERVED_STYLE)
    )
    return allowlist_module


def _resolve(value, spec):
    return resolve_column_allowlist(
        value, market_spec=spec, known_wind_groups=WIND_GROUPS, known_cloud_groups=CLOUD_GROUPS,
    )


PRESSURE = ["pressure", "pressure_trend_3h"]
POLICY_STYLE = [name for name in SERVED_STYLE if name not in PRESSURE]


def test_policy_mode_drops_exactly_the_two_pressure_columns_in_f_markets(served_fixture):
    plan = _resolve("served-policy:nyc", NYC)
    assert plan["feature_names"] == POLICY_STYLE
    assert len(plan["feature_names"]) == len(SERVED_STYLE) - 2
    assert plan["mode"] == "served-policy"
    assert plan["served_feature_names"] == SERVED_STYLE
    assert plan["policy_exclusions_applied"] == PRESSURE
    assert plan["differs_from_served"] is True
    assert plan["training_policy_exclusions_overridden"] == []
    assert plan["training_feature_policy_id"] == TRAINING_FEATURE_POLICY_ID


def test_policy_mode_excludes_nothing_for_the_celsius_market(served_fixture):
    assert training_feature_exclusions(TORONTO) == ()
    plan = _resolve("served-policy:toronto", TORONTO)
    assert plan["feature_names"] == SERVED_STYLE
    assert plan["policy_exclusions_applied"] == []
    assert plan["differs_from_served"] is False
    assert plan["training_policy_exclusions_overridden"] == []


def test_plain_served_mode_keeps_the_list_and_records_overrides(served_fixture):
    plan = _resolve("served:nyc", NYC)
    assert plan["feature_names"] == SERVED_STYLE
    assert plan["mode"] == "served"
    assert plan["policy_exclusions_applied"] == []
    assert plan["differs_from_served"] is False
    assert plan["training_policy_exclusions_overridden"] == PRESSURE


def test_policy_mode_refuses_another_market(served_fixture):
    with pytest.raises(ColumnAllowlistError, match="different market"):
        _resolve("served-policy:toronto", NYC)


def test_allowlist_record_carries_the_served_difference(served_fixture):
    record = allowlist_record(_resolve("served-policy:nyc", NYC))
    assert tuple(record) == ALLOWLIST_RECORD_KEYS
    assert record["policy_exclusions_applied"] == PRESSURE
    assert record["differs_from_served"] is True
    file_plan = _plan(SERVED_STYLE)
    assert file_plan["differs_from_served"] is None
    assert file_plan["served_feature_names"] is None


# R0 output redirect and base-only enforcement --------------------------------


@pytest.mark.parametrize(
    "root",
    [
        ARTIFACTS_ROOT / "models",
        ARTIFACTS_ROOT / "models" / "hgb",
        ARTIFACTS_ROOT,
        ARTIFACTS_ROOT / "releases",
        ARTIFACTS_ROOT / "misc" / "r0",
        ARTIFACTS_ROOT / "candidates",
        REPO_ROOT,
        SRC_ROOT,
        SRC_ROOT / "weather",
    ],
)
def test_output_root_refuses_served_and_source_paths(root):
    with pytest.raises(CandidateArtifactPathError):
        base_only_output_paths(root, "_nyc")


def test_output_root_allows_a_candidate_child_or_scratch_dir(tmp_path):
    candidate = ARTIFACTS_ROOT / "candidates" / "retrain-r0-test-never-created"
    paths = base_only_output_paths(candidate, "_nyc")
    assert paths["hgb"] == candidate.resolve() / "feature_model_hgb_nyc.pkl"
    assert not candidate.exists()
    scratch = base_only_output_paths(tmp_path / "r0", "_nyc")
    assert set(scratch) == {"coefs", "hgb", "report", "validation_rows"}


def test_output_root_never_overwrites(tmp_path):
    (tmp_path / "feature_model_hgb_nyc.pkl").write_bytes(b"x")
    with pytest.raises(CandidateArtifactPathError, match="never overwritten"):
        base_only_output_paths(tmp_path, "_nyc")


@pytest.mark.parametrize("flag", ["--late-day-only", "--item27-report-only"])
@pytest.mark.parametrize(
    "option", [["--output-root", "x"], ["--column-allowlist", "served-policy:nyc"]],
)
def test_cli_refuses_base_only_options_with_other_modes(flag, option):
    with pytest.raises(SystemExit) as raised:
        parse_cli_args(["--market", "nyc", flag, *option])
    assert raised.value.code == 2


def test_cli_default_is_unchanged():
    args = parse_cli_args([])
    assert (args.market, args.column_allowlist, args.output_root) == ("toronto", None, None)


class _FakeModel:
    def __init__(self, market_id="toronto"):
        self.spec = NYC
        self.calibrated_weights = None

    def historical_target_cache(self):
        return {"daily": [], "by_date": {}, "bucket_space": [80, 81, 82]}


def _patch_trainer(monkeypatch, *, records, late_day):
    import weather.calibration.feature_model as trainer

    monkeypatch.setattr(trainer, "TorontoHighTempModel", _FakeModel)
    monkeypatch.setattr(trainer, "RUN_LOO", False)
    for loader in (
        "load_forecast_daily",
        "load_forecast_profiles",
        "load_marine_water_contrast_features",
        "load_reanalysis_synoptic_features",
    ):
        monkeypatch.setattr(trainer, loader, lambda *args, **kwargs: {})
    monkeypatch.setattr(
        trainer,
        "build_feature_records_for_model",
        lambda *args, **kwargs: defaultdict(list, {12: records}),
    )
    monkeypatch.setattr(trainer, "train_late_day_continuation_models", late_day)
    return trainer


def test_r0_main_is_base_only_and_writes_only_under_output_root(
    tmp_path, monkeypatch, served_fixture,
):
    def no_late_day(*args, **kwargs):
        raise AssertionError("R0 must not train late-day continuation models")

    def no_served_write(*args, **kwargs):
        raise AssertionError("R0 must not resolve a served artifact path")

    trainer = _patch_trainer(monkeypatch, records=_records(), late_day=no_late_day)
    monkeypatch.setattr(trainer, "writable_artifact_path", no_served_write)
    out = tmp_path / "retrain-r0"
    trainer.main("nyc", column_allowlist="served-policy:nyc", output_root=str(out))

    assert sorted(path.name for path in out.iterdir()) == [
        "feature_model_coefs_nyc.json",
        "feature_model_hgb_nyc.pkl",
    ]
    hgb = pickle.loads((out / "feature_model_hgb_nyc.pkl").read_bytes())
    coefs = json.loads((out / "feature_model_coefs_nyc.json").read_text(encoding="utf-8"))
    assert hgb["12"]["feature_names"] == POLICY_STYLE
    assert coefs["12"]["feature_names"] == POLICY_STYLE
    for info in (hgb, coefs):
        assert info["base_models_only"] is True
        record = info["training_column_allowlist"]
        assert record["mode"] == "served-policy"
        assert record["policy_exclusions_applied"] == PRESSURE
        assert record["differs_from_served"] is True


def test_default_main_still_trains_late_day_into_served_paths(tmp_path, monkeypatch):
    calls = []

    def fake_late_day(*args, **kwargs):
        calls.append(args)
        return {}, [], []

    trainer = _patch_trainer(monkeypatch, records=_records(), late_day=fake_late_day)
    monkeypatch.setattr(trainer, "writable_artifact_path", lambda name: tmp_path / name)
    trainer.main("nyc")
    assert len(calls) == 1
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "feature_model_coefs_nyc.json",
        "feature_model_hgb_nyc.pkl",
        "late_day_model_coefs_nyc.json",
    ]
    hgb = pickle.loads((tmp_path / "feature_model_hgb_nyc.pkl").read_bytes())
    assert "training_column_allowlist" not in hgb
    assert "base_models_only" not in hgb
    assert "pressure" not in hgb["12"]["feature_names"]
