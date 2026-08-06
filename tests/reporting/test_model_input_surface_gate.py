import hashlib
import json
import pickle
from collections import defaultdict
from datetime import date, datetime, timezone
from fractions import Fraction
from pathlib import Path

import pytest

from weather.market.market_config import config_for_date
from weather.market.market_registry import all_specs, spec_for_id
from weather.reporting.source_gates.model_input_surface_gate import (
    BASE_FEATURES,
    EXPECTED_CUTOFF_HOURS,
    GUST_CALM_MAX_SUSTAINED_WIND_NATIVE,
    SCHEMA_VERSION,
    TRAINED_FEATURE_POPULATION_FLOOR,
    build_parser,
    default_output_path,
    evaluate_gate,
    main,
)


END_DATE = date(2026, 8, 5)
TARGET_DATES = (date(2026, 8, 3), date(2026, 8, 4), END_DATE)
_CURRENT_ARTIFACT_IDENTITY = object()


def _model_identity_for_artifact(
    market_id: str,
    artifact_path: Path,
    *,
    sha256: str | None = None,
    recorded_path: Path | None = None,
):
    content = artifact_path.read_bytes()
    return {
        "schema_version": "weather_model_replay_identity_v0.1",
        "market_id": market_id,
        "active_model_kind": "hgb",
        "artifact_files": [
            {
                "path": str((recorded_path or artifact_path).resolve()),
                "exists": True,
                "size": len(content),
                "sha256": sha256 or hashlib.sha256(content).hexdigest(),
            }
        ],
    }


def _write_artifact(
    path: Path,
    feature_names,
    *,
    wind_groups=(),
    cloud_groups=(),
    missing_hour=None,
    missing_feature_names_hour=None,
):
    payload = {
        "schema_version": "feature_model_hgb_v0.2",
        "trained_at": "2026-08-01T00:00:00+00:00",
    }
    for hour in EXPECTED_CUTOFF_HOURS:
        if hour == missing_hour:
            continue
        names = feature_names.get(hour, ()) if isinstance(feature_names, dict) else feature_names
        bundle = {
            "all_wind_groups": list(wind_groups),
            "all_cloud_groups": list(cloud_groups),
        }
        if hour != missing_feature_names_hour:
            bundle["feature_names"] = list(names)
        payload[str(hour)] = bundle
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pickle.dumps(payload))
    return path


def _write_market_rows(
    snapshot_root: Path,
    market_id: str,
    values,
    *,
    artifact_path: Path | None = None,
    model_identity=_CURRENT_ARTIFACT_IDENTITY,
    rows_per_date=(1, 1, 1),
    hours=EXPECTED_CUTOFF_HOURS,
):
    def identity_for(target_date, hour, index, snapshot_id):
        if callable(model_identity):
            return model_identity(target_date, hour, index, snapshot_id)
        if model_identity is not _CURRENT_ARTIFACT_IDENTITY:
            return model_identity
        if artifact_path is None or not artifact_path.is_file():
            return None
        return _model_identity_for_artifact(market_id, artifact_path)

    seen_by_hour = defaultdict(int)
    for target_date, row_count in zip(TARGET_DATES, rows_per_date, strict=True):
        slug = config_for_date(target_date, market_id).event_slug
        folder = snapshot_root / slug
        folder.mkdir(parents=True, exist_ok=True)
        rows = []
        snapshots = []
        for hour in hours:
            for _ in range(row_count):
                index = seen_by_hour[hour]
                seen_by_hour[hour] += 1
                feature_values = (
                    values(target_date, hour, index)
                    if callable(values)
                    else dict(values)
                )
                snapshot_id = f"{market_id}-{target_date.isoformat()}-{hour}-{index}"
                rows.append(
                    {
                        "snapshot_id": snapshot_id,
                        "event_slug": slug,
                        "target_date": target_date.isoformat(),
                        "cutoff_hour": hour,
                        **feature_values,
                    }
                )
                snapshots.append(
                    {
                        "snapshot_id": snapshot_id,
                        "event_slug": slug,
                        "model_identity": identity_for(
                            target_date,
                            hour,
                            index,
                            snapshot_id,
                        ),
                    }
                )
        (folder / "features.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows),
            encoding="utf-8",
        )
        (folder / "snapshots.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in snapshots),
            encoding="utf-8",
        )


def _coverage(payload, market_id, hour, feature):
    return next(
        row
        for row in payload["trained_feature_coverage"]
        if row["market_id"] == market_id
        and row["cutoff_hour"] == hour
        and row["feature"] == feature
    )


def _date_coverage(payload, market_id, target_date, hour, feature):
    return next(
        row
        for row in payload["trained_feature_daily_coverage"]
        if row["market_id"] == market_id
        and row["target_date"] == str(target_date)
        and row["cutoff_hour"] == hour
        and row["feature"] == feature
    )


def _day_arrival(payload, market_id, target_date, feature):
    return next(
        row
        for row in payload["trained_feature_day_arrival"]
        if row["market_id"] == market_id
        and row["target_date"] == str(target_date)
        and row["feature"] == feature
    )


