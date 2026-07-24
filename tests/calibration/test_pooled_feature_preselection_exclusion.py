import csv
import hashlib
import json
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from weather.calibration import pooled_feature_assembly as assembly
from weather.calibration import pooled_feature_model as facade
from weather.market.market_registry import NYC
from weather.model.toronto_model import TorontoHighTempModel
from weather.reporting.validation.point_in_time_evaluation import build_window_lock
from weather.schema_registry import schema_version


def _source_row(high):
    return {"high": float(high), "bucket": int(high)}


def _production_preselection(fleet_dates):
    generated_at = f"{fleet_dates[-1]}T12:00:00+00:00"
    universe_sha256 = "1" * 64
    payload = {
        "schema_version": schema_version("production_point_in_time_preselection"),
        "artifact_type": "production_point_in_time_preselection",
        "generated_at_utc": generated_at,
        "status": "PASS",
        "candidate_selection_permission": "forbidden",
        "locked_before_candidate_training": True,
        "selection_universe": {
            "schema_version": schema_version("point_in_time_streaming_evaluation"),
            "hash_algorithm": "sha256",
            "canonicalization": "canonical_json_lines",
            "sha256": universe_sha256,
            "row_count": len(fleet_dates),
            "fleet_dates": list(fleet_dates),
            "candidate_dependent_fields_excluded": [],
        },
        "window_lock": build_window_lock(
            fleet_dates,
            input_sha256=universe_sha256,
            input_kind="selection_universe_sha256",
            window_days=14,
            window_end=fleet_dates[-1],
            generated_at_utc=generated_at,
        ),
    }
    payload["preselection_hash"] = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return payload


def _write_current_year_history(data_root, fleet_dates):
    summary_path = data_root / "daily" / "daily_summary.csv"
    summary_path.parent.mkdir(parents=True)
    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "schema_version",
                "local_date",
                "temperature_unit",
                "row_count",
                "max_temp_native",
                "max_temp_bucket_native",
            ),
        )
        writer.writeheader()
        for index, target_date in enumerate(fleet_dates):
            final_bucket = 80 + index % 5
            writer.writerow({
                "schema_version": "wu_daily_native_v2",
                "local_date": target_date,
                "temperature_unit": "F",
                "row_count": 24,
                "max_temp_native": final_bucket,
                "max_temp_bucket_native": final_bucket,
            })

    rows_by_month = {}
    for index, target_date in enumerate(fleet_dates):
        local_date = date.fromisoformat(target_date)
        final_bucket = 80 + index % 5
        rows_by_month.setdefault((local_date.year, local_date.month), []).extend([
            {
                "local_date": target_date,
                "local_time": "07:00",
                "temp_native": float(final_bucket - 5),
                "dewpoint_native": 60.0,
                "humidity": 65.0,
                "pressure": 1015.0,
                "wind_cardinal": "SW",
                "wind_speed_kmh": 8.0,
                "condition": "Fair",
                "clouds": "Clear",
            },
            {
                "local_date": target_date,
                "local_time": "12:00",
                "temp_native": float(final_bucket - 1),
                "dewpoint_native": 62.0,
                "humidity": 55.0,
                "pressure": 1012.0,
                "wind_cardinal": "SW",
                "wind_speed_kmh": 12.0,
                "condition": "Fair",
                "clouds": "Clear",
            },
        ])
    for (year, month), rows in rows_by_month.items():
        hourly_path = (
            data_root
            / "hourly"
            / f"year={year}"
            / f"month={month:02d}"
            / "observations.jsonl"
        )
        hourly_path.parent.mkdir(parents=True)
        with hourly_path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")


def _build_records_with_locked_label(
    locked_bucket,
    *,
    middle_bucket=82,
    excluded_target_dates=None,
    included_target_dates=None,
    prior_as_of_exclusive=None,
):
    first_date = date(2026, 1, 1)
    dates = [first_date + timedelta(days=offset) for offset in range(3)]
    locked_date = dates[-1]
    buckets = {
        dates[0]: 80,
        dates[1]: middle_bucket,
        locked_date: locked_bucket,
    }
    cache = {
        "daily": {
            local_date: {"bucket": bucket}
            for local_date, bucket in buckets.items()
        },
        "by_date": {local_date: [{}] for local_date in dates},
    }
    indexes = {
        assembly.PRIMARY_SOURCE: {
            local_date.isoformat(): _source_row(bucket)
            for local_date, bucket in buckets.items()
        },
        "ghcnh": {
            local_date.isoformat(): _source_row(value)
            for local_date, value in zip(dates, (81, 83, 85))
        },
    }
    model = SimpleNamespace(
        historical_target_cache=lambda coverage_target_dates=None: cache,
        wind_group=lambda *_args, **_kwargs: "Other/variable",
        cloud_group=lambda *_args, **_kwargs: "Other",
        microclimate_features=lambda *_args, **_kwargs: {},
    )

    def build_historical(local_date, _rows, daily_row, _hour, **_kwargs):
        bucket = daily_row["bucket"]
        return {
            "target_date": local_date.isoformat(),
            "final_bucket": bucket,
            "high_so_far": float(bucket - 1),
            "forecast_high": float(bucket),
            "minutes_since_cutoff": 0.0,
        }

    with (
        patch.object(assembly, "family_specs", return_value=[NYC]),
        patch.object(assembly, "TorontoHighTempModel", return_value=model),
        patch.object(assembly, "source_daily_indexes", return_value=indexes),
        patch.object(facade, "source_daily_indexes", return_value=indexes),
        patch.object(assembly, "load_forecast_daily", return_value={}),
        patch.object(assembly, "load_forecast_profiles", return_value={}),
        patch.object(assembly, "load_marine_water_contrast_features", return_value={}),
        patch.object(assembly, "load_reanalysis_synoptic_features", return_value={}),
        patch.object(assembly, "build_historical_feature_record", side_effect=build_historical),
    ):
        return assembly.build_family_dataset(
            unit="F",
            cutoff_hours=(12,),
            excluded_target_dates=excluded_target_dates,
            included_target_dates=included_target_dates,
            prior_as_of_exclusive=prior_as_of_exclusive,
        )


