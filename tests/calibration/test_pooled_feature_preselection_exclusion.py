from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from weather.calibration import pooled_feature_assembly as assembly
from weather.calibration import pooled_feature_model as facade
from weather.market.market_registry import NYC


def _source_row(high):
    return {"high": float(high), "bucket": int(high)}


def _build_records_with_locked_label(
    locked_bucket,
    *,
    middle_bucket=82,
    source_only_future_bucket=None,
    excluded_target_dates=None,
    included_target_dates=None,
    prior_as_of_exclusive=None,
    historical_window_target_date=None,
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
    if source_only_future_bucket is not None:
        indexes[assembly.PRIMARY_SOURCE]["2026-02-01"] = _source_row(80)
        indexes["ghcnh"]["2026-02-01"] = _source_row(
            source_only_future_bucket
        )
    model = SimpleNamespace(
        historical_target_cache=lambda: cache,
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
        patch.object(
            assembly, "TorontoHighTempModel", return_value=model
        ) as model_constructor,
        patch.object(assembly, "source_daily_indexes", return_value=indexes),
        patch.object(facade, "source_daily_indexes", return_value=indexes),
        patch.object(assembly, "load_forecast_daily", return_value={}),
        patch.object(assembly, "load_forecast_profiles", return_value={}),
        patch.object(assembly, "load_marine_water_contrast_features", return_value={}),
        patch.object(assembly, "load_reanalysis_synoptic_features", return_value={}),
        patch.object(assembly, "build_historical_feature_record", side_effect=build_historical),
    ):
        result = assembly.build_family_dataset(
            unit="F",
            cutoff_hours=(12,),
            excluded_target_dates=excluded_target_dates,
            included_target_dates=included_target_dates,
            prior_as_of_exclusive=prior_as_of_exclusive,
            historical_window_target_date=historical_window_target_date,
        )
    if historical_window_target_date is not None:
        model_constructor.assert_called_once_with(
            market_id=NYC.id,
            target_date=date.fromisoformat(str(historical_window_target_date)),
        )
    return result


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
        source_only_future_bucket=81,
        **kwargs,
    )
    changed, _ = _build_records_with_locked_label(
        84,
        middle_bucket=100,
        source_only_future_bucket=40,
        **kwargs,
    )

    assert [row["target_date"] for row in first] == ["2026-01-02"]
    assert [row["target_date"] for row in changed] == ["2026-01-02"]
    assert first[0]["climate_normal"] == changed[0]["climate_normal"] == 80.0
    assert first[0]["source_overlap_days"] == changed[0]["source_overlap_days"] == 1.0


def test_historical_window_uses_explicit_research_anchor():
    records, counts = _build_records_with_locked_label(
        84,
        historical_window_target_date="2026-07-22",
    )

    assert len(records) == 3
    assert counts == {NYC.id: 3}