def _artifact_paths(tmp_path, market_features):
    paths = {}
    for market_id, feature_names in market_features.items():
        suffix = spec_for_id(market_id).artifact_suffix
        paths[market_id] = _write_artifact(
            tmp_path / "artifacts" / f"feature_model_hgb{suffix}.pkl",
            feature_names,
        )
    return paths


def _known_defect_artifact_shape():
    dead_trained = [
        "rise_from_7am",
        "warming_rate_2h",
        "hours_at_peak",
        "dewpoint_c",
        "humidity",
        "pressure",
        "pressure_trend_3h",
        "wind_speed_kmh",
    ]
    surviving_trained = [
        "high_so_far",
        "current_temp",
        "forecast_high",
        "forecast_gap",
        "forecast_source_count",
        "forecast_disagreement",
    ]
    wind_groups = tuple(f"wind-{index}" for index in range(8))
    cloud_groups = tuple(f"cloud-{index}" for index in range(7))
    one_hot_names = [
        *(f"wind_{group}" for group in wind_groups),
        *(f"cloud_{group}" for group in cloud_groups),
    ]
    feature_names = [*dead_trained, *surviving_trained, *one_hot_names]
    assert len(feature_names) == 29
    return feature_names, wind_groups, cloud_groups


def _known_defect_survivor_values(*, forecast_high=27.0):
    return {
        "high_so_far": 25.0,
        "current_temp": 24.0,
        "onshore_flow": 0.0,
        "onshore_wind_speed_kmh": 0.0,
        "lake_breeze_proxy": 0.0,
        "forecast_high": forecast_high,
        "forecast_gap": 2.0,
        "forecast_source_count": 4,
        "forecast_disagreement": 1.5,
        # Categorical source presence is part of the trained input contract;
        # the one-hot values are derived only after these groups arrive.
        "wind_group": "wind-0",
        "cloud_group": "cloud-0",
    }


def test_gate_isolates_market_and_hour_and_uses_each_artifacts_feature_list(tmp_path):
    artifact_paths = {
        "toronto": _write_artifact(
            tmp_path / "artifacts" / "feature_model_hgb.pkl",
            ["pressure"],
        ),
        "miami": _write_artifact(
            tmp_path / "artifacts" / "feature_model_hgb_miami.pkl",
            {
                hour: ["pressure"] if hour == 12 else ["dewpoint_c"]
                for hour in EXPECTED_CUTOFF_HOURS
            },
        ),
    }
    snapshot_root = tmp_path / "snapshots"
    _write_market_rows(
        snapshot_root,
        "toronto",
        {"pressure": 994.25},
        artifact_path=artifact_paths["toronto"],
    )
    _write_market_rows(
        snapshot_root,
        "miami",
        lambda _date, hour, _index: {
            # Legacy names remain native-unit fields. Presence, not magnitude or
            # conversion, is the contract under test.
            "pressure": None if hour == 12 else 29.92,
            "dewpoint_c": 73.0,
        },
        artifact_path=artifact_paths["miami"],
    )

    payload = evaluate_gate(
        snapshot_root=snapshot_root,
        end_date=END_DATE,
        artifact_paths=artifact_paths,
        market_ids=("toronto", "miami"),
        generated_at=datetime(2026, 8, 6, tzinfo=timezone.utc),
    )

    assert payload["status"] == "BLOCK"
    blocked = [
        (row["market_id"], row["cutoff_hour"], row["feature"])
        for row in payload["trained_feature_coverage"]
        if row["decision"] == "BLOCK"
    ]
    assert blocked == [("miami", 12, "pressure")]
    assert _coverage(payload, "toronto", 12, "pressure")["populated_fraction"] == 1.0
    assert _coverage(payload, "miami", 11, "dewpoint_c")["populated_fraction"] == 1.0
    assert _coverage(payload, "miami", 12, "pressure")["populated_fraction"] == 0.0
    identities = {row["market_id"]: row for row in payload["serving_artifacts"]}
    assert identities["miami"]["trained_feature_names_by_hour"]["11"] == ["dewpoint_c"]
    assert identities["miami"]["trained_feature_names_by_hour"]["12"] == ["pressure"]


def test_newest_date_feature_outage_cannot_hide_in_healthy_window_average(tmp_path):
    artifact_paths = _artifact_paths(tmp_path, {"toronto": ["pressure"]})
    snapshot_root = tmp_path / "snapshots"
    _write_market_rows(
        snapshot_root,
        "toronto",
        lambda target_date, _hour, _index: {
            "pressure": None if target_date == END_DATE else 994.25,
        },
        artifact_path=artifact_paths["toronto"],
    )

    payload = evaluate_gate(
        snapshot_root=snapshot_root,
        end_date=END_DATE,
        artifact_paths=artifact_paths,
        market_ids=("toronto",),
    )

    # The three-day aggregate is healthy at the 0.25 floor, but a daily gate
    # must still catch the complete outage on the newest target date.
    aggregate = _coverage(payload, "toronto", 7, "pressure")
    assert aggregate["populated_fraction"] == pytest.approx(2 / 3)
    assert aggregate["decision"] == "PASS"
    assert _date_coverage(payload, "toronto", TARGET_DATES[0], 7, "pressure")[
        "decision"
    ] == "PASS"
    newest = _date_coverage(payload, "toronto", END_DATE, 7, "pressure")
    assert newest["populated_fraction"] == 0.0
    assert newest["decision"] == "BLOCK"
    assert newest["affects_current_verdict"] is False
    day_arrival = _day_arrival(payload, "toronto", END_DATE, "pressure")
    assert day_arrival["populated_count"] == 0
    assert day_arrival["decision"] == "BLOCK"
    assert day_arrival["affects_current_verdict"] is True
    assert payload["status"] == "BLOCK"
    assert payload["summary"]["blocking_current_day_trained_feature_count"] == 1