def test_locked_label_changes_cannot_reach_unlocked_rows_or_priors():
    locked_date = "2026-01-03"

    first_records, first_counts = _build_records_with_locked_label(
        84,
        excluded_target_dates={locked_date},
    )
    changed_records, changed_counts = _build_records_with_locked_label(
        100,
        excluded_target_dates={locked_date},
    )

    assert first_records == changed_records
    assert first_counts == changed_counts == {NYC.id: 2}
    assert {row["target_date"] for row in first_records} == {
        "2026-01-01",
        "2026-01-02",
    }
    assert all(row["climate_normal"] == 81.0 for row in first_records)
    assert all(row["source_overlap_days"] == 2.0 for row in first_records)

    research_first, _ = _build_records_with_locked_label(84)
    research_changed, _ = _build_records_with_locked_label(100)
    unlocked_first = [row for row in research_first if row["target_date"] != locked_date]
    unlocked_changed = [row for row in research_changed if row["target_date"] != locked_date]
    assert unlocked_first != unlocked_changed


def test_locked_dates_must_exist_in_the_preassembly_source_scope():
    with pytest.raises(
        ValueError,
        match="does not cover every locked evaluation date: 2026-01-04",
    ):
        _build_records_with_locked_label(
            84,
            excluded_target_dates={"2026-01-04"},
        )


def test_production_static_priors_use_only_preselection_history():
    kwargs = {
        "excluded_target_dates": {"2026-01-03"},
        "included_target_dates": {"2026-01-02", "2026-01-03"},
        "prior_as_of_exclusive": "2026-01-02",
    }
    first, _ = _build_records_with_locked_label(
        84,
        middle_bucket=82,
        **kwargs,
    )
    changed, _ = _build_records_with_locked_label(
        84,
        middle_bucket=100,
        **kwargs,
    )

    assert [row["target_date"] for row in first] == ["2026-01-02"]
    assert [row["target_date"] for row in changed] == ["2026-01-02"]
    assert first[0]["climate_normal"] == changed[0]["climate_normal"] == 80.0
    assert first[0]["source_overlap_days"] == changed[0]["source_overlap_days"] == 1.0


def test_current_year_fourteen_day_lock_assembles_and_trains_end_to_end(tmp_path):
    first_date = date(2026, 1, 1)
    fleet_dates = [
        (first_date + timedelta(days=offset)).isoformat()
        for offset in range(36)
    ]
    preselection = _production_preselection(fleet_dates)
    locked_dates = set(preselection["window_lock"]["target_dates"])
    data_root = tmp_path / "wunderground" / "klga"
    _write_current_year_history(data_root, fleet_dates)
    spec = SimpleNamespace(
        id=NYC.id,
        city_label=NYC.city_label,
        display_unit=NYC.display_unit,
        icao=NYC.icao,
        lat=NYC.lat,
        lon=NYC.lon,
        coastal=NYC.coastal,
        data_root=data_root,
        c_to_native=NYC.c_to_native,
    )
    model = TorontoHighTempModel(
        market_id=NYC.id,
        target_date="2026-12-31",
    )
    model.spec = spec

    try:
        TorontoHighTempModel.clear_historical_cache()
        with (
            patch.object(assembly, "family_specs", return_value=[spec]),
            patch.object(assembly, "TorontoHighTempModel", return_value=model),
            patch.object(assembly, "source_daily_indexes", return_value={}),
            patch.object(facade, "source_daily_indexes", return_value={}),
            patch.object(assembly, "load_forecast_daily", return_value={}),
            patch.object(assembly, "load_forecast_profiles", return_value={}),
            patch.object(
                assembly,
                "load_marine_water_contrast_features",
                return_value={},
            ),
            patch.object(
                assembly,
                "load_reanalysis_synoptic_features",
                return_value={},
            ),
        ):
            records, counts = assembly.build_family_dataset(
                unit="F",
                cutoff_hours=(12,),
                excluded_target_dates=locked_dates,
                included_target_dates=set(fleet_dates),
                prior_as_of_exclusive=fleet_dates[0],
            )

        expected_training_dates = set(fleet_dates) - locked_dates
        assert counts == {NYC.id: len(expected_training_dates)}
        assert {row["target_date"].isoformat() for row in records} == (
            expected_training_dates
        )
        assert all("date" not in row for row in records)

        artifact, _validation_rows = facade.train_pooled_band_models(
            records,
            holdout_year=None,
            production_preselection=preselection,
        )
        evidence = facade.verify_pooled_point_in_time_training_evidence(
            artifact
        )
        assert evidence["status"] == "PASS"
        assert not locked_dates & set(
            evidence["final_fit_receipt"]["train_dates"]
        )
    finally:
        TorontoHighTempModel.clear_historical_cache()