def test_sparse_per_hour_arrival_passes_when_feature_arrives_elsewhere_that_day(
    tmp_path,
):
    artifact_paths = _artifact_paths(tmp_path, {"toronto": ["forecast_high"]})
    snapshot_root = tmp_path / "snapshots"
    _write_market_rows(
        snapshot_root,
        "toronto",
        lambda target_date, hour, _index: {
            "forecast_high": (
                27.0 if target_date != END_DATE or hour == 12 else None
            ),
        },
        artifact_path=artifact_paths["toronto"],
    )

    payload = evaluate_gate(
        snapshot_root=snapshot_root,
        end_date=END_DATE,
        artifact_paths=artifact_paths,
        market_ids=("toronto",),
    )

    assert _date_coverage(payload, "toronto", END_DATE, 11, "forecast_high")[
        "decision"
    ] == "BLOCK"
    assert _date_coverage(payload, "toronto", END_DATE, 12, "forecast_high")[
        "decision"
    ] == "PASS"
    arrival = _day_arrival(payload, "toronto", END_DATE, "forecast_high")
    assert arrival["populated_count"] == 1
    assert arrival["cutoff_hours"] == list(EXPECTED_CUTOFF_HOURS)
    assert arrival["decision"] == "PASS"
    assert payload["summary"]["diagnostic_blocking_daily_hour_cell_count"] == 13
    assert payload["summary"]["blocking_current_day_trained_feature_count"] == 0
    assert payload["status"] == "PASS"


def test_missing_semantics_keep_zero_and_native_values_and_enforce_floor_boundary(tmp_path):
    features = [
        "onshore_flow",
        "forecast_source_count",
        "dewpoint_c",
        "pressure",
        "humidity",
    ]
    artifact_paths = _artifact_paths(tmp_path, {"miami": features})
    snapshot_root = tmp_path / "snapshots"

    floor = Fraction(str(TRAINED_FEATURE_POPULATION_FLOOR)).limit_denominator(100)
    multiplier = max(1, (3 + floor.denominator - 1) // floor.denominator)
    total_count = floor.denominator * multiplier
    floor_populated_count = floor.numerator * multiplier
    rows_per_date = (total_count - 2, 1, 1)

    def values(_target_date, _hour, index):
        return {
            "onshore_flow": False if index % 2 else 0.0,
            "forecast_source_count": 0,
            "dewpoint_c": 73.0,
            "pressure": 24.4 if index < floor_populated_count else "",
            "humidity": (
                65.0
                if index < max(0, floor_populated_count - 1)
                else (None if index % 2 else " NaN ")
            ),
        }

    _write_market_rows(
        snapshot_root,
        "miami",
        values,
        artifact_path=artifact_paths["miami"],
        rows_per_date=rows_per_date,
    )
    payload = evaluate_gate(
        snapshot_root=snapshot_root,
        end_date=END_DATE,
        artifact_paths=artifact_paths,
        market_ids=("miami",),
    )

    assert _coverage(payload, "miami", 7, "onshore_flow")["populated_fraction"] == 1.0
    assert _coverage(payload, "miami", 7, "forecast_source_count")["populated_fraction"] == 1.0
    assert _coverage(payload, "miami", 7, "dewpoint_c")["populated_fraction"] == 1.0
    pressure = _coverage(payload, "miami", 7, "pressure")
    assert pressure["populated_count"] == floor_populated_count
    assert pressure["populated_fraction"] == TRAINED_FEATURE_POPULATION_FLOOR
    assert pressure["decision"] == "PASS"
    humidity = _coverage(payload, "miami", 7, "humidity")
    assert humidity["populated_count"] == max(0, floor_populated_count - 1)
    assert humidity["null_count"] == total_count - max(0, floor_populated_count - 1)
    assert humidity["decision"] == "BLOCK"


def test_one_hot_columns_block_when_their_categorical_source_disappears(tmp_path):
    artifact_path = _write_artifact(
        tmp_path / "artifacts" / "feature_model_hgb.pkl",
        ["wind_N-NE", "cloud_Fair", "wind_speed_kmh", "future_direct_signal"],
        wind_groups=("N-NE",),
        cloud_groups=("Fair",),
    )
    snapshot_root = tmp_path / "snapshots"
    _write_market_rows(
        snapshot_root,
        "toronto",
        {
            "wind_group": None,
            "cloud_group": "",
            "wind_speed_kmh": None,
        },
        artifact_path=artifact_path,
    )
    payload = evaluate_gate(
        snapshot_root=snapshot_root,
        end_date=END_DATE,
        artifact_paths={"toronto": artifact_path},
        market_ids=("toronto",),
    )

    wind_one_hot = _coverage(payload, "toronto", 7, "wind_N-NE")
    cloud_one_hot = _coverage(payload, "toronto", 7, "cloud_Fair")
    assert wind_one_hot["source_kind"] == "derived_one_hot"
    assert wind_one_hot["populated_fraction"] == 0.0
    assert wind_one_hot["source_field_populated_count"] == 0
    assert wind_one_hot["decision"] == "BLOCK"
    assert cloud_one_hot["source_kind"] == "derived_one_hot"
    assert cloud_one_hot["populated_fraction"] == 0.0
    assert cloud_one_hot["source_field_populated_count"] == 0
    assert cloud_one_hot["decision"] == "BLOCK"
    assert _coverage(payload, "toronto", 7, "wind_speed_kmh")["decision"] == "BLOCK"
    assert _coverage(payload, "toronto", 7, "future_direct_signal")["decision"] == "BLOCK"


def test_one_hot_columns_use_source_presence_not_category_frequency(tmp_path):
    artifact_path = _write_artifact(
        tmp_path / "artifacts" / "feature_model_hgb.pkl",
        ["wind_N-NE", "wind_S-SW", "cloud_Fair"],
        wind_groups=("N-NE", "S-SW"),
        cloud_groups=("Fair",),
    )
    snapshot_root = tmp_path / "snapshots"
    _write_market_rows(
        snapshot_root,
        "toronto",
        {"wind_group": "N-NE", "cloud_group": "Fair"},
        artifact_path=artifact_path,
    )
    payload = evaluate_gate(
        snapshot_root=snapshot_root,
        end_date=END_DATE,
        artifact_paths={"toronto": artifact_path},
        market_ids=("toronto",),
    )

    # Both wind one-hots have complete input coverage even though only one
    # category is active in each row. Coverage judges arrival of wind_group,
    # not how often a particular category's encoded value equals one.
    for feature in ("wind_N-NE", "wind_S-SW", "cloud_Fair"):
        row = _coverage(payload, "toronto", 7, feature)
        assert row["source_field_populated_count"] == row["total_count"]
        assert row["populated_fraction"] == 1.0
        assert row["decision"] == "PASS"
    assert payload["status"] == "PASS"


@pytest.mark.parametrize(
    ("wind_speed", "expected_decision", "expected_supported"),
    [
        (0.0, "EXEMPT_ALLOWED_MISSING", True),
        (5.0, "EXEMPT_ALLOWED_MISSING", True),
        (None, "BLOCK", False),
        (5.01, "BLOCK", False),
    ],
)
def test_wind_gust_absence_requires_observed_calm_wind_support(
    tmp_path,
    wind_speed,
    expected_decision,
    expected_supported,
):
    artifact_paths = _artifact_paths(tmp_path, {"toronto": ["wind_gust_kmh"]})
    snapshot_root = tmp_path / "snapshots"
    _write_market_rows(
        snapshot_root,
        "toronto",
        {"wind_gust_kmh": None, "wind_speed_kmh": wind_speed},
        artifact_path=artifact_paths["toronto"],
    )
    payload = evaluate_gate(
        snapshot_root=snapshot_root,
        end_date=END_DATE,
        artifact_paths=artifact_paths,
        market_ids=("toronto",),
    )

    gust = _coverage(payload, "toronto", 7, "wind_gust_kmh")
    assert GUST_CALM_MAX_SUSTAINED_WIND_NATIVE == 5.0
    assert gust["populated_fraction"] == 0.0
    assert gust["decision"] == expected_decision
    assert gust["null_count"] == gust["total_count"]
    if expected_supported:
        assert gust["affirmative_calm_count"] == gust["total_count"]
        assert gust["unproven_calm_count"] == 0
        assert payload["status"] == "PASS"
    else:
        assert gust["affirmative_calm_count"] == 0
        assert gust["unproven_calm_count"] == gust["total_count"]
        assert payload["status"] == "BLOCK"


@pytest.mark.parametrize(
    ("failure_kind", "detail_fragment"),
    [
        ("missing", "cannot read serving artifact"),
        ("corrupt", "cannot deserialize serving artifact"),
        ("missing_hour", "has no hour 12 bundle"),
        ("missing_feature_names", "has no trained feature_names"),
    ],
)
def test_serving_artifact_failures_are_evidence_blockers(
    tmp_path,
    failure_kind,
    detail_fragment,
):
    artifact_path = tmp_path / "artifacts" / "feature_model_hgb.pkl"
    if failure_kind == "corrupt":
        artifact_path.parent.mkdir(parents=True)
        artifact_path.write_bytes(b"not a pickle")
    elif failure_kind == "missing_hour":
        _write_artifact(artifact_path, ["high_so_far"], missing_hour=12)
    elif failure_kind == "missing_feature_names":
        _write_artifact(
            artifact_path,
            ["high_so_far"],
            missing_feature_names_hour=12,
        )
    snapshot_root = tmp_path / "snapshots"
    _write_market_rows(
        snapshot_root,
        "toronto",
        {"high_so_far": 25.0},
        artifact_path=artifact_path,
    )

    payload = evaluate_gate(
        snapshot_root=snapshot_root,
        end_date=END_DATE,
        artifact_paths={"toronto": artifact_path},
        market_ids=("toronto",),
    )

    assert payload["status"] == "BLOCK"
    artifact_blockers = [
        row
        for row in payload["evidence_blockers"]
        if row["code"] == "serving_artifact_unusable"
    ]
    assert len(artifact_blockers) == 1
    assert detail_fragment in artifact_blockers[0]["detail"]
    assert payload["summary"]["loaded_artifact_market_count"] == 0


@pytest.mark.parametrize(
    ("failure_kind", "expected_reason"),
    [
        ("snapshot_file_missing", "snapshot_identity_file_missing"),
        ("model_identity_missing", "model_identity_missing"),
        ("model_identity_schema_mismatch", "model_identity_schema_invalid"),
        ("model_identity_market_missing", "model_identity_market_mismatch"),
        ("model_identity_market_mismatch", "model_identity_market_mismatch"),
        ("active_model_kind_missing", "active_model_kind_not_hgb"),
        ("active_model_kind_non_hgb", "active_model_kind_not_hgb"),
        ("artifact_path_mismatch", "hgb_descriptor_missing"),
        ("artifact_not_present", "hgb_descriptor_not_present"),
        ("artifact_sha_mismatch", "hgb_sha256_mismatch"),
        ("mixed_artifact_sha", "mixed_hgb_sha256"),
        ("duplicate_snapshot_id", "duplicate_snapshot_identity"),
    ],
)
def test_captured_rows_are_bound_to_the_evaluated_serving_artifact(
    tmp_path,
    failure_kind,
    expected_reason,
):
    artifact_paths = _artifact_paths(tmp_path, {"toronto": ["high_so_far"]})
    artifact_path = artifact_paths["toronto"]
    current_identity = _model_identity_for_artifact("toronto", artifact_path)
    # Basename equality is insufficient: a retained identity must point to the
    # exact evaluated artifact path, not a same-named pickle elsewhere.
    wrong_path = tmp_path / "other-artifacts" / artifact_path.name

    def captured_identity(target_date, _hour, index, _snapshot_id):
        if target_date != END_DATE:
            return current_identity
        if failure_kind == "model_identity_missing":
            return None
        if failure_kind == "model_identity_schema_mismatch":
            identity = json.loads(json.dumps(current_identity))
            identity["schema_version"] = "weather_model_replay_identity_v9"
            return identity
        if failure_kind == "model_identity_market_missing":
            identity = json.loads(json.dumps(current_identity))
            identity.pop("market_id")
            return identity
        if failure_kind == "model_identity_market_mismatch":
            identity = json.loads(json.dumps(current_identity))
            identity["market_id"] = "miami"
            return identity
        if failure_kind == "active_model_kind_missing":
            identity = json.loads(json.dumps(current_identity))
            identity.pop("active_model_kind")
            return identity
        if failure_kind == "active_model_kind_non_hgb":
            identity = json.loads(json.dumps(current_identity))
            identity["active_model_kind"] = "legacy"
            return identity
        if failure_kind == "artifact_path_mismatch":
            return _model_identity_for_artifact(
                "toronto",
                artifact_path,
                recorded_path=wrong_path,
            )
        if failure_kind == "artifact_not_present":
            identity = json.loads(json.dumps(current_identity))
            identity["artifact_files"][0]["exists"] = False
            return identity
        if failure_kind == "artifact_sha_mismatch":
            return _model_identity_for_artifact(
                "toronto",
                artifact_path,
                sha256="0" * 64,
            )
        if failure_kind == "mixed_artifact_sha" and index % 2:
            return _model_identity_for_artifact(
                "toronto",
                artifact_path,
                sha256="f" * 64,
            )
        return current_identity

    rows_per_date = (1, 1, 2) if failure_kind == "mixed_artifact_sha" else (1, 1, 1)
    snapshot_root = tmp_path / "snapshots"
    _write_market_rows(
        snapshot_root,
        "toronto",
        {"high_so_far": 25.0},
        artifact_path=artifact_path,
        model_identity=captured_identity,
        rows_per_date=rows_per_date,
    )
    if failure_kind == "snapshot_file_missing":
        slug = config_for_date(END_DATE, "toronto").event_slug
        (snapshot_root / slug / "snapshots.jsonl").unlink()
    elif failure_kind == "duplicate_snapshot_id":
        slug = config_for_date(END_DATE, "toronto").event_slug
        snapshot_path = snapshot_root / slug / "snapshots.jsonl"
        row = snapshot_path.read_text(encoding="utf-8")
        snapshot_path.write_text(row + row, encoding="utf-8")

    payload = evaluate_gate(
        snapshot_root=snapshot_root,
        end_date=END_DATE,
        artifact_paths=artifact_paths,
        market_ids=("toronto",),
    )

    identity_blockers = [
        row
        for row in payload["evidence_blockers"]
        if row["code"] == "captured_model_artifact_identity_unbound"
    ]
    assert any(row["reason"] == expected_reason for row in identity_blockers)
    assert payload["status"] == "BLOCK"
    assert _coverage(payload, "toronto", 7, "high_so_far")["total_count"] < sum(
        rows_per_date
    )


def test_snapshot_without_exact_feature_sidecar_row_blocks(tmp_path):
    artifact_paths = _artifact_paths(tmp_path, {"toronto": ["high_so_far"]})
    snapshot_root = tmp_path / "snapshots"
    _write_market_rows(
        snapshot_root,
        "toronto",
        {"high_so_far": 25.0},
        artifact_path=artifact_paths["toronto"],
    )

    slug = config_for_date(END_DATE, "toronto").event_slug
    feature_path = snapshot_root / slug / "features.jsonl"
    feature_rows = [
        json.loads(line)
        for line in feature_path.read_text(encoding="utf-8").splitlines()
    ]
    missing_snapshot_id = feature_rows[0]["snapshot_id"]
    feature_path.write_text(
        "".join(json.dumps(row) + "\n" for row in feature_rows[1:]),
        encoding="utf-8",
    )

    payload = evaluate_gate(
        snapshot_root=snapshot_root,
        end_date=END_DATE,
        artifact_paths=artifact_paths,
        market_ids=("toronto",),
    )

    assert payload["status"] == "BLOCK"
    blocker = next(
        row
        for row in payload["evidence_blockers"]
        if row["code"] == "captured_model_artifact_identity_unbound"
        and row["reason"] == "feature_sidecar_row_missing"
    )
    assert blocker["affected_row_count"] == 1
    assert blocker["example_snapshot_ids"] == [missing_snapshot_id]
    assert _coverage(payload, "toronto", 7, "high_so_far")["total_count"] == 2
    assert _day_arrival(payload, "toronto", END_DATE, "high_so_far")[
        "decision"
    ] == "PASS"


def test_verified_release_mode_requires_hashed_identity_bound_replay_lineage(
    tmp_path,
    monkeypatch,
):
    import tests.test_release_serving as release_fixture
    import weather.reporting.source_gates.model_input_surface_gate as gate_module
    from weather.captured_input_hash import (
        CAPTURED_INPUT_HASH_ALGORITHM,
        captured_input_payload_sha256,
    )
    from weather.release_contract import (
        RESEARCH_ONLY_CANDIDATE_MODE,
        SERVING_IDENTITY_BOOTSTRAP_RELEASE_KIND,
    )

    original_fixture = release_fixture._fixture

    def all_hours_release_fixture(fixture_root):
        paths = original_fixture(fixture_root)
        _write_artifact(paths["base_artifacts"]["feature_hgb"], ["high_so_far"])
        return paths

    monkeypatch.setattr(release_fixture, "_fixture", all_hours_release_fixture)
    paths, _frozen, _result, releases_root, pointer = release_fixture._active_fixture(
        tmp_path / "release-fixture",
        candidate_mode=RESEARCH_ONLY_CANDIDATE_MODE,
        release_kind=SERVING_IDENTITY_BOOTSTRAP_RELEASE_KIND,
        release_kind_provenance=release_fixture._bootstrap_provenance(),
    )
    bundle = release_fixture._load(pointer, releases_root, paths["repo"])
    monkeypatch.setattr(
        gate_module,
        "load_verified_active_serving_bundle",
        lambda **_kwargs: bundle,
    )

    snapshot_root = tmp_path / "snapshots"
    ambient_hgb = paths["base_artifacts"]["feature_hgb"]
    _write_market_rows(
        snapshot_root,
        "nyc",
        {"high_so_far": 80.0},
        artifact_path=ambient_hgb,
    )

    for target_date in TARGET_DATES:
        slug = config_for_date(target_date, "nyc").event_slug
        folder = snapshot_root / slug
        snapshots = [
            json.loads(line)
            for line in (folder / "snapshots.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        replay_rows = [
            {
                "schema_version": gate_module.REPLAY_INPUT_SCHEMA_VERSION,
                "snapshot_id": snapshot["snapshot_id"],
                "event_slug": slug,
                "target_date": target_date.isoformat(),
                "release_id": bundle.release_id,
                "release_manifest_sha256": bundle.manifest_sha256,
                "release_pointer_sha256": bundle.pointer_sha256,
                "release_sequence": bundle.sequence,
                "release_identity_status": "verified_variant_serving_bundle",
                "base_model_release_bound": True,
                "base_model_binding_reason": bundle.base_model_binding_reason,
                "model_identity": snapshot["model_identity"],
                "captured_input_hash_algorithm": CAPTURED_INPUT_HASH_ALGORITHM,
            }
            for snapshot in snapshots
        ]
        for replay_row in replay_rows:
            replay_row["captured_input_hash"] = captured_input_payload_sha256(
                replay_row,
                persisted=False,
            )
        (folder / "replay_inputs.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in replay_rows),
            encoding="utf-8",
        )

    evaluate_kwargs = {
        "snapshot_root": snapshot_root,
        "end_date": END_DATE,
        "artifact_root": ambient_hgb.parent,
        "active_release_pointer": pointer,
        "releases_root": releases_root,
        "market_ids": ("nyc",),
    }
    valid = evaluate_gate(**evaluate_kwargs)
    assert valid["serving_binding"]["mode"] == "verified_active_release"
    assert not valid["evidence_blockers"], [
        (row["code"], row.get("reason")) for row in valid["evidence_blockers"]
    ]
    assert valid["status"] == "PASS"

    newest_slug = config_for_date(END_DATE, "nyc").event_slug
    newest_lineage_path = snapshot_root / newest_slug / "replay_inputs.jsonl"
    newest_rows = [
        json.loads(line)
        for line in newest_lineage_path.read_text(encoding="utf-8").splitlines()
    ]

    def write_newest(rows):
        newest_lineage_path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows),
            encoding="utf-8",
        )

    def assert_blocked_for(reason):
        blocked = evaluate_gate(**evaluate_kwargs)
        assert blocked["status"] == "BLOCK"
        assert any(
            row["code"] == "captured_model_artifact_identity_unbound"
            and row["reason"] == reason
            for row in blocked["evidence_blockers"]
        )
        return blocked

    hash_tampered = json.loads(json.dumps(newest_rows))
    for row in hash_tampered:
        row["release_manifest_sha256"] = "0" * 64
    write_newest(hash_tampered)
    assert_blocked_for("captured_input_self_hash_invalid")

    lineage_mismatched = json.loads(json.dumps(newest_rows))
    for row in lineage_mismatched:
        row["release_manifest_sha256"] = "0" * 64
        row["captured_input_hash"] = captured_input_payload_sha256(
            row,
            persisted=True,
        )
    write_newest(lineage_mismatched)
    assert_blocked_for("release_lineage_mismatch")

    identity_mismatched = json.loads(json.dumps(newest_rows))
    for row in identity_mismatched:
        row["model_identity"]["identity_hash"] = "f" * 64
        row["captured_input_hash"] = captured_input_payload_sha256(
            row,
            persisted=True,
        )
    write_newest(identity_mismatched)
    identity_blocked = assert_blocked_for(
        "release_snapshot_model_identity_mismatch"
    )
    assert _coverage(identity_blocked, "nyc", 7, "high_so_far")[
        "total_count"
    ] == 2
    assert _date_coverage(identity_blocked, "nyc", END_DATE, 7, "high_so_far")[
        "decision"
    ] == "BLOCK"


def test_zero_captured_rows_fail_closed_for_every_expected_date_hour(tmp_path):
    artifact_paths = _artifact_paths(tmp_path, {"toronto": ["high_so_far"]})
    snapshot_root = tmp_path / "snapshots"
    _write_market_rows(
        snapshot_root,
        "toronto",
        {"high_so_far": 25.0},
        artifact_path=artifact_paths["toronto"],
        rows_per_date=(0, 0, 0),
    )

    payload = evaluate_gate(
        snapshot_root=snapshot_root,
        end_date=END_DATE,
        artifact_paths=artifact_paths,
        market_ids=("toronto",),
    )

    assert payload["status"] == "BLOCK"
    missing_slices = [
        row
        for row in payload["evidence_blockers"]
        if row["code"] == "captured_market_date_hour_missing"
    ]
    assert len(missing_slices) == 3 * len(EXPECTED_CUTOFF_HOURS)
    assert payload["summary"]["covered_market_date_hour_count"] == 0
    assert _coverage(payload, "toronto", 7, "high_so_far")["reason"] == (
        "no artifact-bound captured rows for expected slice"
    )


@pytest.mark.parametrize(
    "forbidden_args",
    [
        ["--population-floor", "0"],
        ["--market", "toronto"],
        ["--window-target-date-count", "1"],
        ["--allow-sparse-feature", "pressure"],
    ],
)
def test_cli_has_no_policy_surface_override(forbidden_args):
    parser = build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--end-date", END_DATE.isoformat(), *forbidden_args])

    assert exc_info.value.code == 2


def test_main_writes_dated_registered_json_and_uses_gate_exit_codes(tmp_path):
    snapshot_root = tmp_path / "snapshots"
    artifact_root = tmp_path / "artifacts"
    specs = all_specs()
    for spec in specs:
        artifact_path = _write_artifact(
            artifact_root / f"feature_model_hgb{spec.artifact_suffix}.pkl",
            ["high_so_far"],
        )
        _write_market_rows(
            snapshot_root,
            spec.id,
            {"high_so_far": 80.0},
            artifact_path=artifact_path,
        )
    output = tmp_path / default_output_path(END_DATE).name
    common_args = [
        "--end-date",
        END_DATE.isoformat(),
        "--snapshot-root",
        str(snapshot_root),
        "--artifact-root",
        str(artifact_root),
        "--active-release-pointer",
        str(tmp_path / "no-active-release.json"),
        "--releases-root",
        str(tmp_path / "releases"),
        "--output",
        str(output),
    ]

    assert main(common_args) == 0
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert output.name == "model-input-surface-gate-2026-08-05.json"
    assert persisted["schema_version"] == SCHEMA_VERSION
    assert persisted["artifact_date"] == END_DATE.isoformat()
    assert persisted["status"] == "PASS"
    assert persisted["summary"]["expected_market_count"] == len(specs)
    assert TRAINED_FEATURE_POPULATION_FLOOR == 0.25
    assert (
        persisted["policy"]["trained_feature_population_floor"]
        == TRAINED_FEATURE_POPULATION_FLOOR
    )
    assert persisted["policy"]["threshold_cli_override_supported"] is False
    assert persisted["policy"]["market_cli_override_supported"] is False
    assert persisted["policy"]["window_size_cli_override_supported"] is False

    # A single unusable serving artifact is enough to make the same standalone
    # command fail closed and return a non-zero gate code.
    toronto = next(spec for spec in specs if spec.id == "toronto")
    (artifact_root / f"feature_model_hgb{toronto.artifact_suffix}.pkl").write_bytes(
        b"corrupt"
    )
    blocked_output = tmp_path / "blocked.json"
    blocked_args = [
        *(common_args[:-1]),
        str(blocked_output),
    ]
    assert main(blocked_args) == 2
    assert json.loads(blocked_output.read_text(encoding="utf-8"))["status"] == "BLOCK"


def test_known_defect_positive_control_reports_ten_base_and_eight_trained_dead(tmp_path):
    feature_names, wind_groups, cloud_groups = _known_defect_artifact_shape()
    toronto_artifact = _write_artifact(
        tmp_path / "artifacts" / "feature_model_hgb.pkl",
        feature_names,
        wind_groups=wind_groups,
        cloud_groups=cloud_groups,
    )
    miami_artifact = _write_artifact(
        tmp_path / "artifacts" / "feature_model_hgb_miami.pkl",
        ["high_so_far"],
    )
    snapshot_root = tmp_path / "snapshots"
    survivor_values = _known_defect_survivor_values()
    _write_market_rows(
        snapshot_root,
        "toronto",
        survivor_values,
        artifact_path=toronto_artifact,
    )
    _write_market_rows(
        snapshot_root,
        "miami",
        survivor_values,
        artifact_path=miami_artifact,
    )

    payload = evaluate_gate(
        snapshot_root=snapshot_root,
        end_date=END_DATE,
        artifact_paths={"toronto": toronto_artifact, "miami": miami_artifact},
        market_ids=("toronto", "miami"),
        require_positive_control=True,
    )

    control = payload["positive_control"]
    assert control["reproduced"] is False
    assert control["base_feature_control_reproduced"] is True
    assert control["core_dead_input_control_reproduced"] is True
    assert control["evaluated_scope_survivor_range_matches_reference"] is True
    assert control["full_retained_range_reproduced_on_this_host"] is False
    assert control["reference_scope_market_ids_enumerated"] is False
    assert control["authoritative_scope"] is False
    assert control["required_control"] == "full_retained_range"
    assert control["market_ids"] == ["miami"]
    assert control["surviving_base_feature_count"] == 9
    assert control["surviving_base_feature_fraction_min"] == 1.0
    assert control["toronto_trained_8_of_29_all_hours_reproduced"] is True
    assert set(control["observed_uniform_zero_base_features"]) == {
        "rise_from_7am",
        "warming_rate_2h",
        "hours_at_peak",
        "dewpoint_c",
        "humidity",
        "pressure",
        "pressure_trend_3h",
        "wind_speed_kmh",
        "wind_gust_kmh",
        "wind_shift_3h_degrees",
    }
    assert len(BASE_FEATURES) == 19
    assert payload["summary"]["blocking_trained_feature_cell_count"] == (
        8 * len(EXPECTED_CUTOFF_HOURS)
    )
    assert any(
        row["code"] == "established_positive_control_not_reproduced"
        for row in payload["evidence_blockers"]
    )


def test_required_positive_control_fails_closed_without_exact_retained_scope_binding(tmp_path):
    feature_names, wind_groups, cloud_groups = _known_defect_artifact_shape()
    snapshot_root = tmp_path / "snapshots"
    artifact_root = tmp_path / "artifacts"
    specs = all_specs()

    for spec in specs:
        if spec.id == "toronto":
            artifact_path = _write_artifact(
                artifact_root / f"feature_model_hgb{spec.artifact_suffix}.pkl",
                feature_names,
                wind_groups=wind_groups,
                cloud_groups=cloud_groups,
            )
        else:
            artifact_path = _write_artifact(
                artifact_root / f"feature_model_hgb{spec.artifact_suffix}.pkl",
                ["high_so_far"],
            )

        # The ten dead fields still reproduce exactly, while one survivor is
        # present on only two of three target dates. That is enough for the core
        # defect proof, but not the retained 93.6--100% survivor range.
        _write_market_rows(
            snapshot_root,
            spec.id,
            lambda target_date, _hour, _index: _known_defect_survivor_values(
                forecast_high=None if target_date == END_DATE else 27.0
            ),
            artifact_path=artifact_path,
        )

    payload = evaluate_gate(
        snapshot_root=snapshot_root,
        end_date=END_DATE,
        artifact_root=artifact_root,
        active_release_pointer=tmp_path / "no-active-release.json",
        releases_root=tmp_path / "releases",
        market_ids=tuple(spec.id for spec in specs),
        require_positive_control=True,
    )

    control = payload["positive_control"]
    # Today's registered fleet cannot be presumed to equal a historical
    # 11-market retained corpus whose market IDs were never enumerated.
    assert control["reference_scope_market_ids_enumerated"] is False
    assert control["authoritative_scope"] is False
    assert control["required_control"] == "full_retained_range"
    assert control["core_dead_input_control_reproduced"] is True
    assert control["evaluated_scope_survivor_range_matches_reference"] is False
    assert control["full_retained_range_reproduced_on_this_host"] is False
    assert control["reproduced"] is False
    assert payload["status"] == "BLOCK"
    assert any(
        row["code"] == "established_positive_control_not_reproduced"
        for row in payload["evidence_blockers"]
    )
